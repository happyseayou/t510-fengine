#!/usr/bin/env python3
"""Run and analyze the current T510 eight-lane full-band SPEC UDP spur scan."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys
import time
import urllib.error
import urllib.request
from typing import Any

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.t510_plot_spec_udp_pcap import (
    SPEC_NCHAN,
    collect_spectra,
    signed_bin,
)


SAMPLE_RATE_HZ = 320_000_000
BIN_WIDTH_HZ = SAMPLE_RATE_HZ / SPEC_NCHAN
BIN_WIDTH_MHZ = BIN_WIDTH_HZ / 1.0e6
FULL_BAND_BINS = 24_576
CENTERS_MHZ = tuple(float(value) for value in range(160, 1761, 80))
CONDITIONS = ("muted", "tone_25", "tone_100")
AMPLITUDE_BY_CONDITION = {"muted": 0.0, "tone_25": 25.0, "tone_100": 100.0}
CAPTURE_PORTS = tuple(range(4308, 4324))
CAPTURE_PACKETS_PER_PORT = 32
FULL_SCALE_DB = 20.0 * math.log10(32768.0)
CARRIER_SIGNED_BIN = -768
CARRIER_BIN = CARRIER_SIGNED_BIN % SPEC_NCHAN
KNOWN_SPURS_MHZ = (160.0, 480.0, 960.0, 1120.0, 1280.0, 1440.0, 1600.0)

BOARD_COUNTER_KEYS = (
    "rfdc_dropped",
    "science_dropped_beats",
    "time_dropped",
    "spec_dropped",
    "tx_frames_dropped",
    "tx_route_error",
    "tx_route_miss",
)
CHANNELIZER_COUNTER_KEYS = (
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
RECEIVER_COUNTER_KEYS = (
    "parse_errors",
    "kernel_drops",
    "ring_drops",
    "worker_ring_drops",
    "app_drops",
    "seq_gaps",
    "frame_gaps",
    "sample0_gaps",
    "spec_seq_gaps",
    "spec_frame_gaps",
)


def scan_centers() -> tuple[float, ...]:
    return CENTERS_MHZ


def tone_frequency_mhz(center_mhz: float) -> float:
    return float(center_mhz) - 60.0


def campaign_windows() -> list[dict[str, Any]]:
    preflight = [(condition, CENTERS_MHZ[0]) for condition in CONDITIONS]
    remaining = [
        (condition, center)
        for condition in CONDITIONS
        for center in CENTERS_MHZ[1:]
    ]
    return [
        {
            "index": index,
            "condition": condition,
            "center_mhz": center,
            "tone_mhz": None if condition == "muted" else tone_frequency_mhz(center),
            "amplitude_percent": AMPLITUDE_BY_CONDITION[condition],
            "preflight": index < len(preflight),
        }
        for index, (condition, center) in enumerate(preflight + remaining)
    ]


def db_code_to_dbfs(value: float) -> float:
    return float(value) - FULL_SCALE_DB


def circular_bin_distance(left: int, right: int, bins: int = SPEC_NCHAN) -> int:
    delta = (left - right) % bins
    return min(delta, bins - delta)


def first_nyquist_fold_mhz(frequency_mhz: float) -> float:
    wrapped = float(frequency_mhz) % 3840.0
    return min(wrapped, 3840.0 - wrapped)


def _http_json(
    url: str,
    *,
    method: str = "GET",
    body: dict[str, Any] | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=None if body is None else json.dumps(body).encode("utf-8"),
        headers={"Accept": "application/json", **({} if body is None else {"Content-Type": "application/json"})},
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


def _http_bytes(
    url: str,
    *,
    method: str = "GET",
    body: dict[str, Any] | None = None,
    timeout: float = 30.0,
) -> bytes:
    request = urllib.request.Request(
        url,
        data=None if body is None else json.dumps(body).encode("utf-8"),
        headers={
            "Accept": "application/vnd.tcpdump.pcap",
            **({} if body is None else {"Content-Type": "application/json"}),
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} from {url}: {payload}") from exc


def _receiver_prepare(
    receiver_base: str, center_mhz: float, tone_mhz: float | None
) -> dict[str, Any]:
    display_frequency = center_mhz if tone_mhz is None else tone_mhz
    body = {
        "sample_rate_msps": 320,
        "output_mode": "spec_only",
        "center_mhz": center_mhz,
        "expected_mhz": display_frequency,
        "dac_mhz": display_frequency,
        "target_mhz_by_channel": [display_frequency] * 8,
        "channel_mask": 0xFF,
        "paused": False,
    }
    return _http_json(receiver_base.rstrip("/") + "/api/config", method="POST", body=body)


def _configure_body(template: dict[str, Any], center_mhz: float) -> dict[str, Any]:
    body = json.loads(json.dumps(template))
    body["board_id"] = 1
    body["profile"] = {
        "sample_rate_msps": 320,
        "mode": "spec_only",
        "center_mhz": center_mhz,
    }
    for endpoint in body.get("endpoints", []):
        endpoint["enabled"] = str(endpoint.get("stream", "")).upper() == "SPEC"
    return body


def _dac_body(
    center_mhz: float,
    tone_mhz: float | None,
    amplitude: float,
    *,
    expected_board_id: int = 1,
) -> dict[str, Any]:
    enabled = tone_mhz is not None and amplitude > 0.0
    frequency = float(tone_mhz if tone_mhz is not None else center_mhz)
    return {
        "expected_board_id": expected_board_id,
        "center_mhz": center_mhz,
        "channels": [
            {
                "channel": lane,
                "enabled": enabled,
                "rf_frequency_mhz": frequency,
                "amplitude_percent": amplitude if enabled else 0.0,
                "phase_deg": 0.0,
            }
            for lane in range(8)
        ],
    }


def _counter_delta(before: dict[str, Any], after: dict[str, Any], keys: tuple[str, ...]) -> dict[str, int]:
    return {
        key: int(after.get(key, 0) or 0) - int(before.get(key, 0) or 0)
        for key in keys
    }


def _window_name(condition: str, center_mhz: float) -> str:
    return f"{condition}_center_{int(round(center_mhz)):04d}mhz"


def _resume_campaign(
    campaign_path: Path, expected_windows: list[dict[str, Any]]
) -> tuple[dict[str, Any], list[dict[str, Any]], int]:
    """Load a strict successful prefix and rebuild analysis inputs from its PCAPs."""
    evidence = json.loads(campaign_path.read_text())
    completed = evidence.get("windows", [])
    if not isinstance(completed, list) or len(completed) > len(expected_windows):
        raise RuntimeError("resume campaign has an invalid window list")
    decoded_windows: list[dict[str, Any]] = []
    for index, record in enumerate(completed):
        expected = expected_windows[index]
        expected_name = _window_name(str(expected["condition"]), float(expected["center_mhz"]))
        if (
            not isinstance(record, dict)
            or not record.get("ok")
            or record.get("name") != expected_name
            or record.get("condition") != expected["condition"]
            or float(record.get("center_mhz", -1.0)) != float(expected["center_mhz"])
        ):
            raise RuntimeError(f"resume window {index + 1} is not the required successful prefix")
        local_dir = Path(str(record.get("local_dir", "")))
        paths = sorted(local_dir.glob("*.pcap"))
        if not paths:
            raise RuntimeError(f"resume PCAP is missing for {expected_name}")
        decoded = decode_window(paths)
        decoded_windows.append({**expected, "power_dbfs": decoded["power_dbfs"]})
    previous = {
        "classification": evidence.get("classification"),
        "errors": list(evidence.get("errors", [])),
        "window_count": len(completed),
        "resumed_at_unix_ms": int(time.time() * 1000),
    }
    evidence.setdefault("resume_history", []).append(previous)
    evidence["classification"] = "T510_FULLBAND_SPUR_SCAN_IN_PROGRESS"
    evidence["ok"] = False
    evidence["errors"] = []
    evidence.pop("analysis", None)
    campaign_path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
    return evidence, decoded_windows, len(completed)


def _final_stop_and_mute(args: argparse.Namespace, fallback_center_mhz: float) -> list[str]:
    """Best-effort safe shutdown that also works after board_id changes to zero."""
    errors: list[str] = []
    try:
        _http_json(args.agent_base.rstrip("/") + "/api/v2/stop", method="POST")
    except Exception as exc:
        errors.append(f"FINAL_STOP_FAILED: {type(exc).__name__}: {exc}")
    board_id = 1
    center_mhz = fallback_center_mhz
    status: dict[str, Any] | None = None
    try:
        status = _http_json(
            args.agent_base.rstrip("/") + "/api/v2/status", timeout=30.0
        )
        board_id = int(status.get("board_id", board_id))
        center_mhz = float(status.get("profile", {}).get("center_mhz", center_mhz))
    except Exception as exc:
        errors.append(f"FINAL_STATUS_FAILED: {type(exc).__name__}: {exc}")
    try:
        dac = (status or {}).get("dac", {})
        channels = dac.get("channels", [])
        already_safe = (
            status is not None
            and not bool(status.get("streaming"))
            and not bool(status.get("pipeline", {}).get("stream_accepting"))
            and int(dac.get("enable_mask", -1)) == 0
            and len(channels) == 8
            and not any(
                bool(channel.get("enabled"))
                or int(channel.get("amplitude_code", -1)) != 0
                for channel in channels
            )
        )
        if already_safe:
            return errors

        sample_rate_msps = int(
            (status or {}).get("profile", {}).get("sample_rate_msps", 0) or 0
        )
        if sample_rate_msps in (160, 320):
            lower_mhz = sample_rate_msps / 2.0
            upper_mhz = 1920.0 - lower_mhz
            center_mhz = min(max(center_mhz, lower_mhz), upper_mhz)
        _http_json(
            args.agent_base.rstrip("/") + "/api/v2/dac",
            method="PUT",
            body=_dac_body(center_mhz, None, 0.0, expected_board_id=board_id),
        )
        status = _http_json(
            args.agent_base.rstrip("/") + "/api/v2/status", timeout=30.0
        )
        dac = status.get("dac", {})
        channels = dac.get("channels", [])
        if int(dac.get("enable_mask", -1)) != 0 or len(channels) != 8 or any(
            bool(channel.get("enabled")) or int(channel.get("amplitude_code", -1)) != 0
            for channel in channels
        ):
            raise RuntimeError(f"DAC mute readback mismatch: {dac}")
        if bool(status.get("streaming")) or bool(
            status.get("pipeline", {}).get("stream_accepting")
        ):
            raise RuntimeError("STOP readback mismatch after final shutdown")
    except Exception as exc:
        errors.append(f"FINAL_DAC_MUTE_FAILED: {type(exc).__name__}: {exc}")
    return errors


def capture_receiver_pcap(
    *,
    receiver_base: str,
    local_dir: Path,
    packets_per_block: int,
    include_time: bool = False,
) -> tuple[list[Path], dict[str, Any]]:
    """Export raw Ethernet frames from the receiver's existing PACKET_MMAP ring."""
    local_dir.mkdir(parents=True, exist_ok=True)
    request_body = {"packets_per_block": packets_per_block}
    if include_time:
        request_body["include_time"] = True
    pcap = _http_bytes(
        receiver_base.rstrip("/") + "/api/capture/spec-pcap",
        method="POST",
        body=request_body,
        timeout=20.0,
    )
    if len(pcap) < 24 or pcap[:4] != b"\xd4\xc3\xb2\xa1":
        raise RuntimeError("receiver returned an invalid classic PCAP payload")
    path = local_dir / (
        "time_spec_4300_4323.pcap" if include_time else "spec_4308_4323.pcap"
    )
    path.write_bytes(pcap)
    return [path], {
        "method": "receiver_packet_mmap_raw_export",
        "packets_per_block": packets_per_block,
        "include_time": bool(include_time),
        "ports": "4300..4323" if include_time else "4308..4323",
        "pcap_bytes": len(pcap),
        "sha256": hashlib.sha256(pcap).hexdigest(),
    }


