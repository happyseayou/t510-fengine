from __future__ import annotations

from dataclasses import dataclass
from ipaddress import IPv4Address
import time
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
    RFDC_STATUS_FLAGS: int = 0x0340
    RFDC_SAMPLE_COUNT_LO: int = 0x0344
    RFDC_SAMPLE_COUNT_HI: int = 0x0348
    RFDC_DROPPED_COUNT: int = 0x034C
    RFDC_ACTIVE_MASK: int = 0x0350
    RFDC_CURRENT_VALID_MASK: int = 0x0354
    RFDC_SEEN_VALID_MASK: int = 0x0358
    TX_LINK_STATUS_FLAGS: int = 0x0360
    TX_DRY_RUN_PACKET_COUNT: int = 0x0364
    TX_DRY_RUN_BYTE_COUNT: int = 0x0368
    TX_FIFO_LEVEL_WORDS: int = 0x036C
    TX_FIFO_HIGH_WATER_WORDS: int = 0x0370
    TX_FIFO_BACKPRESSURE_CYCLES: int = 0x0374
    TX_HEADER_CAPTURE_CONTROL: int = 0x0378
    TX_HEADER_CAPTURE_STATUS: int = 0x037C
    TX_HEADER_CAPTURE_BUFFER_BASE: int = 0x0380
    DEBUG_CONTROL: int = 0x0400
    DEBUG_STATUS: int = 0x0404
    DEBUG_NFFT: int = 0x0408
    DEBUG_OBS_SAMPLE_RATE_HZ: int = 0x040C
    DEBUG_PEAK_BIN: int = 0x0410
    DEBUG_PEAK_POWER: int = 0x0414
    DEBUG_CAPTURE_COUNT: int = 0x0418
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
    PREVIEW_AUDIT_CONTROL: int = 0x0730
    PREVIEW_AUDIT_STATUS: int = 0x0734
    PREVIEW_AUDIT_START_COUNT: int = 0x0738
    PREVIEW_AUDIT_FIRST_COUNT: int = 0x073C
    PREVIEW_AUDIT_DONE_COUNT: int = 0x0740
    PREVIEW_AUDIT_START_SAMPLE0_LO: int = 0x0744
    PREVIEW_AUDIT_START_SAMPLE0_HI: int = 0x0748
    PREVIEW_AUDIT_FIRST_SAMPLE0_LO: int = 0x074C
    PREVIEW_AUDIT_FIRST_SAMPLE0_HI: int = 0x0750
    PREVIEW_AUDIT_DONE_SAMPLE0_LO: int = 0x0754
    PREVIEW_AUDIT_DONE_SAMPLE0_HI: int = 0x0758
    PREVIEW_AUDIT_START_TO_FIRST_LATENCY: int = 0x075C
    PREVIEW_AUDIT_CAPTURE_BEATS: int = 0x0760
    PREVIEW_AUDIT_VALID_GAP_COUNT: int = 0x0764
    PREVIEW_AUDIT_SAMPLE0_ERROR_COUNT: int = 0x0768
    PREVIEW_AUDIT_EVENT_THRESHOLD: int = 0x0770
    PREVIEW_EVENT_SAMPLE0_LO: int = 0x0774
    PREVIEW_EVENT_SAMPLE0_HI: int = 0x0778
    PREVIEW_EVENT_MAX_CODE: int = 0x077C
    PREVIEW_EVENT_INFO: int = 0x0780
    PREVIEW_EVENT_RFDC_FLAGS: int = 0x0784
    PREVIEW_EVENT_DAC_PHASE_EPOCH: int = 0x0788
    PREVIEW_EVENT_BUFFER_WORDS: int = 0x078C
    PREVIEW_EVENT_BUFFER_BASE: int = 0x0A800
    PREVIEW_EVENT_BUFFER_STRIDE: int = 0x0100
    TX_PAYLOAD_WITNESS_CONTROL: int = 0x0790
    TX_PAYLOAD_WITNESS_STATUS: int = 0x0794
    TX_PAYLOAD_WITNESS_STREAM_FILTER: int = 0x0798
    TX_PAYLOAD_WITNESS_CAPTURE_WORDS: int = 0x079C
    TX_PAYLOAD_WITNESS_SAMPLE0_LO: int = 0x07A0
    TX_PAYLOAD_WITNESS_SAMPLE0_HI: int = 0x07A4
    TX_PAYLOAD_WITNESS_FRAME_ID_LO: int = 0x07A8
    TX_PAYLOAD_WITNESS_FRAME_ID_HI: int = 0x07AC
    TX_PAYLOAD_WITNESS_SEQ_NO: int = 0x07B0
    TX_PAYLOAD_WITNESS_CHAN0: int = 0x07B4
    TX_PAYLOAD_WITNESS_LAYOUT_LO: int = 0x07B8
    TX_PAYLOAD_WITNESS_LAYOUT_HI: int = 0x07BC
    TX_PAYLOAD_WITNESS_PAYLOAD_BYTES: int = 0x07C0
    TX_PAYLOAD_WITNESS_ROUTE_META: int = 0x07C4
    TX_PAYLOAD_WITNESS_RFDC_FLAGS: int = 0x07C8
    TX_PAYLOAD_WITNESS_DAC_PHASE_EPOCH: int = 0x07CC
    TX_PAYLOAD_WITNESS_RFDC_SAMPLE_COUNT_LO: int = 0x07D0
    TX_PAYLOAD_WITNESS_RFDC_SAMPLE_COUNT_HI: int = 0x07D4
    TX_PAIRED_COHERENCE_STATUS: int = 0x07D8
    TX_PAIRED_SOURCE_SAMPLE0_LO: int = 0x07DC
    TX_PAIRED_SOURCE_SAMPLE0_HI: int = 0x07E0
    TX_PAIRED_PREVIEW_SAMPLE0_LO: int = 0x07E4
    TX_PAIRED_PREVIEW_SAMPLE0_HI: int = 0x07E8
    TX_PAIRED_HEADER_SAMPLE0_LO: int = 0x07EC
    TX_PAIRED_HEADER_SAMPLE0_HI: int = 0x07F0
    TX_PAIRED_SAMPLE0_DELTA_LO: int = 0x07F4
    TX_PAIRED_SAMPLE0_DELTA_HI: int = 0x07F8
    TX_PAIRED_RFDC_FLAGS: int = 0x07FC
    TX_PAYLOAD_WITNESS_BUFFER_BASE: int = 0x10000
    TX_PAYLOAD_WITNESS_BUFFER_WORDS: int = 1056
    RFDC_AXIS_RAW_WITNESS_CONTROL: int = 0x0E200
    RFDC_AXIS_RAW_WITNESS_STATUS: int = 0x0E204
    RFDC_AXIS_RAW_WITNESS_CHANNEL_SELECT: int = 0x0E208
    RFDC_AXIS_RAW_WITNESS_CAPTURE_BEATS: int = 0x0E20C
    RFDC_AXIS_RAW_WITNESS_SAMPLE0_LO: int = 0x0E210
    RFDC_AXIS_RAW_WITNESS_SAMPLE0_HI: int = 0x0E214
    RFDC_AXIS_RAW_WITNESS_RFDC_FLAGS: int = 0x0E218
    RFDC_AXIS_RAW_WITNESS_WORD_COUNT: int = 0x0E21C
    RFDC_AXIS_RAW_WITNESS_BUFFER_WORDS_REG: int = 0x0E220
    RFDC_AXIS_RAW_WITNESS_VALID_MASK: int = 0x0E224
    RFDC_AXIS_RAW_WITNESS_BUFFER_BASE: int = 0x0E800
    RFDC_AXIS_RAW_WITNESS_BUFFER_WORDS: int = 1024
    SCIENCE_CONTROL: int = 0x0D000
    SCIENCE_STATUS: int = 0x0D004
    SCIENCE_BANDWIDTH_MODE: int = 0x0D008
    SCIENCE_OUTPUT_MODE: int = 0x0D00C
    SCIENCE_SAMPLE_RATE_HZ: int = 0x0D010
    SCIENCE_DECIM_FACTOR: int = 0x0D014
    SCIENCE_PAYLOAD_RATE_MBPS: int = 0x0D018
    SCIENCE_BLOCK_REASON: int = 0x0D01C
    SCIENCE_CAPABILITY: int = 0x0D020
    DAC_TX_WITNESS_CONTROL: int = 0x0B600
    DAC_TX_WITNESS_STATUS: int = 0x0B604
    DAC_TX_WITNESS_CAPTURE_WORDS: int = 0x0B608
    DAC_TX_WITNESS_BUFFER_WORDS_REG: int = 0x0B60C
    DAC_TX_WITNESS_PHASE_EPOCH: int = 0x0B610
    DAC_TX_WITNESS_PHASE_ACC: int = 0x0B614
    DAC_TX_WITNESS_PHASE_STEP: int = 0x0B618
    DAC_TX_WITNESS_PHASE0: int = 0x0B61C
    DAC_TX_WITNESS_MODE: int = 0x0B620
    DAC_TX_WITNESS_READY_GAP_COUNT: int = 0x0B624
    DAC_TX_WITNESS_BUFFER_BASE: int = 0x0C000
    DAC_TX_WITNESS_BUFFER_WORDS: int = 256
    DAC_AUDIT_PHASE_EPOCH_SEEN: int = 0x06E0
    DAC_AUDIT_CH0_PHASE_ACC: int = 0x06E4
    DAC_AUDIT_CH0_PHASE_STEP: int = 0x06E8
    DAC_AUDIT_CH0_PHASE0: int = 0x06EC
    DAC_AUDIT_CH0_MODE: int = 0x06F0
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
    TX_FRAME_CAPTURE_CONTROL: int = 0xB030
    TX_FRAME_CAPTURE_STATUS: int = 0xB034
    TX_FRAME_CAPTURE_BUFFER_BASE: int = 0xB040
    TX_ENDPOINT_BASE: int = 0xB100
    TX_ENDPOINT_STRIDE: int = 0x0020
    TX_SPEC_ROUTE_BASE: int = 0xB300
    TX_SPEC_ROUTE_STRIDE: int = 0x0020
    TX_TIME_ROUTE_BASE: int = 0xB500
    TX_TIME_ROUTE_STRIDE: int = 0x0020
    QSFP_TEST_INTERVAL_CYCLES: int = 0xB700
    MONITOR_CLIP_BASE: int = 0x0500
    MONITOR_MEAN_BASE: int = 0x0520
    DEBUG_TIME_BUFFER_BASE: int = 0x0800
    DEBUG_FFT_BUFFER_BASE: int = 0x1800
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

    def configure(self, ref: str) -> dict[str, Any]:
        try:
            from .t510_clock import T510ClockController
        except ImportError:
            from t510_clock import T510ClockController

        if ref == "tcxo_10mhz":
            self.last_config = T510ClockController().configure_tcxo_245p76()
        elif ref == "external_10mhz":
            self.last_config = T510ClockController().configure_external_10mhz_245p76()
        else:
            self.last_config = {"ref": ref, "configured": False, "reason": "unsupported reference selected"}
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

        result = T510ClockController().set_sysref(bool(enable))
        self.last_config["sysref_enabled"] = bool(enable)
        return result

    def pulse_sysref(self, *, width_s: float = 0.05, settle_s: float = 0.05) -> dict[str, Any]:
        try:
            from .t510_clock import T510ClockController
        except ImportError:
            from t510_clock import T510ClockController

        result = T510ClockController().pulse_sysref(width_s=width_s, settle_s=settle_s)
        self.last_config["sysref_enabled"] = False
        return result


