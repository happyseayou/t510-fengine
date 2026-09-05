#!/usr/bin/env python3
"""One-shot GB10 queue for TIME_ONLY 900 s summaries and sidebar UI cutover."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import subprocess
import sys
import time
import traceback
from pathlib import Path
from typing import Any

import t510_stage35_s2_queue as base


FORMAT = "T510_TIME_CAPTURE900_UI_QUEUE_V1"
EXPLORER_UNIT = "t510-stage35-explorer.service"


def time_phase(index: int, label: str, duration: int, queue_id: str) -> dict[str, Any]:
    return {
        "index": index,
        "label": label,
        "scan": "TIME900",
        "position": label,
        "kind": "time",
        "mode": "time_only",
        "duration_seconds": duration,
        "scan_id": f"{queue_id}-{label}-{duration}s",
        "metadata_step": "8",
        "purpose": "TIME_ONLY_online_10ms_summary_for_human_sidebar_report",
        "status": "pending",
    }


class Queue(base.QueueRunner):
    def __init__(self, args: argparse.Namespace, template: dict[str, Any]):
        super().__init__(args, template)
        self.phases = [
            time_phase(0, "time-smoke", 60, args.queue_id),
            time_phase(1, "time-formal", 900, args.queue_id),
        ]
        self.state.update({
            "format": FORMAT,
            "schema_version": 1,
            "phases": self.phases,
            "compute_host": "NVIDIA GB10 capture host",
            "storage_policy": "process every sample; retain 10 ms summaries; no 9.2 TB raw stream",
            "pipeline": [
                "receiver_unit_and_replay_tests",
                "60s_fullrate_TIME_smoke",
                "900s_formal_TIME_online_summary",
                "independent_numeric_and_SHA256_verification",
                "readonly_array_generation",
                "sidebar_candidate_application",
                "real_browser_offline_verification",
                "atomic_8035_cutover",
                "in_place_identity",
            ],
        })

    def preflight(self) -> None:
        super().preflight()
        required = [
            self.args.time_verify,
            self.args.time_prepare,
            self.args.browser_verify,
            self.args.receiver_test_binary,
            self.args.app_root / "t510_stage35_explorer.py",
            self.args.app_root / "static" / "index.html",
            self.args.app_root / "static" / "stage35-app.js",
            self.args.app_root / "static" / "stage35-app.css",
        ]
        for path in required:
            if not path.is_file():
                raise RuntimeError(f"required frozen input is missing: {path}")
        if not self.args.existing_raw_index.is_file():
            raise RuntimeError("existing raw index is missing")
        if not (self.args.cross_scan / "dataset_manifest.json").is_file():
            raise RuntimeError("existing full-band cross scan is missing")
        for scan, path in self.args.self_scans.items():
            if not (path / "dataset_manifest.json").is_file():
                raise RuntimeError(f"self scan {scan} is missing")
        base.write_json_new(self.evidence / "implementation_identity.json", {
            "queue": {"path": str(Path(__file__).resolve()),
                      "sha256": base.sha256_file(Path(__file__).resolve())},
            "receiver": {"path": "/opt/t510-time-rx/current/t510_time_rx",
                         "sha256": base.sha256_file(Path("/opt/t510-time-rx/current/t510_time_rx"))},
            "server": {"path": str(self.args.app_root / "t510_stage35_explorer.py"),
                       "sha256": base.sha256_file(self.args.app_root / "t510_stage35_explorer.py")},
            "javascript": {"path": str(self.args.app_root / "static" / "stage35-app.js"),
                           "sha256": base.sha256_file(self.args.app_root / "static" / "stage35-app.js")},
        })
        self.event("time900_ui_preflight_pass")

    def run_command(self, name: str, command: list[str], timeout: int) -> None:
        started = base.unix_ms()
        completed = subprocess.run(command, text=True, capture_output=True, timeout=timeout,
                                   check=False)
        base.write_json_new(self.evidence / f"{name}_process.json", {
            "argv": command,
            "started_unix_ms": started,
            "finished_unix_ms": base.unix_ms(),
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        })
        if completed.returncode:
            raise RuntimeError(f"{name} failed: {completed.stderr or completed.stdout}")
        self.event(name + "_pass")

    def verify_time(self, phase: dict[str, Any]) -> Path:
        dataset = self.args.measurement_root / phase["scan_id"]
        output = self.evidence / f"{phase['label']}_verification.json"
        self.run_command(phase["label"] + "_independent_verify", [
            sys.executable, str(self.args.time_verify), str(dataset), "--output", str(output),
        ], 1800)
        result = json.loads(output.read_text(encoding="utf-8"))
        if result.get("status") != "PASS" or int(result.get("schema_version", 0)) != 2:
            raise RuntimeError(f"{phase['label']} did not produce schema-v2 TIME summaries")
        if int(result.get("duration_seconds", 0)) != phase["duration_seconds"]:
            raise RuntimeError(f"{phase['label']} duration verification mismatch")
        phase["independent_verification"] = {
            "path": str(output), "sha256": base.sha256_file(output)
        }
        self.save()
        return dataset

    def build_release(self, formal_dataset: Path) -> Path:
        release = self.args.explorer_root / "releases" / self.args.queue_id
        release.mkdir(parents=True, exist_ok=False)
        arrays = release / "time_long"
        self.run_command("time900_readonly_arrays", [
            sys.executable, str(self.args.time_prepare), "--dataset", str(formal_dataset),
            "--output", str(arrays), "--label", self.phases[1]["scan_id"],
        ], 1800)
        app_config = {
            "format": "T510_STAGE35_SIMPLE_EXPLORER_CONFIG_V2",
            "center_mhz": 200.0,
            "simple_raw_index_manifest": str(self.args.existing_raw_index),
            "time_long_index": str(arrays / "time_long_index.json"),
            "self_scans": {key: str(value) for key, value in self.args.self_scans.items()},
            "cross_scan": str(self.args.cross_scan),
            "scientific_boundary": {
                "TIME_ONLY": "post-DDC 320 MS/s IQ16 ADU; not original 3.84 GS/s ADC codes",
                "TIME_ONLY_900s": "all samples processed online; 10 ms means retained; raw stream not retained",
                "F-engine": "channelized IQ16 count; no K/Jy/SEFD calibration",
                "cross": "independent 50-ohm instrument false-correlation floor, not sky visibility",
            },
        }
        base.write_json_new(release / "app_config.json", app_config)
        self.run_command("sidebar_browser_verify", [
            sys.executable, str(self.args.browser_verify),
            "--python", sys.executable,
            "--server", str(self.args.app_root / "t510_stage35_explorer.py"),
            "--config", str(release / "app_config.json"),
            "--helper-dir", str(self.args.app_root / "helpers"),
            "--static-root", str(self.args.app_root / "static"),
            "--chrome", str(self.args.chrome),
            "--chromedriver", str(self.args.chromedriver),
            "--output", str(release / "browser_verification.json"),
            "--screenshot", str(release / "browser_smoke.png"),
            "--headful-hardware",
        ], 3600)
        base.write_json_new(release / "stage_status.json", {
            "stage35_step8": "CLIENT_UI_REVIEW_REQUIRED",
            "delivery": "SIDEBAR_AND_TIME_ONLY_900S_BROWSER_VERIFIED",
            "stage35_step12": "INDEPENDENT_50OHM_FULLBAND_100MS_BASELINE_COMPLETE",
            "stage35_step12_overall": "IN_PROGRESS",
            "not_claimed": ["K", "Jy", "SEFD", "sky phase", "physical root cause"],
        })
        return release

    def cutover(self, release: Path) -> None:
        data_current = self.args.explorer_root / "current"
        data_next = self.args.explorer_root / f".current-{self.args.queue_id}"
        if data_next.exists() or data_next.is_symlink():
            raise RuntimeError(f"refusing existing data cutover path {data_next}")
        if data_current.exists() and not data_current.is_symlink():
            raise RuntimeError("explorer data current must be a symlink")
        prior_data = os.readlink(data_current) if data_current.is_symlink() else None
        code_current = Path("/opt/t510-stage35-explorer/current")
        code_candidate = self.args.app_root
        code_previous = Path(f"/opt/t510-stage35-explorer/previous-{self.args.queue_id}")
        code_failed = Path(f"/opt/t510-stage35-explorer/failed-{self.args.queue_id}")
        if code_candidate != Path("/opt/t510-stage35-explorer/candidate"):
            raise RuntimeError("code candidate must be /opt/t510-stage35-explorer/candidate")
        if not code_current.is_dir() or not code_candidate.is_dir() or code_previous.exists():
            raise RuntimeError("code cutover paths are not in the expected state")
        data_next.symlink_to(release)
        os.replace(data_next, data_current)
        code_swapped = False
        try:
            subprocess.run(["sudo", "-n", "mv", "-T", str(code_current), str(code_previous)],
                           check=True, timeout=30)
            subprocess.run(["sudo", "-n", "mv", "-T", str(code_candidate), str(code_current)],
                           check=True, timeout=30)
            code_swapped = True
            subprocess.run(["sudo", "-n", "systemctl", "restart", EXPLORER_UNIT],
                           check=True, timeout=30)
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                try:
                    health = base.http_json("http://127.0.0.1:8035/healthz")
                    if health.get("ok") is True and health.get("application") == "stage35-simple":
                        break
                except Exception:
                    pass
                time.sleep(.25)
            else:
                raise RuntimeError("new explorer did not become healthy on 8035")
        except Exception as error:
            rollback_errors = []
            try:
                subprocess.run(["sudo", "-n", "systemctl", "stop", EXPLORER_UNIT],
                               check=False, timeout=30)
                if code_swapped:
                    subprocess.run(["sudo", "-n", "mv", "-T", str(code_current), str(code_failed)],
                                   check=True, timeout=30)
                    subprocess.run(["sudo", "-n", "mv", "-T", str(code_previous), str(code_current)],
                                   check=True, timeout=30)
                rollback = self.args.explorer_root / f".rollback-{self.args.queue_id}"
                if prior_data is None:
                    data_current.unlink(missing_ok=True)
                else:
                    rollback.symlink_to(prior_data)
                    os.replace(rollback, data_current)
                subprocess.run(["sudo", "-n", "systemctl", "start", EXPLORER_UNIT],
                               check=True, timeout=30)
            except Exception as rollback_error:
                rollback_errors.append(f"{type(rollback_error).__name__}: {rollback_error}")
            raise RuntimeError(f"8035 cutover failed: {error}; rollback={rollback_errors}") from error
        base.write_json_new(release / "cutover_identity.json", {
            "url": "http://192.168.100.162:8035/",
            "release": str(release),
            "code": str(code_current),
            "previous_code_retained": str(code_previous),
            "previous_data_release_retained": prior_data,
            "unix_ms": base.unix_ms(),
        })
        self.event("atomic_8035_cutover_pass", release=str(release))

    def final_manifest(self) -> None:
        release = Path(self.state["explorer_release"])
        formal = self.args.measurement_root / self.phases[1]["scan_id"]
        browser_path = Path(self.state.get(
            "browser_verification_path", release / "browser_verification.json"
        ))
        result = {
            "format": "T510_TIME_CAPTURE900_UI_QUEUE_MANIFEST_V1",
            "complete": True,
            "queue_id": self.args.queue_id,
            "no_archive_copy": True,
            "formal_time_manifest": {
                "path": str(formal / "dataset_manifest.json"),
                "sha256": base.sha256_file(formal / "dataset_manifest.json"),
            },
            "time_long_index": {
                "path": str(release / "time_long" / "time_long_index.json"),
                "sha256": base.sha256_file(release / "time_long" / "time_long_index.json"),
            },
            "browser_verification": {
                "path": str(browser_path),
                "sha256": base.sha256_file(browser_path),
            },
            "app_config": {"path": str(release / "app_config.json"),
                           "sha256": base.sha256_file(release / "app_config.json")},
        }
        path = self.root / "queue_manifest.json"
        base.write_json_new(path, result)
        (self.root / "queue_manifest.sha256").write_text(
            f"{base.sha256_file(path)}  queue_manifest.json\n", encoding="ascii"
        )

    def run(self) -> int:
        self.initialize()
        try:
            self.preflight()
            self.state.update(status="running", started_unix_ms=base.unix_ms())
            self.save()
            self.run_command("receiver_unit_and_synthetic_packet_replay", [
                str(self.args.receiver_test_binary), "time_capture", "--nocapture",
            ], 300)
            self.run_phase(self.phases[0])
            self.verify_time(self.phases[0])
            self.run_phase(self.phases[1])
            formal = self.verify_time(self.phases[1])
            release = self.build_release(formal)
            self.cutover(release)
            safe_errors = self.safe_finalize(failed=False)
            if safe_errors:
                raise RuntimeError(f"safe finalization errors: {safe_errors}")
            self.state.update(status="completed", current_phase_index=None,
                              finished_unix_ms=base.unix_ms(), explorer_release=str(release),
                              url="http://192.168.100.162:8035/")
            self.save()
            self.event("queue_complete")
            self.final_manifest()
            return 0
        except Exception as error:
            current = self.state.get("current_phase_index")
            if current is not None:
                phase = self.phases[int(current)]
                if phase.get("status") != "completed":
                    phase.update(status="failed", error=f"{type(error).__name__}: {error}")
            safe_errors = self.safe_finalize(failed=True)
            self.state.update(status="failed", finished_unix_ms=base.unix_ms(), error={
                "message": f"{type(error).__name__}: {error}",
                "traceback": traceback.format_exc(), "safe_finalize_errors": safe_errors,
            })
            self.save()
            self.event("queue_failed", error=self.state["error"])
            return 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue-id", required=True)
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--helper-dir", type=Path, required=True)
    parser.add_argument("--measurement-root", type=Path, default=Path("/var/lib/t510/stage35"))
    parser.add_argument("--agent-base", default="http://192.168.100.117:8010")
    parser.add_argument("--receiver-base", default="http://127.0.0.1:8089")
    parser.add_argument("--center-mhz", type=float, default=200.0)
    parser.add_argument("--minimum-free-bytes", type=int, default=50 * 1024**3)
    parser.add_argument("--lock", type=Path, default=Path("/run/lock/t510-time-capture900-ui.lock"))
    parser.add_argument("--time-verify", type=Path, required=True)
    parser.add_argument("--time-prepare", type=Path, required=True)
    parser.add_argument("--browser-verify", type=Path, required=True)
    parser.add_argument("--receiver-test-binary", type=Path, required=True)
    parser.add_argument("--existing-raw-index", type=Path, required=True)
    parser.add_argument("--cross-scan", type=Path, required=True)
    parser.add_argument("--explorer-root", type=Path, default=Path("/var/lib/t510/stage35/explorer"))
    parser.add_argument("--app-root", type=Path, default=Path("/opt/t510-stage35-explorer/candidate"))
    parser.add_argument("--chrome", type=Path, required=True)
    parser.add_argument("--chromedriver", type=Path, required=True)
    parser.add_argument("--self-scan", action="append", nargs=2,
                        metavar=("SCAN", "PATH"), required=True)
    args = parser.parse_args()
    args.self_scans = {name.upper(): Path(path) for name, path in args.self_scan}
    if set(args.self_scans) != {"A", "B", "C"}:
        parser.error("--self-scan must provide exactly A, B, and C")
    return args


def main() -> int:
    args = parse_args()
    allowed = b"abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_."
    if not args.queue_id or any(byte not in allowed for byte in args.queue_id.encode("ascii")):
        raise RuntimeError("queue-id contains unsupported characters")
    args.lock.parent.mkdir(parents=True, exist_ok=True)
    with args.lock.open("a+b") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError("another Stage 35 TIME900 UI queue owns the lock") from error
        template = json.loads(args.template.read_text(encoding="utf-8"))
        return Queue(args, template).run()


if __name__ == "__main__":
    raise SystemExit(main())
