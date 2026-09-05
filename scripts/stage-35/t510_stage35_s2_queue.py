#!/usr/bin/env python3
"""Run the fixed Stage 35 S2 TIME/SPEC/TIME A/B/C queue exactly once.

The runner is intentionally fail-closed: the complete queue is journaled before
hardware mutation, phases never retry, and any failure stops the board and
preserves the queue directory for inspection.
"""

from __future__ import annotations

import argparse
import copy
import fcntl
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


FORMAT = "T510_STAGE35_S2_QUEUE_V1"
SAMPLE_RATE_MSPS = 320
CENTER_MHZ = 1020.0
BOARD_ID = 1
NATIVE_BUCKET_MS = 10
TIME_SECONDS = 30
SPEC_SECONDS = 900
MIN_FREE_BYTES = 250 * 1024**3
TIME_RAW_PACKETS_PER_FLOW = 8192
SPEC_RAW_PACKETS_PER_BLOCK = 256
EXPECTED_CORE_VERSION = "0x00010034"
EXPECTED_BITSTREAM_SHA256 = "c21d93f5ea71e9ac17a4448cff138a8faaf9c7347d879be919b680d196b8a5be"
EXPECTED_CLOCK_PROFILE = "160m_10m_request_manual_clkin0"
EXPECTED_CLOCK_SHA256 = "a8504d384354610f8f130b1cda1a446bcdfb25bf8c4bb689fbb58adefe5e88e2"
EXPECTED_MTS_ADC = 416
EXPECTED_MTS_DAC = 112
EXPECTED_FFT_SHIFT = 1366
STREAM_SPEC = 0

BOARD_COUNTERS = (
    "rfdc_dropped",
    "science_dropped_beats",
    "spec_dropped",
    "time_dropped",
    "tx_frames_dropped",
    "tx_route_error",
    "tx_route_miss",
)
RECEIVER_COUNTERS = (
    "kernel_drops",
    "ring_drops",
    "worker_ring_drops",
    "app_drops",
    "parse_errors",
    "seq_gaps",
    "frame_gaps",
    "sample0_gaps",
    "spec_seq_gaps",
    "spec_frame_gaps",
)
RECEIVER_INSTANTANEOUS_ERRORS = (
    "nic_rx_errors_delta",
    "nic_rx_dropped_delta",
    "nic_rx_missed_errors_delta",
    "nic_rx_crc_errors_delta",
)


def unix_ms() -> int:
    return time.time_ns() // 1_000_000


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".partial")
    encoded = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    with partial.open("wb") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
    partial.replace(path)


def write_json_new(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    with path.open("xb") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())


def append_event(path: Path, event: str, **fields: Any) -> None:
    row = {"unix_ms": unix_ms(), "event": event, **fields}
    with path.open("ab") as stream:
        stream.write((json.dumps(row, sort_keys=True) + "\n").encode("utf-8"))
        stream.flush()
        os.fsync(stream.fileno())


def http_request(
    url: str,
    *,
    method: str = "GET",
    body: dict[str, Any] | None = None,
    timeout: float = 30.0,
    accept: str = "application/json",
) -> urllib.response.addinfourl:
    request = urllib.request.Request(
        url,
        data=None if body is None else json.dumps(body).encode("utf-8"),
        headers={
            "Accept": accept,
            **({} if body is None else {"Content-Type": "application/json"}),
        },
        method=method,
    )
    try:
        return urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} from {url}: {payload}") from exc


