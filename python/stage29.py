from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from ipaddress import IPv4Address
import json
import math
from pathlib import Path
import re
import time
import zlib
from typing import Any, Iterable

from .t510_fengine import T510FEngine


EXPECTED_CORE_VERSION = 0x0001_0031
TIME_DST_PORT_BASE = 4300
SPEC_DST_PORT_BASE = 4308
TIME_FLOW_COUNT = 8
SPEC_FLOW_COUNT = 16
PFB_NCHAN = 4096
PFB_TAPS = 4
PFB_BLOCK_COUNT = 16
PFB_CHAN_COUNT = 256
PFB_TIME_COUNT = 1
PAYLOAD_BYTES = 8192
INPUT_MASK = 0x00FF
DAC_AMPLITUDE_FULL_SCALE = 8192
DAC_SAMPLE_RATE_HZ = 245_760_000.0
DEFAULT_RECEIVER_IP = "10.0.1.16"
DEFAULT_RECEIVER_MAC = "08:c0:eb:d5:95:b2"
DEFAULT_SOURCE_IP = "10.0.1.1"
DEFAULT_SOURCE_MAC = "02:00:00:00:00:01"
TIME_SRC_PORT_BASE = 4000
SPEC_SRC_PORT_BASE = 4008
_MAC_RE = re.compile(r"^(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$")


def _normalize_source_ip(value: str) -> str:
    address = IPv4Address(str(value).strip())
    if address.is_unspecified or address.is_multicast or int(address) == 0xFFFF_FFFF:
        raise ValueError("source_ip must be a unicast IPv4 address")
    return str(address)


def _normalize_source_mac(value: str) -> str:
    mac = str(value).strip().lower()
    if not _MAC_RE.fullmatch(mac):
        raise ValueError("source_mac must use six colon-separated hexadecimal octets")
    octets = bytes.fromhex(mac.replace(":", ""))
    if not any(octets) or octets[0] & 0x01:
        raise ValueError("source_mac must be a non-zero unicast MAC address")
    return mac


class Stage29Mode(str, Enum):
    TIME_ONLY = "time_only"
    SPEC_ONLY = "spec_only"
    TIME_SPEC = "time_spec"

    @classmethod
    def parse(cls, value: str | "Stage29Mode") -> "Stage29Mode":
        if isinstance(value, cls):
            return value
        key = str(value).strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {"time": cls.TIME_ONLY, "spec": cls.SPEC_ONLY, "dual": cls.TIME_SPEC}
        if key in aliases:
            return aliases[key]
        try:
            return cls(key)
        except ValueError as exc:
            raise ValueError("mode must be time_only, spec_only, or time_spec") from exc


@dataclass(frozen=True)
class FlowDestination:
    """One production TX endpoint destination and its independent source port."""

    enabled: bool = True
    ip: str = DEFAULT_RECEIVER_IP
    mac: str = DEFAULT_RECEIVER_MAC
    destination_port: int = TIME_DST_PORT_BASE
    source_port: int = TIME_SRC_PORT_BASE

    def __post_init__(self) -> None:
        ip = str(IPv4Address(str(self.ip).strip()))
        mac = str(self.mac).strip().lower()
        port = int(self.destination_port)
        source_port = int(self.source_port)
        if not _MAC_RE.fullmatch(mac):
            raise ValueError("destination MAC must use six colon-separated hexadecimal octets")
        if not 1 <= port <= 0xFFFF:
            raise ValueError("destination_port must be within 1..65535")
        if not 1 <= source_port <= 0xFFFF:
            raise ValueError("source_port must be within 1..65535")
        object.__setattr__(self, "enabled", bool(self.enabled))
        object.__setattr__(self, "ip", ip)
        object.__setattr__(self, "mac", mac)
        object.__setattr__(self, "destination_port", port)
        object.__setattr__(self, "source_port", source_port)


