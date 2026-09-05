#!/usr/bin/env python3
"""Read-only, server-backed Stage 35 human explorer."""

from __future__ import annotations

import argparse
import csv
import functools
import io
import json
import math
import mimetypes
import os
import sys
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pyarrow.parquet as pq


DATA_ROOT = Path("/var/lib/t510/stage35").resolve()
ADC_PAIRS = tuple((a, b) for a in range(8) for b in range(a + 1, 8))
PAIR_INDEX = {pair: index for index, pair in enumerate(ADC_PAIRS)}
MAX_LAG = 512
ALLAN_TAU_FENGINE = (0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1, 2, 4, 8, 15, 30)
ACF_LAG_FENGINE = (
    0, .01, .02, .03, .04, .05, .06, .07, .08, .09, .1, .11, .12, .13,
    .14, .15, .16, .17, .18, .19, .2, .5, 1, 2, 4, 8, 15,
)


def fixed_path(value: str | Path, *, file: bool = False) -> Path:
    path = Path(value).resolve(strict=True)
    if path != DATA_ROOT and DATA_ROOT not in path.parents:
        raise ValueError(f"path escapes fixed Stage 35 data root: {path}")
    if file and not path.is_file():
        raise ValueError(f"required file is missing: {path}")
    return path


def parse_ints(query: dict[str, list[str]], name: str, low: int, high: int,
               maximum: int, default: Iterable[int]) -> list[int]:
    text = query.get(name, [",​".join(str(value) for value in default)])[0]
    text = text.replace("​", "")
    values = []
    for item in text.split(","):
        if not item.strip():
            continue
        value = int(item)
        if not low <= value <= high:
            raise ValueError(f"{name} values must be within {low}..{high}")
        if value not in values:
            values.append(value)
    if not values or len(values) > maximum:
        raise ValueError(f"{name} must contain 1..{maximum} unique values")
    return values


def parse_bins(query: dict[str, list[str]], maximum: int = 32,
               default: Iterable[int] = (295,), center_mhz: float = 1020.0) -> list[int]:
    """Accept global bins or explicit RF tokens such as 960.000000MHz."""
    text = query.get("bins", [",".join(str(value) for value in default)])[0]
    values: list[int] = []
    for raw in text.split(","):
        token = raw.strip().lower().replace(" ", "")
        if not token:
            continue
        if token.endswith("mhz"):
            rf_mhz = float(token[:-3])
            signed = int(round((rf_mhz - center_mhz) / 0.078125))
            if not -2048 <= signed <= 2047:
                low, high = center_mhz - 160.0, center_mhz + 159.921875
                raise ValueError(f"RF MHz must lie on the {low:.6f}..{high:.6f} MHz band")
            actual = center_mhz + signed * 0.078125
            if abs(actual - rf_mhz) > 1e-6:
                raise ValueError(f"RF {rf_mhz} MHz is not on the 0.078125 MHz channel grid")
            value = signed % 4096
        else:
            token = token.removeprefix("global_bin:").removeprefix("bin:").removeprefix("b")
            value = int(token)
            if not 0 <= value <= 4095:
                raise ValueError("global_bin must be within 0..4095")
        if value not in values:
            values.append(value)
    if not values or len(values) > maximum:
        raise ValueError(f"bins must contain 1..{maximum} unique global_bin/RF selections")
    return values


def parse_scans(query: dict[str, list[str]]) -> list[str]:
    values = [item.strip().upper() for item in query.get("scans", ["A"])[0].split(",")]
    if not values or any(value not in ("A", "B", "C") for value in values):
        raise ValueError("scans must be a comma-separated subset of A,B,C")
    return list(dict.fromkeys(values))


def parse_pairs(query: dict[str, list[str]]) -> list[tuple[int, int]]:
    values: list[tuple[int, int]] = []
    for item in query.get("pairs", ["0-1"])[0].split(","):
        parts = item.strip().split("-")
        if len(parts) != 2:
            raise ValueError("pairs must look like 0-1,2-3")
        pair = tuple(sorted((int(parts[0]), int(parts[1]))))
        if pair not in PAIR_INDEX:
            raise ValueError(f"invalid ADC pair {item}")
        if pair not in values:
            values.append(pair)
    if not values or len(values) > 28:
        raise ValueError("pairs must contain 1..28 unique ADC pairs")
    return values


def overlapping_adev(values: np.ndarray, bucket_seconds: float,
                      taus: Iterable[float]) -> list[float | None]:
    values = np.asarray(values, dtype=np.float64)
    result: list[float | None] = []
    cumulative = np.concatenate(([0.0], np.cumsum(values)))
    for tau in taus:
        width = max(1, int(round(float(tau) / bucket_seconds)))
        if 2 * width > len(values):
            result.append(None)
            continue
        means = (cumulative[width:] - cumulative[:-width]) / width
        delta = means[width:] - means[:-width]
        result.append(float(np.sqrt(0.5 * np.mean(delta * delta))))
    return result


def centered_acf(values: np.ndarray, bucket_seconds: float,
                 lags: Iterable[float]) -> list[float | None]:
    centered = np.asarray(values, dtype=np.float64) - float(np.mean(values))
    variance = float(np.mean(centered * centered))
    result: list[float | None] = []
    for lag in lags:
        shift = int(round(float(lag) / bucket_seconds))
        if shift == 0:
            result.append(1.0 if variance > 0 else None)
        elif shift >= len(centered) or variance <= 0:
            result.append(None)
        else:
            result.append(float(np.mean(centered[:-shift] * centered[shift:]) / variance))
    return result


