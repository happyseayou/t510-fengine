#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


EXPECTED_CORE_VERSION = 0x0001_0030


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def main() -> int:
    sys.path.insert(0, str(_root()))
    from python.t510_fengine import T510FEngine

    parser = argparse.ArgumentParser(description="Stage 29 non-reconfiguring QSFP/CMAC production preflight")
    parser.add_argument("--bitfile", default=str(_root() / "overlay" / "t510_fengine.bit"))
    args = parser.parse_args()

    core = T510FEngine(args.bitfile, download=False)
    status = core.read_status()
    tx = core.read_tx_status()
    diagnostics = core.read_qsfp_preflight_diagnostics()
    errors: list[str] = []
    if int(status.get("core_version", 0)) != EXPECTED_CORE_VERSION:
        errors.append("WRONG_CORE_VERSION")
    for key, label in (
        ("gt_locked", "GT_NOT_LOCKED"),
        ("cmac_reset_done", "CMAC_RESET_NOT_DONE"),
        ("cmac_tx_ready", "CMAC_TX_NOT_READY"),
    ):
        if not int(tx.get(key, 0)):
            errors.append(label)
    if int(tx.get("tx_local_fault", 0)):
        errors.append("CMAC_LOCAL_FAULT")
    if int(tx.get("tx_remote_fault", 0)):
        errors.append("CMAC_REMOTE_FAULT")
    if int(tx.get("tx_underflow", 0)):
        errors.append("CMAC_TX_UNDERFLOW")
    if int(tx.get("tx_overflow", 0)):
        errors.append("CMAC_TX_OVERFLOW")
    result = {
        "classification": "STAGE29_QSFP_CMAC_PREFLIGHT_PASS" if not errors else "STAGE29_QSFP_CMAC_PREFLIGHT_FAIL",
        "ok": not errors,
        "core_version": f"0x{int(status.get('core_version', 0)):08x}",
        "tx": tx,
        "diagnostics": diagnostics,
        "errors": errors,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
