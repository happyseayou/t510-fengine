#!/usr/bin/env python3
"""Independently verify a sealed Stage 35 S1 TIME dataset and raw PCAP."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import struct
from collections import Counter
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def udp_view(frame: bytes) -> tuple[int, bytes]:
    if len(frame) < 42 or frame[12:14] != b"\x08\x00":
        raise ValueError("raw PCAP contains a non-IPv4 Ethernet frame")
    ip = 14
    ihl = (frame[ip] & 0x0F) * 4
    if ihl < 20 or frame[ip + 9] != 17:
        raise ValueError("raw PCAP contains a non-UDP IPv4 frame")
    udp = ip + ihl
    dst_port = struct.unpack_from("!H", frame, udp + 2)[0]
    return dst_port, frame[udp + 8 :]


def packet_identity(frame: bytes) -> tuple[int, int, int, int]:
    dst_port, payload = udp_view(frame)
    if len(payload) != 8320:
        raise ValueError(f"unexpected TIME UDP payload length {len(payload)}")
    words = struct.unpack_from("<16Q", payload)
    if words[0] >> 32 != 0x54353130 or (words[1] >> 32) & 0xFFFF != 1:
        raise ValueError("invalid T510 TIME header identity")
    return dst_port, (words[6] >> 32) & 0xFFFF_FFFF, words[5], words[4]


def crop_continuous_pcap(source: Path, destination: Path, packet_count: int = 62_500) -> dict[str, Any]:
    sequences: list[int] = []
    with source.open("rb") as handle:
        header = handle.read(24)
        if len(header) != 24 or header[:4] != b"\xd4\xc3\xb2\xa1":
            raise ValueError("raw superset is not little-endian classic PCAP")
        while record := handle.read(16):
            if len(record) != 16:
                raise ValueError("truncated PCAP record header")
            captured = struct.unpack_from("<I", record, 8)[0]
            frame = handle.read(captured)
            if len(frame) != captured:
                raise ValueError("truncated PCAP frame")
            sequences.append(packet_identity(frame)[1])
    ordered = sorted(set(sequences))
    if len(ordered) != len(sequences):
        raise ValueError("raw superset contains duplicate sequence numbers")
    best_start = best_length = 0
    run_start = run_length = 0
    for index, sequence in enumerate(ordered):
        if index and sequence == ordered[index - 1] + 1:
            run_length += 1
        else:
            run_start, run_length = index, 1
        if run_length > best_length:
            best_start, best_length = run_start, run_length
    if best_length < packet_count:
        raise ValueError(
            f"raw superset longest continuous run is {best_length} packets, need {packet_count}"
        )
    first_seq = ordered[best_start]
    last_seq = first_seq + packet_count - 1
    partial = destination.with_name(destination.name + ".partial")
    written = 0
    with source.open("rb") as source_handle, partial.open("xb") as output:
        output.write(source_handle.read(24))
        while record := source_handle.read(16):
            captured = struct.unpack_from("<I", record, 8)[0]
            frame = source_handle.read(captured)
            sequence = packet_identity(frame)[1]
            if first_seq <= sequence <= last_seq:
                output.write(record)
                output.write(frame)
                written += 1
    if written != packet_count:
        partial.unlink(missing_ok=True)
        raise ValueError(f"cropped {written} packets, expected {packet_count}")
    partial.replace(destination)
    return {
        "source": str(source),
        "destination": str(destination),
        "source_packets": len(sequences),
        "longest_continuous_source_run": best_length,
        "first_seq": first_seq,
        "last_seq": last_seq,
        "packets": written,
    }


def verify_pcap(path: Path) -> dict[str, Any]:
    by_port: dict[int, list[tuple[int, int, int]]] = {port: [] for port in range(4300, 4308)}
    frame_count = 0
    with path.open("rb") as handle:
        header = handle.read(24)
        if len(header) != 24 or header[:4] != b"\xd4\xc3\xb2\xa1":
            raise ValueError("raw capture is not little-endian classic PCAP")
        while record := handle.read(16):
            if len(record) != 16:
                raise ValueError("truncated PCAP record header")
            captured = struct.unpack_from("<I", record, 8)[0]
            frame = handle.read(captured)
            if len(frame) != captured:
                raise ValueError("truncated PCAP frame")
            dst_port, seq, frame_id, sample0 = packet_identity(frame)
            if dst_port not in by_port:
                raise ValueError(f"unexpected raw TIME destination port {dst_port}")
            by_port[dst_port].append((seq, frame_id, sample0))
            frame_count += 1

    counts = {str(port): len(rows) for port, rows in by_port.items()}
    if frame_count != 62_500 or max(counts.values()) - min(counts.values()) > 1:
        raise ValueError(f"unbalanced TIME PCAP flow counts: {counts}")
    all_rows = sorted((row for rows in by_port.values() for row in rows), key=lambda row: row[0])
    discontinuities = []
    for prior, current in zip(all_rows, all_rows[1:]):
        if (
            current[0] != (prior[0] + 1) & 0xFFFF_FFFF
            or current[1] != prior[1] + 1
            or current[2] != prior[2] + 256
        ):
            discontinuities.append({"prior": prior, "current": current})
    if discontinuities:
        raise ValueError(f"raw TIME PCAP is not continuous: {discontinuities[:4]}")
    samples = frame_count * 256
    return {
        "path": str(path),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "frame_count": frame_count,
        "packets_by_port": counts,
        "first_seq": all_rows[0][0],
        "last_seq": all_rows[-1][0],
        "first_sample0": all_rows[0][2],
        "last_sample0": all_rows[-1][2],
        "continuous_samples_per_lane": samples,
        "duration_ms_at_320msps": samples / 320_000.0,
        "discontinuities": 0,
    }


def verify_bucket_csv(
    path: Path, bucket_ms: int, bucket_count: int, *, require_mean_power: bool
) -> dict[str, Any]:
    counts: Counter[int] = Counter()
    rows = 0
    expected_samples = 320_000 * bucket_ms
    expected_packets = 1_250 * bucket_ms
    with path.open(newline="") as handle:
        for row in csv.DictReader(handle):
            bucket = int(row["bucket"])
            lane = int(row["lane"])
            if not 0 <= lane < 8:
                raise ValueError(f"invalid lane in {path.name}: {lane}")
            if int(row["samples"]) != expected_samples:
                raise ValueError(f"incomplete samples in {path.name} bucket {bucket}")
            if int(row["packets"]) != expected_packets:
                raise ValueError(f"incomplete packets in {path.name} bucket {bucket}")
            if require_mean_power:
                power = float(row["mean_power_adu2"])
                rms = float(row["complex_rms_adu"])
                if not math.isfinite(power) or not math.isclose(
                    power, rms * rms, rel_tol=2e-10, abs_tol=2e-10
                ):
                    raise ValueError(
                        f"mean_power_adu2 does not equal mean(I²+Q²) in "
                        f"{path.name} bucket {bucket} lane {lane}"
                    )
            counts[bucket] += 1
            rows += 1
    if rows != bucket_count * 8 or set(counts) != set(range(bucket_count)):
        raise ValueError(f"bucket/lane coverage mismatch in {path.name}")
    if set(counts.values()) != {8}:
        raise ValueError(f"not all lanes occur once per bucket in {path.name}")
    return {"rows": rows, "bucket_count": bucket_count, "lanes_per_bucket": 8}


def verify(root: Path, *, require_raw_pcap: bool = False) -> dict[str, Any]:
    manifest_path = root / "dataset_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("format") != "T510_TIME_CAPTURE_V1" or not manifest.get("complete"):
        raise ValueError("TIME dataset manifest is not complete V1")
    request = manifest.get("request", {})
    duration_seconds = int(request.get("duration_seconds", 0))
    if duration_seconds <= 0:
        raise ValueError("TIME manifest has no positive duration_seconds")
    schema_version = int(manifest.get("schema_version", 1))
    require_mean_power = schema_version >= 2
    identities = []
    for item in manifest["files"]:
        path = root / item["path"]
        actual = {"path": item["path"], "bytes": path.stat().st_size, "sha256": sha256_file(path)}
        if actual["bytes"] != item["bytes"] or actual["sha256"] != item["sha256"]:
            raise ValueError(f"manifest identity mismatch for {item['path']}")
        identities.append(actual)

    quality = json.loads((root / "flow_quality.json").read_text())
    if len(quality) != 8:
        raise ValueError("flow_quality does not contain all eight TIME flows")
    for row in quality:
        if (
            row["packets"] != duration_seconds * 156_250
            or row["missing_packets"]
            or row["reordered_packets"]
            or row["duplicate_packets"]
        ):
            raise ValueError(f"TIME flow quality failed: {row}")

    summary = json.loads((root / "summary.json").read_text())
    if summary["samples_per_lane"] != duration_seconds * 320_000_000 or len(summary["lanes"]) != 8:
        raise ValueError("summary sample/lane coverage mismatch")
    if any(summary[key] for key in ("missing_packets", "reordered_packets", "duplicate_packets")):
        raise ValueError("summary reports packet quality events")
    if summary["histogram_samples_per_lane"] != 16_000_000:
        raise ValueError("histogram is not the required continuous 50 ms full-sample window")

    histogram_counts: dict[tuple[int, str], int] = Counter()
    occupied: dict[tuple[int, str], int] = Counter()
    with (root / "histogram.csv").open(newline="") as handle:
        for row in csv.DictReader(handle):
            key = (int(row["lane"]), row["component"])
            histogram_counts[key] += int(row["count"])
            occupied[key] += 1
    expected_keys = {(lane, component) for lane in range(8) for component in ("I", "Q")}
    if set(histogram_counts) != expected_keys:
        raise ValueError("histogram lane/component coverage mismatch")
    if set(histogram_counts.values()) != {16_000_000}:
        raise ValueError(f"histogram sample totals mismatch: {histogram_counts}")

    raw_path = root / "raw" / "time_50ms_4300_4307.pcap"
    if require_raw_pcap and not raw_path.is_file():
        raise ValueError("required raw TIME PCAP is missing")
    raw = verify_pcap(raw_path) if raw_path.is_file() else None
    buckets_10ms = duration_seconds * 100
    buckets_20ms = duration_seconds * 50
    return {
        "status": "PASS",
        "dataset": str(root),
        "manifest": {
            "path": str(manifest_path),
            "bytes": manifest_path.stat().st_size,
            "sha256": sha256_file(manifest_path),
        },
        "manifest_files": identities,
        "schema_version": schema_version,
        "duration_seconds": duration_seconds,
        "time_10ms": verify_bucket_csv(
            root / "time_10ms.csv", 10, buckets_10ms,
            require_mean_power=require_mean_power,
        ),
        "time_20ms": verify_bucket_csv(
            root / "time_20ms.csv", 20, buckets_20ms,
            require_mean_power=require_mean_power,
        ),
        "flow_quality": {"flows": 8, "packets_per_flow": duration_seconds * 156_250, "events": 0},
        "histogram": {
            "duration_ms": 50,
            "samples_per_lane_component": 16_000_000,
            "occupied_codes": {f"adc{lane}_{component.lower()}": occupied[(lane, component)] for lane, component in sorted(expected_keys)},
        },
        "raw_pcap": raw,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--crop-source", type=Path)
    parser.add_argument("--crop-output", type=Path)
    parser.add_argument("--require-raw-pcap", action="store_true")
    args = parser.parse_args()
    crop = None
    if args.crop_source or args.crop_output:
        if not args.crop_source or not args.crop_output:
            parser.error("--crop-source and --crop-output must be used together")
        crop = crop_continuous_pcap(args.crop_source, args.crop_output)
    result = verify(args.dataset, require_raw_pcap=args.require_raw_pcap)
    if crop is not None:
        result["raw_crop"] = crop
    encoded = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(encoded)
    print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
