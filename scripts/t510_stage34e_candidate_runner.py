#!/usr/bin/env python3
"""Deploy isolated v36, run Stage 34e open-input diagnostics, restore production v34."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import t510_adc_correlated_noise_campaign as c34c
from scripts import t510_fullband_spur_scan as fullband


BOARD_ID = 1
CANDIDATE_CORE = "0x00010036"
CANDIDATE_ID = "fengine-0x00010036"
PRODUCTION_CORE = "0x00010034"
PRODUCTION_ID = "fengine-0x00010034"
TICS_MANIFEST_SHA256 = "695308db629e6223ec2d9ef19c9c07cb0ebd231b5b18f8632a964c6210d17009"
REMOTE_ROOT = "/run/t510-stage34e-v36-agent"
AGENT_UNIT = "t510-stage34e-v36-agent.service"
WATCHDOG_UNIT = "t510-stage34e-v36-watchdog.service"
CAMPAIGN_UNIT = "t510-stage34e-v36-open-input.service"


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
        "ssh", "-F", "/dev/null", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
        "-o", "StrictHostKeyChecking=no", host,
    ]


def remote(host: str, command: str, timeout: float = 90.0) -> str:
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


def remote_sudo(host: str, command: str, timeout: float = 90.0) -> str:
    # The lab PYNQ image deliberately retains its documented default account.
    return remote(
        host,
        "printf '%s\\n' xilinx | sudo -S sh -c " + shlex.quote(command),
        timeout=timeout,
    )


def wait_agent(agent_base: str, core_version: str | None = None) -> dict[str, Any]:
    deadline = time.monotonic() + 60.0
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            fullband._http_json(agent_base.rstrip("/") + "/api/v2/capabilities", timeout=4.0)
            status = fullband._http_json(agent_base.rstrip("/") + "/api/v2/status", timeout=15.0)
            if core_version is None or str(status.get("core_version", "")).lower() == core_version:
                return status
        except Exception as exc:
            last_error = exc
        time.sleep(1.0)
    raise RuntimeError(f"Board Agent did not become ready: {last_error}")


def candidate_config(bit_sha256: str) -> dict[str, Any]:
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
                "sha256": bit_sha256,
                "core_version": CANDIDATE_CORE,
                # Open-input is an engineering diagnostic.  Every CONFIGURE
                # uses MTS discovery; v36 formal fixed targets are intentionally
                # withheld until the registered 40/40 qualification.
                "mts_adc_target_latency": -1,
                "mts_dac_target_latency": -1,
                "profiles": [
                    {"sample_rate_msps": 160, "modes": ["time_only", "spec_only", "time_spec"]},
                    {"sample_rate_msps": 320, "modes": ["time_only", "spec_only"]},
                ],
            }
        ],
    }


def build_bundle(args: argparse.Namespace, root: Path) -> dict[str, str]:
    bit = args.candidate_overlay / "t510_fengine.bit"
    hwh = args.candidate_overlay / "t510_fengine.hwh"
    agent = args.repo / "rust/t510_board_agent/target/aarch64-unknown-linux-musl/release/t510-board-agent"
    sources = {
        agent: root / "bin/t510-board-agent",
        bit: root / "overlay/t510_fengine.bit",
        hwh: root / "overlay/t510_fengine.hwh",
        args.clock_manifest: root / "profiles/manifest.json",
    }
    for name in (
        "__init__.py", "packet.py", "t510_ams.py", "t510_clock.py", "t510_control.py",
        "t510_fengine.py", "t510_hw.py", "t510_ref_watchdog.py", "t510_spur_correction.py",
    ):
        sources[args.repo / "python" / name] = root / "python" / name
    for source, destination in sources.items():
        if not source.is_file():
            raise RuntimeError(f"candidate bundle source is missing: {source}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    if sha256_file(root / "profiles/manifest.json") != TICS_MANIFEST_SHA256:
        raise RuntimeError("production TICS manifest SHA256 mismatch")
    bit_sha = sha256_file(root / "overlay/t510_fengine.bit")
    export_manifest = args.candidate_overlay / "t510_fengine.manifest.txt"
    if export_manifest.is_file():
        fields = dict(
            line.split("=", 1)
            for line in export_manifest.read_text().splitlines()
            if "=" in line
        )
        if fields.get("core_version") != CANDIDATE_CORE or fields.get("bit_sha256") != bit_sha:
            raise RuntimeError(f"candidate export identity mismatch: {fields}")
    write_json(root / "config.json", candidate_config(bit_sha))
    return {
        "bitstream_sha256": bit_sha,
        "agent_sha256": sha256_file(root / "bin/t510-board-agent"),
        "clock_manifest_sha256": sha256_file(root / "profiles/manifest.json"),
    }


def deploy_candidate(args: argparse.Namespace, bundle: Path) -> None:
    upload = "/tmp/t510-stage34e-v36-upload"
    remote_sudo(
        args.board_ssh,
        f"systemctl stop {AGENT_UNIT} {WATCHDOG_UNIT} t510-agent.service t510-ref-watchdog.service >/dev/null 2>&1 || true",
    )
    remote_sudo(
        args.board_ssh,
        f"rm -rf -- {upload} {REMOTE_ROOT} && install -d -o xilinx -g xilinx -m 0755 {upload} && install -d -o root -g root -m 0755 {REMOTE_ROOT}",
    )
    subprocess.run(
        [
            "scp", "-F", "/dev/null", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
            "-o", "StrictHostKeyChecking=no", "-r", f"{bundle}/.", f"{args.board_ssh}:{upload}/",
        ],
        check=True,
        timeout=180.0,
    )
    remote_sudo(
        args.board_ssh,
        f"cp -a {upload}/. {REMOTE_ROOT}/ && chmod 0755 {REMOTE_ROOT}/bin/t510-board-agent && rm -rf -- {upload}",
    )
    common = (
        "--property=User=root --property=Group=root --property=Restart=no "
        "--property=NoNewPrivileges=true --property=PrivateTmp=true "
        "--property=ProtectKernelModules=true --property=ProtectControlGroups=true"
    )
    manifest_remote = f"{REMOTE_ROOT}/profiles/manifest.json"
    remote_sudo(
        args.board_ssh,
        "systemd-run "
        f"--unit={AGENT_UNIT.removesuffix('.service')} {common} --working-directory={REMOTE_ROOT} "
        "--setenv=RUST_LOG=info --setenv=PYTHONDONTWRITEBYTECODE=1 --setenv=PYTHONUNBUFFERED=1 "
        f"--setenv=XILINX_XRT=/usr --setenv=T510_CLOCK_DIAGNOSTIC_PROFILE_MANIFEST={manifest_remote} "
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


def start_candidate_watchdog(args: argparse.Namespace) -> None:
    """Start the v36 watchdog only after v36 is the proven active bitstream.

    The candidate Agent must be available before CONFIGURE, but the watchdog
    must not inspect hardware while PYNQ still records the production v34
    image.  Keeping these two steps separate preserves the active-bitstream
    identity gate instead of weakening it for the deployment transition.
    """
    remote_sudo(
        args.board_ssh,
        f"systemctl stop {WATCHDOG_UNIT} >/dev/null 2>&1 || true",
    )
    common = (
        "--property=User=root --property=Group=root --property=Restart=no "
        "--property=NoNewPrivileges=true --property=PrivateTmp=true "
        "--property=ProtectKernelModules=true --property=ProtectControlGroups=true"
    )
    manifest_remote = f"{REMOTE_ROOT}/profiles/manifest.json"
    remote_sudo(
        args.board_ssh,
        "systemd-run "
        f"--unit={WATCHDOG_UNIT.removesuffix('.service')} {common} --working-directory={REMOTE_ROOT} "
        f"--setenv=PYTHONPATH={REMOTE_ROOT} --setenv=PYTHONDONTWRITEBYTECODE=1 --setenv=PYTHONUNBUFFERED=1 "
        f"--setenv=XILINX_XRT=/usr --setenv=T510_CLOCK_DIAGNOSTIC_PROFILE_MANIFEST={manifest_remote} "
        f"--setenv=T510_CLOCK_DIAGNOSTIC_PROFILE_MANIFEST_SHA256={TICS_MANIFEST_SHA256} "
        f"/usr/local/share/pynq-venv/bin/python3 {REMOTE_ROOT}/python/t510_ref_watchdog.py "
        f"--bitfile {REMOTE_ROOT}/overlay/t510_fengine.bit --state /run/t510-ref-watchdog.json "
        "--lock /run/t510-ref-watchdog.lock --configure-lock /run/t510-configure.lock "
        "--clock-diagnostic-state /run/t510-clock-diagnostic.json --spur-correction-state /run/t510-spur-correction.json "
        "--expected-core-version 0x00010036 --interval-ms 200 --unlock-confirmations 2 "
        "--spi-error-confirmations 5 --stop-timeout-ms 2000",
    )


def configure_body(template: dict[str, Any], bitstream_id: str, profile: dict[str, Any]) -> dict[str, Any]:
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
        remote_sudo(args.board_ssh, f"systemctl stop {AGENT_UNIT} {WATCHDOG_UNIT} >/dev/null 2>&1 || true")
        remote_sudo(args.board_ssh, "systemctl start t510-agent.service")
        wait_agent(args.agent_base)
        profile = (original_board or {}).get("profile") or {
            "sample_rate_msps": 160, "mode": "spec_only", "center_mhz": 1020.0,
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
        evidence["mute_errors"] = c34c.stop_and_mute(args, float(profile.get("center_mhz") or 1020.0))
        evidence["errors"].extend(evidence["mute_errors"])
        evidence["status"] = wait_agent(args.agent_base, PRODUCTION_CORE)
        status = evidence["status"]
        dac = status.get("dac", {})
        if status.get("streaming") or status.get("pipeline", {}).get("stream_accepting"):
            evidence["errors"].append("production restore remains streaming")
        if int(dac.get("enable_mask", -1)) != 0 or any(
            int(row.get("amplitude_code", -1)) != 0 for row in dac.get("channels", [])
        ):
            evidence["errors"].append("production restore DAC is not all-zero")
    except Exception as exc:
        evidence["errors"].append(f"{type(exc).__name__}: {exc}")
    evidence["restored"] = not evidence["errors"]
    return evidence


def submit_systemd(args: argparse.Namespace) -> int:
    command = [
        "systemd-run", "--user", f"--unit={CAMPAIGN_UNIT.removesuffix('.service')}",
        "--property=Restart=no", f"--working-directory={args.repo}", sys.executable,
        str(Path(__file__).resolve()), "--all-open-confirmed", "--agent-base", args.agent_base,
        "--receiver-base", args.receiver_base, "--board-ssh", args.board_ssh, "--repo", str(args.repo),
        "--candidate-overlay", str(args.candidate_overlay), "--clock-manifest", str(args.clock_manifest),
        "--configure-template", str(args.configure_template), "--receiver-output", str(args.receiver_output),
        "--board-output", str(args.board_output),
    ]
    subprocess.run(command, check=True)
    deadline = time.monotonic() + 20.0
    while time.monotonic() < deadline:
        shown = subprocess.run(
            ["systemctl", "--user", "show", CAMPAIGN_UNIT, "--property=ActiveState,SubState,ExecMainStatus"],
            check=True, capture_output=True, text=True,
        )
        state = dict(line.split("=", 1) for line in shown.stdout.splitlines() if "=" in line)
        if state.get("ActiveState") == "active" and state.get("SubState") == "running":
            print(json.dumps({"submitted": True, "unit": CAMPAIGN_UNIT, "state": state}, indent=2))
            return 0
        if state.get("ActiveState") == "failed":
            raise RuntimeError(f"candidate runner failed during startup: {state}")
        time.sleep(1.0)
    raise RuntimeError(f"candidate runner did not enter running state: {CAMPAIGN_UNIT}")


def run(args: argparse.Namespace) -> int:
    runner_path = args.board_output / "candidate_runner.json"
    if runner_path.exists() or (args.receiver_output / "campaign.json").exists():
        raise RuntimeError("refusing to overwrite existing Stage 34e evidence")
    args.board_output.mkdir(parents=True, exist_ok=True)
    state: dict[str, Any] = {
        "stage": "34e", "classification": "V36_OPEN_INPUT_RUNNER_IN_PROGRESS",
        "operational_ok": False, "candidate_core": CANDIDATE_CORE,
        "input_state": "OPEN_INPUT_DIAGNOSTIC", "errors": [],
        "started_at_unix_ms": time.time_ns() // 1_000_000,
    }
    write_json(runner_path, state)
    template = json.loads(args.configure_template.read_text())
    original_board = None
    original_receiver = None
    exit_code = 1
    try:
        original_board = fullband._http_json(args.agent_base.rstrip("/") + "/api/v2/status")
        original_receiver = fullband._http_json(args.receiver_base.rstrip("/") + "/api/state")
        state["original_board"] = original_board
        state["original_receiver_config"] = original_receiver.get("config")
        mute_errors = c34c.stop_and_mute(
            args, float((original_board.get("profile") or {}).get("center_mhz") or 1020.0)
        )
        if mute_errors:
            raise RuntimeError(f"predeploy STOP/DAC mute failed: {mute_errors}")
        with tempfile.TemporaryDirectory(prefix="t510-stage34e-v36-") as temporary:
            bundle = Path(temporary) / "bundle"
            state["bundle"] = build_bundle(args, bundle)
            write_json(runner_path, state)
            deploy_candidate(args, bundle)
        state["candidate_deployed"] = True
        bootstrap_profile = {
            "sample_rate_msps": 160,
            "mode": "spec_only",
            "center_mhz": 420.0,
        }
        state["candidate_bootstrap_configure"] = fullband._http_json(
            args.agent_base.rstrip("/") + "/api/v2/configure",
            method="POST",
            body=configure_body(template, CANDIDATE_ID, bootstrap_profile),
            timeout=240.0,
        )
        state["candidate_bootstrap_status"] = wait_agent(
            args.agent_base, CANDIDATE_CORE
        )
        start_candidate_watchdog(args)
        write_json(runner_path, state)
        command = [
            sys.executable, "-u", str(args.repo / "scripts/t510_adc_interleave_spur_diagnostic.py"),
            "--agent-base", args.agent_base, "--receiver-base", args.receiver_base,
            "--configure-template", str(args.configure_template), "--board-output", str(args.board_output),
            "--receiver-output", str(args.receiver_output),
        ]
        completed = subprocess.run(command, check=False)
        state["campaign_exit_code"] = completed.returncode
        if completed.returncode:
            raise RuntimeError(f"open-input campaign exited {completed.returncode}")
        state["classification"] = "V36_OPEN_INPUT_DIAGNOSTIC_COMPLETE"
        state["operational_ok"] = True
        exit_code = 0
    except Exception as exc:
        state["errors"].append(f"{type(exc).__name__}: {exc}")
        state["classification"] = "V36_OPEN_INPUT_RUNNER_OPERATIONAL_FAIL"
    finally:
        state["production_restore"] = restore_production(
            args, template, original_board, original_receiver
        )
        if not state["production_restore"].get("restored"):
            state["errors"].extend(state["production_restore"].get("errors", []))
            state["operational_ok"] = False
            state["classification"] = "V36_OPEN_INPUT_RUNNER_OPERATIONAL_FAIL"
            exit_code = 1
        state["finished_at_unix_ms"] = time.time_ns() // 1_000_000
        write_json(runner_path, state)
    print(json.dumps({"classification": state["classification"], "operational_ok": state["operational_ok"], "errors": state["errors"]}, indent=2))
    return exit_code


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent-base", default="http://192.168.100.117:8010")
    parser.add_argument("--receiver-base", default="http://192.168.100.162:8089")
    parser.add_argument("--board-ssh", default="xilinx@192.168.100.117")
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--candidate-overlay", type=Path, default=Path("build/board/latest/evidence/adc_interleave_spur_correction/bitstream/overlay"))
    parser.add_argument("--clock-manifest", type=Path, default=Path("build/board/latest/evidence/clock_sysref_causality/tics_profiles/manifest.json"))
    parser.add_argument("--configure-template", type=Path, default=Path("config/t510/configure_320_time_only.example.json"))
    parser.add_argument("--receiver-output", type=Path, default=Path("build/receiver/latest/evidence/adc_interleave_spur_correction"))
    parser.add_argument("--board-output", type=Path, default=Path("build/board/latest/evidence/adc_interleave_spur_correction"))
    parser.add_argument("--all-open-confirmed", action="store_true")
    parser.add_argument("--submit-systemd", action="store_true")
    args = parser.parse_args()
    if not args.all_open_confirmed:
        parser.error("--all-open-confirmed is required for the physical open-input diagnostic")
    for name in ("repo", "candidate_overlay", "clock_manifest", "configure_template", "receiver_output", "board_output"):
        setattr(args, name, getattr(args, name).resolve())
    return submit_systemd(args) if args.submit_systemd else run(args)


if __name__ == "__main__":
    raise SystemExit(main())
