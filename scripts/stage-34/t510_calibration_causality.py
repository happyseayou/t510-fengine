#!/usr/bin/env python3
"""Run the gated Stage 34b-2 RFDC training-freeze A/B/C experiment."""

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
CENTER_MHZ = 740.0
TONE_MHZ = 800.0
SAFE_RF_MHZ = (681.25, 703.75, 726.25, 751.25, 771.25, 792.5)
AMPLITUDE_SCAN_PERCENT = (25.0, 50.0, 75.0, 100.0)
OFFICIAL_MIN_DBFS = -40.0
ENGINEERING_MIN_DBFS = -36.0
ENGINEERING_MAX_DBFS = -8.0
PEAK_MAX_DBFS = -1.0
FORMAL_DURATION_SECONDS = 600
PACKETS_PER_BLOCK = 32
RATES_MSPS = (160, 320)
CONDITIONS = ("A", "B", "C")
BALANCED_ORDERS = (("A", "B", "C"), ("B", "C", "A"), ("C", "A", "B"))


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


def campaign_runs() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for sample_rate_msps in RATES_MSPS:
        for repeat, order in enumerate(BALANCED_ORDERS, start=1):
            for position, condition in enumerate(order, start=1):
                rows.append(
                    {
                        "index": len(rows),
                        "sample_rate_msps": sample_rate_msps,
                        "repeat": repeat,
                        "position": position,
                        "condition": condition,
                    }
                )
    return rows


def training_request(amplitude_percent: float) -> dict[str, Any]:
    return {
        "expected_board_id": 1,
        "training_dac_active": True,
        "training_amplitude_percent": float(amplitude_percent),
    }


def calibration_request() -> dict[str, Any]:
    return {"expected_board_id": 1}


def dac_body(amplitude_percent: float, center_mhz: float = CENTER_MHZ) -> dict[str, Any]:
    return fullband._dac_body(
        center_mhz,
        center_mhz + 60.0 if amplitude_percent > 0.0 else None,
        float(amplitude_percent),
        expected_board_id=1,
    )


def receiver_prepare(
    receiver_base: str,
    sample_rate_msps: int,
    center_mhz: float = CENTER_MHZ,
) -> dict[str, Any]:
    return performance.receiver_prepare(
        receiver_base,
        sample_rate_msps,
        center_mhz,
    )


def configure(
    agent_base: str,
    template: dict[str, Any],
    sample_rate_msps: int,
    center_mhz: float = CENTER_MHZ,
) -> dict[str, Any]:
    return fullband._http_json(
        agent_base.rstrip("/") + "/api/v2/configure",
        method="POST",
        body=performance.configure_body(template, sample_rate_msps, center_mhz),
        timeout=190.0,
    )


def set_dac(
    agent_base: str,
    amplitude_percent: float,
    center_mhz: float = CENTER_MHZ,
) -> dict[str, Any]:
    return fullband._http_json(
        agent_base.rstrip("/") + "/api/v2/dac",
        method="PUT",
        body=dac_body(amplitude_percent, center_mhz),
    )


def stop_mute_unfreeze(
    agent_base: str,
    center_mhz: float = CENTER_MHZ,
) -> list[str]:
    errors = performance.stop_and_mute(agent_base, center_mhz)
    try:
        fullband._http_json(
            agent_base.rstrip("/") + "/api/v2/rfdc/calibration/unfreeze",
            method="POST",
            body=calibration_request(),
            timeout=30.0,
        )
    except Exception as exc:  # noqa: BLE001 - preserve every cleanup failure
        errors.append(f"FINAL_UNFREEZE_FAILED: {type(exc).__name__}: {exc}")
    return errors


def level_pass(channel: dict[str, Any]) -> bool:
    return bool(
        not channel.get("clipped", False)
        and ENGINEERING_MIN_DBFS
        <= float(channel["rms_dbfs"])
        <= ENGINEERING_MAX_DBFS
        and float(channel["peak_dbfs"]) < PEAK_MAX_DBFS
    )


