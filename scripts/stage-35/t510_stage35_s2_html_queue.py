#!/usr/bin/env python3
"""One-shot persistent queue for Stage 35 HTML generation and verification."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import traceback
from pathlib import Path


def write_state(path: Path, value: dict[str, object]) -> None:
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with partial.open("rb") as stream:
        os.fsync(stream.fileno())
    partial.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--analysis-root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--expected-manifest-sha256", required=True)
    args = parser.parse_args()
    report = args.report.resolve()
    report.parent.mkdir(parents=True, exist_ok=False)
    state_path = report.parent / "queue_state.json"
    source_dir = Path(__file__).resolve().parent
    state: dict[str, object] = {
        "format": "T510_STAGE35_S2_HTML_QUEUE_V1",
        "status": "running",
        "created_unix_ms": time.time_ns() // 1_000_000,
        "analysis_root": str(args.analysis_root.resolve()),
        "report": str(report),
        "expected_analysis_manifest_sha256": args.expected_manifest_sha256,
        "phases": [
            {"name": "generate", "status": "pending"},
            {"name": "independent_verify", "status": "pending"},
        ],
        "error": None,
    }
    write_state(state_path, state)
    try:
        commands = [
            [
                sys.executable,
                str(source_dir / "t510_stage35_s2_html_report.py"),
                "--analysis-root", str(args.analysis_root),
                "--output", str(report),
                "--expected-manifest-sha256", args.expected_manifest_sha256,
            ],
            [
                sys.executable,
                str(source_dir / "t510_stage35_s2_html_verify.py"),
                "--report", str(report),
                "--output", str(report.parent / "verification.json"),
            ],
        ]
        for index, command in enumerate(commands):
            phase = state["phases"][index]  # type: ignore[index]
            phase["status"] = "running"
            phase["started_unix_ms"] = time.time_ns() // 1_000_000
            write_state(state_path, state)
            completed = subprocess.run(command, check=False)
            phase["finished_unix_ms"] = time.time_ns() // 1_000_000
            phase["returncode"] = completed.returncode
            if completed.returncode != 0:
                phase["status"] = "failed"
                raise RuntimeError(f"phase {phase['name']} returned {completed.returncode}")
            phase["status"] = "completed"
            write_state(state_path, state)
        state["status"] = "completed"
        state["finished_unix_ms"] = time.time_ns() // 1_000_000
        write_state(state_path, state)
        return 0
    except Exception as exc:
        state["status"] = "failed"
        state["finished_unix_ms"] = time.time_ns() // 1_000_000
        state["error"] = {"type": type(exc).__name__, "message": str(exc), "traceback": traceback.format_exc()}
        write_state(state_path, state)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
