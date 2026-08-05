#!/usr/bin/env python3
"""Validate the current RF axis against a physically known external tone."""

from __future__ import annotations

import argparse
import base64
import json
import math
import os
from pathlib import Path
import socket
import struct
import urllib.request
from typing import Any


SPECTRUM_MAGIC = 0x33505354


def signed_bin(index: int, bins: int) -> int:
    return index if index < bins // 2 else index - bins


def rf_for_bin(center_mhz: float, sample_rate_hz: int, bins: int, index: int) -> float:
    return center_mhz + signed_bin(index, bins) * sample_rate_hz / bins / 1.0e6


def bin_for_rf(center_mhz: float, sample_rate_hz: int, bins: int, rf_mhz: float) -> int:
    signed = round((rf_mhz - center_mhz) * 1.0e6 * bins / sample_rate_hz)
    return signed % bins


def circular_bin_error(left: int, right: int, bins: int) -> int:
    delta = (left - right) % bins
    return min(delta, bins - delta)


def strongest_spur(
    power_db: list[float], carrier_bin: int, exclusion_bins: int
) -> tuple[int, float]:
    """Return the strongest bin outside the circular carrier exclusion window."""
    bins = len(power_db)
    if bins == 0:
        raise ValueError("power spectrum must not be empty")
    if not 0 <= carrier_bin < bins:
        raise ValueError("carrier bin is outside the spectrum")
    if exclusion_bins < 0 or 2 * exclusion_bins + 1 >= bins:
        raise ValueError("carrier exclusion must leave at least one spur bin")
    candidates = (
        index
        for index in range(bins)
        if circular_bin_error(index, carrier_bin, bins) > exclusion_bins
    )
    spur_bin = max(candidates, key=power_db.__getitem__)
    return spur_bin, power_db[spur_bin] - power_db[carrier_bin]


def http_json(url: str, *, timeout: float = 15.0) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        value = json.load(response)
    if not isinstance(value, dict):
        raise RuntimeError(f"{url} returned a non-object JSON value")
    return value


def recv_exact(stream: socket.socket, buffered: bytearray, count: int) -> bytes:
    while len(buffered) < count:
        chunk = stream.recv(max(4096, count - len(buffered)))
        if not chunk:
            raise RuntimeError("receiver WebSocket closed unexpectedly")
        buffered.extend(chunk)
    value = bytes(buffered[:count])
    del buffered[:count]
    return value


def read_binary_frame(stream: socket.socket, buffered: bytearray) -> bytes:
    while True:
        first, second = recv_exact(stream, buffered, 2)
        opcode = first & 0x0F
        length = second & 0x7F
        if second & 0x80:
            raise RuntimeError("server WebSocket frame is unexpectedly masked")
        if length == 126:
            length = struct.unpack(">H", recv_exact(stream, buffered, 2))[0]
        elif length == 127:
            length = struct.unpack(">Q", recv_exact(stream, buffered, 8))[0]
        payload = recv_exact(stream, buffered, length)
        if opcode == 2:
            return payload
        if opcode == 8:
            raise RuntimeError("receiver WebSocket closed before a spectrum frame")


def capture_spectra(host: str, port: int, *, count: int, timeout: float) -> list[dict[str, Any]]:
    key = base64.b64encode(os.urandom(16)).decode("ascii")
    request = (
        "GET /ws/spectrum HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n\r\n"
    ).encode("ascii")
    frames: list[dict[str, Any]] = []
    with socket.create_connection((host, port), timeout=timeout) as stream:
        stream.settimeout(timeout)
        stream.sendall(request)
        buffered = bytearray()
        while b"\r\n\r\n" not in buffered:
            chunk = stream.recv(4096)
            if not chunk:
                raise RuntimeError("receiver WebSocket closed during handshake")
            buffered.extend(chunk)
        header, remainder = bytes(buffered).split(b"\r\n\r\n", 1)
        if b" 101 " not in header.split(b"\r\n", 1)[0]:
            raise RuntimeError(f"receiver WebSocket handshake failed: {header!r}")
        buffered = bytearray(remainder)
        while len(frames) < count:
            payload = read_binary_frame(stream, buffered)
            if len(payload) < 128 or struct.unpack_from("<I", payload, 0)[0] != SPECTRUM_MAGIC:
                continue
            header_bytes = struct.unpack_from("<H", payload, 6)[0]
            lane_count = struct.unpack_from("<I", payload, 56)[0]
            bins = struct.unpack_from("<I", payload, 60)[0]
            sample_rate_hz = struct.unpack_from("<I", payload, 92)[0]
            if header_bytes < 128 or lane_count == 0 or bins == 0 or sample_rate_hz == 0:
                raise RuntimeError("receiver spectrum geometry is invalid")
            amplitudes = []
            phases = []
            powers = []
            offset = header_bytes
            for _lane in range(lane_count):
                lane_bytes = bins * 12
                if offset + lane_bytes > len(payload):
                    raise RuntimeError("receiver spectrum frame is truncated")
                amplitudes.append(struct.unpack_from(f"<{bins}f", payload, offset))
                phases.append(
                    struct.unpack_from(f"<{bins}f", payload, offset + bins * 4)
                )
                powers.append(struct.unpack_from(f"<{bins}f", payload, offset + bins * 8))
                offset += lane_bytes
            frames.append(
                {
                    "sample0": struct.unpack_from("<Q", payload, 8)[0],
                    "frame_id": struct.unpack_from("<Q", payload, 16)[0],
                    "gap_before": bool(struct.unpack_from("<I", payload, 28)[0]),
                    "bins": bins,
                    "sample_rate_hz": sample_rate_hz,
                    "amplitudes": amplitudes,
                    "phases": phases,
                    "powers": powers,
                }
            )
    return frames


