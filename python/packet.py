from __future__ import annotations

from dataclasses import dataclass
from ipaddress import IPv4Address
import struct
from typing import Iterable


MAGIC = 0x54353130
HEADER_BYTES = 128
STRUCT_V1 = struct.Struct("<IHHHHHHQQQIIIHHHHIII")
STRUCT_V2 = struct.Struct("<IHHHHHHQQQQIIHHHHIII")

STREAM_SPEC = 0
STREAM_TIME = 1
STREAM_SNAPSHOT = 2
STREAM_MONITOR = 3

QUANT_INT16 = 0
QUANT_INT8 = 1

EPOCH_EXTERNAL_PPS = 0
EPOCH_INTERNAL_ONLY = 1

FLAG_TIME_VALID = 1 << 0
FLAG_INTERNAL_EPOCH = 1 << 1
FLAG_QSFP_LINK_UP = 1 << 2
FLAG_UDP_DRY_RUN = 1 << 3
FLAG_ADC_CLIP = 1 << 4
FLAG_FIFO_OVERFLOW = 1 << 5
ETH_TYPE_IPV4 = 0x0800
IP_PROTO_UDP = 17


@dataclass(slots=True)
class T510PacketHeader:
    magic: int = MAGIC
    version: int = 2
    header_bytes: int = HEADER_BYTES
    board_id: int = 0
    stream_type: int = STREAM_TIME
    epoch_mode: int = EPOCH_INTERNAL_ONLY
    flags: int = FLAG_INTERNAL_EPOCH | FLAG_UDP_DRY_RUN
    unix_sec: int = 0
    pps_count: int = 0
    sample0: int = 0
    frame_id: int = 0
    seq_no: int = 0
    chan0: int = 0
    chan_count: int = 0
    time_count: int = 256
    ninput: int = 8
    payload_format: int = QUANT_INT16
    scale_id: int = 0
    payload_bytes: int = 8192
    header_crc: int = 0

    def to_bytes(self) -> bytes:
        packed = STRUCT_V2.pack(
            self.magic,
            self.version,
            self.header_bytes,
            self.board_id,
            self.stream_type,
            self.epoch_mode,
            self.flags,
            self.unix_sec,
            self.pps_count,
            self.sample0,
            self.frame_id,
            self.seq_no,
            self.chan0,
            self.chan_count,
            self.time_count,
            self.ninput,
            self.payload_format,
            self.scale_id,
            self.payload_bytes,
            self.header_crc,
        )
        return packed.ljust(self.header_bytes, b"\x00")

    def to_dict(self) -> dict[str, int]:
        return {
            "magic": self.magic,
            "version": self.version,
            "header_bytes": self.header_bytes,
            "board_id": self.board_id,
            "stream_type": self.stream_type,
            "epoch_mode": self.epoch_mode,
            "flags": self.flags,
            "unix_sec": self.unix_sec,
            "pps_count": self.pps_count,
            "sample0": self.sample0,
            "frame_id": self.frame_id,
            "seq_no": self.seq_no,
            "chan0": self.chan0,
            "chan_count": self.chan_count,
            "time_count": self.time_count,
            "ninput": self.ninput,
            "payload_format": self.payload_format,
            "scale_id": self.scale_id,
            "payload_bytes": self.payload_bytes,
            "header_crc": self.header_crc,
        }

    @classmethod
    def from_axis_words(cls, words: Iterable[int]) -> "T510PacketHeader":
        """Parse the RTL 64-bit AXIS header word layout.

        The current packetizers build each 64-bit AXIS beat by concatenating
        fields in the human-readable RTL order, e.g. word 0 is
        {magic, version, header_bytes}. Header capture exposes those beats as
        32-bit low/high register reads, so this parser avoids treating the
        captured register image as a packed little-endian C struct.
        """
        axis_words = [int(word) & 0xFFFF_FFFF_FFFF_FFFF for word in words]
        if len(axis_words) < 16:
            raise ValueError(f"need 16 AXIS header words, got {len(axis_words)}")

        word0 = axis_words[0]
        word1 = axis_words[1]
        word6 = axis_words[6]
        word7 = axis_words[7]
        word8 = axis_words[8]
        word15 = axis_words[15]

        header = cls(
            magic=(word0 >> 32) & 0xFFFF_FFFF,
            version=(word0 >> 16) & 0xFFFF,
            header_bytes=word0 & 0xFFFF,
            board_id=(word1 >> 48) & 0xFFFF,
            stream_type=(word1 >> 32) & 0xFFFF,
            epoch_mode=(word1 >> 16) & 0xFFFF,
            flags=word1 & 0xFFFF,
            unix_sec=axis_words[2],
            pps_count=axis_words[3],
            sample0=axis_words[4],
            frame_id=axis_words[5],
            seq_no=(word6 >> 32) & 0xFFFF_FFFF,
            chan0=word6 & 0xFFFF_FFFF,
            chan_count=(word7 >> 48) & 0xFFFF,
            time_count=(word7 >> 32) & 0xFFFF,
            ninput=(word7 >> 16) & 0xFFFF,
            payload_format=word7 & 0xFFFF,
            scale_id=(word8 >> 32) & 0xFFFF_FFFF,
            payload_bytes=word8 & 0xFFFF_FFFF,
            header_crc=word15 & 0xFFFF_FFFF,
        )
        if header.magic != MAGIC:
            raise ValueError(f"bad T510 packet magic in AXIS words: 0x{header.magic:08x}")
        if header.version != 2:
            raise ValueError(f"unsupported AXIS packet header version: {header.version}")
        if header.header_bytes != HEADER_BYTES:
            raise ValueError(f"unexpected AXIS packet header size: {header.header_bytes}")
        return header

    @classmethod
    def from_bytes(cls, raw: bytes) -> "T510PacketHeader":
        if len(raw) < 8:
            raise ValueError("header too short: need at least 8 bytes")
        magic, version = struct.unpack_from("<IH", raw, 0)
        if magic != MAGIC:
            raise ValueError(f"bad T510 packet magic: 0x{magic:08x}")
        if version == 2:
            if len(raw) < STRUCT_V2.size:
                raise ValueError(f"header too short: need at least {STRUCT_V2.size} bytes")
            return cls(*STRUCT_V2.unpack(raw[: STRUCT_V2.size]))
        if version == 1:
            if len(raw) < STRUCT_V1.size:
                raise ValueError(f"header too short: need at least {STRUCT_V1.size} bytes")
            (
                magic,
                version,
                header_bytes,
                board_id,
                stream_type,
                local_ninput,
                global_input0,
                unix_sec,
                sample0,
                frame_id,
                seq_no,
                flags,
                chan0,
                chan_count,
                time_count,
                quant_mode,
                _scale_mode,
                scale_id,
                payload_bytes,
                header_crc,
            ) = STRUCT_V1.unpack(raw[: STRUCT_V1.size])
            return cls(
                magic=magic,
                version=version,
                header_bytes=header_bytes,
                board_id=board_id,
                stream_type=stream_type,
                epoch_mode=EPOCH_EXTERNAL_PPS if flags & FLAG_TIME_VALID else EPOCH_INTERNAL_ONLY,
                flags=flags,
                unix_sec=unix_sec,
                pps_count=0,
                sample0=sample0,
                frame_id=frame_id,
                seq_no=seq_no,
                chan0=chan0 if chan0 else global_input0,
                chan_count=chan_count,
                time_count=time_count,
                ninput=local_ninput,
                payload_format=quant_mode,
                scale_id=scale_id,
                payload_bytes=payload_bytes,
                header_crc=header_crc,
            )
        raise ValueError(f"unsupported T510 packet header version: {version}")


