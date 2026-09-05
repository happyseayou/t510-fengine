#!/usr/bin/env python3
"""Independent Stage 35 replay/Zarr oracle validator.

This intentionally uses only the Python standard library.  It does not call the
Rust accumulator and reads the uncompressed Zarr v2 chunks directly.
"""

from __future__ import annotations

import argparse
import array
import hashlib
import json
import math
import struct
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


BLOCK_COUNT = 16
BLOCK_CHANS = 256
ADC_COUNT = 8
CELLS_PER_BLOCK = BLOCK_CHANS * ADC_COUNT
HEADER_BYTES = 128
PAYLOAD_BYTES = HEADER_BYTES + CELLS_PER_BLOCK * 4
SAMPLE_RATE_HZ = 320_000_000
FRAME_TICKS = 4096
COMMON_START_TICKS = SAMPLE_RATE_HZ // 10
BUCKET_MODES = (10, 20, 50, 100)
FLOAT_ARRAYS = (
    "mean_power_count2",
    "mean_i_count_100ms",
    "mean_q_count_100ms",
    "m2_power_count4_100ms",
)
U32_ARRAYS = ("n_valid", "clip_count_100ms", "n_valid_100ms")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def div_ceil(value: int, divisor: int) -> int:
    return (value + divisor - 1) // divisor


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def pcap_payloads(path: Path) -> list[list[bytes]]:
    raw = path.read_bytes()
    if len(raw) < 24:
        raise RuntimeError("PCAP global header is truncated")
    magic = raw[:4]
    if magic in (b"\xd4\xc3\xb2\xa1", b"\x4d\x3c\xb2\xa1"):
        endian = "<"
    elif magic in (b"\xa1\xb2\xc3\xd4", b"\xa1\xb2\x3c\x4d"):
        endian = ">"
    else:
        raise RuntimeError(f"unsupported PCAP magic {magic.hex()}")
    if struct.unpack_from(endian + "I", raw, 20)[0] != 1:
        raise RuntimeError("PCAP is not Ethernet link type 1")
    result: list[list[bytes]] = [[] for _ in range(BLOCK_COUNT)]
    offset = 24
    while offset + 16 <= len(raw):
        included = struct.unpack_from(endian + "I", raw, offset + 8)[0]
        offset += 16
        frame = raw[offset : offset + included]
        offset += included
        if len(frame) != included or len(frame) < 14:
            raise RuntimeError("PCAP record is truncated")
        ether_type = struct.unpack_from("!H", frame, 12)[0]
        ip_offset = 14
        while ether_type in (0x8100, 0x88A8):
            if len(frame) < ip_offset + 4:
                raise RuntimeError("truncated VLAN Ethernet frame")
            ether_type = struct.unpack_from("!H", frame, ip_offset + 2)[0]
            ip_offset += 4
        if ether_type != 0x0800 or len(frame) < ip_offset + 20:
            continue
        ihl = (frame[ip_offset] & 0x0F) * 4
        if ihl < 20 or frame[ip_offset + 9] != 17:
            continue
        udp_offset = ip_offset + ihl
        if len(frame) < udp_offset + 8:
            continue
        dst_port = struct.unpack_from("!H", frame, udp_offset + 2)[0]
        udp_len = struct.unpack_from("!H", frame, udp_offset + 4)[0]
        end = udp_offset + udp_len
        if udp_len < 8 or end > len(frame):
            raise RuntimeError("invalid UDP length in source PCAP")
        payload = frame[udp_offset + 8 : end]
        if not 4308 <= dst_port < 4308 + BLOCK_COUNT or len(payload) != PAYLOAD_BYTES:
            continue
        words = struct.unpack_from("<16Q", payload)
        if words[0] >> 32 != 0x54353130 or (words[1] >> 32) & 0xFFFF != 0:
            continue
        block = (words[9] >> 16) & 0xFFFF
        if block >= BLOCK_COUNT or dst_port != 4308 + block:
            raise RuntimeError("source PCAP port/block mapping mismatch")
        result[block].append(payload)
    if offset != len(raw):
        raise RuntimeError("PCAP has trailing bytes")
    if any(len(rows) != 32 for rows in result):
        raise RuntimeError(f"expected 32 source payloads per block, got {[len(x) for x in result]}")
    return result


