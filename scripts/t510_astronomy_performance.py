#!/usr/bin/env python3
"""Run the automated Stage 34a astronomy-performance campaign and analysis."""

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
from typing import Any

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from python import t510_astronomy as astronomy
from scripts import t510_fullband_spur_scan as fullband
from scripts.t510_plot_spec_udp_pcap import collect_spectra, signed_bin


CORE_VERSION = "0x00010034"
BITSTREAM_SHA256 = "c21d93f5ea71e9ac17a4448cff138a8faaf9c7347d879be919b680d196b8a5be"
PFB_PROFILE_ID = "0x34a80001"
MTS_ADC_TARGET = 416
MTS_DAC_TARGET = 112
FFT_SHIFT = 0x556
CENTERS_160_MHZ = tuple(float(value) for value in range(80, 1841, 80))
STABILITY_RF_MHZ = (960.0, 980.0, 1000.0, 1040.0, 1060.0, 1080.0)
CLEAN_STABILITY_RF_MHZ = STABILITY_RF_MHZ[1:]
STABILITY_CENTER_MHZ = 1020.0
FORMAL_STABILITY_SECONDS = 600
PACKETS_PER_BLOCK = 32
REQUIRED_AUTOMATED_EVIDENCE = (
    "mts_discovery.json",
    "mts_fixed.json",
    "8lane_loopback.json",
    "pfb8_loopback_160.json",
    "pfb8_loopback_320.json",
    "stability_60s_160_time_only.json",
    "stability_60s_160_spec_only.json",
    "stability_60s_160_time_spec.json",
    "stability_60s_320_time_only.json",
    "stability_60s_320_spec_only.json",
    "stability_10m_160_time_spec.json",
    "stability_10m_320_spec_only.json",
    "stability_60m_320_spec_only.json",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def configure_body(template: dict[str, Any], sample_rate_msps: int, center_mhz: float) -> dict[str, Any]:
    body = json.loads(json.dumps(template))
    body["board_id"] = 1
    body["bitstream_id"] = "fengine-0x00010034"
    body["profile"] = {
        "sample_rate_msps": sample_rate_msps,
        "mode": "spec_only",
        "center_mhz": center_mhz,
    }
    for endpoint in body.get("endpoints", []):
        endpoint["enabled"] = str(endpoint.get("stream", "")).upper() == "SPEC"
    return body


def receiver_prepare(receiver_base: str, sample_rate_msps: int, center_mhz: float) -> dict[str, Any]:
    return fullband._http_json(
        receiver_base.rstrip("/") + "/api/config",
        method="POST",
        body={
            "sample_rate_msps": sample_rate_msps,
            "output_mode": "spec_only",
            "center_mhz": center_mhz,
            "expected_mhz": center_mhz,
            "dac_mhz": center_mhz,
            "target_mhz_by_channel": [center_mhz] * astronomy.NINPUT,
            "channel_mask": 0xFF,
            "paused": False,
        },
    )


def mute_body(center_mhz: float, board_id: int = 1) -> dict[str, Any]:
    return fullband._dac_body(center_mhz, None, 0.0, expected_board_id=board_id)


def stop_and_mute(agent_base: str, center_mhz: float) -> list[str]:
    shim = argparse.Namespace(agent_base=agent_base)
    return fullband._final_stop_and_mute(shim, center_mhz)


def validate_board_status(status: dict[str, Any], sample_rate_msps: int, center_mhz: float) -> None:
    profile = status.get("profile", {})
    channelizer = status.get("channelizer", {})
    mts = status.get("mts", {})
    if str(status.get("core_version", "")).lower() != CORE_VERSION:
        raise RuntimeError(f"CORE_VERSION mismatch: {status.get('core_version')}")
    if not status.get("streaming") or not status.get("pipeline", {}).get("stream_accepting"):
        raise RuntimeError("board is not streaming/accepting")
    if profile.get("mode") != "spec_only" or int(profile.get("sample_rate_msps", 0)) != sample_rate_msps:
        raise RuntimeError(f"board profile mismatch: {profile}")
    if abs(float(profile.get("center_mhz", 0.0)) - center_mhz) > 1.0e-6:
        raise RuntimeError(f"board center mismatch: {profile}")
    if int(channelizer.get("nchan", 0)) != 4096 or int(channelizer.get("taps", 0)) != 8:
        raise RuntimeError(f"channelizer geometry mismatch: {channelizer}")
    if str(channelizer.get("coefficient_id", "")).lower() != PFB_PROFILE_ID:
        raise RuntimeError(f"PFB profile mismatch: {channelizer}")
    if int(mts.get("adc", {}).get("target_latency", -1)) != MTS_ADC_TARGET:
        raise RuntimeError(f"ADC MTS target mismatch: {mts}")
    if int(mts.get("dac", {}).get("target_latency", -1)) != MTS_DAC_TARGET:
        raise RuntimeError(f"DAC MTS target mismatch: {mts}")
    dac = status.get("dac", {})
    channels = dac.get("channels", [])
    if int(dac.get("enable_mask", -1)) != 0 or len(channels) != astronomy.NINPUT:
        raise RuntimeError(f"DAC is not muted: {dac}")
    if any(bool(row.get("enabled")) or int(row.get("amplitude_code", -1)) != 0 for row in channels):
        raise RuntimeError(f"DAC channel is not muted: {dac}")


def decode_window(paths: list[Path], sample_rate_msps: int) -> dict[str, Any]:
    capture = collect_spectra(paths)
    if int(capture["packet_count"]) != 16 * PACKETS_PER_BLOCK:
        raise RuntimeError(f"unexpected packet count {capture['packet_count']}")
    if list(capture["block_packets"]) != [PACKETS_PER_BLOCK] * 16:
        raise RuntimeError(f"unbalanced block packets {capture['block_packets']}")
    if int(capture["sample_rate_hz"]) != sample_rate_msps * 1_000_000:
        raise RuntimeError(f"sample rate mismatch {capture['sample_rate_hz']}")
    if int(capture["pfb_taps"]) != 8:
        raise RuntimeError(f"PFB taps mismatch {capture['pfb_taps']}")
    power_dbfs = [
        [fullband.db_code_to_dbfs(value) for value in lane]
        for lane in capture.pop("power_db")
    ]
    return {"capture": capture, "power_dbfs": power_dbfs}


def audit_frozen_evidence(board_evidence: Path, fullband_evidence: Path) -> dict[str, Any]:
    rows = []
    for name in REQUIRED_AUTOMATED_EVIDENCE:
        path = board_evidence / name
        if not path.is_file():
            raise RuntimeError(f"missing frozen evidence {path}")
        document = json.loads(path.read_text())
        if document.get("ok") is not True:
            raise RuntimeError(f"frozen evidence is not PASS: {path}")
        core = document.get("core_version")
        if core is not None and str(core).lower() != CORE_VERSION:
            raise RuntimeError(f"frozen evidence core mismatch: {path}")
        bitstream = document.get("bitstream_sha256")
        if bitstream is not None and str(bitstream).lower() != BITSTREAM_SHA256:
            raise RuntimeError(f"frozen evidence bitstream mismatch: {path}")
        rows.append({"name": name, "classification": document.get("classification"), "sha256": sha256_file(path)})
    discovery = json.loads((board_evidence / "mts_discovery.json").read_text())
    fixed = json.loads((board_evidence / "mts_fixed.json").read_text())
    recommended = discovery.get("recommended_fixed_targets", {})
    targets = fixed.get("targets", {})
    for document, label in ((recommended, "discovery"), (targets, "fixed")):
        if int(document.get("adc", -1)) != MTS_ADC_TARGET or int(document.get("dac", -1)) != MTS_DAC_TARGET:
            raise RuntimeError(f"{label} MTS target mismatch: {document}")
    campaign = fullband_evidence / "campaign.json"
    manifest = fullband_evidence / "pcap_manifest.sha256"
    if not campaign.is_file() or not manifest.is_file():
        raise RuntimeError("320 MS/s full-band campaign or manifest is missing")
    fullband_document = json.loads(campaign.read_text())
    if fullband_document.get("classification") != "T510_FULLBAND_SPUR_SCAN_PASS" or len(fullband_document.get("windows", [])) != 63:
        raise RuntimeError("320 MS/s full-band campaign is not the frozen 63-window PASS")
    pcaps = sorted((fullband_evidence / "raw").rglob("*.pcap"))
    if len(pcaps) != 63:
        raise RuntimeError(f"320 MS/s campaign has {len(pcaps)} PCAPs, expected 63")
    manifest_lines = [line for line in manifest.read_text().splitlines() if line.strip()]
    if len(manifest_lines) != 63:
        raise RuntimeError("320 MS/s PCAP manifest does not contain 63 entries")
    return {
        "ok": True,
        "core_version": CORE_VERSION,
        "bitstream_sha256": BITSTREAM_SHA256,
        "pfb_profile_id": PFB_PROFILE_ID,
        "mts_targets": {"adc": MTS_ADC_TARGET, "dac": MTS_DAC_TARGET},
        "frozen_evidence": rows,
        "fullband_320": {
            "classification": fullband_document["classification"],
            "windows": 63,
            "packets": sum(int(row.get("capture", {}).get("packet_count", 0)) for row in fullband_document["windows"]),
            "pcaps": len(pcaps),
            "campaign_sha256": sha256_file(campaign),
            "manifest_sha256": sha256_file(manifest),
        },
    }


def load_scan160_prefix(campaign_path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    document = json.loads(campaign_path.read_text())
    windows = document.get("windows", [])
    if document.get("classification") == "T510_ASTRONOMY_160_MUTED_SCAN_FAIL":
        raise RuntimeError("refusing automatic retry of a failed 160 MS/s scan")
    decoded = []
    for index, record in enumerate(windows):
        if index >= len(CENTERS_160_MHZ) or float(record.get("center_mhz", -1.0)) != CENTERS_160_MHZ[index] or not record.get("ok"):
            raise RuntimeError("160 MS/s resume evidence is not a strict successful prefix")
        paths = sorted(Path(record["local_dir"]).glob("*.pcap"))
        value = decode_window(paths, 160)
        decoded.append({"center_mhz": CENTERS_160_MHZ[index], "power_dbfs": value["power_dbfs"]})
    return document, decoded


def run_scan160(args: argparse.Namespace, output: Path, template: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    scan_dir = output / "muted_fullband_160"
    campaign_path = scan_dir / "campaign.json"
    if campaign_path.exists():
        evidence, decoded = load_scan160_prefix(campaign_path)
        if evidence.get("classification") == "T510_ASTRONOMY_160_MUTED_SCAN_PASS":
            return evidence, decoded
    else:
        evidence = {
            "classification": "T510_ASTRONOMY_160_MUTED_SCAN_IN_PROGRESS",
            "ok": False,
            "sample_rate_msps": 160,
            "centers_mhz": list(CENTERS_160_MHZ),
            "packets_per_block": PACKETS_PER_BLOCK,
            "windows": [],
            "errors": [],
        }
        decoded = []
    current_center = CENTERS_160_MHZ[len(decoded)] if len(decoded) < len(CENTERS_160_MHZ) else CENTERS_160_MHZ[-1]
    try:
        for index, center_mhz in enumerate(CENTERS_160_MHZ[len(decoded):], start=len(decoded)):
            current_center = center_mhz
            print(f"SCAN160_WINDOW_START {index + 1}/{len(CENTERS_160_MHZ)} center={center_mhz:.0f}", flush=True)
            receiver_prepare(args.receiver_base, 160, center_mhz)
            fullband._http_json(
                args.agent_base.rstrip("/") + "/api/v2/configure",
                method="POST",
                body=configure_body(template, 160, center_mhz),
                timeout=190.0,
            )
            fullband._http_json(args.agent_base.rstrip("/") + "/api/v2/dac", method="PUT", body=mute_body(center_mhz))
            fullband._http_json(args.agent_base.rstrip("/") + "/api/v2/start", method="POST", body={"expected_board_id": 1})
            time.sleep(args.settle_seconds)
            before_board = fullband._http_json(args.agent_base.rstrip("/") + "/api/v2/status")
            before_rx = fullband._http_json(args.receiver_base.rstrip("/") + "/api/state")
            validate_board_status(before_board, 160, center_mhz)
            local_dir = scan_dir / "raw" / f"center_{int(center_mhz):04d}mhz"
            paths, capture_log = fullband.capture_receiver_pcap(
                receiver_base=args.receiver_base,
                local_dir=local_dir,
                packets_per_block=PACKETS_PER_BLOCK,
            )
            value = decode_window(paths, 160)
            after_board = fullband._http_json(args.agent_base.rstrip("/") + "/api/v2/status")
            after_rx = fullband._http_json(args.receiver_base.rstrip("/") + "/api/state")
            integrity = fullband._window_integrity(before_board, after_board, before_rx, after_rx)
            if not integrity["ok"]:
                raise RuntimeError(f"160 scan window integrity failed: {integrity['errors']}")
            record = {
                "index": index,
                "center_mhz": center_mhz,
                "ok": True,
                "local_dir": str(local_dir.resolve()),
                "capture": value["capture"],
                "capture_log": capture_log,
                "integrity": integrity,
            }
            evidence["windows"].append(record)
            decoded.append({"center_mhz": center_mhz, "power_dbfs": value["power_dbfs"]})
            write_json(campaign_path, evidence)
            fullband._http_json(args.agent_base.rstrip("/") + "/api/v2/stop", method="POST")
            print(f"SCAN160_WINDOW_PASS center={center_mhz:.0f}", flush=True)
        evidence["ok"] = True
        evidence["classification"] = "T510_ASTRONOMY_160_MUTED_SCAN_PASS"
    except Exception as error:
        evidence["errors"].append(f"{type(error).__name__}: {error}")
        evidence["classification"] = "T510_ASTRONOMY_160_MUTED_SCAN_FAIL"
        raise
    finally:
        evidence["errors"].extend(stop_and_mute(args.agent_base, current_center))
        if evidence["errors"]:
            evidence["ok"] = False
            evidence["classification"] = "T510_ASTRONOMY_160_MUTED_SCAN_FAIL"
        write_json(campaign_path, evidence)
    return evidence, decoded


def wait_for_monitor(receiver_base: str, duration_seconds: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    deadline = time.monotonic() + duration_seconds + 30.0
    rate_samples = []
    while time.monotonic() < deadline:
        status = fullband._http_json(receiver_base.rstrip("/") + "/api/measure/spec-stability/status")
        state = fullband._http_json(receiver_base.rstrip("/") + "/api/state")
        rate_samples.append(
            {
                "unix_ms": int(time.time() * 1000),
                "spec_packets_per_sec": float(state.get("stats", {}).get("spec_processed_packets_per_sec", 0.0)),
                "expected_packets_per_sec": float(state.get("stats", {}).get("expected_packets_per_sec", 0.0)),
            }
        )
        if status.get("status") == "completed":
            result = fullband._http_json(receiver_base.rstrip("/") + "/api/measure/spec-stability/result", timeout=120.0)
            return result, rate_samples
        if status.get("status") == "failed":
            raise RuntimeError(f"SPEC monitor failed: {status.get('error')}")
        time.sleep(1.0)
    raise RuntimeError("SPEC monitor did not complete before its deadline")


def run_stability_mode(
    args: argparse.Namespace,
    output: Path,
    template: dict[str, Any],
    sample_rate_msps: int,
) -> dict[str, Any]:
    mode_dir = output / f"stability_{sample_rate_msps}msps"
    result_path = mode_dir / "result.json"
    if result_path.exists():
        existing = json.loads(result_path.read_text())
        if existing.get("classification") == "T510_ASTRONOMY_SPEC_STABILITY_PASS":
            return existing
        raise RuntimeError(f"refusing automatic retry of failed stability result {result_path}")
    mode_dir.mkdir(parents=True, exist_ok=True)
    center = STABILITY_CENTER_MHZ
    evidence: dict[str, Any] = {
        "classification": "T510_ASTRONOMY_SPEC_STABILITY_IN_PROGRESS",
        "ok": False,
        "sample_rate_msps": sample_rate_msps,
        "center_mhz": center,
        "duration_seconds": FORMAL_STABILITY_SECONDS,
        "rf_frequencies_mhz": list(STABILITY_RF_MHZ),
        "errors": [],
    }
    try:
        receiver_prepare(args.receiver_base, sample_rate_msps, center)
        fullband._http_json(
            args.agent_base.rstrip("/") + "/api/v2/configure",
            method="POST",
            body=configure_body(template, sample_rate_msps, center),
            timeout=190.0,
        )
        fullband._http_json(args.agent_base.rstrip("/") + "/api/v2/dac", method="PUT", body=mute_body(center))
        fullband._http_json(args.agent_base.rstrip("/") + "/api/v2/start", method="POST", body={"expected_board_id": 1})
        time.sleep(args.settle_seconds)
        before_board = fullband._http_json(args.agent_base.rstrip("/") + "/api/v2/status")
        before_rx = fullband._http_json(args.receiver_base.rstrip("/") + "/api/state")
        validate_board_status(before_board, sample_rate_msps, center)
        baseline_rates = []
        for _ in range(5):
            state = fullband._http_json(args.receiver_base.rstrip("/") + "/api/state")
            baseline_rates.append(float(state.get("stats", {}).get("spec_processed_packets_per_sec", 0.0)))
            time.sleep(1.0)
        begin_paths, begin_capture = fullband.capture_receiver_pcap(
            receiver_base=args.receiver_base,
            local_dir=mode_dir / "raw" / "begin",
            packets_per_block=PACKETS_PER_BLOCK,
        )
        begin_decoded = decode_window(begin_paths, sample_rate_msps)
        monitor_request = {
            "duration_seconds": FORMAL_STABILITY_SECONDS,
            "sample_rate_msps": sample_rate_msps,
            "center_mhz": center,
            "rf_frequencies_mhz": list(STABILITY_RF_MHZ),
            "correlation_pair": [0, 2],
        }
        monitor_start = fullband._http_json(
            args.receiver_base.rstrip("/") + "/api/measure/spec-stability",
            method="POST",
            body=monitor_request,
        )
        monitor_result, monitor_rates = wait_for_monitor(args.receiver_base, FORMAL_STABILITY_SECONDS)
        write_json(mode_dir / "monitor_raw.json", monitor_result)
        end_paths, end_capture = fullband.capture_receiver_pcap(
            receiver_base=args.receiver_base,
            local_dir=mode_dir / "raw" / "end",
            packets_per_block=PACKETS_PER_BLOCK,
        )
        end_decoded = decode_window(end_paths, sample_rate_msps)
        after_board = fullband._http_json(args.agent_base.rstrip("/") + "/api/v2/status")
        after_rx = fullband._http_json(args.receiver_base.rstrip("/") + "/api/state")
        validate_board_status(after_board, sample_rate_msps, center)
        integrity = fullband._window_integrity(before_board, after_board, before_rx, after_rx)
        if not integrity["ok"]:
            raise RuntimeError(f"stability integrity failed: {integrity['errors']}")
        if monitor_result.get("status") != "completed":
            raise RuntimeError(f"monitor did not complete: {monitor_result.get('status')}")
        expected_rate = 1_250_000.0 if sample_rate_msps == 320 else 625_000.0
        active_rates = [row["spec_packets_per_sec"] for row in monitor_rates[2:] if row["spec_packets_per_sec"] > 0.0]
        if not active_rates or statistics.median(active_rates) < expected_rate * 0.98:
            raise RuntimeError(f"monitor active receive rate is below 98%: {active_rates[-10:]}")
        if statistics.median(baseline_rates) < expected_rate * 0.98:
            raise RuntimeError(f"baseline receive rate is below 98%: {baseline_rates}")
        evidence.update(
            {
                "ok": True,
                "classification": "T510_ASTRONOMY_SPEC_STABILITY_PASS",
                "before_board": before_board,
                "after_board": after_board,
                "before_receiver": before_rx,
                "after_receiver": after_rx,
                "integrity": integrity,
                "baseline_spec_packets_per_sec": baseline_rates,
                "monitor_rate_samples": monitor_rates,
                "monitor_start": monitor_start,
                "monitor_result_path": str((mode_dir / "monitor_raw.json").resolve()),
                "begin_capture": {**begin_capture, "decoded": begin_decoded["capture"]},
                "end_capture": {**end_capture, "decoded": end_decoded["capture"]},
            }
        )
    except Exception as error:
        evidence["errors"].append(f"{type(error).__name__}: {error}")
        evidence["classification"] = "T510_ASTRONOMY_SPEC_STABILITY_FAIL"
        raise
    finally:
        evidence["errors"].extend(stop_and_mute(args.agent_base, center))
        if evidence["errors"]:
            evidence["ok"] = False
            evidence["classification"] = "T510_ASTRONOMY_SPEC_STABILITY_FAIL"
        write_json(result_path, evidence)
    return evidence


def local_prominence(values: list[float], index: int, radius: int, guard: int = 2) -> tuple[float, float]:
    background = [
        values[position]
        for position in range(max(0, index - radius), min(len(values), index + radius + 1))
        if abs(position - index) > guard and values[position] > -250.0
    ]
    median = statistics.median(background) if background else values[index]
    return values[index] - median, median


def find_classified_spurs(stitched: list[list[float]], windows: list[dict[str, Any]], sample_rate_msps: int) -> list[dict[str, Any]]:
    bin_width = sample_rate_msps / astronomy.NCHAN
    radius = max(4, round(2.0 / bin_width))
    rows = []
    for lane, values in enumerate(stitched):
        candidates = []
        for index in range(radius, len(values) - radius):
            prominence, background = local_prominence(values, index, radius)
            if prominence >= 6.0:
                candidates.append((index, values[index], prominence, background))
        clusters: list[list[tuple[int, float, float, float]]] = []
        for candidate in candidates:
            if not clusters or candidate[0] - clusters[-1][-1][0] > 3:
                clusters.append([candidate])
            else:
                clusters[-1].append(candidate)
        for cluster in clusters:
            peak = max(cluster, key=lambda row: row[1])
            rf_mhz = peak[0] * bin_width
            reproductions = []
            for window in windows:
                offset = round((rf_mhz - float(window["center_mhz"])) / bin_width)
                if not -1536 <= offset <= 1536 or abs(offset) < 13:
                    continue
                prominence, _ = local_prominence(window["power_dbfs"][lane], offset % astronomy.NCHAN, radius)
                if prominence >= 6.0:
                    reproductions.append({"center_mhz": window["center_mhz"], "prominence_db": prominence})
            classification = astronomy.classify_spur(
                rf_mhz=rf_mhz,
                prominence_db=peak[2],
                reproduced=len(reproductions) >= 2,
                bin_width_mhz=bin_width,
                context="muted_adc",
            )
            rows.append(
                {
                    **classification,
                    "lane": lane,
                    "power_dbfs": peak[1],
                    "local_median_dbfs": peak[3],
                    "cluster_bins": len(cluster),
                    "lower_confidence_edge": rf_mhz < 40.0 or rf_mhz >= 1880.0,
                    "reproduced_window_count": len(reproductions),
                    "reproductions": reproductions,
                }
            )
    return sorted(rows, key=lambda row: float(row["prominence_db"]), reverse=True)


def load_stability_analysis(mode_dir: Path) -> dict[str, Any]:
    raw = json.loads((mode_dir / "monitor_raw.json").read_text())
    targets = {int(row["target_index"]): row for row in raw["targets"]}
    grouped: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for row in raw["power_seconds"]:
        grouped.setdefault((int(row["target_index"]), int(row["lane"])), []).append(row)
    combinations = []
    clean_pass = 0
    clean_total = 0
    for (target_index, lane), rows in sorted(grouped.items()):
        rows.sort(key=lambda row: int(row["second"]))
        powers = [astronomy.mean_power_from_accumulator(row) for row in rows]
        stats = astronomy.integration_statistics(powers)
        rf_mhz = float(targets[target_index]["actual_rf_mhz"])
        is_clean = all(abs(rf_mhz - fixed) > 1.0e-6 for fixed in astronomy.ADC_FIXED_SPURS_MHZ)
        slope_pass = -0.65 <= float(stats["slope"]) <= -0.35
        if is_clean:
            clean_total += 1
            clean_pass += int(slope_pass)
        combinations.append(
            {
                "target_index": target_index,
                "rf_mhz": rf_mhz,
                "lane": lane,
                "seconds": len(rows),
                "clean_reference": is_clean,
                "slope_pass": slope_pass if is_clean else None,
                "second": [int(row["second"]) for row in rows],
                "power_dbfs_by_second": [astronomy.power_dbfs(power) for power in powers],
                **stats,
            }
        )
    cross = []
    grouped_cross: dict[int, list[dict[str, Any]]] = {}
    for row in raw.get("cross_seconds", []):
        grouped_cross.setdefault(int(row["target_index"]), []).append(row)
    for target_index, rows in sorted(grouped_cross.items()):
        cross.append({"target_index": target_index, "rf_mhz": targets[target_index]["actual_rf_mhz"], **astronomy.coherence_from_accumulators(rows)})
    fraction = clean_pass / clean_total if clean_total else 0.0
    return {
        "ok": fraction >= 0.8,
        "clean_slope_pass_count": clean_pass,
        "clean_slope_total": clean_total,
        "clean_slope_pass_fraction": fraction,
        "required_fraction": 0.8,
        "combinations": combinations,
        "cross_channel_0_2": cross,
    }


def font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    candidates = (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    )
    for candidate in candidates:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def panels(title: str, subtitle: str) -> tuple[Image.Image, ImageDraw.ImageDraw, list[tuple[int, int, int, int]]]:
    image = Image.new("RGB", (2400, 1500), "#f8fafc")
    draw = ImageDraw.Draw(image)
    draw.text((50, 24), title, fill="#0f172a", font=font(34, True))
    draw.text((50, 70), subtitle, fill="#475569", font=font(19))
    boxes = []
    for lane in range(8):
        row, column = divmod(lane, 2)
        boxes.append((35 + column * 1180, 112 + row * 340, 1180 + column * 1180, 430 + row * 340))
    return image, draw, boxes


def draw_fullband(path: Path, stitched: list[list[float]], spurs: list[dict[str, Any]], sample_rate_msps: int) -> None:
    image, draw, boxes = panels(
        f"T510 {sample_rate_msps} MS/s DAC-muted full band — 8 ADC lanes",
        f"Absolute dBFS/bin; bin spacing {sample_rate_msps / 4096 * 1000:.4f} kHz; orange: frozen ADC masks; labels retain raw peaks",
    )
    colors = ("#2563eb", "#dc2626", "#059669")
    for lane, (left, top, right, bottom) in enumerate(boxes):
        draw.rounded_rectangle((left, top, right, bottom), 8, fill="white", outline="#cbd5e1", width=2)
        pl, pt, pr, pb = left + 62, top + 40, right - 18, bottom - 40
        values = stitched[lane]
        draw.text((left + 12, top + 8), f"ADC{lane}  median {statistics.median(value for value in values if value > -250):.2f} dBFS/bin", fill="#0f172a", font=font(18, True))
        for level in (-100, -80, -60, -40, -20, 0):
            y = round(pb - (level + 110) / 115 * (pb - pt))
            draw.line((pl, y, pr, y), fill="#e2e8f0")
            draw.text((left + 6, y - 8), str(level), fill="#64748b", font=font(12))
        for rf in range(0, 1921, 240):
            x = round(pl + rf / 1920 * (pr - pl))
            draw.line((x, pt, x, pb), fill="#f1f5f9")
            draw.text((x - 16, pb + 8), str(rf), fill="#64748b", font=font(11))
        columns = [[] for _ in range(pr - pl + 1)]
        for index, value in enumerate(values):
            x = min(len(columns) - 1, round(index / (len(values) - 1) * (len(columns) - 1)))
            columns[x].append(value)
        points = []
        for x, values_in_column in enumerate(columns):
            value = max(values_in_column) if values_in_column else -110.0
            y = round(pb - (min(max(value, -110), 5) + 110) / 115 * (pb - pt))
            points.append((pl + x, y))
        draw.line(points, fill=colors[lane % len(colors)], width=1)
        for fixed in astronomy.ADC_FIXED_SPURS_MHZ:
            x = round(pl + fixed / 1920 * (pr - pl))
            draw.line((x, pt, x, pb), fill="#f59e0b", width=2)
        selected = [row for row in spurs if row["lane"] == lane][:4]
        draw.text((pl + 8, pt + 8), "  ".join(f"{row['rf_mhz']:.1f} MHz {row['power_dbfs']:.1f} dBFS" for row in selected), fill="#7c2d12", font=font(12))
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, optimize=True)


def draw_difference(path: Path, spectrum_160: list[list[float]], spectrum_320: list[list[float]], noise_rows: list[dict[str, Any]]) -> None:
    image, draw, boxes = panels(
        "T510 DAC-muted per-bin noise: 160 minus 320 MS/s",
        "White-noise expectation is -3.01 dB because ENBW halves; fixed spurs are masked from the summary",
    )
    for lane, (left, top, right, bottom) in enumerate(boxes):
        draw.rounded_rectangle((left, top, right, bottom), 8, fill="white", outline="#cbd5e1", width=2)
        pl, pt, pr, pb = left + 62, top + 40, right - 18, bottom - 40
        row = noise_rows[lane]
        draw.text((left + 12, top + 8), f"ADC{lane} median {row['median_delta_db']:.2f} dB (expected -3.01)", fill="#0f172a", font=font(18, True))
        expected_y = round(pb - (-3.0103 + 10) / 20 * (pb - pt))
        draw.line((pl, expected_y, pr, expected_y), fill="#f59e0b", width=2)
        points = []
        for pixel in range(pr - pl + 1):
            index160 = round(pixel / max(pr - pl, 1) * (len(spectrum_160[lane]) - 1))
            index320 = min(round(index160 / 2), len(spectrum_320[lane]) - 1)
            delta = spectrum_160[lane][index160] - spectrum_320[lane][index320]
            delta = min(max(delta, -10), 10)
            y = round(pb - (delta + 10) / 20 * (pb - pt))
            points.append((pl + pixel, y))
        draw.line(points, fill="#2563eb", width=1)
        for rf in range(0, 1921, 240):
            x = round(pl + rf / 1920 * (pr - pl))
            draw.line((x, pt, x, pb), fill="#e2e8f0")
            draw.text((x - 16, pb + 8), str(rf), fill="#64748b", font=font(11))
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, optimize=True)


def draw_stability_plots(output: Path, analyses: dict[int, dict[str, Any]]) -> dict[str, Path]:
    timeline_path = output / "plots" / "power_timeline_10minute.png"
    integration_path = output / "plots" / "integration_slope_allan.png"
    comparison_path = output / "plots" / "fixed_960_vs_clean.png"
    for path, kind in ((timeline_path, "timeline"), (integration_path, "integration"), (comparison_path, "comparison")):
        image, draw, boxes = panels(
            {
                "timeline": "Stage 34a 10-minute selected-bin power timeline",
                "integration": "Stage 34a integration slope and Allan stability",
                "comparison": "960 MHz fixed item versus clean astronomy references",
            }[kind],
            "160 and 320 MS/s; power is relative digital dBFS/bin and is not input dBm or system temperature",
        )
        for lane, (left, top, right, bottom) in enumerate(boxes):
            draw.rounded_rectangle((left, top, right, bottom), 8, fill="white", outline="#cbd5e1", width=2)
            pl, pt, pr, pb = left + 62, top + 40, right - 18, bottom - 40
            draw.text((left + 12, top + 8), f"ADC{lane}", fill="#0f172a", font=font(18, True))
            colors = {160: "#2563eb", 320: "#dc2626"}
            for rate, analysis in analyses.items():
                lane_rows = [row for row in analysis["combinations"] if row["lane"] == lane]
                if kind == "timeline":
                    selected = next(row for row in lane_rows if abs(row["rf_mhz"] - 1000.0) < 1e-6)
                    mean = statistics.fmean(selected["power_dbfs_by_second"])
                    points = []
                    for second, value in zip(selected["second"], selected["power_dbfs_by_second"]):
                        x = round(pl + second / (FORMAL_STABILITY_SECONDS - 1) * (pr - pl))
                        # Show small astronomical gain/noise motion around each lane's mean.
                        y = round(pb - (min(max(value - mean, -1.0), 1.0) + 1.0) / 2.0 * (pb - pt))
                        points.append((x, y))
                    if len(points) > 1:
                        draw.line(points, fill=colors[rate], width=1)
                    draw.text((pl + 6, pt + (0 if rate == 160 else 18)), f"{rate}: mean {mean:.2f} dBFS/bin", fill=colors[rate], font=font(12))
                elif kind == "integration":
                    clean = [row for row in lane_rows if row["clean_reference"]]
                    if clean:
                        selected = clean[0]
                        points = []
                        for curve in selected["curve"]:
                            value = curve["fractional_stddev"]
                            if value is None:
                                continue
                            x = round(pl + math.log2(curve["tau_seconds"]) / 7 * (pr - pl))
                            y = round(pb - (math.log10(max(value, 1e-6)) + 6) / 6 * (pb - pt))
                            points.append((x, y))
                        if len(points) > 1:
                            draw.line(points, fill=colors[rate], width=2)
                        allan_points = []
                        for curve in selected["curve"]:
                            value = curve["allan_deviation"]
                            if value is None:
                                continue
                            x = round(pl + math.log2(curve["tau_seconds"]) / 7 * (pr - pl))
                            y = round(pb - (math.log10(max(value, 1e-6)) + 6) / 6 * (pb - pt))
                            allan_points.append((x, y))
                        for left_point, right_point in zip(allan_points, allan_points[1:]):
                            steps = max(abs(right_point[0] - left_point[0]) // 8, 1)
                            for step in range(0, steps, 2):
                                start_fraction = step / steps
                                end_fraction = min((step + 1) / steps, 1.0)
                                x0 = round(left_point[0] + start_fraction * (right_point[0] - left_point[0]))
                                y0 = round(left_point[1] + start_fraction * (right_point[1] - left_point[1]))
                                x1 = round(left_point[0] + end_fraction * (right_point[0] - left_point[0]))
                                y1 = round(left_point[1] + end_fraction * (right_point[1] - left_point[1]))
                                draw.line((x0, y0, x1, y1), fill=colors[rate], width=1)
                        draw.text((pl + (rate - 160) * 2, pt + (0 if rate == 160 else 20)), f"{rate}: slope {selected['slope']:.3f}", fill=colors[rate], font=font(13))
                else:
                    fixed = next(row for row in lane_rows if abs(row["rf_mhz"] - 960.0) < 1e-6)
                    clean = next(row for row in lane_rows if abs(row["rf_mhz"] - 1000.0) < 1e-6)
                    for row_index, row in enumerate((fixed, clean)):
                        points = []
                        for curve in row["curve"]:
                            value = curve["fractional_stddev"]
                            if value is None:
                                continue
                            x = round(pl + math.log2(curve["tau_seconds"]) / 7 * (pr - pl))
                            y = round(pb - (math.log10(max(value, 1e-6)) + 6) / 6 * (pb - pt))
                            points.append((x, y))
                        if len(points) > 1:
                            line_color = colors[rate] if row_index == 0 else "#059669"
                            draw.line(points, fill=line_color, width=2 if rate == 320 else 1)
                    draw.text((pl + 5, pt + (0 if rate == 160 else 18)), f"{rate}: 960 slope {fixed['slope']:.3f}; clean {clean['slope']:.3f}", fill=colors[rate], font=font(12))
        path.parent.mkdir(parents=True, exist_ok=True)
        image.save(path, optimize=True)
    return {"timeline": timeline_path, "integration": integration_path, "fixed_vs_clean": comparison_path}


def read_fullband_csv(path: Path) -> list[list[float]]:
    lanes = [[] for _ in range(astronomy.NINPUT)]
    with path.open(newline="") as stream:
        for row in csv.DictReader(stream):
            for lane in range(astronomy.NINPUT):
                lanes[lane].append(float(row[f"adc{lane}_dbfs"]))
    return lanes


def analyze_dac_source_classification(fullband_dir: Path, output: Path) -> dict[str, Any]:
    """Retain raw DAC-loopback SFDR and also compute a source-excluded value."""
    campaign = json.loads((fullband_dir / "campaign.json").read_text())
    bin_width = 320.0 / astronomy.NCHAN
    rows = []
    for record in campaign["windows"]:
        if record.get("condition") not in ("tone_25", "tone_100"):
            continue
        decoded = fullband.decode_window(sorted(Path(record["local_dir"]).glob("*.pcap")))
        center = float(record["center_mhz"])
        tone = float(record["tone_mhz"])
        carrier_bin = (-768) % astronomy.NCHAN
        image_mhz = center + 60.0
        harmonic_mhz = fullband.first_nyquist_fold_mhz(2.0 * tone)
        for lane, spectrum in enumerate(decoded["power_dbfs"]):
            carrier = spectrum[carrier_bin]
            eligible = [
                index
                for index in range(astronomy.NCHAN)
                if fullband.circular_bin_distance(index, carrier_bin) > 4
                and 13 <= abs(signed_bin(index, astronomy.NCHAN)) <= 1536
            ]
            raw_bin = max(eligible, key=spectrum.__getitem__)

            def source_excluded(index: int) -> bool:
                rf_mhz = center + signed_bin(index, astronomy.NCHAN) * bin_width
                near_dac_comb = abs(rf_mhz / 20.0 - round(rf_mhz / 20.0)) <= 4 * bin_width / 20.0
                near_image = abs(rf_mhz - image_mhz) <= 4 * bin_width
                near_harmonic = abs(rf_mhz - harmonic_mhz) <= 4 * bin_width
                near_adc_fixed = any(abs(rf_mhz - fixed) <= 4 * bin_width for fixed in astronomy.ADC_FIXED_SPURS_MHZ)
                return near_dac_comb or near_image or near_harmonic or near_adc_fixed

            scientific = [index for index in eligible if not source_excluded(index)]
            science_bin = max(scientific, key=spectrum.__getitem__)
            raw_rf = center + signed_bin(raw_bin, astronomy.NCHAN) * bin_width
            raw_classification = astronomy.classify_spur(
                rf_mhz=raw_rf,
                prominence_db=carrier - spectrum[raw_bin],
                reproduced=True,
                bin_width_mhz=bin_width,
                context="dac_loopback",
                dac_signature_match=source_excluded(raw_bin),
            )
            rows.append(
                {
                    "condition": record["condition"],
                    "amplitude_percent": record["amplitude_percent"],
                    "tone_mhz": tone,
                    "center_mhz": center,
                    "lane": lane,
                    "carrier_dbfs": carrier,
                    "raw_worst_spur_rf_mhz": raw_rf,
                    "raw_worst_spur_dbfs": spectrum[raw_bin],
                    "raw_sfdr_dbc": spectrum[raw_bin] - carrier,
                    "raw_worst_spur_classification": raw_classification["classification"],
                    "source_excluded_worst_spur_rf_mhz": center + signed_bin(science_bin, astronomy.NCHAN) * bin_width,
                    "source_excluded_worst_spur_dbfs": spectrum[science_bin],
                    "source_excluded_sfdr_dbc": spectrum[science_bin] - carrier,
                }
            )
    csv_path = output / "dac_loopback_raw_and_source_excluded_sfdr.csv"
    with csv_path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    json_path = output / "dac_loopback_raw_and_source_excluded_sfdr.json"
    write_json(
        json_path,
        {
            "scope": "DAC+loopback+ADC functional characterization; not ADC-only SFDR",
            "source_exclusions": ["20 MHz DAC comb", "DAC image", "visible second harmonic", "frozen ADC bad bins"],
            "rows": rows,
        },
    )
    return {
        "rows": rows,
        "artifacts": {
            csv_path.name: {"path": str(csv_path.resolve()), "sha256": sha256_file(csv_path)},
            json_path.name: {"path": str(json_path.resolve()), "sha256": sha256_file(json_path)},
        },
    }


def write_automated_analysis(output: Path, fullband_dir: Path, windows160: list[dict[str, Any]]) -> dict[str, Any]:
    plots = output / "plots"
    spectrum160 = astronomy.stitch_overlapping_windows(windows160, 160)
    spectrum320 = read_fullband_csv(fullband_dir / "adc_muted_fullband.csv")
    spurs160 = find_classified_spurs(spectrum160, windows160, 160)
    raw320 = json.loads((fullband_dir / "adc_muted_spurs.json").read_text()).get("rows", [])
    spurs320 = [
        {
            **row,
            **astronomy.classify_spur(
                rf_mhz=float(row["rf_mhz"]),
                prominence_db=float(row["prominence_db"]),
                reproduced=int(row.get("reproduced_window_count", 0)) >= 2,
                bin_width_mhz=320.0 / astronomy.NCHAN,
                context="muted_adc",
            ),
        }
        for row in raw320
    ]
    noise = astronomy.compare_noise_modes(spectrum160, spectrum320)
    fullband160_plot = plots / "adc_muted_fullband_160_8lane.png"
    fullband320_plot = plots / "adc_muted_fullband_320_8lane.png"
    difference_plot = plots / "adc_muted_160_minus_320_8lane.png"
    draw_fullband(fullband160_plot, spectrum160, spurs160, 160)
    draw_fullband(fullband320_plot, spectrum320, spurs320, 320)
    draw_difference(difference_plot, spectrum160, spectrum320, noise)
    spectrum_csv = output / "adc_muted_fullband_160.csv"
    with spectrum_csv.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["rf_mhz"] + [f"adc{lane}_dbfs" for lane in range(astronomy.NINPUT)])
        for index in range(len(spectrum160[0])):
            writer.writerow([index * 160.0 / astronomy.NCHAN] + [spectrum160[lane][index] for lane in range(astronomy.NINPUT)])
    classified_path = output / "classified_spurs.json"
    write_json(classified_path, {"muted_160": spurs160, "muted_320": spurs320})
    masks_path = output / "bad_bins_and_watchlist.json"
    write_json(
        masks_path,
        {
            "bad_bins": astronomy.science_bad_bins(160),
            "watchlist_mhz": list(astronomy.ADC_WATCHLIST_MHZ),
            "policy": "No notch or subtraction; masks apply only to science summary statistics.",
        },
    )
    stability_analyses = {
        rate: load_stability_analysis(output / f"stability_{rate}msps")
        for rate in (160, 320)
    }
    stability_paths = draw_stability_plots(output, stability_analyses)
    dac_classification = analyze_dac_source_classification(fullband_dir, output)
    new_review = [
        row
        for row in spurs160 + spurs320
        if row["classification"] == "ASTRONOMY_REVIEW_REQUIRED"
    ]
    artifacts = [fullband160_plot, fullband320_plot, difference_plot, spectrum_csv, classified_path, masks_path, *stability_paths.values()]
    return {
        "noise_160_minus_320": noise,
        "muted_spurs_160": spurs160,
        "muted_spurs_320": spurs320,
        "new_astronomy_review_required": new_review,
        "stability": stability_analyses,
        "dac_loopback_source_classification": dac_classification,
        "automated_astronomy_pass": all(value["ok"] for value in stability_analyses.values()) and not new_review,
        "artifacts": {path.name: {"path": str(path.resolve()), "sha256": sha256_file(path)} for path in artifacts},
    }


def pcap_manifest(output: Path, fullband_dir: Path) -> Path:
    path = output / "pcap_manifest.sha256"
    lines = []
    for root, label in ((fullband_dir / "raw", "reused_320"), (output, "stage34a")):
        for pcap in sorted(root.rglob("*.pcap")):
            lines.append(f"{sha256_file(pcap)}  {label}/{pcap.relative_to(root)}")
    path.write_text("\n".join(lines) + "\n")
    return path


def run_automated(args: argparse.Namespace) -> int:
    output = args.output.resolve()
    board_output = args.board_output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    board_output.mkdir(parents=True, exist_ok=True)
    state_path = output / "campaign.json"
    if state_path.exists():
        previous = json.loads(state_path.read_text())
        if previous.get("classification") in (
            "T510_STAGE34A_AUTOMATED_FAIL",
            "T510_STAGE34A_AUTOMATED_COMPLETE_TG_PENDING",
        ):
            raise RuntimeError(f"refusing to overwrite terminal campaign {state_path}")
        if not args.resume:
            raise RuntimeError(
                f"in-progress campaign exists at {state_path}; explicit --resume is required"
            )
    template = json.loads(args.configure_template.read_text())
    state: dict[str, Any] = {
        "classification": "T510_STAGE34A_AUTOMATED_IN_PROGRESS",
        "ok": False,
        "core_version": CORE_VERSION,
        "bitstream_sha256": BITSTREAM_SHA256,
        "pfb_profile_id": PFB_PROFILE_ID,
        "started_unix_ms": int(time.time() * 1000),
        "phases": [],
        "errors": [],
    }
    current_center = STABILITY_CENTER_MHZ
    write_json(state_path, state)
    try:
        audit = audit_frozen_evidence(args.board_evidence, args.fullband_evidence)
        write_json(output / "frozen_evidence_audit.json", audit)
        state["phases"].append({"name": "frozen_evidence_audit", "ok": True})
        write_json(state_path, state)
        scan, windows160 = run_scan160(args, output, template)
        if not scan["ok"]:
            raise RuntimeError("160 MS/s muted scan did not pass")
        state["phases"].append({"name": "muted_fullband_160", "ok": scan["ok"], "windows": len(scan["windows"])})
        write_json(state_path, state)
        for rate in (320, 160):
            current_center = STABILITY_CENTER_MHZ
            stability = run_stability_mode(args, output, template, rate)
            if not stability["ok"]:
                raise RuntimeError(f"{rate} MS/s stability did not pass")
            state["phases"].append({"name": f"stability_{rate}msps", "ok": stability["ok"]})
            write_json(state_path, state)
        analysis = write_automated_analysis(output, args.fullband_evidence, windows160)
        state["analysis"] = analysis
        manifest = pcap_manifest(output, args.fullband_evidence)
        state["pcap_manifest"] = {"path": str(manifest), "sha256": sha256_file(manifest)}
        state["ok"] = bool(analysis["automated_astronomy_pass"])
        state["classification"] = (
            "T510_STAGE34A_AUTOMATED_COMPLETE_TG_PENDING"
            if state["ok"]
            else "T510_STAGE34A_AUTOMATED_FAIL"
        )
    except Exception as error:
        state["errors"].append(f"{type(error).__name__}: {error}")
        state["classification"] = "T510_STAGE34A_AUTOMATED_FAIL"
    finally:
        state["errors"].extend(stop_and_mute(args.agent_base, current_center))
        state["finished_unix_ms"] = int(time.time() * 1000)
        if state["errors"]:
            state["ok"] = False
            state["classification"] = "T510_STAGE34A_AUTOMATED_FAIL"
        write_json(state_path, state)
        board_summary = {
            "classification": state["classification"],
            "ok": state["ok"],
            "core_version": CORE_VERSION,
            "bitstream_sha256": BITSTREAM_SHA256,
            "receiver_campaign": str(state_path),
            "receiver_campaign_sha256": sha256_file(state_path),
            "phases": state["phases"],
            "errors": state["errors"],
        }
        write_json(board_output / "campaign_summary.json", board_summary)
    print(json.dumps({"classification": state["classification"], "ok": state["ok"], "phases": state["phases"], "errors": state["errors"]}, indent=2), flush=True)
    return 0 if state["ok"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("build/receiver/latest/evidence/performance_evaluation"))
    parser.add_argument("--board-output", type=Path, default=Path("build/board/latest/evidence/performance_evaluation"))
    parser.add_argument("--board-evidence", type=Path, default=Path("build/board/latest/evidence"))
    parser.add_argument("--fullband-evidence", type=Path, default=Path("build/receiver/latest/evidence/fullband_spur_scan"))
    parser.add_argument("--configure-template", type=Path, default=Path("config/t510/configure_320_time_only.example.json"))
    parser.add_argument("--agent-base", default="http://192.168.100.117:8010")
    parser.add_argument("--receiver-base", default="http://192.168.100.162:8089")
    parser.add_argument("--settle-seconds", type=float, default=2.0)
    parser.add_argument(
        "--resume",
        action="store_true",
        help="resume only an explicitly inspected in-progress successful prefix; failed phases are never retried",
    )
    return run_automated(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