def decode_window(paths: list[Path]) -> dict[str, Any]:
    capture = collect_spectra(paths)
    if int(capture["packet_count"]) != len(CAPTURE_PORTS) * CAPTURE_PACKETS_PER_PORT:
        raise RuntimeError(f"unexpected packet count {capture['packet_count']}")
    if list(capture["block_packets"]) != [CAPTURE_PACKETS_PER_PORT] * len(CAPTURE_PORTS):
        raise RuntimeError(f"unbalanced SPEC blocks {capture['block_packets']}")
    if int(capture["sample_rate_hz"]) != SAMPLE_RATE_HZ:
        raise RuntimeError(f"unexpected SPEC sample rate {capture['sample_rate_hz']}")
    if int(capture["pfb_taps"]) != 8:
        raise RuntimeError(f"unexpected PFB taps {capture['pfb_taps']}")
    power_db_code = capture.pop("power_db")
    power_dbfs = [[db_code_to_dbfs(value) for value in lane] for lane in power_db_code]
    return {"power_dbfs": power_dbfs, "capture": capture}


def _median_power_db(values_db: list[float]) -> float:
    powers = [10.0 ** (value / 10.0) for value in values_db]
    return 10.0 * math.log10(max(statistics.median(powers), 1.0e-30))


def stitch_muted(windows: list[dict[str, Any]]) -> list[list[float]]:
    stitched = [[-300.0] * FULL_BAND_BINS for _ in range(8)]
    for global_bin in range(FULL_BAND_BINS):
        observations: list[tuple[int, list[float]]] = []
        for window in windows:
            center_bin = round(float(window["center_mhz"]) / BIN_WIDTH_MHZ)
            offset = global_bin - center_bin
            if not -SPEC_NCHAN // 2 <= offset < SPEC_NCHAN // 2:
                continue
            edge = global_bin < 512 or global_bin >= FULL_BAND_BINS - 512
            if not edge and (abs(offset) < 13 or abs(offset) > 1536):
                continue
            index = offset % SPEC_NCHAN
            observations.append((abs(offset), [window["power_dbfs"][lane][index] for lane in range(8)]))
        if not observations:
            for window in windows:
                center_bin = round(float(window["center_mhz"]) / BIN_WIDTH_MHZ)
                offset = global_bin - center_bin
                if -SPEC_NCHAN // 2 <= offset < SPEC_NCHAN // 2 and abs(offset) >= 13:
                    index = offset % SPEC_NCHAN
                    observations.append((abs(offset), [window["power_dbfs"][lane][index] for lane in range(8)]))
        if not observations:
            continue
        best_distance = min(value[0] for value in observations)
        selected = [values for distance, values in observations if distance <= max(best_distance, 1536)]
        for lane in range(8):
            stitched[lane][global_bin] = _median_power_db([values[lane] for values in selected])
    return stitched


