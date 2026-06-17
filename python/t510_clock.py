from __future__ import annotations

import array
import ctypes
import fcntl
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


LMK04828_INIT_245P76 = (
    0x000090, 0x000010, 0x000200, 0x000306, 0x0004D0, 0x00055B, 0x000600, 0x000C51,
    0x000D04, 0x01000C, 0x010155, 0x010255, 0x010300, 0x010422, 0x010500, 0x0106F0,
    0x010755, 0x01080C, 0x010955, 0x010A55, 0x010B00, 0x010C22, 0x010D00, 0x010EF0,
    0x010F15, 0x01100C, 0x011155, 0x011255, 0x011300, 0x011402, 0x011500, 0x0116F0,
    0x011755, 0x01180C, 0x011955, 0x011A55, 0x011B00, 0x011C02, 0x011D00, 0x011EF0,
    0x011F15, 0x01200C, 0x012155, 0x012255, 0x012300, 0x012422, 0x012500, 0x0126F0,
    0x012705, 0x01280C, 0x012955, 0x012A55, 0x012B00, 0x012C02, 0x012D00, 0x012EF0,
    0x012F55, 0x01300C, 0x013155, 0x013255, 0x013300, 0x013402, 0x013500, 0x0136F0,
    0x013755, 0x013825, 0x013902, 0x013A0C, 0x013B00, 0x013C00, 0x013D08, 0x013E03,
    0x013F00, 0x014000, 0x014100, 0x014200, 0x014351, 0x0144FF, 0x01457F, 0x014638,
    0x01470A, 0x014833, 0x014940, 0x014A0B, 0x014B16, 0x014C00, 0x014D00, 0x014EC0,
    0x014F7F, 0x015003, 0x015102, 0x015200, 0x015300, 0x01547D, 0x015503, 0x015600,
    0x015700, 0x01587D, 0x015906, 0x015A00, 0x015BD4, 0x015C20, 0x015D00, 0x015E00,
    0x015F13, 0x016000, 0x016101, 0x016244, 0x016300, 0x016400, 0x01650C, 0x0171AA,
    0x017202, 0x017C15, 0x017D33, 0x016600, 0x016700, 0x01680C, 0x016959, 0x016A20,
    0x016B00, 0x016C00, 0x016D00, 0x016E3B, 0x017300, 0x018200, 0x018300, 0x018400,
    0x018500, 0x018800, 0x018900, 0x018A00, 0x018B00, 0x1FFD00, 0x1FFE00, 0x1FFF53,
)

LMK_SYSREF_REQ_MODE = (
    0x0143D1,
    0x014400,
    0x0143F1,
    0x0143D1,
    0x0144FF,
    0x014351,
    0x014350,
    0x013902,
    0x016A60,
)


class T510ClockController:
    """Linux-side T510 LMK04828 control for the lab TCXO path."""

    LMK_SPI_BUS_DEV = "spi1.0"
    LMK_SPI_DEVNODE = "/dev/spidev1.0"
    LMK_RESET = 29
    LMK_REF_SELECT0 = 33
    LMK_REF_SELECT1 = 34
    LMK_SYNC = 78
    PROFILE_ID = "tcxo_10mhz_245p76_sysref_req"
    KEY_REGISTERS = (
        0x000, 0x004, 0x005, 0x006, 0x00C, 0x00D,
        0x100, 0x101, 0x102, 0x103, 0x104, 0x105, 0x106, 0x107,
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

    def set_sysref(self, enable: bool) -> dict[str, int | bool | str]:
        """Drive the LMK SYSREF request GPIO used by the RFDC MTS flow."""
        value = 1 if enable else 0
        self._gpio(self.LMK_SYNC, value)
        return {
            "gpio": self.LMK_SYNC,
            "enabled": bool(enable),
            "value": value,
        }

    def pulse_sysref(self, *, width_s: float = 0.05, settle_s: float = 0.05) -> dict[str, object]:
        """Issue one software-controlled SYSREF pulse through the LMK sync GPIO."""
        before = self.read_gpio_status()
        on = self.set_sysref(True)
        time.sleep(max(float(width_s), 0.0))
        off = self.set_sysref(False)
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
            "profile_id": self.PROFILE_ID,
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
        except Exception as exc:
            status["errors"].append(f"gpio_status: {exc}")  # type: ignore[index]
        try:
            registers = self.read_registers(self.KEY_REGISTERS if include_registers else (0x006, 0x182, 0x183))
            status["registers"] = registers
            pll1 = (int(registers.get("0x182", 0)) >> 1) & 0x1
            pll2 = (int(registers.get("0x183", 0)) >> 1) & 0x1
            status["pll1_lock"] = pll1
            status["pll2_lock"] = pll2
            status["reg6"] = int(registers.get("0x006", 0))
            status["configured"] = bool(pll1 and pll2)
        except Exception as exc:
            status["errors"].append(f"lmk_register_read: {exc}")  # type: ignore[index]
        return status

    def configure_tcxo_245p76(
        self,
        *,
        poll_lock: bool = True,
        max_attempts: int = 24,
        register_delay_s: float = 0.005,
    ) -> dict[str, int | bool | str]:
        self._bind_spidev()

        # T510 clock schematic: SEL0/SEL1 = 0/0 selects CLKin0, the onboard
        # 10 MHz oscillator used for no-external-reference lab bring-up.
        self._gpio(self.LMK_REF_SELECT0, 0)
        self._gpio(self.LMK_REF_SELECT1, 0)
        self._gpio(self.LMK_SYNC, 0)
        self._gpio(self.LMK_RESET, 1)
        time.sleep(0.05)
        self._gpio(self.LMK_RESET, 0)
        time.sleep(0.05)

        result: dict[str, int | bool | str] = {
            "ref": "tcxo_10mhz",
            "lmk_clkin": "CLKin0",
            "profile_id": self.PROFILE_ID,
            "spi": self.LMK_SPI_DEVNODE,
            "configured": False,
            "pll1_lock": 0,
            "pll2_lock": 0,
            "reg6": 0,
            "attempts": 0,
        }
        with LinuxSpiDev(self.LMK_SPI_DEVNODE, speed_hz=self.spi_speed_hz) as spi:
            for value in LMK04828_INIT_245P76:
                self._write24(spi, value)
                if register_delay_s:
                    time.sleep(register_delay_s)
            for value in LMK_SYSREF_REQ_MODE:
                time.sleep(0.01)
                self._write24(spi, value)

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
        return result
