#!/usr/bin/env python3
"""Resident Stage 34 external-reference safety watchdog.

The T510 board does not route LMK04828 STATUS_LD1/STATUS_LD2 into the FPGA.
Consequently the PL scheduler cannot distinguish a healthy external 10 MHz
reference from LMK holdover while PLL2 and the RFDC data clocks keep running.

This process polls the LMK PLL lock registers through SPI.  While any science
stream is active, confirmed PLL unlock (or a sustained inability to read the
LMK) directly pulses the existing FPGA STOP/flush control.  A fault remains
latched until a fresh CONFIGURE updates PYNQ's active-bitstream identity.
"""

from __future__ import annotations

import argparse
from collections import deque
import contextlib
from dataclasses import dataclass
from datetime import datetime
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import secrets
import sys
import time
from typing import Any

from python.t510_ams import aggregate_ams_snapshots, read_ams_snapshot
from python.t510_clock import T510ClockController


SCHEMA_VERSION = 1
EXPECTED_CORE_VERSION = 0x0001_0034
DEFAULT_STATE_PATH = Path("/run/t510-ref-watchdog.json")
DEFAULT_LOCK_PATH = Path("/run/t510-ref-watchdog.lock")
DEFAULT_CONFIGURE_LOCK_PATH = Path("/run/t510-configure.lock")
DEFAULT_CLOCK_DIAGNOSTIC_STATE_PATH = Path("/run/t510-clock-diagnostic.json")
DEFAULT_OUTPUT_LOAD_STATE_PATH = Path("/run/t510-output-load.json")
DEFAULT_RFDC_POWER_STATE_PATH = Path("/run/t510-rfdc-power.json")
DEFAULT_POWER_THERMAL_TELEMETRY_PATH = Path("/run/t510-power-thermal.jsonl")
DEFAULT_SPUR_CORRECTION_STATE_PATH = Path("/run/t510-spur-correction.json")
FPGA_MANAGER_STATE_PATH = Path("/sys/class/fpga_manager/fpga0/state")
CALIBRATION_OBSERVATION_INTERVAL_SECONDS = 0.2
AMS_SAMPLE_INTERVAL_SECONDS = 0.2
AMS_AGGREGATE_INTERVAL_SECONDS = 1.0
POWER_THERMAL_RING_CAPACITY_SECONDS = 4096
POWER_THERMAL_RING_COMPACTION_SLACK = 256


