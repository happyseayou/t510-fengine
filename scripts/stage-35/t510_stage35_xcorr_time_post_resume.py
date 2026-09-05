#!/usr/bin/env python3
"""Resume Stage 35 after the completed C XCORR and failed C TIME-post control.

The sealed 900 s C cross-correlation product is reused without copying or
recapture. A short TIME-only coverage gate is run with the topology-aware
receiver, followed by a new C-post identity, independent verification, explorer
generation, and atomic port-8035 cutover.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import shutil
import traceback
from pathlib import Path

import t510_stage35_s2_queue as base
from t510_stage35_xcorr_explorer_queue import Queue


EXPECTED_TIME_ERROR = (
    "RuntimeError: c-time-post capture failed: "
    "one or more 10 ms TIME buckets have incomplete sample coverage"
)


def is_registered_time_smoke_failure(state: dict) -> bool:
    message = str((state.get("error") or {}).get("message", ""))
    recoveries = state.get("time_post_recoveries", [])
    return bool(
        recoveries
        and message.startswith("RuntimeError: time-coverage-recovery-smoke-")
        and message.endswith("capture failed: one or more 10 ms TIME buckets have incomplete sample coverage")
        and recoveries[-1].get("status") == "failed"
        and recoveries[-1].get("error") == message
    )


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
    args.release_id = f"{args.queue_id}-{args.resume_tag}"
    args.recovery_spec_pcaps = {}
    return args


def validate_manifest(runner: Queue, phase: dict) -> None:
    manifest_path = runner.args.measurement_root / phase["scan_id"] / "dataset_manifest.json"
    if not manifest_path.is_file():
        raise RuntimeError(f"sealed phase manifest is missing: {manifest_path}")
    expected = str((phase.get("manifest") or {}).get("sha256", ""))
    if not expected or base.sha256_file(manifest_path) != expected:
        raise RuntimeError(f"sealed phase manifest identity changed: {manifest_path}")
    if json.loads(manifest_path.read_text()).get("complete") is not True:
        raise RuntimeError(f"sealed phase is not complete: {manifest_path}")


def strict_preflight(runner: Queue) -> None:
    state = runner.state
    phases = state.get("phases", [])
    message = str((state.get("error") or {}).get("message", ""))
    smoke_failure = is_registered_time_smoke_failure(state)
    if state.get("status") != "failed" or not (message == EXPECTED_TIME_ERROR or smoke_failure):
        raise RuntimeError(f"queue is not at the registered C TIME-post failure: {message}")
    if len(phases) != 9 or [phase.get("status") for phase in phases[:8]] != [
        "completed"
    ] * 8:
        raise RuntimeError("A/B, C-pre, and the recovered C XCORR are not all sealed")
    if phases[8].get("status") not in ("running", "failed"):
        raise RuntimeError("C TIME-post is not the registered failed phase")
    if smoke_failure:
        latest = state["time_post_recoveries"][-1]
        if latest.get("failed_phase", {}).get("scan_id") != phases[8].get("scan_id"):
            raise RuntimeError("TIME smoke failure does not refer to the current phase 8")
        if not Path(str(latest.get("failed_phase_evidence", ""))).is_dir():
            raise RuntimeError("preserved phase 8 evidence from TIME smoke failure is missing")
    for phase in phases[:8]:
        validate_manifest(runner, phase)
    failed_root = runner.args.measurement_root / phases[8]["scan_id"]
    if not failed_root.is_dir() or (failed_root / "dataset_manifest.json").exists():
        raise RuntimeError("failed C TIME-post evidence was altered or promoted")
    if not (failed_root / "coverage_failure.json").is_file():
        raise RuntimeError("failed C TIME-post coverage ledger is missing")
    if shutil.disk_usage(runner.args.measurement_root).free < runner.args.minimum_free_bytes:
        raise RuntimeError("insufficient free space for TIME-post recovery and analysis")
    board, receiver = runner.board(), runner.receiver()
    if board.get("streaming") or float(receiver.get("stats", {}).get("packets_per_sec", 0) or 0):
        raise RuntimeError("recovery requires a stopped and quiescent stream")
    for endpoint in (
        "/api/measure/time/status",
        "/api/measure/crosscorrelation/status",
    ):
        status = runner.receiver(endpoint)
        if status.get("status") in ("armed", "running", "draining"):
            raise RuntimeError(f"receiver task is still active: {endpoint}={status.get('status')}")
    runner.event("time_post_recovery_preflight_pass", failed_dataset=str(failed_root))


def preserve_phase_evidence(runner: Queue, resume_tag: str) -> Path:
    destination = runner.evidence / f"failed-phase-08-{resume_tag}"
    paths = sorted(runner.evidence.glob("phase_08_*"))
    if not paths:
        recoveries = runner.state.get("time_post_recoveries", [])
        prior = Path(str(recoveries[-1].get("failed_phase_evidence", ""))) if recoveries else None
        if (
            prior is None
            or not prior.is_dir()
            or recoveries[-1].get("failed_phase", {}).get("scan_id")
            != runner.phases[8].get("scan_id")
        ):
            raise RuntimeError("failed phase 8 evidence is missing")
        return prior
    destination.mkdir(exist_ok=False)
    for path in paths:
        path.rename(destination / path.name)
    return destination


def time_smoke(runner: Queue, recovery: dict, resume_tag: str, index: int) -> dict:
    phase = {
        "index": index,
        "label": f"time-coverage-recovery-smoke-{resume_tag}",
        "scan": "RECOVERY-TIME",
        "position": "smoke",
        "kind": "time",
        "mode": "time_only",
        "duration_seconds": 10,
        "scan_id": f"{runner.args.queue_id}-time-{resume_tag}-smoke-10s",
        "raw_stem": f"time-{resume_tag}-smoke",
        "status": "pending",
    }
    recovery["smoke"] = phase
    runner.save()
    runner.run_phase(phase)
    if phase.get("status") != "completed":
        raise RuntimeError("TIME recovery smoke did not complete")
    if not phase.get("formal_integrity", {}).get("ok"):
        raise RuntimeError(f"TIME recovery smoke integrity failed: {phase.get('formal_integrity')}")
    runner.event("time_post_recovery_smoke_pass", scan_id=phase["scan_id"])
    return phase


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
        recovery = None
        try:
            strict_preflight(runner)
            if args.preflight_only:
                return 0
            old_phase = dict(runner.phases[8])
            evidence_root = preserve_phase_evidence(runner, args.resume_tag)
            recovery_index = len(runner.state.get("time_post_recoveries", []))
            recovery = {
                "resume_tag": args.resume_tag,
                "status": "running",
                "started_unix_ms": base.unix_ms(),
                "prior_error": runner.state["error"],
                "failed_phase": old_phase,
                "failed_phase_evidence": str(evidence_root),
                "smoke_evidence_index": 200 + recovery_index,
            }
            runner.state.setdefault("time_post_recoveries", []).append(recovery)
            runner.state.update(
                {
                    "status": "running",
                    "error": None,
                    "current_phase_index": None,
                    "finished_unix_ms": None,
                }
            )
            runner.save()
            runner.event("time_post_recovery_started", resume_tag=args.resume_tag)
            time_smoke(runner, recovery, args.resume_tag, 200 + recovery_index)
            failed_attempts = list(old_phase.get("failed_attempts", []))
            failed_attempts.append(
                {key: value for key, value in old_phase.items() if key != "failed_attempts"}
            )
            retry = {
                "index": 8,
                "label": "c-time-post",
                "scan": "C",
                "position": "post",
                "kind": "time",
                "mode": "time_only",
                "duration_seconds": 30,
                "scan_id": f"{args.queue_id}-c-time-post-{args.resume_tag}-30s",
                "raw_stem": f"c-post-{args.resume_tag}",
                "status": "pending",
                "failed_attempts": failed_attempts,
            }
            runner.phases[8] = retry
            runner.state["phases"] = runner.phases
            runner.save()
            runner.run_phase(retry)
            runner.independent_verify()
            release = runner.build_explorer()
            runner.cutover(release)
            errors = runner.safe_finalize(failed=False)
            if errors:
                raise RuntimeError(f"TIME-post recovery safe finalization failed: {errors}")
            recovery.update({"status": "completed", "finished_unix_ms": base.unix_ms()})
            runner.state.update(
                {
                    "status": "completed",
                    "error": None,
                    "current_phase_index": None,
                    "finished_unix_ms": base.unix_ms(),
                    "explorer_release": str(release),
                    "url": "http://192.168.100.162:8035/",
                }
            )
            runner.save()
            runner.event("queue_complete_after_time_post_recovery", resume_tag=args.resume_tag)
            runner.final_manifest()
            return 0
        except Exception as error:
            errors = runner.safe_finalize(failed=True)
            if runner.state.get("current_phase_index") == 8:
                runner.phases[8]["status"] = "failed"
                runner.phases[8]["error"] = f"{type(error).__name__}: {error}"
            if recovery is not None:
                recovery.update(
                    {
                        "status": "failed",
                        "finished_unix_ms": base.unix_ms(),
                        "error": f"{type(error).__name__}: {error}",
                    }
                )
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
            runner.event(
                "time_post_recovery_failed", resume_tag=args.resume_tag, error=runner.state["error"]
            )
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
