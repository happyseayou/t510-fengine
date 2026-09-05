#!/usr/bin/env python3
"""Audit and externally seal an interrupted Stage 35 scan without resuming it."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scan", type=Path, required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    scan = args.scan.resolve()
    output = args.output_json.resolve()
    digest_output = output.with_suffix(output.suffix + ".sha256")
    if output.exists() or digest_output.exists():
        raise RuntimeError(f"refusing to overwrite {output} or {digest_output}")
    if not scan.is_dir():
        raise RuntimeError(f"interrupted scan does not exist: {scan}")
    if (scan / "dataset_manifest.json").exists() or (scan / "dataset_manifest.sha256").exists():
        raise RuntimeError("scan already has a dataset manifest and is not an unsealed interruption")

    journal_path = scan / "chunk_journal.jsonl"
    if not journal_path.is_file():
        raise RuntimeError("interrupted scan has no chunk journal")
    journal: list[dict[str, Any]] = []
    with journal_path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                journal.append(json.loads(line))
            except json.JSONDecodeError as error:
                raise RuntimeError(f"truncated/corrupt journal line {line_number}: {error}") from error
    paths = [row["path"] for row in journal]
    if len(paths) != len(set(paths)):
        raise RuntimeError("chunk journal contains duplicate committed paths")
    verified_bytes = 0
    for row in journal:
        path = scan / row["path"]
        if not path.is_file():
            raise RuntimeError(f"journaled file is missing: {row['path']}")
        if path.stat().st_size != row["bytes"] or sha256_file(path) != row["sha256"]:
            raise RuntimeError(f"journaled file failed size/SHA verification: {row['path']}")
        verified_bytes += int(row["bytes"])

    files = sorted(path for path in scan.rglob("*") if path.is_file())
    inventory = []
    tree_lines = []
    for path in files:
        relative = path.relative_to(scan).as_posix()
        digest = sha256_file(path)
        size = path.stat().st_size
        inventory.append(
            {
                "path": relative,
                "bytes": size,
                "sha256": digest,
                "journaled": relative in set(paths),
                "partial": path.name.endswith(".partial"),
            }
        )
        tree_lines.append(f"{digest} {size} {relative}\n")
    tree_sha256 = hashlib.sha256("".join(tree_lines).encode("utf-8")).hexdigest()
    partials = [row for row in inventory if row["partial"]]
    result = {
        "format": "T510_STAGE35_INTERRUPTION_SEAL_V1",
        "schema_version": 1,
        "status": "SEALED_INCOMPLETE",
        "resume_permitted": False,
        "source_scan": str(scan),
        "reason": args.reason,
        "dataset_manifest_present": False,
        "journal": {
            "path": str(journal_path),
            "entries": len(journal),
            "verified_entries": len(journal),
            "verified_bytes": verified_bytes,
        },
        "filesystem": {
            "files": len(inventory),
            "tree_sha256": tree_sha256,
            "partial_files": partials,
            "inventory": inventory,
        },
        "disposition": (
            "All journaled commits verify. Residual partials, if present, remain evidence only; "
            "this scan is excluded from scientific analysis and must never be promoted or resumed."
        ),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    seal_sha = sha256_file(output)
    with digest_output.open("x", encoding="ascii") as stream:
        stream.write(f"{seal_sha}  {output.name}\n")
    print(
        f"STAGE35_INTERRUPTION_SEALED scan={scan} journal_entries={len(journal)} "
        f"partials={len(partials)} seal={output}"
    )


if __name__ == "__main__":
    main()
