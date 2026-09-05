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


def _factor_quantized_latency_errors(
    kind: str,
    latencies: list[int],
    *,
    target: int | None = None,
) -> list[str]:
    """Validate the residuals produced by XRFdc_MTS_Latency rounding.

    The 2022.2 driver rounds each FIFO correction to a whole converter factor
    with ties rounded down.  A successful sync can therefore report different
    final T1 latencies across tiles: residuals span -factor/2 through
    factor/2-1.  Exact equality is not an MTS success requirement.
    """

    quantum = LATENCY_QUANTA[kind]
    errors: list[str] = []
    if latencies and max(latencies) - min(latencies) >= quantum:
        errors.append(
            f"{kind.upper()}_INTERTILE_RESIDUAL_EXCEEDS_FACTOR_QUANTIZATION"
        )
    if target is not None:
        tolerance = quantum // 2
        if any(abs(value - int(target)) > tolerance for value in latencies):
            errors.append(f"{kind.upper()}_LATENCY_OUTSIDE_TARGET_QUANTIZATION")
    return errors


def _reset_rfdc_tiles(core: Any) -> list[dict[str, Any]]:
    return core.reset_all_rfdc_tiles()


def _campaign_clock_profile(core: Any, clock_ref: str) -> str:
    return ("160m_10m_request_manual_clkin0" if clock_ref == "tcxo_10mhz"
            else core.PRODUCTION_CLOCK_PROFILE)


def _run_mts(core: Any, *, center_mhz: float, adc_target: int, dac_target: int,
             clock_ref: str | None = None) -> dict[str, Any]:
    center_hz = float(center_mhz) * 1.0e6
    clock_ref = clock_ref or core.PRODUCTION_CLOCK_REF
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
        require_clock_preserved=True,
        input_source_mode="dac_loopback",
        clock_ref=clock_ref,
        clock_profile=_campaign_clock_profile(core, clock_ref),
        sync_mode="free_run" if clock_ref == "tcxo_10mhz" else core.PRODUCTION_SYNC_MODE,
        mts_adc_target_latency=int(adc_target),
        mts_dac_target_latency=int(dac_target),
    )
    mts = observation.get("nco", {}).get("mts", {})
    if not isinstance(mts, dict) or not mts.get("calls"):
        raise RuntimeError("MTS result has no API call evidence")
    clock = core.read_lmk_status(include_registers=False)
    return {
        "mts": mts,
        "clock_ref": clock_ref,
        "digital_scaling": observation.get("digital_scaling"),
        "clock": clock,
        "status": core.read_status(),
    }


def _preserve_clock(clock_ref: str) -> dict[str, Any]:
    from python.t510_hw import _clock_preserving_preflight, _production_clock_selection
    return _clock_preserving_preflight(_production_clock_selection({
        "clock_reference": "onboard_tcxo" if clock_ref == "tcxo_10mhz" else "external_10mhz"
    }))


def _request_for_restart(core: Any, clock_ref: str) -> Any:
    if clock_ref == "tcxo_10mhz":
        return core.clock.set_sysref(True)
    return None


def _reload_overlay(controller: Any) -> Any:
    controller.connect(download=True)
    core = controller.require_core()
    core.stop()
    core.set_dac_enable_mask(0)
    return core


def _condition_initial_hardware(
    controller: Any, *, lmk_settle_seconds: float, settle_seconds: float,
    clock_ref: str = "tcxo_10mhz", initialize_clock: bool = False,
) -> dict[str, Any]:
    if initialize_clock:
        controller.connect(download=False)
        old_core = controller.require_core()
        old_core.stop()
        old_core.set_dac_enable_mask(0)
        shutdown = old_core.shutdown_all_rfdc_tiles()
        clock = old_core.configure_clock(
            ref=clock_ref, profile=_campaign_clock_profile(old_core, clock_ref)
        )
        if not clock.get("configured"):
            raise RuntimeError("initial clock profile did not lock")
        time.sleep(max(float(lmk_settle_seconds), 0.0))
    else:
        shutdown = []
        clock = _preserve_clock(clock_ref)
    core = _reload_overlay(controller)
    resets = _reset_rfdc_tiles(core) if initialize_clock else []
    time.sleep(max(float(settle_seconds), 0.0))
    return {"ok": True, "counted_as_campaign_cycle": False,
            "clock": clock, "clock_initialized": initialize_clock,
            "shutdown_calls": shutdown, "reset_calls": resets,
            "rfdc_contract": core.read_rfdc_contract(require=True)}


