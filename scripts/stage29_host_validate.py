#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import time
import urllib.request
from typing import Any


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def _fetch(url: str) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=3.0) as response:
        return json.loads(response.read().decode("utf-8"))


def _post_config(base: str, bandwidth: int, mode: str) -> None:
    request = urllib.request.Request(
        base.rstrip("/") + "/api/config",
        data=json.dumps({"bandwidth_mhz": bandwidth, "output_mode": mode}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=3.0) as response:
        response.read()


def _net(interface: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for path in (Path("/sys/class/net") / interface / "statistics").glob("*"):
        try:
            result[path.name] = int(path.read_text().strip())
        except (OSError, ValueError):
            pass
    return result


def _ethtool(interface: str) -> dict[str, int]:
    try:
        proc = subprocess.run(["ethtool", "-S", interface], text=True, capture_output=True, check=False)
    except FileNotFoundError:
        return {}
    result: dict[str, int] = {}
    for line in proc.stdout.splitlines():
        match = re.match(r"\s*([^:]+):\s*([0-9]+)\s*$", line)
        if match:
            result[match.group(1).strip()] = int(match.group(2))
    return result


def _delta(after: dict[str, Any], before: dict[str, Any], key: str) -> int:
    return int(after.get(key, 0) or 0) - int(before.get(key, 0) or 0)


def main() -> int:
    parser = argparse.ArgumentParser(description="Stage 29 Rust receiver/NIC gate")
    parser.add_argument("--bandwidth-mhz", type=int, choices=(100, 200), required=True)
    parser.add_argument("--mode", choices=("time_only", "spec_only", "time_spec"), required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8089")
    parser.add_argument("--interface", default="ens2f0np0")
    parser.add_argument("--seconds", type=float, default=60.0)
    parser.add_argument("--output")
    args = parser.parse_args()
    if args.bandwidth_mhz == 200 and args.mode == "time_spec":
        parser.error("Stage 29 rejects 200MHz TIME_SPEC")

    needs_time = args.mode in ("time_only", "time_spec")
    needs_spec = args.mode in ("spec_only", "time_spec")
    time_flows = 8 if needs_time else 0
    spec_flows = 16 if needs_spec else 0
    flow_count = time_flows + spec_flows
    pps_min = 470_000.0 if args.bandwidth_mhz == 100 else 950_000.0
    payload_min = 63_000.0 if args.bandwidth_mhz == 200 or args.mode == "time_spec" else 31_000.0
    base = args.base_url.rstrip("/")
    _post_config(base, args.bandwidth_mhz, args.mode)
    time.sleep(0.25)
    state_before = _fetch(base + "/api/state")
    stats_before = state_before.get("stats", {})
    net_before = _net(args.interface)
    eth_before = _ethtool(args.interface)
    time.sleep(max(float(args.seconds), 0.1))
    state_after = _fetch(base + "/api/state")
    stats_after = state_after.get("stats", {})
    net_after = _net(args.interface)
    eth_after = _ethtool(args.interface)
    elapsed = max(float(args.seconds), 0.1)

    time_packets = _delta(stats_after, stats_before, "time_packets")
    spec_packets = _delta(stats_after, stats_before, "spec_packets")
    rates = {
        "time_pps": time_packets / elapsed,
        "spec_pps": spec_packets / elapsed,
        "combined_t510_udp_payload_mbps": (time_packets + spec_packets) * 8320.0 * 8.0 / elapsed / 1_000_000.0,
    }
    errors: list[str] = []
    if int(stats_after.get("active_time_flow_count", -1)) != time_flows:
        errors.append("TIME_FLOW_COUNT_MISMATCH")
    if int(stats_after.get("active_spec_flow_count", -1)) != spec_flows:
        errors.append("SPEC_FLOW_COUNT_MISMATCH")
    if int(stats_after.get("active_flow_count", -1)) != flow_count:
        errors.append("FLOW_COUNT_MISMATCH")
    if int(stats_after.get("flow_count", -1)) != 24:
        errors.append("CAPTURE_FLOW_CAPACITY_MISMATCH")
    if int(stats_after.get("active_worker_count", 0)) < flow_count:
        errors.append("ACTIVE_WORKERS_LOW")
    if needs_time and rates["time_pps"] < pps_min:
        errors.append("TIME_PPS_LOW")
    if needs_spec and rates["spec_pps"] < pps_min:
        errors.append("SPEC_PPS_LOW")
    if not needs_time and time_packets:
        errors.append("TIME_PACKETS_IN_SPEC_ONLY")
    if not needs_spec and spec_packets:
        errors.append("SPEC_PACKETS_IN_TIME_ONLY")
    if rates["combined_t510_udp_payload_mbps"] < payload_min:
        errors.append("COMBINED_PAYLOAD_RATE_LOW")
    for key in (
        "parse_errors", "ring_drops", "worker_ring_drops", "kernel_drops", "app_drops",
        "seq_gaps", "frame_gaps", "sample0_gaps", "spec_seq_gaps", "spec_frame_gaps",
    ):
        if _delta(stats_after, stats_before, key) != 0:
            errors.append(f"NONZERO_{key.upper()}")
    before_flows = {int(item.get("flow_id", -1)): item for item in stats_before.get("per_flow", [])}
    after_flows = {int(item.get("flow_id", -1)): item for item in stats_after.get("per_flow", [])}
    active_flow_ids = list(range(8)) if needs_time else []
    if needs_spec:
        active_flow_ids.extend(range(8, 24))
    for flow_id in active_flow_ids:
        before_flow = before_flows.get(flow_id, {})
        after_flow = after_flows.get(flow_id)
        if after_flow is None:
            errors.append(f"FLOW_{flow_id}_MISSING")
            continue
        packet_key = "time_packets" if flow_id < 8 else "spec_packets"
        if _delta(after_flow, before_flow, packet_key) <= 0:
            errors.append(f"FLOW_{flow_id}_NO_PACKETS")
        for key in ("seq_gaps", "frame_gaps", "sample0_gaps", "spec_seq_gaps", "spec_frame_gaps"):
            if _delta(after_flow, before_flow, key) != 0:
                errors.append(f"FLOW_{flow_id}_{key.upper()}")
    for flow_id in sorted(set(range(24)).difference(active_flow_ids)):
        before_flow = before_flows.get(flow_id, {})
        after_flow = after_flows.get(flow_id, {})
        if _delta(after_flow, before_flow, "time_packets") or _delta(after_flow, before_flow, "spec_packets"):
            errors.append(f"FLOW_{flow_id}_INACTIVE_PACKETS")
    if needs_time and float(stats_after.get("display_update_hz", 0.0) or 0.0) < 1.0:
        errors.append("WAVEFORM_PREVIEW_NOT_LIVE")
    if needs_spec and float(stats_after.get("spectrum_update_hz", 0.0) or 0.0) < 1.0:
        errors.append("SPECTRUM_PREVIEW_NOT_LIVE")
    if needs_spec:
        preview = state_after.get("spec_preview", {})
        if not bool(preview.get("complete")) or int(preview.get("coverage_blocks", 0) or 0) < 16:
            errors.append("SPEC_PREVIEW_INCOMPLETE")

    net_delta = {key: int(net_after.get(key, 0)) - int(net_before.get(key, 0)) for key in set(net_before) | set(net_after)}
    for key in ("rx_dropped", "rx_errors", "rx_missed_errors", "rx_crc_errors"):
        if net_delta.get(key, 0) != 0:
            errors.append(f"NIC_{key.upper()}")
    eth_delta = {key: int(eth_after.get(key, 0)) - int(eth_before.get(key, 0)) for key in set(eth_before) | set(eth_after)}
    physical_discard = sum(
        max(0, value) for key, value in eth_delta.items()
        if re.search(r"rx.*(discard|drop|miss|error)|prio.*discard", key, re.IGNORECASE)
    )
    if physical_discard:
        errors.append("NIC_PHYSICAL_DISCARD")

    ok = not errors
    result = {
        "classification": f"HOST_STAGE29_{args.bandwidth_mhz}MHZ_{args.mode}_RUST_RX_{'PASS' if ok else 'FAIL'}",
        "ok": ok,
        "stage": 29,
        "bandwidth_mhz": args.bandwidth_mhz,
        "mode": args.mode,
        "seconds": elapsed,
        "required": {"time_flows": time_flows, "spec_flows": spec_flows, "pps_min": pps_min, "payload_mbps_min": payload_min},
        "rates": rates,
        "stats_before": stats_before,
        "stats_after": stats_after,
        "net_delta": {key: value for key, value in net_delta.items() if value},
        "ethtool_delta": {key: value for key, value in eth_delta.items() if value},
        "errors": errors,
    }
    output = Path(args.output) if args.output else _root() / "reports" / "board" / f"stage29_{args.bandwidth_mhz}mhz_{args.mode}_host.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
