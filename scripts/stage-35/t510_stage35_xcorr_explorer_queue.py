#!/usr/bin/env python3
"""One-shot Stage 35 XCORR smoke, A/B/C capture, analysis, app and cutover queue."""

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


FORMAT = "T510_CROSSCORRELATION_EXPLORER_QUEUE_V1"
SMOKE_SECONDS = 60
XCORR_SECONDS = 900
TIME_SECONDS = 30
OLD_HTTP_UNIT = "t510-stage35-s2-report-v2-human-http-20260901.service"
EXPLORER_UNIT = "t510-stage35-explorer.service"


def phase_plan(queue_id: str) -> list[dict[str, Any]]:
    phases = []
    for scan in ("A", "B", "C"):
        for position, kind, duration in (
            ("pre", "time", TIME_SECONDS),
            ("scan", "xcorr", XCORR_SECONDS),
            ("post", "time", TIME_SECONDS),
        ):
            label = f"{scan.lower()}-{kind}-{position}"
            phases.append({
                "index": len(phases), "label": label, "scan": scan,
                "position": position, "kind": kind,
                "mode": "time_only" if kind == "time" else "spec_only",
                "duration_seconds": duration,
                "scan_id": f"{queue_id}-{label}-{duration}s", "status": "pending",
            })
    return phases


def rf_bin(rf_mhz: float, center_mhz: float) -> int:
    signed = int(round((rf_mhz - center_mhz) / .078125))
    return signed % 4096


def focus_bins(analysis_root: Path, helper_dir: Path) -> tuple[list[int], dict[str, Any]]:
    """Freeze 32 focus bins from the authoritative analysis at this tuning."""
    sys.path.insert(0, str(helper_dir))
    import t510_stage35_s2_html_report_v2 as report_v2

    quick, cross, rf_hz = report_v2.load_quick(analysis_root)
    story = report_v2.build_science_story(analysis_root, quick, cross, rf_hz=rf_hz)
    presets = story["adc_presets"]
    priority = [3327, 3328, 3329, 3181, 3182, 3183]
    for adc in range(8):
        row = presets[str(adc)]
        priority += [row["representative"], row["worst_integration"], row["strongest_memory"]]
    # Preserve six deterministic digital-offset witnesses and band quartiles.
    priority += [3840, 3712, 3584, 512, 640, 768]
    priority += [512, 1536, 2560, 3584]
    # Deterministic unflagged grid witnesses fill any slots freed by de-duplication.
    priority += [128, 256, 384, 896, 1024, 1280, 1792, 2304, 2816, 3072, 3456, 3968]
    result = []
    for value in priority:
        if value not in result:
            result.append(value)
        if len(result) == 32:
            break
    if len(result) != 32:
        raise RuntimeError("focus-bin priority did not produce exactly 32 unique bins")
    evidence = {
        "source": "authoritative Stage 35 science_story.adc_presets at requested tuning",
        "analysis_root": str(analysis_root),
        "adc_presets": presets,
        "priority_contract": [
            "previously flagged digital bins 3328/3182 and adjacent bins",
            "each ADC representative/worst-integration/strongest-memory",
            "six deterministic digital-offset witnesses", "band quartiles", "grid fillers",
        ],
    }
    return result, evidence


