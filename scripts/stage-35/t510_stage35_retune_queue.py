#!/usr/bin/env python3
"""Run a complete retuned Stage 35 self-power + XCORR + explorer campaign."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import subprocess
import sys
import time
import traceback
from pathlib import Path
from typing import Any

import t510_stage35_s2_queue as base


FORMAT = "T510_STAGE35_RETUNE_QUEUE_V1"


def run_logged(state_root: Path, name: str, command: list[str], timeout: int) -> None:
    started = base.unix_ms()
    stdout_path = state_root / f"{name}.stdout.log"
    stderr_path = state_root / f"{name}.stderr.log"
    with stdout_path.open("xb") as stdout, stderr_path.open("xb") as stderr:
        result = subprocess.run(command, stdout=stdout, stderr=stderr, timeout=timeout, check=False)
    base.write_json_new(state_root / f"{name}.process.json", {
        "argv": command,
        "started_unix_ms": started,
        "finished_unix_ms": base.unix_ms(),
        "returncode": result.returncode,
        "stdout": str(stdout_path),
        "stderr": str(stderr_path),
    })
    if result.returncode:
        tail = stderr_path.read_text(encoding="utf-8", errors="replace")[-8000:]
        raise RuntimeError(f"{name} failed with {result.returncode}: {tail}")


def make_analysis_config(args: argparse.Namespace, self_id: str, output: Path) -> Path:
    queue_root = args.measurement_root / f"{self_id}-queue"
    state = json.loads((queue_root / "queue_state.json").read_text())
    if state.get("status") != "completed":
        raise RuntimeError("self-power queue did not complete")
    phases = state["phases"]
    by_label = {phase["label"]: phase for phase in phases}
    analysis_root = args.measurement_root / "analysis" / f"{self_id}-analysis"
    config: dict[str, Any] = {
        "format": "T510_STAGE35_S2_ANALYSIS_CONFIG_V1",
        "schema_version": 1,
        "queue_id": self_id,
        "queue_root": str(queue_root),
        "queue_manifest_sha256": base.sha256_file(queue_root / "queue_manifest.json"),
        "output_root": str(analysis_root),
        "center_hz": args.center_mhz * 1e6,
        "channel_width_hz": 78125.0,
        "enbw_hz": 70879.578125,
        "native_bucket_s": .01,
        "integration_seconds": [2.0, 4.0, 15.0, 30.0],
        "allan_seconds": [.01, .02, .05, .1, .2, .5, 1.0, 2.0, 4.0, 8.0, 15.0, 30.0],
        "acf_lag_seconds": [0.0, .01, .02, .03, .04, .05, .06, .07, .08, .09,
                            .1, .11, .12, .13, .14, .15, .16, .17, .18, .19,
                            .2, .5, 1.0, 2.0, 4.0, 8.0, 15.0],
        "bootstrap_replicates": 128,
        "bootstrap_seed": 3507,
        "psd": {"sample_rate_hz": 100.0, "nperseg": 2048, "noverlap": 1024,
                "window": "hann", "variants": ["raw", "constant_removed", "temperature_regressed"]},
        "temperature_predictor": "pl_temp",
        "parallel_workers": 2,
        "scans": [],
        "time_controls": [],
    }
    for scan, index in (("A", 1), ("B", 4), ("C", 7)):
        phase = phases[index]
        config["scans"].append({
            "label": scan,
            "phase_index": index,
            "path": str(args.measurement_root / phase["scan_id"]),
            "manifest_sha256": phase["manifest"]["sha256"],
            "telemetry": str(queue_root / "evidence" / f"phase_{index:02d}_telemetry.json"),
        })
    for scan in "abc":
        for position in ("pre", "post"):
            phase = by_label[f"{scan}-time-{position}"]
            config["time_controls"].append({
                "label": f"{scan.upper()}-{position}",
                "path": str(args.measurement_root / phase["scan_id"]),
                "manifest_sha256": phase["manifest"]["sha256"],
            })
    base.write_json_new(output, config)
    return analysis_root


def make_report_config(
    args: argparse.Namespace, analysis_config: Path, analysis_root: Path, output: Path
) -> None:
    config = json.loads(args.report_template.read_text(encoding="utf-8"))
    analysis = json.loads(analysis_config.read_text(encoding="utf-8"))
    config["analysis_root"] = str(analysis_root)
    config["analysis_manifest_sha256"] = base.sha256_file(analysis_root / "analysis_manifest.json")
    config["queue_manifest_sha256"] = analysis["queue_manifest_sha256"]
    center_hz = args.center_mhz * 1e6
    config["frequency_axis"] = {
        "center_hz": center_hz,
        "channel_width_hz": 78125.0,
        "order": "ascending_rf_hz",
        "first_global_bin": 2048,
        "last_global_bin": 2047,
        "rf_min_hz": center_hz - 160e6,
        "rf_max_hz": center_hz + 159921875.0,
        "landmarks": [
            {"label": "baseband DC", "rf_hz": center_hz, "global_bin": 0},
            {"label": "digital sentinel", "rf_hz": center_hz - 60e6, "global_bin": 3328},
        ],
    }
    config["time_histograms"] = []
    for control in analysis["time_controls"]:
        path = Path(control["path"]) / "histogram.csv"
        config["time_histograms"].append({
            "label": control["label"], "path": str(path), "sha256": base.sha256_file(path)
        })
    base.write_json_new(output, config)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--center-mhz", type=float, required=True)
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--report-template", type=Path, required=True)
    parser.add_argument("--helper-dir", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--measurement-root", type=Path, default=Path("/var/lib/t510/stage35"))
    parser.add_argument("--agent-base", default="http://192.168.100.117:8010")
    parser.add_argument("--receiver-base", default="http://127.0.0.1:8089")
    parser.add_argument("--sidecar", type=Path, required=True)
    parser.add_argument("--replay-evidence", type=Path, required=True)
    parser.add_argument("--preflight-pcap", type=Path, required=True)
    parser.add_argument("--chrome", type=Path, required=True)
    parser.add_argument("--chromedriver", type=Path, required=True)
    parser.add_argument("--app-root", type=Path, required=True)
    parser.add_argument("--lock", type=Path, default=Path("/run/lock/t510-stage35-retune.lock"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not 160.0 <= args.center_mhz <= 6000.0:
        raise RuntimeError("center-mhz must be within 160..6000")
    if any(byte not in b"abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_."
           for byte in args.campaign_id.encode("ascii", errors="strict")):
        raise RuntimeError("campaign-id contains unsupported characters")
    args.lock.parent.mkdir(parents=True, exist_ok=True)
    with args.lock.open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        root = args.measurement_root / "control" / args.campaign_id
        root.mkdir(parents=True, exist_ok=False)
        state_path = root / "retune_state.json"
        state = {
            "format": FORMAT, "campaign_id": args.campaign_id, "center_mhz": args.center_mhz,
            "rf_min_mhz": args.center_mhz - 160.0,
            "rf_max_mhz": args.center_mhz + 159.921875,
            "status": "running", "current_step": "self_power_capture",
            "started_unix_ms": base.unix_ms(), "finished_unix_ms": None, "error": None,
            "pipeline": ["self_power_A_B_C", "self_power_analysis", "xcorr_smoke",
                         "xcorr_A_B_C", "numeric_verify", "explorer_build",
                         "browser_verify", "atomic_8035_cutover"],
        }
        base.write_json_atomic(state_path, state)
        try:
            self_id = args.campaign_id + "-self"
            common = ["--template", str(args.template), "--helper-dir", str(args.helper_dir),
                      "--measurement-root", str(args.measurement_root), "--agent-base", args.agent_base,
                      "--receiver-base", args.receiver_base, "--center-mhz", str(args.center_mhz)]
            run_logged(root, "self_power_queue", [str(args.python),
                str(args.helper_dir / "t510_stage35_s2_queue.py"), "--queue-id", self_id,
                *common], 6 * 3600)
            state["current_step"] = "self_power_analysis"; base.write_json_atomic(state_path, state)
            analysis_config = root / "analysis_config.json"
            analysis_root = make_analysis_config(args, self_id, analysis_config)
            run_logged(root, "self_power_analysis", [str(args.python),
                str(args.helper_dir / "t510_stage35_s2_analyze.py"), "queue", "--config",
                str(analysis_config)], 6 * 3600)
            report_config = root / "report_config.json"
            make_report_config(args, analysis_config, analysis_root, report_config)
            analysis = json.loads(analysis_config.read_text())
            state["current_step"] = "xcorr_and_explorer"; base.write_json_atomic(state_path, state)
            command = [str(args.python), str(args.helper_dir / "t510_stage35_xcorr_explorer_queue.py"),
                "--queue-id", args.campaign_id + "-xcorr", *common,
                "--sidecar", str(args.sidecar), "--replay-evidence", str(args.replay_evidence),
                "--preflight-pcap", str(args.preflight_pcap), "--analysis-root", str(analysis_root),
                "--report-config", str(report_config), "--chrome", str(args.chrome),
                "--chromedriver", str(args.chromedriver), "--app-root", str(args.app_root)]
            for scan in analysis["scans"]:
                command += ["--spec-scan", scan["label"], scan["path"]]
            run_logged(root, "xcorr_explorer_queue", command, 8 * 3600)
            state.update({"status": "completed", "current_step": None,
                          "finished_unix_ms": base.unix_ms(),
                          "analysis_root": str(analysis_root),
                          "url": "http://192.168.100.162:8035/"})
            base.write_json_atomic(state_path, state)
            return 0
        except Exception as error:
            state.update({"status": "failed", "finished_unix_ms": base.unix_ms(),
                          "error": {"message": f"{type(error).__name__}: {error}",
                                    "traceback": traceback.format_exc()}})
            base.write_json_atomic(state_path, state)
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
