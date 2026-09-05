#!/usr/bin/env python3
"""Persistent one-shot Stage 35 report v2 generation and acceptance queue."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import traceback
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: object) -> None:
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with partial.open("rb") as stream:
        os.fsync(stream.fileno())
    partial.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--mode", choices=("sample", "full"), required=True)
    parser.add_argument("--plotly-js", type=Path, required=True)
    parser.add_argument("--plotly-license", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--chromedriver", type=Path, required=True)
    parser.add_argument("--chrome", type=Path, required=True)
    args = parser.parse_args()
    report = args.report.resolve()
    output_root = report.parent
    output_root.mkdir(parents=True, exist_ok=False)
    state_path = output_root / "queue_state.json"
    source_dir = Path(__file__).resolve().parent
    config = json.loads(args.config.read_text(encoding="utf-8"))
    state: dict[str, object] = {
        "format": "T510_STAGE35_S2_HTML_QUEUE_V2", "status": "running", "mode": args.mode,
        "created_unix_ms": time.time_ns() // 1_000_000, "report": str(report),
        "analysis_root": config["analysis_root"], "analysis_manifest_sha256": config["analysis_manifest_sha256"],
        "phases": [{"name": name, "status": "pending"} for name in (
            "generate", "payload_verify", "numeric_parquet_zarr_verify", "offline_chromium_verify", "archive_identity"
        )], "error": None,
    }
    write_json(state_path, state)
    try:
        commands = [
            [sys.executable, str(source_dir / "t510_stage35_s2_html_report_v2.py"), "--config", str(args.config), "--mode", args.mode, "--plotly-js", str(args.plotly_js), "--plotly-license", str(args.plotly_license), "--output", str(report)],
            [sys.executable, str(source_dir / "t510_stage35_s2_html_verify_v2.py"), "--report", str(report), "--output", str(output_root / "payload_verification.json")],
            [sys.executable, str(source_dir / "t510_stage35_s2_numeric_verify_v2.py"), "--report", str(report), "--analysis-root", config["analysis_root"], "--config", str(args.config), "--output", str(output_root / "numeric_verification.json")],
            [sys.executable, str(source_dir / "t510_stage35_s2_html_browser_verify_v2.py"), "--report", str(report), "--chromedriver", str(args.chromedriver), "--chrome", str(args.chrome), "--output", str(output_root / "browser_verification.json"), "--screenshot-dir", str(output_root / "screenshots")],
        ]
        for index, command in enumerate(commands):
            phase = state["phases"][index]  # type: ignore[index]
            phase["status"] = "running"
            phase["started_unix_ms"] = time.time_ns() // 1_000_000
            write_json(state_path, state)
            time_file = output_root / f"{phase['name']}.time.txt"
            completed = subprocess.run(["/usr/bin/time", "-v", "-o", str(time_file), *command], check=False)
            phase["finished_unix_ms"] = time.time_ns() // 1_000_000
            phase["returncode"] = completed.returncode
            if completed.returncode != 0:
                phase["status"] = "failed"
                raise RuntimeError(f"phase {phase['name']} returned {completed.returncode}")
            phase["status"] = "completed"
            write_json(state_path, state)
        archive_phase = state["phases"][4]  # type: ignore[index]
        archive_phase["status"] = "running"
        archive_phase["started_unix_ms"] = time.time_ns() // 1_000_000
        write_json(state_path, state)
        files = []
        for path in sorted(output_root.rglob("*")):
            if path.is_file() and path.name not in {"queue_state.json", "delivery_manifest.json"}:
                files.append({"path": str(path.relative_to(output_root)), "bytes": path.stat().st_size, "sha256": sha256_file(path)})
        delivery = {
            "format": "T510_STAGE35_S2_REPORT_DELIVERY_V2", "complete": True, "mode": args.mode,
            "analysis_manifest_sha256": config["analysis_manifest_sha256"], "files": files,
            "report_bytes": report.stat().st_size, "report_sha256": sha256_file(report),
        }
        write_json(output_root / "delivery_manifest.json", delivery)
        archive_phase["status"] = "completed"
        archive_phase["finished_unix_ms"] = time.time_ns() // 1_000_000
        state["status"] = "completed"
        state["finished_unix_ms"] = time.time_ns() // 1_000_000
        write_json(state_path, state)
        return 0
    except Exception as exc:
        state["status"] = "failed"
        state["finished_unix_ms"] = time.time_ns() // 1_000_000
        state["error"] = {"type": type(exc).__name__, "message": str(exc), "traceback": traceback.format_exc()}
        write_json(state_path, state)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
