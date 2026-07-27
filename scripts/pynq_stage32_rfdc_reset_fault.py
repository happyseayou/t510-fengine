#!/usr/bin/env python3
"""Inject one deliberate RFDC interruption for Stage 32 recovery testing.

This board-side diagnostic does not configure or recover the product.  It
requires an already-running scheduled Stage 32 stream and records whether the
hardware scheduler latched RFDC_NOT_READY and stopped the stream.

``reset`` calls the RFDC driver's Reset method on all four ADC and all four DAC
tiles.  Some driver/hardware revisions complete that operation without making
AXIS TVALID observably low; that is a valid negative diagnostic, not proof of
the stop gate.  ``shutdown_startup`` deliberately holds all tiles down before
starting them again and is the stronger driver-level attempt.  It still may
not propagate to the PL-visible ready signal on a given design.  Product
recovery remains a separate fresh CONFIGURE operation through the production
Board Agent.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from python.stage29 import EXPECTED_CORE_VERSION, Stage29Controller


def _snapshot(core: Any) -> dict[str, Any]:
    status = core.read_status()
    sync = core.read_scheduled_sync_status()
    return {
        "captured_at_unix_ms": time.time_ns() // 1_000_000,
        "core_version": f"0x{int(status.get('core_version', 0)):08x}",
        "streaming": bool(status.get("streaming", 0)),
        "rfdc_ready": bool(sync.get("rfdc_ready", False)),
        "ref_locked": bool(sync.get("ref_locked", False)),
        "pps_recent": bool(sync.get("pps_recent", False)),
        "spec_packets": int(status.get("spec_packet_count", 0)),
        "time_packets": int(status.get("time_packet_count", 0)),
        "rfdc_dropped": int(status.get("rfdc_dropped_count", 0)),
        "science_dropped_beats": int(
            status.get("science_dropped_beat_count", 0)
        ),
        "sync": sync,
    }


def _call_all_tiles(
    core: Any,
    *,
    method_names: tuple[str, ...],
    operation: str,
) -> list[dict[str, Any]]:
    """Attempt an RFDC operation on every tile and preserve every outcome.

    A fault-injection helper must not abandon the remaining tiles when one
    driver call fails.  In particular, a failed StartUp on one tile must not
    prevent best-effort StartUp calls on the other seven tiles or suppress the
    JSON evidence.
    """
    calls: list[dict[str, Any]] = []
    for kind, attribute in (("adc", "adc_tiles"), ("dac", "dac_tiles")):
        for tile_index, tile in enumerate(list(getattr(core.rfdc, attribute, []))):
            method = next(
                (
                    (name, getattr(tile, name))
                    for name in method_names
                    if callable(getattr(tile, name, None))
                ),
                None,
            )
            if method is None:
                calls.append(
                    {
                        "operation": operation,
                        "kind": kind,
                        "tile": tile_index,
                        "method": None,
                        "ok": False,
                        "error": f"no {operation} API",
                    }
                )
                continue
            name, function = method
            try:
                value = function()
                calls.append(
                    {
                        "operation": operation,
                        "kind": kind,
                        "tile": tile_index,
                        "method": name,
                        "ok": True,
                        "result": repr(value),
                    }
                )
            except Exception as exc:  # noqa: BLE001 - evidence must survive driver errors
                calls.append(
                    {
                        "operation": operation,
                        "kind": kind,
                        "tile": tile_index,
                        "method": name,
                        "ok": False,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
    return calls


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bitfile",
        default="/opt/t510-agent/current/overlay/t510_fengine.bit",
    )
    parser.add_argument("--output")
    parser.add_argument("--settle-seconds", type=float, default=2.0)
    parser.add_argument("--hold-seconds", type=float, default=0.5)
    parser.add_argument(
        "--fault-action",
        choices=("reset", "shutdown_startup"),
        default="reset",
    )
    parser.add_argument(
        "--confirm-reset-all-rfdc-tiles",
        action="store_true",
        help="required acknowledgement that this deliberately interrupts RFDC data",
    )
    args = parser.parse_args()
    if not args.confirm_reset_all_rfdc_tiles:
        parser.error("--confirm-reset-all-rfdc-tiles is required")
    if args.settle_seconds < 0.2:
        parser.error("--settle-seconds must be at least 0.2")
    if args.hold_seconds < 0.2:
        parser.error("--hold-seconds must be at least 0.2")

    controller = Stage29Controller(args.bitfile)
    controller.connect(download=False)
    core = controller.require_core()
    before = _snapshot(core)

    errors: list[str] = []
    if before["core_version"] != f"0x{EXPECTED_CORE_VERSION:08x}":
        errors.append("CORE_VERSION_MISMATCH")
    if not before["streaming"]:
        errors.append("FAULT_PRECONDITION_NOT_STREAMING")
    before_sync = dict(before["sync"])
    if not bool(before_sync.get("selected")):
        errors.append("FAULT_PRECONDITION_NOT_SCHEDULED")
    if bool(before_sync.get("error")):
        errors.append("FAULT_PRECONDITION_SYNC_ERROR")

    calls: list[dict[str, Any]] = []
    samples: list[dict[str, Any]] = []
    if not errors:
        if args.fault_action == "reset":
            calls = core.reset_all_rfdc_tiles()
            samples.append(_snapshot(core))
        else:
            calls.extend(
                _call_all_tiles(
                    core,
                    method_names=("ShutDown", "Shutdown", "shutdown"),
                    operation="shutdown",
                )
            )
            hold_deadline = time.monotonic() + float(args.hold_seconds)
            while time.monotonic() < hold_deadline:
                samples.append(_snapshot(core))
                time.sleep(min(0.05, max(hold_deadline - time.monotonic(), 0.0)))
            calls.extend(
                _call_all_tiles(
                    core,
                    method_names=("StartUp", "Startup", "startup"),
                    operation="startup",
                )
            )
            samples.append(_snapshot(core))

        deadline = time.monotonic() + float(args.settle_seconds)
        while time.monotonic() < deadline:
            time.sleep(min(0.1, max(deadline - time.monotonic(), 0.0)))
            samples.append(_snapshot(core))

        expected_calls = 8 if args.fault_action == "reset" else 16
        if len(calls) != expected_calls:
            errors.append(f"RFDC_ACTION_CALL_COUNT_{len(calls)}")
        for call in calls:
            if call.get("ok", True):
                continue
            errors.append(
                "RFDC_ACTION_FAILED_"
                f"{str(call.get('operation', 'unknown')).upper()}_"
                f"{str(call.get('kind', 'unknown')).upper()}_"
                f"{int(call.get('tile', -1))}"
            )
        if not any(not bool(sample["streaming"]) for sample in samples):
            errors.append("STREAM_DID_NOT_STOP_AFTER_RFDC_RESET")
        sync_errors = [
            dict(sample["sync"])
            for sample in samples
            if bool(dict(sample["sync"]).get("error"))
        ]
        if not sync_errors:
            errors.append("SCHEDULER_DID_NOT_LATCH_RFDC_ERROR")
        elif not any(
            int(sync.get("error_code", 0)) == 6
            and str(sync.get("error_name", "")).upper() == "RFDC_NOT_READY"
            for sync in sync_errors
        ):
            errors.append("SCHEDULER_ERROR_NOT_RFDC_NOT_READY")
        if len(samples) >= 2:
            last = samples[-1]
            previous = samples[-2]
            if (
                int(last["time_packets"]) != int(previous["time_packets"])
                or int(last["spec_packets"]) != int(previous["spec_packets"])
            ):
                errors.append("PACKETS_STILL_ADVANCING_AFTER_FAULT_SETTLE")

    result = {
        "stage": "32h-d",
        "test": f"scheduled_stream_all_tile_rfdc_{args.fault_action}",
        "fault_action": args.fault_action,
        "started_at_unix_ms": before["captured_at_unix_ms"],
        "ended_at_unix_ms": time.time_ns() // 1_000_000,
        "bitfile": str(Path(args.bitfile).resolve()),
        "before": before,
        "tile_action_calls": calls,
        "samples": samples,
        "recovery_performed": False,
        "errors": errors,
        "ok": not errors,
        "classification": (
            f"STAGE32H_RFDC_{args.fault_action.upper()}_FAULT_PASS"
            if not errors
            else f"STAGE32H_RFDC_{args.fault_action.upper()}_FAULT_FAIL"
        ),
    }
    rendered = json.dumps(result, indent=2, sort_keys=True)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
