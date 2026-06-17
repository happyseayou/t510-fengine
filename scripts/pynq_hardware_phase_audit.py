#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path
from typing import Any


EXPECTED_CORE_VERSION = 0x0001_0008
PREVIEW_SAMPLE_RATE_HZ = 245_760_000.0
INTERNAL_DDS_BASEBAND_HZ = PREVIEW_SAMPLE_RATE_HZ / 16.0
INTERNAL_DDS_COMPLEX_SIGN = -1.0


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _add_repo_python_path() -> None:
    sys.path.insert(0, str(_repo_root()))


def _parse_int(value: str) -> int:
    return int(value, 0)


def _parse_float_list(value: str) -> list[float]:
    items = [item.strip() for item in value.split(",") if item.strip()]
    if not items:
        raise argparse.ArgumentTypeError("expected comma-separated float list")
    return [float(item) for item in items]


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


def _wrap_phase_deg(value: float) -> float:
    while value > 180.0:
        value -= 360.0
    while value <= -180.0:
        value += 360.0
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


def _prepare_core(core_cls, args):
    signal_hz = float(args.signal_mhz) * 1_000_000.0
    center_hz = float(args.center_mhz) * 1_000_000.0
    bw_hz = float(args.bw_mhz) * 1_000_000.0
    core = core_cls(args.bitfile, download=not args.no_download)
    config = core.apply_observation_instrument_config(
        observe_center_hz=center_hz,
        dac_signal_hz=signal_hz,
        view_bw_hz=bw_hz,
        amplitude=int(args.amplitude),
        phase_deg=float(args.configured_phase_deg),
        enable_mask=0x01,
        adc_active_mask=int(args.adc_port_mask),
        initialize=True,
        start=True,
    )
    status = _wait_streaming(core, int(args.adc_port_mask), float(args.timeout))
    return core, config, status


def _record_from_view(view: dict[str, Any], status: dict[str, Any], audit: dict[str, Any]) -> dict[str, Any]:
    ch0 = view["channels"].get(0) or view["channels"].get("0")
    if ch0 is None:
        return {"sample0": int(view["sample0"]), "error": "missing CH0 sample0-aligned view"}
    return {
        "sample0": int(view["sample0"]),
        "sample0_aligned_phase_deg": float(ch0["sample0_aligned_phase_deg"]),
        "phase_error_deg": float(ch0["phase_error_deg"]),
        "expected_tone_measured_phase_deg": float(ch0["expected_tone_measured_phase_deg"]),
        "sample0_mod_phase_deg": float(ch0["sample0_mod_phase_deg"]),
        "amplitude_code": float(ch0["amplitude_code"]),
        "rms_code": float(ch0["rms_code"]),
        "max_abs_code": float(ch0["max_abs_code"]),
        "snr_db": float(ch0["snr_db"]),
        "fit_residual_fraction": float(ch0["fit_residual_fraction"]),
        "clipped": bool(ch0["clipped"]),
        "rfdc_status_flags": int(status.get("rfdc_status_flags", 0)),
        "rfdc_sample_count": int(status.get("rfdc_sample_count", 0)),
        "preview_capture_count": int(status.get("preview_capture_count", 0)),
        "dac_phase_epoch": int(status.get("dac_phase_epoch", 0)),
        "audit_source": str(audit.get("source", "unknown")),
        "audit_start_count": int(audit.get("start_count", 0)),
        "audit_first_count": int(audit.get("first_count", 0)),
        "audit_done_count": int(audit.get("done_count", 0)),
        "audit_valid_gap_count": int(audit.get("valid_gap_count", 0)),
        "audit_sample0_error_count": int(audit.get("sample0_error_count", 0)),
        "audit_event_valid": bool(audit.get("event_valid", False)),
        "audit_event_max_code": int(audit.get("event_max_code", 0)),
    }


