"""Stage 34a astronomy-performance calculations with no hardware side effects."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
import math
import statistics
from typing import Any


NCHAN = 4096
NINPUT = 8
ADC_FIXED_SPURS_MHZ = (480.0, 960.0, 1440.0)
ADC_WATCHLIST_MHZ = (160.0, 1120.0, 1280.0, 1600.0)
BAD_BIN_RADIUS = 4
INTEGRATION_TAUS_SECONDS = (1, 2, 4, 8, 16, 32, 64, 128)
FULL_SCALE_POWER = 32768.0**2


def rf_to_signed_bin(rf_mhz: float, center_mhz: float, sample_rate_msps: int) -> int:
    """Map an exact RF frequency to the signed FFT/PFB bin used by the product."""
    if sample_rate_msps not in (160, 320):
        raise ValueError("sample_rate_msps must be 160 or 320")
    exact = (float(rf_mhz) - float(center_mhz)) / (sample_rate_msps / NCHAN)
    selected = round(exact)
    if abs(exact - selected) > 1.0e-6:
        raise ValueError("RF frequency is not on an exact PFB bin")
    if not -NCHAN // 2 <= selected < NCHAN // 2:
        raise ValueError("RF frequency is outside the selected Nyquist window")
    return selected


def signed_bin_to_index(signed_bin: int) -> int:
    if not -NCHAN // 2 <= int(signed_bin) < NCHAN // 2:
        raise ValueError("signed bin must be in -2048..2047")
    return int(signed_bin) % NCHAN


def mean_power_from_accumulator(row: dict[str, Any]) -> float:
    count = int(row.get("sample_count", 0))
    if count <= 0:
        raise ValueError("power accumulator has no samples")
    return float(row["sum_power"]) / count


def power_dbfs(mean_power: float) -> float:
    return 10.0 * math.log10(max(float(mean_power), 1.0e-300) / FULL_SCALE_POWER)


def nonoverlapping_means(values: Sequence[float], width: int) -> list[float]:
    if width <= 0:
        raise ValueError("averaging width must be positive")
    return [
        statistics.fmean(values[offset : offset + width])
        for offset in range(0, len(values) - width + 1, width)
    ]


def allan_deviation(values: Sequence[float], width: int) -> float | None:
    means = nonoverlapping_means(values, width)
    if len(means) < 2:
        return None
    scale = abs(statistics.fmean(values))
    if scale <= 0.0:
        return None
    return math.sqrt(
        0.5
        * statistics.fmean(
            (right - left) ** 2 for left, right in zip(means, means[1:])
        )
    ) / scale


def linear_regression_slope(points: Sequence[tuple[float, float]]) -> float:
    valid = [(x, y) for x, y in points if x > 0.0 and y > 0.0]
    if len(valid) < 2:
        raise ValueError("at least two positive points are required")
    xs = [math.log10(x) for x, _ in valid]
    ys = [math.log10(y) for _, y in valid]
    x_mean = statistics.fmean(xs)
    y_mean = statistics.fmean(ys)
    denominator = sum((x - x_mean) ** 2 for x in xs)
    if denominator == 0.0:
        raise ValueError("regression x values have no span")
    return sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys)) / denominator


def integration_statistics(
    values: Sequence[float], taus: Iterable[int] = INTEGRATION_TAUS_SECONDS
) -> dict[str, Any]:
    """Return fractional radiometer scatter and Allan deviation versus tau."""
    if len(values) < 4 or any(not math.isfinite(value) or value < 0.0 for value in values):
        raise ValueError("integration input must contain at least four finite powers")
    overall = statistics.fmean(values)
    if overall <= 0.0:
        raise ValueError("integration input mean power must be positive")
    rows: list[dict[str, Any]] = []
    slope_points: list[tuple[float, float]] = []
    for tau in taus:
        means = nonoverlapping_means(values, int(tau))
        scatter = (
            statistics.stdev(means) / overall if len(means) >= 2 else None
        )
        allan = allan_deviation(values, int(tau))
        rows.append(
            {
                "tau_seconds": int(tau),
                "group_count": len(means),
                "fractional_stddev": scatter,
                "allan_deviation": allan,
            }
        )
        if scatter is not None and len(means) >= 4:
            slope_points.append((float(tau), scatter))
    return {
        "mean_power": overall,
        "mean_dbfs": power_dbfs(overall),
        "slope": linear_regression_slope(slope_points),
        "curve": rows,
    }


def coherence_from_accumulators(rows: Sequence[dict[str, Any]]) -> dict[str, float]:
    count = sum(int(row.get("sample_count", 0)) for row in rows)
    cross_re = sum(float(row.get("sum_cross_re", 0.0)) for row in rows)
    cross_im = sum(float(row.get("sum_cross_im", 0.0)) for row in rows)
    power_a = sum(float(row.get("sum_power_a", 0.0)) for row in rows)
    power_b = sum(float(row.get("sum_power_b", 0.0)) for row in rows)
    denominator = math.sqrt(max(power_a * power_b, 0.0))
    coherence = math.hypot(cross_re, cross_im) / denominator if denominator else 0.0
    phase_deg = math.degrees(math.atan2(cross_im, cross_re))
    return {
        "sample_count": float(count),
        "coherence": min(max(coherence, 0.0), 1.0),
        "phase_deg": phase_deg,
    }


def nearest_named_frequency(
    rf_mhz: float, named: Sequence[float], bin_width_mhz: float
) -> float | None:
    return next(
        (
            frequency
            for frequency in named
            if abs(float(rf_mhz) - frequency) <= bin_width_mhz / 2.0 + 1.0e-12
        ),
        None,
    )


def classify_spur(
    *,
    rf_mhz: float,
    prominence_db: float,
    reproduced: bool,
    bin_width_mhz: float,
    context: str,
    dac_signature_match: bool = False,
    tg_signature_match: bool = False,
) -> dict[str, Any]:
    """Classify without deleting the raw peak or granting cross-context exemptions."""
    fixed = nearest_named_frequency(rf_mhz, ADC_FIXED_SPURS_MHZ, bin_width_mhz)
    watch = nearest_named_frequency(rf_mhz, ADC_WATCHLIST_MHZ, bin_width_mhz)
    if fixed is not None:
        classification = "ADC_FIXED_BAD_BIN"
        exclude_science_summary = True
    elif watch is not None:
        classification = "ADC_WATCHLIST"
        exclude_science_summary = False
    elif context == "dac_loopback" and dac_signature_match:
        classification = "SOURCE_LIMITED_DAC"
        exclude_science_summary = True
    elif context == "tg" and tg_signature_match:
        classification = "SOURCE_LIMITED"
        exclude_science_summary = True
    elif not reproduced:
        classification = "SINGLE_WINDOW_CANDIDATE"
        exclude_science_summary = False
    elif prominence_db >= 12.0:
        classification = "ASTRONOMY_REVIEW_REQUIRED"
        exclude_science_summary = False
    elif prominence_db >= 6.0:
        classification = "WARNING"
        exclude_science_summary = False
    else:
        classification = "BELOW_REPORT_THRESHOLD"
        exclude_science_summary = False
    return {
        "rf_mhz": float(rf_mhz),
        "prominence_db": float(prominence_db),
        "reproduced": bool(reproduced),
        "context": context,
        "classification": classification,
        "exclude_science_summary": exclude_science_summary,
        "matched_frequency_mhz": fixed if fixed is not None else watch,
    }


def science_bad_bins(sample_rate_msps: int = 160) -> list[dict[str, Any]]:
    bin_width_mhz = sample_rate_msps / NCHAN
    rows = []
    for frequency in ADC_FIXED_SPURS_MHZ:
        center_index = round(frequency / bin_width_mhz)
        rows.append(
            {
                "rf_mhz": frequency,
                "nearest_global_bin": center_index,
                "masked_global_bins": list(
                    range(center_index - BAD_BIN_RADIUS, center_index + BAD_BIN_RADIUS + 1)
                ),
                "radius_bins": BAD_BIN_RADIUS,
                "classification": "ADC_FIXED_BAD_BIN",
            }
        )
    return rows


def stitch_overlapping_windows(
    windows: Sequence[dict[str, Any]], sample_rate_msps: int
) -> list[list[float]]:
    """Stitch dBFS spectra with a linear-power median in overlap regions."""
    if sample_rate_msps not in (160, 320):
        raise ValueError("sample_rate_msps must be 160 or 320")
    bin_width_mhz = sample_rate_msps / NCHAN
    full_bins = round(1920.0 / bin_width_mhz)
    stitched = [[-300.0] * full_bins for _ in range(NINPUT)]
    for global_bin in range(full_bins):
        rf_mhz = global_bin * bin_width_mhz
        observations: list[tuple[int, list[float]]] = []
        for window in windows:
            offset = round((rf_mhz - float(window["center_mhz"])) / bin_width_mhz)
            if not -NCHAN // 2 <= offset < NCHAN // 2:
                continue
            low_confidence_edge = rf_mhz < 40.0 or rf_mhz >= 1880.0
            if not low_confidence_edge and (abs(offset) < 13 or abs(offset) > 1536):
                continue
            index = offset % NCHAN
            observations.append(
                (
                    abs(offset),
                    [10.0 ** (float(window["power_dbfs"][lane][index]) / 10.0) for lane in range(NINPUT)],
                )
            )
        if not observations:
            # DC is deliberately avoided.  Where the preferred central regions
            # leave a seam, use the nearest non-DC observation from an overlap.
            for window in windows:
                offset = round((rf_mhz - float(window["center_mhz"])) / bin_width_mhz)
                if -NCHAN // 2 <= offset < NCHAN // 2 and abs(offset) >= 13:
                    index = offset % NCHAN
                    observations.append(
                        (
                            abs(offset),
                            [10.0 ** (float(window["power_dbfs"][lane][index]) / 10.0) for lane in range(NINPUT)],
                        )
                    )
        if not observations:
            continue
        best_distance = min(distance for distance, _ in observations)
        selected = [values for distance, values in observations if distance <= max(best_distance, 1536)]
        for lane in range(NINPUT):
            stitched[lane][global_bin] = 10.0 * math.log10(
                max(statistics.median(row[lane] for row in selected), 1.0e-300)
            )
    return stitched


def compare_noise_modes(
    spectrum_160: Sequence[Sequence[float]], spectrum_320: Sequence[Sequence[float]]
) -> list[dict[str, float | int]]:
    """Compare each 160 bin with the median of its two corresponding 320 bins."""
    rows = []
    for lane in range(NINPUT):
        deltas = []
        for index_160, value_160 in enumerate(spectrum_160[lane]):
            if value_160 <= -250.0:
                continue
            index_320 = min(round(index_160 / 2.0), len(spectrum_320[lane]) - 1)
            reference_320 = float(spectrum_320[lane][index_320])
            if reference_320 <= -250.0:
                continue
            rf_mhz = index_160 * 160.0 / NCHAN
            if any(abs(rf_mhz - spur) <= 4 * 160.0 / NCHAN for spur in ADC_FIXED_SPURS_MHZ):
                continue
            deltas.append(value_160 - reference_320)
        rows.append(
            {
                "lane": lane,
                "median_delta_db": statistics.median(deltas),
                "p10_delta_db": sorted(deltas)[round(0.1 * (len(deltas) - 1))],
                "p90_delta_db": sorted(deltas)[round(0.9 * (len(deltas) - 1))],
                "expected_delta_db": -3.01029995664,
            }
        )
    return rows
