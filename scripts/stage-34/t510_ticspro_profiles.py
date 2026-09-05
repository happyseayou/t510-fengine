#!/usr/bin/env python3
"""Generate Stage 34c-2R LMK04828 profiles through TICS Pro's TCP API.

The script never patches a .tcs file.  It restores a frozen TICS Pro project,
changes named LMK04828 fields, asks TICS Pro to save a complete setup, then
audits the resulting full register tables and freezes both file and register
SHA256 values in a manifest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import socket
import time
from typing import Any

from t510_pl_sysref_phase_eye import native_phase_states


SOC = "<SOC>"
EOC = "<EOC>"
SOR = "<SOR>"
EOR = "<EOR>"
SEP = chr(25)


class TicsProTcp:
    def __init__(self, host: str, port: int) -> None:
        self.socket = socket.create_connection((host, port), timeout=15.0)
        self.socket.settimeout(30.0)

    def close(self) -> None:
        self.socket.close()

    def call(self, command: str, *arguments: object) -> str:
        request = SOC + SEP.join((command, *(str(value) for value in arguments))) + EOC
        self.socket.sendall(request.encode("utf-8"))
        response = bytearray()
        while EOR.encode("ascii") not in response:
            chunk = self.socket.recv(65536)
            if not chunk:
                raise RuntimeError(f"TICS Pro disconnected during {command}")
            response.extend(chunk)
        text = response.decode("utf-8", errors="replace")
        if not text.startswith(SOR) or not text.endswith(EOR):
            raise RuntimeError(f"malformed TICS Pro response to {command}: {text!r}")
        fields = text[len(SOR) : -len(EOR)].split(SEP)
        if len(fields) < 2 or fields[0].lower() != command.lower() or fields[1] != "True":
            raise RuntimeError(f"TICS Pro rejected {command}{arguments!r}: {text!r}")
        return fields[2] if len(fields) > 2 else ""


def windows_path(path: Path) -> str:
    absolute = path.resolve()
    return "Z:" + str(absolute).replace("/", "\\")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def register_words(path: Path) -> list[int]:
    names: dict[int, str] = {}
    values: dict[int, int] = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        name_match = re.fullmatch(r"NAME(\d+)=(.+)", line.strip())
        if name_match:
            names[int(name_match.group(1))] = name_match.group(2)
            continue
        value_match = re.fullmatch(r"VALUE(\d+)=(\d+)", line.strip())
        if value_match:
            values[int(value_match.group(1))] = int(value_match.group(2))
    indexes = sorted(set(names) & set(values))
    if not indexes or any(not names[index].startswith("R") for index in indexes):
        raise ValueError(f"{path} does not contain a complete TICS Pro register table")
    words = [values[index] for index in indexes]
    for index, word in zip(indexes, words):
        address = (word >> 8) & 0xFFFF
        expected = int(names[index].split()[0][1:])
        if address != expected:
            raise ValueError(f"{path}: NAME{index} address does not match VALUE{index}")
    return words


def register_sha256(words: list[int]) -> str:
    payload = b"".join(int(word).to_bytes(3, "big") for word in words)
    return hashlib.sha256(payload).hexdigest()


def changed_addresses(reference: list[int], candidate: list[int]) -> list[int]:
    if len(reference) != len(candidate):
        raise ValueError("TICS register tables differ in length")
    changed: list[int] = []
    for before, after in zip(reference, candidate):
        if (before >> 8) != (after >> 8):
            raise ValueError("TICS register write order/address changed")
        if before != after:
            changed.append((before >> 8) & 0xFFFF)
    return sorted(set(changed))


def save_setup(client: TicsProTcp, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()
    client.call("savesetup", windows_path(output))
    deadline = time.monotonic() + 10.0
    while (not output.is_file() or output.stat().st_size == 0) and time.monotonic() < deadline:
        time.sleep(0.05)
    if not output.is_file() or output.stat().st_size == 0:
        raise RuntimeError(f"TICS Pro reported success but did not create {output}")


def restore_setup(client: TicsProTcp, source: Path) -> None:
    client.call("restoresetup", windows_path(source))
    time.sleep(0.05)
    if client.call("getdevice") != "LMK04828B":
        raise RuntimeError("TICS Pro did not restore an LMK04828B setup")


def profile_record(profile_id: str, path: Path, **metadata: Any) -> dict[str, Any]:
    words = register_words(path)
    return {
        "profile_id": profile_id,
        "path": str(path.resolve()),
        "file_sha256": sha256_file(path),
        "register_sha256": register_sha256(words),
        "register_words": [f"0x{word:06x}" for word in words],
        **metadata,
    }


def set_phase_controls(client: TicsProTcp, state: dict[str, Any]) -> None:
    client.call("setfieldvalue", "SDCLKout3_DDLY", int(state["ddly_index"]))
    client.call("setfieldvalue", "SDCLKout3_HS", int(state["half_step"]))
    client.call("setfieldvalue", "SDCLKout3_ADLY_EN", int(bool(state["adly_enabled"])))
    if state["adly_enabled"]:
        client.call("setindex", "SDCLKout3_ADLY", int(state["adly_index"]))
    readback = {
        "ddly_index": int(client.call("getfieldvalue", "SDCLKout3_DDLY")),
        "half_step": int(client.call("getfieldvalue", "SDCLKout3_HS")),
        "adly_enabled": bool(int(client.call("getfieldvalue", "SDCLKout3_ADLY_EN"))),
        "adly_index": int(client.call("getindex", "SDCLKout3_ADLY")),
    }
    expected = {
        "ddly_index": int(state["ddly_index"]),
        "half_step": int(state["half_step"]),
        "adly_enabled": bool(state["adly_enabled"]),
        "adly_index": int(state["adly_index"] or 0),
    }
    if readback != expected:
        raise RuntimeError(f"TICS phase control readback mismatch: {readback} != {expected}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=11000)
    args = parser.parse_args()
    repo = args.repo.resolve()
    output = (args.output or repo / "build/board/latest/evidence/clock_sysref_causality/tics_profiles").resolve()
    output.mkdir(parents=True, exist_ok=True)
    source_profiles = {
        "160m_10m_cont_manual_clkin2": repo / "reports/arch/lmk04828_stage32_min_delta_160_10m_cont_manual_clkin2.tcs",
        "160m_10m_request_manual_clkin2": repo / "reports/arch/lmk04828_stage34c2_160_10m_request_manual_clkin2.tcs",
        "160m_10m_request_manual_clkin0": repo / "reports/arch/lmk04828_stage34c2_160_10m_request_manual_clkin0.tcs",
    }
    records: list[dict[str, Any]] = []
    client = TicsProTcp(args.host, args.port)
    try:
        for profile_id, source in source_profiles.items():
            restore_setup(client, source)
            exported = output / "base" / f"{profile_id}.tcs"
            save_setup(client, exported)
            records.append(
                profile_record(
                    profile_id,
                    exported,
                    tics_pro_exported=True,
                    source_path=str(source.resolve()),
                    source_sha256=sha256_file(source),
                    sysref_frequency_hz=10_000_000,
                )
            )

        ten_request = output / "base/160m_10m_request_manual_clkin2.tcs"
        restore_setup(client, ten_request)
        # Change the named divider field inside TICS Pro.  Its derived SYSREF
        # frequency display must update to 5 MHz before the complete export.
        client.call("setfieldvalue", "SYSREF_DIV", 480)
        if int(client.call("getfieldvalue", "SYSREF_DIV")) != 480:
            raise RuntimeError("TICS Pro did not accept SYSREF_DIV=480")
        # This board's Stage 32/34 profile uses nested zero-delay with the
        # SYSREF divider selected as the PLL1 feedback source.  Dividing that
        # feedback from 10 MHz to 5 MHz without changing the active CLKin2 R
        # divider leaves the PLL1 phase detector comparing 10 MHz against
        # 5 MHz and can never lock.  Keep both sides at 5 MHz by changing the
        # named TICS field; do not patch R0x158 by hand.
        client.call("setfieldvalue", "CLKin2_R", 2)
        if int(client.call("getfieldvalue", "CLKin2_R")) != 2:
            raise RuntimeError("TICS Pro did not accept CLKin2_R=2")
        if float(client.call("gettext", "SYSREF_FREQ")) != 5.0:
            raise RuntimeError("TICS Pro did not recalculate SYSREF_FREQ to 5 MHz")
        if float(client.call("gettext", "PLL1_PD_FREQ")) != 5.0:
            raise RuntimeError("TICS Pro did not match the PLL1 phase-detector input to 5 MHz")
        if "Unlocked" in client.call("gettext", "WARNING_TEXT_PLL1"):
            raise RuntimeError("TICS Pro reports the 5 MHz nested-zero-delay PLL1 profile unlocked")
        five_request = output / "base/160m_5m_request_manual_clkin2.tcs"
        save_setup(client, five_request)
        five_record = profile_record(
            "160m_5m_request_manual_clkin2",
            five_request,
            tics_pro_exported=True,
            source_path=str(ten_request),
            source_sha256=sha256_file(ten_request),
            sysref_frequency_hz=5_000_000,
        )
        records.append(five_record)

        ten_words = register_words(ten_request)
        five_words = register_words(five_request)
        five_diff = changed_addresses(ten_words, five_words)
        if five_diff != [0x13A, 0x13B, 0x158]:
            # TICS maps the linked 13-bit SYSREF divider into R314/R315
            # (0x13a/0x13b), and the active CLKin2 R divider into R344
            # (0x158).  The latter is required by the frozen nested-zero-delay
            # feedback topology; any other change would mix variables.
            raise RuntimeError(f"unexpected 10-to-5 MHz register diff: {five_diff}")

        states = native_phase_states()
        for frequency_hz, base in ((10_000_000, ten_request), (5_000_000, five_request)):
            base_words = register_words(base)
            mhz = frequency_hz // 1_000_000
            for state in states:
                restore_setup(client, base)
                set_phase_controls(client, state)
                profile_id = f"160m_{mhz}m_request_clkin2_sdclkout3_phase_{state['phase_index']:02d}"
                exported = output / f"phase_{mhz}mhz" / f"{profile_id}.tcs"
                save_setup(client, exported)
                words = register_words(exported)
                diff = changed_addresses(base_words, words)
                if any(address not in (0x10C, 0x10D) for address in diff):
                    raise RuntimeError(f"{profile_id}: non-local register diff {diff}")
                records.append(
                    profile_record(
                        profile_id,
                        exported,
                        tics_pro_exported=True,
                        sysref_frequency_hz=frequency_hz,
                        phase_ps=state["phase_ps"],
                        nominal_target_ps=state["nominal_target_ps"],
                        phase_controls={
                            key: state[key]
                            for key in (
                                "adly_enabled", "adly_index", "adly_ps", "ddly_index",
                                "ddly_cycles", "half_step", "phase_numerator_ps", "phase_denominator",
                            )
                        },
                        changed_addresses=[f"0x{address:03x}" for address in diff],
                    )
                )
    finally:
        client.close()

    phase_values = [float(state["phase_ps"]) for state in native_phase_states()]
    phase_gaps = [
        (phase_values[(index + 1) % len(phase_values)] - value) % 6250.0
        for index, value in enumerate(phase_values)
    ]
    manifest = {
        "schema_version": 1,
        "stage": "34c-2R",
        "generator": str(Path(__file__).resolve()),
        "tool": "TICS Pro 1.7.9.1 TCP API",
        "device": "LMK04828B",
        "vco_frequency_hz": 2_400_000_000,
        "phase_period_ps": 6250,
        "phase_point_count_per_frequency": len(phase_values),
        "maximum_actual_phase_gap_ps": max(phase_gaps),
        "phase_quantization_policy": "native SDCLKout3 DDLY + HS + ADLY; nearest unique state to each 200 ps target",
        "five_mhz_vs_ten_mhz_changed_addresses": ["0x13a", "0x13b", "0x158"],
        "five_mhz_nested_zero_delay": {
            "sysref_div": 480,
            "clkin2_r": 2,
            "pll1_phase_detector_hz": 5_000_000,
            "feedback_hz": 5_000_000,
        },
        "profiles": records,
    }
    manifest_path = output / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output / "manifest.sha256").write_text(
        f"{sha256_file(manifest_path)}  {manifest_path.name}\n", encoding="ascii"
    )
    print(
        json.dumps(
            {
                "manifest": str(manifest_path),
                "manifest_sha256": sha256_file(manifest_path),
                "profiles": len(records),
                "phase_points_per_frequency": len(phase_values),
                "maximum_actual_phase_gap_ps": max(phase_gaps),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
