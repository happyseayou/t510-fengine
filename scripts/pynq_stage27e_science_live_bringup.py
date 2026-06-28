#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any


EXPECTED_CORE_VERSION = 0x0001_001F


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _add_repo_python_path() -> None:
    sys.path.insert(0, str(_repo_root()))


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


def _counter_delta(now: int, prev: int, bits: int = 32) -> int:
    return (int(now) - int(prev)) % (1 << bits)


def _mode_key(value: str) -> str:
    key = str(value).strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "time": "time_only",
        "time_only": "time_only",
        "spec": "spec_only",
        "spec_only": "spec_only",
        "time_spec": "time_spec",
        "dual": "time_spec",
    }
    if key not in aliases:
        raise argparse.ArgumentTypeError("mode must be time_only, spec_only, or time_spec")
    return aliases[key]


def _parse_case_item(item: str) -> tuple[str, int]:
    if ":" not in item:
        raise argparse.ArgumentTypeError("case items must be mode:bandwidth, e.g. time_spec:100")
    mode, bandwidth = item.split(":", 1)
    bw = int(round(float(bandwidth.lower().replace("mhz", "").strip())))
    if bw not in (20, 100, 200):
        raise argparse.ArgumentTypeError("bandwidth must be 20, 100, or 200")
    return _mode_key(mode), bw


def _parse_cases(value: str) -> list[tuple[str, int]]:
    key = str(value).strip().lower()
    if key == "smoke":
        return [
            ("time_only", 20),
            ("time_only", 100),
            ("time_only", 200),
            ("spec_only", 100),
            ("time_spec", 20),
            ("time_spec", 100),
        ]
    if key == "full":
        return [
            ("time_only", 20),
            ("time_only", 100),
            ("time_only", 200),
            ("spec_only", 20),
            ("spec_only", 100),
            ("spec_only", 200),
            ("time_spec", 20),
            ("time_spec", 100),
        ]
    return [_parse_case_item(item.strip()) for item in value.split(",") if item.strip()]


def _case_needs_time(mode: str) -> bool:
    return mode in ("time_only", "time_spec")


def _case_needs_spec(mode: str) -> bool:
    return mode in ("spec_only", "time_spec")


def _tx_live_ready(tx_status: dict[str, Any]) -> bool:
    return bool(
        int(tx_status.get("gt_locked", 0))
        and int(tx_status.get("cmac_reset_done", 0))
        and int(tx_status.get("cmac_tx_ready", 0))
        and not int(tx_status.get("udp_dry_run_active", 1))
        and not int(tx_status.get("tx_local_fault", 0))
        and not int(tx_status.get("tx_remote_fault", 0))
    )


def _tx_link_ready(tx_status: dict[str, Any]) -> bool:
    return bool(
        int(tx_status.get("gt_locked", 0))
        and int(tx_status.get("cmac_reset_done", 0))
        and int(tx_status.get("cmac_tx_ready", 0))
        and int(tx_status.get("qsfp_link_up", 1))
        and not int(tx_status.get("tx_local_fault", 0))
        and not int(tx_status.get("tx_remote_fault", 0))
    )


def _wait_for_tx_link_ready(core: Any, args: argparse.Namespace) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    deadline = time.monotonic() + max(float(args.preflight_link_wait_s), 0.0)
    poll_s = max(float(args.preflight_link_poll_s), 0.0)
    while True:
        sample = core.read_tx_status()
        samples.append(sample)
        if _tx_link_ready(sample) or time.monotonic() >= deadline:
            return samples
        time.sleep(poll_s)


def _sample_tx_until_live(core: Any, args: argparse.Namespace) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    samples: list[dict[str, Any]] = []
    retry_count = max(int(args.tx_status_retries), 0)
    retry_s = max(float(args.tx_status_retry_s), 0.0)
    for attempt in range(retry_count + 1):
        sample = core.read_tx_status()
        samples.append(sample)
        if _tx_live_ready(sample) or attempt >= retry_count:
            return sample, samples
        time.sleep(retry_s)
    return samples[-1], samples