def average_lane_power(frames: list[dict[str, Any]], lane: int) -> list[float]:
    bins = int(frames[0]["bins"])
    result = []
    for index in range(bins):
        linear = sum(10.0 ** (float(frame["powers"][lane][index]) / 10.0) for frame in frames)
        result.append(10.0 * math.log10(max(linear / len(frames), 1.0e-30)))
    return result


def cross_lane_phase_statistics(
    frames: list[dict[str, Any]], reference_lane: int, lane: int, bin_index: int
) -> tuple[float, float]:
    """Return circular-mean phase difference in degrees and its coherence."""
    phasor = 0j
    for frame in frames:
        delta = float(frame["phases"][lane][bin_index]) - float(
            frame["phases"][reference_lane][bin_index]
        )
        phasor += complex(math.cos(delta), math.sin(delta))
    phasor /= len(frames)
    return math.degrees(math.atan2(phasor.imag, phasor.real)), abs(phasor)


def counter_view(state: dict[str, Any]) -> dict[str, int]:
    stats = state.get("stats", {})
    return {
        key: int(stats.get(key, 0))
        for key in (
            "kernel_drops",
            "ring_drops",
            "app_drops",
            "spec_seq_gaps",
            "spec_frame_gaps",
        )
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receiver-base", default="http://192.168.100.162:8089")
    parser.add_argument("--receiver-host", default="192.168.100.162")
    parser.add_argument("--receiver-port", type=int, default=8089)
    parser.add_argument("--expected-rf-mhz", type=float, required=True)
    parser.add_argument(
        "--probe-rf-mhz",
        type=float,
        action="append",
        default=[],
        help="RF frequency to report explicitly; repeat for multiple probe points",
    )
    parser.add_argument("--lanes", default="0,1")
    parser.add_argument("--captures", type=int, default=5)
    parser.add_argument("--bin-tolerance", type=int, default=1)
    parser.add_argument("--min-image-rejection-db", type=float, default=60.0)
    parser.add_argument(
        "--max-spur-dbc",
        type=float,
        help="optional maximum allowed spur level relative to the carrier (for example -50)",
    )
    parser.add_argument(
        "--carrier-exclusion-bins",
        type=int,
        default=2,
        help="bins on each side of the carrier excluded from the spur search",
    )
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    lanes = [int(item) for item in args.lanes.split(",") if item.strip()]
    if not lanes or len(set(lanes)) != len(lanes) or any(lane < 0 for lane in lanes):
        raise ValueError("--lanes must contain unique non-negative lane numbers")
    if args.captures <= 0:
        raise ValueError("--captures must be positive")
    if args.max_spur_dbc is not None and args.max_spur_dbc >= 0.0:
        raise ValueError("--max-spur-dbc must be negative")
    if args.carrier_exclusion_bins < 0:
        raise ValueError("--carrier-exclusion-bins must be non-negative")

    before = http_json(args.receiver_base.rstrip("/") + "/api/state")
    config = before.get("config", {})
    center_mhz = float(config.get("center_mhz", 0.0))
    frames = capture_spectra(
        args.receiver_host,
        args.receiver_port,
        count=args.captures,
        timeout=args.timeout,
    )
    after = http_json(args.receiver_base.rstrip("/") + "/api/state")
    bins = int(frames[0]["bins"])
    sample_rate_hz = int(frames[0]["sample_rate_hz"])
    if any(
        int(frame["bins"]) != bins or int(frame["sample_rate_hz"]) != sample_rate_hz
        for frame in frames
    ):
        raise RuntimeError("spectrum geometry changed during capture")
    if any(lane >= len(frames[0]["powers"]) for lane in lanes):
        raise RuntimeError("requested lane is absent from receiver spectrum")

    expected_bin = bin_for_rf(center_mhz, sample_rate_hz, bins, args.expected_rf_mhz)
    image_rf_mhz = 2.0 * center_mhz - args.expected_rf_mhz
    image_bin = bin_for_rf(center_mhz, sample_rate_hz, bins, image_rf_mhz)
    errors: list[str] = []
    rows = []
    lane_powers: dict[int, list[float]] = {}
    for lane in lanes:
        power = average_lane_power(frames, lane)
        lane_powers[lane] = power
        peak_bin = max(range(bins), key=power.__getitem__)
        bin_error = circular_bin_error(peak_bin, expected_bin, bins)
        image_rejection_db = power[expected_bin] - power[image_bin]
        spur_bin, max_spur_dbc = strongest_spur(
            power, peak_bin, args.carrier_exclusion_bins
        )
        probes = []
        for probe_rf_mhz in args.probe_rf_mhz:
            probe_bin = bin_for_rf(
                center_mhz, sample_rate_hz, bins, probe_rf_mhz
            )
            probes.append(
                {
                    "requested_rf_mhz": probe_rf_mhz,
                    "bin": probe_bin,
                    "mapped_rf_mhz": rf_for_bin(
                        center_mhz, sample_rate_hz, bins, probe_bin
                    ),
                    "power_db": power[probe_bin],
                    "dbc_to_expected": power[probe_bin] - power[expected_bin],
                }
            )
        row = {
            "lane": lane,
            "peak_bin": peak_bin,
            "peak_rf_mhz": rf_for_bin(center_mhz, sample_rate_hz, bins, peak_bin),
            "peak_power_db": power[peak_bin],
            "expected_bin": expected_bin,
            "expected_bin_power_db": power[expected_bin],
            "bin_error": bin_error,
            "image_rf_mhz": image_rf_mhz,
            "image_bin": image_bin,
            "image_power_db": power[image_bin],
            "image_rejection_db": image_rejection_db,
            "carrier_exclusion_bins": args.carrier_exclusion_bins,
            "max_spur_bin": spur_bin,
            "max_spur_rf_mhz": rf_for_bin(
                center_mhz, sample_rate_hz, bins, spur_bin
            ),
            "max_spur_power_db": power[spur_bin],
            "max_spur_dbc": max_spur_dbc,
            "probes": probes,
        }
        rows.append(row)
        if bin_error > args.bin_tolerance:
            errors.append(f"LANE{lane}_RF_BIN_MISMATCH")
        if image_bin != expected_bin and image_rejection_db < args.min_image_rejection_db:
            errors.append(f"LANE{lane}_IMAGE_REJECTION_LOW")
        if args.max_spur_dbc is not None and max_spur_dbc > args.max_spur_dbc:
            errors.append(f"LANE{lane}_SPUR_TOO_HIGH")

    cross_lane = []
    reference_lane = lanes[0]
    comparison_frequencies = list(
        dict.fromkeys([args.expected_rf_mhz, *args.probe_rf_mhz])
    )
    for lane in lanes[1:]:
        points = []
        for rf_mhz in comparison_frequencies:
            bin_index = bin_for_rf(center_mhz, sample_rate_hz, bins, rf_mhz)
            phase_delta_deg, coherence = cross_lane_phase_statistics(
                frames, reference_lane, lane, bin_index
            )
            points.append(
                {
                    "requested_rf_mhz": rf_mhz,
                    "bin": bin_index,
                    "mapped_rf_mhz": rf_for_bin(
                        center_mhz, sample_rate_hz, bins, bin_index
                    ),
                    "power_delta_db": (
                        lane_powers[lane][bin_index]
                        - lane_powers[reference_lane][bin_index]
                    ),
                    "phase_delta_deg": phase_delta_deg,
                    "phase_coherence": coherence,
                }
            )
        cross_lane.append(
            {
                "reference_lane": reference_lane,
                "lane": lane,
                "points": points,
            }
        )

    before_counters = counter_view(before)
    after_counters = counter_view(after)
    counter_delta = {key: after_counters[key] - before_counters[key] for key in before_counters}
    if any(value != 0 for value in counter_delta.values()):
        errors.append("RECEIVER_DROP_OR_GAP_DELTA")
    if any(bool(frame["gap_before"]) for frame in frames):
        errors.append("SPECTRUM_GAP_BEFORE")

    evidence = {
        "classification": (
            "T510_RF_SPECTRAL_METRICS_PASS"
            if not errors
            else "T510_RF_SPECTRAL_METRICS_FAIL"
        ),
        "ok": not errors,
        "errors": errors,
        "expected_rf_mhz": args.expected_rf_mhz,
        "center_mhz": center_mhz,
        "sample_rate_hz": sample_rate_hz,
        "bins": bins,
        "bin_width_hz": sample_rate_hz / bins,
        "captures": args.captures,
        "limits": {
            "bin_tolerance": args.bin_tolerance,
            "min_image_rejection_db": args.min_image_rejection_db,
            "max_spur_dbc": args.max_spur_dbc,
            "carrier_exclusion_bins": args.carrier_exclusion_bins,
        },
        "first_frame_id": frames[0]["frame_id"],
        "last_frame_id": frames[-1]["frame_id"],
        "first_sample0": frames[0]["sample0"],
        "last_sample0": frames[-1]["sample0"],
        "lanes": rows,
        "cross_lane": cross_lane,
        "receiver_counters_before": before_counters,
        "receiver_counters_after": after_counters,
        "receiver_counter_delta": counter_delta,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if evidence["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
