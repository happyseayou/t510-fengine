#!/usr/bin/env python3
"""Resume Stage 35 XCORR post-processing after the raw SPEC alignment fix.

This never re-runs the sealed 900 s integrations.  It captures explicitly
labelled supplemental short SPEC witnesses, reuses the already-passing numeric
verification, and continues analysis/application/cutover/archive fail-closed.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import subprocess
import time
import traceback
from pathlib import Path
from typing import Any

import t510_stage35_s2_queue as base
from t510_stage35_explorer_prepare import inspect_spec_pcap
from t510_stage35_xcorr_explorer_queue import Queue


EXPECTED_FAILURE = "has no sample0 shared by all sixteen blocks"
SUPPLEMENTAL_LABELS = tuple(
    f"{scan}-recovery-{position}"
    for scan in ("A", "B", "C")
    for position in ("begin", "end")
)


def service_state(unit: str) -> str:
    return subprocess.run(
        ["systemctl", "is-active", unit], capture_output=True, text=True, check=False
    ).stdout.strip()


def recovery_preflight(runner: Queue) -> None:
    state = runner.state
    message = str((state.get("error") or {}).get("message", ""))
    if state.get("status") != "failed" or EXPECTED_FAILURE not in message:
        raise RuntimeError(f"queue is not at the registered recoverable failure: {message}")
    if state.get("smoke", {}).get("status") != "completed":
        raise RuntimeError("the original 60 s smoke did not complete")
    if len(state.get("phases", [])) != 9 or any(
        phase.get("status") != "completed" for phase in state["phases"]
    ):
        raise RuntimeError("the original nine formal phases are not all sealed")
    numeric = json.loads((runner.evidence / "xcorr_numeric_verification.json").read_text())
    if numeric.get("status") != "PASS" or int(numeric.get("scan_count", 0)) != 3:
        raise RuntimeError("the original three-scan numeric verification is not PASS")
    board = runner.board()
    receiver = runner.receiver()
    errors: list[str] = []
    if board.get("streaming"):
        errors.append("board is streaming")
    if float(receiver.get("stats", {}).get("packets_per_sec", 0.0) or 0.0):
        errors.append("receiver reports live traffic")
    for path in (
        "/api/measure/autocorrelation/status",
        "/api/measure/time/status",
        "/api/measure/spec-stability/status",
        "/api/measure/crosscorrelation/status",
    ):
        status = runner.receiver(path).get("status")
        if status in ("armed", "running", "draining"):
            errors.append(f"active task {path}={status}")
    if service_state("t510-stage35-s2-report-v2-human-http-20260901.service") != "active":
        errors.append("old 8035 static report is not active")
    if service_state("t510-stage35-explorer.service") == "active":
        errors.append("new explorer is unexpectedly active before recovery")
    if errors:
        raise RuntimeError(f"recovery preflight failed: {errors}")
    runner.event("recovery_preflight_pass", numeric_sha256=base.sha256_file(
        runner.evidence / "xcorr_numeric_verification.json"))


def capture_supplemental_witnesses(runner: Queue) -> dict[str, Path]:
    output = runner.raw / f"supplemental-spec-{runner.args.resume_tag}"
    output.mkdir(parents=True, exist_ok=False)
    phase = {
        "index": 98, "label": "supplemental-spec-witness", "scan": "RECOVERY",
        "position": "supplemental", "kind": "xcorr", "mode": "spec_only",
        "duration_seconds": 0, "scan_id": "supplemental-only", "status": "running",
    }
    runner.ensure_mode(phase)
    runner.start_stream(phase)
    records: dict[str, Any] = {}
    paths: dict[str, Path] = {}
    try:
        for label in SUPPLEMENTAL_LABELS:
            destination = output / f"{label}.pcap"
            before_board, before_receiver = runner.board(), runner.receiver()
            identity = base.http_to_new_file(
                runner.args.receiver_base.rstrip("/") + "/api/capture/spec-pcap",
                destination,
                body={"packets_per_block": 256, "include_time": False, "time_only": False},
                timeout=60,
            )
            after_receiver, after_board = runner.receiver(), runner.board()
            integrity = base.formal_integrity(
                before_board, after_board, before_receiver, after_receiver
            )
            if not integrity["ok"]:
                raise RuntimeError(f"{label} supplemental integrity failed: {integrity['errors']}")
            inspected = inspect_spec_pcap(destination)
            shared = inspected.pop("_shared_sample0_values")
            if len(shared) != 256 or not inspected["shared_sample0_continuous"]:
                raise RuntimeError(f"{label} did not capture 256 common continuous spectra: {inspected}")
            verified = base.verify_spec_pcap(destination)
            records[label] = {
                "identity": identity, "inspection": inspected, "verified": verified,
                "receiver_integrity": integrity,
                "temporal_relationship": (
                    "supplemental after original queue failure; unchanged independent-50ohm/TCXO "
                    "configuration, not simultaneous with sealed A/B/C integrations"
                ),
            }
            paths[label] = destination
            runner.event("supplemental_spec_witness_pass", label=label,
                         sha256=inspected["source_sha256"])
    finally:
        runner.stop_board(f"supplemental_spec_{runner.args.resume_tag}_stop.json")
    base.write_json_new(
        runner.evidence / f"supplemental_spec_witnesses_{runner.args.resume_tag}.json",
        {"status": "PASS", "records": records},
    )
    return paths


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--queue-id", required=True)
    parser.add_argument("--resume-tag", required=True)
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
    parser.add_argument("--explorer-root", type=Path,
                        default=Path("/var/lib/t510/stage35/explorer"))
    parser.add_argument("--app-root", type=Path,
                        default=Path("/opt/t510-stage35-explorer/current"))
    parser.add_argument("--lock", type=Path,
                        default=Path("/run/lock/t510-stage35-xcorr-explorer.lock"))
    parser.add_argument("--minimum-free-bytes", type=int, default=250_000_000_000)
    args = parser.parse_args()
    args.spec_scans = {scan: path for scan, path in args.spec_scan}
    args.release_id = f"{args.queue_id}-{args.resume_tag}"
    args.recovery_spec_pcaps = {}
    return args


def main() -> int:
    args = parse_args()
    args.lock.parent.mkdir(parents=True, exist_ok=True)
    with args.lock.open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        runner = Queue(args, json.loads(args.template.read_text()))
        if not runner.root.is_dir():
            raise RuntimeError(f"original queue root is missing: {runner.root}")
        runner.state = json.loads(runner.state_path.read_text())
        runner.phases = runner.state["phases"]
        try:
            recovery_preflight(runner)
            prior_error = runner.state["error"]
            recovery = {
                "resume_tag": args.resume_tag, "started_unix_ms": base.unix_ms(),
                "prior_error": prior_error, "status": "running",
            }
            runner.state.setdefault("recoveries", []).append(recovery)
            runner.state.update({"status": "running", "error": None,
                                 "current_phase_index": None})
            runner.save(); runner.event("recovery_resume_started", resume_tag=args.resume_tag)
            args.recovery_spec_pcaps = capture_supplemental_witnesses(runner)
            runner.independent_verify()
            release = runner.build_explorer()
            runner.cutover(release)
            errors = runner.safe_finalize(failed=False)
            if errors:
                raise RuntimeError(f"recovery safe finalization failed: {errors}")
            recovery.update({"status": "completed", "finished_unix_ms": base.unix_ms(),
                             "supplemental_spec_pcaps": {
                                 key: str(value) for key, value in args.recovery_spec_pcaps.items()
                             }})
            runner.state.update({
                "status": "completed", "error": None, "current_phase_index": None,
                "finished_unix_ms": base.unix_ms(), "explorer_release": str(release),
                "url": "http://192.168.100.162:8035/",
            })
            runner.save(); runner.event("queue_complete_after_recovery",
                                        resume_tag=args.resume_tag)
            runner.final_manifest()
            return 0
        except Exception as error:
            errors = runner.safe_finalize(failed=True)
            if runner.state.get("recoveries"):
                runner.state["recoveries"][-1].update({
                    "status": "failed", "finished_unix_ms": base.unix_ms(),
                    "error": f"{type(error).__name__}: {error}",
                })
            runner.state.update({
                "status": "failed", "finished_unix_ms": base.unix_ms(),
                "error": {"message": f"{type(error).__name__}: {error}",
                          "traceback": traceback.format_exc(),
                          "safe_finalize_errors": errors},
            })
            runner.save(); runner.event("recovery_resume_failed", resume_tag=args.resume_tag,
                                        error=runner.state["error"])
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