def run_amplitude_preflight(
    args: argparse.Namespace,
    template: dict[str, Any],
) -> dict[str, Any]:
    output = args.board_output.resolve() / "34b2"
    path = output / "amplitude_preflight_pg269.json"
    if path.exists():
        previous = json.loads(path.read_text())
        if previous.get("classification") == "T510_STAGE34B2_AMPLITUDE_PREFLIGHT_PASS":
            return previous
        raise RuntimeError(f"refusing to overwrite failed preflight {path}")
    evidence: dict[str, Any] = {
        "classification": "T510_STAGE34B2_AMPLITUDE_PREFLIGHT_IN_PROGRESS",
        "ok": False,
        "core_version": CORE_VERSION,
        "bitstream_sha256": BITSTREAM_SHA256,
        "center_mhz": CENTER_MHZ,
        "tone_mhz": TONE_MHZ,
        "official_source": "AMD PG269 GCB/TSCB minimum input power",
        "official_min_dbfs": OFFICIAL_MIN_DBFS,
        "engineering_window_dbfs": [ENGINEERING_MIN_DBFS, ENGINEERING_MAX_DBFS],
        "peak_max_dbfs": PEAK_MAX_DBFS,
        "amplitudes_percent": list(AMPLITUDE_SCAN_PERCENT),
        "measurements": [],
        "errors": [],
        "started_unix_ms": time.time_ns() // 1_000_000,
    }
    write_json(path, evidence)
    try:
        receiver_prepare(args.receiver_base, 320)
        configure(args.agent_base, template, 320)
        fullband._http_json(
            args.agent_base.rstrip("/") + "/api/v2/rfdc/calibration/unfreeze",
            method="POST",
            body=calibration_request(),
        )
        for amplitude in AMPLITUDE_SCAN_PERCENT:
            print(f"CALIBRATION_AMPLITUDE_PREFLIGHT amplitude={amplitude:.0f}%", flush=True)
            set_dac(args.agent_base, amplitude)
            time.sleep(1.0)
            preview = fullband._http_json(
                args.agent_base.rstrip("/") + "/api/v2/rfdc/calibration/preview",
                method="POST",
                body=training_request(amplitude),
                timeout=30.0,
            )
            channels = list(preview.get("channels", []))
            if len(channels) != 8:
                raise RuntimeError(f"preview returned {len(channels)} channels")
            evidence["measurements"].append(
                {
                    "amplitude_percent": amplitude,
                    "channels": channels,
                    "all_eight_level_pass": all(level_pass(row) for row in channels),
                    "preview": {
                        key: preview.get(key)
                        for key in (
                            "science_udp_stopped",
                            "sample0",
                            "sample_rate_hz",
                            "dry_run",
                        )
                    },
                }
            )
            write_json(path, evidence)

        baseline = evidence["measurements"][0]
        linearity = []
        for measurement in evidence["measurements"][1:]:
            expected_delta = 20.0 * math.log10(
                float(measurement["amplitude_percent"])
                / float(baseline["amplitude_percent"])
            )
            for lane, (base, current) in enumerate(
                zip(baseline["channels"], measurement["channels"])
            ):
                observed_delta = float(current["rms_dbfs"]) - float(base["rms_dbfs"])
                linearity.append(
                    {
                        "lane": lane,
                        "from_percent": baseline["amplitude_percent"],
                        "to_percent": measurement["amplitude_percent"],
                        "expected_delta_db": expected_delta,
                        "observed_delta_db": observed_delta,
                        "error_db": observed_delta - expected_delta,
                    }
                )
        evidence["linearity"] = linearity
        if any(abs(float(row["error_db"])) > 1.5 for row in linearity):
            raise RuntimeError("DAC amplitude scan is not linear within 1.5 dB on all eight lanes")
        eligible = [
            float(row["amplitude_percent"])
            for row in evidence["measurements"]
            if row["all_eight_level_pass"]
        ]
        if not eligible:
            raise RuntimeError(
                "no DAC amplitude gives all eight ADCs the -36..-8 dBFS training window"
            )
        selected = min(eligible)
        evidence["selected_amplitude_percent"] = selected
        set_dac(args.agent_base, selected)
        trained = fullband._http_json(
            args.agent_base.rstrip("/") + "/api/v2/rfdc/calibration/train-freeze",
            method="POST",
            body=training_request(selected),
            timeout=50.0,
        )
        evidence["train_freeze_proof"] = trained
        time.sleep(2.2)
        resident = fullband._http_json(
            args.agent_base.rstrip("/") + "/api/v2/rfdc/calibration/monitor"
        )
        calibration = resident.get("calibration", {})
        if int(calibration.get("frozen_adc_mask", 0)) != 0xFF:
            raise RuntimeError(f"resident monitor did not read freeze mask 0xff: {resident}")
        evidence["resident_monitor_proof"] = resident
        evidence["ok"] = True
        evidence["classification"] = "T510_STAGE34B2_AMPLITUDE_PREFLIGHT_PASS"
    except Exception as exc:  # noqa: BLE001 - preflight is fail-closed
        evidence["errors"].append(f"{type(exc).__name__}: {exc}")
        evidence["classification"] = "T510_STAGE34B2_AMPLITUDE_PREFLIGHT_FAIL"
    finally:
        evidence["errors"].extend(stop_mute_unfreeze(args.agent_base))
        evidence["finished_unix_ms"] = time.time_ns() // 1_000_000
        if evidence["errors"]:
            evidence["ok"] = False
            evidence["classification"] = "T510_STAGE34B2_AMPLITUDE_PREFLIGHT_FAIL"
        write_json(path, evidence)
    return evidence


