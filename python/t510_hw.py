#!/usr/bin/env python3
"""One-shot PYNQ bridge for the stateless Stage 34 Rust Board Agent.

The request is one JSON object on stdin. Exactly one JSON object is emitted on
stdout; incidental PYNQ output is redirected to stderr.
"""

from __future__ import annotations

import contextlib
import ctypes
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import secrets
import signal
import sys
import tempfile
import time
import traceback
from typing import Any, Callable, TYPE_CHECKING

from python.t510_ams import read_ams_snapshot

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
OCB1_STATE_PATH = Path("/run/t510-ocb1.json")
CLOCK_DIAGNOSTIC_STATE_PATH = Path("/run/t510-clock-diagnostic.json")
OUTPUT_LOAD_STATE_PATH = Path("/run/t510-output-load.json")
RFDC_POWER_STATE_PATH = Path("/run/t510-rfdc-power.json")
SPUR_CORRECTION_STATE_PATH = Path("/run/t510-spur-correction.json")
SPUR_CORRECTION_MODEL_ROOT = Path("/var/lib/t510/spur-correction")
SPUR_CORRECTION_50OHM_GATE_PATH = SPUR_CORRECTION_MODEL_ROOT / "independent-50ohm-qualified.json"
LAST_CONFIGURE_REQUEST_PATH = Path("/run/t510-last-configure.json")
REFERENCE_WATCHDOG_MAX_AGE_MS = 1_500
CALIBRATION_OFFICIAL_MIN_DBFS = -40.0
CALIBRATION_ENGINEERING_MIN_DBFS = -36.0
CALIBRATION_ENGINEERING_MAX_DBFS = -8.0
CALIBRATION_PEAK_MAX_DBFS = -1.0

OCB1_DYNAMIC = "DYNAMIC"
OCB1_OVERRIDE_ACTIVE = "OVERRIDE_ACTIVE"
OCB1_RECONFIGURE_REQUIRED = "RECONFIGURE_REQUIRED"
OCB1_FAULT_LATCHED = "FAULT_LATCHED"
CLOCK_PRODUCTION_PROFILE = "160m_10m_cont_manual_clkin2"
CLOCK_DIAGNOSTIC_PROFILES = {
    "160m_10m_cont_manual_clkin2": ("external_10mhz", "continuous"),
    "160m_10m_request_manual_clkin2": ("external_10mhz", "mts_only"),
    "160m_10m_request_manual_clkin0": ("tcxo_10mhz", "mts_only"),
}
CLOCK_PROFILE_SYSREF_FREQUENCY_HZ = {
    "160m_10m_cont_manual_clkin2": 10_000_000,
    "160m_10m_request_manual_clkin2": 10_000_000,
    "160m_10m_request_manual_clkin0": 10_000_000,
}

OUTPUT_LOAD_PRODUCTION = "PRODUCTION"
OUTPUT_LOAD_ACTIVE = "ACTIVE"
OUTPUT_LOAD_RESTORE_REQUIRED = "RESTORE_REQUIRED"
OUTPUT_LOAD_FAULT_LATCHED = "FAULT_LATCHED"
RFDC_POWER_NORMAL = "NORMAL"
RFDC_POWER_DAC_SHUTDOWN = "DAC_SHUTDOWN"
RFDC_POWER_RESTORE_REQUIRED = "RESTORE_REQUIRED"
RFDC_POWER_FAULT_LATCHED = "FAULT_LATCHED"
SPUR_CORRECTION_CORE_VERSION = 0x0001_0036


def _default_spur_correction_state() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "calibration_state": "UNCALIBRATED",
        "spur_correction_id": None,
        "credential_valid": False,
        "diagnostic_only": True,
        "tracker_mode": "dynamic",
        "invalid_reason": "NOT_CALIBRATED",
        "result": None,
        "updated_at_unix_ms": time.time_ns() // 1_000_000,
    }


def _load_spur_correction_state() -> dict[str, Any]:
    try:
        value = json.loads(SPUR_CORRECTION_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _default_spur_correction_state()
    if not isinstance(value, dict) or int(value.get("schema_version", 0)) != 1:
        return {**_default_spur_correction_state(), "invalid_reason": "INVALID_STATE_FILE"}
    return {**_default_spur_correction_state(), **value}


def _persist_spur_correction_state(value: dict[str, Any]) -> dict[str, Any]:
    state = {**_default_spur_correction_state(), **value}
    state["updated_at_unix_ms"] = time.time_ns() // 1_000_000
    _write_json_atomic(SPUR_CORRECTION_STATE_PATH, state)
    return state


def _invalidate_spur_correction_state(reason: str) -> dict[str, Any]:
    previous = _load_spur_correction_state()
    return _persist_spur_correction_state(
        {
            **previous,
            "calibration_state": "INVALID",
            "spur_correction_id": None,
            "credential_valid": False,
            "invalid_reason": str(reason),
        }
    )


def _extend_stage34c2r_clock_profiles() -> None:
    manifest_path = os.environ.get("T510_CLOCK_DIAGNOSTIC_PROFILE_MANIFEST", "").strip()
    if not manifest_path:
        return
    try:
        manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"cannot load Stage 34c-2R clock profile manifest: {exc}") from exc
    for row in manifest.get("profiles", []):
        profile_id = str(row.get("profile_id", ""))
        if profile_id == "160m_5m_request_manual_clkin2" or (
            profile_id.startswith("160m_10m_request_clkin2_sdclkout3_phase_")
            or profile_id.startswith("160m_5m_request_clkin2_sdclkout3_phase_")
        ):
            CLOCK_DIAGNOSTIC_PROFILES[profile_id] = ("external_10mhz", "mts_only")
            CLOCK_PROFILE_SYSREF_FREQUENCY_HZ[profile_id] = int(row["sysref_frequency_hz"])


_extend_stage34c2r_clock_profiles()
PL_SYSREF_DIAGNOSTIC_CORE_VERSION = 0x0001_0035
PL_SYSREF_CAPTURE_OBSERVATION_SECONDS = 0.050
# Final v35 phase-eye-frozen route: the PL SYSREF input IOB has +3.809 ns
# setup and +0.830 ns hold slack.  Publish the smaller routed pin margin.
PL_SYSREF_INPUT_MARGIN_NS: float | None = 0.830


def _is_external_request_clock_profile(profile_id: str) -> bool:
    if profile_id in (
        "160m_10m_request_manual_clkin2",
        "160m_5m_request_manual_clkin2",
    ):
        return True
    for prefix in (
        "160m_10m_request_clkin2_sdclkout3_phase_",
        "160m_5m_request_clkin2_sdclkout3_phase_",
    ):
        suffix = profile_id.removeprefix(prefix)
        if suffix != profile_id and len(suffix) == 2 and suffix.isdigit():
            return int(suffix) < 32
    return False


class HelperError(RuntimeError):
    def __init__(self, code: str, message: str, *, exit_code: int, details: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.exit_code = int(exit_code)
        self.details = details


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    os.chmod(temporary, 0o644)
    temporary.replace(path)


def _default_ocb1_state() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "ocb1_override_state": OCB1_DYNAMIC,
        "ocb1_override_adc_mask": 0,
        "ocb1_transaction_id": None,
        "ocb1_transaction_valid": False,
        "ocb1_snapshot_sha256": None,
        "ocb1_current_sha256": None,
        "ocb1_restore_required": False,
        "fault": None,
        "updated_at_unix_ms": time.time_ns() // 1_000_000,
    }


def _load_ocb1_state() -> dict[str, Any]:
    try:
        value = json.loads(OCB1_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _default_ocb1_state()
    if not isinstance(value, dict) or int(value.get("schema_version", 0)) != 1:
        return {
            **_default_ocb1_state(),
            "ocb1_override_state": OCB1_RECONFIGURE_REQUIRED,
            "ocb1_restore_required": True,
            "fault": "INVALID_PERSISTED_OCB1_STATE",
        }
    return {**_default_ocb1_state(), **value}


def _persist_ocb1_state(value: dict[str, Any]) -> dict[str, Any]:
    state = {**_default_ocb1_state(), **value}
    state["updated_at_unix_ms"] = time.time_ns() // 1_000_000
    _write_json_atomic(OCB1_STATE_PATH, state)
    return state


def _invalidate_ocb1_state(reason: str) -> dict[str, Any]:
    previous = _load_ocb1_state()
    return _persist_ocb1_state(
        {
            **previous,
            "ocb1_override_state": OCB1_RECONFIGURE_REQUIRED,
            "ocb1_transaction_id": None,
            "ocb1_transaction_valid": False,
            "ocb1_restore_required": True,
            "invalid_reason": str(reason),
        }
    )


def _mark_ocb1_dynamic() -> dict[str, Any]:
    return _persist_ocb1_state(_default_ocb1_state())


def _default_clock_diagnostic_state() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "state": "PRODUCTION",
        "clock_transaction_id": None,
        "clock_transaction_valid": False,
        "profile_id": CLOCK_PRODUCTION_PROFILE,
        "profile_sha256": None,
        "clock_reference": "external_gpsdo",
        "sysref_policy": "continuous",
        "sample_rate_msps": None,
        "center_mhz": None,
        "restore_required": False,
        "invalid_reason": None,
        "fault": None,
        "updated_at_unix_ms": time.time_ns() // 1_000_000,
    }


def _load_clock_diagnostic_state() -> dict[str, Any]:
    try:
        value = json.loads(CLOCK_DIAGNOSTIC_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _default_clock_diagnostic_state()
    if not isinstance(value, dict) or int(value.get("schema_version", 0)) != 1:
        return {
            **_default_clock_diagnostic_state(),
            "state": "FAULT_LATCHED",
            "restore_required": True,
            "fault": "INVALID_PERSISTED_CLOCK_DIAGNOSTIC_STATE",
        }
    return {**_default_clock_diagnostic_state(), **value}


def _persist_clock_diagnostic_state(value: dict[str, Any]) -> dict[str, Any]:
    state = {**_default_clock_diagnostic_state(), **value}
    state["updated_at_unix_ms"] = time.time_ns() // 1_000_000
    _write_json_atomic(CLOCK_DIAGNOSTIC_STATE_PATH, state)
    return state


def _invalidate_clock_diagnostic_state(reason: str) -> dict[str, Any]:
    previous = _load_clock_diagnostic_state()
    if previous.get("state") == "PRODUCTION":
        return previous
    return _persist_clock_diagnostic_state(
        {
            **previous,
            "state": "RESTORE_REQUIRED",
            "clock_transaction_id": None,
            "clock_transaction_valid": False,
            "restore_required": True,
            "invalid_reason": str(reason),
        }
    )


def _mark_clock_production() -> dict[str, Any]:
    return _persist_clock_diagnostic_state(_default_clock_diagnostic_state())


def _default_output_load_state() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "state": OUTPUT_LOAD_PRODUCTION,
        "output_load_transaction_id": None,
        "transaction_valid": False,
        "consumed": False,
        "mode": None,
        "previous_mode": None,
        "sample_rate_msps": None,
        "mts_fingerprint": None,
        "restore_required": False,
        "invalid_reason": None,
        "fault": None,
        "updated_at_unix_ms": time.time_ns() // 1_000_000,
    }


def _load_output_load_state() -> dict[str, Any]:
    try:
        value = json.loads(OUTPUT_LOAD_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _default_output_load_state()
    if not isinstance(value, dict) or int(value.get("schema_version", 0)) != 1:
        return {
            **_default_output_load_state(),
            "state": OUTPUT_LOAD_FAULT_LATCHED,
            "restore_required": True,
            "fault": "INVALID_PERSISTED_OUTPUT_LOAD_STATE",
        }
    return {**_default_output_load_state(), **value}


def _persist_output_load_state(value: dict[str, Any]) -> dict[str, Any]:
    state = {**_default_output_load_state(), **value}
    state["updated_at_unix_ms"] = time.time_ns() // 1_000_000
    _write_json_atomic(OUTPUT_LOAD_STATE_PATH, state)
    return state


def _mark_output_load_production() -> dict[str, Any]:
    return _persist_output_load_state(_default_output_load_state())


def _invalidate_output_load_state(reason: str) -> dict[str, Any]:
    previous = _load_output_load_state()
    if previous.get("state") == OUTPUT_LOAD_PRODUCTION:
        return previous
    return _persist_output_load_state(
        {
            **previous,
            "state": OUTPUT_LOAD_RESTORE_REQUIRED,
            "output_load_transaction_id": None,
            "transaction_valid": False,
            "restore_required": True,
            "invalid_reason": str(reason),
        }
    )


def _default_rfdc_power_state() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "state": RFDC_POWER_NORMAL,
        "rfdc_power_transaction_id": None,
        "transaction_valid": False,
        "consumed": False,
        "restore_required": False,
        "invalid_reason": None,
        "fault": None,
        "updated_at_unix_ms": time.time_ns() // 1_000_000,
    }


