#!/usr/bin/env python3
"""Eight-lane DAC-ADC fractional-bin gate for the current fixed PFB."""

from __future__ import annotations

import argparse
import cmath
import json
import math
from pathlib import Path
import sys
import time
import urllib.error
import urllib.request
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from python.t510_fengine import T510FEngine
from scripts.t510_rf_spectral_metrics import average_lane_power, capture_spectra


OFFSETS = (0.0, -0.5, -0.4, -0.25, 0.25, 0.4, 0.5)
COUNTER_KEYS = (
    "overflow_count",
    "data_halt_count",
    "xfft_event_count",
    "fir_saturation_count",
    "xfft_tlast_unexpected_count",
    "xfft_tlast_missing_count",
    "xfft_fft_overflow_count",
    "xfft_data_out_halt_count",
    "xfft_status_halt_count",
    "capture_backpressure_count",
    "frame_sample0_overflow_count",
    "coefficient_error_count",
)


def http_json(
    url: str,
    *,
    method: str = "GET",
    body: dict[str, Any] | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=None if body is None else json.dumps(body).encode("utf-8"),
        headers={} if body is None else {"Content-Type": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            value = json.load(response)
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} from {url}: {payload}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"{url} returned a non-object JSON value")
    result = value.get("result", value)
    if not isinstance(result, dict):
        raise RuntimeError(f"{url} returned no result object")
    return result


def pfb_response_db(coefficients: list[int], offset_bins: float) -> float:
    rotation = cmath.exp(-2j * math.pi * offset_bins / 4096.0)
    phasor = 1.0 + 0.0j
    response = 0.0 + 0.0j
    for coefficient in coefficients:
        response += coefficient * phasor
        phasor *= rotation
    return 20.0 * math.log10(max(abs(response) / sum(coefficients), 1.0e-30))


def circular_bin(index: int) -> int:
    return index % 4096


def dac_request(
    *, board_id: int, center_mhz: float, rf_mhz: float, amplitude_percent: float
) -> dict[str, Any]:
    return {
        "expected_board_id": board_id,
        "center_mhz": center_mhz,
        "channels": [
            {
                "channel": lane,
                "enabled": amplitude_percent > 0.0,
                "rf_frequency_mhz": rf_mhz,
                "amplitude_percent": amplitude_percent,
                "phase_deg": lane * 45.0 if lane < 5 else lane * 45.0 - 360.0,
            }
            for lane in range(8)
        ],
    }


