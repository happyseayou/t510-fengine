#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
import urllib.request
from pathlib import Path
from typing import Any


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


def _post_config(base_url: str, bandwidth_mhz: int, timeout: float) -> None:
    url = base_url.rstrip("/") + "/api/config"
    payload = json.dumps({"bandwidth_mhz": int(bandwidth_mhz)}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        response.read()


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
        if match:
            out[match.group(1).strip()] = int(match.group(2))
    return out


def _delta(after: dict[str, int], before: dict[str, int]) -> dict[str, int]:
    return {
        key: int(after.get(key, 0)) - int(before.get(key, 0))
        for key in sorted(set(before) | set(after))
        if int(after.get(key, 0)) - int(before.get(key, 0)) != 0
    }


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


def _counter_delta(after: dict[str, Any], before: dict[str, Any], name: str) -> int:
    return int(after.get(name, 0)) - int(before.get(name, 0))


def _flows_by_id(stats: dict[str, Any]) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for flow in stats.get("per_flow", []):
        if isinstance(flow, dict):
            out[int(flow.get("flow_id", -1))] = flow
    return out


def _flow_delta(after: dict[str, Any], before: dict[str, Any], flow_id: int, name: str) -> int:
    before_flow = _flows_by_id(before).get(flow_id, {})
    after_flow = _flows_by_id(after).get(flow_id, {})
    return int(after_flow.get(name, 0)) - int(before_flow.get(name, 0))


def _per_flow_gap_delta(after: dict[str, Any], before: dict[str, Any], name: str) -> int:
    before_by_flow = _flows_by_id(before)
    total = 0
    for flow_id, after_flow in _flows_by_id(after).items():
        total += int(after_flow.get(name, 0)) - int(before_by_flow.get(flow_id, {}).get(name, 0))
    return total


def _mode_key(value: str) -> str:
    key = str(value).strip().lower().replace("-", "_")
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


def _needs_time(mode: str) -> bool:
    return mode in ("time_only", "time_spec")


def _needs_spec(mode: str) -> bool:
    return mode in ("spec_only", "time_spec")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Stage 27e/27f Rust TIME/SPEC receiver state.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8089")
    parser.add_argument("--url", help="Full /api/state URL; overrides --base-url")
    parser.add_argument("--interface", default="ens2f0np0")
    parser.add_argument("--mode", type=_mode_key, default="time_spec")
    parser.add_argument("--bandwidth-mhz", type=int, choices=(20, 100, 200), required=True)
    parser.add_argument("--seconds", type=float, default=8.0)
    parser.add_argument("--poll-interval", type=float, default=0.5)
    parser.add_argument(
        "--collect-samples",
        action="store_true",
        help="Fetch and store intermediate /api/state samples. Disabled by default because full state polling can perturb 60Gbps+ receive.",
    )
    parser.add_argument("--time-flow-count", type=int, default=8)
    parser.add_argument("--spec-flow-count", type=int, default=8)
    parser.add_argument("--expected-flow-count", type=int)
    parser.add_argument("--expected-spec-layout")
    parser.add_argument("--expected-spec-chan-count", type=int)
    parser.add_argument("--stage-label", default="27e")
    parser.add_argument("--min-flow-packets", type=int, default=1)
    parser.add_argument("--min-time-pps", type=float, default=1.0)
    parser.add_argument("--min-spec-pps", type=float, default=1.0)
    parser.add_argument("--min-combined-t510-udp-payload-mbps", type=float, default=0.0)
    parser.add_argument("--min-active-workers", type=int)
    parser.add_argument("--require-waveform", action="store_true")
    parser.add_argument("--require-spectrum", action="store_true")
    parser.add_argument("--min-display-hz", type=float, default=1.0)
    parser.add_argument("--min-spectrum-hz", type=float, default=1.0)
    parser.add_argument("--no-post-config", action="store_true")
    parser.add_argument("--output")
    args = parser.parse_args()

    mode = str(args.mode)
    stage_label = str(args.stage_label).strip().lower().replace("stage", "")
    stage_upper = stage_label.upper()
    pass_classification = f"HOST_STAGE{stage_upper}_RUST_RX_PASS"
    if mode == "time_spec" and int(args.bandwidth_mhz) == 200:
        raise SystemExit(f"Stage {stage_label} rejects TIME_SPEC at 200MHz; validate board-side reject instead")

    base_url = args.base_url.rstrip("/")
    state_url = args.url or f"{base_url}/api/state"
    default_output = (
        _repo_root()
        / "reports"
        / "board"
        / f"stage{stage_label}_rust_rx_{mode}_{args.bandwidth_mhz}mhz.json"
    )
    output_path = args.output or str(default_output)

    if not args.no_post_config:
        _post_config(base_url, args.bandwidth_mhz, timeout=2.0)
        time.sleep(0.25)

    kernel_before = _kernel_counters(args.interface)
    ethtool_before = _ethtool_stats(args.interface)
    state_before = _fetch_json(state_url, timeout=2.0)
    stats_before = _state_stats(state_before)

    samples: list[dict[str, Any]] = []
    deadline = time.monotonic() + max(float(args.seconds), 0.1)
    while time.monotonic() < deadline:
        sleep_s = min(max(float(args.poll_interval), 0.05), max(deadline - time.monotonic(), 0.05))
        time.sleep(sleep_s)
        if args.collect_samples:
            try:
                state = _fetch_json(state_url, timeout=2.0)
                samples.append(_state_stats(state))
            except Exception as exc:  # noqa: BLE001 - command-line diagnostic payload
                samples.append({"sample_error": f"{type(exc).__name__}: {exc}"})

    kernel_after = _kernel_counters(args.interface)
    ethtool_after = _ethtool_stats(args.interface)
    state_after = _fetch_json(state_url, timeout=2.0)
    stats_after = _state_stats(state_after)
    kernel_delta = _delta(kernel_after, kernel_before)
    ethtool_delta = _delta(ethtool_after, ethtool_before)

    time_packet_delta = _counter_delta(stats_after, stats_before, "time_packets")
    spec_packet_delta = _counter_delta(stats_after, stats_before, "spec_packets")
    parse_errors_delta = _counter_delta(stats_after, stats_before, "parse_errors")
    ring_drops_delta = _counter_delta(stats_after, stats_before, "ring_drops")
    worker_ring_drops_delta = _counter_delta(stats_after, stats_before, "worker_ring_drops")
    kernel_drops_delta = _counter_delta(stats_after, stats_before, "kernel_drops")
    app_drops_delta = _counter_delta(stats_after, stats_before, "app_drops")
    seq_gaps_delta = _counter_delta(stats_after, stats_before, "seq_gaps")
    frame_gaps_delta = _counter_delta(stats_after, stats_before, "frame_gaps")
    sample0_gaps_delta = _counter_delta(stats_after, stats_before, "sample0_gaps")
    spec_seq_gaps_delta = _counter_delta(stats_after, stats_before, "spec_seq_gaps")
    spec_frame_gaps_delta = _counter_delta(stats_after, stats_before, "spec_frame_gaps")
    waveform_updates_delta = _counter_delta(stats_after, stats_before, "waveform_updates")
    spectrum_updates_delta = _counter_delta(stats_after, stats_before, "spectrum_updates")
    per_flow_seq_gaps_delta = _per_flow_gap_delta(stats_after, stats_before, "seq_gaps")
    per_flow_frame_gaps_delta = _per_flow_gap_delta(stats_after, stats_before, "frame_gaps")
    per_flow_sample0_gaps_delta = _per_flow_gap_delta(stats_after, stats_before, "sample0_gaps")
    per_flow_spec_seq_gaps_delta = _per_flow_gap_delta(stats_after, stats_before, "spec_seq_gaps")
    per_flow_spec_frame_gaps_delta = _per_flow_gap_delta(stats_after, stats_before, "spec_frame_gaps")

    time_flow_count = int(args.time_flow_count)
    spec_flow_count = int(args.spec_flow_count)
    time_flow_ids = list(range(0, time_flow_count))
    spec_flow_ids = list(range(time_flow_count, time_flow_count + spec_flow_count))
    missing_time_flows = [
        flow_id
        for flow_id in time_flow_ids
        if _flow_delta(stats_after, stats_before, flow_id, "time_packets") < int(args.min_flow_packets)
    ]
    missing_spec_flows = [
        flow_id
        for flow_id in spec_flow_ids
        if _flow_delta(stats_after, stats_before, flow_id, "spec_packets") < int(args.min_flow_packets)
    ]

    # Linux netdev rx_dropped on mlx5 can include driver accounting such as
    # MPWQE filler/drop-to-stack effects even when AF_PACKET/fanout sees a
    # complete no-gap stream. Keep it in the report, but gate production on
    # AF_PACKET drops, sequence/frame gaps, and explicit NIC drop/error
    # counters. Ethtool rx_*discard counters are hard failures because they
    # mean the NIC/driver discarded received packets before the application
    # could account for a complete no-gap flow.
    netdev_rx_dropped_delta = int(kernel_delta.get("rx_dropped", 0))
    nic_error_delta = 0
    nic_error_delta += int(kernel_delta.get("rx_errors", 0))
    nic_error_delta += int(kernel_delta.get("rx_missed_errors", 0))
    nic_error_delta += int(kernel_delta.get("rx_crc_errors", 0))
    nic_error_delta += _sum_named_delta(
        ethtool_delta,
        (
            r"rx.*drop",
            r"rx.*discard",
            r"rx.*miss",
            r"rx.*error",
            r"rx.*crc",
            r"rx.*symbol",
            r"rx.*buffer",
        ),
    )

    backend = str(stats_after.get("backend", ""))
    fanout_mode = str(stats_after.get("fanout_mode", ""))
    active_worker_count = int(stats_after.get("active_worker_count", 0))
    auto_active_workers = (time_flow_count if _needs_time(mode) else 0) + (spec_flow_count if _needs_spec(mode) else 0)
    min_active_workers = int(args.min_active_workers) if args.min_active_workers is not None else auto_active_workers
    rx_time_pps = float(stats_after.get("rx_processed_packets_per_sec", 0.0))
    rx_spec_pps = float(stats_after.get("spec_processed_packets_per_sec", 0.0))
    time_mbps = float(stats_after.get("rx_processed_gbps", 0.0)) * 1000.0
    spec_mbps = float(stats_after.get("spec_processed_gbps", 0.0)) * 1000.0
    combined_t510_udp_payload_mbps = time_mbps + spec_mbps
    selected_mhz = stats_after.get("selected_bandwidth_mhz")
    detected_mhz = stats_after.get("detected_bandwidth_mhz")
    mismatch = bool(stats_after.get("selected_detected_mismatch", False))
    display_hz = float(stats_after.get("display_update_hz", 0.0))
    spectrum_hz = float(stats_after.get("spectrum_update_hz", 0.0))

    errors: list[str] = []
    if backend != "fanout":
        errors.append(f"BACKEND_NOT_FANOUT backend={backend!r}")
    if fanout_mode != "port":
        errors.append(f"FANOUT_MODE_NOT_PORT fanout_mode={fanout_mode!r}")
    if args.expected_flow_count is not None and int(stats_after.get("flow_count", 0)) != int(args.expected_flow_count):
        errors.append(f"FLOW_COUNT_MISMATCH flow_count={stats_after.get('flow_count')} expected={args.expected_flow_count}")
    if args.expected_spec_layout is not None:
        actual_layout = str(stats_after.get("spec_layout", ""))
        if actual_layout != str(args.expected_spec_layout):
            errors.append(f"SPEC_LAYOUT_MISMATCH spec_layout={actual_layout!r} expected={args.expected_spec_layout!r}")
    if active_worker_count < min_active_workers:
        errors.append(f"ACTIVE_WORKERS_LOW active={active_worker_count} required={min_active_workers}")
    if int(selected_mhz or 0) != int(args.bandwidth_mhz):
        errors.append(f"SELECTED_BANDWIDTH_MISMATCH selected={selected_mhz} expected={args.bandwidth_mhz}")
    if _needs_time(mode):
        if detected_mhz is None:
            errors.append("DETECTED_BANDWIDTH_UNKNOWN")
        elif int(detected_mhz) != int(args.bandwidth_mhz):
            errors.append(f"DETECTED_BANDWIDTH_MISMATCH detected={detected_mhz} expected={args.bandwidth_mhz}")
        if mismatch:
            errors.append("SELECTED_DETECTED_MISMATCH")
        if time_packet_delta < int(args.min_flow_packets):
            errors.append(f"TIME_PACKET_COUNTER_NOT_INCREMENTING delta={time_packet_delta}")
        if rx_time_pps < float(args.min_time_pps):
            errors.append(f"TIME_PPS_LOW {rx_time_pps:.3f} < {float(args.min_time_pps):.3f}")
        if missing_time_flows:
            errors.append(f"TIME_FLOW_MISSING_PACKETS flow_ids={missing_time_flows}")
    if _needs_spec(mode):
        if spec_packet_delta < int(args.min_flow_packets):
            errors.append(f"SPEC_PACKET_COUNTER_NOT_INCREMENTING delta={spec_packet_delta}")
        if rx_spec_pps < float(args.min_spec_pps):
            errors.append(f"SPEC_PPS_LOW {rx_spec_pps:.3f} < {float(args.min_spec_pps):.3f}")
        if missing_spec_flows:
            errors.append(f"SPEC_FLOW_MISSING_PACKETS flow_ids={missing_spec_flows}")
        if stats_after.get("last_spec_chan0") is None:
            errors.append("SPEC_LAST_CHAN0_MISSING")
        if int(stats_after.get("last_spec_chan_count") or 0) <= 0:
            errors.append("SPEC_LAST_CHAN_COUNT_MISSING")
        if args.expected_spec_chan_count is not None and int(stats_after.get("last_spec_chan_count") or 0) != int(args.expected_spec_chan_count):
            errors.append(
                f"SPEC_CHAN_COUNT_MISMATCH chan_count={stats_after.get('last_spec_chan_count')} "
                f"expected={args.expected_spec_chan_count}"
            )
    if combined_t510_udp_payload_mbps < float(args.min_combined_t510_udp_payload_mbps):
        errors.append(
            "COMBINED_T510_UDP_PAYLOAD_LOW "
            f"{combined_t510_udp_payload_mbps:.3f} < {float(args.min_combined_t510_udp_payload_mbps):.3f}"
        )
    if parse_errors_delta:
        errors.append(f"PARSE_ERRORS delta={parse_errors_delta}")
    if ring_drops_delta or worker_ring_drops_delta or kernel_drops_delta or app_drops_delta:
        errors.append(
            "RING_OR_KERNEL_DROPS "
            f"ring={ring_drops_delta} worker_ring={worker_ring_drops_delta} "
            f"kernel={kernel_drops_delta} app={app_drops_delta}"
        )
    if nic_error_delta:
        errors.append(f"NIC_DROP_OR_ERROR_COUNTERS delta_sum={nic_error_delta}")
    if seq_gaps_delta or frame_gaps_delta or sample0_gaps_delta:
        errors.append(f"TIME_GAPS seq={seq_gaps_delta} frame={frame_gaps_delta} sample0={sample0_gaps_delta}")
    if per_flow_seq_gaps_delta or per_flow_frame_gaps_delta or per_flow_sample0_gaps_delta:
        errors.append(
            "PER_FLOW_TIME_GAPS "
            f"seq={per_flow_seq_gaps_delta} frame={per_flow_frame_gaps_delta} sample0={per_flow_sample0_gaps_delta}"
        )
    if spec_seq_gaps_delta or spec_frame_gaps_delta:
        errors.append(f"SPEC_GAPS seq={spec_seq_gaps_delta} frame={spec_frame_gaps_delta}")
    if per_flow_spec_seq_gaps_delta or per_flow_spec_frame_gaps_delta:
        errors.append(
            "PER_FLOW_SPEC_GAPS "
            f"seq={per_flow_spec_seq_gaps_delta} frame={per_flow_spec_frame_gaps_delta}"
        )
    if args.require_waveform and (waveform_updates_delta <= 0 or display_hz < float(args.min_display_hz)):
        errors.append(
            f"WAVEFORM_PREVIEW_LOW updates={waveform_updates_delta} hz={display_hz:.3f} "
            f"required_hz={float(args.min_display_hz):.3f}"
        )
    if args.require_spectrum and (spectrum_updates_delta <= 0 or spectrum_hz < float(args.min_spectrum_hz)):
        errors.append(
            f"SPECTRUM_PREVIEW_LOW updates={spectrum_updates_delta} hz={spectrum_hz:.3f} "
            f"required_hz={float(args.min_spectrum_hz):.3f}"
        )

    if backend != "fanout" or fanout_mode != "port" or active_worker_count < min_active_workers:
        classification = f"BLOCK_STAGE{stage_upper}_FANOUT_NOT_DISTRIBUTING"
    elif nic_error_delta or ring_drops_delta or worker_ring_drops_delta or kernel_drops_delta or app_drops_delta:
        classification = f"BLOCK_STAGE{stage_upper}_NIC_DROP_ERROR"
    elif (
        seq_gaps_delta
        or frame_gaps_delta
        or sample0_gaps_delta
        or spec_seq_gaps_delta
        or spec_frame_gaps_delta
        or per_flow_seq_gaps_delta
        or per_flow_frame_gaps_delta
        or per_flow_sample0_gaps_delta
        or per_flow_spec_seq_gaps_delta
        or per_flow_spec_frame_gaps_delta
    ):
        classification = f"BLOCK_STAGE{stage_upper}_HOST_RX_GAPS"
    elif errors:
        classification = f"HOST_STAGE{stage_upper}_RUST_RX_FAIL"
    else:
        classification = pass_classification

    result = {
        "classification": classification,
        "ok": classification == pass_classification,
        "stage_label": f"stage{stage_label}",
        "mode": mode.upper(),
        "bandwidth_mhz": int(args.bandwidth_mhz),
        "backend": backend,
        "fanout_mode": fanout_mode,
        "active_worker_count": active_worker_count,
        "min_active_workers": min_active_workers,
        "expected_flow_count": args.expected_flow_count,
        "expected_spec_layout": args.expected_spec_layout,
        "expected_spec_chan_count": args.expected_spec_chan_count,
        "time_packet_delta": time_packet_delta,
        "spec_packet_delta": spec_packet_delta,
        "rx_time_packets_per_sec": rx_time_pps,
        "rx_spec_packets_per_sec": rx_spec_pps,
        "combined_t510_udp_payload_mbps": combined_t510_udp_payload_mbps,
        "min_combined_t510_udp_payload_mbps": float(args.min_combined_t510_udp_payload_mbps),
        "selected_bandwidth_mhz": selected_mhz,
        "detected_bandwidth_mhz": detected_mhz,
        "time_flow_ids": time_flow_ids,
        "spec_flow_ids": spec_flow_ids,
        "missing_time_flows": missing_time_flows if _needs_time(mode) else [],
        "missing_spec_flows": missing_spec_flows if _needs_spec(mode) else [],
        "time_gaps_delta": {
            "seq": seq_gaps_delta,
            "frame": frame_gaps_delta,
            "sample0": sample0_gaps_delta,
            "per_flow_seq": per_flow_seq_gaps_delta,
            "per_flow_frame": per_flow_frame_gaps_delta,
            "per_flow_sample0": per_flow_sample0_gaps_delta,
        },
        "spec_gaps_delta": {
            "seq": spec_seq_gaps_delta,
            "frame": spec_frame_gaps_delta,
            "per_flow_seq": per_flow_spec_seq_gaps_delta,
            "per_flow_frame": per_flow_spec_frame_gaps_delta,
        },
        "drop_error_delta": {
            "parse_errors": parse_errors_delta,
            "ring_drops": ring_drops_delta,
            "worker_ring_drops": worker_ring_drops_delta,
            "kernel_drops": kernel_drops_delta,
            "app_drops": app_drops_delta,
            "nic_error_delta_sum": nic_error_delta,
            "netdev_rx_dropped_advisory": netdev_rx_dropped_delta,
        },
        "preview_delta": {
            "waveform_updates": waveform_updates_delta,
            "spectrum_updates": spectrum_updates_delta,
            "display_update_hz": display_hz,
            "spectrum_update_hz": spectrum_hz,
        },
        "kernel_delta": kernel_delta,
        "ethtool_delta": ethtool_delta,
        "stats_before": stats_before,
        "stats_after": stats_after,
        "samples": samples,
        "errors": errors,
        "result": "PASS" if classification == pass_classification else "BLOCK" if classification.startswith("BLOCK_") else "FAIL",
    }
    print(json.dumps(_jsonable(result), indent=2, sort_keys=True))
    _write_output(output_path, result)
    return 0 if result["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
