#!/usr/bin/env python3
"""Clock-only Stage 32 LMK smoke.

Run only after the science pipeline has been stopped.  This script programs
only the Stage 32 LMK profile, does not download an overlay, and never starts
RFDC/UDP data.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_controller():
    module_dir = _root() / "python"
    if str(module_dir) not in sys.path:
        sys.path.insert(0, str(module_dir))
    from t510_clock import T510ClockController

    return T510ClockController


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--profile",
        choices=("stage32_160",),
        default="stage32_160",
    )
    parser.add_argument("--reloads", type=int, default=1)
    parser.add_argument("--max-attempts", type=int, default=24)
    parser.add_argument("--register-delay-ms", type=float, default=5.0)
    parser.add_argument("--settle-seconds", type=float, default=0.2)
    args = parser.parse_args()

    if not 1 <= args.reloads <= 10:
        parser.error("--reloads must be within 1..10")

    controller_type = _load_controller()
    controller = controller_type()
    attempts: list[dict[str, object]] = []
    errors: list[str] = []
    for index in range(args.reloads):
        configured = controller.configure_external_10mhz_stage32_160(
            max_attempts=args.max_attempts,
            register_delay_s=max(args.register_delay_ms, 0.0) / 1000.0,
        )
        time.sleep(max(args.settle_seconds, 0.0))
        status = controller.read_status(include_registers=True)
        registers = status.get("registers", {})
        attempt = {
            "index": index,
            "configured": configured,
            "status": {
                "configured": status.get("configured"),
                "pll1_lock": status.get("pll1_lock"),
                "pll2_lock": status.get("pll2_lock"),
                "profile_id": status.get("profile_id"),
                "sysref_mode": status.get("sysref_mode"),
                "lmk_clkin": status.get("lmk_clkin"),
                "selector_bits_sel1_sel0": status.get(
                    "selector_bits_sel1_sel0"
                ),
                "critical_registers": {
                    address: registers.get(address)
                    for address in (
                        "0x118",
                        "0x138",
                        "0x139",
                        "0x143",
                        "0x15a",
                        "0x16a",
                    )
                },
            },
        }
        attempts.append(attempt)
        if not configured.get("configured"):
            errors.append(f"reload {index}: configure did not lock")
        if not status.get("configured"):
            errors.append(f"reload {index}: readback did not report both PLL locks")
        if status.get("profile_id") != controller_type.PROFILE_ID_STAGE32_160:
            errors.append(
                f"reload {index}: Stage 32 signature mismatch: "
                f"{status.get('profile_id')!r}"
            )
        for address, expected in (
            ("0x118", 0x0F),
            ("0x138", 0x00),
            ("0x139", 0x03),
            ("0x143", 0x50),
        ):
            actual = int(registers.get(address, -1))
            if actual != expected:
                errors.append(
                    f"reload {index}: {address} expected 0x{expected:02x}, "
                    f"got 0x{actual & 0xff:02x}"
                )

    result = {
        "ok": not errors,
        "classification": (
            "STAGE32B_CLOCK_ONLY_REGISTER_LOCK_PASS"
            if not errors
            else "STAGE32B_CLOCK_ONLY_REGISTER_LOCK_FAIL"
        ),
        "profile": args.profile,
        "reloads": args.reloads,
        "attempts": attempts,
        "errors": errors,
        "limits": [
            "No frequency/duty-cycle instrument measurement is performed.",
            "No cold power cycle is performed.",
            "No RFDC, MTS, DAC/ADC, or UDP claim is made.",
        ],
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
