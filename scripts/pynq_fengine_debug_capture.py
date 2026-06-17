#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _add_repo_python_path() -> None:
    repo_python = _repo_root() / "python"
    sys.path.insert(0, str(repo_python.parent))


def _parse_int(value: str) -> int:
    return int(value, 0)


def main() -> int:
    _add_repo_python_path()
    from python.t510_fengine import T510FEngine

    default_bitfile = _repo_root() / "overlay" / "t510_fengine.bit"
    parser = argparse.ArgumentParser(
        description="T510 F-engine RFDC debug capture: ADC0 time waveform and hardware FFT power."
    )
    parser.add_argument("--bitfile", default=str(default_bitfile))
    parser.add_argument("--mask", type=_parse_int, default=0x0001)
    parser.add_argument("--mode", default="snapshot", choices=["time", "spec", "dual", "snapshot"])
    parser.add_argument("--tone-enable", action="store_true", default=True)
    parser.add_argument("--tone-disable", action="store_true")
    parser.add_argument("--tone-amplitude", type=_parse_int, default=2048)
    parser.add_argument("--tone-phase-step", type=_parse_int, default=0x0080_0000)
    parser.add_argument("--timeout", type=float, default=2.0)
    parser.add_argument("--no-download", action="store_true")
    args = parser.parse_args()

    core = T510FEngine(args.bitfile, download=not args.no_download)
    status = core.init_lab_rfdc(
        mask=args.mask,
        mode=args.mode,
        tone_enable=not args.tone_disable,
        tone_amplitude=args.tone_amplitude,
        tone_phase_step=args.tone_phase_step,
        wait_seconds=args.timeout,
    )

    print("status:")
    for key in [
        "core_version",
        "sync_config",
        "status",
        "streaming",
        "rfdc_status_flags",
        "rfdc_current_valid_mask",
        "rfdc_seen_valid_mask",
        "rfdc_sample_count",
        "monitor_sample_count",
        "debug_nfft",
        "debug_sample_rate_hz",
    ]:
        value = status.get(key, 0)
        if "mask" in key or key in {"core_version", "sync_config", "status", "rfdc_status_flags"}:
            print(f"  {key}: 0x{value:08x}")
        else:
            print(f"  {key}: {value}")

    time_samples = core.capture_time(timeout=args.timeout)
    spectrum = core.capture_spectrum(timeout=args.timeout)

    print("time_samples_iq_first16:")
    for idx, (ival, qval) in enumerate(time_samples[:16]):
        print(f"  {idx:04d}: I={int(ival):6d} Q={int(qval):6d}")

    peak_bin = int(spectrum["peak_bin"])
    peak_power = int(spectrum["peak_power"])
    sample_rate = int(spectrum["sample_rate_hz"])
    peak_hz = peak_bin * sample_rate / int(status.get("debug_nfft", 1024))
    print("spectrum:")
    print(f"  peak_bin: {peak_bin}")
    print(f"  peak_power: {peak_power}")
    print(f"  observer_sample_rate_hz: {sample_rate}")
    print(f"  peak_frequency_hz_unshifted: {peak_hz:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
