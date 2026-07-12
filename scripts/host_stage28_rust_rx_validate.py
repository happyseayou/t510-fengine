#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _has_option(name: str) -> bool:
    prefix = name + "="
    return any(arg == name or arg.startswith(prefix) for arg in sys.argv[1:])


def _insert_default(name: str, value: str | None = None) -> None:
    if _has_option(name):
        return
    sys.argv.append(name)
    if value is not None:
        sys.argv.append(value)


def _mode(value: str) -> str:
    key = str(value).strip().lower().replace("-", "_")
    aliases = {
        "time": "time_only",
        "time_only": "time_only",
        "spec": "spec_only",
        "spec_only": "spec_only",
        "dual": "time_spec",
        "time_spec": "time_spec",
    }
    if key not in aliases:
        raise argparse.ArgumentTypeError("mode must be time_only, spec_only, or time_spec")
    return aliases[key]


def _load_validator():
    path = _repo_root() / "scripts" / "host_stage27e_rust_rx_validate.py"
    spec = importlib.util.spec_from_file_location("host_stage27e_rust_rx_validate", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--mode", type=_mode, required=True)
    pre.add_argument("--bandwidth-mhz", type=int, choices=(100, 200), required=True)
    selected, _ = pre.parse_known_args()

    mode = str(selected.mode)
    bandwidth = int(selected.bandwidth_mhz)
    allowed = {(100, "time_spec"), (200, "time_only"), (200, "spec_only")}
    if (bandwidth, mode) not in allowed:
        pre.error("Stage 28 accepts only 100/time_spec, 200/time_only, or 200/spec_only")

    _insert_default("--stage-label", "28")
    _insert_default("--min-combined-t510-udp-payload-mbps", "63000")
    if mode == "time_spec":
        _insert_default("--time-flow-count", "8")
        _insert_default("--spec-flow-count", "16")
        _insert_default("--expected-flow-count", "24")
        _insert_default("--min-active-workers", "24")
        _insert_default("--min-time-pps", "470000")
        _insert_default("--min-spec-pps", "470000")
        _insert_default("--require-waveform")
        _insert_default("--require-spectrum")
    elif mode == "time_only":
        _insert_default("--time-flow-count", "8")
        _insert_default("--spec-flow-count", "0")
        _insert_default("--expected-flow-count", "8")
        _insert_default("--min-active-workers", "8")
        _insert_default("--min-time-pps", "950000")
        _insert_default("--min-spec-pps", "0")
        _insert_default("--require-waveform")
    else:
        _insert_default("--time-flow-count", "0")
        _insert_default("--spec-flow-count", "16")
        _insert_default("--expected-flow-count", "16")
        _insert_default("--min-active-workers", "16")
        _insert_default("--min-time-pps", "0")
        _insert_default("--min-spec-pps", "950000")
        _insert_default("--require-spectrum")

    if mode in ("time_spec", "spec_only"):
        _insert_default("--expected-spec-layout", "27j")
        _insert_default("--expected-spec-chan-count", "256")
    _insert_default("--min-display-hz", "1.0")
    _insert_default("--min-spectrum-hz", "1.0")
    return int(_load_validator().main())


if __name__ == "__main__":
    raise SystemExit(main())