def local_prominence(values: list[float], index: int, radius: int = 26, guard: int = 2) -> tuple[float, float]:
    background = [
        values[pos]
        for pos in range(max(0, index - radius), min(len(values), index + radius + 1))
        if abs(pos - index) > guard
    ]
    median = statistics.median(background) if background else values[index]
    return values[index] - median, median


def _spur_reproductions(
    windows: list[dict[str, Any]], lane: int, global_bin: int
) -> list[dict[str, float]]:
    rows = []
    for window in windows:
        center_bin = round(float(window["center_mhz"]) / BIN_WIDTH_MHZ)
        offset = global_bin - center_bin
        if not -1536 <= offset <= 1536 or abs(offset) < 13:
            continue
        index = offset % SPEC_NCHAN
        prominence, _ = local_prominence(window["power_dbfs"][lane], index)
        if prominence >= 6.0:
            rows.append(
                {
                    "center_mhz": float(window["center_mhz"]),
                    "prominence_db": prominence,
                }
            )
    return rows


def find_spurs(stitched: list[list[float]], windows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for lane, values in enumerate(stitched):
        candidates = []
        for index in range(26, len(values) - 26):
            prominence, background = local_prominence(values, index)
            if prominence >= 6.0:
                candidates.append((index, values[index], prominence, background))
        clusters: list[list[tuple[int, float, float, float]]] = []
        for candidate in candidates:
            if not clusters or candidate[0] - clusters[-1][-1][0] > 3:
                clusters.append([candidate])
            else:
                clusters[-1].append(candidate)
        for cluster in clusters:
            peak = max(cluster, key=lambda item: item[1])
            rf_mhz = peak[0] * BIN_WIDTH_MHZ
            reproductions = _spur_reproductions(windows, lane, peak[0])
            lower_confidence_edge = rf_mhz < 40.0 or rf_mhz >= 1880.0
            if len(reproductions) < (1 if lower_confidence_edge else 2):
                continue
            rows.append(
                {
                    "lane": lane,
                    "rf_mhz": rf_mhz,
                    "power_dbfs": peak[1],
                    "prominence_db": peak[2],
                    "local_median_dbfs": peak[3],
                    "cluster_bins": len(cluster),
                    "lower_confidence_edge": lower_confidence_edge,
                    "reproduced_window_count": len(reproductions),
                    "reproductions": reproductions,
                }
            )
    return sorted(rows, key=lambda row: float(row["prominence_db"]), reverse=True)


def tone_metrics(windows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for window in windows:
        tone_mhz = float(window["tone_mhz"])
        center_mhz = float(window["center_mhz"])
        image_bin = (-CARRIER_SIGNED_BIN) % SPEC_NCHAN
        harmonic_mhz = first_nyquist_fold_mhz(2.0 * tone_mhz)
        harmonic_offset = round((harmonic_mhz - center_mhz) / BIN_WIDTH_MHZ)
        for lane, power in enumerate(window["power_dbfs"]):
            carrier = power[CARRIER_BIN]
            eligible = [index for index in range(SPEC_NCHAN) if circular_bin_distance(index, CARRIER_BIN) > 4]
            spur_bin = max(eligible, key=power.__getitem__)
            noise_bins = [
                index
                for index in range(SPEC_NCHAN)
                if 13 <= abs(signed_bin(index, SPEC_NCHAN)) <= 1536
                and circular_bin_distance(index, CARRIER_BIN) > 8
            ]
            noise_values = sorted(power[index] for index in noise_bins)
            median_noise = statistics.median(noise_values)
            noise_p95 = noise_values[min(len(noise_values) - 1, round(0.95 * (len(noise_values) - 1)))]
            row = {
                "condition": window["condition"],
                "amplitude_percent": window["amplitude_percent"],
                "center_mhz": center_mhz,
                "tone_mhz": tone_mhz,
                "lane": lane,
                "carrier_bin": CARRIER_BIN,
                "carrier_dbfs": carrier,
                "median_noise_floor_dbfs_per_bin": median_noise,
                "noise_p95_dbfs_per_bin": noise_p95,
                "carrier_to_median_noise_db": carrier - median_noise,
                "worst_spur_bin": spur_bin,
                "worst_spur_rf_mhz": center_mhz + signed_bin(spur_bin, SPEC_NCHAN) * BIN_WIDTH_MHZ,
                "worst_spur_dbfs": power[spur_bin],
                "worst_spur_dbc": power[spur_bin] - carrier,
                "image_rf_mhz": center_mhz - CARRIER_SIGNED_BIN * BIN_WIDTH_MHZ,
                "image_dbc": power[image_bin] - carrier,
                "second_harmonic_rf_mhz": harmonic_mhz,
                "second_harmonic_dbc": None,
            }
            if -SPEC_NCHAN // 2 <= harmonic_offset < SPEC_NCHAN // 2:
                row["second_harmonic_dbc"] = power[harmonic_offset % SPEC_NCHAN] - carrier
            rows.append(row)
    return rows


def draw_tone_spectrum_atlas(
    path: Path,
    windows: list[dict[str, Any]],
    metrics: list[dict[str, Any]],
    condition: str,
) -> None:
    selected = sorted(
        (window for window in windows if window["condition"] == condition),
        key=lambda window: float(window["tone_mhz"]),
    )
    amplitude = "25%" if condition == "tone_25" else "100%"
    width, height = 2700, 2820
    image = Image.new("RGB", (width, height), "#f8fafc")
    draw = ImageDraw.Draw(image)
    draw.text((55, 24), f"T510 {amplitude} DAC tone spectra — all 8 ADC lanes", fill="#0f172a", font=_font(36, True))
    draw.text(
        (55, 72),
        "Absolute dBFS; NF is median power per 78.125 kHz bin after 32-frame averaging; carrier guard +/-8 bins",
        fill="#334155",
        font=_font(20),
    )
    colors = ("#2563eb", "#dc2626", "#059669", "#7c3aed", "#ea580c", "#0891b2", "#be185d", "#4d7c0f")
    draw.text((55, 104), "  ".join(f"ADC{lane}" for lane in range(8)), fill="#475569", font=_font(17))
    panel_w, panel_h = 865, 370
    for panel_index, window in enumerate(selected):
        row, col = divmod(panel_index, 3)
        left = 35 + col * 890
        top = 142 + row * 378
        right, bottom = left + panel_w, top + panel_h
        draw.rounded_rectangle((left, top, right, bottom), 8, fill="white", outline="#cbd5e1", width=2)
        pl, pt, pr, pb = left + 56, top + 66, right - 18, bottom - 38
        center = float(window["center_mhz"])
        tone = float(window["tone_mhz"])
        window_rows = [
            value
            for value in metrics
            if value["condition"] == condition and float(value["center_mhz"]) == center
        ]
        carriers = [float(value["carrier_dbfs"]) for value in window_rows]
        floors = [float(value["median_noise_floor_dbfs_per_bin"]) for value in window_rows]
        worst_spur = max(float(value["worst_spur_dbc"]) for value in window_rows)
        draw.text((left + 12, top + 8), f"Tone {tone:.0f} MHz  |  center {center:.0f} MHz", fill="#0f172a", font=_font(18, True))
        draw.text(
            (left + 12, top + 33),
            f"Carrier {min(carriers):.2f}..{max(carriers):.2f} dBFS   NF {min(floors):.2f}..{max(floors):.2f} dBFS/bin   worst spur {worst_spur:.2f} dBc",
            fill="#475569",
            font=_font(14),
        )
        for level in (-100, -80, -60, -40, -20, 0):
            y = round(pb - (level + 110.0) / 115.0 * (pb - pt))
            draw.line((pl, y, pr, y), fill="#e2e8f0")
            draw.text((left + 5, y - 8), str(level), fill="#64748b", font=_font(12))
        for offset in (-160, -80, 0, 80, 160):
            x = round(pl + (offset + 160.0) / 320.0 * (pr - pl))
            draw.line((x, pt, x, pb), fill="#f1f5f9")
            draw.text((x - 24, pb + 8), f"{center + offset:.0f}", fill="#64748b", font=_font(12))
        carrier_x = round(pl + ((tone - center) + 160.0) / 320.0 * (pr - pl))
        draw.line((carrier_x, pt, carrier_x, pb), fill="#f59e0b", width=2)
        median_floor = statistics.median(floors)
        floor_y = round(pb - (min(max(median_floor, -110.0), 5.0) + 110.0) / 115.0 * (pb - pt))
        for x in range(pl, pr, 12):
            draw.line((x, floor_y, min(x + 6, pr), floor_y), fill="#64748b")
        plot_width = pr - pl + 1
        for lane, power in enumerate(window["power_dbfs"]):
            columns: list[list[float]] = [[] for _ in range(plot_width)]
            for index, value in enumerate(power):
                signed = signed_bin(index, SPEC_NCHAN)
                x = min(plot_width - 1, round((signed + 2048) / 4095 * (plot_width - 1)))
                columns[x].append(value)
            points = []
            for x, values in enumerate(columns):
                if not values:
                    continue
                value = max(values)
                y = round(pb - (min(max(value, -110.0), 5.0) + 110.0) / 115.0 * (pb - pt))
                points.append((pl + x, y))
            if len(points) > 1:
                draw.line(points, fill=colors[lane], width=1)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, optimize=True)


def amplitude_linearity(metrics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    indexed = {(row["condition"], row["center_mhz"], row["lane"]): row for row in metrics}
    rows = []
    for center in CENTERS_MHZ:
        for lane in range(8):
            low = indexed[("tone_25", center, lane)]
            high = indexed[("tone_100", center, lane)]
            rows.append(
                {
                    "center_mhz": center,
                    "tone_mhz": tone_frequency_mhz(center),
                    "lane": lane,
                    "carrier_25_dbfs": low["carrier_dbfs"],
                    "carrier_100_dbfs": high["carrier_dbfs"],
                    "increase_db": high["carrier_dbfs"] - low["carrier_dbfs"],
                    "error_from_12p04_db": high["carrier_dbfs"] - low["carrier_dbfs"] - 12.04,
                    "worst_spur_25_dbc": low["worst_spur_dbc"],
                    "worst_spur_100_dbc": high["worst_spur_dbc"],
                }
            )
    return rows


def _font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    path = Path("/usr/share/fonts/truetype/dejavu") / name
    return ImageFont.truetype(str(path), size) if path.exists() else ImageFont.load_default()


def _panels(title: str, subtitle: str) -> tuple[Image.Image, ImageDraw.ImageDraw, list[tuple[int, int, int, int]]]:
    width, height = 2400, 1900
    image = Image.new("RGB", (width, height), "#f8fafc")
    draw = ImageDraw.Draw(image)
    draw.text((70, 28), title, fill="#0f172a", font=_font(38, True))
    draw.text((70, 78), subtitle, fill="#334155", font=_font(22))
    panels = []
    for lane in range(8):
        row, col = divmod(lane, 2)
        left = 60 + col * 1180
        top = 135 + row * 430
        panels.append((left, top, left + 1120, top + 390))
    return image, draw, panels


def draw_muted_plot(path: Path, stitched: list[list[float]], spurs: list[dict[str, Any]]) -> None:
    image, draw, panels = _panels(
        "T510 eight-lane ADC full-band spectrum: DAC muted",
        "320 MS/s overlapping raw QSFP SPEC UDP windows; absolute dBFS; shaded edges are lower confidence",
    )
    y_min = min(-100.0, math.floor(min(min(lane) for lane in stitched) / 10.0) * 10.0)
    y_max = max(-60.0, math.ceil(max(max(lane) for lane in stitched) / 10.0) * 10.0)
    for lane, (left, top, right, bottom) in enumerate(panels):
        draw.rounded_rectangle((left, top, right, bottom), 10, fill="white", outline="#cbd5e1", width=2)
        pl, pt, pr, pb = left + 70, top + 42, right - 22, bottom - 48
        draw.text((left + 16, top + 10), f"ADC{lane}", fill="#0f172a", font=_font(22, True))
        draw.rectangle((pl, pt, pl + round((40.0 / 1920.0) * (pr - pl)), pb), fill="#fef3c7")
        draw.rectangle((pr - round((40.0 / 1920.0) * (pr - pl)), pt, pr, pb), fill="#fef3c7")
        for rf in range(0, 1921, 240):
            x = round(pl + rf / 1920.0 * (pr - pl))
            draw.line((x, pt, x, pb), fill="#e2e8f0")
            draw.text((x - 16, pb + 8), str(rf), fill="#475569", font=_font(15))
        for marker in KNOWN_SPURS_MHZ:
            x = round(pl + marker / 1920.0 * (pr - pl))
            draw.line((x, pt, x, pb), fill="#fdba74", width=1)
        columns: list[list[float]] = [[] for _ in range(pr - pl + 1)]
        for index, value in enumerate(stitched[lane]):
            x = round(index / (FULL_BAND_BINS - 1) * (pr - pl))
            columns[x].append(value)
        previous = None
        for offset, values in enumerate(columns):
            if not values:
                continue
            value = max(values)
            y = round(pb - (min(max(value, y_min), y_max) - y_min) / (y_max - y_min) * (pb - pt))
            point = (pl + offset, y)
            if previous is not None:
                draw.line((*previous, *point), fill="#2563eb", width=2)
            previous = point
        lane_spurs = [row for row in spurs if row["lane"] == lane][:3]
        label = "  ".join(f"{row['rf_mhz']:.2f}MHz {row['prominence_db']:+.1f}dB" for row in lane_spurs)
        draw.text((pl, pt + 4), label, fill="#b45309", font=_font(14))
        draw.text((pl - 60, pt), f"{y_max:.0f}", fill="#475569", font=_font(14))
        draw.text((pl - 60, pb - 14), f"{y_min:.0f}", fill="#475569", font=_font(14))
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, optimize=True)


def draw_tone_plot(path: Path, metrics: list[dict[str, Any]]) -> None:
    image, draw, panels = _panels(
        "T510 DAC-to-ADC tone sweep: carrier and worst spur",
        "Solid: carrier dBFS (25% blue, 100% red); dashed: worst spur dBc (25% cyan, 100% orange)",
    )
    for lane, (left, top, right, bottom) in enumerate(panels):
        draw.rounded_rectangle((left, top, right, bottom), 10, fill="white", outline="#cbd5e1", width=2)
        pl, pt, pr, pb = left + 70, top + 42, right - 35, bottom - 48
        draw.text((left + 16, top + 10), f"ADC{lane}", fill="#0f172a", font=_font(22, True))
        rows = [row for row in metrics if row["lane"] == lane]
        colors = {"tone_25": ("#2563eb", "#0891b2"), "tone_100": ("#dc2626", "#ea580c")}
        for condition in ("tone_25", "tone_100"):
            selected = sorted((row for row in rows if row["condition"] == condition), key=lambda row: row["tone_mhz"])
            carrier_points = []
            spur_points = []
            for row in selected:
                x = round(pl + (row["tone_mhz"] - 100.0) / 1600.0 * (pr - pl))
                carrier_y = round(pb - (min(max(row["carrier_dbfs"], -50.0), 5.0) + 50.0) / 55.0 * (pb - pt))
                spur_y = round(pb - (min(max(row["worst_spur_dbc"], -110.0), -20.0) + 110.0) / 90.0 * (pb - pt))
                carrier_points.append((x, carrier_y))
                spur_points.append((x, spur_y))
            if len(carrier_points) > 1:
                draw.line(carrier_points, fill=colors[condition][0], width=3)
                for index in range(len(spur_points) - 1):
                    if index % 2 == 0:
                        draw.line((*spur_points[index], *spur_points[index + 1]), fill=colors[condition][1], width=2)
        for tone in range(100, 1701, 200):
            x = round(pl + (tone - 100.0) / 1600.0 * (pr - pl))
            draw.line((x, pt, x, pb), fill="#e2e8f0")
            draw.text((x - 16, pb + 8), str(tone), fill="#475569", font=_font(14))
        draw.text((pl, pt + 4), "carrier scale: -50..+5 dBFS", fill="#475569", font=_font(14))
        draw.text((pl, pt + 24), "spur scale: -110..-20 dBc", fill="#475569", font=_font(14))
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, optimize=True)


