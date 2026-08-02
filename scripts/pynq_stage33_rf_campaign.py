#!/usr/bin/env python3
"""Run the frozen Stage 33 eight-lane RF loopback acceptance points."""

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
    ("center_200", 200.0, 210.0),
    ("center_960", 960.0, 970.0),
    ("center_1760", 1760.0, 1770.0),
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


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain one JSON object")
    return value


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def _release_entry(catalog: dict[str, Any]) -> dict[str, Any]:
    entries = [
        entry
        for entry in catalog.get("bitstreams", [])
        if entry.get("id") == "fengine-0x00010033"
    ]
    if len(entries) != 1:
        raise ValueError("catalog must contain exactly one fengine-0x00010033 entry")
    entry = entries[0]
    if str(entry.get("core_version", "")).lower() != "0x00010033":
        raise ValueError("Stage 33 catalog core_version mismatch")
    sha256 = str(entry.get("sha256", "")).lower()
    if len(sha256) != 64 or sha256 == "0" * 64:
        raise ValueError("Stage 33 catalog has not been finalized")
    adc_target = int(entry.get("mts_adc_target_latency", -1))
    dac_target = int(entry.get("mts_dac_target_latency", -1))
    if min(adc_target, dac_target) < 0 or adc_target == 230 or dac_target == 336:
        raise ValueError("Stage 33 catalog contains invalid MTS targets")
    campaign = entry.get("mts_campaign")
    if not isinstance(campaign, dict):
        raise ValueError("Stage 33 catalog has no MTS campaign proof")
    expected_cycles = {
        "rfdc_reset": 20,
        "overlay_reload": 10,
        "lmk_reload": 10,
        "passed": 40,
    }
    for phase in ("discovery", "fixed"):
        if campaign.get(phase) != expected_cycles:
            raise ValueError(
                f"Stage 33 catalog {phase} campaign must be the frozen 40/40 matrix"
            )
    if int(campaign.get("adc_margin", -1)) != 20 or int(
        campaign.get("dac_margin", -1)
    ) != 16:
        raise ValueError("Stage 33 catalog has the wrong MTS margins")
    if adc_target != int(campaign.get("observed_adc_max", -1)) + 20 or dac_target != int(
        campaign.get("observed_dac_max", -1)
    ) + 16:
        raise ValueError("Stage 33 catalog targets do not match discovery maxima")
    evidence_sha = str(campaign.get("evidence_sha256", ""))
    if len(evidence_sha) != 64 or any(
        character not in "0123456789abcdefABCDEF" for character in evidence_sha
    ):
        raise ValueError("Stage 33 catalog has an invalid MTS evidence SHA")
    return entry


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--catalog", default="config/stage33/config.example.json"
    )
    parser.add_argument(
        "--bitfile",
        default="build/stage33-vivado/latest/overlay/t510_fengine.bit",
    )
    parser.add_argument("--output-dir", default="reports/board")
    parser.add_argument("--tag", required=True)
    parser.add_argument("--frames", type=int, default=240)
    parser.add_argument("--samples", type=int, default=512)
    parser.add_argument("--timeout", type=float, default=3.0)
    parser.add_argument("--no-download", action="store_true")
    parser.add_argument("--continue-on-failure", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.frames < 2 or args.samples < 64:
        parser.error("--frames must be >=2 and --samples must be >=64")

    root = _root()
    catalog_path = (root / args.catalog).resolve()
    bitfile = (root / args.bitfile).resolve()
    output_dir = (root / args.output_dir).resolve()
    entry = _release_entry(_read_json(catalog_path))
    expected_sha = str(entry["sha256"]).lower()
    if not bitfile.is_file():
        raise FileNotFoundError(bitfile)
    actual_sha = _sha256(bitfile)
    if actual_sha != expected_sha:
        raise ValueError(
            f"candidate bitstream SHA mismatch: catalog={expected_sha}, file={actual_sha}"
        )

    summary_path = output_dir / f"stage33_rf_campaign_summary_{args.tag}.json"
    if summary_path.exists():
        raise FileExistsError(summary_path)
    summary: dict[str, Any] = {
        "ok": False,
        "classification": "STAGE33_RF_CAMPAIGN_IN_PROGRESS",
        "stage": 33,
        "tag": args.tag,
        "started_at": _timestamp(),
        "ended_at": None,
        "catalog": str(catalog_path),
        "catalog_sha256": _sha256(catalog_path),
        "bitfile": str(bitfile),
        "bitstream_sha256": actual_sha,
        "fixed_targets": {
            "adc": int(entry["mts_adc_target_latency"]),
            "dac": int(entry["mts_dac_target_latency"]),
        },
        "cases": [],
        "errors": [],
    }
    _write_json(summary_path, summary)

    for name, center_mhz, signal_mhz in CASES:
        evidence_path = output_dir / f"stage33_rf_{name}_{args.tag}.json"
        command = [
            sys.executable,
            str(root / "scripts" / "pynq_stage33_8lane_loopback.py"),
            "--bitfile",
            str(bitfile),
            "--center-mhz",
            str(center_mhz),
            "--signal-mhz",
            str(signal_mhz),
            "--frames",
            str(args.frames),
            "--samples",
            str(args.samples),
            "--timeout",
            str(args.timeout),
            "--adc-target",
            str(entry["mts_adc_target_latency"]),
            "--dac-target",
            str(entry["mts_dac_target_latency"]),
            "--output",
            str(evidence_path),
        ]
        if args.no_download:
            command.append("--no-download")
        if args.dry_run:
            summary["cases"].append(
                {
                    "name": name,
                    "center_mhz": center_mhz,
                    "signal_mhz": signal_mhz,
                    "ok": True,
                    "dry_run": True,
                    "command": command,
                }
            )
            continue
        if evidence_path.exists():
            summary["errors"].append(f"EVIDENCE_EXISTS:{evidence_path}")
            break
        completed = subprocess.run(
            command, cwd=root, check=False, capture_output=True, text=True
        )
        evidence = _read_json(evidence_path) if evidence_path.exists() else {}
        ok = completed.returncode == 0 and evidence.get("ok") is True
        row = {
            "name": name,
            "center_mhz": center_mhz,
            "signal_mhz": signal_mhz,
            "ok": ok,
            "returncode": completed.returncode,
            "evidence": str(evidence_path),
            "evidence_sha256": _sha256(evidence_path) if evidence_path.exists() else None,
            "stderr": completed.stderr[-2000:],
        }
        summary["cases"].append(row)
        if not ok:
            summary["errors"].append(f"CASE_FAILED:{name}")
            if not args.continue_on_failure:
                break
        _write_json(summary_path, summary)

    summary["ok"] = len(summary["cases"]) == len(CASES) and all(
        row.get("ok") is True for row in summary["cases"]
    ) and not summary["errors"]
    summary["classification"] = (
        "STAGE33_RF_CAMPAIGN_DRY_RUN"
        if args.dry_run and summary["ok"]
        else f"STAGE33_RF_CAMPAIGN_{'PASS' if summary['ok'] else 'FAIL'}"
    )
    summary["ended_at"] = _timestamp()
    _write_json(summary_path, summary)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