def payload_iq(payload: bytes) -> array.array[int]:
    values = array.array("h")
    values.frombytes(payload[HEADER_BYTES:])
    if sys.byteorder != "little":
        values.byteswap()
    if len(values) != CELLS_PER_BLOCK * 2:
        raise RuntimeError("source IQ16 payload has the wrong cell count")
    return values


def read_native_array(path: Path, code: str, count: int) -> array.array[Any]:
    values = array.array(code)
    values.frombytes(path.read_bytes())
    if sys.byteorder != "little":
        values.byteswap()
    if len(values) != count:
        raise RuntimeError(f"{path}: expected {count} elements, got {len(values)}")
    return values


def read_cube(scan: Path, name: str, block: int) -> tuple[list[int], array.array[Any]]:
    meta = load_json(scan / name / ".zarray")
    shape = [int(x) for x in meta["shape"]]
    chunks = [int(x) for x in meta["chunks"]]
    code = "d" if meta["dtype"] == "<f8" else "I" if meta["dtype"] == "<u4" else None
    if code is None or shape[1:] != [ADC_COUNT, BLOCK_COUNT * BLOCK_CHANS]:
        raise RuntimeError(f"unsupported cube metadata for {scan.name}/{name}: {meta}")
    if (
        not 1 <= chunks[0] <= max(shape[0], 1)
        or chunks[1:] != [ADC_COUNT, BLOCK_CHANS]
        or meta.get("compressor") is not None
    ):
        raise RuntimeError(f"unexpected chunk/compressor contract for {scan.name}/{name}")
    values = array.array(code)
    for chunk_index in range(div_ceil(shape[0], chunks[0])):
        stored_count = chunks[0] * ADC_COUNT * BLOCK_CHANS
        chunk = read_native_array(
            scan / name / f"{chunk_index}.0.{block}", code, stored_count
        )
        valid_rows = min(chunks[0], shape[0] - chunk_index * chunks[0])
        values.extend(chunk[: valid_rows * ADC_COUNT * BLOCK_CHANS])
    return shape, values


def read_scalar(scan: Path, name: str, block: int) -> tuple[list[int], array.array[int]]:
    meta = load_json(scan / name / ".zarray")
    shape = [int(x) for x in meta["shape"]]
    chunks = [int(x) for x in meta["chunks"]]
    if (
        meta["dtype"] != "<u4"
        or shape[1:] != [BLOCK_COUNT]
        or not 1 <= chunks[0] <= max(shape[0], 1)
        or chunks[1:] != [1]
    ):
        raise RuntimeError(f"unexpected scalar metadata for {scan.name}/{name}: {meta}")
    values = array.array("I")
    for chunk_index in range(div_ceil(shape[0], chunks[0])):
        chunk = read_native_array(
            scan / name / f"{chunk_index}.{block}", "I", chunks[0]
        )
        valid_rows = min(chunks[0], shape[0] - chunk_index * chunks[0])
        values.extend(chunk[:valid_rows])
    return shape, values


def cube_index(time_index: int, cell: int) -> int:
    local_bin, adc = divmod(cell, ADC_COUNT)
    return time_index * CELLS_PER_BLOCK + adc * BLOCK_CHANS + local_bin


def periodic_sum(prefix2: list[int], period_sum: int, start: int, count: int) -> int:
    cycles, tail = divmod(count, 32)
    phase = start % 32
    return cycles * period_sum + prefix2[phase + tail] - prefix2[phase]


def prefix_twice(values: list[int]) -> tuple[list[int], int]:
    prefix = [0]
    for value in values + values:
        prefix.append(prefix[-1] + value)
    return prefix, sum(values)


