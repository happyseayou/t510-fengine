#!/usr/bin/env python3
"""Independent numeric verifier for Stage 35 full-band cross-correlation Zarr.

This reader deliberately does not use the explorer server.  It reads the
uncompressed Zarr v2 chunks directly, checks every stored second, and proves
that the ten weighted 100 ms focus products merge back to the 1 s full-band
product at the same bins.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

import numpy as np


DATA_ROOT = Path("/var/lib/t510/stage35").resolve()
PAIRS = tuple((a, b) for a in range(8) for b in range(a + 1, 8))


def fixed_scan(value: Path) -> Path:
    path = value.resolve(strict=True)
    if DATA_ROOT not in path.parents or not path.is_dir():
        raise ValueError(f"scan escapes the fixed Stage 35 data root: {path}")
    return path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json_new(path: Path, value: Any) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640)
    try:
        payload = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
        os.write(fd, payload)
        os.fsync(fd)
    finally:
        os.close(fd)


def zmeta(zarr: Path, name: str, shape: list[int], chunks: list[int], dtype: str) -> None:
    actual = json.loads((zarr / name / ".zarray").read_text())
    if (actual.get("zarr_format") != 2 or actual.get("shape") != shape or
            actual.get("chunks") != chunks or actual.get("dtype") != dtype or
            actual.get("compressor") is not None or actual.get("order") != "C"):
        raise ValueError(f"{name} Zarr v2 contract mismatch: {actual}")


def verify_scan(scan: Path) -> dict[str, Any]:
    manifest_path = scan / "dataset_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("complete") is not True:
        raise ValueError(f"{scan.name}: manifest is not complete")
    expected_digest = (scan / "dataset_manifest.sha256").read_text().split()[0]
    if sha256_file(manifest_path) != expected_digest:
        raise ValueError(f"{scan.name}: manifest SHA-256 mismatch")
    for record in manifest["files"]:
        path = scan / record["path"]
        if (not path.is_file() or path.stat().st_size != int(record["bytes"]) or
                sha256_file(path) != record["sha256"]):
            raise ValueError(f"{scan.name}: manifest file mismatch: {path}")

    zarr = scan / "xcorr.zarr"
    attrs = json.loads((zarr / ".zattrs").read_text())
    if attrs.get("complete") is not True or attrs.get("visibility_definition") != "mean(Xa*conj(Xb))":
        raise ValueError(f"{scan.name}: root attributes do not freeze the visibility convention")
    seconds = int(json.loads((zarr / "mean_cross_visibility_count2" / ".zarray").read_text())["shape"][0])
    focus = np.fromfile(zarr / "focus_global_bin" / "0", dtype="<u2").astype(np.int64)
    pair_index = np.fromfile(zarr / "pair_index" / "0.0", dtype="u1").reshape(28, 2)
    if pair_index.tolist() != [list(pair) for pair in PAIRS]:
        raise ValueError(f"{scan.name}: pair ordering changed")
    zmeta(zarr, "mean_auto_power_count2", [seconds, 8, 4096], [1, 8, 256], "<f8")
    zmeta(zarr, "mean_cross_visibility_count2", [seconds, 28, 4096], [1, 28, 256], "<c16")
    zmeta(zarr, "focus_mean_auto_power_count2", [seconds * 10, 8, len(focus)],
          [10, 8, len(focus)], "<f8")
    zmeta(zarr, "focus_mean_cross_visibility_count2", [seconds * 10, 28, len(focus)],
          [10, 28, len(focus)], "<c16")

    max_focus_merge_abs = 0.0
    max_gamma = 0.0
    full_values_checked = 0
    focus_values_checked = 0
    prior_end = None
    by_block: dict[int, list[tuple[int, int]]] = {}
    for focus_index, global_bin in enumerate(focus.tolist()):
        by_block.setdefault(global_bin // 256, []).append((focus_index, global_bin % 256))
    for second in range(seconds):
        nvalid = np.fromfile(zarr / "n_valid" / f"{second}.0", dtype="<u8")
        if nvalid.shape != (16,) or not np.all(nvalid == 78_125):
            raise ValueError(f"{scan.name}: second {second} full-band n_valid mismatch")
        start = int(np.fromfile(zarr / "sample0_start" / str(second), dtype="<u8")[0])
        end = int(np.fromfile(zarr / "sample0_end" / str(second), dtype="<u8")[0])
        if end - start != 320_000_000 or (prior_end is not None and start != prior_end):
            raise ValueError(f"{scan.name}: second {second} sample0 boundary mismatch")
        prior_end = end

        focus_cross = np.fromfile(
            zarr / "focus_mean_cross_visibility_count2" / f"{second}.0.0", dtype="<c16"
        ).reshape(10, 28, len(focus))
        focus_auto = np.fromfile(
            zarr / "focus_mean_auto_power_count2" / f"{second}.0.0", dtype="<f8"
        ).reshape(10, 8, len(focus))
        focus_n = np.fromfile(zarr / "focus_n_valid" / f"{second}.0", dtype="<u8").reshape(10, 16)
        if not np.all(focus_n == focus_n[:, :1]) or int(focus_n[:, 0].sum()) != 78_125:
            raise ValueError(f"{scan.name}: second {second} focus n_valid mismatch")
        if not np.all(np.isfinite(focus_cross)) or not np.all(np.isfinite(focus_auto)) or np.any(focus_auto < 0):
            raise ValueError(f"{scan.name}: second {second} has invalid focus values")
        weights = focus_n[:, 0].astype(np.float64)
        merged_cross = np.sum(focus_cross * weights[:, None, None], axis=0) / weights.sum()
        merged_auto = np.sum(focus_auto * weights[:, None, None], axis=0) / weights.sum()
        for pair_number, (left, right) in enumerate(PAIRS):
            denominator = np.sqrt(np.maximum(focus_auto[:, left] * focus_auto[:, right],
                                             np.finfo(float).tiny))
            max_gamma = max(max_gamma, float(np.max(np.abs(focus_cross[:, pair_number]) / denominator)))
        focus_values_checked += int(focus_cross.size + focus_auto.size)

        for block in range(16):
            full_cross = np.fromfile(
                zarr / "mean_cross_visibility_count2" / f"{second}.0.{block}", dtype="<c16"
            ).reshape(28, 256)
            full_auto = np.fromfile(
                zarr / "mean_auto_power_count2" / f"{second}.0.{block}", dtype="<f8"
            ).reshape(8, 256)
            if not np.all(np.isfinite(full_cross)) or not np.all(np.isfinite(full_auto)) or np.any(full_auto < 0):
                raise ValueError(f"{scan.name}: second {second}, block {block} has invalid full-band values")
            for pair_number, (left, right) in enumerate(PAIRS):
                denominator = np.sqrt(np.maximum(full_auto[left] * full_auto[right], np.finfo(float).tiny))
                max_gamma = max(max_gamma, float(np.max(np.abs(full_cross[pair_number]) / denominator)))
            for focus_index, local_bin in by_block.get(block, []):
                cross_error = float(np.max(np.abs(full_cross[:, local_bin] - merged_cross[:, focus_index])))
                auto_error = float(np.max(np.abs(full_auto[:, local_bin] - merged_auto[:, focus_index])))
                max_focus_merge_abs = max(max_focus_merge_abs, cross_error, auto_error)
                scale = max(float(np.max(np.abs(full_cross[:, local_bin]))),
                            float(np.max(np.abs(full_auto[:, local_bin]))), 1.0)
                if max(cross_error, auto_error) > 1e-10 * scale + 1e-7:
                    raise ValueError(f"{scan.name}: 100 ms -> 1 s merge mismatch at second {second}, bin {block * 256 + local_bin}")
            full_values_checked += int(full_cross.size + full_auto.size)
    if max_gamma > 1.0 + 2e-12:
        raise ValueError(f"{scan.name}: Cauchy bound violated, max |gamma|={max_gamma}")
    return {
        "scan": str(scan), "seconds": seconds, "focus_bins": focus.tolist(),
        "full_values_checked": full_values_checked, "focus_values_checked": focus_values_checked,
        "max_abs_focus_merge_error_count2": max_focus_merge_abs,
        "max_normalized_correlation_amplitude": max_gamma,
        "pair_order": [list(pair) for pair in PAIRS],
        "visibility_definition": "mean(Xa*conj(Xb))",
        "zarr_v2_uncompressed_interoperability": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scan", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    results = [verify_scan(fixed_scan(path)) for path in args.scan]
    write_json_new(args.output, {
        "format": "T510_CROSSCORRELATION_NUMERIC_VERIFY_V1", "status": "PASS",
        "scan_count": len(results), "scans": results,
        "notes": [
            "Re/Im are checked separately and |V| is not used as a zero-visibility significance test.",
            "The 100 ms merge is weighted by exact valid spectra because 32 MHz/4096 alternates 7813 and 7812 frames.",
        ],
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
