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


def _post_config(base: str, sample_rate_msps: int, mode: str, center_mhz: float) -> None:
    body = {
        "sample_rate_msps": sample_rate_msps,
        "output_mode": mode,
        "center_mhz": center_mhz,
        "expected_mhz": center_mhz,
        "dac_mhz": center_mhz,
        "target_mhz_by_channel": [center_mhz] * 8,
    }
    request = urllib.request.Request(
        base.rstrip("/") + "/api/config",
        data=json.dumps(body).encode("utf-8"),
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


def _worker_capacity_errors(stats: dict[str, Any], active_flow_count: int) -> list[str]:
    """Validate the port-fanout workers used by the currently active flows.

    The receiver intentionally supports more UDP flows than workers.  Its BPF
    fanout maps destination ports modulo ``worker_count``, so 24 TIME_SPEC
    flows on the frozen 16-worker service should activate 16 workers.
    """
    worker_count = int(stats.get("worker_count", 0) or 0)
    active_worker_count = int(stats.get("active_worker_count", 0) or 0)
    if worker_count <= 0:
        return ["CAPTURE_WORKER_CAPACITY_INVALID"]
    expected_active_workers = min(active_flow_count, worker_count)
    if active_worker_count < expected_active_workers:
        return ["ACTIVE_WORKERS_LOW"]
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description="current T510 release Rust receiver/NIC gate")
    parser.add_argument("--sample-rate-msps", type=int, choices=(160, 320), required=True)
    parser.add_argument("--mode", choices=("time_only", "spec_only", "time_spec"), required=True)
    parser.add_argument("--center-mhz", type=float, default=200.0)
    parser.add_argument("--base-url", default="http://127.0.0.1:8089")
    parser.add_argument("--interface", default="ens2f0np0")
    parser.add_argument("--seconds", type=float, default=60.0)
    parser.add_argument("--output")
    parser.add_argument(
        "--skip-config",
        action="store_true",
        help="do not change receiver mode; use when it was prepared before scheduled start",
    )
    parser.add_argument(
        "--prepare-only",
        action="store_true",
        help="apply and verify receiver mode without running a traffic gate",
    )
    args = parser.parse_args()
    if args.sample_rate_msps == 320 and args.mode == "time_spec":
        parser.error("current T510 release rejects 320 MS/s TIME_SPEC")
    if args.prepare_only and args.skip_config:
        parser.error("--prepare-only and --skip-config are mutually exclusive")

    if args.prepare_only:
        _post_config(args.base_url, args.sample_rate_msps, args.mode, args.center_mhz)
        deadline = time.monotonic() + 5.0
        state: dict[str, Any] = {}
        while time.monotonic() < deadline:
            state = _fetch(args.base_url.rstrip("/") + "/api/state")
            config = state.get("config", {})
            if (
                int(config.get("sample_rate_msps", 0)) == args.sample_rate_msps
                and str(config.get("output_mode", "")) == args.mode
                and abs(float(config.get("center_mhz", 0.0)) - args.center_mhz) <= 1.0e-6
            ):
                result = {
                    "classification": "HOST_T510_RECEIVER_PREPARE_PASS",
                    "ok": True,
                    "sample_rate_msps": args.sample_rate_msps,
                    "mode": args.mode,
                    "center_mhz": args.center_mhz,
                    "config_generation": state.get("config_generation"),
                }
                print(json.dumps(result, indent=2, sort_keys=True))
                return 0
            time.sleep(0.05)
        raise RuntimeError(f"receiver did not apply requested configuration: {state}")

    needs_time = args.mode in ("time_only", "time_spec")
    needs_spec = args.mode in ("spec_only", "time_spec")
    time_flows = 8 if needs_time else 0
    spec_flows = 16 if needs_spec else 0
    flow_count = time_flows + spec_flows
    # Require at least 95% of the frozen nominal packet rate.  The measured
    # application data rate includes the 128-byte T510 header plus 8192-byte
    # payload; Ethernet framing overhead is checked independently by NIC stats.
    pps_min = 593_750.0 if args.sample_rate_msps == 160 else 1_187_500.0
    payload_min = (
        79_040.0
        if args.sample_rate_msps == 320 or args.mode == "time_spec"
        else 39_520.0
    )
    base = args.base_url.rstrip("/")
    if not args.skip_config:
        _post_config(base, args.sample_rate_msps, args.mode, args.center_mhz)
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
    errors.extend(_worker_capacity_errors(stats_after, flow_count))
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
    warnings: list[str] = []
    if needs_spec:
        preview = state_after.get("spec_preview", {})
        preview_blocks = int(preview.get("coverage_blocks", 0) or 0)
        preview_block_count = int(preview.get("block_count", 0) or 0)
        if preview_block_count != 16:
            errors.append(f"SPEC_PREVIEW_BLOCK_COUNT_{preview_block_count}")
        if preview.get("last_error"):
            errors.append("SPEC_PREVIEW_ERROR")
        # `spec_preview` describes the frame currently being assembled and is
        # reset as soon as the next frame starts.  At 320 MS/s an arbitrary
        # status read will therefore usually observe 1..15 blocks even though
        # complete spectra are publishing continuously.  spectrum_update_hz
        # increments only after all 16 blocks form one coherent spectrum, so
        # the >=1 Hz gate above is the persistent completion evidence.
        if not bool(preview.get("complete")) or preview_blocks < 16:
            warnings.append(
                "SPEC_PREVIEW_SNAPSHOT_IN_PROGRESS="
                f"{preview_blocks}/{preview_block_count}"
            )

    net_delta = {key: int(net_after.get(key, 0)) - int(net_before.get(key, 0)) for key in set(net_before) | set(net_after)}
    for key in ("rx_dropped", "rx_errors", "rx_missed_errors", "rx_crc_errors"):
        if net_delta.get(key, 0) != 0:
            errors.append(f"NIC_{key.upper()}")
    eth_delta = {key: int(eth_after.get(key, 0)) - int(eth_before.get(key, 0)) for key in set(eth_before) | set(eth_after)}
    # The dedicated T510 NIC installs an exact 4300..4323 ntuple whitelist.
    # mlx5 rx_steer_missed_packets therefore also counts unrelated background
    # frames intentionally rejected for not matching that table.  Keep the
    # value as evidence, but rely on per-flow T510 continuity plus the actual
    # ring/kernel/app and physical error counters for the science-loss gate.
    steer_missed = max(0, eth_delta.get("rx_steer_missed_packets", 0))
    physical_discard = sum(
        max(0, value) for key, value in eth_delta.items()
        if key != "rx_steer_missed_packets"
        and re.search(r"rx.*(discard|drop|miss|error)|prio.*discard", key, re.IGNORECASE)
    )
    if physical_discard:
        errors.append("NIC_PHYSICAL_DISCARD")
    if steer_missed:
        warnings.append(
            f"NIC_RX_STEER_MISSED_OUTSIDE_T510_WHITELIST={steer_missed}"
        )

    ok = not errors
    result = {
        "classification": f"HOST_T510_{args.sample_rate_msps}MSPS_{args.mode}_RUST_RX_{'PASS' if ok else 'FAIL'}",
        "ok": ok,
        "release": "latest",
        "sample_rate_msps": args.sample_rate_msps,
        "mode": args.mode,
        "center_mhz": args.center_mhz,
        "seconds": elapsed,
        "required": {
            "time_flows": time_flows,
            "spec_flows": spec_flows,
            "active_workers": min(
                flow_count, int(stats_after.get("worker_count", 0) or 0)
            ),
            "pps_min": pps_min,
            "payload_mbps_min": payload_min,
        },
        "rates": rates,
        "stats_before": stats_before,
        "stats_after": stats_after,
        "spec_preview": state_after.get("spec_preview", {}),
        "net_delta": {key: value for key, value in net_delta.items() if value},
        "ethtool_delta": {key: value for key, value in eth_delta.items() if value},
        "warnings": warnings,
        "errors": errors,
    }
    output = (
        Path(args.output)
        if args.output
        else _root() / "build" / "receiver" / "latest" / "evidence" / "host_validation.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
