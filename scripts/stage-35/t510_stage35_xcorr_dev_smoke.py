#!/usr/bin/env python3
"""Run one short, fail-closed Stage 35 XCORR link qualification.

This is an implementation-time gate only.  It deliberately uses the same
mode transition, stream, raw witness, CUDA capture, manifest, and safe-stop
methods as the formal queue, but it never marks a Stage step complete.
"""

from __future__ import annotations

import argparse
import json
import traceback
from pathlib import Path

import t510_stage35_s2_queue as base
from t510_stage35_xcorr_explorer_queue import Queue


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--queue-id", required=True)
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--helper-dir", type=Path, required=True)
    parser.add_argument("--sidecar", type=Path, required=True)
    parser.add_argument("--analysis-root", type=Path, required=True)
    parser.add_argument("--report-config", type=Path, required=True)
    parser.add_argument("--preflight-pcap", type=Path, required=True)
    parser.add_argument("--duration-seconds", type=int, default=2)
    parser.add_argument("--measurement-root", type=Path, default=Path("/var/lib/t510/stage35"))
    parser.add_argument("--agent-base", default="http://192.168.100.117:8010")
    parser.add_argument("--receiver-base", default="http://127.0.0.1:8089")
    parser.add_argument("--minimum-free-bytes", type=int, default=10_000_000_000)
    args = parser.parse_args()
    if not 1 <= args.duration_seconds <= 10:
        raise ValueError("development qualification duration must be 1..10 seconds")
    # Queue.__init__ only consumes these during later formal-analysis methods;
    # provide inert fixed paths so this tool cannot accidentally cut over 8035.
    args.replay_evidence = args.measurement_root
    args.explorer_root = args.measurement_root / "explorer"
    args.app_root = Path("/opt/t510-stage35-explorer/current")
    args.chrome = Path("/bin/false")
    args.chromedriver = Path("/bin/false")
    args.spec_scans = {}
    runner = Queue(args, json.loads(args.template.read_text()))
    phase = {
        "index": 0, "label": "dev-cuda-link", "scan": "DEV", "position": "dev",
        "kind": "xcorr", "mode": "spec_only", "duration_seconds": args.duration_seconds,
        "scan_id": f"{args.queue_id}-cuda-xcorr-link-{args.duration_seconds}s", "status": "pending",
    }
    runner.phases = [phase]
    runner.state["phases"] = runner.phases
    runner.state["pipeline"] = ["development_link_qualification_only", "safe_stop"]
    runner.initialize()
    try:
        runner.preflight()
        runner.state["status"] = "running"
        runner.state["started_unix_ms"] = base.unix_ms()
        runner.save()
        runner.run_phase(phase)
        errors = runner.safe_finalize(failed=False)
        if errors:
            raise RuntimeError(f"safe finalization errors: {errors}")
        runner.state.update({"status": "completed", "current_phase_index": None,
                             "finished_unix_ms": base.unix_ms(),
                             "scientific_status": "DEVELOPMENT_ONLY_NOT_A_FORMAL_SCAN"})
        runner.save()
        runner.event("development_link_qualification_pass")
        return 0
    except Exception as error:
        errors = runner.safe_finalize(failed=True)
        phase["status"] = "failed"
        runner.state.update({"status": "failed", "finished_unix_ms": base.unix_ms(),
                             "error": {"message": f"{type(error).__name__}: {error}",
                                       "traceback": traceback.format_exc(),
                                       "safe_finalize_errors": errors}})
        runner.save()
        runner.event("development_link_qualification_failed", error=runner.state["error"])
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
