#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from pathlib import Path
from typing import Any


EXPECTED_CORE_VERSION = 0x0001_0011


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _add_repo_python_path() -> None:
    sys.path.insert(0, str(_repo_root()))


def _parse_int(value: str) -> int:
    return int(value, 0)


def _jsonable(value: Any) -> Any:
    try:
        import numpy as np
    except ImportError:
        np = None  # type: ignore[assignment]
    if np is not None:
        if isinstance(value, np.ndarray):
            return value.tolist()
        if isinstance(value, np.generic):
            return value.item()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _write_output(path: str | None, result: dict[str, Any]) -> None:
    if not path:
        return
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(_jsonable(result), indent=2, sort_keys=True) + "\n")


def _wrap_phase_deg(value: float) -> float:
    while value > 180.0:
        value -= 360.0
    while value <= -180.0:
        value += 360.0
    return value


def _wait_streaming(core: Any, mask: int, timeout: float) -> dict[str, int]:
    deadline = time.monotonic() + float(timeout)
    status = core.read_status()
    while time.monotonic() < deadline:
        status = core.read_status()
        if status["streaming"] and (status["rfdc_current_valid_mask"] & mask) == mask:
            return status
        time.sleep(0.02)
    return status


def _preview_digest(preview: dict[str, Any], channel: int = 0) -> str:
    try:
        import numpy as np
    except ImportError:
        np = None  # type: ignore[assignment]
    iq = preview.get("iq", {}).get(channel)
    if iq is None:
        iq = preview.get("iq", {}).get(str(channel))
    if iq is None:
        return ""
    if np is not None:
        data = np.asarray(iq).tobytes()
    else:
        data = repr(iq).encode("ascii", errors="ignore")
    return hashlib.sha256(data).hexdigest()


def _default_dac_mhz(expected_mhz: float) -> float:
    candidate = float(expected_mhz) + 20.0
    if candidate <= 350.0:
        return candidate
    return max(50.0, float(expected_mhz) - 20.0)


def _scenario_names(value: str) -> list[str]:
    value = str(value).strip().lower()
    if value == "all":
        return ["external_direct_dac_off", "external_direct_dac_on", "adc_terminated_dac_on"]
    names = [item.strip() for item in value.split(",") if item.strip()]
    allowed = {"external_direct_dac_off", "external_direct_dac_on", "adc_terminated_dac_on"}
    for name in names:
        if name not in allowed:
            raise argparse.ArgumentTypeError(f"scenario must be one of {sorted(allowed)} or all")
    return names


def _build_condition(args: argparse.Namespace, scenario: str) -> dict[str, Any]:
    expected_hz = float(args.expected_mhz) * 1_000_000.0
    center_hz = float(args.center_mhz) * 1_000_000.0
    bw_hz = float(args.bw_mhz) * 1_000_000.0
    dac_mhz = float(args.dac_mhz) if args.dac_mhz is not None else _default_dac_mhz(float(args.expected_mhz))
    dac_hz = dac_mhz * 1_000_000.0
    if scenario == "external_direct_dac_off":
        return {
            "scenario": scenario,
            "physical_setup_required": "external 200 MHz source direct to ADC0; DAC0 disconnected or disabled",
            "input_source_mode": "external_adc_tone",
            "expected_signal_hz": expected_hz,
            "observe_center_hz": center_hz,
            "view_bw_hz": bw_hz,
            "dac_signal_hz": expected_hz,
            "dac_source_mode": "constant_phasor",
            "dac_amplitude": 0,
            "dac_enable_mask": 0x00,
        }
    if scenario == "external_direct_dac_on":
        return {
            "scenario": scenario,
            "physical_setup_required": "external source direct to ADC0; DAC0 enabled at a different frequency and not connected to ADC0",
            "input_source_mode": "external_adc_tone",
            "expected_signal_hz": expected_hz,
            "observe_center_hz": center_hz,
            "view_bw_hz": bw_hz,
            "dac_signal_hz": dac_hz,
            "dac_source_mode": str(args.dac_source_mode),
            "dac_amplitude": int(args.dac_amplitude),
            "dac_enable_mask": int(args.dac_enable_mask),
        }
    return {
        "scenario": scenario,
        "physical_setup_required": "ADC0 terminated with 50 ohm; DAC0 enabled; any strong DAC-frequency ADC peak is leakage/coupling evidence",
        "input_source_mode": "external_adc_tone",
        "expected_signal_hz": dac_hz,
        "observe_center_hz": center_hz,
        "view_bw_hz": bw_hz,
        "dac_signal_hz": dac_hz,
        "dac_source_mode": str(args.dac_source_mode),
        "dac_amplitude": int(args.dac_amplitude),
        "dac_enable_mask": int(args.dac_enable_mask),
    }