def _reload_lmk(controller: Any, *, clock_ref: str, settle_seconds: float) -> dict[str, Any]:
    # Shut down the converters while their old clocks are still running.
    core = controller.require_core()
    core.stop()
    core.set_dac_enable_mask(0)
    row = {"shutdown_calls": core.shutdown_all_rfdc_tiles()}
    row["clock_reload"] = core.configure_clock(
        ref=clock_ref, profile=_campaign_clock_profile(core, clock_ref))
    if not row["clock_reload"].get("configured"):
        raise RuntimeError("LMK handoff failed to lock")
    time.sleep(max(float(settle_seconds), 0.0))
    row["sysref_for_restart"] = _request_for_restart(core, clock_ref)
    core = _reload_overlay(controller)
    row["post_clock_reset_calls"] = _reset_rfdc_tiles(core)
    return row


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
    tcxo = payload.get("clock_ref") == "tcxo_10mhz"
    expected_profile = "160m_10m_request_manual_clkin0" if tcxo else "160m_10m_cont_manual_clkin2"
    expected_sysref = "request" if tcxo else "continuous"
    if str(clock.get("profile_id")) != expected_profile:
        errors.append("WRONG_LMK_PROFILE")
    if str(clock.get("sysref_mode")) != expected_sysref:
        errors.append("WRONG_SYSREF_MODE")
    if tcxo and (clock.get("sysref_request_gpio") != 0 or clock.get("sysref_output_expected_on") is not False):
        errors.append("REQUEST_SYSREF_NOT_OFF_AFTER_MTS")

    # Continuous SYSREF is never controlled through the LMK SYNC GPIO.  MTS
    # owns only RFDC-side capture gating in this profile.
    for call in mts.get("calls", []):
        if not isinstance(call, dict):
            continue
        if not tcxo and call.get("label", "").startswith("lmk_sysref_"):
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
        else:
            errors.extend(_factor_quantized_latency_errors(kind, latencies))
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
            if int(target) >= 0:
                errors.extend(
                    _factor_quantized_latency_errors(
                        kind, latencies, target=int(target)
                    )
                )
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
                errors.extend(_factor_quantized_latency_errors(kind, list(latency)))
                if target >= 0:
                    residuals.extend(item - target for item in latency)
            if len(offset) == 4 and any(item < 0 or item > 31 for item in offset):
                errors.append(f"{kind.upper()}_OFFSET_OUT_OF_RANGE")
        if target >= 0 and any(abs(value) > tolerance for value in residuals):
            errors.append(f"{kind.upper()}_LATENCY_OUTSIDE_TARGET_QUANTIZATION")
        summary[kind] = {
            "target_latency": target,
            "latency_quantum": quantum,
            "allowed_target_error": tolerance,
            "alignment_mode": (
                "deterministic_target" if target >= 0 else "single_device_relative"
            ),
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
            "XRFdc_MultiConverter_Sync succeeds and reported inter-tile residual span is "
            "less than one RFDC factor; ADC is within half one factor of its deterministic "
            "target, while DAC uses AMD single-device relative alignment because the "
            "observed circular states have no common fixed target"
        ),
        "phase_repeatability_gate": "separate RF loopback/TG measurement",
        "by_kind": summary,
        "errors": sorted(set(errors)),
    }


