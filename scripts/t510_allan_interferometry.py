#!/usr/bin/env python3
"""Stage 34d sample0-bucket Allan stability and eight-lane interferometry campaign."""

from __future__ import annotations

import argparse
import cmath
import csv
import hashlib
import json
import math
from pathlib import Path
import random
import statistics
import struct
import sys
import time
from typing import Any, Iterable, Sequence
from urllib import request as urllib_request

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import t510_adc_correlated_noise_campaign as c34c
from scripts import t510_fullband_spur_scan as fullband
from scripts import t510_power_thermal_causality as c34c3


CORE_VERSION = "0x00010034"
BITSTREAM_ID = "fengine-0x00010034"
BITSTREAM_SHA256 = "c21d93f5ea71e9ac17a4448cff138a8faaf9c7347d879be919b680d196b8a5be"
PFB_PROFILE_ID = "0x34a80001"
PRODUCTION_CLOCK_PROFILE = "160m_10m_cont_manual_clkin2"
BOARD_ID = 1
CENTER_MHZ = 1020.0
FIXED_RF_MHZ = (960.0,)
GRID_RF_MHZ = (
    970.0, 980.0, 990.0, 1000.0, 1010.0,
    1030.0, 1040.0, 1050.0, 1060.0, 1070.0, 1080.0,
)
OFFGRID_RF_MHZ = (966.875, 988.75, 1007.5, 1032.5, 1051.25, 1073.125)
RF_FREQUENCIES_MHZ = FIXED_RF_MHZ + GRID_RF_MHZ + OFFGRID_RF_MHZ
ADC_PAIRS = tuple((a, b) for a in range(8) for b in range(a + 1, 8))
SAME_TILE_PAIRS = ((0, 1), (2, 3), (4, 5), (6, 7))
SHORT_TAUS = (0.1, 0.2, 0.4, 0.8, 1.6, 3.2, 6.4, 12.8, 25.6)
LONG_TAUS = (1, 2, 4, 8, 16, 32, 64, 128)
PACKETS_PER_FLOW = 32


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def shared_plan() -> list[dict[str, Any]]:
    return [
        {"name": "shared_160msps_600s_100ms", "rate": 160, "duration": 600, "bucket_ms": 100},
        {"name": "shared_320msps_600s_100ms", "rate": 320, "duration": 600, "bucket_ms": 100},
        {"name": "shared_320msps_3600s_1s", "rate": 320, "duration": 3600, "bucket_ms": 1000},
        {"name": "shared_160msps_3600s_1s", "rate": 160, "duration": 3600, "bucket_ms": 1000},
    ]


def open_plan() -> list[dict[str, Any]]:
    return [
        {"name": "open_320msps_600s_100ms", "rate": 320, "duration": 600, "bucket_ms": 100},
        {"name": "open_160msps_600s_100ms", "rate": 160, "duration": 600, "bucket_ms": 100},
        {"name": "open_160msps_3600s_1s", "rate": 160, "duration": 3600, "bucket_ms": 1000},
        {"name": "open_320msps_3600s_1s", "rate": 320, "duration": 3600, "bucket_ms": 1000},
    ]


def _read_exact(blob: bytes, offset: int, size: int) -> tuple[bytes, int]:
    end = offset + size
    if end > len(blob):
        raise ValueError(f"truncated TIS1 at byte {offset}, need {size}")
    return blob[offset:end], end


def decode_tis1(blob: bytes) -> dict[str, Any]:
    if len(blob) < 64 or blob[:4] != b"TIS1":
        raise ValueError("not a TIS1 file")
    version, header_bytes = struct.unpack_from("<HH", blob, 4)
    if version != 1 or header_bytes != 64:
        raise ValueError(f"unsupported TIS1 version/header {version}/{header_bytes}")
    (
        metadata_bytes, bucket_ms, sample_rate_msps, duration_seconds,
        target_count, lane_count, pair_count, _reserved,
        record_count, started_unix_ms, _origin, record_bytes,
    ) = struct.unpack_from("<IIIIHHHHQQQQ", blob, 8)
    expected_record_bytes = 32 + lane_count * 40 + pair_count * 24
    if lane_count != 8 or pair_count not in (0, 1, 28):
        raise ValueError(f"invalid TIS1 lane/pair count {lane_count}/{pair_count}")
    if record_bytes != expected_record_bytes:
        raise ValueError(f"TIS1 record size {record_bytes}, expected {expected_record_bytes}")
    metadata_raw, offset = _read_exact(blob, header_bytes, metadata_bytes)
    metadata = json.loads(metadata_raw)
    if len(metadata.get("targets", [])) != target_count or len(metadata.get("pairs", [])) != pair_count:
        raise ValueError("TIS1 metadata mapping count mismatch")
    if len(blob) != offset + record_count * record_bytes:
        raise ValueError("TIS1 length does not match header")
    records: list[dict[str, Any]] = []
    previous_key: tuple[int, int] | None = None
    for _ in range(record_count):
        bucket, target, _reserved, first_sample0, last_sample0, sample_count = struct.unpack_from(
            "<IHHQQQ", blob, offset
        )
        cursor = offset + 32
        lanes = []
        for _lane in range(lane_count):
            count, sum_i, sum_q, sum_power, sum_power_squared = struct.unpack_from(
                "<Qdddd", blob, cursor
            )
            cursor += 40
            lanes.append((count, sum_i, sum_q, sum_power, sum_power_squared))
        crosses = []
        for _pair in range(pair_count):
            count, real, imag = struct.unpack_from("<Qdd", blob, cursor)
            cursor += 24
            crosses.append((count, real, imag))
        if cursor != offset + record_bytes:
            raise ValueError("TIS1 record decoder lost alignment")
        key = (bucket, target)
        if previous_key is not None and key <= previous_key:
            raise ValueError("TIS1 records are duplicated or out of order")
        previous_key = key
        if target >= target_count or first_sample0 > last_sample0 or sample_count == 0:
            raise ValueError(f"invalid TIS1 record {key}")
        records.append({
            "bucket": bucket,
            "target": target,
            "first_sample0": first_sample0,
            "last_sample0": last_sample0,
            "sample_count": sample_count,
            "lanes": lanes,
            "crosses": crosses,
        })
        offset = cursor
    expected_buckets = duration_seconds * 1000 // bucket_ms
    by_target: dict[int, list[dict[str, Any]]] = {target: [] for target in range(target_count)}
    for row in records:
        by_target[row["target"]].append(row)
    for target, rows in by_target.items():
        buckets = [row["bucket"] for row in rows]
        if buckets != list(range(expected_buckets)):
            raise ValueError(f"TIS1 target {target} missing/non-contiguous buckets")
    return {
        "version": version,
        "bucket_ms": bucket_ms,
        "sample_rate_msps": sample_rate_msps,
        "duration_seconds": duration_seconds,
        "target_count": target_count,
        "lane_count": lane_count,
        "pair_count": pair_count,
        "record_count": record_count,
        "started_unix_ms": started_unix_ms,
        "record_bytes": record_bytes,
        "metadata": metadata,
        "records": records,
        "by_target": by_target,
    }


def mean(values: Sequence[float]) -> float:
    return math.fsum(values) / len(values) if values else math.nan


def variance(values: Sequence[float], center: float | None = None) -> float:
    if len(values) < 2:
        return math.nan
    center = mean(values) if center is None else center
    return math.fsum((value - center) ** 2 for value in values) / (len(values) - 1)


def standard_deviation(values: Sequence[float]) -> float:
    value = variance(values)
    return math.sqrt(max(0.0, value)) if math.isfinite(value) else math.nan