def _classify_case(
    mode: str,
    bandwidth_mhz: int,
    before: dict[str, Any],
    after: dict[str, Any],
    tx_before: dict[str, Any],
    tx_after: dict[str, Any],
    science_after: dict[str, Any],
    *,
    min_packet_delta: int,
) -> tuple[str, list[str], list[str], dict[str, int]]:
    deltas = {
        "time_packet_count": _counter_delta(after.get("time_packet_count", 0), before.get("time_packet_count", 0)),
        "spec_packet_count": _counter_delta(after.get("spec_packet_count", 0), before.get("spec_packet_count", 0)),
        "spec_dropped_count": _counter_delta(after.get("spec_dropped_count", 0), before.get("spec_dropped_count", 0)),
        "rfdc_dropped_count": _counter_delta(after.get("rfdc_dropped_count", 0), before.get("rfdc_dropped_count", 0)),
        "tx_frame_built_count": _counter_delta(after.get("tx_frame_built_count", 0), before.get("tx_frame_built_count", 0)),
        "tx_frame_byte_count": _counter_delta(after.get("tx_frame_byte_count", 0), before.get("tx_frame_byte_count", 0)),
        "tx_route_miss_count": _counter_delta(after.get("tx_route_miss_count", 0), before.get("tx_route_miss_count", 0)),
        "tx_route_error_count": _counter_delta(after.get("tx_route_error_count", 0), before.get("tx_route_error_count", 0)),
        "tx_cmac_accepted_packet_count": _counter_delta(
            tx_after.get("tx_cmac_accepted_packet_count", 0),
            tx_before.get("tx_cmac_accepted_packet_count", 0),
        ),
        "tx_frame_dropped_count": _counter_delta(
            tx_after.get("tx_frame_dropped_count", 0),
            tx_before.get("tx_frame_dropped_count", 0),
        ),
    }
    errors: list[str] = []
    blockers: list[str] = []
    if int(science_after.get("science_bandwidth_mhz", 0)) != int(bandwidth_mhz):
        errors.append("SCIENCE_BANDWIDTH_MISMATCH")
    if str(science_after.get("science_output_mode", "")).upper() != mode.upper():
        errors.append("SCIENCE_MODE_MISMATCH")
    for key, label in (
        ("gt_locked", "GT_NOT_LOCKED"),
        ("cmac_reset_done", "CMAC_RESET_NOT_DONE"),
        ("cmac_tx_ready", "CMAC_TX_NOT_READY"),
    ):
        if not int(tx_after.get(key, 0)):
            blockers.append(label)
    if int(tx_after.get("tx_local_fault", 0)):
        blockers.append("CMAC_LOCAL_FAULT")
    if int(tx_after.get("tx_remote_fault", 0)):
        blockers.append("CMAC_REMOTE_FAULT")
    if int(tx_after.get("udp_dry_run_active", 1)):
        errors.append("TX_STILL_DRY_RUN")
    if int(tx_after.get("tx_underflow", 0)):
        errors.append("CMAC_TX_UNDERFLOW")
    if int(tx_after.get("tx_overflow", 0)):
        errors.append("CMAC_TX_OVERFLOW")
    if _case_needs_time(mode):
        if deltas["time_packet_count"] < min_packet_delta:
            errors.append("TIME_PACKET_COUNTER_NOT_INCREMENTING")
        if not int(tx_after.get("tx_time_live_requested_data", 0)):
            errors.append("TIME_LIVE_NOT_REQUESTED_DATA_CLK")
        if deltas["rfdc_dropped_count"] != 0:
            errors.append("RFDC_DROPPED_DURING_TIME_STREAM")
    if _case_needs_spec(mode):
        if deltas["spec_packet_count"] < min_packet_delta:
            errors.append("SPEC_PACKET_COUNTER_NOT_INCREMENTING")
        if not int(tx_after.get("tx_spec_live_requested_data", 0)):
            errors.append("SPEC_LIVE_NOT_REQUESTED_DATA_CLK")
    if deltas["tx_frame_built_count"] < min_packet_delta:
        errors.append("TX_FRAME_COUNTER_NOT_INCREMENTING")
    if deltas["tx_route_miss_count"] != 0:
        errors.append("TX_ROUTE_MISS")
    if deltas["tx_route_error_count"] != 0:
        errors.append("TX_ROUTE_ERROR")
    if deltas["tx_frame_dropped_count"] != 0:
        errors.append("TX_FRAME_DROPPED")

    if blockers:
        classification = "STAGE27E_SCIENCE_LIVE_BLOCKED"
    elif errors:
        classification = "STAGE27E_SCIENCE_LIVE_FAIL"
    else:
        classification = "STAGE27E_SCIENCE_LIVE_PASS"
    return classification, errors, blockers, deltas


