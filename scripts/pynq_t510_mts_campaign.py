#!/usr/bin/env python3
"""Run the current RFDC MTS discovery or fixed-latency campaign on T510.

This script is intentionally board-side.  It writes one checkpoint JSON after
every cycle so a power or SSH interruption cannot turn an incomplete campaign
into an apparent pass.
"""

from __future__ import annotations

import argparse
import atexit
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from typing import Any


LATENCY_QUANTA = {"adc": 12, "dac": 12}
DEFAULT_CONFIGURE_LOCK = Path("/run/t510-configure.lock")


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _jsonable(value: Any) -> Any:
    try:
        import numpy as np
    except ImportError:
        np = None  # type: ignore[assignment]
    if np is not None and isinstance(value, np.ndarray):
        return value.tolist()
    if np is not None and isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _write_checkpoint(path: Path, result: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(_jsonable(result), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _release_configure_lock(descriptor: int) -> None:
    try:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)


def _acquire_configure_lock(path: Path) -> int:
    """Exclude the resident watchdog/Agent from PL and LMK access."""

    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC)
    except FileNotFoundError:
        descriptor = os.open(
            path,
            os.O_CREAT | os.O_RDWR | os.O_CLOEXEC,
            0o644,
        )
    fcntl.flock(descriptor, fcntl.LOCK_EX)
    atexit.register(_release_configure_lock, descriptor)
    return descriptor


def _active_values(config: dict[str, Any], field: str) -> list[int]:
    mask = int(config.get("tiles", 0))
    values = [int(value) for value in config.get(field, [])]
    return [
        values[tile]
        for tile in range(min(4, len(values)))
        if mask & (1 << tile)
    ]