def write_cross_manifest(dataset: Path, request: dict[str, Any]) -> dict[str, Any]:
    zarr = dataset / "xcorr.zarr"
    attrs = json.loads((zarr / ".zattrs").read_text())
    if attrs.get("complete") is not True:
        raise RuntimeError(f"{dataset.name} is not marked complete")
    seconds = int(request["duration_seconds"])
    expected = {
        "mean_auto_power_count2": ([seconds, 8, 4096], [1, 8, 256], "<f8"),
        "mean_cross_visibility_count2": ([seconds, 28, 4096], [1, 28, 256], "<c16"),
        "focus_mean_auto_power_count2": ([seconds * 10, 8, len(request["focus_global_bins"])],
                                           [10, 8, len(request["focus_global_bins"])], "<f8"),
        "focus_mean_cross_visibility_count2": ([seconds * 10, 28, len(request["focus_global_bins"])],
                                                 [10, 28, len(request["focus_global_bins"])], "<c16"),
    }
    for name, (shape, chunks, dtype) in expected.items():
        meta = json.loads((zarr / name / ".zarray").read_text())
        if meta["shape"] != shape or meta["chunks"] != chunks or meta["dtype"] != dtype:
            raise RuntimeError(f"{dataset.name}/{name} metadata mismatch: {meta}")
    nvalid = []
    for second in range(seconds):
        values = np.fromfile(zarr / "n_valid" / f"{second}.0", dtype="<u8")
        if len(values) != 16 or len(set(values.tolist())) != 1 or int(values[0]) != 78_125:
            raise RuntimeError(f"{dataset.name} second {second} n_valid mismatch: {values}")
        nvalid.append(int(values[0]))
    quality = [json.loads(line) for line in (dataset / "quality_ledger.jsonl").read_text().splitlines()]
    if len(quality) != seconds or any(not row.get("complete") or any(row["ring_drops"]) for row in quality):
        raise RuntimeError(f"{dataset.name} quality ledger failed")
    files = []
    for path in sorted(item for item in dataset.rglob("*") if item.is_file()):
        if path.name in ("dataset_manifest.json", "dataset_manifest.sha256"):
            continue
        files.append({"path": path.relative_to(dataset).as_posix(), "bytes": path.stat().st_size,
                      "sha256": base.sha256_file(path)})
    manifest = {
        "format": "T510_CROSSCORRELATION_DATASET_MANIFEST_V1", "complete": True,
        "request": request, "visibility_definition": "mean(Xa*conj(Xb))",
        "pair_index": [[a, b] for a in range(8) for b in range(a + 1, 8)],
        "n_valid_per_second": {"minimum": min(nvalid), "maximum": max(nvalid)},
        "quality": {"ring_drops": 0, "seconds": seconds}, "files": files,
    }
    path = dataset / "dataset_manifest.json"
    base.write_json_new(path, manifest)
    digest = base.sha256_file(path)
    (dataset / "dataset_manifest.sha256").write_text(f"{digest}  dataset_manifest.json\n")
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": digest,
            "file_count": len(files), "format": manifest["format"]}


