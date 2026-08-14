#!/usr/bin/env python3
"""Plot Stage 34b-2 frequency correlation at the 160 MS/s sample rate."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics
from typing import Any

from PIL import Image, ImageDraw, ImageFont


FREQUENCIES_MHZ = (681.25, 703.75, 726.25, 751.25, 771.25, 792.5)
CONDITION_NAMES = {
    "A": "A：动态校准",
    "B": "B：训练后冻结",
    "C": "C：立即冻结",
}


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    path = Path(
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
        if bold
        else "/usr/share/fonts/opentype/noto/NotoSansCJK-Medium.ttc"
    )
    return ImageFont.truetype(str(path), size)


def moving_average(values: list[float], width: int = 16) -> list[float]:
    return [
        statistics.fmean(values[max(0, index - width + 1) : index + 1])
        for index in range(len(values))
    ]


def correlation(left: list[float], right: list[float]) -> float:
    left_mean = statistics.fmean(left)
    right_mean = statistics.fmean(right)
    a = [value - left_mean for value in left]
    b = [value - right_mean for value in right]
    denominator = math.sqrt(sum(value * value for value in a) * sum(value * value for value in b))
    return sum(x * y for x, y in zip(a, b)) / denominator if denominator else 0.0


def load_run(root: Path, run_name: str, lane: int) -> dict[str, Any]:
    run_dir = root / "runs" / run_name
    monitor = json.loads((run_dir / "monitor_raw.json").read_text())
    result = json.loads((run_dir / "result.json").read_text())
    target_rf = {
        int(row["target_index"]): float(row["actual_rf_mhz"])
        for row in monitor["targets"]
    }
    rows: dict[float, list[tuple[int, float]]] = {}
    for row in monitor["power_seconds"]:
        if int(row["lane"]) != lane:
            continue
        rf_mhz = target_rf[int(row["target_index"])]
        rows.setdefault(rf_mhz, []).append(
            (int(row["second"]), float(row["sum_power"]) / int(row["sample_count"]))
        )
    series = {
        rf_mhz: [value for _second, value in sorted(values)]
        for rf_mhz, values in rows.items()
    }
    if set(series) != set(FREQUENCIES_MHZ) or any(len(values) != 600 for values in series.values()):
        raise RuntimeError(f"{run_name} does not contain six complete 600-second series")
    analysis = {
        float(row["rf_mhz"]): row
        for row in result["analysis"]["combinations"]
        if int(row["lane"]) == lane
    }
    return {"series": series, "analysis": analysis}


def condition_matrix(root: Path, condition: str, lane: int) -> tuple[list[list[float]], dict[str, Any]]:
    paths = sorted((root / "runs").glob(f"*_160msps_r?_{condition}"))
    if len(paths) != 3:
        raise RuntimeError(f"160 MS/s condition {condition} has {len(paths)} runs, expected 3")
    matrices = []
    for path in paths:
        run = load_run(root, path.name, lane)
        smooth = {rf: moving_average(values) for rf, values in run["series"].items()}
        matrices.append(
            [
                [correlation(smooth[left], smooth[right]) for right in FREQUENCIES_MHZ]
                for left in FREQUENCIES_MHZ
            ]
        )
    combined = [
        [statistics.median(matrix[row][column] for matrix in matrices) for column in range(6)]
        for row in range(6)
    ]
    off_diagonal = [combined[row][column] for row in range(6) for column in range(row + 1, 6)]
    return combined, {
        "runs": [path.name for path in paths],
        "off_diagonal_median": statistics.median(off_diagonal),
        "off_diagonal_min": min(off_diagonal),
        "off_diagonal_max": max(off_diagonal),
    }


def draw_timeline(
    draw: ImageDraw.ImageDraw,
    bounds: tuple[int, int, int, int],
    *,
    rf_mhz: float,
    values: list[float],
    analysis: dict[str, Any],
) -> None:
    left, top, right, bottom = bounds
    draw.rounded_rectangle(bounds, 13, fill="white", outline="#cbd5e1", width=2)
    draw.text((left + 17, top + 12), f"{rf_mhz:g} MHz", fill="#2563eb", font=font(20, True))
    draw.text(
        (right - 250, top + 15),
        f"斜率 {float(analysis['slope']):.3f}  lag-1 {float(analysis['lag1_correlation']):.3f}",
        fill="#475569",
        font=font(12),
    )
    mean = statistics.fmean(values)
    percent = [(value / mean - 1.0) * 100.0 for value in values]
    smooth = moving_average(percent)
    pl, pt, pr, pb = left + 57, top + 52, right - 18, bottom - 36
    # 771.25 MHz contains a real, frequency-local intermittent excursion in
    # this run.  Give its smoothed trace enough range instead of silently
    # clipping it into an apparently flat rail; retain the common ±2.5% scale
    # for the other five examples.
    y_limit = 40.0 if abs(rf_mhz - 771.25) < 1.0e-9 else 2.5
    for level in (-y_limit, 0.0, y_limit):
        y = round(pb - (level + y_limit) / (2.0 * y_limit) * (pb - pt))
        draw.line((pl, y, pr, y), fill="#e2e8f0")
        label = f"{level:+.0f}%" if y_limit >= 10.0 else f"{level:+.1f}%"
        draw.text((left + 7, y - 8), label if level else "0%", fill="#64748b", font=font(10))
    for second in (0, 200, 400, 600):
        x = round(pl + second / 600.0 * (pr - pl))
        draw.line((x, pt, x, pb), fill="#f1f5f9")
        draw.text((x - 10, pb + 8), str(second), fill="#64748b", font=font(10))

    def map_y(value: float) -> int:
        value = min(max(value, -y_limit), y_limit)
        return round(pb - (value + y_limit) / (2.0 * y_limit) * (pb - pt))

    raw_points = [
        (round(pl + index / 599.0 * (pr - pl)), map_y(value))
        for index, value in enumerate(percent)
    ]
    smooth_points = [
        (round(pl + index / 599.0 * (pr - pl)), map_y(value))
        for index, value in enumerate(smooth)
    ]
    draw.line(raw_points, fill="#bfdbfe", width=1)
    draw.line(smooth_points, fill="#2563eb", width=3)


def heat_color(value: float) -> tuple[int, int, int]:
    value = min(max(float(value), -1.0), 1.0)
    white = (248, 250, 252)
    endpoint = (220, 38, 38) if value >= 0.0 else (37, 99, 235)
    weight = abs(value)
    return tuple(round(white[index] * (1.0 - weight) + endpoint[index] * weight) for index in range(3))


def draw_heatmap(
    draw: ImageDraw.ImageDraw,
    bounds: tuple[int, int, int, int],
    *,
    condition: str,
    matrix: list[list[float]],
    summary: dict[str, Any],
) -> None:
    left, top, right, bottom = bounds
    draw.rounded_rectangle(bounds, 13, fill="white", outline="#cbd5e1", width=2)
    draw.text((left + 20, top + 14), CONDITION_NAMES[condition], fill="#0f172a", font=font(21, True))
    draw.text(
        (left + 20, top + 49),
        f"非对角中值 {summary['off_diagonal_median']:+.2f}，范围 {summary['off_diagonal_min']:+.2f}～{summary['off_diagonal_max']:+.2f}",
        fill="#475569",
        font=font(13),
    )
    cell = 65
    pl, pt = left + 128, top + 103
    labels = [f"{value:g}" for value in FREQUENCIES_MHZ]
    for index, label in enumerate(labels):
        draw.text((pl + index * cell + 6, pt - 30), label, fill="#475569", font=font(10))
        draw.text((left + 37, pt + index * cell + 21), label, fill="#475569", font=font(10))
    for row in range(6):
        for column in range(6):
            value = matrix[row][column]
            x0, y0 = pl + column * cell, pt + row * cell
            draw.rectangle((x0, y0, x0 + cell, y0 + cell), fill=heat_color(value), outline="white")
            text_color = "white" if abs(value) >= 0.55 else "#0f172a"
            draw.text((x0 + 11, y0 + 19), f"{value:+.2f}", fill=text_color, font=font(11, True))
    draw.text((pl + 115, pt + 6 * cell + 19), "频率 / MHz", fill="#475569", font=font(13))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--evidence",
        type=Path,
        default=Path("build/receiver/latest/evidence/rfdc_calibration/34b2"),
    )
    parser.add_argument("--lane", type=int, default=0)
    args = parser.parse_args()
    root = args.evidence.resolve()
    baseline = load_run(root, "01_160msps_r1_A", args.lane)
    matrices = {}
    summaries = {}
    for condition in "ABC":
        matrices[condition], summaries[condition] = condition_matrix(root, condition, args.lane)

    image = Image.new("RGB", (1920, 1660), "#f8fafc")
    draw = ImageDraw.Draw(image)
    draw.text(
        (42, 22),
        f"160 MS/s：ADC{args.lane} 六个频点的时间起伏与频率相关性",
        fill="#0f172a",
        font=font(36, True),
    )
    draw.text(
        (44, 76),
        "上部：A条件第1轮的真实600秒时间线，浅线=每秒功率、深线=16秒平均；下部：A/B/C各3轮的16秒慢起伏相关系数中位。",
        fill="#334155",
        font=font(17),
    )
    draw.text(
        (44, 108),
        "相关系数：+1表示两个频点同涨同跌，−1表示一高一低，0表示没有稳定的线性同步关系。",
        fill="#7c2d12",
        font=font(16, True),
    )

    margin, gap = 34, 16
    width = (1920 - 2 * margin - 2 * gap) // 3
    height = 316
    for index, rf_mhz in enumerate(FREQUENCIES_MHZ):
        row, column = divmod(index, 3)
        left = margin + column * (width + gap)
        top = 148 + row * (height + gap)
        draw_timeline(
            draw,
            (left, top, left + width, top + height),
            rf_mhz=rf_mhz,
            values=baseline["series"][rf_mhz],
            analysis=baseline["analysis"][rf_mhz],
        )

    heat_top, heat_height = 820, 650
    for column, condition in enumerate("ABC"):
        left = margin + column * (width + gap)
        draw_heatmap(
            draw,
            (left, heat_top, left + width, heat_top + heat_height),
            condition=condition,
            matrix=matrices[condition],
            summary=summaries[condition],
        )
    draw.text(
        (45, 1496),
        "结果：存在部分频点对的明显同向或反向慢相关，但不是整个带宽所有频点共同起伏；训练冻结也没有消除这种结构。",
        fill="#0f172a",
        font=font(19, True),
    )
    draw.text(
        (45, 1534),
        "注意：这里只代表160 MS/s、ADC0和这6个预先固定的安全bin；不能外推成每一个频谱bin都具有相同相关性。",
        fill="#475569",
        font=font(16),
    )
    draw.text(
        (45, 1570),
        "色标：蓝色=负相关    白色≈无相关    红色=正相关",
        fill="#475569",
        font=font(15, True),
    )
    output = root / "plots" / "adc0_160msps_six_frequency_correlation.png"
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, optimize=True)
    metadata = {
        "plot": str(output),
        "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "sample_rate_msps": 160,
        "lane": args.lane,
        "frequencies_mhz": list(FREQUENCIES_MHZ),
        "timeline_run": "01_160msps_r1_A",
        "correlation_series": "16-second trailing averages",
        "correlation_aggregation": "element-wise median across three repeats",
        "matrices": matrices,
        "summaries": summaries,
    }
    metadata_path = output.with_suffix(".json")
    metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"plot": str(output), "metadata": str(metadata_path), "sha256": metadata["sha256"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
