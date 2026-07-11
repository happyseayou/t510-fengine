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


def _has_arg(name: str) -> bool:
    return name in sys.argv


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    stage27j_pfb = "--stage27j-pfb" in sys.argv
    if "--stage27i-antialias-acceptance" not in sys.argv:
        sys.argv.insert(1, "--stage27i-antialias-acceptance")
    defaults = {
        "--expected-core-version": "0x0001002C" if stage27j_pfb else "0x0001002B",
        "--target-rf-mhz": "122.88",
        "--target-snr-db": "12",
        "--centers-mhz": "100",
        "--bandwidth-mhz": "100",
        "--dac-nco-sweep-mhz": "60,100",
        "--reference-amplitude": "2048",
        "--physical-state": (
            "dac_adc_loopback_restored_external_10mhz_pps_stage27j_pfb"
            if stage27j_pfb
            else "dac_adc_loopback_restored_external_10mhz_pps_stage27i_antialias"
        ),
        "--sync-mode": "external_pps",
        "--rust-time-window-us": "25",
        "--fengine-clean-seconds": "2",
        "--settle-s": "0.5",
    }
    for key, value in defaults.items():
        if not _has_arg(key):
            sys.argv.extend([key, value])
    if "--no-download-each-case" not in sys.argv and "--download-each-case" not in sys.argv:
        sys.argv.append("--download-each-case")
    if "--output" not in sys.argv:
        date_tag = time.strftime("%Y%m%d")
        sys.argv.extend(
            [
                "--output",
                str(
                    root
                    / "reports"
                    / "board"
                    / (
                        f"stage27j_pfb_spectral_acceptance_{date_tag}.json"
                        if stage27j_pfb
                        else f"stage27i_antialias_spur_acceptance_{date_tag}.json"
                    )
                ),
            ]
        )
    return int(_load_stage27h_audit_main()())


if __name__ == "__main__":
    raise SystemExit(main())
