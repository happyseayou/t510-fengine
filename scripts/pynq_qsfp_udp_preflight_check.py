#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _add_repo_python_path() -> None:
    sys.path.insert(0, str(_repo_root()))


def _parse_int(value: str) -> int:
    return int(value, 0)


def _status_subset(status: dict[str, int]) -> dict[str, int]:
    keys = [
        "core_version",
        "streaming",
        "rfdc_current_valid_mask",
        "rfdc_sample_count",
        "spec_packet_count",
        "spec_udp_byte_count",
        "spec_chan0",
        "tx_fifo_high_water_words",
        "tx_control",
        "tx_status",
        "tx_udp_dry_run_active",
        "tx_qsfp_link_up",
        "tx_frame_built_count",
        "tx_frame_sent_count",
        "tx_frame_dropped_count",
        "tx_frame_byte_count",
        "tx_route_miss_count",
        "tx_route_error_count",
        "pfb_chan0",
        "pfb_chan_count",
        "pfb_time_count",
        "pfb_frame_count",
    ]
    return {key: int(status.get(key, 0)) for key in keys}


def _read_route(core, base: int) -> dict[str, int]:
    control = int(core.ctrl.read(base + 0x00))
    return {
        "enable": control & 0x1,
        "endpoint_id": (control >> 8) & 0x7,
        "word4": int(core.ctrl.read(base + 0x04)),
        "word8": int(core.ctrl.read(base + 0x08)),
        "hit_count": int(core.ctrl.read(base + 0x0C)),
    }