@dataclass(frozen=True)
class DacChannelConfig:
    """Per-lane DAC setting. ``amplitude`` is expressed as percent."""

    enabled: bool = True
    rf_frequency_mhz: float = 60.010
    amplitude: float = 25.0
    phase_deg: float = 0.0

    def __post_init__(self) -> None:
        frequency = float(self.rf_frequency_mhz)
        amplitude = float(self.amplitude)
        phase = float(self.phase_deg)
        if not math.isfinite(frequency) or not 50.0 <= frequency <= 350.0:
            raise ValueError("DAC rf_frequency_mhz must be finite and within 50..350 MHz")
        if not math.isfinite(amplitude) or not 0.0 <= amplitude <= 100.0:
            raise ValueError("DAC amplitude must be finite and within 0..100 percent")
        if not math.isfinite(phase) or not -180.0 <= phase <= 180.0:
            raise ValueError("DAC phase_deg must be finite and within -180..180 degrees")
        object.__setattr__(self, "enabled", bool(self.enabled))
        object.__setattr__(self, "rf_frequency_mhz", frequency)
        object.__setattr__(self, "amplitude", amplitude)
        object.__setattr__(self, "phase_deg", phase)

    @property
    def amplitude_code(self) -> int:
        return int(round(self.amplitude / 100.0 * DAC_AMPLITUDE_FULL_SCALE))


def default_time_destinations() -> tuple[FlowDestination, ...]:
    return tuple(
        FlowDestination(
            destination_port=TIME_DST_PORT_BASE + flow,
            source_port=TIME_SRC_PORT_BASE + flow,
        )
        for flow in range(TIME_FLOW_COUNT)
    )


def default_spec_destinations() -> tuple[FlowDestination, ...]:
    return tuple(
        FlowDestination(
            destination_port=SPEC_DST_PORT_BASE + flow,
            source_port=SPEC_SRC_PORT_BASE + flow,
        )
        for flow in range(SPEC_FLOW_COUNT)
    )


def default_dac_channels() -> tuple[DacChannelConfig, ...]:
    return tuple(DacChannelConfig() for _ in range(8))


