#!/usr/bin/env python3
"""Independently recompute the human-facing Stage 35 v2 science story."""

from __future__ import annotations

import argparse
import base64
import csv
import gzip
import json
import math
import re
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

import t510_stage35_report_v2_core as core
import t510_stage35_s2_html_report_v2 as report_v2


PAYLOAD = re.compile(
    rb'^<script type="application/octet-stream" id="payload-([A-Za-z0-9._-]+)">([A-Za-z0-9+/=]+)</script>\s*$'
)


def selected_payloads(path: Path, wanted: set[str]) -> dict[str, bytes]:
    result: dict[str, bytes] = {}
    with path.open("rb") as stream:
        for line in stream:
            match = PAYLOAD.match(line)
            if match and match.group(1).decode("ascii") in wanted:
                name = match.group(1).decode("ascii")
                result[name] = gzip.decompress(base64.b64decode(match.group(2), validate=True))
                if result.keys() == wanted:
                    break
    missing = wanted - result.keys()
    if missing:
        raise RuntimeError(f"missing selected payloads: {sorted(missing)}")
    return result


def compare_array(
    errors: list[str], label: str, actual: object, expected: object,
    *, rtol: float = 1e-12, atol: float = 0.0,
) -> None:
    a = np.asarray(actual)
    e = np.asarray(expected)
    if a.shape != e.shape or not np.allclose(a, e, rtol=rtol, atol=atol, equal_nan=False):
        errors.append(f"{label} mismatch: actual shape {a.shape}, expected shape {e.shape}")


def curve_quantiles(values: np.ndarray) -> dict[str, np.ndarray]:
    finite = values[np.all(np.isfinite(values), axis=-1)]
    result = np.quantile(finite, (0.05, 0.5, 0.95), axis=0)
    return {"p05": result[0], "median": result[1], "p95": result[2]}


def histogram_quantiles(counts: dict[int, int], probabilities: tuple[float, ...]) -> list[int]:
    ordered = sorted(counts.items())
    total = sum(value for _, value in ordered)
    result = []
    for probability in probabilities:
        target = probability * (total - 1)
        cumulative = 0
        for code, count in ordered:
            if cumulative + count > target:
                result.append(code)
                break
            cumulative += count
        else:
            raise RuntimeError("histogram quantile overflow")
    return result


