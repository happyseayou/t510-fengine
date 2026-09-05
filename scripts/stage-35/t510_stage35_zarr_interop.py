#!/usr/bin/env python3
"""Read every Stage 35 array through the independent Python zarr package."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import zarr


ARRAYS = (
    "mean_power_count2",
    "n_valid",
    "mean_i_count_100ms",
    "mean_q_count_100ms",
    "m2_power_count4_100ms",
    "clip_count_100ms",
    "n_valid_100ms",
)
SCANS = (
    "nominal_10ms",
    "nominal_20ms",
    "nominal_50ms",
    "nominal_100ms",
    "fault_injection_100ms",
    "explicit_stop_100ms",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replay-root", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.output_json.exists():
        raise RuntimeError(f"refusing to overwrite {args.output_json}")
    scans = {}
    total_elements = 0
    total_logical_bytes = 0
    for scan_name in SCANS:
        group = zarr.open_group(str(args.replay_root / scan_name), mode="r")
        if set(group.array_keys()) != set(ARRAYS):
            raise RuntimeError(f"{scan_name}: unexpected array set {sorted(group.array_keys())}")
        arrays = {}
        for name in ARRAYS:
            zarray = group[name]
            values = np.asarray(zarray[:])
            if tuple(values.shape) != tuple(zarray.shape) or values.dtype != zarray.dtype:
                raise RuntimeError(f"{scan_name}/{name}: materialized shape/dtype mismatch")
            if values.dtype.kind == "f":
                nan_count = int(np.count_nonzero(np.isnan(values)))
                finite_count = int(np.count_nonzero(np.isfinite(values)))
            else:
                nan_count = 0
                finite_count = int(values.size)
            logical_bytes = int(values.nbytes)
            total_elements += int(values.size)
            total_logical_bytes += logical_bytes
            arrays[name] = {
                "shape": list(values.shape),
                "chunks": list(zarray.chunks),
                "dtype": values.dtype.str,
                "elements": int(values.size),
                "logical_bytes": logical_bytes,
                "finite_values": finite_count,
                "nan_values": nan_count,
                "logical_c_order_sha256": hashlib.sha256(values.tobytes(order="C")).hexdigest(),
            }
        scans[scan_name] = arrays
    result = {
        "format": "T510_STAGE35_ZARR_INTEROP_V1",
        "status": "PASS",
        "reader": {
            "package": "zarr",
            "version": zarr.__version__,
            "numpy_version": np.__version__,
        },
        "scan_count": len(scans),
        "array_count": len(scans) * len(ARRAYS),
        "total_elements": total_elements,
        "total_logical_bytes": total_logical_bytes,
        "scans": scans,
    }
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    with args.output_json.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(
        f"STAGE35_ZARR_INTEROP_PASS scans={len(scans)} arrays={len(scans) * len(ARRAYS)} "
        f"elements={total_elements} output={args.output_json}"
    )


if __name__ == "__main__":
    main()
