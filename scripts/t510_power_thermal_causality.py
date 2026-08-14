#!/usr/bin/env python3
"""Stage 34c-3 board-load, RFDC DAC-tile, and natural AMS campaign."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import random
import statistics
import sys
import time
from typing import Any, Iterable

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from python import t510_astronomy as astronomy
from scripts import t510_adc_correlated_noise_campaign as c34c
from scripts import t510_fullband_spur_scan as fullband


CORE_VERSION = "0x00010034"
BITSTREAM_ID = "fengine-0x00010034"
BITSTREAM_SHA256 = "c21d93f5ea71e9ac17a4448cff138a8faaf9c7347d879be919b680d196b8a5be"
PFB_PROFILE_ID = "0x34a80001"
BOARD_ID = 1
CENTER_MHZ = 1020.0
LANE_MASK = 0x05
LANES = (0, 2)
FIXED_RF_MHZ = (960.0,)
GRID_RF_MHZ = (
    970.0, 980.0, 990.0, 1000.0, 1010.0,
    1030.0, 1040.0, 1050.0, 1060.0, 1070.0, 1080.0,
)
OFFGRID_RF_MHZ = (966.875, 988.75, 1007.5, 1032.5, 1051.25, 1073.125)
RF_FREQUENCIES_MHZ = FIXED_RF_MHZ + GRID_RF_MHZ + OFFGRID_RF_MHZ
FORMAL_SECONDS = 600
NATURAL_SECONDS = 3600
PRECHECK_SECONDS = 120
QUICK_SECONDS = 60
PACKETS_PER_FLOW = 32
THERMAL_WINDOW_SECONDS = 60
THERMAL_MAX_WAIT_SECONDS = 1200
THERMAL_ROBUST_DRIFT_C = 0.30
TRIPLET_WARNING_C = 2.0
TRIPLET_HARD_C = 2.5
NATURAL_WARNING_C = 2.5
NATURAL_HARD_C = 5.0
ABSOLUTE_HARD_C = 70.0
TELEMETRY_MISSING_ALLOWANCE = 6
TELEMETRY_MAX_GAP_SECONDS = 2


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


def output_load_plan() -> list[dict[str, Any]]:
    rows = []
    for repeat in range(1, 4):
        for condition, mode in (("A1", "spec_only"), ("B", "time_spec"), ("A2", "spec_only")):
            rows.append(
                {
                    "layer": "output_load",
                    "repeat": repeat,
                    "sample_rate_msps": 160,
                    "condition": condition,
                    "mode": mode,
                    "name": f"output_load_r{repeat}_{condition.lower()}_{mode}",
                }
            )
    return rows


def dac_tile_plan() -> list[dict[str, Any]]:
    rows = []
    triplet = 0
    for repeat, order in enumerate(((160, 320), (320, 160), (160, 320)), start=1):
        for rate in order:
            triplet += 1
            for condition, tile_state in (("A1", "DAC_UP"), ("B", "DAC_SHUTDOWN"), ("A2", "DAC_RESTORED")):
                rows.append(
                    {
                        "layer": "dac_tile",
                        "repeat": repeat,
                        "triplet": triplet,
                        "sample_rate_msps": rate,
                        "condition": condition,
                        "mode": "spec_only",
                        "tile_state": tile_state,
                        "name": f"dac_tile_t{triplet:02d}_{rate}msps_r{repeat}_{condition.lower()}_{tile_state.lower()}",
                    }
                )
    return rows


def natural_plan() -> list[dict[str, Any]]:
    return [
        {
            "layer": "natural",
            "repeat": 1,
            "condition": "OBSERVE",
            "mode": "spec_only",
            "sample_rate_msps": rate,
            "duration_seconds": NATURAL_SECONDS,
            "name": f"natural_{rate}msps_60min",
        }
        for rate in (160, 320)
    ]


def full_formal_plan() -> list[dict[str, Any]]:
    return output_load_plan() + dac_tile_plan() + natural_plan()


def monitor_frequency_contract() -> dict[str, Any]:
    return {
        str(rate): {
            f"{rf:.9f}": astronomy.rf_to_signed_bin(rf, CENTER_MHZ, rate)
            for rf in RF_FREQUENCIES_MHZ
        }
        for rate in (160, 320)
    }


def agent_get(args: argparse.Namespace, path: str, *, timeout: float = 60.0) -> dict[str, Any]:
    return fullband._http_json(args.agent_base.rstrip("/") + path, timeout=timeout)


def agent_post(
    args: argparse.Namespace,
    path: str,
    body: dict[str, Any],
    *,
    timeout: float = 240.0,
) -> dict[str, Any]:
    return fullband._http_json(
        args.agent_base.rstrip("/") + path,
        method="POST",
        body=body,
        timeout=timeout,
    )


def receiver_state(args: argparse.Namespace) -> dict[str, Any]:
    return fullband._http_json(args.receiver_base.rstrip("/") + "/api/state")


def receiver_prepare(args: argparse.Namespace, rate: int, mode: str) -> dict[str, Any]:
    return c34c.receiver_prepare(args.receiver_base, rate, mode, CENTER_MHZ)


def fresh_configure(
    args: argparse.Namespace,
    template: dict[str, Any],
    rate: int,
    mode: str = "spec_only",
) -> dict[str, Any]:
    args.bitstream_id = BITSTREAM_ID
    return c34c.configure(args, template, rate, mode, CENTER_MHZ)


def stop_stream(args: argparse.Namespace) -> list[str]:
    errors: list[str] = []
    try:
        agent_post(args, "/api/v2/stop", {}, timeout=60.0)
    except Exception as exc:
        errors.append(f"STOP:{type(exc).__name__}:{exc}")
    try:
        deadline = time.monotonic() + 8.0
        while time.monotonic() < deadline:
            board = agent_get(args, "/api/v2/status")
            receiver = receiver_state(args)
            packet_rate = float(receiver.get("stats", {}).get("packets_per_sec", 0.0) or 0.0)
            if (
                not board.get("streaming")
                and not board.get("pipeline", {}).get("stream_accepting")
                and packet_rate <= 1.0
            ):
                dac = board.get("dac", {})
                if int(dac.get("enable_mask", -1)) != 0 or any(
                    int(row.get("amplitude_code", -1)) != 0
                    for row in dac.get("channels", [])
                ):
                    errors.append("DAC_DIGITAL_READBACK_NOT_ZERO")
                return errors
            time.sleep(0.25)
        errors.append("STREAM_DID_NOT_QUIESCE")
    except Exception as exc:
        errors.append(f"STOP_VERIFY:{type(exc).__name__}:{exc}")
    return errors


def telemetry_marker(args: argparse.Namespace) -> dict[str, Any]:
    monitor = agent_get(args, "/api/v2/rfdc/calibration/monitor")
    row = monitor.get("power_thermal_telemetry") or {}
    epoch = str(row.get("epoch_id") or "")
    sequence = int(row.get("sequence") or 0)
    if not epoch or sequence <= 0:
        raise RuntimeError(f"resident power/thermal telemetry is not ready: {row}")
    return {"epoch_id": epoch, "sequence": sequence}


def telemetry_since(args: argparse.Namespace, marker: dict[str, Any]) -> list[dict[str, Any]]:
    result = agent_get(
        args,
        f"/api/v2/telemetry/power-thermal?since_seq={int(marker['sequence'])}",
        timeout=180.0,
    )
    rows = list(result.get("records", []))
    if rows and any(str(row.get("epoch_id")) != str(marker["epoch_id"]) for row in rows):
        raise RuntimeError("resident telemetry epoch changed during run")
    return rows


def validate_telemetry(
    rows: list[dict[str, Any]], duration_seconds: int, *, marker: dict[str, Any]
) -> dict[str, Any]:
    minimum = duration_seconds - TELEMETRY_MISSING_ALLOWANCE
    sequences = [int(row["sequence"]) for row in rows]
    if len(set(sequences)) != len(sequences):
        raise RuntimeError("resident telemetry has duplicate sequences")
    if len(sequences) < minimum:
        raise RuntimeError(
            f"resident telemetry has {len(sequences)} seconds, requires at least {minimum}"
        )
    gaps = [right - left for left, right in zip(sequences, sequences[1:])]
    maximum_gap = max(gaps, default=1)
    if maximum_gap > TELEMETRY_MAX_GAP_SECONDS:
        raise RuntimeError(f"resident telemetry maximum sequence gap is {maximum_gap} seconds")
    return {
        "epoch_id": marker["epoch_id"],
        "marker_sequence": marker["sequence"],
        "record_count": len(rows),
        "first_sequence": sequences[0] if sequences else None,
        "last_sequence": sequences[-1] if sequences else None,
        "maximum_sequence_gap_seconds": maximum_gap,
        "minimum_required": minimum,
    }


def telemetry_temperatures(rows: Iterable[dict[str, Any]]) -> dict[str, list[float]]:
    values: dict[str, list[float]] = {}
    for row in rows:
        for name, sample in dict(row.get("ams", {}).get("temperatures_c", {})).items():
            if isinstance(sample, dict) and sample.get("mean") is not None:
                values.setdefault(str(name), []).append(float(sample["mean"]))
    return values


def telemetry_temperature_gate(rows: list[dict[str, Any]], duration_seconds: int) -> dict[str, Any]:
    values = telemetry_temperatures(rows)
    sensors = {}
    hard = NATURAL_HARD_C if duration_seconds == NATURAL_SECONDS else TRIPLET_HARD_C
    warning = NATURAL_WARNING_C if duration_seconds == NATURAL_SECONDS else TRIPLET_WARNING_C
    for name, series in values.items():
        filtered = [
            statistics.median(series[max(0, index - 9): index + 1])
            for index in range(len(series))
        ]
        span = max(filtered) - min(filtered)
        maximum = max(filtered)
        sensors[name] = {
            "count": len(series),
            "min_c": min(filtered),
            "max_c": maximum,
            "span_c": span,
            "warning": span > warning,
            "hard_fail": span > hard or maximum >= ABSOLUTE_HARD_C,
        }
    if not sensors:
        raise RuntimeError("no AMS temperatures in resident telemetry")
    failed = [name for name, row in sensors.items() if row["hard_fail"]]
    if failed:
        raise RuntimeError(f"temperature hard gate failed: {failed}; {sensors}")
    return {
        "pass": True,
        "warning_span_c": warning,
        "hard_span_c": hard,
        "absolute_hard_c": ABSOLUTE_HARD_C,
        "warning_sensors": [name for name, row in sensors.items() if row["warning"]],
        "sensors": sensors,
    }


def thermal_window(rows: list[dict[str, Any]]) -> dict[str, Any]:
    temperatures = telemetry_temperatures(rows[-THERMAL_WINDOW_SECONDS:])
    sensors = {}
    for name, values in temperatures.items():
        if len(values) < THERMAL_WINDOW_SECONDS - 2:
            continue
        drift = statistics.median(values[-10:]) - statistics.median(values[:10])
        sensors[name] = {"count": len(values), "robust_drift_c": drift}
    return {
        "stable": bool(sensors)
        and all(abs(row["robust_drift_c"]) <= THERMAL_ROBUST_DRIFT_C for row in sensors.values()),
        "sensors": sensors,
    }


def wait_for_thermal_stability(args: argparse.Namespace) -> dict[str, Any]:
    marker = telemetry_marker(args)
    started = time.monotonic()
    deadline = started + THERMAL_MAX_WAIT_SECONDS
    while time.monotonic() < deadline:
        rows = telemetry_since(args, marker)
        summary = thermal_window(rows)
        if summary["stable"]:
            return {
                "elapsed_seconds": time.monotonic() - started,
                "marker": marker,
                "record_count": len(rows),
                "window": summary,
            }
        time.sleep(2.0)
    raise RuntimeError("temperature did not reach the registered 60-second stability rule within 20 minutes")


def correlation(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or len(left) < 3:
        return 0.0
    left_mean = statistics.fmean(left)
    right_mean = statistics.fmean(right)
    a = [value - left_mean for value in left]
    b = [value - right_mean for value in right]
    denominator = math.sqrt(sum(value * value for value in a) * sum(value * value for value in b))
    return sum(x * y for x, y in zip(a, b)) / denominator if denominator else 0.0


def ranks(values: list[float]) -> list[float]:
    indexed = sorted(enumerate(values), key=lambda item: item[1])
    result = [0.0] * len(values)
    start = 0
    while start < len(indexed):
        end = start + 1
        while end < len(indexed) and indexed[end][1] == indexed[start][1]:
            end += 1
        rank = (start + end - 1) / 2.0 + 1.0
        for index in range(start, end):
            result[indexed[index][0]] = rank
        start = end
    return result


def spearman(left: list[float], right: list[float]) -> float:
    return correlation(ranks(left), ranks(right))


def block_bootstrap_ci(
    left: list[float], right: list[float], *, seed: int, repetitions: int = 80, block: int = 16
) -> dict[str, Any]:
    count = min(len(left), len(right))
    if count < 16:
        return {"low": None, "high": None, "p_two_sided": 1.0, "repetitions": 0}
    ranked_left = ranks(left[:count])
    ranked_right = ranks(right[:count])
    rng = random.Random(seed)
    samples = []
    for _ in range(repetitions):
        indices: list[int] = []
        while len(indices) < count:
            start = rng.randrange(count)
            indices.extend((start + offset) % count for offset in range(block))
        indices = indices[:count]
        samples.append(
            correlation(
                [ranked_left[index] for index in indices],
                [ranked_right[index] for index in indices],
            )
        )
    ordered = sorted(samples)
    low = ordered[max(0, round(0.025 * (len(ordered) - 1)))]
    high = ordered[min(len(ordered) - 1, round(0.975 * (len(ordered) - 1)))]
    nonpositive = sum(value <= 0 for value in samples)
    nonnegative = sum(value >= 0 for value in samples)
    p_value = min(1.0, 2.0 * min(nonpositive, nonnegative) / len(samples))
    return {"low": low, "high": high, "p_two_sided": p_value, "repetitions": repetitions, "block": block}


def bh_adjust(p_values: list[float]) -> list[float]:
    count = len(p_values)
    indexed = sorted(enumerate(p_values), key=lambda item: item[1])
    adjusted = [1.0] * count
    running = 1.0
    for rank_index in range(count - 1, -1, -1):
        original_index, value = indexed[rank_index]
        rank = rank_index + 1
        running = min(running, value * count / rank)
        adjusted[original_index] = min(1.0, running)
    return adjusted


def maximum_cross_correlation(left: list[float], right: list[float], max_lag: int = 60) -> dict[str, Any]:
    # Rank once.  Re-ranking both cropped vectors for every one of 121 lags
    # makes a 3600-second, multi-sensor run need tens of thousands of sorts.
    # Pearson correlation of the full-series ranks is the standard efficient
    # Spearman cross-correlation approximation; the at-most-60 edge samples do
    # not affect a registered slow-trend interpretation.
    ranked_left = ranks(left)
    ranked_right = ranks(right)
    best = {"lag_seconds": 0, "correlation": correlation(ranked_left, ranked_right)}
    for lag in range(-max_lag, max_lag + 1):
        if lag < 0:
            a, b = ranked_left[-lag:], ranked_right[:lag]
        elif lag > 0:
            a, b = ranked_left[:-lag], ranked_right[lag:]
        else:
            a, b = ranked_left, ranked_right
        if len(a) >= 16:
            value = correlation(a, b)
            if abs(value) > abs(float(best["correlation"])):
                best = {"lag_seconds": lag, "correlation": value}
    return best


def telemetry_sensor_series(rows: list[dict[str, Any]]) -> dict[str, list[float]]:
    names = sorted(
        {
            f"temperature:{name}"
            for row in rows
            for name in dict(row.get("ams", {}).get("temperatures_c", {}))
        }
        | {
            f"voltage:{name}"
            for row in rows
            for name in dict(row.get("ams", {}).get("voltages_v", {}))
        }
    )
    result: dict[str, list[float]] = {}
    for name in names:
        group, channel = name.split(":", 1)
        key = "temperatures_c" if group == "temperature" else "voltages_v"
        values = []
        for row in rows:
            sample = row.get("ams", {}).get(key, {}).get(channel)
            if not isinstance(sample, dict) or sample.get("mean") is None:
                values = []
                break
            values.append(float(sample["mean"]))
        if values:
            result[name] = values
    return result


def align_telemetry_to_monitor(
    raw: dict[str, Any], rows: list[dict[str, Any]], duration_seconds: int
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Align the resident one-second records to receiver monitor second zero."""
    started_ms = int(raw.get("started_unix_ms") or 0)
    if started_ms <= 0:
        raise RuntimeError("receiver monitor result has no started_unix_ms")
    ordered = sorted(rows, key=lambda row: int(row.get("captured_at_unix_ms") or 0))
    aligned = [
        row
        for row in ordered
        if int(row.get("captured_at_unix_ms") or 0) >= started_ms
    ][:duration_seconds]
    minimum = duration_seconds - TELEMETRY_MISSING_ALLOWANCE
    if len(aligned) < minimum:
        raise RuntimeError(
            f"only {len(aligned)} telemetry seconds align after receiver start; requires {minimum}"
        )
    first_ms = int(aligned[0]["captured_at_unix_ms"])
    last_ms = int(aligned[-1]["captured_at_unix_ms"])
    return aligned, {
        "receiver_started_unix_ms": started_ms,
        "first_telemetry_unix_ms": first_ms,
        "last_telemetry_unix_ms": last_ms,
        "first_offset_ms": first_ms - started_ms,
        "record_count": len(aligned),
        "method": "first resident 1 Hz record at-or-after receiver monitor start",
    }


