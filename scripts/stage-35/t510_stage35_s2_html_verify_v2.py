#!/usr/bin/env python3
"""Independently decode and verify every payload in a Stage 35 report v2."""

from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import json
import re
from html.parser import HTMLParser
from pathlib import Path


PAYLOAD = re.compile(
    rb'^<script type="application/octet-stream" id="payload-([A-Za-z0-9._-]+)">([A-Za-z0-9+/=]+)</script>\s*$'
)


class ReferenceParser(HTMLParser):
    """Collect only network URLs used by real HTML src/href attributes."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.external: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for key, value in attrs:
            if key.lower() not in {"src", "href"} or value is None:
                continue
            normalized = value.strip().lower()
            if normalized.startswith(("http://", "https://", "//")):
                self.external.append({"tag": tag, "attribute": key, "value": value})


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
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = args.report.resolve()
    manifest_path = (args.manifest or report.with_suffix(report.suffix + ".manifest.json")).resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    errors: list[str] = []
    if manifest.get("format") != "T510_STAGE35_S2_HTML_REPORT_MANIFEST_V2" or not manifest.get("complete"):
        errors.append("invalid or incomplete v2 manifest")
    actual_sha = sha256_file(report)
    if actual_sha != manifest.get("report", {}).get("sha256"):
        errors.append("report SHA-256 mismatch")
    if report.stat().st_size != manifest.get("report", {}).get("bytes"):
        errors.append("report byte count mismatch")
    expected = {item["name"]: item for item in manifest.get("payloads", [])}
    found: dict[str, dict[str, object]] = {}
    marker_names = (
        "plotly.js v4.0.0", "RF frequency (MHz)", "global_bin", "860",
        "1179.921875", "960 MHz", "1020 MHz", "count²/PFB channel",
        "count²/Hz", "count⁴/Hz", "10 log₁₀(P/[1 count²/channel])",
        "直接批评：", "ADU就是数字化后的整数码值", "ADEV ∝ τ^-1/2",
        "全98,304个ADC/bin/scan", "普通代表", "积分最差", "记忆最强",
        "证据：", "天文影响：", "尚不能归因：", "完整匹配", "无截断导出筛选CSV",
    )
    markers = {name: False for name in marker_names}
    reference_parser = ReferenceParser()
    with report.open("rb") as stream:
        for line in stream:
            for marker in markers:
                if marker.encode("utf-8") in line:
                    markers[marker] = True
            match = PAYLOAD.match(line)
            # Payload bodies can be hundreds of MB of base64.  Parse their real
            # start/end tags while deliberately omitting opaque script data.
            parser_line = (
                f'<script type="application/octet-stream" id="payload-{match.group(1).decode("ascii")}"></script>'
                if match else line.decode("utf-8", errors="replace")
            )
            reference_parser.feed(parser_line)
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
            info = {"raw_bytes": len(raw), "sha256_raw": hashlib.sha256(raw).hexdigest()}
            found[name] = info
            wanted = expected.get(name)
            if wanted is None:
                errors.append(f"unexpected payload {name}")
            elif info["raw_bytes"] != wanted.get("raw_bytes") or info["sha256_raw"] != wanted.get("sha256_raw"):
                errors.append(f"payload identity mismatch: {name}")
            if name == "metrics-csv":
                rows = raw.count(b"\n") - 1
                if rows != manifest.get("metrics_csv_rows"):
                    errors.append(f"metrics CSV rows {rows} != {manifest.get('metrics_csv_rows')}")
    missing = sorted(set(expected) - set(found))
    if missing:
        errors.append(f"missing payloads: {missing}")
    missing_markers = sorted(name for name, present in markers.items() if not present)
    if missing_markers:
        errors.append(f"missing report markers: {missing_markers}")
    reference_parser.close()
    if reference_parser.external:
        errors.append(f"external network references: {reference_parser.external[:10]}")
    for item in expected.values():
        if item["name"].startswith("dynamic-"):
            for layer in item.get("layers", []):
                if abs(layer["maximum_encoding_error_db"] - layer["scale_db_per_code"] / 2.0) > 1e-15:
                    errors.append(f"dynamic half-step ledger mismatch: {item['name']}")
        if item["name"].startswith("native15-") and item.get("dtype") != "float32":
            errors.append(f"native display dtype mismatch: {item['name']}")
    result = {
        "format": "T510_STAGE35_S2_HTML_REPORT_VERIFICATION_V2",
        "status": "PASS" if not errors else "FAIL",
        "report": str(report), "report_bytes": report.stat().st_size,
        "report_sha256": actual_sha, "manifest": str(manifest_path),
        "payloads_expected": len(expected), "payloads_verified": len(found),
        "metrics_csv_rows": manifest.get("metrics_csv_rows"),
        "markers": markers, "external_network_references": len(reference_parser.external),
        "errors": errors,
    }
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
