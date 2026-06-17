#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _add_repo_python_path() -> None:
    sys.path.insert(0, str(_repo_root()))


def _parse_int(value: str) -> int:
    return int(value, 0)


def main() -> int:
    _add_repo_python_path()
    from python.packet import FLAG_UDP_DRY_RUN, STREAM_SPEC
    from python.t510_fengine import T510FEngine

    default_bitfile = _repo_root() / "overlay" / "t510_fengine.bit"
    parser = argparse.ArgumentParser(description="Smoke test for the Stage 5a Jupyter virtual instrument backend.")
    parser.add_argument("--bitfile", default=str(default_bitfile))
    parser.add_argument("--mask", type=_parse_int, default=0x0001)
    parser.add_argument("--timeout", type=float, default=2.0)
    parser.add_argument("--preview-samples", type=int, default=256)
    parser.add_argument("--no-download", action="store_true")
    args = parser.parse_args()

    core = T510FEngine(args.bitfile, download=not args.no_download)
    status = core.init_lab_rfdc(mask=args.mask, mode="spec", wait_seconds=args.timeout)
    preview = core.capture_preview(n=args.preview_samples, input_mask=0x01, timeout=args.timeout)
    spectrum = core.capture_spectrum(timeout=args.timeout)
    tx_header = core.capture_tx_header(timeout=args.timeout)

    errors: list[str] = []
    if status["core_version"] < 0x0001_0003:
        errors.append(f"expected CORE_VERSION >= 0x00010003, got 0x{status['core_version']:08x}")
    if not status["streaming"]:
        errors.append("F-engine is not streaming after init")
    if 0 not in preview["iq"] or len(preview["iq"][0]) == 0:
        errors.append("ADC0 preview returned no samples")
    if int(spectrum["peak_power"]) <= 0:
        errors.append("debug FFT peak_power is zero")
    header = tx_header["header"]
    if header.stream_type != STREAM_SPEC:
        errors.append(f"captured TX header is not SPEC: stream_type={header.stream_type}")
    if not (header.flags & FLAG_UDP_DRY_RUN):
        errors.append("captured TX header missing UDP_DRY_RUN")

    summary = {
        "core_version": f"0x{status['core_version']:08x}",
        "streaming": bool(status["streaming"]),
        "rfdc_current_valid_mask": f"0x{status['rfdc_current_valid_mask']:04x}",
        "preview_count": int(preview["count"]),
        "preview_sample0": int(preview["sample0"]),
        "debug_peak_bin": int(spectrum["peak_bin"]),
        "debug_peak_power": int(spectrum["peak_power"]),
        "tx_fifo_high_water_words": int(status.get("tx_fifo_high_water_words", 0)),
        "tx_header": tx_header["header_dict"],
        "result": "PASS" if not errors else "FAIL",
        "errors": errors,
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