@dataclass(frozen=True)
class Stage29Config:
    bandwidth_mhz: int = 100
    mode: Stage29Mode | str = Stage29Mode.TIME_SPEC
    center_mhz: float = 100.0
    board_id: int = 0
    source_ip: str = DEFAULT_SOURCE_IP
    source_mac: str = DEFAULT_SOURCE_MAC
    time_destinations: tuple[FlowDestination, ...] = default_time_destinations()
    spec_destinations: tuple[FlowDestination, ...] = default_spec_destinations()
    dac_channels: tuple[DacChannelConfig, ...] = default_dac_channels()

    def __post_init__(self) -> None:
        bandwidth = int(self.bandwidth_mhz)
        mode = Stage29Mode.parse(self.mode)
        allowed = {
            (100, Stage29Mode.TIME_ONLY),
            (100, Stage29Mode.SPEC_ONLY),
            (100, Stage29Mode.TIME_SPEC),
            (200, Stage29Mode.TIME_ONLY),
            (200, Stage29Mode.SPEC_ONLY),
        }
        if (bandwidth, mode) not in allowed:
            raise ValueError(
                "Stage 29 supports 100MHz TIME_ONLY/SPEC_ONLY/TIME_SPEC and "
                "200MHz TIME_ONLY/SPEC_ONLY"
            )
        center = float(self.center_mhz)
        if not math.isfinite(center) or not 50.0 <= center <= 350.0:
            raise ValueError("center_mhz must be finite and within the 50..350 MHz science band")
        board_id = int(self.board_id)
        if not 0 <= board_id <= 0xFFFF:
            raise ValueError("board_id must be within 0..65535")
        source_ip = _normalize_source_ip(self.source_ip)
        source_mac = _normalize_source_mac(self.source_mac)
        time_destinations = tuple(
            item if isinstance(item, FlowDestination) else FlowDestination(**dict(item))
            for item in self.time_destinations
        )
        spec_destinations = tuple(
            item if isinstance(item, FlowDestination) else FlowDestination(**dict(item))
            for item in self.spec_destinations
        )
        dac_channels = tuple(
            item if isinstance(item, DacChannelConfig) else DacChannelConfig(**dict(item))
            for item in self.dac_channels
        )
        if len(time_destinations) != TIME_FLOW_COUNT:
            raise ValueError("time_destinations must contain exactly 8 entries")
        if len(spec_destinations) != SPEC_FLOW_COUNT:
            raise ValueError("spec_destinations must contain exactly 16 entries")
        if len(dac_channels) != 8:
            raise ValueError("dac_channels must contain exactly 8 entries")
        half_band_mhz = self.sample_rate_hz_for(bandwidth) / 2.0 / 1.0e6
        lower = center - half_band_mhz
        upper = center + half_band_mhz
        for channel, dac in enumerate(dac_channels):
            if not lower <= dac.rf_frequency_mhz <= upper:
                raise ValueError(
                    f"DAC CH{channel} frequency must stay within the {bandwidth}MHz science "
                    f"Nyquist band {lower:.6f}..{upper:.6f} MHz"
                )
        object.__setattr__(self, "bandwidth_mhz", bandwidth)
        object.__setattr__(self, "mode", mode)
        object.__setattr__(self, "center_mhz", center)
        object.__setattr__(self, "board_id", board_id)
        object.__setattr__(self, "source_ip", source_ip)
        object.__setattr__(self, "source_mac", source_mac)
        object.__setattr__(self, "time_destinations", time_destinations)
        object.__setattr__(self, "spec_destinations", spec_destinations)
        object.__setattr__(self, "dac_channels", dac_channels)

    @staticmethod
    def sample_rate_hz_for(bandwidth_mhz: int) -> float:
        return 122_880_000.0 if int(bandwidth_mhz) == 100 else 245_760_000.0

    @property
    def needs_time(self) -> bool:
        return self.mode in (Stage29Mode.TIME_ONLY, Stage29Mode.TIME_SPEC)

    @property
    def needs_spec(self) -> bool:
        return self.mode in (Stage29Mode.SPEC_ONLY, Stage29Mode.TIME_SPEC)

    @property
    def flow_count(self) -> int:
        return (TIME_FLOW_COUNT if self.needs_time else 0) + (SPEC_FLOW_COUNT if self.needs_spec else 0)

    @property
    def sample_rate_hz(self) -> float:
        return self.sample_rate_hz_for(self.bandwidth_mhz)

    @property
    def dac_enable_mask(self) -> int:
        return sum(1 << channel for channel, item in enumerate(self.dac_channels) if item.enabled)

    @property
    def target_mhz_by_channel(self) -> tuple[float, ...]:
        return tuple(item.rf_frequency_mhz for item in self.dac_channels)

    @property
    def phase_deg_by_channel(self) -> tuple[float, ...]:
        return tuple(item.phase_deg for item in self.dac_channels)

    @property
    def expected_packet_rates(self) -> dict[str, float]:
        pps = 480_000.0 if self.bandwidth_mhz == 100 else 960_000.0
        streams = int(self.needs_time) + int(self.needs_spec)
        return {
            "time_pps": pps if self.needs_time else 0.0,
            "spec_pps": pps if self.needs_spec else 0.0,
            "combined_t510_udp_payload_mbps": pps * streams * 8320.0 * 8.0 / 1_000_000.0,
        }

    def nearest_fft_bin(self, channel: int = 0) -> dict[str, float | int]:
        if not 0 <= int(channel) < 8:
            raise ValueError("channel must be within 0..7")
        bin_hz = self.sample_rate_hz / PFB_NCHAN
        requested_hz = self.dac_channels[int(channel)].rf_frequency_mhz * 1_000_000.0
        center_hz = self.center_mhz * 1_000_000.0
        signed_bin = int(round((requested_hz - center_hz) / bin_hz))
        aligned_hz = center_hz + signed_bin * bin_hz
        return {
            "sample_rate_hz": self.sample_rate_hz,
            "bin_width_hz": bin_hz,
            "signed_bin": signed_bin,
            "requested_hz": requested_hz,
            "aligned_hz": aligned_hz,
            "error_hz": requested_hz - aligned_hz,
        }


