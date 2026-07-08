#!/usr/bin/env python3
from __future__ import annotations

import json
import math
from typing import Iterable


FS_HZ = 245.76e6
PASSBAND_HZ = 50.0e6
STOPBAND_HZ = 72.88e6
FRAC_BITS = 17
COEFFS_Q17 = [
    0,
    -87,
    0,
    240,
    0,
    -513,
    0,
    958,
    0,
    -1645,
    0,
    2690,
    0,
    -4317,
    0,
    7096,
    0,
    -13128,
    0,
    41466,
    65552,
    41466,
    0,
    -13128,
    0,
    7096,
    0,
    -4317,
    0,
    2690,
    0,
    -1645,
    0,
    958,
    0,
    -513,
    0,
    240,
    0,
    -87,
    0,
]


def db20(value: float) -> float:
    return 20.0 * math.log10(max(abs(value), 1.0e-15))


def response(freq_hz: float) -> float:
    center = (len(COEFFS_Q17) - 1) // 2
    omega = 2.0 * math.pi * freq_hz / FS_HZ
    re = 0.0
    im = 0.0
    for idx, coeff in enumerate(COEFFS_Q17):
        tap = coeff / float(1 << FRAC_BITS)
        phase = -omega * (idx - center)
        re += tap * math.cos(phase)
        im += tap * math.sin(phase)
    return math.hypot(re, im)


def sweep(start_hz: float, stop_hz: float, count: int) -> Iterable[float]:
    if count <= 1:
        yield start_hz
        return
    for idx in range(count):
        yield start_hz + (stop_hz - start_hz) * idx / float(count - 1)


def main() -> int:
    pass_vals = [db20(response(freq)) for freq in sweep(0.0, PASSBAND_HZ, 2001)]
    stop_vals = [db20(response(freq)) for freq in sweep(STOPBAND_HZ, FS_HZ / 2.0, 2001)]
    result = {
        "tap_count": len(COEFFS_Q17),
        "frac_bits": FRAC_BITS,
        "dc_gain_q17_sum": sum(COEFFS_Q17),
        "passband_hz": PASSBAND_HZ,
        "stopband_hz": STOPBAND_HZ,
        "passband_min_db": min(pass_vals),
        "passband_max_db": max(pass_vals),
        "passband_ripple_db": max(pass_vals) - min(pass_vals),
        "stopband_max_db": max(stop_vals),
        "stopband_attenuation_db": -max(stop_vals),
        "pass": (max(pass_vals) - min(pass_vals) <= 0.25) and (-max(stop_vals) >= 55.0) and sum(COEFFS_Q17) == (1 << FRAC_BITS),
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
