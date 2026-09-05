#!/usr/bin/env python3
"""Generate the publication-style Stage 35 S2 scientific HTML report v2.

The report is self contained.  Exact statistics and tables remain float64;
registered 15-second display windows use float32; only the 900x4096 dynamic
spectrum raster uses an explicitly journalled uint16 display encoding.
"""

from __future__ import annotations

import argparse
import base64
import csv
import gzip
import hashlib
import html
import io
import json
import math
import os
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

import t510_stage35_report_v2_core as core
import t510_stage35_s2_html_report as v1


ADC_COUNT = 8
BIN_COUNT = 4096
BLOCK_COUNT = 16
BLOCK_BINS = 256
SCAN_LABELS = ("A", "B", "C")
TAU_SECONDS = (2.0, 4.0, 15.0, 30.0)
ACF_LAGS = (0,.01,.02,.03,.04,.05,.06,.07,.08,.09,.1,.11,.12,.13,.14,.15,.16,.17,.18,.19,.2,.5,1,2,4,8,15)
ALLAN_SECONDS = (.01,.02,.05,.1,.2,.5,1,2,4,8,15,30)
QUICK_SCALARS = (
    "mean_power_count2", "power_density_count2_per_hz", "native_std_power_count2",
    "spectral_kurtosis", "temperature_beta_count2_per_c", "temperature_r2",
    "acf_first_nonpositive_s", "short_positive_tau_integrated_s", "bootstrap_block_s",
)
QUICK_DERIVED = ("acf_constant_removed_1s",)
QUICK_LISTS = {
    "integration_mean_count2": ("integration_mean_2s", "integration_mean_4s", "integration_mean_15s", "integration_mean_30s"),
    "integration_std_count2": ("integration_std_2s", "integration_std_4s", "integration_std_15s", "integration_std_30s"),
    "integration_mad_count2": ("integration_mad_2s", "integration_mad_4s", "integration_mad_15s", "integration_mad_30s"),
    "integration_mean_ci_low_count2": ("integration_ci_low_2s", "integration_ci_low_4s", "integration_ci_low_15s", "integration_ci_low_30s"),
    "integration_mean_ci_high_count2": ("integration_ci_high_2s", "integration_ci_high_4s", "integration_ci_high_15s", "integration_ci_high_30s"),
    "sigma_theory_enbw_count2": ("sigma_enbw_2s", "sigma_enbw_4s", "sigma_enbw_15s", "sigma_enbw_30s"),
    "sigma_pfb_model_count2": ("sigma_pfb_2s", "sigma_pfb_4s", "sigma_pfb_15s", "sigma_pfb_30s"),
    "sigma_short_cov_count2": ("sigma_short_2s", "sigma_short_4s", "sigma_short_15s", "sigma_short_30s"),
    "sigma_over_theory": ("sigma_ratio_2s", "sigma_ratio_4s", "sigma_ratio_15s", "sigma_ratio_30s"),
    "sigma_over_pfb_model": ("sigma_pfb_ratio_2s", "sigma_pfb_ratio_4s", "sigma_pfb_ratio_15s", "sigma_pfb_ratio_30s"),
    "local_sigma_log_slopes": ("slope_2_4s", "slope_4_15s", "slope_15_30s"),
}
QUICK_FIELDS = QUICK_SCALARS + QUICK_DERIVED + tuple(name for names in QUICK_LISTS.values() for name in names)
CROSS_FIELDS = (
    "mean_power_a_count2", "mean_power_b_count2", "mean_power_c_count2",
    "mean_power_across_scans_count2", "between_scan_std_count2",
    "between_scan_fractional_std", "max_min_ratio",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def payload_tag(name: str, raw: bytes, extra: dict[str, Any] | None = None, level: int = 6) -> tuple[str, dict[str, Any]]:
    packed = gzip.compress(raw, compresslevel=level, mtime=0)
    encoded = base64.b64encode(packed).decode("ascii")
    info = {
        "name": name, "raw_bytes": len(raw), "gzip_bytes": len(packed),
        "sha256_raw": hashlib.sha256(raw).hexdigest(),
    }
    if extra:
        info.update(extra)
    return f'<script type="application/octet-stream" id="payload-{name}">{encoded}</script>', info


def metric_path(root: Path, family: str, scan: str, block: int) -> Path:
    return root / family / f"scan={scan}" / f"block={block:02d}" / "part.parquet"


def table_sorted(root: Path, family: str, scan: str, block: int) -> pa.Table:
    if family == "metrics_by_scan":
        return v1.ordered_metric_table(root, scan, block)
    return v1.ordered_temporal_table(root, scan, block)


def list_matrix(column: pa.ChunkedArray, width: int, dtype: Any = np.float64) -> np.ndarray:
    return v1.list_matrix(column, width, dtype)


def load_quick(root: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    quick = np.empty((3, ADC_COUNT, BIN_COUNT, len(QUICK_FIELDS)), dtype="<f8")
    cross = np.empty((ADC_COUNT, BIN_COUNT, len(CROSS_FIELDS)), dtype="<f8")
    rf = np.empty(BIN_COUNT, dtype="<f8")
    for block in range(BLOCK_COUNT):
        sl = slice(block * BLOCK_BINS, (block + 1) * BLOCK_BINS)
        ctable = pq.read_table(root / "cross_scan_reproducibility" / f"block={block:02d}" / "part.parquet")
        for adc in range(ADC_COUNT):
            rows = slice(adc * BLOCK_BINS, (adc + 1) * BLOCK_BINS)
            for field_index, field in enumerate(CROSS_FIELDS):
                cross[adc, sl, field_index] = ctable[field].to_numpy(zero_copy_only=False)[rows]
        for scan_index, scan in enumerate(SCAN_LABELS):
            table = table_sorted(root, "metrics_by_scan", scan, block)
            temporal = table_sorted(root, "temporal_metrics", scan, block)
            scalar = {field: table[field].to_numpy(zero_copy_only=False) for field in QUICK_SCALARS}
            acf_1s = list_matrix(temporal["acf_constant_removed"], len(ACF_LAGS))[:, ACF_LAGS.index(1)]
            lists = {field: list_matrix(table[field], len(names)) for field, names in QUICK_LISTS.items()}
            for adc in range(ADC_COUNT):
                rows = slice(adc * BLOCK_BINS, (adc + 1) * BLOCK_BINS)
                columns = [scalar[field][rows] for field in QUICK_SCALARS]
                columns.append(acf_1s[rows])
                columns.extend(lists[field][rows, index] for field, names in QUICK_LISTS.items() for index in range(len(names)))
                quick[scan_index, adc, sl, :] = np.stack(columns, axis=1)
                if scan_index == 0 and adc == 0:
                    rf[sl] = table["rf_hz"].to_numpy(zero_copy_only=False)[rows]
    if not np.all(np.isfinite(quick)) or not np.all(np.isfinite(cross)):
        raise RuntimeError("non-finite quick or cross-scan data")
    return quick, cross, rf


def load_temporal(root: Path, adc: int, scan: str) -> dict[str, np.ndarray]:
    arrays = {
        "acf": np.empty((3, BIN_COUNT, len(ACF_LAGS)), dtype="<f4"),
        "adev": np.empty((4, BIN_COUNT, len(ALLAN_SECONDS)), dtype="<f4"),
        "psd": np.empty((3, BIN_COUNT, 1025), dtype="<f4"),
    }
    for block in range(BLOCK_COUNT):
        sl = slice(block * BLOCK_BINS, (block + 1) * BLOCK_BINS)
        table = table_sorted(root, "temporal_metrics", scan, block)
        rows = slice(adc * BLOCK_BINS, (adc + 1) * BLOCK_BINS)
        raw_second = list_matrix(table["acf_raw_uncentered_second_moment_count4"], len(ACF_LAGS), np.float32)[rows]
        arrays["acf"][0, sl] = raw_second / np.maximum(raw_second[:, :1], np.finfo(np.float32).tiny)
        arrays["acf"][1, sl] = list_matrix(table["acf_constant_removed"], len(ACF_LAGS), np.float32)[rows]
        arrays["acf"][2, sl] = list_matrix(table["acf_temperature_regressed"], len(ACF_LAGS), np.float32)[rows]
        for variant, field in enumerate((
            "adev_nonoverlap_raw_count2", "adev_overlap_raw_count2",
            "adev_nonoverlap_temperature_regressed_count2", "adev_overlap_temperature_regressed_count2",
        )):
            arrays["adev"][variant, sl] = list_matrix(table[field], len(ALLAN_SECONDS), np.float32)[rows]
        for variant, field in enumerate((
            "psd_raw_count4_per_hz", "psd_constant_removed_count4_per_hz",
            "psd_temperature_regressed_count4_per_hz",
        )):
            arrays["psd"][variant, sl] = list_matrix(table[field], 1025, np.float32)[rows]
    return arrays


def load_integration_series(root: Path, adc: int, scan: str, tau: float) -> np.ndarray:
    width = {2.0: 450, 4.0: 225, 15.0: 60, 30.0: 30}[tau]
    result = np.empty((BIN_COUNT, width), dtype="<f4")
    for block in range(BLOCK_COUNT):
        path = root / "integration_series" / f"tau={tau:g}s" / f"scan={scan}" / f"block={block:02d}" / "part.parquet"
        table = pq.read_table(path, columns=["adc_id", "global_bin", "raw_power_count2"])
        adc_ids = table["adc_id"].to_numpy(zero_copy_only=False)
        bins = table["global_bin"].to_numpy(zero_copy_only=False)
        selected = np.flatnonzero(adc_ids == adc)
        selected = selected[np.argsort(bins[selected])]
        result[block * BLOCK_BINS:(block + 1) * BLOCK_BINS] = list_matrix(table["raw_power_count2"], width, np.float32)[selected]
    return result


def load_native_window(scan_root: Path, adc: int) -> tuple[np.ndarray, dict[str, float]]:
    result = np.empty((BIN_COUNT, 1500), dtype="<f4")
    max_absolute = 0.0
    max_relative = 0.0
    for block in range(BLOCK_COUNT):
        values = np.concatenate([v1.read_native_chunk(scan_root, block, chunk)[:, adc, :] for chunk in range(15)], axis=0).T
        stored = values.astype(np.float32)
        error = np.abs(values - stored.astype(np.float64))
        max_absolute = max(max_absolute, float(np.max(error)))
        max_relative = max(max_relative, float(np.max(error / np.maximum(np.abs(values), np.finfo(np.float64).tiny))))
        result[block * BLOCK_BINS:(block + 1) * BLOCK_BINS] = stored
    return result, {"max_absolute_error_count2": max_absolute, "max_relative_error": max_relative}


def load_dynamic(scan_root: Path, adc: int, order: np.ndarray) -> tuple[np.ndarray, dict[str, Any]]:
    linear = np.empty((3, 900, BIN_COUNT), dtype=np.float32)
    for block in range(BLOCK_COUNT):
        sl = slice(block * BLOCK_BINS, (block + 1) * BLOCK_BINS)
        for chunk in range(900):
            values = v1.read_native_chunk(scan_root, block, chunk)[:, adc, :]
            linear[0, chunk, sl] = np.min(values, axis=0).astype(np.float32)
            linear[1, chunk, sl] = np.mean(values, axis=0).astype(np.float32)
            linear[2, chunk, sl] = np.max(values, axis=0).astype(np.float32)
    db = (10.0 * np.log10(np.maximum(linear[:, :, order], np.finfo(np.float32).tiny))).astype(np.float32)
    quantized = np.empty(db.shape, dtype="<u2")
    layer_meta = []
    for layer in range(3):
        lo, hi = float(np.min(db[layer])), float(np.max(db[layer]))
        scale = (hi - lo) / 65535.0 or 1.0
        quantized[layer] = np.clip(np.rint((db[layer] - lo) / scale), 0, 65535).astype(np.uint16)
        layer_meta.append({
            "minimum_db_count2_per_channel": lo, "maximum_db_count2_per_channel": hi,
            "scale_db_per_code": scale, "maximum_encoding_error_db": scale / 2.0,
        })
    return quantized, {"layers": layer_meta, "shape": list(quantized.shape)}


def exact_metrics_csv(root: Path, adcs: set[int]) -> tuple[bytes, list[str], int]:
    buffer = io.StringIO(newline="")
    writer: csv.writer | None = None
    output_columns: list[str] = []
    row_count = 0
    for scan in SCAN_LABELS:
        for block in range(BLOCK_COUNT):
            table = table_sorted(root, "metrics_by_scan", scan, block)
            keep = np.flatnonzero(np.isin(table["adc_id"].to_numpy(zero_copy_only=False), list(adcs)))
            table = table.take(pa.array(keep))
            scalar_names = [name for name in table.column_names if name not in v1.METRIC_LIST_COLUMNS and name not in ("scan", "block")]
            if writer is None:
                output_columns = list(scalar_names)
                for name, suffixes in v1.METRIC_LIST_COLUMNS.items():
                    output_columns.extend(f"{name}_{suffix}" for suffix in suffixes)
                writer = csv.writer(buffer, lineterminator="\n")
                writer.writerow(output_columns)
            scalar = {name: table[name].to_pylist() for name in scalar_names}
            lists = {name: list_matrix(table[name], len(suffixes)) for name, suffixes in v1.METRIC_LIST_COLUMNS.items()}
            for row in range(table.num_rows):
                values = [scalar[name][row] for name in scalar_names]
                for name in v1.METRIC_LIST_COLUMNS:
                    values.extend(lists[name][row].tolist())
                writer.writerow(values)
                row_count += 1
    return buffer.getvalue().encode("utf-8"), output_columns, row_count


def quantiles(values: np.ndarray) -> dict[str, float]:
    p = np.quantile(values[np.isfinite(values)], [0.05, 0.5, 0.95])
    return {"p05": float(p[0]), "median": float(p[1]), "p95": float(p[2]), "minimum": float(np.min(values)), "maximum": float(np.max(values))}


def summarize(quick: np.ndarray, cross: np.ndarray) -> dict[str, Any]:
    qi = {name: index for index, name in enumerate(QUICK_FIELDS)}
    ci = {name: index for index, name in enumerate(CROSS_FIELDS)}
    per_adc = []
    anomaly_rows = []
    for adc in range(ADC_COUNT):
        sigma = quick[:, adc, :, qi["sigma_ratio_15s"]]
        acf_1s = quick[:, adc, :, qi["acf_constant_removed_1s"]]
        sk = np.abs(quick[:, adc, :, qi["spectral_kurtosis"]] - 1.0)
        temp = quick[:, adc, :, qi["temperature_r2"]]
        repro = cross[adc, :, ci["between_scan_fractional_std"]]
        per_adc.append({
            "adc_id": adc, "sigma_ratio_15s": quantiles(sigma), "sk_abs_from_one": quantiles(sk),
            "acf_constant_removed_1s_abs": quantiles(np.abs(acf_1s)), "temperature_r2": quantiles(temp),
            "between_scan_fractional_std": quantiles(repro),
        })
        metrics = {
            "sigma_ratio_15s": np.median(sigma, axis=0),
            "between_scan_fractional_std": repro,
            "acf_constant_removed_1s_abs": np.median(np.abs(acf_1s), axis=0),
            "spectral_kurtosis_abs_from_one": np.median(sk, axis=0),
        }
        for metric, values in metrics.items():
            for rank, bin_id in enumerate(np.argsort(values)[-10:][::-1], start=1):
                if metric == "between_scan_fractional_std":
                    scan_values = cross[adc, bin_id, [ci["mean_power_a_count2"], ci["mean_power_b_count2"], ci["mean_power_c_count2"]]]
                    scan_unit = "count²/PFB channel"
                elif metric == "sigma_ratio_15s":
                    scan_values = quick[:, adc, bin_id, qi["sigma_ratio_15s"]]
                    scan_unit = "dimensionless"
                elif metric == "acf_constant_removed_1s_abs":
                    scan_values = quick[:, adc, bin_id, qi["acf_constant_removed_1s"]]
                    scan_unit = "dimensionless (signed ACF)"
                else:
                    scan_values = quick[:, adc, bin_id, qi["spectral_kurtosis"]] - 1.0
                    scan_unit = "dimensionless (signed SK−1)"
                anomaly_rows.append({
                    "adc_id": adc, "metric": metric, "rank": rank,
                    "global_bin": int(bin_id), "rf_mhz": core.rf_hz(int(bin_id))/1e6,
                    "ranking_value": float(values[bin_id]),
                    "scan_a": float(scan_values[0]), "scan_b": float(scan_values[1]),
                    "scan_c": float(scan_values[2]), "scan_value_unit": scan_unit,
                })
    fixed_bin = 3328
    fixed_items = [{
        "adc_id": adc, "global_bin": fixed_bin, "rf_mhz": core.rf_hz(fixed_bin) / 1e6,
        "mean_power_a": float(quick[0, adc, fixed_bin, qi["mean_power_count2"]]),
        "mean_power_b": float(quick[1, adc, fixed_bin, qi["mean_power_count2"]]),
        "mean_power_c": float(quick[2, adc, fixed_bin, qi["mean_power_count2"]]),
        "sigma_ratio_a": float(quick[0, adc, fixed_bin, qi["sigma_ratio_15s"]]),
        "sigma_ratio_b": float(quick[1, adc, fixed_bin, qi["sigma_ratio_15s"]]),
        "sigma_ratio_c": float(quick[2, adc, fixed_bin, qi["sigma_ratio_15s"]]),
    } for adc in range(ADC_COUNT)]
    return {
        "overall": {
            "sigma_ratio_15s": quantiles(quick[:, :, :, qi["sigma_ratio_15s"]]),
            "acf_constant_removed_1s_abs": quantiles(np.abs(quick[:, :, :, qi["acf_constant_removed_1s"]])),
            "temperature_r2": quantiles(quick[:, :, :, qi["temperature_r2"]]),
            "spectral_kurtosis_abs_from_one": quantiles(np.abs(quick[:, :, :, qi["spectral_kurtosis"]] - 1.0)),
            "between_scan_fractional_std": quantiles(cross[:, :, ci["between_scan_fractional_std"]]),
        },
        "per_adc": per_adc, "anomalies": anomaly_rows, "fixed_items_960mhz": fixed_items,
    }


def _curve_quantiles(values: np.ndarray) -> dict[str, list[float]]:
    result = np.quantile(values[np.all(np.isfinite(values), axis=-1)], [0.05, 0.5, 0.95], axis=0)
    return {"p05": result[0].tolist(), "median": result[1].tolist(), "p95": result[2].tolist()}


def build_science_story(
    root: Path,
    quick: np.ndarray,
    cross: np.ndarray,
    *,
    rf_hz: np.ndarray | None = None,
) -> dict[str, Any]:
    """Derive the compact, human-facing story from every authoritative row."""
    if rf_hz is None:
        rf_hz = np.asarray([core.rf_hz(value) for value in range(BIN_COUNT)])
    else:
        rf_hz = np.asarray(rf_hz, dtype=np.float64)
    if rf_hz.shape != (BIN_COUNT,):
        raise ValueError("rf_hz must contain exactly 4096 global-bin frequencies")
    qi = {name: index for index, name in enumerate(QUICK_FIELDS)}
    ci = {name: index for index, name in enumerate(CROSS_FIELDS)}
    eligible = np.ones(BIN_COUNT, dtype=bool)
    eligible[list(core.preflagged_bins())] = False
    presets: dict[str, dict[str, int]] = {}
    for adc in range(ADC_COUNT):
        sigma = np.median(quick[:, adc, :, qi["sigma_ratio_15s"]], axis=0)
        acf = np.median(np.abs(quick[:, adc, :, qi["acf_constant_removed_1s"]]), axis=0)
        repro = cross[adc, :, ci["between_scan_fractional_std"]]
        metric_rows = np.column_stack((np.log(np.maximum(sigma, np.finfo(np.float64).tiny)), acf, repro))
        representative = core.representative_bin(metric_rows.tolist(), eligible.tolist())
        candidates = np.flatnonzero(eligible)
        worst = int(candidates[np.argmax(sigma[candidates])])
        memory = int(candidates[np.argmax(acf[candidates])])
        presets[str(adc)] = {
            "representative": representative,
            "worst_integration": worst,
            "strongest_memory": memory,
            "fixed_960mhz": 3328,
        }

    adev = np.empty((len(SCAN_LABELS), ADC_COUNT, BIN_COUNT, len(ALLAN_SECONDS)), dtype=np.float64)
    acf_adc0 = np.empty((len(SCAN_LABELS), BIN_COUNT, len(ACF_LAGS)), dtype=np.float64)
    for scan_index, scan in enumerate(SCAN_LABELS):
        for block in range(BLOCK_COUNT):
            sl = slice(block * BLOCK_BINS, (block + 1) * BLOCK_BINS)
            table = table_sorted(root, "temporal_metrics", scan, block)
            raw_overlap = list_matrix(table["adev_overlap_raw_count2"], len(ALLAN_SECONDS))
            adev[scan_index, :, sl, :] = raw_overlap.reshape(ADC_COUNT, BLOCK_BINS, len(ALLAN_SECONDS))
            acf = list_matrix(table["acf_constant_removed"], len(ACF_LAGS))
            acf_adc0[scan_index, sl, :] = acf[:BLOCK_BINS]

    mean = quick[:, :, :, qi["mean_power_count2"]]
    white_fractional = np.asarray([core.white_fractional_sigma(value) for value in ALLAN_SECONDS])
    allan_ratio = adev / np.maximum(mean[..., None] * white_fractional[None, None, None, :], np.finfo(np.float64).tiny)
    all_quantiles = _curve_quantiles(allan_ratio.reshape(-1, len(ALLAN_SECONDS)))
    clean_quantiles = _curve_quantiles(allan_ratio[:, :, eligible, :].reshape(-1, len(ALLAN_SECONDS)))

    integration_fractional = np.empty((len(SCAN_LABELS), ADC_COUNT, BIN_COUNT, len(TAU_SECONDS)), dtype=np.float64)
    integration_ratio = np.empty_like(integration_fractional)
    for tau_index, tau in enumerate(TAU_SECONDS):
        integration_fractional[..., tau_index] = (
            quick[..., qi[f"integration_std_{tau:g}s"]]
            / np.maximum(mean, np.finfo(np.float64).tiny)
        )
        integration_ratio[..., tau_index] = quick[..., qi[f"sigma_ratio_{tau:g}s"]]
    integration_quantiles = _curve_quantiles(integration_fractional.reshape(-1, len(TAU_SECONDS)))
    ratio_quantiles = _curve_quantiles(integration_ratio.reshape(-1, len(TAU_SECONDS)))
    paired_gain = integration_fractional[..., 0] / np.maximum(
        integration_fractional[..., -1], np.finfo(np.float64).tiny
    )
    gain_quantiles = quantiles(paired_gain)

    ratio_15 = float(ratio_quantiles["median"][TAU_SECONDS.index(15.0)])
    ratio_30 = float(ratio_quantiles["median"][TAU_SECONDS.index(30.0)])
    flagged_excluded_15 = float(np.median(integration_ratio[:, :, eligible, TAU_SECONDS.index(15.0)]))
    examples = (
        ("representative", "普通代表", presets["0"]["representative"]),
        ("digital_sentinel_3182", f"数字哨兵 bin 3182（{rf_hz[3182] / 1e6:.6f} MHz）", 3182),
        ("digital_sentinel_3328", f"数字哨兵 bin 3328（{rf_hz[3328] / 1e6:.6f} MHz）", 3328),
    )
    allan_examples = []
    acf_examples = []
    for key, label, global_bin in examples:
        fractional = adev[:, 0, global_bin, :] / mean[:, 0, global_bin, None]
        allan_examples.append({
            "key": key, "label": label, "global_bin": global_bin,
            "rf_mhz": float(rf_hz[global_bin] / 1e6),
            "scan_fractional_adev": fractional.tolist(),
            "median_fractional_adev": np.median(fractional, axis=0).tolist(),
        })
        scan_acf = acf_adc0[:, global_bin, :]
        acf_examples.append({
            "key": key, "label": label, "global_bin": global_bin,
            "rf_mhz": float(rf_hz[global_bin] / 1e6),
            "scan_acf": scan_acf.tolist(), "median_acf": np.median(scan_acf, axis=0).tolist(),
        })
    return {
        "population_rows": int(np.prod(quick.shape[:3])),
        "white_enbw_hz": core.ENBW_HZ,
        "preflagged_bins": sorted(core.preflagged_bins()),
        "adc_presets": presets,
        "allan_population": {
            "tau_s": list(ALLAN_SECONDS), "all_bins": all_quantiles,
            "preflagged_excluded": clean_quantiles,
        },
        "allan_examples": allan_examples,
        "acf_examples": acf_examples,
        "white_fractional_allan": white_fractional.tolist(),
        "integration": {
            "tau_s": list(TAU_SECONDS),
            "white_fractional": [core.white_fractional_sigma(value) for value in TAU_SECONDS],
            "measured_fractional": integration_quantiles,
            "measured_over_white": ratio_quantiles,
            "paired_gain_2s_to_30s": gain_quantiles,
            "ideal_gain_2s_to_30s": math.sqrt(15.0),
        },
        "headline": {
            "ratio_15s": ratio_15,
            "ratio_15s_p05": float(ratio_quantiles["p05"][TAU_SECONDS.index(15.0)]),
            "ratio_15s_p95": float(ratio_quantiles["p95"][TAU_SECONDS.index(15.0)]),
            "ratio_15s_preflagged_excluded": flagged_excluded_15,
            "ideal_fractional_15s_percent": 100.0 * core.white_fractional_sigma(15.0),
            "measured_fractional_15s_percent": 100.0 * float(integration_quantiles["median"][TAU_SECONDS.index(15.0)]),
            "equivalent_white_time_15s": core.equivalent_white_time(15.0, ratio_15),
            "radiometer_efficiency_15s": core.radiometer_efficiency(ratio_15),
            "white_time_penalty_15s": ratio_15 * ratio_15,
            "ratio_30s": ratio_30,
            "ideal_fractional_30s_percent": 100.0 * core.white_fractional_sigma(30.0),
            "measured_fractional_30s_percent": 100.0 * float(integration_quantiles["median"][TAU_SECONDS.index(30.0)]),
            "equivalent_white_time_30s": core.equivalent_white_time(30.0, ratio_30),
            "paired_gain_2s_to_30s": float(gain_quantiles["median"]),
            "ideal_gain_2s_to_30s": math.sqrt(15.0),
            "acf_1s_median_abs": float(np.median(np.abs(quick[..., qi["acf_constant_removed_1s"]]))),
            "acf_1s_p95_abs": float(np.quantile(np.abs(quick[..., qi["acf_constant_removed_1s"]]), 0.95)),
            "temperature_r2_median": float(np.median(quick[..., qi["temperature_r2"]])),
            "between_scan_fractional_std_median": float(np.median(cross[..., ci["between_scan_fractional_std"]])),
        },
    }


def _histogram_quantiles(counts: dict[int, int], probabilities: tuple[float, ...]) -> list[int]:
    ordered = sorted(counts.items())
    total = sum(count for _, count in ordered)
    if total <= 0:
        raise RuntimeError("empty TIME histogram")
    result: list[int] = []
    cumulative = 0
    index = 0
    for probability in probabilities:
        target = probability * (total - 1)
        while index < len(ordered) and cumulative + ordered[index][1] <= target:
            cumulative += ordered[index][1]
            index += 1
        if index == len(ordered):
            raise RuntimeError("TIME histogram quantile overflow")
        result.append(int(ordered[index][0]))
    return result


def load_time_histograms(report_config: dict[str, Any], time_metrics: list[dict[str, Any]]) -> dict[str, Any]:
    sources = report_config.get("time_histograms", [])
    if len(sources) != 6:
        raise RuntimeError("report config must freeze six TIME histograms")
    counts = {(adc, component): {} for adc in range(ADC_COUNT) for component in ("I", "Q")}
    frozen_sources = []
    for source in sources:
        path = Path(source["path"])
        actual_sha = sha256_file(path)
        if actual_sha != source["sha256"]:
            raise RuntimeError(f"TIME histogram identity mismatch: {path}")
        rows = 0
        with path.open(newline="", encoding="utf-8") as stream:
            for row in csv.DictReader(stream):
                key = (int(row["lane"]), row["component"])
                code = int(row["code"])
                count = int(row["count"])
                target = counts[key]
                target[code] = target.get(code, 0) + count
                rows += 1
        frozen_sources.append({"label": source["label"], "path": str(path), "sha256": actual_sha, "rows": rows})
    probabilities = (0.001, 0.025, 0.16, 0.5, 0.84, 0.975, 0.999)
    summaries = []
    for adc in range(ADC_COUNT):
        components = {}
        combined: dict[int, int] = {}
        for component in ("I", "Q"):
            histogram = counts[(adc, component)]
            samples = sum(histogram.values())
            if samples != 96_000_000:
                raise RuntimeError(f"ADC{adc} {component}: TIME histogram samples {samples} != 96000000")
            q = _histogram_quantiles(histogram, probabilities)
            components[component] = {
                "samples": samples, "minimum_50ms": min(histogram), "maximum_50ms": max(histogram),
                "q001": q[0], "q025": q[1], "q16": q[2], "median": q[3],
                "q84": q[4], "q975": q[5], "q999": q[6],
            }
            for code, value in histogram.items():
                combined[code] = combined.get(code, 0) + value
        metric_rows = [row for row in time_metrics if int(row["adc_id"]) == adc]
        minimum_30s = min(min(int(row["min_i_adu"]), int(row["min_q_adu"])) for row in metric_rows)
        maximum_30s = max(max(int(row["max_i_adu"]), int(row["max_q_adu"])) for row in metric_rows)
        clips = sum(int(row["clip_i"]) + int(row["clip_q"]) for row in metric_rows)
        codes = list(range(min(combined), max(combined) + 1))
        total = sum(combined.values())
        component_counts = {
            component: [counts[(adc, component)].get(code, 0) for code in codes]
            for component in ("I", "Q")
        }
        summaries.append({
            "adc_id": adc, "components": components,
            "minimum_30s": minimum_30s, "maximum_30s": maximum_30s, "clip_count": clips,
            "codes": codes, "counts": [combined.get(code, 0) for code in codes],
            "probability": [combined.get(code, 0) / total for code in codes],
            "component_counts": component_counts,
            "component_probability": {
                component: [value / components[component]["samples"] for value in component_counts[component]]
                for component in ("I", "Q")
            },
        })
    return {"format": "T510_TIME_CAPTURE_ADU_HISTOGRAM_STORY_V2", "sources": frozen_sources, "adcs": summaries}


def build_payloads(root: Path, analysis_config: dict[str, Any], report_config: dict[str, Any], mode: str) -> tuple[dict[str, Any], list[str]]:
    detail_adcs = [int(value) for value in report_config["modes"][mode]["detail_adcs"]]
    table_adcs = {int(value) for value in report_config["modes"][mode]["table_adcs"]}
    order = np.asarray(core.ascending_global_bins(), dtype=np.int32)
    quick, cross, rf = load_quick(root)
    tags: list[str] = []
    payloads: list[dict[str, Any]] = []

    def add(name: str, raw: bytes, extra: dict[str, Any] | None = None, level: int = 6) -> None:
        tag, info = payload_tag(name, raw, extra, level)
        tags.append(tag); payloads.append(info)

    add("quick-f64", quick.tobytes(order="C"))
    add("cross-f64", cross.tobytes(order="C"))
    add("rf-hz-f64", rf.tobytes(order="C"))
    add("frequency-order-i32", order.astype("<i4").tobytes(order="C"))

    scan_roots = {item["label"]: Path(item["path"]) for item in analysis_config["scans"]}
    native_errors: dict[str, Any] = {}
    for adc in detail_adcs:
        for scan in SCAN_LABELS:
            temporal = load_temporal(root, adc, scan)
            for family, array in temporal.items():
                add(f"{family}-{scan}-{adc}-f32", array.tobytes(order="C"), {"shape": list(array.shape), "dtype": "float32"}, 3)
            for tau in TAU_SECONDS:
                series = load_integration_series(root, adc, scan, tau)
                add(f"integration-{scan}-{adc}-{tau:g}s-f32", series.tobytes(order="C"), {"shape": list(series.shape), "dtype": "float32"}, 3)
            native, errors = load_native_window(scan_roots[scan], adc)
            native_errors[f"{scan}/ADC{adc}"] = errors
            add(f"native15-{scan}-{adc}-f32", native.tobytes(order="C"), {"shape": list(native.shape), "dtype": "float32", **errors}, 3)
            dynamic, dynamic_meta = load_dynamic(scan_roots[scan], adc, order)
            add(f"dynamic-{scan}-{adc}-u16", dynamic.tobytes(order="C"), dynamic_meta, 1)

    time_data = {
        "metrics": pq.read_table(root / "time_control_metrics.parquet").to_pylist(),
        "series": pq.read_table(root / "time_control_10ms_series.parquet").to_pylist(),
    }
    add("time-json", json.dumps(time_data, separators=(",", ":"), allow_nan=False).encode("utf-8"))
    adu_histograms = load_time_histograms(report_config, time_data["metrics"])
    add("adu-hist-json", json.dumps(adu_histograms, separators=(",", ":"), allow_nan=False).encode("utf-8"))
    csv_bytes, csv_columns, csv_rows = exact_metrics_csv(root, table_adcs)
    add("metrics-csv", csv_bytes, {"rows": csv_rows, "columns": len(csv_columns)}, 9)
    science = summarize(quick, cross)
    science_story = build_science_story(root, quick, cross)
    science_story["adu"] = {
        "sources": adu_histograms["sources"],
        "adcs": [{key: value for key, value in row.items() if key not in {
            "codes", "counts", "probability", "component_counts", "component_probability"
        }} for row in adu_histograms["adcs"]],
    }
    meta = {
        "format": "T510_STAGE35_S2_REPORT_DATA_V2", "mode": mode,
        "detail_adcs": detail_adcs, "table_adcs": sorted(table_adcs),
        "quick_fields": list(QUICK_FIELDS), "quick_shape": list(quick.shape),
        "cross_fields": list(CROSS_FIELDS), "cross_shape": list(cross.shape),
        "acf_lag_seconds": list(ACF_LAGS), "allan_seconds": list(ALLAN_SECONDS),
        "integration_seconds": list(TAU_SECONDS), "psd_frequency_hz": np.fft.rfftfreq(2048, .01).tolist(),
        "frequency_order": "ascending RF: bins 2048..4095,0..2047",
        "frequency_tick_pairs": core.frequency_tick_pairs(),
        "native_float32_errors": native_errors, "science": science, "science_story": science_story,
        "data_dictionary": [list(row) for row in core.dictionary_for_columns(csv_columns)],
        "figure_contracts": [contract.__dict__ for contract in core.FIGURE_CONTRACTS],
        "metrics_csv_columns": csv_columns, "metrics_csv_rows": csv_rows,
        "payloads": payloads,
    }
    return meta, tags


CSS = r"""
:root{--paper:#fff;--ink:#17202a;--muted:#586776;--line:#cbd5df;--blue:#1769aa;--cyan:#008c95;--orange:#b45309;--purple:#7851a9;--red:#a61b29;--soft:#f4f7fa;--note:#edf5fa;--problem:#fff4e6}*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:#e9eef3;color:var(--ink);font:16px/1.68 "Noto Sans SC","Source Han Sans SC",system-ui,sans-serif}header{background:var(--paper);border-bottom:6px solid var(--blue);padding:42px max(28px,calc((100vw - 1220px)/2))}h1{font:700 clamp(32px,4vw,52px)/1.15 Georgia,"Noto Serif SC",serif;margin:8px 0 12px}h2{font:700 29px/1.3 Georgia,"Noto Serif SC",serif;border-bottom:2px solid var(--line);padding-bottom:9px;margin-top:48px}h3{font-size:21px;line-height:1.35;margin:0 0 10px}.eyebrow{font-weight:700;color:var(--blue);letter-spacing:.08em}.subtitle,.muted{color:var(--muted)}main{max-width:1220px;margin:auto;background:var(--paper);padding:30px 44px 80px}.card,.figure,.adc{border:1px solid var(--line);background:var(--paper);border-radius:7px;padding:20px;margin:20px 0;box-shadow:0 1px 3px #18243016}.summary-grid,.figure-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(430px,1fr));gap:18px}.metric{border-left:5px solid var(--blue);background:var(--soft);padding:15px}.metric .value{font:700 25px/1.25 Georgia,serif;color:var(--blue)}.metric.problem{border-left-color:var(--red);background:var(--problem)}.metric.problem .value{color:var(--red)}.verdict{border:2px solid #d97706;border-left-width:9px;background:var(--problem);padding:20px 22px;font-size:19px}.verdict strong{color:#8a2d0b}.plain{font-size:18px}.plot{height:460px;width:100%}.plot.tall{height:590px}.hero-plot{height:560px}.dynamic-wrap{position:relative;overflow:auto}.dynamic-canvas{width:100%;height:610px;border:1px solid var(--line);background:#fff}.dynamic-tooltip{position:absolute;display:none;background:#fff;border:1px solid #657789;padding:7px;font-size:12px;pointer-events:none;box-shadow:0 2px 8px #0003}.figure-number{color:var(--blue);font-weight:700}.caption{border-top:1px solid var(--line);padding-top:12px;color:#344453}.caption b{color:var(--ink)}.impact{border-left:5px solid var(--orange);background:#fff8eb;padding:12px 15px}.controls{display:flex;gap:12px;align-items:end;flex-wrap:wrap;background:var(--soft);padding:13px;margin:12px 0}.controls label{display:grid;gap:3px;font-weight:600}.controls input,.controls select,button{background:#fff;border:1px solid #8293a4;border-radius:4px;padding:8px;color:var(--ink)}button{cursor:pointer}button:hover,.preset.active{border-color:var(--blue);color:var(--blue);background:#eef6fc}.warning{border-left:5px solid var(--orange);background:#fff8eb;padding:14px}.finding{border-left:5px solid var(--cyan);background:var(--note);padding:14px}.concept-flow{display:flex;align-items:center;justify-content:center;flex-wrap:wrap;gap:9px;margin:18px 0}.concept-flow span{background:#edf5fa;border:1px solid #9bbbd1;border-radius:6px;padding:11px 14px;font-weight:700}.concept-flow i{font-style:normal;color:var(--blue);font-size:22px}.reading-key{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}.reading-key div{padding:14px;border-top:5px solid var(--blue);background:var(--soft)}.reading-key div:nth-child(2){border-color:var(--orange)}.reading-key div:nth-child(3){border-color:var(--red)}.scroll{overflow:auto;max-height:620px;border:1px solid var(--line)}table{border-collapse:collapse;width:100%;font-size:13px}th,td{padding:7px 9px;border-bottom:1px solid #dce3e9;text-align:right;white-space:nowrap}th{position:sticky;top:0;background:#eaf0f5;z-index:2}th:first-child,td:first-child{text-align:left}.status{font-weight:700;color:var(--blue)}details>summary{font-size:22px;font-weight:700;cursor:pointer}.technical-atlas{margin-top:22px;border-top:2px solid var(--line);padding-top:14px}.technical-atlas>summary{font-size:18px;color:var(--muted)}.toc{columns:2}.toc a{color:var(--blue);text-decoration:none}.formula{font-family:"STIX Two Text",Georgia,serif;background:var(--soft);padding:8px 12px}.provenance{font-size:12px;overflow-wrap:anywhere}.plot-export{float:right;margin-top:-45px}.badge{display:inline-block;border:1px solid var(--blue);color:var(--blue);padding:3px 8px;margin-right:6px}.dictionary td:nth-child(2),.dictionary td:nth-child(5){text-align:left;white-space:normal}.canvas-readout{font-variant-numeric:tabular-nums;color:var(--blue);font-weight:650}fieldset{display:inline-block;vertical-align:top;margin:6px;padding:8px;border:1px solid var(--line)}fieldset label{display:inline-block;margin-right:9px}legend{font-weight:700;color:var(--blue)}@media(max-width:800px){main{padding:18px}.summary-grid,.figure-grid,.reading-key{grid-template-columns:1fr}.toc{columns:1}.plot,.hero-plot{height:430px}}@media print{body{background:white}main{max-width:none}.controls,button{display:none!important}.card,.figure,.adc{break-inside:avoid;box-shadow:none}.plot,.hero-plot{height:390px}.technical-atlas{display:none}}
"""


JS = r"""
'use strict';
const META=JSON.parse(document.getElementById('report-meta').textContent),P=Object.fromEntries(META.payloads.map(x=>[x.name,x]));const CACHE=new Map();
async function bytes(name){if(CACHE.has(name))return CACHE.get(name);const b64=document.getElementById('payload-'+name).textContent.trim(),packed=Uint8Array.from(atob(b64),c=>c.charCodeAt(0));const stream=new Blob([packed]).stream().pipeThrough(new DecompressionStream('gzip')),out=new Uint8Array(await new Response(stream).arrayBuffer());CACHE.set(name,out);return out}
async function typed(name,Type){const b=await bytes(name);return new Type(b.buffer,b.byteOffset,b.byteLength/Type.BYTES_PER_ELEMENT)}
let QUICK,CROSS,RF,ORDER,RFASC,BINASC;const qIndex=Object.fromEntries(META.quick_fields.map((x,i)=>[x,i])),cIndex=Object.fromEntries(META.cross_fields.map((x,i)=>[x,i]));
async function coreData(){if(!QUICK){QUICK=await typed('quick-f64',Float64Array);CROSS=await typed('cross-f64',Float64Array);RF=await typed('rf-hz-f64',Float64Array);ORDER=await typed('frequency-order-i32',Int32Array);RFASC=Array.from(ORDER,b=>RF[b]/1e6);BINASC=Array.from(ORDER)}return QUICK}
function qv(s,a,b,f){return QUICK[(((s*8+a)*4096+b)*META.quick_fields.length)+qIndex[f]]}function cv(a,b,f){return CROSS[((a*4096+b)*META.cross_fields.length)+cIndex[f]]}
const colors=['#1769aa','#db6d00','#008c95','#7851a9','#bc3c4a','#6b7c2b','#8a5a44','#486581'];
const plotConfig={responsive:true,displaylogo:false,scrollZoom:true,modeBarButtonsToRemove:['lasso2d','select2d'],toImageButtonOptions:{format:'png',scale:2}};
function axis(value){let result=Object.assign({},value||{});if(typeof result.title==='string')result.title={text:result.title};return result}
function mergeLayout(base,extra){let out=Object.assign({},base,extra);for(const key of ['xaxis','xaxis2','yaxis'])if(base[key]||extra[key])out[key]=axis(Object.assign({},base[key]||{},extra[key]||{}));return out}
function freqLayout(title,ytitle,extra={}){const ticks=META.frequency_tick_pairs.map(x=>x[0]),bins=META.frequency_tick_pairs.map(x=>x[1]);let base={title:{text:title,x:.02,xanchor:'left'},paper_bgcolor:'#fff',plot_bgcolor:'#fff',font:{family:'Noto Sans SC,system-ui',color:'#17202a'},margin:{l:88,r:42,t:92,b:76},hovermode:'x unified',xaxis:{title:{text:'RF frequency (MHz)'},range:[860,1179.921875],tickmode:'array',tickvals:ticks,showgrid:true,gridcolor:'#dce3e9',showspikes:true,spikemode:'across',spikesnap:'cursor'},xaxis2:{title:{text:'global_bin'},overlaying:'x',side:'top',range:[860,1179.921875],tickmode:'array',tickvals:ticks,ticktext:bins,showgrid:false,showline:true},yaxis:{title:{text:ytitle},showgrid:true,gridcolor:'#dce3e9'},shapes:[{type:'line',x0:960,x1:960,y0:0,y1:1,yref:'paper',line:{color:'#bc3c4a',dash:'dash'}},{type:'line',x0:1020,x1:1020,y0:0,y1:1,yref:'paper',line:{color:'#7851a9',dash:'dot'}}],annotations:[{x:960,y:1,yref:'paper',text:'960 MHz固定项',showarrow:false,yshift:12,font:{color:'#bc3c4a'}},{x:1020,y:1,yref:'paper',text:'1020 MHz复基带DC',showarrow:false,yshift:12,font:{color:'#7851a9'}}]};return mergeLayout(base,extra)}
function cartLayout(title,xtitle,ytitle,extra={}){let base={title:{text:title,x:.02,xanchor:'left'},paper_bgcolor:'#fff',plot_bgcolor:'#fff',font:{family:'Noto Sans SC,system-ui',color:'#17202a'},margin:{l:92,r:34,t:72,b:76},hovermode:'closest',xaxis:{title:{text:xtitle},showgrid:true,gridcolor:'#dce3e9',showspikes:true},yaxis:{title:{text:ytitle},showgrid:true,gridcolor:'#dce3e9',showspikes:true}};return mergeLayout(base,extra)}
function numericValues(value,out=[]){if(Array.isArray(value)||ArrayBuffer.isView(value)){for(const x of value)numericValues(x,out)}else if(Number.isFinite(value))out.push(Number(value));return out}
function unitFromLayout(layout,data){let color=data.find(t=>t.colorbar&&t.colorbar.title)?.colorbar?.title?.text;if(color)return color.replace(/^[^()]*\((.*)\)$/,'$1');let y=layout.yaxis?.title;let text=typeof y==='string'?y:y?.text||'';let m=text.match(/\(([^()]*)\)\s*$/);return m?m[1]:''}
async function draw(id,data,layout){let traces=Array.from(data);if(layout.xaxis2)traces.push({x:[layout.xaxis2.range?.[0]??860,layout.xaxis2.range?.[1]??1179.921875],y:[null,null],xaxis:'x2',mode:'markers',marker:{opacity:0,size:.1},hoverinfo:'skip',showlegend:false,name:'global_bin axis binding'});await Plotly.react(id,traces,layout,plotConfig);const el=document.getElementById(id),panel=el.closest('.figure');if(panel&&!panel.querySelector('.plot-export')){let b=document.createElement('button');b.className='plot-export';b.textContent='导出SVG';b.onclick=()=>Plotly.downloadImage(el,{format:'svg',filename:id});panel.prepend(b)}}
function stats(values,unit=''){const a=Array.from(values).filter(Number.isFinite).sort((x,y)=>x-y),n=a.length,q=p=>a[Math.min(n-1,Math.floor((n-1)*p))];return {min:a[0],median:q(.5),max:a[n-1],p05:q(.05),p95:q(.95),unit}}
function fmt(v){if(!Number.isFinite(v))return '—';let a=Math.abs(v);return a!==0&&(a<1e-3||a>=1e5)?v.toExponential(5):v.toPrecision(7)}
function setStats(id,s){const e=document.getElementById(id);if(e)e.innerHTML=`<span>min ${fmt(s.min)} ${s.unit}</span><span>median ${fmt(s.median)} ${s.unit}</span><span>max ${fmt(s.max)} ${s.unit}</span>`}
function ordered(s,a,field){return Array.from(ORDER,b=>qv(s,a,b,field))}function custom(){return BINASC.map((b,i)=>[b,RFASC[i]])}
async function renderGlobal(){await coreData();let traces=[];for(let a=0;a<8;a++){let y=RFASC.map((_,i)=>{let b=ORDER[i];return(qv(0,a,b,'mean_power_count2')+qv(1,a,b,'mean_power_count2')+qv(2,a,b,'mean_power_count2'))/3});traces.push({x:RFASC,y,name:`ADC${a}`,mode:'lines',line:{width:1.2,color:colors[a]},customdata:custom(),hovertemplate:'RF %{x:.6f} MHz<br>bin %{customdata[0]}<br>mean %{y:.9g} count²/channel<extra>%{fullData.name}</extra>'})}await draw('global-bandpass',traces,freqLayout('八路ADC三扫描平均带通','Mean power (count²/PFB channel)'));let z=[],zr=[];for(let a=0;a<8;a++){z.push(RFASC.map((_,i)=>{let b=ORDER[i];return(qv(0,a,b,'sigma_ratio_15s')+qv(1,a,b,'sigma_ratio_15s')+qv(2,a,b,'sigma_ratio_15s'))/3}));zr.push(RFASC.map((_,i)=>cv(a,ORDER[i],'between_scan_fractional_std')))}await draw('global-sigma',[{type:'heatmap',x:RFASC,y:Array.from({length:8},(_,i)=>`ADC${i}`),z,colorscale:'Viridis',colorbar:{title:{text:'σ(15 s)/σ_ENBW'},ticks:'outside'},customdata:Array.from({length:8},()=>BINASC),hovertemplate:'RF %{x:.6f} MHz<br>%{y}<br>σ/理论 %{z:.6g}<extra></extra>'}],freqLayout('八路ADC：15 s实测散布/白噪声理论','ADC'));await draw('global-repro',[{type:'heatmap',x:RFASC,y:Array.from({length:8},(_,i)=>`ADC${i}`),z:zr,colorscale:'Cividis',colorbar:{title:{text:'fractional std'},ticks:'outside'},hovertemplate:'RF %{x:.6f} MHz<br>%{y}<br>A/B/C fractional std %{z:.6g}<extra></extra>'}],freqLayout('八路ADC：A/B/C扫描间复现性','ADC'));document.getElementById('global-ready').textContent='全局图已从float64指标表渲染'}
async function renderStory(){let story=META.science_story,adu=JSON.parse(new TextDecoder().decode(await bytes('adu-hist-json'))),hist=adu.adcs.flatMap((row,i)=>['I','Q'].map(component=>({x:row.codes,y:row.component_probability[component].map(x=>100*x),name:`ADC${i} ${component}`,mode:'lines+markers',line:{width:1.7,color:colors[i],dash:component==='I'?'solid':'dot'},marker:{size:3},hovertemplate:`ADC${i} ${component}<br>ADU %{x}<br>%{y:.5f}%<extra></extra>`})));await draw('adu-hist',hist,cartLayout('六次TIME控制：每个ADC的I/Q真实码值分布','post-DDC I/Q sample value (ADU)','Probability per ADU code (%)',{xaxis:{title:{text:'post-DDC I/Q sample value (ADU)'},range:[-32,32],dtick:4,showgrid:true},yaxis:{title:{text:'Probability per ADU code (%)'},type:'log',showgrid:true}}));let ap=story.allan_population,t=ap.tau_s;await draw('allan-global',[{x:t,y:ap.all_bins.p05,name:'P05',mode:'lines',line:{color:'#9bbbd1',width:1}},{x:t,y:ap.all_bins.p95,name:'P05–P95',mode:'lines',fill:'tonexty',fillcolor:'#1769aa22',line:{color:'#9bbbd1',width:1}},{x:t,y:ap.all_bins.median,name:'全部98,304行中位',mode:'lines+markers',line:{color:colors[0],width:4}},{x:t,y:t.map(()=>1),name:'理想白噪声 = 1',mode:'lines',line:{color:'#17202a',dash:'dash',width:2}},{x:t,y:ap.preflagged_excluded.median,name:'剔除预标记5 bin后的中位',mode:'lines',line:{color:colors[1],dash:'dot',width:2}}],cartLayout('Allan总览：积分越久，实测反而离白噪声理想越远','Averaging time τ (s)','Measured ADEV / ENBW white-noise expectation',{xaxis:{title:{text:'Averaging time τ (s)'},type:'log',showgrid:true},yaxis:{title:{text:'Measured ADEV / ENBW white-noise expectation'},type:'log',showgrid:true}}));let exampleTr=[{x:t,y:story.white_fractional_allan,name:'理想白噪声 τ^-1/2',mode:'lines',line:{color:'#17202a',dash:'dash',width:3}}];story.allan_examples.forEach((row,i)=>exampleTr.push({x:t,y:row.median_fractional_adev,name:`${row.label} · ADC0 · A/B/C中位`,mode:'lines+markers',line:{color:[colors[2],colors[1],colors[4]][i],width:3},customdata:t.map((_,j)=>row.scan_fractional_adev.map(x=>x[j])),hovertemplate:`${row.label}<br>τ %{x:g} s<br>ADEV/mean %{y:.7g}<br>A/B/C %{customdata}<extra></extra>`}));await draw('allan-examples',exampleTr,cartLayout('普通频点、948.6 MHz异常簇与960 MHz固定项','Averaging time τ (s)','Fractional Allan deviation ADEV / mean power',{xaxis:{title:{text:'Averaging time τ (s)'},type:'log',showgrid:true},yaxis:{title:{text:'Fractional Allan deviation ADEV / mean power'},type:'log',showgrid:true}}));let integ=story.integration;await draw('integration-story',[{x:integ.tau_s,y:integ.measured_fractional.p05.map(x=>100*x),name:'实测P05',mode:'lines',line:{color:'#9bbbd1'}},{x:integ.tau_s,y:integ.measured_fractional.p95.map(x=>100*x),name:'实测P05–P95',mode:'lines',fill:'tonexty',fillcolor:'#008c9522',line:{color:'#9bbbd1'}},{x:integ.tau_s,y:integ.measured_fractional.median.map(x=>100*x),name:'实测中位',mode:'lines+markers',line:{color:colors[2],width:4}},{x:integ.tau_s,y:integ.white_fractional.map(x=>100*x),name:'理想白噪声',mode:'lines+markers',line:{color:'#17202a',dash:'dash',width:3}}],cartLayout('天文直观量：30 s并没有换来应有的灵敏度','Integration time τ (s)','Fractional scatter of integrated power (%)',{xaxis:{title:{text:'Integration time τ (s)'},type:'log',showgrid:true},yaxis:{title:{text:'Fractional scatter of integrated power (%)'},type:'log',showgrid:true}}));let acfTr=[];story.acf_examples.forEach((row,i)=>acfTr.push({x:META.acf_lag_seconds,y:row.median_acf,name:`${row.label} · ADC0 · A/B/C中位`,mode:'lines+markers',line:{color:[colors[2],colors[1],colors[4]][i],width:3}}));acfTr.push({x:META.acf_lag_seconds,y:META.acf_lag_seconds.map(()=>0),name:'白噪声长滞后参考 = 0',mode:'lines',line:{color:'#17202a',dash:'dash'}});await draw('acf-story',acfTr,cartLayout('把序列错开后仍同涨同跌，就是噪声有“记忆”','Lag (s)','ACF after removing the constant mean',{xaxis:{title:{text:'Lag (s)'},type:'log',range:[Math.log10(.01),Math.log10(15)],showgrid:true},yaxis:{title:{text:'ACF after removing the constant mean'},showgrid:true,zeroline:true}}));document.getElementById('story-ready').textContent='ADU、Allan、积分效率与ACF均已从完整数据渲染'}
class DynamicSpectrum{constructor(canvas,tooltip,readout){this.canvas=canvas;this.tip=tooltip;this.readout=readout;this.data=null;this.scan='A';this.adc=0;this.layer=1;canvas.addEventListener('mousemove',e=>this.move(e));canvas.addEventListener('mouseleave',()=>this.tip.style.display='none')}viridis(t){t=Math.max(0,Math.min(1,t));let stops=[[68,1,84],[59,82,139],[33,145,140],[94,201,98],[253,231,37]],p=t*(stops.length-1),i=Math.min(stops.length-2,Math.floor(p)),f=p-i;return stops[i].map((v,j)=>Math.round(v+(stops[i+1][j]-v)*f))}async load(scan,adc,layer){this.scan=scan;this.adc=adc;this.layer=layer;this.data=await typed(`dynamic-${scan}-${adc}-u16`,Uint16Array);this.meta=P[`dynamic-${scan}-${adc}-u16`].layers[layer];this.render()}render(){const c=this.canvas,ctx=c.getContext('2d'),w=c.width=1500,h=c.height=620,m={l:88,r:130,t:72,b:72},pw=w-m.l-m.r,ph=h-m.t-m.b,off=document.createElement('canvas');off.width=4096;off.height=900;let oc=off.getContext('2d'),img=oc.createImageData(4096,900),offset=this.layer*900*4096;for(let i=0;i<900*4096;i++){let rgb=this.viridis(this.data[offset+i]/65535);img.data[4*i]=rgb[0];img.data[4*i+1]=rgb[1];img.data[4*i+2]=rgb[2];img.data[4*i+3]=255}oc.putImageData(img,0,0);ctx.fillStyle='#fff';ctx.fillRect(0,0,w,h);ctx.drawImage(off,m.l,m.t,pw,ph);ctx.strokeStyle='#17202a';ctx.strokeRect(m.l,m.t,pw,ph);ctx.font='14px system-ui';ctx.fillStyle='#17202a';ctx.textAlign='center';for(let i=0;i<=8;i++){let x=m.l+pw*i/8,rf=860+(1179.921875-860)*i/8,b=((Math.round((rf-1020)/.078125)%4096)+4096)%4096;ctx.beginPath();ctx.moveTo(x,m.t+ph);ctx.lineTo(x,m.t+ph+7);ctx.stroke();ctx.fillText(rf.toFixed(1),x,m.t+ph+25);ctx.beginPath();ctx.moveTo(x,m.t);ctx.lineTo(x,m.t-7);ctx.stroke();ctx.fillText(String(b),x,m.t-15)}ctx.textAlign='right';for(let i=0;i<=6;i++){let y=m.t+ph*i/6,t=900*i/6;ctx.beginPath();ctx.moveTo(m.l-7,y);ctx.lineTo(m.l,y);ctx.stroke();ctx.fillText(t.toFixed(0),m.l-12,y+5)}ctx.save();ctx.translate(22,m.t+ph/2);ctx.rotate(-Math.PI/2);ctx.textAlign='center';ctx.fillText('Elapsed time (s)',0,0);ctx.restore();ctx.textAlign='center';ctx.fillText('RF frequency (MHz)',m.l+pw/2,h-20);ctx.fillText('global_bin',m.l+pw/2,22);ctx.font='bold 18px system-ui';ctx.textAlign='left';ctx.fillText(`${this.scan} ADC${this.adc} dynamic spectrum — ${['minimum','mean','maximum'][this.layer]} in each 1 s window`,m.l,42);for(let j=0;j<256;j++){let t=1-j/255,rgb=this.viridis(t);ctx.fillStyle=`rgb(${rgb})`;ctx.fillRect(w-88,m.t+j*ph/256,24,ph/256+1)}ctx.strokeStyle='#17202a';ctx.strokeRect(w-88,m.t,24,ph);ctx.font='12px system-ui';ctx.fillStyle='#17202a';ctx.textAlign='left';for(let i=0;i<=5;i++){let y=m.t+ph*i/5,v=this.meta.maximum_db_count2_per_channel-(this.meta.maximum_db_count2_per_channel-this.meta.minimum_db_count2_per_channel)*i/5;ctx.fillText(v.toFixed(2),w-57,y+4)}ctx.save();ctx.translate(w-12,m.t+ph/2);ctx.rotate(-Math.PI/2);ctx.textAlign='center';ctx.fillText('10 log₁₀(P/[1 count²/channel])',0,0);ctx.restore();this.geom={m,pw,ph,w,h}}move(e){if(!this.data||!this.geom)return;let r=this.canvas.getBoundingClientRect(),x=(e.clientX-r.left)*this.canvas.width/r.width,y=(e.clientY-r.top)*this.canvas.height/r.height,{m,pw,ph}=this.geom;if(x<m.l||x>m.l+pw||y<m.t||y>m.t+ph){this.tip.style.display='none';return}let k=Math.max(0,Math.min(4095,Math.floor((x-m.l)/pw*4096))),t=Math.max(0,Math.min(899,Math.floor((y-m.t)/ph*900))),q=this.data[this.layer*900*4096+t*4096+k],v=this.meta.minimum_db_count2_per_channel+this.meta.scale_db_per_code*q,rf=RFASC[k],bin=BINASC[k];this.tip.style.display='block';this.tip.style.left=`${e.offsetX+18}px`;this.tip.style.top=`${e.offsetY+18}px`;this.tip.textContent=`${this.scan} ADC${this.adc} | t ${t}–${t+1} s | RF ${rf.toFixed(6)} MHz | bin ${bin} | ${v.toFixed(5)} dB(count²/channel)`;this.readout.textContent=this.tip.textContent}export(){let a=document.createElement('a');a.href=this.canvas.toDataURL('image/png');a.download=`stage35-${this.scan}-adc${this.adc}-dynamic.png`;a.click()}}
let DYNAMIC={instances:{},current:null,async load(scan,adc,layer){let box=document.querySelector(`[data-adc="${adc}"]`);if(!this.instances[adc])this.instances[adc]=new DynamicSpectrum(box.querySelector('.dynamic-canvas'),box.querySelector('.dynamic-tooltip'),box.querySelector('.canvas-readout'));this.current=this.instances[adc];await this.current.load(scan,adc,layer)},export(){if(this.current)this.current.export()}};
async function renderADC(adc){await coreData();const box=document.querySelector(`[data-adc="${adc}"]`),s=Number(box.querySelector('.scan').value),scan=SCAN[s],bin=Math.max(0,Math.min(4095,Number(box.querySelector('.bin').value))),q=(f)=>qv(s,adc,bin,f),cd=custom();let band=[],density=[];for(let si=0;si<3;si++){band.push({x:RFASC,y:ordered(si,adc,'mean_power_count2'),name:`Scan ${SCAN[si]}`,mode:'lines',line:{width:1.2,color:colors[si]},customdata:cd,hovertemplate:'RF %{x:.6f} MHz<br>bin %{customdata[0]}<br>P %{y:.10g} count²/channel<extra>%{fullData.name}</extra>'});density.push({x:RFASC,y:ordered(si,adc,'power_density_count2_per_hz'),name:`Scan ${SCAN[si]}`,mode:'lines',line:{width:1.2,color:colors[si]},customdata:cd,hovertemplate:'RF %{x:.6f} MHz<br>bin %{customdata[0]}<br>PSD %{y:.10g} count²/Hz<extra>%{fullData.name}</extra>'})}await draw(`band-${adc}`,band,freqLayout(`ADC${adc}：A/B/C完整4096-bin带通`,'Mean power (count²/PFB channel)'));await draw(`density-${adc}`,density,freqLayout(`ADC${adc}：仪器功率谱密度`,'Power density (count²/Hz)',{yaxis:{title:'Power density (count²/Hz)',type:'log',showgrid:true,gridcolor:'#dce3e9'}}));let zoom=band.map(t=>Object.assign({},t,{x:t.x.slice(1260,1305),y:t.y.slice(1260,1305),customdata:t.customdata.slice(1260,1305)}));await draw(`spur-${adc}`,zoom,freqLayout(`ADC${adc}：960 MHz固定项及邻近bin`,'Mean power (count²/PFB channel)',{xaxis:{title:'RF frequency (MHz)',range:[958.2,961.7],showgrid:true,gridcolor:'#dce3e9'},xaxis2:{title:'global_bin',overlaying:'x',side:'top',range:[958.2,961.7]}}));let zstd=[],zratio=[];for(let ti=0;ti<4;ti++){zstd.push(ordered(s,adc,`integration_std_${[2,4,15,30][ti]}s`));zratio.push(ordered(s,adc,`sigma_ratio_${[2,4,15,30][ti]}s`))}await draw(`sigmaheat-${adc}`,[{type:'heatmap',x:RFASC,y:[2,4,15,30],z:zstd,colorscale:'Viridis',colorbar:{title:{text:'σ_P (count²)'},ticks:'outside'},customdata:Array.from({length:4},()=>BINASC),hovertemplate:'RF %{x:.6f} MHz<br>bin %{customdata}<br>τ %{y} s<br>σ %{z:.9g} count²<extra></extra>'}],freqLayout(`Scan ${scan} ADC${adc}：frequency × τ绝对散布`,'Integration time τ (s)'));await draw(`ratioheat-${adc}`,[{type:'heatmap',x:RFASC,y:[2,4,15,30],z:zratio,colorscale:'Cividis',colorbar:{title:{text:'measured σ / ENBW theory'},ticks:'outside'},hovertemplate:'RF %{x:.6f} MHz<br>τ %{y} s<br>ratio %{z:.7g}<extra></extra>'}],freqLayout(`Scan ${scan} ADC${adc}：frequency × τ实测/理论`,'Integration time τ (s)'));let acf=await typed(`acf-${scan}-${adc}-f32`,Float32Array),av=await typed(`adev-${scan}-${adc}-f32`,Float32Array),acfVariant=Number(box.querySelector('.acfvariant').value),allanVariant=Number(box.querySelector('.allanvariant').value),acfZ=META.acf_lag_seconds.map((_,j)=>RFASC.map((_,i)=>acf[(acfVariant*4096+ORDER[i])*27+j])),avZ=META.allan_seconds.map((_,j)=>RFASC.map((_,i)=>av[(allanVariant*4096+ORDER[i])*12+j]));await draw(`acfheat-${adc}`,[{type:'heatmap',x:RFASC,y:META.acf_lag_seconds,z:acfZ,zmid:0,colorscale:'RdBu',reversescale:true,colorbar:{title:{text:'ACF (dimensionless)'},ticks:'outside'},hovertemplate:'RF %{x:.6f} MHz<br>lag %{y:g} s<br>ACF %{z:.7g}<extra></extra>'}],freqLayout(`Scan ${scan} ADC${adc}：frequency × lag ACF`,'Lag (s)'));await draw(`adevheat-${adc}`,[{type:'heatmap',x:RFASC,y:META.allan_seconds,z:avZ,colorscale:'Viridis',colorbar:{title:{text:'ADEV (count²)'},ticks:'outside'},hovertemplate:'RF %{x:.6f} MHz<br>τ %{y:g} s<br>ADEV %{z:.7g} count²<extra></extra>'}],freqLayout(`Scan ${scan} ADC${adc}：frequency × τ Allan deviation`,'Averaging time τ (s)',{yaxis:{title:'Averaging time τ (s)',type:'log',showgrid:true,gridcolor:'#dce3e9'}}));let tau=[2,4,15,30],measured=tau.map(t=>q(`integration_std_${t}s`)),enbw=tau.map(t=>q(`sigma_enbw_${t}s`)),pfb=tau.map(t=>q(`sigma_pfb_${t}s`)),short=tau.map(t=>q(`sigma_short_${t}s`));await draw(`integration-${adc}`,[{x:tau,y:measured,name:'measured',mode:'lines+markers',line:{color:colors[0],width:3}},{x:tau,y:enbw,name:'ENBW white',mode:'lines+markers',line:{color:colors[1],dash:'dash'}},{x:tau,y:pfb,name:'exact PFB',mode:'lines+markers',line:{color:colors[2],dash:'dot'}},{x:tau,y:short,name:'short covariance',mode:'lines+markers',line:{color:colors[3],dash:'dashdot'}}],cartLayout(`Scan ${scan} ADC${adc} bin ${bin}：积分散布与三种参考`,'Integration time τ (s)','Absolute scatter σ_P(τ) (count²)',{xaxis:{title:'Integration time τ (s)',type:'log',showgrid:true},yaxis:{title:'Absolute scatter σ_P(τ) (count²)',type:'log',showgrid:true}}));let dist=[];for(const t of tau){let series=await typed(`integration-${scan}-${adc}-${t}s-f32`,Float32Array),width={2:450,4:225,15:60,30:30}[t];dist.push({y:Array.from({length:width},(_,i)=>series[bin*width+i]),name:`${t} s`,type:'box',boxpoints:'all',jitter:.25,pointpos:0,marker:{size:3}})}await draw(`integrationdist-${adc}`,dist,cartLayout(`Scan ${scan} ADC${adc} bin ${bin}：2/4/15/30 s完整积分分布`,'Integration time','Integrated power (count²/PFB channel)'));let acfTr=[];['uncentered raw','constant removed','temperature regressed'].forEach((name,vi)=>acfTr.push({x:META.acf_lag_seconds,y:META.acf_lag_seconds.map((_,j)=>acf[(vi*4096+bin)*27+j]),name,mode:'lines+markers'}));await draw(`acfbin-${adc}`,acfTr,cartLayout(`Scan ${scan} ADC${adc} bin ${bin}：ACF三版本`,'Lag (s)','Correlation / normalized second moment'));let adevTr=[];['raw non-overlap','raw overlap','temp-regressed non-overlap','temp-regressed overlap'].forEach((name,vi)=>adevTr.push({x:META.allan_seconds,y:META.allan_seconds.map((_,j)=>av[(vi*4096+bin)*12+j]),name,mode:'lines+markers'}));await draw(`adevbin-${adc}`,adevTr,cartLayout(`Scan ${scan} ADC${adc} bin ${bin}：Allan deviation`,'Averaging time τ (s)','ADEV (count²)',{xaxis:{title:'Averaging time τ (s)',type:'log',showgrid:true},yaxis:{title:'ADEV (count²)',type:'log',showgrid:true}}));let psd=await typed(`psd-${scan}-${adc}-f32`,Float32Array),psdTr=[];['raw','constant removed','temperature regressed'].forEach((name,vi)=>psdTr.push({x:META.psd_frequency_hz,y:META.psd_frequency_hz.map((_,j)=>psd[(vi*4096+bin)*1025+j]),name,mode:'lines',line:{width:1.2}}));await draw(`psdbin-${adc}`,psdTr,cartLayout(`Scan ${scan} ADC${adc} bin ${bin}：temporal PSD`,'Temporal frequency (Hz)','PSD (count⁴/Hz)',{xaxis:{title:'Temporal frequency (Hz)',type:'log',range:[Math.log10(.05),Math.log10(50)],showgrid:true},yaxis:{title:'PSD (count⁴/Hz)',type:'log',showgrid:true}}));let natives=[];for(let si=0;si<3;si++){let n=await typed(`native15-${SCAN[si]}-${adc}-f32`,Float32Array);natives.push({x:Array.from({length:1500},(_,i)=>i*.01),y:Array.from({length:1500},(_,i)=>n[bin*1500+i]),name:`Scan ${SCAN[si]}`,mode:'lines',line:{width:1,color:colors[si]}})}await draw(`native-${adc}`,natives,cartLayout(`ADC${adc} bin ${bin}：A/B/C各15 s全1,500个原生桶`,'Elapsed time in registered window (s)','Mean power (count²/PFB channel)'));await draw(`hist-${adc}`,natives.map((n,i)=>({x:n.y,name:n.name,type:'histogram',opacity:.45,nbinsx:48,histnorm:'probability density'})),cartLayout(`ADC${adc} bin ${bin}：15 s原生桶分布`,'Mean power (count²/PFB channel)','Probability density',{barmode:'overlay'}));let layer=Number(box.querySelector('.dynamiclayer').value);if(!DYNAMIC)DYNAMIC=new DynamicSpectrum(box.querySelector('.dynamic-canvas'),box.querySelector('.dynamic-tooltip'),box.querySelector('.canvas-readout'));await DYNAMIC.load(scan,adc,layer);box.querySelector('.dynamic-export').onclick=()=>DYNAMIC.export();let fact=`Scan ${scan} · ADC${adc} · bin ${bin} · RF ${(RF[bin]/1e6).toFixed(6)} MHz · mean ${fmt(q('mean_power_count2'))} count²/channel · σ(15s)/ENBW ${fmt(q('sigma_ratio_15s'))} · ACF(1s) ${fmt(q('acf_constant_removed_1s'))} · SK ${fmt(q('spectral_kurtosis'))} · temperature R² ${fmt(q('temperature_r2'))}`;box.querySelector('.selected-facts').textContent=fact;box.querySelector('.selected-table').innerHTML='<table><thead><tr><th>τ (s)</th><th>mean</th><th>std</th><th>bootstrap mean CI</th><th>ENBW</th><th>PFB</th><th>short-cov</th><th>measured/ENBW</th></tr></thead><tbody>'+tau.map(t=>`<tr><td>${t}</td><td>${fmt(q(`integration_mean_${t}s`))}</td><td>${fmt(q(`integration_std_${t}s`))}</td><td>[${fmt(q(`integration_ci_low_${t}s`))}, ${fmt(q(`integration_ci_high_${t}s`))}]</td><td>${fmt(q(`sigma_enbw_${t}s`))}</td><td>${fmt(q(`sigma_pfb_${t}s`))}</td><td>${fmt(q(`sigma_short_${t}s`))}</td><td>${fmt(q(`sigma_ratio_${t}s`))}</td></tr>`).join('')+'</tbody></table><p>local log slopes: 2→4 s '+fmt(q('slope_2_4s'))+'; 4→15 s '+fmt(q('slope_4_15s'))+'; 15→30 s '+fmt(q('slope_15_30s'))+' (white reference = −0.5)</p>';box.querySelector('.interpretation').innerHTML=`<b>实测：</b>15 s散布为ENBW理论的 ${fmt(q('sigma_ratio_15s'))} 倍，constant-removed ACF(1 s)=${fmt(q('acf_constant_removed_1s'))}。 <b>温度对照：</b>PL温度线性回归R²=${fmt(q('temperature_r2'))}，只限制该单变量线性模型，不排除未监测、滞后或非线性热机制。 <b>定标限制：</b>不可换算为K、Jy、SEFD、dBm或T<sub>sys</sub>。`;box.dataset.ready='1'}
const renderADCBase=renderADC;renderADC=async function(adc){await renderADCBase(adc);let box=document.querySelector(`[data-adc="${adc}"]`),s=Number(box.querySelector('.scan').value),bin=Number(box.querySelector('.bin').value),mean=qv(s,adc,bin,'mean_power_count2'),white=META.science_story.white_fractional_allan.map(v=>v*mean);await Plotly.addTraces(`adevbin-${adc}`,{x:META.allan_seconds,y:white,name:'ENBW white τ^-1/2',mode:'lines',line:{color:'#17202a',dash:'dash',width:3}});let title=document.getElementById(`adevbin-${adc}`)._fullLayout?.title?.text||'';if(!title.includes('白噪声参考'))await Plotly.relayout(`adevbin-${adc}`,{'title.text':title+' 与白噪声参考'})}
const SCAN=['A','B','C'];document.querySelectorAll('.adc').forEach(box=>{let adc=Number(box.dataset.adc);box.querySelectorAll('select,input').forEach(e=>e.addEventListener('change',()=>renderADC(adc)));box.querySelector('.render').onclick=()=>renderADC(adc);box.querySelectorAll('.preset').forEach(button=>button.onclick=()=>{let bin=META.science_story.adc_presets[String(adc)][button.dataset.preset];box.querySelector('.bin').value=bin;box.querySelectorAll('.preset').forEach(x=>x.classList.toggle('active',x===button));renderADC(adc)});let atlas=box.querySelector('.technical-atlas');if(atlas)atlas.addEventListener('toggle',()=>{if(atlas.open)atlas.querySelectorAll('.js-plotly-plot').forEach(plot=>Plotly.Plots.resize(plot))})});
let CSV=null,ROWS=[],HEADER=[],FILTERED=[],PAGE=0;async function loadCSV(){if(CSV)return;CSV=new TextDecoder().decode(await bytes('metrics-csv'));let lines=CSV.trimEnd().split('\n');HEADER=lines[0].split(',');ROWS=lines.slice(1).map(x=>x.split(','));let sort=document.getElementById('table-sort'),exact=document.getElementById('table-exact-field');HEADER.forEach((x,i)=>{sort.add(new Option(x,String(i)));exact.add(new Option(x,String(i)))});let dict=Object.fromEntries(META.data_dictionary.map(x=>[x[0],x])),groups={};HEADER.forEach((x,i)=>{let g=(dict[x]||[])[2]||'quality';(groups[g]??=[]).push([x,i])});document.getElementById('table-columns').innerHTML=Object.entries(groups).map(([g,items])=>`<fieldset><legend>${g}</legend>${items.map(([x,i])=>`<label><input type="checkbox" value="${i}" ${i<18?'checked':''}>${x}</label>`).join(' ')}</fieldset>`).join('')}
async function searchTable(){await loadCSV();let scan=document.getElementById('table-scan').value,adc=document.getElementById('table-adc').value,b0=+document.getElementById('table-bin0').value,b1=+document.getElementById('table-bin1').value,si=HEADER.indexOf('scan_label'),ai=HEADER.indexOf('adc_id'),bi=HEADER.indexOf('global_bin'),exactField=+document.getElementById('table-exact-field').value,exactValue=document.getElementById('table-exact-value').value,sort=+document.getElementById('table-sort').value,desc=document.getElementById('table-desc').checked;FILTERED=ROWS.filter(r=>(scan==='*'||r[si]===scan)&&(adc==='*'||r[ai]===adc)&&+r[bi]>=b0&&+r[bi]<=b1&&(exactValue===''||r[exactField]===exactValue));FILTERED.sort((a,b)=>{let x=Number(a[sort]),y=Number(b[sort]);let c=Number.isFinite(x)&&Number.isFinite(y)?x-y:String(a[sort]).localeCompare(String(b[sort]));return desc?-c:c});PAGE=0;renderTable()}
function renderTable(){let cols=Array.from(document.querySelectorAll('#table-columns input:checked'),x=>+x.value),size=100,start=PAGE*size,rows=FILTERED.slice(start,start+size),out='<table><thead><tr>'+cols.map(i=>`<th>${HEADER[i]}</th>`).join('')+'</tr></thead><tbody>';for(let r of rows)out+='<tr>'+cols.map(i=>`<td>${r[i]}</td>`).join('')+'</tr>';document.getElementById('table-out').innerHTML=out+'</tbody></table>';document.getElementById('table-status').textContent=`完整匹配 ${FILTERED.length.toLocaleString()} 行；第 ${PAGE+1}/${Math.max(1,Math.ceil(FILTERED.length/size))} 页；当前 ${rows.length} 行`}
function download(name,text,type='text/csv'){let a=document.createElement('a');a.href=URL.createObjectURL(new Blob([text],{type}));a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000)}
document.getElementById('table-search').onclick=searchTable;document.getElementById('table-prev').onclick=()=>{if(PAGE>0){PAGE--;renderTable()}};document.getElementById('table-next').onclick=()=>{if((PAGE+1)*100<FILTERED.length){PAGE++;renderTable()}};document.getElementById('table-export-csv').onclick=()=>download('stage35-v2-filtered.csv',[HEADER.join(','),...FILTERED.map(r=>r.join(','))].join('\n')+'\n');document.getElementById('table-export-json').onclick=()=>download('stage35-v2-filtered.json',JSON.stringify(FILTERED.map(r=>Object.fromEntries(HEADER.map((h,i)=>[h,r[i]]))),null,2),'application/json');
Promise.all([renderStory(),renderGlobal(),coreData()]).then(()=>{let first=document.querySelector('.adc');first.open=true;renderADC(Number(first.dataset.adc));searchTable()});
"""


def figure(number: str, title: str, plot_id: str, caption: str, tall: bool = False) -> str:
    return f'<section class="figure"><h3><span class="figure-number">图{number}</span> {title}</h3><div id="{plot_id}" class="plot{" tall" if tall else ""}"></div><div id="{plot_id}-stats" class="figure-stats"></div><p class="caption">{caption}</p></section>'


def adc_section(adc: int, science: dict[str, Any], story: dict[str, Any]) -> str:
    summary = science["per_adc"][adc]
    presets = story["adc_presets"][str(adc)]
    summary_text = (
        f"<b>ADC{adc}一句话：</b>把960 MHz等预标记点拿开后，宽带相关噪声仍然存在。"
        f"全频带15 s实测散布/白噪声中位数为 "
        f"{summary['sigma_ratio_15s']['median']:.6g}（P05 {summary['sigma_ratio_15s']['p05']:.6g}，"
        f"P95 {summary['sigma_ratio_15s']['p95']:.6g}）；|ACF(1 s)|中位数 "
        f"{summary['acf_constant_removed_1s_abs']['median']:.6g}；扫描间分数散布中位数 "
        f"{summary['between_scan_fractional_std']['median']:.6g}。"
    )
    return f"""<details class="adc" data-adc="{adc}" id="adc-{adc}"><summary>ADC{adc}：先看积分是否有效，再看完整技术图谱</summary>
<p class="adc-summary finding">{summary_text}</p>
<div class="controls"><b>一键看真实频点：</b><button class="preset active" data-preset="representative">普通代表 bin {presets['representative']}</button><button class="preset" data-preset="worst_integration">积分最差 bin {presets['worst_integration']}</button><button class="preset" data-preset="strongest_memory">记忆最强 bin {presets['strongest_memory']}</button><button class="preset" data-preset="fixed_960mhz">960 MHz</button><label>自定义 global_bin<input class="bin" type="number" min="0" max="4095" value="{presets['representative']}"></label><label>扫描<select class="scan"><option value="0">A</option><option value="1">B</option><option value="2">C</option></select></label><button class="render">刷新本章</button></div>
<div class="controls muted"><label>ACF热图版本<select class="acfvariant"><option value="1">去掉常数均值</option><option value="0">未中心化原值</option><option value="2">PL温度回归后</option></select></label><label>Allan热图版本<select class="allanvariant"><option value="1">原始重叠</option><option value="0">原始非重叠</option><option value="3">温度回归后重叠</option><option value="2">温度回归后非重叠</option></select></label><label>动态谱层<select class="dynamiclayer"><option value="1">1 s均值</option><option value="0">1 s最小值</option><option value="2">1 s最大值</option></select></label></div>
<p class="selected-facts finding"></p><p class="interpretation impact"></p><div class="selected-table scroll"></div>
{figure(f'{adc}.1', '这个频点继续积分有没有用：实测散布与白噪声参考', f'integration-{adc}', '<b>怎么读：</b>黑色/虚线参考按白噪声下降；实测曲线越高、越平，继续观测换来的灵敏度越少。')}
{figure(f'{adc}.2', '这个频点有没有记忆：ACF三种处理方式', f'acfbin-{adc}', '<b>怎么读：</b>滞后不为0时仍明显偏离0，表示先前的高低会影响后面的高低；温度版只检验PL温度即时线性项。')}
{figure(f'{adc}.3', 'Allan曲线与τ⁻¹ᐟ²白噪声参考', f'adevbin-{adc}', '<b>怎么读：</b>理想白噪声在双对数图上沿斜率−0.5下降；变平表示积分收益不足，向上表示漂移增强。')}
<details class="technical-atlas"><summary>展开完整频谱、动态谱、热图、PSD和分布附录</summary>
<div class="figure-grid">{figure(f'{adc}.4', 'A/B/C全4096-bin带通', f'band-{adc}', '<b>证据：</b>900 s平均功率，完整保留全部bin；下轴RF MHz，上轴global_bin。')}{figure(f'{adc}.5', '功率谱密度', f'density-{adc}', '<b>限制：</b>count²/Hz是仪器数字单位，不是W/Hz或dBm/Hz。')}{figure(f'{adc}.6', '960 MHz固定项及邻近bin', f'spur-{adc}', '<b>结论：</b>固定窄带项非常严重，但不能解释全带积分效率下降。')}</div>
<section class="figure"><h3><span class="figure-number">图{adc}.4</span> A/B/C全900 s动态谱：1 s min/mean/max</h3><div class="controls"><button class="dynamic-export">导出当前动态谱PNG</button><span class="canvas-readout">移动鼠标查看时间、RF MHz、bin和数值</span></div><div class="dynamic-wrap"><canvas class="dynamic-canvas"></canvas><div class="dynamic-tooltip"></div></div><p class="caption"><b>测量：</b>每个1 s窗内全100个10 ms桶的minimum/mean/maximum。 <b>色标：</b>10 log₁₀(P/[1 count²/channel])，不是dBm。 <b>数值：</b>光标读数显示在图上和顶部。 <b>限制：</b>uint16只是渲染编码，误差在账本中逐层记录，不参与统计。</p></section>
<div class="figure-grid">{figure(f'{adc}.5', 'frequency × τ绝对散布', f'sigmaheat-{adc}', '<b>测量：</b>2/4/15/30 s非重叠积分的绝对散布。 <b>色标单位：</b>count²。')}{figure(f'{adc}.6', 'frequency × τ实测/理论', f'ratioheat-{adc}', '<b>测量：</b>实测散布除以ENBW白噪声参考。 <b>读图：</b>1代表该参考下的理想白噪声缩放。')}{figure(f'{adc}.7', 'frequency × lag ACF', f'acfheat-{adc}', '<b>测量：</b>功率时间记忆。 <b>色标：</b>无量纲ACF，以0为中心。 <b>限制：</b>raw/constant/temperature版本必须显式切换。')}{figure(f'{adc}.8', 'frequency × τ Allan deviation', f'adevheat-{adc}', '<b>测量：</b>不同平均时间的ADEV。 <b>色标单位：</b>count²；overlap/non-overlap不混合。')}</div>
<div class="figure-grid">{figure(f'{adc}.9', '2/4/15/30 s完整积分分布', f'integrationdist-{adc}', '<b>证据：</b>显示全部非重叠积分样本，不用箱线摘要代替原数据。')}{figure(f'{adc}.10', 'temporal PSD', f'psdbin-{adc}', '<b>用途：</b>查看慢变化集中在哪些时间频率；单位count⁴/Hz。')}{figure(f'{adc}.11', 'A/B/C各15 s全原生桶', f'native-{adc}', '<b>数据：</b>每次扫描1500/1500个10 ms桶全部显示。')}{figure(f'{adc}.12', '15 s原生桶分布', f'hist-{adc}', '<b>注意：</b>分布图不替代完整时序和相关性分析。')}</div>
</details></details>"""


def anomaly_table(rows: list[dict[str, Any]], adc_filter: int | None = None) -> str:
    selected = [row for row in rows if adc_filter is None or row["adc_id"] == adc_filter]
    return "".join(
        f"<tr><td>ADC{r['adc_id']}</td><td>{html.escape(r['metric'])}</td><td>{r['rank']}</td>"
        f"<td>{r['rf_mhz']:.6f}</td><td>{r['global_bin']}</td><td>{r['ranking_value']:.9g}</td>"
        f"<td>{r['scan_a']:.9g}</td><td>{r['scan_b']:.9g}</td><td>{r['scan_c']:.9g}</td>"
        f"<td>{html.escape(r['scan_value_unit'])}</td></tr>" for r in selected
    )


def fixed_item_table(rows: list[dict[str, Any]]) -> str:
    return "".join(
        f"<tr><td>ADC{r['adc_id']}</td><td>{r['rf_mhz']:.6f}</td><td>{r['global_bin']}</td>"
        f"<td>{r['mean_power_a']:.9g}</td><td>{r['mean_power_b']:.9g}</td><td>{r['mean_power_c']:.9g}</td>"
        f"<td>{r['sigma_ratio_a']:.7g}</td><td>{r['sigma_ratio_b']:.7g}</td><td>{r['sigma_ratio_c']:.7g}</td></tr>" for r in rows
    )


def make_html(meta: dict[str, Any], tags: Iterable[str], plotly_js: str, license_text: str) -> str:
    story = meta["science_story"]
    headline = story["headline"]
    dictionary = "".join(f"<tr><td>{html.escape(row[0])}</td><td>{html.escape(row[1])}</td><td>{html.escape(row[2])}</td><td>{html.escape(row[3])}</td><td>{html.escape(row[4])}</td></tr>" for row in meta["data_dictionary"])
    sections = "".join(adc_section(adc, meta["science"], story) for adc in meta["detail_adcs"])
    adu_rows = "".join(
        f"<tr><td>ADC{row['adc_id']}</td>"
        f"<td>{min(row['components']['I']['q16'], row['components']['Q']['q16'])}…{max(row['components']['I']['q84'], row['components']['Q']['q84'])}</td>"
        f"<td>{min(row['components']['I']['q025'], row['components']['Q']['q025'])}…{max(row['components']['I']['q975'], row['components']['Q']['q975'])}</td>"
        f"<td>{row['minimum_30s']}…{row['maximum_30s']}</td><td>{row['clip_count']}</td></tr>"
        for row in story["adu"]["adcs"]
    )
    report_meta = {**meta, "payload_index": {p["name"]: p for p in meta["payloads"]}}
    tags_text = "\n".join(tags)
    mode_label = "真实数据样章（全局 + ADC0）" if meta["mode"] == "sample" else "A/B/C × ADC0–7 正式完整版"
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>50 Ω噪声：积分为什么没有按白噪声变好</title><style>{CSS}</style><script>{plotly_js.replace('</script>','<\\/script>')}</script></head><body><header><div class="eyebrow">T510 RADIO ASTRONOMY · STAGE 35 / S2</div><h1>50 Ω噪声：积分为什么没有按白噪声变好</h1><p class="subtitle">{mode_label} · 面向科研读者的未定标报告</p><span class="badge">离线单文件</span><span class="badge">全频带真实数据</span><span class="badge">Allan + ACF + ADU</span></header><main>
<section class="warning"><b>这份报告能说什么：</b>它能说数字码值是多少、噪声有没有记忆、积分收益离白噪声有多远。定标尚未完成，因此不把它换算成 K、Jy、SEFD、dBm 或系统温度。</section>
<nav class="card toc"><b>从上到下回答五个问题</b><br><a href="#summary">1. 先说结论</a><br><a href="#adu">2. ADC实际测到多少 ADU</a><br><a href="#allan">3. Allan图怎么看，白噪声应该什么样</a><br><a href="#correlation">4. 相关噪声怎么看</a><br><a href="#frequency">5. 哪些频率和ADC最严重</a><br><a href="#detail">6. 逐ADC真实频点</a><br><a href="#technical">7. 完整技术附录</a></nav>
<section id="summary"><h2>1. 先说结论</h2><div class="verdict"><strong>直接批评：</strong>这组 50 Ω 数据在科学积分尺度上不是理想白噪声。更久地积分确实有收益，但收益远慢于白噪声应有的速度；而且这不是 960 MHz 一个尖峰把统计抬坏了。</div>
<div class="summary-grid"><div class="metric problem"><b>15 s实测 / 白噪声</b><div class="value">{headline['ratio_15s']:.3f}×</div><div>理想 {headline['ideal_fractional_15s_percent']:.5f}%；实测中位 {headline['measured_fractional_15s_percent']:.5f}%</div></div><div class="metric problem"><b>15 s只换来多少有效白噪声时间</b><div class="value">{headline['equivalent_white_time_15s']:.2f} s</div><div>积分效率 {100*headline['radiometer_efficiency_15s']:.1f}%；同等灵敏度的时间代价 {headline['white_time_penalty_15s']:.1f}×</div></div><div class="metric problem"><b>2 s → 30 s的改善</b><div class="value">{headline['paired_gain_2s_to_30s']:.2f}×</div><div>白噪声应改善 {headline['ideal_gain_2s_to_30s']:.2f}×</div></div><div class="metric problem"><b>30 s时反而离理想更远</b><div class="value">{headline['ratio_30s']:.3f}×</div><div>理想 {headline['ideal_fractional_30s_percent']:.5f}%；实测 {headline['measured_fractional_30s_percent']:.5f}%</div></div></div>
<p class="finding"><b>不是单个 spur：</b>排除预先标记的 DC、频带边界、960 MHz 及邻 bin 后，15 s中位仍是白噪声的 {headline['ratio_15s_preflagged_excluded']:.4f}×。这支持“宽带问题”，但本报告不猜没有证据的物理根因。</p></section>
<section id="adu"><h2>2. ADC实际测到多少 ADU</h2><p class="plain"><b>ADU就是数字化后的整数码值。</b>这里不先谈 RMS：直接数六次 TIME 控制段中每个 I/Q 样本落在哪个 ADU 上。I 和 Q 都以 0 ADU 为中心，大部分样本落在约 ±4–5 ADU，95% 约在 ±8–9 ADU；30 s 内最远大致到 −30…+31 ADU，没有削顶。</p>
<div class="concept-flow"><span>ADU<br><small>电压数字</small></span><i>→</i><span>I²+Q²<br><small>数字功率</small></span><i>→</i><span>PFB<br><small>分成频率通道</small></span><i>→</i><span>时间积分<br><small>压低随机波动</small></span><i>→</i><span>天文灵敏度<br><small>能看见多弱的信号</small></span></div>
{figure('2.1','六次TIME控制的完整ADU码值直方图','adu-hist','<b>证据：</b>每个ADC合并六段I/Q原始码值，每个分量96,000,000样本。 <b>天文影响：</b>这是后续数字功率的起点，它证明码值居中且未削顶。 <b>尚不能归因：</b>码值正常不等于时间噪声必然是白的。',True)}
<div class="scroll"><table><thead><tr><th>ADC</th><th>中间68%约范围 (ADU)</th><th>中间95%约范围 (ADU)</th><th>30 s全段极值 (ADU)</th><th>削顶样本</th></tr></thead><tbody>{adu_rows}</tbody></table></div>
<p class="warning"><b>重要边界：</b>这是 post-DDC IQ16 ADU，不是 ADC 每秒 3.84 Gsample 的原始码。它们接着变成 I²+Q² 和 PFB 频道功率；定标之前不能再换成 K、Jy 或 SEFD。</p></section>
<section id="allan"><h2>3. Allan图怎么看，白噪声应该什么样</h2><p class="plain">把积分想成长曝光：<b>白噪声</b>像每帧都不同的随机颗粒，曝光越久，它应按平方根速度消失。<b>相关噪声</b>像背景亮度在慢慢漂，多拍几张也不会同样有效地抵消。Allan图就是看不同“曝光时间”下这种变化。</p>
<div class="reading-key"><div><b>向下，斜率 −0.5</b><br>ADEV ∝ τ^-1/2：理想白噪声，时间增加4倍，散布约减半。</div><div><b>越来越平</b><br>继续积分的收益接近停止。</div><div><b>向上</b><br>慢漂移开始占主导，观测越久反而越不稳。</div></div><div id="story-ready" class="status">正在从全部数据渲染ADU、Allan和ACF…</div>
{figure('3.1','全98,304个ADC/bin/scan的Allan表现','allan-global','<b>证据：</b>包络是P05–P95，粗线是中位，1是同带宽白噪声预期。 <b>天文影响：</b>曲线高于1且随τ升高，表示长积分没有追上理想灵敏度。 <b>尚不能归因：</b>这张图定量证明非白噪声，不单独指认物理源。',True)}
{figure('3.2','三个真实频点：普通、948.593750 MHz与960.000000 MHz','allan-examples','<b>证据：</b>每条实测曲线与τ^-1/2白噪声参考同图。 <b>天文影响：</b>普通频点也并非完美；960 MHz的固定记忆则强得多。 <b>尚不能归因：</b>“异常簇”和“固定项”是数据描述，不是物理根因诊断。',True)}
{figure('3.3','积分时间与实际灵敏度收益','integration-story','<b>证据：</b>15 s理想相对散布为0.09698%，实测中位为0.36999%。 <b>天文影响：</b>同等灵敏度需要约14.6倍的白噪声时间代价。 <b>尚不能归因：</b>这是当前50 Ω、未定标工作点的数字积分效率，不是天线上天性源的最终灵敏度。',True)}</section>
<section id="correlation"><h2>4. 相关噪声怎么看</h2><p class="plain">ACF做的事很直接：把原序列与延迟一段时间的自己比较，看它们是否仍然“同涨同跌”。白噪声除了极短的PFB记忆外应迅速回到0；延迟1 s还明显不为0，就是秒级记忆的直观证据。</p>
{figure('4.1','原序列与延迟序列是否仍同涨同跌','acf-story',f'<b>证据：</b>全数据 |ACF(1 s)| 中位 {headline["acf_1s_median_abs"]:.4f}，P95 {headline["acf_1s_p95_abs"]:.4f}；960 MHz个别扫描可达约0.6–0.85。 <b>天文影响：</b>有记忆的误差不能靠简单延长观测按平方根消掉。 <b>尚不能归因：</b>ACF只说明“有记忆”，不直接告诉我们记忆来自时钟、供电、温度还是别的环节。',True)}
<p class="finding"><b>PL温度排查：</b>即时单变量线性回归的R²中位仅 {headline['temperature_r2_median']:.6f}。直白地说：<b>当前PL温度单变量模型解释不了问题</b>；但这不是“已排除温度”。</p></section>
<section id="frequency"><h2>5. 哪些频率和ADC最严重</h2><div id="global-ready" class="status">正在解压全局指标…</div>{figure('5.1','先看八路带通中的固定结构','global-bandpass','<b>证据：</b>A/B/C三次900 s扫描平均后的8路完整4096-bin带通。 <b>天文影响：</b>窄带固定项需要标记或校正，否则会伪装成频谱结构。 <b>尚不能归因：</b>未定标带通不单独确定这些结构的物理来源。',True)}{figure('5.2','每个ADC、每个频点的15 s积分亏损','global-sigma','<b>证据：</b>色标是实测散布/白噪声，1才是理想。 <b>天文影响：</b>数值越大，同样的观测时间换来的灵敏度越差。 <b>尚不能归因：</b>这是结果地图，不是故障根因地图。',True)}{figure('5.3','A/B/C三次扫描之间哪里最不稳定','global-repro','<b>证据：</b>三次900 s平均功率的相对变化。 <b>天文影响：</b>跨扫描变化会使分开时段的天文数据更难直接比较。 <b>尚不能归因：</b>它不等于单次扫描内的快噪声。',True)}</section>
<section id="detail"><h2>6. 逐ADC选一个真实频点看证据</h2><p>“普通代表”从无质量标记的bin中稳健选出；“积分最差”和“记忆最强”按三扫描中位排序，并列取较小global_bin。样章只生成ADC0的大体积数据；用户审阅后才生成ADC0–7全量版。</p>{sections}</section>
<section id="technical"><h2>7. 完整技术附录</h2><details><summary>展开异常排名、960 MHz表、方法和完整数值浏览器</summary><h3>异常bin导航</h3><p>每项给出A/B/C实测值；排名用于找问题，不作物理归因。</p><div class="scroll"><table><thead><tr><th>ADC</th><th>排名依据</th><th>rank</th><th>RF MHz</th><th>global_bin</th><th>排名值</th><th>A</th><th>B</th><th>C</th><th>单位</th></tr></thead><tbody>{anomaly_table(meta['science']['anomalies'])}</tbody></table></div><h3>960 MHz固定项</h3><div class="scroll"><table><thead><tr><th>ADC</th><th>RF MHz</th><th>global_bin</th><th>A power</th><th>B power</th><th>C power</th><th>A σ15/ENBW</th><th>B σ15/ENBW</th><th>C σ15/ENBW</th></tr></thead><tbody>{fixed_item_table(meta['science']['fixed_items_960mhz'])}</tbody></table></div>
<h3>方法边界</h3><div class="card"><ul><li>Allan主图使用全部A/B/C × 8 ADC × 4096 bin的原始重叠ADEV，12个τ从10 ms到30 s。</li><li>2/4/15/30 s使用完整非重叠积分序列；ACF主视野为0–15 s。</li><li>统计使用全部有效桶，不填零、不插值、不以频率抽点计算。</li><li>预标记bin为{html.escape(str(story['preflagged_bins']))}；同时保留未删除全带结果。</li><li>TIME与SPEC是相邻控制观测，不解释成同时因果对照。</li></ul></div>
<h3>完整数值表与数据字典</h3><div class="scroll"><table class="dictionary"><thead><tr><th>field</th><th>中文名称</th><th>分组</th><th>单位</th><th>定义</th></tr></thead><tbody>{dictionary}</tbody></table></div><div class="controls"><label>scan<select id="table-scan"><option>*</option><option>A</option><option>B</option><option>C</option></select></label><label>ADC<select id="table-adc"><option>*</option>{''.join(f'<option>{x}</option>' for x in meta['table_adcs'])}</select></label><label>bin from<input id="table-bin0" type="number" min="0" max="4095" value="0"></label><label>to<input id="table-bin1" type="number" min="0" max="4095" value="4095"></label><label>精确匹配列<select id="table-exact-field"></select></label><label>精确值<input id="table-exact-value" type="text" placeholder="留空=不限制"></label><label>排序<select id="table-sort"></select></label><label><input id="table-desc" type="checkbox">降序</label><button id="table-search">检索</button><button id="table-prev">上一页</button><button id="table-next">下一页</button><button id="table-export-csv">无截断导出筛选CSV</button><button id="table-export-json">无截断导出筛选JSON</button></div><details><summary>按字段组选择显示列</summary><div id="table-columns"></div></details><p id="table-status" class="status"></p><div id="table-out" class="scroll"></div><div class="card provenance"><b>分析manifest SHA-256：</b><code>{meta['analysis_manifest_sha256']}</code><br><b>Plotly.js：</b>4.0.0 · SHA-256 <code>{meta['plotly_sha256']}</code><br><b>Plotly license：</b><pre>{html.escape(license_text)}</pre></div></details></section>
</main><script type="application/json" id="report-meta">{json.dumps(report_meta,separators=(',',':')).replace('</','<\\/')}</script>\n{tags_text}\n<script>{JS}</script></body></html>"""


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--mode", choices=("sample", "full"), required=True)
    parser.add_argument("--plotly-js", type=Path, required=True)
    parser.add_argument("--plotly-license", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    config = load_json(args.config)
    if config.get("format") != "T510_STAGE35_S2_REPORT_CONFIG_V2":
        raise RuntimeError("unexpected report config")
    root = Path(config["analysis_root"])
    if sha256_file(root / "analysis_manifest.json") != config["analysis_manifest_sha256"]:
        raise RuntimeError("analysis manifest identity mismatch")
    if sha256_file(args.plotly_js) != config["plotly"]["sha256"]:
        raise RuntimeError("Plotly bundle identity mismatch")
    if sha256_file(args.plotly_license) != config["plotly"]["license_sha256"]:
        raise RuntimeError("Plotly license identity mismatch")
    analysis_config = load_json(root / "analysis_config.json")
    meta, tags = build_payloads(root, analysis_config, config, args.mode)
    meta.update({
        "analysis_root": str(root), "analysis_manifest_sha256": config["analysis_manifest_sha256"],
        "queue_manifest_sha256": config["queue_manifest_sha256"], "report_config": config,
        "plotly_sha256": config["plotly"]["sha256"],
    })
    document = make_html(meta, tags, args.plotly_js.read_text(encoding="utf-8"), args.plotly_license.read_text(encoding="utf-8"))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists() or args.output.with_suffix(args.output.suffix + ".partial").exists():
        raise FileExistsError(f"refusing to overwrite report or partial output: {args.output}")
    partial = args.output.with_suffix(args.output.suffix + ".partial")
    partial.write_text(document, encoding="utf-8")
    with partial.open("rb") as stream:
        os.fsync(stream.fileno())
    partial.replace(args.output)
    report_sha = sha256_file(args.output)
    report_manifest = {
        "format": "T510_STAGE35_S2_HTML_REPORT_MANIFEST_V2", "schema_version": 2,
        "complete": True, "mode": args.mode,
        "report": {"path": str(args.output), "bytes": args.output.stat().st_size, "sha256": report_sha},
        "generator": {"path": str(Path(__file__).resolve()), "sha256": sha256_file(Path(__file__).resolve())},
        "config": {"path": str(args.config.resolve()), "sha256": sha256_file(args.config)},
        "analysis_manifest_sha256": config["analysis_manifest_sha256"],
        "plotly": config["plotly"], "payloads": meta["payloads"],
        "time_histograms": meta["science_story"]["adu"]["sources"],
        "science_story": meta["science_story"],
        "metrics_csv_rows": meta["metrics_csv_rows"], "figure_contracts": meta["figure_contracts"],
    }
    manifest_path = args.output.with_suffix(args.output.suffix + ".manifest.json")
    write_json(manifest_path, report_manifest)
    args.output.with_suffix(args.output.suffix + ".sha256").write_text(f"{report_sha}  {args.output.name}\n", encoding="ascii")
    manifest_path.with_suffix(manifest_path.suffix + ".sha256").write_text(f"{sha256_file(manifest_path)}  {manifest_path.name}\n", encoding="ascii")
    print(json.dumps({"status":"PASS","mode":args.mode,"report":str(args.output),"bytes":args.output.stat().st_size,"sha256":report_sha,"payloads":len(meta["payloads"]),"metrics_csv_rows":meta["metrics_csv_rows"]},indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
