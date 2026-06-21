#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


EXPECTED_CORE_VERSION = 0x0001_0011


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _add_repo_python_path() -> None:
    sys.path.insert(0, str(_repo_root()))


def _jsonable(value: Any) -> Any:
    try:
        import numpy as np
    except ImportError:
        np = None  # type: ignore[assignment]
    if np is not None:
        if isinstance(value, np.ndarray):
            return value.tolist()
        if isinstance(value, np.generic):
            return value.item()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _write_output(path: str | None, result: dict[str, Any]) -> None:
    if not path:
        return
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(_jsonable(result), indent=2, sort_keys=True) + "\n")


def main() -> int:
    _add_repo_python_path()
    from python.t510_fengine import T510FEngine

    default_bitfile = _repo_root() / "overlay" / "t510_fengine.bit"
    parser = argparse.ArgumentParser(description="Stage 20 external 10 MHz/PPS diagnostic.")
    parser.add_argument("--bitfile", default=str(default_bitfile))
    parser.add_argument("--no-download", action="store_true")
    parser.add_argument("--configure-external", action="store_true", help="Program LMK from external 10 MHz and select external_pps mode.")
    parser.add_argument("--include-lmk-registers", action="store_true")
    parser.add_argument("--interval-s", type=float, default=1.2)
    parser.add_argument("--timeout", type=float, default=3.0)
    parser.add_argument("--output")
    args = parser.parse_args()

    core = T510FEngine(args.bitfile, download=not args.no_download)
    errors: list[str] = []
    configure_result: dict[str, Any] | None = None
    if args.configure_external:
        try:
            core.stop()
            configure_result = core.configure_clock(ref="external_10mhz")
            core.set_sync_mode("external_pps")
        except Exception as exc:
            errors.append(f"external clock/sync configure failed: {type(exc).__name__}: {exc}")

    diag = core.read_external_sync_diagnostics(
        interval_s=float(args.interval_s),
        include_lmk_registers=bool(args.include_lmk_registers),
    )
    pps_wait = core.wait_for_pps_increment(timeout=float(args.timeout))
    status = core.read_status()
    if int(status.get("core_version", 0)) != EXPECTED_CORE_VERSION:
        errors.append(f"expected CORE_VERSION 0x{EXPECTED_CORE_VERSION:08x}, got 0x{int(status.get('core_version', 0)):08x}")
    if not bool(diag.get("external_ref_selected", False)):
        errors.append("external 10 MHz is not selected")
    if not bool(diag.get("lmk_locked", False)):
        errors.append("LMK PLLs are not both locked")
    if not bool(diag.get("pps_ok", False)) or not bool(pps_wait.get("ok", False)):
        errors.append("PPS count did not increment")

    result = {
        "expected_core_version": f"0x{EXPECTED_CORE_VERSION:08x}",
        "core_version": f"0x{int(status.get('core_version', 0)):08x}",
        "configure_external": configure_result,
        "diagnostic": diag,
        "pps_wait": pps_wait,
        "classification": diag.get("classification", "UNKNOWN"),
        "result": "PASS" if not errors else "FAIL",
        "errors": errors,
    }
    print(json.dumps(_jsonable(result), indent=2, sort_keys=True))
    _write_output(args.output, result)
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
