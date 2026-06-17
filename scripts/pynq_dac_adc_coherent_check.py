#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _add_repo_python_path() -> None:
    sys.path.insert(0, str(_repo_root()))


def _parse_int(value: str) -> int:
    return int(value, 0)


def _wrap_phase_deg(value: float) -> float:
    while value > 180.0:
        value -= 360.0
    while value <= -180.0:
        value += 360.0
    return value


def _wait_streaming(core, mask: int, timeout: float) -> dict[str, int]:
    deadline = time.monotonic() + timeout
    status = core.read_status()
    while time.monotonic() < deadline:
        status = core.read_status()
        if status["streaming"] and (status["rfdc_current_valid_mask"] & mask) == mask:
            return status
        time.sleep(0.02)
    return status


def _interp_peak_hz(freq, power, peak_idx: int) -> float:
    import numpy as np

    peak_hz = float(freq[peak_idx])
    if peak_idx <= 0 or peak_idx >= len(power) - 1:
        return peak_hz
    alpha = math.log(max(float(power[peak_idx - 1]), 1.0))
    beta = math.log(max(float(power[peak_idx]), 1.0))
    gamma = math.log(max(float(power[peak_idx + 1]), 1.0))
    denom = alpha - 2.0 * beta + gamma
    if abs(denom) < 1e-12:
        return peak_hz
    delta = 0.5 * (alpha - gamma) / denom
    delta = float(np.clip(delta, -1.0, 1.0))
    return peak_hz + delta * float(freq[1] - freq[0])


