#!/usr/bin/env python3
"""Independently verify a generated Stage 35 single-file HTML report."""

from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import json
import re
from pathlib import Path


PAYLOAD = re.compile(
    rb'^<script type="application/octet-stream" id="payload-([A-Za-z0-9._-]+)">([A-Za-z0-9+/=]+)</script>\s*$'
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = args.report.resolve()
    manifest_path = (args.manifest or report.with_suffix(report.suffix + ".manifest.json")).resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    errors: list[str] = []
    if manifest.get("format") != "T510_STAGE35_S2_HTML_REPORT_MANIFEST_V1" or not manifest.get("complete"):
        errors.append("invalid or incomplete report manifest")
    actual_report_sha = sha256_file(report)
    if actual_report_sha != manifest.get("report", {}).get("sha256"):
        errors.append("report SHA-256 mismatch")
    if report.stat().st_size != manifest.get("report", {}).get("bytes"):
        errors.append("report byte count mismatch")

    expected = {item["name"]: item for item in manifest.get("payloads", [])}
    found: dict[str, dict[str, object]] = {}
    markers = {key: False for key in (
        "ADC0", "ADC7", "metrics-csv", "native15-A-0-u16", "dynamic-A-7-u8",
        "frequency × tau", "frequency × lag", "TIME ADU", "temporal PSD",
    )}
    forbidden = re.compile(rb'(?:src|href)\s*=\s*["\'](?:https?:)?//', re.I)
    with report.open("rb") as stream:
        for line_number, line in enumerate(stream, start=1):
            if forbidden.search(line):
                errors.append(f"external network reference on line {line_number}")
            for key in markers:
                if key.encode("utf-8") in line:
                    markers[key] = True
            match = PAYLOAD.match(line)
            if not match:
                continue
            name = match.group(1).decode("ascii")
            if name in found:
                errors.append(f"duplicate payload {name}")
                continue
            try:
                raw = gzip.decompress(base64.b64decode(match.group(2), validate=True))
            except Exception as exc:
                errors.append(f"payload {name} cannot be decoded: {exc}")
                continue
            info = {
                "raw_bytes": len(raw),
                "sha256_raw": hashlib.sha256(raw).hexdigest(),
            }
            found[name] = info
            wanted = expected.get(name)
            if wanted is None:
                errors.append(f"unexpected payload {name}")
            elif info["raw_bytes"] != wanted.get("raw_bytes") or info["sha256_raw"] != wanted.get("sha256_raw"):
                errors.append(f"payload identity mismatch: {name}")
            if name == "metrics-csv":
                rows = raw.count(b"\n") - 1
                if rows != manifest.get("metric_csv_rows"):
                    errors.append(f"metrics CSV row count {rows} != {manifest.get('metric_csv_rows')}")

    missing = sorted(set(expected) - set(found))
    unexpected_missing_markers = sorted(key for key, present in markers.items() if not present)
    if missing:
        errors.append(f"missing payloads: {missing}")
    if unexpected_missing_markers:
        errors.append(f"missing report markers: {unexpected_missing_markers}")
    result = {
        "format": "T510_STAGE35_S2_HTML_REPORT_VERIFICATION_V1",
        "status": "PASS" if not errors else "FAIL",
        "report": str(report),
        "report_bytes": report.stat().st_size,
        "report_sha256": actual_report_sha,
        "manifest": str(manifest_path),
        "payloads_expected": len(expected),
        "payloads_verified": len(found),
        "markers": markers,
        "external_network_references": 0 if not any("external network" in item for item in errors) else None,
        "errors": errors,
    }
    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
