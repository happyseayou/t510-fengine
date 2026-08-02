#!/usr/bin/env python3
"""Validate one Stage 33 DAC0 -> ADC0/ADC1 loopback tone and spectral purity."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import time
import urllib.error
import urllib.request
from typing import Any

from t510_rf_spectral_metrics import (
    average_lane_power,
    bin_for_rf,
    capture_spectra,
    circular_bin_error,
    counter_view,
    http_json,
    rf_for_bin,
)
from stage33_agent_host_gate import _stage33_rfdc_health


def agent_request(
    base: str,
    path: str,
    *,
    body: dict[str, Any] | None = None,
    method: str | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    request = urllib.request.Request(
        base.rstrip("/") + path,
        data=None if body is None else json.dumps(body).encode("utf-8"),
        headers={} if body is None else {"Content-Type": "application/json"},
        method=method or ("GET" if body is None else "POST"),
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            value = json.load(response)
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} from {request.full_url}: {payload}") from exc
    if not isinstance(value, dict) or not isinstance(value.get("result"), dict):
        raise RuntimeError(f"Agent returned an invalid response for {path}: {value}")
    return value["result"]


def dac_request(
    *, board_id: int, center_mhz: float, tone_mhz: float,
    amplitude_percent: float, enabled: bool,
) -> dict[str, Any]:
    return {
        "expected_board_id": board_id,
        "center_mhz": center_mhz,
        "channels": [
            {
                "channel": channel,
                "enabled": enabled and channel == 0,
                "rf_frequency_mhz": tone_mhz,
                "amplitude_percent": amplitude_percent if enabled and channel == 0 else 0.0,
                "phase_deg": 0.0,
            }
            for channel in range(8)
        ],
    }


def configure_receiver(base: str, sample_rate_msps: int, center_mhz: float, tone_mhz: float) -> dict[str, Any]:
    body = {
        "sample_rate_msps": sample_rate_msps,
        "output_mode": "spec_only",
        "center_mhz": center_mhz,
        "expected_mhz": tone_mhz,
        "dac_mhz": tone_mhz,
        "target_mhz_by_channel": [tone_mhz] * 8,
    }
    request = urllib.request.Request(
        base.rstrip("/") + "/api/config",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10.0) as response:
        value = json.load(response)
    if not isinstance(value, dict) or not bool(value.get("ok")):
        raise RuntimeError(f"receiver configuration failed: {value}")
    return value


def compact_board(status: dict[str, Any]) -> dict[str, Any]:
    return {
        key: status.get(key)
        for key in (
            "captured_at_unix_ms", "core_version", "streaming", "profile",
            "clock", "mts", "rfdc", "qsfp", "pipeline", "counters",
            "channelizer", "reference_watchdog", "error_flags",
        )
    }


def board_error_counters(status: dict[str, Any]) -> dict[str, int]:
    counters = dict(status.get("counters", {}))
    channelizer = dict(status.get("channelizer", {}))
    names = (
        "rfdc_dropped", "science_dropped_beats", "spec_dropped", "tx_frames_dropped",
        "tx_route_error", "tx_route_miss",
    )
    result = {name: int(counters.get(name, 0)) for name in names}
    for name in (
        "overflow_count", "data_halt_count", "xfft_event_count",
        "tile_overflow_count", "xfft_tlast_unexpected_count",
        "xfft_tlast_missing_count", "xfft_fft_overflow_count",
        "xfft_data_out_halt_count", "xfft_status_halt_count",
        "capture_backpressure_count", "frame_sample0_overflow_count",
        "coefficient_error_count",
    ):
        result[f"channelizer_{name}"] = int(channelizer.get(name, 0))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent-base", default="http://192.168.100.117:8010")
    parser.add_argument("--receiver-base", default="http://192.168.100.162:8089")
    parser.add_argument("--receiver-host", default="192.168.100.162")
    parser.add_argument("--receiver-port", type=int, default=8089)
    parser.add_argument("--board-id", type=int, default=1)
    parser.add_argument("--sample-rate-msps", type=int, choices=(160, 320), required=True)
    parser.add_argument("--center-mhz", type=float, default=200.0)
    parser.add_argument("--tone-mhz", type=float, required=True)
    parser.add_argument("--amplitude-percent", type=float, default=25.0)
    parser.add_argument("--captures", type=int, default=5)
    parser.add_argument("--settle-seconds", type=float, default=3.0)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--bin-tolerance", type=int, default=1)
    parser.add_argument("--min-image-rejection-db", type=float, default=60.0)
    parser.add_argument("--max-spur-dbc", type=float, default=-50.0)
    parser.add_argument("--carrier-exclusion-bins", type=int, default=2)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.captures <= 0 or args.carrier_exclusion_bins < 0:
        parser.error("--captures must be positive and --carrier-exclusion-bins non-negative")

    evidence: dict[str, Any] = {
        "classification": "STAGE33_DAC_PURITY_IN_PROGRESS",
        "ok": False,
        "errors": [],
        "sample_rate_msps": args.sample_rate_msps,
        "center_mhz": args.center_mhz,
        "tone_mhz": args.tone_mhz,
        "amplitude_percent": args.amplitude_percent,
        "physical_path": "DAC0 -> splitter -> ADC0/ADC1",
        "warnings": [],
    }
    started = False
    dac_enabled = False
    try:
        catalog = agent_request(args.agent_base, "/api/v2/bitstreams")
        entries = list(catalog.get("bitstreams", []))
        if (
            len(entries) != 1
            or entries[0].get("id") != "fengine-0x00010033"
            or str(entries[0].get("core_version", "")).lower() != "0x00010033"
        ):
            raise RuntimeError(f"Agent bitstream catalog mismatch: {entries}")
        evidence["bitstream"] = entries[0]

        idle = agent_request(args.agent_base, "/api/v2/status")
        if str(idle.get("core_version", "")).lower() != "0x00010033":
            raise RuntimeError(f"wrong core version: {idle.get('core_version')}")
        profile = dict(idle.get("profile", {}))
        if bool(idle.get("streaming")):
            raise RuntimeError("board is already streaming")
        if int(profile.get("sample_rate_msps", 0)) != args.sample_rate_msps:
            raise RuntimeError(f"sample-rate profile mismatch: {profile}")
        if profile.get("mode") != "spec_only":
            raise RuntimeError(f"board is not in SPEC_ONLY: {profile}")
        if abs(float(profile.get("center_mhz", 0.0)) - args.center_mhz) > 1.0e-6:
            raise RuntimeError(f"board center-frequency mismatch: {profile}")
        watchdog = dict(idle.get("reference_watchdog", {}))
        if not bool(watchdog.get("healthy")) or bool(watchdog.get("fault_latched")):
            raise RuntimeError(f"reference watchdog is unhealthy: {watchdog}")
        idle_rfdc_health = _stage33_rfdc_health(idle, require_valid=False)
        evidence["rfdc_health_idle"] = idle_rfdc_health
        if not idle_rfdc_health["ok"]:
            raise RuntimeError(
                f"Stage 33 RFDC contract failed before START: {idle_rfdc_health['errors']}"
            )
        evidence["idle"] = compact_board(idle)
        evidence["receiver_config"] = configure_receiver(
            args.receiver_base, args.sample_rate_msps, args.center_mhz, args.tone_mhz
        )

        evidence["dac_on"] = agent_request(
            args.agent_base,
            "/api/v2/dac",
            body=dac_request(
                board_id=args.board_id,
                center_mhz=args.center_mhz,
                tone_mhz=args.tone_mhz,
                amplitude_percent=args.amplitude_percent,
                enabled=True,
            ),
            method="PUT",
        )
        dac_enabled = True
        agent_request(
            args.agent_base,
            "/api/v2/start",
            body={"expected_board_id": args.board_id},
        )
        started = True
        time.sleep(max(args.settle_seconds, 0.1))

        board_before = agent_request(args.agent_base, "/api/v2/status")
        receiver_before = http_json(args.receiver_base.rstrip("/") + "/api/state")
        frames = capture_spectra(
            args.receiver_host,
            args.receiver_port,
            count=args.captures,
            timeout=args.timeout,
        )
        board_after = agent_request(args.agent_base, "/api/v2/status")
        receiver_after = http_json(args.receiver_base.rstrip("/") + "/api/state")

        errors: list[str] = []
        for label, snapshot in (("before", board_before), ("after", board_after)):
            health = _stage33_rfdc_health(snapshot, require_valid=True)
            evidence[f"rfdc_health_{label}"] = health
            if not health["ok"]:
                errors.extend(
                    f"RFDC_{label.upper()}_{item}" for item in health["errors"]
                )

        bins = int(frames[0]["bins"])
        sample_rate_hz = int(frames[0]["sample_rate_hz"])
        expected_bin = bin_for_rf(args.center_mhz, sample_rate_hz, bins, args.tone_mhz)
        image_mhz = 2.0 * args.center_mhz - args.tone_mhz
        image_bin = bin_for_rf(args.center_mhz, sample_rate_hz, bins, image_mhz)
        rows = []
        warnings: list[str] = []
        for lane in (0, 1):
            power = average_lane_power(frames, lane)
            peak_bin = max(range(bins), key=power.__getitem__)
            bin_error = circular_bin_error(peak_bin, expected_bin, bins)
            rejection = power[expected_bin] - power[image_bin]
            spur_candidates = [
                index
                for index in range(bins)
                if circular_bin_error(index, expected_bin, bins)
                > args.carrier_exclusion_bins
            ]
            if not spur_candidates:
                raise RuntimeError(
                    "carrier exclusion covers every spectrum bin; reduce "
                    "--carrier-exclusion-bins"
                )
            spur_bin = max(spur_candidates, key=power.__getitem__)
            spur_dbc = power[spur_bin] - power[expected_bin]
            rows.append({
                "lane": lane,
                "peak_bin": peak_bin,
                "peak_rf_mhz": rf_for_bin(args.center_mhz, sample_rate_hz, bins, peak_bin),
                "peak_power_db": power[peak_bin],
                "expected_bin": expected_bin,
                "expected_power_db": power[expected_bin],
                "bin_error": bin_error,
                "image_bin": image_bin,
                "image_rf_mhz": image_mhz,
                "image_power_db": power[image_bin],
                "image_rejection_db": rejection,
                "max_spur_bin": spur_bin,
                "max_spur_rf_mhz": rf_for_bin(
                    args.center_mhz, sample_rate_hz, bins, spur_bin
                ),
                "max_spur_power_db": power[spur_bin],
                "max_spur_dbc": spur_dbc,
            })
            if bin_error > args.bin_tolerance:
                errors.append(f"ADC{lane}_RF_BIN_MISMATCH")
            if image_bin != expected_bin and rejection < args.min_image_rejection_db:
                errors.append(f"ADC{lane}_IMAGE_REJECTION_LOW")
            if spur_dbc > args.max_spur_dbc:
                errors.append(f"ADC{lane}_MAX_SPUR_HIGH")

        board_before_counters = board_error_counters(board_before)
        board_after_counters = board_error_counters(board_after)
        board_delta = {
            key: board_after_counters[key] - board_before_counters[key]
            for key in board_before_counters
        }
        receiver_before_counters = counter_view(receiver_before)
        receiver_after_counters = counter_view(receiver_after)
        receiver_delta = {
            key: receiver_after_counters[key] - receiver_before_counters[key]
            for key in receiver_before_counters
        }
        if any(board_delta.values()):
            errors.append("BOARD_DROP_OR_OVERFLOW_DELTA")
        if any(receiver_delta.values()):
            errors.append("RECEIVER_DROP_OR_GAP_DELTA")
        if any(bool(frame["gap_before"]) for frame in frames):
            errors.append("SPECTRUM_GAP_BEFORE")

        evidence.update({
            "bins": bins,
            "sample_rate_hz": sample_rate_hz,
            "bin_width_hz": sample_rate_hz / bins,
            "expected_bin": expected_bin,
            "image_bin": image_bin,
            "image_mhz": image_mhz,
            "first_frame_id": frames[0]["frame_id"],
            "last_frame_id": frames[-1]["frame_id"],
            "lanes": rows,
            "board_before": compact_board(board_before),
            "board_after": compact_board(board_after),
            "board_counter_delta": board_delta,
            "receiver_counter_delta": receiver_delta,
            "errors": errors,
            "warnings": warnings,
            "thresholds": {
                "bin_tolerance": args.bin_tolerance,
                "min_image_rejection_db": args.min_image_rejection_db,
                "max_spur_dbc": args.max_spur_dbc,
                "carrier_exclusion_bins": args.carrier_exclusion_bins,
            },
            "ok": not errors,
        })
        evidence["classification"] = (
            "STAGE33_DAC_PURITY_PASS" if not errors
            else "STAGE33_DAC_PURITY_FAIL"
        )
    except Exception as exc:
        evidence["errors"].append(f"{type(exc).__name__}: {exc}")
    finally:
        if started:
            try:
                evidence["stop"] = agent_request(
                    args.agent_base,
                    "/api/v2/stop",
                    body={"reason": "stage33_dac_purity_gate_complete"},
                )
            except Exception as exc:
                evidence["errors"].append(f"STOP_FAILED: {type(exc).__name__}: {exc}")
                evidence["ok"] = False
        if dac_enabled:
            try:
                evidence["dac_off"] = agent_request(
                    args.agent_base,
                    "/api/v2/dac",
                    body=dac_request(
                        board_id=args.board_id,
                        center_mhz=args.center_mhz,
                        tone_mhz=args.tone_mhz,
                        amplitude_percent=0.0,
                        enabled=False,
                    ),
                    method="PUT",
                )
            except Exception as exc:
                evidence["errors"].append(f"DAC_OFF_FAILED: {type(exc).__name__}: {exc}")
                evidence["ok"] = False
        if evidence["errors"]:
            evidence["classification"] = "STAGE33_DAC_PURITY_FAIL"
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(json.dumps({
        "classification": evidence["classification"],
        "ok": evidence["ok"],
        "errors": evidence["errors"],
        "warnings": evidence.get("warnings", []),
        "tone_mhz": args.tone_mhz,
        "sample_rate_msps": args.sample_rate_msps,
        "lanes": evidence.get("lanes"),
    }, indent=2, sort_keys=True))
    return 0 if evidence["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
