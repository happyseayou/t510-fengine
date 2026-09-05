#!/usr/bin/env python3
"""Stage 34c-2 reversible clock-reference and SYSREF causal campaign."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import random
import statistics
import sys
import time
from typing import Any

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import t510_astronomy as astronomy
import t510_adc_correlated_noise_campaign as c34c
from scripts import t510_fullband_spur_scan as fullband
from scripts.t510_plot_spec_udp_pcap import collect_spectra


CORE_VERSION = "0x00010035"
BITSTREAM_ID = "fengine-0x00010035"
BITSTREAM_SHA256 = "8934a0c2d7033494b49133d846f954b52a6fa76a54b65c043c6e7be5289728d1"
PFB_PROFILE_ID = "0x34a80001"
BOARD_ID = 1
CENTER_MHZ = 1020.0
LOW_RF_CENTER_MHZ = 160.0
LOW_RF_NOMINAL_VCXO_MHZ = 122.88
# 122.88 MHz itself is not an exact 4096-channel bin at either 160 or
# 320 MS/s.  This is the common nearest bin for both sample rates.
LOW_RF_VCXO_CAPTURE_MHZ = 122.890625
LANE_MASK = 0x05
LANES = (0, 2)
FIXED_RF_MHZ = (960.0,)
GRID_RF_MHZ = (970.0, 980.0, 990.0, 1000.0, 1010.0, 1030.0, 1040.0, 1050.0, 1060.0, 1070.0, 1080.0)
FIVE_GRID_ONLY_RF_MHZ = (
    965.0, 975.0, 985.0, 995.0, 1005.0, 1015.0,
    1025.0, 1035.0, 1045.0, 1055.0, 1065.0, 1075.0,
)
OFFGRID_RF_MHZ = (966.875, 988.75, 1007.5, 1032.5, 1051.25, 1073.125)
RF_FREQUENCIES_MHZ = (
    FIXED_RF_MHZ + GRID_RF_MHZ + FIVE_GRID_ONLY_RF_MHZ + OFFGRID_RF_MHZ
)
LOW_RF_MARKERS_MHZ = (
    80.0,
    90.0,
    100.0,
    110.0,
    120.0,
    LOW_RF_VCXO_CAPTURE_MHZ,
    130.0,
    140.0,
    150.0,
)
RATES_MSPS = (160, 320)
CONT_PROFILE = "160m_10m_cont_manual_clkin2"
EXT_GATED_PROFILE = "160m_10m_request_clkin2_sdclkout3_phase_15"
FIVE_GATED_PROFILE = "160m_5m_request_clkin2_sdclkout3_phase_15"
TCXO_GATED_PROFILE = "160m_10m_request_manual_clkin0"
REQUIRED_PROFILES = (CONT_PROFILE, EXT_GATED_PROFILE, FIVE_GATED_PROFILE)
PROFILES = REQUIRED_PROFILES + (TCXO_GATED_PROFILE,)
PROFILE_LABEL = {
    CONT_PROFILE: "EXT_CONT",
    EXT_GATED_PROFILE: "EXT_10M_GATED",
    FIVE_GATED_PROFILE: "EXT_5M_GATED",
    TCXO_GATED_PROFILE: "TCXO_GATED",
}
FORMAL_SECONDS = 600
SCREEN_SECONDS = 120
LOW_RF_SECONDS = 60
PACKETS_PER_BLOCK = 32
TEMP_WARNING_C = 2.0
TEMP_HARD_C = 2.5
from python.t510_mts_target import (
    MTS_LATENCY_QUANTUM,
    MTS_TARGET_HEADROOM_QUANTA,
    MTS_TARGET_MARGIN,
    fixed_latency_target,
)
FROZEN_TARGET_EVIDENCE = {
    CONT_PROFILE: {
        "evidence_bound": {"adc": 732, "dac": 192},
        "basis": (
            "r1/r2/r3 continuous discovery plus the r1 RFDC-reported ADC "
            "minimum 732; r2/r3 each completed 10/10 fixed"
        ),
        "source_sha256": (
            "231967e6661de389c5731a7e46304ab576da2cbf94fd5eb94a3cd4a4cb64f0d9",
            "dc7aacb42217cb2c0a86478aead1510fac7d2ae7b482a32068c14cc66534c5c2",
            "7ed31e029f22cc03e85f33fbf469e755b639117a4693603b1be59908ca72967c",
        ),
    },
    EXT_GATED_PROFILE: {
        "evidence_bound": {"adc": 780, "dac": 216},
        "basis": (
            "10 MHz 32-phase eye, 128 attempts, plus the r3 RFDC-reported "
            "ADC minimum 780"
        ),
        "source_sha256": (
            "94def19a531bf414b876dc3ff0ab52efc5a0ba0995cc3fd4f32db113d69649e9",
            "c8b4c905c3dfb3509214e5714c8154e8f5f55963a86e95414539faab596f2b39",
            "9b7fc3a4267b33b6b1705588b6894bd9c6946e60ca47cc692c4c888de3da7b38",
        ),
    },
    FIVE_GATED_PROFILE: {
        "evidence_bound": {"adc": 1140, "dac": 216},
        "basis": "corrected 5 MHz 32-phase eye, 128 attempts",
        "source_sha256": (
            "1c612ff9c344bcba7a0c2710de71c17c011c068baa25d723d35c165d85d51773",
        ),
    },
    TCXO_GATED_PROFILE: {
        "evidence_bound": {"adc": 780, "dac": 216},
        "basis": (
            "conservative inheritance from the 10 MHz all-evidence envelope, "
            "including the RFDC-reported ADC minimum 780"
        ),
        "source_sha256": (
            "94def19a531bf414b876dc3ff0ab52efc5a0ba0995cc3fd4f32db113d69649e9",
        ),
    },
}


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def formal_triplet_plan(layer: str) -> list[dict[str, Any]]:
    if layer == "sysref":
        conditions = (
            ("A1", CONT_PROFILE),
            ("B", EXT_GATED_PROFILE),
            ("A2", CONT_PROFILE),
        )
    elif layer == "reference":
        conditions = (
            ("A1", EXT_GATED_PROFILE),
            ("B", TCXO_GATED_PROFILE),
            ("A2", EXT_GATED_PROFILE),
        )
    elif layer == "frequency":
        conditions = (
            ("A1", EXT_GATED_PROFILE),
            ("B", FIVE_GATED_PROFILE),
            ("A2", EXT_GATED_PROFILE),
        )
    else:
        raise ValueError("layer must be sysref, frequency, or reference")
    rows: list[dict[str, Any]] = []
    rate_orders = ((160, 320), (320, 160), (160, 320))
    triplet = 0
    for repeat, rate_order in enumerate(rate_orders, start=1):
        for rate in rate_order:
            triplet += 1
            for condition, profile_id in conditions:
                rows.append(
                    {
                        "layer": layer,
                        "repeat": repeat,
                        "triplet": triplet,
                        "sample_rate_msps": rate,
                        "condition": condition,
                        "profile_id": profile_id,
                        "name": f"{layer}_t{triplet:02d}_{rate}msps_r{repeat}_{condition.lower()}_{PROFILE_LABEL[profile_id].lower()}",
                    }
                )
    return rows


def screening_plan() -> list[dict[str, Any]]:
    rows = []
    layers = (
        ("sysref", (("A1", CONT_PROFILE), ("B", EXT_GATED_PROFILE), ("A2", CONT_PROFILE))),
        ("frequency", (("A1", EXT_GATED_PROFILE), ("B", FIVE_GATED_PROFILE), ("A2", EXT_GATED_PROFILE))),
        ("reference", (("A1", EXT_GATED_PROFILE), ("B", TCXO_GATED_PROFILE), ("A2", EXT_GATED_PROFILE))),
    )
    for layer, conditions in layers:
        for rate in RATES_MSPS:
            for condition, profile_id in conditions:
                rows.append(
                    {
                        "layer": layer,
                        "condition": condition,
                        "profile_id": profile_id,
                        "sample_rate_msps": rate,
                        "name": f"screen_{layer}_{rate}msps_{condition.lower()}_{PROFILE_LABEL[profile_id].lower()}",
                    }
                )
    return rows


def low_rf_plan(*, include_tcxo: bool = True) -> list[dict[str, Any]]:
    profiles = PROFILES if include_tcxo else REQUIRED_PROFILES
    return [
        {
            "profile_id": profile,
            "sample_rate_msps": rate,
            "name": f"lowrf_{rate}msps_{PROFILE_LABEL[profile].lower()}",
        }
        for profile in profiles
        for rate in RATES_MSPS
    ]


def receiver_prepare(
    args: argparse.Namespace, sample_rate_msps: int, center_mhz: float
) -> dict[str, Any]:
    return c34c.receiver_prepare(
        args.receiver_base, sample_rate_msps, "spec_only", center_mhz
    )


def fresh_configure(
    args: argparse.Namespace,
    template: dict[str, Any],
    sample_rate_msps: int,
    center_mhz: float,
) -> dict[str, Any]:
    return c34c.configure(
        args,
        template,
        sample_rate_msps,
        "spec_only",
        center_mhz,
    )


def prepare_clock(
    args: argparse.Namespace,
    profile_id: str,
    sample_rate_msps: int,
    center_mhz: float,
    *,
    target: dict[str, int] | None = None,
    discovery: bool = False,
    negative_control: bool = False,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "expected_board_id": BOARD_ID,
        "profile_id": profile_id,
        "sample_rate_msps": sample_rate_msps,
        "center_mhz": center_mhz,
        "receiver_stream_accepting": False,
        "mts_target_mode": "discovery" if discovery else ("fixed" if target else "catalog"),
        "verify_sysref_negative_control": bool(negative_control),
    }
    if target is not None:
        body["mts_adc_target_latency"] = int(target["adc"])
        body["mts_dac_target_latency"] = int(target["dac"])
    return fullband._http_json(
        args.agent_base.rstrip("/") + "/api/v2/clock/diagnostic/prepare",
        method="POST",
        body=body,
        timeout=240.0,
    )


def restore_clock(args: argparse.Namespace) -> dict[str, Any]:
    return fullband._http_json(
        args.agent_base.rstrip("/") + "/api/v2/clock/diagnostic/restore",
        method="POST",
        body={
            "expected_board_id": BOARD_ID,
            "receiver_stream_accepting": False,
        },
        timeout=240.0,
    )


def observed_latencies(result: dict[str, Any], kind: str) -> list[int]:
    row = result.get("mts", {}).get(kind, {})
    values = row.get("active_measured_latency") or row.get("measured_latency") or []
    return [int(value) for value in values]


def frozen_profile_target_policy(profile_id: str) -> dict[str, Any]:
    try:
        evidence = FROZEN_TARGET_EVIDENCE[profile_id]
    except KeyError as exc:
        raise ValueError(f"profile has no frozen MTS target evidence: {profile_id}") from exc
    evidence_bound = evidence["evidence_bound"]
    derivation = {
        kind: fixed_latency_target(int(evidence_bound[kind]), kind=kind)
        for kind in ("adc", "dac")
    }
    return {
        "profile_id": profile_id,
        "policy": "frozen_all_evidence_envelope_v1",
        "basis": evidence["basis"],
        "source_sha256": list(evidence["source_sha256"]),
        "evidence_bound": {
            kind: int(evidence_bound[kind]) for kind in ("adc", "dac")
        },
        "derivation": derivation,
        "target": {kind: derivation[kind]["target"] for kind in ("adc", "dac")},
    }


def frozen_target_policy_sha256() -> str:
    payload = {
        profile_id: frozen_profile_target_policy(profile_id)
        for profile_id in PROFILES
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def monitor_frequency_contract() -> dict[str, Any]:
    """Prove every requested monitor frequency is an exact product PFB bin."""

    groups = {
        "science": (CENTER_MHZ, RF_FREQUENCIES_MHZ),
        "low_rf": (LOW_RF_CENTER_MHZ, LOW_RF_MARKERS_MHZ),
    }
    result: dict[str, Any] = {}
    for name, (center_mhz, frequencies_mhz) in groups.items():
        result[name] = {
            "center_mhz": center_mhz,
            "bins": {
                str(rate): {
                    f"{frequency:.9f}": astronomy.rf_to_signed_bin(
                        frequency, center_mhz, rate
                    )
                    for frequency in frequencies_mhz
                }
                for rate in RATES_MSPS
            },
        }
    return result


def validate_resume_checkpoint(path: Path) -> dict[str, Any]:
    """Validate the exact r4 low-RF-marker failure before reusing its gates."""

    source = json.loads(path.read_text())
    expected_identity = {
        "core_version": CORE_VERSION,
        "bitstream_id": BITSTREAM_ID,
        "bitstream_sha256": BITSTREAM_SHA256,
        "pfb_profile_id": PFB_PROFILE_ID,
    }
    for key, expected in expected_identity.items():
        if source.get(key) != expected:
            raise RuntimeError(
                f"resume checkpoint {key} mismatch: {source.get(key)!r} != {expected!r}"
            )
    policy = source.get("frozen_target_policy") or {}
    if policy.get("sha256") != frozen_target_policy_sha256():
        raise RuntimeError("resume checkpoint frozen MTS target policy mismatch")
    errors = source.get("errors") or []
    if (
        source.get("classification") != "STAGE34C2_OPERATIONAL_FAIL"
        or len(errors) != 1
        or "122.880000000 MHz is not on an exact PFB bin" not in str(errors[0])
    ):
        raise RuntimeError("resume checkpoint is not the registered r4 low-RF marker failure")

    qualifications = source.get("profile_qualification") or {}
    targets: dict[str, dict[str, int]] = {}
    for profile_id in REQUIRED_PROFILES:
        row = qualifications.get(profile_id) or {}
        if (
            not row.get("qualified")
            or len(row.get("discovery") or []) != 10
            or len(row.get("fixed") or []) != 10
        ):
            raise RuntimeError(
                f"resume checkpoint required profile is not 10/10 + 10/10: {profile_id}"
            )
        if row.get("target") != frozen_profile_target_policy(profile_id)["target"]:
            raise RuntimeError(f"resume checkpoint target mismatch: {profile_id}")
        targets[profile_id] = dict(row["target"])

    tcxo = qualifications.get(TCXO_GATED_PROFILE) or {}
    tcxo_qualified = bool(tcxo.get("qualified"))
    if tcxo_qualified:
        if len(tcxo.get("discovery") or []) != 10 or len(tcxo.get("fixed") or []) != 10:
            raise RuntimeError("resume checkpoint TCXO qualification is incomplete")
        targets[TCXO_GATED_PROFILE] = dict(tcxo["target"])
    else:
        targets[TCXO_GATED_PROFILE] = dict(targets[EXT_GATED_PROFILE])

    expected_screens = {
        row["name"]
        for row in screening_plan()
        if tcxo_qualified or row["profile_id"] != TCXO_GATED_PROFILE
    }
    completed_screens = {
        row.get("name")
        for row in source.get("runs") or []
        if row.get("duration_seconds") == SCREEN_SECONDS
        and row.get("ok") is True
        and not row.get("errors")
    }
    if completed_screens != expected_screens:
        raise RuntimeError(
            "resume checkpoint screening set mismatch: "
            f"missing={sorted(expected_screens - completed_screens)} "
            f"extra={sorted(completed_screens - expected_screens)}"
        )
    return {
        "source": str(path.resolve()),
        "source_sha256": sha256_file(path),
        "profile_qualification": qualifications,
        "targets": targets,
        "tcxo_qualified": tcxo_qualified,
        "reused_screening_names": sorted(completed_screens),
    }


def qualify_profile(
    args: argparse.Namespace,
    template: dict[str, Any],
    profile_id: str,
    *,
    checkpoint_path: Path | None = None,
) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "profile_id": profile_id,
        "discovery": [],
        "fixed": [],
        "qualified": False,
    }

    def checkpoint() -> None:
        if checkpoint_path is not None:
            write_json(checkpoint_path, evidence)

    checkpoint()
    adc_values: list[int] = []
    dac_values: list[int] = []
    for index in range(1, 11):
        fresh_configure(args, template, 320, CENTER_MHZ)
        result = prepare_clock(
            args, profile_id, 320, CENTER_MHZ, discovery=True
        )
        adc_values.extend(observed_latencies(result, "adc"))
        dac_values.extend(observed_latencies(result, "dac"))
        evidence["discovery"].append(result)
        checkpoint()
        restore_clock(args)
        print(f"CLOCK_PROFILE_DISCOVERY {PROFILE_LABEL[profile_id]} {index}/10", flush=True)
    if not adc_values or not dac_values:
        raise RuntimeError(f"{profile_id} discovery returned no MTS latencies")
    target_policy = frozen_profile_target_policy(profile_id)
    observed_discovery_max = {"adc": max(adc_values), "dac": max(dac_values)}
    target_policy["observed_discovery_max"] = observed_discovery_max
    for kind in ("adc", "dac"):
        if observed_discovery_max[kind] > target_policy["evidence_bound"][kind]:
            evidence["target_policy"] = target_policy
            checkpoint()
            raise RuntimeError(
                f"{profile_id} discovery {kind} latency {observed_discovery_max[kind]} "
                f"exceeds frozen envelope {target_policy['evidence_bound'][kind]}"
            )
    target = dict(target_policy["target"])
    evidence["target_policy"] = target_policy
    evidence["target"] = target
    checkpoint()
    for index in range(1, 11):
        fresh_configure(args, template, 320, CENTER_MHZ)
        result = prepare_clock(
            args, profile_id, 320, CENTER_MHZ, target=target
        )
        # Persist the result before applying the qualification gate.  A failed
        # final cycle is evidence, not something to discard with the exception.
        evidence["fixed"].append(result)
        checkpoint()
        for kind in ("adc", "dac"):
            values = observed_latencies(result, kind)
            if len(values) != 4 or len(set(values)) != 1:
                raise RuntimeError(
                    f"{profile_id} fixed {kind} latency is not four-tile identical: {values}"
                )
        restore_clock(args)
        print(f"CLOCK_PROFILE_FIXED {PROFILE_LABEL[profile_id]} {index}/10", flush=True)
    if profile_id in (EXT_GATED_PROFILE, FIVE_GATED_PROFILE):
        fresh_configure(args, template, 320, CENTER_MHZ)
        negative = prepare_clock(
            args,
            profile_id,
            320,
            CENTER_MHZ,
            target=target,
            negative_control=True,
        )
        evidence["sysref_negative_control"] = negative.get(
            "sysref_negative_control"
        )
        checkpoint()
        if not (evidence["sysref_negative_control"] or {}).get("passed"):
            raise RuntimeError(
                f"{profile_id} external request SYSREF negative control did not pass"
            )
        restore_clock(args)
    evidence["qualified"] = True
    checkpoint()
    return evidence


def correlation(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or len(left) < 2:
        return 0.0
    left_mean = statistics.fmean(left)
    right_mean = statistics.fmean(right)
    a = [value - left_mean for value in left]
    b = [value - right_mean for value in right]
    denominator = math.sqrt(
        sum(value * value for value in a) * sum(value * value for value in b)
    )
    return sum(x * y for x, y in zip(a, b)) / denominator if denominator else 0.0


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "count": 0,
            "slope_pass_count": 0,
            "slope_pass_fraction": None,
            "median_slope": None,
            "median_shuffled_slope": None,
            "median_abs_lag1": None,
            "median_abs_slope_error": None,
        }
    return {
        "count": len(rows),
        "slope_pass_count": sum(int(row["slope_pass"]) for row in rows),
        "slope_pass_fraction": statistics.fmean(
            int(row["slope_pass"]) for row in rows
        ),
        "median_slope": statistics.median(float(row["slope"]) for row in rows),
        "median_shuffled_slope": statistics.median(
            float(row["shuffled_slope"]) for row in rows
        ),
        "median_abs_lag1": statistics.median(
            abs(float(row["lag1_correlation"])) for row in rows
        ),
        "median_abs_slope_error": statistics.median(
            abs(float(row["slope"]) + 0.5) for row in rows
        ),
    }


def analyze_monitor(
    raw: dict[str, Any], *, duration_seconds: int, seed: int
) -> dict[str, Any]:
    targets = {int(row["target_index"]): row for row in raw["targets"]}
    grouped: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for row in raw["power_seconds"]:
        lane = int(row["lane"])
        if lane in LANES:
            grouped.setdefault((lane, int(row["target_index"])), []).append(row)
    combinations: list[dict[str, Any]] = []
    series: dict[tuple[int, int], list[float]] = {}
    for key, rows in sorted(grouped.items()):
        lane, target_index = key
        rows.sort(key=lambda row: int(row["second"]))
        powers = [astronomy.mean_power_from_accumulator(row) for row in rows]
        if len(powers) < duration_seconds - 5:
            raise RuntimeError(
                f"ADC{lane} target {target_index} has only {len(powers)} seconds"
            )
        series[key] = powers
        raw_stats = astronomy.integration_statistics(powers)
        shuffled = list(powers)
        random.Random(seed ^ (lane << 16) ^ target_index).shuffle(shuffled)
        shuffled_stats = astronomy.integration_statistics(shuffled)
        rf_mhz = float(targets[target_index]["actual_rf_mhz"])
        group = (
            "fixed"
            if min(abs(rf_mhz - value) for value in FIXED_RF_MHZ) < 0.001
            else (
                "grid10"
                if min(abs(rf_mhz - value) for value in GRID_RF_MHZ) < 0.001
                else (
                    "grid5_only"
                    if min(abs(rf_mhz - value) for value in FIVE_GRID_ONLY_RF_MHZ) < 0.001
                    else "offgrid"
                )
            )
        )
        slope = float(raw_stats["slope"])
        combinations.append(
            {
                "lane": lane,
                "target_index": target_index,
                "requested_rf_mhz": float(targets[target_index]["requested_rf_mhz"]),
                "actual_rf_mhz": rf_mhz,
                "signed_bin": int(targets[target_index]["signed_bin"]),
                "group": group,
                "seconds": len(powers),
                "slope": slope,
                "shuffled_slope": float(shuffled_stats["slope"]),
                "slope_pass": -0.65 <= slope <= -0.35,
                "lag1_correlation": correlation(powers[:-1], powers[1:]),
                "mean_dbfs": float(raw_stats["mean_dbfs"]),
                "curve": raw_stats["curve"],
                "shuffled_curve": shuffled_stats["curve"],
                "power_series": powers,
            }
        )
    expected = len(LANES) * len(raw["targets"])
    if len(combinations) != expected:
        raise RuntimeError(
            f"monitor produced {len(combinations)} combinations, expected {expected}"
        )
    matrices: dict[str, list[list[float]]] = {}
    for lane in LANES:
        indexes = sorted(index for item_lane, index in series if item_lane == lane)
        matrices[str(lane)] = [
            [correlation(series[(lane, left)], series[(lane, right)]) for right in indexes]
            for left in indexes
        ]
    return {
        "combinations": combinations,
        "fixed": summarize([row for row in combinations if row["group"] == "fixed"]),
        "grid10": summarize([row for row in combinations if row["group"] == "grid10"]),
        "grid5_only": summarize(
            [row for row in combinations if row["group"] == "grid5_only"]
        ),
        "offgrid": summarize([row for row in combinations if row["group"] == "offgrid"]),
        "same_adc_frequency_correlation": matrices,
    }


def validate_clock_status(
    value: dict[str, Any], profile_id: str, transaction_id: str
) -> None:
    if value.get("state") != "ACTIVE" or not value.get("clock_transaction_valid"):
        raise RuntimeError(f"clock transaction is not active: {value}")
    if str(value.get("clock_transaction_id")) != transaction_id:
        raise RuntimeError("clock transaction ID changed")
    if str(value.get("profile_id")) != profile_id or not value.get("integrity_ok"):
        raise RuntimeError(f"clock profile integrity changed: {value}")
    live = value.get("live", {})
    if int(live.get("pll1_lock", 0)) != 1 or int(live.get("pll2_lock", 0)) != 1:
        raise RuntimeError(f"LMK PLL lost lock: {live}")
    if profile_id != CONT_PROFILE and (
        int(live.get("sysref_request_gpio", -1)) != 0
        or bool(live.get("sysref_output_expected_on", True))
    ):
        raise RuntimeError(f"MTS-only SYSREF became active during capture: {live}")


def wait_reference_watchdog_ready(args: argparse.Namespace) -> dict[str, Any]:
    deadline = time.monotonic() + 10.0
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        status = fullband._http_json(
            args.agent_base.rstrip("/") + "/api/v2/status", timeout=30.0
        )
        last = status.get("reference_watchdog", {})
        locks = last.get("lock_status") or {}
        if (
            last.get("healthy")
            and not last.get("stale", True)
            and int(locks.get("pll1_lock", 0)) == 1
            and int(locks.get("pll2_lock", 0)) == 1
        ):
            return last
        time.sleep(0.25)
    raise RuntimeError(f"reference watchdog did not become ready: {last}")


def wait_for_monitor(
    args: argparse.Namespace,
    *,
    duration_seconds: int,
    trace_path: Path,
    profile_id: str,
    transaction_id: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    deadline = time.monotonic() + duration_seconds + 90.0
    last_second = -1
    temperatures: dict[str, list[float]] = {}
    with c34c.IncrementalJsonTrace(trace_path) as trace:
        while time.monotonic() < deadline:
            receiver = fullband._http_json(
                args.receiver_base.rstrip("/")
                + "/api/measure/spec-stability/status"
            )
            clock = fullband._http_json(
                args.agent_base.rstrip("/") + "/api/v2/clock/diagnostic",
                timeout=30.0,
            )
            validate_clock_status(clock, profile_id, transaction_id)
            resident = fullband._http_json(
                args.agent_base.rstrip("/")
                + "/api/v2/rfdc/calibration/monitor"
            )
            calibration = resident.get("calibration", {})
            if int(calibration.get("frozen_adc_mask", -1)) != 0:
                raise RuntimeError("ADC calibration freeze mask changed")
            ocb1 = resident.get("ocb1", {}).get("state", {})
            if ocb1.get("ocb1_override_state") != "DYNAMIC":
                raise RuntimeError(f"OCB1 left DYNAMIC state: {ocb1}")
            second = int(receiver.get("elapsed_seconds", len(trace.rows)) or 0)
            if second != last_second:
                row = {
                    "elapsed_seconds": second,
                    "clock": clock,
                    "resident": resident,
                    "receiver": c34c.receiver_condensed(
                        fullband._http_json(
                            args.receiver_base.rstrip("/") + "/api/state"
                        )
                    ),
                }
                trace.append(row)
                last_second = second
                for name, value in c34c.extract_temperatures(resident).items():
                    temperatures.setdefault(name, []).append(value)
                gate = c34c.temperature_gate(
                    c34c.temperature_series_summary(temperatures)
                )
                if gate["failed_sensors"]:
                    raise RuntimeError(
                        f"temperature exceeded {TEMP_HARD_C:.1f} C hard span: {gate}"
                    )
            if receiver.get("status") == "completed":
                result = fullband._http_json(
                    args.receiver_base.rstrip("/")
                    + "/api/measure/spec-stability/result",
                    timeout=180.0,
                )
                return result, trace.rows
            if receiver.get("status") == "failed":
                raise RuntimeError(f"receiver monitor failed: {receiver.get('error')}")
            time.sleep(0.5)
    raise RuntimeError("receiver monitor did not complete before deadline")


def execute_run(
    args: argparse.Namespace,
    template: dict[str, Any],
    *,
    name: str,
    profile_id: str,
    sample_rate_msps: int,
    center_mhz: float,
    frequencies_mhz: tuple[float, ...],
    duration_seconds: int,
    target: dict[str, int],
    formal: bool,
    thermal_stabilize: bool,
) -> dict[str, Any]:
    run_dir = args.receiver_output / "runs" / name
    run_dir.mkdir(parents=True, exist_ok=False)
    result: dict[str, Any] = {
        "name": name,
        "profile_id": profile_id,
        "sample_rate_msps": sample_rate_msps,
        "center_mhz": center_mhz,
        "duration_seconds": duration_seconds,
        "started_at_unix_ms": time.time_ns() // 1_000_000,
        "ok": False,
        "errors": [],
    }
    write_json(run_dir / "result.json", result)
    try:
        result["configure"] = fresh_configure(
            args, template, sample_rate_msps, center_mhz
        )
        result["clock_prepare"] = prepare_clock(
            args,
            profile_id,
            sample_rate_msps,
            center_mhz,
            target=target,
        )
        transaction_id = str(result["clock_prepare"]["clock_transaction_id"])
        result["reference_watchdog_ready"] = wait_reference_watchdog_ready(args)
        result["start"] = fullband._http_json(
            args.agent_base.rstrip("/") + "/api/v2/start",
            method="POST",
            body={
                "expected_board_id": BOARD_ID,
                "clock_transaction_id": transaction_id,
            },
        )
        time.sleep(args.settle_seconds)
        if thermal_stabilize:
            result["thermal_stability"] = c34c.wait_for_thermal_stability(
                args,
                trace_path=run_dir / "thermal_stability.json",
                sample_rate_msps=sample_rate_msps,
                mode="spec_only",
            )
        before_board = fullband._http_json(
            args.agent_base.rstrip("/") + "/api/v2/status", timeout=30.0
        )
        before_receiver = fullband._http_json(
            args.receiver_base.rstrip("/") + "/api/state"
        )
        begin_capture = c34c.capture_run_edge(
            args, run_dir, "begin", "spec_only"
        )
        result["monitor_start"] = fullband._http_json(
            args.receiver_base.rstrip("/") + "/api/measure/spec-stability",
            method="POST",
            body={
                "duration_seconds": duration_seconds,
                "formal": bool(formal),
                "sample_rate_msps": sample_rate_msps,
                "center_mhz": center_mhz,
                "rf_frequencies_mhz": list(frequencies_mhz),
                "correlation_pair": [0, 2],
                "lane_mask": LANE_MASK,
                "include_time_statistics": False,
            },
        )
        print(f"CLOCK_RUN_MONITOR_HEALTHY {name}", flush=True)
        raw, trace = wait_for_monitor(
            args,
            duration_seconds=duration_seconds,
            trace_path=run_dir / "clock_ams_trace.json",
            profile_id=profile_id,
            transaction_id=transaction_id,
        )
        write_json(run_dir / "monitor_raw.json", raw)
        end_capture = c34c.capture_run_edge(
            args, run_dir, "end", "spec_only"
        )
        after_board = fullband._http_json(
            args.agent_base.rstrip("/") + "/api/v2/status", timeout=30.0
        )
        after_receiver = fullband._http_json(
            args.receiver_base.rstrip("/") + "/api/state"
        )
        integrity = fullband._window_integrity(
            before_board, after_board, before_receiver, after_receiver
        )
        if not integrity["ok"]:
            raise RuntimeError(f"digital integrity failed: {integrity['errors']}")
        analysis = analyze_monitor(
            raw,
            duration_seconds=duration_seconds,
            seed=int.from_bytes(hashlib.sha256(name.encode()).digest()[:4], "little"),
        )
        temperatures: dict[str, list[float]] = {}
        for item in trace:
            for sensor, value in c34c.extract_temperatures(item["resident"]).items():
                temperatures.setdefault(sensor, []).append(value)
        temperature_summary = c34c.temperature_series_summary(temperatures)
        result.update(
            {
                "ok": True,
                "classification": "STAGE34C2_RUN_COMPLETE",
                "analysis": analysis,
                "integrity": integrity,
                "begin_capture": begin_capture,
                "end_capture": end_capture,
                "before_board": before_board,
                "after_board": after_board,
                "temperature": temperature_summary,
                "temperature_gate": c34c.temperature_gate(temperature_summary),
            }
        )
    except Exception as exc:
        result["errors"].append(f"{type(exc).__name__}: {exc}")
        result["classification"] = "STAGE34C2_OPERATIONAL_FAIL"
        raise
    finally:
        result["errors"].extend(c34c.stop_and_mute(args, center_mhz))
        result["finished_at_unix_ms"] = time.time_ns() // 1_000_000
        if result["errors"]:
            result["ok"] = False
            result["classification"] = "STAGE34C2_OPERATIONAL_FAIL"
        write_json(run_dir / "result.json", result)
    return result


def condition_gate(
    runs: list[dict[str, Any]], group: str, *, grid: bool = False
) -> dict[str, Any]:
    by_rate: dict[str, Any] = {}
    for rate in RATES_MSPS:
        selected = [row for row in runs if row["sample_rate_msps"] == rate]
        combinations = [
            item
            for row in selected
            for item in row["analysis"]["combinations"]
            if item["group"] == group
        ]
        per_run = [
            [item for item in row["analysis"]["combinations"] if item["group"] == group]
            for row in selected
        ]
        summary = summarize(combinations)
        per_run_required = math.ceil(0.80 * len(per_run[0]))
        aggregate_required = math.ceil(0.80 * len(combinations))
        gates = {
            "three_repeats": len(selected) == 3,
            "each_repeat_pass_count": all(
                sum(int(item["slope_pass"]) for item in items) >= per_run_required
                for items in per_run
            ),
            "aggregate_pass_count": int(summary["slope_pass_count"])
            >= aggregate_required,
            "each_repeat_median_slope": all(
                -0.65
                <= statistics.median(float(item["slope"]) for item in items)
                <= -0.35
                for items in per_run
            ),
            "median_abs_lag1": float(summary["median_abs_lag1"]) <= 0.10,
            "raw_shuffled_delta": abs(
                float(summary["median_slope"])
                - float(summary["median_shuffled_slope"])
            )
            <= 0.10,
        }
        if not grid:
            gates["each_repeat_10_of_12"] = all(
                sum(int(item["slope_pass"]) for item in items) >= 10
                for items in per_run
            )
            gates["aggregate_29_of_36"] = int(summary["slope_pass_count"]) >= 29
        by_rate[str(rate)] = {
            "pass": all(gates.values()),
            "gates": gates,
            "summary": summary,
            "per_run_pass_count": [
                sum(int(item["slope_pass"]) for item in items) for items in per_run
            ],
        }
    return {
        "pass": all(row["pass"] for row in by_rate.values()),
        "by_rate": by_rate,
    }


def causal_metrics(
    a1_runs: list[dict[str, Any]],
    b_runs: list[dict[str, Any]],
    a2_runs: list[dict[str, Any]],
    group: str,
) -> dict[str, Any]:
    def rows(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            item
            for run in runs
            for item in run["analysis"]["combinations"]
            if item["group"] == group
        ]

    a1 = summarize(rows(a1_runs))
    b = summarize(rows(b_runs))
    a2 = summarize(rows(a2_runs))
    gates = {
        "pass_fraction_improves_50pp": float(b["slope_pass_fraction"])
        - float(a1["slope_pass_fraction"])
        >= 0.50,
        "slope_error_improves_0p12": float(a1["median_abs_slope_error"])
        - float(b["median_abs_slope_error"])
        >= 0.12,
        "lag_improves_0p10": float(a1["median_abs_lag1"])
        - float(b["median_abs_lag1"])
        >= 0.10,
        "a2_slope_returns": abs(
            float(a2["median_slope"]) - float(a1["median_slope"])
        )
        <= 0.10,
        "a2_lag_returns": abs(
            float(a2["median_abs_lag1"]) - float(a1["median_abs_lag1"])
        )
        <= 0.10,
    }
    return {"pass": all(gates.values()), "gates": gates, "A1": a1, "B": b, "A2": a2}


def classify_layers(runs: list[dict[str, Any]], tcxo_qualified: bool) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for layer in ("sysref", "frequency", "reference"):
        layer_runs = [row for row in runs if row["layer"] == layer]
        if layer == "reference" and not tcxo_qualified:
            result[layer] = {"classification": "TCXO_PROFILE_UNQUALIFIED"}
            continue
        conditions = {
            name: [row for row in layer_runs if row["condition"] == name]
            for name in ("A1", "B", "A2")
        }
        gates = {
            name: {
                "offgrid": condition_gate(rows, "offgrid"),
                "grid10": condition_gate(rows, "grid10", grid=True),
                "grid5_only": condition_gate(rows, "grid5_only", grid=True),
            }
            for name, rows in conditions.items()
        }
        offgrid_causal = causal_metrics(
            conditions["A1"], conditions["B"], conditions["A2"], "offgrid"
        )
        grid10_causal = causal_metrics(
            conditions["A1"], conditions["B"], conditions["A2"], "grid10"
        )
        grid5_causal = causal_metrics(
            conditions["A1"], conditions["B"], conditions["A2"], "grid5_only"
        )
        a_reproduced = (
            not gates["A1"]["offgrid"]["pass"]
            or not gates["A1"]["grid10"]["pass"]
            or not gates["A1"]["grid5_only"]["pass"]
        )
        if not a_reproduced:
            classification = "INCONCLUSIVE_BASELINE_NOT_REPRODUCED"
        elif layer == "sysref" and gates["A1"]["offgrid"]["pass"] and not gates["A1"]["grid10"]["pass"] and gates["B"]["grid10"]["pass"] and grid10_causal["pass"]:
            classification = "CONTINUOUS_SYSREF_CAUSAL_GRID_CONTAMINATION"
        elif layer == "sysref" and gates["B"]["offgrid"]["pass"] and offgrid_causal["pass"]:
            classification = "CONTINUOUS_SYSREF_CAUSAL_BROADBAND_CORRELATION"
        elif layer == "reference" and gates["B"]["offgrid"]["pass"] and offgrid_causal["pass"]:
            classification = "EXTERNAL_REFERENCE_CAUSAL"
        elif layer == "frequency" and gates["B"]["offgrid"]["pass"] and offgrid_causal["pass"]:
            classification = "TEN_MHZ_SYSREF_RATE_CAUSAL"
        elif layer == "frequency" and gates["B"]["grid5_only"]["pass"] and grid5_causal["pass"]:
            classification = "TEN_MHZ_SYSREF_RATE_CAUSAL_GRID_CONTAMINATION"
        elif offgrid_causal["B"]["median_abs_slope_error"] < offgrid_causal["A1"]["median_abs_slope_error"]:
            classification = {
                "sysref": "CONTINUOUS_SYSREF_CONTRIBUTOR",
                "frequency": "SYSREF_RATE_CONTRIBUTOR",
                "reference": "CLOCK_REFERENCE_CONTRIBUTOR",
            }[layer]
        else:
            classification = "CLOCK_SYSREF_NOT_CAUSAL_UNDER_SHARED_50OHM"
        result[layer] = {
            "classification": classification,
            "condition_gates": gates,
            "offgrid_causal": offgrid_causal,
            "grid10_causal": grid10_causal,
            "grid5_only_causal": grid5_causal,
        }
    return result


def decode_low_rf_capture(path: Path, center_mhz: float) -> dict[str, Any]:
    decoded = collect_spectra([path])
    power_db = decoded["power_db"]
    sample_rate_hz = int(decoded["sample_rate_hz"])
    bins = len(power_db[0])
    frequencies = [
        center_mhz + ((index if index < bins // 2 else index - bins) * sample_rate_hz / bins) / 1.0e6
        for index in range(bins)
    ]
    return {
        "frequency_mhz": frequencies,
        "power_dbfs": [
            [fullband.db_code_to_dbfs(value) for value in power_db[lane]]
            for lane in LANES
        ],
        "sample_rate_hz": sample_rate_hz,
    }


def _plot_font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    candidates = (
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc")
        if bold
        else Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Medium.ttc"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
        if bold
        else Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    )
    for candidate in candidates:
        if candidate.is_file():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default()


def _map_plot(
    value: float, source_min: float, source_max: float, target_min: int, target_max: int
) -> int:
    fraction = (float(value) - source_min) / (source_max - source_min)
    return round(target_min + min(max(fraction, 0.0), 1.0) * (target_max - target_min))


def _draw_axes(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    *,
    x_ticks: tuple[float, ...],
    y_ticks: tuple[float, ...],
    x_range: tuple[float, float],
    y_range: tuple[float, float],
    x_label: str,
    y_label: str,
) -> None:
    left, top, right, bottom = box
    draw.rectangle(box, outline="#94a3b8", width=2)
    font = _plot_font(18)
    for value in x_ticks:
        x = _map_plot(value, *x_range, left, right)
        draw.line((x, top, x, bottom), fill="#e2e8f0", width=1)
        label = f"{value:g}"
        draw.text((x - draw.textlength(label, font=font) / 2, bottom + 7), label, fill="#475569", font=font)
    for value in y_ticks:
        y = _map_plot(value, *y_range, bottom, top)
        draw.line((left, y, right, y), fill="#e2e8f0", width=1)
        label = f"{value:g}"
        draw.text((left - draw.textlength(label, font=font) - 8, y - 10), label, fill="#475569", font=font)
    draw.text(((left + right) // 2 - 100, bottom + 35), x_label, fill="#334155", font=_plot_font(20))
    draw.text((25, (top + bottom) // 2 - 10), y_label, fill="#334155", font=_plot_font(20))


def write_plots(root: Path, runs: list[dict[str, Any]]) -> list[str]:
    """Generate fixed, dependency-free campaign plots with Pillow."""

    paths: list[str] = []
    formal = [row for row in runs if row.get("duration_seconds") == FORMAL_SECONDS]
    for layer in ("sysref", "frequency", "reference"):
        selected = [row for row in formal if row.get("layer") == layer]
        if not selected:
            continue
        image = Image.new("RGB", (1800, 1250), "#f8fafc")
        draw = ImageDraw.Draw(image)
        draw.text((70, 30), f"Stage 34c-2 {layer}: reversible A1/B/A2", fill="#0f172a", font=_plot_font(38, True))
        draw.text((70, 82), "ADC0/ADC2 off-grid median; shaded slope band is -0.65..-0.35", fill="#475569", font=_plot_font(21))
        slope_box = (150, 150, 1720, 610)
        lag_box = (150, 735, 1720, 1135)
        _draw_axes(draw, slope_box, x_ticks=(160, 320), y_ticks=(-0.7, -0.5, -0.35, 0), x_range=(140, 340), y_range=(-0.75, 0.05), x_label="Complex sample rate / MS/s", y_label="Slope")
        _draw_axes(draw, lag_box, x_ticks=(160, 320), y_ticks=(0, 0.1, 0.3, 0.5, 0.7), x_range=(140, 340), y_range=(0, 0.7), x_label="Complex sample rate / MS/s", y_label="|lag-1|")
        y1 = _map_plot(-0.65, -0.75, 0.05, slope_box[3], slope_box[1])
        y2 = _map_plot(-0.35, -0.75, 0.05, slope_box[3], slope_box[1])
        draw.rectangle((slope_box[0], min(y1, y2), slope_box[2], max(y1, y2)), fill="#dcfce7")
        draw.line((slope_box[0], _map_plot(-0.5, -0.75, 0.05, slope_box[3], slope_box[1]), slope_box[2], _map_plot(-0.5, -0.75, 0.05, slope_box[3], slope_box[1])), fill="#166534", width=2)
        draw.line((lag_box[0], _map_plot(0.1, 0, 0.7, lag_box[3], lag_box[1]), lag_box[2], _map_plot(0.1, 0, 0.7, lag_box[3], lag_box[1])), fill="#166534", width=2)
        for condition, color in (("A1", "#d62728"), ("B", "#2ca02c"), ("A2", "#ff7f0e")):
            rows = [row for row in selected if row["condition"] == condition]
            x = [rate + (-4 if condition == "A1" else 0 if condition == "B" else 4) for rate in RATES_MSPS]
            slopes = []
            lags = []
            for rate in RATES_MSPS:
                combos = [item for row in rows if row["sample_rate_msps"] == rate for item in row["analysis"]["combinations"] if item["group"] == "offgrid"]
                slopes.append(statistics.median(item["slope"] for item in combos))
                lags.append(statistics.median(abs(item["lag1_correlation"]) for item in combos))
            for box, values, yrange in ((slope_box, slopes, (-0.75, 0.05)), (lag_box, lags, (0, 0.7))):
                points = [(_map_plot(xx, 140, 340, box[0], box[2]), _map_plot(yy, *yrange, box[3], box[1])) for xx, yy in zip(x, values)]
                draw.line(points, fill=color, width=4)
                for point in points:
                    draw.ellipse((point[0] - 7, point[1] - 7, point[0] + 7, point[1] + 7), fill=color)
            legend_x = {"A1": 1350, "B": 1460, "A2": 1570}[condition]
            draw.line((legend_x, 105, legend_x + 35, 105), fill=color, width=5)
            draw.text((legend_x + 43, 93), condition, fill="#334155", font=_plot_font(20, True))
        path = root / f"{layer}_a1_b_a2_summary.png"
        image.save(path, optimize=True)
        paths.append(str(path.resolve()))

    low_runs = [row for row in runs if row.get("center_mhz") == LOW_RF_CENTER_MHZ]
    if low_runs:
        image = Image.new("RGB", (2000, 1500), "#f8fafc")
        draw = ImageDraw.Draw(image)
        draw.text((60, 25), "Stage 34c-2 low-RF clock-spur context", fill="#0f172a", font=_plot_font(38, True))
        draw.text((60, 77), "ADC0 blue, ADC2 red; dashed line marks nominal 122.88 MHz VCXO", fill="#475569", font=_plot_font(21))
        for index, run in enumerate(low_runs):
            row, col = divmod(index, 2)
            left, top = 100 + col * 970, 145 + row * 430
            box = (left, top, left + 870, top + 330)
            _draw_axes(draw, box, x_ticks=(0, 80, 160, 240, 320), y_ticks=(-110, -90, -70, -50, -30), x_range=(0, 320), y_range=(-110, -30), x_label="RF / MHz", y_label="dBFS")
            pcap = Path(run["begin_capture"]["paths"][0])
            decoded = decode_low_rf_capture(pcap, LOW_RF_CENTER_MHZ)
            for lane_index, lane in enumerate(LANES):
                points = []
                for frequency, value in zip(decoded["frequency_mhz"], decoded["power_dbfs"][lane_index]):
                    if 0 <= frequency <= 320:
                        points.append((_map_plot(frequency, 0, 320, box[0], box[2]), _map_plot(value, -110, -30, box[3], box[1])))
                if len(points) > 1:
                    draw.line(points, fill=("#2563eb" if lane == 0 else "#dc2626"), width=1)
            for marker in (10.0, 20.0, LOW_RF_NOMINAL_VCXO_MHZ):
                x = _map_plot(marker, 0, 320, box[0], box[2])
                draw.line((x, box[1], x, box[3]), fill="#0f172a", width=(3 if marker == LOW_RF_NOMINAL_VCXO_MHZ else 1))
            draw.text((left + 5, top + 5), f"{PROFILE_LABEL[run['profile_id']]} {run['sample_rate_msps']} MS/s", fill="#0f172a", font=_plot_font(20, True))
        path = root / "low_rf_10mhz_grid_122p88mhz_spectra.png"
        image.save(path, optimize=True)
        paths.append(str(path.resolve()))
    return paths


def write_summary_csv(path: Path, runs: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=(
                "name", "layer", "condition", "profile_id", "sample_rate_msps",
                "lane", "requested_rf_mhz", "actual_rf_mhz", "signed_bin", "group",
                "slope", "shuffled_slope", "lag1_correlation", "mean_dbfs", "slope_pass",
            ),
        )
        writer.writeheader()
        for run in runs:
            for row in run.get("analysis", {}).get("combinations", []):
                writer.writerow(
                    {
                        "name": run["name"],
                        "layer": run.get("layer", ""),
                        "condition": run.get("condition", ""),
                        "profile_id": run["profile_id"],
                        "sample_rate_msps": run["sample_rate_msps"],
                        **{
                            key: row[key]
                            for key in (
                                "lane", "requested_rf_mhz", "actual_rf_mhz", "signed_bin",
                                "group", "slope", "shuffled_slope", "lag1_correlation",
                                "mean_dbfs", "slope_pass",
                            )
                        },
                    }
                )


def pcap_manifest(root: Path) -> dict[str, Any]:
    pcaps = sorted(root.rglob("*.pcap"))
    path = root / "pcap_manifest.sha256"
    content = "".join(
        f"{sha256_file(item)}  {item.relative_to(root)}\n" for item in pcaps
    )
    path.write_text(content)
    return {
        "path": str(path.resolve()),
        "sha256": sha256_file(path),
        "pcap_count": len(pcaps),
    }


def safe_finalize(
    args: argparse.Namespace,
    template: dict[str, Any],
    original_board: dict[str, Any] | None,
    original_receiver: dict[str, Any] | None,
) -> list[str]:
    errors = c34c.stop_and_mute(args, CENTER_MHZ)
    try:
        restore_clock(args)
    except Exception as exc:
        errors.append(f"CLOCK_RESTORE:{type(exc).__name__}:{exc}")
    try:
        profile = (original_board or {}).get("profile", {})
        fresh_configure(
            args,
            template,
            int(profile.get("sample_rate_msps") or 160),
            float(profile.get("center_mhz") or CENTER_MHZ),
        )
    except Exception as exc:
        errors.append(f"BOARD_PROFILE_RESTORE:{type(exc).__name__}:{exc}")
    if original_receiver is not None and isinstance(original_receiver.get("config"), dict):
        try:
            fullband._http_json(
                args.receiver_base.rstrip("/") + "/api/config",
                method="POST",
                body=original_receiver["config"],
            )
        except Exception as exc:
            errors.append(f"RECEIVER_RESTORE:{type(exc).__name__}:{exc}")
    errors.extend(c34c.stop_and_mute(args, float((original_board or {}).get("profile", {}).get("center_mhz") or CENTER_MHZ)))
    try:
        board = fullband._http_json(
            args.agent_base.rstrip("/") + "/api/v2/status", timeout=30.0
        )
        receiver = fullband._http_json(
            args.receiver_base.rstrip("/") + "/api/state"
        )
        clock = board.get("clock", {})
        transaction = clock.get("transaction", {})
        dac = board.get("dac", {})
        ocb1 = board.get("rfdc", {}).get("ocb1", {})
        if board.get("streaming") or board.get("pipeline", {}).get("stream_accepting"):
            raise RuntimeError("board remains streaming")
        if int(dac.get("enable_mask", -1)) != 0 or any(int(row.get("amplitude_code", -1)) != 0 for row in dac.get("channels", [])):
            raise RuntimeError("DAC final readback is not all-zero")
        if int(board.get("rfdc", {}).get("calibration", {}).get("frozen_adc_mask", -1)) != 0:
            raise RuntimeError("freeze mask is not zero")
        if int(ocb1.get("ocb1_override_adc_mask", -1)) != 0 or ocb1.get("ocb1_override_state") != "DYNAMIC":
            raise RuntimeError(f"OCB1 final state invalid: {ocb1}")
        if clock.get("profile_id") != CONT_PROFILE or clock.get("sysref_policy") != "continuous":
            raise RuntimeError(f"production clock not restored: {clock}")
        if transaction.get("state") != "PRODUCTION":
            raise RuntimeError(f"clock transaction final state invalid: {transaction}")
        if float(receiver.get("stats", {}).get("packets_per_sec", 0.0) or 0.0) > 1.0:
            raise RuntimeError("receiver still sees science packets")
    except Exception as exc:
        errors.append(f"FINAL_READBACK:{type(exc).__name__}:{exc}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent-base", default="http://192.168.100.117:8010")
    parser.add_argument("--receiver-base", default="http://192.168.100.162:8089")
    parser.add_argument("--configure-template", type=Path, default=Path("config/t510/configure_320_time_only.example.json"))
    parser.add_argument("--receiver-output", type=Path, default=Path("build/receiver/latest/evidence/clock_sysref_causality/science_matrix"))
    parser.add_argument("--board-output", type=Path, default=Path("build/board/latest/evidence/clock_sysref_causality/science_matrix"))
    parser.add_argument("--settle-seconds", type=float, default=2.0)
    parser.add_argument("--resume-qualified-campaign", type=Path)
    parser.add_argument("--ssa-confirmed", action="store_true")
    args = parser.parse_args()
    if not args.ssa_confirmed:
        parser.error("--ssa-confirmed is required for the shared SSA 50-ohm reference setup")
    args.bitstream_id = BITSTREAM_ID
    args.expected_core_version = CORE_VERSION
    args.receiver_output = args.receiver_output.resolve()
    args.board_output = args.board_output.resolve()
    if args.resume_qualified_campaign is not None:
        args.resume_qualified_campaign = args.resume_qualified_campaign.resolve()
    campaign_path = args.receiver_output / "campaign.json"
    if campaign_path.exists():
        raise RuntimeError(f"refusing to overwrite existing campaign {campaign_path}")
    args.receiver_output.mkdir(parents=True, exist_ok=True)
    args.board_output.mkdir(parents=True, exist_ok=True)
    template = json.loads(args.configure_template.read_text())
    original_board = None
    original_receiver = None
    state: dict[str, Any] = {
        "classification": "STAGE34C2_IN_PROGRESS",
        "operational_ok": False,
        "core_version": CORE_VERSION,
        "bitstream_id": BITSTREAM_ID,
        "bitstream_sha256": BITSTREAM_SHA256,
        "pfb_profile_id": PFB_PROFILE_ID,
        "physical_setup": "SHARED_50OHM_REFERENCE: SSA RF INPUT -> splitter -> ADC0/ADC2; TG/preamp off; 20 dB attenuation; all DAC disconnected",
        "low_rf_vcxo_marker": {
            "nominal_rf_mhz": LOW_RF_NOMINAL_VCXO_MHZ,
            "capture_rf_mhz": LOW_RF_VCXO_CAPTURE_MHZ,
            "policy": "nearest_common_exact_pfb_bin_for_160_and_320_msps",
        },
        "monitor_frequency_contract": monitor_frequency_contract(),
        "temperature_policy": {"warning_span_c": TEMP_WARNING_C, "hard_stop_span_c": TEMP_HARD_C, "pre_run_stability_seconds": 60},
        "frozen_target_policy": {
            "sha256": frozen_target_policy_sha256(),
            "profiles": {
                profile_id: frozen_profile_target_policy(profile_id)
                for profile_id in PROFILES
            },
        },
        "profile_qualification": {},
        "runs": [],
        "errors": [],
        "started_at_unix_ms": time.time_ns() // 1_000_000,
    }
    write_json(campaign_path, state)
    try:
        original_receiver = fullband._http_json(
            args.receiver_base.rstrip("/") + "/api/state"
        )
        state["candidate_preflight_configure"] = fresh_configure(
            args, template, 320, CENTER_MHZ
        )
        original_board = fullband._http_json(
            args.agent_base.rstrip("/") + "/api/v2/status", timeout=30.0
        )
        if original_board.get("streaming") or original_board.get("pipeline", {}).get("stream_accepting"):
            raise RuntimeError("campaign requires streaming=false")
        if str(original_board.get("core_version", "")).lower() != CORE_VERSION:
            raise RuntimeError(
                f"campaign requires {CORE_VERSION}, got {original_board.get('core_version')}"
            )
        state["original_board"] = original_board
        state["original_receiver_config"] = original_receiver.get("config")
        if args.resume_qualified_campaign is not None:
            resume = validate_resume_checkpoint(args.resume_qualified_campaign)
            state["resumed_qualification_and_screening"] = {
                key: resume[key]
                for key in ("source", "source_sha256", "reused_screening_names")
            }
            state["profile_qualification"] = resume["profile_qualification"]
            targets = resume["targets"]
            tcxo_qualified = resume["tcxo_qualified"]
            write_json(campaign_path, state)
            print(
                "CLOCK_RESUME_QUALIFICATION_AND_SCREENING "
                f"{resume['source_sha256']} screens={len(resume['reused_screening_names'])}",
                flush=True,
            )
        else:
            targets: dict[str, dict[str, int]] = {}
            for profile_id in PROFILES:
                qualification_path = (
                    args.receiver_output / "qualification" / f"{profile_id}.json"
                )
                try:
                    qualification = qualify_profile(
                        args,
                        template,
                        profile_id,
                        checkpoint_path=qualification_path,
                    )
                    state["profile_qualification"][profile_id] = qualification
                    targets[profile_id] = qualification["target"]
                except Exception as exc:
                    if qualification_path.exists():
                        qualification = json.loads(qualification_path.read_text())
                    else:
                        qualification = {"profile_id": profile_id}
                    qualification.update(
                        {
                            "qualified": False,
                            "error": f"{type(exc).__name__}: {exc}",
                        }
                    )
                    write_json(qualification_path, qualification)
                    state["profile_qualification"][profile_id] = qualification
                    if profile_id in REQUIRED_PROFILES:
                        raise
                    targets[profile_id] = targets[EXT_GATED_PROFILE]
                write_json(campaign_path, state)

            for index, spec in enumerate(screening_plan(), start=1):
                if (
                    spec["profile_id"] == TCXO_GATED_PROFILE
                    and not state["profile_qualification"][TCXO_GATED_PROFILE]["qualified"]
                ):
                    continue
                print(f"CLOCK_SCREEN_RUN_START {index}/18 {spec['name']}", flush=True)
                row = execute_run(
                    args,
                    template,
                    name=spec["name"],
                    profile_id=spec["profile_id"],
                    sample_rate_msps=spec["sample_rate_msps"],
                    center_mhz=CENTER_MHZ,
                    frequencies_mhz=RF_FREQUENCIES_MHZ,
                    duration_seconds=SCREEN_SECONDS,
                    target=targets[spec["profile_id"]],
                    formal=False,
                    thermal_stabilize=False,
                )
                state["runs"].append(
                    {**row, **{key: spec[key] for key in ("layer", "condition")}}
                )
                write_json(campaign_path, state)
                print(f"CLOCK_SCREEN_RUN_COMPLETE {spec['name']}", flush=True)

            tcxo_qualified = bool(
                state["profile_qualification"][TCXO_GATED_PROFILE]["qualified"]
            )
        for spec in low_rf_plan(include_tcxo=tcxo_qualified):
            row = execute_run(
                args,
                template,
                **spec,
                center_mhz=LOW_RF_CENTER_MHZ,
                frequencies_mhz=LOW_RF_MARKERS_MHZ,
                duration_seconds=LOW_RF_SECONDS,
                target=targets[spec["profile_id"]],
                formal=False,
                thermal_stabilize=False,
            )
            state["runs"].append(row)
            write_json(campaign_path, state)

        formal_rows: list[dict[str, Any]] = []
        for layer in ("sysref", "frequency", "reference"):
            if layer == "reference" and not tcxo_qualified:
                continue
            plan = formal_triplet_plan(layer)
            for index, spec in enumerate(plan, start=1):
                print(f"CLOCK_FORMAL_RUN_START {layer} {index}/18 {spec['name']}", flush=True)
                row = execute_run(
                    args,
                    template,
                    name=spec["name"],
                    profile_id=spec["profile_id"],
                    sample_rate_msps=spec["sample_rate_msps"],
                    center_mhz=CENTER_MHZ,
                    frequencies_mhz=RF_FREQUENCIES_MHZ,
                    duration_seconds=FORMAL_SECONDS,
                    target=targets[spec["profile_id"]],
                    formal=True,
                    thermal_stabilize=True,
                )
                row.update({key: spec[key] for key in ("layer", "repeat", "triplet", "condition")})
                formal_rows.append(row)
                state["runs"].append(row)
                write_json(campaign_path, state)
                print(f"CLOCK_FORMAL_RUN_COMPLETE {spec['name']}", flush=True)
        state["analysis"] = classify_layers(
            formal_rows,
            tcxo_qualified,
        )
        neutral = {
            "CLOCK_SYSREF_NOT_CAUSAL_UNDER_SHARED_50OHM",
            "INCONCLUSIVE_BASELINE_NOT_REPRODUCED",
            "TCXO_PROFILE_UNQUALIFIED",
        }
        classifications = [
            state["analysis"][layer]["classification"]
            for layer in ("sysref", "frequency", "reference")
        ]
        state["classification"] = next(
            (value for value in classifications if value not in neutral),
            classifications[0],
        )
        write_summary_csv(args.receiver_output / "summary.csv", state["runs"])
        state["plots"] = write_plots(args.receiver_output, state["runs"])
        state["pcap_manifest"] = pcap_manifest(args.receiver_output)
        state["operational_ok"] = True
    except Exception as exc:
        state["errors"].append(f"{type(exc).__name__}: {exc}")
        state["classification"] = "STAGE34C2_OPERATIONAL_FAIL"
    finally:
        state["errors"].extend(
            safe_finalize(args, template, original_board, original_receiver)
        )
        state["finished_at_unix_ms"] = time.time_ns() // 1_000_000
        if state["errors"]:
            state["operational_ok"] = False
            state["classification"] = "STAGE34C2_OPERATIONAL_FAIL"
        write_json(campaign_path, state)
        write_json(
            args.board_output / "campaign_summary.json",
            {
                "classification": state["classification"],
                "operational_ok": state["operational_ok"],
                "campaign_path": str(campaign_path),
                "campaign_sha256": sha256_file(campaign_path),
                "run_count": len(state["runs"]),
                "errors": state["errors"],
            },
        )
    print(
        json.dumps(
            {
                "classification": state["classification"],
                "operational_ok": state["operational_ok"],
                "run_count": len(state["runs"]),
                "errors": state["errors"],
            },
            indent=2,
        ),
        flush=True,
    )
    return 0 if state["operational_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