def _summarize_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    phase = [float(item["phase_error_deg"]) for item in records if "phase_error_deg" in item]
    aligned = [float(item["sample0_aligned_phase_deg"]) for item in records if "sample0_aligned_phase_deg" in item]
    amplitude = [float(item["amplitude_code"]) for item in records if "amplitude_code" in item]
    rms = [float(item["rms_code"]) for item in records if "rms_code" in item]
    max_abs = [float(item["max_abs_code"]) for item in records if "max_abs_code" in item]
    residual = [float(item["fit_residual_fraction"]) for item in records if "fit_residual_fraction" in item]
    sample0 = [int(item["sample0"]) for item in records if "sample0" in item]
    sample0_deltas = [float(sample0[idx] - sample0[idx - 1]) for idx in range(1, len(sample0))]
    return {
        "frames": len(records),
        "phase_error": _phase_stats(phase),
        "sample0_aligned_phase": _phase_stats(aligned),
        "amplitude_code": _scalar_stats(amplitude),
        "rms_code": _scalar_stats(rms),
        "max_abs_code": _scalar_stats(max_abs),
        "fit_residual_fraction": _scalar_stats(residual),
        "large_signal_frames": int(sum(1 for value in max_abs if value >= 0.9 * 32768.0)),
        "sample0": {
            "first": int(sample0[0]) if sample0 else 0,
            "last": int(sample0[-1]) if sample0 else 0,
            "monotonic": all(sample0[idx] > sample0[idx - 1] for idx in range(1, len(sample0))),
            "delta": _scalar_stats(sample0_deltas),
        },
        "audit": {
            "valid_gap_count_max": int(max((item.get("audit_valid_gap_count", 0) for item in records), default=0)),
            "sample0_error_count_max": int(max((item.get("audit_sample0_error_count", 0) for item in records), default=0)),
        },
    }


def _sample0_aligned_view(core_cls, preview: dict[str, Any], args, *, signal_hz: float, center_hz: float, anchor_deg):
    return core_cls.compute_sample0_aligned_phase_view(
        preview,
        observe_center_hz=center_hz,
        dac_signal_hz=signal_hz,
        configured_phase_deg=float(args.configured_phase_deg),
        alignment_anchor_deg=anchor_deg,
        phase_ref_input=0,
        time_window_us=float(args.time_window_us),
        display_points=256,
        fft_oversample=float(args.oversample),
    )


def _capture_phase_source(
    core_cls,
    core,
    args,
    *,
    source: str,
    signal_hz: float,
    center_hz: float,
    frames: int,
) -> dict[str, Any]:
    core.configure_preview_audit(
        source=source,
        event_enable=False,
        freeze_on_event=True,
        event_threshold=int(args.event_threshold),
        clear=True,
    )
    time.sleep(0.05)
    records: list[dict[str, Any]] = []
    anchor = None
    for _ in range(max(1, int(frames))):
        preview = core.capture_preview_fast(n=int(args.samples), input_mask=0x01, timeout=float(args.timeout))
        status = core.read_status()
        audit = core.read_preview_audit_status()
        if anchor is None:
            first_view = _sample0_aligned_view(core_cls, preview, args, signal_hz=signal_hz, center_hz=center_hz, anchor_deg=0.0)
            ch0 = first_view["channels"].get(0) or first_view["channels"].get("0")
            anchor = float(ch0["anchor_candidate_deg"]) if ch0 is not None else 0.0
        view = _sample0_aligned_view(core_cls, preview, args, signal_hz=signal_hz, center_hz=center_hz, anchor_deg=anchor)
        records.append(_record_from_view(view, status, audit))
        time.sleep(max(0.0, float(args.frame_interval_s)))
    summary = _summarize_records(records)
    errors: list[str] = []
    warnings: list[str] = []
    if summary["audit"]["valid_gap_count_max"]:
        errors.append(f"{source} preview valid gap count became {summary['audit']['valid_gap_count_max']}")
    if summary["audit"]["sample0_error_count_max"]:
        errors.append(f"{source} preview sample0 step error count became {summary['audit']['sample0_error_count_max']}")
    jitter = float(summary["phase_error"]["max_abs_from_first_deg"])
    if source != "rfdc" and jitter > float(args.internal_phase_jitter_deg):
        errors.append(f"{source} sample0-aligned phase jitter {jitter:.3f} deg exceeds {float(args.internal_phase_jitter_deg):.3f} deg")
    if source == "rfdc" and jitter > float(args.rfdc_phase_jitter_warn_deg):
        warnings.append(f"RFDC source sample0-aligned phase jitter {jitter:.2f} deg exceeds warning threshold")
    return {
        "result": "PASS" if not errors else "FAIL",
        "source": source,
        "signal_hz_used_for_fit": float(signal_hz),
        "center_hz_used_for_fit": float(center_hz),
        "expected_baseband_hz": float(signal_hz - center_hz),
        "alignment_anchor_deg": anchor,
        "summary": summary,
        "first_records": records[:3],
        "last_records": records[-3:] if len(records) > 3 else records,
        "warnings": warnings,
        "errors": errors,
    }


