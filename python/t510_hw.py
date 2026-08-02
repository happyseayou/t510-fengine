#!/usr/bin/env python3
"""One-shot PYNQ bridge for the stateless Stage 33 Rust Board Agent.

The request is one JSON object on stdin. Exactly one JSON object is emitted on
stdout; incidental PYNQ output is redirected to stderr.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import traceback
from typing import Any, Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from python.t510_control import (
        DacChannelConfig,
        FlowDestination,
        RfdcCenterConflict,
        FEngineConfig,
        FEngineController,
    )
else:
    # Importing t510_control imports PYNQ. Keep that import behind the PL-state guard:
    # on a cold boot even importing PYNQ can wait on platform initialization.
    DacChannelConfig = None
    FlowDestination = None
    RfdcCenterConflict = None
    FEngineConfig = None
    FEngineController = None


EXIT_INVALID = 2
EXIT_STATE_CONFLICT = 3
EXIT_HARDWARE_UNAVAILABLE = 4
EXIT_BITSTREAM_PROOF = 5
EXIT_INTERNAL = 6

FPGA_MANAGER_STATE_PATH = Path("/sys/class/fpga_manager/fpga0/state")
MTS_STATE_PATH = Path("/run/t510-mts.json")
REFERENCE_WATCHDOG_STATE_PATH = Path("/run/t510-ref-watchdog.json")
CONFIGURE_LOCK_PATH = Path("/run/t510-configure.lock")
REFERENCE_WATCHDOG_MAX_AGE_MS = 1_500


class HelperError(RuntimeError):
    def __init__(self, code: str, message: str, *, exit_code: int, details: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.exit_code = int(exit_code)
        self.details = details


@contextlib.contextmanager
def _configure_hardware_guard(enabled: bool):
    """Keep the resident watchdog away from PL/SPI while CONFIGURE owns them."""

    if not enabled:
        yield
        return
    descriptor = os.open(
        CONFIGURE_LOCK_PATH,
        os.O_CREAT | os.O_RDWR | os.O_CLOEXEC,
        0o644,
    )
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _load_control() -> None:
    global DacChannelConfig, FlowDestination, RfdcCenterConflict, FEngineConfig, FEngineController

    if all(
        value is not None
        for value in (
            DacChannelConfig,
            FlowDestination,
            RfdcCenterConflict,
            FEngineConfig,
            FEngineController,
        )
    ):
        return

    from python import t510_control

    if DacChannelConfig is None:
        DacChannelConfig = t510_control.DacChannelConfig
    if FlowDestination is None:
        FlowDestination = t510_control.FlowDestination
    if RfdcCenterConflict is None:
        RfdcCenterConflict = t510_control.RfdcCenterConflict
    if FEngineConfig is None:
        FEngineConfig = t510_control.FEngineConfig
    if FEngineController is None:
        FEngineController = t510_control.FEngineController


def _read_request() -> dict[str, Any]:
    try:
        value = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        raise HelperError(
            "INVALID_HELPER_REQUEST",
            f"stdin is not valid JSON: {exc}",
            exit_code=EXIT_INVALID,
        ) from exc
    if not isinstance(value, dict):
        raise HelperError(
            "INVALID_HELPER_REQUEST",
            "stdin JSON must be an object",
            exit_code=EXIT_INVALID,
        )
    return value


def _bitstream(request: dict[str, Any]) -> dict[str, Any]:
    value = request.get("bitstream")
    if not isinstance(value, dict):
        raise HelperError(
            "INVALID_HELPER_REQUEST",
            "bitstream proof is required",
            exit_code=EXIT_INVALID,
        )
    required = ("id", "path", "sha256", "core_version")
    missing = [key for key in required if key not in value]
    if missing:
        raise HelperError(
            "INVALID_HELPER_REQUEST",
            f"bitstream proof is missing: {', '.join(missing)}",
            exit_code=EXIT_INVALID,
        )
    return value


def _body(request: dict[str, Any]) -> dict[str, Any]:
    value = request.get("request", {})
    if not isinstance(value, dict):
        raise HelperError(
            "INVALID_HELPER_REQUEST",
            "request field must be an object",
            exit_code=EXIT_INVALID,
        )
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha1(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_fpga_manager_state() -> str:
    try:
        return FPGA_MANAGER_STATE_PATH.read_text(encoding="ascii").strip().lower()
    except OSError as exc:
        raise HelperError(
            "FPGA_STATE_UNAVAILABLE",
            "cannot read the FPGA manager state without accessing PL MMIO",
            exit_code=EXIT_HARDWARE_UNAVAILABLE,
            details={
                "path": str(FPGA_MANAGER_STATE_PATH),
                "reason": str(exc),
            },
        ) from exc


def _read_pynq_global_pl_state() -> dict[str, Any] | None:
    try:
        from pynq.pl_server import global_state as pynq_global_state
    except ImportError as exc:
        raise HelperError(
            "PYNQ_STATE_UNAVAILABLE",
            "cannot import the PYNQ global PL state reader",
            exit_code=EXIT_HARDWARE_UNAVAILABLE,
            details={"reason": str(exc)},
        ) from exc

    state_path = Path(pynq_global_state.STATE_DIR) / "global_pl_state.json"
    if not state_path.is_file():
        return None
    try:
        value = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HelperError(
            "PYNQ_STATE_UNAVAILABLE",
            "cannot read the PYNQ global PL state safely",
            exit_code=EXIT_HARDWARE_UNAVAILABLE,
            details={"path": str(state_path), "reason": str(exc)},
        ) from exc
    if not isinstance(value, dict):
        raise HelperError(
            "PYNQ_STATE_UNAVAILABLE",
            "the PYNQ global PL state is not a JSON object",
            exit_code=EXIT_HARDWARE_UNAVAILABLE,
            details={"path": str(state_path)},
        )
    return value


def _pynq_global_state_path() -> Path:
    try:
        from pynq.pl_server import global_state as pynq_global_state
    except ImportError as exc:
        raise HelperError(
            "PYNQ_STATE_UNAVAILABLE",
            "cannot import the PYNQ global PL state writer",
            exit_code=EXIT_HARDWARE_UNAVAILABLE,
            details={"reason": str(exc)},
        ) from exc
    return Path(pynq_global_state.STATE_DIR) / "global_pl_state.json"


def _record_active_bitstream_state(path: Path) -> None:
    """Record a bitstream only after the hardware configure transaction passes.

    The T510 image uses PYNQ's XRT device backend.  That backend downloads the
    bitstream but, unlike the embedded-device backend, does not update
    ``global_pl_state.json``.  Preserve PYNQ's other state fields while
    recording an immutable resolved path and the bytes that were just
    downloaded.  Later one-shot helpers still independently hash the catalog
    file before allowing MMIO.
    """
    state_path = _pynq_global_state_path()
    try:
        value = json.loads(state_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        value = {}
    except (OSError, json.JSONDecodeError) as exc:
        raise HelperError(
            "PYNQ_STATE_UNAVAILABLE",
            "cannot update the PYNQ global PL state after configure",
            exit_code=EXIT_HARDWARE_UNAVAILABLE,
            details={"path": str(state_path), "reason": str(exc)},
        ) from exc
    if not isinstance(value, dict):
        raise HelperError(
            "PYNQ_STATE_UNAVAILABLE",
            "the PYNQ global PL state is not a JSON object",
            exit_code=EXIT_HARDWARE_UNAVAILABLE,
            details={"path": str(state_path)},
        )

    try:
        resolved = path.resolve(strict=True)
        active_sha1 = _sha1(resolved)
    except OSError as exc:
        raise HelperError(
            "BITSTREAM_PROOF_FAILED",
            "cannot hash the downloaded bitstream while recording PYNQ state",
            exit_code=EXIT_BITSTREAM_PROOF,
            details={"path": str(path), "reason": str(exc)},
        ) from exc

    value["bitfile_name"] = str(resolved)
    value["bitfile_hash"] = active_sha1
    value["timestamp"] = time.strftime("%Y/%m/%d %H:%M:%S %z")
    value.setdefault("active_name", "T510")
    value.setdefault("shutdown_ips", {})
    value.setdefault("psddr", {})

    temporary = state_path.with_name(f".{state_path.name}.tmp")
    try:
        temporary.write_text(
            json.dumps(value, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        temporary.replace(state_path)
    except OSError as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise HelperError(
            "PYNQ_STATE_UNAVAILABLE",
            "cannot commit the PYNQ global PL state after configure",
            exit_code=EXIT_HARDWARE_UNAVAILABLE,
            details={"path": str(state_path), "reason": str(exc)},
        ) from exc


def _require_active_bitstream(bitstream: dict[str, Any], path: Path) -> None:
    state = _read_fpga_manager_state()
    if state != "operating":
        raise HelperError(
            "PL_NOT_CONFIGURED",
            "the PL is not configured; call POST /api/v2/configure before any hardware API",
            exit_code=EXIT_STATE_CONFLICT,
            details={
                "fpga_manager_state": state,
                "required_action": "configure",
            },
        )

    active = _read_pynq_global_pl_state()
    if active is None:
        raise HelperError(
            "PL_NOT_CONFIGURED",
            "PYNQ has no active bitstream for this boot; call POST /api/v2/configure",
            exit_code=EXIT_STATE_CONFLICT,
            details={
                "fpga_manager_state": state,
                "required_action": "configure",
            },
        )

    expected_path = path.resolve()
    active_name = str(active.get("bitfile_name", "")).strip()
    try:
        active_path = Path(active_name).resolve() if active_name else None
    except OSError:
        active_path = None
    stored_hash = str(active.get("bitfile_hash", "")).strip().lower()
    actual_hash = _sha1(expected_path)
    # PYNQ may retain the path used by an earlier download when the same
    # immutable bitstream is downloaded through a release-directory alias.
    # The active content hash is the hardware identity; the path is diagnostic
    # provenance and must not force a redundant configure when the bytes match.
    if stored_hash != actual_hash:
        raise HelperError(
            "ACTIVE_BITSTREAM_MISMATCH",
            "the active PYNQ bitstream does not match the Agent catalog; configure is required",
            exit_code=EXIT_STATE_CONFLICT,
            details={
                "bitstream_id": bitstream["id"],
                "expected_path": str(expected_path),
                "active_path": str(active_path) if active_path is not None else active_name,
                "expected_sha1": actual_hash,
                "active_sha1": stored_hash,
                "required_action": "configure",
            },
        )


def _verify_bitstream(value: dict[str, Any], *, hash_file: bool) -> Path:
    path = Path(str(value["path"]))
    if not path.is_absolute():
        raise HelperError(
            "BITSTREAM_PROOF_FAILED",
            "catalog bitstream path must be absolute",
            exit_code=EXIT_BITSTREAM_PROOF,
        )
    if not path.is_file():
        raise HelperError(
            "HARDWARE_UNAVAILABLE",
            f"bitstream file is unavailable: {path}",
            exit_code=EXIT_HARDWARE_UNAVAILABLE,
        )
    if hash_file:
        actual = _sha256(path)
        expected = str(value["sha256"]).lower()
        if actual != expected:
            raise HelperError(
                "BITSTREAM_PROOF_FAILED",
                "bitstream SHA256 does not match the catalog proof",
                exit_code=EXIT_BITSTREAM_PROOF,
                details={"expected": expected, "actual": actual},
            )
    return path


def _controller(request: dict[str, Any], *, download: bool = False) -> FEngineController:
    bitstream = _bitstream(request)
    path = _verify_bitstream(bitstream, hash_file=download)
    if not download:
        _require_active_bitstream(bitstream, path)
    _load_control()
    assert FEngineController is not None
    controller = FEngineController(path)
    controller.connect(download=download)
    expected = int(str(bitstream["core_version"]), 0)
    status = controller.require_core().read_status()
    actual = int(status.get("core_version", 0))
    if actual != expected:
        raise HelperError(
            "CORE_VERSION_MISMATCH",
            f"expected core 0x{expected:08x}, read 0x{actual:08x}",
            exit_code=EXIT_STATE_CONFLICT,
        )
    return controller


def _expected_board(controller: FEngineController, body: dict[str, Any]) -> int:
    expected = int(body["expected_board_id"])
    actual = int(controller.require_core().read_status().get("board_id", -1))
    if actual != expected:
        raise HelperError(
            "BOARD_ID_MISMATCH",
            f"expected board_id {expected}, hardware reports {actual}",
            exit_code=EXIT_STATE_CONFLICT,
            details={"expected_board_id": expected, "actual_board_id": actual},
        )
    return actual


def _profile_name(status: dict[str, Any]) -> dict[str, Any]:
    sample_rate_code = int(status.get("science_sample_rate_mode", 0))
    output_code = int(status.get("science_output_mode", 0))
    output_name = str(status.get("science_output_mode_name", "")).strip().lower()
    return {
        "sample_rate_msps": int(
            status.get("science_sample_rate_msps", {1: 160, 2: 320}.get(sample_rate_code, 0))
        )
        or None,
        "mode": {
            "time_only": "time_only",
            "spec_only": "spec_only",
            "time_spec": "time_spec",
        }.get(output_name, {1: "time_only", 2: "spec_only", 3: "time_spec"}.get(output_code, "unknown")),
        "sample_rate_code": sample_rate_code,
        "output_mode_code": output_code,
    }


def _mts_summary(core: Any, *, core_version: str) -> dict[str, Any]:
    sync = getattr(core, "rfdc_sync_status", {})
    mts = sync.get("mts", {}) if isinstance(sync, dict) else {}

    def one(kind: str) -> dict[str, Any]:
        config = mts.get(f"{kind}_config", {}) if isinstance(mts, dict) else {}
        if not isinstance(config, dict):
            config = {}
        tiles = int(config.get("tiles", 0))
        latency = [int(value) for value in config.get("latency", [])]
        offset = [int(value) for value in config.get("offset", [])]
        active_latency = [
            latency[tile]
            for tile in range(min(4, len(latency)))
            if tiles & (1 << tile)
        ]
        return {
            "target_latency": (
                int(config["target_latency"]) if "target_latency" in config else None
            ),
            "measured_latency": latency or None,
            "active_measured_latency": active_latency or None,
            "offset": offset or None,
            "tiles": tiles or None,
            "ref_tile": int(config["ref_tile"]) if "ref_tile" in config else None,
        }

    result = {
        "captured_at_unix_ms": time.time_ns() // 1_000_000,
        "core_version": core_version,
        "available": bool(mts),
        "adc": one("adc"),
        "dac": one("dac"),
    }
    return result


def _persist_mts_summary(summary: dict[str, Any]) -> None:
    temporary = MTS_STATE_PATH.with_suffix(".tmp")
    try:
        temporary.write_text(
            json.dumps(summary, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        temporary.replace(MTS_STATE_PATH)
    except OSError:
        # The configure response still carries the live result.  A read-only
        # /run only makes later one-shot status calls report unavailable.
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _load_mts_summary(*, core_version: str) -> dict[str, Any] | None:
    try:
        value = json.loads(MTS_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict) or value.get("core_version") != core_version:
        return None
    return value


def _reference_watchdog_status() -> dict[str, Any]:
    captured_at = time.time_ns() // 1_000_000
    try:
        value = json.loads(
            REFERENCE_WATCHDOG_STATE_PATH.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "available": False,
            "healthy": False,
            "stale": True,
            "error": f"{type(exc).__name__}: {exc}",
            "path": str(REFERENCE_WATCHDOG_STATE_PATH),
        }
    if not isinstance(value, dict):
        return {
            "available": False,
            "healthy": False,
            "stale": True,
            "error": "watchdog state is not a JSON object",
            "path": str(REFERENCE_WATCHDOG_STATE_PATH),
        }
    updated_at = int(value.get("updated_at_unix_ms", 0))
    age_ms = max(captured_at - updated_at, 0) if updated_at > 0 else None
    stale = age_ms is None or age_ms > REFERENCE_WATCHDOG_MAX_AGE_MS
    return {
        **value,
        "available": True,
        "age_ms": age_ms,
        "stale": stale,
        "healthy": bool(value.get("healthy", False)) and not stale,
        "path": str(REFERENCE_WATCHDOG_STATE_PATH),
    }


def _require_reference_watchdog_ready(bitstream: dict[str, Any]) -> dict[str, Any]:
    watchdog = _reference_watchdog_status()
    expected_sha1 = _sha1(Path(str(bitstream["path"])).resolve())
    errors: list[str] = []
    if not bool(watchdog.get("available", False)):
        errors.append("STATE_UNAVAILABLE")
    if bool(watchdog.get("stale", True)):
        errors.append("STATE_STALE")
    if not bool(watchdog.get("healthy", False)):
        errors.append("NOT_HEALTHY")
    if bool(watchdog.get("fault_latched", False)):
        errors.append("FAULT_LATCHED")
    lock_status = (
        dict(watchdog["lock_status"])
        if isinstance(watchdog.get("lock_status"), dict)
        else {}
    )
    if int(lock_status.get("pll1_lock", 0)) != 1:
        errors.append("PLL1_NOT_LOCKED")
    if int(lock_status.get("pll2_lock", 0)) != 1:
        errors.append("PLL2_NOT_LOCKED")
    if str(watchdog.get("active_bitstream_sha1", "")).lower() != expected_sha1:
        errors.append("BITSTREAM_IDENTITY_MISMATCH")
    if errors:
        raise HelperError(
            "REFERENCE_WATCHDOG_NOT_READY",
            "the resident LMK reference watchdog is not ready; START/ARM is blocked",
            exit_code=EXIT_STATE_CONFLICT,
            details={
                "errors": errors,
                "watchdog": watchdog,
                "required_action": (
                    "restore external 10 MHz and run a fresh CONFIGURE/MTS"
                ),
            },
        )
    return watchdog


def _status_snapshot(controller: FEngineController) -> dict[str, Any]:
    core = controller.require_core()
    status = core.read_status()
    core_version = f"0x{int(status.get('core_version', 0)):08x}"
    live_mts = _mts_summary(core, core_version=core_version)
    mts = (
        live_mts
        if live_mts.get("available")
        else (_load_mts_summary(core_version=core_version) or live_mts)
    )
    try:
        clock = core.read_lmk_status(include_registers=False)
    except Exception as exc:
        clock = {
            "profile_id": "unavailable",
            "sysref_mode": "unavailable",
            "configured": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    scheduled_sync = (
        core.read_scheduled_sync_status()
        if hasattr(core, "read_scheduled_sync_status")
        else None
    )
    mixers = core.read_rfdc_mixer_frequencies()
    try:
        rfdc_contract = (
            core.read_rfdc_contract(require=False)
            if hasattr(core, "read_rfdc_contract")
            else {"ok": False, "errors": ["Stage 33 RFDC contract readback unavailable"]}
        )
    except Exception as exc:
        rfdc_contract = {
            "ok": False,
            "errors": [f"{type(exc).__name__}: {exc}"],
        }
    dac_centers = [
        float(item["frequency_mhz"])
        for item in mixers.get("mixers", [])
        if item.get("kind") == "dac" and float(item.get("frequency_mhz", 0.0)) > 0.0
    ]
    center_mhz = None
    if dac_centers and max(dac_centers) - min(dac_centers) < 1e-6:
        center_mhz = sum(dac_centers) / len(dac_centers)
    tx_flags = int(status.get("tx_link_status_flags", 0))
    mux_locked = bool(status.get("tx_cmac_source_mux_locked", 0))
    mux_source = int(status.get("tx_cmac_mux_selected_source", 0))
    time_fifo_full = bool(status.get("tx_time_live_bridge_fifo_full", 0))
    downstream_ready = bool(status.get("rfdc_downstream_ready", 0))
    streaming = bool(status.get("streaming", 0))
    stale_science_frame = (
        not streaming and mux_locked and mux_source in (1, 2)
    )
    return {
        "captured_at_unix_ms": time.time_ns() // 1_000_000,
        "core_version": core_version,
        "board_id": int(status.get("board_id", 0)),
        "streaming": streaming,
        "error_flags": int(status.get("error_flags", 0)),
        "profile": {
            **_profile_name(status),
            "center_mhz": center_mhz,
            "aa100_active": bool(status.get("science_antialias_100m_active", 0)),
            "display_name": (
                "160 MS/s（约128 MHz可用科学带宽）"
                if int(status.get("science_sample_rate_msps", 160)) == 160
                else "320 MS/s（约256 MHz可用科学带宽）"
            ),
        },
        "clock": {
            "profile_id": clock.get("profile_id"),
            "sysref_mode": clock.get("sysref_mode"),
            "selected_ref": clock.get("selected_ref"),
            "lmk_clkin": clock.get("lmk_clkin"),
            "pll1_lock": int(clock.get("pll1_lock", 0)),
            "pll2_lock": int(clock.get("pll2_lock", 0)),
            "configured": bool(clock.get("configured", False)),
            "errors": clock.get("errors", []),
        },
        "rfdc": {
            "adc_analog_sample_rate_hz": int(
                status.get("rfdc_adc_analog_sample_rate_hz", 3_840_000_000)
            ),
            "dac_analog_sample_rate_hz": int(
                status.get("rfdc_dac_analog_sample_rate_hz", 3_840_000_000)
            ),
            "complex_sample_rate_hz": int(
                status.get("rfdc_complex_sample_rate_hz", 320_000_000)
            ),
            "adc_decimation": int(status.get("rfdc_adc_decimation", 12)),
            "dac_interpolation": int(status.get("rfdc_dac_interpolation", 12)),
            "adc_axis_rate_hz": int(status.get("rfdc_adc_axis_rate_hz", 80_000_000)),
            "dac_axis_rate_hz": int(status.get("rfdc_dac_axis_rate_hz", 80_000_000)),
            "active_mask": int(status.get("rfdc_active_mask", 0)),
            "current_valid_mask": int(status.get("rfdc_current_valid_mask", 0)),
            "seen_valid_mask": int(status.get("rfdc_seen_valid_mask", 0)),
            "status_flags": int(status.get("rfdc_status_flags", 0)),
            "readback": rfdc_contract,
        },
        "mts": mts,
        "halfband": {
            "active": bool(status.get("science_antialias_100m_active", 0)),
            "primed": bool(status.get("science_antialias_100m_primed", 0)),
            "taps": int(status.get("science_antialias_taps", 0)),
            "coefficient_id": f"0x{int(status.get('science_antialias_coeff_version', 0)):08x}",
        },
        "timing": {
            "pps_count": int(status.get("pps_count", 0)),
            "pps_input_high": bool(status.get("pps_status_input_high", 0)),
            "pps_recent": bool(
                status.get("pps_recent", 0) or status.get("pps_status_count_nonzero", 0)
            ),
            "reference_locked": bool(status.get("ref_status_locked", 0)),
            "configured_sync_mode": int(status.get("configured_sync_mode", 0)),
            "configured_clock_ref": int(status.get("configured_clock_ref", 0)),
        },
        "qsfp": {
            "link_up": bool(status.get("tx_qsfp_link_up", 0) or tx_flags & 0x1),
            "module_present": bool(
                status.get("tx_qsfp_module_present", 0) or (tx_flags >> 12) & 0x1
            ),
            "raw_flags": tx_flags,
        },
        "counters": {
            "time_packets": int(status.get("time_packet_count", 0)),
            "time_dropped": int(status.get("time_dropped_count", 0)),
            "spec_packets": int(status.get("spec_packet_count", 0)),
            "spec_dropped": int(status.get("spec_dropped_count", 0)),
            "tx_frames_built": int(status.get("tx_frame_built_count", 0)),
            "tx_frames_sent": int(status.get("tx_frame_sent_count", 0)),
            "tx_frames_dropped": int(status.get("tx_frame_dropped_count", 0)),
            "tx_route_miss": int(status.get("tx_route_miss_count", 0)),
            "tx_route_error": int(status.get("tx_route_error_count", 0)),
            "rfdc_dropped": int(status.get("rfdc_dropped_count", 0)),
            "science_dropped_beats": int(status.get("science_dropped_beat_count", 0)),
        },
        "pipeline": {
            "rfdc_downstream_ready": downstream_ready,
            "cmac_mux_locked": mux_locked,
            "cmac_mux_selected_source": mux_source,
            "cmac_mux_stale_science_frame": stale_science_frame,
            "time_fifo_full": time_fifo_full,
            "time_fifo_empty": bool(status.get("tx_time_live_bridge_fifo_empty", 0)),
            "pfb_input_fifo_level": int(status.get("pfb_input_fifo_level", 0)),
            "flush_clean": bool(
                downstream_ready and not time_fifo_full and not stale_science_frame
            ),
            "stream_accepting": bool(
                streaming and downstream_ready and not time_fifo_full
            ),
            "first_time_seen": bool(
                scheduled_sync and scheduled_sync.get("first_time_seen", False)
            ),
            "first_spec_seen": bool(
                scheduled_sync and scheduled_sync.get("first_spec_seen", False)
            ),
        },
        "channelizer": {
            "nchan": int(status.get("pfb_nchan", 0)),
            "taps": int(status.get("pfb_taps", 0)),
            "packet_chan_count": int(status.get("pfb_chan_count", 0)),
            "packet_time_count": int(status.get("pfb_time_count", 0)),
            "frame_count": int(status.get("pfb_frame_count", 0)),
            "overflow_count": int(status.get("pfb_overflow_count", 0)),
            "data_halt_count": int(status.get("pfb_data_halt_count", 0)),
            "xfft_event_count": int(status.get("pfb_xfft_event_count", 0)),
            "tile_overflow_count": int(status.get("pfb_tile_overflow_count", 0)),
            "xfft_tlast_unexpected_count": int(
                status.get("pfb_xfft_tlast_unexpected_count", 0)
            ),
            "xfft_tlast_missing_count": int(
                status.get("pfb_xfft_tlast_missing_count", 0)
            ),
            "xfft_fft_overflow_count": int(
                status.get("pfb_xfft_fft_overflow_count", 0)
            ),
            "xfft_data_out_halt_count": int(
                status.get("pfb_xfft_data_out_halt_count", 0)
            ),
            "xfft_status_halt_count": int(
                status.get("pfb_xfft_status_halt_count", 0)
            ),
            "capture_backpressure_count": int(
                status.get("pfb_capture_backpressure_count", 0)
            ),
            "frame_sample0_overflow_count": int(
                status.get("pfb_frame_sample0_overflow_count", 0)
            ),
            "peak_chan": int(status.get("pfb_peak_chan", 0)),
            "peak_power": int(status.get("pfb_peak_power", 0)),
            "coefficient_id": f"0x{int(status.get('pfb_coeff_active_id', 0)):08x}",
            "coefficient_error_count": int(status.get("pfb_coeff_error_count", 0)),
        },
        "sample0": {
            "time": int(status.get("time_sample0", 0)),
            "rfdc": int(status.get("rfdc_sample_count", 0)),
        },
        "error_flags": int(status.get("error_flags", 0)),
        "scheduled_sync": scheduled_sync,
        "reference_watchdog": _reference_watchdog_status(),
        "dac": controller.read_dac_channels(center_mhz=center_mhz),
    }


def _configure(request: dict[str, Any]) -> dict[str, Any]:
    body = _body(request)
    bitstream = _bitstream(request)
    path = _verify_bitstream(bitstream, hash_file=True)
    _load_control()
    assert DacChannelConfig is not None
    assert FlowDestination is not None
    assert FEngineConfig is not None
    assert FEngineController is not None
    endpoints = sorted(body["endpoints"], key=lambda item: int(item["endpoint_id"]))
    time_destinations = tuple(
        FlowDestination(
            enabled=bool(item["enabled"]),
            ip=item["destination_ip"],
            mac=item["destination_mac"],
            destination_port=int(item["destination_port"]),
            source_port=int(item["source_port"]),
        )
        for item in endpoints[:8]
    )
    spec_destinations = tuple(
        FlowDestination(
            enabled=bool(item["enabled"]),
            ip=item["destination_ip"],
            mac=item["destination_mac"],
            destination_port=int(item["destination_port"]),
            source_port=int(item["source_port"]),
        )
        for item in endpoints[8:]
    )
    profile = body["profile"]
    source = body["source"]
    center_mhz = float(profile["center_mhz"])
    # CONFIGURE deliberately leaves the live DAC registers untouched
    # (program_dac=False below).  Still give FEngineConfig an in-band
    # placeholder for validation. The DAC bank itself remains untouched.
    validation_dac_channels = tuple(
        DacChannelConfig(rf_frequency_mhz=center_mhz) for _ in range(8)
    )
    config = FEngineConfig(
        sample_rate_msps=int(profile["sample_rate_msps"]),
        mode=profile["mode"],
        center_mhz=center_mhz,
        board_id=int(body["board_id"]),
        mts_adc_target_latency=int(bitstream.get("mts_adc_target_latency", -1)),
        mts_dac_target_latency=int(bitstream.get("mts_dac_target_latency", -1)),
        source_ip=source["ip"],
        source_mac=source["mac"],
        time_destinations=time_destinations,
        spec_destinations=spec_destinations,
        dac_channels=validation_dac_channels,
    )
    controller = FEngineController(path)
    started = time.monotonic()
    applied = controller.prepare(config, fresh_download=True, program_dac=False)
    _record_active_bitstream_state(path)
    applied_core = controller.require_core()
    applied_core_status = applied_core.read_status()
    applied_core_version = f"0x{int(applied_core_status.get('core_version', 0)):08x}"
    _persist_mts_summary(
        _mts_summary(applied_core, core_version=applied_core_version)
    )
    return {
        "bitstream": {
            "id": bitstream["id"],
            "path": str(path),
            "sha256": bitstream["sha256"],
            "core_version": bitstream["core_version"],
        },
        "elapsed_ms": round((time.monotonic() - started) * 1000.0, 3),
        "streaming": bool(applied["status"].get("streaming", 0)),
        "board_id": int(applied["status"].get("board_id", 0)),
        "source_identity": applied["source_identity"],
        "endpoints": applied["endpoint_readback"],
        "status": _status_snapshot(controller),
    }


def _status(request: dict[str, Any]) -> dict[str, Any]:
    return _status_snapshot(_controller(request))


def _start(request: dict[str, Any]) -> dict[str, Any]:
    body = _body(request)
    controller = _controller(request)
    _expected_board(controller, body)
    watchdog = _require_reference_watchdog_ready(_bitstream(request))
    status = controller.start_immediate()
    return {
        "started": True,
        "reference_watchdog": watchdog,
        "status": status,
        "snapshot": _status_snapshot(controller),
    }


def _sync_prepare(request: dict[str, Any]) -> dict[str, Any]:
    body = _body(request)
    controller = _controller(request)
    _expected_board(controller, body)
    core = controller.require_core()
    status = core.prepare_scheduled_sync(
        generation=int(body["generation"]),
        target_pps_count=int(body["target_pps_count"]),
        epoch_tai_seconds=int(body["epoch_tai_seconds"]),
        first_sample0=(
            None if body.get("first_sample0") is None else int(body["first_sample0"])
        ),
        observation_tag=int(body.get("observation_tag", 0)),
        signal_chain_tag=int(body.get("signal_chain_tag", 0)),
        schedule_tag=int(body.get("schedule_tag", 0)),
        mts_result_id=int(body["mts_result_id"]),
    )
    return {"prepared": True, "sync": status, "snapshot": _status_snapshot(controller)}


def _sync_arm(request: dict[str, Any]) -> dict[str, Any]:
    body = _body(request)
    controller = _controller(request)
    _expected_board(controller, body)
    watchdog = _require_reference_watchdog_ready(_bitstream(request))
    status = controller.require_core().arm_scheduled_sync()
    return {
        "armed": True,
        "reference_watchdog": watchdog,
        "sync": status,
        "snapshot": _status_snapshot(controller),
    }


def _sync_abort(request: dict[str, Any]) -> dict[str, Any]:
    body = _body(request)
    controller = _controller(request)
    _expected_board(controller, body)
    status = controller.require_core().abort_scheduled_sync()
    return {"aborted": True, "sync": status, "snapshot": _status_snapshot(controller)}


def _sync_status(request: dict[str, Any]) -> dict[str, Any]:
    controller = _controller(request)
    return {
        "sync": controller.require_core().read_scheduled_sync_status(),
        "snapshot": _status_snapshot(controller),
    }


def _stop(request: dict[str, Any]) -> dict[str, Any]:
    controller = _controller(request)
    status = controller.stop_and_verify()
    return {"stopped": True, "status": status, "snapshot": _status_snapshot(controller)}


def _reset(request: dict[str, Any]) -> dict[str, Any]:
    body = _body(request)
    controller = _controller(request)
    _expected_board(controller, body)
    controller.stop_and_verify()
    controller.require_core().reset()
    return {"reset": True, "snapshot": _status_snapshot(controller)}


def _set_dac(request: dict[str, Any]) -> dict[str, Any]:
    body = _body(request)
    controller = _controller(request)
    _expected_board(controller, body)
    assert DacChannelConfig is not None
    channels = tuple(
        DacChannelConfig(
            enabled=bool(item["enabled"]),
            rf_frequency_mhz=float(item["rf_frequency_mhz"]),
            amplitude=float(item["amplitude_percent"]),
            phase_deg=float(item["phase_deg"]),
        )
        for item in sorted(body["channels"], key=lambda item: int(item["channel"]))
    )
    try:
        result = controller.apply_dac_live(channels, center_mhz=float(body["center_mhz"]))
    except Exception as exc:
        if RfdcCenterConflict is not None and isinstance(exc, RfdcCenterConflict):
            raise HelperError(
                "RFDC_CENTER_CONFLICT",
                str(exc),
                exit_code=EXIT_STATE_CONFLICT,
                details={
                    "requested_center_mhz": exc.requested_mhz,
                    "actual_center_mhz": exc.actual_mhz,
                },
            ) from exc
        raise
    return {"updated": True, **result}


COMMANDS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "status": _status,
    "configure": _configure,
    "start": _start,
    "sync-prepare": _sync_prepare,
    "sync-arm": _sync_arm,
    "sync-abort": _sync_abort,
    "sync-status": _sync_status,
    "stop": _stop,
    "reset": _reset,
    "set-dac": _set_dac,
}


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1 or args[0] not in COMMANDS:
        json.dump(
            {
                "ok": False,
                "error": {
                    "code": "UNKNOWN_COMMAND",
                    "message": "command must be status, configure, start, stop, reset, set-dac, sync-prepare, sync-arm, sync-abort, or sync-status",
                },
            },
            sys.stdout,
        )
        sys.stdout.write("\n")
        return EXIT_INVALID
    try:
        request = _read_request()
        with contextlib.redirect_stdout(sys.stderr):
            with _configure_hardware_guard(args[0] == "configure"):
                result = COMMANDS[args[0]](request)
    except HelperError as exc:
        payload: dict[str, Any] = {
            "ok": False,
            "error": {"code": exc.code, "message": exc.message},
        }
        if exc.details is not None:
            payload["error"]["details"] = exc.details
        json.dump(payload, sys.stdout, separators=(",", ":"))
        sys.stdout.write("\n")
        return exc.exit_code
    except (KeyError, TypeError, ValueError) as exc:
        json.dump(
            {
                "ok": False,
                "error": {"code": "INVALID_HELPER_REQUEST", "message": str(exc)},
            },
            sys.stdout,
            separators=(",", ":"),
        )
        sys.stdout.write("\n")
        return EXIT_INVALID
    except Exception as exc:  # pragma: no cover - exercised on the board
        traceback.print_exc(file=sys.stderr)
        json.dump(
            {
                "ok": False,
                "error": {
                    "code": "HARDWARE_OPERATION_FAILED",
                    "message": str(exc),
                    "details": {"type": type(exc).__name__},
                },
            },
            sys.stdout,
            separators=(",", ":"),
        )
        sys.stdout.write("\n")
        return EXIT_HARDWARE_UNAVAILABLE
    json.dump({"ok": True, "result": result}, sys.stdout, separators=(",", ":"))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