def monitor_power_series(raw: dict[str, Any]) -> tuple[dict[int, dict[str, Any]], dict[tuple[int, int], list[float]]]:
    targets = {int(row["target_index"]): row for row in raw["targets"]}
    grouped: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for row in raw["power_seconds"]:
        lane = int(row["lane"])
        if lane in LANES:
            grouped.setdefault((lane, int(row["target_index"])), []).append(row)
    series = {}
    for key, rows in grouped.items():
        rows.sort(key=lambda row: int(row["second"]))
        series[key] = [astronomy.mean_power_from_accumulator(row) for row in rows]
    return targets, series


def analyze_monitor(
    raw: dict[str, Any], telemetry: list[dict[str, Any]], *, duration_seconds: int, seed: int
) -> dict[str, Any]:
    targets, series = monitor_power_series(raw)
    taus = (1, 2, 4, 8, 16, 32, 64, 128) + ((256, 512) if duration_seconds == NATURAL_SECONDS else ())
    combinations = []
    for (lane, target_index), values in sorted(series.items()):
        if len(values) < duration_seconds - TELEMETRY_MISSING_ALLOWANCE:
            raise RuntimeError(f"ADC{lane} target {target_index} has only {len(values)} seconds")
        raw_stats = astronomy.integration_statistics(values, taus=taus)
        shuffled = list(values)
        random.Random(seed ^ lane << 16 ^ target_index).shuffle(shuffled)
        shuffled_stats = astronomy.integration_statistics(shuffled, taus=taus)
        rf = float(targets[target_index]["actual_rf_mhz"])
        group = "offgrid" if any(abs(rf - item) < 1e-6 for item in OFFGRID_RF_MHZ) else (
            "fixed" if any(abs(rf - item) < 1e-6 for item in FIXED_RF_MHZ) else "grid10"
        )
        combinations.append(
            {
                "lane": lane,
                "target_index": target_index,
                "rf_mhz": rf,
                "group": group,
                "seconds": len(values),
                "slope": float(raw_stats["slope"]),
                "shuffled_slope": float(shuffled_stats["slope"]),
                "slope_pass": -0.65 <= float(raw_stats["slope"]) <= -0.35,
                "lag1_correlation": correlation(values[:-1], values[1:]),
                "mean_dbfs": float(raw_stats["mean_dbfs"]),
                "curve": raw_stats["curve"],
                "shuffled_curve": shuffled_stats["curve"],
                "power_series": values,
            }
        )
    if len(combinations) != len(LANES) * len(RF_FREQUENCIES_MHZ):
        raise RuntimeError(f"monitor produced {len(combinations)} combinations, expected 36")

    aligned_telemetry, telemetry_alignment = align_telemetry_to_monitor(
        raw, telemetry, duration_seconds
    )
    sensor_series = telemetry_sensor_series(aligned_telemetry)
    correlations = []
    # The registered scientific gate and the power/thermal interpretation both
    # use the six off-grid bins.  Restrict the expensive block bootstrap and
    # +/-60 second cross-correlation to that pre-registered set; retaining it
    # for the fixed/grid diagnostic bins would multiply post-processing cost
    # without affecting any conclusion.
    for combo in (row for row in combinations if row["group"] == "offgrid"):
        values = combo["power_series"]
        for sensor, samples in sensor_series.items():
            count = min(len(values), len(samples))
            left = values[:count]
            right = samples[:count]
            raw_rho = spearman(left, right)
            diff_rho = spearman(
                [b - a for a, b in zip(left, left[1:])],
                [b - a for a, b in zip(right, right[1:])],
            )
            bootstrap = block_bootstrap_ci(
                left,
                right,
                seed=seed ^ int(hashlib.sha256(f"{combo['lane']}:{combo['rf_mhz']}:{sensor}".encode()).hexdigest()[:8], 16),
            )
            correlations.append(
                {
                    "lane": combo["lane"],
                    "rf_mhz": combo["rf_mhz"],
                    "group": combo["group"],
                    "sensor": sensor,
                    "raw_spearman": raw_rho,
                    "first_difference_spearman": diff_rho,
                    "cross_correlation": maximum_cross_correlation(left, right),
                    "bootstrap": bootstrap,
                }
            )
    adjusted = bh_adjust([float(row["bootstrap"]["p_two_sided"]) for row in correlations])
    for row, value in zip(correlations, adjusted):
        row["bh_adjusted_p"] = value
        row["significant"] = value <= 0.05

    offgrid = [row for row in combinations if row["group"] == "offgrid"]
    return {
        "combinations": combinations,
        "offgrid": summarize(offgrid),
        "grid10": summarize([row for row in combinations if row["group"] == "grid10"]),
        "fixed_960": summarize([row for row in combinations if row["group"] == "fixed"]),
        "telemetry_correlations": correlations,
        "telemetry_alignment": telemetry_alignment,
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "count": len(rows),
        "slope_pass_count": sum(int(row["slope_pass"]) for row in rows),
        "slope_pass_fraction": statistics.fmean(int(row["slope_pass"]) for row in rows),
        "median_slope": statistics.median(float(row["slope"]) for row in rows),
        "median_shuffled_slope": statistics.median(float(row["shuffled_slope"]) for row in rows),
        "median_abs_lag1": statistics.median(abs(float(row["lag1_correlation"])) for row in rows),
        "median_abs_slope_error": statistics.median(abs(float(row["slope"]) + 0.5) for row in rows),
    }


