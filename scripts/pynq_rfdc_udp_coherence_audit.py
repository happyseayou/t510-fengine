#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path
from typing import Any


EXPECTED_CORE_VERSION = 0x0001_000E
PREVIEW_SAMPLE_RATE_HZ = 245_760_000.0


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


def _parse_modes(value: str) -> list[str]:
    modes = [item.strip().lower() for item in value.split(",") if item.strip()]
    if not modes:
        raise argparse.ArgumentTypeError("expected comma-separated modes")
    for mode in modes:
        if mode not in ("spec", "time"):
            raise argparse.ArgumentTypeError("modes must be spec,time; dual is intentionally not used")
    return modes


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
        return {"count": 0, "first_deg": None, "peak_to_peak_deg": None, "rms_relative_deg": None}
    rel = [_wrap_phase_deg(value - values[0]) for value in values]
    mean_rel = sum(rel) / len(rel)
    rms_rel = math.sqrt(sum((value - mean_rel) ** 2 for value in rel) / len(rel))
    return {
        "count": len(values),
        "first_deg": float(values[0]),
        "peak_to_peak_deg": float(max(rel) - min(rel)),
        "rms_relative_deg": float(rms_rel),
    }


def _scalar_stats(values: list[float]) -> dict[str, float]:
    if not values:
        return {"count": 0, "mean": None, "min": None, "max": None, "peak_to_peak": None}
    return {
        "count": len(values),
        "mean": float(sum(values) / len(values)),
        "min": float(min(values)),
        "max": float(max(values)),
        "peak_to_peak": float(max(values) - min(values)),
    }


def _correlation(a: list[float], b: list[float]) -> float:
    if len(a) < 3 or len(b) < 3 or len(a) != len(b):
        return 0.0
    try:
        import numpy as np
    except ImportError:
        return 0.0
    aa = np.asarray(a, dtype=np.float64)
    bb = np.asarray(b, dtype=np.float64)
    aa = aa - float(np.mean(aa))
    bb = bb - float(np.mean(bb))
    denom = float(np.linalg.norm(aa) * np.linalg.norm(bb))
    if denom <= 1e-12:
        return 0.0
    return float(np.dot(aa, bb) / denom)


def _wait_streaming(core: Any, mask: int, timeout: float) -> dict[str, int]:
    deadline = time.monotonic() + float(timeout)
    status = core.read_status()
    while time.monotonic() < deadline:
        status = core.read_status()
        if status["streaming"] and (status["rfdc_current_valid_mask"] & mask) == mask:
            return status
        time.sleep(0.02)
    return status


def _configure_for_condition(core: Any, args: argparse.Namespace, *, signal_mhz: float, mode: str) -> dict[str, Any]:
    signal_hz = float(signal_mhz) * 1_000_000.0
    center_hz = float(args.center_mhz) * 1_000_000.0
    bw_hz = float(args.bw_mhz) * 1_000_000.0
    core.stop()
    time.sleep(0.05)
    core.reset()
    time.sleep(0.05)
    core.apply_observation_instrument_config(
        observe_center_hz=center_hz,
        dac_signal_hz=signal_hz,
        view_bw_hz=bw_hz,
        amplitude=int(args.amplitude),
        phase_deg=float(args.configured_phase_deg),
        enable_mask=0x01,
        adc_active_mask=int(args.adc_port_mask),
        initialize=True,
        start=False,
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
        "status_after_start": status,
    }


def _preview_record(core_cls: Any, preview: dict[str, Any], *, signal_hz: float, center_hz: float, args: argparse.Namespace) -> dict[str, Any]:
    view = core_cls.compute_sample0_aligned_phase_view(
        preview,
        observe_center_hz=center_hz,
        dac_signal_hz=signal_hz,
        configured_phase_deg=float(args.configured_phase_deg),
        alignment_anchor_deg=0.0,
        phase_ref_input=0,
        time_window_us=0.25,
        display_points=128,
        fft_oversample=4.0,
    )
    ch0 = view["channels"].get(0) or view["channels"].get("0")
    if ch0 is None:
        raise RuntimeError("preview did not contain CH0")
    return {
        "sample0": int(view["sample0"]),
        "phase_error_deg": float(ch0["phase_error_deg"]),
        "sample0_aligned_phase_deg": float(ch0["sample0_aligned_phase_deg"]),
        "amplitude_code": float(ch0["amplitude_code"]),
        "rms_code": float(ch0["rms_code"]),
        "max_abs_code": float(ch0["max_abs_code"]),
        "fit_residual_fraction": float(ch0["fit_residual_fraction"]),
        "snr_db": float(ch0["snr_db"]),
        "clipped": bool(ch0["clipped"]),
    }


