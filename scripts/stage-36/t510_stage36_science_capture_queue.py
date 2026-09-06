#!/usr/bin/env python3
"""Capture the complete Stage 36 50-ohm science dataset exactly once.

The queue reuses the proven Stage 35 acquisition primitives, but freezes the
current v36 identity and writes only new data below /var/lib/t510/measurements.
Every phase is fail-closed and the finalizer always stops the board and all
measurement workers.
"""

from __future__ import annotations

import argparse
import copy
import fcntl
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import time
import traceback
from typing import Any

import numpy as np


HERE = Path(__file__).resolve().parent
STAGE35 = HERE.parent / "stage-35"
sys.path.insert(0, str(STAGE35))
import t510_stage35_s2_queue as base  # noqa: E402


FORMAT = "T510_STAGE36_SCIENCE_CAPTURE_QUEUE_V1"
EXPECTED_CORE_VERSION = "0x00010036"
EXPECTED_BITSTREAM_SHA256 = "e00c586a1d862d7c7af113361832a30093334493e49f943e3dd22bf44f950665"
EXPECTED_MTS_ADC = 492
EXPECTED_MTS_DAC = -1
EXPECTED_QMC_GAIN = 1.9998779296875
EXPECTED_PFB_SHIFT = 16
EXPECTED_FFT_SHIFT = 0x0556
TIME_SECONDS = 30
FORMAL_SECONDS = 900
SPEC_RAW_PACKETS_PER_BLOCK = 4098
FOCUS_BINS = (
    3327, 3328, 3329, 3181, 3182, 3183, 3134, 3584,
    1115, 2233, 1536, 796, 32, 1047, 3901, 1202,
    3840, 3712, 512, 640, 768, 2560, 128, 256,
    384, 896, 1024, 1280, 1792, 2304, 2816, 3072,
)
ACTIVE_TASKS = (
    "/api/measure/time",
    "/api/measure/autocorrelation",
    "/api/measure/crosscorrelation",
)
CHANNELIZER_ERROR_COUNTERS = (
    "overflow_count",
    "data_halt_count",
    "xfft_event_count",
    "fir_saturation_count",
    "xfft_tlast_unexpected_count",
    "xfft_tlast_missing_count",
    "xfft_fft_overflow_count",
    "xfft_data_out_halt_count",
    "xfft_status_halt_count",
    "capture_backpressure_count",
    "frame_sample0_overflow_count",
    "coefficient_error_count",
)


# The inherited helpers intentionally read these module globals at run time.
base.FORMAT = FORMAT
base.SAMPLE_RATE_MSPS = 320
base.CENTER_MHZ = 200.0
base.EXPECTED_CORE_VERSION = EXPECTED_CORE_VERSION
base.EXPECTED_BITSTREAM_SHA256 = EXPECTED_BITSTREAM_SHA256
base.EXPECTED_MTS_ADC = EXPECTED_MTS_ADC
base.EXPECTED_MTS_DAC = EXPECTED_MTS_DAC
base.EXPECTED_FFT_SHIFT = EXPECTED_FFT_SHIFT


def phase_plan(queue_id: str) -> list[dict[str, Any]]:
    phases: list[dict[str, Any]] = [{
        "index": 0,
        "label": "time-formal",
        "scan": "TIME900",
        "position": "formal",
        "kind": "time",
        "mode": "time_only",
        "duration_seconds": FORMAL_SECONDS,
        "scan_id": f"{queue_id}-time-formal-{FORMAL_SECONDS}s",
        "raw_time_witness": True,
        "status": "pending",
    }]
    for scan in "ABC":
        for position, kind, duration in (
            ("pre", "time", TIME_SECONDS),
            ("scan", "spec", FORMAL_SECONDS),
            ("post", "time", TIME_SECONDS),
        ):
            label = f"self-{scan.lower()}-{kind}-{position}"
            phases.append({
                "index": len(phases), "label": label, "scan": scan,
                "position": position, "kind": kind,
                "mode": "time_only" if kind == "time" else "spec_only",
                "duration_seconds": duration,
                "scan_id": f"{queue_id}-{label}-{duration}s",
                "raw_spec_witness": scan == "A" and kind == "spec",
                "status": "pending",
            })
    for position, kind, duration in (
        ("pre", "time", TIME_SECONDS),
        ("scan", "xcorr", FORMAL_SECONDS),
        ("post", "time", TIME_SECONDS),
    ):
        label = f"pairs-{kind}-{position}"
        phases.append({
            "index": len(phases), "label": label, "scan": "PAIRS",
            "position": position, "kind": kind,
            "mode": "time_only" if kind == "time" else "spec_only",
            "duration_seconds": duration,
            "scan_id": f"{queue_id}-{label}-{duration}s",
            "status": "pending",
        })
    return phases


def _scale_errors(snapshot: dict[str, Any]) -> list[str]:
    scale = snapshot.get("digital_scaling", {})
    errors: list[str] = []
    if scale.get("core_version") != EXPECTED_CORE_VERSION:
        errors.append("DIGITAL_SCALE_CORE_VERSION_MISMATCH")
    if int(scale.get("pfb_output_shift", -1)) != EXPECTED_PFB_SHIFT:
        errors.append("PFB_OUTPUT_SHIFT_MISMATCH")
    if int(scale.get("fft_shift", -1)) != EXPECTED_FFT_SHIFT:
        errors.append("FFT_SHIFT_MISMATCH")
    gains = scale.get("qmc_gain_by_adc", [])
    if len(gains) != 8 or any(float(value) != EXPECTED_QMC_GAIN for value in gains):
        errors.append("QMC_GAIN_MISMATCH")
    if scale.get("errors"):
        errors.append("DIGITAL_SCALE_READBACK_ERROR")
    return errors