def _configure_condition(core: Any, args: argparse.Namespace, condition: dict[str, Any]) -> dict[str, Any]:
    core.stop()
    time.sleep(0.05)
    core.reset()
    time.sleep(0.05)
    apply_fn = core.apply_sysref_locked_observation_config if bool(args.allow_partial_prereq) else core.apply_mts_locked_observation_config
    cfg = apply_fn(
        observe_center_hz=float(condition["observe_center_hz"]),
        dac_signal_hz=float(condition["dac_signal_hz"]),
        expected_signal_hz=float(condition["expected_signal_hz"]),
        view_bw_hz=float(condition["view_bw_hz"]),
        amplitude=int(condition["dac_amplitude"]),
        phase_deg=float(args.configured_phase_deg),
        enable_mask=int(condition["dac_enable_mask"]),
        adc_active_mask=int(args.adc_port_mask),
        initialize=True,
        start=True,
        require_full_clock_lock=not bool(args.allow_partial_prereq),
        require_mts=not bool(args.allow_partial_prereq),
        mts_adc_tiles=args.mts_adc_tiles,
        mts_dac_tiles=args.mts_dac_tiles,
        mts_adc_ref_tile=int(args.mts_adc_ref_tile),
        mts_dac_ref_tile=int(args.mts_dac_ref_tile),
        dac_source_mode=str(condition["dac_source_mode"]),
        input_source_mode=str(condition["input_source_mode"]),
    )
    status = _wait_streaming(core, int(args.adc_port_mask), float(args.timeout))
    return {"config": cfg, "status_after_start": status}


def _phase_summary(records: list[dict[str, Any]]) -> dict[str, float]:
    import numpy as np

    phases = [float(item["phase_error_deg"]) for item in records if "phase_error_deg" in item]
    times = [float(item["elapsed_s"]) for item in records if "phase_error_deg" in item]
    if not phases:
        return {"phase_pp_deg": float("inf"), "phase_slope_deg_per_s": float("nan")}
    unwrapped = np.rad2deg(np.unwrap(np.deg2rad(np.asarray(phases, dtype=np.float64))))
    phase_pp = float(np.max(unwrapped) - np.min(unwrapped))
    slope = float("nan")
    if len(unwrapped) >= 2 and (max(times) - min(times)) > 0.0:
        slope = float(np.polyfit(np.asarray(times, dtype=np.float64), unwrapped, 1)[0])
    return {
        "phase_pp_deg": phase_pp,
        "phase_slope_deg_per_s": slope,
        "phase_first_deg": float(unwrapped[0]),
        "phase_last_deg": float(unwrapped[-1]),
    }


