#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


EXPECTED_CORE_VERSION = 0x0001_0012


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


def _run_tcpdump(interface: str, seconds: float, output: str | None) -> dict[str, Any]:
    cmd = [
        "timeout",
        f"{float(seconds):.3f}",
        "tcpdump",
        "-i",
        interface,
        "-nn",
        "udp",
        "and",
        "portrange",
        "4100-4300",
    ]
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
    parser = argparse.ArgumentParser(description="Stage 23 QSFP/CMAC science bandwidth gate.")
    parser.add_argument("--bitfile", default=str(default_bitfile))
    parser.add_argument("--no-download", action="store_true")
    parser.add_argument("--seconds", type=float, default=2.0)
    parser.add_argument("--pcap-interface", help="Optional local interface for tcpdump when live CMAC is ready.")
    parser.add_argument("--pcap-output")
    parser.add_argument("--output")
    parser.add_argument("--try-live", action="store_true", help="Request CMAC live validation instead of dry-run gate only.")
    args = parser.parse_args()

    core = T510FEngine(args.bitfile, download=not args.no_download)
    status = core.read_status()
    cmac_before = core.read_cmac_status()

    matrix: list[dict[str, Any]] = []
    errors: list[str] = []
    blockers: list[str] = []
    mode_matrix = {
        20: ("time_only", "spec_only", "time_spec"),
        100: ("time_only", "spec_only", "time_spec"),
        200: ("time_only", "spec_only", "time_spec"),
    }
    for bandwidth_mhz, modes in mode_matrix.items():
        for mode in modes:
            row: dict[str, Any] = {"bandwidth_mhz": bandwidth_mhz, "output_mode": mode}
            try:
                estimate = core.estimate_science_payload_rate(bandwidth_mhz, mode)
                row["estimate"] = estimate
                if bandwidth_mhz == 200 and mode == "time_spec":
                    if estimate.get("allowed", True):
                        errors.append("200MHz TIME_SPEC was not rejected by rate estimator")
                    row["classification"] = "TIME_SPEC_200M_REJECTED" if not estimate.get("allowed", True) else "ERROR_NOT_REJECTED"
                    matrix.append(row)
                    continue
                configured = core.configure_science_output(
                    bandwidth_mhz,
                    mode,
                    force_dry_run=True,
                    cmac_enable=False,
                    clear_counters=True,
                )
                row["configured"] = configured
                row["classification"] = "DRY_RUN_MODE_CONFIGURED"
            except Exception as exc:
                row["classification"] = "CONFIG_FAILED"
                row["error"] = f"{type(exc).__name__}: {exc}"
                errors.append(f"{bandwidth_mhz}MHz {mode}: {row['error']}")
            matrix.append(row)

    live_validation = core.run_qsfp_live_validation(bandwidth_mhz=100, output_mode="time_only")
    if not live_validation.get("ok", False):
        blockers.append("QSFP live validation blocked: " + ",".join(live_validation.get("errors", [])))

    time.sleep(float(args.seconds))
    cmac_after = core.read_cmac_status()
    science_after = core.read_science_output_status()
    if "RFDC_SCIENCE_BUS_TRUNCATED_TO_LOW16" in science_after.get("science_block_reasons", []):
        errors.append("RFDC science bus is still reporting low16 truncation")
    pcap = None
    if live_validation.get("ok", False) and args.pcap_interface:
        pcap = _run_tcpdump(args.pcap_interface, float(args.seconds), args.pcap_output)
        if int(pcap["returncode"]) not in (0, 124):
            errors.append(f"tcpdump failed with returncode {pcap['returncode']}")
    elif live_validation.get("ok", False) and not args.pcap_interface:
        errors.append("CMAC appears ready, but --pcap-interface was not provided")

    if int(status.get("core_version", 0)) != EXPECTED_CORE_VERSION:
        errors.append(
            f"expected CORE_VERSION 0x{EXPECTED_CORE_VERSION:08x}, "
            f"got 0x{int(status.get('core_version', 0)):08x}"
        )

    result = {
        "expected_core_version": f"0x{EXPECTED_CORE_VERSION:08x}",
        "core_version": f"0x{int(status.get('core_version', 0)):08x}",
        "status": status,
        "cmac_before": cmac_before,
        "cmac_after": cmac_after,
        "science_after": science_after,
        "mode_matrix": matrix,
        "live_validation": live_validation,
        "pcap": pcap,
        "science_data_validated": bool(live_validation.get("ok", False) and pcap is not None and not errors),
        "result": "FAIL" if errors else ("BLOCK" if blockers else "PASS"),
        "errors": errors,
        "blockers": blockers,
    }
    print(json.dumps(_jsonable(result), indent=2, sort_keys=True))
    _write_output(args.output, result)
    return 0 if not errors and not blockers else 1


if __name__ == "__main__":
    raise SystemExit(main())