def verify_histograms(
    config: dict[str, object], analysis_root: Path, actual: dict[str, object],
    story: dict[str, object], errors: list[str],
) -> dict[str, object]:
    counts = {(adc, component): {} for adc in range(8) for component in ("I", "Q")}
    source_checks = []
    for source in config["time_histograms"]:  # type: ignore[index]
        path = Path(source["path"])
        digest = report_v2.sha256_file(path)
        if digest != source["sha256"]:
            errors.append(f"TIME histogram SHA mismatch: {path}")
        rows = 0
        with path.open(newline="", encoding="utf-8") as stream:
            for row in csv.DictReader(stream):
                key = (int(row["lane"]), row["component"])
                code = int(row["code"])
                count = int(row["count"])
                counts[key][code] = counts[key].get(code, 0) + count
                rows += 1
        source_checks.append({"label": source["label"], "sha256": digest, "rows": rows})

    metric_rows = pq.read_table(analysis_root / "time_control_metrics.parquet").to_pylist()
    actual_adcs = actual["adcs"]  # type: ignore[index]
    story_adcs = story["adu"]["adcs"]  # type: ignore[index]
    probabilities = (0.001, 0.025, 0.16, 0.5, 0.84, 0.975, 0.999)
    for adc in range(8):
        row = actual_adcs[adc]
        metadata_row = story_adcs[adc]
        code_min = min(min(counts[(adc, component)]) for component in ("I", "Q"))
        code_max = max(max(counts[(adc, component)]) for component in ("I", "Q"))
        codes = list(range(code_min, code_max + 1))
        combined = [sum(counts[(adc, component)].get(code, 0) for component in ("I", "Q")) for code in codes]
        if row["codes"] != codes or row["counts"] != combined:
            errors.append(f"ADC{adc} combined ADU code counts differ from six histogram CSVs")
        for component in ("I", "Q"):
            expected_counts = [counts[(adc, component)].get(code, 0) for code in codes]
            if row["component_counts"][component] != expected_counts:
                errors.append(f"ADC{adc} {component} ADU code counts differ from six histogram CSVs")
            samples = sum(expected_counts)
            if samples != 96_000_000:
                errors.append(f"ADC{adc} {component} sample count {samples} != 96000000")
            q = histogram_quantiles(counts[(adc, component)], probabilities)
            component_summary = metadata_row["components"][component]
            expected_summary = {
                "samples": samples, "minimum_50ms": min(counts[(adc, component)]),
                "maximum_50ms": max(counts[(adc, component)]), "q001": q[0],
                "q025": q[1], "q16": q[2], "median": q[3], "q84": q[4],
                "q975": q[5], "q999": q[6],
            }
            if component_summary != expected_summary:
                errors.append(f"ADC{adc} {component} ADU summary mismatch")
        adc_metrics = [item for item in metric_rows if int(item["adc_id"]) == adc]
        expected_min = min(min(int(item["min_i_adu"]), int(item["min_q_adu"])) for item in adc_metrics)
        expected_max = max(max(int(item["max_i_adu"]), int(item["max_q_adu"])) for item in adc_metrics)
        expected_clips = sum(int(item["clip_i"]) + int(item["clip_q"]) for item in adc_metrics)
        if (metadata_row["minimum_30s"], metadata_row["maximum_30s"], metadata_row["clip_count"]) != (
            expected_min, expected_max, expected_clips
        ):
            errors.append(f"ADC{adc} 30 s extremes or clipping mismatch")
    return {"sources": source_checks, "adcs": 8, "samples_per_adc_component": 96_000_000}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--analysis-root", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.report.with_suffix(args.report.suffix + ".manifest.json").read_text())
    config = json.loads(args.config.read_text(encoding="utf-8"))
    story = manifest["science_story"]
    native_names = {f"native15-{scan}-0-f32" for scan in report_v2.SCAN_LABELS}
    wanted = {"quick-f64", "cross-f64", "rf-hz-f64", "frequency-order-i32", "adu-hist-json"} | native_names
    raw = selected_payloads(args.report, wanted)
    quick = np.frombuffer(raw["quick-f64"], dtype="<f8").reshape(3, 8, 4096, len(report_v2.QUICK_FIELDS))
    cross = np.frombuffer(raw["cross-f64"], dtype="<f8").reshape(8, 4096, len(report_v2.CROSS_FIELDS))
    rf = np.frombuffer(raw["rf-hz-f64"], dtype="<f8")
    order = np.frombuffer(raw["frequency-order-i32"], dtype="<i4")
    reference_quick, reference_cross, reference_rf = report_v2.load_quick(args.analysis_root)
    errors: list[str] = []
    if not np.array_equal(quick, reference_quick):
        errors.append("quick float64 payload differs from Parquet")
    if not np.array_equal(cross, reference_cross):
        errors.append("cross-scan float64 payload differs from Parquet")
    if not np.array_equal(rf, reference_rf):
        errors.append("RF float64 payload differs from Parquet")
    expected_order = np.asarray(core.ascending_global_bins(), dtype="<i4")
    if not np.array_equal(order, expected_order):
        errors.append("frequency order differs from frozen mapping")

    # Re-read all twelve Allan scales directly from the authoritative Parquet.
    adev = np.empty((3, 8, 4096, len(report_v2.ALLAN_SECONDS)), dtype=np.float64)
    acf_adc0 = np.empty((3, 4096, len(report_v2.ACF_LAGS)), dtype=np.float64)
    for scan_index, scan in enumerate(report_v2.SCAN_LABELS):
        for block in range(report_v2.BLOCK_COUNT):
            table = report_v2.table_sorted(args.analysis_root, "temporal_metrics", scan, block)
            overlap = report_v2.list_matrix(table["adev_overlap_raw_count2"], len(report_v2.ALLAN_SECONDS))
            sl = slice(block * report_v2.BLOCK_BINS, (block + 1) * report_v2.BLOCK_BINS)
            adev[scan_index, :, sl, :] = overlap.reshape(8, report_v2.BLOCK_BINS, len(report_v2.ALLAN_SECONDS))
            acf = report_v2.list_matrix(table["acf_constant_removed"], len(report_v2.ACF_LAGS))
            acf_adc0[scan_index, sl, :] = acf[:report_v2.BLOCK_BINS]

    qi = {name: index for index, name in enumerate(report_v2.QUICK_FIELDS)}
    ci = {name: index for index, name in enumerate(report_v2.CROSS_FIELDS)}
    mean = reference_quick[..., qi["mean_power_count2"]]
    white_allan = np.asarray([1.0 / math.sqrt(core.ENBW_HZ * tau) for tau in report_v2.ALLAN_SECONDS])
    allan_ratio = adev / (mean[..., None] * white_allan)
    eligible = np.ones(4096, dtype=bool)
    eligible[list(core.preflagged_bins())] = False
    for population, values in (
        ("all_bins", allan_ratio.reshape(-1, len(report_v2.ALLAN_SECONDS))),
        ("preflagged_excluded", allan_ratio[:, :, eligible, :].reshape(-1, len(report_v2.ALLAN_SECONDS))),
    ):
        expected = curve_quantiles(values)
        for quantile in ("p05", "median", "p95"):
            compare_array(errors, f"Allan {population} {quantile} all 12 tau", story["allan_population"][population][quantile], expected[quantile])
    compare_array(errors, "Allan white tau^-1/2 reference", story["white_fractional_allan"], white_allan)

    expected_presets = {}
    for adc in range(8):
        sigma = np.median(reference_quick[:, adc, :, qi["sigma_ratio_15s"]], axis=0)
        acf = np.median(np.abs(reference_quick[:, adc, :, qi["acf_constant_removed_1s"]]), axis=0)
        repro = reference_cross[adc, :, ci["between_scan_fractional_std"]]
        rows = np.column_stack((np.log(sigma), acf, repro))
        representative = core.representative_bin(rows.tolist(), eligible.tolist())
        candidates = np.flatnonzero(eligible)
        expected_presets[str(adc)] = {
            "representative": representative,
            "worst_integration": int(candidates[np.argmax(sigma[candidates])]),
            "strongest_memory": int(candidates[np.argmax(acf[candidates])]),
            "fixed_960mhz": 3328,
        }
    if story["adc_presets"] != expected_presets:
        errors.append("deterministic ADC shortcut presets mismatch")
    named_bins = (expected_presets["0"]["representative"], 3182, 3328)
    for row, global_bin in zip(story["allan_examples"], named_bins, strict=True):
        expected = adev[:, 0, global_bin, :] / mean[:, 0, global_bin, None]
        if row["global_bin"] != global_bin:
            errors.append(f"named Allan example bin mismatch: {row['global_bin']} != {global_bin}")
        compare_array(errors, f"Allan example bin {global_bin} scans", row["scan_fractional_adev"], expected)
        compare_array(errors, f"Allan example bin {global_bin} median", row["median_fractional_adev"], np.median(expected, axis=0))
    for row, global_bin in zip(story["acf_examples"], named_bins, strict=True):
        compare_array(errors, f"ACF example bin {global_bin}", row["scan_acf"], acf_adc0[:, global_bin, :])

    integration_fractional = np.empty((3, 8, 4096, 4), dtype=np.float64)
    integration_ratio = np.empty_like(integration_fractional)
    for index, tau in enumerate(report_v2.TAU_SECONDS):
        integration_fractional[..., index] = reference_quick[..., qi[f"integration_std_{tau:g}s"]] / mean
        integration_ratio[..., index] = reference_quick[..., qi[f"sigma_ratio_{tau:g}s"]]
    for label, values in (("measured_fractional", integration_fractional), ("measured_over_white", integration_ratio)):
        expected = curve_quantiles(values.reshape(-1, 4))
        for quantile in ("p05", "median", "p95"):
            compare_array(errors, f"integration {label} {quantile} at 2/4/15/30 s", story["integration"][label][quantile], expected[quantile])
    paired_gain = integration_fractional[..., 0] / integration_fractional[..., -1]
    expected_gain = np.quantile(paired_gain, (0.05, 0.5, 0.95))
    compare_array(errors, "paired 2 s to 30 s gain", [
        story["integration"]["paired_gain_2s_to_30s"][key] for key in ("p05", "median", "p95")
    ], expected_gain)

    ratio_15 = float(np.median(integration_ratio[..., 2]))
    headline_expected = {
        "ratio_15s": ratio_15,
        "ratio_15s_preflagged_excluded": float(np.median(integration_ratio[:, :, eligible, 2])),
        "ideal_fractional_15s_percent": 100 / math.sqrt(core.ENBW_HZ * 15),
        "measured_fractional_15s_percent": 100 * float(np.median(integration_fractional[..., 2])),
        "equivalent_white_time_15s": 15 / ratio_15**2,
        "radiometer_efficiency_15s": 1 / ratio_15**2,
        "white_time_penalty_15s": ratio_15**2,
        "ratio_30s": float(np.median(integration_ratio[..., 3])),
        "paired_gain_2s_to_30s": float(np.median(paired_gain)),
        "ideal_gain_2s_to_30s": math.sqrt(15),
        "acf_1s_median_abs": float(np.median(np.abs(reference_quick[..., qi["acf_constant_removed_1s"]]))),
        "acf_1s_p95_abs": float(np.quantile(np.abs(reference_quick[..., qi["acf_constant_removed_1s"]]), 0.95)),
        "temperature_r2_median": float(np.median(reference_quick[..., qi["temperature_r2"]])),
    }
    for key, expected in headline_expected.items():
        if not math.isclose(float(story["headline"][key]), expected, rel_tol=1e-12, abs_tol=0.0):
            errors.append(f"headline {key} mismatch")

    analysis_config = report_v2.load_json(args.analysis_root / "analysis_config.json")
    scan_roots = {item["label"]: Path(item["path"]) for item in analysis_config["scans"]}
    native_checks = {}
    manifest_payload = {item["name"]: item for item in manifest["payloads"]}
    for scan in report_v2.SCAN_LABELS:
        name = f"native15-{scan}-0-f32"
        actual_native = np.frombuffer(raw[name], dtype="<f4").reshape(4096, 1500)
        expected_native, conversion_error = report_v2.load_native_window(scan_roots[scan], 0)
        if not np.array_equal(actual_native, expected_native):
            errors.append(f"{name} differs from the registered Zarr window")
        ledger = manifest_payload[name]
        for key, value in conversion_error.items():
            if abs(float(ledger[key]) - value) > max(1e-15, abs(value) * 1e-12):
                errors.append(f"{name} conversion ledger mismatch for {key}")
        native_checks[scan] = conversion_error

    histogram_checks = verify_histograms(
        config, args.analysis_root, json.loads(raw["adu-hist-json"]), story, errors
    )
    spots = []
    for adc in (0, 7):
        for global_bin in (0, 100, 2048, 3182, 3328, 4095):
            spots.append({
                "adc_id": adc, "global_bin": global_bin, "rf_mhz": float(rf[global_bin] / 1e6),
                "mean_power_a_count2": float(quick[0, adc, global_bin, qi["mean_power_count2"]]),
                "sigma_ratio_15s_a": float(quick[0, adc, global_bin, qi["sigma_ratio_15s"]]),
                "acf_1s_a": float(quick[0, adc, global_bin, qi["acf_constant_removed_1s"]]),
            })
    result = {
        "format": "T510_STAGE35_S2_NUMERIC_VERIFICATION_V2", "status": "PASS" if not errors else "FAIL",
        "parquet_full_float64_arrays_equal": not any("Parquet" in error for error in errors),
        "zarr_registered_windows_equal": not any("Zarr" in error for error in errors),
        "allan_tau_seconds_verified": list(report_v2.ALLAN_SECONDS),
        "integration_seconds_verified": list(report_v2.TAU_SECONDS),
        "named_frequency_bins_verified": list(named_bins),
        "adc_presets": expected_presets, "histograms": histogram_checks,
        "spot_checks": spots, "native_float32_conversion": native_checks, "errors": errors,
    }
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