def main() -> int:
    _add_repo_python_path()
    from python.packet import (
        FLAG_QSFP_LINK_UP,
        FLAG_UDP_DRY_RUN,
        STREAM_SPEC,
    )
    from python.t510_fengine import T510FEngine

    default_bitfile = _repo_root() / "overlay" / "t510_fengine.bit"
    parser = argparse.ArgumentParser(description="Stage 7 QSFP/CMAC UDP TX preflight check on PYNQ.")
    parser.add_argument("--bitfile", default=str(default_bitfile))
    parser.add_argument("--mask", type=_parse_int, default=0x0001)
    parser.add_argument("--chan-count", type=_parse_int, default=64)
    parser.add_argument("--time-count", type=_parse_int, default=4)
    parser.add_argument("--timeout", type=float, default=2.0)
    parser.add_argument("--seconds", type=float, default=0.5)
    parser.add_argument("--force-dry-run", action="store_true", default=True)
    parser.add_argument("--no-download", action="store_true")
    args = parser.parse_args()

    core = T510FEngine(args.bitfile, download=not args.no_download)
    core.configure_tx_control(
        force_dry_run=bool(args.force_dry_run),
        cmac_enable=False,
        frame_builder_enable=True,
        drop_on_route_miss=True,
        clear_counters=True,
    )
    core.configure_network(
        src_ip="10.0.1.1",
        src_mac="02:00:00:00:00:01",
        dgx_a={"ip": "10.0.1.10", "mac": "02:00:00:00:00:0a", "port": 4100},
        dgx_b={"ip": "10.0.1.11", "mac": "02:00:00:00:00:0b", "port": 4200},
        time_dst={"ip": "10.0.1.16", "mac": "02:00:00:00:00:10", "port": 4300},
    )
    core.configure_tx_endpoints(
        [
            {"id": 0, "ip": "10.0.1.10", "mac": "02:00:00:00:00:0a", "port": 4100},
            {"id": 1, "ip": "10.0.1.11", "mac": "02:00:00:00:00:0b", "port": 4200},
            {"id": 2, "ip": "10.0.1.16", "mac": "02:00:00:00:00:10", "port": 4300},
        ]
    )
    core.configure_spec_routes(
        [
            {"id": 0, "chan0": 0, "chan_count": 2048, "endpoint_id": 0},
            {"id": 1, "chan0": 2048, "chan_count": 2048, "endpoint_id": 1},
        ]
    )
    core.configure_time_routes(
        [
            {"id": 0, "input_mask": int(args.mask) & 0xFFFF, "endpoint_id": 2},
        ]
    )
    channelizer_cfg = core.configure_channelizer(
        chan0=0,
        chan_count=int(args.chan_count),
        time_count=int(args.time_count),
        enable=True,
    )
    init_status = core.init_lab_rfdc(mask=int(args.mask), mode="spec", wait_seconds=float(args.timeout))
    before = core.read_status()
    time.sleep(float(args.seconds))

    def capture_for_chan(chan0: int, expected_ip: str, expected_port: int) -> dict[str, object]:
        core.configure_channelizer(chan0=chan0, chan_count=int(args.chan_count), time_count=int(args.time_count))
        deadline = time.monotonic() + float(args.timeout)
        last_capture: dict[str, object] | None = None
        while time.monotonic() < deadline:
            capture = core.capture_tx_frame_header(timeout=float(args.timeout))
            last_capture = capture
            frame = capture["frame"]
            if frame.to_dict()["dst_ip_str"] == expected_ip and frame.dst_port == expected_port:
                return capture
            time.sleep(0.02)
        if last_capture is None:
            raise TimeoutError(f"no frame captured for chan0={chan0}")
        return last_capture

    internal_capture = core.capture_tx_header(timeout=float(args.timeout))
    route0_capture = capture_for_chan(0, "10.0.1.10", 4100)
    route1_capture = capture_for_chan(2048, "10.0.1.11", 4200)
    after = core.read_status()
    tx_status = core.read_tx_status()
    header = internal_capture["header"]
    frame0 = route0_capture["frame"]
    frame1 = route1_capture["frame"]

    errors: list[str] = []
    if after["core_version"] != 0x0001_0005:
        errors.append(f"expected CORE_VERSION 0x00010005, got 0x{after['core_version']:08x}")
    if not after["streaming"]:
        errors.append("F-engine is not streaming")
    if (after["rfdc_current_valid_mask"] & int(args.mask)) != int(args.mask):
        errors.append("selected RFDC input mask is not valid")
    if not tx_status["udp_dry_run_active"]:
        errors.append("TX preflight dry-run is not active")
    if tx_status["qsfp_link_up"]:
        errors.append("QSFP link is unexpectedly up during preflight")
    if after["tx_frame_built_count"] <= before["tx_frame_built_count"]:
        errors.append("TX frame built counter did not grow")
    if after["tx_frame_sent_count"] <= before["tx_frame_sent_count"]:
        errors.append("TX dry-run/sent counter did not grow")
    if after["tx_route_error_count"] != 0:
        errors.append(f"route error count is nonzero: {after['tx_route_error_count']}")
    if header.stream_type != STREAM_SPEC:
        errors.append(f"internal header stream_type is not SPEC: {header.stream_type}")
    if header.payload_bytes != 8192:
        errors.append(f"internal header payload_bytes expected 8192, got {header.payload_bytes}")
    if not (header.flags & FLAG_UDP_DRY_RUN):
        errors.append("internal header missing UDP_DRY_RUN flag")
    if header.flags & FLAG_QSFP_LINK_UP:
        errors.append("internal header unexpectedly has QSFP_LINK_UP flag")
    if frame0.to_dict()["dst_ip_str"] != "10.0.1.10" or frame0.dst_port != 4100:
        errors.append(f"route0 frame target mismatch: {frame0.to_dict()}")
    if frame1.to_dict()["dst_ip_str"] != "10.0.1.11" or frame1.dst_port != 4200:
        errors.append(f"route1 frame target mismatch: {frame1.to_dict()}")
    if frame0.udp_length != 8328 or frame1.udp_length != 8328:
        errors.append(f"unexpected UDP length: route0={frame0.udp_length}, route1={frame1.udp_length}")
    if frame0.ipv4_total_length != 8348 or frame1.ipv4_total_length != 8348:
        errors.append(
            f"unexpected IPv4 total length: route0={frame0.ipv4_total_length}, "
            f"route1={frame1.ipv4_total_length}"
        )

    regs = core.regs
    route0 = _read_route(core, regs.TX_SPEC_ROUTE_BASE + 0 * regs.TX_SPEC_ROUTE_STRIDE)
    route1 = _read_route(core, regs.TX_SPEC_ROUTE_BASE + 1 * regs.TX_SPEC_ROUTE_STRIDE)
    time_route0 = _read_route(core, regs.TX_TIME_ROUTE_BASE + 0 * regs.TX_TIME_ROUTE_STRIDE)
    if route0["enable"] != 1 or route0["endpoint_id"] != 0 or route0["word4"] != 0 or route0["word8"] != 2048:
        errors.append(f"SPEC route0 readback mismatch: {route0}")
    if route1["enable"] != 1 or route1["endpoint_id"] != 1 or route1["word4"] != 2048 or route1["word8"] != 2048:
        errors.append(f"SPEC route1 readback mismatch: {route1}")
    if time_route0["enable"] != 1 or time_route0["endpoint_id"] != 2 or time_route0["word4"] != (int(args.mask) & 0xFFFF):
        errors.append(f"TIME route0 readback mismatch: {time_route0}")

    summary = {
        "channelizer_config": channelizer_cfg,
        "init": _status_subset(init_status),
        "before": _status_subset(before),
        "after": _status_subset(after),
        "tx_status": tx_status,
        "internal_header": internal_capture["header_dict"],
        "route0_frame": frame0.to_dict(),
        "route1_frame": frame1.to_dict(),
        "route_readback": {
            "spec0": route0,
            "spec1": route1,
            "time0": time_route0,
        },
        "route0_axis_words_first6": [f"0x{word:016x}" for word in route0_capture["axis_words"][:6]],
        "route1_axis_words_first6": [f"0x{word:016x}" for word in route1_capture["axis_words"][:6]],
        "result": "PASS" if not errors else "FAIL",
        "errors": errors,
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