def draw_linearity_plot(path: Path, rows: list[dict[str, Any]]) -> None:
    image, draw, panels = _panels(
        "T510 DAC sweep amplitude linearity: 25% to 100%",
        "Expected carrier increase 12.04 dB; characterization only",
    )
    for lane, (left, top, right, bottom) in enumerate(panels):
        draw.rounded_rectangle((left, top, right, bottom), 10, fill="white", outline="#cbd5e1", width=2)
        pl, pt, pr, pb = left + 70, top + 42, right - 25, bottom - 48
        draw.text((left + 16, top + 10), f"ADC{lane}", fill="#0f172a", font=_font(22, True))
        selected = sorted((row for row in rows if row["lane"] == lane), key=lambda row: row["tone_mhz"])
        points = []
        for row in selected:
            x = round(pl + (row["tone_mhz"] - 100.0) / 1600.0 * (pr - pl))
            y = round(pb - (min(max(row["increase_db"], 8.0), 16.0) - 8.0) / 8.0 * (pb - pt))
            points.append((x, y))
        expected_y = round(pb - (12.04 - 8.0) / 8.0 * (pb - pt))
        draw.line((pl, expected_y, pr, expected_y), fill="#94a3b8", width=2)
        if len(points) > 1:
            draw.line(points, fill="#7c3aed", width=3)
        for point in points:
            draw.ellipse((point[0] - 3, point[1] - 3, point[0] + 3, point[1] + 3), fill="#7c3aed")
        draw.text((pl, pt + 4), f"range {min(row['increase_db'] for row in selected):.2f}..{max(row['increase_db'] for row in selected):.2f} dB", fill="#475569", font=_font(15))
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, optimize=True)


