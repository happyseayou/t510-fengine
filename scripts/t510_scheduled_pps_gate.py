#!/usr/bin/env python3
"""Run the single-board scheduled-PPS release gate and preserve JSON evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shlex
import subprocess
import sys
import time
import urllib.request


ROOT = Path(__file__).resolve().parents[1]


def _http(base: str, path: str, body: dict | None = None) -> dict:
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(
        base.rstrip("/") + path,
        data=data,
        headers={} if data is None else {"Content-Type": "application/json"},
        method="GET" if data is None else "POST",
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        value = json.load(response)
    return dict(value.get("result", value))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent-base", default="http://192.168.100.117:8010")
    parser.add_argument("--board-id", type=int, default=1)
    parser.add_argument("--generation", type=int, default=lambda: int(time.time()))
    parser.add_argument("--epoch-tai", type=int, required=True)
    parser.add_argument("--lead-pps", type=int, default=5)
    parser.add_argument("--signal-chain-tag", type=lambda value: int(value, 0), required=True)
    parser.add_argument("--observation-tag", type=lambda value: int(value, 0), default=0)
    parser.add_argument("--schedule-tag", type=lambda value: int(value, 0), default=0)
    parser.add_argument("--seconds", type=float, default=10.0)
    parser.add_argument("--remote-validator", required=True)
    parser.add_argument("--remote-output", required=True)
    parser.add_argument("--receiver-ssh", default="astrolab@192.168.100.162")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    generation = args.generation() if callable(args.generation) else args.generation
    before = _http(args.agent_base, "/api/v2/sync/status")
    sync_before = dict(before.get("sync", {}))
    current_pps = int(sync_before.get("current_pps_count", -1))
    if not sync_before.get("ref_locked") or not sync_before.get("pps_recent"):
        raise RuntimeError("external reference or PPS is not ready")

    prepare = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", args.receiver_ssh, shlex.join([
            "python3", args.remote_validator, "--sample-rate-msps", "160",
            "--mode", "time_spec", "--center-mhz", "200", "--prepare-only",
        ])], check=False, capture_output=True, text=True,
    )
    if prepare.returncode:
        raise RuntimeError(f"receiver preparation failed: {prepare.stderr or prepare.stdout}")

    coordinate = args.output.with_name("scheduled-coordinate.json")
    command = [
        sys.executable, str(ROOT / "scripts/t510_multiboard_sync.py"),
        "--board", f"{args.agent_base},{args.board_id}",
        "--generation", str(generation), "--epoch-tai", str(args.epoch_tai),
        "--lead-pps", str(args.lead_pps), "--signal-chain-tag", hex(args.signal_chain_tag),
        "--observation-tag", hex(args.observation_tag), "--schedule-tag", hex(args.schedule_tag),
        "--output", str(coordinate),
    ]
    subprocess.run(command, check=True)
    coordinated = json.loads(coordinate.read_text(encoding="utf-8"))
    target_pps = int(coordinated["target_pps_count_by_board"][str(args.board_id)])
    if target_pps < current_pps + 5:
        raise RuntimeError("scheduled target did not preserve the required five-PPS lead")

    host_output = args.output.with_name("scheduled-host.json")
    host = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", args.receiver_ssh, shlex.join([
            "python3", args.remote_validator, "--sample-rate-msps", "160",
            "--mode", "time_spec", "--center-mhz", "200", "--seconds",
            str(args.seconds), "--skip-config", "--output", args.remote_output,
        ])], check=False, capture_output=True, text=True,
    )
    if host.returncode == 0:
        copied = subprocess.run(["scp", f"{args.receiver_ssh}:{args.remote_output}",
                                 str(host_output)], check=False)
        if copied.returncode:
            host = subprocess.CompletedProcess(host.args, copied.returncode, host.stdout,
                                               "failed to copy host evidence")
    after = _http(args.agent_base, "/api/v2/sync/status")
    sync_after = dict(after.get("sync", {}))
    errors: list[str] = []
    if host.returncode != 0:
        errors.append("HOST_VALIDATION_FAILED")
    if int(sync_after.get("active_generation", 0)) != generation:
        errors.append("GENERATION_MISMATCH")
    if not sync_after.get("first_time_seen") or not sync_after.get("first_spec_seen"):
        errors.append("FIRST_PACKET_IDENTITY_MISSING")
    snapshot = dict(after.get("snapshot", {}))
    pipeline = dict(snapshot.get("pipeline", {}))
    if pipeline.get("cmac_mux_stale_science_frame"):
        errors.append("DATA_BEFORE_SCHEDULED_TARGET")
    result = {
        "ok": not errors,
        "generation": generation,
        "current_pps_count_before": current_pps,
        "target_pps_count": target_pps,
        "lead_pps": target_pps - current_pps,
        "seconds": args.seconds,
        "coordinate": coordinated,
        "host": json.loads(host_output.read_text(encoding="utf-8")) if host_output.exists() else {
            "stdout": host.stdout, "stderr": host.stderr,
        },
        "sync_after": after,
        "errors": errors,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    try:
        _http(args.agent_base, "/api/v2/stop", {
            "reason": "scheduled_pps_gate_complete", "expected_board_id": args.board_id,
            "sample_rate_msps": 160, "mode": "time_spec", "center_mhz": 200.0,
        })
    finally:
        print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
