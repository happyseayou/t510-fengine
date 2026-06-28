#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import signal
import shutil
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _add_repo_python_path() -> None:
    sys.path.insert(0, str(_repo_root()))


def _parse_pcap(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    from python.packet import EthernetIPv4UDPFrame

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
    ignored_errors: list[str] = []
    while offset + 16 <= len(data):
        ts_sec, ts_frac, incl_len, orig_len = struct.unpack_from(endian + "IIII", data, offset)
        offset += 16
        frame_bytes = data[offset : offset + incl_len]
        offset += incl_len
        try:
            frame = EthernetIPv4UDPFrame.from_bytes(frame_bytes)
        except Exception as exc:
            ignored_errors.append(f"{type(exc).__name__}: {exc}")
            continue
        packet = frame.to_dict()
        packet.update({"ts_sec": ts_sec, "ts_frac": ts_frac, "incl_len": incl_len, "orig_len": orig_len})
        packets.append(packet)
    return packets, ignored_errors


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
        "port",
        "4300",
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
    stderr = stderr or ""
    drops = None
    match = re.search(r"(\d+)\s+packets dropped by kernel", stderr)
    if match:
        drops = int(match.group(1))
    return {
        "command": cmd,
        "returncode": proc.returncode,
        "timed_out": timed_out,
        "stdout": (stdout or "")[-1000:],
        "stderr": stderr[-4000:],
        "kernel_drops": drops,
    }


def _is_step(prev: int, now: int, step: int, bits: int) -> bool:
    return ((int(prev) + int(step)) % (1 << bits)) == int(now)


def main() -> int:
    _add_repo_python_path()
    from python.packet import STREAM_TIME

    default_pcap = _repo_root() / "reports" / "board" / "stage25_time_low_rate_live.pcap"
    default_json = _repo_root() / "reports" / "board" / "stage25_time_low_rate_live_pcap.json"
    parser = argparse.ArgumentParser(description="Stage 25 host pcap validator for low-rate TIME live CMAC packets.")
    parser.add_argument("--interface", default="ens2f0np0")
    parser.add_argument("--seconds", type=float, default=5.0)
    parser.add_argument("--pcap-file")
    parser.add_argument("--capture-output", default=str(default_pcap))
    parser.add_argument("--sudo", action="store_true", help="Run tcpdump through sudo -n when not root.")
    parser.add_argument("--dst-mac", default="08:c0:eb:d5:95:b2")
    parser.add_argument("--src-mac", default="02:00:00:00:00:01")
    parser.add_argument("--dst-ip", default="10.0.1.16")
    parser.add_argument("--src-ip", default="10.0.1.1")
    parser.add_argument("--dst-port", type=int, default=4300)
    parser.add_argument("--src-port", type=int, default=4000)
    parser.add_argument("--expected-payload-bytes", type=int, default=8192)
    parser.add_argument("--expected-payload-len", type=int, default=8320)
    parser.add_argument("--expected-sample-step", type=int, default=245760)
    parser.add_argument("--min-packets", type=int, default=10)
    parser.add_argument("--output", default=str(default_json))
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
            fd, name = tempfile.mkstemp(prefix="stage25_time_", suffix=".pcap")
            os.close(fd)
            temp_path = Path(name)
            pcap_path = temp_path
        capture_info = _run_tcpdump(args.interface, args.seconds, pcap_path, args.sudo)

    parse_error = None
    ignored_parse_errors: list[str] = []
    try:
        packets, ignored_parse_errors = _parse_pcap(pcap_path) if pcap_path.exists() else ([], [])
    except Exception as exc:
        packets = []
        parse_error = f"{type(exc).__name__}: {exc}"

    expected_dst_mac = args.dst_mac.lower()
    expected_src_mac = args.src_mac.lower()
    matching = []
    for packet in packets:
        header = packet.get("t510_header")
        if not isinstance(header, dict):
            continue
        if packet.get("dst_mac_str") != expected_dst_mac:
            continue
        if packet.get("src_mac_str") != expected_src_mac:
            continue
        if packet.get("dst_ip_str") != args.dst_ip or packet.get("src_ip_str") != args.src_ip:
            continue
        if int(packet.get("dst_port", -1)) != int(args.dst_port):
            continue
        if int(packet.get("src_port", -1)) != int(args.src_port):
            continue
        if int(header.get("stream_type", -1)) != STREAM_TIME:
            continue
        matching.append(packet)

    seq_values = [int(packet["t510_header"]["seq_no"]) for packet in matching]
    frame_values = [int(packet["t510_header"]["frame_id"]) for packet in matching]
    sample_values = [int(packet["t510_header"]["sample0"]) for packet in matching]
    seq_discontinuities = [
        (prev, now)
        for prev, now in zip(seq_values, seq_values[1:])
        if not _is_step(prev, now, 1, 32)
    ]
    frame_discontinuities = [
        (prev, now)
        for prev, now in zip(frame_values, frame_values[1:])
        if not _is_step(prev, now, 1, 64)
    ]
    sample_discontinuities = [
        (prev, now)
        for prev, now in zip(sample_values, sample_values[1:])
        if int(now) - int(prev) != int(args.expected_sample_step)
    ]
    bad_payload = [
        packet
        for packet in matching
        if int(packet.get("payload_len", -1)) != int(args.expected_payload_len)
        or int(packet.get("udp_length", -1)) != int(args.expected_payload_len) + 8
        or int(packet["t510_header"].get("payload_bytes", -1)) != int(args.expected_payload_bytes)
    ]

    errors: list[str] = []
    if parse_error is not None:
        errors.append("PCAP_PARSE_ERROR")
    if capture_info is not None and capture_info.get("returncode") not in (0, None):
        errors.append("TCPDUMP_RETURNED_ERROR")
    if capture_info is not None and int(capture_info.get("kernel_drops") or 0) != 0:
        errors.append("KERNEL_PACKET_DROPS")
    if len(matching) < int(args.min_packets):
        errors.append("NOT_ENOUGH_STAGE25_TIME_PACKETS")
    if seq_discontinuities:
        errors.append("SEQ_NO_DISCONTINUITY")
    if frame_discontinuities:
        errors.append("FRAME_ID_DISCONTINUITY")
    if sample_discontinuities:
        errors.append("SAMPLE0_STEP_DISCONTINUITY")
    if bad_payload:
        errors.append("BAD_TIME_PAYLOAD_SHAPE")

    result = {
        "result": "PASS" if not errors else "FAIL",
        "classification": "HOST_PCAP_STAGE25_TIME_PASS" if not errors else "HOST_PCAP_STAGE25_TIME_FAIL",
        "pcap_file": str(pcap_path),
        "capture": capture_info,
        "parse_error": parse_error,
        "ignored_parse_error_count": len(ignored_parse_errors),
        "packet_count": len(packets),
        "matching_count": len(matching),
        "first_matching": matching[0] if matching else None,
        "last_matching": matching[-1] if matching else None,
        "seq_discontinuities": seq_discontinuities[:16],
        "frame_discontinuities": frame_discontinuities[:16],
        "sample0_discontinuities": sample_discontinuities[:16],
        "bad_payload_count": len(bad_payload),
        "expected": {
            "dst_mac": expected_dst_mac,
            "src_mac": expected_src_mac,
            "dst_ip": args.dst_ip,
            "src_ip": args.src_ip,
            "dst_port": int(args.dst_port),
            "src_port": int(args.src_port),
            "stream_type": "TIME",
            "payload_bytes": int(args.expected_payload_bytes),
            "payload_len": int(args.expected_payload_len),
            "sample0_step": int(args.expected_sample_step),
            "min_packets": int(args.min_packets),
        },
        "errors": errors,
    }
    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    if temp_path is not None and not args.output and not errors:
        temp_path.unlink(missing_ok=True)
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