def _load_rfdc_power_state() -> dict[str, Any]:
    try:
        value = json.loads(RFDC_POWER_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _default_rfdc_power_state()
    if not isinstance(value, dict) or int(value.get("schema_version", 0)) != 1:
        return {
            **_default_rfdc_power_state(),
            "state": RFDC_POWER_FAULT_LATCHED,
            "restore_required": True,
            "fault": "INVALID_PERSISTED_RFDC_POWER_STATE",
        }
    return {**_default_rfdc_power_state(), **value}


def _persist_rfdc_power_state(value: dict[str, Any]) -> dict[str, Any]:
    state = {**_default_rfdc_power_state(), **value}
    state["updated_at_unix_ms"] = time.time_ns() // 1_000_000
    _write_json_atomic(RFDC_POWER_STATE_PATH, state)
    return state


def _mark_rfdc_power_normal() -> dict[str, Any]:
    return _persist_rfdc_power_state(_default_rfdc_power_state())


def _invalidate_rfdc_power_state(reason: str) -> dict[str, Any]:
    previous = _load_rfdc_power_state()
    if previous.get("state") == RFDC_POWER_NORMAL:
        return previous
    return _persist_rfdc_power_state(
        {
            **previous,
            "state": RFDC_POWER_RESTORE_REQUIRED,
            "rfdc_power_transaction_id": None,
            "transaction_valid": False,
            "restore_required": True,
            "invalid_reason": str(reason),
        }
    )


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
    expected = int(str(bitstream["core_version"]), 0)
    controller = FEngineController(path, expected_core_version=expected)
    controller.connect(download=download)
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


def _board_temperature_c() -> float | None:
    telemetry = read_ams_snapshot()
    values = [float(value) for value in telemetry.get("temperatures_c", {}).values()]
    return max(values) if values else None


def _calibration_snapshot(controller: FEngineController) -> dict[str, Any]:
    core = controller.require_core()
    if not hasattr(core, "read_adc_calibration_status"):
        return {
            "supported": False,
            "frozen_adc_mask": 0,
            "requested_freeze_mask": 0,
            "software_owned_mask": 0,
            "channels": [],
            "coefficient_sha256": {},
            "error": "RFDC calibration API is unavailable in this helper build",
            "temperature_c": _board_temperature_c(),
        }
    result = dict(core.read_adc_calibration_status(require=False))
    result["temperature_c"] = _board_temperature_c()
    result["captured_at_unix_ms"] = time.time_ns() // 1_000_000
    return result


def _ocb1_status_snapshot(controller: FEngineController) -> dict[str, Any]:
    state = _load_ocb1_state()
    calibration = controller.require_core().read_adc_calibration_status(require=False)
    current_hash = calibration.get("coefficient_sha256", {}).get("ocb1")
    expected_hash = state.get("ocb1_snapshot_sha256")
    active = state.get("ocb1_override_state") == OCB1_OVERRIDE_ACTIVE
    integrity_ok = bool(
        not active
        or (
            state.get("ocb1_transaction_valid")
            and int(state.get("ocb1_override_adc_mask", 0)) == 0xFF
            and current_hash is not None
            and current_hash == expected_hash
            and int(calibration.get("frozen_adc_mask", -1)) == 0
        )
    )
    channels = []
    for row in calibration.get("channels", []):
        diagnostics = dict(row.get("ocb1_diagnostics", {}))
        channels.append(
            {
                "adc": row.get("adc"),
                "tile": row.get("tile"),
                "block": row.get("block"),
                **diagnostics,
            }
        )
    return {
        **state,
        "ocb1_current_sha256": current_hash,
        "ocb1_integrity_ok": integrity_ok,
        "frozen_adc_mask": int(calibration.get("frozen_adc_mask", 0)),
        "channels": channels,
        "calibration_supported": bool(calibration.get("supported", False)),
        "calibration_error": calibration.get("error"),
    }


def _require_ocb1_start_authorization(
    controller: FEngineController, body: dict[str, Any]
) -> dict[str, Any]:
    status = _ocb1_status_snapshot(controller)
    state = str(status.get("ocb1_override_state", OCB1_RECONFIGURE_REQUIRED))
    requested = body.get("ocb1_transaction_id")
    if state == OCB1_DYNAMIC:
        if requested not in (None, ""):
            raise HelperError(
                "OCB1_TRANSACTION_UNEXPECTED",
                "ocb1_transaction_id is only valid while an OCB1 override is active",
                exit_code=EXIT_STATE_CONFLICT,
                details={"ocb1": status},
            )
        return status
    if state != OCB1_OVERRIDE_ACTIVE:
        raise HelperError(
            "OCB1_RECONFIGURE_REQUIRED",
            "a complete CONFIGURE/MTS is required before START",
            exit_code=EXIT_STATE_CONFLICT,
            details={"ocb1": status},
        )
    if not bool(status.get("ocb1_integrity_ok")):
        raise HelperError(
            "OCB1_OVERRIDE_INTEGRITY_FAILED",
            "OCB1 snapshot state or coefficient readback changed",
            exit_code=EXIT_STATE_CONFLICT,
            details={"ocb1": status},
        )
    if not requested or str(requested) != str(status.get("ocb1_transaction_id")):
        raise HelperError(
            "OCB1_TRANSACTION_REQUIRED",
            "START requires the matching active ocb1_transaction_id",
            exit_code=EXIT_STATE_CONFLICT,
            details={"ocb1": status},
        )
    return status


def _clock_diagnostic_status_snapshot(
    controller: FEngineController, *, include_registers: bool = True
) -> dict[str, Any]:
    state = _load_clock_diagnostic_state()
    core = controller.require_core()
    try:
        live = dict(
            core.read_lmk_status(
                include_registers=bool(include_registers)
            )
        )
    except Exception as exc:  # noqa: BLE001 - status must retain the failure
        live = {
            "configured": False,
            "errors": [f"{type(exc).__name__}: {exc}"],
        }
    active = state.get("state") == "ACTIVE"
    integrity_errors: list[str] = []
    capture = _read_sysref_capture_evidence(core)
    if active:
        for name in ("profile_id", "profile_sha256", "sysref_policy"):
            if str(live.get(name, "")) != str(state.get(name, "")):
                integrity_errors.append(
                    f"{name}:expected={state.get(name)!r}:actual={live.get(name)!r}"
                )
        expected_reference = str(state.get("clock_reference", ""))
        if str(live.get("clock_reference", "")) != expected_reference:
            integrity_errors.append(
                "clock_reference:"
                f"expected={expected_reference!r}:actual={live.get('clock_reference')!r}"
            )
        if int(live.get("pll1_lock", 0)) != 1:
            integrity_errors.append("PLL1_NOT_LOCKED")
        if int(live.get("pll2_lock", 0)) != 1:
            integrity_errors.append("PLL2_NOT_LOCKED")
        if str(state.get("sysref_policy")) == "mts_only":
            if int(live.get("sysref_request_gpio", -1)) != 0:
                integrity_errors.append("SYSREF_REQUEST_GPIO_NOT_LOW")
            if bool(live.get("sysref_output_expected_on", True)):
                integrity_errors.append("SYSREF_OUTPUT_STILL_EXPECTED_ON")
            if capture.get("supported") and bool(capture.get("running")):
                integrity_errors.append("PHYSICAL_SYSREF_CAPTURE_STILL_RUNNING")
        elif str(state.get("sysref_policy")) == "continuous":
            if capture.get("supported") and not bool(capture.get("running")):
                integrity_errors.append("PHYSICAL_SYSREF_CAPTURE_NOT_RUNNING")
    return {
        **state,
        "live": {**live, "sysref_capture": capture},
        "integrity_ok": not integrity_errors,
        "integrity_errors": integrity_errors,
    }


def _require_clock_start_authorization(
    controller: FEngineController, body: dict[str, Any]
) -> dict[str, Any]:
    status = _clock_diagnostic_status_snapshot(controller, include_registers=False)
    state = str(status.get("state", "FAULT_LATCHED"))
    requested = body.get("clock_transaction_id")
    if state == "PRODUCTION":
        if requested not in (None, ""):
            raise HelperError(
                "CLOCK_TRANSACTION_UNEXPECTED",
                "clock_transaction_id is only valid while a diagnostic profile is active",
                exit_code=EXIT_STATE_CONFLICT,
                details={"clock_diagnostic": status},
            )
        return status
    if state != "ACTIVE" or not bool(status.get("clock_transaction_valid")):
        raise HelperError(
            "CLOCK_RESTORE_REQUIRED",
            "the production clock profile must be restored before START",
            exit_code=EXIT_STATE_CONFLICT,
            details={"clock_diagnostic": status},
        )
    if not bool(status.get("integrity_ok")):
        raise HelperError(
            "CLOCK_DIAGNOSTIC_INTEGRITY_FAILED",
            "the active diagnostic clock profile, SYSREF state, or PLL lock changed",
            exit_code=EXIT_STATE_CONFLICT,
            details={"clock_diagnostic": status},
        )
    if not requested or str(requested) != str(status.get("clock_transaction_id")):
        raise HelperError(
            "CLOCK_TRANSACTION_REQUIRED",
            "START requires the matching active clock_transaction_id",
            exit_code=EXIT_STATE_CONFLICT,
            details={"clock_diagnostic": status},
        )
    return status


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


def _read_sysref_capture_evidence(
    core: Any,
    first_status: dict[str, Any] | None = None,
    *,
    interval_seconds: float = PL_SYSREF_CAPTURE_OBSERVATION_SECONDS,
) -> dict[str, Any]:
    """Prove physical SYSREF activity from all three v35 capture domains."""
    status = dict(first_status if first_status is not None else core.read_status())
    supported = int(status.get("core_version", 0)) >= PL_SYSREF_DIAGNOSTIC_CORE_VERSION

    def counts(value: dict[str, Any]) -> dict[str, int]:
        return {
            "pl_160mhz": int(value.get("sysref_pl_edge_count", 0)),
            "adc_80mhz": int(value.get("sysref_adc_edge_count", 0)),
            "dac_80mhz": int(value.get("sysref_dac_edge_count", 0)),
        }

    before = counts(status)
    after = dict(before)
    deltas = {name: 0 for name in before}
    error = None
    observed_seconds = float(interval_seconds)
    if supported:
        try:
            observation_started = time.monotonic()
            time.sleep(max(float(interval_seconds), 0.0))
            second = core.read_status()
            observed_seconds = time.monotonic() - observation_started
            after = counts(second)
            deltas = {
                name: (int(after[name]) - int(before[name])) & 0xFFFF_FFFF
                for name in before
            }
        except Exception as exc:  # noqa: BLE001 - retain the diagnostic failure
            error = f"{type(exc).__name__}: {exc}"
    return {
        "supported": supported,
        "counts": after,
        "count_deltas": deltas,
        "running": bool(supported and error is None and all(value > 0 for value in deltas.values())),
        "observation_seconds": observed_seconds,
        "observation_error": error,
        "capture_levels": {
            "pl_160mhz": int(status.get("sysref_pl_capture_level", 0)),
            "adc_80mhz": int(status.get("sysref_adc_capture_level", 0)),
            "dac_80mhz": int(status.get("sysref_dac_capture_level", 0)),
        },
    }


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
    # ``status`` was captured before the comparatively slow RFDC/LMK
    # readbacks above.  Using it as the first counter sample makes the nominal
    # 50 ms observation include that unrelated latency and over-reports the
    # physical SYSREF frequency.  Take a fresh pair here so the published
    # interval and counter delta describe the same observation window.
    capture = _read_sysref_capture_evidence(core)
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
            else {"ok": False, "errors": ["Stage 34 RFDC contract readback unavailable"]}
        )
    except Exception as exc:
        rfdc_contract = {
            "ok": False,
            "errors": [f"{type(exc).__name__}: {exc}"],
        }
    calibration = _calibration_snapshot(controller)
    ocb1 = _ocb1_status_snapshot(controller)
    clock_transaction = _load_clock_diagnostic_state()
    try:
        tile_power = core.read_rfdc_tile_power_status()
    except Exception as exc:
        tile_power = {
            "supported": False,
            "error": f"{type(exc).__name__}:{exc}",
            "adc_enabled_mask": None,
            "dac_enabled_mask": None,
            "adc_tiles": [],
            "dac_tiles": [],
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
            "profile_sha256": clock.get("profile_sha256"),
            "sysref_mode": clock.get("sysref_mode"),
            "sysref_policy": clock.get("sysref_policy"),
            "selected_ref": clock.get("selected_ref"),
            "clock_reference": clock.get("clock_reference"),
            "lmk_clkin": clock.get("lmk_clkin"),
            "sysref_request_gpio": clock.get("sysref_request_gpio"),
            "sysref_output_expected_on": clock.get(
                "sysref_output_expected_on"
            ),
            "sysref_frequency_hz": clock.get(
                "sysref_frequency_hz",
                CLOCK_PROFILE_SYSREF_FREQUENCY_HZ.get(str(clock.get("profile_id", ""))),
            ),
            "sysref_capture_counts": capture["counts"],
            "sysref_capture_count_deltas": capture["count_deltas"],
            "sysref_capture_running": capture["running"],
            "sysref_capture_supported": capture["supported"],
            "sysref_capture_observation_seconds": capture["observation_seconds"],
            "sysref_capture_observation_error": capture["observation_error"],
            "sysref_capture_levels": capture["capture_levels"],
            "pl_sysref_delay_ps": clock.get("pl_sysref_delay_ps"),
            "pl_sysref_input_margin_ns": PL_SYSREF_INPUT_MARGIN_NS,
            "pll1_lock": int(clock.get("pll1_lock", 0)),
            "pll2_lock": int(clock.get("pll2_lock", 0)),
            "configured": bool(clock.get("configured", False)),
            "errors": clock.get("errors", []),
            "transaction": clock_transaction,
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
            "calibration": calibration,
            "ocb1": ocb1,
            "power": {
                **_load_rfdc_power_state(),
                "live": tile_power,
            },
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
            "fir_saturation_count": int(status.get("pfb_tile_overflow_count", 0)),
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
        "output_load": _load_output_load_state(),
        "adc_interleave_spur_correction": {
            **_load_spur_correction_state(),
            "hardware": status.get("adc_interleave_spur_correction", {}),
        },
        "dac": controller.read_dac_channels(center_mhz=center_mhz),
    }


def _config_from_saved_request(
    request: dict[str, Any],
    *,
    sample_rate_msps: int | None = None,
    center_mhz: float | None = None,
    mts_adc_target_latency: int | None = None,
    mts_dac_target_latency: int | None = None,
) -> FEngineConfig:
    """Rebuild the last production routing/config without downloading PL."""
    _load_control()
    assert DacChannelConfig is not None
    assert FlowDestination is not None
    assert FEngineConfig is not None
    body = _body(request)
    bitstream = _bitstream(request)
    endpoints = sorted(body["endpoints"], key=lambda item: int(item["endpoint_id"]))

    def destination(item: dict[str, Any]) -> FlowDestination:
        return FlowDestination(
            enabled=bool(item["enabled"]),
            ip=item["destination_ip"],
            mac=item["destination_mac"],
            destination_port=int(item["destination_port"]),
            source_port=int(item["source_port"]),
        )

    profile = body["profile"]
    source = body["source"]
    selected_center = float(
        profile["center_mhz"] if center_mhz is None else center_mhz
    )
    selected_rate = int(
        profile["sample_rate_msps"]
        if sample_rate_msps is None
        else sample_rate_msps
    )
    validation_dac_channels = tuple(
        DacChannelConfig(rf_frequency_mhz=selected_center) for _ in range(8)
    )
    return FEngineConfig(
        sample_rate_msps=selected_rate,
        mode=profile["mode"],
        center_mhz=selected_center,
        board_id=int(body["board_id"]),
        mts_adc_target_latency=int(
            bitstream.get("mts_adc_target_latency", -1)
            if mts_adc_target_latency is None
            else mts_adc_target_latency
        ),
        mts_dac_target_latency=int(
            bitstream.get("mts_dac_target_latency", -1)
            if mts_dac_target_latency is None
            else mts_dac_target_latency
        ),
        source_ip=source["ip"],
        source_mac=source["mac"],
        time_destinations=tuple(destination(item) for item in endpoints[:8]),
        spec_destinations=tuple(destination(item) for item in endpoints[8:]),
        dac_channels=validation_dac_channels,
    )


