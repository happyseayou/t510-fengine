from __future__ import annotations

import array
import ctypes
import fcntl
import hashlib
import json
import os
from pathlib import Path
import struct
import time
from typing import Iterable


class LinuxSpiDev:
    """Tiny Linux spidev wrapper using ioctl directly.

    The T510 PYNQ image has the kernel spidev driver but does not ship the
    optional Python spidev package. This keeps clock bring-up self-contained.
    """

    SPI_IOC_MAGIC = ord("k")
    SPI_MODE_0 = 0

    @staticmethod
    def _ioc(direction: int, ioctl_type: int, number: int, size: int) -> int:
        return (
            (direction << 30)
            | (size << 16)
            | (ioctl_type << 8)
            | number
        )

    @classmethod
    def _iow(cls, number: int, size: int) -> int:
        return cls._ioc(1, cls.SPI_IOC_MAGIC, number, size)

    @classmethod
    def _spi_ioc_message(cls, nxfers: int) -> int:
        return cls._iow(0, 32 * nxfers)

    def __init__(
        self,
        device: str = "/dev/spidev1.1",
        *,
        speed_hz: int = 1_000_000,
        mode: int = SPI_MODE_0,
        bits_per_word: int = 8,
    ) -> None:
        self.device = device
        self.speed_hz = speed_hz
        self.mode = mode
        self.bits_per_word = bits_per_word
        self._fd: int | None = None

    def __enter__(self) -> "LinuxSpiDev":
        self.open()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def open(self) -> None:
        if self._fd is not None:
            return
        self._fd = os.open(self.device, os.O_RDWR | os.O_CLOEXEC)
        fcntl.ioctl(self._fd, self._iow(1, 1), struct.pack("B", self.mode))
        fcntl.ioctl(self._fd, self._iow(3, 1), struct.pack("B", self.bits_per_word))
        fcntl.ioctl(self._fd, self._iow(4, 4), struct.pack("I", self.speed_hz))

    def close(self) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None

    def xfer(self, data: Iterable[int]) -> list[int]:
        if self._fd is None:
            raise RuntimeError("SPI device is not open")
        tx = array.array("B", [value & 0xFF for value in data])
        rx = array.array("B", [0] * len(tx))
        tx_addr = tx.buffer_info()[0]
        rx_addr = rx.buffer_info()[0]
        transfer = struct.pack(
            "<QQIIHBBBBBB",
            tx_addr,
            rx_addr,
            len(tx),
            self.speed_hz,
            0,
            self.bits_per_word,
            0,
            0,
            0,
            0,
            0,
        )
        fcntl.ioctl(self._fd, self._spi_ioc_message(1), transfer)
        return list(rx)


class SysfsGpio:
    GPIOCHIP_BASE = 334

    def __init__(self, ps_pin: int) -> None:
        self.ps_pin = ps_pin
        self.gpio = self.GPIOCHIP_BASE + ps_pin
        self.path = Path(f"/sys/class/gpio/gpio{self.gpio}")

    def export(self) -> None:
        if not self.path.exists():
            Path("/sys/class/gpio/export").write_text(f"{self.gpio}\n")
            deadline = time.monotonic() + 1.0
            while not self.path.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
        if not self.path.exists():
            raise RuntimeError(f"GPIO {self.gpio} did not appear after export")

    def set_output(self, value: int) -> None:
        self.export()
        (self.path / "direction").write_text("out\n")
        self.write(value)

    def write(self, value: int) -> None:
        self.export()
        (self.path / "value").write_text("1\n" if value else "0\n")

    def read(self) -> int:
        self.export()
        return int((self.path / "value").read_text().strip())

    def direction(self) -> str:
        self.export()
        direction_path = self.path / "direction"
        if not direction_path.exists():
            return "unknown"
        return direction_path.read_text().strip()


