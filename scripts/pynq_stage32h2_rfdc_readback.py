#!/usr/bin/env python3
"""Export read-only RFDC tile/block settings for a Stage 32h2 comparison."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        return repr(value)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bitfile", required=True)
    parser.add_argument("--python-root", required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    sys.path.insert(0, str(Path(args.python_root).resolve()))
    from python.t510_fengine import T510FEngine

    result: dict[str, Any] = {
        "classification": "STAGE32H2_RFDC_READBACK_FAIL",
        "ok": False,
        "label": args.label,
        "errors": [],
    }
    try:
        core = T510FEngine(args.bitfile, download=False)
        status = core.read_status()
        result.update({
            "core_version": f"0x{int(status.get('core_version', 0)):08x}",
            "streaming": bool(status.get("streaming")),
            "science_bandwidth_mhz": int(status.get("science_bandwidth_mhz", 0)),
            "science_sample_rate_hz": int(status.get("science_sample_rate_hz", 0)),
            "rfdc": core.read_rfdc_sync_status(),
            "ok": True,
            "classification": "STAGE32H2_RFDC_READBACK_PASS",
        })
    except Exception as exc:
        result["errors"].append(f"{type(exc).__name__}: {exc}")

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(_jsonable(result), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(_jsonable(result), indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
