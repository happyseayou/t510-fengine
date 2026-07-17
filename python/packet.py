from __future__ import annotations

from dataclasses import dataclass
from ipaddress import IPv4Address
import struct
from typing import Iterable


MAGIC = 0x54353130
HEADER_BYTES = 128
TIME_PAYLOAD_BYTES = 8192
TIME_UDP_PAYLOAD_BYTES = HEADER_BYTES + TIME_PAYLOAD_BYTES
TIME_NINPUT = 8
TIME_SUBSAMPLES_PER_BEAT = 4
TIME_WORD64_PER_BEAT = 16
RAW_SAMPLE_RATE_HZ = 245_760_000.0
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
EPOCH_SCHEDULED_TAI = 2

FLAG_TIME_VALID = 1 << 0
FLAG_INTERNAL_EPOCH = 1 << 1
FLAG_QSFP_LINK_UP = 1 << 2
FLAG_UDP_DRY_RUN = 1 << 3
FLAG_ADC_CLIP = 1 << 4
FLAG_FIFO_OVERFLOW = 1 << 5
ETH_TYPE_IPV4 = 0x0800
IP_PROTO_UDP = 17

TIME_BANDWIDTH_DECIMATION = {
    200: 1,
    100: 2,
    20: 8,
}


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
    sync_generation: int = 0
    sync_observation_tag: int = 0
    sync_metadata: int = 0
    sync_status: int = 0

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
        raw = bytearray(packed.ljust(self.header_bytes, b"\x00"))
        if self.version >= 3 and self.header_bytes >= HEADER_BYTES:
            struct.pack_into(
                "<QQQQ",
                raw,
                12 * 8,
                self.sync_generation,
                self.sync_observation_tag,
                self.sync_metadata,
                self.sync_status,
            )
        return bytes(raw)

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
            "sync_generation": self.sync_generation,
            "sync_observation_tag": self.sync_observation_tag,
            "sync_metadata": self.sync_metadata,
            "sync_status": self.sync_status,
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
            sync_generation=axis_words[12],
            sync_observation_tag=axis_words[13],
            sync_metadata=axis_words[14],
            sync_status=axis_words[15],
        )
        if header.magic != MAGIC:
            raise ValueError(f"bad T510 packet magic in AXIS words: 0x{header.magic:08x}")
        if header.version not in (2, 3):
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
        if version in (2, 3):
            if len(raw) < STRUCT_V2.size:
                raise ValueError(f"header too short: need at least {STRUCT_V2.size} bytes")
            header = cls(*STRUCT_V2.unpack(raw[: STRUCT_V2.size]))
            if version == 3:
                if len(raw) < HEADER_BYTES:
                    raise ValueError(f"v3 header too short: need at least {HEADER_BYTES} bytes")
                (
                    header.sync_generation,
                    header.sync_observation_tag,
                    header.sync_metadata,
                    header.sync_status,
                ) = struct.unpack_from("<QQQQ", raw, 12 * 8)
                header.header_crc = header.sync_status & 0xFFFF_FFFF
            return header
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


def normalize_time_bandwidth_mhz(bandwidth_mhz: int | float | str) -> int:
    try:
        value = int(round(float(str(bandwidth_mhz).lower().replace("mhz", "").strip())))
    except Exception as exc:
        raise ValueError(f"unsupported TIME bandwidth: {bandwidth_mhz!r}") from exc
    if value not in TIME_BANDWIDTH_DECIMATION:
        raise ValueError("TIME bandwidth must be one of 20, 100, 200 MHz")
    return value


def time_decimation_for_bandwidth(bandwidth_mhz: int | float | str) -> int:
    return TIME_BANDWIDTH_DECIMATION[normalize_time_bandwidth_mhz(bandwidth_mhz)]


def time_sample_rate_hz_for_bandwidth(bandwidth_mhz: int | float | str) -> float:
    return RAW_SAMPLE_RATE_HZ / float(time_decimation_for_bandwidth(bandwidth_mhz))


def expected_time_sample0_delta(header: T510PacketHeader, bandwidth_mhz: int | float | str) -> int:
    return int(header.time_count) * TIME_SUBSAMPLES_PER_BEAT * time_decimation_for_bandwidth(bandwidth_mhz)


