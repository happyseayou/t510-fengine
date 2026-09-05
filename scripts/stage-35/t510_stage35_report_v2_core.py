#!/usr/bin/env python3
"""Pure helpers and contracts for the Stage 35 scientific report v2."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Sequence


BIN_COUNT = 4096
CENTER_HZ = 1_020_000_000.0
CHANNEL_WIDTH_HZ = 78_125.0
ENBW_HZ = 70_879.578125


def signed_bin(global_bin: int) -> int:
    if not 0 <= global_bin < BIN_COUNT:
        raise ValueError(f"global_bin outside 0..4095: {global_bin}")
    return global_bin if global_bin < BIN_COUNT // 2 else global_bin - BIN_COUNT


def rf_hz(global_bin: int) -> float:
    return CENTER_HZ + signed_bin(global_bin) * CHANNEL_WIDTH_HZ


def ascending_global_bins() -> tuple[int, ...]:
    return tuple(range(BIN_COUNT // 2, BIN_COUNT)) + tuple(range(0, BIN_COUNT // 2))


def global_bin_at_rf_hz(frequency_hz: float) -> int:
    offset = round((frequency_hz - CENTER_HZ) / CHANNEL_WIDTH_HZ)
    if not -(BIN_COUNT // 2) <= offset < BIN_COUNT // 2:
        raise ValueError(f"RF frequency outside registered band: {frequency_hz}")
    return offset % BIN_COUNT


def frequency_tick_pairs() -> tuple[tuple[float, int], ...]:
    frequencies_mhz = (860.0, 900.0, 940.0, 960.0, 980.0, 1020.0, 1060.0, 1100.0, 1140.0, 1179.921875)
    return tuple((value, global_bin_at_rf_hz(value * 1e6)) for value in frequencies_mhz)


def white_fractional_sigma(tau_s: float, enbw_hz: float = ENBW_HZ) -> float:
    """Radiometer-equation fractional scatter for ideal white noise."""
    if tau_s <= 0.0 or enbw_hz <= 0.0:
        raise ValueError("tau and ENBW must be positive")
    return 1.0 / math.sqrt(enbw_hz * tau_s)


def radiometer_efficiency(measured_over_white: float) -> float:
    """White-noise-equivalent integration efficiency, 1 / ratio**2."""
    if measured_over_white <= 0.0:
        raise ValueError("measured/white ratio must be positive")
    return 1.0 / (measured_over_white * measured_over_white)


def equivalent_white_time(tau_s: float, measured_over_white: float) -> float:
    if tau_s <= 0.0:
        raise ValueError("tau must be positive")
    return tau_s * radiometer_efficiency(measured_over_white)


def preflagged_bins() -> frozenset[int]:
    """Bins carrying a frozen, pre-existing quality flag in the v1 analysis."""
    return frozenset((0, 2048, 3327, 3328, 3329))


def population_quantiles(
    values: Sequence[float], eligible: Sequence[bool] | None = None
) -> dict[str, float]:
    """P05/median/P95 for a full or explicitly masked population."""
    if eligible is not None and len(values) != len(eligible):
        raise ValueError("population and eligibility lengths differ")
    selected = [
        float(value) for index, value in enumerate(values)
        if (eligible is None or eligible[index]) and math.isfinite(float(value))
    ]
    if not selected:
        raise ValueError("population has no finite eligible values")
    return {
        "p05": _linear_quantile(selected, 0.05),
        "median": _linear_quantile(selected, 0.5),
        "p95": _linear_quantile(selected, 0.95),
    }


def _linear_quantile(values: Sequence[float], probability: float) -> float:
    ordered = sorted(float(value) for value in values if math.isfinite(float(value)))
    if not ordered:
        raise ValueError("quantile requires at least one finite value")
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def representative_bin(
    metric_rows: Sequence[Sequence[float]], eligible: Sequence[bool]
) -> int:
    """Choose the robust multimetric medoid; ties resolve to the lowest bin."""
    if len(metric_rows) != BIN_COUNT or len(eligible) != BIN_COUNT:
        raise ValueError("representative selection requires 4096 rows and flags")
    if not metric_rows or not metric_rows[0]:
        raise ValueError("representative selection requires metrics")
    width = len(metric_rows[0])
    if any(len(row) != width for row in metric_rows):
        raise ValueError("metric rows have inconsistent widths")
    indices = [index for index, allowed in enumerate(eligible) if allowed]
    if not indices:
        raise ValueError("representative selection has no eligible bins")
    centers = []
    scales = []
    for column in range(width):
        values = [float(metric_rows[index][column]) for index in indices]
        center = _linear_quantile(values, 0.5)
        iqr = _linear_quantile(values, 0.75) - _linear_quantile(values, 0.25)
        centers.append(center)
        scales.append(iqr if iqr > 0.0 else 1.0)
    best_bin = indices[0]
    best_score = math.inf
    for index in indices:
        score = sum(
            abs(float(metric_rows[index][column]) - centers[column]) / scales[column]
            for column in range(width)
        )
        if score < best_score:
            best_bin = index
            best_score = score
    return best_bin


UNITS = {
    "time": "s",
    "rf_frequency": "MHz",
    "time_voltage": "ADU",
    "fengine_voltage": "F-engine IQ16 count",
    "power": "count²/PFB channel",
    "power_density": "count²/Hz",
    "scatter": "count²",
    "autocovariance": "count⁴",
    "acf": "dimensionless",
    "adev": "count²",
    "psd": "count⁴/Hz",
    "ratio": "dimensionless",
}


@dataclass(frozen=True)
class FigureContract:
    key: str
    x_title: str
    y_title: str
    requires_colorbar: bool = False
    colorbar_title: str = ""


FIGURE_CONTRACTS = (
    FigureContract("time_adu_histogram", "post-DDC I/Q sample value (ADU)", "Probability per ADU code"),
    FigureContract("allan_population", "Averaging time τ (s)", "Measured ADEV / ENBW white-noise expectation"),
    FigureContract("allan_examples", "Averaging time τ (s)", "Fractional Allan deviation ADEV / mean power"),
    FigureContract("integration_story", "Integration time τ (s)", "Fractional scatter of integrated power"),
    FigureContract("acf_story", "Lag (s)", "ACF after removing the constant mean"),
    FigureContract("global_bandpass", "RF frequency (MHz); top axis: global_bin", "Mean power (count²/PFB channel)"),
    FigureContract("global_sigma_ratio", "RF frequency (MHz); top axis: global_bin", "ADC", True, "σ(15 s) / σ_ENBW"),
    FigureContract("global_reproducibility", "RF frequency (MHz); top axis: global_bin", "ADC", True, "Between-scan fractional std"),
    FigureContract("bandpass", "RF frequency (MHz); top axis: global_bin", "Mean power (count²/PFB channel)"),
    FigureContract("power_density", "RF frequency (MHz); top axis: global_bin", "Power density (count²/Hz)"),
    FigureContract("dynamic", "RF frequency (MHz); top axis: global_bin", "Elapsed time (s)", True, "10 log₁₀(P/[1 count²/channel])"),
    FigureContract("sigma_tau", "Integration time τ (s)", "Absolute scatter σ_P(τ) (count²)"),
    FigureContract("sigma_frequency_tau", "RF frequency (MHz); top axis: global_bin", "Integration time τ (s)", True, "σ_P(τ) (count²)"),
    FigureContract("sigma_ratio_frequency_tau", "RF frequency (MHz); top axis: global_bin", "Integration time τ (s)", True, "Measured σ / ENBW theory"),
    FigureContract("acf_frequency_lag", "RF frequency (MHz); top axis: global_bin", "Lag (s)", True, "ACF (dimensionless)"),
    FigureContract("adev_frequency_tau", "RF frequency (MHz); top axis: global_bin", "Averaging time τ (s)", True, "ADEV (count²)"),
    FigureContract("acf_bin", "Lag (s)", "Correlation / normalized second moment"),
    FigureContract("adev_bin", "Averaging time τ (s)", "ADEV (count²)"),
    FigureContract("psd_bin", "Temporal frequency (Hz)", "PSD (count⁴/Hz)"),
    FigureContract("native_bin", "Elapsed time in registered 15 s window (s)", "Mean power (count²/PFB channel)"),
    FigureContract("distribution", "Mean power (count²/PFB channel)", "Bucket count"),
)


DATA_DICTIONARY = (
    ("scan_label", "扫描标识", "identity", "A/B/C", "三次独立900 s SPEC扫描"),
    ("adc_id", "ADC通道", "identity", "integer", "0..7的物理ADC路径"),
    ("global_bin", "全局频点", "identity", "integer", "生产F-engine 0..4095通道号"),
    ("rf_hz", "RF频率", "identity", "Hz", "f_center + signed_bin × 78.125 kHz"),
    ("mean_power_count2", "平均自相关功率", "power", UNITS["power"], "全900 s按有效谱帧数加权的mean(|X|²)"),
    ("power_density_count2_per_hz", "仪器功率谱密度", "power", UNITS["power_density"], "mean power除以PFB ENBW"),
    ("native_std_power_count2", "10 ms原生桶散布", "integration", UNITS["scatter"], "全90,000个10 ms桶的样本标准差"),
    ("integration_std_count2", "科学积分散布", "integration", UNITS["scatter"], "2/4/15/30 s非重叠积分的样本标准差"),
    ("sigma_theory_enbw_count2", "ENBW白噪声参考", "theory", UNITS["scatter"], "按有效噪声带宽预测的散布"),
    ("sigma_pfb_model_count2", "精确PFB白噪声参考", "theory", UNITS["scatter"], "包含8-tap PFB重叠相关的位精确模型"),
    ("sigma_short_cov_count2", "短滞后协方差参考", "theory", UNITS["scatter"], "使用10 ms实测短滞后自协方差"),
    ("sigma_over_theory", "实测/理论散布", "theory", UNITS["ratio"], "积分实测散布除以ENBW白噪声参考"),
    ("spectral_kurtosis", "Spectral kurtosis", "distribution", UNITS["ratio"], "frame-level功率二阶矩推导的SK"),
    ("temperature_r2", "PL温度线性解释度", "temperature", UNITS["ratio"], "单变量PL温度线性回归R²"),
    ("between_scan_fractional_std", "扫描间分数散布", "reproducibility", UNITS["ratio"], "A/B/C平均功率的sample std / mean"),
)


def dictionary_for_columns(columns: list[str] | tuple[str, ...]) -> tuple[tuple[str, str, str, str, str], ...]:
    """Return a non-empty Chinese/unit/definition entry for every exported column."""
    known = {row[0]: row[1:] for row in DATA_DICTIONARY}
    known.update({
        "acf_first_nonpositive_s": ("ACF首次非正滞后", "ACF/Allan", "s", "constant-removed ACF首次小于或等于零的滞后"),
        "short_positive_tau_integrated_s": ("短正相关积分时间", "ACF/Allan", "s", "短滞后正自相关积分得到的相关时间"),
        "bootstrap_block_s": ("bootstrap块长", "integration", "s", "circular block bootstrap使用的块时长"),
    })
    rows = []
    for field in columns:
        if field in known:
            zh, group, unit, definition = known[field]
        elif field in {"scan", "scan_id", "scan_label", "block", "adc_id", "global_bin", "rf_hz"}:
            zh, group, unit, definition = field, "identity", "identifier" if field != "rf_hz" else "Hz", "观测、通道或频率身份字段"
        elif "temperature" in field:
            zh, group = "温度回归指标", "temperature"
            unit = "dimensionless" if field.endswith("r2") else ("count²/°C" if "beta" in field else "°C")
            definition = "PL温度单变量即时线性回归的参数或诊断量"
        elif "spectral_kurtosis" in field or "kurtosis" in field:
            zh, group, unit, definition = "谱峰度指标", "distribution", "dimensionless", "由功率矩计算的分布形状指标"
        elif "sigma_over" in field or "_ratio" in field or field.endswith("ratio") or "slope" in field:
            zh, group, unit, definition = "理论比值或局部缩放斜率", "theory", "dimensionless", "实测与参考的比值，或相邻积分尺度的对数斜率"
        elif "integration" in field or field.startswith("native_std") or "mad" in field or "bootstrap" in field:
            zh, group, unit, definition = "积分统计量", "integration", "count²", "指定积分时间的均值、散布、MAD或bootstrap置信区间"
        elif "sigma_theory" in field or "sigma_pfb" in field or "sigma_short" in field:
            zh, group, unit, definition = "白噪声或短协方差参考", "theory", "count²", "按ENBW、精确PFB或实测短滞后协方差计算的参考散布"
        elif "power_density" in field:
            zh, group, unit, definition = "仪器功率谱密度", "power", "count²/Hz", "F-engine自相关功率除以PFB等效噪声带宽"
        elif "power" in field or "count2" in field:
            zh, group, unit, definition = "F-engine功率量", "power", "count²/PFB channel", "由未定标F-engine复数计数计算的功率统计量"
        elif any(token in field for token in ("drop", "gap", "duplicate", "reorder", "valid", "quality")):
            zh, group, unit, definition = "数据质量字段", "quality", "count or flag", "完整性计数、有效性或质量诊断"
        else:
            zh, group, unit, definition = "分析辅助字段", "quality", "as recorded", "权威Parquet中保留的分析配置或诊断字段"
        rows.append((field, zh, group, unit, definition))
    return tuple(rows)


def validate_figure_contracts() -> None:
    keys: set[str] = set()
    for contract in FIGURE_CONTRACTS:
        if contract.key in keys:
            raise ValueError(f"duplicate figure contract {contract.key}")
        keys.add(contract.key)
        if not contract.x_title or not contract.y_title:
            raise ValueError(f"missing axis title for {contract.key}")
        if contract.requires_colorbar and not contract.colorbar_title:
            raise ValueError(f"missing colorbar title for {contract.key}")


validate_figure_contracts()
