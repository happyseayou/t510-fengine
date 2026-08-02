#!/usr/bin/env python3
"""Capture the raw RFDC complex stream before the Stage 32 half-band/PFB path.

This diagnostic attaches to an already loaded and streaming overlay.  It does
not configure clocks, RFDC, or the science mode.  The cleanup path always stops
the science stream and disables every PL DAC tone channel.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


EXPECTED_CORE_VERSION = 0x0001_0032


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


def _analyze(iq: Any, sample_rate_hz: float, expected_baseband_hz: float) -> dict[str, Any]:
    import numpy as np

    values = np.asarray(iq, dtype=np.float64)
    samples = values[:, 0] + 1j * values[:, 1]
    count = int(samples.size)
    window = np.hanning(count)
    spectrum = np.fft.fftshift(np.fft.fft(samples * window))
    power = np.abs(spectrum) ** 2
    frequencies = np.fft.fftshift(np.fft.fftfreq(count, d=1.0 / sample_rate_hz))
    peak_index = int(np.argmax(power))
    bin_width_hz = float(sample_rate_hz) / count
    expected_index = int(np.argmin(np.abs(frequencies - expected_baseband_hz)))
    image_index = int(np.argmin(np.abs(frequencies + expected_baseband_hz)))
    floor = np.finfo(np.float64).tiny
    expected_db = 10.0 * np.log10(max(float(power[expected_index]), floor))
    image_db = 10.0 * np.log10(max(float(power[image_index]), floor))
    return {
        "count": count,
        "bin_width_hz": bin_width_hz,
        "peak_index_shifted": peak_index,
        "peak_baseband_hz": float(frequencies[peak_index]),
        "peak_bin_error": float((frequencies[peak_index] - expected_baseband_hz) / bin_width_hz),
        "expected_index_shifted": expected_index,
        "expected_power_db": expected_db,
        "image_index_shifted": image_index,
        "image_power_db": image_db,
        "image_rejection_db": expected_db - image_db,
        "i_min": int(values[:, 0].min()),
        "i_max": int(values[:, 0].max()),
        "q_min": int(values[:, 1].min()),
        "q_max": int(values[:, 1].max()),
        "clipped": bool(np.any(np.abs(values) >= 32767)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bitfile", required=True)
    parser.add_argument(
        "--python-root",
        help="Directory containing the deployed python/ package; defaults beside overlay/.",
    )
    parser.add_argument("--center-mhz", type=float, required=True)
    parser.add_argument("--tone-mhz", type=float, required=True)
    parser.add_argument("--input-mask", type=lambda value: int(value, 0), default=0x03)
    parser.add_argument("--samples", type=int, default=1024)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    repo = (
        Path(args.python_root).resolve()
        if args.python_root
        else Path(args.bitfile).resolve().parent.parent
    )
    sys.path.insert(0, str(repo))
    from python.t510_fengine import T510FEngine

    expected_baseband_hz = (float(args.tone_mhz) - float(args.center_mhz)) * 1.0e6
    result: dict[str, Any] = {
        "classification": "STAGE32H2_RAW_RFDC_PREVIEW_IN_PROGRESS",
        "ok": False,
        "center_mhz": float(args.center_mhz),
        "tone_mhz": float(args.tone_mhz),
        "expected_baseband_hz": expected_baseband_hz,
        "scope": "RFDC ADC complex AXIS before half-band, PFB, and UDP",
        "errors": [],
    }
    core = None
    try:
        core = T510FEngine(args.bitfile, download=False)
        status = core.read_status()
        result["status_before"] = {
            "core_version": f"0x{int(status.get('core_version', 0)):08x}",
            "streaming": bool(status.get("streaming")),
            "rfdc_adc_valid": bool(status.get("rfdc_adc_valid")),
            "debug_sample_rate_hz": int(status.get("debug_sample_rate_hz", 0)),
            "preview_sample_rate_hz": int(status.get("preview_sample_rate_hz", 0)),
            "dac_enable_mask": int(status.get("dac_enable_mask", 0)),
        }
        if int(status.get("core_version", 0)) != EXPECTED_CORE_VERSION:
            raise RuntimeError("unexpected CORE_VERSION")
        if not bool(status.get("streaming")):
            raise RuntimeError("science stream is not running")
        if not bool(status.get("rfdc_adc_valid")):
            raise RuntimeError("RFDC ADC AXIS valid is low")

        preview = core.capture_preview_fast(
            n=int(args.samples), input_mask=int(args.input_mask), timeout=2.0
        )
        sample_rate_hz = float(preview["sample_rate_hz"])
        lanes = {
            int(channel): _analyze(iq, sample_rate_hz, expected_baseband_hz)
            for channel, iq in preview["iq"].items()
        }
        errors = []
        for channel, row in lanes.items():
            if abs(float(row["peak_bin_error"])) > 1.0:
                errors.append(f"ADC{channel}_RAW_BASEBAND_SIGN_OR_BIN_MISMATCH")
        result.update({
            "preview": {
                "sample0": int(preview["sample0"]),
                "sample_rate_hz": int(preview["sample_rate_hz"]),
                "axis_beat_rate_hz": int(preview["axis_beat_rate_hz"]),
                "preview_mode": int(preview["preview_mode"]),
                "count": int(preview["count"]),
                "fast_path": bool(preview.get("fast_path")),
            },
            "lanes": lanes,
            "errors": errors,
            "ok": not errors,
            "classification": (
                "STAGE32H2_RAW_RFDC_PREVIEW_PASS" if not errors
                else "STAGE32H2_RAW_RFDC_PREVIEW_FAIL"
            ),
        })
    except Exception as exc:
        result["errors"].append(f"{type(exc).__name__}: {exc}")
        result["classification"] = "STAGE32H2_RAW_RFDC_PREVIEW_FAIL"
    finally:
        if core is not None:
            try:
                core.stop()
                core.set_dac_enable_mask(0)
                final_status = core.read_status()
                result["cleanup"] = {
                    "streaming": bool(final_status.get("streaming")),
                    "dac_enable_mask": int(final_status.get("dac_enable_mask", 0)),
                }
                if result["cleanup"] != {"streaming": False, "dac_enable_mask": 0}:
                    result["errors"].append("SAFE_CLEANUP_READBACK_FAILED")
                    result["ok"] = False
                    result["classification"] = "STAGE32H2_RAW_RFDC_PREVIEW_FAIL"
            except Exception as exc:
                result["errors"].append(f"SAFE_CLEANUP_FAILED: {type(exc).__name__}: {exc}")
                result["ok"] = False
                result["classification"] = "STAGE32H2_RAW_RFDC_PREVIEW_FAIL"

        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(_jsonable(result), indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(json.dumps(_jsonable(result), indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
