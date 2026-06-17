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


def _capture_analysis(core, *, input_mask: int, samples: int, bandwidth_hz: float, phase_ref: int, timeout: float):
    preview = core.capture_preview_fast(n=samples, input_mask=input_mask, timeout=timeout)
    return preview, core.compute_scope_spectrum(preview, display_bw_hz=bandwidth_hz, phase_ref_input=phase_ref)


def main() -> int:
    _add_repo_python_path()
    from python.t510_fengine import T510FEngine

    default_bitfile = _repo_root() / "overlay" / "t510_fengine.bit"
    parser = argparse.ArgumentParser(description="Stage 9 RF instrument console v2 board smoke test.")
    parser.add_argument("--bitfile", default=str(default_bitfile))
    parser.add_argument("--center-mhz", type=float, default=1500.0)
    parser.add_argument("--bw-mhz", type=float, default=100.0)
    parser.add_argument("--tone-start-mhz", type=float, default=10.0)
    parser.add_argument("--tone-stop-mhz", type=float, default=30.0)
    parser.add_argument("--phase-step-deg", type=float, default=45.0)
    parser.add_argument("--amplitude", type=_parse_int, default=2048)
    parser.add_argument("--samples", type=int, default=512)
    parser.add_argument("--timeout", type=float, default=2.0)
    parser.add_argument("--adc-port-mask", type=_parse_int, default=0x0003)
    parser.add_argument("--preview-input-mask", type=_parse_int, default=0x01)
    parser.add_argument("--phase-ref-input", type=int, default=0)
    parser.add_argument("--min-snr-db", type=float, default=12.0)
    parser.add_argument("--min-capture-hz", type=float, default=5.0)
    parser.add_argument("--phase-tol-deg", type=float, default=90.0)
    parser.add_argument("--no-download", action="store_true")
    args = parser.parse_args()

    center_hz = float(args.center_mhz) * 1_000_000.0
    bandwidth_hz = float(args.bw_mhz) * 1_000_000.0
    tone_start_hz = float(args.tone_start_mhz) * 1_000_000.0
    tone_stop_hz = float(args.tone_stop_mhz) * 1_000_000.0
    tone_mid_hz = (tone_start_hz + tone_stop_hz) / 2.0
    tones_hz = [tone_start_hz, tone_mid_hz, tone_stop_hz]
    errors: list[str] = []

    core = T510FEngine(args.bitfile, download=not args.no_download)
    config0 = core.apply_rf_instrument_config(
        center_hz=center_hz,
        bw_hz=bandwidth_hz,
        tone_hz=tones_hz[0],
        amplitude=int(args.amplitude),
        phase_deg=0.0,
        enable_mask=int(args.preview_input_mask),
        adc_active_mask=int(args.adc_port_mask),
        initialize=True,
        start=True,
    )
    status = _wait_streaming(core, int(args.adc_port_mask), float(args.timeout))
    if status["core_version"] != 0x0001_0006:
        errors.append(f"expected CORE_VERSION=0x00010006, got 0x{status['core_version']:08x}")
    if not status["streaming"]:
        errors.append("F-engine did not enter streaming")
    if (status["rfdc_current_valid_mask"] & int(args.adc_port_mask)) != int(args.adc_port_mask):
        errors.append(
            f"ADC port mask 0x{int(args.adc_port_mask):04x} not valid; "
            f"current=0x{status['rfdc_current_valid_mask']:04x}"
        )

    tone_results = []
    for tone_hz in tones_hz:
        config = core.apply_rf_instrument_config(
            center_hz=center_hz,
            bw_hz=bandwidth_hz,
            tone_hz=tone_hz,
            amplitude=int(args.amplitude),
            phase_deg=0.0,
            enable_mask=int(args.preview_input_mask),
        )
        time.sleep(0.02)
        preview, analysis = _capture_analysis(
            core,
            input_mask=int(args.preview_input_mask),
            samples=int(args.samples),
            bandwidth_hz=bandwidth_hz,
            phase_ref=int(args.phase_ref_input),
            timeout=float(args.timeout),
        )
        peak = analysis["peaks"].get(0)
        if peak is None:
            errors.append("CH0 peak missing from analysis")
            continue
        sample_rate = float(analysis["sample_rate_hz"])
        half_bin_hz = sample_rate / int(args.samples) / 2.0
        tolerance_hz = max(half_bin_hz, 100_000.0)
        error_hz = abs(abs(float(peak["peak_hz"])) - abs(float(tone_hz)))
        if error_hz > tolerance_hz:
            errors.append(
                f"tone {tone_hz / 1e6:.3f} MHz measured {float(peak['peak_mhz']):.6f} MHz "
                f"(error {error_hz / 1000.0:.1f} kHz > {tolerance_hz / 1000.0:.1f} kHz)"
            )
        if bool(peak["clipped"]):
            errors.append(f"tone {tone_hz / 1e6:.3f} MHz appears clipped")
        if float(peak["snr_db"]) < float(args.min_snr_db):
            errors.append(
                f"tone {tone_hz / 1e6:.3f} MHz SNR {float(peak['snr_db']):.2f} dB "
                f"below {float(args.min_snr_db):.2f} dB"
            )
        tone_results.append(
            {
                "tone_mhz": tone_hz / 1_000_000.0,
                "phase_epoch": int(config["dac_phase_epoch"]),
                "sample0": int(preview["sample0"]),
                "peak_mhz": float(peak["peak_mhz"]),
                "rf_peak_mhz": float(peak["rf_peak_mhz"]),
                "error_khz": error_hz / 1000.0,
                "snr_db": float(peak["snr_db"]),
                "coherent_phase_deg": float(peak["coherent_phase_deg"]),
                "max_abs_code": float(peak["max_abs_code"]),
            }
        )

    refresh_captures = 8
    capture_t0 = time.monotonic()
    for _ in range(refresh_captures):
        _capture_analysis(
            core,
            input_mask=int(args.preview_input_mask),
            samples=int(args.samples),
            bandwidth_hz=bandwidth_hz,
            phase_ref=int(args.phase_ref_input),
            timeout=float(args.timeout),
        )
    capture_elapsed = time.monotonic() - capture_t0
    capture_hz = refresh_captures / max(capture_elapsed, 1e-9)
    if capture_hz < float(args.min_capture_hz):
        errors.append(f"fast capture/apply loop rate {capture_hz:.2f} Hz below {args.min_capture_hz:.2f} Hz")

    phase_tone_hz = tone_mid_hz
    phase_zero = core.apply_rf_instrument_config(
        center_hz=center_hz,
        bw_hz=bandwidth_hz,
        tone_hz=phase_tone_hz,
        amplitude=int(args.amplitude),
        phase_deg=0.0,
        enable_mask=int(args.preview_input_mask),
    )
    time.sleep(0.02)
    _, phase_zero_analysis = _capture_analysis(
        core,
        input_mask=int(args.preview_input_mask),
        samples=int(args.samples),
        bandwidth_hz=bandwidth_hz,
        phase_ref=int(args.phase_ref_input),
        timeout=float(args.timeout),
    )
    phase_shift = core.apply_rf_instrument_config(
        center_hz=center_hz,
        bw_hz=bandwidth_hz,
        tone_hz=phase_tone_hz,
        amplitude=int(args.amplitude),
        phase_deg=float(args.phase_step_deg),
        enable_mask=int(args.preview_input_mask),
    )
    time.sleep(0.02)
    _, phase_shift_analysis = _capture_analysis(
        core,
        input_mask=int(args.preview_input_mask),
        samples=int(args.samples),
        bandwidth_hz=bandwidth_hz,
        phase_ref=int(args.phase_ref_input),
        timeout=float(args.timeout),
    )
    phase0 = float(phase_zero_analysis["peaks"][0]["coherent_phase_deg"])
    phase1 = float(phase_shift_analysis["peaks"][0]["coherent_phase_deg"])
    measured_delta = _wrap_phase_deg(phase1 - phase0)
    expected_delta = _wrap_phase_deg(float(args.phase_step_deg))
    phase_error = abs(_wrap_phase_deg(measured_delta - expected_delta))
    if int(phase_shift["dac_phase_epoch"]) <= int(phase_zero["dac_phase_epoch"]):
        errors.append("DAC phase epoch did not increase after phase apply")
    if phase_error > float(args.phase_tol_deg):
        errors.append(
            f"phase delta {measured_delta:.1f} deg not near requested {expected_delta:.1f} deg "
            f"(error {phase_error:.1f} deg > {float(args.phase_tol_deg):.1f} deg)"
        )

    summary = {
        "result": "PASS" if not errors else "FAIL",
        "core_version": f"0x{status['core_version']:08x}",
        "streaming": bool(status["streaming"]),
        "rfdc_current_valid_mask": f"0x{status['rfdc_current_valid_mask']:04x}",
        "center_mhz": float(args.center_mhz),
        "bw_mhz": float(args.bw_mhz),
        "samples": int(args.samples),
        "preview_input_mask": f"0x{int(args.preview_input_mask):02x}",
        "initial_nco": config0["nco"],
        "tone_results": tone_results,
        "capture_hz": capture_hz,
        "phase_check": {
            "tone_mhz": phase_tone_hz / 1_000_000.0,
            "requested_delta_deg": expected_delta,
            "measured_delta_deg": measured_delta,
            "phase_error_deg": phase_error,
            "epoch_before": int(phase_zero["dac_phase_epoch"]),
            "epoch_after": int(phase_shift["dac_phase_epoch"]),
        },
        "errors": errors,
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
