#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


EXPECTED_CORE_VERSION = 0x0001_0030


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _jsonable(value: Any) -> Any:
    try:
        import numpy as np
    except ImportError:
        np = None  # type: ignore[assignment]
    if np is not None and isinstance(value, (np.ndarray, np.generic)):
        return value.tolist() if isinstance(value, np.ndarray) else value.item()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _mode(value: str) -> str:
    key = str(value).strip().lower().replace("-", "_")
    aliases = {"time": "time_only", "time_only": "time_only", "spec": "spec_only", "spec_only": "spec_only", "dual": "time_spec", "time_spec": "time_spec"}
    if key not in aliases:
        raise argparse.ArgumentTypeError("mode must be time_only, spec_only, or time_spec")
    return aliases[key]


def main() -> int:
    sys.path.insert(0, str(_repo_root()))
    from python.t510_fengine import T510FEngine

    parser = argparse.ArgumentParser(description="Stage 28 full-rate board validation")
    parser.add_argument("--bitfile", default=str(_repo_root() / "overlay" / "t510_fengine.bit"))
    parser.add_argument("--no-download", action="store_true")
    parser.add_argument("--bandwidth-mhz", type=int, choices=(100, 200), required=True)
    parser.add_argument("--mode", type=_mode, required=True)
    parser.add_argument("--seconds", type=float, default=10.0)
    parser.add_argument("--measurement-ready-timeout-s", type=float, default=30.0)
    parser.add_argument("--dst-ip", default="10.0.1.16")
    parser.add_argument("--dst-mac", default="08:c0:eb:d5:95:b2")
    parser.add_argument("--src-ip", default="10.0.1.1")
    parser.add_argument("--src-mac", default="02:00:00:00:00:01")
    parser.add_argument("--time-dst-port-base", type=int, default=4300)
    parser.add_argument("--spec-dst-port-base", type=int, default=4308)
    parser.add_argument("--time-src-port-base", type=int, default=4000)
    parser.add_argument("--spec-src-port-base", type=int, default=4008)
    parser.add_argument("--time-endpoint-base", type=int, default=0)
    parser.add_argument("--spec-endpoint-base", type=int, default=8)
    parser.add_argument("--time-flow-count", type=int, default=8)
    parser.add_argument("--spec-route-count", type=int, default=16)
    parser.add_argument("--spec-chan-count", type=int, default=256)
    parser.add_argument("--spec-time-count", type=int, default=1)
    parser.add_argument("--spec-chan0-stride", type=int, default=256)
    parser.add_argument("--time-payload-nsamp", type=int, default=64)
    parser.add_argument("--time-live-interval-beats", type=int, default=0)
    parser.add_argument("--input-mask", type=lambda value: int(value, 0), default=0x00FF)
    parser.add_argument("--pfb-fft-shift", type=lambda value: int(value, 0), default=0x0556)
    parser.add_argument("--pfb-coeff-id", type=lambda value: int(value, 0), default=0x28A4_0001)
    parser.add_argument("--skip-coeff-load", action="store_true")
    parser.add_argument("--min-time-pps", type=float)
    parser.add_argument("--min-spec-pps", type=float)
    parser.add_argument("--min-combined-t510-udp-payload-mbps", type=float, default=63_000.0)
    parser.add_argument("--clock-ref", default="external_10mhz")
    parser.add_argument("--sync-mode", default="external_pps")
    parser.add_argument("--force-clock-reconfigure", action="store_true")
    parser.add_argument("--diagnostic-ignore-link-gate", action="store_true")
    parser.add_argument("--expected-core-version", type=lambda value: int(value, 0), default=EXPECTED_CORE_VERSION)
    parser.add_argument("--output")
    args = parser.parse_args()

    allowed = {(100, "time_spec"), (200, "time_only"), (200, "spec_only")}
    if (int(args.bandwidth_mhz), str(args.mode)) not in allowed:
        parser.error("allowed combinations: 100/time_spec, 200/time_only, 200/spec_only")
    output = Path(args.output) if args.output else _repo_root() / "reports" / "board" / f"stage28_{args.bandwidth_mhz}mhz_{args.mode}_board.json"

    core = T510FEngine(args.bitfile, download=not args.no_download)
    initial_status = core.read_status()
    validation = core.run_stage28_validation(
        configure=True,
        expected_core_version=int(args.expected_core_version),
        bandwidth_mhz=int(args.bandwidth_mhz),
        output_mode=str(args.mode),
        seconds=float(args.seconds),
        min_time_pps=args.min_time_pps,
        min_spec_pps=args.min_spec_pps,
        min_combined_t510_udp_payload_mbps=float(args.min_combined_t510_udp_payload_mbps),
        measurement_ready_timeout_s=float(args.measurement_ready_timeout_s),
        dst_ip=args.dst_ip,
        dst_mac=args.dst_mac,
        src_ip=args.src_ip,
        src_mac=args.src_mac,
        time_dst_port_base=int(args.time_dst_port_base),
        spec_dst_port_base=int(args.spec_dst_port_base),
        time_src_port_base=int(args.time_src_port_base),
        spec_src_port_base=int(args.spec_src_port_base),
        time_endpoint_base=int(args.time_endpoint_base),
        spec_endpoint_base=int(args.spec_endpoint_base),
        time_flow_count=int(args.time_flow_count),
        spec_route_count=int(args.spec_route_count),
        spec_chan_count=int(args.spec_chan_count),
        spec_time_count=int(args.spec_time_count),
        spec_chan0_stride=int(args.spec_chan0_stride),
        time_payload_nsamp=int(args.time_payload_nsamp),
        time_live_interval_beats=int(args.time_live_interval_beats),
        input_mask=int(args.input_mask),
        pfb_fft_shift=int(args.pfb_fft_shift),
        pfb_coeff_id=int(args.pfb_coeff_id),
        load_coefficients=not bool(args.skip_coeff_load),
        diagnostic_ignore_link_gate=bool(args.diagnostic_ignore_link_gate),
        clock_ref=None if str(args.clock_ref).lower() == "none" else str(args.clock_ref),
        force_clock_reconfigure=bool(args.force_clock_reconfigure or not args.no_download),
        sync_mode=None if str(args.sync_mode).lower() == "none" else str(args.sync_mode),
        expected_clock_ref=None if str(args.clock_ref).lower() == "none" else str(args.clock_ref),
        expected_sync_mode=None if str(args.sync_mode).lower() == "none" else str(args.sync_mode),
        start=True,
    )
    result = {
        "classification": validation["classification"],
        "ok": bool(validation.get("ok", False)),
        "expected_core_version": f"0x{int(args.expected_core_version):08x}",
        "core_version": f"0x{int(initial_status.get('core_version', 0)):08x}",
        "fresh_download": not bool(args.no_download),
        "host_receiver_validated": False,
        "production_scope": dict(core.STAGE28_PRODUCTION_SCOPE),
        "initial_status": initial_status,
        "validation": validation,
        "errors": list(validation.get("errors", [])),
        "blockers": list(validation.get("blockers", [])),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(_jsonable(result), indent=2, sort_keys=True) + "\n")
    print(json.dumps(_jsonable(result), indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