def identity_errors(
    snapshot: dict[str, Any], *, mode: str | None, center_mhz: float
) -> list[str]:
    errors = base.board_errors(snapshot, mode=mode, center_mhz=center_mhz)
    if int(snapshot.get("error_flags", 0) or 0) != 0:
        errors.append("FPGA_ERROR_FLAGS_NONZERO")
    errors.extend(_scale_errors(snapshot))
    return errors


def channelizer_delta_errors(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    left, right = before.get("channelizer", {}), after.get("channelizer", {})
    return [
        f"channelizer.{name} delta={int(right.get(name, 0) or 0) - int(left.get(name, 0) or 0)}"
        for name in CHANNELIZER_ERROR_COUNTERS
        if int(right.get(name, 0) or 0) != int(left.get(name, 0) or 0)
    ]


def verify_spec_witness(path: Path) -> dict[str, Any]:
    by_block: list[dict[int, tuple[int, int, int]]] = [dict() for _ in range(16)]
    packet_count = 0
    with path.open("rb") as stream:
        header = stream.read(24)
        if len(header) != 24 or header[:4] != b"\xd4\xc3\xb2\xa1":
            raise RuntimeError("SPEC witness is not little-endian classic PCAP")
        while record := stream.read(16):
            if len(record) != 16:
                raise RuntimeError("truncated SPEC witness record header")
            captured = struct.unpack_from("<I", record, 8)[0]
            frame = stream.read(captured)
            if len(frame) != captured or len(frame) < 42:
                raise RuntimeError("truncated SPEC witness frame")
            ip = 14
            udp = ip + (frame[ip] & 0x0F) * 4
            port = struct.unpack_from("!H", frame, udp + 2)[0]
            payload = frame[udp + 8 :]
            if not 4308 <= port < 4324 or len(payload) != 8320:
                raise RuntimeError(f"unexpected SPEC witness packet port={port}")
            words = struct.unpack_from("<16Q", payload)
            block = (words[9] >> 16) & 0xFFFF
            frame_id, sample0, sequence = words[5], words[4], words[6] >> 32
            group = frame_id // 16
            if (
                words[0] >> 32 != 0x54353130
                or ((words[1] >> 32) & 0xFFFF) != 0
                or block != port - 4308
                or frame_id % 16 != block
            ):
                raise RuntimeError("SPEC witness identity mismatch")
            if group in by_block[block]:
                raise RuntimeError("duplicate SPEC witness frame group")
            by_block[block][group] = (sample0, sequence, frame_id)
            packet_count += 1
    common = sorted(set.intersection(*(set(values) for values in by_block)))
    if len(common) < 4096:
        raise RuntimeError(f"only {len(common)} complete full-band frames, need 4096")
    selected = common[:4096]
    if any(right != left + 1 for left, right in zip(selected, selected[1:])):
        raise RuntimeError("SPEC witness does not contain 4096 contiguous frame groups")
    for group in selected:
        sample0s = {values[group][0] for values in by_block}
        if len(sample0s) != 1:
            raise RuntimeError("SPEC witness cross-block sample0 mismatch")
    return {
        "path": str(path), "bytes": path.stat().st_size,
        "sha256": base.sha256_file(path), "packets": packet_count,
        "complete_contiguous_fullband_frames": 4096,
        "first_frame_group": selected[0], "last_frame_group": selected[-1],
        "first_sample0": by_block[0][selected[0]][0],
    }


def write_cross_manifest(dataset: Path, request: dict[str, Any]) -> dict[str, Any]:
    zarr = dataset / "xcorr.zarr"
    attrs = json.loads((zarr / ".zattrs").read_text(encoding="utf-8"))
    seconds = int(request["duration_seconds"])
    rows100 = seconds * 10
    if attrs.get("complete") is not True or attrs.get("save_fullband_100ms") is not True:
        raise RuntimeError("XCORR full-band 100 ms product is not complete")
    expected = {
        "mean_auto_power_count2": ([seconds, 8, 4096], [1, 8, 256], "<f8"),
        "mean_cross_visibility_count2": ([seconds, 28, 4096], [1, 28, 256], "<c16"),
        "mean_auto_power_count2_100ms": ([rows100, 8, 4096], [10, 8, 256], "<f8"),
        "mean_cross_visibility_count2_100ms": ([rows100, 28, 4096], [10, 28, 256], "<c16"),
    }
    for name, (shape, chunks, dtype) in expected.items():
        meta = json.loads((zarr / name / ".zarray").read_text(encoding="utf-8"))
        if meta.get("shape") != shape or meta.get("chunks") != chunks or meta.get("dtype") != dtype:
            raise RuntimeError(f"XCORR array contract mismatch for {name}: {meta}")
    quality = [json.loads(row) for row in (dataset / "quality_ledger.jsonl").read_text().splitlines()]
    quality100 = [json.loads(row) for row in (dataset / "quality_ledger_100ms.jsonl").read_text().splitlines()]
    if len(quality) != seconds or len(quality100) != rows100:
        raise RuntimeError("XCORR quality ledger coverage mismatch")
    if any(not row.get("complete") or any(row.get("ring_drops", [])) for row in quality):
        raise RuntimeError("XCORR one-second quality ledger failed")
    if any(any(row.get("ring_drops", [])) or int(row.get("n_valid", 0)) <= 0 for row in quality100):
        raise RuntimeError("XCORR 100 ms quality ledger failed")
    files = []
    for path in sorted(item for item in dataset.rglob("*") if item.is_file()):
        if path.name in ("dataset_manifest.json", "dataset_manifest.sha256"):
            continue
        files.append({"path": path.relative_to(dataset).as_posix(), "bytes": path.stat().st_size,
                      "sha256": base.sha256_file(path)})
    manifest = {
        "format": "T510_STAGE36_CROSSCORRELATION_DATASET_MANIFEST_V1",
        "complete": True, "request": request,
        "visibility_definition": "mean(Xa*conj(Xb))",
        "pair_index": [[a, b] for a in range(8) for b in range(a + 1, 8)],
        "products": {"native_fullband_bucket_ms": 100, "derived_fullband_bucket_ms": 1000},
        "quality": {"ring_drops": 0, "seconds": seconds, "rows_100ms": rows100},
        "files": files,
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
        self.state.update({
            "format": FORMAT,
            "phases": self.phases,
            "source_commit": args.source_commit,
            "physical_context": {
                "rf_inputs": "eight_independent_50ohm_operator_confirmed_unchanged",
                "external_10mhz_pps": "operator_confirmed_disconnected",
                "clock_reference": "onboard_tcxo",
                "dac": "disabled",
            },
            "products": [
                "TIME_ONLY_900s_10ms_plus_100ms_1s",
                "TIME_ONLY_contiguous_50ms_raw_witness",
                "autocorrelation_A_B_C_900s_with_30s_TIME_controls",
                "SPEC_contiguous_4096_frame_fullband_raw_witness",
                "all_28_pairs_fullband_100ms_plus_derived_1s_900s",
            ],
        })

    def preflight(self) -> None:
        usage = shutil.disk_usage(self.args.measurement_root)
        identity_paths = {
            "queue": Path(__file__).resolve(),
            "stage35_acquisition_primitives": Path(base.__file__).resolve(),
            "time_verifier": (self.args.helper_dir / "t510_stage35_time_verify.py").resolve(),
            "stage36_amplitude_verifier": (HERE / "t510_stage36_short_gate.py").resolve(),
            "configure_template": self.args.template.resolve(),
            "cuda_sidecar": self.args.sidecar.resolve(),
        }
        base.write_json_new(self.evidence / "implementation_identity.json", {
            "source_commit": self.args.source_commit,
            "files": {name: {"path": str(path), "bytes": path.stat().st_size,
                             "sha256": base.sha256_file(path)}
                      for name, path in identity_paths.items()},
        })
        base.write_json_new(self.evidence / "disk_preflight.json", {
            "total": usage.total, "used": usage.used, "free": usage.free,
        })
        errors: list[str] = []
        if usage.free < self.args.minimum_free_bytes:
            errors.append(f"free bytes {usage.free} below {self.args.minimum_free_bytes}")
        for phase in self.phases:
            if (self.args.measurement_root / phase["scan_id"]).exists():
                errors.append(f"scan already exists: {phase['scan_id']}")
        board, receiver = self.board(), self.receiver()
        base.write_json_new(self.evidence / "board_preflight.json", board)
        base.write_json_new(self.evidence / "receiver_preflight.json", receiver)
        profile = board.get("profile", {})
        mode = str(profile.get("mode", ""))
        center = float(profile.get("center_mhz", 0.0))
        identity = identity_errors(board, mode=mode, center_mhz=center)
        # A completed standard gate may leave the stopped board at 160 MS/s.
        # The first phase performs a verified hot update to 320 MS/s.
        errors.extend(row for row in identity if not row.startswith("sample_rate_msps="))
        if int(profile.get("sample_rate_msps", 0)) not in (160, 320):
            errors.append(f"unsupported stopped sample rate: {profile.get('sample_rate_msps')}")
        if board.get("streaming"):
            errors.append("board is streaming")
        if float(receiver.get("stats", {}).get("packets_per_sec", 0.0) or 0.0):
            errors.append("receiver reports live packets")
        for endpoint in ACTIVE_TASKS:
            status = self.receiver(endpoint + "/status")
            if status.get("status") in ("armed", "running", "draining"):
                errors.append(f"active task {endpoint}: {status.get('status')}")
        catalog = self.board("/api/v2/bitstreams")
        rows = catalog.get("bitstreams", [])
        if len(rows) != 1 or rows[0].get("id") != "fengine-current":
            errors.append("catalog is not single current release")
        elif rows[0].get("sha256") != EXPECTED_BITSTREAM_SHA256:
            errors.append("catalog bitstream SHA mismatch")
        elif rows[0].get("mts_qualifications", {}).get("onboard_tcxo", {}).get("status") != "qualified":
            errors.append("onboard reference is not qualified")
        if not self.args.sidecar.is_file() or not os.access(self.args.sidecar, os.X_OK):
            errors.append(f"CUDA sidecar is not executable: {self.args.sidecar}")
        else:
            completed = subprocess.run(
                [str(self.args.sidecar), "--self-test"], text=True,
                capture_output=True, timeout=180, check=False,
            )
            base.write_json_new(self.evidence / "cuda_sidecar_self_test.json", {
                "argv": [str(self.args.sidecar), "--self-test"],
                "returncode": completed.returncode,
                "stdout": completed.stdout, "stderr": completed.stderr,
            })
            if completed.returncode:
                errors.append("CUDA sidecar self-test failed")
        if errors:
            raise RuntimeError(f"Stage 36 science preflight failed: {errors}")
        self.event("preflight_pass", disk_free_bytes=usage.free)

    def ensure_mode(self, phase: dict[str, Any]) -> None:
        mode = phase["mode"]
        self.stop_board(f"phase_{phase['index']:02d}_stop_before.json")
        self.wait_receiver_quiescent()
        applied_receiver = self.receiver(
            "/api/config", method="POST",
            body=base.receiver_config(mode, self.args.center_mhz),
        )
        base.write_json_new(
            self.evidence / f"phase_{phase['index']:02d}_receiver_config.json",
            applied_receiver,
        )
        board = self.board()
        profile = board.get("profile", {})
        if (
            int(profile.get("sample_rate_msps", 0)) != 320
            or profile.get("mode") != mode
            or abs(float(profile.get("center_mhz", 0.0)) - self.args.center_mhz) > 1.0e-6
        ):
            configured = self.board(
                "/api/v2/configure", method="POST",
                body=base.configure_body(self.template, mode, self.args.center_mhz),
                timeout=300.0,
            )
            base.write_json_new(
                self.evidence / f"phase_{phase['index']:02d}_hot_configure.json",
                configured,
            )
            bitstream = configured.get("bitstream", {})
            journal = (configured.get("hot_update", {}) or {}).get("journal", {})
            if bitstream.get("sha256") != EXPECTED_BITSTREAM_SHA256:
                raise RuntimeError(f"hot configure bitstream identity mismatch: {bitstream}")
            if configured.get("update_mode") != "clock_preserving" or not journal.get("ready"):
                raise RuntimeError(f"hot configure did not reach READY: {configured.get('hot_update')}")
            board = self.board()
        errors = identity_errors(board, mode=mode, center_mhz=self.args.center_mhz)
        errors.extend(base.receiver_errors(
            self.receiver(), mode=mode, center_mhz=self.args.center_mhz))
        if errors:
            raise RuntimeError(f"mode transition validation failed: {errors}")
        self.event("mode_ready", phase=phase["label"], mode=mode)

    def _capture_time_witness(self, phase: dict[str, Any]) -> dict[str, Any]:
        superset = self.raw / "time-formal-52ms-superset.pcap"
        cropped = self.raw / "time-formal-50ms.pcap"
        before_board, before_receiver = self.board(), self.receiver()
        identity = base.http_to_new_file(
            self.args.receiver_base.rstrip("/") + "/api/capture/spec-pcap", superset,
            body={"packets_per_block": base.TIME_RAW_PACKETS_PER_FLOW,
                  "include_time": True, "time_only": True}, timeout=240,
        )
        integrity = base.formal_integrity(before_board, self.board(), before_receiver, self.receiver())
        if not integrity["ok"]:
            raise RuntimeError(f"TIME raw witness integrity failed: {integrity['errors']}")
        sys.path.insert(0, str(self.args.helper_dir))
        from t510_stage35_time_verify import crop_continuous_pcap, verify_pcap
        result = {"superset": identity, "crop": crop_continuous_pcap(superset, cropped),
                  "verified": verify_pcap(cropped), "receiver_integrity": integrity,
                  "phase": phase["label"]}
        base.write_json_new(self.evidence / "time_raw_witness.json", result)
        return result

    def _capture_spec_witness(self, phase: dict[str, Any]) -> dict[str, Any]:
        path = self.raw / "spec-fullband-4096frames.pcap"
        before_board, before_receiver = self.board(), self.receiver()
        identity = base.http_to_new_file(
            self.args.receiver_base.rstrip("/") + "/api/capture/spec-pcap", path,
            body={"packets_per_block": SPEC_RAW_PACKETS_PER_BLOCK,
                  "include_time": False, "time_only": False}, timeout=300,
        )
        after_board, after_receiver = self.board(), self.receiver()
        integrity = base.formal_integrity(before_board, after_board, before_receiver, after_receiver)
        integrity["errors"].extend(channelizer_delta_errors(before_board, after_board))
        integrity["ok"] = not integrity["errors"]
        if not integrity["ok"]:
            raise RuntimeError(f"SPEC raw witness integrity failed: {integrity['errors']}")
        result = {"capture": identity, "verified": verify_spec_witness(path),
                  "receiver_integrity": integrity, "phase": phase["label"]}
        base.write_json_new(self.evidence / "spec_raw_witness.json", result)
        return result

    def _begin_common(self, phase: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        phase.update(status="starting", started_unix_ms=base.unix_ms())
        self.state["current_phase_index"] = phase["index"]
        self.save(); self.event("phase_starting", phase=phase["label"], scan_id=phase["scan_id"])
        self.ensure_mode(phase)
        return self.board(), self.receiver()

    def _finish_common(
        self, phase: dict[str, Any], before_board: dict[str, Any], before_receiver: dict[str, Any],
        final_status: dict[str, Any], telemetry: list[dict[str, Any]],
        manifest_builder: Any, raw_witness: dict[str, Any] | None,
    ) -> None:
        after_board, after_receiver = self.board(), self.receiver()
        base.write_json_new(self.evidence / f"phase_{phase['index']:02d}_board_after.json", after_board)
        base.write_json_new(self.evidence / f"phase_{phase['index']:02d}_receiver_after.json", after_receiver)
        integrity = base.formal_integrity(before_board, after_board, before_receiver, after_receiver)
        integrity["errors"].extend(channelizer_delta_errors(before_board, after_board))
        integrity["errors"].extend(identity_errors(
            after_board, mode=phase["mode"], center_mhz=self.args.center_mhz))
        integrity["ok"] = not integrity["errors"]
        if not integrity["ok"]:
            raise RuntimeError(f"{phase['label']} formal integrity failed: {integrity['errors']}")
        self.stop_board(f"phase_{phase['index']:02d}_stop_after.json")
        manifest = manifest_builder()
        phase.update(status="completed", finished_unix_ms=base.unix_ms(),
                     capture_status=final_status, manifest=manifest,
                     formal_integrity=integrity, telemetry_samples=len(telemetry),
                     raw_witness=raw_witness)
        self.save(); self.event("phase_complete", phase=phase["label"],
                                manifest_sha256=manifest["sha256"])

    def run_time_or_spec(self, phase: dict[str, Any]) -> None:
        self._begin_common(phase)
        self.start_stream(phase)
        raw = self._capture_spec_witness(phase) if phase.get("raw_spec_witness") else None
        before_board, before_receiver = self.board(), self.receiver()
        self.seed_telemetry_cursor(before_board)
        base.write_json_new(self.evidence / f"phase_{phase['index']:02d}_board_before.json", before_board)
        base.write_json_new(self.evidence / f"phase_{phase['index']:02d}_receiver_before.json", before_receiver)
        request = {
            "scan_id": phase["scan_id"],
            "tuning_id": f"center-{self.args.center_mhz:g}mhz-{phase['mode']}",
            "duration_seconds": phase["duration_seconds"], "native_bucket_ms": 10,
            "sample_rate_msps": 320, "center_mhz": self.args.center_mhz,
            "metadata": {
                "stage": "36", "queue_id": self.args.queue_id, "scan": phase["scan"],
                "position": phase["position"], "clock_reference": "onboard_tcxo",
                "physical_input": "eight_independent_50ohm_operator_confirmed",
                "scaling_profile": "qmc16383of8192-pfb16-fft0556",
                "simultaneity": "adjacent_time_control_not_simultaneous_with_spectrum",
            },
        }
        endpoint = "/api/measure/autocorrelation" if phase["kind"] == "spec" else "/api/measure/time"
        if phase["kind"] == "spec":
            request["expected_fft_shift"] = EXPECTED_FFT_SHIFT
        started = self.receiver(endpoint, method="POST", body=request)
        phase.update(capture_start=started, status="running"); self.save()
        final_status, telemetry = self.monitor_capture(phase, endpoint + "/status")
        if phase.get("raw_time_witness"):
            raw = self._capture_time_witness(phase)
        dataset = self.args.measurement_root / phase["scan_id"]
        self._finish_common(
            phase, before_board, before_receiver, final_status, telemetry,
            lambda: base.verify_manifest_basic(dataset, phase), raw,
        )

    def run_xcorr(self, phase: dict[str, Any]) -> None:
        prearm_board, prearm_receiver = self._begin_common(phase)
        request = {
            "scan_id": phase["scan_id"],
            "tuning_id": f"center-{self.args.center_mhz:g}mhz-fullband-xcorr",
            "duration_seconds": phase["duration_seconds"],
            "fullband_bucket_ms": 1000, "focus_bucket_ms": 100,
            "save_fullband_100ms": True,
            "sample_rate_msps": 320, "center_mhz": self.args.center_mhz,
            "focus_global_bins": list(FOCUS_BINS), "lane_mask": 255,
            "expected_fft_shift": EXPECTED_FFT_SHIFT,
            "metadata": {
                "stage": "36", "queue_id": self.args.queue_id,
                "scan": "PAIRS", "clock_reference": "onboard_tcxo",
                "physical_input": "eight_independent_50ohm_operator_confirmed",
                "interpretation": "instrument_false_correlation_floor_not_sky",
                "scaling_profile": "qmc16383of8192-pfb16-fft0556",
            },
        }
        started = self.receiver("/api/measure/crosscorrelation", method="POST", body=request)
        start_snapshot = self.start_stream(phase)
        before_receiver = self.receiver()
        warm = self.receiver("/api/measure/crosscorrelation/status")
        if warm.get("status") != "armed" or int(warm.get("progress", {}).get("packets_published", -1)) != 0:
            raise RuntimeError(f"XCORR formal window started before integrity snapshot: {warm}")
        startup = base.formal_integrity(prearm_board, start_snapshot, prearm_receiver, before_receiver)
        if [error for error in startup["errors"] if error.startswith("receiver.")]:
            raise RuntimeError(f"XCORR arm/start receiver loss: {startup['errors']}")
        base.write_json_new(self.evidence / f"phase_{phase['index']:02d}_startup_integrity.json", startup)
        before_board = start_snapshot
        self.seed_telemetry_cursor(before_board)
        base.write_json_new(self.evidence / f"phase_{phase['index']:02d}_board_before.json", before_board)
        base.write_json_new(self.evidence / f"phase_{phase['index']:02d}_receiver_before.json", before_receiver)
        phase.update(capture_start=started, status="running"); self.save()
        final_status, telemetry = self.monitor_capture(
            phase, "/api/measure/crosscorrelation/status")
        dataset = self.args.measurement_root / phase["scan_id"]
        self._finish_common(
            phase, before_board, before_receiver, final_status, telemetry,
            lambda: write_cross_manifest(dataset, request), None,
        )

    def run_phase(self, phase: dict[str, Any]) -> None:
        if phase["kind"] == "xcorr":
            self.run_xcorr(phase)
        else:
            self.run_time_or_spec(phase)

    def independent_verify(self) -> None:
        results: list[dict[str, Any]] = []
        for phase in self.phases:
            dataset = self.args.measurement_root / phase["scan_id"]
            manifest = json.loads((dataset / "dataset_manifest.json").read_text())
            for item in manifest.get("files", []):
                path = dataset / item["path"]
                if path.stat().st_size != int(item["bytes"]) or base.sha256_file(path) != item["sha256"]:
                    raise RuntimeError(f"sealed file identity mismatch: {path}")
            results.append({"scan_id": phase["scan_id"], "kind": phase["kind"],
                            "manifest_sha256": base.sha256_file(dataset / "dataset_manifest.json")})

        formal = self.phases[0]
        formal_root = self.args.measurement_root / formal["scan_id"]
        time_verify = self.evidence / "time900_verification.json"
        completed = subprocess.run([
            sys.executable, str(self.args.helper_dir / "t510_stage35_time_verify.py"),
            str(formal_root), "--output", str(time_verify),
        ], text=True, capture_output=True, timeout=1800, check=False)
        base.write_json_new(self.evidence / "time900_verification_process.json", {
            "returncode": completed.returncode, "stdout": completed.stdout, "stderr": completed.stderr,
        })
        if completed.returncode or json.loads(time_verify.read_text()).get("status") != "PASS":
            raise RuntimeError("independent TIME900 verification failed")

        # Materialize the requested 100 ms and 1 s TIME products from the sealed
        # native 10 ms rows using sample-count weighted means.
        import csv
        native: dict[tuple[int, int], tuple[float, float, float, int]] = {}
        with (formal_root / "time_10ms.csv").open(newline="") as stream:
            for row in csv.DictReader(stream):
                native[(int(row["bucket"]), int(row["lane"]))] = (
                    float(row["mean_i_adu"]), float(row["mean_q_adu"]),
                    float(row["mean_power_adu2"]), int(row["samples"]),
                )
        derived: dict[str, np.ndarray] = {}
        for label, width in (("time_100ms", 10), ("time_1s", 100)):
            rows = FORMAL_SECONDS * 100 // width
            output = np.empty((rows, 8, 3), dtype="<f8")
            for index in range(rows):
                for lane in range(8):
                    values = [native[(bucket, lane)] for bucket in range(index * width, (index + 1) * width)]
                    weights = np.asarray([row[3] for row in values], dtype=np.float64)
                    output[index, lane] = np.average(np.asarray([row[:3] for row in values]), axis=0, weights=weights)
            derived[label] = output
        derived_path = self.evidence / "time_derived_100ms_1s.npz"
        np.savez_compressed(derived_path, **derived)

        sys.path.insert(0, str(HERE))
        from t510_stage36_short_gate import numerical_errors, spec_stats, time_stats
        time_result = time_stats(self.raw / "time-formal-50ms.pcap")
        spec_result = spec_stats(self.raw / "spec-fullband-4096frames.pcap", self.evidence)
        amplitude_errors = numerical_errors(time_result, spec_result)
        base.write_json_new(self.evidence / "formal_amplitude_verification.json", {
            "status": "PASS" if not amplitude_errors else "FAIL",
            "time": time_result, "spec": spec_result, "errors": amplitude_errors,
        })
        if amplitude_errors:
            raise RuntimeError(f"Stage 36 amplitude gate failed: {amplitude_errors}")
        base.write_json_new(self.evidence / "independent_verification.json", {
            "status": "PASS", "scans": results,
            "time_derived": {"path": str(derived_path), "sha256": base.sha256_file(derived_path)},
            "raw_time_frames": 62_500, "raw_spec_fullband_frames": 4096,
            "fullband_xcorr_100ms": True,
        })
        self.event("independent_verification_pass", scan_count=len(results))

    def safe_finalize(self, *, failed: bool) -> list[str]:
        errors: list[str] = []
        for endpoint in ACTIVE_TASKS:
            try:
                status = self.receiver(endpoint + "/status")
                if status.get("status") in ("armed", "running", "draining"):
                    self.receiver(endpoint + "/stop", method="POST",
                                  body={"reason": "Stage 36 queue finalization"})
            except Exception as exc:
                errors.append(f"{endpoint} STOP: {type(exc).__name__}: {exc}")
        errors.extend(super().safe_finalize(failed=failed))
        return errors

    def final_manifest(self) -> None:
        files = []
        for path in sorted(item for item in self.root.rglob("*") if item.is_file()):
            if path.name in ("queue_manifest.json", "queue_manifest.sha256"):
                continue
            files.append({"path": path.relative_to(self.root).as_posix(),
                          "bytes": path.stat().st_size, "sha256": base.sha256_file(path)})
        manifest = {
            "format": "T510_STAGE36_SCIENCE_CAPTURE_MANIFEST_V1",
            "complete": True, "queue_id": self.args.queue_id,
            "bitstream_sha256": EXPECTED_BITSTREAM_SHA256,
            "core_version": EXPECTED_CORE_VERSION,
            "scans": [{"scan_id": phase["scan_id"], "kind": phase["kind"],
                       "duration_seconds": phase["duration_seconds"],
                       "manifest": phase["manifest"]} for phase in self.phases],
            "files": files,
        }
        path = self.root / "queue_manifest.json"
        base.write_json_new(path, manifest)
        (self.root / "queue_manifest.sha256").write_text(
            f"{base.sha256_file(path)}  queue_manifest.json\n", encoding="ascii")

    def run(self) -> int:
        self.initialize()
        try:
            self.preflight()
            self.state.update(status="running", started_unix_ms=base.unix_ms())
            self.save()
            for phase in self.phases:
                self.run_phase(phase)
            self.independent_verify()
            safe_errors = self.safe_finalize(failed=False)
            if safe_errors:
                raise RuntimeError(f"safe finalization errors: {safe_errors}")
            self.state.update(status="completed", current_phase_index=None,
                              finished_unix_ms=base.unix_ms())
            self.save(); self.event("queue_complete"); self.final_manifest()
            return 0
        except Exception as exc:
            current = self.state.get("current_phase_index")
            if current is not None:
                phase = self.phases[int(current)]
                if phase.get("status") != "completed":
                    phase.update(status="failed", error=f"{type(exc).__name__}: {exc}")
            safe_errors = self.safe_finalize(failed=True)
            self.state.update(status="failed", finished_unix_ms=base.unix_ms(), error={
                "message": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(), "safe_finalize_errors": safe_errors,
            })
            self.save(); self.event("queue_failed", error=self.state["error"])
            return 1

    def resume_after_time_witness_import_failure(self) -> int:
        """Resume the one registered phase-0 failure without recapturing TIME900.

        The original receiver task and 52 ms PCAP completed before the bad import
        was evaluated.  This path first proves those immutable products, records
        the missing post-window snapshot as unavailable, and then continues at
        phase 1.  It deliberately refuses every other failure shape.
        """
        registered_error = "ModuleNotFoundError: No module named 't510_time_capture_verify'"
        if not self.state_path.is_file():
            raise RuntimeError(f"resume state does not exist: {self.state_path}")
        loaded = json.loads(self.state_path.read_text(encoding="utf-8"))
        if loaded.get("format") != FORMAT or loaded.get("queue_id") != self.args.queue_id:
            raise RuntimeError("resume queue identity mismatch")
        if loaded.get("status") != "failed" or loaded.get("error", {}).get("message") != registered_error:
            raise RuntimeError("queue did not stop at the registered TIME witness import failure")
        phases = loaded.get("phases", [])
        if len(phases) != 13 or phases[0].get("status") != "failed":
            raise RuntimeError("registered resume requires failed phase 0 and the complete 13-phase plan")
        if phases[0].get("error") != registered_error:
            raise RuntimeError("phase-0 error does not match the registered failure")
        if any(phase.get("status") != "pending" for phase in phases[1:]):
            raise RuntimeError("registered resume requires every later phase to remain pending")
        if loaded.get("source_commit") != "5d9316a":
            raise RuntimeError("registered failure source identity mismatch")

        self.state = loaded
        self.phases = phases
        self.telemetry_since_seq = 0
        self.telemetry_epoch_id = None
        recovery_committed = False
        try:
            usage = shutil.disk_usage(self.args.measurement_root)
            errors: list[str] = []
            if usage.free < self.args.minimum_free_bytes:
                errors.append(f"free bytes {usage.free} below {self.args.minimum_free_bytes}")
            for phase in phases[1:]:
                if (self.args.measurement_root / phase["scan_id"]).exists():
                    errors.append(f"unregistered later scan already exists: {phase['scan_id']}")
            board, receiver = self.board(), self.receiver()
            if board.get("streaming"):
                errors.append("board is streaming")
            if float(receiver.get("stats", {}).get("packets_per_sec", 0.0) or 0.0):
                errors.append("receiver reports live packets")
            for endpoint in ACTIVE_TASKS:
                status = self.receiver(endpoint + "/status")
                if endpoint == "/api/measure/time" and status.get("status") == "completed":
                    request = status.get("request", {})
                    if request.get("scan_id") != phases[0]["scan_id"]:
                        errors.append("completed TIME task belongs to another scan")
                elif status.get("status") in ("armed", "running", "draining"):
                    errors.append(f"active task {endpoint}: {status.get('status')}")
            current_mode = str(board.get("profile", {}).get("mode", ""))
            current_center = float(board.get("profile", {}).get("center_mhz", 0.0))
            errors.extend(
                row for row in identity_errors(board, mode=current_mode, center_mhz=current_center)
                if not row.startswith("sample_rate_msps=")
            )
            catalog = self.board("/api/v2/bitstreams").get("bitstreams", [])
            if len(catalog) != 1 or catalog[0].get("id") != "fengine-current":
                errors.append("catalog is not single current release")
            elif catalog[0].get("sha256") != EXPECTED_BITSTREAM_SHA256:
                errors.append("catalog bitstream SHA mismatch")
            elif catalog[0].get("mts_qualifications", {}).get("onboard_tcxo", {}).get("status") != "qualified":
                errors.append("onboard reference is not qualified")
            if errors:
                raise RuntimeError(f"resume preflight failed: {errors}")
            resume_number = len(self.state.get("resume_history", [])) + 1
            attempt_id = base.unix_ms()
            base.write_json_new(self.evidence / f"resume_{resume_number:02d}_{attempt_id}_preflight.json", {
                "registered_failure": registered_error,
                "resume_source_commit": self.args.source_commit,
                "disk_free_bytes": usage.free,
                "board": board,
                "receiver": receiver,
                "queue_script": {"path": str(Path(__file__).resolve()),
                                 "sha256": base.sha256_file(Path(__file__).resolve())},
            })

            formal = phases[0]
            dataset = self.args.measurement_root / formal["scan_id"]
            manifest = base.verify_manifest_basic(dataset, formal)
            sys.path.insert(0, str(self.args.helper_dir))
            from t510_stage35_time_verify import crop_continuous_pcap, verify, verify_pcap
            time_verification = verify(dataset)
            superset = self.raw / "time-formal-52ms-superset.pcap"
            cropped = self.raw / "time-formal-50ms.pcap"
            if not superset.is_file() or cropped.with_name(cropped.name + ".partial").exists():
                raise RuntimeError("TIME witness files are not in a recoverable state")
            superset_identity = {"path": str(superset), "bytes": superset.stat().st_size,
                                 "sha256": base.sha256_file(superset)}
            crop = (verify_pcap(cropped) if cropped.exists()
                    else crop_continuous_pcap(superset, cropped))
            raw = {
                "superset": superset_identity,
                "crop": crop,
                "verified": verify_pcap(cropped),
                "receiver_integrity": {
                    "ok": True,
                    "evidence": "reconstructed_after_registered_post-capture_import_failure",
                    "dataset_verification": time_verification,
                    "limitation": "The live post-window board/receiver snapshot was not persisted before the import failed; continuity is established by the sealed receiver manifest, eight-flow quality ledger, telemetry, and raw PCAP.",
                },
                "phase": formal["label"],
            }
            witness_path = self.evidence / "time_raw_witness.json"
            if witness_path.exists():
                prior_witness = json.loads(witness_path.read_text(encoding="utf-8"))
                if prior_witness.get("verified", {}).get("sha256") != raw["verified"]["sha256"]:
                    raise RuntimeError("existing recovered TIME witness identity mismatch")
                raw = prior_witness
            else:
                base.write_json_new(witness_path, raw)
            telemetry = json.loads((self.evidence / "phase_00_telemetry.json").read_text(encoding="utf-8"))
            formal.update(
                status="completed",
                finished_unix_ms=base.unix_ms(),
                capture_status=self.receiver("/api/measure/time/status"),
                manifest=manifest,
                formal_integrity={
                    "ok": True,
                    "evidence": "post_failure_recovery_audit",
                    "dataset_verification": time_verification,
                    "raw_witness_sha256": raw["verified"]["sha256"],
                    "telemetry_samples": len(telemetry),
                    "limitation": raw["receiver_integrity"]["limitation"],
                },
                telemetry_samples=len(telemetry),
                raw_witness=raw,
                recovered_after_registered_failure=True,
            )
            formal.pop("error", None)
            history = self.state.setdefault("resume_history", [])
            history.append({
                "resume_number": resume_number,
                "resumed_unix_ms": base.unix_ms(),
                "resume_source_commit": self.args.source_commit,
                "original_error": self.state.get("error"),
                "reused_scan_id": formal["scan_id"],
                "reused_manifest_sha256": manifest["sha256"],
            })
            self.state.update(status="running", current_phase_index=None,
                              finished_unix_ms=None, error=None)
            self.save()
            recovery_committed = True
            self.event("registered_failure_recovered", phase=formal["label"],
                       manifest_sha256=manifest["sha256"], resume_number=resume_number)

            for phase in phases[1:]:
                self.run_phase(phase)
            self.independent_verify()
            safe_errors = self.safe_finalize(failed=False)
            if safe_errors:
                raise RuntimeError(f"safe finalization errors: {safe_errors}")
            self.state.update(status="completed", current_phase_index=None,
                              finished_unix_ms=base.unix_ms())
            self.save(); self.event("queue_complete"); self.final_manifest()
            return 0
        except Exception as exc:
            if not recovery_committed:
                safe_errors = self.safe_finalize(failed=True)
                self.event("registered_failure_recovery_failed", error={
                    "message": f"{type(exc).__name__}: {exc}",
                    "traceback": traceback.format_exc(), "safe_finalize_errors": safe_errors,
                })
                return 1
            current = self.state.get("current_phase_index")
            if current is not None:
                phase = self.phases[int(current)]
                if phase.get("status") != "completed":
                    phase.update(status="failed", error=f"{type(exc).__name__}: {exc}")
            safe_errors = self.safe_finalize(failed=True)
            self.state.update(status="failed", finished_unix_ms=base.unix_ms(), error={
                "message": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(), "safe_finalize_errors": safe_errors,
            })
            self.save(); self.event("queue_failed", error=self.state["error"])
            return 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue-id", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--helper-dir", type=Path, required=True)
    parser.add_argument("--measurement-root", type=Path,
                        default=Path("/var/lib/t510/measurements"))
    parser.add_argument("--agent-base", default="http://192.168.100.117:8010")
    parser.add_argument("--receiver-base", default="http://127.0.0.1:8089")
    parser.add_argument("--center-mhz", type=float, default=200.0)
    parser.add_argument("--minimum-free-bytes", type=int, default=250 * 1024**3)
    parser.add_argument("--sidecar", type=Path,
                        default=Path("/opt/t510-time-rx/current/t510_xcorr_cuda"))
    parser.add_argument("--lock", type=Path,
                        default=Path("/run/lock/t510-stage36-science.lock"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--resume-after-time-witness-import-failure", action="store_true")
    args = parser.parse_args()
    allowed = b"abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_."
    if not args.queue_id or any(byte not in allowed for byte in args.queue_id.encode("ascii")):
        parser.error("queue-id contains unsupported characters")
    return args


def main() -> int:
    args = parse_args()
    if args.dry_run:
        print(json.dumps({
            "format": FORMAT, "queue_id": args.queue_id,
            "source_commit": args.source_commit,
            "core_version": EXPECTED_CORE_VERSION,
            "bitstream_sha256": EXPECTED_BITSTREAM_SHA256,
            "measurement_root": str(args.measurement_root),
            "phases": phase_plan(args.queue_id),
        }, indent=2, sort_keys=True))
        return 0
    args.lock.parent.mkdir(parents=True, exist_ok=True)
    with args.lock.open("a+b") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("another Stage 36 science queue owns the lock") from exc
        template = json.loads(args.template.read_text(encoding="utf-8"))
        queue = Queue(args, template)
        if args.resume_after_time_witness_import_failure:
            return queue.resume_after_time_witness_import_failure()
        return queue.run()


if __name__ == "__main__":
    raise SystemExit(main())
