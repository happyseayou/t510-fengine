#!/usr/bin/env python3
"""Read-only Stage 35 explorer with only TIME, F-engine, and Allan views."""

from __future__ import annotations

import argparse
import functools
import hashlib
import json
import mimetypes
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import numpy as np


DATA_ROOT = Path("/var/lib/t510/stage35").resolve()
ADC_PAIRS = tuple((a, b) for a in range(8) for b in range(a + 1, 8))
PAIR_INDEX = {pair: index for index, pair in enumerate(ADC_PAIRS)}
SHORT_BUCKETS = (1, 4, 16, 64, 256)
PHASE_GATE = 0.05
SELF_TAUS = (0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1, 2, 4, 8, 15, 30)
PAIR_TAUS = {
    100: (0.1, 0.2, 0.5, 1, 2, 4, 8, 15, 30),
    1000: (1, 2, 4, 8, 15, 30),
}


def fixed_path(value: str | Path, *, file: bool = False) -> Path:
    path = Path(value).resolve(strict=True)
    if path != DATA_ROOT and DATA_ROOT not in path.parents:
        raise ValueError(f"path escapes the fixed Stage 35 data root: {path}")
    if file and not path.is_file():
        raise ValueError(f"required file is missing: {path}")
    return path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def query_one(query: dict[str, list[str]], name: str, default: str) -> str:
    return query.get(name, [default])[0].strip()


def query_adc(query: dict[str, list[str]]) -> int:
    value = int(query_one(query, "adc", "0"))
    if not 0 <= value <= 7:
        raise ValueError("adc must be within 0..7")
    return value


def query_pair(query: dict[str, list[str]]) -> tuple[int, int]:
    parts = query_one(query, "pair", "0-1").split("-")
    if len(parts) != 2:
        raise ValueError("pair must look like 0-1")
    pair = tuple(sorted((int(parts[0]), int(parts[1]))))
    if pair not in PAIR_INDEX:
        raise ValueError("pair must select two different ADCs within 0..7")
    return pair


def parse_bins(text: str, center_mhz: float) -> list[int]:
    values: list[int] = []
    for raw in text.split(","):
        token = raw.strip().lower().replace(" ", "")
        if not token:
            continue
        if token.endswith("mhz"):
            rf_mhz = float(token[:-3])
            signed = int(round((rf_mhz - center_mhz) / 0.078125))
            if not -2048 <= signed <= 2047:
                raise ValueError("RF frequency lies outside the current 40–359.921875 MHz band")
            actual = center_mhz + signed * 0.078125
            if abs(actual - rf_mhz) > 1e-6:
                raise ValueError("RF frequency must lie on the 0.078125 MHz channel grid")
            value = signed % 4096
        else:
            value = int(token.removeprefix("global_bin:").removeprefix("bin:").removeprefix("b"))
            if not 0 <= value <= 4095:
                raise ValueError("global_bin must be within 0..4095")
        if value not in values:
            values.append(value)
    if not 1 <= len(values) <= 4:
        raise ValueError("select between one and four unique frequencies")
    return values


def weighted_nonoverlap(values: np.ndarray, weights: np.ndarray, width: int) -> tuple[np.ndarray, np.ndarray]:
    groups = len(values) // width
    if groups < 1:
        raise ValueError("time bucket is wider than the selected data")
    value = values[: groups * width].reshape((groups, width) + values.shape[1:])
    weight = weights[: groups * width].reshape(groups, width)
    total = np.sum(weight, axis=1)
    factor = weight.reshape((groups, width) + (1,) * (values.ndim - 1))
    mean = np.sum(value * factor, axis=1) / total.reshape((groups,) + (1,) * (values.ndim - 1))
    return mean, total


def normalized_correlation_magnitude(
    visibility: np.ndarray, pa: np.ndarray, pb: np.ndarray
) -> np.ndarray:
    """Return |V|/sqrt(Pa*Pb), leaving zero-power samples explicitly undefined."""
    denominator = np.sqrt(pa * pb)
    gamma = np.full(np.shape(denominator), np.nan, dtype=np.float64)
    valid = np.isfinite(denominator) & (denominator > 0)
    np.divide(np.abs(visibility), denominator, out=gamma, where=valid)
    return gamma


def finite_list(values: np.ndarray) -> list[Any]:
    """Encode expected missing numeric values as JSON null, never as a fabricated zero."""
    array = np.asarray(values)
    return np.where(np.isfinite(array), array.astype(object), None).tolist()