class Queue(base.QueueRunner):
    def __init__(self, args: argparse.Namespace, template: dict[str, Any]):
        super().__init__(args, template)
        self.phases = phase_plan(args.queue_id)
        self.state["format"] = FORMAT
        self.state["schema_version"] = 1
        self.state["phases"] = self.phases
        selected, selection = focus_bins(args.analysis_root, args.helper_dir)
        selection["report_config"] = {
            "path": str(args.report_config), "sha256": base.sha256_file(args.report_config),
        }
        self.state["focus_global_bins"] = selected
        self.state["focus_bin_selection"] = selection
        self.state["pipeline"] = [
            "synthetic_and_archived_pcap_oracle", "cuda_60s_live_smoke",
            "A_pre_TIME", "A_XCORR", "A_post_TIME", "B_pre_TIME", "B_XCORR",
            "B_post_TIME", "C_pre_TIME", "C_XCORR", "C_post_TIME",
            "numeric_and_zarr_verify", "raw_index", "fullband_analysis",
            "candidate_app", "offline_browser_verify", "atomic_8035_cutover", "archive_identity",
        ]

    def preflight(self) -> None:
        super().preflight()
        status = self.receiver("/api/measure/crosscorrelation/status")
        if status.get("status") in ("armed", "running", "draining"):
            raise RuntimeError(f"cross-correlation task is already active: {status}")
        if not self.args.sidecar.is_file() or not os.access(self.args.sidecar, os.X_OK):
            raise RuntimeError(f"CUDA sidecar is not executable: {self.args.sidecar}")
        if not self.args.preflight_pcap.is_file():
            raise RuntimeError(f"frozen preflight SPEC PCAP is missing: {self.args.preflight_pcap}")

    def safe_finalize(self, *, failed: bool) -> list[str]:
        errors: list[str] = []
        try:
            status = self.receiver("/api/measure/crosscorrelation/status")
            if status.get("status") in ("armed", "running", "draining"):
                self.receiver("/api/measure/crosscorrelation/stop", method="POST",
                              body={"reason": "queue safe finalization"})
        except Exception as error:
            errors.append(f"cross-correlation STOP failed: {type(error).__name__}: {error}")
        errors.extend(super().safe_finalize(failed=failed))
        return errors

    def synthetic_oracle(self) -> None:
        completed = subprocess.run([str(self.args.sidecar), "--self-test"], text=True,
                                   capture_output=True, timeout=180, check=False)
        evidence = {"argv": [str(self.args.sidecar), "--self-test"],
                    "returncode": completed.returncode, "stdout": completed.stdout,
                    "stderr": completed.stderr,
                    "archived_pcap_replay_evidence": str(self.args.replay_evidence)}
        if completed.returncode != 0:
            raise RuntimeError(f"CUDA/CPU oracle failed: {completed.stderr}")
        # Before any live traffic, feed a frozen real SPEC PCAP through the exact
        # production CUDA product kernel and its independent CPU integer oracle.
        sys.path.insert(0, str(self.args.helper_dir))
        from t510_stage35_explorer_prepare import prepare_spec
        oracle_root = self.evidence / "preflight_pcap_cuda_oracle"
        record = prepare_spec("r4-a-begin", self.args.preflight_pcap, oracle_root)
        iq = np.load(record["iq16_npy"], mmap_mode="r")
        oracle_raw = oracle_root / "r4-a-begin-iq16.raw"
        np.asarray(iq, dtype="<i2").tofile(oracle_raw)
        del iq
        oracle_command = [str(self.args.sidecar), "--self-test", "--oracle-raw",
                          str(oracle_raw), "--oracle-spectra", str(record["spectra"])]
        self.run_command("preflight_pcap_cuda_cpu_oracle", oracle_command, 600)
        record["oracle_raw"] = {"path": str(oracle_raw), "bytes": oracle_raw.stat().st_size,
                                "sha256": base.sha256_file(oracle_raw)}
        evidence["preflight_pcap_cuda_cpu_oracle"] = record
        replay_manifest = self.args.replay_evidence / "compact_evidence_manifest.json"
        if not replay_manifest.is_file():
            candidates = list(self.args.replay_evidence.glob("*.json"))
            if not candidates:
                raise RuntimeError("archived Stage 35 PCAP replay evidence is missing")
        evidence["archived_evidence_files"] = [
            {"path": str(path), "sha256": base.sha256_file(path)}
            for path in sorted(self.args.replay_evidence.glob("*")) if path.is_file()
        ]
        base.write_json_new(self.evidence / "synthetic_and_pcap_oracle.json", evidence)
        self.event("synthetic_and_pcap_oracle_pass")

    def capture_time_raw(self, phase: dict[str, Any]) -> dict[str, Any]:
        stem = phase["label"]
        superset = self.raw / f"{stem}-52ms-superset.pcap"
        cropped = self.raw / f"{stem}-50ms.pcap"
        before_board, before_receiver = self.board(), self.receiver()
        identity = base.http_to_new_file(
            self.args.receiver_base.rstrip("/") + "/api/capture/spec-pcap", superset,
            body={"packets_per_block": base.TIME_RAW_PACKETS_PER_FLOW,
                  "include_time": True, "time_only": True}, timeout=240,
        )
        integrity = base.formal_integrity(before_board, self.board(), before_receiver, self.receiver())
        if not integrity["ok"]:
            raise RuntimeError(f"{stem} TIME raw integrity failed: {integrity['errors']}")
        sys.path.insert(0, str(self.args.helper_dir))
        from t510_time_capture_verify import crop_continuous_pcap, verify_pcap
        result = {"superset": identity, "crop": crop_continuous_pcap(superset, cropped),
                  "verified": verify_pcap(cropped), "receiver_integrity": integrity,
                  "phase": stem}
        base.write_json_new(self.evidence / f"{stem}-raw.json", result)
        return result

    def run_phase(self, phase: dict[str, Any]) -> None:
        phase["status"] = "starting"; phase["started_unix_ms"] = base.unix_ms()
        self.state["current_phase_index"] = phase["index"]; self.save()
        self.event("phase_starting", phase=phase["label"], scan_id=phase["scan_id"])
        self.ensure_mode(phase)
        prearm_board, prearm_receiver = self.board(), self.receiver()
        if phase["kind"] == "xcorr":
            request = {
                "scan_id": phase["scan_id"], "tuning_id": f"center-{self.args.center_mhz:g}mhz-fullband-xcorr",
                "duration_seconds": phase["duration_seconds"], "fullband_bucket_ms": 1000,
                "focus_bucket_ms": 100, "sample_rate_msps": 320, "center_mhz": self.args.center_mhz,
                "focus_global_bins": self.state["focus_global_bins"], "lane_mask": 255,
                "expected_fft_shift": base.EXPECTED_FFT_SHIFT,
                "metadata": {"stage": "35", "step": "12-independent-50ohm-fullband-baseline",
                             "queue_id": self.args.queue_id, "scan": phase["scan"],
                             "physical_input": "eight_independent_50ohm_operator_confirmed",
                             "clock_reference": "onboard_tcxo",
                             "interpretation": "instrument_false_correlation_floor_not_sky"},
            }
            begin_path = "/api/measure/crosscorrelation"
        else:
            request = {
                "scan_id": phase["scan_id"], "tuning_id": f"center-{self.args.center_mhz:g}mhz-time-only",
                "duration_seconds": phase["duration_seconds"], "native_bucket_ms": 10,
                "sample_rate_msps": 320, "center_mhz": self.args.center_mhz,
                "metadata": {"stage": "35", "step": "8-interactive-time-control",
                             "queue_id": self.args.queue_id, "scan": phase["scan"],
                             "position": phase["position"],
                             "physical_input": "eight_independent_50ohm_operator_confirmed"},
            }
            begin_path = "/api/measure/time"
        # Pin/register the large CUDA shared ring while the board is STOPPED.
        # Doing this under the 83.2 Gbit/s stream can transiently starve packet
        # fanout before the formal sample0 window even begins.
        if phase["kind"] == "xcorr":
            started = self.receiver(begin_path, method="POST", body=request)
            start_snapshot = self.start_stream(phase)
            before_receiver = self.receiver()
            warm = self.receiver(begin_path + "/status")
            if (warm.get("status") != "armed" or
                    int(warm.get("progress", {}).get("packets_published", -1)) != 0):
                raise RuntimeError(f"formal XCORR window started before the integrity snapshot: {warm}")
            before_board = start_snapshot
            startup = base.formal_integrity(
                prearm_board, before_board, prearm_receiver, before_receiver)
            receiver_startup_errors = [error for error in startup["errors"]
                                       if error.startswith("receiver.")]
            if receiver_startup_errors:
                raise RuntimeError(
                    f"XCORR CUDA arm/START caused receiver loss: {receiver_startup_errors}")
            base.write_json_new(
                self.evidence / f"phase_{phase['index']:02d}_startup_integrity.json", startup)
            raw_begin = self.capture_spec_raw(phase, "begin")
        else:
            before_board = self.start_stream(phase)
            before_receiver = self.receiver()
            raw_begin = None
            started = self.receiver(begin_path, method="POST", body=request)
        self.seed_telemetry_cursor(before_board)
        base.write_json_new(
            self.evidence / f"phase_{phase['index']:02d}_board_before.json", before_board)
        base.write_json_new(
            self.evidence / f"phase_{phase['index']:02d}_receiver_before.json", before_receiver)
        phase["capture_start"] = started; phase["status"] = "running"; self.save()
        self.event("phase_capture_armed", phase=phase["label"], status=started.get("status"))
        final_status, telemetry = self.monitor_capture(phase, begin_path + "/status")
        after_board, after_receiver = self.board(), self.receiver()
        base.write_json_new(self.evidence / f"phase_{phase['index']:02d}_board_after.json", after_board)
        base.write_json_new(self.evidence / f"phase_{phase['index']:02d}_receiver_after.json", after_receiver)
        integrity = base.formal_integrity(before_board, after_board, before_receiver, after_receiver)
        if not integrity["ok"]:
            raise RuntimeError(f"{phase['label']} formal integrity failed: {integrity['errors']}")
        errors = base.board_errors(
            after_board, mode=phase["mode"], center_mhz=self.args.center_mhz
        )
        if errors:
            raise RuntimeError(f"{phase['label']} board identity changed: {errors}")
        raw_end = (self.capture_spec_raw(phase, "end") if phase["kind"] == "xcorr"
                   else self.capture_time_raw(phase))
        self.stop_board(f"phase_{phase['index']:02d}_stop_after.json")
        dataset = self.args.measurement_root / phase["scan_id"]
        manifest = (write_cross_manifest(dataset, request) if phase["kind"] == "xcorr"
                    else base.verify_manifest_basic(dataset, phase))
        phase.update({"status": "completed", "finished_unix_ms": base.unix_ms(),
                      "capture_status": final_status, "manifest": manifest,
                      "formal_integrity": integrity, "telemetry_samples": len(telemetry),
                      "raw_begin": raw_begin, "raw_end": raw_end})
        self.save(); self.event("phase_complete", phase=phase["label"], manifest_sha256=manifest["sha256"])

    def smoke(self) -> None:
        phase = {"index": 99, "label": "cuda-fullband-smoke", "scan": "SMOKE",
                 "position": "smoke", "kind": "xcorr", "mode": "spec_only",
                 "duration_seconds": SMOKE_SECONDS,
                 "scan_id": f"{self.args.queue_id}-cuda-xcorr-smoke-{SMOKE_SECONDS}s",
                 "status": "pending"}
        # Keep the formal nine-phase state untouched while running the mandatory gate.
        saved = self.state["current_phase_index"]
        self.run_phase(phase)
        self.state["current_phase_index"] = saved
        self.state["smoke"] = phase
        progress = phase["capture_status"]["progress"]
        expected_packets = SMOKE_SECONDS * 78_125 * 16
        if progress["packets_published"] != expected_packets or progress["packets_consumed"] != expected_packets:
            raise RuntimeError(f"60 s smoke packet coverage mismatch: {progress}")
        if progress["ring_drops"] != 0 or progress["completed_block_mask"] != 0xffff:
            raise RuntimeError(f"60 s smoke ring gate failed: {progress}")
        self.save(); self.event("cuda_60s_smoke_pass", progress=progress)

    def independent_verify(self) -> None:
        time_results, cross_results = [], []
        for phase in self.phases:
            dataset = self.args.measurement_root / phase["scan_id"]
            manifest = json.loads((dataset / "dataset_manifest.json").read_text())
            for item in manifest["files"]:
                path = dataset / item["path"]
                if path.stat().st_size != int(item["bytes"]) or base.sha256_file(path) != item["sha256"]:
                    raise RuntimeError(f"manifest identity mismatch: {path}")
            if phase["kind"] == "time":
                quality = json.loads((dataset / "flow_quality.json").read_text())
                if len(quality) != 8 or any(int(row[key]) for row in quality
                    for key in ("missing_packets", "reordered_packets", "duplicate_packets")):
                    raise RuntimeError(f"TIME quality failed: {phase['scan_id']}")
                time_results.append(phase["scan_id"])
            else:
                cross_results.append(phase["scan_id"])
        numeric_output = self.evidence / "xcorr_numeric_verification.json"
        if numeric_output.exists():
            numeric = json.loads(numeric_output.read_text())
            if numeric.get("status") != "PASS" or int(numeric.get("scan_count", 0)) != 3:
                raise RuntimeError("existing XCORR numeric verification is not a reusable three-scan PASS")
            self.event("xcorr_numeric_verification_reused",
                       sha256=base.sha256_file(numeric_output))
        else:
            numeric_command = [sys.executable,
                               str(self.args.helper_dir / "t510_stage35_xcorr_verify.py")]
            for scan_id in cross_results:
                numeric_command += ["--scan", str(self.args.measurement_root / scan_id)]
            numeric_command += ["--output", str(numeric_output)]
            self.run_command("xcorr_numeric_verification", numeric_command, 3600)

        # Replay a real short SPEC PCAP through the same CUDA integer kernel and
        # compare every auto/cross cell against an independent CPU integer oracle.
        sys.path.insert(0, str(self.args.helper_dir))
        from t510_stage35_explorer_prepare import prepare_spec
        supplemental = getattr(self.args, "recovery_spec_pcaps", {})
        if supplemental:
            oracle_label, oracle_source = sorted(supplemental.items())[0]
            oracle_note = (
                "post-failure supplemental witness under unchanged independent-50ohm/TCXO "
                "conditions; not simultaneous with the sealed A/B/C integrations"
            )
        else:
            oracle_label, oracle_source = "a-begin", self.raw / "a-spec-begin-raw.pcap"
            oracle_note = "formal A-begin raw witness"
        resume_tag = getattr(self.args, "resume_tag", "initial")
        oracle_root = self.evidence / f"captured_spec_cuda_oracle-{resume_tag}"
        record = prepare_spec(oracle_label, Path(oracle_source), oracle_root)
        iq = np.load(record["iq16_npy"], mmap_mode="r")
        oracle_raw = oracle_root / f"{oracle_label}-iq16.raw"
        np.asarray(iq, dtype="<i2").tofile(oracle_raw)
        del iq
        oracle_command = [str(self.args.sidecar), "--self-test", "--oracle-raw",
                          str(oracle_raw), "--oracle-spectra", str(record["spectra"])]
        process_name = f"captured_spec_cuda_cpu_oracle_{resume_tag}"
        self.run_command(process_name, oracle_command, 600)
        record["oracle_raw"] = {"path": str(oracle_raw), "bytes": oracle_raw.stat().st_size,
                                "sha256": base.sha256_file(oracle_raw)}
        record["temporal_relationship"] = oracle_note
        base.write_json_new(self.evidence / "captured_spec_cuda_oracle.json", record)
        base.write_json_new(self.evidence / "independent_verification.json",
                            {"status": "PASS", "time_scans": time_results,
                             "cross_scans": cross_results, "sha256_all_manifest_files": True,
                             "numeric_verification": str(numeric_output),
                             "captured_spec_cuda_cpu_oracle": str(
                                 self.evidence / "captured_spec_cuda_oracle.json")})
        self.event("independent_verification_pass", time_scans=6, cross_scans=3)

    def build_explorer(self) -> Path:
        release_id = getattr(self.args, "release_id", self.args.queue_id)
        release = self.args.explorer_root / "releases" / release_id
        release.mkdir(parents=True, exist_ok=False)
        time_raw, spec_raw, xcorr_scans = {}, {}, {}
        for phase in self.phases:
            if phase["kind"] == "time":
                time_raw[f"{phase['scan']}-{phase['position']}"] = str(self.raw / f"{phase['label']}-50ms.pcap")
            else:
                xcorr_scans[phase["scan"]] = str(self.args.measurement_root / phase["scan_id"])
                spec_raw[f"{phase['scan']}-begin"] = phase["raw_begin"]["path"]
                spec_raw[f"{phase['scan']}-end"] = phase["raw_end"]["path"]
        supplemental = getattr(self.args, "recovery_spec_pcaps", {})
        if supplemental:
            spec_raw = {label: str(path) for label, path in sorted(supplemental.items())}
        raw_config = release / "raw_config.json"
        base.write_json_new(raw_config, {"time_raw": time_raw, "spec_raw": spec_raw})
        raw_output = release / "raw"
        self.run_command("raw_index", [sys.executable, str(self.args.helper_dir / "t510_stage35_explorer_prepare.py"),
                         "--config", str(raw_config), "--output", str(raw_output)], 3600)
        analysis_config = release / "analysis_config.json"
        base.write_json_new(analysis_config, {"xcorr_scans": xcorr_scans,
                            "spec_scans": self.args.spec_scans})
        analysis_output = release / "analysis"
        self.run_command("explorer_analysis", [sys.executable,
                         str(self.args.helper_dir / "t510_stage35_explorer_analyze.py"),
                         "--config", str(analysis_config), "--output", str(analysis_output)], 7200)
        report_copy = release / "stage35_s2_report_v2.json"
        shutil.copy2(self.args.report_config, report_copy)
        app_config = {
            "analysis_root": str(self.args.analysis_root), "report_config": str(report_copy),
            "raw_index_manifest": str(raw_output / "raw_index_manifest.json"),
            "spec_scans": self.args.spec_scans, "xcorr_scans": xcorr_scans,
            "explorer_analysis_summary": str(analysis_output / "explorer_analysis_summary.json"),
        }
        base.write_json_new(release / "app_config.json", app_config)
        self.run_command("browser_verify", [sys.executable,
            str(self.args.helper_dir / "t510_stage35_explorer_browser_verify.py"),
            "--python", sys.executable, "--server", str(self.args.app_root / "t510_stage35_explorer.py"),
            "--config", str(release / "app_config.json"), "--helper-dir", str(self.args.app_root / "helpers"),
            "--static-root", str(self.args.app_root / "static"), "--chrome", str(self.args.chrome),
            "--chromedriver", str(self.args.chromedriver), "--output", str(release / "browser_verification.json"),
            "--screenshot", str(release / "browser_smoke.png")], 1800)
        return release

    def run_command(self, name: str, command: list[str], timeout: int) -> None:
        started = base.unix_ms()
        completed = subprocess.run(command, text=True, capture_output=True, timeout=timeout, check=False)
        base.write_json_new(self.evidence / f"{name}_process.json",
                            {"argv": command, "started_unix_ms": started,
                             "finished_unix_ms": base.unix_ms(), "returncode": completed.returncode,
                             "stdout": completed.stdout, "stderr": completed.stderr})
        if completed.returncode:
            raise RuntimeError(f"{name} failed: {completed.stderr or completed.stdout}")
        self.event(name + "_pass")

    def cutover(self, release: Path) -> None:
        current = self.args.explorer_root / "current"
        candidate = self.args.explorer_root / f".current-{self.args.queue_id}"
        if candidate.exists() or candidate.is_symlink():
            raise RuntimeError(f"refusing to overwrite cutover candidate {candidate}")
        prior_target = os.readlink(current) if current.is_symlink() else None
        if current.exists() and not current.is_symlink():
            raise RuntimeError(f"refusing to replace non-symlink explorer current path: {current}")
        candidate.symlink_to(release)
        os.replace(candidate, current)
        old_stopped = False
        try:
            old_stop = subprocess.run(
                ["sudo", "-n", "systemctl", "stop", OLD_HTTP_UNIT],
                check=False,
                timeout=30,
            )
            # systemctl returns 5 when a transient unit no longer exists. That
            # is already the desired state and must not abort the cutover after
            # the current symlink has been replaced.
            if old_stop.returncode not in (0, 5):
                raise RuntimeError(
                    f"stop legacy HTTP unit returned {old_stop.returncode}"
                )
            old_stopped = old_stop.returncode == 0
            subprocess.run(["sudo", "-n", "systemctl", "restart", EXPLORER_UNIT], check=True, timeout=30)
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                try:
                    health = base.http_json("http://127.0.0.1:8035/healthz")
                    if health.get("ok") is True:
                        break
                except Exception:
                    pass
                time.sleep(.25)
            else:
                raise RuntimeError("new explorer did not become healthy on 8035")
        except Exception as cutover_error:
            rollback_errors = []
            try:
                subprocess.run(["sudo", "-n", "systemctl", "stop", EXPLORER_UNIT], check=False, timeout=30)
            except Exception as error:
                rollback_errors.append(f"stop new service: {error}")
            try:
                rollback = self.args.explorer_root / f".rollback-{self.args.queue_id}"
                if rollback.exists() or rollback.is_symlink():
                    rollback.unlink()
                if prior_target is None:
                    current.unlink(missing_ok=True)
                else:
                    rollback.symlink_to(prior_target)
                    os.replace(rollback, current)
            except Exception as error:
                rollback_errors.append(f"restore current symlink: {error}")
            if old_stopped:
                try:
                    subprocess.run(["sudo", "-n", "systemctl", "start", OLD_HTTP_UNIT], check=True, timeout=30)
                except Exception as error:
                    rollback_errors.append(f"restart old service: {error}")
            raise RuntimeError(
                f"8035 cutover failed and rollback was attempted: {cutover_error}; "
                f"rollback_errors={rollback_errors}"
            ) from cutover_error
        base.write_json_new(release / "cutover_identity.json",
                            {"url": "http://192.168.100.162:8035/", "release": str(release),
                             "old_unit_stopped": OLD_HTTP_UNIT, "new_unit": EXPLORER_UNIT,
                             "unix_ms": base.unix_ms()})
        self.event("atomic_8035_cutover_pass", release=str(release))

    def run(self) -> int:
        self.initialize()
        try:
            self.preflight(); self.state["status"] = "running"
            self.state["started_unix_ms"] = base.unix_ms(); self.save()
            self.synthetic_oracle(); self.smoke()
            for phase in self.phases:
                self.run_phase(phase)
            self.independent_verify()
            release = self.build_explorer()
            self.cutover(release)
            safe_errors = self.safe_finalize(failed=False)
            if safe_errors:
                raise RuntimeError(f"safe finalization errors: {safe_errors}")
            self.state.update({"status": "completed", "current_phase_index": None,
                               "finished_unix_ms": base.unix_ms(), "explorer_release": str(release),
                               "url": "http://192.168.100.162:8035/"})
            self.save(); self.event("queue_complete"); self.final_manifest(); return 0
        except Exception as error:
            if self.state.get("current_phase_index") is not None:
                index = int(self.state["current_phase_index"])
                if 0 <= index < len(self.phases) and self.phases[index].get("status") != "completed":
                    self.phases[index]["status"] = "failed"
                    self.phases[index]["error"] = f"{type(error).__name__}: {error}"
            safe_errors = self.safe_finalize(failed=True)
            self.state["status"] = "failed"
            self.state["error"] = {"message": f"{type(error).__name__}: {error}",
                                   "traceback": traceback.format_exc(),
                                   "safe_finalize_errors": safe_errors}
            self.state["finished_unix_ms"] = base.unix_ms(); self.save()
            self.event("queue_failed", error=self.state["error"]); return 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--queue-id", required=True)
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--helper-dir", type=Path, required=True)
    parser.add_argument("--measurement-root", type=Path, default=Path("/var/lib/t510/stage35"))
    parser.add_argument("--agent-base", default="http://192.168.100.117:8010")
    parser.add_argument("--receiver-base", default="http://127.0.0.1:8089")
    parser.add_argument("--center-mhz", type=float, default=base.CENTER_MHZ)
    parser.add_argument("--minimum-free-bytes", type=int, default=base.MIN_FREE_BYTES)
    parser.add_argument("--lock", type=Path, default=Path("/run/lock/t510-stage35-xcorr-explorer.lock"))
    parser.add_argument("--sidecar", type=Path, required=True)
    parser.add_argument("--replay-evidence", type=Path, required=True)
    parser.add_argument("--preflight-pcap", type=Path, required=True)
    parser.add_argument("--explorer-root", type=Path, default=Path("/var/lib/t510/stage35/explorer"))
    parser.add_argument("--app-root", type=Path, default=Path("/opt/t510-stage35-explorer/current"))
    parser.add_argument("--analysis-root", type=Path, required=True)
    parser.add_argument("--report-config", type=Path, required=True)
    parser.add_argument("--chrome", type=Path, required=True)
    parser.add_argument("--chromedriver", type=Path, required=True)
    parser.add_argument("--spec-scan", action="append", nargs=2, metavar=("SCAN", "PATH"), required=True)
    args = parser.parse_args()
    args.spec_scans = {scan: path for scan, path in args.spec_scan}
    return args


def main() -> int:
    args = parse_args()
    if not args.queue_id or any(byte not in b"abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_."
                                for byte in args.queue_id.encode("ascii", errors="strict")):
        raise RuntimeError("queue-id contains unsupported characters")
    args.lock.parent.mkdir(parents=True, exist_ok=True)
    with args.lock.open("a+b") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError("another Stage 35 XCORR explorer queue owns the lock") from error
        template = json.loads(args.template.read_text())
        return Queue(args, template).run()


if __name__ == "__main__":
    raise SystemExit(main())
