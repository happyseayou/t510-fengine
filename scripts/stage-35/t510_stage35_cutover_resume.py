#!/usr/bin/env python3
"""Finish a verified Stage 35 explorer cutover without rerunning science work."""

from __future__ import annotations

import argparse
import fcntl
import json
import traceback
from pathlib import Path

import t510_stage35_s2_queue as base
from t510_stage35_xcorr_explorer_queue import Queue


EXPECTED_ERROR = "RuntimeError: 8035 cutover failed and rollback was attempted:"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--queue-id", required=True)
    parser.add_argument("--resume-tag", required=True)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--helper-dir", type=Path, required=True)
    parser.add_argument("--sidecar", type=Path, required=True)
    parser.add_argument("--replay-evidence", type=Path, required=True)
    parser.add_argument("--preflight-pcap", type=Path, required=True)
    parser.add_argument("--analysis-root", type=Path, required=True)
    parser.add_argument("--report-config", type=Path, required=True)
    parser.add_argument("--chrome", type=Path, required=True)
    parser.add_argument("--chromedriver", type=Path, required=True)
    parser.add_argument("--spec-scan", action="append", nargs=2, required=True)
    parser.add_argument("--measurement-root", type=Path, default=Path("/var/lib/t510/stage35"))
    parser.add_argument("--agent-base", default="http://192.168.100.117:8010")
    parser.add_argument("--receiver-base", default="http://127.0.0.1:8089")
    parser.add_argument(
        "--explorer-root", type=Path, default=Path("/var/lib/t510/stage35/explorer")
    )
    parser.add_argument(
        "--app-root", type=Path, default=Path("/opt/t510-stage35-explorer/current")
    )
    parser.add_argument(
        "--lock", type=Path, default=Path("/run/lock/t510-stage35-xcorr-explorer.lock")
    )
    parser.add_argument("--minimum-free-bytes", type=int, default=250_000_000_000)
    parser.add_argument("--center-mhz", type=float, required=True)
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    args.spec_scans = {scan: path for scan, path in args.spec_scan}
    args.release_id = args.release.name
    args.recovery_spec_pcaps = {}
    return args


def validate_manifest(runner: Queue, phase: dict) -> None:
    path = runner.args.measurement_root / phase["scan_id"] / "dataset_manifest.json"
    expected = str((phase.get("manifest") or {}).get("sha256", ""))
    if not path.is_file() or not expected or base.sha256_file(path) != expected:
        raise RuntimeError(f"sealed phase manifest identity changed: {path}")
    if json.loads(path.read_text()).get("complete") is not True:
        raise RuntimeError(f"sealed phase is not complete: {path}")


def strict_preflight(runner: Queue, release: Path) -> None:
    state = runner.state
    message = str((state.get("error") or {}).get("message", ""))
    phases = state.get("phases", [])
    if state.get("status") != "failed" or not message.startswith(EXPECTED_ERROR):
        raise RuntimeError(f"queue is not at the registered cutover-only failure: {message}")
    if len(phases) != 9 or [phase.get("status") for phase in phases[:8]] != [
        "completed"
    ] * 8:
        raise RuntimeError("the scientific prefix through C XCORR is not sealed")
    phase8 = phases[8]
    if (
        phase8.get("status") != "failed"
        or not phase8.get("formal_integrity", {}).get("ok")
        or not phase8.get("manifest")
    ):
        raise RuntimeError("C TIME-post did not finish before the cutover failure")
    for phase in phases:
        validate_manifest(runner, phase)
    if not release.is_dir():
        raise RuntimeError(f"verified explorer release is missing: {release}")
    browser = release / "browser_verification.json"
    browser_result = json.loads(browser.read_text()) if browser.is_file() else {}
    if browser_result.get("status") != "PASS" or browser_result.get("errors"):
        raise RuntimeError("browser verification evidence is missing or failed")
    for name in ("raw_index_process.json", "explorer_analysis_process.json", "browser_verify_process.json"):
        evidence = runner.evidence / name
        if not evidence.is_file() or json.loads(evidence.read_text()).get("returncode") != 0:
            raise RuntimeError(f"successful process evidence is missing: {evidence}")
    board, receiver = runner.board(), runner.receiver()
    if board.get("streaming") or float(receiver.get("stats", {}).get("packets_per_sec", 0) or 0):
        raise RuntimeError("cutover recovery requires a stopped and quiescent stream")
    runner.event("cutover_recovery_preflight_pass", release=str(release))


def main() -> int:
    args = parse_args()
    args.lock.parent.mkdir(parents=True, exist_ok=True)
    with args.lock.open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        runner = Queue(args, json.loads(args.template.read_text()))
        runner.state = json.loads(runner.state_path.read_text())
        runner.phases = runner.state["phases"]
        try:
            strict_preflight(runner, args.release)
            if args.preflight_only:
                return 0
            runner.state.update({"status": "running", "error": None, "current_phase_index": None})
            runner.save()
            runner.event("cutover_recovery_started", resume_tag=args.resume_tag)
            runner.cutover(args.release)
            errors = runner.safe_finalize(failed=False)
            if errors:
                raise RuntimeError(f"cutover recovery safe finalization failed: {errors}")
            phase8 = runner.phases[8]
            phase8["status"] = "completed"
            phase8.pop("error", None)
            recoveries = runner.state.get("time_post_recoveries", [])
            if recoveries and recoveries[-1].get("resume_tag") == "time-retry2":
                recoveries[-1].update(
                    {
                        "status": "completed",
                        "finished_unix_ms": base.unix_ms(),
                        "cutover_resume_tag": args.resume_tag,
                    }
                )
                recoveries[-1].pop("error", None)
            runner.state.update(
                {
                    "status": "completed",
                    "error": None,
                    "current_phase_index": None,
                    "finished_unix_ms": base.unix_ms(),
                    "explorer_release": str(args.release),
                    "url": "http://192.168.100.162:8035/",
                }
            )
            runner.save()
            runner.event("queue_complete_after_cutover_recovery", resume_tag=args.resume_tag)
            runner.final_manifest()
            return 0
        except Exception as error:
            errors = runner.safe_finalize(failed=True)
            runner.state.update(
                {
                    "status": "failed",
                    "finished_unix_ms": base.unix_ms(),
                    "error": {
                        "message": f"{type(error).__name__}: {error}",
                        "traceback": traceback.format_exc(),
                        "safe_finalize_errors": errors,
                    },
                }
            )
            runner.save()
            runner.event("cutover_recovery_failed", resume_tag=args.resume_tag, error=runner.state["error"])
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
