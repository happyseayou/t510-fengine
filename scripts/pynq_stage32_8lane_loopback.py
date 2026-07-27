#!/usr/bin/env python3
"""Stage 32 eight-lane DAC-to-ADC loopback gate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time
from typing import Any


EXPECTED_CORE_VERSION = 0x0001_0032


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def _jsonable(value: Any) -> Any:
    try:
        import numpy as np
    except ImportError:
        np = None  # type: ignore[assignment]
    if np is not None and isinstance(value, np.ndarray):
        return value.tolist()
    if np is not None and isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(_jsonable(value), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _phase_pp_deg(values: list[float]) -> float:
    import numpy as np

    if not values:
        return 0.0
    return float(
        np.ptp(np.rad2deg(np.unwrap(np.deg2rad(np.asarray(values, dtype=np.float64)))))
    )


def _pp_percent(values: list[float]) -> float:
    if not values:
        return 0.0
    mean = sum(values) / len(values)
    return float("inf") if mean == 0.0 else 100.0 * (max(values) - min(values)) / abs(mean)


def _wait_streaming(core: Any, *, timeout_s: float) -> dict[str, Any]:
    deadline = time.monotonic() + max(float(timeout_s), 0.0)
    status = core.read_status()
    while time.monotonic() < deadline:
        status = core.read_status()
        if (
            int(status.get("streaming", 0))
            and int(status.get("rfdc_current_valid_mask", 0)) & 0xFFFF == 0xFFFF
        ):
            return status
        time.sleep(0.02)
    return status


def main() -> int:
    sys.path.insert(0, str(_root()))
    from python.t510_fengine import T510FEngine

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bitfile", default=str(_root() / "overlay" / "t510_fengine.bit"))
    parser.add_argument("--no-download", action="store_true")
    parser.add_argument("--center-mhz", type=float, default=200.0)
    parser.add_argument("--signal-mhz", type=float, default=200.0)
    parser.add_argument("--amplitude", type=lambda value: int(value, 0), default=2048)
    parser.add_argument("--frames", type=int, default=240)
    parser.add_argument("--samples", type=int, default=512)
    parser.add_argument("--timeout", type=float, default=3.0)
    parser.add_argument("--adc-target", type=int, default=230)
    parser.add_argument("--dac-target", type=int, default=336)
    parser.add_argument("--phase-pp-deg", type=float, default=3.0)
    parser.add_argument("--amplitude-pp-percent", type=float, default=5.0)
    parser.add_argument("--min-snr-db", type=float, default=40.0)
    parser.add_argument(
        "--output",
        default=str(_root() / "reports" / "board" / "stage32c_8lane_loopback.json"),
    )
    args = parser.parse_args()

    if args.frames < 2 or args.samples < 64:
        parser.error("--frames must be >=2 and --samples must be >=64")
    if args.adc_target < 0 or args.dac_target < 0:
        parser.error("fixed MTS targets must be non-negative")

    phases = (0.0, 45.0, 90.0, 135.0, 180.0, -135.0, -90.0, -45.0)
    core = T510FEngine(args.bitfile, download=not args.no_download)
    result: dict[str, Any] = {
        "classification": "STAGE32C_8LANE_LOOPBACK_IN_PROGRESS",
        "ok": False,
        "core_version_expected": f"0x{EXPECTED_CORE_VERSION:08x}",
        "fixed_targets": {"adc": args.adc_target, "dac": args.dac_target},
        "errors": [],
    }
    try:
        core.stop()
        config = core.apply_mts_locked_observation_config(
            observe_center_hz=args.center_mhz * 1.0e6,
            dac_signal_hz=args.signal_mhz * 1.0e6,
            expected_signal_hz=args.signal_mhz * 1.0e6,
            view_bw_hz=320.0e6,
            amplitude=args.amplitude,
            phase_deg=0.0,
            phase_deg_by_channel=phases,
            enable_mask=0xFF,
            adc_active_mask=0xFFFF,
            initialize=True,
            start=True,
            require_full_clock_lock=True,
            require_mts=True,
            force_clock_reconfigure=False,
            dac_source_mode="constant_phasor",
            input_source_mode="dac_loopback",
            clock_ref=core.PRODUCTION_CLOCK_REF,
            sync_mode=core.PRODUCTION_SYNC_MODE,
            mts_adc_target_latency=args.adc_target,
            mts_dac_target_latency=args.dac_target,
        )
        stream_status = _wait_streaming(core, timeout_s=args.timeout)
        sync = core.read_external_sync_diagnostics(interval_s=1.2)
        records = {
            channel: {
                "phase": [],
                "amplitude": [],
                "snr": [],
                "clipped": [],
            }
            for channel in range(8)
        }
        anchors: dict[int, float] | None = None
        sample0_values: list[int] = []
        for _frame in range(args.frames):
            preview = core.capture_preview_fast(
                n=args.samples,
                input_mask=0xFF,
                timeout=args.timeout,
            )
            view = T510FEngine.compute_sample0_aligned_phase_view(
                preview,
                observe_center_hz=args.center_mhz * 1.0e6,
                dac_signal_hz=args.signal_mhz * 1.0e6,
                expected_signal_hz=args.signal_mhz * 1.0e6,
                configured_phase_deg=0.0,
                phase_deg_by_channel=phases,
                alignment_anchor_deg=anchors,
                phase_ref_input=0,
                time_window_us=0.25,
                display_points=128,
            )
            if anchors is None:
                anchors = {
                    int(channel): float(row["anchor_candidate_deg"])
                    for channel, row in view["channels"].items()
                }
                view = T510FEngine.compute_sample0_aligned_phase_view(
                    preview,
                    observe_center_hz=args.center_mhz * 1.0e6,
                    dac_signal_hz=args.signal_mhz * 1.0e6,
                    expected_signal_hz=args.signal_mhz * 1.0e6,
                    configured_phase_deg=0.0,
                    phase_deg_by_channel=phases,
                    alignment_anchor_deg=anchors,
                    phase_ref_input=0,
                    time_window_us=0.25,
                    display_points=128,
                )
            sample0_values.append(int(view["sample0"]))
            for channel, row in view["channels"].items():
                record = records[int(channel)]
                record["phase"].append(float(row["phase_error_deg"]))
                record["amplitude"].append(float(row["amplitude_code"]))
                record["snr"].append(float(row["snr_db"]))
                record["clipped"].append(bool(row["clipped"]))

        errors: list[str] = []
        status = core.read_status()
        core_version = int(status.get("core_version", 0))
        if core_version != EXPECTED_CORE_VERSION:
            errors.append(
                f"CORE_VERSION expected 0x{EXPECTED_CORE_VERSION:08x}, "
                f"read 0x{core_version:08x}"
            )
        if not bool(stream_status.get("streaming", 0)):
            errors.append("F-engine did not enter streaming state")
        if not bool(sync.get("pps_ok", False)):
            errors.append("external PPS diagnostic did not pass")
        if any(right <= left for left, right in zip(sample0_values, sample0_values[1:])):
            errors.append("preview sample0 did not increase monotonically")

        channels: dict[int, dict[str, Any]] = {}
        for channel, record in records.items():
            phase_pp = _phase_pp_deg(record["phase"])
            amplitude_pp = _pp_percent(record["amplitude"])
            min_snr = min(record["snr"]) if record["snr"] else 0.0
            clipped = any(record["clipped"])
            channels[channel] = {
                "configured_phase_deg": phases[channel],
                "frames": len(record["phase"]),
                "phase_pp_deg": phase_pp,
                "amplitude_pp_percent": amplitude_pp,
                "amplitude_mean_code": (
                    sum(record["amplitude"]) / len(record["amplitude"])
                    if record["amplitude"]
                    else 0.0
                ),
                "min_snr_db": min_snr,
                "clipped": clipped,
            }
            if phase_pp > args.phase_pp_deg:
                errors.append(
                    f"CH{channel} phase p-p {phase_pp:.3f} > {args.phase_pp_deg:.3f} deg"
                )
            if amplitude_pp > args.amplitude_pp_percent:
                errors.append(
                    f"CH{channel} amplitude p-p {amplitude_pp:.3f} > "
                    f"{args.amplitude_pp_percent:.3f}%"
                )
            if min_snr < args.min_snr_db:
                errors.append(
                    f"CH{channel} min SNR {min_snr:.3f} < {args.min_snr_db:.3f} dB"
                )
            if clipped:
                errors.append(f"CH{channel} clipped")

        result.update(
            {
                "classification": (
                    "STAGE32C_8LANE_LOOPBACK_PASS"
                    if not errors
                    else "STAGE32C_8LANE_LOOPBACK_FAIL"
                ),
                "ok": not errors,
                "core_version": f"0x{core_version:08x}",
                "config": config,
                "stream_status": stream_status,
                "sync_diagnostic": sync,
                "frames": args.frames,
                "samples": args.samples,
                "sample0_first": sample0_values[0] if sample0_values else None,
                "sample0_last": sample0_values[-1] if sample0_values else None,
                "thresholds": {
                    "phase_pp_deg": args.phase_pp_deg,
                    "amplitude_pp_percent": args.amplitude_pp_percent,
                    "min_snr_db": args.min_snr_db,
                },
                "channels": channels,
                "errors": errors,
            }
        )
    except Exception as exc:
        result["classification"] = "STAGE32C_8LANE_LOOPBACK_FAIL"
        result["errors"] = [f"{type(exc).__name__}: {exc}"]
    finally:
        try:
            result["stop_status"] = core.stop()
        except Exception as exc:
            result.setdefault("errors", []).append(f"STOP_FAILED: {type(exc).__name__}: {exc}")
            result["ok"] = False
            result["classification"] = "STAGE32C_8LANE_LOOPBACK_FAIL"

    _write_json(Path(args.output), result)
    print(json.dumps(_jsonable(result), indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