def boundaries(bucket_ms: int, rows: int) -> list[tuple[int, int]]:
    width = bucket_ms * SAMPLE_RATE_HZ // 1000
    formal = div_ceil(COMMON_START_TICKS, FRAME_TICKS)
    result = []
    for row in range(rows):
        first = div_ceil(COMMON_START_TICKS + row * width, FRAME_TICKS)
        end = div_ceil(COMMON_START_TICKS + (row + 1) * width, FRAME_TICKS)
        result.append((first - formal, end - first))
    return result


def update_error(stats: dict[str, float | int], actual: float, expected: float, *, rtol: float, atol: float) -> None:
    absolute = abs(actual - expected)
    relative = absolute / max(abs(expected), 1.0)
    stats["comparisons"] = int(stats["comparisons"]) + 1
    stats["max_abs_error"] = max(float(stats["max_abs_error"]), absolute)
    stats["max_rel_error"] = max(float(stats["max_rel_error"]), relative)
    if not math.isclose(actual, expected, rel_tol=rtol, abs_tol=atol):
        stats["failures"] = int(stats["failures"]) + 1


def new_error_stats(rtol: float, atol: float) -> dict[str, float | int]:
    return {
        "registered_rtol": rtol,
        "registered_atol": atol,
        "comparisons": 0,
        "failures": 0,
        "max_abs_error": 0.0,
        "max_rel_error": 0.0,
    }


def verify_manifest(scan: Path, expected_complete: bool) -> dict[str, Any]:
    manifest_path = scan / "dataset_manifest.json"
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    digest = hashlib.sha256(manifest_bytes).hexdigest()
    digest_line = (scan / "dataset_manifest.sha256").read_text(encoding="ascii").strip()
    if digest_line != f"{digest}  dataset_manifest.json":
        raise RuntimeError(f"{scan.name}: dataset manifest digest mismatch")
    if bool(manifest["complete"]) != expected_complete:
        raise RuntimeError(f"{scan.name}: unexpected complete={manifest['complete']}")
    records = {row["path"]: row for row in manifest["files"]}
    if len(records) != len(manifest["files"]):
        raise RuntimeError(f"{scan.name}: duplicate paths in manifest")
    for relative, row in records.items():
        path = scan / relative
        if not path.is_file() or path.stat().st_size != row["bytes"] or sha256_file(path) != row["sha256"]:
            raise RuntimeError(f"{scan.name}: manifest file mismatch at {relative}")
    actual = {
        path.relative_to(scan).as_posix()
        for path in scan.rglob("*")
        if path.is_file() and path.name not in ("dataset_manifest.json", "dataset_manifest.sha256")
    }
    if actual != set(records):
        raise RuntimeError(f"{scan.name}: manifest/actual file set differs")
    partials = [path.relative_to(scan).as_posix() for path in scan.rglob("*.partial")]
    if partials:
        raise RuntimeError(f"{scan.name}: residual partial files: {partials}")
    journal = jsonl(scan / "chunk_journal.jsonl")
    if len({row["path"] for row in journal}) != len(journal):
        raise RuntimeError(f"{scan.name}: duplicate chunk journal entry")
    for row in journal:
        record = records.get(row["path"])
        if record != row:
            raise RuntimeError(f"{scan.name}: journal/manifest mismatch at {row['path']}")
    return {
        "complete": expected_complete,
        "failure_reason": manifest.get("failure_reason"),
        "manifest_sha256": digest,
        "file_count": len(records),
        "journal_entries": len(journal),
        "verified_bytes": sum(int(row["bytes"]) for row in records.values()),
        "partial_files": 0,
    }