def _reset_rfdc_tiles(core: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if core.rfdc is None:
        raise RuntimeError("RFDC handle is unavailable")
    for kind, attribute in (("adc", "adc_tiles"), ("dac", "dac_tiles")):
        for tile_index, tile in enumerate(list(getattr(core.rfdc, attribute, []))):
            method = next(
                (
                    (name, getattr(tile, name))
                    for name in ("Reset", "reset")
                    if callable(getattr(tile, name, None))
                ),
                None,
            )
            if method is None:
                raise RuntimeError(f"{kind} tile {tile_index} has no Reset API")
            name, function = method
            value = function()
            rows.append(
                {
                    "kind": kind,
                    "tile": tile_index,
                    "method": name,
                    "result": repr(value),
                }
            )
    return rows


def _run_mts(core: Any, *, center_mhz: float, adc_target: int, dac_target: int) -> dict[str, Any]:
    center_hz = float(center_mhz) * 1.0e6
    core.stop()
    observation = core.apply_mts_locked_observation_config(
        observe_center_hz=center_hz,
        dac_signal_hz=center_hz,
        expected_signal_hz=center_hz,
        view_bw_hz=320.0e6,
        amplitude=0,
        phase_deg=0.0,
        phase_deg_by_channel=(0.0,) * 8,
        enable_mask=0x00,
        adc_active_mask=core.complex_input_mask_to_adc_active_mask(0xFF),
        initialize=True,
        start=False,
        require_full_clock_lock=True,
        require_mts=True,
        force_clock_reconfigure=False,
        input_source_mode="dac_loopback",
        clock_ref=core.PRODUCTION_CLOCK_REF,
        sync_mode=core.PRODUCTION_SYNC_MODE,
        mts_adc_target_latency=int(adc_target),
        mts_dac_target_latency=int(dac_target),
    )
    mts = observation.get("nco", {}).get("mts", {})
    if not isinstance(mts, dict) or not mts.get("calls"):
        raise RuntimeError("MTS result has no API call evidence")
    clock = core.read_lmk_status(include_registers=False)
    return {
        "mts": mts,
        "clock": clock,
        "status": core.read_status(),
    }


def _condition_initial_hardware(
    core: Any,
    *,
    lmk_settle_seconds: float,
    settle_seconds: float,
) -> dict[str, Any]:
    """Put a freshly downloaded current T510 release RFDC into a known clocked state.

    The campaign actions measure restart repeatability; this one-time bootstrap
    is recorded separately and is not counted as one of the required 40
    discovery/fixed cycles.
    """
    core.stop()
    clock_reload = core.configure_clock(
        ref=core.PRODUCTION_CLOCK_REF,
        profile=core.PRODUCTION_CLOCK_PROFILE,
    )
    if not bool(clock_reload.get("configured")):
        raise RuntimeError(f"initial LMK configuration did not lock: {clock_reload}")
    time.sleep(max(float(lmk_settle_seconds), 0.0))
    reset_calls = _reset_rfdc_tiles(core)
    time.sleep(max(float(settle_seconds), 0.0))
    clock = core.read_lmk_status(include_registers=False)
    if not bool(clock.get("configured")):
        raise RuntimeError(f"initial LMK lock was not retained: {clock}")
    contract = core.read_rfdc_contract(require=True)
    return {
        "ok": True,
        "counted_as_campaign_cycle": False,
        "reason": "condition RFDC after fresh bitstream download and before recorded restart cycles",
        "clock_reload": clock_reload,
        "lmk_settle_seconds": max(float(lmk_settle_seconds), 0.0),
        "reset_calls": reset_calls,
        "post_reset_settle_seconds": max(float(settle_seconds), 0.0),
        "clock": clock,
        "rfdc_contract": contract,
    }


def _assess_cycle(
    payload: dict[str, Any],
    *,
    phase: str,
    adc_target: int,
    dac_target: int,
) -> list[str]:
    errors: list[str] = []
    mts = payload["mts"]
    clock = payload["clock"]
    if bool(mts.get("failures")):
        errors.append("MTS_API_FAILURE")
    if not bool(clock.get("configured")):
        errors.append("LMK_NOT_LOCKED")
    if str(clock.get("profile_id")) != "160m_10m_cont_manual_clkin2":
        errors.append("WRONG_LMK_PROFILE")
    if str(clock.get("sysref_mode")) != "continuous":
        errors.append("SYSREF_NOT_CONTINUOUS")

    # Continuous SYSREF is never controlled through the LMK SYNC GPIO.  MTS
    # owns only RFDC-side capture gating in this profile.
    for call in mts.get("calls", []):
        if not isinstance(call, dict):
            continue
        if call.get("label", "").startswith("lmk_sysref_"):
            if call.get("mode") != "continuous" or call.get("gpio_changed") is not False:
                errors.append("CONTINUOUS_SYSREF_GPIO_TOGGLED")

    for kind, target in (("adc", adc_target), ("dac", dac_target)):
        config = mts.get(f"{kind}_config", {})
        if not isinstance(config, dict):
            errors.append(f"{kind.upper()}_CONFIG_MISSING")
            continue
        latencies = _active_values(config, "latency")
        offsets = _active_values(config, "offset")
        if len(latencies) != 4:
            errors.append(f"{kind.upper()}_LATENCY_READBACK_INCOMPLETE")
        elif len(set(latencies)) != 1:
            errors.append(f"{kind.upper()}_TILE_LATENCY_MISMATCH")
        if len(offsets) != 4:
            errors.append(f"{kind.upper()}_OFFSET_READBACK_INCOMPLETE")
        elif any(value < 0 or value > 31 for value in offsets):
            errors.append(f"{kind.upper()}_OFFSET_OUT_OF_RANGE")
        if phase == "fixed":
            if int(config.get("target_latency", -1)) != int(target):
                errors.append(f"{kind.upper()}_TARGET_READBACK_MISMATCH")
            # XRFdc_MTS_Latency applies an integer correction in units of the
            # converter decimation/interpolation factor.  The reported final
            # latency may therefore land on either side of Target_Latency by
            # at most half one factor; this is not XRFDC_MTS_TARGET_LOW.
            tolerance = LATENCY_QUANTA[kind] // 2
            if any(abs(value - int(target)) > tolerance for value in latencies):
                errors.append(f"{kind.upper()}_LATENCY_OUTSIDE_TARGET_QUANTIZATION")
    return sorted(set(errors))


def _campaign_actions(args: argparse.Namespace) -> list[str]:
    return (
        ["rfdc_reset"] * max(int(args.rfdc_resets), 0)
        + ["overlay_reload"] * max(int(args.overlay_reloads), 0)
        + ["lmk_reload"] * max(int(args.lmk_reloads), 0)
    )


def _fixed_repeatability(
    cycles: list[dict[str, Any]],
    *,
    adc_target: int,
    dac_target: int,
) -> dict[str, Any]:
    observations: dict[str, list[dict[str, list[int]]]] = {"adc": [], "dac": []}
    errors: list[str] = []
    for row in cycles:
        if row.get("ok") is not True:
            continue
        mts = row.get("evidence", {}).get("mts", {})
        for kind in ("adc", "dac"):
            config = mts.get(f"{kind}_config", {})
            observation = {
                "latency": _active_values(config, "latency"),
                "offset": _active_values(config, "offset"),
            }
            if len(observation["latency"]) != 4 or len(observation["offset"]) != 4:
                errors.append(f"{kind.upper()}_REPEATABILITY_READBACK_INCOMPLETE")
            observations[kind].append(observation)

    targets = {"adc": int(adc_target), "dac": int(dac_target)}
    summary: dict[str, Any] = {}
    for kind, values in observations.items():
        if len(values) != 40:
            errors.append(f"{kind.upper()}_REPEATABILITY_CYCLE_COUNT_{len(values)}")
        target = targets[kind]
        quantum = LATENCY_QUANTA[kind]
        tolerance = quantum // 2
        latency_counts: dict[tuple[int, ...], int] = {}
        offset_counts: dict[tuple[int, ...], int] = {}
        residuals: list[int] = []
        for value in values:
            latency = tuple(value["latency"])
            offset = tuple(value["offset"])
            latency_counts[latency] = latency_counts.get(latency, 0) + 1
            offset_counts[offset] = offset_counts.get(offset, 0) + 1
            if len(latency) == 4:
                if len(set(latency)) != 1:
                    errors.append(f"{kind.upper()}_TILE_LATENCY_MISMATCH")
                residuals.extend(item - target for item in latency)
            if len(offset) == 4 and any(item < 0 or item > 31 for item in offset):
                errors.append(f"{kind.upper()}_OFFSET_OUT_OF_RANGE")
        if any(abs(value) > tolerance for value in residuals):
            errors.append(f"{kind.upper()}_LATENCY_OUTSIDE_TARGET_QUANTIZATION")
        summary[kind] = {
            "target_latency": target,
            "latency_quantum": quantum,
            "allowed_target_error": tolerance,
            "target_residual_min": min(residuals) if residuals else None,
            "target_residual_max": max(residuals) if residuals else None,
            "unique_latency_vectors": [
                {"values": list(vector), "count": count}
                for vector, count in sorted(latency_counts.items())
            ],
            "unique_offset_vectors": [
                {"values": list(vector), "count": count}
                for vector, count in sorted(offset_counts.items())
            ],
        }
    return {
        "ok": not errors,
        "cycles": min((len(values) for values in observations.values()), default=0),
        "criterion": (
            "all four tiles aligned within each cycle and final latency within "
            "half one RFDC factor of Target_Latency; raw correction offsets are evidence, not phase"
        ),
        "phase_repeatability_gate": "separate RF loopback/TG measurement",
        "by_kind": summary,
        "errors": sorted(set(errors)),
    }


def _targets(args: argparse.Namespace) -> tuple[int, int]:
    adc_target = args.adc_target
    dac_target = args.dac_target
    if args.phase == "discovery":
        if adc_target not in (None, -1) or dac_target not in (None, -1):
            raise ValueError("discovery requires ADC/DAC target latency -1")
        return -1, -1
    if args.discovery_json:
        discovery = json.loads(Path(args.discovery_json).read_text(encoding="utf-8"))
        recommended = discovery.get("recommended_fixed_targets", {})
        if adc_target is None:
            adc_target = recommended.get("adc")
        if dac_target is None:
            dac_target = recommended.get("dac")
    if adc_target is None or dac_target is None:
        raise ValueError("fixed phase requires --adc-target/--dac-target or --discovery-json")
    if int(adc_target) < 0 or int(dac_target) < 0:
        raise ValueError("fixed target latencies must be non-negative")
    if int(adc_target) == 230 or int(dac_target) == 336:
        raise ValueError("current T510 release fixed phase must not reuse ADC=230 or DAC=336")
    return int(adc_target), int(dac_target)


def main() -> int:
    sys.path.insert(0, str(_root()))
    from python.t510_control import EXPECTED_CORE_VERSION, FEngineController

    parser = argparse.ArgumentParser(description="current T510 release RFDC MTS campaign")
    parser.add_argument("--phase", choices=("discovery", "fixed"), required=True)
    parser.add_argument(
        "--bitfile",
        default=str(_root() / "overlay" / "t510_fengine.bit"),
    )
    parser.add_argument("--center-mhz", type=float, default=200.0)
    parser.add_argument("--rfdc-resets", type=int, default=20)
    parser.add_argument("--overlay-reloads", type=int, default=10)
    parser.add_argument("--lmk-reloads", type=int, default=10)
    parser.add_argument("--adc-target", type=int)
    parser.add_argument("--dac-target", type=int)
    parser.add_argument("--discovery-json")
    parser.add_argument("--settle-seconds", type=float, default=0.1)
    parser.add_argument(
        "--lmk-settle-seconds",
        type=float,
        default=1.0,
        help=(
            "wait for analog clocks after an LMK reload before resetting RFDC "
            "tiles and attempting MTS"
        ),
    )
    parser.add_argument("--configure-lock", default=str(DEFAULT_CONFIGURE_LOCK))
    parser.add_argument("--output")
    args = parser.parse_args()

    try:
        adc_target, dac_target = _targets(args)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    output = (
        Path(args.output)
        if args.output
        else _root() / "build" / "board" / "latest" / "evidence" / f"mts_{args.phase}.json"
    )
    bitfile = Path(args.bitfile).resolve(strict=True)
    actions = _campaign_actions(args)
    result: dict[str, Any] = {
        "classification": f"T510_MTS_{args.phase.upper()}_IN_PROGRESS",
        "ok": False,
        "release": "latest",
        "phase": args.phase,
        "core_version": f"0x{EXPECTED_CORE_VERSION:08x}",
        "bitfile": str(bitfile),
        "bitstream_sha256": _sha256(bitfile),
        "targets": {"adc": adc_target, "dac": dac_target},
        "latency_quanta": dict(LATENCY_QUANTA),
        "margins": {"adc": 20, "dac": 16},
        "required_cycles": {
            "rfdc_reset": int(args.rfdc_resets),
            "overlay_reload": int(args.overlay_reloads),
            "lmk_reload": int(args.lmk_reloads),
        },
        "completed_cycles": 0,
        "configure_lock": str(Path(args.configure_lock)),
        "cycles": [],
        "errors": [],
    }
    _write_checkpoint(output, result)

    _configure_lock_descriptor = _acquire_configure_lock(Path(args.configure_lock))
    result["configure_lock_acquired"] = True
    _write_checkpoint(output, result)

    controller = FEngineController(args.bitfile)
    controller.connect(download=True)
    core = controller.require_core()
    initial_status = core.read_status()
    if int(initial_status.get("core_version", 0)) != EXPECTED_CORE_VERSION:
        raise RuntimeError(
            f"wrong core version: expected 0x{EXPECTED_CORE_VERSION:08x}, "
            f"read 0x{int(initial_status.get('core_version', 0)):08x}"
        )

    try:
        result["initial_conditioning"] = _condition_initial_hardware(
            core,
            lmk_settle_seconds=args.lmk_settle_seconds,
            settle_seconds=args.settle_seconds,
        )
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        result["initial_conditioning"] = {
            "ok": False,
            "counted_as_campaign_cycle": False,
            "error": error,
        }
        result["errors"].append({"initial_conditioning": error})
        result["classification"] = f"T510_MTS_{args.phase.upper()}_FAIL"
        _write_checkpoint(output, result)
        print(json.dumps(_jsonable(result), indent=2, sort_keys=True))
        return 1
    _write_checkpoint(output, result)

    for cycle_index, action in enumerate(actions):
        row: dict[str, Any] = {
            "cycle": cycle_index,
            "action": action,
            "ok": False,
            "errors": [],
        }
        try:
            core.stop()
            if action == "rfdc_reset":
                row["reset_calls"] = _reset_rfdc_tiles(core)
            elif action == "overlay_reload":
                controller.connect(download=True)
                core = controller.require_core()
            elif action == "lmk_reload":
                row["clock_reload"] = core.configure_clock(
                    ref=core.PRODUCTION_CLOCK_REF,
                    profile=core.PRODUCTION_CLOCK_PROFILE,
                )
                # Reprogramming LMK interrupts the RFDC reference clocks.  A
                # PLL-lock readback alone does not reinitialize the converter
                # tile state used by the MTS DTC scan.  Wait for the analog
                # clocks to settle, then restart every active tile before MTS.
                time.sleep(max(float(args.lmk_settle_seconds), 0.0))
                row["post_clock_reset_calls"] = _reset_rfdc_tiles(core)
            else:
                raise RuntimeError(f"unsupported campaign action {action}")
            time.sleep(max(float(args.settle_seconds), 0.0))
            row["evidence"] = _run_mts(
                core,
                center_mhz=args.center_mhz,
                adc_target=adc_target,
                dac_target=dac_target,
            )
            row["errors"] = _assess_cycle(
                row["evidence"],
                phase=args.phase,
                adc_target=adc_target,
                dac_target=dac_target,
            )
            row["ok"] = not row["errors"]
        except Exception as exc:
            row["errors"] = [f"{type(exc).__name__}: {exc}"]
        result["cycles"].append(row)
        result["completed_cycles"] = len(result["cycles"])
        if row["errors"]:
            result["errors"].append(
                {"cycle": cycle_index, "action": action, "errors": row["errors"]}
            )
        _write_checkpoint(output, result)

    if args.phase == "discovery":
        adc_latencies: list[int] = []
        dac_latencies: list[int] = []
        for row in result["cycles"]:
            if not row.get("ok"):
                continue
            mts = row["evidence"]["mts"]
            adc_latencies.extend(_active_values(mts["adc_config"], "latency"))
            dac_latencies.extend(_active_values(mts["dac_config"], "latency"))
        if adc_latencies and dac_latencies:
            result["observed_latency"] = {
                "adc": adc_latencies,
                "dac": dac_latencies,
                "adc_max": max(adc_latencies),
                "dac_max": max(dac_latencies),
            }
            result["recommended_fixed_targets"] = {
                "adc": max(adc_latencies) + 20,
                "dac": max(dac_latencies) + 16,
            }
        else:
            result["errors"].append({"campaign": "NO_VALID_LATENCY_OBSERVATIONS"})
    else:
        result["fixed_repeatability"] = _fixed_repeatability(
            result["cycles"],
            adc_target=adc_target,
            dac_target=dac_target,
        )
        if not result["fixed_repeatability"]["ok"]:
            result["errors"].append(
                {
                    "campaign": "FIXED_LATENCY_OR_OFFSET_NOT_REPEATABLE",
                    "errors": result["fixed_repeatability"]["errors"],
                }
            )

    result["ok"] = (
        len(result["cycles"]) == len(actions)
        and bool(actions)
        and all(bool(row.get("ok")) for row in result["cycles"])
        and not result["errors"]
    )
    result["classification"] = (
        f"T510_MTS_{args.phase.upper()}_{'PASS' if result['ok'] else 'FAIL'}"
    )
    _write_checkpoint(output, result)
    print(json.dumps(_jsonable(result), indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
