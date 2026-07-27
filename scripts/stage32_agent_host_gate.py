#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.request
from typing import Any


def _http_json(url: str, *, body: dict[str, Any] | None = None, timeout: float = 30.0) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=None if body is None else json.dumps(body).encode("utf-8"),
        headers={} if body is None else {"Content-Type": "application/json"},
        method="GET" if body is None else "POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            value = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} from {url}: {payload}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"non-object JSON from {url}")
    return value


def _result(value: dict[str, Any]) -> dict[str, Any]:
    result = value.get("result")
    if not isinstance(result, dict):
        raise RuntimeError(f"Agent response has no result object: {value}")
    return result


def _counter_delta(after: dict[str, Any], before: dict[str, Any], key: str) -> int:
    return int(after.get(key, 0) or 0) - int(before.get(key, 0) or 0)


def _qsfp_physical_health(qsfp: dict[str, Any]) -> dict[str, Any]:
    """Decode stable physical CMAC health without using AXIS TREADY.

    The current bitstream's `link_up` includes `tx_axis_tready_raw`.  TREADY
    may legally be low for pause/backpressure at the exact status sample, so
    it is not a persistent physical-link condition.
    """
    raw = int(qsfp.get("raw_flags", 0) or 0)
    required_bits = {
        "cmac_reset_done": 2,
        "gt_locked": 3,
        "module_present": 12,
        "gt_refclk_seen": 13,
        "gt_tx_reset_done": 14,
        "gt_rx_reset_done": 15,
        "rx_aligned": 18,
        "rx_status": 19,
    }
    fault_bits = {
        "local_fault": 5,
        "remote_fault": 6,
        "tx_overflow": 17,
        "rx_local_fault": 20,
        "rx_internal_local_fault": 21,
        "tx_local_fault_detail": 22,
    }
    required = {name: bool((raw >> bit) & 0x1) for name, bit in required_bits.items()}
    faults = {name: bool((raw >> bit) & 0x1) for name, bit in fault_bits.items()}
    return {
        "physical_healthy": bool(all(required.values()) and not any(faults.values())),
        "link_up_sample": bool(qsfp.get("link_up", False)),
        "tx_ready_sample": bool((raw >> 4) & 0x1),
        "raw_flags": raw,
        "required": required,
        "faults": faults,
    }