def _load_saved_configure_request() -> dict[str, Any]:
    try:
        value = json.loads(LAST_CONFIGURE_REQUEST_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HelperError(
            "CLOCK_DIAGNOSTIC_CONFIGURE_REQUIRED",
            "a successful production CONFIGURE is required before clock diagnostics",
            exit_code=EXIT_STATE_CONFLICT,
            details={"reason": str(exc)},
        ) from exc
    if not isinstance(value, dict):
        raise HelperError(
            "CLOCK_DIAGNOSTIC_CONFIGURE_REQUIRED",
            "the saved production CONFIGURE request is invalid",
            exit_code=EXIT_STATE_CONFLICT,
        )
    return value


def _apply_clock_profile(
    controller: FEngineController,
    saved_request: dict[str, Any],
    *,
    profile_id: str,
    sample_rate_msps: int,
    center_mhz: float,
    mts_adc_target_latency: int | None = None,
    mts_dac_target_latency: int | None = None,
) -> dict[str, Any]:
    profile_meta = CLOCK_DIAGNOSTIC_PROFILES[profile_id]
    # Shut the RFDC restart state machines down while the currently selected
    # LMK profile is still supplying their clocks.  Reprogramming the LMK first
    # can strand XRFdc_Reset at state 6 even though both PLL lock bits recover.
    pre_clock_tile_shutdown_calls = (
        controller.require_core().shutdown_all_rfdc_tiles()
    )
    config = _config_from_saved_request(
        saved_request,
        sample_rate_msps=sample_rate_msps,
        center_mhz=center_mhz,
        mts_adc_target_latency=mts_adc_target_latency,
        mts_dac_target_latency=mts_dac_target_latency,
    )
    # Program LMK while the old RFDC tiles are shut down, then re-load the
    # catalog-selected image only after the requested clock is stable. During
    # 34c-2R this is the isolated v35 /run candidate, not the v34 production
    # directory.
    # Rewriting LMK after the overlay is loaded strands XRFdc_Reset at restart
    # state 6 on this board.  The image identity is unchanged.
    old_core = controller.require_core()
    pre_overlay_clock = old_core.configure_clock(
        ref=profile_meta[0], profile=profile_id
    )
    time.sleep(float(old_core.RFDC_CLOCK_RECOVERY_SETTLE_SECONDS))
    pre_overlay_sysref = None
    if str(pre_overlay_clock.get("sysref_policy")) == "mts_only":
        pre_overlay_sysref = old_core.clock.set_sysref(True)
    controller.connect(download=True)
    running_capture = (
        _read_sysref_capture_evidence(controller.require_core())
        if str(pre_overlay_clock.get("sysref_policy")) == "mts_only"
        else None
    )
    post_overlay_tile_reset_calls = controller.require_core().reset_all_rfdc_tiles()
    applied = controller.prepare(
        config,
        fresh_download=False,
        program_dac=False,
        clock_ref=profile_meta[0],
        clock_profile=profile_id,
        force_clock_reconfigure=False,
    )
    core = controller.require_core()
    core_status = core.read_status()
    core_version = f"0x{int(core_status.get('core_version', 0)):08x}"
    mts = _mts_summary(core, core_version=core_version)
    _persist_mts_summary(mts)
    clock = dict(core.read_lmk_status(include_registers=True))
    return {
        "applied": applied,
        "clock": clock,
        "mts": mts,
        "config": config,
        "pre_clock_tile_shutdown_calls": pre_clock_tile_shutdown_calls,
        "pre_overlay_clock": pre_overlay_clock,
        "pre_overlay_sysref": pre_overlay_sysref,
        "sysref_running_capture": running_capture,
        "post_overlay_tile_reset_calls": post_overlay_tile_reset_calls,
    }


def _repeat_active_clock_profile_mts(
    controller: FEngineController,
    saved_request: dict[str, Any],
    *,
    profile_id: str,
    sample_rate_msps: int,
    center_mhz: float,
    mts_adc_target_latency: int | None = None,
    mts_dac_target_latency: int | None = None,
) -> dict[str, Any]:
    """Repeat MTS with RFDC tile resets while preserving the active LMK profile."""
    profile_meta = CLOCK_DIAGNOSTIC_PROFILES[profile_id]
    core = controller.require_core()
    core.stop()
    live_before = dict(core.read_lmk_status(include_registers=True))
    if (
        str(live_before.get("profile_id")) != profile_id
        or str(live_before.get("sysref_policy")) != "mts_only"
        or int(live_before.get("pll1_lock", 0)) != 1
        or int(live_before.get("pll2_lock", 0)) != 1
    ):
        raise RuntimeError(f"active phase profile cannot be reused: {live_before}")
    sysref_for_reset = core.clock.set_sysref(True)
    reset_calls = core.reset_all_rfdc_tiles()
    running_capture = _read_sysref_capture_evidence(core)
    config = _config_from_saved_request(
        saved_request,
        sample_rate_msps=sample_rate_msps,
        center_mhz=center_mhz,
        mts_adc_target_latency=mts_adc_target_latency,
        mts_dac_target_latency=mts_dac_target_latency,
    )
    applied = controller.prepare(
        config,
        fresh_download=False,
        program_dac=False,
        clock_ref=profile_meta[0],
        clock_profile=profile_id,
        force_clock_reconfigure=False,
    )
    core_status = core.read_status()
    core_version = f"0x{int(core_status.get('core_version', 0)):08x}"
    mts = _mts_summary(core, core_version=core_version)
    _persist_mts_summary(mts)
    clock = dict(core.read_lmk_status(include_registers=True))
    return {
        "applied": applied,
        "clock": clock,
        "mts": mts,
        "config": config,
        "pre_clock_tile_shutdown_calls": [],
        "pre_overlay_clock": live_before,
        "pre_overlay_sysref": sysref_for_reset,
        "sysref_running_capture": running_capture,
        "post_overlay_tile_reset_calls": reset_calls,
        "attempt_kind": "rfdc_reset",
    }


def _configure(request: dict[str, Any]) -> dict[str, Any]:
    _invalidate_spur_correction_state("CONFIGURE_STARTED")
    _invalidate_clock_diagnostic_state("CONFIGURE_STARTED")
    _invalidate_ocb1_state("CONFIGURE_STARTED")
    _invalidate_output_load_state("CONFIGURE_STARTED")
    _invalidate_rfdc_power_state("CONFIGURE_STARTED")
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
    controller = FEngineController(
        path,
        expected_core_version=int(str(bitstream["core_version"]), 0),
    )
    started = time.monotonic()
    applied = controller.prepare(config, fresh_download=True, program_dac=False)
    _record_active_bitstream_state(path)
    applied_core = controller.require_core()
    applied_core_status = applied_core.read_status()
    applied_core_version = f"0x{int(applied_core_status.get('core_version', 0)):08x}"
    _persist_mts_summary(
        _mts_summary(applied_core, core_version=applied_core_version)
    )
    _write_json_atomic(LAST_CONFIGURE_REQUEST_PATH, request)
    ocb1 = _mark_ocb1_dynamic()
    clock_diagnostic = _mark_clock_production()
    output_load = _mark_output_load_production()
    rfdc_power = _mark_rfdc_power_normal()
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
        "ocb1": ocb1,
        "clock_diagnostic": clock_diagnostic,
        "output_load": output_load,
        "rfdc_power": rfdc_power,
        "status": _status_snapshot(controller),
    }


def _status(request: dict[str, Any]) -> dict[str, Any]:
    return _status_snapshot(_controller(request))


def _require_clock_diagnostic_quiescent(
    controller: FEngineController, body: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any], float]:
    if body.get("receiver_stream_accepting") is not False:
        raise HelperError(
            "CLOCK_RECEIVER_QUIESCENCE_REQUIRED",
            "caller must prove receiver_stream_accepting=false",
            exit_code=EXIT_STATE_CONFLICT,
        )
    status, dac, center_mhz = _require_calibration_quiescent(
        controller,
        allow_training_dac=False,
    )
    calibration = controller.require_core().read_adc_calibration_status(require=True)
    if int(calibration.get("frozen_adc_mask", -1)) != 0:
        raise HelperError(
            "CLOCK_CALIBRATION_FREEZE_CONFLICT",
            "clock diagnostics require frozen_adc_mask=0x00",
            exit_code=EXIT_STATE_CONFLICT,
            details={"calibration": calibration},
        )
    ocb1 = _ocb1_status_snapshot(controller)
    if str(ocb1.get("ocb1_override_state")) != OCB1_DYNAMIC:
        raise HelperError(
            "CLOCK_OCB1_STATE_CONFLICT",
            "clock diagnostics require OCB1 state DYNAMIC after fresh CONFIGURE/MTS",
            exit_code=EXIT_STATE_CONFLICT,
            details={"ocb1": ocb1},
        )
    return status, dac, center_mhz


def _recover_clock_diagnostic_failure(
    request: dict[str, Any],
    controller: FEngineController,
    *,
    saved_request: dict[str, Any],
    sample_rate_msps: int,
    center_mhz: float,
) -> list[str]:
    errors: list[str] = []
    core = controller.require_core()
    for label, action in (
        ("STOP", controller.stop_and_verify),
        # Force the hardware gate low before touching clocking.  A partially
        # applied RFDC profile can make mixer readback temporarily disagree
        # across tiles, so the full eight-lane zero-amplitude transaction is
        # deliberately deferred until production clock/MTS has been restored.
        ("DAC_DISABLE_MASK", lambda: core.set_dac_enable_mask(0)),
        ("CALIBRATION_UNFREEZE", lambda: core.set_adc_calibration_freeze(False)),
    ):
        try:
            action()
        except Exception as exc:  # noqa: BLE001 - retain every recovery failure
            errors.append(f"{label}:{type(exc).__name__}:{exc}")
    try:
        if _load_ocb1_state().get("ocb1_override_state") == OCB1_OVERRIDE_ACTIVE:
            core.release_adc_ocb1_override()
    except Exception as exc:  # noqa: BLE001
        errors.append(f"OCB1_RELEASE:{type(exc).__name__}:{exc}")
    try:
        _apply_clock_profile(
            controller,
            saved_request,
            profile_id=CLOCK_PRODUCTION_PROFILE,
            sample_rate_msps=sample_rate_msps,
            center_mhz=center_mhz,
        )
        _mark_ocb1_dynamic()
        _mark_clock_production()
    except Exception as exc:  # noqa: BLE001
        errors.append(f"PRODUCTION_CLOCK_RESTORE:{type(exc).__name__}:{exc}")
    else:
        try:
            _mute_all_dac(controller, center_mhz)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"DAC_MUTE:{type(exc).__name__}:{exc}")
    if errors:
        _persist_clock_diagnostic_state(
            {
                **_load_clock_diagnostic_state(),
                "state": "FAULT_LATCHED",
                "clock_transaction_id": None,
                "clock_transaction_valid": False,
                "restore_required": True,
                "fault": errors,
            }
        )
    return errors


def _clock_diagnostic_status(request: dict[str, Any]) -> dict[str, Any]:
    controller = _controller(request)
    core_status = controller.require_core().read_status()
    return {
        **_clock_diagnostic_status_snapshot(controller, include_registers=True),
        "core_version": f"0x{int(core_status.get('core_version', 0)):08x}",
        "board_id": int(core_status.get("board_id", 0)),
        "bitstream_sha256": str(_bitstream(request)["sha256"]).lower(),
        "mts": _mts_summary(
            controller.require_core(),
            core_version=f"0x{int(core_status.get('core_version', 0)):08x}",
        ),
    }


def _clock_diagnostic_prepare(request: dict[str, Any]) -> dict[str, Any]:
    body = _body(request)
    controller = _controller(request)
    board_id = _expected_board(controller, body)
    _require_clock_diagnostic_quiescent(controller, body)
    _invalidate_spur_correction_state("CLOCK_DIAGNOSTIC_PREPARE")
    current_state = _load_clock_diagnostic_state()
    attempt_kind = str(body.get("attempt_kind", "overlay_reload")).strip().lower()
    repeat_active = (
        attempt_kind == "rfdc_reset"
        and current_state.get("state") == "ACTIVE"
        and current_state.get("clock_transaction_valid") is True
        and str(current_state.get("profile_id")) == str(body.get("profile_id"))
    )
    if current_state.get("state") != "PRODUCTION" and not repeat_active:
        raise HelperError(
            "CLOCK_DIAGNOSTIC_STATE_CONFLICT",
            "diagnostic prepare requires production state, or an active matching profile for rfdc_reset",
            exit_code=EXIT_STATE_CONFLICT,
            details={"clock_diagnostic": current_state},
        )
    profile_id = str(body["profile_id"])
    if profile_id not in CLOCK_DIAGNOSTIC_PROFILES:
        raise HelperError(
            "CLOCK_DIAGNOSTIC_PROFILE_INVALID",
            f"unsupported clock diagnostic profile {profile_id!r}",
            exit_code=EXIT_INVALID,
        )
    sample_rate_msps = int(body["sample_rate_msps"])
    if sample_rate_msps not in (160, 320):
        raise HelperError(
            "CLOCK_DIAGNOSTIC_SAMPLE_RATE_INVALID",
            "sample_rate_msps must be 160 or 320",
            exit_code=EXIT_INVALID,
        )
    center_mhz = float(body["center_mhz"])
    if not math.isfinite(center_mhz):
        raise HelperError(
            "CLOCK_DIAGNOSTIC_CENTER_INVALID",
            "center_mhz must be finite",
            exit_code=EXIT_INVALID,
        )
    saved_request = _load_saved_configure_request()
    saved_board = int(_body(saved_request)["board_id"])
    if saved_board != board_id:
        raise HelperError(
            "CLOCK_DIAGNOSTIC_CONFIGURE_REQUIRED",
            "saved production CONFIGURE belongs to a different board_id",
            exit_code=EXIT_STATE_CONFLICT,
            details={"saved_board_id": saved_board, "actual_board_id": board_id},
        )
    target_mode = str(body.get("mts_target_mode", "catalog")).strip().lower()
    if target_mode not in ("catalog", "discovery", "fixed"):
        raise HelperError(
            "CLOCK_DIAGNOSTIC_TARGET_MODE_INVALID",
            "mts_target_mode must be catalog, discovery, or fixed",
            exit_code=EXIT_INVALID,
        )
    adc_target: int | None = None
    dac_target: int | None = None
    if target_mode == "discovery":
        adc_target = -1
        dac_target = -1
    elif target_mode == "fixed":
        adc_target = int(body["mts_adc_target_latency"])
        dac_target = int(body["mts_dac_target_latency"])
        if adc_target < 0 or dac_target < 0:
            raise HelperError(
                "CLOCK_DIAGNOSTIC_TARGET_INVALID",
                "fixed MTS targets must be non-negative",
                exit_code=EXIT_INVALID,
            )
    try:
        negative_control: dict[str, Any] | None = None
        if bool(body.get("verify_sysref_negative_control", False)):
            if not _is_external_request_clock_profile(profile_id):
                raise ValueError(
                    "SYSREF negative control is only valid for the external request profile"
                )
            negative_seed = _apply_clock_profile(
                controller,
                saved_request,
                profile_id=profile_id,
                sample_rate_msps=sample_rate_msps,
                center_mhz=center_mhz,
                mts_adc_target_latency=adc_target,
                mts_dac_target_latency=dac_target,
            )
            core = controller.require_core()
            core.stop()
            core.clock.set_sysref(False)
            original_set_sysref = core.clock.set_sysref
            started = time.monotonic()
            timed_out = False
            forced_result: dict[str, Any] | None = None
            forced_error: str | None = None

            def timeout_handler(_signum: int, _frame: Any) -> None:
                raise TimeoutError("MTS did not complete with SYSREF_REQ held low")

            previous_handler = signal.signal(signal.SIGALRM, timeout_handler)
            core.clock.set_sysref = lambda _enable: original_set_sysref(False)
            native_stdout = ""
            with tempfile.TemporaryFile(mode="w+b") as native_output:
                sys.stdout.flush()
                saved_stdout_fd = os.dup(1)
                os.dup2(native_output.fileno(), 1)
                try:
                    try:
                        signal.setitimer(signal.ITIMER_REAL, 15.0)
                        forced_result = core._run_rfdc_mts_sequence(
                            required=False,
                            adc_target_latency=-1,
                            dac_target_latency=-1,
                        )
                    except TimeoutError as exc:
                        timed_out = True
                        forced_error = str(exc)
                    except Exception as exc:  # noqa: BLE001 - expected negative path
                        forced_error = f"{type(exc).__name__}: {exc}"
                finally:
                    signal.setitimer(signal.ITIMER_REAL, 0.0)
                    signal.signal(signal.SIGALRM, previous_handler)
                    core.clock.set_sysref = original_set_sysref
                    original_set_sysref(False)
                    ctypes.CDLL(None).fflush(None)
                    os.dup2(saved_stdout_fd, 1)
                    os.close(saved_stdout_fd)
                native_output.seek(0)
                native_stdout = native_output.read(32_768).decode(
                    "utf-8", errors="replace"
                )
            calls = list((forced_result or {}).get("calls", []))
            failures = list((forced_result or {}).get("failures", []))
            sync_succeeded = any(
                str(call.get("label", "")).endswith("_mts_sync")
                and int(call.get("result", 1)) == 0
                for call in calls
            )
            negative_control = {
                "sysref_request_held_low": True,
                "timeout_seconds": 15.0,
                "timed_out": timed_out,
                "elapsed_seconds": time.monotonic() - started,
                # The bounded low-request MTS runs against the just-qualified
                # tile state.  Reset is intentionally deferred to the normal
                # high-request apply below: this RFDC restart sequencer itself
                # waits for SYSREF at state 6 when the request is held low.
                "reset_calls": [],
                "reset_after_negative_control": "performed_by_final_qualified_apply",
                "qualified_seed": {
                    "clock": negative_seed["clock"],
                    "mts": negative_seed["mts"],
                    "pre_clock_tile_shutdown_calls": negative_seed[
                        "pre_clock_tile_shutdown_calls"
                    ],
                },
                "result": forced_result,
                "error": forced_error,
                "vendor_stdout": native_stdout,
                "passed": bool(timed_out or forced_error or failures or not sync_succeeded),
            }
            if not negative_control["passed"]:
                raise RuntimeError(
                    "MTS unexpectedly succeeded while external request SYSREF was held low"
                )
        apply_function = (
            _repeat_active_clock_profile_mts if attempt_kind == "rfdc_reset" else _apply_clock_profile
        )
        result = apply_function(
            controller,
            saved_request,
            profile_id=profile_id,
            sample_rate_msps=sample_rate_msps,
            center_mhz=center_mhz,
            mts_adc_target_latency=adc_target,
            mts_dac_target_latency=dac_target,
        )
        core = controller.require_core()
        live = dict(result["clock"])
        expected_reference = (
            "external_gpsdo"
            if CLOCK_DIAGNOSTIC_PROFILES[profile_id][0] == "external_10mhz"
            else "onboard_tcxo"
        )
        errors: list[str] = []
        if str(live.get("profile_id")) != profile_id:
            errors.append("PROFILE_READBACK_MISMATCH")
        if str(live.get("clock_reference")) != expected_reference:
            errors.append("REFERENCE_READBACK_MISMATCH")
        if int(live.get("pll1_lock", 0)) != 1:
            errors.append("PLL1_NOT_LOCKED")
        if int(live.get("pll2_lock", 0)) != 1:
            errors.append("PLL2_NOT_LOCKED")
        policy = CLOCK_DIAGNOSTIC_PROFILES[profile_id][1]
        if str(live.get("sysref_policy")) != policy:
            errors.append("SYSREF_POLICY_READBACK_MISMATCH")
        capture = _read_sysref_capture_evidence(core)
        if policy == "mts_only" and (
            int(live.get("sysref_request_gpio", -1)) != 0
            or bool(live.get("sysref_output_expected_on", True))
        ):
            errors.append("SYSREF_NOT_OFF_AFTER_MTS")
        if bool(capture.get("supported")):
            if capture.get("observation_error"):
                errors.append("SYSREF_CAPTURE_OBSERVATION_FAILED")
            elif policy == "mts_only" and bool(capture.get("running")):
                errors.append("PHYSICAL_SYSREF_NOT_OFF_AFTER_MTS")
            elif policy == "continuous" and not bool(capture.get("running")):
                errors.append("PHYSICAL_SYSREF_NOT_RUNNING")
        if errors:
            raise RuntimeError(f"clock diagnostic readback failed: {errors}; live={live}")
        transaction_id = f"clock-{secrets.token_hex(16)}"
        mts = dict(result["mts"])
        state = _persist_clock_diagnostic_state(
            {
                "schema_version": 1,
                "state": "ACTIVE",
                "clock_transaction_id": transaction_id,
                "clock_transaction_valid": True,
                "profile_id": profile_id,
                "profile_sha256": live.get("profile_sha256"),
                "clock_reference": expected_reference,
                "sysref_policy": policy,
                "sample_rate_msps": sample_rate_msps,
                "center_mhz": center_mhz,
                "restore_required": False,
                "invalid_reason": None,
                "fault": None,
                "board_id": board_id,
                "bitstream_sha256": str(_bitstream(request)["sha256"]).lower(),
                "mts_target_mode": target_mode,
                "attempt_kind": attempt_kind,
                "mts": mts,
                "sysref_negative_control": negative_control,
                "sysref_capture": capture,
                "sysref_running_capture": result.get("sysref_running_capture"),
                "created_at_unix_ms": time.time_ns() // 1_000_000,
            }
        )
        return {
            "prepared": True,
            "clock_transaction_id": transaction_id,
            "clock_diagnostic": {**state, "live": live, "integrity_ok": True},
            "mts": mts,
            "sysref_negative_control": negative_control,
            "attempt_kind": attempt_kind,
            "sysref_capture": capture,
            "sysref_running_capture": result.get("sysref_running_capture"),
            "snapshot": _status_snapshot(controller),
        }
    except Exception as exc:
        recovery_errors = _recover_clock_diagnostic_failure(
            request,
            controller,
            saved_request=saved_request,
            sample_rate_msps=sample_rate_msps,
            center_mhz=center_mhz,
        )
        raise HelperError(
            "CLOCK_DIAGNOSTIC_PREPARE_FAILED",
            str(exc),
            exit_code=EXIT_HARDWARE_UNAVAILABLE,
            details={"recovery_errors": recovery_errors},
        ) from exc


