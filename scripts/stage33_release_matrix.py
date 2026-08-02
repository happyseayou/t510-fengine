#!/usr/bin/env python3
"""Run resumable Stage 33 production smoke, soak, and thermal matrices."""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import urllib.error
import urllib.request
from typing import Any


SUITES: dict[str, tuple[float, tuple[tuple[int, str], ...]]] = {
    "smoke_60s": (
        60.0,
        (
            (160, "time_only"),
            (160, "spec_only"),
            (160, "time_spec"),
            (320, "time_only"),
            (320, "spec_only"),
        ),
    ),
    "soak_10m": (
        600.0,
        (
            (160, "time_spec"),
            (320, "time_only"),
            (320, "spec_only"),
        ),
    ),
    "thermal_60m": (3600.0, ((160, "time_spec"),)),
}


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
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _run(command: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )


def _agent_result(base: str, *, method: str = "GET", path: str = "/api/v2/status", body: dict[str, Any] | None = None) -> dict[str, Any]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        base.rstrip("/") + path,
        data=data,
        headers={"Content-Type": "application/json"} if data is not None else {},
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=15.0) as response:
            value = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(
            f"HTTP {exc.code} {path}: {exc.read().decode('utf-8', errors='replace')}"
        ) from exc
    result = value.get("result") if isinstance(value, dict) else None
    if not isinstance(result, dict):
        raise RuntimeError(f"Agent response has no result object: {value!r}")
    return result


def _stream_health(snapshot: dict[str, Any]) -> list[str]:
    if not bool(snapshot.get("streaming")):
        return []
    errors: list[str] = []
    if str(snapshot.get("core_version", "")).lower() != "0x00010033":
        errors.append("CORE_VERSION_MISMATCH")
    if int(snapshot.get("error_flags", 0)) != 0:
        errors.append("FPGA_ERROR_FLAGS_NONZERO")
    clock = snapshot.get("clock", {})
    if not bool(clock.get("configured")) or int(clock.get("pll1_lock", 0)) != 1 or int(clock.get("pll2_lock", 0)) != 1:
        errors.append("LMK_PLL_UNLOCKED")
    if str(clock.get("sysref_mode", "")) != "continuous":
        errors.append("SYSREF_NOT_CONTINUOUS")
    rfdc = snapshot.get("rfdc", {})
    if rfdc.get("readback", {}).get("ok") is not True:
        errors.append("RFDC_READBACK_CONTRACT_FAILED")
    active = int(rfdc.get("active_mask", 0)) & 0xFFFF
    current = int(rfdc.get("current_valid_mask", 0)) & 0xFFFF
    if active != 0xFFFF or current != active:
        errors.append("RFDC_VALID_MASK_INCOMPLETE")
    if snapshot.get("mts", {}).get("available") is not True:
        errors.append("MTS_EVIDENCE_UNAVAILABLE")
    if snapshot.get("pipeline", {}).get("stream_accepting") is not True:
        errors.append("PIPELINE_NOT_ACCEPTING")
    counters = snapshot.get("counters", {})
    for name in (
        "time_dropped",
        "spec_dropped",
        "tx_frames_dropped",
        "tx_route_miss",
        "tx_route_error",
        "rfdc_dropped",
        "science_dropped_beats",
    ):
        if int(counters.get(name, 0)) != 0:
            errors.append(f"NONZERO_{name.upper()}")
    return errors


