from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
import zlib


CORE_VERSION_V36 = 0x0001_0036
RAW_COMPLEX_SAMPLE_RATE_HZ = 320_000_000.0
PHASE_MODULUS = 1 << 48
SPUR_RF_HZ: dict[int, float] = {
    1: 480_000_000.0,
    2: 960_000_000.0,
    3: 1_440_000_000.0,
}
SPUR_PROFILE_ID = 0x36E8_0001
Q8_16_SCALE = 1 << 16
Q8_16_MIN = -(1 << 23)
Q8_16_MAX = (1 << 23) - 1


def find_in_band_spur(center_hz: float, selected_sample_rate_hz: float) -> dict[str, Any] | None:
    """Return the unique interleave spur strictly inside the selected window."""

    center_hz = float(center_hz)
    half_band = float(selected_sample_rate_hz) / 2.0
    matches = [
        (spur_id, rf_hz)
        for spur_id, rf_hz in SPUR_RF_HZ.items()
        if abs(rf_hz - center_hz) < half_band
    ]
    if len(matches) > 1:
        raise RuntimeError(f"more than one fixed ADC interleave spur is in-band: {matches}")
    if not matches:
        return None
    spur_id, rf_hz = matches[0]
    return {
        "spur_id": int(spur_id),
        "ocb1_dft_k": int(spur_id),
        "rf_hz": float(rf_hz),
        "offset_hz": float(rf_hz - center_hz),
    }


def phase_step_u48(offset_hz: float) -> int:
    return int(round(float(offset_hz) / RAW_COMPLEX_SAMPLE_RATE_HZ * PHASE_MODULUS)) % PHASE_MODULUS


def phase_step_signed(step_u48: int) -> int:
    value = int(step_u48) & (PHASE_MODULUS - 1)
    return value - PHASE_MODULUS if value & (1 << 47) else value


def phase_seed_u48(step_u48: int, raw_sample0: int) -> int:
    return (int(step_u48) * int(raw_sample0)) & (PHASE_MODULUS - 1)


def ocb1_dft(coefficients: Sequence[int]) -> dict[int, complex]:
    if len(coefficients) != 8:
        raise ValueError("OCB1 DFT requires exactly eight time-interleave coefficients")
    result: dict[int, complex] = {}
    for k in range(1, 5):
        value = sum(
            int(coefficients[n]) * complex(
                math.cos(-2.0 * math.pi * k * n / 8.0),
                math.sin(-2.0 * math.pi * k * n / 8.0),
            )
            for n in range(8)
        ) / 8.0
        result[k] = value
    return result


def apply_ocb_tracking_matrix(
    c0: complex,
    d: complex,
    d0: complex,
    matrix_2x2: Sequence[Sequence[float]],
) -> complex:
    if len(matrix_2x2) != 2 or any(len(row) != 2 for row in matrix_2x2):
        raise ValueError("OCB tracking matrix must be real 2x2")
    delta = complex(d) - complex(d0)
    real = float(c0.real) + float(matrix_2x2[0][0]) * delta.real + float(matrix_2x2[0][1]) * delta.imag
    imag = float(c0.imag) + float(matrix_2x2[1][0]) * delta.real + float(matrix_2x2[1][1]) * delta.imag
    return complex(real, imag)


def quantize_q8_16(value: complex) -> tuple[int, int]:
    def quantize(component: float) -> int:
        code = int(round(float(component) * Q8_16_SCALE))
        if not Q8_16_MIN <= code <= Q8_16_MAX:
            raise OverflowError(f"spur correction coefficient {component} exceeds Q8.16 range")
        return code

    return quantize(value.real), quantize(value.imag)


def dequantize_q8_16(value: Sequence[int]) -> complex:
    if len(value) != 2:
        raise ValueError("Q8.16 complex value must have real and imaginary components")
    return complex(int(value[0]) / Q8_16_SCALE, int(value[1]) / Q8_16_SCALE)


def coefficient_crc32(values: Iterable[Sequence[int]]) -> int:
    payload = bytearray()
    count = 0
    for pair in values:
        if len(pair) != 2:
            raise ValueError("each correction coefficient must have two components")
        for component in pair:
            code = int(component)
            if not Q8_16_MIN <= code <= Q8_16_MAX:
                raise ValueError("coefficient is outside signed 24-bit Q8.16")
            payload.extend(int(code & 0x00FF_FFFF).to_bytes(4, "little", signed=False))
        count += 1
    if count != 8:
        raise ValueError("coefficient CRC requires exactly eight complex values")
    return zlib.crc32(payload) & 0xFFFF_FFFF


