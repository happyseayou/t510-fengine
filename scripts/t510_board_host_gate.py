#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.request
from typing import Any
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from python.t510_scaling import manifest_metadata


START_WARMUP_SECONDS = 3.0
EXPECTED_CLOCK_PROFILE = "160m_10m_request_manual_clkin0"
EXPECTED_CLOCK_SHA256 = "a8504d384354610f8f130b1cda1a446bcdfb25bf8c4bb689fbb58adefe5e88e2"
EXPECTED_MTS_TARGETS = {"adc": 492, "dac": -1}
RECEIVER_LOSS_COUNTERS = (
    "kernel_drops", "ring_drops", "worker_ring_drops", "app_drops",
    "parse_errors", "seq_gaps", "frame_gaps", "sample0_gaps",
    "spec_seq_gaps", "spec_frame_gaps",
)


def _http_json(url: str, *, body: dict[str, Any] | None = None, timeout: float = 30.0) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=None if body is None else json.dumps(body).encode("utf-8"),
        headers={} if body is None else {"Content-Type": "application/json"},
        method="GET" if body is None else "POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            value = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} from {url}: {payload}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"non-object JSON from {url}")
    return value


def _result(value: dict[str, Any]) -> dict[str, Any]:
    result = value.get("result")
    if not isinstance(result, dict):
        raise RuntimeError(f"Agent response has no result object: {value}")
    return result


def _remote_run(
    ssh_target: str, argv: list[str], **kwargs: Any,
) -> subprocess.CompletedProcess[str]:
    """Run an argv on the receiver without losing argument boundaries to ssh.

    OpenSSH joins every argument after the host into one command string for the
    remote shell.  Passing ``python3``, ``-c`` and Python source as separate
    local argv elements therefore strips the source's grouping.  Render the
    complete remote argv with POSIX shell quoting before handing it to ssh.
    """
    remote_command = shlex.join([str(argument) for argument in argv])
    return subprocess.run(
        ["ssh", "-o", "BatchMode=yes", ssh_target, remote_command], **kwargs
    )


def _remote_receiver_state(ssh_target: str, base_url: str) -> dict[str, Any]:
    completed = _remote_run(
        ssh_target,
        ["python3", "-c",
        (
            "import json,sys,urllib.request; "
            "print(json.dumps(json.load(urllib.request.urlopen("
            "sys.argv[1].rstrip('/')+'/api/state',timeout=5))))"
        ),
        base_url],
        text=True, capture_output=True, check=False,
    )
    if completed.returncode:
        raise RuntimeError(
            "receiver state read failed: " + (completed.stderr or completed.stdout)
        )
    value = json.loads(completed.stdout)
    if not isinstance(value, dict):
        raise RuntimeError("receiver state is not an object")
    return value.get("result", value)


