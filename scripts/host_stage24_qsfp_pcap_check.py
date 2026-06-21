#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ipaddress
import json
import os
import signal
import shutil
import struct
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any


EXPECTED_CORE_VERSION = 0x0001_001A


def _mac_text(raw: bytes) -> str:
    return ":".join(f"{byte:02x}" for byte in raw)


def _ip_text(raw: bytes) -> str:
    return str(ipaddress.IPv4Address(raw))


def _parse_pcap(path: Path) -> list[dict[str, Any]]:
    data = path.read_bytes()
    if len(data) < 24:
        raise ValueError("pcap file is too short")
    magic = data[:4]
    if magic in (b"\xd4\xc3\xb2\xa1", b"\x4d\x3c\xb2\xa1"):
        endian = "<"
    elif magic in (b"\xa1\xb2\xc3\xd4", b"\xa1\xb2\x3c\x4d"):
        endian = ">"
    else:
        raise ValueError(f"unsupported pcap magic {magic.hex()}")

    offset = 24
    packets: list[dict[str, Any]] = []
    while offset + 16 <= len(data):
        ts_sec, ts_frac, incl_len, orig_len = struct.unpack_from(endian + "IIII", data, offset)
        offset += 16
        frame = data[offset : offset + incl_len]
        offset += incl_len
        parsed = _parse_ethernet_frame(frame)
        if parsed is not None:
            parsed.update({"ts_sec": ts_sec, "ts_frac": ts_frac, "incl_len": incl_len, "orig_len": orig_len})
            packets.append(parsed)
    return packets


def _parse_ethernet_frame(frame: bytes) -> dict[str, Any] | None:
    if len(frame) < 42:
        return None
    dst_mac = _mac_text(frame[0:6])
    src_mac = _mac_text(frame[6:12])
    eth_type = int.from_bytes(frame[12:14], "big")
    if eth_type != 0x0800:
        return None
    ip = frame[14:]
    version = ip[0] >> 4
    ihl = (ip[0] & 0x0F) * 4
    if version != 4 or len(ip) < ihl + 8 or ip[9] != 17:
        return None
    total_len = int.from_bytes(ip[2:4], "big")
    src_ip = _ip_text(ip[12:16])
    dst_ip = _ip_text(ip[16:20])
    udp = ip[ihl:]
    src_port = int.from_bytes(udp[0:2], "big")
    dst_port = int.from_bytes(udp[2:4], "big")
    udp_len = int.from_bytes(udp[4:6], "big")
    payload = udp[8:udp_len]
    packet: dict[str, Any] = {
        "dst_mac": dst_mac,
        "src_mac": src_mac,
        "src_ip": src_ip,
        "dst_ip": dst_ip,
        "src_port": src_port,
        "dst_port": dst_port,
        "ipv4_total_len": total_len,
        "udp_len": udp_len,
        "payload_len": len(payload),
        "payload_magic": payload[:4].decode("ascii", errors="replace") if len(payload) >= 4 else "",
    }
    if len(payload) >= 22 and payload[:4] == b"T510":
        packet.update(
            {
                "core_version": int.from_bytes(payload[4:8], "big"),
                "seq_no": int.from_bytes(payload[8:12], "big"),
                "sample_count_low32": int.from_bytes(payload[12:16], "big"),
                "status_flags": int.from_bytes(payload[16:20], "big"),
                "board_id": int.from_bytes(payload[20:22], "big"),
            }
        )
    return packet