def _payload_record(core_cls: Any, witness: dict[str, Any], *, mode: str, signal_hz: float, center_hz: float, args: argparse.Namespace) -> dict[str, Any]:
    if mode == "spec":
        decoded = core_cls.decode_spec_payload_iq(witness, channel=0)
    else:
        decoded = core_cls.decode_time_payload_iq(witness, channel=0)
    metrics = core_cls.compute_payload_phase_metrics(
        decoded,
        sample_rate_hz=PREVIEW_SAMPLE_RATE_HZ,
        observe_center_hz=center_hz,
        dac_signal_hz=signal_hz,
        configured_phase_deg=float(args.configured_phase_deg),
    )
    header = witness["header"]
    metadata = witness["metadata"]
    return {
        "sample0": int(header.sample0),
        "metadata_sample0": int(metadata["sample0"]),
        "frame_id": int(header.frame_id),
        "seq_no": int(header.seq_no),
        "stream_type": int(header.stream_type),
        "chan0": int(header.chan0),
        "chan_count": int(header.chan_count),
        "time_count": int(header.time_count),
        "payload_bytes": int(header.payload_bytes),
        "decoded_count": int(decoded["decoded_count"]),
        "phase_error_deg": float(metrics["phase_error_deg"]),
        "sample0_aligned_phase_deg": float(metrics["sample0_aligned_phase_deg"]),
        "amplitude_code": float(metrics["amplitude_code"]),
        "rms_code": float(metrics["rms_code"]),
        "max_abs_code": float(metrics["max_abs_code"]),
        "fit_residual_fraction": float(metrics["fit_residual_fraction"]),
        "snr_db": float(metrics["snr_db"]),
        "fft_peak_mhz": float(metrics["fft_peak_mhz"]),
        "route_id": int(metadata["route_id"]),
        "endpoint_id": int(metadata["endpoint_id"]),
        "rfdc_flags": int(metadata["rfdc_flags"]),
        "rfdc_sample_count": int(metadata["rfdc_sample_count"]),
        "dac_phase_epoch": int(metadata["dac_phase_epoch"]),
    }


def _summarize_pair(records: list[dict[str, Any]]) -> dict[str, Any]:
    valid_records = [item for item in records if isinstance(item.get("payload"), dict)]
    preview_phase_all = [float(item["preview"]["phase_error_deg"]) for item in records]
    preview_amp_all = [float(item["preview"]["amplitude_code"]) for item in records]
    preview_phase = [float(item["preview"]["phase_error_deg"]) for item in valid_records]
    payload_phase = [float(item["payload"]["phase_error_deg"]) for item in valid_records]
    payload_amp = [float(item["payload"]["amplitude_code"]) for item in valid_records]
    sample0_delta = [float(item["sample0_delta"]) for item in valid_records]
    phase_delta = [_wrap_phase_deg(payload_phase[idx] - preview_phase[idx]) for idx in range(len(valid_records))]
    return {
        "frames": len(records),
        "valid_pair_frames": len(valid_records),
        "witness_timeout_frames": len(records) - len(valid_records),
        "preview_phase_error": _phase_stats(preview_phase_all),
        "preview_pair_phase_error": _phase_stats(preview_phase),
        "payload_phase_error": _phase_stats(payload_phase),
        "payload_minus_preview_phase": _phase_stats(phase_delta),
        "preview_amplitude_code": _scalar_stats(preview_amp_all),
        "preview_pair_amplitude_code": _scalar_stats([float(item["preview"]["amplitude_code"]) for item in valid_records]),
        "payload_amplitude_code": _scalar_stats(payload_amp),
        "sample0_delta": _scalar_stats(sample0_delta),
        "phase_correlation": _correlation(
            [_wrap_phase_deg(v - preview_phase[0]) for v in preview_phase] if preview_phase else [],
            [_wrap_phase_deg(v - payload_phase[0]) for v in payload_phase] if payload_phase else [],
        ),
        "payload_header_sample0_monotonic": all(
            int(valid_records[idx]["payload"]["sample0"]) > int(valid_records[idx - 1]["payload"]["sample0"])
            for idx in range(1, len(valid_records))
        ),
        "preview_sample0_monotonic": all(
            int(records[idx]["preview"]["sample0"]) > int(records[idx - 1]["preview"]["sample0"])
            for idx in range(1, len(records))
        ),
        "large_signal_frames": int(
            sum(
                1
                for item in valid_records
                if max(float(item["preview"]["max_abs_code"]), float(item["payload"]["max_abs_code"])) >= 0.9 * 32768.0
            )
        ),
        "large_signal_preview_frames": int(
            sum(1 for item in records if float(item["preview"]["max_abs_code"]) >= 0.9 * 32768.0)
        ),
    }


