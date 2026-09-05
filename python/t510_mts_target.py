"""Canonical RFDC MTS fixed-latency target policy."""

from __future__ import annotations

from typing import Any


MTS_LATENCY_QUANTUM = 12
MTS_TARGET_MARGIN = {"adc": 20, "dac": 16}
MTS_TARGET_HEADROOM_QUANTA = 1
T510_DAC_SYSREF_T1_PERIOD = 720
T510_ONBOARD_TCXO_EVIDENCE_BOUNDS = {
    "adc": {"min": 360, "max": 456},
    "dac": {"min": 32, "max": 416},
}
# The pre-r6 deterministic candidate was based on the then-known maximum 384.
T510_ONBOARD_DAC_NOMINAL_TARGET = 384 + MTS_TARGET_MARGIN["dac"]
T510_ONBOARD_DAC_PERIOD_BRANCH_CEILING = (
    32
    + T510_DAC_SYSREF_T1_PERIOD // 2
)
T510_ONBOARD_DAC_RELATIVE_ALIGNMENT_REFERENCE = 392
T510_ONBOARD_DAC_INFEASIBLE_WITNESS = (32, 384, 416)
T510_ONBOARD_TCXO_FIXED_TARGETS = {
    "adc": 492,
    # The TCXO/free-run science contract needs inter-tile alignment, not a
    # deterministic DAC total latency.  The accumulated circular latency
    # witness has no fixed target within the driver's correction limit.
    "dac": -1,
}
T510_MTS_DELAY_MAX = 31


