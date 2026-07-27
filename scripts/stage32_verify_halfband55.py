#!/usr/bin/env python3
"""Offline acceptance for the frozen Stage 32 55-tap Q1.17 half-band FIR."""

from __future__ import annotations

import json
import math
from pathlib import Path
import re
from typing import Iterable


FS_HZ = 320.0e6
PASSBAND_HZ = 64.0e6
STOPBAND_HZ = 96.0e6
FRAC_BITS = 17
COEFF_ID = 0xAA16_0055
COEFFS_Q17 = [
    -8, 0, 27, 0, -67, 0, 144, 0, -277, 0, 490, 0, -817, 0,
    1301, 0, -2006, 0, 3043, 0, -4631, 0, 7343, 0, -13284, 0,
    41510, 65536, 41510, 0, -13284, 0, 7343, 0, -4631, 0, 3043, 0,
    -2006, 0, 1301, 0, -817, 0, 490, 0, -277, 0, 144, 0, -67, 0,
    27, 0, -8,
]


def _db20(value: float) -> float:
    return 20.0 * math.log10(max(abs(value), 1.0e-15))


def _response(freq_hz: float) -> float:
    center = (len(COEFFS_Q17) - 1) // 2
    omega = 2.0 * math.pi * freq_hz / FS_HZ
    real = 0.0
    imag = 0.0
    for index, coefficient in enumerate(COEFFS_Q17):
        tap = coefficient / float(1 << FRAC_BITS)
        phase = -omega * (index - center)
        real += tap * math.cos(phase)
        imag += tap * math.sin(phase)
    return math.hypot(real, imag)


def _sweep(start_hz: float, stop_hz: float, count: int) -> Iterable[float]:
    for index in range(count):
        yield start_hz + (stop_hz - start_hz) * index / float(max(count - 1, 1))


def _round_q17(accumulator: int) -> int:
    if accumulator >= 0:
        return (accumulator + (1 << (FRAC_BITS - 1))) >> FRAC_BITS
    return -(((-accumulator) + (1 << (FRAC_BITS - 1))) >> FRAC_BITS)


def _fixed_point_tone_attenuation_db(
    frequency_hz: float,
    *,
    amplitude: int = 30_000,
    samples: int = 8192,
    phases: int = 8,
) -> float:
    """Return the least attenuation over several input phases.

    This mirrors the RTL's integer products, Q1.17 accumulator scaling and
    round-away-from-zero output quantizer.  A large but non-clipping input
    makes the result sensitive to the actual 16-bit output floor.
    """
    least_attenuation_db = float("inf")
    history = len(COEFFS_Q17) - 1
    for phase_index in range(phases):
        phase = 2.0 * math.pi * phase_index / phases
        values = [
            round(
                amplitude
                * math.sin(2.0 * math.pi * frequency_hz * index / FS_HZ + phase)
            )
            for index in range(samples + history)
        ]
        output_energy = 0
        input_energy = 0
        for index in range(history, len(values)):
            accumulator = sum(
                coefficient * values[index - tap]
                for tap, coefficient in enumerate(COEFFS_Q17)
            )
            output = _round_q17(accumulator)
            output_energy += output * output
            input_energy += values[index] * values[index]
        ratio = math.sqrt(output_energy / max(input_energy, 1))
        attenuation_db = -_db20(ratio)
        least_attenuation_db = min(least_attenuation_db, attenuation_db)
    return least_attenuation_db


def main() -> int:
    rtl_path = Path("rtl/science_decim2_halfband_aa.sv")
    rtl = rtl_path.read_text(encoding="utf-8")
    passband = [_db20(_response(freq)) for freq in _sweep(0.0, PASSBAND_HZ, 8001)]
    stopband_frequencies = list(_sweep(STOPBAND_HZ, FS_HZ / 2.0, 8001))
    stopband = [_db20(_response(freq)) for freq in stopband_frequencies]
    worst_stopband_index = stopband.index(max(stopband))
    worst_stopband_frequency_hz = stopband_frequencies[worst_stopband_index]
    fixed_point_stopband_attenuation_db = _fixed_point_tone_attenuation_db(
        worst_stopband_frequency_hz
    )
    rtl_offsets = {
        int(offset): (-1 if sign == "-" else 1) * int(value)
        for offset, sign, value in re.findall(
            r"(\d+):\s+coeff_for_odd_offset\s*=\s*"
            r"(-?)18'sd(\d+)",
            rtl,
        )
    }
    expected_offsets = {
        offset: COEFFS_Q17[(len(COEFFS_Q17) // 2) + offset]
        for offset in range(1, 28, 2)
    }
    checks = {
        "tap_count": len(COEFFS_Q17) == 55,
        "group_delay": (len(COEFFS_Q17) - 1) // 2 == 27,
        "dc_gain_exact": sum(COEFFS_Q17) == (1 << FRAC_BITS),
        "passband_ripple": max(passband) - min(passband) <= 0.1,
        "stopband_attenuation": -max(stopband) >= 80.0,
        "fixed_point_stopband": fixed_point_stopband_attenuation_db >= 80.0,
        "rtl_coefficients": rtl_offsets == expected_offsets,
        "rtl_coeff_id": "32'hAA16_0055" in rtl,
        "rtl_pipelined_tree": all(
            name in rtl for name in ("product_pipe", "sum_l1", "sum_l2", "sum_l3", "sum_l4")
        ),
    }
    result = {
        "classification": (
            "STAGE32_HALFBAND55_OFFLINE_PASS"
            if all(checks.values())
            else "STAGE32_HALFBAND55_OFFLINE_FAIL"
        ),
        "ok": all(checks.values()),
        "checks": checks,
        "sample_rate_hz": int(FS_HZ),
        "passband_hz": int(PASSBAND_HZ),
        "stopband_hz": int(STOPBAND_HZ),
        "tap_count": len(COEFFS_Q17),
        "group_delay_base_samples": (len(COEFFS_Q17) - 1) // 2,
        "frac_bits": FRAC_BITS,
        "coeff_id": f"0x{COEFF_ID:08x}",
        "dc_gain_q17_sum": sum(COEFFS_Q17),
        "passband_ripple_db": max(passband) - min(passband),
        "stopband_attenuation_db": -max(stopband),
        "fixed_point_stopband_attenuation_db": fixed_point_stopband_attenuation_db,
        "fixed_point_stopband_frequency_hz": int(worst_stopband_frequency_hz),
        "fixed_point_tone_amplitude": 30_000,
        "fixed_point_tone_phases": 8,
        "fixed_point_tone_samples_per_phase": 8192,
        "rtl": str(rtl_path),
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