def _mac_to_str(value: int) -> str:
    return ":".join(f"{(value >> shift) & 0xFF:02x}" for shift in range(40, -1, -8))


def _ipv4_checksum(header: bytes) -> int:
    if len(header) % 2:
        header += b"\x00"
    total = 0
    for idx in range(0, len(header), 2):
        total += (header[idx] << 8) | header[idx + 1]
        total = (total & 0xFFFF) + (total >> 16)
    return (~total) & 0xFFFF


@dataclass(slots=True)
class EthernetIPv4UDPFrame:
    dst_mac: int
    src_mac: int
    eth_type: int
    ipv4_total_length: int
    ipv4_identification: int
    ipv4_flags_fragment: int
    ipv4_ttl: int
    ipv4_protocol: int
    ipv4_checksum: int
    src_ip: int
    dst_ip: int
    src_port: int
    dst_port: int
    udp_length: int
    udp_checksum: int
    payload: bytes
    t510_header: T510PacketHeader | None = None

    @classmethod
    def from_axis_words(cls, words: Iterable[int], *, tkeep: Iterable[int] | None = None) -> "EthernetIPv4UDPFrame":
        axis_words = [int(word) & 0xFFFF_FFFF_FFFF_FFFF for word in words]
        keeps = list(tkeep) if tkeep is not None else [0xFF] * len(axis_words)
        raw = bytearray()
        for word, keep in zip(axis_words, keeps):
            word_bytes = word.to_bytes(8, "little")
            for lane in range(8):
                if keep & (1 << lane):
                    raw.append(word_bytes[lane])
        return cls.from_bytes(bytes(raw))

    @classmethod
    def from_bytes(cls, raw: bytes) -> "EthernetIPv4UDPFrame":
        if len(raw) < 42:
            raise ValueError("Ethernet/IPv4/UDP frame too short: need at least 42 bytes")
        dst_mac = int.from_bytes(raw[0:6], "big")
        src_mac = int.from_bytes(raw[6:12], "big")
        eth_type = int.from_bytes(raw[12:14], "big")
        if eth_type != ETH_TYPE_IPV4:
            raise ValueError(f"unsupported eth_type: 0x{eth_type:04x}")
        version_ihl = raw[14]
        version = version_ihl >> 4
        ihl = version_ihl & 0x0F
        if version != 4 or ihl != 5:
            raise ValueError(f"unsupported IPv4 header shape: version={version} ihl={ihl}")
        ipv4_total_length = int.from_bytes(raw[16:18], "big")
        ipv4_identification = int.from_bytes(raw[18:20], "big")
        ipv4_flags_fragment = int.from_bytes(raw[20:22], "big")
        ipv4_ttl = raw[22]
        ipv4_protocol = raw[23]
        ipv4_checksum = int.from_bytes(raw[24:26], "big")
        if ipv4_protocol != IP_PROTO_UDP:
            raise ValueError(f"unsupported IPv4 protocol: {ipv4_protocol}")
        ip_header = raw[14:34]
        if _ipv4_checksum(ip_header) != 0:
            raise ValueError("bad IPv4 header checksum")
        src_ip = int.from_bytes(raw[26:30], "big")
        dst_ip = int.from_bytes(raw[30:34], "big")
        src_port = int.from_bytes(raw[34:36], "big")
        dst_port = int.from_bytes(raw[36:38], "big")
        udp_length = int.from_bytes(raw[38:40], "big")
        udp_checksum = int.from_bytes(raw[40:42], "big")
        payload_end = 42 + max(udp_length - 8, 0)
        payload = raw[42:min(len(raw), payload_end)]
        t510_header = None
        if len(payload) >= HEADER_BYTES:
            axis_words = struct.unpack("<16Q", payload[:HEADER_BYTES])
            t510_header = T510PacketHeader.from_axis_words(axis_words)
        return cls(
            dst_mac=dst_mac,
            src_mac=src_mac,
            eth_type=eth_type,
            ipv4_total_length=ipv4_total_length,
            ipv4_identification=ipv4_identification,
            ipv4_flags_fragment=ipv4_flags_fragment,
            ipv4_ttl=ipv4_ttl,
            ipv4_protocol=ipv4_protocol,
            ipv4_checksum=ipv4_checksum,
            src_ip=src_ip,
            dst_ip=dst_ip,
            src_port=src_port,
            dst_port=dst_port,
            udp_length=udp_length,
            udp_checksum=udp_checksum,
            payload=bytes(payload),
            t510_header=t510_header,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "dst_mac": self.dst_mac,
            "dst_mac_str": _mac_to_str(self.dst_mac),
            "src_mac": self.src_mac,
            "src_mac_str": _mac_to_str(self.src_mac),
            "eth_type": self.eth_type,
            "ipv4_total_length": self.ipv4_total_length,
            "ipv4_identification": self.ipv4_identification,
            "ipv4_flags_fragment": self.ipv4_flags_fragment,
            "ipv4_ttl": self.ipv4_ttl,
            "ipv4_protocol": self.ipv4_protocol,
            "ipv4_checksum": self.ipv4_checksum,
            "src_ip": self.src_ip,
            "src_ip_str": str(IPv4Address(self.src_ip)),
            "dst_ip": self.dst_ip,
            "dst_ip_str": str(IPv4Address(self.dst_ip)),
            "src_port": self.src_port,
            "dst_port": self.dst_port,
            "udp_length": self.udp_length,
            "udp_checksum": self.udp_checksum,
            "payload_len": len(self.payload),
            "t510_header": self.t510_header.to_dict() if self.t510_header is not None else None,
        }