def _safe_stop(
    base: str, *, reason: str, expected_board_id: int,
    sample_rate_msps: int, mode: str, center_mhz: float,
    reference: str = "onboard_tcxo", targets: dict[str, int] | None = None,
    expected_core: str | None = None,
) -> dict[str, Any]:
    """Issue STOP once and accept a lost reply only after strict safe readback."""
    transport_error: str | None = None
    initial = _result(_http_json(base + "/api/v2/status", timeout=30.0))
    if bool(initial.get("streaming")):
        try:
            _http_json(
                base + "/api/v2/stop", body={"reason": reason}, timeout=30.0
            )
        except Exception as exc:
            transport_error = f"{type(exc).__name__}: {exc}"

    read_errors: list[str] = []
    snapshot: dict[str, Any] | None = None
    for attempt in range(3):
        try:
            snapshot = _result(_http_json(base + "/api/v2/status", timeout=30.0))
            break
        except Exception as exc:
            read_errors.append(f"{type(exc).__name__}: {exc}")
            if attempt < 2:
                time.sleep(1.0)
    if snapshot is None:
        raise RuntimeError(
            f"STOP status read failed: transport={transport_error}; reads={read_errors}"
        )

    errors: list[str] = []
    if bool(snapshot.get("streaming")):
        errors.append("BOARD_STILL_STREAMING")
    if int(snapshot.get("board_id", -1)) != expected_board_id:
        errors.append("BOARD_ID_MISMATCH")
    if expected_core is not None and str(snapshot.get("core_version", "")).lower() != expected_core.lower():
        errors.append("CORE_VERSION_MISMATCH")
    if int(snapshot.get("dac", {}).get("enable_mask", -1)) != 0:
        errors.append("DAC_NOT_MUTED")
    profile = snapshot.get("profile", {})
    if int(profile.get("sample_rate_msps", -1)) != sample_rate_msps:
        errors.append("SAMPLE_RATE_MISMATCH")
    if str(profile.get("mode")) != mode:
        errors.append("MODE_MISMATCH")
    if abs(float(profile.get("center_mhz", 0.0)) - center_mhz) > 1.0e-6:
        errors.append("CENTER_FREQUENCY_MISMATCH")
    errors.extend(_current_metadata_errors(snapshot, reference=reference, targets=targets))
    errors.extend(_t510_rfdc_health(snapshot, require_valid=False)["errors"])
    if errors:
        raise RuntimeError(
            f"STOP safe readback failed: transport={transport_error}; errors={errors}"
        )
    return {
        "stopped": True,
        "stop_response_transport_error": transport_error,
        "idempotent_readback_accepted": transport_error is not None,
        "snapshot": _compact_board(snapshot),
    }


def _incremental_telemetry(base: str, before: dict[str, Any]) -> dict[str, Any]:
    marker = before.get("reference_watchdog", {}).get("power_thermal_telemetry", {})
    sequence = int(marker.get("sequence", 0) or 0)
    epoch = marker.get("epoch_id")
    if sequence <= 0 or epoch is None:
        raise RuntimeError("power/thermal telemetry cursor is unavailable before formal gate")
    value = _result(
        _http_json(
            base + f"/api/v2/telemetry/power-thermal?since_seq={sequence}",
            timeout=30.0,
        )
    )
    errors: list[str] = []
    if epoch is not None and value.get("epoch_id") is not None and str(value["epoch_id"]) != str(epoch):
        errors.append("TELEMETRY_EPOCH_CHANGED")
    records = value.get("records", [])
    if not isinstance(records, list) or not records:
        errors.append("TELEMETRY_EMPTY")
    elif int(value.get("first_sequence", -1)) != sequence + 1:
        errors.append("TELEMETRY_SEQUENCE_GAP")
    elif any(int(row.get("sequence", -1)) != sequence + index + 1
             for index, row in enumerate(records)):
        errors.append("TELEMETRY_RECORDS_NOT_CONTIGUOUS")
    if isinstance(records, list) and any(str(row.get("epoch_id")) != str(epoch) for row in records):
        errors.append("TELEMETRY_RECORD_EPOCH_CHANGED")
    if int(value.get("record_count", -1)) != len(records):
        errors.append("TELEMETRY_RECORD_COUNT_MISMATCH")
    return {
        "source": value.get("source"), "since_seq": sequence,
        "record_count": value.get("record_count"),
        "first_sequence": value.get("first_sequence"),
        "last_sequence": value.get("last_sequence"),
        "epoch_id": value.get("epoch_id"), "records": records, "errors": errors,
    }


def _counter_delta(after: dict[str, Any], before: dict[str, Any], key: str) -> int:
    return int(after.get(key, 0) or 0) - int(before.get(key, 0) or 0)


def _startup_receiver_boundary(
    after: dict[str, Any], before: dict[str, Any],
) -> dict[str, Any]:
    """Record receiver discontinuities before the frozen formal window.

    The qualified sequence is START -> 3 s warmup -> freeze-before as the capture
    boundary.  A profile change can produce one continuity event while the
    receiver still remembers the previous stream.  Preserve that evidence but
    do not apply it to the subsequent 60 s interval.
    """
    delta = {
        key: _counter_delta(after, before, key) for key in RECEIVER_LOSS_COUNTERS
    }
    events = [
        f"receiver.{key} delta={value}" for key, value in delta.items() if value
    ]
    return {
        "receiver_counter_delta": delta,
        "receiver_boundary_events": events,
        "excluded_from_formal_window": True,
    }


