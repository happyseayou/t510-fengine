#!/usr/bin/env python3
"""Production-coefficient equivalent 8-tap PFB white-noise correlation model."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import struct
import zlib
from pathlib import Path


NCHAN = 4096
TAPS = 8
COEFF_SCALE = 131072
EXPECTED_PROFILE_ID = 0x34A80001
EXPECTED_CRC32 = 0xB9BA227C


def coefficients_for_phase(phase: int) -> list[int]:
    values = []
    for tap in range(TAPS):
        sample = tap * NCHAN + phase
        x = (sample - 16383.5) / NCHAN
        sinc = 1.0 if abs(x) < 1.0e-15 else math.sin(math.pi * x) / (math.pi * x)
        window = 0.54 - 0.46 * math.cos(2.0 * math.pi * sample / 32767.0)
        values.append(sinc * window)
    phase_sum = sum(values)
    quantized = []
    for value in values:
        scaled = value / phase_sum * COEFF_SCALE
        rounded = int(scaled + 0.5) if scaled >= 0.0 else int(scaled - 0.5)
        quantized.append(max(-131072, min(131071, rounded)))
    delta = COEFF_SCALE - sum(quantized)
    eligible = [
        tap
        for tap in range(TAPS)
        if (delta > 0 and quantized[tap] < 131071)
        or (delta < 0 and quantized[tap] > -131072)
        or delta == 0
    ]
    strongest = max(eligible, key=lambda tap: abs(values[tap]))
    quantized[strongest] += delta
    return quantized


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-json", type=Path, required=True)
    args = parser.parse_args()
    if args.output_json.exists():
        raise RuntimeError(f"refusing to overwrite {args.output_json}")

    by_phase = [coefficients_for_phase(phase) for phase in range(NCHAN)]
    if any(sum(values) != COEFF_SCALE for values in by_phase):
        raise RuntimeError("quantized production coefficient phase normalization failed")
    coefficient_stream = bytearray()
    for tap in range(TAPS):
        for phase in range(NCHAN):
            coefficient_stream.extend(struct.pack("<I", by_phase[phase][tap] & 0x3FFFF))
    crc32 = zlib.crc32(coefficient_stream)
    if crc32 != EXPECTED_CRC32:
        raise RuntimeError(f"production coefficient CRC mismatch: 0x{crc32:08x}")

    lag_rows = []
    total_variance = sum(value * value for phase in by_phase for value in phase)
    for lag in range(1, TAPS):
        phase_voltage = []
        total_covariance = 0
        for values in by_phase:
            variance = sum(value * value for value in values)
            covariance = sum(values[tap] * values[tap + lag] for tap in range(TAPS - lag))
            phase_voltage.append(covariance / variance)
            total_covariance += covariance
        aggregate_voltage = total_covariance / total_variance
        lag_rows.append(
            {
                "lag_frames": lag,
                "lag_microseconds": lag * 12.8,
                "aggregate_complex_voltage_correlation": aggregate_voltage,
                "aggregate_power_correlation": aggregate_voltage * aggregate_voltage,
                "phase_voltage_correlation_min": min(phase_voltage),
                "phase_voltage_correlation_max": max(phase_voltage),
            }
        )

    source = Path(__file__).resolve()
    result = {
        "format": "T510_STAGE35_PFB_WHITE_MODEL_V1",
        "schema_version": 1,
        "status": "PASS",
        "model": "analytic proper-complex white noise through the exact quantized production 4096-channel 8-tap prototype coefficients",
        "coefficient_identity": {
            "profile_id": f"0x{EXPECTED_PROFILE_ID:08x}",
            "taps": TAPS,
            "phases": NCHAN,
            "count": TAPS * NCHAN,
            "scale": COEFF_SCALE,
            "crc32": f"0x{crc32:08x}",
            "expected_crc32": f"0x{EXPECTED_CRC32:08x}",
            "all_phase_sums_exact": True,
        },
        "derivation": (
            "For lag l, complex-voltage rho is sum_phase,tap(c[p,t]*c[p,t+l]) / "
            "sum_phase,tap(c[p,t]^2). For proper complex Gaussian white input, same-bin "
            "power correlation is |rho|^2; the same-channel FFT phase factors cancel."
        ),
        "frame_interval_microseconds": 12.8,
        "lags": lag_rows,
        "applicability": (
            "This is an equivalent unsaturated white-noise baseline using bit-exact 18-bit "
            "prototype coefficients. It excludes finite IQ16 output rounding/saturation and is "
            "not a claim about the colored 32-frame hardware replay fixture."
        ),
        "generator": {"path": str(source), "sha256": sha256_file(source)},
    }
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    with args.output_json.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(
        f"STAGE35_PFB_WHITE_MODEL_PASS crc32=0x{crc32:08x} "
        f"lag1_power={lag_rows[0]['aggregate_power_correlation']:.12g} output={args.output_json}"
    )


if __name__ == "__main__":
    main()