def block_average(values: Sequence[float], width: int) -> list[float]:
    if width <= 0:
        raise ValueError("block width must be positive")
    count = len(values) // width
    return [mean(values[index * width:(index + 1) * width]) for index in range(count)]


def overlapping_allan_deviation(values: Sequence[float], width: int) -> float:
    if width <= 0 or len(values) < 2 * width + 1:
        return math.nan
    prefix = [0.0]
    for value in values:
        prefix.append(prefix[-1] + value)
    window = [(prefix[index + width] - prefix[index]) / width for index in range(len(values) - width + 1)]
    differences = [window[index + width] - window[index] for index in range(len(window) - width)]
    return math.sqrt(0.5 * mean([value * value for value in differences]))


def lag_correlation(values: Sequence[float], lag: int = 1) -> float:
    if lag <= 0 or len(values) < lag + 3:
        return math.nan
    left, right = values[:-lag], values[lag:]
    ml, mr = mean(left), mean(right)
    numerator = math.fsum((a - ml) * (b - mr) for a, b in zip(left, right))
    denominator = math.sqrt(
        math.fsum((a - ml) ** 2 for a in left) * math.fsum((b - mr) ** 2 for b in right)
    )
    return numerator / denominator if denominator else 0.0


def fit_log_slope(points: Sequence[tuple[float, float]]) -> float:
    valid = [(math.log(x), math.log(y)) for x, y in points if x > 0 and y > 0 and math.isfinite(y)]
    if len(valid) < 3:
        return math.nan
    mx = mean([x for x, _ in valid]); my = mean([y for _, y in valid])
    denominator = math.fsum((x - mx) ** 2 for x, _ in valid)
    return math.fsum((x - mx) * (y - my) for x, y in valid) / denominator if denominator else math.nan


def stability_curve(values: Sequence[float], bucket_seconds: float, taus: Sequence[float]) -> dict[str, Any]:
    center = mean(values)
    scale = abs(center) if center and math.isfinite(center) else 1.0
    rows = []
    for tau in taus:
        width = max(1, round(tau / bucket_seconds))
        averaged = block_average(values, width)
        scatter = standard_deviation(averaged) / scale if len(averaged) >= 2 else math.nan
        allan = overlapping_allan_deviation(values, width) / scale
        rows.append({"tau_seconds": width * bucket_seconds, "width": width, "fractional_stddev": scatter, "overlapping_allan_deviation": allan})
    slope = fit_log_slope([(row["tau_seconds"], row["fractional_stddev"]) for row in rows])
    finite_allan = [row for row in rows if math.isfinite(row["overlapping_allan_deviation"])]
    if finite_allan:
        minimum = min(finite_allan, key=lambda row: row["overlapping_allan_deviation"])
        allan_time: float | str = (
            f"<{bucket_seconds:g}" if minimum["width"] == 1 else minimum["tau_seconds"]
        )
    else:
        allan_time = "UNAVAILABLE"
    return {"slope": slope, "curve": rows, "allan_time_seconds": allan_time}