class T510FEngine:
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
    DAC_MODES = {
        "single_tone": 0,
        "tone": 0,
        "constant_phasor": 1,
        "constant": 1,
        "phasor": 1,
    }
    SCIENCE_BANDWIDTHS: dict[int, dict[str, Any]] = {
        20: {"code": 0, "pl_decim": 8, "sample_rate_hz": 30_720_000.0},
        100: {"code": 1, "pl_decim": 2, "sample_rate_hz": 122_880_000.0},
        200: {"code": 2, "pl_decim": 1, "sample_rate_hz": 245_760_000.0},
    }
    SCIENCE_BANDWIDTH_BY_CODE = {
        int(item["code"]): bandwidth_mhz for bandwidth_mhz, item in SCIENCE_BANDWIDTHS.items()
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
        1: "SPEC_SCIENCE_BLOCKED_PFB_SCAFFOLD",
        2: "CMAC_LIVE_BLOCKED_NO_GT_DATAPATH",
        3: "WIDE_512B_TX_PATH_NOT_IMPLEMENTED",
        4: "RFDC_SCIENCE_BUS_TRUNCATED_TO_LOW16",
        5: "CMAC_LINK_NOT_READY",
        6: "FORCED_DRY_RUN",
    }

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

    def _write64(self, lo_offset: int, value: int) -> None:
        self.ctrl.write(lo_offset, value & 0xFFFF_FFFF)
        self.ctrl.write(lo_offset + 4, (value >> 32) & 0xFFFF_FFFF)

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

    def configure_clock(self, ref: str = "external_10mhz") -> dict[str, Any]:
        try:
            clock_ref = self.CLOCK_REFS[ref]
        except KeyError as exc:
            raise ValueError(f"Unsupported reference source: {ref}")
        self.clock_status = self.clock.configure(ref)
        self._write_sync_config(clock_ref=clock_ref)
        self.clock_reference = ref
        return dict(self.clock_status)

    def set_sync_mode(self, mode: str) -> None:
        try:
            sync_mode = self.SYNC_MODES[mode.lower()]
        except KeyError as exc:
            raise ValueError(f"Unsupported sync mode: {mode}") from exc
        self._write_sync_config(sync_mode=sync_mode)

    def set_adc_active_mask(self, mask: int) -> None:
        if mask <= 0 or mask > 0xFFFF:
            raise ValueError("ADC active mask must be in range 0x0001..0xffff")
        self._ensure_sync_config_mutable()
        self.ctrl.write(self.regs.RFDC_ACTIVE_MASK, mask & 0xFFFF)

    def configure_rfdc(
        self,
        *,
        fs_adc: int,
        f_center: float,
        bandwidth: float,
        decimation: int,
    ) -> None:
        self.ctrl.write(self.regs.SAMPLE_RATE_HZ, fs_adc)
        self.rfdc_config = {
            "fs_adc": fs_adc,
            "f_center": f_center,
            "bandwidth": bandwidth,
            "decimation": decimation,
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
        if center_freq_hz <= 0:
            raise ValueError("center_freq_hz must be positive")
        if bandwidth_hz <= 0:
            raise ValueError("bandwidth_hz must be positive")
        result = self._configure_rfdc_nco_pair(
            adc_nco_hz=-center_freq_hz,
            dac_nco_hz=center_freq_hz,
            bandwidth_hz=bandwidth_hz,
            require=require,
        )
        self.rfdc_config = {
            "fs_adc": 245_760_000,
            "f_center": center_freq_hz,
            "bandwidth": bandwidth_hz,
            "decimation": 20,
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
                        results.append(
                            {
                                "kind": tile_kind,
                                "tile": tile_idx,
                                "block": block_idx,
                                "requested_freq_mhz": float(freq_mhz),
                                "readback_freq_mhz": float(readback.get("Freq", freq_mhz)),
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
        configured = adc_count > 0 and dac_count > 0 and not failures
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
    ) -> dict[str, Any]:
        try:
            import xrfdc  # type: ignore
        except ImportError:
            xrfdc = None  # type: ignore[assignment]
        event_sysref = self._xrfdc_const(xrfdc, ("EVNT_SRC_SYSREF", "XRFDC_EVNT_SRC_SYSREF"), 2)
        event_mixer = self._xrfdc_const(xrfdc, ("EVENT_MIXER", "XRFDC_EVENT_MIXER"), 1)
        mixer_type_fine = self._xrfdc_const(xrfdc, ("MIXER_TYPE_FINE", "XRFDC_MIXER_TYPE_FINE"), 2)
        mode_r2c = self._xrfdc_const(xrfdc, ("MIXER_MODE_R2C", "XRFDC_MIXER_MODE_R2C"), 1)
        mode_c2r = self._xrfdc_const(xrfdc, ("MIXER_MODE_C2R", "XRFDC_MIXER_MODE_C2R"), 2)
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
                settings["EventSource"] = event_sysref
                settings["MixerType"] = mixer_type_fine
                settings["MixerMode"] = mixer_mode
                block.MixerSettings = settings
                if hasattr(block, "ResetNCOPhase"):
                    block.ResetNCOPhase()
                elif hasattr(block, "reset_nco_phase"):
                    block.reset_nco_phase()
                else:
                    raise RuntimeError("ResetNCOPhase API unavailable")
                readback = dict(getattr(block, "MixerSettings", settings))
                results.append(
                    {
                        "kind": tile_kind,
                        "tile": tile_idx,
                        "block": block_idx,
                        "requested_freq_mhz": float(freq_mhz),
                        "readback_freq_mhz": float(readback.get("Freq", freq_mhz)),
                        "event_source": readback.get("EventSource"),
                        "mixer_mode": readback.get("MixerMode"),
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
            dac_cfg, dac_init = self._new_mts_config(
                ffi,
                lib,
                tiles=dac_tile_mask,
                ref_tile=int(dac_ref_tile),
                target_latency=int(target_latency),
            )
            adc_cfg, adc_init = self._new_mts_config(
                ffi,
                lib,
                tiles=adc_tile_mask,
                ref_tile=int(adc_ref_tile),
                target_latency=int(target_latency),
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

    def probe_rfdc_mts_matrix(
        self,
        *,
        ref_tiles: Iterable[int] = (0, 1, 2, 3),
        tile_masks: Iterable[int] = (0x1, 0x3, 0xF),
        target_latency: int = -1,
        max_cases: int = 16,
    ) -> dict[str, Any]:
        """Run bounded MTS sync probes across tile masks/ref tiles.

        This is intentionally explicit and opt-in because it toggles RFDC MTS
        state. It is used by Stage 18 to learn whether the blocker is global
        SYSREF/marker behavior or a specific tile group.
        """
        rows: list[dict[str, Any]] = []
        cases = 0
        for mask in tile_masks:
            mask_i = int(mask) & 0xF
            if mask_i == 0:
                continue
            for ref in ref_tiles:
                ref_i = int(ref)
                if not (mask_i & (1 << ref_i)):
                    rows.append(
                        {
                            "tile_mask": mask_i,
                            "ref_tile": ref_i,
                            "skipped": True,
                            "reason": "ref_tile_not_in_tile_mask",
                        }
                    )
                    continue
                if cases >= int(max_cases):
                    rows.append({"skipped": True, "reason": "max_cases_reached", "max_cases": int(max_cases)})
                    return {"rows": rows, "max_cases": int(max_cases)}
                cases += 1
                try:
                    mts = self._run_rfdc_mts_sequence(
                        required=False,
                        adc_tiles=mask_i,
                        dac_tiles=mask_i,
                        adc_ref_tile=ref_i,
                        dac_ref_tile=ref_i,
                        target_latency=int(target_latency),
                    )
                    rows.append(
                        {
                            "tile_mask": mask_i,
                            "ref_tile": ref_i,
                            "ok": not bool(mts.get("failures")),
                            "details": mts,
                        }
                    )
                except Exception as exc:
                    rows.append(
                        {
                            "tile_mask": mask_i,
                            "ref_tile": ref_i,
                            "ok": False,
                            "error": str(exc),
                        }
                    )
        return {"rows": rows, "max_cases": int(max_cases)}

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
        )
        mixer = self._configure_rfdc_mixer_blocks_sysref(
            adc_nco_hz=float(adc_nco_hz),
            dac_nco_hz=float(dac_nco_hz),
            require=require,
        )
        result["mixer"] = mixer
        mts_available = bool(result["mts"].get("available", True))
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
        result["configured"] = bool(mixer.get("configured"))
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
        """Stage 18 deterministic observation init with real MTS/SYSREF as a hard prerequisite."""
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
        config["stage18_mts_locked"] = True
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
        force_clock_reconfigure: bool = False,
        dac_source_mode: str = "constant_phasor",
        input_source_mode: str = "dac_loopback",
        clock_ref: str = "tcxo_10mhz",
        sync_mode: str = "free_run",
    ) -> dict[str, Any]:
        observe_center_hz = float(observe_center_hz)
        dac_signal_hz = float(dac_signal_hz)
        expected_signal_hz = float(dac_signal_hz if expected_signal_hz is None else expected_signal_hz)
        view_bw_hz = float(view_bw_hz)
        dac_source_mode = str(dac_source_mode).strip().lower()
        input_source_mode = self._normalize_input_source_mode(input_source_mode)
        if dac_source_mode not in ("constant_phasor", "single_tone"):
            raise ValueError("dac_source_mode must be constant_phasor or single_tone")
        if not 50_000_000.0 <= observe_center_hz <= 350_000_000.0:
            raise ValueError("observe_center_hz must be in the 50..350 MHz science band")
        if not 50_000_000.0 <= dac_signal_hz <= 350_000_000.0:
            raise ValueError("dac_signal_hz must be in the 50..350 MHz science band")
        if not 50_000_000.0 <= expected_signal_hz <= 350_000_000.0:
            raise ValueError("expected_signal_hz must be in the 50..350 MHz science band")
        if not 5_000_000.0 <= view_bw_hz <= 200_000_000.0:
            raise ValueError("view_bw_hz must be in the 5..200 MHz display band")
        if input_source_mode == "dac_loopback" and abs(expected_signal_hz - dac_signal_hz) > 1.0:
            raise ValueError("dac_loopback input_source_mode requires expected_signal_hz to match dac_signal_hz")

        if initialize:
            self.stop()
            time.sleep(0.05)
            clock = self.clock.read_status(include_registers=False)
            status_ref = str(clock.get("selected_ref", clock.get("ref", "")))
            if bool(force_clock_reconfigure) or not bool(clock.get("configured", False)) or status_ref != str(clock_ref):
                clock = self.configure_clock(ref=str(clock_ref))
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

        dac_nco_hz = dac_signal_hz if dac_source_mode == "constant_phasor" else observe_center_hz
        dac_tone_hz = 0.0 if dac_source_mode == "constant_phasor" else (dac_signal_hz - observe_center_hz)
        dac_tone_mode = "constant_phasor" if dac_source_mode == "constant_phasor" else "single_tone"

        self.configure_rfdc(fs_adc=245_760_000, f_center=observe_center_hz, bandwidth=view_bw_hz, decimation=20)
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
        )
        self.rfdc_config = {
            "fs_adc": 245_760_000,
            "f_center": observe_center_hz,
            "observe_center_hz": observe_center_hz,
            "dac_signal_hz": dac_signal_hz,
            "expected_signal_hz": expected_signal_hz,
            "input_signal_hz": expected_signal_hz,
            "input_source_mode": input_source_mode,
            "bandwidth": view_bw_hz,
            "decimation": 20,
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
            dac_sample_rate_hz=245_760_000.0,
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
            "sync_mode": str(sync_mode),
            "clock": dict(clock) if isinstance(clock, Mapping) else clock,
            "nco": nco,
            "tone": tone,
            "dac_phase_epoch": int(epoch),
            "rfdc_sysref_lock": self.read_rfdc_sync_status(),
        }
        self.observation_instrument_config = config
        return config

    def apply_external_pps_locked_observation_config(self, **kwargs: Any) -> dict[str, Any]:
        """Stage 20 observation init using external 10 MHz and PPS as hard gates."""
        kwargs.setdefault("clock_ref", "external_10mhz")
        kwargs.setdefault("sync_mode", "external_pps")
        kwargs.setdefault("require_full_clock_lock", True)
        kwargs.setdefault("require_mts", True)
        kwargs.setdefault("force_clock_reconfigure", True)
        config = self.apply_mts_locked_observation_config(**kwargs)
        config["stage20_external_pps_locked"] = True
        return config

    @staticmethod
    def dac_phase_step_from_frequency(freq_hz: float, dac_sample_rate_hz: float = 245_760_000.0) -> int:
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
        dac_sample_rate_hz: float = 245_760_000.0,
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

    def apply_rf_instrument_config(
        self,
        *,
        center_hz: float,
        bw_hz: float = 100_000_000.0,
        tone_hz: float = 20_000_000.0,
        amplitude: int = 2048,
        phase_deg: float = 0.0,
        enable_mask: int = 0x01,
        phase_deg_per_channel: float = 0.0,
        phase_deg_by_channel: Optional[Mapping[Any, Any] | Iterable[Any]] = None,
        adc_active_mask: int = 0x0003,
        initialize: bool = False,
        start: bool = False,
    ) -> dict[str, Any]:
        if initialize:
            self.stop()
            time.sleep(0.05)
            self.configure_clock(ref="tcxo_10mhz")
            self.set_adc_active_mask(adc_active_mask)
            self.set_sync_mode("free_run")
            self.set_mode("spec")
        self.configure_rfdc(fs_adc=245_760_000, f_center=float(center_hz), bandwidth=float(bw_hz), decimation=20)
        nco = self.configure_rfdc_center_frequency(float(center_hz), bandwidth_hz=float(bw_hz), require=True)
        tone = self.configure_dac_tone_bank(
            freq_hz=float(tone_hz),
            amplitude=int(amplitude),
            phase_offset_deg=float(phase_deg),
            phase_deg_per_channel=float(phase_deg_per_channel),
            phase_deg_by_channel=phase_deg_by_channel,
            enable_mask=int(enable_mask),
            dac_sample_rate_hz=245_760_000.0,
        )
        epoch = self.reset_dac_phase()
        if start:
            self.start()
        config = {
            "center_hz": float(center_hz),
            "bw_hz": float(bw_hz),
            "tone_hz": float(tone_hz),
            "amplitude": int(amplitude),
            "phase_deg": float(phase_deg),
            "phase_deg_per_channel": float(phase_deg_per_channel),
            "phase_deg_by_channel": [float(value) for value in tone.get("phase_deg_by_channel", [])],
            "enable_mask": int(enable_mask),
            "adc_active_mask": int(adc_active_mask),
            "nco": nco,
            "tone": tone,
            "dac_phase_epoch": int(epoch),
        }
        self.rf_instrument_config = config
        return config

    def apply_observation_instrument_config(
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
        input_source_mode: str = "dac_loopback",
    ) -> dict[str, Any]:
        observe_center_hz = float(observe_center_hz)
        dac_signal_hz = float(dac_signal_hz)
        expected_signal_hz = float(dac_signal_hz if expected_signal_hz is None else expected_signal_hz)
        view_bw_hz = float(view_bw_hz)
        input_source_mode = self._normalize_input_source_mode(input_source_mode)
        if not 50_000_000.0 <= observe_center_hz <= 350_000_000.0:
            raise ValueError("observe_center_hz must be in the 50..350 MHz science band")
        if not 50_000_000.0 <= dac_signal_hz <= 350_000_000.0:
            raise ValueError("dac_signal_hz must be in the 50..350 MHz science band")
        if not 50_000_000.0 <= expected_signal_hz <= 350_000_000.0:
            raise ValueError("expected_signal_hz must be in the 50..350 MHz science band")
        if not 5_000_000.0 <= view_bw_hz <= 200_000_000.0:
            raise ValueError("view_bw_hz must be in the 5..200 MHz display band")
        if input_source_mode == "dac_loopback" and abs(expected_signal_hz - dac_signal_hz) > 1.0:
            raise ValueError("dac_loopback input_source_mode requires expected_signal_hz to match dac_signal_hz")

        if initialize:
            self.stop()
            time.sleep(0.05)
            self.configure_clock(ref="tcxo_10mhz")
            self.set_adc_active_mask(adc_active_mask)
            self.set_sync_mode("free_run")
            self.set_mode("spec")

        self.configure_rfdc(fs_adc=245_760_000, f_center=observe_center_hz, bandwidth=view_bw_hz, decimation=20)
        nco = self._configure_rfdc_nco_pair(
            adc_nco_hz=-observe_center_hz,
            dac_nco_hz=dac_signal_hz,
            bandwidth_hz=view_bw_hz,
            require=True,
        )
        self.rfdc_config = {
            "fs_adc": 245_760_000,
            "f_center": observe_center_hz,
            "observe_center_hz": observe_center_hz,
            "dac_signal_hz": dac_signal_hz,
            "expected_signal_hz": expected_signal_hz,
            "input_signal_hz": expected_signal_hz,
            "input_source_mode": input_source_mode,
            "bandwidth": view_bw_hz,
            "decimation": 20,
            "nco_configured": nco["configured"],
            "nco_results": nco["results"],
        }
        tone = self.configure_dac_tone_bank(
            freq_hz=0.0,
            amplitude=int(amplitude),
            phase_offset_deg=float(phase_deg),
            phase_deg_per_channel=float(phase_deg_per_channel),
            phase_deg_by_channel=phase_deg_by_channel,
            enable_mask=int(enable_mask),
            dac_sample_rate_hz=245_760_000.0,
            mode="constant_phasor",
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
            "input_source_mode": input_source_mode,
            "amplitude": int(amplitude),
            "phase_deg": float(phase_deg),
            "phase_deg_per_channel": float(phase_deg_per_channel),
            "phase_deg_by_channel": [float(value) for value in tone.get("phase_deg_by_channel", [])],
            "enable_mask": int(enable_mask),
            "adc_active_mask": int(adc_active_mask),
            "nco": nco,
            "tone": tone,
            "dac_phase_epoch": int(epoch),
        }
        self.observation_instrument_config = config
        return config

    def set_dac_enable_mask(self, mask: int) -> None:
        if not 0 <= mask <= 0xFF:
            raise ValueError("DAC enable mask must be in range 0x00..0xff")
        self.ctrl.write(self.regs.DAC_ENABLE_MASK, mask)

    def reset_dac_phase(self) -> int:
        before = int(self.ctrl.read(self.regs.DAC_PHASE_EPOCH))
        self.ctrl.write(self.regs.DAC_PHASE_EPOCH, 0x1)
        after = int(self.ctrl.read(self.regs.DAC_PHASE_EPOCH))
        if after == before:
            time.sleep(0.001)
            after = int(self.ctrl.read(self.regs.DAC_PHASE_EPOCH))
        return after

    def init_lab_rfdc(
        self,
        *,
        mask: int = 0x0001,
        mode: str = "snapshot",
        tone_enable: bool = True,
        tone_amplitude: int = 2048,
        tone_phase_step: int = 0x0080_0000,
        wait_seconds: float = 1.0,
    ) -> dict[str, int]:
        self.stop()
        time.sleep(0.05)
        self.configure_clock(ref="tcxo_10mhz")
        self.set_adc_active_mask(mask)
        self.set_sync_mode("free_run")
        self.set_mode(mode)
        self.configure_rfdc(
            fs_adc=245_760_000,
            f_center=1.5e9,
            bandwidth=245.76e6,
            decimation=20,
        )
        self.set_dac_tone(enable=tone_enable, amplitude=tone_amplitude, phase_step=tone_phase_step)
        before = self.read_status()
        self.start()
        deadline = time.monotonic() + wait_seconds
        status = before
        while time.monotonic() < deadline:
            status = self.read_status()
            if status["streaming"] and (status["rfdc_current_valid_mask"] & mask):
                break
            time.sleep(0.05)
        status = self.read_status()
        status["rfdc_sample_count_before_start"] = before["rfdc_sample_count"]
        return status

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
    def _normalize_science_bandwidth_mhz(cls, bandwidth_mhz: int | float | str) -> int:
        try:
            value = int(round(float(str(bandwidth_mhz).lower().replace("mhz", "").strip())))
        except Exception as exc:
            raise ValueError(f"Unsupported science bandwidth: {bandwidth_mhz!r}") from exc
        if value not in cls.SCIENCE_BANDWIDTHS:
            raise ValueError("science bandwidth must be one of 20, 100, 200 MHz")
        return value

    @classmethod
    def _normalize_science_output_mode(cls, output_mode: str | int) -> tuple[str, int]:
        if isinstance(output_mode, int):
            code = int(output_mode)
            if code not in cls.SCIENCE_OUTPUT_MODE_NAMES:
                raise ValueError("science output mode code must be in range 0..4")
            return cls.SCIENCE_OUTPUT_MODE_NAMES[code], code
        key = str(output_mode).strip().lower().replace("-", "_").replace(" ", "_")
        if key not in cls.SCIENCE_OUTPUT_MODES:
            raise ValueError(
                "science output mode must be OFF, TIME_ONLY, SPEC_ONLY, "
                "TIME_SPEC, or TIME_MONITOR_SPEC"
            )
        code = int(cls.SCIENCE_OUTPUT_MODES[key])
        return cls.SCIENCE_OUTPUT_MODE_NAMES[code], code

    @classmethod
    def _science_block_names(cls, mask: int) -> list[str]:
        return [name for bit, name in cls.SCIENCE_BLOCK_REASONS.items() if int(mask) & (1 << bit)]

    @classmethod
    def estimate_science_payload_rate(
        cls,
        bandwidth_mhz: int | float | str,
        output_mode: str | int,
        *,
        ninput: int = 8,
        iq_bits: int = 16,
        payload_bytes: int = 8192,
    ) -> dict[str, Any]:
        bandwidth = cls._normalize_science_bandwidth_mhz(bandwidth_mhz)
        mode_name, mode_code = cls._normalize_science_output_mode(output_mode)
        bw_cfg = cls.SCIENCE_BANDWIDTHS[bandwidth]
        sample_rate_hz = float(bw_cfg["sample_rate_hz"])
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
        if bandwidth == 200 and mode_code == 3:
            block_mask |= 1 << 0
        payload_bps = sample_rate_hz * int(ninput) * 2.0 * int(iq_bits) * full_stream_factor
        payload_mbps = payload_bps / 1_000_000.0
        packet_rate = 0.0 if payload_bytes <= 0 else (payload_bps / 8.0) / float(payload_bytes)
        # Ethernet/IP/UDP + T510 header + preamble/FCS/IFG estimate. This is a
        # planning number; pcap validation remains the real gate.
        wire_bytes = float(payload_bytes + 128 + 42 + 24)
        wire_mbps_est = payload_mbps * (wire_bytes / max(float(payload_bytes), 1.0))
        return {
            "bandwidth_mhz": bandwidth,
            "bandwidth_code": int(bw_cfg["code"]),
            "output_mode": mode_name,
            "output_mode_code": mode_code,
            "pl_decim_factor": int(bw_cfg["pl_decim"]),
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
        raw_bw = int(self.ctrl.read(self.regs.SCIENCE_BANDWIDTH_MODE))
        raw_mode = int(self.ctrl.read(self.regs.SCIENCE_OUTPUT_MODE))
        raw_block = int(self.ctrl.read(self.regs.SCIENCE_BLOCK_REASON))
        bandwidth = self.SCIENCE_BANDWIDTH_BY_CODE.get(raw_bw & 0x3, 20)
        mode_name = self.SCIENCE_OUTPUT_MODE_NAMES.get(raw_mode & 0x7, f"UNKNOWN_{raw_mode & 0x7}")
        status = {
            "science_control": raw_control,
            "science_status": raw_status,
            "science_bandwidth_mode": raw_bw,
            "science_output_mode_code": raw_mode,
            "science_output_mode": mode_name,
            "science_bandwidth_mhz": bandwidth,
            "science_sample_rate_hz": int(self.ctrl.read(self.regs.SCIENCE_SAMPLE_RATE_HZ)),
            "science_decim_factor": int(self.ctrl.read(self.regs.SCIENCE_DECIM_FACTOR)),
            "science_payload_rate_mbps": int(self.ctrl.read(self.regs.SCIENCE_PAYLOAD_RATE_MBPS)),
            "science_block_reason": raw_block,
            "science_block_reasons": self._science_block_names(raw_block),
            "science_capability": int(self.ctrl.read(self.regs.SCIENCE_CAPABILITY)),
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
        status["estimate"] = self.estimate_science_payload_rate(bandwidth, estimate_mode)
        return status

    def configure_science_output(
        self,
        bandwidth_mhz: int | float | str,
        output_mode: str | int,
        *,
        force_dry_run: bool = True,
        cmac_enable: bool = False,
        clear_counters: bool = False,
        apply_stream_mode: bool = True,
    ) -> dict[str, Any]:
        estimate = self.estimate_science_payload_rate(bandwidth_mhz, output_mode)
        if not estimate["allowed"]:
            raise ValueError(
                f"science output mode rejected: {', '.join(estimate['block_reasons'])}"
            )

        bandwidth_code = int(estimate["bandwidth_code"])
        output_code = int(estimate["output_mode_code"])
        control = (
            (0x1 if force_dry_run else 0x0)
            | (0x2 if cmac_enable else 0x0)
            | (0x4 if not force_dry_run else 0x0)
        )
        self.ctrl.write(self.regs.SCIENCE_BANDWIDTH_MODE, bandwidth_code)
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
        if live_requested:
            if not bool(cmac.get("cmac_live_ready", False)):
                blockers.append("CMAC_LINK_NOT_READY")
            if output_code in (2, 3) and not bool(status.get("spec_science_ready", False)):
                blockers.append("SPEC_SCIENCE_BLOCKED_PFB_SCAFFOLD")
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

    def configure_qsfp_test_link(
        self,
        *,
        dst_ip: str = "10.0.1.16",
        dst_mac: str = "08:c0:eb:d5:95:b2",
        dst_port: int = 4300,
        src_ip: str = "10.0.1.1",
        src_mac: str = "02:00:00:00:00:01",
        src_port: int = 4000,
        rate_pps: int | float = 1000,
        force_dry_run: bool = False,
        cmac_enable: bool = True,
        diagnostic_ignore_link_gate: bool = False,
        clear_counters: bool = True,
    ) -> dict[str, Any]:
        """Configure the Stage 24 low-rate CMAC heartbeat path.

        This is intentionally separate from TIME/SPEC science output: it only
        drives the 512-bit CMAC TX heartbeat/test-frame generator.
        """
        rate = max(float(rate_pps), 0.001)
        interval_cycles = max(1024, int(round(322_265_625.0 / rate)))
        self.ctrl.write(self.regs.SRC_IP, _ipv4_to_int(src_ip))
        src_lo, src_hi = _mac_to_parts(src_mac)
        self.ctrl.write(self.regs.SRC_MAC_LO, src_lo)
        self.ctrl.write(self.regs.SRC_MAC_HI, src_hi)
        self.ctrl.write(self.regs.TIME_DST_IP, _ipv4_to_int(dst_ip))
        self.ctrl.write(self.regs.TIME_UDP_PORT, int(dst_port) & 0xFFFF)
        self._write_tx_endpoint(
            2,
            enable=True,
            ip=str(dst_ip),
            mac=str(dst_mac),
            dst_port=int(dst_port),
            src_port=int(src_port),
        )
        self.ctrl.write(self.regs.QSFP_TEST_INTERVAL_CYCLES, interval_cycles)
        self.configure_tx_control(
            force_dry_run=bool(force_dry_run),
            cmac_enable=bool(cmac_enable),
            frame_builder_enable=True,
            drop_on_route_miss=True,
            diagnostic_ignore_link_gate=bool(diagnostic_ignore_link_gate),
            clear_counters=bool(clear_counters),
        )
        return {
            "dst_ip": str(dst_ip),
            "dst_mac": str(dst_mac),
            "dst_port": int(dst_port),
            "src_ip": str(src_ip),
            "src_mac": str(src_mac),
            "src_port": int(src_port),
            "rate_pps": rate,
            "interval_cycles": interval_cycles,
            "force_dry_run": bool(force_dry_run),
            "cmac_enable": bool(cmac_enable),
            "diagnostic_ignore_link_gate": bool(diagnostic_ignore_link_gate),
            "tx_status": self.read_tx_status(),
        }

    def run_qsfp_link_bringup(
        self,
        *,
        configure: bool = True,
        dst_ip: str = "10.0.1.16",
        dst_mac: str = "08:c0:eb:d5:95:b2",
        dst_port: int = 4300,
        src_ip: str = "10.0.1.1",
        src_mac: str = "02:00:00:00:00:01",
        src_port: int = 4000,
        rate_pps: int | float = 1000,
        seconds: float = 2.0,
        diagnostic_ignore_link_gate: bool = False,
    ) -> dict[str, Any]:
        config = None
        if configure:
            config = self.configure_qsfp_test_link(
                dst_ip=dst_ip,
                dst_mac=dst_mac,
                dst_port=dst_port,
                src_ip=src_ip,
                src_mac=src_mac,
                src_port=src_port,
                rate_pps=rate_pps,
                force_dry_run=False,
                cmac_enable=True,
                diagnostic_ignore_link_gate=bool(diagnostic_ignore_link_gate),
                clear_counters=True,
            )
        before = self.read_cmac_status()
        before_packets = int(before.get("accepted_packet_count", 0))
        before_bytes = int(before.get("accepted_byte_count", 0))
        time.sleep(max(float(seconds), 0.0))
        after = self.read_cmac_status()
        an_lt_applicable = bool(after.get("an_lt_applicable", False))
        after_packets = int(after.get("accepted_packet_count", 0))
        after_bytes = int(after.get("accepted_byte_count", 0))
        packet_delta = self._counter_delta(after_packets, before_packets)
        byte_delta = self._counter_delta(after_bytes, before_bytes)

        tx = after.get("tx", {})
        errors: list[str] = []
        if not bool(after.get("module_present", False)):
            errors.append("QSFP_MODULE_NOT_PRESENT")
        if not bool(tx.get("gt_refclk_seen", 0)):
            errors.append("GT_REFCLK_NOT_SEEN")
        if not bool(tx.get("gt_locked", 0)):
            errors.append("GT_NOT_LOCKED")
        if not bool(tx.get("gt_tx_reset_done", 0)):
            errors.append("GT_TX_RESET_NOT_DONE")
        if not bool(tx.get("gt_rx_reset_done", 0)):
            errors.append("GT_RX_RESET_NOT_DONE")
        if not bool(tx.get("cmac_reset_done", 0)):
            errors.append("CMAC_RESET_NOT_DONE")
        if not bool(tx.get("cmac_tx_ready", 0)):
            errors.append("CMAC_TX_NOT_READY")
        if bool(tx.get("tx_local_fault", 0)):
            errors.append("CMAC_LOCAL_FAULT")
        if bool(tx.get("tx_remote_fault", 0)):
            errors.append("CMAC_REMOTE_FAULT")
        if an_lt_applicable and not bool(tx.get("cmac_an_autoneg_complete", 0)):
            errors.append("CMAC_AN_NOT_COMPLETE")
        if an_lt_applicable and bool(tx.get("cmac_an_lp_ability_valid", 0)) and not bool(tx.get("cmac_an_lp_ability_100gbase_cr4", 0)):
            errors.append("CMAC_PARTNER_NOT_100G_CR4")
        if an_lt_applicable and not bool(tx.get("cmac_lt_signal_detect_all", 0)):
            errors.append("CMAC_LT_SIGNAL_DETECT_NOT_ALL")
        if an_lt_applicable and bool(tx.get("cmac_lt_training_fail_any", 0)):
            errors.append("CMAC_LT_TRAINING_FAIL")
        if an_lt_applicable and not bool(tx.get("cmac_lt_frame_lock_all", 0)):
            errors.append("CMAC_LT_FRAME_LOCK_NOT_ALL")
        if bool(tx.get("udp_dry_run_active", 1)):
            errors.append("TX_STILL_DRY_RUN")
        if bool(tx.get("tx_underflow", 0)):
            errors.append("CMAC_TX_UNDERFLOW")
        if bool(tx.get("tx_overflow", 0)):
            errors.append("CMAC_TX_OVERFLOW")
        if not errors and packet_delta <= 0:
            errors.append("CMAC_ACCEPTED_COUNTER_NOT_INCREMENTING")

        classification = "QSFP_HEARTBEAT_READY_FOR_PCAP" if not errors else "QSFP_HEARTBEAT_BLOCKED"
        return {
            "classification": classification,
            "ok": classification == "QSFP_HEARTBEAT_READY_FOR_PCAP",
            "pcap_validated": False,
            "config": config,
            "before": before,
            "after": after,
            "accepted_packet_delta": int(packet_delta),
            "accepted_byte_delta": int(byte_delta),
            "errors": errors,
        }

    def run_qsfp_live_validation(
        self,
        *,
        bandwidth_mhz: int | float | str = 100,
        output_mode: str | int = "time_only",
    ) -> dict[str, Any]:
        estimate = self.estimate_science_payload_rate(bandwidth_mhz, output_mode)
        cmac = self.read_cmac_status()
        science = self.read_science_output_status()
        errors: list[str] = []
        if not estimate["allowed"]:
            errors.extend(estimate["block_reasons"])
        if not bool(cmac.get("cmac_live_ready", False)):
            errors.append("CMAC_LINK_NOT_READY")
        if int(estimate["output_mode_code"]) in (2, 3) and not bool(science.get("spec_science_ready", False)):
            errors.append("SPEC_SCIENCE_BLOCKED_PFB_SCAFFOLD")
        if not bool(science.get("wide_tx_ready", False)):
            errors.append("WIDE_512B_TX_PATH_NOT_IMPLEMENTED")
        if errors:
            classification = "QSFP_LIVE_SCIENCE_BLOCKED"
        else:
            classification = "QSFP_LIVE_READY_FOR_PCAP"
        return {
            "classification": classification,
            "ok": classification == "QSFP_LIVE_READY_FOR_PCAP",
            "pcap_validated": False,
            "estimate": estimate,
            "cmac_status": cmac,
            "science_status": science,
            "errors": sorted(set(errors)),
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
        if not 0 <= endpoint_id < 8:
            raise ValueError("endpoint_id must be in range 0..7")
        if not 0 <= int(dst_port) <= 0xFFFF:
            raise ValueError("dst_port must fit in 16 bits")
        if not 0 <= int(src_port) <= 0xFFFF:
            raise ValueError("src_port must fit in 16 bits")
        base = self.regs.TX_ENDPOINT_BASE + endpoint_id * self.regs.TX_ENDPOINT_STRIDE
        mac_value = _mac_to_int(mac)
        self.ctrl.write(base + 0x04, _ipv4_to_int(ip))
        self.ctrl.write(base + 0x08, mac_value & 0xFFFF_FFFF)
        self.ctrl.write(base + 0x0C, (mac_value >> 32) & 0xFFFF)
        self.ctrl.write(base + 0x10, int(dst_port))
        self.ctrl.write(base + 0x14, int(src_port))
        self.ctrl.write(base + 0x00, 0x1 if enable else 0x0)

    def configure_tx_endpoints(self, endpoints: list[Mapping[str, Any]]) -> None:
        if len(endpoints) > 8:
            raise ValueError("Stage 7 supports at most 8 TX endpoints")
        for index, endpoint in enumerate(endpoints):
            endpoint_id = int(endpoint.get("id", index))
            enable = bool(endpoint.get("enable", True))
            if not enable:
                base = self.regs.TX_ENDPOINT_BASE + endpoint_id * self.regs.TX_ENDPOINT_STRIDE
                self.ctrl.write(base + 0x00, 0)
                continue
            self._write_tx_endpoint(
                endpoint_id,
                enable=enable,
                ip=str(endpoint["ip"]),
                mac=str(endpoint["mac"]),
                dst_port=int(endpoint.get("dst_port", endpoint.get("port", 4100 + endpoint_id))),
                src_port=int(endpoint.get("src_port", self.ctrl.read(self.regs.SRC_UDP_PORT))),
            )

    def configure_spec_routes(self, routes: list[Mapping[str, Any]], *, clear_unlisted: bool = True) -> None:
        if len(routes) > 8:
            raise ValueError("Stage 7 supports at most 8 SPEC routes")
        if clear_unlisted:
            for route_id in range(8):
                base = self.regs.TX_SPEC_ROUTE_BASE + route_id * self.regs.TX_SPEC_ROUTE_STRIDE
                self.ctrl.write(base + 0x00, 0)
        for index, route in enumerate(routes):
            route_id = int(route.get("id", index))
            if not 0 <= route_id < 8:
                raise ValueError("SPEC route id must be in range 0..7")
            endpoint_id = int(route["endpoint_id"])
            if not 0 <= endpoint_id < 8:
                raise ValueError("SPEC route endpoint_id must be in range 0..7")
            chan0 = int(route["chan0"])
            chan_count = int(route["chan_count"])
            if chan0 < 0 or chan_count <= 0 or chan0 + chan_count > 4096:
                raise ValueError("SPEC route channel window must stay within 0..4095")
            base = self.regs.TX_SPEC_ROUTE_BASE + route_id * self.regs.TX_SPEC_ROUTE_STRIDE
            self.ctrl.write(base + 0x04, chan0)
            self.ctrl.write(base + 0x08, chan_count)
            self.ctrl.write(base + 0x00, (endpoint_id << 8) | (0x1 if route.get("enable", True) else 0x0))

    def configure_time_routes(self, routes: list[Mapping[str, Any]], *, clear_unlisted: bool = True) -> None:
        if len(routes) > 8:
            raise ValueError("Stage 7 supports at most 8 TIME routes")
        if clear_unlisted:
            for route_id in range(8):
                base = self.regs.TX_TIME_ROUTE_BASE + route_id * self.regs.TX_TIME_ROUTE_STRIDE
                self.ctrl.write(base + 0x00, 0)
        for index, route in enumerate(routes):
            route_id = int(route.get("id", index))
            if not 0 <= route_id < 8:
                raise ValueError("TIME route id must be in range 0..7")
            endpoint_id = int(route["endpoint_id"])
            input_mask = int(route["input_mask"])
            if not 0 <= endpoint_id < 8:
                raise ValueError("TIME route endpoint_id must be in range 0..7")
            if not 1 <= input_mask <= 0xFFFF:
                raise ValueError("TIME route input_mask must be in range 0x0001..0xffff")
            base = self.regs.TX_TIME_ROUTE_BASE + route_id * self.regs.TX_TIME_ROUTE_STRIDE
            self.ctrl.write(base + 0x04, input_mask)
            self.ctrl.write(base + 0x00, (endpoint_id << 8) | (0x1 if route.get("enable", True) else 0x0))

    def read_tx_status(self) -> dict[str, Any]:
        raw = int(self.ctrl.read(self.regs.TX_STATUS))
        link_raw = int(self.ctrl.read(self.regs.TX_LINK_STATUS_FLAGS))
        selected_route = int(self.ctrl.read(self.regs.TX_SELECTED_ROUTE))
        status: dict[str, Any] = {
            "tx_control": int(self.ctrl.read(self.regs.TX_CONTROL)),
            "tx_status": raw,
            "tx_link_status_flags_raw": link_raw,
            "qsfp_link_up": raw & 0x1,
            "udp_dry_run_active": (raw >> 1) & 0x1,
            "cmac_reset_done": (raw >> 2) & 0x1,
            "gt_locked": (raw >> 3) & 0x1,
            "cmac_tx_ready": (raw >> 4) & 0x1,
            "tx_local_fault": (raw >> 5) & 0x1,
            "tx_remote_fault": (raw >> 6) & 0x1,
            "route_miss_sticky": (raw >> 7) & 0x1,
            "route_error_sticky": (raw >> 8) & 0x1,
            "frame_builder_enabled": (raw >> 9) & 0x1,
            "force_dry_run": (raw >> 10) & 0x1,
            "cmac_enable": (raw >> 11) & 0x1,
            "qsfp_module_present": (raw >> 12) & 0x1,
            "gt_refclk_seen": (raw >> 13) & 0x1,
            "gt_tx_reset_done": (raw >> 14) & 0x1,
            "gt_rx_reset_done": (raw >> 15) & 0x1,
            "tx_underflow": (raw >> 16) & 0x1,
            "tx_overflow": (raw >> 17) & 0x1,
            "diagnostic_ignore_link_gate": (int(self.ctrl.read(self.regs.TX_CONTROL)) >> 4) & 0x1,
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
            "tx_selected_endpoint": int(self.ctrl.read(self.regs.TX_SELECTED_ENDPOINT)) & 0x7,
            "tx_selected_route": selected_route & 0x7,
            "tx_selected_route_is_time": (selected_route >> 3) & 0x1,
            "qsfp_test_interval_cycles": int(self.ctrl.read(self.regs.QSFP_TEST_INTERVAL_CYCLES)),
        }
        return status

    def capture_tx_frame_header(self, *, timeout: float = 1.0) -> dict[str, Any]:
        try:
            from .packet import EthernetIPv4UDPFrame
        except ImportError:
            from packet import EthernetIPv4UDPFrame

        self.ctrl.write(self.regs.TX_FRAME_CAPTURE_CONTROL, 0x1)
        deadline = time.monotonic() + timeout
        status = self.read_tx_status()
        capture_status = int(self.ctrl.read(self.regs.TX_FRAME_CAPTURE_STATUS))
        while time.monotonic() < deadline:
            capture_status = int(self.ctrl.read(self.regs.TX_FRAME_CAPTURE_STATUS))
            if (capture_status >> 1) & 0x1:
                break
            time.sleep(0.005)
        else:
            raise TimeoutError(f"TX frame capture timed out: TX_FRAME_CAPTURE_STATUS=0x{capture_status:08x}")

        words32 = [
            int(self.ctrl.read(self.regs.TX_FRAME_CAPTURE_BUFFER_BASE + 4 * idx))
            for idx in range(32)
        ]
        axis_words = [
            (words32[idx * 2] & 0xFFFF_FFFF) | ((words32[idx * 2 + 1] & 0xFFFF_FFFF) << 32)
            for idx in range(16)
        ]
        frame = EthernetIPv4UDPFrame.from_axis_words(axis_words)
        return {
            "frame": frame,
            "frame_dict": frame.to_dict(),
            "t510_header": frame.t510_header,
            "t510_header_dict": frame.t510_header.to_dict() if frame.t510_header is not None else None,
            "axis_words": axis_words,
            "words32": words32,
            "capture_status": capture_status,
            "status": status,
        }

    def run_spec_route_walk(
        self,
        *,
        chan0_values: tuple[int, ...] = (0, 2048),
        chan_count: int = 64,
        time_count: int = 4,
        timeout: float = 1.0,
    ) -> list[dict[str, Any]]:
        captures: list[dict[str, Any]] = []
        for chan0 in chan0_values:
            self.configure_channelizer(chan0=chan0, chan_count=chan_count, time_count=time_count)
            captures.append(self.capture_tx_frame_header(timeout=timeout))
        return captures

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
        taps: int = 4,
        chan0: int = 0,
        chan_count: int = 64,
        time_count: int = 4,
        fft_shift: int = 0,
        enable: bool = True,
    ) -> dict[str, int]:
        if nchan != 4096:
            raise ValueError("Stage 6 dry-run channelizer currently supports nchan=4096")
        if not 1 <= taps <= 16:
            raise ValueError("taps must be in range 1..16")
        if not 0 <= fft_shift <= 0xFFFF:
            raise ValueError("fft_shift must fit in 16 bits")
        if not 0 <= chan0 < nchan:
            raise ValueError("chan0 must be in range 0..nchan-1")
        if not 1 <= chan_count <= nchan:
            raise ValueError("chan_count must be in range 1..nchan")
        if not 1 <= time_count <= 0xFFFF:
            raise ValueError("time_count must be positive")
        if chan0 + chan_count > nchan:
            raise ValueError("chan0 + chan_count must not exceed nchan")
        if chan_count * time_count * 8 * 4 != 8192:
            raise ValueError("Stage 6 dry-run payload must remain 8192 bytes: chan_count*time_count must be 256")

        self.ctrl.write(self.regs.PFB_TAPS, int(taps))
        self.ctrl.write(self.regs.PFB_FFT_SHIFT, int(fft_shift))
        self.ctrl.write(self.regs.PFB_CHAN0, int(chan0))
        self.ctrl.write(self.regs.PFB_CHAN_COUNT, int(chan_count))
        self.ctrl.write(self.regs.PFB_TIME_COUNT, int(time_count))
        self.ctrl.write(self.regs.SPEC_CHAN_COUNT, int(chan_count))
        self.ctrl.write(self.regs.SPEC_TIME_COUNT, int(time_count))
        self.ctrl.write(self.regs.PFB_CONTROL, 0x1 if enable else 0x0)
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
            "pfb_peak_chan": int(self.ctrl.read(self.regs.PFB_PEAK_CHAN)),
            "pfb_peak_power": int(self.ctrl.read(self.regs.PFB_PEAK_POWER)),
        }
        raw = status["pfb_status"]
        status["pfb_enabled"] = raw & 0x1
        status["pfb_config_valid"] = (raw >> 1) & 0x1
        status["pfb_output_valid"] = (raw >> 2) & 0x1
        status["pfb_overflow"] = (raw >> 3) & 0x1
        status["pfb_window_active"] = (raw >> 4) & 0x1
        return status

    def start(self) -> None:
        self.ctrl.write(self.regs.CONTROL, 0x1)

    def trigger_epoch(self) -> None:
        self.ctrl.write(self.regs.CONTROL, 0x2)

    def stop(self) -> None:
        self.ctrl.write(self.regs.CONTROL, 0x4)

    def reset(self) -> None:
        self.ctrl.write(self.regs.CONTROL, 0x8)

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
            "monitor_sample_count": self.regs.MONITOR_SAMPLE_COUNT,
            "spec_packet_count": self.regs.SPEC_PACKET_COUNT,
            "spec_udp_byte_count": self.regs.SPEC_UDP_BYTE_COUNT,
            "time_packet_count": self.regs.TIME_PACKET_COUNT,
            "time_udp_byte_count": self.regs.TIME_UDP_BYTE_COUNT,
            "time_dropped_count": self.regs.TIME_DROPPED_COUNT,
            "spec_seq_no": self.regs.SPEC_SEQ_NO,
            "time_seq_no": self.regs.TIME_SEQ_NO,
            "spec_chan0": self.regs.SPEC_CHAN0,
            "rfdc_status_flags": self.regs.RFDC_STATUS_FLAGS,
            "rfdc_dropped_count": self.regs.RFDC_DROPPED_COUNT,
            "rfdc_active_mask": self.regs.RFDC_ACTIVE_MASK,
            "rfdc_current_valid_mask": self.regs.RFDC_CURRENT_VALID_MASK,
            "rfdc_seen_valid_mask": self.regs.RFDC_SEEN_VALID_MASK,
            "tx_link_status_flags": self.regs.TX_LINK_STATUS_FLAGS,
            "tx_dry_run_packet_count": self.regs.TX_DRY_RUN_PACKET_COUNT,
            "tx_dry_run_byte_count": self.regs.TX_DRY_RUN_BYTE_COUNT,
            "tx_fifo_level_words": self.regs.TX_FIFO_LEVEL_WORDS,
            "tx_fifo_high_water_words": self.regs.TX_FIFO_HIGH_WATER_WORDS,
            "tx_fifo_backpressure_cycles": self.regs.TX_FIFO_BACKPRESSURE_CYCLES,
            "tx_header_capture_status": self.regs.TX_HEADER_CAPTURE_STATUS,
            "debug_status": self.regs.DEBUG_STATUS,
            "debug_nfft": self.regs.DEBUG_NFFT,
            "debug_sample_rate_hz": self.regs.DEBUG_OBS_SAMPLE_RATE_HZ,
            "debug_peak_bin": self.regs.DEBUG_PEAK_BIN,
            "debug_peak_power": self.regs.DEBUG_PEAK_POWER,
            "debug_capture_count": self.regs.DEBUG_CAPTURE_COUNT,
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
            "preview_audit_control": self.regs.PREVIEW_AUDIT_CONTROL,
            "preview_audit_status": self.regs.PREVIEW_AUDIT_STATUS,
            "preview_audit_start_count": self.regs.PREVIEW_AUDIT_START_COUNT,
            "preview_audit_first_count": self.regs.PREVIEW_AUDIT_FIRST_COUNT,
            "preview_audit_done_count": self.regs.PREVIEW_AUDIT_DONE_COUNT,
            "preview_audit_start_to_first_latency": self.regs.PREVIEW_AUDIT_START_TO_FIRST_LATENCY,
            "preview_audit_capture_beats": self.regs.PREVIEW_AUDIT_CAPTURE_BEATS,
            "preview_audit_valid_gap_count": self.regs.PREVIEW_AUDIT_VALID_GAP_COUNT,
            "preview_audit_sample0_error_count": self.regs.PREVIEW_AUDIT_SAMPLE0_ERROR_COUNT,
            "preview_audit_event_threshold": self.regs.PREVIEW_AUDIT_EVENT_THRESHOLD,
            "preview_event_max_code": self.regs.PREVIEW_EVENT_MAX_CODE,
            "preview_event_info": self.regs.PREVIEW_EVENT_INFO,
            "preview_event_rfdc_flags": self.regs.PREVIEW_EVENT_RFDC_FLAGS,
            "preview_event_dac_phase_epoch": self.regs.PREVIEW_EVENT_DAC_PHASE_EPOCH,
            "preview_event_buffer_words": self.regs.PREVIEW_EVENT_BUFFER_WORDS,
            "tx_payload_witness_status": self.regs.TX_PAYLOAD_WITNESS_STATUS,
            "tx_payload_witness_stream_filter": self.regs.TX_PAYLOAD_WITNESS_STREAM_FILTER,
            "tx_payload_witness_capture_words": self.regs.TX_PAYLOAD_WITNESS_CAPTURE_WORDS,
            "tx_paired_coherence_status": self.regs.TX_PAIRED_COHERENCE_STATUS,
            "tx_paired_rfdc_flags": self.regs.TX_PAIRED_RFDC_FLAGS,
            "science_control": self.regs.SCIENCE_CONTROL,
            "science_status": self.regs.SCIENCE_STATUS,
            "science_bandwidth_mode": self.regs.SCIENCE_BANDWIDTH_MODE,
            "science_output_mode": self.regs.SCIENCE_OUTPUT_MODE,
            "science_sample_rate_hz": self.regs.SCIENCE_SAMPLE_RATE_HZ,
            "science_decim_factor": self.regs.SCIENCE_DECIM_FACTOR,
            "science_payload_rate_mbps": self.regs.SCIENCE_PAYLOAD_RATE_MBPS,
            "science_block_reason": self.regs.SCIENCE_BLOCK_REASON,
            "science_capability": self.regs.SCIENCE_CAPABILITY,
            "dac_tx_witness_status": self.regs.DAC_TX_WITNESS_STATUS,
            "dac_tx_witness_capture_words": self.regs.DAC_TX_WITNESS_CAPTURE_WORDS,
            "dac_tx_witness_buffer_words": self.regs.DAC_TX_WITNESS_BUFFER_WORDS_REG,
            "dac_tx_witness_phase_epoch": self.regs.DAC_TX_WITNESS_PHASE_EPOCH,
            "dac_tx_witness_phase_acc": self.regs.DAC_TX_WITNESS_PHASE_ACC,
            "dac_tx_witness_phase_step": self.regs.DAC_TX_WITNESS_PHASE_STEP,
            "dac_tx_witness_phase0": self.regs.DAC_TX_WITNESS_PHASE0,
            "dac_tx_witness_mode": self.regs.DAC_TX_WITNESS_MODE,
            "dac_tx_witness_ready_gap_count": self.regs.DAC_TX_WITNESS_READY_GAP_COUNT,
            "rfdc_axis_raw_witness_status": self.regs.RFDC_AXIS_RAW_WITNESS_STATUS,
            "rfdc_axis_raw_witness_channel_select_ctrl": self.regs.RFDC_AXIS_RAW_WITNESS_CHANNEL_SELECT,
            "rfdc_axis_raw_witness_capture_beats": self.regs.RFDC_AXIS_RAW_WITNESS_CAPTURE_BEATS,
            "rfdc_axis_raw_witness_rfdc_flags": self.regs.RFDC_AXIS_RAW_WITNESS_RFDC_FLAGS,
            "rfdc_axis_raw_witness_word_count_reg": self.regs.RFDC_AXIS_RAW_WITNESS_WORD_COUNT,
            "rfdc_axis_raw_witness_buffer_words": self.regs.RFDC_AXIS_RAW_WITNESS_BUFFER_WORDS_REG,
            "rfdc_axis_raw_witness_valid_mask": self.regs.RFDC_AXIS_RAW_WITNESS_VALID_MASK,
            "dac_audit_phase_epoch_seen": self.regs.DAC_AUDIT_PHASE_EPOCH_SEEN,
            "dac_audit_ch0_phase_acc": self.regs.DAC_AUDIT_CH0_PHASE_ACC,
            "dac_audit_ch0_phase_step": self.regs.DAC_AUDIT_CH0_PHASE_STEP,
            "dac_audit_ch0_phase0": self.regs.DAC_AUDIT_CH0_PHASE0,
            "dac_audit_ch0_mode": self.regs.DAC_AUDIT_CH0_MODE,
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
            "pfb_peak_chan": self.regs.PFB_PEAK_CHAN,
            "pfb_peak_power": self.regs.PFB_PEAK_POWER,
            "tx_control": self.regs.TX_CONTROL,
            "tx_status": self.regs.TX_STATUS,
            "tx_frame_built_count": self.regs.TX_FRAME_BUILT_COUNT,
            "tx_frame_sent_count": self.regs.TX_FRAME_SENT_COUNT,
            "tx_frame_dropped_count": self.regs.TX_FRAME_DROPPED_COUNT,
            "tx_frame_byte_count": self.regs.TX_FRAME_BYTE_COUNT,
            "tx_route_miss_count": self.regs.TX_ROUTE_MISS_COUNT,
            "tx_route_error_count": self.regs.TX_ROUTE_ERROR_COUNT,
            "tx_frame_capture_status": self.regs.TX_FRAME_CAPTURE_STATUS,
            "qsfp_test_interval_cycles": self.regs.QSFP_TEST_INTERVAL_CYCLES,
        }
        status = {name: int(self.ctrl.read(offset)) for name, offset in keys.items()}
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
        debug_status = status["debug_status"]
        status["debug_busy"] = debug_status & 0x1
        status["debug_error"] = (debug_status >> 1) & 0x1
        status["debug_done"] = (debug_status >> 2) & 0x1
        tx_flags = status["tx_link_status_flags"]
        status["qsfp_link_up"] = tx_flags & 0x1
        status["udp_dry_run"] = (tx_flags >> 1) & 0x1
        tx_status = status["tx_status"]
        tx_link_raw = status["tx_link_status_flags"]
        status["tx_qsfp_link_up"] = tx_status & 0x1
        status["tx_udp_dry_run_active"] = (tx_status >> 1) & 0x1
        status["tx_cmac_reset_done"] = (tx_status >> 2) & 0x1
        status["tx_gt_locked"] = (tx_status >> 3) & 0x1
        status["tx_cmac_tx_ready"] = (tx_status >> 4) & 0x1
        status["tx_local_fault"] = (tx_status >> 5) & 0x1
        status["tx_remote_fault"] = (tx_status >> 6) & 0x1
        status["tx_route_miss_sticky"] = (tx_status >> 7) & 0x1
        status["tx_route_error_sticky"] = (tx_status >> 8) & 0x1
        status["tx_frame_builder_enabled"] = (tx_status >> 9) & 0x1
        status["tx_force_dry_run"] = (tx_status >> 10) & 0x1
        status["tx_cmac_enable"] = (tx_status >> 11) & 0x1
        status["tx_qsfp_module_present"] = (tx_status >> 12) & 0x1
        status["tx_gt_refclk_seen"] = (tx_status >> 13) & 0x1
        status["tx_gt_tx_reset_done"] = (tx_status >> 14) & 0x1
        status["tx_gt_rx_reset_done"] = (tx_status >> 15) & 0x1
        status["tx_underflow"] = (tx_status >> 16) & 0x1
        status["tx_overflow"] = (tx_status >> 17) & 0x1
        status["tx_diagnostic_ignore_link_gate"] = (status["tx_control"] >> 4) & 0x1
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
        tx_header_status = status["tx_header_capture_status"]
        status["tx_header_capture_armed"] = tx_header_status & 0x1
        status["tx_header_capture_valid"] = (tx_header_status >> 1) & 0x1
        status["tx_header_capture_word_count"] = (tx_header_status >> 16) & 0x1F
        tx_frame_status = status["tx_frame_capture_status"]
        status["tx_frame_capture_armed"] = tx_frame_status & 0x1
        status["tx_frame_capture_valid"] = (tx_frame_status >> 1) & 0x1
        status["tx_frame_capture_word_count"] = (tx_frame_status >> 16) & 0x1F
        witness_status = status["tx_payload_witness_status"]
        status["tx_payload_witness_armed"] = witness_status & 0x1
        status["tx_payload_witness_valid"] = (witness_status >> 1) & 0x1
        status["tx_payload_witness_capturing"] = (witness_status >> 2) & 0x1
        status["tx_payload_witness_overflow"] = (witness_status >> 3) & 0x1
        status["tx_payload_witness_filter_mismatch"] = (witness_status >> 4) & 0x1
        status["tx_payload_witness_word_count"] = (witness_status >> 8) & 0x7FF
        status["tx_payload_witness_stream_type"] = (witness_status >> 24) & 0xFF
        paired_status = status["tx_paired_coherence_status"]
        status["tx_paired_witness_valid"] = paired_status & 0x1
        status["tx_paired_preview_done"] = (paired_status >> 1) & 0x1
        status["tx_paired_preview_error"] = (paired_status >> 2) & 0x1
        status["tx_paired_witness_overflow"] = (paired_status >> 3) & 0x1
        status["tx_paired_witness_filter_mismatch"] = (paired_status >> 4) & 0x1
        status["tx_paired_witness_word_count"] = (paired_status >> 8) & 0x7FF
        status["tx_paired_witness_stream_type_lsb"] = (paired_status >> 24) & 0xFF
        dac_tx_status = status["dac_tx_witness_status"]
        status["dac_tx_witness_armed"] = dac_tx_status & 0x1
        status["dac_tx_witness_valid"] = (dac_tx_status >> 1) & 0x1
        status["dac_tx_witness_capturing"] = (dac_tx_status >> 2) & 0x1
        status["dac_tx_witness_overflow"] = (dac_tx_status >> 3) & 0x1
        status["dac_tx_witness_tvalid_seen"] = (dac_tx_status >> 4) & 0x1
        status["dac_tx_witness_tready_seen"] = (dac_tx_status >> 5) & 0x1
        status["dac_tx_witness_ready_gap_seen"] = (dac_tx_status >> 6) & 0x1
        status["dac_tx_witness_word_count"] = (dac_tx_status >> 8) & 0x1FF
        raw_witness_status = status["rfdc_axis_raw_witness_status"]
        status["rfdc_axis_raw_witness_armed"] = raw_witness_status & 0x1
        status["rfdc_axis_raw_witness_valid"] = (raw_witness_status >> 1) & 0x1
        status["rfdc_axis_raw_witness_capturing"] = (raw_witness_status >> 2) & 0x1
        status["rfdc_axis_raw_witness_overflow"] = (raw_witness_status >> 3) & 0x1
        status["rfdc_axis_raw_witness_tvalid_seen"] = (raw_witness_status >> 4) & 0x1
        status["rfdc_axis_raw_witness_beat_count"] = (raw_witness_status >> 8) & 0x1FF
        status["rfdc_axis_raw_witness_channel_select"] = (raw_witness_status >> 24) & 0x7
        status["rfdc_axis_raw_witness_word_count"] = status["rfdc_axis_raw_witness_beat_count"] * 4
        status["rfdc_axis_raw_witness_sample0"] = (
            int(self.ctrl.read(self.regs.RFDC_AXIS_RAW_WITNESS_SAMPLE0_LO))
            | (int(self.ctrl.read(self.regs.RFDC_AXIS_RAW_WITNESS_SAMPLE0_HI)) << 32)
        )
        status["tx_paired_source_sample0"] = (
            int(self.ctrl.read(self.regs.TX_PAIRED_SOURCE_SAMPLE0_LO))
            | (int(self.ctrl.read(self.regs.TX_PAIRED_SOURCE_SAMPLE0_HI)) << 32)
        )
        status["tx_paired_preview_sample0"] = (
            int(self.ctrl.read(self.regs.TX_PAIRED_PREVIEW_SAMPLE0_LO))
            | (int(self.ctrl.read(self.regs.TX_PAIRED_PREVIEW_SAMPLE0_HI)) << 32)
        )
        status["tx_paired_header_sample0"] = (
            int(self.ctrl.read(self.regs.TX_PAIRED_HEADER_SAMPLE0_LO))
            | (int(self.ctrl.read(self.regs.TX_PAIRED_HEADER_SAMPLE0_HI)) << 32)
        )
        sample0_delta = (
            int(self.ctrl.read(self.regs.TX_PAIRED_SAMPLE0_DELTA_LO))
            | (int(self.ctrl.read(self.regs.TX_PAIRED_SAMPLE0_DELTA_HI)) << 32)
        )
        if sample0_delta & (1 << 63):
            sample0_delta -= 1 << 64
        status["tx_paired_sample0_delta"] = int(sample0_delta)
        preview_status = status["preview_status"]
        status["preview_busy"] = preview_status & 0x1
        status["preview_error"] = (preview_status >> 1) & 0x1
        status["preview_done"] = (preview_status >> 2) & 0x1
        status["preview_sample0"] = (
            int(self.ctrl.read(self.regs.PREVIEW_SAMPLE0_LO))
            | (int(self.ctrl.read(self.regs.PREVIEW_SAMPLE0_HI)) << 32)
        )
        status["preview_audit_start_sample0"] = (
            int(self.ctrl.read(self.regs.PREVIEW_AUDIT_START_SAMPLE0_LO))
            | (int(self.ctrl.read(self.regs.PREVIEW_AUDIT_START_SAMPLE0_HI)) << 32)
        )
        status["preview_audit_first_sample0"] = (
            int(self.ctrl.read(self.regs.PREVIEW_AUDIT_FIRST_SAMPLE0_LO))
            | (int(self.ctrl.read(self.regs.PREVIEW_AUDIT_FIRST_SAMPLE0_HI)) << 32)
        )
        status["preview_audit_done_sample0"] = (
            int(self.ctrl.read(self.regs.PREVIEW_AUDIT_DONE_SAMPLE0_LO))
            | (int(self.ctrl.read(self.regs.PREVIEW_AUDIT_DONE_SAMPLE0_HI)) << 32)
        )
        status["preview_event_sample0"] = (
            int(self.ctrl.read(self.regs.PREVIEW_EVENT_SAMPLE0_LO))
            | (int(self.ctrl.read(self.regs.PREVIEW_EVENT_SAMPLE0_HI)) << 32)
        )
        audit_status = status["preview_audit_status"]
        status["preview_event_valid"] = audit_status & 0x1
        status["preview_event_active"] = (audit_status >> 1) & 0x1
        status["preview_event_overflow"] = (audit_status >> 2) & 0x1
        status["preview_sample0_nonmonotonic"] = (audit_status >> 3) & 0x1
        status["preview_valid_gap_seen"] = (audit_status >> 4) & 0x1
        status["preview_sample0_error_seen"] = (audit_status >> 5) & 0x1
        status["preview_audit_source"] = (audit_status >> 6) & 0x3
        audit_control = status["preview_audit_control"]
        status["preview_audit_event_enable"] = (audit_control >> 1) & 0x1
        status["preview_audit_freeze_on_event"] = (audit_control >> 2) & 0x1
        status["preview_audit_configured_source"] = (audit_control >> 8) & 0x3
        pfb_status = status["pfb_status"]
        status["pfb_enabled"] = pfb_status & 0x1
        status["pfb_config_valid"] = (pfb_status >> 1) & 0x1
        status["pfb_output_valid"] = (pfb_status >> 2) & 0x1
        status["pfb_overflow"] = (pfb_status >> 3) & 0x1
        status["pfb_window_active"] = (pfb_status >> 4) & 0x1
        science_status = status["science_status"]
        science_bw = int(status["science_bandwidth_mode"]) & 0x3
        science_mode = int(status["science_output_mode"]) & 0x7
        status["science_bandwidth_mhz"] = self.SCIENCE_BANDWIDTH_BY_CODE.get(science_bw, 20)
        status["science_output_mode_name"] = self.SCIENCE_OUTPUT_MODE_NAMES.get(science_mode, f"UNKNOWN_{science_mode}")
        status["science_time_enabled"] = science_status & 0x1
        status["science_spec_enabled"] = (science_status >> 1) & 0x1
        status["science_time_spec_rejected"] = (science_status >> 2) & 0x1
        status["science_spec_ready"] = (science_status >> 3) & 0x1
        status["science_wide_tx_ready"] = (science_status >> 4) & 0x1
        status["science_cmac_live_ready"] = (science_status >> 5) & 0x1
        status["science_block_reasons"] = self._science_block_names(status["science_block_reason"])
        return status

    def read_paired_coherence_status(self) -> dict[str, Any]:
        status = self.read_status()
        return {
            "status": int(status["tx_paired_coherence_status"]),
            "witness_valid": bool(status["tx_paired_witness_valid"]),
            "preview_done": bool(status["tx_paired_preview_done"]),
            "preview_error": bool(status["tx_paired_preview_error"]),
            "witness_overflow": bool(status["tx_paired_witness_overflow"]),
            "witness_filter_mismatch": bool(status["tx_paired_witness_filter_mismatch"]),
            "witness_word_count": int(status["tx_paired_witness_word_count"]),
            "witness_stream_type_lsb": int(status["tx_paired_witness_stream_type_lsb"]),
            "source_sample0": int(status["tx_paired_source_sample0"]),
            "preview_sample0": int(status["tx_paired_preview_sample0"]),
            "header_sample0": int(status["tx_paired_header_sample0"]),
            "sample0_delta": int(status["tx_paired_sample0_delta"]),
            "source_header_delta": int(status["tx_paired_source_sample0"]) - int(status["tx_paired_header_sample0"]),
            "preview_header_delta": int(status["tx_paired_header_sample0"]) - int(status["tx_paired_preview_sample0"]),
            "rfdc_flags": int(status["tx_paired_rfdc_flags"]),
        }

    @staticmethod
    def _preview_source_code(source: str | int) -> int:
        if isinstance(source, int):
            code = int(source)
        else:
            name = str(source).strip().lower().replace("-", "_")
            aliases = {
                "rfdc": 0,
                "adc": 0,
                "internal_dds": 1,
                "dds": 1,
                "internal": 1,
                "sample_index_ramp": 2,
                "ramp": 2,
            }
            if name not in aliases:
                raise ValueError(f"unknown preview audit source {source!r}")
            code = aliases[name]
        if code not in (0, 1, 2):
            raise ValueError("preview audit source must be RFDC=0, internal_dds=1, or ramp=2")
        return code

    @staticmethod
    def _preview_source_name(code: int) -> str:
        return {0: "rfdc", 1: "internal_dds", 2: "sample_index_ramp"}.get(int(code), f"unknown_{int(code)}")

    def configure_preview_audit(
        self,
        *,
        source: str | int = "rfdc",
        event_enable: bool = False,
        freeze_on_event: bool = True,
        event_threshold: int = 28000,
        clear: bool = True,
    ) -> dict[str, Any]:
        source_code = self._preview_source_code(source)
        if not 0 <= int(event_threshold) <= 0xFFFF:
            raise ValueError("event_threshold must fit in 16 bits")
        self.ctrl.write(self.regs.PREVIEW_AUDIT_EVENT_THRESHOLD, int(event_threshold))
        control = (
            (0x1 if clear else 0x0)
            | ((0x1 if event_enable else 0x0) << 1)
            | ((0x1 if freeze_on_event else 0x0) << 2)
            | (source_code << 8)
        )
        self.ctrl.write(self.regs.PREVIEW_AUDIT_CONTROL, control)
        time.sleep(0.01)
        return self.read_preview_audit_status()

    def read_preview_audit_status(self) -> dict[str, Any]:
        status = self.read_status()
        return {
            "control": int(status["preview_audit_control"]),
            "status": int(status["preview_audit_status"]),
            "source": self._preview_source_name(int(status["preview_audit_source"])),
            "configured_source": self._preview_source_name(int(status["preview_audit_configured_source"])),
            "event_enable": bool(status["preview_audit_event_enable"]),
            "freeze_on_event": bool(status["preview_audit_freeze_on_event"]),
            "event_valid": bool(status["preview_event_valid"]),
            "event_active": bool(status["preview_event_active"]),
            "event_overflow": bool(status["preview_event_overflow"]),
            "sample0_nonmonotonic": bool(status["preview_sample0_nonmonotonic"]),
            "valid_gap_seen": bool(status["preview_valid_gap_seen"]),
            "sample0_error_seen": bool(status["preview_sample0_error_seen"]),
            "start_count": int(status["preview_audit_start_count"]),
            "first_count": int(status["preview_audit_first_count"]),
            "done_count": int(status["preview_audit_done_count"]),
            "start_sample0": int(status["preview_audit_start_sample0"]),
            "first_sample0": int(status["preview_audit_first_sample0"]),
            "done_sample0": int(status["preview_audit_done_sample0"]),
            "start_to_first_latency": int(status["preview_audit_start_to_first_latency"]),
            "capture_beats": int(status["preview_audit_capture_beats"]),
            "valid_gap_count": int(status["preview_audit_valid_gap_count"]),
            "sample0_error_count": int(status["preview_audit_sample0_error_count"]),
            "event_threshold": int(status["preview_audit_event_threshold"] & 0xFFFF),
            "event_sample0": int(status["preview_event_sample0"]),
            "event_max_code": int(status["preview_event_max_code"]),
            "event_info": int(status["preview_event_info"]),
            "event_rfdc_flags": int(status["preview_event_rfdc_flags"]),
            "event_dac_phase_epoch": int(status["preview_event_dac_phase_epoch"]),
            "event_buffer_words": int(status["preview_event_buffer_words"]),
        }

    def capture_preview_event(self, *, timeout: float = 1.0, n: Optional[int] = None) -> dict[str, Any]:
        deadline = time.monotonic() + float(timeout)
        audit = self.read_preview_audit_status()
        while not audit["event_valid"] and time.monotonic() < deadline:
            time.sleep(0.01)
            audit = self.read_preview_audit_status()
        if not audit["event_valid"]:
            raise TimeoutError(f"preview event capture timed out: PREVIEW_AUDIT_STATUS=0x{audit['status']:08x}")
        count = int(audit["event_buffer_words"])
        if n is not None:
            count = min(count, int(n))
        words = [int(self.ctrl.read(self.regs.PREVIEW_EVENT_BUFFER_BASE + 4 * idx)) for idx in range(count)]
        iq_list = [(self._s16(word & 0xFFFF), self._s16(word >> 16)) for word in words]
        try:
            import numpy as np

            iq: Any = np.array(iq_list, dtype=np.int16)
        except ImportError:
            iq = iq_list
        return {
            "audit": audit,
            "count": count,
            "sample0": int(audit["event_sample0"]),
            "max_code": int(audit["event_max_code"]),
            "rfdc_flags": int(audit["event_rfdc_flags"]),
            "dac_phase_epoch": int(audit["event_dac_phase_epoch"]),
            "words": words,
            "iq": iq,
        }

    def read_dac_audit_status(self) -> dict[str, int]:
        return {
            "phase_epoch_seen": int(self.ctrl.read(self.regs.DAC_AUDIT_PHASE_EPOCH_SEEN)),
            "ch0_phase_acc": int(self.ctrl.read(self.regs.DAC_AUDIT_CH0_PHASE_ACC)),
            "ch0_phase_step": int(self.ctrl.read(self.regs.DAC_AUDIT_CH0_PHASE_STEP)),
            "ch0_phase0": int(self.ctrl.read(self.regs.DAC_AUDIT_CH0_PHASE0)),
            "ch0_mode": int(self.ctrl.read(self.regs.DAC_AUDIT_CH0_MODE)),
        }

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
            "science_bandwidth_mhz": int(status.get("science_bandwidth_mhz", 0)),
            "science_output_mode": str(status.get("science_output_mode_name", "UNKNOWN")),
            "science_block_reasons": list(status.get("science_block_reasons", [])),
        }

    def capture_tx_header(self, *, timeout: float = 1.0) -> dict[str, Any]:
        try:
            from .packet import T510PacketHeader
        except ImportError:
            from packet import T510PacketHeader

        self.ctrl.write(self.regs.TX_HEADER_CAPTURE_CONTROL, 0x1)
        deadline = time.monotonic() + timeout
        status = self.read_status()
        while time.monotonic() < deadline:
            status = self.read_status()
            if status["tx_header_capture_valid"]:
                break
            time.sleep(0.005)
        else:
            raise TimeoutError(
                "TX header capture timed out: "
                f"TX_HEADER_CAPTURE_STATUS=0x{status['tx_header_capture_status']:08x}"
            )

        words32 = [
            int(self.ctrl.read(self.regs.TX_HEADER_CAPTURE_BUFFER_BASE + 4 * idx))
            for idx in range(32)
        ]
        axis_words = [
            (words32[idx * 2] & 0xFFFF_FFFF) | ((words32[idx * 2 + 1] & 0xFFFF_FFFF) << 32)
            for idx in range(16)
        ]
        header = T510PacketHeader.from_axis_words(axis_words)
        return {
            "header": header,
            "header_dict": header.to_dict(),
            "axis_words": axis_words,
            "words32": words32,
            "status": status,
        }

    @staticmethod
    def _tx_payload_witness_filter_code(stream: str | int) -> int:
        if isinstance(stream, int):
            code = int(stream)
        else:
            name = str(stream).strip().lower()
            aliases = {"any": 0, "all": 0, "*": 0, "spec": 1, "spectral": 1, "time": 2}
            if name not in aliases:
                raise ValueError(f"unknown TX payload witness stream filter {stream!r}")
            code = aliases[name]
        if code not in (0, 1, 2):
            raise ValueError("TX payload witness stream filter must be any=0, spec=1, or time=2")
        return code

    @staticmethod
    def _tx_payload_witness_filter_name(code: int) -> str:
        return {0: "any", 1: "spec", 2: "time"}.get(int(code), f"unknown_{int(code)}")

    def capture_tx_payload_witness(
        self,
        stream: str | int = "spec",
        *,
        timeout: float = 1.0,
        capture_words: int = 1040,
    ) -> dict[str, Any]:
        try:
            from .packet import T510PacketHeader
        except ImportError:
            from packet import T510PacketHeader

        capture_words = int(capture_words)
        if not 1 <= capture_words <= self.regs.TX_PAYLOAD_WITNESS_BUFFER_WORDS:
            raise ValueError(f"capture_words must be in range 1..{self.regs.TX_PAYLOAD_WITNESS_BUFFER_WORDS}")
        filter_code = self._tx_payload_witness_filter_code(stream)
        self.ctrl.write(self.regs.TX_PAYLOAD_WITNESS_STREAM_FILTER, filter_code)
        self.ctrl.write(self.regs.TX_PAYLOAD_WITNESS_CAPTURE_WORDS, capture_words)
        self.ctrl.write(self.regs.TX_PAYLOAD_WITNESS_CONTROL, 0x2)
        self.ctrl.write(self.regs.TX_PAYLOAD_WITNESS_CONTROL, 0x1)

        deadline = time.monotonic() + float(timeout)
        status = self.read_status()
        while time.monotonic() < deadline:
            status = self.read_status()
            if status.get("tx_payload_witness_valid"):
                break
            time.sleep(0.005)
        else:
            raise TimeoutError(
                "TX payload witness capture timed out: "
                f"TX_PAYLOAD_WITNESS_STATUS=0x{status.get('tx_payload_witness_status', 0):08x}"
            )

        word_count = max(0, min(capture_words, int(status.get("tx_payload_witness_word_count", 0))))
        mmio_array = getattr(self.ctrl, "array", None)
        if mmio_array is None:
            mmio = getattr(self.ctrl, "mmio", None)
            mmio_array = getattr(mmio, "array", None)
        if mmio_array is not None:
            import numpy as np

            word_index = self.regs.TX_PAYLOAD_WITNESS_BUFFER_BASE // 4
            words32 = [int(word) for word in np.asarray(mmio_array[word_index:word_index + word_count * 2], dtype=np.uint32).copy()]
            fast_path = True
        else:
            words32 = [
                int(self.ctrl.read(self.regs.TX_PAYLOAD_WITNESS_BUFFER_BASE + 4 * idx))
                for idx in range(word_count * 2)
            ]
            fast_path = False
        axis_words = [
            (words32[idx * 2] & 0xFFFF_FFFF) | ((words32[idx * 2 + 1] & 0xFFFF_FFFF) << 32)
            for idx in range(word_count)
        ]
        if len(axis_words) < 16:
            raise RuntimeError(f"TX payload witness captured only {len(axis_words)} words; need at least 16")
        header = T510PacketHeader.from_axis_words(axis_words[:16])
        layout_word = (
            int(self.ctrl.read(self.regs.TX_PAYLOAD_WITNESS_LAYOUT_LO))
            | (int(self.ctrl.read(self.regs.TX_PAYLOAD_WITNESS_LAYOUT_HI)) << 32)
        )
        metadata = {
            "sample0": int(self.ctrl.read(self.regs.TX_PAYLOAD_WITNESS_SAMPLE0_LO))
            | (int(self.ctrl.read(self.regs.TX_PAYLOAD_WITNESS_SAMPLE0_HI)) << 32),
            "frame_id": int(self.ctrl.read(self.regs.TX_PAYLOAD_WITNESS_FRAME_ID_LO))
            | (int(self.ctrl.read(self.regs.TX_PAYLOAD_WITNESS_FRAME_ID_HI)) << 32),
            "seq_no": int(self.ctrl.read(self.regs.TX_PAYLOAD_WITNESS_SEQ_NO)),
            "chan0": int(self.ctrl.read(self.regs.TX_PAYLOAD_WITNESS_CHAN0)),
            "layout_word": layout_word,
            "payload_bytes": int(self.ctrl.read(self.regs.TX_PAYLOAD_WITNESS_PAYLOAD_BYTES)),
            "route_meta": int(self.ctrl.read(self.regs.TX_PAYLOAD_WITNESS_ROUTE_META)),
            "rfdc_flags": int(self.ctrl.read(self.regs.TX_PAYLOAD_WITNESS_RFDC_FLAGS)),
            "rfdc_sample_count": int(self.ctrl.read(self.regs.TX_PAYLOAD_WITNESS_RFDC_SAMPLE_COUNT_LO))
            | (int(self.ctrl.read(self.regs.TX_PAYLOAD_WITNESS_RFDC_SAMPLE_COUNT_HI)) << 32),
            "dac_phase_epoch": int(self.ctrl.read(self.regs.TX_PAYLOAD_WITNESS_DAC_PHASE_EPOCH)),
        }
        route_meta = int(metadata["route_meta"])
        metadata.update(
            {
                "route_stream_type": (route_meta >> 16) & 0xFFFF,
                "route_is_time": (route_meta >> 11) & 0x1,
                "route_id": (route_meta >> 8) & 0x7,
                "endpoint_id": (route_meta >> 5) & 0x7,
            }
        )
        return {
            "header": header,
            "header_dict": header.to_dict(),
            "axis_words": axis_words,
            "payload_words": axis_words[16:],
            "words32": words32,
            "word_count": word_count,
            "capture_words": capture_words,
            "fast_path": fast_path,
            "stream_filter": filter_code,
            "stream_filter_name": self._tx_payload_witness_filter_name(filter_code),
            "metadata": metadata,
            "status": status,
        }

    def capture_dac_tx_witness(
        self,
        *,
        timeout: float = 1.0,
        capture_words: int = 256,
    ) -> dict[str, Any]:
        capture_words = int(capture_words)
        if not 1 <= capture_words <= self.regs.DAC_TX_WITNESS_BUFFER_WORDS:
            raise ValueError("capture_words must be in range 1..256")

        self.ctrl.write(self.regs.DAC_TX_WITNESS_CAPTURE_WORDS, capture_words)
        self.ctrl.write(self.regs.DAC_TX_WITNESS_CONTROL, 0x2)
        self.ctrl.write(self.regs.DAC_TX_WITNESS_CONTROL, 0x1)

        deadline = time.monotonic() + float(timeout)
        status = self.read_status()
        while time.monotonic() < deadline:
            status = self.read_status()
            if status.get("dac_tx_witness_valid"):
                break
            time.sleep(0.005)
        else:
            raise TimeoutError(
                "DAC TX witness capture timed out: "
                f"DAC_TX_WITNESS_STATUS=0x{status.get('dac_tx_witness_status', 0):08x}"
            )

        word_count = max(0, min(capture_words, int(status.get("dac_tx_witness_word_count", 0))))
        words32 = [
            int(self.ctrl.read(self.regs.DAC_TX_WITNESS_BUFFER_BASE + 4 * idx))
            for idx in range(word_count * 4)
        ]
        words128: list[int] = []
        for idx in range(word_count):
            base = idx * 4
            word = 0
            for lane in range(4):
                word |= (words32[base + lane] & 0xFFFF_FFFF) << (32 * lane)
            words128.append(word)

        metadata = {
            "phase_epoch": int(self.ctrl.read(self.regs.DAC_TX_WITNESS_PHASE_EPOCH)),
            "phase_acc": int(self.ctrl.read(self.regs.DAC_TX_WITNESS_PHASE_ACC)),
            "phase_step": int(self.ctrl.read(self.regs.DAC_TX_WITNESS_PHASE_STEP)),
            "phase0": int(self.ctrl.read(self.regs.DAC_TX_WITNESS_PHASE0)),
            "mode": int(self.ctrl.read(self.regs.DAC_TX_WITNESS_MODE)),
            "ready_gap_count": int(self.ctrl.read(self.regs.DAC_TX_WITNESS_READY_GAP_COUNT)),
        }
        decoded = self.decode_dac_tx_words(words128)
        return {
            "axis_words": words128,
            "words128": words128,
            "words32": words32,
            "word_count": word_count,
            "capture_words": capture_words,
            "metadata": metadata,
            "decoded": decoded,
            "status": status,
        }

    @staticmethod
    def decode_rfdc_axis_raw_words(
        witness: Mapping[str, Any] | list[int] | tuple[int, ...],
    ) -> dict[str, Any]:
        import numpy as np

        if isinstance(witness, Mapping):
            words = [int(word) & 0xFFFF_FFFF for word in witness.get("words32", witness.get("words", []))]
        else:
            words = [int(word) & 0xFFFF_FFFF for word in witness]

        decoded: list[tuple[int, int]] = []
        beat_index: list[int] = []
        subsample_index: list[int] = []
        lanes: list[list[tuple[int, int]]] = [[], [], [], []]
        for idx, word in enumerate(words):
            i_sample = T510FEngine._s16(word & 0xFFFF)
            q_sample = T510FEngine._s16((word >> 16) & 0xFFFF)
            pair = (i_sample, q_sample)
            decoded.append(pair)
            beat_index.append(idx // 4)
            subsample_index.append(idx % 4)
            lanes[idx % 4].append(pair)

        return {
            "iq": np.asarray(decoded, dtype=np.int16),
            "beat_index": np.asarray(beat_index, dtype=np.int64),
            "subsample_index": np.asarray(subsample_index, dtype=np.int64),
            "lanes": [np.asarray(values, dtype=np.int16) for values in lanes],
            "word_count": len(words),
            "beat_count": len(words) // 4,
        }

    def capture_rfdc_axis_raw_witness(
        self,
        channel: int = 0,
        *,
        timeout: float = 1.0,
        capture_beats: int = 256,
    ) -> dict[str, Any]:
        capture_beats = int(capture_beats)
        channel = int(channel)
        if not 0 <= channel <= 7:
            raise ValueError("channel must be in range 0..7")
        max_beats = self.regs.RFDC_AXIS_RAW_WITNESS_BUFFER_WORDS // 4
        if not 1 <= capture_beats <= max_beats:
            raise ValueError(
                f"capture_beats must be in range 1..{max_beats}"
            )

        self.ctrl.write(self.regs.RFDC_AXIS_RAW_WITNESS_CHANNEL_SELECT, channel)
        self.ctrl.write(self.regs.RFDC_AXIS_RAW_WITNESS_CAPTURE_BEATS, capture_beats)
        self.ctrl.write(self.regs.RFDC_AXIS_RAW_WITNESS_CONTROL, 0x2)
        self.ctrl.write(self.regs.RFDC_AXIS_RAW_WITNESS_CONTROL, 0x1)

        deadline = time.monotonic() + float(timeout)
        status = self.read_status()
        while time.monotonic() < deadline:
            status = self.read_status()
            if status.get("rfdc_axis_raw_witness_valid"):
                break
            time.sleep(0.005)
        else:
            raise TimeoutError(
                "RFDC AXIS raw witness capture timed out: "
                f"RFDC_AXIS_RAW_WITNESS_STATUS=0x{status.get('rfdc_axis_raw_witness_status', 0):08x}"
            )

        beat_count = max(0, min(capture_beats, int(status.get("rfdc_axis_raw_witness_beat_count", 0))))
        word_count = beat_count * 4
        mmio_array = getattr(self.ctrl, "array", None)
        if mmio_array is None:
            mmio = getattr(self.ctrl, "mmio", None)
            mmio_array = getattr(mmio, "array", None)
        if mmio_array is not None:
            import numpy as np

            word_index = self.regs.RFDC_AXIS_RAW_WITNESS_BUFFER_BASE // 4
            words32 = [
                int(word)
                for word in np.asarray(mmio_array[word_index:word_index + word_count], dtype=np.uint32).copy()
            ]
        else:
            words32 = [
                int(self.ctrl.read(self.regs.RFDC_AXIS_RAW_WITNESS_BUFFER_BASE + 4 * idx))
                for idx in range(word_count)
            ]

        decoded = self.decode_rfdc_axis_raw_words(words32)
        return {
            "channel": channel,
            "capture_beats": capture_beats,
            "beat_count": beat_count,
            "word_count": word_count,
            "sample0": int(self.ctrl.read(self.regs.RFDC_AXIS_RAW_WITNESS_SAMPLE0_LO))
            | (int(self.ctrl.read(self.regs.RFDC_AXIS_RAW_WITNESS_SAMPLE0_HI)) << 32),
            "rfdc_flags": int(status.get("rfdc_axis_raw_witness_rfdc_flags", 0)),
            "valid_mask": int(status.get("rfdc_axis_raw_witness_valid_mask", 0)),
            "words32": words32,
            "decoded": decoded,
            "status": status,
        }

    @staticmethod
    def decode_dac_tx_words(
        witness: Mapping[str, Any] | list[int] | tuple[int, ...],
    ) -> dict[str, Any]:
        import numpy as np

        if isinstance(witness, Mapping):
            words = [int(word) & ((1 << 128) - 1) for word in witness.get("axis_words", witness.get("words128", []))]
        else:
            words = [int(word) & ((1 << 128) - 1) for word in witness]

        decoded: list[tuple[int, int]] = []
        lanes: list[list[tuple[int, int]]] = [[], [], [], []]
        sample_offsets: list[int] = []
        for word_index, word in enumerate(words):
            for lane in range(4):
                complex_word = (word >> (32 * lane)) & 0xFFFF_FFFF
                i_sample = T510FEngine._s16(complex_word & 0xFFFF)
                q_sample = T510FEngine._s16((complex_word >> 16) & 0xFFFF)
                pair = (i_sample, q_sample)
                decoded.append(pair)
                lanes[lane].append(pair)
                sample_offsets.append(word_index * 4 + lane)

        return {
            "iq": np.asarray(decoded, dtype=np.int16),
            "lanes": [np.asarray(values, dtype=np.int16) for values in lanes],
            "sample_offsets": np.asarray(sample_offsets, dtype=np.int64),
            "sample_stride": 1,
            "word_count": len(words),
            "decoded_count": len(decoded),
        }

    @staticmethod
    def compute_dac_source_phase_metrics(
        dac_iq: Mapping[str, Any] | Any,
        *,
        sample_rate_hz: float = 245_760_000.0,
        tone_hz: Optional[float] = None,
        phase_step: Optional[int] = None,
        sample_offsets: Optional[Any] = None,
    ) -> dict[str, Any]:
        import numpy as np

        if isinstance(dac_iq, Mapping) and "decoded" in dac_iq:
            decoded = dac_iq["decoded"]
            metadata = dac_iq.get("metadata", {})
            iq = np.asarray(decoded["iq"], dtype=np.float64)
            if sample_offsets is None:
                sample_offsets = decoded.get("sample_offsets")
            if phase_step is None and isinstance(metadata, Mapping):
                phase_step = int(metadata.get("phase_step", 0))
        elif isinstance(dac_iq, Mapping):
            iq = np.asarray(dac_iq["iq"], dtype=np.float64)
            if sample_offsets is None:
                sample_offsets = dac_iq.get("sample_offsets")
        else:
            iq = np.asarray(dac_iq, dtype=np.float64)

        if iq.ndim != 2 or iq.shape[1] != 2:
            raise ValueError("dac_iq must have shape (n, 2)")
        count = int(iq.shape[0])
        if count <= 0:
            raise ValueError("dac_iq must contain at least one IQ sample")
        sample_rate = float(sample_rate_hz)
        if sample_rate <= 0.0:
            raise ValueError("sample_rate_hz must be positive")

        if sample_offsets is None:
            offsets = np.arange(count, dtype=np.float64)
        else:
            offsets = np.asarray(sample_offsets, dtype=np.float64)
            if offsets.size != count:
                raise ValueError("sample_offsets length must match dac_iq sample count")

        if tone_hz is None:
            step = 0 if phase_step is None else int(phase_step) & 0xFFFF_FFFF
            if step & 0x8000_0000:
                step -= 1 << 32
            tone_hz = (float(step) / float(1 << 32)) * sample_rate

        z = iq[:, 0] + 1j * iq[:, 1]
        # DAC source RTL emits I=sin(phase), Q=cos(phase), so I+jQ rotates in
        # the negative direction for a positive phase step.
        basis = np.exp(-1j * 2.0 * np.pi * float(tone_hz) * offsets / sample_rate)
        residual = z / basis
        amplitude = np.abs(residual)
        phase_deg = np.rad2deg(np.unwrap(np.angle(residual)))
        amp_mean = float(np.mean(amplitude)) if count else 0.0
        amp_pp = float(np.max(amplitude) - np.min(amplitude)) if count else 0.0
        phase_pp = float(np.max(phase_deg) - np.min(phase_deg)) if count else 0.0
        return {
            "count": count,
            "sample_rate_hz": sample_rate,
            "tone_hz": float(tone_hz),
            "phase_step": None if phase_step is None else int(phase_step) & 0xFFFF_FFFF,
            "phase_deg": phase_deg,
            "amplitude": amplitude,
            "phase_pp_deg": phase_pp,
            "amplitude_pp": amp_pp,
            "amplitude_mean": amp_mean,
            "amplitude_pp_percent": (100.0 * amp_pp / amp_mean) if amp_mean > 0.0 else float("inf"),
            "first_phase_deg": float(phase_deg[0]),
            "last_phase_deg": float(phase_deg[-1]),
        }

    @staticmethod
    def decode_time_payload_iq(
        witness: Mapping[str, Any] | list[int] | tuple[int, ...],
        *,
        channel: int = 0,
    ) -> dict[str, Any]:
        return T510FEngine._decode_payload_iq_words(witness, channel=channel, stream_hint="time")

    @staticmethod
    def decode_spec_payload_iq(
        witness: Mapping[str, Any] | list[int] | tuple[int, ...],
        *,
        channel: int = 0,
    ) -> dict[str, Any]:
        return T510FEngine._decode_payload_iq_words(witness, channel=channel, stream_hint="spec")

    @staticmethod
    def _decode_payload_iq_words(
        witness: Mapping[str, Any] | list[int] | tuple[int, ...],
        *,
        channel: int = 0,
        stream_hint: str = "unknown",
    ) -> dict[str, Any]:
        import numpy as np

        if not 0 <= int(channel) < 8:
            raise ValueError("channel must be in range 0..7")
        header = None
        sample0 = 0
        payload_words: list[int]
        if isinstance(witness, Mapping):
            payload_words = [int(word) & 0xFFFF_FFFF_FFFF_FFFF for word in witness.get("payload_words", [])]
            header = witness.get("header")
            if header is not None:
                sample0 = int(getattr(header, "sample0", 0))
            else:
                metadata = witness.get("metadata", {})
                if isinstance(metadata, Mapping):
                    sample0 = int(metadata.get("sample0", 0))
        else:
            payload_words = [int(word) & 0xFFFF_FFFF_FFFF_FFFF for word in witness]

        subword = int(channel) // 2
        half = int(channel) & 0x1
        decoded: list[tuple[int, int]] = []
        sample_offsets: list[int] = []
        for payload_index, word in enumerate(payload_words):
            if (payload_index % 4) != subword:
                continue
            complex_word = (word >> (32 * half)) & 0xFFFF_FFFF
            i_sample = T510FEngine._s16(complex_word & 0xFFFF)
            q_sample = T510FEngine._s16((complex_word >> 16) & 0xFFFF)
            decoded.append((i_sample, q_sample))
            sample_offsets.append((payload_index // 4) * 4)

        return {
            "channel": int(channel),
            "stream_hint": str(stream_hint),
            "iq": np.asarray(decoded, dtype=np.int16),
            "sample0": sample0,
            "sample_offsets": np.asarray(sample_offsets, dtype=np.int64),
            "sample_stride": 4,
            "payload_word_count": len(payload_words),
            "decoded_count": len(decoded),
            "header": header,
        }

    @staticmethod
    def compute_payload_phase_metrics(
        payload_iq: Mapping[str, Any] | Any,
        *,
        sample0: Optional[int] = None,
        sample_rate_hz: float = 245_760_000.0,
        observe_center_hz: float,
        dac_signal_hz: float,
        expected_signal_hz: Optional[float] = None,
        configured_phase_deg: float = 0.0,
        alignment_anchor_deg: float = 0.0,
        sample_stride: Optional[int] = None,
        sample_offsets: Optional[Any] = None,
    ) -> dict[str, Any]:
        import numpy as np

        if isinstance(payload_iq, Mapping):
            iq = np.asarray(payload_iq["iq"], dtype=np.float64)
            if sample0 is None:
                sample0 = int(payload_iq.get("sample0", 0))
            if sample_stride is None:
                sample_stride = int(payload_iq.get("sample_stride", 4))
            if sample_offsets is None and "sample_offsets" in payload_iq:
                sample_offsets = payload_iq["sample_offsets"]
        else:
            iq = np.asarray(payload_iq, dtype=np.float64)
        if iq.ndim != 2 or iq.shape[1] != 2:
            raise ValueError("payload_iq must have shape (n, 2)")
        count = int(iq.shape[0])
        if count <= 0:
            raise ValueError("payload_iq must contain at least one IQ sample")
        sample_rate = float(sample_rate_hz)
        if sample_rate <= 0.0:
            raise ValueError("sample_rate_hz must be positive")
        sample0_value = int(0 if sample0 is None else sample0)
        if sample_offsets is None:
            stride = int(4 if sample_stride is None else sample_stride)
            offsets = np.arange(count, dtype=np.float64) * float(stride)
        else:
            offsets = np.asarray(sample_offsets, dtype=np.float64)
            if offsets.size != count:
                raise ValueError("sample_offsets length must match payload_iq sample count")
            stride = int(sample_stride if sample_stride is not None else 4)

        signal_hz = float(dac_signal_hz if expected_signal_hz is None else expected_signal_hz)
        expected_baseband_hz = signal_hz - float(observe_center_hz)
        t_fit = offsets / sample_rate
        z = iq[:, 0] + 1j * iq[:, 1]
        expected_basis = np.exp(1j * 2.0 * np.pi * expected_baseband_hz * t_fit)
        expected_basis_norm = max(float(np.vdot(expected_basis, expected_basis).real), 1.0)
        coeff = np.vdot(expected_basis, z) / expected_basis_norm
        fit = coeff * expected_basis
        residual = z - fit
        measured_phase_deg = float(np.angle(coeff, deg=True))
        sample0_phase_deg = (
            360.0 * ((sample0_value * expected_baseband_hz / sample_rate) % 1.0)
        ) % 360.0
        sample0_aligned_phase_deg = T510FEngine._wrap_phase_deg(measured_phase_deg - sample0_phase_deg)
        phase_error_deg = T510FEngine._wrap_phase_deg(
            sample0_aligned_phase_deg - float(configured_phase_deg) - float(alignment_anchor_deg)
        )
        amplitude_code = float(abs(coeff))
        max_abs_code = float(np.max(np.abs(iq))) if iq.size else 0.0
        rms_code = float(np.sqrt(np.mean(iq[:, 0] * iq[:, 0] + iq[:, 1] * iq[:, 1]))) if iq.size else 0.0
        residual_rms_code = float(np.sqrt(np.mean(np.abs(residual) ** 2))) if residual.size else 0.0
        signal_rms_code = float(np.sqrt(np.mean(np.abs(fit) ** 2))) if fit.size else 0.0
        residual_fraction = residual_rms_code / max(signal_rms_code, 1.0)
        if count >= 4:
            window = np.hanning(count)
            nfft = int(2 ** np.ceil(np.log2(max(16, count * 8))))
            nfft = min(65536, max(16, nfft))
            sample_step_s = float(stride) / sample_rate
            freq_hz = np.fft.fftshift(np.fft.fftfreq(nfft, d=sample_step_s))
            spectrum = np.fft.fftshift(np.fft.fft(z * window, n=nfft))
            power = np.abs(spectrum) ** 2
            peak_idx = int(np.argmax(power))
            peak_hz = T510FEngine._interp_peak_from_power(freq_hz, power, peak_idx)
            guard = max(2, nfft // 128)
            noise_mask = np.ones_like(power, dtype=bool)
            noise_mask[max(0, peak_idx - guard):min(len(noise_mask), peak_idx + guard + 1)] = False
            noise_floor = float(np.median(power[noise_mask])) if np.any(noise_mask) else 1.0
            snr_db = float(10.0 * np.log10(max(float(power[peak_idx]), 1.0) / max(noise_floor, 1.0)))
        else:
            peak_hz = 0.0
            snr_db = 0.0
        return {
            "sample0": sample0_value,
            "sample_rate_hz": sample_rate,
            "sample_stride": stride,
            "sample_count": count,
            "dac_signal_hz": float(dac_signal_hz),
            "expected_signal_hz": signal_hz,
            "expected_baseband_hz": expected_baseband_hz,
            "measured_phase_deg": measured_phase_deg,
            "sample0_mod_phase_deg": float(sample0_phase_deg),
            "sample0_aligned_phase_deg": sample0_aligned_phase_deg,
            "configured_phase_deg": float(configured_phase_deg),
            "alignment_anchor_deg": float(alignment_anchor_deg),
            "phase_error_deg": phase_error_deg,
            "amplitude_code": amplitude_code,
            "rms_code": rms_code,
            "max_abs_code": max_abs_code,
            "fit_residual_rms_code": residual_rms_code,
            "fit_residual_fraction": residual_fraction,
            "fit_residual_db": float(20.0 * np.log10(max(residual_fraction, 1e-12))),
            "fft_peak_hz": float(peak_hz),
            "fft_peak_mhz": float(peak_hz / 1_000_000.0),
            "snr_db": snr_db,
            "clipped": bool(max_abs_code >= 32760.0),
        }

    def capture_pfb_preview(
        self,
        *,
        input_mask: int = 0x01,
        n: Optional[int] = 256,
        timeout: float = 1.0,
        include_adc_preview: bool = True,
    ) -> dict[str, Any]:
        pfb_before = self.read_channelizer_status()
        header_capture = self.capture_tx_header(timeout=timeout)
        pfb_after = self.read_channelizer_status()
        result: dict[str, Any] = {
            "pfb_before": pfb_before,
            "pfb_after": pfb_after,
            "tx_header": header_capture["header"],
            "tx_header_dict": header_capture["header_dict"],
            "axis_words": header_capture["axis_words"],
        }
        if include_adc_preview:
            result["adc_preview"] = self.capture_preview(n=n, input_mask=input_mask, timeout=timeout)
        return result

    @staticmethod
    def _s16(value: int) -> int:
        value &= 0xFFFF
        return value - 0x1_0000 if value & 0x8000 else value

    def _wait_debug_done(self, timeout: float) -> dict[str, int]:
        deadline = time.monotonic() + timeout
        status = self.read_status()
        while time.monotonic() < deadline:
            status = self.read_status()
            if status["debug_done"]:
                return status
            if status["debug_error"]:
                raise RuntimeError(f"debug capture failed: DEBUG_STATUS=0x{status['debug_status']:08x}")
            time.sleep(0.005)
        raise TimeoutError(f"debug capture timed out: DEBUG_STATUS=0x{status['debug_status']:08x}")

    def _trigger_debug_capture(self, timeout: float = 1.0) -> dict[str, int]:
        status = self.read_status()
        if not status["rfdc_clock_locked"]:
            raise RuntimeError(
                "debug capture cannot run: PL/RFDC data clock is not locked "
                "(RFDC_FLAGS bit3=0). Run configure_clock/init_lab_rfdc and "
                "verify the LMK/245.76 MHz clock path first."
            )
        if not status["rfdc_adc_valid"]:
            raise RuntimeError(
                "debug capture cannot run: RFDC ADC AXIS valid is low "
                "(RFDC_FLAGS bit1=0). Verify RFDC tile startup and ADC0 input."
            )
        self.ctrl.write(self.regs.DEBUG_CONTROL, 0x2)
        self.ctrl.write(self.regs.DEBUG_CONTROL, 0x1)
        return self._wait_debug_done(timeout)

    def capture_time(self, n: Optional[int] = None, *, timeout: float = 1.0) -> Any:
        status = self._trigger_debug_capture(timeout=timeout)
        nfft = int(status["debug_nfft"])
        count = nfft if n is None else min(int(n), nfft)
        words = [int(self.ctrl.read(self.regs.DEBUG_TIME_BUFFER_BASE + 4 * i)) for i in range(count)]
        iq = [(self._s16(word & 0xFFFF), self._s16(word >> 16)) for word in words]
        try:
            import numpy as np

            return np.array(iq, dtype=np.int16)
        except ImportError:
            return iq

    def capture_spectrum(self, *, timeout: float = 1.0) -> dict[str, Any]:
        status = self._trigger_debug_capture(timeout=timeout)
        nfft = int(status["debug_nfft"])
        sample_rate = int(status["debug_sample_rate_hz"])
        power_words = [
            int(self.ctrl.read(self.regs.DEBUG_FFT_BUFFER_BASE + 4 * i))
            for i in range(nfft)
        ]
        try:
            import numpy as np

            power: Any = np.array(power_words, dtype=np.uint32)
            freq_hz: Any = np.arange(nfft, dtype=np.float64) * (sample_rate / nfft)
        except ImportError:
            power = power_words
            freq_hz = [i * (sample_rate / nfft) for i in range(nfft)]
        return {
            "power": power,
            "freq_hz": freq_hz,
            "sample_rate_hz": sample_rate,
            "peak_bin": int(status["debug_peak_bin"]),
            "peak_power": int(status["debug_peak_power"]),
        }

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

    def _trigger_preview_capture(self, input_mask: int, timeout: float = 1.0) -> dict[str, int]:
        if not 0 < input_mask <= 0xFF:
            raise ValueError("preview input_mask must be in range 0x01..0xff")
        status = self.read_status()
        if not status["streaming"]:
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
    ) -> dict[str, Any]:
        status = self._trigger_preview_capture(input_mask=input_mask, timeout=timeout)
        return self._read_preview_buffer_from_status(status, n=n, input_mask=input_mask, prefer_fast=True)

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

    def capture_preview_readback_check(
        self,
        n: Optional[int] = None,
        *,
        input_mask: int = 0x01,
        timeout: float = 1.0,
        include_data: bool = False,
    ) -> dict[str, Any]:
        """Capture once, then read the same preview BRAM twice without retriggering.

        A mismatch here points below Jupyter/Plotly: preview BRAM, MMIO readout,
        CDC, or arbitration is changing data after PREVIEW_DONE.
        """
        status = self._trigger_preview_capture(input_mask=input_mask, timeout=timeout)
        first = self._read_preview_buffer_from_status(status, n=n, input_mask=input_mask, prefer_fast=True)
        second = self._read_preview_buffer_from_status(status, n=n, input_mask=input_mask, prefer_fast=True)
        per_channel: dict[int, dict[str, Any]] = {}
        total_mismatches = 0
        try:
            import numpy as np
        except ImportError:
            np = None  # type: ignore[assignment]

        for idx in first["inputs"]:
            a = first["iq"][idx]
            b = second["iq"][idx]
            if np is not None:
                arr_a = np.asarray(a)
                arr_b = np.asarray(b)
                mismatch_mask = arr_a != arr_b
                mismatch_count = int(np.count_nonzero(mismatch_mask))
                first_mismatch = None
                if mismatch_count:
                    pos = np.argwhere(mismatch_mask)[0]
                    first_mismatch = {
                        "sample": int(pos[0]),
                        "lane": int(pos[1]) if len(pos) > 1 else 0,
                        "first": int(arr_a[tuple(pos)]),
                        "second": int(arr_b[tuple(pos)]),
                    }
            else:
                mismatch_count = 0
                first_mismatch = None
                for sample_idx, (sample_a, sample_b) in enumerate(zip(a, b)):
                    if sample_a != sample_b:
                        mismatch_count += 1
                        if first_mismatch is None:
                            first_mismatch = {
                                "sample": sample_idx,
                                "lane": -1,
                                "first": sample_a,
                                "second": sample_b,
                            }
            total_mismatches += mismatch_count
            per_channel[int(idx)] = {
                "match": mismatch_count == 0,
                "mismatch_count": mismatch_count,
                "first_mismatch": first_mismatch,
            }

        result: dict[str, Any] = {
            "match": total_mismatches == 0,
            "mismatch_count": total_mismatches,
            "input_mask": int(input_mask),
            "inputs": list(first["inputs"]),
            "count": int(first["count"]),
            "sample0": int(first["sample0"]),
            "sample_rate_hz": int(first["sample_rate_hz"]),
            "preview_status": int(status.get("preview_status", 0)),
            "preview_capture_count": int(status.get("preview_capture_count", 0)),
            "dac_phase_epoch": int(status.get("dac_phase_epoch", 0)),
            "rfdc_status_flags": int(status.get("rfdc_status_flags", 0)),
            "per_channel": per_channel,
        }
        if include_data:
            result["first_preview"] = first
            result["second_preview"] = second
        return result

    @staticmethod
    def synthetic_phase_frame(
        *,
        n: int = 512,
        input_mask: int = 0x01,
        sample0: int = 0,
        sample_rate_hz: float = 245_760_000.0,
        observe_center_hz: float = 100_000_000.0,
        dac_signal_hz: float = 100_000_000.0,
        amplitude: float = 2048.0,
        phase_deg: float = 0.0,
        phase_deg_per_channel: float = 0.0,
        noise_rms: float = 0.0,
    ) -> dict[str, Any]:
        import numpy as np

        n = int(n)
        if n <= 0:
            raise ValueError("n must be positive")
        if not 0 < int(input_mask) <= 0xFF:
            raise ValueError("input_mask must be in range 0x01..0xff")
        sample_rate_hz = float(sample_rate_hz)
        baseband_hz = float(dac_signal_hz) - float(observe_center_hz)
        inputs = [idx for idx in range(8) if int(input_mask) & (1 << idx)]
        sample_index = int(sample0) + np.arange(n, dtype=np.float64)
        t = sample_index / sample_rate_hz
        rng = np.random.default_rng(0)
        samples: dict[int, Any] = {}
        for idx in inputs:
            phase_rad = np.deg2rad(float(phase_deg) + float(phase_deg_per_channel) * idx)
            z = float(amplitude) * np.exp(1j * (2.0 * np.pi * baseband_hz * t + phase_rad))
            if noise_rms > 0.0:
                noise = rng.normal(0.0, float(noise_rms), n) + 1j * rng.normal(0.0, float(noise_rms), n)
                z = z + noise
            iq = np.empty((n, 2), dtype=np.int16)
            iq[:, 0] = np.clip(np.round(np.real(z)), -32768, 32767).astype(np.int16)
            iq[:, 1] = np.clip(np.round(np.imag(z)), -32768, 32767).astype(np.int16)
            samples[idx] = iq
        return {
            "input_mask": int(input_mask),
            "inputs": inputs,
            "sample0": int(sample0),
            "sample_rate_hz": int(round(sample_rate_hz)),
            "axis_beat_rate_hz": int(round(sample_rate_hz / 4.0)),
            "preview_mode": 0,
            "phase_ref_input": 0,
            "center_freq_hz": float(observe_center_hz),
            "bandwidth_hz": float(min(sample_rate_hz, 100_000_000.0)),
            "count": n,
            "iq": samples,
            "synthetic": True,
        }

    @staticmethod
    def compute_phase_provenance(
        preview: Mapping[str, Any],
        *,
        observe_center_hz: Optional[float] = None,
        view_bw_hz: Optional[float] = None,
        dac_signal_hz: Optional[float] = None,
        expected_signal_hz: Optional[float] = None,
        configured_phase_deg: float = 0.0,
        display_phase_deg: Optional[float] = None,
        phase_deg_per_channel: float = 0.0,
        phase_deg_by_channel: Optional[Mapping[Any, Any] | Iterable[Any]] = None,
        phase_ref_input: int = 0,
        oversample: float = 8.0,
        input_source_mode: str = "dac_loopback",
    ) -> dict[str, Any]:
        """Separate configured, measured, sample0-coherent, and display phase.

        The Stage 11/12 RF scope is intentionally configuration-locked. This
        helper exposes the raw ADC phase separately so the UI cannot accidentally
        present display stability as hardware phase stability.
        """
        import math
        import numpy as np

        sample_rate = float(preview["sample_rate_hz"])
        count = int(preview["count"])
        sample0 = int(preview["sample0"])
        if count <= 0:
            raise ValueError("preview count must be positive")
        observe_center_value = float(
            observe_center_hz if observe_center_hz is not None else preview.get("center_freq_hz", 0.0)
        )
        view_bw_value = float(
            view_bw_hz if view_bw_hz is not None else preview.get("bandwidth_hz", sample_rate)
        )
        display_phase_base = float(configured_phase_deg if display_phase_deg is None else display_phase_deg)
        expected_signal_value = expected_signal_hz if expected_signal_hz is not None else dac_signal_hz
        expected_baseband_hz = (
            None if expected_signal_value is None else float(expected_signal_value) - observe_center_value
        )
        input_source_mode = T510FEngine._normalize_input_source_mode(input_source_mode)
        nfft = max(4096, int(2 ** math.ceil(math.log2(max(2.0, count * max(float(oversample), 1.0))))))
        nfft = min(65536, nfft)
        freq_hz = np.fft.fftshift(np.fft.fftfreq(nfft, d=1.0 / sample_rate))
        passband = np.abs(freq_hz) <= max(view_bw_value / 2.0, sample_rate / max(nfft, 1))
        if not np.any(passband):
            passband = np.ones_like(freq_hz, dtype=bool)
        window = np.hanning(count)
        window_norm = max(float(np.sum(window)), 1.0)
        full_scale = 32768.0

        channels: dict[int, dict[str, Any]] = {}
        ref_measured: Optional[float] = None
        ref_coherent: Optional[float] = None
        for idx, iq in preview["iq"].items():
            arr = np.asarray(iq, dtype=np.float64)
            i_data = arr[:, 0]
            q_data = arr[:, 1]
            z = i_data + 1j * q_data
            fft = np.fft.fftshift(np.fft.fft(z * window, n=nfft))
            power = np.abs(fft) ** 2
            masked_power = np.where(passband, power, 0.0)
            peak_idx = int(np.argmax(masked_power))
            raw_peak_hz = T510FEngine._interp_peak_from_power(freq_hz, masked_power, peak_idx)
            if expected_baseband_hz is not None:
                alt_peak_hz = -raw_peak_hz
                logical_peak_hz = alt_peak_hz if abs(alt_peak_hz - expected_baseband_hz) < abs(raw_peak_hz - expected_baseband_hz) else raw_peak_hz
            else:
                logical_peak_hz = raw_peak_hz

            t = np.arange(count, dtype=np.float64) / sample_rate
            basis = np.exp(1j * 2.0 * np.pi * raw_peak_hz * t)
            coeff = np.vdot(basis, z) / max(float(np.vdot(basis, basis).real), 1.0)
            fit = coeff * basis
            residual = z - fit
            measured_phase = float(np.angle(coeff, deg=True))
            sample0_correction = (360.0 * raw_peak_hz * (sample0 / sample_rate)) % 360.0
            coherent_phase = T510FEngine._wrap_phase_deg(measured_phase - sample0_correction)
            configured_ch_phase = T510FEngine._configured_phase_deg_for_channel(
                int(idx),
                configured_phase_deg=float(configured_phase_deg),
                phase_deg_per_channel=float(phase_deg_per_channel),
                phase_deg_by_channel=phase_deg_by_channel,
            )
            display_ch_phase = T510FEngine._configured_phase_deg_for_channel(
                int(idx),
                configured_phase_deg=display_phase_base,
                phase_deg_per_channel=float(phase_deg_per_channel),
                phase_deg_by_channel=phase_deg_by_channel,
            )

            guard = max(2, nfft // 128)
            noise_mask = passband.copy()
            noise_mask[max(0, peak_idx - guard):min(len(noise_mask), peak_idx + guard + 1)] = False
            noise_floor = float(np.median(power[noise_mask])) if np.any(noise_mask) else 1.0
            peak_power = float(power[peak_idx])
            snr_db = 10.0 * np.log10(max(peak_power, 1.0) / max(noise_floor, 1.0))
            amplitude_code = float(abs(coeff))
            residual_rms_code = float(np.sqrt(np.mean(np.abs(residual) ** 2))) if residual.size else 0.0
            signal_rms_code = float(np.sqrt(np.mean(np.abs(fit) ** 2))) if fit.size else 0.0
            residual_fraction = residual_rms_code / max(signal_rms_code, 1.0)
            rms_code = float(np.sqrt(np.mean(i_data * i_data + q_data * q_data))) if arr.size else 0.0
            max_abs = float(np.max(np.abs(arr))) if arr.size else 0.0
            peak_dbfs = 20.0 * np.log10(max(float(np.abs(fft[peak_idx])) / (window_norm * full_scale), 1e-12))

            channels[int(idx)] = {
                "configured_phase_deg": configured_ch_phase,
                "measured_fft_phase_deg": measured_phase,
                "sample0_correction_deg": float(sample0_correction),
                "sample0_coherent_phase_deg": coherent_phase,
                "display_rf_phase_deg": display_ch_phase,
                "display_phase_source": "configured_rf",
                "raw_baseband_hz": float(raw_peak_hz),
                "raw_baseband_mhz": float(raw_peak_hz / 1_000_000.0),
                "baseband_hz": float(logical_peak_hz),
                "baseband_mhz": float(logical_peak_hz / 1_000_000.0),
                "rf_peak_hz": float(observe_center_value + logical_peak_hz),
                "rf_peak_mhz": float((observe_center_value + logical_peak_hz) / 1_000_000.0),
                "dac_signal_hz": 0.0 if dac_signal_hz is None else float(dac_signal_hz),
                "expected_signal_hz": 0.0 if expected_signal_value is None else float(expected_signal_value),
                "input_signal_hz": 0.0 if expected_signal_value is None else float(expected_signal_value),
                "input_source_mode": input_source_mode,
                "expected_baseband_hz": 0.0 if expected_baseband_hz is None else float(expected_baseband_hz),
                "peak_bin": int(peak_idx),
                "peak_dbfs": float(peak_dbfs),
                "snr_db": float(snr_db),
                "amplitude_code": amplitude_code,
                "rms_code": rms_code,
                "max_abs_code": max_abs,
                "clipped": bool(max_abs >= 32760.0),
                "fit_residual_rms_code": residual_rms_code,
                "fit_residual_fraction": residual_fraction,
                "fit_residual_db": 20.0 * np.log10(max(residual_fraction, 1e-12)),
            }
            if int(idx) == int(phase_ref_input):
                ref_measured = measured_phase
                ref_coherent = coherent_phase

        for item in channels.values():
            if ref_measured is not None:
                item["delta_measured_phase_deg"] = T510FEngine._wrap_phase_deg(
                    float(item["measured_fft_phase_deg"]) - ref_measured
                )
            if ref_coherent is not None:
                item["delta_sample0_coherent_phase_deg"] = T510FEngine._wrap_phase_deg(
                    float(item["sample0_coherent_phase_deg"]) - ref_coherent
                )

        return {
            "input_mask": int(preview["input_mask"]),
            "inputs": list(preview["inputs"]),
            "sample0": sample0,
            "count": count,
            "nfft": int(nfft),
            "sample_rate_hz": sample_rate,
            "axis_beat_rate_hz": float(preview.get("axis_beat_rate_hz", sample_rate)),
            "observe_center_hz": observe_center_value,
            "view_bw_hz": view_bw_value,
            "dac_signal_hz": 0.0 if dac_signal_hz is None else float(dac_signal_hz),
            "expected_signal_hz": 0.0 if expected_signal_value is None else float(expected_signal_value),
            "input_signal_hz": 0.0 if expected_signal_value is None else float(expected_signal_value),
            "input_source_mode": input_source_mode,
            "expected_baseband_hz": 0.0 if expected_baseband_hz is None else float(expected_baseband_hz),
            "configured_phase_deg": float(configured_phase_deg),
            "phase_deg_by_channel": T510FEngine._normalize_phase_deg_by_channel(
                phase_deg_by_channel,
                phase_offset_deg=float(configured_phase_deg),
                phase_deg_per_channel=float(phase_deg_per_channel),
                count=8,
            ),
            "display_rf_phase_deg": display_phase_base,
            "phase_ref_input": int(phase_ref_input),
            "phase_lock": "configured_rf",
            "phase_note": "display_rf_phase_deg is configuration-locked; measured_fft_phase_deg is raw ADC-derived",
            "channels": channels,
        }

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
        start_cycles = math.fmod(float(sample0) * center_hz / sample_rate_hz, 1.0)
        cycles = start_cycles + (center_hz / sample_rate_hz) * np.arange(count, dtype=np.float64)
        phase = 2.0 * np.pi * np.mod(cycles, 1.0)
        return i_arr[:count] * np.cos(phase) - q_arr[:count] * np.sin(phase)

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
        sample_rate_hz: float = 245_760_000.0,
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
        display_count = max(4, min(count, int(math.ceil(float(time_window_us) * 1e-6 * sample_rate))))
        time_us = np.arange(display_count, dtype=np.float64) / sample_rate * 1_000_000.0

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
                "waveform_i": raw_waveform,
                "waveform_q": raw_q_waveform,
                "waveform_mag": raw_magnitude_waveform,
                "rf_equivalent_waveform": rf_equivalent_waveform,
                "rf_equivalent_time_us": time_us,
                "rf_equivalent_center_hz": observe_center_hz,
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
                "rms": rms_code,
                "rms_dbfs": rms_dbfs,
                "max_abs_code": max_abs,
                "clipped": bool(max_abs >= 32760.0),
            }
            baseband_scope[idx] = {
                "time_us": time_us,
                "waveform": raw_waveform,
                "raw_waveform": raw_waveform,
                "raw_q_waveform": raw_q_waveform,
                "raw_magnitude_waveform": raw_magnitude_waveform,
                "rf_equivalent_waveform": rf_equivalent_waveform,
                "rf_equivalent_time_us": time_us,
                "rf_equivalent_center_hz": observe_center_hz,
                "derived_from_real_iq": True,
                "raw_rf": False,
                "waveform_source": "rfdc_preview_buffer",
                "virtual_waveform": False,
                "preview_mode": int(preview.get("preview_mode", 0)),
                "sample0": sample0,
                "sample_rate_hz": sample_rate,
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
                "dac_signal_hz": 0.0 if dac_signal_value is None else dac_signal_value,
                "expected_rf_hz": 0.0 if expected_signal_value is None else expected_signal_value,
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

        return {
            "sample0": sample0,
            "count": count,
            "display_count": display_count,
            "nfft": nfft,
            "input_mask": int(preview["input_mask"]),
            "inputs": list(preview["inputs"]),
            "sample_rate_hz": sample_rate,
            "axis_beat_rate_hz": float(preview.get("axis_beat_rate_hz", sample_rate)),
            "observe_center_hz": observe_center_hz,
            "view_bw_hz": view_bw_hz,
            "dac_signal_hz": 0.0 if dac_signal_value is None else dac_signal_value,
            "expected_signal_hz": 0.0 if expected_signal_value is None else expected_signal_value,
            "input_signal_hz": 0.0 if expected_signal_value is None else expected_signal_value,
            "input_source_mode": input_source_mode,
            "expected_baseband_hz": 0.0 if expected_offset_hz is None else expected_offset_hz,
            "time_window_us": float(time_window_us),
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
