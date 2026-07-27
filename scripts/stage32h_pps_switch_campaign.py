#!/usr/bin/env python3
"""Run the Stage 32h single-board PPS-boundary mode-switch campaign.

Each switch uses the existing stateless Board Agent contract:

    STOP/CONFIGURE -> sync PREPARE -> sync ARM -> future PPS commit
    -> prove sustained required streams -> STOP/flush

The script changes no FPGA, UDP, or REST contract.  It writes one JSON file
per switch plus a resumable campaign summary.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import time
from typing import Any, Callable
import urllib.error
import urllib.request


CASES = (
    (160, "time_only"),
    (160, "spec_only"),
    (160, "time_spec"),
    (320, "time_only"),
    (320, "spec_only"),
)

CASE_NAMES = {
    "160_time_only": (160, "time_only"),
    "160_spec_only": (160, "spec_only"),
    "160_time_spec": (160, "time_spec"),
    "320_time_only": (320, "time_only"),
    "320_spec_only": (320, "spec_only"),
}

SIGNAL_CHAIN_TAGS = {
    (160, "time_only"): 0x32160101,
    (160, "spec_only"): 0x32160102,
    (160, "time_spec"): 0x32160103,
    (320, "time_only"): 0x32320101,
    (320, "spec_only"): 0x32320102,
}

DROP_COUNTERS = (
    "time_dropped",
    "spec_dropped",
    "tx_frames_dropped",
    "tx_route_miss",
    "tx_route_error",
    "rfdc_dropped",
    "science_dropped_beats",
)

PFB_ERROR_COUNTERS = (
    "overflow_count",
    "data_halt_count",
    "xfft_event_count",
    "tile_overflow_count",
    "xfft_tlast_unexpected_count",
    "xfft_tlast_missing_count",
    "xfft_fft_overflow_count",
    "xfft_data_out_halt_count",
    "xfft_status_halt_count",
    "capture_backpressure_count",
    "frame_sample0_overflow_count",
    "coefficient_error_count",
)


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def _timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} does not contain a JSON object")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run_receiver_validation(
    *,
    receiver_ssh: str,
    remote_validator: str,
    remote_output: str,
    receiver_base_url: str,
    receiver_interface: str,
    bandwidth_mhz: int,
    mode: str,
    seconds: float,
    local_output: Path,
) -> dict[str, Any]:
    command = [
        "ssh",
        "-o",
        "BatchMode=yes",
        receiver_ssh,
        "python3",
        remote_validator,
        "--bandwidth-mhz",
        str(bandwidth_mhz),
        "--mode",
        mode,
        "--base-url",
        receiver_base_url,
        "--interface",
        receiver_interface,
        "--seconds",
        str(seconds),
        "--output",
        remote_output,
        "--skip-config",
    ]
    process = subprocess.run(command, text=True, capture_output=True, check=False)
    fetched = subprocess.run(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            receiver_ssh,
            "cat",
            remote_output,
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if fetched.returncode != 0:
        raise RuntimeError(
            "receiver evidence fetch failed: "
            f"{fetched.stderr.strip() or fetched.stdout.strip()}"
        )
    host = json.loads(fetched.stdout)
    if not isinstance(host, dict):
        raise RuntimeError("receiver evidence is not a JSON object")
    _write_json(local_output, host)
    return {
        "returncode": process.returncode,
        "stderr": process.stderr,
        "evidence": str(local_output),
        "evidence_sha256": _sha256(local_output),
        "classification": host.get("classification"),
        "ok": bool(host.get("ok")),
        "errors": host.get("errors"),
        "warnings": host.get("warnings"),
        "rates": host.get("rates"),
        "net_delta": host.get("net_delta"),
        "ethtool_delta": host.get("ethtool_delta"),
    }


def _prepare_receiver(
    *,
    receiver_control_url: str,
    bandwidth_mhz: int,
    mode: str,
) -> dict[str, Any]:
    request = urllib.request.Request(
        receiver_control_url.rstrip("/") + "/api/config",
        data=json.dumps(
            {"bandwidth_mhz": bandwidth_mhz, "output_mode": mode}
        ).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=5.0) as response:
        value = json.loads(response.read().decode("utf-8"))
    if not isinstance(value, dict) or not bool(value.get("ok")):
        raise RuntimeError(f"receiver pre-configuration failed: {value}")
    # Receiver fanout workers poll config_generation every 100 ms.  Perform
    # this while FPGA science is stopped and leave ample time for every worker
    # to clear its previous-run continuity tail before the scheduled commit.
    time.sleep(1.0)
    return value


def _git_sha(root: Path) -> str:
    process = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    return process.stdout.strip() if process.returncode == 0 else "unknown"


def _request(
    base: str,
    path: str,
    body: dict[str, Any] | None = None,
    *,
    timeout: float = 190.0,
) -> dict[str, Any]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        base.rstrip("/") + path,
        data=data,
        headers={"Content-Type": "application/json"} if data is not None else {},
        method="POST" if data is not None else "GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            value = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"{request.full_url}: HTTP {exc.code}: {details}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"{request.full_url}: response is not an object")
    result = value.get("result", value)
    if not isinstance(result, dict):
        raise RuntimeError(f"{request.full_url}: response has no result object")
    return result


def _configured_body(template: dict[str, Any], bandwidth_mhz: int, mode: str) -> dict[str, Any]:
    # JSON round trip provides a dependency-free deep copy.
    body = json.loads(json.dumps(template))
    profile = body["profile"]
    profile["bandwidth_mhz"] = bandwidth_mhz
    profile["mode"] = mode
    enabled = {
        "time_only": {"TIME"},
        "spec_only": {"SPEC"},
        "time_spec": {"TIME", "SPEC"},
    }[mode]
    for endpoint in body["endpoints"]:
        endpoint["enabled"] = str(endpoint["stream"]).upper() in enabled
    return body


def _compact_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        key: snapshot.get(key)
        for key in (
            "captured_at_unix_ms",
            "core_version",
            "board_id",
            "streaming",
            "profile",
            "clock",
            "mts",
            "halfband",
            "timing",
            "qsfp",
            "pipeline",
            "counters",
            "channelizer",
            "sample0",
            "error_flags",
            "scheduled_sync",
        )
    }


def _qsfp_physical_healthy(snapshot: dict[str, Any]) -> bool:
    raw = int(dict(snapshot.get("qsfp", {})).get("raw_flags", 0) or 0)
    required = (2, 3, 12, 13, 14, 15, 18, 19)
    faults = (5, 6, 17, 20, 21, 22)
    return all((raw >> bit) & 1 for bit in required) and not any(
        (raw >> bit) & 1 for bit in faults
    )


def _counter_delta(after: dict[str, Any], before: dict[str, Any], key: str) -> int:
    return int(after.get(key, 0) or 0) - int(before.get(key, 0) or 0)


def _validate_configure(
    snapshot: dict[str, Any],
    *,
    bandwidth_mhz: int,
    mode: str,
) -> list[str]:
    errors: list[str] = []
    profile = dict(snapshot.get("profile", {}))
    clock = dict(snapshot.get("clock", {}))
    mts = dict(snapshot.get("mts", {}))
    halfband = dict(snapshot.get("halfband", {}))
    pipeline = dict(snapshot.get("pipeline", {}))
    if snapshot.get("core_version") != "0x00010032":
        errors.append("CORE_VERSION_MISMATCH")
    if int(profile.get("bandwidth_mhz", 0)) != bandwidth_mhz:
        errors.append("BANDWIDTH_MISMATCH")
    if str(profile.get("mode")) != mode:
        errors.append("MODE_MISMATCH")
    if bool(snapshot.get("streaming")):
        errors.append("CONFIGURE_LEFT_STREAMING")
    if not bool(pipeline.get("flush_clean")):
        errors.append("CONFIGURE_PIPELINE_NOT_CLEAN")
    if clock.get("profile_id") != "stage32_160_10m_cont_manual_clkin2":
        errors.append("LMK_PROFILE_MISMATCH")
    if clock.get("sysref_mode") != "continuous":
        errors.append("SYSREF_NOT_CONTINUOUS")
    if int(clock.get("pll1_lock", 0)) != 1 or int(clock.get("pll2_lock", 0)) != 1:
        errors.append("LMK_PLL_NOT_LOCKED")
    if not bool(clock.get("configured")) or clock.get("errors"):
        errors.append("LMK_STATUS_NOT_CLEAN")
    if not bool(mts.get("available")):
        errors.append("MTS_UNAVAILABLE")
    for kind, target in (("adc", 230), ("dac", 336)):
        item = dict(mts.get(kind, {}))
        if int(item.get("target_latency", -1)) != target:
            errors.append(f"MTS_{kind.upper()}_TARGET_MISMATCH")
        measured = [int(value) for value in item.get("active_measured_latency", [])]
        if len(measured) != 4 or len(set(measured)) != 1:
            errors.append(f"MTS_{kind.upper()}_TILES_NOT_ALIGNED")
        if any(value > target for value in measured):
            errors.append(f"MTS_{kind.upper()}_OVER_TARGET")
    if str(halfband.get("coefficient_id", "")).lower() != "0xaa160055":
        errors.append("HALFBAND_COEFFICIENT_MISMATCH")
    if int(halfband.get("taps", 0)) != 55:
        errors.append("HALFBAND_TAPS_MISMATCH")
    if bandwidth_mhz == 160 and not bool(halfband.get("active")):
        errors.append("HALFBAND_NOT_ACTIVE")
    if bandwidth_mhz == 320 and bool(halfband.get("active")):
        errors.append("HALFBAND_ACTIVE_IN_320")
    sync = dict(snapshot.get("scheduled_sync", {}))
    if not all(bool(sync.get(key)) for key in ("ref_locked", "rfdc_ready", "pps_recent")):
        errors.append("SYNC_NOT_TIMING_READY")
    if int(sync.get("mts_result_id", 0)) == 0:
        errors.append("SYNC_MTS_RESULT_ID_MISSING")
    if int(snapshot.get("error_flags", 0) or 0) != 0:
        errors.append("BOARD_ERROR_FLAGS_NONZERO")
    if not _qsfp_physical_healthy(snapshot):
        errors.append("QSFP_PHYSICAL_HEALTH_BAD")
    return errors


def _validate_progress(
    first: dict[str, Any],
    second: dict[str, Any],
    *,
    bandwidth_mhz: int,
    mode: str,
    generation: int,
    target_pps: int,
    first_sample0: int,
) -> tuple[list[str], dict[str, int]]:
    errors: list[str] = []
    sync = dict(second.get("sync", {}))
    before = dict(first.get("snapshot", {}))
    after = dict(second.get("snapshot", {}))
    before_counters = dict(before.get("counters", {}))
    after_counters = dict(after.get("counters", {}))
    before_pfb = dict(before.get("channelizer", {}))
    after_pfb = dict(after.get("channelizer", {}))
    needs_time = mode in ("time_only", "time_spec")
    needs_spec = mode in ("spec_only", "time_spec")

    if bool(sync.get("error")) or int(sync.get("error_code", 0)) != 0:
        errors.append("SYNC_ERROR")
    if int(sync.get("active_generation", 0)) != generation:
        errors.append("ACTIVE_GENERATION_MISMATCH")
    if not bool(sync.get("epoch_committed")) or not bool(sync.get("epoch_valid")):
        errors.append("EPOCH_NOT_COMMITTED")
    if int(sync.get("actual_commit_pps_count", 0)) != target_pps:
        errors.append("COMMIT_PPS_MISMATCH")
    if int(sync.get("target_pps_count", 0)) != target_pps:
        errors.append("TARGET_PPS_READBACK_MISMATCH")
    if needs_time:
        if not bool(sync.get("first_time_seen")):
            errors.append("FIRST_TIME_NOT_SEEN")
        if int(sync.get("actual_first_time_sample0", 0)) != first_sample0:
            errors.append("FIRST_TIME_SAMPLE0_MISMATCH")
    elif int(sync.get("actual_first_time_sample0", 0)) != 0:
        errors.append("UNEXPECTED_TIME_FIRST_SAMPLE0")
    if needs_spec:
        if not bool(sync.get("first_spec_seen")):
            errors.append("FIRST_SPEC_NOT_SEEN")
        if int(sync.get("actual_first_spec_sample0", 0)) != first_sample0:
            errors.append("FIRST_SPEC_SAMPLE0_MISMATCH")
    elif int(sync.get("actual_first_spec_sample0", 0)) != 0:
        errors.append("UNEXPECTED_SPEC_FIRST_SAMPLE0")
    modulus, residue = ((8, 4) if bandwidth_mhz == 160 else (4, 0))
    if first_sample0 % modulus != residue:
        errors.append("FIRST_SAMPLE0_ALIGNMENT_MISMATCH")
    if not bool(sync.get("streaming")) or not bool(after.get("streaming")):
        errors.append("NOT_STREAMING_AFTER_COMMIT")
    if not bool(dict(after.get("pipeline", {})).get("stream_accepting")):
        errors.append("PIPELINE_NOT_ACCEPTING")
    if bool(dict(after.get("pipeline", {})).get("cmac_mux_stale_science_frame")):
        errors.append("STALE_SCIENCE_FRAME")
    if not _qsfp_physical_healthy(after):
        errors.append("QSFP_PHYSICAL_HEALTH_BAD")

    deltas = {
        key: _counter_delta(after_counters, before_counters, key)
        for key in set(DROP_COUNTERS) | {"time_packets", "spec_packets"}
    }
    if needs_time and deltas["time_packets"] <= 0:
        errors.append("TIME_PACKETS_NOT_ADVANCING")
    if not needs_time and deltas["time_packets"] != 0:
        errors.append("TIME_PACKETS_IN_DISABLED_MODE")
    if needs_spec and deltas["spec_packets"] <= 0:
        errors.append("SPEC_PACKETS_NOT_ADVANCING")
    if not needs_spec and deltas["spec_packets"] != 0:
        errors.append("SPEC_PACKETS_IN_DISABLED_MODE")
    for key in DROP_COUNTERS:
        if deltas[key] != 0:
            errors.append(f"NONZERO_{key.upper()}_DELTA")
    if needs_spec:
        if _counter_delta(after_pfb, before_pfb, "frame_count") <= 0:
            errors.append("PFB_FRAMES_NOT_ADVANCING")
        for key in PFB_ERROR_COUNTERS:
            if int(before_pfb.get(key, 0) or 0) != 0:
                errors.append(f"NONZERO_INITIAL_PFB_{key.upper()}")
            if _counter_delta(after_pfb, before_pfb, key) != 0:
                errors.append(f"NONZERO_PFB_{key.upper()}_DELTA")
    return errors, deltas


def _stop_clean(base: str) -> tuple[dict[str, Any], list[str]]:
    result = _request(base, "/api/v1/stop", {"reason": "stage32h_pps_switch"})
    snapshot = dict(result.get("snapshot", {}))
    pipeline = dict(snapshot.get("pipeline", {}))
    errors: list[str] = []
    if not bool(result.get("stopped")) or bool(snapshot.get("streaming")):
        errors.append("STOP_DID_NOT_STOP")
    if not bool(pipeline.get("flush_clean")):
        errors.append("STOP_PIPELINE_NOT_CLEAN")
    if bool(pipeline.get("stream_accepting")):
        errors.append("STOP_PIPELINE_STILL_ACCEPTING")
    return result, errors


def _wait_for_commit_pair(
    base: str,
    *,
    generation: int,
    target_pps: int,
    timeout_seconds: float,
    after_commit: Callable[[], dict[str, Any]] | None = None,
) -> tuple[
    list[dict[str, Any]],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any] | None,
]:
    """Return the first committed sample and one later progress sample."""
    deadline = time.monotonic() + timeout_seconds
    polls: list[dict[str, Any]] = []
    committed: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        result = _request(base, "/api/v1/sync/status")
        polls.append(
            {
                "sync": result.get("sync"),
                "snapshot": _compact_snapshot(dict(result.get("snapshot", {}))),
            }
        )
        sync = dict(result.get("sync", {}))
        if bool(sync.get("error")):
            raise RuntimeError(
                f"sync error while waiting for PPS commit: {sync.get('error_name')}"
            )
        if (
            bool(sync.get("epoch_committed"))
            and bool(sync.get("streaming"))
            and int(sync.get("active_generation", 0)) == generation
            and int(sync.get("actual_commit_pps_count", 0)) == target_pps
        ):
            committed = result
            break
    if committed is None:
        last_sync = polls[-1]["sync"] if polls else None
        raise TimeoutError(f"PPS commit not observed before timeout: {last_sync}")
    after_commit_result = after_commit() if after_commit is not None else None
    later = _request(base, "/api/v1/sync/status")
    polls.append(
        {
            "sync": later.get("sync"),
            "snapshot": _compact_snapshot(dict(later.get("snapshot", {}))),
        }
    )
    return polls, committed, later, after_commit_result


def _run_switch(
    base: str,
    template: dict[str, Any],
    *,
    switch_index: int,
    bandwidth_mhz: int,
    mode: str,
    generation_base: int,
    lead_pps: int,
    first_sample0_override: int | None = None,
    host_seconds: float = 0.0,
    receiver_ssh: str = "astrolab@192.168.100.162",
    receiver_control_url: str = "http://192.168.100.162:8089",
    receiver_base_url: str = "http://127.0.0.1:8089",
    receiver_interface: str = "enp1s0f0np0",
    remote_validator: str = (
        "/home/astrolab/.cache/t510-stage32/stage29_host_validate.py"
    ),
    local_host_output: Path | None = None,
) -> dict[str, Any]:
    generation = generation_base + switch_index
    evidence: dict[str, Any] = {
        "ok": False,
        "classification": "STAGE32H_PPS_SWITCH_IN_PROGRESS",
        "switch_index": switch_index,
        "bandwidth_mhz": bandwidth_mhz,
        "mode": mode,
        "generation": generation,
        "started_at": _timestamp(),
        "errors": [],
    }
    prepared = False
    try:
        configure = _request(
            base,
            "/api/v1/configure",
            _configured_body(template, bandwidth_mhz, mode),
        )
        configured = dict(configure.get("status", {}))
        evidence["configure"] = {
            "elapsed_ms": configure.get("elapsed_ms"),
            "bitstream": configure.get("bitstream"),
            "snapshot": _compact_snapshot(configured),
        }
        evidence["errors"].extend(
            _validate_configure(
                configured,
                bandwidth_mhz=bandwidth_mhz,
                mode=mode,
            )
        )
        if evidence["errors"]:
            raise RuntimeError("configure gate failed")

        if host_seconds > 0.0:
            evidence["receiver_prepare"] = _prepare_receiver(
                receiver_control_url=receiver_control_url,
                bandwidth_mhz=bandwidth_mhz,
                mode=mode,
            )

        initial = _request(base, "/api/v1/sync/status")
        sync = dict(initial.get("sync", {}))
        target_pps = int(sync["current_pps_count"]) + lead_pps
        first_sample0 = (
            int(sync["default_first_sample0"])
            if first_sample0_override is None
            else first_sample0_override
        )
        modulus = int(sync["first_sample0_modulus"])
        residue = int(sync["first_sample0_residue"])
        expected_rule = (8, 4) if bandwidth_mhz == 160 else (4, 0)
        if (modulus, residue) != expected_rule:
            raise RuntimeError(
                f"unexpected path rule {(modulus, residue)} != {expected_rule}"
            )
        prepare_body = {
            "expected_board_id": int(template["board_id"]),
            "generation": generation,
            "target_pps_count": target_pps,
            "epoch_tai_seconds": int(time.time()) + lead_pps,
            "first_sample0": first_sample0,
            "observation_tag": 0x53324843,
            "signal_chain_tag": SIGNAL_CHAIN_TAGS[(bandwidth_mhz, mode)],
            "schedule_tag": switch_index,
            "mts_result_id": int(sync["mts_result_id"]),
        }
        evidence["transaction"] = {
            "initial_sync": sync,
            "prepare_body": prepare_body,
        }
        prepared_result = _request(base, "/api/v1/sync/prepare", prepare_body)
        prepared = True
        evidence["transaction"]["prepare_sync"] = prepared_result.get("sync")
        armed_result = _request(
            base,
            "/api/v1/sync/arm",
            {"expected_board_id": int(template["board_id"])},
        )
        evidence["transaction"]["arm_sync"] = armed_result.get("sync")

        host_gate = None
        if host_seconds > 0.0:
            if local_host_output is None:
                raise RuntimeError("host gate requested without a local evidence path")
            remote_output = (
                "/home/astrolab/.cache/t510-stage32/"
                f"stage32h_scheduled_host_{generation}.json"
            )
            host_gate = lambda: _run_receiver_validation(
                receiver_ssh=receiver_ssh,
                remote_validator=remote_validator,
                remote_output=remote_output,
                receiver_base_url=receiver_base_url,
                receiver_interface=receiver_interface,
                bandwidth_mhz=bandwidth_mhz,
                mode=mode,
                seconds=host_seconds,
                local_output=local_host_output,
            )
        (
            progress_polls,
            progress_first,
            progress_second,
            host_result,
        ) = _wait_for_commit_pair(
            base,
            generation=generation,
            target_pps=target_pps,
            timeout_seconds=float(lead_pps + host_seconds + 60),
            after_commit=host_gate,
        )
        if host_result is not None:
            evidence["host"] = host_result
            if int(host_result.get("returncode", 1)) != 0:
                evidence["errors"].append("HOST_VALIDATOR_PROCESS_FAILED")
            if not bool(host_result.get("ok")):
                evidence["errors"].append("HOST_VALIDATOR_GATE_FAILED")
        evidence["progress"] = {
            "polls": progress_polls,
            "first": {
                "sync": progress_first.get("sync"),
                "snapshot": _compact_snapshot(dict(progress_first.get("snapshot", {}))),
            },
            "second": {
                "sync": progress_second.get("sync"),
                "snapshot": _compact_snapshot(dict(progress_second.get("snapshot", {}))),
            },
        }
        progress_errors, counter_delta = _validate_progress(
            progress_first,
            progress_second,
            bandwidth_mhz=bandwidth_mhz,
            mode=mode,
            generation=generation,
            target_pps=target_pps,
            first_sample0=first_sample0,
        )
        evidence["counter_delta"] = counter_delta
        evidence["errors"].extend(progress_errors)
    except Exception as exc:
        evidence["errors"].append(f"{type(exc).__name__}: {exc}")
        if prepared:
            try:
                evidence["abort"] = _request(
                    base,
                    "/api/v1/sync/abort",
                    {"expected_board_id": int(template["board_id"])},
                )
            except Exception as abort_exc:
                evidence["errors"].append(
                    f"ABORT_FAILED:{type(abort_exc).__name__}:{abort_exc}"
                )
    finally:
        try:
            stop, stop_errors = _stop_clean(base)
            evidence["stop"] = {
                "stopped": stop.get("stopped"),
                "snapshot": _compact_snapshot(dict(stop.get("snapshot", {}))),
            }
            evidence["errors"].extend(stop_errors)
        except Exception as stop_exc:
            evidence["errors"].append(
                f"STOP_FAILED:{type(stop_exc).__name__}:{stop_exc}"
            )
    evidence["ended_at"] = _timestamp()
    evidence["ok"] = not evidence["errors"]
    evidence["classification"] = (
        "STAGE32H_PPS_SWITCH_PASS" if evidence["ok"] else "STAGE32H_PPS_SWITCH_FAIL"
    )
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument(
        "--config",
        default="config/stage32/configure_160_time_only.example.json",
    )
    parser.add_argument("--output-dir", default="reports/board")
    parser.add_argument("--agent-base", default="http://192.168.100.117:8010")
    parser.add_argument("--lead-pps", type=int, default=35)
    parser.add_argument("--generation-base", type=int, default=3_200_000_000)
    parser.add_argument(
        "--first-sample0",
        type=int,
        help=(
            "diagnostic override for the scheduled release sample; the default "
            "uses the FPGA-reported first_sample0"
        ),
    )
    parser.add_argument(
        "--host-seconds",
        type=float,
        default=0.0,
        help="run the receiver-host validator for this many seconds after PPS commit",
    )
    parser.add_argument("--receiver-ssh", default="astrolab@192.168.100.162")
    parser.add_argument(
        "--receiver-control-url",
        default="http://192.168.100.162:8089",
    )
    parser.add_argument("--receiver-base-url", default="http://127.0.0.1:8089")
    parser.add_argument("--receiver-interface", default="enp1s0f0np0")
    parser.add_argument(
        "--remote-validator",
        default="/home/astrolab/.cache/t510-stage32/stage29_host_validate.py",
    )
    parser.add_argument(
        "--only-case",
        choices=tuple(CASE_NAMES),
        help="repeat one targeted Stage 32 mode instead of cycling all five modes",
    )
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.iterations <= 0:
        parser.error("--iterations must be positive")
    if args.lead_pps < 30:
        parser.error("--lead-pps must be at least 30 for stateless helper latency")
    if args.generation_base <= 0:
        parser.error("--generation-base must be positive")
    if args.first_sample0 is not None and args.first_sample0 <= 0:
        parser.error("--first-sample0 must be positive")
    if args.host_seconds < 0.0:
        parser.error("--host-seconds cannot be negative")

    root = _root()
    config_path = root / args.config
    template = _read_json(config_path)
    output_dir = root / args.output_dir
    summary_path = output_dir / f"stage32h_pps_switch_summary_{args.tag}.json"
    summary: dict[str, Any] = {
        "ok": False,
        "classification": "STAGE32H_PPS_SWITCH_CAMPAIGN_IN_PROGRESS",
        "stage": "32h-c",
        "tag": args.tag,
        "iterations_required": args.iterations,
        "lead_pps": args.lead_pps,
        "generation_base": args.generation_base,
        "first_sample0_override": args.first_sample0,
        "host_seconds": args.host_seconds,
        "receiver_ssh": args.receiver_ssh if args.host_seconds > 0.0 else None,
        "only_case": args.only_case,
        "agent_base": args.agent_base,
        "config": args.config,
        "config_sha256": _sha256(config_path),
        "script_sha256": _sha256(Path(__file__)),
        "git_sha": _git_sha(root),
        "started_at": _timestamp(),
        "ended_at": None,
        "passes": 0,
        "failures": 0,
        "switches": [],
        "errors": [],
    }
    _write_json(summary_path, summary)

    for switch_index in range(1, args.iterations + 1):
        bandwidth_mhz, mode = (
            CASE_NAMES[args.only_case]
            if args.only_case
            else CASES[(switch_index - 1) % len(CASES)]
        )
        case_path = output_dir / (
            f"stage32h_pps_switch_{switch_index:03d}_"
            f"{bandwidth_mhz}msps_{mode}_{args.tag}.json"
        )
        if case_path.exists():
            if not args.resume:
                summary["errors"].append(f"EVIDENCE_EXISTS:{case_path}")
                break
            existing = _read_json(case_path)
            if bool(existing.get("ok")):
                summary["switches"].append(
                    {
                        "switch_index": switch_index,
                        "bandwidth_mhz": bandwidth_mhz,
                        "mode": mode,
                        "ok": True,
                        "resumed": True,
                        "evidence": str(case_path),
                        "evidence_sha256": _sha256(case_path),
                    }
                )
                summary["passes"] += 1
                _write_json(summary_path, summary)
                print(f"RESUME PASS switch {switch_index:03d}", flush=True)
                continue

        if args.dry_run:
            print(
                f"DRY RUN switch {switch_index:03d}: {bandwidth_mhz} {mode}",
                flush=True,
            )
            continue

        print(
            f"START switch {switch_index:03d}/{args.iterations}: "
            f"{bandwidth_mhz} MS/s {mode}",
            flush=True,
        )
        evidence = _run_switch(
            args.agent_base,
            template,
            switch_index=switch_index,
            bandwidth_mhz=bandwidth_mhz,
            mode=mode,
            generation_base=args.generation_base,
            lead_pps=args.lead_pps,
            first_sample0_override=args.first_sample0,
            host_seconds=args.host_seconds,
            receiver_ssh=args.receiver_ssh,
            receiver_control_url=args.receiver_control_url,
            receiver_base_url=args.receiver_base_url,
            receiver_interface=args.receiver_interface,
            remote_validator=args.remote_validator,
            local_host_output=case_path.with_name(
                f"{case_path.stem}_host.json"
            ),
        )
        _write_json(case_path, evidence)
        row = {
            "switch_index": switch_index,
            "bandwidth_mhz": bandwidth_mhz,
            "mode": mode,
            "ok": bool(evidence["ok"]),
            "resumed": False,
            "classification": evidence["classification"],
            "evidence": str(case_path),
            "evidence_sha256": _sha256(case_path),
            "counter_delta": evidence.get("counter_delta"),
            "errors": evidence.get("errors"),
            "host": evidence.get("host"),
        }
        summary["switches"].append(row)
        if evidence["ok"]:
            summary["passes"] += 1
            print(f"PASS switch {switch_index:03d}", flush=True)
        else:
            summary["failures"] += 1
            summary["errors"].append(f"SWITCH_FAILED:{switch_index:03d}")
            print(json.dumps(row, indent=2, sort_keys=True), flush=True)
        _write_json(summary_path, summary)
        if not evidence["ok"]:
            break

    if args.dry_run:
        summary["ok"] = True
        summary["classification"] = "STAGE32H_PPS_SWITCH_CAMPAIGN_DRY_RUN"
    else:
        summary["ok"] = (
            summary["passes"] == args.iterations
            and summary["failures"] == 0
            and not summary["errors"]
        )
        summary["classification"] = (
            "STAGE32H_PPS_SWITCH_CAMPAIGN_PASS"
            if summary["ok"]
            else "STAGE32H_PPS_SWITCH_CAMPAIGN_FAIL"
        )
    summary["ended_at"] = _timestamp()
    _write_json(summary_path, summary)
    print(json.dumps(summary, indent=2, sort_keys=True), flush=True)
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
