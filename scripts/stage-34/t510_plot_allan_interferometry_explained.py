#!/usr/bin/env python3
"""Render reader-oriented Stage 34d figures from frozen JSON/TIS1 evidence."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import statistics
import struct
import sys
import textwrap
from typing import Any, Callable, Iterable, Sequence

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import t510_allan_interferometry as stage34d


BG = "#f4f7fb"
PANEL = "#ffffff"
INK = "#14213d"
MUTED = "#58677f"
GRID = "#d8e0eb"
BLUE = "#2563eb"
RED = "#dc2626"
GREEN = "#16803a"
ORANGE = "#ea7c18"
PURPLE = "#7c3aed"
CYAN = "#0891b2"
PINK = "#be185d"
GRAY = "#64748b"


def font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    candidates = (
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc" if bold
        else "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    )
    for candidate in candidates:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def rounded(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], *, fill: str = PANEL, outline: str = GRID, radius: int = 20, width: int = 2) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def wrapped(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, *, width: int, size: int = 24, fill: str = INK, bold: bool = False, spacing: int = 9) -> int:
    lines: list[str] = []
    for paragraph in text.split("\n"):
        if not paragraph:
            lines.append("")
            continue
        line = ""
        for character in paragraph:
            candidate = line + character
            if draw.textlength(candidate, font=font(size, bold)) > width and line:
                lines.append(line); line = character
            else:
                line = candidate
        lines.append(line)
    y = xy[1]
    for line in lines:
        draw.text((xy[0], y), line, fill=fill, font=font(size, bold))
        y += size + spacing
    return y


def title(draw: ImageDraw.ImageDraw, heading: str, subtitle: str, *, width: int) -> int:
    draw.text((55, 34), heading, fill=INK, font=font(38, True))
    return wrapped(draw, (58, 91), subtitle, width=width - 116, size=21, fill=MUTED, spacing=6) + 18


def median_curve(rows: Sequence[dict[str, Any]], field: str) -> list[tuple[float, float]]:
    by_tau: dict[float, list[float]] = {}
    for row in rows:
        curve = row.get("curve", row)
        for point in curve:
            value = float(point.get(field, math.nan))
            if math.isfinite(value) and value > 0:
                by_tau.setdefault(float(point["tau_seconds"]), []).append(value)
    return [(tau, statistics.median(values)) for tau, values in sorted(by_tau.items()) if values]


def normalized(points: Sequence[tuple[float, float]]) -> list[tuple[float, float]]:
    if not points or points[0][1] <= 0:
        return []
    base = points[0][1]
    return [(x, y / base) for x, y in points]


def log_ticks(low: float, high: float) -> list[float]:
    start = math.floor(math.log10(low)); stop = math.ceil(math.log10(high))
    ticks = []
    for exponent in range(start, stop + 1):
        for multiplier in (1, 2, 5):
            value = multiplier * 10 ** exponent
            if low <= value <= high:
                ticks.append(value)
    return ticks


def format_tick(value: float) -> str:
    if value >= 100:
        return f"{value:.0f}"
    if value >= 1:
        return f"{value:g}"
    if value >= 0.01:
        return f"{value:.2g}"
    return f"{value:.0e}"


def plot_loglog(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    curves: Sequence[tuple[str, Sequence[tuple[float, float]], str, int]],
    *,
    x_label: str,
    y_label: str,
    y_range: tuple[float, float] | None = None,
    reference: bool = True,
) -> None:
    left, top, right, bottom = box
    points = [(x, y) for _name, curve, _color, _width in curves for x, y in curve if x > 0 and y > 0 and math.isfinite(y)]
    if not points:
        return
    x_low, x_high = min(x for x, _ in points), max(x for x, _ in points)
    if y_range is None:
        y_low, y_high = min(y for _, y in points), max(y for _, y in points)
        y_low = max(1e-8, y_low / 1.5); y_high *= 1.5
    else:
        y_low, y_high = y_range
    lx0, lx1 = math.log10(x_low), math.log10(x_high)
    ly0, ly1 = math.log10(y_low), math.log10(y_high)

    def point(x: float, y: float) -> tuple[int, int]:
        px = left + int((math.log10(x) - lx0) / max(1e-12, lx1 - lx0) * (right - left))
        py = bottom - int((math.log10(y) - ly0) / max(1e-12, ly1 - ly0) * (bottom - top))
        return px, py

    for value in log_ticks(x_low, x_high):
        x, _ = point(value, y_low)
        draw.line((x, top, x, bottom), fill=GRID, width=1)
        label = format_tick(value)
        draw.text((x - draw.textlength(label, font=font(15)) / 2, bottom + 8), label, fill=MUTED, font=font(15))
    for value in log_ticks(y_low, y_high):
        _, y = point(x_low, value)
        draw.line((left, y, right, y), fill=GRID, width=1)
        label = format_tick(value)
        draw.text((left - 12 - draw.textlength(label, font=font(15)), y - 10), label, fill=MUTED, font=font(15))
    draw.rectangle(box, outline="#92a3b8", width=2)
    if reference:
        ref = [(x, math.sqrt(x_low / x)) for x in sorted({x for x, _ in points})]
        line = [point(x, y) for x, y in ref if y_low <= y <= y_high]
        for first, second in zip(line[::2], line[1::2]):
            draw.line((first, second), fill="#111827", width=3)
    for _name, curve, color, line_width in curves:
        line = [point(x, y) for x, y in curve if x_low <= x <= x_high and y_low <= y <= y_high]
        if len(line) >= 2:
            draw.line(line, fill=color, width=line_width, joint="curve")
        for x, y in line:
            draw.ellipse((x - 4, y - 4, x + 4, y + 4), fill=color)
    draw.text(((left + right) // 2 - 65, bottom + 30), x_label, fill=INK, font=font(17, True))
    draw.text((left + 8, top + 8), y_label, fill=INK, font=font(16, True))


def legend(draw: ImageDraw.ImageDraw, items: Sequence[tuple[str, str]], xy: tuple[int, int], *, columns: int = 1, item_width: int = 260) -> None:
    x0, y0 = xy
    for index, (label, color) in enumerate(items):
        column, row = index % columns, index // columns
        x, y = x0 + column * item_width, y0 + row * 31
        draw.line((x, y + 10, x + 34, y + 10), fill=color, width=5)
        draw.text((x + 44, y - 3), label, fill=INK, font=font(16))


def percent(value: float) -> str:
    return f"{100 * value:.1f}%"


def load_evidence(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    shared = json.loads((root / "shared" / "phase_result.json").read_text())
    opened = json.loads((root / "open" / "phase_result.json").read_text())
    return shared, opened


def find_run(phase: dict[str, Any], rate: int, duration: int) -> dict[str, Any]:
    return next(row for row in phase["runs"] if int(row["rate"]) == rate and int(row["duration"]) == duration)


def executive_summary(output: Path, shared: dict[str, Any], opened: dict[str, Any]) -> Path:
    image = Image.new("RGB", (2100, 1240), BG); draw = ImageDraw.Draw(image)
    y = title(
        draw,
        "Stage 34d 结果总览：工程数据完整，但互相关存在长积分地板",
        "先看结论，再看证据。绿色表示工程链路通过；红色表示天文互相关预门禁未通过。开放输入不是50 Ω匹配负载，因此最后一项仍需独立终端复核。",
        width=image.width,
    )
    cards = [
        ("① 数据链路", "ENGINEERING PASS", GREEN, "8个正式run全部完成；160/320 MS/s全速；drop、gap、FIR饱和、FFT overflow均为0。说明结论不是丢包或数据错位造成。"),
        ("② 自相关 / Allan", "慢漂移仍存在", RED, "原始总功率失败；扣掉公共增益模态后的频谱残差也大多失败。因此不是一个可简单相除掉的整体增益起伏，而含频率相关或通道局部漂移。"),
        ("③ 共享SSA：ADC0×ADC2", "相关地板观察到", RED, "Re/Im白噪声斜率四次仅1/12、0/12、0/12、0/12通过；长run的128秒散布是白噪声外推的4.55～4.69倍。"),
        ("④ 八路全部开放", "相关地板仍观察到", RED, "平均|γ|只有约0.001～0.002，但长积分后多对ADC在多个频点显著非零；3600秒Re/Im斜率通过率仅27.1%和31.5%。"),
        ("⑤ 同tile vs 跨tile", "同tile更强", ORANGE, "开放输入下，同tile pair的整体中位|γ|=0.00550；跨tile=0.00115，约4.8倍。这个方向值得继续调查，但尚不能单独证明片内串扰。"),
        ("⑥ 结论边界", "仍需8个独立50 Ω终端", PURPLE, "悬空ADC输入会像天线一样接收实验室RFI和板间耦合。开放输入失败不能区分环境拾取与板内公共噪声。"),
    ]
    card_width, card_height = 965, 255
    for index, (heading, status, color, body) in enumerate(cards):
        column, row = index % 2, index // 2
        left = 55 + column * 1015; top = y + row * 285
        rounded(draw, (left, top, left + card_width, top + card_height))
        draw.rectangle((left, top, left + 11, top + card_height), fill=color)
        draw.text((left + 30, top + 22), heading, fill=INK, font=font(25, True))
        draw.rounded_rectangle((left + 585, top + 17, left + 935, top + 58), radius=18, fill=color)
        label_width = draw.textlength(status, font=font(18, True))
        draw.text((left + 760 - label_width / 2, top + 25), status, fill="white", font=font(18, True))
        wrapped(draw, (left + 30, top + 79), body, width=card_width - 60, size=20, fill=MUTED, spacing=8)
    footer_top = y + 3 * 285 + 8
    rounded(draw, (55, footer_top, 2045, 1190), fill="#eef3ff", outline="#93b4ff")
    draw.text((85, footer_top + 22), "一句话理解", fill=BLUE, font=font(25, True))
    wrapped(
        draw,
        (85, footer_top + 66),
        "ADC噪声的平均值确实很小，但它不是完全随机、完全独立的；积分越久，剩下的慢变化越明显。现在能确认“存在相关地板”，还不能确认“地板来自芯片内部”。",
        width=1900,
        size=23,
        fill=INK,
        bold=True,
        spacing=8,
    )
    path = output / "00_stage34d_result_at_a_glance.png"; image.save(path, optimize=True); return path


def _power_curves(run: dict[str, Any], field: str) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    analysis = run["analysis"]
    total = normalized(median_curve(analysis["sampled_total_power"], field))
    residual = normalized(median_curve(analysis["spectroscopic_allan"], field))
    return total, residual


def integration_figure(output: Path, shared: dict[str, Any], opened: dict[str, Any]) -> Path:
    image = Image.new("RGB", (2200, 1720), BG); draw = ImageDraw.Draw(image)
    y = title(
        draw,
        "1. 积分越久，噪声有没有按 1/√时间 下降？",
        "纵轴已除以1秒时的散布：1代表未改善，越低越好。黑色虚线是理想白噪声；蓝线是六个离栅格点形成的“采样总功率”，红线是扣除每秒公共标量增益后的频谱形状残差。若红线恢复理想斜率，说明只需校正整体增益；本次并没有。",
        width=image.width,
    )
    configurations = [
        ("共享SSA输入", find_run(shared, 160, 3600)),
        ("共享SSA输入", find_run(shared, 320, 3600)),
        ("八路全部开放", find_run(opened, 160, 3600)),
        ("八路全部开放", find_run(opened, 320, 3600)),
    ]
    for index, (condition, run) in enumerate(configurations):
        column, row = index % 2, index // 2
        panel_left = 55 + column * 1070; panel_top = y + row * 670
        rounded(draw, (panel_left, panel_top, panel_left + 1020, panel_top + 620))
        draw.text((panel_left + 26, panel_top + 20), f"{condition} · {run['rate']} MS/s · 3600秒", fill=INK, font=font(25, True))
        total, residual = _power_curves(run, "fractional_stddev")
        plot_loglog(
            draw,
            (panel_left + 105, panel_top + 86, panel_left + 960, panel_top + 430),
            (("采样总功率", total, BLUE, 5), ("频谱残差", residual, RED, 5)),
            x_label="积分时间 τ / 秒",
            y_label="相对散布 σ(τ)/σ(1s)",
            y_range=(0.04, 1.5),
        )
        legend(draw, (("理想白噪声 1/√τ", "#111827"), ("采样总功率", BLUE), ("频谱残差", RED)), (panel_left + 105, panel_top + 488), columns=3, item_width=280)
        total_slope = statistics.median(float(row["slope"]) for row in run["analysis"]["sampled_total_power"])
        residual_slope = statistics.median(float(row["slope"]) for row in run["analysis"]["spectroscopic_allan"])
        note = f"斜率：总功率 {total_slope:+.3f}，频谱残差 {residual_slope:+.3f}；合格区是 −0.65～−0.35。"
        draw.text((panel_left + 105, panel_top + 548), note, fill=RED if not (-.65 <= residual_slope <= -.35) else GREEN, font=font(18, True))
    rounded(draw, (55, 1510, 2145, 1660), fill="#fff7ed", outline="#fdba74")
    draw.text((85, 1530), "怎么看这张图", fill=ORANGE, font=font(23, True))
    wrapped(draw, (85, 1570), "四个面板中，实际曲线到几十秒以后都比黑色理想线更平。频谱残差也没有回到黑线，说明慢变化不仅是所有频点一起升降，还会改变频谱形状。", width=2020, size=21, fill=INK, bold=True)
    path = output / "01_integration_white_noise_test_explained.png"; image.save(path, optimize=True); return path


def allan_figure(output: Path, shared: dict[str, Any], opened: dict[str, Any]) -> Path:
    image = Image.new("RGB", (2200, 1720), BG); draw = ImageDraw.Draw(image)
    y = title(
        draw,
        "2. Overlapping Allan deviation：稳定时间在哪里？",
        "Allan曲线先下降表示随机噪声在被平均；到最低点后变平或上升，表示慢漂移开始占主导。这里把每条曲线除以自己的1秒值以便比较形状。最低点落在测试右边界时，只能说稳定时间至少到该点，不能外推更久。",
        width=image.width,
    )
    configurations = [
        ("共享SSA输入", find_run(shared, 160, 3600)),
        ("共享SSA输入", find_run(shared, 320, 3600)),
        ("八路全部开放", find_run(opened, 160, 3600)),
        ("八路全部开放", find_run(opened, 320, 3600)),
    ]
    for index, (condition, run) in enumerate(configurations):
        column, row = index % 2, index // 2
        panel_left = 55 + column * 1070; panel_top = y + row * 670
        rounded(draw, (panel_left, panel_top, panel_left + 1020, panel_top + 620))
        draw.text((panel_left + 26, panel_top + 20), f"{condition} · {run['rate']} MS/s", fill=INK, font=font(25, True))
        total, residual = _power_curves(run, "overlapping_allan_deviation")
        plot_loglog(
            draw,
            (panel_left + 105, panel_top + 86, panel_left + 960, panel_top + 430),
            (("采样总功率", total, BLUE, 5), ("频谱残差", residual, RED, 5)),
            x_label="平均时间 τ / 秒",
            y_label="归一化 Allan deviation",
            y_range=(0.04, 1.8),
        )
        legend(draw, (("理想白噪声趋势", "#111827"), ("采样总功率", BLUE), ("频谱残差", RED)), (panel_left + 105, panel_top + 488), columns=3, item_width=280)
        total_times = [float(row["allan_time_seconds"]) for row in run["analysis"]["sampled_total_power"] if isinstance(row["allan_time_seconds"], (int, float))]
        residual_times = [float(row["allan_time_seconds"]) for row in run["analysis"]["spectroscopic_allan"] if isinstance(row["allan_time_seconds"], (int, float))]
        draw.text((panel_left + 105, panel_top + 548), f"各通道Allan最低点分布：总功率 {min(total_times):g}～{max(total_times):g} s；残差 {min(residual_times):g}～{max(residual_times):g} s", fill=MUTED, font=font(17))
    rounded(draw, (55, 1510, 2145, 1660), fill="#eef3ff", outline="#93b4ff")
    draw.text((85, 1530), "它对观测策略意味着什么", fill=BLUE, font=font(23, True))
    wrapped(draw, (85, 1570), "不能假设把数据连续平均几分钟就一定更灵敏。更稳妥的做法是把长观测切成较短积分、保留时间轴，并用校准源或参考天区周期性追踪慢漂移；真正可用周期仍需50 Ω匹配负载和实际前端复核。", width=2020, size=21, fill=INK, bold=True)
    path = output / "02_allan_stability_time_explained.png"; image.save(path, optimize=True); return path


def shared_visibility_figure(output: Path, shared: dict[str, Any]) -> Path:
    image = Image.new("RGB", (2200, 1720), BG); draw = ImageDraw.Draw(image)
    y = title(
        draw,
        "3. 共享输入 ADC0×ADC2：复可见度残差是否继续下降？",
        "V02=<X0·conj(X2)>。先减去每个run的平均复可见度，再分别观察实部Re和虚部Im的散布。共享源允许平均V02不为零；正式问题是残差是否继续按1/√τ下降。每个面板有6个离栅格频点×Re/Im=12条判定序列。",
        width=image.width,
    )
    runs = shared["runs"]
    for index, run in enumerate(runs):
        column, row_index = index % 2, index // 2
        panel_left = 55 + column * 1070; panel_top = y + row_index * 670
        rounded(draw, (panel_left, panel_top, panel_left + 1020, panel_top + 620))
        draw.text((panel_left + 26, panel_top + 20), f"{run['rate']} MS/s · {run['duration']} s · {run['bucket_ms']} ms bucket", fill=INK, font=font(21, True))
        rows = [metric for metric in run["analysis"]["cross_metrics"] if (metric["channel_a"], metric["channel_b"]) == (0, 2)]
        re_rows = [{"curve": metric["re_curve"]} for metric in rows]
        im_rows = [{"curve": metric["im_curve"]} for metric in rows]
        re_curve = normalized(median_curve(re_rows, "fractional_stddev"))
        im_curve = normalized(median_curve(im_rows, "fractional_stddev"))
        plot_loglog(
            draw,
            (panel_left + 105, panel_top + 82, panel_left + 960, panel_top + 415),
            (("Re残差", re_curve, BLUE, 5), ("Im残差", im_curve, RED, 5)),
            x_label="积分时间 τ / 秒",
            y_label="相对散布（首点=1）",
            y_range=(0.04, 1.5),
        )
        legend(draw, (("理想白噪声 1/√τ", "#111827"), ("Re残差", BLUE), ("Im残差", RED)), (panel_left + 105, panel_top + 470), columns=3, item_width=275)
        slope_pass = sum(int(metric["re_slope_pass"]) + int(metric["im_slope_pass"]) for metric in rows)
        lag = statistics.median(abs(float(metric[key])) for metric in rows for key in ("re_lag1_1s", "im_lag1_1s"))
        gamma = statistics.median(float(metric["mean_coherence"]) for metric in rows)
        ratio = statistics.median(float(metric[key]) for metric in rows for key in ("re_white_128_ratio", "im_white_128_ratio"))
        draw.text((panel_left + 105, panel_top + 520), f"斜率通过 {slope_pass}/12（要求≥10）   中位|lag-1|={lag:.3f}（要求≤0.10）", fill=RED, font=font(18, True))
        if run["duration"] == 3600:
            draw.text((panel_left + 105, panel_top + 558), f"中位|γ|={gamma:.4f}；128秒散布/白噪声外推={ratio:.2f}×（要求≤2×）", fill=RED, font=font(17))
        else:
            draw.text((panel_left + 105, panel_top + 558), f"中位|γ|={gamma:.4f}；短run不执行128秒硬门禁", fill=MUTED, font=font(17))
    rounded(draw, (55, 1510, 2145, 1660), fill="#fff1f2", outline="#fda4af")
    draw.text((85, 1530), "结论：SHARED_INPUT_VISIBILITY_FLOOR_OBSERVED", fill=RED, font=font(23, True))
    wrapped(draw, (85, 1570), "曲线显著比黑色理想线更平，且连续1秒样本本身就有明显相关。共享输入的物理信号可以产生非零平均可见度，但无法解释“减去平均后仍不按白噪声下降”的长积分地板。", width=2020, size=21, fill=INK, bold=True)
    path = output / "03_shared_adc02_visibility_explained.png"; image.save(path, optimize=True); return path


def _heat_color(value: float, low: float, high: float) -> tuple[int, int, int]:
    fraction = min(1.0, max(0.0, (value - low) / max(1e-12, high - low)))
    stops = ((240, 249, 255), (96, 165, 250), (250, 204, 21), (220, 38, 38))
    position = fraction * (len(stops) - 1)
    index = min(len(stops) - 2, int(position)); local = position - index
    return tuple(int(stops[index][channel] * (1 - local) + stops[index + 1][channel] * local) for channel in range(3))


def _pair_rows(run: dict[str, Any], pair: tuple[int, int]) -> list[dict[str, Any]]:
    return [row for row in run["analysis"]["cross_metrics"] if (row["channel_a"], row["channel_b"]) == pair]


def draw_pair_matrix(
    draw: ImageDraw.ImageDraw,
    origin: tuple[int, int],
    run: dict[str, Any],
    *,
    mode: str,
    cell: int = 112,
) -> None:
    x0, y0 = origin
    for lane in range(8):
        draw.text((x0 + (lane + 1) * cell + 40, y0 + 12), str(lane), fill=INK, font=font(18, True))
        draw.text((x0 + 42, y0 + (lane + 1) * cell + 35), str(lane), fill=INK, font=font(18, True))
    draw.text((x0 + cell * 4, y0 - 25), "ADC j", fill=MUTED, font=font(17, True))
    draw.text((x0 + 2, y0 + cell * 4), "ADC i", fill=MUTED, font=font(17, True))
    for left in range(8):
        for right in range(8):
            box = (x0 + (right + 1) * cell, y0 + (left + 1) * cell, x0 + (right + 2) * cell - 4, y0 + (left + 2) * cell - 4)
            if left == right:
                draw.rectangle(box, fill="#e5e7eb", outline="#cbd5e1")
                draw.text((box[0] + 39, box[1] + 39), "—", fill=MUTED, font=font(22, True)); continue
            pair = tuple(sorted((left, right)))
            rows = _pair_rows(run, pair)
            if mode == "coherence":
                value = statistics.median(float(row["mean_coherence"]) for row in rows)
                transformed = math.log10(max(value, 1e-6))
                fill = _heat_color(transformed, -4.0, -1.0)
                label = f"{value:.3g}"
            else:
                value = sum(int(row["zero_mean_significant_q0p01"]) for row in rows)
                fill = _heat_color(value, 0, 6)
                label = f"{value}/6"
            draw.rectangle(box, fill=fill, outline="#ffffff", width=2)
            text_fill = "white" if (mode == "coherence" and transformed > -2.1) or (mode != "coherence" and value >= 4) else INK
            width = draw.textlength(label, font=font(17, True))
            draw.text(((box[0] + box[2] - width) / 2, box[1] + 39), label, fill=text_fill, font=font(17, True))
            if pair in stage34d.SAME_TILE_PAIRS:
                draw.rectangle(box, outline=PURPLE, width=5)


def open_pair_matrix_figure(output: Path, opened: dict[str, Any]) -> Path:
    image = Image.new("RGB", (2300, 2240), BG); draw = ImageDraw.Draw(image)
    y = title(
        draw,
        "4. 八路全部开放：28对ADC的相关地板矩阵",
        "上排是中位归一化相关幅度|γ|（越接近0越好）；下排是6个离栅格频点中，有多少个在BH q=0.01后仍显著非零。紫色边框是同一个RFDC tile内的pair：01、23、45、67。红色4/6以上就是注册的“宽带重复相关”判据。",
        width=image.width,
    )
    long_runs = (find_run(opened, 160, 3600), find_run(opened, 320, 3600))
    for column, run in enumerate(long_runs):
        panel_left = 55 + column * 1120
        rounded(draw, (panel_left, y, panel_left + 1070, y + 940))
        draw.text((panel_left + 28, y + 22), f"{run['rate']} MS/s · 3600秒：中位 |γ|", fill=INK, font=font(26, True))
        draw_pair_matrix(draw, (panel_left + 150, y + 80), run, mode="coherence", cell=82)
        values = [float(row["mean_coherence"]) for row in run["analysis"]["cross_metrics"]]
        draw.text((panel_left + 65, y + 875), f"全28对中位 |γ| = {statistics.median(values):.4g}；数值虽小，但长积分会提高检出能力。", fill=MUTED, font=font(18))
    lower_y = y + 980
    for column, run in enumerate(long_runs):
        panel_left = 55 + column * 1120
        rounded(draw, (panel_left, lower_y, panel_left + 1070, lower_y + 940))
        draw.text((panel_left + 28, lower_y + 22), f"{run['rate']} MS/s · 显著频点数 / 6", fill=INK, font=font(26, True))
        draw_pair_matrix(draw, (panel_left + 150, lower_y + 80), run, mode="significance", cell=82)
        failing = sum(sum(int(row["zero_mean_significant_q0p01"]) for row in _pair_rows(run, pair)) >= 4 for pair in stage34d.ADC_PAIRS)
        draw.text((panel_left + 65, lower_y + 875), f"宽带重复相关pair：{failing}/28（要求0/28）。", fill=RED, font=font(19, True))
    path = output / "04_open_input_28pair_matrices_explained.png"; image.save(path, optimize=True); return path


def tile_comparison_figure(output: Path, opened: dict[str, Any]) -> Path:
    image = Image.new("RGB", (2100, 1350), BG); draw = ImageDraw.Draw(image)
    y = title(
        draw,
        "5. 同一个RFDC tile内的ADC pair，相关幅度系统性更高",
        "每个run分别把同tile四对（01、23、45、67）与其余24个跨tile pair的六个离栅格频点合并取中位。纵轴是对数刻度；数字是同tile/跨tile的倍率。这个差异是定位线索，不是因果证明。",
        width=image.width,
    )
    runs = opened["runs"]
    left, top, right, bottom = 150, y + 40, 2020, y + 780
    y_low, y_high = 5e-4, 6e-2
    ly0, ly1 = math.log10(y_low), math.log10(y_high)

    def py(value: float) -> int:
        return bottom - int((math.log10(value) - ly0) / (ly1 - ly0) * (bottom - top))

    for value in (0.0005, 0.001, 0.002, 0.005, 0.01, 0.02, 0.05):
        yy = py(value); draw.line((left, yy, right, yy), fill=GRID, width=1)
        label = format_tick(value); draw.text((left - 18 - draw.textlength(label, font=font(17)), yy - 11), label, fill=MUTED, font=font(17))
    draw.rectangle((left, top, right, bottom), outline="#92a3b8", width=2)
    group_width = (right - left) / len(runs)
    for index, run in enumerate(runs):
        rows = run["analysis"]["cross_metrics"]
        same = statistics.median(float(row["mean_coherence"]) for row in rows if row["tile_group"] == "same_tile")
        cross = statistics.median(float(row["mean_coherence"]) for row in rows if row["tile_group"] == "cross_tile")
        center = left + group_width * (index + .5)
        for offset, value, color, name in ((-62, same, PURPLE, "同tile"), (18, cross, CYAN, "跨tile")):
            x0 = int(center + offset); y0 = py(value)
            draw.rectangle((x0, y0, x0 + 54, bottom), fill=color)
            label = f"{value:.3g}"; draw.text((x0 + 27 - draw.textlength(label, font=font(16, True)) / 2, y0 - 27), label, fill=color, font=font(16, True))
        ratio = same / cross
        draw.text((center - draw.textlength(f"{ratio:.1f}×", font=font(23, True)) / 2, top + 18), f"{ratio:.1f}×", fill=ORANGE, font=font(23, True))
        label = f"{run['rate']} MS/s\n{run['duration']} s"
        draw.multiline_text((center - 60, bottom + 18), label, fill=INK, font=font(17, True), align="center", spacing=4)
    legend(draw, (("同tile pair", PURPLE), ("跨tile pair", CYAN)), (760, bottom + 92), columns=2, item_width=300)
    rounded(draw, (70, 1050, 2030, 1280), fill="#fff7ed", outline="#fdba74")
    draw.text((100, 1074), "为什么这很重要，但还不能下结论", fill=ORANGE, font=font(25, True))
    wrapped(draw, (100, 1122), "四次实验都是同tile高于跨tile，说明RFDC tile内部共享的时钟、供电、基底耦合或输入邻近耦合值得优先检查。但开放端口也可能在相邻走线/连接器上同时接收到相同环境RFI。只有给每路接独立匹配50 Ω后，这个倍率仍复现，才能把板内机制放到更强的因果位置。", width=1870, size=21, fill=INK, spacing=7)
    path = output / "05_same_tile_vs_cross_tile_explained.png"; image.save(path, optimize=True); return path


def read_tis1_selected(path: Path, rf_mhz: float, pairs: Sequence[tuple[int, int]]) -> dict[str, Any]:
    with path.open("rb") as stream:
        header = stream.read(64)
        if len(header) != 64 or header[:4] != b"TIS1":
            raise ValueError(f"invalid TIS1 {path}")
        version, header_bytes = struct.unpack_from("<HH", header, 4)
        metadata_bytes, bucket_ms, rate, duration, target_count, lane_count, pair_count, _reserved, record_count, _started, _origin, record_bytes = struct.unpack_from("<IIIIHHHHQQQQ", header, 8)
        if version != 1 or header_bytes != 64 or lane_count != 8:
            raise ValueError("unsupported TIS1")
        metadata = json.loads(stream.read(metadata_bytes))
        target = min(metadata["targets"], key=lambda row: abs(float(row["actual_rf_mhz"]) - rf_mhz))
        if abs(float(target["actual_rf_mhz"]) - rf_mhz) > 1e-6:
            raise ValueError(f"RF {rf_mhz} not present")
        target_index = int(target["target_index"])
        mapping = [tuple(item) for item in metadata["pairs"]]
        pair_indices = {pair: mapping.index(pair) for pair in pairs}
        buckets: list[int] = []
        powers = {lane: [] for lane in range(8)}
        crosses = {pair: [] for pair in pairs}
        remainder_size = record_bytes - 32
        for _ in range(record_count):
            prefix = stream.read(32)
            if len(prefix) != 32:
                raise ValueError("truncated TIS1 prefix")
            bucket, row_target, _reserved, _first, _last, _samples = struct.unpack("<IHHQQQ", prefix)
            remainder = stream.read(remainder_size)
            if len(remainder) != remainder_size:
                raise ValueError("truncated TIS1 record")
            if row_target != target_index:
                continue
            buckets.append(bucket)
            for lane in range(8):
                count, _sum_i, _sum_q, sum_power, _sum_square = struct.unpack_from("<Qdddd", remainder, lane * 40)
                powers[lane].append(sum_power / count)
            pair_base = lane_count * 40
            for pair, pair_index in pair_indices.items():
                count, real, imag = struct.unpack_from("<Qdd", remainder, pair_base + pair_index * 24)
                raw = complex(real / count, imag / count)
                power_a = powers[pair[0]][-1]; power_b = powers[pair[1]][-1]
                crosses[pair].append(raw / math.sqrt(max(power_a * power_b, 1e-300)))
        expected = duration * 1000 // bucket_ms
        if buckets != list(range(expected)):
            raise ValueError(f"selected TIS1 buckets are incomplete: {len(buckets)}/{expected}")
        return {"bucket_ms": bucket_ms, "rate": rate, "duration": duration, "rf_mhz": rf_mhz, "powers": powers, "crosses": crosses}


def moving_average(values: Sequence[float], width: int) -> list[float]:
    prefix = [0.0]
    for value in values:
        prefix.append(prefix[-1] + value)
    result = []
    for index in range(len(values)):
        left = max(0, index - width + 1)
        result.append((prefix[index + 1] - prefix[left]) / (index + 1 - left))
    return result


def percentile(values: Sequence[float], fraction: float) -> float:
    ordered = sorted(value for value in values if math.isfinite(value))
    if not ordered:
        return math.nan
    position = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * fraction))))
    return ordered[position]


def plot_linear_time(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    curves: Sequence[tuple[str, Sequence[float], str, int]],
    *,
    bucket_seconds: float,
    y_label: str,
) -> None:
    left, top, right, bottom = box
    all_values = [value for _name, values, _color, _width in curves for value in values if math.isfinite(value)]
    low, high = percentile(all_values, .01), percentile(all_values, .99)
    padding = max(1e-12, (high - low) * .15); low -= padding; high += padding
    duration = max(len(values) for _name, values, _color, _width in curves) * bucket_seconds

    def point(index: int, value: float, length: int) -> tuple[int, int]:
        x = left + int(index / max(1, length - 1) * (right - left))
        y = bottom - int((value - low) / max(1e-12, high - low) * (bottom - top))
        return x, max(top, min(bottom, y))

    for second in range(0, int(duration) + 1, 600):
        x = left + int(second / duration * (right - left))
        draw.line((x, top, x, bottom), fill=GRID)
        label = str(second); draw.text((x - draw.textlength(label, font=font(14)) / 2, bottom + 8), label, fill=MUTED, font=font(14))
    for fraction in (0, .25, .5, .75, 1):
        value = low + fraction * (high - low); y = bottom - int(fraction * (bottom - top))
        draw.line((left, y, right, y), fill=GRID)
        label = f"{value:+.3g}"; draw.text((left - 12 - draw.textlength(label, font=font(14)), y - 9), label, fill=MUTED, font=font(14))
    if low < 0 < high:
        y0 = bottom - int((-low) / (high - low) * (bottom - top)); draw.line((left, y0, right, y0), fill="#475569", width=2)
    draw.rectangle(box, outline="#92a3b8", width=2)
    for _name, values, color, width in curves:
        stride = max(1, len(values) // 1800)
        line = [point(index, values[index], len(values)) for index in range(0, len(values), stride)]
        if len(line) >= 2:
            draw.line(line, fill=color, width=width, joint="curve")
    draw.text(((left + right) // 2 - 50, bottom + 30), "时间 / 秒", fill=INK, font=font(17, True))
    draw.text((left + 8, top + 8), y_label, fill=INK, font=font(16, True))


def real_timeline_figure(output: Path, evidence_root: Path) -> Path:
    shared_path = evidence_root / "shared" / "runs" / "shared_320msps_3600s_1s" / "shared_320msps_3600s_1s.tis1"
    open_path = evidence_root / "open" / "runs" / "open_320msps_3600s_1s" / "open_320msps_3600s_1s.tis1"
    shared = read_tis1_selected(shared_path, 1007.5, ((0, 2),))
    opened = read_tis1_selected(open_path, 1007.5, ((0, 1), (0, 4)))
    image = Image.new("RGB", (2200, 1840), BG); draw = ImageDraw.Draw(image)
    y = title(
        draw,
        "6. 真实1秒数据：慢起伏在时间轴上是什么样子？",
        "数据直接从冻结TIS1读取，频点为1007.5 MHz、320 MS/s、3600秒。细灰线是每秒值，彩色粗线是32秒滑动平均。平滑后仍缓慢起伏，就说明相邻时间桶不是完全独立的随机噪声。",
        width=image.width,
    )
    panels = []
    median0 = statistics.median(shared["powers"][0]); median2 = statistics.median(shared["powers"][2])
    p0 = [(value / median0 - 1) * 100 for value in shared["powers"][0]]
    p2 = [(value / median2 - 1) * 100 for value in shared["powers"][2]]
    panels.append((
        "A. 共享SSA输入：ADC0/ADC2单频点功率",
        (("ADC0 每秒", p0, "#cbd5e1", 1), ("ADC2 每秒", p2, "#e5e7eb", 1), ("ADC0 32秒平均", moving_average(p0, 32), BLUE, 4), ("ADC2 32秒平均", moving_average(p2, 32), RED, 4)),
        "相对各自中位功率 / %",
        (("ADC0 32秒平均", BLUE), ("ADC2 32秒平均", RED)),
    ))
    shared_gamma = shared["crosses"][(0, 2)]
    mean_re = statistics.fmean(value.real for value in shared_gamma); mean_im = statistics.fmean(value.imag for value in shared_gamma)
    shared_re = [(value.real - mean_re) * 1000 for value in shared_gamma]
    shared_im = [(value.imag - mean_im) * 1000 for value in shared_gamma]
    panels.append((
        "B. 共享SSA输入：ADC0×ADC2复可见度（已减去平均值）",
        (("Re 每秒", shared_re, "#bfdbfe", 1), ("Im 每秒", shared_im, "#fecaca", 1), ("Re 32秒平均", moving_average(shared_re, 32), BLUE, 4), ("Im 32秒平均", moving_average(shared_im, 32), RED, 4)),
        "残差 γ × 10⁻³",
        (("Re 32秒平均", BLUE), ("Im 32秒平均", RED)),
    ))
    same = opened["crosses"][(0, 1)]; cross = opened["crosses"][(0, 4)]
    same_re = [(value.real - statistics.fmean(item.real for item in same)) * 1000 for value in same]
    cross_re = [(value.real - statistics.fmean(item.real for item in cross)) * 1000 for value in cross]
    panels.append((
        "C. 八路开放：同tile pair 01 与跨tile pair 04",
        (("01 每秒", same_re, "#ddd6fe", 1), ("04 每秒", cross_re, "#cffafe", 1), ("同tile 01，32秒平均", moving_average(same_re, 32), PURPLE, 4), ("跨tile 04，32秒平均", moving_average(cross_re, 32), CYAN, 4)),
        "Re(γ−平均γ) × 10⁻³",
        (("同tile 01", PURPLE), ("跨tile 04", CYAN)),
    ))
    for index, (heading, curves, y_label, items) in enumerate(panels):
        panel_top = y + index * 490
        rounded(draw, (55, panel_top, 2145, panel_top + 450))
        draw.text((85, panel_top + 18), heading, fill=INK, font=font(24, True))
        plot_linear_time(draw, (205, panel_top + 72, 2070, panel_top + 320), curves, bucket_seconds=1.0, y_label=y_label)
        legend(draw, items, (760, panel_top + 402), columns=2, item_width=360)
    rounded(draw, (55, 1660, 2145, 1790), fill="#eef3ff", outline="#93b4ff")
    wrapped(draw, (85, 1686), "这些曲线不是为了比较绝对幅度，而是让你直接看到：32秒平均后并没有变成一条安静的直线，仍有共同或局部的慢起伏。这正是积分曲线变平、lag-1偏高和128秒地板的时间域表现。", width=2020, size=21, fill=INK, bold=True)
    path = output / "06_real_1second_timelines_explained.png"; image.save(path, optimize=True); return path


def write_index(output: Path, paths: Sequence[Path]) -> Path:
    content = """# Stage 34d 易读版图表