# TICS Pro export retained in reports/ as historical evidence.  The register
# sequence below is the sole active 160 MHz / 10 MHz continuous-SYSREF profile.
# SHA256 a9fac413bf18ff7bda1844284f72e59fde3e72dcfceed6144b59dcbda82f216e
#
# This table is intentionally kept in the exact TICS write order.  Do not
# sort/deduplicate it: R0 is written twice and the high-page final writes are
# part of the programming sequence.
LMK04828_INIT_160M_10M_CONTINUOUS = (
    0x000090, 0x000010, 0x000200, 0x000306, 0x0004D0, 0x00055B, 0x000600, 0x000C51,
    0x000D04, 0x01000F, 0x010155, 0x010255, 0x010300, 0x010420, 0x010500, 0x0106F0,
    0x010755, 0x01080F, 0x010955, 0x010A55, 0x010B00, 0x010C20, 0x010D00, 0x010EF0,
    0x010F15, 0x01100F, 0x011155, 0x011255, 0x011300, 0x011420, 0x011500, 0x0116F0,
    0x011755, 0x01180F, 0x011955, 0x011A55, 0x011B00, 0x011C00, 0x011D00, 0x011EF0,
    0x011F15, 0x01200F, 0x012155, 0x012255, 0x012300, 0x012420, 0x012500, 0x0126F0,
    0x012705, 0x01280F, 0x012955, 0x012A55, 0x012B00, 0x012C00, 0x012D00, 0x012EF0,
    0x012F55, 0x013018, 0x013155, 0x013255, 0x013300, 0x013400, 0x013500, 0x0136F0,
    0x013755, 0x013800, 0x013903, 0x013A00, 0x013BF0, 0x013C00, 0x013D08, 0x013E03,
    0x013F0D, 0x014003, 0x014100, 0x014200, 0x014350, 0x0144FF, 0x01457F, 0x014620,
    0x01472F, 0x014803, 0x014943, 0x014A0B, 0x014B16, 0x014C00, 0x014D00, 0x014EC0,
    0x014F7F, 0x015003, 0x015102, 0x015200, 0x015300, 0x01547D, 0x015503, 0x015600,
    0x015700, 0x015801, 0x015900, 0x015A01, 0x015BD4, 0x015C20, 0x015D00, 0x015E00,
    0x015F13, 0x016006, 0x016100, 0x0162A4, 0x016300, 0x016400, 0x016501, 0x0171AA,
    0x017202, 0x017C15, 0x017D33, 0x016600, 0x016717, 0x016870, 0x016959, 0x016A20,
    0x016B00, 0x016C00, 0x016D00, 0x016E3B, 0x017300, 0x018200, 0x018300, 0x018400,
    0x018500, 0x018800, 0x018900, 0x018A00, 0x018B00, 0x1FFD00, 0x1FFE00, 0x1FFF53,
)

def _replace_profile_registers(
    values: tuple[int, ...], replacements: dict[int, int]
) -> tuple[int, ...]:
    """Return a full TICS write table with selected register bytes replaced."""
    missing = set(int(address) for address in replacements)
    result: list[int] = []
    for word in values:
        address = (int(word) >> 8) & 0xFFFF
        if address in replacements:
            word = (address << 8) | (int(replacements[address]) & 0xFF)
            missing.discard(address)
        result.append(int(word))
    if missing:
        raise ValueError(f"LMK profile replacements contain unknown addresses: {sorted(missing)}")
    return tuple(result)


def _profile_sha256(values: tuple[int, ...]) -> str:
    payload = b"".join(int(value).to_bytes(3, "big") for value in values)
    return hashlib.sha256(payload).hexdigest()


# These complete profiles were exported by the official TICS Pro 1.7.9.1
# application from the frozen Stage 32 project.  The request-mode export
# differs only in documented SYSREF/SYNC fields.  The CLKin0 export adds only
# manual CLKin0 selection and its PLL1 R divider (10 MHz / 1).
LMK04828_INIT_160M_10M_REQUEST_CLKIN2 = _replace_profile_registers(
    LMK04828_INIT_160M_10M_CONTINUOUS,
    {
        0x139: 0x02,
        # External request uses the pulser and the SYSREF digital-delay path;
        # both power-down bits must be clear while reset/MTS is performed.
        0x140: 0x00,
        # TI Table 1 external SYSREF request mode keeps SYNC_MODE at 0
        # (SYNC pin disabled) while SYSREF_REQ_EN makes the pin a request input.
        # TICS Pro's SYSREF Request shortcut selects the SPI pulser (0x53), so
        # the exported profile is explicitly returned to the documented mode.
        0x143: 0x50,
        # CLKin0 stays disabled for the external-reference profile. TICS
        # enables it as a side effect of the SYSREF Request shortcut even
        # though this mode uses the separate SYNC/SYSREF_REQ pin.
        0x146: 0x20,
        0x16A: 0x60,
    },
)

