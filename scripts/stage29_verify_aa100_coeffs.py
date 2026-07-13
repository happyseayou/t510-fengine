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
    0, -87, 0, 240, 0, -513, 0, 958, 0, -1645, 0, 2690, 0, -4317,
    0, 7096, 0, -13128, 0, 41466, 65552, 41466, 0, -13128, 0, 7096,
    0, -4317, 0, 2690, 0, -1645, 0, 958, 0, -513, 0, 240, 0, -87, 0,
]


def _db20(value: float) -> float:
    return 20.0 * math.log10(max(abs(value), 1.0e-15))


def _response(freq_hz: float) -> float:
    center = (len(COEFFS_Q17) - 1) // 2
    omega = 2.0 * math.pi * freq_hz / FS_HZ
    re = 0.0
    im = 0.0
    for index, coefficient in enumerate(COEFFS_Q17):
        tap = coefficient / float(1 << FRAC_BITS)
        phase = -omega * (index - center)
        re += tap * math.cos(phase)
        im += tap * math.sin(phase)
    return math.hypot(re, im)


def _sweep(start_hz: float, stop_hz: float, count: int) -> Iterable[float]:
    for index in range(count):
        yield start_hz + (stop_hz - start_hz) * index / float(max(count - 1, 1))


def main() -> int:
    passband = [_db20(_response(freq)) for freq in _sweep(0.0, PASSBAND_HZ, 2001)]
    stopband = [_db20(_response(freq)) for freq in _sweep(STOPBAND_HZ, FS_HZ / 2.0, 2001)]
    result = {
        "stage": 29,
        "tap_count": len(COEFFS_Q17),
        "frac_bits": FRAC_BITS,
        "dc_gain_q17_sum": sum(COEFFS_Q17),
        "passband_ripple_db": max(passband) - min(passband),
        "stopband_attenuation_db": -max(stopband),
    }
    result["pass"] = (
        result["passband_ripple_db"] <= 0.25
        and result["stopband_attenuation_db"] >= 55.0
        and result["dc_gain_q17_sum"] == (1 << FRAC_BITS)
        and result["tap_count"] == 41
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