def _validate_case(core: Any, args: argparse.Namespace, mode: str, bandwidth_mhz: int, case_index: int) -> dict[str, Any]:
    config = core.configure_science_live_27e(
        bandwidth_mhz=bandwidth_mhz,
        output_mode=mode,
        dst_ip=args.dst_ip,
        dst_mac=args.dst_mac,
        src_ip=args.src_ip,
        src_mac=args.src_mac,
        time_dst_port_base=int(args.time_dst_port_base),
        spec_dst_port_base=int(args.spec_dst_port_base),
        time_src_port_base=int(args.time_src_port_base),
        spec_src_port_base=int(args.spec_src_port_base),
        time_endpoint_base=int(args.time_endpoint_base),
        spec_endpoint_base=int(args.spec_endpoint_base),
        time_flow_count=int(args.time_flow_count),
        spec_route_count=int(args.spec_route_count),
        time_payload_nsamp=int(args.time_payload_nsamp),
        time_live_interval_beats=int(args.time_live_interval_beats),
        spec_chan_count=int(args.spec_chan_count),
        spec_time_count=int(args.spec_time_count),
        spec_chan0_stride=int(args.spec_chan0_stride),
        input_mask=int(args.input_mask, 0) if isinstance(args.input_mask, str) else int(args.input_mask),
        force_dry_run=False,
        cmac_enable=True,
        diagnostic_ignore_link_gate=bool(args.diagnostic_ignore_link_gate),
        clear_counters=True,
        sync_mode=(None if case_index > 0 else (None if str(args.sync_mode).lower() == "none" else str(args.sync_mode))),
        start=not bool(args.no_start),
        settle_s=float(args.settle_s),
    )
    before = core.read_status()
    tx_before = core.read_tx_status()
    time.sleep(max(float(args.seconds), 0.0))
    after = core.read_status()
    tx_after, tx_status_samples = _sample_tx_until_live(core, args)
    if len(tx_status_samples) > 1:
        after = core.read_status()
    science_after = core.read_science_output_status()
    classification, errors, blockers, deltas = _classify_case(
        mode,
        bandwidth_mhz,
        before,
        after,
        tx_before,
        tx_after,
        science_after,
        min_packet_delta=int(args.min_packet_delta),
    )
    return {
        "mode": mode.upper(),
        "bandwidth_mhz": int(bandwidth_mhz),
        "classification": classification,
        "ok": classification == "STAGE27E_SCIENCE_LIVE_PASS",
        "config": config,
        "before": before,
        "after": after,
        "tx_after": tx_after,
        "tx_status_samples": tx_status_samples,
        "science_after": science_after,
        "deltas": deltas,
        "errors": errors,
        "blockers": blockers,
    }


