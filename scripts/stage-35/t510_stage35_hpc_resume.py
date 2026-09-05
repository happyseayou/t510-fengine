#!/usr/bin/env python3
"""Pull a sealed Slurm analysis and continue the Stage 35 XCORR/app queue."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import time
import traceback
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import t510_stage35_s2_queue as base


def get(url: str, timeout: float = 15) -> bytes:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return response.read()


def download(url: str, destination: Path) -> str:
    partial = destination.with_name(destination.name + ".partial")
    if destination.exists() or partial.exists():
        raise RuntimeError(f"refusing to overwrite download {destination}")
    digest = hashlib.sha256()
    with urllib.request.urlopen(url, timeout=3600) as response, partial.open("xb") as output:
        for chunk in iter(lambda: response.read(8 * 1024 * 1024), b""):
            output.write(chunk); digest.update(chunk)
        output.flush(); os.fsync(output.fileno())
    partial.replace(destination)
    return digest.hexdigest()


def report_config(args: argparse.Namespace, analysis_root: Path, output: Path) -> None:
    value = json.loads(args.report_template.read_text())
    source = json.loads(args.source_analysis_config.read_text())
    value["analysis_root"] = str(analysis_root)
    value["analysis_manifest_sha256"] = base.sha256_file(analysis_root / "analysis_manifest.json")
    value["queue_manifest_sha256"] = source["queue_manifest_sha256"]
    center_hz = args.center_mhz * 1e6
    value["frequency_axis"] = {
        "center_hz": center_hz, "channel_width_hz": 78125.0,
        "order": "ascending_rf_hz", "first_global_bin": 2048, "last_global_bin": 2047,
        "rf_min_hz": center_hz - 160e6, "rf_max_hz": center_hz + 159921875.0,
        "landmarks": [
            {"label": "baseband DC", "rf_hz": center_hz, "global_bin": 0},
            {"label": "digital sentinel", "rf_hz": center_hz - 60e6, "global_bin": 3328},
        ],
    }
    value["time_histograms"] = []
    for control in source["time_controls"]:
        path = Path(control["path"]) / "histogram.csv"
        value["time_histograms"].append({"label": control["label"], "path": str(path),
                                          "sha256": base.sha256_file(path)})
    base.write_json_new(output, value)


def verify_analysis(root: Path) -> dict[str, Any]:
    manifest_path = root / "analysis_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    expected = (root / "analysis_manifest.sha256").read_text().split()[0]
    if base.sha256_file(manifest_path) != expected:
        raise RuntimeError("analysis manifest digest mismatch")
    for row in manifest["files"]:
        path = root / row["path"]
        if not path.is_file() or path.stat().st_size != int(row["bytes"]):
            raise RuntimeError(f"analysis payload size mismatch: {path}")
        if base.sha256_file(path) != row["sha256"]:
            raise RuntimeError(f"analysis payload digest mismatch: {path}")
    return {"manifest_sha256": expected, "files": len(manifest["files"]),
            "bytes": sum(int(row["bytes"]) for row in manifest["files"])}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue-id", required=True)
    parser.add_argument("--ready-url", required=True)
    parser.add_argument("--analysis-base-url", required=True)
    parser.add_argument("--analysis-dir-name", required=True)
    parser.add_argument("--measurement-root", type=Path, default=Path("/var/lib/t510/stage35"))
    parser.add_argument("--source-analysis-config", type=Path, required=True)
    parser.add_argument("--report-template", type=Path, required=True)
    parser.add_argument("--helper-dir", type=Path, required=True)
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--sidecar", type=Path, required=True)
    parser.add_argument("--replay-evidence", type=Path, required=True)
    parser.add_argument("--preflight-pcap", type=Path, required=True)
    parser.add_argument("--chrome", type=Path, required=True)
    parser.add_argument("--chromedriver", type=Path, required=True)
    parser.add_argument("--app-root", type=Path, required=True)
    parser.add_argument("--center-mhz", type=float, default=200.0)
    parser.add_argument("--wait-seconds", type=int, default=43200)
    args = parser.parse_args()
    state_root = args.measurement_root / "control" / args.queue_id
    state_root.mkdir(parents=True, exist_ok=False)
    state_path = state_root / "hpc_resume_state.json"
    state = {"format": "T510_STAGE35_HPC_RESUME_V1", "queue_id": args.queue_id,
             "status": "waiting_for_slurm", "started_unix_ms": base.unix_ms(), "error": None}
    base.write_json_atomic(state_path, state)
    try:
        deadline = time.monotonic() + args.wait_seconds
        while time.monotonic() < deadline:
            try:
                if get(args.ready_url).strip() == b"READY":
                    break
            except (OSError, urllib.error.URLError):
                pass
            time.sleep(30)
        else:
            raise TimeoutError("Slurm analysis did not publish READY before deadline")
        state["status"] = "downloading_analysis"; base.write_json_atomic(state_path, state)
        destination = args.measurement_root / "analysis" / args.analysis_dir_name
        if destination.exists():
            raise RuntimeError(f"refusing to overwrite analysis destination {destination}")
        destination.mkdir(parents=True)
        base_url = args.analysis_base_url.rstrip("/") + "/" + args.analysis_dir_name
        manifest_path = destination / "analysis_manifest.json"
        manifest_sha_path = destination / "analysis_manifest.sha256"
        manifest_digest = download(base_url + "/analysis_manifest.json", manifest_path)
        download(base_url + "/analysis_manifest.sha256", manifest_sha_path)
        expected_manifest = manifest_sha_path.read_text().split()[0]
        if manifest_digest != expected_manifest:
            raise RuntimeError("downloaded analysis manifest digest mismatch")
        manifest = json.loads(manifest_path.read_text())
        for row in manifest["files"]:
            relative = Path(row["path"])
            if relative.is_absolute() or ".." in relative.parts:
                raise RuntimeError(f"unsafe analysis manifest path: {relative}")
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            actual = download(base_url + "/" + relative.as_posix(), target)
            if target.stat().st_size != int(row["bytes"]) or actual != row["sha256"]:
                raise RuntimeError(f"downloaded analysis identity mismatch: {relative}")
        identity = verify_analysis(destination)
        state.update({"status": "starting_xcorr", "analysis_identity": identity})
        base.write_json_atomic(state_path, state)
        report = state_root / "report_config.json"
        report_config(args, destination, report)
        source = json.loads(args.source_analysis_config.read_text())
        command = [str(args.python), str(args.helper_dir / "t510_stage35_xcorr_explorer_queue.py"),
                   "--queue-id", args.queue_id + "-xcorr", "--center-mhz", str(args.center_mhz),
                   "--template", str(args.template), "--helper-dir", str(args.helper_dir),
                   "--sidecar", str(args.sidecar), "--replay-evidence", str(args.replay_evidence),
                   "--preflight-pcap", str(args.preflight_pcap), "--analysis-root", str(destination),
                   "--report-config", str(report), "--chrome", str(args.chrome),
                   "--chromedriver", str(args.chromedriver), "--app-root", str(args.app_root)]
        for scan in source["scans"]:
            command += ["--spec-scan", scan["label"], scan["path"]]
        result = subprocess.run(command, stdout=(state_root / "xcorr.stdout.log").open("xb"),
                                stderr=(state_root / "xcorr.stderr.log").open("xb"), check=False)
        if result.returncode:
            raise RuntimeError(f"XCORR explorer queue failed with {result.returncode}")
        state.update({"status": "completed", "finished_unix_ms": base.unix_ms(),
                      "analysis_root": str(destination), "url": "http://192.168.100.162:8035/"})
        base.write_json_atomic(state_path, state)
        return 0
    except Exception as error:
        state.update({"status": "failed", "finished_unix_ms": base.unix_ms(),
                      "error": {"message": f"{type(error).__name__}: {error}",
                                "traceback": traceback.format_exc()}})
        base.write_json_atomic(state_path, state)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
