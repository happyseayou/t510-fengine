#!/usr/bin/env python3
"""Render a Stage 34b-2 A/B/C power-timeline example from measured evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import statistics
from typing import Any

from PIL import Image, ImageDraw, ImageFont


RUNS = {
    (160, "A"): "01_160msps_r1_A",
    (160, "B"): "02_160msps_r1_B",
    (160, "C"): "03_160msps_r1_C",
    (320, "A"): "10_320msps_r1_A",
    (320, "B"): "11_320msps_r1_B",
    (320, "C"): "12_320msps_r1_C",
}
CONDITION_NAMES = {
    "A": "A：动态校准",
    "B": "B：训练后冻结",
    "C": "C：立即冻结",
}
COLORS = {160: "#2563eb", 320: "#dc2626"}
LIGHT_COLORS = {160: "#bfdbfe", 320: "#fecaca"}


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    path = Path(
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
        if bold
        else "/usr/share/fonts/opentype/noto/NotoSansCJK-Medium.ttc"
    )
    return ImageFont.truetype(str(path), size)


def moving_average(values: list[float], width: int) -> list[float]:
    return [
        statistics.fmean(values[max(0, index - width + 1) : index + 1])
        for index in range(len(values))
    ]


def load_series(root: Path, run_name: str, lane: int, rf_mhz: float) -> dict[str, Any]:
    run_dir = root / "runs" / run_name
    monitor = json.loads((run_dir / "monitor_raw.json").read_text())
    result = json.loads((run_dir / "result.json").read_text())
    target = next(
        row
        for row in monitor["targets"]
        if abs(float(row["actual_rf_mhz"]) - rf_mhz) < 1.0e-9
    )
    target_index = int(target["target_index"])
    samples = sorted(
        (
            int(row["second"]),
            float(row["sum_power"]) / int(row["sample_count"]),
        )
        for row in monitor["power_seconds"]
        if int(row["lane"]) == lane and int(row["target_index"]) == target_index
    )
    if len(samples) != 600:
        raise RuntimeError(f"{run_name} returned {len(samples)} seconds, expected 600")
    power = [value for _second, value in samples]
    mean = statistics.fmean(power)
    percent = [(value / mean - 1.0) * 100.0 for value in power]
    analysis = next(
        row
        for row in result["analysis"]["combinations"]
        if int(row["lane"]) == lane and abs(float(row["rf_mhz"]) - rf_mhz) < 1.0e-9
    )
    return {
        "run": run_name,
        "percent": percent,
        "smooth": moving_average(percent, 16),
        "slope": float(analysis["slope"]),
        "lag1": float(analysis["lag1_correlation"]),
        "mean_dbfs": float(analysis["mean_dbfs"]),
    }


def draw_panel(
    draw: ImageDraw.ImageDraw,
    bounds: tuple[int, int, int, int],
    *,
    rate: int,
    condition: str,
    data: dict[str, Any],
) -> None:
    left, top, right, bottom = bounds
    draw.rounded_rectangle(bounds, radius=15, fill="white", outline="#cbd5e1", width=2)
    draw.text(
        (left + 20, top + 14),
        f"{rate} MS/s · {CONDITION_NAMES[condition]}",
        fill=COLORS[rate],
        font=font(21, True),
    )
    draw.text(
        (right - 286, top + 18),
        f"斜率 {data['slope']:.3f}  |  lag-1 {data['lag1']:.3f}",
        fill="#475569",
        font=font(14),
    )
    pl, pt, pr, pb = left + 72, top + 66, right - 22, bottom - 48
    y_limit = 2.5
    for percent in (-2.5, 0.0, 2.5):
        y = round(pb - (percent + y_limit) / (2.0 * y_limit) * (pb - pt))
        draw.line((pl, y, pr, y), fill="#e2e8f0", width=1)
        label = f"{percent:+.1f}%" if percent else "0%"
        draw.text((left + 10, y - 10), label, fill="#64748b", font=font(12))
    for second in (0, 120, 240, 360, 480, 600):
        x = round(pl + second / 600.0 * (pr - pl))
        draw.line((x, pt, x, pb), fill="#f1f5f9", width=1)
        draw.text((x - 12, pb + 12), str(second), fill="#64748b", font=font(11))

    def map_y(value: float) -> int:
        clipped = min(max(value, -y_limit), y_limit)
        return round(pb - (clipped + y_limit) / (2.0 * y_limit) * (pb - pt))

    raw_points = [
        (round(pl + second / 599.0 * (pr - pl)), map_y(value))
        for second, value in enumerate(data["percent"])
    ]
    smooth_points = [
        (round(pl + second / 599.0 * (pr - pl)), map_y(value))
        for second, value in enumerate(data["smooth"])
    ]
    draw.line(raw_points, fill=LIGHT_COLORS[rate], width=1)
    draw.line(smooth_points, fill=COLORS[rate], width=4)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--evidence",
        type=Path,
        default=Path("build/receiver/latest/evidence/rfdc_calibration/34b2"),
    )
    parser.add_argument("--lane", type=int, default=0)
    parser.add_argument("--rf-mhz", type=float, default=703.75)
    args = parser.parse_args()
    evidence = args.evidence.resolve()
    measurements = {
        key: load_series(evidence, run_name, args.lane, args.rf_mhz)
        for key, run_name in RUNS.items()
    }

    image = Image.new("RGB", (1920, 1170), "#f8fafc")
    draw = ImageDraw.Draw(image)
    draw.text(
        (44, 24),
        f"Stage 34b-2 实际例子：ADC{args.lane}、{args.rf_mhz:g} MHz 的600秒功率起伏",
        fill="#0f172a",
        font=font(36, True),
    )
    draw.text(
        (46, 78),
        "第一轮A/B/C的真实数据；每个面板按自身600秒平均功率归一化。浅线=每秒功率，深线=16秒滑动平均。",
        fill="#334155",
        font=font(18),
    )
    draw.text(
        (46, 113),
        "理想独立白噪声的积分斜率约为 −0.5；深线仍有缓慢成片起伏，表示相邻时刻并不完全独立。",
        fill="#7c2d12",
        font=font(17, True),
    )

    margin_x, gap_x = 38, 18
    panel_width = (1920 - 2 * margin_x - 2 * gap_x) // 3
    panel_height, gap_y, first_top = 410, 20, 164
    for row, rate in enumerate((160, 320)):
        for column, condition in enumerate(("A", "B", "C")):
            left = margin_x + column * (panel_width + gap_x)
            top = first_top + row * (panel_height + gap_y)
            draw_panel(
                draw,
                (left, top, left + panel_width, top + panel_height),
                rate=rate,
                condition=condition,
                data=measurements[(rate, condition)],
            )

    draw.text(
        (45, 1033),
        "怎么看：如果训练冻结有效，B列深线应明显比A列更平、斜率更接近−0.5、lag-1更接近0；这里没有出现这种变化。",
        fill="#0f172a",
        font=font(20, True),
    )
    draw.text(
        (45, 1074),
        "这幅图只展示固定的 ADC0/703.75 MHz/第1轮；最终FAIL结论来自两种速率、3轮、8路×6个安全bin的全部统计。",
        fill="#475569",
        font=font(17),
    )
    output = evidence / "plots" / "adc0_703p75mhz_abc_power_timeline.png"
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, optimize=True)
    metadata = {
        "plot": str(output),
        "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "lane": args.lane,
        "rf_mhz": args.rf_mhz,
        "normalization": "each 600-second run mean",
        "rolling_average_seconds": 16,
        "runs": {f"{rate}_{condition}": value for (rate, condition), value in measurements.items()},
    }
    metadata_path = output.with_suffix(".json")
    metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"plot": str(output), "metadata": str(metadata_path), "sha256": metadata["sha256"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
