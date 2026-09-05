#!/usr/bin/env python3
"""Prepare only the raw products required by the simple Stage 35 explorer.

Existing signed TIME IQ arrays are referenced in place.  The only sizeable
new derived TIME product is a direct 4096-point Hann FFT time series.  One new
4096-spectrum SPEC witness is decoded once for random access in the browser.
All work is intended to run on the GB10 capture host.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import numpy as np

from t510_stage35_explorer_prepare import DATA_ROOT, prepare_spec


FFT_SIZE = 4096
TIME_SAMPLES = 16_000_000
TIME_FFT_FRAMES = TIME_SAMPLES // FFT_SIZE
TIME_TAIL_SAMPLES = TIME_SAMPLES % FFT_SIZE


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json_new(path: Path, value: Any) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(path, flags, 0o640)
    try:
        payload = (json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode()
        os.write(fd, payload)
        os.fsync(fd)
    finally:
        os.close(fd)


def fixed_file(value: str | Path) -> Path:
    path = Path(value).resolve(strict=True)
    if DATA_ROOT not in path.parents or not path.is_file():
        raise ValueError(f"input is outside the fixed Stage 35 data root: {path}")
    return path


def prepare_time_fft(label: str, record: dict[str, Any], output: Path) -> dict[str, Any]:
    raw_path = fixed_file(record["iq16_npy"])
    raw = np.load(raw_path, mmap_mode="r")
    expected = (TIME_SAMPLES, 8, 2)
    if raw.shape != expected or raw.dtype != np.dtype("<i2"):
        raise ValueError(f"{label} TIME IQ shape/dtype is {raw.shape}/{raw.dtype}, expected {expected}/int16")
    destination = output / "time_fft4096" / label
    destination.mkdir(parents=True, exist_ok=False)
    fft_path = destination / "hann_fft4096_complex64.npy"
    fft = np.lib.format.open_memmap(
        fft_path, mode="w+", dtype="<c8", shape=(TIME_FFT_FRAMES, 8, FFT_SIZE)
    )
    window = np.hanning(FFT_SIZE).astype(np.float32)
    divisor = float(np.sum(window, dtype=np.float64))
    batch_frames = 16
    for first in range(0, TIME_FFT_FRAMES, batch_frames):
        count = min(batch_frames, TIME_FFT_FRAMES - first)
        samples = np.asarray(
            raw[first * FFT_SIZE : (first + count) * FFT_SIZE], dtype=np.float32
        ).reshape(count, FFT_SIZE, 8, 2)
        complex_samples = samples[..., 0] + 1j * samples[..., 1]
        transformed = np.fft.fft(
            complex_samples.transpose(0, 2, 1) * window[None, None, :], axis=2
        ) / divisor
        fft[first : first + count] = transformed.astype(np.complex64)
    fft.flush()
    del fft, raw
    return {
        **record,
        "label": label,
        "fft4096_complex64_npy": str(fft_path),
        "fft4096_complex64_bytes": fft_path.stat().st_size,
        "fft4096_complex64_sha256": sha256_file(fft_path),
        "fft_size": FFT_SIZE,
        "fft_frames": TIME_FFT_FRAMES,
        "fft_frame_seconds": FFT_SIZE / 320_000_000,
        "fft_tail_samples_dropped": TIME_TAIL_SAMPLES,
        "fft_window": "Hann",
        "fft_normalization": "divide by sum(Hann window)",
        "fft_global_bin_order": "native complex DFT order; RF=center+signed_bin*0.078125 MHz",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--existing-raw-index", type=Path, required=True)
    parser.add_argument("--spec-pcap", type=Path, required=True)
    parser.add_argument("--spec-label", default="simple-4096")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    existing_path = fixed_file(args.existing_raw_index)
    existing = json.loads(existing_path.read_text(encoding="utf-8"))
    args.output.mkdir(parents=True, exist_ok=False)
    manifest: dict[str, Any] = {
        "format": "T510_STAGE35_SIMPLE_RAW_INDEX_V1",
        "existing_raw_index": str(existing_path),
        "existing_raw_index_sha256": sha256_file(existing_path),
        "time": {},
        "spec": {},
    }
    for label, record in sorted(existing.get("time", {}).items()):
        manifest["time"][label] = prepare_time_fft(label, record, args.output)
    spec_source = fixed_file(args.spec_pcap)
    spec_record = prepare_spec(
        args.spec_label, spec_source, args.output / "spec_index"
    )
    spec_record["iq16_npy_sha256"] = sha256_file(Path(spec_record["iq16_npy"]))
    manifest["spec"][args.spec_label] = spec_record
    manifest_path = args.output / "simple_raw_index_manifest.json"
    write_json_new(manifest_path, manifest)
    write_json_new(
        args.output / "simple_raw_index_manifest.sha256",
        {"path": str(manifest_path), "sha256": sha256_file(manifest_path)},
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
