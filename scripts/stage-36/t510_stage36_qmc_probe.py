#!/usr/bin/env python3
"""Journaled, stopped-board Stage 36 QMC qualification on the frozen v34 image.

This diagnostic does not reprogram the FPGA, change clocks, or start a stream.
The original effective QMC settings are restored on an apply failure. Disabled
power-on QMC uses event 0, which the high-speed ADC setter rejects: restoration
uses a TILE event for those disabled settings and records that normalization.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import sys
import time


QMC_GAIN = 16383 / 8192
ADC_ERROR_MASK = 0x00FF0FFF  # FIFO, decimator, QMC, sub-ADC decoder status.
BITFILE = "/opt/t510-agent/current/overlay/t510_fengine.bit"


def gain_settings() -> dict:
    return dict(EnableGain=1, EnablePhase=0, GainCorrectionFactor=QMC_GAIN,
                PhaseCorrectionFactor=0.0, OffsetCorrectionFactor=0, EventSource=2)


def restoration_settings(original: dict) -> dict:
    settings = dict(original)
    if settings["EventSource"] in (0, 1):
        if settings["EnableGain"] or settings["EnablePhase"] or settings["OffsetCorrectionFactor"]:
            raise RuntimeError("cannot normalize event source of active original QMC")
        settings["EventSource"] = 2
    return settings


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_suffix(path.suffix + ".partial")
    with pending.open("w") as out:
        json.dump(value, out, indent=2, sort_keys=True)
        out.write("\n")
        out.flush()
        os.fsync(out.fileno())
    pending.replace(path)


def snapshot(core, xrfdc) -> dict:
    status = core.read_status()
    rows = []
    for tile in range(4):
        for block in range(2):
            obj = core.rfdc.adc_tiles[tile].blocks[block]
            interrupt = xrfdc._ffi.new("u32 *")
            obj._call_function("GetIntrStatus", interrupt)
            rows.append(dict(tile=tile, block=block, qmc=dict(obj.QMCSettings),
                             mixer=dict(obj.MixerSettings), dsa=dict(obj.DSA),
                             decimation=int(obj.DecimationFactor),
                             interrupt_status=int(interrupt[0]),
                             adc_error_bits=int(interrupt[0]) & ADC_ERROR_MASK))
    return dict(unix_ms=time.time_ns() // 1_000_000,
                core_version=int(status["core_version"]),
                streaming=bool(status["streaming"]),
                dac_enable_mask=int(core.ctrl.read(core.regs.DAC_ENABLE_MASK)),
                fft_shift=int(core.ctrl.read(core.regs.PFB_FFT_SHIFT)), blocks=rows)


def require_stopped(value: dict) -> None:
    if value["core_version"] != 0x00010034:
        raise RuntimeError("QMC qualification requires the frozen v34 core")
    if value["streaming"] or value["dac_enable_mask"]:
        raise RuntimeError("QMC mutation requires stopped science and muted DACs")


def apply_rows(core, xrfdc, rows: list[dict]) -> None:
    # Program both physical ADCs in each tile before triggering its update.
    for tile in range(4):
        for row in rows:
            if row["tile"] == tile:
                core.rfdc.adc_tiles[tile].blocks[row["block"]].QMCSettings = dict(row["qmc"])
        for block in range(2):
            core.rfdc.adc_tiles[tile].blocks[block].UpdateEvent(xrfdc.EVENT_QMC)


def verify_rows(actual: dict, expected: list[dict], original: dict) -> None:
    for row, want, prior in zip(actual["blocks"], expected, original["blocks"], strict=True):
        if (row["tile"], row["block"]) != (want["tile"], want["block"]):
            raise RuntimeError("QMC ADC mapping changed")
        if row["qmc"] != want["qmc"]:
            raise RuntimeError(f"QMC readback mismatch: {row}, expected {want}")
        for key in ("mixer", "dsa", "decimation"):
            if row[key] != prior[key]:
                raise RuntimeError(f"QMC operation unexpectedly changed {key}")


def restore(core, xrfdc, journal: dict, path: Path) -> dict:
    require_stopped(snapshot(core, xrfdc))
    rows = [dict(tile=r["tile"], block=r["block"], qmc=restoration_settings(r["qmc"]))
            for r in journal["original"]["blocks"]]
    journal["restore_requested"] = rows
    journal["state"] = "restoring"
    write_json(path, journal)
    apply_rows(core, xrfdc, rows)
    actual = snapshot(core, xrfdc)
    verify_rows(actual, rows, journal["original"])
    journal.update(state="restored", restored=actual,
                   restore_note="disabled power-on event 0/1 normalized to supported TILE event 2")
    write_json(path, journal)
    return actual


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("snapshot", "apply", "restore"))
    parser.add_argument("--journal", type=Path, required=True)
    args = parser.parse_args()
    os.environ["XILINX_XRT"] = "/usr"
    sys.dont_write_bytecode = True
    sys.path.insert(0, "/opt/t510-agent/current")
    import xrfdc
    from python.t510_fengine import T510FEngine

    with Path("/run/t510-configure.lock").open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        core = T510FEngine(BITFILE, download=False)
        original = snapshot(core, xrfdc)
        if args.action == "snapshot":
            print(json.dumps(original))
            return 0
        require_stopped(original)
        if args.action == "restore":
            journal = json.loads(args.journal.read_text())
            actual = restore(core, xrfdc, journal, args.journal)
            print(json.dumps(dict(status="RESTORED", snapshot=actual)))
            return 0
        if args.journal.exists():
            raise RuntimeError("refusing repeated apply: journal already exists")
        # Validate restorability before the first write, including partial apply.
        for row in original["blocks"]:
            restoration_settings(row["qmc"])
            if row["decimation"] != 12 or row["dsa"]["Attenuation"] != 0:
                raise RuntimeError("RFDC configuration differs from frozen baseline")
        journal = dict(format="T510_STAGE36_QMC_QUALIFICATION_V1", state="applying",
                       original=original, requested_gain=QMC_GAIN)
        write_json(args.journal, journal)
        rows = [dict(tile=r["tile"], block=r["block"], qmc=gain_settings())
                for r in original["blocks"]]
        try:
            apply_rows(core, xrfdc, rows)
            actual = snapshot(core, xrfdc)
            verify_rows(actual, rows, original)
            journal.update(state="applied", applied=actual)
            write_json(args.journal, journal)
            # Save historical sticky bits above, then clear for this observation.
            for tile in core.rfdc.adc_tiles:
                for block in tile.blocks[:2]:
                    block._call_function("IntrClr", ADC_ERROR_MASK)
            clean = snapshot(core, xrfdc)
            journal["after_interrupt_clear"] = clean
            write_json(args.journal, journal)
            if any(row["adc_error_bits"] for row in clean["blocks"]):
                raise RuntimeError("RFDC error reasserted before capture")
        except Exception as exc:
            journal["apply_error"] = repr(exc)
            write_json(args.journal, journal)
            restore(core, xrfdc, journal, args.journal)
            raise
        print(json.dumps(dict(status="APPLIED", snapshot=clean)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