def validate_board_running(
    board: dict[str, Any], *, rate: int, mode: str, expected_dac_mask: int
) -> None:
    c34c.validate_board_status(board, rate, mode, CENTER_MHZ)
    power = board.get("rfdc", {}).get("power", {}).get("live", {})
    if int(power.get("adc_enabled_mask", -1)) != 0xF:
        raise RuntimeError(f"ADC tile state invalid: {power}")
    if int(power.get("dac_enabled_mask", -1)) != expected_dac_mask:
        raise RuntimeError(f"DAC tile state invalid: expected {expected_dac_mask:#x}; {power}")


def capture_edge(args: argparse.Namespace, run_dir: Path, edge: str, mode: str) -> dict[str, Any]:
    paths, metadata = fullband.capture_receiver_pcap(
        receiver_base=args.receiver_base,
        local_dir=run_dir / "raw" / edge,
        packets_per_block=PACKETS_PER_FLOW,
        include_time=mode == "time_spec",
    )
    return {
        **metadata,
        "paths": [str(path.resolve()) for path in paths],
        "sha256": {path.name: sha256_file(path) for path in paths},
    }


def wait_monitor(args: argparse.Namespace, duration_seconds: int) -> dict[str, Any]:
    deadline = time.monotonic() + duration_seconds + 90.0
    while time.monotonic() < deadline:
        status = fullband._http_json(
            args.receiver_base.rstrip("/") + "/api/measure/spec-stability/status"
        )
        if status.get("status") == "completed":
            return fullband._http_json(
                args.receiver_base.rstrip("/") + "/api/measure/spec-stability/result",
                timeout=240.0,
            )
        if status.get("status") == "failed":
            raise RuntimeError(f"receiver monitor failed: {status.get('error')}")
        time.sleep(2.0)
    raise RuntimeError("receiver monitor did not complete before deadline")


def execute_run(
    args: argparse.Namespace,
    *,
    row: dict[str, Any],
    duration_seconds: int,
    start_transactions: dict[str, str] | None = None,
    expected_dac_mask: int = 0xF,
) -> dict[str, Any]:
    run_dir = args.receiver_output / "runs" / row["name"]
    run_dir.mkdir(parents=True, exist_ok=False)
    evidence = {
        **row,
        "duration_seconds": duration_seconds,
        "center_mhz": CENTER_MHZ,
        "rf_frequencies_mhz": list(RF_FREQUENCIES_MHZ),
        "ok": False,
        "classification": "STAGE34C3_RUN_IN_PROGRESS",
        "errors": [],
        "started_at_unix_ms": time.time_ns() // 1_000_000,
    }
    write_json(run_dir / "result.json", evidence)
    progress_path = args.receiver_output / "current_run.json"
    write_json(
        progress_path,
        {
            "name": row["name"],
            "layer": row["layer"],
            "condition": row["condition"],
            "duration_seconds": duration_seconds,
            "status": "PREPARING",
            "started_at_unix_ms": evidence["started_at_unix_ms"],
        },
    )
    try:
        receiver_prepare(args, int(row["sample_rate_msps"]), str(row["mode"]))
        start_body: dict[str, Any] = {"expected_board_id": BOARD_ID}
        start_body.update(start_transactions or {})
        evidence["start"] = agent_post(args, "/api/v2/start", start_body)
        time.sleep(args.settle_seconds)
        evidence["thermal_warmup"] = wait_for_thermal_stability(args)
        marker = telemetry_marker(args)
        before_board = agent_get(args, "/api/v2/status")
        before_receiver = receiver_state(args)
        validate_board_running(
            before_board,
            rate=int(row["sample_rate_msps"]),
            mode=str(row["mode"]),
            expected_dac_mask=expected_dac_mask,
        )
        evidence["begin_capture"] = capture_edge(args, run_dir, "begin", str(row["mode"]))
        evidence["monitor_start"] = fullband._http_json(
            args.receiver_base.rstrip("/") + "/api/measure/spec-stability",
            method="POST",
            body={
                "duration_seconds": duration_seconds,
                "formal": True,
                "sample_rate_msps": int(row["sample_rate_msps"]),
                "center_mhz": CENTER_MHZ,
                "rf_frequencies_mhz": list(RF_FREQUENCIES_MHZ),
                "correlation_pair": [0, 2],
                "lane_mask": LANE_MASK,
                "include_time_statistics": row["mode"] == "time_spec",
            },
        )
        write_json(
            progress_path,
            {
                "name": row["name"],
                "layer": row["layer"],
                "condition": row["condition"],
                "duration_seconds": duration_seconds,
                "status": "MONITOR_RUNNING",
                "started_at_unix_ms": evidence["started_at_unix_ms"],
                "monitor_started_unix_ms": evidence["monitor_start"].get("started_unix_ms"),
            },
        )
        raw = wait_monitor(args, duration_seconds)
        write_json(run_dir / "monitor_raw.json", raw)
        telemetry = telemetry_since(args, marker)
        write_json(run_dir / "power_thermal_telemetry.json", telemetry)
        telemetry_integrity = validate_telemetry(telemetry, duration_seconds, marker=marker)
        evidence["end_capture"] = capture_edge(args, run_dir, "end", str(row["mode"]))
        after_board = agent_get(args, "/api/v2/status")
        after_receiver = receiver_state(args)
        validate_board_running(
            after_board,
            rate=int(row["sample_rate_msps"]),
            mode=str(row["mode"]),
            expected_dac_mask=expected_dac_mask,
        )
        integrity = fullband._window_integrity(
            before_board, after_board, before_receiver, after_receiver
        )
        if not integrity["ok"]:
            raise RuntimeError(f"digital integrity failed: {integrity['errors']}")
        analysis = analyze_monitor(
            raw,
            telemetry,
            duration_seconds=duration_seconds,
            seed=int(hashlib.sha256(row["name"].encode()).hexdigest()[:8], 16),
        )
        time_rows = list(raw.get("time_seconds", []))
        if row["mode"] == "time_spec" and (
            not time_rows or any(bool(item.get("clipped")) for item in time_rows)
        ):
            raise RuntimeError("TIME statistics are absent or clipped")
        evidence.update(
            {
                "ok": True,
                "classification": "STAGE34C3_RUN_COMPLETE",
                "telemetry_integrity": telemetry_integrity,
                "temperature_gate": telemetry_temperature_gate(telemetry, duration_seconds),
                "before_board": before_board,
                "after_board": after_board,
                "before_receiver": c34c.receiver_condensed(before_receiver),
                "after_receiver": c34c.receiver_condensed(after_receiver),
                "integrity": integrity,
                "analysis": analysis,
                "time_statistics": time_rows,
            }
        )
    except Exception as exc:
        evidence["errors"].append(f"{type(exc).__name__}:{exc}")
        evidence["classification"] = "STAGE34C3_RUN_OPERATIONAL_FAIL"
        raise
    finally:
        evidence["errors"].extend(stop_stream(args))
        evidence["finished_at_unix_ms"] = time.time_ns() // 1_000_000
        if evidence["errors"]:
            evidence["ok"] = False
            evidence["classification"] = "STAGE34C3_RUN_OPERATIONAL_FAIL"
        write_json(run_dir / "result.json", evidence)
        write_json(
            progress_path,
            {
                "name": row["name"],
                "layer": row["layer"],
                "condition": row["condition"],
                "duration_seconds": duration_seconds,
                "status": "COMPLETED" if evidence["ok"] else "FAILED",
                "started_at_unix_ms": evidence["started_at_unix_ms"],
                "finished_at_unix_ms": evidence["finished_at_unix_ms"],
                "errors": evidence["errors"],
            },
        )
    if not evidence["ok"]:
        raise RuntimeError(f"run {row['name']} failed: {evidence['errors']}")
    return evidence


