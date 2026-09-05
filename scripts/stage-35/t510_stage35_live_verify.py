#!/usr/bin/env python3
"""Verify sealed live Stage 35 datasets without third-party Python packages."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from t510_measurement_replay_validate import jsonl, load_json, read_scalar, verify_manifest


BLOCK_COUNT = 16


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def verify_scan(scan: Path) -> dict[str, Any]:
    scan = scan.resolve()
    manifest = load_json(scan / "dataset_manifest.json")
    require(manifest.get("stage") == "stage35", f"{scan.name}: wrong stage")
    require(manifest.get("complete") is True, f"{scan.name}: dataset is not complete")
    request = manifest["request"]
    native_count = int(manifest["native_bucket_count"])
    moment_count = int(manifest["moment_100ms_count"])
    native = jsonl(scan / "bucket_quality.jsonl")
    moments = jsonl(scan / "bucket_quality_100ms.jsonl")
    gaps = jsonl(scan / "gap_ranges.jsonl")
    arrivals = jsonl(scan / "arrival_events.jsonl")
    require(
        len(native) == native_count * BLOCK_COUNT,
        f"{scan.name}: native quality row cardinality mismatch",
    )
    require(
        len(moments) == moment_count * BLOCK_COUNT,
        f"{scan.name}: 100 ms quality row cardinality mismatch",
    )
    require(
        len({(row["bucket_index"], row["block_index"]) for row in native})
        == len(native),
        f"{scan.name}: duplicate native quality key",
    )
    require(
        len({(row["bucket_100ms_index"], row["block_index"]) for row in moments})
        == len(moments),
        f"{scan.name}: duplicate 100 ms quality key",
    )

    native_expected = sum(int(row["expected_frames"]) for row in native)
    native_valid = sum(int(row["valid_frames"]) for row in native)
    native_missing = sum(int(row["missing_frames"]) for row in native)
    moment_expected = sum(int(row["expected_frames"]) for row in moments)
    moment_valid = sum(int(row["valid_frames"]) for row in moments)
    moment_missing = sum(int(row["missing_frames"]) for row in moments)
    gap_missing = sum(int(row["missing_groups"]) for row in gaps)
    require(
        native_expected == native_valid + native_missing,
        f"{scan.name}: native expected/valid/missing conservation failed",
    )
    require(
        (moment_expected, moment_valid, moment_missing)
        == (native_expected, native_valid, native_missing),
        f"{scan.name}: native/100 ms quality conservation failed",
    )
    require(
        gap_missing == native_missing,
        f"{scan.name}: gap ledger does not match missing frames",
    )

    scalar_valid = 0
    scalar_moment_valid = 0
    native_shape = None
    moment_shape = None
    for block in range(BLOCK_COUNT):
        shape, values = read_scalar(scan, "n_valid", block)
        coarse_shape, coarse_values = read_scalar(scan, "n_valid_100ms", block)
        native_shape = native_shape or shape
        moment_shape = moment_shape or coarse_shape
        require(shape == native_shape, f"{scan.name}: n_valid shape changed by block")
        require(
            coarse_shape == moment_shape,
            f"{scan.name}: n_valid_100ms shape changed by block",
        )
        scalar_valid += sum(values)
        scalar_moment_valid += sum(coarse_values)
    require(
        scalar_valid == native_valid,
        f"{scan.name}: n_valid Zarr chunks do not match native quality",
    )
    require(
        scalar_moment_valid == moment_valid,
        f"{scan.name}: n_valid_100ms Zarr chunks do not match 100 ms quality",
    )

    file_verification = verify_manifest(scan, True)
    return {
        **file_verification,
        "scan": str(scan),
        "scan_id": request["scan_id"],
        "native_bucket_ms": int(request["native_bucket_ms"]),
        "duration_seconds": int(request["duration_seconds"]),
        "native_quality_rows": len(native),
        "moment_quality_rows": len(moments),
        "gap_ranges": len(gaps),
        "arrival_events": len(arrivals),
        "expected_frames": native_expected,
        "valid_frames": native_valid,
        "missing_frames": native_missing,
        "loss_fraction": native_missing / native_expected,
        "duplicates": sum(int(row["duplicate_count"]) for row in native),
        "reordered": sum(int(row["reordered_count"]) for row in native),
        "late": sum(int(row["late_count"]) for row in native),
        "n_valid_shape": native_shape,
        "n_valid_100ms_shape": moment_shape,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scan", action="append", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    args = parser.parse_args()
    if args.output_json.exists():
        raise RuntimeError(f"refusing to overwrite {args.output_json}")
    digest_path = args.output_json.with_suffix(args.output_json.suffix + ".sha256")
    if digest_path.exists():
        raise RuntimeError(f"refusing to overwrite {digest_path}")
    scans = [verify_scan(scan) for scan in args.scan]
    result = {
        "format": "T510_STAGE35_LIVE_DATASET_VERIFY_V1",
        "schema_version": 1,
        "status": "PASS",
        "scan_count": len(scans),
        "scans": scans,
    }
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    digest_path.write_text(
        f"{sha256_file(args.output_json)}  {args.output_json.name}\n", encoding="ascii"
    )
    print(
        f"STAGE35_LIVE_VERIFY_PASS scans={len(scans)} "
        f"output={args.output_json} sha256={sha256_file(args.output_json)}"
    )


if __name__ == "__main__":
    main()
