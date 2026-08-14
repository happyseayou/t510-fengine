"""Read and aggregate Zynq UltraScale+ AMS IIO telemetry.

The RFSoC image exposes the on-chip monitor as an IIO device named ``ams``.
This module intentionally contains no PYNQ dependency so the resident reference
watchdog can sample it at 5 Hz without touching PL MMIO or SPI.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
import statistics
from typing import Any


DEFAULT_IIO_ROOT = Path("/sys/bus/iio/devices")


def find_ams_device(root: Path = DEFAULT_IIO_ROOT) -> Path | None:
    for candidate in sorted(root.glob("iio:device*")):
        try:
            if candidate.joinpath("name").read_text(encoding="ascii").strip() == "ams":
                return candidate
        except OSError:
            continue
    return None


def _read_number(path: Path) -> float:
    return float(path.read_text(encoding="ascii").strip())


def _channel_value(device: Path, stem: str, *, temperature: bool) -> float:
    raw = _read_number(device / f"{stem}_raw")
    scale = _read_number(device / f"{stem}_scale")
    if temperature:
        offset_path = device / f"{stem}_offset"
        offset = _read_number(offset_path) if offset_path.is_file() else 0.0
        return (raw + offset) * scale / 1000.0
    return raw * scale / 1000.0


def read_ams_snapshot(root: Path = DEFAULT_IIO_ROOT) -> dict[str, Any]:
    captured: dict[str, Any] = {
        "supported": False,
        "device": None,
        "temperatures_c": {},
        "voltages_v": {},
        "errors": [],
    }
    device = find_ams_device(root)
    if device is None:
        captured["errors"].append("AMS_IIO_DEVICE_NOT_FOUND")
        return captured
    captured["device"] = str(device)

    for raw_path in sorted(device.glob("in_temp*_raw")):
        stem = raw_path.name.removesuffix("_raw")
        label_path = device / f"{stem}_label"
        try:
            label = (
                label_path.read_text(encoding="ascii").strip()
                if label_path.is_file()
                else stem
            )
            captured["temperatures_c"][label] = _channel_value(
                device, stem, temperature=True
            )
        except (OSError, ValueError) as exc:
            captured["errors"].append(f"{stem}:{type(exc).__name__}:{exc}")

    for raw_path in sorted(device.glob("in_voltage*_raw")):
        stem = raw_path.name.removesuffix("_raw")
        label_path = device / f"{stem}_label"
        try:
            label = (
                label_path.read_text(encoding="ascii").strip()
                if label_path.is_file()
                else stem
            )
            captured["voltages_v"][label] = _channel_value(
                device, stem, temperature=False
            )
        except (OSError, ValueError) as exc:
            captured["errors"].append(f"{stem}:{type(exc).__name__}:{exc}")

    captured["supported"] = bool(
        captured["temperatures_c"] or captured["voltages_v"]
    )
    return captured


def aggregate_ams_snapshots(samples: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = list(samples)

    def aggregate(group: str) -> dict[str, dict[str, float]]:
        names = sorted(
            {
                name
                for row in rows
                for name in dict(row.get(group, {})).keys()
            }
        )
        result: dict[str, dict[str, float]] = {}
        for name in names:
            values = [
                float(row[group][name])
                for row in rows
                if name in dict(row.get(group, {}))
            ]
            if values:
                result[name] = {
                    "min": min(values),
                    "mean": statistics.fmean(values),
                    "max": max(values),
                }
        return result

    errors = [str(error) for row in rows for error in row.get("errors", [])]
    return {
        "supported": any(bool(row.get("supported")) for row in rows),
        "sample_count": len(rows),
        "sample_rate_hz": 5.0,
        "temperatures_c": aggregate("temperatures_c"),
        "voltages_v": aggregate("voltages_v"),
        "errors": errors,
    }
