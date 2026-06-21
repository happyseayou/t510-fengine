#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


EXPECTED_CORE_VERSION = 0x0001_001A


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


def main() -> int:
    _add_repo_python_path()
    from python.t510_fengine import T510FEngine

    default_bitfile = _repo_root() / "overlay" / "t510_fengine.bit"
    parser = argparse.ArgumentParser(description="Stage 24 QSFP0 CMAC heartbeat bring-up on PYNQ.")
    parser.add_argument("--bitfile", default=str(default_bitfile))
    parser.add_argument("--no-download", action="store_true")
    parser.add_argument("--seconds", type=float, default=2.0)
    parser.add_argument("--dst-ip", default="10.0.1.16")
    parser.add_argument("--dst-mac", default="08:c0:eb:d5:95:b2")
    parser.add_argument("--dst-port", type=int, default=4300)
    parser.add_argument("--src-ip", default="10.0.1.1")
    parser.add_argument("--src-mac", default="02:00:00:00:00:01")
    parser.add_argument("--src-port", type=int, default=4000)
    parser.add_argument("--rate-pps", type=float, default=1000.0)
    parser.add_argument(
        "--diagnostic-ignore-link-gate",
        action="store_true",
        help="Stage 24d diagnostic only: feed heartbeat into CMAC when tx_ready even if link/fault gates are not clean.",
    )
    parser.add_argument("--expected-core-version", type=lambda value: int(value, 0), default=EXPECTED_CORE_VERSION)
    parser.add_argument("--output")
    args = parser.parse_args()

    core = T510FEngine(args.bitfile, download=not args.no_download)
    status = core.read_status()
    errors: list[str] = []
    blockers: list[str] = []
    expected_core_version = int(args.expected_core_version)
    if int(status.get("core_version", 0)) != expected_core_version:
        errors.append(
            f"expected CORE_VERSION 0x{expected_core_version:08x}, "
            f"got 0x{int(status.get('core_version', 0)):08x}"
        )

    bringup = core.run_qsfp_link_bringup(
        configure=True,
        dst_ip=args.dst_ip,
        dst_mac=args.dst_mac,
        dst_port=args.dst_port,
        src_ip=args.src_ip,
        src_mac=args.src_mac,
        src_port=args.src_port,
        rate_pps=args.rate_pps,
        seconds=args.seconds,
        diagnostic_ignore_link_gate=args.diagnostic_ignore_link_gate,
    )
    if not bool(bringup.get("ok", False)):
        blockers.extend(str(item) for item in bringup.get("errors", []))

    after_status = core.read_status()
    result = {
        "expected_core_version": f"0x{expected_core_version:08x}",
        "core_version": f"0x{int(status.get('core_version', 0)):08x}",
        "classification": bringup.get("classification"),
        "pcap_validated": False,
        "science_data_validated": False,
        "stage24_scope": "CMAC 100G link and low-rate UDP heartbeat only",
        "status_before": status,
        "status_after": after_status,
        "bringup": bringup,
        "result": "FAIL" if errors else ("BLOCK" if blockers else "PASS"),
        "errors": errors,
        "blockers": blockers,
        "host_pcap_next_step": {
            "interface": "ens2f0np0",
            "filter": "udp and portrange 4100-4300",
            "expected_dst_mac": args.dst_mac,
            "expected_dst_ip": args.dst_ip,
            "expected_dst_port": args.dst_port,
            "expected_payload_magic": "T510",
        },
    }
    print(json.dumps(_jsonable(result), indent=2, sort_keys=True))
    _write_output(args.output, result)
    return 0 if not errors and not blockers else 1


if __name__ == "__main__":
    raise SystemExit(main())
