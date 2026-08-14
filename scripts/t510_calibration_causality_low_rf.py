#!/usr/bin/env python3
"""Run the Stage 34b-2 low-RF A/B/C causality extension."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import t510_calibration_causality as causality


LOW_RF_BANDS: dict[str, dict[str, Any]] = {
    "low": {
        "rf_frequencies_mhz": (50.0, 75.0, 100.0, 125.0, 150.0, 175.0),
        "centers_mhz": {160: 112.5, 320: 160.0},
    },
    "high": {
        "rf_frequencies_mhz": (205.0, 230.0, 255.0, 280.0, 305.0, 330.0),
        "centers_mhz": {160: 267.5, 320: 267.5},
    },
}
EVIDENCE_SCOPE = "34b2/low_rf"


def low_rf_runs() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for rate in causality.RATES_MSPS:
        for repeat, order in enumerate(causality.BALANCED_ORDERS, start=1):
            for position, condition in enumerate(order, start=1):
                for band_name, band in LOW_RF_BANDS.items():
                    index = len(rows)
                    rows.append(
                        {
                            "index": index,
                            "name": (
                                f"{index + 1:02d}_{band_name}_{rate}msps_"
                                f"r{repeat}_{condition}"
                            ),
                            "band": band_name,
                            "sample_rate_msps": rate,
                            "repeat": repeat,
                            "position": position,
                            "condition": condition,
                            "center_mhz": float(band["centers_mhz"][rate]),
                            "rf_frequencies_mhz": list(band["rf_frequencies_mhz"]),
                        }
                    )
    return rows


def validate_frequency_plan() -> list[dict[str, Any]]:
    rows = []
    for band_name, band in LOW_RF_BANDS.items():
        frequencies = tuple(float(value) for value in band["rf_frequencies_mhz"])
        if min(frequencies) < 30.0 or max(frequencies) > 350.0:
            raise RuntimeError(f"{band_name} lies outside the requested 30..350 MHz region")
        for rate in causality.RATES_MSPS:
            center = float(band["centers_mhz"][rate])
            spacing = float(rate) / 4096.0
            signed_bins = [round((frequency - center) / spacing) for frequency in frequencies]
            errors_hz = [
                abs((center + signed_bin * spacing - frequency) * 1.0e6)
                for frequency, signed_bin in zip(frequencies, signed_bins)
            ]
            lower_edge = center - rate / 2.0
            upper_edge = center + rate / 2.0
            edge_guard = min(min(frequencies) - lower_edge, upper_edge - max(frequencies))
            if max(errors_hz) > 1.0e-3:
                raise RuntimeError(f"{band_name}/{rate} targets are not exact PFB bins")
            if edge_guard < 15.0:
                raise RuntimeError(f"{band_name}/{rate} has only {edge_guard} MHz edge guard")
            rows.append(
                {
                    "band": band_name,
                    "sample_rate_msps": rate,
                    "center_mhz": center,
                    "rf_frequencies_mhz": list(frequencies),
                    "signed_bins": signed_bins,
                    "edge_guard_mhz": edge_guard,
                }
            )
    return rows


def load_preflight(board_output: Path) -> dict[str, Any]:
    path = board_output.resolve() / "34b2" / "amplitude_preflight_pg269.json"
    value = json.loads(path.read_text())
    if value.get("classification") != "T510_STAGE34B2_AMPLITUDE_PREFLIGHT_PASS":
        raise RuntimeError(f"low-RF campaign requires the passing amplitude preflight {path}")
    return value


def run(args: argparse.Namespace, template: dict[str, Any]) -> int:
    plan = low_rf_runs()
    frequency_plan = validate_frequency_plan()
    preflight = load_preflight(args.board_output)
    selected_amplitude = float(preflight["selected_amplitude_percent"])
    root = args.receiver_output.resolve() / EVIDENCE_SCOPE
    campaign_path = root / "campaign.json"
    if campaign_path.exists():
        raise RuntimeError(f"refusing to overwrite existing low-RF campaign {campaign_path}")
    state: dict[str, Any] = {
        "classification": "T510_STAGE34B2_LOW_RF_CAUSALITY_IN_PROGRESS",
        "ok": False,
        "core_version": causality.CORE_VERSION,
        "bitstream_sha256": causality.BITSTREAM_SHA256,
        "pfb_profile_id": causality.PFB_PROFILE_ID,
        "requested_rf_region_mhz": [30.0, 350.0],
        "measured_rf_region_mhz": [50.0, 330.0],
        "edge_policy": "20 MHz endpoint guard; every target is an exact PFB bin",
        "frequency_plan": frequency_plan,
        "selected_amplitude_percent": selected_amplitude,
        "duration_seconds_per_run": causality.FORMAL_DURATION_SECONDS,
        "planned_runs": plan,
        "completed_runs": [],
        "errors": [],
        "started_unix_ms": time.time_ns() // 1_000_000,
    }
    causality.write_json(campaign_path, state)
    last_center = 160.0
    try:
        for row in plan:
            last_center = float(row["center_mhz"])
            print(
                "STAGE34B2_LOW_RF_RUN_START "
                f"{row['index'] + 1}/36 band={row['band']} "
                f"rate={row['sample_rate_msps']} repeat={row['repeat']} "
                f"condition={row['condition']} center={last_center:g}",
                flush=True,
            )
            result = causality.execute_run(
                args,
                template,
                row,
                selected_amplitude,
                center_mhz=last_center,
                rf_frequencies_mhz=tuple(float(value) for value in row["rf_frequencies_mhz"]),
                evidence_scope=EVIDENCE_SCOPE,
            )
            result_path = root / "runs" / result["name"] / "result.json"
            state["completed_runs"].append(
                {
                    "name": result["name"],
                    "band": result["band"],
                    "sample_rate_msps": result["sample_rate_msps"],
                    "repeat": result["repeat"],
                    "condition": result["condition"],
                    "result_path": str(result_path.resolve()),
                }
            )
            causality.write_json(campaign_path, state)
            print(f"STAGE34B2_LOW_RF_RUN_PASS {result['name']}", flush=True)

        results = [
            json.loads(Path(row["result_path"]).read_text())
            for row in state["completed_runs"]
        ]
        gates = {}
        for band_name in LOW_RF_BANDS:
            selected = [row for row in results if row["band"] == band_name]
            gates[band_name] = causality.aggregate_gate(selected)
            causality.write_summary_csv(root / f"{band_name}_causality_summary.csv", selected)
        state["gates"] = gates
        state["ok"] = all(bool(value["ok"]) for value in gates.values())
        state["classification"] = (
            "T510_STAGE34B2_LOW_RF_CAUSALITY_PASS"
            if state["ok"]
            else (
                "INCONCLUSIVE_LOW_RF_BASELINE_NOT_REPRODUCED"
                if any(
                    value["classification"] == "INCONCLUSIVE_BASELINE_NOT_REPRODUCED"
                    for value in gates.values()
                )
                else "T510_STAGE34B2_LOW_RF_CAUSALITY_FAIL"
            )
        )
        manifest = causality.write_pcap_manifest(root)
        state["pcap_manifest"] = {
            "path": str(manifest.resolve()),
            "sha256": causality.sha256_file(manifest),
        }
    except Exception as exc:  # noqa: BLE001 - fail closed and preserve evidence
        state["errors"].append(f"{type(exc).__name__}: {exc}")
        state["classification"] = "T510_STAGE34B2_LOW_RF_OPERATIONAL_FAIL"
    finally:
        state["errors"].extend(causality.stop_mute_unfreeze(args.agent_base, last_center))
        state["finished_unix_ms"] = time.time_ns() // 1_000_000
        if state["errors"]:
            state["ok"] = False
            state["classification"] = "T510_STAGE34B2_LOW_RF_OPERATIONAL_FAIL"
        causality.write_json(campaign_path, state)
        board_summary = {
            "classification": state["classification"],
            "ok": state["ok"],
            "campaign_path": str(campaign_path),
            "campaign_sha256": causality.sha256_file(campaign_path),
            "completed_run_count": len(state["completed_runs"]),
            "errors": state["errors"],
        }
        causality.write_json(
            args.board_output.resolve() / EVIDENCE_SCOPE / "campaign_summary.json",
            board_summary,
        )
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
    args = parser.parse_args()
    template = json.loads(args.configure_template.read_text())
    return run(args, template)


if __name__ == "__main__":
    raise SystemExit(main())
