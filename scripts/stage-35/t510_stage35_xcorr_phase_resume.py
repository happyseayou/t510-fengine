#!/usr/bin/env python3
"""Resume Stage 35 XCORR after the registered C shared-ring overflow.

The failed partial C dataset and its evidence remain preserved. This runner
executes a new 60 s full-band CUDA gate, records C under a new scan identity,
captures C-post, and completes verification, application generation, and the
atomic 8035 cutover. Sealed A/B products are never rerun.
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


EXPECTED_ERROR_PREFIX = "CUDA cross-correlation ring "
EXPECTED_ERROR_INFIX = " is full at "


def is_registered_ring_failure(message: str) -> bool:
    return (EXPECTED_ERROR_PREFIX in message and EXPECTED_ERROR_INFIX in message
            and message.rstrip().endswith(" packets"))


def is_registered_setup_failure(state: dict) -> bool:
    """Accept only the known pre-capture evidence-name collision.

    The failed retry had already preserved phase-07 evidence, then stopped while
    creating the recovery-smoke receiver-config evidence.  No acquisition was
    armed, so the scientifically failed phase is still the phase-07 retry stored
    in the queue and in the latest recovery record.
    """
    message = str((state.get("error") or {}).get("message", ""))
    recoveries = state.get("recoveries", [])
    if not recoveries:
        return False
    latest = recoveries[-1]
    return (
        message.startswith("FileExistsError: [Errno 17] File exists:")
        and "/evidence/phase_97_receiver_config.json" in message
        and latest.get("status") == "failed"
        and latest.get("error") == message
        and is_registered_ring_failure(
            str((latest.get("prior_error") or {}).get("message", ""))
        )
    )


def latest_recovery_preserved_current_phase(state: dict) -> bool:
    """Whether the last retry stopped before replacing phase 7.

    Setup and recovery-smoke failures occur after the old phase-07 evidence is
    moved but before a new C phase is installed. Reusing that recorded evidence
    directory is safe only when the recorded failed scan identity still equals
    the queue's current phase-07 identity.
    """
    phases = state.get("phases", [])
    recoveries = state.get("recoveries", [])
    if len(phases) <= 7 or not recoveries:
        return False
    latest = recoveries[-1]
    evidence_root = Path(str(latest.get("failed_phase_evidence", "")))
    return (
        latest.get("status") == "failed"
        and latest.get("failed_phase", {}).get("scan_id") == phases[7].get("scan_id")
        and evidence_root.is_dir()
        and state.get("current_phase_index") != 7
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
    parser.add_argument("--explorer-root", type=Path,
                        default=Path("/var/lib/t510/stage35/explorer"))
    parser.add_argument("--app-root", type=Path,
                        default=Path("/opt/t510-stage35-explorer/current"))
    parser.add_argument("--lock", type=Path,
                        default=Path("/run/lock/t510-stage35-xcorr-explorer.lock"))
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
    message = str((state.get("error") or {}).get("message", ""))
    phases = state.get("phases", [])
    setup_failure = is_registered_setup_failure(state)
    if state.get("status") != "failed" or not (
        is_registered_ring_failure(message) or setup_failure
    ):
        raise RuntimeError(f"queue is not at the registered ring-overflow failure: {message}")
    if len(phases) != 9 or [phase.get("status") for phase in phases[:7]] != ["completed"] * 7:
        raise RuntimeError("the strict successful prefix A/B plus C-pre is not sealed")
    if phases[7].get("status") not in ("failed", "running"):
        raise RuntimeError("phase 7 is not the registered failed C integration")
    if setup_failure:
        latest = state["recoveries"][-1]
        if latest.get("failed_phase", {}).get("scan_id") != phases[7].get("scan_id"):
            raise RuntimeError("setup failure does not refer to the current failed phase 7")
        evidence_root = Path(str(latest.get("failed_phase_evidence", "")))
        if not evidence_root.is_dir():
            raise RuntimeError("preserved phase 7 evidence from setup failure is missing")
    if phases[8].get("status") != "pending":
        raise RuntimeError("C-post is not pending")
    if state.get("smoke", {}).get("status") != "completed":
        raise RuntimeError("the original 60 s CUDA smoke is not complete")
    for phase in phases[:7]:
        validate_manifest(runner, phase)
    failed_root = runner.args.measurement_root / phases[7]["scan_id"]
    if not failed_root.is_dir() or (failed_root / "dataset_manifest.json").exists():
        raise RuntimeError("failed C partial dataset was altered or promoted")
    if shutil.disk_usage(runner.args.measurement_root).free < runner.args.minimum_free_bytes:
        raise RuntimeError("insufficient free space for C recovery")
    board, receiver = runner.board(), runner.receiver()
    if board.get("streaming") or float(receiver.get("stats", {}).get("packets_per_sec", 0) or 0):
        raise RuntimeError("recovery requires a stopped and quiescent stream")
    cross = runner.receiver("/api/measure/crosscorrelation/status")
    if cross.get("status") in ("armed", "running", "draining"):
        raise RuntimeError(f"cross-correlation task is still active: {cross.get('status')}")
    runner.event("phase_recovery_preflight_pass", failed_dataset=str(failed_root))


def preserve_phase_evidence(runner: Queue, resume_tag: str) -> Path:
    destination = runner.evidence / f"failed-phase-07-{resume_tag}"
    paths = sorted(runner.evidence.glob("phase_07_*"))
    if not paths:
        # A prior recovery may have failed after preserving this evidence but
        # before starting any new capture. Reuse that immutable directory.
        recoveries = runner.state.get("recoveries", [])
        prior = Path(str(recoveries[-1].get("failed_phase_evidence", ""))) if recoveries else None
        if prior is None or not latest_recovery_preserved_current_phase(runner.state):
            raise RuntimeError("failed phase 7 evidence is missing")
        return prior
    destination.mkdir(exist_ok=False)
    for path in paths:
        path.rename(destination / path.name)
    return destination


def recovery_smoke(runner: Queue, recovery: dict, resume_tag: str,
                   evidence_index: int) -> dict:
    phase = {
        "index": evidence_index, "label": f"cuda-fullband-recovery-smoke-{resume_tag}",
        "scan": "RECOVERY-SMOKE", "position": "smoke", "kind": "xcorr",
        "mode": "spec_only", "duration_seconds": 60,
        "scan_id": f"{runner.args.queue_id}-cuda-xcorr-{resume_tag}-smoke-60s",
        "raw_stem": f"recovery-smoke-{resume_tag}", "status": "pending",
    }
    recovery["smoke"] = phase
    runner.save()
    runner.run_phase(phase)
    progress = phase["capture_status"]["progress"]
    expected = 60 * 78_125 * 16
    if progress.get("packets_published") != expected or progress.get("packets_consumed") != expected:
        raise RuntimeError(f"recovery smoke packet coverage mismatch: {progress}")
    if progress.get("ring_drops") != 0 or progress.get("completed_block_mask") != 0xffff:
        raise RuntimeError(f"recovery smoke ring gate failed: {progress}")
    runner.event("phase_recovery_smoke_pass", progress=progress)
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
            prior_error = runner.state["error"]
            old_phase = dict(runner.phases[7])
            evidence_root = preserve_phase_evidence(runner, args.resume_tag)
            smoke_index = 100 + len(runner.state.get("recoveries", []))
            recovery = {
                "resume_tag": args.resume_tag, "status": "running",
                "started_unix_ms": base.unix_ms(), "prior_error": prior_error,
                "failed_phase": old_phase, "failed_phase_evidence": str(evidence_root),
                "ring_slots": 32768, "smoke_evidence_index": smoke_index,
            }
            runner.state.setdefault("recoveries", []).append(recovery)
            runner.state.update({"status": "running", "error": None,
                                 "current_phase_index": None, "finished_unix_ms": None})
            runner.save()
            runner.event("phase_recovery_started", resume_tag=args.resume_tag,
                         reused_phases=list(range(7)))
            recovery_smoke(runner, recovery, args.resume_tag, smoke_index)
            failed_attempts = list(old_phase.get("failed_attempts", []))
            failed_attempts.append({
                key: value for key, value in old_phase.items() if key != "failed_attempts"
            })
            retry = {
                "index": 7, "label": "c-xcorr-scan", "scan": "C",
                "position": "scan", "kind": "xcorr", "mode": "spec_only",
                "duration_seconds": 900,
                "scan_id": f"{args.queue_id}-c-xcorr-scan-{args.resume_tag}-900s",
                "raw_stem": f"c-{args.resume_tag}", "status": "pending",
                "failed_attempts": failed_attempts,
            }
            runner.phases[7] = retry
            runner.state["phases"] = runner.phases
            runner.save()
            runner.run_phase(retry)
            runner.run_phase(runner.phases[8])
            runner.independent_verify()
            release = runner.build_explorer()
            runner.cutover(release)
            errors = runner.safe_finalize(failed=False)
            if errors:
                raise RuntimeError(f"recovery safe finalization failed: {errors}")
            recovery.update({"status": "completed", "finished_unix_ms": base.unix_ms()})
            runner.state.update({
                "status": "completed", "error": None, "current_phase_index": None,
                "finished_unix_ms": base.unix_ms(), "explorer_release": str(release),
                "url": "http://192.168.100.162:8035/",
            })
            runner.save()
            runner.event("queue_complete_after_phase_recovery", resume_tag=args.resume_tag)
            runner.final_manifest()
            return 0
        except Exception as error:
            errors = runner.safe_finalize(failed=True)
            if runner.state.get("current_phase_index") == 7:
                runner.phases[7]["status"] = "failed"
                runner.phases[7]["error"] = f"{type(error).__name__}: {error}"
            if recovery is not None:
                recovery.update({"status": "failed", "finished_unix_ms": base.unix_ms(),
                                 "error": f"{type(error).__name__}: {error}"})
            runner.state.update({
                "status": "failed", "finished_unix_ms": base.unix_ms(),
                "error": {"message": f"{type(error).__name__}: {error}",
                          "traceback": traceback.format_exc(),
                          "safe_finalize_errors": errors},
            })
            runner.save()
            runner.event("phase_recovery_failed", resume_tag=args.resume_tag,
                         error=runner.state["error"])
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
