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
PREVIEW_SAMPLE_RATE_HZ = 245_760_000.0


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
            raise argparse.ArgumentTypeError("modes must be time,spec; dual is intentionally not used")
    return modes


def _is_full_tile_scope(args: argparse.Namespace) -> bool:
    adc_tiles = 0xF if args.mts_adc_tiles is None else int(args.mts_adc_tiles)
    dac_tiles = 0xF if args.mts_dac_tiles is None else int(args.mts_dac_tiles)
    return adc_tiles == 0xF and dac_tiles == 0xF


def _phase_pp(values: list[float]) -> float | None:
    if not values:
        return None
    first = float(values[0])
    rel: list[float] = []
    for value in values:
        delta = float(value) - first
        while delta > 180.0:
            delta -= 360.0
        while delta <= -180.0:
            delta += 360.0
        rel.append(delta)
    return float(max(rel) - min(rel))


def _amp_pp_percent(values: list[float]) -> float | None:
    valid = [abs(float(value)) for value in values if math.isfinite(float(value))]
    if not valid:
        return None
    mean = sum(valid) / len(valid)
    if mean <= 1e-9:
        return None
    return float((max(valid) - min(valid)) * 100.0 / mean)


def _wait_streaming(core: Any, mask: int, timeout: float) -> dict[str, int]:
    deadline = time.monotonic() + float(timeout)
    status = core.read_status()
    while time.monotonic() < deadline:
        status = core.read_status()
        if status["streaming"] and (status["rfdc_current_valid_mask"] & mask) == mask:
            return status
        time.sleep(0.02)
    return status


def _sysref_prereq_errors(sysref_config: dict[str, Any]) -> tuple[list[str], str | None]:
    errors: list[str] = []
    classification: str | None = None
    clock = sysref_config.get("clock", {})
    if isinstance(clock, dict) and not bool(clock.get("configured", False)):
        errors.append(f"LMK full lock incomplete: {clock}")
        classification = "RFDC_SYSREF_LOCK_FAILED"
    nco = sysref_config.get("nco", {})
    mts = nco.get("mts", {}) if isinstance(nco, dict) else {}
    if isinstance(mts, dict) and not bool(mts.get("available", True)):
        errors.append(f"RFDC MTS API unavailable: {mts.get('failures', mts)}")
        classification = "RFDC_SYSREF_API_UNAVAILABLE"
    if isinstance(nco, dict) and not bool(nco.get("configured", False)):
        errors.append(f"RFDC SYSREF mixer configuration incomplete: {nco}")
        classification = classification or "RFDC_SYSREF_LOCK_FAILED"
    return errors, classification


def _configure_for_condition(core: Any, args: argparse.Namespace, *, signal_mhz: float, mode: str) -> dict[str, Any]:
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
        "sysref_config": sysref_config,
        "status_after_start": status,
    }


def _record_pair(core_cls: Any, core: Any, args: argparse.Namespace, setup: dict[str, Any], *, mode: str) -> dict[str, Any]:
    import pynq_rfdc_udp_coherence_audit as stage16

    preview = core.capture_preview_fast(n=int(args.samples), input_mask=0x01, timeout=float(args.timeout))
    preview_rec = stage16._preview_record(
        core_cls,
        preview,
        signal_hz=float(setup["signal_hz"]),
        center_hz=float(setup["center_hz"]),
        args=args,
    )
    record: dict[str, Any] = {"preview": preview_rec}
    witness = core.capture_tx_payload_witness(mode, timeout=float(args.timeout), capture_words=int(args.capture_words))
    payload_rec = stage16._payload_record(
        core_cls,
        witness,
        mode=mode,
        signal_hz=float(setup["signal_hz"]),
        center_hz=float(setup["center_hz"]),
        args=args,
    )
    paired = core.read_paired_coherence_status()
    record["payload"] = payload_rec
    record["paired"] = paired
    record["sequential_sample0_delta"] = int(payload_rec["sample0"]) - int(preview_rec["sample0"])
    record["tx_source_header_delta"] = int(paired.get("source_header_delta", 0))
    if paired.get("witness_valid") and paired.get("preview_done"):
        record["sample0_delta"] = int(paired.get("sample0_delta", 0))
    else:
        record["sample0_delta"] = int(record["sequential_sample0_delta"])
    return record


