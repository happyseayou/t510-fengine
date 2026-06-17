#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path
from typing import Any


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _add_repo_python_path() -> None:
    sys.path.insert(0, str(_repo_root()))


def _parse_int(value: str) -> int:
    return int(value, 0)


def _parse_float_list(value: str) -> list[float]:
    items = [item.strip() for item in value.split(",") if item.strip()]
    if not items:
        raise argparse.ArgumentTypeError("expected a comma-separated float list")
    return [float(item) for item in items]


def _wrap_phase_deg(value: float) -> float:
    while value > 180.0:
        value -= 360.0
    while value <= -180.0:
        value += 360.0
    return value


def _jsonable(value: Any) -> Any:
    try:
        import numpy as np
    except ImportError:
        np = None  # type: ignore[assignment]
    if np is not None:
        if isinstance(value, np.ndarray):
            return value.tolist()
        if isinstance(value, np.generic):
            return value.item()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _phase_stats(values: list[float]) -> dict[str, float]:
    if not values:
        return {
            "count": 0,
            "first_deg": 0.0,
            "mean_relative_deg": 0.0,
            "peak_to_peak_deg": float("inf"),
            "max_abs_from_first_deg": float("inf"),
            "rms_relative_deg": float("inf"),
        }
    rel = [_wrap_phase_deg(value - values[0]) for value in values]
    mean_rel = sum(rel) / len(rel)
    rms_rel = math.sqrt(sum((value - mean_rel) ** 2 for value in rel) / len(rel))
    return {
        "count": len(values),
        "first_deg": float(values[0]),
        "mean_relative_deg": float(mean_rel),
        "peak_to_peak_deg": float(max(rel) - min(rel)),
        "max_abs_from_first_deg": float(max(abs(value) for value in rel)),
        "rms_relative_deg": float(rms_rel),
    }


def _scalar_stats(values: list[float]) -> dict[str, float]:
    if not values:
        return {"count": 0, "mean": 0.0, "min": 0.0, "max": 0.0, "peak_to_peak": float("inf")}
    mean_value = sum(values) / len(values)
    return {
        "count": len(values),
        "mean": float(mean_value),
        "min": float(min(values)),
        "max": float(max(values)),
        "peak_to_peak": float(max(values) - min(values)),
    }


def _wait_streaming(core, mask: int, timeout: float) -> dict[str, int]:
    deadline = time.monotonic() + timeout
    status = core.read_status()
    while time.monotonic() < deadline:
        status = core.read_status()
        if status["streaming"] and (status["rfdc_current_valid_mask"] & mask) == mask:
            return status
        time.sleep(0.02)
    return status


def _prepare_core(core_cls, args, *, phase_deg: float = 0.0):
    signal_hz = float(args.signal_mhz) * 1_000_000.0
    center_hz = float(args.center_mhz) * 1_000_000.0
    bw_hz = float(args.bw_mhz) * 1_000_000.0
    core = core_cls(args.bitfile, download=not args.no_download)
    config = core.apply_observation_instrument_config(
        observe_center_hz=center_hz,
        dac_signal_hz=signal_hz,
        view_bw_hz=bw_hz,
        amplitude=int(args.amplitude),
        phase_deg=float(phase_deg),
        enable_mask=0x01,
        adc_active_mask=int(args.adc_port_mask),
        initialize=True,
        start=True,
    )
    status = _wait_streaming(core, int(args.adc_port_mask), float(args.timeout))
    return core, config, status


def _phase_from_preview(core_cls, preview: dict[str, Any], args, *, phase_deg: float) -> dict[str, Any]:
    return core_cls.compute_phase_provenance(
        preview,
        observe_center_hz=float(args.center_mhz) * 1_000_000.0,
        view_bw_hz=float(args.bw_mhz) * 1_000_000.0,
        dac_signal_hz=float(args.signal_mhz) * 1_000_000.0,
        configured_phase_deg=float(phase_deg),
        display_phase_deg=float(phase_deg),
        phase_ref_input=0,
        oversample=float(args.oversample),
    )


