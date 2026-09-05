#!/usr/bin/env python3
"""Run Stage 34c shared-50-ohm and conditional OCB1 causal investigation."""

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
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import t510_astronomy as astronomy
import t510_astronomy_performance as performance
from scripts import t510_fullband_spur_scan as fullband


CORE_VERSION = "0x00010034"
BITSTREAM_SHA256 = "c21d93f5ea71e9ac17a4448cff138a8faaf9c7347d879be919b680d196b8a5be"
PFB_PROFILE_ID = "0x34a80001"
CENTER_MHZ = 1020.0
RF_FREQUENCIES_MHZ = (960.0, 980.0, 1000.0, 1040.0, 1060.0, 1080.0)
CLEAN_RF_MHZ = RF_FREQUENCIES_MHZ[1:]
LANE_MASK = 0x05
LANES = (0, 2)
FORMAL_DURATION_SECONDS = 600
PRECHECK_DURATION_SECONDS = 60
THERMAL_STABILITY_WINDOW_SECONDS = 60
THERMAL_STABILITY_MAX_WAIT_SECONDS = 600
THERMAL_STABILITY_ENDPOINT_MEDIAN_SECONDS = 10
THERMAL_STABILITY_MAX_ROBUST_DRIFT_C = 0.30
TEMPERATURE_GATE_MEDIAN_SECONDS = 10
TEMPERATURE_WARNING_FILTERED_SPAN_C = 2.0
TEMPERATURE_HARD_FILTERED_SPAN_C = 2.5
PACKETS_PER_FLOW = 32
RATES_MSPS = (160, 320)
C0_ORDER = ((160, 1), (320, 1), (320, 2), (160, 2), (160, 3), (320, 3))
TRIPLET_RATE_ORDER = ((160, 320), (320, 160), (160, 320))
SCIENTIFIC_EXIT_CLASSIFICATIONS = {
    "SHARED_50OHM_REFERENCE_RECOVERS_LONG_INTEGRATION",
    "OCB1_CAUSAL_ADC0_ADC2",
    "OCB1_FIXED_SPUR_ONLY",
    "OCB1_CONTRIBUTOR",
    "OCB1_NOT_CAUSAL_UNDER_SHARED_50OHM",
    "INCONCLUSIVE_BASELINE_NOT_REPRODUCED",
}


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