def _strict_summary(records: list[dict[str, Any]], args: argparse.Namespace) -> tuple[dict[str, Any], str, list[str]]:
    preview_phase = [float(item["preview"]["phase_error_deg"]) for item in records if "preview" in item]
    preview_amp = [float(item["preview"]["amplitude_code"]) for item in records if "preview" in item]
    payload_records = [item for item in records if "payload" in item]
    payload_phase = [float(item["payload"]["phase_error_deg"]) for item in payload_records]
    payload_amp = [float(item["payload"]["amplitude_code"]) for item in payload_records]
    preview_phase_pp = _phase_pp(preview_phase)
    payload_phase_pp = _phase_pp(payload_phase)
    preview_amp_pp = _amp_pp_percent(preview_amp)
    payload_amp_pp = _amp_pp_percent(payload_amp)
    sample0_delta_values = [int(item["sample0_delta"]) for item in payload_records]
    sequential_delta_values = [int(item.get("sequential_sample0_delta", 0)) for item in payload_records]
    source_header_delta_values = [int(item.get("tx_source_header_delta", 0)) for item in payload_records]
    sample0_delta_unique = sorted(set(sample0_delta_values))
    sequential_delta_unique = sorted(set(sequential_delta_values))
    source_header_delta_unique = sorted(set(source_header_delta_values))
    clipping_frames = [
        idx
        for idx, item in enumerate(records)
        if bool(item.get("preview", {}).get("clipped", False)) or bool(item.get("payload", {}).get("clipped", False))
    ]
    large_event_frames = [
        idx
        for idx, item in enumerate(records)
        if max(float(item.get("preview", {}).get("max_abs_code", 0.0)), float(item.get("payload", {}).get("max_abs_code", 0.0))) >= 0.9 * 32768.0
    ]
    paired_errors = [
        idx
        for idx, item in enumerate(payload_records)
        if item.get("paired", {}).get("witness_overflow")
        or item.get("paired", {}).get("witness_filter_mismatch")
        or item.get("paired", {}).get("preview_error")
    ]
    summary = {
        "frames": len(records),
        "valid_pair_frames": len(payload_records),
        "preview_phase_pp_deg": preview_phase_pp,
        "payload_phase_pp_deg": payload_phase_pp,
        "preview_amplitude_pp_percent": preview_amp_pp,
        "payload_amplitude_pp_percent": payload_amp_pp,
        "sample0_delta_unique": sample0_delta_unique[:16],
        "sample0_delta_unique_count": len(sample0_delta_unique),
        "sequential_sample0_delta_unique": sequential_delta_unique[:16],
        "sequential_sample0_delta_unique_count": len(sequential_delta_unique),
        "tx_source_header_delta_unique": source_header_delta_unique[:16],
        "tx_source_header_delta_unique_count": len(source_header_delta_unique),
        "clipping_frame_count": len(clipping_frames),
        "large_event_frame_count": len(large_event_frames),
        "paired_error_frame_count": len(paired_errors),
    }
    errors: list[str] = []
    strict_phase = float(args.strict_phase_pp_deg)
    strict_amp = float(args.strict_amplitude_pp_percent)
    if len(payload_records) != len(records):
        errors.append("TX payload witness did not capture every frame")
    if preview_phase_pp is None or preview_phase_pp > strict_phase:
        errors.append(f"preview phase p-p {preview_phase_pp} deg exceeds {strict_phase} deg")
    if payload_phase_pp is None or payload_phase_pp > strict_phase:
        errors.append(f"payload phase p-p {payload_phase_pp} deg exceeds {strict_phase} deg")
    if preview_amp_pp is None or preview_amp_pp > strict_amp:
        errors.append(f"preview amplitude p-p {preview_amp_pp} percent exceeds {strict_amp} percent")
    if payload_amp_pp is None or payload_amp_pp > strict_amp:
        errors.append(f"payload amplitude p-p {payload_amp_pp} percent exceeds {strict_amp} percent")
    if clipping_frames:
        errors.append(f"clipping seen in {len(clipping_frames)} frames")
    if large_event_frames:
        errors.append(f"large-event pollution seen in {len(large_event_frames)} frames")
    if paired_errors:
        errors.append(f"paired witness/preview error flags seen in {len(paired_errors)} frames")
    if len(source_header_delta_unique) > 1:
        errors.append("TX source/header sample0 delta is not fixed")

    if not errors:
        return summary, "RFDC_TO_UDP_COHERENCE_STABLE", []
    if len(payload_records) != len(records):
        classification = "MODE_SWITCH_STATE_CONTAMINATION"
    elif len(source_header_delta_unique) > 1:
        classification = "ADAPTER_SAMPLE0_BROKEN"
    elif preview_phase_pp is not None and preview_phase_pp > strict_phase and payload_phase_pp is not None and payload_phase_pp > strict_phase:
        classification = "RFDC_ANALOG_CLOCK_PATH_UNSTABLE"
    elif payload_phase_pp is not None and payload_phase_pp > strict_phase:
        classification = "PACKETIZER_PAYLOAD_UNSTABLE"
    else:
        classification = "RFDC_ANALOG_CLOCK_PATH_UNSTABLE"
    return summary, classification, errors


