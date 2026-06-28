#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any


EXPECTED_PPS = {
    20: 120_000.0,
    100: 480_000.0,
    200: 960_000.0,
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _jsonable(value: Any) -> Any:
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


def _fetch_json(url: str, timeout: float) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _net_stat(interface: str, name: str) -> int | None:
    path = Path("/sys/class/net") / interface / "statistics" / name
    try:
        return int(path.read_text().strip())
    except (FileNotFoundError, ValueError):
        return None


def _kernel_counters(interface: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for name in (
        "rx_packets",
        "rx_bytes",
        "rx_dropped",
        "rx_errors",
        "rx_missed_errors",
        "rx_crc_errors",
        "tx_packets",
        "tx_bytes",
        "tx_dropped",
        "tx_errors",
    ):
        value = _net_stat(interface, name)
        if value is not None:
            out[name] = value
    return out


def _ethtool_stats(interface: str) -> dict[str, int]:
    try:
        proc = subprocess.run(
            ["ethtool", "-S", interface],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        return {}
    if proc.returncode != 0:
        return {}
    out: dict[str, int] = {}
    for line in proc.stdout.splitlines():
        match = re.match(r"\s*([^:]+):\s*([0-9]+)\s*$", line)
        if not match:
            continue
        out[match.group(1).strip()] = int(match.group(2))
    return out


def _delta(after: dict[str, int], before: dict[str, int]) -> dict[str, int]:
    return {
        key: int(after.get(key, 0)) - int(before.get(key, 0))
        for key in sorted(set(before) | set(after))
        if int(after.get(key, 0)) - int(before.get(key, 0)) != 0
    }


def _queue_packet_deltas(stats_delta: dict[str, int]) -> dict[str, int]:
    queue_packets: dict[str, int] = {}
    patterns = (
        re.compile(r"^(rx[_-]?queue[_-]?(\d+)|rx(\d+)).*(packets|packet)$", re.IGNORECASE),
        re.compile(r"^(rx_q(\d+)).*(packets|packet)$", re.IGNORECASE),
    )
    for key, value in stats_delta.items():
        if value <= 0:
            continue
        for pattern in patterns:
            match = pattern.search(key)
            if match:
                queue_id = next((group for group in match.groups()[1:3] if group is not None), None)
                if queue_id is not None:
                    queue_packets[queue_id] = queue_packets.get(queue_id, 0) + value
                break
    return queue_packets


def _sum_named_delta(delta: dict[str, int], patterns: tuple[str, ...]) -> int:
    regexes = [re.compile(pattern, re.IGNORECASE) for pattern in patterns]
    total = 0
    for key, value in delta.items():
        if any(regex.search(key) for regex in regexes):
            total += max(0, int(value))
    return total


def _state_stats(state: dict[str, Any]) -> dict[str, Any]:
    stats = state.get("stats")
    if not isinstance(stats, dict):
        raise RuntimeError("/api/state did not contain a stats object")
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Stage 27c Rust 8-flow TIME receiver state.")
    parser.add_argument("--url", default="http://127.0.0.1:8089/api/state")
    parser.add_argument("--interface", default="ens2f0np0")
    parser.add_argument("--bandwidth-mhz", type=int, choices=(20, 100, 200), required=True)
    parser.add_argument("--seconds", type=float, default=8.0)
    parser.add_argument("--poll-interval", type=float, default=0.5)
    parser.add_argument("--min-rx-ratio", type=float, default=0.95)
    parser.add_argument("--min-active-rx-queues", type=int, default=4)
    parser.add_argument("--output")
    args = parser.parse_args()

    default_output = _repo_root() / "reports" / "board" / f"stage27c_rust_rx_{args.bandwidth_mhz}mhz.json"
    output_path = args.output or str(default_output)
    expected_pps = EXPECTED_PPS[int(args.bandwidth_mhz)]
    threshold_pps = expected_pps * float(args.min_rx_ratio)

    kernel_before = _kernel_counters(args.interface)
    ethtool_before = _ethtool_stats(args.interface)
    state_before = _fetch_json(args.url, timeout=2.0)
    stats_before = _state_stats(state_before)

    samples: list[dict[str, Any]] = []
    deadline = time.monotonic() + max(float(args.seconds), 0.1)
    while time.monotonic() < deadline:
        time.sleep(max(float(args.poll_interval), 0.05))
        try:
            state = _fetch_json(args.url, timeout=2.0)
            samples.append(_state_stats(state))
        except Exception as exc:  # noqa: BLE001 - want diagnostic payload
            samples.append({"sample_error": f"{type(exc).__name__}: {exc}"})

    state_after = _fetch_json(args.url, timeout=2.0)
    stats_after = _state_stats(state_after)
    kernel_after = _kernel_counters(args.interface)
    ethtool_after = _ethtool_stats(args.interface)
    kernel_delta = _delta(kernel_after, kernel_before)
    ethtool_delta = _delta(ethtool_after, ethtool_before)
    queue_packets = _queue_packet_deltas(ethtool_delta)

    seq_gaps_delta = int(stats_after.get("seq_gaps", 0)) - int(stats_before.get("seq_gaps", 0))
    frame_gaps_delta = int(stats_after.get("frame_gaps", 0)) - int(stats_before.get("frame_gaps", 0))
    sample0_gaps_delta = int(stats_after.get("sample0_gaps", 0)) - int(stats_before.get("sample0_gaps", 0))
    parse_errors_delta = int(stats_after.get("parse_errors", 0)) - int(stats_before.get("parse_errors", 0))
    ring_drops_delta = int(stats_after.get("ring_drops", 0)) - int(stats_before.get("ring_drops", 0))
    kernel_drops_delta = int(stats_after.get("kernel_drops", 0)) - int(stats_before.get("kernel_drops", 0))
    rx_processed_pps = float(stats_after.get("rx_processed_packets_per_sec", 0.0))
    detected_mhz = stats_after.get("detected_bandwidth_mhz")
    selected_mhz = stats_after.get("selected_bandwidth_mhz")
    mismatch = bool(stats_after.get("selected_detected_mismatch", False))
    display_hz = float(stats_after.get("display_update_hz", 0.0))

    nic_error_delta = 0
    nic_error_delta += int(kernel_delta.get("rx_dropped", 0))
    nic_error_delta += int(kernel_delta.get("rx_errors", 0))
    nic_error_delta += int(kernel_delta.get("rx_missed_errors", 0))
    nic_error_delta += int(kernel_delta.get("rx_crc_errors", 0))
    nic_error_delta += _sum_named_delta(
        ethtool_delta,
        (
            r"rx.*drop",
            r"rx.*miss",
            r"rx.*error",
            r"rx.*crc",
            r"rx.*symbol",
            r"rx.*buffer",
        ),
    )

    errors: list[str] = []
    blockers: list[str] = []
    if int(selected_mhz or 0) != int(args.bandwidth_mhz):
        errors.append(f"SELECTED_BANDWIDTH_MISMATCH selected={selected_mhz} expected={args.bandwidth_mhz}")
    if detected_mhz is None:
        errors.append("DETECTED_BANDWIDTH_UNKNOWN")
    if detected_mhz is not None and int(detected_mhz) != int(args.bandwidth_mhz):
        errors.append(f"DETECTED_BANDWIDTH_MISMATCH detected={detected_mhz} expected={args.bandwidth_mhz}")
    if mismatch:
        errors.append("SELECTED_DETECTED_MISMATCH")
    if rx_processed_pps < threshold_pps:
        errors.append(f"RX_PROCESSED_LOW {rx_processed_pps:.3f} < {threshold_pps:.3f}")
    if seq_gaps_delta or frame_gaps_delta or sample0_gaps_delta:
        errors.append(f"TIME_GAPS seq={seq_gaps_delta} frame={frame_gaps_delta} sample0={sample0_gaps_delta}")
    if parse_errors_delta:
        errors.append(f"PARSE_ERRORS delta={parse_errors_delta}")
    if ring_drops_delta or kernel_drops_delta:
        errors.append(f"RING_OR_KERNEL_DROPS ring={ring_drops_delta} kernel={kernel_drops_delta}")
    if nic_error_delta:
        errors.append(f"NIC_DROP_OR_ERROR_COUNTERS delta_sum={nic_error_delta}")
    if not queue_packets:
        blockers.append("BLOCK_RSS_QUEUE_COUNTER_UNAVAILABLE")
    elif len(queue_packets) < int(args.min_active_rx_queues):
        blockers.append(
            f"BLOCK_STAGE27C_RSS_NOT_DISTRIBUTING_FLOWS active_queues={len(queue_packets)} "
            f"required={int(args.min_active_rx_queues)}"
        )

    if blockers:
        classification = "HOST_STAGE27C_RUST_RX_BLOCKED"
    elif errors:
        if rx_processed_pps < threshold_pps or seq_gaps_delta or frame_gaps_delta or sample0_gaps_delta:
            classification = "BLOCK_STAGE27C_HOST_RSS_RX_LIMIT"
        else:
            classification = "HOST_STAGE27C_RUST_RX_FAIL"
    else:
        classification = "HOST_STAGE27C_RUST_RX_PASS"

    result = {
        "classification": classification,
        "ok": classification == "HOST_STAGE27C_RUST_RX_PASS",
        "bandwidth_mhz": int(args.bandwidth_mhz),
        "expected_packets_per_sec": expected_pps,
        "threshold_packets_per_sec": threshold_pps,
        "rx_processed_packets_per_sec": rx_processed_pps,
        "display_update_hz": display_hz,
        "selected_bandwidth_mhz": selected_mhz,
        "detected_bandwidth_mhz": detected_mhz,
        "selected_detected_mismatch": mismatch,
        "gap_deltas": {
            "seq_gaps": seq_gaps_delta,
            "frame_gaps": frame_gaps_delta,
            "sample0_gaps": sample0_gaps_delta,
        },
        "parse_errors_delta": parse_errors_delta,
        "ring_drops_delta": ring_drops_delta,
        "kernel_drops_delta": kernel_drops_delta,
        "nic_error_delta_sum": nic_error_delta,
        "active_rx_queue_count": len(queue_packets),
        "rx_queue_packet_deltas": queue_packets,
        "kernel_counter_delta": kernel_delta,
        "ethtool_counter_delta": ethtool_delta,
        "stats_before": stats_before,
        "stats_after": stats_after,
        "samples": samples,
        "errors": errors,
        "blockers": blockers,
        "result": "PASS" if classification == "HOST_STAGE27C_RUST_RX_PASS" else ("BLOCKED" if blockers else "FAIL"),
    }
    print(json.dumps(_jsonable(result), indent=2, sort_keys=True))
    _write_output(output_path, result)
    return 0 if result["result"] == "PASS" else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001 - command-line diagnostic
        print(json.dumps({"classification": "HOST_STAGE27C_RUST_RX_ERROR", "error": f"{type(exc).__name__}: {exc}"}))
        raise
