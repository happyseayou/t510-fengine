#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


EXPECTED_CORE_VERSION = 0x0001_002B


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


def _mode_key(value: str) -> str:
    key = str(value).strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "time": "time_only",
        "time_only": "time_only",
        "spec": "spec_only",
        "spec_only": "spec_only",
        "time_spec": "time_spec",
        "dual": "time_spec",
    }
    if key not in aliases:
        raise argparse.ArgumentTypeError("mode must be time_only, spec_only, or time_spec")
    return aliases[key]


def _parse_case_item(item: str) -> tuple[str, int]:
    if ":" not in item:
        raise argparse.ArgumentTypeError("case items must be mode:bandwidth, e.g. time_spec:100")
    mode, bandwidth = item.split(":", 1)
    bw = int(round(float(bandwidth.lower().replace("mhz", "").strip())))
    if bw not in (20, 100, 200):
        raise argparse.ArgumentTypeError("bandwidth must be 20, 100, or 200")
    return _mode_key(mode), bw


def _parse_cases(value: str) -> list[tuple[str, int]]:
    key = str(value).strip().lower()
    if key in ("converge", "convergence", "stage27h", "fft_fullrate", "time_spec_100"):
        return [("time_spec", 100)]
    if key == "smoke":
        return [("spec_only", 100), ("time_spec", 100)]
    if key == "full":
        return [
            ("time_only", 20),
            ("time_only", 100),
            ("time_only", 200),
            ("spec_only", 20),
            ("spec_only", 100),
            ("spec_only", 200),
            ("time_spec", 20),
            ("time_spec", 100),
        ]
    return [_parse_case_item(item.strip()) for item in value.split(",") if item.strip()]


