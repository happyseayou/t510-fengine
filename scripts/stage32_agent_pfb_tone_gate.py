#!/usr/bin/env python3
"""Stage 32 board-side PFB bin-order and complex-IQ direction gate."""

from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import socket
import struct
import time
import urllib.error
import urllib.request
from typing import Any


def _http_json(
    url: str,
    *,
    body: dict[str, Any] | None = None,
    method: str | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=None if body is None else json.dumps(body).encode("utf-8"),
        headers={} if body is None else {"Content-Type": "application/json"},
        method=method or ("GET" if body is None else "POST"),
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            value = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} from {url}: {payload}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"non-object JSON from {url}")
    result = value.get("result")
    if not isinstance(result, dict):
        raise RuntimeError(f"Agent response has no result object: {value}")
    return result


def _dac_request(
    *,
    board_id: int,
    center_mhz: float,
    tone_mhz: float,
    amplitude_percent: float,
    enabled: bool,
) -> dict[str, Any]:
    return {
        "expected_board_id": board_id,
        "center_mhz": center_mhz,
        "channels": [
            {
                "channel": channel,
                "enabled": enabled,
                "rf_frequency_mhz": tone_mhz,
                "amplitude_percent": amplitude_percent if enabled else 0.0,
                "phase_deg": 0.0,
            }
            for channel in range(8)
        ],
    }