def _clock_diagnostic_restore(request: dict[str, Any]) -> dict[str, Any]:
    body = _body(request)
    controller = _controller(request)
    _expected_board(controller, body)
    _require_clock_diagnostic_quiescent(controller, body)
    saved_request = _load_saved_configure_request()
    saved_profile = _body(saved_request)["profile"]
    sample_rate_msps = int(saved_profile["sample_rate_msps"])
    center_mhz = float(saved_profile["center_mhz"])
    try:
        result = _apply_clock_profile(
            controller,
            saved_request,
            profile_id=CLOCK_PRODUCTION_PROFILE,
            sample_rate_msps=sample_rate_msps,
            center_mhz=center_mhz,
        )
        live = dict(result["clock"])
        if (
            str(live.get("profile_id")) != CLOCK_PRODUCTION_PROFILE
            or str(live.get("sysref_policy")) != "continuous"
            or str(live.get("clock_reference")) != "external_gpsdo"
            or int(live.get("pll1_lock", 0)) != 1
            or int(live.get("pll2_lock", 0)) != 1
        ):
            raise RuntimeError(f"production clock restore readback failed: {live}")
        state = _mark_clock_production()
        _mark_ocb1_dynamic()
        return {
            "restored": True,
            "clock_diagnostic": {**state, "live": live, "integrity_ok": True},
            "mts": result["mts"],
            "snapshot": _status_snapshot(controller),
        }
    except Exception as exc:
        _persist_clock_diagnostic_state(
            {
                **_load_clock_diagnostic_state(),
                "state": "FAULT_LATCHED",
                "clock_transaction_id": None,
                "clock_transaction_valid": False,
                "restore_required": True,
                "fault": f"{type(exc).__name__}: {exc}",
            }
        )
        raise HelperError(
            "CLOCK_DIAGNOSTIC_RESTORE_FAILED",
            str(exc),
            exit_code=EXIT_HARDWARE_UNAVAILABLE,
        ) from exc


def _calibration_status(request: dict[str, Any]) -> dict[str, Any]:
    controller = _controller(request)
    status = controller.require_core().read_status()
    return {
        **_calibration_snapshot(controller),
        "core_version": f"0x{int(status.get('core_version', 0)):08x}",
        "board_id": int(status.get("board_id", 0)),
        "bitstream_sha256": str(_bitstream(request)["sha256"]).lower(),
        "mts": _mts_summary(
            controller.require_core(),
            core_version=f"0x{int(status.get('core_version', 0)):08x}",
        ),
        "ocb1": _ocb1_status_snapshot(controller),
    }


def _ocb1_status(request: dict[str, Any]) -> dict[str, Any]:
    controller = _controller(request)
    status = controller.require_core().read_status()
    return {
        **_ocb1_status_snapshot(controller),
        "core_version": f"0x{int(status.get('core_version', 0)):08x}",
        "board_id": int(status.get("board_id", 0)),
        "bitstream_sha256": str(_bitstream(request)["sha256"]).lower(),
        "mts": _mts_summary(
            controller.require_core(),
            core_version=f"0x{int(status.get('core_version', 0)):08x}",
        ),
    }


def _require_ocb1_quiescent(
    controller: FEngineController, body: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any], float]:
    if body.get("receiver_stream_accepting") is not False:
        raise HelperError(
            "OCB1_RECEIVER_QUIESCENCE_REQUIRED",
            "caller must prove receiver_stream_accepting=false",
            exit_code=EXIT_STATE_CONFLICT,
        )
    status, dac, center_mhz = _require_calibration_quiescent(
        controller,
        allow_training_dac=False,
    )
    if bool(status.get("streaming", 0)):
        raise HelperError(
            "OCB1_STATE_CONFLICT",
            "OCB1 control requires streaming=false",
            exit_code=EXIT_STATE_CONFLICT,
        )
    return status, dac, center_mhz


def _recover_ocb1_failure(
    request: dict[str, Any], controller: FEngineController, center_mhz: float
) -> list[str]:
    errors: list[str] = []
    for label, action in (
        ("STOP", controller.stop_and_verify),
        ("DAC_MUTE", lambda: _mute_all_dac(controller, center_mhz)),
        ("OCB1_RELEASE", controller.require_core().release_adc_ocb1_override),
    ):
        try:
            action()
        except Exception as exc:  # noqa: BLE001 - preserve every recovery fault
            errors.append(f"{label}:{type(exc).__name__}:{exc}")
    try:
        saved = json.loads(LAST_CONFIGURE_REQUEST_PATH.read_text(encoding="utf-8"))
        if not isinstance(saved, dict):
            raise ValueError("saved configure request is not an object")
        with _configure_hardware_guard(True):
            _configure(saved)
    except Exception as exc:  # noqa: BLE001 - failure is latched below
        errors.append(f"RECONFIGURE_MTS:{type(exc).__name__}:{exc}")
    if errors:
        _persist_ocb1_state(
            {
                **_load_ocb1_state(),
                "ocb1_override_state": OCB1_FAULT_LATCHED,
                "ocb1_transaction_id": None,
                "ocb1_transaction_valid": False,
                "ocb1_restore_required": True,
                "fault": errors,
            }
        )
    return errors


def _ocb1_snapshot_override(request: dict[str, Any]) -> dict[str, Any]:
    body = _body(request)
    controller = _controller(request)
    _expected_board(controller, body)
    _status, dac, center_mhz = _require_ocb1_quiescent(controller, body)
    _invalidate_spur_correction_state("OCB1_OVERRIDE")
    before_state = _load_ocb1_state()
    if before_state.get("ocb1_override_state") != OCB1_DYNAMIC:
        raise HelperError(
            "OCB1_STATE_CONFLICT",
            "OCB1 snapshot override requires DYNAMIC state after a fresh CONFIGURE/MTS",
            exit_code=EXIT_STATE_CONFLICT,
            details={"ocb1": before_state},
        )
    before_calibration = controller.require_core().read_adc_calibration_status(require=True)
    if int(before_calibration.get("frozen_adc_mask", -1)) != 0:
        raise HelperError(
            "OCB1_CALIBRATION_FREEZE_CONFLICT",
            "GCB/TSCB freeze mask must remain 0x00 for the OCB1 experiment",
            exit_code=EXIT_STATE_CONFLICT,
            details={"calibration": before_calibration},
        )
    try:
        result = controller.require_core().set_adc_ocb1_snapshot_override()
        transaction_id = f"ocb1-{secrets.token_hex(16)}"
        state = _persist_ocb1_state(
            {
                "schema_version": 1,
                "ocb1_override_state": OCB1_OVERRIDE_ACTIVE,
                "ocb1_override_adc_mask": 0xFF,
                "ocb1_transaction_id": transaction_id,
                "ocb1_transaction_valid": True,
                "ocb1_snapshot_sha256": result["snapshot_sha256"],
                "ocb1_current_sha256": result["current_sha256"],
                "ocb1_restore_required": False,
                "fault": None,
                "created_at_unix_ms": time.time_ns() // 1_000_000,
                "board_id": int(body["expected_board_id"]),
                "bitstream_sha256": str(_bitstream(request)["sha256"]).lower(),
            }
        )
        return {
            "updated": True,
            "dac": dac,
            "ocb1": {**state, **result},
            "snapshot": _status_snapshot(controller),
        }
    except Exception as exc:
        recovery_errors = _recover_ocb1_failure(request, controller, center_mhz)
        raise HelperError(
            "RFDC_OCB1_OVERRIDE_FAILED",
            str(exc),
            exit_code=EXIT_HARDWARE_UNAVAILABLE,
            details={"recovery_errors": recovery_errors},
        ) from exc


def _ocb1_release(request: dict[str, Any]) -> dict[str, Any]:
    body = _body(request)
    controller = _controller(request)
    _expected_board(controller, body)
    _status, dac, center_mhz = _require_ocb1_quiescent(controller, body)
    before = _load_ocb1_state()
    if before.get("ocb1_override_state") != OCB1_OVERRIDE_ACTIVE:
        raise HelperError(
            "OCB1_STATE_CONFLICT",
            "OCB1 release requires an active snapshot override",
            exit_code=EXIT_STATE_CONFLICT,
            details={"ocb1": before},
        )
    supplied = body.get("ocb1_transaction_id")
    if not supplied or str(supplied) != str(before.get("ocb1_transaction_id")):
        raise HelperError(
            "OCB1_TRANSACTION_REQUIRED",
            "release requires the matching active ocb1_transaction_id",
            exit_code=EXIT_STATE_CONFLICT,
        )
    try:
        release = controller.require_core().release_adc_ocb1_override()
        state = _persist_ocb1_state(
            {
                **before,
                "ocb1_override_state": OCB1_RECONFIGURE_REQUIRED,
                "ocb1_override_adc_mask": 0,
                "ocb1_transaction_id": None,
                "ocb1_transaction_valid": False,
                "ocb1_restore_required": True,
                "invalid_reason": "OCB1_OVERRIDE_RELEASED",
            }
        )
        return {
            "updated": True,
            "dac": dac,
            "release": release,
            "ocb1": state,
            "required_action": "fresh CONFIGURE/MTS",
            "snapshot": _status_snapshot(controller),
        }
    except Exception as exc:
        recovery_errors = _recover_ocb1_failure(request, controller, center_mhz)
        raise HelperError(
            "RFDC_OCB1_RELEASE_FAILED",
            str(exc),
            exit_code=EXIT_HARDWARE_UNAVAILABLE,
            details={"recovery_errors": recovery_errors},
        ) from exc


def _require_calibration_quiescent(
    controller: FEngineController,
    *,
    allow_training_dac: bool,
    training_amplitude_percent: float | None = None,
) -> tuple[dict[str, Any], dict[str, Any], float]:
    core = controller.require_core()
    status = core.read_status()
    if bool(status.get("streaming", 0)):
        raise HelperError(
            "CALIBRATION_STATE_CONFLICT",
            "RFDC calibration control requires science streaming to be stopped",
            exit_code=EXIT_STATE_CONFLICT,
        )
    sync = core.read_scheduled_sync_status()
    if any(bool(sync.get(name, False)) for name in ("prepared", "armed", "selected")):
        raise HelperError(
            "CALIBRATION_STATE_CONFLICT",
            "RFDC calibration control is blocked while scheduled sync is prepared or armed",
            exit_code=EXIT_STATE_CONFLICT,
            details={"scheduled_sync": sync},
        )
    centers = [
        float(item["frequency_mhz"])
        for item in core.read_rfdc_mixer_frequencies().get("mixers", [])
        if item.get("kind") == "dac" and float(item.get("frequency_mhz", 0.0)) > 0.0
    ]
    if len(centers) != 8 or max(centers) - min(centers) > 1.0e-6:
        raise HelperError(
            "CALIBRATION_STATE_CONFLICT",
            "all eight DAC mixer centers must be available and identical",
            exit_code=EXIT_STATE_CONFLICT,
            details={"dac_centers_mhz": centers},
        )
    center_mhz = sum(centers) / len(centers)
    dac = controller.read_dac_channels(center_mhz=center_mhz)
    channels = list(dac.get("channels", []))
    muted = int(dac.get("enable_mask", 0)) == 0 and len(channels) == 8 and all(
        not bool(item.get("enabled", False))
        and int(item.get("amplitude_code", 0)) == 0
        and abs(float(item.get("amplitude_percent", 0.0))) <= 1.0e-9
        for item in channels
    )
    if not muted and not allow_training_dac:
        raise HelperError(
            "CALIBRATION_DAC_NOT_MUTED",
            "RFDC calibration control requires all eight DAC channels to be muted",
            exit_code=EXIT_STATE_CONFLICT,
            details={"dac": dac},
        )
    if allow_training_dac:
        if training_amplitude_percent is None:
            raise HelperError(
                "CALIBRATION_TRAINING_AMPLITUDE_REQUIRED",
                "training_amplitude_percent is required while the training DAC is active",
                exit_code=EXIT_INVALID,
            )
        expected_amplitude = float(training_amplitude_percent)
        if not 0.0 < expected_amplitude <= 100.0:
            raise HelperError(
                "CALIBRATION_TRAINING_AMPLITUDE_INVALID",
                "training_amplitude_percent must be within (0, 100]",
                exit_code=EXIT_INVALID,
            )
        expected_frequency = center_mhz + 60.0
        valid_training = int(dac.get("enable_mask", 0)) == 0xFF and len(channels) == 8 and all(
            bool(item.get("enabled", False))
            and abs(float(item.get("rf_frequency_mhz", 0.0)) - expected_frequency) <= 1.0e-6
            and abs(float(item.get("amplitude_percent", 0.0)) - expected_amplitude) <= 0.01
            for item in channels
        )
        if not valid_training:
            raise HelperError(
                "CALIBRATION_TRAINING_DAC_INVALID",
                "training requires all eight DACs at center+60 MHz and the declared amplitude",
                exit_code=EXIT_STATE_CONFLICT,
                details={
                    "center_mhz": center_mhz,
                    "expected_frequency_mhz": expected_frequency,
                    "expected_amplitude_percent": expected_amplitude,
                    "dac": dac,
                },
            )
    return status, dac, center_mhz


