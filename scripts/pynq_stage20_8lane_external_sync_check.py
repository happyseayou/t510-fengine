#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path
from typing import Any


EXPECTED_CORE_VERSION = 0x0001_0011


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _add_repo_python_path() -> None:
    sys.path.insert(0, str(_repo_root()))


def _parse_int(value: str) -> int:
    return int(value, 0)


def _parse_phase_list(value: str) -> list[float]:
    phases = [float(item.strip()) for item in value.split(",") if item.strip()]
    if not phases:
        raise argparse.ArgumentTypeError("expected comma-separated phase list")
    if len(phases) > 8:
        raise argparse.ArgumentTypeError("at most 8 phases are supported")
    return phases + [0.0] * (8 - len(phases))


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


def _write_output(path: str | None, result: dict[str, Any]) -> None:
    if not path:
        return
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(_jsonable(result), indent=2, sort_keys=True) + "\n")


def _wait_streaming(core: Any, mask: int, timeout: float) -> dict[str, int]:
    deadline = time.monotonic() + float(timeout)
    status = core.read_status()
    while time.monotonic() < deadline:
        status = core.read_status()
        if status.get("streaming") and (int(status.get("rfdc_current_valid_mask", 0)) & int(mask)) == int(mask):
            return status
        time.sleep(0.02)
    return status


def _phase_pp_deg(values: list[float]) -> float:
    if not values:
        return 0.0
    import numpy as np

    radians = np.deg2rad(np.asarray(values, dtype=np.float64))
    unwrapped = np.rad2deg(np.unwrap(radians))
    return float(np.max(unwrapped) - np.min(unwrapped))


def _pp_percent(values: list[float]) -> float:
    if not values:
        return 0.0
    mean = sum(values) / len(values)
    return float("inf") if mean == 0.0 else 100.0 * (max(values) - min(values)) / abs(mean)