def _record_from_provenance(provenance: dict[str, Any], status: dict[str, int] | None = None) -> dict[str, Any]:
    ch0 = provenance["channels"].get(0) or provenance["channels"].get("0")
    if ch0 is None:
        return {
            "sample0": int(provenance["sample0"]),
            "error": "missing CH0 provenance",
        }
    item = {
        "sample0": int(provenance["sample0"]),
        "configured_phase_deg": float(ch0["configured_phase_deg"]),
        "measured_fft_phase_deg": float(ch0["measured_fft_phase_deg"]),
        "sample0_correction_deg": float(ch0["sample0_correction_deg"]),
        "sample0_coherent_phase_deg": float(ch0["sample0_coherent_phase_deg"]),
        "display_rf_phase_deg": float(ch0["display_rf_phase_deg"]),
        "raw_baseband_mhz": float(ch0["raw_baseband_mhz"]),
        "rf_peak_mhz": float(ch0["rf_peak_mhz"]),
        "amplitude_code": float(ch0["amplitude_code"]),
        "rms_code": float(ch0["rms_code"]),
        "max_abs_code": float(ch0["max_abs_code"]),
        "snr_db": float(ch0["snr_db"]),
        "fit_residual_fraction": float(ch0["fit_residual_fraction"]),
        "clipped": bool(ch0["clipped"]),
    }
    if status is not None:
        item.update(
            {
                "rfdc_status_flags": int(status.get("rfdc_status_flags", 0)),
                "rfdc_sample_count": int(status.get("rfdc_sample_count", 0)),
                "preview_capture_count": int(status.get("preview_capture_count", 0)),
                "dac_phase_epoch": int(status.get("dac_phase_epoch", 0)),
                "tx_dry_run_packet_count": int(status.get("tx_dry_run_packet_count", 0)),
                "tx_frame_built_count": int(status.get("tx_frame_built_count", 0)),
            }
        )
    return item


def _summarize_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    measured = [float(item["measured_fft_phase_deg"]) for item in records if "measured_fft_phase_deg" in item]
    coherent = [float(item["sample0_coherent_phase_deg"]) for item in records if "sample0_coherent_phase_deg" in item]
    display = [float(item["display_rf_phase_deg"]) for item in records if "display_rf_phase_deg" in item]
    amplitude = [float(item["amplitude_code"]) for item in records if "amplitude_code" in item]
    rms = [float(item["rms_code"]) for item in records if "rms_code" in item]
    max_abs = [float(item["max_abs_code"]) for item in records if "max_abs_code" in item]
    sample0 = [int(item["sample0"]) for item in records if "sample0" in item]
    sample0_deltas = [float(sample0[idx] - sample0[idx - 1]) for idx in range(1, len(sample0))]
    return {
        "frames": len(records),
        "measured_fft_phase": _phase_stats(measured),
        "sample0_coherent_phase": _phase_stats(coherent),
        "display_rf_phase": _phase_stats(display),
        "amplitude_code": _scalar_stats(amplitude),
        "rms_code": _scalar_stats(rms),
        "max_abs_code": _scalar_stats(max_abs),
        "sample0": {
            "first": int(sample0[0]) if sample0 else 0,
            "last": int(sample0[-1]) if sample0 else 0,
            "monotonic": all(sample0[idx] > sample0[idx - 1] for idx in range(1, len(sample0))),
            "delta": _scalar_stats(sample0_deltas),
        },
    }


def _aligned_from_preview(core_cls, preview: dict[str, Any], args, *, phase_deg: float, anchor_deg=None) -> dict[str, Any]:
    return core_cls.compute_sample0_aligned_phase_view(
        preview,
        observe_center_hz=float(args.center_mhz) * 1_000_000.0,
        dac_signal_hz=float(args.signal_mhz) * 1_000_000.0,
        configured_phase_deg=float(phase_deg),
        alignment_anchor_deg=anchor_deg,
        phase_ref_input=0,
        time_window_us=float(args.time_window_us),
        display_points=int(args.aligned_display_points),
        fft_oversample=float(args.oversample),
    )