def aggregate_to_seconds(values: Sequence[float], bucket_ms: int) -> list[float]:
    return list(values) if bucket_ms == 1000 else block_average(values, 1000 // bucket_ms)


def acf(values: Sequence[float], maximum_lag: int = 64) -> list[float]:
    return [lag_correlation(values, lag) for lag in range(1, min(maximum_lag, len(values) - 3) + 1)]


def fft(values: Sequence[complex]) -> list[complex]:
    size = 1
    while size < len(values):
        size <<= 1
    data = list(values) + [0j] * (size - len(values))
    j = 0
    for i in range(1, size):
        bit = size >> 1
        while j & bit:
            j ^= bit; bit >>= 1
        j ^= bit
        if i < j:
            data[i], data[j] = data[j], data[i]
    length = 2
    while length <= size:
        root = cmath.exp(-2j * math.pi / length)
        for base in range(0, size, length):
            factor = 1 + 0j
            half = length // 2
            for offset in range(half):
                even = data[base + offset]
                odd = data[base + offset + half] * factor
                data[base + offset] = even + odd
                data[base + offset + half] = even - odd
                factor *= root
        length <<= 1
    return data


def temporal_psd(values: Sequence[float], bucket_seconds: float) -> dict[str, Any]:
    if len(values) < 16:
        return {"frequencies_hz": [], "power": [], "low_frequency_index": math.nan}
    centered = [value - mean(values) for value in values]
    spectrum = fft([complex(value, 0) for value in centered])
    size = len(spectrum)
    frequencies = [index / (size * bucket_seconds) for index in range(1, size // 2)]
    power = [abs(spectrum[index]) ** 2 / size for index in range(1, size // 2)]
    cutoff = min(len(power), max(8, len(values) // 32))
    index = fit_log_slope(list(zip(frequencies[:cutoff], power[:cutoff])))
    stride = max(1, len(frequencies) // 256)
    return {"frequencies_hz": frequencies[::stride], "power": power[::stride], "low_frequency_index": index}


def block_shuffle(values: Sequence[float], block: int, seed: int) -> list[float]:
    chunks = [list(values[index:index + block]) for index in range(0, len(values), block)]
    random.Random(seed).shuffle(chunks)
    return [value for chunk in chunks for value in chunk]


def first_pca_mode(matrix: Sequence[Sequence[float]], iterations: int = 80) -> dict[str, Any]:
    if not matrix or not matrix[0]:
        return {"explained_fraction": math.nan, "loadings": [], "scores": []}
    rows = len(matrix); columns = len(matrix[0])
    centers = [mean([matrix[row][column] for row in range(rows)]) for column in range(columns)]
    centered = [[matrix[row][column] - centers[column] for column in range(columns)] for row in range(rows)]
    covariance = [[0.0] * columns for _ in range(columns)]
    for row in centered:
        for left in range(columns):
            for right in range(left, columns):
                covariance[left][right] += row[left] * row[right]
    denominator = max(1, rows - 1)
    for left in range(columns):
        for right in range(left, columns):
            value = covariance[left][right] / denominator
            covariance[left][right] = covariance[right][left] = value
    vector = [1.0 / math.sqrt(columns)] * columns
    for _ in range(iterations):
        updated = [math.fsum(covariance[row][column] * vector[column] for column in range(columns)) for row in range(columns)]
        norm = math.sqrt(math.fsum(value * value for value in updated))
        if norm == 0:
            break
        vector = [value / norm for value in updated]
    eigenvalue = math.fsum(vector[row] * covariance[row][column] * vector[column] for row in range(columns) for column in range(columns))
    trace = math.fsum(covariance[index][index] for index in range(columns))
    scores = [math.fsum(row[column] * vector[column] for column in range(columns)) for row in centered]
    return {"explained_fraction": eigenvalue / trace if trace > 0 else 0.0, "loadings": vector, "scores": scores}


def moving_block_bootstrap_mean(values: Sequence[float], *, seed: int, replicates: int = 400) -> dict[str, Any]:
    if len(values) < 16:
        return {"p_two_sided": 1.0, "ci95": [math.nan, math.nan]}
    width = max(2, round(len(values) ** (1 / 3)))
    prefix = [0.0]
    extended = list(values) + list(values[:width])
    for value in extended:
        prefix.append(prefix[-1] + value)
    rng = random.Random(seed)
    count = math.ceil(len(values) / width)
    estimates = []
    for _ in range(replicates):
        total = 0.0; used = 0
        for _block in range(count):
            start = rng.randrange(len(values))
            take = min(width, len(values) - used)
            total += prefix[start + take] - prefix[start]
            used += take
        estimates.append(total / len(values))
    estimates.sort()
    negative = sum(value <= 0 for value in estimates) / replicates
    positive = sum(value >= 0 for value in estimates) / replicates
    return {
        "p_two_sided": min(1.0, 2 * min(negative, positive)),
        "ci95": [estimates[int(0.025 * replicates)], estimates[min(replicates - 1, int(0.975 * replicates))]],
        "block_width": width,
    }


def bh_adjust(p_values: Sequence[float]) -> list[float]:
    count = len(p_values)
    order = sorted(range(count), key=lambda index: p_values[index])
    adjusted = [1.0] * count
    running = 1.0
    for rank_from_end, index in enumerate(reversed(order), start=1):
        rank = count - rank_from_end + 1
        running = min(running, p_values[index] * count / rank)
        adjusted[index] = min(1.0, running)
    return adjusted


def _target_group(rf_mhz: float) -> str:
    if abs(rf_mhz - 960.0) < 1e-6:
        return "fixed"
    if any(abs(rf_mhz - value) < 1e-6 for value in OFFGRID_RF_MHZ):
        return "offgrid"
    return "grid10"


def _series_from_tis1(decoded: dict[str, Any]) -> dict[str, Any]:
    targets = sorted(decoded["metadata"]["targets"], key=lambda row: int(row["target_index"]))
    pairs = [tuple(pair) for pair in decoded["metadata"]["pairs"]]
    powers: dict[tuple[int, int], list[float]] = {}
    crosses: dict[tuple[int, int, int], list[complex]] = {}
    sample0: dict[int, list[tuple[int, int]]] = {}
    counts: dict[int, list[int]] = {}
    for target in targets:
        target_index = int(target["target_index"])
        rows = decoded["by_target"][target_index]
        sample0[target_index] = [(int(row["first_sample0"]), int(row["last_sample0"])) for row in rows]
        counts[target_index] = [int(row["sample_count"]) for row in rows]
        for lane in range(8):
            powers[(target_index, lane)] = [
                row["lanes"][lane][3] / row["lanes"][lane][0]
                for row in rows
            ]
        for pair_index, (channel_a, channel_b) in enumerate(pairs):
            crosses[(target_index, channel_a, channel_b)] = [
                complex(row["crosses"][pair_index][1], row["crosses"][pair_index][2])
                / row["crosses"][pair_index][0]
                for row in rows
            ]
    return {"targets": targets, "pairs": pairs, "powers": powers, "crosses": crosses, "sample0": sample0, "counts": counts}


def _curve_pass(curve: dict[str, Any]) -> bool:
    return math.isfinite(curve["slope"]) and -0.65 <= curve["slope"] <= -0.35


def _white_extrapolation_ratio(curve: dict[str, Any], target_tau: float = 128.0) -> float:
    rows = [row for row in curve["curve"] if math.isfinite(row["fractional_stddev"])]
    if not rows:
        return math.inf
    closest = min(rows, key=lambda row: abs(row["tau_seconds"] - target_tau))
    first = rows[0]
    predicted = first["fractional_stddev"] * math.sqrt(first["tau_seconds"] / closest["tau_seconds"])
    return closest["fractional_stddev"] / predicted if predicted > 0 else math.inf


def analyze_tis1(decoded: dict[str, Any], *, condition: str, seed: int) -> dict[str, Any]:
    series = _series_from_tis1(decoded)
    bucket_seconds = decoded["bucket_ms"] / 1000.0
    taus = SHORT_TAUS if decoded["bucket_ms"] == 100 else LONG_TAUS
    target_by_index = {int(row["target_index"]): row for row in series["targets"]}
    offgrid_indices = [
        index for index, row in target_by_index.items()
        if _target_group(float(row["actual_rf_mhz"])) == "offgrid"
    ]
    power_metrics = []
    for target_index, target in target_by_index.items():
        rf_mhz = float(target["actual_rf_mhz"])
        for lane in range(8):
            values = series["powers"][(target_index, lane)]
            curve = stability_curve(values, bucket_seconds, taus)
            seconds = aggregate_to_seconds(values, decoded["bucket_ms"])
            shuffled = block_shuffle(values, max(1, round(1 / bucket_seconds)), seed ^ (target_index << 8) ^ lane)
            shuffled_curve = stability_curve(shuffled, bucket_seconds, taus)
            power_metrics.append({
                "target_index": target_index,
                "rf_mhz": rf_mhz,
                "group": _target_group(rf_mhz),
                "lane": lane,
                "slope": curve["slope"],
                "slope_pass": _curve_pass(curve),
                "shuffled_slope": shuffled_curve["slope"],
                "lag1_1s": lag_correlation(seconds),
                "allan_time_seconds": curve["allan_time_seconds"],
                "curve": curve["curve"],
            })

    total_power = []
    spectroscopic = []
    matrix: list[list[float]] = []
    for bucket in range(len(series["powers"][(offgrid_indices[0], 0)])):
        row = []
        for lane in range(8):
            lane_logs = [math.log(max(series["powers"][(target, lane)][bucket], 1e-300)) for target in offgrid_indices]
            common = mean(lane_logs)
            row.extend(lane_logs)
            if bucket == 0:
                total_power.append({"lane": lane, "values": []})
                for target in offgrid_indices:
                    spectroscopic.append({"lane": lane, "target": target, "values": []})
            total_power[lane]["values"].append(common)
            for local, target in enumerate(offgrid_indices):
                spectroscopic[lane * len(offgrid_indices) + local]["values"].append(lane_logs[local] - common)
        matrix.append(row)
    total_metrics = []
    for item in total_power:
        curve = stability_curve(item["values"], bucket_seconds, taus)
        shuffled = stability_curve(
            block_shuffle(item["values"], max(1, round(1 / bucket_seconds)), seed ^ item["lane"]),
            bucket_seconds,
            taus,
        )
        total_metrics.append({"lane": item["lane"], "curve": curve["curve"], "slope": curve["slope"], "slope_pass": _curve_pass(curve), "shuffled_slope": shuffled["slope"], "allan_time_seconds": curve["allan_time_seconds"]})
    spectroscopic_metrics = []
    for item in spectroscopic:
        curve = stability_curve(item["values"], bucket_seconds, taus)
        spectroscopic_metrics.append({
            "lane": item["lane"],
            "target_index": item["target"],
            "rf_mhz": float(target_by_index[item["target"]]["actual_rf_mhz"]),
            "slope": curve["slope"],
            "slope_pass": _curve_pass(curve),
            "allan_time_seconds": curve["allan_time_seconds"],
            "curve": curve["curve"],
        })
    pca = first_pca_mode(matrix)
    representative = total_power[0]["values"]
    pca_summary = {
        "explained_fraction": pca["explained_fraction"],
        "loadings": pca["loadings"],
        "score_acf": acf(pca["scores"]),
        "score_psd": temporal_psd(pca["scores"], bucket_seconds),
        "adc0_total_acf": acf(representative),
        "adc0_total_psd": temporal_psd(representative, bucket_seconds),
    }

    common_differential = []
    for target in offgrid_indices:
        left = [math.log(max(value, 1e-300)) for value in series["powers"][(target, 0)]]
        right = [math.log(max(value, 1e-300)) for value in series["powers"][(target, 2)]]
        common = [(a + b) / 2 for a, b in zip(left, right)]
        differential = [(a - b) / 2 for a, b in zip(left, right)]
        common_curve = stability_curve(common, bucket_seconds, taus)
        differential_curve = stability_curve(differential, bucket_seconds, taus)
        common_differential.append({
            "rf_mhz": float(target_by_index[target]["actual_rf_mhz"]),
            "common_slope": common_curve["slope"],
            "differential_slope": differential_curve["slope"],
            "common_curve": common_curve["curve"],
            "differential_curve": differential_curve["curve"],
        })

    cross_metrics = []
    for target in offgrid_indices:
        rf_mhz = float(target_by_index[target]["actual_rf_mhz"])
        for pair_index, (channel_a, channel_b) in enumerate(series["pairs"]):
            raw = series["crosses"][(target, channel_a, channel_b)]
            powers_a = series["powers"][(target, channel_a)]
            powers_b = series["powers"][(target, channel_b)]
            normalized = [value / math.sqrt(max(pa * pb, 1e-300)) for value, pa, pb in zip(raw, powers_a, powers_b)]
            average = complex(mean([value.real for value in normalized]), mean([value.imag for value in normalized]))
            magnitudes = [abs(value) for value in normalized]
            phases = []
            for value in normalized:
                phase = cmath.phase(value)
                if phases:
                    while phase - phases[-1] > math.pi:
                        phase -= 2 * math.pi
                    while phase - phases[-1] < -math.pi:
                        phase += 2 * math.pi
                phases.append(phase)
            residual_re = [value.real - average.real for value in normalized]
            residual_im = [value.imag - average.imag for value in normalized]
            re_curve = stability_curve(residual_re, bucket_seconds, taus)
            im_curve = stability_curve(residual_im, bucket_seconds, taus)
            one_second_re = aggregate_to_seconds(residual_re, decoded["bucket_ms"])
            one_second_im = aggregate_to_seconds(residual_im, decoded["bucket_ms"])
            bootstrap_re = moving_block_bootstrap_mean(
                [value.real for value in normalized], seed=seed ^ (target << 12) ^ (pair_index << 1)
            )
            bootstrap_im = moving_block_bootstrap_mean(
                [value.imag for value in normalized], seed=seed ^ (target << 12) ^ (pair_index << 1) ^ 1
            )
            cross_metrics.append({
                "rf_mhz": rf_mhz,
                "target_index": target,
                "channel_a": channel_a,
                "channel_b": channel_b,
                "tile_group": "same_tile" if (channel_a, channel_b) in SAME_TILE_PAIRS else "cross_tile",
                "mean_gamma_re": average.real,
                "mean_gamma_im": average.imag,
                "mean_coherence": abs(average),
                "mean_phase_deg": math.degrees(cmath.phase(average)) if abs(average) >= 0.05 else None,
                "phase_gate": "ACTIVE" if abs(average) >= 0.05 else "SOURCE_TOO_WEAK_FOR_PHASE_GATE",
                "coherence_magnitude_pp_fraction": (max(magnitudes) - min(magnitudes)) / mean(magnitudes) if mean(magnitudes) > 0 else math.inf,
                "phase_pp_deg": math.degrees(max(phases) - min(phases)) if abs(average) >= 0.05 else None,
                "re_slope": re_curve["slope"],
                "im_slope": im_curve["slope"],
                "re_slope_pass": _curve_pass(re_curve),
                "im_slope_pass": _curve_pass(im_curve),
                "re_lag1_1s": lag_correlation(one_second_re),
                "im_lag1_1s": lag_correlation(one_second_im),
                "re_white_128_ratio": _white_extrapolation_ratio(re_curve),
                "im_white_128_ratio": _white_extrapolation_ratio(im_curve),
                "re_curve": re_curve["curve"],
                "im_curve": im_curve["curve"],
                "bootstrap_re": bootstrap_re,
                "bootstrap_im": bootstrap_im,
            })
    p_values = [
        value
        for row in cross_metrics
        for value in (row["bootstrap_re"]["p_two_sided"], row["bootstrap_im"]["p_two_sided"])
    ]
    adjusted = bh_adjust(p_values)
    for index, row in enumerate(cross_metrics):
        row["bh_q_re"] = adjusted[2 * index]
        row["bh_q_im"] = adjusted[2 * index + 1]
        row["zero_mean_significant_q0p01"] = min(row["bh_q_re"], row["bh_q_im"]) <= 0.01

    spectroscopic_pass_fraction = mean([float(row["slope_pass"]) for row in spectroscopic_metrics])
    total_pass_fraction = mean([float(row["slope_pass"]) for row in total_metrics])
    allan_classification = (
        "SCALAR_TOTAL_POWER_MODE_DOMINANT"
        if total_pass_fraction < 0.8 and spectroscopic_pass_fraction >= 0.8 and pca["explained_fraction"] >= 0.70
        else "FREQUENCY_DEPENDENT_OR_CHANNEL_LOCAL_DRIFT"
        if total_pass_fraction < 0.8 and spectroscopic_pass_fraction < 0.8
        else "ALLAN_WHITE_NOISE_REGION_CONFIRMED"
    )
    return {
        "condition": condition,
        "bucket_ms": decoded["bucket_ms"],
        "sample_rate_msps": decoded["sample_rate_msps"],
        "duration_seconds": decoded["duration_seconds"],
        "power_metrics": power_metrics,
        "sampled_total_power": total_metrics,
        "spectroscopic_allan": spectroscopic_metrics,
        "spectroscopic_pass_fraction": spectroscopic_pass_fraction,
        "total_power_pass_fraction": total_pass_fraction,
        "allan_classification": allan_classification,
        "pca": pca_summary,
        "adc02_common_differential": common_differential,
        "cross_metrics": cross_metrics,
    }


def _median_abs(rows: Iterable[dict[str, Any]], *keys: str) -> float:
    values = [abs(float(row[key])) for row in rows for key in keys if math.isfinite(float(row[key]))]
    return statistics.median(values) if values else math.inf


def classify_shared(runs: Sequence[dict[str, Any]]) -> dict[str, Any]:
    run_gates = []
    for run in runs:
        rows = [
            row for row in run["analysis"]["cross_metrics"]
            if (row["channel_a"], row["channel_b"]) == (0, 2)
        ]
        slope_passes = sum(int(row["re_slope_pass"]) + int(row["im_slope_pass"]) for row in rows)
        lag_median = _median_abs(rows, "re_lag1_1s", "im_lag1_1s")
        white_ratios = [
            float(row[key]) for row in rows for key in ("re_white_128_ratio", "im_white_128_ratio")
            if math.isfinite(float(row[key]))
        ]
        ratio_median = statistics.median(white_ratios) if white_ratios else math.inf
        gates = {
            "at_least_10_of_12_slopes": slope_passes >= 10,
            "median_abs_lag1_le_0p10": lag_median <= 0.10,
            "long_128s_scatter_le_2x_white": run["bucket_ms"] != 1000 or ratio_median <= 2.0,
        }
        run_gates.append({
            "name": run["name"], "rate": run["rate"], "bucket_ms": run["bucket_ms"],
            "slope_pass_count": slope_passes, "median_abs_lag1": lag_median,
            "median_128s_white_ratio": ratio_median, "gates": gates, "pass": all(gates.values()),
        })
    leakage_pairs = []
    for channel_a, channel_b in ADC_PAIRS:
        if (channel_a, channel_b) == (0, 2) or not ({channel_a, channel_b} & {0, 2}):
            continue
        significant_frequencies = set()
        for run in runs:
            for row in run["analysis"]["cross_metrics"]:
                if (row["channel_a"], row["channel_b"]) == (channel_a, channel_b) and row["zero_mean_significant_q0p01"]:
                    significant_frequencies.add(round(float(row["rf_mhz"]), 6))
        if len(significant_frequencies) >= 4:
            leakage_pairs.append({"pair": [channel_a, channel_b], "frequency_count": len(significant_frequencies)})
    passed = all(row["pass"] for row in run_gates)
    return {
        "classification": "SHARED_INPUT_VISIBILITY_RESIDUAL_PASS" if passed else "SHARED_INPUT_VISIBILITY_FLOOR_OBSERVED",
        "pass": passed,
        "run_gates": run_gates,
        "leakage": "SHARED_INPUT_LEAKAGE_OBSERVED" if leakage_pairs else "NO_BROADBAND_SHARED_INPUT_LEAKAGE_DETECTED",
        "leakage_pairs": leakage_pairs,
    }


def classify_open(runs: Sequence[dict[str, Any]]) -> dict[str, Any]:
    run_gates = []
    broadband_by_run: list[dict[str, Any]] = []
    for run in runs:
        rows = run["analysis"]["cross_metrics"]
        pass_count = sum(int(row["re_slope_pass"]) + int(row["im_slope_pass"]) for row in rows)
        total = 2 * len(rows)
        pair_pass = {}
        for pair in ADC_PAIRS:
            selected = [row for row in rows if (row["channel_a"], row["channel_b"]) == pair]
            pair_pass[f"{pair[0]}{pair[1]}"] = sum(
                int(row["re_slope_pass"]) + int(row["im_slope_pass"]) for row in selected
            ) >= 10
        lag_median = _median_abs(rows, "re_lag1_1s", "im_lag1_1s")
        white_ratios = [
            float(row[key]) for row in rows for key in ("re_white_128_ratio", "im_white_128_ratio")
            if math.isfinite(float(row[key]))
        ]
        ratio_median = statistics.median(white_ratios) if white_ratios else math.inf
        significant_pairs = []
        for pair in ADC_PAIRS:
            frequency_count = sum(
                int(row["zero_mean_significant_q0p01"])
                for row in rows if (row["channel_a"], row["channel_b"]) == pair
            )
            if frequency_count >= 4:
                significant_pairs.append({"pair": list(pair), "frequency_count": frequency_count})
        gates = {
            "slope_pass_fraction_ge_0p90": pass_count / total >= 0.90,
            "every_pair_at_least_10_of_12": all(pair_pass.values()),
            "median_abs_lag1_le_0p10": lag_median <= 0.10,
            "long_128s_scatter_le_2x_white": run["bucket_ms"] != 1000 or ratio_median <= 2.0,
            "no_broadband_significant_pair": not significant_pairs,
        }
        run_gates.append({
            "name": run["name"], "rate": run["rate"], "bucket_ms": run["bucket_ms"],
            "slope_pass_count": pass_count, "series_count": total,
            "slope_pass_fraction": pass_count / total, "pair_pass": pair_pass,
            "median_abs_lag1": lag_median, "median_128s_white_ratio": ratio_median,
            "significant_pairs": significant_pairs, "gates": gates, "pass": all(gates.values()),
        })
        broadband_by_run.extend({"run": run["name"], **item} for item in significant_pairs)
    all_pass = all(row["pass"] for row in run_gates)
    if all_pass:
        classification = "OPEN_INPUT_CROSS_CORRELATION_PREQUALIFIED"
    elif broadband_by_run or any(not row["gates"]["long_128s_scatter_le_2x_white"] for row in run_gates):
        classification = "OPEN_INPUT_CORRELATED_FLOOR_OBSERVED"
    else:
        classification = "OPEN_INPUT_NARROWBAND_PICKUP"
    same_tile = [
        row for run in runs for row in run["analysis"]["cross_metrics"]
        if (row["channel_a"], row["channel_b"]) in SAME_TILE_PAIRS
    ]
    cross_tile = [
        row for run in runs for row in run["analysis"]["cross_metrics"]
        if (row["channel_a"], row["channel_b"]) not in SAME_TILE_PAIRS
    ]
    return {
        "classification": classification,
        "pass": all_pass,
        "run_gates": run_gates,
        "broadband_significant_pairs": broadband_by_run,
        "same_tile_median_coherence": statistics.median(float(row["mean_coherence"]) for row in same_tile),
        "cross_tile_median_coherence": statistics.median(float(row["mean_coherence"]) for row in cross_tile),
    }


def _font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    candidates = [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc" if bold else "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def _line_plot(draw: ImageDraw.ImageDraw, values: Sequence[float], box: tuple[int, int, int, int], color: str, *, log_y: bool = False) -> None:
    finite = [value for value in values if math.isfinite(value) and (not log_y or value > 0)]
    if len(finite) < 2:
        return
    transformed = [math.log10(max(value, 1e-300)) if log_y else value for value in finite]
    low, high = min(transformed), max(transformed)
    if high == low:
        high = low + 1.0
    left, top, right, bottom = box
    points = []
    for index, value in enumerate(values):
        if not math.isfinite(value) or (log_y and value <= 0):
            continue
        y_value = math.log10(value) if log_y else value
        x = left + int(index * (right - left) / max(1, len(values) - 1))
        y = bottom - int((y_value - low) * (bottom - top) / (high - low))
        points.append((x, y))
    if len(points) >= 2:
        draw.line(points, fill=color, width=2)


def write_plots(root: Path, runs: Sequence[dict[str, Any]], phase_summary: dict[str, Any]) -> list[str]:
    plot_root = root / "plots"
    plot_root.mkdir(parents=True, exist_ok=True)
    outputs = []
    image = Image.new("RGB", (1900, 1050), "#f8fafc"); draw = ImageDraw.Draw(image)
    draw.text((50, 25), "Stage 34d: sampled-total-power 与 spectroscopic Allan", fill="#0f172a", font=_font(34, True))
    colors = ("#2563eb", "#dc2626", "#16a34a", "#9333ea", "#0891b2", "#ea580c", "#475569", "#be123c")
    for panel, run in enumerate(runs):
        left, top, right, bottom = 100, 110 + panel * 225, 1800, 290 + panel * 225
        draw.rectangle((left, top, right, bottom), outline="#94a3b8", width=1)
        for row in run["analysis"]["sampled_total_power"]:
            _line_plot(draw, [point["overlapping_allan_deviation"] for point in row["curve"]], (left, top, right, bottom), colors[row["lane"]], log_y=True)
        draw.text((left + 8, top + 8), f"{run['rate']} MS/s, bucket {run['bucket_ms']} ms, {run['duration']} s", fill="#334155", font=_font(17, True))
        draw.text((right - 390, top + 8), run["analysis"]["allan_classification"], fill="#7c2d12", font=_font(15))
    path = plot_root / "total_power_spectroscopic_allan.png"; image.save(path, optimize=True); outputs.append(str(path.resolve()))

    image = Image.new("RGB", (1900, 1050), "#f8fafc"); draw = ImageDraw.Draw(image)
    draw.text((50, 25), "Allan / integration slope heatmap (off-grid)", fill="#0f172a", font=_font(34, True))
    cell_w, cell_h = 55, 42
    for run_index, run in enumerate(runs):
        y0 = 105 + run_index * 225
        draw.text((30, y0), run["name"], fill="#334155", font=_font(15, True))
        metrics = [row for row in run["analysis"]["power_metrics"] if row["group"] == "offgrid"]
        for index, row in enumerate(metrics):
            column = index % 24; line = index // 24
            slope = float(row["slope"])
            distance = min(1.0, abs(slope + 0.5) / 0.5) if math.isfinite(slope) else 1.0
            color = (int(40 + 190 * distance), int(180 - 120 * distance), int(90 - 40 * distance))
            x = 520 + column * cell_w; y = y0 + line * cell_h
            draw.rectangle((x, y, x + cell_w - 2, y + cell_h - 2), fill=color)
            draw.text((x + 3, y + 10), f"{slope:+.2f}", fill="white", font=_font(12, True))
    path = plot_root / "allan_slope_heatmap.png"; image.save(path, optimize=True); outputs.append(str(path.resolve()))

    image = Image.new("RGB", (1900, 1000), "#f8fafc"); draw = ImageDraw.Draw(image)
    draw.text((50, 25), "复可见度 Re/Im 收敛与相关地板", fill="#0f172a", font=_font(34, True))
    for panel, run in enumerate(runs):
        rows = run["analysis"]["cross_metrics"]
        if run["analysis"]["condition"] == "shared":
            rows = [row for row in rows if (row["channel_a"], row["channel_b"]) == (0, 2)]
        pass_fraction = mean([float(row["re_slope_pass"]) for row in rows] + [float(row["im_slope_pass"]) for row in rows])
        coherence = statistics.median(float(row["mean_coherence"]) for row in rows)
        y = 125 + panel * 205
        draw.rectangle((80, y, 1820, y + 150), outline="#cbd5e1")
        draw.text((105, y + 18), run["name"], fill="#0f172a", font=_font(20, True))
        draw.text((700, y + 18), f"Re/Im slope pass {pass_fraction:.1%}", fill="#166534" if pass_fraction >= .9 else "#b91c1c", font=_font(22, True))
        draw.text((1260, y + 18), f"median |gamma| {coherence:.3g}", fill="#334155", font=_font(22))
        slopes = [float(row["re_slope"]) for row in rows] + [float(row["im_slope"]) for row in rows]
        _line_plot(draw, slopes, (110, y + 65, 1790, y + 135), "#2563eb")
    path = plot_root / "complex_visibility_convergence.png"; image.save(path, optimize=True); outputs.append(str(path.resolve()))

    image = Image.new("RGB", (1500, 900), "#f8fafc"); draw = ImageDraw.Draw(image)
    draw.text((45, 25), "28 pairs: same-tile / cross-tile correlation floor", fill="#0f172a", font=_font(31, True))
    pairs = list(ADC_PAIRS)
    long_run = next((run for run in runs if run["bucket_ms"] == 1000), runs[-1])
    for index, pair in enumerate(pairs):
        rows = [row for row in long_run["analysis"]["cross_metrics"] if (row["channel_a"], row["channel_b"]) == pair]
        coherence = statistics.median(float(row["mean_coherence"]) for row in rows)
        significant = sum(int(row["zero_mean_significant_q0p01"]) for row in rows)
        x = 80 + (index % 7) * 195; y = 120 + (index // 7) * 175
        color = "#dc2626" if significant >= 4 else "#16a34a" if pair in SAME_TILE_PAIRS else "#2563eb"
        draw.rectangle((x, y, x + 165, y + 130), fill="#ffffff", outline=color, width=3)
        draw.text((x + 12, y + 10), f"ADC{pair[0]}×ADC{pair[1]}", fill=color, font=_font(20, True))
        draw.text((x + 12, y + 48), f"|γ| {coherence:.3g}", fill="#334155", font=_font(17))
        draw.text((x + 12, y + 78), f"sig {significant}/6", fill="#334155", font=_font(17))
    draw.text((45, 835), f"classification: {phase_summary.get('classification')}", fill="#0f172a", font=_font(23, True))
    path = plot_root / "pair_floor_heatmap.png"; image.save(path, optimize=True); outputs.append(str(path.resolve()))
    write_json(plot_root / "classification.json", phase_summary)
    return outputs


def agent_get(args: argparse.Namespace, path: str, *, timeout: float = 60.0) -> dict[str, Any]:
    return fullband._http_json(args.agent_base.rstrip("/") + path, timeout=timeout)


def agent_post(args: argparse.Namespace, path: str, body: dict[str, Any], *, timeout: float = 240.0) -> dict[str, Any]:
    return fullband._http_json(args.agent_base.rstrip("/") + path, method="POST", body=body, timeout=timeout)


def receiver_state(args: argparse.Namespace) -> dict[str, Any]:
    return fullband._http_json(args.receiver_base.rstrip("/") + "/api/state")


def download_binary(url: str, destination: Path, *, timeout: float = 900.0) -> dict[str, Any]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    digest = hashlib.sha256(); size = 0
    with urllib_request.urlopen(url, timeout=timeout) as response, temporary.open("wb") as output:
        if response.status != 200:
            raise RuntimeError(f"binary download HTTP {response.status}")
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            output.write(chunk); digest.update(chunk); size += len(chunk)
    temporary.replace(destination)
    return {"path": str(destination.resolve()), "bytes": size, "sha256": digest.hexdigest()}


def stop_stream(args: argparse.Namespace) -> list[str]:
    return c34c3.stop_stream(args)


def validate_running(args: argparse.Namespace, board: dict[str, Any], rate: int) -> None:
    c34c.validate_board_status(board, rate, "spec_only", CENTER_MHZ)
    clock = board.get("clock", {})
    if clock.get("profile_id") != PRODUCTION_CLOCK_PROFILE:
        raise RuntimeError(f"production clock profile mismatch: {clock}")
    if int(clock.get("pll1_lock", 0)) != 1 or int(clock.get("pll2_lock", 0)) != 1:
        raise RuntimeError(f"clock PLL is not locked: {clock}")
    ocb1 = board.get("rfdc", {}).get("ocb1", {})
    if int(ocb1.get("ocb1_override_adc_mask", -1)) != 0 or ocb1.get("ocb1_override_state") != "DYNAMIC":
        raise RuntimeError(f"OCB1 is not dynamic: {ocb1}")


def fresh_configure(args: argparse.Namespace, template: dict[str, Any], rate: int) -> dict[str, Any]:
    args.bitstream_id = BITSTREAM_ID
    return c34c3.fresh_configure(args, template, rate, "spec_only")


def capture_edge(args: argparse.Namespace, run_dir: Path, edge: str) -> dict[str, Any]:
    paths, metadata = fullband.capture_receiver_pcap(
        receiver_base=args.receiver_base,
        local_dir=run_dir / "raw" / edge,
        packets_per_block=PACKETS_PER_FLOW,
        include_time=False,
    )
    return {
        **metadata,
        "paths": [str(path.resolve()) for path in paths],
        "sha256": {path.name: sha256_file(path) for path in paths},
    }


def start_monitor(args: argparse.Namespace, *, rate: int, duration: int, bucket_ms: int, formal: bool) -> dict[str, Any]:
    return fullband._http_json(
        args.receiver_base.rstrip("/") + "/api/measure/spec-stability",
        method="POST",
        body={
            "duration_seconds": duration,
            "formal": formal,
            "sample_rate_msps": rate,
            "center_mhz": CENTER_MHZ,
            "rf_frequencies_mhz": list(RF_FREQUENCIES_MHZ),
            "correlation_mode": "all",
            "bucket_ms": bucket_ms,
            "result_format": "binary",
            "lane_mask": 0xff,
            "include_time_statistics": False,
        },
        timeout=60.0,
    )


def wait_monitor(args: argparse.Namespace, duration: int) -> tuple[dict[str, Any], dict[str, Any]]:
    deadline = time.monotonic() + duration + 120.0
    last_status: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last_status = fullband._http_json(args.receiver_base.rstrip("/") + "/api/measure/spec-stability/status")
        if last_status.get("status") == "completed":
            result = fullband._http_json(
                args.receiver_base.rstrip("/") + "/api/measure/spec-stability/result",
                timeout=900.0,
            )
            return last_status, result
        if last_status.get("status") == "failed":
            raise RuntimeError(f"receiver monitor failed: {last_status.get('error')}")
        time.sleep(2.0)
    raise RuntimeError(f"receiver monitor timeout: {last_status}")


def _packet_rate(state: dict[str, Any]) -> float:
    return float(state.get("stats", {}).get("packets_per_sec", 0.0) or 0.0)


def performance_preflight(args: argparse.Namespace, template: dict[str, Any], root: Path) -> dict[str, Any]:
    stop_stream(args)
    configure = fresh_configure(args, template, 320)
    c34c3.receiver_prepare(args, 320, "spec_only")
    start = agent_post(args, "/api/v2/start", {"expected_board_id": BOARD_ID})
    time.sleep(3.0)
    before_board = agent_get(args, "/api/v2/status")
    before_receiver = receiver_state(args)
    validate_running(args, before_board, 320)
    baseline_rates = []
    for _ in range(10):
        baseline_rates.append(_packet_rate(receiver_state(args))); time.sleep(1.0)
    monitor_start = start_monitor(args, rate=320, duration=20, bucket_ms=1000, formal=False)
    enabled_rates = []
    for _ in range(20):
        enabled_rates.append(_packet_rate(receiver_state(args))); time.sleep(1.0)
    status, result = wait_monitor(args, 20)
    binary = download_binary(
        args.receiver_base.rstrip("/") + "/api/measure/spec-stability/data",
        root / "preflight" / "monitor_on.tis1",
    )
    after_board = agent_get(args, "/api/v2/status")
    after_receiver = receiver_state(args)
    integrity = fullband._window_integrity(before_board, after_board, before_receiver, after_receiver)
    baseline = statistics.median([value for value in baseline_rates if value > 0])
    enabled = statistics.median([value for value in enabled_rates if value > 0])
    throughput_ratio = enabled / baseline if baseline > 0 else 0.0
    decoded = decode_tis1(Path(binary["path"]).read_bytes())
    errors = []
    if not integrity["ok"]:
        errors.extend(integrity["errors"])
    if throughput_ratio < 0.98:
        errors.append(f"monitor throughput ratio {throughput_ratio:.6f} < 0.98")
    if binary["sha256"] != result.get("binary_sha256") or binary["bytes"] != result.get("binary_bytes"):
        errors.append("TIS1 size/SHA disagrees with receiver result")
    evidence = {
        "ok": not errors, "errors": errors, "configure": configure, "start": start,
        "monitor_start": monitor_start, "monitor_status": status, "monitor_result": result,
        "binary": binary, "record_count": decoded["record_count"],
        "baseline_packet_rate": baseline, "enabled_packet_rate": enabled,
        "throughput_ratio": throughput_ratio, "integrity": integrity,
        "before_board": before_board, "after_board": after_board,
    }
    write_json(root / "preflight" / "result.json", evidence)
    errors.extend(stop_stream(args))
    if errors:
        raise RuntimeError(f"320 MS/s monitor A/B failed: {errors}")
    return evidence


def execute_run(args: argparse.Namespace, template: dict[str, Any], row: dict[str, Any], condition: str) -> dict[str, Any]:
    run_dir = args.receiver_output / condition / "runs" / row["name"]
    run_dir.mkdir(parents=True, exist_ok=False)
    progress = args.receiver_output / condition / "current_run.json"
    evidence: dict[str, Any] = {
        **row, "condition": condition, "ok": False, "errors": [],
        "started_at_unix_ms": time.time_ns() // 1_000_000,
        "status": "PREPARING",
    }
    write_json(run_dir / "result.json", evidence); write_json(progress, evidence)
    try:
        stop_errors = stop_stream(args)
        if stop_errors:
            raise RuntimeError(f"pre-run safe stop failed: {stop_errors}")
        evidence["configure"] = fresh_configure(args, template, int(row["rate"]))
        c34c3.receiver_prepare(args, int(row["rate"]), "spec_only")
        evidence["start"] = agent_post(args, "/api/v2/start", {"expected_board_id": BOARD_ID})
        time.sleep(args.settle_seconds)
        evidence["thermal_warmup"] = c34c3.wait_for_thermal_stability(args)
        marker = c34c3.telemetry_marker(args)
        before_board = agent_get(args, "/api/v2/status")
        before_receiver = receiver_state(args)
        validate_running(args, before_board, int(row["rate"]))
        evidence["begin_capture"] = capture_edge(args, run_dir, "begin")
        evidence["monitor_start"] = start_monitor(
            args, rate=int(row["rate"]), duration=int(row["duration"]),
            bucket_ms=int(row["bucket_ms"]), formal=True,
        )
        evidence["status"] = "MONITOR_RUNNING"; write_json(run_dir / "result.json", evidence); write_json(progress, evidence)
        status, result = wait_monitor(args, int(row["duration"]))
        evidence["monitor_status"] = status; evidence["monitor_result"] = result
        binary = download_binary(
            args.receiver_base.rstrip("/") + "/api/measure/spec-stability/data",
            run_dir / f"{row['name']}.tis1",
        )
        evidence["binary"] = binary
        if binary["sha256"] != result.get("binary_sha256") or binary["bytes"] != result.get("binary_bytes"):
            raise RuntimeError("TIS1 size/SHA disagrees with receiver result")
        telemetry = c34c3.telemetry_since(args, marker)
        write_json(run_dir / "power_thermal_telemetry.json", telemetry)
        evidence["telemetry_integrity"] = c34c3.validate_telemetry(telemetry, int(row["duration"]), marker=marker)
        evidence["temperature_gate"] = c34c3.telemetry_temperature_gate(telemetry, int(row["duration"]))
        evidence["end_capture"] = capture_edge(args, run_dir, "end")
        after_board = agent_get(args, "/api/v2/status")
        after_receiver = receiver_state(args)
        validate_running(args, after_board, int(row["rate"]))
        integrity = fullband._window_integrity(before_board, after_board, before_receiver, after_receiver)
        if not integrity["ok"]:
            raise RuntimeError(f"digital integrity failed: {integrity['errors']}")
        decoded = decode_tis1(Path(binary["path"]).read_bytes())
        analysis = analyze_tis1(
            decoded, condition=condition,
            seed=int(hashlib.sha256(row["name"].encode()).hexdigest()[:8], 16),
        )
        evidence.update({
            "ok": True, "status": "COMPLETE", "integrity": integrity, "analysis": analysis,
            "before_board": before_board, "after_board": after_board,
            "before_receiver": c34c.receiver_condensed(before_receiver),
            "after_receiver": c34c.receiver_condensed(after_receiver),
            "tis1": {key: decoded[key] for key in ("version", "bucket_ms", "sample_rate_msps", "duration_seconds", "target_count", "lane_count", "pair_count", "record_count", "record_bytes")},
        })
    except Exception as exc:
        evidence["errors"].append(f"{type(exc).__name__}:{exc}"); evidence["status"] = "FAILED"
        raise
    finally:
        evidence["errors"].extend(stop_stream(args))
        evidence["finished_at_unix_ms"] = time.time_ns() // 1_000_000
        if evidence["errors"]:
            evidence["ok"] = False; evidence["status"] = "FAILED"
        write_json(run_dir / "result.json", evidence); write_json(progress, evidence)
    if not evidence["ok"]:
        raise RuntimeError(f"run {row['name']} failed: {evidence['errors']}")
    return evidence


def write_summary_csv(path: Path, runs: Sequence[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=(
            "run", "condition", "rate_msps", "bucket_ms", "duration_seconds",
            "allan_classification", "total_power_pass_fraction", "spectroscopic_pass_fraction",
            "pca_first_mode_fraction", "cross_re_im_slope_pass_fraction",
        ))
        writer.writeheader()
        for run in runs:
            cross = run["analysis"]["cross_metrics"]
            writer.writerow({
                "run": run["name"], "condition": run["condition"], "rate_msps": run["rate"],
                "bucket_ms": run["bucket_ms"], "duration_seconds": run["duration"],
                "allan_classification": run["analysis"]["allan_classification"],
                "total_power_pass_fraction": run["analysis"]["total_power_pass_fraction"],
                "spectroscopic_pass_fraction": run["analysis"]["spectroscopic_pass_fraction"],
                "pca_first_mode_fraction": run["analysis"]["pca"]["explained_fraction"],
                "cross_re_im_slope_pass_fraction": mean([float(row["re_slope_pass"]) for row in cross] + [float(row["im_slope_pass"]) for row in cross]),
            })


def pcap_manifest(root: Path) -> dict[str, Any]:
    files = sorted(root.rglob("*.pcap"))
    path = root / "pcap_manifest.sha256"
    path.write_text("".join(f"{sha256_file(item)}  {item.relative_to(root)}\n" for item in files))
    return {"path": str(path.resolve()), "sha256": sha256_file(path), "pcap_count": len(files)}


def tis1_manifest(root: Path) -> dict[str, Any]:
    files = sorted(root.rglob("*.tis1"))
    path = root / "tis1_manifest.sha256"
    path.write_text("".join(f"{sha256_file(item)}  {item.relative_to(root)}\n" for item in files))
    return {"path": str(path.resolve()), "sha256": sha256_file(path), "file_count": len(files), "total_bytes": sum(item.stat().st_size for item in files)}


def run_phase(args: argparse.Namespace, template: dict[str, Any], phase: str) -> int:
    campaign_path = args.receiver_output / "campaign.json"
    phase_root = args.receiver_output / phase
    phase_result_path = phase_root / "phase_result.json"
    if phase_result_path.exists():
        raise RuntimeError(f"refusing to overwrite completed/attempted phase evidence {phase_result_path}")
    original_board = agent_get(args, "/api/v2/status")
    original_receiver = receiver_state(args)
    if phase == "shared":
        if campaign_path.exists():
            raise RuntimeError(f"refusing to overwrite existing Stage 34d campaign {campaign_path}")
        state: dict[str, Any] = {
            "stage": "34d", "status": "SHARED_PHASE_IN_PROGRESS", "operational_ok": False,
            "core_version": CORE_VERSION, "bitstream_id": BITSTREAM_ID,
            "bitstream_sha256": BITSTREAM_SHA256, "pfb_profile_id": PFB_PROFILE_ID,
            "center_mhz": CENTER_MHZ, "clock_profile": PRODUCTION_CLOCK_PROFILE,
            "targets_mhz": list(RF_FREQUENCIES_MHZ), "adc_pairs": [list(pair) for pair in ADC_PAIRS],
            "mandatory_pending": ["INDEPENDENT_MATCHED_LOAD_ZERO_CORRELATION_QUALIFICATION_PENDING"],
            "physical_conditions": {
                "shared": "SSA RF INPUT -> two-way splitter -> ADC0/ADC2; TG/preamp off; attenuation 20 dB; ADC1/3/4/5/6/7 and all DAC physically open",
                "open": "PENDING_USER_CONFIRMATION",
            },
            "plans": {"shared": shared_plan(), "open": open_plan()},
            "preflight": None, "phases": {}, "errors": [],
            "started_at_unix_ms": time.time_ns() // 1_000_000,
        }
    else:
        if not campaign_path.exists():
            raise RuntimeError("open phase requires completed shared campaign evidence")
        state = json.loads(campaign_path.read_text())
        if state.get("status") != "WAITING_FOR_ALL_OPEN_CONFIRMATION" or not state.get("phases", {}).get("shared", {}).get("operational_ok"):
            raise RuntimeError(f"shared phase is not ready for physical transition: {state.get('status')}")
        state["status"] = "OPEN_PHASE_IN_PROGRESS"; state["operational_ok"] = False
        state["physical_conditions"]["open"] = "all eight ADC inputs physically disconnected; all DAC physically disconnected"
    phase_state: dict[str, Any] = {
        "phase": phase, "operational_ok": False, "status": "IN_PROGRESS", "runs": [],
        "errors": [], "started_at_unix_ms": time.time_ns() // 1_000_000,
    }
    state.setdefault("phases", {})[phase] = phase_state
    write_json(campaign_path, state); write_json(phase_result_path, phase_state)
    try:
        if phase == "shared":
            state["preflight"] = performance_preflight(args, template, args.receiver_output)
            write_json(campaign_path, state)
        plan = shared_plan() if phase == "shared" else open_plan()
        for row in plan:
            result = execute_run(args, template, row, phase)
            phase_state["runs"].append(result)
            write_json(phase_result_path, phase_state); write_json(campaign_path, state)
        phase_state["science"] = classify_shared(phase_state["runs"]) if phase == "shared" else classify_open(phase_state["runs"])
        phase_state["pcap_manifest"] = pcap_manifest(phase_root)
        phase_state["tis1_manifest"] = tis1_manifest(phase_root)
        write_summary_csv(phase_root / "summary.csv", phase_state["runs"])
        phase_state["plots"] = write_plots(phase_root, phase_state["runs"], phase_state["science"])
        phase_state["operational_ok"] = True
        phase_state["status"] = "WAITING_FOR_ALL_OPEN_CONFIRMATION" if phase == "shared" else "COMPLETE"
        state["status"] = phase_state["status"]
        state["operational_ok"] = True
        if phase == "open":
            state["final_classification"] = {
                "shared": state["phases"]["shared"]["science"],
                "open": phase_state["science"],
                "qualification_limit": "INDEPENDENT_MATCHED_LOAD_ZERO_CORRELATION_QUALIFICATION_PENDING",
            }
    except Exception as exc:
        error = f"{type(exc).__name__}:{exc}"
        phase_state["errors"].append(error); phase_state["status"] = "OPERATIONAL_FAIL"
        state["errors"].append(error); state["status"] = "STAGE34D_OPERATIONAL_FAIL"
    finally:
        finalize_errors = c34c3.safe_finalize(args, template, original_board, original_receiver)
        phase_state["finalize_errors"] = finalize_errors
        phase_state["finished_at_unix_ms"] = time.time_ns() // 1_000_000
        if finalize_errors:
            phase_state["errors"].extend(finalize_errors); state["errors"].extend(finalize_errors)
            phase_state["status"] = "OPERATIONAL_FAIL"; phase_state["operational_ok"] = False
            state["status"] = "STAGE34D_OPERATIONAL_FAIL"; state["operational_ok"] = False
        state["finished_at_unix_ms"] = phase_state["finished_at_unix_ms"]
        write_json(phase_result_path, phase_state); write_json(campaign_path, state)
        write_json(args.board_output / "campaign_pointer.json", {
            "campaign": str(campaign_path.resolve()), "phase": phase,
            "status": state["status"], "operational_ok": phase_state["operational_ok"],
        })
    return 0 if phase_state["operational_ok"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("shared", "open"), required=True)
    parser.add_argument("--shared-ssa-confirmed", action="store_true")
    parser.add_argument("--all-open-confirmed", action="store_true")
    parser.add_argument("--agent-base", default="http://192.168.100.117:8010")
    parser.add_argument("--receiver-base", default="http://192.168.100.162:8089")
    parser.add_argument("--configure-template", type=Path, default=Path("config/t510/configure_320_time_only.example.json"))
    parser.add_argument("--receiver-output", type=Path, default=Path("build/receiver/latest/evidence/allan_interferometry"))
    parser.add_argument("--board-output", type=Path, default=Path("build/board/latest/evidence/allan_interferometry"))
    parser.add_argument("--settle-seconds", type=float, default=2.0)
    args = parser.parse_args()
    if args.phase == "shared" and not args.shared_ssa_confirmed:
        parser.error("shared phase requires --shared-ssa-confirmed")
    if args.phase == "open" and not args.all_open_confirmed:
        parser.error("open phase requires --all-open-confirmed")
    args.receiver_output = args.receiver_output.resolve(); args.board_output = args.board_output.resolve()
    args.receiver_output.mkdir(parents=True, exist_ok=True); args.board_output.mkdir(parents=True, exist_ok=True)
    template = json.loads(args.configure_template.read_text())
    return run_phase(args, template, args.phase)


if __name__ == "__main__":
    raise SystemExit(main())
