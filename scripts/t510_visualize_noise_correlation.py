#!/usr/bin/env python3
"""Visualize Stage 34a temporal and cross-channel noise correlation evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics
from typing import Any

from PIL import Image, ImageDraw, ImageFont


TAUS = (1, 2, 4, 8, 16, 32, 64, 128)
LAGS = (1, 2, 4, 8, 16, 32, 64)
CLEAN_RF_MHZ = (980.0, 1000.0, 1040.0, 1060.0, 1080.0)
ALL_RF_MHZ = (960.0, *CLEAN_RF_MHZ)
COLORS = {160: "#2563eb", 320: "#dc2626"}


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    path = Path(
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
        if bold
        else "/usr/share/fonts/opentype/noto/NotoSansCJK-Medium.ttc"
    )
    return ImageFont.truetype(str(path), size)


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[round((len(ordered) - 1) * fraction)]


def correlation(left: list[float], right: list[float]) -> float:
    left_mean = statistics.fmean(left)
    right_mean = statistics.fmean(right)
    left_centered = [value - left_mean for value in left]
    right_centered = [value - right_mean for value in right]
    denominator = math.sqrt(
        sum(value * value for value in left_centered)
        * sum(value * value for value in right_centered)
    )
    if denominator == 0.0:
        return 0.0
    return sum(a * b for a, b in zip(left_centered, right_centered)) / denominator


def nonoverlapping_means(values: list[float], width: int) -> list[float]:
    return [
        statistics.fmean(values[offset : offset + width])
        for offset in range(0, len(values) - width + 1, width)
    ]


def fractional_stddev(values: list[float], width: int) -> float:
    groups = nonoverlapping_means(values, width)
    return statistics.stdev(groups) / statistics.fmean(values)


def regression_slope(curve: list[tuple[int, float]], maximum_tau: int) -> float:
    points = [
        (math.log10(tau), math.log10(value))
        for tau, value in curve
        if tau <= maximum_tau
    ]
    x_mean = statistics.fmean(x for x, _ in points)
    y_mean = statistics.fmean(y for _, y in points)
    return sum((x - x_mean) * (y - y_mean) for x, y in points) / sum(
        (x - x_mean) ** 2 for x, _ in points
    )


def coherence(rows: list[dict[str, Any]]) -> float:
    cross_re = sum(float(row["sum_cross_re"]) for row in rows)
    cross_im = sum(float(row["sum_cross_im"]) for row in rows)
    power_a = sum(float(row["sum_power_a"]) for row in rows)
    power_b = sum(float(row["sum_power_b"]) for row in rows)
    denominator = math.sqrt(power_a * power_b)
    return math.hypot(cross_re, cross_im) / denominator if denominator else 0.0


def load_measurement(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text())
    targets = {
        int(row["target_index"]): float(row["actual_rf_mhz"])
        for row in raw["targets"]
    }
    series: dict[tuple[int, float], list[tuple[int, float]]] = {}
    for row in raw["power_seconds"]:
        key = (int(row["lane"]), targets[int(row["target_index"])])
        value = float(row["sum_power"]) / int(row["sample_count"])
        series.setdefault(key, []).append((int(row["second"]), value))
    ordered_series = {
        key: [value for _second, value in sorted(rows)]
        for key, rows in series.items()
    }
    cross_rows: dict[float, list[dict[str, Any]]] = {}
    for row in raw["cross_seconds"]:
        cross_rows.setdefault(targets[int(row["target_index"])], []).append(row)

    clean = [
        values
        for (_lane, rf_mhz), values in ordered_series.items()
        if rf_mhz in CLEAN_RF_MHZ
    ]
    integration = {}
    for tau in TAUS:
        values = [fractional_stddev(row, tau) for row in clean]
        integration[tau] = {
            "median": statistics.median(values),
            "p10": percentile(values, 0.1),
            "p90": percentile(values, 0.9),
        }
    autocorrelation = {}
    for lag in LAGS:
        values = [correlation(row[lag:], row[:-lag]) for row in clean]
        autocorrelation[lag] = {
            "median": statistics.median(values),
            "p10": percentile(values, 0.1),
            "p90": percentile(values, 0.9),
        }
    individual_curves = [
        [(tau, fractional_stddev(row, tau)) for tau in TAUS] for row in clean
    ]
    slope_16 = [regression_slope(curve, 16) for curve in individual_curves]
    slope_128 = [regression_slope(curve, 128) for curve in individual_curves]
    base = integration[1]["median"]
    improvement = {
        tau: {
            "measured": base / integration[tau]["median"],
            "ideal": math.sqrt(tau),
        }
        for tau in (32, 128)
    }
    return {
        "series": ordered_series,
        "integration": integration,
        "autocorrelation": autocorrelation,
        "coherence": {
            rf_mhz: coherence(cross_rows[rf_mhz]) for rf_mhz in ALL_RF_MHZ
        },
        "median_slope_1_16_seconds": statistics.median(slope_16),
        "median_slope_1_128_seconds": statistics.median(slope_128),
        "improvement": improvement,
    }


def dashed_line(
    draw: ImageDraw.ImageDraw,
    points: tuple[int, int, int, int],
    *,
    fill: str,
    width: int = 2,
    dash: int = 10,
) -> None:
    x0, y0, x1, y1 = points
    distance = math.hypot(x1 - x0, y1 - y0)
    if distance == 0:
        return
    steps = max(1, round(distance / dash))
    for index in range(0, steps, 2):
        left = index / steps
        right = min((index + 1) / steps, 1.0)
        draw.line(
            (
                round(x0 + left * (x1 - x0)),
                round(y0 + left * (y1 - y0)),
                round(x0 + right * (x1 - x0)),
                round(y0 + right * (y1 - y0)),
            ),
            fill=fill,
            width=width,
        )


def panel(
    draw: ImageDraw.ImageDraw,
    bounds: tuple[int, int, int, int],
    title: str,
    subtitle: str,
) -> tuple[int, int, int, int]:
    left, top, right, bottom = bounds
    draw.rounded_rectangle(bounds, 14, fill="white", outline="#cbd5e1", width=2)
    draw.text((left + 22, top + 16), title, fill="#0f172a", font=font(25, True))
    draw.text((left + 22, top + 56), subtitle, fill="#475569", font=font(16))
    return left + 92, top + 108, right - 34, bottom - 70


def draw_integration(
    draw: ImageDraw.ImageDraw,
    bounds: tuple[int, int, int, int],
    measurements: dict[int, dict[str, Any]],
) -> None:
    pl, pt, pr, pb = panel(
        draw,
        bounds,
        "1. 积分越久，实际噪声下降得比理想情况慢",
        "实线/色带：40个干净 ADC×bin 的中值及10%～90%；虚线：从1秒点延伸的 1/√t",
    )
    y_min, y_max = 1.0e-4, 2.0e-2
    for power in (-4, -3, -2):
        value = 10.0**power
        y = round(pb - (math.log10(value) - math.log10(y_min)) / (math.log10(y_max) - math.log10(y_min)) * (pb - pt))
        draw.line((pl, y, pr, y), fill="#e2e8f0")
        draw.text((pl - 78, y - 10), f"10^{power}", fill="#64748b", font=font(14))
    for tau in TAUS:
        x = round(pl + math.log2(tau) / 7.0 * (pr - pl))
        draw.line((x, pt, x, pb), fill="#f1f5f9")
        draw.text((x - 12, pb + 14), str(tau), fill="#64748b", font=font(14))
    map_y = lambda value: round(
        pb
        - (math.log10(value) - math.log10(y_min))
        / (math.log10(y_max) - math.log10(y_min))
        * (pb - pt)
    )
    plotted: dict[int, tuple[list[tuple[int, int]], list[tuple[int, int]], list[tuple[int, int]], list[tuple[int, int]]]] = {}
    for rate in (160, 320):
        data = measurements[rate]
        band_upper = []
        band_lower = []
        points = []
        for tau in TAUS:
            x = round(pl + math.log2(tau) / 7.0 * (pr - pl))
            row = data["integration"][tau]
            band_upper.append((x, map_y(row["p90"])))
            band_lower.append((x, map_y(row["p10"])))
            points.append((x, map_y(row["median"])))
        ideal = [
            (
                round(pl + math.log2(tau) / 7.0 * (pr - pl)),
                map_y(data["integration"][1]["median"] / math.sqrt(tau)),
            )
            for tau in TAUS
        ]
        plotted[rate] = (band_upper, band_lower, points, ideal)
    for rate in (160, 320):
        band_upper, band_lower, _points, _ideal = plotted[rate]
        shade = "#dbeafe" if rate == 160 else "#fee2e2"
        draw.polygon(band_upper + list(reversed(band_lower)), fill=shade)
    for rate in (160, 320):
        _band_upper, _band_lower, points, ideal = plotted[rate]
        draw.line(points, fill=COLORS[rate], width=5)
        for left, right in zip(ideal, ideal[1:]):
            dashed_line(draw, (*left, *right), fill=COLORS[rate], width=2, dash=8)
    draw.text((pl, pt + 8), "160 MS/s", fill=COLORS[160], font=font(16, True))
    draw.text((pl + 130, pt + 8), "320 MS/s", fill=COLORS[320], font=font(16, True))
    draw.text((pr - 415, pt + 8), "虚线斜率 = −0.5", fill="#334155", font=font(15))
    draw.text(
        (pr - 415, pt + 38),
        f"32秒实测改善：160={measurements[160]['improvement'][32]['measured']:.2f}×，320={measurements[320]['improvement'][32]['measured']:.2f}×",
        fill="#334155",
        font=font(14),
    )
    draw.text((pr - 415, pt + 64), "理想值：5.66×", fill="#334155", font=font(14))
    draw.text((pl, pb + 40), "积分时间 / 秒（对数轴）", fill="#334155", font=font(15))


def draw_autocorrelation(
    draw: ImageDraw.ImageDraw,
    bounds: tuple[int, int, int, int],
    measurements: dict[int, dict[str, Any]],
) -> None:
    pl, pt, pr, pb = panel(
        draw,
        bounds,
        "2. 同一个低噪声 bin 的功率在相邻秒之间有关联",
        "白噪声在非零延迟应接近0；正值表示这一秒偏高时，下一些秒也倾向偏高",
    )
    y_min, y_max = -0.15, 0.7
    map_y = lambda value: round(pb - (value - y_min) / (y_max - y_min) * (pb - pt))
    zero_y = map_y(0.0)
    dashed_line(draw, (pl, zero_y, pr, zero_y), fill="#64748b", width=2, dash=9)
    draw.text((pr - 175, zero_y + 8), "理想白噪声 ≈ 0", fill="#64748b", font=font(14))
    for level in (0.0, 0.2, 0.4, 0.6):
        y = map_y(level)
        draw.line((pl, y, pr, y), fill="#e2e8f0")
        draw.text((pl - 55, y - 9), f"{level:.1f}", fill="#64748b", font=font(14))
    for lag in LAGS:
        x = round(pl + math.log2(lag) / 6.0 * (pr - pl))
        draw.text((x - 10, pb + 14), str(lag), fill="#64748b", font=font(14))
    plotted_bands: dict[int, tuple[list[tuple[int, int]], list[tuple[int, int]], list[tuple[int, int]]]] = {}
    for rate in (160, 320):
        upper = []
        lower = []
        points = []
        for lag in LAGS:
            x = round(pl + math.log2(lag) / 6.0 * (pr - pl))
            row = measurements[rate]["autocorrelation"][lag]
            upper.append((x, map_y(row["p90"])))
            lower.append((x, map_y(row["p10"])))
            points.append((x, map_y(row["median"])))
        plotted_bands[rate] = (upper, lower, points)
    for rate in (160, 320):
        upper, lower, _points = plotted_bands[rate]
        draw.polygon(
            upper + list(reversed(lower)),
            fill="#dbeafe" if rate == 160 else "#fee2e2",
        )
    for rate in (160, 320):
        _upper, _lower, points = plotted_bands[rate]
        draw.line(points, fill=COLORS[rate], width=5)
        for x, y in points:
            draw.ellipse((x - 5, y - 5, x + 5, y + 5), fill=COLORS[rate])
    draw.text((pl, pt + 8), "160 MS/s", fill=COLORS[160], font=font(16, True))
    draw.text((pl + 130, pt + 8), "320 MS/s", fill=COLORS[320], font=font(16, True))
    draw.text(
        (pr - 345, pt + 8),
        f"相邻秒：{measurements[160]['autocorrelation'][1]['median']:.2f} / {measurements[320]['autocorrelation'][1]['median']:.2f}",
        fill="#334155",
        font=font(14),
    )
    draw.text((pl, pb + 40), "时间延迟 / 秒（对数轴）", fill="#334155", font=font(15))


def draw_coherence(
    draw: ImageDraw.ImageDraw,
    bounds: tuple[int, int, int, int],
    measurements: dict[int, dict[str, Any]],
) -> None:
    pl, pt, pr, pb = panel(
        draw,
        bounds,
        "3. ADC0/ADC2 通道间相干度：960 MHz 与低噪声点不同",
        "相干度0=没有稳定共同复信号，1=完全相干；960 MHz 是已知坏频点，仅作对照",
    )
    for level in (0.0, 0.25, 0.5, 0.75, 1.0):
        y = round(pb - level * (pb - pt))
        draw.line((pl, y, pr, y), fill="#e2e8f0")
        draw.text((pl - 58, y - 9), f"{level:.2f}", fill="#64748b", font=font(13))
    group_width = (pr - pl) / len(ALL_RF_MHZ)
    for index, rf_mhz in enumerate(ALL_RF_MHZ):
        center = pl + (index + 0.5) * group_width
        for rate, shift in ((160, -18), (320, 18)):
            value = measurements[rate]["coherence"][rf_mhz]
            x0 = round(center + shift - 15)
            x1 = round(center + shift + 15)
            y = round(pb - value * (pb - pt))
            draw.rectangle((x0, y, x1, pb), fill=COLORS[rate])
            draw.text((x0 - 8, max(pt, y - 26)), f"{value:.2f}", fill=COLORS[rate], font=font(12, True))
        draw.text((round(center) - 28, pb + 14), f"{rf_mhz:.0f}", fill="#7c2d12" if rf_mhz == 960.0 else "#475569", font=font(14, rf_mhz == 960.0))
    draw.text((pl, pt + 8), "160 MS/s", fill=COLORS[160], font=font(16, True))
    draw.text((pl + 130, pt + 8), "320 MS/s", fill=COLORS[320], font=font(16, True))
    draw.text((pl, pb + 42), "物理 RF / MHz", fill="#334155", font=font(15))


def moving_average(values: list[float], width: int) -> list[float]:
    return [
        statistics.fmean(values[max(0, index - width + 1) : index + 1])
        for index in range(len(values))
    ]


def draw_timeline(
    draw: ImageDraw.ImageDraw,
    bounds: tuple[int, int, int, int],
    measurements: dict[int, dict[str, Any]],
) -> None:
    left, top, right, bottom = bounds
    pl, pt, pr, pb = panel(
        draw,
        bounds,
        "4. 实际例子：ADC0、1000 MHz 的600秒功率起伏",
        "浅线=每秒功率；深线=16秒滑动平均。若每秒完全独立，深线会更快变平",
    )
    half = (pb - pt - 34) // 2
    for rate_index, rate in enumerate((160, 320)):
        axis_top = pt + rate_index * (half + 34)
        axis_bottom = axis_top + half
        values = measurements[rate]["series"][(0, 1000.0)]
        mean = statistics.fmean(values)
        percent = [(value / mean - 1.0) * 100.0 for value in values]
        smooth = moving_average(percent, 16)
        y_limit = 2.5
        zero_y = (axis_top + axis_bottom) // 2
        draw.line((pl, zero_y, pr, zero_y), fill="#cbd5e1")
        draw.text((pl + 6, axis_top + 5), f"{rate} MS/s", fill=COLORS[rate], font=font(15, True))
        draw.text((pl - 72, axis_top), "+2.5%", fill="#64748b", font=font(12))
        draw.text((pl - 72, axis_bottom - 15), "−2.5%", fill="#64748b", font=font(12))
        map_y = lambda value: round(
            axis_bottom
            - (min(max(value, -y_limit), y_limit) + y_limit)
            / (2.0 * y_limit)
            * (axis_bottom - axis_top)
        )
        raw_points = [
            (round(pl + second / 599.0 * (pr - pl)), map_y(value))
            for second, value in enumerate(percent)
        ]
        smooth_points = [
            (round(pl + second / 599.0 * (pr - pl)), map_y(value))
            for second, value in enumerate(smooth)
        ]
        draw.line(raw_points, fill="#bfdbfe" if rate == 160 else "#fecaca", width=1)
        draw.line(smooth_points, fill=COLORS[rate], width=3)
    for second in (0, 120, 240, 360, 480, 600):
        x = round(pl + second / 600.0 * (pr - pl))
        draw.text((x - 14, pb + 14), str(second), fill="#64748b", font=font(12))
    draw.text((pl, pb + 42), "时间 / 秒", fill="#334155", font=font(15))


def summary(measurements: dict[int, dict[str, Any]]) -> dict[str, Any]:
    return {
        "meaning": {
            "temporal_autocorrelation": "Same clean-bin power remains correlated across adjacent seconds; this slows integration.",
            "cross_channel_coherence": "ADC0/ADC2 share a stable complex component; this is distinct from temporal power correlation.",
            "not_a_detection_claim": "Correlation does not prove a weak astronomical signal or isolate the source to the ADC.",
        },
        "rates": {
            str(rate): {
                "median_slope_1_16_seconds": value["median_slope_1_16_seconds"],
                "median_slope_1_128_seconds": value["median_slope_1_128_seconds"],
                "autocorrelation": value["autocorrelation"],
                "integration_improvement": value["improvement"],
                "adc0_adc2_coherence": value["coherence"],
            }
            for rate, value in measurements.items()
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--evidence",
        type=Path,
        default=Path("build/receiver/latest/evidence/performance_evaluation"),
    )
    args = parser.parse_args()
    measurements = {
        rate: load_measurement(
            args.evidence / f"stability_{rate}msps" / "monitor_raw.json"
        )
        for rate in (160, 320)
    }
    image = Image.new("RGB", (2600, 1900), "#f8fafc")
    draw = ImageDraw.Draw(image)
    draw.text(
        (54, 24),
        "Stage 34a：低噪声 bin 的“相关性”到底是什么？",
        fill="#0f172a",
        font=font(43, True),
    )
    draw.text(
        (56, 84),
        "以下全部来自 DAC 静音、160/320 MS/s 各600秒实测；960 MHz只作已知固定杂散对照，不参加干净积分门禁。",
        fill="#334155",
        font=font(21),
    )
    draw_integration(draw, (38, 135, 1280, 980), measurements)
    draw_autocorrelation(draw, (1320, 135, 2562, 980), measurements)
    draw_coherence(draw, (38, 1018, 1280, 1818), measurements)
    draw_timeline(draw, (1320, 1018, 2562, 1818), measurements)
    draw.text(
        (55, 1842),
        "关键：这里的相关性表示噪声起伏不是完全独立；不等于发现了天文信号，也尚未把来源单独归因到 ADC。",
        fill="#7c2d12",
        font=font(22, True),
    )
    output = args.evidence / "plots" / "noise_correlation_explainer.png"
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, optimize=True)
    summary_path = args.evidence / "noise_correlation_summary.json"
    value = summary(measurements)
    value["plot"] = {
        "path": str(output.resolve()),
        "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
    }
    summary_path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"plot": str(output), "summary": str(summary_path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
