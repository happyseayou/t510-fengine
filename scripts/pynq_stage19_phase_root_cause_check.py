#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any


EXPECTED_CORE_VERSION = 0x0001_000E
PREVIEW_SAMPLE_RATE_HZ = 245_760_000.0
PREVIEW_AXIS_BEAT_RATE_HZ = 61_440_000.0


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _add_repo_python_path() -> None:
    root = _repo_root()
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(root / "scripts"))


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


def _parse_int(value: str) -> int:
    return int(value, 0)


def _parse_float_list(value: str) -> list[float]:
    items = [item.strip() for item in value.split(",") if item.strip()]
    if not items:
        raise argparse.ArgumentTypeError("expected comma-separated float list")
    return [float(item) for item in items]


def _parse_modes(value: str) -> list[str]:
    modes = [item.strip().lower() for item in value.split(",") if item.strip()]
    if not modes:
        raise argparse.ArgumentTypeError("expected comma-separated modes")
    for mode in modes:
        if mode not in ("time", "spec"):
            raise argparse.ArgumentTypeError("modes must be time,spec")
    return modes


def _parse_dac_source_modes(value: str) -> list[str]:
    modes = [item.strip().lower() for item in value.split(",") if item.strip()]
    if not modes:
        raise argparse.ArgumentTypeError("expected comma-separated DAC source modes")
    for mode in modes:
        if mode not in ("constant_phasor", "single_tone"):
            raise argparse.ArgumentTypeError("DAC source modes must be constant_phasor,single_tone")
    return modes


def _wait_streaming(core: Any, mask: int, timeout: float) -> dict[str, int]:
    deadline = time.monotonic() + float(timeout)
    status = core.read_status()
    while time.monotonic() < deadline:
        status = core.read_status()
        if status["streaming"] and (status["rfdc_current_valid_mask"] & mask) == mask:
            return status
        time.sleep(0.02)
    return status


def _clock_audit(status: dict[str, Any]) -> dict[str, Any]:
    sample_rate = int(status.get("preview_sample_rate_hz", 0))
    beat_rate = int(status.get("preview_axis_beat_rate_hz", 0))
    return {
        "preview_sample_rate_hz": sample_rate,
        "preview_axis_beat_rate_hz": beat_rate,
        "expected_sample_rate_hz": int(PREVIEW_SAMPLE_RATE_HZ),
        "expected_axis_beat_rate_hz": int(PREVIEW_AXIS_BEAT_RATE_HZ),
        "sample_rate_exact": sample_rate == int(PREVIEW_SAMPLE_RATE_HZ),
        "axis_beat_rate_exact": beat_rate == int(PREVIEW_AXIS_BEAT_RATE_HZ),
    }


def _configure_condition(core: Any, args: argparse.Namespace, *, signal_mhz: float, mode: str, dac_source_mode: str) -> dict[str, Any]:
    signal_hz = float(signal_mhz) * 1_000_000.0
    center_hz = float(args.center_mhz) * 1_000_000.0
    bw_hz = float(args.bw_mhz) * 1_000_000.0
    core.stop()
    time.sleep(0.05)
    core.reset()
    time.sleep(0.05)
    apply_fn = core.apply_sysref_locked_observation_config if bool(args.allow_partial_prereq) else core.apply_mts_locked_observation_config
    sysref_config = apply_fn(
        observe_center_hz=center_hz,
        dac_signal_hz=signal_hz,
        view_bw_hz=bw_hz,
        amplitude=int(args.amplitude),
        phase_deg=float(args.configured_phase_deg),
        enable_mask=0x01,
        adc_active_mask=int(args.adc_port_mask),
        initialize=True,
        start=False,
        require_full_clock_lock=not bool(args.allow_partial_prereq),
        require_mts=not bool(args.allow_partial_prereq),
        mts_adc_tiles=args.mts_adc_tiles,
        mts_dac_tiles=args.mts_dac_tiles,
        mts_adc_ref_tile=int(args.mts_adc_ref_tile),
        mts_dac_ref_tile=int(args.mts_dac_ref_tile),
        dac_source_mode=dac_source_mode,
    )
    core.configure_tx_control(
        force_dry_run=True,
        cmac_enable=False,
        frame_builder_enable=True,
        drop_on_route_miss=True,
        clear_counters=True,
    )
    core.configure_tx_endpoints(
        [
            {"id": 0, "ip": "10.0.1.10", "mac": "02:00:00:00:00:0a", "port": 4100},
            {"id": 1, "ip": "10.0.1.11", "mac": "02:00:00:00:00:0b", "port": 4200},
            {"id": 2, "ip": "10.0.1.16", "mac": "02:00:00:00:00:10", "port": 4300},
        ]
    )
    core.configure_spec_routes([{"id": 0, "chan0": int(args.chan0), "chan_count": 2048, "endpoint_id": 0}])
    core.configure_time_routes([{"id": 0, "input_mask": int(args.adc_port_mask), "endpoint_id": 2}])
    core.configure_channelizer(chan0=int(args.chan0), chan_count=int(args.chan_count), time_count=int(args.time_count))
    core.set_mode(mode)
    core.start()
    status = _wait_streaming(core, int(args.adc_port_mask), float(args.timeout))
    return {
        "signal_hz": signal_hz,
        "center_hz": center_hz,
        "bw_hz": bw_hz,
        "mode": mode,
        "dac_source_mode": dac_source_mode,
        "sysref_config": sysref_config,
        "status_after_start": status,
    }


