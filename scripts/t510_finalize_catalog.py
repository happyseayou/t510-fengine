#!/usr/bin/env python3
"""Finalize the current T510 release Agent catalog from completed MTS campaign evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


EXPECTED_CORE_VERSION = "0x00010033"
EXPECTED_BITSTREAM_ID = "fengine-0x00010033"
EXPECTED_ACTIONS = {"rfdc_reset": 20, "overlay_reload": 10, "lmk_reload": 10}
EXPECTED_LATENCY_QUANTA = {"adc": 12, "dac": 12}


def _load(path: Path) -> tuple[dict[str, Any], bytes]:
    raw = path.read_bytes()
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain one JSON object")
    return value, raw


def _active_values(config: dict[str, Any], field: str) -> list[int]:
    mask = int(config.get("tiles", 0))
    values = [int(value) for value in config.get(field, [])]
    return [
        values[tile]
        for tile in range(min(4, len(values)))
        if mask & (1 << tile)
    ]


def _validate_campaign(value: dict[str, Any], *, phase: str) -> None:
    if value.get("phase") != phase or value.get("core_version") != EXPECTED_CORE_VERSION:
        raise ValueError(f"{phase} report has the wrong phase or core version")
    if value.get("ok") is not True:
        raise ValueError(f"{phase} report is not a passing campaign")
    required = value.get("required_cycles")
    if required != EXPECTED_ACTIONS:
        raise ValueError(f"{phase} report must use {EXPECTED_ACTIONS}, got {required!r}")
    cycles = value.get("cycles")
    if not isinstance(cycles, list) or len(cycles) != 40:
        raise ValueError(f"{phase} report must contain exactly 40 cycles")
    observed = {name: 0 for name in EXPECTED_ACTIONS}
    for row in cycles:
        if not isinstance(row, dict) or row.get("ok") is not True or row.get("errors"):
            raise ValueError(f"{phase} report contains a failed cycle")
        action = str(row.get("action"))
        if action not in observed:
            raise ValueError(f"{phase} report contains unknown action {action!r}")
        observed[action] += 1
    if observed != EXPECTED_ACTIONS:
        raise ValueError(f"{phase} action counts are {observed}, expected {EXPECTED_ACTIONS}")
    if phase == "fixed":
        if value.get("latency_quanta") != EXPECTED_LATENCY_QUANTA:
            raise ValueError(
                f"fixed report latency quanta must be {EXPECTED_LATENCY_QUANTA}"
            )
        targets = value.get("targets", {})
        for row in cycles:
            mts = row.get("evidence", {}).get("mts", {})
            for kind, quantum in EXPECTED_LATENCY_QUANTA.items():
                config = mts.get(f"{kind}_config", {})
                latency = tuple(_active_values(config, "latency"))
                offset = tuple(_active_values(config, "offset"))
                if len(latency) != 4 or len(offset) != 4:
                    raise ValueError(
                        f"fixed report has incomplete {kind.upper()} latency/offset readback"
                    )
                if len(set(latency)) != 1:
                    raise ValueError(
                        f"fixed report {kind.upper()} tiles are not latency-aligned"
                    )
                target = int(targets.get(kind, -1))
                if int(config.get("target_latency", -1)) != target:
                    raise ValueError(
                        f"fixed report {kind.upper()} target readback mismatch"
                    )
                if any(abs(item - target) > quantum // 2 for item in latency):
                    raise ValueError(
                        f"fixed report {kind.upper()} latency is outside target quantization"
                    )
                if any(item < 0 or item > 31 for item in offset):
                    raise ValueError(
                        f"fixed report {kind.upper()} correction offset is out of range"
                    )
        repeatability = value.get("fixed_repeatability", {})
        if not isinstance(repeatability, dict) or repeatability.get("ok") is not True:
            raise ValueError("fixed report normalized repeatability gate did not pass")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description="Write current T510 release bitstream SHA and proven MTS targets into the Agent catalog"
    )
    parser.add_argument(
        "--bitstream",
        default=str(root / "overlay" / "t510_fengine.bit"),
    )
    parser.add_argument("--discovery-json", required=True)
    parser.add_argument("--fixed-json", required=True)
    parser.add_argument(
        "--catalog",
        default=str(root / "config" / "t510" / "config.example.json"),
    )
    args = parser.parse_args()

    bitstream = Path(args.bitstream).resolve()
    discovery_path = Path(args.discovery_json).resolve()
    fixed_path = Path(args.fixed_json).resolve()
    catalog_path = Path(args.catalog).resolve()
    discovery, discovery_raw = _load(discovery_path)
    fixed, fixed_raw = _load(fixed_path)
    _validate_campaign(discovery, phase="discovery")
    _validate_campaign(fixed, phase="fixed")
    bitstream_sha256 = _sha256(bitstream)
    for phase, report in (("discovery", discovery), ("fixed", fixed)):
        if report.get("bitstream_sha256") != bitstream_sha256:
            raise ValueError(
                f"{phase} campaign bitstream SHA does not match the candidate bitstream"
            )

    observed = discovery.get("observed_latency", {})
    recommended = discovery.get("recommended_fixed_targets", {})
    adc_max = int(observed.get("adc_max", -1))
    dac_max = int(observed.get("dac_max", -1))
    adc_target = int(recommended.get("adc", -1))
    dac_target = int(recommended.get("dac", -1))
    if adc_target != adc_max + 20 or dac_target != dac_max + 16:
        raise ValueError("discovery targets do not equal observed maxima plus ADC +20 / DAC +16")
    if fixed.get("targets") != {"adc": adc_target, "dac": dac_target}:
        raise ValueError("fixed campaign did not use the discovery-derived targets")
    if adc_target == 230 or dac_target == 336:
        raise ValueError("current T510 release must not reuse the retired ADC=230 or DAC=336 target")

    catalog, _catalog_raw = _load(catalog_path)
    entries = catalog.get("bitstreams")
    if not isinstance(entries, list):
        raise ValueError("catalog.bitstreams must be an array")
    matches = [entry for entry in entries if entry.get("id") == EXPECTED_BITSTREAM_ID]
    if len(matches) != 1:
        raise ValueError(f"catalog must contain exactly one {EXPECTED_BITSTREAM_ID} entry")
    entry = matches[0]
    if entry.get("core_version") != EXPECTED_CORE_VERSION:
        raise ValueError("current T510 release catalog entry has the wrong core_version")

    evidence_digest = hashlib.sha256()
    evidence_digest.update(discovery_raw)
    evidence_digest.update(fixed_raw)
    entry["sha256"] = bitstream_sha256
    entry["mts_adc_target_latency"] = adc_target
    entry["mts_dac_target_latency"] = dac_target
    entry["mts_campaign"] = {
        "discovery": {**EXPECTED_ACTIONS, "passed": 40},
        "fixed": {**EXPECTED_ACTIONS, "passed": 40},
        "observed_adc_max": adc_max,
        "observed_dac_max": dac_max,
        "adc_margin": 20,
        "dac_margin": 16,
        "evidence_sha256": evidence_digest.hexdigest(),
    }

    temporary = catalog_path.with_suffix(catalog_path.suffix + ".tmp")
    temporary.write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")
    temporary.replace(catalog_path)
    print(
        json.dumps(
            {
                "catalog": str(catalog_path),
                "bitstream_id": EXPECTED_BITSTREAM_ID,
                "sha256": entry["sha256"],
                "mts_adc_target_latency": adc_target,
                "mts_dac_target_latency": dac_target,
                "evidence_sha256": entry["mts_campaign"]["evidence_sha256"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