class IncrementalJsonTrace:
    """Append large traces in O(N), then materialize the compatible JSON once.

    Rewriting the complete, pretty-printed trace after every observation made a
    600-second run O(N^2).  Once the trace reached roughly 40 MB, the collector
    started missing otherwise healthy one-second watchdog snapshots.  The JSONL
    sidecar is flushed per row so an abrupt process failure still leaves useful
    evidence; controlled completion or failure produces the original JSON-array
    contract and then removes the sidecar.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self.partial_path = path.with_suffix(path.suffix + "l")
        self.rows: list[dict[str, Any]] = []
        self._stream: Any = None

    def __enter__(self) -> "IncrementalJsonTrace":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._stream = self.partial_path.open("w", encoding="utf-8")
        return self

    def append(self, row: dict[str, Any]) -> None:
        if self._stream is None:
            raise RuntimeError("incremental trace is not open")
        self._stream.write(
            json.dumps(row, separators=(",", ":"), sort_keys=True) + "\n"
        )
        self._stream.flush()
        self.rows.append(row)

    def __exit__(self, _exc_type: Any, _exc: Any, _traceback: Any) -> bool:
        if self._stream is not None:
            self._stream.close()
            self._stream = None
        # Keep the JSONL sidecar if materialization itself fails.
        write_json(self.path, self.rows)
        self.partial_path.unlink(missing_ok=True)
        return False


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def configure_body(
    template: dict[str, Any],
    sample_rate_msps: int,
    mode: str,
    center_mhz: float,
    *,
    bitstream_id: str = "fengine-0x00010034",
) -> dict[str, Any]:
    body = json.loads(json.dumps(template))
    body["bitstream_id"] = str(bitstream_id)
    body["board_id"] = 1
    body["profile"] = {
        "sample_rate_msps": int(sample_rate_msps),
        "mode": str(mode),
        "center_mhz": float(center_mhz),
    }
    for endpoint in body["endpoints"]:
        stream = str(endpoint["stream"]).upper()
        endpoint["enabled"] = stream == "SPEC" or (mode in ("time_only", "time_spec") and stream == "TIME")
        if mode == "time_only" and stream == "SPEC":
            endpoint["enabled"] = False
    return body


def receiver_prepare(
    receiver_base: str, sample_rate_msps: int, mode: str, center_mhz: float
) -> dict[str, Any]:
    return fullband._http_json(
        receiver_base.rstrip("/") + "/api/config",
        method="POST",
        body={
            "sample_rate_msps": int(sample_rate_msps),
            "output_mode": str(mode),
            "center_mhz": float(center_mhz),
            "expected_mhz": float(center_mhz),
            "dac_mhz": float(center_mhz),
            "target_mhz_by_channel": [float(center_mhz)] * 8,
            "channel_mask": LANE_MASK,
            "paused": False,
        },
    )


def configure(
    args: argparse.Namespace,
    template: dict[str, Any],
    sample_rate_msps: int,
    mode: str,
    center_mhz: float = CENTER_MHZ,
) -> dict[str, Any]:
    receiver_prepare(args.receiver_base, sample_rate_msps, mode, center_mhz)
    bitstream_id = str(
        getattr(args, "bitstream_id", "fengine-0x00010034")
    )
    return fullband._http_json(
        args.agent_base.rstrip("/") + "/api/v2/configure",
        method="POST",
        body=configure_body(
            template,
            sample_rate_msps,
            mode,
            center_mhz,
            bitstream_id=bitstream_id,
        ),
        timeout=210.0,
    )


def stop_and_mute(args: argparse.Namespace, center_mhz: float = CENTER_MHZ) -> list[str]:
    return performance.stop_and_mute(args.agent_base, center_mhz)


def receiver_condensed(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "captured_at_unix_ms": time.time_ns() // 1_000_000,
        "config": value.get("config"),
        "stats": value.get("stats"),
    }


def validate_board_status(
    status: dict[str, Any],
    sample_rate_msps: int,
    mode: str,
    center_mhz: float,
    *,
    expected_core_version: str = CORE_VERSION,
) -> None:
    profile = status.get("profile", {})
    channelizer = status.get("channelizer", {})
    if str(status.get("core_version", "")).lower() != expected_core_version.lower():
        raise RuntimeError(f"CORE_VERSION mismatch: {status.get('core_version')}")
    if not status.get("streaming") or not status.get("pipeline", {}).get("stream_accepting"):
        raise RuntimeError("board is not streaming/accepting")
    if int(profile.get("sample_rate_msps", 0)) != sample_rate_msps or profile.get("mode") != mode:
        raise RuntimeError(f"profile mismatch: {profile}")
    if abs(float(profile.get("center_mhz", 0.0)) - center_mhz) > 1.0e-6:
        raise RuntimeError(f"center mismatch: {profile}")
    if int(channelizer.get("nchan", 0)) != 4096 or int(channelizer.get("taps", 0)) != 8:
        raise RuntimeError(f"PFB geometry mismatch: {channelizer}")
    if str(channelizer.get("coefficient_id", "")).lower() != PFB_PROFILE_ID:
        raise RuntimeError(f"PFB profile mismatch: {channelizer}")
    if int(status.get("rfdc", {}).get("calibration", {}).get("frozen_adc_mask", -1)) != 0:
        raise RuntimeError("GCB/TSCB freeze mask must remain 0x00")
    dac = status.get("dac", {})
    channels = list(dac.get("channels", []))
    if int(dac.get("enable_mask", -1)) != 0 or len(channels) != 8:
        raise RuntimeError(f"DAC is not muted: {dac}")
    if any(bool(row.get("enabled")) or int(row.get("amplitude_code", -1)) != 0 for row in channels):
        raise RuntimeError(f"DAC channel is not muted: {dac}")


def correlation(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or len(left) < 2:
        return 0.0
    left_mean = statistics.fmean(left)
    right_mean = statistics.fmean(right)
    a = [value - left_mean for value in left]
    b = [value - right_mean for value in right]
    denominator = math.sqrt(sum(value * value for value in a) * sum(value * value for value in b))
    return sum(x * y for x, y in zip(a, b)) / denominator if denominator else 0.0


def analyze_monitor(raw: dict[str, Any], *, seed: int) -> dict[str, Any]:
    targets = {int(row["target_index"]): row for row in raw["targets"]}
    grouped: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for row in raw["power_seconds"]:
        lane = int(row["lane"])
        if lane in LANES:
            grouped.setdefault((lane, int(row["target_index"])), []).append(row)
    combinations = []
    series: dict[tuple[int, int], list[float]] = {}
    for (lane, target_index), rows in sorted(grouped.items()):
        rows.sort(key=lambda row: int(row["second"]))
        powers = [astronomy.mean_power_from_accumulator(row) for row in rows]
        if len(powers) < FORMAL_DURATION_SECONDS - 3:
            raise RuntimeError(
                f"ADC{lane} target {target_index} has only {len(powers)} seconds"
            )
        series[(lane, target_index)] = powers
        raw_stats = astronomy.integration_statistics(powers)
        shuffled = list(powers)
        random.Random(seed ^ (lane << 16) ^ target_index).shuffle(shuffled)
        shuffled_stats = astronomy.integration_statistics(shuffled)
        slope = float(raw_stats["slope"])
        rf_mhz = float(targets[target_index]["actual_rf_mhz"])
        combinations.append(
            {
                "lane": lane,
                "target_index": target_index,
                "rf_mhz": rf_mhz,
                "clean": rf_mhz in CLEAN_RF_MHZ,
                "seconds": len(powers),
                "slope": slope,
                "shuffled_slope": float(shuffled_stats["slope"]),
                "slope_pass": -0.65 <= slope <= -0.35,
                "lag1_correlation": correlation(powers[:-1], powers[1:]),
                "mean_dbfs": float(raw_stats["mean_dbfs"]),
                "curve": raw_stats["curve"],
                "shuffled_curve": shuffled_stats["curve"],
                "power_series": powers,
            }
        )
    if len(combinations) != len(LANES) * len(RF_FREQUENCIES_MHZ):
        raise RuntimeError(f"monitor produced {len(combinations)} combinations, expected 12")
    matrix = {}
    for lane in LANES:
        matrix[str(lane)] = [
            [correlation(series[(lane, left)], series[(lane, right)]) for right in range(6)]
            for left in range(6)
        ]
    cross_adc_same_rf = {
        str(index): correlation(series[(LANES[0], index)], series[(LANES[1], index)])
        for index in range(len(RF_FREQUENCIES_MHZ))
    }
    clean = [row for row in combinations if row["clean"]]
    fixed = [row for row in combinations if not row["clean"]]
    return {
        "combinations": combinations,
        "clean": summarize_combinations(clean),
        "fixed_960": summarize_combinations(fixed),
        "same_adc_frequency_correlation": matrix,
        "cross_adc_same_rf_correlation": cross_adc_same_rf,
    }


def summarize_combinations(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "count": len(rows),
        "slope_pass_count": sum(int(row["slope_pass"]) for row in rows),
        "slope_pass_fraction": statistics.fmean(int(row["slope_pass"]) for row in rows),
        "median_slope": statistics.median(float(row["slope"]) for row in rows),
        "median_shuffled_slope": statistics.median(float(row["shuffled_slope"]) for row in rows),
        "median_abs_lag1": statistics.median(abs(float(row["lag1_correlation"])) for row in rows),
        "median_abs_slope_error": statistics.median(abs(float(row["slope"]) + 0.5) for row in rows),
    }


def extract_temperatures(resident: dict[str, Any]) -> dict[str, float]:
    telemetry = resident.get("ams") or resident.get("calibration", {}).get("ams") or {}
    values: dict[str, float] = {}
    for name, row in dict(telemetry.get("temperatures_c", {})).items():
        if isinstance(row, dict) and row.get("mean") is not None:
            values[str(name)] = float(row["mean"])
    return values


def thermal_window_summary(rows: list[dict[str, float]]) -> dict[str, Any]:
    names = sorted({name for row in rows for name in row})
    sensors = {}
    for name in names:
        values = [float(row[name]) for row in rows if name in row]
        if values:
            endpoint_count = min(THERMAL_STABILITY_ENDPOINT_MEDIAN_SECONDS, len(values) // 2)
            robust_drift = (
                statistics.median(values[-endpoint_count:])
                - statistics.median(values[:endpoint_count])
                if endpoint_count > 0
                else math.inf
            )
            sensors[name] = {
                "count": len(values),
                "min": min(values),
                "max": max(values),
                "span": max(values) - min(values),
                "drift": values[-1] - values[0],
                "robust_drift": robust_drift,
            }
    stable = bool(sensors) and all(
        row["count"] >= THERMAL_STABILITY_WINDOW_SECONDS - 2
        and abs(row["robust_drift"]) <= THERMAL_STABILITY_MAX_ROBUST_DRIFT_C
        for row in sensors.values()
    )
    return {"stable": stable, "sensors": sensors}


def temperature_series_summary(series: dict[str, list[float]]) -> dict[str, Any]:
    result = {}
    for sensor, values in sorted(series.items()):
        filtered = [
            statistics.median(values[index - TEMPERATURE_GATE_MEDIAN_SECONDS + 1:index + 1])
            for index in range(TEMPERATURE_GATE_MEDIAN_SECONDS - 1, len(values))
        ]
        result[sensor] = {
            "raw": {
                "min": min(values),
                "max": max(values),
                "span": max(values) - min(values),
            },
            "filtered": (
                {
                    "min": min(filtered),
                    "max": max(filtered),
                    "span": max(filtered) - min(filtered),
                }
                if filtered
                else None
            ),
        }
    return result


def temperature_gate(summary: dict[str, Any]) -> dict[str, Any]:
    """Classify robust temperature spans without hiding the original 2 C limit."""

    sensors = {}
    warnings = []
    errors = []
    for sensor, row in sorted(summary.items()):
        filtered = row.get("filtered") or {}
        span = filtered.get("span")
        if span is None:
            continue
        value = float(span)
        status = "PASS"
        if value > TEMPERATURE_HARD_FILTERED_SPAN_C:
            status = "FAIL"
            errors.append(sensor)
        elif value > TEMPERATURE_WARNING_FILTERED_SPAN_C:
            status = "WARNING_OVER_ORIGINAL_2C_LIMIT"
            warnings.append(sensor)
        sensors[sensor] = {"filtered_span_c": value, "status": status}
    return {
        "pass": not errors,
        "warning": bool(warnings),
        "original_limit_c": TEMPERATURE_WARNING_FILTERED_SPAN_C,
        "hard_limit_c": TEMPERATURE_HARD_FILTERED_SPAN_C,
        "warning_sensors": warnings,
        "failed_sensors": errors,
        "sensors": sensors,
    }


def triplet_temperature_gate(*runs: dict[str, Any]) -> dict[str, Any]:
    sensors = sorted(
        {
            sensor
            for run in runs
            for sensor in run.get("temperature_by_sensor_c", {})
        }
    )
    summary = {}
    for sensor in sensors:
        values = [
            float(value)
            for run in runs
            for value in (
                (
                    run.get("temperature_by_sensor_c", {})
                    .get(sensor, {})
                    .get("filtered")
                    or {}
                ).get("min"),
                (
                    run.get("temperature_by_sensor_c", {})
                    .get(sensor, {})
                    .get("filtered")
                    or {}
                ).get("max"),
            )
            if value is not None
        ]
        if values:
            summary[sensor] = {
                "filtered": {
                    "min": min(values),
                    "max": max(values),
                    "span": max(values) - min(values),
                }
            }
    return temperature_gate(summary)


def ocb1_triplet_plan() -> list[dict[str, Any]]:
    rows = []
    triplet_index = 0
    for repeat, rate_order in enumerate(TRIPLET_RATE_ORDER, start=1):
        for rate in rate_order:
            triplet_index += 1
            rows.append(
                {
                    "triplet_index": triplet_index,
                    "repeat": repeat,
                    "sample_rate_msps": rate,
                    "prefix": f"c1_t{triplet_index:02d}_{rate}msps_r{repeat}",
                }
            )
    return rows


def wait_for_thermal_stability(
    args: argparse.Namespace,
    *,
    trace_path: Path,
    sample_rate_msps: int,
    mode: str,
) -> dict[str, Any]:
    started = time.monotonic()
    deadline = started + THERMAL_STABILITY_MAX_WAIT_SECONDS
    before_board = fullband._http_json(args.agent_base.rstrip("/") + "/api/v2/status", timeout=30.0)
    before_receiver = fullband._http_json(args.receiver_base.rstrip("/") + "/api/state")
    observations: list[dict[str, Any]] = []
    temperature_rows: list[dict[str, float]] = []
    last_timestamp: int | None = None
    while time.monotonic() < deadline:
        resident = fullband._http_json(
            args.agent_base.rstrip("/") + "/api/v2/rfdc/calibration/monitor"
        )
        ams = resident.get("ams") or {}
        captured = int(ams.get("captured_at_unix_ms", 0) or 0)
        temperatures = extract_temperatures(resident)
        if not ams.get("supported") or not temperatures:
            raise RuntimeError(f"AMS thermal warm-up monitor unavailable: {ams}")
        if captured != last_timestamp:
            observations.append(
                {
                    "elapsed_seconds": time.monotonic() - started,
                    "captured_at_unix_ms": captured,
                    "temperatures_c": temperatures,
                    "voltages_v": ams.get("voltages_v", {}),
                }
            )
            temperature_rows.append(temperatures)
            last_timestamp = captured
            write_json(trace_path, observations)
            window = temperature_rows[-THERMAL_STABILITY_WINDOW_SECONDS:]
            summary = thermal_window_summary(window)
            if summary["stable"]:
                after_board = fullband._http_json(
                    args.agent_base.rstrip("/") + "/api/v2/status", timeout=30.0
                )
                after_receiver = fullband._http_json(
                    args.receiver_base.rstrip("/") + "/api/state"
                )
                validate_board_status(
                    after_board,
                    sample_rate_msps,
                    mode,
                    CENTER_MHZ,
                    expected_core_version=str(
                        getattr(args, "expected_core_version", CORE_VERSION)
                    ),
                )
                integrity = fullband._window_integrity(
                    before_board, after_board, before_receiver, after_receiver
                )
                if not integrity["ok"]:
                    raise RuntimeError(
                        f"thermal warm-up digital integrity failed: {integrity['errors']}"
                    )
                return {
                    "ok": True,
                    "elapsed_seconds": time.monotonic() - started,
                    "window": summary,
                    "observation_count": len(observations),
                    "integrity": integrity,
                }
        time.sleep(0.5)
    raise RuntimeError(
        "full-rate thermal warm-up did not stabilize within "
        f"{THERMAL_STABILITY_MAX_WAIT_SECONDS} seconds"
    )


def wait_for_monitor(
    args: argparse.Namespace,
    *,
    duration_seconds: int,
    trace_path: Path,
    expected_ocb1_state: str,
    expected_ocb1_hash: str | None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    deadline = time.monotonic() + duration_seconds + 60.0
    last_calibration_timestamp: int | None = None
    temperatures: dict[str, list[float]] = {}
    with IncrementalJsonTrace(trace_path) as trace:
        while time.monotonic() < deadline:
            monitor = fullband._http_json(
                args.receiver_base.rstrip("/") + "/api/measure/spec-stability/status"
            )
            resident = fullband._http_json(
                args.agent_base.rstrip("/") + "/api/v2/rfdc/calibration/monitor"
            )
            calibration = resident.get("calibration", {})
            captured = int(calibration.get("captured_at_unix_ms", 0) or 0)
            if not calibration.get("supported") or calibration.get("error"):
                raise RuntimeError(f"resident calibration observation failed: {calibration}")
            if int(calibration.get("frozen_adc_mask", -1)) != 0:
                raise RuntimeError("GCB/TSCB freeze mask changed during Stage 34c")
            ocb1 = resident.get("ocb1", {})
            persisted = ocb1.get("state", {})
            state_name = str(persisted.get("ocb1_override_state", "DYNAMIC"))
            if state_name != expected_ocb1_state:
                raise RuntimeError(
                    f"OCB1 state changed: expected {expected_ocb1_state}, got {state_name}"
                )
            if expected_ocb1_hash is not None:
                if (
                    str(ocb1.get("current_sha256")) != expected_ocb1_hash
                    or not ocb1.get("integrity_ok")
                ):
                    raise RuntimeError(f"OCB1 override hash/integrity changed: {ocb1}")
            if captured != last_calibration_timestamp:
                row = {
                    "elapsed_seconds": len(trace.rows),
                    "resident": resident,
                    "receiver": receiver_condensed(
                        fullband._http_json(
                            args.receiver_base.rstrip("/") + "/api/state"
                        )
                    ),
                }
                trace.append(row)
                last_calibration_timestamp = captured
                for name, value in extract_temperatures(resident).items():
                    temperatures.setdefault(name, []).append(value)
                temperature_summary = temperature_series_summary(temperatures)
                gate = temperature_gate(temperature_summary)
                for name in gate["failed_sensors"]:
                    summary = temperature_summary[name]
                    filtered = summary["filtered"]
                    if filtered is not None:
                        raise RuntimeError(
                            f"{name} 10-second-median temperature span exceeded "
                            f"{TEMPERATURE_HARD_FILTERED_SPAN_C:.1f} C: "
                            f"{filtered['min']:.3f}..{filtered['max']:.3f}; "
                            f"raw={summary['raw']['min']:.3f}..{summary['raw']['max']:.3f}"
                        )
            if monitor.get("status") == "completed":
                result = fullband._http_json(
                    args.receiver_base.rstrip("/")
                    + "/api/measure/spec-stability/result",
                    timeout=180.0,
                )
                if len(trace.rows) < duration_seconds - 5:
                    raise RuntimeError(
                        f"only {len(trace.rows)} one-second observations"
                    )
                return result, trace.rows
            if monitor.get("status") == "failed":
                raise RuntimeError(f"receiver monitor failed: {monitor.get('error')}")
            time.sleep(0.5)
    raise RuntimeError("receiver monitor did not complete before deadline")


def capture_run_edge(
    args: argparse.Namespace, run_dir: Path, edge: str, mode: str
) -> dict[str, Any]:
    paths, metadata = fullband.capture_receiver_pcap(
        receiver_base=args.receiver_base,
        local_dir=run_dir / "raw" / edge,
        packets_per_block=PACKETS_PER_FLOW,
        include_time=mode == "time_spec",
    )
    return {
        **metadata,
        "paths": [str(path.resolve()) for path in paths],
        "sha256": {str(path.name): sha256_file(path) for path in paths},
    }


def execute_run(
    args: argparse.Namespace,
    template: dict[str, Any],
    *,
    name: str,
    sample_rate_msps: int,
    mode: str,
    condition: str,
    fresh_configure: bool,
    ocb1_transaction_id: str | None = None,
    expected_ocb1_hash: str | None = None,
) -> dict[str, Any]:
    run_dir = args.receiver_output / "runs" / name
    run_dir.mkdir(parents=True, exist_ok=False)
    evidence: dict[str, Any] = {
        "name": name,
        "sample_rate_msps": sample_rate_msps,
        "mode": mode,
        "condition": condition,
        "ok": False,
        "classification": "STAGE34C_RUN_IN_PROGRESS",
        "center_mhz": CENTER_MHZ,
        "rf_frequencies_mhz": list(RF_FREQUENCIES_MHZ),
        "started_at_unix_ms": time.time_ns() // 1_000_000,
        "errors": [],
    }
    write_json(run_dir / "result.json", evidence)
    try:
        if fresh_configure:
            evidence["configure"] = configure(
                args, template, sample_rate_msps, mode
            )
        else:
            receiver_prepare(args.receiver_base, sample_rate_msps, mode, CENTER_MHZ)
        start_body: dict[str, Any] = {"expected_board_id": 1}
        if ocb1_transaction_id is not None:
            start_body["ocb1_transaction_id"] = ocb1_transaction_id
        evidence["start"] = fullband._http_json(
            args.agent_base.rstrip("/") + "/api/v2/start",
            method="POST",
            body=start_body,
        )
        time.sleep(args.settle_seconds)
        evidence["thermal_warmup"] = wait_for_thermal_stability(
            args,
            trace_path=run_dir / "thermal_warmup_trace.json",
            sample_rate_msps=sample_rate_msps,
            mode=mode,
        )
        before_board = fullband._http_json(args.agent_base.rstrip("/") + "/api/v2/status", timeout=30.0)
        before_receiver = fullband._http_json(args.receiver_base.rstrip("/") + "/api/state")
        validate_board_status(before_board, sample_rate_msps, mode, CENTER_MHZ)
        begin_capture = capture_run_edge(args, run_dir, "begin", mode)
        request = {
            "duration_seconds": FORMAL_DURATION_SECONDS,
            "formal": True,
            "sample_rate_msps": sample_rate_msps,
            "center_mhz": CENTER_MHZ,
            "rf_frequencies_mhz": list(RF_FREQUENCIES_MHZ),
            "correlation_pair": [0, 2],
            "lane_mask": LANE_MASK,
            "include_time_statistics": mode == "time_spec",
        }
        evidence["monitor_start"] = fullband._http_json(
            args.receiver_base.rstrip("/") + "/api/measure/spec-stability",
            method="POST",
            body=request,
        )
        raw, observations = wait_for_monitor(
            args,
            duration_seconds=FORMAL_DURATION_SECONDS,
            trace_path=run_dir / "calibration_ams_trace.json",
            expected_ocb1_state=("OVERRIDE_ACTIVE" if ocb1_transaction_id else "DYNAMIC"),
            expected_ocb1_hash=expected_ocb1_hash,
        )
        write_json(run_dir / "monitor_raw.json", raw)
        end_capture = capture_run_edge(args, run_dir, "end", mode)
        after_board = fullband._http_json(args.agent_base.rstrip("/") + "/api/v2/status", timeout=30.0)
        after_receiver = fullband._http_json(args.receiver_base.rstrip("/") + "/api/state")
        validate_board_status(after_board, sample_rate_msps, mode, CENTER_MHZ)
        integrity = fullband._window_integrity(
            before_board, after_board, before_receiver, after_receiver
        )
        if not integrity["ok"]:
            raise RuntimeError(f"digital integrity failed: {integrity['errors']}")
        name_seed = int.from_bytes(hashlib.sha256(name.encode("utf-8")).digest()[:4], "little")
        analysis = analyze_monitor(raw, seed=0x34C00000 ^ name_seed)
        time_stats = list(raw.get("time_seconds", []))
        if mode == "time_spec":
            if not time_stats or any(row.get("clipped") for row in time_stats):
                raise RuntimeError("TIME statistics are absent or clipped")
        ocb1_hashes = {
            str(row["resident"]["calibration"]["coefficient_sha256"]["ocb1"])
            for row in observations
        }
        temperatures: dict[str, list[float]] = {}
        for row in observations:
            for sensor, value in extract_temperatures(row["resident"]).items():
                temperatures.setdefault(sensor, []).append(value)
        temperature_summary = temperature_series_summary(temperatures)
        evidence.update(
            {
                "ok": True,
                "classification": "STAGE34C_RUN_COMPLETE",
                "before_board": before_board,
                "after_board": after_board,
                "before_receiver": receiver_condensed(before_receiver),
                "after_receiver": receiver_condensed(after_receiver),
                "integrity": integrity,
                "analysis": analysis,
                "time_statistics": time_stats,
                "begin_capture": begin_capture,
                "end_capture": end_capture,
                "ocb1_unique_hashes": len(ocb1_hashes),
                "ocb1_hashes": sorted(ocb1_hashes),
                "temperature_by_sensor_c": temperature_summary,
                "temperature_gate": temperature_gate(temperature_summary),
            }
        )
    except Exception as exc:
        evidence["errors"].append(f"{type(exc).__name__}: {exc}")
        evidence["classification"] = "STAGE34C_RUN_OPERATIONAL_FAIL"
        raise
    finally:
        evidence["errors"].extend(stop_and_mute(args))
        evidence["finished_at_unix_ms"] = time.time_ns() // 1_000_000
        if evidence["errors"]:
            evidence["ok"] = False
            evidence["classification"] = "STAGE34C_RUN_OPERATIONAL_FAIL"
        write_json(run_dir / "result.json", evidence)
    if not evidence["ok"]:
        raise RuntimeError(
            f"{name} cleanup/integrity failed: {evidence['errors']}"
        )
    return evidence


def run_gate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    combinations = [combo for row in rows for combo in row["analysis"]["combinations"] if combo["clean"]]
    repeat_pass = [int(row["analysis"]["clean"]["slope_pass_count"]) for row in rows]
    repeat_median = [float(row["analysis"]["clean"]["median_slope"]) for row in rows]
    summary = summarize_combinations(combinations)
    gates = {
        "each_repeat_at_least_8_of_10": all(value >= 8 for value in repeat_pass),
        "aggregate_at_least_24_of_30": int(summary["slope_pass_count"]) >= 24,
        "each_repeat_median_slope_in_range": all(-0.65 <= value <= -0.35 for value in repeat_median),
        "median_abs_lag1_le_0p10": float(summary["median_abs_lag1"]) <= 0.10,
        "raw_shuffled_median_delta_le_0p10": abs(
            float(summary["median_slope"]) - float(summary["median_shuffled_slope"])
        ) <= 0.10,
    }
    return {"pass": all(gates.values()), "gates": gates, "summary": summary, "repeat_pass_counts": repeat_pass}


def aggregate_c0(rows: list[dict[str, Any]]) -> dict[str, Any]:
    rates = {}
    for rate in RATES_MSPS:
        selected = [row for row in rows if int(row["sample_rate_msps"]) == rate]
        rates[str(rate)] = run_gate(selected)
    passed = all(row["pass"] for row in rates.values())
    return {
        "pass": passed,
        "classification": (
            "SHARED_50OHM_REFERENCE_RECOVERS_LONG_INTEGRATION"
            if passed
            else "SHARED_50OHM_REFERENCE_REPRODUCES_CORRELATED_NOISE"
        ),
        "rates": rates,
    }


def metric_for_condition(rows: list[dict[str, Any]], condition: str, rate: int) -> dict[str, Any]:
    selected = [
        row for row in rows
        if row["condition"] == condition and int(row["sample_rate_msps"]) == rate
    ]
    gate = run_gate(selected)
    hashes = [int(row.get("ocb1_unique_hashes", 0)) for row in selected]
    return {**gate, "ocb1_unique_hashes_by_run": hashes}


def aggregate_ocb1(rows: list[dict[str, Any]]) -> dict[str, Any]:
    rates: dict[str, Any] = {}
    all_causal = True
    any_clean_improvement = False
    any_fixed_improvement = False
    inconclusive = False
    for rate in RATES_MSPS:
        a1 = metric_for_condition(rows, "A1_DYNAMIC", rate)
        b = metric_for_condition(rows, "B_OCB1_SNAPSHOT", rate)
        a2 = metric_for_condition(rows, "A2_RESTORED", rate)
        a1s, bs, a2s = a1["summary"], b["summary"], a2["summary"]
        baseline_reproduced = bool(
            int(a1s["slope_pass_count"]) <= 3
            and float(a1s["median_abs_slope_error"]) >= 0.12
        )
        if not baseline_reproduced:
            inconclusive = True
        improvement_fraction = float(bs["slope_pass_fraction"]) - float(a1s["slope_pass_fraction"])
        slope_error_improvement = float(a1s["median_abs_slope_error"]) - float(bs["median_abs_slope_error"])
        lag_improvement = float(a1s["median_abs_lag1"]) - float(bs["median_abs_lag1"])
        a2_return = abs(float(a2s["median_slope"]) - float(a1s["median_slope"])) <= 0.10 and abs(
            float(a2s["median_abs_lag1"]) - float(a1s["median_abs_lag1"])
        ) <= 0.10
        a2_degrades = (
            float(a2s["median_abs_slope_error"]) > float(bs["median_abs_slope_error"])
            and float(a2s["median_abs_lag1"]) > float(bs["median_abs_lag1"])
        )
        hashes_ok = all(value == 1 for value in b["ocb1_unique_hashes_by_run"]) and all(
            value > 1 for value in a1["ocb1_unique_hashes_by_run"] + a2["ocb1_unique_hashes_by_run"]
        )
        causal_gates = {
            "a1_baseline_reproduced": baseline_reproduced,
            "b_absolute_gate": bool(b["pass"]),
            "pass_fraction_improvement_ge_0p50": improvement_fraction >= 0.50,
            "slope_error_improvement_ge_0p12": slope_error_improvement >= 0.12,
            "lag_improvement_ge_0p10": lag_improvement >= 0.10,
            "a2_degrades_from_b": a2_degrades,
            "a2_returns_to_a1_within_0p10": a2_return,
            "ocb1_hash_behavior": hashes_ok,
        }
        causal = all(causal_gates.values())
        all_causal &= causal
        any_clean_improvement |= (
            improvement_fraction >= 0.20
            or slope_error_improvement >= 0.05
            or lag_improvement >= 0.05
        )
        fixed_a = statistics.median(
            float(row["analysis"]["fixed_960"]["median_abs_lag1"])
            for row in rows if row["condition"] == "A1_DYNAMIC" and int(row["sample_rate_msps"]) == rate
        )
        fixed_b = statistics.median(
            float(row["analysis"]["fixed_960"]["median_abs_lag1"])
            for row in rows if row["condition"] == "B_OCB1_SNAPSHOT" and int(row["sample_rate_msps"]) == rate
        )
        any_fixed_improvement |= fixed_a - fixed_b >= 0.10
        rates[str(rate)] = {
            "A1": a1,
            "B": b,
            "A2": a2,
            "improvements": {
                "pass_fraction": improvement_fraction,
                "median_slope_error": slope_error_improvement,
                "median_abs_lag1": lag_improvement,
                "fixed_960_abs_lag1": fixed_a - fixed_b,
            },
            "causal_gates": causal_gates,
            "causal": causal,
        }
    if all_causal:
        classification = "OCB1_CAUSAL_ADC0_ADC2"
    elif inconclusive:
        classification = "INCONCLUSIVE_BASELINE_NOT_REPRODUCED"
    elif any_clean_improvement:
        classification = "OCB1_CONTRIBUTOR"
    elif any_fixed_improvement:
        classification = "OCB1_FIXED_SPUR_ONLY"
    else:
        classification = "OCB1_NOT_CAUSAL_UNDER_SHARED_50OHM"
    return {"pass": all_causal, "classification": classification, "rates": rates}


def preview_preflight(args: argparse.Namespace, template: dict[str, Any]) -> dict[str, Any]:
    configure(args, template, 320, "spec_only")
    preview = fullband._http_json(
        args.agent_base.rstrip("/") + "/api/v2/rfdc/calibration/preview",
        method="POST",
        body={"expected_board_id": 1},
        timeout=30.0,
    )
    channels = list(preview.get("channels", []))
    if len(channels) != 8 or any(
        bool(row.get("clipped")) or float(row.get("peak_dbfs", 0.0)) >= -1.0
        for row in channels
    ):
        raise RuntimeError(f"stopped preview clip/peak gate failed: {channels}")
    return preview


def monitor_performance_preflight(
    args: argparse.Namespace, template: dict[str, Any]
) -> dict[str, Any]:
    rows = []
    for rate, mode in ((320, "spec_only"), (160, "time_spec")):
        configure(args, template, rate, mode)
        fullband._http_json(
            args.agent_base.rstrip("/") + "/api/v2/start",
            method="POST",
            body={"expected_board_id": 1},
        )
        time.sleep(args.settle_seconds)
        thermal_warmup = wait_for_thermal_stability(
            args,
            trace_path=args.receiver_output / "preflight" / f"{rate}_{mode}_thermal_warmup.json",
            sample_rate_msps=rate,
            mode=mode,
        )
        before = fullband._http_json(args.receiver_base.rstrip("/") + "/api/state")
        before_board = fullband._http_json(args.agent_base.rstrip("/") + "/api/v2/status", timeout=30.0)
        time.sleep(PRECHECK_DURATION_SECONDS)
        middle = fullband._http_json(args.receiver_base.rstrip("/") + "/api/state")
        middle_board = fullband._http_json(args.agent_base.rstrip("/") + "/api/v2/status", timeout=30.0)
        off_integrity = fullband._window_integrity(before_board, middle_board, before, middle)
        if not off_integrity["ok"]:
            raise RuntimeError(f"monitor-off integrity failed: {off_integrity['errors']}")
        start = fullband._http_json(
            args.receiver_base.rstrip("/") + "/api/measure/spec-stability",
            method="POST",
            body={
                "duration_seconds": PRECHECK_DURATION_SECONDS,
                "formal": False,
                "sample_rate_msps": rate,
                "center_mhz": CENTER_MHZ,
                "rf_frequencies_mhz": list(RF_FREQUENCIES_MHZ),
                "correlation_pair": [0, 2],
                "lane_mask": LANE_MASK,
                "include_time_statistics": mode == "time_spec",
            },
        )
        raw, _observations = wait_for_monitor(
            args,
            duration_seconds=PRECHECK_DURATION_SECONDS,
            trace_path=args.receiver_output / "preflight" / f"{rate}_{mode}_trace.json",
            expected_ocb1_state="DYNAMIC",
            expected_ocb1_hash=None,
        )
        after = fullband._http_json(args.receiver_base.rstrip("/") + "/api/state")
        after_board = fullband._http_json(args.agent_base.rstrip("/") + "/api/v2/status", timeout=30.0)
        on_integrity = fullband._window_integrity(middle_board, after_board, middle, after)
        if not on_integrity["ok"]:
            raise RuntimeError(f"monitor-on integrity failed: {on_integrity['errors']}")
        rows.append(
            {
                "sample_rate_msps": rate,
                "mode": mode,
                "thermal_warmup": thermal_warmup,
                "monitor_start": start,
                "monitor_result": raw,
                "monitor_off_integrity": off_integrity,
                "monitor_on_integrity": on_integrity,
            }
        )
        errors = stop_and_mute(args)
        if errors:
            raise RuntimeError(f"preflight cleanup failed: {errors}")
    return {"ok": True, "runs": rows}


def snapshot_ocb1(args: argparse.Namespace) -> tuple[str, str, dict[str, Any]]:
    deadline = time.monotonic() + 5.0
    receiver = {}
    while time.monotonic() < deadline:
        receiver = fullband._http_json(args.receiver_base.rstrip("/") + "/api/state")
        if float(receiver.get("stats", {}).get("packets_per_sec", 0.0) or 0.0) <= 1.0:
            break
        time.sleep(0.25)
    else:
        raise RuntimeError("receiver still reports packet flow before OCB1 snapshot")
    result = fullband._http_json(
        args.agent_base.rstrip("/") + "/api/v2/rfdc/calibration/ocb1/snapshot-override",
        method="POST",
        body={"expected_board_id": 1, "receiver_stream_accepting": False},
        timeout=210.0,
    )
    ocb1 = result["ocb1"]
    return str(ocb1["ocb1_transaction_id"]), str(ocb1["snapshot_sha256"]), result


def release_ocb1(args: argparse.Namespace, transaction_id: str) -> dict[str, Any]:
    return fullband._http_json(
        args.agent_base.rstrip("/") + "/api/v2/rfdc/calibration/ocb1/release",
        method="POST",
        body={
            "expected_board_id": 1,
            "receiver_stream_accepting": False,
            "ocb1_transaction_id": transaction_id,
        },
        timeout=210.0,
    )


def safe_finalize(
    args: argparse.Namespace,
    template: dict[str, Any],
    original_board: dict[str, Any] | None,
    original_receiver: dict[str, Any] | None,
) -> list[str]:
    errors = stop_and_mute(args)
    try:
        ocb1 = fullband._http_json(
            args.agent_base.rstrip("/") + "/api/v2/rfdc/calibration/ocb1",
            timeout=30.0,
        )
        state = str(ocb1.get("ocb1_override_state", "DYNAMIC"))
        if state == "OVERRIDE_ACTIVE":
            release_ocb1(args, str(ocb1["ocb1_transaction_id"]))
            state = "RECONFIGURE_REQUIRED"
        if state != "DYNAMIC":
            configure(args, template, 160, "spec_only")
    except Exception as exc:
        errors.append(f"OCB1_FINAL_RESTORE:{type(exc).__name__}:{exc}")
    if original_board is not None:
        try:
            profile = original_board.get("profile", {})
            configure(
                args,
                template,
                int(profile.get("sample_rate_msps") or 160),
                str(profile.get("mode") or "spec_only"),
                float(profile.get("center_mhz") or CENTER_MHZ),
            )
        except Exception as exc:
            errors.append(f"BOARD_PROFILE_RESTORE:{type(exc).__name__}:{exc}")
    if original_receiver is not None and isinstance(original_receiver.get("config"), dict):
        try:
            fullband._http_json(
                args.receiver_base.rstrip("/") + "/api/config",
                method="POST",
                body=original_receiver["config"],
            )
        except Exception as exc:
            errors.append(f"RECEIVER_PROFILE_RESTORE:{type(exc).__name__}:{exc}")
    errors.extend(stop_and_mute(args, float((original_board or {}).get("profile", {}).get("center_mhz") or CENTER_MHZ)))
    try:
        board = fullband._http_json(args.agent_base.rstrip("/") + "/api/v2/status", timeout=30.0)
        receiver = fullband._http_json(args.receiver_base.rstrip("/") + "/api/state")
        ocb1 = board.get("rfdc", {}).get("ocb1", {})
        if board.get("streaming") or board.get("pipeline", {}).get("stream_accepting"):
            raise RuntimeError("board remains streaming")
        if int(board.get("dac", {}).get("enable_mask", -1)) != 0:
            raise RuntimeError("DAC mask is not zero")
        if int(board.get("rfdc", {}).get("calibration", {}).get("frozen_adc_mask", -1)) != 0:
            raise RuntimeError("freeze mask is not zero")
        if int(ocb1.get("ocb1_override_adc_mask", -1)) != 0 or ocb1.get("ocb1_override_state") != "DYNAMIC":
            raise RuntimeError(f"OCB1 final state invalid: {ocb1}")
        if float(receiver.get("stats", {}).get("packets_per_sec", 0.0) or 0.0) > 1.0:
            raise RuntimeError("receiver still observes packets")
    except Exception as exc:
        errors.append(f"FINAL_READBACK:{type(exc).__name__}:{exc}")
    return errors


def write_summary_csv(path: Path, runs: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=(
                "name", "sample_rate_msps", "condition", "lane", "rf_mhz",
                "slope", "shuffled_slope", "lag1_correlation", "mean_dbfs", "slope_pass",
            ),
        )
        writer.writeheader()
        for run in runs:
            for row in run["analysis"]["combinations"]:
                writer.writerow({
                    "name": run["name"],
                    "sample_rate_msps": run["sample_rate_msps"],
                    "condition": run["condition"],
                    **{key: row[key] for key in ("lane", "rf_mhz", "slope", "shuffled_slope", "lag1_correlation", "mean_dbfs", "slope_pass")},
                })


def autocorrelation_curve(values: list[float], max_lag: int = 64) -> list[float]:
    return [
        1.0 if lag == 0 else correlation(values[:-lag], values[lag:])
        for lag in range(min(max_lag, len(values) - 2) + 1)
    ]


def generate_ocb1_condition_summary_plot(
    root: Path, runs: list[dict[str, Any]]
) -> str | None:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return None

    conditions = ("A1_DYNAMIC", "B_OCB1_SNAPSHOT", "A2_RESTORED")
    labels = ("A1 dynamic", "B OCB1 locked", "A2 restored")
    colors = ("#3274a1", "#e1812c", "#3a923a")
    figure, axes = plt.subplots(2, 2, figsize=(13, 8))
    offsets = (-0.18, 0.0, 0.18)
    rate_x = {160: 0.0, 320: 1.0}
    aggregate_rows = []
    for condition_index, (condition, label, color) in enumerate(
        zip(conditions, labels, colors)
    ):
        for rate in RATES_MSPS:
            selected = [
                row
                for row in runs
                if row.get("condition") == condition
                and int(row.get("sample_rate_msps", 0)) == rate
            ]
            if not selected:
                continue
            slopes = [
                float(row["analysis"]["clean"]["median_slope"])
                for row in selected
            ]
            lags = [
                float(row["analysis"]["clean"]["median_abs_lag1"])
                for row in selected
            ]
            passes = [
                int(row["analysis"]["clean"]["slope_pass_count"])
                for row in selected
            ]
            x = rate_x[rate] + offsets[condition_index]
            jitter = [x + (index - (len(selected) - 1) / 2.0) * 0.035 for index in range(len(selected))]
            axes[0, 0].scatter(jitter, slopes, color=color, alpha=0.65, s=35)
            axes[0, 0].scatter([x], [statistics.median(slopes)], color=color, edgecolor="black", s=110, label=label if rate == 160 else None)
            axes[0, 1].scatter(jitter, lags, color=color, alpha=0.65, s=35)
            axes[0, 1].scatter([x], [statistics.median(lags)], color=color, edgecolor="black", s=110)
            axes[1, 0].bar(x, sum(passes), width=0.15, color=color, alpha=0.85)
            axes[1, 0].text(x, sum(passes) + 0.5, f"{sum(passes)}/30", ha="center", va="bottom", fontsize=8)
            aggregate_rows.append((rate, label, statistics.median(slopes), statistics.median(lags), sum(passes)))

    for axis in (axes[0, 0], axes[0, 1], axes[1, 0]):
        axis.set_xticks((0.0, 1.0), ("160 MS/s", "320 MS/s"))
        axis.grid(alpha=0.25)
    axes[0, 0].axhspan(-0.65, -0.35, color="green", alpha=0.08, label="accepted slope range")
    axes[0, 0].axhline(-0.5, color="green", linestyle="--", linewidth=1.0)
    axes[0, 0].set_ylabel("Median integration slope")
    axes[0, 0].set_title("Closer to -0.5 is better")
    axes[0, 0].legend(fontsize=8, ncol=2)
    axes[0, 1].axhspan(0.0, 0.10, color="green", alpha=0.08)
    axes[0, 1].axhline(0.10, color="green", linestyle="--", linewidth=1.0)
    axes[0, 1].set_ylabel("Median |lag-1 correlation|")
    axes[0, 1].set_title("Closer to 0 is better")
    axes[1, 0].axhline(24, color="green", linestyle="--", linewidth=1.0, label="required 24/30")
    axes[1, 0].set_ylim(0, 31)
    axes[1, 0].set_ylabel("Slope-pass combinations / 30")
    axes[1, 0].set_title("Absolute long-integration gate")
    axes[1, 0].legend(fontsize=8)

    axes[1, 1].axis("off")
    lines = [
        "Condition medians (three repeats)",
        "",
        *[
            f"{rate:3d}  {label:15s}  slope={slope:+.3f}  |lag1|={lag:.3f}  pass={passes:2d}/30"
            for rate, label, slope, lag, passes in aggregate_rows
        ],
        "",
        "Observed direction: locking OCB1 worsens both rates;",
        "releasing it returns toward the dynamic baseline.",
    ]
    axes[1, 1].text(
        0.02,
        0.98,
        "\n".join(lines),
        va="top",
        ha="left",
        family="monospace",
        fontsize=10,
    )
    figure.suptitle("Stage 34c OCB1 A1/B/A2 long-integration comparison")
    figure.tight_layout()
    output = root / "plots"
    output.mkdir(parents=True, exist_ok=True)
    path = output / "stage34c_ocb1_condition_summary.png"
    figure.savefig(path, dpi=160)
    plt.close(figure)
    return str(path.resolve())


def generate_plots(root: Path, runs: list[dict[str, Any]]) -> list[str]:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return []
    output = root / "plots"
    output.mkdir(parents=True, exist_ok=True)
    paths = []
    colors = plt.get_cmap("tab10")
    for run in runs:
        figure, axes = plt.subplots(2, 1, figsize=(12, 7), sharex=True)
        for axis, lane in zip(axes, LANES):
            for row in run["analysis"]["combinations"]:
                if row["lane"] == lane and row["clean"]:
                    mean = statistics.fmean(row["power_series"])
                    values = [(value / mean - 1.0) * 100.0 for value in row["power_series"]]
                    axis.plot(values, linewidth=0.7, alpha=0.7, label=f"{row['rf_mhz']:.0f} MHz")
            axis.set_ylabel(f"ADC{lane} / %")
            axis.grid(alpha=0.2)
            axis.legend(ncol=5, fontsize=7)
        axes[-1].set_xlabel("Time / s")
        figure.suptitle(f"{run['name']} shared 50-ohm power stability")
        figure.tight_layout()
        path = output / f"{run['name']}_power_timeline.png"
        figure.savefig(path, dpi=150)
        plt.close(figure)
        paths.append(str(path.resolve()))

        figure, axes = plt.subplots(2, 2, figsize=(13, 8), sharex=True)
        for lane_index, lane in enumerate(LANES):
            for row_index, row in enumerate(
                item
                for item in run["analysis"]["combinations"]
                if item["lane"] == lane and item["clean"]
            ):
                color = colors(row_index)
                raw_points = [
                    (item["tau_seconds"], item["fractional_stddev"])
                    for item in row["curve"]
                    if item["fractional_stddev"] is not None
                ]
                shuffled_points = [
                    (item["tau_seconds"], item["fractional_stddev"])
                    for item in row["shuffled_curve"]
                    if item["fractional_stddev"] is not None
                ]
                allan_points = [
                    (item["tau_seconds"], item["allan_deviation"])
                    for item in row["curve"]
                    if item["allan_deviation"] is not None
                ]
                axes[lane_index][0].loglog(
                    [x for x, _ in raw_points], [y for _, y in raw_points],
                    color=color, marker="o", linewidth=1.2,
                    label=f"{row['rf_mhz']:.0f} MHz raw",
                )
                axes[lane_index][0].loglog(
                    [x for x, _ in shuffled_points], [y for _, y in shuffled_points],
                    color=color, linestyle=":", linewidth=1.0,
                    label=f"{row['rf_mhz']:.0f} MHz shuffled",
                )
                axes[lane_index][1].loglog(
                    [x for x, _ in allan_points], [y for _, y in allan_points],
                    color=color, marker=".", linewidth=1.2,
                    label=f"{row['rf_mhz']:.0f} MHz",
                )
            axes[lane_index][0].set_ylabel(f"ADC{lane} fractional stddev")
            axes[lane_index][1].set_ylabel(f"ADC{lane} Allan deviation")
            for axis in axes[lane_index]:
                axis.grid(which="both", alpha=0.2)
                axis.legend(fontsize=6, ncol=2)
        axes[-1][0].set_xlabel("Integration time / s")
        axes[-1][1].set_xlabel("Allan averaging time / s")
        figure.suptitle(f"{run['name']} raw/shuffled integration and Allan deviation")
        figure.tight_layout()
        path = output / f"{run['name']}_integration_allan.png"
        figure.savefig(path, dpi=150)
        plt.close(figure)
        paths.append(str(path.resolve()))

        figure, axes = plt.subplots(2, 1, figsize=(12, 7), sharex=True)
        for axis, lane in zip(axes, LANES):
            for row in run["analysis"]["combinations"]:
                if row["lane"] == lane and row["clean"]:
                    acf = autocorrelation_curve(row["power_series"])
                    axis.plot(range(len(acf)), acf, linewidth=1.0, label=f"{row['rf_mhz']:.0f} MHz")
            axis.axhline(0.0, color="black", linewidth=0.6)
            axis.set_ylabel(f"ADC{lane} ACF")
            axis.grid(alpha=0.2)
            axis.legend(ncol=5, fontsize=7)
        axes[-1].set_xlabel("Lag / s")
        figure.suptitle(f"{run['name']} clean-bin temporal autocorrelation")
        figure.tight_layout()
        path = output / f"{run['name']}_acf.png"
        figure.savefig(path, dpi=150)
        plt.close(figure)
        paths.append(str(path.resolve()))

        figure, axes = plt.subplots(1, 2, figsize=(11, 4.8))
        for axis, lane in zip(axes, LANES):
            matrix = run["analysis"]["same_adc_frequency_correlation"][str(lane)]
            image = axis.imshow(matrix, vmin=-1.0, vmax=1.0, cmap="coolwarm")
            axis.set_xticks(range(6), [f"{value:.0f}" for value in RF_FREQUENCIES_MHZ], rotation=45)
            axis.set_yticks(range(6), [f"{value:.0f}" for value in RF_FREQUENCIES_MHZ])
            axis.set_title(f"ADC{lane}")
            axis.set_xlabel("RF / MHz")
            axis.set_ylabel("RF / MHz")
        figure.colorbar(image, ax=axes, label="Pearson correlation", shrink=0.85)
        figure.suptitle(f"{run['name']} cross-frequency correlation")
        figure.subplots_adjust(left=0.10, right=0.88, bottom=0.20, top=0.83, wspace=0.30)
        path = output / f"{run['name']}_frequency_correlation.png"
        figure.savefig(path, dpi=150)
        plt.close(figure)
        paths.append(str(path.resolve()))

        time_rows = list(run.get("time_statistics", []))
        if time_rows:
            figure, axis = plt.subplots(figsize=(12, 4.5))
            for lane in LANES:
                selected = sorted(
                    (row for row in time_rows if int(row["lane"]) == lane),
                    key=lambda row: int(row["second"]),
                )
                seconds = [int(row["second"]) for row in selected]
                rms_dbfs = [
                    20.0 * math.log10(
                        max(math.sqrt(float(row["sum_power"]) / int(row["sample_count"])), 1.0e-300)
                        / 32768.0
                    )
                    for row in selected
                    if int(row["sample_count"]) > 0
                ]
                axis.plot(seconds[:len(rms_dbfs)], rms_dbfs, linewidth=0.9, label=f"ADC{lane}")
            axis.set_xlabel("Time / s")
            axis.set_ylabel("TIME RMS / dBFS")
            axis.grid(alpha=0.2)
            axis.legend()
            axis.set_title(f"{run['name']} rotating-sample TIME RMS")
            figure.tight_layout()
            path = output / f"{run['name']}_time_rms.png"
            figure.savefig(path, dpi=150)
            plt.close(figure)
            paths.append(str(path.resolve()))

    environment_rows: list[dict[str, Any]] = []
    elapsed = 0
    for run in runs:
        trace_path = root / "runs" / run["name"] / "calibration_ams_trace.json"
        if not trace_path.is_file():
            continue
        trace = json.loads(trace_path.read_text())
        for row in trace:
            ams = row.get("resident", {}).get("ams") or {}
            environment_rows.append({"second": elapsed, "run": run["name"], "ams": ams})
            elapsed += 1
    if environment_rows:
        figure, axes = plt.subplots(2, 1, figsize=(14, 8), sharex=True)
        temperature_names = sorted({
            name for row in environment_rows for name in row["ams"].get("temperatures_c", {})
        })
        voltage_names = sorted({
            name for row in environment_rows for name in row["ams"].get("voltages_v", {})
        })
        for name in temperature_names:
            points = [
                (row["second"], row["ams"]["temperatures_c"][name]["mean"])
                for row in environment_rows if name in row["ams"].get("temperatures_c", {})
            ]
            axes[0].plot([x for x, _ in points], [y for _, y in points], linewidth=0.8, label=name)
        for name in voltage_names:
            points = [
                (row["second"], row["ams"]["voltages_v"][name]["mean"])
                for row in environment_rows if name in row["ams"].get("voltages_v", {})
            ]
            axes[1].plot([x for x, _ in points], [y for _, y in points], linewidth=0.8, label=name)
        axes[0].set_ylabel("Temperature / C")
        axes[1].set_ylabel("Voltage / V")
        axes[1].set_xlabel("Concatenated campaign time / s")
        for axis in axes:
            axis.grid(alpha=0.2)
            axis.legend(fontsize=7, ncol=4)
        figure.suptitle("Stage 34c AMS temperature and internal-rail telemetry")
        figure.tight_layout()
        path = output / "campaign_ams_temperature_voltage.png"
        figure.savefig(path, dpi=150)
        plt.close(figure)
        paths.append(str(path.resolve()))

    for snapshot_path in sorted(root.glob("runs/*/ocb1_snapshot.json")):
        snapshot = json.loads(snapshot_path.read_text())
        channels = snapshot.get("ocb1", {}).get("channels", [])
        if not channels:
            continue
        figure, axes = plt.subplots(1, 2, figsize=(12, 4.5))
        for channel in channels:
            adc = int(channel["adc"])
            axes[0].plot(range(8), channel["signed16"], marker="o", linewidth=0.9, label=f"ADC{adc}")
            axes[1].plot(
                [int(item["k"]) for item in channel["dft"]],
                [float(item["magnitude"]) for item in channel["dft"]],
                marker="o", linewidth=0.9, label=f"ADC{adc}",
            )
        axes[0].set_xlabel("OCB1 coefficient index")
        axes[0].set_ylabel("Signed coefficient / LSB")
        axes[1].set_xlabel("DFT k")
        axes[1].set_ylabel("DFT magnitude")
        for axis in axes:
            axis.grid(alpha=0.2)
            axis.legend(fontsize=7, ncol=2)
        figure.suptitle(f"{snapshot_path.parent.name} OCB1 snapshot and interleave DFT")
        figure.tight_layout()
        path = output / f"{snapshot_path.parent.name}_ocb1_coefficients_dft.png"
        figure.savefig(path, dpi=150)
        plt.close(figure)
        paths.append(str(path.resolve()))
    condition_summary = generate_ocb1_condition_summary_plot(root, runs)
    if condition_summary is not None:
        paths.append(condition_summary)
    return paths


def write_pcap_manifest(root: Path) -> dict[str, Any]:
    path = root / "pcap_manifest.sha256"
    lines = [f"{sha256_file(item)}  {item.relative_to(root)}" for item in sorted(root.rglob("*.pcap"))]
    path.write_text("\n".join(lines) + ("\n" if lines else ""))
    return {"path": str(path.resolve()), "sha256": sha256_file(path), "pcap_count": len(lines)}


def load_completed_run(root: Path, name: str) -> dict[str, Any]:
    path = root / "runs" / name / "result.json"
    if not path.exists():
        raise RuntimeError(f"resume evidence missing: {path}")
    row = json.loads(path.read_text())
    if not row.get("ok") or row.get("classification") != "STAGE34C_RUN_COMPLETE":
        raise RuntimeError(f"resume evidence is not a completed run: {path}")
    return row


def execute_ocb1_triplet(
    args: argparse.Namespace,
    template: dict[str, Any],
    triplet: dict[str, Any],
    state: dict[str, Any],
    campaign_path: Path,
) -> list[dict[str, Any]]:
    rate = int(triplet["sample_rate_msps"])
    prefix = str(triplet["prefix"])
    a1 = execute_run(
        args,
        template,
        name=f"{prefix}_a1_dynamic",
        sample_rate_msps=rate,
        mode="spec_only",
        condition="A1_DYNAMIC",
        fresh_configure=True,
    )
    state["completed_runs"].append(
        str((args.receiver_output / "runs" / a1["name"] / "result.json").resolve())
    )
    transaction_id, snapshot_hash, snapshot = snapshot_ocb1(args)
    write_json(
        args.receiver_output / "runs" / a1["name"] / "ocb1_snapshot.json",
        snapshot,
    )
    b = execute_run(
        args,
        template,
        name=f"{prefix}_b_ocb1_snapshot",
        sample_rate_msps=rate,
        mode="spec_only",
        condition="B_OCB1_SNAPSHOT",
        fresh_configure=False,
        ocb1_transaction_id=transaction_id,
        expected_ocb1_hash=snapshot_hash,
    )
    state["completed_runs"].append(
        str((args.receiver_output / "runs" / b["name"] / "result.json").resolve())
    )
    release = release_ocb1(args, transaction_id)
    write_json(
        args.receiver_output / "runs" / b["name"] / "ocb1_release.json",
        release,
    )
    a2 = execute_run(
        args,
        template,
        name=f"{prefix}_a2_restored",
        sample_rate_msps=rate,
        mode="spec_only",
        condition="A2_RESTORED",
        fresh_configure=True,
    )
    triplet_gate = triplet_temperature_gate(a1, b, a2)
    a2["triplet_temperature_gate"] = triplet_gate
    write_json(args.receiver_output / "runs" / a2["name"] / "result.json", a2)
    if not triplet_gate["pass"]:
        raise RuntimeError(
            "triplet temperature span exceeded "
            f"{TEMPERATURE_HARD_FILTERED_SPAN_C:.1f} C: "
            f"{triplet_gate['sensors']}"
        )
    if triplet_gate["warning"]:
        state.setdefault("temperature_warnings", []).append(
            {"triplet": prefix, "gate": triplet_gate}
        )
    state["completed_runs"].append(
        str((args.receiver_output / "runs" / a2["name"] / "result.json").resolve())
    )
    write_json(campaign_path, state)
    return [a1, b, a2]


def resume_ocb1_campaign(
    args: argparse.Namespace,
    template: dict[str, Any],
    start_triplet: int,
) -> int:
    campaign_path = args.receiver_output / "campaign.json"
    if not 1 <= start_triplet <= len(ocb1_triplet_plan()):
        raise RuntimeError(f"invalid OCB1 resume triplet {start_triplet}")
    state = json.loads(campaign_path.read_text())
    if state.get("classification") != "STAGE34C_OPERATIONAL_FAIL" or not any(
        "temperature span exceeded" in str(error) for error in state.get("errors", [])
    ):
        raise RuntimeError("resume is allowed only after the recorded temperature-gate stop")

    c0_rows = [
        load_completed_run(
            args.receiver_output,
            f"c0_{index:02d}_{rate}msps_r{repeat}_dynamic",
        )
        for index, (rate, repeat) in enumerate(C0_ORDER, start=1)
    ]
    localization = load_completed_run(
        args.receiver_output, "c0_localization_160msps_time_spec"
    )
    completed_ocb_rows = []
    for triplet in ocb1_triplet_plan():
        if int(triplet["triplet_index"]) >= start_triplet:
            break
        prefix = str(triplet["prefix"])
        completed_ocb_rows.extend(
            load_completed_run(args.receiver_output, f"{prefix}_{suffix}")
            for suffix in ("a1_dynamic", "b_ocb1_snapshot", "a2_restored")
        )

    original_board = fullband._http_json(
        args.agent_base.rstrip("/") + "/api/v2/status", timeout=30.0
    )
    original_receiver = fullband._http_json(
        args.receiver_base.rstrip("/") + "/api/state"
    )
    if original_board.get("streaming") or original_board.get("pipeline", {}).get(
        "stream_accepting"
    ):
        raise RuntimeError("resume requires streaming=false")
    if int(original_board.get("dac", {}).get("enable_mask", -1)) != 0:
        raise RuntimeError("resume requires DAC mask=0")
    ocb1 = original_board.get("rfdc", {}).get("ocb1", {})
    if (
        int(ocb1.get("ocb1_override_adc_mask", -1)) != 0
        or ocb1.get("ocb1_override_state") != "DYNAMIC"
    ):
        raise RuntimeError(f"resume requires dynamic OCB1: {ocb1}")

    old_errors = list(state.get("errors", []))
    state.update(
        {
            "classification": "STAGE34C_IN_PROGRESS",
            "operational_ok": False,
            "scientific_pass": False,
            "errors": [],
            "stage34c1": None,
            "resume_started_at_unix_ms": time.time_ns() // 1_000_000,
            "temperature_policy": {
                "original_limit_c": TEMPERATURE_WARNING_FILTERED_SPAN_C,
                "hard_limit_c": TEMPERATURE_HARD_FILTERED_SPAN_C,
                "reason": "USER_APPROVED_MINIMAL_RELAXATION_AFTER_2P011C_STOP",
            },
            "completed_runs": [
                str(
                    (
                        args.receiver_output
                        / "runs"
                        / row["name"]
                        / "result.json"
                    ).resolve()
                )
                for row in [*c0_rows, localization, *completed_ocb_rows]
            ],
        }
    )
    state.pop("finished_at_unix_ms", None)
    state.setdefault("continuations", []).append(
        {
            "start_triplet": start_triplet,
            "superseded_errors": old_errors,
            "rerun_complete_triplet": True,
            "reason": "AMBIENT_TEMPERATURE_BASELINE_CHANGED",
        }
    )
    write_json(campaign_path, state)

    ocb_rows = list(completed_ocb_rows)
    try:
        for triplet in ocb1_triplet_plan():
            if int(triplet["triplet_index"]) < start_triplet:
                continue
            print(
                "STAGE34C1_RESUME_TRIPLET_START "
                f"{triplet['triplet_index']}/6 {triplet['prefix']}",
                flush=True,
            )
            ocb_rows.extend(
                execute_ocb1_triplet(args, template, triplet, state, campaign_path)
            )
            print(
                f"STAGE34C1_RESUME_TRIPLET_COMPLETE {triplet['prefix']}",
                flush=True,
            )
        state["stage34c1"] = aggregate_ocb1(ocb_rows)
        state["classification"] = state["stage34c1"]["classification"]
        state["scientific_pass"] = bool(state["stage34c1"]["pass"])
        all_rows = [*c0_rows, localization, *ocb_rows]
        write_summary_csv(args.receiver_output / "summary.csv", all_rows)
        state["plots"] = generate_plots(args.receiver_output, all_rows)
        state["pcap_manifest"] = write_pcap_manifest(args.receiver_output)
        state["operational_ok"] = True
    except Exception as exc:
        state["errors"].append(f"{type(exc).__name__}: {exc}")
        state["classification"] = "STAGE34C_OPERATIONAL_FAIL"
    finally:
        state["errors"].extend(
            safe_finalize(args, template, original_board, original_receiver)
        )
        state["finished_at_unix_ms"] = time.time_ns() // 1_000_000
        if state["errors"]:
            state["operational_ok"] = False
            state["scientific_pass"] = False
            state["classification"] = "STAGE34C_OPERATIONAL_FAIL"
        write_json(campaign_path, state)
        write_json(
            args.board_output / "campaign_summary.json",
            {
                "classification": state["classification"],
                "operational_ok": state["operational_ok"],
                "scientific_pass": state["scientific_pass"],
                "campaign_path": str(campaign_path),
                "campaign_sha256": sha256_file(campaign_path),
                "completed_run_count": len(state["completed_runs"]),
                "errors": state["errors"],
            },
        )
    print(
        json.dumps(
            {
                "classification": state["classification"],
                "operational_ok": state["operational_ok"],
                "scientific_pass": state["scientific_pass"],
                "completed_run_count": len(state["completed_runs"]),
                "errors": state["errors"],
            },
            indent=2,
        ),
        flush=True,
    )
    return (
        0
        if state["operational_ok"]
        and state["classification"] in SCIENTIFIC_EXIT_CLASSIFICATIONS
        else 1
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent-base", default="http://192.168.100.117:8010")
    parser.add_argument("--receiver-base", default="http://192.168.100.162:8089")
    parser.add_argument("--configure-template", type=Path, default=Path("config/t510/configure_320_time_only.example.json"))
    parser.add_argument("--receiver-output", type=Path, default=Path("build/receiver/latest/evidence/adc_correlated_noise_root_cause"))
    parser.add_argument("--board-output", type=Path, default=Path("build/board/latest/evidence/adc_correlated_noise_root_cause"))
    parser.add_argument("--settle-seconds", type=float, default=2.0)
    parser.add_argument("--ssa-confirmed", action="store_true")
    parser.add_argument("--resume-ocb1-from-triplet", type=int)
    args = parser.parse_args()
    args.receiver_output = args.receiver_output.resolve()
    args.board_output = args.board_output.resolve()
    if not args.ssa_confirmed:
        parser.error("--ssa-confirmed is required for the fixed SSA TG-off/preamp-off/20 dB setup")
    campaign_path = args.receiver_output / "campaign.json"
    template = json.loads(args.configure_template.read_text())
    if args.resume_ocb1_from_triplet is not None:
        if not campaign_path.exists():
            raise RuntimeError(f"resume campaign is missing: {campaign_path}")
        return resume_ocb1_campaign(args, template, args.resume_ocb1_from_triplet)
    if campaign_path.exists():
        raise RuntimeError(f"refusing to overwrite existing Stage 34c campaign {campaign_path}")
    args.receiver_output.mkdir(parents=True, exist_ok=True)
    args.board_output.mkdir(parents=True, exist_ok=True)
    original_board = None
    original_receiver = None
    state: dict[str, Any] = {
        "classification": "STAGE34C_IN_PROGRESS",
        "operational_ok": False,
        "scientific_pass": False,
        "core_version": CORE_VERSION,
        "bitstream_sha256": BITSTREAM_SHA256,
        "pfb_profile_id": PFB_PROFILE_ID,
        "physical_setup": {
            "classification": "SHARED_50OHM_REFERENCE",
            "path": "SSA RF INPUT -> two-way splitter -> ADC0/ADC2",
            "ssa_powered": True,
            "tg_enabled": False,
            "preamp_enabled": False,
            "input_attenuation_db": 20,
            "other_adc_physically_disconnected": True,
            "all_dac_physically_disconnected": True,
        },
        "completed_runs": [],
        "errors": [],
        "started_at_unix_ms": time.time_ns() // 1_000_000,
    }
    write_json(campaign_path, state)
    try:
        original_board = fullband._http_json(args.agent_base.rstrip("/") + "/api/v2/status", timeout=30.0)
        original_receiver = fullband._http_json(args.receiver_base.rstrip("/") + "/api/state")
        if original_board.get("streaming") or original_board.get("pipeline", {}).get("stream_accepting"):
            raise RuntimeError("campaign preflight requires streaming=false")
        state["original_board"] = original_board
        state["original_receiver"] = original_receiver.get("config")
        state["preview_preflight"] = preview_preflight(args, template)
        state["monitor_performance_preflight"] = monitor_performance_preflight(args, template)
        write_json(campaign_path, state)

        c0_rows = []
        for index, (rate, repeat) in enumerate(C0_ORDER, start=1):
            name = f"c0_{index:02d}_{rate}msps_r{repeat}_dynamic"
            print(f"STAGE34C0_RUN_START {index}/6 {name}", flush=True)
            row = execute_run(
                args, template, name=name, sample_rate_msps=rate, mode="spec_only",
                condition="C0_DYNAMIC", fresh_configure=True,
            )
            c0_rows.append(row)
            state["completed_runs"].append(str((args.receiver_output / "runs" / name / "result.json").resolve()))
            write_json(campaign_path, state)
            print(f"STAGE34C0_RUN_COMPLETE {name}", flush=True)
        state["stage34c0"] = aggregate_c0(c0_rows)
        write_json(campaign_path, state)
        all_rows = list(c0_rows)

        if state["stage34c0"]["pass"]:
            state["classification"] = state["stage34c0"]["classification"]
            state["scientific_pass"] = True
        else:
            localization = execute_run(
                args, template, name="c0_localization_160msps_time_spec",
                sample_rate_msps=160, mode="time_spec", condition="TIME_SPEC_LOCALIZATION",
                fresh_configure=True,
            )
            all_rows.append(localization)
            state["completed_runs"].append(str((args.receiver_output / "runs" / localization["name"] / "result.json").resolve()))
            write_json(campaign_path, state)

            ocb_rows = []
            for triplet in ocb1_triplet_plan():
                ocb_rows.extend(
                    execute_ocb1_triplet(
                        args, template, triplet, state, campaign_path
                    )
                )
            state["stage34c1"] = aggregate_ocb1(ocb_rows)
            state["classification"] = state["stage34c1"]["classification"]
            state["scientific_pass"] = bool(state["stage34c1"]["pass"])
            all_rows.extend(ocb_rows)

        write_summary_csv(args.receiver_output / "summary.csv", all_rows)
        state["plots"] = generate_plots(args.receiver_output, all_rows)
        state["pcap_manifest"] = write_pcap_manifest(args.receiver_output)
        state["operational_ok"] = True
    except Exception as exc:
        state["errors"].append(f"{type(exc).__name__}: {exc}")
        state["classification"] = "STAGE34C_OPERATIONAL_FAIL"
    finally:
        state["errors"].extend(
            safe_finalize(args, template, original_board, original_receiver)
        )
        state["finished_at_unix_ms"] = time.time_ns() // 1_000_000
        if state["errors"]:
            state["operational_ok"] = False
            state["scientific_pass"] = False
            state["classification"] = "STAGE34C_OPERATIONAL_FAIL"
        write_json(campaign_path, state)
        board_summary = {
            "classification": state["classification"],
            "operational_ok": state["operational_ok"],
            "scientific_pass": state["scientific_pass"],
            "campaign_path": str(campaign_path),
            "campaign_sha256": sha256_file(campaign_path),
            "completed_run_count": len(state["completed_runs"]),
            "errors": state["errors"],
        }
        write_json(args.board_output / "campaign_summary.json", board_summary)
    print(json.dumps({
        "classification": state["classification"],
        "operational_ok": state["operational_ok"],
        "scientific_pass": state["scientific_pass"],
        "completed_run_count": len(state["completed_runs"]),
        "errors": state["errors"],
    }, indent=2), flush=True)
    # A scientifically negative result is a completed experiment, not a crash.
    return 0 if state["operational_ok"] and state["classification"] in SCIENTIFIC_EXIT_CLASSIFICATIONS else 1


if __name__ == "__main__":
    raise SystemExit(main())
