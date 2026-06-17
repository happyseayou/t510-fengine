#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _add_repo_python_path() -> None:
    sys.path.insert(0, str(_repo_root()))


def _parse_int(value: str) -> int:
    return int(value, 0)


def _status_subset(status: dict[str, int]) -> dict[str, int]:
    keys = [
        "core_version",
        "status",
        "streaming",
        "rfdc_status_flags",
        "rfdc_current_valid_mask",
        "rfdc_sample_count",
        "spec_packet_count",
        "spec_udp_byte_count",
        "spec_seq_no",
        "spec_frame_id",
        "spec_chan0",
        "tx_link_status_flags",
        "qsfp_link_up",
        "udp_dry_run",
        "tx_fifo_high_water_words",
        "pfb_status",
        "pfb_enabled",
        "pfb_config_valid",
        "pfb_nchan",
        "pfb_taps",
        "pfb_fft_shift",
        "pfb_chan0",
        "pfb_chan_count",
        "pfb_time_count",
        "pfb_frame_count",
        "pfb_overflow_count",
        "pfb_peak_chan",
        "pfb_peak_power",
    ]
    return {key: int(status.get(key, 0)) for key in keys}


def main() -> int:
    _add_repo_python_path()
    from python.packet import (
        FLAG_INTERNAL_EPOCH,
        FLAG_QSFP_LINK_UP,
        FLAG_UDP_DRY_RUN,
        STREAM_SPEC,
    )
    from python.t510_fengine import T510FEngine

    default_bitfile = _repo_root() / "overlay" / "t510_fengine.bit"
    parser = argparse.ArgumentParser(description="Stage 6 PFB/FFT channel-window dry-run check on PYNQ.")
    parser.add_argument("--bitfile", default=str(default_bitfile))
    parser.add_argument("--mask", type=_parse_int, default=0x0001)
    parser.add_argument("--chan0", type=_parse_int, default=0)
    parser.add_argument("--chan-count", type=_parse_int, default=64)
    parser.add_argument("--time-count", type=_parse_int, default=4)
    parser.add_argument("--taps", type=_parse_int, default=4)
    parser.add_argument("--fft-shift", type=_parse_int, default=0)
    parser.add_argument("--freq-mhz", type=float, default=5.0)
    parser.add_argument("--dac-sample-rate-mhz", type=float, default=245.76)
    parser.add_argument("--amplitude", type=_parse_int, default=2048)
    parser.add_argument("--seconds", type=float, default=0.5)
    parser.add_argument("--timeout", type=float, default=2.0)
    parser.add_argument("--no-download", action="store_true")
    args = parser.parse_args()

    freq_hz = float(args.freq_mhz) * 1_000_000.0
    dac_sample_rate_hz = float(args.dac_sample_rate_mhz) * 1_000_000.0

    core = T510FEngine(args.bitfile, download=not args.no_download)
    channelizer_cfg = core.configure_channelizer(
        nchan=4096,
        taps=int(args.taps),
        chan0=int(args.chan0),
        chan_count=int(args.chan_count),
        time_count=int(args.time_count),
        fft_shift=int(args.fft_shift),
        enable=True,
    )
    phase_step = core.dac_phase_step_from_frequency(freq_hz, dac_sample_rate_hz)
    init_status = core.init_lab_rfdc(
        mask=int(args.mask),
        mode="spec",
        tone_enable=True,
        tone_amplitude=int(args.amplitude),
        tone_phase_step=phase_step,
        wait_seconds=float(args.timeout),
    )
    before = core.read_status()
    time.sleep(float(args.seconds))
    capture = core.capture_tx_header(timeout=float(args.timeout))
    after = core.read_status()
    header = capture["header"]
    header_dict = capture["header_dict"]

    errors: list[str] = []
    if after["core_version"] < 0x0001_0004:
        errors.append(f"expected CORE_VERSION >= 0x00010004, got 0x{after['core_version']:08x}")
    if not after["streaming"]:
        errors.append("F-engine is not streaming")
    if (after["rfdc_current_valid_mask"] & int(args.mask)) != int(args.mask):
        errors.append(
            f"selected mask 0x{int(args.mask):04x} not present in current_valid_mask "
            f"0x{after['rfdc_current_valid_mask']:04x}"
        )
    if after["spec_packet_count"] <= before["spec_packet_count"]:
        errors.append("SPEC packet counter did not grow")
    if after["pfb_frame_count"] <= before["pfb_frame_count"]:
        errors.append("PFB frame counter did not grow")
    if not after["pfb_enabled"]:
        errors.append("PFB enabled status bit is not set")
    if not after["pfb_config_valid"]:
        errors.append("PFB config_valid status bit is not set")
    if after["pfb_nchan"] != 4096:
        errors.append(f"expected PFB_NCHAN 4096, got {after['pfb_nchan']}")
    if after["pfb_chan0"] != int(args.chan0):
        errors.append(f"expected PFB_CHAN0 {int(args.chan0)}, got {after['pfb_chan0']}")
    if after["pfb_chan_count"] != int(args.chan_count):
        errors.append(f"expected PFB_CHAN_COUNT {int(args.chan_count)}, got {after['pfb_chan_count']}")
    if after["pfb_time_count"] != int(args.time_count):
        errors.append(f"expected PFB_TIME_COUNT {int(args.time_count)}, got {after['pfb_time_count']}")
    if after["qsfp_link_up"]:
        errors.append("QSFP_LINK_UP is unexpectedly set in no-QSFP dry-run")
    if not after["udp_dry_run"]:
        errors.append("UDP_DRY_RUN status bit is not set")
    if header.version != 2:
        errors.append(f"expected header version 2, got {header.version}")
    if header.stream_type != STREAM_SPEC:
        errors.append(f"expected stream_type SPEC(0), got {header.stream_type}")
    if header.payload_bytes != 8192:
        errors.append(f"expected payload_bytes 8192, got {header.payload_bytes}")
    if header.chan0 != int(args.chan0):
        errors.append(f"expected header chan0 {int(args.chan0)}, got {header.chan0}")
    if header.chan_count != int(args.chan_count):
        errors.append(f"expected header chan_count {int(args.chan_count)}, got {header.chan_count}")
    if header.time_count != int(args.time_count):
        errors.append(f"expected header time_count {int(args.time_count)}, got {header.time_count}")
    if header.ninput != 8:
        errors.append(f"expected header ninput 8, got {header.ninput}")
    if not (header.flags & FLAG_UDP_DRY_RUN):
        errors.append("captured header missing UDP_DRY_RUN flag")
    if not (header.flags & FLAG_INTERNAL_EPOCH):
        errors.append("captured header missing INTERNAL_EPOCH flag")
    if header.flags & FLAG_QSFP_LINK_UP:
        errors.append("captured header unexpectedly has QSFP_LINK_UP flag")

    summary = {
        "channelizer_config": channelizer_cfg,
        "tone": {
            "freq_mhz": float(args.freq_mhz),
            "dac_sample_rate_mhz": float(args.dac_sample_rate_mhz),
            "phase_step": f"0x{phase_step:08x}",
            "amplitude": int(args.amplitude),
        },
        "init": _status_subset(init_status),
        "before": _status_subset(before),
        "after": _status_subset(after),
        "header": header_dict,
        "axis_words_first10": [f"0x{word:016x}" for word in capture["axis_words"][:10]],
        "result": "PASS" if not errors else "FAIL",
        "errors": errors,
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