def main() -> int:
    _add_repo_python_path()
    from python.t510_fengine import T510FEngine

    default_bitfile = _repo_root() / "overlay" / "t510_fengine.bit"
    parser = argparse.ArgumentParser(description="Stage 17/18 RFDC SYSREF/MTS coherence lock and preview/UDP stability gate.")
    parser.add_argument("--bitfile", default=str(default_bitfile))
    parser.add_argument("--center-mhz", type=float, default=100.0)
    parser.add_argument("--signals-mhz", type=_parse_float_list, default=[119.2, 130.24, 130.0, 100.0])
    parser.add_argument("--modes", type=_parse_modes, default=["time", "spec"])
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
    parser.add_argument("--seconds-between-frames", type=float, default=0.0)
    parser.add_argument("--strict-phase-pp-deg", type=float, default=3.0)
    parser.add_argument("--strict-amplitude-pp-percent", type=float, default=5.0)
    parser.add_argument("--allow-partial-prereq", action="store_true", help="diagnostic mode only: collect partial evidence even when LMK/MTS prerequisites fail")
    parser.add_argument("--mts-adc-tiles", type=_parse_int, default=None, help="optional ADC MTS tile mask, e.g. 0x1 for CH0-only closure")
    parser.add_argument("--mts-dac-tiles", type=_parse_int, default=None, help="optional DAC MTS tile mask, e.g. 0x1 for CH0-only closure")
    parser.add_argument("--mts-adc-ref-tile", type=int, default=0)
    parser.add_argument("--mts-dac-ref-tile", type=int, default=0)
    parser.add_argument("--no-download", action="store_true")
    args = parser.parse_args()

    result: dict[str, Any] = {
        "result": "PASS",
        "expected_core_version": EXPECTED_CORE_VERSION,
        "strict_phase_pp_deg": float(args.strict_phase_pp_deg),
        "strict_amplitude_pp_percent": float(args.strict_amplitude_pp_percent),
        "mts_tile_scope": {
            "adc_tiles": args.mts_adc_tiles,
            "dac_tiles": args.mts_dac_tiles,
            "adc_ref_tile": int(args.mts_adc_ref_tile),
            "dac_ref_tile": int(args.mts_dac_ref_tile),
        },
        "data_quality_gate": "READY_FOR_QSFP_SCIENCE_DATA",
        "conditions": [],
        "errors": [],
    }
    core = T510FEngine(args.bitfile, download=not args.no_download)
    initial_status = core.read_status()
    result["initial_status"] = {
        "core_version": int(initial_status.get("core_version", 0)),
        "udp_dry_run": int(initial_status.get("udp_dry_run", 0)),
        "qsfp_link_up": int(initial_status.get("qsfp_link_up", 0)),
    }
    if int(initial_status.get("core_version", 0)) != EXPECTED_CORE_VERSION:
        result["result"] = "FAIL"
        result["classification"] = "WRONG_CORE_VERSION"
        result["data_quality_gate"] = "BLOCK_QSFP_LIVE_DATA_QUALITY"
        result["errors"].append(
            f"expected CORE_VERSION=0x{EXPECTED_CORE_VERSION:08x}, got 0x{int(initial_status.get('core_version', 0)):08x}"
        )
        print(json.dumps(_jsonable(result), indent=2, sort_keys=True))
        return 2

    condition_index = 0
    for signal_mhz in args.signals_mhz:
        for mode in args.modes:
            condition: dict[str, Any] = {
                "signal_mhz": float(signal_mhz),
                "center_mhz": float(args.center_mhz),
                "mode": mode,
                "condition_index": condition_index,
                "records": [],
            }
            try:
                setup = _configure_for_condition(core, args, signal_mhz=float(signal_mhz), mode=mode)
            except Exception as exc:
                message = str(exc)
                condition["setup_error"] = message
                if "RFDC_SYSREF_API_UNAVAILABLE" in message:
                    condition["classification"] = "RFDC_SYSREF_API_UNAVAILABLE"
                elif "RFDC_SYSREF_LOCK_FAILED" in message:
                    condition["classification"] = "RFDC_SYSREF_LOCK_FAILED"
                else:
                    condition["classification"] = "RFDC_SYSREF_LOCK_FAILED"
                condition["data_quality_gate"] = "BLOCK_QSFP_LIVE_DATA_QUALITY"
                condition["summary"] = {}
                condition["errors"] = [message]
                result["conditions"].append(condition)
                condition_index += 1
                continue
            condition["setup"] = {
                "signal_hz": float(setup["signal_hz"]),
                "center_hz": float(setup["center_hz"]),
                "expected_baseband_hz": float(setup["signal_hz"] - setup["center_hz"]),
                "streaming": int(setup["status_after_start"].get("streaming", 0)),
                "rfdc_current_valid_mask": int(setup["status_after_start"].get("rfdc_current_valid_mask", 0)),
                "rfdc_sysref_configured": bool(setup.get("sysref_config", {}).get("nco", {}).get("configured", False)),
                "clock": setup.get("sysref_config", {}).get("clock", {}),
                "mts_available": bool(
                    setup.get("sysref_config", {}).get("nco", {}).get("mts", {}).get("available", True)
                ),
            }
            for _frame in range(int(args.frames)):
                try:
                    condition["records"].append(_record_pair(T510FEngine, core, args, setup, mode=mode))
                except Exception as exc:
                    condition["records"].append({"error": str(exc)})
                if float(args.seconds_between_frames) > 0.0:
                    time.sleep(float(args.seconds_between_frames))
            summary, classification, errors = _strict_summary(condition["records"], args)
            prereq_errors, prereq_classification = _sysref_prereq_errors(setup.get("sysref_config", {}))
            if prereq_errors:
                errors = prereq_errors + errors
                classification = prereq_classification or classification
            condition["summary"] = summary
            condition["classification"] = classification
            condition["errors"] = errors
            if errors:
                condition["data_quality_gate"] = "BLOCK_QSFP_LIVE_DATA_QUALITY"
            elif _is_full_tile_scope(args):
                condition["data_quality_gate"] = "READY_FOR_QSFP_SCIENCE_DATA"
            else:
                condition["data_quality_gate"] = "READY_FOR_CH0_TILE0_ONLY_DATA_QUALITY"
            result["conditions"].append(condition)
            condition_index += 1

    classifications = {str(item.get("classification", "")) for item in result["conditions"] if item.get("classification")}
    gates = {str(item.get("data_quality_gate", "")) for item in result["conditions"] if item.get("data_quality_gate")}
    result["classification"] = ",".join(sorted(classifications)) if classifications else "UNKNOWN"
    if "BLOCK_QSFP_LIVE_DATA_QUALITY" in gates or any(item.get("errors") for item in result["conditions"]):
        result["result"] = "FAIL"
        result["data_quality_gate"] = "BLOCK_QSFP_LIVE_DATA_QUALITY"
        for item in result["conditions"]:
            for error in item.get("errors", []):
                result["errors"].append(f"condition {item.get('condition_index')}: {error}")
    elif "READY_FOR_CH0_TILE0_ONLY_DATA_QUALITY" in gates:
        result["data_quality_gate"] = "READY_FOR_CH0_TILE0_ONLY_DATA_QUALITY"
        result["notes"] = [
            "MTS/stability closure used a partial tile scope; this proves the DAC0->ADC0 path only.",
            "Full-tile QSFP science data remains blocked until ADC/DAC tile mask 0xf MTS passes.",
        ]
    print(json.dumps(_jsonable(result), indent=2, sort_keys=True))
    return 0 if result["result"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