def condition_gate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    combinations = [
        combo
        for row in rows
        for combo in row["analysis"]["combinations"]
        if combo["group"] == "offgrid"
    ]
    summary = summarize(combinations)
    per_run = [row["analysis"]["offgrid"] for row in rows]
    gates = {
        "each_run_at_least_10_of_12": all(int(item["slope_pass_count"]) >= 10 for item in per_run),
        "aggregate_at_least_29_of_36": int(summary["slope_pass_count"]) >= 29,
        "each_median_slope_in_range": all(-0.65 <= float(item["median_slope"]) <= -0.35 for item in per_run),
        "median_abs_lag1_le_0p10": float(summary["median_abs_lag1"]) <= 0.10,
        "raw_shuffled_delta_le_0p10": abs(float(summary["median_slope"]) - float(summary["median_shuffled_slope"])) <= 0.10,
    }
    return {"pass": all(gates.values()), "gates": gates, "summary": summary}


def reversible_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by = {
        condition: [row for row in rows if row["condition"] == condition]
        for condition in ("A1", "B", "A2")
    }
    metrics = {condition: condition_gate(selected) for condition, selected in by.items()}
    a1 = metrics["A1"]["summary"]
    b = metrics["B"]["summary"]
    a2 = metrics["A2"]["summary"]
    pass_delta = float(b["slope_pass_fraction"]) - float(a1["slope_pass_fraction"])
    slope_delta = float(a1["median_abs_slope_error"]) - float(b["median_abs_slope_error"])
    lag_delta = float(a1["median_abs_lag1"]) - float(b["median_abs_lag1"])
    gates = {
        "a1_a2_two_of_three_consistent": sum(
            abs(float(left["analysis"]["offgrid"]["median_slope"]) - float(right["analysis"]["offgrid"]["median_slope"])) <= 0.10
            for left, right in zip(by["A1"], by["A2"])
        ) >= 2,
        "b_absolute_gate": bool(metrics["B"]["pass"]),
        "pass_fraction_change_ge_0p50": abs(pass_delta) >= 0.50,
        "slope_error_change_ge_0p12": abs(slope_delta) >= 0.12,
        "lag_change_ge_0p10": abs(lag_delta) >= 0.10,
        "a2_returns_to_a1_slope": abs(float(a2["median_slope"]) - float(a1["median_slope"])) <= 0.10,
        "a2_returns_to_a1_lag": abs(float(a2["median_abs_lag1"]) - float(a1["median_abs_lag1"])) <= 0.10,
    }
    return {
        "causal": all(gates.values()),
        "gates": gates,
        "conditions": metrics,
        "deltas_b_minus_a1": {
            "slope_pass_fraction": pass_delta,
            "median_abs_slope_error_improvement": slope_delta,
            "median_abs_lag1_improvement": lag_delta,
        },
    }


def repeated_direction_contributor(rows: list[dict[str, Any]]) -> bool:
    by_repeat: dict[int, dict[str, float]] = {}
    for row in rows:
        by_repeat.setdefault(int(row["repeat"]), {})[row["condition"]] = float(
            row["analysis"]["offgrid"]["median_abs_slope_error"]
        )
    changes = [value["A1"] - value["B"] for value in by_repeat.values() if "A1" in value and "B" in value]
    if len(changes) < 3:
        return False
    direction = 1 if statistics.median(changes) >= 0 else -1
    return sum(1 for value in changes if value * direction > 0) >= 2 and abs(statistics.median(changes)) >= 0.05