def _mute_all_dac(controller: FEngineController, center_mhz: float) -> dict[str, Any]:
    _load_control()
    assert DacChannelConfig is not None
    channels = tuple(
        DacChannelConfig(
            enabled=False,
            rf_frequency_mhz=float(center_mhz),
            amplitude=0.0,
            phase_deg=0.0,
        )
        for _ in range(8)
    )
    return controller.apply_dac_live(channels, center_mhz=float(center_mhz))


def _calibration_set(request: dict[str, Any], *, freeze: bool) -> dict[str, Any]:
    body = _body(request)
    controller = _controller(request)
    _expected_board(controller, body)
    training = bool(body.get("training_dac_active", False))
    _status, dac_before, center_mhz = _require_calibration_quiescent(
        controller,
        allow_training_dac=training and freeze,
        training_amplitude_percent=(
            float(body["training_amplitude_percent"])
            if training and freeze
            else None
        ),
    )
    _invalidate_spur_correction_state(
        "ADC_CALIBRATION_FREEZE" if freeze else "ADC_CALIBRATION_UNFREEZE"
    )
    try:
        result = controller.require_core().set_adc_calibration_freeze(bool(freeze))
        mute_result = _mute_all_dac(controller, center_mhz) if training else None
        return {
            "updated": True,
            "requested_freeze": bool(freeze),
            "training_dac_active": training,
            "dac_before": dac_before,
            "dac_after_training": mute_result,
            "calibration": result,
            "snapshot": _status_snapshot(controller),
        }
    except Exception as exc:
        cleanup_errors: list[str] = []
        try:
            controller.stop_and_verify()
        except Exception as cleanup:
            cleanup_errors.append(f"STOP: {type(cleanup).__name__}: {cleanup}")
        try:
            _mute_all_dac(controller, center_mhz)
        except Exception as cleanup:
            cleanup_errors.append(f"DAC_MUTE: {type(cleanup).__name__}: {cleanup}")
        raise HelperError(
            "RFDC_CALIBRATION_UPDATE_FAILED",
            str(exc),
            exit_code=EXIT_HARDWARE_UNAVAILABLE,
            details={"requested_freeze": bool(freeze), "cleanup_errors": cleanup_errors},
        ) from exc


def _calibration_freeze(request: dict[str, Any]) -> dict[str, Any]:
    return _calibration_set(request, freeze=True)


def _calibration_unfreeze(request: dict[str, Any]) -> dict[str, Any]:
    return _calibration_set(request, freeze=False)


def _calibration_preview(request: dict[str, Any]) -> dict[str, Any]:
    body = _body(request)
    controller = _controller(request)
    _expected_board(controller, body)
    status, dac, _center_mhz = _require_calibration_quiescent(
        controller,
        allow_training_dac=bool(body.get("training_dac_active", False)),
        training_amplitude_percent=(
            float(body["training_amplitude_percent"])
            if bool(body.get("training_dac_active", False))
            else None
        ),
    )
    core = controller.require_core()
    if not hasattr(core, "capture_preview_calibration_quiescent"):
        raise HelperError(
            "CALIBRATION_PREVIEW_UNAVAILABLE",
            "the board helper has no dry-run calibration preview transaction",
            exit_code=EXIT_HARDWARE_UNAVAILABLE,
        )
    preview = core.capture_preview_calibration_quiescent(
        n=1024,
        input_mask=0xFF,
        timeout=1.0,
    )
    channels = []
    for adc in range(8):
        samples = preview["iq"][adc]
        pairs = samples.tolist() if hasattr(samples, "tolist") else list(samples)
        powers = [int(i_value) ** 2 + int(q_value) ** 2 for i_value, q_value in pairs]
        rms_code = math.sqrt(sum(powers) / max(len(powers), 1))
        max_abs = max(
            (max(abs(int(i_value)), abs(int(q_value))) for i_value, q_value in pairs),
            default=0,
        )
        channels.append(
            {
                "adc": adc,
                "sample_count": len(pairs),
                "rms_code": rms_code,
                "rms_dbfs": 20.0 * math.log10(max(rms_code / 32768.0, 1.0e-12)),
                "max_abs_code": max_abs,
                "peak_dbfs": 20.0 * math.log10(max(max_abs / 32768.0, 1.0e-12)),
                "clipped": max_abs >= 32760,
            }
        )
    return {
        "captured": True,
        "streaming": bool(status.get("streaming", 0)),
        "science_udp_stopped": not bool(status.get("streaming", 0)),
        "dac": dac,
        "sample0": int(preview["sample0"]),
        "sample_rate_hz": int(preview["sample_rate_hz"]),
        "dry_run": preview.get("calibration_dry_run"),
        "channels": channels,
    }


def _calibration_train_freeze(request: dict[str, Any]) -> dict[str, Any]:
    body = _body(request)
    if not bool(body.get("training_dac_active", False)):
        raise HelperError(
            "CALIBRATION_TRAINING_DAC_REQUIRED",
            "train-freeze requires training_dac_active=true and the fixed all-eight tone",
            exit_code=EXIT_INVALID,
        )
    training_amplitude_percent = float(body["training_amplitude_percent"])
    controller = _controller(request)
    _expected_board(controller, body)
    _status, dac_before, center_mhz = _require_calibration_quiescent(
        controller,
        allow_training_dac=True,
        training_amplitude_percent=training_amplitude_percent,
    )
    core = controller.require_core()
    try:
        preview = core.capture_preview_calibration_quiescent(
            n=1024,
            input_mask=0xFF,
            timeout=1.0,
        )
        levels = []
        for adc in range(8):
            samples = preview["iq"][adc]
            pairs = samples.tolist() if hasattr(samples, "tolist") else list(samples)
            powers = [int(i_value) ** 2 + int(q_value) ** 2 for i_value, q_value in pairs]
            rms_code = math.sqrt(sum(powers) / max(len(powers), 1))
            max_abs = max(
                (max(abs(int(i_value)), abs(int(q_value))) for i_value, q_value in pairs),
                default=0,
            )
            rms_dbfs = 20.0 * math.log10(max(rms_code / 32768.0, 1.0e-12))
            peak_dbfs = 20.0 * math.log10(max(max_abs / 32768.0, 1.0e-12))
            levels.append(
                {
                    "adc": adc,
                    "rms_code": rms_code,
                    "rms_dbfs": rms_dbfs,
                    "max_abs_code": max_abs,
                    "peak_dbfs": peak_dbfs,
                    "clipped": max_abs >= 32760,
                }
            )
        bad_levels = [
            item
            for item in levels
            if item["clipped"]
            or not CALIBRATION_ENGINEERING_MIN_DBFS
            <= float(item["rms_dbfs"])
            <= CALIBRATION_ENGINEERING_MAX_DBFS
            or float(item["peak_dbfs"]) >= CALIBRATION_PEAK_MAX_DBFS
        ]
        if bad_levels:
            raise RuntimeError(
                f"CALIBRATION_TRAINING_LEVEL_FAILED: channels={bad_levels}"
            )
        convergence = core.wait_adc_calibration_convergence(
            poll_hz=5.0,
            stable_seconds=2.0,
            timeout_seconds=30.0,
            median_delta_lsb=1,
            p95_delta_lsb=4,
            max_delta_lsb=32,
        )
        frozen = core.set_adc_calibration_freeze(True)
        muted = _mute_all_dac(controller, center_mhz)
        return {
            "trained_and_frozen": True,
            "center_mhz": center_mhz,
            "tone_frequency_mhz": center_mhz + 60.0,
            "amplitude_percent": training_amplitude_percent,
            "level_policy": {
                "source": "AMD PG269 GCB/TSCB minimum input power",
                "official_min_dbfs": CALIBRATION_OFFICIAL_MIN_DBFS,
                "engineering_min_dbfs": CALIBRATION_ENGINEERING_MIN_DBFS,
                "engineering_max_dbfs": CALIBRATION_ENGINEERING_MAX_DBFS,
                "peak_max_dbfs": CALIBRATION_PEAK_MAX_DBFS,
            },
            "dac_before": dac_before,
            "preview": {
                "sample0": int(preview["sample0"]),
                "sample_rate_hz": int(preview["sample_rate_hz"]),
                "dry_run": preview.get("calibration_dry_run"),
                "channels": levels,
            },
            "convergence": convergence,
            "calibration": frozen,
            "dac_after": muted,
            "snapshot": _status_snapshot(controller),
        }
    except Exception as exc:
        cleanup_errors: list[str] = []
        try:
            core.set_adc_calibration_freeze(False)
        except Exception as cleanup:
            cleanup_errors.append(f"UNFREEZE: {type(cleanup).__name__}: {cleanup}")
        try:
            controller.stop_and_verify()
        except Exception as cleanup:
            cleanup_errors.append(f"STOP: {type(cleanup).__name__}: {cleanup}")
        try:
            _mute_all_dac(controller, center_mhz)
        except Exception as cleanup:
            cleanup_errors.append(f"DAC_MUTE: {type(cleanup).__name__}: {cleanup}")
        raise HelperError(
            "RFDC_CALIBRATION_TRAINING_FAILED",
            str(exc),
            exit_code=EXIT_HARDWARE_UNAVAILABLE,
            details={"cleanup_errors": cleanup_errors},
        ) from exc


def _diagnostic_fingerprint(controller: FEngineController) -> dict[str, Any]:
    """Fingerprint state that output-load and DAC-power interventions may not alter."""
    core = controller.require_core()
    status = core.read_status()
    core_version = f"0x{int(status.get('core_version', 0)):08x}"
    mts = _load_mts_summary(core_version=core_version) or _mts_summary(
        core, core_version=core_version
    )
    mixers = core.read_rfdc_mixer_frequencies()
    clock = core.read_lmk_status(include_registers=False)
    protected = {
        "core_version": core_version,
        "mts": mts,
        "mixers": mixers,
        "clock_profile_id": clock.get("profile_id"),
        "clock_profile_sha256": clock.get("profile_sha256"),
        "sysref_policy": clock.get("sysref_policy"),
        "pfb_nchan": int(status.get("pfb_nchan", 0)),
        "pfb_taps": int(status.get("pfb_taps", 0)),
        "pfb_coefficient_id": int(status.get("pfb_coeff_active_id", 0)),
        "pfb_coefficient_crc32": int(status.get("pfb_coeff_crc32", 0)),
        "fft_shift": int(status.get("pfb_fft_shift", 0)),
    }
    encoded = json.dumps(protected, sort_keys=True, separators=(",", ":")).encode()
    return {"sha256": hashlib.sha256(encoded).hexdigest(), "protected": protected}


def _require_diagnostic_quiescent(
    controller: FEngineController, body: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any], float]:
    if body.get("receiver_stream_accepting") is not False:
        raise HelperError(
            "DIAGNOSTIC_RECEIVER_QUIESCENCE_REQUIRED",
            "caller must prove receiver_stream_accepting=false",
            exit_code=EXIT_STATE_CONFLICT,
        )
    status, dac, center_mhz = _require_calibration_quiescent(
        controller, allow_training_dac=False
    )
    calibration = controller.require_core().read_adc_calibration_status(require=True)
    if int(calibration.get("frozen_adc_mask", -1)) != 0:
        raise HelperError(
            "DIAGNOSTIC_CALIBRATION_STATE_CONFLICT",
            "diagnostic interventions require freeze mask 0x00",
            exit_code=EXIT_STATE_CONFLICT,
            details={"calibration": calibration},
        )
    ocb1 = _ocb1_status_snapshot(controller)
    if str(ocb1.get("ocb1_override_state")) != OCB1_DYNAMIC:
        raise HelperError(
            "DIAGNOSTIC_OCB1_STATE_CONFLICT",
            "diagnostic interventions require dynamic OCB1",
            exit_code=EXIT_STATE_CONFLICT,
            details={"ocb1": ocb1},
        )
    clock = _clock_diagnostic_status_snapshot(controller, include_registers=False)
    if str(clock.get("state")) != "PRODUCTION" or not bool(clock.get("integrity_ok")):
        raise HelperError(
            "DIAGNOSTIC_CLOCK_STATE_CONFLICT",
            "diagnostic interventions require the production clock profile",
            exit_code=EXIT_STATE_CONFLICT,
            details={"clock": clock},
        )
    return status, dac, center_mhz


def _output_load_status_snapshot(controller: FEngineController) -> dict[str, Any]:
    state = _load_output_load_state()
    status = controller.require_core().read_status()
    profile = _profile_name(status)
    fingerprint = _diagnostic_fingerprint(controller)
    integrity_errors: list[str] = []
    if state.get("state") == OUTPUT_LOAD_ACTIVE:
        if str(profile.get("mode")) != str(state.get("mode")):
            integrity_errors.append("OUTPUT_MODE_CHANGED")
        if str(fingerprint["sha256"]) != str(state.get("mts_fingerprint")):
            integrity_errors.append("PROTECTED_CONFIGURATION_CHANGED")
    return {
        **state,
        "live_mode": profile.get("mode"),
        "live_sample_rate_msps": profile.get("sample_rate_msps"),
        "live_fingerprint": fingerprint,
        "integrity_ok": not integrity_errors,
        "integrity_errors": integrity_errors,
    }


def _apply_output_load_mode(
    controller: FEngineController, mode: str
) -> dict[str, Any]:
    if mode not in ("spec_only", "time_spec"):
        raise HelperError(
            "OUTPUT_LOAD_MODE_INVALID",
            "mode must be spec_only or time_spec",
            exit_code=EXIT_INVALID,
        )
    core = controller.require_core()
    current = _profile_name(core.read_status())
    if int(current.get("sample_rate_msps") or 0) != 160:
        raise HelperError(
            "OUTPUT_LOAD_RATE_INVALID",
            "output-load diagnostics are only qualified at 160 MS/s",
            exit_code=EXIT_STATE_CONFLICT,
            details={"profile": current},
        )
    saved = _load_saved_configure_request()
    endpoints = sorted(_body(saved)["endpoints"], key=lambda row: int(row["endpoint_id"]))
    time_endpoints = []
    for item in endpoints[:8]:
        time_endpoints.append(
            {
                "id": int(item["endpoint_id"]),
                "enable": mode == "time_spec",
                "ip": str(item["destination_ip"]),
                "mac": str(item["destination_mac"]),
                "dst_port": int(item["destination_port"]),
                "src_port": int(item["source_port"]),
            }
        )
    core.configure_tx_endpoints(time_endpoints)
    # The wide TIME packetizer receives one 8-input vector per beat.  Its
    # route lookup therefore matches the aggregate 0x00ff input mask once;
    # SCIENCE_TIME_MULTIFLOW_CONTROL then rotates the resulting packets over
    # endpoints 0..7.  Eight one-bit routes never match the aggregate mask and
    # produce a real route miss/drop on every TIME frame.
    core.configure_time_routes(
        [
            {
                "id": 0,
                "enable": True,
                "endpoint_id": 0,
                "input_mask": 0x00FF,
            }
        ],
        clear_unlisted=True,
    )
    applied = core.configure_science_output(
        160,
        mode,
        force_dry_run=False,
        cmac_enable=True,
        clear_counters=False,
        validate_live_ready=False,
    )
    live = _profile_name(core.read_status())
    if live.get("mode") != mode or int(live.get("sample_rate_msps") or 0) != 160:
        raise RuntimeError(f"output-load readback mismatch: {live}")
    endpoint_readback = core.read_tx_endpoints(range(8))
    route_readback = core.read_time_route_table()
    science_readback = core.read_science_output_status()
    if endpoint_readback != time_endpoints:
        raise RuntimeError(
            f"output-load TIME endpoint readback mismatch: requested={time_endpoints}; "
            f"actual={endpoint_readback}"
        )
    expected_routes = [
        {"id": route_id, "enable": int(route_id == 0), "endpoint_id": 0, "input_mask": 0x00FF if route_id == 0 else 0}
        for route_id in range(8)
    ]
    route_geometry = [
        {key: int(row[key]) for key in ("id", "enable", "endpoint_id", "input_mask")}
        for row in route_readback
    ]
    if route_geometry != expected_routes:
        raise RuntimeError(
            f"output-load TIME route readback mismatch: expected={expected_routes}; "
            f"actual={route_geometry}"
        )
    if (
        int(science_readback.get("time_multiflow_enable", 0)) != 1
        or int(science_readback.get("time_multiflow_base_endpoint", -1)) != 0
        or int(science_readback.get("time_multiflow_count", 0)) != 8
    ):
        raise RuntimeError(
            f"output-load TIME multiflow readback mismatch: {science_readback}"
        )
    return {
        "applied": applied,
        "profile": live,
        "time_endpoints": time_endpoints,
        "time_endpoint_readback": endpoint_readback,
        "time_route_readback": route_readback,
        "time_multiflow_readback": {
            key: science_readback[key]
            for key in (
                "time_multiflow_enable",
                "time_multiflow_base_endpoint",
                "time_multiflow_count",
            )
        },
    }