def main() -> int:
    _add_repo_python_path()
    from python.t510_fengine import T510FEngine

    default_bitfile = _repo_root() / "overlay" / "t510_fengine.bit"
    parser = argparse.ArgumentParser(description="Stage 20 8-lane DAC->ADC external 10 MHz/PPS validation.")
    parser.add_argument("--bitfile", default=str(default_bitfile))
    parser.add_argument("--no-download", action="store_true")
    parser.add_argument("--center-mhz", type=float, default=200.0)
    parser.add_argument("--signal-mhz", type=float, default=200.0)
    parser.add_argument("--bw-mhz", type=float, default=100.0)
    parser.add_argument("--amplitude", type=_parse_int, default=2048)
    parser.add_argument("--phases-deg", type=_parse_phase_list, default=[0.0, 45.0, 90.0, 135.0, 180.0, -135.0, -90.0, -45.0])
    parser.add_argument("--frames", type=int, default=240)
    parser.add_argument("--samples", type=int, default=512)
    parser.add_argument("--timeout", type=float, default=3.0)
    parser.add_argument("--frame-sleep-s", type=float, default=0.0)
    parser.add_argument("--adc-port-mask", type=_parse_int, default=0xFFFF)
    parser.add_argument("--preview-mask", type=_parse_int, default=0xFF)
    parser.add_argument("--allow-partial-prereq", action="store_true")
    parser.add_argument("--phase-pp-deg", type=float, default=3.0)
    parser.add_argument("--amplitude-pp-percent", type=float, default=5.0)
    parser.add_argument("--output")
    args = parser.parse_args()

    phases = list(args.phases_deg)
    core = T510FEngine(args.bitfile, download=not args.no_download)
    apply_fn = (
        core.apply_sysref_locked_observation_config
        if bool(args.allow_partial_prereq)
        else core.apply_external_pps_locked_observation_config
    )
    config = apply_fn(
        observe_center_hz=float(args.center_mhz) * 1_000_000.0,
        dac_signal_hz=float(args.signal_mhz) * 1_000_000.0,
        expected_signal_hz=float(args.signal_mhz) * 1_000_000.0,
        view_bw_hz=float(args.bw_mhz) * 1_000_000.0,
        amplitude=int(args.amplitude),
        phase_deg=0.0,
        phase_deg_by_channel=phases,
        enable_mask=0xFF,
        adc_active_mask=int(args.adc_port_mask),
        initialize=True,
        start=True,
        require_full_clock_lock=not bool(args.allow_partial_prereq),
        require_mts=not bool(args.allow_partial_prereq),
        force_clock_reconfigure=True,
        dac_source_mode="constant_phasor",
        input_source_mode="dac_loopback",
        clock_ref="external_10mhz",
        sync_mode="external_pps",
    )
    stream_status = _wait_streaming(core, int(args.adc_port_mask), float(args.timeout))
    sync_diag = core.read_external_sync_diagnostics(interval_s=1.2)

    anchors: dict[int, float] | None = None
    per_channel: dict[int, dict[str, Any]] = {
        channel: {"phase_error_deg": [], "amplitude_code": [], "sample0": [], "snr_db": [], "clipped": []}
        for channel in range(8)
        if int(args.preview_mask) & (1 << channel)
    }
    sample0_values: list[int] = []
    errors: list[str] = []
    for frame_idx in range(int(args.frames)):
        preview = core.capture_preview_fast(n=int(args.samples), input_mask=int(args.preview_mask), timeout=float(args.timeout))
        view = T510FEngine.compute_sample0_aligned_phase_view(
            preview,
            observe_center_hz=float(args.center_mhz) * 1_000_000.0,
            dac_signal_hz=float(args.signal_mhz) * 1_000_000.0,
            expected_signal_hz=float(args.signal_mhz) * 1_000_000.0,
            configured_phase_deg=0.0,
            phase_deg_by_channel=phases,
            alignment_anchor_deg=anchors,
            phase_ref_input=0,
            time_window_us=0.25,
            display_points=128,
        )
        if anchors is None:
            anchors = {
                int(channel): float(item["anchor_candidate_deg"])
                for channel, item in view["channels"].items()
            }
            view = T510FEngine.compute_sample0_aligned_phase_view(
                preview,
                observe_center_hz=float(args.center_mhz) * 1_000_000.0,
                dac_signal_hz=float(args.signal_mhz) * 1_000_000.0,
                expected_signal_hz=float(args.signal_mhz) * 1_000_000.0,
                configured_phase_deg=0.0,
                phase_deg_by_channel=phases,
                alignment_anchor_deg=anchors,
                phase_ref_input=0,
                time_window_us=0.25,
                display_points=128,
            )
        sample0_values.append(int(view["sample0"]))
        for channel, item in view["channels"].items():
            rec = per_channel[int(channel)]
            rec["phase_error_deg"].append(float(item["phase_error_deg"]))
            rec["amplitude_code"].append(float(item["amplitude_code"]))
            rec["sample0"].append(int(view["sample0"]))
            rec["snr_db"].append(float(item["snr_db"]))
            rec["clipped"].append(bool(item["clipped"]))
        if float(args.frame_sleep_s) > 0.0:
            time.sleep(float(args.frame_sleep_s))

    summary_channels: dict[int, dict[str, Any]] = {}
    for channel, rec in per_channel.items():
        phase_pp = _phase_pp_deg(rec["phase_error_deg"])
        amp_pp = _pp_percent(rec["amplitude_code"])
        clipped = any(rec["clipped"])
        min_snr = min(rec["snr_db"]) if rec["snr_db"] else 0.0
        summary_channels[channel] = {
            "configured_phase_deg": phases[channel],
            "frames": len(rec["phase_error_deg"]),
            "phase_pp_deg": phase_pp,
            "phase_first_deg": rec["phase_error_deg"][0] if rec["phase_error_deg"] else 0.0,
            "phase_last_deg": rec["phase_error_deg"][-1] if rec["phase_error_deg"] else 0.0,
            "amplitude_pp_percent": amp_pp,
            "amplitude_mean_code": (sum(rec["amplitude_code"]) / len(rec["amplitude_code"])) if rec["amplitude_code"] else 0.0,
            "min_snr_db": min_snr,
            "clipped": clipped,
        }
        if phase_pp > float(args.phase_pp_deg):
            errors.append(f"CH{channel} phase p-p {phase_pp:.3f} deg exceeds {float(args.phase_pp_deg):.3f} deg")
        if amp_pp > float(args.amplitude_pp_percent):
            errors.append(f"CH{channel} amplitude p-p {amp_pp:.3f}% exceeds {float(args.amplitude_pp_percent):.3f}%")
        if clipped:
            errors.append(f"CH{channel} clipped")
    status = core.read_status()
    if int(status.get("core_version", 0)) != EXPECTED_CORE_VERSION:
        errors.append(f"expected CORE_VERSION 0x{EXPECTED_CORE_VERSION:08x}, got 0x{int(status.get('core_version', 0)):08x}")
    if not bool(stream_status.get("streaming", 0)):
        errors.append("F-engine did not start streaming after external PPS")
    if not bool(sync_diag.get("pps_ok", False)):
        errors.append("PPS diagnostic did not pass")
    if any(b <= a for a, b in zip(sample0_values, sample0_values[1:])):
        errors.append("preview sample0 did not increase monotonically")

    result = {
        "expected_core_version": f"0x{EXPECTED_CORE_VERSION:08x}",
        "core_version": f"0x{int(status.get('core_version', 0)):08x}",
        "config": config,
        "sync_diagnostic": sync_diag,
        "stream_status": stream_status,
        "anchors_deg": anchors,
        "sample0_first": sample0_values[0] if sample0_values else 0,
        "sample0_last": sample0_values[-1] if sample0_values else 0,
        "frames": int(args.frames),
        "samples": int(args.samples),
        "thresholds": {
            "phase_pp_deg": float(args.phase_pp_deg),
            "amplitude_pp_percent": float(args.amplitude_pp_percent),
        },
        "channels": summary_channels,
        "classification": "STAGE20_8LANE_EXTERNAL_SYNC_PASS" if not errors else "STAGE20_8LANE_EXTERNAL_SYNC_FAIL",
        "result": "PASS" if not errors else "FAIL",
        "errors": errors,
    }
    print(json.dumps(_jsonable(result), indent=2, sort_keys=True))
    _write_output(args.output, result)
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