def _heat_color(value_dbc: float) -> str:
    value = min(max((value_dbc + 100.0) / 100.0, 0.0), 1.0)
    stops = (
        (0.00, (15, 23, 42)),
        (0.35, (30, 64, 175)),
        (0.60, (8, 145, 178)),
        (0.80, (250, 204, 21)),
        (1.00, (220, 38, 38)),
    )
    for index in range(1, len(stops)):
        if value <= stops[index][0]:
            left_x, left = stops[index - 1]
            right_x, right = stops[index]
            ratio = (value - left_x) / (right_x - left_x)
            rgb = tuple(
                round(left[channel] + ratio * (right[channel] - left[channel]))
                for channel in range(3)
            )
            return "#%02x%02x%02x" % rgb
    return "#dc2626"


def draw_tone_heatmap(path: Path, windows: list[dict[str, Any]], condition: str) -> None:
    selected = sorted(
        (window for window in windows if window["condition"] == condition),
        key=lambda window: float(window["tone_mhz"]),
    )
    title_amplitude = "25%" if condition == "tone_25" else "100%"
    image, draw, panels = _panels(
        f"T510 {title_amplitude} DAC tone sweep: tone x RF spur heatmap",
        "Each row is one injected tone; color is dBc relative to that row's carrier; carrier +/-4 bins are blank",
    )
    for lane, (left, top, right, bottom) in enumerate(panels):
        draw.rounded_rectangle(
            (left, top, right, bottom), 10, fill="white", outline="#cbd5e1", width=2
        )
        pl, pt, pr, pb = left + 70, top + 42, right - 35, bottom - 48
        draw.text((left + 16, top + 10), f"ADC{lane}", fill="#0f172a", font=_font(22, True))
        heat_width = pr - pl + 1
        row_height = max(1, (pb - pt + 1) // len(selected))
        for row_index, window in enumerate(selected):
            power = window["power_dbfs"][lane]
            carrier = power[CARRIER_BIN]
            center_bin = round(float(window["center_mhz"]) / BIN_WIDTH_MHZ)
            pixels: list[list[float]] = [[] for _ in range(heat_width)]
            for local_bin, value in enumerate(power):
                if circular_bin_distance(local_bin, CARRIER_BIN) <= 4:
                    continue
                global_bin = center_bin + signed_bin(local_bin, SPEC_NCHAN)
                if not 0 <= global_bin < FULL_BAND_BINS:
                    continue
                x = min(
                    heat_width - 1,
                    round(global_bin / (FULL_BAND_BINS - 1) * (heat_width - 1)),
                )
                pixels[x].append(value - carrier)
            y0 = pt + row_index * row_height
            y1 = pb if row_index == len(selected) - 1 else y0 + row_height - 1
            for x, values in enumerate(pixels):
                if values:
                    draw.rectangle((pl + x, y0, pl + x, y1), fill=_heat_color(max(values)))
        for rf in range(0, 1921, 240):
            x = round(pl + rf / 1920.0 * (pr - pl))
            draw.line((x, pt, x, pb), fill="#ffffff", width=1)
            draw.text((x - 16, pb + 8), str(rf), fill="#475569", font=_font(14))
        draw.text((pl, pt + 4), "-100 dBc", fill="#f8fafc", font=_font(13))
        draw.text((pr - 55, pt + 4), "0 dBc", fill="#f8fafc", font=_font(13))
        draw.text((pl - 58, pt), "100", fill="#475569", font=_font(13))
        draw.text((pl - 58, pb - 14), "1700", fill="#475569", font=_font(13))
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, optimize=True)


