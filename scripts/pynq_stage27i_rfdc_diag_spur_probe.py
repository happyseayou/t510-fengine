#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import time
from pathlib import Path


def _load_stage27h_audit_main():
    script = Path(__file__).resolve().with_name("pynq_stage27h_rfdc_spur_audit.py")
    spec = importlib.util.spec_from_file_location("stage27h_rfdc_spur_audit", script)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load {script}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.main


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    if "--stage27i-diag-audit" not in sys.argv:
        sys.argv.insert(1, "--stage27i-diag-audit")
    if "--physical-state" not in sys.argv:
        sys.argv.extend(["--physical-state", "dac_adc_loopback_restored_external_10mhz_pps"])
    if "--sync-mode" not in sys.argv:
        sys.argv.extend(["--sync-mode", "external_pps"])
    if "--output" not in sys.argv:
        date_tag = time.strftime("%Y%m%d")
        sys.argv.extend(
            [
                "--output",
                str(root / "reports" / "board" / f"stage27i_rfdc_axis_diag_spur_probe_external_pps_{date_tag}.json"),
            ]
        )
    return int(_load_stage27h_audit_main()())


if __name__ == "__main__":
    raise SystemExit(main())