def _summary_from_records(records: list[dict[str, Any]], args: argparse.Namespace, condition: dict[str, Any]) -> dict[str, Any]:
    import numpy as np

    good = [item for item in records if not item.get("error")]
    if not good:
        return {"record_count": 0, "classification": "RFDC_PREVIEW_STALLED", "errors": ["no successful frames"]}

    sample0 = [int(item["sample0"]) for item in good]
    digests = [str(item["preview_digest"]) for item in good]
    amplitudes = np.asarray([float(item["amplitude_code"]) for item in good], dtype=np.float64)
    rf_peaks = np.asarray([float(item["rf_peak_mhz"]) for item in good], dtype=np.float64)
    snr = np.asarray([float(item["snr_db"]) for item in good], dtype=np.float64)
    max_abs = np.asarray([float(item["max_abs_code"]) for item in good], dtype=np.float64)
    clipped_count = sum(1 for item in good if bool(item["clipped"]))
    reject_count = sum(1 for item in good if not bool(item["valid_frame"]))
    accepted_count = sum(1 for item in good if bool(item["valid_frame"]))
    errors: list[str] = []
    scenario = str(condition["scenario"])
    is_terminated_leakage_check = scenario == "adc_terminated_dac_on"

    phase = _phase_summary(good)
    amp_mean = float(np.mean(amplitudes)) if amplitudes.size else 0.0
    amp_pp_percent = (
        float(100.0 * (np.max(amplitudes) - np.min(amplitudes)) / amp_mean)
        if amp_mean > 0.0 else float("inf")
    )
    sample0_grew = len(set(sample0)) > 1 and all(b > a for a, b in zip(sample0, sample0[1:]))
    digest_changed = len(set(digests)) > 1
    expected_mhz = float(condition["expected_signal_hz"]) / 1_000_000.0
    expected_baseband_hz = float(condition["expected_signal_hz"]) - float(condition["observe_center_hz"])
    rf_peak_mean_mhz = float(np.mean(rf_peaks))
    rf_peak_pp_mhz = float(np.max(rf_peaks) - np.min(rf_peaks))
    rf_peak_error_mhz = abs(rf_peak_mean_mhz - expected_mhz)
    min_snr_db = float(np.min(snr))
    amplitude_unstable = amp_pp_percent > float(args.strict_amplitude_pp_percent)
    unlocked_center_dc = (
        not is_terminated_leakage_check
        and not bool(args.external_source_locked)
        and abs(expected_baseband_hz) <= 1.0
    )
    preview_stalled = not sample0_grew or not digest_changed
    peak_near_expected = rf_peak_error_mhz <= float(args.peak_tol_mhz)
    peak_stable = rf_peak_pp_mhz <= float(args.peak_pp_tol_mhz)
    strong_peak = min_snr_db >= float(args.min_snr_db)
    strong_expected_peak = strong_peak and peak_near_expected and peak_stable

    if preview_stalled:
        errors.append("preview sample0 or IQ digest did not advance")
    if clipped_count:
        errors.append(f"{clipped_count} frames clipped")

    if is_terminated_leakage_check:
        if strong_expected_peak:
            errors.append(
                f"terminated ADC0 still has a DAC-related peak near {expected_mhz:.6f} MHz "
                f"with min SNR {min_snr_db:.3f} dB"
            )
        elif strong_peak:
            errors.append(
                f"terminated ADC0 has a strong unexpected peak at {rf_peak_mean_mhz:.6f} MHz "
                f"(expected DAC leakage near {expected_mhz:.6f} MHz)"
            )
    else:
        if min_snr_db < float(args.min_snr_db):
            errors.append(f"min SNR {min_snr_db:.3f} dB below {float(args.min_snr_db):.3f} dB")
        if rf_peak_error_mhz > float(args.peak_tol_mhz):
            errors.append(
                f"mean RF peak {rf_peak_mean_mhz:.6f} MHz not near expected {expected_mhz:.6f} MHz"
            )
        if rf_peak_pp_mhz > float(args.peak_pp_tol_mhz):
            errors.append(f"RF peak p-p {rf_peak_pp_mhz:.6f} MHz exceeds {float(args.peak_pp_tol_mhz):.6f} MHz")
        if amplitude_unstable:
            errors.append(
                f"amplitude p-p {amp_pp_percent:.6f}% exceeds {float(args.strict_amplitude_pp_percent):.6f}%"
            )
            if unlocked_center_dc:
                errors.append(
                    "external source is not locked to the board reference and expected tone is at observation center/DC; "
                    "run an off-center observation or lock the external source before treating amplitude p-p as an ADC path fault"
                )
        if reject_count:
            reasons = sorted({str(item.get("reject_reason", "")) for item in good if item.get("reject_reason")})
            errors.append(f"stabilizer rejected {reject_count}/{len(good)} frames: {','.join(reasons)}")
        if bool(args.external_source_locked) and phase["phase_pp_deg"] > float(args.strict_phase_pp_deg):
            errors.append(
                f"phase p-p {phase['phase_pp_deg']:.6f} deg exceeds locked-source gate {float(args.strict_phase_pp_deg):.6f} deg"
            )

    secondary_classifications: list[str] = []
    if reject_count:
        secondary_classifications.append("UI_STABILIZER_REJECTING_EXTERNAL_TONE")

    if preview_stalled:
        classification = "RFDC_PREVIEW_STALLED"
    elif is_terminated_leakage_check and strong_expected_peak:
        classification = "DAC_ADC_COUPLING_SUSPECT"
    elif is_terminated_leakage_check and strong_peak:
        classification = "ADC_INPUT_LEVEL_OR_PATH_FAULT"
    elif is_terminated_leakage_check:
        classification = "DAC_ADC_ISOLATION_OK_TERMINATED"
    elif unlocked_center_dc and amplitude_unstable:
        classification = "EXTERNAL_TONE_CENTER_DC_AMBIGUOUS"
    elif (
        clipped_count
        or min_snr_db < float(args.min_snr_db)
        or rf_peak_error_mhz > float(args.peak_tol_mhz)
        or rf_peak_pp_mhz > float(args.peak_pp_tol_mhz)
        or amplitude_unstable
    ):
        classification = "ADC_INPUT_LEVEL_OR_PATH_FAULT"
    elif reject_count > 0:
        classification = "UI_STABILIZER_REJECTING_EXTERNAL_TONE"
    else:
        classification = "EXTERNAL_TONE_OK_FREE_RUNNING_PHASE"

    return {
        "record_count": len(good),
        "sample0_first": sample0[0],
        "sample0_last": sample0[-1],
        "sample0_strictly_increases": bool(sample0_grew),
        "unique_preview_digest_count": len(set(digests)),
        "rf_peak_mean_mhz": rf_peak_mean_mhz,
        "rf_peak_pp_mhz": rf_peak_pp_mhz,
        "rf_peak_error_mhz": rf_peak_error_mhz,
        "expected_baseband_hz": expected_baseband_hz,
        "snr_min_db": min_snr_db,
        "snr_mean_db": float(np.mean(snr)),
        "amplitude_mean_code": amp_mean,
        "amplitude_pp_percent": amp_pp_percent,
        "amplitude_unstable": bool(amplitude_unstable),
        "unlocked_center_dc": bool(unlocked_center_dc),
        "max_abs_code": float(np.max(max_abs)),
        "clipped_count": clipped_count,
        "accepted_count": accepted_count,
        "reject_count": reject_count,
        "reject_reasons": sorted({str(item.get("reject_reason", "")) for item in good if item.get("reject_reason")}),
        "preview_stalled": bool(preview_stalled),
        "strong_peak": bool(strong_peak),
        "strong_expected_peak": bool(strong_expected_peak),
        "secondary_classifications": secondary_classifications,
        "external_source_locked": bool(args.external_source_locked),
        "phase_free_running_expected": not bool(args.external_source_locked),
        **phase,
        "classification": classification,
        "errors": errors,
    }


