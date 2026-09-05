#!/usr/bin/env python3
"""Finalize 48 independently generated Stage 35 analysis shards."""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import sys
import traceback
from pathlib import Path

import numpy as np
import pyarrow as pa

import t510_stage35_s2_analyze as analysis


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--slurm-evidence", type=Path, required=True)
    args = parser.parse_args()
    config = analysis.load_json(args.config)
    analysis.validate_config(config)
    identity = analysis.verify_inputs(config)
    root = Path(config["output_root"])
    root.mkdir(parents=True, exist_ok=True)
    state_path = root / "analysis_state.json"
    tasks = []
    for scan_index, scan in enumerate(config["scans"]):
        for block in range(analysis.BLOCK_COUNT):
            shard = f"scan={scan['label']}/block={block:02d}"
            required = [
                root / "metrics_by_scan" / shard / "part.parquet",
                root / "temporal_metrics" / shard / "part.parquet",
                root / "block_metadata" / shard / "metadata.json",
            ] + [
                root / "integration_series" / f"tau={tau:g}s" / shard / "part.parquet"
                for tau in map(float, config["integration_seconds"])
            ]
            missing = [str(path) for path in required if not path.is_file()]
            if missing:
                raise RuntimeError(f"distributed shard is incomplete: {missing}")
            metadata = analysis.load_json(required[2])
            tasks.append({
                "scan_index": scan_index, "scan_label": scan["label"], "block": block,
                "status": "completed", "elapsed_seconds": metadata["elapsed_seconds"],
                "bootstrap_block_s": metadata["bootstrap_block_s"],
            })
    frozen = root / "analysis_config.json"
    if not frozen.exists():
        shutil.copyfile(args.config, frozen)
    reproduction = root / "reproduction"
    reproduction.mkdir(exist_ok=True)
    for source in (Path(analysis.__file__).resolve(), Path(__file__).resolve(), args.slurm_evidence):
        if source.is_file():
            shutil.copyfile(source, reproduction / source.name)
    state = {
        "format": "T510_STAGE35_S2_ANALYSIS_QUEUE_V1",
        "execution": "SLURM_DISTRIBUTED_8_NODE_48_SHARD",
        "status": "finalizing",
        "created_unix_ms": analysis.unix_ms(),
        "config_sha256": analysis.sha256_file(frozen),
        "input_identity": identity,
        "environment": {"python": sys.version, "platform": platform.platform(),
                        "numpy": np.__version__, "pyarrow": pa.__version__},
        "tasks": tasks,
        "slurm_evidence_sha256": analysis.sha256_file(args.slurm_evidence),
        "error": None,
    }
    analysis.write_json_atomic(state_path, state)
    try:
        summary = analysis.finalize_analysis(config, root)
        state.update({"status": "completed", "finished_unix_ms": analysis.unix_ms(),
                      "summary": summary})
        analysis.write_json_atomic(state_path, state)
        return 0
    except Exception as error:
        state.update({"status": "failed", "finished_unix_ms": analysis.unix_ms(),
                      "error": {"message": f"{type(error).__name__}: {error}",
                                "traceback": traceback.format_exc()}})
        analysis.write_json_atomic(state_path, state)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
