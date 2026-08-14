#!/usr/bin/env python3
"""Stage 34e v36 open-input spur-correction engineering campaign.

This runner deliberately cannot issue formal science credentials.  It executes
the registered raw -> static C0 -> dynamic OCB1 comparison, then the legal-mode
throughput/soak matrix.  A failed step stops the single queue and performs the
safe STOP/DAC-mute/receiver-pause cleanup; there is no retry or result picking.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
import statistics
import subprocess
import sys
import time
from typing import Any, Iterable

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import t510_adc_correlated_noise_campaign as c34c
from python import t510_astronomy as astronomy
from scripts import t510_fullband_spur_scan as fullband
from scripts import t510_plot_spec_udp_pcap as pcap_decoder


CORE_VERSION = "0x00010036"
BITSTREAM_ID = "fengine-0x00010036"
BOARD_ID = 1
PFB_PROFILE_ID = "0x34a80001"
FIXED_SPURS_MHZ = (480.0, 960.0, 1440.0)
SPUR_CENTERS_MHZ = {480.0: 420.0, 960.0: 900.0, 1440.0: 1380.0}
FLAG_ACTIVE = 1 << 6
FLAG_UNCORRECTED = 1 << 7
PACKETS_PER_FLOW = 32
BOARD_EVIDENCE = Path("build/board/latest/evidence/adc_interleave_spur_correction")
RECEIVER_EVIDENCE = Path("build/receiver/latest/evidence/adc_interleave_spur_correction")
SYSTEMD_UNIT = "t510-stage34e-open-input.service"


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def diagnostic_windows() -> list[dict[str, Any]]:
    return [
        {
            "name": f"spur_{int(spur)}mhz_{rate}msps",
            "spur_mhz": spur,
            "center_mhz": SPUR_CENTERS_MHZ[spur],
            "sample_rate_msps": rate,
        }
        for spur in FIXED_SPURS_MHZ
        for rate in (160, 320)
    ]


def comparison_plan() -> list[dict[str, Any]]:
    return [
        {**window, "condition": condition, "duration_seconds": 60}
        for window in diagnostic_windows()
        for condition in ("raw", "static_c0", "dynamic")
    ]


def throughput_plan() -> list[dict[str, Any]]:
    rows = [
        {"name": "mode_160_time_only_60s", "rate": 160, "mode": "time_only", "duration": 60},
        {"name": "mode_160_spec_only_60s", "rate": 160, "mode": "spec_only", "duration": 60},
        {"name": "mode_160_time_spec_60s", "rate": 160, "mode": "time_spec", "duration": 60},
        {"name": "mode_320_time_only_60s", "rate": 320, "mode": "time_only", "duration": 60},
        {"name": "mode_320_spec_only_60s", "rate": 320, "mode": "spec_only", "duration": 60},
        {"name": "heavy_160_time_spec_600s", "rate": 160, "mode": "time_spec", "duration": 600},
        {"name": "heavy_320_spec_only_600s", "rate": 320, "mode": "spec_only", "duration": 600},
        {"name": "soak_320_spec_only_3600s", "rate": 320, "mode": "spec_only", "duration": 3600},
    ]
    return rows


def local_signed_bins(rate: int) -> list[int]:
    carrier = round(60.0 / (rate / 4096.0))
    return [carrier] + [carrier + offset for offset in (-16, -12, -8, -4, 4, 8, 12, 16)]


def local_rf_targets(center_mhz: float, rate: int) -> list[float]:
    spacing = rate / 4096.0
    return [center_mhz + signed_bin * spacing for signed_bin in local_signed_bins(rate)]


def mean_dbfs(power_seconds: Iterable[dict[str, Any]]) -> float:
    values = [astronomy.mean_power_from_accumulator(row) for row in power_seconds]
    if not values:
        raise RuntimeError("monitor returned no power buckets")
    return astronomy.power_dbfs(math.fsum(values) / len(values))


def summarize_spur_monitor(raw: dict[str, Any]) -> dict[str, Any]:
    grouped: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for row in raw.get("power_seconds", []):
        grouped.setdefault((int(row["lane"]), int(row["target_index"])), []).append(row)
    targets = {int(row["target_index"]): row for row in raw.get("targets", [])}
    if len(targets) != 9:
        raise RuntimeError(f"monitor returned {len(targets)} targets, expected 9")
    rows = []
    for lane in range(8):
        powers_dbfs = []
        for target_index in range(9):
            samples = grouped.get((lane, target_index), [])
            powers_dbfs.append(mean_dbfs(samples))
        noise_linear = [10.0 ** (value / 10.0) for value in powers_dbfs[1:]]
        local_noise_dbfs = 10.0 * math.log10(max(statistics.median(noise_linear), 1.0e-30))
        rows.append(
            {
                "lane": lane,
                "spur_rf_mhz": float(targets[0]["actual_rf_mhz"]),
                "spur_dbfs": powers_dbfs[0],
                "local_noise_dbfs": local_noise_dbfs,
                "prominence_db": powers_dbfs[0] - local_noise_dbfs,
                "target_dbfs": powers_dbfs,
            }
        )
    return {
        "lanes": rows,
        "all_lanes_at_or_below_noise_plus_6db": all(row["prominence_db"] <= 6.0 for row in rows),
        "worst_prominence_db": max(row["prominence_db"] for row in rows),
    }


def agent_get(args: argparse.Namespace, path: str, timeout: float = 60.0) -> dict[str, Any]:
    return fullband._http_json(args.agent_base.rstrip("/") + path, timeout=timeout)


def agent_post(
    args: argparse.Namespace, path: str, body: dict[str, Any], timeout: float = 240.0
) -> dict[str, Any]:
    return fullband._http_json(
        args.agent_base.rstrip("/") + path,
        method="POST",
        body=body,
        timeout=timeout,
    )


def receiver_state(args: argparse.Namespace) -> dict[str, Any]:
    return fullband._http_json(args.receiver_base.rstrip("/") + "/api/state")


def receiver_pause(args: argparse.Namespace, paused: bool) -> dict[str, Any]:
    state = receiver_state(args)
    config = dict(state.get("config") or {})
    if not config:
        raise RuntimeError("receiver state has no restorable Web configuration")
    config["paused"] = bool(paused)
    return fullband._http_json(
        args.receiver_base.rstrip("/") + "/api/config",
        method="POST",
        body=config,
    )


def stop_and_safe(args: argparse.Namespace, center_mhz: float) -> list[str]:
    actual_center_mhz = float(center_mhz)
    try:
        status = agent_get(args, "/api/v2/status")
        actual_center_mhz = float(
            (status.get("profile") or {}).get("center_mhz") or center_mhz
        )
    except Exception:
        # The safe cleanup helper still attempts STOP and DAC mute using the
        # caller's last known configured center if status itself is unavailable.
        pass
    errors = c34c.stop_and_mute(args, actual_center_mhz)
    try:
        receiver_pause(args, True)
    except Exception as exc:
        errors.append(f"RECEIVER_PAUSE:{type(exc).__name__}:{exc}")
    return errors


def configure(
    args: argparse.Namespace,
    template: dict[str, Any],
    *,
    rate: int,
    mode: str,
    center_mhz: float,
) -> dict[str, Any]:
    args.bitstream_id = BITSTREAM_ID
    result = c34c.configure(args, template, rate, mode, center_mhz)
    status = agent_get(args, "/api/v2/status")
    if str(status.get("core_version", "")).lower() != CORE_VERSION:
        raise RuntimeError(f"v36 core identity mismatch: {status.get('core_version')}")
    channelizer = status.get("channelizer", {})
    if int(channelizer.get("nchan", 0)) != 4096 or int(channelizer.get("taps", 0)) != 8:
        raise RuntimeError(f"PFB geometry mismatch: {channelizer}")
    if str(channelizer.get("coefficient_id", "")).lower() != PFB_PROFILE_ID:
        raise RuntimeError(f"PFB profile mismatch: {channelizer}")
    dac = status.get("dac", {})
    if int(dac.get("enable_mask", -1)) != 0 or any(
        int(row.get("amplitude_code", -1)) != 0 for row in dac.get("channels", [])
    ):
        raise RuntimeError(f"DAC is not digitally silent: {dac}")
    return result


def wait_calibration(args: argparse.Namespace, timeout: float = 1200.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last = agent_get(args, "/api/v2/adc/spur-correction/calibrate/status")
        state = dict(last.get("state") or {})
        if state.get("calibration_state") == "CALIBRATED":
            return agent_get(args, "/api/v2/adc/spur-correction/calibrate/result")
        if state.get("calibration_state") == "FAILED":
            raise RuntimeError(f"spur calibration failed: {state}")
        time.sleep(1.0)
    raise RuntimeError(f"spur calibration timeout: {last}")


def calibrate_open_input(args: argparse.Namespace) -> dict[str, Any]:
    receiver_pause(args, True)
    status = agent_get(args, "/api/v2/adc/spur-correction")
    fingerprint = str(status.get("configuration_fingerprint") or "")
    if len(fingerprint) != 64:
        raise RuntimeError(f"invalid configuration fingerprint: {status}")
    accepted = agent_post(
        args,
        "/api/v2/adc/spur-correction/calibrate",
        {
            "expected_board_id": BOARD_ID,
            "receiver_stream_accepting": False,
            "configuration_fingerprint": fingerprint,
            "input_state": "all_open_diagnostic",
        },
        timeout=60.0,
    )
    completed = wait_calibration(args)
    state = dict(completed.get("state") or {})
    if not state.get("diagnostic_only") or not state.get("credential_valid"):
        raise RuntimeError(f"open-input calibration did not produce diagnostic credential: {state}")
    return {"accepted": accepted, "completed": completed}


def select_tracker_mode(args: argparse.Namespace, credential_id: str, mode: str) -> dict[str, Any]:
    receiver_pause(args, True)
    return agent_post(
        args,
        "/api/v2/adc/spur-correction/tracker-mode",
        {
            "expected_board_id": BOARD_ID,
            "receiver_stream_accepting": False,
            "spur_correction_id": credential_id,
            "mode": mode,
        },
    )


def wait_monitor(args: argparse.Namespace, duration: int) -> dict[str, Any]:
    deadline = time.monotonic() + duration + 120.0
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last = fullband._http_json(
            args.receiver_base.rstrip("/") + "/api/measure/spec-stability/status"
        )
        if last.get("status") == "completed":
            return fullband._http_json(
                args.receiver_base.rstrip("/") + "/api/measure/spec-stability/result",
                timeout=300.0,
            )
        if last.get("status") == "failed":
            raise RuntimeError(f"receiver monitor failed: {last}")
        time.sleep(1.0)
    raise RuntimeError(f"receiver monitor timeout: {last}")


def capture_edge(
    args: argparse.Namespace,
    directory: Path,
    name: str,
    include_time: bool,
    rate: int,
) -> dict[str, Any]:
    paths, metadata = fullband.capture_receiver_pcap(
        receiver_base=args.receiver_base,
        local_dir=directory / "raw" / name,
        packets_per_block=PACKETS_PER_FLOW,
        include_time=include_time,
    )
    record: dict[str, Any] = {**metadata, "paths": [str(path.resolve()) for path in paths]}
    if not include_time:
        decoded = pcap_decoder.collect_spectra(paths)
        if int(decoded["sample_rate_hz"]) != rate * 1_000_000:
            raise RuntimeError(f"PCAP sample rate mismatch: {decoded['sample_rate_hz']}")
        if int(decoded["pfb_taps"]) != 8:
            raise RuntimeError(f"PCAP PFB tap mismatch: {decoded['pfb_taps']}")
        decoded.pop("power_db")
        record["decoded"] = decoded
    return record


def validate_packet_flags(state: dict[str, Any], *, active: bool, uncorrected: bool) -> None:
    stats = state.get("stats", {})
    if bool(stats.get("adc_interleave_spur_correction_active")) != active:
        raise RuntimeError(f"receiver active flag mismatch: {stats}")
    if bool(stats.get("adc_interleave_spur_uncorrected")) != uncorrected:
        raise RuntimeError(f"receiver uncorrected flag mismatch: {stats}")


def run_spec_interval(
    args: argparse.Namespace,
    run_dir: Path,
    *,
    rate: int,
    center_mhz: float,
    duration: int,
    credential_id: str | None,
    expect_active: bool,
    expect_uncorrected: bool,
) -> dict[str, Any]:
    c34c.receiver_prepare(args.receiver_base, rate, "spec_only", center_mhz)
    start_body: dict[str, Any] = {"expected_board_id": BOARD_ID}
    if credential_id is not None:
        start_body["spur_correction_id"] = credential_id
    start = agent_post(args, "/api/v2/start", start_body)
    time.sleep(args.settle_seconds)
    before_board = agent_get(args, "/api/v2/status")
    before_receiver = receiver_state(args)
    validate_packet_flags(
        before_receiver, active=expect_active, uncorrected=expect_uncorrected
    )
    begin = capture_edge(args, run_dir, "begin", include_time=False, rate=rate)
    pcap_flags = int(begin["decoded"]["packet_flags"])
    if bool(pcap_flags & FLAG_ACTIVE) != expect_active or bool(pcap_flags & FLAG_UNCORRECTED) != expect_uncorrected:
        raise RuntimeError(f"QSFP PCAP packet flag mismatch: 0x{pcap_flags:04x}")
    monitor_start = fullband._http_json(
        args.receiver_base.rstrip("/") + "/api/measure/spec-stability",
        method="POST",
        body={
            "duration_seconds": duration,
            "formal": False,
            "sample_rate_msps": rate,
            "center_mhz": center_mhz,
            "rf_frequencies_mhz": local_rf_targets(center_mhz, rate),
            "lane_mask": 0xFF,
            "include_time_statistics": False,
            "bucket_ms": 1000,
            "correlation_mode": "none",
        },
    )
    monitor = wait_monitor(args, duration)
    end = capture_edge(args, run_dir, "end", include_time=False, rate=rate)
    after_board = agent_get(args, "/api/v2/status")
    after_receiver = receiver_state(args)
    integrity = fullband._window_integrity(
        before_board, after_board, before_receiver, after_receiver
    )
    if not integrity["ok"]:
        raise RuntimeError(f"digital integrity failed: {integrity['errors']}")
    return {
        "start": start,
        "monitor_start": monitor_start,
        "monitor": monitor,
        "metrics": summarize_spur_monitor(monitor),
        "begin_capture": begin,
        "end_capture": end,
        "integrity": integrity,
        "before_board": before_board,
        "after_board": after_board,
    }


def timed_integrity_run(
    args: argparse.Namespace,
    directory: Path,
    *,
    duration: int,
    credential_id: str,
    mode: str,
    rate: int,
) -> dict[str, Any]:
    start = agent_post(
        args,
        "/api/v2/start",
        {"expected_board_id": BOARD_ID, "spur_correction_id": credential_id},
    )
    time.sleep(args.settle_seconds)
    before_board = agent_get(args, "/api/v2/status")
    before_receiver = receiver_state(args)
    validate_packet_flags(before_receiver, active=True, uncorrected=False)
    begin = None
    if mode != "time_only":
        begin = capture_edge(
            args,
            directory,
            "begin",
            include_time=mode == "time_spec",
            rate=rate,
        )
    deadline = time.monotonic() + duration
    samples = []
    while time.monotonic() < deadline:
        board = agent_get(args, "/api/v2/status")
        receiver = receiver_state(args)
        validate_packet_flags(receiver, active=True, uncorrected=False)
        samples.append(
            {
                "elapsed_seconds": duration - max(0.0, deadline - time.monotonic()),
                "board_counters": board.get("counters"),
                "receiver_stats": receiver.get("stats"),
                "spur_correction": board.get("adc_interleave_spur_correction"),
            }
        )
        time.sleep(min(5.0, max(0.0, deadline - time.monotonic())))
    end = (
        capture_edge(
            args,
            directory,
            "end",
            include_time=mode == "time_spec",
            rate=rate,
        )
        if mode != "time_only"
        else None
    )
    after_board = agent_get(args, "/api/v2/status")
    after_receiver = receiver_state(args)
    integrity = fullband._window_integrity(
        before_board, after_board, before_receiver, after_receiver
    )
    if not integrity["ok"]:
        raise RuntimeError(f"digital integrity failed: {integrity['errors']}")
    return {
        "start": start,
        "samples": samples,
        "begin_capture": begin,
        "end_capture": end,
        "integrity": integrity,
        "before_board": before_board,
        "after_board": after_board,
    }


def run_comparisons(args: argparse.Namespace, template: dict[str, Any]) -> list[dict[str, Any]]:
    records = []
    for window in diagnostic_windows():
        root = args.receiver_output / "comparisons" / window["name"]
        root.mkdir(parents=True, exist_ok=False)
        stop_errors = stop_and_safe(args, float(window["center_mhz"]))
        if stop_errors:
            raise RuntimeError(f"pre-window safe stop failed: {stop_errors}")
        configured = configure(
            args,
            template,
            rate=int(window["sample_rate_msps"]),
            mode="spec_only",
            center_mhz=float(window["center_mhz"]),
        )
        raw = run_spec_interval(
            args,
            root / "raw_condition",
            rate=int(window["sample_rate_msps"]),
            center_mhz=float(window["center_mhz"]),
            duration=60,
            credential_id=None,
            expect_active=False,
            expect_uncorrected=True,
        )
        errors = stop_and_safe(args, float(window["center_mhz"]))
        if errors:
            raise RuntimeError(f"raw cleanup failed: {errors}")
        calibration = calibrate_open_input(args)
        state = dict(calibration["completed"]["state"])
        credential_id = str(state["spur_correction_id"])
        static_select = select_tracker_mode(args, credential_id, "static_c0")
        static = run_spec_interval(
            args,
            root / "static_c0",
            rate=int(window["sample_rate_msps"]),
            center_mhz=float(window["center_mhz"]),
            duration=60,
            credential_id=credential_id,
            expect_active=True,
            expect_uncorrected=False,
        )
        errors = stop_and_safe(args, float(window["center_mhz"]))
        if errors:
            raise RuntimeError(f"static cleanup failed: {errors}")
        dynamic_select = select_tracker_mode(args, credential_id, "dynamic")
        dynamic = run_spec_interval(
            args,
            root / "dynamic",
            rate=int(window["sample_rate_msps"]),
            center_mhz=float(window["center_mhz"]),
            duration=60,
            credential_id=credential_id,
            expect_active=True,
            expect_uncorrected=False,
        )
        record = {
            **window,
            "configured": configured,
            "calibration": calibration,
            "static_select": static_select,
            "dynamic_select": dynamic_select,
            "raw": raw,
            "static_c0": static,
            "dynamic": dynamic,
            "direction_consistent": all(
                dynamic["metrics"]["lanes"][lane]["prominence_db"]
                <= raw["metrics"]["lanes"][lane]["prominence_db"]
                for lane in range(8)
            ),
        }
        write_json(root / "result.json", record)
        records.append(record)
        print(f"STAGE34E_COMPARE_PASS {window['name']}", flush=True)
    return records


def run_960_tracker_soak(
    args: argparse.Namespace, template: dict[str, Any]
) -> dict[str, Any]:
    root = args.receiver_output / "tracker_960mhz_3600s"
    root.mkdir(parents=True, exist_ok=False)
    stop_errors = stop_and_safe(args, 900.0)
    if stop_errors:
        raise RuntimeError(f"pre-soak safe stop failed: {stop_errors}")
    configured = configure(args, template, rate=320, mode="spec_only", center_mhz=900.0)
    calibration = calibrate_open_input(args)
    credential = str(calibration["completed"]["state"]["spur_correction_id"])
    select = select_tracker_mode(args, credential, "dynamic")
    run = run_spec_interval(
        args,
        root,
        rate=320,
        center_mhz=900.0,
        duration=3600,
        credential_id=credential,
        expect_active=True,
        expect_uncorrected=False,
    )
    result = {"configured": configured, "calibration": calibration, "select": select, "run": run}
    write_json(root / "result.json", result)
    return result


def run_throughput_matrix(
    args: argparse.Namespace, template: dict[str, Any]
) -> list[dict[str, Any]]:
    rows = []
    for item in throughput_plan():
        root = args.receiver_output / "throughput" / item["name"]
        root.mkdir(parents=True, exist_ok=False)
        errors = stop_and_safe(args, 900.0)
        if errors:
            raise RuntimeError(f"pre-throughput safe stop failed: {errors}")
        configured = configure(
            args,
            template,
            rate=int(item["rate"]),
            mode=str(item["mode"]),
            center_mhz=900.0,
        )
        calibration = calibrate_open_input(args)
        credential = str(calibration["completed"]["state"]["spur_correction_id"])
        select = select_tracker_mode(args, credential, "dynamic")
        c34c.receiver_prepare(args.receiver_base, int(item["rate"]), str(item["mode"]), 900.0)
        run = timed_integrity_run(
            args,
            root,
            duration=int(item["duration"]),
            credential_id=credential,
            mode=str(item["mode"]),
            rate=int(item["rate"]),
        )
        record = {**item, "configured": configured, "calibration": calibration, "select": select, "run": run}
        write_json(root / "result.json", record)
        rows.append(record)
        print(f"STAGE34E_THROUGHPUT_PASS {item['name']}", flush=True)
    return rows


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    names = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    ]
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default()


def write_comparison_artifacts(root: Path, rows: list[dict[str, Any]]) -> list[str]:
    csv_path = root / "spur_prominence.csv"
    with csv_path.open("w", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=("spur_mhz", "sample_rate_msps", "condition", "lane", "spur_dbfs", "local_noise_dbfs", "prominence_db"),
        )
        writer.writeheader()
        for row in rows:
            for condition in ("raw", "static_c0", "dynamic"):
                for lane in row[condition]["metrics"]["lanes"]:
                    writer.writerow(
                        {
                            "spur_mhz": row["spur_mhz"],
                            "sample_rate_msps": row["sample_rate_msps"],
                            "condition": condition,
                            **{key: lane[key] for key in ("lane", "spur_dbfs", "local_noise_dbfs", "prominence_db")},
                        }
                    )
    image = Image.new("RGB", (1800, 1250), "#f8fafc")
    draw = ImageDraw.Draw(image)
    draw.text((45, 28), "Stage 34e — 固定杂散相对局部噪底", fill="#0f172a", font=_font(34, True))
    draw.text((45, 75), "0 dB表示与局部噪底相同；绿色虚线+6 dB是开放输入工程目标。数值越低越好。", fill="#334155", font=_font(21))
    colors = {"raw": "#dc2626", "static_c0": "#d97706", "dynamic": "#2563eb"}
    panel_w, panel_h = 560, 510
    for index, row in enumerate(rows):
        left = 35 + (index % 3) * 585
        top = 130 + (index // 3) * 540
        draw.rounded_rectangle((left, top, left + panel_w, top + panel_h), 10, fill="white", outline="#cbd5e1", width=2)
        draw.text((left + 18, top + 12), f"{int(row['spur_mhz'])} MHz · {row['sample_rate_msps']} MS/s", fill="#0f172a", font=_font(23, True))
        plot_left, plot_top, plot_right, plot_bottom = left + 55, top + 75, left + 535, top + 440
        draw.line((plot_left, plot_bottom, plot_right, plot_bottom), fill="#64748b", width=2)
        draw.line((plot_left, plot_top, plot_left, plot_bottom), fill="#64748b", width=2)
        minimum, maximum = -12.0, 36.0
        y6 = plot_bottom - (6.0 - minimum) / (maximum - minimum) * (plot_bottom - plot_top)
        draw.line((plot_left, y6, plot_right, y6), fill="#16a34a", width=2)
        for condition_index, condition in enumerate(("raw", "static_c0", "dynamic")):
            values = [float(lane["prominence_db"]) for lane in row[condition]["metrics"]["lanes"]]
            points = []
            for lane, value in enumerate(values):
                x = plot_left + lane / 7 * (plot_right - plot_left)
                clipped = min(max(value, minimum), maximum)
                y = plot_bottom - (clipped - minimum) / (maximum - minimum) * (plot_bottom - plot_top)
                points.append((x, y))
            draw.line(points, fill=colors[condition], width=3)
            for x, y in points:
                draw.ellipse((x - 4, y - 4, x + 4, y + 4), fill=colors[condition])
            draw.text((left + 60 + condition_index * 155, top + 462), condition, fill=colors[condition], font=_font(17, True))
        for lane in range(8):
            x = plot_left + lane / 7 * (plot_right - plot_left)
            draw.text((x - 12, plot_bottom + 7), str(lane), fill="#475569", font=_font(14))
        draw.text((left + 8, plot_top - 8), "+36", fill="#64748b", font=_font(13))
        draw.text((left + 10, plot_bottom - 8), "-12", fill="#64748b", font=_font(13))
    plot_path = root / "raw_static_dynamic_prominence.png"
    image.save(plot_path, optimize=True)
    return [str(csv_path.resolve()), str(plot_path.resolve())]


def submit_systemd(args: argparse.Namespace) -> int:
    command = [
        "systemd-run",
        "--user",
        f"--unit={SYSTEMD_UNIT.removesuffix('.service')}",
        "--property=Restart=no",
        f"--working-directory={Path.cwd()}",
        sys.executable,
        str(Path(__file__).resolve()),
        "--agent-base", args.agent_base,
        "--receiver-base", args.receiver_base,
        "--configure-template", str(args.configure_template),
        "--board-output", str(args.board_output),
        "--receiver-output", str(args.receiver_output),
        "--settle-seconds", str(args.settle_seconds),
    ]
    subprocess.run(command, check=True)
    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline:
        result = subprocess.run(
            ["systemctl", "--user", "show", SYSTEMD_UNIT, "--property=ActiveState,SubState,ExecMainStatus"],
            check=True,
            capture_output=True,
            text=True,
        )
        values = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
        if values.get("ActiveState") == "active" and values.get("SubState") == "running":
            print(json.dumps({"submitted": True, "unit": SYSTEMD_UNIT, "state": values}, indent=2))
            return 0
        if values.get("ActiveState") == "failed":
            raise RuntimeError(f"systemd campaign failed during startup: {values}")
        time.sleep(1.0)
    raise RuntimeError(f"systemd campaign did not enter running state: {SYSTEMD_UNIT}")


def run_campaign(args: argparse.Namespace) -> int:
    if args.receiver_output.exists() and any(args.receiver_output.iterdir()):
        raise RuntimeError(f"refusing to overwrite non-empty evidence {args.receiver_output}")
    args.receiver_output.mkdir(parents=True, exist_ok=True)
    args.board_output.mkdir(parents=True, exist_ok=True)
    template = json.loads(args.configure_template.read_text())
    original_receiver = receiver_state(args)
    campaign: dict[str, Any] = {
        "stage": "34e",
        "classification": "OPEN_INPUT_DIAGNOSTIC_RUNNING",
        "ok": False,
        "core_version": CORE_VERSION,
        "bitstream_id": BITSTREAM_ID,
        "input_state": "OPEN_INPUT_DIAGNOSTIC",
        "windows": diagnostic_windows(),
        "throughput_plan": throughput_plan(),
        "started_at_unix_ms": time.time_ns() // 1_000_000,
        "errors": [],
    }
    write_json(args.receiver_output / "campaign.json", campaign)
    current_center = 900.0
    try:
        comparisons = run_comparisons(args, template)
        campaign["comparisons"] = comparisons
        write_json(args.receiver_output / "campaign.json", campaign)
        if not all(row["direction_consistent"] for row in comparisons):
            raise RuntimeError("open-input correction improvement is not direction-consistent on all eight lanes")
        campaign["tracker_soak"] = run_960_tracker_soak(args, template)
        write_json(args.receiver_output / "campaign.json", campaign)
        campaign["throughput"] = run_throughput_matrix(args, template)
        campaign["artifacts"] = write_comparison_artifacts(args.receiver_output, comparisons)
        campaign["classification"] = "OPEN_INPUT_DIAGNOSTIC_PASS"
        campaign["ok"] = True
    except Exception as exc:
        campaign["errors"].append(f"{type(exc).__name__}: {exc}")
        campaign["classification"] = "OPEN_INPUT_DIAGNOSTIC_FAIL"
    finally:
        campaign["errors"].extend(stop_and_safe(args, current_center))
        try:
            original_config = dict(original_receiver.get("config") or {})
            fullband._http_json(
                args.receiver_base.rstrip("/") + "/api/config",
                method="POST",
                body=original_config,
            )
        except Exception as exc:
            campaign["errors"].append(f"RECEIVER_RESTORE:{type(exc).__name__}:{exc}")
        if campaign["errors"]:
            campaign["ok"] = False
            campaign["classification"] = "OPEN_INPUT_DIAGNOSTIC_FAIL"
        campaign["finished_at_unix_ms"] = time.time_ns() // 1_000_000
        write_json(args.receiver_output / "campaign.json", campaign)
        write_json(
            args.board_output / "campaign_summary.json",
            {
                key: campaign.get(key)
                for key in ("stage", "classification", "ok", "core_version", "bitstream_id", "input_state", "started_at_unix_ms", "finished_at_unix_ms", "errors")
            },
        )
    print(json.dumps({"classification": campaign["classification"], "ok": campaign["ok"], "errors": campaign["errors"]}, indent=2))
    return 0 if campaign["ok"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent-base", default="http://192.168.100.117:8010")
    parser.add_argument("--receiver-base", default="http://192.168.100.162:8089")
    parser.add_argument("--configure-template", type=Path, default=Path("config/t510/configure_320_time_only.example.json"))
    parser.add_argument("--board-output", type=Path, default=BOARD_EVIDENCE)
    parser.add_argument("--receiver-output", type=Path, default=RECEIVER_EVIDENCE)
    parser.add_argument("--settle-seconds", type=float, default=2.0)
    parser.add_argument("--submit-systemd", action="store_true")
    args = parser.parse_args()
    if args.settle_seconds < 1.0:
        parser.error("--settle-seconds must be at least 1 second")
    return submit_systemd(args) if args.submit_systemd else run_campaign(args)


if __name__ == "__main__":
    raise SystemExit(main())