def infer_time_bandwidth_from_delta(header: T510PacketHeader, sample0_delta: int) -> int | None:
    denom = int(header.time_count) * TIME_SUBSAMPLES_PER_BEAT
    if denom <= 0 or int(sample0_delta) % denom != 0:
        return None
    decim = int(sample0_delta) // denom
    for bandwidth, candidate in TIME_BANDWIDTH_DECIMATION.items():
        if int(candidate) == decim:
            return int(bandwidth)
    return None


def time_payload_complex_offset(*, beat: int, sub_sample: int, channel: int) -> int:
    if int(beat) < 0:
        raise ValueError("beat must be non-negative")
    if not 0 <= int(sub_sample) < TIME_SUBSAMPLES_PER_BEAT:
        raise ValueError("sub_sample must be in range 0..3")
    if not 0 <= int(channel) < TIME_NINPUT:
        raise ValueError("channel must be in range 0..7")
    word64 = int(beat) * TIME_WORD64_PER_BEAT + int(sub_sample) * (TIME_NINPUT // 2) + (int(channel) // 2)
    return HEADER_BYTES + word64 * 8 + (0 if (int(channel) % 2) == 0 else 4)


def decode_time_udp_payload_iq(
    udp_payload: bytes,
    *,
    bandwidth_mhz: int | float | str = 200,
    channels: Iterable[int] | None = None,
) -> dict[str, object]:
    """Decode a T510 TIME UDP payload according to docs/time_udp_payload_v2.md.

    ``udp_payload`` is the UDP payload, not the whole Ethernet frame. It must
    contain the 128-byte T510 header followed by the TIME sample payload.
    """
    if len(udp_payload) < HEADER_BYTES:
        raise ValueError("TIME UDP payload is shorter than the T510 header")
    header = T510PacketHeader.from_axis_words(struct.unpack("<16Q", udp_payload[:HEADER_BYTES]))
    if int(header.stream_type) != STREAM_TIME:
        raise ValueError(f"T510 header is not TIME stream: stream_type={header.stream_type}")
    if int(header.ninput) != TIME_NINPUT:
        raise ValueError(f"unsupported TIME ninput={header.ninput}; expected {TIME_NINPUT}")
    if int(header.payload_format) != QUANT_INT16:
        raise ValueError(f"unsupported TIME payload_format={header.payload_format}; expected int16 IQ")
    if int(header.payload_bytes) > len(udp_payload) - HEADER_BYTES:
        raise ValueError(
            f"TIME payload truncated: header payload_bytes={header.payload_bytes}, "
            f"available={len(udp_payload) - HEADER_BYTES}"
        )
    if int(header.payload_bytes) != TIME_PAYLOAD_BYTES:
        raise ValueError(f"unexpected TIME payload_bytes={header.payload_bytes}; expected {TIME_PAYLOAD_BYTES}")

    bandwidth = normalize_time_bandwidth_mhz(bandwidth_mhz)
    decim = time_decimation_for_bandwidth(bandwidth)
    selected_channels = list(range(TIME_NINPUT)) if channels is None else [int(ch) for ch in channels]
    for channel in selected_channels:
        if not 0 <= channel < TIME_NINPUT:
            raise ValueError("channels must be in range 0..7")

    sample_count = int(header.time_count) * TIME_SUBSAMPLES_PER_BEAT
    decoded: dict[int, list[tuple[int, int, int]]] = {channel: [] for channel in selected_channels}
    for beat in range(int(header.time_count)):
        for sub in range(TIME_SUBSAMPLES_PER_BEAT):
            logical_idx = beat * TIME_SUBSAMPLES_PER_BEAT + sub
            sample_index = int(header.sample0) + logical_idx * decim
            for channel in selected_channels:
                offset = time_payload_complex_offset(beat=beat, sub_sample=sub, channel=channel)
                i_sample = int.from_bytes(udp_payload[offset : offset + 2], "little", signed=True)
                q_sample = int.from_bytes(udp_payload[offset + 2 : offset + 4], "little", signed=True)
                decoded[channel].append((sample_index, i_sample, q_sample))

    return {
        "header": header,
        "header_dict": header.to_dict(),
        "bandwidth_mhz": bandwidth,
        "decimation": decim,
        "sample_rate_hz": time_sample_rate_hz_for_bandwidth(bandwidth),
        "sample_count_per_channel": sample_count,
        "expected_sample0_delta": expected_time_sample0_delta(header, bandwidth),
        "channels": decoded,
    }