def _classify(summary: dict[str, Any]) -> tuple[str, str]:
    if int(summary.get("valid_pair_frames", 0)) <= 0:
        return "tx_payload_witness_missing", "BLOCK_QSFP_LIVE_DATA_QUALITY"
    if int(summary.get("witness_timeout_frames", 0)) > 0:
        return "tx_payload_witness_intermittent", "BLOCK_QSFP_LIVE_DATA_QUALITY"
    preview_pp = float(summary["preview_phase_error"]["peak_to_peak_deg"])
    payload_pp = float(summary["payload_phase_error"]["peak_to_peak_deg"])
    corr = float(summary["phase_correlation"])
    sample0_ok = bool(summary["payload_header_sample0_monotonic"]) and bool(summary["preview_sample0_monotonic"])
    if not sample0_ok:
        return "packet_sample0_semantics_broken", "BLOCK_QSFP_LIVE_DATA_QUALITY"
    if preview_pp <= 30.0 and payload_pp > 90.0:
        return "packetizer_or_downstream_payload_instability", "BLOCK_QSFP_LIVE_DATA_QUALITY"
    if preview_pp > 90.0 and payload_pp > 90.0 and corr > 0.4:
        return "upstream_rfdc_instability_enters_udp_payload", "BLOCK_QSFP_LIVE_DATA_QUALITY"
    if preview_pp > 90.0 and payload_pp > 90.0:
        return "preview_and_payload_unstable_correlation_unclear", "BLOCK_QSFP_LIVE_DATA_QUALITY"
    if preview_pp > 90.0 and payload_pp <= 45.0:
        return "preview_path_instability_not_seen_in_payload_witness", "WARN_QSFP_LIVE_DATA_QUALITY"
    return "preview_payload_coherence_witness_stable", "READY_FOR_QSFP_PREFLIGHT_ONLY"