建议按编号阅读：

1. `00_stage34d_result_at_a_glance.png`：先看最终结论和边界。
2. `01_integration_white_noise_test_explained.png`：实际积分曲线与理想 `1/√τ` 对比。
3. `02_allan_stability_time_explained.png`：Allan deviation及稳定时间含义。
4. `03_shared_adc02_visibility_explained.png`：共享SSA时ADC0×ADC2的复可见度残差。
5. `04_open_input_28pair_matrices_explained.png`：开放输入28对的相关幅度和显著频点矩阵。
6. `05_same_tile_vs_cross_tile_explained.png`：同tile与跨tile的方向性差异。
7. `06_real_1second_timelines_explained.png`：从TIS1直接提取的真实1秒时间序列。

核心结论：数字数据链完整；自相关和复互相关都存在长积分地板；开放输入下同tile相关更强，但开放端口会接收环境RFI，因此还需要八个独立匹配50 Ω终端才能区分板内机制与环境拾取。
"""
    path = output / "README.md"; path.write_text(content)
    manifest = output / "SHA256SUMS"
    import hashlib
    lines = []
    for item in paths:
        lines.append(f"{hashlib.sha256(item.read_bytes()).hexdigest()}  {item.name}\n")
    manifest.write_text("".join(lines))
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root", type=Path, default=Path("build/receiver/latest/evidence/allan_interferometry"))
    parser.add_argument("--output")
    args = parser.parse_args()
    evidence_root = args.evidence_root.resolve()
    output = Path(args.output).resolve() if args.output else evidence_root / "plots_explained"
    output.mkdir(parents=True, exist_ok=True)
    shared, opened = load_evidence(evidence_root)
    paths = [
        executive_summary(output, shared, opened),
        integration_figure(output, shared, opened),
        allan_figure(output, shared, opened),
        shared_visibility_figure(output, shared),
        open_pair_matrix_figure(output, opened),
        tile_comparison_figure(output, opened),
        real_timeline_figure(output, evidence_root),
    ]
    write_index(output, paths)
    print(json.dumps({"output": str(output), "plots": [str(path) for path in paths]}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