def _current_metadata_errors(
    snapshot: dict[str, Any], *, reference: str = "onboard_tcxo",
    targets: dict[str, int] | None = None,
) -> list[str]:
    errors: list[str] = []
    clock = snapshot.get("clock", {})
    if clock.get("clock_reference") != reference:
        errors.append("CLOCK_REFERENCE_MISMATCH")
    if reference == "onboard_tcxo":
        if clock.get("profile_id") != EXPECTED_CLOCK_PROFILE:
            errors.append("CLOCK_PROFILE_MISMATCH")
        if clock.get("profile_sha256") != EXPECTED_CLOCK_SHA256:
            errors.append("CLOCK_PROFILE_SHA256_MISMATCH")
    elif "clkin2" not in str(clock.get("profile_id", "")).lower():
        errors.append("EXTERNAL_CLKIN2_PROFILE_MISMATCH")
    if int(clock.get("pll1_lock", 0)) != 1 or int(clock.get("pll2_lock", 0)) != 1:
        errors.append("CLOCK_PLL_UNLOCKED")
    mts = snapshot.get("mts", {})
    for kind, expected in (targets or EXPECTED_MTS_TARGETS).items():
        if int(mts.get(kind, {}).get("target_latency", -1)) != expected:
            errors.append(f"{kind.upper()}_MTS_TARGET_MISMATCH")
    return errors


def _qsfp_physical_health(qsfp: dict[str, Any]) -> dict[str, Any]:
    """Decode stable physical CMAC health without using AXIS TREADY.

    The current bitstream's `link_up` includes `tx_axis_tready_raw`.  TREADY
    may legally be low for pause/backpressure at the exact status sample, so
    it is not a persistent physical-link condition.
    """
    raw = int(qsfp.get("raw_flags", 0) or 0)
    required_bits = {
        "cmac_reset_done": 2,
        "gt_locked": 3,
        "module_present": 12,
        "gt_refclk_seen": 13,
        "gt_tx_reset_done": 14,
        "gt_rx_reset_done": 15,
        "rx_aligned": 18,
        "rx_status": 19,
    }
    fault_bits = {
        "local_fault": 5,
        "remote_fault": 6,
        "tx_overflow": 17,
        "rx_local_fault": 20,
        "rx_internal_local_fault": 21,
        "tx_local_fault_detail": 22,
    }
    required = {name: bool((raw >> bit) & 0x1) for name, bit in required_bits.items()}
    faults = {name: bool((raw >> bit) & 0x1) for name, bit in fault_bits.items()}
    return {
        "physical_healthy": bool(all(required.values()) and not any(faults.values())),
        "link_up_sample": bool(qsfp.get("link_up", False)),
        "tx_ready_sample": bool((raw >> 4) & 0x1),
        "raw_flags": raw,
        "required": required,
        "faults": faults,
    }


def _compact_board(value: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value.get(key)
        for key in (
            "captured_at_unix_ms",
            "core_version",
            "digital_scaling",
            "board_id",
            "streaming",
            "error_flags",
            "profile",
            "clock",
            "rfdc",
            "mts",
            "halfband",
            "channelizer",
            "qsfp",
            "pipeline",
            "counters",
            "sample0",
            "timing",
        )
    }