def validate_nominal_quality(
    scan: Path, bucket_ms: int, duration_ms: int, status_flags_or_by_block: list[int]
) -> dict[str, Any]:
    rows_expected = duration_ms // bucket_ms
    moment_rows_expected = duration_ms // 100
    native = jsonl(scan / "bucket_quality.jsonl")
    moments = jsonl(scan / "bucket_quality_100ms.jsonl")
    if len(native) != rows_expected * BLOCK_COUNT or len(moments) != moment_rows_expected * BLOCK_COUNT:
        raise RuntimeError(f"{scan.name}: quality row cardinality mismatch")
    by_key = {(row["bucket_index"], row["block_index"]): row for row in native}
    origin_sample0 = load_json(scan / "capture_start.json")["origin_sample0"]
    native_bounds = boundaries(bucket_ms, rows_expected)
    total_valid_by_block = [0] * BLOCK_COUNT
    for bucket, (relative, count) in enumerate(native_bounds):
        first_delta = div_ceil(COMMON_START_TICKS, FRAME_TICKS) + relative
        for block in range(BLOCK_COUNT):
            row = by_key[(bucket, block)]
            expected = {
                "expected_frames": count,
                "valid_frames": count,
                "missing_frames": 0,
                "duplicate_count": 0,
                "reordered_count": 0,
                "late_count": 0,
                "first_sample0": origin_sample0 + first_delta * FRAME_TICKS,
                "last_sample0": origin_sample0 + (first_delta + count - 1) * FRAME_TICKS,
                "spec_status_flags_or": status_flags_or_by_block[block],
            }
            for key, value in expected.items():
                if row[key] != value:
                    raise RuntimeError(f"{scan.name}: native quality mismatch {bucket=} {block=} {key=}")
            total_valid_by_block[block] += row["valid_frames"]
    expected_total_frames = duration_ms * SAMPLE_RATE_HZ // 1000 // FRAME_TICKS
    if total_valid_by_block != [expected_total_frames] * BLOCK_COUNT:
        raise RuntimeError(f"{scan.name}: input/output frame conservation failed")
    if (scan / "gap_ranges.jsonl").stat().st_size or (scan / "arrival_events.jsonl").stat().st_size:
        raise RuntimeError(f"{scan.name}: nominal replay produced gap/arrival events")
    for row in moments:
        if row["expected_frames"] != row["valid_frames"] or row["missing_frames"] != 0:
            raise RuntimeError(f"{scan.name}: invalid 100 ms quality row")
        if row["spec_status_flags_or"] != status_flags_or_by_block[row["block_index"]]:
            raise RuntimeError(f"{scan.name}: 100 ms status-flag OR mismatch")
    return {
        "native_rows": len(native),
        "moment_rows": len(moments),
        "valid_frames_per_block": total_valid_by_block[0],
        "gap_ranges": 0,
        "arrival_events": 0,
    }


