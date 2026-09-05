#!/usr/bin/env python3
"""One-shot GB10 queue for the Stage 35 simple report, acquisition, and cutover."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path
from typing import Any

import numpy as np

import t510_stage35_s2_queue as base


FORMAT = "T510_STAGE35_SIMPLE_QUEUE_V1"
SMOKE_SECONDS = 60
FORMAL_SECONDS = 900
RAW_SPECTRA = 4096
EXPLORER_UNIT = "t510-stage35-explorer.service"
FOCUS_BINS = (
    3134, 3182, 3328, 3181, 3183, 3327, 3329, 0,
    1, 4095, 128, 256, 384, 512, 640, 768,
    896, 1024, 1280, 1536, 1792, 2047, 2048, 2304,
    2560, 2816, 3072, 3456, 3584, 3712, 3840, 3968,
)


def phase(index: int, label: str, duration: int, queue_id: str) -> dict[str, Any]:
    return {
        "index": index, "label": label, "scan": "SIMPLE", "position": label,
        "kind": "xcorr" if duration else "raw", "mode": "spec_only",
        "duration_seconds": duration,
        "scan_id": f"{queue_id}-{label}-{duration}s" if duration else f"{queue_id}-{label}",
        "status": "pending",
    }


def write_cross_manifest(scan: Path, request: dict[str, Any], verification: Path) -> dict[str, Any]:
    if (scan / "dataset_manifest.json").exists():
        raise RuntimeError(f"refusing to overwrite dataset manifest in {scan}")
    files = []
    for path in sorted(item for item in scan.rglob("*") if item.is_file()):
        if path.name in ("dataset_manifest.json", "dataset_manifest.sha256"):
            continue
        files.append({
            "path": path.relative_to(scan).as_posix(), "bytes": path.stat().st_size,
            "sha256": base.sha256_file(path),
        })
    result = {
        "format": "T510_CROSSCORRELATION_FULLBAND_100MS_DATASET_MANIFEST_V1",
        "complete": True, "request": request,
        "visibility_definition": "mean(Xa*conj(Xb))",
        "pair_index": [[a, b] for a in range(8) for b in range(a + 1, 8)],
        "fullband_products": {"one_hundred_ms": True, "one_second": True,
                              "one_second_derived_from_one_hundred_ms": True},
        "verification": {"path": str(verification), "sha256": base.sha256_file(verification)},
        "files": files,
    }
    manifest = scan / "dataset_manifest.json"
    base.write_json_new(manifest, result)
    digest = base.sha256_file(manifest)
    with (scan / "dataset_manifest.sha256").open("x", encoding="ascii") as stream:
        stream.write(f"{digest}  dataset_manifest.json\n")
    return {"path": str(manifest), "sha256": digest, "bytes": manifest.stat().st_size,
            "file_count": len(files), "verified_bytes": sum(row["bytes"] for row in files)}


class Queue(base.QueueRunner):
    def __init__(self, args: argparse.Namespace, template: dict[str, Any]):
        super().__init__(args, template)
        self.phases = [
            phase(0, "fullband100-smoke", SMOKE_SECONDS, args.queue_id),
            phase(1, "raw-4096-spectra", 0, args.queue_id),
            phase(2, "fullband100-formal", FORMAL_SECONDS, args.queue_id),
        ]
        self.state.update({
            "format": FORMAT, "schema_version": 1, "phases": self.phases,
            "compute_host": "GB10 capture host; no workstation or HPC computation",
            "data_movement": "in-place only; no archive copy",
            "focus_global_bins": list(FOCUS_BINS),
            "pipeline": [
                "CUDA_and_CPU_oracles", "frozen_PCAP_derived_oracle",
                "60s_fullrate_fullband_100ms_writer_smoke", "4096_raw_Fengine_spectra",
                "900s_fullband_100ms_and_1s_capture", "in_place_SHA256_and_numeric_recompute",
                "six_TIME_ONLY_Hann_FFT_references", "simple_candidate_application",
                "real_browser_offline_verification", "atomic_8035_cutover", "in_place_identity",
            ],
        })

    def preflight(self) -> None:
        super().preflight()
        status = self.receiver("/api/measure/crosscorrelation/status")
        if status.get("status") in ("armed", "running", "draining"):
            raise RuntimeError(f"cross-correlation task is already active: {status}")
        for path in (self.args.sidecar, self.args.oracle_raw, self.args.existing_raw_index,
                     self.args.app_root / "t510_stage35_explorer.py",
                     self.args.app_root / "static" / "index.html"):
            if not path.exists():
                raise RuntimeError(f"required local GB10 input is missing: {path}")
        if not os.access(self.args.sidecar, os.X_OK):
            raise RuntimeError(f"CUDA sidecar is not executable: {self.args.sidecar}")
        if self.args.oracle_raw.stat().st_size != self.args.oracle_spectra * 8 * 4096 * 4:
            raise RuntimeError("frozen PCAP-derived IQ oracle has an unexpected size")
        if len(FOCUS_BINS) != 32 or len(set(FOCUS_BINS)) != 32:
            raise RuntimeError("focus-bin contract must contain 32 unique bins")
        for scan, path in self.args.self_scans.items():
            if not (path / "dataset_manifest.json").is_file():
                raise RuntimeError(f"self-power scan {scan} is missing its dataset manifest: {path}")
        if not self.args.browser_verify.is_file() or not self.args.fullband_verify.is_file():
            raise RuntimeError("verification helpers are missing")
        base.write_json_new(self.evidence / "implementation_identity.json", {
            "cuda_sidecar": {"path": str(self.args.sidecar),
                             "sha256": base.sha256_file(self.args.sidecar)},
            "application_server": {
                "path": str(self.args.app_root / "t510_stage35_explorer.py"),
                "sha256": base.sha256_file(self.args.app_root / "t510_stage35_explorer.py"),
            },
            "application_javascript": {
                "path": str(self.args.app_root / "static" / "app.js"),
                "sha256": base.sha256_file(self.args.app_root / "static" / "app.js"),
            },
            "queue": {"path": str(Path(__file__).resolve()),
                      "sha256": base.sha256_file(Path(__file__).resolve())},
        })
        self.event("simple_preflight_pass", code_root=str(self.args.app_root))

    def run_command(self, name: str, command: list[str], timeout: int) -> None:
        started = base.unix_ms()
        completed = subprocess.run(command, text=True, capture_output=True, timeout=timeout,
                                   check=False)
        base.write_json_new(self.evidence / f"{name}_process.json", {
            "argv": command, "started_unix_ms": started, "finished_unix_ms": base.unix_ms(),
            "returncode": completed.returncode, "stdout": completed.stdout,
            "stderr": completed.stderr,
        })
        if completed.returncode:
            raise RuntimeError(f"{name} failed: {completed.stderr or completed.stdout}")
        self.event(name + "_pass")

    def oracle(self) -> None:
        self.run_command("cuda_synthetic_cpu_integer_oracle",
                         [str(self.args.sidecar), "--self-test"], 300)
        self.run_command("frozen_pcap_derived_cuda_cpu_oracle", [
            str(self.args.sidecar), "--self-test", "--oracle-raw", str(self.args.oracle_raw),
            "--oracle-spectra", str(self.args.oracle_spectra),
        ], 900)
        sys.path.insert(0, str(self.args.helper_dir))
        from t510_stage35_simple_math import overlapping_allan, overlapping_allan_visibility

        constant = overlapping_allan(np.ones(1024), .1, [.1, .2, .5, 1.0])
        if any(row["variance"] != 0 for row in constant):
            raise RuntimeError("constant Allan oracle is nonzero")
        random = np.random.default_rng(51035).normal(size=1_000_000)
        rows = overlapping_allan(random, 1.0, [1, 2, 4, 8, 16, 32, 64])
        variance_slope = float(np.polyfit(np.log([r["tau_s"] for r in rows]),
                                          np.log([r["variance"] for r in rows]), 1)[0])
        root_slope = float(np.polyfit(np.log([r["tau_s"] for r in rows]),
                                      np.log([r["square_root"] for r in rows]), 1)[0])
        if abs(variance_slope + 1) > .03 or abs(root_slope + .5) > .015:
            raise RuntimeError(f"white-noise slope oracle failed: {variance_slope}, {root_slope}")
        angles = np.deg2rad(np.asarray([179., -179., 179., -179.]))
        wrapped = overlapping_allan_visibility(np.exp(1j * angles), np.ones(4), np.ones(4),
                                               np.ones(4), 1.0, [1.0], relative_percent=False)
        if wrapped[0]["square_root"] >= .05:
            raise RuntimeError("complex-vector Allan created a phase-wrap discontinuity")
        base.write_json_new(self.evidence / "allan_math_oracle.json", {
            "status": "PASS", "constant_variances": [r["variance"] for r in constant],
            "white_noise_variance_log_slope": variance_slope,
            "white_noise_square_root_log_slope": root_slope,
            "phase_wrap_square_root": wrapped[0]["square_root"],
            "oracle_raw": {"path": str(self.args.oracle_raw),
                           "sha256": base.sha256_file(self.args.oracle_raw),
                           "spectra": self.args.oracle_spectra},
        })
        self.event("allan_math_oracle_pass", variance_slope=variance_slope,
                   square_root_slope=root_slope)

    def cross_request(self, phase_value: dict[str, Any]) -> dict[str, Any]:
        return {
            "scan_id": phase_value["scan_id"],
            "tuning_id": "center-200mhz-fullband-xcorr-100ms-and-1s",
            "duration_seconds": phase_value["duration_seconds"],
            "fullband_bucket_ms": 1000, "focus_bucket_ms": 100,
            "save_fullband_100ms": True,
            "sample_rate_msps": 320, "center_mhz": 200.0,
            "focus_global_bins": list(FOCUS_BINS), "lane_mask": 255,
            "expected_fft_shift": base.EXPECTED_FFT_SHIFT,
            "metadata": {
                "stage": "35", "step": "12-independent-50ohm-fullband-100ms-baseline",
                "queue_id": self.args.queue_id,
                "physical_input": "eight_independent_50ohm_operator_confirmed",
                "clock_reference": "onboard_tcxo",
                "interpretation": "instrument_false_correlation_floor_not_sky",
                "report_use": "simple_human_readable_single_and_pair_views",
            },
        }

    def run_cross(self, phase_value: dict[str, Any]) -> None:
        phase_value.update(status="starting", started_unix_ms=base.unix_ms())
        self.state["current_phase_index"] = phase_value["index"]
        self.save()
        self.event("phase_starting", phase=phase_value["label"], scan_id=phase_value["scan_id"])
        self.ensure_mode(phase_value)
        prearm_board, prearm_receiver = self.board(), self.receiver()
        request = self.cross_request(phase_value)
        started = self.receiver("/api/measure/crosscorrelation", method="POST", body=request)
        start_snapshot = self.start_stream(phase_value)
        live_receiver = self.receiver()
        status = self.receiver("/api/measure/crosscorrelation/status")
        if (status.get("status") != "armed" or
                int(status.get("progress", {}).get("packets_published", -1)) != 0):
            raise RuntimeError(
                f"formal cross-correlation window started before the integrity snapshot: {status}")
        startup = base.formal_integrity(
            prearm_board, start_snapshot, prearm_receiver, live_receiver)
        # START can increment board-side RFDC ingress counters before the receiver has
        # warmed all 16 blocks and before the future formal sample0 window.  Preserve
        # those deltas as evidence, but only receiver loss is fatal in this explicitly
        # non-scientific startup interval.  The formal gate below is based on the
        # post-START snapshots and remains strict for every board/receiver counter.
        receiver_startup_errors = [
            error for error in startup["errors"] if error.startswith("receiver.")
        ]
        if receiver_startup_errors:
            raise RuntimeError(
                "cross-correlation CUDA arm/START caused receiver loss: "
                f"{receiver_startup_errors}")
        before_board, before_receiver = start_snapshot, live_receiver
        self.seed_telemetry_cursor(before_board)
        base.write_json_new(self.evidence / f"phase_{phase_value['index']:02d}_startup.json", {
            "request": request, "receiver_response": started, "status": status,
            "integrity": startup,
        })
        phase_value.update(status="running", capture_start=started)
        self.save()
        final, telemetry = self.monitor_capture(
            phase_value, "/api/measure/crosscorrelation/status")
        after_board, after_receiver = self.board(), self.receiver()
        integrity = base.formal_integrity(before_board, after_board, before_receiver, after_receiver)
        if not integrity["ok"]:
            raise RuntimeError(f"{phase_value['label']} integrity failed: {integrity['errors']}")
        board_errors = base.board_errors(after_board, mode="spec_only", center_mhz=200.0)
        if board_errors:
            raise RuntimeError(f"board identity changed: {board_errors}")
        expected_packets = phase_value["duration_seconds"] * 78_125 * 16
        progress = final.get("progress", {})
        for key in ("packets_published", "packets_consumed"):
            if int(progress.get(key, -1)) != expected_packets:
                raise RuntimeError(f"{phase_value['label']} {key} mismatch: {progress}")
        if int(progress.get("ring_drops", -1)) != 0 or int(progress.get("completed_block_mask", 0)) != 0xffff:
            raise RuntimeError(f"{phase_value['label']} ring/completion gate failed: {progress}")
        self.stop_board(f"phase_{phase_value['index']:02d}_stop_after.json")
        scan = self.args.measurement_root / phase_value["scan_id"]
        verification = self.evidence / f"{phase_value['label']}_fullband_verification.json"
        self.run_command(f"{phase_value['label']}_fullband_verify", [
            sys.executable, str(self.args.fullband_verify), "--scan", str(scan),
            "--duration-seconds", str(phase_value["duration_seconds"]),
            "--output", str(verification),
        ], max(1800, phase_value["duration_seconds"] * 8))
        manifest = write_cross_manifest(scan, request, verification)
        phase_value.update(status="completed", finished_unix_ms=base.unix_ms(),
                           capture_status=final, formal_integrity=integrity,
                           telemetry_samples=len(telemetry), manifest=manifest)
        self.save()
        self.event("phase_complete", phase=phase_value["label"],
                   manifest_sha256=manifest["sha256"])

    def capture_raw_spectra(self, phase_value: dict[str, Any]) -> None:
        phase_value.update(status="starting", started_unix_ms=base.unix_ms())
        self.state["current_phase_index"] = phase_value["index"]
        self.save()
        self.ensure_mode(phase_value)
        self.start_stream(phase_value)
        before_board, before_receiver = self.board(), self.receiver()
        destination = self.raw / "fengine-4096-complete-spectra.pcap"
        identity = base.http_to_new_file(
            self.args.receiver_base.rstrip("/") + "/api/capture/spec-pcap", destination,
            body={"packets_per_block": RAW_SPECTRA, "include_time": False,
                  "time_only": False}, timeout=600,
        )
        after_board, after_receiver = self.board(), self.receiver()
        integrity = base.formal_integrity(before_board, after_board, before_receiver, after_receiver)
        if not integrity["ok"]:
            raise RuntimeError(f"4096-spectrum capture integrity failed: {integrity['errors']}")
        sys.path.insert(0, str(self.args.helper_dir))
        from t510_stage35_explorer_prepare import inspect_spec_pcap

        inspected = inspect_spec_pcap(destination)
        inspected.pop("_shared_sample0_values", None)
        if (int(inspected["packets_per_block"]) != RAW_SPECTRA or
                int(inspected["shared_sample0_count"]) != RAW_SPECTRA or
                not inspected["shared_sample0_continuous"]):
            raise RuntimeError(f"raw F-engine witness is incomplete: {inspected}")
        self.stop_board(f"phase_{phase_value['index']:02d}_stop_after.json")
        evidence = {"identity": identity, "inspection": inspected,
                    "receiver_integrity": integrity,
                    "decoded_shape_contract": [RAW_SPECTRA, 8, 4096, 2],
                    "time_span_seconds": RAW_SPECTRA * 4096 / 320_000_000}
        base.write_json_new(self.evidence / "raw_4096_spectra.json", evidence)
        phase_value.update(status="completed", finished_unix_ms=base.unix_ms(),
                           pcap=identity, inspection=inspected, formal_integrity=integrity)
        self.save()
        self.event("raw_4096_spectra_complete", bytes=identity["bytes"])

    def build_candidate(self, formal_scan: Path) -> Path:
        release = self.args.explorer_root / "releases" / self.args.queue_id
        release.mkdir(parents=True, exist_ok=False)
        raw_output = release / "raw"
        self.run_command("simple_raw_prepare_on_GB10", [
            sys.executable, str(self.args.helper_dir / "t510_stage35_simple_prepare.py"),
            "--existing-raw-index", str(self.args.existing_raw_index),
            "--spec-pcap", str(self.raw / "fengine-4096-complete-spectra.pcap"),
            "--spec-label", "simple-4096", "--output", str(raw_output),
        ], 7200)
        app_config = {
            "format": "T510_STAGE35_SIMPLE_EXPLORER_CONFIG_V1", "center_mhz": 200.0,
            "simple_raw_index_manifest": str(raw_output / "simple_raw_index_manifest.json"),
            "self_scans": {key: str(path) for key, path in self.args.self_scans.items()},
            "cross_scan": str(formal_scan),
            "scientific_boundary": {
                "TIME_ONLY": "post-DDC IQ16 ADU, not original 3.84 GS/s ADC codes",
                "F-engine": "channelized IQ16 count; no K/Jy/SEFD calibration",
                "cross": "independent 50-ohm instrument false-correlation floor, not sky visibility",
            },
        }
        base.write_json_new(release / "app_config.json", app_config)
        self.run_command("simple_browser_verify", [
            sys.executable, str(self.args.browser_verify), "--python", sys.executable,
            "--server", str(self.args.app_root / "t510_stage35_explorer.py"),
            "--config", str(release / "app_config.json"),
            "--helper-dir", str(self.args.app_root / "helpers"),
            "--static-root", str(self.args.app_root / "static"),
            "--chrome", str(self.args.chrome), "--chromedriver", str(self.args.chromedriver),
            "--output", str(release / "browser_verification.json"),
            "--screenshot", str(release / "browser_smoke.png"),
        ], 3600)
        base.write_json_new(release / "stage_status.json", {
            "stage35_step8": "INTERACTIVE_SIMPLE_REPORT_BROWSER_VERIFIED",
            "stage35_step12": "INDEPENDENT_50OHM_FULLBAND_100MS_BASELINE_COMPLETE",
            "stage35_step12_overall": "IN_PROGRESS",
            "not_claimed": ["K", "Jy", "SEFD", "sky phase", "imaging capability", "physical root cause"],
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
            raise RuntimeError("cutover candidate code path is not the frozen /opt path")
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
            subprocess.run(["sudo", "-n", "install", "-o", "root", "-g", "root", "-m", "0644",
                            str(code_current / "t510-stage35-explorer.service"),
                            "/etc/systemd/system/t510-stage35-explorer.service"], check=True, timeout=30)
            subprocess.run(["sudo", "-n", "systemctl", "daemon-reload"], check=True, timeout=30)
            subprocess.run(["sudo", "-n", "systemctl", "restart", EXPLORER_UNIT], check=True, timeout=30)
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
                raise RuntimeError("simple explorer did not become healthy on port 8035")
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
                    subprocess.run(["sudo", "-n", "install", "-o", "root", "-g", "root", "-m", "0644",
                                    str(code_current / "t510-stage35-explorer.service"),
                                    "/etc/systemd/system/t510-stage35-explorer.service"], check=True, timeout=30)
                rollback = self.args.explorer_root / f".rollback-{self.args.queue_id}"
                if prior_data is None:
                    data_current.unlink(missing_ok=True)
                else:
                    rollback.symlink_to(prior_data)
                    os.replace(rollback, data_current)
                subprocess.run(["sudo", "-n", "systemctl", "daemon-reload"], check=True, timeout=30)
                subprocess.run(["sudo", "-n", "systemctl", "start", EXPLORER_UNIT], check=True, timeout=30)
            except Exception as rollback_error:
                rollback_errors.append(f"{type(rollback_error).__name__}: {rollback_error}")
            raise RuntimeError(f"8035 cutover failed: {error}; rollback_errors={rollback_errors}") from error
        base.write_json_new(release / "cutover_identity.json", {
            "url": "http://192.168.100.162:8035/", "release": str(release),
            "code": str(code_current), "previous_code_retained": str(code_previous),
            "previous_data_release_retained": prior_data, "unix_ms": base.unix_ms(),
        })
        self.event("atomic_8035_cutover_pass", release=str(release))

    def safe_finalize(self, *, failed: bool) -> list[str]:
        errors = []
        try:
            status = self.receiver("/api/measure/crosscorrelation/status")
            if status.get("status") in ("armed", "running", "draining"):
                self.receiver("/api/measure/crosscorrelation/stop", method="POST",
                              body={"reason": "simple queue safe finalization"})
        except Exception as error:
            errors.append(f"cross-correlation STOP failed: {type(error).__name__}: {error}")
        errors.extend(super().safe_finalize(failed=failed))
        return errors

    def final_manifest(self) -> None:
        formal = self.phases[2]
        release = Path(self.state["explorer_release"])
        identities = {
            "format": "T510_STAGE35_SIMPLE_QUEUE_MANIFEST_V1", "complete": True,
            "queue_id": self.args.queue_id, "no_archive_copy": True,
            "raw_4096_pcap": self.phases[1]["pcap"],
            "formal_cross_dataset_manifest": formal["manifest"],
            "simple_raw_manifest": {
                "path": str(release / "raw" / "simple_raw_index_manifest.json"),
                "sha256": base.sha256_file(release / "raw" / "simple_raw_index_manifest.json"),
            },
            "browser_verification": {
                "path": str(release / "browser_verification.json"),
                "sha256": base.sha256_file(release / "browser_verification.json"),
            },
            "app_config": {"path": str(release / "app_config.json"),
                           "sha256": base.sha256_file(release / "app_config.json")},
        }
        path = self.root / "queue_manifest.json"
        base.write_json_new(path, identities)
        with (self.root / "queue_manifest.sha256").open("x", encoding="ascii") as stream:
            stream.write(f"{base.sha256_file(path)}  queue_manifest.json\n")

    def run(self) -> int:
        self.initialize()
        try:
            self.preflight()
            self.state.update(status="running", started_unix_ms=base.unix_ms())
            self.save()
            self.oracle()
            self.run_cross(self.phases[0])
            self.capture_raw_spectra(self.phases[1])
            self.run_cross(self.phases[2])
            formal_scan = self.args.measurement_root / self.phases[2]["scan_id"]
            release = self.build_candidate(formal_scan)
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
                match = next((p for p in self.phases if p["index"] == int(current)), None)
                if match and match.get("status") != "completed":
                    match.update(status="failed", error=f"{type(error).__name__}: {error}")
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
    parser.add_argument("--minimum-free-bytes", type=int, default=250 * 1024**3)
    parser.add_argument("--lock", type=Path, default=Path("/run/lock/t510-stage35-simple.lock"))
    parser.add_argument("--sidecar", type=Path, required=True)
    parser.add_argument("--oracle-raw", type=Path, required=True)
    parser.add_argument("--oracle-spectra", type=int, required=True)
    parser.add_argument("--existing-raw-index", type=Path, required=True)
    parser.add_argument("--fullband-verify", type=Path, required=True)
    parser.add_argument("--browser-verify", type=Path, required=True)
    parser.add_argument("--explorer-root", type=Path, default=Path("/var/lib/t510/stage35/explorer"))
    parser.add_argument("--app-root", type=Path, default=Path("/opt/t510-stage35-explorer/candidate"))
    parser.add_argument("--chrome", type=Path, required=True)
    parser.add_argument("--chromedriver", type=Path, required=True)
    parser.add_argument("--self-scan", action="append", nargs=2,
                        metavar=("SCAN", "PATH"), required=True)
    args = parser.parse_args()
    args.self_scans = {scan.upper(): Path(path) for scan, path in args.self_scan}
    if set(args.self_scans) != {"A", "B", "C"}:
        parser.error("--self-scan must provide exactly A, B, and C")
    return args


def main() -> int:
    args = parse_args()
    allowed = b"abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_."
    if not args.queue_id or any(byte not in allowed for byte in args.queue_id.encode("ascii", errors="strict")):
        raise RuntimeError("queue-id contains unsupported characters")
    args.lock.parent.mkdir(parents=True, exist_ok=True)
    with args.lock.open("a+b") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError("another Stage 35 simple queue owns the lock") from error
        template = json.loads(args.template.read_text(encoding="utf-8"))
        return Queue(args, template).run()


if __name__ == "__main__":
    raise SystemExit(main())
