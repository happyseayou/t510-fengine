# T510 TIME UDP Payload v2

This document is the wire-format contract for T510 TIME UDP packets. RTL,
Python, Rust, and downstream receivers should treat this as the source of
truth for TIME packet payload decoding.

## UDP Datagram Shape

The TIME UDP datagram payload is fixed-size in the current design:

| Byte range | Size | Contents |
| --- | ---: | --- |
| `0..127` | `128 B` | T510 v2 header |
| `128..8319` | `8192 B` | TIME sample payload |

Lengths:

- UDP payload length: `8320 B`
- UDP datagram length, including UDP header: `8328 B`
- Ethernet frame length, excluding FCS: `8362 B`

## T510 v2 Header

The header is 16 little-endian AXIS lane-order `u64` words. Each word's logical
bit fields match RTL concatenation order.

| Word | Field layout |
| ---: | --- |
| `0` | `{magic=0x54353130, version=2, header_bytes=128}` |
| `1` | `{board_id, stream_type=1 TIME, epoch_mode, flags}` |
| `2` | `unix_sec` |
| `3` | `pps_count` |
| `4` | `sample0` |
| `5` | `frame_id` |
| `6` | `{seq_no[31:0], 16'h0000, global_input0[15:0]}` |
| `7` | `{16'h0000, time_count, ninput=8, payload_format=0 int16 IQ}` |
| `8` | `{scale_id, payload_bytes=8192}` |
| `9..14` | reserved, currently `0` |
| `15` | reserved upper 32 bits, `header_crc[31:0]`; CRC currently `0` |

The fields are interpreted as:

- `sample0`: raw `245.76 MHz` sample index of the first decoded sample in the
  packet.
- `time_count`: number of 1024-bit science beats in the TIME sample payload.
  The default and current full-size value is `64`.
- `ninput`: number of logical complex input channels. Current value is `8`.
- `payload_format=0`: each complex sample is signed `i16 I` plus signed `i16 Q`.

## TIME Sample Payload

The TIME sample payload is `time_count` consecutive 1024-bit science beats.
Each 1024-bit beat contains 4 time sub-samples for 8 complex channels.

Each complex sample is one little-endian 32-bit word:

- bits `15:0`: signed `i16 I`
- bits `31:16`: signed `i16 Q`

Each 64-bit payload word carries two adjacent channels:

- lower 32 bits: even channel
- upper 32 bits: odd channel

For `beat b`, `sub-sample s in 0..3`, and `channel ch in 0..7`:

```text
word64      = b * 16 + s * 4 + floor(ch / 2)
byte_offset = 128 + word64 * 8 + (0 if ch even else 4)
I           = le_i16(byte_offset + 0)
Q           = le_i16(byte_offset + 2)
```

With the default `time_count=64`, each channel has `64 * 4 = 256` decoded
complex samples per packet.

## Time Axis

All TIME modes use raw `245.76 MHz` sample indices for packet timestamps.
The selected receive/display bandwidth determines the decimation factor:

| TIME bandwidth | Decimation | Effective sample rate |
| ---: | ---: | ---: |
| `200 MHz` | `1` | `245.76 MS/s` |
| `100 MHz` | `2` | `122.88 MS/s` |
| `20 MHz` | `8` | `30.72 MS/s` |

For decoded sample index `(b, s)`:

```text
sample_index = sample0 + (b * 4 + s) * decim
```

For full-rate consecutive packets, the expected `sample0` delta is:

```text
expected_sample0_delta = time_count * 4 * decim
```

For default `time_count=64`, that is:

- `200 MHz`: `256`
- `100 MHz`: `512`
- `20 MHz`: `2048`

`seq_no` and `frame_id` must increment by `1` per packet. A mismatch in
`seq_no`, `frame_id`, or `sample0` delta is a packet gap/loss indicator. Display
clients must break waveform continuity at gaps rather than interpolating.

## RF Equivalent Display

The browser-side RF-equivalent waveform is derived from received I/Q. It is not
raw RF ADC data.

For raw sample index `sample_index`, center frequency `center_hz`, and optional
per-channel display phase `phase_rad`:

```text
theta = 2*pi*center_hz*sample_index/245.76e6 + phase_rad
rf    = I*cos(theta) - Q*sin(theta)
```

The HTML bandwidth selector changes receive-side decoding, validation, and time
axis only. It does not configure FPGA hardware. Jupyter or board-side scripts
remain responsible for changing FPGA TIME bandwidth.