def _validate_reject(core: Any) -> dict[str, Any]:
    try:
        core.configure_science_live_27e(bandwidth_mhz=200, output_mode="time_spec", start=False)
    except ValueError as exc:
        return {
            "mode": "TIME_SPEC",
            "bandwidth_mhz": 200,
            "classification": "STAGE27E_TIME_SPEC_200_REJECT_PASS",
            "ok": True,
            "error": str(exc),
        }
    except Exception as exc:
        return {
            "mode": "TIME_SPEC",
            "bandwidth_mhz": 200,
            "classification": "STAGE27E_TIME_SPEC_200_REJECT_FAIL",
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    return {
        "mode": "TIME_SPEC",
        "bandwidth_mhz": 200,
        "classification": "STAGE27E_TIME_SPEC_200_NOT_REJECTED",
        "ok": False,
        "error": "configure_science_live_27e accepted TIME_SPEC at 200MHz",
    }


def main() -> int:
    _add_repo_python_path()
    from python.t510_fengine import T510FEngine

    default_bitfile = _repo_root() / "overlay" / "t510_fengine.bit"
    default_output = _repo_root() / "reports" / "board" / "stage27e_science_live_board.json"
    parser = argparse.ArgumentParser(description="Stage 27e TIME/SPEC live science board bring-up on PYNQ.")
    parser.add_argument("--bitfile", default=str(default_bitfile))
    parser.add_argument("--no-download", action="store_true")
    parser.add_argument("--seconds", type=float, default=2.0)
    parser.add_argument("--matrix", default="smoke", help="smoke, full, or comma list like time_only:20,spec_only:100,time_spec:20")
    parser.add_argument("--dst-ip", default="10.0.1.16")
    parser.add_argument("--dst-mac", default="08:c0:eb:d5:95:b2")
    parser.add_argument("--src-ip", default="10.0.1.1")
    parser.add_argument("--src-mac", default="02:00:00:00:00:01")
    parser.add_argument("--time-dst-port-base", type=int, default=4300)
    parser.add_argument("--spec-dst-port-base", type=int, default=4308)
    parser.add_argument("--time-src-port-base", type=int, default=4000)
    parser.add_argument("--spec-src-port-base", type=int, default=4008)
    parser.add_argument("--time-endpoint-base", type=int, default=0)
    parser.add_argument("--spec-endpoint-base", type=int, default=8)
    parser.add_argument("--time-flow-count", type=int, default=8, choices=(1, 2, 4, 8))
    parser.add_argument("--spec-route-count", type=int, default=8)
    parser.add_argument("--time-payload-nsamp", type=int, default=64)
    parser.add_argument("--time-live-interval-beats", type=int, default=0)
    parser.add_argument("--spec-chan-count", type=int, default=64)
    parser.add_argument("--spec-time-count", type=int, default=4)
    parser.add_argument("--spec-chan0-stride", type=int, default=64)
    parser.add_argument("--input-mask", default="0x00ff")
    parser.add_argument("--min-packet-delta", type=int, default=1)
    parser.add_argument("--sync-mode", default="free_run")
    parser.add_argument("--settle-s", type=float, default=0.05)
    parser.add_argument("--preflight-link-wait-s", type=float, default=5.0)
    parser.add_argument("--preflight-link-poll-s", type=float, default=0.1)
    parser.add_argument("--tx-status-retries", type=int, default=5)
    parser.add_argument("--tx-status-retry-s", type=float, default=0.05)
    parser.add_argument("--no-start", action="store_true")
    parser.add_argument("--skip-reject-check", action="store_true")
    parser.add_argument("--diagnostic-ignore-link-gate", action="store_true")
    parser.add_argument("--expected-core-version", type=lambda value: int(value, 0), default=EXPECTED_CORE_VERSION)
    parser.add_argument("--output", default=str(default_output))
    args = parser.parse_args()

    cases = _parse_cases(args.matrix)
    core = T510FEngine(args.bitfile, download=not args.no_download)
    initial_status = core.read_status()
    expected_core_version = int(args.expected_core_version)
    errors: list[str] = []
    if int(initial_status.get("core_version", 0)) != expected_core_version:
        errors.append(
            f"expected CORE_VERSION 0x{expected_core_version:08x}, "
            f"got 0x{int(initial_status.get('core_version', 0)):08x}"
        )

    preflight_tx_status_samples = _wait_for_tx_link_ready(core, args)
    validations: list[dict[str, Any]] = []
    for case_index, (mode, bandwidth_mhz) in enumerate(cases):
        validations.append(_validate_case(core, args, mode, bandwidth_mhz, case_index))
    reject = None if args.skip_reject_check else _validate_reject(core)

    all_cases_ok = all(bool(item.get("ok", False)) for item in validations)
    blocked = any(str(item.get("classification", "")).endswith("_BLOCKED") for item in validations)
    reject_ok = True if reject is None else bool(reject.get("ok", False))
    ok = not errors and all_cases_ok and reject_ok
    classification = (
        "STAGE27E_SCIENCE_LIVE_PASS"
        if ok
        else ("STAGE27E_SCIENCE_LIVE_BLOCKED" if blocked else "STAGE27E_SCIENCE_LIVE_FAIL")
    )
    result = {
        "expected_core_version": f"0x{expected_core_version:08x}",
        "core_version": f"0x{int(initial_status.get('core_version', 0)):08x}",
        "classification": classification,
        "host_receiver_validated": False,
        "science_data_scope": "Stage 27e live TIME/SPEC preview; SPEC uses 8192B channel-window payload",
        "payload_contract": "TIME docs/time_udp_payload_v2.md; SPEC channel_window[time][channel][input][IQ16]",
        "status_initial": initial_status,
        "preflight_tx_status_samples": preflight_tx_status_samples,
        "validations": validations,
        "reject_check": reject,
        "host_receiver_next_step": {
            "binary": "rust/t510_time_rx/target/release/t510_time_rx",
            "interface": "ens2f0np0",
            "web": "0.0.0.0:8088",
            "dst_port_range": f"{args.time_dst_port_base}..{args.spec_dst_port_base + args.spec_route_count - 1}",
            "time_ports": f"{args.time_dst_port_base}..{args.time_dst_port_base + args.time_flow_count - 1}",
            "spec_ports": f"{args.spec_dst_port_base}..{args.spec_dst_port_base + args.spec_route_count - 1}",
            "recommended_args": [
                "--flow-count",
                "16",
                "--time-flow-count",
                str(args.time_flow_count),
                "--spec-flow-count",
                str(args.spec_route_count),
                "--fanout-mode",
                "port",
            ],
        },
        "result": "PASS" if ok else ("BLOCKED" if blocked else "FAIL"),
        "errors": errors,
    }
    print(json.dumps(_jsonable(result), indent=2, sort_keys=True))
    _write_output(args.output, result)
    return 0 if result["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