def _run_condition(core_cls: Any, stabilizer_cls: Any, core: Any, args: argparse.Namespace, condition: dict[str, Any]) -> dict[str, Any]:
    import numpy as np

    setup = _configure_condition(core, args, condition)
    stabilizer = stabilizer_cls(
        min_snr_db=float(args.min_snr_db),
        peak_jump_mhz=float(args.stabilizer_peak_jump_mhz),
        amp_jump_db=float(args.stabilizer_amp_jump_db),
    )
    records: list[dict[str, Any]] = []
    start = time.monotonic()
    for frame in range(int(args.frames)):
        try:
            preview = core.capture_preview_fast(n=int(args.samples), input_mask=int(args.adc_port_mask), timeout=float(args.timeout))
            analysis = core.compute_observation_view(
                preview,
                observe_center_hz=float(condition["observe_center_hz"]),
                view_bw_hz=float(condition["view_bw_hz"]),
                dac_signal_hz=float(condition["dac_signal_hz"]),
                expected_signal_hz=float(condition["expected_signal_hz"]),
                time_window_us=float(args.time_window_us),
                oversample=float(args.oversample),
                phase_ref_input=0,
                stabilize_phase=False,
                display_phase_deg=float(args.configured_phase_deg),
                input_source_mode=str(condition["input_source_mode"]),
            )
            aligned = core_cls.compute_sample0_aligned_phase_view(
                preview,
                observe_center_hz=float(condition["observe_center_hz"]),
                dac_signal_hz=float(condition["dac_signal_hz"]),
                expected_signal_hz=float(condition["expected_signal_hz"]),
                configured_phase_deg=float(args.configured_phase_deg),
                alignment_anchor_deg=0.0,
                phase_ref_input=0,
                time_window_us=float(args.time_window_us),
                display_points=128,
                fft_oversample=4.0,
                input_source_mode=str(condition["input_source_mode"]),
            )
            display = stabilizer.update_channel(
                0,
                analysis["spectrum"][0],
                analysis["peaks"][0],
                smoothing_enabled=True,
                alpha=float(args.smooth_alpha),
            )
            peak = analysis["peaks"][0]
            aligned_ch0 = aligned["channels"][0]
            records.append(
                {
                    "frame": frame,
                    "elapsed_s": time.monotonic() - start,
                    "sample0": int(preview["sample0"]),
                    "preview_digest": _preview_digest(preview, 0),
                    "rf_peak_mhz": float(peak["rf_peak_mhz"]),
                    "raw_baseband_mhz": float(peak["raw_baseband_mhz"]),
                    "snr_db": float(peak["snr_db"]),
                    "rms_dbfs": float(peak["rms_dbfs"]),
                    "peak_dbfs": float(peak["peak_dbfs"]),
                    "max_abs_code": float(peak["max_abs_code"]),
                    "clipped": bool(peak["clipped"]),
                    "amplitude_code": float(aligned_ch0["amplitude_code"]),
                    "phase_error_deg": float(aligned_ch0["phase_error_deg"]),
                    "valid_frame": bool(display["valid_frame"]),
                    "reject_reason": str(display["reject_reason"]),
                    "display_peak_mhz": float(display["display_peak_mhz"]),
                    "display_peak_dbfs": float(display["display_peak_dbfs"]),
                    "raw_display_delta_db": float(display["display_peak_dbfs"] - display["raw_peak_dbfs"]),
                }
            )
        except Exception as exc:
            records.append({"frame": frame, "elapsed_s": time.monotonic() - start, "error": str(exc)})
        if float(args.seconds_between_frames) > 0.0:
            time.sleep(float(args.seconds_between_frames))

    summary = _summary_from_records(records, args, condition)
    return {
        "scenario": condition["scenario"],
        "physical_setup_required": condition["physical_setup_required"],
        "condition": condition,
        "setup": {
            "config": setup["config"],
            "status_after_start": setup["status_after_start"],
        },
        "summary": summary,
        "records": records,
    }


