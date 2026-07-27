#!/usr/bin/env python3
"""Run resumable Stage 32h board/host soak matrices.

This is deliberately a thin orchestrator around the existing Stage 32
configure client and board/host gate.  It does not introduce another control
or packet path.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any


TEN_MINUTE_CASES = (
    (160, "time_only"),
    (160, "spec_only"),
    (160, "time_spec"),
    (320, "time_only"),
    (320, "spec_only"),
)

FULL_LINE_CASES = (
    (160, "time_spec"),
    (320, "time_only"),
    (320, "spec_only"),
)


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def _timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} does not contain a JSON object")
    return value


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_sha(root: Path) -> str:
    process = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    return process.stdout.strip() if process.returncode == 0 else "unknown"


def _case_summary(
    bandwidth_mhz: int,
    mode: str,
    output: Path,
    evidence: dict[str, Any],
    *,
    resumed: bool,
) -> dict[str, Any]:
    host = evidence.get("host", {})
    return {
        "bandwidth_mhz": bandwidth_mhz,
        "mode": mode,
        "ok": bool(evidence.get("ok")),
        "classification": evidence.get("classification"),
        "resumed": resumed,
        "evidence": str(output),
        "evidence_sha256": _sha256(output),
        "host_evidence": evidence.get("host_evidence"),
        "rates": host.get("rates"),
        "host_errors": host.get("errors"),
        "host_warnings": host.get("warnings"),
        "board_errors": evidence.get("errors"),
        "board_warnings": evidence.get("warnings"),
        "qsfp_health": evidence.get("qsfp_health"),
        "board_counter_delta": evidence.get("board_counter_delta"),
        "channelizer_counter_delta": evidence.get("channelizer_counter_delta"),
        "stop_clean": bool(
            evidence.get("stop", {})
            .get("snapshot", {})
            .get("pipeline", {})
            .get("flush_clean")
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--suite",
        choices=("ten_minute", "full_line"),
        default="ten_minute",
    )
    parser.add_argument(
        "--seconds",
        type=float,
        help="override 600/3600 seconds; intended only for orchestrator smoke tests",
    )
    parser.add_argument("--tag", required=True)
    parser.add_argument(
        "--config",
        default="config/stage32/configure_160_time_only.example.json",
    )
    parser.add_argument("--output-dir", default="reports/board")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--continue-on-failure", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    root = _root()
    cases = TEN_MINUTE_CASES if args.suite == "ten_minute" else FULL_LINE_CASES
    default_seconds = 600.0 if args.suite == "ten_minute" else 3600.0
    seconds = default_seconds if args.seconds is None else max(args.seconds, 0.1)
    output_dir = root / args.output_dir
    summary_path = output_dir / f"stage32h_{args.suite}_summary_{args.tag}.json"
    validator_path = root / "scripts" / "stage29_host_validate.py"
    summary: dict[str, Any] = {
        "ok": False,
        "classification": f"STAGE32H_{args.suite.upper()}_IN_PROGRESS",
        "stage": "32h",
        "suite": args.suite,
        "seconds_per_case": seconds,
        "tag": args.tag,
        "started_at": _timestamp(),
        "ended_at": None,
        "git_sha": _git_sha(root),
        "validator_sha256": _sha256(validator_path),
        "config": args.config,
        "cases": [],
        "errors": [],
    }
    _write_json(summary_path, summary)

    for bandwidth_mhz, mode in cases:
        stem = f"stage32h_{args.suite}_{bandwidth_mhz}msps_{mode}_{args.tag}"
        output = output_dir / f"{stem}.json"
        if output.exists():
            if not args.resume:
                summary["errors"].append(f"EVIDENCE_EXISTS:{output}")
                break
            evidence = _read_json(output)
            if bool(evidence.get("ok")):
                case = _case_summary(
                    bandwidth_mhz,
                    mode,
                    output,
                    evidence,
                    resumed=True,
                )
                summary["cases"].append(case)
                _write_json(summary_path, summary)
                print(
                    f"RESUME PASS {bandwidth_mhz} {mode}: {output}",
                    flush=True,
                )
                continue

        configure_command = [
            sys.executable,
            str(root / "scripts" / "stage30_agent_client.py"),
            "configure",
            str(root / args.config),
            "--bandwidth-mhz",
            str(bandwidth_mhz),
            "--mode",
            mode,
        ]
        gate_command = [
            sys.executable,
            str(root / "scripts" / "stage32_agent_host_gate.py"),
            "--bandwidth-mhz",
            str(bandwidth_mhz),
            "--mode",
            mode,
            "--seconds",
            str(seconds),
            "--output",
            str(output),
        ]
        if args.dry_run:
            print("CONFIGURE:", " ".join(configure_command), flush=True)
            print("GATE:", " ".join(gate_command), flush=True)
            continue

        print(
            f"START {bandwidth_mhz} MS/s {mode} for {seconds:.1f}s",
            flush=True,
        )
        configured = subprocess.run(
            configure_command,
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
        )
        if configured.returncode != 0:
            summary["errors"].append(
                f"CONFIGURE_FAILED:{bandwidth_mhz}:{mode}:"
                f"{configured.stderr.strip() or configured.stdout[-1000:].strip()}"
            )
            _write_json(summary_path, summary)
            if not args.continue_on_failure:
                break
            continue

        gated = subprocess.run(
            gate_command,
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
        )
        if not output.exists():
            summary["errors"].append(
                f"GATE_NO_EVIDENCE:{bandwidth_mhz}:{mode}:"
                f"{gated.stderr.strip() or gated.stdout[-1000:].strip()}"
            )
            _write_json(summary_path, summary)
            if not args.continue_on_failure:
                break
            continue

        evidence = _read_json(output)
        case = _case_summary(
            bandwidth_mhz,
            mode,
            output,
            evidence,
            resumed=False,
        )
        summary["cases"].append(case)
        _write_json(summary_path, summary)
        print(
            f"{'PASS' if case['ok'] else 'FAIL'} "
            f"{bandwidth_mhz} {mode}: {output}",
            flush=True,
        )
        if gated.returncode != 0 or not case["ok"]:
            summary["errors"].append(f"GATE_FAILED:{bandwidth_mhz}:{mode}")
            if not args.continue_on_failure:
                break

    if args.dry_run:
        summary["classification"] = f"STAGE32H_{args.suite.upper()}_DRY_RUN"
        summary["ok"] = True
    else:
        summary["ok"] = (
            len(summary["cases"]) == len(cases)
            and all(bool(case.get("ok")) for case in summary["cases"])
            and not summary["errors"]
        )
        summary["classification"] = (
            f"STAGE32H_{args.suite.upper()}_"
            f"{'PASS' if summary['ok'] else 'FAIL'}"
        )
    summary["ended_at"] = _timestamp()
    _write_json(summary_path, summary)
    print(json.dumps(summary, indent=2, sort_keys=True), flush=True)
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