def _recommended_fixed_targets(
    adc_observations: list[int], dac_observations: list[int], *, clock_ref: str = "tcxo_10mhz"
) -> dict[str, Any]:
    """Apply the policy for the selected physical reference."""

    from python.t510_mts_target import (
        external_10mhz_fixed_target_policy,
        onboard_tcxo_fixed_target_policy,
    )

    if clock_ref == "tcxo_10mhz":
        return onboard_tcxo_fixed_target_policy(adc_observations, dac_observations)
    return external_10mhz_fixed_target_policy(adc_observations, dac_observations)


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
        observed = discovery.get("observed_latency", {})
        derived = _recommended_fixed_targets(
            [int(value) for value in observed.get("adc", [])],
            [int(value) for value in observed.get("dac", [])],
            clock_ref=getattr(args, "clock_ref", "tcxo_10mhz"),
        )["targets"]
        if recommended != derived:
            raise ValueError(
                f"discovery fixed targets do not match frozen policy: {recommended} != {derived}"
            )
        if adc_target is not None and int(adc_target) != int(derived["adc"]):
            raise ValueError("explicit ADC target does not match frozen policy")
        if dac_target is not None and int(dac_target) != int(derived["dac"]):
            raise ValueError("explicit DAC target does not match frozen policy")
        if adc_target is None:
            adc_target = derived.get("adc")
        if dac_target is None:
            dac_target = derived.get("dac")
    if adc_target is None or dac_target is None:
        raise ValueError("fixed phase requires --adc-target/--dac-target or --discovery-json")
    if int(adc_target) < 0 or int(dac_target) < -1:
        raise ValueError(
            "fixed phase requires a non-negative ADC target and DAC target >= -1"
        )
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
    parser.add_argument("--clock-ref", choices=("tcxo_10mhz", "external_10mhz"),
                        default="tcxo_10mhz")
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
        default=3.0,
        help=(
            "wait for analog clocks after an LMK reload before resetting RFDC "
            "tiles and attempting MTS; historical baseline repeatability established 3 s"
        ),
    )
    parser.add_argument("--configure-lock", default=str(DEFAULT_CONFIGURE_LOCK))
    parser.add_argument(
        "--initialize-clock",
        action="store_true",
        help="select and lock the requested clock before loading the candidate",
    )
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
        "clock_ref": args.clock_ref,
        "bitfile": str(bitfile),
        "bitstream_sha256": _sha256(bitfile),
        "targets": {"adc": adc_target, "dac": dac_target},
        "latency_quanta": dict(LATENCY_QUANTA),
        "margins": {"adc": 20, "dac": 16},
        "settle_seconds": float(args.settle_seconds),
        "lmk_settle_seconds": float(args.lmk_settle_seconds),
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
    try:
        result["initial_conditioning"] = _condition_initial_hardware(
            controller,
            lmk_settle_seconds=args.lmk_settle_seconds,
            settle_seconds=args.settle_seconds,
            clock_ref=args.clock_ref,
            initialize_clock=args.initialize_clock,
        )
        core = controller.require_core()
        from python.t510_control import EXPECTED_CORE_VERSION
        if int(core.read_status().get("core_version", 0)) != EXPECTED_CORE_VERSION:
            raise RuntimeError("wrong core version after clock-preserving reload")
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
                row["sysref_for_restart"] = _request_for_restart(core, args.clock_ref)
                row["reset_calls"] = _reset_rfdc_tiles(core)
            elif action == "overlay_reload":
                row["clock_preserved"] = _preserve_clock(args.clock_ref)
                core = _reload_overlay(controller)
            elif action == "lmk_reload":
                row.update(_reload_lmk(controller, clock_ref=args.clock_ref,
                                       settle_seconds=args.lmk_settle_seconds))
                core = controller.require_core()
            else:
                raise RuntimeError(f"unsupported campaign action {action}")
            time.sleep(max(float(args.settle_seconds), 0.0))
            row["evidence"] = _run_mts(
                core,
                center_mhz=args.center_mhz,
                adc_target=adc_target,
                dac_target=dac_target,
                clock_ref=args.clock_ref,
            )
            row["errors"] = _assess_cycle(
                row["evidence"],
                phase=args.phase,
                adc_target=adc_target,
                dac_target=dac_target,
            )
            # Qualify actual current scale on every restart, not only when
            # finalizing the catalog after all cycles have finished.
            from python.t510_scaling import manifest_metadata
            manifest_metadata(row["evidence"]["digital_scaling"])
            row["ok"] = not row["errors"]
        except Exception as exc:
            core = controller.require_core()
            core.stop()
            core.set_dac_enable_mask(0)
            if args.clock_ref == "tcxo_10mhz":
                core.clock.set_sysref(False)
            row["errors"] = [f"{type(exc).__name__}: {exc}"]
        result["cycles"].append(row)
        result["completed_cycles"] = len(result["cycles"])
        if row["errors"]:
            result["errors"].append(
                {"cycle": cycle_index, "action": action, "errors": row["errors"]}
            )
        _write_checkpoint(output, result)
        if row["errors"]:
            # AGENTS.md: a failed gate stops the remaining queue immediately.
            result["stopped_on_first_failure"] = True
            break

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
            try:
                target_policy = _recommended_fixed_targets(
                    adc_latencies, dac_latencies, clock_ref=args.clock_ref
                )
                result["recommended_fixed_targets"] = target_policy["targets"]
                result["target_policy"] = target_policy
            except ValueError as exc:
                result["errors"].append(
                    {"campaign": "FROZEN_TARGET_POLICY_REJECTED", "error": str(exc)}
                )
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
