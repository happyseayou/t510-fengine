#!/usr/bin/env python3
"""Manual SSA TG entry points for the Stage 34a ADC0/ADC2 evaluation."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
import statistics
import sys
import time
from typing import Any

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import t510_astronomy as astronomy
import t510_astronomy_performance as performance
from scripts import t510_fullband_spur_scan as fullband
from scripts.t510_plot_spec_udp_pcap import (
    HEADER_BYTES,
    ethernet_udp_payload,
    iter_pcap_packets,
    parse_spec_header,
    signed_bin,
)


REFERENCES = {
    "408": {"label": "408 MHz continuum", "tone_mhz": 408.0, "center_mhz": 468.0},
    "hi": {"label": "H I 1420.4057518 MHz", "tone_mhz": 1420.4057518, "center_mhz": 1480.4057518},
    "oh": {"label": "OH 1665.40184 MHz", "tone_mhz": 1665.40184, "center_mhz": 1725.40184},
}
TG_FROZEN_OFFSET_MHZ = 91.71875


def tg_plan() -> dict[str, Any]:
    captures = []
    for reference in ("408", "hi", "oh"):
        levels = (-30, -25, -20) if reference == "hi" else (-20,)
        for rate in (160, 320):
            for level in levels:
                captures.append(
                    {
                        "reference": reference,
                        "sample_rate_msps": rate,
                        "tg_level_dbm": level,
                        "tone_mhz": REFERENCES[reference]["tone_mhz"],
                        "center_mhz": REFERENCES[reference]["center_mhz"],
                        "signed_bin": -1536 if rate == 160 else -768,
                    }
                )
    return {
        "physical_connection": "SSA TG -> verified two-way splitter -> ADC0/ADC2",
        "dac_required": "all eight channels muted",
        "captures": captures,
        "stability": [
            {"reference": "hi", "sample_rate_msps": rate, "tg_level_dbm": -20, "duration_seconds": 600}
            for rate in (160, 320)
        ],
        "fresh_configure_mts_repeatability": {
            "reference": "hi",
            "sample_rate_msps": 320,
            "tg_level_dbm": -20,
            "cycles": 5,
            "automatic_retry": False,
        },
        "source_limited_signature": {
            "carrier_relative_offset_mhz": TG_FROZEN_OFFSET_MHZ,
            "rule": "SOURCE_LIMITED only when the same offset is reproduced on ADC0 and ADC2; raw peak remains visible",
        },
    }


def ensure_confirmation(args: argparse.Namespace) -> None:
    if not args.confirm_source:
        raise RuntimeError(
            "SSA has no SCPI automation: set the requested TG frequency/level and pass --confirm-source"
        )


def setup_stream(args: argparse.Namespace, reference: str, rate: int) -> tuple[dict[str, Any], dict[str, Any]]:
    spec = REFERENCES[reference]
    template = json.loads(args.configure_template.read_text())
    performance.receiver_prepare(args.receiver_base, rate, spec["center_mhz"])
    configured = fullband._http_json(
        args.agent_base.rstrip("/") + "/api/v2/configure",
        method="POST",
        body=performance.configure_body(template, rate, spec["center_mhz"]),
        timeout=190.0,
    )
    status = fullband._http_json(args.agent_base.rstrip("/") + "/api/v2/status")
    board_id = int(status.get("board_id", 1))
    fullband._http_json(
        args.agent_base.rstrip("/") + "/api/v2/dac",
        method="PUT",
        body=performance.mute_body(spec["center_mhz"], board_id),
    )
    fullband._http_json(
        args.agent_base.rstrip("/") + "/api/v2/start",
        method="POST",
        body={"expected_board_id": board_id},
    )
    time.sleep(args.settle_seconds)
    status = fullband._http_json(args.agent_base.rstrip("/") + "/api/v2/status")
    performance.validate_board_status(status, rate, spec["center_mhz"])
    return configured, status


def carrier_bin(reference: str, rate: int) -> int:
    spec = REFERENCES[reference]
    return astronomy.signed_bin_to_index(
        astronomy.rf_to_signed_bin(spec["tone_mhz"], spec["center_mhz"], rate)
    )


def collect_carrier_iq(paths: list[Path], selected_bin: int) -> dict[str, Any]:
    selected_block, local_bin = divmod(selected_bin, 256)
    lanes = [
        {"count": 0, "sum_i": 0.0, "sum_q": 0.0, "sum_power": 0.0}
        for _ in range(astronomy.NINPUT)
    ]
    cross = {"sample_count": 0, "sum_cross_re": 0.0, "sum_cross_im": 0.0, "sum_power_a": 0.0, "sum_power_b": 0.0}
    for path in paths:
        for frame in iter_pcap_packets(path):
            udp = ethernet_udp_payload(frame)
            if udp is None:
                continue
            _port, payload = udp
            header = parse_spec_header(payload)
            if int(header["block_index"]) != selected_block:
                continue
            base = HEADER_BYTES + local_bin * astronomy.NINPUT * 4
            values = []
            for lane in range(astronomy.NINPUT):
                offset = base + lane * 4
                i = int.from_bytes(payload[offset : offset + 2], "little", signed=True)
                q = int.from_bytes(payload[offset + 2 : offset + 4], "little", signed=True)
                power = float(i * i + q * q)
                values.append((i, q, power))
                row = lanes[lane]
                row["count"] += 1
                row["sum_i"] += i
                row["sum_q"] += q
                row["sum_power"] += power
            i0, q0, p0 = values[0]
            i2, q2, p2 = values[2]
            cross["sample_count"] += 1
            cross["sum_cross_re"] += i0 * i2 + q0 * q2
            cross["sum_cross_im"] += q0 * i2 - i0 * q2
            cross["sum_power_a"] += p0
            cross["sum_power_b"] += p2
    if not lanes[0]["count"]:
        raise RuntimeError("carrier block was not present in PCAP")
    for row in lanes:
        row["mean_power"] = row["sum_power"] / row["count"]
        row["power_dbfs"] = astronomy.power_dbfs(row["mean_power"])
    return {"lanes": lanes, "adc0_adc2": astronomy.coherence_from_accumulators([cross])}


def draw_context(path: Path, decoded: dict[str, Any], reference: str, rate: int, level_dbm: int) -> None:
    spec = REFERENCES[reference]
    image, draw, boxes = performance.panels(
        f"SSA TG {spec['label']} at {level_dbm} dBm — {rate} MS/s context",
        "All eight ADC lanes shown; only ADC0/ADC2 are connected to the external splitter. Dashed annotation is dBFS/bin, not dBm.",
    )
    for lane, (left, top, right, bottom) in enumerate(boxes):
        draw.rounded_rectangle((left, top, right, bottom), 8, fill="white", outline="#cbd5e1", width=2)
        pl, pt, pr, pb = left + 62, top + 40, right - 18, bottom - 40
        values = decoded["power_dbfs"][lane]
        draw.text((left + 12, top + 8), f"ADC{lane} {'TG path' if lane in (0, 2) else 'context only'}", fill="#0f172a", font=performance.font(17, True))
        columns = [[] for _ in range(pr - pl + 1)]
        for index, value in enumerate(values):
            x = min(len(columns) - 1, round((signed_bin(index, astronomy.NCHAN) + 2048) / 4095 * (len(columns) - 1)))
            columns[x].append(value)
        points = []
        for x, column in enumerate(columns):
            value = max(column) if column else -110.0
            y = round(pb - (min(max(value, -110), 5) + 110) / 115 * (pb - pt))
            points.append((pl + x, y))
        draw.line(points, fill="#2563eb" if lane in (0, 2) else "#64748b", width=1)
        selected = carrier_bin(reference, rate)
        carrier = values[selected]
        noise_indices = [index for index in range(astronomy.NCHAN) if fullband.circular_bin_distance(index, selected) > 8 and 13 <= abs(signed_bin(index, astronomy.NCHAN)) <= 1536]
        noise = statistics.median(values[index] for index in noise_indices)
        draw.text((pl + 5, pt + 5), f"carrier {carrier:.2f} dBFS; median noise {noise:.2f} dBFS/bin", fill="#7c2d12", font=performance.font(12))
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, optimize=True)


def capture_once(args: argparse.Namespace) -> int:
    ensure_confirmation(args)
    spec = REFERENCES[args.reference]
    output = args.output / "tg" / args.reference / f"{args.sample_rate_msps}msps" / f"level_{args.level_dbm:+d}dbm"
    result_path = output / "capture.json"
    if result_path.exists():
        raise RuntimeError(f"refusing to overwrite TG capture {result_path}")
    evidence: dict[str, Any] = {
        "classification": "T510_STAGE34A_TG_CAPTURE_IN_PROGRESS",
        "ok": False,
        "operator_confirmed_source": True,
        "reference": args.reference,
        "sample_rate_msps": args.sample_rate_msps,
        "tg_level_dbm": args.level_dbm,
        "tone_mhz": spec["tone_mhz"],
        "center_mhz": spec["center_mhz"],
        "errors": [],
    }
    try:
        configured, before_board = setup_stream(args, args.reference, args.sample_rate_msps)
        before_rx = fullband._http_json(args.receiver_base.rstrip("/") + "/api/state")
        paths, capture = fullband.capture_receiver_pcap(
            receiver_base=args.receiver_base,
            local_dir=output / "raw",
            packets_per_block=performance.PACKETS_PER_BLOCK,
        )
        decoded = performance.decode_window(paths, args.sample_rate_msps)
        iq = collect_carrier_iq(paths, carrier_bin(args.reference, args.sample_rate_msps))
        after_board = fullband._http_json(args.agent_base.rstrip("/") + "/api/v2/status")
        after_rx = fullband._http_json(args.receiver_base.rstrip("/") + "/api/state")
        integrity = fullband._window_integrity(before_board, after_board, before_rx, after_rx)
        selected = carrier_bin(args.reference, args.sample_rate_msps)
        peak_rows = []
        for lane in (0, 2):
            spectrum = decoded["power_dbfs"][lane]
            peak = max(range(astronomy.NCHAN), key=spectrum.__getitem__)
            error_bins = min((peak - selected) % astronomy.NCHAN, (selected - peak) % astronomy.NCHAN)
            peak_rows.append({"lane": lane, "peak_bin": peak, "expected_bin": selected, "frequency_error_bins": error_bins, "carrier_dbfs": spectrum[selected]})
        adc_delta = abs(peak_rows[0]["carrier_dbfs"] - peak_rows[1]["carrier_dbfs"])
        source_signature: dict[str, Any] = {
            "frozen_offset_mhz": TG_FROZEN_OFFSET_MHZ,
            "visible_in_selected_band": args.sample_rate_msps == 320,
            "classification": "NOT_IN_SELECTED_160MSPS_BAND" if args.sample_rate_msps == 160 else "NOT_REPRODUCED",
            "lanes": [],
        }
        if args.sample_rate_msps == 320:
            signature_rf = spec["tone_mhz"] + TG_FROZEN_OFFSET_MHZ
            signature_signed = astronomy.rf_to_signed_bin(signature_rf, spec["center_mhz"], 320)
            signature_bin = astronomy.signed_bin_to_index(signature_signed)
            for lane in (0, 2):
                spectrum = decoded["power_dbfs"][lane]
                prominence, background = performance.local_prominence(spectrum, signature_bin, 26)
                source_signature["lanes"].append(
                    {
                        "lane": lane,
                        "rf_mhz": signature_rf,
                        "signed_bin": signature_signed,
                        "power_dbfs": spectrum[signature_bin],
                        "local_median_dbfs": background,
                        "prominence_db": prominence,
                    }
                )
            if all(row["prominence_db"] >= 6.0 for row in source_signature["lanes"]):
                source_signature["classification"] = "SOURCE_LIMITED"
        ok = integrity["ok"] and all(row["frequency_error_bins"] <= 1 for row in peak_rows) and adc_delta <= 1.0
        plot = output / "tg_context_8lane.png"
        draw_context(plot, decoded, args.reference, args.sample_rate_msps, args.level_dbm)
        evidence.update(
            {
                "ok": ok,
                "classification": "T510_STAGE34A_TG_CAPTURE_PASS" if ok else "T510_STAGE34A_TG_CAPTURE_FAIL",
                "configured": configured,
                "capture": capture,
                "decoded_capture": decoded["capture"],
                "integrity": integrity,
                "adc0_adc2_carrier_delta_db": adc_delta,
                "carrier_peaks": peak_rows,
                "carrier_iq": iq,
                "tg_frozen_offset_signature": source_signature,
                "plot": {"path": str(plot.resolve()), "sha256": performance.sha256_file(plot)},
            }
        )
        if not ok:
            evidence["errors"].append("TG capture acceptance failed")
    except Exception as error:
        evidence["errors"].append(f"{type(error).__name__}: {error}")
        evidence["classification"] = "T510_STAGE34A_TG_CAPTURE_FAIL"
    finally:
        evidence["errors"].extend(performance.stop_and_mute(args.agent_base, spec["center_mhz"]))
        if evidence["errors"]:
            evidence["ok"] = False
            evidence["classification"] = "T510_STAGE34A_TG_CAPTURE_FAIL"
        performance.write_json(result_path, evidence)
    return 0 if evidence["ok"] else 1


def unwrap_degrees(values: list[float]) -> list[float]:
    output = [values[0]]
    for value in values[1:]:
        while value - output[-1] > 180.0:
            value -= 360.0
        while value - output[-1] < -180.0:
            value += 360.0
        output.append(value)
    return output


def run_tg_stability(args: argparse.Namespace) -> int:
    ensure_confirmation(args)
    if args.reference != "hi" or args.level_dbm != -20:
        raise RuntimeError("formal TG stability is fixed to H I at -20 dBm")
    spec = REFERENCES["hi"]
    output = args.output / "tg" / "hi" / f"{args.sample_rate_msps}msps" / "stability_10minute"
    result_path = output / "result.json"
    if result_path.exists():
        raise RuntimeError(f"refusing to overwrite TG stability {result_path}")
    evidence: dict[str, Any] = {"classification": "T510_STAGE34A_TG_STABILITY_IN_PROGRESS", "ok": False, "errors": []}
    try:
        _configured, before_board = setup_stream(args, "hi", args.sample_rate_msps)
        before_rx = fullband._http_json(args.receiver_base.rstrip("/") + "/api/state")
        request = {
            "duration_seconds": 600,
            "sample_rate_msps": args.sample_rate_msps,
            "center_mhz": spec["center_mhz"],
            "rf_frequencies_mhz": [spec["tone_mhz"]],
            "correlation_pair": [0, 2],
        }
        started = fullband._http_json(args.receiver_base.rstrip("/") + "/api/measure/spec-stability", method="POST", body=request)
        raw, rates = performance.wait_for_monitor(args.receiver_base, 600)
        performance.write_json(output / "monitor_raw.json", raw)
        after_board = fullband._http_json(args.agent_base.rstrip("/") + "/api/v2/status")
        after_rx = fullband._http_json(args.receiver_base.rstrip("/") + "/api/state")
        integrity = fullband._window_integrity(before_board, after_board, before_rx, after_rx)
        lane_rows = {lane: [] for lane in (0, 2)}
        for row in raw["power_seconds"]:
            lane = int(row["lane"])
            if lane in lane_rows:
                lane_rows[lane].append(astronomy.mean_power_from_accumulator(row))
        gain_pp = {}
        for lane, powers in lane_rows.items():
            amplitudes = [math.sqrt(power) for power in powers]
            gain_pp[lane] = (max(amplitudes) - min(amplitudes)) / statistics.fmean(amplitudes) * 100.0
        cross_rows = sorted(raw["cross_seconds"], key=lambda row: int(row["second"]))
        phases = unwrap_degrees([math.degrees(math.atan2(float(row["sum_cross_im"]), float(row["sum_cross_re"]))) for row in cross_rows])
        phase_pp = max(phases) - min(phases)
        coherence = astronomy.coherence_from_accumulators(cross_rows)["coherence"]
        ok = integrity["ok"] and max(gain_pp.values()) <= 1.0 and phase_pp <= 3.0 and coherence >= 0.99
        evidence.update(
            {
                "ok": ok,
                "classification": "T510_STAGE34A_TG_STABILITY_PASS" if ok else "T510_STAGE34A_TG_STABILITY_FAIL",
                "sample_rate_msps": args.sample_rate_msps,
                "tg_level_dbm": -20,
                "monitor_start": started,
                "monitor_rates": rates,
                "integrity": integrity,
                "gain_peak_to_peak_percent": gain_pp,
                "phase_peak_to_peak_deg_after_fixed_cable_phase_removal": phase_pp,
                "coherence_adc0_adc2": coherence,
            }
        )
        if not ok:
            evidence["errors"].append("TG 10-minute stability acceptance failed")
    except Exception as error:
        evidence["errors"].append(f"{type(error).__name__}: {error}")
        evidence["classification"] = "T510_STAGE34A_TG_STABILITY_FAIL"
    finally:
        evidence["errors"].extend(performance.stop_and_mute(args.agent_base, spec["center_mhz"]))
        if evidence["errors"]:
            evidence["ok"] = False
            evidence["classification"] = "T510_STAGE34A_TG_STABILITY_FAIL"
        performance.write_json(result_path, evidence)
    return 0 if evidence["ok"] else 1


def run_repeatability(args: argparse.Namespace) -> int:
    ensure_confirmation(args)
    if args.reference != "hi" or args.sample_rate_msps != 320 or args.level_dbm != -20:
        raise RuntimeError("repeatability is fixed to H I, 320 MS/s, -20 dBm")
    output = args.output / "tg" / "hi" / "320msps" / "fresh_configure_mts_5x"
    result_path = output / "result.json"
    if result_path.exists():
        raise RuntimeError(f"refusing to overwrite repeatability {result_path}")
    evidence: dict[str, Any] = {"classification": "T510_STAGE34A_TG_REPEATABILITY_IN_PROGRESS", "ok": False, "cycles": [], "errors": []}
    spec = REFERENCES["hi"]
    try:
        for cycle in range(5):
            print(f"TG_FRESH_CONFIGURE_START {cycle + 1}/5", flush=True)
            configured, before_board = setup_stream(args, "hi", 320)
            paths, capture = fullband.capture_receiver_pcap(receiver_base=args.receiver_base, local_dir=output / "raw" / f"cycle_{cycle + 1}", packets_per_block=performance.PACKETS_PER_BLOCK)
            iq = collect_carrier_iq(paths, carrier_bin("hi", 320))
            row = {
                "cycle": cycle + 1,
                "configured": configured,
                "mts": before_board.get("mts"),
                "capture": capture,
                "adc0_dbfs": iq["lanes"][0]["power_dbfs"],
                "adc2_dbfs": iq["lanes"][2]["power_dbfs"],
                "adc0_adc2": iq["adc0_adc2"],
            }
            evidence["cycles"].append(row)
            performance.write_json(result_path, evidence)
            fullband._http_json(args.agent_base.rstrip("/") + "/api/v2/stop", method="POST")
        adc0 = [row["adc0_dbfs"] for row in evidence["cycles"]]
        adc2 = [row["adc2_dbfs"] for row in evidence["cycles"]]
        phases = unwrap_degrees([row["adc0_adc2"]["phase_deg"] for row in evidence["cycles"]])
        amplitude_span_db = max(max(adc0) - min(adc0), max(adc2) - min(adc2))
        phase_span = max(phases) - min(phases)
        ok = amplitude_span_db <= 1.0 and phase_span <= 3.0 and all(row["adc0_adc2"]["coherence"] >= 0.99 for row in evidence["cycles"])
        evidence.update(
            {
                "ok": ok,
                "classification": "T510_STAGE34A_TG_REPEATABILITY_PASS" if ok else "T510_STAGE34A_TG_REPEATABILITY_FAIL",
                "amplitude_span_db": amplitude_span_db,
                "phase_span_deg_after_fixed_cable_phase_removal": phase_span,
            }
        )
        if not ok:
            evidence["errors"].append("five-cycle repeatability acceptance failed")
    except Exception as error:
        evidence["errors"].append(f"{type(error).__name__}: {error}")
        evidence["classification"] = "T510_STAGE34A_TG_REPEATABILITY_FAIL"
    finally:
        evidence["errors"].extend(performance.stop_and_mute(args.agent_base, spec["center_mhz"]))
        if evidence["errors"]:
            evidence["ok"] = False
            evidence["classification"] = "T510_STAGE34A_TG_REPEATABILITY_FAIL"
        performance.write_json(result_path, evidence)
    return 0 if evidence["ok"] else 1


def finalize(args: argparse.Namespace) -> int:
    plan = tg_plan()
    captures = []
    errors = []
    for expected in plan["captures"]:
        path = args.output / "tg" / expected["reference"] / f"{expected['sample_rate_msps']}msps" / f"level_{expected['tg_level_dbm']:+d}dbm" / "capture.json"
        if not path.is_file():
            errors.append(f"missing {path}")
            continue
        value = json.loads(path.read_text())
        if not value.get("ok"):
            errors.append(f"failed {path}")
        captures.append(value)
    linearity = []
    for rate in (160, 320):
        for lane in (0, 2):
            rows = sorted((value for value in captures if value["reference"] == "hi" and value["sample_rate_msps"] == rate), key=lambda value: value["tg_level_dbm"])
            for left, right in zip(rows, rows[1:]):
                left_power = next(row["carrier_dbfs"] for row in left["carrier_peaks"] if row["lane"] == lane)
                right_power = next(row["carrier_dbfs"] for row in right["carrier_peaks"] if row["lane"] == lane)
                increment = right_power - left_power
                linearity.append({"sample_rate_msps": rate, "lane": lane, "from_dbm": left["tg_level_dbm"], "to_dbm": right["tg_level_dbm"], "digital_increment_db": increment, "pass": abs(increment - 5.0) <= 1.0})
    for rate in (160, 320):
        path = args.output / "tg" / "hi" / f"{rate}msps" / "stability_10minute" / "result.json"
        if not path.is_file() or not json.loads(path.read_text()).get("ok"):
            errors.append(f"missing/failed {path}")
    repeatability = args.output / "tg" / "hi" / "320msps" / "fresh_configure_mts_5x" / "result.json"
    if not repeatability.is_file() or not json.loads(repeatability.read_text()).get("ok"):
        errors.append(f"missing/failed {repeatability}")
    if any(not row["pass"] for row in linearity):
        errors.append("H I 5 dB input-step linearity failed")
    result = {
        "classification": "T510_STAGE34A_TG_COMPLETE_PASS" if not errors else "T510_STAGE34A_TG_INCOMPLETE_OR_FAIL",
        "ok": not errors,
        "scope": "SSA TG + splitter + ADC0/ADC2 end-to-end; not ADC-only SFDR",
        "capture_count": len(captures),
        "linearity": linearity,
        "errors": errors,
    }
    performance.write_json(args.output / "tg" / "final_result.json", result)
    return 0 if result["ok"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("plan", "capture", "stability", "repeatability", "finalize"))
    parser.add_argument("--output", type=Path, default=Path("build/receiver/latest/evidence/performance_evaluation"))
    parser.add_argument("--reference", choices=tuple(REFERENCES), default="hi")
    parser.add_argument("--sample-rate-msps", type=int, choices=(160, 320), default=320)
    parser.add_argument("--level-dbm", type=int, choices=(-30, -25, -20), default=-20)
    parser.add_argument("--confirm-source", action="store_true")
    parser.add_argument("--configure-template", type=Path, default=Path("config/t510/configure_320_time_only.example.json"))
    parser.add_argument("--agent-base", default="http://192.168.100.117:8010")
    parser.add_argument("--receiver-base", default="http://192.168.100.162:8089")
    parser.add_argument("--settle-seconds", type=float, default=2.0)
    args = parser.parse_args()
    if args.action == "plan":
        performance.write_json(args.output / "tg" / "plan.json", tg_plan())
        print(json.dumps(tg_plan(), indent=2))
        return 0
    if args.action == "capture":
        return capture_once(args)
    if args.action == "stability":
        return run_tg_stability(args)
    if args.action == "repeatability":
        return run_repeatability(args)
    return finalize(args)


if __name__ == "__main__":
    raise SystemExit(main())
