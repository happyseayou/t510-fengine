#!/usr/bin/env python3
"""Finalize one reference qualification in the single current Agent catalog."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from python.t510_mts_target import (  # noqa: E402
    T510_DAC_SYSREF_T1_PERIOD,
    external_10mhz_fixed_target_policy,
    onboard_tcxo_fixed_target_policy,
)
from python.t510_scaling import manifest_metadata  # noqa: E402
from scripts.t510_current_release import CURRENT_ID, load_object, sha256  # noqa: E402


EXPECTED_ACTIONS = {"rfdc_reset": 20, "overlay_reload": 10, "lmk_reload": 10}
EXPECTED_LATENCY_QUANTA = {"adc": 12, "dac": 12}


def _load_with_bytes(path: Path) -> tuple[dict[str, Any], bytes]:
    raw = path.read_bytes()
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain one JSON object")
    return value, raw


def _active_values(config: dict[str, Any], field: str) -> list[int]:
    mask = int(config.get("tiles", 0))
    values = [int(value) for value in config.get(field, [])]
    return [values[tile] for tile in range(min(4, len(values))) if mask & (1 << tile)]


def _validate_campaign(
    value: dict[str, Any], *, phase: str, core_version: str, reference: str
) -> None:
    expected_clock_ref = "tcxo_10mhz" if reference == "onboard_tcxo" else "external_10mhz"
    if value.get("phase") != phase or value.get("core_version") != core_version:
        raise ValueError(f"{phase} report has the wrong phase or core version")
    if value.get("clock_ref") != expected_clock_ref:
        raise ValueError(f"{phase} report has the wrong clock reference")
    if value.get("ok") is not True:
        raise ValueError(f"{phase} report is not passing")
    if float(value.get("lmk_settle_seconds", 0.0)) < 3.0:
        raise ValueError(f"{phase} report did not use the qualified 3 s LMK settle")
    if value.get("required_cycles") != EXPECTED_ACTIONS:
        raise ValueError(f"{phase} report does not use the complete 40-cycle matrix")
    cycles = value.get("cycles")
    if not isinstance(cycles, list) or len(cycles) != 40:
        raise ValueError(f"{phase} report must contain exactly 40 cycles")
    observed = {name: 0 for name in EXPECTED_ACTIONS}
    for row in cycles:
        if not isinstance(row, dict) or row.get("ok") is not True or row.get("errors"):
            raise ValueError(f"{phase} report contains a failed cycle")
        identity = row.get("evidence", {}).get("digital_scaling")
        try:
            if identity.get("core_version") != core_version:
                raise ValueError("wrong scaling core version")
            manifest_metadata(identity)
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"{phase} cycle lacks verified current scaling identity") from exc
        action = str(row.get("action"))
        if action not in observed:
            raise ValueError(f"{phase} report contains unknown action {action!r}")
        observed[action] += 1
    if observed != EXPECTED_ACTIONS:
        raise ValueError(f"{phase} action counts are {observed}, expected {EXPECTED_ACTIONS}")
    if phase != "fixed":
        return
    if value.get("latency_quanta") != EXPECTED_LATENCY_QUANTA:
        raise ValueError("fixed report has the wrong latency quantum")
    targets = value.get("targets", {})
    for row in cycles:
        mts = row.get("evidence", {}).get("mts", {})
        for kind, quantum in EXPECTED_LATENCY_QUANTA.items():
            config = mts.get(f"{kind}_config", {})
            latency = _active_values(config, "latency")
            offset = _active_values(config, "offset")
            if len(latency) != 4 or len(offset) != 4:
                raise ValueError(f"fixed report has incomplete {kind} readback")
            if max(latency) - min(latency) >= quantum:
                raise ValueError(f"fixed report {kind} inter-tile span is too large")
            target = int(targets.get(kind, -2))
            if int(config.get("target_latency", -2)) != target:
                raise ValueError(f"fixed report {kind} target readback mismatch")
            if target >= 0 and any(abs(item - target) > quantum // 2 for item in latency):
                raise ValueError(f"fixed report {kind} lies outside target quantization")
            if any(item < 0 or item > 31 for item in offset):
                raise ValueError(f"fixed report {kind} correction offset is invalid")
    repeatability = value.get("fixed_repeatability", {})
    if not isinstance(repeatability, dict) or repeatability.get("ok") is not True:
        raise ValueError("fixed repeatability gate did not pass")


def _target_policy(reference: str, observed: dict[str, Any]) -> dict[str, Any]:
    adc = [int(value) for value in observed.get("adc", [])]
    dac = [int(value) for value in observed.get("dac", [])]
    if reference == "onboard_tcxo":
        return onboard_tcxo_fixed_target_policy(adc, dac)
    return external_10mhz_fixed_target_policy(adc, dac)


def finalize(
    *, bitstream: Path, metadata_path: Path, discovery_path: Path,
    fixed_path: Path, catalog_path: Path, reference: str,
) -> dict[str, Any]:
    metadata = load_object(metadata_path)
    core_version = str(metadata["core_version"])
    digest = sha256(bitstream)
    if digest != metadata.get("bitstream_sha256"):
        raise ValueError("candidate bitstream does not match current release metadata")
    discovery, discovery_raw = _load_with_bytes(discovery_path)
    fixed, fixed_raw = _load_with_bytes(fixed_path)
    _validate_campaign(discovery, phase="discovery", core_version=core_version, reference=reference)
    _validate_campaign(fixed, phase="fixed", core_version=core_version, reference=reference)
    for phase, report in (("discovery", discovery), ("fixed", fixed)):
        if report.get("bitstream_sha256") != digest:
            raise ValueError(f"{phase} report has the wrong bitstream SHA256")

    observed = discovery.get("observed_latency", {})
    policy = _target_policy(reference, observed)
    targets = {name: int(value) for name, value in policy["targets"].items()}
    if discovery.get("recommended_fixed_targets") != targets:
        raise ValueError("discovery target recommendation does not match policy")
    if fixed.get("targets") != targets:
        raise ValueError("fixed campaign did not use the discovery recommendation")

    catalog = load_object(catalog_path)
    entries = catalog.get("bitstreams")
    if catalog.get("default_bitstream_id") != CURRENT_ID or not isinstance(entries, list):
        raise ValueError("catalog is not current-only")
    matches = [entry for entry in entries if entry.get("id") == CURRENT_ID]
    if len(matches) != 1 or len(entries) != 1:
        raise ValueError("catalog must contain exactly one fengine-current entry")
    entry = matches[0]
    if entry.get("core_version") != core_version:
        raise ValueError("catalog and current release metadata disagree on core version")

    derivation = policy["derivation"]
    evidence_digest = hashlib.sha256(discovery_raw + fixed_raw).hexdigest()
    campaign = {
        "discovery": {**EXPECTED_ACTIONS, "passed": 40},
        "fixed": {**EXPECTED_ACTIONS, "passed": 40},
        "observed_adc_max": int(observed["adc_max"]),
        "observed_dac_max": int(observed["dac_max"]),
        "adc_margin": 20,
        "dac_margin": 16,
        "dac_nominal_target": int(derivation["dac_nominal_target"]),
        "dac_period_branch_ceiling": int(derivation["dac_period_branch_ceiling"]),
        "dac_alignment_mode": derivation["dac_alignment_mode"],
        "dac_deterministic_target_feasible": bool(derivation["dac_deterministic_target_feasible"]),
        "dac_deterministic_infeasible_witness": derivation["dac_deterministic_infeasible_witness"],
        "lmk_settle_seconds": {
            "discovery": float(discovery["lmk_settle_seconds"]),
            "fixed": float(fixed["lmk_settle_seconds"]),
        },
        "latency_quantum": 12,
        "strict_headroom_quanta": 1,
        "dac_sysref_t1_period": T510_DAC_SYSREF_T1_PERIOD,
        "frozen_evidence_bounds": derivation["frozen_evidence_bounds"],
        "frozen_fixed_targets": targets,
        "evidence_sha256": evidence_digest,
    }
    entry["sha256"] = digest
    entry["mts_qualifications"][reference] = {
        "status": "qualified",
        "mts_adc_target_latency": targets["adc"],
        "mts_dac_target_latency": targets["dac"],
        "campaign": campaign,
    }
    temporary = catalog_path.with_suffix(catalog_path.suffix + ".tmp")
    temporary.write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")
    temporary.replace(catalog_path)
    return {
        "status": "PASS", "catalog": str(catalog_path), "bitstream_id": CURRENT_ID,
        "reference": reference, "core_version": core_version,
        "bitstream_sha256": digest, "targets": targets,
        "evidence_sha256": evidence_digest,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", choices=("onboard_tcxo", "external_10mhz"), required=True)
    parser.add_argument("--bitstream", type=Path, default=ROOT / "overlay/t510_fengine.bit")
    parser.add_argument("--metadata", type=Path, default=ROOT / "config/t510/current_release.json")
    parser.add_argument("--discovery-json", type=Path, required=True)
    parser.add_argument("--fixed-json", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, default=ROOT / "config/t510/config.example.json")
    args = parser.parse_args()
    result = finalize(
        bitstream=args.bitstream.resolve(), metadata_path=args.metadata.resolve(),
        discovery_path=args.discovery_json.resolve(), fixed_path=args.fixed_json.resolve(),
        catalog_path=args.catalog.resolve(), reference=args.reference,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
