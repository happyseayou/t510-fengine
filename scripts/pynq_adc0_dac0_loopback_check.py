#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _add_repo_python_path() -> None:
    repo_python = _repo_root() / "python"
    sys.path.insert(0, str(repo_python.parent))


def _parse_mask(value: str) -> int:
    return int(value, 0)


def _print_status(label: str, status: dict[str, int]) -> None:
    keys_hex = [
        "sync_config",
        "status",
        "rfdc_status_flags",
        "rfdc_active_mask",
        "rfdc_current_valid_mask",
        "rfdc_seen_valid_mask",
    ]
    keys_dec = [
        "fsm_state",
        "armed",
        "streaming",
        "waiting_for_epoch",
        "rfdc_sample_count",
        "monitor_sample_count",
        "time_packet_count",
        "spec_packet_count",
        "rfdc_dropped_count",
    ]
    print(f"[{label}]")
    for key in keys_hex:
        print(f"  {key}: 0x{status.get(key, 0):08x}")
    for key in keys_dec:
        print(f"  {key}: {status.get(key, 0)}")


def main() -> int:
    _add_repo_python_path()
    from python.t510_fengine import T510FEngine

    default_bitfile = _repo_root() / "overlay" / "t510_fengine.bit"
    parser = argparse.ArgumentParser(
        description="T510 ADC0/DAC0 RFDC loopback bring-up check for PYNQ."
    )
    parser.add_argument("--bitfile", default=str(default_bitfile))
    parser.add_argument(
        "--mask",
        type=_parse_mask,
        default=0x0001,
        help="RFDC port active mask. Use 0x1 for m00 only, 0x3 for current complex ch0 m00+m01.",
    )
    parser.add_argument("--mode", default="time", choices=["time", "spec", "dual", "snapshot"])
    parser.add_argument("--seconds", type=float, default=1.0)
    parser.add_argument("--no-download", action="store_true")
    args = parser.parse_args()

    core = T510FEngine(args.bitfile, download=not args.no_download)
    core.stop()
    time.sleep(0.05)
    core.configure_clock(ref="tcxo_10mhz")
    core.set_adc_active_mask(args.mask)
    core.set_sync_mode("free_run")
    core.set_mode(args.mode)
    core.configure_rfdc(fs_adc=245_760_000, f_center=1.5e9, bandwidth=245.76e6, decimation=20)

    before = core.read_status()
    _print_status("before_start", before)

    core.start()
    time.sleep(args.seconds)

    after = core.read_status()
    _print_status("after_start", after)

    required_seen = (after["rfdc_current_valid_mask"] & args.mask) == args.mask
    count_grew = after["rfdc_sample_count"] > before["rfdc_sample_count"]
    streaming = bool(after["streaming"])

    if required_seen and count_grew and streaming:
        print("PASS: selected ADC mask is valid, samples are flowing, and free-run streaming started.")
        return 0

    print("FAIL: loopback path is not fully alive yet.")
    if not required_seen:
        print(
            f"  selected mask 0x{args.mask:04x} is not present in current_valid_mask "
            f"0x{after['rfdc_current_valid_mask']:04x}"
        )
    if not count_grew:
        print("  rfdc_sample_count did not grow")
    if not streaming:
        print("  F-engine did not enter streaming")
    print("  If ADC0 is one real RFDC port, try --mask 0x1. If it is complex ch0, try --mask 0x3.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
