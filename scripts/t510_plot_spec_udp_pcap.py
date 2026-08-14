#!/usr/bin/env python3
"""Reassemble current T510 SPEC UDP pcaps and plot all eight ADC lanes."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import statistics
import struct
from typing import Iterator

from PIL import Image, ImageDraw, ImageFont


MAGIC = 0x5435_3130
HEADER_BYTES = 128
STREAM_SPEC = 0
SPEC_PAYLOAD_BYTES = 8192
SPEC_NCHAN = 4096
SPEC_BLOCK_COUNT = 16
SPEC_BLOCK_CHANS = 256
SPEC_NINPUT = 8


def _pcap_endian(magic: bytes) -> str:
    if magic in (b"\xd4\xc3\xb2\xa1", b"\x4d\x3c\xb2\xa1"):
        return "<"
    if magic in (b"\xa1\xb2\xc3\xd4", b"\xa1\xb2\x3c\x4d"):
        return ">"
    raise ValueError(f"unsupported PCAP magic {magic.hex()}")


def iter_pcap_packets(path: Path) -> Iterator[bytes]:
    raw = path.read_bytes()
    if len(raw) < 24:
        raise ValueError(f"{path} is shorter than a PCAP global header")
    endian = _pcap_endian(raw[:4])
    network = struct.unpack_from(endian + "I", raw, 20)[0]
    if network != 1:
        raise ValueError(f"{path} has unsupported link type {network}; expected Ethernet")
    offset = 24
    while offset + 16 <= len(raw):
        _ts_sec, _ts_frac, included, _original = struct.unpack_from(
            endian + "IIII", raw, offset
        )
        offset += 16
        end = offset + included
        if end > len(raw):
            raise ValueError(f"{path} contains a truncated packet record")
        yield raw[offset:end]
        offset = end
    if offset != len(raw):
        raise ValueError(f"{path} has {len(raw) - offset} trailing bytes")


def ethernet_udp_payload(frame: bytes) -> tuple[int, bytes] | None:
    if len(frame) < 14:
        return None
    ether_type = struct.unpack_from("!H", frame, 12)[0]
    ip_offset = 14
    while ether_type in (0x8100, 0x88A8):
        if len(frame) < ip_offset + 4:
            return None
        ether_type = struct.unpack_from("!H", frame, ip_offset + 2)[0]
        ip_offset += 4
    if ether_type != 0x0800 or len(frame) < ip_offset + 20:
        return None
    version_ihl = frame[ip_offset]
    if version_ihl >> 4 != 4:
        return None
    ihl = (version_ihl & 0x0F) * 4
    if ihl < 20 or frame[ip_offset + 9] != 17:
        return None
    udp_offset = ip_offset + ihl
    if len(frame) < udp_offset + 8:
        return None
    dst_port = struct.unpack_from("!H", frame, udp_offset + 2)[0]
    udp_len = struct.unpack_from("!H", frame, udp_offset + 4)[0]
    if udp_len < 8:
        return None
    payload_end = min(len(frame), udp_offset + udp_len)
    return dst_port, frame[udp_offset + 8 : payload_end]


def parse_spec_header(payload: bytes) -> dict[str, int]:
    if len(payload) < HEADER_BYTES:
        raise ValueError("UDP payload is shorter than the T510 header")
    words = struct.unpack_from("<16Q", payload, 0)
    word0, word1 = words[0], words[1]
    word6, word7 = words[6], words[7]
    word8, word9, word10, word11 = words[8], words[9], words[10], words[11]
    header = {
        "magic": word0 >> 32,
        "version": (word0 >> 16) & 0xFFFF,
        "header_bytes": word0 & 0xFFFF,
        "board_id": (word1 >> 48) & 0xFFFF,
        "stream_type": (word1 >> 32) & 0xFFFF,
        "sample0": words[4],
        "frame_id": words[5],
        "seq_no": word6 >> 32,
        "chan0": word6 & 0xFFFF_FFFF,
        "chan_count": word7 >> 48,
        "time_count": (word7 >> 32) & 0xFFFF,
        "ninput": (word7 >> 16) & 0xFFFF,
        "payload_format": word7 & 0xFFFF,
        "payload_bytes": word8 & 0xFFFF_FFFF,
        "product_id": word9 >> 48,
        "nchan": (word9 >> 32) & 0xFFFF,
        "block_index": (word9 >> 16) & 0xFFFF,
        "block_count": word9 & 0xFFFF,
        "pfb_taps": word10 >> 48,
        "fft_shift": (word10 >> 32) & 0xFFFF,
        "spec_status_flags": word10 & 0xFFFF_FFFF,
        "spec_sample_rate_hz": word11 >> 32,
    }
    expected = {
        "magic": MAGIC,
        "stream_type": STREAM_SPEC,
        "header_bytes": HEADER_BYTES,
        "payload_bytes": SPEC_PAYLOAD_BYTES,
        "nchan": SPEC_NCHAN,
        "block_count": SPEC_BLOCK_COUNT,
        "chan_count": SPEC_BLOCK_CHANS,
        "time_count": 1,
        "ninput": SPEC_NINPUT,
        "payload_format": 0,
    }
    for key, value in expected.items():
        if header[key] != value:
            raise ValueError(f"unexpected SPEC {key}={header[key]}; expected {value}")
    if header["chan0"] != header["block_index"] * header["chan_count"]:
        raise ValueError("SPEC chan0 does not match block_index")
    if len(payload) != HEADER_BYTES + SPEC_PAYLOAD_BYTES:
        raise ValueError(
            f"unexpected SPEC UDP payload length {len(payload)}; "
            f"expected {HEADER_BYTES + SPEC_PAYLOAD_BYTES}"
        )
    return header


def collect_spectra(paths: list[Path]) -> dict[str, object]:
    power_sum = [[0.0] * SPEC_NCHAN for _ in range(SPEC_NINPUT)]
    bin_counts = [0] * SPEC_NCHAN
    block_packets = [0] * SPEC_BLOCK_COUNT
    packet_count = 0
    board_ids: set[int] = set()
    sample_rates: set[int] = set()
    pfb_taps: set[int] = set()
    sha256 = {}
    first_sample0 = None
    last_sample0 = None
    previous_by_block: list[dict[str, int] | None] = [None] * SPEC_BLOCK_COUNT
    continuity_checks = 0

    for path in paths:
        sha256[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        for frame in iter_pcap_packets(path):
            udp = ethernet_udp_payload(frame)
            if udp is None:
                continue
            dst_port, payload = udp
            if not 4308 <= dst_port <= 4323:
                continue
            header = parse_spec_header(payload)
            block = header["block_index"]
            if dst_port != 4308 + block:
                raise ValueError(
                    f"SPEC dst_port {dst_port} does not match block_index {block}"
                )
            previous = previous_by_block[block]
            if previous is not None:
                expected_sample_delta = 4096 * (320_000_000 // header["spec_sample_rate_hz"])
                deltas = {
                    "seq_no": (header["seq_no"] - previous["seq_no"]) & 0xFFFF_FFFF,
                    "frame_id": (header["frame_id"] - previous["frame_id"]) & 0xFFFF_FFFF_FFFF_FFFF,
                    "sample0": (header["sample0"] - previous["sample0"]) & 0xFFFF_FFFF_FFFF_FFFF,
                }
                expected = {
                    "seq_no": SPEC_BLOCK_COUNT,
                    "frame_id": SPEC_BLOCK_COUNT,
                    "sample0": expected_sample_delta,
                }
                if deltas != expected:
                    raise ValueError(
                        f"SPEC block {block} continuity mismatch: deltas={deltas} expected={expected}"
                    )
                continuity_checks += 1
            previous_by_block[block] = header
            body = payload[HEADER_BYTES : HEADER_BYTES + SPEC_PAYLOAD_BYTES]
            chan0 = header["chan0"]
            for pair_index, (i_sample, q_sample) in enumerate(
                struct.iter_unpack("<hh", body)
            ):
                chan_idx, lane = divmod(pair_index, SPEC_NINPUT)
                bin_index = chan0 + chan_idx
                power_sum[lane][bin_index] += i_sample * i_sample + q_sample * q_sample
            for bin_index in range(chan0, chan0 + SPEC_BLOCK_CHANS):
                bin_counts[bin_index] += 1
            block_packets[block] += 1
            packet_count += 1
            board_ids.add(header["board_id"])
            sample_rates.add(header["spec_sample_rate_hz"])
            pfb_taps.add(header["pfb_taps"])
            first_sample0 = (
                header["sample0"]
                if first_sample0 is None
                else min(first_sample0, header["sample0"])
            )
            last_sample0 = (
                header["sample0"]
                if last_sample0 is None
                else max(last_sample0, header["sample0"])
            )

    if block_packets != [block_packets[0]] * SPEC_BLOCK_COUNT or block_packets[0] == 0:
        raise ValueError(f"unbalanced or incomplete SPEC blocks: {block_packets}")
    if len(board_ids) != 1 or len(sample_rates) != 1 or len(pfb_taps) != 1:
        raise ValueError(
            f"capture geometry changed: board={board_ids}, rates={sample_rates}, taps={pfb_taps}"
        )
    power_db = []
    for lane in range(SPEC_NINPUT):
        power_db.append(
            [
                10.0 * math.log10(max(power_sum[lane][index] / bin_counts[index], 1.0))
                for index in range(SPEC_NCHAN)
            ]
        )
    return {
        "power_db": power_db,
        "packet_count": packet_count,
        "block_packets": block_packets,
        "board_id": next(iter(board_ids)),
        "sample_rate_hz": next(iter(sample_rates)),
        "pfb_taps": next(iter(pfb_taps)),
        "first_sample0": first_sample0,
        "last_sample0": last_sample0,
        "pcap_sha256": sha256,
        "continuity_checks": continuity_checks,
    }


def signed_bin(index: int, bins: int) -> int:
    return index if index < bins // 2 else index - bins


def rf_for_bin(center_mhz: float, sample_rate_hz: int, index: int) -> float:
    return center_mhz + signed_bin(index, SPEC_NCHAN) * sample_rate_hz / SPEC_NCHAN / 1.0e6


def sorted_bin_indices() -> list[int]:
    return list(range(SPEC_NCHAN // 2, SPEC_NCHAN)) + list(range(SPEC_NCHAN // 2))


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = round((len(ordered) - 1) * fraction)
    return ordered[index]


def lane_summaries(
    power_db: list[list[float]], center_mhz: float, sample_rate_hz: int
) -> list[dict[str, float | int]]:
    bin_width_mhz = sample_rate_hz / SPEC_NCHAN / 1.0e6
    spur_bin = round((960.0 - center_mhz) / bin_width_mhz) % SPEC_NCHAN
    summaries = []
    for lane, values in enumerate(power_db):
        noise_values = [
            value
            for index, value in enumerate(values)
            if min((index - spur_bin) % SPEC_NCHAN, (spur_bin - index) % SPEC_NCHAN) > 4
        ]
        noise = statistics.median(noise_values)
        peak_bin = max(range(SPEC_NCHAN), key=values.__getitem__)
        non_960_bins = [
            index
            for index in range(SPEC_NCHAN)
            if min((index - spur_bin) % SPEC_NCHAN, (spur_bin - index) % SPEC_NCHAN) > 6
        ]
        non_960_peak_bin = max(non_960_bins, key=values.__getitem__)
        summaries.append(
            {
                "adc": lane,
                "noise_median_db_code": noise,
                "noise_p05_db_code": percentile(noise_values, 0.05),
                "noise_p95_db_code": percentile(noise_values, 0.95),
                "spur_960_bin": spur_bin,
                "spur_960_mapped_rf_mhz": rf_for_bin(
                    center_mhz, sample_rate_hz, spur_bin
                ),
                "spur_960_power_db_code": values[spur_bin],
                "spur_960_above_noise_db": values[spur_bin] - noise,
                "strongest_bin": peak_bin,
                "strongest_rf_mhz": rf_for_bin(center_mhz, sample_rate_hz, peak_bin),
                "strongest_power_db_code": values[peak_bin],
                "strongest_above_noise_db": values[peak_bin] - noise,
                "strongest_non_960_bin": non_960_peak_bin,
                "strongest_non_960_rf_mhz": rf_for_bin(
                    center_mhz, sample_rate_hz, non_960_peak_bin
                ),
                "strongest_non_960_power_db_code": values[non_960_peak_bin],
                "strongest_non_960_above_noise_db": values[non_960_peak_bin] - noise,
            }
        )
    return summaries


def _font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    path = Path("/usr/share/fonts/truetype/dejavu") / name
    if path.exists():
        return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def draw_plot(
    output: Path,
    power_db: list[list[float]],
    summaries: list[dict[str, float | int]],
    center_mhz: float,
    sample_rate_hz: int,
    packet_count: int,
) -> None:
    width, height = 2400, 1840
    image = Image.new("RGB", (width, height), "#f8fafc")
    draw = ImageDraw.Draw(image)
    title_font = _font(36, True)
    subtitle_font = _font(23)
    panel_font = _font(22, True)
    tick_font = _font(17)
    note_font = _font(17)
    draw.text(
        (80, 34),
        "T510 open-input ADC spectra from raw SPEC UDP",
        fill="#0f172a",
        font=title_font,
    )
    draw.text(
        (80, 82),
        f"160 MS/s complex band, center {center_mhz:.0f} MHz, 32 packets/subband, "
        f"{packet_count} UDP packets total; linear-power average",
        fill="#334155",
        font=subtitle_font,
    )
    draw.text(
        (80, 116),
        "Shared y-axis: dB above each ADC lane's median noise. Orange line marks 960 MHz.",
        fill="#334155",
        font=subtitle_font,
    )

    order = sorted_bin_indices()
    frequencies = [rf_for_bin(center_mhz, sample_rate_hz, index) for index in order]
    relative = []
    for lane, values in enumerate(power_db):
        noise = float(summaries[lane]["noise_median_db_code"])
        relative.append([values[index] - noise for index in order])
    global_max = max(max(values) for values in relative)
    y_min = -8.0
    y_max = max(20.0, math.ceil((global_max + 3.0) / 5.0) * 5.0)
    columns, rows = 2, 4
    outer_left, outer_right = 70, 70
    outer_top, outer_bottom = 165, 70
    gap_x, gap_y = 46, 34
    panel_w = (width - outer_left - outer_right - gap_x) // columns
    panel_h = (height - outer_top - outer_bottom - gap_y * (rows - 1)) // rows
    x_min, x_max = frequencies[0], frequencies[-1]
    x_ticks = list(range(880, 1041, 20))
    y_ticks = list(range(-5, int(y_max) + 1, 5))

    for lane in range(SPEC_NINPUT):
        row, column = divmod(lane, columns)
        left = outer_left + column * (panel_w + gap_x)
        top = outer_top + row * (panel_h + gap_y)
        right = left + panel_w
        bottom = top + panel_h
        plot_left, plot_top = left + 68, top + 44
        plot_right, plot_bottom = right - 18, bottom - 48
        draw.rounded_rectangle(
            (left, top, right, bottom), radius=10, fill="white", outline="#cbd5e1", width=2
        )
        summary = summaries[lane]
        draw.text(
            (left + 18, top + 10),
            f"ADC{lane}   960 MHz: {summary['spur_960_above_noise_db']:+.1f} dB   "
            f"noise: {summary['noise_median_db_code']:.1f} dB code",
            fill="#0f172a",
            font=panel_font,
        )

        def x_pixel(freq: float) -> int:
            return round(plot_left + (freq - x_min) * (plot_right - plot_left) / (x_max - x_min))

        def y_pixel(value: float) -> int:
            clipped = min(max(value, y_min), y_max)
            return round(
                plot_bottom - (clipped - y_min) * (plot_bottom - plot_top) / (y_max - y_min)
            )

        for tick in x_ticks:
            x = x_pixel(float(tick))
            draw.line((x, plot_top, x, plot_bottom), fill="#e2e8f0", width=1)
            label = str(tick)
            bbox = draw.textbbox((0, 0), label, font=tick_font)
            draw.text(
                (x - (bbox[2] - bbox[0]) / 2, plot_bottom + 7),
                label,
                fill="#475569",
                font=tick_font,
            )
        for tick in y_ticks:
            y = y_pixel(float(tick))
            draw.line((plot_left, y, plot_right, y), fill="#e2e8f0", width=1)
            label = str(tick)
            bbox = draw.textbbox((0, 0), label, font=tick_font)
            draw.text(
                (plot_left - 10 - (bbox[2] - bbox[0]), y - (bbox[3] - bbox[1]) / 2),
                label,
                fill="#475569",
                font=tick_font,
            )
        draw.line((plot_left, y_pixel(0.0), plot_right, y_pixel(0.0)), fill="#64748b", width=2)

        pixels: list[list[float]] = [[] for _ in range(plot_right - plot_left + 1)]
        for freq, value in zip(frequencies, relative[lane]):
            pixels[x_pixel(freq) - plot_left].append(value)
        previous = None
        for pixel_offset, values in enumerate(pixels):
            if not values:
                continue
            x = plot_left + pixel_offset
            low, high = min(values), max(values)
            draw.line((x, y_pixel(low), x, y_pixel(high)), fill="#93c5fd", width=1)
            point = (x, y_pixel(high))
            if previous is not None:
                draw.line((previous[0], previous[1], point[0], point[1]), fill="#2563eb", width=2)
            previous = point

        spur_x = x_pixel(960.0)
        for dash_top in range(plot_top, plot_bottom, 12):
            draw.line(
                (spur_x, dash_top, spur_x, min(dash_top + 7, plot_bottom)),
                fill="#f97316",
                width=2,
            )
        spur_y = y_pixel(float(summary["spur_960_above_noise_db"]))
        draw.ellipse((spur_x - 5, spur_y - 5, spur_x + 5, spur_y + 5), fill="#ea580c")
        draw.text((spur_x + 8, plot_top + 5), "960", fill="#c2410c", font=note_font)
        if row == rows - 1:
            label = "RF frequency (MHz)"
            bbox = draw.textbbox((0, 0), label, font=note_font)
            draw.text(
                ((plot_left + plot_right - (bbox[2] - bbox[0])) / 2, bottom - 22),
                label,
                fill="#334155",
                font=note_font,
            )

    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, format="PNG", optimize=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pcap", nargs="+", type=Path, help="PCAP files or directories")
    parser.add_argument("--center-mhz", type=float, required=True)
    parser.add_argument("--png", type=Path, required=True)
    parser.add_argument("--json", type=Path, required=True)
    parser.add_argument("--csv", type=Path, required=True)
    args = parser.parse_args()
    paths = []
    for item in args.pcap:
        if item.is_dir():
            paths.extend(sorted(item.glob("*.pcap")))
        else:
            paths.append(item)
    if not paths:
        parser.error("no PCAP files found")

    capture = collect_spectra(paths)
    power_db = capture.pop("power_db")
    assert isinstance(power_db, list)
    sample_rate_hz = int(capture["sample_rate_hz"])
    summaries = lane_summaries(power_db, args.center_mhz, sample_rate_hz)
    draw_plot(
        args.png,
        power_db,
        summaries,
        args.center_mhz,
        sample_rate_hz,
        int(capture["packet_count"]),
    )

    order = sorted_bin_indices()
    args.csv.parent.mkdir(parents=True, exist_ok=True)
    with args.csv.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            ["rf_mhz"]
            + [f"adc{lane}_power_db_code" for lane in range(SPEC_NINPUT)]
            + [f"adc{lane}_above_median_db" for lane in range(SPEC_NINPUT)]
        )
        for index in order:
            row = [rf_for_bin(args.center_mhz, sample_rate_hz, index)]
            row.extend(power_db[lane][index] for lane in range(SPEC_NINPUT))
            row.extend(
                power_db[lane][index] - float(summaries[lane]["noise_median_db_code"])
                for lane in range(SPEC_NINPUT)
            )
            writer.writerow(row)

    result = {
        "classification": "T510_ADC_OPEN_INPUT_RAW_SPEC_UDP_SPECTRUM",
        "release": "latest",
        "center_mhz": args.center_mhz,
        "sample_rate_hz": sample_rate_hz,
        "rf_start_mhz": args.center_mhz - sample_rate_hz / 2.0e6,
        "rf_stop_mhz": args.center_mhz + sample_rate_hz / 2.0e6,
        "bin_count": SPEC_NCHAN,
        "bin_width_hz": sample_rate_hz / SPEC_NCHAN,
        "averaging": "linear IQ power across packets independently for each 256-bin SPEC block",
        "input_condition": "ADC0..ADC7 and DAC0..DAC7 physically open/unconnected (user-confirmed)",
        "capture": capture,
        "lanes": summaries,
        "artifacts": {
            "png": str(args.png),
            "png_sha256": hashlib.sha256(args.png.read_bytes()).hexdigest(),
            "csv": str(args.csv),
            "csv_sha256": hashlib.sha256(args.csv.read_bytes()).hexdigest(),
        },
    }
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
