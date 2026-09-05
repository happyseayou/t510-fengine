#!/usr/bin/env python3
"""Validate the single current T510 release identity and qualification catalog."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CURRENT_ID = "fengine-current"
REFERENCES = ("onboard_tcxo", "external_10mhz")


def sha256(path: Path) -> str:
    with path.open("rb") as handle:
        digest = hashlib.sha256()
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
        return digest.hexdigest()


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain one JSON object")
    return value


def validate_current_release(
    metadata_path: Path,
    catalog_path: Path,
    bitstream_path: Path,
    *,
    require_reference: str | None = None,
    require_deployable: bool = True,
) -> dict[str, Any]:
    metadata = load_object(metadata_path)
    catalog = load_object(catalog_path)
    if metadata.get("schema_version") != 1:
        raise ValueError("unsupported current release metadata schema")
    if metadata.get("bitstream_id") != CURRENT_ID:
        raise ValueError("current release metadata must use fengine-current")
    if catalog.get("default_bitstream_id") != CURRENT_ID:
        raise ValueError("catalog default must be fengine-current")
    entries = catalog.get("bitstreams")
    if not isinstance(entries, list) or len(entries) != 1 or entries[0].get("id") != CURRENT_ID:
        raise ValueError("catalog must contain exactly one fengine-current entry")
    entry = entries[0]
    for key, metadata_key in (
        ("core_version", "core_version"),
        ("sha256", "bitstream_sha256"),
        ("scaling_profile", "scaling_profile"),
        ("pfb_output_shift", "pfb_output_shift"),
        ("coefficient_fraction_bits", "coefficient_fraction_bits"),
        ("fft_shift", "fft_shift"),
        ("required_qmc_gain", "required_qmc_gain"),
    ):
        if entry.get(key) != metadata.get(metadata_key):
            raise ValueError(f"catalog {key} does not match current release metadata")
    digest = sha256(bitstream_path)
    if digest != metadata.get("bitstream_sha256"):
        raise ValueError("bitstream SHA256 does not match current release metadata")
    qualifications = entry.get("mts_qualifications")
    if not isinstance(qualifications, dict) or set(qualifications) != set(REFERENCES):
        raise ValueError("catalog must declare both reference qualifications")
    onboard = qualifications["onboard_tcxo"]
    if require_deployable and onboard.get("status") != "qualified":
        raise ValueError("onboard_tcxo must be qualified in every deployable release")
    if require_reference is not None:
        if require_reference not in REFERENCES:
            raise ValueError(f"unknown reference {require_reference}")
        if qualifications[require_reference].get("status") != "qualified":
            raise ValueError(f"reference {require_reference} is not qualified")
    return {
        "status": "PASS",
        "bitstream_id": CURRENT_ID,
        "core_version": metadata["core_version"],
        "bitstream_sha256": digest,
        "qualifications": {
            name: value.get("status") for name, value in qualifications.items()
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--metadata", type=Path, default=ROOT / "config/t510/current_release.json"
    )
    parser.add_argument(
        "--catalog", type=Path, default=ROOT / "config/t510/config.example.json"
    )
    parser.add_argument(
        "--bitstream", type=Path, default=ROOT / "overlay/t510_fengine.bit"
    )
    parser.add_argument("--require-reference", choices=REFERENCES)
    parser.add_argument("--allow-unqualified", action="store_true")
    args = parser.parse_args()
    result = validate_current_release(
        args.metadata,
        args.catalog,
        args.bitstream,
        require_reference=args.require_reference,
        require_deployable=not args.allow_unqualified,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