def _ramp_integrity(core, args) -> dict[str, Any]:
    core.configure_preview_audit(
        source="sample_index_ramp",
        event_enable=False,
        freeze_on_event=True,
        event_threshold=int(args.event_threshold),
        clear=True,
    )
    preview = core.capture_preview_fast(n=int(args.samples), input_mask=0x01, timeout=float(args.timeout))
    audit = core.read_preview_audit_status()
    mismatches = 0
    first_mismatch = None
    try:
        import numpy as np

        arr = np.asarray(preview["iq"][0], dtype=np.int64)
    except ImportError:
        arr = preview["iq"][0]
    for idx, sample in enumerate(arr):
        i_value = int(sample[0])
        q_value = int(sample[1])
        expected_i_u16 = (int(preview["sample0"]) + idx) & 0xFFFF
        expected_q_u16 = expected_i_u16 ^ 0x8000
        expected_i = expected_i_u16 if expected_i_u16 < 0x8000 else expected_i_u16 - 0x10000
        expected_q = expected_q_u16 if expected_q_u16 < 0x8000 else expected_q_u16 - 0x10000
        if i_value != expected_i or q_value != expected_q:
            mismatches += 1
            if first_mismatch is None:
                first_mismatch = {
                    "sample": int(idx),
                    "actual_i": i_value,
                    "actual_q": q_value,
                    "expected_i": expected_i,
                    "expected_q": expected_q,
                }
    errors = []
    if mismatches:
        errors.append(f"sample_index_ramp preview had {mismatches} CH0 mismatches")
    if int(audit["valid_gap_count"]) != 0:
        errors.append(f"ramp valid_gap_count={int(audit['valid_gap_count'])}")
    if int(audit["sample0_error_count"]) != 0:
        errors.append(f"ramp sample0_error_count={int(audit['sample0_error_count'])}")
    return {
        "result": "PASS" if not errors else "FAIL",
        "source": "sample_index_ramp",
        "sample0": int(preview["sample0"]),
        "count": int(preview["count"]),
        "mismatches": mismatches,
        "first_mismatch": first_mismatch,
        "audit": audit,
        "errors": errors,
    }


def _event_capture(core, args) -> dict[str, Any]:
    core.configure_preview_audit(
        source="rfdc",
        event_enable=True,
        freeze_on_event=True,
        event_threshold=int(args.event_threshold),
        clear=True,
    )
    deadline = time.monotonic() + max(0.0, float(args.seconds))
    audit = core.read_preview_audit_status()
    while not audit["event_valid"] and time.monotonic() < deadline:
        time.sleep(0.05)
        audit = core.read_preview_audit_status()
    if not audit["event_valid"]:
        return {
            "result": "NO_EVENT",
            "source": "rfdc",
            "event_threshold": int(args.event_threshold),
            "seconds": float(args.seconds),
            "audit": audit,
            "warnings": ["no large event triggered during audit window"],
            "errors": [],
        }

    count = int(audit["event_buffer_words"])
    regs = core.regs
    first = [int(core.ctrl.read(regs.PREVIEW_EVENT_BUFFER_BASE + 4 * idx)) for idx in range(count)]
    second = [int(core.ctrl.read(regs.PREVIEW_EVENT_BUFFER_BASE + 4 * idx)) for idx in range(count)]
    mismatches = sum(1 for a, b in zip(first, second) if a != b)
    event = core.capture_preview_event(timeout=0.1, n=count)
    errors = []
    if mismatches:
        errors.append(f"event buffer changed between double read ({mismatches} word mismatches)")
    if int(event["max_code"]) < int(args.event_threshold):
        errors.append(f"event max_code {int(event['max_code'])} below threshold {int(args.event_threshold)}")
    return {
        "result": "PASS" if not errors else "FAIL",
        "source": "rfdc",
        "event_threshold": int(args.event_threshold),
        "audit": audit,
        "event": {
            "sample0": int(event["sample0"]),
            "count": int(event["count"]),
            "max_code": int(event["max_code"]),
            "rfdc_flags": int(event["rfdc_flags"]),
            "dac_phase_epoch": int(event["dac_phase_epoch"]),
            "first_words": first[:8],
        },
        "double_read_match": mismatches == 0,
        "double_read_mismatches": mismatches,
        "errors": errors,
    }