def main() -> int:
    _add_repo_python_path()
    from python.t510_fengine import T510FEngine

    default_bitfile = _repo_root() / "overlay" / "t510_fengine.bit"
    parser = argparse.ArgumentParser(description="Stage 16 RFDC-to-UDP coherence witness audit.")
    parser.add_argument("--bitfile", default=str(default_bitfile))
    parser.add_argument("--center-mhz", type=float, default=100.0)
    parser.add_argument("--signals-mhz", type=_parse_float_list, default=[119.2, 130.24, 130.0, 100.0])
    parser.add_argument("--modes", type=_parse_modes, default=["spec", "time"])
    parser.add_argument("--bw-mhz", type=float, default=100.0)
    parser.add_argument("--samples", type=int, default=512)
    parser.add_argument("--frames", type=int, default=120)
    parser.add_argument("--timeout", type=float, default=2.0)
    parser.add_argument("--adc-port-mask", type=_parse_int, default=0x0001)
    parser.add_argument("--amplitude", type=int, default=2048)
    parser.add_argument("--configured-phase-deg", type=float, default=0.0)
    parser.add_argument("--chan0", type=int, default=0)
    parser.add_argument("--chan-count", type=int, default=64)
    parser.add_argument("--time-count", type=int, default=4)
    parser.add_argument("--capture-words", type=int, default=1040)
    parser.add_argument("--seconds-between-frames", type=float, default=0.0)
    parser.add_argument("--max-consecutive-witness-timeouts", type=int, default=8)
    parser.add_argument("--reload-each-condition", dest="reload_each_condition", action="store_true", default=True)
    parser.add_argument("--no-reload-each-condition", dest="reload_each_condition", action="store_false")
    parser.add_argument("--no-download", action="store_true")
    args = parser.parse_args()

    result: dict[str, Any] = {
        "result": "PASS",
        "expected_core_version": EXPECTED_CORE_VERSION,
        "conditions": [],
        "errors": [],
    }
    core = T510FEngine(args.bitfile, download=not args.no_download)
    first_status = core.read_status()
    result["initial_status"] = {
        "core_version": int(first_status.get("core_version", 0)),
        "udp_dry_run": int(first_status.get("udp_dry_run", 0)),
        "qsfp_link_up": int(first_status.get("qsfp_link_up", 0)),
    }
    if int(first_status.get("core_version", 0)) != EXPECTED_CORE_VERSION:
        result["result"] = "FAIL"
        result["errors"].append(
            f"expected CORE_VERSION=0x{EXPECTED_CORE_VERSION:08x}, got 0x{int(first_status.get('core_version', 0)):08x}"
        )
        print(json.dumps(_jsonable(result), indent=2, sort_keys=True))
        return 2

    condition_index = 0
    for signal_mhz in args.signals_mhz:
        for mode in args.modes:
            if condition_index > 0 and bool(args.reload_each_condition) and not bool(args.no_download):
                core = T510FEngine(args.bitfile, download=True)
                status_after_reload = core.read_status()
                if int(status_after_reload.get("core_version", 0)) != EXPECTED_CORE_VERSION:
                    result["result"] = "FAIL"
                    result["errors"].append(
                        f"reload condition {condition_index}: expected CORE_VERSION=0x{EXPECTED_CORE_VERSION:08x}, "
                        f"got 0x{int(status_after_reload.get('core_version', 0)):08x}"
                    )
                    print(json.dumps(_jsonable(result), indent=2, sort_keys=True))
                    return 2
            condition = {
                "signal_mhz": float(signal_mhz),
                "center_mhz": float(args.center_mhz),
                "mode": mode,
                "condition_index": condition_index,
                "overlay_reloaded": bool(condition_index == 0 or (args.reload_each_condition and not args.no_download)),
                "records": [],
            }
            setup = _configure_for_condition(core, args, signal_mhz=float(signal_mhz), mode=mode)
            condition["setup"] = {
                "signal_hz": float(setup["signal_hz"]),
                "center_hz": float(setup["center_hz"]),
                "expected_baseband_hz": float(setup["signal_hz"] - setup["center_hz"]),
                "streaming": int(setup["status_after_start"].get("streaming", 0)),
                "rfdc_current_valid_mask": int(setup["status_after_start"].get("rfdc_current_valid_mask", 0)),
            }
            consecutive_timeouts = 0
            for _frame in range(int(args.frames)):
                preview = core.capture_preview_fast(n=int(args.samples), input_mask=0x01, timeout=float(args.timeout))
                preview_rec = _preview_record(
                    T510FEngine,
                    preview,
                    signal_hz=float(setup["signal_hz"]),
                    center_hz=float(setup["center_hz"]),
                    args=args,
                )
                record: dict[str, Any] = {"preview": preview_rec}
                try:
                    witness = core.capture_tx_payload_witness(mode, timeout=float(args.timeout), capture_words=int(args.capture_words))
                    payload_rec = _payload_record(
                        T510FEngine,
                        witness,
                        mode=mode,
                        signal_hz=float(setup["signal_hz"]),
                        center_hz=float(setup["center_hz"]),
                        args=args,
                    )
                    record["payload"] = payload_rec
                    record["sample0_delta"] = int(payload_rec["sample0"]) - int(preview_rec["sample0"])
                    consecutive_timeouts = 0
                except TimeoutError as exc:
                    record["payload_error"] = str(exc)
                    record["sample0_delta"] = None
                    condition["witness_timeouts"] = int(condition.get("witness_timeouts", 0)) + 1
                    consecutive_timeouts += 1
                condition["records"].append(record)
                if consecutive_timeouts >= int(args.max_consecutive_witness_timeouts):
                    condition["aborted_after_consecutive_witness_timeouts"] = consecutive_timeouts
                    break
                if float(args.seconds_between_frames) > 0.0:
                    time.sleep(float(args.seconds_between_frames))

            summary = _summarize_pair(condition["records"])
            classification, gate = _classify(summary)
            condition["summary"] = summary
            condition["classification"] = classification
            condition["data_quality_gate"] = gate
            if int(condition.get("witness_timeouts", 0)) > 0:
                condition["witness_timeouts"] = int(condition["witness_timeouts"])
            result["conditions"].append(condition)
            condition_index += 1

    gates = {str(item["data_quality_gate"]) for item in result["conditions"]}
    classifications = {str(item["classification"]) for item in result["conditions"]}
    if "BLOCK_QSFP_LIVE_DATA_QUALITY" in gates:
        result["data_quality_gate"] = "BLOCK_QSFP_LIVE_DATA_QUALITY"
    elif "WARN_QSFP_LIVE_DATA_QUALITY" in gates:
        result["data_quality_gate"] = "WARN_QSFP_LIVE_DATA_QUALITY"
    else:
        result["data_quality_gate"] = "READY_FOR_QSFP_PREFLIGHT_ONLY"
    result["classification"] = ",".join(sorted(classifications))
    print(json.dumps(_jsonable(result), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
