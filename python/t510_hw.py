#!/usr/bin/env python3
"""One-shot PYNQ bridge for the stateless Stage 30 Rust Board Agent.

The request is one JSON object on stdin. Exactly one JSON object is emitted on
stdout; incidental PYNQ output is redirected to stderr.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
from pathlib import Path
import sys
import time
import traceback
from typing import Any, Callable

from python.stage29 import (
    DacChannelConfig,
    FlowDestination,
    Stage29Config,
    Stage29Controller,
)


EXIT_INVALID = 2
EXIT_STATE_CONFLICT = 3
EXIT_HARDWARE_UNAVAILABLE = 4
EXIT_BITSTREAM_PROOF = 5
EXIT_INTERNAL = 6


class HelperError(RuntimeError):
    def __init__(self, code: str, message: str, *, exit_code: int, details: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.exit_code = int(exit_code)
        self.details = details


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


def _controller(request: dict[str, Any], *, download: bool = False) -> Stage29Controller:
    bitstream = _bitstream(request)
    path = _verify_bitstream(bitstream, hash_file=download)
    controller = Stage29Controller(path)
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


def _expected_board(controller: Stage29Controller, body: dict[str, Any]) -> int:
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
    bandwidth_code = int(status.get("science_bandwidth_mode", 0))
    output_code = int(status.get("science_output_mode", 0))
    output_name = str(status.get("science_output_mode_name", "")).strip().lower()
    return {
        "bandwidth_mhz": int(
            status.get("science_bandwidth_mhz", {1: 100, 2: 200}.get(bandwidth_code, 0))
        )
        or None,
        "mode": {
            "time_only": "time_only",
            "spec_only": "spec_only",
            "time_spec": "time_spec",
        }.get(output_name, {1: "time_only", 2: "spec_only", 3: "time_spec"}.get(output_code, "unknown")),
        "bandwidth_code": bandwidth_code,
        "output_mode_code": output_code,
    }


def _status_snapshot(controller: Stage29Controller) -> dict[str, Any]:
    core = controller.require_core()
    status = core.read_status()
    mixers = core.read_rfdc_mixer_frequencies()
    dac_centers = [
        float(item["frequency_mhz"])
        for item in mixers.get("mixers", [])
        if item.get("kind") == "dac" and float(item.get("frequency_mhz", 0.0)) > 0.0
    ]
    center_mhz = None
    if dac_centers and max(dac_centers) - min(dac_centers) < 1e-6:
        center_mhz = sum(dac_centers) / len(dac_centers)
    tx_flags = int(status.get("tx_link_status_flags", 0))
    return {
        "captured_at_unix_ms": time.time_ns() // 1_000_000,
        "core_version": f"0x{int(status.get('core_version', 0)):08x}",
        "board_id": int(status.get("board_id", 0)),
        "streaming": bool(status.get("streaming", 0)),
        "profile": {**_profile_name(status), "center_mhz": center_mhz},
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
        "sample0": {
            "time": int(status.get("time_sample0", 0)),
            "rfdc": int(status.get("rfdc_sample_count", 0)),
        },
        "error_flags": int(status.get("error_flags", 0)),
        "dac": controller.read_dac_channels(center_mhz=center_mhz),
    }


def _configure(request: dict[str, Any]) -> dict[str, Any]:
    body = _body(request)
    bitstream = _bitstream(request)
    path = _verify_bitstream(bitstream, hash_file=True)
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
    config = Stage29Config(
        bandwidth_mhz=int(profile["bandwidth_mhz"]),
        mode=profile["mode"],
        center_mhz=float(profile["center_mhz"]),
        board_id=int(body["board_id"]),
        source_ip=source["ip"],
        source_mac=source["mac"],
        time_destinations=time_destinations,
        spec_destinations=spec_destinations,
    )
    controller = Stage29Controller(path)
    started = time.monotonic()
    applied = controller.prepare(config, fresh_download=True, program_dac=False)
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
    status = controller.start_immediate()
    return {"started": True, "status": status, "snapshot": _status_snapshot(controller)}


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
    channels = tuple(
        DacChannelConfig(
            enabled=bool(item["enabled"]),
            rf_frequency_mhz=float(item["rf_frequency_mhz"]),
            amplitude=float(item["amplitude_percent"]),
            phase_deg=float(item["phase_deg"]),
        )
        for item in sorted(body["channels"], key=lambda item: int(item["channel"]))
    )
    result = controller.apply_dac_live(channels, center_mhz=float(body["center_mhz"]))
    return {"updated": True, **result}


COMMANDS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "status": _status,
    "configure": _configure,
    "start": _start,
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
                    "message": "command must be status, configure, start, stop, reset, or set-dac",
                },
            },
            sys.stdout,
        )
        sys.stdout.write("\n")
        return EXIT_INVALID
    try:
        request = _read_request()
        with contextlib.redirect_stdout(sys.stderr):
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