def _readback_consistency(core, args) -> dict[str, Any]:
    checks = []
    mismatch_frames = 0
    mismatch_words = 0
    for _ in range(max(1, int(args.readback_frames))):
        check = core.capture_preview_readback_check(n=int(args.samples), input_mask=0x01, timeout=float(args.timeout))
        if not bool(check["match"]):
            mismatch_frames += 1
            mismatch_words += int(check["mismatch_count"])
        checks.append({key: value for key, value in check.items() if key not in ("first_preview", "second_preview")})
    errors = []
    if mismatch_frames:
        errors.append(f"{mismatch_frames} preview buffers changed between two reads ({mismatch_words} mismatches)")
    return {
        "result": "PASS" if not errors else "FAIL",
        "frames": len(checks),
        "mismatch_frames": mismatch_frames,
        "mismatch_words": mismatch_words,
        "first_checks": checks[:3],
        "last_checks": checks[-3:] if len(checks) > 3 else checks,
        "errors": errors,
    }


def _dac_phase_commit(core, args) -> dict[str, Any]:
    phases = _parse_float_list(args.phase_deg)
    results = []
    errors = []
    previous_epoch = int(core.read_dac_audit_status()["phase_epoch_seen"])
    for phase in phases:
        cfg = core.apply_observation_instrument_config(
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
        time.sleep(max(0.01, float(args.settle_s)))
        audit = core.read_dac_audit_status()
        expected_phase0 = int(round(((float(phase) % 360.0) / 360.0) * (1 << 32))) & 0xFFFF_FFFF
        epoch = int(audit["phase_epoch_seen"])
        if epoch <= previous_epoch:
            errors.append(f"DAC audit epoch did not increase for phase {phase:.1f} deg")
        if int(audit["ch0_mode"]) != 1:
            errors.append(f"DAC CH0 mode readback {int(audit['ch0_mode'])} is not constant_phasor=1")
        if int(audit["ch0_phase0"]) != expected_phase0:
            errors.append(
                f"DAC CH0 phase0 readback 0x{int(audit['ch0_phase0']):08x} != expected 0x{expected_phase0:08x}"
            )
        previous_epoch = epoch
        results.append(
            {
                "requested_phase_deg": float(phase),
                "expected_phase0": expected_phase0,
                "config_epoch": int(cfg["dac_phase_epoch"]),
                "audit": audit,
            }
        )
    return {
        "result": "PASS" if not errors else "FAIL",
        "steps": results,
        "errors": errors,
    }


def _classify(summary: dict[str, Any]) -> str:
    def section_result(name: str) -> str | None:
        item = summary.get(name)
        if not isinstance(item, dict):
            return None
        result = item.get("result")
        return str(result) if result is not None else None

    internal_result = section_result("internal_dds")
    ramp_result = section_result("sample_index_ramp")
    readback_result = section_result("readback_consistency")
    dac_result = section_result("dac_phase_commit")
    rfdc = summary.get("rfdc_source", {})
    rfdc_jitter = float(rfdc.get("summary", {}).get("phase_error", {}).get("max_abs_from_first_deg", 0.0))
    if readback_result not in (None, "PASS"):
        return "preview_bram_or_mmio_readback_unstable"
    if internal_result not in (None, "PASS") or ramp_result not in (None, "PASS"):
        return "preview_observer_sample0_latch_or_cdc_suspect"
    if dac_result not in (None, "PASS"):
        return "dac_phase_commit_cdc_suspect"
    if rfdc_jitter > 15.0:
        return "rfdc_or_analog_or_clock_path_suspect"
    if all(result is None for result in (internal_result, ramp_result, readback_result, dac_result)) and "rfdc_source" not in summary:
        return "partial_audit_no_global_classification"
    return "stage15_audit_no_major_phase_path_fault_detected"


def main() -> int:
    _add_repo_python_path()
    from python.t510_fengine import T510FEngine

    default_bitfile = _repo_root() / "overlay" / "t510_fengine.bit"
    parser = argparse.ArgumentParser(description="Stage 15 hardware phase audit and preview event capture.")
    parser.add_argument("--bitfile", default=str(default_bitfile))
    parser.add_argument("--no-download", action="store_true")
    parser.add_argument("--mode", choices=["all", "internal", "rfdc", "event", "dac", "readback"], default="all")
    parser.add_argument("--signal-mhz", type=float, default=100.0)
    parser.add_argument("--center-mhz", type=float, default=100.0)
    parser.add_argument("--bw-mhz", type=float, default=100.0)
    parser.add_argument("--samples", type=int, default=512)
    parser.add_argument("--frames", type=int, default=60)
    parser.add_argument("--readback-frames", type=int, default=20)
    parser.add_argument("--seconds", type=float, default=60.0)
    parser.add_argument("--event-threshold", type=_parse_int, default=28000)
    parser.add_argument("--amplitude", type=_parse_int, default=2048)
    parser.add_argument("--configured-phase-deg", type=float, default=0.0)
    parser.add_argument("--phase-deg", default="0,45,90,180")
    parser.add_argument("--adc-port-mask", type=_parse_int, default=0x0003)
    parser.add_argument("--timeout", type=float, default=2.0)
    parser.add_argument("--settle-s", type=float, default=0.2)
    parser.add_argument("--frame-interval-s", type=float, default=0.03)
    parser.add_argument("--oversample", type=float, default=8.0)
    parser.add_argument("--time-window-us", type=float, default=0.25)
    parser.add_argument("--internal-phase-jitter-deg", type=float, default=0.05)
    parser.add_argument("--rfdc-phase-jitter-warn-deg", type=float, default=15.0)
    args = parser.parse_args()

    errors: list[str] = []
    warnings: list[str] = []
    core, config, status = _prepare_core(T510FEngine, args)
    if int(status["core_version"]) != EXPECTED_CORE_VERSION:
        errors.append(f"expected CORE_VERSION=0x{EXPECTED_CORE_VERSION:08x}, got 0x{int(status['core_version']):08x}")
    if not status["streaming"]:
        errors.append("F-engine did not enter streaming")

    summary: dict[str, Any] = {
        "result": "PASS",
        "mode": args.mode,
        "core_version": f"0x{int(status['core_version']):08x}",
        "streaming": bool(status["streaming"]),
        "config": config,
        "initial_status": {
            "rfdc_status_flags": int(status.get("rfdc_status_flags", 0)),
            "rfdc_current_valid_mask": int(status.get("rfdc_current_valid_mask", 0)),
            "udp_dry_run": int(status.get("udp_dry_run", 0)),
            "qsfp_link_up": int(status.get("qsfp_link_up", 0)),
        },
    }

    if args.mode in ("all", "internal"):
        center_hz = float(args.center_mhz) * 1_000_000.0
        # The RTL audit DDS emits I=sin(phase), Q=cos(phase). With the Python
        # convention z = I + jQ this is a negative-frequency complex tone.
        internal_signal_hz = center_hz + INTERNAL_DDS_COMPLEX_SIGN * INTERNAL_DDS_BASEBAND_HZ
        summary["sample_index_ramp"] = _ramp_integrity(core, args)
        summary["internal_dds"] = _capture_phase_source(
            T510FEngine,
            core,
            args,
            source="internal_dds",
            signal_hz=internal_signal_hz,
            center_hz=center_hz,
            frames=int(args.frames),
        )
    if args.mode in ("all", "rfdc"):
        summary["rfdc_source"] = _capture_phase_source(
            T510FEngine,
            core,
            args,
            source="rfdc",
            signal_hz=float(args.signal_mhz) * 1_000_000.0,
            center_hz=float(args.center_mhz) * 1_000_000.0,
            frames=int(args.frames),
        )
    if args.mode in ("all", "readback"):
        summary["readback_consistency"] = _readback_consistency(core, args)
    if args.mode in ("all", "event"):
        summary["large_event_capture"] = _event_capture(core, args)
    if args.mode in ("all", "dac"):
        summary["dac_phase_commit"] = _dac_phase_commit(core, args)

    for key, value in summary.items():
        if isinstance(value, dict):
            errors.extend([f"{key}: {item}" for item in value.get("errors", [])])
            warnings.extend([f"{key}: {item}" for item in value.get("warnings", [])])

    summary["classification"] = _classify(summary)
    summary["warnings"] = warnings
    summary["errors"] = errors
    summary["result"] = "PASS" if not errors else "FAIL"
    print(json.dumps(_jsonable(summary), indent=2, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
