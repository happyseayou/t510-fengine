#!/usr/bin/env python3
from __future__ import annotations

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
    if value is None:
        sys.argv.append(name)
    else:
        sys.argv.extend([name, value])


def _load_stage27e_validator():
    path = _repo_root() / "scripts" / "host_stage27e_rust_rx_validate.py"
    spec = importlib.util.spec_from_file_location("host_stage27e_rust_rx_validate", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    _insert_default("--stage-label", "27j")
    _insert_default("--mode", "time_spec")
    _insert_default("--bandwidth-mhz", "100")
    _insert_default("--time-flow-count", "8")
    _insert_default("--spec-flow-count", "16")
    _insert_default("--expected-flow-count", "24")
    _insert_default("--expected-spec-layout", "27j")
    _insert_default("--expected-spec-chan-count", "256")
    _insert_default("--min-active-workers", "24")
    _insert_default("--min-time-pps", "470000")
    _insert_default("--min-spec-pps", "470000")
    _insert_default("--min-combined-t510-udp-payload-mbps", "63000")
    _insert_default("--require-waveform")
    _insert_default("--require-spectrum")
    _insert_default("--min-display-hz", "1.0")
    _insert_default("--min-spectrum-hz", "1.0")
    module = _load_stage27e_validator()
    return int(module.main())


if __name__ == "__main__":
    raise SystemExit(main())
