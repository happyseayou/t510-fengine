#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any


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
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _wrap_phase_deg(value: float) -> float:
    while value > 180.0:
        value -= 360.0
    while value <= -180.0:
        value += 360.0
    return value


def _phase_pp(values: list[float]) -> float | None:
    if not values:
        return None
    relative = [_wrap_phase_deg(value - values[0]) for value in values]
    return float(max(relative) - min(relative))


def _amp_pp_percent(values: list[float]) -> float | None:
    if not values:
        return None
    mean = sum(values) / len(values)
    if mean == 0.0:
        return None
    return float(100.0 * (max(values) - min(values)) / mean)


def _manual_time_witness_capture(core: Any, *, delay_s: float, timeout: float, capture_words: int) -> dict[str, Any]:
    try:
        from python.packet import T510PacketHeader
    except ImportError:
        from packet import T510PacketHeader

    regs = core.regs
    core.ctrl.write(regs.TX_PAYLOAD_WITNESS_STREAM_FILTER, 2)
    core.ctrl.write(regs.TX_PAYLOAD_WITNESS_CAPTURE_WORDS, int(capture_words))
    core.ctrl.write(regs.TX_PAYLOAD_WITNESS_CONTROL, 0x2)
    core.ctrl.write(regs.TX_PAYLOAD_WITNESS_CONTROL, 0x1)

    deadline = time.monotonic() + float(timeout)
    status = core.read_status()
    while time.monotonic() < deadline:
        status = core.read_status()
        if status.get("tx_payload_witness_valid"):
            break
        time.sleep(0.005)
    else:
        raise TimeoutError(f"TX witness timeout: status=0x{status.get('tx_payload_witness_status', 0):08x}")

    if delay_s > 0.0:
        time.sleep(float(delay_s))

    word_count = max(0, min(int(capture_words), int(status.get("tx_payload_witness_word_count", 0))))
    words32 = [
        int(core.ctrl.read(regs.TX_PAYLOAD_WITNESS_BUFFER_BASE + 4 * idx))
        for idx in range(word_count * 2)
    ]
    axis_words = [
        (words32[idx * 2] & 0xFFFF_FFFF) | ((words32[idx * 2 + 1] & 0xFFFF_FFFF) << 32)
        for idx in range(word_count)
    ]
    if len(axis_words) < 16:
        raise RuntimeError(f"TX witness captured only {len(axis_words)} words")
    header = T510PacketHeader.from_axis_words(axis_words[:16])
    witness = {
        "axis_words": axis_words,
        "payload_words": axis_words[16:],
        "header": header,
        "metadata": {
            "sample0": int(core.ctrl.read(regs.TX_PAYLOAD_WITNESS_SAMPLE0_LO))
            | (int(core.ctrl.read(regs.TX_PAYLOAD_WITNESS_SAMPLE0_HI)) << 32),
        },
    }
    decoded = core.decode_time_payload_iq(witness, channel=0)
    metrics = core.compute_payload_phase_metrics(
        decoded,
        sample_rate_hz=245_760_000.0,
        observe_center_hz=130_000_000.0,
        dac_signal_hz=119_200_000.0,
        configured_phase_deg=0.0,
    )
    return {
        "phase_error_deg": float(metrics["phase_error_deg"]),
        "amplitude_code": float(metrics["amplitude_code"]),
        "fit_residual_fraction": float(metrics["fit_residual_fraction"]),
        "sample0": int(header.sample0),
        "status": int(status.get("tx_payload_witness_status", 0)),
        "word_count": int(word_count),
    }


def main() -> int:
    _add_repo_python_path()
    from python.t510_fengine import T510FEngine
    import pynq_stage19_phase_root_cause_check as stage19

    parser = argparse.ArgumentParser(description="Probe TX payload witness CDC readout delay.")
    parser.add_argument("--bitfile", default=str(_repo_root() / "overlay" / "t510_fengine.bit"))
    parser.add_argument("--delays-ms", default="0,5,20,100")
    parser.add_argument("--frames", type=int, default=40)
    parser.add_argument("--timeout", type=float, default=2.0)
    parser.add_argument("--capture-words", type=int, default=1040)
    parser.add_argument("--download", action="store_true")
    args = parser.parse_args()

    config_args = argparse.Namespace(
        center_mhz=130.0,
        bw_mhz=100.0,
        amplitude=2048,
        configured_phase_deg=0.0,
        allow_partial_prereq=False,
        adc_port_mask=0x1,
        mts_adc_tiles=None,
        mts_dac_tiles=None,
        mts_adc_ref_tile=0,
        mts_dac_ref_tile=0,
        timeout=float(args.timeout),
        chan0=0,
        chan_count=64,
        time_count=4,
    )
    delays_s = [float(item.strip()) / 1000.0 for item in str(args.delays_ms).split(",") if item.strip()]
    core = T510FEngine(args.bitfile, download=bool(args.download))
    setup = stage19._configure_condition(
        core,
        config_args,
        signal_mhz=119.2,
        mode="time",
        dac_source_mode="constant_phasor",
    )
    result: dict[str, Any] = {
        "setup": {
            "signal_hz": float(setup["signal_hz"]),
            "center_hz": float(setup["center_hz"]),
            "dac_tone_hz": float(setup.get("sysref_config", {}).get("dac_tone_hz", 0.0)),
            "status_after_start": setup.get("status_after_start", {}),
        },
        "delays": {},
    }
    for delay_s in delays_s:
        rows: list[dict[str, Any]] = []
        errors: list[str] = []
        for _idx in range(int(args.frames)):
            try:
                rows.append(
                    _manual_time_witness_capture(
                        core,
                        delay_s=delay_s,
                        timeout=float(args.timeout),
                        capture_words=int(args.capture_words),
                    )
                )
            except Exception as exc:  # noqa: BLE001 - this is a diagnostic script.
                errors.append(str(exc))
        phases = [float(row["phase_error_deg"]) for row in rows]
        amps = [float(row["amplitude_code"]) for row in rows]
        result["delays"][f"{delay_s * 1000.0:.3f}ms"] = {
            "count": len(rows),
            "errors": errors[:8],
            "phase_pp_deg": _phase_pp(phases),
            "amplitude_pp_percent": _amp_pp_percent(amps),
            "phase_first10": phases[:10],
            "amplitude_first10": amps[:10],
            "residual_first10": [float(row["fit_residual_fraction"]) for row in rows[:10]],
            "sample0_delta_first10": [
                int(rows[idx + 1]["sample0"]) - int(rows[idx]["sample0"])
                for idx in range(min(len(rows) - 1, 10))
            ],
            "status_unique": sorted({int(row["status"]) for row in rows}),
            "word_count_unique": sorted({int(row["word_count"]) for row in rows}),
        }
    print(json.dumps(_jsonable(result), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