def validate_numeric(root: Path, payloads: list[list[bytes]], duration_ms: int) -> dict[str, Any]:
    scans = {mode: root / f"nominal_{mode}ms" for mode in BUCKET_MODES}
    native_stats = {str(mode): new_error_stats(1e-13, 1e-9) for mode in BUCKET_MODES}
    merge_stats = {str(mode): new_error_stats(2e-13, 1e-8) for mode in (20, 50, 100)}
    moment_stats = {
        "mean_i": new_error_stats(1e-13, 1e-10),
        "mean_q": new_error_stats(1e-13, 1e-10),
        "m2_power": new_error_stats(2e-12, 1e5),
        "clip_count": new_error_stats(0.0, 0.0),
    }
    cross_mode_moment_stats = {
        name: new_error_stats(2e-12 if name == "m2_power_count4_100ms" else 1e-13, 1e5 if name == "m2_power_count4_100ms" else 1e-10)
        for name in ("mean_i_count_100ms", "mean_q_count_100ms", "m2_power_count4_100ms", "clip_count_100ms", "n_valid_100ms")
    }
    bounds = {mode: boundaries(mode, duration_ms // mode) for mode in BUCKET_MODES}
    moment_rows = duration_ms // 100
    correlation = {lag: [0.0, 0.0, 0.0] for lag in range(1, 9)}

    for block in range(BLOCK_COUNT):
        iq_frames = [payload_iq(payload) for payload in payloads[block]]
        cubes: dict[int, array.array[Any]] = {}
        counts: dict[int, array.array[int]] = {}
        moment_cubes: dict[int, dict[str, array.array[Any]]] = defaultdict(dict)
        for mode, scan in scans.items():
            shape, cubes[mode] = read_cube(scan, "mean_power_count2", block)
            if shape[0] != duration_ms // mode:
                raise RuntimeError(f"{scan.name}: wrong native time shape")
            _, counts[mode] = read_scalar(scan, "n_valid", block)
            for name in ("mean_i_count_100ms", "mean_q_count_100ms", "m2_power_count4_100ms", "clip_count_100ms"):
                shape, values = read_cube(scan, name, block)
                if shape[0] != moment_rows:
                    raise RuntimeError(f"{scan.name}/{name}: wrong 100 ms shape")
                moment_cubes[mode][name] = values
            _, moment_cubes[mode]["n_valid_100ms"] = read_scalar(scan, "n_valid_100ms", block)

        for mode in BUCKET_MODES:
            expected_counts = [count for _, count in bounds[mode]]
            if list(counts[mode]) != expected_counts:
                raise RuntimeError(f"nominal_{mode}ms: n_valid mismatch for block {block}")

        for cell in range(CELLS_PER_BLOCK):
            i_values = [int(frame[cell * 2]) for frame in iq_frames]
            q_values = [int(frame[cell * 2 + 1]) for frame in iq_frames]
            p_values = [i * i + q * q for i, q in zip(i_values, q_values)]
            clip_values = [int(i == -32768 or q == -32768 or abs(i) >= 32760 or abs(q) >= 32760) for i, q in zip(i_values, q_values)]
            p_prefix, p_period = prefix_twice(p_values)
            i_prefix, i_period = prefix_twice(i_values)
            q_prefix, q_period = prefix_twice(q_values)
            p2_prefix, p2_period = prefix_twice([value * value for value in p_values])
            clip_prefix, clip_period = prefix_twice(clip_values)

            mean_p = sum(p_values) / 32.0
            centered = [value - mean_p for value in p_values]
            for lag in range(1, 9):
                for index in range(32 - lag):
                    x = centered[index]
                    y = centered[index + lag]
                    correlation[lag][0] += x * y
                    correlation[lag][1] += x * x
                    correlation[lag][2] += y * y

            for mode in BUCKET_MODES:
                for row, (start, count) in enumerate(bounds[mode]):
                    expected = periodic_sum(p_prefix, p_period, start, count) / count
                    actual = float(cubes[mode][cube_index(row, cell)])
                    update_error(native_stats[str(mode)], actual, expected, rtol=1e-13, atol=1e-9)

            for row, (start, count) in enumerate(bounds[100]):
                sum_i = periodic_sum(i_prefix, i_period, start, count)
                sum_q = periodic_sum(q_prefix, q_period, start, count)
                sum_p = periodic_sum(p_prefix, p_period, start, count)
                sum_p2 = periodic_sum(p2_prefix, p2_period, start, count)
                clipped = periodic_sum(clip_prefix, clip_period, start, count)
                expected_values = {
                    "mean_i_count_100ms": sum_i / count,
                    "mean_q_count_100ms": sum_q / count,
                    "m2_power_count4_100ms": float(sum_p2) - float(sum_p) * float(sum_p) / count,
                    "clip_count_100ms": float(clipped),
                }
                labels = {
                    "mean_i_count_100ms": "mean_i",
                    "mean_q_count_100ms": "mean_q",
                    "m2_power_count4_100ms": "m2_power",
                    "clip_count_100ms": "clip_count",
                }
                for name, expected in expected_values.items():
                    actual = float(moment_cubes[10][name][cube_index(row, cell)])
                    spec = moment_stats[labels[name]]
                    update_error(spec, actual, expected, rtol=float(spec["registered_rtol"]), atol=float(spec["registered_atol"]))

            for mode in (20, 50, 100):
                factor = mode // 10
                for row in range(duration_ms // mode):
                    first = row * factor
                    total = sum(int(counts[10][index]) for index in range(first, first + factor))
                    merged = sum(
                        float(cubes[10][cube_index(index, cell)]) * int(counts[10][index])
                        for index in range(first, first + factor)
                    ) / total
                    actual = float(cubes[mode][cube_index(row, cell)])
                    update_error(merge_stats[str(mode)], actual, merged, rtol=2e-13, atol=1e-8)

            for mode in (20, 50, 100):
                for name, reference in moment_cubes[10].items():
                    if name == "n_valid_100ms":
                        continue
                    spec = cross_mode_moment_stats[name]
                    for row in range(moment_rows):
                        actual = float(moment_cubes[mode][name][cube_index(row, cell)])
                        expected = float(reference[cube_index(row, cell)])
                        update_error(spec, actual, expected, rtol=float(spec["registered_rtol"]), atol=float(spec["registered_atol"]))

        reference_counts = list(moment_cubes[10]["n_valid_100ms"])
        if reference_counts != [count for _, count in bounds[100]]:
            raise RuntimeError(f"nominal_10ms: n_valid_100ms mismatch for block {block}")
        for mode in (20, 50, 100):
            for actual, expected in zip(moment_cubes[mode]["n_valid_100ms"], reference_counts):
                spec = cross_mode_moment_stats["n_valid_100ms"]
                update_error(spec, float(actual), float(expected), rtol=0.0, atol=0.0)

    all_stats = list(native_stats.values()) + list(merge_stats.values()) + list(moment_stats.values()) + list(cross_mode_moment_stats.values())
    if any(int(stats["failures"]) for stats in all_stats):
        raise RuntimeError("numeric oracle or cross-granularity comparison exceeded registered tolerance")
    pfb_correlation = {
        str(lag): covariance / math.sqrt(x2 * y2) if x2 and y2 else math.nan
        for lag, (covariance, x2, y2) in correlation.items()
    }
    return {
        "native_integer_oracle": native_stats,
        "ten_ms_weighted_merge": merge_stats,
        "moment_integer_oracle": moment_stats,
        "cross_mode_100ms_moments": cross_mode_moment_stats,
        "pfb_frame_power_correlation": {
            "method": "per-cell demeaned pooled Pearson correlation across all 16x2048 cells and 32-frame source windows",
            "lag_unit": "12.8 us spectrum-frame intervals",
            "coefficients": pfb_correlation,
        },
    }


def validate_faults(root: Path) -> dict[str, Any]:
    fault = root / "fault_injection_100ms"
    quality = {(row["bucket_index"], row["block_index"]): row for row in jsonl(fault / "bucket_quality.jsonl")}
    first = quality[(0, 0)]
    if first["valid_frames"] != 3 or first["duplicate_count"] != 1 or first["reordered_count"] != 1:
        raise RuntimeError(f"fault injection reorder/duplicate mismatch: {first}")
    missing = quality[(5, 1)]
    if missing["valid_frames"] != 0 or missing["missing_frames"] != missing["expected_frames"]:
        raise RuntimeError("fault injection missing bucket quality mismatch")
    _, missing_count = read_scalar(fault, "n_valid", 1)
    _, missing_power = read_cube(fault, "mean_power_count2", 1)
    if missing_count[5] != 0 or not math.isnan(float(missing_power[cube_index(5, 0)])):
        raise RuntimeError("missing fault bucket was not represented as N=0/NaN")
    arrivals = jsonl(fault / "arrival_events.jsonl")
    gaps = jsonl(fault / "gap_ranges.jsonl")
    if len(arrivals) != 1 or arrivals[0]["kind"] != "late" or len(gaps) != 159:
        raise RuntimeError("fault event ledgers have unexpected cardinality/kind")
    stop_manifest = load_json(root / "explicit_stop_100ms" / "dataset_manifest.json")
    if stop_manifest["complete"] or stop_manifest["failure_reason"] != "intentional Stage 35 step-3 recovery validation":
        raise RuntimeError("explicit-stop failure manifest mismatch")
    return {
        "reordered_frames_counted_once": True,
        "duplicate_frames_excluded": True,
        "missing_bucket": {"bucket": 5, "block": 1, "n_valid": 0, "floating_fill": "NaN"},
        "gap_ranges": len(gaps),
        "closed_bucket_arrival_events": arrivals,
        "explicit_stop_complete": False,
        "explicit_stop_failure_reason": stop_manifest["failure_reason"],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-pcap", type=Path, required=True)
    parser.add_argument("--replay-root", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.output_json.exists():
        raise RuntimeError(f"refusing to overwrite {args.output_json}")
    summary = load_json(args.replay_root / "step3_replay_summary.json")
    durations = {int(row["duration_seconds"]) for row in summary["nominal_runs"]}
    if len(durations) != 1:
        raise RuntimeError(f"nominal replay durations differ: {sorted(durations)}")
    duration_ms = durations.pop() * 1000
    source_sha = sha256_file(args.source_pcap)
    if source_sha != summary["source"]["sha256"]:
        raise RuntimeError("source PCAP SHA-256 differs from replay summary")
    payloads = pcap_payloads(args.source_pcap)
    status_flags_or = 0
    status_flags_or_by_block: list[int] = []
    half_band_by_block: dict[str, list[bool]] = {}
    for block, rows in enumerate(payloads):
        flags = []
        half_bands = set()
        for payload in rows:
            words = struct.unpack_from("<16Q", payload)
            flags.append(words[10] & 0xFFFF_FFFF)
            half_bands.add(bool(words[11] & 1))
        for value in flags:
            status_flags_or |= int(value)
        block_flags_or = 0
        for value in flags:
            block_flags_or |= int(value)
        status_flags_or_by_block.append(block_flags_or)
        half_band_by_block[str(block)] = sorted(half_bands)
    if status_flags_or != summary["source"]["spec_status_flags"]:
        raise RuntimeError("source status flag OR differs from replay summary")

    manifests = {}
    for mode in BUCKET_MODES:
        scan = args.replay_root / f"nominal_{mode}ms"
        manifests[scan.name] = verify_manifest(scan, True)
    manifests["fault_injection_100ms"] = verify_manifest(args.replay_root / "fault_injection_100ms", True)
    manifests["explicit_stop_100ms"] = verify_manifest(args.replay_root / "explicit_stop_100ms", False)

    quality = {
        f"nominal_{mode}ms": validate_nominal_quality(
            args.replay_root / f"nominal_{mode}ms",
            mode,
            duration_ms,
            status_flags_or_by_block,
        )
        for mode in BUCKET_MODES
    }
    numeric = validate_numeric(args.replay_root, payloads, duration_ms)
    faults = validate_faults(args.replay_root)
    result = {
        "format": "T510_STAGE35_REPLAY_ORACLE_V1",
        "schema_version": 1,
        "status": "PASS",
        "validator": {
            "path": str(Path(__file__).resolve()),
            "sha256": sha256_file(Path(__file__).resolve()),
            "dependencies": "Python standard library only",
            "zarr_reader": "direct Zarr v2 uncompressed chunk reader independent of Rust implementation",
        },
        "source": {
            "path": str(args.source_pcap.resolve()),
            "sha256": source_sha,
            "payloads": sum(len(rows) for rows in payloads),
            "payloads_per_block": [len(rows) for rows in payloads],
            "iq16_payload_bytes_preserved_by_replay": True,
            "spec_status_flags_or": status_flags_or,
            "spec_status_flags_or_by_block": status_flags_or_by_block,
            "spec_half_band_values_by_block": half_band_by_block,
        },
        "manifests": manifests,
        "quality_and_conservation": quality,
        "numeric": numeric,
        "fault_and_stop": faults,
    }
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    with args.output_json.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(f"STAGE35_ORACLE_PASS output={args.output_json}")


if __name__ == "__main__":
    main()
