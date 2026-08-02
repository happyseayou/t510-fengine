#!/usr/bin/env python3
"""Run the frozen low/mid/high and 1.90 GHz Stage 33 DAC-purity points."""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any


CASES: tuple[tuple[str, float, float], ...] = (
    ("low", 200.0, 210.0),
    ("mid", 960.0, 970.0),
    ("high", 1760.0, 1770.0),
    ("rf_1900", 1760.0, 1900.0),
)


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def _timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    parser.add_argument(
        "--config", default="config/stage33/configure_320_time_only.example.json"
    )
    parser.add_argument("--output-dir", default="reports/board")
    parser.add_argument("--agent-base", default="http://192.168.100.117:8010")
    parser.add_argument("--receiver-base", default="http://192.168.100.162:8089")
    parser.add_argument("--receiver-host", default="192.168.100.162")
    parser.add_argument("--receiver-port", type=int, default=8089)
    parser.add_argument("--board-id", type=int, default=1)
    parser.add_argument("--captures", type=int, default=5)
    parser.add_argument("--continue-on-failure", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.captures <= 0:
        parser.error("--captures must be positive")

    root = _root()
    config = (root / args.config).resolve()
    output_dir = (root / args.output_dir).resolve()
    summary_path = output_dir / f"stage33_dac_purity_summary_{args.tag}.json"
    if summary_path.exists():
        raise FileExistsError(summary_path)
    summary: dict[str, Any] = {
        "ok": False,
        "classification": "STAGE33_DAC_PURITY_MATRIX_IN_PROGRESS",
        "stage": 33,
        "tag": args.tag,
        "started_at": _timestamp(),
        "ended_at": None,
        "sample_rate_msps": 320,
        "config": str(config),
        "config_sha256": _sha256(config),
        "cases": [],
        "errors": [],
    }
    _write_json(summary_path, summary)

    for name, center_mhz, tone_mhz in CASES:
        evidence_path = output_dir / f"stage33_dac_purity_{name}_{args.tag}.json"
        configure = [
            sys.executable,
            str(root / "scripts" / "t510_agent_client.py"),
            "--base-url",
            args.agent_base,
            "configure",
            str(config),
            "--board-id",
            str(args.board_id),
            "--sample-rate-msps",
            "320",
            "--mode",
            "spec_only",
            "--center-mhz",
            str(center_mhz),
        ]
        gate = [
            sys.executable,
            str(root / "scripts" / "stage33_dac_purity_gate.py"),
            "--agent-base",
            args.agent_base,
            "--receiver-base",
            args.receiver_base,
            "--receiver-host",
            args.receiver_host,
            "--receiver-port",
            str(args.receiver_port),
            "--board-id",
            str(args.board_id),
            "--sample-rate-msps",
            "320",
            "--center-mhz",
            str(center_mhz),
            "--tone-mhz",
            str(tone_mhz),
            "--captures",
            str(args.captures),
            "--output",
            str(evidence_path),
        ]
        if args.dry_run:
            summary["cases"].append(
                {
                    "name": name,
                    "center_mhz": center_mhz,
                    "tone_mhz": tone_mhz,
                    "ok": True,
                    "dry_run": True,
                    "configure_command": configure,
                    "gate_command": gate,
                }
            )
            continue
        if evidence_path.exists():
            summary["errors"].append(f"EVIDENCE_EXISTS:{evidence_path}")
            break
        configured = subprocess.run(
            configure, cwd=root, check=False, capture_output=True, text=True
        )
        completed = None
        if configured.returncode == 0:
            completed = subprocess.run(
                gate, cwd=root, check=False, capture_output=True, text=True
            )
        ok = (
            completed is not None
            and completed.returncode == 0
            and evidence_path.exists()
            and json.loads(evidence_path.read_text(encoding="utf-8")).get("ok") is True
        )
        summary["cases"].append(
            {
                "name": name,
                "center_mhz": center_mhz,
                "tone_mhz": tone_mhz,
                "ok": ok,
                "configure_returncode": configured.returncode,
                "gate_returncode": None if completed is None else completed.returncode,
                "evidence": str(evidence_path),
                "evidence_sha256": _sha256(evidence_path) if evidence_path.exists() else None,
                "stderr": (
                    configured.stderr[-2000:]
                    if configured.returncode != 0
                    else "" if completed is None else completed.stderr[-2000:]
                ),
            }
        )
        if not ok:
            summary["errors"].append(f"CASE_FAILED:{name}")
            if not args.continue_on_failure:
                break
        _write_json(summary_path, summary)

    summary["ok"] = len(summary["cases"]) == len(CASES) and all(
        row.get("ok") is True for row in summary["cases"]
    ) and not summary["errors"]
    summary["classification"] = (
        "STAGE33_DAC_PURITY_MATRIX_DRY_RUN"
        if args.dry_run and summary["ok"]
        else f"STAGE33_DAC_PURITY_MATRIX_{'PASS' if summary['ok'] else 'FAIL'}"
    )
    summary["ended_at"] = _timestamp()
    _write_json(summary_path, summary)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