class Stage29Controller:
    """Narrow production facade used by the Stage 29 notebook and CLI."""

    def __init__(self, bitfile: str | Path, *, core: T510FEngine | None = None) -> None:
        self.bitfile = str(Path(bitfile))
        self.core = core
        self.config: Stage29Config | None = None

    def connect(self, *, download: bool = False) -> dict[str, Any]:
        self.core = T510FEngine(self.bitfile, download=bool(download))
        status = self.core.read_status()
        version = int(status.get("core_version", 0))
        if version != EXPECTED_CORE_VERSION:
            raise RuntimeError(
                f"Stage 29 requires CORE_VERSION=0x{EXPECTED_CORE_VERSION:08x}; got 0x{version:08x}"
            )
        return status

    def require_core(self) -> T510FEngine:
        if self.core is None:
            raise RuntimeError("connect the Stage 29 controller first")
        return self.core

    def _program_destinations(self, config: Stage29Config) -> list[dict[str, Any]]:
        endpoints: list[dict[str, Any]] = []
        for endpoint_id, destination in enumerate(config.time_destinations):
            endpoints.append({
                "id": endpoint_id,
                "enable": bool(config.needs_time and destination.enabled),
                "ip": destination.ip,
                "mac": destination.mac,
                "dst_port": destination.destination_port,
                "src_port": destination.source_port,
            })
        for flow, destination in enumerate(config.spec_destinations):
            endpoints.append({
                "id": 8 + flow,
                "enable": bool(config.needs_spec and destination.enabled),
                "ip": destination.ip,
                "mac": destination.mac,
                "dst_port": destination.destination_port,
                "src_port": destination.source_port,
            })
        core = self.require_core()
        core.configure_tx_endpoints(endpoints)
        readback = core.read_tx_endpoints(range(TIME_FLOW_COUNT + SPEC_FLOW_COUNT))
        mismatches: list[str] = []
        for requested, actual in zip(endpoints, readback):
            different = [
                key for key in ("id", "enable", "ip", "mac", "dst_port", "src_port")
                if requested[key] != actual.get(key)
            ]
            if different:
                mismatches.append(
                    f"EP{requested['id']} fields={','.join(different)} "
                    f"requested={requested} readback={actual}"
                )
        if len(readback) != len(endpoints):
            mismatches.append(f"endpoint count requested={len(endpoints)} readback={len(readback)}")
        if mismatches:
            raise RuntimeError("Stage 29 TX endpoint readback mismatch: " + "; ".join(mismatches))
        return endpoints

    @staticmethod
    def _fallback_source_port(config: Stage29Config) -> int:
        groups = []
        if config.needs_time:
            groups.append(config.time_destinations)
        if config.needs_spec:
            groups.append(config.spec_destinations)
        for group in groups:
            for destination in group:
                if destination.enabled:
                    return destination.source_port
        return groups[0][0].source_port

    @staticmethod
    def _flow_tuple_warnings(config: Stage29Config, endpoints: list[dict[str, Any]]) -> list[str]:
        seen: dict[tuple[str, int, str, int], int] = {}
        warnings: list[str] = []
        for endpoint in endpoints:
            if not endpoint["enable"]:
                continue
            key = (
                config.source_ip,
                int(endpoint["src_port"]),
                str(endpoint["ip"]),
                int(endpoint["dst_port"]),
            )
            previous = seen.get(key)
            if previous is not None:
                warnings.append(
                    f"EP{previous} and EP{endpoint['id']} share UDP tuple "
                    f"{key[0]}:{key[1]} -> {key[2]}:{key[3]}; RSS separation may be reduced"
                )
            else:
                seen[key] = int(endpoint["id"])
        return warnings

    def _write_dac_channels(
        self,
        channels: tuple[DacChannelConfig, ...],
        *,
        center_mhz: float,
    ) -> dict[str, Any]:
        core = self.require_core()
        requested_mask = sum(1 << channel for channel, item in enumerate(channels) if item.enabled)
        started_ns = time.monotonic_ns()
        core.set_dac_enable_mask(0)
        muted_ns = time.monotonic_ns()
        rows: list[dict[str, Any]] = []
        for channel, item in enumerate(channels):
            offset_hz = (item.rf_frequency_mhz - float(center_mhz)) * 1.0e6
            phase_step = core.dac_phase_step_from_frequency(offset_hz, DAC_SAMPLE_RATE_HZ)
            phase0 = core._wrap_phase0_word(item.phase_deg)
            core.set_dac_tone(
                enable=False,
                amplitude=item.amplitude_code,
                phase_step=phase_step,
                channel=channel,
                phase0=phase0,
                phase_inject=0,
                mode="single_tone",
            )
            rows.append({
                "channel": channel,
                "enabled": item.enabled,
                "rf_frequency_mhz": item.rf_frequency_mhz,
                "baseband_offset_hz": offset_hz,
                "phase_step": phase_step,
                "amplitude_percent": item.amplitude,
                "amplitude_code": item.amplitude_code,
                "phase_deg": item.phase_deg,
                "phase0": phase0,
            })
        epoch = core.reset_dac_phase()
        core.set_dac_enable_mask(requested_mask)
        finished_ns = time.monotonic_ns()
        return {
            "channels": rows,
            "enable_mask": requested_mask,
            "dac_phase_epoch": epoch,
            "mute_duration_us": (finished_ns - muted_ns) / 1_000.0,
            "transaction_duration_us": (finished_ns - started_ns) / 1_000.0,
        }

    def read_dac_channels(self, *, center_mhz: float | None = None) -> dict[str, Any]:
        """Return register-derived DAC state without relying on ``self.config``."""
        core = self.require_core()
        if not hasattr(core, "read_dac_channels"):
            if self.config is None:
                raise RuntimeError("DAC readback is unavailable before a configuration is applied")
            return {
                "enable_mask": self.config.dac_enable_mask,
                "dac_phase_epoch": None,
                "channels": [
                    {
                        "channel": channel,
                        "enabled": item.enabled,
                        "rf_frequency_mhz": item.rf_frequency_mhz,
                        "amplitude_percent": item.amplitude,
                        "phase_deg": item.phase_deg,
                    }
                    for channel, item in enumerate(self.config.dac_channels)
                ],
                "source": "cached-config",
            }
        result = dict(core.read_dac_channels(dac_sample_rate_hz=DAC_SAMPLE_RATE_HZ))
        center_mhz = self.config.center_mhz if self.config is not None else center_mhz
        channels = []
        for row in result.get("channels", []):
            item = dict(row)
            item["amplitude_percent"] = float(item.get("amplitude_code", 0)) * 100.0 / DAC_AMPLITUDE_FULL_SCALE
            if center_mhz is not None:
                item["rf_frequency_mhz"] = float(center_mhz) + float(item.get("baseband_frequency_hz", 0.0)) / 1.0e6
            channels.append(item)
        result["channels"] = channels
        result["source"] = "register-readback"
        return result

    def prepare(
        self,
        config: Stage29Config,
        *,
        fresh_download: bool = True,
        program_dac: bool = False,
    ) -> dict[str, Any]:
        """Apply a production configuration while leaving science streaming stopped."""
        config = config if isinstance(config, Stage29Config) else Stage29Config(**dict(config))
        if fresh_download or self.core is None:
            self.connect(download=True)
        core = self.require_core()
        core.stop()
        observation = core.apply_mts_locked_observation_config(
            observe_center_hz=config.center_mhz * 1_000_000.0,
            dac_signal_hz=config.center_mhz * 1_000_000.0,
            expected_signal_hz=config.center_mhz * 1_000_000.0,
            view_bw_hz=config.bandwidth_mhz * 1_000_000.0,
            amplitude=0,
            phase_deg=0.0,
            phase_deg_by_channel=(0.0,) * 8,
            enable_mask=0x00,
            adc_active_mask=T510FEngine.complex_input_mask_to_adc_active_mask(0xFF),
            initialize=True,
            start=False,
            require_full_clock_lock=True,
            require_mts=True,
            force_clock_reconfigure=True,
            input_source_mode="dac_loopback",
            clock_ref=T510FEngine.PRODUCTION_CLOCK_REF,
            sync_mode=T510FEngine.PRODUCTION_SYNC_MODE,
        )
        mts_payload = observation.get("nco", {}).get("mts", {})
        if (
            not isinstance(mts_payload, Mapping)
            or not mts_payload.get("calls")
            or mts_payload.get("available") is False
            or bool(mts_payload.get("failures"))
        ):
            raise RuntimeError(
                "Stage31 requires a successful configure-time MTS result with call evidence"
            )
        mts_result_id = zlib.crc32(
            json.dumps(mts_payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        ) or 1
        if hasattr(core, "persist_stage31_mts_result_id"):
            core.persist_stage31_mts_result_id(mts_result_id)
        observation["stage31_mts_result_id"] = mts_result_id
        science = core.configure_science_29(
            bandwidth_mhz=config.bandwidth_mhz,
            output_mode=config.mode.value,
            dst_ip=DEFAULT_RECEIVER_IP,
            dst_mac=DEFAULT_RECEIVER_MAC,
            src_ip=config.source_ip,
            src_mac=config.source_mac,
            clear_counters=True,
            start=False,
        )
        requested_source = {
            "ip": config.source_ip,
            "mac": config.source_mac,
            "src_port": self._fallback_source_port(config),
        }
        source_readback = core.configure_tx_source_identity(**requested_source)
        if requested_source != source_readback:
            raise RuntimeError(
                "Stage 29 TX source identity readback mismatch: "
                f"requested={requested_source} readback={source_readback}"
            )
        endpoints = self._program_destinations(config)
        endpoint_readback = core.read_tx_endpoints(range(TIME_FLOW_COUNT + SPEC_FLOW_COUNT))
        flow_warnings = self._flow_tuple_warnings(config, endpoints)
        dac = self._write_dac_channels(config.dac_channels, center_mhz=config.center_mhz) if program_dac else None
        if not program_dac:
            core.set_dac_enable_mask(0)
        board_id_readback = core.configure_board_id(config.board_id)
        if board_id_readback != config.board_id:
            raise RuntimeError(
                "Stage 29 board_id readback mismatch: "
                f"requested={config.board_id} readback={board_id_readback}"
            )
        core.stop()
        self.config = config
        return {
            "observation": observation,
            "science": science,
            "board_identity": {"requested": config.board_id, "readback": board_id_readback},
            "source_identity": {"requested": requested_source, "readback": source_readback},
            "endpoints": endpoints,
            "endpoint_readback": endpoint_readback,
            "flow_warnings": flow_warnings,
            "dac": dac,
            "dac_readback": self.read_dac_channels(),
            "started": False,
            "status": core.read_status(),
        }

    def start_immediate(self, *, timeout: float = 2.0) -> dict[str, Any]:
        """Start the current hardware immediately and prove the streaming bit when available."""
        core = self.require_core()
        core.start()
        deadline = time.monotonic() + max(float(timeout), 0.0)
        status = core.read_status()
        if "streaming" not in status:
            return status
        while not bool(status.get("streaming")) and time.monotonic() < deadline:
            time.sleep(0.01)
            status = core.read_status()
        if not bool(status.get("streaming")):
            raise RuntimeError("Stage 29 immediate start did not assert the hardware streaming state")
        return status

    def stop_and_verify(self, *, settle_seconds: float = 0.1, timeout: float = 2.0) -> dict[str, Any]:
        """Stop science streaming and prove that packet counters have become stable."""
        core = self.require_core()
        core.stop()
        deadline = time.monotonic() + max(float(timeout), 0.0)
        previous: dict[str, Any] | None = None
        counter_keys = ("time_packet_count", "spec_packet_count", "tx_frame_sent_count")
        while True:
            status = core.read_status()
            if "streaming" not in status:
                return status
            counters_stable = previous is not None and all(
                int(status.get(key, 0)) == int(previous.get(key, 0)) for key in counter_keys
            )
            if not bool(status.get("streaming")) and counters_stable:
                return status
            if time.monotonic() >= deadline:
                raise RuntimeError(f"Stage 29 stop could not be proven: {status}")
            previous = status
            time.sleep(max(float(settle_seconds), 0.01))

    def discover(self) -> dict[str, Any]:
        """Discover hardware facts after process restart without downloading an overlay."""
        if self.core is None:
            self.connect(download=False)
        core = self.require_core()
        status = core.read_status()
        mixers = (
            core.read_rfdc_mixer_frequencies()
            if hasattr(core, "read_rfdc_mixer_frequencies")
            else {"available": False, "mixers": [], "errors": ["mixer readback unavailable"]}
        )
        dac_centers = [
            float(item["frequency_mhz"])
            for item in mixers.get("mixers", [])
            if item.get("kind") == "dac" and float(item.get("frequency_mhz", 0.0)) > 0.0
        ]
        center_mhz = None
        if dac_centers and max(dac_centers) - min(dac_centers) < 1e-6:
            center_mhz = sum(dac_centers) / len(dac_centers)
        result: dict[str, Any] = {
            "status": status,
            "core_version": int(status.get("core_version", 0)),
            "board_id": int(status.get("board_id", 0)),
            "source_identity": core.read_tx_source_identity() if hasattr(core, "read_tx_source_identity") else None,
            "rfdc_mixers": mixers,
            "center_mhz": center_mhz,
            "dac": self.read_dac_channels(center_mhz=center_mhz),
        }
        if hasattr(core, "read_tx_endpoints"):
            result["endpoints"] = core.read_tx_endpoints(range(TIME_FLOW_COUNT + SPEC_FLOW_COUNT))
        if hasattr(core, "read_science_output_status"):
            result["science"] = core.read_science_output_status()
        if hasattr(core, "read_channelizer_status"):
            result["channelizer"] = core.read_channelizer_status()
        return result

    def apply(self, config: Stage29Config, *, fresh_download: bool = True) -> dict[str, Any]:
        """Compatibility entry point used by the Stage 29 notebook and release gate."""
        result = self.prepare(config, fresh_download=fresh_download, program_dac=True)
        result["status"] = self.start_immediate()
        result["started"] = True
        return result

    def apply_dac_live(
        self,
        dac_channels: Iterable[DacChannelConfig | dict[str, Any]],
        *,
        center_mhz: float | None = None,
    ) -> dict[str, Any]:
        """Atomically update the DAC bank.

        ``center_mhz`` lets the stateless Stage 30 helper perform a live update
        after reconnecting to an already configured overlay. Existing notebook
        callers continue to use the cached Stage 29 configuration.
        """
        if self.config is None and center_mhz is None:
            raise RuntimeError("center_mhz is required when no Stage 29 configuration is cached")
        channels = tuple(
            item if isinstance(item, DacChannelConfig) else DacChannelConfig(**dict(item))
            for item in dac_channels
        )
        if len(channels) != 8:
            raise ValueError("dac_channels must contain exactly 8 entries")
        active_center_mhz = self.config.center_mhz if self.config is not None else float(center_mhz)
        if not math.isfinite(active_center_mhz) or not 50.0 <= active_center_mhz <= 350.0:
            raise ValueError("center_mhz must be finite and within the 50..350 MHz science band")
        if self.config is None:
            result = self._write_dac_channels(channels, center_mhz=active_center_mhz)
            result["readback"] = self.read_dac_channels(center_mhz=active_center_mhz)
            return result
        config = Stage29Config(
            bandwidth_mhz=self.config.bandwidth_mhz,
            mode=self.config.mode,
            center_mhz=active_center_mhz,
            board_id=self.config.board_id,
            source_ip=self.config.source_ip,
            source_mac=self.config.source_mac,
            time_destinations=self.config.time_destinations,
            spec_destinations=self.config.spec_destinations,
            dac_channels=channels,
        )
        result = self._write_dac_channels(config.dac_channels, center_mhz=config.center_mhz)
        result["readback"] = self.read_dac_channels(center_mhz=config.center_mhz)
        self.config = config
        return result

    def stop(self) -> None:
        self.require_core().stop()

    def validate(self, *, seconds: float = 10.0) -> dict[str, Any]:
        if self.config is None:
            raise RuntimeError("apply a Stage 29 production configuration first")
        return self.require_core().run_stage29_validation(
            configure=False,
            bandwidth_mhz=self.config.bandwidth_mhz,
            output_mode=self.config.mode.value,
            seconds=float(seconds),
            start=False,
        )

    def capture_preview(self, *, time_window_us: float = 0.25) -> dict[str, Any]:
        if self.config is None:
            raise RuntimeError("apply a Stage 29 production configuration first")
        core = self.require_core()
        preview = core.capture_preview_fast(n=1024, input_mask=0xFF, timeout=1.0)
        channel0 = self.config.dac_channels[0]
        analysis = core.compute_observation_view(
            preview,
            observe_center_hz=self.config.center_mhz * 1_000_000.0,
            view_bw_hz=self.config.bandwidth_mhz * 1_000_000.0,
            dac_signal_hz=channel0.rf_frequency_mhz * 1_000_000.0,
            expected_signal_hz=channel0.rf_frequency_mhz * 1_000_000.0,
            time_window_us=float(time_window_us),
            curve_points=1024,
            oversample=2.5,
            phase_ref_input=0,
            stabilize_phase=False,
            phase_deg_by_channel=self.config.phase_deg_by_channel,
            input_source_mode="dac_loopback",
        )
        return {"preview": preview, "analysis": analysis}


__all__ = [
    "DAC_SAMPLE_RATE_HZ",
    "DEFAULT_RECEIVER_IP",
    "DEFAULT_RECEIVER_MAC",
    "DEFAULT_SOURCE_IP",
    "DEFAULT_SOURCE_MAC",
    "DacChannelConfig",
    "EXPECTED_CORE_VERSION",
    "FlowDestination",
    "INPUT_MASK",
    "PAYLOAD_BYTES",
    "PFB_BLOCK_COUNT",
    "PFB_CHAN_COUNT",
    "PFB_NCHAN",
    "PFB_TAPS",
    "PFB_TIME_COUNT",
    "SPEC_DST_PORT_BASE",
    "SPEC_FLOW_COUNT",
    "SPEC_SRC_PORT_BASE",
    "Stage29Config",
    "Stage29Controller",
    "Stage29Mode",
    "TIME_DST_PORT_BASE",
    "TIME_FLOW_COUNT",
    "TIME_SRC_PORT_BASE",
    "default_dac_channels",
    "default_spec_destinations",
    "default_time_destinations",
]
