#!/usr/bin/env python3
"""Compare two Stage 31 captures in waveform or F-engine voltage space.

Input files are NumPy .npy arrays or .npz archives.  Waveform arrays contain
complex samples (or a final I/Q dimension of length two).  F-engine arrays are
complex [frame, channel] voltages; detected powers cannot be used for phase.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np


def load_complex(path: str, key: str | None) -> np.ndarray:
    value = np.load(path)
    if isinstance(value, np.lib.npyio.NpzFile):
        selected = key or (value.files[0] if len(value.files) == 1 else None)
        if selected is None or selected not in value.files:
            raise ValueError(f"{path}: choose one of the NPZ keys {value.files} with --key-a/--key-b")
        array = np.asarray(value[selected])
    else:
        array = np.asarray(value)
    if not np.iscomplexobj(array):
        if array.ndim == 0 or array.shape[-1] != 2:
            raise ValueError(f"{path}: expected complex data or a final I/Q dimension of length two")
        array = array[..., 0].astype(np.float64) + 1j * array[..., 1].astype(np.float64)
    return np.asarray(array, dtype=np.complex128)


def coherence(a: np.ndarray, b: np.ndarray) -> tuple[complex, float]:
    cross = np.sum(a * np.conj(b))
    denom = np.sqrt(np.sum(np.abs(a) ** 2) * np.sum(np.abs(b) ** 2))
    return complex(cross), float(abs(cross) / denom) if denom > 0 else 0.0


def waveform_result(a: np.ndarray, b: np.ndarray, max_lag: int, sample_rate_hz: float) -> dict[str, Any]:
    a = a.reshape(-1)
    b = b.reshape(-1)
    best: tuple[float, int, complex, float] | None = None
    for lag in range(-max_lag, max_lag + 1):
        if lag >= 0:
            aa, bb = a[: min(a.size, b.size - lag)], b[lag : lag + min(a.size, b.size - lag)]
        else:
            aa, bb = a[-lag : -lag + min(a.size + lag, b.size)], b[: min(a.size + lag, b.size)]
        if aa.size < 8:
            continue
        cross, coh = coherence(aa, bb)
        candidate = (abs(cross), lag, cross, coh)
        if best is None or candidate[0] > best[0]:
            best = candidate
    if best is None:
        raise ValueError("captures are too short for the requested lag range")
    _, lag, cross, coh = best
    return {
        "method": "complex_waveform_cross_correlation",
        "lag_definition": "positive means capture B is later than capture A",
        "lag_samples": lag,
        "lag_seconds": lag / sample_rate_hz,
        "phase_a_minus_b_deg": float(np.degrees(np.angle(cross))),
        "coherence": coh,
        "samples_a": int(a.size),
        "samples_b": int(b.size),
    }


def fengine_result(a: np.ndarray, b: np.ndarray, freq_start_hz: float, freq_step_hz: float) -> dict[str, Any]:
    if a.ndim == 1:
        a = a[np.newaxis, :]
    if b.ndim == 1:
        b = b[np.newaxis, :]
    frames = min(a.shape[0], b.shape[0])
    channels = min(a.shape[1], b.shape[1])
    if frames < 1 or channels < 2:
        raise ValueError("F-engine captures need at least one frame and two channels")
    a = a[:frames, :channels]
    b = b[:frames, :channels]
    cross = np.sum(a * np.conj(b), axis=0)
    denom = np.sqrt(np.sum(np.abs(a) ** 2, axis=0) * np.sum(np.abs(b) ** 2, axis=0))
    coh = np.divide(np.abs(cross), denom, out=np.zeros_like(denom), where=denom > 0)
    frequencies = freq_start_hz + np.arange(channels, dtype=np.float64) * freq_step_hz
    valid = (denom > 0) & (coh >= 0.2)
    if np.count_nonzero(valid) < 2:
        raise ValueError("fewer than two channels have usable correlated signal")
    phase = np.unwrap(np.angle(cross))
    weights = np.maximum(coh[valid], 1e-6)
    slope, intercept = np.polyfit(frequencies[valid], phase[valid], 1, w=weights)
    model = slope * frequencies + intercept
    residual = np.angle(np.exp(1j * (phase - model)))
    residual_rms_deg = float(np.degrees(np.sqrt(np.average(residual[valid] ** 2, weights=weights))))
    return {
        "method": "fengine_cross_spectrum_phase_slope",
        "phase_definition": "angle(A * conj(B))",
        "frames": frames,
        "channels": channels,
        "delay_a_minus_b_seconds": float(-slope / (2.0 * np.pi)),
        "phase_intercept_deg": float(np.degrees(np.angle(np.exp(1j * intercept)))),
        "residual_phase_rms_deg": residual_rms_deg,
        "median_coherence": float(np.median(coh[valid])),
        "frequency_hz": frequencies.tolist(),
        "phase_a_minus_b_deg": np.degrees(np.angle(cross)).tolist(),
        "coherence": coh.tolist(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="mode", required=True)
    for name in ("waveform", "fengine"):
        sub = subparsers.add_parser(name)
        sub.add_argument("--a", required=True)
        sub.add_argument("--b", required=True)
        sub.add_argument("--key-a")
        sub.add_argument("--key-b")
        sub.add_argument("--output")
    waveform = subparsers.choices["waveform"]
    waveform.add_argument("--sample-rate-hz", required=True, type=float)
    waveform.add_argument("--max-lag", type=int, default=256)
    fengine = subparsers.choices["fengine"]
    fengine.add_argument("--freq-start-hz", required=True, type=float)
    fengine.add_argument("--freq-step-hz", required=True, type=float)
    args = parser.parse_args()

    a = load_complex(args.a, args.key_a)
    b = load_complex(args.b, args.key_b)
    if args.mode == "waveform":
        result = waveform_result(a, b, max(0, args.max_lag), args.sample_rate_hz)
    else:
        result = fengine_result(a, b, args.freq_start_hz, args.freq_step_hz)
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered)
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
