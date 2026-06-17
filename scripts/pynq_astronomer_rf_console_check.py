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


def _parse_float_list(value: str) -> list[float]:
    items = [item.strip() for item in value.split(",") if item.strip()]
    if not items:
        raise argparse.ArgumentTypeError("expected a comma-separated list of MHz values")
    return [float(item) for item in items]


def _wrap_phase_deg(value: float) -> float:
    while value > 180.0:
        value -= 360.0
    while value <= -180.0:
        value += 360.0
    return value


def _amp_ratio_from_dbfs(value: float) -> float:
    return math.pow(10.0, float(value) / 20.0)


def _peak_to_peak_fraction(values: list[float]) -> float:
    if not values:
        return float("inf")
    mean_value = sum(values) / len(values)
    if mean_value <= 0.0:
        return float("inf")
    return (max(values) - min(values)) / mean_value


def _wait_streaming(core, mask: int, timeout: float) -> dict[str, int]:
    deadline = time.monotonic() + timeout
    status = core.read_status()
    while time.monotonic() < deadline:
        status = core.read_status()
        if status["streaming"] and (status["rfdc_current_valid_mask"] & mask) == mask:
            return status
        time.sleep(0.02)
    return status


def _has_nco_readback(nco: dict, *, kind: str, expected_mhz: float, tol_mhz: float = 0.5) -> bool:
    for item in nco.get("results", []):
        if item.get("kind") == kind and abs(float(item.get("readback_freq_mhz", 1e9)) - expected_mhz) <= tol_mhz:
            return True
    return False


def _capture_observation(core, *, signal_hz: float, center_hz: float, bw_hz: float, samples: int, time_window_us: float, oversample: float, timeout: float):
    preview = core.capture_preview_fast(n=samples, input_mask=0x01, timeout=timeout)
    analysis = core.compute_observation_view(
        preview,
        observe_center_hz=center_hz,
        view_bw_hz=bw_hz,
        dac_signal_hz=signal_hz,
        time_window_us=time_window_us,
        oversample=oversample,
        phase_ref_input=0,
        stabilize_phase=True,
    )
    return preview, analysis


def _capture_best_observation(
    core,
    *,
    signal_hz: float,
    center_hz: float,
    bw_hz: float,
    samples: int,
    time_window_us: float,
    oversample: float,
    timeout: float,
    repeats: int,
    interval_s: float,
):
    best = None
    best_score = None
    for attempt in range(max(1, int(repeats))):
        if attempt:
            time.sleep(max(0.0, float(interval_s)))
        preview, analysis = _capture_observation(
            core,
            signal_hz=signal_hz,
            center_hz=center_hz,
            bw_hz=bw_hz,
            samples=samples,
            time_window_us=time_window_us,
            oversample=oversample,
            timeout=timeout,
        )
        peak = analysis["peaks"].get(0)
        if peak is None:
            score = -1.0e9
        else:
            score = float(peak["snr_db"])
            if bool(peak["clipped"]):
                score -= 1.0e6
        if best is None or score > best_score:
            best = (preview, analysis)
            best_score = score
    return best


