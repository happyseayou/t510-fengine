#!/usr/bin/env python3
"""Offline gate for the Stage 32 LMK04828 TICS profile.

The production tuple must remain a mechanical copy of the TICS/register
export.  This script deliberately has no TICS, numpy, or board dependency.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
TCS_PATH = ROOT / "reports" / "arch" / "lmk04828_stage32_min_delta_160_10m_cont_manual_clkin2.tcs"
REGISTER_PATH = (
    ROOT
    / "reports"
    / "arch"
    / "lmk04828_stage32_min_delta_160_10m_cont_manual_clkin2_registers.txt"
)
EXPECTED_TCS_SHA256 = "a9fac413bf18ff7bda1844284f72e59fde3e72dcfceed6144b59dcbda82f216e"
EXPECTED_REGISTER_SHA256 = "9bface367f371a0b3bc2c7f659b2c62aecb976a0fc32bc8658ef3e0a0c6b032a"
EXPECTED_WRITE_COUNT = 136
EXPECTED_CRITICAL_REGISTERS = {
    0x118: 0x0F,  # PL DCLKout6 divider: 2400/15 = 160 MHz
    0x138: 0x00,  # OSCout off so CLKin2 is available
    0x139: 0x03,  # SYSREF continuous path
    0x143: 0x50,  # continuous SYSREF mux state
    0x15A: 0x01,  # manual CLKin selection
    0x16A: 0x20,  # SYSREF divider/feedback configuration
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _parse_tcs_values(path: Path) -> tuple[int, ...]:
    values: list[int] = []
    in_modes = False
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if line.startswith("[") and line.endswith("]"):
            in_modes = line == "[MODES]"
            continue
        if not in_modes:
            continue
        match = re.fullmatch(r"VALUE\d+=(\d+)", line)
        if match:
            values.append(int(match.group(1)))
    return tuple(values)


def _parse_register_values(path: Path) -> tuple[int, ...]:
    values: list[int] = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        match = re.search(r"\b0x([0-9a-fA-F]{6})\b", line)
        if match:
            values.append(int(match.group(1), 16))
    return tuple(values)


def _last_register_values(values: Iterable[int]) -> dict[int, int]:
    registers: dict[int, int] = {}
    for value in values:
        registers[(int(value) >> 8) & 0x1FFF] = int(value) & 0xFF
    return registers


def verify() -> dict[str, object]:
    sys.path.insert(0, str(ROOT))
    from python.t510_clock import (  # pylint: disable=import-outside-toplevel
        LMK04828_INIT_STAGE32_160,
        T510ClockController,
    )

    errors: list[str] = []
    tcs_sha = _sha256(TCS_PATH)
    register_sha = _sha256(REGISTER_PATH)
    tcs_values = _parse_tcs_values(TCS_PATH)
    register_values = _parse_register_values(REGISTER_PATH)
    python_values = tuple(int(value) for value in LMK04828_INIT_STAGE32_160)

    if tcs_sha != EXPECTED_TCS_SHA256:
        errors.append(f"TCS_SHA256 expected {EXPECTED_TCS_SHA256}, got {tcs_sha}")
    if register_sha != EXPECTED_REGISTER_SHA256:
        errors.append(
            f"REGISTER_SHA256 expected {EXPECTED_REGISTER_SHA256}, got {register_sha}"
        )
    for label, values in (
        ("TCS", tcs_values),
        ("register export", register_values),
        ("Python", python_values),
    ):
        if len(values) != EXPECTED_WRITE_COUNT:
            errors.append(
                f"{label} write count expected {EXPECTED_WRITE_COUNT}, got {len(values)}"
            )
    if tcs_values != register_values:
        errors.append("TCS values differ from register export or write order")
    if register_values != python_values:
        errors.append("register export differs from LMK04828_INIT_STAGE32_160 or write order")

    final_registers = _last_register_values(python_values)
    for address, expected in EXPECTED_CRITICAL_REGISTERS.items():
        actual = final_registers.get(address)
        if actual != expected:
            errors.append(
                f"critical register 0x{address:03x} expected 0x{expected:02x}, "
                f"got {actual!r}"
            )

    # A continuous profile must never change the LMK SYNC GPIO when old MTS
    # callers request on/off.  Exercise the policy without board access.
    gpio_writes: list[tuple[int, int]] = []
    controller = T510ClockController()
    controller._gpio = lambda pin, value: gpio_writes.append((pin, value))  # type: ignore[method-assign]
    continuous_on = controller.set_sysref(
        True, mode=T510ClockController.SYSREF_CONTINUOUS
    )
    continuous_off = controller.set_sysref(
        False, mode=T510ClockController.SYSREF_CONTINUOUS
    )
    if gpio_writes:
        errors.append(f"continuous SYSREF unexpectedly changed GPIO: {gpio_writes}")
    if not continuous_on.get("enabled") or not continuous_off.get("enabled"):
        errors.append("continuous SYSREF did not remain enabled for on/off requests")

    request_on = controller.set_sysref(
        True, mode=T510ClockController.SYSREF_REQUEST
    )
    if gpio_writes != [(T510ClockController.LMK_SYNC, 1)]:
        errors.append(f"request SYSREF GPIO regression: {gpio_writes}")
    if not request_on.get("gpio_changed"):
        errors.append("request SYSREF did not report GPIO mutation")

    return {
        "ok": not errors,
        "classification": (
            "STAGE32_LMK_PROFILE_OFFLINE_PASS"
            if not errors
            else "STAGE32_LMK_PROFILE_OFFLINE_FAIL"
        ),
        "tcs": str(TCS_PATH.relative_to(ROOT)),
        "register_export": str(REGISTER_PATH.relative_to(ROOT)),
        "tcs_sha256": tcs_sha,
        "register_sha256": register_sha,
        "write_count": len(python_values),
        "critical_registers": {
            f"0x{address:03x}": f"0x{value:02x}"
            for address, value in EXPECTED_CRITICAL_REGISTERS.items()
        },
        "profile_id": T510ClockController.PROFILE_ID_STAGE32_160,
        "sysref_mode": T510ClockController.SYSREF_CONTINUOUS,
        "continuous_gpio_changed": bool(
            continuous_on.get("gpio_changed") or continuous_off.get("gpio_changed")
        ),
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--compact", action="store_true")
    args = parser.parse_args()
    result = verify()
    print(
        json.dumps(
            result,
            indent=None if args.compact else 2,
            sort_keys=True,
        )
    )
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
