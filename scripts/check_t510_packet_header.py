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
    from python.packet import (
        FLAG_INTERNAL_EPOCH,
        FLAG_UDP_DRY_RUN,
        HEADER_BYTES,
        MAGIC,
        T510PacketHeader,
    )

    parser = argparse.ArgumentParser(description="Parse and sanity-check a T510 UDP packet header.")
    parser.add_argument("packet", type=Path, help="Binary file containing at least the 128-byte T510 header.")
    parser.add_argument("--require-dry-run", action="store_true")
    args = parser.parse_args()

    raw = args.packet.read_bytes()
    if len(raw) < HEADER_BYTES:
        raise SystemExit(f"packet too short: {len(raw)} bytes, need at least {HEADER_BYTES}")
    source = "bytes"
    try:
        header = T510PacketHeader.from_bytes(raw[:HEADER_BYTES])
    except ValueError as exc:
        if len(raw) < HEADER_BYTES:
            raise
        try:
            axis_words = struct.unpack("<16Q", raw[:HEADER_BYTES])
            header = T510PacketHeader.from_axis_words(axis_words)
            source = "axis64_words"
        except ValueError:
            raise exc
    if header.magic != MAGIC:
        raise SystemExit(f"bad magic: 0x{header.magic:08x}")
    if args.require_dry_run and not (header.flags & FLAG_UDP_DRY_RUN):
        raise SystemExit("UDP_DRY_RUN flag is not set")

    summary = {
        "version": header.version,
        "board_id": header.board_id,
        "stream_type": header.stream_type,
        "epoch_mode": header.epoch_mode,
        "flags": header.flags,
        "internal_epoch": bool(header.flags & FLAG_INTERNAL_EPOCH),
        "udp_dry_run": bool(header.flags & FLAG_UDP_DRY_RUN),
        "unix_sec": header.unix_sec,
        "pps_count": header.pps_count,
        "sample0": header.sample0,
        "frame_id": header.frame_id,
        "seq_no": header.seq_no,
        "chan0": header.chan0,
        "chan_count": header.chan_count,
        "time_count": header.time_count,
        "ninput": header.ninput,
        "payload_format": header.payload_format,
        "payload_bytes": header.payload_bytes,
        "source": source,
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