LMK04828_INIT_160M_10M_REQUEST_CLKIN0 = _replace_profile_registers(
    LMK04828_INIT_160M_10M_REQUEST_CLKIN2,
    {
        0x146: 0x28,
        0x147: 0x0F,
        0x154: 0x01,
    },
)

LMK04828_PROFILE_SHA256 = {
    "160m_10m_cont_manual_clkin2": _profile_sha256(
        LMK04828_INIT_160M_10M_CONTINUOUS
    ),
    "160m_10m_request_manual_clkin2": _profile_sha256(
        LMK04828_INIT_160M_10M_REQUEST_CLKIN2
    ),
    "160m_10m_request_manual_clkin0": _profile_sha256(
        LMK04828_INIT_160M_10M_REQUEST_CLKIN0
    ),
}

LMK04828_PROFILE_SYSREF_FREQUENCY_HZ = {
    "160m_10m_cont_manual_clkin2": 10_000_000,
    "160m_10m_request_manual_clkin2": 10_000_000,
    "160m_10m_request_manual_clkin0": 10_000_000,
}

# The diagnostic image deliberately starts with the frozen Stage 32 phase.
# A routed-datasheet-backed phase eye is measured with that image; only the
# selected eye centre is allowed to become a non-None production value in the
# second, release-candidate build.
LMK04828_PROFILE_PL_SYSREF_DELAY_PS = {
    profile_id: None for profile_id in LMK04828_PROFILE_SYSREF_FREQUENCY_HZ
}

DIAGNOSTIC_PROFILE_MANIFEST_ENV = "T510_CLOCK_DIAGNOSTIC_PROFILE_MANIFEST"
DIAGNOSTIC_PROFILE_MANIFEST_SHA_ENV = "T510_CLOCK_DIAGNOSTIC_PROFILE_MANIFEST_SHA256"
ACTIVE_PROFILE_STATE_PATH = Path("/run/t510-clock-active-profile.json")


def _load_tics_diagnostic_profiles() -> dict[str, dict[str, object]]:
    """Load only SHA-verified full TICS exports from the diagnostic manifest."""
    manifest_text = os.environ.get(DIAGNOSTIC_PROFILE_MANIFEST_ENV, "").strip()
    if not manifest_text:
        return {}
    path = Path(manifest_text)
    payload = path.read_bytes()
    expected_manifest_sha = os.environ.get(DIAGNOSTIC_PROFILE_MANIFEST_SHA_ENV, "").strip().lower()
    actual_manifest_sha = hashlib.sha256(payload).hexdigest()
    if expected_manifest_sha and actual_manifest_sha != expected_manifest_sha:
        raise RuntimeError("TICS diagnostic profile manifest SHA256 mismatch")
    manifest = json.loads(payload)
    if manifest.get("stage") != "34c-2R" or manifest.get("device") != "LMK04828B":
        raise RuntimeError("unsupported TICS diagnostic profile manifest identity")
    profiles: dict[str, dict[str, object]] = {}
    for row in manifest.get("profiles", []):
        profile_id = str(row.get("profile_id", ""))
        if profile_id == "160m_5m_request_manual_clkin2" or (
            profile_id.startswith("160m_10m_request_clkin2_sdclkout3_phase_")
            or profile_id.startswith("160m_5m_request_clkin2_sdclkout3_phase_")
        ):
            words = tuple(int(value, 0) if isinstance(value, str) else int(value) for value in row["register_words"])
            actual_register_sha = _profile_sha256(words)
            if actual_register_sha != str(row.get("register_sha256", "")).lower():
                raise RuntimeError(f"{profile_id}: TICS register SHA256 mismatch")
            profiles[profile_id] = {
                "register_words": words,
                "register_sha256": actual_register_sha,
                "file_sha256": str(row.get("file_sha256", "")).lower(),
                "sysref_frequency_hz": int(row["sysref_frequency_hz"]),
                "pl_sysref_delay_ps": row.get("phase_ps"),
            }
    return profiles


LMK04828_TICS_DIAGNOSTIC_PROFILES = _load_tics_diagnostic_profiles()


