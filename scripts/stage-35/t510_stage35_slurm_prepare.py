#!/usr/bin/env python3
"""Prepare and independently verify an already streamed Stage 35 input tree."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any


DATASETS = (
    "stage35-40-360mhz-v2-20260902-1225-self-a-spec-scan-900s",
    "stage35-40-360mhz-v2-20260902-1225-self-b-spec-scan-900s",
    "stage35-40-360mhz-v2-20260902-1225-self-c-spec-scan-900s",
    "stage35-40-360mhz-v2-20260902-1225-self-a-time-pre-30s",
    "stage35-40-360mhz-v2-20260902-1225-self-a-time-post-30s",
    "stage35-40-360mhz-v2-20260902-1225-self-b-time-pre-30s",
    "stage35-40-360mhz-v2-20260902-1225-self-b-time-post-30s",
    "stage35-40-360mhz-v2-20260902-1225-self-c-time-pre-30s",
    "stage35-40-360mhz-v2-20260902-1225-self-c-time-post-30s",
)


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def verify_rows(rows: list[tuple[str, int, str]]) -> list[str]:
    errors = []
    for name, size, expected in rows:
        path = Path(name)
        if not path.is_file():
            errors.append(f"missing:{path}"); continue
        if path.stat().st_size != size:
            errors.append(f"size:{path}"); continue
        if digest(path) != expected:
            errors.append(f"sha256:{path}")
    return errors


def replace_root(value: Any, source: str, destination: str) -> Any:
    if isinstance(value, str):
        return destination + value[len(source):] if value.startswith(source) else value
    if isinstance(value, list):
        return [replace_root(item, source, destination) for item in value]
    if isinstance(value, dict):
        return {key: replace_root(item, source, destination) for key, item in value.items()}
    return value


def write_json(path: Path, value: Any) -> None:
    partial = path.with_name(path.name + ".partial")
    partial.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    with partial.open("rb") as stream:
        os.fsync(stream.fileno())
    partial.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--analysis-dir", required=True)
    parser.add_argument("--workers", type=int, default=96)
    args = parser.parse_args()
    input_root = args.work / "input"
    all_rows: list[tuple[str, int, str]] = []
    for dataset in DATASETS:
        root = input_root / dataset
        manifest = json.loads((root / "dataset_manifest.json").read_text())
        if manifest.get("complete") is not True:
            raise RuntimeError(f"input manifest is not complete: {dataset}")
        for row in manifest["files"]:
            relative = Path(row["path"])
            if relative.is_absolute() or ".." in relative.parts:
                raise RuntimeError(f"unsafe input path: {relative}")
            all_rows.append((str(root / relative), int(row["bytes"]), row["sha256"]))
    groups = [[] for _ in range(args.workers)]
    for index, row in enumerate(all_rows):
        groups[index % args.workers].append(row)
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        failures = [error for result in pool.map(verify_rows, groups) for error in result]
    if failures:
        raise RuntimeError(f"input identity verification failed: {failures[:20]}")
    source = json.loads((args.work / "source_analysis_config.json").read_text())
    config = replace_root(source, "/var/lib/t510/stage35", str(input_root))
    config["output_root"] = str(args.work / args.analysis_dir)
    config["parallel_workers"] = 1
    write_json(args.work / "analysis_config.json", config)
    Path(config["output_root"]).mkdir(parents=True, exist_ok=True)
    write_json(args.work / "input_transfer_verification.json", {
        "format": "T510_STAGE35_CLUSTER_INPUT_VERIFY_V1", "status": "PASS",
        "files": len(all_rows), "bytes": sum(row[1] for row in all_rows),
        "workers": args.workers, "dataset_count": len(DATASETS),
    })
    (args.work / "STAGED").touch()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
