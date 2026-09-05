#!/usr/bin/env python3
"""Full-band Stage 35 S2 offline autocorrelation and time-noise analysis.

The input Zarr v2 arrays are uncompressed and are read one native 256-bin
block at a time.  Every output row retains scan, ADC, and global-bin identity.
The command also provides a persistent queue mode that journals all 48 block
tasks before starting any analysis work.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import platform
import shutil
import sys
import time
import traceback
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq


FORMAT = "T510_STAGE35_S2_ANALYSIS_V1"
ADC_COUNT = 8
BLOCK_COUNT = 16
BLOCK_CHANS = 256
FRAME_TICKS = 4096
SAMPLE_RATE_HZ = 320_000_000
PFB_FRAME_SECONDS = FRAME_TICKS / SAMPLE_RATE_HZ
PFB_POWER_CORRELATIONS = np.array(
    [
        0.00949326424028388,
        0.004929849143528964,
        0.0013901496869103923,
        0.0002524055652463064,
        0.00000884079355811649,
        0.0000002950628595366823,
        0.000000003934676312382962,
    ],
    dtype=np.float64,
)


def unix_ms() -> int:
    return time.time_ns() // 1_000_000


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".partial")
    with partial.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    partial.replace(path)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_config(config: dict[str, Any]) -> None:
    if config.get("format") != "T510_STAGE35_S2_ANALYSIS_CONFIG_V1":
        raise RuntimeError("unexpected analysis config format")
    if len(config.get("scans", [])) != 3 or len(config.get("time_controls", [])) != 6:
        raise RuntimeError("analysis requires three SPEC scans and six TIME controls")
    if float(config.get("native_bucket_s", 0.0)) != 0.01:
        raise RuntimeError("analysis config must retain the formal 10 ms native bucket")
    if [float(x) for x in config.get("integration_seconds", [])] != [2.0, 4.0, 15.0, 30.0]:
        raise RuntimeError("registered integration times changed")


def verify_inputs(config: dict[str, Any]) -> dict[str, Any]:
    queue_root = Path(config["queue_root"])
    queue_manifest = queue_root / "queue_manifest.json"
    actual_queue_sha = sha256_file(queue_manifest)
    if actual_queue_sha != config["queue_manifest_sha256"]:
        raise RuntimeError("queue manifest identity mismatch")
    scans = []
    for scan in config["scans"]:
        path = Path(scan["path"])
        actual = sha256_file(path / "dataset_manifest.json")
        if actual != scan["manifest_sha256"]:
            raise RuntimeError(f"SPEC manifest identity mismatch for {scan['label']}")
        attrs = load_json(path / ".zattrs")
        expected_arrays = {
            "mean_power_count2": ([90000, 8, 4096], [100, 8, 256], "<f8"),
            "n_valid": ([90000, 16], [100, 1], "<u4"),
            "mean_i_count_100ms": ([9000, 8, 4096], [10, 8, 256], "<f8"),
            "mean_q_count_100ms": ([9000, 8, 4096], [10, 8, 256], "<f8"),
            "m2_power_count4_100ms": ([9000, 8, 4096], [10, 8, 256], "<f8"),
            "clip_count_100ms": ([9000, 8, 4096], [10, 8, 256], "<u4"),
            "n_valid_100ms": ([9000, 16], [10, 1], "<u4"),
        }
        for name, (shape, chunks, dtype) in expected_arrays.items():
            meta = load_json(path / name / ".zarray")
            if meta["shape"] != shape or meta["chunks"] != chunks or meta["dtype"] != dtype:
                raise RuntimeError(f"unexpected Zarr contract for {path.name}/{name}")
            if meta.get("compressor") is not None or meta.get("order") != "C":
                raise RuntimeError(f"unsupported Zarr encoding for {path.name}/{name}")
        scans.append({"label": scan["label"], "scan_id": attrs["scan_id"], "manifest_sha256": actual})
    controls = []
    for control in config["time_controls"]:
        path = Path(control["path"])
        actual = sha256_file(path / "dataset_manifest.json")
        if actual != control["manifest_sha256"]:
            raise RuntimeError(f"TIME manifest identity mismatch for {control['label']}")
        controls.append({"label": control["label"], "manifest_sha256": actual})
    return {
        "queue_manifest_sha256": actual_queue_sha,
        "spec_scans": scans,
        "time_controls": controls,
    }


def zarr_meta(scan: Path, name: str) -> dict[str, Any]:
    return load_json(scan / name / ".zarray")


def read_cube_block(scan: Path, name: str, block: int) -> np.ndarray:
    meta = zarr_meta(scan, name)
    rows, adc_count, bins = (int(x) for x in meta["shape"])
    chunk_rows, chunk_adcs, chunk_bins = (int(x) for x in meta["chunks"])
    if adc_count != ADC_COUNT or bins != BLOCK_COUNT * BLOCK_CHANS:
        raise RuntimeError(f"{scan.name}/{name}: unexpected cube shape")
    if chunk_adcs != ADC_COUNT or chunk_bins != BLOCK_CHANS:
        raise RuntimeError(f"{scan.name}/{name}: unexpected cube chunk")
    dtype = np.dtype(meta["dtype"])
    result = np.empty((rows, ADC_COUNT, BLOCK_CHANS), dtype=dtype)
    for chunk_index, start in enumerate(range(0, rows, chunk_rows)):
        path = scan / name / f"{chunk_index}.0.{block}"
        chunk = np.fromfile(path, dtype=dtype)
        expected = chunk_rows * ADC_COUNT * BLOCK_CHANS
        if chunk.size != expected:
            raise RuntimeError(f"{path}: got {chunk.size} values, expected {expected}")
        valid = min(chunk_rows, rows - start)
        result[start : start + valid] = chunk.reshape(chunk_rows, ADC_COUNT, BLOCK_CHANS)[:valid]
    return result


def read_scalar_block(scan: Path, name: str, block: int) -> np.ndarray:
    meta = zarr_meta(scan, name)
    rows, blocks = (int(x) for x in meta["shape"])
    chunk_rows, chunk_blocks = (int(x) for x in meta["chunks"])
    if blocks != BLOCK_COUNT or chunk_blocks != 1:
        raise RuntimeError(f"{scan.name}/{name}: unexpected scalar shape")
    dtype = np.dtype(meta["dtype"])
    result = np.empty(rows, dtype=dtype)
    for chunk_index, start in enumerate(range(0, rows, chunk_rows)):
        path = scan / name / f"{chunk_index}.{block}"
        chunk = np.fromfile(path, dtype=dtype)
        if chunk.size != chunk_rows:
            raise RuntimeError(f"{path}: got {chunk.size} values, expected {chunk_rows}")
        valid = min(chunk_rows, rows - start)
        result[start : start + valid] = chunk[:valid]
    return result


def weighted_columns(values: np.ndarray, weights: np.ndarray) -> np.ndarray:
    return np.einsum("t,tc->c", weights, values, optimize=True) / float(np.sum(weights))


def aggregate_nonoverlap(values: np.ndarray, weights: np.ndarray, width: int) -> np.ndarray:
    rows, columns = values.shape
    groups = rows // width
    if groups < 1:
        raise RuntimeError(f"{rows} rows do not contain one integration width {width}")
    trimmed = groups * width
    grouped_weights = weights[:trimmed].reshape(groups, width)
    denominator = np.sum(grouped_weights, axis=1)
    numerator = np.einsum(
        "gmc,gm->gc",
        values[:trimmed].reshape(groups, width, columns),
        grouped_weights,
        optimize=True,
    )
    return numerator / denominator[:, None]


def autocovariance(values_centered: np.ndarray, lag_buckets: list[int]) -> np.ndarray:
    result = np.empty((len(lag_buckets), values_centered.shape[1]), dtype=np.float64)
    for index, lag in enumerate(lag_buckets):
        if lag == 0:
            result[index] = np.einsum(
                "tc,tc->c", values_centered, values_centered, optimize=True
            ) / values_centered.shape[0]
        else:
            result[index] = np.einsum(
                "tc,tc->c", values_centered[:-lag], values_centered[lag:], optimize=True
            ) / (values_centered.shape[0] - lag)
    return result


def allan_nonoverlap(series: np.ndarray) -> np.ndarray:
    if series.shape[0] < 2:
        return np.full(series.shape[1], np.nan)
    delta = np.diff(series, axis=0)
    return 0.5 * np.einsum("tc,tc->c", delta, delta, optimize=True) / delta.shape[0]


def weighted_cumulative(values: np.ndarray, weights: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    cumulative = np.empty((values.shape[0] + 1, values.shape[1]), dtype=np.float64)
    cumulative[0] = 0.0
    np.multiply(values, weights[:, None], out=cumulative[1:])
    np.cumsum(cumulative[1:], axis=0, out=cumulative[1:])
    weight_cumulative = np.concatenate(([0.0], np.cumsum(weights, dtype=np.float64)))
    return cumulative, weight_cumulative


def allan_overlap(cumulative: np.ndarray, weight_cumulative: np.ndarray, width: int) -> np.ndarray:
    averages = (cumulative[width:] - cumulative[:-width]) / (
        weight_cumulative[width:] - weight_cumulative[:-width]
    )[:, None]
    if averages.shape[0] <= width:
        return np.full(cumulative.shape[1], np.nan)
    delta = averages[width:] - averages[:-width]
    return 0.5 * np.einsum("tc,tc->c", delta, delta, optimize=True) / delta.shape[0]


def circular_block_bootstrap_weights(
    count: int, block_length: int, replicates: int, seed: int
) -> np.ndarray:
    rng = np.random.default_rng(seed)
    block_length = max(1, min(block_length, count))
    blocks = math.ceil(count / block_length)
    weights = np.zeros((replicates, count), dtype=np.float64)
    offsets = np.arange(block_length, dtype=np.int64)
    for replicate in range(replicates):
        starts = rng.integers(0, count, size=blocks)
        indices = ((starts[:, None] + offsets[None, :]) % count).ravel()[:count]
        weights[replicate] = np.bincount(indices, minlength=count)
    return weights


def bootstrap_mean_interval(
    series: np.ndarray, block_length: int, replicates: int, seed: int
) -> tuple[np.ndarray, np.ndarray]:
    weights = circular_block_bootstrap_weights(series.shape[0], block_length, replicates, seed)
    means = weights @ series / float(series.shape[0])
    interval = np.quantile(means, [0.025, 0.975], axis=0)
    return interval[0], interval[1]


def pfb_white_sigma(mean_power: np.ndarray, tau_s: float) -> np.ndarray:
    frames = max(2, int(round(tau_s / PFB_FRAME_SECONDS)))
    lags = np.arange(1, len(PFB_POWER_CORRELATIONS) + 1, dtype=np.float64)
    correction = 1.0 + 2.0 * np.sum((1.0 - lags / frames) * PFB_POWER_CORRELATIONS)
    return mean_power * math.sqrt(correction / frames)


def short_covariance_sigma(covariance: np.ndarray, width: int, lag_buckets: list[int]) -> np.ndarray:
    variance = width * covariance[0].copy()
    for index, lag in enumerate(lag_buckets[1:], start=1):
        if lag >= width or lag > 20:
            continue
        variance += 2.0 * (width - lag) * covariance[index]
    return np.sqrt(np.maximum(variance / (width * width), 0.0))


def welch_psd_variants(
    raw: np.ndarray,
    constant_removed: np.ndarray,
    temperature_regressed: np.ndarray,
    sample_rate_hz: float,
    nperseg: int,
    noverlap: int,
) -> tuple[np.ndarray, np.ndarray]:
    step = nperseg - noverlap
    starts = range(0, raw.shape[0] - nperseg + 1, step)
    window = np.hanning(nperseg).astype(np.float64)
    scale = 1.0 / (sample_rate_hz * float(np.sum(window * window)))
    frequency = np.fft.rfftfreq(nperseg, d=1.0 / sample_rate_hz)
    accumulators = np.zeros((3, frequency.size, raw.shape[1]), dtype=np.float64)
    segment_count = 0
    for start in starts:
        stacked = np.concatenate(
            (
                raw[start : start + nperseg],
                constant_removed[start : start + nperseg],
                temperature_regressed[start : start + nperseg],
            ),
            axis=1,
        )
        stacked *= window[:, None]
        transformed = np.fft.rfft(stacked, axis=0)
        power = transformed.real * transformed.real + transformed.imag * transformed.imag
        power *= scale
        if power.shape[0] > 2:
            power[1:-1] *= 2.0
        columns = raw.shape[1]
        for variant in range(3):
            accumulators[variant] += power[:, variant * columns : (variant + 1) * columns]
        segment_count += 1
    if segment_count == 0:
        raise RuntimeError("Welch configuration produced no segments")
    accumulators /= segment_count
    return frequency, accumulators


def telemetry_temperature(
    config: dict[str, Any], scan_config: dict[str, Any], row_count: int
) -> tuple[np.ndarray, dict[str, Any]]:
    telemetry = load_json(Path(scan_config["telemetry"]))
    timestamps = []
    temperatures = []
    predictor = config["temperature_predictor"]
    for sample in telemetry:
        for record in sample.get("board", {}).get("records", []):
            ams = record.get("ams", {})
            value = ams.get("temperatures_c", {}).get(predictor, {}).get("mean")
            timestamp = ams.get("captured_at_unix_ms")
            if value is not None and timestamp is not None:
                timestamps.append(float(timestamp))
                temperatures.append(float(value))
    if len(timestamps) < 2:
        raise RuntimeError(f"insufficient {predictor} telemetry for scan {scan_config['label']}")
    order = np.argsort(timestamps)
    timestamp_values = np.asarray(timestamps, dtype=np.float64)[order]
    temperature_values = np.asarray(temperatures, dtype=np.float64)[order]
    unique, unique_index = np.unique(timestamp_values, return_index=True)
    timestamp_values = unique
    temperature_values = temperature_values[unique_index]

    queue_state = load_json(Path(config["queue_root"]) / "queue_state.json")
    phase = queue_state["phases"][int(scan_config["phase_index"])]
    status = phase["capture_status"]
    capture_start = load_json(Path(scan_config["path"]) / "capture_start.json")
    lead_ms = (
        int(capture_start["start_sample0"]) - int(capture_start["origin_sample0"])
    ) / SAMPLE_RATE_HZ * 1000.0
    first_bucket_center_ms = float(status["started_unix_ms"]) + lead_ms + 5.0
    bucket_times = first_bucket_center_ms + np.arange(row_count, dtype=np.float64) * 10.0
    interpolated = np.interp(bucket_times, timestamp_values, temperature_values)
    covered = np.count_nonzero(
        (bucket_times >= timestamp_values[0]) & (bucket_times <= timestamp_values[-1])
    )
    return interpolated, {
        "predictor": predictor,
        "telemetry_points": int(timestamp_values.size),
        "telemetry_first_unix_ms": float(timestamp_values[0]),
        "telemetry_last_unix_ms": float(timestamp_values[-1]),
        "bucket_first_unix_ms": float(bucket_times[0]),
        "bucket_last_unix_ms": float(bucket_times[-1]),
        "coverage_fraction": covered / row_count,
        "alignment": "capture started_unix_ms plus sample0 arm lead; linear interpolation",
    }


def fixed_list(values: np.ndarray, value_type: pa.DataType) -> pa.Array:
    matrix = np.ascontiguousarray(values)
    flat = pa.array(matrix.ravel(order="C"), type=value_type)
    return pa.FixedSizeListArray.from_arrays(flat, matrix.shape[1])


def variable_list(values: np.ndarray, value_type: pa.DataType) -> pa.Array:
    matrix = np.ascontiguousarray(values)
    offsets = pa.array(np.arange(0, matrix.size + 1, matrix.shape[1], dtype=np.int64))
    flat = pa.array(matrix.ravel(order="C"), type=value_type)
    return pa.ListArray.from_arrays(offsets, flat)


def write_parquet_atomic(path: Path, table: pa.Table) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".partial")
    if partial.exists() or path.exists():
        raise RuntimeError(f"refusing to overwrite analysis shard {path}")
    pq.write_table(
        table,
        partial,
        compression="zstd",
        compression_level=6,
        use_dictionary=True,
        write_statistics=True,
    )
    with partial.open("rb") as stream:
        os.fsync(stream.fileno())
    partial.replace(path)


def metric_flags(global_bin: int) -> str:
    flags = []
    if global_bin == 0:
        flags.append("baseband_dc")
    if global_bin == 2048:
        flags.append("signed_spectrum_boundary")
    spur = 3328
    distance = min((global_bin - spur) % 4096, (spur - global_bin) % 4096)
    if distance == 0:
        flags.append("preflagged_digital_bin_3328")
    elif distance == 1:
        flags.append("preflagged_digital_bin_3328_neighbor")
    return ";".join(flags)


def analyze_block(config_path: str, scan_index: int, block: int) -> dict[str, Any]:
    config = load_json(Path(config_path))
    validate_config(config)
    scan_config = config["scans"][scan_index]
    scan = Path(scan_config["path"])
    output_root = Path(config["output_root"])
    shard = f"scan={scan_config['label']}/block={block:02d}"
    metric_path = output_root / "metrics_by_scan" / shard / "part.parquet"
    temporal_path = output_root / "temporal_metrics" / shard / "part.parquet"
    if metric_path.exists() or temporal_path.exists():
        raise RuntimeError(f"analysis shard already exists: {shard}")
    started = time.monotonic()

    power_cube = read_cube_block(scan, "mean_power_count2", block)
    power = power_cube.reshape(power_cube.shape[0], -1)
    native_valid = read_scalar_block(scan, "n_valid", block).astype(np.float64)
    if np.any(native_valid <= 0) or not np.all(np.isfinite(power)):
        raise RuntimeError(f"{shard}: non-finite power or zero valid exposure")
    mean_power = weighted_columns(power, native_valid)
    centered = power - mean_power[None, :]

    temperature, temperature_info = telemetry_temperature(config, scan_config, power.shape[0])
    temperature_mean = float(np.average(temperature, weights=native_valid))
    temperature_centered = temperature - temperature_mean
    denominator = float(np.sum(native_valid * temperature_centered * temperature_centered))
    if denominator <= 0.0:
        raise RuntimeError(f"{shard}: temperature predictor has zero variance")
    temperature_beta = np.einsum(
        "t,t,tc->c", native_valid, temperature_centered, centered, optimize=True
    ) / denominator
    temperature_regressed = power - temperature_centered[:, None] * temperature_beta[None, :]
    temperature_regressed_mean = weighted_columns(temperature_regressed, native_valid)
    temperature_residual_centered = temperature_regressed - temperature_regressed_mean[None, :]
    raw_variance = np.einsum("tc,tc->c", centered, centered, optimize=True) / centered.shape[0]
    residual_variance = np.einsum(
        "tc,tc->c", temperature_residual_centered, temperature_residual_centered, optimize=True
    ) / temperature_residual_centered.shape[0]
    temperature_r2 = 1.0 - residual_variance / np.maximum(raw_variance, np.finfo(np.float64).tiny)

    quantiles = np.quantile(power, [0.05, 0.16, 0.50, 0.84, 0.95], axis=0)
    native_mad = np.median(np.abs(power - quantiles[2][None, :]), axis=0)
    native_std = np.std(power, axis=0, ddof=1)

    mean_i_cube = read_cube_block(scan, "mean_i_count_100ms", block)
    mean_q_cube = read_cube_block(scan, "mean_q_count_100ms", block)
    m2_cube = read_cube_block(scan, "m2_power_count4_100ms", block)
    clip_cube = read_cube_block(scan, "clip_count_100ms", block)
    valid_100ms = read_scalar_block(scan, "n_valid_100ms", block).astype(np.float64)
    mean_i_100ms = mean_i_cube.reshape(mean_i_cube.shape[0], -1)
    mean_q_100ms = mean_q_cube.reshape(mean_q_cube.shape[0], -1)
    m2_100ms = m2_cube.reshape(m2_cube.shape[0], -1)
    clip_100ms = clip_cube.reshape(clip_cube.shape[0], -1)
    mean_i = weighted_columns(mean_i_100ms, valid_100ms)
    mean_q = weighted_columns(mean_q_100ms, valid_100ms)
    power_100ms = aggregate_nonoverlap(power, native_valid, 10)
    if power_100ms.shape != mean_i_100ms.shape:
        raise RuntimeError(f"{shard}: 10/100 ms cube shape mismatch")
    total_frames = float(np.sum(valid_100ms))
    sum_power_squared = np.sum(
        m2_100ms + valid_100ms[:, None] * power_100ms * power_100ms, axis=0
    )
    sum_power = mean_power * total_frames
    spectral_kurtosis = (total_frames + 1.0) / (total_frames - 1.0) * (
        total_frames * sum_power_squared / np.maximum(sum_power * sum_power, np.finfo(np.float64).tiny)
        - 1.0
    )
    clip_count = np.sum(clip_100ms, axis=0, dtype=np.uint64)
    del mean_i_cube, mean_q_cube, m2_cube, clip_cube, m2_100ms, clip_100ms

    lag_buckets = [int(round(float(value) / config["native_bucket_s"])) for value in config["acf_lag_seconds"]]
    covariance = autocovariance(centered, lag_buckets)
    covariance_temperature = autocovariance(temperature_residual_centered, lag_buckets)
    acf = covariance / np.maximum(covariance[0], np.finfo(np.float64).tiny)[None, :]
    acf_temperature = covariance_temperature / np.maximum(
        covariance_temperature[0], np.finfo(np.float64).tiny
    )[None, :]
    first_nonpositive = np.full(power.shape[1], 15.0, dtype=np.float64)
    for index, lag_s in enumerate(config["acf_lag_seconds"][1:], start=1):
        select = (first_nonpositive == 15.0) & (acf[index] <= 0.0)
        first_nonpositive[select] = float(lag_s)
    bootstrap_block_s = max(0.1, float(np.quantile(first_nonpositive, 0.95)))
    tau_integrated_s = config["native_bucket_s"] * (
        0.5 + np.sum(np.maximum(acf[1:21], 0.0), axis=0)
    )

    integration_seconds = [float(value) for value in config["integration_seconds"]]
    integration_raw = []
    integration_temperature = []
    integration_mean = []
    integration_std = []
    integration_mad = []
    integration_ci_low = []
    integration_ci_high = []
    theory_sigma = []
    pfb_sigma = []
    short_sigma = []
    for tau_index, tau_s in enumerate(integration_seconds):
        width = int(round(tau_s / config["native_bucket_s"]))
        raw_series = aggregate_nonoverlap(power, native_valid, width)
        temp_series = aggregate_nonoverlap(temperature_regressed, native_valid, width)
        integration_raw.append(raw_series)
        integration_temperature.append(temp_series)
        integration_mean.append(np.mean(raw_series, axis=0))
        integration_std.append(np.std(raw_series, axis=0, ddof=1))
        median = np.median(raw_series, axis=0)
        integration_mad.append(np.median(np.abs(raw_series - median[None, :]), axis=0))
        block_length = max(1, int(math.ceil(bootstrap_block_s / tau_s)))
        low, high = bootstrap_mean_interval(
            raw_series,
            block_length,
            int(config["bootstrap_replicates"]),
            int(config["bootstrap_seed"]) + scan_index * 1000 + block * 20 + tau_index,
        )
        integration_ci_low.append(low)
        integration_ci_high.append(high)
        theory_sigma.append(mean_power / math.sqrt(float(config["enbw_hz"]) * tau_s))
        pfb_sigma.append(pfb_white_sigma(mean_power, tau_s))
        short_sigma.append(short_covariance_sigma(covariance, width, lag_buckets))

    integration_std_array = np.stack(integration_std, axis=1)
    slopes = np.diff(np.log(np.maximum(integration_std_array, np.finfo(np.float64).tiny)), axis=1) / np.diff(
        np.log(np.asarray(integration_seconds, dtype=np.float64))
    )[None, :]

    cumulative, cumulative_weights = weighted_cumulative(power, native_valid)
    cumulative_temperature, _ = weighted_cumulative(temperature_regressed, native_valid)
    allan_seconds = [float(value) for value in config["allan_seconds"]]
    overlap_avar = []
    overlap_avar_temperature = []
    all_nonoverlap_avar = []
    all_nonoverlap_avar_temperature = []
    for tau_s in allan_seconds:
        width = int(round(tau_s / config["native_bucket_s"]))
        overlap_avar.append(allan_overlap(cumulative, cumulative_weights, width))
        overlap_avar_temperature.append(
            allan_overlap(cumulative_temperature, cumulative_weights, width)
        )
        all_nonoverlap_avar.append(
            allan_nonoverlap(aggregate_nonoverlap(power, native_valid, width))
        )
        all_nonoverlap_avar_temperature.append(
            allan_nonoverlap(aggregate_nonoverlap(temperature_regressed, native_valid, width))
        )
    del cumulative, cumulative_temperature

    psd_config = config["psd"]
    frequency, psd = welch_psd_variants(
        power,
        centered,
        temperature_regressed,
        float(psd_config["sample_rate_hz"]),
        int(psd_config["nperseg"]),
        int(psd_config["noverlap"]),
    )

    attrs = load_json(scan / ".zattrs")
    columns = ADC_COUNT * BLOCK_CHANS
    adc_ids = np.repeat(np.arange(ADC_COUNT, dtype=np.int16), BLOCK_CHANS)
    local_bins = np.tile(np.arange(BLOCK_CHANS, dtype=np.int16), ADC_COUNT)
    global_bins = block * BLOCK_CHANS + local_bins.astype(np.int32)
    signed_bins = np.where(global_bins < 2048, global_bins, global_bins - 4096).astype(np.int32)
    rf_hz = float(config["center_hz"]) + signed_bins.astype(np.float64) * float(
        config["channel_width_hz"]
    )
    identifiers: dict[str, pa.Array] = {
        "scan_id": pa.array([attrs["scan_id"]] * columns),
        "scan_label": pa.array([scan_config["label"]] * columns),
        "tuning_id": pa.array([attrs["tuning_id"]] * columns),
        "adc_id": pa.array(adc_ids),
        "block_index": pa.array(np.full(columns, block, dtype=np.int16)),
        "global_bin": pa.array(global_bins),
        "signed_bin": pa.array(signed_bins),
        "rf_hz": pa.array(rf_hz),
    }
    metric_table = pa.table(
        {
            **identifiers,
            "channel_width_hz": pa.array(np.full(columns, config["channel_width_hz"])),
            "enbw_hz": pa.array(np.full(columns, config["enbw_hz"])),
            "n_valid": pa.array(np.full(columns, int(np.sum(native_valid)), dtype=np.int64)),
            "exposure_s": pa.array(
                np.full(columns, np.sum(native_valid) * PFB_FRAME_SECONDS, dtype=np.float64)
            ),
            "mean_i_count": pa.array(mean_i),
            "mean_q_count": pa.array(mean_q),
            "rms_x_count": pa.array(np.sqrt(np.maximum(mean_power, 0.0))),
            "mean_power_count2": pa.array(mean_power),
            "power_density_count2_per_hz": pa.array(mean_power / float(config["enbw_hz"])),
            "power_p05_count2": pa.array(quantiles[0]),
            "power_p16_count2": pa.array(quantiles[1]),
            "power_p50_count2": pa.array(quantiles[2]),
            "power_p84_count2": pa.array(quantiles[3]),
            "power_p95_count2": pa.array(quantiles[4]),
            "power_min_count2": pa.array(np.min(power, axis=0)),
            "power_max_count2": pa.array(np.max(power, axis=0)),
            "native_std_power_count2": pa.array(native_std),
            "native_mad_power_count2": pa.array(native_mad),
            "mean_i_100ms_min_count": pa.array(np.min(mean_i_100ms, axis=0)),
            "mean_i_100ms_max_count": pa.array(np.max(mean_i_100ms, axis=0)),
            "mean_q_100ms_min_count": pa.array(np.min(mean_q_100ms, axis=0)),
            "mean_q_100ms_max_count": pa.array(np.max(mean_q_100ms, axis=0)),
            "spectral_kurtosis": pa.array(spectral_kurtosis),
            "clip_count": pa.array(clip_count),
            "temperature_predictor": pa.array([config["temperature_predictor"]] * columns),
            "temperature_beta_count2_per_c": pa.array(temperature_beta),
            "temperature_r2": pa.array(temperature_r2),
            "acf_first_nonpositive_s": pa.array(first_nonpositive),
            "short_positive_tau_integrated_s": pa.array(tau_integrated_s),
            "bootstrap_block_s": pa.array(np.full(columns, bootstrap_block_s)),
            "integration_mean_count2": fixed_list(np.stack(integration_mean, axis=1), pa.float64()),
            "integration_std_count2": fixed_list(integration_std_array, pa.float64()),
            "integration_mad_count2": fixed_list(np.stack(integration_mad, axis=1), pa.float64()),
            "integration_mean_ci_low_count2": fixed_list(
                np.stack(integration_ci_low, axis=1), pa.float64()
            ),
            "integration_mean_ci_high_count2": fixed_list(
                np.stack(integration_ci_high, axis=1), pa.float64()
            ),
            "sigma_theory_enbw_count2": fixed_list(np.stack(theory_sigma, axis=1), pa.float64()),
            "sigma_pfb_model_count2": fixed_list(np.stack(pfb_sigma, axis=1), pa.float64()),
            "sigma_short_cov_count2": fixed_list(np.stack(short_sigma, axis=1), pa.float64()),
            "sigma_over_theory": fixed_list(
                integration_std_array / np.maximum(np.stack(theory_sigma, axis=1), np.finfo(np.float64).tiny),
                pa.float64(),
            ),
            "sigma_over_pfb_model": fixed_list(
                integration_std_array / np.maximum(np.stack(pfb_sigma, axis=1), np.finfo(np.float64).tiny),
                pa.float64(),
            ),
            "local_sigma_log_slopes": fixed_list(slopes, pa.float64()),
            "data_quality_flags": pa.array([metric_flags(int(value)) for value in global_bins]),
        }
    )
    write_parquet_atomic(metric_path, metric_table)

    temporal_table = pa.table(
        {
            **identifiers,
            "acf_raw_uncentered_second_moment_count4": fixed_list(
                (covariance + mean_power[None, :] * mean_power[None, :]).T, pa.float64()
            ),
            "autocov_constant_removed_count4": fixed_list(covariance.T, pa.float64()),
            "acf_constant_removed": fixed_list(acf.T, pa.float64()),
            "autocov_temperature_regressed_count4": fixed_list(
                covariance_temperature.T, pa.float64()
            ),
            "acf_temperature_regressed": fixed_list(acf_temperature.T, pa.float64()),
            "avar_nonoverlap_raw_count4": fixed_list(
                np.stack(all_nonoverlap_avar, axis=1), pa.float64()
            ),
            "adev_nonoverlap_raw_count2": fixed_list(
                np.sqrt(np.maximum(np.stack(all_nonoverlap_avar, axis=1), 0.0)), pa.float64()
            ),
            "avar_overlap_raw_count4": fixed_list(np.stack(overlap_avar, axis=1), pa.float64()),
            "adev_overlap_raw_count2": fixed_list(
                np.sqrt(np.maximum(np.stack(overlap_avar, axis=1), 0.0)), pa.float64()
            ),
            "avar_nonoverlap_temperature_regressed_count4": fixed_list(
                np.stack(all_nonoverlap_avar_temperature, axis=1), pa.float64()
            ),
            "adev_nonoverlap_temperature_regressed_count2": fixed_list(
                np.sqrt(np.maximum(np.stack(all_nonoverlap_avar_temperature, axis=1), 0.0)),
                pa.float64(),
            ),
            "avar_overlap_temperature_regressed_count4": fixed_list(
                np.stack(overlap_avar_temperature, axis=1), pa.float64()
            ),
            "adev_overlap_temperature_regressed_count2": fixed_list(
                np.sqrt(np.maximum(np.stack(overlap_avar_temperature, axis=1), 0.0)),
                pa.float64(),
            ),
            "psd_raw_count4_per_hz": fixed_list(psd[0].T.astype(np.float32), pa.float32()),
            "psd_constant_removed_count4_per_hz": fixed_list(
                psd[1].T.astype(np.float32), pa.float32()
            ),
            "psd_temperature_regressed_count4_per_hz": fixed_list(
                psd[2].T.astype(np.float32), pa.float32()
            ),
        }
    )
    write_parquet_atomic(temporal_path, temporal_table)

    series_outputs = []
    for tau_index, tau_s in enumerate(integration_seconds):
        raw_series = integration_raw[tau_index]
        temp_series = integration_temperature[tau_index]
        series_path = (
            output_root
            / "integration_series"
            / f"tau={tau_s:g}s"
            / shard
            / "part.parquet"
        )
        series_table = pa.table(
            {
                **identifiers,
                "tau_s": pa.array(np.full(columns, tau_s)),
                "raw_power_count2": variable_list(raw_series.T.astype(np.float32), pa.float32()),
                "constant_removed_power_count2": variable_list(
                    (raw_series - mean_power[None, :]).T.astype(np.float32), pa.float32()
                ),
                "temperature_regressed_power_count2": variable_list(
                    temp_series.T.astype(np.float32), pa.float32()
                ),
            }
        )
        write_parquet_atomic(series_path, series_table)
        series_outputs.append(str(series_path))

    metadata_path = output_root / "block_metadata" / shard / "metadata.json"
    metadata = {
        "format": "T510_STAGE35_S2_ANALYSIS_BLOCK_V1",
        "scan_label": scan_config["label"],
        "scan_id": attrs["scan_id"],
        "block_index": block,
        "global_bin_first": block * BLOCK_CHANS,
        "global_bin_last": (block + 1) * BLOCK_CHANS - 1,
        "rows": columns,
        "native_buckets": power.shape[0],
        "temperature": temperature_info,
        "bootstrap_block_s": bootstrap_block_s,
        "integration_seconds": integration_seconds,
        "allan_seconds": allan_seconds,
        "acf_lag_seconds": config["acf_lag_seconds"],
        "psd_frequency_hz": frequency.tolist(),
        "psd_segment_count": 1 + (power.shape[0] - int(psd_config["nperseg"])) // (
            int(psd_config["nperseg"]) - int(psd_config["noverlap"])
        ),
        "outputs": [str(metric_path), str(temporal_path), *series_outputs],
        "elapsed_seconds": time.monotonic() - started,
    }
    write_json_atomic(metadata_path, metadata)
    return metadata


def analyze_time_controls(config: dict[str, Any], output_root: Path) -> tuple[Path, Path]:
    rows: list[dict[str, Any]] = []
    series_rows: list[dict[str, Any]] = []
    for control in config["time_controls"]:
        root = Path(control["path"])
        summary = load_json(root / "summary.json")
        manifest = load_json(root / "dataset_manifest.json")
        for lane in summary["lanes"]:
            rows.append(
                {
                    "control_label": control["label"],
                    "scan_id": manifest["request"]["scan_id"],
                    "position": manifest["request"]["metadata"]["position"],
                    "scan_label": manifest["request"]["metadata"]["scan"],
                    "adc_id": int(lane["lane"]),
                    "samples": int(lane["samples"]),
                    "mean_i_adu": float(lane["mean_i_adu"]),
                    "mean_q_adu": float(lane["mean_q_adu"]),
                    "std_i_adu": float(lane["std_i_adu"]),
                    "std_q_adu": float(lane["std_q_adu"]),
                    "complex_rms_adu": float(lane["complex_rms_adu"]),
                    "min_i_adu": int(lane["min_i"]),
                    "max_i_adu": int(lane["max_i"]),
                    "min_q_adu": int(lane["min_q"]),
                    "max_q_adu": int(lane["max_q"]),
                    "clip_i": int(lane["clip_i"]),
                    "clip_q": int(lane["clip_q"]),
                    "manifest_sha256": control["manifest_sha256"],
                }
            )
        by_lane: dict[int, dict[str, list[Any]]] = {
            lane: {
                key: []
                for key in (
                    "mean_i_adu",
                    "mean_q_adu",
                    "std_i_adu",
                    "std_q_adu",
                    "complex_rms_adu",
                    "min_i",
                    "max_i",
                    "min_q",
                    "max_q",
                    "clip_i",
                    "clip_q",
                )
            }
            for lane in range(ADC_COUNT)
        }
        with (root / "time_10ms.csv").open(newline="", encoding="utf-8") as stream:
            for row in csv.DictReader(stream):
                lane = int(row["lane"])
                for key in by_lane[lane]:
                    if key.startswith("clip_") or key.startswith("min_") or key.startswith("max_"):
                        by_lane[lane][key].append(int(row[key]))
                    else:
                        by_lane[lane][key].append(float(row[key]))
        for lane, values in by_lane.items():
            if set(len(items) for items in values.values()) != {3000}:
                raise RuntimeError(f"{control['label']} lane {lane}: incomplete 10 ms TIME series")
            series_rows.append(
                {
                    "control_label": control["label"],
                    "scan_id": manifest["request"]["scan_id"],
                    "position": manifest["request"]["metadata"]["position"],
                    "scan_label": manifest["request"]["metadata"]["scan"],
                    "adc_id": lane,
                    "bucket_ms": 10,
                    **values,
                }
            )
    path = output_root / "time_control_metrics.parquet"
    write_parquet_atomic(path, pa.Table.from_pylist(rows))
    series_path = output_root / "time_control_10ms_series.parquet"
    write_parquet_atomic(series_path, pa.Table.from_pylist(series_rows))
    return path, series_path


def finalize_analysis(config: dict[str, Any], output_root: Path) -> dict[str, Any]:
    cross_paths = []
    for block in range(BLOCK_COUNT):
        tables = []
        for scan in config["scans"]:
            path = output_root / "metrics_by_scan" / f"scan={scan['label']}" / f"block={block:02d}" / "part.parquet"
            tables.append(
                pq.read_table(
                    path,
                    columns=[
                        "adc_id",
                        "global_bin",
                        "rf_hz",
                        "mean_power_count2",
                        "native_std_power_count2",
                        "temperature_beta_count2_per_c",
                        "temperature_r2",
                    ],
                )
            )
        mean_by_scan = np.stack(
            [table["mean_power_count2"].to_numpy(zero_copy_only=False) for table in tables], axis=1
        )
        cross = pa.table(
            {
                "adc_id": tables[0]["adc_id"],
                "global_bin": tables[0]["global_bin"],
                "rf_hz": tables[0]["rf_hz"],
                "mean_power_a_count2": pa.array(mean_by_scan[:, 0]),
                "mean_power_b_count2": pa.array(mean_by_scan[:, 1]),
                "mean_power_c_count2": pa.array(mean_by_scan[:, 2]),
                "mean_power_across_scans_count2": pa.array(np.mean(mean_by_scan, axis=1)),
                "between_scan_std_count2": pa.array(np.std(mean_by_scan, axis=1, ddof=1)),
                "between_scan_fractional_std": pa.array(
                    np.std(mean_by_scan, axis=1, ddof=1)
                    / np.maximum(np.mean(mean_by_scan, axis=1), np.finfo(np.float64).tiny)
                ),
                "max_min_ratio": pa.array(
                    np.max(mean_by_scan, axis=1)
                    / np.maximum(np.min(mean_by_scan, axis=1), np.finfo(np.float64).tiny)
                ),
            }
        )
        path = output_root / "cross_scan_reproducibility" / f"block={block:02d}" / "part.parquet"
        write_parquet_atomic(path, cross)
        cross_paths.append(path)

    time_path, time_series_path = analyze_time_controls(config, output_root)
    output_files = sorted(path for path in output_root.rglob("*") if path.is_file())
    manifest_files = []
    for path in output_files:
        if path.name in ("analysis_manifest.json", "analysis_manifest.sha256", "analysis_state.json"):
            continue
        manifest_files.append(
            {
                "path": path.relative_to(output_root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    summary = {
        "format": FORMAT,
        "schema_version": 1,
        "status": "PASS",
        "queue_id": config["queue_id"],
        "row_identity": "scan_id x tuning_id x adc_id x global_bin",
        "metric_rows": 3 * ADC_COUNT * BLOCK_COUNT * BLOCK_CHANS,
        "cross_scan_rows": ADC_COUNT * BLOCK_COUNT * BLOCK_CHANS,
        "time_control_rows": 6 * ADC_COUNT,
        "integration_seconds": config["integration_seconds"],
        "allan_seconds": config["allan_seconds"],
        "acf_lag_seconds": config["acf_lag_seconds"],
        "psd": config["psd"],
        "units": {
            "voltage": "F-engine IQ16 count",
            "power": "count^2/PFB channel",
            "power_density": "count^2/Hz",
            "autocovariance_and_allan_variance": "count^4",
            "adev": "count^2",
            "time_control": "RFDC/TIME post-DDC complex IQ16 ADU",
        },
        "calibration_limit": "No K, Jy, SEFD, connector dBm, or T_sys without Stage 35 calibration",
        "payload_files": len(manifest_files),
        "payload_bytes": sum(item["bytes"] for item in manifest_files),
        "time_control_path": str(time_path),
        "time_control_series_path": str(time_series_path),
        "completed_unix_ms": unix_ms(),
    }
    write_json_atomic(output_root / "analysis_summary.json", summary)
    manifest_files.append(
        {
            "path": "analysis_summary.json",
            "bytes": (output_root / "analysis_summary.json").stat().st_size,
            "sha256": sha256_file(output_root / "analysis_summary.json"),
        }
    )
    manifest = {
        "format": "T510_STAGE35_S2_ANALYSIS_MANIFEST_V1",
        "schema_version": 1,
        "complete": True,
        "queue_id": config["queue_id"],
        "files": sorted(manifest_files, key=lambda item: item["path"]),
    }
    manifest_path = output_root / "analysis_manifest.json"
    write_json_atomic(manifest_path, manifest)
    (output_root / "analysis_manifest.sha256").write_text(
        f"{sha256_file(manifest_path)}  analysis_manifest.json\n", encoding="ascii"
    )
    return summary


def run_queue(config_path: Path) -> int:
    config = load_json(config_path)
    validate_config(config)
    input_identity = verify_inputs(config)
    output_root = Path(config["output_root"])
    output_root.mkdir(parents=True, exist_ok=False)
    state_path = output_root / "analysis_state.json"
    frozen_config = output_root / "analysis_config.json"
    shutil.copyfile(config_path, frozen_config)
    reproduction = output_root / "reproduction"
    reproduction.mkdir()
    source_dir = Path(__file__).resolve().parent
    shutil.copyfile(Path(__file__).resolve(), reproduction / Path(__file__).name)
    for name in (
        "t510_stage35_pfb_white_model.py",
        "pfb_white_model.json",
        "pip-freeze.txt",
        "SHA256SUMS",
    ):
        source = source_dir / name
        if source.is_file():
            shutil.copyfile(source, reproduction / name)
    tasks = [
        {"scan_index": scan_index, "scan_label": scan["label"], "block": block, "status": "pending"}
        for scan_index, scan in enumerate(config["scans"])
        for block in range(BLOCK_COUNT)
    ]
    state = {
        "format": "T510_STAGE35_S2_ANALYSIS_QUEUE_V1",
        "status": "running",
        "created_unix_ms": unix_ms(),
        "config_sha256": sha256_file(frozen_config),
        "input_identity": input_identity,
        "environment": {
            "python": sys.version,
            "platform": platform.platform(),
            "numpy": np.__version__,
            "pyarrow": pa.__version__,
        },
        "tasks": tasks,
        "error": None,
    }
    write_json_atomic(state_path, state)
    workers = int(config.get("parallel_workers", 1))
    futures: dict[Any, int] = {}
    try:
        with ProcessPoolExecutor(max_workers=workers) as executor:
            next_task = 0
            while next_task < len(tasks) or futures:
                while next_task < len(tasks) and len(futures) < workers:
                    task = tasks[next_task]
                    task["status"] = "running"
                    task["started_unix_ms"] = unix_ms()
                    future = executor.submit(
                        analyze_block,
                        str(frozen_config),
                        int(task["scan_index"]),
                        int(task["block"]),
                    )
                    futures[future] = next_task
                    next_task += 1
                write_json_atomic(state_path, state)
                done, _ = wait(futures, return_when=FIRST_COMPLETED)
                for future in done:
                    task_index = futures.pop(future)
                    task = tasks[task_index]
                    result = future.result()
                    task["status"] = "completed"
                    task["finished_unix_ms"] = unix_ms()
                    task["elapsed_seconds"] = result["elapsed_seconds"]
                    task["bootstrap_block_s"] = result["bootstrap_block_s"]
                    write_json_atomic(state_path, state)
        state["status"] = "finalizing"
        write_json_atomic(state_path, state)
        summary = finalize_analysis(config, output_root)
        state["status"] = "completed"
        state["finished_unix_ms"] = unix_ms()
        state["summary"] = summary
        write_json_atomic(state_path, state)
        return 0
    except Exception as exc:
        state["status"] = "failed"
        state["finished_unix_ms"] = unix_ms()
        state["error"] = {
            "message": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        }
        write_json_atomic(state_path, state)
        return 1


def self_test() -> None:
    weights = np.ones(1200, dtype=np.float64)
    columns = np.stack(
        (np.full(1200, 7.0), np.arange(1200, dtype=np.float64)), axis=1
    )
    integrated = aggregate_nonoverlap(columns, weights, 200)
    if integrated.shape != (6, 2) or not np.all(integrated[:, 0] == 7.0):
        raise RuntimeError("non-overlap integration self-test failed")
    centered = columns - np.mean(columns, axis=0)
    covariance = autocovariance(centered, [0, 1, 10])
    if covariance.shape != (3, 2) or covariance[0, 0] != 0.0:
        raise RuntimeError("autocovariance self-test failed")
    if allan_nonoverlap(integrated)[0] != 0.0:
        raise RuntimeError("Allan self-test failed")
    cumulative, cumulative_weights = weighted_cumulative(columns, weights)
    if allan_overlap(cumulative, cumulative_weights, 200)[0] != 0.0:
        raise RuntimeError("overlap Allan self-test failed")
    first = circular_block_bootstrap_weights(20, 4, 8, 123)
    second = circular_block_bootstrap_weights(20, 4, 8, 123)
    if not np.array_equal(first, second) or not np.all(np.sum(first, axis=1) == 20):
        raise RuntimeError("block bootstrap self-test failed")
    frequency, psd = welch_psd_variants(
        columns[:, :1], centered[:, :1], columns[:, :1], 100.0, 256, 128
    )
    if frequency.size != 129 or psd.shape != (3, 129, 1):
        raise RuntimeError("Welch PSD self-test failed")
    table = pa.table({"series": variable_list(integrated.T.astype(np.float32), pa.float32())})
    if table.num_rows != 2:
        raise RuntimeError("Arrow list self-test failed")
    print("STAGE35_S2_ANALYSIS_SELF_TEST_PASS")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    queue = sub.add_parser("queue")
    queue.add_argument("--config", type=Path, required=True)
    block = sub.add_parser("block")
    block.add_argument("--config", type=Path, required=True)
    block.add_argument("--scan-index", type=int, required=True)
    block.add_argument("--block-index", type=int, required=True)
    sub.add_parser("self-test")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "self-test":
        self_test()
        return 0
    if args.command == "block":
        result = analyze_block(str(args.config), args.scan_index, args.block_index)
        print(json.dumps(result, sort_keys=True))
        return 0
    return run_queue(args.config)


if __name__ == "__main__":
    raise SystemExit(main())