def _record_from_aligned(view: dict[str, Any], status: dict[str, int] | None = None) -> dict[str, Any]:
    ch0 = view["channels"].get(0) or view["channels"].get("0")
    if ch0 is None:
        return {
            "sample0": int(view["sample0"]),
            "error": "missing CH0 aligned view",
        }
    item = {
        "sample0": int(view["sample0"]),
        "configured_phase_deg": float(ch0["configured_phase_deg"]),
        "expected_tone_measured_phase_deg": float(ch0["expected_tone_measured_phase_deg"]),
        "sample0_mod_phase_deg": float(ch0["sample0_mod_phase_deg"]),
        "sample0_aligned_phase_deg": float(ch0["sample0_aligned_phase_deg"]),
        "alignment_anchor_deg": float(ch0["alignment_anchor_deg"]),
        "phase_error_deg": float(ch0["phase_error_deg"]),
        "display_reference_phase_deg": float(ch0["display_reference_phase_deg"]),
        "measured_display_phase_deg": float(ch0["measured_display_phase_deg"]),
        "anchor_candidate_deg": float(ch0["anchor_candidate_deg"]),
        "expected_baseband_mhz": float(ch0["expected_baseband_mhz"]),
        "fft_peak_mhz": float(ch0["fft_peak_mhz"]),
        "fft_peak_phase_deg": float(ch0["fft_peak_phase_deg"]),
        "amplitude_code": float(ch0["amplitude_code"]),
        "rms_code": float(ch0["rms_code"]),
        "max_abs_code": float(ch0["max_abs_code"]),
        "snr_db": float(ch0["snr_db"]),
        "fit_residual_fraction": float(ch0["fit_residual_fraction"]),
        "clipped": bool(ch0["clipped"]),
    }
    if status is not None:
        item.update(
            {
                "rfdc_status_flags": int(status.get("rfdc_status_flags", 0)),
                "rfdc_sample_count": int(status.get("rfdc_sample_count", 0)),
                "preview_capture_count": int(status.get("preview_capture_count", 0)),
                "dac_phase_epoch": int(status.get("dac_phase_epoch", 0)),
                "tx_dry_run_packet_count": int(status.get("tx_dry_run_packet_count", 0)),
                "tx_frame_built_count": int(status.get("tx_frame_built_count", 0)),
            }
        )
    return item


def _summarize_aligned_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    phase_error = [float(item["phase_error_deg"]) for item in records if "phase_error_deg" in item]
    aligned = [float(item["sample0_aligned_phase_deg"]) for item in records if "sample0_aligned_phase_deg" in item]
    expected_phase = [
        float(item["expected_tone_measured_phase_deg"])
        for item in records
        if "expected_tone_measured_phase_deg" in item
    ]
    amplitude = [float(item["amplitude_code"]) for item in records if "amplitude_code" in item]
    rms = [float(item["rms_code"]) for item in records if "rms_code" in item]
    max_abs = [float(item["max_abs_code"]) for item in records if "max_abs_code" in item]
    residual = [float(item["fit_residual_fraction"]) for item in records if "fit_residual_fraction" in item]
    sample0 = [int(item["sample0"]) for item in records if "sample0" in item]
    sample0_deltas = [float(sample0[idx] - sample0[idx - 1]) for idx in range(1, len(sample0))]
    spike_count = sum(1 for value in max_abs if value >= 0.9 * 32768.0)
    return {
        "frames": len(records),
        "phase_error": _phase_stats(phase_error),
        "sample0_aligned_phase": _phase_stats(aligned),
        "expected_tone_measured_phase": _phase_stats(expected_phase),
        "amplitude_code": _scalar_stats(amplitude),
        "rms_code": _scalar_stats(rms),
        "max_abs_code": _scalar_stats(max_abs),
        "fit_residual_fraction": _scalar_stats(residual),
        "large_signal_frames": int(spike_count),
        "sample0": {
            "first": int(sample0[0]) if sample0 else 0,
            "last": int(sample0[-1]) if sample0 else 0,
            "monotonic": all(sample0[idx] > sample0[idx - 1] for idx in range(1, len(sample0))),
            "delta": _scalar_stats(sample0_deltas),
        },
    }


def _save_preview(args, mode: str, frame_idx: int, preview: dict[str, Any], provenance: dict[str, Any]) -> None:
    if int(args.save_raw_frames) <= 0 or frame_idx >= int(args.save_raw_frames):
        return
    try:
        import numpy as np
    except ImportError:
        return
    save_dir = Path(args.save_dir)
    save_dir.mkdir(parents=True, exist_ok=True)
    arrays = {f"ch{idx}_iq": np.asarray(iq, dtype=np.int16) for idx, iq in preview["iq"].items()}
    meta = {
        "mode": mode,
        "frame": frame_idx,
        "sample0": int(preview["sample0"]),
        "sample_rate_hz": float(preview["sample_rate_hz"]),
        "provenance_ch0": _record_from_provenance(provenance),
    }
    np.savez_compressed(save_dir / f"{mode}_frame_{frame_idx:04d}.npz", meta=json.dumps(meta), **arrays)