def _run_tcpdump(interface: str, seconds: float, output: Path, use_sudo: bool) -> dict[str, Any]:
    cmd = [
        "tcpdump",
        "-Z",
        "root",
        "-i",
        interface,
        "-nn",
        "-s",
        "0",
        "-w",
        str(output),
        "udp",
        "and",
        "portrange",
        "4100-4300",
    ]
    if use_sudo and os.geteuid() != 0:
        if shutil.which("aa-exec") is not None:
            cmd = ["sudo", "-n", "aa-exec", "-p", "unconfined", "--"] + cmd
        else:
            cmd = ["sudo", "-n"] + cmd
    proc = subprocess.Popen(
        cmd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )

    def signal_group(sig: signal.Signals) -> None:
        pgid = os.getpgid(proc.pid)
        try:
            os.killpg(pgid, sig)
            return
        except PermissionError:
            pass
        kill_cmd = ["/bin/kill", f"-{sig.name.removeprefix('SIG')}", f"-{pgid}"]
        if shutil.which("aa-exec") is not None:
            kill_cmd = ["aa-exec", "-p", "unconfined", "--"] + kill_cmd
        if use_sudo and os.geteuid() != 0:
            kill_cmd = ["sudo", "-n"] + kill_cmd
        subprocess.run(kill_cmd, check=False)

    time.sleep(max(float(seconds), 0.0))
    timed_out = False
    try:
        signal_group(signal.SIGINT)
        stdout, stderr = proc.communicate(timeout=2.0)
    except subprocess.TimeoutExpired:
        timed_out = True
        proc.terminate()
        try:
            stdout, stderr = proc.communicate(timeout=1.0)
        except subprocess.TimeoutExpired:
            signal_group(signal.SIGKILL)
            stdout, stderr = proc.communicate(timeout=1.0)
    return {
        "command": cmd,
        "returncode": proc.returncode,
        "timed_out": timed_out,
        "stdout": (stdout or "")[-1000:],
        "stderr": (stderr or "")[-4000:],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Stage 24 host-side pcap validator for FPGA CMAC heartbeat.")
    parser.add_argument("--interface", default="ens2f0np0")
    parser.add_argument("--seconds", type=float, default=5.0)
    parser.add_argument("--pcap-file")
    parser.add_argument("--capture-output", help="Where to save a new live capture pcap.")
    parser.add_argument("--sudo", action="store_true", help="Run tcpdump through sudo -n when not root.")
    parser.add_argument("--dst-mac", default="08:c0:eb:d5:95:b2")
    parser.add_argument("--dst-ip", default="10.0.1.16")
    parser.add_argument("--dst-port", type=int, default=4300)
    parser.add_argument("--expected-core-version", type=lambda value: int(value, 0), default=EXPECTED_CORE_VERSION)
    parser.add_argument("--output")
    args = parser.parse_args()

    capture_info = None
    temp_path = None
    if args.pcap_file:
        pcap_path = Path(args.pcap_file)
    else:
        if args.capture_output:
            pcap_path = Path(args.capture_output)
            pcap_path.parent.mkdir(parents=True, exist_ok=True)
        else:
            fd, name = tempfile.mkstemp(prefix="stage24_qsfp_", suffix=".pcap")
            os.close(fd)
            temp_path = Path(name)
            pcap_path = temp_path
        capture_info = _run_tcpdump(args.interface, args.seconds, pcap_path, args.sudo)

    parse_error = None
    try:
        packets = _parse_pcap(pcap_path) if pcap_path.exists() else []
    except Exception as exc:
        packets = []
        parse_error = f"{type(exc).__name__}: {exc}"
    matching = [
        packet
        for packet in packets
        if packet.get("dst_mac") == args.dst_mac.lower()
        and packet.get("dst_ip") == args.dst_ip
        and int(packet.get("dst_port", -1)) == int(args.dst_port)
        and packet.get("payload_magic") == "T510"
    ]
    errors: list[str] = []
    if parse_error is not None:
        errors.append("PCAP_PARSE_ERROR")
    if not matching:
        errors.append("NO_STAGE24_T510_HEARTBEAT_PACKET")
    seq_values = [int(packet["seq_no"]) for packet in matching if "seq_no" in packet]
    if seq_values:
        discontinuities = [
            (prev, now)
            for prev, now in zip(seq_values, seq_values[1:])
            if ((prev + 1) & 0xFFFF_FFFF) != now
        ]
    else:
        discontinuities = []
    if discontinuities:
        errors.append("SEQ_NO_DISCONTINUITY")
    bad_core = [
        packet
        for packet in matching
        if int(packet.get("core_version", -1)) != int(args.expected_core_version)
    ]
    if bad_core:
        errors.append("WRONG_CORE_VERSION_IN_HEARTBEAT")

    result = {
        "result": "PASS" if not errors else "FAIL",
        "classification": "HOST_PCAP_STAGE24_HEARTBEAT_PASS" if not errors else "HOST_PCAP_STAGE24_HEARTBEAT_FAIL",
        "pcap_file": str(pcap_path),
        "capture": capture_info,
        "parse_error": parse_error,
        "packet_count": len(packets),
        "matching_count": len(matching),
        "first_matching": matching[0] if matching else None,
        "last_matching": matching[-1] if matching else None,
        "seq_count": len(seq_values),
        "seq_discontinuities": discontinuities[:16],
        "expected": {
            "dst_mac": args.dst_mac.lower(),
            "dst_ip": args.dst_ip,
            "dst_port": int(args.dst_port),
            "core_version": f"0x{int(args.expected_core_version):08x}",
        },
        "errors": errors,
    }
    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    if temp_path is not None and not args.output:
        # Keep the pcap when failing so the operator can inspect it manually.
        if not errors:
            temp_path.unlink(missing_ok=True)
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