def integration_scatter(values: np.ndarray, bucket_seconds: float,
                        taus: Iterable[float] = (2, 4, 15, 30)) -> list[dict[str, Any]]:
    values = np.asarray(values)
    output = []
    for tau in taus:
        width = max(1, int(round(float(tau) / bucket_seconds)))
        count = len(values) // width
        if count < 2:
            output.append({"tau_s": tau, "count": count, "std_re": None, "std_im": None})
            continue
        blocks = values[: count * width].reshape(count, width).mean(axis=1)
        output.append({
            "tau_s": tau,
            "count": count,
            "std_re": float(np.std(blocks.real, ddof=1)),
            "std_im": float(np.std(blocks.imag, ddof=1)),
        })
    return output


def spectral_summary(values: np.ndarray, bucket_seconds: float) -> dict[str, list[float]]:
    values = np.asarray(values)
    centered = values - np.mean(values)
    window = np.hanning(len(values))
    transformed = np.fft.rfft(centered.real * window)
    transformed_im = np.fft.rfft(centered.imag * window)
    frequency = np.fft.rfftfreq(len(values), bucket_seconds)
    stride = max(1, len(frequency) // 512)
    return {
        "frequency_hz": frequency[1::stride].tolist(),
        "psd_re": (np.abs(transformed[1::stride]) ** 2).tolist(),
        "psd_im": (np.abs(transformed_im[1::stride]) ** 2).tolist(),
    }


class ExplorerData:
    def __init__(self, config_path: Path, helper_dir: Path):
        self.config_path = config_path.resolve(strict=True)
        self.config = json.loads(self.config_path.read_text(encoding="utf-8"))
        sys.path.insert(0, str(helper_dir.resolve(strict=True)))
        import t510_stage35_s2_html_report_v2 as report_v2

        self.report_v2 = report_v2
        self.analysis_root = fixed_path(self.config["analysis_root"])
        self.report_config = json.loads(
            fixed_path(self.config["report_config"], file=True).read_text(encoding="utf-8")
        )
        self.quick, self.cross_scan, self.rf_hz = report_v2.load_quick(self.analysis_root)
        self.story = report_v2.build_science_story(
            self.analysis_root, self.quick, self.cross_scan, rf_hz=self.rf_hz
        )
        self.center_mhz = float(self.rf_hz[0] / 1e6)
        time_metrics_table = pq.read_table(self.analysis_root / "time_control_metrics.parquet")
        self.time_metrics = time_metrics_table.to_pylist()
        self.time_rows = pq.read_table(self.analysis_root / "time_control_10ms_series.parquet").to_pylist()
        self.time_by_key = {
            (str(row["control_label"]), int(row["adc_id"])): row for row in self.time_rows
        }
        self.adu_story = report_v2.load_time_histograms(self.report_config, self.time_metrics)
        self.raw_manifest_path = fixed_path(self.config["raw_index_manifest"], file=True)
        self.raw_manifest = json.loads(self.raw_manifest_path.read_text(encoding="utf-8"))
        self.spec_scans = {key: fixed_path(value) for key, value in self.config["spec_scans"].items()}
        self.xcorr_scans = {}
        for key, value in self.config.get("xcorr_scans", {}).items():
            path = Path(value)
            if path.exists():
                self.xcorr_scans[key] = fixed_path(path)
        self.explorer_analysis = None
        analysis_summary = self.config.get("explorer_analysis_summary")
        if analysis_summary and Path(analysis_summary).exists():
            summary_path = fixed_path(analysis_summary, file=True)
            self.explorer_analysis = json.loads(summary_path.read_text(encoding="utf-8"))
        self.qi = {name: index for index, name in enumerate(report_v2.QUICK_FIELDS)}
        self.ci = {name: index for index, name in enumerate(report_v2.CROSS_FIELDS)}

    def meta(self) -> dict[str, Any]:
        adu = []
        for row in self.adu_story["adcs"]:
            adu.append({
                key: row[key]
                for key in ("adc_id", "components", "minimum_30s", "maximum_30s", "clip_count",
                            "codes", "component_probability")
            })
        time_histograms = [
            {
                "label": str(row["label"]),
                "path": str(fixed_path(row["path"], file=True)),
                "sha256": str(row["sha256"]),
            }
            for row in self.report_config.get("time_histograms", [])
        ]
        time_raw = {
            label: {
                "source_pcap": str(fixed_path(record["source"], file=True)),
                "source_sha256": str(record["source_sha256"]),
                "iq16_npy": str(fixed_path(record["iq16_npy"], file=True)),
                "summary_npz": str(fixed_path(record["summary"], file=True)),
                "samples": int(record["samples"]),
                "sample_rate_hz": int(record["sample_rate_hz"]),
            }
            for label, record in self.raw_manifest.get("time", {}).items()
        }
        spec_raw = {
            label: {
                "source_pcap": str(fixed_path(record["source"], file=True)),
                "source_sha256": str(record["source_sha256"]),
                "iq16_npy": str(fixed_path(record["iq16_npy"], file=True)),
                "spectra": int(record["spectra"]),
            }
            for label, record in self.raw_manifest.get("spec", {}).items()
        }
        provenance = {
            "analysis_root": str(self.analysis_root),
            "analysis_manifest": str(self.analysis_root / "analysis_manifest.json"),
            "self_power": {
                scan: {
                    "scan_root": str(root),
                    "metrics": str(self.analysis_root / "metrics_by_scan" / f"scan={scan}" / "block=00..15" / "part.parquet"),
                    "temporal_metrics": str(self.analysis_root / "temporal_metrics" / f"scan={scan}" / "block=00..15" / "part.parquet"),
                    "integration_2s": str(self.analysis_root / "integration_series" / "tau=2s" / f"scan={scan}" / "block=00..15" / "part.parquet"),
                }
                for scan, root in self.spec_scans.items()
            },
            "time_controls": {
                "metrics": str(self.analysis_root / "time_control_metrics.parquet"),
                "series_10ms": str(self.analysis_root / "time_control_10ms_series.parquet"),
                "histograms": time_histograms,
            },
            "time_raw": time_raw,
            "spec_raw": spec_raw,
            "xcorr": {
                scan: {
                    "scan_root": str(root),
                    "zarr": str(root / "xcorr.zarr"),
                }
                for scan, root in self.xcorr_scans.items()
            },
            "cross_scan": str(self.analysis_root / "cross_scan_reproducibility" / "block=00..15" / "part.parquet"),
            "dynamic": {
                scan: {
                    "display_array": str(record["path"]),
                    "statistics_source": str(record["statistics_source"]),
                }
                for scan, record in (
                    self.explorer_analysis.get("dynamic", {}).items()
                    if self.explorer_analysis else []
                )
            },
        }
        return {
            "format": "T510_STAGE35_EXPLORER_META_V1",
            "title": "Stage 35：50 Ω 噪声、积分记忆与全频伪相关底",
            "science_story": self.story,
            "adu": adu,
            "rf_mhz": (self.rf_hz / 1e6).tolist(),
            "center_mhz": self.center_mhz,
            "rf_min_mhz": float(np.min(self.rf_hz) / 1e6),
            "rf_max_mhz": float(np.max(self.rf_hz) / 1e6),
            "time_captures": sorted(self.raw_manifest.get("time", {})),
            "spec_raw_captures": sorted(self.raw_manifest.get("spec", {})),
            "scans": sorted(self.spec_scans),
            "xcorr_scans": sorted(self.xcorr_scans),
            "dynamic_scans": sorted(
                self.explorer_analysis.get("dynamic", {}) if self.explorer_analysis else {}
            ),
            "pair_index": [list(pair) for pair in ADC_PAIRS],
            "phase_gate_gamma": 0.05,
            "provenance": provenance,
            "units": {
                "time_raw": "post-DDC IQ16 ADU",
                "fengine_iq": "F-engine IQ16 count",
                "auto": "count²",
                "visibility": "count² complex; mean(Xa·conj(Xb))",
            },
            "limits": {
                "calibration": "未定标；不能换算 K、Jy、SEFD、dBm 或系统温度",
                "physical_input": "八路独立 50 Ω；复相关是仪器伪相关底，不是天空可见度",
                "time_fft": "普通 Hann FFT/STFT；与生产 8-tap PFB 不同时、不同滤波，不作逐点定标",
            },
        }

    @functools.lru_cache(maxsize=64)
    def temporal_row(self, scan: str, adc: int, global_bin: int) -> dict[str, Any]:
        block = global_bin // 256
        local = global_bin % 256
        path = self.analysis_root / "temporal_metrics" / f"scan={scan}" / f"block={block:02d}" / "part.parquet"
        table = self.report_v2.table_sorted(self.analysis_root, "temporal_metrics", scan, block)
        row = adc * 256 + local
        return {name: table[name][row].as_py() for name in (
            "acf_constant_removed", "acf_temperature_regressed",
            "adev_overlap_raw_count2", "adev_overlap_temperature_regressed_count2",
            "psd_constant_removed_count4_per_hz",
        )}

    @functools.lru_cache(maxsize=24)
    def full_temporal(self, scan: str, adc: int) -> tuple[np.ndarray, np.ndarray]:
        acf = np.empty((4096, len(ACF_LAG_FENGINE)), dtype=np.float32)
        adev = np.empty((4096, len(ALLAN_TAU_FENGINE)), dtype=np.float32)
        for block in range(16):
            table = self.report_v2.table_sorted(self.analysis_root, "temporal_metrics", scan, block)
            rows = slice(adc * 256, (adc + 1) * 256)
            acf[block * 256:(block + 1) * 256] = self.report_v2.list_matrix(
                table["acf_constant_removed"], len(ACF_LAG_FENGINE), np.float32
            )[rows]
            adev[block * 256:(block + 1) * 256] = self.report_v2.list_matrix(
                table["adev_overlap_raw_count2"], len(ALLAN_TAU_FENGINE), np.float32
            )[rows]
        return acf, adev

    @functools.lru_cache(maxsize=64)
    def integration_2s(self, scan: str, adc: int, block: int) -> np.ndarray:
        path = self.analysis_root / "integration_series" / "tau=2s" / f"scan={scan}" / f"block={block:02d}" / "part.parquet"
        table = pq.read_table(path, columns=["adc_id", "global_bin", "raw_power_count2"])
        adc_ids = table["adc_id"].to_numpy(zero_copy_only=False)
        bins = table["global_bin"].to_numpy(zero_copy_only=False)
        selected = np.flatnonzero(adc_ids == adc)
        selected = selected[np.argsort(bins[selected])]
        return self.report_v2.list_matrix(table["raw_power_count2"], 450, np.float64)[selected]

    def time_control(self, captures: list[str], adcs: list[int]) -> list[dict[str, Any]]:
        rows = []
        taus = (0.01, .02, .05, .1, .2, .5, 1, 2, 4, 8, 15)
        lags = (0, .01, .02, .05, .1, .2, .5, 1, 2, 4, 8, 15)
        for capture in captures:
            for adc in adcs:
                row = self.time_by_key.get((capture, adc))
                if row is None:
                    continue
                std_i = np.asarray(row["std_i_adu"], dtype=np.float64)
                std_q = np.asarray(row["std_q_adu"], dtype=np.float64)
                proxy = std_i * std_i + std_q * std_q
                rows.append({
                    "capture": capture,
                    "adc": adc,
                    "time_s": (np.arange(len(proxy)) * 0.01).tolist(),
                    "mean_i_adu": row["mean_i_adu"],
                    "mean_q_adu": row["mean_q_adu"],
                    "typical_swing_i_adu": std_i.tolist(),
                    "typical_swing_q_adu": std_q.tolist(),
                    "noise_power_proxy_adu2": proxy.tolist(),
                    "allan_tau_s": list(taus),
                    "allan_proxy_adu2": overlapping_adev(proxy, .01, taus),
                    "acf_lag_s": list(lags),
                    "acf_proxy": centered_acf(proxy, .01, lags),
                })
        return rows

    def single(self, query: dict[str, list[str]]) -> dict[str, Any]:
        adcs = parse_ints(query, "adcs", 0, 7, 8, [0])
        bins = parse_bins(query, 32, [self.story["adc_presets"]["0"]["representative"]], self.center_mhz)
        scans = parse_scans(query)
        if len(adcs) * len(bins) * len(scans) > 48:
            raise ValueError("single selection exceeds 48 ADC/bin/scan series")
        series = []
        bandpass = []
        for scan in scans:
            scan_index = ("A", "B", "C").index(scan)
            for adc in adcs:
                bandpass.append({
                    "scan": scan,
                    "adc": adc,
                    "mean_power_count2": self.quick[scan_index, adc, :, self.qi["mean_power_count2"]].tolist(),
                })
                for global_bin in bins:
                    temporal = self.temporal_row(scan, adc, global_bin)
                    mean = float(self.quick[scan_index, adc, global_bin, self.qi["mean_power_count2"]])
                    long_values = self.integration_2s(scan, adc, global_bin // 256)[global_bin % 256]
                    series.append({
                        "scan": scan,
                        "adc": adc,
                        "global_bin": global_bin,
                        "rf_mhz": float(self.rf_hz[global_bin] / 1e6),
                        "time_2s_s": (np.arange(450) * 2 + 1).tolist(),
                        "power_2s_count2": long_values.tolist(),
                        "relative_power_2s_percent": ((long_values / mean - 1) * 100).tolist(),
                        "allan_tau_s": list(ALLAN_TAU_FENGINE),
                        "allan_count2": temporal["adev_overlap_raw_count2"],
                        "allan_fractional": (np.asarray(temporal["adev_overlap_raw_count2"]) / mean).tolist(),
                        "white_fractional": self.story["white_fractional_allan"],
                        "acf_lag_s": list(ACF_LAG_FENGINE),
                        "acf": temporal["acf_constant_removed"],
                        "temperature_regressed_acf": temporal["acf_temperature_regressed"],
                        "psd_frequency_hz": (np.arange(1025) * .048828125).tolist(),
                        "psd_count4_per_hz": temporal["psd_constant_removed_count4_per_hz"],
                        "sigma_ratio_15s": float(self.quick[scan_index, adc, global_bin, self.qi["sigma_ratio_15s"]]),
                        "temperature_r2": float(self.quick[scan_index, adc, global_bin, self.qi["temperature_r2"]]),
                    })
        controls = query.get("time_captures", [""])[0]
        control_labels = [value for value in controls.split(",") if value]
        return {
            "adcs": adcs,
            "bins": bins,
            "scans": scans,
            "rf_mhz": (self.rf_hz / 1e6).tolist(),
            "bandpass": bandpass,
            "series": series,
            "time_control": self.time_control(control_labels, adcs),
        }

    def statistics(self, query: dict[str, list[str]]) -> dict[str, Any]:
        adcs = parse_ints(query, "adcs", 0, 7, 8, [0])
        scans = parse_scans(query)
        if len(adcs) * len(scans) > 8:
            raise ValueError("statistics view permits at most eight ADC/scan panels")
        rows = []
        for scan in scans:
            scan_index = ("A", "B", "C").index(scan)
            for adc in adcs:
                acf, adev = self.full_temporal(scan, adc)
                mean = self.quick[scan_index, adc, :, self.qi["mean_power_count2"]]
                rows.append({
                    "scan": scan, "adc": adc,
                    "mean_power_count2": mean.tolist(),
                    "sigma_ratio_15s": self.quick[scan_index, adc, :, self.qi["sigma_ratio_15s"]].tolist(),
                    "acf_1s": self.quick[scan_index, adc, :, self.qi["acf_constant_removed_1s"]].tolist(),
                    "spectral_kurtosis": self.quick[scan_index, adc, :, self.qi["spectral_kurtosis"]].tolist(),
                    "temperature_r2": self.quick[scan_index, adc, :, self.qi["temperature_r2"]].tolist(),
                    "allan_ratio": (adev / np.maximum(
                        mean[:, None] * np.asarray(self.story["white_fractional_allan"])[None, :],
                        np.finfo(np.float64).tiny,
                    )).tolist(),
                    "acf_frequency_lag": acf.tolist(),
                    "cross_scan_fractional_std": self.cross_scan[adc, :, self.ci["between_scan_fractional_std"]].tolist(),
                })
        return {"rf_mhz": (self.rf_hz / 1e6).tolist(),
                "allan_tau_s": list(ALLAN_TAU_FENGINE),
                "acf_lag_s": list(ACF_LAG_FENGINE), "rows": rows}

    @functools.lru_cache(maxsize=6)
    def dynamic_array(self, scan: str) -> np.ndarray:
        if not self.explorer_analysis or scan not in self.explorer_analysis.get("dynamic", {}):
            raise ValueError(f"dynamic spectrum {scan} is not prepared")
        return np.load(
            fixed_path(self.explorer_analysis["dynamic"][scan]["path"], file=True),
            mmap_mode="r",
        )

    def dynamic(self, query: dict[str, list[str]]) -> dict[str, Any]:
        scan = parse_scans(query)[0]
        adc = parse_ints(query, "adcs", 0, 7, 1, [0])[0]
        layer = int(query.get("layer", ["1"])[0])
        if layer not in (0, 1, 2):
            raise ValueError("dynamic layer must be 0=min, 1=mean, or 2=max")
        record = self.explorer_analysis["dynamic"][scan]  # type: ignore[index]
        coding = record["layers"][layer][adc]
        codes = np.asarray(self.dynamic_array(scan)[layer, adc], dtype=np.float32)
        db = coding["minimum_db"] + codes * coding["scale_db_per_code"]
        order = np.asarray(self.report_v2.core.ascending_global_bins(), dtype=np.int64)
        ordered = db[:, order].reshape(900, 512, 8)
        if layer == 0:
            display = np.min(ordered, axis=2)
        elif layer == 2:
            display = np.max(ordered, axis=2)
        else:
            display = np.mean(ordered, axis=2)
        rf = (self.rf_hz[order] / 1e6).reshape(512, 8).mean(axis=1)
        return {
            "scan": scan, "adc": adc, "layer": ("minimum", "mean", "maximum")[layer],
            "time_s": (np.arange(900) + .5).tolist(), "rf_mhz": rf.tolist(),
            "db_count2_per_channel": display.tolist(),
            "display_frequency_groups": 512, "source_frequency_bins": 4096,
            "encoding_max_error_db": coding["maximum_error_db"],
            "statistics_source": record["statistics_source"],
        }

    @functools.lru_cache(maxsize=12)
    def raw_time_array(self, capture: str) -> np.ndarray:
        record = self.raw_manifest["time"].get(capture)
        if record is None:
            raise ValueError(f"unknown TIME raw capture {capture}")
        return np.load(fixed_path(record["iq16_npy"], file=True), mmap_mode="r")

    @functools.lru_cache(maxsize=12)
    def raw_time_summary(self, capture: str) -> dict[str, np.ndarray]:
        record = self.raw_manifest["time"].get(capture)
        if record is None:
            raise ValueError(f"unknown TIME raw capture {capture}")
        loaded = np.load(fixed_path(record["summary"], file=True))
        return {name: loaded[name] for name in loaded.files}

    def time_raw(self, query: dict[str, list[str]]) -> dict[str, Any]:
        capture = query.get("capture", [""])[0]
        adcs = parse_ints(query, "adcs", 0, 7, 8, [0])
        start_us = max(0.0, float(query.get("start_us", ["0"])[0]))
        duration_us = min(50_000.0 - start_us, max(0.001, float(query.get("duration_us", ["50000"])[0])))
        points = min(20_000, max(128, int(query.get("points", ["4000"])[0])))
        raw = self.raw_time_array(capture)
        start = min(len(raw), int(round(start_us * 320)))
        stop = min(len(raw), int(round((start_us + duration_us) * 320)))
        if stop <= start:
            raise ValueError("TIME raw window is empty")
        count = stop - start
        exact = count <= points
        output = []
        if exact:
            selected = np.asarray(raw[start:stop, adcs, :])
            time_us = ((np.arange(start, stop) + .5) / 320).tolist()
            for index, adc in enumerate(adcs):
                output.append({
                    "adc": adc, "exact": True, "time_us": time_us,
                    "i_adu": selected[:, index, 0].tolist(),
                    "q_adu": selected[:, index, 1].tolist(),
                })
        else:
            edges = np.linspace(start, stop, points + 1, dtype=np.int64)
            time_us = (((edges[:-1] + edges[1:]) * .5) / 320).tolist()
            for adc in adcs:
                imin, imax, qmin, qmax = [], [], [], []
                for left, right in zip(edges[:-1], edges[1:]):
                    values = np.asarray(raw[left:max(left + 1, right), adc])
                    imin.append(int(values[:, 0].min())); imax.append(int(values[:, 0].max()))
                    qmin.append(int(values[:, 1].min())); qmax.append(int(values[:, 1].max()))
                output.append({
                    "adc": adc, "exact": False, "time_us": time_us,
                    "i_min_adu": imin, "i_max_adu": imax,
                    "q_min_adu": qmin, "q_max_adu": qmax,
                })
        return {"capture": capture, "start_us": start_us, "duration_us": duration_us,
                "sample_rate_hz": 320_000_000, "series": output}

    def time_fft(self, query: dict[str, list[str]]) -> dict[str, Any]:
        capture = query.get("capture", [""])[0]
        adcs = parse_ints(query, "adcs", 0, 7, 8, [0])
        summary = self.raw_time_summary(capture)
        short_taus = (1e-6, 2e-6, 5e-6, 1e-5, 2e-5, 5e-5, 1e-4,
                      2e-4, 5e-4, .001, .002, .005, .01)
        return {
            "capture": capture,
            "frequency_mhz_baseband": (summary["fft_frequency_hz"] / 1e6).tolist(),
            "series": [{
                "adc": adc,
                "fft_db_relative": summary["fft_db_relative"][adc].tolist(),
                "short_allan_tau_s": list(short_taus),
                "short_allan_power_proxy_adu2": overlapping_adev(
                    summary["power_1us"][:, adc], 1e-6, short_taus
                ),
                "raw_acf_lag_s": (summary["lag_samples"] / 320_000_000).tolist(),
                "raw_iq_acf": summary["raw_iq_acf"][adc].tolist(),
            } for adc in adcs],
            "kind": "普通 Hann-windowed FFT average；不是生产 PFB，也不与 F-engine 逐点定标",
        }

    @functools.lru_cache(maxsize=12)
    def raw_spec_array(self, capture: str) -> np.ndarray:
        record = self.raw_manifest["spec"].get(capture)
        if record is None:
            raise ValueError(f"unknown SPEC raw capture {capture}")
        return np.load(fixed_path(record["iq16_npy"], file=True), mmap_mode="r")

    def spec_raw(self, query: dict[str, list[str]]) -> dict[str, Any]:
        capture = query.get("capture", [""])[0]
        adcs = parse_ints(query, "adcs", 0, 7, 8, [0])
        bins = parse_bins(query, 32, [295], self.center_mhz)
        raw = self.raw_spec_array(capture)
        output = []
        for adc in adcs:
            for global_bin in bins:
                values = np.asarray(raw[:, adc, global_bin, :])
                output.append({
                    "adc": adc, "global_bin": global_bin,
                    "rf_mhz": float(self.rf_hz[global_bin] / 1e6),
                    "time_ms": (np.arange(len(values)) * 4096 / 320_000).tolist(),
                    "i_count": values[:, 0].tolist(), "q_count": values[:, 1].tolist(),
                    "power_count2": np.sum(values.astype(np.float64) ** 2, axis=1).tolist(),
                })
        return {"capture": capture, "series": output}

    def _xcorr_meta(self, scan: str) -> tuple[Path, dict[str, Any], list[int]]:
        root = self.xcorr_scans.get(scan)
        if root is None:
            raise ValueError(f"cross-correlation scan {scan} is not available")
        zarr = root / "xcorr.zarr"
        attrs = json.loads((zarr / ".zattrs").read_text(encoding="utf-8"))
        if attrs.get("complete") is not True:
            raise ValueError(f"cross-correlation scan {scan} is not sealed")
        focus = np.fromfile(zarr / "focus_global_bin" / "0", dtype="<u2").astype(int).tolist()
        return zarr, attrs, focus

    @functools.lru_cache(maxsize=256)
    def xcorr_series(self, scan: str, pair: tuple[int, int], global_bin: int) -> dict[str, Any]:
        zarr, _, focus = self._xcorr_meta(scan)
        pair_index = PAIR_INDEX[pair]
        if global_bin in focus:
            f = focus.index(global_bin)
            cross_meta = json.loads((zarr / "focus_mean_cross_visibility_count2" / ".zarray").read_text())
            rows = cross_meta["shape"][0]
            chunks = rows // 10
            values = np.empty(rows, dtype=np.complex128)
            auto_left = np.empty(rows, dtype=np.float64)
            auto_right = np.empty(rows, dtype=np.float64)
            n_valid = np.empty(rows, dtype=np.uint64)
            for chunk in range(chunks):
                cross = np.fromfile(zarr / "focus_mean_cross_visibility_count2" / f"{chunk}.0.0", dtype="<c16").reshape(10, 28, len(focus))
                auto = np.fromfile(zarr / "focus_mean_auto_power_count2" / f"{chunk}.0.0", dtype="<f8").reshape(10, 8, len(focus))
                valid = np.fromfile(zarr / "focus_n_valid" / f"{chunk}.0", dtype="<u8").reshape(10, 16)
                if not np.all(valid == valid[:, :1]):
                    raise ValueError(f"{scan} focus n_valid differs among 16 packet blocks")
                values[chunk * 10:(chunk + 1) * 10] = cross[:, pair_index, f]
                auto_left[chunk * 10:(chunk + 1) * 10] = auto[:, pair[0], f]
                auto_right[chunk * 10:(chunk + 1) * 10] = auto[:, pair[1], f]
                n_valid[chunk * 10:(chunk + 1) * 10] = valid[:, 0]
            bucket = .1
            source = "100 ms focus product"
        else:
            block = global_bin // 256
            local = global_bin % 256
            cross_meta = json.loads((zarr / "mean_cross_visibility_count2" / ".zarray").read_text())
            rows = cross_meta["shape"][0]
            values = np.empty(rows, dtype=np.complex128)
            auto_left = np.empty(rows, dtype=np.float64)
            auto_right = np.empty(rows, dtype=np.float64)
            n_valid = np.empty(rows, dtype=np.uint64)
            for second in range(rows):
                cross = np.fromfile(zarr / "mean_cross_visibility_count2" / f"{second}.0.{block}", dtype="<c16").reshape(28, 256)
                auto = np.fromfile(zarr / "mean_auto_power_count2" / f"{second}.0.{block}", dtype="<f8").reshape(8, 256)
                valid = np.fromfile(zarr / "n_valid" / f"{second}.0", dtype="<u8")
                if valid.shape != (16,) or not np.all(valid == valid[0]):
                    raise ValueError(f"{scan} second {second} n_valid differs among packet blocks")
                values[second] = cross[pair_index, local]
                auto_left[second] = auto[pair[0], local]
                auto_right[second] = auto[pair[1], local]
                n_valid[second] = valid[0]
            bucket = 1.0
            source = "1 s full-band product"
        gamma = np.abs(values) / np.sqrt(np.maximum(auto_left * auto_right, np.finfo(float).tiny))
        phase = np.angle(values, deg=True)
        phase[gamma < .05] = np.nan
        taus = tuple(value for value in (.1, .2, .5, 1, 2, 4, 15, 30) if value >= bucket)
        lags = tuple(value for value in (0, .1, .2, .5, 1, 2, 4, 8, 15, 30) if value >= bucket or value == 0)
        return {
            "scan": scan, "pair": list(pair), "global_bin": global_bin,
            "rf_mhz": float(self.rf_hz[global_bin] / 1e6), "bucket_s": bucket,
            "source": source, "time_s": ((np.arange(len(values)) + .5) * bucket).tolist(),
            "n_valid": n_valid.astype(int).tolist(),
            "re_count2": values.real.tolist(), "im_count2": values.imag.tolist(),
            "gamma": gamma.tolist(),
            "phase_deg_or_null": [None if not np.isfinite(value) else float(value) for value in phase],
            "phase_gate_gamma": .05,
            "allan_tau_s": list(taus),
            "allan_re_count2": overlapping_adev(values.real, bucket, taus),
            "allan_im_count2": overlapping_adev(values.imag, bucket, taus),
            "acf_lag_s": list(lags),
            "acf_re": centered_acf(values.real, bucket, lags),
            "acf_im": centered_acf(values.imag, bucket, lags),
            "integration_scatter": integration_scatter(values, bucket),
            "temporal_psd": spectral_summary(values, bucket),
        }

    def pair(self, query: dict[str, list[str]]) -> dict[str, Any]:
        pairs = parse_pairs(query)
        bins = parse_bins(query, 32, [295], self.center_mhz)
        scans = parse_scans(query)
        if len(pairs) * len(bins) * len(scans) > 48:
            raise ValueError("pair selection exceeds 48 pair/bin/scan series")
        output = [self.xcorr_series(scan, pair, global_bin)
                  for scan in scans for pair in pairs for global_bin in bins]
        capture = query.get("time_capture", [""])[0]
        raw = []
        slow = []
        if capture:
            summary = self.raw_time_summary(capture)
            pair_rows = {tuple(row): index for index, row in enumerate(summary["pair_index"].tolist())}
            for pair in pairs:
                index = pair_rows[pair]
                value = summary["raw_complex_xcorr"][index]
                gamma0 = abs(value[MAX_LAG])
                raw.append({
                    "capture": capture, "pair": list(pair),
                    "lag_samples": summary["lag_samples"].tolist(),
                    "lag_ns": (summary["lag_samples"] / .32).tolist(),
                    "re_gamma": value.real.tolist(), "im_gamma": value.imag.tolist(),
                    "abs_gamma": np.abs(value).tolist(),
                    "zero_lag_gamma": float(gamma0),
                    "phase_deg": None if gamma0 < .05 else float(np.angle(value[MAX_LAG], deg=True)),
                    "phase_note": "|γ|<0.05，相关太弱时相位隐藏" if gamma0 < .05 else "相位门限已满足",
                })
                left_row = self.time_by_key.get((capture, pair[0]))
                right_row = self.time_by_key.get((capture, pair[1]))
                if left_row is not None and right_row is not None:
                    left_i = np.asarray(left_row["std_i_adu"], dtype=np.float64)
                    left_q = np.asarray(left_row["std_q_adu"], dtype=np.float64)
                    right_i = np.asarray(right_row["std_i_adu"], dtype=np.float64)
                    right_q = np.asarray(right_row["std_q_adu"], dtype=np.float64)
                    left_power = left_i * left_i + left_q * left_q
                    right_power = right_i * right_i + right_q * right_q
                    coefficient = float(np.corrcoef(left_power, right_power)[0, 1])
                    slow.append({
                        "capture": capture, "pair": list(pair),
                        "time_s": (np.arange(len(left_power)) * .01).tolist(),
                        "left_relative_percent": ((left_power / np.mean(left_power) - 1) * 100).tolist(),
                        "right_relative_percent": ((right_power / np.mean(right_power) - 1) * 100).tolist(),
                        "pearson_correlation": coefficient,
                        "meaning": "两路 10 ms 噪声宽度/功率代理的共同慢漂移；不是天文可见度",
                    })
        matrix = None
        if output:
            matrix = self.xcorr_matrix(scans[0], bins[0])
        return {"series": output, "time_raw_cross": raw,
                "time_slow_drift": slow, "matrix": matrix}

    @functools.lru_cache(maxsize=24)
    def xcorr_matrix(self, scan: str, global_bin: int) -> dict[str, Any]:
        zarr, _, focus = self._xcorr_meta(scan)
        sums = np.zeros(28, dtype=np.float64)
        count = 0
        if global_bin in focus:
            f = focus.index(global_bin)
            rows = json.loads((zarr / "focus_mean_cross_visibility_count2" / ".zarray").read_text())["shape"][0]
            for chunk in range(rows // 10):
                cross = np.fromfile(zarr / "focus_mean_cross_visibility_count2" / f"{chunk}.0.0", dtype="<c16").reshape(10, 28, len(focus))[:, :, f]
                auto = np.fromfile(zarr / "focus_mean_auto_power_count2" / f"{chunk}.0.0", dtype="<f8").reshape(10, 8, len(focus))[:, :, f]
                for index, pair in enumerate(ADC_PAIRS):
                    sums[index] += np.sum(np.abs(cross[:, index]) / np.sqrt(np.maximum(
                        auto[:, pair[0]] * auto[:, pair[1]], np.finfo(float).tiny)))
                count += 10
            bucket = .1
        else:
            block, local = divmod(global_bin, 256)
            rows = json.loads((zarr / "mean_cross_visibility_count2" / ".zarray").read_text())["shape"][0]
            for second in range(rows):
                cross = np.fromfile(zarr / "mean_cross_visibility_count2" / f"{second}.0.{block}", dtype="<c16").reshape(28, 256)[:, local]
                auto = np.fromfile(zarr / "mean_auto_power_count2" / f"{second}.0.{block}", dtype="<f8").reshape(8, 256)[:, local]
                for index, pair in enumerate(ADC_PAIRS):
                    sums[index] += abs(cross[index]) / math.sqrt(max(
                        auto[pair[0]] * auto[pair[1]], np.finfo(float).tiny))
                count += 1
            bucket = 1.0
        means = sums / max(count, 1)
        matrix = np.eye(8, dtype=np.float64)
        for index, pair in enumerate(ADC_PAIRS):
            matrix[pair] = means[index]
            matrix[pair[::-1]] = means[index]
        same_indices = [PAIR_INDEX[pair] for pair in ((0, 1), (2, 3), (4, 5), (6, 7))]
        cross_indices = [index for index in range(28) if index not in same_indices]
        return {
            "scan": scan, "global_bin": global_bin, "bucket_s": bucket,
            "mean_gamma_matrix": matrix.tolist(),
            "same_tile_mean_gamma_median": float(np.median(means[same_indices])),
            "cross_tile_mean_gamma_median": float(np.median(means[cross_indices])),
        }


class ExplorerHandler(BaseHTTPRequestHandler):
    server_version = "T510Stage35Explorer/1"

    @property
    def app(self) -> "ExplorerServer":
        return self.server  # type: ignore[return-value]

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("stage35-explorer: " + fmt % args + "\n")

    def end_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'",
        )
        super().end_headers()

    def send_bytes(self, status: int, content_type: str, payload: bytes, *, head: bool = False) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store" if content_type == "application/json" else "public, max-age=3600")
        self.end_headers()
        if not head:
            self.wfile.write(payload)

    def send_json(self, value: Any, *, head: bool = False) -> None:
        self.send_bytes(200, "application/json; charset=utf-8",
                        json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode(),
                        head=head)

    def route(self, *, head: bool) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        try:
            if parsed.path == "/healthz":
                self.send_json({"ok": True}, head=head)
            elif parsed.path == "/api/meta":
                self.send_json(self.app.data.meta(), head=head)
            elif parsed.path == "/api/single":
                self.send_json(self.app.data.single(query), head=head)
            elif parsed.path == "/api/time-raw":
                self.send_json(self.app.data.time_raw(query), head=head)
            elif parsed.path == "/api/time-fft":
                self.send_json(self.app.data.time_fft(query), head=head)
            elif parsed.path == "/api/spec-raw":
                self.send_json(self.app.data.spec_raw(query), head=head)
            elif parsed.path == "/api/pair":
                self.send_json(self.app.data.pair(query), head=head)
            elif parsed.path == "/api/statistics":
                self.send_json(self.app.data.statistics(query), head=head)
            elif parsed.path == "/api/dynamic":
                self.send_json(self.app.data.dynamic(query), head=head)
            elif parsed.path == "/":
                self.static("index.html", head)
            elif parsed.path.startswith("/static/"):
                self.static(parsed.path.removeprefix("/static/"), head)
            else:
                self.send_bytes(404, "text/plain; charset=utf-8", "not found\n".encode(), head=head)
        except (ValueError, KeyError, FileNotFoundError, json.JSONDecodeError) as error:
            payload = json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False).encode()
            self.send_bytes(400, "application/json; charset=utf-8", payload, head=head)
        except Exception as error:
            payload = json.dumps({"ok": False, "error": f"internal data error: {error}"}, ensure_ascii=False).encode()
            self.send_bytes(500, "application/json; charset=utf-8", payload, head=head)

    def static(self, relative: str, head: bool) -> None:
        if not relative or relative.startswith(".") or "/" in relative or "\\" in relative:
            self.send_bytes(404, "text/plain", b"not found\n", head=head)
            return
        path = (self.app.static_root / relative).resolve()
        if path.parent != self.app.static_root or not path.is_file():
            self.send_bytes(404, "text/plain", b"not found\n", head=head)
            return
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_bytes(200, content_type, path.read_bytes(), head=head)

    def do_GET(self) -> None:
        self.route(head=False)

    def do_HEAD(self) -> None:
        self.route(head=True)

    def do_POST(self) -> None:
        self.send_bytes(405, "application/json", b'{"ok":false,"error":"read-only: GET/HEAD only"}')

    do_PUT = do_POST
    do_DELETE = do_POST
    do_PATCH = do_POST


class ExplorerServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], data: ExplorerData, static_root: Path):
        self.data = data
        self.static_root = static_root.resolve(strict=True)
        super().__init__(address, ExplorerHandler)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--helper-dir", type=Path, required=True)
    parser.add_argument("--static-root", type=Path, required=True)
    parser.add_argument("--bind", default="0.0.0.0:8035")
    args = parser.parse_args()
    host, port_text = args.bind.rsplit(":", 1)
    data = ExplorerData(args.config, args.helper_dir)
    server = ExplorerServer((host, int(port_text)), data, args.static_root)
    server.serve_forever(poll_interval=.25)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
