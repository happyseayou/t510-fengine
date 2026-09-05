#!/usr/bin/env python3
"""Create a stable file-level manifest for the complete Stage 35 step-3 evidence root."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    output = args.output_json.resolve()
    digest_output = output.with_suffix(output.suffix + ".sha256")
    if output.exists() or digest_output.exists():
        raise RuntimeError(f"refusing to overwrite {output} or {digest_output}")
    files = []
    for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file()):
        resolved = path.resolve()
        if resolved in (output, digest_output):
            continue
        files.append(
            {
                "path": path.relative_to(root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    canonical = "".join(
        f"{row['sha256']} {row['bytes']} {row['path']}\n" for row in files
    ).encode("utf-8")
    result = {
        "format": "T510_STAGE35_STEP3_EVIDENCE_MANIFEST_V1",
        "schema_version": 1,
        "root": str(root),
        "file_count": len(files),
        "total_bytes": sum(int(row["bytes"]) for row in files),
        "canonical_tree_sha256": hashlib.sha256(canonical).hexdigest(),
        "files": files,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    with digest_output.open("x", encoding="ascii") as stream:
        stream.write(f"{sha256_file(output)}  {output.name}\n")
    print(
        f"STAGE35_EVIDENCE_MANIFEST_OK files={len(files)} bytes={result['total_bytes']} "
        f"tree_sha256={result['canonical_tree_sha256']}"
    )


if __name__ == "__main__":
    main()