def write_pcap_manifest(output: Path) -> Path:
    path = output / "pcap_manifest.sha256"
    lines = []
    for pcap in sorted((output / "raw").rglob("*.pcap")):
        digest = hashlib.sha256(pcap.read_bytes()).hexdigest()
        lines.append(f"{digest}  {pcap.relative_to(output)}")
    path.write_text("\n".join(lines) + "\n")
    return path


def write_analysis(output: Path, decoded_windows: list[dict[str, Any]]) -> dict[str, Any]:
    muted = [window for window in decoded_windows if window["condition"] == "muted"]
    tones = [window for window in decoded_windows if window["condition"] != "muted"]
    stitched = stitch_muted(muted)
    spurs = find_spurs(stitched, muted)
    metrics = tone_metrics(tones)
    linearity = amplitude_linearity(metrics)
    plots = output / "plots"
    muted_png = plots / "adc_muted_fullband_8lane.png"
    tone_png = plots / "dac_tone_sweep_8lane.png"
    linearity_png = plots / "dac_amplitude_linearity_8lane.png"
    heatmap_25_png = plots / "dac_tone_rf_heatmap_25_8lane.png"
    heatmap_100_png = plots / "dac_tone_rf_heatmap_100_8lane.png"
    spectra_25_png = plots / "dac_tone_spectra_25_8lane_atlas.png"
    spectra_100_png = plots / "dac_tone_spectra_100_8lane_atlas.png"
    draw_muted_plot(muted_png, stitched, spurs)
    draw_tone_plot(tone_png, metrics)
    draw_linearity_plot(linearity_png, linearity)
    draw_tone_heatmap(heatmap_25_png, decoded_windows, "tone_25")
    draw_tone_heatmap(heatmap_100_png, decoded_windows, "tone_100")
    draw_tone_spectrum_atlas(spectra_25_png, decoded_windows, metrics, "tone_25")
    draw_tone_spectrum_atlas(spectra_100_png, decoded_windows, metrics, "tone_100")

    spectrum_csv = output / "adc_muted_fullband.csv"
    with spectrum_csv.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["rf_mhz"] + [f"adc{lane}_dbfs" for lane in range(8)])
        for index in range(FULL_BAND_BINS):
            writer.writerow([index * BIN_WIDTH_MHZ] + [stitched[lane][index] for lane in range(8)])
    tone_csv = output / "dac_tone_metrics.csv"
    with tone_csv.open("w", newline="") as stream:
        fields = list(metrics[0])
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(metrics)
    linearity_csv = output / "dac_amplitude_linearity.csv"
    with linearity_csv.open("w", newline="") as stream:
        fields = list(linearity[0])
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(linearity)
    spurs_json = output / "adc_muted_spurs.json"
    spurs_json.write_text(json.dumps({"threshold_db": 6.0, "rows": spurs}, indent=2) + "\n")
    manifest = write_pcap_manifest(output)
    artifacts = [
        muted_png,
        tone_png,
        linearity_png,
        heatmap_25_png,
        heatmap_100_png,
        spectra_25_png,
        spectra_100_png,
        spectrum_csv,
        tone_csv,
        linearity_csv,
        spurs_json,
        manifest,
    ]
    return {
        "spurs": spurs,
        "tone_metrics": metrics,
        "linearity": linearity,
        "artifacts": {
            path.name: {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            for path in artifacts
        },
    }


def _window_integrity(before_board: dict[str, Any], after_board: dict[str, Any], before_rx: dict[str, Any], after_rx: dict[str, Any]) -> dict[str, Any]:
    board_delta = _counter_delta(before_board.get("counters", {}), after_board.get("counters", {}), BOARD_COUNTER_KEYS)
    channelizer_delta = _counter_delta(before_board.get("channelizer", {}), after_board.get("channelizer", {}), CHANNELIZER_COUNTER_KEYS)
    receiver_delta = _counter_delta(before_rx.get("stats", {}), after_rx.get("stats", {}), RECEIVER_COUNTER_KEYS)
    errors = [f"BOARD_{key}" for key, value in board_delta.items() if value != 0]
    errors += [f"PFB_{key}" for key, value in channelizer_delta.items() if value != 0]
    errors += [f"RECEIVER_{key}" for key, value in receiver_delta.items() if value != 0]
    return {
        "ok": not errors,
        "errors": errors,
        "board_counter_delta": board_delta,
        "channelizer_counter_delta": channelizer_delta,
        "receiver_counter_delta": receiver_delta,
    }


def analyze_existing_campaign(args: argparse.Namespace) -> int:
    output = args.output.resolve()
    campaign_path = output / "campaign.json"
    if not campaign_path.exists():
        raise RuntimeError(f"cannot analyze missing campaign {campaign_path}")
    evidence = json.loads(campaign_path.read_text())
    expected = campaign_windows()
    records = evidence.get("windows", [])
    if evidence.get("classification") != "T510_FULLBAND_SPUR_SCAN_PASS" or len(records) != len(expected):
        raise RuntimeError("analyze-only requires a completed 63-window PASS campaign")
    decoded_windows: list[dict[str, Any]] = []
    for index, (record, spec) in enumerate(zip(records, expected)):
        expected_name = _window_name(str(spec["condition"]), float(spec["center_mhz"]))
        if not record.get("ok") or record.get("name") != expected_name:
            raise RuntimeError(f"campaign window {index + 1} is not the required PASS record")
        paths = sorted(Path(str(record["local_dir"])).glob("*.pcap"))
        if not paths:
            raise RuntimeError(f"missing PCAP for {expected_name}")
        decoded = decode_window(paths)
        decoded_windows.append({**spec, "power_dbfs": decoded["power_dbfs"]})
    evidence["analysis"] = write_analysis(output, decoded_windows)
    evidence["analysis_regenerated_at_unix_ms"] = int(time.time() * 1000)
    campaign_path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"classification": evidence["classification"], "windows": len(records), "analysis_artifacts": sorted(evidence["analysis"]["artifacts"])}, indent=2))
    return 0