def _profile_metadata(profile_id: str) -> dict[str, object]:
    if profile_id in LMK04828_TICS_DIAGNOSTIC_PROFILES:
        return LMK04828_TICS_DIAGNOSTIC_PROFILES[profile_id]
    return {
        "register_words": {
            "160m_10m_cont_manual_clkin2": LMK04828_INIT_160M_10M_CONTINUOUS,
            "160m_10m_request_manual_clkin2": LMK04828_INIT_160M_10M_REQUEST_CLKIN2,
            "160m_10m_request_manual_clkin0": LMK04828_INIT_160M_10M_REQUEST_CLKIN0,
        }.get(profile_id, ()),
        "register_sha256": LMK04828_PROFILE_SHA256.get(profile_id, ""),
        "sysref_frequency_hz": LMK04828_PROFILE_SYSREF_FREQUENCY_HZ.get(profile_id),
        "pl_sysref_delay_ps": LMK04828_PROFILE_PL_SYSREF_DELAY_PS.get(profile_id),
    }


class T510ClockController:
    """Linux-side T510 LMK04828 control for the lab TCXO path."""

    LMK_SPI_BUS_DEV = "spi1.0"
    LMK_SPI_DEVNODE = "/dev/spidev1.0"
    LMK_RESET = 29
    LMK_REF_SELECT0 = 33
    LMK_REF_SELECT1 = 34
    LMK_SYNC = 78
    PROFILE_ID_160M_10M_CONTINUOUS = "160m_10m_cont_manual_clkin2"
    PROFILE_ID_160M_10M_REQUEST_CLKIN2 = "160m_10m_request_manual_clkin2"
    PROFILE_ID_160M_10M_REQUEST_CLKIN0 = "160m_10m_request_manual_clkin0"
    PROFILE_ID_160M_5M_REQUEST_CLKIN2 = "160m_5m_request_manual_clkin2"
    SYSREF_REQUEST = "request"
    SYSREF_CONTINUOUS = "continuous"
    KEY_REGISTERS = (
        0x000, 0x004, 0x005, 0x006, 0x00C, 0x00D,
        0x100, 0x101, 0x102, 0x103, 0x104, 0x105, 0x106, 0x107,
        0x10C, 0x10D,
        0x118,
        0x138, 0x139, 0x13A, 0x13B, 0x13C, 0x13D, 0x13E, 0x13F,
        0x140, 0x143, 0x144, 0x145, 0x146, 0x147, 0x148, 0x149,
        0x14A, 0x14B, 0x14C, 0x14D, 0x14E, 0x14F, 0x150, 0x151,
        0x152, 0x153, 0x154, 0x155, 0x156, 0x157, 0x158, 0x159,
        0x15A, 0x15B, 0x15C, 0x15D, 0x15E, 0x15F, 0x160, 0x161,
        0x162, 0x163, 0x164, 0x165, 0x166, 0x167, 0x168, 0x169,
        0x16A, 0x16B, 0x16C, 0x16D, 0x16E, 0x171, 0x172, 0x173,
        0x17C, 0x17D, 0x182, 0x183, 0x184, 0x185,
    )

    def __init__(self, *, spi_speed_hz: int = 1_000_000) -> None:
        self.spi_speed_hz = spi_speed_hz

    def _bind_spidev(self) -> None:
        dev = Path("/sys/bus/spi/devices") / self.LMK_SPI_BUS_DEV
        if not dev.exists():
            raise RuntimeError(f"{self.LMK_SPI_BUS_DEV} is not present in /sys/bus/spi/devices")
        devnode = Path(self.LMK_SPI_DEVNODE)
        if devnode.exists():
            return
        override = dev / "driver_override"
        if override.exists():
            override.write_text("spidev\n")
        bind = Path("/sys/bus/spi/drivers/spidev/bind")
        bind.write_text(f"{self.LMK_SPI_BUS_DEV}\n")
        deadline = time.monotonic() + 1.0
        while not devnode.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        if not devnode.exists():
            raise RuntimeError(f"{self.LMK_SPI_DEVNODE} did not appear after spidev bind")

    def _gpio(self, pin: int, value: int) -> None:
        SysfsGpio(pin).set_output(value)

    def _gpio_status(self, pin: int) -> dict[str, int | str]:
        gpio = SysfsGpio(pin)
        return {
            "ps_pin": pin,
            "gpio": gpio.gpio,
            "direction": gpio.direction(),
            "value": gpio.read(),
        }

    def set_sysref(
        self,
        enable: bool,
        *,
        mode: str = SYSREF_REQUEST,
    ) -> dict[str, int | bool | str]:
        """Control request-mode SYSREF without disturbing continuous profiles."""
        if mode == self.SYSREF_CONTINUOUS:
            return {
                "gpio": self.LMK_SYNC,
                "requested_enable": bool(enable),
                "enabled": True,
                "value": 0,
                "mode": self.SYSREF_CONTINUOUS,
                "gpio_changed": False,
                "reason": "LMK profile drives continuous SYSREF; RFDC receiver gating owns capture",
            }
        if mode != self.SYSREF_REQUEST:
            raise ValueError(f"unsupported SYSREF mode: {mode!r}")
        value = 1 if enable else 0
        self._gpio(self.LMK_SYNC, value)
        return {
            "gpio": self.LMK_SYNC,
            "requested_enable": bool(enable),
            "enabled": bool(enable),
            "value": value,
            "mode": self.SYSREF_REQUEST,
            "gpio_changed": True,
        }

    def pulse_sysref(
        self,
        *,
        width_s: float = 0.05,
        settle_s: float = 0.05,
        mode: str = SYSREF_REQUEST,
    ) -> dict[str, object]:
        """Issue one software-controlled SYSREF pulse through the LMK sync GPIO."""
        if mode == self.SYSREF_CONTINUOUS:
            raise RuntimeError("continuous SYSREF profile cannot be pulsed through the LMK SYNC GPIO")
        before = self.read_gpio_status()
        on = self.set_sysref(True, mode=mode)
        time.sleep(max(float(width_s), 0.0))
        off = self.set_sysref(False, mode=mode)
        time.sleep(max(float(settle_s), 0.0))
        after = self.read_gpio_status()
        return {
            "width_s": float(width_s),
            "settle_s": float(settle_s),
            "before": before,
            "on": on,
            "off": off,
            "after": after,
        }

    @staticmethod
    def _write24(spi: LinuxSpiDev, value: int) -> None:
        spi.xfer([(value >> 16) & 0xFF, (value >> 8) & 0xFF, value & 0xFF])

    @staticmethod
    def _read_reg(spi: LinuxSpiDev, reg: int) -> int:
        cmd = 0x8000 | (reg & 0x1FFF)
        return spi.xfer([(cmd >> 8) & 0xFF, cmd & 0xFF, 0x00])[2]

    def read_registers(self, registers: Iterable[int] | None = None) -> dict[str, int]:
        """Read selected LMK04828 registers without changing the active profile."""
        self._bind_spidev()
        regs = self.KEY_REGISTERS if registers is None else tuple(int(reg) for reg in registers)
        with LinuxSpiDev(self.LMK_SPI_DEVNODE, speed_hz=self.spi_speed_hz) as spi:
            return {f"0x{reg:03x}": self._read_reg(spi, reg) for reg in regs}

    def read_lock_status(self) -> dict[str, int]:
        """Read only the two LMK digital-lock-detect registers.

        This intentionally avoids the GPIO and profile-signature work done by
        :meth:`read_status`.  A resident reference watchdog can therefore poll
        the physical PLL lock state with one short SPI session and without
        modifying the active LMK profile.
        """
        registers = self.read_registers((0x182, 0x183))
        return {
            "captured_at_unix_ms": time.time_ns() // 1_000_000,
            "pll1_lock": (int(registers["0x182"]) >> 1) & 0x1,
            "pll2_lock": (int(registers["0x183"]) >> 1) & 0x1,
            "reg_0x182": int(registers["0x182"]),
            "reg_0x183": int(registers["0x183"]),
        }

    def read_gpio_status(self) -> dict[str, dict[str, int | str]]:
        return {
            "reset": self._gpio_status(self.LMK_RESET),
            "ref_select0": self._gpio_status(self.LMK_REF_SELECT0),
            "ref_select1": self._gpio_status(self.LMK_REF_SELECT1),
            "sysref_sync": self._gpio_status(self.LMK_SYNC),
        }

    def read_status(self, *, include_registers: bool = False) -> dict[str, object]:
        """Return LMK lock, profile, GPIO and optional register-dump evidence."""
        status: dict[str, object] = {
            "profile_id": "unknown",
            "sysref_mode": "unknown",
            "lmk_clkin": "CLKin0",
            "spi_bus_device": self.LMK_SPI_BUS_DEV,
            "spi": self.LMK_SPI_DEVNODE,
            "configured": False,
            "pll1_lock": 0,
            "pll2_lock": 0,
            "reg6": 0,
            "gpio": {},
            "registers": {},
            "errors": [],
        }
        try:
            status["gpio"] = self.read_gpio_status()
            gpio = status["gpio"]  # type: ignore[assignment]
            ref0 = int(gpio["ref_select0"]["value"])  # type: ignore[index]
            ref1 = int(gpio["ref_select1"]["value"])  # type: ignore[index]
            status["ref_select0"] = ref0
            status["ref_select1"] = ref1
            status["selector_bits_sel1_sel0"] = f"{ref1}{ref0}"
            status["selected_ref"] = "tcxo_10mhz" if (ref0, ref1) == (0, 0) else "external_10mhz"
            status["lmk_clkin"] = {
                (0, 0): "CLKin0",
                (0, 1): "CLKin1",
                (1, 0): "CLKin2",
                (1, 1): "holdover",
            }.get((ref1, ref0), "unknown")
        except Exception as exc:
            status["errors"].append(f"gpio_status: {exc}")  # type: ignore[index]
        try:
            registers = self.read_registers(
                self.KEY_REGISTERS
                if include_registers
                else (
                    0x006, 0x10C, 0x10D, 0x118, 0x138, 0x139, 0x13A, 0x13B, 0x143, 0x146, 0x147,
                    0x154, 0x16A, 0x182, 0x183,
                )
            )
            status["registers"] = registers
            pll1 = (int(registers.get("0x182", 0)) >> 1) & 0x1
            pll2 = (int(registers.get("0x183", 0)) >> 1) & 0x1
            status["pll1_lock"] = pll1
            status["pll2_lock"] = pll2
            status["reg6"] = int(registers.get("0x006", 0))
            status["configured"] = bool(pll1 and pll2)
            common_profile_signature = (
                int(registers.get("0x118", -1)) == 0x0F
                and int(registers.get("0x138", -1)) == 0x00
            )
            continuous_signature = (
                common_profile_signature
                and int(registers.get("0x139", -1)) == 0x03
                and int(registers.get("0x143", -1)) == 0x50
                and int(registers.get("0x146", -1)) == 0x20
                and int(registers.get("0x16a", -1)) == 0x20
            )
            request_signature = (
                common_profile_signature
                and int(registers.get("0x139", -1)) == 0x02
                and int(registers.get("0x143", -1)) == 0x50
                and int(registers.get("0x146", -1)) == 0x20
                and int(registers.get("0x147", -1)) == 0x2F
                and int(registers.get("0x154", -1)) == 0x7D
                and int(registers.get("0x16a", -1)) == 0x60
            )
            tcxo_signature = (
                common_profile_signature
                and int(registers.get("0x139", -1)) == 0x02
                and int(registers.get("0x143", -1)) == 0x50
                and int(registers.get("0x146", -1)) == 0x28
                and int(registers.get("0x147", -1)) == 0x0F
                and int(registers.get("0x154", -1)) == 0x01
                and int(registers.get("0x16a", -1)) == 0x60
            )
            if continuous_signature:
                status["profile_id"] = self.PROFILE_ID_160M_10M_CONTINUOUS
                status["sysref_mode"] = self.SYSREF_CONTINUOUS
                status["sysref_policy"] = "continuous"
                status["lmk_clkin"] = "CLKin2 (manual)"
                status["selected_ref"] = "external_10mhz"
                status["clock_reference"] = "external_gpsdo"
            elif tcxo_signature:
                status["profile_id"] = self.PROFILE_ID_160M_10M_REQUEST_CLKIN0
                status["sysref_mode"] = self.SYSREF_REQUEST
                status["sysref_policy"] = "mts_only"
                status["lmk_clkin"] = "CLKin0 (manual)"
                status["selected_ref"] = "tcxo_10mhz"
                status["clock_reference"] = "onboard_tcxo"
            elif request_signature:
                status["profile_id"] = self.PROFILE_ID_160M_10M_REQUEST_CLKIN2
                status["sysref_mode"] = self.SYSREF_REQUEST
                status["sysref_policy"] = "mts_only"
                status["lmk_clkin"] = "CLKin2 (manual)"
                status["selected_ref"] = "external_10mhz"
                status["clock_reference"] = "external_gpsdo"
            else:
                status["profile_id"] = "unknown"
                status["sysref_mode"] = "unknown"
                status["sysref_policy"] = "unknown"
                status["clock_reference"] = "unknown"
            profile_id = str(status["profile_id"])
            try:
                active = json.loads(ACTIVE_PROFILE_STATE_PATH.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                active = {}
            active_id = str(active.get("profile_id", ""))
            active_meta = LMK04828_TICS_DIAGNOSTIC_PROFILES.get(active_id)
            if active_meta and request_signature:
                expected_words = tuple(active_meta["register_words"])
                expected_last = {
                    (int(word) >> 8) & 0xFFFF: int(word) & 0xFF for word in expected_words
                }
                identity_addresses = (0x10C, 0x10D, 0x13A, 0x13B)
                if all(
                    int(registers.get(f"0x{address:03x}", -1)) == expected_last.get(address)
                    for address in identity_addresses
                ):
                    profile_id = active_id
                    status["profile_id"] = active_id
            metadata = _profile_metadata(profile_id)
            status["profile_sha256"] = metadata.get("register_sha256")
            status["tics_file_sha256"] = metadata.get("file_sha256")
            status["sysref_frequency_hz"] = metadata.get("sysref_frequency_hz")
            status["pl_sysref_delay_ps"] = metadata.get("pl_sysref_delay_ps")
            request_value = int(
                status.get("gpio", {}).get("sysref_sync", {}).get("value", 0)  # type: ignore[union-attr]
            )
            status["sysref_request_gpio"] = request_value
            status["sysref_output_expected_on"] = bool(
                status.get("sysref_mode") == self.SYSREF_CONTINUOUS
                or (
                    status.get("sysref_mode") == self.SYSREF_REQUEST
                    and request_value
                )
            )
        except Exception as exc:
            status["errors"].append(f"lmk_register_read: {exc}")  # type: ignore[index]
        return status

    def _configure_profile(
        self,
        *,
        ref: str,
        lmk_clkin: str,
        ref_select0: int,
        ref_select1: int,
        profile_id: str,
        init_values: tuple[int, ...],
        sysref_mode: str,
        poll_lock: bool = True,
        max_attempts: int = 24,
        register_delay_s: float = 0.005,
    ) -> dict[str, int | bool | str]:
        self._bind_spidev()

        self._gpio(self.LMK_REF_SELECT0, int(ref_select0) & 0x1)
        self._gpio(self.LMK_REF_SELECT1, int(ref_select1) & 0x1)
        self._gpio(self.LMK_SYNC, 0)
        self._gpio(self.LMK_RESET, 1)
        time.sleep(0.05)
        self._gpio(self.LMK_RESET, 0)
        time.sleep(0.05)

        result: dict[str, int | bool | str] = {
            "ref": ref,
            "lmk_clkin": lmk_clkin,
            "profile_id": profile_id,
            "sysref_mode": sysref_mode,
            "spi": self.LMK_SPI_DEVNODE,
            "ref_select0": int(ref_select0) & 0x1,
            "ref_select1": int(ref_select1) & 0x1,
            "configured": False,
            "pll1_lock": 0,
            "pll2_lock": 0,
            "reg6": 0,
            "attempts": 0,
        }
        with LinuxSpiDev(self.LMK_SPI_DEVNODE, speed_hz=self.spi_speed_hz) as spi:
            for value in init_values:
                self._write24(spi, value)
                if register_delay_s:
                    time.sleep(register_delay_s)
            if sysref_mode not in (self.SYSREF_REQUEST, self.SYSREF_CONTINUOUS):
                raise ValueError(f"unsupported SYSREF mode: {sysref_mode!r}")

            for attempt in range(1, max_attempts + 1):
                result["attempts"] = attempt
                time.sleep(0.5)
                pll1 = (self._read_reg(spi, 0x182) >> 1) & 0x1
                pll2 = (self._read_reg(spi, 0x183) >> 1) & 0x1
                result["pll1_lock"] = pll1
                result["pll2_lock"] = pll2
                result["reg6"] = self._read_reg(spi, 0x006)
                if not poll_lock or (pll1 and pll2):
                    break
        result["configured"] = bool(result["pll1_lock"] and result["pll2_lock"])
        metadata = _profile_metadata(profile_id)
        result["profile_sha256"] = str(metadata.get("register_sha256", ""))
        result["tics_file_sha256"] = str(metadata.get("file_sha256", ""))
        result["sysref_frequency_hz"] = metadata.get("sysref_frequency_hz")
        result["pl_sysref_delay_ps"] = metadata.get("pl_sysref_delay_ps")
        result["clock_reference"] = (
            "onboard_tcxo" if ref == "tcxo_10mhz" else "external_gpsdo"
        )
        result["sysref_policy"] = (
            "continuous" if sysref_mode == self.SYSREF_CONTINUOUS else "mts_only"
        )
        result["sysref_request_gpio"] = 0
        result["sysref_output_expected_on"] = sysref_mode == self.SYSREF_CONTINUOUS
        if result["configured"]:
            temporary = ACTIVE_PROFILE_STATE_PATH.with_suffix(".tmp")
            temporary.write_text(
                json.dumps(
                    {
                        "profile_id": profile_id,
                        "register_sha256": result["profile_sha256"],
                        "configured_at_unix_ms": time.time_ns() // 1_000_000,
                    },
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            temporary.replace(ACTIVE_PROFILE_STATE_PATH)
        return result

    def configure_external_10mhz_160m_continuous(
        self,
        *,
        poll_lock: bool = True,
        max_attempts: int = 24,
        register_delay_s: float = 0.005,
    ) -> dict[str, int | bool | str]:
        """Program the manual-CLKin2, 160 MHz, continuous-SYSREF profile."""
        return self._configure_profile(
            ref="external_10mhz",
            lmk_clkin="CLKin2 (manual)",
            # SEL1:SEL0=10 agrees with the physical CLKin2 path even though
            # this TICS profile selects CLKin2 manually and ignores the pins.
            ref_select0=0,
            ref_select1=1,
            profile_id=self.PROFILE_ID_160M_10M_CONTINUOUS,
            init_values=LMK04828_INIT_160M_10M_CONTINUOUS,
            sysref_mode=self.SYSREF_CONTINUOUS,
            poll_lock=poll_lock,
            max_attempts=max_attempts,
            register_delay_s=register_delay_s,
        )

    def configure_external_10mhz_160m_request(
        self,
        *,
        poll_lock: bool = True,
        max_attempts: int = 24,
        register_delay_s: float = 0.005,
    ) -> dict[str, int | bool | str]:
        """Program the TICS-generated manual-CLKin2 MTS-only profile."""
        return self._configure_profile(
            ref="external_10mhz",
            lmk_clkin="CLKin2 (manual)",
            ref_select0=0,
            ref_select1=1,
            profile_id=self.PROFILE_ID_160M_10M_REQUEST_CLKIN2,
            init_values=LMK04828_INIT_160M_10M_REQUEST_CLKIN2,
            sysref_mode=self.SYSREF_REQUEST,
            poll_lock=poll_lock,
            max_attempts=max_attempts,
            register_delay_s=register_delay_s,
        )

    def configure_tcxo_10mhz_160m_request(
        self,
        *,
        poll_lock: bool = True,
        max_attempts: int = 24,
        register_delay_s: float = 0.005,
    ) -> dict[str, int | bool | str]:
        """Program the TICS-generated manual-CLKin0 MTS-only profile."""
        return self._configure_profile(
            ref="tcxo_10mhz",
            lmk_clkin="CLKin0 (manual)",
            ref_select0=0,
            ref_select1=0,
            profile_id=self.PROFILE_ID_160M_10M_REQUEST_CLKIN0,
            init_values=LMK04828_INIT_160M_10M_REQUEST_CLKIN0,
            sysref_mode=self.SYSREF_REQUEST,
            poll_lock=poll_lock,
            max_attempts=max_attempts,
            register_delay_s=register_delay_s,
        )

    def configure_tics_diagnostic_profile(
        self,
        profile_id: str,
        *,
        poll_lock: bool = True,
        max_attempts: int = 24,
        register_delay_s: float = 0.005,
    ) -> dict[str, int | bool | str]:
        """Program one SHA-verified Stage 34c-2R full TICS register table."""
        metadata = LMK04828_TICS_DIAGNOSTIC_PROFILES.get(profile_id)
        if metadata is None:
            raise ValueError(f"diagnostic TICS profile is unavailable: {profile_id}")
        return self._configure_profile(
            ref="external_10mhz",
            lmk_clkin="CLKin2 (manual)",
            ref_select0=0,
            ref_select1=1,
            profile_id=profile_id,
            init_values=tuple(metadata["register_words"]),
            sysref_mode=self.SYSREF_REQUEST,
            poll_lock=poll_lock,
            max_attempts=max_attempts,
            register_delay_s=register_delay_s,
        )