def _run_synthetic(core_cls, args) -> tuple[int, dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for frame_idx in range(max(1, int(args.frames))):
        preview = core_cls.synthetic_phase_frame(
            n=int(args.samples),
            input_mask=0x01,
            sample0=frame_idx * int(args.samples),
            observe_center_hz=float(args.center_mhz) * 1_000_000.0,
            dac_signal_hz=float(args.signal_mhz) * 1_000_000.0,
            amplitude=float(args.amplitude),
            phase_deg=float(args.configured_phase_deg),
            noise_rms=float(args.synthetic_noise_rms),
        )
        provenance = _phase_from_preview(core_cls, preview, args, phase_deg=float(args.configured_phase_deg))
        records.append(_record_from_provenance(provenance))
    summary = _summarize_records(records)
    errors: list[str] = []
    if summary["sample0_coherent_phase"]["max_abs_from_first_deg"] > float(args.synthetic_phase_jitter_deg):
        errors.append(
            "synthetic sample0-coherent phase jitter "
            f"{summary['sample0_coherent_phase']['max_abs_from_first_deg']:.6f} deg exceeds "
            f"{float(args.synthetic_phase_jitter_deg):.6f} deg"
        )
    result = {
        "result": "PASS" if not errors else "FAIL",
        "mode": "synthetic",
        "signal_mhz": float(args.signal_mhz),
        "center_mhz": float(args.center_mhz),
        "samples": int(args.samples),
        "summary": summary,
        "first_records": records[:3],
        "last_records": records[-3:] if len(records) > 3 else records,
        "errors": errors,
    }
    return (0 if not errors else 1), result


def _run_frozen_frame(core_cls, args) -> tuple[int, dict[str, Any]]:
    core, config, status = _prepare_core(core_cls, args, phase_deg=float(args.configured_phase_deg))
    errors: list[str] = []
    if int(status["core_version"]) != 0x0001_0007:
        errors.append(f"expected CORE_VERSION=0x00010007, got 0x{int(status['core_version']):08x}")
    if not status["streaming"]:
        errors.append("F-engine did not enter streaming")
    preview = core.capture_preview_fast(n=int(args.samples), input_mask=0x01, timeout=float(args.timeout))
    records: list[dict[str, Any]] = []
    for frame_idx in range(max(1, int(args.frames))):
        provenance = _phase_from_preview(core_cls, preview, args, phase_deg=float(args.configured_phase_deg))
        _save_preview(args, "frozen_frame", frame_idx, preview, provenance)
        records.append(_record_from_provenance(provenance))
    summary = _summarize_records(records)
    if summary["sample0_coherent_phase"]["max_abs_from_first_deg"] > float(args.frozen_phase_jitter_deg):
        errors.append(
            "frozen-frame phase changed under repeated backend recompute: "
            f"{summary['sample0_coherent_phase']['max_abs_from_first_deg']:.6f} deg"
        )
    result = {
        "result": "PASS" if not errors else "FAIL",
        "mode": "frozen_frame",
        "core_version": f"0x{int(status['core_version']):08x}",
        "streaming": bool(status["streaming"]),
        "config": config,
        "summary": summary,
        "first_records": records[:3],
        "last_records": records[-3:] if len(records) > 3 else records,
        "errors": errors,
    }
    return (0 if not errors else 1), result


def _run_repeated_preview(core_cls, args) -> tuple[int, dict[str, Any]]:
    core, config, status = _prepare_core(core_cls, args, phase_deg=float(args.configured_phase_deg))
    errors: list[str] = []
    if int(status["core_version"]) != 0x0001_0007:
        errors.append(f"expected CORE_VERSION=0x00010007, got 0x{int(status['core_version']):08x}")
    if not status["streaming"]:
        errors.append("F-engine did not enter streaming")
    records: list[dict[str, Any]] = []
    deadline = time.monotonic() + max(0.0, float(args.seconds))
    frame_idx = 0
    while frame_idx < max(1, int(args.frames)) or time.monotonic() < deadline:
        preview = core.capture_preview_fast(n=int(args.samples), input_mask=0x01, timeout=float(args.timeout))
        status_now = core.read_status()
        provenance = _phase_from_preview(core_cls, preview, args, phase_deg=float(args.configured_phase_deg))
        _save_preview(args, "repeated_preview", frame_idx, preview, provenance)
        records.append(_record_from_provenance(provenance, status_now))
        frame_idx += 1
        if float(args.seconds) <= 0.0 and frame_idx >= max(1, int(args.frames)):
            break
        time.sleep(max(0.0, float(args.frame_interval_s)))
    summary = _summarize_records(records)
    coherent_jitter = float(summary["sample0_coherent_phase"]["max_abs_from_first_deg"])
    classification = (
        "hardware_or_sampling_path_jitter"
        if coherent_jitter > float(args.repeated_phase_jitter_warn_deg)
        else "raw_phase_stable_within_threshold"
    )
    result = {
        "result": "PASS" if not errors else "FAIL",
        "mode": "repeated_preview",
        "classification": classification,
        "core_version": f"0x{int(status['core_version']):08x}",
        "streaming": bool(status["streaming"]),
        "config": config,
        "summary": summary,
        "first_records": records[:3],
        "last_records": records[-3:] if len(records) > 3 else records,
        "errors": errors,
    }
    return (0 if not errors else 1), result


def _run_readback_consistency(core_cls, args) -> tuple[int, dict[str, Any]]:
    core, config, status = _prepare_core(core_cls, args, phase_deg=float(args.configured_phase_deg))
    errors: list[str] = []
    if int(status["core_version"]) != 0x0001_0007:
        errors.append(f"expected CORE_VERSION=0x00010007, got 0x{int(status['core_version']):08x}")
    checks = []
    mismatch_frames = 0
    mismatch_words = 0
    for frame_idx in range(max(1, int(args.frames))):
        check = core.capture_preview_readback_check(
            n=int(args.samples),
            input_mask=0x01,
            timeout=float(args.timeout),
            include_data=frame_idx < int(args.save_raw_frames),
        )
        if not bool(check["match"]):
            mismatch_frames += 1
            mismatch_words += int(check["mismatch_count"])
        check_no_data = {key: value for key, value in check.items() if key not in ("first_preview", "second_preview")}
        checks.append(check_no_data)
        if frame_idx < int(args.save_raw_frames) and "first_preview" in check:
            provenance = _phase_from_preview(core_cls, check["first_preview"], args, phase_deg=float(args.configured_phase_deg))
            _save_preview(args, "readback_consistency", frame_idx, check["first_preview"], provenance)
    if mismatch_frames:
        errors.append(f"{mismatch_frames} capture buffers changed between two reads ({mismatch_words} mismatches)")
    result = {
        "result": "PASS" if not errors else "FAIL",
        "mode": "readback_consistency",
        "core_version": f"0x{int(status['core_version']):08x}",
        "streaming": bool(status["streaming"]),
        "config": config,
        "frames": len(checks),
        "mismatch_frames": mismatch_frames,
        "mismatch_count": mismatch_words,
        "first_checks": checks[:3],
        "last_checks": checks[-3:] if len(checks) > 3 else checks,
        "errors": errors,
    }
    return (0 if not errors else 1), result


def _run_phase_step(core_cls, args) -> tuple[int, dict[str, Any]]:
    phases = _parse_float_list(args.phase_deg)
    core, config, status = _prepare_core(core_cls, args, phase_deg=float(phases[0]))
    errors: list[str] = []
    warnings: list[str] = []
    if int(status["core_version"]) != 0x0001_0007:
        errors.append(f"expected CORE_VERSION=0x00010007, got 0x{int(status['core_version']):08x}")
    results = []
    previous_epoch = int(config["dac_phase_epoch"])
    first_mean = None
    for step_idx, phase in enumerate(phases):
        step_config = core.apply_observation_instrument_config(
            observe_center_hz=float(args.center_mhz) * 1_000_000.0,
            dac_signal_hz=float(args.signal_mhz) * 1_000_000.0,
            view_bw_hz=float(args.bw_mhz) * 1_000_000.0,
            amplitude=int(args.amplitude),
            phase_deg=float(phase),
            enable_mask=0x01,
            adc_active_mask=int(args.adc_port_mask),
            initialize=False,
            start=False,
        )
        time.sleep(max(0.0, float(args.settle_s)))
        records: list[dict[str, Any]] = []
        deadline = time.monotonic() + max(0.0, float(args.seconds_per_step))
        frame_idx = 0
        while frame_idx < max(1, int(args.frames_per_step)) or time.monotonic() < deadline:
            preview = core.capture_preview_fast(n=int(args.samples), input_mask=0x01, timeout=float(args.timeout))
            status_now = core.read_status()
            provenance = _phase_from_preview(core_cls, preview, args, phase_deg=float(phase))
            _save_preview(args, f"phase_step_{step_idx}", frame_idx, preview, provenance)
            records.append(_record_from_provenance(provenance, status_now))
            frame_idx += 1
            if float(args.seconds_per_step) <= 0.0 and frame_idx >= max(1, int(args.frames_per_step)):
                break
            time.sleep(max(0.0, float(args.frame_interval_s)))
        summary = _summarize_records(records)
        coherent_values = [float(item["sample0_coherent_phase_deg"]) for item in records]
        coherent_mean = float(coherent_values[0]) if coherent_values else 0.0
        if first_mean is None:
            first_mean = coherent_mean
        measured_delta = _wrap_phase_deg(coherent_mean - first_mean)
        requested_delta = _wrap_phase_deg(float(phase) - float(phases[0]))
        display_delta = _wrap_phase_deg(float(summary["display_rf_phase"]["first_deg"]) - float(phases[0]))
        measured_error = abs(_wrap_phase_deg(measured_delta - requested_delta))
        measured_jitter = float(summary["sample0_coherent_phase"]["max_abs_from_first_deg"])
        epoch = int(step_config["dac_phase_epoch"])
        if step_idx > 0 and epoch <= previous_epoch:
            errors.append(f"DAC phase epoch did not increase at phase {phase:.1f} deg")
        previous_epoch = epoch
        if step_idx > 0 and measured_error > float(args.phase_follow_warn_deg):
            warnings.append(
                f"measured sample0-coherent phase delta {measured_delta:.2f} deg did not follow "
                f"requested {requested_delta:.2f} deg at phase {phase:.1f} deg"
            )
        if measured_jitter > float(args.repeated_phase_jitter_warn_deg):
            warnings.append(
                f"phase {phase:.1f} deg raw sample0-coherent jitter {measured_jitter:.2f} deg "
                f"exceeds {float(args.repeated_phase_jitter_warn_deg):.2f} deg"
            )
        results.append(
            {
                "requested_phase_deg": float(phase),
                "requested_delta_deg": requested_delta,
                "measured_first_delta_deg": measured_delta,
                "measured_delta_error_deg": measured_error,
                "measured_follows_request": measured_error <= float(args.phase_follow_warn_deg),
                "display_delta_deg": display_delta,
                "display_follows_request": abs(_wrap_phase_deg(display_delta - requested_delta)) <= 0.25,
                "phase_epoch": epoch,
                "summary": summary,
            }
        )
    result = {
        "result": "PASS" if not errors else "FAIL",
        "mode": "phase_step",
        "core_version": f"0x{int(status['core_version']):08x}",
        "streaming": bool(status["streaming"]),
        "initial_config": config,
        "steps": results,
        "warnings": warnings,
        "errors": errors,
    }
    return (0 if not errors else 1), result


def _run_sample0_aligned_preview(core_cls, args) -> tuple[int, dict[str, Any]]:
    errors: list[str] = []
    warnings: list[str] = []
    signal_hz = float(args.signal_mhz) * 1_000_000.0
    center_hz = float(args.center_mhz) * 1_000_000.0
    configured_phase = float(args.configured_phase_deg)

    synthetic_records: list[dict[str, Any]] = []
    for frame_idx in range(max(1, int(args.frames))):
        preview = core_cls.synthetic_phase_frame(
            n=int(args.samples),
            input_mask=0x01,
            sample0=frame_idx * int(args.samples),
            observe_center_hz=center_hz,
            dac_signal_hz=signal_hz,
            amplitude=float(args.amplitude),
            phase_deg=configured_phase,
            noise_rms=0.0,
        )
        view = _aligned_from_preview(core_cls, preview, args, phase_deg=configured_phase, anchor_deg=0.0)
        synthetic_records.append(_record_from_aligned(view))
    synthetic_summary = _summarize_aligned_records(synthetic_records)
    if float(synthetic_summary["phase_error"]["peak_to_peak_deg"]) > float(args.aligned_synthetic_jitter_deg):
        errors.append(
            "synthetic fixed sample0-aligned phase p-p "
            f"{float(synthetic_summary['phase_error']['peak_to_peak_deg']):.6f} deg exceeds "
            f"{float(args.aligned_synthetic_jitter_deg):.6f} deg"
        )

    phase_step_records = []
    for phase in _parse_float_list(args.phase_deg):
        preview = core_cls.synthetic_phase_frame(
            n=int(args.samples),
            input_mask=0x01,
            sample0=int(args.samples) * 3,
            observe_center_hz=center_hz,
            dac_signal_hz=signal_hz,
            amplitude=float(args.amplitude),
            phase_deg=float(phase),
            noise_rms=0.0,
        )
        view = _aligned_from_preview(core_cls, preview, args, phase_deg=float(phase), anchor_deg=0.0)
        rec = _record_from_aligned(view)
        phase_step_records.append(rec)
        if abs(_wrap_phase_deg(float(rec["phase_error_deg"]))) > float(args.aligned_synthetic_jitter_deg):
            errors.append(
                f"synthetic phase step {phase:.1f} deg produced residual {float(rec['phase_error_deg']):.6f} deg"
            )

    drift_preview = core_cls.synthetic_phase_frame(
        n=int(args.samples),
        input_mask=0x01,
        sample0=int(args.samples) * 7,
        observe_center_hz=center_hz,
        dac_signal_hz=signal_hz,
        amplitude=float(args.amplitude),
        phase_deg=configured_phase + float(args.injected_drift_deg),
        noise_rms=0.0,
    )
    drift_view = _aligned_from_preview(core_cls, drift_preview, args, phase_deg=configured_phase, anchor_deg=0.0)
    drift_record = _record_from_aligned(drift_view)
    drift_error = abs(_wrap_phase_deg(float(drift_record["phase_error_deg"]) - float(args.injected_drift_deg)))
    if drift_error > float(args.injected_drift_tol_deg):
        errors.append(
            f"synthetic injected drift measured {float(drift_record['phase_error_deg']):.3f} deg, "
            f"expected {float(args.injected_drift_deg):.3f} deg"
        )

    core, config, status = _prepare_core(core_cls, args, phase_deg=configured_phase)
    if int(status["core_version"]) != 0x0001_0007:
        errors.append(f"expected CORE_VERSION=0x00010007, got 0x{int(status['core_version']):08x}")
    if not status["streaming"]:
        errors.append("F-engine did not enter streaming")

    frozen_preview = core.capture_preview_fast(n=int(args.samples), input_mask=0x01, timeout=float(args.timeout))
    first_frozen = _aligned_from_preview(core_cls, frozen_preview, args, phase_deg=configured_phase, anchor_deg=0.0)
    frozen_anchor = float((first_frozen["channels"].get(0) or first_frozen["channels"].get("0"))["anchor_candidate_deg"])
    frozen_records: list[dict[str, Any]] = []
    for frame_idx in range(max(1, int(args.frames))):
        view = _aligned_from_preview(core_cls, frozen_preview, args, phase_deg=configured_phase, anchor_deg=frozen_anchor)
        frozen_records.append(_record_from_aligned(view))
    frozen_summary = _summarize_aligned_records(frozen_records)
    if float(frozen_summary["phase_error"]["peak_to_peak_deg"]) > float(args.aligned_frozen_jitter_deg):
        errors.append(
            "frozen hardware frame sample0-aligned phase changed by "
            f"{float(frozen_summary['phase_error']['peak_to_peak_deg']):.6f} deg"
        )

    repeated_records: list[dict[str, Any]] = []
    repeated_anchor = None
    deadline = time.monotonic() + max(0.0, float(args.seconds))
    frame_idx = 0
    while frame_idx < max(1, int(args.repeated_frames)) or time.monotonic() < deadline:
        preview = core.capture_preview_fast(n=int(args.samples), input_mask=0x01, timeout=float(args.timeout))
        status_now = core.read_status()
        if repeated_anchor is None:
            first_view = _aligned_from_preview(core_cls, preview, args, phase_deg=configured_phase, anchor_deg=0.0)
            repeated_anchor = float((first_view["channels"].get(0) or first_view["channels"].get("0"))["anchor_candidate_deg"])
        view = _aligned_from_preview(core_cls, preview, args, phase_deg=configured_phase, anchor_deg=repeated_anchor)
        repeated_records.append(_record_from_aligned(view, status_now))
        frame_idx += 1
        if float(args.seconds) <= 0.0 and frame_idx >= max(1, int(args.repeated_frames)):
            break
        time.sleep(max(0.0, float(args.frame_interval_s)))
    repeated_summary = _summarize_aligned_records(repeated_records)
    repeated_jitter = float(repeated_summary["phase_error"]["max_abs_from_first_deg"])
    classification = (
        "sample0_aligned_live_phase_jitter"
        if repeated_jitter > float(args.repeated_phase_jitter_warn_deg)
        else "sample0_aligned_live_phase_stable_within_threshold"
    )
    if classification == "sample0_aligned_live_phase_jitter":
        warnings.append(
            f"repeated preview sample0-aligned phase max_abs_from_first={repeated_jitter:.2f} deg"
        )

    result = {
        "result": "PASS" if not errors else "FAIL",
        "mode": "sample0_aligned_preview",
        "classification": classification,
        "core_version": f"0x{int(status['core_version']):08x}",
        "streaming": bool(status["streaming"]),
        "config": config,
        "synthetic_fixed": {
            "summary": synthetic_summary,
            "first_records": synthetic_records[:3],
            "last_records": synthetic_records[-3:] if len(synthetic_records) > 3 else synthetic_records,
        },
        "synthetic_phase_step": phase_step_records,
        "synthetic_injected_drift": {
            "requested_drift_deg": float(args.injected_drift_deg),
            "record": drift_record,
            "error_deg": drift_error,
        },
        "frozen_frame": {
            "alignment_anchor_deg": frozen_anchor,
            "summary": frozen_summary,
            "first_records": frozen_records[:3],
            "last_records": frozen_records[-3:] if len(frozen_records) > 3 else frozen_records,
        },
        "repeated_preview": {
            "alignment_anchor_deg": repeated_anchor,
            "summary": repeated_summary,
            "first_records": repeated_records[:3],
            "last_records": repeated_records[-3:] if len(repeated_records) > 3 else repeated_records,
        },
        "warnings": warnings,
        "errors": errors,
    }
    return (0 if not errors else 1), result


def main() -> int:
    _add_repo_python_path()
    from python.t510_fengine import T510FEngine

    default_bitfile = _repo_root() / "overlay" / "t510_fengine.bit"
    parser = argparse.ArgumentParser(description="Stage 13/14 phase provenance and hardware design audit.")
    parser.add_argument(
        "--mode",
        choices=[
            "synthetic",
            "frozen_frame",
            "repeated_preview",
            "readback_consistency",
            "phase_step",
            "sample0_aligned_preview",
        ],
        required=True,
    )
    parser.add_argument("--bitfile", default=str(default_bitfile))
    parser.add_argument("--no-download", action="store_true")
    parser.add_argument("--signal-mhz", type=float, default=100.0)
    parser.add_argument("--center-mhz", type=float, default=100.0)
    parser.add_argument("--bw-mhz", type=float, default=100.0)
    parser.add_argument("--samples", type=int, default=512)
    parser.add_argument("--oversample", type=float, default=8.0)
    parser.add_argument("--frames", type=int, default=100)
    parser.add_argument("--seconds", type=float, default=0.0)
    parser.add_argument("--frame-interval-s", type=float, default=0.05)
    parser.add_argument("--seconds-per-step", type=float, default=5.0)
    parser.add_argument("--frames-per-step", type=int, default=1)
    parser.add_argument("--repeated-frames", type=int, default=1)
    parser.add_argument("--phase-deg", default="0,45,90,180")
    parser.add_argument("--configured-phase-deg", type=float, default=0.0)
    parser.add_argument("--amplitude", type=_parse_int, default=2048)
    parser.add_argument("--adc-port-mask", type=_parse_int, default=0x0003)
    parser.add_argument("--timeout", type=float, default=2.0)
    parser.add_argument("--settle-s", type=float, default=0.2)
    parser.add_argument("--synthetic-noise-rms", type=float, default=0.0)
    parser.add_argument("--synthetic-phase-jitter-deg", type=float, default=1.0e-6)
    parser.add_argument("--frozen-phase-jitter-deg", type=float, default=1.0e-6)
    parser.add_argument("--repeated-phase-jitter-warn-deg", type=float, default=15.0)
    parser.add_argument("--phase-follow-warn-deg", type=float, default=30.0)
    parser.add_argument("--time-window-us", type=float, default=0.25)
    parser.add_argument("--aligned-display-points", type=int, default=512)
    parser.add_argument("--aligned-synthetic-jitter-deg", type=float, default=0.01)
    parser.add_argument("--aligned-frozen-jitter-deg", type=float, default=0.01)
    parser.add_argument("--injected-drift-deg", type=float, default=30.0)
    parser.add_argument("--injected-drift-tol-deg", type=float, default=1.0)
    parser.add_argument("--save-dir", default=str(_repo_root() / "reports" / "runtime" / "stage13"))
    parser.add_argument("--save-raw-frames", type=int, default=3)
    args = parser.parse_args()

    dispatch = {
        "synthetic": _run_synthetic,
        "frozen_frame": _run_frozen_frame,
        "repeated_preview": _run_repeated_preview,
        "readback_consistency": _run_readback_consistency,
        "phase_step": _run_phase_step,
        "sample0_aligned_preview": _run_sample0_aligned_preview,
    }
    rc, summary = dispatch[args.mode](T510FEngine, args)
    print(json.dumps(_jsonable(summary), indent=2, sort_keys=True))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
