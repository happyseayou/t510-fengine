#!/usr/bin/env python3
"""Convert one verified 900 s TIME_ONLY CSV into mmap-friendly read-only arrays."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path

import numpy as np


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--label", default="TIME-900s")
    args = parser.parse_args()

    dataset = args.dataset.resolve(strict=True)
    manifest_path = dataset / "dataset_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    request = manifest.get("request", {})
    duration = int(request.get("duration_seconds", 0))
    if manifest.get("format") != "T510_TIME_CAPTURE_V1" or not manifest.get("complete"):
        raise RuntimeError("TIME_ONLY dataset manifest is not complete")
    if int(manifest.get("schema_version", 0)) < 2:
        raise RuntimeError("TIME_ONLY long dataset does not contain direct mean_power_adu2")
    if duration != 900 or int(manifest.get("native_bucket_ms", 0)) != 10:
        raise RuntimeError("TIME_ONLY long dataset must be exactly 900 s at 10 ms cadence")

    source = dataset / "time_10ms.csv"
    identity = next((row for row in manifest["files"] if row["path"] == source.name), None)
    if identity is None or source.stat().st_size != int(identity["bytes"]):
        raise RuntimeError("time_10ms.csv is missing or has the wrong size")
    if sha256_file(source) != identity["sha256"]:
        raise RuntimeError("time_10ms.csv SHA-256 does not match its sealed manifest")

    points, lanes = duration * 100, 8
    output = args.output
    output.mkdir(parents=True, exist_ok=False)
    arrays = {
        "mean_i_adu": np.lib.format.open_memmap(
            output / "mean_i_adu.npy", mode="w+", dtype="<f8", shape=(points, lanes)
        ),
        "mean_q_adu": np.lib.format.open_memmap(
            output / "mean_q_adu.npy", mode="w+", dtype="<f8", shape=(points, lanes)
        ),
        "mean_power_adu2": np.lib.format.open_memmap(
            output / "mean_power_adu2.npy", mode="w+", dtype="<f8", shape=(points, lanes)
        ),
        "n_valid": np.lib.format.open_memmap(
            output / "n_valid.npy", mode="w+", dtype="<u8", shape=(points, lanes)
        ),
    }
    seen = np.zeros((points, lanes), dtype=np.bool_)
    with source.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            bucket, lane = int(row["bucket"]), int(row["lane"])
            if not (0 <= bucket < points and 0 <= lane < lanes) or seen[bucket, lane]:
                raise RuntimeError(f"invalid or duplicate TIME row bucket={bucket} lane={lane}")
            values = (
                float(row["mean_i_adu"]), float(row["mean_q_adu"]),
                float(row["mean_power_adu2"]), int(row["samples"]),
            )
            if not all(math.isfinite(value) for value in values[:3]) or values[2] < 0 or values[3] <= 0:
                raise RuntimeError(f"invalid TIME values bucket={bucket} lane={lane}")
            arrays["mean_i_adu"][bucket, lane] = values[0]
            arrays["mean_q_adu"][bucket, lane] = values[1]
            arrays["mean_power_adu2"][bucket, lane] = values[2]
            arrays["n_valid"][bucket, lane] = values[3]
            seen[bucket, lane] = True
    if not np.all(seen):
        raise RuntimeError(f"TIME array coverage incomplete: {int(np.count_nonzero(~seen))} rows missing")
    for array in arrays.values():
        array.flush()

    array_identity = {}
    for name in arrays:
        path = output / f"{name}.npy"
        array_identity[name] = {
            "path": str(path), "bytes": path.stat().st_size, "sha256": sha256_file(path),
            "dtype": str(np.load(path, mmap_mode="r").dtype), "shape": [points, lanes],
        }
        path.chmod(0o444)
    result = {
        "format": "T510_TIME_CAPTURE_LONG_ARRAYS_V1",
        "label": args.label,
        "duration_seconds": duration,
        "base_cadence_ms": 10,
        "points": points,
        "lanes": lanes,
        "source_dataset": str(dataset),
        "source_manifest": {"path": str(manifest_path), "sha256": sha256_file(manifest_path)},
        "source_time_10ms": {"path": str(source), "sha256": identity["sha256"]},
        "arrays": array_identity,
        "meaning": (
            "每个10 ms点由该时间内全部有效post-DDC IQ16样点直接累加得到；"
            "mean_power_adu2是mean(I²+Q²)，不是RMS。"
        ),
    }
    index = output / "time_long_index.json"
    index.write_text(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    index.chmod(0o444)
    output.chmod(0o555)
    print(json.dumps({"status": "PASS", "index": str(index), "sha256": sha256_file(index)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
