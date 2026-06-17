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
        "sync_config",
        "status",
        "streaming",
        "rfdc_status_flags",
        "rfdc_current_valid_mask",
        "rfdc_sample_count",
        "spec_packet_count",
        "spec_udp_byte_count",
        "spec_seq_no",
        "spec_frame_id",
        "spec_chan0",
        "tx_link_status_flags",
        "qsfp_link_up",
        "udp_dry_run",
        "tx_dry_run_packet_count",
        "tx_dry_run_byte_count",
        "tx_fifo_level_words",
        "tx_fifo_high_water_words",
        "tx_fifo_backpressure_cycles",
        "tx_header_capture_status",
    ]
    return {key: int(status.get(key, 0)) for key in keys}


def main() -> int:
    _add_repo_python_path()
    from python.packet import (
        FLAG_INTERNAL_EPOCH,
        FLAG_QSFP_LINK_UP,
        FLAG_UDP_DRY_RUN,
        STREAM_SPEC,
    )
    from python.t510_fengine import T510FEngine

    default_bitfile = _repo_root() / "overlay" / "t510_fengine.bit"
    parser = argparse.ArgumentParser(description="Stage 5 SPEC dry-run/FIFO/header capture check on PYNQ.")
    parser.add_argument("--bitfile", default=str(default_bitfile))
    parser.add_argument("--mask", type=_parse_int, default=0x0001)
    parser.add_argument("--seconds", type=float, default=0.5)
    parser.add_argument("--timeout", type=float, default=2.0)
    parser.add_argument("--no-download", action="store_true")
    args = parser.parse_args()

    core = T510FEngine(args.bitfile, download=not args.no_download)
    before = core.init_lab_rfdc(mask=args.mask, mode="spec", wait_seconds=args.timeout)
    time.sleep(args.seconds)
    after = core.read_status()
    capture = core.capture_tx_header(timeout=args.timeout)
    header = capture["header"]
    header_dict = capture["header_dict"]

    errors: list[str] = []
    if after["core_version"] < 0x0001_0003:
        errors.append(f"expected CORE_VERSION >= 0x00010003, got 0x{after['core_version']:08x}")
    if not after["streaming"]:
        errors.append("F-engine is not streaming")
    if (after["rfdc_current_valid_mask"] & args.mask) != args.mask:
        errors.append(
            f"selected mask 0x{args.mask:04x} not present in current_valid_mask "
            f"0x{after['rfdc_current_valid_mask']:04x}"
        )
    if after["spec_packet_count"] <= before["spec_packet_count"]:
        errors.append("SPEC packet counter did not grow")
    if after["tx_dry_run_packet_count"] <= before["tx_dry_run_packet_count"]:
        errors.append("TX dry-run packet counter did not grow")
    if after["tx_dry_run_byte_count"] <= before["tx_dry_run_byte_count"]:
        errors.append("TX dry-run byte counter did not grow")
    if after["qsfp_link_up"]:
        errors.append("QSFP_LINK_UP is unexpectedly set in no-QSFP dry-run")
    if not after["udp_dry_run"]:
        errors.append("UDP_DRY_RUN status bit is not set")
    if after["tx_fifo_high_water_words"] <= 0:
        errors.append("TX FIFO high-water counter did not rise")
    if header.version != 2:
        errors.append(f"expected header version 2, got {header.version}")
    if header.stream_type != STREAM_SPEC:
        errors.append(f"expected stream_type SPEC(0), got {header.stream_type}")
    if header.payload_bytes != 8192:
        errors.append(f"expected payload_bytes 8192, got {header.payload_bytes}")
    if not (header.flags & FLAG_UDP_DRY_RUN):
        errors.append("captured header missing UDP_DRY_RUN flag")
    if not (header.flags & FLAG_INTERNAL_EPOCH):
        errors.append("captured header missing INTERNAL_EPOCH flag")
    if header.flags & FLAG_QSFP_LINK_UP:
        errors.append("captured header unexpectedly has QSFP_LINK_UP flag")

    summary = {
        "before": _status_subset(before),
        "after": _status_subset(after),
        "header": header_dict,
        "axis_words_first10": [f"0x{word:016x}" for word in capture["axis_words"][:10]],
        "result": "PASS" if not errors else "FAIL",
        "errors": errors,
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
