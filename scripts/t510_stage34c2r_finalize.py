#!/usr/bin/env python3
"""Recapture three low-RF context runs and finalize the completed 34c-2R matrix."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tempfile
import time
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import t510_adc_correlated_noise_campaign as c34c
from scripts import t510_clock_sysref_causality as campaign
from scripts import t510_fullband_spur_scan as fullband
from scripts import t510_stage34c2r_science_runner as runner


def write_json(path: Path, value: Any) -> None:
    campaign.write_json(path, value)


def validate_completed_r6(path: Path) -> dict[str, Any]:
    source = json.loads(path.read_text())
    expected = {
        "core_version": campaign.CORE_VERSION,
        "bitstream_id": campaign.BITSTREAM_ID,
        "bitstream_sha256": campaign.BITSTREAM_SHA256,
        "pfb_profile_id": campaign.PFB_PROFILE_ID,
    }
    for key, value in expected.items():
        if source.get(key) != value:
            raise RuntimeError(f"r6 {key} mismatch")
    if (
        source.get("classification") != "STAGE34C2_OPERATIONAL_FAIL"
        or source.get("errors") != ["ModuleNotFoundError: No module named 'matplotlib'"]
    ):
        raise RuntimeError("r6 is not the registered post-analysis plotting failure")
    if source.get("analysis") is None:
        raise RuntimeError("r6 analysis is missing")

    rows = list(source.get("runs") or [])
    formal_by_name = {
        row["name"]: row
        for row in rows
        if int(row.get("duration_seconds", 0)) == campaign.FORMAL_SECONDS
    }
    expected_formal = {
        row["name"]
        for layer in ("sysref", "frequency")
        for row in campaign.formal_triplet_plan(layer)
    }
    if set(formal_by_name) != expected_formal:
        raise RuntimeError("r6 formal run set is incomplete")
    for name, row in formal_by_name.items():
        if (
            row.get("ok") is not True
            or row.get("errors")
            or not (row.get("integrity") or {}).get("ok")
            or len((row.get("analysis") or {}).get("combinations") or [])
            != len(campaign.LANES) * len(campaign.RF_FREQUENCIES_MHZ)
        ):
            raise RuntimeError(f"r6 formal run is not reusable: {name}")

    low_by_name = {
        row["name"]: row
        for row in rows
        if int(row.get("duration_seconds", 0)) == campaign.LOW_RF_SECONDS
    }
    expected_low = {
        row["name"]
        for row in campaign.low_rf_plan(include_tcxo=False)
    }
    if set(low_by_name) != expected_low:
        raise RuntimeError("r6 low-RF run set is incomplete")
    accepted_low: list[dict[str, Any]] = []
    recapture: list[dict[str, Any]] = []
    plans = {
        row["name"]: row for row in campaign.low_rf_plan(include_tcxo=False)
    }
    for name, row in low_by_name.items():
        if int(row.get("sample_rate_msps", 0)) == 160:
            if row.get("ok") is not True or row.get("errors"):
                raise RuntimeError(f"r6 160 MS/s low-RF run is not reusable: {name}")
            accepted_low.append(row)
            continue
        errors = row.get("errors") or []
        if (
            row.get("ok") is not False
            or len(errors) != 1
            or "FINAL_DAC_MUTE_FAILED" not in errors[0]
            or "center_mhz must be finite and within 160..1760 MHz" not in errors[0]
            or not (row.get("integrity") or {}).get("ok")
            or len((row.get("analysis") or {}).get("combinations") or [])
            != len(campaign.LANES) * len(campaign.LOW_RF_MARKERS_MHZ)
        ):
            raise RuntimeError(f"r6 320 MS/s low-RF failure is not registered: {name}")
        recapture.append(plans[name])

    formal = list(formal_by_name.values())
    recomputed = campaign.classify_layers(formal, False)
    if recomputed != source["analysis"]:
        raise RuntimeError("r6 frozen analysis does not reproduce bit-exactly")
    return {
        "source": str(path.resolve()),
        "source_sha256": campaign.sha256_file(path),
        "formal": formal,
        "accepted_low": accepted_low,
        "recapture": sorted(recapture, key=lambda row: row["name"]),
        "analysis": recomputed,
    }


def referenced_pcap_manifest(
    output: Path, runs: list[dict[str, Any]], repo: Path
) -> dict[str, Any]:
    seen: set[Path] = set()
    rows: list[tuple[str, str]] = []
    for run in runs:
        for edge in ("begin_capture", "end_capture"):
            for value in (run.get(edge) or {}).get("paths") or []:
                path = Path(value).resolve()
                if path in seen:
                    continue
                if not path.is_file():
                    raise RuntimeError(f"referenced PCAP is missing: {path}")
                seen.add(path)
                try:
                    label = str(path.relative_to(repo))
                except ValueError:
                    label = str(path)
                rows.append((campaign.sha256_file(path), label))
    manifest = output / "pcap_manifest.sha256"
    manifest.write_text("".join(f"{digest}  {label}\n" for digest, label in sorted(rows)))
    return {
        "path": str(manifest.resolve()),
        "sha256": campaign.sha256_file(manifest),
        "pcap_count": len(rows),
    }


def final_classification(analysis: dict[str, Any]) -> str:
    neutral = {
        "CLOCK_SYSREF_NOT_CAUSAL_UNDER_SHARED_50OHM",
        "INCONCLUSIVE_BASELINE_NOT_REPRODUCED",
        "TCXO_PROFILE_UNQUALIFIED",
    }
    values = [analysis[layer]["classification"] for layer in ("sysref", "frequency", "reference")]
    return next((value for value in values if value not in neutral), values[0])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent-base", default="http://192.168.100.117:8010")
    parser.add_argument("--receiver-base", default="http://192.168.100.162:8089")
    parser.add_argument("--board-ssh", default="xilinx@192.168.100.117")
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--candidate-overlay", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--configure-template", type=Path, required=True)
    parser.add_argument("--r4-campaign", type=Path, required=True)
    parser.add_argument("--r6-campaign", type=Path, required=True)
    parser.add_argument("--receiver-output", type=Path, required=True)
    parser.add_argument("--board-output", type=Path, required=True)
    parser.add_argument("--settle-seconds", type=float, default=2.0)
    parser.add_argument("--ssa-confirmed", action="store_true")
    args = parser.parse_args()
    if not args.ssa_confirmed:
        parser.error("--ssa-confirmed is required")
    for name in (
        "repo", "candidate_overlay", "manifest", "configure_template",
        "r4_campaign", "r6_campaign", "receiver_output", "board_output",
    ):
        setattr(args, name, getattr(args, name).resolve())
    args.bitstream_id = campaign.BITSTREAM_ID
    args.expected_core_version = campaign.CORE_VERSION
    output = args.receiver_output
    result_path = output / "campaign.json"
    runner_path = args.board_output / "runner.json"
    if result_path.exists() or runner_path.exists():
        raise RuntimeError("refusing to overwrite Stage 34c-2R finalization evidence")
    output.mkdir(parents=True, exist_ok=True)
    args.board_output.mkdir(parents=True, exist_ok=True)
    source = validate_completed_r6(args.r6_campaign)
    qualification = campaign.validate_resume_checkpoint(args.r4_campaign)
    template = json.loads(args.configure_template.read_text())
    state: dict[str, Any] = {
        "classification": "STAGE34C2_FINALIZATION_IN_PROGRESS",
        "operational_ok": False,
        "source_r6": {key: source[key] for key in ("source", "source_sha256")},
        "qualification_r4": {
            "source": qualification["source"],
            "source_sha256": qualification["source_sha256"],
        },
        "recapture_runs": [],
        "errors": [],
        "started_at_unix_ms": time.time_ns() // 1_000_000,
    }
    write_json(result_path, state)
    board_state: dict[str, Any] = {
        "classification": "V35_FINALIZATION_RUNNER_IN_PROGRESS",
        "operational_ok": False,
        "errors": [],
        "started_at_unix_ms": time.time_ns() // 1_000_000,
    }
    write_json(runner_path, board_state)
    original_board = None
    original_receiver = None
    exit_code = 1
    try:
        original_board = fullband._http_json(args.agent_base.rstrip("/") + "/api/v2/status")
        original_receiver = fullband._http_json(args.receiver_base.rstrip("/") + "/api/state")
        mute_errors = c34c.stop_and_mute(args, campaign.CENTER_MHZ)
        if mute_errors:
            raise RuntimeError(f"predeploy STOP/DAC mute failed: {mute_errors}")
        with tempfile.TemporaryDirectory(prefix="t510-stage34c2r-finalize-") as temporary:
            bundle = Path(temporary) / "bundle"
            runner.build_bundle(args, bundle)
            runner.deploy_candidate(args, bundle)
        board_state["candidate_deployed"] = True
        write_json(runner_path, board_state)
        targets = qualification["targets"]
        for spec in source["recapture"]:
            print(f"CLOCK_FINALIZE_RECAPTURE_START {spec['name']}", flush=True)
            row = campaign.execute_run(
                args,
                template,
                name=f"recapture_{spec['name']}",
                profile_id=spec["profile_id"],
                sample_rate_msps=spec["sample_rate_msps"],
                center_mhz=campaign.LOW_RF_CENTER_MHZ,
                frequencies_mhz=campaign.LOW_RF_MARKERS_MHZ,
                duration_seconds=campaign.LOW_RF_SECONDS,
                target=targets[spec["profile_id"]],
                formal=False,
                thermal_stabilize=False,
            )
            if not row.get("ok"):
                raise RuntimeError(f"low-RF recapture failed: {spec['name']}")
            state["recapture_runs"].append(row)
            write_json(result_path, state)
            print(f"CLOCK_FINALIZE_RECAPTURE_COMPLETE {spec['name']}", flush=True)

        combined = [*source["accepted_low"], *state["recapture_runs"], *source["formal"]]
        state["analysis"] = campaign.classify_layers(source["formal"], False)
        state["classification"] = final_classification(state["analysis"])
        state["source_classification"] = {
            key: value["classification"] for key, value in state["analysis"].items()
        }
        state["combined_run_count"] = len(combined)
        state["formal_run_count"] = len(source["formal"])
        campaign.write_summary_csv(output / "summary.csv", combined)
        state["plots"] = campaign.write_plots(output, combined)
        state["pcap_manifest"] = referenced_pcap_manifest(output, combined, args.repo)
        state["operational_ok"] = True
        exit_code = 0
    except Exception as exc:
        state["errors"].append(f"{type(exc).__name__}: {exc}")
        state["classification"] = "STAGE34C2_FINALIZATION_OPERATIONAL_FAIL"
    finally:
        board_state["production_restore"] = runner.restore_production(
            args, template, original_board, original_receiver
        )
        if not board_state["production_restore"].get("restored"):
            state["errors"].extend(board_state["production_restore"].get("errors", []))
            state["operational_ok"] = False
            state["classification"] = "STAGE34C2_FINALIZATION_OPERATIONAL_FAIL"
            exit_code = 1
        state["finished_at_unix_ms"] = time.time_ns() // 1_000_000
        write_json(result_path, state)
        board_state.update(
            {
                "classification": (
                    "V35_FINALIZATION_COMPLETE" if state["operational_ok"]
                    else "V35_FINALIZATION_OPERATIONAL_FAIL"
                ),
                "operational_ok": state["operational_ok"],
                "receiver_campaign": str(result_path),
                "receiver_campaign_sha256": campaign.sha256_file(result_path),
                "errors": list(state["errors"]),
                "finished_at_unix_ms": time.time_ns() // 1_000_000,
            }
        )
        write_json(runner_path, board_state)
    print(json.dumps({key: state.get(key) for key in ("classification", "operational_ok", "combined_run_count", "errors")}, indent=2), flush=True)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