class SimpleData:
    def __init__(self, config_path: Path, helper_dir: Path):
        self.config_path = config_path.resolve(strict=True)
        self.config = json.loads(self.config_path.read_text(encoding="utf-8"))
        if self.config.get("format") not in {
            "T510_STAGE35_SIMPLE_EXPLORER_CONFIG_V1",
            "T510_STAGE35_SIMPLE_EXPLORER_CONFIG_V2",
        }:
            raise ValueError("unexpected simple explorer config format")
        sys.path.insert(0, str(helper_dir.resolve(strict=True)))
        from t510_stage35_simple_math import (
            aggregate_frames,
            overlapping_allan,
            overlapping_allan_visibility,
            white_noise_reference,
        )

        self.aggregate_frames = aggregate_frames
        self.overlapping_allan = overlapping_allan
        self.overlapping_allan_visibility = overlapping_allan_visibility
        self.white_noise_reference = white_noise_reference
        self.center_mhz = float(self.config.get("center_mhz", 200.0))
        if self.center_mhz != 200.0:
            raise ValueError("the simple Stage 35 report is frozen to the 200 MHz center")
        signed = np.where(np.arange(4096) < 2048, np.arange(4096), np.arange(4096) - 4096)
        self.rf_mhz = self.center_mhz + signed * 0.078125
        raw_path = fixed_path(self.config["simple_raw_index_manifest"], file=True)
        self.raw_manifest_path = raw_path
        self.raw_manifest = json.loads(raw_path.read_text(encoding="utf-8"))
        if self.raw_manifest.get("format") != "T510_STAGE35_SIMPLE_RAW_INDEX_V1":
            raise ValueError("unexpected simple raw index format")
        self.time_records = self.raw_manifest["time"]
        self.spec_records = self.raw_manifest["spec"]
        if len(self.spec_records) != 1:
            raise ValueError("simple explorer requires exactly one 4096-spectrum witness")
        self.time_long_index_path = fixed_path(self.config["time_long_index"], file=True)
        self.time_long_index = json.loads(self.time_long_index_path.read_text(encoding="utf-8"))
        if (
            self.time_long_index.get("format") != "T510_STAGE35_TIME_LONG_ARRAYS_V1"
            or int(self.time_long_index.get("duration_seconds", 0)) != 900
            or int(self.time_long_index.get("base_cadence_ms", 0)) != 10
        ):
            raise ValueError("TIME_ONLY long index is not a sealed 900 s / 10 ms product")
        self.self_scans = {
            key.upper(): fixed_path(value)
            for key, value in self.config["self_scans"].items()
        }
        if set(self.self_scans) != {"A", "B", "C"}:
            raise ValueError("self_scans must contain A, B, and C")
        self.cross_scan = fixed_path(self.config["cross_scan"])
        cross_attrs = json.loads((self.cross_scan / "xcorr.zarr" / ".zattrs").read_text())
        if cross_attrs.get("complete") is not True or cross_attrs.get("save_fullband_100ms") is not True:
            raise ValueError("cross scan is not a sealed full-band 100 ms dataset")
        self.cross_attrs = cross_attrs
        self.cross_id = self.cross_scan.name
        temperature = self.config.get("time_temperature")
        self.time_temperature_path = fixed_path(temperature, file=True) if temperature else None
        self.time_temperature = (
            json.loads(self.time_temperature_path.read_text(encoding="utf-8"))
            if self.time_temperature_path else None
        )
        if self.time_temperature is not None:
            if self.time_temperature.get("format") != "T510_STAGE35_TIME_TEMPERATURE_V1":
                raise ValueError("unexpected TIME temperature format")
            sizes = {
                len(self.time_temperature.get(name, []))
                for name in ("time_s", "mean_c", "min_c", "max_c")
            }
            if sizes != {int(self.time_temperature.get("points", -1))}:
                raise ValueError("TIME temperature arrays have inconsistent lengths")
            if self.time_temperature.get("sensor") != "pl_temp" or self.time_temperature.get("unit") != "degC":
                raise ValueError("TIME temperature must be the PL sensor in degC")
            times = np.asarray(self.time_temperature["time_s"], dtype=np.float64)
            values = np.asarray(self.time_temperature["mean_c"], dtype=np.float64)
            if not np.all(np.isfinite(times)) or not np.all(np.isfinite(values)):
                raise ValueError("TIME temperature contains non-finite values")
            if len(times) and (np.any(np.diff(times) <= 0) or times[0] < 0 or times[-1] > 900):
                raise ValueError("TIME temperature timestamps are outside the formal window")
        self._identities = {
            "raw_manifest": sha256_file(self.raw_manifest_path),
            "cross_manifest": sha256_file(self.cross_scan / "dataset_manifest.json"),
            "self_manifests": {
                key: sha256_file(path / "dataset_manifest.json") for key, path in self.self_scans.items()
            },
            "time_long_index": sha256_file(self.time_long_index_path),
        }
        if self.time_temperature_path:
            self._identities["time_temperature"] = sha256_file(self.time_temperature_path)

    def meta(self) -> dict[str, Any]:
        time_identity = {
            label: {
                "data_segment": label,
                "arrays": {
                    "iq16_npy": record.get("source_sha256"),
                    "fft4096_complex64_npy": record.get("fft4096_complex64_sha256"),
                },
            }
            for label, record in sorted(self.time_records.items())
        }
        spec_identity = {
            label: {
                "data_segment": label,
                "arrays": {"iq16_npy": record.get("iq16_npy_sha256")},
            }
            for label, record in sorted(self.spec_records.items())
        }
        return {
            "format": "T510_STAGE35_SIMPLE_EXPLORER_META_V1",
            "title": "Stage 35：TIME_ONLY、F-engine 与 Allan 方差",
            "center_mhz": self.center_mhz,
            "rf_min_mhz": float(np.min(self.rf_mhz)),
            "rf_max_mhz": float(np.max(self.rf_mhz)),
            "channel_spacing_mhz": 0.078125,
            "rf_mhz": self.rf_mhz.tolist(),
            "defaults": {
                "adcs": [0], "pairs": [[0, 1]],
                "bins": [3134, 3182, 3328], "time_capture": "A-pre",
                "self_scan": "A", "short_bucket_frames": 16,
            },
            "time_captures": sorted(self.time_records),
            "time_long_capture": self.time_long_index["label"],
            "time_long_cadence_ms": [10, 100, 1000],
            "time_temperature": ({
                key: self.time_temperature[key] for key in (
                    "format", "sensor", "unit", "points", "sampling", "coverage_seconds",
                    "capture_start_unix_ms", "capture_duration_seconds", "source",
                )
            } if self.time_temperature else None),
            "spec_capture": next(iter(self.spec_records)),
            "self_scans": sorted(self.self_scans),
            "cross_scan": self.cross_id,
            "short_bucket_frames": list(SHORT_BUCKETS),
            "phase_gate_gamma": PHASE_GATE,
            "limits": {
                "time": "TIME_ONLY 是 post-DDC IQ16 ADU，不是 ADC 的 3.84 GS/s 原始码。",
                "fengine": "F-engine 是通道化后的 IQ16 count，尚未定标为 K、Jy 或 SEFD。",
                "correlation": "独立 50 Ω 下测得的是仪器伪相关底，不是天空可见度。",
                "fft": "普通 Hann FFT 与生产 8-tap PFB 不同时、滤波不同，只作参照。",
            },
            "identities": self._identities,
            "technical_sources": {
                "TIME_ONLY": time_identity,
                "TIME_ONLY_900s": {
                    "index": str(self.time_long_index_path),
                    "sha256": self._identities["time_long_index"],
                    "source_manifest": self.time_long_index["source_manifest"],
                },
                "F_engine_raw": spec_identity,
                "F_engine_900s_self_power_manifests": self._identities["self_manifests"],
                "F_engine_900s_cross_manifest": self._identities["cross_manifest"],
            },
        }

    def _capture(self, query: dict[str, list[str]]) -> str:
        capture = query_one(query, "capture", "A-pre")
        if capture not in self.time_records:
            raise ValueError(f"unknown TIME capture {capture}")
        return capture

    def _bins(self, query: dict[str, list[str]]) -> list[int]:
        return parse_bins(query_one(query, "bins", "3134,3182,3328"), self.center_mhz)

    @functools.lru_cache(maxsize=12)
    def time_raw_array(self, capture: str) -> np.ndarray:
        return np.load(fixed_path(self.time_records[capture]["iq16_npy"], file=True), mmap_mode="r")

    @functools.lru_cache(maxsize=12)
    def time_fft_array(self, capture: str) -> np.ndarray:
        return np.load(
            fixed_path(self.time_records[capture]["fft4096_complex64_npy"], file=True), mmap_mode="r"
        )

    @functools.lru_cache(maxsize=4)
    def time_long_array(self, name: str) -> np.ndarray:
        record = self.time_long_index["arrays"].get(name)
        if not isinstance(record, dict):
            raise ValueError(f"TIME_ONLY long array is missing: {name}")
        path = fixed_path(record["path"], file=True)
        return np.load(path, mmap_mode="r")

    @functools.lru_cache(maxsize=2)
    def spec_raw_array(self, capture: str) -> np.ndarray:
        return np.load(fixed_path(self.spec_records[capture]["iq16_npy"], file=True), mmap_mode="r")

    def _source(
        self,
        kind: str,
        record: dict[str, Any],
        array: str,
        sha_key: str,
        meaning: str,
    ) -> dict[str, Any]:
        return {
            "kind": kind,
            "meaning": meaning,
            "capture_id": record.get("label"),
            "array": array,
            "sha256": record.get(sha_key),
        }

    def time_single(self, query: dict[str, list[str]]) -> dict[str, Any]:
        capture, adc = self._capture(query), query_adc(query)
        bucket_text = query_one(query, "bucket", "raw")
        raw = self.time_raw_array(capture)
        if bucket_text == "raw":
            start = int(query_one(query, "start_sample", "0"))
            if not 0 <= start <= len(raw) - 4096:
                raise ValueError("start_sample must leave room for 4096 real samples")
            # Keep the wire-format signed integers intact.  Converting these
            # samples to float made the JSON say 9.0 even though the actual
            # RFDC output word was the integer 9.
            values = np.asarray(raw[start:start + 4096, adc], dtype=np.int16)
            time_us = (np.arange(start, start + 4096) / 320.0).tolist()
            text = "每个点就是一个未经平均的 post-DDC I/Q 样点。"
            calculation = {"samples": 4096, "start_sample": start, "bucket_samples": 1}
        else:
            frames = int(bucket_text)
            if frames not in SHORT_BUCKETS[1:]:
                raise ValueError("TIME bucket must be raw, 4, 16, 64, or 256")
            width = frames * 4096
            count = len(raw) // width
            selected = np.asarray(raw[:count * width, adc], dtype=np.float64).reshape(count, width, 2)
            values = np.mean(selected, axis=1)
            time_us = ((np.arange(count) + 0.5) * width / 320.0).tolist()
            text = f"每个点是连续 {width:,} 个 TIME_ONLY 样点分别求平均 I 和平均 Q。"
            calculation = {"samples": int(count * width), "bucket_samples": width,
                           "bucket_seconds": width / 320_000_000, "points": count}
        record = self.time_records[capture]
        return {
            "domain": "time_single", "capture": capture, "adc": adc,
            "time_us": time_us, "i_adu": values[:, 0].tolist(), "q_adu": values[:, 1].tolist(),
            "point_definition": text,
            "formula": r"z[n]=I[n]+\mathrm{i}Q[n],\quad \bar I_k=\frac{1}{B}\sum I[n],\quad \bar Q_k=\frac{1}{B}\sum Q[n]",
            "calculation": calculation,
            "source": self._source(
                "TIME_ONLY IQ16 ADU", record, "iq16_npy", "source_sha256",
                "模拟输入先由 ADC 采样，再在 RFDC 内完成数字下变频和 12 倍抽取；"
                "这里显示的是随后以 320 MS/s 输出的复数 I/Q。I、Q 各为一个有符号 16 位整数，"
                "不是 ADC 在 3.84 GS/s 下的原始转换码。",
            ),
        }

    def time_long_single(self, query: dict[str, list[str]]) -> dict[str, Any]:
        adc = query_adc(query)
        cadence_ms = int(query_one(query, "cadence_ms", "100"))
        if cadence_ms not in (10, 100, 1000):
            raise ValueError("TIME_ONLY long cadence_ms must be 10, 100, or 1000")
        width = cadence_ms // 10
        weights = np.asarray(self.time_long_array("n_valid")[:, adc], dtype=np.float64)
        values = np.column_stack([
            self.time_long_array("mean_i_adu")[:, adc],
            self.time_long_array("mean_q_adu")[:, adc],
            self.time_long_array("mean_power_adu2")[:, adc],
        ]).astype(np.float64, copy=False)
        if width > 1:
            values, weights = weighted_nonoverlap(values, weights, width)
        points = len(values)
        return {
            "domain": "time_long_single",
            "capture": self.time_long_index["label"],
            "adc": adc,
            "cadence_ms": cadence_ms,
            "time_s": ((np.arange(points) + 0.5) * cadence_ms / 1000.0).tolist(),
            "mean_i_adu": values[:, 0].tolist(),
            "mean_q_adu": values[:, 1].tolist(),
            "mean_power_adu2": values[:, 2].tolist(),
            "n_valid": weights.astype(np.uint64).tolist(),
            "temperature": self.time_temperature,
            "point_definition": (
                f"每个点由连续 {cadence_ms} ms 内全部有效 TIME_ONLY I/Q整数按样本数加权平均。"
            ),
            "formula": (
                r"\bar I_k=\frac{\sum_r n_r\bar I_r}{\sum_r n_r},\quad "
                r"\bar Q_k=\frac{\sum_r n_r\bar Q_r}{\sum_r n_r},\quad "
                r"\bar P_k=\frac{\sum_r n_r\,\overline{(I^2+Q^2)}_r}{\sum_r n_r}"
            ),
            "calculation": {
                "base_cadence_ms": 10, "display_cadence_ms": cadence_ms,
                "base_points": int(self.time_long_index["points"]), "display_points": points,
            },
            "source": {
                "kind": "TIME_ONLY 900秒在线统计",
                "meaning": (
                    "接收机处理了完整900秒、320 MS/s的post-DDC复数I/Q，但没有保存约9.2 TB原始流；"
                    "每个10 ms基础点直接累加I、Q、I²+Q²。这里的数字功率是mean(I²+Q²)，不是RMS。"
                ),
                "capture_id": self.time_long_index["label"],
                "array": "mean_i_adu, mean_q_adu, mean_power_adu2, n_valid",
                "sha256": self._identities["time_long_index"],
            },
        }

    def _short_complex(self, domain: str, capture: str, adc: int, bins: list[int], width: int) -> dict[str, Any]:
        if domain == "time_fft_single":
            raw = np.asarray(self.time_fft_array(capture)[:, adc, :])[:, bins]
            source_record = self.time_records[capture]
            source = self._source(
                "TIME_ONLY 4096点Hann FFT", source_record,
                "fft4096_complex64_npy", "fft4096_complex64_sha256",
                "先取得 RFDC 下变频和抽取后的 TIME_ONLY I/Q 整数，再由本报告软件每 4096 点"
                "乘 Hann 窗并作普通 FFT；它不是板上生产 F-engine 的直接输出。",
            )
            unit = "FFT 后 ADU"
            formula = (
                r"X_f=\frac{1}{\sum_{n=0}^{4095}w[n]}"
                r"\sum_{n=0}^{4095}w[n](I[n]+\mathrm{i}Q[n])"
                r"e^{-\mathrm{i}2\pi fn/4096},\quad P_f=|X_f|^2"
            )
        else:
            raw_iq = np.asarray(self.spec_raw_array(capture)[:, adc, :, :])[:, bins, :]
            raw = raw_iq[..., 0].astype(np.float64) + 1j * raw_iq[..., 1].astype(np.float64)
            source_record = self.spec_records[capture]
            source = self._source(
                "F-engine IQ16 count", source_record, "iq16_npy", "iq16_npy_sha256",
                "生产 F-engine 接收 RFDC 下变频和抽取后的复数 I/Q，经 4096 通道、8-tap PFB"
                "频率通道化并重新量化；这里的 I、Q 是所选频率通道每帧输出的有符号 16 位整数，"
                "不是 ADC 原始转换码。",
            )
            unit = "count"
            formula = (
                r"X_{r,f}=I_{r,f}+\mathrm{i}Q_{r,f},\quad "
                r"P_{r,f}=I_{r,f}^2+Q_{r,f}^2,\quad "
                r"\bar P_{k,f}=\frac{1}{B}\sum_{r=1}^{B}P_{r,f}"
            )
        if domain == "fengine_raw_single":
            power = (
                raw_iq[..., 0].astype(np.int64) ** 2
                + raw_iq[..., 1].astype(np.int64) ** 2
            )
        else:
            power = np.abs(raw) ** 2
        if width > 1:
            complex_values = self.aggregate_frames(raw, width)
            power_values = self.aggregate_frames(power, width)
        else:
            complex_values, power_values = raw, power
        time_ms = ((np.arange(len(complex_values)) + 0.5) * width * 4096 / 320_000.0).tolist()
        series = []
        for index, global_bin in enumerate(bins):
            values = complex_values[:, index]
            pvalues = power_values[:, index]
            if domain == "fengine_raw_single" and width == 1:
                i_values = raw_iq[:, index, 0]
                q_values = raw_iq[:, index, 1]
            else:
                i_values = values.real
                q_values = values.imag
            series.append({
                "global_bin": global_bin, "rf_mhz": float(self.rf_mhz[global_bin]),
                "i": i_values.tolist(), "q": q_values.tolist(), "power": pvalues.tolist(),
                "mean_power": float(np.mean(pvalues)),
            })
        return {
            "domain": domain, "capture": capture, "adc": adc, "bucket_frames": width,
            "bucket_seconds": width * 4096 / 320_000_000,
            "time_ms": time_ms, "series": series, "iq_unit": unit,
            "power_unit": f"{unit}²",
            "point_definition": (
                "每个点是一个完整 F-engine 帧的通道值，没有作时间平均。" if width == 1
                else f"每个点由连续 {width} 个完整频谱作时间平均；频率通道之间没有混合。"
            ),
            "formula": formula,
            "calculation": {"source_frames": int(len(raw)), "bucket_frames": width,
                            "output_points": int(len(complex_values))},
            "source": source,
        }

    def short_single(self, query: dict[str, list[str]], *, time_fft: bool) -> dict[str, Any]:
        adc, bins = query_adc(query), self._bins(query)
        width = int(query_one(query, "bucket", "1"))
        if width not in SHORT_BUCKETS:
            raise ValueError("bucket must be 1, 4, 16, 64, or 256 frames")
        if time_fft:
            capture = self._capture(query)
            return self._short_complex("time_fft_single", capture, adc, bins, width)
        capture = query_one(query, "capture", next(iter(self.spec_records)))
        if capture not in self.spec_records:
            raise ValueError("unknown F-engine raw capture")
        return self._short_complex("fengine_raw_single", capture, adc, bins, width)

    @functools.lru_cache(maxsize=384)
    def self_base(self, scan: str, adc: int, global_bin: int) -> tuple[np.ndarray, np.ndarray]:
        root = self.self_scans[scan]
        block, local = divmod(global_bin, 256)
        meta = json.loads((root / "mean_power_count2" / ".zarray").read_text())
        rows, chunk_rows = int(meta["shape"][0]), int(meta["chunks"][0])
        power = np.empty(rows, dtype=np.float64)
        valid = np.empty(rows, dtype=np.float64)
        for chunk_index, start in enumerate(range(0, rows, chunk_rows)):
            cube = np.fromfile(root / "mean_power_count2" / f"{chunk_index}.0.{block}", dtype="<f8")
            cube = cube.reshape(chunk_rows, 8, 256)
            count = min(chunk_rows, rows - start)
            power[start:start + count] = cube[:count, adc, local]
            weights = np.fromfile(root / "n_valid" / f"{chunk_index}.{block}", dtype="<u4")
            valid[start:start + count] = weights[:count]
        if np.any(valid <= 0) or not np.all(np.isfinite(power)):
            raise ValueError("self-power series has invalid samples")
        return power, valid

    def fengine_long_single(self, query: dict[str, list[str]]) -> dict[str, Any]:
        adc, bins = query_adc(query), self._bins(query)
        scan = query_one(query, "scan", "A").upper()
        if scan not in self.self_scans:
            raise ValueError("scan must be A, B, or C")
        cadence_ms = int(query_one(query, "cadence_ms", "10"))
        if cadence_ms not in (10, 100, 1000):
            raise ValueError("cadence_ms must be 10, 100, or 1000")
        width = cadence_ms // 10
        series = []
        points = None
        for global_bin in bins:
            power, valid = self.self_base(scan, adc, global_bin)
            if width > 1:
                values, weights = weighted_nonoverlap(power, valid, width)
            else:
                values, weights = power, valid
            points = len(values)
            reference = float(np.average(power, weights=valid))
            series.append({
                "global_bin": global_bin, "rf_mhz": float(self.rf_mhz[global_bin]),
                "power_count2": values.tolist(),
                "relative_power_percent": (100.0 * (values / reference - 1.0)).tolist(),
                "scan_mean_power_count2": reference,
                "n_valid": weights.astype(int).tolist(),
            })
        return {
            "domain": "fengine_long_single", "scan": scan, "adc": adc,
            "cadence_ms": cadence_ms,
            "time_s": ((np.arange(points or 0) + 0.5) * cadence_ms / 1000.0).tolist(),
            "series": series,
            "point_definition": f"每个点是生产 F-engine 在 {cadence_ms} ms 内所有有效频谱的 I²+Q² 平均。",
            "formula": (
                r"P_r=I_r^2+Q_r^2,\quad \bar P_k=\frac{\sum_r n_rP_r}{\sum_r n_r},\quad "
                r"\text{相对功率变化}=100\left(\frac{\bar P_k}{\langle P\rangle_{\rm scan}}-1\right)\%"
            ),
            "calculation": {"base_cadence_ms": 10, "display_cadence_ms": cadence_ms,
                            "display_points": points},
            "source": {
                "kind": "F-engine长期自功率",
                "meaning": "生产 F-engine 对每个 10 ms 时间桶、每个频率通道先逐帧计算 "
                "I²+Q²，再按有效频谱数求平均；这是数字功率随时间的变化，尚未换算成温度或 Jy。",
                "scan_id": self.self_scans[scan].name,
                "array": "mean_power_count2", "sha256": self._identities["self_manifests"][scan],
            },
        }

    def _time_pair(self, query: dict[str, list[str]]) -> dict[str, Any]:
        capture, pair = self._capture(query), query_pair(query)
        bucket_text = query_one(query, "bucket", "raw")
        raw = self.time_raw_array(capture)
        if bucket_text == "raw":
            start = int(query_one(query, "start_sample", "0"))
            if not 0 <= start <= len(raw) - 4096:
                raise ValueError("start_sample must leave room for 4096 real samples")
            left_iq = np.asarray(raw[start:start + 4096, pair[0], :], dtype=np.float64)
            right_iq = np.asarray(raw[start:start + 4096, pair[1], :], dtype=np.float64)
            left = left_iq[:, 0] + 1j * left_iq[:, 1]
            right = right_iq[:, 0] + 1j * right_iq[:, 1]
            visibility = left * np.conj(right)
            gamma = normalized_correlation_magnitude(
                visibility, np.abs(left) ** 2, np.abs(right) ** 2
            )
            reliable = np.zeros(len(visibility), dtype=bool)
            time_us = (np.arange(start, start + 4096) / 320.0).tolist()
            bucket_samples = 1
            text = "每个点只是两个同一时刻样点的瞬时复乘；尚未平均，因此还不是可靠相关量。"
        else:
            frames = int(bucket_text)
            if frames not in SHORT_BUCKETS[1:]:
                raise ValueError("TIME pair bucket must be raw, 4, 16, 64, or 256")
            bucket_samples = frames * 4096
            groups = len(raw) // bucket_samples
            left_iq = np.asarray(raw[:groups * bucket_samples, pair[0], :], dtype=np.float64)
            right_iq = np.asarray(raw[:groups * bucket_samples, pair[1], :], dtype=np.float64)
            left_iq = left_iq.reshape(groups, bucket_samples, 2)
            right_iq = right_iq.reshape(groups, bucket_samples, 2)
            left = left_iq[:, :, 0] + 1j * left_iq[:, :, 1]
            right = right_iq[:, :, 0] + 1j * right_iq[:, :, 1]
            visibility = np.mean(left * np.conj(right), axis=1)
            pa = np.mean(np.abs(left) ** 2, axis=1)
            pb = np.mean(np.abs(right) ** 2, axis=1)
            gamma = normalized_correlation_magnitude(visibility, pa, pb)
            reliable = np.isfinite(gamma) & (gamma >= PHASE_GATE)
            time_us = ((np.arange(groups) + 0.5) * bucket_samples / 320.0).tolist()
            text = f"每个点把连续 {bucket_samples:,} 对 TIME_ONLY 样点先复乘再平均。"
        phase = np.angle(visibility, deg=True)
        record = self.time_records[capture]
        return {
            "domain": "time_pair", "capture": capture, "pair": list(pair),
            "time_us": time_us, "amplitude_adu2": np.abs(visibility).tolist(),
            "phase_deg": phase.tolist(), "gamma": finite_list(gamma),
            "phase_reliable": reliable.tolist(), "phase_gate_gamma": PHASE_GATE,
            "point_definition": text,
            "formula": (
                r"C_{ab}[n]=(I_a+\mathrm{i}Q_a)(I_b-\mathrm{i}Q_b),\quad "
                r"V_{ab,k}=\frac{1}{B}\sum C_{ab}[n],\quad "
                r"|V|=\sqrt{(\Re V)^2+(\Im V)^2},\quad "
                r"\phi=\operatorname{atan2}(\Im V,\Re V),\quad "
                r"\text{相对复可见度}=100\frac{V_{ab}}{\sqrt{P_aP_b}}\%"
            ),
            "calculation": {"bucket_samples": bucket_samples, "output_points": len(visibility)},
            "source": self._source(
                "TIME_ONLY复乘", record, "iq16_npy", "source_sha256",
                "两路数据分别是 RFDC 下变频和抽取后的 TIME_ONLY 复数 I/Q；本图把同一时刻的"
                "两路 I/Q 作复乘。它是由两路数字读数计算出的相关量，不是 ADC 的直接读数。",
            ),
        }

    def _short_pair(self, query: dict[str, list[str]], *, time_fft: bool) -> dict[str, Any]:
        pair, bins = query_pair(query), self._bins(query)
        width = int(query_one(query, "bucket", "1"))
        if width not in SHORT_BUCKETS:
            raise ValueError("bucket must be 1, 4, 16, 64, or 256 frames")
        if time_fft:
            capture = self._capture(query)
            cube = self.time_fft_array(capture)
            left = np.asarray(cube[:, pair[0], :])[:, bins]
            right = np.asarray(cube[:, pair[1], :])[:, bins]
            record = self.time_records[capture]
            source = self._source(
                "TIME_ONLY 4096点Hann FFT复乘", record,
                "fft4096_complex64_npy", "fft4096_complex64_sha256",
                "两路 TIME_ONLY I/Q 分别由本报告软件作 4096 点 Hann FFT，再在同一频率上复乘；"
                "它是软件参照，不是生产 F-engine 的直接输出。",
            )
            unit = "FFT后ADU²"
            domain = "time_fft_pair"
            transform = (
                r"X_{a,f}=\operatorname{FFT}_{4096}(wz_a)_f/\sum w,\quad "
                r"X_{b,f}=\operatorname{FFT}_{4096}(wz_b)_f/\sum w,\quad "
            )
        else:
            capture = query_one(query, "capture", next(iter(self.spec_records)))
            if capture not in self.spec_records:
                raise ValueError("unknown F-engine raw capture")
            cube = self.spec_raw_array(capture)
            left_iq = np.asarray(cube[:, pair[0], :, :])[:, bins, :]
            right_iq = np.asarray(cube[:, pair[1], :, :])[:, bins, :]
            left = left_iq[..., 0].astype(np.float64) + 1j * left_iq[..., 1].astype(np.float64)
            right = right_iq[..., 0].astype(np.float64) + 1j * right_iq[..., 1].astype(np.float64)
            record = self.spec_records[capture]
            source = self._source(
                "F-engine瞬时复乘", record, "iq16_npy", "iq16_npy_sha256",
                "两路生产 F-engine 在同一频率、同一帧各输出一个复数 I/Q；本图先做"
                "Xa·conj(Xb)。单帧结果是计算量，不是 ADC 的直接读数，也还不是稳定的相关估计。",
            )
            unit = "count²"
            domain = "fengine_raw_pair"
            transform = ""
        product = left * np.conj(right)
        pa, pb = np.abs(left) ** 2, np.abs(right) ** 2
        if width > 1:
            visibility = self.aggregate_frames(product, width)
            pa = self.aggregate_frames(pa, width)
            pb = self.aggregate_frames(pb, width)
        else:
            visibility = product
        gamma = normalized_correlation_magnitude(visibility, pa, pb)
        reliable = np.isfinite(gamma) & (gamma >= PHASE_GATE) & (width > 1)
        series = []
        for index, global_bin in enumerate(bins):
            value = visibility[:, index]
            series.append({
                "global_bin": global_bin, "rf_mhz": float(self.rf_mhz[global_bin]),
                "amplitude": np.abs(value).tolist(), "phase_deg": np.angle(value, deg=True).tolist(),
                "gamma": finite_list(gamma[:, index]),
                "phase_reliable": reliable[:, index].tolist(),
            })
        return {
            "domain": domain, "capture": capture, "pair": list(pair),
            "bucket_frames": width, "bucket_seconds": width * 4096 / 320_000_000,
            "time_ms": ((np.arange(len(visibility)) + 0.5) * width * 4096 / 320_000.0).tolist(),
            "series": series, "amplitude_unit": unit, "phase_gate_gamma": PHASE_GATE,
            "point_definition": (
                "每个点是同一频率、同一帧两路复数的瞬时复乘；尚未形成可靠平均。" if width == 1
                else f"每个点是连续 {width} 个同频复乘结果的复数平均。"
            ),
            "formula": transform + (
                r"C_{ab,r,f}=X_{a,r,f}X_{b,r,f}^*,\quad "
                r"V_{ab}=\frac{1}{B}\sum_r C_{ab,r,f},\quad "
                r"|V|=\sqrt{(\Re V)^2+(\Im V)^2},\quad "
                r"\phi=\operatorname{atan2}(\Im V,\Re V),\quad "
                r"\text{相对复可见度}=100\frac{V_{ab}}{\sqrt{P_aP_b}}\%"
            ),
            "calculation": {"source_frames": len(product), "bucket_frames": width,
                            "output_points": len(visibility)},
            "source": source,
        }

    @functools.lru_cache(maxsize=256)
    def cross_base(self, pair: tuple[int, int], global_bin: int, cadence_ms: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        zarr = self.cross_scan / "xcorr.zarr"
        pair_index = PAIR_INDEX[pair]
        block, local = divmod(global_bin, 256)
        if cadence_ms == 100:
            rows = int(json.loads((zarr / "mean_cross_visibility_count2_100ms" / ".zarray").read_text())["shape"][0])
            seconds = rows // 10
            visibility = np.empty(rows, dtype=np.complex128)
            pa = np.empty(rows, dtype=np.float64)
            pb = np.empty(rows, dtype=np.float64)
            valid = np.empty(rows, dtype=np.float64)
            for second in range(seconds):
                cross = np.fromfile(zarr / "mean_cross_visibility_count2_100ms" / f"{second}.0.{block}", dtype="<c16").reshape(10, 28, 256)
                auto = np.fromfile(zarr / "mean_auto_power_count2_100ms" / f"{second}.0.{block}", dtype="<f8").reshape(10, 8, 256)
                nvalid = np.fromfile(zarr / "n_valid_100ms" / f"{second}.0", dtype="<u8").reshape(10, 16)
                if not np.all(nvalid == nvalid[:, :1]):
                    raise ValueError("100 ms n_valid differs among the sixteen SPEC blocks")
                sl = slice(second * 10, (second + 1) * 10)
                visibility[sl] = cross[:, pair_index, local]
                pa[sl], pb[sl] = auto[:, pair[0], local], auto[:, pair[1], local]
                valid[sl] = nvalid[:, 0]
        elif cadence_ms == 1000:
            rows = int(json.loads((zarr / "mean_cross_visibility_count2" / ".zarray").read_text())["shape"][0])
            visibility = np.empty(rows, dtype=np.complex128)
            pa = np.empty(rows, dtype=np.float64)
            pb = np.empty(rows, dtype=np.float64)
            valid = np.empty(rows, dtype=np.float64)
            for second in range(rows):
                cross = np.fromfile(zarr / "mean_cross_visibility_count2" / f"{second}.0.{block}", dtype="<c16").reshape(28, 256)
                auto = np.fromfile(zarr / "mean_auto_power_count2" / f"{second}.0.{block}", dtype="<f8").reshape(8, 256)
                nvalid = np.fromfile(zarr / "n_valid" / f"{second}.0", dtype="<u8")
                if nvalid.shape != (16,) or not np.all(nvalid == nvalid[0]):
                    raise ValueError("1 s n_valid differs among the sixteen SPEC blocks")
                visibility[second] = cross[pair_index, local]
                pa[second], pb[second] = auto[pair[0], local], auto[pair[1], local]
                valid[second] = nvalid[0]
        else:
            raise ValueError("cadence_ms must be 100 or 1000")
        return visibility, pa, pb, valid

    def fengine_long_pair(self, query: dict[str, list[str]]) -> dict[str, Any]:
        pair, bins = query_pair(query), self._bins(query)
        cadence_ms = int(query_one(query, "cadence_ms", "100"))
        if cadence_ms not in (100, 1000):
            raise ValueError("cadence_ms must be 100 or 1000")
        series = []
        points = 0
        for global_bin in bins:
            visibility, pa, pb, valid = self.cross_base(pair, global_bin, cadence_ms)
            gamma = normalized_correlation_magnitude(visibility, pa, pb)
            reliable = np.isfinite(gamma) & (gamma >= PHASE_GATE)
            points = len(visibility)
            series.append({
                "global_bin": global_bin, "rf_mhz": float(self.rf_mhz[global_bin]),
                "amplitude_count2": np.abs(visibility).tolist(),
                "phase_deg": np.angle(visibility, deg=True).tolist(),
                "gamma": finite_list(gamma), "phase_reliable": reliable.tolist(),
                "n_valid": valid.astype(int).tolist(),
            })
        return {
            "domain": "fengine_long_pair", "pair": list(pair), "cadence_ms": cadence_ms,
            "time_s": ((np.arange(points) + 0.5) * cadence_ms / 1000.0).tolist(),
            "series": series, "phase_gate_gamma": PHASE_GATE,
            "amplitude_unit": "count²",
            "point_definition": f"每个点是全4096通道产品中该频率连续 {cadence_ms} ms 的复乘平均。",
            "formula": (
                r"V_{ab,k}=\frac{\sum_r X_{a,r}X_{b,r}^*}{n_k},\quad "
                r"|V|=\sqrt{(\Re V)^2+(\Im V)^2},\quad "
                r"\phi=\operatorname{atan2}(\Im V,\Re V),\quad "
                r"\text{相对复可见度}=100\frac{V_{ab}}{\sqrt{P_aP_b}}\%"
            ),
            "calculation": {"cadence_ms": cadence_ms, "points": points},
            "source": {
                "kind": "F-engine全频复可见度",
                "meaning": f"两路生产 F-engine 的同频复数先逐帧计算 Xa·conj(Xb)，再按有效频谱数"
                f"平均成每 {cadence_ms} ms 一个复可见度；这是独立 50 Ω 条件下的仪器相关底，"
                "不是 ADC 直接读数或天空可见度。",
                "scan_id": self.cross_id,
                "array": "mean_cross_visibility_count2_100ms" if cadence_ms == 100 else "mean_cross_visibility_count2",
                "sha256": self._identities["cross_manifest"],
            },
        }

    def timeseries(self, query: dict[str, list[str]]) -> dict[str, Any]:
        domain = query_one(query, "domain", "time_single")
        if domain == "time_single":
            return self.time_single(query)
        if domain == "time_long_single":
            return self.time_long_single(query)
        if domain == "time_pair":
            return self._time_pair(query)
        if domain == "time_fft_single":
            return self.short_single(query, time_fft=True)
        if domain == "fengine_raw_single":
            return self.short_single(query, time_fft=False)
        if domain == "time_fft_pair":
            return self._short_pair(query, time_fft=True)
        if domain == "fengine_raw_pair":
            return self._short_pair(query, time_fft=False)
        if domain == "fengine_long_single":
            return self.fengine_long_single(query)
        if domain == "fengine_long_pair":
            return self.fengine_long_pair(query)
        raise ValueError("unknown timeseries domain")

    def allan(self, query: dict[str, list[str]]) -> dict[str, Any]:
        subject = query_one(query, "subject", "single")
        bins = self._bins(query)
        form = query_one(query, "form", "variance")
        scale = query_one(query, "scale", "relative")
        if form not in ("variance", "square_root"):
            raise ValueError("form must be variance or square_root")
        if scale not in ("relative", "absolute"):
            raise ValueError("scale must be relative or absolute")
        series = []
        if subject == "single":
            adc = query_adc(query)
            scan = query_one(query, "scan", "A").upper()
            if scan not in self.self_scans:
                raise ValueError("scan must be A, B, or C")
            for global_bin in bins:
                power, valid = self.self_base(scan, adc, global_bin)
                reference = float(np.average(power, weights=valid))
                values = 100.0 * (power / reference - 1.0) if scale == "relative" else power
                points = self.overlapping_allan(values, 0.01, SELF_TAUS, valid)
                white = self.white_noise_reference(points, form)
                series.append({
                    "global_bin": global_bin, "rf_mhz": float(self.rf_mhz[global_bin]),
                    "points": [{**point, "value": point[form], "white_reference": white[index]}
                               for index, point in enumerate(points)],
                    "scan_mean_power_count2": reference,
                })
            subject_value: dict[str, Any] = {"adc": adc, "scan": scan, "base_bucket_s": 0.01}
            source = {
                "kind": "F-engine 10 ms自功率",
                "meaning": "从生产 F-engine 的逐帧频率通道 I/Q 开始，先算 I²+Q²，再形成 10 ms"
                "平均功率序列；Allan 方差比较这条功率序列中相邻的两个时间平均窗口。",
                "scan_id": self.self_scans[scan].name,
                "array": "mean_power_count2", "sha256": self._identities["self_manifests"][scan],
            }
            if scale == "relative":
                definition = r"Y_r=100\left(\frac{P_r}{\langle P\rangle_{\rm scan}}-1\right)"
            else:
                definition = r"Y_r=P_r=I_r^2+Q_r^2"
            formula = (
                definition + r",\quad \bar Y_i=\frac{\sum_{r=i}^{i+m-1}n_rY_r}{\sum_{r=i}^{i+m-1}n_r},\quad "
                r"K=N-2m+1,\quad \sigma_A^2(\tau)=\frac{1}{2K}"
                r"\sum_{i=1}^{K}(\bar Y_{i+m}-\bar Y_i)^2"
            )
        elif subject == "pair":
            pair = query_pair(query)
            cadence_ms = int(query_one(query, "cadence_ms", "100"))
            if cadence_ms not in PAIR_TAUS:
                raise ValueError("pair cadence_ms must be 100 or 1000")
            for global_bin in bins:
                visibility, pa, pb, valid = self.cross_base(pair, global_bin, cadence_ms)
                points = self.overlapping_allan_visibility(
                    visibility, pa, pb, valid, cadence_ms / 1000.0,
                    PAIR_TAUS[cadence_ms], relative_percent=scale == "relative",
                )
                white = self.white_noise_reference(points, form)
                series.append({
                    "global_bin": global_bin, "rf_mhz": float(self.rf_mhz[global_bin]),
                    "points": [{**point, "value": point[form], "white_reference": white[index]}
                               for index, point in enumerate(points)],
                })
            subject_value = {"pair": list(pair), "scan": self.cross_id,
                             "base_bucket_s": cadence_ms / 1000.0, "cadence_ms": cadence_ms}
            source = {
                "kind": "F-engine全频复可见度",
                "meaning": f"从两路生产 F-engine 同频复乘并平均得到的 {cadence_ms} ms 复可见度序列"
                "开始；Allan 方差比较相邻时间窗口的完整复数向量差，不把相位角直接相减。",
                "scan_id": self.cross_id,
                "array": "mean_cross_visibility_count2_100ms" if cadence_ms == 100 else "mean_cross_visibility_count2",
                "sha256": self._identities["cross_manifest"],
            }
            if scale == "relative":
                definition = (
                    r"Y_i=100\frac{\bar V_{ab,i}}{\sqrt{\bar P_{a,i}\bar P_{b,i}}}"
                )
            else:
                definition = r"Y_i=\bar V_{ab,i}"
            formula = (
                definition + r",\quad \bar V_{ab,i}=\frac{\sum_{r=i}^{i+m-1}n_rV_{ab,r}}"
                r"{\sum_{r=i}^{i+m-1}n_r},\quad K=N-2m+1,\quad "
                r"\sigma_A^2(\tau)=\frac{1}{2K}\sum_{i=1}^{K}"
                r"|Y_{i+m}-Y_i|^2"
            )
        else:
            raise ValueError("subject must be single or pair")
        if scale == "relative":
            unit = "%²" if form == "variance" else "%"
        else:
            unit = "count⁴" if form == "variance" else "count²"
        return {
            "format": "T510_STAGE35_SIMPLE_ALLAN_V1", "subject": subject,
            **subject_value, "form": form, "scale": scale, "unit": unit,
            "series": series, "formula": formula,
            "white_formula": (
                r"W(\tau)=W(\tau_0)\frac{\tau_0}{\tau}" if form == "variance"
                else r"W(\tau)=W(\tau_0)\sqrt{\frac{\tau_0}{\tau}}"
            ),
            "point_definition": "实线每点来自实测数据；同色虚线只表示从首点出发时白噪声应有的下降速度。",
            "source": source,
        }


class Handler(BaseHTTPRequestHandler):
    server_version = "T510Stage35SimpleExplorer/1"

    @property
    def app(self) -> "Server":
        return self.server  # type: ignore[return-value]

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("stage35-simple-explorer: " + fmt % args + "\n")

    def end_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "font-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'",
        )
        super().end_headers()

    def send_bytes(self, status: int, content_type: str, payload: bytes, *, head: bool = False) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        dynamic_asset = "json" in content_type or content_type in {
            "text/html", "text/css", "text/javascript", "application/javascript"
        }
        self.send_header("Cache-Control", "no-store" if dynamic_asset else "public, max-age=3600")
        self.end_headers()
        if not head:
            self.wfile.write(payload)

    def send_json(self, value: Any, *, head: bool = False) -> None:
        payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
        self.send_bytes(200, "application/json; charset=utf-8", payload, head=head)

    def route(self, *, head: bool) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        try:
            if parsed.path == "/healthz":
                self.send_json({"ok": True, "application": "stage35-simple"}, head=head)
            elif parsed.path == "/api/v2/meta":
                self.send_json(self.app.data.meta(), head=head)
            elif parsed.path == "/api/v2/timeseries":
                self.send_json(self.app.data.timeseries(query), head=head)
            elif parsed.path == "/api/v2/allan":
                self.send_json(self.app.data.allan(query), head=head)
            elif parsed.path == "/":
                self.static("index.html", head)
            elif parsed.path.startswith("/static/"):
                self.static(parsed.path.removeprefix("/static/"), head)
            else:
                self.send_bytes(404, "text/plain; charset=utf-8", b"not found\n", head=head)
        except (ValueError, KeyError, FileNotFoundError, json.JSONDecodeError) as error:
            self.send_bytes(400, "application/json; charset=utf-8",
                            json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False).encode(), head=head)
        except Exception as error:
            self.send_bytes(500, "application/json; charset=utf-8",
                            json.dumps({"ok": False, "error": f"internal data error: {error}"}, ensure_ascii=False).encode(), head=head)

    def static(self, relative: str, head: bool) -> None:
        if not relative or relative.startswith("/") or ".." in Path(relative).parts:
            self.send_bytes(404, "text/plain; charset=utf-8", b"not found\n", head=head)
            return
        path = (self.app.static_root / relative).resolve()
        if self.app.static_root not in path.parents or not path.is_file():
            self.send_bytes(404, "text/plain; charset=utf-8", b"not found\n", head=head)
            return
        self.send_bytes(200, mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                        path.read_bytes(), head=head)

    def do_GET(self) -> None:
        self.route(head=False)

    def do_HEAD(self) -> None:
        self.route(head=True)

    def do_POST(self) -> None:
        self.send_bytes(405, "application/json", b'{"ok":false,"error":"read-only: GET/HEAD only"}')

    do_PUT = do_POST
    do_DELETE = do_POST
    do_PATCH = do_POST


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], data: SimpleData, static_root: Path):
        self.data = data
        self.static_root = static_root.resolve(strict=True)
        super().__init__(address, Handler)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--helper-dir", type=Path, required=True)
    parser.add_argument("--static-root", type=Path, required=True)
    parser.add_argument("--bind", default="0.0.0.0:8035")
    args = parser.parse_args()
    host, port_text = args.bind.rsplit(":", 1)
    data = SimpleData(args.config, args.helper_dir)
    Server((host, int(port_text)), data, args.static_root).serve_forever(poll_interval=0.25)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
