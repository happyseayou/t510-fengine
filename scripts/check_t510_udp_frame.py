#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import struct
import sys


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _add_repo_python_path() -> None:
    sys.path.insert(0, str(_repo_root()))


def main() -> int:
    _add_repo_python_path()
    from python.packet import EthernetIPv4UDPFrame

    parser = argparse.ArgumentParser(description="Parse and sanity-check a T510 Ethernet/IPv4/UDP frame.")
    parser.add_argument("frame", type=Path, help="Binary frame file, or captured 64-bit AXIS words with --axis-words.")
    parser.add_argument("--axis-words", action="store_true", help="Interpret the file as little-endian 64-bit AXIS words.")
    parser.add_argument("--expect-dst-ip")
    parser.add_argument("--expect-dst-port", type=int)
    parser.add_argument("--expect-stream-type", type=int)
    args = parser.parse_args()

    raw = args.frame.read_bytes()
    if args.axis_words:
        if len(raw) % 8:
            raise SystemExit("--axis-words input length must be a multiple of 8 bytes")
        words = struct.unpack(f"<{len(raw) // 8}Q", raw)
        frame = EthernetIPv4UDPFrame.from_axis_words(words)
    else:
        frame = EthernetIPv4UDPFrame.from_bytes(raw)

    summary = frame.to_dict()
    errors: list[str] = []
    if args.expect_dst_ip is not None and summary["dst_ip_str"] != args.expect_dst_ip:
        errors.append(f"expected dst_ip {args.expect_dst_ip}, got {summary['dst_ip_str']}")
    if args.expect_dst_port is not None and frame.dst_port != args.expect_dst_port:
        errors.append(f"expected dst_port {args.expect_dst_port}, got {frame.dst_port}")
    if args.expect_stream_type is not None:
        if frame.t510_header is None:
            errors.append("captured frame does not include a complete T510 header")
        elif frame.t510_header.stream_type != args.expect_stream_type:
            errors.append(
                f"expected stream_type {args.expect_stream_type}, got {frame.t510_header.stream_type}"
            )

    summary["result"] = "PASS" if not errors else "FAIL"
    summary["errors"] = errors
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
