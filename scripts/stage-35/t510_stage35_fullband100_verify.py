#!/usr/bin/env python3
"""Independently verify Stage 35 full-band 100 ms products and their 1 s merge."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import numpy as np


ARRAYS = {
    "mean_auto_power_count2": ("<f8", [1, 8, 256]),
    "mean_cross_visibility_count2": ("<c16", [1, 28, 256]),
    "n_valid": ("<u8", [1, 16]),
    "mean_auto_power_count2_100ms": ("<f8", [10, 8, 256]),
    "mean_cross_visibility_count2_100ms": ("<c16", [10, 28, 256]),
    "n_valid_100ms": ("<u8", [10, 16]),
}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json_new(path: Path, value: Any) -> None:
    payload = (json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640)
    try:
        os.write(fd, payload)
        os.fsync(fd)
    finally:
        os.close(fd)


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def metadata(zarr: Path, name: str, duration: int) -> dict[str, Any]:
    value = load_json(zarr / name / ".zarray")
    dtype, chunks = ARRAYS[name]
    rows = duration * (10 if name.endswith("_100ms") else 1)
    trailing = [16] if name.startswith("n_valid") else ([8, 4096] if "auto" in name else [28, 4096])
    expected_shape = [rows, *trailing]
    if value.get("shape") != expected_shape or value.get("chunks") != chunks or value.get("dtype") != dtype:
        raise RuntimeError(f"{name} metadata mismatch: {value}")
    if value.get("compressor") is not None or value.get("order") != "C":
        raise RuntimeError(f"{name} must be uncompressed C-order Zarr v2")
    return value


def read(path: Path, dtype: str, shape: tuple[int, ...]) -> np.ndarray:
    value = np.fromfile(path, dtype=dtype)
    expected = int(np.prod(shape))
    if value.size != expected:
        raise RuntimeError(f"{path}: found {value.size} values, expected {expected}")
    return value.reshape(shape)


def update_error(summary: dict[str, float | int], actual: np.ndarray, expected: np.ndarray) -> None:
    difference = np.abs(actual - expected)
    absolute = float(np.max(difference))
    scale = np.maximum(np.abs(expected), 1.0)
    relative = float(np.max(difference / scale))
    summary["comparisons"] = int(summary["comparisons"]) + actual.size
    summary["maximum_absolute_error"] = max(float(summary["maximum_absolute_error"]), absolute)
    summary["maximum_relative_error"] = max(float(summary["maximum_relative_error"]), relative)
    if not np.allclose(actual, expected, rtol=2e-13, atol=1e-10):
        raise RuntimeError(f"100 ms to 1 s merge mismatch: max_abs={absolute}, max_rel={relative}")


def verify(scan: Path, duration: int) -> dict[str, Any]:
    zarr = scan / "xcorr.zarr"
    attrs = load_json(zarr / ".zattrs")
    if attrs.get("complete") is not True or attrs.get("save_fullband_100ms") is not True:
        raise RuntimeError(f"dataset is not a sealed full-band 100 ms capture: {attrs}")
    for name in ARRAYS:
        metadata(zarr, name, duration)
    for name, shape, dtype in (
        ("sample0_start", [duration], "<u8"),
        ("sample0_end", [duration], "<u8"),
        ("sample0_start_100ms", [duration * 10], "<u8"),
        ("sample0_end_100ms", [duration * 10], "<u8"),
    ):
        meta = load_json(zarr / name / ".zarray")
        chunk = [10] if name.endswith("_100ms") else [1]
        if meta.get("shape") != shape or meta.get("chunks") != chunk or meta.get("dtype") != dtype:
            raise RuntimeError(f"{name} metadata mismatch: {meta}")

    pair_index = read(zarr / "pair_index" / "0.0", "|u1", (28, 2))
    expected_pairs = np.asarray([(a, b) for a in range(8) for b in range(a + 1, 8)], dtype=np.uint8)
    if not np.array_equal(pair_index, expected_pairs):
        raise RuntimeError("pair ordering is not (0,1),(0,2),…,(6,7)")
    global_bins = read(zarr / "global_bin" / "0", "<u2", (4096,))
    if not np.array_equal(global_bins, np.arange(4096, dtype=np.uint16)):
        raise RuntimeError("global_bin coordinate is not 0..4095")
    focus_bins = np.fromfile(zarr / "focus_global_bin" / "0", dtype="<u2")
    if not 1 <= focus_bins.size <= 32 or len(set(focus_bins.tolist())) != focus_bins.size:
        raise RuntimeError("focus-bin coordinate is invalid")

    ledger = [json.loads(line) for line in (scan / "quality_ledger.jsonl").read_text().splitlines() if line]
    ledger100 = [json.loads(line) for line in (scan / "quality_ledger_100ms.jsonl").read_text().splitlines() if line]
    if len(ledger) != duration or len(ledger100) != duration * 10:
        raise RuntimeError("quality-ledger row count mismatch")
    if any(not row.get("complete") or any(row.get("ring_drops", [])) for row in ledger + ledger100):
        raise RuntimeError("quality ledger contains an incomplete row or ring drop")

    error = {"comparisons": 0, "maximum_absolute_error": 0.0, "maximum_relative_error": 0.0}
    focus_error = {"comparisons": 0, "maximum_absolute_error": 0.0, "maximum_relative_error": 0.0}
    sample0_origin = None
    n100_min, n100_max = 2**63 - 1, 0
    for second in range(duration):
        n100 = read(zarr / "n_valid_100ms" / f"{second}.0", "<u8", (10, 16))
        n1 = read(zarr / "n_valid" / f"{second}.0", "<u8", (16,))
        if not np.all(n100 == n100[:, :1]) or not np.all(n1 == n1[0]):
            raise RuntimeError(f"n_valid differs among sixteen blocks at second {second}")
        weights = n100[:, 0]
        if int(n1[0]) != 78_125 or int(np.sum(weights, dtype=np.uint64)) != int(n1[0]):
            raise RuntimeError(f"frame conservation failed at second {second}")
        n100_min = min(n100_min, int(np.min(weights)))
        n100_max = max(n100_max, int(np.max(weights)))
        starts100 = read(zarr / "sample0_start_100ms" / str(second), "<u8", (10,))
        ends100 = read(zarr / "sample0_end_100ms" / str(second), "<u8", (10,))
        start1 = int(read(zarr / "sample0_start" / str(second), "<u8", (1,))[0])
        end1 = int(read(zarr / "sample0_end" / str(second), "<u8", (1,))[0])
        if sample0_origin is None:
            sample0_origin = start1
        expected_start = int(sample0_origin) + second * 320_000_000
        if start1 != expected_start or end1 != expected_start + 320_000_000:
            raise RuntimeError(f"1 s sample0 interval mismatch at second {second}")
        expected100 = expected_start + np.arange(10, dtype=np.uint64) * 32_000_000
        if not np.array_equal(starts100, expected100) or not np.array_equal(ends100, expected100 + 32_000_000):
            raise RuntimeError(f"100 ms sample0 interval mismatch at second {second}")

        focus_auto = read(zarr / "focus_mean_auto_power_count2" / f"{second}.0.0", "<f8", (10, 8, focus_bins.size))
        focus_cross = read(zarr / "focus_mean_cross_visibility_count2" / f"{second}.0.0", "<c16", (10, 28, focus_bins.size))
        for block in range(16):
            auto100 = read(zarr / "mean_auto_power_count2_100ms" / f"{second}.0.{block}", "<f8", (10, 8, 256))
            cross100 = read(zarr / "mean_cross_visibility_count2_100ms" / f"{second}.0.{block}", "<c16", (10, 28, 256))
            auto1 = read(zarr / "mean_auto_power_count2" / f"{second}.0.{block}", "<f8", (8, 256))
            cross1 = read(zarr / "mean_cross_visibility_count2" / f"{second}.0.{block}", "<c16", (28, 256))
            divisor = float(np.sum(weights, dtype=np.uint64))
            merged_auto = np.sum(auto100 * weights[:, None, None], axis=0) / divisor
            merged_cross = np.sum(cross100 * weights[:, None, None], axis=0) / divisor
            update_error(error, merged_auto, auto1)
            update_error(error, merged_cross, cross1)
            in_block = np.flatnonzero((focus_bins // 256) == block)
            if in_block.size:
                local = (focus_bins[in_block] % 256).astype(int)
                update_error(focus_error, auto100[:, :, local],
                             focus_auto[:, :, in_block])
                update_error(focus_error, cross100[:, :, local],
                             focus_cross[:, :, in_block])

    expected_files = {
        "mean_auto_power_count2": duration * 16,
        "mean_cross_visibility_count2": duration * 16,
        "mean_auto_power_count2_100ms": duration * 16,
        "mean_cross_visibility_count2_100ms": duration * 16,
        "n_valid": duration,
        "n_valid_100ms": duration,
    }
    for name, expected in expected_files.items():
        chunks = [p for p in (zarr / name).iterdir() if not p.name.startswith(".")]
        if len(chunks) != expected:
            raise RuntimeError(f"{name} has {len(chunks)} chunks, expected {expected}")
    return {
        "status": "PASS", "scan": str(scan), "duration_seconds": duration,
        "fullband_100ms_to_1s": error, "focus_to_fullband_100ms": focus_error,
        "n_valid_100ms": {"minimum": n100_min, "maximum": n100_max,
                          "per_second_sum": 78_125},
        "pair_order": expected_pairs.tolist(), "global_bins": 4096,
        "quality_rows": {"one_second": len(ledger), "one_hundred_ms": len(ledger100)},
        "phase_wrap_rule": "Allan verification uses complex-vector differences, not phase-angle subtraction",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scan", type=Path, required=True)
    parser.add_argument("--duration-seconds", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.scan.resolve(strict=True), args.duration_seconds)
    write_json_new(args.output, result)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
