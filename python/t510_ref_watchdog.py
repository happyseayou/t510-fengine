#!/usr/bin/env python3
"""Resident Stage 32 external-reference safety watchdog.

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
import contextlib
from dataclasses import dataclass
from datetime import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import sys
import time
from typing import Any

from python.t510_clock import T510ClockController


SCHEMA_VERSION = 1
EXPECTED_CORE_VERSION = 0x0001_0032
DEFAULT_STATE_PATH = Path("/run/t510-stage32-ref-watchdog.json")
DEFAULT_LOCK_PATH = Path("/run/t510-stage32-ref-watchdog.lock")
DEFAULT_CONFIGURE_LOCK_PATH = Path("/run/t510-stage32-configure.lock")
FPGA_MANAGER_STATE_PATH = Path("/sys/class/fpga_manager/fpga0/state")


def _timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def _sha1(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
    ) -> None:
        self.bitfile = bitfile.resolve()
        self.expected_bitstream_sha1 = _sha1(self.bitfile)
        self.state_path = state_path
        self.interval_seconds = interval_seconds
        self.stop_timeout_seconds = stop_timeout_seconds
        self.configure_lock_path = configure_lock_path
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
        self._load_previous_state()

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
        from python.stage29 import Stage29Controller

        controller = Stage29Controller(self.bitfile)
        status = controller.connect(download=False)
        version = int(status.get("core_version", 0))
        if version != EXPECTED_CORE_VERSION:
            raise RuntimeError(
                "CORE_VERSION_MISMATCH:"
                f"expected=0x{EXPECTED_CORE_VERSION:08x}:actual=0x{version:08x}"
            )
        old_identity = self.pl_identity
        self.controller = controller
        self.core = controller.require_core()
        self.pl_identity = identity
        if old_identity is not None and identity != old_identity:
            self.policy.clear_for_fresh_configure()
            print(
                f"REFERENCE_WATCHDOG_FRESH_CONFIGURE identity={identity}",
                flush=True,
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
        return {
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
            "service": "t510-stage32-ref-watchdog",
            "pid": os.getpid(),
            "service_started_at": self.service_started_at,
            "updated_at": _timestamp(),
            "updated_at_unix_ms": time.time_ns() // 1_000_000,
            "mode": mode,
            "healthy": bool(healthy),
            "fault_latched": bool(self.policy.fault_latched),
            "pl_identity": self.pl_identity,
            "active_bitstream_sha1": self.expected_bitstream_sha1,
            "expected_core_version": f"0x{EXPECTED_CORE_VERSION:08x}",
            "poll_interval_ms": round(self.interval_seconds * 1000.0, 3),
            "unlock_confirmations_required": self.policy.unlock_confirmations,
            "spi_error_confirmations_required": self.policy.spi_error_confirmations,
            "pll1_unlock_count": self.policy.pll1_unlock_count,
            "pll2_unlock_count": self.policy.pll2_unlock_count,
            "spi_error_count": self.policy.spi_error_count,
            "lock_status": self.lock_status,
            "hardware": self.hardware,
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
            self.hardware = self._read_hardware_minimal()
            try:
                self.lock_status = self.clock.read_lock_status()
                self.last_error = None
                reason = self.policy.observe(
                    streaming=bool(self.hardware["streaming"]),
                    pll1_lock=int(self.lock_status["pll1_lock"]),
                    pll2_lock=int(self.lock_status["pll2_lock"]),
                )
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
    parser.add_argument("--interval-ms", type=float, default=100.0)
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