def _output_load_apply(request: dict[str, Any]) -> dict[str, Any]:
    body = _body(request)
    controller = _controller(request)
    _expected_board(controller, body)
    _require_diagnostic_quiescent(controller, body)
    if _load_rfdc_power_state().get("state") != RFDC_POWER_NORMAL:
        raise HelperError(
            "OUTPUT_LOAD_POWER_STATE_CONFLICT",
            "restore normal RFDC power before changing output load",
            exit_code=EXIT_STATE_CONFLICT,
        )
    before_state = _load_output_load_state()
    if before_state.get("state") != OUTPUT_LOAD_PRODUCTION:
        raise HelperError(
            "OUTPUT_LOAD_TRANSACTION_ACTIVE",
            "restore the existing output-load transaction first",
            exit_code=EXIT_STATE_CONFLICT,
            details={"output_load": before_state},
        )
    mode = str(body.get("mode", ""))
    before_fingerprint = _diagnostic_fingerprint(controller)
    before_profile = _profile_name(controller.require_core().read_status())
    try:
        applied = _apply_output_load_mode(controller, mode)
        after_fingerprint = _diagnostic_fingerprint(controller)
        if after_fingerprint["sha256"] != before_fingerprint["sha256"]:
            raise RuntimeError("output-load intervention changed MTS/NCO/PFB/clock state")
        transaction_id = f"output-load-{secrets.token_hex(16)}"
        state = _persist_output_load_state(
            {
                "state": OUTPUT_LOAD_ACTIVE,
                "output_load_transaction_id": transaction_id,
                "transaction_valid": True,
                "consumed": False,
                "mode": mode,
                "previous_mode": before_profile.get("mode"),
                "sample_rate_msps": 160,
                "mts_fingerprint": before_fingerprint["sha256"],
                "restore_required": True,
                "board_id": int(body["expected_board_id"]),
            }
        )
        return {
            "updated": True,
            "output_load_transaction_id": transaction_id,
            "output_load": state,
            "before_fingerprint": before_fingerprint,
            "after_fingerprint": after_fingerprint,
            "applied": applied,
            "snapshot": _status_snapshot(controller),
        }
    except Exception as exc:
        recovery_errors: list[str] = []
        try:
            _apply_output_load_mode(controller, str(before_profile.get("mode")))
            _mark_output_load_production()
        except Exception as cleanup:
            recovery_errors.append(f"OUTPUT_RESTORE:{type(cleanup).__name__}:{cleanup}")
            _persist_output_load_state(
                {
                    **_load_output_load_state(),
                    "state": OUTPUT_LOAD_FAULT_LATCHED,
                    "restore_required": True,
                    "fault": str(exc),
                }
            )
        raise HelperError(
            "OUTPUT_LOAD_APPLY_FAILED",
            str(exc),
            exit_code=EXIT_HARDWARE_UNAVAILABLE,
            details={"recovery_errors": recovery_errors},
        ) from exc


def _output_load_restore(request: dict[str, Any]) -> dict[str, Any]:
    body = _body(request)
    controller = _controller(request)
    _expected_board(controller, body)
    _require_diagnostic_quiescent(controller, body)
    state = _load_output_load_state()
    if state.get("state") == OUTPUT_LOAD_PRODUCTION:
        return {"restored": True, "already_production": True, "output_load": state}
    if state.get("state") not in (OUTPUT_LOAD_ACTIVE, OUTPUT_LOAD_RESTORE_REQUIRED):
        raise HelperError(
            "OUTPUT_LOAD_RESTORE_BLOCKED",
            "output-load state is fault-latched; full CONFIGURE is required",
            exit_code=EXIT_STATE_CONFLICT,
            details={"output_load": state},
        )
    mode = str(state.get("previous_mode") or "spec_only")
    try:
        applied = _apply_output_load_mode(controller, mode)
        restored = _mark_output_load_production()
        return {
            "restored": True,
            "applied": applied,
            "output_load": restored,
            "snapshot": _status_snapshot(controller),
        }
    except Exception as exc:
        failed = _persist_output_load_state(
            {
                **state,
                "state": OUTPUT_LOAD_FAULT_LATCHED,
                "transaction_valid": False,
                "restore_required": True,
                "fault": str(exc),
            }
        )
        raise HelperError(
            "OUTPUT_LOAD_RESTORE_FAILED",
            str(exc),
            exit_code=EXIT_HARDWARE_UNAVAILABLE,
            details={"output_load": failed},
        ) from exc


def _rfdc_power_status(request: dict[str, Any]) -> dict[str, Any]:
    controller = _controller(request)
    return {
        **_load_rfdc_power_state(),
        "live": controller.require_core().read_rfdc_tile_power_status(),
    }


def _recover_full_production_configure(saved_request: dict[str, Any]) -> dict[str, Any]:
    result = _configure(saved_request)
    _mark_output_load_production()
    _mark_rfdc_power_normal()
    return result


def _rfdc_power_dac_shutdown(request: dict[str, Any]) -> dict[str, Any]:
    body = _body(request)
    controller = _controller(request)
    _expected_board(controller, body)
    _require_diagnostic_quiescent(controller, body)
    if _load_output_load_state().get("state") != OUTPUT_LOAD_PRODUCTION:
        raise HelperError(
            "RFDC_POWER_OUTPUT_LOAD_CONFLICT",
            "restore output-load diagnostics before DAC shutdown",
            exit_code=EXIT_STATE_CONFLICT,
        )
    state = _load_rfdc_power_state()
    if state.get("state") != RFDC_POWER_NORMAL:
        raise HelperError(
            "RFDC_POWER_TRANSACTION_ACTIVE",
            "restore the existing RFDC power transaction first",
            exit_code=EXIT_STATE_CONFLICT,
            details={"rfdc_power": state},
        )
    saved = _load_saved_configure_request()
    before_fingerprint = _diagnostic_fingerprint(controller)
    try:
        shutdown = controller.require_core().shutdown_all_dac_tiles()
        after_fingerprint = _diagnostic_fingerprint(controller)
        if after_fingerprint["sha256"] != before_fingerprint["sha256"]:
            raise RuntimeError("DAC tile shutdown changed MTS/NCO/PFB/clock state")
        transaction_id = f"rfdc-power-{secrets.token_hex(16)}"
        persisted = _persist_rfdc_power_state(
            {
                "state": RFDC_POWER_DAC_SHUTDOWN,
                "rfdc_power_transaction_id": transaction_id,
                "transaction_valid": True,
                "consumed": False,
                "restore_required": True,
                "mts_fingerprint": before_fingerprint["sha256"],
                "board_id": int(body["expected_board_id"]),
                "live": shutdown["after"],
            }
        )
        return {
            "shutdown": True,
            "rfdc_power_transaction_id": transaction_id,
            "rfdc_power": persisted,
            "driver": shutdown,
            "before_fingerprint": before_fingerprint,
            "after_fingerprint": after_fingerprint,
            "snapshot": _status_snapshot(controller),
        }
    except Exception as exc:
        recovery_errors: list[str] = []
        try:
            controller.require_core().startup_all_dac_tiles()
        except Exception as cleanup:
            recovery_errors.append(f"DAC_STARTUP:{type(cleanup).__name__}:{cleanup}")
        try:
            _recover_full_production_configure(saved)
        except Exception as cleanup:
            recovery_errors.append(f"CONFIGURE:{type(cleanup).__name__}:{cleanup}")
            _persist_rfdc_power_state(
                {
                    **_load_rfdc_power_state(),
                    "state": RFDC_POWER_FAULT_LATCHED,
                    "transaction_valid": False,
                    "restore_required": True,
                    "fault": str(exc),
                }
            )
        raise HelperError(
            "RFDC_DAC_SHUTDOWN_FAILED",
            str(exc),
            exit_code=EXIT_HARDWARE_UNAVAILABLE,
            details={"recovery_errors": recovery_errors},
        ) from exc


def _rfdc_power_restore(request: dict[str, Any]) -> dict[str, Any]:
    body = _body(request)
    controller = _controller(request)
    _expected_board(controller, body)
    _require_diagnostic_quiescent(controller, body)
    state = _load_rfdc_power_state()
    if state.get("state") == RFDC_POWER_NORMAL:
        return {"restored": True, "already_normal": True, "rfdc_power": state}
    saved = _load_saved_configure_request()
    startup = None
    try:
        try:
            startup = controller.require_core().startup_all_dac_tiles()
        except Exception as startup_error:
            startup = {"ok": False, "error": f"{type(startup_error).__name__}:{startup_error}"}
        configured = _recover_full_production_configure(saved)
        verifier = _controller(request)
        live = verifier.require_core().read_rfdc_tile_power_status()
        if int(live.get("adc_enabled_mask", 0)) != 0xF or int(live.get("dac_enabled_mask", 0)) != 0xF:
            raise RuntimeError(f"RFDC tile restore readback failed: {live}")
        normal = _mark_rfdc_power_normal()
        return {
            "restored": True,
            "startup": startup,
            "configure": configured,
            "live": live,
            "rfdc_power": normal,
        }
    except Exception as exc:
        failed = _persist_rfdc_power_state(
            {
                **state,
                "state": RFDC_POWER_FAULT_LATCHED,
                "transaction_valid": False,
                "restore_required": True,
                "fault": str(exc),
            }
        )
        raise HelperError(
            "RFDC_POWER_RESTORE_FAILED",
            str(exc),
            exit_code=EXIT_HARDWARE_UNAVAILABLE,
            details={"rfdc_power": failed, "startup": startup},
        ) from exc