def _configure_receiver(
    base_url: str,
    *,
    sample_rate_msps: int,
    center_mhz: float,
    tone_mhz: float,
) -> dict[str, Any]:
    body = {
        "bandwidth_mhz": sample_rate_msps,
        "output_mode": "spec_only",
        "center_mhz": center_mhz,
        "expected_mhz": tone_mhz,
        "dac_mhz": tone_mhz,
        "target_mhz_by_channel": [tone_mhz] * 8,
    }
    request = urllib.request.Request(
        base_url.rstrip("/") + "/api/config",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=5.0) as response:
        value = json.loads(response.read().decode("utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("receiver config returned non-object JSON")
    return value


def _read_ws_spectrum(host: str, port: int, *, timeout: float) -> dict[str, Any]:
    key = base64.b64encode(os.urandom(16)).decode("ascii")
    request = (
        "GET /ws/spectrum HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n\r\n"
    ).encode("ascii")
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

        def take(count: int) -> bytes:
            while len(buffered) < count:
                chunk = stream.recv(max(4096, count - len(buffered)))
                if not chunk:
                    raise RuntimeError("receiver WebSocket closed before a spectrum frame")
                buffered.extend(chunk)
            value = bytes(buffered[:count])
            del buffered[:count]
            return value

        while True:
            first, second = take(2)
            opcode = first & 0x0F
            length = second & 0x7F
            if second & 0x80:
                raise RuntimeError("server-to-client WebSocket frame must not be masked")
            if length == 126:
                length = struct.unpack(">H", take(2))[0]
            elif length == 127:
                length = struct.unpack(">Q", take(8))[0]
            payload = take(length)
            if opcode == 2:
                break
            if opcode == 8:
                raise RuntimeError("receiver WebSocket closed before binary spectrum")

    if len(payload) < 128 or struct.unpack_from("<I", payload, 0)[0] != 0x33505354:
        raise RuntimeError("receiver spectrum frame has invalid header")
    header_bytes = struct.unpack_from("<H", payload, 6)[0]
    lane_count = struct.unpack_from("<I", payload, 56)[0]
    bins = struct.unpack_from("<I", payload, 60)[0]
    if header_bytes < 128 or lane_count == 0 or bins == 0:
        raise RuntimeError("receiver spectrum frame has invalid geometry")
    lanes = []
    offset = header_bytes
    for lane in range(lane_count):
        lane_bytes = bins * 12
        if offset + lane_bytes > len(payload):
            raise RuntimeError("receiver spectrum frame is truncated")
        amplitude = struct.unpack_from(f"<{bins}f", payload, offset)
        phase_offset = offset + bins * 4
        power_offset = phase_offset + bins * 4
        power = struct.unpack_from(f"<{bins}f", payload, power_offset)
        peak_bin = max(range(bins), key=power.__getitem__)
        lanes.append(
            {
                "lane": lane,
                "peak_bin": peak_bin,
                "peak_power_db": power[peak_bin],
                "peak_amplitude": amplitude[peak_bin],
                "peak_phase_rad": struct.unpack_from("<f", payload, phase_offset + peak_bin * 4)[0],
            }
        )
        offset += lane_bytes
    return {
        "sample0": struct.unpack_from("<Q", payload, 8)[0],
        "frame_id": struct.unpack_from("<Q", payload, 16)[0],
        "gap_before": bool(struct.unpack_from("<I", payload, 28)[0]),
        "lane_count": lane_count,
        "bins": bins,
        "nchan": struct.unpack_from("<I", payload, 68)[0],
        "block_count": struct.unpack_from("<I", payload, 76)[0],
        "pfb_taps": struct.unpack_from("<I", payload, 80)[0],
        "sample_rate_hz": struct.unpack_from("<I", payload, 92)[0],
        "coverage_blocks": struct.unpack_from("<I", payload, 96)[0],
        "lanes": lanes,
    }


def _compact(status: dict[str, Any]) -> dict[str, Any]:
    return {
        key: status.get(key)
        for key in (
            "captured_at_unix_ms",
            "core_version",
            "streaming",
            "profile",
            "clock",
            "mts",
            "halfband",
            "channelizer",
            "qsfp",
            "pipeline",
            "counters",
        )
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent-base", default="http://192.168.100.117:8010")
    parser.add_argument("--receiver-base", default="http://192.168.100.162:8089")
    parser.add_argument("--receiver-host", default="192.168.100.162")
    parser.add_argument("--receiver-port", type=int, default=8089)
    parser.add_argument("--board-id", type=int, default=1)
    parser.add_argument("--center-mhz", type=float, default=100.0)
    parser.add_argument("--tone-mhz", type=float, default=120.0)
    parser.add_argument("--sample-rate-msps", type=float, default=160.0)
    parser.add_argument("--fft-size", type=int, default=4096)
    parser.add_argument("--amplitude-percent", type=float, default=25.0)
    parser.add_argument("--settle-seconds", type=float, default=3.0)
    parser.add_argument("--observe-seconds", type=float, default=3.0)
    parser.add_argument("--bin-tolerance", type=int, default=1)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    base = args.agent_base.rstrip("/")
    expected_signed_bin = round(
        (args.tone_mhz - args.center_mhz) * args.fft_size / args.sample_rate_msps
    )
    expected_bin = expected_signed_bin % args.fft_size
    mirrored_bin = (-expected_signed_bin) % args.fft_size
    evidence: dict[str, Any] = {
        "classification": "STAGE32_PFB_TONE_IN_PROGRESS",
        "ok": False,
        "stage": 32,
        "center_mhz": args.center_mhz,
        "tone_mhz": args.tone_mhz,
        "sample_rate_msps": args.sample_rate_msps,
        "fft_size": args.fft_size,
        "channel_spacing_hz": args.sample_rate_msps * 1.0e6 / args.fft_size,
        "expected_signed_bin": expected_signed_bin,
        "expected_bin": expected_bin,
        "mirrored_bin_if_iq_reversed": mirrored_bin,
        "errors": [],
    }
    started = False
    dac_enabled = False
    try:
        idle = _http_json(base + "/api/v1/status")
        profile = idle.get("profile", {})
        if int(profile.get("bandwidth_mhz", 0)) != round(args.sample_rate_msps):
            raise RuntimeError(f"board sample-rate profile mismatch: {profile}")
        if str(profile.get("mode")) not in ("spec_only", "time_spec"):
            raise RuntimeError(f"board is not in a SPEC-producing mode: {profile}")
        evidence["idle"] = _compact(idle)
        evidence["receiver_config"] = _configure_receiver(
            args.receiver_base,
            sample_rate_msps=round(args.sample_rate_msps),
            center_mhz=args.center_mhz,
            tone_mhz=args.tone_mhz,
        )

        evidence["dac_on"] = _http_json(
            base + "/api/v1/dac",
            body=_dac_request(
                board_id=args.board_id,
                center_mhz=args.center_mhz,
                tone_mhz=args.tone_mhz,
                amplitude_percent=args.amplitude_percent,
                enabled=True,
            ),
            method="PUT",
        )
        dac_enabled = True
        _http_json(
            base + "/api/v1/start",
            body={"expected_board_id": args.board_id},
        )
        started = True
        time.sleep(max(args.settle_seconds, 0.1))
        before = _http_json(base + "/api/v1/status")
        spectrum = _read_ws_spectrum(
            args.receiver_host,
            args.receiver_port,
            timeout=max(args.observe_seconds + 5.0, 8.0),
        )
        time.sleep(max(args.observe_seconds, 0.1))
        after = _http_json(base + "/api/v1/status")
        evidence["before"] = _compact(before)
        evidence["after"] = _compact(after)
        evidence["receiver_spectrum"] = spectrum

        channelizer = after.get("channelizer", {})
        errors: list[str] = []
        frame_delta = int(channelizer.get("frame_count", 0)) - int(
            before.get("channelizer", {}).get("frame_count", 0)
        )
        peak_bins = [int(lane["peak_bin"]) for lane in spectrum["lanes"]]
        evidence["observed_peak_bins"] = peak_bins
        evidence["board_peak_register_diagnostic"] = {
            "peak_chan": int(channelizer.get("peak_chan", 0)),
            "peak_power": int(channelizer.get("peak_power", 0)),
            "used_for_acceptance": False,
        }
        evidence["frame_count_delta"] = frame_delta
        peak_bin_errors = [
            min(
                (peak_bin - expected_bin) % args.fft_size,
                (expected_bin - peak_bin) % args.fft_size,
            )
            for peak_bin in peak_bins
        ]
        evidence["peak_bin_errors"] = peak_bin_errors
        if len(peak_bins) != 8:
            errors.append("SPEC_LANE_COUNT_NOT_8")
        if any(error > args.bin_tolerance for error in peak_bin_errors):
            errors.append("PFB_PEAK_BIN_MISMATCH")
        if any(peak_bin == mirrored_bin for peak_bin in peak_bins) and mirrored_bin != expected_bin:
            errors.append("PFB_COMPLEX_IQ_DIRECTION_REVERSED")
        if int(spectrum.get("bins", 0)) != args.fft_size:
            errors.append("SPEC_SNAPSHOT_BIN_COUNT_MISMATCH")
        if int(spectrum.get("sample_rate_hz", 0)) != round(args.sample_rate_msps * 1.0e6):
            errors.append("SPEC_SNAPSHOT_SAMPLE_RATE_MISMATCH")
        if int(spectrum.get("coverage_blocks", 0)) < int(spectrum.get("block_count", 16)):
            errors.append("SPEC_SNAPSHOT_INCOMPLETE")
        if bool(spectrum.get("gap_before")):
            errors.append("SPEC_SNAPSHOT_GAP_BEFORE")
        if frame_delta <= 0:
            errors.append("PFB_FRAME_COUNT_NOT_ADVANCING")
        if int(channelizer.get("nchan", 0)) != args.fft_size:
            errors.append("PFB_FFT_SIZE_MISMATCH")
        if int(channelizer.get("taps", 0)) != 4:
            errors.append("PFB_TAPS_NOT_4")
        for key in (
            "overflow_count",
            "data_halt_count",
            "xfft_event_count",
            "tile_overflow_count",
            "xfft_tlast_unexpected_count",
            "xfft_tlast_missing_count",
            "xfft_fft_overflow_count",
            "xfft_data_out_halt_count",
            "xfft_status_halt_count",
            "capture_backpressure_count",
            "frame_sample0_overflow_count",
            "coefficient_error_count",
        ):
            if int(channelizer.get(key, 0)) != 0:
                errors.append(f"NONZERO_{key.upper()}")
        evidence["errors"] = errors
        evidence["ok"] = not errors
        evidence["classification"] = (
            "STAGE32_160MSPS_PFB_BIN_IQ_BOARD_PASS"
            if evidence["ok"]
            else "STAGE32_160MSPS_PFB_BIN_IQ_BOARD_FAIL"
        )
    except Exception as exc:
        evidence["errors"].append(f"{type(exc).__name__}: {exc}")
    finally:
        if started:
            try:
                evidence["stop"] = _http_json(
                    base + "/api/v1/stop",
                    body={"reason": "stage32_pfb_tone_gate_complete"},
                )
            except Exception as exc:
                evidence["errors"].append(f"STOP_FAILED: {type(exc).__name__}: {exc}")
                evidence["ok"] = False
        if dac_enabled:
            try:
                evidence["dac_off"] = _http_json(
                    base + "/api/v1/dac",
                    body=_dac_request(
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
        if not evidence["ok"]:
            evidence["classification"] = "STAGE32_160MSPS_PFB_BIN_IQ_BOARD_FAIL"
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(evidence, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if evidence["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