def run_campaign(args: argparse.Namespace) -> int:
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    campaign_path = output / "campaign.json"
    resume = bool(getattr(args, "resume", False))
    if campaign_path.exists() and not resume:
        raise RuntimeError(f"refusing to overwrite existing campaign {campaign_path}")
    if resume and not campaign_path.exists():
        raise RuntimeError(f"cannot resume missing campaign {campaign_path}")
    template = json.loads(args.configure_template.read_text())
    campaign_id = time.strftime("%Y%m%dT%H%M%S")
    windows = campaign_windows()
    if resume:
        evidence, decoded_windows, completed_count = _resume_campaign(
            campaign_path, windows
        )
        print(f"CAMPAIGN_RESUME completed={completed_count} remaining={len(windows) - completed_count}", flush=True)
    else:
        evidence = {
            "classification": "T510_FULLBAND_SPUR_SCAN_IN_PROGRESS",
            "ok": False,
            "campaign_id": campaign_id,
            "centers_mhz": list(CENTERS_MHZ),
            "conditions": list(CONDITIONS),
            "capture_packets_per_port": args.packets_per_port,
            "windows": [],
            "errors": [],
            "preflight_complete": False,
        }
        decoded_windows = []
        completed_count = 0
    current_center = 160.0
    try:
        for spec in windows[completed_count:]:
            condition = str(spec["condition"])
            center = float(spec["center_mhz"])
            tone = spec["tone_mhz"]
            amplitude = float(spec["amplitude_percent"])
            name = _window_name(condition, center)
            print(f"WINDOW_START {spec['index'] + 1}/63 {name}", flush=True)
            _receiver_prepare(
                args.receiver_base, center, None if tone is None else float(tone)
            )
            configured = _http_json(
                args.agent_base.rstrip("/") + "/api/v2/configure",
                method="POST",
                body=_configure_body(template, center),
                timeout=190.0,
            )
            current_center = center
            snapshot = configured.get("snapshot", configured)
            if str(snapshot.get("core_version", "")).lower() not in ("", "0x00010034"):
                raise RuntimeError("configured board is not CORE_VERSION 0x00010034")
            _http_json(
                args.agent_base.rstrip("/") + "/api/v2/dac",
                method="PUT",
                body=_dac_body(center, None if tone is None else float(tone), amplitude),
            )
            _http_json(
                args.agent_base.rstrip("/") + "/api/v2/start",
                method="POST",
                body={"expected_board_id": 1},
            )
            time.sleep(args.settle_seconds)
            before_board = _http_json(args.agent_base.rstrip("/") + "/api/v2/status")
            before_rx = _http_json(args.receiver_base.rstrip("/") + "/api/state")
            profile = before_board.get("profile", {})
            channelizer = before_board.get("channelizer", {})
            if str(before_board.get("core_version", "")).lower() != "0x00010034":
                raise RuntimeError(f"board core version mismatch: {before_board.get('core_version')}")
            if not bool(before_board.get("streaming")):
                raise RuntimeError("board did not enter streaming state")
            if profile.get("mode") != "spec_only" or int(profile.get("sample_rate_msps", 0)) != 320 or abs(float(profile.get("center_mhz", 0.0)) - center) > 1.0e-6:
                raise RuntimeError(f"board profile mismatch: {profile}")
            if int(channelizer.get("nchan", 0)) != 4096 or int(channelizer.get("taps", 0)) != 8 or str(channelizer.get("coefficient_id", "")).lower() != "0x34a80001":
                raise RuntimeError(f"channelizer identity mismatch: {channelizer}")
            local_dir = output / "raw" / condition / f"center_{int(center):04d}mhz"
            paths, capture_logs = capture_receiver_pcap(
                receiver_base=args.receiver_base,
                local_dir=local_dir,
                packets_per_block=args.packets_per_port,
            )
            time.sleep(1.0)
            after_board = _http_json(args.agent_base.rstrip("/") + "/api/v2/status")
            after_rx = _http_json(args.receiver_base.rstrip("/") + "/api/state")
            integrity = _window_integrity(before_board, after_board, before_rx, after_rx)
            decoded = decode_window(paths)
            if not integrity["ok"]:
                raise RuntimeError(f"window integrity failed: {integrity['errors']}")
            window_record = {
                **spec,
                "name": name,
                "ok": True,
                "local_dir": str(local_dir),
                "capture": decoded["capture"],
                "capture_logs": capture_logs,
                "integrity": integrity,
            }
            evidence["windows"].append(window_record)
            decoded_windows.append({**spec, "power_dbfs": decoded["power_dbfs"]})
            if int(spec["index"]) == 2:
                evidence["preflight_complete"] = True
            campaign_path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
            _http_json(args.agent_base.rstrip("/") + "/api/v2/dac", method="PUT", body=_dac_body(center, None, 0.0))
            _http_json(args.agent_base.rstrip("/") + "/api/v2/stop", method="POST")
            print(f"WINDOW_PASS {name}", flush=True)
        analysis = write_analysis(output, decoded_windows)
        evidence["analysis"] = analysis
        evidence["ok"] = True
        evidence["classification"] = "T510_FULLBAND_SPUR_SCAN_PASS"
    except Exception as exc:
        evidence["errors"].append(f"{type(exc).__name__}: {exc}")
        evidence["classification"] = "T510_FULLBAND_SPUR_SCAN_FAIL"
    finally:
        evidence["errors"].extend(_final_stop_and_mute(args, current_center))
        if evidence["errors"]:
            evidence["ok"] = False
        if not evidence["ok"]:
            evidence["classification"] = "T510_FULLBAND_SPUR_SCAN_FAIL"
        campaign_path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"classification": evidence["classification"], "ok": evidence["ok"], "windows": len(evidence["windows"]), "errors": evidence["errors"]}, indent=2))
    return 0 if evidence["ok"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("build/receiver/latest/evidence/fullband_spur_scan"))
    parser.add_argument("--configure-template", type=Path, default=Path("config/t510/configure_320_time_only.example.json"))
    parser.add_argument("--agent-base", default="http://192.168.100.117:8010")
    parser.add_argument("--receiver-base", default="http://192.168.100.162:8089")
    parser.add_argument("--packets-per-port", type=int, default=CAPTURE_PACKETS_PER_PORT)
    parser.add_argument("--settle-seconds", type=float, default=2.0)
    parser.add_argument(
        "--resume",
        action="store_true",
        help="resume only the strict successful prefix recorded in campaign.json",
    )
    parser.add_argument(
        "--analyze-only",
        action="store_true",
        help="rebuild analysis artifacts from an existing completed campaign without hardware access",
    )
    args = parser.parse_args()
    if args.resume and args.analyze_only:
        parser.error("--resume and --analyze-only are mutually exclusive")
    if args.packets_per_port != CAPTURE_PACKETS_PER_PORT:
        parser.error(f"formal campaign requires exactly {CAPTURE_PACKETS_PER_PORT} packets per port")
    if args.settle_seconds < 0.5:
        parser.error("--settle-seconds must be at least 0.5")
    return analyze_existing_campaign(args) if args.analyze_only else run_campaign(args)


if __name__ == "__main__":
    raise SystemExit(main())
