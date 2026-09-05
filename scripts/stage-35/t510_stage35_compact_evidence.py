#!/usr/bin/env python3
"""Retain only Stage 35 step-3 manifests and summaries before local Zarr cleanup."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path


TOP_LEVEL = (
    "step3_replay_summary.json",
    "step3_oracle_validation.json",
    "step3_zarr_interop.json",
    "step3_pfb_white_model.json",
    "step3_recovery_identity_abort_seal.json",
    "step3_recovery_identity_abort_seal.json.sha256",
    "step3_recovery_stop_interruption_seal.json",
    "step3_recovery_stop_interruption_seal.json.sha256",
    "step3_evidence_manifest_v2.json",
    "step3_evidence_manifest_v2.json.sha256",
)
SCANS = (
    "nominal_10ms",
    "nominal_20ms",
    "nominal_50ms",
    "nominal_100ms",
    "fault_injection_100ms",
    "explicit_stop_100ms",
)
SCAN_FILES = (
    "dataset_manifest.json",
    "dataset_manifest.sha256",
    "observation_request.json",
    "capture_start.json",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--authoritative-pcap", required=True)
    parser.add_argument("--pcap-sha256", required=True)
    args = parser.parse_args()
    source = args.source_root.resolve()
    output = args.output_root.resolve()
    output.mkdir(parents=True, exist_ok=False)
    for relative in TOP_LEVEL:
        shutil.copy2(source / relative, output / relative)
    for scan in SCANS:
        destination = output / "datasets" / scan
        destination.mkdir(parents=True)
        for relative in SCAN_FILES:
            path = source / scan / relative
            if path.exists():
                shutil.copy2(path, destination / relative)

    files = []
    for path in sorted(candidate for candidate in output.rglob("*") if candidate.is_file()):
        files.append(
            {
                "path": path.relative_to(output).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    canonical = "".join(
        f"{row['sha256']} {row['bytes']} {row['path']}\n" for row in files
    ).encode("utf-8")
    index = {
        "format": "T510_STAGE35_STEP3_COMPACT_EVIDENCE_V1",
        "schema_version": 1,
        "status": "COMPLETE",
        "authoritative_source_pcap": {
            "path": args.authoritative_pcap,
            "sha256": args.pcap_sha256,
            "retained_locally": False,
        },
        "ephemeral_zarr_retained_locally": False,
        "file_count": len(files),
        "total_bytes": sum(int(row["bytes"]) for row in files),
        "canonical_tree_sha256": hashlib.sha256(canonical).hexdigest(),
        "files": files,
    }
    index_path = output / "compact_evidence_index.json"
    index_path.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    digest_path = output / "compact_evidence_index.json.sha256"
    digest_path.write_text(
        f"{sha256_file(index_path)}  {index_path.name}\n", encoding="ascii"
    )
    print(
        f"STAGE35_COMPACT_EVIDENCE_OK files={len(files)} bytes={index['total_bytes']} "
        f"tree_sha256={index['canonical_tree_sha256']} output={output}"
    )


if __name__ == "__main__":
    main()