def _validate_reject(core: Any) -> dict[str, Any]:
    try:
        core.configure_science_27h(bandwidth_mhz=200, output_mode="time_spec", start=False)
    except ValueError as exc:
        return {
            "mode": "TIME_SPEC",
            "bandwidth_mhz": 200,
            "classification": "STAGE27H_TIME_SPEC_200_REJECT_PASS",
            "ok": True,
            "error": str(exc),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "mode": "TIME_SPEC",
            "bandwidth_mhz": 200,
            "classification": "STAGE27H_TIME_SPEC_200_REJECT_FAIL",
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    return {
        "mode": "TIME_SPEC",
        "bandwidth_mhz": 200,
        "classification": "STAGE27H_TIME_SPEC_200_NOT_REJECTED",
        "ok": False,
        "error": "configure_science_27h accepted TIME_SPEC at 200MHz",
    }


def main() -> int:
    _add_repo_python_path()
    from python.t510_fengine import T510FEngine

    default_bitfile = _repo_root() / "overlay" / "t510_fengine.bit"
    default_output = _repo_root() / "reports" / "board" / "stage27h_time_spec_100mhz_fft_fullrate_board.json"
    parser = argparse.ArgumentParser(description="Stage 27h TIME_SPEC 100MHz FFT-only full-rate board validation.")
    parser.add_argument("--bitfile", default=str(default_bitfile))
    parser.add_argument("--no-download", action="store_true")
    parser.add_argument("--seconds", type=float, default=10.0)
    parser.add_argument("--matrix", default="converge", help="converge, smoke, full, or comma list like time_spec:100")
    parser.add_argument("--dst-ip", default="10.0.1.16")
    parser.add_argument("--dst-mac", default="08:c0:eb:d5:95:b2")
    parser.add_argument("--src-ip", default="10.0.1.1")
    parser.add_argument("--src-mac", default="02:00:00:00:00:01")
    parser.add_argument("--time-dst-port-base", type=int, default=4300)
    parser.add_argument("--spec-dst-port-base", type=int, default=4308)
    parser.add_argument("--time-src-port-base", type=int, default=4000)
    parser.add_argument("--spec-src-port-base", type=int, default=4008)
    parser.add_argument("--time-endpoint-base", type=int, default=0)
    parser.add_argument("--spec-endpoint-base", type=int, default=8)
    parser.add_argument("--time-flow-count", type=int, default=8, choices=(1, 2, 4, 8))
    parser.add_argument("--spec-route-count", type=int, default=16)
    parser.add_argument("--spec-chan-count", type=int, default=256)
    parser.add_argument("--spec-time-count", type=int, default=1)
    parser.add_argument("--spec-chan0-stride", type=int, default=256)
    parser.add_argument("--time-payload-nsamp", type=int, default=64)
    parser.add_argument("--time-live-interval-beats", type=int, default=0)
    parser.add_argument("--input-mask", default="0x00ff")
    parser.add_argument("--pfb-taps", type=int, default=0)
    parser.add_argument("--pfb-fft-shift", type=lambda value: int(value, 0), default=0x0556)
    parser.add_argument("--min-time-pps", type=float, default=470_000.0)
    parser.add_argument("--min-spec-pps", type=float, default=470_000.0)
    parser.add_argument("--min-combined-t510-udp-payload-mbps", type=float, default=63_000.0)
    parser.add_argument("--clock-ref", default="external_10mhz")
    parser.add_argument("--sync-mode", default="external_pps")
    parser.add_argument("--measurement-ready-timeout-s", type=float, default=10.0)
    parser.add_argument("--settle-s", type=float, default=0.05)
    parser.add_argument("--no-start", action="store_true")
    parser.add_argument("--skip-reject-check", action="store_true")
    parser.add_argument("--diagnostic-ignore-link-gate", action="store_true")
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
    for index, (mode, bandwidth_mhz) in enumerate(_parse_cases(args.matrix)):
        validations.append(
            core.run_stage27h_time_spec_fft_fullrate_validation(
                configure=True,
                expected_core_version=expected_core_version,
                bandwidth_mhz=bandwidth_mhz,
                output_mode=mode,
                seconds=float(args.seconds),
                min_time_pps=float(args.min_time_pps),
                min_spec_pps=float(args.min_spec_pps),
                min_combined_t510_udp_payload_mbps=float(args.min_combined_t510_udp_payload_mbps),
                measurement_ready_timeout_s=float(args.measurement_ready_timeout_s),
                dst_ip=args.dst_ip,
                dst_mac=args.dst_mac,
                src_ip=args.src_ip,
                src_mac=args.src_mac,
                time_dst_port_base=int(args.time_dst_port_base),
                spec_dst_port_base=int(args.spec_dst_port_base),
                time_src_port_base=int(args.time_src_port_base),
                spec_src_port_base=int(args.spec_src_port_base),
                time_endpoint_base=int(args.time_endpoint_base),
                spec_endpoint_base=int(args.spec_endpoint_base),
                time_flow_count=int(args.time_flow_count),
                spec_route_count=int(args.spec_route_count),
                spec_chan_count=int(args.spec_chan_count),
                spec_time_count=int(args.spec_time_count),
                spec_chan0_stride=int(args.spec_chan0_stride),
                time_payload_nsamp=int(args.time_payload_nsamp),
                time_live_interval_beats=int(args.time_live_interval_beats),
                input_mask=int(args.input_mask, 0) if isinstance(args.input_mask, str) else int(args.input_mask),
                pfb_taps=int(args.pfb_taps),
                pfb_fft_shift=int(args.pfb_fft_shift),
                diagnostic_ignore_link_gate=bool(args.diagnostic_ignore_link_gate),
                clock_ref=(None if index > 0 else (None if str(args.clock_ref).lower() == "none" else str(args.clock_ref))),
                sync_mode=(None if index > 0 else (None if str(args.sync_mode).lower() == "none" else str(args.sync_mode))),
                expected_clock_ref=(None if str(args.clock_ref).lower() == "none" else str(args.clock_ref)),
                expected_sync_mode=(None if str(args.sync_mode).lower() == "none" else str(args.sync_mode)),
                start=not bool(args.no_start),
                settle_s=float(args.settle_s),
            )
        )

    reject = None if args.skip_reject_check else _validate_reject(core)
    case_errors: list[str] = []
    case_blockers: list[str] = []
    for item in validations:
        for error in item.get("errors", []):
            if error not in case_errors:
                case_errors.append(str(error))
        for blocker in item.get("blockers", []):
            if blocker not in case_blockers:
                case_blockers.append(str(blocker))
    all_cases_ok = all(bool(item.get("ok", False)) for item in validations)
    reject_ok = True if reject is None else bool(reject.get("ok", False))
    ok = not errors and all_cases_ok and reject_ok
    classification = "STAGE27H_TIME_SPEC_100MHZ_FFT_FULLRATE_BOARD_PASS" if ok else "STAGE27H_TIME_SPEC_100MHZ_FFT_FULLRATE_BOARD_FAIL"
    result = {
        "expected_core_version": f"0x{expected_core_version:08x}",
        "core_version": f"0x{int(initial_status.get('core_version', 0)):08x}",
        "classification": classification,
        "ok": ok,
        "host_receiver_validated": False,
        "production_scope": dict(core.STAGE27H_PRODUCTION_SCOPE),
        "science_data_scope": "Stage 27h production TIME/SPEC science streams plus Jupyter control/preview",
        "payload_contract": "SPEC product_id=FENGINE_IQ16 nchan=4096 16 blocks x 256 channels x 1 spectrum-time x 8 inputs x IQ16",
        "rate_gate": "TIME 480kpps + SPEC 480kpps, combined T510 UDP payload target 63.8976Gbps",
        "status_initial": initial_status,
        "validations": validations,
        "reject_check": reject,
        "host_receiver_next_step": {
            "binary": "rust/t510_time_rx/target/release/t510_time_rx",
            "interface": "ens2f0np0",
            "web": "0.0.0.0:8089",
            "fanout_group": "0x279",
            "dst_port_range": f"{args.time_dst_port_base}..{args.spec_dst_port_base + args.spec_route_count - 1}",
            "time_ports": f"{args.time_dst_port_base}..{args.time_dst_port_base + args.time_flow_count - 1}",
            "spec_ports": f"{args.spec_dst_port_base}..{args.spec_dst_port_base + args.spec_route_count - 1}",
            "recommended_args": [
                "--backend",
                "fanout",
                "--flow-count",
                "24",
                "--time-flow-count",
                str(args.time_flow_count),
                "--spec-flow-count",
                str(args.spec_route_count),
                "--fanout-mode",
                "port",
                "--fanout-group",
                "0x279",
                "--initial-bandwidth-mhz",
                "100",
            ],
        },
        "errors": errors + [f"validation:{error}" for error in case_errors],
        "case_errors": case_errors,
        "case_blockers": case_blockers,
    }
    _write_output(args.output, result)
    print(json.dumps(_jsonable(result), indent=2, sort_keys=True))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