def correlation(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or len(left) < 2:
        raise ValueError("correlation inputs must have equal length >=2")
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
        grouped.setdefault((int(row["lane"]), int(row["target_index"])), []).append(row)
    combinations = []
    series: dict[tuple[int, int], list[float]] = {}
    for (lane, target_index), rows in sorted(grouped.items()):
        rows.sort(key=lambda row: int(row["second"]))
        powers = [astronomy.mean_power_from_accumulator(row) for row in rows]
        if len(powers) < FORMAL_DURATION_SECONDS - 2:
            raise RuntimeError(
                f"lane {lane} target {target_index} has only {len(powers)} seconds"
            )
        series[(lane, target_index)] = powers
        raw_stats = astronomy.integration_statistics(powers)
        shuffled = list(powers)
        random.Random(seed ^ (lane << 16) ^ target_index).shuffle(shuffled)
        shuffled_stats = astronomy.integration_statistics(shuffled)
        lag1 = correlation(powers[:-1], powers[1:])
        slope = float(raw_stats["slope"])
        combinations.append(
            {
                "lane": lane,
                "target_index": target_index,
                "rf_mhz": float(targets[target_index]["actual_rf_mhz"]),
                "seconds": len(powers),
                "slope": slope,
                "shuffled_slope": float(shuffled_stats["slope"]),
                "slope_pass": -0.65 <= slope <= -0.35,
                "lag1_correlation": lag1,
                "mean_dbfs": float(raw_stats["mean_dbfs"]),
                "curve": raw_stats["curve"],
                "shuffled_curve": shuffled_stats["curve"],
            }
        )
    if len(combinations) != 48:
        raise RuntimeError(f"monitor produced {len(combinations)} combinations, expected 48")

    same_adc_different_rf = {}
    for lane in range(8):
        same_adc_different_rf[str(lane)] = [
            [correlation(series[(lane, left)], series[(lane, right)]) for right in range(6)]
            for left in range(6)
        ]
    different_adc_same_rf = {}
    for target_index in range(6):
        different_adc_same_rf[str(target_index)] = [
            [correlation(series[(left, target_index)], series[(right, target_index)]) for right in range(8)]
            for left in range(8)
        ]
    return {
        "combinations": combinations,
        "slope_pass_count": sum(int(row["slope_pass"]) for row in combinations),
        "slope_pass_fraction": statistics.fmean(int(row["slope_pass"]) for row in combinations),
        "median_slope": statistics.median(float(row["slope"]) for row in combinations),
        "median_shuffled_slope": statistics.median(
            float(row["shuffled_slope"]) for row in combinations
        ),
        "median_abs_lag1": statistics.median(
            abs(float(row["lag1_correlation"])) for row in combinations
        ),
        "same_adc_different_rf_correlation": same_adc_different_rf,
        "different_adc_same_rf_correlation": different_adc_same_rf,
    }


def condensed_receiver_state(state: dict[str, Any]) -> dict[str, Any]:
    stats = state.get("stats", {})
    keys = (
        "gbps",
        "packets_per_sec",
        "spec_processed_packets_per_sec",
        "kernel_drops",
        "ring_drops",
        "worker_ring_drops",
        "app_drops",
        "parse_errors",
        "seq_gaps",
        "frame_gaps",
        "sample0_gaps",
        "spec_seq_gaps",
        "spec_frame_gaps",
        "nic_rx_errors_delta",
        "nic_rx_dropped_delta",
        "nic_rx_missed_errors_delta",
    )
    return {
        "captured_at_unix_ms": time.time_ns() // 1_000_000,
        **{key: stats.get(key) for key in keys},
    }


def resident_observation_age_ms(captured_at_unix_ms: int, now_unix_ms: int) -> int:
    """Validate freshness while allowing small inter-host wall-clock skew."""

    age_ms = int(now_unix_ms) - int(captured_at_unix_ms)
    if age_ms < -1000 or age_ms > 2500:
        raise RuntimeError(f"resident calibration observation is stale by {age_ms} ms")
    return age_ms


def wait_for_monitor(
    args: argparse.Namespace,
    *,
    expected_frozen_mask: int,
    trace_path: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    deadline = time.monotonic() + FORMAL_DURATION_SECONDS + 45.0
    observations: list[dict[str, Any]] = []
    last_calibration_timestamp: int | None = None
    while time.monotonic() < deadline:
        status = fullband._http_json(
            args.receiver_base.rstrip("/") + "/api/measure/spec-stability/status"
        )
        resident = fullband._http_json(
            args.agent_base.rstrip("/") + "/api/v2/rfdc/calibration/monitor"
        )
        calibration = resident.get("calibration", {})
        captured = int(calibration.get("captured_at_unix_ms", 0) or 0)
        age_ms = resident_observation_age_ms(
            captured,
            time.time_ns() // 1_000_000,
        )
        if not calibration.get("supported") or calibration.get("error"):
            raise RuntimeError(f"resident calibration observation failed: {calibration}")
        if int(calibration.get("frozen_adc_mask", -1)) != expected_frozen_mask:
            raise RuntimeError(
                f"freeze mask changed: expected 0x{expected_frozen_mask:02x}, "
                f"read 0x{int(calibration.get('frozen_adc_mask', -1)) & 0xff:02x}"
            )
        if captured != last_calibration_timestamp:
            observations.append(
                {
                    "elapsed_seconds": len(observations),
                    "resident": resident,
                    "receiver": condensed_receiver_state(
                        fullband._http_json(args.receiver_base.rstrip("/") + "/api/state")
                    ),
                }
            )
            last_calibration_timestamp = captured
            write_json(trace_path, observations)
        if status.get("status") == "completed":
            result = fullband._http_json(
                args.receiver_base.rstrip("/") + "/api/measure/spec-stability/result",
                timeout=120.0,
            )
            if len(observations) < FORMAL_DURATION_SECONDS - 5:
                raise RuntimeError(
                    f"only {len(observations)} unique one-second calibration observations"
                )
            return result, observations
        if status.get("status") == "failed":
            raise RuntimeError(f"SPEC monitor failed: {status.get('error')}")
        time.sleep(0.5)
    raise RuntimeError("SPEC monitor did not complete before its deadline")


def validate_calibration_trace(
    observations: list[dict[str, Any]],
    *,
    expected_mask: int,
    require_stable_hashes: bool,
) -> dict[str, Any]:
    calibrations = [row["resident"]["calibration"] for row in observations]
    masks = {int(row["frozen_adc_mask"]) for row in calibrations}
    gcb = {str(row["coefficient_sha256"]["gcb"]) for row in calibrations}
    tscb = {str(row["coefficient_sha256"]["tscb"]) for row in calibrations}
    result = {
        "samples": len(calibrations),
        "frozen_masks": sorted(masks),
        "gcb_unique_hashes": len(gcb),
        "tscb_unique_hashes": len(tscb),
        "temperature_c": [row.get("temperature_c") for row in calibrations],
    }
    if masks != {expected_mask}:
        raise RuntimeError(f"calibration trace masks are {masks}, expected {expected_mask}")
    if require_stable_hashes and (len(gcb) != 1 or len(tscb) != 1):
        raise RuntimeError(
            f"frozen GCB/TSCB hashes changed: gcb={len(gcb)} tscb={len(tscb)}"
        )
    return result


def execute_run(
    args: argparse.Namespace,
    template: dict[str, Any],
    run: dict[str, Any],
    selected_amplitude: float,
    *,
    center_mhz: float = CENTER_MHZ,
    rf_frequencies_mhz: tuple[float, ...] = SAFE_RF_MHZ,
    evidence_scope: str = "34b2",
) -> dict[str, Any]:
    rate = int(run["sample_rate_msps"])
    condition = str(run["condition"])
    run_name = str(
        run.get("name")
        or f"{run['index'] + 1:02d}_{rate}msps_r{run['repeat']}_{condition}"
    )
    run_dir = args.receiver_output.resolve() / evidence_scope / "runs" / run_name
    run_dir.mkdir(parents=True, exist_ok=False)
    evidence: dict[str, Any] = {
        **run,
        "name": run_name,
        "ok": False,
        "classification": "T510_STAGE34B2_RUN_IN_PROGRESS",
        "selected_amplitude_percent": selected_amplitude,
        "center_mhz": center_mhz,
        "rf_frequencies_mhz": list(rf_frequencies_mhz),
        "started_unix_ms": time.time_ns() // 1_000_000,
        "errors": [],
    }
    write_json(run_dir / "result.json", evidence)
    try:
        receiver_prepare(args.receiver_base, rate, center_mhz)
        evidence["configure"] = configure(args.agent_base, template, rate, center_mhz)
        if condition == "A":
            evidence["calibration_action"] = fullband._http_json(
                args.agent_base.rstrip("/") + "/api/v2/rfdc/calibration/unfreeze",
                method="POST",
                body=calibration_request(),
            )
            expected_mask = 0
        elif condition == "B":
            set_dac(args.agent_base, selected_amplitude, center_mhz)
            evidence["calibration_action"] = fullband._http_json(
                args.agent_base.rstrip("/") + "/api/v2/rfdc/calibration/train-freeze",
                method="POST",
                body=training_request(selected_amplitude),
                timeout=50.0,
            )
            expected_mask = 0xFF
            time.sleep(5.0)
        elif condition == "C":
            evidence["calibration_action"] = fullband._http_json(
                args.agent_base.rstrip("/") + "/api/v2/rfdc/calibration/freeze",
                method="POST",
                body=calibration_request(),
            )
            expected_mask = 0xFF
        else:  # pragma: no cover - campaign_runs fixes this
            raise RuntimeError(f"unknown condition {condition}")

        fullband._http_json(
            args.agent_base.rstrip("/") + "/api/v2/start",
            method="POST",
            body={"expected_board_id": 1},
        )
        time.sleep(args.settle_seconds)
        before_board = fullband._http_json(
            args.agent_base.rstrip("/") + "/api/v2/status",
            timeout=30.0,
        )
        before_receiver = fullband._http_json(
            args.receiver_base.rstrip("/") + "/api/state"
        )
        performance.validate_board_status(before_board, rate, center_mhz)
        begin_paths, begin_capture = fullband.capture_receiver_pcap(
            receiver_base=args.receiver_base,
            local_dir=run_dir / "raw" / "begin",
            packets_per_block=PACKETS_PER_BLOCK,
        )
        begin_decoded = performance.decode_window(begin_paths, rate)
        monitor_request = {
            "duration_seconds": FORMAL_DURATION_SECONDS,
            "sample_rate_msps": rate,
            "center_mhz": center_mhz,
            "rf_frequencies_mhz": list(rf_frequencies_mhz),
        }
        evidence["monitor_start"] = fullband._http_json(
            args.receiver_base.rstrip("/") + "/api/measure/spec-stability",
            method="POST",
            body=monitor_request,
        )
        monitor_raw, calibration_observations = wait_for_monitor(
            args,
            expected_frozen_mask=expected_mask,
            trace_path=run_dir / "calibration_trace.json",
        )
        write_json(run_dir / "monitor_raw.json", monitor_raw)
        end_paths, end_capture = fullband.capture_receiver_pcap(
            receiver_base=args.receiver_base,
            local_dir=run_dir / "raw" / "end",
            packets_per_block=PACKETS_PER_BLOCK,
        )
        end_decoded = performance.decode_window(end_paths, rate)
        after_board = fullband._http_json(
            args.agent_base.rstrip("/") + "/api/v2/status",
            timeout=30.0,
        )
        after_receiver = fullband._http_json(
            args.receiver_base.rstrip("/") + "/api/state"
        )
        performance.validate_board_status(after_board, rate, center_mhz)
        integrity = fullband._window_integrity(
            before_board,
            after_board,
            before_receiver,
            after_receiver,
        )
        if not integrity["ok"]:
            raise RuntimeError(f"digital integrity failed: {integrity['errors']}")
        analysis = analyze_monitor(
            monitor_raw,
            seed=0x34B20000 ^ int(run["index"]),
        )
        calibration_trace = validate_calibration_trace(
            calibration_observations,
            expected_mask=expected_mask,
            require_stable_hashes=condition in ("B", "C"),
        )
        evidence.update(
            {
                "ok": True,
                "classification": "T510_STAGE34B2_RUN_COMPLETE",
                "before_board": before_board,
                "after_board": after_board,
                "before_receiver": condensed_receiver_state(before_receiver),
                "after_receiver": condensed_receiver_state(after_receiver),
                "integrity": integrity,
                "calibration_trace_summary": calibration_trace,
                "analysis": analysis,
                "begin_capture": {**begin_capture, "decoded": begin_decoded["capture"]},
                "end_capture": {**end_capture, "decoded": end_decoded["capture"]},
            }
        )
    except Exception as exc:  # noqa: BLE001 - any run failure stops the queue
        evidence["errors"].append(f"{type(exc).__name__}: {exc}")
        evidence["classification"] = "T510_STAGE34B2_RUN_FAIL"
        raise
    finally:
        evidence["errors"].extend(stop_mute_unfreeze(args.agent_base, center_mhz))
        evidence["finished_unix_ms"] = time.time_ns() // 1_000_000
        if evidence["errors"]:
            evidence["ok"] = False
            evidence["classification"] = "T510_STAGE34B2_RUN_FAIL"
        write_json(run_dir / "result.json", evidence)
    return evidence


def aggregate_gate(runs: list[dict[str, Any]]) -> dict[str, Any]:
    rates: dict[str, Any] = {}
    all_pass = True
    inconclusive = False
    for rate in RATES_MSPS:
        condition_rows: dict[str, Any] = {}
        selected = [row for row in runs if int(row["sample_rate_msps"]) == rate]
        for condition in CONDITIONS:
            condition_runs = [row for row in selected if row["condition"] == condition]
            combinations = [
                combo
                for row in condition_runs
                for combo in row["analysis"]["combinations"]
            ]
            condition_rows[condition] = {
                "repeat_pass_fractions": [
                    float(row["analysis"]["slope_pass_fraction"])
                    for row in condition_runs
                ],
                "repeat_median_slopes": [
                    float(row["analysis"]["median_slope"])
                    for row in condition_runs
                ],
                "aggregate_pass_fraction": statistics.fmean(
                    int(row["slope_pass"]) for row in combinations
                ),
                "median_slope": statistics.median(
                    float(row["slope"]) for row in combinations
                ),
                "median_shuffled_slope": statistics.median(
                    float(row["shuffled_slope"]) for row in combinations
                ),
                "median_abs_lag1": statistics.median(
                    abs(float(row["lag1_correlation"])) for row in combinations
                ),
                "median_abs_slope_error": statistics.median(
                    abs(float(row["slope"]) + 0.5) for row in combinations
                ),
            }
        a = condition_rows["A"]
        b = condition_rows["B"]
        baseline_reproduced = bool(
            a["aggregate_pass_fraction"] <= 0.30
            and a["median_abs_slope_error"] >= 0.12
        )
        b_gates = {
            "each_repeat_pass_fraction_ge_0p75": all(
                value >= 0.75 for value in b["repeat_pass_fractions"]
            ),
            "aggregate_pass_fraction_ge_0p80": b["aggregate_pass_fraction"] >= 0.80,
            "repeat_median_slopes_in_range": all(
                -0.65 <= value <= -0.35 for value in b["repeat_median_slopes"]
            ),
            "raw_shuffled_median_slope_delta_le_0p10": abs(
                b["median_slope"] - b["median_shuffled_slope"]
            )
            <= 0.10,
            "median_abs_lag1_le_0p10": b["median_abs_lag1"] <= 0.10,
            "pass_fraction_improvement_ge_0p50": (
                b["aggregate_pass_fraction"] - a["aggregate_pass_fraction"]
            )
            >= 0.50,
            "median_slope_error_improvement_ge_0p12": (
                a["median_abs_slope_error"] - b["median_abs_slope_error"]
            )
            >= 0.12,
        }
        rate_pass = baseline_reproduced and all(b_gates.values())
        if not baseline_reproduced:
            inconclusive = True
        all_pass = all_pass and rate_pass
        rates[str(rate)] = {
            "baseline_reproduced": baseline_reproduced,
            "conditions": condition_rows,
            "b_gates": b_gates,
            "pass": rate_pass,
        }
    classification = (
        "T510_STAGE34B2_CAUSALITY_PASS"
        if all_pass
        else (
            "INCONCLUSIVE_BASELINE_NOT_REPRODUCED"
            if inconclusive
            else "T510_STAGE34B2_CAUSALITY_FAIL"
        )
    )
    return {"ok": all_pass, "classification": classification, "rates": rates}


def write_summary_csv(path: Path, runs: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=(
                "sample_rate_msps",
                "repeat",
                "condition",
                "lane",
                "rf_mhz",
                "slope",
                "shuffled_slope",
                "lag1_correlation",
                "slope_pass",
            ),
        )
        writer.writeheader()
        for run in runs:
            for row in run["analysis"]["combinations"]:
                writer.writerow(
                    {
                        "sample_rate_msps": run["sample_rate_msps"],
                        "repeat": run["repeat"],
                        "condition": run["condition"],
                        **{
                            key: row[key]
                            for key in (
                                "lane",
                                "rf_mhz",
                                "slope",
                                "shuffled_slope",
                                "lag1_correlation",
                                "slope_pass",
                            )
                        },
                    }
                )


def write_pcap_manifest(root: Path) -> Path:
    path = root / "pcap_manifest.sha256"
    lines = [
        f"{sha256_file(pcap)}  {pcap.relative_to(root)}"
        for pcap in sorted(root.rglob("*.pcap"))
    ]
    path.write_text("\n".join(lines) + ("\n" if lines else ""))
    return path


def run_campaign(
    args: argparse.Namespace,
    template: dict[str, Any],
    preflight: dict[str, Any],
) -> int:
    if preflight.get("classification") != "T510_STAGE34B2_AMPLITUDE_PREFLIGHT_PASS":
        raise RuntimeError("formal campaign requires the passing PG269 amplitude preflight")
    selected_amplitude = float(preflight["selected_amplitude_percent"])
    root = args.receiver_output.resolve() / "34b2"
    campaign_path = root / "campaign.json"
    if campaign_path.exists():
        raise RuntimeError(f"refusing to overwrite existing campaign {campaign_path}")
    state: dict[str, Any] = {
        "classification": "T510_STAGE34B2_CAUSALITY_IN_PROGRESS",
        "ok": False,
        "core_version": CORE_VERSION,
        "bitstream_sha256": BITSTREAM_SHA256,
        "pfb_profile_id": PFB_PROFILE_ID,
        "center_mhz": CENTER_MHZ,
        "tone_mhz": TONE_MHZ,
        "safe_rf_mhz": list(SAFE_RF_MHZ),
        "selected_amplitude_percent": selected_amplitude,
        "duration_seconds_per_run": FORMAL_DURATION_SECONDS,
        "planned_runs": campaign_runs(),
        "completed_runs": [],
        "errors": [],
        "started_unix_ms": time.time_ns() // 1_000_000,
    }
    write_json(campaign_path, state)
    try:
        for run in campaign_runs():
            print(
                "STAGE34B2_RUN_START "
                f"{run['index'] + 1}/18 rate={run['sample_rate_msps']} "
                f"repeat={run['repeat']} condition={run['condition']}",
                flush=True,
            )
            result = execute_run(args, template, run, selected_amplitude)
            state["completed_runs"].append(
                {
                    "name": result["name"],
                    "sample_rate_msps": result["sample_rate_msps"],
                    "repeat": result["repeat"],
                    "condition": result["condition"],
                    "result_path": str(
                        (
                            root
                            / "runs"
                            / str(result["name"])
                            / "result.json"
                        ).resolve()
                    ),
                }
            )
            write_json(campaign_path, state)
            print(f"STAGE34B2_RUN_PASS {result['name']}", flush=True)
        results = [
            json.loads(Path(row["result_path"]).read_text())
            for row in state["completed_runs"]
        ]
        gate = aggregate_gate(results)
        state["gate"] = gate
        state["ok"] = bool(gate["ok"])
        state["classification"] = str(gate["classification"])
        write_summary_csv(root / "causality_summary.csv", results)
        manifest = write_pcap_manifest(root)
        state["pcap_manifest"] = {
            "path": str(manifest.resolve()),
            "sha256": sha256_file(manifest),
        }
    except Exception as exc:  # noqa: BLE001 - campaign stops on first operational failure
        state["errors"].append(f"{type(exc).__name__}: {exc}")
        state["classification"] = "T510_STAGE34B2_CAUSALITY_FAIL"
    finally:
        state["errors"].extend(stop_mute_unfreeze(args.agent_base))
        state["finished_unix_ms"] = time.time_ns() // 1_000_000
        if state["errors"]:
            state["ok"] = False
            state["classification"] = "T510_STAGE34B2_CAUSALITY_FAIL"
        write_json(campaign_path, state)
        board_summary = {
            "classification": state["classification"],
            "ok": state["ok"],
            "campaign_path": str(campaign_path),
            "campaign_sha256": sha256_file(campaign_path),
            "completed_run_count": len(state["completed_runs"]),
            "errors": state["errors"],
        }
        write_json(args.board_output.resolve() / "34b2" / "campaign_summary.json", board_summary)
    print(
        json.dumps(
            {
                "classification": state["classification"],
                "ok": state["ok"],
                "completed_run_count": len(state["completed_runs"]),
                "errors": state["errors"],
            },
            indent=2,
        ),
        flush=True,
    )
    return 0 if state["ok"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--receiver-output",
        type=Path,
        default=Path("build/receiver/latest/evidence/rfdc_calibration"),
    )
    parser.add_argument(
        "--board-output",
        type=Path,
        default=Path("build/board/latest/evidence/rfdc_calibration"),
    )
    parser.add_argument(
        "--configure-template",
        type=Path,
        default=Path("config/t510/configure_320_time_only.example.json"),
    )
    parser.add_argument("--agent-base", default="http://192.168.100.117:8010")
    parser.add_argument("--receiver-base", default="http://192.168.100.162:8089")
    parser.add_argument("--settle-seconds", type=float, default=2.0)
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    template = json.loads(args.configure_template.read_text())
    preflight = run_amplitude_preflight(args, template)
    print(
        json.dumps(
            {
                "classification": preflight["classification"],
                "ok": preflight["ok"],
                "selected_amplitude_percent": preflight.get(
                    "selected_amplitude_percent"
                ),
                "errors": preflight["errors"],
            },
            indent=2,
        ),
        flush=True,
    )
    if not preflight["ok"]:
        return 1
    return 0 if args.preflight_only else run_campaign(args, template, preflight)


if __name__ == "__main__":
    raise SystemExit(main())