def correlation_classification(runs: list[dict[str, Any]]) -> dict[str, Any] | None:
    by_sensor: dict[str, list[tuple[str, float, bool]]] = {}
    for run in runs:
        per_sensor: dict[str, list[dict[str, Any]]] = {}
        for row in run.get("analysis", {}).get("telemetry_correlations", []):
            if row["group"] == "offgrid":
                per_sensor.setdefault(row["sensor"], []).append(row)
        for sensor, rows in per_sensor.items():
            rho = statistics.median(float(row["raw_spearman"]) for row in rows)
            significant = sum(bool(row["significant"]) for row in rows) >= max(1, len(rows) // 2)
            by_sensor.setdefault(sensor, []).append((run["name"], rho, significant))
    candidates = []
    for sensor, rows in by_sensor.items():
        significant = [row for row in rows if row[2]]
        if len(significant) < 4:
            continue
        median_rho = statistics.median(row[1] for row in significant)
        direction = 1 if median_rho >= 0 else -1
        consistent = sum(1 for row in significant if row[1] * direction > 0)
        if consistent >= 4 and abs(median_rho) >= 0.35:
            candidates.append(
                {
                    "sensor": sensor,
                    "independent_run_count": len(significant),
                    "direction_consistent_count": consistent,
                    "median_rho": median_rho,
                    "runs": significant,
                }
            )
    return max(candidates, key=lambda row: abs(row["median_rho"])) if candidates else None


def classify(
    runs: list[dict[str, Any]], interventions: dict[str, Any] | None = None
) -> dict[str, Any]:
    output_rows = [row for row in runs if row["layer"] == "output_load"]
    output = reversible_metrics(output_rows)
    dac_qualified = bool((interventions or {}).get("dac_tile", {}).get("qualified", True))
    dac_rates = (
        {
            str(rate): reversible_metrics(
                [row for row in runs if row["layer"] == "dac_tile" and int(row["sample_rate_msps"]) == rate]
            )
            for rate in (160, 320)
        }
        if dac_qualified
        else {
            "classification": "INTERVENTION_UNQUALIFIED",
            "reason": (interventions or {}).get("dac_tile", {}).get("reason"),
        }
    )
    baselines = [row for row in runs if row["condition"] in ("A1", "OBSERVE")]
    baseline_reproduced = sum(not row["analysis"]["offgrid"]["slope_pass_fraction"] >= 10 / 12 for row in baselines) >= max(2, len(baselines) // 2)
    if not baseline_reproduced:
        primary = "INCONCLUSIVE_BASELINE_NOT_REPRODUCED"
    elif output["causal"]:
        direction = "IMPROVEMENT" if output["deltas_b_minus_a1"]["median_abs_slope_error_improvement"] > 0 else "WORSENING"
        primary = f"OUTPUT_LOAD_STATE_CAUSAL_{direction}"
    elif dac_qualified and all(row["causal"] for row in dac_rates.values()):
        improvement = statistics.median(
            row["deltas_b_minus_a1"]["median_abs_slope_error_improvement"]
            for row in dac_rates.values()
        )
        primary = "DAC_TILE_STATE_CAUSAL_RECOVERY" if improvement > 0 else "DAC_TILE_STATE_CAUSAL_WORSENING"
    elif repeated_direction_contributor(output_rows):
        primary = "OUTPUT_LOAD_STATE_CONTRIBUTOR"
    elif dac_qualified and any(
        repeated_direction_contributor(
            [row for row in runs if row["layer"] == "dac_tile" and int(row["sample_rate_msps"]) == rate]
        )
        for rate in (160, 320)
    ):
        primary = "DAC_TILE_STATE_CONTRIBUTOR"
    else:
        correlated = correlation_classification(runs)
        if correlated:
            primary = "POWER_THERMAL_CORRELATED_ONLY"
        elif dac_qualified:
            primary = "POWER_LOAD_NOT_CAUSAL_UNDER_SHARED_50OHM"
        else:
            primary = "OUTPUT_LOAD_NOT_CAUSAL_DAC_TILE_INTERVENTION_UNQUALIFIED"
    return {
        "primary": primary,
        "output_load": output,
        "dac_tile": dac_rates,
        "power_thermal_correlation": correlation_classification(runs),
        "baseline_reproduced": baseline_reproduced,
        "mandatory_pending": [
            "ADC_ANALOG_RAIL_RIPPLE_QUALIFICATION_PENDING",
            "THERMAL_CAUSALITY_PENDING_ACTIVE_CONTROL",
        ],
    }


def quick_monitor(
    args: argparse.Namespace,
    *,
    rate: int,
    mode: str,
    seconds: int,
    transactions: dict[str, str] | None = None,
    expected_dac_mask: int = 0xF,
) -> dict[str, Any]:
    receiver_prepare(args, rate, mode)
    start = agent_post(args, "/api/v2/start", {"expected_board_id": BOARD_ID, **(transactions or {})})
    try:
        time.sleep(args.settle_seconds)
        before_board = agent_get(args, "/api/v2/status")
        before_receiver = receiver_state(args)
        validate_board_running(
            before_board,
            rate=rate,
            mode=mode,
            expected_dac_mask=expected_dac_mask,
        )
        started = fullband._http_json(
            args.receiver_base.rstrip("/") + "/api/measure/spec-stability",
            method="POST",
            body={
                "duration_seconds": seconds,
                "formal": False,
                "sample_rate_msps": rate,
                "center_mhz": CENTER_MHZ,
                "rf_frequencies_mhz": list(RF_FREQUENCIES_MHZ),
                "correlation_pair": [0, 2],
                "lane_mask": LANE_MASK,
                "include_time_statistics": mode == "time_spec",
            },
        )
        result = wait_monitor(args, seconds)
        after_board = agent_get(args, "/api/v2/status")
        after_receiver = receiver_state(args)
        integrity = fullband._window_integrity(before_board, after_board, before_receiver, after_receiver)
        if not integrity["ok"]:
            raise RuntimeError(f"quick monitor integrity failed: {integrity['errors']}")
        return {
            "start": start,
            "monitor_start": started,
            "result": result,
            "integrity": integrity,
            "before_receiver": c34c.receiver_condensed(before_receiver),
            "after_receiver": c34c.receiver_condensed(after_receiver),
        }
    finally:
        errors = stop_stream(args)
        if errors:
            raise RuntimeError(f"quick monitor cleanup failed: {errors}")


def preflight(
    args: argparse.Namespace, template: dict[str, Any], evidence_root: Path
) -> dict[str, Any]:
    result: dict[str, Any] = {"ok": False, "interventions": {}, "errors": []}
    result["configure"] = fresh_configure(args, template, 320)
    board = agent_get(args, "/api/v2/status")
    if (
        str(board.get("core_version", "")).lower() != CORE_VERSION
        or int(board.get("channelizer", {}).get("nchan", 0)) != 4096
        or int(board.get("channelizer", {}).get("taps", 0)) != 8
        or str(board.get("channelizer", {}).get("coefficient_id", "")).lower() != PFB_PROFILE_ID
        or board.get("clock", {}).get("profile_id") != "160m_10m_cont_manual_clkin2"
        or int(board.get("clock", {}).get("pll1_lock", 0)) != 1
        or int(board.get("clock", {}).get("pll2_lock", 0)) != 1
    ):
        raise RuntimeError(f"identity/clock/PFB preflight failed: {board}")
    result["identity"] = board
    marker = telemetry_marker(args)
    time.sleep(PRECHECK_SECONDS)
    rows = telemetry_since(args, marker)
    result["telemetry_120s"] = validate_telemetry(rows, PRECHECK_SECONDS, marker=marker)
    write_json(evidence_root / "preflight_telemetry_120s.json", rows)

    # The existing receiver ring remains the only packet socket.  Compare a
    # 120-second no-monitor interval to an otherwise identical monitor interval.
    result["collector_ab"] = []
    for rate, mode in ((320, "spec_only"), (160, "time_spec")):
        fresh_configure(args, template, rate, mode)
        receiver_prepare(args, rate, mode)
        agent_post(args, "/api/v2/start", {"expected_board_id": BOARD_ID})
        time.sleep(args.settle_seconds)
        before_board = agent_get(args, "/api/v2/status")
        before_receiver = receiver_state(args)
        validate_board_running(before_board, rate=rate, mode=mode, expected_dac_mask=0xF)
        time.sleep(PRECHECK_SECONDS)
        after_board = agent_get(args, "/api/v2/status")
        after_receiver = receiver_state(args)
        off_integrity = fullband._window_integrity(before_board, after_board, before_receiver, after_receiver)
        errors = stop_stream(args)
        if errors or not off_integrity["ok"]:
            raise RuntimeError(f"collector-off preflight failed: {errors}; {off_integrity}")
        fresh_configure(args, template, rate, mode)
        on = quick_monitor(args, rate=rate, mode=mode, seconds=PRECHECK_SECONDS)
        off_pps = float(after_receiver.get("stats", {}).get("packets_per_sec", 0.0) or 0.0)
        on_pps = float(
            on.get("after_receiver", {}).get("stats", {}).get("packets_per_sec", 0.0)
            or 0.0
        )
        if off_pps <= 0.0 or on_pps <= 0.0:
            raise RuntimeError(
                f"collector A/B packet rate missing at {rate} MS/s {mode}: "
                f"off={off_pps}, on={on_pps}"
            )
        relative_delta = abs(on_pps - off_pps) / off_pps
        if relative_delta > 0.05:
            raise RuntimeError(
                f"collector changes packet throughput at {rate} MS/s {mode}: "
                f"off={off_pps:.3f} pps, on={on_pps:.3f} pps, "
                f"relative_delta={relative_delta:.6f}"
            )
        result["collector_ab"].append(
            {
                "rate": rate,
                "mode": mode,
                "off": off_integrity,
                "on": on,
                "throughput": {
                    "collector_off_packets_per_second": off_pps,
                    "collector_on_packets_per_second": on_pps,
                    "relative_delta": relative_delta,
                    "maximum_allowed_relative_delta": 0.05,
                    "pass": True,
                },
            }
        )

    # Reversible output load quick screen.
    fresh_configure(args, template, 160, "spec_only")
    quick_a1 = quick_monitor(args, rate=160, mode="spec_only", seconds=QUICK_SECONDS)
    receiver_prepare(args, 160, "time_spec")
    changed = agent_post(
        args,
        "/api/v2/diagnostics/output-load",
        {"expected_board_id": BOARD_ID, "receiver_stream_accepting": False, "mode": "time_spec"},
    )
    quick_b = quick_monitor(
        args,
        rate=160,
        mode="time_spec",
        seconds=QUICK_SECONDS,
        transactions={"output_load_transaction_id": changed["output_load_transaction_id"]},
    )
    restored = agent_post(
        args,
        "/api/v2/diagnostics/output-load/restore",
        {"expected_board_id": BOARD_ID, "receiver_stream_accepting": False},
    )
    quick_a2 = quick_monitor(args, rate=160, mode="spec_only", seconds=QUICK_SECONDS)
    result["interventions"]["output_load"] = {"qualified": True, "A1": quick_a1, "change": changed, "B": quick_b, "restore": restored, "A2": quick_a2}

    # Reversible DAC shutdown quick screen.  A2 restoration is always a full
    # production CONFIGURE/MTS performed by the Board Agent endpoint.
    frozen_unqualified = getattr(args, "dac_intervention_unqualified_evidence", None)
    if frozen_unqualified is not None:
        frozen = json.loads(Path(frozen_unqualified).read_text())
        if (
            frozen.get("classification") != "INTERVENTION_UNQUALIFIED"
            or frozen.get("intervention") != "XRFdc_Shutdown(Type=DAC, Tile_Id=-1)"
            or frozen.get("core_version") != CORE_VERSION
            or frozen.get("bitstream_sha256") != BITSTREAM_SHA256
            or not frozen.get("full_configure_mts_recovery_ok")
        ):
            raise RuntimeError(f"invalid frozen DAC intervention evidence: {frozen}")
        live = agent_get(args, "/api/v2/rfdc/power")
        tile = live.get("live", {})
        if int(tile.get("adc_enabled_mask", 0)) != 0xF or int(tile.get("dac_enabled_mask", 0)) != 0xF:
            raise RuntimeError(f"frozen DAC intervention evidence restore no longer holds: {tile}")
        result["interventions"]["dac_tile"] = {
            "qualified": False,
            "classification": "INTERVENTION_UNQUALIFIED",
            "reason": frozen.get("failure"),
            "evidence_path": str(Path(frozen_unqualified).resolve()),
            "evidence_sha256": sha256_file(Path(frozen_unqualified)),
            "restored_live": live,
        }
    else:
        fresh_configure(args, template, 320, "spec_only")
        quick_a1 = quick_monitor(args, rate=320, mode="spec_only", seconds=QUICK_SECONDS)
        try:
            shutdown = agent_post(
                args,
                "/api/v2/rfdc/power/dac-shutdown",
                {"expected_board_id": BOARD_ID, "receiver_stream_accepting": False},
            )
            quick_b = quick_monitor(
                args,
                rate=320,
                mode="spec_only",
                seconds=QUICK_SECONDS,
                transactions={"rfdc_power_transaction_id": shutdown["rfdc_power_transaction_id"]},
                expected_dac_mask=0,
            )
            restored = agent_post(
                args,
                "/api/v2/rfdc/power/restore",
                {"expected_board_id": BOARD_ID, "receiver_stream_accepting": False},
                timeout=300.0,
            )
            quick_a2 = quick_monitor(args, rate=320, mode="spec_only", seconds=QUICK_SECONDS)
            result["interventions"]["dac_tile"] = {"qualified": True, "classification": "INTERVENTION_QUALIFIED", "A1": quick_a1, "shutdown": shutdown, "B": quick_b, "restore": restored, "A2": quick_a2}
        except Exception as exc:
            recovery_errors = stop_stream(args)
            try:
                fresh_configure(args, template, 320, "spec_only")
            except Exception as cleanup:
                recovery_errors.append(f"FULL_CONFIGURE_MTS:{type(cleanup).__name__}:{cleanup}")
            recovery_errors.extend(stop_stream(args))
            if recovery_errors:
                raise RuntimeError(
                    f"DAC tile intervention failed and recovery was not clean: {exc}; {recovery_errors}"
                ) from exc
            live = agent_get(args, "/api/v2/rfdc/power")
            tile = live.get("live", {})
            if int(tile.get("adc_enabled_mask", 0)) != 0xF or int(tile.get("dac_enabled_mask", 0)) != 0xF:
                raise RuntimeError(
                    f"DAC tile intervention failed and full CONFIGURE/MTS did not restore all tiles: {tile}"
                ) from exc
            result["interventions"]["dac_tile"] = {
                "qualified": False,
                "classification": "INTERVENTION_UNQUALIFIED",
                "reason": f"{type(exc).__name__}:{exc}",
                "recovery_errors": [],
                "restored_live": live,
                "A1": quick_a1,
            }
    result["ok"] = True
    return result


def write_summary_csv(path: Path, runs: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=("name", "layer", "condition", "sample_rate_msps", "mode", "lane", "rf_mhz", "group", "slope", "shuffled_slope", "lag1_correlation", "mean_dbfs", "slope_pass"),
        )
        writer.writeheader()
        for run in runs:
            for row in run.get("analysis", {}).get("combinations", []):
                writer.writerow({
                    "name": run["name"], "layer": run["layer"], "condition": run["condition"],
                    "sample_rate_msps": run["sample_rate_msps"], "mode": run["mode"],
                    **{key: row[key] for key in ("lane", "rf_mhz", "group", "slope", "shuffled_slope", "lag1_correlation", "mean_dbfs", "slope_pass")},
                })


def _font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    for path in (
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc") if bold else Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Medium.ttc"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf") if bold else Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ):
        if path.is_file():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def _polyline(
    draw: ImageDraw.ImageDraw,
    values: list[float],
    box: tuple[int, int, int, int],
    *,
    color: str,
    low: float | None = None,
    high: float | None = None,
    width: int = 2,
) -> None:
    if len(values) < 2:
        return
    left, top, right, bottom = box
    low = min(values) if low is None else low
    high = max(values) if high is None else high
    if not math.isfinite(low) or not math.isfinite(high) or high <= low:
        return
    points = [
        (
            left + round(index * (right - left) / max(1, len(values) - 1)),
            bottom - round((value - low) / (high - low) * (bottom - top)),
        )
        for index, value in enumerate(values)
    ]
    draw.line(points, fill=color, width=width)


def _median_fractional_power(run: dict[str, Any], lane: int) -> list[float]:
    rows = [
        row
        for row in run.get("analysis", {}).get("combinations", [])
        if int(row["lane"]) == lane and row["group"] == "offgrid"
    ]
    if not rows:
        return []
    count = min(len(row["power_series"]) for row in rows)
    normalized = [
        [100.0 * (float(value) / statistics.fmean(row["power_series"]) - 1.0) for value in row["power_series"][:count]]
        for row in rows
    ]
    return [statistics.median(values) for values in zip(*normalized)]


def _draw_intervention_timelines(
    plot_root: Path, layer: str, selected: list[dict[str, Any]]
) -> Path | None:
    if not selected:
        return None
    repeats = sorted({int(row["repeat"]) for row in selected})
    image = Image.new("RGB", (1900, 360 + 310 * len(repeats)), "#f8fafc")
    draw = ImageDraw.Draw(image)
    draw.text((55, 25), f"Stage 34c-3 {layer}：A1 / B / A2 功率时间线", fill="#0f172a", font=_font(34, True))
    draw.text((55, 75), "每个条件内，以各离栅格频点自身均值归一化；蓝=ADC0，红=ADC2", fill="#475569", font=_font(21))
    colors = {0: "#2563eb", 2: "#dc2626"}
    for panel, repeat in enumerate(repeats):
        rows = [row for row in selected if int(row["repeat"]) == repeat]
        rows.sort(key=lambda row: ("A1", "B", "A2").index(row["condition"]))
        left, top, right, bottom = 115, 145 + panel * 310, 1815, 385 + panel * 310
        draw.rectangle((left, top, right, bottom), outline="#94a3b8", width=2)
        all_values = [value for row in rows for lane in LANES for value in _median_fractional_power(row, lane)]
        limit = max(0.05, sorted(abs(value) for value in all_values)[round(0.995 * (len(all_values) - 1))]) if all_values else 1.0
        segment_width = (right - left) / 3.0
        zero_y = (top + bottom) // 2
        draw.line((left, zero_y, right, zero_y), fill="#cbd5e1", width=1)
        for segment, row in enumerate(rows):
            box = (
                round(left + segment * segment_width),
                top,
                round(left + (segment + 1) * segment_width),
                bottom,
            )
            if segment:
                draw.line((box[0], top, box[0], bottom), fill="#94a3b8", width=1)
            for lane in LANES:
                _polyline(draw, _median_fractional_power(row, lane), box, color=colors[lane], low=-limit, high=limit, width=2)
            draw.text((box[0] + 12, top + 10), f"{row['condition']}  {row['mode']}", fill="#334155", font=_font(18, True))
        draw.text((20, top + 6), f"r{repeat}", fill="#0f172a", font=_font(20, True))
        draw.text((20, zero_y - 10), "0%", fill="#64748b", font=_font(16))
        draw.text((right - 130, bottom + 8), f"±{limit:.3f}%", fill="#64748b", font=_font(16))
    path = plot_root / f"{layer}_a1_b_a2_power_timelines.png"
    image.save(path, optimize=True)
    return path


def _draw_correlation_heatmap(plot_root: Path, runs: list[dict[str, Any]]) -> Path | None:
    rows = [
        row
        for run in runs
        for row in run.get("analysis", {}).get("telemetry_correlations", [])
        if row.get("group") == "offgrid"
    ]
    if not rows:
        return None
    sensors = sorted({str(row["sensor"]) for row in rows})
    columns = [(lane, rf) for lane in LANES for rf in OFFGRID_RF_MHZ]
    image = Image.new("RGB", (2150, 190 + 42 * len(sensors)), "#f8fafc")
    draw = ImageDraw.Draw(image)
    draw.text((45, 22), "Stage 34c-3：AMS 与科学功率的 Spearman 相关热图", fill="#0f172a", font=_font(32, True))
    draw.text((45, 68), "显示各正式 run 的中位原始相关；仅表示相关，不表示供电或温度因果", fill="#475569", font=_font(20))
    x0, y0, cell_w, cell_h = 560, 145, 125, 42
    for column, (lane, rf) in enumerate(columns):
        draw.text((x0 + column * cell_w + 8, 112), f"A{lane}\n{rf:g}", fill="#334155", font=_font(15))
    for row_index, sensor in enumerate(sensors):
        y = y0 + row_index * cell_h
        draw.text((35, y + 8), sensor, fill="#334155", font=_font(17))
        for column, (lane, rf) in enumerate(columns):
            values = [
                float(item["raw_spearman"])
                for item in rows
                if int(item["lane"]) == lane and abs(float(item["rf_mhz"]) - rf) < 1e-6 and item["sensor"] == sensor
            ]
            rho = statistics.median(values) if values else 0.0
            strength = min(1.0, abs(rho))
            if rho >= 0:
                color = (255, round(255 - 145 * strength), round(255 - 170 * strength))
            else:
                color = (round(255 - 170 * strength), round(255 - 130 * strength), 255)
            x = x0 + column * cell_w
            draw.rectangle((x, y, x + cell_w - 2, y + cell_h - 2), fill=color, outline="#e2e8f0")
            draw.text((x + 30, y + 9), f"{rho:+.2f}", fill="#172554", font=_font(15))
    path = plot_root / "sensor_adc_rf_correlation_heatmap.png"
    image.save(path, optimize=True)
    return path


def _telemetry_channel(rows: list[dict[str, Any]], group: str, name: str) -> list[float]:
    key = "temperatures_c" if group == "temperature" else "voltages_v"
    return [
        float(row.get("ams", {}).get(key, {}).get(name, {}).get("mean"))
        for row in rows
        if row.get("ams", {}).get(key, {}).get(name, {}).get("mean") is not None
    ]


def _ocb1_k1_magnitude(rows: list[dict[str, Any]], adc: int = 0) -> list[float]:
    values: list[float] = []
    for row in rows:
        dft = row.get("calibration", {}).get("ocb1_dft", {}).get(str(adc), [])
        k1 = next((item for item in dft if int(item.get("k", -1)) == 1), None)
        if k1 is not None:
            values.append(float(k1["magnitude"]))
    return values


def _draw_environment_timeline(plot_root: Path, root: Path, natural: list[dict[str, Any]]) -> Path | None:
    if not natural:
        return None
    image = Image.new("RGB", (1900, 170 + 520 * len(natural)), "#f8fafc")
    draw = ImageDraw.Draw(image)
    draw.text((45, 22), "Stage 34c-3：60 分钟功率、温度、电压与 OCB1 共时间轴", fill="#0f172a", font=_font(31, True))
    draw.text((45, 68), "曲线均减去自身中位数；用于找慢趋势，不用于验收模拟电源纹波", fill="#475569", font=_font(20))
    for outer, run in enumerate(natural):
        telemetry_path = root / "runs" / run["name"] / "power_thermal_telemetry.json"
        telemetry = json.loads(telemetry_path.read_text()) if telemetry_path.is_file() else []
        metrics = [
            ("ADC0/2 离栅格中位功率 / %", [statistics.median(v) for v in zip(_median_fractional_power(run, 0), _median_fractional_power(run, 2))], "#7c3aed"),
            ("PL 温度变化 / °C", _telemetry_channel(telemetry, "temperature", "pl_temp"), "#dc2626"),
            ("VCCINT 变化 / mV", [1000.0 * value for value in _telemetry_channel(telemetry, "voltage", "vccint")], "#2563eb"),
            ("ADC0 OCB1 DFT k1 幅度变化", _ocb1_k1_magnitude(telemetry), "#16a34a"),
        ]
        draw.text((45, 120 + outer * 520), f"{run['sample_rate_msps']} MS/s", fill="#0f172a", font=_font(22, True))
        for panel, (label, values, color) in enumerate(metrics):
            left, top, right, bottom = 430, 115 + outer * 520 + panel * 118, 1820, 205 + outer * 520 + panel * 118
            draw.rectangle((left, top, right, bottom), outline="#cbd5e1", width=1)
            if values:
                center = statistics.median(values)
                centered = [value - center for value in values]
                limit = max(1e-12, max(abs(value) for value in centered))
                _polyline(draw, centered, (left, top, right, bottom), color=color, low=-limit, high=limit, width=2)
                draw.text((right - 205, top + 7), f"range ±{limit:.4g}", fill="#64748b", font=_font(15))
            draw.text((45, top + 25), label, fill="#334155", font=_font(17))
    path = plot_root / "natural_power_ams_ocb1_timeline.png"
    image.save(path, optimize=True)
    return path


def write_plots(root: Path, runs: list[dict[str, Any]], classification: dict[str, Any]) -> list[str]:
    plot_root = root / "plots"
    plot_root.mkdir(parents=True, exist_ok=True)
    paths = []
    for layer in ("output_load", "dac_tile"):
        selected = [row for row in runs if row["layer"] == layer]
        timeline = _draw_intervention_timelines(plot_root, layer, selected)
        if timeline is not None:
            paths.append(str(timeline.resolve()))
        if not selected:
            if layer == "dac_tile":
                image = Image.new("RGB", (1700, 500), "#f8fafc")
                draw = ImageDraw.Draw(image)
                draw.text((55, 45), "DAC tile 干预：INTERVENTION_UNQUALIFIED", fill="#b91c1c", font=_font(34, True))
                draw.text((55, 115), "XRFdc_Shutdown(-1) 未能到达可验证的安全停止状态；恢复依赖完整 CONFIGURE/MTS。", fill="#334155", font=_font(22))
                draw.text((55, 165), "因此没有采集 DAC tile A1/B/A2 数据，也不会把这一层误判为无因果。", fill="#334155", font=_font(22))
                draw.text((55, 235), "已继续执行相互独立、实机验证安全的数字输出负载层与自然温度/电压观察层。", fill="#334155", font=_font(22))
                path = plot_root / "dac_tile_intervention_unqualified.png"
                image.save(path, optimize=True)
                paths.append(str(path.resolve()))
            continue
        image = Image.new("RGB", (1800, 1050), "#f8fafc")
        draw = ImageDraw.Draw(image)
        draw.text((55, 30), f"Stage 34c-3 {layer} A1/B/A2", fill="#0f172a", font=_font(36, True))
        draw.text((55, 82), "ADC0/ADC2 off-grid: integration slope and |lag-1|", fill="#475569", font=_font(21))
        conditions = ("A1", "B", "A2")
        colors = {"A1": "#2563eb", "B": "#dc2626", "A2": "#16a34a"}
        for panel, metric, low, high, target in ((0, "median_slope", -0.75, 0.05, -0.5), (1, "median_abs_lag1", 0.0, 0.8, 0.1)):
            left, top, right, bottom = 120, 155 + panel * 430, 1720, 500 + panel * 430
            draw.rectangle((left, top, right, bottom), outline="#94a3b8", width=2)
            target_y = bottom - int((target - low) / (high - low) * (bottom - top))
            draw.line((left, target_y, right, target_y), fill="#166534", width=2)
            for index, condition in enumerate(conditions):
                rows = [row for row in selected if row["condition"] == condition]
                values = [float(row["analysis"]["offgrid"][metric]) for row in rows]
                if not values:
                    continue
                x = left + (index + 1) * (right - left) // 4
                y = bottom - int((statistics.median(values) - low) / (high - low) * (bottom - top))
                draw.ellipse((x - 10, y - 10, x + 10, y + 10), fill=colors[condition])
                draw.text((x - 25, bottom + 12), condition, fill=colors[condition], font=_font(22, True))
                draw.text((x + 18, y - 14), f"{statistics.median(values):+.3f}", fill="#334155", font=_font(18))
            draw.text((20, (top + bottom) // 2), "Slope" if panel == 0 else "|lag-1|", fill="#334155", font=_font(20))
        path = plot_root / f"{layer}_a1_b_a2_summary.png"
        image.save(path, optimize=True)
        paths.append(str(path.resolve()))

    natural = [row for row in runs if row["layer"] == "natural"]
    if natural:
        image = Image.new("RGB", (1800, 950), "#f8fafc")
        draw = ImageDraw.Draw(image)
        draw.text((55, 25), "Stage 34c-3 60-minute integration and Allan context", fill="#0f172a", font=_font(34, True))
        for panel, run in enumerate(natural):
            left, top, right, bottom = 120, 130 + panel * 390, 1720, 440 + panel * 390
            draw.rectangle((left, top, right, bottom), outline="#94a3b8", width=2)
            combos = [row for row in run["analysis"]["combinations"] if row["group"] == "offgrid"]
            for index, combo in enumerate(combos):
                points = []
                for sample in combo["curve"]:
                    scatter = sample.get("fractional_stddev")
                    if scatter is None:
                        continue
                    x = left + int(math.log2(sample["tau_seconds"]) / 9 * (right - left))
                    y = bottom - int((math.log10(max(scatter, 1e-8)) + 5) / 4 * (bottom - top))
                    points.append((x, max(top, min(bottom, y))))
                if len(points) > 1:
                    draw.line(points, fill=("#2563eb" if combo["lane"] == 0 else "#dc2626"), width=1)
                allan_points = []
                for sample in combo["curve"]:
                    allan = sample.get("allan_deviation")
                    if allan is None:
                        continue
                    x = left + int(math.log2(sample["tau_seconds"]) / 9 * (right - left))
                    y = bottom - int((math.log10(max(allan, 1e-8)) + 5) / 4 * (bottom - top))
                    allan_points.append((x, max(top, min(bottom, y))))
                for a, b in zip(allan_points[::2], allan_points[1::2]):
                    draw.line((a, b), fill=("#60a5fa" if combo["lane"] == 0 else "#f87171"), width=1)
            draw.text((left + 10, top + 10), f"{run['sample_rate_msps']} MS/s", fill="#0f172a", font=_font(21, True))
        path = plot_root / "natural_60min_integration_allan.png"
        image.save(path, optimize=True)
        paths.append(str(path.resolve()))

    heatmap = _draw_correlation_heatmap(plot_root, runs)
    if heatmap is not None:
        paths.append(str(heatmap.resolve()))
    environment = _draw_environment_timeline(plot_root, root, natural)
    if environment is not None:
        paths.append(str(environment.resolve()))

    write_json(plot_root / "classification.json", classification)
    return paths


def pcap_manifest(root: Path) -> dict[str, Any]:
    pcaps = sorted(root.rglob("*.pcap"))
    path = root / "pcap_manifest.sha256"
    path.write_text("".join(f"{sha256_file(item)}  {item.relative_to(root)}\n" for item in pcaps))
    return {"path": str(path.resolve()), "sha256": sha256_file(path), "pcap_count": len(pcaps)}


def safe_finalize(
    args: argparse.Namespace,
    template: dict[str, Any],
    original_board: dict[str, Any] | None,
    original_receiver: dict[str, Any] | None,
) -> list[str]:
    errors = stop_stream(args)
    try:
        power = agent_get(args, "/api/v2/rfdc/power")
        if power.get("state") != "NORMAL":
            agent_post(args, "/api/v2/rfdc/power/restore", {"expected_board_id": BOARD_ID, "receiver_stream_accepting": False}, timeout=300.0)
    except Exception as exc:
        errors.append(f"RFDC_POWER_RESTORE:{type(exc).__name__}:{exc}")
    try:
        output = agent_get(args, "/api/v2/diagnostics/output-load")
        if output.get("state") != "PRODUCTION":
            agent_post(args, "/api/v2/diagnostics/output-load/restore", {"expected_board_id": BOARD_ID, "receiver_stream_accepting": False})
    except Exception as exc:
        errors.append(f"OUTPUT_LOAD_RESTORE:{type(exc).__name__}:{exc}")
    try:
        profile = (original_board or {}).get("profile", {})
        fresh_configure(
            args,
            template,
            int(profile.get("sample_rate_msps") or 160),
            str(profile.get("mode") or "spec_only"),
        )
    except Exception as exc:
        errors.append(f"BOARD_PROFILE_RESTORE:{type(exc).__name__}:{exc}")
    if original_receiver is not None and isinstance(original_receiver.get("config"), dict):
        try:
            fullband._http_json(args.receiver_base.rstrip("/") + "/api/config", method="POST", body=original_receiver["config"])
        except Exception as exc:
            errors.append(f"RECEIVER_PROFILE_RESTORE:{type(exc).__name__}:{exc}")
    errors.extend(stop_stream(args))
    try:
        board = agent_get(args, "/api/v2/status")
        receiver = receiver_state(args)
        power = board.get("rfdc", {}).get("power", {}).get("live", {})
        if board.get("streaming") or board.get("pipeline", {}).get("stream_accepting"):
            raise RuntimeError("board remains streaming")
        if float(receiver.get("stats", {}).get("packets_per_sec", 0.0) or 0.0) > 1.0:
            raise RuntimeError("receiver remains active")
        if int(board.get("dac", {}).get("enable_mask", -1)) != 0:
            raise RuntimeError("DAC mask is not zero")
        if int(power.get("adc_enabled_mask", 0)) != 0xF or int(power.get("dac_enabled_mask", 0)) != 0xF:
            raise RuntimeError(f"RFDC tiles not all running: {power}")
        if int(board.get("rfdc", {}).get("calibration", {}).get("frozen_adc_mask", -1)) != 0:
            raise RuntimeError("freeze mask is not zero")
        ocb1 = board.get("rfdc", {}).get("ocb1", {})
        if int(ocb1.get("ocb1_override_adc_mask", -1)) != 0 or ocb1.get("ocb1_override_state") != "DYNAMIC":
            raise RuntimeError(f"OCB1 final state invalid: {ocb1}")
        if board.get("clock", {}).get("profile_id") != "160m_10m_cont_manual_clkin2" or int(board.get("clock", {}).get("pll1_lock", 0)) != 1 or int(board.get("clock", {}).get("pll2_lock", 0)) != 1:
            raise RuntimeError(f"production clock final state invalid: {board.get('clock')}")
    except Exception as exc:
        errors.append(f"FINAL_READBACK:{type(exc).__name__}:{exc}")
    return errors


def natural_resume_rows(state: dict[str, Any], evidence_root: Path) -> list[dict[str, Any]]:
    """Return only the missing natural-observation rows for a safe campaign resume.

    A resume is deliberately narrow: all nine output-load runs must already be
    complete and no DAC-tile run may be present when that intervention was
    frozen as unqualified.  Failed run directories are never overwritten; the
    next retry receives a monotonically increasing suffix.
    """
    runs = list(state.get("runs", []))
    output = [row for row in runs if row.get("layer") == "output_load"]
    expected_output = {row["name"] for row in output_load_plan()}
    if len(output) != 9 or {row.get("name") for row in output} != expected_output:
        raise RuntimeError("resume requires the complete nine-run output-load layer")
    if any(not row.get("ok") for row in output):
        raise RuntimeError("resume refuses an unsuccessful output-load run")

    dac = [row for row in runs if row.get("layer") == "dac_tile"]
    dac_qualified = bool(
        state.get("preflight", {}).get("interventions", {}).get("dac_tile", {}).get(
            "qualified", True
        )
    )
    if dac_qualified:
        if len(dac) != 18 or any(not row.get("ok") for row in dac):
            raise RuntimeError("resume requires the complete qualified DAC-tile layer")
    elif dac:
        raise RuntimeError("unqualified DAC-tile intervention must not have formal runs")

    successful_natural = [
        row for row in runs if row.get("layer") == "natural" and row.get("ok")
    ]
    by_rate: dict[int, list[dict[str, Any]]] = {}
    for row in successful_natural:
        by_rate.setdefault(int(row["sample_rate_msps"]), []).append(row)
    if any(rate not in (160, 320) or len(rows) != 1 for rate, rows in by_rate.items()):
        raise RuntimeError("resume found duplicate or unexpected successful natural runs")

    pending: list[dict[str, Any]] = []
    for template in natural_plan():
        rate = int(template["sample_rate_msps"])
        if rate in by_rate:
            continue
        base = str(template["name"])
        retry = 1
        while (evidence_root / "runs" / f"{base}_retry{retry}").exists():
            retry += 1
        pending.append({**template, "name": f"{base}_retry{retry}", "canonical_name": base})
    return pending


def resume_natural_campaign(
    args: argparse.Namespace,
    template: dict[str, Any],
    campaign_path: Path,
) -> int:
    state = json.loads(campaign_path.read_text())
    if state.get("operational_ok"):
        raise RuntimeError("campaign is already operationally complete")
    if state.get("classification") != "STAGE34C3_OPERATIONAL_FAIL":
        raise RuntimeError(
            f"campaign is not in the resumable operational-fail state: {state.get('classification')}"
        )
    pending = natural_resume_rows(state, args.receiver_output)
    if not pending:
        raise RuntimeError("campaign has no missing natural observations")

    original_board = agent_get(args, "/api/v2/status")
    original_receiver = receiver_state(args)
    history = {
        "started_at_unix_ms": time.time_ns() // 1_000_000,
        "prior_classification": state.get("classification"),
        "prior_errors": list(state.get("errors", [])),
        "prior_finished_at_unix_ms": state.get("finished_at_unix_ms"),
        "pending_runs": [row["name"] for row in pending],
        "status": "RUNNING",
    }
    state.setdefault("resume_history", []).append(history)
    state["classification"] = "STAGE34C3_RESUME_IN_PROGRESS"
    state["operational_ok"] = False
    state["errors"] = []
    state["finalize_errors"] = []
    state["science"] = None
    state["pcap_manifest"] = None
    state["plots"] = None
    state["resume_pending"] = [row["name"] for row in pending]
    state.pop("finished_at_unix_ms", None)
    write_json(campaign_path, state)

    try:
        for row in pending:
            fresh_configure(args, template, int(row["sample_rate_msps"]), "spec_only")
            result = execute_run(args, row=row, duration_seconds=NATURAL_SECONDS)
            state["runs"].append(result)
            state["resume_pending"] = [
                name for name in state["resume_pending"] if name != row["name"]
            ]
            write_json(campaign_path, state)

        state["science"] = classify(
            state["runs"], state["preflight"].get("interventions", {})
        )
        state["classification"] = state["science"]["primary"]
        state["operational_ok"] = True
        write_summary_csv(args.receiver_output / "summary.csv", state["runs"])
        state["pcap_manifest"] = pcap_manifest(args.receiver_output)
        state["plots"] = write_plots(
            args.receiver_output, state["runs"], state["science"]
        )
        history["status"] = "COMPLETE"
    except Exception as exc:
        state["errors"].append(f"{type(exc).__name__}:{exc}")
        state["classification"] = "STAGE34C3_OPERATIONAL_FAIL"
        history["status"] = "FAILED"
        history["error"] = state["errors"][-1]
    finally:
        state["finalize_errors"] = safe_finalize(
            args, template, original_board, original_receiver
        )
        state["finished_at_unix_ms"] = time.time_ns() // 1_000_000
        history["finished_at_unix_ms"] = state["finished_at_unix_ms"]
        if state["finalize_errors"]:
            state["errors"].extend(state["finalize_errors"])
            state["classification"] = "STAGE34C3_OPERATIONAL_FAIL"
            state["operational_ok"] = False
            history["status"] = "FAILED"
        write_json(campaign_path, state)
        write_json(
            args.board_output / "campaign_pointer.json",
            {
                "campaign": str(campaign_path),
                "classification": state["classification"],
                "operational_ok": state["operational_ok"],
            },
        )
    return 0 if state["operational_ok"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent-base", default="http://192.168.100.117:8010")
    parser.add_argument("--receiver-base", default="http://192.168.100.162:8089")
    parser.add_argument("--configure-template", type=Path, default=Path("config/t510/configure_320_time_only.example.json"))
    parser.add_argument("--receiver-output", type=Path, default=Path("build/receiver/latest/evidence/power_thermal_causality"))
    parser.add_argument("--board-output", type=Path, default=Path("build/board/latest/evidence/power_thermal_causality"))
    parser.add_argument("--settle-seconds", type=float, default=2.0)
    parser.add_argument("--dac-intervention-unqualified-evidence", type=Path)
    parser.add_argument("--ssa-confirmed", action="store_true")
    parser.add_argument(
        "--resume-natural",
        action="store_true",
        help="preserve completed intervention runs and acquire only missing 60-minute natural observations",
    )
    args = parser.parse_args()
    if not args.ssa_confirmed:
        parser.error("--ssa-confirmed is required for the frozen shared-50-ohm wiring")
    args.receiver_output = args.receiver_output.resolve()
    args.board_output = args.board_output.resolve()
    campaign_path = args.receiver_output / "campaign.json"
    if campaign_path.exists() and not args.resume_natural:
        raise RuntimeError(f"refusing to overwrite existing campaign {campaign_path}")
    if not campaign_path.exists() and args.resume_natural:
        raise RuntimeError(f"cannot resume missing campaign {campaign_path}")
    args.receiver_output.mkdir(parents=True, exist_ok=True)
    args.board_output.mkdir(parents=True, exist_ok=True)
    template = json.loads(args.configure_template.read_text())
    if args.resume_natural:
        return resume_natural_campaign(args, template, campaign_path)
    state: dict[str, Any] = {
        "classification": "STAGE34C3_IN_PROGRESS",
        "operational_ok": False,
        "core_version": CORE_VERSION,
        "bitstream_id": BITSTREAM_ID,
        "bitstream_sha256": BITSTREAM_SHA256,
        "pfb_profile_id": PFB_PROFILE_ID,
        "physical_setup": "SHARED_50OHM_REFERENCE: SSA RF INPUT -> splitter -> ADC0/ADC2; TG/preamp off; 20 dB attenuation; all DAC physically disconnected",
        "frequency_contract": monitor_frequency_contract(),
        "formal_plan": full_formal_plan(),
        "formal_run_count_expected": 29,
        "pure_capture_seconds": 29 * FORMAL_SECONDS + 2 * (NATURAL_SECONDS - FORMAL_SECONDS),
        "mandatory_pending": ["ADC_ANALOG_RAIL_RIPPLE_QUALIFICATION_PENDING", "THERMAL_CAUSALITY_PENDING_ACTIVE_CONTROL"],
        "preflight": None,
        "runs": [],
        "errors": [],
        "started_at_unix_ms": time.time_ns() // 1_000_000,
    }
    write_json(campaign_path, state)
    original_board = None
    original_receiver = None
    try:
        original_receiver = receiver_state(args)
        original_board = agent_get(args, "/api/v2/status")
        state["preflight"] = preflight(args, template, args.receiver_output)
        write_json(campaign_path, state)

        for repeat in range(1, 4):
            fresh_configure(args, template, 160, "spec_only")
            a1_row, b_row, a2_row = [row for row in output_load_plan() if int(row["repeat"]) == repeat]
            a1 = execute_run(args, row=a1_row, duration_seconds=FORMAL_SECONDS)
            state["runs"].append(a1); write_json(campaign_path, state)
            receiver_prepare(args, 160, "time_spec")
            transaction = agent_post(args, "/api/v2/diagnostics/output-load", {"expected_board_id": BOARD_ID, "receiver_stream_accepting": False, "mode": "time_spec"})
            b = execute_run(args, row=b_row, duration_seconds=FORMAL_SECONDS, start_transactions={"output_load_transaction_id": transaction["output_load_transaction_id"]})
            b["output_load_transaction"] = transaction
            state["runs"].append(b); write_json(campaign_path, state)
            restore = agent_post(args, "/api/v2/diagnostics/output-load/restore", {"expected_board_id": BOARD_ID, "receiver_stream_accepting": False})
            a2 = execute_run(args, row=a2_row, duration_seconds=FORMAL_SECONDS)
            a2["output_load_restore"] = restore
            state["runs"].append(a2); write_json(campaign_path, state)

        tile_rows = dac_tile_plan()
        if state["preflight"]["interventions"]["dac_tile"]["qualified"]:
            for triplet in range(1, 7):
                selected = [row for row in tile_rows if int(row["triplet"]) == triplet]
                rate = int(selected[0]["sample_rate_msps"])
                fresh_configure(args, template, rate, "spec_only")
                a1 = execute_run(args, row=selected[0], duration_seconds=FORMAL_SECONDS)
                state["runs"].append(a1); write_json(campaign_path, state)
                shutdown = agent_post(args, "/api/v2/rfdc/power/dac-shutdown", {"expected_board_id": BOARD_ID, "receiver_stream_accepting": False})
                b = execute_run(args, row=selected[1], duration_seconds=FORMAL_SECONDS, start_transactions={"rfdc_power_transaction_id": shutdown["rfdc_power_transaction_id"]}, expected_dac_mask=0)
                b["rfdc_power_shutdown"] = shutdown
                state["runs"].append(b); write_json(campaign_path, state)
                restore = agent_post(args, "/api/v2/rfdc/power/restore", {"expected_board_id": BOARD_ID, "receiver_stream_accepting": False}, timeout=300.0)
                a2 = execute_run(args, row=selected[2], duration_seconds=FORMAL_SECONDS)
                a2["rfdc_power_restore"] = restore
                state["runs"].append(a2); write_json(campaign_path, state)
        else:
            state["intervention_unqualified"] = ["dac_tile"]
            state["formal_run_count_scheduled"] = 11
            state["pure_capture_seconds_scheduled"] = 9 * FORMAL_SECONDS + 2 * NATURAL_SECONDS
            write_json(campaign_path, state)

        for row in natural_plan():
            fresh_configure(args, template, int(row["sample_rate_msps"]), "spec_only")
            result = execute_run(args, row=row, duration_seconds=NATURAL_SECONDS)
            state["runs"].append(result); write_json(campaign_path, state)

        state["science"] = classify(
            state["runs"], state["preflight"].get("interventions", {})
        )
        state["classification"] = state["science"]["primary"]
        state["operational_ok"] = True
        write_summary_csv(args.receiver_output / "summary.csv", state["runs"])
        state["pcap_manifest"] = pcap_manifest(args.receiver_output)
        state["plots"] = write_plots(args.receiver_output, state["runs"], state["science"])
    except Exception as exc:
        state["errors"].append(f"{type(exc).__name__}:{exc}")
        state["classification"] = "STAGE34C3_OPERATIONAL_FAIL"
    finally:
        state["finalize_errors"] = safe_finalize(args, template, original_board, original_receiver)
        state["finished_at_unix_ms"] = time.time_ns() // 1_000_000
        if state["finalize_errors"]:
            state["errors"].extend(state["finalize_errors"])
            state["classification"] = "STAGE34C3_OPERATIONAL_FAIL"
            state["operational_ok"] = False
        write_json(campaign_path, state)
        write_json(args.board_output / "campaign_pointer.json", {"campaign": str(campaign_path), "classification": state["classification"], "operational_ok": state["operational_ok"]})
    return 0 if state["operational_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
