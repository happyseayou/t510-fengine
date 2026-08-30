from __future__ import annotations

from dataclasses import dataclass
import hashlib
from ipaddress import IPv4Address
import math
import os
from pathlib import Path
import struct
import subprocess
import time
import zlib
from typing import Any, Iterable, Mapping, Optional

try:
    from pynq import MMIO, Overlay
except ImportError as exc:  # pragma: no cover - host-side import guard
    MMIO = None  # type: ignore[assignment]
    Overlay = None  # type: ignore[assignment]
    _PYNQ_IMPORT_ERROR = exc
else:
    _PYNQ_IMPORT_ERROR = None


def _ipv4_to_int(value: str | IPv4Address) -> int:
    return int(IPv4Address(value))


def _mac_to_parts(value: str) -> tuple[int, int]:
    cleaned = value.replace(":", "").replace("-", "")
    mac = int(cleaned, 16)
    return mac & 0xFFFF_FFFF, (mac >> 32) & 0xFFFF


def _mac_to_int(value: str) -> int:
    return int(value.replace(":", "").replace("-", ""), 16) & 0xFFFF_FFFF_FFFF


def _normalize_unicast_ipv4(value: str | IPv4Address) -> str:
    address = IPv4Address(value)
    if address.is_unspecified or address.is_multicast or int(address) == 0xFFFF_FFFF:
        raise ValueError("source IP must be a unicast IPv4 address")
    return str(address)


def _normalize_unicast_mac(value: str) -> str:
    cleaned = str(value).strip().lower().replace(":", "").replace("-", "")
    if len(cleaned) != 12:
        raise ValueError("source MAC must contain exactly six octets")
    try:
        mac = int(cleaned, 16)
    except ValueError as exc:
        raise ValueError("source MAC must contain only hexadecimal octets") from exc
    if mac == 0 or (mac >> 40) & 0x01:
        raise ValueError("source MAC must be a non-zero unicast MAC address")
    return ":".join(cleaned[index:index + 2] for index in range(0, 12, 2))


def _mac_from_int(value: int) -> str:
    cleaned = f"{int(value) & 0xFFFF_FFFF_FFFF:012x}"
    return ":".join(cleaned[index:index + 2] for index in range(0, 12, 2))


def _calibration_circular_delta(left: int, right: int, width: int) -> int:
    """Return the shortest LSB distance for a signed fixed-width value.

    RFDC calibration coefficients are two's-complement fields.  A transition
    from the largest positive code to the most negative code is one LSB on the
    calibration accumulator, not a full-scale jump.
    """

    modulus = 1 << int(width)
    difference = abs(int(right) - int(left))
    return min(difference, modulus - difference)


def _nearest_rank_percentile(values: list[int], percentile: float) -> int:
    if not values:
        return 0
    ordered = sorted(int(value) for value in values)
    rank = max(1, int(math.ceil(float(percentile) * len(ordered))))
    return ordered[min(rank - 1, len(ordered) - 1)]


class ObservationSpectrumStabilizer:
    """Stateful display stabilizer for the astronomer observation console."""

    def __init__(
        self,
        *,
        alpha: float = 0.25,
        min_snr_db: float = 10.0,
        peak_jump_mhz: float = 2.0,
        amp_jump_db: float = 6.0,
    ) -> None:
        self.alpha = float(alpha)
        self.min_snr_db = float(min_snr_db)
        self.peak_jump_mhz = float(peak_jump_mhz)
        self.amp_jump_db = float(amp_jump_db)
        self._channels: dict[int, dict[str, Any]] = {}

    def reset(self, channel: Optional[int] = None) -> None:
        if channel is None:
            self._channels.clear()
        else:
            self._channels.pop(int(channel), None)

    @staticmethod
    def _power_from_db(values: Any) -> Any:
        import numpy as np

        return np.power(10.0, np.asarray(values, dtype=np.float64) / 10.0)

    @staticmethod
    def _db_from_power(values: Any) -> Any:
        import numpy as np

        return 10.0 * np.log10(np.maximum(np.asarray(values, dtype=np.float64), 1e-24))

    def update_channel(
        self,
        channel: int,
        spectrum: Mapping[str, Any],
        peak: Mapping[str, Any],
        *,
        smoothing_enabled: bool = True,
        alpha: Optional[float] = None,
    ) -> dict[str, Any]:
        import numpy as np

        channel = int(channel)
        alpha_value = self.alpha if alpha is None else float(alpha)
        alpha_value = min(1.0, max(0.0, alpha_value))
        rf_mhz = np.asarray(spectrum["rf_mhz"], dtype=np.float64)
        raw_dbfs = np.asarray(spectrum["power_dbfs"], dtype=np.float64)
        raw_power = self._power_from_db(raw_dbfs)
        raw_peak_mhz = float(peak.get("rf_peak_mhz", 0.0))
        raw_peak_dbfs = float(peak.get("peak_dbfs", spectrum.get("peak_dbfs", -240.0)))
        raw_rms_dbfs = float(peak.get("rms_dbfs", spectrum.get("rms_dbfs", -240.0)))
        snr_db = float(peak.get("snr_db", 0.0))
        reasons: list[str] = []
        if bool(peak.get("clipped", False)):
            reasons.append("clipped")
        if snr_db < self.min_snr_db:
            reasons.append(f"snr<{self.min_snr_db:.1f}dB")

        previous = self._channels.get(channel)
        same_axis = (
            previous is not None
            and int(previous.get("size", -1)) == int(rf_mhz.size)
            and abs(float(previous.get("x0", 1e30)) - float(rf_mhz[0])) < 1e-9
            and abs(float(previous.get("x1", 1e30)) - float(rf_mhz[-1])) < 1e-9
        )
        if previous is not None and same_axis:
            previous_gate_peak_mhz = float(previous.get("gate_peak_mhz", previous["peak_mhz"]))
            if abs(raw_peak_mhz - previous_gate_peak_mhz) > self.peak_jump_mhz:
                reasons.append(f"peak_jump>{self.peak_jump_mhz:.1f}MHz")
            if abs(raw_peak_dbfs - float(previous["raw_peak_dbfs"])) > self.amp_jump_db:
                reasons.append(f"amp_jump>{self.amp_jump_db:.1f}dB")
            if abs(raw_rms_dbfs - float(previous["raw_rms_dbfs"])) > self.amp_jump_db:
                reasons.append(f"rms_jump>{self.amp_jump_db:.1f}dB")

        valid = not reasons
        if valid:
            if smoothing_enabled and previous is not None and same_axis:
                smooth_power = alpha_value * raw_power + (1.0 - alpha_value) * previous["smooth_power"]
                smooth_rms_power = (
                    alpha_value * float(self._power_from_db(raw_rms_dbfs))
                    + (1.0 - alpha_value) * float(previous["smooth_rms_power"])
                )
            else:
                smooth_power = raw_power
                smooth_rms_power = float(self._power_from_db(raw_rms_dbfs))
            display_dbfs = self._db_from_power(smooth_power)
            display_peak_idx = (
                int(np.argmin(np.abs(rf_mhz - raw_peak_mhz)))
                if smooth_power.size and rf_mhz.size else 0
            )
            display_peak_dbfs = float(display_dbfs[display_peak_idx]) if display_dbfs.size else raw_peak_dbfs
            display_peak_mhz = raw_peak_mhz
            display_rms_dbfs = float(self._db_from_power(smooth_rms_power))
            self._channels[channel] = {
                "size": int(rf_mhz.size),
                "x0": float(rf_mhz[0]) if rf_mhz.size else 0.0,
                "x1": float(rf_mhz[-1]) if rf_mhz.size else 0.0,
                "peak_mhz": display_peak_mhz,
                "gate_peak_mhz": raw_peak_mhz,
                "peak_dbfs": display_peak_dbfs,
                "raw_peak_dbfs": raw_peak_dbfs,
                "raw_rms_dbfs": raw_rms_dbfs,
                "rms_dbfs": display_rms_dbfs,
                "smooth_power": smooth_power,
                "smooth_rms_power": smooth_rms_power,
            }
        elif previous is not None and same_axis:
            smooth_power = previous["smooth_power"]
            display_dbfs = self._db_from_power(smooth_power)
            display_peak_mhz = float(previous["peak_mhz"])
            display_peak_dbfs = float(previous["peak_dbfs"])
            display_rms_dbfs = float(previous["rms_dbfs"])
        else:
            display_dbfs = raw_dbfs
            display_peak_mhz = raw_peak_mhz
            display_peak_dbfs = raw_peak_dbfs
            display_rms_dbfs = raw_rms_dbfs

        return {
            "rf_mhz": rf_mhz,
            "raw_power_dbfs": raw_dbfs,
            "display_power_dbfs": display_dbfs,
            "raw_peak_mhz": raw_peak_mhz,
            "raw_peak_dbfs": raw_peak_dbfs,
            "raw_rms_dbfs": raw_rms_dbfs,
            "display_peak_mhz": display_peak_mhz,
            "display_peak_dbfs": display_peak_dbfs,
            "display_rms_dbfs": display_rms_dbfs,
            "noise_floor_dbfs": float(peak.get("noise_floor_dbfs", spectrum.get("noise_floor_dbfs", -240.0))),
            "snr_db": snr_db,
            "valid_frame": valid,
            "reject_reason": ",".join(reasons),
            "accepted": valid,
        }


@dataclass(frozen=True)
class RegisterMap:
    CORE_VERSION: int = 0x0000
    BOARD_ID: int = 0x0004
    MODE: int = 0x0008
    CONTROL: int = 0x000C
    STATUS: int = 0x0010
    PPS_STATUS: int = 0x0014
    REF_STATUS: int = 0x0018
    ERROR_FLAGS: int = 0x001C
    SYNC_CONFIG: int = 0x0020
    PPS_COUNT_LO: int = 0x0024
    PPS_COUNT_HI: int = 0x0028
    SYSREF_CAPTURE_STATUS: int = 0x002C
    SYSREF_PL_EDGE_COUNT: int = 0x0030
    SYSREF_ADC_EDGE_COUNT: int = 0x0034
    SYSREF_DAC_EDGE_COUNT: int = 0x0038
    SAMPLE_RATE_HZ: int = 0x0108
    QUANT_MODE: int = 0x010C
    SCALE_MODE: int = 0x0110
    TIME_PAYLOAD_NSAMP: int = 0x0114
    SPEC_TIME_COUNT: int = 0x0118
    SPEC_CHAN_COUNT: int = 0x011C
    SRC_IP: int = 0x0200
    DGX_A_IP: int = 0x0204
    DGX_B_IP: int = 0x0208
    TIME_DST_IP: int = 0x020C
    SRC_MAC_LO: int = 0x0210
    SRC_MAC_HI: int = 0x0214
    DGX_A_MAC_LO: int = 0x0218
    DGX_A_MAC_HI: int = 0x021C
    DGX_B_MAC_LO: int = 0x0220
    DGX_B_MAC_HI: int = 0x0224
    SRC_UDP_PORT: int = 0x0228
    DGX_A_UDP_PORT: int = 0x022C
    DGX_B_UDP_PORT: int = 0x0230
    TIME_UDP_PORT: int = 0x0234
    CHAN_SPLIT: int = 0x0238
    SCALE_ID: int = 0x0240
    UNIX_SECONDS_LO: int = 0x0244
    UNIX_SECONDS_HI: int = 0x0248
    MONITOR_SAMPLE_COUNT: int = 0x0300
    SPEC_PACKET_COUNT: int = 0x0304
    SPEC_UDP_BYTE_COUNT: int = 0x0308
    TIME_PACKET_COUNT: int = 0x030C
    TIME_UDP_BYTE_COUNT: int = 0x0310
    TIME_DROPPED_COUNT: int = 0x0314
    SPEC_SEQ_NO: int = 0x0318
    TIME_SEQ_NO: int = 0x031C
    TIME_SAMPLE0_LO: int = 0x0320
    TIME_SAMPLE0_HI: int = 0x0324
    TIME_FRAME_ID_LO: int = 0x0328
    TIME_FRAME_ID_HI: int = 0x032C
    SPEC_FRAME_ID_LO: int = 0x0330
    SPEC_FRAME_ID_HI: int = 0x0334
    SPEC_CHAN0: int = 0x0338
    SPEC_DROPPED_COUNT: int = 0x033C
    RFDC_STATUS_FLAGS: int = 0x0340
    RFDC_SAMPLE_COUNT_LO: int = 0x0344
    RFDC_SAMPLE_COUNT_HI: int = 0x0348
    RFDC_DROPPED_COUNT: int = 0x034C
    RFDC_ACTIVE_MASK: int = 0x0350
    RFDC_CURRENT_VALID_MASK: int = 0x0354
    RFDC_SEEN_VALID_MASK: int = 0x0358
    SCIENCE_DROPPED_BEAT_COUNT: int = 0x035C
    TX_LINK_STATUS_FLAGS: int = 0x0360
    TX_DRY_RUN_PACKET_COUNT: int = 0x0364
    TX_DRY_RUN_BYTE_COUNT: int = 0x0368
    TX_FIFO_LEVEL_WORDS: int = 0x036C
    TX_FIFO_HIGH_WATER_WORDS: int = 0x0370
    TX_FIFO_BACKPRESSURE_CYCLES: int = 0x0374
    DAC_TONE_CONTROL: int = 0x0440
    DAC_TONE_AMPLITUDE: int = 0x0444
    DAC_TONE_PHASE_STEP: int = 0x0448
    DAC_ENABLE_MASK: int = 0x0600
    DAC_BROADCAST_AMPLITUDE: int = 0x0604
    DAC_BROADCAST_PHASE_STEP: int = 0x0608
    DAC_PHASE_EPOCH: int = 0x060C
    DAC_CH_BASE: int = 0x0620
    DAC_CH_STRIDE: int = 0x0018
    PREVIEW_CONTROL: int = 0x0700
    PREVIEW_STATUS: int = 0x0704
    PREVIEW_INPUT_MASK: int = 0x0708
    PREVIEW_CAPTURE_COUNT: int = 0x070C
    PREVIEW_SAMPLE0_LO: int = 0x0710
    PREVIEW_SAMPLE0_HI: int = 0x0714
    PREVIEW_NSAMP: int = 0x0718
    PREVIEW_SAMPLE_RATE_HZ: int = 0x071C
    PREVIEW_AXIS_BEAT_RATE_HZ: int = 0x0720
    PREVIEW_MODE: int = 0x0724
    SCIENCE_CONTROL: int = 0x0D000
    SCIENCE_STATUS: int = 0x0D004
    SCIENCE_SAMPLE_RATE_MODE: int = 0x0D008
    SCIENCE_OUTPUT_MODE: int = 0x0D00C
    SCIENCE_SAMPLE_RATE_HZ: int = 0x0D010
    SCIENCE_DECIM_FACTOR: int = 0x0D014
    SCIENCE_PAYLOAD_RATE_MBPS: int = 0x0D018
    SCIENCE_BLOCK_REASON: int = 0x0D01C
    SCIENCE_CAPABILITY: int = 0x0D020
    SCIENCE_TIME_LIVE_INTERVAL_BEATS: int = 0x0D024
    SCIENCE_TIME_DDR_RING_CONTROL: int = 0x0D028
    SCIENCE_TIME_DDR_RING_BASE_LO: int = 0x0D02C
    SCIENCE_TIME_DDR_RING_BASE_HI: int = 0x0D030
    SCIENCE_TIME_DDR_RING_SLOTS: int = 0x0D034
    SCIENCE_TIME_DDR_RING_STATUS: int = 0x0D038
    SCIENCE_TIME_DDR_RING_OCCUPANCY: int = 0x0D03C
    SCIENCE_TIME_DDR_RING_WRITE_COUNT: int = 0x0D040
    SCIENCE_TIME_DDR_RING_READ_COUNT: int = 0x0D044
    SCIENCE_TIME_DDR_RING_DROP_COUNT: int = 0x0D048
    SCIENCE_TIME_DDR_RING_ERROR_COUNT: int = 0x0D04C
    SCIENCE_TIME_MULTIFLOW_CONTROL: int = 0x0D050
    SCIENCE_ANTIALIAS_STATUS: int = 0x0D054
    SCIENCE_ANTIALIAS_COEFF_VERSION: int = 0x0D058
    PFB_CONTROL: int = 0x0900
    PFB_STATUS: int = 0x0904
    PFB_NCHAN: int = 0x0908
    PFB_TAPS: int = 0x090C
    PFB_FFT_SHIFT: int = 0x0910
    PFB_CHAN0: int = 0x0914
    PFB_CHAN_COUNT: int = 0x0918
    PFB_TIME_COUNT: int = 0x091C
    PFB_FRAME_COUNT: int = 0x0920
    PFB_OVERFLOW_COUNT: int = 0x0924
    PFB_PEAK_CHAN: int = 0x0928
    PFB_PEAK_POWER: int = 0x092C
    PFB_DATA_HALT_COUNT: int = 0x0930
    PFB_XFFT_EVENT_COUNT: int = 0x0934
    PFB_TILE_OVERFLOW_COUNT: int = 0x0938
    PFB_INPUT_FIFO_LEVEL: int = 0x093C
    PFB_XFFT_TLAST_UNEXPECTED_COUNT: int = 0x0940
    PFB_XFFT_TLAST_MISSING_COUNT: int = 0x0944
    PFB_XFFT_FFT_OVERFLOW_COUNT: int = 0x0948
    PFB_XFFT_DATA_OUT_HALT_COUNT: int = 0x094C
    PFB_XFFT_STATUS_HALT_COUNT: int = 0x0950
    PFB_CAPTURE_BACKPRESSURE_COUNT: int = 0x0954
    PFB_FRAME_SAMPLE0_OVERFLOW_COUNT: int = 0x0958
    PFB_COEFF_CONTROL: int = 0x0960
    PFB_COEFF_STATUS: int = 0x0964
    PFB_COEFF_INDEX: int = 0x0968
    PFB_COEFF_DATA: int = 0x096C
    PFB_COEFF_LOADED_COUNT: int = 0x0970
    PFB_COEFF_ID: int = 0x0974
    PFB_COEFF_CRC32: int = 0x0978
    PFB_COEFF_CHECKSUM: int = PFB_COEFF_CRC32
    PFB_COEFF_ERROR_COUNT: int = 0x097C
    SYNC_CAPS: int = 0xAC00
    SYNC_COMMAND: int = 0xAC04
    SYNC_STATUS: int = 0xAC08
    SYNC_ERROR: int = 0xAC0C
    SYNC_GENERATION_LO: int = 0xAC10
    SYNC_TARGET_PPS_LO: int = 0xAC18
    SYNC_EPOCH_TAI_LO: int = 0xAC20
    SYNC_FIRST_SAMPLE0_LO: int = 0xAC28
    SYNC_OBSERVATION_TAG_LO: int = 0xAC30
    SYNC_SIGNAL_CHAIN_TAG: int = 0xAC38
    SYNC_SCHEDULE_TAG: int = 0xAC3C
    SYNC_MTS_RESULT_ID: int = 0xAC40
    SYNC_ACTIVE_GENERATION_LO: int = 0xAC44
    SYNC_ACTUAL_COMMIT_PPS_LO: int = 0xAC4C
    SYNC_ACTUAL_EPOCH_RAW_SAMPLE0_LO: int = 0xAC54
    SYNC_ACTUAL_FIRST_TIME_SAMPLE0_LO: int = 0xAC5C
    SYNC_ACTUAL_FIRST_SPEC_SAMPLE0_LO: int = 0xAC64
    SYNC_CURRENT_PPS_LO: int = 0xAC6C
    TX_CONTROL: int = 0xB000
    TX_STATUS: int = 0xB004
    TX_FRAME_BUILT_COUNT: int = 0xB008
    TX_FRAME_SENT_COUNT: int = 0xB00C
    TX_FRAME_DROPPED_COUNT: int = 0xB010
    TX_FRAME_BYTE_COUNT: int = 0xB014
    TX_ROUTE_MISS_COUNT: int = 0xB018
    TX_ROUTE_ERROR_COUNT: int = 0xB01C
    TX_CMAC_ACCEPTED_PACKET_COUNT: int = 0xB020
    TX_CMAC_ACCEPTED_BYTE_COUNT: int = 0xB024
    TX_SELECTED_ENDPOINT: int = 0xB028
    TX_SELECTED_ROUTE: int = 0xB02C
    TX_ENDPOINT_INDIRECT_INDEX: int = 0xB100
    TX_ENDPOINT_INDIRECT_ENABLE: int = 0xB104
    TX_ENDPOINT_INDIRECT_IP: int = 0xB108
    TX_ENDPOINT_INDIRECT_MAC_LO: int = 0xB10C
    TX_ENDPOINT_INDIRECT_MAC_HI: int = 0xB110
    TX_ENDPOINT_INDIRECT_DST_PORT: int = 0xB114
    TX_ENDPOINT_INDIRECT_SRC_PORT: int = 0xB118
    TX_SPEC_ROUTE_INDIRECT_INDEX: int = 0xB130
    TX_SPEC_ROUTE_INDIRECT_CONTROL: int = 0xB134
    TX_SPEC_ROUTE_INDIRECT_CHAN0: int = 0xB138
    TX_SPEC_ROUTE_INDIRECT_CHAN_COUNT: int = 0xB13C
    TX_SPEC_ROUTE_INDIRECT_HIT_COUNT: int = 0xB140
    TX_TIME_ROUTE_INDIRECT_INDEX: int = 0xB150
    TX_TIME_ROUTE_INDIRECT_CONTROL: int = 0xB154
    TX_TIME_ROUTE_INDIRECT_INPUT_MASK: int = 0xB158
    TX_TIME_ROUTE_INDIRECT_HIT_COUNT: int = 0xB15C
    TX_ENDPOINT_BASE: int = 0x13000
    TX_ENDPOINT_STRIDE: int = 0x0020
    TX_SPEC_ROUTE_BASE: int = 0x14000
    TX_SPEC_ROUTE_STRIDE: int = 0x0020
    TX_TIME_ROUTE_BASE: int = 0x14800
    TX_TIME_ROUTE_STRIDE: int = 0x0020
    QSFP_TEST_INTERVAL_CYCLES: int = 0xB700
    TX_CMAC_SOURCE_STATUS: int = 0xB704
    MONITOR_CLIP_BASE: int = 0x0500
    MONITOR_MEAN_BASE: int = 0x0520
    PREVIEW_BUFFER_BASE: int = 0x2800
    PREVIEW_INPUT_STRIDE: int = 0x1000


class T510Clock:
    """Board-clock control shim for the lab RFDC bring-up path.

    The current PYNQ image does not expose spidev/i2c RF clock devices. This
    class is intentionally small: it makes the requested lab reference explicit
    and leaves the low-level LMK transaction hook in one place instead of
    scattering board pokes through the F-engine API.
    """

    def __init__(self, *, require_low_level: bool = False) -> None:
        self.require_low_level = require_low_level
        self.last_config: dict[str, Any] = {}

    def configure(
        self,
        ref: str,
        *,
        profile: str = "160m_10m_continuous",
    ) -> dict[str, Any]:
        try:
            from .t510_clock import T510ClockController
        except ImportError:
            from t510_clock import T510ClockController

        if profile in ("160m_10m_continuous", "160m_10m_cont_manual_clkin2") and ref == "external_10mhz":
            self.last_config = T510ClockController().configure_external_10mhz_160m_continuous()
        elif profile == "160m_10m_request_manual_clkin2" and ref == "external_10mhz":
            self.last_config = T510ClockController().configure_external_10mhz_160m_request()
        elif profile == "160m_10m_request_manual_clkin0" and ref == "tcxo_10mhz":
            self.last_config = T510ClockController().configure_tcxo_10mhz_160m_request()
        elif ref == "external_10mhz" and (
            profile == "160m_5m_request_manual_clkin2"
            or profile.startswith("160m_10m_request_clkin2_sdclkout3_phase_")
            or profile.startswith("160m_5m_request_clkin2_sdclkout3_phase_")
        ):
            self.last_config = T510ClockController().configure_tics_diagnostic_profile(profile)
        elif profile not in (
            "160m_10m_continuous",
            "160m_10m_cont_manual_clkin2",
            "160m_10m_request_manual_clkin2",
            "160m_10m_request_manual_clkin0",
            "160m_5m_request_manual_clkin2",
        ):
            self.last_config = {
                "ref": ref,
                "profile": profile,
                "configured": False,
                "reason": "unsupported clock profile selected",
            }
        else:
            self.last_config = {
                "ref": ref,
                "profile": profile,
                "configured": False,
                "reason": "clock reference and diagnostic profile do not match",
            }
        if self.require_low_level:
            if not self.last_config.get("configured"):
                raise RuntimeError(f"T510 clock configuration failed: {self.last_config}")
        return self.last_config

    def read_status(self, *, include_registers: bool = False) -> dict[str, Any]:
        try:
            from .t510_clock import T510ClockController
        except ImportError:
            from t510_clock import T510ClockController

        status = T510ClockController().read_status(include_registers=include_registers)
        self.last_config.update(status)
        return status

    def set_sysref(self, enable: bool) -> dict[str, Any]:
        try:
            from .t510_clock import T510ClockController
        except ImportError:
            from t510_clock import T510ClockController

        mode = str(self.last_config.get("sysref_mode", T510ClockController.SYSREF_REQUEST))
        result = T510ClockController().set_sysref(bool(enable), mode=mode)
        self.last_config["sysref_enabled"] = bool(result.get("enabled", enable))
        return result

    def pulse_sysref(self, *, width_s: float = 0.05, settle_s: float = 0.05) -> dict[str, Any]:
        try:
            from .t510_clock import T510ClockController
        except ImportError:
            from t510_clock import T510ClockController

        mode = str(self.last_config.get("sysref_mode", T510ClockController.SYSREF_REQUEST))
        result = T510ClockController().pulse_sysref(
            width_s=width_s,
            settle_s=settle_s,
            mode=mode,
        )
        self.last_config["sysref_enabled"] = False
        return result


class T510FEngine:
    RFDC_CLOCK_RECOVERY_SETTLE_SECONDS = 1.0

    MODES = {
        "spec": 0,
        "time": 1,
        "dual": 2,
        "snapshot": 3,
    }
    SYNC_MODES = {
        "external_pps": 0,
        "software_epoch": 1,
        "free_run": 2,
    }
    CLOCK_REFS = {
        "external_10mhz": 0,
        "tcxo_10mhz": 1,
        "gps_10mhz": 2,
    }
    PRODUCTION_CLOCK_REF = "external_10mhz"
    PRODUCTION_CLOCK_PROFILE = "160m_10m_continuous"
    PRODUCTION_SYNC_MODE = "external_pps"
    RFDC_ADC_ANALOG_SAMPLE_RATE_HZ = 3_840_000_000
    RFDC_DAC_ANALOG_SAMPLE_RATE_HZ = 3_840_000_000
    # API v1 compatibility: fs_analog historically used this shared alias.
    # Stage 34 also reports the ADC and DAC analog rates explicitly.
    RFDC_ANALOG_SAMPLE_RATE_HZ = RFDC_ADC_ANALOG_SAMPLE_RATE_HZ
    RFDC_COMPLEX_SAMPLE_RATE_HZ = 320_000_000
    RFDC_DECIMATION = 12
    RFDC_INTERPOLATION = 12
    ADC_AXIS_RATE_HZ = 80_000_000
    DAC_AXIS_RATE_HZ = 80_000_000
    RF_FIRST_NYQUIST_MIN_HZ = 1_000_000.0
    RF_FIRST_NYQUIST_MAX_HZ = 1_920_000_000.0
    ADC_MTS_TARGET_MARGIN = 20
    DAC_MTS_TARGET_MARGIN = 16
    DAC_MODES = {
        "single_tone": 0,
        "tone": 0,
        "constant_phasor": 1,
        "constant": 1,
        "phasor": 1,
        "stage33_q_advance": 2,
        "stage33_q_retard": 3,
    }
    # Stage 33 direct-SSA measurements select the new compensated mode while
    # mode 0 remains the unchanged accepted DDS contract.  The same bitstream
    # also implements stage33_q_retard so physical direction can be reversed
    # by software alone if the first on-board comparison requires it.
    STAGE34_DAC_TONE_MODE = "stage33_q_advance"
    STAGE33_DAC_TONE_MODE = STAGE34_DAC_TONE_MODE
    SCIENCE_SAMPLE_RATES: dict[int, dict[str, Any]] = {
        160: {"code": 1, "pl_decim": 2, "sample_rate_hz": 160_000_000.0},
        320: {"code": 2, "pl_decim": 1, "sample_rate_hz": 320_000_000.0},
    }
    SCIENCE_SAMPLE_RATE_BY_CODE = {
        int(item["code"]): sample_rate_msps for sample_rate_msps, item in SCIENCE_SAMPLE_RATES.items()
    }
    SCIENCE_OUTPUT_MODES = {
        "off": 0,
        "time_only": 1,
        "time": 1,
        "spec_only": 2,
        "spec": 2,
        "time_spec": 3,
        "dual": 3,
        "time_monitor_spec": 4,
        "monitor": 4,
    }
    SCIENCE_OUTPUT_MODE_NAMES = {
        0: "OFF",
        1: "TIME_ONLY",
        2: "SPEC_ONLY",
        3: "TIME_SPEC",
        4: "TIME_MONITOR_SPEC",
    }
    SCIENCE_BLOCK_REASONS = {
        0: "TIME_SPEC_200M_REJECTED",
        1: "FENGINE_SCIENCE_NOT_READY",
        2: "CMAC_LIVE_BLOCKED_NO_GT_DATAPATH",
        3: "WIDE_512B_TX_PATH_NOT_IMPLEMENTED",
        4: "RFDC_SCIENCE_BUS_TRUNCATED_TO_LOW16",
        5: "CMAC_LINK_NOT_READY",
        6: "FORCED_DRY_RUN",
        7: "FENGINE_SCIENCE_VALID",
        8: "PFB_FFT_NOT_READY",
        9: "FENGINE_OVERFLOW",
        10: "SPEC_ROUTE_INCOMPLETE",
        11: "SCIENCE_RATE_DROPPED",
    }
    TX_ENDPOINT_COUNT = 72
    TX_SPEC_ROUTE_COUNT = 64
    TX_TIME_ROUTE_COUNT = 8
    FENGINE_DEFAULT_FFT_SHIFT: int = 0x5556
    FENGINE_FFT_ONLY_DEFAULT_FFT_SHIFT: int = 0x0556
    PRODUCTION_SCOPE = {
        "data_streams": "TIME native 512b + SPEC/F-engine FENGINE_IQ16 fixed 8-tap RTL PFB 4096-channel science streams",
        "control_preview": "Jupyter notebook 00_t510_fengine_control.ipynb",
        "production_preview": "mode-selective RF reconstructed waveform and/or 4096-bin PFB spectrum",
        "production_modes": (
            "160MS/s TIME_ONLY",
            "160MS/s SPEC_ONLY",
            "160MS/s TIME_SPEC",
            "320MS/s TIME_ONLY",
            "320MS/s SPEC_ONLY",
        ),
        "convergence_gate": "fresh-download board counters plus mode-sized Rust/Web receive at the mode full rate",
        "spec_contract": "4096 channels, 16 blocks x 256 channels x 1 spectrum-time x 8 inputs x IQ16, 8192B payload",
        "pfb_contract": "fixed 8-tap Hamming Q1.17 coefficient bank, stopped/idle commit only",
        "rate_contract": "RFDC 320MS/s complex base path; PL 55-tap half-band decim2 for 160MS/s",
        "fixed_runtime_contract": (
            "external_10mhz + external_pps",
            "default TIME destination UDP 4300..4307",
            "default SPEC destination UDP 4308..4323",
            "board-global source IP/MAC plus per-endpoint source UDP ports",
            "8 logical RFDC inputs",
        ),
        "excluded_from_gate": (
            "320MS/s TIME_SPEC (exceeds the 100GbE capacity)",
            "X-engine/beamformer interfaces",
            "payload or wire-format changes",
        ),
    }

    @staticmethod
    def ensure_xrt_dri_ready() -> dict[str, Any]:
        """Restore the PYNQ zocl DRM links needed by XRT bitstream downloads."""

        def run(cmd: list[str], *, timeout: float = 5.0) -> dict[str, Any]:
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
                return {
                    "cmd": " ".join(cmd),
                    "returncode": int(proc.returncode),
                    "stdout": proc.stdout.strip(),
                    "stderr": proc.stderr.strip(),
                }
            except Exception as exc:  # pragma: no cover - board recovery path
                return {"cmd": " ".join(cmd), "returncode": -1, "stderr": f"{type(exc).__name__}: {exc}"}

        def safe_symlink(target: Path, link: Path) -> None:
            try:
                if link.exists() or link.is_symlink():
                    link.unlink()
                link.symlink_to(target)
            except OSError:
                pass

        status: dict[str, Any] = {
            "euid": int(os.geteuid()) if hasattr(os, "geteuid") else None,
            "xilinx_xrt": os.environ.get("XILINX_XRT", ""),
            "attempted_repair": False,
            "repair_commands": [],
        }

        if not status["xilinx_xrt"]:
            os.environ.setdefault("XILINX_XRT", "/usr")
            status["xilinx_xrt"] = os.environ.get("XILINX_XRT", "")

        if status["euid"] == 0:
            status["attempted_repair"] = True
            helper = Path("/usr/local/sbin/pynq-fix-zocl-dri.sh")
            if helper.exists():
                status["repair_commands"].append(run([str(helper)], timeout=8.0))
            else:
                status["repair_commands"].append(run(["modprobe", "zocl"], timeout=5.0))
                if Path("/dev/dri/card0").exists() or Path("/dev/dri/renderD128").exists():
                    by_path = Path("/dev/dri/by-path")
                    try:
                        by_path.mkdir(parents=True, exist_ok=True)
                    except OSError:
                        pass
                    if Path("/dev/dri/card0").exists():
                        safe_symlink(Path("../card0"), by_path / "platform-axi-zyxclmm_drm-card")
                    if Path("/dev/dri/renderD128").exists():
                        safe_symlink(Path("../renderD128"), by_path / "platform-axi-zyxclmm_drm-render")

        by_path = Path("/dev/dri/by-path")
        status.update(
            {
                "zocl_loaded": Path("/sys/module/zocl").exists(),
                "dri_card0": Path("/dev/dri/card0").exists(),
                "dri_renderD128": Path("/dev/dri/renderD128").exists(),
                "dri_by_path": by_path.exists(),
                "dri_by_path_entries": sorted(p.name for p in by_path.iterdir()) if by_path.exists() else [],
            }
        )
        return status

    def __init__(
        self,
        bitfile: str,
        *,
        ctrl_ip: str = "core_s_axi",
        ctrl_base: int = 0x8004_0000,
        ctrl_range: int = 0x0002_0000,
        download: bool = True,
    ) -> None:
        if Overlay is None:
            raise RuntimeError("PYNQ is required to use T510FEngine") from _PYNQ_IMPORT_ERROR
        if download:
            self.ensure_xrt_dri_ready()
        self.overlay = Overlay(bitfile, download=download)
        self.ctrl = getattr(self.overlay, ctrl_ip, None)
        if self.ctrl is None and ctrl_ip == "core_s_axi":
            self.ctrl = getattr(self.overlay, "feng_ctrl_axi_0", None)
        if self.ctrl is None:
            if MMIO is None:
                raise RuntimeError("PYNQ MMIO is required to access the F-engine control port") from _PYNQ_IMPORT_ERROR
            self.ctrl = MMIO(ctrl_base, ctrl_range)
        self.regs = RegisterMap()
        self.clock = T510Clock()
        self.rfdc_bind_error: Optional[str] = None
        self.rfdc = self._resolve_rfdc_ip()

    def _resolve_rfdc_ip(self) -> Any:
        """Return an xrfdc-backed RFDC object when PYNQ did not auto-bind it."""
        direct = getattr(self.overlay, "usp_rf_data_converter_0", None)
        if direct is not None and hasattr(direct, "adc_tiles") and hasattr(direct, "dac_tiles"):
            return direct

        ip_dict = getattr(self.overlay, "ip_dict", {})
        candidates: list[tuple[str, Any]] = []
        for name, description in ip_dict.items():
            vlnv = str(description.get("type", "")).lower() if isinstance(description, Mapping) else ""
            if "usp_rf_data_converter" in vlnv or "rf_data_converter" in vlnv:
                candidates.append((name, description))
        if not candidates and direct is not None:
            candidates.append(("usp_rf_data_converter_0", getattr(direct, "description", None)))

        try:
            import xrfdc  # type: ignore
        except ImportError as exc:  # pragma: no cover - board-side dependency
            self.rfdc_bind_error = f"xrfdc import failed: {exc}"
            return direct

        bind_errors: list[str] = []
        for name, description in candidates:
            if description is None:
                continue
            try:
                bound = xrfdc.RFdc(description)
            except Exception as exc:  # pragma: no cover - board-side diagnostic path
                bind_errors.append(f"{name}: {exc}")
                continue
            if hasattr(bound, "adc_tiles") and hasattr(bound, "dac_tiles"):
                return bound

        if bind_errors:
            self.rfdc_bind_error = "; ".join(bind_errors)
        return direct

    def reset_all_rfdc_tiles(self) -> list[dict[str, Any]]:
        """Restart all ADC/DAC tiles after an RFDC reference-clock interruption."""
        if self.rfdc is None:
            raise RuntimeError("RFDC handle is unavailable")
        calls: list[dict[str, Any]] = []
        for kind, attribute in (("adc", "adc_tiles"), ("dac", "dac_tiles")):
            for tile_index, tile in enumerate(list(getattr(self.rfdc, attribute, []))):
                method = next(
                    (
                        (name, getattr(tile, name))
                        for name in ("Reset", "reset")
                        if callable(getattr(tile, name, None))
                    ),
                    None,
                )
                if method is None:
                    raise RuntimeError(f"{kind} tile {tile_index} has no Reset API")
                name, function = method
                value = function()
                calls.append(
                    {
                        "kind": kind,
                        "tile": tile_index,
                        "method": name,
                        "result": repr(value),
                    }
                )
        if len(calls) != 8:
            raise RuntimeError(
                f"Stage 34 expected eight RFDC tile reset calls, observed {len(calls)}"
            )
        return calls

    def shutdown_all_rfdc_tiles(self) -> list[dict[str, Any]]:
        """Quiesce every RFDC tile before interrupting its external clock.

        XRFdc_Shutdown preserves the tile register settings while bringing the
        restart state machine to a safe stopped state.  This must happen while
        the old clock is still present; otherwise a subsequent Reset can remain
        stuck waiting for restart state 6 after an LMK reprogramming cycle.
        """
        if self.rfdc is None:
            raise RuntimeError("RFDC handle is unavailable")
        cffi_lib: Any | None = None
        cffi_instance = getattr(self.rfdc, "_instance", None)
        try:
            import xrfdc  # type: ignore

            candidate = getattr(xrfdc, "_lib", None)
            if candidate is not None and hasattr(candidate, "XRFdc_Shutdown"):
                cffi_lib = candidate
        except ImportError:
            pass
        calls: list[dict[str, Any]] = []
        for tile_type, kind, attribute in (
            (0, "adc", "adc_tiles"),
            (1, "dac", "dac_tiles"),
        ):
            for tile_index, tile in enumerate(list(getattr(self.rfdc, attribute, []))):
                method = next(
                    (
                        (name, getattr(tile, name))
                        for name in ("Shutdown", "shutdown")
                        if callable(getattr(tile, name, None))
                    ),
                    None,
                )
                if method is not None:
                    name, function = method
                    value = function()
                    method_name = name
                elif cffi_lib is not None and cffi_instance is not None:
                    status = int(
                        cffi_lib.XRFdc_Shutdown(
                            cffi_instance, int(tile_type), int(tile_index)
                        )
                    )
                    if status != 0:
                        raise RuntimeError(
                            f"XRFdc_Shutdown {kind} tile {tile_index} returned {status}"
                        )
                    value = status
                    method_name = "cffi:XRFdc_Shutdown"
                else:
                    raise RuntimeError(
                        f"{kind} tile {tile_index} has no Shutdown API and the "
                        "libxrfdc CFFI symbol is unavailable"
                    )
                calls.append(
                    {
                        "kind": kind,
                        "tile": tile_index,
                        "method": method_name,
                        "result": repr(value),
                    }
                )
        if len(calls) != 8:
            raise RuntimeError(
                f"Stage 34 expected eight RFDC tile shutdown calls, observed {len(calls)}"
            )
        return calls

    def read_rfdc_tile_power_status(self) -> dict[str, Any]:
        """Return the live RFDC tile restart/power state from ``GetIPStatus``.

        PYNQ exposes the driver's :c:type:`XRFdc_IPStatus` structure as the
        ``IPStatus`` property.  Keep the normalization here so Board Agent and
        campaign code never need to depend on PYNQ's PropertyDict layout.
        """
        if self.rfdc is None:
            raise RuntimeError("RFDC handle is unavailable")
        try:
            raw = getattr(self.rfdc, "IPStatus")
            if callable(raw):
                raw = raw()
            raw = dict(raw)
        except Exception as exc:
            raise RuntimeError(f"XRFdc_GetIPStatus failed: {exc}") from exc

        def normalize(kind: str) -> list[dict[str, Any]]:
            key = "ADCTileStatus" if kind == "adc" else "DACTileStatus"
            values = list(raw.get(key, []))
            if len(values) != 4:
                raise RuntimeError(
                    f"XRFdc_GetIPStatus returned {len(values)} {kind.upper()} tiles, expected 4"
                )
            result: list[dict[str, Any]] = []
            for tile, value in enumerate(values):
                row = dict(value)
                result.append(
                    {
                        "kind": kind,
                        "tile": tile,
                        "is_enabled": bool(int(row.get("IsEnabled", 0))),
                        "tile_state": int(row.get("TileState", 0)),
                        "block_status_mask": int(row.get("BlockStatusMask", 0)) & 0xFF,
                        "power_up_state": int(row.get("PowerUpState", 0)),
                        "pll_state": int(row.get("PLLState", 0)),
                    }
                )
            return result

        adc = normalize("adc")
        dac = normalize("dac")
        return {
            "supported": True,
            "state": int(raw.get("State", 0)),
            "adc_tiles": adc,
            "dac_tiles": dac,
            "adc_enabled_mask": sum(
                (1 << row["tile"]) for row in adc if row["is_enabled"]
            ),
            "dac_enabled_mask": sum(
                (1 << row["tile"]) for row in dac if row["is_enabled"]
            ),
        }

    def shutdown_all_dac_tiles(self) -> dict[str, Any]:
        """Shut down all four DAC tiles with the driver's all-tile selector."""
        if self.rfdc is None:
            raise RuntimeError("RFDC handle is unavailable")
        before = self.read_rfdc_tile_power_status()
        try:
            import xrfdc  # type: ignore

            lib = getattr(xrfdc, "_lib")
            instance = getattr(self.rfdc, "_instance")
            status = int(lib.XRFdc_Shutdown(instance, 1, -1))
        except Exception as exc:
            raise RuntimeError(f"XRFdc_Shutdown(DAC, all tiles) failed: {exc}") from exc
        if status != 0:
            raise RuntimeError(
                f"XRFdc_Shutdown(DAC, all tiles) returned {status}"
            )
        after = self.read_rfdc_tile_power_status()
        if int(after["adc_enabled_mask"]) != 0xF:
            raise RuntimeError(
                f"ADC tiles changed during DAC shutdown: {after['adc_tiles']}"
            )
        if int(after["dac_enabled_mask"]) != 0:
            raise RuntimeError(
                f"DAC tiles did not all shut down: {after['dac_tiles']}"
            )
        return {
            "method": "XRFdc_Shutdown",
            "type": "DAC",
            "tile_id": -1,
            "driver_status": status,
            "before": before,
            "after": after,
        }

    def startup_all_dac_tiles(self) -> dict[str, Any]:
        """Best-effort low-level DAC restart used only by failure recovery."""
        if self.rfdc is None:
            raise RuntimeError("RFDC handle is unavailable")
        before = self.read_rfdc_tile_power_status()
        try:
            import xrfdc  # type: ignore

            lib = getattr(xrfdc, "_lib")
            instance = getattr(self.rfdc, "_instance")
            status = int(lib.XRFdc_StartUp(instance, 1, -1))
        except Exception as exc:
            raise RuntimeError(f"XRFdc_StartUp(DAC, all tiles) failed: {exc}") from exc
        if status != 0:
            raise RuntimeError(f"XRFdc_StartUp(DAC, all tiles) returned {status}")
        return {
            "method": "XRFdc_StartUp",
            "type": "DAC",
            "tile_id": -1,
            "driver_status": status,
            "before": before,
            "after": self.read_rfdc_tile_power_status(),
        }

    def _write64(self, lo_offset: int, value: int) -> None:
        self.ctrl.write(lo_offset, value & 0xFFFF_FFFF)
        self.ctrl.write(lo_offset + 4, (value >> 32) & 0xFFFF_FFFF)

    def _read64(self, lo_offset: int) -> int:
        """Read a live 64-bit counter without accepting a torn rollover."""
        for _ in range(4):
            hi_before = int(self.ctrl.read(lo_offset + 4)) & 0xFFFF_FFFF
            lo = int(self.ctrl.read(lo_offset)) & 0xFFFF_FFFF
            hi_after = int(self.ctrl.read(lo_offset + 4)) & 0xFFFF_FFFF
            if hi_before == hi_after:
                return (hi_after << 32) | lo
        raise RuntimeError(f"unstable 64-bit MMIO read at offset 0x{lo_offset:05x}")

    def _ensure_sync_config_mutable(self) -> None:
        status = int(self.ctrl.read(self.regs.STATUS))
        control = int(self.ctrl.read(self.regs.CONTROL))
        if (status & 0x3) or (control & 0x1):
            raise RuntimeError("SYNC_CONFIG can only be changed while idle; stop/reset the core first")

    def _write_sync_config(self, *, sync_mode: Optional[int] = None, clock_ref: Optional[int] = None) -> None:
        self._ensure_sync_config_mutable()
        value = int(self.ctrl.read(self.regs.SYNC_CONFIG))
        if sync_mode is not None:
            value = (value & ~0x3) | (sync_mode & 0x3)
        if clock_ref is not None:
            value = (value & ~(0x3 << 16)) | ((clock_ref & 0x3) << 16)
        self.ctrl.write(self.regs.SYNC_CONFIG, value)

    def configure_clock(
        self,
        ref: str = "external_10mhz",
        *,
        profile: str = PRODUCTION_CLOCK_PROFILE,
    ) -> dict[str, Any]:
        try:
            clock_ref = self.CLOCK_REFS[ref]
        except KeyError as exc:
            raise ValueError(f"Unsupported reference source: {ref}")
        self.clock_status = self.clock.configure(ref, profile=profile)
        self._write_sync_config(clock_ref=clock_ref)
        self.clock_reference = ref
        return dict(self.clock_status)

    def set_sync_mode(self, mode: str) -> None:
        try:
            sync_mode = self.SYNC_MODES[mode.lower()]
        except KeyError as exc:
            raise ValueError(f"Unsupported sync mode: {mode}") from exc
        self._write_sync_config(sync_mode=sync_mode)
        self.sync_mode = mode.lower()

    def set_adc_active_mask(self, mask: int) -> None:
        if mask <= 0 or mask > 0xFFFF:
            raise ValueError("ADC active mask must be in range 0x0001..0xffff")
        self._ensure_sync_config_mutable()
        self.ctrl.write(self.regs.RFDC_ACTIVE_MASK, mask & 0xFFFF)

    @staticmethod
    def complex_input_mask_to_adc_active_mask(input_mask: int) -> int:
        """Map 8 logical IQ preview/science channels to 16 RFDC ADC ports."""
        logical_mask = int(input_mask)
        if not 0 <= logical_mask <= 0xFF:
            raise ValueError("logical complex input mask must be in range 0x00..0xff")
        physical_mask = 0
        for channel in range(8):
            if logical_mask & (1 << channel):
                physical_mask |= 0x3 << (channel * 2)
        return physical_mask

    @classmethod
    def science_center_bounds_hz(cls, sample_rate_msps: int | float | str) -> tuple[float, float]:
        sample_rate_msps = int(sample_rate_msps)
        if sample_rate_msps not in cls.SCIENCE_SAMPLE_RATES:
            raise ValueError("Stage 34 complex sample-rate setting must be 160 or 320 MS/s")
        half_rate_hz = float(cls.SCIENCE_SAMPLE_RATES[sample_rate_msps]["sample_rate_hz"]) / 2.0
        return half_rate_hz, cls.RF_FIRST_NYQUIST_MAX_HZ - half_rate_hz

    @classmethod
    def validate_observation_frequency_plan(
        cls,
        *,
        center_hz: float,
        bandwidth_hz: float,
        signal_hz: float | None = None,
        signal_name: str = "signal_hz",
    ) -> None:
        center = float(center_hz)
        bandwidth = float(bandwidth_hz)
        if not math.isfinite(bandwidth) or not 0.0 < bandwidth <= cls.RFDC_COMPLEX_SAMPLE_RATE_HZ:
            raise ValueError("bandwidth_hz must be finite and within 0..320 MHz")
        lower = bandwidth / 2.0
        upper = cls.RF_FIRST_NYQUIST_MAX_HZ - lower
        if not math.isfinite(center) or not lower <= center <= upper:
            raise ValueError(
                f"center_hz must be within {lower / 1.0e6:g}..{upper / 1.0e6:g} MHz "
                "so the complete complex band remains in the first Nyquist zone"
            )
        if signal_hz is None:
            return
        signal = float(signal_hz)
        if (
            not math.isfinite(signal)
            or not cls.RF_FIRST_NYQUIST_MIN_HZ <= signal < cls.RF_FIRST_NYQUIST_MAX_HZ
        ):
            raise ValueError(f"{signal_name} must be finite and within 1..1920 MHz (upper bound exclusive)")
        if abs(signal - center) > bandwidth / 2.0:
            raise ValueError(
                f"{signal_name} must remain within center +/- {bandwidth / 2.0 / 1.0e6:g} MHz"
            )

    def configure_rfdc(
        self,
        *,
        rfdc_complex_sample_rate_hz: int,
        f_center: float,
        bandwidth: float,
        decimation: int,
    ) -> None:
        if int(rfdc_complex_sample_rate_hz) != self.RFDC_COMPLEX_SAMPLE_RATE_HZ:
            raise ValueError(
                "Stage 34 RFDC complex sample rate must be 320 MS/s"
            )
        if int(decimation) != self.RFDC_DECIMATION:
            raise ValueError("Stage 34 ADC decimation must be 12")
        self.ctrl.write(self.regs.SAMPLE_RATE_HZ, rfdc_complex_sample_rate_hz)
        self.rfdc_config = {
            "rfdc_complex_sample_rate_hz": rfdc_complex_sample_rate_hz,
            "complex_sample_rate_hz": rfdc_complex_sample_rate_hz,
            "adc_analog_sample_rate_hz": self.RFDC_ADC_ANALOG_SAMPLE_RATE_HZ,
            "dac_analog_sample_rate_hz": self.RFDC_DAC_ANALOG_SAMPLE_RATE_HZ,
            "f_center": f_center,
            "bandwidth": bandwidth,
            "decimation": decimation,
            "adc_decimation": self.RFDC_DECIMATION,
            "dac_interpolation": self.RFDC_INTERPOLATION,
        }
        # The overlay exposes the RFDC IP at 0x8000_0000. On PYNQ images with
        # xrfdc installed, callers can use self.rfdc for the full tile setup.
        if self.rfdc is not None and hasattr(self.rfdc, "adc_tiles"):
            for tile in self.rfdc.adc_tiles:
                _ = tile

    def configure_rfdc_center_frequency(
        self,
        center_freq_hz: float,
        *,
        bandwidth_hz: float = 100_000_000.0,
        require: bool = True,
    ) -> dict[str, Any]:
        """Configure RFDC mixer/NCO center frequency through PYNQ xrfdc.

        The T510 lab RFDC design uses DAC NCO +center and ADC NCO -center for
        the DAC0->ADC0 loopback convention described by the board manual.
        """
        center_freq_hz = float(center_freq_hz)
        bandwidth_hz = float(bandwidth_hz)
        self.validate_observation_frequency_plan(
            center_hz=center_freq_hz,
            bandwidth_hz=bandwidth_hz,
        )
        result = self._configure_rfdc_nco_pair(
            adc_nco_hz=-center_freq_hz,
            dac_nco_hz=center_freq_hz,
            bandwidth_hz=bandwidth_hz,
            require=require,
        )
        self.rfdc_config = {
            "rfdc_complex_sample_rate_hz": self.RFDC_COMPLEX_SAMPLE_RATE_HZ,
            "complex_sample_rate_hz": self.RFDC_COMPLEX_SAMPLE_RATE_HZ,
            "fs_analog": self.RFDC_ANALOG_SAMPLE_RATE_HZ,
            "adc_analog_sample_rate_hz": self.RFDC_ADC_ANALOG_SAMPLE_RATE_HZ,
            "dac_analog_sample_rate_hz": self.RFDC_DAC_ANALOG_SAMPLE_RATE_HZ,
            "f_center": center_freq_hz,
            "bandwidth": bandwidth_hz,
            "decimation": self.RFDC_DECIMATION,
            "adc_decimation": self.RFDC_DECIMATION,
            "dac_interpolation": self.RFDC_INTERPOLATION,
            "nco_configured": result["configured"],
            "nco_results": result["results"],
        }
        result.update(
            {
                "center_freq_hz": center_freq_hz,
                "bandwidth_hz": bandwidth_hz,
            }
        )
        return result

    def _configure_rfdc_nco_pair(
        self,
        *,
        adc_nco_hz: float,
        dac_nco_hz: float,
        bandwidth_hz: float,
        require: bool = True,
    ) -> dict[str, Any]:
        adc_nco_hz = float(adc_nco_hz)
        dac_nco_hz = float(dac_nco_hz)
        bandwidth_hz = float(bandwidth_hz)
        if bandwidth_hz <= 0:
            raise ValueError("bandwidth_hz must be positive")
        if self.rfdc is None:
            if require:
                raise RuntimeError("RFDC NCO configuration requires the xrfdc-backed RFDC IP handle")
            return {"configured": False, "reason": "RFDC IP handle not found"}

        try:
            import xrfdc  # type: ignore
        except ImportError:
            xrfdc = None  # type: ignore[assignment]
        event_mixer = getattr(xrfdc, "EVENT_MIXER", 1) if xrfdc is not None else 1
        results: list[dict[str, Any]] = []
        failures: list[str] = []
        skipped: list[str] = []

        def iter_blocks(tile: Any) -> list[Any]:
            blocks = getattr(tile, "blocks", None)
            if blocks is None:
                return []
            if isinstance(blocks, Mapping):
                return list(blocks.values())
            return list(blocks)

        def configure_blocks(tile_kind: str, tiles: Any, freq_mhz: float) -> None:
            for tile_idx, tile in enumerate(list(tiles)):
                for block_idx, block in enumerate(iter_blocks(tile)):
                    try:
                        settings = dict(getattr(block, "MixerSettings"))
                    except Exception as exc:  # pragma: no cover - inactive RFDC block
                        skipped.append(f"{tile_kind}[{tile_idx}].block[{block_idx}]: {exc}")
                        continue
                    try:
                        settings["Freq"] = float(freq_mhz)
                        block.NyquistZone = 1
                        block.MixerSettings = settings
                        if hasattr(block, "UpdateEvent"):
                            block.UpdateEvent(event_mixer)
                        elif hasattr(block, "update_event"):
                            block.update_event(event_mixer)
                        if hasattr(block, "ResetNCOPhase"):
                            block.ResetNCOPhase()
                        elif hasattr(block, "reset_nco_phase"):
                            block.reset_nco_phase()
                        readback = dict(getattr(block, "MixerSettings", settings))
                        readback_freq_mhz = float(readback.get("Freq", freq_mhz))
                        nyquist_zone = int(getattr(block, "NyquistZone"))
                        if abs(readback_freq_mhz - float(freq_mhz)) > 1.0e-6:
                            raise RuntimeError(
                                f"NCO readback mismatch: requested {freq_mhz} MHz, read {readback_freq_mhz} MHz"
                            )
                        if nyquist_zone != 1:
                            raise RuntimeError(f"NyquistZone readback mismatch: expected 1, read {nyquist_zone}")
                        results.append(
                            {
                                "kind": tile_kind,
                                "tile": tile_idx,
                                "block": block_idx,
                                "requested_freq_mhz": float(freq_mhz),
                                "readback_freq_mhz": readback_freq_mhz,
                                "nyquist_zone": nyquist_zone,
                            }
                        )
                    except Exception as exc:  # pragma: no cover - board-side diagnostic path
                        failures.append(f"{tile_kind}[{tile_idx}].block[{block_idx}]: {exc}")

        adc_tiles = getattr(self.rfdc, "adc_tiles", [])
        dac_tiles = getattr(self.rfdc, "dac_tiles", [])
        configure_blocks("adc", adc_tiles, adc_nco_hz / 1_000_000.0)
        configure_blocks("dac", dac_tiles, dac_nco_hz / 1_000_000.0)
        adc_count = sum(1 for item in results if item["kind"] == "adc")
        dac_count = sum(1 for item in results if item["kind"] == "dac")
        configured = adc_count == 8 and dac_count == 8 and not failures
        if require and not configured:
            bind_note = f" rfdc_bind_error={self.rfdc_bind_error}" if self.rfdc_bind_error else ""
            raise RuntimeError(
                "RFDC NCO configuration failed or was incomplete: "
                f"adc_blocks={adc_count} dac_blocks={dac_count} "
                f"failures={failures} skipped={skipped}{bind_note}"
            )
        return {
            "configured": configured,
            "adc_nco_hz": adc_nco_hz,
            "dac_nco_hz": dac_nco_hz,
            "bandwidth_hz": bandwidth_hz,
            "adc_blocks": adc_count,
            "dac_blocks": dac_count,
            "results": results,
            "failures": failures,
            "skipped": skipped,
        }

    @staticmethod
    def _iter_rfdc_blocks(tile: Any) -> list[Any]:
        blocks = getattr(tile, "blocks", None)
        if blocks is None:
            return []
        if isinstance(blocks, Mapping):
            return list(blocks.values())
        return list(blocks)

    def read_rfdc_contract(self, *, require: bool = False) -> dict[str, Any]:
        expected_factor = {"adc": self.RFDC_DECIMATION, "dac": self.RFDC_INTERPOLATION}
        expected_rate_hz = {
            "adc": self.RFDC_ADC_ANALOG_SAMPLE_RATE_HZ,
            "dac": self.RFDC_DAC_ANALOG_SAMPLE_RATE_HZ,
        }
        result: dict[str, Any] = {
            "expected": {
                "adc_analog_sample_rate_hz": self.RFDC_ADC_ANALOG_SAMPLE_RATE_HZ,
                "dac_analog_sample_rate_hz": self.RFDC_DAC_ANALOG_SAMPLE_RATE_HZ,
                "complex_sample_rate_hz": self.RFDC_COMPLEX_SAMPLE_RATE_HZ,
                "adc_decimation": self.RFDC_DECIMATION,
                "dac_interpolation": self.RFDC_INTERPOLATION,
                "adc_axis_rate_hz": self.ADC_AXIS_RATE_HZ,
                "dac_axis_rate_hz": self.DAC_AXIS_RATE_HZ,
                "nyquist_zone": 1,
            },
            "tiles": [],
            "blocks": [],
            "errors": [],
        }
        if self.rfdc is None:
            result["errors"].append("RFDC IP handle not found")
        else:
            for kind, tiles in (
                ("adc", getattr(self.rfdc, "adc_tiles", [])),
                ("dac", getattr(self.rfdc, "dac_tiles", [])),
            ):
                tile_list = list(tiles)
                if len(tile_list) != 4:
                    result["errors"].append(
                        f"expected 4 {kind.upper()} tiles, read {len(tile_list)}"
                    )
                for tile_idx, tile in enumerate(tile_list):
                    tile_row: dict[str, Any] = {"kind": kind, "tile": tile_idx}
                    try:
                        tile_row["pll_lock_status"] = int(getattr(tile, "PLLLockStatus"))
                        if not tile_row["pll_lock_status"]:
                            result["errors"].append(f"{kind}[{tile_idx}] PLL is not locked")
                    except Exception as exc:
                        result["errors"].append(f"{kind}[{tile_idx}] PLLLockStatus unavailable: {exc}")
                    try:
                        pll_config = dict(getattr(tile, "PLLConfig"))
                        tile_row["pll_config"] = pll_config
                        sample_rate = pll_config.get("SampleRate", pll_config.get("SampleRateHz"))
                        if sample_rate is None:
                            result["errors"].append(
                                f"{kind}[{tile_idx}] PLLConfig has no SampleRate readback"
                            )
                        else:
                            sample_rate_hz = float(sample_rate)
                            if sample_rate_hz < 100.0:
                                sample_rate_hz *= 1.0e9
                            elif sample_rate_hz < 100_000.0:
                                sample_rate_hz *= 1.0e6
                            tile_row["sample_rate_hz"] = sample_rate_hz
                            if abs(sample_rate_hz - expected_rate_hz[kind]) > 1.0:
                                result["errors"].append(
                                    f"{kind}[{tile_idx}] sample rate expected {expected_rate_hz[kind]}, read {sample_rate_hz}"
                                )
                    except Exception as exc:
                        tile_row["pll_config_error"] = str(exc)
                        result["errors"].append(
                            f"{kind}[{tile_idx}] PLLConfig readback unavailable: {exc}"
                        )
                    result["tiles"].append(tile_row)
                    for block_idx, block in enumerate(self._iter_rfdc_blocks(tile)):
                        physical_block_idx = int(getattr(block, "_index", block_idx))
                        try:
                            mixer_settings = dict(getattr(block, "MixerSettings"))
                        except Exception:
                            continue
                        row: dict[str, Any] = {
                            "kind": kind,
                            "tile": tile_idx,
                            "block": physical_block_idx,
                        }
                        try:
                            row["mixer_frequency_mhz"] = float(mixer_settings["Freq"])
                        except (KeyError, TypeError, ValueError) as exc:
                            result["errors"].append(
                                f"{kind}[{tile_idx}].block[{block_idx}] NCO frequency readback failed: {exc}"
                            )
                        factor_name = "DecimationFactor" if kind == "adc" else "InterpolationFactor"
                        try:
                            row["factor"] = int(getattr(block, factor_name))
                            row["nyquist_zone"] = int(getattr(block, "NyquistZone"))
                        except Exception as exc:
                            result["errors"].append(f"{kind}[{tile_idx}].block[{physical_block_idx}] readback failed: {exc}")
                            result["blocks"].append(row)
                            continue
                        if row["factor"] != expected_factor[kind]:
                            result["errors"].append(
                                f"{kind}[{tile_idx}].block[{physical_block_idx}] factor expected {expected_factor[kind]}, read {row['factor']}"
                            )
                        if row["nyquist_zone"] != 1:
                            result["errors"].append(
                                f"{kind}[{tile_idx}].block[{physical_block_idx}] NyquistZone expected 1, read {row['nyquist_zone']}"
                            )
                        result["blocks"].append(row)
        adc_blocks = sum(1 for row in result["blocks"] if row["kind"] == "adc")
        dac_blocks = sum(1 for row in result["blocks"] if row["kind"] == "dac")
        result["active_block_count"] = {"adc": adc_blocks, "dac": dac_blocks}
        if adc_blocks != 8 or dac_blocks != 8:
            result["errors"].append(f"expected 8 ADC and 8 DAC blocks, read ADC={adc_blocks} DAC={dac_blocks}")
        result["ok"] = not result["errors"]
        if require and not result["ok"]:
            raise RuntimeError(f"RFDC_STAGE34_CONTRACT_FAILED: {result['errors']}")
        return result

    @staticmethod
    def _method_names(obj: Any) -> list[str]:
        try:
            return [name for name in dir(obj) if not name.startswith("_")]
        except Exception:
            return []

    def _call_rfdc_api(
        self,
        names: tuple[str, ...],
        arg_options: tuple[tuple[Any, ...], ...],
        *,
        label: str,
        required: bool = True,
    ) -> dict[str, Any]:
        errors: list[str] = []
        if self.rfdc is None:
            raise RuntimeError(f"RFDC_SYSREF_API_UNAVAILABLE: RFDC handle missing for {label}")
        for name in names:
            fn = getattr(self.rfdc, name, None)
            if not callable(fn):
                continue
            for args in arg_options:
                try:
                    value = fn(*args)
                    return {"ok": True, "label": label, "method": name, "args": [repr(arg) for arg in args], "result": repr(value)}
                except TypeError as exc:
                    errors.append(f"{name}{args}: {exc}")
                except Exception as exc:
                    return {"ok": False, "label": label, "method": name, "args": [repr(arg) for arg in args], "error": str(exc)}
        if required:
            available = ",".join(self._method_names(self.rfdc)[:80])
            raise RuntimeError(
                f"RFDC_SYSREF_API_UNAVAILABLE: missing {label}; tried={names}; "
                f"errors={errors}; available={available}"
            )
        return {"ok": False, "label": label, "reason": "method_not_found", "tried": list(names), "errors": errors}

    @staticmethod
    def _xrfdc_const(module: Any, names: tuple[str, ...], default: int) -> int:
        for name in names:
            if module is not None and hasattr(module, name):
                try:
                    return int(getattr(module, name))
                except Exception:
                    pass
        return int(default)

    @staticmethod
    def _mts_config_to_dict(config: Any) -> dict[str, Any]:
        return {
            "ref_tile": int(config.RefTile),
            "tiles": int(config.Tiles),
            "target_latency": int(config.Target_Latency),
            "offset": [int(config.Offset[idx]) for idx in range(4)],
            "latency": [int(config.Latency[idx]) for idx in range(4)],
            "marker_delay": int(config.Marker_Delay),
            "sysref_enable": int(config.SysRef_Enable),
            "dtc_pll_code": [int(config.DTC_Set_PLL.DTC_Code[idx]) for idx in range(4)],
            "dtc_t1_code": [int(config.DTC_Set_T1.DTC_Code[idx]) for idx in range(4)],
        }

    @staticmethod
    def _decode_mts_status(value: int) -> dict[str, Any]:
        """Decode XRFdc MTS status bitfields from xrfdc.h."""
        status = int(value)
        flags = {
            1: "XRFDC_MTS_NOT_SUPPORTED",
            2: "XRFDC_MTS_TIMEOUT",
            4: "XRFDC_MTS_MARKER_RUN",
            8: "XRFDC_MTS_MARKER_MISM",
            16: "XRFDC_MTS_DELAY_OVER",
            32: "XRFDC_MTS_TARGET_LOW",
            64: "XRFDC_MTS_IP_NOT_READY",
            128: "XRFDC_MTS_DTC_INVALID",
            512: "XRFDC_MTS_NOT_ENABLED",
            2048: "XRFDC_MTS_SYSREF_GATE_ERROR",
            4096: "XRFDC_MTS_SYSREF_FREQ_NDONE",
            8192: "XRFDC_MTS_BAD_REF_TILE",
        }
        return {
            "value": status,
            "ok": status == 0,
            "flags": [name for bit, name in flags.items() if status & bit],
            "unknown_bits": status & ~sum(flags),
        }

    @staticmethod
    def _rfdc_tile_mask(tiles: Any, *, fallback: int = 0xF) -> int:
        mask = 0
        try:
            tile_list = list(tiles)
        except Exception:
            return int(fallback)
        for idx, tile in enumerate(tile_list[:4]):
            enabled = getattr(tile, "Enabled", None)
            if enabled is None:
                mask |= 1 << idx
                continue
            try:
                if int(enabled):
                    mask |= 1 << idx
            except Exception:
                if bool(enabled):
                    mask |= 1 << idx
        return mask if mask else int(fallback)

    def _has_direct_mts_api(self) -> bool:
        required = (
            ("MTS_Sysref_Config", "mts_sysref_config", "mts_sysref_configure"),
            ("MultiConverter_Init", "multi_converter_init", "mts_init"),
            ("MultiConverter_Sync", "multi_converter_sync", "mts_sync"),
        )
        if self.rfdc is None:
            return False
        return all(any(callable(getattr(self.rfdc, name, None)) for name in names) for names in required)

    def _ensure_rfdc_mts_cffi(self) -> tuple[Any, Any]:
        try:
            import xrfdc  # type: ignore
        except ImportError as exc:
            raise RuntimeError(f"RFDC_MTS_SHIM_UNAVAILABLE: xrfdc import failed: {exc}") from exc
        ffi = getattr(xrfdc, "_ffi", None)
        lib = getattr(xrfdc, "_lib", None)
        if ffi is None or lib is None:
            raise RuntimeError("RFDC_MTS_SHIM_UNAVAILABLE: xrfdc._ffi/_lib are not available")
        if not getattr(xrfdc, "_t510_mts_cdef_loaded", False):
            ffi.cdef(
                """
                typedef struct {
                    u32 RefTile;
                    u32 IsPLL;
                    int Target[4];
                    int Scan_Mode;
                    int DTC_Code[4];
                    int Num_Windows[4];
                    int Max_Gap[4];
                    int Min_Gap[4];
                    int Max_Overlap[4];
                } XRFdc_MTS_DTC_Settings;
                typedef struct {
                    u32 RefTile;
                    u32 Tiles;
                    int Target_Latency;
                    int Offset[4];
                    int Latency[4];
                    int Marker_Delay;
                    int SysRef_Enable;
                    XRFdc_MTS_DTC_Settings DTC_Set_PLL;
                    XRFdc_MTS_DTC_Settings DTC_Set_T1;
                } XRFdc_MultiConverter_Sync_Config;
                u32 XRFdc_MultiConverter_Sync(XRFdc *InstancePtr, u32 Type, XRFdc_MultiConverter_Sync_Config *ConfigPtr);
                u32 XRFdc_MultiConverter_Init(XRFdc_MultiConverter_Sync_Config *ConfigPtr, int *PLL_CodesPtr, int *T1_CodesPtr, u32 RefTile);
                u32 XRFdc_MTS_Sysref_Config(XRFdc *InstancePtr, XRFdc_MultiConverter_Sync_Config *DACSyncConfigPtr, XRFdc_MultiConverter_Sync_Config *ADCSyncConfigPtr, u32 SysRefEnable);
                u32 XRFdc_GetMTSEnable(XRFdc *InstancePtr, u32 Type, u32 Tile, u32 *EnablePtr);
                """
            )
            setattr(xrfdc, "_t510_mts_cdef_loaded", True)
        missing = [
            name
            for name in (
                "XRFdc_MTS_Sysref_Config",
                "XRFdc_MultiConverter_Init",
                "XRFdc_MultiConverter_Sync",
                "XRFdc_GetMTSEnable",
            )
            if not hasattr(lib, name)
        ]
        if missing:
            raise RuntimeError(f"RFDC_MTS_SHIM_UNAVAILABLE: libxrfdc missing symbols {missing}")
        if getattr(self.rfdc, "_instance", None) is None:
            raise RuntimeError("RFDC_MTS_SHIM_UNAVAILABLE: RFdc object has no _instance pointer")
        return ffi, lib

    def _ensure_rfdc_calibration_cffi(self) -> tuple[Any, Any]:
        """Return the vendor CFFI handles required for ADC calibration control.

        PYNQ 3.0 exposes ``CalFreeze`` as a block property, but using the
        underlying libxrfdc calls here gives us explicit return-code checking
        for an atomic all-eight-channel transaction.  The structures are part
        of PYNQ's generated ``xrfdc_functions.c`` cdef; no private register
        offsets are used.
        """

        if self.rfdc is None:
            raise RuntimeError("RFDC_CALIBRATION_UNAVAILABLE: RFDC handle is unavailable")
        try:
            import xrfdc  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                f"RFDC_CALIBRATION_UNAVAILABLE: xrfdc import failed: {exc}"
            ) from exc
        ffi = getattr(xrfdc, "_ffi", None)
        lib = getattr(xrfdc, "_lib", None)
        if ffi is None or lib is None:
            raise RuntimeError(
                "RFDC_CALIBRATION_UNAVAILABLE: xrfdc._ffi/_lib are not available"
            )
        missing = [
            name
            for name in (
                "XRFdc_SetCalFreeze",
                "XRFdc_GetCalFreeze",
                "XRFdc_GetCalCoefficients",
                "XRFdc_SetCalCoefficients",
                "XRFdc_DisableCoefficientsOverride",
            )
            if not hasattr(lib, name)
        ]
        if missing:
            raise RuntimeError(
                f"RFDC_CALIBRATION_UNAVAILABLE: libxrfdc missing symbols {missing}"
            )
        for type_name in (
            "XRFdc_Cal_Freeze_Settings*",
            "XRFdc_Calibration_Coefficients*",
        ):
            try:
                ffi.typeof(type_name)
            except Exception as exc:
                raise RuntimeError(
                    f"RFDC_CALIBRATION_UNAVAILABLE: xrfdc CFFI lacks {type_name}"
                ) from exc
        if getattr(self.rfdc, "_instance", None) is None:
            raise RuntimeError(
                "RFDC_CALIBRATION_UNAVAILABLE: RFdc object has no _instance pointer"
            )
        return ffi, lib

    def _adc_calibration_blocks(self) -> list[tuple[int, int]]:
        if self.rfdc is None:
            raise RuntimeError("RFDC_CALIBRATION_UNAVAILABLE: RFDC handle is unavailable")
        contract = self.read_rfdc_contract(require=True)
        blocks = sorted(
            (int(row["tile"]), int(row["block"]))
            for row in contract["blocks"]
            if row.get("kind") == "adc"
        )
        if len(blocks) != 8:
            raise RuntimeError(
                "RFDC_CALIBRATION_UNAVAILABLE: Stage 34 requires exactly eight active "
                f"ADC blocks, observed {len(blocks)} ({blocks})"
            )
        return blocks

    @staticmethod
    def _calibration_coefficient_hashes(channels: list[dict[str, Any]]) -> dict[str, str]:
        names = ("ocb1", "ocb2", "gcb", "tscb")
        per_kind = {name: hashlib.sha256() for name in names}
        combined = hashlib.sha256()
        for channel in channels:
            for name in names:
                for value in channel["coefficients"][name]:
                    encoded = struct.pack("<I", int(value) & 0xFFFF_FFFF)
                    per_kind[name].update(encoded)
                    combined.update(encoded)
        return {
            **{name: digest.hexdigest() for name, digest in per_kind.items()},
            "all": combined.hexdigest(),
        }

    @staticmethod
    def _ocb1_diagnostics(raw_coefficients: Iterable[int]) -> dict[str, Any]:
        """Expose the eight signed OCB1 values and their interleave DFT.

        The driver ABI stores each coefficient in a u32 field.  OCB1 is a
        signed 16-bit value in the low half; retaining both forms makes the
        write/readback proof bit-exact while the signed view remains useful to
        humans and correlation analysis.
        """

        raw = [int(value) & 0xFFFF_FFFF for value in raw_coefficients]
        signed = [
            (value & 0xFFFF) - (0x10000 if value & 0x8000 else 0)
            for value in raw
        ]
        if len(signed) != 8:
            raise ValueError(f"OCB1 requires eight coefficients, observed {len(signed)}")
        dft = []
        for k in range(1, 5):
            real = sum(
                value * math.cos(-2.0 * math.pi * k * index / 8.0)
                for index, value in enumerate(signed)
            )
            imag = sum(
                value * math.sin(-2.0 * math.pi * k * index / 8.0)
                for index, value in enumerate(signed)
            )
            dft.append(
                {
                    "k": k,
                    "real": real,
                    "imag": imag,
                    "magnitude": math.hypot(real, imag),
                    "phase_deg": math.degrees(math.atan2(imag, real)),
                }
            )
        return {"raw_u32": raw, "signed16": signed, "dft": dft}

    def read_adc_calibration_status(
        self,
        *,
        require: bool = False,
        _blocks: Optional[list[tuple[int, int]]] = None,
    ) -> dict[str, Any]:
        """Read freeze state and all four calibration coefficient banks.

        Logical ADC numbering is the existing tile-major, active-block-major
        Stage 34 ordering: tile0/block0, tile0/block1, ... tile3/block1.
        """

        try:
            ffi, lib = self._ensure_rfdc_calibration_cffi()
            instance = getattr(self.rfdc, "_instance")
            channels: list[dict[str, Any]] = []
            coefficient_kinds = (("ocb1", 0), ("ocb2", 1), ("gcb", 2), ("tscb", 3))
            frozen_mask = 0
            requested_mask = 0
            software_owned_mask = 0
            blocks = self._adc_calibration_blocks() if _blocks is None else list(_blocks)
            if len(blocks) != 8:
                raise RuntimeError(
                    f"RFDC_CALIBRATION_UNAVAILABLE: expected 8 cached ADC blocks, got {blocks}"
                )
            for logical_adc, (tile, block) in enumerate(blocks):
                freeze = ffi.new("XRFdc_Cal_Freeze_Settings*")
                status = int(lib.XRFdc_GetCalFreeze(instance, tile, block, freeze))
                if status != 0:
                    raise RuntimeError(
                        f"XRFdc_GetCalFreeze adc{logical_adc} tile={tile} block={block} returned {status}"
                    )
                cal_frozen = bool(int(freeze.CalFrozen))
                freeze_requested = bool(int(freeze.FreezeCalibration))
                disable_freeze_pin = bool(int(freeze.DisableFreezePin))
                frozen_mask |= int(cal_frozen) << logical_adc
                requested_mask |= int(freeze_requested) << logical_adc
                software_owned_mask |= int(disable_freeze_pin) << logical_adc
                coefficients: dict[str, list[int]] = {}
                for name, calibration_block in coefficient_kinds:
                    coeff = ffi.new("XRFdc_Calibration_Coefficients*")
                    status = int(
                        lib.XRFdc_GetCalCoefficients(
                            instance, tile, block, calibration_block, coeff
                        )
                    )
                    if status != 0:
                        raise RuntimeError(
                            f"XRFdc_GetCalCoefficients {name} adc{logical_adc} "
                            f"tile={tile} block={block} returned {status}"
                        )
                    coefficients[name] = [
                        int(getattr(coeff, f"Coeff{index}")) & 0xFFFF_FFFF
                        for index in range(8)
                    ]
                channels.append(
                    {
                        "adc": logical_adc,
                        "tile": tile,
                        "block": block,
                        "cal_frozen": cal_frozen,
                        "disable_freeze_pin": disable_freeze_pin,
                        "freeze_calibration": freeze_requested,
                        "coefficients": coefficients,
                        "ocb1_diagnostics": self._ocb1_diagnostics(
                            coefficients["ocb1"]
                        ),
                    }
                )
            return {
                "supported": True,
                "frozen_adc_mask": frozen_mask,
                "requested_freeze_mask": requested_mask,
                "software_owned_mask": software_owned_mask,
                "channels": channels,
                "coefficient_sha256": self._calibration_coefficient_hashes(channels),
            }
        except Exception as exc:
            if require:
                raise
            return {
                "supported": False,
                "frozen_adc_mask": 0,
                "requested_freeze_mask": 0,
                "software_owned_mask": 0,
                "channels": [],
                "coefficient_sha256": {},
                "error": f"{type(exc).__name__}: {exc}",
            }

    def set_adc_ocb1_snapshot_override(self) -> dict[str, Any]:
        """Snapshot all eight OCB1 banks and write the same values back once."""

        ffi, lib = self._ensure_rfdc_calibration_cffi()
        instance = getattr(self.rfdc, "_instance")
        blocks = self._adc_calibration_blocks()
        before = self.read_adc_calibration_status(require=True, _blocks=blocks)
        expected = [
            [int(value) & 0xFFFF_FFFF for value in row["coefficients"]["ocb1"]]
            for row in before["channels"]
        ]
        calls: list[dict[str, int]] = []

        def release_all() -> list[dict[str, int]]:
            releases = []
            for logical_adc, (tile, block) in enumerate(blocks):
                status = int(
                    lib.XRFdc_DisableCoefficientsOverride(instance, tile, block, 0)
                )
                releases.append(
                    {"adc": logical_adc, "tile": tile, "block": block, "status": status}
                )
                if status != 0:
                    raise RuntimeError(
                        "XRFdc_DisableCoefficientsOverride "
                        f"adc{logical_adc} tile={tile} block={block} returned {status}"
                    )
            return releases

        try:
            for logical_adc, (tile, block) in enumerate(blocks):
                coeff = ffi.new("XRFdc_Calibration_Coefficients*")
                for index, value in enumerate(expected[logical_adc]):
                    setattr(coeff, f"Coeff{index}", value)
                status = int(
                    lib.XRFdc_SetCalCoefficients(instance, tile, block, 0, coeff)
                )
                calls.append(
                    {"adc": logical_adc, "tile": tile, "block": block, "status": status}
                )
                if status != 0:
                    raise RuntimeError(
                        f"XRFdc_SetCalCoefficients adc{logical_adc} tile={tile} "
                        f"block={block} returned {status}; calls={calls}"
                    )
            after = self.read_adc_calibration_status(require=True, _blocks=blocks)
            actual = [
                [int(value) & 0xFFFF_FFFF for value in row["coefficients"]["ocb1"]]
                for row in after["channels"]
            ]
            if actual != expected:
                raise RuntimeError(
                    f"RFDC_OCB1_READBACK_MISMATCH: expected={expected} actual={actual}"
                )
            if int(after["frozen_adc_mask"]) != 0:
                raise RuntimeError(
                    "RFDC_OCB1_FREEZE_CONFLICT: GCB/TSCB freeze mask changed while "
                    "installing OCB1 snapshot"
                )
            return {
                "override_adc_mask": 0xFF,
                "calls": calls,
                "snapshot_sha256": before["coefficient_sha256"]["ocb1"],
                "current_sha256": after["coefficient_sha256"]["ocb1"],
                "channels": [
                    {
                        "adc": row["adc"],
                        "tile": row["tile"],
                        "block": row["block"],
                        **row["ocb1_diagnostics"],
                    }
                    for row in after["channels"]
                ],
                "calibration": after,
            }
        except Exception as original:
            rollback_errors: list[str] = []
            try:
                release_all()
            except Exception as rollback:
                rollback_errors.append(f"{type(rollback).__name__}: {rollback}")
            raise RuntimeError(
                f"RFDC_OCB1_ATOMIC_OVERRIDE_FAILED: {original}; "
                f"rollback_errors={rollback_errors}"
            ) from original

    def release_adc_ocb1_override(self) -> dict[str, Any]:
        """Disable the OCB1 override on every active ADC block."""

        ffi, lib = self._ensure_rfdc_calibration_cffi()
        instance = getattr(self.rfdc, "_instance")
        blocks = self._adc_calibration_blocks()
        calls = []
        errors = []
        for logical_adc, (tile, block) in enumerate(blocks):
            try:
                status = int(
                    lib.XRFdc_DisableCoefficientsOverride(instance, tile, block, 0)
                )
            except Exception as exc:
                status = -1
                errors.append(f"adc{logical_adc}:{type(exc).__name__}:{exc}")
            calls.append(
                {"adc": logical_adc, "tile": tile, "block": block, "status": status}
            )
            if status != 0 and not errors:
                errors.append(f"adc{logical_adc}:status={status}")
        if errors:
            raise RuntimeError(f"RFDC_OCB1_RELEASE_FAILED: {errors}; calls={calls}")
        return {
            "override_adc_mask": 0,
            "calls": calls,
            "calibration": self.read_adc_calibration_status(
                require=True, _blocks=blocks
            ),
        }

    def wait_adc_calibration_convergence(
        self,
        *,
        poll_hz: float = 5.0,
        stable_seconds: float = 2.0,
        timeout_seconds: float = 30.0,
        median_delta_lsb: int | None = None,
        p95_delta_lsb: int | None = None,
        max_delta_lsb: int = 32,
    ) -> dict[str, Any]:
        """Wait until GCB/TSCB background adaptation becomes stationary.

        GCB and TSCB remain adaptive until explicitly frozen, so requiring all
        256 sub-coefficients to stop changing is not a physically meaningful
        convergence test.  We instead bound the typical update (median), the
        tail (p95), and any single outlier over a continuous time window.
        """

        poll_hz = float(poll_hz)
        stable_seconds = float(stable_seconds)
        timeout_seconds = float(timeout_seconds)
        max_delta_lsb = int(max_delta_lsb)
        p95_delta_lsb = min(4, max_delta_lsb) if p95_delta_lsb is None else int(p95_delta_lsb)
        median_delta_lsb = (
            min(1, p95_delta_lsb)
            if median_delta_lsb is None
            else int(median_delta_lsb)
        )
        if poll_hz <= 0.0 or stable_seconds <= 0.0 or timeout_seconds <= 0.0:
            raise ValueError("calibration convergence timing values must be positive")
        if min(median_delta_lsb, p95_delta_lsb, max_delta_lsb) < 0:
            raise ValueError("calibration convergence LSB limits must be non-negative")
        if not median_delta_lsb <= p95_delta_lsb <= max_delta_lsb:
            raise ValueError("calibration convergence limits must satisfy median <= p95 <= max")
        blocks = self._adc_calibration_blocks()
        interval = 1.0 / poll_hz
        required_samples = max(2, int(math.ceil(stable_seconds * poll_hz)) + 1)
        deadline = time.monotonic() + timeout_seconds
        previous: list[tuple[int, int]] | None = None
        stable_samples = 0
        trace: list[dict[str, Any]] = []
        started = time.monotonic()
        last_snapshot: dict[str, Any] | None = None
        while True:
            sampled_at = time.monotonic()
            snapshot = self.read_adc_calibration_status(
                require=True,
                _blocks=blocks,
            )
            values: list[tuple[int, int]] = []
            for channel in snapshot["channels"]:
                for name, width in (("gcb", 12), ("tscb", 9)):
                    mask = (1 << width) - 1
                    sign = 1 << (width - 1)
                    for packed in channel["coefficients"][name]:
                        # libxrfdc returns two signed calibration coefficients
                        # packed into the low/high 16-bit halves of each u32
                        # Coeff field.  Comparing the packed u32 directly turns
                        # a one-LSB high-half update into a false 65536-LSB jump.
                        for shift in (0, 16):
                            raw = (int(packed) >> shift) & mask
                            signed = raw - (1 << width) if raw & sign else raw
                            values.append((signed, width))
            deltas = (
                []
                if previous is None
                else [
                    _calibration_circular_delta(left, right, width)
                    for (left, left_width), (right, width) in zip(previous, values)
                    if left_width == width
                ]
            )
            max_delta = max(deltas, default=None)
            median_delta = _nearest_rank_percentile(deltas, 0.50) if deltas else None
            p95_delta = _nearest_rank_percentile(deltas, 0.95) if deltas else None
            stable_update = bool(
                deltas
                and median_delta is not None
                and p95_delta is not None
                and max_delta is not None
                and median_delta <= median_delta_lsb
                and p95_delta <= p95_delta_lsb
                and max_delta <= max_delta_lsb
            )
            if stable_update:
                stable_samples += 1
            else:
                # The current sample is the baseline for the next continuous
                # interval, even when the preceding update was outside limits.
                stable_samples = 1
            trace.append(
                {
                    "elapsed_seconds": sampled_at - started,
                    "median_delta_lsb": median_delta,
                    "p95_delta_lsb": p95_delta,
                    "max_delta_lsb": max_delta,
                    "stable_samples": stable_samples,
                    "gcb_sha256": snapshot["coefficient_sha256"]["gcb"],
                    "tscb_sha256": snapshot["coefficient_sha256"]["tscb"],
                }
            )
            previous = values
            last_snapshot = snapshot
            if stable_samples >= required_samples:
                return {
                    "converged": True,
                    "poll_hz": poll_hz,
                    "stable_seconds": stable_seconds,
                    "required_samples": required_samples,
                    "limits_lsb": {
                        "median": median_delta_lsb,
                        "p95": p95_delta_lsb,
                        "max": max_delta_lsb,
                    },
                    "elapsed_seconds": time.monotonic() - started,
                    "trace": trace,
                    "snapshot": last_snapshot,
                }
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    "RFDC_CALIBRATION_CONVERGENCE_TIMEOUT: GCB/TSCB updates did not "
                    f"remain within median/p95/max={median_delta_lsb}/"
                    f"{p95_delta_lsb}/{max_delta_lsb} LSB for {stable_seconds}s; "
                    f"trace={trace}"
                )
            time.sleep(max(0.0, interval - (time.monotonic() - sampled_at)))
    def set_adc_calibration_freeze(self, freeze: bool) -> dict[str, Any]:
        """Atomically request one freeze state on all eight logical ADCs.

        A failed write or readback triggers a best-effort all-channel unfreeze.
        The original exception is retained together with rollback failures.
        """

        ffi, lib = self._ensure_rfdc_calibration_cffi()
        instance = getattr(self.rfdc, "_instance")
        blocks = self._adc_calibration_blocks()

        def apply(value: bool) -> list[dict[str, int]]:
            calls: list[dict[str, int]] = []
            for logical_adc, (tile, block) in enumerate(blocks):
                settings = ffi.new("XRFdc_Cal_Freeze_Settings*")
                settings.CalFrozen = 0
                settings.DisableFreezePin = 1
                settings.FreezeCalibration = 1 if value else 0
                status = int(
                    lib.XRFdc_SetCalFreeze(instance, tile, block, settings)
                )
                calls.append(
                    {
                        "adc": logical_adc,
                        "tile": tile,
                        "block": block,
                        "status": status,
                    }
                )
                if status != 0:
                    raise RuntimeError(
                        f"XRFdc_SetCalFreeze adc{logical_adc} tile={tile} "
                        f"block={block} returned {status}; calls={calls}"
                    )
            return calls

        try:
            calls = apply(bool(freeze))
            readback = self.read_adc_calibration_status(require=True)
            expected_mask = 0xFF if freeze else 0x00
            if int(readback["frozen_adc_mask"]) != expected_mask:
                raise RuntimeError(
                    "RFDC_CALIBRATION_READBACK_MISMATCH: expected frozen mask "
                    f"0x{expected_mask:02x}, read 0x{int(readback['frozen_adc_mask']):02x}"
                )
            if int(readback["requested_freeze_mask"]) != expected_mask:
                raise RuntimeError(
                    "RFDC_CALIBRATION_READBACK_MISMATCH: expected requested mask "
                    f"0x{expected_mask:02x}, read 0x{int(readback['requested_freeze_mask']):02x}"
                )
            if int(readback["software_owned_mask"]) != 0xFF:
                raise RuntimeError(
                    "RFDC_CALIBRATION_READBACK_MISMATCH: software ownership mask "
                    f"is 0x{int(readback['software_owned_mask']):02x}, expected 0xff"
                )
            return {"requested_freeze": bool(freeze), "calls": calls, **readback}
        except Exception as original:
            rollback_errors: list[str] = []
            try:
                apply(False)
            except Exception as rollback:
                rollback_errors.append(f"{type(rollback).__name__}: {rollback}")
            try:
                rollback_status = self.read_adc_calibration_status(require=True)
                if int(rollback_status["frozen_adc_mask"]) != 0:
                    rollback_errors.append(
                        "rollback readback frozen mask is "
                        f"0x{int(rollback_status['frozen_adc_mask']):02x}"
                    )
            except Exception as rollback:
                rollback_errors.append(f"{type(rollback).__name__}: {rollback}")
            raise RuntimeError(
                f"RFDC_CALIBRATION_ATOMIC_UPDATE_FAILED: {original}; "
                f"rollback_errors={rollback_errors}"
            ) from original

    def _new_mts_config(self, ffi: Any, lib: Any, *, tiles: int, ref_tile: int, target_latency: int) -> tuple[Any, dict[str, Any]]:
        config = ffi.new("XRFdc_MultiConverter_Sync_Config*")
        ret = int(lib.XRFdc_MultiConverter_Init(config, ffi.NULL, ffi.NULL, int(ref_tile)))
        config.Tiles = int(tiles) & 0xF
        config.Target_Latency = int(target_latency)
        initialized = int(config.RefTile) == int(ref_tile) and int(config.Marker_Delay) == 15
        return config, {
            "method": "XRFdc_MultiConverter_Init",
            "result": ret,
            "status": self._decode_mts_status(ret),
            "return_value_reliable": False,
            "initialized": initialized,
            "note": "Some PYNQ/libxrfdc builds expose an init symbol whose return value is undefined; the C demo ignores it. Gate on structure initialization and MultiConverter_Sync instead.",
            "ref_tile": int(ref_tile),
            "tiles": int(config.Tiles),
            "target_latency": int(config.Target_Latency),
            "config": self._mts_config_to_dict(config),
        }

    def _call_rfdc_mts_sysref_config(self, *, enable: bool, label: str, required: bool = True) -> dict[str, Any]:
        if self._has_direct_mts_api():
            return self._call_rfdc_api(
                ("MTS_Sysref_Config", "mts_sysref_config", "mts_sysref_configure"),
                ((1 if enable else 0,), (bool(enable),), (None, None, 1 if enable else 0), (None, None, bool(enable))),
                label=label,
                required=required,
            )
        try:
            ffi, lib = self._ensure_rfdc_mts_cffi()
            configs = getattr(self, "_rfdc_mts_shim_configs", None)
            if configs is None:
                dac_cfg, dac_init = self._new_mts_config(
                    ffi,
                    lib,
                    tiles=self._rfdc_tile_mask(getattr(self.rfdc, "dac_tiles", [])),
                    ref_tile=0,
                    target_latency=-1,
                )
                adc_cfg, adc_init = self._new_mts_config(
                    ffi,
                    lib,
                    tiles=self._rfdc_tile_mask(getattr(self.rfdc, "adc_tiles", [])),
                    ref_tile=0,
                    target_latency=-1,
                )
                self._rfdc_mts_shim_configs = (dac_cfg, adc_cfg)
                init_calls = [dac_init, adc_init]
            else:
                dac_cfg, adc_cfg = configs
                init_calls = []
            ret = int(lib.XRFdc_MTS_Sysref_Config(getattr(self.rfdc, "_instance"), dac_cfg, adc_cfg, 1 if enable else 0))
            call = {
                "ok": ret == 0,
                "label": label,
                "method": "cffi:XRFdc_MTS_Sysref_Config",
                "sysref_enable": 1 if enable else 0,
                "result": ret,
                "status": self._decode_mts_status(ret),
                "init_calls": init_calls,
                "dac_config": self._mts_config_to_dict(dac_cfg),
                "adc_config": self._mts_config_to_dict(adc_cfg),
            }
            if ret and required:
                raise RuntimeError(f"RFDC_SYSREF_LOCK_FAILED: {label} returned {ret}")
            return call
        except Exception as exc:
            if required:
                raise
            return {"ok": False, "label": label, "method": "cffi:XRFdc_MTS_Sysref_Config", "error": str(exc)}

    def _read_mts_enable_cffi(self) -> list[dict[str, Any]]:
        try:
            ffi, lib = self._ensure_rfdc_mts_cffi()
        except Exception as exc:
            return [{"error": str(exc)}]
        rows: list[dict[str, Any]] = []
        try:
            import xrfdc  # type: ignore
        except ImportError:
            xrfdc = None  # type: ignore[assignment]
        adc_tile = self._xrfdc_const(xrfdc, ("ADC_TILE", "XRFDC_ADC_TILE"), 0)
        dac_tile = self._xrfdc_const(xrfdc, ("DAC_TILE", "XRFDC_DAC_TILE"), 1)
        for kind, tile_type in (("adc", adc_tile), ("dac", dac_tile)):
            for tile in range(4):
                value = ffi.new("u32*")
                try:
                    ret = int(lib.XRFdc_GetMTSEnable(getattr(self.rfdc, "_instance"), int(tile_type), int(tile), value))
                    rows.append({"kind": kind, "tile": tile, "result": ret, "enable": int(value[0]) if ret == 0 else None})
                except Exception as exc:
                    rows.append({"kind": kind, "tile": tile, "error": str(exc)})
        return rows

    def _configure_rfdc_mixer_blocks_sysref(
        self,
        *,
        adc_nco_hz: float,
        dac_nco_hz: float,
        require: bool,
        rfdc_mixer_sequence: str = "sysref_reset_before_pulse",
    ) -> dict[str, Any]:
        try:
            import xrfdc  # type: ignore
        except ImportError:
            xrfdc = None  # type: ignore[assignment]
        event_sysref = self._xrfdc_const(xrfdc, ("EVNT_SRC_SYSREF", "XRFDC_EVNT_SRC_SYSREF"), 2)
        # Keep the immediate-event value in the status payload for API
        # compatibility even though the Stage 33 production sequences use
        # SYSREF, SLICE, or TILE events only.
        event_immediate = self._xrfdc_const(xrfdc, ("EVNT_SRC_IMMEDIATE", "XRFDC_EVNT_SRC_IMMEDIATE"), 0)
        event_slice = self._xrfdc_const(xrfdc, ("EVNT_SRC_SLICE", "XRFDC_EVNT_SRC_SLICE"), 1)
        event_tile = self._xrfdc_const(xrfdc, ("EVNT_SRC_TILE", "XRFDC_EVNT_SRC_TILE"), 2)
        event_mixer = self._xrfdc_const(xrfdc, ("EVENT_MIXER", "XRFDC_EVENT_MIXER"), 1)
        mixer_type_fine = self._xrfdc_const(xrfdc, ("MIXER_TYPE_FINE", "XRFDC_MIXER_TYPE_FINE"), 2)
        mode_r2c = self._xrfdc_const(xrfdc, ("MIXER_MODE_R2C", "XRFDC_MIXER_MODE_R2C"), 1)
        mode_c2r = self._xrfdc_const(xrfdc, ("MIXER_MODE_C2R", "XRFDC_MIXER_MODE_C2R"), 2)
        sequence = str(rfdc_mixer_sequence).strip().lower().replace("-", "_")
        allowed_sequences = {
            "sysref_reset_before_pulse",
            "sysref_no_reset",
            "tile_update_then_reset",
            "tile_reset_then_update",
            "tile_update_no_reset",
            "slice_update_then_reset",
            "slice_reset_then_update",
            "slice_update_no_reset",
        }
        if sequence not in allowed_sequences:
            raise ValueError(f"unsupported rfdc_mixer_sequence {rfdc_mixer_sequence!r}")
        uses_sysref_event = sequence.startswith("sysref_")
        if uses_sysref_event:
            event_source = event_sysref
            event_source_name = "sysref"
        elif sequence.startswith("slice_"):
            event_source = event_slice
            event_source_name = "slice"
        elif sequence.startswith("tile_"):
            event_source = event_tile
            event_source_name = "tile"
        else:
            raise AssertionError(f"unhandled RFDC mixer sequence: {sequence}")
        results: list[dict[str, Any]] = []
        failures: list[str] = []
        skipped: list[str] = []

        def update_block(tile_kind: str, tile_idx: int, block_idx: int, block: Any, freq_mhz: float, mixer_mode: int) -> None:
            try:
                settings = dict(getattr(block, "MixerSettings"))
            except Exception as exc:
                skipped.append(f"{tile_kind}[{tile_idx}].block[{block_idx}]: {exc}")
                return
            try:
                settings["Freq"] = float(freq_mhz)
                if event_source is not None:
                    settings["EventSource"] = event_source
                settings["MixerType"] = mixer_type_fine
                settings["MixerMode"] = mixer_mode
                block.NyquistZone = 1
                block.MixerSettings = settings
                operations: list[dict[str, Any]] = []

                def reset_nco_phase() -> None:
                    if hasattr(block, "ResetNCOPhase"):
                        value = block.ResetNCOPhase()
                    elif hasattr(block, "reset_nco_phase"):
                        value = block.reset_nco_phase()
                    else:
                        raise RuntimeError("ResetNCOPhase API unavailable")
                    operations.append({"op": "ResetNCOPhase", "result": repr(value)})

                def update_event() -> None:
                    if hasattr(block, "UpdateEvent"):
                        value = block.UpdateEvent(event_mixer)
                    elif hasattr(block, "update_event"):
                        value = block.update_event(event_mixer)
                    else:
                        raise RuntimeError("UpdateEvent API unavailable")
                    operations.append({"op": "UpdateEvent", "event": int(event_mixer), "result": repr(value)})

                reset_then_update_sequences = (
                    "tile_reset_then_update",
                    "slice_reset_then_update",
                )
                update_then_reset_sequences = (
                    "tile_update_then_reset",
                    "slice_update_then_reset",
                )
                update_no_reset_sequences = (
                    "tile_update_no_reset",
                    "slice_update_no_reset",
                )
                if sequence == "sysref_reset_before_pulse" or sequence in reset_then_update_sequences:
                    reset_nco_phase()
                if sequence in update_then_reset_sequences or sequence in reset_then_update_sequences or sequence in update_no_reset_sequences:
                    update_event()
                if sequence in update_then_reset_sequences:
                    reset_nco_phase()
                readback = dict(getattr(block, "MixerSettings", settings))
                readback_freq_mhz = float(readback.get("Freq", freq_mhz))
                nyquist_zone = int(getattr(block, "NyquistZone"))
                if abs(readback_freq_mhz - float(freq_mhz)) > 1.0e-6:
                    raise RuntimeError(
                        f"NCO readback mismatch: requested {freq_mhz} MHz, read {readback_freq_mhz} MHz"
                    )
                if nyquist_zone != 1:
                    raise RuntimeError(f"NyquistZone readback mismatch: expected 1, read {nyquist_zone}")
                results.append(
                    {
                        "kind": tile_kind,
                        "tile": tile_idx,
                        "block": block_idx,
                        "requested_freq_mhz": float(freq_mhz),
                        "readback_freq_mhz": readback_freq_mhz,
                        "nyquist_zone": nyquist_zone,
                        "event_source": readback.get("EventSource"),
                        "requested_event_source": int(event_source) if event_source is not None else None,
                        "requested_event_source_name": event_source_name,
                        "mixer_mode": readback.get("MixerMode"),
                        "rfdc_mixer_sequence": sequence,
                        "operations": operations,
                    }
                )
            except Exception as exc:
                failures.append(f"{tile_kind}[{tile_idx}].block[{block_idx}]: {exc}")

        for tile_idx, tile in enumerate(list(getattr(self.rfdc, "adc_tiles", []))):
            for block_idx, block in enumerate(self._iter_rfdc_blocks(tile)):
                update_block("adc", tile_idx, block_idx, block, adc_nco_hz / 1_000_000.0, mode_r2c)
        for tile_idx, tile in enumerate(list(getattr(self.rfdc, "dac_tiles", []))):
            for block_idx, block in enumerate(self._iter_rfdc_blocks(tile)):
                update_block("dac", tile_idx, block_idx, block, dac_nco_hz / 1_000_000.0, mode_c2r)
        adc_count = sum(1 for item in results if item["kind"] == "adc")
        dac_count = sum(1 for item in results if item["kind"] == "dac")
        configured = adc_count > 0 and dac_count > 0 and not failures
        if require and not configured:
            raise RuntimeError(
                "RFDC_SYSREF_LOCK_FAILED: mixer SYSREF configuration incomplete "
                f"adc_blocks={adc_count} dac_blocks={dac_count} failures={failures} skipped={skipped}"
            )
        return {
            "configured": configured,
            "event_mixer": event_mixer,
            "event_sysref": event_sysref,
            "event_immediate": event_immediate,
            "event_slice": event_slice,
            "event_tile": event_tile,
            "event_source": event_source,
            "event_source_name": event_source_name,
            "rfdc_mixer_sequence": sequence,
            "uses_sysref_event": bool(uses_sysref_event),
            "adc_blocks": adc_count,
            "dac_blocks": dac_count,
            "results": results,
            "failures": failures,
            "skipped": skipped,
        }

    def _update_rfdc_mixer_events(self, *, event_mixer: int, driver_update: bool = True) -> list[dict[str, Any]]:
        updates: list[dict[str, Any]] = []
        failures: list[str] = []
        if not driver_update:
            return [
                {
                    "driver_update_skipped": True,
                    "event_mixer": int(event_mixer),
                    "reason": "Mixer EventSource=SYSREF is updated by external SYSREF, not block.UpdateEvent().",
                }
            ]
        for tile_kind, tiles in (("adc", getattr(self.rfdc, "adc_tiles", [])), ("dac", getattr(self.rfdc, "dac_tiles", []))):
            for tile_idx, tile in enumerate(list(tiles)):
                for block_idx, block in enumerate(self._iter_rfdc_blocks(tile)):
                    try:
                        if hasattr(block, "UpdateEvent"):
                            value = block.UpdateEvent(event_mixer)
                        elif hasattr(block, "update_event"):
                            value = block.update_event(event_mixer)
                        else:
                            raise RuntimeError("UpdateEvent API unavailable")
                        updates.append({"kind": tile_kind, "tile": tile_idx, "block": block_idx, "result": repr(value)})
                    except Exception as exc:
                        failures.append(f"{tile_kind}[{tile_idx}].block[{block_idx}]: {exc}")
        if failures:
            raise RuntimeError(f"RFDC_SYSREF_LOCK_FAILED: mixer UpdateEvent failed: {failures}")
        return updates

    def _run_rfdc_mts_sequence(
        self,
        *,
        required: bool = True,
        adc_tiles: int | None = None,
        dac_tiles: int | None = None,
        adc_ref_tile: int = 0,
        dac_ref_tile: int = 0,
        target_latency: int = -1,
        adc_target_latency: int | None = None,
        dac_target_latency: int | None = None,
    ) -> dict[str, Any]:
        if self.rfdc is None:
            raise RuntimeError("RFDC_SYSREF_API_UNAVAILABLE: RFDC handle missing")
        try:
            import xrfdc  # type: ignore
        except ImportError as exc:
            raise RuntimeError(f"RFDC_SYSREF_API_UNAVAILABLE: xrfdc import failed: {exc}") from exc
        adc_tile = self._xrfdc_const(xrfdc, ("ADC_TILE", "XRFDC_ADC_TILE"), 0)
        dac_tile = self._xrfdc_const(xrfdc, ("DAC_TILE", "XRFDC_DAC_TILE"), 1)
        calls: list[dict[str, Any]] = []

        if not self._has_direct_mts_api():
            try:
                ffi, lib = self._ensure_rfdc_mts_cffi()
            except Exception as exc:
                if required:
                    raise RuntimeError(f"RFDC_SYSREF_API_UNAVAILABLE: {exc}") from exc
                return {"available": False, "calls": [], "failures": [str(exc)], "shim": "unavailable"}
            dac_tile_mask = int(dac_tiles) & 0xF if dac_tiles is not None else self._rfdc_tile_mask(getattr(self.rfdc, "dac_tiles", []))
            adc_tile_mask = int(adc_tiles) & 0xF if adc_tiles is not None else self._rfdc_tile_mask(getattr(self.rfdc, "adc_tiles", []))
            effective_adc_target = (
                int(target_latency)
                if adc_target_latency is None
                else int(adc_target_latency)
            )
            effective_dac_target = (
                int(target_latency)
                if dac_target_latency is None
                else int(dac_target_latency)
            )
            dac_cfg, dac_init = self._new_mts_config(
                ffi,
                lib,
                tiles=dac_tile_mask,
                ref_tile=int(dac_ref_tile),
                target_latency=effective_dac_target,
            )
            adc_cfg, adc_init = self._new_mts_config(
                ffi,
                lib,
                tiles=adc_tile_mask,
                ref_tile=int(adc_ref_tile),
                target_latency=effective_adc_target,
            )
            calls.extend(
                [
                    {"label": "dac_mts_init", **dac_init},
                    {"label": "adc_mts_init", **adc_init},
                ]
            )
            if not bool(dac_init.get("initialized")) or not bool(adc_init.get("initialized")):
                failures = [call for call in calls if not bool(call.get("initialized"))]
                if required:
                    raise RuntimeError(f"RFDC_SYSREF_LOCK_FAILED: MTS cffi init structure check failed: {failures}")
                return {"available": True, "shim": "cffi", "calls": calls, "failures": failures}
            self._rfdc_mts_shim_configs = (dac_cfg, adc_cfg)
            try:
                calls.append({"label": "lmk_sysref_on_before_sync", **self.clock.set_sysref(True)})
            except Exception as exc:
                raise RuntimeError(f"RFDC_SYSREF_LOCK_FAILED: enabling LMK SYSREF failed: {exc}") from exc
            time.sleep(0.2)
            for label, tile_type, config in (("dac_mts_sync", dac_tile, dac_cfg), ("adc_mts_sync", adc_tile, adc_cfg)):
                ret = int(lib.XRFdc_MultiConverter_Sync(getattr(self.rfdc, "_instance"), int(tile_type), config))
                call = {
                    "label": label,
                    "method": "cffi:XRFdc_MultiConverter_Sync",
                    "result": ret,
                    "status": self._decode_mts_status(ret),
                    "config": self._mts_config_to_dict(config),
                }
                calls.append(call)
                if ret:
                    try:
                        calls.append({"label": "lmk_sysref_off_after_sync_error", **self.clock.set_sysref(False)})
                    except Exception:
                        pass
                    if required:
                        raise RuntimeError(f"RFDC_SYSREF_LOCK_FAILED: {label} returned {ret}; config={call['config']}")
                    return {"available": True, "shim": "cffi", "calls": calls, "failures": [call]}
            try:
                calls.append({"label": "lmk_sysref_off_after_sync", **self.clock.set_sysref(False)})
            except Exception as exc:
                raise RuntimeError(f"RFDC_SYSREF_LOCK_FAILED: disabling LMK SYSREF failed: {exc}") from exc
            calls.append(self._call_rfdc_mts_sysref_config(enable=False, label="mts_sysref_disable_after_sync", required=required))
            calls.append({"label": "mts_enable_readback", "rows": self._read_mts_enable_cffi()})
            return {
                "available": True,
                "shim": "cffi",
                "calls": calls,
                "adc_tile_type": adc_tile,
                "dac_tile_type": dac_tile,
                "adc_config": self._mts_config_to_dict(adc_cfg),
                "dac_config": self._mts_config_to_dict(dac_cfg),
                "failures": [
                    call
                    for call in calls
                    if (
                        bool(call.get("return_value_reliable", True))
                        and call.get("result", 0) not in (0, None)
                    )
                    or call.get("ok") is False
                    or call.get("initialized") is False
                ],
            }

        def call_or_return_unavailable(names: tuple[str, ...], arg_options: tuple[tuple[Any, ...], ...], *, label: str) -> dict[str, Any]:
            call = self._call_rfdc_api(names, arg_options, label=label, required=required)
            calls.append(call)
            if not call.get("ok", False):
                return {
                    "available": False,
                    "calls": calls,
                    "failures": [f"{label}: {call}"],
                    "adc_tile_type": adc_tile,
                    "dac_tile_type": dac_tile,
                }
            return {}

        unavailable = call_or_return_unavailable(
            ("MTS_Sysref_Config", "mts_sysref_config", "mts_sysref_configure"),
            ((1,), (True,), (None, None, 1), (None, None, True)),
            label="mts_sysref_enable_before_sync",
        )
        if unavailable:
            return unavailable
        try:
            calls.append({"label": "lmk_sysref_on_before_sync", **self.clock.set_sysref(True)})
        except Exception as exc:
            raise RuntimeError(f"RFDC_SYSREF_LOCK_FAILED: enabling LMK SYSREF failed: {exc}") from exc
        time.sleep(0.2)
        for kind, tile_type in (("dac", dac_tile), ("adc", adc_tile)):
            unavailable = call_or_return_unavailable(
                ("MultiConverter_Init", "multi_converter_init", "mts_init"),
                ((tile_type,), (kind,), tuple()),
                label=f"{kind}_mts_init",
            )
            if unavailable:
                return unavailable
            unavailable = call_or_return_unavailable(
                ("MultiConverter_Sync", "multi_converter_sync", "mts_sync"),
                ((tile_type,), (kind,), tuple()),
                label=f"{kind}_mts_sync",
            )
            if unavailable:
                return unavailable
        try:
            calls.append({"label": "lmk_sysref_off_after_sync", **self.clock.set_sysref(False)})
        except Exception as exc:
            raise RuntimeError(f"RFDC_SYSREF_LOCK_FAILED: disabling LMK SYSREF failed: {exc}") from exc
        unavailable = call_or_return_unavailable(
            ("MTS_Sysref_Config", "mts_sysref_config", "mts_sysref_configure"),
            ((0,), (False,), (None, None, 0), (None, None, False)),
            label="mts_sysref_disable_after_sync",
        )
        if unavailable:
            return unavailable
        return {"calls": calls, "adc_tile_type": adc_tile, "dac_tile_type": dac_tile}

    def _configure_rfdc_sysref_locked_pair(
        self,
        *,
        adc_nco_hz: float,
        dac_nco_hz: float,
        bandwidth_hz: float,
        require: bool = True,
        require_mts: bool = True,
        mts_adc_tiles: int | None = None,
        mts_dac_tiles: int | None = None,
        mts_adc_ref_tile: int = 0,
        mts_dac_ref_tile: int = 0,
        mts_adc_target_latency: int = -1,
        mts_dac_target_latency: int = -1,
        rfdc_mixer_sequence: str = "sysref_reset_before_pulse",
    ) -> dict[str, Any]:
        if self.rfdc is None:
            raise RuntimeError("RFDC_SYSREF_API_UNAVAILABLE: RFDC IP handle not found")
        bandwidth_hz = float(bandwidth_hz)
        if bandwidth_hz <= 0:
            raise ValueError("bandwidth_hz must be positive")
        result: dict[str, Any] = {
            "configured": False,
            "adc_nco_hz": float(adc_nco_hz),
            "dac_nco_hz": float(dac_nco_hz),
            "bandwidth_hz": bandwidth_hz,
            "mts": {},
            "mixer": {},
            "event_updates": [],
            "sysref_after": None,
        }
        result["mts"] = self._run_rfdc_mts_sequence(
            required=require_mts,
            adc_tiles=mts_adc_tiles,
            dac_tiles=mts_dac_tiles,
            adc_ref_tile=int(mts_adc_ref_tile),
            dac_ref_tile=int(mts_dac_ref_tile),
            adc_target_latency=int(mts_adc_target_latency),
            dac_target_latency=int(mts_dac_target_latency),
        )
        mixer = self._configure_rfdc_mixer_blocks_sysref(
            adc_nco_hz=float(adc_nco_hz),
            dac_nco_hz=float(dac_nco_hz),
            require=require,
            rfdc_mixer_sequence=str(rfdc_mixer_sequence),
        )
        result["mixer"] = mixer
        mts_available = bool(result["mts"].get("available", True))
        if bool(mixer.get("uses_sysref_event", True)):
            try:
                result["sysref_update_on"] = self.clock.set_sysref(True)
            except Exception as exc:
                raise RuntimeError(f"RFDC_SYSREF_LOCK_FAILED: enabling LMK SYSREF for mixer update failed: {exc}") from exc
            if mts_available:
                result["mts_sysref_enable_for_mixer_update"] = self._call_rfdc_mts_sysref_config(
                    enable=True,
                    label="mts_sysref_enable_for_mixer_update",
                    required=require_mts,
                )
            time.sleep(0.2)
            result["event_updates"] = self._update_rfdc_mixer_events(event_mixer=int(mixer["event_mixer"]), driver_update=False)
            time.sleep(0.1)
            if mts_available:
                result["mts_sysref_disable_after_mixer_update"] = self._call_rfdc_mts_sysref_config(
                    enable=False,
                    label="mts_sysref_disable_after_mixer_update",
                    required=require_mts,
                )
            result["sysref_after"] = self.clock.set_sysref(False)
        else:
            result["sysref_update_on"] = {
                "skipped": True,
                "reason": "rfdc_mixer_sequence uses non-SYSREF EventSource and block.UpdateEvent(EVENT_MIXER)",
                "rfdc_mixer_sequence": mixer.get("rfdc_mixer_sequence"),
                "event_source": mixer.get("event_source"),
                "event_source_name": mixer.get("event_source_name"),
            }
            result["event_updates"] = [
                {
                    "driver_update_in_block_sequence": True,
                    "rfdc_mixer_sequence": mixer.get("rfdc_mixer_sequence"),
                }
            ]
            result["sysref_after"] = self.clock.set_sysref(False)
        result["rfdc_contract"] = self.read_rfdc_contract(require=require)
        result["configured"] = bool(mixer.get("configured")) and bool(result["rfdc_contract"].get("ok"))
        result["mts_available"] = mts_available
        self.rfdc_sync_status = result
        return result

    def read_lmk_status(self, *, include_registers: bool = False) -> dict[str, Any]:
        return self.clock.read_status(include_registers=include_registers)

    @staticmethod
    def _sync_mode_name(value: int) -> str:
        return {0: "external_pps", 1: "software_epoch", 2: "free_run"}.get(int(value), f"unknown_{int(value)}")

    @staticmethod
    def _clock_ref_name(value: int) -> str:
        return {0: "external_10mhz", 1: "tcxo_10mhz", 2: "gps_10mhz"}.get(int(value), f"unknown_{int(value)}")

    def read_external_sync_diagnostics(
        self,
        *,
        interval_s: float = 1.2,
        include_lmk_registers: bool = False,
    ) -> dict[str, Any]:
        """Read simple 10 MHz/PPS health evidence for LEDs and Jupyter."""
        before = self.read_status()
        lmk: dict[str, Any]
        try:
            lmk = self.read_lmk_status(include_registers=include_lmk_registers)
        except Exception as exc:
            lmk = {"configured": False, "errors": [str(exc)]}
        time.sleep(max(float(interval_s), 0.0))
        after = self.read_status()
        pps_delta = self._counter_delta(after.get("pps_count", 0), before.get("pps_count", 0), bits=64)
        selected_ref = str(lmk.get("selected_ref", lmk.get("ref", "")))
        configured_ref = self._clock_ref_name(int(after.get("configured_clock_ref", 0)))
        configured_sync = self._sync_mode_name(int(after.get("configured_sync_mode", 0)))
        lmk_locked = bool(lmk.get("configured", False))
        external_ref_selected = selected_ref == "external_10mhz" or configured_ref == "external_10mhz"
        pps_ok = int(pps_delta) > 0 or bool(after.get("pps_recent", 0))
        ref_ok = lmk_locked and bool(after.get("ref_status_locked", after.get("rfdc_clock_locked", 0)))
        if not external_ref_selected:
            classification = "EXTERNAL_10MHZ_NOT_SELECTED"
        elif not lmk_locked:
            classification = "EXTERNAL_10MHZ_LMK_UNLOCKED"
        elif not pps_ok:
            classification = "PPS_NOT_SEEN_OR_NOT_TOGGLING"
        elif configured_sync != "external_pps":
            classification = "EXTERNAL_SYNC_PRESENT_BUT_NOT_ARMED"
        else:
            classification = "EXTERNAL_10MHZ_PPS_OK"
        return {
            "classification": classification,
            "ok": classification == "EXTERNAL_10MHZ_PPS_OK",
            "configured_clock_ref": configured_ref,
            "configured_sync_mode": configured_sync,
            "external_ref_selected": bool(external_ref_selected),
            "lmk_locked": bool(lmk_locked),
            "ref_ok": bool(ref_ok),
            "pps_ok": bool(pps_ok),
            "pps_count_before": int(before.get("pps_count", 0)),
            "pps_count_after": int(after.get("pps_count", 0)),
            "pps_delta": int(pps_delta),
            "pps_recent": bool(after.get("pps_recent", 0)),
            "pps_input_high": bool(after.get("pps_input_high", 0)),
            "led_semantics": {
                "pl_led0": "RF/LMK-derived data clock chain ready",
                "pl_led1": "PPS edge blink",
                "pl_led2": "PPS seen recently",
                "pl_led3": "sync error: no clock-chain lock or no recent PPS",
            },
            "lmk": lmk,
            "before": before,
            "after": after,
        }

    def wait_for_pps_increment(self, *, timeout: float = 3.0, poll_s: float = 0.05) -> dict[str, Any]:
        start = self.read_status()
        start_count = int(start.get("pps_count", 0))
        deadline = time.monotonic() + float(timeout)
        status = start
        while time.monotonic() < deadline:
            time.sleep(max(float(poll_s), 0.001))
            status = self.read_status()
            if int(status.get("pps_count", 0)) != start_count:
                return {
                    "ok": True,
                    "start_count": start_count,
                    "end_count": int(status.get("pps_count", 0)),
                    "status": status,
                }
        return {
            "ok": False,
            "start_count": start_count,
            "end_count": int(status.get("pps_count", 0)),
            "status": status,
        }

    def read_qsfp_preflight_diagnostics(self) -> dict[str, Any]:
        status = self.read_status()
        tx = self.read_tx_status()
        dry_run = bool(tx.get("udp_dry_run_active", 0) or status.get("tx_udp_dry_run_active", 0))
        link_up = bool(tx.get("qsfp_link_up", 0) or status.get("qsfp_link_up", 0))
        cmac_ready = bool(tx.get("cmac_tx_ready", 0) and tx.get("cmac_reset_done", 0) and tx.get("gt_locked", 0))
        module_present = bool(tx.get("qsfp_module_present", 0) or status.get("tx_qsfp_module_present", 0))
        if dry_run and not link_up and not cmac_ready:
            classification = "CURRENT_BIT_DRY_RUN_NO_CMAC_GT_DATAPATH"
        elif link_up and cmac_ready and not dry_run:
            classification = "QSFP_LINK_READY_FOR_PCAP"
        elif module_present and not cmac_ready:
            classification = "QSFP_MODULE_PRESENT_BUT_CMAC_GT_NOT_READY"
        elif link_up and dry_run:
            classification = "QSFP_LINK_SEEN_BUT_TX_FORCED_DRY_RUN"
        else:
            classification = "QSFP_LINK_NOT_READY"
        return {
            "classification": classification,
            "link_pcap_possible": classification == "QSFP_LINK_READY_FOR_PCAP",
            "science_data_validated": False,
            "module_present": module_present,
            "status": status,
            "tx": tx,
            "default_receivers": [
                {"stream": "spec_low", "ip": "10.0.1.10", "port": 4100},
                {"stream": "spec_high", "ip": "10.0.1.11", "port": 4200},
                {"stream": "time", "ip": "10.0.1.16", "port": 4300},
            ],
            "note": (
                "This overlay still reports dry-run/no live CMAC data path unless "
                "tx_status shows link, GT lock, CMAC reset done and TX ready with dry-run off."
            ),
        }

    @staticmethod
    def _probe_library_symbols(path: str, patterns: tuple[str, ...]) -> dict[str, Any]:
        import subprocess

        result: dict[str, Any] = {"path": path, "exists": False, "symbols": [], "error": None}
        try:
            from pathlib import Path

            if not Path(path).exists():
                return result
            result["exists"] = True
            proc = subprocess.run(["nm", "-D", path], text=True, capture_output=True, timeout=5.0, check=False)
            output = proc.stdout if proc.returncode == 0 else ""
            if not output:
                proc = subprocess.run(["strings", path], text=True, capture_output=True, timeout=5.0, check=False)
                output = proc.stdout
            result["symbols"] = sorted(
                {
                    line.split()[-1]
                    for line in output.splitlines()
                    if any(pattern in line for pattern in patterns)
                }
            )
        except Exception as exc:
            result["error"] = str(exc)
        return result

    def read_rfdc_driver_status(self, *, probe_symbols: bool = True) -> dict[str, Any]:
        import ctypes.util
        import glob
        import sys
        from pathlib import Path

        status: dict[str, Any] = {
            "python_executable": sys.executable,
            "python_version": sys.version,
            "rfdc_handle_available": self.rfdc is not None,
            "rfdc_bind_error": self.rfdc_bind_error,
            "xrfdc_import_ok": False,
            "xrfdc_file": None,
            "xrfdc_attrs_mts": [],
            "rfdc_methods_mts": [],
            "lib_candidates": [],
            "lib_symbol_probe": [],
            "required_c_symbols": [
                "XRFdc_MTS_Sysref_Config",
                "XRFdc_MultiConverter_Init",
                "XRFdc_MultiConverter_Sync",
            ],
            "direct_python_mts_api": self._has_direct_mts_api(),
            "cffi_mts_shim_ready": False,
            "classification": "RFDC_MTS_API_UNAVAILABLE",
            "errors": [],
        }
        try:
            import xrfdc  # type: ignore

            status["xrfdc_import_ok"] = True
            status["xrfdc_file"] = getattr(xrfdc, "__file__", None)
            status["xrfdc_attrs_mts"] = [
                name
                for name in dir(xrfdc)
                if "MTS" in name or "Sysref" in name or "MultiConverter" in name
            ]
            if status["xrfdc_file"]:
                package_dir = Path(str(status["xrfdc_file"])).resolve().parent
                for candidate in (package_dir / "libxrfdc.so", package_dir.parent.parent / "lib64" / "python3.10" / "site-packages" / "xrfdc" / "libxrfdc.so"):
                    if candidate.exists():
                        status["lib_candidates"].append(str(candidate))
            find_lib = ctypes.util.find_library("xrfdc")
            if find_lib:
                status["lib_candidates"].append(str(find_lib))
            for pattern in (
                "/usr/local/share/pynq-venv/lib*/python*/site-packages/xrfdc/libxrfdc.so",
                "/usr/lib*/libxrfdc.so*",
                "/usr/lib*/aarch64-linux-gnu/libxrfdc.so*",
                "/usr/local/lib*/libxrfdc.so*",
            ):
                for path in glob.glob(pattern):
                    status["lib_candidates"].append(str(Path(path).resolve()))
            status["lib_candidates"] = sorted(set(status["lib_candidates"]))
        except Exception as exc:
            status["errors"].append(f"xrfdc_import_or_lib_discovery: {exc}")
        if self.rfdc is not None:
            status["rfdc_methods_mts"] = [
                name
                for name in self._method_names(self.rfdc)
                if "MTS" in name or "Sysref" in name or "MultiConverter" in name or "mts" in name.lower()
            ]
        if probe_symbols:
            patterns = ("XRFdc_MTS", "XRFdc_MultiConverter", "Sysref", "MTSEnable")
            status["lib_symbol_probe"] = [
                self._probe_library_symbols(path, patterns)
                for path in status["lib_candidates"]
            ]
        found_symbols = {
            symbol
            for probe in status["lib_symbol_probe"]
            for symbol in probe.get("symbols", [])
        }
        required = set(status["required_c_symbols"])
        status["c_symbols_available"] = sorted(found_symbols & required)
        try:
            self._ensure_rfdc_mts_cffi()
            status["cffi_mts_shim_ready"] = True
        except Exception as exc:
            status["cffi_mts_shim_error"] = str(exc)
        if status["direct_python_mts_api"]:
            status["classification"] = "RFDC_MTS_API_READY"
        elif status["cffi_mts_shim_ready"]:
            status["classification"] = "RFDC_MTS_SHIM_READY"
        elif required.issubset(found_symbols):
            status["classification"] = "RFDC_MTS_C_SYMBOLS_PRESENT_SHIM_FAILED"
        elif not status["rfdc_handle_available"]:
            status["classification"] = "RFDC_HANDLE_UNAVAILABLE"
        else:
            status["classification"] = "RFDC_MTS_API_UNAVAILABLE"
        return status

    def read_rfdc_sync_status(self) -> dict[str, Any]:
        status: dict[str, Any] = {
            "api_available": self.rfdc is not None,
            "rfdc_bind_error": self.rfdc_bind_error,
            "last_sysref_lock": getattr(self, "rfdc_sync_status", None),
            "driver": self.read_rfdc_driver_status(probe_symbols=False),
            "mts_enable": self._read_mts_enable_cffi() if self.rfdc is not None else [],
            "blocks": [],
        }
        if self.rfdc is None:
            status["classification"] = "RFDC_SYSREF_API_UNAVAILABLE"
            return status

        def safe_read(obj: Any, names: tuple[str, ...]) -> dict[str, Any]:
            out: dict[str, Any] = {}
            for name in names:
                try:
                    value = getattr(obj, name)
                    if callable(value):
                        try:
                            value = value()
                        except TypeError:
                            continue
                    out[name] = value
                except Exception as exc:
                    out[f"{name}_error"] = str(exc)
            return out

        for tile_kind, tiles in (("adc", getattr(self.rfdc, "adc_tiles", [])), ("dac", getattr(self.rfdc, "dac_tiles", []))):
            for tile_idx, tile in enumerate(list(tiles)):
                tile_info = {
                    "kind": tile_kind,
                    "tile": tile_idx,
                    "enabled": getattr(tile, "Enabled", None),
                    "status_readback": safe_read(
                        tile,
                        (
                            "PLLLockStatus",
                            "PLLConfig",
                            "ClockSource",
                            "FIFOStatus",
                            "IPStatus",
                            "TileState",
                            "FabClkOutDiv",
                        ),
                    ),
                    "blocks": [],
                    "available_methods": self._method_names(tile)[:40],
                }
                for block_idx, block in enumerate(self._iter_rfdc_blocks(tile)):
                    item = {"block": block_idx, "available_methods": self._method_names(block)[:40]}
                    item["status_readback"] = safe_read(
                        block,
                        (
                            "BlockStatus",
                            "DecimationFactor",
                            "InterpolationFactor",
                            "QMCSettings",
                            "NyquistZone",
                            "CalibrationMode",
                            "FIFOStatus",
                        ),
                    )
                    try:
                        item["MixerSettings"] = dict(getattr(block, "MixerSettings"))
                    except Exception as exc:
                        item["MixerSettings_error"] = str(exc)
                    tile_info["blocks"].append(item)
                status["blocks"].append(tile_info)
        return status

    def apply_mts_locked_observation_config(self, **kwargs: Any) -> dict[str, Any]:
        """Apply the current observation configuration with MTS/SYSREF required."""
        kwargs.setdefault("require_full_clock_lock", True)
        kwargs.setdefault("require_mts", True)
        config = self.apply_sysref_locked_observation_config(**kwargs)
        clock = config.get("clock", {})
        nco = config.get("nco", {})
        mts = nco.get("mts", {}) if isinstance(nco, Mapping) else {}
        if isinstance(clock, Mapping) and not bool(clock.get("configured", False)):
            raise RuntimeError(f"RFDC_SYSREF_LOCK_FAILED: LMK full lock incomplete: {clock}")
        if isinstance(mts, Mapping):
            if not bool(mts.get("available", True)):
                raise RuntimeError(f"RFDC_SYSREF_API_UNAVAILABLE: RFDC MTS unavailable: {mts}")
            failures = mts.get("failures", [])
            if failures:
                raise RuntimeError(f"RFDC_SYSREF_LOCK_FAILED: RFDC MTS failures: {failures}")
        config["mts_locked"] = True
        config["rfdc_driver"] = self.read_rfdc_driver_status(probe_symbols=False)
        return config

    @staticmethod
    def _normalize_input_source_mode(input_source_mode: str) -> str:
        mode = str(input_source_mode).strip().lower()
        if mode not in ("dac_loopback", "external_adc_tone"):
            raise ValueError("input_source_mode must be dac_loopback or external_adc_tone")
        return mode

    def apply_sysref_locked_observation_config(
        self,
        *,
        observe_center_hz: float,
        dac_signal_hz: float,
        expected_signal_hz: float | None = None,
        view_bw_hz: float = 100_000_000.0,
        amplitude: int = 2048,
        phase_deg: float = 0.0,
        enable_mask: int = 0x01,
        phase_deg_per_channel: float = 0.0,
        phase_deg_by_channel: Optional[Mapping[Any, Any] | Iterable[Any]] = None,
        adc_active_mask: int = 0x0003,
        initialize: bool = False,
        start: bool = False,
        require_full_clock_lock: bool = True,
        require_mts: bool = True,
        mts_adc_tiles: int | None = None,
        mts_dac_tiles: int | None = None,
        mts_adc_ref_tile: int = 0,
        mts_dac_ref_tile: int = 0,
        mts_adc_target_latency: int = -1,
        mts_dac_target_latency: int = -1,
        force_clock_reconfigure: bool = False,
        dac_source_mode: str = "constant_phasor",
        input_source_mode: str = "dac_loopback",
        clock_ref: str = PRODUCTION_CLOCK_REF,
        clock_profile: str = PRODUCTION_CLOCK_PROFILE,
        sync_mode: str = PRODUCTION_SYNC_MODE,
        rfdc_mixer_sequence: str = "sysref_reset_before_pulse",
    ) -> dict[str, Any]:
        observe_center_hz = float(observe_center_hz)
        dac_signal_hz = float(dac_signal_hz)
        expected_signal_hz = float(dac_signal_hz if expected_signal_hz is None else expected_signal_hz)
        view_bw_hz = float(view_bw_hz)
        dac_source_mode = str(dac_source_mode).strip().lower()
        input_source_mode = self._normalize_input_source_mode(input_source_mode)
        if dac_source_mode not in ("constant_phasor", "single_tone"):
            raise ValueError("dac_source_mode must be constant_phasor or single_tone")
        self.validate_observation_frequency_plan(
            center_hz=observe_center_hz,
            bandwidth_hz=view_bw_hz,
            signal_hz=dac_signal_hz,
            signal_name="dac_signal_hz",
        )
        self.validate_observation_frequency_plan(
            center_hz=observe_center_hz,
            bandwidth_hz=view_bw_hz,
            signal_hz=expected_signal_hz,
            signal_name="expected_signal_hz",
        )
        if input_source_mode == "dac_loopback" and abs(expected_signal_hz - dac_signal_hz) > 1.0:
            raise ValueError("dac_loopback input_source_mode requires expected_signal_hz to match dac_signal_hz")
        if (
            dac_source_mode == "constant_phasor"
            and abs(dac_signal_hz - observe_center_hz) > 1.0
        ):
            raise ValueError(
                "Stage 34 constant_phasor requires dac_signal_hz to equal "
                "observe_center_hz; use single_tone for an offset signal"
            )

        clock_recovery: dict[str, Any] = {
            "clock_reconfigured": False,
            "settle_seconds": 0.0,
            "tile_reset_calls": [],
        }
        if initialize:
            self.stop()
            time.sleep(0.05)
            clock = self.clock.read_status(include_registers=False)
            status_ref = str(clock.get("selected_ref", clock.get("ref", "")))
            if bool(force_clock_reconfigure) or not bool(clock.get("configured", False)) or status_ref != str(clock_ref):
                clock = self.configure_clock(
                    ref=str(clock_ref), profile=str(clock_profile)
                )
                clock_recovery["clock_reconfigured"] = True
                if bool(clock.get("configured", False)):
                    settle_seconds = float(self.RFDC_CLOCK_RECOVERY_SETTLE_SECONDS)
                    time.sleep(settle_seconds)
                    clock_recovery["settle_seconds"] = settle_seconds
                    if str(clock.get("sysref_policy")) == "mts_only":
                        # This RFDC generation's restart sequencer reaches a
                        # SYSREF wait at state 6.  Keep request-mode SYSREF on
                        # across tile Reset; the MTS sequence below owns the
                        # final synchronized deassertion.
                        clock_recovery["sysref_request_for_tile_reset"] = (
                            self.clock.set_sysref(True)
                        )
                    clock_recovery["tile_reset_calls"] = self.reset_all_rfdc_tiles()
            else:
                self._write_sync_config(clock_ref=self.CLOCK_REFS[str(clock_ref)])
                self.clock_reference = str(clock_ref)
                self.clock_status = dict(clock)
            if require_full_clock_lock and not clock.get("configured", False):
                raise RuntimeError(f"RFDC_SYSREF_LOCK_FAILED: LMK {clock_ref} clock did not lock: {clock}")
            self.set_adc_active_mask(adc_active_mask)
            self.set_sync_mode(sync_mode)
            self.set_mode("spec")
        else:
            clock = getattr(self, "clock_status", {})

        dac_nco_hz = observe_center_hz
        dac_tone_hz = 0.0 if dac_source_mode == "constant_phasor" else (dac_signal_hz - observe_center_hz)
        dac_tone_mode = (
            "constant_phasor"
            if dac_source_mode == "constant_phasor"
            else self.STAGE34_DAC_TONE_MODE
        )

        self.configure_rfdc(
            rfdc_complex_sample_rate_hz=self.RFDC_COMPLEX_SAMPLE_RATE_HZ,
            f_center=observe_center_hz,
            bandwidth=view_bw_hz,
            decimation=self.RFDC_DECIMATION,
        )
        nco = self._configure_rfdc_sysref_locked_pair(
            adc_nco_hz=-observe_center_hz,
            dac_nco_hz=dac_nco_hz,
            bandwidth_hz=view_bw_hz,
            require=True,
            require_mts=require_mts,
            mts_adc_tiles=mts_adc_tiles,
            mts_dac_tiles=mts_dac_tiles,
            mts_adc_ref_tile=mts_adc_ref_tile,
            mts_dac_ref_tile=mts_dac_ref_tile,
            mts_adc_target_latency=int(mts_adc_target_latency),
            mts_dac_target_latency=int(mts_dac_target_latency),
            rfdc_mixer_sequence=str(rfdc_mixer_sequence),
        )
        self.rfdc_config = {
            "rfdc_complex_sample_rate_hz": self.RFDC_COMPLEX_SAMPLE_RATE_HZ,
            "complex_sample_rate_hz": self.RFDC_COMPLEX_SAMPLE_RATE_HZ,
            "fs_analog": self.RFDC_ANALOG_SAMPLE_RATE_HZ,
            "adc_analog_sample_rate_hz": self.RFDC_ADC_ANALOG_SAMPLE_RATE_HZ,
            "dac_analog_sample_rate_hz": self.RFDC_DAC_ANALOG_SAMPLE_RATE_HZ,
            "f_center": observe_center_hz,
            "observe_center_hz": observe_center_hz,
            "dac_signal_hz": dac_signal_hz,
            "expected_signal_hz": expected_signal_hz,
            "input_signal_hz": expected_signal_hz,
            "input_source_mode": input_source_mode,
            "bandwidth": view_bw_hz,
            "decimation": self.RFDC_DECIMATION,
            "adc_decimation": self.RFDC_DECIMATION,
            "dac_interpolation": self.RFDC_INTERPOLATION,
            "nco_configured": nco["configured"],
            "nco_results": nco,
            "sysref_locked": bool(nco["configured"]),
        }
        tone = self.configure_dac_tone_bank(
            freq_hz=dac_tone_hz,
            amplitude=int(amplitude),
            phase_offset_deg=float(phase_deg),
            phase_deg_per_channel=float(phase_deg_per_channel),
            phase_deg_by_channel=phase_deg_by_channel,
            enable_mask=int(enable_mask),
            dac_sample_rate_hz=float(self.RFDC_COMPLEX_SAMPLE_RATE_HZ),
            mode=dac_tone_mode,
        )
        epoch = self.reset_dac_phase()
        if start:
            self.start()
        config = {
            "observe_center_hz": observe_center_hz,
            "dac_signal_hz": dac_signal_hz,
            "expected_signal_hz": expected_signal_hz,
            "input_signal_hz": expected_signal_hz,
            "view_bw_hz": view_bw_hz,
            "expected_baseband_hz": expected_signal_hz - observe_center_hz,
            "dac_source_mode": dac_source_mode,
            "input_source_mode": input_source_mode,
            "dac_nco_hz": dac_nco_hz,
            "dac_tone_hz": dac_tone_hz,
            "dac_tone_mode": dac_tone_mode,
            "amplitude": int(amplitude),
            "phase_deg": float(phase_deg),
            "phase_deg_per_channel": float(phase_deg_per_channel),
            "phase_deg_by_channel": [float(value) for value in tone.get("phase_deg_by_channel", [])],
            "enable_mask": int(enable_mask),
            "adc_active_mask": int(adc_active_mask),
            "clock_ref": str(clock_ref),
            "clock_profile": str(clock_profile),
            "sync_mode": str(sync_mode),
            "rfdc_mixer_sequence": str(rfdc_mixer_sequence),
            "clock": dict(clock) if isinstance(clock, Mapping) else clock,
            "clock_recovery": clock_recovery,
            "nco": nco,
            "tone": tone,
            "dac_phase_epoch": int(epoch),
            "rfdc_sysref_lock": self.read_rfdc_sync_status(),
        }
        self.observation_instrument_config = config
        return config

    @staticmethod
    def dac_phase_step_from_frequency(freq_hz: float, dac_sample_rate_hz: float = 320_000_000.0) -> int:
        if dac_sample_rate_hz <= 0:
            raise ValueError("dac_sample_rate_hz must be positive")
        if abs(float(freq_hz)) >= dac_sample_rate_hz:
            raise ValueError("|freq_hz| must be lower than dac_sample_rate_hz")
        return int(round((float(freq_hz) / float(dac_sample_rate_hz)) * (1 << 32))) & 0xFFFF_FFFF

    @staticmethod
    def _wrap_phase0_word(phase_deg: float) -> int:
        return int(round(((float(phase_deg) % 360.0) / 360.0) * (1 << 32))) & 0xFFFF_FFFF

    @staticmethod
    def _normalize_phase_deg_by_channel(
        phase_deg_by_channel: Optional[Mapping[Any, Any] | Iterable[Any]],
        *,
        phase_offset_deg: float = 0.0,
        phase_deg_per_channel: float = 0.0,
        count: int = 8,
    ) -> list[float]:
        fallback = [
            float(phase_offset_deg) + float(phase_deg_per_channel) * channel
            for channel in range(int(count))
        ]
        if phase_deg_by_channel is None:
            return fallback
        if isinstance(phase_deg_by_channel, Mapping):
            phases = []
            for channel in range(int(count)):
                value = phase_deg_by_channel.get(channel)
                if value is None:
                    value = phase_deg_by_channel.get(str(channel), fallback[channel])
                phases.append(float(value))
            return phases
        values = [float(value) for value in phase_deg_by_channel]
        if len(values) > int(count):
            raise ValueError(f"phase_deg_by_channel accepts at most {int(count)} entries")
        return values + fallback[len(values):]

    @staticmethod
    def _configured_phase_deg_for_channel(
        channel: int,
        *,
        configured_phase_deg: float = 0.0,
        phase_deg_per_channel: float = 0.0,
        phase_deg_by_channel: Optional[Mapping[Any, Any] | Iterable[Any]] = None,
    ) -> float:
        phases = T510FEngine._normalize_phase_deg_by_channel(
            phase_deg_by_channel,
            phase_offset_deg=float(configured_phase_deg),
            phase_deg_per_channel=float(phase_deg_per_channel),
            count=8,
        )
        return T510FEngine._wrap_phase_deg(phases[int(channel)])

    def set_dac_tone(
        self,
        *,
        enable: bool = True,
        amplitude: int = 2048,
        phase_step: int = 0x0080_0000,
        channel: Optional[int] = None,
        phase0: int = 0,
        phase_inject: int = 0,
        mode: str | int = "single_tone",
    ) -> None:
        if not 0 <= amplitude <= 8192:
            raise ValueError("DAC debug tone amplitude must be in range 0..8192")
        if not 0 <= phase_step <= 0xFFFF_FFFF:
            raise ValueError("DAC debug tone phase_step must fit in 32 bits")
        if not 0 <= phase0 <= 0xFFFF_FFFF:
            raise ValueError("DAC phase0 must fit in 32 bits")
        if not 0 <= phase_inject <= 0xFFFF_FFFF:
            raise ValueError("DAC phase_inject must fit in 32 bits")
        mode_value = mode if isinstance(mode, int) else self.DAC_MODES.get(mode.lower())
        if mode_value is None or not 0 <= int(mode_value) <= 3:
            raise ValueError(f"Unsupported DAC tone mode: {mode}")

        if channel is None:
            self.ctrl.write(self.regs.DAC_TONE_CONTROL, 0x1 if enable else 0x0)
            self.ctrl.write(self.regs.DAC_TONE_AMPLITUDE, amplitude)
            self.ctrl.write(self.regs.DAC_TONE_PHASE_STEP, phase_step)
            self.ctrl.write(self.regs.DAC_ENABLE_MASK, 0xFF if enable else 0x00)
            self.ctrl.write(self.regs.DAC_BROADCAST_AMPLITUDE, amplitude)
            self.ctrl.write(self.regs.DAC_BROADCAST_PHASE_STEP, phase_step)
            return

        if not 0 <= channel < 8:
            raise ValueError("DAC channel must be in range 0..7")
        mask = int(self.ctrl.read(self.regs.DAC_ENABLE_MASK)) & 0xFF
        if enable:
            mask |= 1 << channel
        else:
            mask &= ~(1 << channel)
        base = self.regs.DAC_CH_BASE + channel * self.regs.DAC_CH_STRIDE
        self.ctrl.write(self.regs.DAC_ENABLE_MASK, mask)
        self.ctrl.write(base + 0x00, phase_step)
        self.ctrl.write(base + 0x04, amplitude)
        self.ctrl.write(base + 0x08, phase0)
        self.ctrl.write(base + 0x0C, phase_inject)
        self.ctrl.write(base + 0x10, int(mode_value))

    def configure_dac_tone_bank(
        self,
        *,
        freq_hz: float = 20_000_000.0,
        amplitude: int = 2048,
        phase_offset_deg: float = 0.0,
        phase_deg_per_channel: float = 0.0,
        phase_deg_by_channel: Optional[Mapping[Any, Any] | Iterable[Any]] = None,
        enable_mask: int = 0xFF,
        dac_sample_rate_hz: float = 320_000_000.0,
        mode: str | int = "single_tone",
    ) -> dict[str, Any]:
        if not 0 <= enable_mask <= 0xFF:
            raise ValueError("DAC enable_mask must be in range 0x00..0xff")
        phase_step = self.dac_phase_step_from_frequency(freq_hz, dac_sample_rate_hz)
        self.set_dac_tone(enable=enable_mask != 0, amplitude=amplitude, phase_step=phase_step, mode=mode)
        phase_deg_values = self._normalize_phase_deg_by_channel(
            phase_deg_by_channel,
            phase_offset_deg=float(phase_offset_deg),
            phase_deg_per_channel=float(phase_deg_per_channel),
            count=8,
        )
        phase0_by_channel: dict[int, int] = {}
        for channel in range(8):
            phase_deg = phase_deg_values[channel]
            phase0 = self._wrap_phase0_word(phase_deg)
            phase0_by_channel[channel] = phase0
            self.set_dac_tone(
                enable=bool(enable_mask & (1 << channel)),
                amplitude=amplitude,
                phase_step=phase_step,
                channel=channel,
                phase0=phase0,
                phase_inject=0,
                mode=mode,
            )
        self.set_dac_enable_mask(enable_mask)
        return {
            "freq_hz": float(freq_hz),
            "dac_sample_rate_hz": float(dac_sample_rate_hz),
            "phase_step": phase_step,
            "phase_offset_deg": float(phase_offset_deg),
            "phase_deg_per_channel": float(phase_deg_per_channel),
            "phase_deg_by_channel": [float(value) for value in phase_deg_values],
            "phase0_by_channel": phase0_by_channel,
            "amplitude": int(amplitude),
            "enable_mask": int(enable_mask),
        }

    def set_dac_enable_mask(self, mask: int) -> None:
        if not 0 <= mask <= 0xFF:
            raise ValueError("DAC enable mask must be in range 0x00..0xff")
        self.ctrl.write(self.regs.DAC_ENABLE_MASK, mask)

    def read_dac_channels(self, *, dac_sample_rate_hz: float = 320_000_000.0) -> dict[str, Any]:
        """Read back the complete eight-lane programmable DAC tone bank."""
        if dac_sample_rate_hz <= 0:
            raise ValueError("dac_sample_rate_hz must be positive")
        enable_mask = int(self.ctrl.read(self.regs.DAC_ENABLE_MASK)) & 0xFF
        rows: list[dict[str, Any]] = []
        mode_names = {value: name for name, value in self.DAC_MODES.items()}
        for channel in range(8):
            base = self.regs.DAC_CH_BASE + channel * self.regs.DAC_CH_STRIDE
            phase_step = int(self.ctrl.read(base + 0x00)) & 0xFFFF_FFFF
            signed_step = phase_step - (1 << 32) if phase_step & (1 << 31) else phase_step
            amplitude = int(self.ctrl.read(base + 0x04)) & 0xFFFF
            phase0 = int(self.ctrl.read(base + 0x08)) & 0xFFFF_FFFF
            phase_inject = int(self.ctrl.read(base + 0x0C)) & 0xFFFF_FFFF
            mode = int(self.ctrl.read(base + 0x10)) & 0x3
            rows.append({
                "channel": channel,
                "enabled": bool(enable_mask & (1 << channel)),
                "phase_step": phase_step,
                "baseband_frequency_hz": float(signed_step) * float(dac_sample_rate_hz) / float(1 << 32),
                "amplitude_code": amplitude,
                "phase0": phase0,
                "phase_deg": float(phase0) * 360.0 / float(1 << 32),
                "phase_inject": phase_inject,
                "mode": mode,
                "mode_name": mode_names.get(mode, f"unknown_{mode}"),
            })
        return {
            "enable_mask": enable_mask,
            "dac_phase_epoch": int(self.ctrl.read(self.regs.DAC_PHASE_EPOCH)) & 0xFFFF_FFFF,
            "channels": rows,
        }

    def read_rfdc_mixer_frequencies(self) -> dict[str, Any]:
        """Read RFDC mixer/NCO frequencies without changing RFDC state."""
        if self.rfdc is None:
            return {"available": False, "mixers": [], "errors": ["RFDC IP handle not found"]}
        mixers: list[dict[str, Any]] = []
        errors: list[str] = []
        for kind, tiles in (
            ("adc", getattr(self.rfdc, "adc_tiles", [])),
            ("dac", getattr(self.rfdc, "dac_tiles", [])),
        ):
            for tile_index, tile in enumerate(list(tiles)):
                for block_index, block in enumerate(self._iter_rfdc_blocks(tile)):
                    try:
                        settings = dict(getattr(block, "MixerSettings"))
                        mixers.append({
                            "kind": kind,
                            "tile": tile_index,
                            "block": block_index,
                            "frequency_mhz": float(settings["Freq"]),
                        })
                    except Exception as exc:  # pragma: no cover - inactive board block
                        errors.append(f"{kind}[{tile_index}].block[{block_index}]: {exc}")
        return {"available": bool(mixers), "mixers": mixers, "errors": errors}

    def reset_dac_phase(self) -> int:
        before = int(self.ctrl.read(self.regs.DAC_PHASE_EPOCH))
        self.ctrl.write(self.regs.DAC_PHASE_EPOCH, 0x1)
        after = int(self.ctrl.read(self.regs.DAC_PHASE_EPOCH))
        if after == before:
            time.sleep(0.001)
            after = int(self.ctrl.read(self.regs.DAC_PHASE_EPOCH))
        return after

    def configure_network(
        self,
        *,
        src_ip: str,
        src_mac: str,
        dgx_a: Mapping[str, Any],
        dgx_b: Mapping[str, Any],
        time_dst: Optional[Mapping[str, Any]] = None,
    ) -> None:
        self.ctrl.write(self.regs.SRC_IP, _ipv4_to_int(src_ip))
        src_lo, src_hi = _mac_to_parts(src_mac)
        self.ctrl.write(self.regs.SRC_MAC_LO, src_lo)
        self.ctrl.write(self.regs.SRC_MAC_HI, src_hi)

        self.ctrl.write(self.regs.DGX_A_IP, _ipv4_to_int(dgx_a["ip"]))
        dgx_a_lo, dgx_a_hi = _mac_to_parts(dgx_a["mac"])
        self.ctrl.write(self.regs.DGX_A_MAC_LO, dgx_a_lo)
        self.ctrl.write(self.regs.DGX_A_MAC_HI, dgx_a_hi)
        self.ctrl.write(self.regs.DGX_A_UDP_PORT, int(dgx_a.get("port", 4100)))

        self.ctrl.write(self.regs.DGX_B_IP, _ipv4_to_int(dgx_b["ip"]))
        dgx_b_lo, dgx_b_hi = _mac_to_parts(dgx_b["mac"])
        self.ctrl.write(self.regs.DGX_B_MAC_LO, dgx_b_lo)
        self.ctrl.write(self.regs.DGX_B_MAC_HI, dgx_b_hi)
        self.ctrl.write(self.regs.DGX_B_UDP_PORT, int(dgx_b.get("port", 4200)))

        if time_dst is not None:
            self.ctrl.write(self.regs.TIME_DST_IP, _ipv4_to_int(time_dst["ip"]))
            self.ctrl.write(self.regs.TIME_UDP_PORT, int(time_dst.get("port", 4300)))
            if "mac" in time_dst:
                self._write_tx_endpoint(
                    2,
                    enable=True,
                    ip=str(time_dst["ip"]),
                    mac=str(time_dst["mac"]),
                    dst_port=int(time_dst.get("port", 4300)),
                    src_port=int(time_dst.get("src_port", self.ctrl.read(self.regs.SRC_UDP_PORT))),
                )

    def configure_tx_control(
        self,
        *,
        force_dry_run: bool = True,
        cmac_enable: bool = False,
        frame_builder_enable: bool = True,
        drop_on_route_miss: bool = True,
        diagnostic_ignore_link_gate: bool = False,
        clear_counters: bool = False,
    ) -> None:
        value = (
            (0x1 if force_dry_run else 0x0)
            | (0x2 if cmac_enable else 0x0)
            | (0x4 if frame_builder_enable else 0x0)
            | (0x8 if drop_on_route_miss else 0x0)
            | (0x10 if diagnostic_ignore_link_gate else 0x0)
            | (0x20 if clear_counters else 0x0)
        )
        self.ctrl.write(self.regs.TX_CONTROL, value)

    @classmethod
    def _normalize_science_sample_rate_msps(cls, sample_rate_msps: int | float | str) -> int:
        try:
            value = int(round(float(str(sample_rate_msps).lower().replace("mhz", "").strip())))
        except Exception as exc:
            raise ValueError(f"Unsupported science sample rate: {sample_rate_msps!r}") from exc
        if value not in cls.SCIENCE_SAMPLE_RATES:
            raise ValueError("Stage 34 complex sample-rate setting must be 160 or 320 MS/s")
        return value

    @classmethod
    def _normalize_science_output_mode(cls, output_mode: str | int) -> tuple[str, int]:
        if isinstance(output_mode, int):
            code = int(output_mode)
            if code not in cls.SCIENCE_OUTPUT_MODE_NAMES:
                raise ValueError("science output mode code must be in range 0..4")
            if code == 4:
                raise ValueError("Stage 34 does not support TIME_MONITOR_SPEC")
            return cls.SCIENCE_OUTPUT_MODE_NAMES[code], code
        key = str(output_mode).strip().lower().replace("-", "_").replace(" ", "_")
        if key not in cls.SCIENCE_OUTPUT_MODES:
            raise ValueError(
                "science output mode must be OFF, TIME_ONLY, SPEC_ONLY, "
                "TIME_SPEC, or TIME_MONITOR_SPEC"
            )
        code = int(cls.SCIENCE_OUTPUT_MODES[key])
        if code == 4:
            raise ValueError("Stage 34 does not support TIME_MONITOR_SPEC")
        return cls.SCIENCE_OUTPUT_MODE_NAMES[code], code

    @classmethod
    def _science_block_names(cls, mask: int) -> list[str]:
        return [
            name
            for bit, name in cls.SCIENCE_BLOCK_REASONS.items()
            if bit != 7 and int(mask) & (1 << bit)
        ]

    @classmethod
    def estimate_science_payload_rate(
        cls,
        sample_rate_msps: int | float | str,
        output_mode: str | int,
        *,
        ninput: int = 8,
        iq_bits: int = 16,
        payload_bytes: int = 8192,
    ) -> dict[str, Any]:
        sample_rate_msps = cls._normalize_science_sample_rate_msps(sample_rate_msps)
        mode_name, mode_code = cls._normalize_science_output_mode(output_mode)
        rate_config = cls.SCIENCE_SAMPLE_RATES[sample_rate_msps]
        sample_rate_hz = float(rate_config["sample_rate_hz"])
        full_stream_factor = 0.0
        full_time = mode_code in (1, 3, 4)
        full_spec = mode_code in (2, 3)
        monitor_spec = mode_code == 4
        if full_time:
            full_stream_factor += 1.0
        if full_spec:
            full_stream_factor += 1.0
        if monitor_spec:
            full_stream_factor += 1.0 / 64.0

        block_mask = 0
        if sample_rate_msps == 320 and mode_code == 3:
            block_mask |= 1 << 0
        payload_bps = sample_rate_hz * int(ninput) * 2.0 * int(iq_bits) * full_stream_factor
        payload_mbps = payload_bps / 1_000_000.0
        packet_rate = 0.0 if payload_bytes <= 0 else (payload_bps / 8.0) / float(payload_bytes)
        # Ethernet/IP/UDP + T510 header + preamble/FCS/IFG estimate. This is a
        # planning number; pcap validation remains the real gate.
        wire_bytes = float(payload_bytes + 128 + 42 + 24)
        wire_mbps_est = payload_mbps * (wire_bytes / max(float(payload_bytes), 1.0))
        return {
            "sample_rate_msps": sample_rate_msps,
            "sample_rate_code": int(rate_config["code"]),
            "output_mode": mode_name,
            "output_mode_code": mode_code,
            "pl_decim_factor": int(rate_config["pl_decim"]),
            "sample_rate_hz": sample_rate_hz,
            "complex_sample_rate_msps": sample_rate_hz / 1_000_000.0,
            "ninput": int(ninput),
            "iq_bits": int(iq_bits),
            "full_time_stream": bool(full_time),
            "full_spec_stream": bool(full_spec),
            "monitor_spec_stream": bool(monitor_spec),
            "payload_mbps": payload_mbps,
            "wire_mbps_est": wire_mbps_est,
            "packet_rate_est": packet_rate,
            "payload_bytes": int(payload_bytes),
            "allowed": block_mask == 0,
            "block_reason_mask": block_mask,
            "block_reasons": cls._science_block_names(block_mask),
        }

    def read_science_output_status(self) -> dict[str, Any]:
        raw_control = int(self.ctrl.read(self.regs.SCIENCE_CONTROL))
        raw_status = int(self.ctrl.read(self.regs.SCIENCE_STATUS))
        raw_sample_rate_mode = int(self.ctrl.read(self.regs.SCIENCE_SAMPLE_RATE_MODE))
        raw_mode = int(self.ctrl.read(self.regs.SCIENCE_OUTPUT_MODE))
        raw_block = int(self.ctrl.read(self.regs.SCIENCE_BLOCK_REASON))
        raw_multiflow = int(self.ctrl.read(self.regs.SCIENCE_TIME_MULTIFLOW_CONTROL))
        raw_antialias = int(self.ctrl.read(self.regs.SCIENCE_ANTIALIAS_STATUS))
        raw_antialias_coeff = int(self.ctrl.read(self.regs.SCIENCE_ANTIALIAS_COEFF_VERSION))
        sample_rate_msps = self.SCIENCE_SAMPLE_RATE_BY_CODE.get(raw_sample_rate_mode & 0x3, 160)
        mode_name = self.SCIENCE_OUTPUT_MODE_NAMES.get(raw_mode & 0x7, f"UNKNOWN_{raw_mode & 0x7}")
        status = {
            "science_control": raw_control,
            "science_status": raw_status,
            "science_sample_rate_mode": raw_sample_rate_mode,
            "science_output_mode_code": raw_mode,
            "science_output_mode": mode_name,
            "science_sample_rate_msps": sample_rate_msps,
            "science_sample_rate_hz": int(self.ctrl.read(self.regs.SCIENCE_SAMPLE_RATE_HZ)),
            "science_decim_factor": int(self.ctrl.read(self.regs.SCIENCE_DECIM_FACTOR)),
            "science_payload_rate_mbps": int(self.ctrl.read(self.regs.SCIENCE_PAYLOAD_RATE_MBPS)),
            "science_block_reason": raw_block,
            "science_block_reasons": self._science_block_names(raw_block),
            "fengine_science_valid": (raw_block >> 7) & 0x1,
            "pfb_fft_not_ready": (raw_block >> 8) & 0x1,
            "fengine_overflow": (raw_block >> 9) & 0x1,
            "spec_route_incomplete": (raw_block >> 10) & 0x1,
            "science_rate_dropped": (raw_block >> 11) & 0x1,
            "science_dropped_beat_count": int(self.ctrl.read(self.regs.SCIENCE_DROPPED_BEAT_COUNT)),
            "science_capability": int(self.ctrl.read(self.regs.SCIENCE_CAPABILITY)),
            "time_live_interval_beats": int(self.ctrl.read(self.regs.SCIENCE_TIME_LIVE_INTERVAL_BEATS)),
            "time_multiflow_control": raw_multiflow,
            "time_multiflow_enable": raw_multiflow & 0x1,
            "time_multiflow_base_endpoint": (raw_multiflow >> 8) & 0x7,
            "time_multiflow_count": (raw_multiflow >> 16) & 0xF,
            "science_antialias_status": raw_antialias,
            "science_antialias_taps": raw_antialias & 0xFF,
            "science_antialias_100m_active": (raw_antialias >> 8) & 0x1,
            "science_antialias_100m_primed": (raw_antialias >> 9) & 0x1,
            "science_antialias_coeff_version": raw_antialias_coeff,
            "halfband_active": (raw_antialias >> 8) & 0x1,
            "halfband_primed": (raw_antialias >> 9) & 0x1,
            "halfband_taps": raw_antialias & 0xFF,
            "halfband_coeff_id": raw_antialias_coeff,
            "force_dry_run": raw_control & 0x1,
            "cmac_enable": (raw_control >> 1) & 0x1,
            "live_requested": (raw_control >> 2) & 0x1,
            "time_enabled": raw_status & 0x1,
            "spec_enabled": (raw_status >> 1) & 0x1,
            "time_spec_rejected": (raw_status >> 2) & 0x1,
            "spec_science_ready": (raw_status >> 3) & 0x1,
            "wide_tx_ready": (raw_status >> 4) & 0x1,
            "cmac_live_ready": (raw_status >> 5) & 0x1,
        }
        estimate_mode = (raw_mode & 0x7) if (raw_mode & 0x7) in self.SCIENCE_OUTPUT_MODE_NAMES else 0
        status["estimate"] = self.estimate_science_payload_rate(sample_rate_msps, estimate_mode)
        return status

    def read_time_ddr_ring_status(self) -> dict[str, Any]:
        raw_control = int(self.ctrl.read(self.regs.SCIENCE_TIME_DDR_RING_CONTROL))
        raw_status = int(self.ctrl.read(self.regs.SCIENCE_TIME_DDR_RING_STATUS))
        occupancy = int(self.ctrl.read(self.regs.SCIENCE_TIME_DDR_RING_OCCUPANCY))
        write_count = int(self.ctrl.read(self.regs.SCIENCE_TIME_DDR_RING_WRITE_COUNT))
        read_count = int(self.ctrl.read(self.regs.SCIENCE_TIME_DDR_RING_READ_COUNT))
        drop_count = int(self.ctrl.read(self.regs.SCIENCE_TIME_DDR_RING_DROP_COUNT))
        error_count = int(self.ctrl.read(self.regs.SCIENCE_TIME_DDR_RING_ERROR_COUNT))
        return {
            "time_ddr_ring_control": raw_control,
            "time_ddr_ring_enable": raw_control & 0x1,
            "time_ddr_ring_clear_pulse": (raw_control >> 1) & 0x1,
            "time_ddr_ring_base_addr": (
                int(self.ctrl.read(self.regs.SCIENCE_TIME_DDR_RING_BASE_LO))
                | (int(self.ctrl.read(self.regs.SCIENCE_TIME_DDR_RING_BASE_HI)) << 32)
            ),
            "time_ddr_ring_slots": int(self.ctrl.read(self.regs.SCIENCE_TIME_DDR_RING_SLOTS)) & 0xFFFF,
            "time_ddr_ring_status": raw_status,
            "time_ddr_ring_status_write_count_lsb": raw_status & 0xFF,
            "time_ddr_ring_status_error_count_lsb": (raw_status >> 8) & 0xFF,
            "time_ddr_ring_status_occupancy_lsb": (raw_status >> 16) & 0xFF,
            "time_ddr_ring_status_drop_count_lsb": (raw_status >> 24) & 0xFF,
            "time_ddr_ring_occupancy": occupancy,
            "time_ddr_ring_write_count": write_count,
            "time_ddr_ring_read_count": read_count,
            "time_ddr_ring_drop_count": drop_count,
            "time_ddr_ring_error_count": error_count,
        }

    def configure_science_output(
        self,
        sample_rate_msps: int | float | str,
        output_mode: str | int,
        *,
        force_dry_run: bool = True,
        cmac_enable: bool = False,
        clear_counters: bool = False,
        apply_stream_mode: bool = True,
        validate_live_ready: bool = True,
    ) -> dict[str, Any]:
        estimate = self.estimate_science_payload_rate(sample_rate_msps, output_mode)
        if not estimate["allowed"]:
            raise ValueError(
                f"science output mode rejected: {', '.join(estimate['block_reasons'])}"
            )

        sample_rate_code = int(estimate["sample_rate_code"])
        output_code = int(estimate["output_mode_code"])
        control = (
            (0x1 if force_dry_run else 0x0)
            | (0x2 if cmac_enable else 0x0)
            | (0x4 if not force_dry_run else 0x0)
        )
        self.ctrl.write(self.regs.SCIENCE_SAMPLE_RATE_MODE, sample_rate_code)
        self.ctrl.write(self.regs.SCIENCE_OUTPUT_MODE, output_code)
        self.ctrl.write(self.regs.SCIENCE_SAMPLE_RATE_HZ, int(round(float(estimate["sample_rate_hz"]))))
        self.ctrl.write(self.regs.SCIENCE_DECIM_FACTOR, int(estimate["pl_decim_factor"]))
        self.ctrl.write(self.regs.SCIENCE_PAYLOAD_RATE_MBPS, int(round(float(estimate["payload_mbps"]))))
        self.ctrl.write(self.regs.SCIENCE_CONTROL, control)
        self.ctrl.write(self.regs.SAMPLE_RATE_HZ, int(round(float(estimate["sample_rate_hz"]))))

        if apply_stream_mode:
            if output_code == 0:
                self.set_mode("snapshot")
            elif output_code == 1:
                self.set_mode("time")
            elif output_code == 2:
                self.set_mode("spec")
            else:
                self.set_mode("dual")

        self.configure_tx_control(
            force_dry_run=bool(force_dry_run),
            cmac_enable=bool(cmac_enable),
            frame_builder_enable=True,
            drop_on_route_miss=True,
            clear_counters=bool(clear_counters),
        )
        status = self.read_science_output_status()
        cmac = self.read_cmac_status()
        live_requested = bool(cmac_enable and not force_dry_run)
        blockers = list(status.get("science_block_reasons", []))
        if live_requested and validate_live_ready:
            if not bool(cmac.get("cmac_live_ready", False)):
                blockers.append("CMAC_LINK_NOT_READY")
            if output_code in (2, 3) and not bool(status.get("spec_science_ready", False)):
                blockers.append("FENGINE_SCIENCE_NOT_READY")
            if not bool(status.get("wide_tx_ready", False)):
                blockers.append("WIDE_512B_TX_PATH_NOT_IMPLEMENTED")
            if blockers:
                raise RuntimeError(f"QSFP_LIVE_SCIENCE_BLOCKED: {', '.join(sorted(set(blockers)))}")
        return {"estimate": estimate, "science_status": status, "cmac_status": cmac}

    def read_cmac_status(self) -> dict[str, Any]:
        status = self.read_status()
        tx = self.read_tx_status()
        core_version = int(status.get("core_version", 0))
        an_lt_applicable = core_version in (0x0001_0014, 0x0001_0015)
        module_present = bool(status.get("tx_qsfp_module_present", 0) or tx.get("qsfp_module_present", 0))
        dry_run = bool(tx.get("udp_dry_run_active", 1))
        cmac_live_ready = bool(
            tx.get("qsfp_link_up", 0)
            and tx.get("cmac_reset_done", 0)
            and tx.get("gt_locked", 0)
            and tx.get("cmac_tx_ready", 0)
            and not tx.get("tx_local_fault", 0)
            and not tx.get("tx_remote_fault", 0)
            and not dry_run
        )
        if cmac_live_ready:
            classification = "CMAC_100G_TX_READY"
        elif not module_present:
            classification = "QSFP_MODULE_NOT_PRESENT_OR_NOT_DETECTED"
        elif not bool(tx.get("gt_refclk_seen", 0)):
            classification = "QSFP_MODULE_PRESENT_BUT_GT_REFCLK_NOT_SEEN"
        elif not bool(tx.get("gt_locked", 0)):
            classification = "QSFP_MODULE_PRESENT_BUT_GT_NOT_LOCKED"
        elif not bool(tx.get("cmac_reset_done", 0)):
            classification = "QSFP_GT_LOCKED_BUT_CMAC_RESET_NOT_DONE"
        elif not bool(tx.get("cmac_tx_ready", 0)):
            classification = "QSFP_CMAC_RESET_DONE_BUT_TX_NOT_READY"
        elif an_lt_applicable and not bool(tx.get("cmac_an_autoneg_complete", 0)):
            classification = "QSFP_CMAC_AN_LT_NOT_COMPLETE"
        elif an_lt_applicable and bool(tx.get("cmac_an_lp_ability_valid", 0)) and not bool(tx.get("cmac_an_lp_ability_100gbase_cr4", 0)):
            classification = "QSFP_CMAC_PARTNER_NOT_ADVERTISING_100G_CR4"
        elif an_lt_applicable and bool(tx.get("cmac_lt_training_fail_any", 0)):
            classification = "QSFP_CMAC_LT_TRAINING_FAIL"
        elif bool(tx.get("tx_local_fault", 0)):
            classification = "QSFP_CMAC_LOCAL_FAULT"
        elif bool(tx.get("tx_remote_fault", 0)):
            classification = "QSFP_CMAC_REMOTE_FAULT"
        elif dry_run:
            classification = "QSFP_CMAC_READY_BUT_TX_FORCED_DRY_RUN"
        elif module_present:
            classification = "QSFP_MODULE_PRESENT_BUT_CMAC_NOT_READY"
        else:
            classification = "QSFP_MODULE_NOT_PRESENT_OR_NOT_DETECTED"
        return {
            "classification": classification,
            "module_present": module_present,
            "an_lt_applicable": an_lt_applicable,
            "cmac_live_ready": cmac_live_ready,
            "pcap_gate_possible": cmac_live_ready,
            "accepted_packet_count": int(tx.get("tx_cmac_accepted_packet_count", 0)),
            "accepted_byte_count": int(tx.get("tx_cmac_accepted_byte_count", 0)),
            "an_autoneg_complete": bool(tx.get("cmac_an_autoneg_complete", 0)),
            "an_lp_ability_valid": bool(tx.get("cmac_an_lp_ability_valid", 0)),
            "an_lp_autoneg_able": bool(tx.get("cmac_an_lp_autoneg_able", 0)),
            "an_lp_ability_100gbase_cr4": bool(tx.get("cmac_an_lp_ability_100gbase_cr4", 0)),
            "an_rs_fec_enable": bool(tx.get("cmac_an_rs_fec_enable", 0)),
            "lt_signal_detect_all": bool(tx.get("cmac_lt_signal_detect_all", 0)),
            "lt_training_any": bool(tx.get("cmac_lt_training_any", 0)),
            "lt_training_fail_any": bool(tx.get("cmac_lt_training_fail_any", 0)),
            "lt_frame_lock_all": bool(tx.get("cmac_lt_frame_lock_all", 0)),
            "tx": tx,
            "status": status,
            "science_status": self.read_science_output_status(),
        }

    def _configure_science_data_path(
        self,
        *,
        sample_rate_msps: int | float | str = 100,
        output_mode: str | int = "time_spec",
        dst_ip: str = "10.0.1.16",
        dst_mac: str = "08:c0:eb:d5:95:b2",
        src_ip: str = "10.0.1.1",
        src_mac: str = "02:00:00:00:00:01",
        time_dst_port_base: int = 4300,
        spec_dst_port_base: int = 4308,
        time_src_port_base: int = 4000,
        spec_src_port_base: int = 4008,
        time_endpoint_base: int = 0,
        spec_endpoint_base: int = 8,
        time_flow_count: int = 8,
        spec_route_count: int = 8,
        time_payload_nsamp: int = 64,
        time_live_interval_beats: int = 0,
        spec_chan_count: int = 64,
        spec_time_count: int = 4,
        spec_chan0_stride: int = 64,
        input_mask: int = 0x00FF,
        force_dry_run: bool = False,
        cmac_enable: bool = True,
        diagnostic_ignore_link_gate: bool = False,
        clear_counters: bool = True,
        clock_ref: str | None = PRODUCTION_CLOCK_REF,
        sync_mode: str | None = PRODUCTION_SYNC_MODE,
        force_clock_reconfigure: bool = False,
        require_clock_lock: bool = True,
        require_pps_lock: bool = True,
        start: bool = True,
        settle_s: float = 0.05,
    ) -> dict[str, Any]:
        """Configure the current TIME/SPEC datapath and fixed route geometry."""
        sample_rate_msps = self._normalize_science_sample_rate_msps(sample_rate_msps)
        mode_name, mode_code = self._normalize_science_output_mode(output_mode)
        if mode_code not in (1, 2, 3):
            raise ValueError("the current datapath supports TIME_ONLY, SPEC_ONLY, or TIME_SPEC")
        if sample_rate_msps == 320 and mode_code == self.SCIENCE_OUTPUT_MODES["time_spec"]:
            raise ValueError("TIME_SPEC is unavailable at the high-rate profile")
        if int(time_flow_count) not in (1, 2, 4, 8):
            raise ValueError("time_flow_count must be one of 1, 2, 4, 8")
        if not 0 <= int(time_endpoint_base) < 8:
            raise ValueError("time_endpoint_base must be in range 0..7")
        if int(time_endpoint_base) + int(time_flow_count) > 8:
            raise ValueError("TIME endpoints must stay within 0..7")
        if not 0 <= int(spec_endpoint_base) < self.TX_ENDPOINT_COUNT:
            raise ValueError(f"spec_endpoint_base must be in range 0..{self.TX_ENDPOINT_COUNT - 1}")
        if not 1 <= int(spec_route_count) <= self.TX_SPEC_ROUTE_COUNT:
            raise ValueError(f"spec_route_count must be in range 1..{self.TX_SPEC_ROUTE_COUNT}")
        if int(spec_endpoint_base) + int(spec_route_count) > self.TX_ENDPOINT_COUNT:
            raise ValueError(f"SPEC endpoints must stay within 0..{self.TX_ENDPOINT_COUNT - 1}")
        if int(spec_chan_count) <= 0 or int(spec_time_count) <= 0:
            raise ValueError("SPEC chan/time counts must be positive")
        if int(spec_chan_count) * int(spec_time_count) * 8 * 4 != 8192:
            raise ValueError("SPEC payload must remain 8192 bytes")
        last_chan = (int(spec_route_count) - 1) * int(spec_chan0_stride) + int(spec_chan_count)
        if last_chan > 4096:
            raise ValueError("SPEC route windows must stay within 0..4095")
        if not 1 <= int(input_mask) <= 0x00FF:
            raise ValueError("input_mask must select at least one of the low 8 RFDC lanes")

        clock_result: dict[str, Any] = {"requested": clock_ref, "applied": False, "warning": None}
        sync_result: dict[str, Any] = {"requested": sync_mode, "applied": False, "warning": None}
        if sync_mode is not None or clock_ref is not None:
            try:
                status = self.read_status()
                if int(status.get("armed", 0)) or int(status.get("streaming", 0)) or int(status.get("arm_latched", 0)):
                    self.stop()
                    time.sleep(max(float(settle_s), 0.0))
                    self.reset()
                    time.sleep(max(float(settle_s), 0.0))
                if clock_ref is not None:
                    if bool(force_clock_reconfigure):
                        clock_status = self.configure_clock(ref=str(clock_ref))
                    else:
                        self._write_sync_config(clock_ref=self.CLOCK_REFS[str(clock_ref)])
                        self.clock_reference = str(clock_ref)
                        clock_status = self.clock.read_status(include_registers=False)
                        self.clock_status = dict(clock_status)
                    status_after_clock_ref = self.read_status()
                    if bool(require_clock_lock) and not int(status_after_clock_ref.get("ref_status_locked", 0)):
                        raise RuntimeError(
                            f"RFDC_CLOCK_LOCK_FAILED: {clock_ref} ref_status_locked=0 status={status_after_clock_ref}"
                        )
                    clock_result["applied"] = True
                    clock_result["status"] = dict(clock_status) if isinstance(clock_status, Mapping) else clock_status
                if sync_mode is not None:
                    self.set_sync_mode(str(sync_mode))
                    sync_result["applied"] = True
                    if str(sync_mode).lower() == "external_pps" and bool(require_pps_lock):
                        pps_wait = self.wait_for_pps_increment(timeout=2.0)
                        sync_result["pps_wait"] = pps_wait
                        if not bool(pps_wait.get("ok", False)):
                            raise RuntimeError(f"EXTERNAL_PPS_NOT_SEEN: {pps_wait}")
            except Exception as exc:
                message = f"{type(exc).__name__}: {exc}"
                sync_result["warning"] = message
                clock_result["warning"] = message
                raise

        active_input_mask = int(input_mask) & 0x00FF
        adc_active_mask = self.complex_input_mask_to_adc_active_mask(active_input_mask)
        current_active_mask = int(self.ctrl.read(self.regs.RFDC_ACTIVE_MASK)) & 0xFFFF
        if current_active_mask != adc_active_mask:
            self.set_adc_active_mask(adc_active_mask)

        estimate = self.estimate_science_payload_rate(sample_rate_msps, mode_code)
        sample_rate_code = int(estimate["sample_rate_code"])
        sample_rate_hz = float(estimate["sample_rate_hz"])
        flow_count = int(time_flow_count)
        spec_count = int(spec_route_count)
        time_base = int(time_endpoint_base)
        spec_base = int(spec_endpoint_base)
        time_dst_base = int(time_dst_port_base)
        spec_dst_base = int(spec_dst_port_base)
        time_src_base = int(time_src_port_base)
        spec_src_base = int(spec_src_port_base)
        for base, count, label in (
            (time_dst_base, flow_count, "TIME dst"),
            (time_src_base, flow_count, "TIME src"),
            (spec_dst_base, spec_count, "SPEC dst"),
            (spec_src_base, spec_count, "SPEC src"),
        ):
            if base < 0 or base + count - 1 > 0xFFFF:
                raise ValueError(f"{label} UDP port range must fit in 16 bits")

        self.ctrl.write(self.regs.SRC_IP, _ipv4_to_int(src_ip))
        src_lo, src_hi = _mac_to_parts(src_mac)
        self.ctrl.write(self.regs.SRC_MAC_LO, src_lo)
        self.ctrl.write(self.regs.SRC_MAC_HI, src_hi)
        self.ctrl.write(self.regs.SRC_UDP_PORT, time_src_base & 0xFFFF)
        self.ctrl.write(self.regs.TIME_DST_IP, _ipv4_to_int(dst_ip))
        self.ctrl.write(self.regs.TIME_UDP_PORT, time_dst_base & 0xFFFF)

        time_flows: list[dict[str, Any]] = []
        for flow_id in range(flow_count):
            endpoint_id = time_base + flow_id
            self._write_tx_endpoint(
                endpoint_id,
                enable=True,
                ip=str(dst_ip),
                mac=str(dst_mac),
                dst_port=time_dst_base + flow_id,
                src_port=time_src_base + flow_id,
            )
            time_flows.append(
                {
                    "flow_id": flow_id,
                    "endpoint_id": endpoint_id,
                    "dst_port": time_dst_base + flow_id,
                    "src_port": time_src_base + flow_id,
                }
            )

        spec_routes: list[dict[str, Any]] = []
        for route_id in range(spec_count):
            endpoint_id = spec_base + route_id
            chan0 = route_id * int(spec_chan0_stride)
            self._write_tx_endpoint(
                endpoint_id,
                enable=True,
                ip=str(dst_ip),
                mac=str(dst_mac),
                dst_port=spec_dst_base + route_id,
                src_port=spec_src_base + route_id,
            )
            spec_routes.append(
                {
                    "id": route_id,
                    "endpoint_id": endpoint_id,
                    "chan0": chan0,
                    "chan_count": int(spec_chan_count),
                    "dst_port": spec_dst_base + route_id,
                    "src_port": spec_src_base + route_id,
                    "enable": True,
                }
            )

        self.configure_time_routes(
            [{"id": 0, "endpoint_id": time_base, "input_mask": active_input_mask, "enable": True}],
            clear_unlisted=True,
        )
        self.configure_spec_routes(spec_routes, clear_unlisted=True)
        self.ctrl.write(
            self.regs.SCIENCE_TIME_MULTIFLOW_CONTROL,
            (0x1 if flow_count > 1 else 0x0)
            | ((time_base & 0x7) << 8)
            | ((flow_count & 0xF) << 16),
        )
        self.configure_channelizer(
            nchan=4096,
            chan0=0,
            chan_count=int(spec_chan_count),
            time_count=int(spec_time_count),
            enable=True,
        )

        self.ctrl.write(self.regs.TIME_PAYLOAD_NSAMP, int(time_payload_nsamp) & 0xFFFF)
        self.ctrl.write(self.regs.SCIENCE_TIME_LIVE_INTERVAL_BEATS, int(time_live_interval_beats) & 0xFFFF_FFFF)
        self.ctrl.write(self.regs.SCIENCE_SAMPLE_RATE_MODE, sample_rate_code)
        self.ctrl.write(self.regs.SCIENCE_OUTPUT_MODE, mode_code)
        self.ctrl.write(self.regs.SCIENCE_SAMPLE_RATE_HZ, int(round(sample_rate_hz)))
        self.ctrl.write(self.regs.SCIENCE_DECIM_FACTOR, int(estimate["pl_decim_factor"]))
        self.ctrl.write(self.regs.SCIENCE_PAYLOAD_RATE_MBPS, int(round(float(estimate["payload_mbps"]))))
        science_control = (
            (0x1 if force_dry_run else 0x0)
            | (0x2 if cmac_enable else 0x0)
            | (0x4 if not force_dry_run else 0x0)
        )
        self.ctrl.write(self.regs.SCIENCE_CONTROL, science_control)
        self.ctrl.write(self.regs.SAMPLE_RATE_HZ, int(round(sample_rate_hz)))
        self.set_mode("time" if mode_code == 1 else "spec" if mode_code == 2 else "dual")
        self.configure_tx_control(
            force_dry_run=bool(force_dry_run),
            cmac_enable=bool(cmac_enable),
            frame_builder_enable=True,
            drop_on_route_miss=True,
            diagnostic_ignore_link_gate=bool(diagnostic_ignore_link_gate),
            clear_counters=bool(clear_counters),
        )
        if start:
            self.start()
            time.sleep(max(float(settle_s), 0.0))

        return {
            "implementation": "current",
            "sample_rate_msps": sample_rate_msps,
            "science_output_mode": mode_name,
            "src_ip": str(src_ip),
            "src_mac": str(src_mac),
            "dst_ip": str(dst_ip),
            "dst_mac": str(dst_mac),
            "time_flows": time_flows,
            "spec_routes": spec_routes,
            "time_endpoint_base": time_base,
            "time_flow_count": flow_count,
            "spec_endpoint_base": spec_base,
            "spec_route_count": spec_count,
            "time_dst_port_base": time_dst_base,
            "time_src_port_base": time_src_base,
            "spec_dst_port_base": spec_dst_base,
            "spec_src_port_base": spec_src_base,
            "time_payload_nsamp": int(time_payload_nsamp),
            "time_live_interval_beats": int(time_live_interval_beats),
            "spec_chan_count": int(spec_chan_count),
            "spec_time_count": int(spec_time_count),
            "spec_chan0_stride": int(spec_chan0_stride),
            "input_mask": active_input_mask,
            "rfdc_active_mask": adc_active_mask,
            "force_dry_run": bool(force_dry_run),
            "cmac_enable": bool(cmac_enable),
            "diagnostic_ignore_link_gate": bool(diagnostic_ignore_link_gate),
            "clear_counters": bool(clear_counters),
            "clock": clock_result,
            "sync": sync_result,
            "started": bool(start),
            "estimate": estimate,
            "science_status": self.read_science_output_status(),
            "tx_status": self.read_tx_status(),
            "channelizer_status": self.read_channelizer_status(),
        }

    @staticmethod
    def generate_default_pfb_coefficients(*, nchan: int = 4096, taps: int = 8) -> list[int]:
        """Generate the fixed tap-major 8-tap Hamming PFB profile in signed Q1.17."""
        if int(nchan) != 4096:
            raise ValueError("default coefficients require nchan=4096")
        if int(taps) != 8:
            raise ValueError("the current PFB supports exactly 8 taps")
        total = int(nchan) * int(taps)
        center = (total - 1) / 2.0
        coeff_by_tap = [[0 for _ in range(int(nchan))] for _ in range(int(taps))]
        for phase in range(int(nchan)):
            values: list[float] = []
            for tap in range(int(taps)):
                sample = tap * int(nchan) + phase
                x = (sample - center) / float(nchan)
                sinc = 1.0 if abs(x) < 1.0e-15 else math.sin(math.pi * x) / (math.pi * x)
                window = 0.54 - 0.46 * math.cos((2.0 * math.pi * sample) / float(total - 1))
                values.append(sinc * window)
            phase_sum = sum(values)
            if abs(phase_sum) < 1.0e-18:
                raise ValueError(f"PFB coefficient phase {phase} has near-zero normalization")
            quantized = [
                max(-131_072, min(131_071, int(round((value / phase_sum) * 131_072.0))))
                for value in values
            ]
            delta = 131_072 - sum(quantized)
            while delta:
                moved = False
                for idx in sorted(range(int(taps)), key=lambda i: abs(values[i]), reverse=True):
                    if delta > 0 and quantized[idx] < 131_071:
                        step = min(delta, 131_071 - quantized[idx])
                        quantized[idx] += step
                        delta -= step
                        moved = True
                    elif delta < 0 and quantized[idx] > -131_072:
                        step = min(-delta, quantized[idx] + 131_072)
                        quantized[idx] -= step
                        delta += step
                        moved = True
                    if delta == 0:
                        break
                if not moved:
                    raise ValueError(f"PFB coefficient phase {phase} cannot be quantized to unity sum")
            if sum(quantized) != 131_072:
                raise ValueError(f"PFB coefficient phase {phase} quantized sum is not unity")
            for tap, value in enumerate(quantized):
                coeff_by_tap[tap][phase] = int(value)
        return [coeff_by_tap[tap][phase] for tap in range(int(taps)) for phase in range(int(nchan))]

    @staticmethod
    def pfb_coefficients_crc32(coefficients: Iterable[int]) -> int:
        """Return IEEE/zlib CRC32 over tap-major little-endian coefficient words."""
        crc32 = 0
        count = 0
        for coeff in coefficients:
            value = int(coeff)
            if value < -131_072 or value > 131_071:
                raise ValueError(f"PFB coefficient {count} out of signed Q1.17 range: {value}")
            crc32 = zlib.crc32((value & 0x3FFFF).to_bytes(4, "little"), crc32)
            count += 1
        if count != 32_768:
            raise ValueError(f"current 8-tap PFB requires 32768 coefficients, got {count}")
        return crc32 & 0xFFFF_FFFF

    @staticmethod
    def pfb_coefficients_checksum(coefficients: Iterable[int]) -> int:
        """Deprecated compatibility alias for :meth:`pfb_coefficients_crc32`."""
        return T510FEngine.pfb_coefficients_crc32(coefficients)

    def load_pfb_coefficients(
        self,
        coefficients: Iterable[int] | None = None,
        *,
        coeff_id: int = 0x34A8_0001,
        stop_first: bool = True,
        verify: bool = True,
        settle_s: float = 0.01,
    ) -> dict[str, Any]:
        """Load the fixed 8-tap PFB profile into the shadow bank and commit while idle."""
        coeffs = list(coefficients) if coefficients is not None else self.generate_default_pfb_coefficients()
        crc32 = self.pfb_coefficients_crc32(coeffs)
        if stop_first:
            self.stop()
            time.sleep(max(float(settle_s), 0.0))
        self.ctrl.write(self.regs.PFB_COEFF_ID, int(coeff_id) & 0xFFFF_FFFF)
        self.ctrl.write(self.regs.PFB_COEFF_CONTROL, (8 << 4) | (1 << 3) | 0x1)
        self.ctrl.write(self.regs.PFB_COEFF_INDEX, 0)
        for coeff in coeffs:
            self.ctrl.write(self.regs.PFB_COEFF_DATA, int(coeff) & 0x3FFFF)
        loaded_count = int(self.ctrl.read(self.regs.PFB_COEFF_LOADED_COUNT))
        status_before_commit = self.read_channelizer_status()
        self.ctrl.write(self.regs.PFB_COEFF_CONTROL, (8 << 4) | (1 << 3) | 0x2)
        deadline = time.monotonic() + 2.0
        status_after_commit = self.read_channelizer_status()
        while time.monotonic() < deadline:
            status_after_commit = self.read_channelizer_status()
            if int(status_after_commit.get("pfb_coeff_active_valid", 0)):
                break
            time.sleep(0.01)
        if verify:
            if loaded_count != 32_768:
                raise RuntimeError(f"PFB coefficient load count mismatch: {loaded_count} != 32768")
            if not int(status_after_commit.get("pfb_coeff_active_valid", 0)):
                raise RuntimeError("PFB coefficient commit did not make an active bank valid")
            if int(status_after_commit.get("pfb_coeff_active_taps", 0)) != 8:
                raise RuntimeError(f"PFB active taps mismatch: {status_after_commit.get('pfb_coeff_active_taps')}")
            if int(status_after_commit.get("pfb_coeff_active_id", 0)) != (int(coeff_id) & 0xFFFF_FFFF):
                raise RuntimeError("PFB active coefficient id mismatch")
            if int(status_after_commit.get("pfb_coeff_crc32", 0)) != crc32:
                raise RuntimeError(
                    f"PFB coefficient CRC32 mismatch: 0x{int(status_after_commit.get('pfb_coeff_crc32', 0)):08x} != 0x{crc32:08x}"
                )
            if int(status_after_commit.get("pfb_coeff_error_count", 0)) != 0:
                raise RuntimeError(f"PFB coefficient command errors: {status_after_commit.get('pfb_coeff_error_count')}")
        return {
            "coeff_id": int(coeff_id) & 0xFFFF_FFFF,
            "coeff_count": len(coeffs),
            "crc32": crc32,
            "checksum": crc32,
            "loaded_count": loaded_count,
            "status_before_commit": status_before_commit,
            "status_after_commit": status_after_commit,
        }

    def configure_science(
        self,
        *,
        sample_rate_msps: int | float | str = 160,
        output_mode: str | int = "time_spec",
        dst_ip: str = "10.0.1.16",
        dst_mac: str = "08:c0:eb:d5:95:b2",
        src_ip: str = "10.0.1.1",
        src_mac: str = "02:00:00:00:00:01",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Configure one of the five Stage 34 production profiles.

        Wire layout, port allocation, flow counts, PFB layout, synchronization
        policy, and diagnostic controls remain fixed.  The board-global CMAC
        source IP/MAC are production configuration; endpoint source ports are
        applied by :class:`FEngineController` after this base profile.
        """
        mode_name, mode_code = self._normalize_science_output_mode(output_mode)
        sample_rate_msps = self._normalize_science_sample_rate_msps(sample_rate_msps)
        allowed = {
            (160, self.SCIENCE_OUTPUT_MODES["time_only"]),
            (160, self.SCIENCE_OUTPUT_MODES["spec_only"]),
            (160, self.SCIENCE_OUTPUT_MODES["time_spec"]),
            (320, self.SCIENCE_OUTPUT_MODES["time_only"]),
            (320, self.SCIENCE_OUTPUT_MODES["spec_only"]),
        }
        if (sample_rate_msps, mode_code) not in allowed:
            raise ValueError(
                "Stage 34 production supports 160MS/s TIME_ONLY/SPEC_ONLY/TIME_SPEC "
                "and 320MS/s TIME_ONLY/SPEC_ONLY"
            )
        normalized_src_ip = _normalize_unicast_ipv4(src_ip)
        normalized_src_mac = _normalize_unicast_mac(src_mac)
        forbidden = {
            "time_dst_port_base", "spec_dst_port_base",
            "time_src_port_base", "spec_src_port_base", "time_endpoint_base",
            "spec_endpoint_base", "time_flow_count", "spec_route_count",
            "spec_chan_count", "spec_time_count", "spec_chan0_stride",
            "input_mask", "pfb_fft_shift", "pfb_coeff_id", "clock_ref",
            "sync_mode", "diagnostic_ignore_link_gate",
        }
        supplied = sorted(forbidden.intersection(kwargs))
        if supplied:
            raise ValueError(f"Stage 34 fixed production parameters cannot be overridden: {supplied}")
        unexpected = sorted(set(kwargs).difference({"start", "clear_counters"}))
        if unexpected:
            raise ValueError(f"unsupported Stage 34 production parameters: {unexpected}")

        start_requested = bool(kwargs.pop("start", True))
        active_clock_ref = str(
            getattr(self, "clock_reference", self.PRODUCTION_CLOCK_REF)
        )
        if active_clock_ref not in self.CLOCK_REFS:
            raise RuntimeError(
                f"active production clock reference is invalid: {active_clock_ref!r}"
            )
        active_sync_mode = str(
            getattr(self, "sync_mode", self.PRODUCTION_SYNC_MODE)
        )
        if active_sync_mode not in self.SYNC_MODES:
            raise RuntimeError(
                f"active production sync mode is invalid: {active_sync_mode!r}"
            )
        result = self._configure_science_data_path(
            sample_rate_msps=sample_rate_msps,
            output_mode=mode_name,
            dst_ip=str(dst_ip),
            dst_mac=str(dst_mac),
            src_ip=normalized_src_ip,
            src_mac=normalized_src_mac,
            time_dst_port_base=4300,
            spec_dst_port_base=4308,
            time_src_port_base=4000,
            spec_src_port_base=4008,
            time_endpoint_base=0,
            spec_endpoint_base=8,
            time_flow_count=8,
            spec_route_count=16,
            spec_chan_count=256,
            spec_time_count=1,
            spec_chan0_stride=256,
            input_mask=0x00FF,
            clock_ref=active_clock_ref,
            sync_mode=active_sync_mode,
            diagnostic_ignore_link_gate=False,
            start=False,
            **kwargs,
        )
        expects_time = mode_code in (
            self.SCIENCE_OUTPUT_MODES["time_only"],
            self.SCIENCE_OUTPUT_MODES["time_spec"],
        )
        expects_spec = mode_code in (
            self.SCIENCE_OUTPUT_MODES["spec_only"],
            self.SCIENCE_OUTPUT_MODES["time_spec"],
        )
        if not expects_time:
            self.configure_time_routes([], clear_unlisted=True)
        if not expects_spec:
            self.configure_spec_routes([], clear_unlisted=True)

        coeff_result = None
        if expects_spec:
            coeff_result = self.load_pfb_coefficients(
                None,
                coeff_id=0x34A8_0001,
                stop_first=True,
            )
            self.ctrl.write(self.regs.PFB_TAPS, 8)
            self.ctrl.write(self.regs.PFB_FFT_SHIFT, self.FENGINE_FFT_ONLY_DEFAULT_FFT_SHIFT)
            self.ctrl.write(self.regs.PFB_CONTROL, 0x3)
        else:
            self.ctrl.write(self.regs.PFB_CONTROL, 0x0)

        if start_requested:
            self.start()
            time.sleep(0.05)

        rate_scale = 0.5 if sample_rate_msps == 160 else 1.0
        result.update(
            {
                "science_status": self.read_science_output_status(),
                "tx_status": self.read_tx_status(),
                "channelizer_status": self.read_channelizer_status(),
                "stage": 34,
                "science_product": "FENGINE_IQ16_COMPLEX_VOLTAGE_8TAP_RTL_PFB",
                "production_scope": dict(self.PRODUCTION_SCOPE),
                "convergence_target": "STAGE34_FIVE_PRODUCTION_COMBINATIONS_FULL_RATE_BOARD_AND_HOST",
                "fengine_nchan": 4096,
                "fengine_taps": 8 if expects_spec else None,
                "fengine_fft_shift": self.FENGINE_FFT_ONLY_DEFAULT_FFT_SHIFT if expects_spec else None,
                "fft_only": False,
                "pfb_coefficients": coeff_result,
                "time_ports": "4300..4307",
                "spec_ports": "4308..4323",
                "host_flow_count": (8 if expects_time else 0) + (16 if expects_spec else 0),
                "expected_packet_rates": {
                    "time_pps": 1_250_000.0 * rate_scale if expects_time else 0.0,
                    "spec_pps": 1_250_000.0 * rate_scale if expects_spec else 0.0,
                    "combined_t510_udp_payload_mbps": 83_200.0 * rate_scale * (2.0 if expects_time and expects_spec else 1.0),
                },
                "payload_contract": {
                    "product": "FENGINE_IQ16",
                    "nchan": 4096,
                    "block_count": 16,
                    "chan_count": 256,
                    "time_count": 1,
                    "ninput": 8,
                    "iq_bits": 16,
                    "payload_bytes": 8192,
                    "pfb_taps": 8,
                },
                "started": bool(start_requested),
            }
        )
        return result

    def _wait_measurement_ready(
        self,
        *,
        expects_time: bool,
        expects_spec: bool,
        timeout_s: float,
        poll_s: float = 0.05,
    ) -> dict[str, Any]:
        start = self.read_status()
        start_time_packets = int(start.get("time_packet_count", 0))
        start_spec_packets = int(start.get("spec_packet_count", 0))
        deadline = time.monotonic() + max(float(timeout_s), 0.0)
        last_status = start
        last_tx = self.read_tx_status()
        while time.monotonic() <= deadline:
            status = self.read_status()
            tx = self.read_tx_status()
            time_delta = self._counter_delta(status.get("time_packet_count", 0), start_time_packets)
            spec_delta = self._counter_delta(status.get("spec_packet_count", 0), start_spec_packets)
            tx_ready = (
                bool(int(tx.get("gt_locked", 0)))
                and bool(int(tx.get("cmac_reset_done", 0)))
                and bool(int(tx.get("cmac_tx_ready", 0)))
                and bool(int(tx.get("cmac_enable", 0)))
                and not bool(int(tx.get("tx_local_fault", 0)))
                and not bool(int(tx.get("tx_remote_fault", 0)))
                and not bool(int(tx.get("udp_dry_run_active", 1)))
            )
            packet_ready = (not expects_time or time_delta > 0) and (not expects_spec or spec_delta > 0)
            if bool(int(status.get("streaming", 0))) and tx_ready and packet_ready:
                return {
                    "ok": True,
                    "elapsed_s": max(float(timeout_s) - max(deadline - time.monotonic(), 0.0), 0.0),
                    "time_packet_delta": int(time_delta),
                    "spec_packet_delta": int(spec_delta),
                    "status": status,
                    "tx_status": tx,
                }
            last_status = status
            last_tx = tx
            time.sleep(max(float(poll_s), 0.001))
        return {
            "ok": False,
            "timeout_s": float(timeout_s),
            "time_packet_delta": int(self._counter_delta(last_status.get("time_packet_count", 0), start_time_packets)),
            "spec_packet_delta": int(self._counter_delta(last_status.get("spec_packet_count", 0), start_spec_packets)),
            "status": last_status,
            "tx_status": last_tx,
        }

    def run_production_validation(
        self,
        *,
        configure: bool = True,
        sample_rate_msps: int | float | str = 160,
        output_mode: str | int = "time_spec",
        seconds: float = 10.0,
        measurement_ready_timeout_s: float = 10.0,
        **config_kwargs: Any,
    ) -> dict[str, Any]:
        """Run the Stage 34 board gate for any production profile."""
        expected_core_version = 0x0001_0034
        mode_name, mode_code = self._normalize_science_output_mode(output_mode)
        sample_rate_msps = self._normalize_science_sample_rate_msps(sample_rate_msps)
        allowed = {
            (160, self.SCIENCE_OUTPUT_MODES["time_only"]),
            (160, self.SCIENCE_OUTPUT_MODES["spec_only"]),
            (160, self.SCIENCE_OUTPUT_MODES["time_spec"]),
            (320, self.SCIENCE_OUTPUT_MODES["time_only"]),
            (320, self.SCIENCE_OUTPUT_MODES["spec_only"]),
        }
        if (sample_rate_msps, mode_code) not in allowed:
            raise ValueError(
                "Stage 34 production supports 160MS/s TIME_ONLY/SPEC_ONLY/TIME_SPEC "
                "and 320MS/s TIME_ONLY/SPEC_ONLY"
            )

        start_requested = bool(config_kwargs.pop("start", True))
        config = None
        if configure:
            config = self.configure_science(
                sample_rate_msps=sample_rate_msps,
                output_mode=mode_name,
                start=False,
                **config_kwargs,
            )
            config_kwargs = {}
        elif config_kwargs:
            raise ValueError(f"unused Stage 34 config kwargs when configure=False: {sorted(config_kwargs)}")

        expects_time = mode_code in (
            self.SCIENCE_OUTPUT_MODES["time_only"],
            self.SCIENCE_OUTPUT_MODES["time_spec"],
        )
        expects_spec = mode_code in (
            self.SCIENCE_OUTPUT_MODES["spec_only"],
            self.SCIENCE_OUTPUT_MODES["time_spec"],
        )
        ready_before_measurement = None
        if start_requested:
            self.start()
            ready_before_measurement = self._wait_measurement_ready(
                expects_time=expects_time,
                expects_spec=expects_spec,
                timeout_s=float(measurement_ready_timeout_s),
            )

        before = self.read_status()
        time.sleep(max(float(seconds), 0.0))
        after = self.read_status()
        tx_live = self.read_tx_status()
        tx_after = self._prefer_coherent_live_tx_status(
            self._tx_status_from_status_snapshot(after, tx_live),
            tx_live,
        )
        science = self.read_science_output_status()
        channelizer = self.read_channelizer_status()
        time_routes = self.read_time_route_table()
        spec_routes = self.read_spec_route_table()
        counter_keys = (
            "time_packet_count", "spec_packet_count", "time_dropped_count",
            "spec_dropped_count", "rfdc_dropped_count", "science_dropped_beat_count",
            "tx_route_miss_count", "tx_route_error_count", "pfb_overflow_count",
            "pfb_data_halt_count", "pfb_xfft_event_count", "pfb_tile_overflow_count",
            "pfb_xfft_tlast_unexpected_count", "pfb_xfft_tlast_missing_count",
            "pfb_xfft_fft_overflow_count", "pfb_xfft_data_out_halt_count",
            "pfb_xfft_status_halt_count", "pfb_capture_backpressure_count",
            "pfb_frame_sample0_overflow_count", "pfb_coeff_error_count",
        )
        deltas = {key: self._counter_delta(after.get(key, 0), before.get(key, 0)) for key in counter_keys}
        elapsed = max(float(seconds), 1.0e-6)
        rates = {
            "time_pps": float(deltas["time_packet_count"]) / elapsed,
            "spec_pps": float(deltas["spec_packet_count"]) / elapsed,
        }
        rates["combined_t510_udp_payload_mbps"] = (
            float(deltas["time_packet_count"] + deltas["spec_packet_count"])
            * 8320.0 * 8.0 / elapsed / 1_000_000.0
        )
        errors: list[str] = []
        blockers: list[str] = []

        if int(after.get("core_version", 0)) != int(expected_core_version):
            errors.append(
                f"WRONG_CORE_VERSION expected 0x{int(expected_core_version):08x} "
                f"got 0x{int(after.get('core_version', 0)):08x}"
            )
        expected_clock_ref = str(
            getattr(self, "clock_reference", self.PRODUCTION_CLOCK_REF)
        )
        if int(after.get("configured_clock_ref", -1)) != self.CLOCK_REFS[expected_clock_ref]:
            errors.append("WRONG_CLOCK_REF")
        expected_sync_mode = str(
            getattr(self, "sync_mode", self.PRODUCTION_SYNC_MODE)
        )
        production_sync = self.SYNC_MODES[expected_sync_mode]
        if int(after.get("configured_sync_mode", -1)) != production_sync or int(after.get("active_sync_mode", -1)) != production_sync:
            errors.append("WRONG_SYNC_MODE")
        if expected_sync_mode == "external_pps" and (
            not int(after.get("pps_recent", 0))
            or int(after.get("pps_count", 0)) <= 0
        ):
            errors.append("EXTERNAL_PPS_NOT_READY")
        if int(science.get("science_sample_rate_msps", 0)) != sample_rate_msps:
            errors.append("SCIENCE_SAMPLE_RATE_MISMATCH")
        if bool(int(science.get("time_enabled", 0))) != expects_time:
            errors.append("TIME_ENABLE_MISMATCH")
        if bool(int(science.get("spec_enabled", 0))) != expects_spec:
            errors.append("SPEC_ENABLE_MISMATCH")
        halfband_expected = sample_rate_msps == 160
        halfband_active = bool(int(science.get("halfband_active", 0)))
        halfband_primed = bool(int(science.get("halfband_primed", 0)))
        if halfband_active != halfband_expected:
            errors.append("HALFBAND_ACTIVE_MISMATCH")
        if halfband_expected and not halfband_primed:
            errors.append("HALFBAND_NOT_PRIMED")
        if (
            int(science.get("halfband_taps", 0)) != 55
            or int(science.get("halfband_coeff_id", 0)) != 0xAA16_0055
        ):
            errors.append("HALFBAND_CONTRACT_MISMATCH")

        for key, label in (
            ("gt_locked", "GT_NOT_LOCKED"),
            ("cmac_reset_done", "CMAC_RESET_NOT_DONE"),
            ("cmac_tx_ready", "CMAC_TX_NOT_READY"),
        ):
            if not int(tx_after.get(key, 0)):
                blockers.append(label)
        if int(tx_after.get("tx_local_fault", 0)) or int(tx_after.get("tx_remote_fault", 0)):
            blockers.append("CMAC_FAULT")
        if int(tx_after.get("udp_dry_run_active", 1)) or not int(tx_after.get("cmac_enable", 0)):
            errors.append("CMAC_LIVE_TX_NOT_ENABLED")

        zero_delta = {
            "time_dropped_count", "spec_dropped_count", "rfdc_dropped_count",
            "science_dropped_beat_count", "tx_route_miss_count", "tx_route_error_count",
            "pfb_overflow_count", "pfb_data_halt_count", "pfb_xfft_event_count",
            "pfb_tile_overflow_count", "pfb_xfft_tlast_unexpected_count",
            "pfb_xfft_tlast_missing_count", "pfb_xfft_fft_overflow_count",
            "pfb_xfft_data_out_halt_count", "pfb_xfft_status_halt_count",
            "pfb_capture_backpressure_count", "pfb_frame_sample0_overflow_count",
            "pfb_coeff_error_count",
        }
        for key in sorted(zero_delta):
            if deltas[key] != 0:
                errors.append(f"NONZERO_{key.upper()}")
        if not expects_spec and deltas["spec_packet_count"] != 0:
            errors.append("SPEC_PACKETS_PRESENT_IN_TIME_ONLY")
        if not expects_time and deltas["time_packet_count"] != 0:
            errors.append("TIME_PACKETS_PRESENT_IN_SPEC_ONLY")
        pps_min = 593_750.0 if sample_rate_msps == 160 else 1_187_500.0
        payload_mbps_min = pps_min * (int(expects_time) + int(expects_spec)) * 8320.0 * 8.0 / 1_000_000.0
        if expects_time and rates["time_pps"] < pps_min:
            errors.append(f"TIME_PPS_LOW {rates['time_pps']:.3f} < {pps_min:.3f}")
        if expects_spec and rates["spec_pps"] < pps_min:
            errors.append(f"SPEC_PPS_LOW {rates['spec_pps']:.3f} < {pps_min:.3f}")
        if rates["combined_t510_udp_payload_mbps"] < payload_mbps_min:
            errors.append(
                "COMBINED_T510_UDP_PAYLOAD_LOW "
                f"{rates['combined_t510_udp_payload_mbps']:.3f} < {payload_mbps_min:.3f}"
            )

        enabled_time = [route for route in time_routes if int(route.get("enable", 0))]
        enabled_spec = [route for route in spec_routes if int(route.get("enable", 0))]
        if expects_time:
            if len(enabled_time) != 8 or any(int(route.get("hit_count", 0)) == 0 for route in enabled_time):
                errors.append("TIME_ROUTE_CONTRACT_FAILED")
        elif enabled_time:
            errors.append("TIME_ROUTE_ENABLED_IN_SPEC_ONLY")
        if expects_spec:
            if len(enabled_spec) != 16 or any(int(route.get("hit_count", 0)) == 0 for route in enabled_spec):
                errors.append("SPEC_ROUTE_CONTRACT_FAILED")
            if not int(science.get("fengine_science_valid", 0)):
                errors.append("FENGINE_SCIENCE_NOT_VALID")
            for condition, label in (
                (int(channelizer.get("pfb_taps", -1)) != 8, "PFB_TAPS_NOT_8"),
                (not int(channelizer.get("pfb_active", 0)), "PFB_NOT_ACTIVE"),
                (not int(channelizer.get("pfb_coeff_active_valid", 0)), "PFB_COEFF_NOT_VALID"),
                (int(channelizer.get("pfb_chan_count", 0)) != 256, "PFB_CHAN_COUNT_NOT_256"),
                (int(channelizer.get("pfb_time_count", 0)) != 1, "PFB_TIME_COUNT_NOT_1"),
            ):
                if condition:
                    errors.append(label)
        else:
            if enabled_spec:
                errors.append("SPEC_ROUTE_ENABLED_IN_TIME_ONLY")
            if int(channelizer.get("pfb_active", 0)):
                errors.append("PFB_ACTIVE_IN_TIME_ONLY")

        ok = not errors and not blockers
        return {
            "classification": f"STAGE34_{sample_rate_msps}MSPS_{mode_name}_BOARD_{'PASS' if ok else 'FAIL'}",
            "ok": ok,
            "full_science_validated": ok,
            "stage": 34,
            "production_scope": dict(self.PRODUCTION_SCOPE),
            "convergence_target": "STAGE34_FIVE_PRODUCTION_COMBINATIONS_FULL_RATE_BOARD_AND_HOST",
            "host_receiver_required": True,
            "expected_core_version": f"0x{int(expected_core_version):08x}",
            "sample_rate_msps": sample_rate_msps,
            "output_mode": mode_name,
            "required_rates": {
                "time_pps_min": pps_min if expects_time else 0.0,
                "spec_pps_min": pps_min if expects_spec else 0.0,
                "combined_t510_udp_payload_mbps_min": payload_mbps_min,
            },
            "config": config,
            "ready_before_measurement": ready_before_measurement,
            "before": before,
            "after": after,
            "tx_after": tx_after,
            "science_after": science,
            "channelizer_after": channelizer,
            "spec_routes": spec_routes,
            "time_routes": time_routes,
            "deltas": deltas,
            "rates": rates,
            "errors": errors,
            "blockers": blockers,
        }

    def _write_tx_endpoint(
        self,
        endpoint_id: int,
        *,
        enable: bool,
        ip: str,
        mac: str,
        dst_port: int,
        src_port: int,
    ) -> None:
        if not 0 <= endpoint_id < self.TX_ENDPOINT_COUNT:
            raise ValueError(f"endpoint_id must be in range 0..{self.TX_ENDPOINT_COUNT - 1}")
        if not 0 <= int(dst_port) <= 0xFFFF:
            raise ValueError("dst_port must fit in 16 bits")
        if not 0 <= int(src_port) <= 0xFFFF:
            raise ValueError("src_port must fit in 16 bits")
        mac_value = _mac_to_int(mac)
        self.ctrl.write(self.regs.TX_ENDPOINT_INDIRECT_INDEX, endpoint_id)
        self.ctrl.write(self.regs.TX_ENDPOINT_INDIRECT_IP, _ipv4_to_int(ip))
        self.ctrl.write(self.regs.TX_ENDPOINT_INDIRECT_MAC_LO, mac_value & 0xFFFF_FFFF)
        self.ctrl.write(self.regs.TX_ENDPOINT_INDIRECT_MAC_HI, (mac_value >> 32) & 0xFFFF)
        self.ctrl.write(self.regs.TX_ENDPOINT_INDIRECT_DST_PORT, int(dst_port))
        self.ctrl.write(self.regs.TX_ENDPOINT_INDIRECT_SRC_PORT, int(src_port))
        self.ctrl.write(self.regs.TX_ENDPOINT_INDIRECT_ENABLE, 0x1 if enable else 0x0)

    def configure_tx_endpoints(self, endpoints: list[Mapping[str, Any]]) -> None:
        if len(endpoints) > self.TX_ENDPOINT_COUNT:
            raise ValueError(f"current hardware supports at most {self.TX_ENDPOINT_COUNT} TX endpoints")
        for index, endpoint in enumerate(endpoints):
            endpoint_id = int(endpoint.get("id", index))
            enable = bool(endpoint.get("enable", True))
            has_full_config = "ip" in endpoint and "mac" in endpoint and (
                "dst_port" in endpoint or "port" in endpoint
            )
            if not enable and not has_full_config:
                if not 0 <= endpoint_id < self.TX_ENDPOINT_COUNT:
                    raise ValueError(f"endpoint_id must be in range 0..{self.TX_ENDPOINT_COUNT - 1}")
                self.ctrl.write(self.regs.TX_ENDPOINT_INDIRECT_INDEX, endpoint_id)
                self.ctrl.write(self.regs.TX_ENDPOINT_INDIRECT_ENABLE, 0)
                continue
            self._write_tx_endpoint(
                endpoint_id,
                enable=enable,
                ip=str(endpoint["ip"]),
                mac=str(endpoint["mac"]),
                dst_port=int(endpoint.get("dst_port", endpoint.get("port", 4100 + endpoint_id))),
                src_port=int(endpoint.get("src_port", self.ctrl.read(self.regs.SRC_UDP_PORT))),
            )

    def configure_tx_source_identity(self, *, ip: str, mac: str, src_port: int) -> dict[str, Any]:
        """Set and read back the board-global CMAC source identity.

        ``src_port`` is the board-global source-port readback. TIME/SPEC frames
        use the source ports stored in their endpoint table.
        """
        normalized_ip = _normalize_unicast_ipv4(ip)
        normalized_mac = _normalize_unicast_mac(mac)
        port = int(src_port)
        if not 1 <= port <= 0xFFFF:
            raise ValueError("src_port must be within 1..65535")
        self.ctrl.write(self.regs.SRC_IP, _ipv4_to_int(normalized_ip))
        mac_value = _mac_to_int(normalized_mac)
        self.ctrl.write(self.regs.SRC_MAC_LO, mac_value & 0xFFFF_FFFF)
        self.ctrl.write(self.regs.SRC_MAC_HI, (mac_value >> 32) & 0xFFFF)
        self.ctrl.write(self.regs.SRC_UDP_PORT, port)
        return self.read_tx_source_identity()

    def configure_board_id(self, board_id: int) -> int:
        """Set and verify the 16-bit identity carried in every T510 packet."""
        value = int(board_id)
        if not 0 <= value <= 0xFFFF:
            raise ValueError("board_id must be within 0..65535")
        self.ctrl.write(self.regs.BOARD_ID, value)
        readback = int(self.ctrl.read(self.regs.BOARD_ID)) & 0xFFFF
        if readback != value:
            raise RuntimeError(
                f"board_id readback mismatch: requested={value} readback={readback}"
            )
        return readback

    def read_tx_source_identity(self) -> dict[str, Any]:
        ip_value = int(self.ctrl.read(self.regs.SRC_IP)) & 0xFFFF_FFFF
        mac_value = (
            (int(self.ctrl.read(self.regs.SRC_MAC_HI)) & 0xFFFF) << 32
            | (int(self.ctrl.read(self.regs.SRC_MAC_LO)) & 0xFFFF_FFFF)
        )
        return {
            "ip": str(IPv4Address(ip_value)),
            "mac": _mac_from_int(mac_value),
            "src_port": int(self.ctrl.read(self.regs.SRC_UDP_PORT)) & 0xFFFF,
        }

    def read_tx_endpoints(self, endpoint_ids: Iterable[int] | None = None) -> list[dict[str, Any]]:
        ids = range(self.TX_ENDPOINT_COUNT) if endpoint_ids is None else endpoint_ids
        result: list[dict[str, Any]] = []
        for value in ids:
            endpoint_id = int(value)
            if not 0 <= endpoint_id < self.TX_ENDPOINT_COUNT:
                raise ValueError(f"endpoint_id must be in range 0..{self.TX_ENDPOINT_COUNT - 1}")
            self.ctrl.write(self.regs.TX_ENDPOINT_INDIRECT_INDEX, endpoint_id)
            mac_value = (
                (int(self.ctrl.read(self.regs.TX_ENDPOINT_INDIRECT_MAC_HI)) & 0xFFFF) << 32
                | (int(self.ctrl.read(self.regs.TX_ENDPOINT_INDIRECT_MAC_LO)) & 0xFFFF_FFFF)
            )
            result.append({
                "id": endpoint_id,
                "enable": bool(int(self.ctrl.read(self.regs.TX_ENDPOINT_INDIRECT_ENABLE)) & 0x1),
                "ip": str(IPv4Address(int(self.ctrl.read(self.regs.TX_ENDPOINT_INDIRECT_IP)) & 0xFFFF_FFFF)),
                "mac": _mac_from_int(mac_value),
                "dst_port": int(self.ctrl.read(self.regs.TX_ENDPOINT_INDIRECT_DST_PORT)) & 0xFFFF,
                "src_port": int(self.ctrl.read(self.regs.TX_ENDPOINT_INDIRECT_SRC_PORT)) & 0xFFFF,
            })
        return result

    def configure_spec_routes(self, routes: list[Mapping[str, Any]], *, clear_unlisted: bool = True) -> None:
        if len(routes) > self.TX_SPEC_ROUTE_COUNT:
            raise ValueError(f"current hardware supports at most {self.TX_SPEC_ROUTE_COUNT} SPEC routes")
        if clear_unlisted:
            for route_id in range(self.TX_SPEC_ROUTE_COUNT):
                self.ctrl.write(self.regs.TX_SPEC_ROUTE_INDIRECT_INDEX, route_id)
                self.ctrl.write(self.regs.TX_SPEC_ROUTE_INDIRECT_CONTROL, 0)
        for index, route in enumerate(routes):
            route_id = int(route.get("id", index))
            if not 0 <= route_id < self.TX_SPEC_ROUTE_COUNT:
                raise ValueError(f"SPEC route id must be in range 0..{self.TX_SPEC_ROUTE_COUNT - 1}")
            endpoint_id = int(route["endpoint_id"])
            if not 0 <= endpoint_id < self.TX_ENDPOINT_COUNT:
                raise ValueError(f"SPEC route endpoint_id must be in range 0..{self.TX_ENDPOINT_COUNT - 1}")
            chan0 = int(route["chan0"])
            chan_count = int(route["chan_count"])
            if chan0 < 0 or chan_count <= 0 or chan0 + chan_count > 4096:
                raise ValueError("SPEC route channel window must stay within 0..4095")
            self.ctrl.write(self.regs.TX_SPEC_ROUTE_INDIRECT_INDEX, route_id)
            self.ctrl.write(self.regs.TX_SPEC_ROUTE_INDIRECT_CHAN0, chan0)
            self.ctrl.write(self.regs.TX_SPEC_ROUTE_INDIRECT_CHAN_COUNT, chan_count)
            self.ctrl.write(
                self.regs.TX_SPEC_ROUTE_INDIRECT_CONTROL,
                (endpoint_id << 8) | (0x1 if route.get("enable", True) else 0x0),
            )

    def configure_time_routes(self, routes: list[Mapping[str, Any]], *, clear_unlisted: bool = True) -> None:
        if len(routes) > self.TX_TIME_ROUTE_COUNT:
            raise ValueError(f"current hardware supports at most {self.TX_TIME_ROUTE_COUNT} TIME routes")
        if clear_unlisted:
            for route_id in range(self.TX_TIME_ROUTE_COUNT):
                self.ctrl.write(self.regs.TX_TIME_ROUTE_INDIRECT_INDEX, route_id)
                self.ctrl.write(self.regs.TX_TIME_ROUTE_INDIRECT_CONTROL, 0)
                self.ctrl.write(self.regs.TX_TIME_ROUTE_INDIRECT_INPUT_MASK, 0)
        for index, route in enumerate(routes):
            route_id = int(route.get("id", index))
            if not 0 <= route_id < self.TX_TIME_ROUTE_COUNT:
                raise ValueError(f"TIME route id must be in range 0..{self.TX_TIME_ROUTE_COUNT - 1}")
            endpoint_id = int(route["endpoint_id"])
            input_mask = int(route["input_mask"])
            if not 0 <= endpoint_id < self.TX_ENDPOINT_COUNT:
                raise ValueError(f"TIME route endpoint_id must be in range 0..{self.TX_ENDPOINT_COUNT - 1}")
            if not 1 <= input_mask <= 0xFFFF:
                raise ValueError("TIME route input_mask must be in range 0x0001..0xffff")
            self.ctrl.write(self.regs.TX_TIME_ROUTE_INDIRECT_INDEX, route_id)
            self.ctrl.write(self.regs.TX_TIME_ROUTE_INDIRECT_INPUT_MASK, input_mask)
            self.ctrl.write(
                self.regs.TX_TIME_ROUTE_INDIRECT_CONTROL,
                (endpoint_id << 8) | (0x1 if route.get("enable", True) else 0x0),
            )

    def read_spec_route_table(self, count: int | None = None) -> list[dict[str, int]]:
        route_count = self.TX_SPEC_ROUTE_COUNT if count is None else min(int(count), self.TX_SPEC_ROUTE_COUNT)
        routes: list[dict[str, int]] = []
        for route_id in range(route_count):
            self.ctrl.write(self.regs.TX_SPEC_ROUTE_INDIRECT_INDEX, route_id)
            control = int(self.ctrl.read(self.regs.TX_SPEC_ROUTE_INDIRECT_CONTROL))
            routes.append(
                {
                    "id": route_id,
                    "enable": control & 0x1,
                    "endpoint_id": (control >> 8) & 0xFF,
                    "chan0": int(self.ctrl.read(self.regs.TX_SPEC_ROUTE_INDIRECT_CHAN0)),
                    "chan_count": int(self.ctrl.read(self.regs.TX_SPEC_ROUTE_INDIRECT_CHAN_COUNT)) & 0xFFFF,
                    "hit_count": int(self.ctrl.read(self.regs.TX_SPEC_ROUTE_INDIRECT_HIT_COUNT)),
                }
            )
        return routes

    def read_time_route_table(self, count: int | None = None) -> list[dict[str, int]]:
        route_count = self.TX_TIME_ROUTE_COUNT if count is None else min(int(count), self.TX_TIME_ROUTE_COUNT)
        routes: list[dict[str, int]] = []
        for route_id in range(route_count):
            self.ctrl.write(self.regs.TX_TIME_ROUTE_INDIRECT_INDEX, route_id)
            control = int(self.ctrl.read(self.regs.TX_TIME_ROUTE_INDIRECT_CONTROL))
            routes.append(
                {
                    "id": route_id,
                    "enable": control & 0x1,
                    "endpoint_id": (control >> 8) & 0xFF,
                    "input_mask": int(self.ctrl.read(self.regs.TX_TIME_ROUTE_INDIRECT_INPUT_MASK)) & 0xFFFF,
                    "hit_count": int(self.ctrl.read(self.regs.TX_TIME_ROUTE_INDIRECT_HIT_COUNT)),
                }
            )
        return routes

    def read_tx_status(self) -> dict[str, Any]:
        preflight_raw = int(self.ctrl.read(self.regs.TX_STATUS))
        link_raw = int(self.ctrl.read(self.regs.TX_LINK_STATUS_FLAGS))
        selected_route = int(self.ctrl.read(self.regs.TX_SELECTED_ROUTE))
        tx_control = int(self.ctrl.read(self.regs.TX_CONTROL))
        link_up = link_raw & 0x1
        cmac_reset_done = (link_raw >> 2) & 0x1
        gt_locked = (link_raw >> 3) & 0x1
        cmac_tx_ready = (link_raw >> 4) & 0x1
        tx_local_fault = (link_raw >> 5) & 0x1
        tx_remote_fault = (link_raw >> 6) & 0x1
        force_dry_run = tx_control & 0x1
        cmac_enable = (tx_control >> 1) & 0x1
        frame_builder_enabled = (tx_control >> 2) & 0x1
        stable_dry_run = int(
            bool(force_dry_run)
            or not bool(cmac_enable)
            or not bool(frame_builder_enabled)
            or not bool(link_up)
            or not bool(cmac_reset_done)
            or not bool(gt_locked)
            or bool(tx_local_fault)
            or bool(tx_remote_fault)
        )
        status: dict[str, Any] = {
            "tx_control": tx_control,
            "tx_status": preflight_raw,
            "tx_preflight_status": preflight_raw,
            "tx_link_status_flags_raw": link_raw,
            "tx_preflight_qsfp_link_up": preflight_raw & 0x1,
            "tx_preflight_udp_dry_run_active": (preflight_raw >> 1) & 0x1,
            "tx_preflight_cmac_reset_done": (preflight_raw >> 2) & 0x1,
            "tx_preflight_gt_locked": (preflight_raw >> 3) & 0x1,
            "tx_preflight_cmac_tx_ready": (preflight_raw >> 4) & 0x1,
            "qsfp_link_up": link_up,
            "udp_dry_run_active": stable_dry_run,
            "cmac_reset_done": cmac_reset_done,
            "gt_locked": gt_locked,
            "cmac_tx_ready": cmac_tx_ready,
            "tx_local_fault": tx_local_fault,
            "tx_remote_fault": tx_remote_fault,
            "route_miss_sticky": (preflight_raw >> 7) & 0x1,
            "route_error_sticky": (preflight_raw >> 8) & 0x1,
            "frame_builder_enabled": frame_builder_enabled,
            "force_dry_run": force_dry_run,
            "cmac_enable": cmac_enable,
            "qsfp_module_present": (link_raw >> 12) & 0x1,
            "gt_refclk_seen": (link_raw >> 13) & 0x1,
            "gt_tx_reset_done": (link_raw >> 14) & 0x1,
            "gt_rx_reset_done": (link_raw >> 15) & 0x1,
            "tx_underflow": (link_raw >> 16) & 0x1,
            "tx_overflow": (link_raw >> 17) & 0x1,
            "diagnostic_ignore_link_gate": (tx_control >> 4) & 0x1,
            "cmac_rx_aligned": (link_raw >> 18) & 0x1,
            "cmac_rx_status": (link_raw >> 19) & 0x1,
            "cmac_rx_local_fault_detail": (link_raw >> 20) & 0x1,
            "cmac_rx_internal_local_fault": (link_raw >> 21) & 0x1,
            "cmac_tx_local_fault_detail": (link_raw >> 22) & 0x1,
            "cmac_an_autoneg_complete": (link_raw >> 23) & 0x1,
            "cmac_an_lp_ability_valid": (link_raw >> 24) & 0x1,
            "cmac_an_lp_autoneg_able": (link_raw >> 25) & 0x1,
            "cmac_an_lp_ability_100gbase_cr4": (link_raw >> 26) & 0x1,
            "cmac_an_rs_fec_enable": (link_raw >> 27) & 0x1,
            "cmac_lt_signal_detect_all": (link_raw >> 28) & 0x1,
            "cmac_lt_training_any": (link_raw >> 29) & 0x1,
            "cmac_lt_training_fail_any": (link_raw >> 30) & 0x1,
            "cmac_lt_frame_lock_all": (link_raw >> 31) & 0x1,
            "tx_frame_built_count": int(self.ctrl.read(self.regs.TX_FRAME_BUILT_COUNT)),
            "tx_frame_sent_count": int(self.ctrl.read(self.regs.TX_FRAME_SENT_COUNT)),
            "tx_frame_dropped_count": int(self.ctrl.read(self.regs.TX_FRAME_DROPPED_COUNT)),
            "tx_frame_byte_count": int(self.ctrl.read(self.regs.TX_FRAME_BYTE_COUNT)),
            "tx_route_miss_count": int(self.ctrl.read(self.regs.TX_ROUTE_MISS_COUNT)),
            "tx_route_error_count": int(self.ctrl.read(self.regs.TX_ROUTE_ERROR_COUNT)),
            "tx_cmac_accepted_packet_count": int(self.ctrl.read(self.regs.TX_CMAC_ACCEPTED_PACKET_COUNT)),
            "tx_cmac_accepted_byte_count": int(self.ctrl.read(self.regs.TX_CMAC_ACCEPTED_BYTE_COUNT)),
            "tx_selected_endpoint": int(self.ctrl.read(self.regs.TX_SELECTED_ENDPOINT)) & 0xFF,
            "tx_selected_route": selected_route & 0x3F,
            "tx_selected_route_is_time": (selected_route >> 6) & 0x1,
            "qsfp_test_interval_cycles": int(self.ctrl.read(self.regs.QSFP_TEST_INTERVAL_CYCLES)),
            "tx_cmac_source_status": int(self.ctrl.read(self.regs.TX_CMAC_SOURCE_STATUS)),
        }
        source_status = int(status["tx_cmac_source_status"])
        source_mux_raw = (source_status >> 16) & 0xFFFF
        status.update(
            {
                "tx_cmac_mux_selected_source": source_status & 0x3,
                "tx_cmac_mux_selected_heartbeat": 1 if (source_status & 0x3) == 0 else 0,
                "tx_cmac_mux_selected_time": 1 if (source_status & 0x3) == 1 else 0,
                "tx_cmac_mux_selected_spec": 1 if (source_status & 0x3) == 2 else 0,
                "tx_cmac_mux_select_time": (source_mux_raw >> 11) & 0x1,
                "tx_cmac_mux_select_spec": (source_mux_raw >> 12) & 0x1,
                "tx_cmac_heartbeat_enabled": (source_status >> 2) & 0x1,
                "tx_cmac_heartbeat_valid": (source_status >> 3) & 0x1,
                "tx_cmac_time_valid": (source_status >> 4) & 0x1,
                "tx_cmac_idle_bridge_ready": (source_status >> 5) & 0x1,
                "tx_time_live_requested_data": (source_status >> 6) & 0x1,
                "tx_time_live_requested_cmac": (source_status >> 7) & 0x1,
                "tx_spec_live_requested_data": (source_status >> 8) & 0x1,
                "tx_spec_live_requested_cmac": (source_status >> 9) & 0x1,
                "tx_idle_bridge_requested_data": (source_status >> 10) & 0x1,
                "tx_idle_bridge_requested_cmac": (source_status >> 11) & 0x1,
                "tx_idle_bridge_fifo_full": (source_status >> 12) & 0x1,
                "tx_idle_bridge_fifo_empty": (source_status >> 13) & 0x1,
                "tx_time_live_bridge_fifo_full": (source_status >> 14) & 0x1,
                "tx_time_live_bridge_fifo_empty": (source_status >> 15) & 0x1,
                "tx_cmac_source_mux_raw": source_mux_raw,
                "tx_cmac_source_mux_locked": (source_mux_raw >> 4) & 0x1,
            }
        )
        return status

    @staticmethod
    def _tx_status_from_status_snapshot(status: Mapping[str, Any], live: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Build a read_tx_status-shaped view from one read_status() snapshot."""
        result: dict[str, Any] = dict(live or {})
        mapping = {
            "tx_control": "tx_control",
            "tx_status": "tx_status",
            "tx_preflight_status": "tx_preflight_status",
            "tx_link_status_flags_raw": "tx_link_status_flags",
            "tx_preflight_qsfp_link_up": "tx_preflight_qsfp_link_up",
            "tx_preflight_udp_dry_run_active": "tx_preflight_udp_dry_run_active",
            "tx_preflight_cmac_reset_done": "tx_preflight_cmac_reset_done",
            "tx_preflight_gt_locked": "tx_preflight_gt_locked",
            "tx_preflight_cmac_tx_ready": "tx_preflight_cmac_tx_ready",
            "qsfp_link_up": "tx_qsfp_link_up",
            "udp_dry_run_active": "tx_udp_dry_run_active",
            "cmac_reset_done": "tx_cmac_reset_done",
            "gt_locked": "tx_gt_locked",
            "cmac_tx_ready": "tx_cmac_tx_ready",
            "tx_local_fault": "tx_local_fault",
            "tx_remote_fault": "tx_remote_fault",
            "route_miss_sticky": "tx_route_miss_sticky",
            "route_error_sticky": "tx_route_error_sticky",
            "frame_builder_enabled": "tx_frame_builder_enabled",
            "force_dry_run": "tx_force_dry_run",
            "cmac_enable": "tx_cmac_enable",
            "qsfp_module_present": "tx_qsfp_module_present",
            "gt_refclk_seen": "tx_gt_refclk_seen",
            "gt_tx_reset_done": "tx_gt_tx_reset_done",
            "gt_rx_reset_done": "tx_gt_rx_reset_done",
            "tx_underflow": "tx_underflow",
            "tx_overflow": "tx_overflow",
            "diagnostic_ignore_link_gate": "tx_diagnostic_ignore_link_gate",
            "cmac_rx_aligned": "tx_cmac_rx_aligned",
            "cmac_rx_status": "tx_cmac_rx_status",
            "cmac_rx_local_fault_detail": "tx_cmac_rx_local_fault_detail",
            "cmac_rx_internal_local_fault": "tx_cmac_rx_internal_local_fault",
            "cmac_tx_local_fault_detail": "tx_cmac_tx_local_fault_detail",
            "cmac_an_autoneg_complete": "tx_cmac_an_autoneg_complete",
            "cmac_an_lp_ability_valid": "tx_cmac_an_lp_ability_valid",
            "cmac_an_lp_autoneg_able": "tx_cmac_an_lp_autoneg_able",
            "cmac_an_lp_ability_100gbase_cr4": "tx_cmac_an_lp_ability_100gbase_cr4",
            "cmac_an_rs_fec_enable": "tx_cmac_an_rs_fec_enable",
            "cmac_lt_signal_detect_all": "tx_cmac_lt_signal_detect_all",
            "cmac_lt_training_any": "tx_cmac_lt_training_any",
            "cmac_lt_training_fail_any": "tx_cmac_lt_training_fail_any",
            "cmac_lt_frame_lock_all": "tx_cmac_lt_frame_lock_all",
            "tx_frame_built_count": "tx_frame_built_count",
            "tx_frame_sent_count": "tx_frame_sent_count",
            "tx_frame_dropped_count": "tx_frame_dropped_count",
            "tx_frame_byte_count": "tx_frame_byte_count",
            "tx_route_miss_count": "tx_route_miss_count",
            "tx_route_error_count": "tx_route_error_count",
            "tx_cmac_accepted_packet_count": "tx_cmac_accepted_packet_count",
            "tx_cmac_accepted_byte_count": "tx_cmac_accepted_byte_count",
            "tx_selected_endpoint": "tx_selected_endpoint",
            "tx_selected_route": "tx_selected_route",
            "tx_selected_route_is_time": "tx_selected_route_is_time",
            "qsfp_test_interval_cycles": "qsfp_test_interval_cycles",
            "tx_cmac_source_status": "tx_cmac_source_status",
            "tx_cmac_mux_selected_source": "tx_cmac_mux_selected_source",
            "tx_cmac_mux_selected_heartbeat": "tx_cmac_mux_selected_heartbeat",
            "tx_cmac_mux_selected_time": "tx_cmac_mux_selected_time",
            "tx_cmac_mux_selected_spec": "tx_cmac_mux_selected_spec",
            "tx_cmac_mux_select_time": "tx_cmac_mux_select_time",
            "tx_cmac_mux_select_spec": "tx_cmac_mux_select_spec",
            "tx_cmac_heartbeat_enabled": "tx_cmac_heartbeat_enabled",
            "tx_cmac_heartbeat_valid": "tx_cmac_heartbeat_valid",
            "tx_cmac_time_valid": "tx_cmac_time_valid",
            "tx_cmac_idle_bridge_ready": "tx_cmac_idle_bridge_ready",
            "tx_time_live_requested_data": "tx_time_live_requested_data",
            "tx_time_live_requested_cmac": "tx_time_live_requested_cmac",
            "tx_spec_live_requested_data": "tx_spec_live_requested_data",
            "tx_spec_live_requested_cmac": "tx_spec_live_requested_cmac",
            "tx_idle_bridge_requested_data": "tx_idle_bridge_requested_data",
            "tx_idle_bridge_requested_cmac": "tx_idle_bridge_requested_cmac",
            "tx_idle_bridge_fifo_full": "tx_idle_bridge_fifo_full",
            "tx_idle_bridge_fifo_empty": "tx_idle_bridge_fifo_empty",
            "tx_time_live_bridge_fifo_full": "tx_time_live_bridge_fifo_full",
            "tx_time_live_bridge_fifo_empty": "tx_time_live_bridge_fifo_empty",
            "tx_cmac_source_mux_raw": "tx_cmac_source_mux_raw",
            "tx_cmac_source_mux_locked": "tx_cmac_source_mux_locked",
        }
        for dst, src in mapping.items():
            if src in status:
                result[dst] = status[src]
        result["snapshot_source"] = "read_status_after"
        return result

    @staticmethod
    def _prefer_coherent_live_tx_status(snapshot: Mapping[str, Any], live: Mapping[str, Any]) -> dict[str, Any]:
        """Use a self-consistent live CMAC sample when the bulk snapshot races it."""
        result = dict(snapshot)
        live_ready = (
            bool(int(live.get("gt_locked", 0)))
            and bool(int(live.get("cmac_reset_done", 0)))
            and bool(int(live.get("cmac_tx_ready", 0)))
            and bool(int(live.get("qsfp_link_up", 0)))
            and bool(int(live.get("cmac_enable", 0)))
            and bool(int(live.get("frame_builder_enabled", 0)))
            and not bool(int(live.get("udp_dry_run_active", 1)))
            and not bool(int(live.get("tx_local_fault", 0)))
            and not bool(int(live.get("tx_remote_fault", 0)))
        )
        if live_ready:
            for key in (
                "gt_locked", "cmac_reset_done", "cmac_tx_ready", "qsfp_link_up",
                "cmac_enable", "frame_builder_enabled", "udp_dry_run_active",
                "tx_local_fault", "tx_remote_fault", "tx_underflow", "tx_overflow",
            ):
                result[key] = live.get(key, result.get(key, 0))
            result["snapshot_source"] = "coherent_live_after_snapshot_race"
        return result

    def set_unix_seconds(self, unix_seconds: int) -> None:
        self._write64(self.regs.UNIX_SECONDS_LO, unix_seconds)

    def set_mode(self, mode: str) -> None:
        try:
            value = self.MODES[mode.lower()]
        except KeyError as exc:
            raise ValueError(f"Unsupported mode: {mode}") from exc
        self.ctrl.write(self.regs.MODE, value)

    def configure_channelizer(
        self,
        *,
        nchan: int = 4096,
        taps: int = 8,
        chan0: int = 0,
        chan_count: int = 256,
        time_count: int = 1,
        fft_shift: int = FENGINE_DEFAULT_FFT_SHIFT,
        enable: bool = True,
        clear: bool = False,
    ) -> dict[str, int]:
        if nchan != 4096:
            raise ValueError("current channelizer requires nchan=4096")
        if taps != 8:
            raise ValueError("current channelizer requires taps=8")
        if not 0 <= fft_shift <= 0xFFFF:
            raise ValueError("fft_shift must fit in 16 bits")
        if chan0 != 0 or chan_count != 256 or time_count != 1:
            raise ValueError(
                "current SPEC layout requires chan0=0, chan_count=256, and time_count=1"
            )

        self.ctrl.write(self.regs.PFB_TAPS, int(taps))
        self.ctrl.write(self.regs.PFB_FFT_SHIFT, int(fft_shift))
        self.ctrl.write(self.regs.PFB_CHAN0, int(chan0))
        self.ctrl.write(self.regs.PFB_CHAN_COUNT, int(chan_count))
        self.ctrl.write(self.regs.PFB_TIME_COUNT, int(time_count))
        self.ctrl.write(self.regs.SPEC_CHAN_COUNT, int(chan_count))
        self.ctrl.write(self.regs.SPEC_TIME_COUNT, int(time_count))
        self.ctrl.write(self.regs.PFB_CONTROL, (0x1 if enable else 0x0) | (0x2 if clear else 0x0))
        return self.read_channelizer_status()

    def read_channelizer_status(self) -> dict[str, int]:
        status = {
            "pfb_control": int(self.ctrl.read(self.regs.PFB_CONTROL)),
            "pfb_status": int(self.ctrl.read(self.regs.PFB_STATUS)),
            "pfb_nchan": int(self.ctrl.read(self.regs.PFB_NCHAN)),
            "pfb_taps": int(self.ctrl.read(self.regs.PFB_TAPS)),
            "pfb_fft_shift": int(self.ctrl.read(self.regs.PFB_FFT_SHIFT)),
            "pfb_chan0": int(self.ctrl.read(self.regs.PFB_CHAN0)),
            "pfb_chan_count": int(self.ctrl.read(self.regs.PFB_CHAN_COUNT)),
            "pfb_time_count": int(self.ctrl.read(self.regs.PFB_TIME_COUNT)),
            "pfb_frame_count": int(self.ctrl.read(self.regs.PFB_FRAME_COUNT)),
            "pfb_overflow_count": int(self.ctrl.read(self.regs.PFB_OVERFLOW_COUNT)),
            "pfb_data_halt_count": int(self.ctrl.read(self.regs.PFB_DATA_HALT_COUNT)),
            "pfb_xfft_event_count": int(self.ctrl.read(self.regs.PFB_XFFT_EVENT_COUNT)),
            "pfb_tile_overflow_count": int(self.ctrl.read(self.regs.PFB_TILE_OVERFLOW_COUNT)),
            "pfb_input_fifo_level": int(self.ctrl.read(self.regs.PFB_INPUT_FIFO_LEVEL)),
            "pfb_xfft_tlast_unexpected_count": int(self.ctrl.read(self.regs.PFB_XFFT_TLAST_UNEXPECTED_COUNT)),
            "pfb_xfft_tlast_missing_count": int(self.ctrl.read(self.regs.PFB_XFFT_TLAST_MISSING_COUNT)),
            "pfb_xfft_fft_overflow_count": int(self.ctrl.read(self.regs.PFB_XFFT_FFT_OVERFLOW_COUNT)),
            "pfb_xfft_data_out_halt_count": int(self.ctrl.read(self.regs.PFB_XFFT_DATA_OUT_HALT_COUNT)),
            "pfb_xfft_status_halt_count": int(self.ctrl.read(self.regs.PFB_XFFT_STATUS_HALT_COUNT)),
            "pfb_capture_backpressure_count": int(self.ctrl.read(self.regs.PFB_CAPTURE_BACKPRESSURE_COUNT)),
            "pfb_frame_sample0_overflow_count": int(self.ctrl.read(self.regs.PFB_FRAME_SAMPLE0_OVERFLOW_COUNT)),
            "pfb_peak_chan": int(self.ctrl.read(self.regs.PFB_PEAK_CHAN)),
            "pfb_peak_power": int(self.ctrl.read(self.regs.PFB_PEAK_POWER)),
            "pfb_coeff_control": int(self.ctrl.read(self.regs.PFB_COEFF_CONTROL)),
            "pfb_coeff_status": int(self.ctrl.read(self.regs.PFB_COEFF_STATUS)),
            "pfb_coeff_loaded_count": int(self.ctrl.read(self.regs.PFB_COEFF_LOADED_COUNT)),
            "pfb_coeff_active_id": int(self.ctrl.read(self.regs.PFB_COEFF_ID)),
            "pfb_coeff_crc32": int(self.ctrl.read(self.regs.PFB_COEFF_CRC32)),
            "pfb_coeff_error_count": int(self.ctrl.read(self.regs.PFB_COEFF_ERROR_COUNT)),
        }
        raw = status["pfb_status"]
        status["pfb_enabled"] = raw & 0x1
        status["pfb_config_valid"] = (raw >> 1) & 0x1
        status["pfb_output_valid"] = (raw >> 2) & 0x1
        status["pfb_overflow"] = (raw >> 3) & 0x1
        status["pfb_busy"] = (raw >> 4) & 0x1
        status["pfb_window_active"] = status["pfb_busy"]
        status["fir_saturation_count"] = status["pfb_tile_overflow_count"]
        status["pfb_coeff_checksum"] = status["pfb_coeff_crc32"]
        status["pfb_science_valid"] = (raw >> 5) & 0x1
        status["pfb_input_fifo_frame_ready"] = (raw >> 6) & 0x1
        status["pfb_data_halt_seen"] = (raw >> 7) & 0x1
        status["pfb_fft_only"] = (raw >> 8) & 0x1
        status["pfb_xfft_configured"] = (raw >> 9) & 0x1
        status["pfb_xfft_config_tvalid"] = (raw >> 10) & 0x1
        status["pfb_xfft_config_tready"] = (raw >> 11) & 0x1
        status["pfb_fft_shift_status"] = (raw >> 12) & 0xF
        status["pfb_xfft_config_done_mask"] = (raw >> 16) & 0xFF
        status["pfb_xfft_config_ready_mask"] = (raw >> 24) & 0xFF
        coeff_control = status["pfb_coeff_control"]
        coeff_status = status["pfb_coeff_status"]
        status["pfb_coeff_requested_taps"] = (coeff_control >> 4) & 0xF
        status["pfb_coeff_auto_increment"] = (coeff_control >> 3) & 0x1
        status["pfb_coeff_active_valid"] = coeff_status & 0x1
        status["pfb_coeff_shadow_loading"] = (coeff_status >> 1) & 0x1
        status["pfb_coeff_shadow_full"] = (coeff_status >> 2) & 0x1
        status["pfb_coeff_commit_pending"] = (coeff_status >> 3) & 0x1
        status["pfb_coeff_busy"] = (coeff_status >> 4) & 0x1
        status["pfb_coeff_command_error"] = (coeff_status >> 5) & 0x1
        status["pfb_coeff_active_bank"] = (coeff_status >> 6) & 0x1
        status["pfb_coeff_shadow_bank"] = (coeff_status >> 7) & 0x1
        status["pfb_coeff_active_taps"] = (coeff_status >> 8) & 0xF
        status["pfb_active"] = int(
            int(status["pfb_taps"]) == 8
            and int(status["pfb_science_valid"])
            and not int(status["pfb_fft_only"])
            and int(status["pfb_coeff_active_valid"])
        )
        return status

    _SYNC_ERROR_NAMES = {
        0: "none",
        1: "prepare_busy",
        2: "bad_first_sample0_alignment",
        3: "generation_not_monotonic",
        4: "mts_result_not_valid",
        5: "reference_unlocked",
        6: "rfdc_not_ready",
        7: "pps_not_recent",
        8: "command_in_bad_state",
        9: "target_pps_too_soon",
        10: "target_pps_missed",
        11: "first_sample0_missed",
        12: "signal_chain_tag_invalid",
        13: "epoch_tai_invalid",
    }

    def read_scheduled_sync_status(self) -> dict[str, Any]:
        raw = int(self.ctrl.read(self.regs.SYNC_STATUS)) & 0xFFFF_FFFF
        error = int(self.ctrl.read(self.regs.SYNC_ERROR)) & 0xFFFF_FFFF
        caps = int(self.ctrl.read(self.regs.SYNC_CAPS)) & 0xFFFF_FFFF
        sample_rate_mode = int(self.ctrl.read(self.regs.SCIENCE_SAMPLE_RATE_MODE)) & 0x3
        aa100_active = bool(
            int(self.ctrl.read(self.regs.SCIENCE_ANTIALIAS_STATUS)) & (1 << 8)
        )
        alignment_modulus, alignment_residue, default_first_sample0 = (
            self._first_sample0_rule(sample_rate_mode, aa100_active)
        )
        return {
            "caps_raw": caps,
            "contract_version": (caps >> 24) & 0xFF,
            "sample0_alignment_log2": (caps >> 16) & 0xFF,
            "min_lead_pps": (caps >> 8) & 0xFF,
            "sample_rate_mode": sample_rate_mode,
            "aa100_active": aa100_active,
            "first_sample0_modulus": alignment_modulus,
            "first_sample0_residue": alignment_residue,
            "default_first_sample0": default_first_sample0,
            "raw": raw,
            "selected": bool(raw & (1 << 0)),
            "prepared": bool(raw & (1 << 1)),
            "armed": bool(raw & (1 << 2)),
            "epoch_committed": bool(raw & (1 << 3)),
            "epoch_valid": bool(raw & (1 << 4)),
            "streaming": bool(raw & (1 << 5)),
            "error": bool(raw & (1 << 6)),
            "pps_recent": bool(raw & (1 << 7)),
            "ref_locked": bool(raw & (1 << 8)),
            "rfdc_ready": bool(raw & (1 << 9)),
            "mts_result_valid": bool(raw & (1 << 10)),
            "first_time_seen": bool(raw & (1 << 11)),
            "first_spec_seen": bool(raw & (1 << 12)),
            "state": (raw >> 16) & 0xF,
            "error_code": error,
            "error_name": self._SYNC_ERROR_NAMES.get(error, f"unknown_{error}"),
            "generation": self._read64(self.regs.SYNC_GENERATION_LO),
            "target_pps_count": self._read64(self.regs.SYNC_TARGET_PPS_LO),
            "epoch_tai_seconds": self._read64(self.regs.SYNC_EPOCH_TAI_LO),
            "first_sample0": self._read64(self.regs.SYNC_FIRST_SAMPLE0_LO),
            "observation_tag": self._read64(self.regs.SYNC_OBSERVATION_TAG_LO),
            "signal_chain_tag": int(self.ctrl.read(self.regs.SYNC_SIGNAL_CHAIN_TAG)) & 0xFFFF_FFFF,
            "schedule_tag": int(self.ctrl.read(self.regs.SYNC_SCHEDULE_TAG)) & 0xFFFF_FFFF,
            "mts_result_id": int(self.ctrl.read(self.regs.SYNC_MTS_RESULT_ID)) & 0xFFFF_FFFF,
            "active_generation": self._read64(self.regs.SYNC_ACTIVE_GENERATION_LO),
            "actual_commit_pps_count": self._read64(self.regs.SYNC_ACTUAL_COMMIT_PPS_LO),
            "actual_epoch_raw_sample0": self._read64(self.regs.SYNC_ACTUAL_EPOCH_RAW_SAMPLE0_LO),
            "actual_first_time_sample0": self._read64(self.regs.SYNC_ACTUAL_FIRST_TIME_SAMPLE0_LO),
            "actual_first_spec_sample0": self._read64(self.regs.SYNC_ACTUAL_FIRST_SPEC_SAMPLE0_LO),
            "current_pps_count": self._read64(self.regs.SYNC_CURRENT_PPS_LO),
        }

    @staticmethod
    def _first_sample0_rule(
        sample_rate_mode: int, aa100_active: bool
    ) -> tuple[int, int, int]:
        """Return (modulus, residue, safe default) in raw ADC sample units."""
        sample_rate_mode = int(sample_rate_mode) & 0x3
        if sample_rate_mode == 0:
            return 32, 0, 32768
        if sample_rate_mode == 1:
            if bool(aa100_active):
                # The narrow path advances by eight 320-MS/s base samples per
                # output beat and therefore uses residue four.
                return 8, 4, 32788
            return 8, 0, 32768
        return 4, 0, 32768

    def _wait_scheduled_sync(self, predicate: Any, *, timeout_s: float) -> dict[str, Any]:
        deadline = time.monotonic() + max(0.0, float(timeout_s))
        while True:
            status = self.read_scheduled_sync_status()
            if status["error"]:
                raise RuntimeError(
                    f"ScheduledSync sync failed: {status['error_name']} "
                    f"(code={status['error_code']})"
                )
            if predicate(status):
                return status
            if time.monotonic() >= deadline:
                raise TimeoutError(f"ScheduledSync sync command timed out: {status}")
            time.sleep(0.002)

    def prepare_scheduled_sync(
        self,
        *,
        generation: int,
        target_pps_count: Optional[int] = None,
        epoch_tai_seconds: int,
        first_sample0: Optional[int] = None,
        observation_tag: int = 0,
        signal_chain_tag: int = 0,
        schedule_tag: int = 0,
        mts_result_id: int,
        lead_pps: int = 5,
        timeout_s: float = 0.25,
    ) -> dict[str, Any]:
        generation = int(generation)
        epoch_tai_seconds = int(epoch_tai_seconds)
        mts_result_id = int(mts_result_id)
        if generation <= 0 or generation > 0xFFFF_FFFF_FFFF_FFFF:
            raise ValueError("generation must be a positive u64")
        if epoch_tai_seconds <= 0 or epoch_tai_seconds > 0xFFFF_FFFF_FFFF_FFFF:
            raise ValueError("epoch_tai_seconds must be positive TAI seconds")
        sample_rate_mode = int(self.ctrl.read(self.regs.SCIENCE_SAMPLE_RATE_MODE)) & 0x3
        aa100_active = bool(
            int(self.ctrl.read(self.regs.SCIENCE_ANTIALIAS_STATUS)) & (1 << 8)
        )
        modulus, residue, safe_default = self._first_sample0_rule(
            sample_rate_mode, aa100_active
        )
        if first_sample0 is None:
            first_sample0 = safe_default
        first_sample0 = int(first_sample0)
        if first_sample0 <= 0 or first_sample0 % modulus != residue:
            raise ValueError(
                "first_sample0 is unreachable for the active science path: "
                f"sample_rate_mode={sample_rate_mode}, aa100_active={aa100_active}, "
                f"require first_sample0 % {modulus} == {residue}"
            )
        if mts_result_id <= 0 or mts_result_id > 0xFFFF_FFFF:
            raise ValueError("mts_result_id must identify a successful persisted MTS result")
        if int(signal_chain_tag) <= 0 or int(signal_chain_tag) > 0xFFFF_FFFF:
            raise ValueError("signal_chain_tag must be a non-zero immutable configuration ID")
        current_pps = self._read64(self.regs.SYNC_CURRENT_PPS_LO)
        if target_pps_count is None:
            target_pps_count = current_pps + max(2, int(lead_pps))
        target_pps_count = int(target_pps_count)
        if target_pps_count < current_pps + 2:
            raise ValueError(
                f"target_pps_count={target_pps_count} is too soon; current_pps_count={current_pps}"
            )

        self._write64(self.regs.SYNC_GENERATION_LO, generation)
        self._write64(self.regs.SYNC_TARGET_PPS_LO, target_pps_count)
        self._write64(self.regs.SYNC_EPOCH_TAI_LO, epoch_tai_seconds)
        self._write64(self.regs.SYNC_FIRST_SAMPLE0_LO, first_sample0)
        self._write64(self.regs.SYNC_OBSERVATION_TAG_LO, int(observation_tag))
        self.ctrl.write(self.regs.SYNC_SIGNAL_CHAIN_TAG, int(signal_chain_tag) & 0xFFFF_FFFF)
        self.ctrl.write(self.regs.SYNC_SCHEDULE_TAG, int(schedule_tag) & 0xFFFF_FFFF)
        self.ctrl.write(self.regs.SYNC_MTS_RESULT_ID, mts_result_id & 0xFFFF_FFFF)
        self.ctrl.write(self.regs.SYNC_COMMAND, 0x1)
        return self._wait_scheduled_sync(
            lambda value: bool(value["prepared"] and value["active_generation"] == generation),
            timeout_s=timeout_s,
        )

    def arm_scheduled_sync(self, *, timeout_s: float = 0.25) -> dict[str, Any]:
        self.ctrl.write(self.regs.SYNC_COMMAND, 0x2)
        return self._wait_scheduled_sync(lambda value: bool(value["armed"]), timeout_s=timeout_s)

    def abort_scheduled_sync(self, *, timeout_s: float = 0.25) -> dict[str, Any]:
        self.ctrl.write(self.regs.SYNC_COMMAND, 0x4)
        status = self._wait_scheduled_sync(
            lambda value: not bool(value["selected"]), timeout_s=timeout_s
        )
        # ABORT also clears any partial science or CMAC-side frame.
        status["pipeline_flush"] = self.flush_science_pipeline()
        return status

    def clear_scheduled_sync_status(self) -> None:
        self.ctrl.write(self.regs.SYNC_COMMAND, 0x8)

    def persist_mts_result_id(self, mts_result_id: int) -> int:
        mts_result_id = int(mts_result_id) & 0xFFFF_FFFF
        if mts_result_id == 0:
            raise ValueError("mts_result_id must be non-zero")
        self.ctrl.write(self.regs.SYNC_MTS_RESULT_ID, mts_result_id)
        readback = int(self.ctrl.read(self.regs.SYNC_MTS_RESULT_ID)) & 0xFFFF_FFFF
        if readback != mts_result_id:
            raise RuntimeError(
                f"ScheduledSync MTS result-id readback mismatch: wrote={mts_result_id} read={readback}"
            )
        return readback

    def start(self) -> None:
        self.ctrl.write(self.regs.CONTROL, 0x1)

    def trigger_epoch(self) -> None:
        self.ctrl.write(self.regs.CONTROL, 0x2)

    def flush_science_pipeline(self) -> dict[str, int]:
        """Flush both sides of the science-to-CMAC path without changing config.

        PFB_CONTROL[1] clears the science selector/PFB state while preserving
        PFB_CONTROL[0].  TX_CONTROL[5] clears packet/TX state and the CMAC-side
        frame lock while preserving the persistent TX policy bits [4:0].
        Both pulses are required to leave no partial frame on either side.
        """
        pfb_control = int(self.ctrl.read(self.regs.PFB_CONTROL)) & 0x1
        tx_control = int(self.ctrl.read(self.regs.TX_CONTROL)) & 0x1F
        self.ctrl.write(self.regs.PFB_CONTROL, pfb_control | 0x2)
        self.ctrl.write(self.regs.TX_CONTROL, tx_control | 0x20)
        return {
            "pfb_control_preserved": pfb_control,
            "tx_control_preserved": tx_control,
            "pfb_clear_pulsed": 1,
            "tx_clear_pulsed": 1,
        }

    def stop(self) -> None:
        self.ctrl.write(self.regs.CONTROL, 0x4)
        self.flush_science_pipeline()

    def reset(self) -> None:
        self.ctrl.write(self.regs.CONTROL, 0x8)
        self.flush_science_pipeline()

    def read_status(self) -> dict[str, int]:
        keys = {
            "core_version": self.regs.CORE_VERSION,
            "board_id": self.regs.BOARD_ID,
            "mode": self.regs.MODE,
            "status": self.regs.STATUS,
            "pps_status": self.regs.PPS_STATUS,
            "ref_status": self.regs.REF_STATUS,
            "error_flags": self.regs.ERROR_FLAGS,
            "sync_config": self.regs.SYNC_CONFIG,
            "pps_count_lo": self.regs.PPS_COUNT_LO,
            "pps_count_hi": self.regs.PPS_COUNT_HI,
            "sysref_capture_status": self.regs.SYSREF_CAPTURE_STATUS,
            "sysref_pl_edge_count": self.regs.SYSREF_PL_EDGE_COUNT,
            "sysref_adc_edge_count": self.regs.SYSREF_ADC_EDGE_COUNT,
            "sysref_dac_edge_count": self.regs.SYSREF_DAC_EDGE_COUNT,
            "monitor_sample_count": self.regs.MONITOR_SAMPLE_COUNT,
            "spec_packet_count": self.regs.SPEC_PACKET_COUNT,
            "spec_udp_byte_count": self.regs.SPEC_UDP_BYTE_COUNT,
            "time_packet_count": self.regs.TIME_PACKET_COUNT,
            "time_udp_byte_count": self.regs.TIME_UDP_BYTE_COUNT,
            "time_dropped_count": self.regs.TIME_DROPPED_COUNT,
            "spec_dropped_count": self.regs.SPEC_DROPPED_COUNT,
            "spec_seq_no": self.regs.SPEC_SEQ_NO,
            "time_seq_no": self.regs.TIME_SEQ_NO,
            "spec_chan0": self.regs.SPEC_CHAN0,
            "rfdc_status_flags": self.regs.RFDC_STATUS_FLAGS,
            "rfdc_dropped_count": self.regs.RFDC_DROPPED_COUNT,
            "rfdc_active_mask": self.regs.RFDC_ACTIVE_MASK,
            "rfdc_current_valid_mask": self.regs.RFDC_CURRENT_VALID_MASK,
            "rfdc_seen_valid_mask": self.regs.RFDC_SEEN_VALID_MASK,
            "science_dropped_beat_count": self.regs.SCIENCE_DROPPED_BEAT_COUNT,
            "tx_link_status_flags": self.regs.TX_LINK_STATUS_FLAGS,
            "tx_dry_run_packet_count": self.regs.TX_DRY_RUN_PACKET_COUNT,
            "tx_dry_run_byte_count": self.regs.TX_DRY_RUN_BYTE_COUNT,
            "tx_fifo_level_words": self.regs.TX_FIFO_LEVEL_WORDS,
            "tx_fifo_high_water_words": self.regs.TX_FIFO_HIGH_WATER_WORDS,
            "tx_fifo_backpressure_cycles": self.regs.TX_FIFO_BACKPRESSURE_CYCLES,
            "dac_tone_control": self.regs.DAC_TONE_CONTROL,
            "dac_tone_amplitude": self.regs.DAC_TONE_AMPLITUDE,
            "dac_tone_phase_step": self.regs.DAC_TONE_PHASE_STEP,
            "dac_enable_mask": self.regs.DAC_ENABLE_MASK,
            "dac_phase_epoch": self.regs.DAC_PHASE_EPOCH,
            "preview_status": self.regs.PREVIEW_STATUS,
            "preview_input_mask": self.regs.PREVIEW_INPUT_MASK,
            "preview_capture_count": self.regs.PREVIEW_CAPTURE_COUNT,
            "preview_nsample": self.regs.PREVIEW_NSAMP,
            "preview_sample_rate_hz": self.regs.PREVIEW_SAMPLE_RATE_HZ,
            "preview_axis_beat_rate_hz": self.regs.PREVIEW_AXIS_BEAT_RATE_HZ,
            "preview_mode": self.regs.PREVIEW_MODE,
            "science_control": self.regs.SCIENCE_CONTROL,
            "science_status": self.regs.SCIENCE_STATUS,
            "science_sample_rate_mode": self.regs.SCIENCE_SAMPLE_RATE_MODE,
            "science_output_mode": self.regs.SCIENCE_OUTPUT_MODE,
            "science_sample_rate_hz": self.regs.SCIENCE_SAMPLE_RATE_HZ,
            "science_decim_factor": self.regs.SCIENCE_DECIM_FACTOR,
            "science_payload_rate_mbps": self.regs.SCIENCE_PAYLOAD_RATE_MBPS,
            "science_block_reason": self.regs.SCIENCE_BLOCK_REASON,
            "science_capability": self.regs.SCIENCE_CAPABILITY,
            "science_time_live_interval_beats": self.regs.SCIENCE_TIME_LIVE_INTERVAL_BEATS,
            "science_time_multiflow_control": self.regs.SCIENCE_TIME_MULTIFLOW_CONTROL,
            "science_antialias_status": self.regs.SCIENCE_ANTIALIAS_STATUS,
            "science_antialias_coeff_version": self.regs.SCIENCE_ANTIALIAS_COEFF_VERSION,
            "pfb_control": self.regs.PFB_CONTROL,
            "pfb_status": self.regs.PFB_STATUS,
            "pfb_nchan": self.regs.PFB_NCHAN,
            "pfb_taps": self.regs.PFB_TAPS,
            "pfb_fft_shift": self.regs.PFB_FFT_SHIFT,
            "pfb_chan0": self.regs.PFB_CHAN0,
            "pfb_chan_count": self.regs.PFB_CHAN_COUNT,
            "pfb_time_count": self.regs.PFB_TIME_COUNT,
            "pfb_frame_count": self.regs.PFB_FRAME_COUNT,
            "pfb_overflow_count": self.regs.PFB_OVERFLOW_COUNT,
            "pfb_data_halt_count": self.regs.PFB_DATA_HALT_COUNT,
            "pfb_xfft_event_count": self.regs.PFB_XFFT_EVENT_COUNT,
            "pfb_tile_overflow_count": self.regs.PFB_TILE_OVERFLOW_COUNT,
            "pfb_input_fifo_level": self.regs.PFB_INPUT_FIFO_LEVEL,
            "pfb_xfft_tlast_unexpected_count": self.regs.PFB_XFFT_TLAST_UNEXPECTED_COUNT,
            "pfb_xfft_tlast_missing_count": self.regs.PFB_XFFT_TLAST_MISSING_COUNT,
            "pfb_xfft_fft_overflow_count": self.regs.PFB_XFFT_FFT_OVERFLOW_COUNT,
            "pfb_xfft_data_out_halt_count": self.regs.PFB_XFFT_DATA_OUT_HALT_COUNT,
            "pfb_xfft_status_halt_count": self.regs.PFB_XFFT_STATUS_HALT_COUNT,
            "pfb_capture_backpressure_count": self.regs.PFB_CAPTURE_BACKPRESSURE_COUNT,
            "pfb_frame_sample0_overflow_count": self.regs.PFB_FRAME_SAMPLE0_OVERFLOW_COUNT,
            "pfb_peak_chan": self.regs.PFB_PEAK_CHAN,
            "pfb_peak_power": self.regs.PFB_PEAK_POWER,
            "pfb_coeff_control": self.regs.PFB_COEFF_CONTROL,
            "pfb_coeff_status": self.regs.PFB_COEFF_STATUS,
            "pfb_coeff_loaded_count": self.regs.PFB_COEFF_LOADED_COUNT,
            "pfb_coeff_active_id": self.regs.PFB_COEFF_ID,
            "pfb_coeff_crc32": self.regs.PFB_COEFF_CRC32,
            "pfb_coeff_checksum": self.regs.PFB_COEFF_CRC32,
            "pfb_coeff_error_count": self.regs.PFB_COEFF_ERROR_COUNT,
            "tx_control": self.regs.TX_CONTROL,
            "tx_status": self.regs.TX_STATUS,
            "tx_frame_built_count": self.regs.TX_FRAME_BUILT_COUNT,
            "tx_frame_sent_count": self.regs.TX_FRAME_SENT_COUNT,
            "tx_frame_dropped_count": self.regs.TX_FRAME_DROPPED_COUNT,
            "tx_frame_byte_count": self.regs.TX_FRAME_BYTE_COUNT,
            "tx_route_miss_count": self.regs.TX_ROUTE_MISS_COUNT,
            "tx_route_error_count": self.regs.TX_ROUTE_ERROR_COUNT,
            "qsfp_test_interval_cycles": self.regs.QSFP_TEST_INTERVAL_CYCLES,
            "tx_cmac_source_status": self.regs.TX_CMAC_SOURCE_STATUS,
        }
        status = {name: int(self.ctrl.read(offset)) for name, offset in keys.items()}
        status.update(self.read_time_ddr_ring_status())
        raw_status = status["status"]
        status["armed"] = raw_status & 0x1
        status["streaming"] = (raw_status >> 1) & 0x1
        status["active_sync_mode"] = (raw_status >> 2) & 0x3
        status["waiting_for_epoch"] = (raw_status >> 4) & 0x1
        status["fsm_state"] = (raw_status >> 8) & 0xF
        status["configured_sync_mode"] = status["sync_config"] & 0x3
        status["configured_clock_ref"] = (status["sync_config"] >> 16) & 0x3
        status["pps_count"] = (
            int(status["pps_count_lo"])
            | (int(status["pps_count_hi"]) << 32)
        )
        status["pps_status_input_high"] = status["pps_status"] & 0x1
        status["pps_status_ref_locked"] = (status["pps_status"] >> 1) & 0x1
        status["pps_status_count_nonzero"] = (status["pps_status"] >> 2) & 0x1
        status["ref_status_locked"] = status["ref_status"] & 0x1
        status["sysref_pl_capture_level"] = status["sysref_capture_status"] & 0x1
        status["sysref_adc_capture_level"] = (status["sysref_capture_status"] >> 1) & 0x1
        status["sysref_dac_capture_level"] = (status["sysref_capture_status"] >> 2) & 0x1
        status["rfdc_sample_count"] = (
            int(self.ctrl.read(self.regs.RFDC_SAMPLE_COUNT_LO))
            | (int(self.ctrl.read(self.regs.RFDC_SAMPLE_COUNT_HI)) << 32)
        )
        status["time_sample0"] = (
            int(self.ctrl.read(self.regs.TIME_SAMPLE0_LO))
            | (int(self.ctrl.read(self.regs.TIME_SAMPLE0_HI)) << 32)
        )
        status["time_frame_id"] = (
            int(self.ctrl.read(self.regs.TIME_FRAME_ID_LO))
            | (int(self.ctrl.read(self.regs.TIME_FRAME_ID_HI)) << 32)
        )
        status["spec_frame_id"] = (
            int(self.ctrl.read(self.regs.SPEC_FRAME_ID_LO))
            | (int(self.ctrl.read(self.regs.SPEC_FRAME_ID_HI)) << 32)
        )
        flags = status["rfdc_status_flags"]
        status["rfdc_downstream_ready"] = flags & 0x1
        status["rfdc_core_ready"] = status["rfdc_downstream_ready"]
        status["rfdc_adc_valid"] = (flags >> 1) & 0x1
        status["rfdc_dac_ready"] = (flags >> 2) & 0x1
        status["rfdc_clock_locked"] = (flags >> 3) & 0x1
        status["pps_seen"] = (flags >> 4) & 0x1
        status["pps_input_high"] = (flags >> 5) & 0x1
        status["pps_recent"] = (flags >> 6) & 0x1
        tx_flags = status["tx_link_status_flags"]
        status["qsfp_link_up"] = tx_flags & 0x1
        status["udp_dry_run"] = (tx_flags >> 1) & 0x1
        tx_status = status["tx_status"]
        tx_link_raw = status["tx_link_status_flags"]
        tx_control = status["tx_control"]
        status["tx_preflight_status"] = tx_status
        status["tx_preflight_qsfp_link_up"] = tx_status & 0x1
        status["tx_preflight_udp_dry_run_active"] = (tx_status >> 1) & 0x1
        status["tx_preflight_cmac_reset_done"] = (tx_status >> 2) & 0x1
        status["tx_preflight_gt_locked"] = (tx_status >> 3) & 0x1
        status["tx_preflight_cmac_tx_ready"] = (tx_status >> 4) & 0x1
        status["tx_qsfp_link_up"] = tx_link_raw & 0x1
        status["tx_cmac_reset_done"] = (tx_link_raw >> 2) & 0x1
        status["tx_gt_locked"] = (tx_link_raw >> 3) & 0x1
        status["tx_cmac_tx_ready"] = (tx_link_raw >> 4) & 0x1
        status["tx_local_fault"] = (tx_link_raw >> 5) & 0x1
        status["tx_remote_fault"] = (tx_link_raw >> 6) & 0x1
        status["tx_route_miss_sticky"] = (tx_status >> 7) & 0x1
        status["tx_route_error_sticky"] = (tx_status >> 8) & 0x1
        status["tx_frame_builder_enabled"] = (tx_control >> 2) & 0x1
        status["tx_force_dry_run"] = tx_control & 0x1
        status["tx_cmac_enable"] = (tx_control >> 1) & 0x1
        status["tx_qsfp_module_present"] = (tx_link_raw >> 12) & 0x1
        status["tx_gt_refclk_seen"] = (tx_link_raw >> 13) & 0x1
        status["tx_gt_tx_reset_done"] = (tx_link_raw >> 14) & 0x1
        status["tx_gt_rx_reset_done"] = (tx_link_raw >> 15) & 0x1
        status["tx_underflow"] = (tx_link_raw >> 16) & 0x1
        status["tx_overflow"] = (tx_link_raw >> 17) & 0x1
        status["tx_diagnostic_ignore_link_gate"] = (tx_control >> 4) & 0x1
        status["tx_udp_dry_run_active"] = int(
            bool(status["tx_force_dry_run"])
            or not bool(status["tx_cmac_enable"])
            or not bool(status["tx_frame_builder_enabled"])
            or not bool(status["tx_qsfp_link_up"])
            or not bool(status["tx_cmac_reset_done"])
            or not bool(status["tx_gt_locked"])
            or bool(status["tx_local_fault"])
            or bool(status["tx_remote_fault"])
        )
        source_status = status["tx_cmac_source_status"]
        status["tx_cmac_mux_selected_source"] = source_status & 0x3
        status["tx_cmac_mux_selected_heartbeat"] = 1 if (source_status & 0x3) == 0 else 0
        status["tx_cmac_mux_selected_time"] = 1 if (source_status & 0x3) == 1 else 0
        status["tx_cmac_mux_selected_spec"] = 1 if (source_status & 0x3) == 2 else 0
        source_mux_raw = (source_status >> 16) & 0xFFFF
        status["tx_cmac_mux_select_time"] = (source_mux_raw >> 11) & 0x1
        status["tx_cmac_mux_select_spec"] = (source_mux_raw >> 12) & 0x1
        status["tx_cmac_heartbeat_enabled"] = (source_status >> 2) & 0x1
        status["tx_cmac_heartbeat_valid"] = (source_status >> 3) & 0x1
        status["tx_cmac_time_valid"] = (source_status >> 4) & 0x1
        status["tx_cmac_idle_bridge_ready"] = (source_status >> 5) & 0x1
        status["tx_time_live_requested_data"] = (source_status >> 6) & 0x1
        status["tx_time_live_requested_cmac"] = (source_status >> 7) & 0x1
        status["tx_spec_live_requested_data"] = (source_status >> 8) & 0x1
        status["tx_spec_live_requested_cmac"] = (source_status >> 9) & 0x1
        status["tx_idle_bridge_requested_data"] = (source_status >> 10) & 0x1
        status["tx_idle_bridge_requested_cmac"] = (source_status >> 11) & 0x1
        status["tx_idle_bridge_fifo_full"] = (source_status >> 12) & 0x1
        status["tx_idle_bridge_fifo_empty"] = (source_status >> 13) & 0x1
        status["tx_time_live_bridge_fifo_full"] = (source_status >> 14) & 0x1
        status["tx_time_live_bridge_fifo_empty"] = (source_status >> 15) & 0x1
        status["tx_cmac_source_mux_raw"] = source_mux_raw
        status["tx_cmac_source_mux_locked"] = (source_mux_raw >> 4) & 0x1
        status["tx_cmac_rx_aligned"] = (tx_link_raw >> 18) & 0x1
        status["tx_cmac_rx_status"] = (tx_link_raw >> 19) & 0x1
        status["tx_cmac_rx_local_fault_detail"] = (tx_link_raw >> 20) & 0x1
        status["tx_cmac_rx_internal_local_fault"] = (tx_link_raw >> 21) & 0x1
        status["tx_cmac_tx_local_fault_detail"] = (tx_link_raw >> 22) & 0x1
        status["tx_cmac_an_autoneg_complete"] = (tx_link_raw >> 23) & 0x1
        status["tx_cmac_an_lp_ability_valid"] = (tx_link_raw >> 24) & 0x1
        status["tx_cmac_an_lp_autoneg_able"] = (tx_link_raw >> 25) & 0x1
        status["tx_cmac_an_lp_ability_100gbase_cr4"] = (tx_link_raw >> 26) & 0x1
        status["tx_cmac_an_rs_fec_enable"] = (tx_link_raw >> 27) & 0x1
        status["tx_cmac_lt_signal_detect_all"] = (tx_link_raw >> 28) & 0x1
        status["tx_cmac_lt_training_any"] = (tx_link_raw >> 29) & 0x1
        status["tx_cmac_lt_training_fail_any"] = (tx_link_raw >> 30) & 0x1
        status["tx_cmac_lt_frame_lock_all"] = (tx_link_raw >> 31) & 0x1
        preview_status = status["preview_status"]
        status["preview_busy"] = preview_status & 0x1
        status["preview_error"] = (preview_status >> 1) & 0x1
        status["preview_done"] = (preview_status >> 2) & 0x1
        status["preview_sample0"] = (
            int(self.ctrl.read(self.regs.PREVIEW_SAMPLE0_LO))
            | (int(self.ctrl.read(self.regs.PREVIEW_SAMPLE0_HI)) << 32)
        )
        pfb_status = status["pfb_status"]
        status["pfb_enabled"] = pfb_status & 0x1
        status["pfb_config_valid"] = (pfb_status >> 1) & 0x1
        status["pfb_output_valid"] = (pfb_status >> 2) & 0x1
        status["pfb_overflow"] = (pfb_status >> 3) & 0x1
        status["pfb_busy"] = (pfb_status >> 4) & 0x1
        status["pfb_window_active"] = status["pfb_busy"]
        status["fir_saturation_count"] = status["pfb_tile_overflow_count"]
        status["pfb_coeff_crc32"] = status["pfb_coeff_checksum"]
        status["pfb_science_valid"] = (pfb_status >> 5) & 0x1
        status["pfb_input_fifo_frame_ready"] = (pfb_status >> 6) & 0x1
        status["pfb_data_halt_seen"] = (pfb_status >> 7) & 0x1
        status["pfb_fft_only"] = (pfb_status >> 8) & 0x1
        status["pfb_xfft_configured"] = (pfb_status >> 9) & 0x1
        status["pfb_xfft_config_tvalid"] = (pfb_status >> 10) & 0x1
        status["pfb_xfft_config_tready"] = (pfb_status >> 11) & 0x1
        status["pfb_fft_shift_status"] = (pfb_status >> 12) & 0xF
        status["pfb_xfft_config_done_mask"] = (pfb_status >> 16) & 0xFF
        status["pfb_xfft_config_ready_mask"] = (pfb_status >> 24) & 0xFF
        pfb_coeff_control = status["pfb_coeff_control"]
        pfb_coeff_status = status["pfb_coeff_status"]
        status["pfb_coeff_requested_taps"] = (pfb_coeff_control >> 4) & 0xF
        status["pfb_coeff_auto_increment"] = (pfb_coeff_control >> 3) & 0x1
        status["pfb_coeff_active_valid"] = pfb_coeff_status & 0x1
        status["pfb_coeff_shadow_loading"] = (pfb_coeff_status >> 1) & 0x1
        status["pfb_coeff_shadow_full"] = (pfb_coeff_status >> 2) & 0x1
        status["pfb_coeff_commit_pending"] = (pfb_coeff_status >> 3) & 0x1
        status["pfb_coeff_busy"] = (pfb_coeff_status >> 4) & 0x1
        status["pfb_coeff_command_error"] = (pfb_coeff_status >> 5) & 0x1
        status["pfb_coeff_active_bank"] = (pfb_coeff_status >> 6) & 0x1
        status["pfb_coeff_shadow_bank"] = (pfb_coeff_status >> 7) & 0x1
        status["pfb_coeff_active_taps"] = (pfb_coeff_status >> 8) & 0xF
        status["pfb_active"] = int(
            int(status["pfb_taps"]) == 8
            and int(status["pfb_science_valid"])
            and not int(status["pfb_fft_only"])
            and int(status["pfb_coeff_active_valid"])
        )
        science_status = status["science_status"]
        science_bw = int(status["science_sample_rate_mode"]) & 0x3
        science_mode = int(status["science_output_mode"]) & 0x7
        status["science_sample_rate_msps"] = self.SCIENCE_SAMPLE_RATE_BY_CODE.get(science_bw, 160)
        status["science_output_mode_name"] = self.SCIENCE_OUTPUT_MODE_NAMES.get(science_mode, f"UNKNOWN_{science_mode}")
        status["science_time_enabled"] = science_status & 0x1
        status["science_spec_enabled"] = (science_status >> 1) & 0x1
        status["science_time_spec_rejected"] = (science_status >> 2) & 0x1
        status["science_spec_ready"] = (science_status >> 3) & 0x1
        status["science_wide_tx_ready"] = (science_status >> 4) & 0x1
        status["science_cmac_live_ready"] = (science_status >> 5) & 0x1
        status["science_antialias_100m_active_from_status"] = (science_status >> 10) & 0x1
        status["science_antialias_100m_primed_from_status"] = (science_status >> 11) & 0x1
        antialias_status = int(status.get("science_antialias_status", 0))
        status["science_antialias_taps"] = antialias_status & 0xFF
        status["science_antialias_100m_active"] = (antialias_status >> 8) & 0x1
        status["science_antialias_100m_primed"] = (antialias_status >> 9) & 0x1
        status["science_block_reasons"] = self._science_block_names(status["science_block_reason"])
        status["rfdc_adc_analog_sample_rate_hz"] = self.RFDC_ADC_ANALOG_SAMPLE_RATE_HZ
        status["rfdc_dac_analog_sample_rate_hz"] = self.RFDC_DAC_ANALOG_SAMPLE_RATE_HZ
        status["rfdc_complex_sample_rate_hz"] = self.RFDC_COMPLEX_SAMPLE_RATE_HZ
        status["rfdc_adc_decimation"] = self.RFDC_DECIMATION
        status["rfdc_dac_interpolation"] = self.RFDC_INTERPOLATION
        status["rfdc_adc_axis_rate_hz"] = self.ADC_AXIS_RATE_HZ
        status["rfdc_dac_axis_rate_hz"] = self.DAC_AXIS_RATE_HZ
        return status


    @staticmethod
    def _counter_delta(now: int, prev: int, bits: int = 32) -> int:
        now = int(now)
        prev = int(prev)
        modulus = 1 << int(bits)
        return (now - prev) % modulus

    def read_realtime_rates(self) -> dict[str, Any]:
        now_s = time.monotonic()
        status = self.read_status()
        prev = getattr(self, "_last_rate_sample", None)
        self._last_rate_sample = {"time_s": now_s, "status": status}
        rates: dict[str, float] = {
            "adc_samples_per_s": 0.0,
            "spec_packets_per_s": 0.0,
            "spec_bytes_per_s": 0.0,
            "time_packets_per_s": 0.0,
            "time_bytes_per_s": 0.0,
            "packetizer_packets_per_s": 0.0,
            "packetizer_bytes_per_s": 0.0,
            "tx_dry_run_packets_per_s": 0.0,
            "tx_dry_run_bytes_per_s": 0.0,
            "tx_frame_built_per_s": 0.0,
            "tx_frame_bytes_per_s": 0.0,
        }
        if prev is not None:
            dt = max(now_s - float(prev["time_s"]), 1e-9)
            prev_status = prev["status"]
            rates["adc_samples_per_s"] = self._counter_delta(
                status["rfdc_sample_count"], prev_status["rfdc_sample_count"], bits=64
            ) / dt
            for name in (
                "spec_packet_count",
                "spec_udp_byte_count",
                "time_packet_count",
                "time_udp_byte_count",
                "tx_dry_run_packet_count",
                "tx_dry_run_byte_count",
                "tx_frame_built_count",
                "tx_frame_byte_count",
            ):
                delta = self._counter_delta(status[name], prev_status[name], bits=32)
                rates[name.replace("_count", "_per_s")] = delta / dt
            rates["packetizer_packets_per_s"] = rates["spec_packet_per_s"] + rates["time_packet_per_s"]
            rates["packetizer_bytes_per_s"] = rates["spec_udp_byte_per_s"] + rates["time_udp_byte_per_s"]
            rates["spec_packets_per_s"] = rates.pop("spec_packet_per_s")
            rates["spec_bytes_per_s"] = rates.pop("spec_udp_byte_per_s")
            rates["time_packets_per_s"] = rates.pop("time_packet_per_s")
            rates["time_bytes_per_s"] = rates.pop("time_udp_byte_per_s")
            rates["tx_dry_run_packets_per_s"] = rates.pop("tx_dry_run_packet_per_s")
            rates["tx_dry_run_bytes_per_s"] = rates.pop("tx_dry_run_byte_per_s")
            rates["tx_frame_built_per_s"] = rates.pop("tx_frame_built_per_s")
            rates["tx_frame_bytes_per_s"] = rates.pop("tx_frame_byte_per_s")
        return {
            "time_s": now_s,
            "status": status,
            "dt_s": 0.0 if prev is None else max(now_s - float(prev["time_s"]), 0.0),
            "rates": rates,
            "udp_dry_run": bool(status.get("udp_dry_run", 0) or status.get("tx_udp_dry_run_active", 0)),
            "qsfp_link_up": bool(status.get("qsfp_link_up", 0) or status.get("tx_qsfp_link_up", 0)),
            "qsfp_module_present": bool(status.get("tx_qsfp_module_present", 0)),
            "cmac_live_ready": bool(status.get("tx_cmac_reset_done", 0) and status.get("tx_gt_locked", 0) and status.get("tx_cmac_tx_ready", 0)),
            "science_payload_rate_mbps": float(status.get("science_payload_rate_mbps", 0)),
            "science_sample_rate_hz": float(status.get("science_sample_rate_hz", 0)),
            "science_sample_rate_msps": int(status.get("science_sample_rate_msps", 0)),
            "science_output_mode": str(status.get("science_output_mode_name", "UNKNOWN")),
            "science_block_reasons": list(status.get("science_block_reasons", [])),
        }

    @staticmethod
    def _s16(value: int) -> int:
        value &= 0xFFFF
        return value - 0x1_0000 if value & 0x8000 else value

    def _wait_preview_done(self, timeout: float) -> dict[str, int]:
        deadline = time.monotonic() + timeout
        status = self.read_status()
        while time.monotonic() < deadline:
            status = self.read_status()
            if status["preview_done"]:
                return status
            if status["preview_error"]:
                raise RuntimeError(f"preview capture failed: PREVIEW_STATUS=0x{status['preview_status']:08x}")
            time.sleep(0.005)
        raise TimeoutError(f"preview capture timed out: PREVIEW_STATUS=0x{status['preview_status']:08x}")

    def _trigger_preview_capture(
        self,
        input_mask: int,
        timeout: float = 1.0,
        *,
        allow_stopped: bool = False,
    ) -> dict[str, int]:
        if not 0 < input_mask <= 0xFF:
            raise ValueError("preview input_mask must be in range 0x01..0xff")
        status = self.read_status()
        if not status["streaming"] and not allow_stopped:
            raise RuntimeError("preview capture cannot run: F-engine is not streaming")
        if not status["rfdc_adc_valid"]:
            raise RuntimeError("preview capture cannot run: RFDC ADC AXIS valid is low")
        self.ctrl.write(self.regs.PREVIEW_INPUT_MASK, input_mask)
        self.ctrl.write(self.regs.PREVIEW_CONTROL, 0x2)
        self.ctrl.write(self.regs.PREVIEW_CONTROL, 0x1)
        return self._wait_preview_done(timeout)

    def capture_preview(
        self,
        n: Optional[int] = None,
        *,
        input_mask: int = 0x01,
        timeout: float = 1.0,
    ) -> dict[str, Any]:
        status = self._trigger_preview_capture(input_mask=input_mask, timeout=timeout)
        nsamp = int(status.get("preview_nsample", 1024) or 1024)
        count = nsamp if n is None else min(int(n), nsamp)
        inputs = [idx for idx in range(8) if input_mask & (1 << idx)]
        samples: dict[int, Any] = {}
        for idx in inputs:
            base = self.regs.PREVIEW_BUFFER_BASE + idx * self.regs.PREVIEW_INPUT_STRIDE
            words = [int(self.ctrl.read(base + 4 * sample_idx)) for sample_idx in range(count)]
            iq = [(self._s16(word & 0xFFFF), self._s16(word >> 16)) for word in words]
            samples[idx] = iq
        try:
            import numpy as np

            samples = {idx: np.array(iq, dtype=np.int16) for idx, iq in samples.items()}
        except ImportError:
            pass
        return {
            "input_mask": input_mask,
            "inputs": inputs,
            "sample0": int(status["preview_sample0"]),
            "sample_rate_hz": int(status.get("preview_sample_rate_hz") or status["debug_sample_rate_hz"]),
            "axis_beat_rate_hz": int(status.get("preview_axis_beat_rate_hz") or status["debug_sample_rate_hz"]),
            "preview_mode": int(status.get("preview_mode", 0)),
            "phase_ref_input": 0,
            "center_freq_hz": float(getattr(self, "rfdc_config", {}).get("f_center", 0.0)),
            "bandwidth_hz": float(getattr(self, "rfdc_config", {}).get("bandwidth", 0.0)),
            "count": count,
            "iq": samples,
        }

    def _preview_metadata(self, status: Mapping[str, int], input_mask: int, inputs: list[int], count: int) -> dict[str, Any]:
        return {
            "input_mask": input_mask,
            "inputs": inputs,
            "sample0": int(status["preview_sample0"]),
            "sample_rate_hz": int(status.get("preview_sample_rate_hz") or status["debug_sample_rate_hz"]),
            "axis_beat_rate_hz": int(status.get("preview_axis_beat_rate_hz") or status["debug_sample_rate_hz"]),
            "preview_mode": int(status.get("preview_mode", 0)),
            "phase_ref_input": 0,
            "center_freq_hz": float(getattr(self, "rfdc_config", {}).get("f_center", 0.0)),
            "bandwidth_hz": float(getattr(self, "rfdc_config", {}).get("bandwidth", 0.0)),
            "count": count,
        }

    def capture_preview_fast(
        self,
        n: Optional[int] = None,
        *,
        input_mask: int = 0x01,
        timeout: float = 1.0,
        allow_stopped: bool = False,
    ) -> dict[str, Any]:
        status = self._trigger_preview_capture(
            input_mask=input_mask,
            timeout=timeout,
            allow_stopped=allow_stopped,
        )
        return self._read_preview_buffer_from_status(status, n=n, input_mask=input_mask, prefer_fast=True)

    def capture_preview_calibration_quiescent(
        self,
        n: Optional[int] = None,
        *,
        input_mask: int = 0xFF,
        timeout: float = 1.0,
    ) -> dict[str, Any]:
        """Capture RFDC samples without enabling the science UDP path.

        STOP removes the global data-path handshake needed by the preview
        recorder.  This transaction temporarily starts only that global path
        while both science and TX controls are forced into dry-run.  Persistent
        controls are restored exactly and science packet counters must not
        advance.  It therefore does not create an unlabelled QSFP stream.
        """

        before = self.read_status()
        if bool(before.get("streaming", 0)):
            raise RuntimeError(
                "CALIBRATION_PREVIEW_STATE_CONFLICT: science streaming must be stopped"
            )
        science_control = int(self.ctrl.read(self.regs.SCIENCE_CONTROL)) & 0xFFFF_FFFF
        tx_control = int(self.ctrl.read(self.regs.TX_CONTROL)) & 0x1F
        counter_names = (
            "time_packet_count",
            "spec_packet_count",
            "tx_frame_sent_count",
        )
        capture: dict[str, Any] | None = None
        transaction_error: Exception | None = None
        try:
            self.ctrl.write(self.regs.SCIENCE_CONTROL, 0x1)
            self.configure_tx_control(
                force_dry_run=True,
                cmac_enable=False,
                frame_builder_enable=False,
                drop_on_route_miss=True,
                clear_counters=False,
            )
            self.start()
            deadline = time.monotonic() + max(float(timeout), 0.1)
            started = self.read_status()
            while (
                not bool(started.get("streaming", 0))
                or not bool(started.get("rfdc_adc_valid", 0))
            ) and time.monotonic() < deadline:
                time.sleep(0.005)
                started = self.read_status()
            if not bool(started.get("streaming", 0)):
                raise RuntimeError(
                    "CALIBRATION_PREVIEW_START_FAILED: internal dry-run path did not start"
                )
            capture = self.capture_preview_fast(
                n=n,
                input_mask=input_mask,
                timeout=timeout,
                allow_stopped=False,
            )
        except Exception as exc:
            transaction_error = exc
        finally:
            try:
                self.stop()
            finally:
                self.ctrl.write(self.regs.SCIENCE_CONTROL, science_control)
                self.ctrl.write(self.regs.TX_CONTROL, tx_control)
        after = self.read_status()
        deltas = {
            name: int(after.get(name, 0)) - int(before.get(name, 0))
            for name in counter_names
        }
        cleanup_errors = []
        if bool(after.get("streaming", 0)):
            cleanup_errors.append("streaming remained active")
        if any(value != 0 for value in deltas.values()):
            cleanup_errors.append(f"science packet counters advanced: {deltas}")
        if transaction_error is not None or cleanup_errors:
            raise RuntimeError(
                "CALIBRATION_PREVIEW_FAILED: "
                f"transaction={transaction_error}; cleanup={cleanup_errors}"
            ) from transaction_error
        assert capture is not None
        capture["calibration_dry_run"] = {
            "science_udp_stopped": True,
            "science_control_restored": int(self.ctrl.read(self.regs.SCIENCE_CONTROL))
            == science_control,
            "tx_control_restored": (int(self.ctrl.read(self.regs.TX_CONTROL)) & 0x1F)
            == tx_control,
            "packet_counter_deltas": deltas,
        }
        return capture

    def _read_preview_buffer_from_status(
        self,
        status: Mapping[str, int],
        *,
        n: Optional[int] = None,
        input_mask: int = 0x01,
        prefer_fast: bool = True,
    ) -> dict[str, Any]:
        try:
            import numpy as np
        except ImportError:
            np = None  # type: ignore[assignment]

        nsamp = int(status.get("preview_nsample", 1024) or 1024)
        count = nsamp if n is None else min(int(n), nsamp)
        if count <= 0:
            raise ValueError("preview sample count must be positive")
        inputs = [idx for idx in range(8) if input_mask & (1 << idx)]
        samples: dict[int, Any] = {}

        mmio_array = None
        if prefer_fast and np is not None:
            mmio_array = getattr(self.ctrl, "array", None)
            if mmio_array is None:
                mmio = getattr(self.ctrl, "mmio", None)
                mmio_array = getattr(mmio, "array", None)

        if mmio_array is not None and np is not None:
            for idx in inputs:
                word_index = (self.regs.PREVIEW_BUFFER_BASE + idx * self.regs.PREVIEW_INPUT_STRIDE) // 4
                words = np.asarray(mmio_array[word_index:word_index + count], dtype=np.uint32).copy()
                iq = np.empty((count, 2), dtype=np.int16)
                iq[:, 0] = (words & 0xFFFF).astype(np.int16)
                iq[:, 1] = ((words >> 16) & 0xFFFF).astype(np.int16)
                samples[idx] = iq
        else:
            for idx in inputs:
                base = self.regs.PREVIEW_BUFFER_BASE + idx * self.regs.PREVIEW_INPUT_STRIDE
                words = [int(self.ctrl.read(base + 4 * sample_idx)) for sample_idx in range(count)]
                iq_list = [(self._s16(word & 0xFFFF), self._s16(word >> 16)) for word in words]
                if np is not None:
                    samples[idx] = np.array(iq_list, dtype=np.int16)
                else:
                    samples[idx] = iq_list

        result = self._preview_metadata(status, input_mask, inputs, count)
        result["iq"] = samples
        result["fast_path"] = bool(mmio_array is not None)
        return result

    @staticmethod
    def compute_sample0_aligned_phase_view(
        preview: Mapping[str, Any],
        *,
        observe_center_hz: float,
        dac_signal_hz: Optional[float] = None,
        expected_signal_hz: Optional[float] = None,
        configured_phase_deg: float = 0.0,
        alignment_anchor_deg: Optional[float | Mapping[int, float]] = None,
        phase_deg_per_channel: float = 0.0,
        phase_deg_by_channel: Optional[Mapping[Any, Any] | Iterable[Any]] = None,
        phase_ref_input: int = 0,
        time_window_us: float = 0.25,
        display_points: int = 512,
        fft_oversample: float = 8.0,
        input_source_mode: str = "dac_loopback",
    ) -> dict[str, Any]:
        """Build phase diagnostics and a real sample0-indexed preview snapshot.

        The phase metrics still fit the raw ADC IQ numerically, but every
        waveform field returned by this view is copied from the RFDC preview
        buffer. Jupyter must never use fitted or configured tones as visible
        waveforms.
        """
        import math
        import numpy as np

        sample_rate = float(preview["sample_rate_hz"])
        count = int(preview["count"])
        sample0 = int(preview["sample0"])
        if sample_rate <= 0.0:
            raise ValueError("preview sample_rate_hz must be positive")
        if count <= 0:
            raise ValueError("preview count must be positive")
        observe_center_hz = float(observe_center_hz)
        signal_hz = expected_signal_hz if expected_signal_hz is not None else dac_signal_hz
        if signal_hz is None:
            raise ValueError("expected_signal_hz or dac_signal_hz is required")
        signal_hz = float(signal_hz)
        dac_signal_value = float(0.0 if dac_signal_hz is None else dac_signal_hz)
        expected_baseband_hz = signal_hz - observe_center_hz
        input_source_mode = T510FEngine._normalize_input_source_mode(input_source_mode)
        time_window_us = float(time_window_us)
        if time_window_us <= 0.0:
            raise ValueError("time_window_us must be positive")
        display_points = max(64, min(4096, int(display_points)))

        phase_cycles = math.fmod(float(sample0) * (expected_baseband_hz / sample_rate), 1.0)
        sample0_mod_phase_deg = (360.0 * phase_cycles) % 360.0
        t_fit = np.arange(count, dtype=np.float64) / sample_rate
        expected_basis = np.exp(1j * 2.0 * np.pi * expected_baseband_hz * t_fit)
        expected_basis_norm = max(float(np.vdot(expected_basis, expected_basis).real), 1.0)
        nfft = max(4096, int(2 ** math.ceil(math.log2(max(2.0, count * max(float(fft_oversample), 1.0))))))
        nfft = min(65536, nfft)
        freq_hz = np.fft.fftshift(np.fft.fftfreq(nfft, d=1.0 / sample_rate))
        window = np.hanning(count)

        def anchor_for_channel(channel: int) -> float:
            if alignment_anchor_deg is None:
                return 0.0
            if isinstance(alignment_anchor_deg, Mapping):
                value = alignment_anchor_deg.get(channel)
                if value is None:
                    value = alignment_anchor_deg.get(str(channel), 0.0)  # type: ignore[arg-type]
                return float(value)
            return float(alignment_anchor_deg)

        channels: dict[int, dict[str, Any]] = {}
        ref_phase_error: Optional[float] = None
        for idx, iq in preview["iq"].items():
            arr = np.asarray(iq, dtype=np.float64)
            i_data = arr[:, 0]
            q_data = arr[:, 1]
            z = i_data + 1j * q_data
            coeff = np.vdot(expected_basis, z) / expected_basis_norm
            fit = coeff * expected_basis
            residual = z - fit
            expected_tone_measured_phase_deg = float(np.angle(coeff, deg=True))
            sample0_aligned_phase_deg = T510FEngine._wrap_phase_deg(
                expected_tone_measured_phase_deg - sample0_mod_phase_deg
            )
            configured_ch_phase_deg = T510FEngine._configured_phase_deg_for_channel(
                int(idx),
                configured_phase_deg=float(configured_phase_deg),
                phase_deg_per_channel=float(phase_deg_per_channel),
                phase_deg_by_channel=phase_deg_by_channel,
            )
            anchor_deg = anchor_for_channel(int(idx))
            anchor_candidate_deg = T510FEngine._wrap_phase_deg(
                sample0_aligned_phase_deg - configured_ch_phase_deg
            )
            phase_error_deg = T510FEngine._wrap_phase_deg(
                sample0_aligned_phase_deg - configured_ch_phase_deg - anchor_deg
            )
            measured_display_phase_deg = T510FEngine._wrap_phase_deg(
                configured_ch_phase_deg + phase_error_deg
            )
            amplitude_code = float(abs(coeff))
            display_count = min(int(display_points), count)
            preview_time_us = np.arange(display_count, dtype=np.float64) / sample_rate * 1_000_000.0
            preview_sample_index = sample0 + np.arange(display_count, dtype=np.uint64)
            preview_i = i_data[:display_count]
            preview_q = q_data[:display_count]
            preview_mag = np.abs(z[:display_count])
            rf_equiv = T510FEngine._derive_rf_equivalent_waveform(
                preview_i,
                preview_q,
                sample0=sample0,
                sample_rate_hz=sample_rate,
                center_hz=observe_center_hz,
            )

            fft = np.fft.fftshift(np.fft.fft(z * window, n=nfft))
            power = np.abs(fft) ** 2
            peak_idx = int(np.argmax(power))
            fft_peak_hz = T510FEngine._interp_peak_from_power(freq_hz, power, peak_idx)
            fft_peak_phase_deg = float(np.angle(fft[peak_idx], deg=True))
            guard = max(2, nfft // 128)
            noise_mask = np.ones_like(power, dtype=bool)
            noise_mask[max(0, peak_idx - guard):min(len(noise_mask), peak_idx + guard + 1)] = False
            noise_floor = float(np.median(power[noise_mask])) if np.any(noise_mask) else 1.0
            peak_power = float(power[peak_idx])
            snr_db = 10.0 * np.log10(max(peak_power, 1.0) / max(noise_floor, 1.0))
            residual_rms_code = float(np.sqrt(np.mean(np.abs(residual) ** 2))) if residual.size else 0.0
            signal_rms_code = float(np.sqrt(np.mean(np.abs(fit) ** 2))) if fit.size else 0.0
            residual_fraction = residual_rms_code / max(signal_rms_code, 1.0)
            rms_code = float(np.sqrt(np.mean(i_data * i_data + q_data * q_data))) if arr.size else 0.0
            max_abs = float(np.max(np.abs(arr))) if arr.size else 0.0

            item = {
                "preview_time_us": preview_time_us,
                "preview_sample_index": preview_sample_index,
                "preview_waveform_i": preview_i,
                "preview_waveform_q": preview_q,
                "preview_waveform_mag": preview_mag,
                "rf_equivalent_waveform": rf_equiv,
                "rf_equivalent_time_us": preview_time_us,
                "rf_equivalent_center_hz": observe_center_hz,
                "derived_from_real_iq": True,
                "raw_rf": False,
                "waveform_source": "rfdc_preview_buffer",
                "virtual_waveform": False,
                "preview_mode": int(preview.get("preview_mode", 0)),
                "sample0": sample0,
                "sample_rate_hz": sample_rate,
                "configured_phase_deg": configured_ch_phase_deg,
                "display_reference_phase_deg": configured_ch_phase_deg,
                "expected_tone_measured_phase_deg": expected_tone_measured_phase_deg,
                "sample0_mod_phase_deg": float(sample0_mod_phase_deg),
                "sample0_aligned_phase_deg": sample0_aligned_phase_deg,
                "alignment_anchor_deg": anchor_deg,
                "anchor_candidate_deg": anchor_candidate_deg,
                "phase_error_deg": phase_error_deg,
                "measured_display_phase_deg": measured_display_phase_deg,
                "dac_signal_hz": dac_signal_value,
                "expected_signal_hz": signal_hz,
                "input_signal_hz": signal_hz,
                "input_source_mode": input_source_mode,
                "expected_baseband_hz": expected_baseband_hz,
                "expected_baseband_mhz": expected_baseband_hz / 1_000_000.0,
                "fft_peak_hz": float(fft_peak_hz),
                "fft_peak_mhz": float(fft_peak_hz / 1_000_000.0),
                "fft_peak_phase_deg": fft_peak_phase_deg,
                "amplitude_code": amplitude_code,
                "rms_code": rms_code,
                "max_abs_code": max_abs,
                "snr_db": float(snr_db),
                "fit_residual_rms_code": residual_rms_code,
                "fit_residual_fraction": residual_fraction,
                "fit_residual_db": 20.0 * np.log10(max(residual_fraction, 1e-12)),
                "clipped": bool(max_abs >= 32760.0),
            }
            channels[int(idx)] = item
            if int(idx) == int(phase_ref_input):
                ref_phase_error = phase_error_deg

        for item in channels.values():
            if ref_phase_error is not None:
                item["delta_phase_error_deg"] = T510FEngine._wrap_phase_deg(
                    float(item["phase_error_deg"]) - ref_phase_error
                )

        return {
            "input_mask": int(preview["input_mask"]),
            "inputs": list(preview["inputs"]),
            "sample0": sample0,
            "count": count,
            "sample_rate_hz": sample_rate,
            "axis_beat_rate_hz": float(preview.get("axis_beat_rate_hz", sample_rate)),
            "observe_center_hz": observe_center_hz,
            "dac_signal_hz": dac_signal_value,
            "expected_signal_hz": signal_hz,
            "input_signal_hz": signal_hz,
            "input_source_mode": input_source_mode,
            "expected_baseband_hz": expected_baseband_hz,
            "configured_phase_deg": float(configured_phase_deg),
            "phase_deg_by_channel": T510FEngine._normalize_phase_deg_by_channel(
                phase_deg_by_channel,
                phase_offset_deg=float(configured_phase_deg),
                phase_deg_per_channel=float(phase_deg_per_channel),
                count=8,
            ),
            "time_window_us": time_window_us,
            "display_points": int(display_points),
            "alignment_anchor_deg": 0.0 if alignment_anchor_deg is None else alignment_anchor_deg,
            "phase_ref_input": int(phase_ref_input),
            "phase_lock": "sample0_aligned_measured",
            "timestamp_model": "frame_sample0_plus_sample_index",
            "channels": channels,
        }

    @staticmethod
    def _wrap_phase_deg(value: float) -> float:
        while value > 180.0:
            value -= 360.0
        while value <= -180.0:
            value += 360.0
        return value

    @staticmethod
    def _interp_peak_from_power(freq_hz: Any, power: Any, peak_idx: int) -> float:
        import numpy as np

        peak_hz = float(freq_hz[peak_idx])
        if peak_idx <= 0 or peak_idx >= len(power) - 1:
            return peak_hz
        alpha = np.log(max(float(power[peak_idx - 1]), 1.0))
        beta = np.log(max(float(power[peak_idx]), 1.0))
        gamma = np.log(max(float(power[peak_idx + 1]), 1.0))
        denom = alpha - 2.0 * beta + gamma
        if abs(float(denom)) < 1e-12:
            return peak_hz
        delta = 0.5 * (alpha - gamma) / denom
        delta = float(np.clip(delta, -1.0, 1.0))
        return peak_hz + delta * float(freq_hz[1] - freq_hz[0])

    @staticmethod
    def _derive_rf_equivalent_waveform(
        i_data: Any,
        q_data: Any,
        *,
        sample0: int,
        sample_rate_hz: float,
        center_hz: float,
        mixer_sign: float = 1.0,
    ) -> Any:
        import math
        import numpy as np

        i_arr = np.asarray(i_data, dtype=np.float64)
        q_arr = np.asarray(q_data, dtype=np.float64)
        count = min(i_arr.size, q_arr.size)
        if count == 0:
            return np.asarray([], dtype=np.float64)
        sample_rate_hz = float(sample_rate_hz)
        if sample_rate_hz <= 0.0:
            raise ValueError("sample_rate_hz must be positive")
        center_hz = float(center_hz)
        mixer_sign = 1.0 if float(mixer_sign) >= 0.0 else -1.0
        start_cycles = math.fmod(float(sample0) * center_hz / sample_rate_hz, 1.0)
        cycles = start_cycles + (center_hz / sample_rate_hz) * np.arange(count, dtype=np.float64)
        phase = 2.0 * np.pi * np.mod(cycles, 1.0)
        return i_arr[:count] * np.cos(phase) - mixer_sign * q_arr[:count] * np.sin(phase)

    @staticmethod
    def _derive_rf_equivalent_waveform_at_times(
        i_data: Any,
        q_data: Any,
        time_us: Any,
        *,
        sample0: int,
        sample_rate_hz: float,
        center_hz: float,
        mixer_sign: float = 1.0,
    ) -> Any:
        import numpy as np

        i_arr = np.asarray(i_data, dtype=np.float64)
        q_arr = np.asarray(q_data, dtype=np.float64)
        t_arr = np.asarray(time_us, dtype=np.float64)
        count = min(i_arr.size, q_arr.size, t_arr.size)
        if count == 0:
            return np.asarray([], dtype=np.float64)
        sample_rate_hz = float(sample_rate_hz)
        if sample_rate_hz <= 0.0:
            raise ValueError("sample_rate_hz must be positive")
        mixer_sign = 1.0 if float(mixer_sign) >= 0.0 else -1.0
        sample_index = float(sample0) + t_arr[:count] * 1.0e-6 * sample_rate_hz
        phase = 2.0 * np.pi * np.mod(sample_index * float(center_hz) / sample_rate_hz, 1.0)
        return i_arr[:count] * np.cos(phase) - mixer_sign * q_arr[:count] * np.sin(phase)

    @staticmethod
    def _bandlimited_iq_interpolate_at_times(
        i_data: Any,
        q_data: Any,
        time_us: Any,
        *,
        sample_rate_hz: float,
        kernel_radius: int = 12,
    ) -> tuple[Any, Any]:
        import numpy as np

        i_arr = np.asarray(i_data, dtype=np.float64)
        q_arr = np.asarray(q_data, dtype=np.float64)
        t_arr = np.asarray(time_us, dtype=np.float64)
        count = min(i_arr.size, q_arr.size)
        if count == 0 or t_arr.size == 0:
            empty = np.asarray([], dtype=np.float64)
            return empty, empty
        if count < 4:
            nearest = np.clip(np.rint(t_arr * 1.0e-6 * float(sample_rate_hz)).astype(np.int64), 0, count - 1)
            return i_arr[nearest], q_arr[nearest]
        sample_rate_hz = float(sample_rate_hz)
        if sample_rate_hz <= 0.0:
            raise ValueError("sample_rate_hz must be positive")
        radius = max(2, int(kernel_radius))
        source = np.arange(count, dtype=np.float64)
        target = t_arr * 1.0e-6 * sample_rate_hz
        x = target[:, None] - source[None, :]
        weights = np.sinc(x) * np.sinc(x / float(radius))
        weights[np.abs(x) >= float(radius)] = 0.0
        norm = np.sum(weights, axis=1)
        valid = np.abs(norm) > 1.0e-12
        nearest = np.clip(np.rint(target).astype(np.int64), 0, count - 1)
        out_i = i_arr[nearest].astype(np.float64, copy=True)
        out_q = q_arr[nearest].astype(np.float64, copy=True)
        if np.any(valid):
            out_i[valid] = (weights[valid] @ i_arr[:count]) / norm[valid]
            out_q[valid] = (weights[valid] @ q_arr[:count]) / norm[valid]
        return out_i, out_q

    def compute_scope_spectrum(
        self,
        preview: Mapping[str, Any],
        *,
        display_bw_hz: Optional[float] = None,
        phase_ref_input: int = 0,
    ) -> dict[str, Any]:
        import numpy as np

        sample_rate = float(preview["sample_rate_hz"])
        count = int(preview["count"])
        sample0 = int(preview["sample0"])
        center_hz = float(preview.get("center_freq_hz", 0.0))
        bandwidth_hz = float(display_bw_hz if display_bw_hz is not None else preview.get("bandwidth_hz", sample_rate))
        time_us = np.arange(count, dtype=np.float64) / sample_rate * 1_000_000.0
        sample_index = sample0 + np.arange(count, dtype=np.int64)
        nfft = max(4096, count * 8)
        freq_hz = np.fft.fftshift(np.fft.fftfreq(nfft, d=1.0 / sample_rate))
        passband = np.abs(freq_hz) <= (bandwidth_hz / 2.0)
        if not np.any(passband):
            passband = np.ones_like(freq_hz, dtype=bool)

        scope: dict[int, dict[str, Any]] = {}
        spectra: dict[int, dict[str, Any]] = {}
        peaks: dict[int, dict[str, float | int | bool]] = {}
        ref_phase: Optional[float] = None
        ref_coherent_phase: Optional[float] = None
        window = np.hanning(count)
        for idx, iq in preview["iq"].items():
            arr = np.asarray(iq, dtype=np.float64)
            i_data = arr[:, 0]
            q_data = arr[:, 1]
            z_raw = i_data + 1j * q_data
            expected_is_dc = expected_offset_hz is not None and abs(expected_offset_hz) < (sample_rate / max(count, 1))
            z = z_raw if expected_is_dc else z_raw - np.mean(z_raw)
            fft = np.fft.fftshift(np.fft.fft(z * window, n=nfft))
            power = np.abs(fft) ** 2
            masked_power = np.where(passband, power, 0.0)
            peak_idx = int(np.argmax(masked_power))
            raw_peak_hz = float(freq_hz[peak_idx])
            peak_hz = self._interp_peak_from_power(freq_hz, masked_power, peak_idx)
            phase_deg = float(np.angle(fft[peak_idx], deg=True))
            sample0_phase = (360.0 * peak_hz * (sample0 / sample_rate)) % 360.0
            coherent_phase = self._wrap_phase_deg(phase_deg - sample0_phase)
            guard = max(2, nfft // 128)
            noise_mask = passband.copy()
            noise_mask[max(0, peak_idx - guard):min(len(noise_mask), peak_idx + guard + 1)] = False
            noise_floor = float(np.median(power[noise_mask])) if np.any(noise_mask) else 1.0
            peak_power = float(power[peak_idx])
            snr_db = 10.0 * np.log10(max(peak_power, 1.0) / max(noise_floor, 1.0))
            max_abs = float(np.max(np.abs(arr))) if arr.size else 0.0
            scope[idx] = {
                "time_us": time_us,
                "sample_index": sample_index,
                "i": i_data,
                "q": q_data,
                "waveform": i_data,
                "rms": float(np.sqrt(np.mean(i_data * i_data + q_data * q_data))),
                "max_abs_code": max_abs,
                "clipped": bool(max_abs >= 32760.0),
            }
            spectra[idx] = {
                "freq_hz": freq_hz,
                "freq_mhz": freq_hz / 1_000_000.0,
                "power": power,
                "power_db": 10.0 * np.log10(np.maximum(power, 1.0)),
            }
            peaks[idx] = {
                "peak_bin": peak_idx,
                "raw_peak_hz": raw_peak_hz,
                "peak_hz": peak_hz,
                "peak_mhz": peak_hz / 1_000_000.0,
                "rf_peak_hz": center_hz + peak_hz,
                "rf_peak_mhz": (center_hz + peak_hz) / 1_000_000.0,
                "peak_power": peak_power,
                "phase_deg": phase_deg,
                "coherent_phase_deg": coherent_phase,
                "snr_db": float(snr_db),
                "rms": scope[idx]["rms"],
                "max_abs_code": max_abs,
                "clipped": bool(max_abs >= 32760.0),
            }
            if idx == int(phase_ref_input):
                ref_phase = phase_deg
                ref_coherent_phase = coherent_phase
        for item in peaks.values():
            if ref_phase is not None:
                item["delta_phase_deg"] = self._wrap_phase_deg(float(item["phase_deg"]) - ref_phase)
            if ref_coherent_phase is not None:
                item["delta_coherent_phase_deg"] = self._wrap_phase_deg(
                    float(item["coherent_phase_deg"]) - ref_coherent_phase
                )
        return {
            "sample0": sample0,
            "count": count,
            "nfft": nfft,
            "input_mask": int(preview["input_mask"]),
            "inputs": list(preview["inputs"]),
            "sample_rate_hz": sample_rate,
            "axis_beat_rate_hz": float(preview.get("axis_beat_rate_hz", sample_rate)),
            "center_freq_hz": center_hz,
            "display_bw_hz": bandwidth_hz,
            "phase_ref_input": int(phase_ref_input),
            "scope": scope,
            "spectrum": spectra,
            "peaks": peaks,
        }

    @staticmethod
    def observation_capture_count(
        *,
        sample_rate_hz: float = 320_000_000.0,
        time_window_us: float = 0.25,
        oversample: float = 2.5,
        min_count: int = 512,
        max_count: int = 1024,
    ) -> int:
        import math

        sample_rate_hz = float(sample_rate_hz)
        time_window_us = float(time_window_us)
        oversample = float(oversample)
        if sample_rate_hz <= 0:
            raise ValueError("sample_rate_hz must be positive")
        if time_window_us <= 0:
            raise ValueError("time_window_us must be positive")
        if oversample <= 0:
            raise ValueError("oversample must be positive")
        needed = int(math.ceil(sample_rate_hz * time_window_us * 1e-6 * max(1.0, oversample)))
        count = max(int(min_count), needed)
        count = 1 << int(math.ceil(math.log2(max(2, count))))
        return min(int(max_count), count)

    def compute_observation_view(
        self,
        preview: Mapping[str, Any],
        *,
        observe_center_hz: float,
        view_bw_hz: float,
        dac_signal_hz: Optional[float] = None,
        expected_signal_hz: Optional[float] = None,
        time_window_us: float = 0.25,
        curve_points: int = 1024,
        oversample: float = 2.5,
        phase_ref_input: int = 0,
        stabilize_phase: bool = True,
        display_phase_deg: Optional[float] = None,
        phase_deg_by_channel: Optional[Mapping[Any, Any] | Iterable[Any]] = None,
        input_source_mode: str = "dac_loopback",
    ) -> dict[str, Any]:
        import math
        import numpy as np

        sample_rate = float(preview["sample_rate_hz"])
        count = int(preview["count"])
        sample0 = int(preview["sample0"])
        observe_center_hz = float(observe_center_hz)
        view_bw_hz = float(view_bw_hz)
        dac_signal_value = None if dac_signal_hz is None else float(dac_signal_hz)
        expected_signal_value = (
            dac_signal_value if expected_signal_hz is None else float(expected_signal_hz)
        )
        expected_offset_hz = (
            None if expected_signal_value is None else float(expected_signal_value - observe_center_hz)
        )
        expected_rf_hz = 0.0 if expected_signal_value is None else float(expected_signal_value)
        expected_baseband_hz = 0.0 if expected_offset_hz is None else float(expected_offset_hz)

        def _samples_per_cycle(freq_hz: float) -> float:
            freq_hz = float(freq_hz)
            if not math.isfinite(freq_hz) or abs(freq_hz) < 1.0:
                return math.inf
            return float(sample_rate / abs(freq_hz))

        rf_samples_per_cycle = _samples_per_cycle(expected_rf_hz)
        baseband_samples_per_cycle = _samples_per_cycle(expected_baseband_hz)
        expected_cycles_in_window = abs(expected_rf_hz) * float(time_window_us) * 1.0e-6
        expected_baseband_cycles_in_window = abs(expected_baseband_hz) * float(time_window_us) * 1.0e-6
        rf_near_nyquist = bool(math.isfinite(rf_samples_per_cycle) and rf_samples_per_cycle < 4.0)
        input_source_mode = self._normalize_input_source_mode(input_source_mode)
        cfg = getattr(self, "observation_instrument_config", None)
        if not isinstance(cfg, Mapping):
            cfg = {}
        display_phase_base_deg = (
            float(cfg.get("phase_deg", 0.0))
            if display_phase_deg is None else float(display_phase_deg)
        )
        display_phase_step_deg = float(cfg.get("phase_deg_per_channel", 0.0))
        display_phase_by_channel = (
            phase_deg_by_channel
            if phase_deg_by_channel is not None
            else cfg.get("phase_deg_by_channel")
        )
        nfft_min = max(4096, int(2 ** math.ceil(math.log2(max(2.0, count * max(float(oversample), 1.0))))))
        nfft = min(32768, nfft_min)
        raw_freq_hz = np.fft.fftshift(np.fft.fftfreq(nfft, d=1.0 / sample_rate))
        passband = np.abs(raw_freq_hz) <= (view_bw_hz / 2.0)
        if not np.any(passband):
            passband = np.ones_like(raw_freq_hz, dtype=bool)
        display_count = max(4, min(count, int(math.ceil(float(time_window_us) * 1e-6 * sample_rate)) + 1))
        curve_count = max(64, min(16384, int(curve_points)))
        time_us = np.arange(display_count, dtype=np.float64) / sample_rate * 1_000_000.0
        requested_time_us = np.linspace(0.0, float(time_window_us), curve_count, dtype=np.float64)
        captured_window_us = float(time_us[-1]) if time_us.size else 0.0

        scope: dict[int, dict[str, Any]] = {}
        baseband_scope: dict[int, dict[str, Any]] = {}
        spectra: dict[int, dict[str, Any]] = {}
        peaks: dict[int, dict[str, float | int | bool]] = {}
        ref_coherent_phase: Optional[float] = None
        window = np.hanning(count)
        window_norm = max(float(np.sum(window)), 1.0)
        full_scale = 32768.0

        for idx, iq in preview["iq"].items():
            arr = np.asarray(iq, dtype=np.float64)
            i_data = arr[:, 0]
            q_data = arr[:, 1]
            # Do not remove the complex mean here: in the astronomer view, a
            # signal exactly at the observation center is the science peak at
            # 0 Hz offset, not an unwanted DC term.
            z = i_data + 1j * q_data
            fft = np.fft.fftshift(np.fft.fft(z * window, n=nfft))
            power = np.abs(fft) ** 2
            masked_power = np.where(passband, power, 0.0)
            peak_idx = int(np.argmax(masked_power))
            raw_peak_hz = self._interp_peak_from_power(raw_freq_hz, masked_power, peak_idx)

            mixer_sign = 1.0
            if expected_offset_hz is not None:
                if abs((-raw_peak_hz) - expected_offset_hz) < abs(raw_peak_hz - expected_offset_hz):
                    mixer_sign = -1.0
            logical_peak_hz = mixer_sign * raw_peak_hz
            rf_peak_hz = observe_center_hz + logical_peak_hz
            rf_freq_mhz = (observe_center_hz + mixer_sign * raw_freq_hz) / 1_000_000.0

            t = np.arange(count, dtype=np.float64) / sample_rate
            basis = np.exp(1j * 2.0 * np.pi * raw_peak_hz * t)
            coeff = np.vdot(basis, z) / max(float(np.vdot(basis, basis).real), 1.0)
            phase_deg = float(np.angle(coeff, deg=True))
            sample0_phase = (360.0 * raw_peak_hz * (sample0 / sample_rate)) % 360.0
            coherent_phase = self._wrap_phase_deg(phase_deg - sample0_phase)
            amplitude = float(abs(coeff))
            raw_waveform = i_data[:display_count]
            raw_q_waveform = q_data[:display_count]
            raw_magnitude_waveform = np.abs(z[:display_count])
            rf_equivalent_waveform = self._derive_rf_equivalent_waveform(
                raw_waveform,
                raw_q_waveform,
                sample0=sample0,
                sample_rate_hz=sample_rate,
                center_hz=observe_center_hz,
                mixer_sign=mixer_sign,
            )
            curve_i, curve_q = self._bandlimited_iq_interpolate_at_times(
                raw_waveform,
                raw_q_waveform,
                requested_time_us,
                sample_rate_hz=sample_rate,
            )
            rf_equivalent_curve = self._derive_rf_equivalent_waveform_at_times(
                curve_i,
                curve_q,
                requested_time_us,
                sample0=sample0,
                sample_rate_hz=sample_rate,
                center_hz=observe_center_hz,
                mixer_sign=mixer_sign,
            )

            mag_dbfs = 20.0 * np.log10(np.maximum(np.abs(fft) / (window_norm * full_scale), 1e-12))
            x_axis = rf_freq_mhz
            y_axis = mag_dbfs
            if x_axis[0] > x_axis[-1]:
                x_axis = x_axis[::-1]
                y_axis = y_axis[::-1]

            guard = max(2, nfft // 128)
            noise_mask = passband.copy()
            noise_mask[max(0, peak_idx - guard):min(len(noise_mask), peak_idx + guard + 1)] = False
            noise_floor = float(np.median(power[noise_mask])) if np.any(noise_mask) else 1.0
            peak_power = float(power[peak_idx])
            snr_db = 10.0 * np.log10(max(peak_power, 1.0) / max(noise_floor, 1.0))
            max_abs = float(np.max(np.abs(arr))) if arr.size else 0.0
            rms_code = float(np.sqrt(np.mean(i_data * i_data + q_data * q_data))) if arr.size else 0.0
            peak_dbfs = 20.0 * np.log10(
                max(float(np.abs(fft[peak_idx])) / (window_norm * full_scale), 1e-12)
            )
            noise_floor_dbfs = 20.0 * np.log10(
                max(float(np.sqrt(max(noise_floor, 1.0))) / (window_norm * full_scale), 1e-12)
            )
            rms_dbfs = 20.0 * np.log10(max(rms_code / full_scale, 1e-12))

            scope[idx] = {
                "time_us": time_us,
                "time_axis_source": "sample0_plus_sample_index_over_preview_sample_rate",
                "waveform_i": raw_waveform,
                "waveform_q": raw_q_waveform,
                "waveform_mag": raw_magnitude_waveform,
                "rf_equivalent_waveform": rf_equivalent_waveform,
                "rf_equivalent_time_us": time_us,
                "rf_equivalent_curve_waveform": rf_equivalent_curve,
                "rf_equivalent_curve_time_us": requested_time_us,
                "rf_equivalent_center_hz": observe_center_hz,
                "rf_equivalent_carrier_hz": observe_center_hz,
                "rf_equivalent_mixer_sign": int(mixer_sign),
                "derived_from_real_iq": True,
                "raw_rf": False,
                "raw_waveform": raw_waveform,
                "raw_q_waveform": raw_q_waveform,
                "raw_magnitude_waveform": raw_magnitude_waveform,
                "frequency_hz": raw_peak_hz,
                "frequency_mhz": raw_peak_hz / 1_000_000.0,
                "phase_deg": coherent_phase,
                "point_count": display_count,
                "source": "rfdc_preview_buffer",
                "waveform_source": "rfdc_preview_buffer",
                "virtual_waveform": False,
                "preview_mode": int(preview.get("preview_mode", 0)),
                "sample0": sample0,
                "sample_rate_hz": sample_rate,
                "expected_rf_hz": expected_rf_hz,
                "expected_rf_mhz": expected_rf_hz / 1_000_000.0,
                "expected_baseband_hz": expected_baseband_hz,
                "expected_baseband_mhz": expected_baseband_hz / 1_000_000.0,
                "requested_window_us": float(time_window_us),
                "captured_window_us": captured_window_us,
                "real_sample_count": int(display_count),
                "rf_curve_point_count": int(curve_count),
                "measured_rf_peak_hz": rf_peak_hz,
                "measured_rf_peak_mhz": rf_peak_hz / 1_000_000.0,
                "measured_baseband_hz": logical_peak_hz,
                "measured_baseband_mhz": logical_peak_hz / 1_000_000.0,
                "rf_samples_per_cycle": rf_samples_per_cycle,
                "baseband_samples_per_cycle": baseband_samples_per_cycle,
                "expected_cycles_in_window": expected_cycles_in_window,
                "expected_baseband_cycles_in_window": expected_baseband_cycles_in_window,
                "rf_near_nyquist_warning": rf_near_nyquist,
                "rms": rms_code,
                "rms_dbfs": rms_dbfs,
                "max_abs_code": max_abs,
                "clipped": bool(max_abs >= 32760.0),
            }
            baseband_scope[idx] = {
                "time_us": time_us,
                "time_axis_source": "sample0_plus_sample_index_over_preview_sample_rate",
                "waveform": raw_waveform,
                "raw_waveform": raw_waveform,
                "raw_q_waveform": raw_q_waveform,
                "raw_magnitude_waveform": raw_magnitude_waveform,
                "rf_equivalent_waveform": rf_equivalent_waveform,
                "rf_equivalent_time_us": time_us,
                "rf_equivalent_curve_waveform": rf_equivalent_curve,
                "rf_equivalent_curve_time_us": requested_time_us,
                "rf_equivalent_center_hz": observe_center_hz,
                "rf_equivalent_mixer_sign": int(mixer_sign),
                "derived_from_real_iq": True,
                "raw_rf": False,
                "waveform_source": "rfdc_preview_buffer",
                "virtual_waveform": False,
                "preview_mode": int(preview.get("preview_mode", 0)),
                "sample0": sample0,
                "sample_rate_hz": sample_rate,
                "expected_rf_hz": expected_rf_hz,
                "expected_baseband_hz": expected_baseband_hz,
                "requested_window_us": float(time_window_us),
                "captured_window_us": captured_window_us,
                "real_sample_count": int(display_count),
                "rf_curve_point_count": int(curve_count),
                "rf_samples_per_cycle": rf_samples_per_cycle,
                "baseband_samples_per_cycle": baseband_samples_per_cycle,
                "expected_cycles_in_window": expected_cycles_in_window,
                "expected_baseband_cycles_in_window": expected_baseband_cycles_in_window,
                "rf_near_nyquist_warning": rf_near_nyquist,
                "frequency_hz": raw_peak_hz,
                "frequency_mhz": raw_peak_hz / 1_000_000.0,
                "phase_deg": coherent_phase,
                "rms": rms_code,
                "rms_dbfs": rms_dbfs,
                "max_abs_code": max_abs,
                "clipped": bool(max_abs >= 32760.0),
            }
            spectra[idx] = {
                "rf_mhz": x_axis,
                "power_dbfs": y_axis,
                "raw_baseband_mhz": raw_freq_hz / 1_000_000.0,
                "peak_dbfs": peak_dbfs,
                "noise_floor_dbfs": noise_floor_dbfs,
                "rms_dbfs": rms_dbfs,
                "valid_frame": True,
                "reject_reason": "",
            }
            peaks[idx] = {
                "peak_bin": peak_idx,
                "raw_baseband_hz": raw_peak_hz,
                "raw_baseband_mhz": raw_peak_hz / 1_000_000.0,
                "mixer_sign": int(mixer_sign),
                "baseband_hz": logical_peak_hz,
                "baseband_mhz": logical_peak_hz / 1_000_000.0,
                "rf_peak_hz": rf_peak_hz,
                "rf_peak_mhz": rf_peak_hz / 1_000_000.0,
                "expected_baseband_hz": 0.0 if expected_offset_hz is None else expected_offset_hz,
                "expected_baseband_mhz": expected_baseband_hz / 1_000_000.0,
                "dac_signal_hz": 0.0 if dac_signal_value is None else dac_signal_value,
                "expected_rf_hz": 0.0 if expected_signal_value is None else expected_signal_value,
                "expected_rf_mhz": expected_rf_hz / 1_000_000.0,
                "expected_signal_hz": 0.0 if expected_signal_value is None else expected_signal_value,
                "input_signal_hz": 0.0 if expected_signal_value is None else expected_signal_value,
                "input_source_mode": input_source_mode,
                "phase_deg": phase_deg,
                "coherent_phase_deg": coherent_phase,
                "snr_db": float(snr_db),
                "rms": scope[idx]["rms"],
                "rms_dbfs": rms_dbfs,
                "peak_dbfs": peak_dbfs,
                "noise_floor_dbfs": noise_floor_dbfs,
                "rf_samples_per_cycle": rf_samples_per_cycle,
                "baseband_samples_per_cycle": baseband_samples_per_cycle,
                "expected_cycles_in_window": expected_cycles_in_window,
                "rf_near_nyquist_warning": rf_near_nyquist,
                "max_abs_code": max_abs,
                "clipped": bool(max_abs >= 32760.0),
                "valid_frame": True,
                "reject_reason": "",
            }
            if idx == int(phase_ref_input):
                ref_coherent_phase = coherent_phase

        for item in peaks.values():
            if ref_coherent_phase is not None:
                item["delta_coherent_phase_deg"] = self._wrap_phase_deg(
                    float(item["coherent_phase_deg"]) - ref_coherent_phase
                )
        measured_peak = (
            dict(peaks[int(phase_ref_input)])
            if int(phase_ref_input) in peaks
            else (dict(next(iter(peaks.values()))) if peaks else {})
        )

        return {
            "sample0": sample0,
            "count": count,
            "display_count": display_count,
            "rf_curve_point_count": int(curve_count),
            "nfft": nfft,
            "input_mask": int(preview["input_mask"]),
            "inputs": list(preview["inputs"]),
            "sample_rate_hz": sample_rate,
            "axis_beat_rate_hz": float(preview.get("axis_beat_rate_hz", sample_rate)),
            "time_axis_source": "sample0_plus_sample_index_over_preview_sample_rate",
            "observe_center_hz": observe_center_hz,
            "view_bw_hz": view_bw_hz,
            "dac_signal_hz": 0.0 if dac_signal_value is None else dac_signal_value,
            "expected_signal_hz": 0.0 if expected_signal_value is None else expected_signal_value,
            "input_signal_hz": 0.0 if expected_signal_value is None else expected_signal_value,
            "input_source_mode": input_source_mode,
            "expected_rf_hz": expected_rf_hz,
            "expected_baseband_hz": expected_baseband_hz,
            "rf_samples_per_cycle": rf_samples_per_cycle,
            "baseband_samples_per_cycle": baseband_samples_per_cycle,
            "expected_cycles_in_window": expected_cycles_in_window,
            "expected_baseband_cycles_in_window": expected_baseband_cycles_in_window,
            "rf_near_nyquist_warning": rf_near_nyquist,
            "measured_peak": measured_peak,
            "time_window_us": float(time_window_us),
            "requested_window_us": float(time_window_us),
            "captured_window_us": captured_window_us,
            "oversample": float(oversample),
            "phase_ref_input": int(phase_ref_input),
            "stabilize_phase": bool(stabilize_phase),
            "phase_lock": "rfdc_preview_buffer",
            "scope": scope,
            "real_preview_scope": scope,
            "rf_scope": scope,
            "baseband_scope": baseband_scope,
            "spectrum": spectra,
            "peaks": peaks,
        }

    def capture_preview_spectrum(
        self,
        *,
        input_mask: int = 0x01,
        n: Optional[int] = None,
        timeout: float = 1.0,
    ) -> dict[str, Any]:
        preview = self.capture_preview(n=n, input_mask=input_mask, timeout=timeout)
        import numpy as np

        spectra: dict[int, Any] = {}
        shifted_spectra: dict[int, Any] = {}
        peaks: dict[int, dict[str, float | int]] = {}
        sample_rate = int(preview["sample_rate_hz"])
        count = int(preview["count"])
        freq_hz = np.arange(count, dtype=np.float64) * (sample_rate / count)
        signed_freq_hz = np.fft.fftshift(np.fft.fftfreq(count, d=1.0 / sample_rate))

        def interp_peak_hz(power_array: Any, peak_idx: int) -> float:
            peak_hz = float(signed_freq_hz[peak_idx])
            if peak_idx <= 0 or peak_idx >= count - 1:
                return peak_hz
            alpha = np.log(max(float(power_array[peak_idx - 1]), 1.0))
            beta = np.log(max(float(power_array[peak_idx]), 1.0))
            gamma = np.log(max(float(power_array[peak_idx + 1]), 1.0))
            denom = alpha - 2.0 * beta + gamma
            if abs(float(denom)) < 1e-12:
                return peak_hz
            delta = 0.5 * (alpha - gamma) / denom
            delta = float(np.clip(delta, -1.0, 1.0))
            return peak_hz + delta * (sample_rate / count)

        ref_phase: Optional[float] = None
        for idx, iq in preview["iq"].items():
            arr = np.asarray(iq, dtype=np.float64)
            complex_samples = arr[:, 0] + 1j * arr[:, 1]
            fft = np.fft.fft(complex_samples)
            power = np.abs(fft) ** 2
            peak_bin = int(np.argmax(power))
            shifted_power = np.fft.fftshift(power)
            shifted_peak_idx = int(np.argmax(shifted_power))
            raw_signed_peak_hz = float(signed_freq_hz[shifted_peak_idx])
            signed_peak_hz = interp_peak_hz(shifted_power, shifted_peak_idx)
            phase_deg = float(np.angle(fft[peak_bin], deg=True))
            if idx == int(preview.get("phase_ref_input", 0)):
                ref_phase = phase_deg
            spectra[idx] = power
            shifted_spectra[idx] = shifted_power
            peaks[idx] = {
                "peak_bin": peak_bin,
                "display_bin": min(peak_bin, count - peak_bin),
                "raw_peak_hz": raw_signed_peak_hz,
                "peak_hz": signed_peak_hz,
                "peak_mhz": signed_peak_hz / 1_000_000.0,
                "rf_peak_hz": float(preview.get("center_freq_hz", 0.0)) + signed_peak_hz,
                "peak_power": float(power[peak_bin]),
                "phase_deg": phase_deg,
            }
        if ref_phase is not None:
            for item in peaks.values():
                delta = float(item["phase_deg"]) - ref_phase
                while delta > 180.0:
                    delta -= 360.0
                while delta <= -180.0:
                    delta += 360.0
                item["delta_phase_deg"] = delta
        return {
            "input_mask": preview["input_mask"],
            "inputs": preview["inputs"],
            "sample0": preview["sample0"],
            "sample_rate_hz": sample_rate,
            "axis_beat_rate_hz": preview.get("axis_beat_rate_hz", sample_rate),
            "preview_mode": preview.get("preview_mode", 0),
            "phase_ref_input": preview.get("phase_ref_input", 0),
            "center_freq_hz": preview.get("center_freq_hz", 0.0),
            "bandwidth_hz": preview.get("bandwidth_hz", 0.0),
            "freq_hz": freq_hz,
            "signed_freq_hz": signed_freq_hz,
            "power": spectra,
            "shifted_power": shifted_spectra,
            "peaks": peaks,
        }

    def plot_time(self, n: Optional[int] = None, *, timeout: float = 1.0) -> Any:
        samples = self.capture_time(n=n, timeout=timeout)
        import numpy as np
        import matplotlib.pyplot as plt

        samples = np.asarray(samples)
        fig, ax = plt.subplots()
        ax.plot(samples[:, 0], label="I")
        ax.plot(samples[:, 1], label="Q")
        ax.set_title("T510 F-engine ADC0 debug time capture")
        ax.set_xlabel("sample @ 61.44 MHz observer rate")
        ax.set_ylabel("ADC code")
        ax.grid(True)
        ax.legend()
        return fig

    def plot_spectrum(self, *, timeout: float = 1.0) -> Any:
        spec = self.capture_spectrum(timeout=timeout)
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots()
        ax.plot(spec["freq_hz"], spec["power"])
        ax.set_title(f"T510 F-engine hardware FFT debug spectrum, peak bin {spec['peak_bin']}")
        ax.set_xlabel("frequency (Hz), unshifted 1024-point FFT")
        ax.set_ylabel("power")
        ax.grid(True)
        return fig

    def snapshot(self, nsamp: int = 1024) -> Any:
        return self.capture_time(n=nsamp)
