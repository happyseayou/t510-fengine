#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


EXPECTED_CORE_VERSION = 0x0001_001D


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _add_repo_python_path() -> None:
    sys.path.insert(0, str(_repo_root()))


def _jsonable(value: Any) -> Any:
    try:
        import numpy as np
    except ImportError:
        np = None  # type: ignore[assignment]
    if np is not None:
        if isinstance(value, np.ndarray):
            return value.tolist()
        if isinstance(value, np.generic):
            return value.item()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _write_output(path: str | None, result: dict[str, Any]) -> None:
    if not path:
        return
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(_jsonable(result), indent=2, sort_keys=True) + "\n")


def _parse_bandwidths(value: str) -> list[int]:
    if str(value).strip().lower() in ("all", "matrix"):
        return [20, 100, 200]
    out: list[int] = []
    for item in str(value).replace("mhz", "").split(","):
        item = item.strip()
        if not item:
            continue
        bw = int(round(float(item)))
        if bw not in (20, 100, 200):
            raise argparse.ArgumentTypeError("bandwidth must be 20, 100, 200, or all")
        out.append(bw)
    if not out:
        raise argparse.ArgumentTypeError("at least one bandwidth is required")
    return out


def main() -> int:
    _add_repo_python_path()
    from python.t510_fengine import T510FEngine

    default_bitfile = _repo_root() / "overlay" / "t510_fengine.bit"
    default_output = _repo_root() / "reports" / "board" / "stage26_time_full_rate_live_bringup.json"
    parser = argparse.ArgumentParser(description="Stage 26 full-rate TIME live CMAC bring-up on PYNQ.")
    parser.add_argument("--bitfile", default=str(default_bitfile))
    parser.add_argument("--no-download", action="store_true")
    parser.add_argument("--seconds", type=float, default=2.0)
    parser.add_argument("--dst-ip", default="10.0.1.16")
    parser.add_argument("--dst-mac", default="08:c0:eb:d5:95:b2")
    parser.add_argument("--dst-port", type=int, default=4300)
    parser.add_argument("--src-ip", default="10.0.1.1")
    parser.add_argument("--src-mac", default="02:00:00:00:00:01")
    parser.add_argument("--src-port", type=int, default=4000)
    parser.add_argument("--bandwidth-mhz", type=_parse_bandwidths, default=[20, 100, 200])
    parser.add_argument("--time-payload-nsamp", type=int, default=64)
    parser.add_argument("--min-packet-delta", type=int, default=1)
    parser.add_argument("--ddr-enable", action="store_true")
    parser.add_argument("--ddr-base-addr", type=lambda value: int(value, 0), default=0x0000_0008_0000_0000)
    parser.add_argument("--ddr-slots", type=int, default=64)
    parser.add_argument("--ddr-clear", action="store_true")
    parser.add_argument("--sync-mode", default="free_run")
    parser.add_argument("--no-start", action="store_true")
    parser.add_argument(
        "--diagnostic-ignore-link-gate",
        action="store_true",
        help="Diagnostic only: feed TIME live when tx_ready even if link/fault gates are not clean.",
    )
    parser.add_argument("--expected-core-version", type=lambda value: int(value, 0), default=EXPECTED_CORE_VERSION)
    parser.add_argument("--output", default=str(default_output))
    args = parser.parse_args()

    core = T510FEngine(args.bitfile, download=not args.no_download)
    initial_status = core.read_status()
    expected_core_version = int(args.expected_core_version)
    errors: list[str] = []
    if int(initial_status.get("core_version", 0)) != expected_core_version:
        errors.append(
            f"expected CORE_VERSION 0x{expected_core_version:08x}, "
            f"got 0x{int(initial_status.get('core_version', 0)):08x}"
        )

    validations: list[dict[str, Any]] = []
    for idx, bandwidth in enumerate(args.bandwidth_mhz):
        validation = core.run_stage26_time_live_validation(
            configure=True,
            expected_core_version=expected_core_version,
            seconds=float(args.seconds),
            min_packet_delta=int(args.min_packet_delta),
            bandwidth_mhz=int(bandwidth),
            dst_ip=args.dst_ip,
            dst_mac=args.dst_mac,
            dst_port=int(args.dst_port),
            src_ip=args.src_ip,
            src_mac=args.src_mac,
            src_port=int(args.src_port),
            time_payload_nsamp=int(args.time_payload_nsamp),
            ddr_enable=bool(args.ddr_enable),
            ddr_base_addr=int(args.ddr_base_addr),
            ddr_slots=int(args.ddr_slots),
            ddr_clear=bool(args.ddr_clear or args.ddr_enable),
            diagnostic_ignore_link_gate=bool(args.diagnostic_ignore_link_gate),
            sync_mode=(None if idx > 0 else (None if str(args.sync_mode).lower() == "none" else str(args.sync_mode))),
            start=not bool(args.no_start),
        )
        validations.append(validation)

    ok = not errors and all(bool(item.get("ok", False)) for item in validations)
    result = {
        "expected_core_version": f"0x{expected_core_version:08x}",
        "core_version": f"0x{int(initial_status.get('core_version', 0)):08x}",
        "classification": "STAGE26_TIME_FULL_RATE_PASS" if ok else "STAGE26_TIME_FULL_RATE_FAIL",
        "host_receiver_validated": False,
        "science_data_scope": "20/100/200MHz TIME_ONLY full-rate live only",
        "full_science_validated": False,
        "payload_contract": "docs/time_udp_payload_v2.md",
        "status_initial": initial_status,
        "validations": validations,
        "host_receiver_next_step": {
            "binary": "rust/t510_time_rx",
            "interface": "ens2f0np0",
            "web": "127.0.0.1:8088",
            "filter": "udp dst port 4300",
            "expected_dst_mac": args.dst_mac,
            "expected_src_mac": args.src_mac,
            "expected_dst_ip": args.dst_ip,
            "expected_src_ip": args.src_ip,
            "expected_dst_port": args.dst_port,
            "expected_src_port": args.src_port,
            "expected_stream_type": "TIME",
            "expected_payload_bytes": 8192,
            "html_bandwidth_selector": "20/100/200MHz receive-side decode/display only",
        },
        "result": "PASS" if ok else "FAIL",
        "errors": errors,
    }
    print(json.dumps(_jsonable(result), indent=2, sort_keys=True))
    _write_output(args.output, result)
    return 0 if result["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
