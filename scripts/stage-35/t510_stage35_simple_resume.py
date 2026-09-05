#!/usr/bin/env python3
"""Resume Stage 35 simple browser verification and atomic cutover without recapture."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import subprocess
import time
import traceback
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import t510_stage35_s2_queue as base
from t510_stage35_simple_queue import Queue


EXPECTED_FAILURE = "browser verification failed"


def process_evidence(command: list[str], timeout: int) -> dict[str, Any]:
    started = base.unix_ms()
    completed = subprocess.run(
        command, text=True, capture_output=True, timeout=timeout, check=False
    )
    return {
        "argv": command,
        "started_unix_ms": started,
        "finished_unix_ms": base.unix_ms(),
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def validate_sealed_input(runner: Queue, release: Path, expected_detail: str) -> None:
    state = runner.state
    message = str((state.get("error") or {}).get("message", ""))
    if (state.get("status") != "failed" or EXPECTED_FAILURE not in message.lower() or
            expected_detail not in message):
        raise RuntimeError(f"queue is not at the registered browser-only failure: {message}")
    if len(runner.phases) != 3 or any(row.get("status") != "completed" for row in runner.phases):
        raise RuntimeError("the smoke, raw-spectrum, and formal acquisitions are not all sealed")
    for phase in (runner.phases[0], runner.phases[2]):
        identity = phase.get("manifest") or {}
        manifest = Path(str(identity.get("path", "")))
        if (not manifest.is_file() or not identity.get("sha256") or
                base.sha256_file(manifest) != identity["sha256"]):
            raise RuntimeError(f"sealed dataset manifest identity changed: {manifest}")
        if json.loads(manifest.read_text(encoding="utf-8")).get("complete") is not True:
            raise RuntimeError(f"sealed dataset is not complete: {manifest}")
    raw = runner.phases[1].get("pcap") or {}
    raw_path = Path(str(raw.get("path", "")))
    if (not raw_path.is_file() or base.sha256_file(raw_path) != raw.get("sha256")):
        raise RuntimeError("the sealed 4096-spectrum PCAP identity changed")
    if not release.is_dir():
        raise RuntimeError(f"candidate release is missing: {release}")
    raw_manifest = release / "raw" / "simple_raw_index_manifest.json"
    raw_index = json.loads(raw_manifest.read_text(encoding="utf-8"))
    if set(raw_index.get("spec", {})) != {"simple-4096"}:
        raise RuntimeError("candidate raw index does not contain exactly simple-4096")
    failed_browser = json.loads((release / "browser_verification.json").read_text(encoding="utf-8"))
    if (failed_browser.get("status") != "FAIL" or
            expected_detail not in " ".join(failed_browser.get("errors", []))):
        raise RuntimeError("initial browser failure evidence no longer matches the registered fault")
    board, receiver = runner.board(), runner.receiver()
    cross = runner.receiver("/api/measure/crosscorrelation/status")
    if board.get("streaming") or float(receiver.get("stats", {}).get("packets_per_sec", 0) or 0):
        raise RuntimeError("browser-only recovery requires the board stream to remain stopped")
    if cross.get("status") in ("armed", "running", "draining"):
        raise RuntimeError("browser-only recovery found an active cross-correlation task")


def make_runner(args: argparse.Namespace) -> Queue:
    runner = object.__new__(Queue)
    runner.args = SimpleNamespace(
        queue_id=args.queue_id,
        measurement_root=args.measurement_root,
        explorer_root=args.explorer_root,
        app_root=args.app_root,
        agent_base=args.agent_base,
        receiver_base=args.receiver_base,
    )
    runner.template = {}
    runner.root = args.measurement_root / f"{args.queue_id}-queue"
    runner.state_path = runner.root / "queue_state.json"
    runner.events_path = runner.root / "queue_events.jsonl"
    runner.evidence = runner.root / "evidence"
    runner.raw = runner.root / "raw"
    runner.state = json.loads(runner.state_path.read_text(encoding="utf-8"))
    runner.phases = runner.state["phases"]
    runner.telemetry_since_seq = 0
    runner.telemetry_epoch_id = None
    return runner


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue-id", required=True)
    parser.add_argument("--resume-tag", required=True)
    parser.add_argument("--prior-tag", required=True)
    parser.add_argument("--expected-detail", required=True)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--browser-verify", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--chrome", type=Path, required=True)
    parser.add_argument("--chromedriver", type=Path, required=True)
    parser.add_argument("--measurement-root", type=Path, default=Path("/var/lib/t510/stage35"))
    parser.add_argument("--explorer-root", type=Path,
                        default=Path("/var/lib/t510/stage35/explorer"))
    parser.add_argument("--app-root", type=Path,
                        default=Path("/opt/t510-stage35-explorer/candidate"))
    parser.add_argument("--agent-base", default="http://192.168.100.117:8010")
    parser.add_argument("--receiver-base", default="http://127.0.0.1:8089")
    parser.add_argument("--lock", type=Path,
                        default=Path("/run/lock/t510-stage35-simple.lock"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.lock.parent.mkdir(parents=True, exist_ok=True)
    with args.lock.open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        runner = make_runner(args)
        try:
            validate_sealed_input(runner, args.release, args.expected_detail)
            original = args.release / "browser_verification.json"
            retained = args.release / f"browser_verification.{args.prior_tag}-failure.json"
            if retained.exists():
                raise RuntimeError(f"refusing existing retained failure evidence: {retained}")
            os.replace(original, retained)
            runner.state.update(status="running", error=None, current_phase_index=None)
            runner.save()
            runner.event("simple_browser_recovery_started", resume_tag=args.resume_tag)
            command = [
                str(args.python), str(args.browser_verify), "--python", str(args.python),
                "--server", str(args.app_root / "t510_stage35_explorer.py"),
                "--config", str(args.release / "app_config.json"),
                "--helper-dir", str(args.app_root / "helpers"),
                "--static-root", str(args.app_root / "static"),
                "--chrome", str(args.chrome), "--chromedriver", str(args.chromedriver),
                "--output", str(original),
                "--screenshot", str(args.release / "browser_smoke.png"),
            ]
            process = process_evidence(command, 3600)
            base.write_json_new(
                runner.evidence / f"simple_browser_verify_{args.resume_tag}_process.json", process
            )
            if process["returncode"]:
                raise RuntimeError(
                    "resumed browser verification failed: " +
                    str(process["stderr"] or process["stdout"])
                )
            browser = json.loads(original.read_text(encoding="utf-8"))
            if browser.get("status") != "PASS" or browser.get("errors"):
                raise RuntimeError("resumed browser evidence is not PASS")
            base.write_json_new(args.release / "stage_status.json", {
                "stage35_step8": "INTERACTIVE_SIMPLE_REPORT_BROWSER_VERIFIED",
                "stage35_step12": "INDEPENDENT_50OHM_FULLBAND_100MS_BASELINE_COMPLETE",
                "stage35_step12_overall": "IN_PROGRESS",
                "not_claimed": [
                    "K", "Jy", "SEFD", "sky phase", "imaging capability", "physical root cause"
                ],
                "browser_recovery": args.resume_tag,
            })
            base.write_json_new(args.release / "application_code_identity.json", {
                "server": {"path": str(args.app_root / "t510_stage35_explorer.py"),
                           "sha256": base.sha256_file(args.app_root / "t510_stage35_explorer.py")},
                "javascript": {"path": str(args.app_root / "static" / "app.js"),
                               "sha256": base.sha256_file(args.app_root / "static" / "app.js")},
            })
            runner.cutover(args.release)
            safe_errors = runner.safe_finalize(failed=False)
            if safe_errors:
                raise RuntimeError(f"safe finalization failed: {safe_errors}")
            runner.state.update(
                status="completed", error=None, current_phase_index=None,
                finished_unix_ms=base.unix_ms(), explorer_release=str(args.release),
                url="http://192.168.100.162:8035/",
            )
            runner.save()
            runner.event("queue_complete_after_simple_browser_recovery",
                         resume_tag=args.resume_tag)
            runner.final_manifest()
            return 0
        except Exception as error:
            safe_errors = runner.safe_finalize(failed=True)
            runner.state.update(status="failed", finished_unix_ms=base.unix_ms(), error={
                "message": f"{type(error).__name__}: {error}",
                "traceback": traceback.format_exc(),
                "safe_finalize_errors": safe_errors,
            })
            runner.save()
            runner.event("simple_browser_recovery_failed", resume_tag=args.resume_tag,
                         error=runner.state["error"])
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
