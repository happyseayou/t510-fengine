#!/usr/bin/env python3
"""Deploy the isolated final v35 candidate, run Stage 34c-2 science, restore v34."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import t510_adc_correlated_noise_campaign as c34c
from scripts import t510_fullband_spur_scan as fullband


BOARD_ID = 1
CANDIDATE_CORE = "0x00010035"
CANDIDATE_ID = "fengine-0x00010035"
CANDIDATE_SHA256 = "8934a0c2d7033494b49133d846f954b52a6fa76a54b65c043c6e7be5289728d1"
PRODUCTION_CORE = "0x00010034"
PRODUCTION_ID = "fengine-0x00010034"
TICS_MANIFEST_SHA256 = "695308db629e6223ec2d9ef19c9c07cb0ebd231b5b18f8632a964c6210d17009"
REMOTE_ROOT = "/run/t510-stage34c2r-v35-agent"
AGENT_UNIT = "t510-stage34c2r-v35-science-agent.service"
WATCHDOG_UNIT = "t510-stage34c2r-v35-science-watchdog.service"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def ssh_base(host: str) -> list[str]:
    return [
        "ssh",
        "-F",
        "/dev/null",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=8",
        "-o",
        "StrictHostKeyChecking=no",
        host,
    ]


def remote(host: str, command: str, *, timeout: float = 90.0) -> str:
    result = subprocess.run(
        [*ssh_base(host), command],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(f"remote command failed ({command}): {result.stdout.strip()}")
    return result.stdout


def remote_sudo(host: str, command: str, *, timeout: float = 90.0) -> str:
    return remote(
        host,
        "printf '%s\\n' xilinx | sudo -S sh -c " + shlex.quote(command),
        timeout=timeout,
    )


def wait_agent(agent_base: str, *, core_version: str | None = None) -> dict[str, Any]:
    deadline = time.monotonic() + 45.0
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            capabilities = fullband._http_json(
                agent_base.rstrip("/") + "/api/v2/capabilities", timeout=4.0
            )
            if core_version is None:
                return capabilities
            status = fullband._http_json(
                agent_base.rstrip("/") + "/api/v2/status", timeout=12.0
            )
            if core_version is None or str(status.get("core_version", "")).lower() == core_version:
                return status
        except Exception as exc:  # noqa: BLE001 - retry bounded service startup
            last_error = exc
        time.sleep(1.0)
    raise RuntimeError(f"board Agent did not become ready: {last_error}")


def candidate_config(template: dict[str, Any]) -> dict[str, Any]:
    return {
        "listen": "0.0.0.0:8010",
        "management_interface": "eth0",
        "python_executable": "/usr/local/share/pynq-venv/bin/python3",
        "helper_path": f"{REMOTE_ROOT}/python/t510_hw.py",
        "helper_pythonpath": REMOTE_ROOT,
        "default_bitstream_id": CANDIDATE_ID,
        "configure_timeout_seconds": 300,
        "operation_timeout_seconds": 60,
        "bitstreams": [
            {
                "id": CANDIDATE_ID,
                "path": f"{REMOTE_ROOT}/overlay/t510_fengine.bit",
                "sha256": CANDIDATE_SHA256,
                "core_version": CANDIDATE_CORE,
                "mts_adc_target_latency": -1,
                "mts_dac_target_latency": -1,
                "profiles": [
                    {
                        "sample_rate_msps": 160,
                        "modes": ["time_only", "spec_only", "time_spec"],
                    },
                    {
                        "sample_rate_msps": 320,
                        "modes": ["time_only", "spec_only"],
                    },
                ],
            }
        ],
    }


def build_bundle(args: argparse.Namespace, root: Path) -> None:
    repo = args.repo
    sources = {
        repo / "rust/t510_board_agent/target/aarch64-unknown-linux-musl/release/t510-board-agent": root / "bin/t510-board-agent",
        args.candidate_overlay / "t510_fengine.bit": root / "overlay/t510_fengine.bit",
        args.candidate_overlay / "t510_fengine.hwh": root / "overlay/t510_fengine.hwh",
        args.manifest: root / "profiles/manifest.json",
    }
    for name in (
        "__init__.py",
        "packet.py",
        "t510_ams.py",
        "t510_clock.py",
        "t510_control.py",
        "t510_fengine.py",
        "t510_scaling.py",
        "t510_hw.py",
        "t510_ref_watchdog.py",
    ):
        sources[repo / "python" / name] = root / "python" / name
    for source, target in sources.items():
        if not source.is_file():
            raise RuntimeError(f"candidate bundle source is missing: {source}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    if sha256_file(root / "overlay/t510_fengine.bit") != CANDIDATE_SHA256:
        raise RuntimeError("final v35 candidate bitstream SHA256 mismatch")
    if sha256_file(root / "profiles/manifest.json") != TICS_MANIFEST_SHA256:
        raise RuntimeError("TICS profile manifest SHA256 mismatch")
    write_json(root / "config.json", candidate_config({}))


def deploy_candidate(args: argparse.Namespace, bundle: Path) -> None:
    upload = "/tmp/t510-stage34c2r-v35-science-upload"
    remote_sudo(
        args.board_ssh,
        f"systemctl stop {AGENT_UNIT} {WATCHDOG_UNIT} t510-agent.service t510-ref-watchdog.service >/dev/null 2>&1 || true",
    )
    remote_sudo(
        args.board_ssh,
        f"rm -rf -- {upload} {REMOTE_ROOT} && "
        f"install -d -o xilinx -g xilinx -m 0755 {upload} && "
        f"install -d -o root -g root -m 0755 {REMOTE_ROOT}",
    )
    subprocess.run(
        [
            "scp",
            "-F",
            "/dev/null",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=8",
            "-o",
            "StrictHostKeyChecking=no",
            "-r",
            f"{bundle}/.",
            f"{args.board_ssh}:{upload}/",
        ],
        check=True,
        timeout=180.0,
    )
    remote_sudo(
        args.board_ssh,
        f"cp -a {upload}/. {REMOTE_ROOT}/ && chmod 0755 {REMOTE_ROOT}/bin/t510-board-agent && rm -rf -- {upload}",
    )
    manifest_remote = f"{REMOTE_ROOT}/profiles/manifest.json"
    common_properties = (
        "--property=User=root --property=Group=root --property=Restart=on-failure "
        "--property=RestartSec=2 --property=NoNewPrivileges=true "
        "--property=PrivateTmp=true --property=ProtectKernelModules=true "
        "--property=ProtectControlGroups=true"
    )
    remote_sudo(
        args.board_ssh,
        "systemd-run "
        f"--unit={AGENT_UNIT.removesuffix('.service')} {common_properties} "
        f"--working-directory={REMOTE_ROOT} --setenv=RUST_LOG=info "
        "--setenv=PYTHONDONTWRITEBYTECODE=1 --setenv=PYTHONUNBUFFERED=1 "
        "--setenv=XILINX_XRT=/usr "
        f"--setenv=T510_CLOCK_DIAGNOSTIC_PROFILE_MANIFEST={manifest_remote} "
        f"--setenv=T510_CLOCK_DIAGNOSTIC_PROFILE_MANIFEST_SHA256={TICS_MANIFEST_SHA256} "
        f"{REMOTE_ROOT}/bin/t510-board-agent --config {REMOTE_ROOT}/config.json",
    )
    deadline = time.monotonic() + 30.0
    while True:
        try:
            fullband._http_json(args.agent_base.rstrip("/") + "/api/v2/capabilities", timeout=3.0)
            break
        except Exception:
            if time.monotonic() >= deadline:
                raise
            time.sleep(1.0)
    remote_sudo(
        args.board_ssh,
        "systemd-run "
        f"--unit={WATCHDOG_UNIT.removesuffix('.service')} {common_properties} "
        f"--working-directory={REMOTE_ROOT} --setenv=PYTHONPATH={REMOTE_ROOT} "
        "--setenv=PYTHONDONTWRITEBYTECODE=1 --setenv=PYTHONUNBUFFERED=1 "
        "--setenv=XILINX_XRT=/usr "
        f"--setenv=T510_CLOCK_DIAGNOSTIC_PROFILE_MANIFEST={manifest_remote} "
        f"--setenv=T510_CLOCK_DIAGNOSTIC_PROFILE_MANIFEST_SHA256={TICS_MANIFEST_SHA256} "
        "/usr/local/share/pynq-venv/bin/python3 "
        f"{REMOTE_ROOT}/python/t510_ref_watchdog.py "
        f"--bitfile {REMOTE_ROOT}/overlay/t510_fengine.bit "
        "--state /run/t510-ref-watchdog.json --lock /run/t510-ref-watchdog.lock "
        "--configure-lock /run/t510-configure.lock "
        "--clock-diagnostic-state /run/t510-clock-diagnostic.json "
        "--expected-core-version 0x00010035 --interval-ms 100 "
        "--unlock-confirmations 2 --spi-error-confirmations 5 --stop-timeout-ms 2000",
    )


def configure_body(
    template: dict[str, Any], bitstream_id: str, profile: dict[str, Any]
) -> dict[str, Any]:
    return c34c.configure_body(
        template,
        int(profile.get("sample_rate_msps") or 160),
        str(profile.get("mode") or "spec_only"),
        float(profile.get("center_mhz") or 1020.0),
        bitstream_id=bitstream_id,
    )


def restore_production(
    args: argparse.Namespace,
    template: dict[str, Any],
    original_board: dict[str, Any] | None,
    original_receiver: dict[str, Any] | None,
) -> dict[str, Any]:
    evidence: dict[str, Any] = {"errors": []}
    try:
        remote_sudo(
            args.board_ssh,
            f"systemctl stop {AGENT_UNIT} {WATCHDOG_UNIT} >/dev/null 2>&1 || true",
        )
        remote_sudo(args.board_ssh, "systemctl start t510-agent.service")
        wait_agent(args.agent_base)
        profile = (original_board or {}).get("profile") or {
            "sample_rate_msps": 160,
            "mode": "spec_only",
            "center_mhz": 1020.0,
        }
        evidence["configure"] = fullband._http_json(
            args.agent_base.rstrip("/") + "/api/v2/configure",
            method="POST",
            body=configure_body(template, PRODUCTION_ID, profile),
            timeout=240.0,
        )
        remote_sudo(args.board_ssh, "systemctl start t510-ref-watchdog.service")
        if original_receiver is not None and isinstance(original_receiver.get("config"), dict):
            evidence["receiver_restore"] = fullband._http_json(
                args.receiver_base.rstrip("/") + "/api/config",
                method="POST",
                body=original_receiver["config"],
            )
        evidence["mute_errors"] = c34c.stop_and_mute(
            args, float(profile.get("center_mhz") or 1020.0)
        )
        if evidence["mute_errors"]:
            evidence["errors"].extend(evidence["mute_errors"])
        evidence["status"] = wait_agent(args.agent_base, core_version=PRODUCTION_CORE)
        status = evidence["status"]
        dac = status.get("dac", {})
        if status.get("streaming") or status.get("pipeline", {}).get("stream_accepting"):
            evidence["errors"].append("production restore remains streaming")
        if int(dac.get("enable_mask", -1)) != 0 or any(
            int(row.get("amplitude_code", -1)) != 0 for row in dac.get("channels", [])
        ):
            evidence["errors"].append("production restore DAC is not all-zero")
    except Exception as exc:  # noqa: BLE001 - preserve complete restoration evidence
        evidence["errors"].append(f"{type(exc).__name__}: {exc}")
    evidence["restored"] = not evidence["errors"]
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent-base", default="http://192.168.100.117:8010")
    parser.add_argument("--receiver-base", default="http://192.168.100.162:8089")
    parser.add_argument("--board-ssh", default="xilinx@192.168.100.117")
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument(
        "--candidate-overlay",
        type=Path,
        default=Path("/run/user/1000/t510-stage34c2r-v35-candidate/overlay"),
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("build/board/latest/evidence/clock_sysref_causality/tics_profiles/manifest.json"),
    )
    parser.add_argument(
        "--configure-template",
        type=Path,
        default=Path("config/t510/configure_320_time_only.example.json"),
    )
    parser.add_argument(
        "--receiver-output",
        type=Path,
        default=Path("build/receiver/latest/evidence/clock_sysref_causality/science_matrix"),
    )
    parser.add_argument(
        "--board-output",
        type=Path,
        default=Path("build/board/latest/evidence/clock_sysref_causality/science_matrix"),
    )
    parser.add_argument("--ssa-confirmed", action="store_true")
    parser.add_argument("--resume-qualified-campaign", type=Path)
    args = parser.parse_args()
    if not args.ssa_confirmed:
        parser.error("--ssa-confirmed is required")
    args.repo = args.repo.resolve()
    args.candidate_overlay = args.candidate_overlay.resolve()
    args.manifest = args.manifest.resolve()
    args.configure_template = args.configure_template.resolve()
    args.receiver_output = args.receiver_output.resolve()
    args.board_output = args.board_output.resolve()
    if args.resume_qualified_campaign is not None:
        args.resume_qualified_campaign = args.resume_qualified_campaign.resolve()
    runner_path = args.board_output / "runner.json"
    if runner_path.exists() or (args.receiver_output / "campaign.json").exists():
        raise RuntimeError("refusing to overwrite existing v35 science evidence")
    args.board_output.mkdir(parents=True, exist_ok=True)
    state: dict[str, Any] = {
        "stage": "34c-2R",
        "classification": "V35_SCIENCE_RUNNER_IN_PROGRESS",
        "operational_ok": False,
        "candidate_core_version": CANDIDATE_CORE,
        "candidate_bitstream_sha256": CANDIDATE_SHA256,
        "tics_manifest_sha256": TICS_MANIFEST_SHA256,
        "errors": [],
        "started_at_unix_ms": time.time_ns() // 1_000_000,
    }
    write_json(runner_path, state)
    template = json.loads(args.configure_template.read_text())
    original_board: dict[str, Any] | None = None
    original_receiver: dict[str, Any] | None = None
    exit_code = 1
    try:
        original_board = fullband._http_json(
            args.agent_base.rstrip("/") + "/api/v2/status", timeout=30.0
        )
        original_receiver = fullband._http_json(
            args.receiver_base.rstrip("/") + "/api/state"
        )
        state["original_board"] = original_board
        state["original_receiver_config"] = original_receiver.get("config")
        state["predeploy_mute_errors"] = c34c.stop_and_mute(
            args,
            float((original_board.get("profile") or {}).get("center_mhz") or 1020.0),
        )
        if state["predeploy_mute_errors"]:
            raise RuntimeError(f"predeploy STOP/DAC mute failed: {state['predeploy_mute_errors']}")
        with tempfile.TemporaryDirectory(prefix="t510-stage34c2r-v35-science-") as temporary:
            bundle = Path(temporary) / "bundle"
            build_bundle(args, bundle)
            state["bundle"] = {
                "candidate_bitstream_sha256": sha256_file(bundle / "overlay/t510_fengine.bit"),
                "agent_sha256": sha256_file(bundle / "bin/t510-board-agent"),
                "manifest_sha256": sha256_file(bundle / "profiles/manifest.json"),
            }
            write_json(runner_path, state)
            deploy_candidate(args, bundle)
        state["candidate_deployed"] = True
        write_json(runner_path, state)
        command = [
            sys.executable,
            "-u",
            str(args.repo / "scripts/stage-34/t510_clock_sysref_causality.py"),
            "--agent-base",
            args.agent_base,
            "--receiver-base",
            args.receiver_base,
            "--configure-template",
            str(args.configure_template),
            "--receiver-output",
            str(args.receiver_output),
            "--board-output",
            str(args.board_output),
            "--ssa-confirmed",
        ]
        if args.resume_qualified_campaign is not None:
            command.extend(
                ["--resume-qualified-campaign", str(args.resume_qualified_campaign)]
            )
        completed = subprocess.run(command, check=False)
        state["science_exit_code"] = completed.returncode
        if completed.returncode:
            raise RuntimeError(f"science campaign exited {completed.returncode}")
        state["classification"] = "V35_SCIENCE_CAMPAIGN_COMPLETE"
        state["operational_ok"] = True
        exit_code = 0
    except Exception as exc:  # noqa: BLE001 - top-level long-task evidence
        state["errors"].append(f"{type(exc).__name__}: {exc}")
        state["classification"] = "V35_SCIENCE_RUNNER_OPERATIONAL_FAIL"
    finally:
        state["production_restore"] = restore_production(
            args, template, original_board, original_receiver
        )
        if not state["production_restore"].get("restored"):
            state["errors"].extend(state["production_restore"].get("errors", []))
            state["operational_ok"] = False
            state["classification"] = "V35_SCIENCE_RUNNER_OPERATIONAL_FAIL"
            exit_code = 1
        state["finished_at_unix_ms"] = time.time_ns() // 1_000_000
        write_json(runner_path, state)
    print(json.dumps({
        "classification": state["classification"],
        "operational_ok": state["operational_ok"],
        "runner": str(runner_path),
        "errors": state["errors"],
    }, indent=2), flush=True)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
