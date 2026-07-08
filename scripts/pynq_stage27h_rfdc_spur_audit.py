#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import math
import os
import socket
import struct
import sys
import time
import traceback
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


EXPECTED_CORE_VERSION = 0x0001_0028
TFW5_MAGIC = 0x3557_4654
TSP3_MAGIC = 0x3350_5354
RAW_SAMPLE_RATE_HZ = 245_760_000.0
U32_MODULUS = 1 << 32
ALLOWED_STAGE27I_SPUR_CLASSIFICATIONS = (
    "adc_or_board_fixed_rf_suspect",
    "rfdc_mixer_config_suspect",
    "clock_derived_spur_suspect",
    "adc_or_rfdc_frontend_spur_confirmed_by_axis_zero",
    "lmk_sysref_or_clock_coupling_suspect",
    "rfdc_adc_config_or_internal_suspect",
    "adc_input_frontend_or_board_analog_suspect",
    "stage27i_frontend_inconclusive",
    "rfdc_decimation_sideband_flip_suspect",
    "spec_frequency_axis_or_packer_mapping_suspect",
    "stage27i_spec_sideband_inconclusive",
    "rfdc_200m_config_mismatch_suspect",
    "rfdc_200m_decimation_path_suspect",
    "fengine_200m_output_backpressure_suspect",
    "spec_axis_mapping_suspect",
    "stage27i_rfdc_200m_inconclusive",
    "fixed_rf_or_board_coupling_suspect",
    "rfdc_mixer_nco_sideband_suspect",
    "rfdc_dc_image_or_iq_mapping_suspect",
    "adc_or_rfdc_frontend_internal_suspect",
    "stage27i_100m_spur_taxonomy_inconclusive",
    "mixer_event_phase_sensitive",
    "sysref_sensitive",
    "center_sideband_mapping_sensitive",
    "rfdc_internal_or_adc_frontend_remaining",
    "stage27i_mixer_event_inconclusive",
    "mixer_eventsource_sensitive",
    "mixer_sequence_order_sensitive",
    "stage27i_mixer_sequence_inconclusive",
    "raw_lane_matches_time_spec",
    "raw_lane_decim2_alias_matches_time_spec",
    "raw_lane_time_spec_mapping_suspect",
    "raw_lane_witness_inconclusive",
    "stage27i_100m_antialias_spur_suppressed",
    "stage27i_100m_antialias_acceptance_fail",
    "inconclusive",
)
SYNC_MODE_NAMES = {0: "external_pps", 1: "software_epoch", 2: "free_run"}
CLOCK_REF_NAMES = {0: "external_10mhz", 1: "tcxo_10mhz", 2: "gps_10mhz"}
FENGINE_ERROR_COUNTER_KEYS = (
    "pfb_overflow_count",
    "pfb_data_halt_count",
    "pfb_xfft_event_count",
    "pfb_tile_overflow_count",
    "pfb_xfft_tlast_unexpected_count",
    "pfb_xfft_tlast_missing_count",
    "pfb_xfft_fft_overflow_count",
    "pfb_xfft_data_out_halt_count",
    "pfb_xfft_status_halt_count",
    "pfb_capture_backpressure_count",
    "pfb_frame_sample0_overflow_count",
)
FENGINE_REQUIRED_STATUS = {
    "pfb_enabled": 1,
    "pfb_config_valid": 1,
    "pfb_science_valid": 1,
    "pfb_fft_only": 1,
    "pfb_taps": 0,
    "pfb_chan_count": 256,
    "pfb_time_count": 1,
}
ROOTCAUSE_STATUS_COUNTER_KEYS = (
    "time_packet_count",
    "spec_packet_count",
    "time_dropped_count",
    "spec_dropped_count",
    "rfdc_dropped_count",
    "science_dropped_beat_count",
    "tx_frame_built_count",
    "tx_frame_byte_count",
    "tx_route_miss_count",
    "tx_route_error_count",
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _add_repo_python_path() -> None:
    sys.path.insert(0, str(_repo_root()))


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


def _parse_centers(value: str) -> list[float]:
    centers = [float(item.strip().lower().replace("mhz", "")) for item in value.split(",") if item.strip()]
    if not centers:
        raise argparse.ArgumentTypeError("at least one center frequency is required")
    return centers


def _parse_float_list(value: str) -> list[float]:
    values = [float(item.strip().lower().replace("mhz", "")) for item in value.split(",") if item.strip()]
    if not values:
        raise argparse.ArgumentTypeError("at least one value is required")
    return values


def _parse_str_list(value: str) -> list[str]:
    values = [item.strip().lower().replace("-", "_").replace(" ", "_") for item in value.split(",") if item.strip()]
    if not values:
        raise argparse.ArgumentTypeError("at least one value is required")
    return values


def _parse_mode_sweep(value: str) -> list[tuple[int, str]]:
    entries: list[tuple[int, str]] = []
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        if ":" not in item:
            raise argparse.ArgumentTypeError("mode sweep entries must use BANDWIDTH:MODE, for example 100:time_spec")
        bw_text, mode_text = item.split(":", 1)
        bandwidth = int(float(bw_text.strip().lower().replace("mhz", "")))
        mode = mode_text.strip().lower().replace("-", "_").replace(" ", "_")
        if bandwidth not in (20, 100, 200):
            raise argparse.ArgumentTypeError("mode sweep bandwidth must be 20, 100, or 200")
        if mode not in ("time_only", "spec_only", "time_spec"):
            raise argparse.ArgumentTypeError("mode sweep mode must be time_only, spec_only, or time_spec")
        if bandwidth == 200 and mode == "time_spec":
            raise argparse.ArgumentTypeError("Stage 27h/27i production rejects TIME_SPEC at 200MHz; use 200:time_only or 200:spec_only")
        entries.append((bandwidth, mode))
    if not entries:
        raise argparse.ArgumentTypeError("at least one mode sweep entry is required")
    return entries


def _nearest_fft_aligned_mhz(center_mhz: float, target_mhz: float, sample_rate_hz: float, bins: int = 4096) -> float:
    bin_hz = float(sample_rate_hz) / float(bins)
    signed_bin = round(((float(target_mhz) - float(center_mhz)) * 1_000_000.0) / bin_hz)
    return float(center_mhz) + signed_bin * bin_hz / 1_000_000.0


def _safe_call(fn: Any, *args: Any, **kwargs: Any) -> Any:
    try:
        return fn(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}


def _dict_or_empty(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _u32_delta(after: int, before: int) -> int:
    return (int(after) - int(before)) % U32_MODULUS


def _capture_fengine_clean_gate(core: Any, seconds: float) -> dict[str, Any]:
    before = _dict_or_empty(core.read_channelizer_status())
    time.sleep(max(0.0, float(seconds)))
    after = _dict_or_empty(core.read_channelizer_status())
    counter_deltas = {
        key: _u32_delta(int(after.get(key, 0)), int(before.get(key, 0)))
        for key in FENGINE_ERROR_COUNTER_KEYS
    }
    frame_delta = _u32_delta(int(after.get("pfb_frame_count", 0)), int(before.get("pfb_frame_count", 0)))
    status_mismatches = {
        key: {"expected": expected, "actual": int(after.get(key, -1))}
        for key, expected in FENGINE_REQUIRED_STATUS.items()
        if int(after.get(key, -1)) != int(expected)
    }
    active_error_latches = {
        key: int(after.get(key, 0))
        for key in ("pfb_overflow", "pfb_data_halt_seen")
        if int(after.get(key, 0)) != 0
    }
    nonzero_error_deltas = {key: delta for key, delta in counter_deltas.items() if int(delta) != 0}
    reasons = []
    if status_mismatches:
        reasons.append("FENGINE_STATUS_MISMATCH")
    if active_error_latches:
        reasons.append("FENGINE_ERROR_LATCH_SET")
    if nonzero_error_deltas:
        reasons.append("FENGINE_ERROR_COUNTER_DELTA")
    if frame_delta <= 0:
        reasons.append("FENGINE_NO_FRAME_PROGRESS")
    return {
        "seconds": float(seconds),
        "clean": not reasons,
        "reasons": reasons,
        "frame_delta": frame_delta,
        "counter_deltas": counter_deltas,
        "nonzero_error_deltas": nonzero_error_deltas,
        "status_mismatches": status_mismatches,
        "active_error_latches": active_error_latches,
        "before": before,
        "after": after,
    }


def _capture_time_path_clean_gate(core: Any, seconds: float) -> dict[str, Any]:
    before = _dict_or_empty(core.read_status())
    time.sleep(max(0.0, float(seconds)))
    after = _dict_or_empty(core.read_status())
    deltas = {
        "rfdc_dropped_count": _u32_delta(int(after.get("rfdc_dropped_count", 0)), int(before.get("rfdc_dropped_count", 0))),
        "time_dropped_count": _u32_delta(int(after.get("time_dropped_count", 0)), int(before.get("time_dropped_count", 0))),
        "time_packet_count": _u32_delta(int(after.get("time_packet_count", 0)), int(before.get("time_packet_count", 0))),
    }
    reasons = []
    if not int(after.get("streaming", 0)):
        reasons.append("TIME_PATH_NOT_STREAMING")
    if not int(after.get("rfdc_adc_valid", 0)):
        reasons.append("TIME_PATH_RFDC_NOT_VALID")
    if deltas["rfdc_dropped_count"] != 0:
        reasons.append("TIME_PATH_RFDC_DROPPED")
    if deltas["time_dropped_count"] != 0:
        reasons.append("TIME_PATH_DROPPED")
    if deltas["time_packet_count"] <= 0:
        reasons.append("TIME_PATH_NO_PACKET_PROGRESS")
    return {
        "seconds": float(seconds),
        "clean": not reasons,
        "reasons": reasons,
        "deltas": deltas,
        "before": before,
        "after": after,
        "note": "TIME_ONLY audit gate; PFB/SPEC frame progress is intentionally not required.",
    }


def _route_hit_deltas(before: Any, after: Any) -> dict[str, Any]:
    if not isinstance(before, list) or not isinstance(after, list):
        return {"available": False}
    before_by_id = {int(route.get("id", -1)): route for route in before if isinstance(route, dict)}
    after_by_id = {int(route.get("id", -1)): route for route in after if isinstance(route, dict)}
    rows = []
    for route_id, route_after in sorted(after_by_id.items()):
        route_before = before_by_id.get(route_id, {})
        enable = int(route_after.get("enable", 0))
        before_hit = int(route_before.get("hit_count", 0))
        after_hit = int(route_after.get("hit_count", 0))
        rows.append(
            {
                "id": route_id,
                "enable": enable,
                "endpoint_id": int(route_after.get("endpoint_id", 0)),
                "hit_delta": _u32_delta(after_hit, before_hit),
                "hit_count_after": after_hit,
            }
        )
    enabled = [row for row in rows if row["enable"]]
    hit_enabled = [row for row in enabled if int(row["hit_delta"]) > 0]
    return {
        "available": True,
        "route_count": len(rows),
        "enabled_count": len(enabled),
        "hit_enabled_count": len(hit_enabled),
        "zero_hit_enabled_ids": [row["id"] for row in enabled if int(row["hit_delta"]) == 0],
        "routes": rows,
    }


def _counter_delta_map(before: dict[str, Any], after: dict[str, Any], keys: tuple[str, ...]) -> dict[str, int]:
    return {
        key: _u32_delta(int(after.get(key, 0)), int(before.get(key, 0)))
        for key in keys
    }


def _capture_stage27i_rootcause_telemetry(core: Any, seconds: float) -> dict[str, Any]:
    before_status = _dict_or_empty(core.read_status())
    before_channelizer = _dict_or_empty(core.read_channelizer_status())
    before_tx = _dict_or_empty(core.read_tx_status())
    before_science = _dict_or_empty(core.read_science_output_status())
    before_spec_routes = _safe_call(core.read_spec_route_table, 16)
    before_time_routes = _safe_call(core.read_time_route_table, 8)
    time.sleep(max(0.0, float(seconds)))
    after_status = _dict_or_empty(core.read_status())
    after_channelizer = _dict_or_empty(core.read_channelizer_status())
    after_tx = _dict_or_empty(core.read_tx_status())
    after_science = _dict_or_empty(core.read_science_output_status())
    after_spec_routes = _safe_call(core.read_spec_route_table, 16)
    after_time_routes = _safe_call(core.read_time_route_table, 8)
    elapsed = max(float(seconds), 1.0e-6)
    status_deltas = _counter_delta_map(before_status, after_status, ROOTCAUSE_STATUS_COUNTER_KEYS)
    channelizer_deltas = _counter_delta_map(
        before_channelizer,
        after_channelizer,
        tuple(FENGINE_ERROR_COUNTER_KEYS) + ("pfb_frame_count",),
    )
    tx_counter_keys = tuple(
        key for key in (
            "tx_frame_dropped_count",
            "tx_underflow_count",
            "tx_overflow_count",
            "tx_route_miss_count",
            "tx_route_error_count",
        )
        if key in before_tx or key in after_tx
    )
    tx_deltas = _counter_delta_map(before_tx, after_tx, tx_counter_keys) if tx_counter_keys else {}
    return {
        "seconds": float(seconds),
        "status_deltas": status_deltas,
        "channelizer_deltas": channelizer_deltas,
        "tx_deltas": tx_deltas,
        "rates": {
            "time_pps": float(status_deltas.get("time_packet_count", 0)) / elapsed,
            "spec_pps": float(status_deltas.get("spec_packet_count", 0)) / elapsed,
            "combined_t510_udp_payload_mbps": (
                float(status_deltas.get("time_packet_count", 0) + status_deltas.get("spec_packet_count", 0))
                * 8320.0
                * 8.0
                / elapsed
                / 1_000_000.0
            ),
        },
        "spec_route_delta": _route_hit_deltas(before_spec_routes, after_spec_routes),
        "time_route_delta": _route_hit_deltas(before_time_routes, after_time_routes),
        "before": {
            "status": before_status,
            "channelizer_status": before_channelizer,
            "tx_status": before_tx,
            "science_status": before_science,
        },
        "after": {
            "status": after_status,
            "channelizer_status": after_channelizer,
            "tx_status": after_tx,
            "science_status": after_science,
        },
    }


def _clear_stage27h_production_path(core: Any, args: argparse.Namespace) -> dict[str, Any]:
    core.stop()
    time.sleep(max(0.05, float(args.settle_s)))
    core.configure_tx_control(
        force_dry_run=False,
        cmac_enable=True,
        frame_builder_enable=True,
        drop_on_route_miss=True,
        diagnostic_ignore_link_gate=bool(args.diagnostic_ignore_link_gate),
        clear_counters=True,
    )
    channelizer_status = core.configure_channelizer(
        nchan=4096,
        taps=0,
        chan0=0,
        chan_count=256,
        time_count=1,
        fft_shift=int(getattr(core, "FENGINE_FFT_ONLY_DEFAULT_FFT_SHIFT", 0x0556)),
        enable=False,
        clear=True,
    )
    return {
        "tx_status": _safe_call(core.read_tx_status),
        "channelizer_status": channelizer_status,
    }


def _read_dac_registers(core: Any) -> dict[str, Any]:
    regs = core.regs
    result: dict[str, Any] = {
        "dac_tone_control": int(core.ctrl.read(regs.DAC_TONE_CONTROL)),
        "dac_tone_amplitude": int(core.ctrl.read(regs.DAC_TONE_AMPLITUDE)),
        "dac_tone_phase_step": int(core.ctrl.read(regs.DAC_TONE_PHASE_STEP)),
        "dac_enable_mask": int(core.ctrl.read(regs.DAC_ENABLE_MASK)) & 0xFF,
        "dac_broadcast_amplitude": int(core.ctrl.read(regs.DAC_BROADCAST_AMPLITUDE)),
        "dac_broadcast_phase_step": int(core.ctrl.read(regs.DAC_BROADCAST_PHASE_STEP)),
        "dac_phase_epoch": int(core.ctrl.read(regs.DAC_PHASE_EPOCH)),
        "channels": [],
    }
    for channel in range(8):
        base = regs.DAC_CH_BASE + channel * regs.DAC_CH_STRIDE
        result["channels"].append(
            {
                "channel": channel,
                "phase_step": int(core.ctrl.read(base + 0x00)),
                "amplitude": int(core.ctrl.read(base + 0x04)),
                "phase0": int(core.ctrl.read(base + 0x08)),
                "phase_inject": int(core.ctrl.read(base + 0x0C)),
                "mode": int(core.ctrl.read(base + 0x10)),
            }
        )
    return result


def _rank_power_peaks(
    power_db: Any,
    freq_hz: Any,
    *,
    center_mhz: float,
    bin_ids: Any,
    count: int = 8,
    guard_bins: int = 4,
) -> list[dict[str, Any]]:
    import numpy as np

    power = np.asarray(power_db, dtype=np.float64)
    freq = np.asarray(freq_hz, dtype=np.float64)
    ids = np.asarray(bin_ids, dtype=np.int64)
    finite = np.isfinite(power)
    if power.size == 0 or not np.any(finite):
        return []
    noise_floor_db = float(np.median(power[finite]))
    work = np.where(finite, power, np.nan)
    peaks: list[dict[str, Any]] = []
    for _ in range(int(count)):
        if not np.any(np.isfinite(work)):
            break
        idx = int(np.nanargmax(work))
        value = float(work[idx])
        if not math.isfinite(value):
            break
        baseband_mhz = float(freq[idx] / 1_000_000.0)
        peaks.append(
            {
                "rank": len(peaks) + 1,
                "index": int(ids[idx]),
                "baseband_mhz": baseband_mhz,
                "rf_mhz": float(center_mhz) + baseband_mhz,
                "power_db": value,
                "noise_floor_db": noise_floor_db,
                "snr_db": value - noise_floor_db,
            }
        )
        start = max(0, idx - int(guard_bins))
        end = min(work.size, idx + int(guard_bins) + 1)
        work[start:end] = np.nan
    return peaks


def _target_power_metric(
    power_db: Any,
    freq_hz: Any,
    *,
    center_mhz: float,
    target_rf_mhz: float,
    bin_ids: Any,
    phase_rad: Any | None = None,
    amplitude: Any | None = None,
    search_half_width_mhz: float = 0.0,
) -> dict[str, Any]:
    import numpy as np

    power = np.asarray(power_db, dtype=np.float64)
    freq = np.asarray(freq_hz, dtype=np.float64)
    ids = np.asarray(bin_ids, dtype=np.int64)
    if power.size == 0 or freq.size == 0:
        return {"available": False, "reason": "empty spectrum"}
    finite = np.isfinite(power)
    if not np.any(finite):
        return {"available": False, "reason": "no finite power bins"}
    target_baseband_hz = (float(target_rf_mhz) - float(center_mhz)) * 1_000_000.0
    nyquist_hz = float(np.nanmax(np.abs(freq))) if freq.size else 0.0
    in_band = abs(target_baseband_hz) <= nyquist_hz
    nearest_idx = int(np.argmin(np.abs(freq - target_baseband_hz)))
    idx = nearest_idx
    search_half_width_hz = max(0.0, float(search_half_width_mhz)) * 1_000_000.0
    if search_half_width_hz > 0.0:
        candidates = np.where(np.abs(freq - target_baseband_hz) <= search_half_width_hz)[0]
        if candidates.size:
            idx = int(candidates[int(np.nanargmax(power[candidates]))])
    noise_floor_db = float(np.median(power[finite]))
    metric: dict[str, Any] = {
        "available": True,
        "target_rf_mhz": float(target_rf_mhz),
        "target_baseband_mhz": target_baseband_hz / 1_000_000.0,
        "search_half_width_mhz": float(search_half_width_mhz),
        "in_band": bool(in_band),
        "nearest_index": int(ids[nearest_idx]) if ids.size > nearest_idx else nearest_idx,
        "nearest_bin_baseband_mhz": float(freq[nearest_idx] / 1_000_000.0),
        "nearest_bin_rf_mhz": float(center_mhz) + float(freq[nearest_idx] / 1_000_000.0),
        "nearest_bin_error_khz": float((freq[nearest_idx] - target_baseband_hz) / 1_000.0),
        "index": int(ids[idx]) if ids.size > idx else idx,
        "array_index": idx,
        "bin_baseband_mhz": float(freq[idx] / 1_000_000.0),
        "bin_rf_mhz": float(center_mhz) + float(freq[idx] / 1_000_000.0),
        "bin_error_khz": float((freq[idx] - target_baseband_hz) / 1_000.0),
        "power_db": float(power[idx]),
        "noise_floor_db": noise_floor_db,
        "snr_db": float(power[idx] - noise_floor_db),
    }
    if phase_rad is not None:
        phase = np.asarray(phase_rad, dtype=np.float64)
        if phase.size > idx and np.isfinite(phase[idx]):
            metric["phase_rad"] = float(phase[idx])
    if amplitude is not None:
        amp = np.asarray(amplitude, dtype=np.float64)
        if amp.size > idx and np.isfinite(amp[idx]):
            metric["amplitude"] = float(amp[idx])
    return metric


def _time_preview_fft(preview: dict[str, Any], *, center_mhz: float, top_count: int) -> dict[str, Any]:
    import numpy as np

    sample_rate = float(preview["sample_rate_hz"])
    count = int(preview["count"])
    nfft = max(4096, 1 << int(math.ceil(math.log2(max(count, 2)))))
    nfft = min(nfft, 65536)
    freq_hz = np.fft.fftshift(np.fft.fftfreq(nfft, d=1.0 / sample_rate))
    bin_ids = np.arange(nfft, dtype=np.int64)
    window = np.hanning(count)
    spectra_db = []
    channels: dict[str, Any] = {}
    for channel, iq in preview["iq"].items():
        arr = np.asarray(iq, dtype=np.float64)
        z = arr[:, 0] + 1j * arr[:, 1]
        fft = np.fft.fftshift(np.fft.fft(z * window, n=nfft))
        power = np.maximum(np.abs(fft) ** 2, 1.0)
        power_db = 10.0 * np.log10(power)
        spectra_db.append(power_db)
        channels[str(channel)] = {
            "rms_code": float(np.sqrt(np.mean(np.abs(z) ** 2))) if z.size else 0.0,
            "max_abs_code": int(max(np.max(np.abs(arr[:, 0])), np.max(np.abs(arr[:, 1])))) if arr.size else 0,
            "top_peaks": _rank_power_peaks(
                power_db,
                freq_hz,
                center_mhz=center_mhz,
                bin_ids=bin_ids,
                count=top_count,
            ),
        }
    if spectra_db:
        linear = np.mean([10.0 ** (power_db / 10.0) for power_db in spectra_db], axis=0)
        average_power_db = 10.0 * np.log10(np.maximum(linear, 1.0e-16))
        average_peaks = _rank_power_peaks(
            average_power_db,
            freq_hz,
            center_mhz=center_mhz,
            bin_ids=bin_ids,
            count=top_count,
        )
    else:
        average_peaks = []
    return {
        "sample0": int(preview["sample0"]),
        "count": count,
        "sample_rate_hz": sample_rate,
        "nfft": nfft,
        "average_peaks": average_peaks,
        "channels": channels,
    }


def _raw_witness_fft(
    captures: dict[int, dict[str, Any]],
    *,
    center_mhz: float,
    target_rf_mhz: float | None,
    target_search_half_width_mhz: float,
    top_count: int,
    sample_rate_hz: float = RAW_SAMPLE_RATE_HZ,
) -> dict[str, Any]:
    import numpy as np

    spectra_db = []
    spectra_ac_db = []
    decim2_spectra_db = []
    decim2_spectra_ac_db = []
    channels: dict[str, Any] = {}
    nfft = 4096
    freq_hz = np.fft.fftshift(np.fft.fftfreq(nfft, d=1.0 / float(sample_rate_hz)))
    bin_ids = np.arange(nfft, dtype=np.int64)

    def analyze_series(z: Any, series_sample_rate_hz: float) -> dict[str, Any]:
        z_arr = np.asarray(z, dtype=np.complex128)
        if z_arr.size <= 0:
            return {
                "nfft": 0,
                "top_peaks": [],
                "top_ac_peaks": [],
                "power_db": None,
                "power_ac_db": None,
                "freq_hz": None,
                "bin_ids": None,
            }
        local_nfft = max(4096, 1 << int(math.ceil(math.log2(max(z_arr.size, 2)))))
        local_nfft = min(local_nfft, 65536)
        local_freq_hz = np.fft.fftshift(np.fft.fftfreq(local_nfft, d=1.0 / float(series_sample_rate_hz)))
        local_bin_ids = np.arange(local_nfft, dtype=np.int64)
        window = np.hanning(z_arr.size)
        fft = np.fft.fftshift(np.fft.fft(z_arr * window, n=local_nfft))
        power_db = 10.0 * np.log10(np.maximum(np.abs(fft) ** 2, 1.0e-16))
        z_ac = z_arr - np.mean(z_arr)
        fft_ac = np.fft.fftshift(np.fft.fft(z_ac * window, n=local_nfft))
        power_ac_db = 10.0 * np.log10(np.maximum(np.abs(fft_ac) ** 2, 1.0e-16))
        result = {
            "nfft": int(local_nfft),
            "top_peaks": _rank_power_peaks(power_db, local_freq_hz, center_mhz=center_mhz, bin_ids=local_bin_ids, count=top_count),
            "top_ac_peaks": _rank_power_peaks(power_ac_db, local_freq_hz, center_mhz=center_mhz, bin_ids=local_bin_ids, count=top_count),
            "power_db": power_db,
            "power_ac_db": power_ac_db,
            "freq_hz": local_freq_hz,
            "bin_ids": local_bin_ids,
        }
        if target_rf_mhz is not None:
            result["target_rf_bin"] = _target_power_metric(
                power_ac_db,
                local_freq_hz,
                center_mhz=center_mhz,
                target_rf_mhz=float(target_rf_mhz),
                bin_ids=local_bin_ids,
                phase_rad=np.angle(fft_ac),
                search_half_width_mhz=float(target_search_half_width_mhz),
            )
            result["target_rf_bin_raw"] = _target_power_metric(
                power_db,
                local_freq_hz,
                center_mhz=center_mhz,
                target_rf_mhz=float(target_rf_mhz),
                bin_ids=local_bin_ids,
                phase_rad=np.angle(fft),
                search_half_width_mhz=float(target_search_half_width_mhz),
            )
        return result

    for channel in sorted(captures):
        capture = captures[channel]
        decoded = capture.get("decoded") if isinstance(capture, dict) else None
        iq = decoded.get("iq") if isinstance(decoded, dict) else None
        arr = np.asarray(iq, dtype=np.float64) if iq is not None else np.zeros((0, 2), dtype=np.float64)
        if arr.ndim != 2 or arr.shape[1] < 2:
            arr = np.zeros((0, 2), dtype=np.float64)
        z = arr[:, 0] + 1j * arr[:, 1]
        if z.size:
            metrics = analyze_series(z, float(sample_rate_hz))
            nfft = int(metrics["nfft"])
            freq_hz = metrics["freq_hz"]
            bin_ids = metrics["bin_ids"]
            power_db = metrics["power_db"]
            power_ac_db = metrics["power_ac_db"]
            spectra_db.append(power_db)
            spectra_ac_db.append(power_ac_db)
            top_peaks = metrics["top_peaks"]
            top_ac_peaks = metrics["top_ac_peaks"]
            target_metric = metrics.get("target_rf_bin")
            target_metric_raw = metrics.get("target_rf_bin_raw")
            decim2_metrics = analyze_series(z[::2], float(sample_rate_hz) / 2.0)
            if decim2_metrics.get("power_db") is not None:
                decim2_spectra_db.append(decim2_metrics["power_db"])
                decim2_spectra_ac_db.append(decim2_metrics["power_ac_db"])
        else:
            top_peaks = []
            top_ac_peaks = []
            target_metric = None
            target_metric_raw = None
            decim2_metrics = None
        channel_info: dict[str, Any] = {
            "channel": int(channel),
            "sample0": int(capture.get("sample0", 0)) if isinstance(capture, dict) else 0,
            "beat_count": int(capture.get("beat_count", 0)) if isinstance(capture, dict) else 0,
            "word_count": int(capture.get("word_count", 0)) if isinstance(capture, dict) else 0,
            "valid_mask": int(capture.get("valid_mask", 0)) if isinstance(capture, dict) else 0,
            "rfdc_flags": int(capture.get("rfdc_flags", 0)) if isinstance(capture, dict) else 0,
            "rms_code": float(np.sqrt(np.mean(np.abs(z) ** 2))) if z.size else 0.0,
            "max_abs_code": int(max(np.max(np.abs(arr[:, 0])), np.max(np.abs(arr[:, 1])))) if arr.size else 0,
            "top_peaks": top_peaks,
            "top_ac_peaks": top_ac_peaks,
        }
        if target_metric is not None:
            channel_info["target_rf_bin"] = target_metric
        if target_metric_raw is not None:
            channel_info["target_rf_bin_raw"] = target_metric_raw
        if isinstance(decim2_metrics, dict) and int(decim2_metrics.get("nfft", 0)) > 0:
            decim2_public = {
                "sample_rate_hz": float(sample_rate_hz) / 2.0,
                "source": "rtl_science_rate_selector_bw100_even_samples_z_0_step_2",
                "nfft": int(decim2_metrics["nfft"]),
                "top_peaks": decim2_metrics["top_peaks"],
                "top_ac_peaks": decim2_metrics["top_ac_peaks"],
            }
            if decim2_metrics.get("target_rf_bin") is not None:
                decim2_public["target_rf_bin"] = decim2_metrics["target_rf_bin"]
            if decim2_metrics.get("target_rf_bin_raw") is not None:
                decim2_public["target_rf_bin_raw"] = decim2_metrics["target_rf_bin_raw"]
            channel_info["rtl_decim2_model"] = decim2_public
        status = capture.get("status") if isinstance(capture, dict) else None
        if isinstance(status, dict):
            channel_info["status"] = {
                "rfdc_axis_raw_witness_status": int(status.get("rfdc_axis_raw_witness_status", 0)),
                "rfdc_axis_raw_witness_valid": int(status.get("rfdc_axis_raw_witness_valid", 0)),
                "rfdc_axis_raw_witness_tvalid_seen": int(status.get("rfdc_axis_raw_witness_tvalid_seen", 0)),
                "rfdc_axis_raw_witness_beat_count": int(status.get("rfdc_axis_raw_witness_beat_count", 0)),
            }
        channels[str(channel)] = channel_info

    if spectra_db:
        linear = np.mean([10.0 ** (power_db / 10.0) for power_db in spectra_db], axis=0)
        average_power_db = 10.0 * np.log10(np.maximum(linear, 1.0e-16))
        linear_ac = np.mean([10.0 ** (power_db / 10.0) for power_db in spectra_ac_db], axis=0)
        average_ac_power_db = 10.0 * np.log10(np.maximum(linear_ac, 1.0e-16))
        average_peaks = _rank_power_peaks(average_power_db, freq_hz, center_mhz=center_mhz, bin_ids=bin_ids, count=top_count)
        average_ac_peaks = _rank_power_peaks(average_ac_power_db, freq_hz, center_mhz=center_mhz, bin_ids=bin_ids, count=top_count)
        target_metric = (
            _target_power_metric(
                average_ac_power_db,
                freq_hz,
                center_mhz=center_mhz,
                target_rf_mhz=float(target_rf_mhz),
                bin_ids=bin_ids,
                search_half_width_mhz=float(target_search_half_width_mhz),
            )
            if target_rf_mhz is not None
            else None
        )
        target_metric_raw = (
            _target_power_metric(
                average_power_db,
                freq_hz,
                center_mhz=center_mhz,
                target_rf_mhz=float(target_rf_mhz),
                bin_ids=bin_ids,
                search_half_width_mhz=float(target_search_half_width_mhz),
            )
            if target_rf_mhz is not None
            else None
        )
    else:
        average_peaks = []
        average_ac_peaks = []
        target_metric = None
        target_metric_raw = None

    result: dict[str, Any] = {
        "sample_rate_hz": float(sample_rate_hz),
        "nfft": int(nfft),
        "channel_count": len(channels),
        "average_peaks": average_peaks,
        "average_ac_peaks": average_ac_peaks,
        "channels": channels,
    }
    if target_metric is not None:
        result["target_rf_bin"] = target_metric
    if target_metric_raw is not None:
        result["target_rf_bin_raw"] = target_metric_raw
    if decim2_spectra_db:
        decim2_freq_hz = np.fft.fftshift(np.fft.fftfreq(len(decim2_spectra_db[0]), d=1.0 / (float(sample_rate_hz) / 2.0)))
        decim2_bin_ids = np.arange(len(decim2_spectra_db[0]), dtype=np.int64)
        decim2_linear = np.mean([10.0 ** (power_db / 10.0) for power_db in decim2_spectra_db], axis=0)
        decim2_average_power_db = 10.0 * np.log10(np.maximum(decim2_linear, 1.0e-16))
        decim2_linear_ac = np.mean([10.0 ** (power_db / 10.0) for power_db in decim2_spectra_ac_db], axis=0)
        decim2_average_ac_power_db = 10.0 * np.log10(np.maximum(decim2_linear_ac, 1.0e-16))
        decim2_public = {
            "sample_rate_hz": float(sample_rate_hz) / 2.0,
            "source": "rtl_science_rate_selector_bw100_even_samples_z_0_step_2",
            "nfft": int(len(decim2_average_power_db)),
            "average_peaks": _rank_power_peaks(decim2_average_power_db, decim2_freq_hz, center_mhz=center_mhz, bin_ids=decim2_bin_ids, count=top_count),
            "average_ac_peaks": _rank_power_peaks(decim2_average_ac_power_db, decim2_freq_hz, center_mhz=center_mhz, bin_ids=decim2_bin_ids, count=top_count),
        }
        if target_rf_mhz is not None:
            decim2_public["target_rf_bin"] = _target_power_metric(
                decim2_average_ac_power_db,
                decim2_freq_hz,
                center_mhz=center_mhz,
                target_rf_mhz=float(target_rf_mhz),
                bin_ids=decim2_bin_ids,
                search_half_width_mhz=float(target_search_half_width_mhz),
            )
            decim2_public["target_rf_bin_raw"] = _target_power_metric(
                decim2_average_power_db,
                decim2_freq_hz,
                center_mhz=center_mhz,
                target_rf_mhz=float(target_rf_mhz),
                bin_ids=decim2_bin_ids,
                search_half_width_mhz=float(target_search_half_width_mhz),
            )
        result["rtl_decim2_model"] = decim2_public
    return result


def _http_json(url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def _read_exact(sock: socket.socket, count: int) -> bytes:
    chunks = []
    remaining = int(count)
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:
            raise RuntimeError("websocket closed while reading frame")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _read_ws_frame(sock: socket.socket) -> tuple[int, bytes]:
    header = _read_exact(sock, 2)
    opcode = header[0] & 0x0F
    masked = bool(header[1] & 0x80)
    length = header[1] & 0x7F
    if length == 126:
        length = struct.unpack("!H", _read_exact(sock, 2))[0]
    elif length == 127:
        length = struct.unpack("!Q", _read_exact(sock, 8))[0]
    mask = _read_exact(sock, 4) if masked else b""
    payload = _read_exact(sock, length)
    if masked:
        payload = bytes(value ^ mask[idx & 3] for idx, value in enumerate(payload))
    return opcode, payload


def _capture_ws_binary(base_url: str, endpoint: str, timeout: float) -> bytes:
    parsed = urllib.parse.urlparse(base_url)
    scheme = "ws" if parsed.scheme in ("http", "ws", "") else "wss"
    if scheme == "wss":
        raise ValueError("wss Rust Web capture is not supported by this stdlib audit client")
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 8089
    base_path = parsed.path.rstrip("/")
    path = f"{base_path}{endpoint}" if base_path else endpoint
    key = base64.b64encode(os.urandom(16)).decode("ascii")
    with socket.create_connection((host, port), timeout=timeout) as sock:
        sock.settimeout(timeout)
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        )
        sock.sendall(request.encode("ascii"))
        response = b""
        while b"\r\n\r\n" not in response:
            response += sock.recv(4096)
            if not response:
                raise RuntimeError("empty websocket handshake response")
        if b" 101 " not in response.split(b"\r\n", 1)[0]:
            raise RuntimeError(response.decode("utf-8", errors="replace").splitlines()[0])
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            opcode, payload = _read_ws_frame(sock)
            if opcode == 2:
                return payload
            if opcode == 8:
                raise RuntimeError("websocket closed before binary frame")
        raise TimeoutError("timed out waiting for websocket binary frame")


def _capture_ws_binary_retry(base_url: str, endpoint: str, timeout: float, attempts: int) -> bytes:
    last_exc: Exception | None = None
    for attempt in range(max(1, int(attempts))):
        try:
            return _capture_ws_binary(base_url, endpoint, timeout)
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt + 1 < max(1, int(attempts)):
                time.sleep(0.5)
    assert last_exc is not None
    raise last_exc


def _parse_tsp3_spectrum(
    payload: bytes,
    *,
    center_mhz: float,
    top_count: int,
    target_rf_mhz: float | None = None,
    target_search_half_width_mhz: float = 0.0,
) -> dict[str, Any]:
    import numpy as np

    if len(payload) < 128:
        raise ValueError("TSP3 payload is shorter than 128-byte header")
    if struct.unpack_from("<I", payload, 0)[0] != TSP3_MAGIC:
        raise ValueError("websocket payload is not TSP3 spectrum binary")
    header = {
        "version": struct.unpack_from("<H", payload, 4)[0],
        "header_bytes": struct.unpack_from("<H", payload, 6)[0],
        "sample0": struct.unpack_from("<Q", payload, 8)[0],
        "frame_id": struct.unpack_from("<Q", payload, 16)[0],
        "seq_no": struct.unpack_from("<I", payload, 24)[0],
        "gap": bool(struct.unpack_from("<I", payload, 28)[0]),
        "chan0": struct.unpack_from("<I", payload, 32)[0],
        "chan_count": struct.unpack_from("<I", payload, 36)[0],
        "time_count": struct.unpack_from("<I", payload, 40)[0],
        "ninput": struct.unpack_from("<I", payload, 44)[0],
        "src_port": struct.unpack_from("<I", payload, 48)[0],
        "dst_port": struct.unpack_from("<I", payload, 52)[0],
        "lane_count": struct.unpack_from("<I", payload, 56)[0],
        "bins": struct.unpack_from("<I", payload, 60)[0],
        "product_id": struct.unpack_from("<I", payload, 64)[0],
        "nchan": struct.unpack_from("<I", payload, 68)[0],
        "block_index": struct.unpack_from("<I", payload, 72)[0],
        "block_count": struct.unpack_from("<I", payload, 76)[0],
        "pfb_taps": struct.unpack_from("<I", payload, 80)[0],
        "fft_shift": struct.unpack_from("<I", payload, 84)[0],
        "spec_flags": struct.unpack_from("<I", payload, 88)[0],
        "sample_rate_hz": struct.unpack_from("<I", payload, 92)[0],
        "coverage_blocks": struct.unpack_from("<I", payload, 96)[0],
        "coverage_mask_lo": struct.unpack_from("<Q", payload, 104)[0],
        "coverage_mask_hi": struct.unpack_from("<Q", payload, 112)[0],
    }
    bins = int(header["bins"])
    lane_count = int(header["lane_count"])
    offset = int(header["header_bytes"])
    lanes: dict[str, Any] = {}
    powers = []
    freq_hz = _spec_freq_hz(bins, int(header["sample_rate_hz"]))
    bin_ids = np.arange(bins, dtype=np.int64)
    for lane in range(lane_count):
        lane_bytes = bins * 12
        if offset + lane_bytes > len(payload):
            raise ValueError("truncated TSP3 lane payload")
        amplitude = np.frombuffer(payload, dtype="<f4", count=bins, offset=offset).copy()
        offset += bins * 4
        phase = np.frombuffer(payload, dtype="<f4", count=bins, offset=offset).copy()
        offset += bins * 4
        power = np.frombuffer(payload, dtype="<f4", count=bins, offset=offset).copy()
        offset += bins * 4
        powers.append(power)
        lane_info = {
            "top_peaks": _rank_power_peaks(
                power,
                freq_hz,
                center_mhz=center_mhz,
                bin_ids=bin_ids,
                count=top_count,
            ),
            "amplitude_max": float(np.nanmax(amplitude)) if amplitude.size else 0.0,
            "phase_at_max_rad": float(phase[int(np.nanargmax(power))]) if power.size else 0.0,
        }
        if target_rf_mhz is not None:
            lane_info["target_rf_bin"] = _target_power_metric(
                power,
                freq_hz,
                center_mhz=center_mhz,
                target_rf_mhz=float(target_rf_mhz),
                bin_ids=bin_ids,
                phase_rad=phase,
                amplitude=amplitude,
                search_half_width_mhz=float(target_search_half_width_mhz),
            )
            mirror_rf_mhz = 2.0 * float(center_mhz) - float(target_rf_mhz)
            lane_info["mirror_rf_bin"] = _target_power_metric(
                power,
                freq_hz,
                center_mhz=center_mhz,
                target_rf_mhz=mirror_rf_mhz,
                bin_ids=bin_ids,
                phase_rad=phase,
                amplitude=amplitude,
                search_half_width_mhz=float(target_search_half_width_mhz),
            )
            negative_edge_rf_mhz = float(center_mhz) - float(header["sample_rate_hz"]) / 2_000_000.0
            lane_info["negative_edge_bin"] = _target_power_metric(
                power,
                freq_hz,
                center_mhz=center_mhz,
                target_rf_mhz=negative_edge_rf_mhz,
                bin_ids=bin_ids,
                phase_rad=phase,
                amplitude=amplitude,
                search_half_width_mhz=float(target_search_half_width_mhz),
            )
            lane_info["dc_bin"] = _target_power_metric(
                power,
                freq_hz,
                center_mhz=center_mhz,
                target_rf_mhz=float(center_mhz),
                bin_ids=bin_ids,
                phase_rad=phase,
                amplitude=amplitude,
                search_half_width_mhz=float(target_search_half_width_mhz),
            )
        lanes[str(lane)] = lane_info
    if powers:
        linear = np.mean([10.0 ** (np.asarray(power, dtype=np.float64) / 10.0) for power in powers], axis=0)
        average_power_db = 10.0 * np.log10(np.maximum(linear, 1.0e-16))
        average_peaks = _rank_power_peaks(
            average_power_db,
            freq_hz,
            center_mhz=center_mhz,
            bin_ids=bin_ids,
            count=top_count,
        )
        target_metric = (
            _target_power_metric(
                average_power_db,
                freq_hz,
                center_mhz=center_mhz,
                target_rf_mhz=float(target_rf_mhz),
                bin_ids=bin_ids,
                search_half_width_mhz=float(target_search_half_width_mhz),
            )
            if target_rf_mhz is not None
            else None
        )
        mirror_metric = (
            _target_power_metric(
                average_power_db,
                freq_hz,
                center_mhz=center_mhz,
                target_rf_mhz=2.0 * float(center_mhz) - float(target_rf_mhz),
                bin_ids=bin_ids,
                search_half_width_mhz=float(target_search_half_width_mhz),
            )
            if target_rf_mhz is not None
            else None
        )
        negative_edge_metric = (
            _target_power_metric(
                average_power_db,
                freq_hz,
                center_mhz=center_mhz,
                target_rf_mhz=float(center_mhz) - float(header["sample_rate_hz"]) / 2_000_000.0,
                bin_ids=bin_ids,
                search_half_width_mhz=float(target_search_half_width_mhz),
            )
            if target_rf_mhz is not None
            else None
        )
        dc_metric = (
            _target_power_metric(
                average_power_db,
                freq_hz,
                center_mhz=center_mhz,
                target_rf_mhz=float(center_mhz),
                bin_ids=bin_ids,
                search_half_width_mhz=float(target_search_half_width_mhz),
            )
            if target_rf_mhz is not None
            else None
        )
    else:
        average_peaks = []
        target_metric = None
        mirror_metric = None
        negative_edge_metric = None
        dc_metric = None
    result = {"header": header, "average_peaks": average_peaks, "lanes": lanes}
    if target_metric is not None:
        result["target_rf_bin"] = target_metric
    if mirror_metric is not None:
        result["mirror_rf_bin"] = mirror_metric
    if negative_edge_metric is not None:
        result["negative_edge_bin"] = negative_edge_metric
    if dc_metric is not None:
        result["dc_bin"] = dc_metric
    return result


def _parse_tfw_waveform(
    payload: bytes,
    *,
    center_mhz: float,
    top_count: int,
    target_rf_mhz: float | None = None,
    target_search_half_width_mhz: float = 0.0,
) -> dict[str, Any]:
    import numpy as np

    if len(payload) < 160:
        raise ValueError("TFW waveform payload is shorter than the Stage 27h header")
    magic = struct.unpack_from("<I", payload, 0)[0]
    if magic != TFW5_MAGIC:
        raise ValueError("websocket payload is not TFW5 waveform binary")
    version = struct.unpack_from("<H", payload, 4)[0]
    if version < 3:
        raise ValueError(f"TFW version {version} does not carry production TIME I/Q samples")
    header = {
        "version": version,
        "header_bytes": struct.unpack_from("<H", payload, 6)[0],
        "sample0": struct.unpack_from("<Q", payload, 8)[0],
        "seq_start": struct.unpack_from("<I", payload, 16)[0],
        "seq_end": struct.unpack_from("<I", payload, 20)[0],
        "selected_bandwidth_mhz": struct.unpack_from("<I", payload, 24)[0],
        "detected_bandwidth_mhz": struct.unpack_from("<I", payload, 28)[0],
        "flags": struct.unpack_from("<I", payload, 32)[0],
        "channel_mask": struct.unpack_from("<I", payload, 36)[0],
        "points": struct.unpack_from("<I", payload, 40)[0],
        "channel_count": struct.unpack_from("<I", payload, 44)[0],
        "decimation": struct.unpack_from("<I", payload, 48)[0],
        "rf_points": struct.unpack_from("<I", payload, 52)[0] if version >= 4 else struct.unpack_from("<I", payload, 40)[0],
        "sample_rate_hz": struct.unpack_from("<d", payload, 56)[0],
        "requested_window_us": struct.unpack_from("<d", payload, 64)[0],
        "center_mhz": struct.unpack_from("<d", payload, 72)[0],
        "expected_mhz": struct.unpack_from("<d", payload, 80)[0],
        "dac_mhz": struct.unpack_from("<d", payload, 88)[0],
        "expected_baseband_mhz": struct.unpack_from("<d", payload, 96)[0],
        "rf_samples_per_cycle": struct.unpack_from("<d", payload, 104)[0],
        "baseband_samples_per_cycle": struct.unpack_from("<d", payload, 112)[0],
        "rf_window_cycles": struct.unpack_from("<d", payload, 120)[0],
        "captured_window_us": struct.unpack_from("<d", payload, 128)[0] if version >= 5 else struct.unpack_from("<d", payload, 64)[0],
    }
    points = int(header["points"])
    rf_points = int(header["rf_points"])
    sample_rate = float(header["sample_rate_hz"])
    if points <= 0 or sample_rate <= 0.0:
        raise ValueError("TFW waveform has no usable production TIME samples")
    fft_size = max(4096, 1 << int(math.ceil(math.log2(max(points, 2)))))
    fft_size = min(fft_size, 65536)
    freq_hz = np.fft.fftshift(np.fft.fftfreq(fft_size, d=1.0 / sample_rate))
    bin_ids = np.arange(fft_size, dtype=np.int64)
    offset = int(header["header_bytes"])
    mask = int(header["channel_mask"])
    spectra_db = []
    spectra_ac_db = []
    channels: dict[str, Any] = {}
    for channel in range(8):
        if not (mask & (1 << channel)):
            continue
        if version >= 5:
            needed = points * 20 + rf_points * 8
            if offset + needed > len(payload):
                raise ValueError("truncated TFW5 waveform channel payload")
            x_us = np.frombuffer(payload, dtype="<f4", count=points, offset=offset).copy()
            offset += points * 4
            i_values = np.frombuffer(payload, dtype="<f4", count=points, offset=offset).astype(np.float64)
            offset += points * 4
            q_values = np.frombuffer(payload, dtype="<f4", count=points, offset=offset).astype(np.float64)
            offset += points * 4
            offset += points * 4  # magnitude
            offset += points * 4  # sample RF
            offset += rf_points * 4  # RF curve x
            offset += rf_points * 4  # RF curve y
        elif version == 4:
            needed = points * 16 + rf_points * 8
            if offset + needed > len(payload):
                raise ValueError("truncated TFW4 waveform channel payload")
            x_us = np.frombuffer(payload, dtype="<f4", count=points, offset=offset).copy()
            offset += points * 4
            i_values = np.frombuffer(payload, dtype="<f4", count=points, offset=offset).astype(np.float64)
            offset += points * 4
            q_values = np.frombuffer(payload, dtype="<f4", count=points, offset=offset).astype(np.float64)
            offset += points * 4
            offset += points * 4  # magnitude
            offset += rf_points * 4
            offset += rf_points * 4
        else:
            needed = points * 20
            if offset + needed > len(payload):
                raise ValueError("truncated TFW3 waveform channel payload")
            x_us = np.frombuffer(payload, dtype="<f4", count=points, offset=offset).copy()
            offset += points * 4
            i_values = np.frombuffer(payload, dtype="<f4", count=points, offset=offset).astype(np.float64)
            offset += points * 4
            q_values = np.frombuffer(payload, dtype="<f4", count=points, offset=offset).astype(np.float64)
            offset += points * 4
            offset += points * 4  # magnitude
            offset += points * 4  # RF
        z = i_values + 1j * q_values
        window = np.hanning(z.size)
        fft = np.fft.fftshift(np.fft.fft(z * window, n=fft_size))
        power_db = 10.0 * np.log10(np.maximum(np.abs(fft) ** 2, 1.0e-16))
        z_ac = z - np.mean(z) if z.size else z
        fft_ac = np.fft.fftshift(np.fft.fft(z_ac * window, n=fft_size))
        power_ac_db = 10.0 * np.log10(np.maximum(np.abs(fft_ac) ** 2, 1.0e-16))
        spectra_db.append(power_db)
        spectra_ac_db.append(power_ac_db)
        channel_info = {
            "points": int(points),
            "x_start_us": float(x_us[0]) if x_us.size else 0.0,
            "x_end_us": float(x_us[-1]) if x_us.size else 0.0,
            "rms_iq_display": float(np.sqrt(np.mean(np.abs(z) ** 2))) if z.size else 0.0,
            "top_peaks": _rank_power_peaks(
                power_db,
                freq_hz,
                center_mhz=center_mhz,
                bin_ids=bin_ids,
                count=top_count,
            ),
            "top_ac_peaks": _rank_power_peaks(
                power_ac_db,
                freq_hz,
                center_mhz=center_mhz,
                bin_ids=bin_ids,
                count=top_count,
            ),
        }
        if target_rf_mhz is not None:
            channel_info["target_rf_bin_raw"] = _target_power_metric(
                power_db,
                freq_hz,
                center_mhz=center_mhz,
                target_rf_mhz=float(target_rf_mhz),
                bin_ids=bin_ids,
                phase_rad=np.angle(fft),
                search_half_width_mhz=float(target_search_half_width_mhz),
            )
            channel_info["target_rf_bin"] = _target_power_metric(
                power_ac_db,
                freq_hz,
                center_mhz=center_mhz,
                target_rf_mhz=float(target_rf_mhz),
                bin_ids=bin_ids,
                phase_rad=np.angle(fft_ac),
                search_half_width_mhz=float(target_search_half_width_mhz),
            )
            mirror_rf_mhz = 2.0 * float(center_mhz) - float(target_rf_mhz)
            channel_info["mirror_rf_bin"] = _target_power_metric(
                power_ac_db,
                freq_hz,
                center_mhz=center_mhz,
                target_rf_mhz=mirror_rf_mhz,
                bin_ids=bin_ids,
                phase_rad=np.angle(fft_ac),
                search_half_width_mhz=float(target_search_half_width_mhz),
            )
            negative_edge_rf_mhz = float(center_mhz) - sample_rate / 2_000_000.0
            channel_info["negative_edge_bin"] = _target_power_metric(
                power_ac_db,
                freq_hz,
                center_mhz=center_mhz,
                target_rf_mhz=negative_edge_rf_mhz,
                bin_ids=bin_ids,
                phase_rad=np.angle(fft_ac),
                search_half_width_mhz=float(target_search_half_width_mhz),
            )
            channel_info["dc_bin_raw"] = _target_power_metric(
                power_db,
                freq_hz,
                center_mhz=center_mhz,
                target_rf_mhz=float(center_mhz),
                bin_ids=bin_ids,
                phase_rad=np.angle(fft),
                search_half_width_mhz=float(target_search_half_width_mhz),
            )
            channel_info["dc_bin_ac"] = _target_power_metric(
                power_ac_db,
                freq_hz,
                center_mhz=center_mhz,
                target_rf_mhz=float(center_mhz),
                bin_ids=bin_ids,
                phase_rad=np.angle(fft_ac),
                search_half_width_mhz=float(target_search_half_width_mhz),
            )
        channels[str(channel)] = channel_info
    if spectra_db:
        linear = np.mean([10.0 ** (power_db / 10.0) for power_db in spectra_db], axis=0)
        average_power_db = 10.0 * np.log10(np.maximum(linear, 1.0e-16))
        average_peaks = _rank_power_peaks(
            average_power_db,
            freq_hz,
            center_mhz=center_mhz,
            bin_ids=bin_ids,
            count=top_count,
        )
        linear_ac = np.mean([10.0 ** (power_db / 10.0) for power_db in spectra_ac_db], axis=0)
        average_ac_power_db = 10.0 * np.log10(np.maximum(linear_ac, 1.0e-16))
        average_ac_peaks = _rank_power_peaks(
            average_ac_power_db,
            freq_hz,
            center_mhz=center_mhz,
            bin_ids=bin_ids,
            count=top_count,
        )
        target_metric = (
            _target_power_metric(
                average_ac_power_db,
                freq_hz,
                center_mhz=center_mhz,
                target_rf_mhz=float(target_rf_mhz),
                bin_ids=bin_ids,
                search_half_width_mhz=float(target_search_half_width_mhz),
            )
            if target_rf_mhz is not None
            else None
        )
        target_metric_raw = (
            _target_power_metric(
                average_power_db,
                freq_hz,
                center_mhz=center_mhz,
                target_rf_mhz=float(target_rf_mhz),
                bin_ids=bin_ids,
                search_half_width_mhz=float(target_search_half_width_mhz),
            )
            if target_rf_mhz is not None
            else None
        )
        mirror_metric = (
            _target_power_metric(
                average_ac_power_db,
                freq_hz,
                center_mhz=center_mhz,
                target_rf_mhz=2.0 * float(center_mhz) - float(target_rf_mhz),
                bin_ids=bin_ids,
                search_half_width_mhz=float(target_search_half_width_mhz),
            )
            if target_rf_mhz is not None
            else None
        )
        negative_edge_metric = (
            _target_power_metric(
                average_ac_power_db,
                freq_hz,
                center_mhz=center_mhz,
                target_rf_mhz=float(center_mhz) - sample_rate / 2_000_000.0,
                bin_ids=bin_ids,
                search_half_width_mhz=float(target_search_half_width_mhz),
            )
            if target_rf_mhz is not None
            else None
        )
        dc_metric_raw = (
            _target_power_metric(
                average_power_db,
                freq_hz,
                center_mhz=center_mhz,
                target_rf_mhz=float(center_mhz),
                bin_ids=bin_ids,
                search_half_width_mhz=float(target_search_half_width_mhz),
            )
            if target_rf_mhz is not None
            else None
        )
        dc_metric_ac = (
            _target_power_metric(
                average_ac_power_db,
                freq_hz,
                center_mhz=center_mhz,
                target_rf_mhz=float(center_mhz),
                bin_ids=bin_ids,
                search_half_width_mhz=float(target_search_half_width_mhz),
            )
            if target_rf_mhz is not None
            else None
        )
    else:
        average_peaks = []
        average_ac_peaks = []
        target_metric = None
        target_metric_raw = None
        mirror_metric = None
        negative_edge_metric = None
        dc_metric_raw = None
        dc_metric_ac = None
    result = {
        "header": header,
        "nfft": fft_size,
        "average_peaks": average_peaks,
        "average_ac_peaks": average_ac_peaks,
        "channels": channels,
    }
    if target_metric is not None:
        result["target_rf_bin"] = target_metric
    if target_metric_raw is not None:
        result["target_rf_bin_raw"] = target_metric_raw
    if mirror_metric is not None:
        result["mirror_rf_bin"] = mirror_metric
    if negative_edge_metric is not None:
        result["negative_edge_bin"] = negative_edge_metric
    if dc_metric_raw is not None:
        result["dc_bin_raw"] = dc_metric_raw
    if dc_metric_ac is not None:
        result["dc_bin_ac"] = dc_metric_ac
    return result


def _spec_freq_hz(bins: int, sample_rate_hz: int) -> Any:
    import numpy as np

    indices = np.arange(int(bins), dtype=np.int64)
    signed = np.where(indices < bins // 2, indices, indices - bins)
    return signed.astype(np.float64) * (float(sample_rate_hz) / float(bins))


def _capture_rust_previews(
    base_url: str,
    *,
    center_mhz: float,
    bandwidth_mhz: int,
    expected_mhz: float,
    dac_mhz: float,
    target_rf_mhz: float | None,
    target_search_half_width_mhz: float,
    timeout: float,
    top_count: int,
    time_window_us: float,
    capture_retries: int,
    capture_waveform: bool,
    capture_spectrum: bool,
) -> dict[str, Any]:
    config_url = urllib.parse.urljoin(base_url.rstrip("/") + "/", "api/config")
    config_result = _safe_call(
        _http_json,
        config_url,
        {
            "bandwidth_mhz": int(bandwidth_mhz),
            "center_mhz": float(center_mhz),
            "expected_mhz": float(expected_mhz),
            "dac_mhz": float(dac_mhz),
            "waveform_view_mode": "dual",
            "channel_mask": 0xFF,
            "time_window_us": float(time_window_us),
            "display_points": 1024,
            "vertical_scale": 4096.0,
            "paused": False,
        },
        timeout,
    )
    time.sleep(0.25)
    result: dict[str, Any] = {"config_result": config_result}
    if capture_waveform:
        waveform_binary = _safe_call(_capture_ws_binary_retry, base_url, "/ws/waveform", timeout, capture_retries)
        if isinstance(waveform_binary, dict) and "error" in waveform_binary:
            result["waveform"] = waveform_binary
        else:
            result["waveform"] = _safe_call(
                _parse_tfw_waveform,
                waveform_binary,
                center_mhz=center_mhz,
                top_count=top_count,
                target_rf_mhz=target_rf_mhz,
                target_search_half_width_mhz=float(target_search_half_width_mhz),
            )
    if capture_spectrum:
        spectrum_binary = _safe_call(_capture_ws_binary_retry, base_url, "/ws/spectrum", timeout, capture_retries)
        if isinstance(spectrum_binary, dict) and "error" in spectrum_binary:
            result["spectrum"] = spectrum_binary
        else:
            result["spectrum"] = _safe_call(
                _parse_tsp3_spectrum,
                spectrum_binary,
                center_mhz=center_mhz,
                top_count=top_count,
                target_rf_mhz=target_rf_mhz,
                target_search_half_width_mhz=float(target_search_half_width_mhz),
            )
    return result


def _wait_not_error(core: Any, timeout: float) -> dict[str, Any]:
    deadline = time.monotonic() + float(timeout)
    last_status: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last_status = core.read_status()
        if int(last_status.get("fsm_state", 0)) != 8:
            return last_status
        time.sleep(0.02)
    raise RuntimeError(
        "sync FSM stayed in error after reset: "
        f"status=0x{int(last_status.get('status', 0)):08x} "
        f"rfdc_flags=0x{int(last_status.get('rfdc_status_flags', 0)):08x}"
    )


def _wait_streaming(core: Any, timeout: float) -> dict[str, Any]:
    deadline = time.monotonic() + float(timeout)
    last_status: dict[str, Any] = {}
    core.start()
    while time.monotonic() < deadline:
        last_status = core.read_status()
        if int(last_status.get("streaming", 0)) and int(last_status.get("rfdc_adc_valid", 0)):
            return last_status
        time.sleep(0.05)
    raise RuntimeError(
        "stream did not become ready: "
        f"streaming={last_status.get('streaming')} "
        f"rfdc_adc_valid={last_status.get('rfdc_adc_valid')} "
        f"status=0x{int(last_status.get('status', 0)):08x} "
        f"rfdc_flags=0x{int(last_status.get('rfdc_status_flags', 0)):08x}"
    )


def _prepare_stream_after_observation(core: Any, timeout: float) -> dict[str, Any]:
    # RFDC mixer/NCO reconfiguration can briefly deassert rfdc_ready. If the
    # production sync FSM is still armed during that window it correctly enters
    # ST_ERROR and stays there until a soft reset. Audit cases intentionally
    # change RFDC state, so reset the sync FSM before starting science again.
    core.reset()
    time.sleep(0.05)
    return _wait_not_error(core, timeout)


def _peak_list(case: dict[str, Any], source: str) -> list[dict[str, Any]]:
    if source in ("time", "production_time"):
        waveform = case.get("rust_time_waveform", {})
        return list(waveform.get("average_ac_peaks") or waveform.get("average_peaks") or [])
    if source in ("raw_preview", "rfdc_preview"):
        return list(case.get("time_preview", {}).get("average_peaks", []) or [])
    if source == "raw_lane":
        raw_lane = case.get("rfdc_axis_raw_witness")
        return list(raw_lane.get("average_ac_peaks") or raw_lane.get("average_peaks") or []) if isinstance(raw_lane, dict) else []
    if source == "raw_lane_decim2":
        raw_lane = case.get("rfdc_axis_raw_witness")
        decim2 = raw_lane.get("rtl_decim2_model") if isinstance(raw_lane, dict) else None
        return list(decim2.get("average_ac_peaks") or decim2.get("average_peaks") or []) if isinstance(decim2, dict) else []
    if source == "spec":
        return list(case.get("rust_spectrum", {}).get("average_peaks", []) or [])
    raise ValueError(f"unknown peak source {source!r}")


def _strong_peaks(peaks: list[dict[str, Any]], min_snr_db: float = 12.0) -> list[dict[str, Any]]:
    return [peak for peak in peaks if float(peak.get("snr_db", 0.0)) >= float(min_snr_db)]


def _primary_peak(case: dict[str, Any], source: str, *, min_snr_db: float = 12.0) -> dict[str, Any] | None:
    peaks = _strong_peaks(_peak_list(case, source), min_snr_db=min_snr_db)
    if not peaks:
        return None
    return peaks[0]


def _nearest_peak(target_peak: dict[str, Any], peaks: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, float | None]:
    if not peaks:
        return None, None
    nearest = min(peaks, key=lambda peak: abs(float(peak["baseband_mhz"]) - float(target_peak["baseband_mhz"])))
    return nearest, abs(float(nearest["baseband_mhz"]) - float(target_peak["baseband_mhz"]))


def _sideband_peak_from_peaks(peaks: list[dict[str, Any]], *, expected_abs_baseband_mhz: float, tolerance_mhz: float = 1.0) -> dict[str, Any] | None:
    candidates = [
        peak for peak in peaks
        if abs(abs(float(peak.get("baseband_mhz", 0.0))) - float(expected_abs_baseband_mhz)) <= float(tolerance_mhz)
    ]
    if not candidates:
        return None
    best = max(candidates, key=lambda peak: float(peak.get("snr_db", 0.0)))
    result = dict(best)
    result["sideband_sign"] = 1 if float(best.get("baseband_mhz", 0.0)) >= 0.0 else -1
    result["expected_abs_baseband_mhz"] = float(expected_abs_baseband_mhz)
    result["sideband_tolerance_mhz"] = float(tolerance_mhz)
    return result


def _case_sideband_evidence(case: dict[str, Any], *, target_rf_mhz: float, tolerance_mhz: float = 1.0) -> dict[str, Any]:
    center_mhz = float(case.get("center_mhz", 0.0))
    expected_abs = abs(float(target_rf_mhz) - center_mhz)
    raw_peak = _sideband_peak_from_peaks(_peak_list(case, "raw_preview"), expected_abs_baseband_mhz=expected_abs, tolerance_mhz=tolerance_mhz)
    spec_peak = _sideband_peak_from_peaks(_peak_list(case, "spec"), expected_abs_baseband_mhz=expected_abs, tolerance_mhz=tolerance_mhz)
    raw_primary = _primary_peak(case, "raw_preview", min_snr_db=0.0)
    spec_primary = _primary_peak(case, "spec", min_snr_db=0.0)
    return {
        "case": case.get("name"),
        "case_type": case.get("case_type"),
        "bandwidth_mhz": case.get("bandwidth_mhz"),
        "output_mode": case.get("output_mode"),
        "center_mhz": center_mhz,
        "target_rf_mhz": float(target_rf_mhz),
        "expected_abs_baseband_mhz": expected_abs,
        "valid_for_spur": case.get("valid_for_spur"),
        "invalid_for_spur_reason": case.get("invalid_for_spur_reason"),
        "fengine_clean_gate": case.get("fengine_clean_gate"),
        "raw_preview_peak": raw_peak,
        "spec_peak": spec_peak,
        "raw_primary_peak": raw_primary,
        "spec_primary_peak": spec_primary,
        "raw_sideband_sign": raw_peak.get("sideband_sign") if raw_peak else None,
        "spec_sideband_sign": spec_peak.get("sideband_sign") if spec_peak else None,
    }


def _consistency_rows(cases: list[dict[str, Any]], *, time_source: str) -> list[dict[str, Any]]:
    rows = []
    for case in cases:
        spec_peaks = _strong_peaks(_peak_list(case, "spec"))
        time_peaks = _strong_peaks(_peak_list(case, time_source))
        if not spec_peaks and not time_peaks:
            continue
        spec_peak = spec_peaks[0] if spec_peaks else None
        nearest, delta = _nearest_peak(spec_peak, time_peaks) if spec_peak is not None else (None, None)
        rows.append(
            {
                "case": case.get("name"),
                "time_source": time_source,
                "spec_baseband_mhz": spec_peak.get("baseband_mhz") if spec_peak else None,
                "spec_rf_mhz": spec_peak.get("rf_mhz") if spec_peak else None,
                "spec_snr_db": spec_peak.get("snr_db") if spec_peak else None,
                "nearest_time_baseband_mhz": nearest.get("baseband_mhz") if nearest else None,
                "nearest_time_rf_mhz": nearest.get("rf_mhz") if nearest else None,
                "nearest_time_snr_db": nearest.get("snr_db") if nearest else None,
                "nearest_time_delta_mhz": delta,
            }
        )
    return rows


def _target_metric(case: dict[str, Any], source: str) -> dict[str, Any] | None:
    if source == "production_time":
        metric = case.get("rust_time_waveform", {}).get("target_rf_bin")
    elif source == "raw_lane":
        metric = case.get("rfdc_axis_raw_witness", {}).get("target_rf_bin")
    elif source == "spec":
        metric = case.get("rust_spectrum", {}).get("target_rf_bin")
    else:
        raise ValueError(f"unknown target metric source {source!r}")
    return metric if isinstance(metric, dict) and metric.get("available") else None


def _named_preview_metric(case: dict[str, Any], source: str, key: str) -> dict[str, Any] | None:
    if source == "production_time":
        container = case.get("rust_time_waveform", {})
    elif source == "raw_lane":
        container = case.get("rfdc_axis_raw_witness", {})
    elif source == "spec":
        container = case.get("rust_spectrum", {})
    else:
        raise ValueError(f"unknown target metric source {source!r}")
    metric = container.get(key) if isinstance(container, dict) else None
    return metric if isinstance(metric, dict) and metric.get("available") else None


def _target_metric_rows(cases: list[dict[str, Any]], *, min_snr_db: float) -> list[dict[str, Any]]:
    rows = []
    for case in cases:
        time_metric = _target_metric(case, "production_time")
        spec_metric = _target_metric(case, "spec")
        rows.append(
            {
                "case": case.get("name"),
                "case_type": case.get("case_type"),
                "physical_state": case.get("physical_state"),
                "clock_ref": case.get("clock_ref"),
                "bandwidth_mhz": case.get("bandwidth_mhz"),
                "output_mode": case.get("output_mode"),
                "center_mhz": case.get("center_mhz"),
                "dac_mhz": case.get("dac_mhz"),
                "amplitude": case.get("amplitude"),
                "enable_mask": case.get("enable_mask"),
                "sysref_action": case.get("sysref_action"),
                "sysref_action_result": case.get("sysref_action_result"),
                "diag_control": case.get("diag_control"),
                "diag_after_config": case.get("diag_after_config"),
                "diag_after_science_readback": case.get("diag_after_science_readback"),
                "valid_for_spur": case.get("valid_for_spur"),
                "time_in_band": time_metric.get("in_band") if time_metric else None,
                "time_bin_rf_mhz": time_metric.get("bin_rf_mhz") if time_metric else None,
                "time_bin_error_khz": time_metric.get("bin_error_khz") if time_metric else None,
                "time_power_db": time_metric.get("power_db") if time_metric else None,
                "time_snr_db": time_metric.get("snr_db") if time_metric else None,
                "time_pass": bool(time_metric and time_metric.get("in_band") and float(time_metric.get("snr_db", 0.0)) >= min_snr_db),
                "spec_in_band": spec_metric.get("in_band") if spec_metric else None,
                "spec_bin_rf_mhz": spec_metric.get("bin_rf_mhz") if spec_metric else None,
                "spec_bin_error_khz": spec_metric.get("bin_error_khz") if spec_metric else None,
                "spec_power_db": spec_metric.get("power_db") if spec_metric else None,
                "spec_snr_db": spec_metric.get("snr_db") if spec_metric else None,
                "spec_pass": bool(spec_metric and spec_metric.get("in_band") and float(spec_metric.get("snr_db", 0.0)) >= min_snr_db),
            }
        )
    return rows


def _metric_pass(metric: dict[str, Any] | None, min_snr_db: float) -> bool:
    return bool(metric and metric.get("in_band") and float(metric.get("snr_db", 0.0)) >= float(min_snr_db))


def _metric_power(metric: dict[str, Any] | None) -> float | None:
    if not metric or not math.isfinite(float(metric.get("power_db", float("nan")))):
        return None
    return float(metric["power_db"])


def _rootcause_case_has_backpressure(case: dict[str, Any]) -> bool:
    gate = case.get("fengine_clean_gate") if isinstance(case.get("fengine_clean_gate"), dict) else {}
    nonzero_raw = gate.get("nonzero_error_deltas") if isinstance(gate, dict) else {}
    nonzero = nonzero_raw if isinstance(nonzero_raw, dict) else {}
    telemetry = case.get("rootcause_telemetry") if isinstance(case.get("rootcause_telemetry"), dict) else {}
    channelizer_raw = telemetry.get("channelizer_deltas") if isinstance(telemetry, dict) else {}
    channelizer = channelizer_raw if isinstance(channelizer_raw, dict) else {}
    for source in (nonzero, channelizer):
        if int(source.get("pfb_capture_backpressure_count", 0)) != 0:
            return True
        if int(source.get("pfb_xfft_data_out_halt_count", 0)) != 0:
            return True
    return False


def _rootcause_evidence_row(case: dict[str, Any], *, target_rf_mhz: float, min_snr_db: float) -> dict[str, Any]:
    spec_primary = _primary_peak(case, "spec", min_snr_db=0.0)
    time_primary = _primary_peak(case, "production_time", min_snr_db=0.0)
    raw_primary = _primary_peak(case, "raw_preview", min_snr_db=0.0)
    spec_target = _target_metric(case, "spec")
    time_target = _target_metric(case, "production_time")
    spec_mirror = _named_preview_metric(case, "spec", "mirror_rf_bin")
    time_mirror = _named_preview_metric(case, "production_time", "mirror_rf_bin")
    spec_negative_edge = _named_preview_metric(case, "spec", "negative_edge_bin")
    time_negative_edge = _named_preview_metric(case, "production_time", "negative_edge_bin")
    sample_rate_hz = None
    spectrum = case.get("rust_spectrum")
    if isinstance(spectrum, dict):
        header = spectrum.get("header")
        if isinstance(header, dict):
            sample_rate_hz = header.get("sample_rate_hz")
    return {
        "case": case.get("name"),
        "case_type": case.get("case_type"),
        "rootcause_role": case.get("rootcause_role"),
        "physical_state": case.get("physical_state"),
        "clock_ref": case.get("clock_ref"),
        "bandwidth_mhz": case.get("bandwidth_mhz"),
        "output_mode": case.get("output_mode"),
        "center_mhz": case.get("center_mhz"),
        "target_rf_mhz": float(target_rf_mhz),
        "sample_rate_hz": sample_rate_hz,
        "valid_for_spur": case.get("valid_for_spur"),
        "invalid_for_spur_reason": case.get("invalid_for_spur_reason"),
        "target_search_half_width_mhz": case.get("rust_spectrum", {}).get("target_rf_bin", {}).get("search_half_width_mhz")
        if isinstance(case.get("rust_spectrum"), dict)
        else None,
        "time_target": time_target,
        "spec_target": spec_target,
        "time_target_pass": _metric_pass(time_target, min_snr_db),
        "spec_target_pass": _metric_pass(spec_target, min_snr_db),
        "time_mirror": time_mirror,
        "spec_mirror": spec_mirror,
        "time_negative_edge": time_negative_edge,
        "spec_negative_edge": spec_negative_edge,
        "time_primary_peak": time_primary,
        "spec_primary_peak": spec_primary,
        "raw_preview_primary_peak": raw_primary,
        "has_xfft_or_capture_backpressure": _rootcause_case_has_backpressure(case),
        "fengine_clean_reasons": list((case.get("fengine_clean_gate") or {}).get("reasons", []))
        if isinstance(case.get("fengine_clean_gate"), dict)
        else [],
        "fengine_nonzero_error_deltas": (case.get("fengine_clean_gate") or {}).get("nonzero_error_deltas", {})
        if isinstance(case.get("fengine_clean_gate"), dict)
        else {},
        "rootcause_telemetry_rates": (case.get("rootcause_telemetry") or {}).get("rates", {})
        if isinstance(case.get("rootcause_telemetry"), dict)
        else {},
        "rootcause_telemetry_channelizer_deltas": (case.get("rootcause_telemetry") or {}).get("channelizer_deltas", {})
        if isinstance(case.get("rootcause_telemetry"), dict)
        else {},
        "spec_route_delta": (case.get("rootcause_telemetry") or {}).get("spec_route_delta", {})
        if isinstance(case.get("rootcause_telemetry"), dict)
        else {},
        "time_route_delta": (case.get("rootcause_telemetry") or {}).get("time_route_delta", {})
        if isinstance(case.get("rootcause_telemetry"), dict)
        else {},
        "rfdc_readback_check": case.get("rfdc_readback_check"),
    }


def _row_required_pass(row: dict[str, Any]) -> bool:
    mode = str(row.get("output_mode", "time_spec")).upper()
    time_ok = bool(row.get("time_pass"))
    spec_ok = bool(row.get("spec_pass"))
    if mode == "TIME_ONLY":
        return time_ok
    if mode == "SPEC_ONLY":
        return spec_ok
    return time_ok and spec_ok


def _row_required_power_values(row: dict[str, Any]) -> list[float]:
    mode = str(row.get("output_mode", "time_spec")).upper()
    values: list[float] = []
    if mode in ("TIME_ONLY", "TIME_SPEC", "DUAL") and row.get("time_power_db") is not None:
        values.append(float(row["time_power_db"]))
    if mode in ("SPEC_ONLY", "TIME_SPEC", "DUAL") and row.get("spec_power_db") is not None:
        values.append(float(row["spec_power_db"]))
    return [value for value in values if math.isfinite(value)]


def _row_required_power(row: dict[str, Any]) -> float | None:
    values = _row_required_power_values(row)
    if not values:
        return None
    return sum(values) / float(len(values))


def _extract_mixer_freq_mhz(settings: dict[str, Any]) -> float | None:
    for key in ("Freq", "Frequency", "MixerFrequency", "NCOFrequency", "NCO_Freq"):
        value = settings.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except Exception:
            continue
    return None


def _rfdc_readback_check(case: dict[str, Any], *, tolerance_mhz: float = 0.25) -> dict[str, Any]:
    status = case.get("rfdc_sync_status")
    if not isinstance(status, dict):
        return {"available": False, "mismatches": [], "reason": "missing rfdc_sync_status"}
    def compact(value: Any) -> Any:
        converted = _jsonable(value)
        try:
            json.dumps(converted)
            return converted
        except TypeError:
            return repr(value)

    center = float(case.get("center_mhz", 0.0))
    dac_mhz = float(case.get("dac_mhz", center))
    blocks = []
    mismatches = []
    readable_adc = 0
    readable_dac = 0
    for tile in status.get("blocks", []) or []:
        if not isinstance(tile, dict):
            continue
        kind = str(tile.get("kind", ""))
        for block in tile.get("blocks", []) or []:
            if not isinstance(block, dict):
                continue
            settings = block.get("MixerSettings")
            settings = settings if isinstance(settings, dict) else {}
            freq = _extract_mixer_freq_mhz(settings)
            readback = block.get("status_readback")
            readback = readback if isinstance(readback, dict) else {}
            item = {
                "kind": kind,
                "tile": tile.get("tile"),
                "block": block.get("block"),
                "mixer_freq_mhz": freq,
                "decimation_factor": compact(readback.get("DecimationFactor")),
                "interpolation_factor": compact(readback.get("InterpolationFactor")),
                "nyquist_zone": compact(readback.get("NyquistZone")),
                "qmc_settings": compact(readback.get("QMCSettings")),
            }
            blocks.append(item)
            if freq is None:
                continue
            if kind == "adc":
                readable_adc += 1
                if abs(freq - (-center)) > tolerance_mhz:
                    mismatches.append({"kind": kind, "tile": tile.get("tile"), "block": block.get("block"), "expected_mhz": -center, "actual_mhz": freq})
            elif kind == "dac":
                readable_dac += 1
                if abs(freq - dac_mhz) > tolerance_mhz:
                    mismatches.append({"kind": kind, "tile": tile.get("tile"), "block": block.get("block"), "expected_mhz": dac_mhz, "actual_mhz": freq})
    return {
        "available": bool(blocks),
        "readable_adc_mixer_count": readable_adc,
        "readable_dac_mixer_count": readable_dac,
        "mismatches": mismatches,
        "blocks": blocks,
    }


def _sync_readback_summary(case: dict[str, Any]) -> dict[str, Any]:
    status = case.get("status") if isinstance(case.get("status"), dict) else {}
    lmk = case.get("lmk_status") if isinstance(case.get("lmk_status"), dict) else {}
    rfdc = case.get("rfdc_sync_status") if isinstance(case.get("rfdc_sync_status"), dict) else {}
    external = case.get("external_sync_diagnostics") if isinstance(case.get("external_sync_diagnostics"), dict) else {}
    configured_ref_code = int(status.get("configured_clock_ref", -1)) if status else -1
    configured_sync_code = int(status.get("configured_sync_mode", -1)) if status else -1
    active_sync_code = int(status.get("active_sync_mode", -1)) if status else -1
    last_sysref = rfdc.get("last_sysref_lock") if isinstance(rfdc.get("last_sysref_lock"), dict) else {}
    return {
        "requested_clock_ref": case.get("clock_ref"),
        "requested_sync_mode": case.get("sync_mode"),
        "configured_clock_ref_code": configured_ref_code,
        "configured_clock_ref": CLOCK_REF_NAMES.get(configured_ref_code, f"unknown_{configured_ref_code}"),
        "configured_sync_mode_code": configured_sync_code,
        "configured_sync_mode": SYNC_MODE_NAMES.get(configured_sync_code, f"unknown_{configured_sync_code}"),
        "active_sync_mode_code": active_sync_code,
        "active_sync_mode": SYNC_MODE_NAMES.get(active_sync_code, f"unknown_{active_sync_code}"),
        "pps_count": int(status.get("pps_count", 0)) if status else None,
        "pps_recent": bool(status.get("pps_recent", 0)) if status else None,
        "pps_input_high": bool(status.get("pps_input_high", 0)) if status else None,
        "ref_status_locked": bool(status.get("ref_status_locked", 0)) if status else None,
        "rfdc_clock_locked": bool(status.get("rfdc_clock_locked", 0)) if status else None,
        "lmk_configured": lmk.get("configured"),
        "lmk_selected_ref": lmk.get("selected_ref", lmk.get("ref")),
        "external_sync_classification": external.get("classification"),
        "external_sync_ok": external.get("ok"),
        "external_sync_pps_delta": external.get("pps_delta"),
        "rfdc_mts_enable": rfdc.get("mts_enable"),
        "rfdc_driver_classification": (
            rfdc.get("driver", {}).get("classification")
            if isinstance(rfdc.get("driver"), dict)
            else None
        ),
        "last_sysref_lock_keys": sorted(last_sysref.keys()) if isinstance(last_sysref, dict) else [],
        "last_sysref_configured": last_sysref.get("configured") if isinstance(last_sysref, dict) else None,
        "last_sysref_mts_available": last_sysref.get("mts_available") if isinstance(last_sysref, dict) else None,
    }


def _readback_mismatches(valid_cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    readback_checks = [case.get("rfdc_readback_check") for case in valid_cases if isinstance(case.get("rfdc_readback_check"), dict)]
    return [
        mismatch
        for check in readback_checks
        for mismatch in check.get("mismatches", [])
        if isinstance(check, dict)
    ]


def _reference_tone_check(cases: list[dict[str, Any]], *, min_snr_db: float, tolerance_mhz: float = 0.5) -> dict[str, Any]:
    refs = [case for case in cases if case.get("case_type") == "reference_tone_on"]
    if not refs:
        return {"available": False, "ok": False, "reason": "reference case missing"}
    case = refs[0]
    expected = float(case.get("expected_mhz", case.get("dac_mhz", 0.0)))
    time_peak = _primary_peak(case, "production_time", min_snr_db=min_snr_db)
    spec_peak = _primary_peak(case, "spec", min_snr_db=min_snr_db)
    time_delta = abs(float(time_peak["rf_mhz"]) - expected) if time_peak else None
    spec_delta = abs(float(spec_peak["rf_mhz"]) - expected) if spec_peak else None
    ok = bool(
        time_peak
        and spec_peak
        and time_delta is not None
        and spec_delta is not None
        and time_delta <= tolerance_mhz
        and spec_delta <= tolerance_mhz
    )
    return {
        "available": True,
        "ok": ok,
        "expected_mhz": expected,
        "tolerance_mhz": float(tolerance_mhz),
        "time_peak": time_peak,
        "spec_peak": spec_peak,
        "time_delta_mhz": time_delta,
        "spec_delta_mhz": spec_delta,
        "reason": None if ok else "reference tone peak missing or outside tolerance",
    }


def _classify_board_internal(cases: list[dict[str, Any]], *, target_rf_mhz: float, min_snr_db: float) -> dict[str, Any]:
    invalid_cases = [
        {
            "case": case.get("name"),
            "reason": case.get("invalid_for_spur_reason") or case.get("error") or "not marked valid_for_spur",
            "fengine_clean_gate": case.get("fengine_clean_gate"),
        }
        for case in cases
        if case.get("valid_for_spur") is not True
    ]
    valid_cases = [case for case in cases if case.get("valid_for_spur") is True and not case.get("error")]
    target_rows = _target_metric_rows(valid_cases, min_snr_db=min_snr_db)
    readback_mismatches = _readback_mismatches(valid_cases)
    if readback_mismatches:
        return {
            "classification": "rfdc_mixer_config_suspect",
            "reason": "RFDC mixer/readback does not match requested center/DAC NCO during board-internal sweep",
            "target_rf_mhz": float(target_rf_mhz),
            "min_snr_db": float(min_snr_db),
            "rfdc_mismatches": readback_mismatches,
            "target_rows": target_rows,
            "invalid_cases": invalid_cases,
            "allowed_classifications": list(ALLOWED_STAGE27I_SPUR_CLASSIFICATIONS),
        }

    def row_pass(row: dict[str, Any]) -> bool:
        mode = str(row.get("output_mode", "time_spec")).upper()
        time_ok = bool(row.get("time_pass"))
        spec_ok = bool(row.get("spec_pass"))
        if mode == "TIME_ONLY":
            return time_ok
        if mode == "SPEC_ONLY":
            return spec_ok
        return time_ok and spec_ok

    clock_rows = [row for row in target_rows if row.get("case_type") == "board_internal_clock_ref"]
    mode_rows = [row for row in target_rows if row.get("case_type") == "board_internal_mode_sweep"]
    clock_pass = [row for row in clock_rows if row_pass(row)]
    mode_pass = [row for row in mode_rows if row_pass(row)]
    clock_refs_seen = sorted({str(row.get("clock_ref")) for row in clock_pass if row.get("clock_ref") is not None})
    mode_cases_seen = sorted(
        {
            f"{row.get('bandwidth_mhz')}MHz:{row.get('output_mode')}"
            for row in mode_pass
            if row.get("bandwidth_mhz") is not None and row.get("output_mode") is not None
        }
    )
    if len(clock_refs_seen) >= 2 and len(mode_cases_seen) >= 2:
        classification = "adc_or_board_fixed_rf_suspect"
        reason = "target RF spur persists across clock-reference and production-mode sweeps"
    elif len(clock_refs_seen) >= 2:
        classification = "adc_or_board_fixed_rf_suspect"
        reason = "target RF spur persists across clock-reference sweep"
    elif len(mode_cases_seen) >= 2:
        classification = "adc_or_board_fixed_rf_suspect"
        reason = "target RF spur persists across production-mode sweep"
    else:
        classification = "inconclusive"
        reason = "not enough board-internal cases exceeded the target RF SNR threshold"
    return {
        "classification": classification,
        "reason": reason,
        "target_rf_mhz": float(target_rf_mhz),
        "min_snr_db": float(min_snr_db),
        "clock_refs_with_target": clock_refs_seen,
        "mode_cases_with_target": mode_cases_seen,
        "target_rows": target_rows,
        "invalid_cases": invalid_cases,
        "allowed_classifications": list(ALLOWED_STAGE27I_SPUR_CLASSIFICATIONS),
    }


def _classify_stage27i_diag(cases: list[dict[str, Any]], *, target_rf_mhz: float, min_snr_db: float) -> dict[str, Any]:
    invalid_cases = [
        {
            "case": case.get("name"),
            "reason": case.get("invalid_for_spur_reason") or case.get("error") or "not marked valid_for_spur",
            "fengine_clean_gate": case.get("fengine_clean_gate"),
        }
        for case in cases
        if case.get("valid_for_spur") is not True
    ]
    valid_cases = [case for case in cases if case.get("valid_for_spur") is True and not case.get("error")]
    target_rows = _target_metric_rows(valid_cases, min_snr_db=min_snr_db)
    readback_mismatches = _readback_mismatches(valid_cases)
    if readback_mismatches:
        return {
            "classification": "rfdc_mixer_config_suspect",
            "reason": "RFDC mixer/readback does not match requested center/DAC NCO during Stage 27i diagnostic audit",
            "target_rf_mhz": float(target_rf_mhz),
            "min_snr_db": float(min_snr_db),
            "invalid_cases": invalid_cases,
            "rfdc_mismatches": readback_mismatches,
            "target_rows": target_rows,
            "allowed_classifications": list(ALLOWED_STAGE27I_SPUR_CLASSIFICATIONS),
        }

    def row_pass(row: dict[str, Any]) -> bool:
        return bool(row.get("time_pass")) or bool(row.get("spec_pass"))

    def rows_for(case_type: str) -> list[dict[str, Any]]:
        return [row for row in target_rows if row.get("case_type") == case_type]

    default_rows = rows_for("stage27i_diag_default_off")
    force_zero_rows = rows_for("stage27i_diag_adc_force_zero")
    force_hold_rows = rows_for("stage27i_diag_adc_force_hold")
    dac_gate_rows = rows_for("stage27i_diag_dac_gate")
    isolate_rows = rows_for("stage27i_diag_channel_isolate")

    default_ok = any(row_pass(row) for row in default_rows)
    force_zero_ok = any(row_pass(row) for row in force_zero_rows)
    force_hold_ok = any(row_pass(row) for row in force_hold_rows)
    dac_gate_ok = any(row_pass(row) for row in dac_gate_rows)
    isolate_hits = [
        {
            "case": row.get("case"),
            "diag_control": row.get("diag_control"),
            "time_snr_db": row.get("time_snr_db"),
            "spec_snr_db": row.get("spec_snr_db"),
            "time_pass": row.get("time_pass"),
            "spec_pass": row.get("spec_pass"),
        }
        for row in isolate_rows
        if row_pass(row)
    ]

    if not default_ok:
        classification = "inconclusive"
        reason = "default-off diagnostic case did not see the target spur, so diagnostic comparisons are not meaningful"
    elif force_zero_ok:
        classification = "inconclusive"
        reason = "target spur persists after RFDC AXIS force-zero; downstream digital path must be rechecked before assigning a Stage 27i root-cause class"
    elif force_zero_rows and not force_zero_ok:
        classification = "adc_or_rfdc_frontend_spur_confirmed_by_axis_zero"
        reason = "target spur is present with diagnostics off and disappears after RFDC AXIS force-zero"
    elif force_hold_rows and not force_hold_ok:
        classification = "adc_or_rfdc_frontend_spur_confirmed_by_axis_zero"
        reason = "target spur is present with diagnostics off and disappears when RFDC AXIS data is held constant"
    elif dac_gate_rows and not dac_gate_ok:
        classification = "inconclusive"
        reason = "target spur changes when DAC AXIS digital output is gated; DAC coupling requires a separate audit before assigning root cause"
    else:
        classification = "inconclusive"
        reason = "diagnostic cases did not cleanly separate RFDC-front-end and downstream digital sources"

    return {
        "classification": classification,
        "reason": reason,
        "target_rf_mhz": float(target_rf_mhz),
        "min_snr_db": float(min_snr_db),
        "invalid_cases": invalid_cases,
        "target_rows": target_rows,
        "default_off_has_target": default_ok,
        "force_zero_has_target": force_zero_ok,
        "force_hold_has_target": force_hold_ok,
        "dac_gate_has_target": dac_gate_ok,
        "channel_isolate_hits": isolate_hits,
        "allowed_classifications": list(ALLOWED_STAGE27I_SPUR_CLASSIFICATIONS),
    }


def _classify_stage27i_front_end(cases: list[dict[str, Any]], *, target_rf_mhz: float, min_snr_db: float) -> dict[str, Any]:
    invalid_cases = [
        {
            "case": case.get("name"),
            "reason": case.get("invalid_for_spur_reason") or case.get("error") or "not marked valid_for_spur",
            "fengine_clean_gate": case.get("fengine_clean_gate"),
        }
        for case in cases
        if case.get("valid_for_spur") is not True
    ]
    valid_cases = [case for case in cases if case.get("valid_for_spur") is True and not case.get("error")]
    target_rows = _target_metric_rows(valid_cases, min_snr_db=min_snr_db)
    readback_mismatches = _readback_mismatches(valid_cases)
    if readback_mismatches:
        return {
            "classification": "rfdc_adc_config_or_internal_suspect",
            "reason": "RFDC ADC/DAC readback does not match requested mixer/decimation state during Stage 27i front-end audit",
            "target_rf_mhz": float(target_rf_mhz),
            "min_snr_db": float(min_snr_db),
            "invalid_cases": invalid_cases,
            "rfdc_mismatches": readback_mismatches,
            "target_rows": target_rows,
            "allowed_classifications": list(ALLOWED_STAGE27I_SPUR_CLASSIFICATIONS),
        }

    def rows_for(case_type: str) -> list[dict[str, Any]]:
        return [row for row in target_rows if row.get("case_type") == case_type]

    baseline_rows = rows_for("stage27i_frontend_baseline")
    force_zero_rows = rows_for("stage27i_frontend_force_zero_sentinel")
    clock_rows = rows_for("stage27i_frontend_clock_ref")
    mode_rows = rows_for("stage27i_frontend_mode_sweep")
    center_rows = rows_for("stage27i_frontend_center_sweep")
    sysref_rows = rows_for("stage27i_frontend_sysref_pulse")

    baseline_ok = any(_row_required_pass(row) for row in baseline_rows)
    force_zero_has_target = any(_row_required_pass(row) for row in force_zero_rows)
    force_zero_clears = bool(force_zero_rows) and not force_zero_has_target

    baseline_power = next((_row_required_power(row) for row in baseline_rows if _row_required_power(row) is not None), None)
    clock_sensitive_evidence = []
    for row in [*clock_rows, *sysref_rows]:
        power = _row_required_power(row)
        if power is None or baseline_power is None:
            continue
        delta = power - baseline_power
        if abs(delta) >= 12.0:
            clock_sensitive_evidence.append(
                {
                    "case": row.get("case"),
                    "case_type": row.get("case_type"),
                    "clock_ref": row.get("clock_ref"),
                    "sysref_action": row.get("sysref_action"),
                    "baseline_power_db": baseline_power,
                    "power_db": power,
                    "power_delta_db": delta,
                }
            )
    if baseline_ok:
        for row in [*clock_rows, *sysref_rows]:
            if not _row_required_pass(row):
                clock_sensitive_evidence.append(
                    {
                        "case": row.get("case"),
                        "case_type": row.get("case_type"),
                        "clock_ref": row.get("clock_ref"),
                        "sysref_action": row.get("sysref_action"),
                        "reason": "target RF spur dropped below threshold relative to baseline",
                        "time_snr_db": row.get("time_snr_db"),
                        "spec_snr_db": row.get("spec_snr_db"),
                    }
                )

    mode_missing = [
        {
            "case": row.get("case"),
            "bandwidth_mhz": row.get("bandwidth_mhz"),
            "output_mode": row.get("output_mode"),
            "time_snr_db": row.get("time_snr_db"),
            "spec_snr_db": row.get("spec_snr_db"),
        }
        for row in mode_rows
        if not _row_required_pass(row)
    ]
    center_missing = [
        {
            "case": row.get("case"),
            "center_mhz": row.get("center_mhz"),
            "time_snr_db": row.get("time_snr_db"),
            "spec_snr_db": row.get("spec_snr_db"),
        }
        for row in center_rows
        if not _row_required_pass(row)
    ]
    clock_refs_with_target = sorted({str(row.get("clock_ref")) for row in clock_rows if _row_required_pass(row)})
    mode_cases_with_target = sorted(
        {
            f"{row.get('bandwidth_mhz')}MHz:{row.get('output_mode')}"
            for row in mode_rows
            if _row_required_pass(row)
        }
    )
    centers_with_target = sorted(
        {
            round(float(row.get("center_mhz", 0.0)), 6)
            for row in center_rows
            if _row_required_pass(row)
        }
    )

    if not baseline_ok:
        classification = "stage27i_frontend_inconclusive"
        reason = "baseline external-10MHz/PPS diagnostic-off case did not see the target spur"
    elif not force_zero_clears:
        classification = "stage27i_frontend_inconclusive"
        reason = "RFDC AXIS force-zero sentinel did not clear the target spur, so front-end classification is not valid"
    elif clock_sensitive_evidence:
        classification = "lmk_sysref_or_clock_coupling_suspect"
        reason = "target RF spur changes significantly with clock-reference or SYSREF pulse state"
    elif mode_missing or center_missing:
        classification = "rfdc_adc_config_or_internal_suspect"
        reason = "target RF spur is not stable across RFDC bandwidth/decimation or ADC mixer center sweep despite clean readback"
    elif clock_rows and mode_rows and center_rows:
        classification = "adc_input_frontend_or_board_analog_suspect"
        reason = "target RF spur is present with diagnostics off, cleared by RFDC AXIS force-zero, and stable across software clock/RFDC state changes"
    else:
        classification = "stage27i_frontend_inconclusive"
        reason = "front-end audit did not collect enough valid clock, mode, and center cases"

    return {
        "classification": classification,
        "reason": reason,
        "target_rf_mhz": float(target_rf_mhz),
        "min_snr_db": float(min_snr_db),
        "invalid_cases": invalid_cases,
        "target_rows": target_rows,
        "baseline_has_target": baseline_ok,
        "force_zero_clears_target": force_zero_clears,
        "force_zero_has_target": force_zero_has_target,
        "clock_sensitive_evidence": clock_sensitive_evidence,
        "mode_missing_target": mode_missing,
        "center_missing_target": center_missing,
        "clock_refs_with_target": clock_refs_with_target,
        "mode_cases_with_target": mode_cases_with_target,
        "centers_with_target": centers_with_target,
        "allowed_classifications": list(ALLOWED_STAGE27I_SPUR_CLASSIFICATIONS),
    }


def _classify_stage27i_spec_sideband(cases: list[dict[str, Any]], *, target_rf_mhz: float, min_snr_db: float) -> dict[str, Any]:
    evidence = [
        _case_sideband_evidence(case, target_rf_mhz=target_rf_mhz, tolerance_mhz=1.0)
        for case in cases
        if case.get("case_type") == "stage27i_spec_sideband"
    ]
    by_bw = {int(row["bandwidth_mhz"]): row for row in evidence if row.get("bandwidth_mhz") is not None}
    row_100 = by_bw.get(100)
    row_200 = by_bw.get(200)
    invalid_cases = [
        {
            "case": case.get("name"),
            "reason": case.get("invalid_for_spur_reason") or case.get("error") or "not marked valid_for_spur",
            "fengine_clean_gate": case.get("fengine_clean_gate"),
        }
        for case in cases
        if case.get("valid_for_spur") is not True
    ]

    def peak_ok(row: dict[str, Any] | None, key: str) -> bool:
        if not row:
            return False
        peak = row.get(key)
        return bool(isinstance(peak, dict) and float(peak.get("snr_db", 0.0)) >= float(min_snr_db))

    raw_ok = peak_ok(row_100, "raw_preview_peak") and peak_ok(row_200, "raw_preview_peak")
    spec_ok = peak_ok(row_100, "spec_peak") and peak_ok(row_200, "spec_peak")
    def primary_ok(row: dict[str, Any] | None, key: str) -> bool:
        if not row:
            return False
        peak = row.get(key)
        return bool(isinstance(peak, dict) and float(peak.get("snr_db", 0.0)) >= float(min_snr_db))

    if not row_100 or not row_200:
        classification = "stage27i_spec_sideband_inconclusive"
        reason = "sideband audit did not collect both 100MHz and 200MHz SPEC_ONLY cases"
    elif peak_ok(row_100, "spec_peak") and not peak_ok(row_200, "spec_peak") and primary_ok(row_200, "spec_primary_peak"):
        classification = "rfdc_adc_config_or_internal_suspect"
        reason = "100MHz SPEC_ONLY sees the target RF sideband, but 200MHz SPEC_ONLY suppresses that target and produces a different dominant SPEC peak"
    elif not spec_ok:
        classification = "stage27i_spec_sideband_inconclusive"
        reason = "SPEC sideband peaks were not strong enough in both bandwidth cases"
    else:
        raw_sign_100 = row_100.get("raw_sideband_sign")
        raw_sign_200 = row_200.get("raw_sideband_sign")
        spec_sign_100 = row_100.get("spec_sideband_sign")
        spec_sign_200 = row_200.get("spec_sideband_sign")
        if spec_sign_100 != spec_sign_200 and raw_ok and raw_sign_100 == raw_sign_200:
            classification = "spec_frequency_axis_or_packer_mapping_suspect"
            reason = "SPEC sideband sign changes between 100MHz and 200MHz while RFDC raw preview sideband sign does not"
        elif spec_sign_100 != spec_sign_200 and raw_ok and raw_sign_100 != raw_sign_200:
            classification = "rfdc_decimation_sideband_flip_suspect"
            reason = "RFDC raw preview and SPEC both change sideband sign between 100MHz and 200MHz"
        elif spec_sign_100 == spec_sign_200 and raw_ok and raw_sign_100 != spec_sign_100:
            classification = "spec_frequency_axis_or_packer_mapping_suspect"
            reason = "SPEC and RFDC raw preview disagree on sideband sign"
        elif spec_sign_100 == spec_sign_200:
            classification = "stage27i_spec_sideband_inconclusive"
            reason = "SPEC sideband sign did not reproduce the reported 100MHz/200MHz flip"
        else:
            classification = "stage27i_spec_sideband_inconclusive"
            reason = "RFDC raw preview sideband evidence was not strong enough to separate RFDC and SPEC mapping"

    return {
        "classification": classification,
        "reason": reason,
        "target_rf_mhz": float(target_rf_mhz),
        "min_snr_db": float(min_snr_db),
        "evidence": evidence,
        "invalid_cases": invalid_cases,
        "allowed_classifications": list(ALLOWED_STAGE27I_SPUR_CLASSIFICATIONS),
        "note": "Sideband audit may keep dirty SPEC previews for diagnosis; clean-gate failures are retained in invalid_cases instead of hidden.",
    }


def _wrap_degrees(value: float) -> float:
    wrapped = (float(value) + 180.0) % 360.0 - 180.0
    return 180.0 if wrapped == -180.0 else wrapped


def _phase_rad_to_deg(value: Any) -> float | None:
    try:
        phase = float(value)
    except Exception:
        return None
    if not math.isfinite(phase):
        return None
    return _wrap_degrees(math.degrees(phase))


def _channel_relative_phases(
    container: dict[str, Any],
    metric_key: str,
    *,
    ref_channel: str = "1",
) -> dict[str, Any]:
    channels = container.get("channels") if isinstance(container, dict) else {}
    if not isinstance(channels, dict):
        return {"available": False, "reason": "missing channels"}
    ref_metric = channels.get(ref_channel, {}).get(metric_key) if isinstance(channels.get(ref_channel), dict) else None
    ref_phase = _phase_rad_to_deg(ref_metric.get("phase_rad")) if isinstance(ref_metric, dict) else None
    if ref_phase is None:
        for channel, info in sorted(channels.items()):
            metric = info.get(metric_key) if isinstance(info, dict) else None
            phase = _phase_rad_to_deg(metric.get("phase_rad")) if isinstance(metric, dict) else None
            if phase is not None:
                ref_channel = str(channel)
                ref_phase = phase
                break
    if ref_phase is None:
        return {"available": False, "reason": f"missing {metric_key} phase"}
    values: dict[str, Any] = {}
    for channel, info in sorted(channels.items()):
        metric = info.get(metric_key) if isinstance(info, dict) else None
        phase = _phase_rad_to_deg(metric.get("phase_rad")) if isinstance(metric, dict) else None
        if phase is None:
            continue
        values[str(channel)] = {
            "phase_deg": phase,
            "relative_deg": _wrap_degrees(phase - ref_phase),
            "snr_db": metric.get("snr_db") if isinstance(metric, dict) else None,
            "power_db": metric.get("power_db") if isinstance(metric, dict) else None,
        }
    return {"available": bool(values), "ref_channel": ref_channel, "values": values}


def _relative_phase_delta_evidence(
    baseline: dict[str, Any] | None,
    row: dict[str, Any],
    *,
    phase_key: str = "time_relative_phases",
    threshold_deg: float = 45.0,
    min_snr_db: float = 12.0,
) -> dict[str, Any] | None:
    if not baseline:
        return None
    base_phases = baseline.get(phase_key, {})
    row_phases = row.get(phase_key, {})
    if not (isinstance(base_phases, dict) and isinstance(row_phases, dict)):
        return None
    base_values = base_phases.get("values") if base_phases.get("available") else {}
    row_values = row_phases.get("values") if row_phases.get("available") else {}
    if not (isinstance(base_values, dict) and isinstance(row_values, dict)):
        return None
    deltas = {}
    for channel, base in base_values.items():
        other = row_values.get(channel)
        if not isinstance(base, dict) or not isinstance(other, dict):
            continue
        try:
            base_snr = float(base.get("snr_db", float("-inf")))
            other_snr = float(other.get("snr_db", float("-inf")))
        except Exception:
            continue
        if base_snr < float(min_snr_db) or other_snr < float(min_snr_db):
            continue
        if base.get("relative_deg") is None or other.get("relative_deg") is None:
            continue
        delta = _wrap_degrees(float(other["relative_deg"]) - float(base["relative_deg"]))
        if abs(delta) >= float(threshold_deg):
            deltas[channel] = delta
    if not deltas:
        return None
    return {
        "case": row.get("case"),
        "baseline_case": baseline.get("case"),
        "reason": "relative channel phase changed across NCO/SYSREF operation",
        "phase_key": phase_key,
        "threshold_deg": float(threshold_deg),
        "channel_phase_delta_deg": deltas,
    }


def _taxonomy_effective_time_metric(row: dict[str, Any], *, target_rf_mhz: float) -> dict[str, Any] | None:
    center_mhz = float(row.get("center_mhz", 0.0))
    if abs(center_mhz - float(target_rf_mhz)) <= 0.5:
        metric = row.get("time_target_raw")
        if isinstance(metric, dict):
            return metric
    metric = row.get("time_target")
    return metric if isinstance(metric, dict) else None


def _taxonomy_metric_pass(metric: dict[str, Any] | None, min_snr_db: float) -> bool:
    return bool(metric and metric.get("in_band") and float(metric.get("snr_db", 0.0)) >= float(min_snr_db))


def _taxonomy_evidence_row(case: dict[str, Any], *, target_rf_mhz: float, min_snr_db: float) -> dict[str, Any]:
    waveform = case.get("rust_time_waveform") if isinstance(case.get("rust_time_waveform"), dict) else {}
    spectrum = case.get("rust_spectrum") if isinstance(case.get("rust_spectrum"), dict) else {}
    time_target = _target_metric(case, "production_time")
    spec_target = _target_metric(case, "spec")
    time_target_raw = waveform.get("target_rf_bin_raw") if isinstance(waveform.get("target_rf_bin_raw"), dict) else None
    time_dc_raw = waveform.get("dc_bin_raw") if isinstance(waveform.get("dc_bin_raw"), dict) else None
    time_dc_ac = waveform.get("dc_bin_ac") if isinstance(waveform.get("dc_bin_ac"), dict) else None
    time_raw_primary = (waveform.get("average_peaks") or [None])[0] if isinstance(waveform.get("average_peaks"), list) and waveform.get("average_peaks") else None
    spec_dc = spectrum.get("dc_bin") if isinstance(spectrum.get("dc_bin"), dict) else None
    row = {
        "case": case.get("name"),
        "case_type": case.get("case_type"),
        "taxonomy_role": case.get("taxonomy_role"),
        "sentinel_position": case.get("sentinel_position"),
        "repeat_index": case.get("repeat_index"),
        "physical_state": case.get("physical_state"),
        "clock_ref": case.get("clock_ref"),
        "bandwidth_mhz": case.get("bandwidth_mhz"),
        "output_mode": case.get("output_mode"),
        "center_mhz": case.get("center_mhz"),
        "target_rf_mhz": float(target_rf_mhz),
        "rfdc_mixer_sequence": case.get("rfdc_mixer_sequence"),
        "sysref_action": case.get("sysref_action"),
        "sysref_action_result": case.get("sysref_action_result"),
        "valid_for_spur": case.get("valid_for_spur"),
        "invalid_for_spur_reason": case.get("invalid_for_spur_reason"),
        "fengine_clean_reasons": list((case.get("fengine_clean_gate") or {}).get("reasons", []))
        if isinstance(case.get("fengine_clean_gate"), dict)
        else [],
        "time_target": time_target,
        "time_target_raw": time_target_raw,
        "time_dc_raw": time_dc_raw,
        "time_dc_ac": time_dc_ac,
        "time_mirror": _named_preview_metric(case, "production_time", "mirror_rf_bin"),
        "time_negative_edge": _named_preview_metric(case, "production_time", "negative_edge_bin"),
        "time_primary_peak": _primary_peak(case, "production_time", min_snr_db=0.0),
        "time_raw_primary_peak": time_raw_primary,
        "time_relative_phases": _channel_relative_phases(waveform, "target_rf_bin"),
        "time_relative_phases_raw": _channel_relative_phases(waveform, "target_rf_bin_raw"),
        "time_channel_targets": {
            str(channel): {
                "target": info.get("target_rf_bin"),
                "target_raw": info.get("target_rf_bin_raw"),
                "dc_raw": info.get("dc_bin_raw"),
                "dc_ac": info.get("dc_bin_ac"),
            }
            for channel, info in (waveform.get("channels") or {}).items()
            if isinstance(info, dict)
        }
        if isinstance(waveform.get("channels"), dict)
        else {},
        "spec_target": spec_target,
        "spec_dc": spec_dc,
        "spec_mirror": _named_preview_metric(case, "spec", "mirror_rf_bin"),
        "spec_negative_edge": _named_preview_metric(case, "spec", "negative_edge_bin"),
        "spec_primary_peak": _primary_peak(case, "spec", min_snr_db=0.0),
        "spec_lane_targets": {
            str(lane): {
                "target": info.get("target_rf_bin"),
                "dc": info.get("dc_bin"),
            }
            for lane, info in (spectrum.get("lanes") or {}).items()
            if isinstance(info, dict)
        }
        if isinstance(spectrum.get("lanes"), dict)
        else {},
        "rfdc_readback_check": case.get("rfdc_readback_check"),
        "sync_readback_summary": case.get("sync_readback_summary"),
    }
    effective = _taxonomy_effective_time_metric(row, target_rf_mhz=target_rf_mhz)
    row["time_effective_target"] = effective
    row["time_effective_target_pass"] = _taxonomy_metric_pass(effective, min_snr_db)
    row["time_target_pass"] = _taxonomy_metric_pass(time_target, min_snr_db)
    row["time_target_raw_pass"] = _taxonomy_metric_pass(time_target_raw, min_snr_db)
    row["spec_target_pass"] = _taxonomy_metric_pass(spec_target, min_snr_db)
    return row


def _classify_stage27i_100m_spur_taxonomy(cases: list[dict[str, Any]], *, target_rf_mhz: float, min_snr_db: float) -> dict[str, Any]:
    taxonomy_cases = [case for case in cases if str(case.get("case_type", "")).startswith("stage27i_100m_taxonomy")]
    evidence = [
        _taxonomy_evidence_row(case, target_rf_mhz=target_rf_mhz, min_snr_db=min_snr_db)
        for case in taxonomy_cases
    ]
    invalid_cases = [
        {
            "case": case.get("name"),
            "reason": case.get("invalid_for_spur_reason") or case.get("error") or "not marked valid_for_spur",
            "fengine_clean_gate": case.get("fengine_clean_gate"),
        }
        for case in taxonomy_cases
        if case.get("valid_for_spur") is not True
    ]
    valid_cases = [case for case in taxonomy_cases if case.get("valid_for_spur") is True and not case.get("error")]
    readback_mismatches = _readback_mismatches(valid_cases)

    def rows_for(case_type: str) -> list[dict[str, Any]]:
        return [row for row in evidence if row.get("case_type") == case_type]

    force_zero_rows = rows_for("stage27i_100m_taxonomy_force_zero")
    time_sweep_rows = rows_for("stage27i_100m_taxonomy_time_sweep")
    confirm_rows = rows_for("stage27i_100m_taxonomy_time_spec_confirm")
    repeat_rows = rows_for("stage27i_100m_taxonomy_nco_repeat")
    sysref_rows = rows_for("stage27i_100m_taxonomy_sysref")
    force_zero_clears = bool(force_zero_rows) and not any(
        bool(row.get("time_effective_target_pass") or row.get("spec_target_pass"))
        for row in force_zero_rows
    )
    sweep_hits = [row for row in time_sweep_rows if row.get("time_effective_target_pass")]
    sweep_missing = [row for row in time_sweep_rows if not row.get("time_effective_target_pass")]
    confirm_agree = [
        row for row in confirm_rows
        if row.get("time_effective_target_pass") and row.get("spec_target_pass")
    ]
    baseline = next((row for row in time_sweep_rows if abs(float(row.get("center_mhz", 0.0)) - 100.0) <= 0.001), None)
    if baseline is None:
        baseline = next((row for row in repeat_rows if int(row.get("repeat_index", -1)) == 0), None)

    sensitivity_evidence: list[dict[str, Any]] = []
    baseline_metric = _taxonomy_effective_time_metric(baseline, target_rf_mhz=target_rf_mhz) if baseline else None
    baseline_power = _metric_power(baseline_metric)
    for row in [*repeat_rows, *sysref_rows]:
        metric = _taxonomy_effective_time_metric(row, target_rf_mhz=target_rf_mhz)
        power = _metric_power(metric)
        if baseline_power is not None and power is not None:
            delta = power - baseline_power
            if abs(delta) >= 12.0:
                sensitivity_evidence.append(
                    {
                        "case": row.get("case"),
                        "baseline_case": baseline.get("case") if baseline else None,
                        "reason": "target power changed across NCO/SYSREF operation",
                        "baseline_power_db": baseline_power,
                        "power_db": power,
                        "power_delta_db": delta,
                    }
                )
        phase_delta = _relative_phase_delta_evidence(baseline, row, min_snr_db=min_snr_db)
        if phase_delta is not None:
            sensitivity_evidence.append(phase_delta)

    primary_tracks_target = []
    primary_misses_target = []
    for row in sweep_hits:
        center = float(row.get("center_mhz", 0.0))
        if abs(center - float(target_rf_mhz)) <= 0.5:
            continue
        primary = row.get("time_primary_peak")
        if not isinstance(primary, dict):
            primary_misses_target.append({"case": row.get("case"), "reason": "missing time primary peak"})
            continue
        delta = abs(float(primary.get("rf_mhz", 0.0)) - float(target_rf_mhz))
        item = {"case": row.get("case"), "center_mhz": center, "primary_rf_mhz": primary.get("rf_mhz"), "target_delta_mhz": delta}
        if delta <= 1.0:
            primary_tracks_target.append(item)
        else:
            primary_misses_target.append(item)

    dc_rows = [row for row in time_sweep_rows if abs(float(row.get("center_mhz", 0.0)) - float(target_rf_mhz)) <= 0.5]
    dc_evidence = []
    for row in dc_rows:
        if row.get("time_target_raw_pass") and not row.get("time_target_pass"):
            dc_evidence.append(
                {
                    "case": row.get("case"),
                    "center_mhz": row.get("center_mhz"),
                    "raw_target_snr_db": (row.get("time_target_raw") or {}).get("snr_db") if isinstance(row.get("time_target_raw"), dict) else None,
                    "ac_target_snr_db": (row.get("time_target") or {}).get("snr_db") if isinstance(row.get("time_target"), dict) else None,
                    "reason": "target RF maps to DC and is visible in raw TIME spectrum but suppressed in AC/mean-removed metric",
                }
            )

    centers_with_target = sorted(round(float(row.get("center_mhz", 0.0)), 6) for row in sweep_hits)
    centers_missing_target = sorted(round(float(row.get("center_mhz", 0.0)), 6) for row in sweep_missing)
    required_centers = {70.0, 80.0, 90.0, 100.0, 110.0, 120.0, 122.88, 130.0, 140.0, 150.0, 160.0}
    collected_centers = {round(float(row.get("center_mhz", 0.0)), 6) for row in time_sweep_rows}
    missing_required_centers = sorted(required_centers - collected_centers)

    if invalid_cases:
        classification = "stage27i_100m_spur_taxonomy_inconclusive"
        reason = "one or more 100MHz taxonomy cases failed the clean gate or raised an exception"
    elif readback_mismatches:
        classification = "rfdc_mixer_nco_sideband_suspect"
        reason = "RFDC readback differs from requested 100MHz center/mixer/decimation state"
    elif missing_required_centers or len(confirm_rows) < 4:
        classification = "stage27i_100m_spur_taxonomy_inconclusive"
        reason = "100MHz taxonomy audit did not collect the required TIME sweep or TIME_SPEC confirm cases"
    elif not force_zero_clears:
        classification = "stage27i_100m_spur_taxonomy_inconclusive"
        reason = "RFDC AXIS force-zero sentinel did not clear the target spur"
    elif sensitivity_evidence:
        classification = "rfdc_mixer_nco_sideband_suspect"
        reason = "target power or relative channel phase changes with repeated RFDC mixer/NCO apply or SYSREF pulse"
    elif sweep_missing:
        classification = "rfdc_mixer_nco_sideband_suspect"
        reason = "122.88MHz target is not stable across the 100MHz center sweep despite clean RFDC readback"
    elif dc_evidence and len(sweep_hits) <= 3:
        classification = "rfdc_dc_image_or_iq_mapping_suspect"
        reason = "target RF collapses into a DC/image-dominated response near center=122.88MHz without broad fixed-RF evidence"
    elif len(sweep_hits) >= 9 and len(confirm_agree) >= 3 and len(primary_tracks_target) >= 7:
        classification = "fixed_rf_or_board_coupling_suspect"
        reason = "TIME target stays at the same absolute RF across the 100MHz center sweep, SPEC confirms it, and NCO/SYSREF operations do not move it"
    elif sweep_hits:
        classification = "adc_or_rfdc_frontend_internal_suspect"
        reason = "target is cleared by RFDC AXIS force-zero and appears in clean TIME data, but evidence is not stable enough to call fixed RF/board coupling"
    else:
        classification = "stage27i_100m_spur_taxonomy_inconclusive"
        reason = "100MHz TIME sweep did not collect a usable target spur"

    return {
        "classification": classification,
        "reason": reason,
        "target_rf_mhz": float(target_rf_mhz),
        "min_snr_db": float(min_snr_db),
        "invalid_cases": invalid_cases,
        "rfdc_mismatches": readback_mismatches,
        "force_zero_clears_target": force_zero_clears,
        "centers_with_time_target": centers_with_target,
        "centers_missing_time_target": centers_missing_target,
        "time_spec_confirm_agree_count": len(confirm_agree),
        "sensitivity_evidence": sensitivity_evidence,
        "dc_evidence": dc_evidence,
        "primary_tracks_target": primary_tracks_target,
        "primary_misses_target": primary_misses_target,
        "evidence": evidence,
        "allowed_classifications": list(ALLOWED_STAGE27I_SPUR_CLASSIFICATIONS),
        "note": "This taxonomy intentionally ignores 200MHz as a production issue; classification uses clean 100MHz TIME evidence first and SPEC only as confirmation.",
    }


def _classify_stage27i_mixer_event_audit(cases: list[dict[str, Any]], *, target_rf_mhz: float, min_snr_db: float) -> dict[str, Any]:
    mixer_cases = [case for case in cases if str(case.get("case_type", "")).startswith("stage27i_mixer_event")]
    evidence = [
        _taxonomy_evidence_row(case, target_rf_mhz=target_rf_mhz, min_snr_db=min_snr_db)
        for case in mixer_cases
    ]
    invalid_cases = [
        {
            "case": case.get("name"),
            "reason": case.get("invalid_for_spur_reason") or case.get("error") or "not marked valid_for_spur",
            "fengine_clean_gate": case.get("fengine_clean_gate"),
        }
        for case in mixer_cases
        if case.get("valid_for_spur") is not True
    ]
    valid_cases = [case for case in mixer_cases if case.get("valid_for_spur") is True and not case.get("error")]
    readback_mismatches = _readback_mismatches(valid_cases)

    def rows_for(role: str) -> list[dict[str, Any]]:
        return [row for row in evidence if row.get("taxonomy_role") == role]

    force_zero_rows = rows_for("force_zero_sentinel")
    baseline_rows = rows_for("center_baseline")
    repeat_rows = rows_for("repeat_apply")
    sysref_rows = rows_for("sysref_pulse")
    force_zero_clears = bool(force_zero_rows) and not any(
        bool(row.get("time_effective_target_pass") or row.get("spec_target_pass"))
        for row in force_zero_rows
    )

    baseline_by_center = {
        round(float(row.get("center_mhz", 0.0)), 6): row
        for row in baseline_rows
        if row.get("valid_for_spur") is True
    }
    center_hits = [
        row for row in baseline_rows
        if row.get("time_effective_target_pass")
    ]
    center_missing = [
        row for row in baseline_rows
        if not row.get("time_effective_target_pass")
    ]

    def sensitivity_rows(rows: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
        sensitive: list[dict[str, Any]] = []
        for row in rows:
            center = round(float(row.get("center_mhz", 0.0)), 6)
            baseline = baseline_by_center.get(center)
            if baseline is None:
                sensitive.append(
                    {
                        "case": row.get("case"),
                        "reason": "missing same-center baseline for comparison",
                        "sensitivity_kind": kind,
                        "center_mhz": row.get("center_mhz"),
                    }
                )
                continue
            base_metric = _taxonomy_effective_time_metric(baseline, target_rf_mhz=target_rf_mhz)
            row_metric = _taxonomy_effective_time_metric(row, target_rf_mhz=target_rf_mhz)
            base_power = _metric_power(base_metric)
            row_power = _metric_power(row_metric)
            if base_power is not None and row_power is not None:
                delta = row_power - base_power
                if abs(delta) >= 12.0:
                    sensitive.append(
                        {
                            "case": row.get("case"),
                            "baseline_case": baseline.get("case"),
                            "reason": "target power changed across RFDC mixer event operation",
                            "sensitivity_kind": kind,
                            "center_mhz": row.get("center_mhz"),
                            "baseline_power_db": base_power,
                            "power_db": row_power,
                            "power_delta_db": delta,
                        }
                    )
            phase_key = (
                "time_relative_phases_raw"
                if abs(float(row.get("center_mhz", 0.0)) - float(target_rf_mhz)) <= 0.5
                else "time_relative_phases"
            )
            phase_delta = _relative_phase_delta_evidence(baseline, row, phase_key=phase_key, min_snr_db=min_snr_db)
            if phase_delta is not None:
                phase_delta["sensitivity_kind"] = kind
                phase_delta["center_mhz"] = row.get("center_mhz")
                sensitive.append(phase_delta)
        return sensitive

    repeat_sensitivity = sensitivity_rows(repeat_rows, "repeat_apply")
    sysref_sensitivity = sensitivity_rows(sysref_rows, "sysref_pulse")
    centers_with_target = sorted(round(float(row.get("center_mhz", 0.0)), 6) for row in center_hits)
    centers_missing_target = sorted(round(float(row.get("center_mhz", 0.0)), 6) for row in center_missing)
    required_centers = {100.0, 120.0, 122.88, 130.0, 140.0}
    collected_centers = {round(float(row.get("center_mhz", 0.0)), 6) for row in baseline_rows}
    missing_required_centers = sorted(required_centers - collected_centers)

    if invalid_cases:
        classification = "stage27i_mixer_event_inconclusive"
        reason = "one or more RFDC mixer event audit cases failed the clean gate or raised an exception"
    elif readback_mismatches:
        classification = "rfdc_mixer_nco_sideband_suspect"
        reason = "RFDC readback differs from requested 100MHz mixer/NCO/decimation state"
    elif missing_required_centers:
        classification = "stage27i_mixer_event_inconclusive"
        reason = "RFDC mixer event audit did not collect the required center baselines"
    elif not force_zero_clears:
        classification = "stage27i_mixer_event_inconclusive"
        reason = "RFDC AXIS force-zero sentinel did not clear the target spur"
    elif sysref_sensitivity:
        classification = "sysref_sensitive"
        reason = "target power or relative channel phase changes after explicit SYSREF pulse"
    elif repeat_sensitivity:
        classification = "mixer_event_phase_sensitive"
        reason = "target power or relative channel phase changes across repeated RFDC mixer/NCO apply"
    elif center_missing and center_hits:
        classification = "center_sideband_mapping_sensitive"
        reason = "target appears for some clean 100MHz centers but disappears for other clean centers"
    elif center_hits:
        classification = "rfdc_internal_or_adc_frontend_remaining"
        reason = "target is cleared by force-zero and survives clean RFDC mixer event checks without measurable event sensitivity"
    else:
        classification = "stage27i_mixer_event_inconclusive"
        reason = "RFDC mixer event audit did not collect a usable target spur"

    return {
        "classification": classification,
        "reason": reason,
        "target_rf_mhz": float(target_rf_mhz),
        "min_snr_db": float(min_snr_db),
        "invalid_cases": invalid_cases,
        "rfdc_mismatches": readback_mismatches,
        "force_zero_clears_target": force_zero_clears,
        "centers_with_time_target": centers_with_target,
        "centers_missing_time_target": centers_missing_target,
        "repeat_apply_sensitivity": repeat_sensitivity,
        "sysref_sensitivity": sysref_sensitivity,
        "evidence": evidence,
        "allowed_classifications": list(ALLOWED_STAGE27I_SPUR_CLASSIFICATIONS),
        "note": "This Stage 27i audit uses only 100MHz BW cases. Repeated apply currently exercises the same RFDC UpdateEvent(EVENT_MIXER)+ResetNCOPhase path used by production observation apply.",
    }


def _classify_stage27i_mixer_sequence_audit(cases: list[dict[str, Any]], *, target_rf_mhz: float, min_snr_db: float) -> dict[str, Any]:
    sequence_cases = [case for case in cases if str(case.get("case_type", "")).startswith("stage27i_mixer_sequence")]
    evidence = [
        _taxonomy_evidence_row(case, target_rf_mhz=target_rf_mhz, min_snr_db=min_snr_db)
        for case in sequence_cases
    ]
    invalid_cases = [
        {
            "case": case.get("name"),
            "reason": case.get("invalid_for_spur_reason") or case.get("error") or "not marked valid_for_spur",
            "fengine_clean_gate": case.get("fengine_clean_gate"),
        }
        for case in sequence_cases
        if case.get("valid_for_spur") is not True
    ]
    valid_cases = [case for case in sequence_cases if case.get("valid_for_spur") is True and not case.get("error")]
    readback_mismatches = _readback_mismatches(valid_cases)

    force_zero_rows = [row for row in evidence if row.get("taxonomy_role") == "force_zero_sentinel"]
    sequence_rows = [row for row in evidence if row.get("taxonomy_role") == "mixer_sequence"]
    force_zero_clears = bool(force_zero_rows) and not any(
        bool(row.get("time_effective_target_pass") or row.get("spec_target_pass"))
        for row in force_zero_rows
    )

    baseline_by_center = {
        round(float(row.get("center_mhz", 0.0)), 6): row
        for row in sequence_rows
        if row.get("rfdc_mixer_sequence") == "sysref_reset_before_pulse"
    }
    centers_with_target = sorted(
        {
            round(float(row.get("center_mhz", 0.0)), 6)
            for row in sequence_rows
            if row.get("rfdc_mixer_sequence") == "sysref_reset_before_pulse" and row.get("time_effective_target_pass")
        }
    )
    centers_missing_target = sorted(
        {
            round(float(row.get("center_mhz", 0.0)), 6)
            for row in sequence_rows
            if row.get("rfdc_mixer_sequence") == "sysref_reset_before_pulse" and not row.get("time_effective_target_pass")
        }
    )
    required_sequences = {
        "sysref_reset_before_pulse",
        "sysref_no_reset",
        "tile_update_then_reset",
        "tile_reset_then_update",
        "tile_update_no_reset",
    }
    required_centers = {100.0, 122.88, 130.0, 140.0}
    collected_by_center: dict[float, set[str]] = {}
    for row in sequence_rows:
        center = round(float(row.get("center_mhz", 0.0)), 6)
        collected_by_center.setdefault(center, set()).add(str(row.get("rfdc_mixer_sequence")))
    missing_matrix = [
        {"center_mhz": center, "missing_sequences": sorted(required_sequences - collected_by_center.get(center, set()))}
        for center in sorted(required_centers)
        if required_sequences - collected_by_center.get(center, set())
    ]

    sequence_sensitivity: list[dict[str, Any]] = []
    eventsource_sensitivity: list[dict[str, Any]] = []
    reset_sensitivity: list[dict[str, Any]] = []
    order_sensitivity: list[dict[str, Any]] = []
    for row in sequence_rows:
        seq = str(row.get("rfdc_mixer_sequence"))
        if seq == "sysref_reset_before_pulse":
            continue
        center = round(float(row.get("center_mhz", 0.0)), 6)
        baseline = baseline_by_center.get(center)
        if baseline is None:
            continue
        baseline_pass = bool(baseline.get("time_effective_target_pass"))
        row_pass = bool(row.get("time_effective_target_pass"))
        item_prefix = {
            "case": row.get("case"),
            "baseline_case": baseline.get("case"),
            "center_mhz": row.get("center_mhz"),
            "rfdc_mixer_sequence": seq,
            "baseline_sequence": baseline.get("rfdc_mixer_sequence"),
        }
        if baseline_pass != row_pass:
            item = {
                **item_prefix,
                "reason": "target threshold pass/fail changed relative to default SYSREF sequence",
                "baseline_pass": baseline_pass,
                "sequence_pass": row_pass,
                "baseline_snr_db": (_taxonomy_effective_time_metric(baseline, target_rf_mhz=target_rf_mhz) or {}).get("snr_db"),
                "sequence_snr_db": (_taxonomy_effective_time_metric(row, target_rf_mhz=target_rf_mhz) or {}).get("snr_db"),
            }
            sequence_sensitivity.append(item)
        base_power = _metric_power(_taxonomy_effective_time_metric(baseline, target_rf_mhz=target_rf_mhz))
        row_power = _metric_power(_taxonomy_effective_time_metric(row, target_rf_mhz=target_rf_mhz))
        if base_power is not None and row_power is not None and abs(row_power - base_power) >= 12.0:
            sequence_sensitivity.append(
                {
                    **item_prefix,
                    "reason": "target power changed relative to default SYSREF sequence",
                    "baseline_power_db": base_power,
                    "sequence_power_db": row_power,
                    "power_delta_db": row_power - base_power,
                }
            )
        phase_key = "time_relative_phases_raw" if abs(float(row.get("center_mhz", 0.0)) - float(target_rf_mhz)) <= 0.5 else "time_relative_phases"
        phase_delta = _relative_phase_delta_evidence(baseline, row, phase_key=phase_key, min_snr_db=min_snr_db)
        if phase_delta is not None:
            phase_delta.update(item_prefix)
            sequence_sensitivity.append(phase_delta)

    for item in sequence_sensitivity:
        seq = str(item.get("rfdc_mixer_sequence", ""))
        if seq.startswith(("event_", "tile_", "slice_")):
            eventsource_sensitivity.append(item)
        if seq == "sysref_no_reset":
            reset_sensitivity.append(item)
        if seq in (
            "event_update_then_reset",
            "event_reset_then_update",
            "event_update_no_reset",
            "tile_update_then_reset",
            "tile_reset_then_update",
            "tile_update_no_reset",
            "slice_update_then_reset",
            "slice_reset_then_update",
            "slice_update_no_reset",
        ):
            order_sensitivity.append(item)

    if invalid_cases:
        classification = "stage27i_mixer_sequence_inconclusive"
        reason = "one or more RFDC mixer sequence cases failed the clean gate or raised an exception"
    elif readback_mismatches:
        classification = "rfdc_mixer_nco_sideband_suspect"
        reason = "RFDC readback differs from requested mixer sequence state"
    elif missing_matrix:
        classification = "stage27i_mixer_sequence_inconclusive"
        reason = "RFDC mixer sequence audit did not collect the required center/sequence matrix"
    elif not force_zero_clears:
        classification = "stage27i_mixer_sequence_inconclusive"
        reason = "RFDC AXIS force-zero sentinel did not clear the target spur"
    elif reset_sensitivity:
        classification = "mixer_sequence_order_sensitive"
        reason = "SYSREF reset/no-reset sequence changes target power or relative channel phase"
    elif eventsource_sensitivity:
        classification = "mixer_eventsource_sensitive"
        reason = "TILE UpdateEvent sequence differs from the default SYSREF sequence"
    elif order_sensitivity:
        classification = "mixer_sequence_order_sensitive"
        reason = "UpdateEvent/ResetNCOPhase ordering changes target power or relative channel phase"
    elif centers_missing_target and centers_with_target:
        classification = "center_sideband_mapping_sensitive"
        reason = "default SYSREF sequence sees target at some centers but not others"
    elif centers_with_target:
        classification = "rfdc_internal_or_adc_frontend_remaining"
        reason = "all mixer sequences produce equivalent target evidence; remaining boundary is RFDC/ADC internal or front-end"
    else:
        classification = "stage27i_mixer_sequence_inconclusive"
        reason = "RFDC mixer sequence audit did not collect a usable target spur"

    return {
        "classification": classification,
        "reason": reason,
        "target_rf_mhz": float(target_rf_mhz),
        "min_snr_db": float(min_snr_db),
        "invalid_cases": invalid_cases,
        "rfdc_mismatches": readback_mismatches,
        "force_zero_clears_target": force_zero_clears,
        "centers_with_time_target": centers_with_target,
        "centers_missing_time_target": centers_missing_target,
        "missing_matrix": missing_matrix,
        "sequence_sensitivity": sequence_sensitivity,
        "eventsource_sensitivity": eventsource_sensitivity,
        "reset_sensitivity": reset_sensitivity,
        "order_sensitivity": order_sensitivity,
        "evidence": evidence,
        "allowed_classifications": list(ALLOWED_STAGE27I_SPUR_CLASSIFICATIONS),
        "note": "This Stage 27i audit uses only 100MHz BW cases and compares RFDC mixer EventSource/UpdateEvent/ResetNCOPhase sequencing against the default SYSREF reset-before-pulse sequence.",
    }


def _raw_lane_target_metric(case: dict[str, Any], source: str, *, target_rf_mhz: float) -> dict[str, Any] | None:
    center_mhz = float(case.get("center_mhz", 0.0))
    use_raw_dc = abs(center_mhz - float(target_rf_mhz)) <= 0.5
    if source == "raw_lane":
        container = case.get("rfdc_axis_raw_witness") if isinstance(case.get("rfdc_axis_raw_witness"), dict) else {}
        key = "target_rf_bin_raw" if use_raw_dc else "target_rf_bin"
    elif source == "raw_lane_decim2":
        raw_container = case.get("rfdc_axis_raw_witness") if isinstance(case.get("rfdc_axis_raw_witness"), dict) else {}
        container = raw_container.get("rtl_decim2_model") if isinstance(raw_container, dict) else {}
        key = "target_rf_bin_raw" if use_raw_dc else "target_rf_bin"
    elif source == "production_time":
        container = case.get("rust_time_waveform") if isinstance(case.get("rust_time_waveform"), dict) else {}
        key = "target_rf_bin_raw" if use_raw_dc else "target_rf_bin"
    elif source == "spec":
        container = case.get("rust_spectrum") if isinstance(case.get("rust_spectrum"), dict) else {}
        key = "target_rf_bin"
    else:
        raise ValueError(f"unknown raw-lane target metric source {source!r}")
    metric = container.get(key) if isinstance(container, dict) else None
    return metric if isinstance(metric, dict) and metric.get("available") else None


def _raw_lane_evidence_row(case: dict[str, Any], *, target_rf_mhz: float, min_snr_db: float) -> dict[str, Any]:
    raw_metric = _raw_lane_target_metric(case, "raw_lane", target_rf_mhz=target_rf_mhz)
    raw_decim2_metric = _raw_lane_target_metric(case, "raw_lane_decim2", target_rf_mhz=target_rf_mhz)
    time_metric = _raw_lane_target_metric(case, "production_time", target_rf_mhz=target_rf_mhz)
    spec_metric = _raw_lane_target_metric(case, "spec", target_rf_mhz=target_rf_mhz)
    center_mhz = float(case.get("center_mhz", 0.0))
    return {
        "case": case.get("name"),
        "case_type": case.get("case_type"),
        "taxonomy_role": case.get("taxonomy_role"),
        "sentinel_position": case.get("sentinel_position"),
        "valid_for_spur": case.get("valid_for_spur"),
        "invalid_for_spur_reason": case.get("invalid_for_spur_reason"),
        "center_mhz": center_mhz,
        "target_rf_mhz": float(target_rf_mhz),
        "target_maps_to_dc": abs(center_mhz - float(target_rf_mhz)) <= 0.5,
        "bandwidth_mhz": case.get("bandwidth_mhz"),
        "output_mode": case.get("output_mode"),
        "diag_control": case.get("diag_control"),
        "raw_lane_primary_peak": _primary_peak(case, "raw_lane", min_snr_db=0.0),
        "raw_lane_decim2_primary_peak": _primary_peak(case, "raw_lane_decim2", min_snr_db=0.0),
        "time_primary_peak": _primary_peak(case, "production_time", min_snr_db=0.0),
        "spec_primary_peak": _primary_peak(case, "spec", min_snr_db=0.0),
        "raw_lane_target": raw_metric,
        "raw_lane_decim2_target": raw_decim2_metric,
        "time_target": time_metric,
        "spec_target": spec_metric,
        "raw_lane_pass": _metric_pass(raw_metric, min_snr_db),
        "raw_lane_decim2_pass": _metric_pass(raw_decim2_metric, min_snr_db),
        "time_pass": _metric_pass(time_metric, min_snr_db),
        "spec_pass": _metric_pass(spec_metric, min_snr_db),
        "raw_lane_channel_target": {
            channel: info.get("target_rf_bin_raw" if abs(center_mhz - float(target_rf_mhz)) <= 0.5 else "target_rf_bin")
            for channel, info in ((case.get("rfdc_axis_raw_witness", {}) or {}).get("channels", {}) or {}).items()
            if isinstance(info, dict)
        }
        if isinstance(case.get("rfdc_axis_raw_witness"), dict)
        else {},
    }


def _classify_stage27i_raw_lane_witness_audit(cases: list[dict[str, Any]], *, target_rf_mhz: float, min_snr_db: float) -> dict[str, Any]:
    raw_cases = [case for case in cases if str(case.get("case_type", "")).startswith("stage27i_raw_lane")]
    evidence = [
        _raw_lane_evidence_row(case, target_rf_mhz=target_rf_mhz, min_snr_db=min_snr_db)
        for case in raw_cases
    ]
    invalid_cases = [
        {
            "case": case.get("name"),
            "reason": case.get("invalid_for_spur_reason") or case.get("error") or "not marked valid_for_spur",
            "fengine_clean_gate": case.get("fengine_clean_gate"),
        }
        for case in raw_cases
        if case.get("valid_for_spur") is not True
    ]
    force_zero_rows = [row for row in evidence if row.get("taxonomy_role") == "force_zero_sentinel"]
    baseline_rows = [row for row in evidence if row.get("taxonomy_role") == "raw_lane_time_spec_center"]
    non_dc_baseline_rows = [row for row in baseline_rows if not row.get("target_maps_to_dc")]
    baseline_mismatches = [
        {
            "case": row.get("case"),
            "center_mhz": row.get("center_mhz"),
            "raw_lane_pass": row.get("raw_lane_pass"),
            "time_pass": row.get("time_pass"),
            "spec_pass": row.get("spec_pass"),
            "raw_lane_target": row.get("raw_lane_target"),
            "time_target": row.get("time_target"),
            "spec_target": row.get("spec_target"),
            "reason": "raw-lane target presence does not match production TIME/SPEC target presence",
        }
        for row in non_dc_baseline_rows
        if not (bool(row.get("raw_lane_pass")) == bool(row.get("time_pass")) == bool(row.get("spec_pass")))
    ]
    matching_rows = [
        row for row in non_dc_baseline_rows
        if bool(row.get("raw_lane_pass")) == bool(row.get("time_pass")) == bool(row.get("spec_pass"))
    ]
    decim2_matching_rows = [
        row for row in non_dc_baseline_rows
        if bool(row.get("raw_lane_decim2_pass")) == bool(row.get("time_pass")) == bool(row.get("spec_pass"))
    ]
    decim2_target_rows = [
        row for row in non_dc_baseline_rows
        if bool(row.get("raw_lane_decim2_pass") and row.get("time_pass") and row.get("spec_pass"))
    ]
    rows_with_target = [
        row for row in non_dc_baseline_rows
        if bool(row.get("raw_lane_pass") or row.get("time_pass") or row.get("spec_pass"))
    ]
    force_zero_boundary_ok = bool(force_zero_rows) and all(
        isinstance(row.get("raw_lane_primary_peak"), dict)
        and float(row["raw_lane_primary_peak"].get("snr_db", 0.0)) >= float(min_snr_db)
        and not bool(row.get("time_pass"))
        and not bool(row.get("spec_pass"))
        for row in force_zero_rows
        if not row.get("target_maps_to_dc")
    )
    required_centers = {100.0, 130.0, 140.0}
    collected_centers = {round(float(row.get("center_mhz", 0.0)), 6) for row in non_dc_baseline_rows}
    missing_centers = sorted(required_centers - collected_centers)

    if invalid_cases:
        classification = "raw_lane_witness_inconclusive"
        reason = "one or more raw-lane witness cases failed the clean gate or raised an exception"
    elif missing_centers:
        classification = "raw_lane_witness_inconclusive"
        reason = "raw-lane witness audit did not collect the required non-DC 100MHz center cases"
    elif not force_zero_boundary_ok:
        classification = "raw_lane_witness_inconclusive"
        reason = "force-zero sentinel did not prove raw-lane pre-diag activity with production TIME/SPEC target cleared"
    elif baseline_mismatches and len(decim2_matching_rows) == len(non_dc_baseline_rows) and decim2_target_rows:
        classification = "raw_lane_decim2_alias_matches_time_spec"
        reason = "raw-lane direct view disagrees, but the RTL 100MHz decim2 model matches production TIME/SPEC target-bin behavior"
    elif baseline_mismatches:
        classification = "raw_lane_time_spec_mapping_suspect"
        reason = "raw-lane witness and production TIME/SPEC disagree at one or more 100MHz center cases"
    elif not rows_with_target:
        classification = "raw_lane_witness_inconclusive"
        reason = "raw-lane witness audit did not see the target spur in any usable non-DC center case"
    elif len(matching_rows) == len(non_dc_baseline_rows):
        classification = "raw_lane_matches_time_spec"
        reason = "pre-diag RFDC raw-lane witness, production TIME, and FFT-only SPEC see the same target-bin behavior"
    else:
        classification = "raw_lane_witness_inconclusive"
        reason = "raw-lane witness audit produced insufficient agreement evidence"

    return {
        "classification": classification,
        "reason": reason,
        "target_rf_mhz": float(target_rf_mhz),
        "min_snr_db": float(min_snr_db),
        "invalid_cases": invalid_cases,
        "missing_required_centers": missing_centers,
        "force_zero_boundary_ok": force_zero_boundary_ok,
        "baseline_mismatches": baseline_mismatches,
        "decim2_matching_non_dc_center_count": len(decim2_matching_rows),
        "decim2_target_center_count": len(decim2_target_rows),
        "centers_with_any_target": sorted(round(float(row.get("center_mhz", 0.0)), 6) for row in rows_with_target),
        "matching_non_dc_center_count": len(matching_rows),
        "evidence": evidence,
        "allowed_classifications": list(ALLOWED_STAGE27I_SPUR_CLASSIFICATIONS),
        "note": "Stage 27i raw-lane witness is captured before ADC diagnostic force-zero/hold/channel-isolate and is used only to localize the 122.88MHz spur boundary.",
    }


def _classify_stage27i_rfdc_200m_rootcause(cases: list[dict[str, Any]], *, target_rf_mhz: float, min_snr_db: float) -> dict[str, Any]:
    root_cases = [case for case in cases if case.get("case_type") == "stage27i_rfdc_200m_rootcause"]
    evidence = [
        _rootcause_evidence_row(case, target_rf_mhz=target_rf_mhz, min_snr_db=min_snr_db)
        for case in root_cases
    ]
    invalid_cases = [
        {
            "case": case.get("name"),
            "reason": case.get("invalid_for_spur_reason") or case.get("error") or "not marked valid_for_spur",
            "fengine_clean_gate": case.get("fengine_clean_gate"),
        }
        for case in root_cases
        if case.get("valid_for_spur") is not True
    ]
    readback_mismatches = _readback_mismatches([case for case in root_cases if not case.get("error")])

    def find_row(bandwidth: int, mode: str, center_mhz: float = 100.0) -> dict[str, Any] | None:
        mode_upper = mode.upper()
        for row in evidence:
            if int(row.get("bandwidth_mhz", -1)) != int(bandwidth):
                continue
            if str(row.get("output_mode", "")).upper() != mode_upper:
                continue
            if abs(float(row.get("center_mhz", 0.0)) - float(center_mhz)) > 0.001:
                continue
            return row
        return None

    spec_100 = find_row(100, "SPEC_ONLY")
    spec_200 = find_row(200, "SPEC_ONLY")
    time_200 = find_row(200, "TIME_ONLY")
    time_spec_100 = find_row(100, "TIME_SPEC")
    required_present = bool(spec_100 and spec_200 and time_200 and time_spec_100)
    spec_100_target = bool(spec_100 and spec_100.get("spec_target_pass"))
    spec_200_target = bool(spec_200 and spec_200.get("spec_target_pass"))
    time_200_target = bool(time_200 and time_200.get("time_target_pass"))
    spec_200_primary = spec_200.get("spec_primary_peak") if isinstance(spec_200, dict) else None
    spec_200_primary_strong = bool(
        isinstance(spec_200_primary, dict)
        and float(spec_200_primary.get("snr_db", 0.0)) >= float(min_snr_db)
    )
    time_200_primary = time_200.get("time_primary_peak") if isinstance(time_200, dict) else None
    time_200_primary_strong = bool(
        isinstance(time_200_primary, dict)
        and float(time_200_primary.get("snr_db", 0.0)) >= float(min_snr_db)
    )
    spec_200_backpressure = bool(spec_200 and spec_200.get("has_xfft_or_capture_backpressure"))

    if readback_mismatches:
        classification = "rfdc_200m_config_mismatch_suspect"
        reason = "RFDC readback differs from requested center/decimation/mixer/Nyquist/MTS state in the 100/200MHz root-cause audit"
    elif not required_present:
        classification = "stage27i_rfdc_200m_inconclusive"
        reason = "root-cause audit did not collect all required 100/200MHz control cases"
    elif spec_100_target and not spec_200_target and not time_200_target and time_200_primary_strong:
        classification = "rfdc_200m_decimation_path_suspect"
        reason = "100MHz target is clean, but 200MHz TIME_ONLY and SPEC_ONLY both suppress the target and produce a different dominant low-frequency/sideband peak; SPEC also records any XFFT backpressure separately"
    elif spec_100_target and not spec_200_target and spec_200_backpressure:
        classification = "fengine_200m_output_backpressure_suspect"
        reason = "100MHz SPEC_ONLY sees the target, while 200MHz SPEC_ONLY suppresses it and shows XFFT output halt/capture backpressure"
    elif spec_100_target and not spec_200_target and time_200_target:
        classification = "spec_axis_mapping_suspect"
        reason = "200MHz TIME_ONLY sees the target but 200MHz SPEC_ONLY does not, with clean readback and no SPEC backpressure"
    elif spec_100_target and not spec_200_target and spec_200_primary_strong:
        classification = "rfdc_200m_decimation_path_suspect"
        reason = "100MHz SPEC_ONLY sees the target but 200MHz SPEC_ONLY produces a different strong dominant peak without RFDC readback mismatch"
    else:
        classification = "stage27i_rfdc_200m_inconclusive"
        reason = "100/200MHz root-cause evidence did not separate RFDC config, decimation path, F-engine backpressure, and SPEC axis mapping"

    return {
        "classification": classification,
        "reason": reason,
        "target_rf_mhz": float(target_rf_mhz),
        "min_snr_db": float(min_snr_db),
        "required_cases_present": required_present,
        "spec_100_target_pass": spec_100_target,
        "spec_200_target_pass": spec_200_target,
        "time_200_target_pass": time_200_target,
        "time_200_primary_strong": time_200_primary_strong,
        "spec_200_has_xfft_or_capture_backpressure": spec_200_backpressure,
        "rfdc_mismatches": readback_mismatches,
        "invalid_cases": invalid_cases,
        "evidence": evidence,
        "allowed_classifications": list(ALLOWED_STAGE27I_SPUR_CLASSIFICATIONS),
        "note": "Dirty 200MHz SPEC_ONLY previews are retained only as diagnostic evidence; invalid_cases must not be treated as clean science pass evidence.",
    }


def _classify_fixed_rf(cases: list[dict[str, Any]], *, target_rf_mhz: float, min_snr_db: float) -> dict[str, Any]:
    invalid_cases = [
        {
            "case": case.get("name"),
            "reason": case.get("invalid_for_spur_reason") or case.get("error") or "not marked valid_for_spur",
            "fengine_clean_gate": case.get("fengine_clean_gate"),
        }
        for case in cases
        if case.get("valid_for_spur") is not True
    ]
    valid_cases = [case for case in cases if case.get("valid_for_spur") is True and not case.get("error")]
    target_rows = _target_metric_rows(valid_cases, min_snr_db=min_snr_db)
    reference_check = _reference_tone_check(valid_cases, min_snr_db=min_snr_db)
    if reference_check.get("available") and not reference_check.get("ok"):
        return {
            "classification": "inconclusive",
            "reason": "reference tone did not validate production TIME/SPEC frequency placement",
            "target_rf_mhz": float(target_rf_mhz),
            "min_snr_db": float(min_snr_db),
            "reference_tone_check": reference_check,
            "target_rows": target_rows,
            "invalid_cases": invalid_cases,
            "allowed_classifications": list(ALLOWED_STAGE27I_SPUR_CLASSIFICATIONS),
        }
    readback_mismatches = _readback_mismatches(valid_cases)
    if readback_mismatches:
        return {
            "classification": "rfdc_mixer_config_suspect",
            "reason": "RFDC mixer readback does not match requested center/DAC NCO",
            "target_rf_mhz": float(target_rf_mhz),
            "min_snr_db": float(min_snr_db),
            "reference_tone_check": reference_check,
            "rfdc_mismatches": readback_mismatches,
            "target_rows": target_rows,
            "invalid_cases": invalid_cases,
            "allowed_classifications": list(ALLOWED_STAGE27I_SPUR_CLASSIFICATIONS),
        }

    center_cases = [
        case
        for case in valid_cases
        if case.get("case_type") == "zero_amp_enable_ff"
    ]
    center_pass = [
        case
        for case in center_cases
        if _metric_pass(_target_metric(case, "production_time"), min_snr_db)
        and _metric_pass(_target_metric(case, "spec"), min_snr_db)
    ]
    center_values = sorted({round(float(case.get("center_mhz", 0.0)), 6) for case in center_pass})

    reference_centers = [
        float(case.get("center_mhz", 0.0))
        for case in valid_cases
        if case.get("case_type") == "zero_amp_enable_00"
    ]
    reference_center_mhz = reference_centers[0] if reference_centers else 100.0
    same_center_on = [
        case for case in valid_cases
        if case.get("case_type") == "zero_amp_enable_ff"
        and abs(float(case.get("center_mhz", 0.0)) - reference_center_mhz) <= 1.0
    ]
    same_center_off = [
        case for case in valid_cases
        if case.get("case_type") == "zero_amp_enable_00"
        and abs(float(case.get("center_mhz", 0.0)) - reference_center_mhz) <= 1.0
    ]
    dac_sweep = [case for case in valid_cases if case.get("case_type") == "zero_amp_dac_nco_sweep"]
    dac_sensitive_evidence = []
    for source in ("production_time", "spec"):
        on_metric = _target_metric(same_center_on[0], source) if same_center_on else None
        off_metric = _target_metric(same_center_off[0], source) if same_center_off else None
        if on_metric and off_metric:
            on_power = _metric_power(on_metric)
            off_power = _metric_power(off_metric)
            if on_power is not None and off_power is not None and abs(on_power - off_power) > 12.0:
                dac_sensitive_evidence.append({"source": source, "comparison": "enable_ff_vs_00", "power_delta_db": on_power - off_power})
        sweep_powers = [_metric_power(_target_metric(case, source)) for case in dac_sweep]
        sweep_powers = [value for value in sweep_powers if value is not None]
        if len(sweep_powers) >= 2 and max(sweep_powers) - min(sweep_powers) > 12.0:
            dac_sensitive_evidence.append({"source": source, "comparison": "dac_nco_sweep", "power_span_db": max(sweep_powers) - min(sweep_powers)})

    if dac_sensitive_evidence:
        return {
            "classification": "inconclusive",
            "reason": "zero-amplitude target RF spur changes significantly with DAC enable or DAC NCO; this needs a separate DAC-coupling audit",
            "target_rf_mhz": float(target_rf_mhz),
            "min_snr_db": float(min_snr_db),
            "reference_tone_check": reference_check,
            "dac_sensitive_evidence": dac_sensitive_evidence,
            "target_rows": target_rows,
            "invalid_cases": invalid_cases,
            "allowed_classifications": list(ALLOWED_STAGE27I_SPUR_CLASSIFICATIONS),
        }

    dac_sweep_pass = [
        case
        for case in dac_sweep
        if _metric_pass(_target_metric(case, "production_time"), min_snr_db)
        and _metric_pass(_target_metric(case, "spec"), min_snr_db)
    ]
    enable_off_pass = bool(
        same_center_off
        and _metric_pass(_target_metric(same_center_off[0], "production_time"), min_snr_db)
        and _metric_pass(_target_metric(same_center_off[0], "spec"), min_snr_db)
    )
    if len(center_values) >= 3 and enable_off_pass and len(dac_sweep_pass) >= 2:
        return {
            "classification": "adc_or_board_fixed_rf_suspect",
            "reason": "target RF spur is present across center sweep, remains with DAC enable off, and does not track DAC NCO",
            "target_rf_mhz": float(target_rf_mhz),
            "min_snr_db": float(min_snr_db),
            "reference_tone_check": reference_check,
            "passing_centers_mhz": center_values,
            "dac_nco_sweep_pass_count": len(dac_sweep_pass),
            "target_rows": target_rows,
            "invalid_cases": invalid_cases,
            "allowed_classifications": list(ALLOWED_STAGE27I_SPUR_CLASSIFICATIONS),
        }
    if len(center_values) >= 3:
        return {
            "classification": "adc_or_board_fixed_rf_suspect",
            "reason": "target RF spur is present across center sweep in production TIME and SPEC",
            "target_rf_mhz": float(target_rf_mhz),
            "min_snr_db": float(min_snr_db),
            "reference_tone_check": reference_check,
            "passing_centers_mhz": center_values,
            "target_rows": target_rows,
            "invalid_cases": invalid_cases,
            "allowed_classifications": list(ALLOWED_STAGE27I_SPUR_CLASSIFICATIONS),
        }
    return {
        "classification": "inconclusive",
        "reason": "not enough clean target-RF cases exceeded the SNR threshold",
        "target_rf_mhz": float(target_rf_mhz),
        "min_snr_db": float(min_snr_db),
        "reference_tone_check": reference_check,
        "passing_centers_mhz": center_values,
        "target_rows": target_rows,
        "invalid_cases": invalid_cases,
        "allowed_classifications": list(ALLOWED_STAGE27I_SPUR_CLASSIFICATIONS),
    }


def _antialias_status_row(case: dict[str, Any]) -> dict[str, Any]:
    status = case.get("science_status") if isinstance(case.get("science_status"), dict) else {}
    fallback = case.get("status") if isinstance(case.get("status"), dict) else {}
    def field(name: str, default: Any = None) -> Any:
        if name in status:
            return status.get(name)
        return fallback.get(name, default)

    taps = int(field("science_antialias_taps", 0) or 0)
    active = int(field("science_antialias_100m_active", 0) or 0)
    primed = int(field("science_antialias_100m_primed", 0) or 0)
    coeff_version = int(field("science_antialias_coeff_version", 0) or 0)
    ok = bool(active == 1 and primed == 1 and taps == 41 and coeff_version == 0xAA10_0041)
    return {
        "case": case.get("name"),
        "case_type": case.get("case_type"),
        "bandwidth_mhz": case.get("bandwidth_mhz"),
        "active": active,
        "primed": primed,
        "taps": taps,
        "coeff_version": f"0x{coeff_version:08x}",
        "ok": ok,
    }


def _classify_stage27i_antialias_acceptance(cases: list[dict[str, Any]], *, target_rf_mhz: float, min_snr_db: float) -> dict[str, Any]:
    invalid_cases = [
        {
            "case": case.get("name"),
            "reason": case.get("invalid_for_spur_reason") or case.get("error") or "not marked valid_for_spur",
            "fengine_clean_gate": case.get("fengine_clean_gate"),
        }
        for case in cases
        if case.get("valid_for_spur") is not True
    ]
    valid_cases = [case for case in cases if case.get("valid_for_spur") is True and not case.get("error")]
    target_rows = _target_metric_rows(valid_cases, min_snr_db=min_snr_db)
    reference_check = _reference_tone_check(valid_cases, min_snr_db=min_snr_db)
    readback_mismatches = _readback_mismatches(valid_cases)
    zero_case_types = {"zero_amp_enable_ff", "zero_amp_enable_00", "zero_amp_dac_nco_sweep"}
    zero_rows = [row for row in target_rows if row.get("case_type") in zero_case_types]
    zero_status_rows = [
        _antialias_status_row(case)
        for case in valid_cases
        if case.get("case_type") in zero_case_types or case.get("case_type") == "reference_tone_on"
    ]
    required_case_types = {"zero_amp_enable_ff", "zero_amp_enable_00"}
    present_case_types = {str(row.get("case_type")) for row in zero_rows}
    missing_required = sorted(required_case_types - present_case_types)
    failed_zero_rows = []
    for row in zero_rows:
        time_ready = bool(row.get("time_in_band")) and row.get("time_snr_db") is not None
        spec_ready = bool(row.get("spec_in_band")) and row.get("spec_snr_db") is not None
        if not time_ready or not spec_ready or bool(row.get("time_pass")) or bool(row.get("spec_pass")):
            failed_zero_rows.append(row)
    failed_status_rows = [row for row in zero_status_rows if not row.get("ok")]

    if invalid_cases:
        classification = "stage27i_100m_antialias_acceptance_fail"
        reason = "one or more anti-alias acceptance cases failed the clean production gate"
    elif readback_mismatches:
        classification = "stage27i_100m_antialias_acceptance_fail"
        reason = "RFDC readback mismatches remain during anti-alias acceptance"
    elif missing_required:
        classification = "stage27i_100m_antialias_acceptance_fail"
        reason = f"missing required zero-amplitude cases: {', '.join(missing_required)}"
    elif failed_status_rows:
        classification = "stage27i_100m_antialias_acceptance_fail"
        reason = "100MHz anti-alias FIR status is not active/primed with expected coefficient version"
    elif failed_zero_rows:
        classification = "stage27i_100m_antialias_acceptance_fail"
        reason = "122.88MHz target bin is still above the SNR threshold, missing, or outside the expected production band"
    elif not reference_check.get("available") or not reference_check.get("ok"):
        classification = "stage27i_100m_antialias_acceptance_fail"
        reason = "reference tone did not validate production TIME/SPEC frequency placement"
    else:
        classification = "stage27i_100m_antialias_spur_suppressed"
        reason = "100MHz anti-alias FIR is active; zero-amplitude production TIME/SPEC target bins are below threshold and reference tone placement is valid"

    return {
        "classification": classification,
        "reason": reason,
        "target_rf_mhz": float(target_rf_mhz),
        "min_snr_db": float(min_snr_db),
        "reference_tone_check": reference_check,
        "zero_case_count": len(zero_rows),
        "missing_required_zero_case_types": missing_required,
        "failed_zero_rows": failed_zero_rows,
        "anti_alias_status_rows": zero_status_rows,
        "failed_anti_alias_status_rows": failed_status_rows,
        "rfdc_mismatches": readback_mismatches,
        "target_rows": target_rows,
        "invalid_cases": invalid_cases,
        "allowed_classifications": list(ALLOWED_STAGE27I_SPUR_CLASSIFICATIONS),
        "note": "This is a post-fix acceptance classifier: success means the old 122.88MHz target is suppressed in zero-amplitude 100MHz production TIME/SPEC, not that a fixed-RF spur was found.",
    }


def _classify(cases: list[dict[str, Any]]) -> dict[str, Any]:
    invalid_cases = [
        {
            "case": case.get("name"),
            "reason": case.get("invalid_for_spur_reason") or case.get("error") or "not marked valid_for_spur",
            "fengine_clean_gate": case.get("fengine_clean_gate"),
        }
        for case in cases
        if case.get("valid_for_spur") is not True
    ]
    valid_cases = [case for case in cases if case.get("valid_for_spur") is True and not case.get("error")]
    production_consistency = _consistency_rows(valid_cases, time_source="production_time")
    raw_preview_consistency = _consistency_rows(valid_cases, time_source="raw_preview")
    if not valid_cases:
        return {
            "classification": "inconclusive",
            "reason": "no case passed the F-engine clean gate; dirty overflow/tlast states are not valid spur evidence",
            "invalid_cases": invalid_cases,
            "production_time_spec_consistency": production_consistency,
            "raw_preview_spec_consistency": raw_preview_consistency,
        }
    has_production_time = any(row.get("nearest_time_baseband_mhz") is not None for row in production_consistency)
    spec_only = has_production_time and any(
        row.get("spec_baseband_mhz") is not None
        and (row.get("nearest_time_delta_mhz") is None or float(row["nearest_time_delta_mhz"]) > 2.0)
        for row in production_consistency
    )
    if spec_only:
        return {
            "classification": "spec_only_issue",
            "reason": "SPEC top peak has no matching production TIME waveform peak within 2MHz in at least one case",
            "invalid_cases": invalid_cases,
            "production_time_spec_consistency": production_consistency,
            "raw_preview_spec_consistency": raw_preview_consistency,
        }

    for source in ("production_time", "spec", "raw_preview"):
        zero_ff = [
            case
            for case in valid_cases
            if case.get("case_type") == "zero_amp_enable_ff" and _primary_peak(case, source) is not None
        ]
        zero_00 = [
            case
            for case in valid_cases
            if case.get("case_type") == "zero_amp_enable_00" and _primary_peak(case, source) is not None
        ]
        for off in zero_00:
            if not zero_ff:
                break
            ff = min(zero_ff, key=lambda item: abs(float(item["center_mhz"]) - float(off["center_mhz"])))
            center_delta = abs(float(ff["center_mhz"]) - float(off["center_mhz"]))
            if center_delta > 1.0:
                continue
            ff_peak = _primary_peak(ff, source)
            off_peak = _primary_peak(off, source)
            if ff_peak and off_peak:
                power_drop = float(ff_peak["power_db"]) - float(off_peak["power_db"])
                loc_delta = abs(float(ff_peak["baseband_mhz"]) - float(off_peak["baseband_mhz"]))
                if power_drop > 12.0 or loc_delta > 5.0:
                    return {
                        "classification": "dac_related_spur",
                        "source": source,
                        "reason": f"DAC enable-mask change removed or shifted the zero-amplitude {source} spur",
                        "enable_ff_peak": ff_peak,
                        "enable_00_peak": off_peak,
                        "power_drop_db": power_drop,
                        "baseband_delta_mhz": loc_delta,
                        "center_delta_mhz": center_delta,
                        "invalid_cases": invalid_cases,
                        "production_time_spec_consistency": production_consistency,
                        "raw_preview_spec_consistency": raw_preview_consistency,
                    }

        if len(zero_ff) >= 3:
            basebands = [float(_primary_peak(case, source)["baseband_mhz"]) for case in zero_ff]  # type: ignore[index]
            rfs = [float(_primary_peak(case, source)["rf_mhz"]) for case in zero_ff]  # type: ignore[index]
            baseband_span = max(basebands) - min(basebands)
            rf_span = max(rfs) - min(rfs)
            if baseband_span <= 2.0:
                return {
                    "classification": "fixed_baseband_spur",
                    "source": source,
                    "reason": f"zero-amplitude {source} top peak stays at a fixed baseband frequency across center sweep",
                    "baseband_span_mhz": baseband_span,
                    "rf_span_mhz": rf_span,
                    "invalid_cases": invalid_cases,
                    "production_time_spec_consistency": production_consistency,
                    "raw_preview_spec_consistency": raw_preview_consistency,
                }
            if rf_span <= 2.0:
                return {
                    "classification": "fixed_rf_spur",
                    "source": source,
                    "reason": f"zero-amplitude {source} top peak stays at a fixed absolute RF frequency across center sweep",
                    "baseband_span_mhz": baseband_span,
                    "rf_span_mhz": rf_span,
                    "invalid_cases": invalid_cases,
                    "production_time_spec_consistency": production_consistency,
                    "raw_preview_spec_consistency": raw_preview_consistency,
                }

    if has_production_time and not any(row.get("spec_baseband_mhz") is not None for row in production_consistency):
        return {
            "classification": "time_decode_issue",
            "reason": "production TIME waveform sees a strong spur but no SPEC TSP3 comparison was available",
            "invalid_cases": invalid_cases,
            "production_time_spec_consistency": production_consistency,
            "raw_preview_spec_consistency": raw_preview_consistency,
        }
    return {
        "classification": "inconclusive",
        "reason": "insufficient high-SNR center sweep data to classify the spur",
        "invalid_cases": invalid_cases,
        "production_time_spec_consistency": production_consistency,
        "raw_preview_spec_consistency": raw_preview_consistency,
    }


def _run_case(core: Any, args: argparse.Namespace, case: dict[str, Any], *, initialize: bool) -> dict[str, Any]:
    center_mhz = float(case["center_mhz"])
    dac_mhz = float(case["dac_mhz"])
    expected_mhz = float(case["expected_mhz"])
    bandwidth_mhz = int(case.get("bandwidth_mhz", args.bandwidth_mhz))
    output_mode = str(case.get("output_mode", "time_spec"))
    clock_ref = str(case.get("clock_ref", "external_10mhz"))
    amplitude = int(case["amplitude"])
    enable_mask = int(case["enable_mask"])
    mode_key = output_mode.strip().lower().replace("-", "_").replace(" ", "_")
    expects_time = mode_key in ("time_only", "time_spec", "dual")
    expects_spec = mode_key in ("spec_only", "time_spec", "dual")
    target_enabled = (
        bool(args.fixed_rf_audit)
        or bool(getattr(args, "board_internal_audit", False))
        or bool(getattr(args, "stage27i_diag_audit", False))
        or bool(getattr(args, "stage27i_front_end_audit", False))
        or bool(getattr(args, "stage27i_spec_sideband_audit", False))
        or bool(getattr(args, "stage27i_rfdc_200m_rootcause_audit", False))
        or bool(getattr(args, "stage27i_100m_spur_taxonomy_audit", False))
        or bool(getattr(args, "stage27i_rfdc_mixer_event_audit", False))
        or bool(getattr(args, "stage27i_rfdc_mixer_sequence_audit", False))
        or bool(getattr(args, "stage27i_raw_lane_witness_audit", False))
    )
    result: dict[str, Any] = dict(case)
    result["sync_mode"] = str(args.sync_mode)
    result["start_time_unix"] = time.time()

    pre_clear_status = _clear_stage27h_production_path(core, args)
    rfdc_readback_before_observation = _safe_call(core.read_rfdc_sync_status)
    diag_request = case.get("diag_control")
    if isinstance(diag_request, dict):
        result["diag_before"] = _safe_call(core.read_stage27i_diag_control)
        result["diag_config"] = _safe_call(core.configure_stage27i_diag, **diag_request)
        result["diag_after_config"] = _safe_call(core.read_stage27i_diag_control)
    observation = core.apply_mts_locked_observation_config(
        observe_center_hz=center_mhz * 1_000_000.0,
        view_bw_hz=float(bandwidth_mhz) * 1_000_000.0,
        dac_signal_hz=dac_mhz * 1_000_000.0,
        expected_signal_hz=expected_mhz * 1_000_000.0,
        amplitude=amplitude,
        enable_mask=enable_mask,
        adc_active_mask=int(args.input_mask, 0),
        initialize=initialize,
        start=False,
        dac_source_mode="constant_phasor",
        input_source_mode="dac_loopback",
        clock_ref=clock_ref,
        sync_mode=args.sync_mode,
        require_mts=not bool(args.no_require_mts),
        require_full_clock_lock=not bool(args.no_require_clock_lock),
        force_clock_reconfigure=bool(getattr(args, "force_clock_reconfigure", False)),
        rfdc_mixer_sequence=str(case.get("rfdc_mixer_sequence", "sysref_reset_before_pulse")),
    )
    rfdc_readback_after_observation = _safe_call(core.read_rfdc_sync_status)
    recovery_status = _prepare_stream_after_observation(core, float(args.stream_timeout))
    science_start = not isinstance(diag_request, dict)
    science = core.configure_science_27h(
        bandwidth_mhz=bandwidth_mhz,
        output_mode=output_mode,
        dst_ip=args.dst_ip,
        dst_mac=args.dst_mac,
        src_ip=args.src_ip,
        src_mac=args.src_mac,
        input_mask=int(args.input_mask, 0),
        diagnostic_ignore_link_gate=bool(args.diagnostic_ignore_link_gate),
        start=science_start,
        settle_s=float(args.settle_s),
    )
    rfdc_readback_after_science = _safe_call(core.read_rfdc_sync_status)
    if isinstance(diag_request, dict):
        result["diag_after_science_config"] = _safe_call(core.configure_stage27i_diag, **diag_request)
        result["diag_after_science_readback"] = _safe_call(core.read_stage27i_diag_control)
    core.set_mode("time" if expects_time and not expects_spec else "spec" if expects_spec and not expects_time else "dual")
    core.start()
    stream_status = _wait_streaming(core, float(args.stream_timeout))
    rfdc_readback_after_stream_start = _safe_call(core.read_rfdc_sync_status)
    sysref_action_result = None
    sysref_action = str(case.get("sysref_action", "none") or "none")
    if sysref_action == "pulse_before_capture":
        sysref_action_result = {
            "before": _safe_call(core.clock.read_status, include_registers=False),
            "pulse": _safe_call(
                core.clock.pulse_sysref,
                width_s=float(args.sysref_pulse_width_s),
                settle_s=float(args.sysref_pulse_settle_s),
            ),
            "after": _safe_call(core.clock.read_status, include_registers=False),
        }
    elif sysref_action != "none":
        raise ValueError(f"unsupported sysref_action {sysref_action!r}")
    time.sleep(float(args.settle_s))
    fengine_clean_gate = (
        _capture_fengine_clean_gate(core, float(args.fengine_clean_seconds))
        if expects_spec
        else _capture_time_path_clean_gate(core, float(args.fengine_clean_seconds))
    )
    rootcause_telemetry = (
        _safe_call(_capture_stage27i_rootcause_telemetry, core, float(args.rootcause_telemetry_seconds))
        if bool(getattr(args, "stage27i_rfdc_200m_rootcause_audit", False))
        else None
    )
    valid_for_spur = bool(fengine_clean_gate.get("clean"))
    status = core.read_status()
    preview = _safe_call(core.capture_preview_fast, n=int(args.samples), input_mask=int(args.input_mask, 0), timeout=float(args.timeout))
    time_preview = (
        _safe_call(_time_preview_fft, preview, center_mhz=center_mhz, top_count=int(args.top_count))
        if isinstance(preview, dict) and "error" not in preview
        else preview
    )
    raw_witness_summary = None
    if bool(getattr(args, "stage27i_raw_lane_witness_audit", False)):
        raw_captures: dict[int, dict[str, Any]] = {}
        raw_capture_errors: dict[str, Any] = {}
        for channel in range(8):
            capture = _safe_call(
                core.capture_rfdc_axis_raw_witness,
                channel=channel,
                capture_beats=int(args.raw_witness_beats),
                timeout=float(args.raw_witness_timeout),
            )
            if isinstance(capture, dict) and "error" in capture:
                raw_capture_errors[str(channel)] = capture
            elif isinstance(capture, dict):
                raw_captures[channel] = capture
            else:
                raw_capture_errors[str(channel)] = {"error": f"unexpected capture result {type(capture).__name__}"}
        raw_witness_summary = _safe_call(
            _raw_witness_fft,
            raw_captures,
            center_mhz=center_mhz,
            target_rf_mhz=float(args.target_rf_mhz) if target_enabled else None,
            target_search_half_width_mhz=float(args.target_search_half_width_mhz),
            top_count=int(args.top_count),
            sample_rate_hz=float(args.raw_witness_sample_rate_hz),
        )
        if isinstance(raw_witness_summary, dict):
            raw_witness_summary["capture_errors"] = raw_capture_errors
            raw_witness_summary["capture_beats_requested"] = int(args.raw_witness_beats)
            raw_witness_summary["pre_diag_boundary"] = True
    result.update(
        {
            "pre_clear_status": pre_clear_status,
            "rfdc_readback_before_observation": rfdc_readback_before_observation,
            "observation_config": observation,
            "rfdc_readback_after_observation": rfdc_readback_after_observation,
            "post_observation_recovery_status": recovery_status,
            "science_config": science,
            "rfdc_readback_after_science": rfdc_readback_after_science,
            "stream_status": stream_status,
            "rfdc_readback_after_stream_start": rfdc_readback_after_stream_start,
            "sysref_action_result": sysref_action_result,
            "fengine_clean_gate": fengine_clean_gate,
            "rootcause_telemetry": rootcause_telemetry,
            "valid_for_spur": valid_for_spur,
            "invalid_for_spur_reason": None if valid_for_spur else "FENGINE_CLEAN_GATE_FAILED",
            "status": status,
            "science_status": _safe_call(core.read_science_output_status),
            "channelizer_status": _safe_call(core.read_channelizer_status),
            "tx_status": _safe_call(core.read_tx_status),
            "dac_registers": _read_dac_registers(core),
            "dac_audit_status": _safe_call(core.read_dac_audit_status),
            "lmk_status": _safe_call(core.clock.read_status, include_registers=True),
            "rfdc_sync_status": _safe_call(core.read_rfdc_sync_status),
            "external_sync_diagnostics": _safe_call(
                core.read_external_sync_diagnostics,
                interval_s=0.1,
                include_lmk_registers=False,
            ),
            "time_preview": time_preview,
            "rfdc_axis_raw_witness": raw_witness_summary,
        }
    )
    result["rfdc_readback_check"] = _rfdc_readback_check(result)
    result["sync_readback_summary"] = _sync_readback_summary(result)
    if not valid_for_spur and not bool(getattr(args, "capture_dirty_previews", False)):
        result["rust_previews"] = {
            "skipped": True,
            "reason": "FENGINE_CLEAN_GATE_FAILED",
            "fengine_clean_gate_reasons": list(fengine_clean_gate.get("reasons", [])),
        }
    elif not (args.skip_rust_waveform and args.skip_rust_spectrum):
        result["dirty_preview_capture"] = bool(not valid_for_spur)
        rust_previews = _safe_call(
            _capture_rust_previews,
            args.rust_web_url,
            center_mhz=center_mhz,
            bandwidth_mhz=bandwidth_mhz,
            expected_mhz=expected_mhz,
            dac_mhz=dac_mhz,
            target_rf_mhz=float(args.target_rf_mhz) if target_enabled else None,
            target_search_half_width_mhz=float(args.target_search_half_width_mhz),
            timeout=float(args.rust_timeout),
            top_count=int(args.top_count),
            time_window_us=float(args.rust_time_window_us),
            capture_retries=int(args.rust_capture_retries),
            capture_waveform=expects_time and not bool(args.skip_rust_waveform),
            capture_spectrum=expects_spec and not bool(args.skip_rust_spectrum),
        )
        result["rust_previews"] = rust_previews
        if isinstance(rust_previews, dict):
            if "waveform" in rust_previews:
                result["rust_time_waveform"] = rust_previews["waveform"]
            if "spectrum" in rust_previews:
                result["rust_spectrum"] = rust_previews["spectrum"]
    result["end_time_unix"] = time.time()
    return result


def main() -> int:
    _add_repo_python_path()
    from python.t510_fengine import T510FEngine

    default_bitfile = _repo_root() / "overlay" / "t510_fengine.bit"
    default_output = _repo_root() / "reports" / "board" / "stage27h_rfdc_time_spur_audit.json"
    parser = argparse.ArgumentParser(description="Stage 27h RFDC/TIME fixed-spur audit with production TIME/SPEC Rust Web cross-check.")
    parser.add_argument("--bitfile", default=str(default_bitfile))
    parser.add_argument("--no-download", action="store_true")
    parser.add_argument(
        "--download-each-case",
        dest="download_each_case",
        action="store_true",
        help="Reload the Stage 27h bitstream before each audit case to avoid RFDC/F-engine reconfiguration residue.",
    )
    parser.add_argument(
        "--no-download-each-case",
        dest="download_each_case",
        action="store_false",
        help="Keep one programmed bitstream across all audit cases; faster but vulnerable to cross-case state contamination.",
    )
    parser.add_argument("--output", default=str(default_output))
    parser.add_argument("--fixed-rf-audit", action="store_true", help="Run the Stage 27h fixed absolute-RF spur audit using direct target-bin metrics.")
    parser.add_argument("--board-internal-audit", action="store_true", help="Run the Stage 27h board-internal 122.88MHz clock/RFDC sweep without requiring a DAC-ADC reference tone.")
    parser.add_argument("--stage27i-diag-audit", action="store_true", help="Run Stage 27i diagnostic mux cases against the 0x00010029 diagnostic bitstream.")
    parser.add_argument("--stage27i-front-end-audit", action="store_true", help="Run Stage 27i front-end clock/RFDC/ADC spur localization against the 0x00010029 diagnostic bitstream.")
    parser.add_argument("--stage27i-spec-sideband-audit", action="store_true", help="Run Stage 27i SPEC_ONLY 100MHz/200MHz sideband sign audit against the 0x00010029 diagnostic bitstream.")
    parser.add_argument("--stage27i-rfdc-200m-rootcause-audit", action="store_true", help="Run Stage 27i RFDC 100/200MHz target/mirror/left-edge and XFFT backpressure root-cause audit.")
    parser.add_argument("--stage27i-100m-spur-taxonomy-audit", action="store_true", help="Run Stage 27i 100MHz-only TIME-first spur taxonomy audit.")
    parser.add_argument("--stage27i-rfdc-mixer-event-audit", action="store_true", help="Run Stage 27i 100MHz RFDC mixer/NCO/SYSREF event sensitivity audit.")
    parser.add_argument("--stage27i-rfdc-mixer-sequence-audit", action="store_true", help="Run Stage 27i 100MHz RFDC EventSource/UpdateEvent/ResetNCOPhase sequence audit.")
    parser.add_argument("--stage27i-raw-lane-witness-audit", action="store_true", help="Run Stage 27i 0x0001002A pre-diag RFDC raw-lane witness audit.")
    parser.add_argument("--stage27i-antialias-acceptance", action="store_true", help="Run Stage 27i 0x0001002B 100MHz anti-alias post-fix acceptance against the 122.88MHz target.")
    parser.add_argument("--physical-state", default="unspecified", help="Free-form physical setup label stored in every case, e.g. adc_to_spectrum_analyzer_50ohm.")
    parser.add_argument("--clock-refs", default=_parse_str_list("external_10mhz,tcxo_10mhz"), type=_parse_str_list)
    parser.add_argument("--mode-sweep", default=_parse_mode_sweep("20:spec_only,100:time_spec,100:spec_only,100:time_only"), type=_parse_mode_sweep)
    parser.add_argument(
        "--front-end-mode-sweep",
        default=_parse_mode_sweep("20:spec_only,100:time_spec,100:spec_only,100:time_only,200:spec_only,200:time_only"),
        type=_parse_mode_sweep,
        help="Mode/bandwidth cases for --stage27i-front-end-audit; TIME_SPEC 200MHz remains rejected.",
    )
    parser.add_argument("--board-internal-center-mhz", type=float, default=100.0)
    parser.add_argument("--board-internal-20mhz-center-mhz", type=float, default=120.0)
    parser.add_argument("--target-rf-mhz", type=float, default=122.88)
    parser.add_argument("--target-search-half-width-mhz", type=float, default=0.30)
    parser.add_argument("--target-snr-db", type=float, default=12.0)
    parser.add_argument("--centers-mhz", default=None, type=_parse_centers)
    parser.add_argument("--dac-nco-sweep-mhz", default=_parse_float_list("60,100,122.88,180"), type=_parse_float_list)
    parser.add_argument("--bandwidth-mhz", type=int, default=100, choices=(20, 100, 200))
    parser.add_argument("--expected-mhz", type=float, default=60.010)
    parser.add_argument("--reference-center-mhz", type=float, default=100.0)
    parser.add_argument("--reference-tone-mhz", type=float, default=60.0)
    parser.add_argument("--reference-amplitude", type=int, default=4096)
    parser.add_argument("--no-reference-case", action="store_true")
    parser.add_argument("--samples", type=int, default=4096)
    parser.add_argument("--top-count", type=int, default=12)
    parser.add_argument("--timeout", type=float, default=2.0)
    parser.add_argument("--stream-timeout", type=float, default=5.0)
    parser.add_argument("--settle-s", type=float, default=0.25)
    parser.add_argument(
        "--fengine-clean-seconds",
        type=float,
        default=1.0,
        help="Require zero Stage 27h F-engine error-counter delta over this window before using TIME/SPEC preview as spur evidence.",
    )
    parser.add_argument("--sync-mode", default="external_pps")
    parser.add_argument("--input-mask", default="0x00ff")
    parser.add_argument("--dst-ip", default="10.0.1.16")
    parser.add_argument("--dst-mac", default="08:c0:eb:d5:95:b2")
    parser.add_argument("--src-ip", default="10.0.1.1")
    parser.add_argument("--src-mac", default="02:00:00:00:00:01")
    parser.add_argument("--diagnostic-ignore-link-gate", action="store_true")
    parser.add_argument(
        "--rust-web-url",
        default=os.environ.get("STAGE27H_RUST_WEB_URL", "http://192.168.100.192:8089"),
        help="Rust Web URL reachable from the PYNQ management network; override with STAGE27H_RUST_WEB_URL.",
    )
    parser.add_argument("--rust-timeout", type=float, default=12.0)
    parser.add_argument("--rust-time-window-us", type=float, default=25.0)
    parser.add_argument("--rust-capture-retries", type=int, default=3)
    parser.add_argument("--skip-rust-waveform", action="store_true")
    parser.add_argument("--skip-rust-spectrum", action="store_true")
    parser.add_argument("--capture-dirty-previews", action="store_true", help="Capture Rust preview frames even when the F-engine clean gate fails; diagnostic evidence only.")
    parser.add_argument("--rootcause-telemetry-seconds", type=float, default=0.25, help="Short per-case counter/route delta window for --stage27i-rfdc-200m-rootcause-audit.")
    parser.add_argument("--raw-witness-beats", type=int, default=256, help="RFDC raw-lane witness capture length in 4-sample beats.")
    parser.add_argument("--raw-witness-timeout", type=float, default=1.0)
    parser.add_argument("--raw-witness-sample-rate-hz", type=float, default=RAW_SAMPLE_RATE_HZ)
    parser.add_argument("--sysref-pulse-width-s", type=float, default=0.05)
    parser.add_argument("--sysref-pulse-settle-s", type=float, default=0.05)
    parser.add_argument("--no-require-mts", action="store_true")
    parser.add_argument("--no-require-clock-lock", action="store_true")
    parser.add_argument("--force-clock-reconfigure", action="store_true")
    parser.add_argument("--no-restore-dac-off", dest="restore_dac_off", action="store_false")
    parser.set_defaults(restore_dac_off=True, download_each_case=True)
    parser.add_argument("--expected-core-version", type=lambda value: int(value, 0), default=EXPECTED_CORE_VERSION)
    args = parser.parse_args()
    if bool(args.stage27i_diag_audit):
        args.fixed_rf_audit = True
        args.no_reference_case = True
        if int(args.expected_core_version) == EXPECTED_CORE_VERSION:
            args.expected_core_version = 0x0001_0029
    if bool(args.stage27i_front_end_audit):
        args.fixed_rf_audit = True
        args.no_reference_case = True
        args.force_clock_reconfigure = True
        if int(args.expected_core_version) == EXPECTED_CORE_VERSION:
            args.expected_core_version = 0x0001_0029
    if bool(args.stage27i_spec_sideband_audit):
        args.fixed_rf_audit = True
        args.no_reference_case = True
        args.capture_dirty_previews = True
        args.force_clock_reconfigure = True
        args.top_count = max(int(args.top_count), 32)
        if int(args.expected_core_version) == EXPECTED_CORE_VERSION:
            args.expected_core_version = 0x0001_0029
    if bool(args.stage27i_rfdc_200m_rootcause_audit):
        args.fixed_rf_audit = True
        args.no_reference_case = True
        args.capture_dirty_previews = True
        args.force_clock_reconfigure = True
        args.top_count = max(int(args.top_count), 32)
        if int(args.expected_core_version) == EXPECTED_CORE_VERSION:
            args.expected_core_version = 0x0001_0029
    if bool(args.stage27i_100m_spur_taxonomy_audit):
        args.fixed_rf_audit = True
        args.no_reference_case = True
        args.force_clock_reconfigure = True
        args.top_count = max(int(args.top_count), 32)
        if int(args.expected_core_version) == EXPECTED_CORE_VERSION:
            args.expected_core_version = 0x0001_0029
    if bool(args.stage27i_rfdc_mixer_event_audit):
        args.fixed_rf_audit = True
        args.no_reference_case = True
        args.force_clock_reconfigure = True
        args.top_count = max(int(args.top_count), 32)
        if int(args.expected_core_version) == EXPECTED_CORE_VERSION:
            args.expected_core_version = 0x0001_0029
    if bool(args.stage27i_rfdc_mixer_sequence_audit):
        args.fixed_rf_audit = True
        args.no_reference_case = True
        args.force_clock_reconfigure = True
        args.top_count = max(int(args.top_count), 32)
        if int(args.expected_core_version) == EXPECTED_CORE_VERSION:
            args.expected_core_version = 0x0001_0029
    if bool(args.stage27i_raw_lane_witness_audit):
        args.fixed_rf_audit = True
        args.no_reference_case = True
        args.force_clock_reconfigure = True
        args.top_count = max(int(args.top_count), 32)
        if int(args.expected_core_version) == EXPECTED_CORE_VERSION:
            args.expected_core_version = 0x0001_002A
    if bool(args.stage27i_antialias_acceptance):
        args.fixed_rf_audit = True
        args.force_clock_reconfigure = True
        args.bandwidth_mhz = 100
        args.top_count = max(int(args.top_count), 32)
        if int(args.expected_core_version) == EXPECTED_CORE_VERSION:
            args.expected_core_version = 0x0001_002B
    if bool(args.board_internal_audit):
        args.fixed_rf_audit = True
        args.no_reference_case = True
        args.force_clock_reconfigure = True
    if args.centers_mhz is None:
        if bool(args.stage27i_front_end_audit):
            args.centers_mhz = _parse_centers("80,100,122.88,140,160")
        elif bool(args.stage27i_rfdc_200m_rootcause_audit):
            args.centers_mhz = _parse_centers("100,122.88,140,160")
        elif bool(args.stage27i_100m_spur_taxonomy_audit):
            args.centers_mhz = _parse_centers("70,80,90,100,110,120,122.88,130,140,150,160")
        elif bool(args.stage27i_rfdc_mixer_event_audit):
            args.centers_mhz = _parse_centers("100,120,122.88,130,140")
        elif bool(args.stage27i_rfdc_mixer_sequence_audit):
            args.centers_mhz = _parse_centers("100,122.88,130,140")
        elif bool(args.stage27i_raw_lane_witness_audit):
            args.centers_mhz = _parse_centers("100,122.88,130,140")
        elif bool(args.stage27i_antialias_acceptance):
            args.centers_mhz = _parse_centers("100")
        else:
            args.centers_mhz = _parse_centers("70,80,90,100,110,120,130,140,150,160,170,180") if bool(args.fixed_rf_audit) else _parse_centers("80,100,120,160")

    core = T510FEngine(args.bitfile, download=not args.no_download)
    initial_status = core.read_status()
    errors: list[str] = []
    if int(initial_status.get("core_version", 0)) != int(args.expected_core_version):
        errors.append(
            f"expected CORE_VERSION 0x{int(args.expected_core_version):08x}, "
            f"got 0x{int(initial_status.get('core_version', 0)):08x}"
        )

    cases: list[dict[str, Any]] = []
    if bool(args.stage27i_raw_lane_witness_audit):
        diag_off = {
            "adc_force_zero": False,
            "adc_force_hold": False,
            "adc_channel_mask": 0xFF,
            "dac_gate": False,
        }
        force_zero = {
            "adc_force_zero": True,
            "adc_force_hold": False,
            "adc_channel_mask": 0xFF,
            "dac_gate": False,
        }
        common_case = {
            "case_type": "stage27i_raw_lane",
            "physical_state": str(args.physical_state),
            "clock_ref": "external_10mhz",
            "bandwidth_mhz": 100,
            "center_mhz": float(args.board_internal_center_mhz),
            "expected_mhz": float(args.board_internal_center_mhz),
            "dac_mhz": float(args.board_internal_center_mhz),
            "amplitude": 0,
            "enable_mask": 0xFF,
            "target_rf_mhz": float(args.target_rf_mhz),
            "diag_control": diag_off,
            "rfdc_mixer_sequence": "sysref_reset_before_pulse",
        }
        cases.append(
            {
                **common_case,
                "name": f"stage27i_raw_lane_force_zero_start_center_{float(args.board_internal_center_mhz):.3f}",
                "case_type": "stage27i_raw_lane_force_zero",
                "taxonomy_role": "force_zero_sentinel",
                "sentinel_position": "start",
                "output_mode": "time_spec",
                "diag_control": force_zero,
            }
        )
        for center_mhz in args.centers_mhz:
            center_mhz = float(center_mhz)
            cases.append(
                {
                    **common_case,
                    "name": f"stage27i_raw_lane_time_spec_center_{center_mhz:.3f}",
                    "case_type": "stage27i_raw_lane_time_spec",
                    "taxonomy_role": "raw_lane_time_spec_center",
                    "output_mode": "time_spec",
                    "center_mhz": center_mhz,
                    "expected_mhz": center_mhz,
                    "dac_mhz": center_mhz,
                    "force_download_before_case": abs(center_mhz - float(args.target_rf_mhz)) <= 0.5,
                }
            )
        cases.append(
            {
                **common_case,
                "name": f"stage27i_raw_lane_force_zero_end_center_{float(args.board_internal_center_mhz):.3f}",
                "case_type": "stage27i_raw_lane_force_zero",
                "taxonomy_role": "force_zero_sentinel",
                "sentinel_position": "end",
                "output_mode": "time_spec",
                "diag_control": force_zero,
                "force_download_before_case": True,
            }
        )
    elif bool(args.stage27i_rfdc_mixer_sequence_audit):
        diag_off = {
            "adc_force_zero": False,
            "adc_force_hold": False,
            "adc_channel_mask": 0xFF,
            "dac_gate": False,
        }
        force_zero = {
            "adc_force_zero": True,
            "adc_force_hold": False,
            "adc_channel_mask": 0xFF,
            "dac_gate": False,
        }
        sequence_names = (
            "sysref_reset_before_pulse",
            "sysref_no_reset",
            "tile_update_then_reset",
            "tile_reset_then_update",
            "tile_update_no_reset",
        )
        common_case = {
            "case_type": "stage27i_mixer_sequence",
            "physical_state": str(args.physical_state),
            "clock_ref": "external_10mhz",
            "bandwidth_mhz": 100,
            "center_mhz": float(args.board_internal_center_mhz),
            "expected_mhz": float(args.board_internal_center_mhz),
            "dac_mhz": float(args.board_internal_center_mhz),
            "amplitude": 0,
            "enable_mask": 0xFF,
            "target_rf_mhz": float(args.target_rf_mhz),
            "diag_control": diag_off,
        }
        cases.append(
            {
                **common_case,
                "name": f"stage27i_mixer_sequence_force_zero_start_center_{float(args.board_internal_center_mhz):.3f}",
                "case_type": "stage27i_mixer_sequence_force_zero",
                "taxonomy_role": "force_zero_sentinel",
                "sentinel_position": "start",
                "output_mode": "time_spec",
                "diag_control": force_zero,
                "rfdc_mixer_sequence": "sysref_reset_before_pulse",
            }
        )
        for center_mhz in args.centers_mhz:
            center_mhz = float(center_mhz)
            for sequence_index, sequence_name in enumerate(sequence_names):
                cases.append(
                    {
                        **common_case,
                        "name": f"stage27i_mixer_sequence_{sequence_name}_center_{center_mhz:.3f}",
                        "case_type": "stage27i_mixer_sequence_case",
                        "taxonomy_role": "mixer_sequence",
                        "sequence_index": sequence_index,
                        "rfdc_mixer_sequence": sequence_name,
                        "output_mode": "time_only",
                        "center_mhz": center_mhz,
                        "expected_mhz": center_mhz,
                        "dac_mhz": center_mhz,
                    }
                )
        cases.append(
            {
                **common_case,
                "name": f"stage27i_mixer_sequence_force_zero_end_center_{float(args.board_internal_center_mhz):.3f}",
                "case_type": "stage27i_mixer_sequence_force_zero",
                "taxonomy_role": "force_zero_sentinel",
                "sentinel_position": "end",
                "output_mode": "time_spec",
                "diag_control": force_zero,
                "rfdc_mixer_sequence": "sysref_reset_before_pulse",
                "force_download_before_case": True,
            }
        )
    elif bool(args.stage27i_rfdc_mixer_event_audit):
        diag_off = {
            "adc_force_zero": False,
            "adc_force_hold": False,
            "adc_channel_mask": 0xFF,
            "dac_gate": False,
        }
        force_zero = {
            "adc_force_zero": True,
            "adc_force_hold": False,
            "adc_channel_mask": 0xFF,
            "dac_gate": False,
        }
        common_case = {
            "case_type": "stage27i_mixer_event",
            "physical_state": str(args.physical_state),
            "clock_ref": "external_10mhz",
            "bandwidth_mhz": 100,
            "center_mhz": float(args.board_internal_center_mhz),
            "expected_mhz": float(args.board_internal_center_mhz),
            "dac_mhz": float(args.board_internal_center_mhz),
            "amplitude": 0,
            "enable_mask": 0xFF,
            "target_rf_mhz": float(args.target_rf_mhz),
            "diag_control": diag_off,
            "rfdc_event_path": "observation_apply_update_event_reset_nco",
        }
        cases.append(
            {
                **common_case,
                "name": f"stage27i_mixer_event_force_zero_start_center_{float(args.board_internal_center_mhz):.3f}",
                "case_type": "stage27i_mixer_event_force_zero",
                "taxonomy_role": "force_zero_sentinel",
                "sentinel_position": "start",
                "output_mode": "time_spec",
                "diag_control": force_zero,
            }
        )
        for center_mhz in args.centers_mhz:
            center_mhz = float(center_mhz)
            center_fields = {
                "center_mhz": center_mhz,
                "expected_mhz": center_mhz,
                "dac_mhz": center_mhz,
                "output_mode": "time_only",
            }
            cases.append(
                {
                    **common_case,
                    **center_fields,
                    "name": f"stage27i_mixer_event_baseline_center_{center_mhz:.3f}",
                    "case_type": "stage27i_mixer_event_baseline",
                    "taxonomy_role": "center_baseline",
                    "event_sequence_index": 0,
                }
            )
            for repeat_index in (1, 2):
                cases.append(
                    {
                        **common_case,
                        **center_fields,
                        "name": f"stage27i_mixer_event_repeat_{repeat_index}_center_{center_mhz:.3f}",
                        "case_type": "stage27i_mixer_event_repeat",
                        "taxonomy_role": "repeat_apply",
                        "repeat_index": repeat_index,
                        "event_sequence_index": repeat_index,
                    }
                )
            cases.append(
                {
                    **common_case,
                    **center_fields,
                    "name": f"stage27i_mixer_event_sysref_pulse_center_{center_mhz:.3f}",
                    "case_type": "stage27i_mixer_event_sysref",
                    "taxonomy_role": "sysref_pulse",
                    "sysref_action": "pulse_before_capture",
                    "event_sequence_index": 3,
                }
            )
        cases.append(
            {
                **common_case,
                "name": f"stage27i_mixer_event_force_zero_end_center_{float(args.board_internal_center_mhz):.3f}",
                "case_type": "stage27i_mixer_event_force_zero",
                "taxonomy_role": "force_zero_sentinel",
                "sentinel_position": "end",
                "output_mode": "time_spec",
                "diag_control": force_zero,
                "force_download_before_case": True,
            }
        )
    elif bool(args.stage27i_100m_spur_taxonomy_audit):
        diag_off = {
            "adc_force_zero": False,
            "adc_force_hold": False,
            "adc_channel_mask": 0xFF,
            "dac_gate": False,
        }
        force_zero = {
            "adc_force_zero": True,
            "adc_force_hold": False,
            "adc_channel_mask": 0xFF,
            "dac_gate": False,
        }
        common_case = {
            "case_type": "stage27i_100m_taxonomy",
            "physical_state": str(args.physical_state),
            "clock_ref": "external_10mhz",
            "bandwidth_mhz": 100,
            "center_mhz": float(args.board_internal_center_mhz),
            "expected_mhz": float(args.board_internal_center_mhz),
            "dac_mhz": float(args.board_internal_center_mhz),
            "amplitude": 0,
            "enable_mask": 0xFF,
            "target_rf_mhz": float(args.target_rf_mhz),
            "diag_control": diag_off,
        }
        cases.append(
            {
                **common_case,
                "name": f"stage27i_100m_taxonomy_force_zero_start_center_{float(args.board_internal_center_mhz):.3f}",
                "case_type": "stage27i_100m_taxonomy_force_zero",
                "taxonomy_role": "force_zero_sentinel",
                "sentinel_position": "start",
                "output_mode": "time_spec",
                "diag_control": force_zero,
            }
        )
        for sweep_center_mhz in args.centers_mhz:
            cases.append(
                {
                    **common_case,
                    "name": f"stage27i_100m_taxonomy_time_only_center_{float(sweep_center_mhz):.3f}",
                    "case_type": "stage27i_100m_taxonomy_time_sweep",
                    "taxonomy_role": "time_only_center_sweep",
                    "output_mode": "time_only",
                    "center_mhz": float(sweep_center_mhz),
                    "expected_mhz": float(sweep_center_mhz),
                    "dac_mhz": float(sweep_center_mhz),
                }
            )
        for confirm_center_mhz in (80.0, 100.0, 122.88, 140.0):
            cases.append(
                {
                    **common_case,
                    "name": f"stage27i_100m_taxonomy_time_spec_confirm_center_{confirm_center_mhz:.3f}",
                    "case_type": "stage27i_100m_taxonomy_time_spec_confirm",
                    "taxonomy_role": "time_spec_confirm",
                    "output_mode": "time_spec",
                    "center_mhz": float(confirm_center_mhz),
                    "expected_mhz": float(confirm_center_mhz),
                    "dac_mhz": float(confirm_center_mhz),
                    "force_download_before_case": True,
                }
            )
        for repeat_index in range(3):
            cases.append(
                {
                    **common_case,
                    "name": f"stage27i_100m_taxonomy_nco_repeat_{repeat_index}_center_{float(args.board_internal_center_mhz):.3f}",
                    "case_type": "stage27i_100m_taxonomy_nco_repeat",
                    "taxonomy_role": "nco_repeat_apply",
                    "repeat_index": repeat_index,
                    "output_mode": "time_only",
                }
            )
        cases.append(
            {
                **common_case,
                "name": f"stage27i_100m_taxonomy_sysref_baseline_center_{float(args.board_internal_center_mhz):.3f}",
                "case_type": "stage27i_100m_taxonomy_sysref",
                "taxonomy_role": "sysref_baseline",
                "output_mode": "time_only",
                "sysref_action": "none",
            }
        )
        cases.append(
            {
                **common_case,
                "name": f"stage27i_100m_taxonomy_sysref_pulse_center_{float(args.board_internal_center_mhz):.3f}",
                "case_type": "stage27i_100m_taxonomy_sysref",
                "taxonomy_role": "sysref_pulse",
                "output_mode": "time_only",
                "sysref_action": "pulse_before_capture",
            }
        )
        cases.append(
            {
                **common_case,
                "name": f"stage27i_100m_taxonomy_force_zero_end_center_{float(args.board_internal_center_mhz):.3f}",
                "case_type": "stage27i_100m_taxonomy_force_zero",
                "taxonomy_role": "force_zero_sentinel",
                "sentinel_position": "end",
                "output_mode": "time_spec",
                "diag_control": force_zero,
                "force_download_before_case": True,
            }
        )
    elif bool(args.stage27i_rfdc_200m_rootcause_audit):
        center_mhz = float(args.board_internal_center_mhz)
        diag_off = {
            "adc_force_zero": False,
            "adc_force_hold": False,
            "adc_channel_mask": 0xFF,
            "dac_gate": False,
        }
        common_case = {
            "case_type": "stage27i_rfdc_200m_rootcause",
            "physical_state": str(args.physical_state),
            "clock_ref": "external_10mhz",
            "center_mhz": center_mhz,
            "expected_mhz": center_mhz,
            "dac_mhz": center_mhz,
            "amplitude": 0,
            "enable_mask": 0xFF,
            "target_rf_mhz": float(args.target_rf_mhz),
            "diag_control": diag_off,
        }
        for bandwidth, mode in ((100, "spec_only"), (200, "spec_only"), (100, "time_spec"), (200, "time_only")):
            cases.append(
                {
                    **common_case,
                    "name": f"stage27i_rfdc_200m_rootcause_{bandwidth}mhz_{mode}_center_{center_mhz:.3f}",
                    "rootcause_role": "controlled_center_100",
                    "bandwidth_mhz": int(bandwidth),
                    "output_mode": str(mode),
                }
            )
        for sweep_center_mhz in args.centers_mhz:
            if abs(float(sweep_center_mhz) - center_mhz) <= 0.001:
                continue
            for bandwidth in (100, 200):
                cases.append(
                    {
                        **common_case,
                        "name": f"stage27i_rfdc_200m_rootcause_center_{float(sweep_center_mhz):.3f}_{bandwidth}mhz_spec_only",
                        "rootcause_role": "center_sweep",
                        "bandwidth_mhz": int(bandwidth),
                        "output_mode": "spec_only",
                        "center_mhz": float(sweep_center_mhz),
                        "expected_mhz": float(sweep_center_mhz),
                        "dac_mhz": float(sweep_center_mhz),
                    }
                )
    elif bool(args.stage27i_spec_sideband_audit):
        center_mhz = float(args.board_internal_center_mhz)
        common_case = {
            "case_type": "stage27i_spec_sideband",
            "physical_state": str(args.physical_state),
            "clock_ref": "external_10mhz",
            "output_mode": "spec_only",
            "center_mhz": center_mhz,
            "expected_mhz": center_mhz,
            "dac_mhz": center_mhz,
            "amplitude": 0,
            "enable_mask": 0xFF,
            "target_rf_mhz": float(args.target_rf_mhz),
        }
        for bandwidth in (100, 200):
            cases.append(
                {
                    **common_case,
                    "name": f"stage27i_spec_sideband_{bandwidth}mhz_spec_only_center_{center_mhz:.3f}",
                    "bandwidth_mhz": int(bandwidth),
                }
            )
    elif bool(args.stage27i_front_end_audit):
        center_mhz = float(args.board_internal_center_mhz)
        diag_off = {
            "adc_force_zero": False,
            "adc_force_hold": False,
            "adc_channel_mask": 0xFF,
            "dac_gate": False,
        }
        force_zero = {
            "adc_force_zero": True,
            "adc_force_hold": False,
            "adc_channel_mask": 0xFF,
            "dac_gate": False,
        }
        common_case = {
            "physical_state": str(args.physical_state),
            "clock_ref": "external_10mhz",
            "bandwidth_mhz": 100,
            "output_mode": "time_spec",
            "center_mhz": center_mhz,
            "expected_mhz": center_mhz,
            "dac_mhz": center_mhz,
            "amplitude": 0,
            "enable_mask": 0x00,
            "target_rf_mhz": float(args.target_rf_mhz),
        }
        cases.append(
            {
                **common_case,
                "name": f"stage27i_frontend_force_zero_start_center_{center_mhz:.3f}",
                "case_type": "stage27i_frontend_force_zero_sentinel",
                "sentinel_position": "start",
                "diag_control": force_zero,
            }
        )
        cases.append(
            {
                **common_case,
                "name": f"stage27i_frontend_baseline_external_100mhz_time_spec_center_{center_mhz:.3f}",
                "case_type": "stage27i_frontend_baseline",
                "diag_control": diag_off,
            }
        )
        for clock_ref in args.clock_refs:
            cases.append(
                {
                    **common_case,
                    "name": f"stage27i_frontend_clock_{clock_ref}_100mhz_time_spec_center_{center_mhz:.3f}",
                    "case_type": "stage27i_frontend_clock_ref",
                    "clock_ref": str(clock_ref),
                    "diag_control": diag_off,
                }
            )
        for bandwidth, mode in args.front_end_mode_sweep:
            mode_center_mhz = float(args.target_rf_mhz) if int(bandwidth) == 20 else center_mhz
            cases.append(
                {
                    **common_case,
                    "name": f"stage27i_frontend_mode_{int(bandwidth)}mhz_{mode}_center_{mode_center_mhz:.3f}",
                    "case_type": "stage27i_frontend_mode_sweep",
                    "bandwidth_mhz": int(bandwidth),
                    "output_mode": str(mode),
                    "center_mhz": mode_center_mhz,
                    "expected_mhz": mode_center_mhz,
                    "dac_mhz": mode_center_mhz,
                    "diag_control": diag_off,
                }
            )
        for sweep_center_mhz in args.centers_mhz:
            cases.append(
                {
                    **common_case,
                    "name": f"stage27i_frontend_center_{float(sweep_center_mhz):.3f}_100mhz_time_spec",
                    "case_type": "stage27i_frontend_center_sweep",
                    "center_mhz": float(sweep_center_mhz),
                    "expected_mhz": float(sweep_center_mhz),
                    "dac_mhz": float(sweep_center_mhz),
                    "diag_control": diag_off,
                }
            )
        cases.append(
            {
                **common_case,
                "name": f"stage27i_frontend_sysref_pulse_center_{center_mhz:.3f}",
                "case_type": "stage27i_frontend_sysref_pulse",
                "sysref_action": "pulse_before_capture",
                "diag_control": diag_off,
            }
        )
        cases.append(
            {
                **common_case,
                "name": f"stage27i_frontend_force_zero_end_center_{center_mhz:.3f}",
                "case_type": "stage27i_frontend_force_zero_sentinel",
                "sentinel_position": "end",
                "diag_control": force_zero,
            }
        )
    elif bool(args.stage27i_diag_audit):
        center_mhz = float(args.board_internal_center_mhz)
        common_case = {
            "physical_state": str(args.physical_state),
            "clock_ref": "external_10mhz",
            "bandwidth_mhz": 100,
            "output_mode": "time_spec",
            "center_mhz": center_mhz,
            "expected_mhz": center_mhz,
            "dac_mhz": center_mhz,
            "amplitude": 0,
            "enable_mask": 0x00,
            "target_rf_mhz": float(args.target_rf_mhz),
        }
        cases.append(
            {
                **common_case,
                "name": "stage27i_diag_default_off_center_100.000",
                "case_type": "stage27i_diag_default_off",
                "diag_control": {
                    "adc_force_zero": False,
                    "adc_force_hold": False,
                    "adc_channel_mask": 0xFF,
                    "dac_gate": False,
                },
            }
        )
        cases.append(
            {
                **common_case,
                "name": "stage27i_diag_adc_force_zero_center_100.000",
                "case_type": "stage27i_diag_adc_force_zero",
                "diag_control": {
                    "adc_force_zero": True,
                    "adc_force_hold": False,
                    "adc_channel_mask": 0xFF,
                    "dac_gate": False,
                },
            }
        )
        cases.append(
            {
                **common_case,
                "name": "stage27i_diag_adc_force_hold_center_100.000",
                "case_type": "stage27i_diag_adc_force_hold",
                "diag_control": {
                    "adc_force_zero": False,
                    "adc_force_hold": True,
                    "adc_channel_mask": 0xFF,
                    "dac_gate": False,
                },
            }
        )
        cases.append(
            {
                **common_case,
                "name": "stage27i_diag_dac_gate_center_100.000",
                "case_type": "stage27i_diag_dac_gate",
                "diag_control": {
                    "adc_force_zero": False,
                    "adc_force_hold": False,
                    "adc_channel_mask": 0xFF,
                    "dac_gate": True,
                },
            }
        )
        for ch in range(8):
            mask = 1 << ch
            cases.append(
                {
                    **common_case,
                    "name": f"stage27i_diag_ch{ch}_isolate_center_100.000",
                    "case_type": "stage27i_diag_channel_isolate",
                    "diag_channel": ch,
                    "diag_control": {
                        "adc_force_zero": False,
                        "adc_force_hold": False,
                        "adc_channel_mask": mask,
                        "dac_gate": False,
                    },
                }
            )
    elif bool(args.board_internal_audit):
        for clock_ref in args.clock_refs:
            cases.append(
                {
                    "name": f"board_internal_clock_{clock_ref}_100mhz_time_spec_center_{float(args.board_internal_center_mhz):.3f}",
                    "case_type": "board_internal_clock_ref",
                    "physical_state": str(args.physical_state),
                    "clock_ref": str(clock_ref),
                    "bandwidth_mhz": 100,
                    "output_mode": "time_spec",
                    "center_mhz": float(args.board_internal_center_mhz),
                    "expected_mhz": float(args.board_internal_center_mhz),
                    "dac_mhz": float(args.board_internal_center_mhz),
                    "amplitude": 0,
                    "enable_mask": 0x00,
                    "target_rf_mhz": float(args.target_rf_mhz),
                }
            )
        for bandwidth, mode in args.mode_sweep:
            center_mhz = float(args.board_internal_20mhz_center_mhz) if int(bandwidth) == 20 else float(args.board_internal_center_mhz)
            cases.append(
                {
                    "name": f"board_internal_mode_{int(bandwidth)}mhz_{mode}_center_{center_mhz:.3f}",
                    "case_type": "board_internal_mode_sweep",
                    "physical_state": str(args.physical_state),
                    "clock_ref": "external_10mhz",
                    "bandwidth_mhz": int(bandwidth),
                    "output_mode": str(mode),
                    "center_mhz": center_mhz,
                    "expected_mhz": center_mhz,
                    "dac_mhz": center_mhz,
                    "amplitude": 0,
                    "enable_mask": 0x00,
                    "target_rf_mhz": float(args.target_rf_mhz),
                }
            )
    else:
        for center_mhz in args.centers_mhz:
            cases.append(
                {
                    "name": f"zero_amp_enable_ff_center_{center_mhz:.3f}",
                    "case_type": "zero_amp_enable_ff",
                    "physical_state": str(args.physical_state),
                    "clock_ref": "external_10mhz",
                    "bandwidth_mhz": int(args.bandwidth_mhz),
                    "output_mode": "time_spec",
                    "center_mhz": float(center_mhz),
                    "expected_mhz": float(center_mhz),
                    "dac_mhz": float(center_mhz),
                    "amplitude": 0,
                    "enable_mask": 0xFF,
                    "target_rf_mhz": float(args.target_rf_mhz) if bool(args.fixed_rf_audit) else None,
                }
            )
        cases.append(
            {
                "name": f"zero_amp_enable_00_center_{float(args.reference_center_mhz):.3f}",
                "case_type": "zero_amp_enable_00",
                "physical_state": str(args.physical_state),
                "clock_ref": "external_10mhz",
                "bandwidth_mhz": int(args.bandwidth_mhz),
                "output_mode": "time_spec",
                "center_mhz": float(args.reference_center_mhz),
                "expected_mhz": float(args.reference_center_mhz),
                "dac_mhz": float(args.reference_center_mhz),
                "amplitude": 0,
                "enable_mask": 0x00,
                "target_rf_mhz": float(args.target_rf_mhz) if bool(args.fixed_rf_audit) else None,
            }
        )
        if bool(args.fixed_rf_audit):
            for dac_nco_mhz in args.dac_nco_sweep_mhz:
                cases.append(
                    {
                        "name": f"zero_amp_dac_nco_{float(dac_nco_mhz):.6f}_center_{float(args.reference_center_mhz):.3f}",
                        "case_type": "zero_amp_dac_nco_sweep",
                        "physical_state": str(args.physical_state),
                        "clock_ref": "external_10mhz",
                        "bandwidth_mhz": int(args.bandwidth_mhz),
                        "output_mode": "time_spec",
                        "center_mhz": float(args.reference_center_mhz),
                        "expected_mhz": float(dac_nco_mhz),
                        "dac_mhz": float(dac_nco_mhz),
                        "amplitude": 0,
                        "enable_mask": 0xFF,
                        "target_rf_mhz": float(args.target_rf_mhz),
                    }
                )
    if not args.no_reference_case:
        sample_rate_hz = RAW_SAMPLE_RATE_HZ / 2.0 if int(args.bandwidth_mhz) == 100 else RAW_SAMPLE_RATE_HZ
        if int(args.bandwidth_mhz) == 20:
            sample_rate_hz = RAW_SAMPLE_RATE_HZ / 8.0
        aligned_mhz = _nearest_fft_aligned_mhz(float(args.reference_center_mhz), float(args.reference_tone_mhz), sample_rate_hz)
        cases.append(
            {
                "name": f"reference_tone_center_{float(args.reference_center_mhz):.3f}_tone_{aligned_mhz:.6f}",
                "case_type": "reference_tone_on",
                "physical_state": str(args.physical_state),
                "clock_ref": "external_10mhz",
                "bandwidth_mhz": int(args.bandwidth_mhz),
                "output_mode": "time_spec",
                "center_mhz": float(args.reference_center_mhz),
                "expected_mhz": aligned_mhz,
                "dac_mhz": aligned_mhz,
                "requested_reference_tone_mhz": float(args.reference_tone_mhz),
                "amplitude": int(args.reference_amplitude),
                "enable_mask": 0xFF,
                "target_rf_mhz": float(args.target_rf_mhz) if bool(args.fixed_rf_audit) else None,
            }
        )

    results = []
    try:
        for index, case in enumerate(cases):
            download_before_case = (
                not bool(args.no_download)
                and (
                    index == 0
                    or bool(args.download_each_case)
                    or bool(case.get("force_download_before_case", False))
                )
            )
            if download_before_case and index > 0:
                core = T510FEngine(args.bitfile, download=True)
            case["downloaded_before_case"] = bool(download_before_case)
            try:
                initialize_case = index == 0 or bool(download_before_case)
                results.append(_run_case(core, args, case, initialize=initialize_case))
            except Exception as exc:  # noqa: BLE001
                failed = dict(case)
                failed.update(
                    {
                        "error": f"{type(exc).__name__}: {exc}",
                        "traceback": traceback.format_exc(),
                        "valid_for_spur": False,
                        "invalid_for_spur_reason": "CASE_EXCEPTION",
                        "status": _safe_call(core.read_status),
                        "science_status": _safe_call(core.read_science_output_status),
                        "channelizer_status": _safe_call(core.read_channelizer_status),
                        "tx_status": _safe_call(core.read_tx_status),
                        "dac_registers": _safe_call(_read_dac_registers, core),
                    }
                )
                results.append(failed)
    finally:
        if bool(args.restore_dac_off):
            _safe_call(core.configure_dac_tone_bank, freq_hz=0.0, amplitude=0, enable_mask=0x00, mode="constant_phasor")
        if (
            bool(getattr(args, "stage27i_diag_audit", False))
            or bool(getattr(args, "stage27i_front_end_audit", False))
            or bool(getattr(args, "stage27i_rfdc_200m_rootcause_audit", False))
            or bool(getattr(args, "stage27i_100m_spur_taxonomy_audit", False))
            or bool(getattr(args, "stage27i_rfdc_mixer_event_audit", False))
            or bool(getattr(args, "stage27i_rfdc_mixer_sequence_audit", False))
            or bool(getattr(args, "stage27i_raw_lane_witness_audit", False))
            or bool(getattr(args, "stage27i_antialias_acceptance", False))
        ):
            _safe_call(core.disable_stage27i_diag)

    if bool(args.stage27i_antialias_acceptance):
        classification = _classify_stage27i_antialias_acceptance(results, target_rf_mhz=float(args.target_rf_mhz), min_snr_db=float(args.target_snr_db))
    elif bool(args.stage27i_raw_lane_witness_audit):
        classification = _classify_stage27i_raw_lane_witness_audit(results, target_rf_mhz=float(args.target_rf_mhz), min_snr_db=float(args.target_snr_db))
    elif bool(args.stage27i_rfdc_mixer_sequence_audit):
        classification = _classify_stage27i_mixer_sequence_audit(results, target_rf_mhz=float(args.target_rf_mhz), min_snr_db=float(args.target_snr_db))
    elif bool(args.stage27i_rfdc_mixer_event_audit):
        classification = _classify_stage27i_mixer_event_audit(results, target_rf_mhz=float(args.target_rf_mhz), min_snr_db=float(args.target_snr_db))
    elif bool(args.stage27i_100m_spur_taxonomy_audit):
        classification = _classify_stage27i_100m_spur_taxonomy(results, target_rf_mhz=float(args.target_rf_mhz), min_snr_db=float(args.target_snr_db))
    elif bool(args.stage27i_rfdc_200m_rootcause_audit):
        classification = _classify_stage27i_rfdc_200m_rootcause(results, target_rf_mhz=float(args.target_rf_mhz), min_snr_db=float(args.target_snr_db))
    elif bool(args.stage27i_spec_sideband_audit):
        classification = _classify_stage27i_spec_sideband(results, target_rf_mhz=float(args.target_rf_mhz), min_snr_db=float(args.target_snr_db))
    elif bool(args.stage27i_front_end_audit):
        classification = _classify_stage27i_front_end(results, target_rf_mhz=float(args.target_rf_mhz), min_snr_db=float(args.target_snr_db))
    elif bool(args.stage27i_diag_audit):
        classification = _classify_stage27i_diag(results, target_rf_mhz=float(args.target_rf_mhz), min_snr_db=float(args.target_snr_db))
    elif bool(args.board_internal_audit):
        classification = _classify_board_internal(results, target_rf_mhz=float(args.target_rf_mhz), min_snr_db=float(args.target_snr_db))
    elif bool(args.fixed_rf_audit):
        classification = _classify_fixed_rf(results, target_rf_mhz=float(args.target_rf_mhz), min_snr_db=float(args.target_snr_db))
    else:
        classification = _classify(results)
    classification_invalid_cases = list(classification.get("invalid_cases", [])) if isinstance(classification, dict) else []
    classification_cases_valid = not classification_invalid_cases
    ok = (
        not errors
        and classification.get("classification") not in (
            "inconclusive",
            "stage27i_frontend_inconclusive",
            "stage27i_spec_sideband_inconclusive",
            "stage27i_rfdc_200m_inconclusive",
            "stage27i_100m_spur_taxonomy_inconclusive",
            "stage27i_mixer_event_inconclusive",
            "stage27i_mixer_sequence_inconclusive",
            "raw_lane_witness_inconclusive",
            "stage27i_100m_antialias_acceptance_fail",
        )
        and (not bool(args.stage27i_front_end_audit) or classification_cases_valid)
        and (not bool(args.stage27i_100m_spur_taxonomy_audit) or classification_cases_valid)
        and (not bool(args.stage27i_rfdc_mixer_event_audit) or classification_cases_valid)
        and (not bool(args.stage27i_rfdc_mixer_sequence_audit) or classification_cases_valid)
        and (not bool(args.stage27i_raw_lane_witness_audit) or classification_cases_valid)
        and (not bool(args.stage27i_antialias_acceptance) or classification_cases_valid)
    )
    result = {
        "stage": "27i" if (
            bool(args.stage27i_diag_audit)
            or bool(args.stage27i_front_end_audit)
            or bool(args.stage27i_spec_sideband_audit)
            or bool(args.stage27i_rfdc_200m_rootcause_audit)
            or bool(args.stage27i_100m_spur_taxonomy_audit)
            or bool(args.stage27i_rfdc_mixer_event_audit)
            or bool(args.stage27i_rfdc_mixer_sequence_audit)
            or bool(args.stage27i_raw_lane_witness_audit)
            or bool(args.stage27i_antialias_acceptance)
        ) else "27h",
        "production_stage": "27h",
        "expected_core_version": f"0x{int(args.expected_core_version):08x}",
        "core_version": f"0x{int(initial_status.get('core_version', 0)):08x}",
        "ok": ok,
        "classification": classification,
        "classification_cases_valid": classification_cases_valid,
        "purpose": "Separate Rust Web display correctness from real RFDC raw preview, production TIME waveform, and FFT-only SPEC spur sources.",
        "allowed_spur_classifications": list(ALLOWED_STAGE27I_SPUR_CLASSIFICATIONS),
        "fixed_rf_audit": bool(args.fixed_rf_audit),
        "board_internal_audit": bool(args.board_internal_audit),
        "stage27i_diag_audit": bool(args.stage27i_diag_audit),
        "stage27i_front_end_audit": bool(args.stage27i_front_end_audit),
        "stage27i_spec_sideband_audit": bool(args.stage27i_spec_sideband_audit),
        "stage27i_rfdc_200m_rootcause_audit": bool(args.stage27i_rfdc_200m_rootcause_audit),
        "stage27i_100m_spur_taxonomy_audit": bool(args.stage27i_100m_spur_taxonomy_audit),
        "stage27i_rfdc_mixer_event_audit": bool(args.stage27i_rfdc_mixer_event_audit),
        "stage27i_rfdc_mixer_sequence_audit": bool(args.stage27i_rfdc_mixer_sequence_audit),
        "stage27i_raw_lane_witness_audit": bool(args.stage27i_raw_lane_witness_audit),
        "stage27i_antialias_acceptance": bool(args.stage27i_antialias_acceptance),
        "physical_state": str(args.physical_state),
        "sync_mode": str(args.sync_mode),
        "clock_refs": list(args.clock_refs),
        "mode_sweep": [{"bandwidth_mhz": int(bw), "output_mode": mode} for bw, mode in args.mode_sweep],
        "front_end_mode_sweep": [{"bandwidth_mhz": int(bw), "output_mode": mode} for bw, mode in args.front_end_mode_sweep],
        "target_rf_mhz": float(args.target_rf_mhz) if bool(args.fixed_rf_audit) else None,
        "target_search_half_width_mhz": float(args.target_search_half_width_mhz) if bool(args.fixed_rf_audit) else None,
        "target_snr_db": float(args.target_snr_db) if bool(args.fixed_rf_audit) else None,
        "rootcause_telemetry_seconds": float(args.rootcause_telemetry_seconds),
        "raw_witness_beats": int(args.raw_witness_beats),
        "raw_witness_sample_rate_hz": float(args.raw_witness_sample_rate_hz),
        "sysref_pulse_width_s": float(args.sysref_pulse_width_s),
        "sysref_pulse_settle_s": float(args.sysref_pulse_settle_s),
        "initial_status": initial_status,
        "cases": results,
        "errors": errors,
    }
    _write_output(args.output, result)
    print(json.dumps(_jsonable(result), indent=2, sort_keys=True))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
