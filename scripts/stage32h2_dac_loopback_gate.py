#!/usr/bin/env python3
"""Validate one Stage 32h2 DAC0 -> ADC0/ADC1 physical loopback tone."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import time
import urllib.error
import urllib.request
from typing import Any

from stage32h1_external_rf_axis_gate import (
    average_lane_power,
    bin_for_rf,
    capture_spectra,
    circular_bin_error,
    counter_view,
    http_json,
    rf_for_bin,
)


EXPECTED_BIT_SHA256 = "47117c9e656cfd8345125ef0130eb91a5ec0868cef59931b40b957da29f31234"


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
        "bandwidth_mhz": sample_rate_msps,
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
            "clock", "mts", "qsfp", "pipeline", "counters", "channelizer",
            "reference_watchdog",
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
    parser.add_argument("--center-mhz", type=float, default=170.0)
    parser.add_argument("--tone-mhz", type=float, required=True)
    parser.add_argument("--amplitude-percent", type=float, default=25.0)
    parser.add_argument("--captures", type=int, default=5)
    parser.add_argument("--settle-seconds", type=float, default=3.0)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--bin-tolerance", type=int, default=1)
    parser.add_argument("--min-image-rejection-db", type=float, default=60.0)
    parser.add_argument(
        "--enforce-image-rejection",
        action="store_true",
        help="Fail on low image rejection; Stage 32h2 normally records it for the 32h3 purity gate.",
    )
    parser.add_argument(
        "--expected-bit-sha256",
        default=EXPECTED_BIT_SHA256,
        help="Require this exact Stage 32 candidate bitstream SHA256 before enabling DAC0.",
    )
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    evidence: dict[str, Any] = {
        "classification": "STAGE32H2_DAC_LOOPBACK_IN_PROGRESS",
        "ok": False,
        "errors": [],
        "expected_bit_sha256": args.expected_bit_sha256,
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
        catalog = agent_request(args.agent_base, "/api/v1/bitstreams")
        entries = list(catalog.get("bitstreams", []))
        if len(entries) != 1 or entries[0].get("sha256") != args.expected_bit_sha256:
            raise RuntimeError(f"Agent bitstream catalog mismatch: {entries}")

        idle = agent_request(args.agent_base, "/api/v1/status")
        profile = dict(idle.get("profile", {}))
        if bool(idle.get("streaming")):
            raise RuntimeError("board is already streaming")
        if int(profile.get("bandwidth_mhz", 0)) != args.sample_rate_msps:
            raise RuntimeError(f"sample-rate profile mismatch: {profile}")
        if profile.get("mode") != "spec_only":
            raise RuntimeError(f"board is not in SPEC_ONLY: {profile}")
        watchdog = dict(idle.get("reference_watchdog", {}))
        if not bool(watchdog.get("healthy")) or bool(watchdog.get("fault_latched")):
            raise RuntimeError(f"reference watchdog is unhealthy: {watchdog}")
        evidence["idle"] = compact_board(idle)
        evidence["receiver_config"] = configure_receiver(
            args.receiver_base, args.sample_rate_msps, args.center_mhz, args.tone_mhz
        )

        evidence["dac_on"] = agent_request(
            args.agent_base,
            "/api/v1/dac",
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
            "/api/v1/start",
            body={"expected_board_id": args.board_id},
        )
        started = True
        time.sleep(max(args.settle_seconds, 0.1))

        board_before = agent_request(args.agent_base, "/api/v1/status")
        receiver_before = http_json(args.receiver_base.rstrip("/") + "/api/state")
        frames = capture_spectra(
            args.receiver_host,
            args.receiver_port,
            count=args.captures,
            timeout=args.timeout,
        )
        board_after = agent_request(args.agent_base, "/api/v1/status")
        receiver_after = http_json(args.receiver_base.rstrip("/") + "/api/state")

        bins = int(frames[0]["bins"])
        sample_rate_hz = int(frames[0]["sample_rate_hz"])
        expected_bin = bin_for_rf(args.center_mhz, sample_rate_hz, bins, args.tone_mhz)
        image_mhz = 2.0 * args.center_mhz - args.tone_mhz
        image_bin = bin_for_rf(args.center_mhz, sample_rate_hz, bins, image_mhz)
        rows = []
        errors: list[str] = []
        warnings: list[str] = []
        for lane in (0, 1):
            power = average_lane_power(frames, lane)
            peak_bin = max(range(bins), key=power.__getitem__)
            bin_error = circular_bin_error(peak_bin, expected_bin, bins)
            rejection = power[expected_bin] - power[image_bin]
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
            })
            if bin_error > args.bin_tolerance:
                errors.append(f"ADC{lane}_RF_BIN_MISMATCH")
            if rejection < args.min_image_rejection_db:
                warning = f"ADC{lane}_IMAGE_REJECTION_LOW"
                warnings.append(warning)
                if args.enforce_image_rejection:
                    errors.append(warning)

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
            "image_rejection_enforced": bool(args.enforce_image_rejection),
            "ok": not errors,
        })
        evidence["classification"] = (
            "STAGE32H2_DAC_LOOPBACK_PASS" if not errors
            else "STAGE32H2_DAC_LOOPBACK_FAIL"
        )
    except Exception as exc:
        evidence["errors"].append(f"{type(exc).__name__}: {exc}")
    finally:
        if started:
            try:
                evidence["stop"] = agent_request(
                    args.agent_base,
                    "/api/v1/stop",
                    body={"reason": "stage32h2_dac_loopback_gate_complete"},
                )
            except Exception as exc:
                evidence["errors"].append(f"STOP_FAILED: {type(exc).__name__}: {exc}")
                evidence["ok"] = False
        if dac_enabled:
            try:
                evidence["dac_off"] = agent_request(
                    args.agent_base,
                    "/api/v1/dac",
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
            evidence["classification"] = "STAGE32H2_DAC_LOOPBACK_FAIL"
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
