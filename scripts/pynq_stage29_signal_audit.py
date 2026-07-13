#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def _jsonable(value: Any) -> Any:
    try:
        import numpy as np
    except ImportError:
        np = None  # type: ignore[assignment]
    if np is not None and isinstance(value, np.ndarray):
        return value.tolist()
    if np is not None and isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def main() -> int:
    sys.path.insert(0, str(_root()))
    from python.stage29 import EXPECTED_CORE_VERSION
    from python.t510_fengine import T510FEngine

    parser = argparse.ArgumentParser(description="Read-only Stage 29 RFDC/PFB/XFFT/AA/phase field audit")
    parser.add_argument("--bitfile", default=str(_root() / "overlay" / "t510_fengine.bit"))
    parser.add_argument("--center-mhz", type=float, default=100.0)
    parser.add_argument("--expected-mhz", type=float, default=60.010)
    parser.add_argument("--bandwidth-mhz", type=int, choices=(100, 200), default=100)
    parser.add_argument("--output")
    args = parser.parse_args()

    core = T510FEngine(args.bitfile, download=False)
    status = core.read_status()
    science = core.read_science_output_status()
    channelizer = core.read_channelizer_status()
    tx = core.read_tx_status()
    preview = core.capture_preview_fast(n=1024, input_mask=0xFF, timeout=1.0)
    analysis = core.compute_observation_view(
        preview,
        observe_center_hz=float(args.center_mhz) * 1_000_000.0,
        view_bw_hz=float(args.bandwidth_mhz) * 1_000_000.0,
        dac_signal_hz=float(args.expected_mhz) * 1_000_000.0,
        expected_signal_hz=float(args.expected_mhz) * 1_000_000.0,
        time_window_us=0.25,
        curve_points=1024,
        oversample=2.5,
        phase_ref_input=0,
        stabilize_phase=False,
        input_source_mode="dac_loopback",
    )
    errors: list[str] = []
    if int(status.get("core_version", 0)) != EXPECTED_CORE_VERSION:
        errors.append("WRONG_CORE_VERSION")
    if int(status.get("stage27i_diag_control", 0)) != 0x0000_FF00:
        errors.append("DIAGNOSTIC_INJECTION_ENABLED")
    for key in (
        "rfdc_dropped_count", "science_dropped_beat_count", "pfb_overflow_count",
        "pfb_xfft_event_count", "pfb_xfft_tlast_missing_count",
        "pfb_xfft_tlast_unexpected_count", "pfb_xfft_fft_overflow_count",
        "pfb_xfft_data_out_halt_count", "pfb_capture_backpressure_count",
        "tx_route_miss_count", "tx_route_error_count",
    ):
        if int(status.get(key, 0)) != 0:
            errors.append(f"NONZERO_{key.upper()}")
    if args.bandwidth_mhz == 100:
        if not int(science.get("science_antialias_100m_active", 0)) or not int(science.get("science_antialias_100m_primed", 0)):
            errors.append("AA100_NOT_READY")
    else:
        if int(science.get("science_antialias_100m_active", 0)):
            errors.append("AA100_ACTIVE_AT_200MHZ")
    result = {
        "classification": "STAGE29_SIGNAL_AUDIT_PASS" if not errors else "STAGE29_SIGNAL_AUDIT_FAIL",
        "ok": not errors,
        "core_version": f"0x{int(status.get('core_version', 0)):08x}",
        "science": science,
        "channelizer": channelizer,
        "tx": tx,
        "preview": {
            "sample0": preview.get("sample0"),
            "count": preview.get("count"),
            "inputs": preview.get("inputs"),
            "peaks": analysis.get("peaks"),
        },
        "errors": errors,
    }
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(_jsonable(result), indent=2, sort_keys=True) + "\n")
    print(json.dumps(_jsonable(result), indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
