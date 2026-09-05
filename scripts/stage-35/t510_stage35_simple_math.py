#!/usr/bin/env python3
"""Frozen, human-report mathematics for the Stage 35 simple explorer.

The functions in this file deliberately return the intermediate counts used
by the UI.  A plotted Allan point must be explainable as N base buckets,
window width m, K adjacent-window comparisons, and one explicit sum.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import numpy as np


def _validated(values: np.ndarray, weights: np.ndarray | None) -> tuple[np.ndarray, np.ndarray]:
    data = np.asarray(values)
    if data.ndim != 1 or data.size < 2:
        raise ValueError("values must be a one-dimensional series with at least two points")
    if not np.all(np.isfinite(data.real)) or not np.all(np.isfinite(data.imag)):
        raise ValueError("values contain non-finite samples")
    if weights is None:
        weight = np.ones(data.size, dtype=np.float64)
    else:
        weight = np.asarray(weights, dtype=np.float64)
        if weight.shape != data.shape or not np.all(np.isfinite(weight)) or np.any(weight <= 0):
            raise ValueError("weights must be finite, positive, and match values")
    return data, weight


def weighted_windows(values: np.ndarray, weights: np.ndarray, width: int) -> np.ndarray:
    """Return every overlapping, exactly weighted window mean."""
    if width < 1 or width > len(values):
        raise ValueError("window width is outside the series")
    weighted = values * weights
    cumulative = np.concatenate((np.zeros(1, dtype=weighted.dtype), np.cumsum(weighted)))
    cumulative_weight = np.concatenate(([0.0], np.cumsum(weights)))
    sums = cumulative[width:] - cumulative[:-width]
    counts = cumulative_weight[width:] - cumulative_weight[:-width]
    return sums / counts


def overlapping_allan(
    values: np.ndarray,
    bucket_seconds: float,
    taus: Iterable[float],
    weights: np.ndarray | None = None,
) -> list[dict[str, Any]]:
    """Allan variance and its square root for real or complex scalar data.

    Each starting index supplies two immediately adjacent windows of width m.
    Starting indices advance by one base bucket, hence the estimator is the
    overlapping form.  Complex input uses |delta|^2 and is phase-wrap safe.
    """
    if not np.isfinite(bucket_seconds) or bucket_seconds <= 0:
        raise ValueError("bucket_seconds must be positive")
    data, weight = _validated(values, weights)
    output: list[dict[str, Any]] = []
    for requested_tau in taus:
        width = int(round(float(requested_tau) / bucket_seconds))
        if width < 1 or not np.isclose(width * bucket_seconds, requested_tau, rtol=0, atol=1e-12):
            raise ValueError(f"tau {requested_tau} is not an integer multiple of the base bucket")
        comparisons = data.size - 2 * width + 1
        if comparisons < 1:
            continue
        means = weighted_windows(data, weight, width)
        delta = means[width:] - means[:-width]
        squared = np.abs(delta) ** 2
        sum_squared = float(np.sum(squared, dtype=np.float64))
        variance = sum_squared / (2.0 * comparisons)
        output.append({
            "tau_s": float(requested_tau),
            "base_bucket_s": float(bucket_seconds),
            "N": int(data.size),
            "m": int(width),
            "K": int(comparisons),
            "sum_squared_difference": sum_squared,
            "variance": float(variance),
            "square_root": float(np.sqrt(variance)),
        })
    return output


def overlapping_allan_visibility(
    visibility: np.ndarray,
    auto_left: np.ndarray,
    auto_right: np.ndarray,
    weights: np.ndarray,
    bucket_seconds: float,
    taus: Iterable[float],
    *,
    relative_percent: bool,
) -> list[dict[str, Any]]:
    """Phase-wrap-safe Allan statistic of complex visibility windows.

    Relative mode normalizes *after* each integration window is formed:
    100 Vbar/sqrt(Pabar P bbar).  It never averages already-biased magnitudes.
    """
    vis, weight = _validated(np.asarray(visibility, dtype=np.complex128), weights)
    left, _ = _validated(np.asarray(auto_left, dtype=np.float64), weight)
    right, _ = _validated(np.asarray(auto_right, dtype=np.float64), weight)
    if vis.shape != left.shape or vis.shape != right.shape:
        raise ValueError("visibility and auto-power arrays must match")
    if np.any(left <= 0) or np.any(right <= 0):
        raise ValueError("auto powers must be positive")
    output: list[dict[str, Any]] = []
    for requested_tau in taus:
        width = int(round(float(requested_tau) / bucket_seconds))
        if width < 1 or not np.isclose(width * bucket_seconds, requested_tau, rtol=0, atol=1e-12):
            raise ValueError(f"tau {requested_tau} is not an integer multiple of the base bucket")
        comparisons = vis.size - 2 * width + 1
        if comparisons < 1:
            continue
        vbar = weighted_windows(vis, weight, width)
        if relative_percent:
            pleft = weighted_windows(left, weight, width)
            pright = weighted_windows(right, weight, width)
            y = 100.0 * vbar / np.sqrt(pleft * pright)
        else:
            y = vbar
        delta = y[width:] - y[:-width]
        squared = np.abs(delta) ** 2
        sum_squared = float(np.sum(squared, dtype=np.float64))
        variance = sum_squared / (2.0 * comparisons)
        output.append({
            "tau_s": float(requested_tau),
            "base_bucket_s": float(bucket_seconds),
            "N": int(vis.size),
            "m": int(width),
            "K": int(comparisons),
            "sum_squared_difference": sum_squared,
            "variance": float(variance),
            "square_root": float(np.sqrt(variance)),
        })
    return output


def white_noise_reference(points: list[dict[str, Any]], form: str) -> list[float]:
    """Anchor the explanatory white-noise line to the first measured point."""
    if not points:
        return []
    if form not in ("variance", "square_root"):
        raise ValueError("form must be variance or square_root")
    tau0 = float(points[0]["tau_s"])
    value0 = float(points[0][form])
    exponent = 1.0 if form == "variance" else 0.5
    return [value0 * (tau0 / float(point["tau_s"])) ** exponent for point in points]


def aggregate_frames(values: np.ndarray, width: int) -> np.ndarray:
    """Non-overlapping display averages; incomplete tail is intentionally dropped."""
    data = np.asarray(values)
    if width < 1:
        raise ValueError("width must be positive")
    count = len(data) // width
    if count < 1:
        raise ValueError("width exceeds the series")
    return data[: count * width].reshape((count, width) + data.shape[1:]).mean(axis=1)
