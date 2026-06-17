#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _add_repo_python_path() -> None:
    sys.path.insert(0, str(_repo_root()))


def _parse_int(value: str) -> int:
    return int(value, 0)


def _circular_bin_delta(actual: int, expected: float, count: int) -> float:
    forward = abs(float(actual) - expected)
    mirrored = abs(float(actual) - (float(count) - expected))
    return min(forward, mirrored)


def main() -> int:
    _add_repo_python_path()
    from python.t510_fengine import T510FEngine

    default_bitfile = _repo_root() / "overlay" / "t510_fengine.bit"
    parser = argparse.ArgumentParser(description="Stage 5b 8-lane realtime Jupyter instrument smoke test.")
    parser.add_argument("--bitfile", default=str(default_bitfile))
    parser.add_argument("--mask", type=_parse_int, default=0x0001)
    parser.add_argument("--freq-mhz", type=float, default=5.0)
    parser.add_argument("--dac-sample-rate-mhz", type=float, default=245.76)
    parser.add_argument("--strict-physical-max-mhz", type=float, default=8.0)
    parser.add_argument("--amplitude", type=_parse_int, default=2048)
    parser.add_argument("--phase-deg-per-channel", type=float, default=35.0)
    parser.add_argument("--channels", type=int, default=8)
    parser.add_argument("--samples", type=int, default=512)
    parser.add_argument("--timeout", type=float, default=2.0)
    parser.add_argument("--no-download", action="store_true")
    args = parser.parse_args()

    visible_channels = max(1, min(int(args.channels), 8))
    input_mask = (1 << visible_channels) - 1
    freq_hz = float(args.freq_mhz) * 1_000_000.0

    core = T510FEngine(args.bitfile, download=not args.no_download)
    status = core.init_lab_rfdc(mask=args.mask, mode="spec", tone_enable=True, wait_seconds=args.timeout)
    tone = core.configure_dac_tone_bank(
        freq_hz=freq_hz,
        amplitude=int(args.amplitude),
        phase_deg_per_channel=float(args.phase_deg_per_channel),
        enable_mask=input_mask,
        dac_sample_rate_hz=float(args.dac_sample_rate_mhz) * 1_000_000.0,
    )
    preview = core.capture_preview(n=int(args.samples), input_mask=input_mask, timeout=args.timeout)
    spectrum = core.capture_preview_spectrum(input_mask=input_mask, n=int(args.samples), timeout=args.timeout)
    debug_spectrum = core.capture_spectrum(timeout=args.timeout)
    after = core.read_status()

    errors: list[str] = []
    warnings: list[str] = []
    if after["core_version"] < 0x0001_0003:
        errors.append(f"expected CORE_VERSION >= 0x00010003, got 0x{after['core_version']:08x}")
    if not after["streaming"]:
        errors.append("F-engine is not streaming")
    if not after["udp_dry_run"]:
        errors.append("UDP_DRY_RUN status bit is not set")
    if after["qsfp_link_up"]:
        errors.append("QSFP_LINK_UP is unexpectedly set in no-QSFP dry-run")
    if (after["rfdc_current_valid_mask"] & args.mask) != args.mask:
        errors.append(
            f"selected mask 0x{args.mask:04x} not present in current_valid_mask "
            f"0x{after['rfdc_current_valid_mask']:04x}"
        )
    if preview["sample0"] <= 0:
        errors.append("preview sample0 did not advance")
    if preview["input_mask"] != input_mask:
        errors.append(f"expected preview input_mask 0x{input_mask:02x}, got 0x{preview['input_mask']:02x}")
    for channel in range(visible_channels):
        samples = preview["iq"].get(channel)
        if samples is None or len(samples) != int(args.samples):
            errors.append(f"CH{channel} preview length mismatch")

    preview_sample_rate = float(spectrum["sample_rate_hz"])
    preview_count = int(args.samples)
    preview_ch0_peak = spectrum["peaks"].get(0, {})
    preview_ch0_peak_bin = int(preview_ch0_peak.get("peak_bin", -1))
    preview_ch0_peak_mhz = (
        min(preview_ch0_peak_bin, preview_count - preview_ch0_peak_bin)
        * preview_sample_rate
        / preview_count
        / 1_000_000.0
    )

    debug_count = len(debug_spectrum["power"])
    debug_sample_rate = float(debug_spectrum["sample_rate_hz"])
    debug_expected_bin = (freq_hz / debug_sample_rate) * debug_count
    debug_peak_bin = int(debug_spectrum["peak_bin"])
    debug_bin_delta = _circular_bin_delta(debug_peak_bin, debug_expected_bin, debug_count)
    debug_bin_tolerance = max(3.0, math.ceil(debug_count * 0.005))
    debug_peak_mhz = min(debug_peak_bin, debug_count - debug_peak_bin) * debug_sample_rate / debug_count / 1_000_000.0
    if args.freq_mhz <= args.strict_physical_max_mhz:
        if debug_bin_delta > debug_bin_tolerance:
            errors.append(
                f"CH0 debug FFT peak is not near {args.freq_mhz:.3f} MHz: "
                f"peak_bin={debug_peak_bin}, peak_freq={debug_peak_mhz:.3f} MHz, "
                f"expected_bin={debug_expected_bin:.2f}, delta={debug_bin_delta:.2f}"
            )
    else:
        warnings.append(
            f"Exact CH0 physical frequency gate skipped above {args.strict_physical_max_mhz:.3f} MHz; "
            f"debug FFT measured {debug_peak_mhz:.3f} MHz and preview global peak measured {preview_ch0_peak_mhz:.3f} MHz."
        )

    summary = {
        "core_version": f"0x{after['core_version']:08x}",
        "streaming": bool(after["streaming"]),
        "rfdc_current_valid_mask": f"0x{after['rfdc_current_valid_mask']:04x}",
        "udp_dry_run": bool(after["udp_dry_run"]),
        "qsfp_link_up": bool(after["qsfp_link_up"]),
        "tx_fifo_high_water_words": int(after.get("tx_fifo_high_water_words", 0)),
        "tone": {
            "freq_mhz": args.freq_mhz,
            "dac_sample_rate_mhz": args.dac_sample_rate_mhz,
            "phase_step": f"0x{tone['phase_step']:08x}",
            "amplitude": int(tone["amplitude"]),
            "phase_deg_per_channel": float(tone["phase_deg_per_channel"]),
            "enable_mask": f"0x{tone['enable_mask']:02x}",
        },
        "preview": {
            "input_mask": f"0x{preview['input_mask']:02x}",
            "inputs": preview["inputs"],
            "count": int(preview["count"]),
            "sample0": int(preview["sample0"]),
            "sample_rate_hz": int(preview["sample_rate_hz"]),
        },
        "ch0_preview_peak": {
            "peak_bin": preview_ch0_peak_bin,
            "peak_mhz": preview_ch0_peak_mhz,
            "peak_power": float(preview_ch0_peak.get("peak_power", 0.0)),
            "phase_deg": float(preview_ch0_peak.get("phase_deg", 0.0)),
        },
        "ch0_debug_peak": {
            "peak_bin": debug_peak_bin,
            "peak_mhz": debug_peak_mhz,
            "expected_bin": debug_expected_bin,
            "bin_delta": debug_bin_delta,
            "peak_power": int(debug_spectrum["peak_power"]),
            "strict_gate": bool(args.freq_mhz <= args.strict_physical_max_mhz),
        },
        "channel_status": {
            f"CH{idx}": (
                "physical loopback verified by debug FFT"
                if idx == 0 and args.freq_mhz <= args.strict_physical_max_mhz
                else "physical loopback observed; exact high-frequency gate skipped"
                if idx == 0
                else "digital/control only, not analog-verified"
            )
            for idx in range(visible_channels)
        },
        "result": "PASS" if not errors else "FAIL",
        "warnings": warnings,
        "errors": errors,
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