def counter_delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, int]:
    left = before.get("channelizer", {})
    right = after.get("channelizer", {})
    return {key: int(right.get(key, 0) or 0) - int(left.get(key, 0) or 0) for key in COUNTER_KEYS}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent-base", default="http://192.168.100.117:8010")
    parser.add_argument("--receiver-base", default="http://192.168.100.162:8089")
    parser.add_argument("--receiver-host", default="192.168.100.162")
    parser.add_argument("--receiver-port", type=int, default=8089)
    parser.add_argument("--sample-rate-msps", type=int, choices=(160, 320), required=True)
    parser.add_argument("--anchor-signed-bin", type=int, default=512)
    parser.add_argument("--amplitude-percent", type=float, default=25.0)
    parser.add_argument("--captures", type=int, default=5)
    parser.add_argument("--settle-seconds", type=float, default=0.25)
    parser.add_argument("--ratio-tolerance-db", type=float, default=1.5)
    parser.add_argument("--half-bin-tolerance-db", type=float, default=1.0)
    parser.add_argument("--lane-spread-db", type=float, default=1.0)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if not -2048 < args.anchor_signed_bin < 2048:
        raise ValueError("--anchor-signed-bin must be within -2047..2047")
    if not 0.0 < args.amplitude_percent <= 100.0:
        raise ValueError("--amplitude-percent must be within (0, 100]")

    agent = args.agent_base.rstrip("/")
    receiver = args.receiver_base.rstrip("/")
    before = http_json(agent + "/api/v2/status")
    receiver_before = http_json(receiver + "/api/state")
    if str(before.get("core_version", "")).lower() != "0x00010034":
        raise RuntimeError("board is not running CORE_VERSION 0x00010034")
    if not bool(before.get("streaming")):
        raise RuntimeError("board must already be streaming a SPEC-enabled profile")
    profile = before.get("profile", {})
    if int(profile.get("sample_rate_msps", 0)) != args.sample_rate_msps:
        raise RuntimeError("active board sample rate does not match --sample-rate-msps")
    if str(profile.get("mode", "")) not in ("spec_only", "time_spec"):
        raise RuntimeError("active board profile is not SPEC-enabled")
    channelizer = before.get("channelizer", {})
    if int(channelizer.get("nchan", 0)) != 4096 or int(channelizer.get("taps", 0)) != 8:
        raise RuntimeError("active board does not expose the fixed 4096-channel 8-tap PFB")

    board_id = int(before.get("board_id", -1))
    center_mhz = float(profile.get("center_mhz", 0.0))
    sample_rate_hz = args.sample_rate_msps * 1_000_000
    bin_hz = sample_rate_hz / 4096.0
    coefficients = T510FEngine.generate_default_pfb_coefficients()
    predictions = {
        offset: pfb_response_db(coefficients, offset) for offset in OFFSETS
    }
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    center_power: list[float] | None = None

    try:
        for offset in OFFSETS:
            rf_mhz = center_mhz + (args.anchor_signed_bin + offset) * bin_hz / 1.0e6
            http_json(
                agent + "/api/v2/dac",
                method="PUT",
                body=dac_request(
                    board_id=board_id,
                    center_mhz=center_mhz,
                    rf_mhz=rf_mhz,
                    amplitude_percent=args.amplitude_percent,
                ),
            )
            time.sleep(max(args.settle_seconds, 0.0))
            frames = capture_spectra(
                args.receiver_host,
                args.receiver_port,
                count=args.captures,
                timeout=30.0,
            )
            if any(int(frame.get("bins", 0)) != 4096 for frame in frames):
                raise RuntimeError("receiver did not publish a 4096-bin spectrum")
            if any(frame.get("gap_before") for frame in frames):
                errors.append(f"OFFSET_{offset:+.2f}_RECEIVER_GAP")
            lane_power = [average_lane_power(frames, lane) for lane in range(8)]
            anchor_bin = circular_bin(args.anchor_signed_bin)
            neighbor_bin = circular_bin(
                args.anchor_signed_bin + (1 if offset >= 0.0 else -1)
            )
            neighbor_offset = offset - 1.0 if offset >= 0.0 else offset + 1.0
            predicted_anchor = predictions[offset]
            predicted_neighbor = pfb_response_db(coefficients, neighbor_offset)
            predicted_delta = predicted_anchor - predicted_neighbor
            expected_peak = anchor_bin if predicted_anchor >= predicted_neighbor else neighbor_bin
            half_bin = abs(abs(offset) - 0.5) < 1.0e-9
            allowed_peak_bins = (
                {anchor_bin, neighbor_bin} if half_bin else {expected_peak}
            )
            lane_rows = []
            normalized_peaks = []
            for lane, power in enumerate(lane_power):
                peak_bin = max(range(4096), key=power.__getitem__)
                measured_delta = power[anchor_bin] - power[neighbor_bin]
                lane_rows.append(
                    {
                        "lane": lane,
                        "peak_bin": peak_bin,
                        "anchor_db": power[anchor_bin],
                        "neighbor_db": power[neighbor_bin],
                        "measured_delta_db": measured_delta,
                    }
                )
                if peak_bin not in allowed_peak_bins:
                    errors.append(f"OFFSET_{offset:+.2f}_LANE{lane}_PEAK_BIN")
                if min(predicted_anchor, predicted_neighbor) - max(
                    predicted_anchor, predicted_neighbor
                ) >= -30.0 and abs(measured_delta - predicted_delta) > args.ratio_tolerance_db:
                    errors.append(f"OFFSET_{offset:+.2f}_LANE{lane}_RATIO")
                if half_bin and abs(measured_delta) > args.half_bin_tolerance_db:
                    errors.append(f"OFFSET_{offset:+.2f}_LANE{lane}_HALF_BIN")
                if offset == 0.0:
                    normalized_peaks.append(power[expected_peak])
                elif center_power is not None:
                    normalized_peaks.append(power[expected_peak] - center_power[lane])
            if offset == 0.0:
                center_power = list(normalized_peaks)
                normalized_peaks = [0.0] * 8
            if max(normalized_peaks) - min(normalized_peaks) > args.lane_spread_db:
                errors.append(f"OFFSET_{offset:+.2f}_LANE_SPREAD")
            rows.append(
                {
                    "offset_bins": offset,
                    "rf_mhz": rf_mhz,
                    "anchor_bin": anchor_bin,
                    "neighbor_bin": neighbor_bin,
                    "predicted_anchor_db": predicted_anchor,
                    "predicted_neighbor_db": predicted_neighbor,
                    "predicted_delta_db": predicted_delta,
                    "lanes": lane_rows,
                }
            )
    finally:
        http_json(
            agent + "/api/v2/dac",
            method="PUT",
            body=dac_request(
                board_id=board_id,
                center_mhz=center_mhz,
                rf_mhz=center_mhz,
                amplitude_percent=0.0,
            ),
        )

    after = http_json(agent + "/api/v2/status")
    receiver_after = http_json(receiver + "/api/state")
    deltas = counter_delta(before, after)
    for key, value in deltas.items():
        if value != 0:
            errors.append(f"NONZERO_{key.upper()}_DELTA")
    for key in (
        "kernel_drops",
        "ring_drops",
        "worker_ring_drops",
        "app_drops",
        "seq_gaps",
        "frame_gaps",
        "sample0_gaps",
        "spec_seq_gaps",
        "spec_frame_gaps",
    ):
        delta = int(receiver_after.get("stats", {}).get(key, 0)) - int(
            receiver_before.get("stats", {}).get(key, 0)
        )
        if delta != 0:
            errors.append(f"RECEIVER_{key.upper()}_DELTA")

    result = {
        "ok": not errors,
        "core_version": before.get("core_version"),
        "board_id": board_id,
        "sample_rate_msps": args.sample_rate_msps,
        "center_mhz": center_mhz,
        "anchor_signed_bin": args.anchor_signed_bin,
        "bin_width_hz": bin_hz,
        "profile_id": "0x34a80001",
        "coefficient_crc32": "0xb9ba227c",
        "rows": rows,
        "counter_delta": deltas,
        "errors": sorted(set(errors)),
        "dac_muted_after_gate": True,
    }
    Path(args.output).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