def fixed_latency_target(max_observed: int, *, kind: str) -> dict[str, Any]:
    """Round the margin floor upward and reserve one full RFDC quantum.

    The AMD driver rejects a target that lands on its minimum-possible
    boundary, even when the reported target and minimum print identically.
    """

    if kind not in MTS_TARGET_MARGIN:
        raise ValueError(f"unknown MTS kind: {kind}")
    maximum = int(max_observed)
    if maximum < 0:
        raise ValueError("max_observed must be non-negative")
    quantum = MTS_LATENCY_QUANTUM
    margin = MTS_TARGET_MARGIN[kind]
    margin_floor = maximum + margin
    quantized_margin_floor = ((margin_floor + quantum - 1) // quantum) * quantum
    target = quantized_margin_floor + MTS_TARGET_HEADROOM_QUANTA * quantum
    return {
        "max_observed": maximum,
        "nominal_margin": margin,
        "margin_floor": margin_floor,
        "latency_quantum": quantum,
        "quantized_margin_floor": quantized_margin_floor,
        "headroom_quanta": MTS_TARGET_HEADROOM_QUANTA,
        "target": target,
    }


def periodic_fixed_latency_target(
    observations: list[int] | tuple[int, ...],
    *,
    kind: str,
    period: int,
    reference_target: int,
) -> dict[str, Any]:
    """Map SYSREF-period-equivalent discovery branches before targeting."""

    raw = [int(value) for value in observations]
    if not raw:
        raise ValueError("latency observations must not be empty")
    if int(period) <= 0:
        raise ValueError("period must be positive")
    reference = int(reference_target)

    def normalize(value: int) -> int:
        difference = reference - value
        offset_value = value + int(period) if difference > 0 else value - int(period)
        offset_difference = reference - offset_value
        # Match xrfdc_mts.c exactly: only inspect the branch in the direction
        # selected by LatencyDiff, and retain the raw branch on an exact tie.
        return offset_value if abs(difference) > abs(offset_difference) else value

    normalized = [normalize(value) for value in raw]
    policy = fixed_latency_target(max(normalized), kind=kind)
    return {
        **policy,
        "raw_observations": raw,
        "normalized_observations": normalized,
        "period": int(period),
        "reference_target": reference,
        "raw_max_observed": max(raw),
    }


def _driver_delay_offset(target: int, latency: int, *, factor: int = 12) -> int:
    delta = max(int(target) - int(latency), 0)
    integer, remainder = divmod(delta, int(factor))
    return integer + (1 if remainder > int(factor) // 2 else 0)


def _driver_period_normalize(latency: int, target: int, period: int) -> int:
    difference = int(target) - int(latency)
    alternative = (
        int(latency) + int(period)
        if difference > 0
        else int(latency) - int(period)
    )
    alternative_difference = int(target) - alternative
    return alternative if abs(difference) > abs(alternative_difference) else int(latency)


def feasible_dac_fixed_targets(
    observations: list[int] | tuple[int, ...],
    *,
    period: int = T510_DAC_SYSREF_T1_PERIOD,
) -> list[int]:
    """Return target residues reachable for every observed DAC latency."""

    values = [int(value) for value in observations]
    feasible: list[int] = []
    # The driver considers only the raw branch and one adjacent SYSREF-period
    # branch.  Above this finite bound even the highest adjusted observation
    # is more than the maximum correction range below the target.
    upper = max(values) + int(period) + T510_MTS_DELAY_MAX * MTS_LATENCY_QUANTUM
    for target in range(upper + 1):
        normalized = [
            _driver_period_normalize(value, target, int(period)) for value in values
        ]
        if any(value > target for value in normalized):
            continue
        offsets = [_driver_delay_offset(target, value) for value in normalized]
        if any(value > T510_MTS_DELAY_MAX for value in offsets):
            continue
        final = [
            value + offset * MTS_LATENCY_QUANTUM
            for value, offset in zip(normalized, offsets)
        ]
        if all(abs(value - target) <= MTS_LATENCY_QUANTUM // 2 for value in final):
            feasible.append(target)
    return feasible


def onboard_tcxo_fixed_target_policy(
    adc_observations: list[int], dac_observations: list[int]
) -> dict[str, Any]:
    """Apply the frozen frozen-envelope envelope for the current TCXO image."""

    adc = [int(value) for value in adc_observations]
    dac = [int(value) for value in dac_observations]
    if not adc or not dac:
        raise ValueError("ADC and DAC discovery observations must not be empty")

    dac_normalized_policy = periodic_fixed_latency_target(
        dac,
        kind="dac",
        period=T510_DAC_SYSREF_T1_PERIOD,
        reference_target=T510_ONBOARD_DAC_RELATIVE_ALIGNMENT_REFERENCE,
    )
    normalized_dac = dac_normalized_policy["normalized_observations"]
    current = {"adc": {"min": min(adc), "max": max(adc)},
               "dac": {"min": min(normalized_dac), "max": max(normalized_dac)}}
    errors: list[str] = []
    # ADC keeps a deterministic target.  DAC is relative-only because the
    # accumulated circular states have no common target; its bounds are
    # recorded as evidence but do not gate a target calculation.
    for kind in ("adc",):
        if current[kind]["min"] < T510_ONBOARD_TCXO_EVIDENCE_BOUNDS[kind]["min"]:
            errors.append(
                f"{kind.upper()}_DISCOVERY_BELOW_FROZEN_MIN:"
                f"{current[kind]['min']}<{T510_ONBOARD_TCXO_EVIDENCE_BOUNDS[kind]['min']}"
            )
        if current[kind]["max"] > T510_ONBOARD_TCXO_EVIDENCE_BOUNDS[kind]["max"]:
            errors.append(
                f"{kind.upper()}_DISCOVERY_EXCEEDS_FROZEN_MAX:"
                f"{current[kind]['max']}>{T510_ONBOARD_TCXO_EVIDENCE_BOUNDS[kind]['max']}"
            )
        correction = _driver_delay_offset(
            T510_ONBOARD_TCXO_FIXED_TARGETS[kind], current[kind]["min"]
        )
        if correction > T510_MTS_DELAY_MAX:
            errors.append(
                f"{kind.upper()}_DISCOVERY_EXCEEDS_DELAY_RANGE:"
                f"required={correction}:max={T510_MTS_DELAY_MAX}"
            )
    if errors:
        raise ValueError(";".join(errors))

    feasible_witness_targets = feasible_dac_fixed_targets(
        T510_ONBOARD_DAC_INFEASIBLE_WITNESS
    )
    if feasible_witness_targets:
        raise ValueError(
            "DAC_INFEASIBLE_WITNESS_UNEXPECTEDLY_HAS_TARGETS:"
            f"{feasible_witness_targets}"
        )

    return {
        "targets": dict(T510_ONBOARD_TCXO_FIXED_TARGETS),
        "derivation": {
            "policy": "frozen_multi_attempt_envelope",
            "source": "Stage35 free-run/sample0 contract plus current qualification evidence",
            "latency_quantum": MTS_LATENCY_QUANTUM,
            "delay_max": T510_MTS_DELAY_MAX,
            "frozen_evidence_bounds": T510_ONBOARD_TCXO_EVIDENCE_BOUNDS,
            "current_observed_bounds": current,
            "dac_sysref_t1_period": T510_DAC_SYSREF_T1_PERIOD,
            "dac_raw_observations": dac,
            "dac_normalized_observations": normalized_dac,
            "dac_nominal_margin": MTS_TARGET_MARGIN["dac"],
            "dac_nominal_target": T510_ONBOARD_DAC_NOMINAL_TARGET,
            "dac_period_branch_ceiling": T510_ONBOARD_DAC_PERIOD_BRANCH_CEILING,
            "dac_alignment_mode": "single_device_relative",
            "dac_deterministic_target_feasible": False,
            "dac_deterministic_infeasible_witness": list(
                T510_ONBOARD_DAC_INFEASIBLE_WITNESS
            ),
            "dac_feasible_fixed_targets": feasible_witness_targets,
            "worst_case_frozen_offsets": {
                "adc": _driver_delay_offset(
                    T510_ONBOARD_TCXO_FIXED_TARGETS["adc"],
                    T510_ONBOARD_TCXO_EVIDENCE_BOUNDS["adc"]["min"],
                ),
                "dac": None,
            },
        },
    }


def external_10mhz_fixed_target_policy(
    adc_observations: list[int], dac_observations: list[int]
) -> dict[str, Any]:
    """Derive conservative targets from a complete external-reference discovery."""

    adc = [int(value) for value in adc_observations]
    dac = [int(value) for value in dac_observations]
    if not adc or not dac:
        raise ValueError("ADC and DAC discovery observations must not be empty")
    adc_policy = fixed_latency_target(max(adc), kind="adc")
    dac_policy = fixed_latency_target(max(dac), kind="dac")
    feasible = [
        target
        for target in feasible_dac_fixed_targets(dac)
        if target >= int(dac_policy["target"])
    ]
    dac_target = min(feasible) if feasible else -1
    targets = {"adc": int(adc_policy["target"]), "dac": int(dac_target)}
    bounds = {
        "adc": {"min": min(adc), "max": max(adc)},
        "dac": {"min": min(dac), "max": max(dac)},
    }
    return {
        "targets": targets,
        "derivation": {
            "policy": "complete_discovery_envelope",
            "source": "external_10mhz 40-cycle discovery",
            "latency_quantum": MTS_LATENCY_QUANTUM,
            "delay_max": T510_MTS_DELAY_MAX,
            "frozen_evidence_bounds": bounds,
            "current_observed_bounds": bounds,
            "dac_sysref_t1_period": T510_DAC_SYSREF_T1_PERIOD,
            "dac_raw_observations": dac,
            "dac_normalized_observations": dac,
            "dac_nominal_margin": MTS_TARGET_MARGIN["dac"],
            "dac_nominal_target": int(dac_policy["target"]),
            "dac_period_branch_ceiling": max(dac),
            "dac_alignment_mode": (
                "deterministic_target" if dac_target >= 0 else "single_device_relative"
            ),
            "dac_deterministic_target_feasible": dac_target >= 0,
            "dac_deterministic_infeasible_witness": [] if dac_target >= 0 else sorted(set(dac)),
            "dac_feasible_fixed_targets": feasible,
            "worst_case_frozen_offsets": {
                "adc": _driver_delay_offset(targets["adc"], min(adc)),
                "dac": (
                    max(_driver_delay_offset(dac_target, value) for value in dac)
                    if dac_target >= 0
                    else None
                ),
            },
        },
    }
