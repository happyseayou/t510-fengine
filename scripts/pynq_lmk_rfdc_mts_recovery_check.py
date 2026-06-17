#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


EXPECTED_CORE_VERSION = 0x0001_000E


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _add_repo_python_path() -> None:
    root = _repo_root()
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(root / "scripts"))


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
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _parse_int(value: str) -> int:
    return int(str(value), 0)


def _parse_int_list(value: str) -> list[int]:
    return [_parse_int(item.strip()) for item in str(value).split(",") if item.strip()]


def _default_output() -> Path:
    return _repo_root() / "artifacts" / f"stage18_lmk_rfdc_mts_recovery_check_{_timestamp()}.json"


def _copy_path(src: Path, dst_root: Path) -> dict[str, Any]:
    entry = {"src": str(src), "exists": src.exists(), "dst": None, "error": None}
    if not src.exists():
        return entry
    dst = dst_root / src.as_posix().lstrip("/")
    entry["dst"] = str(dst)
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst, symlinks=True)
        else:
            shutil.copy2(src, dst)
    except Exception as exc:
        entry["error"] = str(exc)
    return entry


def _write_rollback_script(backup_dir: Path, entries: list[dict[str, Any]]) -> Path:
    script = backup_dir / "restore_stage18_backup.sh"
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "echo 'Restoring Stage 18 xrfdc/libxrfdc backup...'",
    ]
    for entry in entries:
        if not entry.get("dst") or entry.get("error"):
            continue
        src = str(entry["dst"])
        dst = str(entry["src"])
        if Path(src).is_dir():
            lines.append(f"rm -rf {dst!r}")
            lines.append(f"mkdir -p {str(Path(dst).parent)!r}")
            lines.append(f"cp -a {src!r} {dst!r}")
        else:
            lines.append(f"mkdir -p {str(Path(dst).parent)!r}")
            lines.append(f"cp -a {src!r} {dst!r}")
    lines.append("echo 'Restore complete. Reboot the board before rerunning RFDC checks.'")
    script.write_text("\n".join(lines) + "\n")
    script.chmod(0o755)
    return script


def _backup_system(driver: dict[str, Any], backup_root: Path) -> dict[str, Any]:
    backup_dir = backup_root / f"stage18_{_timestamp()}"
    backup_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    xrfdc_file = driver.get("xrfdc_file")
    if xrfdc_file:
        xrfdc_path = Path(str(xrfdc_file)).resolve()
        paths.append(xrfdc_path.parent)
    for item in driver.get("lib_candidates", []):
        paths.append(Path(str(item)).resolve())
    unique: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path)
        if key not in seen:
            seen.add(key)
            unique.append(path)
    entries = [_copy_path(path, backup_dir) for path in unique]
    rollback = _write_rollback_script(backup_dir, entries)
    return {
        "backup_dir": str(backup_dir),
        "entries": entries,
        "rollback_script": str(rollback),
    }


def _classify(lmk: dict[str, Any], driver: dict[str, Any], mts_probe: dict[str, Any] | None) -> tuple[str, str]:
    if not bool(lmk.get("configured", False)):
        if int(lmk.get("pll1_lock", 0)) == 0:
            return "LMK_PLL1_UNLOCKED", "BLOCK_QSFP_LIVE_DATA_QUALITY"
        if int(lmk.get("pll2_lock", 0)) == 0:
            return "LMK_PLL2_UNLOCKED", "BLOCK_QSFP_LIVE_DATA_QUALITY"
        return "LMK_FULL_LOCK_INCOMPLETE", "BLOCK_QSFP_LIVE_DATA_QUALITY"
    if mts_probe is not None:
        if mts_probe.get("ok"):
            return "RFDC_MTS_LOCK_PASS", "BLOCK_QSFP_LIVE_DATA_QUALITY"
        return str(mts_probe.get("classification", "RFDC_MTS_LOCK_FAILED")), "BLOCK_QSFP_LIVE_DATA_QUALITY"
    if driver.get("classification") == "RFDC_MTS_API_READY":
        return "RFDC_MTS_API_READY", "BLOCK_QSFP_LIVE_DATA_QUALITY"
    if driver.get("classification") == "RFDC_MTS_SHIM_READY":
        return "RFDC_MTS_SHIM_READY", "BLOCK_QSFP_LIVE_DATA_QUALITY"
    if driver.get("classification") == "RFDC_MTS_C_SYMBOLS_PRESENT_SHIM_FAILED":
        return "RFDC_MTS_C_SYMBOLS_PRESENT_SHIM_FAILED", "BLOCK_QSFP_LIVE_DATA_QUALITY"
    return "RFDC_MTS_API_UNAVAILABLE", "BLOCK_QSFP_LIVE_DATA_QUALITY"


