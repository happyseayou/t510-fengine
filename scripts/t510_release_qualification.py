#!/usr/bin/env python3
"""Run the current T510 reference qualification as one fail-fast queue."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import time
import traceback
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
MODES = ((160, "time_only"), (160, "spec_only"), (160, "time_spec"),
         (320, "time_only"), (320, "spec_only"))
SCHEDULED_PPS_LEAD = 30
BOARD_PYTHON = "/usr/local/share/pynq-venv/bin/python3"


def sha256(path: Path) -> str:
    with path.open("rb") as handle:
        digest = hashlib.sha256()
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
        return digest.hexdigest()


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


class QualificationQueue:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.evidence = args.evidence.resolve()
        self.package = args.package.resolve()
        self.board_host = getattr(args, "board_ssh", "xilinx@192.168.100.117")
        self.receiver_host = getattr(args, "receiver_ssh", "astrolab@192.168.100.162")
        self.remote_package = f"/home/xilinx/.cache/t510/{args.queue_id}"
        self.remote_evidence = f"{self.remote_package}/evidence"
        self.receiver_root = f"/var/lib/t510/measurements/qualification/{args.queue_id}"
        self.reuse_discovery = getattr(args, "reuse_discovery", None)
        self.reuse_fixed = getattr(args, "reuse_fixed", None)
        self.reuse_matrix_dir = getattr(args, "reuse_matrix_dir", None)
        self.args.reference = getattr(args, "reference", "onboard_tcxo")
        self.args.agent_base = getattr(args, "agent_base", "http://192.168.100.117:8010")
        self.clock_ref = "tcxo_10mhz" if self.args.reference == "onboard_tcxo" else "external_10mhz"
        phases = ["preflight", "mts_discovery_40", "mts_fixed_40", "catalog_install",
                  "matrix_160_time_only", "matrix_160_spec_only", "matrix_160_time_spec",
                  "matrix_320_time_only", "matrix_320_spec_only"]
        if self.args.reference == "external_10mhz":
            phases.append("scheduled_pps")
        self.state = {
            "schema_version": 1, "queue_id": args.queue_id, "reference": self.args.reference,
            "status": "armed", "phases": phases, "completed": [], "hardware_owned": False,
            "created_unix_s": time.time(),
        }

    def save(self, **fields: object) -> None:
        self.state.update(fields, updated_unix_s=time.time())
        atomic_json(self.evidence / "queue-state.json", self.state)

    def command(self, name: str, argv: list[str], *, sudo: bool = False,
                timeout: float = 7200) -> None:
        self.save(current_command=name)
        with (self.evidence / f"{name}.log").open("x", encoding="utf-8") as log:
            result = subprocess.run(
                argv, input=(os.environ["PYNQ_SUDO_PASSWORD"] + "\n") if sudo else None,
                text=True, stdout=log, stderr=subprocess.STDOUT, timeout=timeout,
            )
        if result.returncode:
            raise RuntimeError(f"{name} returned {result.returncode}; see {name}.log")

    def remote(self, name: str, argv: list[str], *, host: str | None = None,
               sudo: bool = False, timeout: float = 7200) -> None:
        target = host or self.board_host
        remote_argv = (["sudo", "-S", "-p", ""] if sudo else []) + [str(x) for x in argv]
        self.command(name, ["ssh", "-o", "BatchMode=yes", target, shlex.join(remote_argv)],
                     sudo=sudo, timeout=timeout)

    def http(self, path: str, body: dict | None = None) -> dict:
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(
            self.args.agent_base.rstrip("/") + path, data=data,
            headers={} if data is None else {"Content-Type": "application/json"},
            method="GET" if data is None else "POST",
        )
        with urllib.request.urlopen(request, timeout=300) as response:
            value = json.load(response)
        return dict(value.get("result", value))

    def validate_package(self) -> dict:
        required = [
            "bin/t510-board-agent", "overlay/t510_fengine.bit", "overlay/t510_fengine.hwh",
            "config/config.example.json", "config/current_release.json",
            "config/qualification-template.json", "deploy/install-on-board.sh",
            "scripts/pynq_t510_mts_campaign.py", "scripts/t510_finalize_catalog.py",
            "scripts/t510_board_host_gate.py", "scripts/t510_host_validate.py",
            "scripts/t510_multiboard_sync.py", "scripts/t510_scheduled_pps_gate.py",
        ]
        missing = [name for name in required if not (self.package / name).is_file()]
        if missing:
            raise RuntimeError(f"qualification package is incomplete: {missing}")
        completed = subprocess.run(
            [sys.executable, str(ROOT / "scripts/t510_current_release.py"),
             "--metadata", str(self.package / "config/current_release.json"),
             "--catalog", str(self.package / "config/config.example.json"),
             "--bitstream", str(self.package / "overlay/t510_fengine.bit"),
             "--allow-unqualified"], capture_output=True, text=True,
        )
        if completed.returncode:
            raise RuntimeError(completed.stderr.strip() or "current release validation failed")
        metadata = json.loads((self.package / "config/current_release.json").read_text())
        self.state["bitstream_sha256"] = sha256(self.package / "overlay/t510_fengine.bit")
        self.state["core_version"] = metadata["core_version"]
        return metadata

    def plan(self) -> dict:
        metadata = self.validate_package()
        commands = [
            {"phase": "preflight", "reference": self.args.reference},
            {"phase": "mts_discovery_40", "clock_ref": self.clock_ref,
             "initialize_clock": self.args.reference == "external_10mhz"},
            {"phase": "mts_fixed_40", "clock_ref": self.clock_ref},
            {"phase": "catalog_install", "reference": self.args.reference},
            *({"phase": f"matrix_{rate}_{mode}", "seconds": 60} for rate, mode in MODES),
        ]
        if self.args.reference == "external_10mhz":
            commands.append({"phase": "scheduled_pps", "mode": "160_time_spec",
                             "lead_pps": SCHEDULED_PPS_LEAD, "seconds": 10})
        return {"status": "DRY_RUN_PASS", "reference": self.args.reference,
                "metadata": metadata, "evidence": str(self.evidence), "commands": commands}

    def safe_failure(self) -> list[str]:
        errors: list[str] = []
        stop_error: str | None = None
        try:
            self.http("/api/v2/stop", {"reason": "release_qualification_failure",
                      "expected_board_id": 1, "sample_rate_msps": 160,
                      "mode": "time_only", "center_mhz": 200.0})
        except Exception as exc:
            stop_error = f"stop: {exc}"
        try:
            self.remote("failure_mute", ["env", "XILINX_XRT=/usr",
                f"PYTHONPATH={self.remote_package}", BOARD_PYTHON, "-c",
                "from python.t510_control import FEngineController; c=FEngineController('/opt/t510-agent/current/overlay/t510_fengine.bit'); c.connect(download=False); x=c.require_core(); x.stop(); x.set_dac_enable_mask(0); s=x.read_status(); d=x.read_dac_channels(); assert not s['streaming'] and d['enable_mask'] == 0"],
                sudo=True, timeout=60)
        except Exception as exc:
            if stop_error is not None:
                errors.append(stop_error)
            errors.append(f"mute: {exc}")
        return errors

    def validated_reuse_discovery(self) -> tuple[Path, dict] | None:
        if self.reuse_discovery is None:
            return None
        source = Path(self.reuse_discovery).resolve(strict=True)
        report = json.loads(source.read_text(encoding="utf-8"))
        checks = {
            "ok": report.get("ok") is True,
            "classification": report.get("classification") == "T510_MTS_DISCOVERY_PASS",
            "completed_cycles": int(report.get("completed_cycles", 0)) == 40,
            "clock_ref": report.get("clock_ref") == self.clock_ref,
            "bitstream_sha256": report.get("bitstream_sha256") == self.state.get("bitstream_sha256"),
            "core_version": report.get("core_version") == self.state.get("core_version"),
        }
        if not all(checks.values()):
            raise RuntimeError(f"reused discovery evidence failed validation: {checks}")
        return source, report

    def validated_reuse_fixed(
        self, discovery: tuple[Path, dict] | None
    ) -> tuple[Path, dict] | None:
        if self.reuse_fixed is None:
            return None
        if discovery is None:
            raise RuntimeError("--reuse-fixed requires --reuse-discovery")
        source = Path(self.reuse_fixed).resolve(strict=True)
        report = json.loads(source.read_text(encoding="utf-8"))
        expected_targets = discovery[1].get("recommended_fixed_targets")
        checks = {
            "ok": report.get("ok") is True,
            "classification": report.get("classification") == "T510_MTS_FIXED_PASS",
            "completed_cycles": int(report.get("completed_cycles", 0)) == 40,
            "clock_ref": report.get("clock_ref") == self.clock_ref,
            "bitstream_sha256": report.get("bitstream_sha256") == self.state.get("bitstream_sha256"),
            "core_version": report.get("core_version") == self.state.get("core_version"),
            "targets": report.get("targets") == expected_targets,
            "repeatability": report.get("fixed_repeatability", {}).get("ok") is True,
        }
        if not all(checks.values()):
            raise RuntimeError(f"reused fixed evidence failed validation: {checks}")
        return source, report

    def validated_reuse_matrix(self) -> dict[str, tuple[Path, dict]] | None:
        if self.reuse_matrix_dir is None:
            return None
        source_dir = Path(self.reuse_matrix_dir).resolve(strict=True)
        proofs: dict[str, tuple[Path, dict]] = {}
        for rate, mode in MODES:
            label = f"{rate}_{mode}"
            source = source_dir / f"{label}_gate.json"
            report = json.loads(source.read_text(encoding="utf-8"))
            idle = report.get("board_idle", {})
            clock = idle.get("clock", {})
            checks = {
                "ok": report.get("ok") is True,
                "classification": report.get("classification") == (
                    f"T510_{rate}MSPS_{mode.upper()}_BOARD_HOST_PASS"
                ),
                "sample_rate": int(report.get("sample_rate_msps", 0)) == rate,
                "mode": report.get("mode") == mode,
                "duration": float(report.get("seconds", 0)) >= 60.0,
                "errors": report.get("errors") == [],
                "core_version": idle.get("core_version") == self.state.get("core_version"),
                "clock_reference": clock.get("clock_reference") == (
                    "onboard_tcxo" if self.args.reference == "onboard_tcxo" else "external_gpsdo"
                ),
            }
            if not all(checks.values()):
                raise RuntimeError(f"reused matrix evidence {label} failed validation: {checks}")
            proofs[label] = (source, report)
        return proofs

    def run(self) -> None:
        self.evidence.mkdir(parents=True, exist_ok=True)
        state_path = self.evidence / "queue-state.json"
        if state_path.exists():
            raise RuntimeError("qualification evidence already exists; inspect it instead of resubmitting")
        with (self.evidence / "queue.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.save(status="running", phase="preflight")
            try:
                self.validate_package()
                reused = self.validated_reuse_discovery()
                reused_fixed = self.validated_reuse_fixed(reused)
                reused_matrix = self.validated_reuse_matrix()
                before = self.http("/api/v2/status")
                atomic_json(self.evidence / "board-before.json", before)
                if before.get("streaming") or int(before.get("dac", {}).get("enable_mask", -1)) != 0:
                    raise RuntimeError("board must be stopped with DAC muted")
                self.command("stage_board", ["rsync", "-a", "--delete", f"{self.package}/",
                                             f"{self.board_host}:{self.remote_package}/"], timeout=300)
                self.remote("board_evidence_directory", ["mkdir", "-p", self.remote_evidence],
                            timeout=30)
                self.remote("receiver_directory", ["mkdir", "-p", self.receiver_root],
                            host=self.receiver_host, timeout=30)
                self.command("stage_receiver_validator", ["scp",
                    str(self.package / "scripts/t510_host_validate.py"),
                    f"{self.receiver_host}:{self.receiver_root}/t510_host_validate.py"], timeout=60)
                self.remote("services_stop", ["systemctl", "stop", "t510-agent.service",
                            "t510-ref-watchdog.service"], sudo=True, timeout=60)
                self.state["hardware_owned"] = True
                self.state["completed"].append("preflight"); self.save()

                phases = ("discovery", "fixed")
                if reused is not None:
                    source, report = reused
                    local_discovery = self.evidence / "mts_discovery.json"
                    shutil.copy2(source, local_discovery)
                    self.command("stage_reused_discovery", ["scp", str(local_discovery),
                        f"{self.board_host}:{self.remote_evidence}/mts_discovery.json"], timeout=60)
                    self.state["completed"].append("mts_discovery_40")
                    self.save(reused_discovery={"source": str(source), "sha256": sha256(source),
                              "targets": report.get("recommended_fixed_targets")})
                    phases = ("fixed",)
                if reused_fixed is not None:
                    source, report = reused_fixed
                    local_fixed = self.evidence / "mts_fixed.json"
                    shutil.copy2(source, local_fixed)
                    self.command("stage_reused_fixed", ["scp", str(local_fixed),
                        f"{self.board_host}:{self.remote_evidence}/mts_fixed.json"], timeout=60)
                    self.state["completed"].append("mts_fixed_40")
                    self.save(reused_fixed={"source": str(source), "sha256": sha256(source),
                              "targets": report.get("targets")})
                    phases = ()

                for phase in phases:
                    label = f"mts_{phase}_40"; self.save(phase=label)
                    remote_output = f"{self.remote_evidence}/mts_{phase}.json"
                    argv = ["env", "XILINX_XRT=/usr", "PYTHONDONTWRITEBYTECODE=1", BOARD_PYTHON,
                            f"{self.remote_package}/scripts/pynq_t510_mts_campaign.py",
                            "--phase", phase, "--bitfile", f"{self.remote_package}/overlay/t510_fengine.bit",
                            "--center-mhz", "200", "--clock-ref", self.clock_ref,
                            "--lmk-settle-seconds", "3", "--output", remote_output]
                    if phase == "discovery" and self.args.reference == "external_10mhz":
                        argv.append("--initialize-clock")
                    if phase == "fixed":
                        argv += ["--discovery-json", f"{self.remote_evidence}/mts_discovery.json"]
                    self.remote(label, argv, sudo=True)
                    self.command(f"copy_{label}", ["scp", f"{self.board_host}:{remote_output}",
                                                   str(self.evidence / f"mts_{phase}.json")])
                    report = json.loads((self.evidence / f"mts_{phase}.json").read_text())
                    if not report.get("ok") or int(report.get("completed_cycles", 0)) != 40:
                        raise RuntimeError(f"{label} did not pass all 40 cycles")
                    self.state["completed"].append(label); self.save()

                self.save(phase="catalog_install")
                self.command("catalog_finalize", [sys.executable,
                    str(self.package / "scripts/t510_finalize_catalog.py"),
                    "--reference", self.args.reference,
                    "--metadata", str(self.package / "config/current_release.json"),
                    "--bitstream", str(self.package / "overlay/t510_fengine.bit"),
                    "--discovery-json", str(self.evidence / "mts_discovery.json"),
                    "--fixed-json", str(self.evidence / "mts_fixed.json"),
                    "--catalog", str(self.package / "config/config.example.json")])
                self.command("restage_board", ["rsync", "-a", "--delete", f"{self.package}/",
                                               f"{self.board_host}:{self.remote_package}/"], timeout=300)
                self.remote("install", ["bash", f"{self.remote_package}/deploy/install-on-board.sh",
                            self.remote_package], sudo=True, timeout=300)
                self.state["completed"].append("catalog_install"); self.save()

                template = json.loads((self.package / "config/qualification-template.json").read_text())
                if reused_matrix is not None:
                    matrix_hashes = {}
                    for rate, mode in MODES:
                        proof_label = f"{rate}_{mode}"
                        label = f"matrix_{proof_label}"
                        source, _report = reused_matrix[proof_label]
                        shutil.copy2(source, self.evidence / source.name)
                        host_source = source.with_name(source.stem + "_host.json")
                        if host_source.is_file():
                            shutil.copy2(host_source, self.evidence / host_source.name)
                        matrix_hashes[proof_label] = sha256(source)
                        self.state["completed"].append(label)
                    self.save(reused_matrix={"source": str(Path(self.reuse_matrix_dir).resolve()),
                                             "sha256": matrix_hashes})
                else:
                    for rate, mode in MODES:
                        label = f"matrix_{rate}_{mode}"; self.save(phase=label)
                        body = json.loads(json.dumps(template))
                        body["clock_reference"] = self.args.reference
                        body["profile"] = {"sample_rate_msps": rate, "mode": mode, "center_mhz": 200.0}
                        body["update_mode"] = "clock_preserving"
                        body["receiver_stream_accepting"] = False
                        for endpoint in body["endpoints"]:
                            endpoint["enabled"] = ((endpoint["stream"] == "TIME" and mode in ("time_only", "time_spec")) or
                                                   (endpoint["stream"] == "SPEC" and mode in ("spec_only", "time_spec")))
                        atomic_json(self.evidence / f"{rate}_{mode}_configured.json",
                                    self.http("/api/v2/configure", body))
                        self.command(label, [sys.executable, str(self.package / "scripts/t510_board_host_gate.py"),
                            "--sample-rate-msps", str(rate), "--mode", mode, "--seconds", "60",
                            "--reference", self.args.reference,
                            "--metadata", str(self.package / "config/current_release.json"),
                            "--center-mhz", "200", "--remote-validator", f"{self.receiver_root}/t510_host_validate.py",
                            "--remote-output", f"{self.receiver_root}/{rate}_{mode}_host.json",
                            "--output", str(self.evidence / f"{rate}_{mode}_gate.json")], timeout=300)
                        self.state["completed"].append(label); self.save()

                if self.args.reference == "external_10mhz":
                    self.save(phase="scheduled_pps")
                    body = json.loads(json.dumps(template))
                    body["clock_reference"] = self.args.reference
                    body["profile"] = {"sample_rate_msps": 160, "mode": "time_spec", "center_mhz": 200.0}
                    body["update_mode"] = "clock_preserving"
                    body["receiver_stream_accepting"] = False
                    for endpoint in body["endpoints"]:
                        endpoint["enabled"] = endpoint["stream"] in ("TIME", "SPEC")
                    atomic_json(self.evidence / "scheduled_configured.json",
                                self.http("/api/v2/configure", body))
                    generation = int(time.time())
                    self.command("scheduled_pps", [sys.executable,
                        str(self.package / "scripts/t510_scheduled_pps_gate.py"),
                        "--generation", str(generation), "--epoch-tai", str(generation + 37),
                        "--lead-pps", str(SCHEDULED_PPS_LEAD),
                        "--signal-chain-tag", hex(generation & 0xFFFFFFFF or 1),
                        "--remote-validator", f"{self.receiver_root}/t510_host_validate.py",
                        "--remote-output", f"{self.receiver_root}/scheduled_host.json",
                        "--output", str(self.evidence / "scheduled_pps.json")], timeout=180)
                    self.state["completed"].append("scheduled_pps"); self.save()
                shutil.copy2(self.package / "config/config.example.json",
                             ROOT / "config/t510/config.example.json")
                self.save(status="PASS", phase="complete", finished_unix_s=time.time())
            except Exception as exc:
                cleanup_errors = (
                    self.safe_failure() if self.state.get("hardware_owned") else []
                )
                self.save(status="FAIL", error=str(exc), traceback=traceback.format_exc(),
                          cleanup_errors=cleanup_errors, finished_unix_s=time.time())
                raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", choices=("onboard_tcxo", "external_10mhz"), required=True)
    parser.add_argument("--package", type=Path, default=ROOT / "build/board/latest/package")
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--queue-id", default=lambda: time.strftime("qualification-%Y%m%dT%H%M%SZ", time.gmtime()))
    parser.add_argument("--board-ssh", default="xilinx@192.168.100.117")
    parser.add_argument("--receiver-ssh", default="astrolab@192.168.100.162")
    parser.add_argument("--agent-base", default="http://192.168.100.117:8010")
    parser.add_argument("--reuse-discovery", type=Path,
                        help="resume after validating a completed discovery 40/40 result")
    parser.add_argument("--reuse-fixed", type=Path,
                        help="resume after validating matching discovery and fixed 40/40 results")
    parser.add_argument("--reuse-matrix-dir", type=Path,
                        help="resume after validating all five 60-second mode gate results")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    args.queue_id = args.queue_id() if callable(args.queue_id) else args.queue_id
    if not all(character.isalnum() or character in "-_" for character in args.queue_id):
        parser.error("queue id may contain only letters, digits, dash, and underscore")
    if args.evidence is None:
        args.evidence = ROOT / "build/qualification/latest" / args.reference
    if not args.dry_run and not os.environ.get("PYNQ_SUDO_PASSWORD"):
        parser.error("PYNQ_SUDO_PASSWORD is required for hardware qualification")
    return args


def main() -> int:
    args = parse_args()
    queue = QualificationQueue(args)
    if args.dry_run:
        result = queue.plan()
        args.evidence.mkdir(parents=True, exist_ok=True)
        atomic_json(args.evidence / "dry-run.json", result)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    queue.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