def _periodic_schedule_due(
    now: float, anchor: float, interval_seconds: float
) -> tuple[bool, float]:
    """Advance a periodic deadline without accumulating callback duration.

    Assigning ``anchor = now`` after every sample turns a nominal one-second
    task into ``1 second + callback/loop jitter``.  Over a ten-minute science
    run that previously yielded only 559 observations.  Anchoring to the
    ideal cadence makes a late sample pull the next deadline forward again;
    genuinely missed whole periods are skipped rather than backfilled.
    """

    if not math.isfinite(anchor):
        return True, now
    elapsed = now - anchor
    if elapsed + 1.0e-9 < interval_seconds:
        return False, anchor
    periods = max(1, int((elapsed + 1.0e-9) // interval_seconds))
    return True, anchor + periods * interval_seconds


def _timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def _sha1(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _expected_core_version_for_bitfile(bitfile: Path) -> int:
    manifest = bitfile.resolve().with_name("t510_fengine.manifest.txt")
    try:
        rows = dict(
            line.split("=", 1)
            for line in manifest.read_text(encoding="utf-8").splitlines()
            if "=" in line
        )
        return int(rows["core_version"], 0)
    except (OSError, KeyError, ValueError):
        return EXPECTED_CORE_VERSION


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.chmod(temporary, 0o644)
    temporary.replace(path)


def _maximum_ams_temperature(telemetry: dict[str, Any]) -> float | None:
    values = [
        float(row["mean"])
        for row in dict(telemetry.get("temperatures_c", {})).values()
        if isinstance(row, dict) and row.get("mean") is not None
    ]
    return max(values) if values else None


class BoundedJsonlRing:
    """Append one-second evidence cheaply while retaining a bounded window."""

    def __init__(
        self,
        path: Path,
        *,
        capacity: int = POWER_THERMAL_RING_CAPACITY_SECONDS,
        compaction_slack: int = POWER_THERMAL_RING_COMPACTION_SLACK,
    ) -> None:
        if capacity < 1 or compaction_slack < 1:
            raise ValueError("telemetry ring capacity and compaction slack must be positive")
        self.path = path
        self.capacity = int(capacity)
        self.compaction_slack = int(compaction_slack)
        self.epoch_id = secrets.token_hex(16)
        self.sequence = 0
        self._encoded: deque[str] = deque(maxlen=self.capacity)
        self._records_since_compaction = 0
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("", encoding="utf-8")
        os.chmod(self.path, 0o644)

    def append(self, value: dict[str, Any]) -> dict[str, Any]:
        self.sequence += 1
        row = {
            **value,
            "schema_version": 1,
            "epoch_id": self.epoch_id,
            "sequence": self.sequence,
        }
        encoded = json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
        self._encoded.append(encoded)
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(encoded)
            stream.flush()
        self._records_since_compaction += 1
        if (
            self.sequence > self.capacity
            and self._records_since_compaction >= self.compaction_slack
        ):
            temporary = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
            temporary.write_text("".join(self._encoded), encoding="utf-8")
            os.chmod(temporary, 0o644)
            temporary.replace(self.path)
            self._records_since_compaction = 0
        return row


@dataclass
class WatchdogPolicy:
    """Pure confirmation policy, separated from PYNQ/SPI for unit testing."""

    unlock_confirmations: int = 2
    spi_error_confirmations: int = 5
    pll1_unlock_count: int = 0
    pll2_unlock_count: int = 0
    spi_error_count: int = 0
    fault_latched: bool = False

    def clear_for_fresh_configure(self) -> None:
        self.pll1_unlock_count = 0
        self.pll2_unlock_count = 0
        self.spi_error_count = 0
        self.fault_latched = False

    def observe(
        self,
        *,
        streaming: bool,
        pll1_lock: int | None,
        pll2_lock: int | None,
        spi_error: bool = False,
    ) -> str | None:
        if self.fault_latched:
            return None
        if not streaming:
            self.pll1_unlock_count = 0
            self.pll2_unlock_count = 0
            self.spi_error_count = 0
            return None
        if spi_error:
            self.spi_error_count += 1
            if self.spi_error_count >= self.spi_error_confirmations:
                self.fault_latched = True
                return "LMK_SPI_UNAVAILABLE"
            return None

        self.spi_error_count = 0
        self.pll1_unlock_count = (
            self.pll1_unlock_count + 1 if int(pll1_lock or 0) == 0 else 0
        )
        self.pll2_unlock_count = (
            self.pll2_unlock_count + 1 if int(pll2_lock or 0) == 0 else 0
        )
        if self.pll1_unlock_count >= self.unlock_confirmations:
            self.fault_latched = True
            return "LMK_PLL1_UNLOCKED"
        if self.pll2_unlock_count >= self.unlock_confirmations:
            self.fault_latched = True
            return "LMK_PLL2_UNLOCKED"
        return None


class ReferenceWatchdog:
    def __init__(
        self,
        *,
        bitfile: Path,
        state_path: Path,
        interval_seconds: float,
        stop_timeout_seconds: float,
        unlock_confirmations: int,
        spi_error_confirmations: int,
        configure_lock_path: Path = DEFAULT_CONFIGURE_LOCK_PATH,
        expected_core_version: int = EXPECTED_CORE_VERSION,
        clock_diagnostic_state_path: Path = DEFAULT_CLOCK_DIAGNOSTIC_STATE_PATH,
        output_load_state_path: Path = DEFAULT_OUTPUT_LOAD_STATE_PATH,
        rfdc_power_state_path: Path = DEFAULT_RFDC_POWER_STATE_PATH,
        spur_correction_state_path: Path = DEFAULT_SPUR_CORRECTION_STATE_PATH,
        power_thermal_telemetry_path: Path | None = None,
    ) -> None:
        self.bitfile = bitfile.resolve()
        self.expected_bitstream_sha1 = _sha1(self.bitfile)
        self.state_path = state_path
        self.interval_seconds = interval_seconds
        self.stop_timeout_seconds = stop_timeout_seconds
        self.configure_lock_path = configure_lock_path
        self.expected_core_version = int(expected_core_version)
        self.clock_diagnostic_state_path = clock_diagnostic_state_path
        self.output_load_state_path = output_load_state_path
        self.rfdc_power_state_path = rfdc_power_state_path
        self.spur_correction_state_path = spur_correction_state_path
        self.power_thermal_ring = BoundedJsonlRing(
            power_thermal_telemetry_path
            if power_thermal_telemetry_path is not None
            else state_path.with_name("t510-power-thermal.jsonl")
        )
        self.clock = T510ClockController()
        self.policy = WatchdogPolicy(
            unlock_confirmations=unlock_confirmations,
            spi_error_confirmations=spi_error_confirmations,
        )
        self.controller: Any = None
        self.core: Any = None
        self.pl_identity: str | None = None
        self.service_started_at = _timestamp()
        self.stop_requested = False
        self.last_fault: dict[str, Any] | None = None
        self.last_error: str | None = None
        self.lock_status: dict[str, Any] | None = None
        self.hardware: dict[str, Any] = {
            "streaming": False,
            "selected": False,
            "generation": 0,
            "time_packets": 0,
            "spec_packets": 0,
        }
        self.calibration_blocks: list[tuple[int, int]] | None = None
        self.calibration_observation: dict[str, Any] = {
            "supported": False,
            "error": "NOT_YET_SAMPLED",
            "captured_at_unix_ms": None,
            "temperature_c": None,
        }
        self.last_calibration_observation_monotonic = float("-inf")
        self.ams_samples: list[dict[str, Any]] = []
        self.ams_telemetry: dict[str, Any] = {
            "supported": False,
            "sample_count": 0,
            "sample_rate_hz": 5.0,
            "temperatures_c": {},
            "voltages_v": {},
            "errors": ["NOT_YET_SAMPLED"],
        }
        self.last_ams_sample_monotonic = float("-inf")
        self.last_ams_aggregate_monotonic = time.monotonic()
        self.telemetry_record_due = False
        self.last_power_thermal_record: dict[str, Any] | None = None
        self.spur_tracker: dict[str, Any] = {
            "supported": self.expected_core_version >= 0x0001_0036,
            "state": "IDLE",
            "last_update_unix_ms": None,
            "last_coefficient_crc32": None,
            "last_error": None,
        }
        self.spur_tracker_fault_reason: str | None = None
        self._last_spur_coefficients: tuple[tuple[int, int], ...] | None = None
        self._load_previous_state()
        if self.expected_core_version >= 0x0001_0036:
            state = _read_json(self.spur_correction_state_path)
            if isinstance(state, dict) and bool(state.get("credential_valid")):
                _write_json_atomic(
                    self.spur_correction_state_path,
                    {
                        **state,
                        "calibration_state": "INVALID",
                        "spur_correction_id": None,
                        "credential_valid": False,
                        "invalid_reason": "SPUR_TRACKER_SERVICE_RESTART",
                        "updated_at_unix_ms": time.time_ns() // 1_000_000,
                    },
                )

    def _load_previous_state(self) -> None:
        previous = _read_json(self.state_path)
        if previous is None:
            return
        self.last_fault = (
            dict(previous["last_fault"])
            if isinstance(previous.get("last_fault"), dict)
            else None
        )
        if bool(previous.get("fault_latched", False)):
            self.policy.fault_latched = True
        previous_identity = previous.get("pl_identity")
        self.pl_identity = (
            str(previous_identity) if previous_identity is not None else None
        )

    @staticmethod
    def _pynq_state_path() -> Path:
        from pynq.pl_server import global_state as pynq_global_state

        return Path(pynq_global_state.STATE_DIR) / "global_pl_state.json"

    def _read_pl_identity(self) -> tuple[str, dict[str, Any]]:
        manager_state = FPGA_MANAGER_STATE_PATH.read_text(
            encoding="ascii"
        ).strip().lower()
        if manager_state != "operating":
            raise RuntimeError(f"FPGA_MANAGER_{manager_state.upper()}")
        state_path = self._pynq_state_path()
        state = _read_json(state_path)
        if state is None:
            raise RuntimeError("PYNQ_ACTIVE_BITSTREAM_STATE_UNAVAILABLE")
        active_sha1 = str(state.get("bitfile_hash", "")).strip().lower()
        if active_sha1 != self.expected_bitstream_sha1:
            raise RuntimeError(
                "ACTIVE_BITSTREAM_MISMATCH:"
                f"expected={self.expected_bitstream_sha1}:active={active_sha1}"
            )
        timestamp = str(state.get("timestamp", "")).strip()
        if not timestamp:
            raise RuntimeError("PYNQ_ACTIVE_BITSTREAM_TIMESTAMP_MISSING")
        return f"{active_sha1}:{timestamp}", state

    def _connect(self, identity: str) -> None:
        from python.t510_control import FEngineController

        controller = FEngineController(
            self.bitfile,
            expected_core_version=self.expected_core_version,
        )
        status = controller.connect(download=False)
        version = int(status.get("core_version", 0))
        if version != self.expected_core_version:
            raise RuntimeError(
                "CORE_VERSION_MISMATCH:"
                f"expected=0x{self.expected_core_version:08x}:actual=0x{version:08x}"
            )
        old_identity = self.pl_identity
        self.controller = controller
        self.core = controller.require_core()
        self.calibration_blocks = None
        self.last_calibration_observation_monotonic = float("-inf")
        self.pl_identity = identity
        if old_identity is not None and identity != old_identity:
            self.policy.clear_for_fresh_configure()
            print(
                f"REFERENCE_WATCHDOG_FRESH_CONFIGURE identity={identity}",
                flush=True,
            )

    def _sample_ams_if_due(self) -> None:
        now = time.monotonic()
        sample_due, sample_anchor = _periodic_schedule_due(
            now, self.last_ams_sample_monotonic, AMS_SAMPLE_INTERVAL_SECONDS
        )
        if sample_due:
            self.ams_samples.append(read_ams_snapshot())
            self.last_ams_sample_monotonic = sample_anchor
        aggregate_due, aggregate_anchor = _periodic_schedule_due(
            now, self.last_ams_aggregate_monotonic, AMS_AGGREGATE_INTERVAL_SECONDS
        )
        if aggregate_due and self.ams_samples:
            self.ams_telemetry = aggregate_ams_snapshots(self.ams_samples)
            self.ams_telemetry["captured_at_unix_ms"] = time.time_ns() // 1_000_000
            self.ams_samples.clear()
            self.last_ams_aggregate_monotonic = aggregate_anchor
            self.telemetry_record_due = True

    def _append_power_thermal_telemetry_if_due(self) -> None:
        if not self.telemetry_record_due:
            return
        self.telemetry_record_due = False
        tile_power: dict[str, Any]
        try:
            if self.core is None or not hasattr(self.core, "read_rfdc_tile_power_status"):
                raise RuntimeError("RFDC_TILE_POWER_API_UNAVAILABLE")
            tile_power = dict(self.core.read_rfdc_tile_power_status())
        except Exception as exc:  # noqa: BLE001 - evidence carries the read failure
            tile_power = {
                "supported": False,
                "error": f"{type(exc).__name__}:{exc}",
            }
        calibration = self.calibration_observation
        coefficients = dict(calibration.get("coefficient_sha256", {}))
        ocb1_dft = {
            str(row.get("adc")): dict(row.get("ocb1_diagnostics", {})).get("dft", [])
            for row in calibration.get("channels", [])
            if isinstance(row, dict)
        }
        self.last_power_thermal_record = self.power_thermal_ring.append(
            {
                "captured_at": _timestamp(),
                "captured_at_unix_ms": time.time_ns() // 1_000_000,
                "service_started_at": self.service_started_at,
                "pl_identity": self.pl_identity,
                "hardware": self.hardware,
                "lock_status": self.lock_status,
                "ams": self.ams_telemetry,
                "rfdc_tile_power": tile_power,
                "calibration": {
                    "supported": calibration.get("supported"),
                    "error": calibration.get("error"),
                    "frozen_adc_mask": calibration.get("frozen_adc_mask"),
                    "coefficient_sha256": coefficients,
                    "ocb1_dft": ocb1_dft,
                },
                "output_load": _read_json(self.output_load_state_path),
                "rfdc_power": _read_json(self.rfdc_power_state_path),
            }
        )

    def _read_hardware_minimal(self) -> dict[str, Any]:
        if self.core is None:
            raise RuntimeError("PL_CORE_NOT_CONNECTED")
        raw_status = int(self.core.ctrl.read(self.core.regs.STATUS))
        streaming = bool((raw_status >> 1) & 0x1)
        selected = False
        generation = 0
        sync_state = 0
        if streaming:
            sync = self.core.read_scheduled_sync_status()
            selected = bool(sync.get("selected", False))
            generation = int(sync.get("active_generation", 0))
            sync_state = int(sync.get("state", 0))
        result = {
            "streaming": streaming,
            "selected": selected,
            "generation": generation,
            "sync_state": sync_state,
            "time_packets": int(
                self.core.ctrl.read(self.core.regs.TIME_PACKET_COUNT)
            ),
            "spec_packets": int(
                self.core.ctrl.read(self.core.regs.SPEC_PACKET_COUNT)
            ),
        }
        if self.expected_core_version >= 0x0001_0035:
            result["sysref_capture_counts"] = {
                "pl_160mhz": int(
                    self.core.ctrl.read(self.core.regs.SYSREF_PL_EDGE_COUNT)
                ),
                "adc_80mhz": int(
                    self.core.ctrl.read(self.core.regs.SYSREF_ADC_EDGE_COUNT)
                ),
                "dac_80mhz": int(
                    self.core.ctrl.read(self.core.regs.SYSREF_DAC_EDGE_COUNT)
                ),
            }
        return result

    def _observe_sysref_capture(
        self,
        previous: dict[str, Any],
        current: dict[str, Any],
    ) -> str | None:
        """Trip if an MTS-only profile resumes physical SYSREF in science."""
        if self.expected_core_version < 0x0001_0035:
            return None
        if not bool(previous.get("streaming")) or not bool(current.get("streaming")):
            return None
        clock_state = _read_json(self.clock_diagnostic_state_path)
        if not isinstance(clock_state, dict) or str(clock_state.get("sysref_policy")) != "mts_only":
            return None
        before = previous.get("sysref_capture_counts")
        after = current.get("sysref_capture_counts")
        if not isinstance(before, dict) or not isinstance(after, dict):
            return "SYSREF_CAPTURE_EVIDENCE_UNAVAILABLE"
        deltas = {
            name: (int(after.get(name, 0)) - int(before.get(name, 0))) & 0xFFFF_FFFF
            for name in ("pl_160mhz", "adc_80mhz", "dac_80mhz")
        }
        current["sysref_capture_count_deltas"] = deltas
        if any(value != 0 for value in deltas.values()):
            return "SYSREF_CAPTURE_DURING_SCIENCE"
        return None

    def _sample_calibration_if_due(self) -> None:
        now = time.monotonic()
        due, anchor = _periodic_schedule_due(
            now,
            self.last_calibration_observation_monotonic,
            CALIBRATION_OBSERVATION_INTERVAL_SECONDS,
        )
        if not due:
            return
        self.last_calibration_observation_monotonic = anchor
        captured_at_unix_ms = time.time_ns() // 1_000_000
        try:
            if self.core is None or not hasattr(
                self.core, "read_adc_calibration_status"
            ):
                raise RuntimeError("RFDC_CALIBRATION_API_UNAVAILABLE")
            if self.calibration_blocks is None:
                self.calibration_blocks = list(self.core._adc_calibration_blocks())
            observation = dict(
                self.core.read_adc_calibration_status(
                    require=True,
                    _blocks=self.calibration_blocks,
                )
            )
            observation.update(
                {
                    "captured_at_unix_ms": captured_at_unix_ms,
                    "temperature_c": _maximum_ams_temperature(self.ams_telemetry),
                    "ams": self.ams_telemetry,
                    "error": None,
                }
            )
            self.calibration_observation = observation
            self._update_spur_tracker(observation)
        except Exception as exc:  # noqa: BLE001 - observation failure is reported, not hidden
            self.calibration_observation = {
                "supported": False,
                "error": f"{type(exc).__name__}:{exc}",
                "captured_at_unix_ms": captured_at_unix_ms,
                "temperature_c": _maximum_ams_temperature(self.ams_telemetry),
                "ams": self.ams_telemetry,
            }
            self._handle_spur_tracker_error(exc)
            self._handle_spur_tracker_error(exc)

    def _persist_spur_tracker_state(
        self, state: dict[str, Any], **updates: Any
    ) -> dict[str, Any]:
        value = {
            **state,
            **updates,
            "updated_at_unix_ms": time.time_ns() // 1_000_000,
        }
        _write_json_atomic(self.spur_correction_state_path, value)
        return value

    @staticmethod
    def _ocb1_dft_from_observation(
        observation: dict[str, Any], adc: int, k: int
    ) -> complex:
        channels = {
            int(row["adc"]): row
            for row in observation.get("channels", [])
            if isinstance(row, dict) and row.get("adc") is not None
        }
        diagnostics = dict(channels[int(adc)].get("ocb1_diagnostics", {}))
        row = next(
            item
            for item in diagnostics.get("dft", [])
            if int(item.get("k", -1)) == int(k)
        )
        return complex(float(row["real"]), float(row["imag"]))

    def _handle_spur_tracker_error(self, exc: Exception) -> None:
        if self.expected_core_version < 0x0001_0036:
            return
        state = _read_json(self.spur_correction_state_path)
        if not isinstance(state, dict) or not bool(state.get("credential_valid")):
            return
        reason = f"SPUR_TRACKER:{type(exc).__name__}:{exc}"
        self.spur_tracker.update({"state": "FAULT", "last_error": reason})
        self._persist_spur_tracker_state(
            state,
            calibration_state="INVALID",
            spur_correction_id=None,
            credential_valid=False,
            invalid_reason=reason,
            tracker=self.spur_tracker,
        )
        # A valid correction credential means this is a corrected science
        # session.  Even if hardware has already failed itself to bypass (for
        # example on tracker timeout), the stream must STOP instead of silently
        # continuing with the uncorrected flag.
        if bool(self.hardware.get("streaming")):
            self.spur_tracker_fault_reason = reason
        else:
            try:
                self.core.disable_spur_correction(clear_errors=False)
            except Exception:
                pass

    def _update_spur_tracker(self, observation: dict[str, Any]) -> None:
        """Refresh v36 coefficients from read-only dynamic OCB1 at 5 Hz."""

        if self.expected_core_version < 0x0001_0036 or self.core is None:
            return
        state = _read_json(self.spur_correction_state_path)
        if not isinstance(state, dict) or not bool(state.get("credential_valid")):
            self.spur_tracker.update({"state": "IDLE", "last_error": None})
            return
        try:
            from python.t510_spur_correction import (
                LaneSpurModel,
                coefficient_crc32,
                load_model,
                quantize_q8_16,
            )

            result = dict(state.get("result") or {})
            model = load_model(str(result["model_path"]))
            if str(model.get("sha256")) != str(result.get("model_sha256")):
                raise RuntimeError("credential/model SHA256 mismatch")
            if int(observation.get("frozen_adc_mask", -1)) != 0:
                raise RuntimeError("ADC calibration freeze mask changed from 0x00")
            spur = dict(result["spur"])
            k = int(spur["ocb1_dft_k"])
            lane_models = [LaneSpurModel.from_json(row) for row in model["lanes"]]
            if len(lane_models) != 8:
                raise RuntimeError("frozen spur model does not contain eight lanes")
            tracker_mode = str(state.get("tracker_mode", "dynamic"))
            if tracker_mode not in ("static_c0", "dynamic"):
                raise RuntimeError(f"unsupported spur tracker mode {tracker_mode!r}")
            coefficients = tuple(
                quantize_q8_16(
                    lane_models[adc].c0
                    if tracker_mode == "static_c0"
                    else lane_models[adc].tracked(
                        self._ocb1_dft_from_observation(observation, adc, k)
                    )
                )
                for adc in range(8)
            )
            temperature = observation.get("temperature_c")
            calibrated_temperature = result.get("temperature_c")
            delta_c = (
                abs(float(temperature) - float(calibrated_temperature))
                if temperature is not None and calibrated_temperature is not None
                else None
            )
            if delta_c is not None and delta_c > 5.0:
                raise RuntimeError(f"temperature delta {delta_c:.3f} C exceeds 5 C")

            load = None
            commit = None
            if coefficients != self._last_spur_coefficients:
                load = self.core.load_spur_correction_shadow(
                    spur_id=int(spur["spur_id"]),
                    phase_step=int(result["phase_step"]),
                    phase_seed=0,
                    coefficients_q8_16=coefficients,
                    profile_id=int(str(result["profile_id"]), 0),
                    model_crc32=int(result["model_crc32"]),
                    generation=int(result["generation"]),
                    enable=True,
                    in_band=True,
                    bypass=False,
                    phase_reload=False,
                )
                commit = self.core.commit_spur_correction()
                self._last_spur_coefficients = coefficients
            hardware = self.core.heartbeat_spur_correction()
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
            if bool(self.hardware.get("streaming")) and (
                not bool(hardware.get("active")) or identity_mismatch
            ):
                raise RuntimeError(
                    "hardware correction became inactive or changed identity: "
                    f"hardware={hardware} mismatch={identity_mismatch}"
                )
            now_ms = time.time_ns() // 1_000_000
            self.spur_tracker = {
                "supported": True,
                "state": "STATIC_C0" if tracker_mode == "static_c0" else "TRACKING",
                "mode": tracker_mode,
                "last_update_unix_ms": now_ms,
                "last_coefficient_crc32": coefficient_crc32(coefficients),
                "temperature_delta_c": delta_c,
                "temperature_warning": bool(delta_c is not None and delta_c > 2.0),
                "coefficient_changed": load is not None,
                "hardware": hardware,
                "commit": commit,
                "last_error": None,
            }
            self._persist_spur_tracker_state(state, tracker=self.spur_tracker)
            self.spur_tracker_fault_reason = None
        except Exception as exc:
            self._handle_spur_tracker_error(exc)

    def _trip(self, reason: str) -> None:
        if self.core is None:
            raise RuntimeError("cannot stop without a connected PL core")
        detected_ns = time.monotonic_ns()
        before = dict(self.hardware)
        before["lock_status"] = dict(self.lock_status or {})
        print(
            f"REFERENCE_WATCHDOG_TRIP reason={reason} "
            f"generation={before.get('generation')} "
            f"time_packets={before.get('time_packets')} "
            f"spec_packets={before.get('spec_packets')}",
            flush=True,
        )
        self.core.stop()
        # A tracker fault is a science-integrity failure.  The DAC mask and all
        # amplitude registers are explicitly cleared, not merely hidden by the
        # global enable bit.
        try:
            self.core.set_dac_enable_mask(0)
            self.core.set_dac_tone(enable=False, amplitude=0, phase_step=0)
            for channel in range(8):
                self.core.set_dac_tone(
                    enable=False,
                    amplitude=0,
                    phase_step=0,
                    channel=channel,
                    phase0=0,
                    phase_inject=0,
                )
            if self.expected_core_version >= 0x0001_0036:
                self.core.disable_spur_correction(clear_errors=False)
        except Exception as exc:  # noqa: BLE001 - retain stop evidence below
            self.last_error = f"FAULT_CLEANUP:{type(exc).__name__}:{exc}"
        stopped_ns: int | None = None
        deadline = time.monotonic() + self.stop_timeout_seconds
        last = dict(before)
        while time.monotonic() < deadline:
            raw_status = int(self.core.ctrl.read(self.core.regs.STATUS))
            streaming = bool((raw_status >> 1) & 0x1)
            last = {
                "streaming": streaming,
                "time_packets": int(
                    self.core.ctrl.read(self.core.regs.TIME_PACKET_COUNT)
                ),
                "spec_packets": int(
                    self.core.ctrl.read(self.core.regs.SPEC_PACKET_COUNT)
                ),
            }
            if not streaming:
                stopped_ns = time.monotonic_ns()
                break
            time.sleep(0.005)
        time.sleep(0.1)
        final_status = self.core.read_status()
        final_streaming = bool(final_status.get("streaming", 0))
        cmac_locked = bool(final_status.get("tx_cmac_source_mux_locked", 0))
        cmac_source = int(final_status.get("tx_cmac_mux_selected_source", 0))
        flush_clean = bool(
            final_status.get("rfdc_downstream_ready", 0)
            and not bool(final_status.get("tx_time_live_bridge_fifo_full", 0))
            and not (cmac_locked and cmac_source in (1, 2))
        )
        self.last_fault = {
            "reason": reason,
            "detected_at": _timestamp(),
            "detected_at_unix_ms": time.time_ns() // 1_000_000,
            "pl_identity": self.pl_identity,
            "before": before,
            "after": {
                **last,
                "flush_clean": flush_clean,
                "stream_accepting": bool(
                    final_streaming
                    and final_status.get("rfdc_downstream_ready", 0)
                    and not final_status.get("tx_time_live_bridge_fifo_full", 0)
                ),
            },
            "stop_latency_ms": (
                None
                if stopped_ns is None
                else round((stopped_ns - detected_ns) / 1_000_000.0, 3)
            ),
            "stop_ok": bool(
                stopped_ns is not None and not final_streaming and flush_clean
            ),
        }
        self.hardware = {
            **self.hardware,
            **last,
            "streaming": final_streaming,
        }

    def _state(self, *, mode: str, healthy: bool) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "service": "t510-ref-watchdog",
            "pid": os.getpid(),
            "service_started_at": self.service_started_at,
            "updated_at": _timestamp(),
            "updated_at_unix_ms": time.time_ns() // 1_000_000,
            "mode": mode,
            "healthy": bool(healthy),
            "fault_latched": bool(self.policy.fault_latched),
            "pl_identity": self.pl_identity,
            "active_bitstream_sha1": self.expected_bitstream_sha1,
            "expected_core_version": f"0x{self.expected_core_version:08x}",
            "poll_interval_ms": round(self.interval_seconds * 1000.0, 3),
            "unlock_confirmations_required": self.policy.unlock_confirmations,
            "spi_error_confirmations_required": self.policy.spi_error_confirmations,
            "pll1_unlock_count": self.policy.pll1_unlock_count,
            "pll2_unlock_count": self.policy.pll2_unlock_count,
            "spi_error_count": self.policy.spi_error_count,
            "lock_status": self.lock_status,
            "hardware": self.hardware,
            "calibration_observation_interval_ms": round(
                CALIBRATION_OBSERVATION_INTERVAL_SECONDS * 1000.0, 3
            ),
            "calibration_observation": self.calibration_observation,
            "spur_tracker": self.spur_tracker,
            "ams_sample_interval_ms": round(AMS_SAMPLE_INTERVAL_SECONDS * 1000.0, 3),
            "ams_telemetry": self.ams_telemetry,
            "power_thermal_telemetry": {
                "path": str(self.power_thermal_ring.path),
                "epoch_id": self.power_thermal_ring.epoch_id,
                "sequence": self.power_thermal_ring.sequence,
                "capacity_seconds": self.power_thermal_ring.capacity,
                "last_record": self.last_power_thermal_record,
            },
            "last_fault": self.last_fault,
            "last_error": self.last_error,
        }

    def _write_state(self, *, mode: str, healthy: bool) -> None:
        _write_json_atomic(self.state_path, self._state(mode=mode, healthy=healthy))

    def request_stop(self, _signum: int, _frame: Any) -> None:
        self.stop_requested = True

    @contextlib.contextmanager
    def _configure_read_guard(self):
        descriptor = os.open(
            self.configure_lock_path,
            os.O_CREAT | os.O_RDWR | os.O_CLOEXEC,
            0o644,
        )
        acquired = False
        try:
            try:
                fcntl.flock(
                    descriptor,
                    fcntl.LOCK_SH | fcntl.LOCK_NB,
                )
                acquired = True
            except BlockingIOError:
                pass
            yield acquired
        finally:
            if acquired:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    def _poll_once(self) -> tuple[str, bool]:
        mode = "ERROR"
        healthy = False
        try:
            identity, _active = self._read_pl_identity()
            if self.core is None or identity != self.pl_identity:
                self._connect(identity)
            previous_hardware = dict(self.hardware)
            self.hardware = self._read_hardware_minimal()
            self._sample_ams_if_due()
            self._sample_calibration_if_due()
            self._append_power_thermal_telemetry_if_due()
            try:
                self.lock_status = self.clock.read_lock_status()
                self.last_error = None
                reason = self.policy.observe(
                    streaming=bool(self.hardware["streaming"]),
                    pll1_lock=int(self.lock_status["pll1_lock"]),
                    pll2_lock=int(self.lock_status["pll2_lock"]),
                )
                sysref_reason = self._observe_sysref_capture(
                    previous_hardware,
                    self.hardware,
                )
                if reason is None and sysref_reason is not None:
                    self.policy.fault_latched = True
                    reason = sysref_reason
                if reason is None and self.spur_tracker_fault_reason is not None:
                    self.policy.fault_latched = True
                    reason = self.spur_tracker_fault_reason
            except Exception as exc:  # noqa: BLE001 - sustained errors fail safe
                self.lock_status = None
                self.last_error = f"LMK_SPI:{type(exc).__name__}:{exc}"
                reason = self.policy.observe(
                    streaming=bool(self.hardware["streaming"]),
                    pll1_lock=None,
                    pll2_lock=None,
                    spi_error=True,
                )
            if reason is not None:
                self._trip(reason)
            if self.policy.fault_latched:
                mode = "FAULT_LATCHED"
            elif bool(self.hardware["streaming"]):
                mode = "MONITORING"
            else:
                mode = "IDLE"
            healthy = bool(
                not self.policy.fault_latched
                and self.lock_status is not None
                and int(self.lock_status.get("pll1_lock", 0)) == 1
                and int(self.lock_status.get("pll2_lock", 0)) == 1
                and self.last_error is None
            )
        except Exception as exc:  # noqa: BLE001 - daemon must keep reporting
            self.last_error = f"{type(exc).__name__}:{exc}"
            self.controller = None
            self.core = None
            mode = (
                "FAULT_LATCHED"
                if self.policy.fault_latched
                else "WAITING_FOR_PL"
            )
        return mode, healthy

    def run(self) -> int:
        while not self.stop_requested:
            loop_started = time.monotonic()
            with self._configure_read_guard() as read_allowed:
                if read_allowed:
                    mode, healthy = self._poll_once()
                else:
                    mode = "CONFIGURE_PAUSE"
                    healthy = False
                    self.last_error = "CONFIGURE_IN_PROGRESS"
            self._write_state(mode=mode, healthy=healthy)
            remaining = self.interval_seconds - (time.monotonic() - loop_started)
            if remaining > 0:
                time.sleep(remaining)
        self._write_state(mode="STOPPED", healthy=False)
        return 0


def _acquire_singleton(path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR | os.O_CLOEXEC, 0o644)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        os.close(descriptor)
        raise RuntimeError("another reference watchdog instance is running") from exc
    os.ftruncate(descriptor, 0)
    os.write(descriptor, f"{os.getpid()}\n".encode("ascii"))
    return descriptor


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bitfile",
        default="/opt/t510-agent/current/overlay/t510_fengine.bit",
    )
    parser.add_argument("--state", default=str(DEFAULT_STATE_PATH))
    parser.add_argument("--lock", default=str(DEFAULT_LOCK_PATH))
    parser.add_argument(
        "--configure-lock",
        default=str(DEFAULT_CONFIGURE_LOCK_PATH),
    )
    parser.add_argument(
        "--clock-diagnostic-state",
        default=str(DEFAULT_CLOCK_DIAGNOSTIC_STATE_PATH),
    )
    parser.add_argument(
        "--output-load-state",
        default=str(DEFAULT_OUTPUT_LOAD_STATE_PATH),
    )
    parser.add_argument(
        "--rfdc-power-state",
        default=str(DEFAULT_RFDC_POWER_STATE_PATH),
    )
    parser.add_argument(
        "--spur-correction-state",
        default=str(DEFAULT_SPUR_CORRECTION_STATE_PATH),
    )
    parser.add_argument(
        "--power-thermal-telemetry",
        default=str(DEFAULT_POWER_THERMAL_TELEMETRY_PATH),
    )
    parser.add_argument("--interval-ms", type=float, default=100.0)
    parser.add_argument(
        "--expected-core-version",
        default="auto",
        help="catalog-bound core identity; auto reads the overlay manifest (v34 fallback)",
    )
    parser.add_argument("--unlock-confirmations", type=int, default=2)
    parser.add_argument("--spi-error-confirmations", type=int, default=5)
    parser.add_argument("--stop-timeout-ms", type=float, default=2000.0)
    args = parser.parse_args(argv)
    if not 20.0 <= args.interval_ms <= 1000.0:
        parser.error("--interval-ms must be within 20..1000")
    if not 2 <= args.unlock_confirmations <= 10:
        parser.error("--unlock-confirmations must be within 2..10")
    if not 2 <= args.spi_error_confirmations <= 50:
        parser.error("--spi-error-confirmations must be within 2..50")
    if not 100.0 <= args.stop_timeout_ms <= 10_000.0:
        parser.error("--stop-timeout-ms must be within 100..10000")
    try:
        expected_core_version = (
            _expected_core_version_for_bitfile(Path(args.bitfile))
            if str(args.expected_core_version).strip().lower() == "auto"
            else int(str(args.expected_core_version), 0)
        )
    except ValueError:
        parser.error("--expected-core-version must be auto or an integer such as 0x00010036")

    lock_descriptor = _acquire_singleton(Path(args.lock))
    try:
        watchdog = ReferenceWatchdog(
            bitfile=Path(args.bitfile),
            state_path=Path(args.state),
            interval_seconds=args.interval_ms / 1000.0,
            stop_timeout_seconds=args.stop_timeout_ms / 1000.0,
            unlock_confirmations=args.unlock_confirmations,
            spi_error_confirmations=args.spi_error_confirmations,
            configure_lock_path=Path(args.configure_lock),
            expected_core_version=expected_core_version,
            clock_diagnostic_state_path=Path(args.clock_diagnostic_state),
            output_load_state_path=Path(args.output_load_state),
            rfdc_power_state_path=Path(args.rfdc_power_state),
            spur_correction_state_path=Path(args.spur_correction_state),
            power_thermal_telemetry_path=Path(args.power_thermal_telemetry),
        )
        signal.signal(signal.SIGTERM, watchdog.request_stop)
        signal.signal(signal.SIGINT, watchdog.request_stop)
        return watchdog.run()
    finally:
        os.close(lock_descriptor)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001 - systemd must receive a nonzero exit
        print(f"REFERENCE_WATCHDOG_FATAL {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