def _analyze_iq(iq, sample_rate_hz: float, tone_hz: float, bandwidth_hz: float) -> dict[str, float | int]:
    import numpy as np

    arr = np.asarray(iq, dtype=np.float64)
    complex_samples = arr[:, 0] + 1j * arr[:, 1]
    complex_samples = complex_samples - np.mean(complex_samples)
    count = int(complex_samples.size)
    window = np.hanning(count)
    fft = np.fft.fftshift(np.fft.fft(complex_samples * window))
    freq = np.fft.fftshift(np.fft.fftfreq(count, d=1.0 / sample_rate_hz))
    power = np.abs(fft) ** 2
    passband = np.abs(freq) <= (bandwidth_hz / 2.0)
    if not np.any(passband):
        passband = np.ones_like(freq, dtype=bool)
    masked_power = np.where(passband, power, 0.0)
    peak_idx = int(np.argmax(masked_power))
    raw_peak_hz = float(freq[peak_idx])
    peak_hz = _interp_peak_hz(freq, masked_power, peak_idx)
    peak_power = float(power[peak_idx])
    guard = max(2, count // 128)
    noise_mask = passband.copy()
    lo = max(0, peak_idx - guard)
    hi = min(count, peak_idx + guard + 1)
    noise_mask[lo:hi] = False
    noise_floor = float(np.median(power[noise_mask])) if np.any(noise_mask) else 1.0
    snr_db = 10.0 * math.log10(max(peak_power, 1.0) / max(noise_floor, 1.0))
    t = np.arange(count, dtype=np.float64) / sample_rate_hz
    fit_hz = math.copysign(abs(float(tone_hz)), peak_hz if peak_hz != 0.0 else raw_peak_hz)
    basis = np.exp(1j * 2.0 * np.pi * fit_hz * t)
    coeff = np.vdot(basis, complex_samples) / max(float(np.vdot(basis, basis).real), 1.0)
    recon = coeff * basis
    signal_rms = float(np.sqrt(np.mean(np.abs(recon) ** 2)))
    residual_rms = float(np.sqrt(np.mean(np.abs(complex_samples - recon) ** 2)))
    residual_ratio = residual_rms / max(signal_rms, 1.0)
    max_abs = float(np.max(np.abs(arr))) if arr.size else 0.0
    expected_error_hz = abs(abs(peak_hz) - abs(tone_hz))
    return {
        "count": count,
        "peak_bin": peak_idx,
        "raw_peak_hz": raw_peak_hz,
        "peak_hz": peak_hz,
        "peak_mhz": peak_hz / 1_000_000.0,
        "fit_hz": fit_hz,
        "expected_error_hz": expected_error_hz,
        "peak_power": peak_power,
        "noise_floor": noise_floor,
        "snr_db": snr_db,
        "phase_deg": float(np.angle(coeff, deg=True)),
        "delta_phase_deg": _wrap_phase_deg(float(np.angle(coeff, deg=True))),
        "signal_rms": signal_rms,
        "residual_rms": residual_rms,
        "residual_ratio": residual_ratio,
        "max_abs_code": max_abs,
        "clipped": bool(max_abs >= 32760.0),
    }


def main() -> int:
    _add_repo_python_path()
    from python.t510_fengine import T510FEngine

    default_bitfile = _repo_root() / "overlay" / "t510_fengine.bit"
    parser = argparse.ArgumentParser(description="Stage 8 DAC0-ADC0 coherent RF instrument smoke test.")
    parser.add_argument("--bitfile", default=str(default_bitfile))
    parser.add_argument("--center-mhz", type=float, default=1500.0)
    parser.add_argument("--bw-mhz", type=float, default=100.0)
    parser.add_argument("--tone-mhz", type=float, default=20.0)
    parser.add_argument("--amplitude", type=_parse_int, default=2048)
    parser.add_argument("--samples", type=int, default=1024)
    parser.add_argument("--timeout", type=float, default=2.0)
    parser.add_argument("--adc-port-mask", type=_parse_int, default=0x0003)
    parser.add_argument("--preview-input-mask", type=_parse_int, default=0x01)
    parser.add_argument("--freq-tol-khz", type=float, default=500.0)
    parser.add_argument("--min-snr-db", type=float, default=12.0)
    parser.add_argument("--max-residual-ratio", type=float, default=0.85)
    parser.add_argument("--refresh-captures", type=int, default=3)
    parser.add_argument("--min-capture-hz", type=float, default=0.5)
    parser.add_argument("--no-download", action="store_true")
    args = parser.parse_args()

    center_hz = float(args.center_mhz) * 1_000_000.0
    bandwidth_hz = float(args.bw_mhz) * 1_000_000.0
    tone_hz = float(args.tone_mhz) * 1_000_000.0
    errors: list[str] = []

    core = T510FEngine(args.bitfile, download=not args.no_download)
    core.stop()
    time.sleep(0.05)
    core.configure_clock(ref="tcxo_10mhz")
    core.set_adc_active_mask(int(args.adc_port_mask))
    core.set_sync_mode("free_run")
    core.set_mode("spec")
    core.configure_rfdc(fs_adc=245_760_000, f_center=center_hz, bandwidth=bandwidth_hz, decimation=20)
    nco = core.configure_rfdc_center_frequency(center_hz, bandwidth_hz=bandwidth_hz, require=True)
    tone = core.configure_dac_tone_bank(
        freq_hz=tone_hz,
        amplitude=int(args.amplitude),
        phase_deg_per_channel=0.0,
        enable_mask=0x01,
        dac_sample_rate_hz=245_760_000.0,
    )
    dac_epoch = core.reset_dac_phase()
    core.start()
    status = _wait_streaming(core, int(args.adc_port_mask), float(args.timeout))
    if not status["streaming"]:
        errors.append("F-engine did not enter streaming")
    if (status["rfdc_current_valid_mask"] & int(args.adc_port_mask)) != int(args.adc_port_mask):
        errors.append(
            f"ADC port mask 0x{int(args.adc_port_mask):04x} not valid; "
            f"current=0x{status['rfdc_current_valid_mask']:04x}"
        )

    captures = []
    t0 = time.monotonic()
    for _ in range(max(1, int(args.refresh_captures))):
        captures.append(
            core.capture_preview(n=int(args.samples), input_mask=int(args.preview_input_mask), timeout=float(args.timeout))
        )
    elapsed = time.monotonic() - t0
    capture_hz = len(captures) / max(elapsed, 1e-9)
    preview = captures[-1]
    sample_rate = float(preview["sample_rate_hz"])
    analysis = _analyze_iq(preview["iq"][0], sample_rate, tone_hz, bandwidth_hz)
    after = core.read_status()

    if after["core_version"] != 0x0001_0006:
        errors.append(f"expected CORE_VERSION=0x00010006, got 0x{after['core_version']:08x}")
    if int(preview["sample_rate_hz"]) != 245_760_000:
        errors.append(f"expected preview sample_rate_hz=245760000, got {preview['sample_rate_hz']}")
    if int(preview.get("axis_beat_rate_hz", 0)) != 61_440_000:
        errors.append(f"expected axis_beat_rate_hz=61440000, got {preview.get('axis_beat_rate_hz')}")
    if analysis["expected_error_hz"] > float(args.freq_tol_khz) * 1_000.0:
        errors.append(
            f"CH0 peak {analysis['peak_mhz']:.6f} MHz not near {args.tone_mhz:.6f} MHz "
            f"(abs error {analysis['expected_error_hz'] / 1000.0:.1f} kHz)"
        )
    if analysis["clipped"]:
        errors.append("CH0 preview appears clipped")
    if analysis["snr_db"] < float(args.min_snr_db):
        errors.append(f"CH0 tone SNR {analysis['snr_db']:.2f} dB below {args.min_snr_db:.2f} dB")
    if analysis["residual_ratio"] > float(args.max_residual_ratio):
        errors.append(
            f"CH0 sine-fit residual ratio {analysis['residual_ratio']:.3f} "
            f"above {args.max_residual_ratio:.3f}"
        )
    if capture_hz < float(args.min_capture_hz):
        errors.append(f"preview capture rate {capture_hz:.2f} Hz below {args.min_capture_hz:.2f} Hz")

    summary = {
        "result": "PASS" if not errors else "FAIL",
        "core_version": f"0x{after['core_version']:08x}",
        "streaming": bool(after["streaming"]),
        "rfdc_current_valid_mask": f"0x{after['rfdc_current_valid_mask']:04x}",
        "adc_port_mask": f"0x{int(args.adc_port_mask):04x}",
        "preview_input_mask": f"0x{int(args.preview_input_mask):02x}",
        "preview": {
            "sample0": int(preview["sample0"]),
            "count": int(preview["count"]),
            "sample_rate_hz": int(preview["sample_rate_hz"]),
            "axis_beat_rate_hz": int(preview.get("axis_beat_rate_hz", 0)),
            "mode": int(preview.get("preview_mode", 0)),
            "capture_hz": capture_hz,
        },
        "rfdc_nco": nco,
        "dac": {
            "phase_epoch": int(dac_epoch),
            "tone_freq_mhz": float(args.tone_mhz),
            "phase_step": f"0x{tone['phase_step']:08x}",
            "amplitude": int(tone["amplitude"]),
        },
        "analysis_ch0": analysis,
        "errors": errors,
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