def _compact_board(value: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value.get(key)
        for key in (
            "captured_at_unix_ms",
            "core_version",
            "board_id",
            "streaming",
            "error_flags",
            "profile",
            "clock",
            "mts",
            "halfband",
            "channelizer",
            "qsfp",
            "pipeline",
            "counters",
            "sample0",
            "timing",
        )
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Stage 32 simultaneous board/host UDP gate")
    parser.add_argument("--bandwidth-mhz", type=int, choices=(160, 320), required=True)
    parser.add_argument("--mode", choices=("time_only", "spec_only", "time_spec"), required=True)
    parser.add_argument("--seconds", type=float, default=60.0)
    parser.add_argument("--board-id", type=int, default=1)
    parser.add_argument("--agent-base", default="http://192.168.100.117:8010")
    parser.add_argument("--receiver-ssh", default="astrolab@192.168.100.162")
    parser.add_argument("--receiver-base-url", default="http://127.0.0.1:8089")
    parser.add_argument("--receiver-interface", default="enp1s0f0np0")
    parser.add_argument(
        "--remote-validator",
        default="/home/astrolab/.cache/t510-stage32/stage29_host_validate.py",
    )
    parser.add_argument(
        "--remote-output",
        default="/home/astrolab/.cache/t510-stage32/stage32_host_gate.json",
    )
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.bandwidth_mhz == 320 and args.mode == "time_spec":
        parser.error("Stage 32 rejects 320 MS/s TIME_SPEC")

    base = args.agent_base.rstrip("/")
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    evidence: dict[str, Any] = {
        "classification": (
            f"STAGE32_{args.bandwidth_mhz}MSPS_{args.mode.upper()}_BOARD_HOST_IN_PROGRESS"
        ),
        "ok": False,
        "stage": 32,
        "bandwidth_mhz": args.bandwidth_mhz,
        "mode": args.mode,
        "seconds": max(float(args.seconds), 0.1),
        "agent_base": base,
        "receiver": {
            "ssh": args.receiver_ssh,
            "base_url": args.receiver_base_url,
            "interface": args.receiver_interface,
        },
        "warnings": [],
        "errors": [],
    }
    started = False
    try:
        idle = _result(_http_json(base + "/api/v1/status", timeout=30.0))
        profile = idle.get("profile", {})
        if int(profile.get("bandwidth_mhz", 0)) != args.bandwidth_mhz:
            raise RuntimeError(f"board bandwidth mismatch before START: {profile}")
        if str(profile.get("mode")) != args.mode:
            raise RuntimeError(f"board mode mismatch before START: {profile}")
        evidence["board_idle"] = _compact_board(idle)

        _result(
            _http_json(
                base + "/api/v1/start",
                body={"expected_board_id": args.board_id},
                timeout=30.0,
            )
        )
        started = True
        time.sleep(1.0)
        board_before = _result(_http_json(base + "/api/v1/status", timeout=30.0))
        evidence["board_before"] = _compact_board(board_before)

        command = [
            "ssh",
            "-o",
            "BatchMode=yes",
            args.receiver_ssh,
            "python3",
            args.remote_validator,
            "--bandwidth-mhz",
            str(args.bandwidth_mhz),
            "--mode",
            args.mode,
            "--base-url",
            args.receiver_base_url,
            "--interface",
            args.receiver_interface,
            "--seconds",
            str(max(float(args.seconds), 0.1)),
            "--output",
            args.remote_output,
        ]
        host_process = subprocess.run(command, text=True, capture_output=True, check=False)
        evidence["host_validator"] = {
            "returncode": host_process.returncode,
            "stderr": host_process.stderr,
        }
        host_json = subprocess.run(
            [
                "ssh",
                "-o",
                "BatchMode=yes",
                args.receiver_ssh,
                "cat",
                args.remote_output,
            ],
            text=True,
            capture_output=True,
            check=True,
        )
        host = json.loads(host_json.stdout)
        host_output = output.with_name(output.stem + "_host.json")
        host_output.write_text(
            json.dumps(host, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        host_before = host.get("stats_before", {})
        host_after = host.get("stats_after", {})
        evidence["host_evidence"] = str(host_output)
        evidence["host"] = {
            key: host.get(key)
            for key in (
                "classification",
                "ok",
                "errors",
                "warnings",
                "required",
                "rates",
                "net_delta",
                "ethtool_delta",
            )
        }
        evidence["host"]["counter_delta"] = {
            key: _counter_delta(host_after, host_before, key)
            for key in (
                "time_packets",
                "spec_packets",
                "parse_errors",
                "kernel_drops",
                "ring_drops",
                "worker_ring_drops",
                "app_drops",
                "seq_gaps",
                "frame_gaps",
                "sample0_gaps",
                "spec_seq_gaps",
                "spec_frame_gaps",
            )
        }

        board_after = _result(_http_json(base + "/api/v1/status", timeout=30.0))
        evidence["board_after"] = _compact_board(board_after)
        before_counters = board_before.get("counters", {})
        after_counters = board_after.get("counters", {})
        board_delta = {
            key: _counter_delta(after_counters, before_counters, key)
            for key in sorted(set(before_counters) | set(after_counters))
        }
        evidence["board_counter_delta"] = board_delta
        before_channelizer = board_before.get("channelizer", {})
        after_channelizer = board_after.get("channelizer", {})
        channelizer_delta = {
            key: _counter_delta(after_channelizer, before_channelizer, key)
            for key in (
                "frame_count",
                "overflow_count",
                "data_halt_count",
                "xfft_event_count",
                "tile_overflow_count",
                "xfft_tlast_unexpected_count",
                "xfft_tlast_missing_count",
                "xfft_fft_overflow_count",
                "xfft_data_out_halt_count",
                "xfft_status_halt_count",
                "capture_backpressure_count",
                "frame_sample0_overflow_count",
                "coefficient_error_count",
            )
        }
        evidence["channelizer_counter_delta"] = channelizer_delta

        errors: list[str] = []
        warnings: list[str] = []
        if not bool(board_before.get("streaming")) or not bool(board_after.get("streaming")):
            errors.append("BOARD_NOT_STREAMING")
        if not bool(board_after.get("pipeline", {}).get("stream_accepting")):
            errors.append("BOARD_PIPELINE_NOT_ACCEPTING")
        qsfp_health = {
            "before": _qsfp_physical_health(board_before.get("qsfp", {})),
            "after": _qsfp_physical_health(board_after.get("qsfp", {})),
        }
        evidence["qsfp_health"] = qsfp_health
        if not bool(qsfp_health["before"]["physical_healthy"]):
            errors.append("BOARD_QSFP_PHYSICAL_HEALTH_BAD_BEFORE")
        if not bool(qsfp_health["after"]["physical_healthy"]):
            errors.append("BOARD_QSFP_PHYSICAL_HEALTH_BAD_AFTER")
        for label in ("before", "after"):
            health = qsfp_health[label]
            if bool(health["physical_healthy"]) and not bool(health["link_up_sample"]):
                warnings.append(
                    f"BOARD_QSFP_LINK_SAMPLE_LOW_DURING_BACKPRESSURE_{label.upper()}"
                )
        halfband = board_after.get("halfband", {})
        if str(halfband.get("coefficient_id", "")).lower() != "0xaa160055":
            errors.append("BOARD_HALFBAND_COEFFICIENT_ID_MISMATCH")
        if int(halfband.get("taps", 0) or 0) != 55:
            errors.append("BOARD_HALFBAND_TAP_COUNT_MISMATCH")
        if args.bandwidth_mhz == 160:
            if not bool(halfband.get("active")):
                errors.append("BOARD_HALFBAND_NOT_ACTIVE_AT_160MSPS")
            if not bool(halfband.get("primed")):
                errors.append("BOARD_HALFBAND_NOT_PRIMED_AT_160MSPS")
        elif bool(halfband.get("active")):
            errors.append("BOARD_HALFBAND_ACTIVE_AT_320MSPS")
        needs_spec = args.mode in ("spec_only", "time_spec")
        if needs_spec:
            if int(after_channelizer.get("nchan", 0) or 0) != 4096:
                errors.append("BOARD_PFB_NCHAN_NOT_4096")
            if int(after_channelizer.get("taps", 0) or 0) != 4:
                errors.append("BOARD_PFB_TAPS_NOT_4")
            if int(after_channelizer.get("packet_chan_count", 0) or 0) != 256:
                errors.append("BOARD_SPEC_PACKET_CHAN_COUNT_NOT_256")
            if int(after_channelizer.get("packet_time_count", 0) or 0) != 1:
                errors.append("BOARD_SPEC_PACKET_TIME_COUNT_NOT_1")
            if channelizer_delta.get("frame_count", 0) <= 0:
                errors.append("BOARD_PFB_FRAME_COUNT_NOT_ADVANCING")
            for key in (
                "overflow_count",
                "data_halt_count",
                "xfft_event_count",
                "tile_overflow_count",
                "xfft_tlast_unexpected_count",
                "xfft_tlast_missing_count",
                "xfft_fft_overflow_count",
                "xfft_data_out_halt_count",
                "xfft_status_halt_count",
                "capture_backpressure_count",
                "frame_sample0_overflow_count",
                "coefficient_error_count",
            ):
                if int(before_channelizer.get(key, 0) or 0) != 0:
                    errors.append(f"BOARD_NONZERO_INITIAL_PFB_{key.upper()}")
                if channelizer_delta.get(key, 0) != 0:
                    errors.append(f"BOARD_NONZERO_PFB_{key.upper()}_DELTA")
        active_packet_key = "time_packets" if args.mode in ("time_only", "time_spec") else "spec_packets"
        if board_delta.get(active_packet_key, 0) <= 0:
            errors.append(f"BOARD_{active_packet_key.upper()}_NOT_ADVANCING")
        if args.mode == "time_only" and board_delta.get("spec_packets", 0) != 0:
            errors.append("BOARD_SPEC_PACKETS_IN_TIME_ONLY")
        if args.mode == "spec_only" and board_delta.get("time_packets", 0) != 0:
            errors.append("BOARD_TIME_PACKETS_IN_SPEC_ONLY")
        for key in (
            "time_dropped",
            "spec_dropped",
            "tx_frames_dropped",
            "tx_route_error",
            "tx_route_miss",
            "rfdc_dropped",
            "science_dropped_beats",
        ):
            if board_delta.get(key, 0) != 0:
                errors.append(f"BOARD_NONZERO_{key.upper()}_DELTA")
        if host_process.returncode != 0 or not bool(host.get("ok")):
            errors.append("HOST_GATE_FAILED")
        evidence["warnings"] = warnings
        evidence["errors"] = errors
        evidence["ok"] = not errors
        evidence["classification"] = (
            f"STAGE32_{args.bandwidth_mhz}MSPS_{args.mode.upper()}_BOARD_HOST_"
            f"{'PASS' if evidence['ok'] else 'FAIL'}"
        )
    except Exception as exc:
        evidence["errors"].append(f"{type(exc).__name__}: {exc}")
    finally:
        if started:
            try:
                stop = _result(
                    _http_json(
                        base + "/api/v1/stop",
                        body={"reason": "stage32_agent_host_gate_complete"},
                        timeout=30.0,
                    )
                )
                evidence["stop"] = {
                    "stopped": stop.get("stopped"),
                    "snapshot": _compact_board(stop.get("snapshot", {})),
                }
            except Exception as exc:
                evidence["errors"].append(f"STOP_FAILED: {type(exc).__name__}: {exc}")
                evidence["ok"] = False
        if not evidence["ok"]:
            evidence["classification"] = (
                f"STAGE32_{args.bandwidth_mhz}MSPS_{args.mode.upper()}_BOARD_HOST_FAIL"
            )
        output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if evidence["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