def _t510_rfdc_health(
    snapshot: dict[str, Any], *, require_valid: bool,
    expected_core: str | None = None,
) -> dict[str, Any]:
    errors: list[str] = []
    try:
        identity = snapshot['digital_scaling']
        if expected_core is not None and identity['core_version'].lower() != expected_core.lower():
            raise ValueError('wrong scaling core version')
        manifest_metadata(identity)
    except (KeyError, TypeError, ValueError):
        errors.append('DIGITAL_SCALING_READBACK_FAILED')
    if int(snapshot.get("error_flags", 0)) != 0:
        errors.append("FPGA_ERROR_FLAGS_NONZERO")
    rfdc = snapshot.get("rfdc", {})
    expected_scalars = {
        "adc_analog_sample_rate_hz": 3_840_000_000,
        "dac_analog_sample_rate_hz": 3_840_000_000,
        "complex_sample_rate_hz": 320_000_000,
        "adc_decimation": 12,
        "dac_interpolation": 12,
        "adc_axis_rate_hz": 80_000_000,
        "dac_axis_rate_hz": 80_000_000,
    }
    for name, expected in expected_scalars.items():
        if int(rfdc.get(name, -1)) != expected:
            errors.append(f"RFDC_{name.upper()}_MISMATCH")
    readback = rfdc.get("readback", {})
    if readback.get("ok") is not True:
        errors.append("RFDC_READBACK_CONTRACT_FAILED")
    counts = readback.get("active_block_count", {})
    if counts != {"adc": 8, "dac": 8}:
        errors.append("RFDC_ACTIVE_BLOCK_COUNT_MISMATCH")
    center_mhz = float(snapshot.get("profile", {}).get("center_mhz") or 0.0)
    tiles = readback.get("tiles", [])
    if len(tiles) != 8:
        errors.append("RFDC_TILE_COUNT_MISMATCH")
    for tile in tiles:
        if int(tile.get("pll_lock_status", 0)) == 0:
            errors.append(f"RFDC_{str(tile.get('kind', '')).upper()}{tile.get('tile')}_PLL_UNLOCKED")
        if abs(float(tile.get("sample_rate_hz", 0.0)) - 3_840_000_000.0) > 1.0:
            errors.append(f"RFDC_{str(tile.get('kind', '')).upper()}{tile.get('tile')}_RATE_MISMATCH")
    blocks = readback.get("blocks", [])
    if len(blocks) != 16:
        errors.append("RFDC_BLOCK_READBACK_COUNT_MISMATCH")
    for block in blocks:
        kind = str(block.get("kind", ""))
        if int(block.get("factor", -1)) != 12:
            errors.append(f"RFDC_{kind.upper()}_FACTOR_MISMATCH")
        if int(block.get("nyquist_zone", -1)) != 1:
            errors.append(f"RFDC_{kind.upper()}_NYQUIST_ZONE_MISMATCH")
        expected_nco = -center_mhz if kind == "adc" else center_mhz
        if abs(float(block.get("mixer_frequency_mhz", float("inf"))) - expected_nco) > 1.0e-6:
            errors.append(f"RFDC_{kind.upper()}_NCO_MISMATCH")
    if require_valid:
        active_mask = int(rfdc.get("active_mask", 0)) & 0xFFFF
        current_valid = int(rfdc.get("current_valid_mask", 0)) & 0xFFFF
        if active_mask != 0xFFFF or current_valid != active_mask:
            errors.append("RFDC_VALID_MASK_INCOMPLETE")
    return {"ok": not errors, "errors": sorted(set(errors))}