def _dac_witness_gate(core_cls: Any, core: Any, args: argparse.Namespace, setup: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    witness = core.capture_dac_tx_witness(timeout=float(args.timeout), capture_words=int(args.dac_capture_words))
    tone_hz = float(setup.get("sysref_config", {}).get("dac_tone_hz", setup["signal_hz"] - setup["center_hz"]))
    metrics = core_cls.compute_dac_source_phase_metrics(witness, tone_hz=tone_hz)
    errors: list[str] = []
    if int(witness["status"].get("dac_tx_witness_word_count", 0)) <= 0:
        errors.append("DAC TX witness captured zero words")
    if int(witness["status"].get("dac_tx_witness_overflow", 0)):
        errors.append("DAC TX witness overflow")
    if int(witness["status"].get("dac_tx_witness_ready_gap_seen", 0)):
        errors.append(f"DAC TX witness saw ready gaps: {int(witness['metadata'].get('ready_gap_count', 0))}")
    if float(metrics["phase_pp_deg"]) > float(args.dac_strict_phase_pp_deg):
        errors.append(
            f"DAC pre-RFDC phase p-p {float(metrics['phase_pp_deg']):.6f} deg exceeds {float(args.dac_strict_phase_pp_deg)} deg"
        )
    if float(metrics["amplitude_pp_percent"]) > float(args.dac_strict_amplitude_pp_percent):
        errors.append(
            "DAC pre-RFDC amplitude p-p "
            f"{float(metrics['amplitude_pp_percent']):.6f} percent exceeds {float(args.dac_strict_amplitude_pp_percent)} percent"
        )
    return (
        {
            "status": {
                "raw": int(witness["status"].get("dac_tx_witness_status", 0)),
                "word_count": int(witness["status"].get("dac_tx_witness_word_count", 0)),
                "overflow": int(witness["status"].get("dac_tx_witness_overflow", 0)),
                "tvalid_seen": int(witness["status"].get("dac_tx_witness_tvalid_seen", 0)),
                "tready_seen": int(witness["status"].get("dac_tx_witness_tready_seen", 0)),
                "ready_gap_seen": int(witness["status"].get("dac_tx_witness_ready_gap_seen", 0)),
            },
            "metadata": witness["metadata"],
            "metrics": {
                "count": int(metrics["count"]),
                "tone_hz": float(metrics["tone_hz"]),
                "phase_pp_deg": float(metrics["phase_pp_deg"]),
                "amplitude_pp_percent": float(metrics["amplitude_pp_percent"]),
                "amplitude_mean": float(metrics["amplitude_mean"]),
                "first_phase_deg": float(metrics["first_phase_deg"]),
                "last_phase_deg": float(metrics["last_phase_deg"]),
            },
        },
        errors,
    )


def _classify(condition: dict[str, Any], strict_errors: list[str], dac_errors: list[str], strict_classification: str) -> str:
    if dac_errors:
        return "DAC_SOURCE_UNSTABLE"
    summary = condition.get("summary", {})
    preview_bad = (
        summary.get("preview_phase_pp_deg") is not None
        and float(summary["preview_phase_pp_deg"]) > float(condition["strict_phase_pp_deg"])
    ) or (
        summary.get("preview_amplitude_pp_percent") is not None
        and float(summary["preview_amplitude_pp_percent"]) > float(condition["strict_amplitude_pp_percent"])
    )
    payload_bad = (
        summary.get("payload_phase_pp_deg") is not None
        and float(summary["payload_phase_pp_deg"]) > float(condition["strict_phase_pp_deg"])
    ) or (
        summary.get("payload_amplitude_pp_percent") is not None
        and float(summary["payload_amplitude_pp_percent"]) > float(condition["strict_amplitude_pp_percent"])
    )
    if not strict_errors:
        return "PS_DERIVED_AXIS_CLOCK_MISMATCH_CLOSED"
    if preview_bad and payload_bad:
        return "RFDC_ANALOG_CLOCK_PATH_UNSTABLE"
    if payload_bad and not preview_bad:
        return "PACKETIZER_PAYLOAD_UNSTABLE"
    return strict_classification


def main() -> int:
    _add_repo_python_path()
    from python.t510_fengine import T510FEngine
    import pynq_rfdc_sysref_coherence_lock_check as stage18

    default_bitfile = _repo_root() / "overlay" / "t510_fengine.bit"
    parser = argparse.ArgumentParser(description="Stage 19 phase drift root-cause closure.")
    parser.add_argument("--bitfile", default=str(default_bitfile))
    parser.add_argument("--center-mhz", type=float, default=130.0)
    parser.add_argument("--signals-mhz", type=_parse_float_list, default=[119.2, 130.24, 130.0])
    parser.add_argument("--modes", type=_parse_modes, default=["time", "spec"])
    parser.add_argument("--dac-source-modes", type=_parse_dac_source_modes, default=["constant_phasor", "single_tone"])
    parser.add_argument("--bw-mhz", type=float, default=100.0)
    parser.add_argument("--samples", type=int, default=512)
    parser.add_argument("--frames", type=int, default=240)
    parser.add_argument("--timeout", type=float, default=2.0)
    parser.add_argument("--adc-port-mask", type=_parse_int, default=0x0001)
    parser.add_argument("--amplitude", type=int, default=2048)
    parser.add_argument("--configured-phase-deg", type=float, default=0.0)
    parser.add_argument("--chan0", type=int, default=0)
    parser.add_argument("--chan-count", type=int, default=64)
    parser.add_argument("--time-count", type=int, default=4)
    parser.add_argument("--capture-words", type=int, default=1040)
    parser.add_argument("--dac-capture-words", type=int, default=256)
    parser.add_argument("--seconds-between-frames", type=float, default=0.0)
    parser.add_argument("--strict-phase-pp-deg", type=float, default=3.0)
    parser.add_argument("--strict-amplitude-pp-percent", type=float, default=5.0)
    parser.add_argument("--dac-strict-phase-pp-deg", type=float, default=0.5)
    parser.add_argument("--dac-strict-amplitude-pp-percent", type=float, default=1.0)
    parser.add_argument("--max-frame-errors", type=int, default=5, help="early-fail a condition after this many frame capture errors; <=0 disables early-fail")
    parser.add_argument("--output", default=None, help="write incremental/final JSON evidence to this path")
    parser.add_argument("--allow-partial-prereq", action="store_true")
    parser.add_argument("--mts-adc-tiles", type=_parse_int, default=None)
    parser.add_argument("--mts-dac-tiles", type=_parse_int, default=None)
    parser.add_argument("--mts-adc-ref-tile", type=int, default=0)
    parser.add_argument("--mts-dac-ref-tile", type=int, default=0)
    parser.add_argument("--no-download", action="store_true")
    args = parser.parse_args()

    result: dict[str, Any] = {
        "result": "PASS",
        "expected_core_version": EXPECTED_CORE_VERSION,
        "strict_phase_pp_deg": float(args.strict_phase_pp_deg),
        "strict_amplitude_pp_percent": float(args.strict_amplitude_pp_percent),
        "dac_strict_phase_pp_deg": float(args.dac_strict_phase_pp_deg),
        "dac_strict_amplitude_pp_percent": float(args.dac_strict_amplitude_pp_percent),
        "max_frame_errors": int(args.max_frame_errors),
        "data_quality_gate": "READY_FOR_QSFP_SCIENCE_DATA",
        "conditions": [],
        "errors": [],
    }

    core = T510FEngine(args.bitfile, download=not args.no_download)
    initial_status = core.read_status()
    result["initial_status"] = {
        "core_version": int(initial_status.get("core_version", 0)),
        "rfdc_flags": int(initial_status.get("rfdc_status_flags", 0)),
        "rfdc_downstream_ready": int(initial_status.get("rfdc_downstream_ready", 0)),
        "rfdc_adc_valid": int(initial_status.get("rfdc_adc_valid", 0)),
        "rfdc_dac_ready": int(initial_status.get("rfdc_dac_ready", 0)),
    }
    result["clock_audit"] = _clock_audit(initial_status)
    if int(initial_status.get("core_version", 0)) != EXPECTED_CORE_VERSION:
        result["result"] = "FAIL"
        result["classification"] = "WRONG_CORE_VERSION"
        result["data_quality_gate"] = "BLOCK_QSFP_LIVE_DATA_QUALITY"
        result["errors"].append(
            f"expected CORE_VERSION=0x{EXPECTED_CORE_VERSION:08x}, got 0x{int(initial_status.get('core_version', 0)):08x}"
        )
        _write_output(args.output, result)
        print(json.dumps(_jsonable(result), indent=2, sort_keys=True))
        return 2
    if not result["clock_audit"]["sample_rate_exact"] or not result["clock_audit"]["axis_beat_rate_exact"]:
        result["errors"].append(f"AXIS/sample-rate metadata mismatch: {result['clock_audit']}")

    condition_index = 0
    for dac_source_mode in args.dac_source_modes:
        for signal_mhz in args.signals_mhz:
            for mode in args.modes:
                condition: dict[str, Any] = {
                    "condition_index": condition_index,
                    "dac_source_mode": dac_source_mode,
                    "signal_mhz": float(signal_mhz),
                    "center_mhz": float(args.center_mhz),
                    "mode": mode,
                    "strict_phase_pp_deg": float(args.strict_phase_pp_deg),
                    "strict_amplitude_pp_percent": float(args.strict_amplitude_pp_percent),
                    "records": [],
                }
                try:
                    print(
                        "STAGE19_CONDITION_START "
                        f"idx={condition_index} dac_source_mode={dac_source_mode} signal_mhz={float(signal_mhz):.6f} mode={mode}",
                        file=sys.stderr,
                        flush=True,
                    )
                    setup = _configure_condition(core, args, signal_mhz=float(signal_mhz), mode=mode, dac_source_mode=dac_source_mode)
                    condition["setup"] = {
                        "signal_hz": float(setup["signal_hz"]),
                        "center_hz": float(setup["center_hz"]),
                        "expected_baseband_hz": float(setup["signal_hz"] - setup["center_hz"]),
                        "dac_tone_hz": float(setup.get("sysref_config", {}).get("dac_tone_hz", 0.0)),
                        "dac_nco_hz": float(setup.get("sysref_config", {}).get("dac_nco_hz", 0.0)),
                        "streaming": int(setup["status_after_start"].get("streaming", 0)),
                        "rfdc_current_valid_mask": int(setup["status_after_start"].get("rfdc_current_valid_mask", 0)),
                        "clock": setup.get("sysref_config", {}).get("clock", {}),
                        "mts": setup.get("sysref_config", {}).get("nco", {}).get("mts", {}),
                    }
                    dac_witness, dac_errors = _dac_witness_gate(T510FEngine, core, args, setup)
                    condition["dac_witness"] = dac_witness
                    frame_error_count = 0
                    for frame_index in range(int(args.frames)):
                        try:
                            condition["records"].append(stage18._record_pair(T510FEngine, core, args, setup, mode=mode))
                        except Exception as exc:
                            frame_error_count += 1
                            condition["records"].append({"frame_index": frame_index, "error": str(exc)})
                            print(
                                "STAGE19_FRAME_ERROR "
                                f"idx={condition_index} frame={frame_index} count={frame_error_count} error={exc}",
                                file=sys.stderr,
                                flush=True,
                            )
                            if int(args.max_frame_errors) > 0 and frame_error_count >= int(args.max_frame_errors):
                                condition["records"].append(
                                    {
                                        "error": (
                                            "condition early-failed after "
                                            f"{frame_error_count} frame capture errors"
                                        )
                                    }
                                )
                                break
                        if float(args.seconds_between_frames) > 0.0:
                            time.sleep(float(args.seconds_between_frames))
                    summary, strict_classification, strict_errors = stage18._strict_summary(condition["records"], args)
                    prereq_errors, prereq_classification = stage18._sysref_prereq_errors(setup.get("sysref_config", {}))
                    errors = dac_errors + prereq_errors + strict_errors
                    condition["summary"] = summary
                    condition["errors"] = errors
                    if prereq_errors and prereq_classification:
                        condition["classification"] = prereq_classification
                    else:
                        condition["classification"] = _classify(condition, strict_errors, dac_errors, strict_classification)
                except Exception as exc:
                    condition["summary"] = {}
                    condition["classification"] = "STAGE19_CHECK_EXCEPTION"
                    condition["errors"] = [str(exc)]
                condition["data_quality_gate"] = (
                    "READY_FOR_QSFP_SCIENCE_DATA" if not condition["errors"] else "BLOCK_QSFP_LIVE_DATA_QUALITY"
                )
                result["conditions"].append(condition)
                _write_output(args.output, result)
                print(
                    "STAGE19_CONDITION_DONE "
                    f"idx={condition_index} classification={condition.get('classification')} "
                    f"errors={len(condition.get('errors', []))}",
                    file=sys.stderr,
                    flush=True,
                )
                condition_index += 1

    classifications = {str(item.get("classification", "")) for item in result["conditions"] if item.get("classification")}
    result["classification"] = ",".join(sorted(classifications)) if classifications else "UNKNOWN"
    for item in result["conditions"]:
        for error in item.get("errors", []):
            result["errors"].append(f"condition {item.get('condition_index')}: {error}")
    if result["errors"]:
        result["result"] = "FAIL"
        result["data_quality_gate"] = "BLOCK_QSFP_LIVE_DATA_QUALITY"
    _write_output(args.output, result)
    print(json.dumps(_jsonable(result), indent=2, sort_keys=True))
    return 0 if result["result"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