def hardware_phasor(step_u48: int, sample_indices: Any) -> Any:
    """Return the exact 1024-entry/Q1.17 phasor implemented by the RTL."""
    values = []
    step = int(step_u48) & (PHASE_MODULUS - 1)
    for sample in sample_indices:
        table_index = ((int(sample) * step) & (PHASE_MODULUS - 1)) >> 38
        sin_code = round(math.sin(2.0 * math.pi * table_index / 1024.0) * 131071.0)
        cos_index = (table_index + 256) & 1023
        cos_code = round(math.sin(2.0 * math.pi * cos_index / 1024.0) * 131071.0)
        values.append(complex(cos_code / 131072.0, sin_code / 131072.0))
    return values


def estimate_preview_vector(
    iq: Any,
    *,
    sample0: int,
    step_u48: int,
    phase_origin_sample0: int = 0,
) -> complex:
    pairs = iq.tolist() if hasattr(iq, "tolist") else list(iq)
    if not pairs or any(len(pair) != 2 for pair in pairs):
        raise ValueError("preview IQ must have shape (nsample, 2)")
    reference = hardware_phasor(
        step_u48,
        (
            int(sample0) + index - int(phase_origin_sample0)
            for index in range(len(pairs))
        ),
    )
    total = sum(
        complex(float(pair[0]), float(pair[1])) * phasor.conjugate()
        for pair, phasor in zip(pairs, reference)
    )
    normalization = sum(abs(phasor) ** 2 for phasor in reference)
    if normalization <= 0.0:
        raise ValueError("preview correlation reference has zero power")
    return total / normalization


def fit_real_2x2(d_values: Sequence[complex], c_values: Sequence[complex]) -> list[list[float]]:
    """Least-squares fit of C-C0 = M(D-D0) using a real 2x2 matrix."""
    if len(d_values) != len(c_values) or len(d_values) < 3:
        raise ValueError("2x2 OCB tracking fit requires at least three paired observations")
    # Center on the ensemble means.  The first preview is not privileged and
    # using it as the origin would unnecessarily transfer one preview's noise
    # into every fitted update.
    d0 = sum((complex(value) for value in d_values), 0j) / len(d_values)
    c0 = sum((complex(value) for value in c_values), 0j) / len(c_values)
    rows = [
        (
            (complex(d).real - d0.real),
            (complex(d).imag - d0.imag),
            (complex(c).real - c0.real),
            (complex(c).imag - c0.imag),
        )
        for d, c in zip(d_values, c_values)
    ]
    xx = sum(row[0] * row[0] for row in rows)
    xy = sum(row[0] * row[1] for row in rows)
    yy = sum(row[1] * row[1] for row in rows)
    determinant = xx * yy - xy * xy
    scale = max(xx * yy, 1.0)
    if abs(determinant) <= 1.0e-12 * scale:
        raise ValueError("OCB tracking observations do not span a two-dimensional fit")

    def solve(target_index: int) -> list[float]:
        xt = sum(row[0] * row[target_index] for row in rows)
        yt = sum(row[1] * row[target_index] for row in rows)
        return [
            (yy * xt - xy * yt) / determinant,
            (xx * yt - xy * xt) / determinant,
        ]

    return [solve(2), solve(3)]


def canonical_sha256(value: Mapping[str, Any]) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class LaneSpurModel:
    c0: complex
    d0: complex
    matrix_2x2: tuple[tuple[float, float], tuple[float, float]]

    def tracked(self, d: complex) -> complex:
        return apply_ocb_tracking_matrix(self.c0, d, self.d0, self.matrix_2x2)

    def to_json(self) -> dict[str, Any]:
        return {
            "c0": [self.c0.real, self.c0.imag],
            "d0": [self.d0.real, self.d0.imag],
            "matrix_2x2": [list(row) for row in self.matrix_2x2],
        }

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> "LaneSpurModel":
        return cls(
            c0=complex(*value["c0"]),
            d0=complex(*value["d0"]),
            matrix_2x2=tuple(tuple(float(item) for item in row) for row in value["matrix_2x2"]),  # type: ignore[arg-type]
        )


def load_model(path: str | Path) -> dict[str, Any]:
    model_path = Path(path)
    value = json.loads(model_path.read_text(encoding="utf-8"))
    expected = str(value.get("sha256", ""))
    unsigned = {key: item for key, item in value.items() if key != "sha256"}
    actual = canonical_sha256(unsigned)
    if not expected or expected != actual:
        raise ValueError(f"spur model SHA256 mismatch: expected={expected!r} actual={actual}")
    return value


def save_model(path: str | Path, value: Mapping[str, Any]) -> dict[str, Any]:
    model_path = Path(path)
    unsigned = {key: item for key, item in dict(value).items() if key != "sha256"}
    frozen = {**unsigned, "sha256": canonical_sha256(unsigned)}
    model_path.parent.mkdir(parents=True, exist_ok=True)
    model_path.write_text(json.dumps(frozen, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return frozen
