#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


EXPECTED_CORE_VERSION = 0x0001_0011


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _add_repo_python_path() -> None:
    sys.path.insert(0, str(_repo_root()))


def _parse_int(value: str) -> int:
    return int(value, 0)


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


def _run_tcpdump(interface: str, seconds: float, output: str | None) -> dict[str, Any]:
    cmd = ["timeout", f"{float(seconds):.3f}", "tcpdump", "-i", interface, "-nn", "udp", "and", "portrange", "4100-4300"]
    if output:
        cmd.extend(["-w", output])
    proc = subprocess.run(cmd, text=True, capture_output=True, check=False)
    return {
        "command": cmd,
        "returncode": proc.returncode,
        "stdout": proc.stdout[-4000:],
        "stderr": proc.stderr[-4000:],
        "pcap_output": output,
    }


def main() -> int:
    _add_repo_python_path()
    from python.t510_fengine import T510FEngine

    default_bitfile = _repo_root() / "overlay" / "t510_fengine.bit"
    parser = argparse.ArgumentParser(description="Stage 21 QSFP link + pcap readiness check.")
    parser.add_argument("--bitfile", default=str(default_bitfile))
    parser.add_argument("--no-download", action="store_true")
    parser.add_argument("--mask", type=_parse_int, default=0x00FF)
    parser.add_argument("--seconds", type=float, default=2.0)
    parser.add_argument("--pcap-interface", help="Optional local interface for tcpdump if live CMAC/QSFP is present.")
    parser.add_argument("--pcap-output")
    parser.add_argument("--output")
    args = parser.parse_args()

    core = T510FEngine(args.bitfile, download=not args.no_download)
    core.configure_network(
        src_ip="10.0.1.1",
        src_mac="02:00:00:00:00:01",
        dgx_a={"ip": "10.0.1.10", "mac": "02:00:00:00:00:0a", "port": 4100},
        dgx_b={"ip": "10.0.1.11", "mac": "02:00:00:00:00:0b", "port": 4200},
        time_dst={"ip": "10.0.1.16", "mac": "02:00:00:00:00:10", "port": 4300},
    )
    core.configure_tx_endpoints(
        [
            {"id": 0, "ip": "10.0.1.10", "mac": "02:00:00:00:00:0a", "port": 4100},
            {"id": 1, "ip": "10.0.1.11", "mac": "02:00:00:00:00:0b", "port": 4200},
            {"id": 2, "ip": "10.0.1.16", "mac": "02:00:00:00:00:10", "port": 4300},
        ]
    )
    core.configure_spec_routes(
        [
            {"id": 0, "chan0": 0, "chan_count": 2048, "endpoint_id": 0},
            {"id": 1, "chan0": 2048, "chan_count": 2048, "endpoint_id": 1},
        ]
    )
    core.configure_time_routes([{"id": 0, "input_mask": int(args.mask), "endpoint_id": 2}])
    core.configure_tx_control(
        force_dry_run=False,
        cmac_enable=True,
        frame_builder_enable=True,
        drop_on_route_miss=True,
        clear_counters=True,
    )
    before = core.read_qsfp_preflight_diagnostics()
    time.sleep(float(args.seconds))
    after = core.read_qsfp_preflight_diagnostics()

    pcap = None
    errors: list[str] = []
    status = after["status"]
    if int(status.get("core_version", 0)) != EXPECTED_CORE_VERSION:
        errors.append(f"expected CORE_VERSION 0x{EXPECTED_CORE_VERSION:08x}, got 0x{int(status.get('core_version', 0)):08x}")
    if after["classification"] == "CURRENT_BIT_DRY_RUN_NO_CMAC_GT_DATAPATH":
        errors.append("current overlay is still dry-run/no live CMAC-GT datapath; QSFP live pcap cannot be validated")
    elif not bool(after.get("link_pcap_possible", False)):
        errors.append(f"QSFP link/CMAC not ready: {after['classification']}")
    elif args.pcap_interface:
        pcap = _run_tcpdump(args.pcap_interface, float(args.seconds), args.pcap_output)
        if int(pcap["returncode"]) not in (0, 124):
            errors.append(f"tcpdump failed with returncode {pcap['returncode']}")
    elif after.get("link_pcap_possible"):
        errors.append("QSFP link looks ready, but --pcap-interface was not provided for packet capture")

    result = {
        "expected_core_version": f"0x{EXPECTED_CORE_VERSION:08x}",
        "core_version": f"0x{int(status.get('core_version', 0)):08x}",
        "default_receivers": after["default_receivers"],
        "before": before,
        "after": after,
        "pcap": pcap,
        "classification": after["classification"],
        "science_data_validated": False,
        "result": "PASS" if not errors else "FAIL",
        "errors": errors,
    }
    print(json.dumps(_jsonable(result), indent=2, sort_keys=True))
    _write_output(args.output, result)
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