def _spur_configuration_fingerprint(request: dict[str, Any] | None = None) -> str:
    if request is None:
        try:
            request = json.loads(LAST_CONFIGURE_REQUEST_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise HelperError(
                "SPUR_CORRECTION_CONFIG_UNAVAILABLE",
                f"cannot read the current configure identity: {exc}",
                exit_code=EXIT_STATE_CONFLICT,
            ) from exc
    body = dict(request.get("request", {}))
    bitstream = dict(request.get("bitstream", {}))
    identity = {
        "board_id": body.get("board_id"),
        "profile": body.get("profile"),
        "bitstream_id": bitstream.get("id"),
        "bitstream_sha256": bitstream.get("sha256"),
        "core_version": bitstream.get("core_version"),
        "mts": json.loads(MTS_STATE_PATH.read_text(encoding="utf-8"))
        if MTS_STATE_PATH.is_file()
        else None,
    }
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _spur_current_window(controller: FEngineController) -> tuple[dict[str, Any], dict[str, Any] | None]:
    from python.t510_spur_correction import find_in_band_spur

    core = controller.require_core()
    status = core.read_status()
    sample_rate_msps = int(status.get("science_sample_rate_msps", 0))
    if sample_rate_msps not in (160, 320):
        raise HelperError(
            "SPUR_CORRECTION_PROFILE_INVALID",
            "spur correction requires a configured 160 or 320 MS/s science profile",
            exit_code=EXIT_STATE_CONFLICT,
            details={"sample_rate_msps": sample_rate_msps},
        )
    mixers = core.read_rfdc_mixer_frequencies()
    adc_mixer_readbacks = [
        float(row["frequency_mhz"])
        for row in mixers.get("mixers", [])
        if row.get("kind") == "adc" and row.get("frequency_mhz") is not None
    ]
    # RFDC reports the ADC complex-mixer NCO with the digital downconversion
    # sign.  The configured physical RF centre has the opposite sign (for
    # example a 420 MHz RF centre reads back as an ADC mixer at -420 MHz).
    # Spur identity is defined on the physical RF axis, not the signed NCO
    # rotation, so restore that axis before applying the in-band test.
    adc_centers = [-frequency_mhz for frequency_mhz in adc_mixer_readbacks]
    if len(adc_centers) != 8 or max(adc_centers) - min(adc_centers) > 1.0e-6:
        raise HelperError(
            "SPUR_CORRECTION_MIXER_READBACK_INVALID",
            "all eight ADC mixer readbacks must be present and identical",
            exit_code=EXIT_STATE_CONFLICT,
            details={"adc_centers_mhz": adc_centers},
        )
    center_hz = 1.0e6 * sum(adc_centers) / len(adc_centers)
    window = {
        "sample_rate_msps": sample_rate_msps,
        "sample_rate_hz": sample_rate_msps * 1_000_000,
        "center_mhz": center_hz / 1.0e6,
        "center_hz": center_hz,
        "adc_mixer_readback_mhz": adc_mixer_readbacks,
    }
    return window, find_in_band_spur(center_hz, sample_rate_msps * 1.0e6)


def _spur_temperature_c() -> float | None:
    snapshot = read_ams_snapshot()
    values = [float(value) for value in dict(snapshot.get("temperatures_c", {})).values()]
    return max(values) if values else None


def _spur_ocb_dft(calibration: dict[str, Any], adc: int, k: int) -> complex:
    channels = {int(row["adc"]): row for row in calibration.get("channels", [])}
    rows = dict(channels[int(adc)].get("ocb1_diagnostics", {})).get("dft", [])
    row = next(item for item in rows if int(item.get("k", -1)) == int(k))
    return complex(float(row["real"]), float(row["imag"]))


def _spur_correction_status(request: dict[str, Any]) -> dict[str, Any]:
    controller = _controller(request)
    core = controller.require_core()
    window, spur = _spur_current_window(controller)
    return {
        "state": _load_spur_correction_state(),
        "configuration_fingerprint": _spur_configuration_fingerprint(),
        "window": window,
        "in_band_spur": spur,
        "hardware": core.read_spur_correction_status(),
        "temperature_c": _spur_temperature_c(),
    }


def _spur_correction_calibrate(request: dict[str, Any]) -> dict[str, Any]:
    from python.t510_spur_correction import (
        LaneSpurModel,
        SPUR_PROFILE_ID,
        apply_ocb_tracking_matrix,
        canonical_sha256,
        estimate_preview_vector,
        fit_real_2x2,
        phase_step_u48,
        quantize_q8_16,
        save_model,
    )

    body = _body(request)
    controller = _controller(request)
    board_id = _expected_board(controller, body)
    if body.get("receiver_stream_accepting") is not False:
        raise HelperError(
            "SPUR_CORRECTION_RECEIVER_QUIESCENCE_REQUIRED",
            "spur calibration requires receiver_stream_accepting=false",
            exit_code=EXIT_STATE_CONFLICT,
        )
    fingerprint = _spur_configuration_fingerprint()
    if str(body.get("configuration_fingerprint", "")) != fingerprint:
        raise HelperError(
            "SPUR_CORRECTION_CONFIG_MISMATCH",
            "configuration_fingerprint does not match the current board configuration",
            exit_code=EXIT_STATE_CONFLICT,
            details={"expected": fingerprint, "provided": body.get("configuration_fingerprint")},
        )
    input_state = str(body.get("input_state", ""))
    if input_state not in ("all_open_diagnostic", "all_adc_independent_50ohm"):
        raise HelperError(
            "SPUR_CORRECTION_INPUT_STATE_INVALID",
            "input_state must be all_open_diagnostic or all_adc_independent_50ohm",
            exit_code=EXIT_INVALID,
        )
    bitstream = _bitstream(request)
    core = controller.require_core()
    status, dac, _center_mhz = _require_calibration_quiescent(
        controller, allow_training_dac=False
    )
    if int(status.get("core_version", 0)) != SPUR_CORRECTION_CORE_VERSION:
        raise HelperError(
            "SPUR_CORRECTION_UNSUPPORTED",
            "spur correction calibration requires CORE_VERSION 0x00010036",
            exit_code=EXIT_STATE_CONFLICT,
        )
    calibration_before = core.read_adc_calibration_status(require=True)
    ocb1_state = _load_ocb1_state()
    if int(calibration_before.get("frozen_adc_mask", 0)) != 0 or str(
        ocb1_state.get("ocb1_override_state", OCB1_DYNAMIC)
    ) != OCB1_DYNAMIC:
        raise HelperError(
            "SPUR_CORRECTION_OCB1_NOT_DYNAMIC",
            "spur correction requires dynamic RFDC calibration with freeze mask 0x00",
            exit_code=EXIT_STATE_CONFLICT,
            details={"calibration": calibration_before, "ocb1": ocb1_state},
        )
    window, spur = _spur_current_window(controller)
    if spur is None:
        raise HelperError(
            "SPUR_CORRECTION_NOT_IN_BAND",
            "the current observation window contains none of 480/960/1440 MHz",
            exit_code=EXIT_STATE_CONFLICT,
            details={"window": window},
        )
    if input_state == "all_adc_independent_50ohm":
        try:
            gate = json.loads(SPUR_CORRECTION_50OHM_GATE_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise HelperError(
                "SPUR_CORRECTION_50OHM_GATE_REQUIRED",
                "independent 50 ohm qualification evidence is not installed",
                exit_code=EXIT_STATE_CONFLICT,
                details={"path": str(SPUR_CORRECTION_50OHM_GATE_PATH), "error": str(exc)},
            ) from exc
        if not bool(gate.get("qualified")) or int(gate.get("board_id", -1)) != board_id:
            raise HelperError(
                "SPUR_CORRECTION_50OHM_GATE_REQUIRED",
                "independent 50 ohm qualification is not valid for this board",
                exit_code=EXIT_STATE_CONFLICT,
                details={"gate": gate},
            )

    state = _persist_spur_correction_state(
        {
            "calibration_state": "RUNNING",
            "credential_valid": False,
            "diagnostic_only": input_state != "all_adc_independent_50ohm",
            "tracker_mode": "dynamic",
            "invalid_reason": None,
            "progress": {"step": "raw_preview_ensemble", "completed": 0, "total": 64},
        }
    )
    core.disable_spur_correction(clear_errors=True)
    core.set_spur_correction_preview("raw")
    step = phase_step_u48(float(spur["offset_hz"]))
    c_observations: list[list[complex]] = [[] for _ in range(8)]
    d_observations: list[list[complex]] = [[] for _ in range(8)]
    preview_records: list[tuple[int, list[list[list[int]]]]] = []
    raw_preview_sha = hashlib.sha256()
    first_preview_sample0: int | None = None
    for capture_index in range(64):
        preview = core.capture_preview_calibration_quiescent(
            n=1024, input_mask=0xFF, timeout=1.0
        )
        if first_preview_sample0 is None:
            first_preview_sample0 = int(preview["sample0"])
        calibration = core.read_adc_calibration_status(require=True)
        capture_lanes: list[list[list[int]]] = []
        for adc in range(8):
            iq = preview["iq"][adc]
            d_value = _spur_ocb_dft(calibration, adc, int(spur["ocb1_dft_k"]))
            d_observations[adc].append(d_value)
            pairs = iq.tolist() if hasattr(iq, "tolist") else list(iq)
            normalized_pairs = [[int(i_value), int(q_value)] for i_value, q_value in pairs]
            capture_lanes.append(normalized_pairs)
            for i_value, q_value in pairs:
                raw_preview_sha.update(int(i_value).to_bytes(2, "little", signed=True))
                raw_preview_sha.update(int(q_value).to_bytes(2, "little", signed=True))
        preview_records.append((int(preview["sample0"]), capture_lanes))
        if capture_index in (7, 15, 31, 47, 63):
            state = _persist_spur_correction_state(
                {
                    **state,
                    "progress": {
                        "step": "raw_preview_ensemble",
                        "completed": capture_index + 1,
                        "total": 64,
                    },
                }
            )

    # First establish the actual hardware NCO origin.  Atomic commit latency is
    # intentionally unconstrained; correlating against sample0-origin makes the
    # calibration valid for arbitrary mixer centers rather than only offsets
    # whose period divides 8192 samples.
    generation = int(time.time_ns() & 0xFFFF_FFFF) or 1
    core.load_spur_correction_shadow(
        spur_id=int(spur["spur_id"]),
        phase_step=step,
        phase_seed=0,
        coefficients_q8_16=[(0, 0)] * 8,
        profile_id=SPUR_PROFILE_ID,
        model_crc32=0,
        generation=generation,
        enable=True,
        in_band=True,
        bypass=False,
        phase_reload=True,
    )
    origin_commit = core.commit_spur_correction()
    phase_origin_sample0 = int(origin_commit["last_commit_sample0"])
    core.heartbeat_spur_correction()
    for capture_index, (capture_sample0, capture_lanes) in enumerate(preview_records):
        for adc in range(8):
            c_observations[adc].append(
                estimate_preview_vector(
                    capture_lanes[adc],
                    sample0=capture_sample0,
                    step_u48=step,
                    phase_origin_sample0=phase_origin_sample0,
                )
            )

    lane_models: list[LaneSpurModel] = []
    coefficient_values: list[complex] = []
    tracking_fit: list[dict[str, Any]] = []
    for adc in range(8):
        try:
            matrix_raw = fit_real_2x2(d_observations[adc], c_observations[adc])
            fit_state = "FULL_2X2"
            fit_error = None
        except ValueError as exc:
            matrix_raw = [[0.0, 0.0], [0.0, 0.0]]
            fit_state = "STATIC_C0_ONLY"
            fit_error = str(exc)
        matrix = (
            (float(matrix_raw[0][0]), float(matrix_raw[0][1])),
            (float(matrix_raw[1][0]), float(matrix_raw[1][1])),
        )
        d0 = sum(d_observations[adc], 0j) / len(d_observations[adc])
        c0 = sum(c_observations[adc], 0j) / len(c_observations[adc])
        model = LaneSpurModel(
            c0=c0,
            d0=d0,
            matrix_2x2=matrix,
        )
        lane_models.append(model)
        coefficient_values.append(model.tracked(d_observations[adc][-1]))
        tracking_fit.append(
            {
                "adc": adc,
                "state": fit_state,
                "error": fit_error,
                "observations": len(d_observations[adc]),
            }
        )

    model_payload: dict[str, Any] = {
        "schema_version": 1,
        "board_id": board_id,
        "core_version": f"0x{SPUR_CORRECTION_CORE_VERSION:08x}",
        "bitstream_sha256": str(bitstream["sha256"]),
        "configuration_fingerprint": fingerprint,
        "input_state": input_state,
        "window": window,
        "spur": spur,
        "phase_origin_sample0": phase_origin_sample0,
        "profile_id": f"0x{SPUR_PROFILE_ID:08x}",
        "raw_preview_sha256": raw_preview_sha.hexdigest(),
        "tracking_fit": tracking_fit,
        "lanes": [model.to_json() for model in lane_models],
    }
    # The initial transaction is deliberately marked with a provisional model
    # identity.  Residual refinement changes C0, so the final frozen model is
    # re-hashed and committed once more below before a credential is issued.
    provisional_model_sha = canonical_sha256(model_payload)
    model_crc32 = zlib.crc32(provisional_model_sha.encode("ascii")) & 0xFFFF_FFFF
    quantized = [quantize_q8_16(value) for value in coefficient_values]
    load = core.load_spur_correction_shadow(
        spur_id=int(spur["spur_id"]),
        phase_step=step,
        phase_seed=0,
        coefficients_q8_16=quantized,
        profile_id=SPUR_PROFILE_ID,
        model_crc32=model_crc32,
        generation=generation,
        enable=True,
        in_band=True,
        bypass=False,
        phase_reload=False,
    )
    commit = core.commit_spur_correction()
    core.heartbeat_spur_correction()

    residual_history: list[dict[str, Any]] = []
    for refinement in range(2):
        core.set_spur_correction_preview("corrected")
        preview = core.capture_preview_calibration_quiescent(
            n=1024, input_mask=0xFF, timeout=1.0
        )
        residual = [
            estimate_preview_vector(
                preview["iq"][adc],
                sample0=int(preview["sample0"]),
                step_u48=step,
                phase_origin_sample0=phase_origin_sample0,
            )
            for adc in range(8)
        ]
        residual_history.append(
            {
                "iteration": refinement + 1,
                "sample0": int(preview["sample0"]),
                "residual": [[value.real, value.imag] for value in residual],
            }
        )
        coefficient_values = [value + delta for value, delta in zip(coefficient_values, residual)]
        quantized = [quantize_q8_16(value) for value in coefficient_values]
        load = core.load_spur_correction_shadow(
            spur_id=int(spur["spur_id"]),
            phase_step=step,
            phase_seed=0,
            coefficients_q8_16=quantized,
            profile_id=SPUR_PROFILE_ID,
            model_crc32=model_crc32,
            generation=generation,
            enable=True,
            in_band=True,
            bypass=False,
            phase_reload=False,
        )
        commit = core.commit_spur_correction()
        core.heartbeat_spur_correction()

    core.set_spur_correction_preview("raw")
    accumulated_residual = [complex(0.0, 0.0) for _ in range(8)]
    for row in residual_history:
        for adc, pair in enumerate(row["residual"]):
            accumulated_residual[adc] += complex(float(pair[0]), float(pair[1]))
    lane_models = [
        LaneSpurModel(
            c0=model.c0 + accumulated_residual[adc],
            d0=model.d0,
            matrix_2x2=model.matrix_2x2,
        )
        for adc, model in enumerate(lane_models)
    ]
    model_payload["lanes"] = [model.to_json() for model in lane_models]
    model_payload["residual_refinement"] = residual_history
    model_payload["final_coefficients_q8_16"] = [list(value) for value in quantized]
    model_sha = canonical_sha256(model_payload)
    model_crc32 = zlib.crc32(model_sha.encode("ascii")) & 0xFFFF_FFFF
    load = core.load_spur_correction_shadow(
        spur_id=int(spur["spur_id"]),
        phase_step=step,
        phase_seed=0,
        coefficients_q8_16=quantized,
        profile_id=SPUR_PROFILE_ID,
        model_crc32=model_crc32,
        generation=generation,
        enable=True,
        in_band=True,
        bypass=False,
        phase_reload=False,
    )
    commit = core.commit_spur_correction()
    core.heartbeat_spur_correction()
    core.set_spur_correction_preview("corrected")
    verification_preview = core.capture_preview_calibration_quiescent(
        n=1024, input_mask=0xFF, timeout=1.0
    )
    verification_residual = [
        estimate_preview_vector(
            verification_preview["iq"][adc],
            sample0=int(verification_preview["sample0"]),
            step_u48=step,
            phase_origin_sample0=phase_origin_sample0,
        )
        for adc in range(8)
    ]
    verification_dbfs = [
        20.0 * math.log10(max(abs(value) / 32768.0, 1.0e-15))
        for value in verification_residual
    ]
    core.set_spur_correction_preview("raw")
    if input_state == "all_adc_independent_50ohm" and any(
        value > -90.0 for value in verification_dbfs
    ):
        core.disable_spur_correction(clear_errors=False)
        raise HelperError(
            "SPUR_CORRECTION_PREVIEW_RESIDUAL_FAILED",
            "corrected preview residual exceeds the -90 dBFS formal calibration gate",
            exit_code=EXIT_STATE_CONFLICT,
            details={
                "residual_dbfs": verification_dbfs,
                "limit_dbfs": -90.0,
                "sample0": int(verification_preview["sample0"]),
            },
        )
    model_name = f"board{board_id}_spur{int(spur['spur_id'])}_{int(window['sample_rate_msps'])}msps.json"
    frozen_model = save_model(SPUR_CORRECTION_MODEL_ROOT / model_name, model_payload)
    if frozen_model["sha256"] != model_sha:
        raise RuntimeError("final spur model SHA changed during persistence")
    temperature_c = _spur_temperature_c()
    credential_id = f"spur-{secrets.token_hex(16)}"
    result = {
        "spur_correction_id": credential_id,
        "diagnostic_only": input_state != "all_adc_independent_50ohm",
        "board_id": board_id,
        "core_version": f"0x{SPUR_CORRECTION_CORE_VERSION:08x}",
        "bitstream_sha256": str(bitstream["sha256"]),
        "configuration_fingerprint": fingerprint,
        "window": window,
        "spur": spur,
        "phase_step": step,
        "profile_id": f"0x{SPUR_PROFILE_ID:08x}",
        "model_path": str(SPUR_CORRECTION_MODEL_ROOT / model_name),
        "model_sha256": frozen_model["sha256"],
        "model_crc32": model_crc32,
        "coefficient_crc32": load["coefficient_crc32"],
        "generation": generation,
        "ocb1_baseline_sha256": calibration_before.get("coefficient_sha256", {}).get("ocb1"),
        "temperature_c": temperature_c,
        "raw_first_sample0": first_preview_sample0,
        "phase_origin_sample0": phase_origin_sample0,
        "origin_commit": origin_commit,
        "residual_refinement": residual_history,
        "corrected_preview_verification": {
            "sample0": int(verification_preview["sample0"]),
            "residual": [[value.real, value.imag] for value in verification_residual],
            "residual_dbfs": verification_dbfs,
            "all_lanes_at_or_below_minus_90_dbfs": all(
                value <= -90.0 for value in verification_dbfs
            ),
        },
        "hardware": commit,
        "dac": dac,
    }
    state = _persist_spur_correction_state(
        {
            "calibration_state": "CALIBRATED",
            "spur_correction_id": credential_id,
            "credential_valid": True,
            "diagnostic_only": result["diagnostic_only"],
            "tracker_mode": "dynamic",
            "invalid_reason": None,
            "result": result,
            "progress": {"step": "complete", "completed": 64, "total": 64},
        }
    )
    return {"calibrated": True, "state": state, "result": result}


def _spur_correction_tracker_mode(request: dict[str, Any]) -> dict[str, Any]:
    """Select static-C0 or read-only dynamic-OCB tracking for diagnostics."""

    from python.t510_spur_correction import (
        LaneSpurModel,
        load_model,
        quantize_q8_16,
    )

    body = _body(request)
    controller = _controller(request)
    board_id = _expected_board(controller, body)
    if body.get("receiver_stream_accepting") is not False:
        raise HelperError(
            "SPUR_CORRECTION_RECEIVER_QUIESCENCE_REQUIRED",
            "changing tracker mode requires receiver_stream_accepting=false",
            exit_code=EXIT_STATE_CONFLICT,
        )
    mode = str(body.get("mode", ""))
    if mode not in ("static_c0", "dynamic"):
        raise HelperError(
            "SPUR_CORRECTION_TRACKER_MODE_INVALID",
            "tracker mode must be static_c0 or dynamic",
            exit_code=EXIT_INVALID,
        )
    state = _load_spur_correction_state()
    supplied = str(body.get("spur_correction_id", ""))
    if (
        not bool(state.get("credential_valid"))
        or not supplied
        or supplied != str(state.get("spur_correction_id"))
    ):
        raise HelperError(
            "SPUR_CORRECTION_CREDENTIAL_INVALID",
            "changing tracker mode requires the matching active credential",
            exit_code=EXIT_STATE_CONFLICT,
            details={"state": state},
        )
    if not bool(state.get("diagnostic_only")):
        raise HelperError(
            "SPUR_CORRECTION_TRACKER_MODE_DIAGNOSTIC_ONLY",
            "static/dynamic tracker A/B selection is restricted to diagnostic credentials",
            exit_code=EXIT_STATE_CONFLICT,
        )
    result = dict(state.get("result") or {})
    if int(result.get("board_id", -1)) != board_id:
        raise HelperError(
            "SPUR_CORRECTION_CREDENTIAL_INVALID",
            "credential board ID does not match the requested board",
            exit_code=EXIT_STATE_CONFLICT,
        )
    controller.stop_and_verify()
    core = controller.require_core()
    model = load_model(str(result["model_path"]))
    if str(model.get("sha256")) != str(result.get("model_sha256")):
        raise HelperError(
            "SPUR_CORRECTION_MODEL_INVALID",
            "credential/model SHA256 mismatch",
            exit_code=EXIT_STATE_CONFLICT,
        )
    calibration = core.read_adc_calibration_status(require=True)
    if int(calibration.get("frozen_adc_mask", -1)) != 0:
        raise HelperError(
            "SPUR_CORRECTION_OCB1_NOT_DYNAMIC",
            "tracker mode requires freeze mask 0x00",
            exit_code=EXIT_STATE_CONFLICT,
        )
    spur = dict(result["spur"])
    k = int(spur["ocb1_dft_k"])
    lane_models = [LaneSpurModel.from_json(row) for row in model["lanes"]]
    if len(lane_models) != 8:
        raise HelperError(
            "SPUR_CORRECTION_MODEL_INVALID",
            "frozen model does not contain eight lanes",
            exit_code=EXIT_STATE_CONFLICT,
        )
    values = []
    for adc, lane_model in enumerate(lane_models):
        value = lane_model.c0
        if mode == "dynamic":
            value = lane_model.tracked(_spur_ocb_dft(calibration, adc, k))
        values.append(quantize_q8_16(value))
    load = core.load_spur_correction_shadow(
        spur_id=int(spur["spur_id"]),
        phase_step=int(result["phase_step"]),
        phase_seed=0,
        coefficients_q8_16=values,
        profile_id=int(str(result["profile_id"]), 0),
        model_crc32=int(result["model_crc32"]),
        generation=int(result["generation"]),
        enable=True,
        in_band=True,
        bypass=False,
        phase_reload=False,
    )
    commit = core.commit_spur_correction()
    hardware = core.heartbeat_spur_correction()
    updated = _persist_spur_correction_state(
        {
            **state,
            "tracker_mode": mode,
            "tracker_mode_changed_at_unix_ms": time.time_ns() // 1_000_000,
        }
    )
    return {
        "updated": True,
        "tracker_mode": mode,
        "state": updated,
        "load": load,
        "commit": commit,
        "hardware": hardware,
    }


def _spur_correction_disable(request: dict[str, Any]) -> dict[str, Any]:
    body = _body(request)
    controller = _controller(request)
    _expected_board(controller, body)
    if body.get("receiver_stream_accepting") is not False:
        raise HelperError(
            "SPUR_CORRECTION_RECEIVER_QUIESCENCE_REQUIRED",
            "disabling correction requires receiver_stream_accepting=false",
            exit_code=EXIT_STATE_CONFLICT,
        )
    controller.stop_and_verify()
    hardware = controller.require_core().disable_spur_correction(clear_errors=False)
    state = _invalidate_spur_correction_state("EXPLICIT_DISABLE")
    return {"disabled": True, "state": state, "hardware": hardware}


def _require_spur_correction_start_authorization(
    controller: FEngineController,
    body: dict[str, Any],
    bitstream: dict[str, Any],
) -> dict[str, Any]:
    from python.t510_spur_correction import SPUR_PROFILE_ID, phase_step_u48

    core = controller.require_core()
    status = core.read_status()
    if int(status.get("core_version", 0)) < SPUR_CORRECTION_CORE_VERSION:
        return {"supported": False, "active": False, "warning": None}
    window, spur = _spur_current_window(controller)
    supplied = body.get("spur_correction_id")
    if spur is None:
        if supplied:
            raise HelperError(
                "SPUR_CORRECTION_NOT_APPLICABLE",
                "a spur_correction_id was supplied but no fixed spur is in-band",
                exit_code=EXIT_STATE_CONFLICT,
            )
        hardware = core.disable_spur_correction(clear_errors=False)
        return {"supported": True, "active": False, "warning": None, "window": window, "hardware": hardware}

    state = _load_spur_correction_state()
    if supplied:
        result = dict(state.get("result") or {})
        current_fingerprint = _spur_configuration_fingerprint()
        valid = (
            bool(state.get("credential_valid"))
            and str(supplied) == str(state.get("spur_correction_id"))
            and str(result.get("configuration_fingerprint")) == current_fingerprint
            and str(result.get("bitstream_sha256")) == str(bitstream.get("sha256"))
            and int(dict(result.get("spur", {})).get("spur_id", -1)) == int(spur["spur_id"])
            and int(dict(result.get("window", {})).get("sample_rate_msps", -1)) == int(window["sample_rate_msps"])
            and abs(float(dict(result.get("window", {})).get("center_mhz", -1.0)) - float(window["center_mhz"])) <= 1.0e-6
        )
        if not valid:
            raise HelperError(
                "SPUR_CORRECTION_CREDENTIAL_INVALID",
                "spur_correction_id is missing, stale, or bound to another configuration",
                exit_code=EXIT_STATE_CONFLICT,
                details={"state": state, "window": window, "spur": spur},
            )
        current_temperature = _spur_temperature_c()
        calibration_temperature = result.get("temperature_c")
        temperature_delta = (
            abs(float(current_temperature) - float(calibration_temperature))
            if current_temperature is not None and calibration_temperature is not None
            else None
        )
        if temperature_delta is not None and temperature_delta > 5.0:
            _invalidate_spur_correction_state("TEMPERATURE_DELTA_GT_5C")
            core.disable_spur_correction(clear_errors=False)
            raise HelperError(
                "SPUR_CORRECTION_TEMPERATURE_INVALID",
                "temperature changed by more than 5 C since calibration",
                exit_code=EXIT_STATE_CONFLICT,
                details={"temperature_delta_c": temperature_delta},
            )
        hardware = core.heartbeat_spur_correction()
        expected_hardware = {
            "active_spur_id": int(spur["spur_id"]),
            "active_phase_step": int(result["phase_step"]) & ((1 << 48) - 1),
            "active_profile_id": int(str(result["profile_id"]), 0),
            "active_model_crc32": int(result["model_crc32"]) & 0xFFFF_FFFF,
            "active_generation": int(result["generation"]) & 0xFFFF_FFFF,
        }
        identity_mismatch = {
            key: {"expected": expected, "actual": hardware.get(key)}
            for key, expected in expected_hardware.items()
            if int(hardware.get(key, -1)) != expected
        }
        if not bool(hardware.get("active")) or identity_mismatch:
            raise HelperError(
                "SPUR_CORRECTION_HARDWARE_INACTIVE",
                "the credential is valid but the active hardware model identity does not match",
                exit_code=EXIT_STATE_CONFLICT,
                details={"hardware": hardware, "identity_mismatch": identity_mismatch},
            )
        return {
            "supported": True,
            "active": True,
            "warning": "TEMPERATURE_DELTA_GT_2C" if temperature_delta is not None and temperature_delta > 2.0 else None,
            "temperature_delta_c": temperature_delta,
            "credential": result,
            "hardware": hardware,
        }

    step = phase_step_u48(float(spur["offset_hz"]))
    generation = int(time.time_ns() & 0xFFFF_FFFF) or 1
    core.load_spur_correction_shadow(
        spur_id=int(spur["spur_id"]),
        phase_step=step,
        phase_seed=0,
        coefficients_q8_16=[(0, 0)] * 8,
        profile_id=SPUR_PROFILE_ID,
        model_crc32=0,
        generation=generation,
        enable=False,
        in_band=True,
        bypass=True,
        phase_reload=False,
    )
    hardware = core.commit_spur_correction()
    return {
        "supported": True,
        "active": False,
        "warning": "ADC_INTERLEAVE_SPUR_UNCORRECTED",
        "window": window,
        "spur": spur,
        "hardware": hardware,
    }


def _require_output_load_start_authorization(
    controller: FEngineController, body: dict[str, Any]
) -> dict[str, Any]:
    status = _output_load_status_snapshot(controller)
    requested = body.get("output_load_transaction_id")
    if status.get("state") == OUTPUT_LOAD_PRODUCTION:
        if requested not in (None, ""):
            raise HelperError(
                "OUTPUT_LOAD_TRANSACTION_UNEXPECTED",
                "output_load_transaction_id is only valid during an active output-load intervention",
                exit_code=EXIT_STATE_CONFLICT,
            )
        return status
    if status.get("state") != OUTPUT_LOAD_ACTIVE or not status.get("transaction_valid"):
        raise HelperError(
            "OUTPUT_LOAD_RESTORE_REQUIRED",
            "output-load state requires restore before START",
            exit_code=EXIT_STATE_CONFLICT,
            details={"output_load": status},
        )
    if status.get("consumed"):
        raise HelperError(
            "OUTPUT_LOAD_TRANSACTION_CONSUMED",
            "output-load transaction was already consumed",
            exit_code=EXIT_STATE_CONFLICT,
        )
    if not requested or str(requested) != str(status.get("output_load_transaction_id")):
        raise HelperError(
            "OUTPUT_LOAD_TRANSACTION_REQUIRED",
            "START requires the matching output_load_transaction_id",
            exit_code=EXIT_STATE_CONFLICT,
            details={"output_load": status},
        )
    if not status.get("integrity_ok"):
        raise HelperError(
            "OUTPUT_LOAD_INTEGRITY_FAILED",
            "output-load protected state changed",
            exit_code=EXIT_STATE_CONFLICT,
            details={"output_load": status},
        )
    _persist_output_load_state({**_load_output_load_state(), "consumed": True})
    return status


def _require_rfdc_power_start_authorization(
    controller: FEngineController, body: dict[str, Any]
) -> dict[str, Any]:
    state = _load_rfdc_power_state()
    requested = body.get("rfdc_power_transaction_id")
    if state.get("state") == RFDC_POWER_NORMAL:
        if requested not in (None, ""):
            raise HelperError(
                "RFDC_POWER_TRANSACTION_UNEXPECTED",
                "rfdc_power_transaction_id is only valid while DAC tiles are shut down",
                exit_code=EXIT_STATE_CONFLICT,
            )
        return state
    live = controller.require_core().read_rfdc_tile_power_status()
    if (
        state.get("state") != RFDC_POWER_DAC_SHUTDOWN
        or not state.get("transaction_valid")
        or int(live.get("adc_enabled_mask", 0)) != 0xF
        or int(live.get("dac_enabled_mask", -1)) != 0
    ):
        raise HelperError(
            "RFDC_POWER_RESTORE_REQUIRED",
            "RFDC power state is not a valid DAC-shutdown intervention",
            exit_code=EXIT_STATE_CONFLICT,
            details={"rfdc_power": state, "live": live},
        )
    if state.get("consumed"):
        raise HelperError(
            "RFDC_POWER_TRANSACTION_CONSUMED",
            "RFDC power transaction was already consumed",
            exit_code=EXIT_STATE_CONFLICT,
        )
    if not requested or str(requested) != str(state.get("rfdc_power_transaction_id")):
        raise HelperError(
            "RFDC_POWER_TRANSACTION_REQUIRED",
            "START requires the matching rfdc_power_transaction_id",
            exit_code=EXIT_STATE_CONFLICT,
            details={"rfdc_power": state},
        )
    _persist_rfdc_power_state({**state, "consumed": True, "live": live})
    return {**state, "live": live}


def _start(request: dict[str, Any]) -> dict[str, Any]:
    body = _body(request)
    controller = _controller(request)
    _expected_board(controller, body)
    ocb1 = _require_ocb1_start_authorization(controller, body)
    clock_diagnostic = _require_clock_start_authorization(controller, body)
    output_load = _require_output_load_start_authorization(controller, body)
    rfdc_power = _require_rfdc_power_start_authorization(controller, body)
    spur_correction = _require_spur_correction_start_authorization(
        controller, body, _bitstream(request)
    )
    watchdog = _require_reference_watchdog_ready(_bitstream(request))
    status = controller.start_immediate()
    return {
        "started": True,
        "reference_watchdog": watchdog,
        "ocb1": ocb1,
        "clock_diagnostic": clock_diagnostic,
        "output_load": output_load,
        "rfdc_power": rfdc_power,
        "adc_interleave_spur_correction": spur_correction,
        "status": status,
        "snapshot": _status_snapshot(controller),
    }


def _sync_prepare(request: dict[str, Any]) -> dict[str, Any]:
    body = _body(request)
    controller = _controller(request)
    _expected_board(controller, body)
    ocb1 = _require_ocb1_start_authorization(controller, body)
    clock_diagnostic = _require_clock_start_authorization(controller, body)
    output_load = _require_output_load_start_authorization(controller, body)
    rfdc_power = _require_rfdc_power_start_authorization(controller, body)
    spur_correction = _require_spur_correction_start_authorization(
        controller, body, _bitstream(request)
    )
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
    return {
        "prepared": True,
        "ocb1": ocb1,
        "clock_diagnostic": clock_diagnostic,
        "output_load": output_load,
        "rfdc_power": rfdc_power,
        "adc_interleave_spur_correction": spur_correction,
        "sync": status,
        "snapshot": _status_snapshot(controller),
    }


def _sync_arm(request: dict[str, Any]) -> dict[str, Any]:
    body = _body(request)
    controller = _controller(request)
    _expected_board(controller, body)
    ocb1 = _require_ocb1_start_authorization(controller, body)
    clock_diagnostic = _require_clock_start_authorization(controller, body)
    output_load = _load_output_load_state()
    rfdc_power = _load_rfdc_power_state()
    spur_correction = _require_spur_correction_start_authorization(
        controller, body, _bitstream(request)
    )
    watchdog = _require_reference_watchdog_ready(_bitstream(request))
    status = controller.require_core().arm_scheduled_sync()
    return {
        "armed": True,
        "reference_watchdog": watchdog,
        "ocb1": ocb1,
        "clock_diagnostic": clock_diagnostic,
        "output_load": output_load,
        "rfdc_power": rfdc_power,
        "adc_interleave_spur_correction": spur_correction,
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
    clock_diagnostic = _invalidate_clock_diagnostic_state("STOP")
    return {
        "stopped": True,
        "status": status,
        "clock_diagnostic": clock_diagnostic,
        "snapshot": _status_snapshot(controller),
    }


def _reset(request: dict[str, Any]) -> dict[str, Any]:
    body = _body(request)
    controller = _controller(request)
    _expected_board(controller, body)
    _invalidate_ocb1_state("RFDC_RESET")
    _invalidate_clock_diagnostic_state("RFDC_RESET")
    _invalidate_output_load_state("RFDC_RESET")
    _invalidate_rfdc_power_state("RFDC_RESET")
    _invalidate_spur_correction_state("RFDC_RESET")
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
    "calibration-status": _calibration_status,
    "calibration-freeze": _calibration_freeze,
    "calibration-unfreeze": _calibration_unfreeze,
    "calibration-preview": _calibration_preview,
    "calibration-train-freeze": _calibration_train_freeze,
    "ocb1-status": _ocb1_status,
    "ocb1-snapshot-override": _ocb1_snapshot_override,
    "ocb1-release": _ocb1_release,
    "clock-diagnostic-status": _clock_diagnostic_status,
    "clock-diagnostic-prepare": _clock_diagnostic_prepare,
    "clock-diagnostic-restore": _clock_diagnostic_restore,
    "output-load-status": lambda request: _output_load_status_snapshot(_controller(request)),
    "output-load-apply": _output_load_apply,
    "output-load-restore": _output_load_restore,
    "rfdc-power-status": _rfdc_power_status,
    "rfdc-power-dac-shutdown": _rfdc_power_dac_shutdown,
    "rfdc-power-restore": _rfdc_power_restore,
    "spur-correction-status": _spur_correction_status,
    "spur-correction-calibrate": _spur_correction_calibrate,
    "spur-correction-tracker-mode": _spur_correction_tracker_mode,
    "spur-correction-disable": _spur_correction_disable,
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
                    "message": "command must be a supported status, calibration, configure, stream, sync, reset, or DAC operation",
                },
            },
            sys.stdout,
        )
        sys.stdout.write("\n")
        return EXIT_INVALID
    try:
        request = _read_request()
        with contextlib.redirect_stdout(sys.stderr):
            with _configure_hardware_guard(
                args[0]
                in (
                    "configure",
                    "clock-diagnostic-prepare",
                    "clock-diagnostic-restore",
                    "rfdc-power-dac-shutdown",
                    "rfdc-power-restore",
                )
            ):
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
