#!/usr/bin/env python3
"""Capture one operator-applied Stage 32 physical reference fault.

The helper configures the existing Stage 32 release, schedules a 320 MS/s
TIME_ONLY stream, prints an explicit cable-disconnect prompt, and records the
hardware timeline until the selected physical fault is visible.  It does not
change RTL, the Board Agent contract, or the UDP format.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import time
from typing import Any

from stage32h_pps_switch_campaign import (
    SIGNAL_CHAIN_TAGS,
    _compact_snapshot,
    _configured_body,
    _read_json,
    _request,
)


def _timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _sample(result: dict[str, Any]) -> dict[str, Any]:
    snapshot = dict(result.get("snapshot", {}))
    sync = dict(result.get("sync", snapshot.get("scheduled_sync", {})))
    clock = dict(snapshot.get("clock", {}))
    pipeline = dict(snapshot.get("pipeline", {}))
    counters = dict(snapshot.get("counters", {}))
    watchdog = dict(snapshot.get("reference_watchdog", {}))
    watchdog_lock_value = watchdog.get("lock_status")
    watchdog_lock = (
        dict(watchdog_lock_value)
        if isinstance(watchdog_lock_value, dict)
        else {}
    )
    watchdog_fault_value = watchdog.get("last_fault")
    watchdog_fault = (
        dict(watchdog_fault_value)
        if isinstance(watchdog_fault_value, dict)
        else {}
    )
    watchdog_after_value = watchdog_fault.get("after")
    watchdog_after = (
        dict(watchdog_after_value)
        if isinstance(watchdog_after_value, dict)
        else {}
    )
    return {
        "observed_at": _timestamp(),
        "captured_at_unix_ms": snapshot.get("captured_at_unix_ms"),
        "streaming": bool(sync.get("streaming", snapshot.get("streaming", False))),
        "selected": bool(sync.get("selected", False)),
        "state": int(sync.get("state", 0)),
        "error": bool(sync.get("error", False)),
        "error_code": int(sync.get("error_code", 0)),
        "error_name": str(sync.get("error_name", "none")),
        "pps_recent": bool(sync.get("pps_recent", False)),
        "ref_locked": bool(sync.get("ref_locked", False)),
        "rfdc_ready": bool(sync.get("rfdc_ready", False)),
        "current_pps_count": int(sync.get("current_pps_count", 0)),
        "pll1_lock": int(clock.get("pll1_lock", 0)),
        "pll2_lock": int(clock.get("pll2_lock", 0)),
        "clock_configured": bool(clock.get("configured", False)),
        "stream_accepting": bool(pipeline.get("stream_accepting", False)),
        "flush_clean": bool(pipeline.get("flush_clean", False)),
        "time_packets": int(counters.get("time_packets", 0)),
        "spec_packets": int(counters.get("spec_packets", 0)),
        "time_dropped": int(counters.get("time_dropped", 0)),
        "tx_frames_dropped": int(counters.get("tx_frames_dropped", 0)),
        "rfdc_dropped": int(counters.get("rfdc_dropped", 0)),
        "science_dropped_beats": int(counters.get("science_dropped_beats", 0)),
        "watchdog_available": bool(watchdog.get("available", False)),
        "watchdog_healthy": bool(watchdog.get("healthy", False)),
        "watchdog_stale": bool(watchdog.get("stale", True)),
        "watchdog_fault_latched": bool(watchdog.get("fault_latched", False)),
        "watchdog_mode": str(watchdog.get("mode", "UNAVAILABLE")),
        "watchdog_age_ms": watchdog.get("age_ms"),
        "watchdog_pll1_lock": watchdog_lock.get("pll1_lock"),
        "watchdog_pll2_lock": watchdog_lock.get("pll2_lock"),
        "watchdog_fault_reason": watchdog_fault.get("reason"),
        "watchdog_stop_ok": bool(watchdog_fault.get("stop_ok", False)),
        "watchdog_stop_latency_ms": watchdog_fault.get("stop_latency_ms"),
        "watchdog_after_streaming": watchdog_after.get("streaming"),
        "watchdog_after_flush_clean": watchdog_after.get("flush_clean"),
    }


def _physical_seen(fault: str, sample: dict[str, Any]) -> bool:
    if fault == "pps":
        return not bool(sample["pps_recent"])
    return (
        int(sample["pll1_lock"]) == 0
        or sample.get("watchdog_pll1_lock") == 0
        or sample.get("watchdog_fault_reason") == "LMK_PLL1_UNLOCKED"
    )


def _wait_for_stream(
    base: str,
    *,
    generation: int,
    target_pps: int,
    timeout_seconds: float,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    deadline = time.monotonic() + timeout_seconds
    samples: list[dict[str, Any]] = []
    while time.monotonic() < deadline:
        result = _request(base, "/api/v1/sync/status", timeout=20.0)
        sample = _sample(result)
        samples.append(sample)
        sync = dict(result.get("sync", {}))
        if bool(sync.get("error")):
            raise RuntimeError(
                "scheduler error before stream: "
                f"{sync.get('error_name')} ({sync.get('error_code')})"
            )
        if (
            bool(sync.get("streaming"))
            and int(sync.get("generation", 0)) == generation
            and int(sync.get("actual_commit_pps_count", 0)) == target_pps
        ):
            return samples, result
        time.sleep(0.1)
    raise TimeoutError("scheduled stream did not commit before timeout")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fault", choices=("pps", "10mhz"), required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--config",
        default="config/stage32/configure_320_time_only.example.json",
    )
    parser.add_argument("--agent-base", default="http://192.168.100.117:8010")
    parser.add_argument("--generation", type=int, required=True)
    parser.add_argument(
        "--lead-pps",
        type=int,
        default=35,
        help="future PPS lead; 35 seconds covers the stateless helper startup latency",
    )
    parser.add_argument("--operator-timeout-seconds", type=float, default=300.0)
    parser.add_argument("--post-fault-seconds", type=float, default=4.0)
    parser.add_argument("--poll-seconds", type=float, default=0.1)
    args = parser.parse_args()
    if args.generation <= 0:
        parser.error("--generation must be positive")
    if args.lead_pps < 30:
        parser.error("--lead-pps must be at least 30")
    if args.operator_timeout_seconds < 10.0:
        parser.error("--operator-timeout-seconds must be at least 10")
    if args.post_fault_seconds < 2.0:
        parser.error("--post-fault-seconds must be at least 2")
    if not 0.05 <= args.poll_seconds <= 1.0:
        parser.error("--poll-seconds must be between 0.05 and 1")

    root = Path(__file__).resolve().parents[1]
    config_path = (root / args.config).resolve()
    output_path = (root / args.output).resolve()
    template = _read_json(config_path)
    base = args.agent_base.rstrip("/")
    result: dict[str, Any] = {
        "stage": "32h-d",
        "test": "physical_reference_fault_while_scheduled_streaming",
        "fault": args.fault,
        "generation": args.generation,
        "started_at": _timestamp(),
        "ended_at": None,
        "agent_base": base,
        "config": str(config_path),
        "config_sha256": _sha256(config_path),
        "script_sha256": _sha256(Path(__file__).resolve()),
        "bitstream_expected_sha256": (
            "439080046408267493a031efa1d097fcd3c2f818850ee9eac"
            "1925ae95d6b094c"
        ),
        "timeline": [],
        "errors": [],
        "ok": False,
    }
    configured = False
    physical_seen_at: float | None = None
    try:
        configure = _request(
            base,
            "/api/v1/configure",
            _configured_body(template, 320, "time_only"),
        )
        configured = True
        result["configure"] = {
            "elapsed_ms": configure.get("elapsed_ms"),
            "bitstream": configure.get("bitstream"),
            "snapshot": _compact_snapshot(dict(configure.get("status", {}))),
        }
        configured_snapshot = dict(configure.get("status", {}))
        configured_clock = dict(configured_snapshot.get("clock", {}))
        if not bool(configured_clock.get("configured")):
            raise RuntimeError("clock not configured after CONFIGURE")
        if (
            int(configured_clock.get("pll1_lock", 0)) != 1
            or int(configured_clock.get("pll2_lock", 0)) != 1
        ):
            raise RuntimeError("LMK PLL1/PLL2 are not both locked")

        # CONFIGURE holds the cross-process hardware lock through its final
        # snapshot, so that response may legitimately show CONFIGURE_PAUSE.
        # Once the request returns, let the watchdog reconnect to the newly
        # timestamped PL identity before PREPARE/ARM.
        time.sleep(0.3)
        initial = _request(base, "/api/v1/sync/status", timeout=20.0)
        initial_snapshot = dict(initial.get("snapshot", {}))
        initial_watchdog = dict(
            initial_snapshot.get("reference_watchdog", {})
        )
        if not (
            bool(initial_watchdog.get("available"))
            and bool(initial_watchdog.get("healthy"))
            and not bool(initial_watchdog.get("stale", True))
            and not bool(initial_watchdog.get("fault_latched"))
        ):
            raise RuntimeError(
                "PS reference watchdog is not ready before PREPARE: "
                f"{initial_watchdog}"
            )
        sync = dict(initial.get("sync", {}))
        if not bool(sync.get("pps_recent")):
            raise RuntimeError("PPS is not recent before PREPARE")
        target_pps = int(sync["current_pps_count"]) + args.lead_pps
        prepare_body = {
            "expected_board_id": int(template["board_id"]),
            "generation": args.generation,
            "target_pps_count": target_pps,
            "epoch_tai_seconds": int(time.time()) + args.lead_pps,
            "first_sample0": int(sync["default_first_sample0"]),
            "observation_tag": 0x53324850,
            "signal_chain_tag": SIGNAL_CHAIN_TAGS[(320, "time_only")],
            "schedule_tag": 0x50485953,
            "mts_result_id": int(sync["mts_result_id"]),
        }
        result["prepare_body"] = prepare_body
        result["prepare"] = _request(
            base, "/api/v1/sync/prepare", prepare_body, timeout=20.0
        )
        result["arm"] = _request(
            base,
            "/api/v1/sync/arm",
            {"expected_board_id": int(template["board_id"])},
            timeout=20.0,
        )
        commit_samples, committed = _wait_for_stream(
            base,
            generation=args.generation,
            target_pps=target_pps,
            timeout_seconds=float(args.lead_pps + 15),
        )
        result["commit_timeline"] = commit_samples
        before = _sample(committed)
        time.sleep(0.5)
        advancing = _sample(_request(base, "/api/v1/sync/status", timeout=20.0))
        result["timeline"].extend((before, advancing))
        if int(advancing["time_packets"]) <= int(before["time_packets"]):
            raise RuntimeError("TIME packet counter did not advance before fault")

        prompt = (
            "READY_DISCONNECT_PPS"
            if args.fault == "pps"
            else "READY_DISCONNECT_10MHZ"
        )
        print(
            f"{prompt} generation={args.generation} "
            f"time_packets={advancing['time_packets']}",
            flush=True,
        )

        operator_deadline = time.monotonic() + args.operator_timeout_seconds
        post_fault_deadline: float | None = None
        while time.monotonic() < operator_deadline:
            observed = _sample(
                _request(base, "/api/v1/sync/status", timeout=20.0)
            )
            result["timeline"].append(observed)
            if physical_seen_at is None and _physical_seen(args.fault, observed):
                physical_seen_at = time.monotonic()
                post_fault_deadline = physical_seen_at + args.post_fault_seconds
                result["physical_fault_first_observation"] = observed
                print(
                    "PHYSICAL_FAULT_SEEN "
                    f"fault={args.fault} state={observed['state']} "
                    f"streaming={observed['streaming']} "
                    f"error={observed['error_name']}",
                    flush=True,
                )
            if post_fault_deadline is not None and time.monotonic() >= post_fault_deadline:
                break
            time.sleep(args.poll_seconds)

        if physical_seen_at is None:
            result["errors"].append("PHYSICAL_FAULT_NOT_OBSERVED")
        post_fault = (
            result["timeline"][2:]
            if len(result["timeline"]) > 2
            else []
        )
        auto_stopped = any(not bool(item["streaming"]) for item in post_fault)
        expected_error = 7 if args.fault == "pps" else 5
        expected_error_seen = any(
            bool(item["error"]) and int(item["error_code"]) == expected_error
            for item in post_fault
        )
        watchdog_fault_seen = any(
            bool(item["watchdog_fault_latched"])
            and item["watchdog_fault_reason"] == "LMK_PLL1_UNLOCKED"
            and bool(item["watchdog_stop_ok"])
            and item["watchdog_after_streaming"] is False
            and bool(item["watchdog_after_flush_clean"])
            for item in post_fault
        )
        result["automatic_stop_observed"] = auto_stopped
        result["expected_scheduler_error_code"] = expected_error
        result["expected_scheduler_error_observed"] = expected_error_seen
        result["watchdog_fault_observed"] = watchdog_fault_seen
        if physical_seen_at is not None and not auto_stopped:
            result["errors"].append("ACTIVE_STREAM_DID_NOT_AUTOMATICALLY_STOP")
        if (
            physical_seen_at is not None
            and args.fault == "pps"
            and not expected_error_seen
        ):
            result["errors"].append("EXPECTED_SCHEDULER_ERROR_NOT_LATCHED")
        if (
            physical_seen_at is not None
            and args.fault == "10mhz"
            and not watchdog_fault_seen
        ):
            result["errors"].append("EXPECTED_PS_WATCHDOG_FAULT_NOT_LATCHED")
    except Exception as exc:  # noqa: BLE001 - always preserve and stop after test
        result["errors"].append(f"{type(exc).__name__}: {exc}")
    finally:
        if configured:
            try:
                result["stop"] = _request(
                    base,
                    "/api/v1/stop",
                    {"reason": f"stage32h_physical_{args.fault}_fault"},
                    timeout=30.0,
                )
            except Exception as exc:  # noqa: BLE001
                result["errors"].append(f"STOP_FAILED:{type(exc).__name__}:{exc}")
        result["ended_at"] = _timestamp()
        result["ok"] = not result["errors"]
        result["classification"] = (
            f"STAGE32H_PHYSICAL_{args.fault.upper()}_FAULT_PASS"
            if result["ok"]
            else f"STAGE32H_PHYSICAL_{args.fault.upper()}_FAULT_FAIL"
        )
        _write_json(output_path, result)
        print(json.dumps(
            {
                "classification": result["classification"],
                "errors": result["errors"],
                "output": str(output_path),
            },
            indent=2,
            sort_keys=True,
        ), flush=True)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