def main() -> int:
    parser = argparse.ArgumentParser(description="current T510 release simultaneous board/host UDP gate")
    parser.add_argument("--sample-rate-msps", type=int, choices=(160, 320), required=True)
    parser.add_argument("--mode", choices=("time_only", "spec_only", "time_spec"), required=True)
    parser.add_argument("--center-mhz", type=float, default=200.0)
    parser.add_argument("--seconds", type=float, default=60.0)
    parser.add_argument("--board-id", type=int, default=1)
    parser.add_argument("--reference", choices=("onboard_tcxo", "external_10mhz"),
                        default="onboard_tcxo")
    parser.add_argument("--agent-base", default="http://192.168.100.117:8010")
    parser.add_argument("--metadata", type=Path,
                        default=Path(__file__).resolve().parents[1] / "config/t510/current_release.json")
    parser.add_argument("--receiver-ssh", default="astrolab@192.168.100.162")
    parser.add_argument("--receiver-base-url", default="http://127.0.0.1:8089")
    parser.add_argument("--receiver-interface", default="enp1s0f0np0")
    parser.add_argument(
        "--remote-validator",
        default="/opt/t510-time-rx/current/t510_host_validate.py",
    )
    parser.add_argument(
        "--remote-output",
        default="/home/astrolab/.cache/t510/latest/evidence/host_validation.json",
    )
    parser.add_argument(
        "--output",
        default="build/board/latest/evidence/board_host_gate.json",
    )
    args = parser.parse_args()
    if args.sample_rate_msps == 320 and args.mode == "time_spec":
        parser.error("current T510 release rejects 320 MS/s TIME_SPEC")

    base = args.agent_base.rstrip("/")
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    evidence: dict[str, Any] = {
        "classification": (
            f"T510_{args.sample_rate_msps}MSPS_{args.mode.upper()}_BOARD_HOST_IN_PROGRESS"
        ),
        "ok": False,
        "release": "latest",
        "sample_rate_msps": args.sample_rate_msps,
        "mode": args.mode,
        "center_mhz": args.center_mhz,
        "seconds": max(float(args.seconds), 0.1),
        "agent_base": base,
        "receiver": {
            "ssh": args.receiver_ssh,
            "base_url": args.receiver_base_url,
            "interface": args.receiver_interface,
        },
        "warnings": [],
        "errors": [],
    }
    started = False
    try:
        expected_core = str(json.loads(args.metadata.read_text(encoding="utf-8"))["core_version"])
        catalog = _result(_http_json(base + "/api/v2/bitstreams", timeout=30.0))
        entries = catalog.get("bitstreams", [])
        if len(entries) != 1:
            raise RuntimeError("current catalog must contain one bitstream")
        qualification = entries[0].get("mts_qualifications", {}).get(args.reference, {})
        if qualification.get("status") != "qualified":
            raise RuntimeError(f"reference {args.reference} is not qualified")
        expected_targets = {
            "adc": int(qualification["mts_adc_target_latency"]),
            "dac": int(qualification["mts_dac_target_latency"]),
        }
        idle = _result(_http_json(base + "/api/v2/status", timeout=30.0))
        profile = idle.get("profile", {})
        if int(profile.get("sample_rate_msps", 0)) != args.sample_rate_msps:
            raise RuntimeError(f"board sample-rate mismatch before START: {profile}")
        if str(profile.get("mode")) != args.mode:
            raise RuntimeError(f"board mode mismatch before START: {profile}")
        if abs(float(profile.get("center_mhz", 0.0)) - args.center_mhz) > 1.0e-6:
            raise RuntimeError(f"board center-frequency mismatch before START: {profile}")
        if str(idle.get("core_version", "")).lower() != expected_core.lower():
            raise RuntimeError(f"current T510 release core mismatch before START: {idle.get('core_version')}")
        idle_rfdc_health = _t510_rfdc_health(
            idle, require_valid=False, expected_core=expected_core)
        evidence["rfdc_health_idle"] = idle_rfdc_health
        if not idle_rfdc_health["ok"]:
            raise RuntimeError(f"current T510 release RFDC contract failed before START: {idle_rfdc_health['errors']}")
        idle_metadata_errors = _current_metadata_errors(
            idle, reference=args.reference, targets=expected_targets)
        if bool(idle.get("streaming")) or int(idle.get("board_id", -1)) != args.board_id:
            idle_metadata_errors.append("BOARD_NOT_STOPPED_OR_ID_MISMATCH")
        if int(idle.get("dac", {}).get("enable_mask", -1)) != 0:
            idle_metadata_errors.append("DAC_NOT_MUTED")
        if idle_metadata_errors:
            raise RuntimeError(f"current T510 release identity failed before START: {idle_metadata_errors}")
        evidence["board_idle"] = _compact_board(idle)

        prepare_command = [
            "python3",
            args.remote_validator,
            "--sample-rate-msps",
            str(args.sample_rate_msps),
            "--mode",
            args.mode,
            "--center-mhz",
            str(args.center_mhz),
            "--base-url",
            args.receiver_base_url,
            "--interface",
            args.receiver_interface,
            "--prepare-only",
        ]
        receiver_prepare = _remote_run(
            args.receiver_ssh, prepare_command,
            text=True, capture_output=True, check=False,
        )
        evidence["receiver_prepare"] = {
            "returncode": receiver_prepare.returncode,
            "stdout": receiver_prepare.stdout,
            "stderr": receiver_prepare.stderr,
        }
        if receiver_prepare.returncode != 0:
            raise RuntimeError(
                "receiver preparation failed before START: "
                f"{receiver_prepare.stderr or receiver_prepare.stdout}"
            )

        receiver_prestart = _remote_receiver_state(
            args.receiver_ssh, args.receiver_base_url
        )
        board_prestart = _result(_http_json(base + "/api/v2/status", timeout=30.0))
        _result(
            _http_json(
                base + "/api/v2/start",
                body={"expected_board_id": args.board_id},
                timeout=30.0,
            )
        )
        started = True
        time.sleep(START_WARMUP_SECONDS)
        board_before = _result(_http_json(base + "/api/v2/status", timeout=30.0))
        receiver_warm = _remote_receiver_state(
            args.receiver_ssh, args.receiver_base_url
        )
        startup_board_before = board_prestart.get("counters", {})
        startup_board_after = board_before.get("counters", {})
        startup_receiver_before = receiver_prestart.get("stats", {})
        startup_receiver_after = receiver_warm.get("stats", {})
        startup_boundary = _startup_receiver_boundary(
            startup_receiver_after, startup_receiver_before
        )
        evidence["startup_warmup"] = {
            "seconds": START_WARMUP_SECONDS,
            "board_counter_delta": {
                key: _counter_delta(startup_board_after, startup_board_before, key)
                for key in sorted(set(startup_board_before) | set(startup_board_after))
            },
            **startup_boundary,
            "board_transient_excluded_from_formal_window": True,
        }
        evidence["board_before"] = _compact_board(board_before)
        evidence["rfdc_health_before"] = _t510_rfdc_health(
            board_before, require_valid=True, expected_core=expected_core
        )

        command = [
            "python3",
            args.remote_validator,
            "--sample-rate-msps",
            str(args.sample_rate_msps),
            "--mode",
            args.mode,
            "--center-mhz",
            str(args.center_mhz),
            "--base-url",
            args.receiver_base_url,
            "--interface",
            args.receiver_interface,
            "--seconds",
            str(max(float(args.seconds), 0.1)),
            "--output",
            args.remote_output,
            "--skip-config",
        ]
        host_process = _remote_run(
            args.receiver_ssh, command,
            text=True, capture_output=True, check=False,
        )
        evidence["host_validator"] = {
            "returncode": host_process.returncode,
            "stderr": host_process.stderr,
        }
        host_json = _remote_run(
            args.receiver_ssh,
            ["cat", args.remote_output],
            text=True,
            capture_output=True,
            check=True,
        )
        host = json.loads(host_json.stdout)
        host_output = output.with_name(output.stem + "_host.json")
        host_output.write_text(
            json.dumps(host, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        host_before = host.get("stats_before", {})
        host_after = host.get("stats_after", {})
        evidence["host_evidence"] = str(host_output)
        evidence["host"] = {
            key: host.get(key)
            for key in (
                "classification",
                "ok",
                "errors",
                "warnings",
                "required",
                "rates",
                "net_delta",
                "ethtool_delta",
            )
        }
        evidence["host"]["counter_delta"] = {
            key: _counter_delta(host_after, host_before, key)
            for key in (
                "time_packets",
                "spec_packets",
                "parse_errors",
                "kernel_drops",
                "ring_drops",
                "worker_ring_drops",
                "app_drops",
                "seq_gaps",
                "frame_gaps",
                "sample0_gaps",
                "spec_seq_gaps",
                "spec_frame_gaps",
            )
        }

        board_after = _result(_http_json(base + "/api/v2/status", timeout=30.0))
        telemetry = _incremental_telemetry(base, board_before)
        evidence["incremental_power_thermal_telemetry"] = telemetry
        evidence["board_after"] = _compact_board(board_after)
        evidence["rfdc_health_after"] = _t510_rfdc_health(
            board_after, require_valid=True, expected_core=expected_core
        )
        before_counters = board_before.get("counters", {})
        after_counters = board_after.get("counters", {})
        board_delta = {
            key: _counter_delta(after_counters, before_counters, key)
            for key in sorted(set(before_counters) | set(after_counters))
        }
        evidence["board_counter_delta"] = board_delta
        before_channelizer = board_before.get("channelizer", {})
        after_channelizer = board_after.get("channelizer", {})
        channelizer_delta = {
            key: _counter_delta(after_channelizer, before_channelizer, key)
            for key in (
                "frame_count",
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
        }
        evidence["channelizer_counter_delta"] = channelizer_delta

        errors: list[str] = []
        warnings: list[str] = []
        if startup_boundary["receiver_boundary_events"]:
            warnings.append(
                "START_WARMUP_BOUNDARY_EVENTS_EXCLUDED="
                + ", ".join(startup_boundary["receiver_boundary_events"])
            )
        if board_before.get('digital_scaling') != board_after.get('digital_scaling'):
            errors.append('DIGITAL_SCALING_CHANGED_DURING_GATE')
        errors.extend(telemetry["errors"])
        if not bool(board_before.get("streaming")) or not bool(board_after.get("streaming")):
            errors.append("BOARD_NOT_STREAMING")
        if not bool(board_after.get("pipeline", {}).get("stream_accepting")):
            errors.append("BOARD_PIPELINE_NOT_ACCEPTING")
        for label, snapshot in (("before", board_before), ("after", board_after)):
            if str(snapshot.get("core_version", "")).lower() != expected_core.lower():
                errors.append(f"BOARD_CORE_VERSION_MISMATCH_{label.upper()}")
            health = evidence[f"rfdc_health_{label}"]
            errors.extend(f"{error}_{label.upper()}" for error in health["errors"])
            errors.extend(
                f"{error}_{label.upper()}"
                for error in _current_metadata_errors(
                    snapshot, reference=args.reference, targets=expected_targets)
            )
        qsfp_health = {
            "before": _qsfp_physical_health(board_before.get("qsfp", {})),
            "after": _qsfp_physical_health(board_after.get("qsfp", {})),
        }
        evidence["qsfp_health"] = qsfp_health
        if not bool(qsfp_health["before"]["physical_healthy"]):
            errors.append("BOARD_QSFP_PHYSICAL_HEALTH_BAD_BEFORE")
        if not bool(qsfp_health["after"]["physical_healthy"]):
            errors.append("BOARD_QSFP_PHYSICAL_HEALTH_BAD_AFTER")
        for label in ("before", "after"):
            health = qsfp_health[label]
            if bool(health["physical_healthy"]) and not bool(health["link_up_sample"]):
                warnings.append(
                    f"BOARD_QSFP_LINK_SAMPLE_LOW_DURING_BACKPRESSURE_{label.upper()}"
                )
        halfband = board_after.get("halfband", {})
        if str(halfband.get("coefficient_id", "")).lower() != "0xaa160055":
            errors.append("BOARD_HALFBAND_COEFFICIENT_ID_MISMATCH")
        if int(halfband.get("taps", 0) or 0) != 55:
            errors.append("BOARD_HALFBAND_TAP_COUNT_MISMATCH")
        if args.sample_rate_msps == 160:
            if not bool(halfband.get("active")):
                errors.append("BOARD_HALFBAND_NOT_ACTIVE_AT_160MSPS")
            if not bool(halfband.get("primed")):
                errors.append("BOARD_HALFBAND_NOT_PRIMED_AT_160MSPS")
        elif bool(halfband.get("active")):
            errors.append("BOARD_HALFBAND_ACTIVE_AT_320MSPS")
        needs_spec = args.mode in ("spec_only", "time_spec")
        if needs_spec:
            if int(after_channelizer.get("nchan", 0) or 0) != 4096:
                errors.append("BOARD_PFB_NCHAN_NOT_4096")
            if int(after_channelizer.get("taps", 0) or 0) != 8:
                errors.append("BOARD_PFB_TAPS_NOT_8")
            if int(after_channelizer.get("packet_chan_count", 0) or 0) != 256:
                errors.append("BOARD_SPEC_PACKET_CHAN_COUNT_NOT_256")
            if int(after_channelizer.get("packet_time_count", 0) or 0) != 1:
                errors.append("BOARD_SPEC_PACKET_TIME_COUNT_NOT_1")
            if channelizer_delta.get("frame_count", 0) <= 0:
                errors.append("BOARD_PFB_FRAME_COUNT_NOT_ADVANCING")
            for key in (
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
            ):
                if int(before_channelizer.get(key, 0) or 0) != 0:
                    errors.append(f"BOARD_NONZERO_INITIAL_PFB_{key.upper()}")
                if channelizer_delta.get(key, 0) != 0:
                    errors.append(f"BOARD_NONZERO_PFB_{key.upper()}_DELTA")
        active_packet_key = "time_packets" if args.mode in ("time_only", "time_spec") else "spec_packets"
        if board_delta.get(active_packet_key, 0) <= 0:
            errors.append(f"BOARD_{active_packet_key.upper()}_NOT_ADVANCING")
        if args.mode == "time_only" and board_delta.get("spec_packets", 0) != 0:
            errors.append("BOARD_SPEC_PACKETS_IN_TIME_ONLY")
        if args.mode == "spec_only" and board_delta.get("time_packets", 0) != 0:
            errors.append("BOARD_TIME_PACKETS_IN_SPEC_ONLY")
        for key in (
            "time_dropped",
            "spec_dropped",
            "tx_frames_dropped",
            "tx_route_error",
            "tx_route_miss",
            "rfdc_dropped",
            "science_dropped_beats",
        ):
            if board_delta.get(key, 0) != 0:
                errors.append(f"BOARD_NONZERO_{key.upper()}_DELTA")
        if host_process.returncode != 0 or not bool(host.get("ok")):
            errors.append("HOST_GATE_FAILED")
        evidence["warnings"] = warnings
        evidence["errors"] = errors
        evidence["ok"] = not errors
        evidence["classification"] = (
            f"T510_{args.sample_rate_msps}MSPS_{args.mode.upper()}_BOARD_HOST_"
            f"{'PASS' if evidence['ok'] else 'FAIL'}"
        )
    except Exception as exc:
        evidence["errors"].append(f"{type(exc).__name__}: {exc}")
    finally:
        if started:
            try:
                stop = _safe_stop(
                    base, reason="t510_board_host_gate_complete",
                    expected_board_id=args.board_id,
                    sample_rate_msps=args.sample_rate_msps, mode=args.mode,
                    center_mhz=args.center_mhz,
                    reference=args.reference, targets=expected_targets,
                    expected_core=expected_core,
                )
                evidence["stop"] = stop
            except Exception as exc:
                evidence["errors"].append(f"STOP_FAILED: {type(exc).__name__}: {exc}")
                evidence["ok"] = False
        if not evidence["ok"]:
            evidence["classification"] = (
                f"T510_{args.sample_rate_msps}MSPS_{args.mode.upper()}_BOARD_HOST_FAIL"
            )
        output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if evidence["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