def main() -> int:
    _add_repo_python_path()
    from python.t510_fengine import ObservationSpectrumStabilizer, T510FEngine

    default_bitfile = _repo_root() / "overlay" / "t510_fengine.bit"
    parser = argparse.ArgumentParser(description="Stage 19b external ADC tone decoupling and false-stability check.")
    parser.add_argument("--bitfile", default=str(default_bitfile))
    parser.add_argument("--scenario", type=_scenario_names, default=["external_direct_dac_off"])
    parser.add_argument("--expected-mhz", type=float, default=200.0)
    parser.add_argument("--center-mhz", type=float, default=200.0)
    parser.add_argument("--dac-mhz", type=float, default=None)
    parser.add_argument("--bw-mhz", type=float, default=100.0)
    parser.add_argument("--samples", type=int, default=512)
    parser.add_argument("--frames", type=int, default=240)
    parser.add_argument("--time-window-us", type=float, default=0.25)
    parser.add_argument("--oversample", type=float, default=2.5)
    parser.add_argument("--timeout", type=float, default=2.0)
    parser.add_argument("--seconds-between-frames", type=float, default=0.0)
    parser.add_argument("--adc-port-mask", type=_parse_int, default=0x0001)
    parser.add_argument("--dac-enable-mask", type=_parse_int, default=0x01)
    parser.add_argument("--dac-amplitude", type=int, default=2048)
    parser.add_argument("--dac-source-mode", choices=["constant_phasor", "single_tone"], default="constant_phasor")
    parser.add_argument("--configured-phase-deg", type=float, default=0.0)
    parser.add_argument("--min-snr-db", type=float, default=10.0)
    parser.add_argument("--peak-tol-mhz", type=float, default=1.5)
    parser.add_argument("--peak-pp-tol-mhz", type=float, default=2.0)
    parser.add_argument("--strict-phase-pp-deg", type=float, default=3.0)
    parser.add_argument("--strict-amplitude-pp-percent", type=float, default=5.0)
    parser.add_argument("--smooth-alpha", type=float, default=0.25)
    parser.add_argument("--stabilizer-peak-jump-mhz", type=float, default=2.0)
    parser.add_argument("--stabilizer-amp-jump-db", type=float, default=6.0)
    parser.add_argument("--external-source-locked", action="store_true")
    parser.add_argument("--allow-partial-prereq", action="store_true")
    parser.add_argument("--mts-adc-tiles", type=_parse_int, default=0x1)
    parser.add_argument("--mts-dac-tiles", type=_parse_int, default=0x1)
    parser.add_argument("--mts-adc-ref-tile", type=int, default=0)
    parser.add_argument("--mts-dac-ref-tile", type=int, default=0)
    parser.add_argument("--expected-core-version", type=_parse_int, default=EXPECTED_CORE_VERSION)
    parser.add_argument("--output", default=None)
    parser.add_argument("--no-download", action="store_true")
    args = parser.parse_args()
    expected_core_version = int(args.expected_core_version)

    result: dict[str, Any] = {
        "result": "PASS",
        "expected_core_version": expected_core_version,
        "stage": "19b_external_adc_tone_decoupling",
        "external_source_locked": bool(args.external_source_locked),
        "conditions": [],
        "errors": [],
    }

    core = T510FEngine(args.bitfile, download=not args.no_download)
    initial_status = core.read_status()
    result["initial_status"] = {
        "core_version": int(initial_status.get("core_version", 0)),
        "rfdc_flags": int(initial_status.get("rfdc_status_flags", 0)),
        "preview_sample_rate_hz": int(initial_status.get("preview_sample_rate_hz", 0)),
        "preview_axis_beat_rate_hz": int(initial_status.get("preview_axis_beat_rate_hz", 0)),
        "streaming": int(initial_status.get("streaming", 0)),
    }
    if int(initial_status.get("core_version", 0)) != expected_core_version:
        result["result"] = "FAIL"
        result["classification"] = "WRONG_CORE_VERSION"
        result["errors"].append(
            f"expected CORE_VERSION=0x{expected_core_version:08x}, got 0x{int(initial_status.get('core_version', 0)):08x}"
        )
        _write_output(args.output, result)
        print(json.dumps(_jsonable(result), indent=2, sort_keys=True))
        return 2

    fail_classes = {
        "RFDC_PREVIEW_STALLED",
        "ADC_INPUT_LEVEL_OR_PATH_FAULT",
        "EXTERNAL_TONE_CENTER_DC_AMBIGUOUS",
        "UI_STABILIZER_REJECTING_EXTERNAL_TONE",
        "DAC_ADC_COUPLING_SUSPECT",
        "RFDC_ANALOG_CLOCK_PATH_UNSTABLE",
    }
    for scenario in args.scenario:
        condition = _build_condition(args, scenario)
        print(f"STAGE19B_CONDITION_START scenario={scenario}", file=sys.stderr, flush=True)
        item = _run_condition(T510FEngine, ObservationSpectrumStabilizer, core, args, condition)
        result["conditions"].append(item)
        summary = item["summary"]
        classification = str(summary.get("classification", "UNKNOWN"))
        if classification in fail_classes or summary.get("errors"):
            for error in summary.get("errors", []):
                result["errors"].append(f"{scenario}: {error}")
        print(
            f"STAGE19B_CONDITION_DONE scenario={scenario} classification={classification} errors={len(summary.get('errors', []))}",
            file=sys.stderr,
            flush=True,
        )
        _write_output(args.output, result)

    classifications = sorted({str(item["summary"].get("classification", "UNKNOWN")) for item in result["conditions"]})
    result["classification"] = ",".join(classifications) if classifications else "UNKNOWN"
    if result["errors"]:
        result["result"] = "FAIL"
    _write_output(args.output, result)
    print(json.dumps(_jsonable(result), indent=2, sort_keys=True))
    return 0 if result["result"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