def _run_stage11_scope_check(core_cls, args) -> int:
    signals_mhz = _parse_float_list(args.signals_mhz)
    if len(signals_mhz) < 3:
        raise SystemExit("--stage11-scope-check requires at least three --signals-mhz values")

    center_hz = float(args.center_mhz) * 1_000_000.0
    bw_hz = float(args.bw_mhz) * 1_000_000.0
    samples = core_cls.observation_capture_count(
        time_window_us=args.time_window_us,
        oversample=args.oversample,
    )
    errors: list[str] = []
    results = []

    core = core_cls(args.bitfile, download=not args.no_download)
    first_signal_hz = float(signals_mhz[0]) * 1_000_000.0
    first_config = core.apply_observation_instrument_config(
        observe_center_hz=center_hz,
        dac_signal_hz=first_signal_hz,
        view_bw_hz=bw_hz,
        amplitude=int(args.amplitude),
        phase_deg=0.0,
        enable_mask=0x01,
        adc_active_mask=int(args.adc_port_mask),
        initialize=True,
        start=True,
    )
    status = _wait_streaming(core, int(args.adc_port_mask), float(args.timeout))
    if status["core_version"] != 0x0001_0007:
        errors.append(f"expected CORE_VERSION=0x00010007, got 0x{status['core_version']:08x}")
    if not status["streaming"]:
        errors.append("F-engine did not enter streaming")
    if (status["rfdc_current_valid_mask"] & int(args.adc_port_mask)) != int(args.adc_port_mask):
        errors.append(
            f"ADC port mask 0x{int(args.adc_port_mask):04x} not valid; "
            f"current=0x{status['rfdc_current_valid_mask']:04x}"
        )
    if not _has_nco_readback(first_config["nco"], kind="adc", expected_mhz=-float(args.center_mhz)):
        errors.append(f"ADC NCO readback did not include -{float(args.center_mhz):.3f} MHz")

    for signal_mhz in signals_mhz:
        signal_hz = float(signal_mhz) * 1_000_000.0
        config = core.apply_observation_instrument_config(
            observe_center_hz=center_hz,
            dac_signal_hz=signal_hz,
            view_bw_hz=bw_hz,
            amplitude=int(args.amplitude),
            phase_deg=0.0,
            enable_mask=0x01,
            adc_active_mask=int(args.adc_port_mask),
            initialize=False,
            start=False,
        )
        if not _has_nco_readback(config["nco"], kind="dac", expected_mhz=float(signal_mhz)):
            errors.append(f"DAC NCO readback did not include +{float(signal_mhz):.3f} MHz")
        time.sleep(max(0.03, float(args.settle_s)))
        preview, analysis = _capture_best_observation(
            core,
            signal_hz=signal_hz,
            center_hz=center_hz,
            bw_hz=bw_hz,
            samples=samples,
            time_window_us=float(args.time_window_us),
            oversample=float(args.oversample),
            timeout=float(args.timeout),
            repeats=int(args.capture_retries),
            interval_s=float(args.capture_retry_interval_s),
        )
        peak = analysis["peaks"].get(0)
        rf_scope = analysis["rf_scope"].get(0)
        baseband_scope = analysis["baseband_scope"].get(0)
        if peak is None or rf_scope is None or baseband_scope is None:
            errors.append(f"missing CH0 analysis for signal {signal_mhz:.3f} MHz")
            continue

        x_end = float(rf_scope["time_us"][-1])
        x_error_us = abs(x_end - float(args.time_window_us))
        cycles = float(rf_scope["cycles"])
        expected_cycles = signal_hz * float(args.time_window_us) * 1.0e-6
        cycle_error = abs(cycles - expected_cycles)
        baseband_abs_error_hz = abs(abs(float(peak["baseband_hz"])) - abs(signal_hz - center_hz))
        if x_error_us > 1.0e-9:
            errors.append(
                f"RF scope x-axis ends at {x_end:.9f} us, expected {float(args.time_window_us):.9f} us"
            )
        if cycle_error > 1.0e-6:
            errors.append(
                f"RF scope cycles {cycles:.6f} not equal expected {expected_cycles:.6f} "
                f"for signal {signal_mhz:.3f} MHz"
            )
        if baseband_abs_error_hz > float(args.stage11_baseband_tol_khz) * 1_000.0:
            errors.append(
                f"signal {signal_mhz:.3f} MHz baseband abs {abs(float(peak['baseband_mhz'])):.6f} MHz "
                f"not near expected {abs(signal_hz - center_hz) / 1e6:.6f} MHz"
            )
        if bool(peak["clipped"]):
            errors.append(f"signal {signal_mhz:.3f} MHz CH0 preview appears clipped")
        if float(peak["snr_db"]) < float(args.min_snr_db):
            errors.append(
                f"signal {signal_mhz:.3f} MHz CH0 SNR {float(peak['snr_db']):.2f} dB "
                f"below {float(args.min_snr_db):.2f} dB"
            )
        results.append(
            {
                "signal_mhz": float(signal_mhz),
                "rf_scope_cycles": cycles,
                "expected_cycles": expected_cycles,
                "rf_scope_phase_deg": float(rf_scope["phase_deg"]),
                "rf_scope_points": int(rf_scope["point_count"]),
                "rf_scope_x_end_us": x_end,
                "baseband_mhz": float(peak["baseband_mhz"]),
                "baseband_abs_error_khz": baseband_abs_error_hz / 1000.0,
                "baseband_scope_mhz": float(baseband_scope["frequency_mhz"]),
                "snr_db": float(peak["snr_db"]),
                "max_abs_code": float(peak["max_abs_code"]),
                "sample0": int(preview["sample0"]),
            }
        )

    cycles = [float(item["rf_scope_cycles"]) for item in results]
    if len(cycles) >= 3 and not all(cycles[idx] < cycles[idx + 1] for idx in range(len(cycles) - 1)):
        errors.append(f"RF scope cycles are not monotonic increasing with signal frequency: {cycles}")

    jitter_signal_hz = float(signals_mhz[len(signals_mhz) // 2]) * 1_000_000.0
    core.apply_observation_instrument_config(
        observe_center_hz=center_hz,
        dac_signal_hz=jitter_signal_hz,
        view_bw_hz=bw_hz,
        amplitude=int(args.amplitude),
        phase_deg=0.0,
        enable_mask=0x01,
    )
    time.sleep(max(0.03, float(args.settle_s)))
    phase_values = []
    for _ in range(max(1, int(args.stage11_jitter_frames))):
        _, analysis = _capture_observation(
            core,
            signal_hz=jitter_signal_hz,
            center_hz=center_hz,
            bw_hz=bw_hz,
            samples=samples,
            time_window_us=float(args.time_window_us),
            oversample=float(args.oversample),
            timeout=float(args.timeout),
        )
        phase_values.append(float(analysis["rf_scope"][0]["phase_deg"]))
    phase_jitter = max(abs(_wrap_phase_deg(value - phase_values[0])) for value in phase_values)
    if phase_jitter > float(args.stage11_phase_jitter_deg):
        errors.append(
            f"RF scope phase jitter {phase_jitter:.3f} deg exceeds "
            f"{float(args.stage11_phase_jitter_deg):.3f} deg"
        )

    phase_results = []
    prev_epoch = None
    for phase_deg in (0.0, 45.0, 90.0):
        cfg = core.apply_observation_instrument_config(
            observe_center_hz=center_hz,
            dac_signal_hz=jitter_signal_hz,
            view_bw_hz=bw_hz,
            amplitude=int(args.amplitude),
            phase_deg=phase_deg,
            enable_mask=0x01,
        )
        time.sleep(max(0.03, float(args.settle_s)))
        _, analysis = _capture_observation(
            core,
            signal_hz=jitter_signal_hz,
            center_hz=center_hz,
            bw_hz=bw_hz,
            samples=samples,
            time_window_us=float(args.time_window_us),
            oversample=float(args.oversample),
            timeout=float(args.timeout),
        )
        measured_phase = float(analysis["rf_scope"][0]["phase_deg"])
        phase_error = abs(_wrap_phase_deg(measured_phase - phase_deg))
        if int(cfg["dac_phase_epoch"]) <= 0:
            errors.append("DAC phase epoch did not read back after phase apply")
        if prev_epoch is not None and int(cfg["dac_phase_epoch"]) <= prev_epoch:
            errors.append(
                f"DAC phase epoch did not increase for phase {phase_deg:.1f} deg: "
                f"{int(cfg['dac_phase_epoch'])} <= {prev_epoch}"
            )
        prev_epoch = int(cfg["dac_phase_epoch"])
        if phase_error > float(args.stage11_phase_display_tol_deg):
            errors.append(
                f"RF scope configured phase {measured_phase:.3f} deg not near "
                f"{phase_deg:.3f} deg"
            )
        phase_results.append(
            {
                "requested_phase_deg": phase_deg,
                "rf_scope_phase_deg": measured_phase,
                "phase_error_deg": phase_error,
                "phase_epoch": int(cfg["dac_phase_epoch"]),
            }
        )

    core.read_realtime_rates()
    time.sleep(0.25)
    rates = core.read_realtime_rates()
    rate_values = rates["rates"]
    if float(rate_values["adc_samples_per_s"]) <= 0.0:
        errors.append("ADC sample counter did not advance during rate measurement")
    if (
        float(rate_values["packetizer_packets_per_s"]) <= 0.0 and
        float(rate_values["tx_dry_run_packets_per_s"]) <= 0.0
    ):
        errors.append("UDP packet/dry-run counters did not advance during rate measurement")

    summary = {
        "result": "PASS" if not errors else "FAIL",
        "stage11_scope_check": True,
        "core_version": f"0x{status['core_version']:08x}",
        "streaming": bool(status["streaming"]),
        "center_mhz": float(args.center_mhz),
        "bw_mhz": float(args.bw_mhz),
        "signals_mhz": signals_mhz,
        "samples": int(samples),
        "time_window_us": float(args.time_window_us),
        "scope_results": results,
        "phase_jitter_deg": phase_jitter,
        "phase_results": phase_results,
        "rates": {
            "udp_dry_run": bool(rates["udp_dry_run"]),
            "qsfp_link_up": bool(rates["qsfp_link_up"]),
            **rate_values,
        },
        "errors": errors,
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if not errors else 1


def _run_stage12_stability_check(core_cls, stabilizer_cls, args) -> int:
    signal_hz = float(args.signal_mhz) * 1_000_000.0
    center_hz = float(args.center_mhz) * 1_000_000.0
    bw_hz = float(args.bw_mhz) * 1_000_000.0
    samples = core_cls.observation_capture_count(
        time_window_us=float(args.time_window_us),
        oversample=float(args.oversample),
    )
    frames_required = max(1, int(args.frames))
    max_attempts = max(frames_required, int(math.ceil(frames_required * float(args.stage12_max_attempt_factor))))
    errors: list[str] = []

    core = core_cls(args.bitfile, download=not args.no_download)
    config = core.apply_observation_instrument_config(
        observe_center_hz=center_hz,
        dac_signal_hz=signal_hz,
        view_bw_hz=bw_hz,
        amplitude=int(args.amplitude),
        phase_deg=0.0,
        enable_mask=0x01,
        adc_active_mask=int(args.adc_port_mask),
        initialize=True,
        start=True,
    )
    status = _wait_streaming(core, int(args.adc_port_mask), float(args.timeout))
    if status["core_version"] != 0x0001_0007:
        errors.append(f"expected CORE_VERSION=0x00010007, got 0x{status['core_version']:08x}")
    if not status["streaming"]:
        errors.append("F-engine did not enter streaming")
    if (status["rfdc_current_valid_mask"] & int(args.adc_port_mask)) != int(args.adc_port_mask):
        errors.append(
            f"ADC port mask 0x{int(args.adc_port_mask):04x} not valid; "
            f"current=0x{status['rfdc_current_valid_mask']:04x}"
        )
    if not _has_nco_readback(config["nco"], kind="dac", expected_mhz=float(args.signal_mhz)):
        errors.append(f"DAC NCO readback did not include +{float(args.signal_mhz):.3f} MHz")
    if not _has_nco_readback(config["nco"], kind="adc", expected_mhz=-float(args.center_mhz)):
        errors.append(f"ADC NCO readback did not include -{float(args.center_mhz):.3f} MHz")

    stabilizer = stabilizer_cls(
        alpha=float(args.smooth_alpha),
        min_snr_db=float(args.stage12_reject_snr_db),
        peak_jump_mhz=float(args.stage12_reject_peak_jump_mhz),
        amp_jump_db=float(args.stage12_reject_amp_jump_db),
    )
    raw_peak_amp: list[float] = []
    smooth_peak_amp: list[float] = []
    raw_rms_amp: list[float] = []
    smooth_rms_amp: list[float] = []
    accepted_history = []
    rejected = []
    attempts = 0
    waterfall_x_range_mhz = [
        float(args.center_mhz) - float(args.bw_mhz) / 2.0,
        float(args.center_mhz) + float(args.bw_mhz) / 2.0,
    ]

    while attempts < max_attempts and len(accepted_history) < frames_required:
        attempts += 1
        _, analysis = _capture_observation(
            core,
            signal_hz=signal_hz,
            center_hz=center_hz,
            bw_hz=bw_hz,
            samples=samples,
            time_window_us=float(args.time_window_us),
            oversample=float(args.oversample),
            timeout=float(args.timeout),
        )
        spectrum = analysis["spectrum"].get(0)
        peak = analysis["peaks"].get(0)
        if spectrum is None or peak is None:
            errors.append(f"missing CH0 analysis on attempt {attempts}")
            continue
        update = stabilizer.update_channel(
            0,
            spectrum,
            peak,
            smoothing_enabled=True,
            alpha=float(args.smooth_alpha),
        )
        if update["accepted"]:
            raw_peak_amp.append(_amp_ratio_from_dbfs(float(update["raw_peak_dbfs"])))
            smooth_peak_amp.append(_amp_ratio_from_dbfs(float(update["display_peak_dbfs"])))
            raw_rms_amp.append(_amp_ratio_from_dbfs(float(update["raw_rms_dbfs"])))
            smooth_rms_amp.append(_amp_ratio_from_dbfs(float(update["display_rms_dbfs"])))
            accepted_history.append(
                {
                    "frame": attempts,
                    "sample0": int(analysis["sample0"]),
                    "raw_peak_mhz": float(update["raw_peak_mhz"]),
                    "smooth_peak_mhz": float(update["display_peak_mhz"]),
                    "raw_peak_dbfs": float(update["raw_peak_dbfs"]),
                    "smooth_peak_dbfs": float(update["display_peak_dbfs"]),
                    "raw_rms_dbfs": float(update["raw_rms_dbfs"]),
                    "smooth_rms_dbfs": float(update["display_rms_dbfs"]),
                    "snr_db": float(update["snr_db"]),
                }
            )
        else:
            rejected.append(
                {
                    "frame": attempts,
                    "sample0": int(analysis["sample0"]),
                    "reject_reason": str(update["reject_reason"]),
                    "raw_peak_mhz": float(update["raw_peak_mhz"]),
                    "raw_peak_dbfs": float(update["raw_peak_dbfs"]),
                    "snr_db": float(update["snr_db"]),
                }
            )
        time.sleep(max(0.0, float(args.stage12_frame_interval_s)))

    if len(accepted_history) < frames_required:
        errors.append(
            f"waterfall history accepted {len(accepted_history)} frames, expected {frames_required} "
            f"within {max_attempts} attempts"
        )
    raw_peak_pp = _peak_to_peak_fraction(raw_peak_amp)
    smooth_peak_pp = _peak_to_peak_fraction(smooth_peak_amp)
    raw_rms_pp = _peak_to_peak_fraction(raw_rms_amp)
    smooth_rms_pp = _peak_to_peak_fraction(smooth_rms_amp)
    if smooth_peak_amp and not (
        smooth_peak_pp <= float(args.stage12_max_smoothed_pp_frac)
        or smooth_peak_pp <= raw_peak_pp * float(args.stage12_max_smoothed_vs_raw_ratio)
    ):
        errors.append(
            f"smoothed peak p-p jitter {smooth_peak_pp * 100.0:.2f}% did not meet "
            f"{float(args.stage12_max_smoothed_pp_frac) * 100.0:.2f}% absolute or "
            f"{float(args.stage12_max_smoothed_vs_raw_ratio) * 100.0:.1f}% of raw "
            f"({raw_peak_pp * 100.0:.2f}%)"
        )
    if rejected and len(accepted_history) != len(raw_peak_amp):
        errors.append("rejected frames contaminated accepted waterfall/amplitude history")

    core.read_realtime_rates()
    time.sleep(0.25)
    rates = core.read_realtime_rates()
    summary = {
        "result": "PASS" if not errors else "FAIL",
        "stage12_stability_check": True,
        "core_version": f"0x{status['core_version']:08x}",
        "streaming": bool(status["streaming"]),
        "signal_mhz": float(args.signal_mhz),
        "center_mhz": float(args.center_mhz),
        "bw_mhz": float(args.bw_mhz),
        "samples": int(samples),
        "frames_required": frames_required,
        "attempts": attempts,
        "accepted_frames": len(accepted_history),
        "rejected_frames": len(rejected),
        "raw_peak_pp_fraction": raw_peak_pp,
        "smoothed_peak_pp_fraction": smooth_peak_pp,
        "raw_rms_pp_fraction": raw_rms_pp,
        "smoothed_rms_pp_fraction": smooth_rms_pp,
        "smooth_alpha": float(args.smooth_alpha),
        "waterfall": {
            "channel": 0,
            "history_frames": len(accepted_history),
            "x_range_mhz": waterfall_x_range_mhz,
            "dbfs_range": [float(args.stage12_waterfall_floor_db), float(args.stage12_waterfall_top_db)],
        },
        "accepted_preview": accepted_history[:3] + accepted_history[-3:] if len(accepted_history) > 6 else accepted_history,
        "rejected_preview": rejected[:10],
        "rates": {
            "udp_dry_run": bool(rates["udp_dry_run"]),
            "qsfp_link_up": bool(rates["qsfp_link_up"]),
            **rates["rates"],
        },
        "errors": errors,
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if not errors else 1


def _run_stage12_performance_check(core_cls, stabilizer_cls, args) -> int:
    import numpy as np

    signal_hz = float(args.signal_mhz) * 1_000_000.0
    center_hz = float(args.center_mhz) * 1_000_000.0
    bw_hz = float(args.bw_mhz) * 1_000_000.0
    samples = core_cls.observation_capture_count(
        time_window_us=float(args.time_window_us),
        oversample=float(args.oversample),
    )
    frames = max(1, int(args.frames))
    errors: list[str] = []
    core = core_cls(args.bitfile, download=not args.no_download)
    core.apply_observation_instrument_config(
        observe_center_hz=center_hz,
        dac_signal_hz=signal_hz,
        view_bw_hz=bw_hz,
        amplitude=int(args.amplitude),
        phase_deg=0.0,
        enable_mask=0x01,
        adc_active_mask=int(args.adc_port_mask),
        initialize=True,
        start=True,
    )
    status = _wait_streaming(core, int(args.adc_port_mask), float(args.timeout))
    if status["core_version"] != 0x0001_0007:
        errors.append(f"expected CORE_VERSION=0x00010007, got 0x{status['core_version']:08x}")
    if not status["streaming"]:
        errors.append("F-engine did not enter streaming")

    stabilizer = stabilizer_cls(alpha=float(args.smooth_alpha))
    capture_ms: list[float] = []
    analysis_ms: list[float] = []
    display_reduce_ms: list[float] = []
    total_ms: list[float] = []
    for _ in range(frames):
        t0 = time.monotonic()
        preview = core.capture_preview_fast(n=samples, input_mask=0x01, timeout=float(args.timeout))
        t1 = time.monotonic()
        analysis = core.compute_observation_view(
            preview,
            observe_center_hz=center_hz,
            view_bw_hz=bw_hz,
            dac_signal_hz=signal_hz,
            time_window_us=float(args.time_window_us),
            oversample=float(args.oversample),
            display_phase_deg=0.0,
        )
        t2 = time.monotonic()
        display = stabilizer.update_channel(
            0,
            analysis["spectrum"][0],
            analysis["peaks"][0],
            smoothing_enabled=True,
            alpha=float(args.smooth_alpha),
        )
        x = np.asarray(display["rf_mhz"], dtype=float)
        y = np.asarray(display["display_power_dbfs"], dtype=float)
        mask = (x >= float(args.center_mhz) - float(args.bw_mhz) / 2.0) & (
            x <= float(args.center_mhz) + float(args.bw_mhz) / 2.0
        )
        y = y[mask]
        if y.size > int(args.stage12_perf_spectrum_points):
            group = int(np.ceil(y.size / int(args.stage12_perf_spectrum_points)))
            padded = group * int(np.ceil(y.size / group))
            if padded > y.size:
                y = np.pad(y, (0, padded - y.size), mode="constant", constant_values=np.nanmin(y))
            _ = np.nanmax(y.reshape(-1, group), axis=1)
        t3 = time.monotonic()
        capture_ms.append((t1 - t0) * 1000.0)
        analysis_ms.append((t2 - t1) * 1000.0)
        display_reduce_ms.append((t3 - t2) * 1000.0)
        total_ms.append((t3 - t0) * 1000.0)

    avg_total = sum(total_ms) / len(total_ms)
    backend_fps = 1000.0 / avg_total if avg_total > 0.0 else 0.0
    if backend_fps < float(args.stage12_min_backend_fps):
        errors.append(
            f"backend FPS {backend_fps:.2f} below {float(args.stage12_min_backend_fps):.2f}"
        )
    summary = {
        "result": "PASS" if not errors else "FAIL",
        "stage12_performance_check": True,
        "core_version": f"0x{status['core_version']:08x}",
        "frames": frames,
        "samples": int(samples),
        "capture_ms_avg": sum(capture_ms) / len(capture_ms),
        "capture_ms_max": max(capture_ms),
        "analysis_ms_avg": sum(analysis_ms) / len(analysis_ms),
        "analysis_ms_max": max(analysis_ms),
        "display_reduce_ms_avg": sum(display_reduce_ms) / len(display_reduce_ms),
        "total_backend_ms_avg": avg_total,
        "total_backend_ms_max": max(total_ms),
        "backend_fps_est": backend_fps,
        "errors": errors,
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if not errors else 1


def main() -> int:
    _add_repo_python_path()
    from python.t510_fengine import ObservationSpectrumStabilizer, T510FEngine

    default_bitfile = _repo_root() / "overlay" / "t510_fengine.bit"
    parser = argparse.ArgumentParser(description="Stage 10/11/12 astronomer RF observation console board smoke test.")
    parser.add_argument("--bitfile", default=str(default_bitfile))
    parser.add_argument("--stage11-scope-check", action="store_true")
    parser.add_argument("--stage12-stability-check", action="store_true")
    parser.add_argument("--stage12-performance-check", action="store_true")
    parser.add_argument("--signals-mhz", default="60,100,130")
    parser.add_argument("--signal-mhz", type=float, default=200.0)
    parser.add_argument("--center-mhz", type=float, default=180.0)
    parser.add_argument("--bw-mhz", type=float, default=100.0)
    parser.add_argument("--phase-step-deg", type=float, default=45.0)
    parser.add_argument("--time-window-us", type=float, default=0.25)
    parser.add_argument("--oversample", type=float, default=2.5)
    parser.add_argument("--amplitude", type=_parse_int, default=2048)
    parser.add_argument("--timeout", type=float, default=2.0)
    parser.add_argument("--adc-port-mask", type=_parse_int, default=0x0003)
    parser.add_argument("--rf-tol-khz", type=float, default=750.0)
    parser.add_argument("--baseband-tol-khz", type=float, default=750.0)
    parser.add_argument("--phase-tol-deg", type=float, default=180.0)
    parser.add_argument("--min-phase-move-deg", type=float, default=20.0)
    parser.add_argument("--min-snr-db", type=float, default=10.0)
    parser.add_argument("--settle-s", type=float, default=0.2)
    parser.add_argument("--capture-retries", type=int, default=3)
    parser.add_argument("--capture-retry-interval-s", type=float, default=0.05)
    parser.add_argument("--stage11-baseband-tol-khz", type=float, default=1500.0)
    parser.add_argument("--stage11-jitter-frames", type=int, default=20)
    parser.add_argument("--stage11-phase-jitter-deg", type=float, default=0.25)
    parser.add_argument("--stage11-phase-display-tol-deg", type=float, default=0.25)
    parser.add_argument("--frames", type=int, default=60)
    parser.add_argument("--smooth-alpha", type=float, default=0.25)
    parser.add_argument("--stage12-reject-snr-db", type=float, default=10.0)
    parser.add_argument("--stage12-reject-peak-jump-mhz", type=float, default=2.0)
    parser.add_argument("--stage12-reject-amp-jump-db", type=float, default=6.0)
    parser.add_argument("--stage12-max-smoothed-pp-frac", type=float, default=0.15)
    parser.add_argument("--stage12-max-smoothed-vs-raw-ratio", type=float, default=0.40)
    parser.add_argument("--stage12-max-attempt-factor", type=float, default=2.0)
    parser.add_argument("--stage12-frame-interval-s", type=float, default=0.02)
    parser.add_argument("--stage12-waterfall-floor-db", type=float, default=-120.0)
    parser.add_argument("--stage12-waterfall-top-db", type=float, default=-20.0)
    parser.add_argument("--stage12-perf-spectrum-points", type=int, default=384)
    parser.add_argument("--stage12-min-backend-fps", type=float, default=30.0)
    parser.add_argument("--no-download", action="store_true")
    args = parser.parse_args()

    if args.stage11_scope_check:
        return _run_stage11_scope_check(T510FEngine, args)
    if args.stage12_stability_check:
        return _run_stage12_stability_check(T510FEngine, ObservationSpectrumStabilizer, args)
    if args.stage12_performance_check:
        return _run_stage12_performance_check(T510FEngine, ObservationSpectrumStabilizer, args)

    signal_hz = float(args.signal_mhz) * 1_000_000.0
    first_center_hz = float(args.center_mhz) * 1_000_000.0
    bw_hz = float(args.bw_mhz) * 1_000_000.0
    samples = T510FEngine.observation_capture_count(time_window_us=args.time_window_us, oversample=args.oversample)
    errors: list[str] = []
    centers_hz = [first_center_hz, signal_hz]
    plus_center_hz = signal_hz + 20_000_000.0
    if plus_center_hz <= 350_000_000.0:
        centers_hz.append(plus_center_hz)

    core = T510FEngine(args.bitfile, download=not args.no_download)
    first_config = core.apply_observation_instrument_config(
        observe_center_hz=centers_hz[0],
        dac_signal_hz=signal_hz,
        view_bw_hz=bw_hz,
        amplitude=int(args.amplitude),
        phase_deg=0.0,
        enable_mask=0x01,
        adc_active_mask=int(args.adc_port_mask),
        initialize=True,
        start=True,
    )
    status = _wait_streaming(core, int(args.adc_port_mask), float(args.timeout))
    if status["core_version"] != 0x0001_0007:
        errors.append(f"expected CORE_VERSION=0x00010007, got 0x{status['core_version']:08x}")
    if not status["streaming"]:
        errors.append("F-engine did not enter streaming")
    if (status["rfdc_current_valid_mask"] & int(args.adc_port_mask)) != int(args.adc_port_mask):
        errors.append(
            f"ADC port mask 0x{int(args.adc_port_mask):04x} not valid; "
            f"current=0x{status['rfdc_current_valid_mask']:04x}"
        )
    if not _has_nco_readback(first_config["nco"], kind="dac", expected_mhz=float(args.signal_mhz)):
        errors.append(f"DAC NCO readback did not include +{float(args.signal_mhz):.3f} MHz")
    if not _has_nco_readback(first_config["nco"], kind="adc", expected_mhz=-float(args.center_mhz)):
        errors.append(f"ADC NCO readback did not include -{float(args.center_mhz):.3f} MHz")

    sweep_results = []
    for idx, center_hz in enumerate(centers_hz):
        config = core.apply_observation_instrument_config(
            observe_center_hz=center_hz,
            dac_signal_hz=signal_hz,
            view_bw_hz=bw_hz,
            amplitude=int(args.amplitude),
            phase_deg=0.0,
            enable_mask=0x01,
            initialize=False,
            start=False,
        )
        time.sleep(max(0.03, float(args.settle_s)))
        preview, analysis = _capture_best_observation(
            core,
            signal_hz=signal_hz,
            center_hz=center_hz,
            bw_hz=bw_hz,
            samples=samples,
            time_window_us=float(args.time_window_us),
            oversample=float(args.oversample),
            timeout=float(args.timeout),
            repeats=int(args.capture_retries),
            interval_s=float(args.capture_retry_interval_s),
        )
        peak = analysis["peaks"].get(0)
        if peak is None:
            errors.append(f"CH0 peak missing at center {center_hz / 1e6:.3f} MHz")
            continue
        rf_error_hz = abs(float(peak["rf_peak_hz"]) - signal_hz)
        baseband_error_hz = abs(float(peak["baseband_hz"]) - (signal_hz - center_hz))
        if rf_error_hz > float(args.rf_tol_khz) * 1_000.0:
            errors.append(
                f"center {center_hz / 1e6:.3f} MHz RF peak {float(peak['rf_peak_mhz']):.6f} MHz "
                f"not near signal {float(args.signal_mhz):.6f} MHz"
            )
        if baseband_error_hz > float(args.baseband_tol_khz) * 1_000.0:
            errors.append(
                f"center {center_hz / 1e6:.3f} MHz baseband {float(peak['baseband_mhz']):.6f} MHz "
                f"not near expected {(signal_hz - center_hz) / 1e6:.6f} MHz"
            )
        if bool(peak["clipped"]):
            errors.append(f"center {center_hz / 1e6:.3f} MHz CH0 preview appears clipped")
        if float(peak["snr_db"]) < float(args.min_snr_db):
            errors.append(
                f"center {center_hz / 1e6:.3f} MHz CH0 SNR {float(peak['snr_db']):.2f} dB "
                f"below {float(args.min_snr_db):.2f} dB"
            )
        sweep_results.append(
            {
                "center_mhz": center_hz / 1_000_000.0,
                "phase_epoch": int(config["dac_phase_epoch"]),
                "sample0": int(preview["sample0"]),
                "rf_peak_mhz": float(peak["rf_peak_mhz"]),
                "baseband_mhz": float(peak["baseband_mhz"]),
                "raw_baseband_mhz": float(peak["raw_baseband_mhz"]),
                "mixer_sign": int(peak["mixer_sign"]),
                "rf_error_khz": rf_error_hz / 1000.0,
                "baseband_error_khz": baseband_error_hz / 1000.0,
                "snr_db": float(peak["snr_db"]),
                "max_abs_code": float(peak["max_abs_code"]),
            }
        )

    phase_center_hz = first_center_hz
    zero_cfg = core.apply_observation_instrument_config(
        observe_center_hz=phase_center_hz,
        dac_signal_hz=signal_hz,
        view_bw_hz=bw_hz,
        amplitude=int(args.amplitude),
        phase_deg=0.0,
        enable_mask=0x01,
    )
    time.sleep(max(0.03, float(args.settle_s)))
    _, zero_analysis = _capture_best_observation(
        core,
        signal_hz=signal_hz,
        center_hz=phase_center_hz,
        bw_hz=bw_hz,
        samples=samples,
        time_window_us=float(args.time_window_us),
        oversample=float(args.oversample),
        timeout=float(args.timeout),
        repeats=int(args.capture_retries),
        interval_s=float(args.capture_retry_interval_s),
    )
    phase_cfg = core.apply_observation_instrument_config(
        observe_center_hz=phase_center_hz,
        dac_signal_hz=signal_hz,
        view_bw_hz=bw_hz,
        amplitude=int(args.amplitude),
        phase_deg=float(args.phase_step_deg),
        enable_mask=0x01,
    )
    time.sleep(max(0.03, float(args.settle_s)))
    _, phase_analysis = _capture_best_observation(
        core,
        signal_hz=signal_hz,
        center_hz=phase_center_hz,
        bw_hz=bw_hz,
        samples=samples,
        time_window_us=float(args.time_window_us),
        oversample=float(args.oversample),
        timeout=float(args.timeout),
        repeats=int(args.capture_retries),
        interval_s=float(args.capture_retry_interval_s),
    )
    measured_delta = _wrap_phase_deg(
        float(phase_analysis["peaks"][0]["coherent_phase_deg"]) -
        float(zero_analysis["peaks"][0]["coherent_phase_deg"])
    )
    expected_delta = _wrap_phase_deg(float(args.phase_step_deg))
    phase_error = abs(_wrap_phase_deg(measured_delta - expected_delta))
    if int(phase_cfg["dac_phase_epoch"]) <= int(zero_cfg["dac_phase_epoch"]):
        errors.append("DAC phase epoch did not increase after phase apply")
    if abs(measured_delta) < float(args.min_phase_move_deg):
        errors.append(
            f"phase delta {measured_delta:.1f} deg is below visible movement threshold "
            f"{float(args.min_phase_move_deg):.1f} deg"
        )
    if float(args.phase_tol_deg) < 180.0 and phase_error > float(args.phase_tol_deg):
        errors.append(
            f"phase delta {measured_delta:.1f} deg not near requested {expected_delta:.1f} deg "
            f"(error {phase_error:.1f} deg > {float(args.phase_tol_deg):.1f} deg)"
        )

    core.read_realtime_rates()
    time.sleep(0.25)
    rates = core.read_realtime_rates()
    rate_values = rates["rates"]
    if float(rate_values["adc_samples_per_s"]) <= 0.0:
        errors.append("ADC sample counter did not advance during rate measurement")
    if (
        float(rate_values["packetizer_packets_per_s"]) <= 0.0 and
        float(rate_values["tx_dry_run_packets_per_s"]) <= 0.0
    ):
        errors.append("UDP packet/dry-run counters did not advance during rate measurement")

    summary = {
        "result": "PASS" if not errors else "FAIL",
        "core_version": f"0x{status['core_version']:08x}",
        "streaming": bool(status["streaming"]),
        "rfdc_current_valid_mask": f"0x{status['rfdc_current_valid_mask']:04x}",
        "signal_mhz": float(args.signal_mhz),
        "bw_mhz": float(args.bw_mhz),
        "samples": int(samples),
        "time_window_us": float(args.time_window_us),
        "oversample": float(args.oversample),
        "initial_nco": first_config["nco"],
        "sweep_results": sweep_results,
        "phase_check": {
            "center_mhz": phase_center_hz / 1_000_000.0,
            "requested_delta_deg": expected_delta,
            "measured_delta_deg": measured_delta,
            "phase_error_deg": phase_error,
            "epoch_before": int(zero_cfg["dac_phase_epoch"]),
            "epoch_after": int(phase_cfg["dac_phase_epoch"]),
        },
        "rates": {
            "udp_dry_run": bool(rates["udp_dry_run"]),
            "qsfp_link_up": bool(rates["qsfp_link_up"]),
            **rate_values,
        },
        "errors": errors,
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
