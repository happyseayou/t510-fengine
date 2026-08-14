#!/usr/bin/env python3
"""Stage 34c-2R PL SYSREF phase-eye grid and deterministic selector.

The first v35 diagnostic image supplies routed setup/hold requirements and
physical edge counters.  Hardware orchestration records one JSON point per
TICS Pro exported SDCLKout3-delay profile.  This program validates those
records and selects the centre of the longest cyclic all-pass interval; it
never edits LMK registers or invents a profile from a register delta.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from fractions import Fraction
from pathlib import Path
from typing import Any, Iterable


PHASE_PERIOD_PS = 6_250
VCO_PERIOD_PS = Fraction(1_000_000, 2_400)  # 2.4 GHz VCO: 416 2/3 ps
NOMINAL_PHASE_STEP_PS = 200
MAX_PHASE_GAP_PS = 250
MIN_RESET_ATTEMPTS = 3
MIN_OVERLAY_ATTEMPTS = 1
REQUIRED_ATTEMPTS = MIN_RESET_ATTEMPTS + MIN_OVERLAY_ATTEMPTS


def native_phase_states(*, period_ps: int = PHASE_PERIOD_PS) -> list[dict[str, Any]]:
    """Return a deterministic <=250 ps cover made from real LMK local controls.

    SDCLKout3 has an 11-state local digital delay, a -0.5 VCO-cycle half
    step, and a 16-state local analog delay.  TICS Pro reports the effective
    analog delays below.  Selecting the native state nearest each 200 ps
    target gives 32 unique points around the 6.25 ns PL-clock period; the
    largest actual circular gap is 241 2/3 ps.  No nonexistent uniform
    250 ps LMK setting is invented.
    """

    if period_ps != PHASE_PERIOD_PS:
        raise ValueError(f"native LMK phase cover is frozen for {PHASE_PERIOD_PS} ps")
    analog_options = [(False, None, 0)] + [
        (True, index, delay_ps)
        for index, delay_ps in enumerate(
            (700, 1300, 1450, 1600, 1750, 1900, 2050, 2200,
             2350, 2500, 2650, 2800, 2950, 3100, 3250, 3400)
        )
    ]
    digital_options = [(0, 0)] + [(index, index + 1) for index in range(1, 11)]
    period = Fraction(period_ps)
    candidates: list[dict[str, Any]] = []
    for adly_enabled, adly_index, analog_delay_ps in analog_options:
        for ddly_index, ddly_cycles in digital_options:
            for half_step in (0, 1):
                phase = (
                    Fraction(analog_delay_ps)
                    + ddly_cycles * VCO_PERIOD_PS
                    - half_step * VCO_PERIOD_PS / 2
                ) % period
                candidates.append(
                    {
                        "phase_fraction_ps": phase,
                        "adly_enabled": adly_enabled,
                        "adly_index": adly_index,
                        "adly_ps": analog_delay_ps,
                        "ddly_index": ddly_index,
                        "ddly_cycles": ddly_cycles,
                        "half_step": half_step,
                    }
                )

    chosen: list[dict[str, Any]] = []
    used_phases: set[Fraction] = set()
    for target_ps in range(0, period_ps, NOMINAL_PHASE_STEP_PS):
        ranked = sorted(
            candidates,
            key=lambda item: (
                min(
                    abs(item["phase_fraction_ps"] - target_ps),
                    period - abs(item["phase_fraction_ps"] - target_ps),
                ),
                bool(item["adly_enabled"]),
                int(item["ddly_index"]),
                int(item["half_step"]),
                -1 if item["adly_index"] is None else int(item["adly_index"]),
            ),
        )
        selected = next(item for item in ranked if item["phase_fraction_ps"] not in used_phases)
        used_phases.add(selected["phase_fraction_ps"])
        chosen.append({**selected, "nominal_target_ps": target_ps})

    chosen.sort(key=lambda item: item["phase_fraction_ps"])
    for index, item in enumerate(chosen):
        phase = item.pop("phase_fraction_ps")
        item["phase_ps"] = round(float(phase), 6)
        item["phase_numerator_ps"] = int(phase.numerator)
        item["phase_denominator"] = int(phase.denominator)
        item["phase_index"] = index
    gaps = [
        (chosen[(index + 1) % len(chosen)]["phase_ps"] - item["phase_ps"]) % period_ps
        for index, item in enumerate(chosen)
    ]
    if max(gaps) > MAX_PHASE_GAP_PS + 1e-6:
        raise RuntimeError("native LMK phase cover exceeds the registered 250 ps maximum gap")
    return chosen


def phase_grid(*, period_ps: int = PHASE_PERIOD_PS) -> list[float]:
    return [float(item["phase_ps"]) for item in native_phase_states(period_ps=period_ps)]


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _attempt_passed(attempt: dict[str, Any], *, frequency_hz: int) -> bool:
    adc = [int(value) for value in attempt.get("adc_latency", [])]
    dac = [int(value) for value in attempt.get("dac_latency", [])]
    delta = attempt.get("sysref_capture_delta", {})
    duration = float(attempt.get("capture_interval_seconds", 0.0))
    expected_edges = float(frequency_hz) * duration
    tolerance = max(expected_edges * 0.02, 2.0)
    counts_ok = bool(
        duration > 0.0
        and all(
            abs(float(delta.get(domain, -1)) - expected_edges) <= tolerance
            for domain in ("pl_160mhz", "adc_80mhz", "dac_80mhz")
        )
    )
    return bool(
        attempt.get("mts_passed")
        and attempt.get("pll1_locked")
        and attempt.get("pll2_locked")
        and len(adc) == 4
        and len(dac) == 4
        and len(set(adc)) == 1
        and len(set(dac)) == 1
        and counts_ok
    )


def assess_point(point: dict[str, Any], *, frequency_hz: int) -> dict[str, Any]:
    attempts = list(point.get("attempts", []))
    reset_attempts = sum(str(item.get("kind")) == "rfdc_reset" for item in attempts)
    overlay_attempts = sum(str(item.get("kind")) == "overlay_reload" for item in attempts)
    attempt_pass = [_attempt_passed(item, frequency_hz=frequency_hz) for item in attempts]
    profile_path = Path(str(point.get("tics_profile_path", "")))
    profile_sha = str(point.get("tics_profile_sha256", "")).lower()
    profile_ok = bool(
        profile_path.is_file()
        and len(profile_sha) == 64
        and file_sha256(profile_path) == profile_sha
        and bool(point.get("tics_pro_exported", False))
    )
    passed = bool(
        profile_ok
        and reset_attempts >= MIN_RESET_ATTEMPTS
        and overlay_attempts >= MIN_OVERLAY_ATTEMPTS
        and len(attempts) >= REQUIRED_ATTEMPTS
        and all(attempt_pass)
    )
    return {
        **point,
        "profile_identity_ok": profile_ok,
        "reset_attempts": reset_attempts,
        "overlay_attempts": overlay_attempts,
        "attempt_pass": attempt_pass,
        "passed": passed,
    }


def longest_cyclic_pass_window(passed: Iterable[bool]) -> tuple[int, int]:
    values = [bool(value) for value in passed]
    count = len(values)
    if count == 0 or not any(values):
        return (-1, 0)
    if all(values):
        return (0, count)
    best_start = -1
    best_length = 0
    run_start = 0
    run_length = 0
    doubled = values + values
    for index, value in enumerate(doubled):
        if value:
            if run_length == 0:
                run_start = index
            run_length = min(run_length + 1, count)
            if run_length > best_length and run_start < count:
                best_start = run_start
                best_length = run_length
        else:
            run_length = 0
    return (best_start % count, best_length)


def select_eye(
    points: list[dict[str, Any]],
    *,
    frequency_hz: int,
    setup_ns: float,
    hold_ns: float,
    period_ps: int = PHASE_PERIOD_PS,
) -> dict[str, Any]:
    expected_states = native_phase_states(period_ps=period_ps)
    expected_grid = [round(float(item["phase_ps"]), 6) for item in expected_states]
    by_delay = {round(float(point["delay_ps"]), 6): point for point in points}
    if sorted(by_delay) != expected_grid or len(points) != len(expected_grid):
        raise ValueError("phase evidence must contain every native grid point exactly once")
    assessed = [assess_point(by_delay[delay], frequency_hz=frequency_hz) for delay in expected_grid]
    start_index, length = longest_cyclic_pass_window(point["passed"] for point in assessed)
    circular_gaps = [
        (expected_grid[(index + 1) % len(expected_grid)] - delay) % period_ps
        for index, delay in enumerate(expected_grid)
    ]
    # Adjacent passing samples prove only the interval between their centres.
    if length <= 1:
        width_ps = 0.0
    elif length == len(expected_grid):
        # With no failing boundary, report the conservative covered width.
        width_ps = float(period_ps - max(circular_gaps))
    else:
        last_index = (start_index + length - 1) % len(expected_grid)
        width_ps = float((expected_grid[last_index] - expected_grid[start_index]) % period_ps)
    required_width_ps = int(round((float(setup_ns) + float(hold_ns) + 1.0) * 1000.0))
    qualified = bool(start_index >= 0 and width_ps >= required_width_ps)
    selected_delay_ps = None
    if qualified:
        midpoint = (expected_grid[start_index] + width_ps / 2.0) % period_ps
        run_indices = [(start_index + offset) % len(expected_grid) for offset in range(length)]
        selected_index = min(
            run_indices,
            key=lambda index: min(
                (expected_grid[index] - midpoint) % period_ps,
                (midpoint - expected_grid[index]) % period_ps,
            ),
        )
        selected_delay_ps = expected_grid[selected_index]
    return {
        "schema_version": 2,
        "frequency_hz": int(frequency_hz),
        "period_ps": int(period_ps),
        "nominal_phase_step_ps": NOMINAL_PHASE_STEP_PS,
        "maximum_actual_phase_gap_ps": max(circular_gaps),
        "phase_grid_policy": "LMK04828_SDCLKOUT3_NATIVE_DDLY_HS_ADLY_EXHAUSTIVE_COVER",
        "routed_setup_ns": float(setup_ns),
        "routed_hold_ns": float(hold_ns),
        "required_eye_width_ps": required_width_ps,
        "longest_eye_start_ps": (
            expected_grid[start_index] if start_index >= 0 else None
        ),
        "longest_eye_point_count": length,
        "longest_eye_width_ps": width_ps,
        "selected_delay_ps": selected_delay_ps,
        "qualified": qualified,
        "classification": "PHASE_EYE_QUALIFIED" if qualified else "NO_QUALIFIED_PHASE_EYE",
        "points": assessed,
    }


def campaign_template(*, frequency_hz: int, profile_prefix: str) -> dict[str, Any]:
    states = native_phase_states()
    return {
        "schema_version": 2,
        "stage": "34c-2R",
        "frequency_hz": int(frequency_hz),
        "period_ps": PHASE_PERIOD_PS,
        "nominal_phase_step_ps": NOMINAL_PHASE_STEP_PS,
        "maximum_phase_gap_ps": MAX_PHASE_GAP_PS,
        "phase_grid_policy": "LMK04828_SDCLKOUT3_NATIVE_DDLY_HS_ADLY_EXHAUSTIVE_COVER",
        "points": [
            {
                "delay_ps": state["phase_ps"],
                "nominal_target_ps": state["nominal_target_ps"],
                "phase_controls": {
                    key: state[key]
                    for key in (
                        "adly_enabled", "adly_index", "adly_ps", "ddly_index",
                        "ddly_cycles", "half_step", "phase_numerator_ps", "phase_denominator",
                    )
                },
                "profile_id": f"{profile_prefix}_sdclkout3_phase_{state['phase_index']:02d}",
                "tics_profile_path": "",
                "tics_profile_sha256": "",
                "tics_pro_exported": False,
                "attempts": [],
            }
            for state in states
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    template_parser = subparsers.add_parser("template")
    template_parser.add_argument("--frequency-hz", type=int, choices=(5_000_000, 10_000_000), required=True)
    template_parser.add_argument("--profile-prefix", required=True)
    template_parser.add_argument("--output", type=Path, required=True)
    select_parser = subparsers.add_parser("select")
    select_parser.add_argument("--input", type=Path, required=True)
    select_parser.add_argument("--output", type=Path, required=True)
    select_parser.add_argument("--setup-ns", type=float, required=True)
    select_parser.add_argument("--hold-ns", type=float, required=True)
    args = parser.parse_args()
    if args.command == "template":
        result = campaign_template(
            frequency_hz=args.frequency_hz,
            profile_prefix=args.profile_prefix,
        )
    else:
        campaign = json.loads(args.input.read_text(encoding="utf-8"))
        result = select_eye(
            list(campaign["points"]),
            frequency_hz=int(campaign["frequency_hz"]),
            setup_ns=args.setup_ns,
            hold_ns=args.hold_ns,
            period_ps=int(campaign.get("period_ps", PHASE_PERIOD_PS)),
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "points"}, sort_keys=True))
    return 0 if result.get("qualified", True) else 2


if __name__ == "__main__":
    raise SystemExit(main())
