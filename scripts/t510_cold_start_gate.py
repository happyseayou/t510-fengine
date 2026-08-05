#!/usr/bin/env python3
"""Verify a freshly cold-booted T510 board, services, configure, and resume."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import subprocess
import sys
import urllib.error
import urllib.request
from typing import Any

from t510_board_host_gate import _t510_rfdc_health


BOARD_SERVICES = ("t510-ref-watchdog.service", "t510-agent.service")
RECEIVER_SERVICES = ("t510-rx-tune.service", "t510-time-rx.service")


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def _timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def _run(command: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command, cwd=cwd, check=False, capture_output=True, text=True
    )


def _ssh(target: str, *remote_command: str) -> list[str]:
    return ["ssh", "-o", "BatchMode=yes", target, *remote_command]


def _service_probe(target: str, services: tuple[str, ...], *, cwd: Path) -> dict[str, Any]:
    uptime = _run(_ssh(target, "cat", "/proc/uptime"), cwd=cwd)
    enabled = _run(_ssh(target, "systemctl", "is-enabled", *services), cwd=cwd)
    active = _run(_ssh(target, "systemctl", "is-active", *services), cwd=cwd)
    try:
        uptime_seconds = float(uptime.stdout.split()[0])
    except (IndexError, ValueError):
        uptime_seconds = -1.0
    return {
        "target": target,
        "services": list(services),
        "uptime_seconds": uptime_seconds,
        "uptime_returncode": uptime.returncode,
        "enabled_returncode": enabled.returncode,
        "enabled": enabled.stdout.splitlines(),
        "active_returncode": active.returncode,
        "active": active.stdout.splitlines(),
        "stderr": "\n".join(
            item for item in (uptime.stderr, enabled.stderr, active.stderr) if item
        )[-2000:],
        "ok": (
            uptime.returncode == 0
            and uptime_seconds >= 0.0
            and enabled.returncode == 0
            and active.returncode == 0
            and enabled.stdout.splitlines() == ["enabled"] * len(services)
            and active.stdout.splitlines() == ["active"] * len(services)
        ),
    }


def _agent_result(
    base: str,
    path: str,
    *,
    body: dict[str, Any] | None = None,
    timeout: float = 190.0,
) -> dict[str, Any]:
    request = urllib.request.Request(
        base.rstrip("/") + path,
        data=None if body is None else json.dumps(body).encode("utf-8"),
        headers={} if body is None else {"Content-Type": "application/json"},
        method="GET" if body is None else "POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            value = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(
            f"HTTP {exc.code} {path}: {exc.read().decode('utf-8', errors='replace')}"
        ) from exc
    result = value.get("result") if isinstance(value, dict) else None
    if not isinstance(result, dict):
        raise RuntimeError(f"Agent response has no result object: {value!r}")
    return result


def _receiver_state(base: str) -> dict[str, Any]:
    with urllib.request.urlopen(base.rstrip("/") + "/api/state", timeout=10.0) as response:
        value = json.loads(response.read().decode("utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("receiver /api/state did not return an object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config/t510/configure_160_time_only.example.json")
    parser.add_argument(
        "--output",
        default="build/board/latest/evidence/cold_start.json",
    )
    parser.add_argument("--agent-base", default="http://192.168.100.117:8010")
    parser.add_argument("--receiver-base", default="http://192.168.100.162:8089")
    parser.add_argument("--board-ssh", default="xilinx@192.168.100.117")
    parser.add_argument("--receiver-ssh", default="astrolab@192.168.100.162")
    parser.add_argument("--board-id", type=int, default=1)
    parser.add_argument(
        "--max-board-uptime-seconds",
        type=float,
        default=600.0,
        help="fail unless the board was booted within this many seconds",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    root = _root()
    config = (root / args.config).resolve()
    output = (root / args.output).resolve()
    configure = [
        sys.executable,
        str(root / "scripts" / "t510_agent_client.py"),
        "--base-url",
        args.agent_base,
        "configure",
        str(config),
        "--board-id",
        str(args.board_id),
    ]
    dry_commands = {
        "board_uptime": _ssh(args.board_ssh, "cat", "/proc/uptime"),
        "board_enabled": _ssh(args.board_ssh, "systemctl", "is-enabled", *BOARD_SERVICES),
        "board_active": _ssh(args.board_ssh, "systemctl", "is-active", *BOARD_SERVICES),
        "receiver_enabled": _ssh(
            args.receiver_ssh, "systemctl", "is-enabled", *RECEIVER_SERVICES
        ),
        "receiver_active": _ssh(
            args.receiver_ssh, "systemctl", "is-active", *RECEIVER_SERVICES
        ),
        "configure": configure,
    }
    evidence: dict[str, Any] = {
        "ok": False,
        "classification": "T510_COLD_START_IN_PROGRESS",
        "release": "latest",
        "started_at": _timestamp(),
        "ended_at": None,
        "config": str(config),
        "max_board_uptime_seconds": args.max_board_uptime_seconds,
        "errors": [],
    }
    if args.dry_run:
        evidence.update(
            {
                "ok": True,
                "classification": "T510_COLD_START_DRY_RUN",
                "commands": dry_commands,
                "ended_at": _timestamp(),
            }
        )
        _write_json(output, evidence)
        print(json.dumps(evidence, indent=2, sort_keys=True))
        return 0

    started = False
    try:
        board_probe = _service_probe(args.board_ssh, BOARD_SERVICES, cwd=root)
        receiver_probe = _service_probe(args.receiver_ssh, RECEIVER_SERVICES, cwd=root)
        evidence["board_services"] = board_probe
        evidence["receiver_services"] = receiver_probe
        if not board_probe["ok"]:
            evidence["errors"].append("BOARD_SERVICES_NOT_ENABLED_AND_ACTIVE")
        if not receiver_probe["ok"]:
            evidence["errors"].append("RECEIVER_SERVICES_NOT_ENABLED_AND_ACTIVE")
        if not 0.0 <= board_probe["uptime_seconds"] <= args.max_board_uptime_seconds:
            evidence["errors"].append("BOARD_NOT_FRESHLY_BOOTED")
        evidence["receiver_state"] = _receiver_state(args.receiver_base)

        configured = _run(configure, cwd=root)
        evidence["configure"] = {
            "returncode": configured.returncode,
            "stdout": configured.stdout[-4000:],
            "stderr": configured.stderr[-4000:],
        }
        if configured.returncode != 0:
            raise RuntimeError("fresh CONFIGURE/MTS failed")

        idle = _agent_result(args.agent_base, "/api/v2/status")
        idle_health = _t510_rfdc_health(idle, require_valid=False)
        evidence["idle"] = idle
        evidence["idle_rfdc_health"] = idle_health
        if str(idle.get("core_version", "")).lower() != "0x00010033":
            evidence["errors"].append("CORE_VERSION_MISMATCH")
        if not idle_health["ok"]:
            evidence["errors"].extend(idle_health["errors"])

        transitions: list[dict[str, Any]] = []
        for cycle in range(2):
            _agent_result(
                args.agent_base,
                "/api/v2/start",
                body={"expected_board_id": args.board_id},
                timeout=30.0,
            )
            started = True
            streaming = _agent_result(args.agent_base, "/api/v2/status")
            health = _t510_rfdc_health(streaming, require_valid=True)
            row = {
                "cycle": cycle,
                "streaming": streaming,
                "rfdc_health": health,
            }
            if not bool(streaming.get("streaming")):
                evidence["errors"].append(f"START_{cycle}_DID_NOT_STREAM")
            if not health["ok"]:
                evidence["errors"].extend(
                    f"START_{cycle}_{error}" for error in health["errors"]
                )
            stopped = _agent_result(args.agent_base, "/api/v2/stop", body={})
            started = False
            row["stop"] = stopped
            transitions.append(row)
        evidence["transitions"] = transitions
    except Exception as exc:
        evidence["errors"].append(f"{type(exc).__name__}: {exc}")
    finally:
        if started:
            try:
                evidence["final_stop"] = _agent_result(
                    args.agent_base, "/api/v2/stop", body={}
                )
            except Exception as exc:
                evidence["errors"].append(
                    f"FINAL_STOP_FAILED:{type(exc).__name__}:{exc}"
                )
        evidence["ok"] = not evidence["errors"]
        evidence["classification"] = (
            "T510_COLD_START_PASS"
            if evidence["ok"]
            else "T510_COLD_START_FAIL"
        )
        evidence["ended_at"] = _timestamp()
        _write_json(output, evidence)

    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if evidence["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
