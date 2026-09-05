#!/usr/bin/env python3
"""Prepare indexed raw witnesses for the read-only Stage 35 explorer.

The authoritative PCAP files are never modified.  This creates mmap-friendly
IQ16 arrays plus compact FFT/correlation/envelope summaries so browser requests
do not repeatedly scan half-gigabyte captures.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import struct
from pathlib import Path
from typing import Any, Iterator

import numpy as np


DATA_ROOT = Path("/var/lib/t510/stage35")
TIME_SAMPLES = 16_000_000
TIME_PACKET_SAMPLES = 256
TIME_PACKETS = 62_500
NFFT = 65_536
MAX_LAG = 512
ADC_PAIRS = tuple((a, b) for a in range(8) for b in range(a + 1, 8))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json_new(path: Path, value: Any) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(path, flags, 0o640)
    try:
        payload = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
        os.write(fd, payload)
        os.fsync(fd)
    finally:
        os.close(fd)


def safe_source(value: str) -> Path:
    path = Path(value).resolve(strict=True)
    if DATA_ROOT not in path.parents:
        raise ValueError(f"raw witness is outside fixed data root: {path}")
    if not path.is_file():
        raise ValueError(f"raw witness is not a file: {path}")
    return path


def pcap_frames(path: Path) -> Iterator[bytes]:
    with path.open("rb") as stream:
        header = stream.read(24)
        if len(header) != 24 or header[:4] != b"\xd4\xc3\xb2\xa1":
            raise ValueError(f"{path} is not little-endian classic PCAP")
        while record := stream.read(16):
            if len(record) != 16:
                raise ValueError(f"{path} has a truncated PCAP record header")
            captured = struct.unpack_from("<I", record, 8)[0]
            frame = stream.read(captured)
            if len(frame) != captured:
                raise ValueError(f"{path} has a truncated PCAP frame")
            yield frame


def udp_payload(frame: bytes) -> tuple[int, bytes]:
    if len(frame) < 42 or frame[12:14] != b"\x08\x00":
        raise ValueError("raw witness contains a non-IPv4 Ethernet frame")
    ip = 14
    ihl = (frame[ip] & 0x0F) * 4
    if ihl < 20 or frame[ip + 9] != 17:
        raise ValueError("raw witness contains a non-UDP IPv4 frame")
    udp = ip + ihl
    dst = struct.unpack_from("!H", frame, udp + 2)[0]
    return dst, frame[udp + 8 :]


def header_identity(payload: bytes) -> dict[str, int]:
    if len(payload) != 8320:
        raise ValueError(f"unexpected T510 payload length {len(payload)}")
    words = struct.unpack_from("<16Q", payload)
    if words[0] >> 32 != 0x54353130:
        raise ValueError("invalid T510 payload magic")
    return {
        "stream_type": (words[1] >> 32) & 0xFFFF,
        "sample0": words[4],
        "frame_id": words[5],
        "seq_no": (words[6] >> 32) & 0xFFFF_FFFF,
        "chan0": words[6] & 0xFFFF_FFFF,
        "block_index": (words[9] >> 16) & 0xFFFF,
    }


def _time_summary(raw: np.memmap, output: Path) -> dict[str, Any]:
    if raw.shape != (TIME_SAMPLES, 8, 2):
        raise ValueError(f"TIME array shape is {raw.shape}, expected {(TIME_SAMPLES, 8, 2)}")
    envelope = np.asarray(raw).reshape(4000, 4000, 8, 2)
    envelope_min = envelope.min(axis=1).astype("<i2")
    envelope_max = envelope.max(axis=1).astype("<i2")
    power_1us = np.empty((50_000, 8), dtype="<f8")
    for start in range(0, 50_000, 1000):
        block = np.asarray(raw[start * 320 : (start + 1000) * 320], dtype=np.float64)
        block = block.reshape(1000, 320, 8, 2)
        power_1us[start : start + 1000] = np.mean(np.sum(block * block, axis=3), axis=1)

    window = np.hanning(NFFT).astype(np.float32)
    auto_spectrum = np.zeros((8, NFFT), dtype=np.float64)
    cross_spectrum = np.zeros((28, NFFT), dtype=np.complex128)
    fft_blocks = TIME_SAMPLES // NFFT
    for index in range(fft_blocks):
        block = np.asarray(raw[index * NFFT : (index + 1) * NFFT], dtype=np.float32)
        transformed = np.fft.fft((block[:, :, 0] + 1j * block[:, :, 1]).T * window, axis=1)
        auto_spectrum += np.abs(transformed) ** 2
        for pair_index, (left, right) in enumerate(ADC_PAIRS):
            cross_spectrum[pair_index] += transformed[left] * np.conj(transformed[right])
    auto_spectrum /= fft_blocks
    cross_spectrum /= fft_blocks
    autocorrelation = np.fft.ifft(auto_spectrum, axis=1).real
    crosscorrelation = np.fft.ifft(cross_spectrum, axis=1)
    lag_indices = np.concatenate((np.arange(NFFT - MAX_LAG, NFFT), np.arange(MAX_LAG + 1)))
    acf_lag = autocorrelation[:, lag_indices] / np.maximum(
        autocorrelation[:, :1], np.finfo(np.float64).tiny
    )
    xcorr_lag = np.empty((28, len(lag_indices)), dtype=np.complex128)
    for pair_index, (left, right) in enumerate(ADC_PAIRS):
        norm = np.sqrt(autocorrelation[left, 0] * autocorrelation[right, 0])
        xcorr_lag[pair_index] = crosscorrelation[pair_index, lag_indices] / max(
            float(norm), np.finfo(np.float64).tiny
        )
    shifted = np.fft.fftshift(auto_spectrum, axes=1).reshape(8, 4096, 16).mean(axis=2)
    fft_db_relative = 10.0 * np.log10(
        np.maximum(shifted, np.finfo(np.float64).tiny)
        / np.maximum(np.median(shifted, axis=1, keepdims=True), np.finfo(np.float64).tiny)
    )
    fft_frequency_hz = np.linspace(-160_000_000, 160_000_000, 4096, endpoint=False) + 19_531.25
    summary = output / "summary.npz"
    np.savez(
        summary,
        envelope_min=envelope_min,
        envelope_max=envelope_max,
        envelope_time_s=(np.arange(4000, dtype=np.float64) + 0.5) * 0.05 / 4000,
        power_1us=power_1us,
        fft_frequency_hz=fft_frequency_hz,
        fft_db_relative=fft_db_relative,
        lag_samples=np.arange(-MAX_LAG, MAX_LAG + 1, dtype=np.int32),
        raw_iq_acf=acf_lag,
        raw_complex_xcorr=xcorr_lag,
        pair_index=np.asarray(ADC_PAIRS, dtype=np.uint8),
    )
    return {
        "summary": str(summary),
        "fft_kind": "ordinary Hann-windowed block FFT average",
        "fft_blocks": fft_blocks,
        "fft_size": NFFT,
        "lag_range_samples": [-MAX_LAG, MAX_LAG],
        "power_proxy_bucket_us": 1,
    }


def prepare_time(label: str, source: Path, output_root: Path) -> dict[str, Any]:
    output = output_root / "time" / label
    output.mkdir(parents=True, exist_ok=False)
    identities: list[dict[str, int]] = []
    for frame in pcap_frames(source):
        _, payload = udp_payload(frame)
        identity = header_identity(payload)
        if identity["stream_type"] != 1:
            raise ValueError(f"{source} contains non-TIME data")
        identities.append(identity)
    if len(identities) != TIME_PACKETS:
        raise ValueError(f"{source} has {len(identities)} TIME packets, expected {TIME_PACKETS}")
    frames = sorted(identity["frame_id"] for identity in identities)
    if frames != list(range(frames[0], frames[0] + TIME_PACKETS)):
        raise ValueError(f"{source} TIME frame_id sequence is not continuous")
    first_frame = frames[0]
    raw_path = output / "iq16.npy"
    raw = np.lib.format.open_memmap(raw_path, mode="w+", dtype="<i2", shape=(TIME_SAMPLES, 8, 2))
    seen = np.zeros(TIME_PACKETS, dtype=bool)
    for frame in pcap_frames(source):
        _, payload = udp_payload(frame)
        identity = header_identity(payload)
        packet_index = identity["frame_id"] - first_frame
        if not 0 <= packet_index < TIME_PACKETS or seen[packet_index]:
            raise ValueError(f"{source} has duplicate/out-of-range TIME frame")
        values = np.frombuffer(payload, dtype="<i2", offset=128, count=4096).reshape(256, 8, 2)
        raw[packet_index * 256 : (packet_index + 1) * 256] = values
        seen[packet_index] = True
    raw.flush()
    if not np.all(seen):
        raise ValueError(f"{source} TIME witness is incomplete")
    detail = _time_summary(raw, output)
    del raw
    return {
        "label": label,
        "source": str(source),
        "source_bytes": source.stat().st_size,
        "source_sha256": sha256_file(source),
        "iq16_npy": str(raw_path),
        "iq16_npy_bytes": raw_path.stat().st_size,
        "samples": TIME_SAMPLES,
        "sample_rate_hz": 320_000_000,
        "first_frame_id": first_frame,
        **detail,
    }


def inspect_spec_pcap(source: Path) -> dict[str, Any]:
    """Describe strict cross-block alignment without materializing IQ arrays."""
    identities: list[dict[str, int]] = []
    for frame in pcap_frames(source):
        _, payload = udp_payload(frame)
        identity = header_identity(payload)
        if identity["stream_type"] != 0:
            raise ValueError(f"{source} contains non-SPEC data")
        identities.append(identity)
    by_block = {block: set() for block in range(16)}
    for value in identities:
        if value["block_index"] not in by_block:
            raise ValueError(f"{source} contains invalid SPEC block index")
        by_block[value["block_index"]].add(value["sample0"])
    counts = {len(values) for values in by_block.values()}
    if len(counts) != 1 or next(iter(counts), 0) == 0:
        raise ValueError(f"{source} does not contain balanced per-block SPEC records")
    sample0s = sorted(set.intersection(*(values for values in by_block.values())))
    continuous = bool(sample0s) and not any(
        right - left != 4096 for left, right in zip(sample0s, sample0s[1:])
    )
    return {
        "source": str(source), "source_bytes": source.stat().st_size,
        "source_sha256": sha256_file(source),
        "packets_per_block": next(iter(counts)),
        "per_block_sample0_min": [min(by_block[block]) for block in range(16)],
        "per_block_sample0_max": [max(by_block[block]) for block in range(16)],
        "shared_sample0_count": len(sample0s),
        "shared_sample0_start": sample0s[0] if sample0s else None,
        "shared_sample0_end": sample0s[-1] + 4096 if sample0s else None,
        "shared_sample0_continuous": continuous,
        "_shared_sample0_values": sample0s,
    }


def prepare_spec(label: str, source: Path, output_root: Path) -> dict[str, Any]:
    output = output_root / "spec" / label
    output.mkdir(parents=True, exist_ok=False)
    inspected = inspect_spec_pcap(source)
    sample0s = inspected.pop("_shared_sample0_values")
    if not sample0s:
        raise ValueError(f"{source} has no sample0 shared by all sixteen blocks")
    if not inspected["shared_sample0_continuous"]:
        raise ValueError(f"{source} SPEC sample0 sequence is not continuous")
    sample_index = {value: index for index, value in enumerate(sample0s)}
    raw_path = output / "iq16.npy"
    raw = np.lib.format.open_memmap(
        raw_path, mode="w+", dtype="<i2", shape=(len(sample0s), 8, 4096, 2)
    )
    seen = np.zeros((len(sample0s), 16), dtype=bool)
    for frame in pcap_frames(source):
        _, payload = udp_payload(frame)
        identity = header_identity(payload)
        if identity["sample0"] not in sample_index:
            continue
        time_index = sample_index[identity["sample0"]]
        block = identity["block_index"]
        if not 0 <= block < 16 or seen[time_index, block]:
            raise ValueError(f"{source} has duplicate/out-of-range SPEC block")
        values = np.frombuffer(payload, dtype="<i2", offset=128, count=4096).reshape(256, 8, 2)
        raw[time_index, :, block * 256 : (block + 1) * 256, :] = values.transpose(1, 0, 2)
        seen[time_index, block] = True
    raw.flush()
    if not np.all(seen):
        raise ValueError(f"{source} SPEC witness is incomplete")
    del raw
    return {
        "label": label,
        "source": str(source),
        "source_bytes": inspected["source_bytes"],
        "source_sha256": inspected["source_sha256"],
        "iq16_npy": str(raw_path),
        "iq16_npy_bytes": raw_path.stat().st_size,
        "spectra": len(sample0s),
        "source_packets_per_block": inspected["packets_per_block"],
        "selection": "strict common future sample0 interval across all sixteen SPEC blocks",
        "sample0_start": sample0s[0],
        "sample0_end": sample0s[-1] + 4096,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    args.output.mkdir(parents=True, exist_ok=False)
    records: dict[str, Any] = {
        "format": "T510_STAGE35_EXPLORER_RAW_INDEX_V1",
        "config": str(args.config.resolve()),
        "time": {},
        "spec": {},
    }
    for label, value in sorted(config.get("time_raw", {}).items()):
        records["time"][label] = prepare_time(label, safe_source(value), args.output)
    for label, value in sorted(config.get("spec_raw", {}).items()):
        records["spec"][label] = prepare_spec(label, safe_source(value), args.output)
    manifest = args.output / "raw_index_manifest.json"
    write_json_new(manifest, records)
    write_json_new(
        args.output / "raw_index_manifest.sha256",
        {"path": str(manifest), "sha256": sha256_file(manifest)},
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