def _run_gate_with_monitor(
    command: list[str],
    *,
    cwd: Path,
    agent_base: str,
    poll_seconds: float,
) -> tuple[int, dict[str, Any]]:
    process = subprocess.Popen(
        command,
        cwd=cwd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    samples: list[dict[str, Any]] = []
    monitor_errors: list[str] = []
    monitor_warnings: list[str] = []
    streaming_samples = 0
    while process.poll() is None:
        time.sleep(max(float(poll_seconds), 0.25))
        try:
            snapshot = _agent_result(agent_base)
        except Exception as exc:
            failure = f"STATUS_POLL_FAILED:{type(exc).__name__}:{exc}"
            monitor_warnings.append(failure)
            monitor_errors.append(failure)
            continue
        health_errors = _stream_health(snapshot)
        if bool(snapshot.get("streaming")):
            streaming_samples += 1
            monitor_errors.extend(health_errors)
        samples.append(
            {
                "captured_at_unix_ms": snapshot.get("captured_at_unix_ms"),
                "streaming": bool(snapshot.get("streaming")),
                "core_version": snapshot.get("core_version"),
                "clock": snapshot.get("clock"),
                "rfdc": snapshot.get("rfdc"),
                "mts": snapshot.get("mts"),
                "pipeline": snapshot.get("pipeline"),
                "counters": snapshot.get("counters"),
                "errors": health_errors,
            }
        )
    streaming_indexes = [
        index for index, sample in enumerate(samples) if sample["streaming"]
    ]
    if streaming_indexes:
        first_streaming = streaming_indexes[0]
        last_streaming = streaming_indexes[-1]
        if any(
            not sample["streaming"]
            for sample in samples[first_streaming:last_streaming + 1]
        ):
            monitor_errors.append("STREAMING_INTERRUPTED")
    return int(process.wait()), {
        "poll_seconds": max(float(poll_seconds), 0.25),
        "streaming_samples": streaming_samples,
        "samples": samples,
        "warnings": monitor_warnings,
        "errors": sorted(set(monitor_errors)),
        "ok": streaming_samples > 0 and not monitor_errors,
    }


def _mute_all_dacs(agent_base: str, dac_path: Path) -> dict[str, Any]:
    body = _read_json(dac_path)
    for channel in body.get("channels", []):
        channel["enabled"] = False
        channel["amplitude_percent"] = 0.0
    return _agent_result(agent_base, method="PUT", path="/api/v2/dac", body=body)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=tuple(SUITES), default="smoke_60s")
    parser.add_argument("--seconds", type=float, help="override the frozen suite duration")
    parser.add_argument("--tag", required=True)
    parser.add_argument("--config", default="config/stage33/configure_160_time_only.example.json")
    parser.add_argument("--dac-config", default="config/stage33/dac.example.json")
    parser.add_argument("--output-dir", default="reports/board")
    parser.add_argument("--agent-base", default="http://192.168.100.117:8010")
    parser.add_argument("--receiver-ssh", default="astrolab@192.168.100.162")
    parser.add_argument("--receiver-base-url", default="http://127.0.0.1:8089")
    parser.add_argument("--receiver-interface", default="enp1s0f0np0")
    parser.add_argument("--board-id", type=int, default=1)
    parser.add_argument("--poll-seconds", type=float, default=5.0)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--continue-on-failure", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    root = _root()
    default_seconds, cases = SUITES[args.suite]
    seconds = default_seconds if args.seconds is None else max(float(args.seconds), 0.1)
    config_path = (root / args.config).resolve()
    dac_path = (root / args.dac_config).resolve()
    config_template = _read_json(config_path)
    center_mhz = float(config_template.get("profile", {}).get("center_mhz", 200.0))
    output_dir = (root / args.output_dir).resolve()
    summary_path = output_dir / f"stage33_{args.suite}_summary_{args.tag}.json"
    summary: dict[str, Any] = {
        "ok": False,
        "classification": f"STAGE33_{args.suite.upper()}_IN_PROGRESS",
        "stage": 33,
        "suite": args.suite,
        "seconds_per_case": seconds,
        "tag": args.tag,
        "started_at": _timestamp(),
        "ended_at": None,
        "config": str(config_path),
        "config_sha256": _sha256(config_path),
        "center_mhz": center_mhz,
        "dac_config": str(dac_path),
        "dac_config_sha256": _sha256(dac_path),
        "cases": [],
        "errors": [],
    }
    _write_json(summary_path, summary)

    for sample_rate_msps, mode in cases:
        stem = f"stage33_{args.suite}_{sample_rate_msps}msps_{mode}_{args.tag}"
        output = output_dir / f"{stem}.json"
        if output.exists() and args.resume:
            evidence = _read_json(output)
            if evidence.get("ok") is True:
                summary["cases"].append(
                    {
                        "sample_rate_msps": sample_rate_msps,
                        "mode": mode,
                        "ok": True,
                        "resumed": True,
                        "evidence": str(output),
                        "evidence_sha256": _sha256(output),
                    }
                )
                _write_json(summary_path, summary)
                continue
        elif output.exists():
            summary["errors"].append(f"EVIDENCE_EXISTS:{output}")
            break

        configure = [
            sys.executable,
            str(root / "scripts" / "t510_agent_client.py"),
            "--base-url",
            args.agent_base,
            "configure",
            str(config_path),
            "--board-id",
            str(args.board_id),
            "--sample-rate-msps",
            str(sample_rate_msps),
            "--mode",
            mode,
            "--center-mhz",
            str(center_mhz),
        ]
        gate = [
            sys.executable,
            str(root / "scripts" / "stage33_agent_host_gate.py"),
            "--sample-rate-msps",
            str(sample_rate_msps),
            "--mode",
            mode,
            "--center-mhz",
            str(center_mhz),
            "--seconds",
            str(seconds),
            "--board-id",
            str(args.board_id),
            "--agent-base",
            args.agent_base,
            "--receiver-ssh",
            args.receiver_ssh,
            "--receiver-base-url",
            args.receiver_base_url,
            "--receiver-interface",
            args.receiver_interface,
            "--output",
            str(output),
        ]
        if args.dry_run:
            summary["cases"].append(
                {
                    "sample_rate_msps": sample_rate_msps,
                    "mode": mode,
                    "ok": True,
                    "dry_run": True,
                    "configure_command": configure,
                    "gate_command": gate,
                    "enable_all_dacs": args.suite == "thermal_60m",
                }
            )
            continue

        configured = _run(configure, cwd=root)
        if configured.returncode != 0:
            summary["errors"].append(
                f"CONFIGURE_FAILED:{sample_rate_msps}:{mode}:"
                f"{configured.stderr.strip() or configured.stdout[-2000:].strip()}"
            )
            _write_json(summary_path, summary)
            if not args.continue_on_failure:
                break
            continue

        dac_enabled = False
        dac_mute_required = args.suite == "thermal_60m"
        case_errors: list[str] = []
        try:
            if args.suite == "thermal_60m":
                enabled = _run(
                    [
                        sys.executable,
                        str(root / "scripts" / "t510_agent_client.py"),
                        "--base-url",
                        args.agent_base,
                        "dac",
                        str(dac_path),
                    ],
                    cwd=root,
                )
                if enabled.returncode != 0:
                    raise RuntimeError(enabled.stderr.strip() or enabled.stdout[-2000:].strip())
                dac_enabled = True
            returncode, monitor = _run_gate_with_monitor(
                gate,
                cwd=root,
                agent_base=args.agent_base,
                poll_seconds=args.poll_seconds,
            )
            if returncode != 0:
                case_errors.append(f"GATE_EXIT_{returncode}")
            if not monitor["ok"]:
                case_errors.extend(monitor["errors"] or ["NO_STREAMING_MONITOR_SAMPLE"])
            if not output.exists():
                case_errors.append("GATE_NO_EVIDENCE")
                evidence: dict[str, Any] = {}
            else:
                evidence = _read_json(output)
                if evidence.get("ok") is not True:
                    case_errors.append("GATE_REPORTED_FAILURE")
                evidence["continuous_monitor"] = monitor
                evidence["thermal_dac_all_enabled"] = dac_enabled
                evidence["ok"] = not case_errors
                if case_errors:
                    evidence.setdefault("errors", []).extend(sorted(set(case_errors)))
                _write_json(output, evidence)
        except Exception as exc:
            case_errors.append(f"{type(exc).__name__}:{exc}")
            evidence = {}
        finally:
            if dac_mute_required:
                try:
                    mute = _mute_all_dacs(args.agent_base, dac_path)
                    if output.exists():
                        current = _read_json(output)
                        current["thermal_dac_mute"] = mute
                        _write_json(output, current)
                except Exception as exc:
                    case_errors.append(f"DAC_MUTE_FAILED:{type(exc).__name__}:{exc}")

        if output.exists() and case_errors:
            current = _read_json(output)
            current["ok"] = False
            current.setdefault("errors", []).extend(sorted(set(case_errors)))
            _write_json(output, current)
        case_ok = output.exists() and not case_errors and _read_json(output).get("ok") is True
        summary["cases"].append(
            {
                "sample_rate_msps": sample_rate_msps,
                "mode": mode,
                "ok": case_ok,
                "resumed": False,
                "evidence": str(output),
                "evidence_sha256": _sha256(output) if output.exists() else None,
                "errors": sorted(set(case_errors)),
            }
        )
        if not case_ok:
            summary["errors"].append(f"CASE_FAILED:{sample_rate_msps}:{mode}")
            if not args.continue_on_failure:
                break
        _write_json(summary_path, summary)

    if args.dry_run:
        summary["ok"] = len(summary["cases"]) == len(cases)
        summary["classification"] = "STAGE33_RELEASE_MATRIX_DRY_RUN"
    else:
        summary["ok"] = (
            len(summary["cases"]) == len(cases)
            and all(case.get("ok") is True for case in summary["cases"])
            and not summary["errors"]
        )
        summary["classification"] = (
            f"STAGE33_{args.suite.upper()}_{'PASS' if summary['ok'] else 'FAIL'}"
        )
    summary["ended_at"] = _timestamp()
    _write_json(summary_path, summary)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
