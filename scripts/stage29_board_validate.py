#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def _phases(value: str) -> tuple[float, ...]:
    try:
        result = tuple(float(item.strip()) for item in value.split(","))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("phases must be eight comma-separated degrees") from exc
    if len(result) != 8:
        raise argparse.ArgumentTypeError("phases must contain exactly eight values")
    return result


def _jsonable(value: Any) -> Any:
    try:
        import numpy as np
    except ImportError:
        np = None  # type: ignore[assignment]
    if np is not None and isinstance(value, np.ndarray):
        return value.tolist()
    if np is not None and isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def main() -> int:
    sys.path.insert(0, str(_root()))
    from python.stage29 import (
        DacChannelConfig,
        EXPECTED_CORE_VERSION,
        FlowDestination,
        Stage29Config,
        Stage29Controller,
        default_spec_destinations,
        default_time_destinations,
    )

    parser = argparse.ArgumentParser(description="Stage 29 frozen-profile board gate")
    parser.add_argument("--bandwidth-mhz", type=int, choices=(100, 200), required=True)
    parser.add_argument("--mode", choices=("time_only", "spec_only", "time_spec"), required=True)
    parser.add_argument("--center-mhz", type=float, default=100.0)
    parser.add_argument("--board-id", type=int, default=0, help="16-bit board identity carried in every T510 packet")
    parser.add_argument("--dac-mhz", type=float, default=60.010)
    parser.add_argument("--amplitude-percent", type=float, default=25.0)
    parser.add_argument("--phases", type=_phases, default=(0.0,) * 8)
    parser.add_argument("--receiver-ip", default="10.0.1.16")
    parser.add_argument("--receiver-mac", default="08:c0:eb:d5:95:b2")
    parser.add_argument("--source-ip", default="10.0.1.1")
    parser.add_argument("--source-mac", default="02:00:00:00:00:01")
    parser.add_argument("--time-source-port-base", type=int, default=4000)
    parser.add_argument("--spec-source-port-base", type=int, default=4008)
    parser.add_argument("--seconds", type=float, default=60.0)
    parser.add_argument("--bitfile", default=str(_root() / "overlay" / "t510_fengine.bit"))
    parser.add_argument("--output")
    args = parser.parse_args()

    time_destinations = tuple(
        FlowDestination(
            enabled=item.enabled,
            ip=args.receiver_ip,
            mac=args.receiver_mac,
            destination_port=item.destination_port,
            source_port=args.time_source_port_base + flow,
        )
        for flow, item in enumerate(default_time_destinations())
    )
    spec_destinations = tuple(
        FlowDestination(
            enabled=item.enabled,
            ip=args.receiver_ip,
            mac=args.receiver_mac,
            destination_port=item.destination_port,
            source_port=args.spec_source_port_base + flow,
        )
        for flow, item in enumerate(default_spec_destinations())
    )
    dac_channels = tuple(
        DacChannelConfig(
            rf_frequency_mhz=args.dac_mhz,
            amplitude=args.amplitude_percent,
            phase_deg=args.phases[channel],
        )
        for channel in range(8)
    )
    config = Stage29Config(
        bandwidth_mhz=args.bandwidth_mhz,
        mode=args.mode,
        center_mhz=args.center_mhz,
        board_id=args.board_id,
        source_ip=args.source_ip,
        source_mac=args.source_mac,
        time_destinations=time_destinations,
        spec_destinations=spec_destinations,
        dac_channels=dac_channels,
    )
    controller = Stage29Controller(args.bitfile)
    applied = controller.apply(config, fresh_download=True)
    gate = controller.validate(seconds=max(float(args.seconds), 0.1))
    result = {
        "classification": gate.get("classification"),
        "ok": bool(gate.get("ok")),
        "stage": 29,
        "core_version": f"0x{EXPECTED_CORE_VERSION:08x}",
        "fresh_download": True,
        "profile": {
            "bandwidth_mhz": config.bandwidth_mhz,
            "mode": config.mode.value,
            "center_mhz": config.center_mhz,
            "board_id": config.board_id,
            "source_ip": config.source_ip,
            "source_mac": config.source_mac,
            "dac_targets_mhz": list(config.target_mhz_by_channel),
            "time_destinations": [item.__dict__ for item in config.time_destinations],
            "spec_destinations": [item.__dict__ for item in config.spec_destinations],
            "flow_count": config.flow_count,
            "expected_packet_rates": config.expected_packet_rates,
        },
        "apply": applied,
        "validation": gate,
    }
    output = Path(args.output) if args.output else _root() / "reports" / "board" / f"stage29_{config.bandwidth_mhz}mhz_{config.mode.value}_board.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(_jsonable(result), indent=2, sort_keys=True) + "\n")
    print(json.dumps(_jsonable(result), indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