def main() -> int:
    _add_repo_python_path()
    from python.t510_clock import T510ClockController
    from python.t510_fengine import T510FEngine

    default_bitfile = _repo_root() / "overlay" / "t510_fengine.bit"
    parser = argparse.ArgumentParser(description="Stage 18 LMK/RFDC MTS recovery audit and preflight check.")
    parser.add_argument("--bitfile", default=str(default_bitfile))
    parser.add_argument("--dump-lmk", action="store_true")
    parser.add_argument("--dump-rfdc-api", action="store_true")
    parser.add_argument("--configure-lmk", action="store_true", help="rewrite the known TCXO/245.76 MHz LMK profile before reading status")
    parser.add_argument("--backup-system", action="store_true", help="backup current xrfdc package and libxrfdc.so with a rollback script")
    parser.add_argument("--backup-root", default="/home/xilinx/t510_stage18_backups")
    parser.add_argument("--probe-mts", action="store_true", help="actually run the RFDC MTS shim/API sequence; requires LMK full lock")
    parser.add_argument("--probe-mts-matrix", action="store_true", help="probe selected RFDC MTS tile masks/ref tiles after the main probe")
    parser.add_argument("--adc-tiles", type=_parse_int, default=None, help="ADC MTS tile mask for --probe-mts, e.g. 0x1 or 0xf")
    parser.add_argument("--dac-tiles", type=_parse_int, default=None, help="DAC MTS tile mask for --probe-mts, e.g. 0x1 or 0xf")
    parser.add_argument("--adc-ref-tile", type=int, default=0)
    parser.add_argument("--dac-ref-tile", type=int, default=0)
    parser.add_argument("--probe-tile-masks", default="0x1,0x3,0xf", help="comma-separated masks for --probe-mts-matrix")
    parser.add_argument("--probe-ref-tiles", default="0,1,2,3", help="comma-separated ref tiles for --probe-mts-matrix")
    parser.add_argument("--probe-max-cases", type=int, default=16)
    parser.add_argument("--timeout", type=float, default=2.0)
    parser.add_argument("--output", default=None)
    parser.add_argument("--no-download", action="store_true")
    args = parser.parse_args()

    start = time.monotonic()
    result: dict[str, Any] = {
        "result": "PASS",
        "stage": 18,
        "expected_core_version": EXPECTED_CORE_VERSION,
        "classification": "UNKNOWN",
        "data_quality_gate": "BLOCK_QSFP_LIVE_DATA_QUALITY",
        "timestamp_utc": _timestamp(),
        "elapsed_s": 0.0,
        "lmk": {},
        "rfdc_driver": {},
        "rfdc_sync": {},
        "system_backup": None,
        "mts_probe": None,
        "mts_probe_matrix": None,
        "preview_payload_stability": {"status": "not_run", "reason": "run pynq_rfdc_sysref_coherence_lock_check.py after LMK/MTS PASS"},
        "errors": [],
    }

    clock = T510ClockController()
    if args.configure_lmk:
        try:
            result["lmk_configure"] = clock.configure_tcxo_245p76()
        except Exception as exc:
            result["errors"].append(f"configure_lmk: {exc}")
    try:
        result["lmk"] = clock.read_status(include_registers=bool(args.dump_lmk))
    except Exception as exc:
        result["lmk"] = {"configured": False, "errors": [str(exc)]}
        result["errors"].append(f"read_lmk: {exc}")

    core = None
    try:
        core = T510FEngine(args.bitfile, download=not args.no_download)
        status = core.read_status()
        result["core_status"] = {
            "core_version": int(status.get("core_version", 0)),
            "udp_dry_run": int(status.get("udp_dry_run", 0)),
            "qsfp_link_up": int(status.get("qsfp_link_up", 0)),
            "rfdc_current_valid_mask": int(status.get("rfdc_current_valid_mask", 0)),
        }
        if int(status.get("core_version", 0)) != EXPECTED_CORE_VERSION:
            result["errors"].append(
                f"expected CORE_VERSION=0x{EXPECTED_CORE_VERSION:08x}, got 0x{int(status.get('core_version', 0)):08x}"
            )
    except Exception as exc:
        result["errors"].append(f"load_overlay_or_read_core: {exc}")

    if core is not None:
        try:
            result["rfdc_driver"] = core.read_rfdc_driver_status(probe_symbols=bool(args.dump_rfdc_api))
        except Exception as exc:
            result["rfdc_driver"] = {"classification": "RFDC_DRIVER_STATUS_FAILED", "errors": [str(exc)]}
            result["errors"].append(f"read_rfdc_driver_status: {exc}")
        try:
            result["rfdc_sync"] = core.read_rfdc_sync_status()
        except Exception as exc:
            result["rfdc_sync"] = {"error": str(exc)}
            result["errors"].append(f"read_rfdc_sync_status: {exc}")

    if args.backup_system:
        try:
            result["system_backup"] = _backup_system(result.get("rfdc_driver", {}), Path(args.backup_root))
        except Exception as exc:
            result["errors"].append(f"backup_system: {exc}")

    if args.probe_mts:
        if core is None:
            result["mts_probe"] = {"ok": False, "classification": "RFDC_HANDLE_UNAVAILABLE", "error": "overlay/RFDC handle not loaded"}
        elif not bool(result.get("lmk", {}).get("configured", False)):
            result["mts_probe"] = {
                "ok": False,
                "classification": "LMK_FULL_LOCK_INCOMPLETE",
                "error": "MTS probe skipped because LMK full lock is incomplete",
            }
        else:
            try:
                mts = core._run_rfdc_mts_sequence(
                    required=True,
                    adc_tiles=args.adc_tiles,
                    dac_tiles=args.dac_tiles,
                    adc_ref_tile=args.adc_ref_tile,
                    dac_ref_tile=args.dac_ref_tile,
                )
                result["mts_probe"] = {"ok": not bool(mts.get("failures")), "details": mts}
                if mts.get("failures"):
                    result["mts_probe"]["classification"] = "RFDC_MTS_LOCK_FAILED"
            except Exception as exc:
                message = str(exc)
                classification = "RFDC_MTS_LOCK_FAILED"
                if "RFDC_SYSREF_API_UNAVAILABLE" in message or "RFDC_MTS_SHIM_UNAVAILABLE" in message:
                    classification = "RFDC_MTS_API_UNAVAILABLE"
                result["mts_probe"] = {"ok": False, "classification": classification, "error": message}

    if args.probe_mts_matrix:
        if core is None:
            result["mts_probe_matrix"] = {"ok": False, "classification": "RFDC_HANDLE_UNAVAILABLE", "error": "overlay/RFDC handle not loaded"}
        elif not bool(result.get("lmk", {}).get("configured", False)):
            result["mts_probe_matrix"] = {
                "ok": False,
                "classification": "LMK_FULL_LOCK_INCOMPLETE",
                "error": "MTS matrix skipped because LMK full lock is incomplete",
            }
        else:
            try:
                result["mts_probe_matrix"] = core.probe_rfdc_mts_matrix(
                    ref_tiles=_parse_int_list(args.probe_ref_tiles),
                    tile_masks=_parse_int_list(args.probe_tile_masks),
                    max_cases=args.probe_max_cases,
                )
            except Exception as exc:
                result["mts_probe_matrix"] = {"ok": False, "classification": "RFDC_MTS_MATRIX_FAILED", "error": str(exc)}

    classification, gate = _classify(
        result.get("lmk", {}),
        result.get("rfdc_driver", {}),
        result.get("mts_probe") if args.probe_mts else None,
    )
    result["classification"] = classification
    result["data_quality_gate"] = gate
    result["elapsed_s"] = time.monotonic() - start

    output = Path(args.output) if args.output else _default_output()
    output.parent.mkdir(parents=True, exist_ok=True)
    result["output_json"] = str(output)
    output.write_text(json.dumps(_jsonable(result), indent=2, sort_keys=True) + "\n")
    print(json.dumps(_jsonable(result), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
