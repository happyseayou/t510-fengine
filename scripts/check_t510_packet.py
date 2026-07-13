#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import struct
import sys


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def main() -> int:
    sys.path.insert(0, str(_root()))
    from python.packet import EthernetIPv4UDPFrame, HEADER_BYTES, MAGIC, T510PacketHeader

    parser = argparse.ArgumentParser(description="Inspect a T510 header or complete Ethernet/IPv4/UDP frame")
    parser.add_argument("input", type=Path)
    parser.add_argument("--kind", choices=("header", "frame"), default="frame")
    parser.add_argument("--axis-words", action="store_true")
    parser.add_argument("--expect-dst-ip")
    parser.add_argument("--expect-dst-port", type=int)
    parser.add_argument("--expect-stream-type", type=int)
    args = parser.parse_args()
    raw = args.input.read_bytes()
    errors: list[str] = []
    if args.kind == "header":
        if len(raw) < HEADER_BYTES:
            parser.error(f"header input needs at least {HEADER_BYTES} bytes")
        try:
            header = T510PacketHeader.from_bytes(raw[:HEADER_BYTES])
            source = "bytes"
        except ValueError:
            header = T510PacketHeader.from_axis_words(struct.unpack("<16Q", raw[:HEADER_BYTES]))
            source = "axis64_words"
        summary = asdict(header)
        summary["source"] = source
        if header.magic != MAGIC:
            errors.append("BAD_MAGIC")
    else:
        if args.axis_words:
            if len(raw) % 8:
                parser.error("--axis-words frame length must be a multiple of 8")
            frame = EthernetIPv4UDPFrame.from_axis_words(struct.unpack(f"<{len(raw) // 8}Q", raw))
        else:
            frame = EthernetIPv4UDPFrame.from_bytes(raw)
        summary = frame.to_dict()
        if args.expect_dst_ip and summary.get("dst_ip_str") != args.expect_dst_ip:
            errors.append("DST_IP_MISMATCH")
        if args.expect_dst_port is not None and frame.dst_port != args.expect_dst_port:
            errors.append("DST_PORT_MISMATCH")
        if args.expect_stream_type is not None:
            if frame.t510_header is None or frame.t510_header.stream_type != args.expect_stream_type:
                errors.append("STREAM_TYPE_MISMATCH")
    summary["result"] = "PASS" if not errors else "FAIL"
    summary["errors"] = errors
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