def http_json(
    url: str,
    *,
    method: str = "GET",
    body: dict[str, Any] | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    with http_request(url, method=method, body=body, timeout=timeout) as response:
        value = json.load(response)
    if not isinstance(value, dict):
        raise RuntimeError(f"{url} returned non-object JSON")
    result = value.get("result", value)
    if not isinstance(result, dict):
        raise RuntimeError(f"{url} returned no result object")
    return result


def http_to_new_file(
    url: str,
    destination: Path,
    *,
    body: dict[str, Any],
    timeout: float = 180.0,
) -> dict[str, Any]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise RuntimeError(f"refusing to overwrite {destination}")
    partial = destination.with_name(destination.name + ".partial")
    try:
        with http_request(
            url,
            method="POST",
            body=body,
            timeout=timeout,
            accept="application/vnd.tcpdump.pcap",
        ) as response, partial.open("xb") as output:
            for chunk in iter(lambda: response.read(8 * 1024 * 1024), b""):
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        partial.replace(destination)
    except Exception:
        partial.unlink(missing_ok=True)
        raise
    return {
        "path": str(destination),
        "bytes": destination.stat().st_size,
        "sha256": sha256_file(destination),
    }


def phase_plan(queue_id: str) -> list[dict[str, Any]]:
    phases: list[dict[str, Any]] = []
    for scan in ("a", "b", "c"):
        for position, kind, duration in (
            ("pre", "time", TIME_SECONDS),
            ("scan", "spec", SPEC_SECONDS),
            ("post", "time", TIME_SECONDS),
        ):
            label = f"{scan}-{kind}-{position}"
            phases.append(
                {
                    "index": len(phases),
                    "label": label,
                    "scan": scan.upper(),
                    "position": position,
                    "kind": kind,
                    "mode": "time_only" if kind == "time" else "spec_only",
                    "duration_seconds": duration,
                    "scan_id": f"{queue_id}-{label}-{duration}s",
                    "status": "pending",
                }
            )
    return phases


def configure_body(
    template: dict[str, Any], mode: str, center_mhz: float = CENTER_MHZ
) -> dict[str, Any]:
    if mode not in ("time_only", "spec_only"):
        raise ValueError(f"unsupported output mode {mode}")
    body = copy.deepcopy(template)
    body["board_id"] = BOARD_ID
    body["clock_reference"] = "onboard_tcxo"
    body["profile"] = {
        "sample_rate_msps": SAMPLE_RATE_MSPS,
        "mode": mode,
        "center_mhz": center_mhz,
    }
    body["update_mode"] = "clock_preserving"
    body["receiver_stream_accepting"] = False
    expected_stream = "TIME" if mode == "time_only" else "SPEC"
    for endpoint in body.get("endpoints", []):
        endpoint["enabled"] = str(endpoint.get("stream", "")).upper() == expected_stream
    return body


def receiver_config(mode: str, center_mhz: float = CENTER_MHZ) -> dict[str, Any]:
    return {
        "sample_rate_msps": SAMPLE_RATE_MSPS,
        "output_mode": mode,
        "center_mhz": center_mhz,
        "expected_mhz": center_mhz,
        "dac_mhz": center_mhz,
        "target_mhz_by_channel": [center_mhz] * 8,
        "channel_mask": 0xFF,
        "paused": False,
    }


def nested_board_status(value: dict[str, Any]) -> dict[str, Any]:
    snapshot = value.get("snapshot")
    return snapshot if isinstance(snapshot, dict) else value


def board_errors(
    board: dict[str, Any], *, mode: str | None = None, center_mhz: float = CENTER_MHZ
) -> list[str]:
    board = nested_board_status(board)
    errors: list[str] = []
    if board.get("core_version") != EXPECTED_CORE_VERSION:
        errors.append(f"core_version={board.get('core_version')}")
    if int(board.get("board_id", -1)) != BOARD_ID:
        errors.append(f"board_id={board.get('board_id')}")
    profile = board.get("profile", {})
    if int(profile.get("sample_rate_msps", 0)) != SAMPLE_RATE_MSPS:
        errors.append(f"sample_rate_msps={profile.get('sample_rate_msps')}")
    if mode is not None and profile.get("mode") != mode:
        errors.append(f"mode={profile.get('mode')} expected={mode}")
    if abs(float(profile.get("center_mhz", 0.0)) - center_mhz) > 1.0e-6:
        errors.append(f"center_mhz={profile.get('center_mhz')}")
    clock = board.get("clock", {})
    if clock.get("clock_reference") != "onboard_tcxo":
        errors.append(f"clock_reference={clock.get('clock_reference')}")
    if clock.get("profile_id") != EXPECTED_CLOCK_PROFILE:
        errors.append(f"clock_profile={clock.get('profile_id')}")
    if clock.get("profile_sha256") != EXPECTED_CLOCK_SHA256:
        errors.append(f"clock_profile_sha256={clock.get('profile_sha256')}")
    if int(clock.get("pll1_lock", 0)) != 1 or int(clock.get("pll2_lock", 0)) != 1:
        errors.append("clock PLL lock is not 1/1")
    rfdc = board.get("rfdc", {})
    if int(rfdc.get("active_mask", 0)) != 0xFFFF:
        errors.append(f"rfdc.active_mask={rfdc.get('active_mask')}")
    valid = rfdc.get("current_valid_mask", rfdc.get("valid_mask", 0))
    if int(valid or 0) != 0xFFFF:
        errors.append(f"rfdc.current_valid_mask={valid}")
    mts = board.get("mts", {})
    if int(mts.get("adc", {}).get("target_latency", -1)) != EXPECTED_MTS_ADC:
        errors.append("ADC MTS target mismatch")
    if int(mts.get("dac", {}).get("target_latency", -1)) != EXPECTED_MTS_DAC:
        errors.append("DAC MTS target mismatch")
    if int(board.get("dac", {}).get("enable_mask", -1)) != 0:
        errors.append(f"DAC enable_mask={board.get('dac', {}).get('enable_mask')}")
    return errors


def receiver_errors(
    receiver: dict[str, Any], *, mode: str, center_mhz: float = CENTER_MHZ
) -> list[str]:
    config = receiver.get("config", {})
    errors: list[str] = []
    if int(config.get("sample_rate_msps", 0)) != SAMPLE_RATE_MSPS:
        errors.append(f"receiver sample_rate_msps={config.get('sample_rate_msps')}")
    if config.get("output_mode") != mode:
        errors.append(f"receiver mode={config.get('output_mode')} expected={mode}")
    if abs(float(config.get("center_mhz", 0.0)) - center_mhz) > 1.0e-6:
        errors.append(f"receiver center_mhz={config.get('center_mhz')}")
    return errors


def counter_delta(before: dict[str, Any], after: dict[str, Any], keys: tuple[str, ...]) -> dict[str, int]:
    return {
        key: int(after.get(key, 0) or 0) - int(before.get(key, 0) or 0)
        for key in keys
    }


def formal_integrity(
    before_board: dict[str, Any],
    after_board: dict[str, Any],
    before_receiver: dict[str, Any],
    after_receiver: dict[str, Any],
) -> dict[str, Any]:
    board_delta = counter_delta(
        nested_board_status(before_board).get("counters", {}),
        nested_board_status(after_board).get("counters", {}),
        BOARD_COUNTERS,
    )
    before_stats = before_receiver.get("stats", {})
    after_stats = after_receiver.get("stats", {})
    receiver_delta = counter_delta(before_stats, after_stats, RECEIVER_COUNTERS)
    instantaneous = {
        key: int(after_stats.get(key, 0) or 0) for key in RECEIVER_INSTANTANEOUS_ERRORS
    }
    errors = [f"board.{key} delta={value}" for key, value in board_delta.items() if value]
    errors += [
        f"receiver.{key} delta={value}" for key, value in receiver_delta.items() if value
    ]
    errors += [
        f"receiver.{key}={value}" for key, value in instantaneous.items() if value
    ]
    return {
        "ok": not errors,
        "errors": errors,
        "board_counter_deltas": board_delta,
        "receiver_counter_deltas": receiver_delta,
        "receiver_instantaneous_errors": instantaneous,
    }


def verify_manifest_basic(dataset: Path, phase: dict[str, Any]) -> dict[str, Any]:
    manifest_path = dataset / "dataset_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("complete") is not True:
        raise RuntimeError(f"{phase['scan_id']} manifest is not complete")
    request = manifest.get("request", {})
    for key, expected in (
        ("scan_id", phase["scan_id"]),
        ("duration_seconds", phase["duration_seconds"]),
        ("sample_rate_msps", SAMPLE_RATE_MSPS),
        ("native_bucket_ms", NATIVE_BUCKET_MS),
    ):
        if request.get(key) != expected:
            raise RuntimeError(
                f"{phase['scan_id']} manifest request {key}={request.get(key)!r}, expected={expected!r}"
            )
    digest_path = dataset / "dataset_manifest.sha256"
    expected_digest = digest_path.read_text(encoding="ascii").split()[0]
    actual_digest = sha256_file(manifest_path)
    if expected_digest != actual_digest:
        raise RuntimeError(f"{phase['scan_id']} manifest SHA-256 mismatch")
    return {
        "path": str(manifest_path),
        "bytes": manifest_path.stat().st_size,
        "sha256": actual_digest,
        "format": manifest.get("format"),
        "file_count": len(manifest.get("files", [])),
    }


def verify_spec_pcap(path: Path) -> dict[str, Any]:
    counts = {port: 0 for port in range(4308, 4324)}
    identities: dict[int, list[tuple[int, int, int]]] = {port: [] for port in counts}
    frames = 0
    with path.open("rb") as stream:
        header = stream.read(24)
        if len(header) != 24 or header[:4] != b"\xd4\xc3\xb2\xa1":
            raise RuntimeError(f"{path} is not little-endian classic PCAP")
        while record := stream.read(16):
            if len(record) != 16:
                raise RuntimeError(f"{path} has a truncated record header")
            captured = struct.unpack_from("<I", record, 8)[0]
            frame = stream.read(captured)
            if len(frame) != captured or len(frame) < 42:
                raise RuntimeError(f"{path} has a truncated Ethernet frame")
            ip = 14
            ihl = (frame[ip] & 0x0F) * 4
            udp = ip + ihl
            port = struct.unpack_from("!H", frame, udp + 2)[0]
            payload = frame[udp + 8 :]
            if port not in counts or len(payload) < 128:
                raise RuntimeError(f"{path} contains unexpected SPEC frame port={port}")
            words = struct.unpack_from("<16Q", payload)
            if (
                words[0] >> 32 != 0x54353130
                or ((words[1] >> 32) & 0xFFFF) != STREAM_SPEC
            ):
                raise RuntimeError(f"{path} contains invalid T510 SPEC identity")
            counts[port] += 1
            identities[port].append(((words[6] >> 32) & 0xFFFF_FFFF, words[5], words[4]))
            frames += 1
    expected = SPEC_RAW_PACKETS_PER_BLOCK * 16
    if frames != expected or set(counts.values()) != {SPEC_RAW_PACKETS_PER_BLOCK}:
        raise RuntimeError(f"unbalanced SPEC PCAP frames={frames} counts={counts}")
    for port, rows in identities.items():
        for prior, current in zip(rows, rows[1:]):
            if (
                current[0] != ((prior[0] + 16) & 0xFFFF_FFFF)
                or current[1] != prior[1] + 16
                or current[2] != prior[2] + 4096
            ):
                raise RuntimeError(
                    f"{path} port {port} is discontinuous: prior={prior} current={current}"
                )
    return {
        "path": str(path),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "frames": frames,
        "packets_by_port": {str(key): value for key, value in counts.items()},
    }


class QueueRunner:
    def __init__(self, args: argparse.Namespace, template: dict[str, Any]):
        self.args = args
        self.template = template
        self.root = args.measurement_root / f"{args.queue_id}-queue"
        self.state_path = self.root / "queue_state.json"
        self.events_path = self.root / "queue_events.jsonl"
        self.evidence = self.root / "evidence"
        self.raw = self.root / "raw"
        self.phases = phase_plan(args.queue_id)
        self.telemetry_since_seq = 0
        self.telemetry_epoch_id: str | None = None
        self.state: dict[str, Any] = {
            "format": FORMAT,
            "schema_version": 1,
            "queue_id": args.queue_id,
            "status": "armed",
            "created_unix_ms": unix_ms(),
            "started_unix_ms": None,
            "finished_unix_ms": None,
            "current_phase_index": None,
            "error": None,
            "agent_base": args.agent_base,
            "receiver_base": args.receiver_base,
            "measurement_root": str(args.measurement_root),
            "center_mhz": args.center_mhz,
            "minimum_free_bytes": args.minimum_free_bytes,
            "physical_context": {
                "rf_inputs": "operator-confirmed unchanged Stage 35 eight independent 50-ohm terminations; connectors are not remotely sensed",
                "external_10mhz_pps": "operator reported disconnected before Stage 35 S1/S2",
                "clock_reference": "onboard_tcxo",
                "dac": "disabled; physical DAC cable state inherited and not remotely sensed",
                "air_conditioning": "required stable-on condition; room state is not remotely sensed",
            },
            "phases": self.phases,
        }

    def save(self) -> None:
        write_json_atomic(self.state_path, self.state)

    def event(self, event: str, **fields: Any) -> None:
        append_event(self.events_path, event, **fields)

    def board(self, path: str = "/api/v2/status", **kwargs: Any) -> dict[str, Any]:
        return http_json(self.args.agent_base.rstrip("/") + path, **kwargs)

    def receiver(self, path: str = "/api/state", **kwargs: Any) -> dict[str, Any]:
        return http_json(self.args.receiver_base.rstrip("/") + path, **kwargs)

    def initialize(self) -> None:
        self.root.mkdir(parents=True, exist_ok=False)
        self.evidence.mkdir()
        self.raw.mkdir()
        self.save()
        self.event("queue_armed", phase_count=len(self.phases))
        write_json_new(self.evidence / "configure_template.json", self.template)
        write_json_new(self.evidence / "queue_definition.json", self.state)

    def preflight(self) -> None:
        usage = shutil.disk_usage(self.args.measurement_root)
        disk = {"total": usage.total, "used": usage.used, "free": usage.free}
        write_json_new(self.evidence / "disk_preflight.json", disk)
        if usage.free < self.args.minimum_free_bytes:
            raise RuntimeError(
                f"only {usage.free} bytes free, require {self.args.minimum_free_bytes}"
            )
        for phase in self.phases:
            if (self.args.measurement_root / phase["scan_id"]).exists():
                raise RuntimeError(f"refusing to reuse scan_id {phase['scan_id']}")
        board = self.board()
        receiver = self.receiver()
        write_json_new(self.evidence / "board_preflight.json", board)
        write_json_new(self.evidence / "receiver_preflight.json", receiver)
        current_mode = str(board.get("profile", {}).get("mode", ""))
        if current_mode not in ("time_only", "spec_only"):
            errors = [f"unsupported preflight board mode={current_mode!r}"]
        else:
            current_center = float(board.get("profile", {}).get("center_mhz", 0.0))
            # The receiver service may have restarted with its harmless default
            # view configuration while the stopped board retains the prior
            # tuning.  Each phase applies and verifies the requested receiver
            # configuration before START, so preflight validates the board
            # identity here without requiring those two stopped states to match.
            errors = board_errors(board, mode=current_mode, center_mhz=current_center)
        if bool(board.get("streaming")):
            errors.append("board is streaming before queue start")
        if float(receiver.get("stats", {}).get("packets_per_sec", 0.0) or 0.0) != 0.0:
            errors.append("receiver still reports live packets before queue start")
        for path in (
            "/api/measure/autocorrelation/status",
            "/api/measure/time/status",
            "/api/measure/spec-stability/status",
        ):
            status = self.receiver(path)
            if status.get("status") in ("armed", "running", "draining"):
                errors.append(f"active receiver task at {path}: {status.get('status')}")
        if errors:
            raise RuntimeError(f"S2 preflight failed: {errors}")
        self.event("preflight_pass", disk_free_bytes=usage.free)

    def stop_board(self, evidence_name: str) -> dict[str, Any]:
        current = self.read_board_with_retries()
        if bool(current.get("streaming")):
            try:
                stopped = self.board("/api/v2/stop", method="POST", body={}, timeout=90.0)
            except Exception as stop_error:
                # STOP is an idempotent safety operation. A large successful
                # response can be reset after the board has already stopped;
                # never repeat the mutation blindly. Accept only a fresh,
                # independently validated readback proving the safe state.
                readback = self.read_board_with_retries()
                errors = board_errors(readback, center_mhz=self.args.center_mhz)
                if bool(readback.get("streaming")) or errors:
                    raise RuntimeError(
                        "STOP transport failed and safe readback did not pass: "
                        f"transport={type(stop_error).__name__}: {stop_error}; "
                        f"streaming={readback.get('streaming')}; errors={errors}"
                    ) from stop_error
                stopped = {
                    "stop_response_transport_error": (
                        f"{type(stop_error).__name__}: {stop_error}"
                    ),
                    "idempotent_readback_accepted": True,
                    "snapshot": readback,
                }
        else:
            stopped = current
        write_json_atomic(self.evidence / evidence_name, stopped)
        return stopped

    def read_board_with_retries(self, attempts: int = 3) -> dict[str, Any]:
        errors: list[str] = []
        for attempt in range(attempts):
            try:
                return self.board()
            except Exception as exc:
                errors.append(f"{type(exc).__name__}: {exc}")
                if attempt + 1 < attempts:
                    time.sleep(1.0)
        raise RuntimeError(f"board status read failed after {attempts} attempts: {errors}")

    def seed_telemetry_cursor(self, board: dict[str, Any]) -> None:
        telemetry = (
            board.get("reference_watchdog", {}).get("power_thermal_telemetry", {})
        )
        self.telemetry_since_seq = int(telemetry.get("sequence", 0) or 0)
        epoch = telemetry.get("epoch_id")
        self.telemetry_epoch_id = str(epoch) if epoch is not None else None

    def incremental_telemetry(self) -> dict[str, Any]:
        result = self.board(
            f"/api/v2/telemetry/power-thermal?since_seq={self.telemetry_since_seq}"
        )
        epoch = result.get("epoch_id")
        if (
            self.telemetry_epoch_id is not None
            and epoch is not None
            and str(epoch) != self.telemetry_epoch_id
        ):
            raise RuntimeError(
                "power/thermal telemetry epoch changed during a formal phase: "
                f"{self.telemetry_epoch_id} -> {epoch}"
            )
        last = result.get("last_sequence")
        if last is not None:
            self.telemetry_since_seq = int(last)
        return {
            "source": result.get("source"),
            "since_seq": result.get("since_seq"),
            "record_count": result.get("record_count"),
            "first_sequence": result.get("first_sequence"),
            "last_sequence": result.get("last_sequence"),
            "epoch_id": result.get("epoch_id"),
            "records": result.get("records", []),
        }

    def wait_receiver_quiescent(self) -> dict[str, Any]:
        deadline = time.monotonic() + 15.0
        last: dict[str, Any] = {}
        while time.monotonic() < deadline:
            last = self.receiver()
            stats = last.get("stats", {})
            if (
                float(stats.get("packets_per_sec", 0.0) or 0.0) == 0.0
                and int(stats.get("active_worker_count", 0) or 0) == 0
            ):
                return last
            time.sleep(0.5)
        raise RuntimeError(f"receiver did not quiesce: {last.get('stats', {})}")

    def ensure_mode(self, phase: dict[str, Any]) -> None:
        mode = phase["mode"]
        self.stop_board(f"phase_{phase['index']:02d}_stop_before.json")
        self.wait_receiver_quiescent()
        applied_receiver = self.receiver(
            "/api/config", method="POST", body=receiver_config(mode, self.args.center_mhz)
        )
        write_json_new(
            self.evidence / f"phase_{phase['index']:02d}_receiver_config.json",
            applied_receiver,
        )
        board = self.board()
        profile = board.get("profile", {})
        if (profile.get("mode") != mode or
                abs(float(profile.get("center_mhz", 0.0)) - self.args.center_mhz) > 1.0e-6):
            configured = self.board(
                "/api/v2/configure",
                method="POST",
                body=configure_body(self.template, mode, self.args.center_mhz),
                timeout=300.0,
            )
            write_json_new(
                self.evidence / f"phase_{phase['index']:02d}_hot_configure.json",
                configured,
            )
            bitstream = configured.get("bitstream", {})
            hot = configured.get("hot_update", {}) or {}
            journal = hot.get("journal", {}) if isinstance(hot, dict) else {}
            if bitstream.get("sha256") != EXPECTED_BITSTREAM_SHA256:
                raise RuntimeError(f"hot configure bitstream identity mismatch: {bitstream}")
            if configured.get("update_mode") != "clock_preserving" or not journal.get("ready"):
                raise RuntimeError(f"hot configure did not reach READY: {hot}")
            board = self.board()
        errors = board_errors(board, mode=mode, center_mhz=self.args.center_mhz)
        errors += receiver_errors(self.receiver(), mode=mode, center_mhz=self.args.center_mhz)
        if errors:
            raise RuntimeError(f"mode transition validation failed: {errors}")
        self.event("mode_ready", phase=phase["label"], mode=mode)

    def start_stream(self, phase: dict[str, Any]) -> dict[str, Any]:
        started = self.board(
            "/api/v2/start",
            method="POST",
            body={"expected_board_id": BOARD_ID},
            timeout=90.0,
        )
        write_json_new(
            self.evidence / f"phase_{phase['index']:02d}_start.json", started
        )
        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline:
            state = self.receiver()
            stats = state.get("stats", {})
            if float(stats.get("packets_per_sec", 0.0) or 0.0) > 0.0:
                self.event(
                    "stream_healthy",
                    phase=phase["label"],
                    packets_per_sec=stats.get("packets_per_sec"),
                    gbps=stats.get("gbps"),
                )
                return started
            time.sleep(0.5)
        raise RuntimeError(f"no receiver traffic after START for {phase['label']}")

    def capture_spec_raw(self, phase: dict[str, Any], position: str) -> dict[str, Any]:
        raw_stem = str(phase.get("raw_stem", phase["scan"].lower()))
        name = f"{raw_stem}-spec-{position}-raw.pcap"
        path = self.raw / name
        board_before = self.board()
        before = self.receiver()
        identity = http_to_new_file(
            self.args.receiver_base.rstrip("/") + "/api/capture/spec-pcap",
            path,
            body={
                "packets_per_block": SPEC_RAW_PACKETS_PER_BLOCK,
                "include_time": False,
                "time_only": False,
            },
        )
        after = self.receiver()
        board_after = self.board()
        integrity = formal_integrity(board_before, board_after, before, after)
        if not integrity["ok"]:
            raise RuntimeError(f"SPEC raw capture integrity failed: {integrity['errors']}")
        verified = verify_spec_pcap(path)
        result = {**identity, "verified": verified, "receiver_integrity": integrity}
        write_json_new(self.evidence / f"{name}.json", result)
        return result

    def capture_time_raw(self, phase: dict[str, Any]) -> dict[str, Any]:
        superset = self.raw / "a-time-pre-52ms-superset.pcap"
        cropped = self.raw / "a-time-pre-50ms.pcap"
        board_before = self.board()
        before = self.receiver()
        identity = http_to_new_file(
            self.args.receiver_base.rstrip("/") + "/api/capture/spec-pcap",
            superset,
            body={
                "packets_per_block": TIME_RAW_PACKETS_PER_FLOW,
                "include_time": True,
                "time_only": True,
            },
            timeout=240.0,
        )
        after = self.receiver()
        board_after = self.board()
        integrity = formal_integrity(board_before, board_after, before, after)
        if not integrity["ok"]:
            raise RuntimeError(f"TIME raw capture integrity failed: {integrity['errors']}")
        sys.path.insert(0, str(self.args.helper_dir))
        from t510_time_capture_verify import crop_continuous_pcap, verify_pcap

        crop = crop_continuous_pcap(superset, cropped)
        verified = verify_pcap(cropped)
        result = {
            "superset": identity,
            "crop": crop,
            "verified": verified,
            "receiver_integrity": integrity,
            "phase": phase["label"],
        }
        write_json_new(self.evidence / "a-time-pre-raw.json", result)
        return result

    def monitor_capture(
        self, phase: dict[str, Any], status_path: str
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        deadline = time.monotonic() + float(phase["duration_seconds"]) + 360.0
        telemetry: list[dict[str, Any]] = []
        next_telemetry = 0.0
        next_state_write = 0.0
        last: dict[str, Any] = {}
        while time.monotonic() < deadline:
            last = self.receiver(status_path)
            status = str(last.get("status"))
            now = time.monotonic()
            if now >= next_telemetry:
                try:
                    receiver_state = self.receiver()
                    telemetry.append(
                        {
                            "unix_ms": unix_ms(),
                            "board": self.incremental_telemetry(),
                            "receiver": {
                                key: receiver_state.get("stats", {}).get(key)
                                for key in (
                                    "packets_per_sec",
                                    "gbps",
                                    "kernel_drops",
                                    "ring_drops",
                                    "seq_gaps",
                                    "frame_gaps",
                                    "sample0_gaps",
                                    "spec_seq_gaps",
                                    "spec_frame_gaps",
                                )
                            },
                        }
                    )
                except Exception as exc:  # telemetry absence must remain visible
                    telemetry.append({"unix_ms": unix_ms(), "error": repr(exc)})
                write_json_atomic(
                    self.evidence / f"phase_{phase['index']:02d}_telemetry.json",
                    telemetry,
                )
                next_telemetry = now + 30.0
            if now >= next_state_write:
                phase["capture_status"] = last
                self.save()
                next_state_write = now + 10.0
            if status == "completed":
                return last, telemetry
            if status == "failed":
                raise RuntimeError(
                    f"{phase['label']} capture failed: {last.get('error')}"
                )
            if status not in ("armed", "running", "draining"):
                raise RuntimeError(f"{phase['label']} unexpected capture state {status}")
            time.sleep(2.0)
        raise RuntimeError(f"{phase['label']} capture deadline expired; last={last}")

    def run_phase(self, phase: dict[str, Any]) -> None:
        phase["status"] = "starting"
        phase["started_unix_ms"] = unix_ms()
        self.state["current_phase_index"] = phase["index"]
        self.save()
        self.event("phase_starting", phase=phase["label"], scan_id=phase["scan_id"])
        self.ensure_mode(phase)
        self.start_stream(phase)

        raw_begin = None
        if phase["kind"] == "spec":
            raw_begin = self.capture_spec_raw(phase, "begin")

        before_board = self.board()
        before_receiver = self.receiver()
        self.seed_telemetry_cursor(before_board)
        write_json_new(
            self.evidence / f"phase_{phase['index']:02d}_board_before.json", before_board
        )
        write_json_new(
            self.evidence / f"phase_{phase['index']:02d}_receiver_before.json",
            before_receiver,
        )
        request = {
            "scan_id": phase["scan_id"],
            "tuning_id": f"center-{self.args.center_mhz:g}mhz-{phase['mode']}",
            "duration_seconds": phase["duration_seconds"],
            "native_bucket_ms": NATIVE_BUCKET_MS,
            "sample_rate_msps": SAMPLE_RATE_MSPS,
            "center_mhz": self.args.center_mhz,
            "metadata": {
                "stage": "35",
                "step": str(phase.get("metadata_step", "6")),
                "queue_id": self.args.queue_id,
                "scan": phase["scan"],
                "position": phase["position"],
                "purpose": phase.get("purpose", "S2_TIME_SPEC_control"),
                "physical_input": "eight_independent_50ohm_operator_confirmed",
                "clock_reference": "onboard_tcxo",
                "simultaneity": "adjacent_time_control_not_simultaneous_with_spec",
            },
        }
        if phase["kind"] == "spec":
            request["expected_fft_shift"] = EXPECTED_FFT_SHIFT
            begin_path = "/api/measure/autocorrelation"
            status_path = begin_path + "/status"
        else:
            begin_path = "/api/measure/time"
            status_path = begin_path + "/status"
        started = self.receiver(begin_path, method="POST", body=request)
        phase["capture_start"] = started
        phase["status"] = "running"
        self.save()
        self.event("phase_capture_armed", phase=phase["label"], status=started.get("status"))
        final_status, telemetry = self.monitor_capture(phase, status_path)
        after_board = self.board()
        after_receiver = self.receiver()
        write_json_new(
            self.evidence / f"phase_{phase['index']:02d}_board_after.json", after_board
        )
        write_json_new(
            self.evidence / f"phase_{phase['index']:02d}_receiver_after.json",
            after_receiver,
        )
        integrity = formal_integrity(
            before_board, after_board, before_receiver, after_receiver
        )
        if not integrity["ok"]:
            raise RuntimeError(f"{phase['label']} formal integrity failed: {integrity['errors']}")
        board_state_errors = board_errors(
            after_board, mode=phase["mode"], center_mhz=self.args.center_mhz
        )
        if board_state_errors:
            raise RuntimeError(
                f"{phase['label']} board identity changed: {board_state_errors}"
            )

        raw_end = None
        if phase["kind"] == "spec":
            raw_end = self.capture_spec_raw(phase, "end")
        elif phase["label"] == "a-time-pre":
            raw_end = self.capture_time_raw(phase)

        self.stop_board(f"phase_{phase['index']:02d}_stop_after.json")
        dataset = self.args.measurement_root / phase["scan_id"]
        manifest = verify_manifest_basic(dataset, phase)
        phase.update(
            {
                "status": "completed",
                "finished_unix_ms": unix_ms(),
                "capture_status": final_status,
                "manifest": manifest,
                "formal_integrity": integrity,
                "telemetry_samples": len(telemetry),
                "raw_begin": raw_begin,
                "raw_end": raw_end,
            }
        )
        self.save()
        self.event("phase_complete", phase=phase["label"], manifest_sha256=manifest["sha256"])

    def independent_verify(self) -> None:
        spec_scans = [
            self.args.measurement_root / phase["scan_id"]
            for phase in self.phases
            if phase["kind"] == "spec"
        ]
        spec_output = self.evidence / "spec_independent_verification.json"
        command = [
            sys.executable,
            str(self.args.helper_dir / "t510_stage35_live_verify.py"),
        ]
        for scan in spec_scans:
            command += ["--scan", str(scan)]
        command += ["--output-json", str(spec_output)]
        completed = subprocess.run(
            command,
            cwd=self.args.helper_dir,
            text=True,
            capture_output=True,
            timeout=1800,
            check=False,
        )
        write_json_new(
            self.evidence / "spec_independent_verification_process.json",
            {
                "argv": command,
                "returncode": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
            },
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"independent SPEC verification failed: {completed.stderr or completed.stdout}"
            )
        spec_result = json.loads(spec_output.read_text(encoding="utf-8"))
        for scan in spec_result.get("scans", []):
            events = {
                key: int(scan.get(key, 0) or 0)
                for key in ("missing_frames", "duplicates", "reordered", "late")
            }
            events["gap_ranges"] = int(scan.get("gap_ranges", 0) or 0)
            events["arrival_events"] = int(scan.get("arrival_events", 0) or 0)
            if any(events.values()):
                raise RuntimeError(
                    f"independent SPEC data-quality gate failed for {scan.get('scan_id')}: {events}"
                )

        time_results = []
        for phase in self.phases:
            if phase["kind"] != "time":
                continue
            dataset = self.args.measurement_root / phase["scan_id"]
            manifest = json.loads((dataset / "dataset_manifest.json").read_text())
            for item in manifest["files"]:
                path = dataset / item["path"]
                if path.stat().st_size != int(item["bytes"]):
                    raise RuntimeError(f"TIME file size mismatch: {path}")
                if sha256_file(path) != item["sha256"]:
                    raise RuntimeError(f"TIME file SHA-256 mismatch: {path}")
            quality = json.loads((dataset / "flow_quality.json").read_text())
            if len(quality) != 8 or any(
                int(row[key]) != 0
                for row in quality
                for key in ("missing_packets", "reordered_packets", "duplicate_packets")
            ):
                raise RuntimeError(f"TIME flow quality failed: {phase['scan_id']}")
            summary = json.loads((dataset / "summary.json").read_text())
            if (
                int(summary.get("packets", 0)) != 37_500_000
                or int(summary.get("samples_per_lane", 0)) != 9_600_000_000
            ):
                raise RuntimeError(f"TIME coverage failed: {phase['scan_id']}")
            time_results.append(
                {
                    "scan_id": phase["scan_id"],
                    "manifest_sha256": sha256_file(dataset / "dataset_manifest.json"),
                    "packets": summary["packets"],
                    "samples_per_lane": summary["samples_per_lane"],
                    "flow_events": 0,
                }
            )
        write_json_new(
            self.evidence / "time_independent_verification.json",
            {"status": "PASS", "scan_count": len(time_results), "scans": time_results},
        )
        self.event("independent_verification_pass", spec_scans=3, time_scans=6)

    def final_manifest(self) -> None:
        files = []
        for path in sorted(item for item in self.root.rglob("*") if item.is_file()):
            if path.name in ("queue_manifest.json", "queue_manifest.sha256"):
                continue
            files.append(
                {
                    "path": path.relative_to(self.root).as_posix(),
                    "bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            )
        scans = [
            {
                "scan_id": phase["scan_id"],
                "kind": phase["kind"],
                "duration_seconds": phase["duration_seconds"],
                "manifest": phase["manifest"],
            }
            for phase in self.phases
        ]
        manifest = {
            "format": "T510_STAGE35_S2_QUEUE_MANIFEST_V1",
            "schema_version": 1,
            "queue_id": self.args.queue_id,
            "complete": True,
            "files": files,
            "scans": scans,
        }
        path = self.root / "queue_manifest.json"
        write_json_new(path, manifest)
        (self.root / "queue_manifest.sha256").write_text(
            f"{sha256_file(path)}  queue_manifest.json\n", encoding="ascii"
        )

    def safe_finalize(self, *, failed: bool) -> list[str]:
        errors: list[str] = []
        try:
            self.stop_board("board_final_safe.json")
        except Exception as exc:
            errors.append(f"board STOP failed: {type(exc).__name__}: {exc}")
        try:
            receiver = self.wait_receiver_quiescent()
            write_json_atomic(self.evidence / "receiver_final_safe.json", receiver)
        except Exception as exc:
            errors.append(f"receiver quiescence failed: {type(exc).__name__}: {exc}")
        self.event("safe_finalize", failed=failed, errors=errors)
        return errors

    def run(self) -> int:
        self.initialize()
        try:
            self.preflight()
            self.state["status"] = "running"
            self.state["started_unix_ms"] = unix_ms()
            self.save()
            for phase in self.phases:
                self.run_phase(phase)
            self.independent_verify()
            safe_errors = self.safe_finalize(failed=False)
            if safe_errors:
                raise RuntimeError(f"safe finalization errors: {safe_errors}")
            self.state["status"] = "completed"
            self.state["current_phase_index"] = None
            self.state["finished_unix_ms"] = unix_ms()
            self.save()
            self.event("queue_complete")
            self.final_manifest()
            return 0
        except Exception as exc:  # any phase failure stops the complete queue
            if self.state.get("current_phase_index") is not None:
                phase = self.phases[int(self.state["current_phase_index"])]
                if phase.get("status") != "completed":
                    phase["status"] = "failed"
                    phase["error"] = f"{type(exc).__name__}: {exc}"
            safe_errors = self.safe_finalize(failed=True)
            self.state["status"] = "failed"
            self.state["error"] = {
                "message": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(),
                "safe_finalize_errors": safe_errors,
            }
            self.state["finished_unix_ms"] = unix_ms()
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
    parser.add_argument("--center-mhz", type=float, default=CENTER_MHZ)
    parser.add_argument("--minimum-free-bytes", type=int, default=MIN_FREE_BYTES)
    parser.add_argument("--lock", type=Path, default=Path("/run/lock/t510-stage35-s2.lock"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.queue_id or any(
        byte not in b"abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_."
        for byte in args.queue_id.encode("ascii", errors="strict")
    ):
        raise RuntimeError("queue-id contains unsupported characters")
    args.lock.parent.mkdir(parents=True, exist_ok=True)
    with args.lock.open("a+b") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("another Stage 35 S2 queue owns the lock") from exc
        template = json.loads(args.template.read_text(encoding="utf-8"))
        return QueueRunner(args, template).run()


if __name__ == "__main__":
    raise SystemExit(main())
