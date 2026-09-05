#!/usr/bin/env python3
"""Freeze full-band cross-correlation and dynamic-spectrum explorer summaries."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq


DATA_ROOT = Path("/var/lib/t510/stage35").resolve()
PAIRS = tuple((a, b) for a in range(8) for b in range(a + 1, 8))
INTEGRATION_TAUS = (2, 4, 15, 30)
ALLAN_TAUS = (1, 2, 4, 8, 15, 30)
ACF_LAGS = (0, 1, 2, 4, 8, 15, 30)
BOOTSTRAP_REPLICATES = 512
BOOTSTRAP_BLOCK_SECONDS = 30


def fixed_path(value: str | Path) -> Path:
    path = Path(value).resolve(strict=True)
    if DATA_ROOT not in path.parents:
        raise ValueError(f"path escapes Stage 35 data root: {path}")
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
        data = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)


def bh_qvalues(pvalues: np.ndarray) -> np.ndarray:
    flat = np.asarray(pvalues, dtype=np.float64).ravel()
    order = np.argsort(flat)
    ranked = flat[order]
    adjusted = ranked * len(flat) / np.arange(1, len(flat) + 1)
    adjusted = np.minimum.accumulate(adjusted[::-1])[::-1]
    output = np.empty_like(flat)
    output[order] = np.minimum(adjusted, 1.0)
    return output.reshape(pvalues.shape)


def nonoverlap_std(values: np.ndarray, width: int) -> np.ndarray:
    count = values.shape[0] // width
    blocks = values[: count * width].reshape(count, width, *values.shape[1:]).mean(axis=1)
    return np.std(blocks, axis=0, ddof=1)


def overlap_adev(values: np.ndarray, width: int) -> np.ndarray:
    cumulative = np.concatenate((np.zeros((1,) + values.shape[1:], dtype=np.float64),
                                 np.cumsum(values, axis=0, dtype=np.float64)), axis=0)
    means = (cumulative[width:] - cumulative[:-width]) / width
    difference = means[width:] - means[:-width]
    return np.sqrt(.5 * np.mean(difference * difference, axis=0))


def acf(values: np.ndarray, lag: int) -> np.ndarray:
    centered = values - np.mean(values, axis=0, keepdims=True)
    variance = np.mean(centered * centered, axis=0)
    if lag == 0:
        return np.where(variance > 0, 1.0, np.nan)
    return np.mean(centered[:-lag] * centered[lag:], axis=0) / np.maximum(
        variance, np.finfo(np.float64).tiny
    )


def bootstrap_mean(values: np.ndarray, seed: int) -> tuple[np.ndarray, ...]:
    width = BOOTSTRAP_BLOCK_SECONDS
    count = values.shape[0] // width
    block_means = values[: count * width].reshape(count, width, -1).mean(axis=1)
    rng = np.random.default_rng(seed)
    weights = np.empty((BOOTSTRAP_REPLICATES, count), dtype=np.float64)
    for index in range(BOOTSTRAP_REPLICATES):
        weights[index] = np.bincount(rng.integers(0, count, size=count), minlength=count) / count
    replicates = weights @ block_means
    observed = np.mean(block_means, axis=0)
    low, high = np.quantile(replicates, (.005, .995), axis=0)
    standard_error = np.std(block_means, axis=0, ddof=1) / math.sqrt(count)
    zscore = np.abs(observed) / np.maximum(standard_error, np.finfo(float).tiny)
    pvalue = np.fromiter(
        (math.erfc(float(value) / math.sqrt(2.0)) for value in zscore),
        dtype=np.float64,
        count=zscore.size,
    )
    shape = values.shape[1:]
    return low.reshape(shape), high.reshape(shape), pvalue.reshape(shape)


def read_cross_block(zarr: Path, block: int, seconds: int) -> tuple[np.ndarray, np.ndarray]:
    visibility = np.empty((seconds, 28, 256), dtype=np.complex128)
    auto = np.empty((seconds, 8, 256), dtype=np.float64)
    for second in range(seconds):
        visibility[second] = np.fromfile(
            zarr / "mean_cross_visibility_count2" / f"{second}.0.{block}", dtype="<c16"
        ).reshape(28, 256)
        auto[second] = np.fromfile(
            zarr / "mean_auto_power_count2" / f"{second}.0.{block}", dtype="<f8"
        ).reshape(8, 256)
    if not np.all(np.isfinite(visibility)) or not np.all(np.isfinite(auto)):
        raise ValueError(f"non-finite cross-correlation values in block {block}")
    return visibility, auto


def analyze_cross_scan(scan: str, root: Path, output: Path) -> dict[str, Any]:
    zarr = root / "xcorr.zarr"
    attrs = json.loads((zarr / ".zattrs").read_text())
    if attrs.get("complete") is not True:
        raise ValueError(f"{scan} cross-correlation Zarr is not complete")
    meta = json.loads((zarr / "mean_cross_visibility_count2" / ".zarray").read_text())
    seconds = int(meta["shape"][0])
    if meta["shape"][1:] != [28, 4096] or meta["chunks"] != [1, 28, 256]:
        raise ValueError(f"{scan} cross Zarr shape/chunk contract changed")
    scan_root = output / "cross_summary" / f"scan={scan}"
    scan_root.mkdir(parents=True)
    pending: list[dict[str, np.ndarray]] = []
    p_re = np.empty((28, 4096), dtype=np.float64)
    p_im = np.empty_like(p_re)
    for block in range(16):
        visibility, auto = read_cross_block(zarr, block, seconds)
        real, imag = visibility.real, visibility.imag
        mean_re, mean_im = np.mean(real, axis=0), np.mean(imag, axis=0)
        std_re, std_im = np.std(real, axis=0, ddof=1), np.std(imag, axis=0, ddof=1)
        integration_re = np.stack([nonoverlap_std(real, tau) for tau in INTEGRATION_TAUS], axis=2)
        integration_im = np.stack([nonoverlap_std(imag, tau) for tau in INTEGRATION_TAUS], axis=2)
        allan_re = np.stack([overlap_adev(real, tau) for tau in ALLAN_TAUS], axis=2)
        allan_im = np.stack([overlap_adev(imag, tau) for tau in ALLAN_TAUS], axis=2)
        acf_re = np.stack([acf(real, lag) for lag in ACF_LAGS], axis=2)
        acf_im = np.stack([acf(imag, lag) for lag in ACF_LAGS], axis=2)
        window = np.hanning(seconds)[:, None, None]
        psd_re = np.abs(np.fft.rfft((real - mean_re) * window, axis=0)) ** 2
        psd_im = np.abs(np.fft.rfft((imag - mean_im) * window, axis=0)) ** 2
        frequency = np.fft.rfftfreq(seconds, 1.0)
        low = (frequency > 0) & (frequency <= .05)
        positive = frequency > 0
        low_fraction_re = np.sum(psd_re[low], axis=0) / np.maximum(np.sum(psd_re[positive], axis=0), np.finfo(float).tiny)
        low_fraction_im = np.sum(psd_im[low], axis=0) / np.maximum(np.sum(psd_im[positive], axis=0), np.finfo(float).tiny)
        boot_re_low, boot_re_high, block_p_re = bootstrap_mean(real, 35000 + block)
        boot_im_low, boot_im_high, block_p_im = bootstrap_mean(imag, 36000 + block)
        p_re[:, block * 256:(block + 1) * 256] = block_p_re
        p_im[:, block * 256:(block + 1) * 256] = block_p_im
        mean_gamma = np.mean(np.abs(visibility) / np.sqrt(np.maximum(
            np.stack([auto[:, pair[0]] * auto[:, pair[1]] for pair in PAIRS], axis=1),
            np.finfo(float).tiny,
        )), axis=0)
        pending.append({
            "mean_re": mean_re, "mean_im": mean_im, "std_re": std_re, "std_im": std_im,
            "integration_re": integration_re, "integration_im": integration_im,
            "allan_re": allan_re, "allan_im": allan_im, "acf_re": acf_re, "acf_im": acf_im,
            "psd_low_re": low_fraction_re, "psd_low_im": low_fraction_im,
            "boot_re_low": boot_re_low, "boot_re_high": boot_re_high,
            "boot_im_low": boot_im_low, "boot_im_high": boot_im_high,
            "mean_gamma": mean_gamma,
        })
    q_re, q_im = bh_qvalues(p_re), bh_qvalues(p_im)
    significant_re = significant_im = 0
    for block, arrays in enumerate(pending):
        rows: dict[str, Any] = {
            "scan": [], "pair_index": [], "adc_a": [], "adc_b": [], "global_bin": [],
            "mean_re_count2": [], "mean_im_count2": [], "std_re_count2": [], "std_im_count2": [],
            "mean_gamma": [], "integration_std_re_count2": [], "integration_std_im_count2": [],
            "allan_re_count2": [], "allan_im_count2": [], "acf_re": [], "acf_im": [],
            "psd_low_frequency_fraction_re": [], "psd_low_frequency_fraction_im": [],
            "bootstrap_re_ci_low_count2": [], "bootstrap_re_ci_high_count2": [],
            "bootstrap_im_ci_low_count2": [], "bootstrap_im_ci_high_count2": [],
            "block_mean_p_re": [], "block_mean_p_im": [], "bh_q_re": [], "bh_q_im": [],
            "bh_q01_significant_re": [], "bh_q01_significant_im": [],
        }
        for pair_index, pair in enumerate(PAIRS):
            for local in range(256):
                global_bin = block * 256 + local
                rows["scan"].append(scan); rows["pair_index"].append(pair_index)
                rows["adc_a"].append(pair[0]); rows["adc_b"].append(pair[1]); rows["global_bin"].append(global_bin)
                for name in ("mean_re", "mean_im", "std_re", "std_im", "mean_gamma",
                             "psd_low_re", "psd_low_im", "boot_re_low", "boot_re_high",
                             "boot_im_low", "boot_im_high"):
                    target = {
                        "mean_re": "mean_re_count2", "mean_im": "mean_im_count2",
                        "std_re": "std_re_count2", "std_im": "std_im_count2",
                        "psd_low_re": "psd_low_frequency_fraction_re",
                        "psd_low_im": "psd_low_frequency_fraction_im",
                        "boot_re_low": "bootstrap_re_ci_low_count2",
                        "boot_re_high": "bootstrap_re_ci_high_count2",
                        "boot_im_low": "bootstrap_im_ci_low_count2",
                        "boot_im_high": "bootstrap_im_ci_high_count2",
                        "mean_gamma": "mean_gamma",
                    }[name]
                    rows[target].append(float(arrays[name][pair_index, local]))
                for name, target in (("integration_re", "integration_std_re_count2"),
                                     ("integration_im", "integration_std_im_count2"),
                                     ("allan_re", "allan_re_count2"), ("allan_im", "allan_im_count2"),
                                     ("acf_re", "acf_re"), ("acf_im", "acf_im")):
                    rows[target].append(arrays[name][pair_index, local].tolist())
                pre, pim = p_re[pair_index, global_bin], p_im[pair_index, global_bin]
                qre, qim = q_re[pair_index, global_bin], q_im[pair_index, global_bin]
                rows["block_mean_p_re"].append(float(pre)); rows["block_mean_p_im"].append(float(pim))
                rows["bh_q_re"].append(float(qre)); rows["bh_q_im"].append(float(qim))
                rows["bh_q01_significant_re"].append(bool(qre <= .01))
                rows["bh_q01_significant_im"].append(bool(qim <= .01))
                significant_re += qre <= .01; significant_im += qim <= .01
        block_root = scan_root / f"block={block:02d}"
        block_root.mkdir()
        pq.write_table(pa.table(rows), block_root / "part.parquet", compression="zstd")
    same = [PAIRS.index(pair) for pair in ((0, 1), (2, 3), (4, 5), (6, 7))]
    all_gamma = np.concatenate([row["mean_gamma"] for row in pending], axis=1)
    cross = [index for index in range(28) if index not in same]
    return {
        "scan": scan, "seconds": seconds, "rows": 28 * 4096,
        "significant_re_bh_q01": int(significant_re),
        "significant_im_bh_q01": int(significant_im),
        "mean_gamma_median": float(np.median(all_gamma)),
        "same_tile_mean_gamma_median": float(np.median(all_gamma[same])),
        "cross_tile_mean_gamma_median": float(np.median(all_gamma[cross])),
        "bootstrap": {"kind": "non-overlapping block bootstrap", "block_seconds": 30,
                      "replicates": BOOTSTRAP_REPLICATES, "ci": .99},
        "multiple_testing": {"method": "Benjamini-Hochberg", "q": .01,
                             "pvalue_source": "two-sided Gaussian block-mean z test using 30 s blocks",
                             "family": "all 28 pairs x 4096 bins, separately for Re and Im"},
    }


def build_dynamic(scan: str, root: Path, output: Path) -> dict[str, Any]:
    linear_path = output / f"dynamic-{scan}-float32.npy"
    linear = np.lib.format.open_memmap(linear_path, mode="w+", dtype="<f4",
                                       shape=(3, 8, 900, 4096))
    for block in range(16):
        for second in range(900):
            chunk = np.fromfile(root / "mean_power_count2" / f"{second}.0.{block}", dtype="<f8").reshape(100, 8, 256)
            target = slice(block * 256, (block + 1) * 256)
            linear[0, :, second, target] = np.min(chunk, axis=0)
            linear[1, :, second, target] = np.mean(chunk, axis=0)
            linear[2, :, second, target] = np.max(chunk, axis=0)
    linear.flush()
    quantized_path = output / f"dynamic-{scan}-uint16.npy"
    quantized = np.lib.format.open_memmap(quantized_path, mode="w+", dtype="<u2",
                                          shape=linear.shape)
    layers = []
    for layer in range(3):
        layer_rows = []
        for adc in range(8):
            values = 10 * np.log10(np.maximum(linear[layer, adc], np.finfo(np.float32).tiny))
            lo, hi = float(np.min(values)), float(np.max(values))
            scale = (hi - lo) / 65535 or 1.0
            quantized[layer, adc] = np.clip(np.rint((values - lo) / scale), 0, 65535)
            layer_rows.append({"adc": adc, "minimum_db": lo, "maximum_db": hi,
                               "scale_db_per_code": scale, "maximum_error_db": scale / 2})
        layers.append(layer_rows)
    quantized.flush()
    del quantized, linear
    linear_path.unlink()
    return {"scan": scan, "path": str(quantized_path), "shape": [3, 8, 900, 4096],
            "layers": layers, "source": str(root),
            "statistics_source": "all native 10 ms float64 power buckets",
            "display_only": True}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    args.output.mkdir(parents=True, exist_ok=False)
    summary = {"format": "T510_STAGE35_EXPLORER_ANALYSIS_V1", "cross": {}, "dynamic": {}}
    for scan, value in sorted(config["xcorr_scans"].items()):
        summary["cross"][scan] = analyze_cross_scan(scan, fixed_path(value), args.output)
    for scan, value in sorted(config["spec_scans"].items()):
        summary["dynamic"][scan] = build_dynamic(scan, fixed_path(value), args.output)
    summary_path = args.output / "explorer_analysis_summary.json"
    write_json_new(summary_path, summary)
    files = []
    for path in sorted(args.output.rglob("*")):
        if path.is_file() and path.name != "explorer_analysis_manifest.json":
            files.append({"path": str(path.relative_to(args.output)), "bytes": path.stat().st_size,
                          "sha256": sha256_file(path)})
    write_json_new(args.output / "explorer_analysis_manifest.json", {
        "format": "T510_STAGE35_EXPLORER_ANALYSIS_MANIFEST_V1", "complete": True,
        "summary": summary, "files": files,
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
