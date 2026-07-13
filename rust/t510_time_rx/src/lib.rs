use serde::{Deserialize, Serialize};

pub const MAGIC: u32 = 0x5435_3130;
pub const HEADER_BYTES: usize = 128;
pub const TIME_PAYLOAD_BYTES: usize = 8192;
pub const TIME_UDP_PAYLOAD_BYTES: usize = HEADER_BYTES + TIME_PAYLOAD_BYTES;
pub const SPEC_PAYLOAD_BYTES: usize = 8192;
pub const SPEC_UDP_PAYLOAD_BYTES: usize = HEADER_BYTES + SPEC_PAYLOAD_BYTES;
pub const TIME_NINPUT: usize = 8;
pub const TIME_SUBSAMPLES_PER_BEAT: usize = 4;
pub const TIME_WORD64_PER_BEAT: usize = 16;
pub const RAW_SAMPLE_RATE_HZ: f64 = 245_760_000.0;
pub const STREAM_SPEC: u16 = 0;
pub const STREAM_TIME: u16 = 1;
pub const PAYLOAD_FORMAT_INT16_IQ: u16 = 0;
pub const PRODUCT_FENGINE_IQ16: u16 = 0xf101;
pub const SPEC_NCHAN_27F: u16 = 4096;
pub const SPEC_BLOCK_COUNT_27F: u16 = 64;
pub const SPEC_BLOCK_CHANS_27F: u16 = 64;
pub const SPEC_TIME_COUNT_27F: u16 = 4;
pub const SPEC_BLOCK_COUNT_27H: u16 = 16;
pub const SPEC_BLOCK_CHANS_27H: u16 = 256;
pub const SPEC_TIME_COUNT_27H: u16 = 1;
pub const SPEC_FFT_ONLY_FLAG: u32 = 1 << 8;
pub const SPEC_ANTI_ALIAS_100M_FLAG: u32 = 1 << 9;
pub const SPEC_PFB_ACTIVE_FLAG: u32 = 1 << 10;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum BandwidthMode {
    Mhz20,
    Mhz100,
    Mhz200,
}

impl BandwidthMode {
    pub fn from_mhz(value: u32) -> Option<Self> {
        match value {
            20 => Some(Self::Mhz20),
            100 => Some(Self::Mhz100),
            200 => Some(Self::Mhz200),
            _ => None,
        }
    }

    pub fn mhz(self) -> u32 {
        match self {
            Self::Mhz20 => 20,
            Self::Mhz100 => 100,
            Self::Mhz200 => 200,
        }
    }

    pub fn decimation(self) -> u64 {
        match self {
            Self::Mhz20 => 8,
            Self::Mhz100 => 2,
            Self::Mhz200 => 1,
        }
    }

    pub fn sample_rate_hz(self) -> f64 {
        RAW_SAMPLE_RATE_HZ / self.decimation() as f64
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DisplayConfig {
    pub bandwidth_mhz: u32,
    #[serde(default = "default_output_mode")]
    pub output_mode: String,
    pub center_mhz: f64,
    pub expected_mhz: f64,
    pub dac_mhz: f64,
    #[serde(default = "default_target_mhz_by_channel")]
    pub target_mhz_by_channel: [f64; TIME_NINPUT],
    pub waveform_view_mode: String,
    pub phase_deg_by_channel: [f64; TIME_NINPUT],
    pub channel_mask: u16,
    pub time_window_us: f64,
    pub display_points: usize,
    pub vertical_scale: f64,
    pub paused: bool,
}

impl Default for DisplayConfig {
    fn default() -> Self {
        Self {
            bandwidth_mhz: 100,
            output_mode: "time_spec".to_string(),
            center_mhz: 100.0,
            expected_mhz: 60.010,
            dac_mhz: 60.010,
            target_mhz_by_channel: [60.010; TIME_NINPUT],
            waveform_view_mode: "dual".to_string(),
            phase_deg_by_channel: [0.0; TIME_NINPUT],
            channel_mask: 0x00ff,
            time_window_us: 0.25,
            display_points: 1024,
            vertical_scale: 512.0,
            paused: false,
        }
    }
}

impl DisplayConfig {
    pub fn bandwidth_mode(&self) -> BandwidthMode {
        BandwidthMode::from_mhz(self.bandwidth_mhz).unwrap_or(BandwidthMode::Mhz100)
    }

    pub fn needs_time(&self) -> bool {
        matches!(self.output_mode.as_str(), "time_only" | "time_spec")
    }

    pub fn needs_spec(&self) -> bool {
        matches!(self.output_mode.as_str(), "spec_only" | "time_spec")
    }

    pub fn target_hz(&self, channel: usize) -> f64 {
        let target = self.target_mhz_by_channel[channel.min(TIME_NINPUT - 1)];
        let legacy_only = self
            .target_mhz_by_channel
            .iter()
            .all(|value| (*value - 60.010).abs() < 1.0e-12);
        if legacy_only && (self.expected_mhz - 60.010).abs() >= 1.0e-12 {
            return expected_signal_hz(self);
        }
        if target.is_finite() && target > 0.0 {
            target * 1_000_000.0
        } else {
            expected_signal_hz(self)
        }
    }
}

fn default_output_mode() -> String {
    "time_spec".to_string()
}

fn default_target_mhz_by_channel() -> [f64; TIME_NINPUT] {
    [60.010; TIME_NINPUT]
}

fn waveform_carrier_hz(config: &DisplayConfig) -> f64 {
    config.center_mhz * 1_000_000.0
}

fn expected_signal_hz(config: &DisplayConfig) -> f64 {
    if config.expected_mhz.is_finite() && config.expected_mhz > 0.0 {
        config.expected_mhz * 1_000_000.0
    } else if config.dac_mhz.is_finite() && config.dac_mhz > 0.0 {
        config.dac_mhz * 1_000_000.0
    } else {
        config.center_mhz * 1_000_000.0
    }
}

fn samples_per_cycle(sample_rate_hz: f64, frequency_hz: f64) -> f64 {
    if !frequency_hz.is_finite() || frequency_hz.abs() < 1.0 {
        f64::INFINITY
    } else {
        sample_rate_hz / frequency_hz.abs()
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct T510Header {
    pub magic: u32,
    pub version: u16,
    pub header_bytes: u16,
    pub board_id: u16,
    pub stream_type: u16,
    pub epoch_mode: u16,
    pub flags: u16,
    pub unix_sec: u64,
    pub pps_count: u64,
    pub sample0: u64,
    pub frame_id: u64,
    pub seq_no: u32,
    pub chan0: u32,
    pub chan_count: u16,
    pub time_count: u16,
    pub ninput: u16,
    pub payload_format: u16,
    pub scale_id: u32,
    pub payload_bytes: u32,
    pub product_id: u16,
    pub nchan: u16,
    pub block_index: u16,
    pub block_count: u16,
    pub pfb_taps: u16,
    pub fft_shift: u16,
    pub spec_status_flags: u32,
    pub spec_sample_rate_hz: u32,
    pub scale_mode: u16,
    pub spec_half_band: bool,
    pub header_crc: u32,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum FastPacketError {
    FrameTooShort,
    NonIpv4Ethernet,
    UnsupportedIpv4Header,
    TruncatedIpv4Udp,
    NonUdpIpv4,
    WrongUdpDstPort,
    BadUdpLength,
    UdpPayloadTooShort,
    BadT510Magic,
    UnsupportedT510Version,
    UnexpectedT510HeaderBytes,
    NotTimeStream,
    NotSpecStream,
    UnsupportedNinput,
    UnsupportedPayloadFormat,
    UnexpectedPayloadBytes,
    UnsupportedProduct,
    UnexpectedSpecLayout,
    TruncatedPayload,
    TruncatedTimePayload,
    TruncatedSpecPayload,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct DecodedSample {
    pub sample_index: u64,
    pub i: i16,
    pub q: i16,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ChannelWaveform {
    pub channel: usize,
    pub x_us: Vec<f32>,
    pub i: Vec<f32>,
    pub q: Vec<f32>,
    pub mag: Vec<f32>,
    pub sample_rf: Vec<f32>,
    pub rf_x_us: Vec<f32>,
    pub rf: Vec<f32>,
    pub y: Vec<f32>,
    pub rms_code: f32,
    pub max_abs_code: i16,
    pub clipped: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WaveformSnapshot {
    pub sample0: u64,
    pub seq_no: u32,
    pub frame_id: u64,
    pub selected_bandwidth_mhz: u32,
    pub detected_bandwidth_mhz: Option<u32>,
    pub decimation: u64,
    pub sample_rate_hz: f64,
    pub requested_window_us: f64,
    pub captured_window_us: f64,
    pub center_mhz: f64,
    pub expected_mhz: f64,
    pub dac_mhz: f64,
    pub expected_baseband_mhz: f64,
    pub rf_samples_per_cycle: f64,
    pub baseband_samples_per_cycle: f64,
    pub rf_window_cycles: f64,
    pub gap_before: bool,
    pub channels: Vec<ChannelWaveform>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SpectrumLane {
    pub input: usize,
    pub amplitude: Vec<f32>,
    pub phase_rad: Vec<f32>,
    pub power_db: Vec<f32>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SpectrumSnapshot {
    pub sample0: u64,
    pub seq_no: u32,
    pub frame_id: u64,
    pub chan0: u32,
    pub chan_count: u16,
    pub time_count: u16,
    pub ninput: u16,
    pub product_id: u16,
    pub nchan: u16,
    pub block_index: u16,
    pub block_count: u16,
    pub pfb_taps: u16,
    pub fft_shift: u16,
    pub spec_status_flags: u32,
    pub spec_sample_rate_hz: u32,
    pub coverage_blocks: u32,
    pub coverage_mask_lo: u64,
    pub coverage_mask_hi: u64,
    pub src_port: u16,
    pub dst_port: u16,
    pub gap_before: bool,
    pub lanes: Vec<SpectrumLane>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct UdpPayloadView<'a> {
    pub payload: &'a [u8],
    pub src_port: u16,
    pub dst_port: u16,
}

pub fn parse_t510_header(udp_payload: &[u8]) -> Result<T510Header, String> {
    if udp_payload.len() < HEADER_BYTES {
        return Err("UDP payload shorter than T510 header".to_string());
    }
    let mut words = [0u64; 16];
    for (idx, chunk) in udp_payload[..HEADER_BYTES].chunks_exact(8).enumerate() {
        let mut word = [0u8; 8];
        word.copy_from_slice(chunk);
        words[idx] = u64::from_le_bytes(word);
    }
    let word0 = words[0];
    let word1 = words[1];
    let word6 = words[6];
    let word7 = words[7];
    let word8 = words[8];
    let word9 = words[9];
    let word10 = words[10];
    let word11 = words[11];
    let word15 = words[15];
    let header = T510Header {
        magic: (word0 >> 32) as u32,
        version: ((word0 >> 16) & 0xffff) as u16,
        header_bytes: (word0 & 0xffff) as u16,
        board_id: ((word1 >> 48) & 0xffff) as u16,
        stream_type: ((word1 >> 32) & 0xffff) as u16,
        epoch_mode: ((word1 >> 16) & 0xffff) as u16,
        flags: (word1 & 0xffff) as u16,
        unix_sec: words[2],
        pps_count: words[3],
        sample0: words[4],
        frame_id: words[5],
        seq_no: ((word6 >> 32) & 0xffff_ffff) as u32,
        chan0: (word6 & 0xffff_ffff) as u32,
        chan_count: ((word7 >> 48) & 0xffff) as u16,
        time_count: ((word7 >> 32) & 0xffff) as u16,
        ninput: ((word7 >> 16) & 0xffff) as u16,
        payload_format: (word7 & 0xffff) as u16,
        scale_id: ((word8 >> 32) & 0xffff_ffff) as u32,
        payload_bytes: (word8 & 0xffff_ffff) as u32,
        product_id: ((word9 >> 48) & 0xffff) as u16,
        nchan: ((word9 >> 32) & 0xffff) as u16,
        block_index: ((word9 >> 16) & 0xffff) as u16,
        block_count: (word9 & 0xffff) as u16,
        pfb_taps: ((word10 >> 48) & 0xffff) as u16,
        fft_shift: ((word10 >> 32) & 0xffff) as u16,
        spec_status_flags: (word10 & 0xffff_ffff) as u32,
        spec_sample_rate_hz: ((word11 >> 32) & 0xffff_ffff) as u32,
        scale_mode: ((word11 >> 16) & 0xffff) as u16,
        spec_half_band: (word11 & 1) != 0,
        header_crc: (word15 & 0xffff_ffff) as u32,
    };
    if header.magic != MAGIC {
        return Err(format!("bad T510 magic 0x{:08x}", header.magic));
    }
    if header.version != 2 {
        return Err(format!("unsupported T510 header version {}", header.version));
    }
    if header.header_bytes as usize != HEADER_BYTES {
        return Err(format!("unexpected header_bytes {}", header.header_bytes));
    }
    Ok(header)
}

pub fn validate_common_payload_bounds(header: &T510Header, udp_payload_len: usize) -> Result<(), String> {
    if udp_payload_len < HEADER_BYTES + header.payload_bytes as usize {
        return Err(format!(
            "truncated T510 payload: available {}, needed {}",
            udp_payload_len,
            HEADER_BYTES + header.payload_bytes as usize
        ));
    }
    Ok(())
}

pub fn validate_time_header(header: &T510Header, udp_payload_len: usize) -> Result<(), String> {
    if header.stream_type != STREAM_TIME {
        return Err(format!("not a TIME stream: stream_type={}", header.stream_type));
    }
    if header.ninput as usize != TIME_NINPUT {
        return Err(format!("unsupported ninput {}; expected {}", header.ninput, TIME_NINPUT));
    }
    if header.payload_format != PAYLOAD_FORMAT_INT16_IQ {
        return Err(format!(
            "unsupported payload_format {}; expected int16 IQ",
            header.payload_format
        ));
    }
    if header.payload_bytes as usize != TIME_PAYLOAD_BYTES {
        return Err(format!(
            "unexpected payload_bytes {}; expected {}",
            header.payload_bytes, TIME_PAYLOAD_BYTES
        ));
    }
    if udp_payload_len < HEADER_BYTES + header.payload_bytes as usize {
        return Err(format!(
            "truncated TIME payload: available {}, needed {}",
            udp_payload_len,
            HEADER_BYTES + header.payload_bytes as usize
        ));
    }
    Ok(())
}

pub fn is_supported_spec_layout(header: &T510Header) -> bool {
    if header.nchan != SPEC_NCHAN_27F || header.block_index >= header.block_count {
        return false;
    }
    if header.chan0 != u32::from(header.block_index) * u32::from(header.chan_count) {
        return false;
    }
    let payload_bytes = header.chan_count as usize * header.time_count as usize * header.ninput as usize * 4;
    if payload_bytes != SPEC_PAYLOAD_BYTES {
        return false;
    }
    let stage27h = header.block_count == SPEC_BLOCK_COUNT_27H
        && header.chan_count == SPEC_BLOCK_CHANS_27H
        && header.time_count == SPEC_TIME_COUNT_27H
        && header.pfb_taps == 0;
    let stage27j = header.block_count == SPEC_BLOCK_COUNT_27H
        && header.chan_count == SPEC_BLOCK_CHANS_27H
        && header.time_count == SPEC_TIME_COUNT_27H
        && header.pfb_taps >= 4;
    let stage27g = header.block_count == SPEC_BLOCK_COUNT_27F
        && header.chan_count == SPEC_BLOCK_CHANS_27F
        && header.time_count == SPEC_TIME_COUNT_27F
        && header.pfb_taps >= 4;
    stage27h || stage27j || stage27g
}

pub fn validate_spec_header(header: &T510Header, udp_payload_len: usize) -> Result<(), String> {
    if header.stream_type != STREAM_SPEC {
        return Err(format!("not a SPEC stream: stream_type={}", header.stream_type));
    }
    if header.ninput as usize != TIME_NINPUT {
        return Err(format!("unsupported ninput {}; expected {}", header.ninput, TIME_NINPUT));
    }
    if header.payload_format != PAYLOAD_FORMAT_INT16_IQ {
        return Err(format!(
            "unsupported payload_format {}; expected int16 IQ",
            header.payload_format
        ));
    }
    if header.payload_bytes as usize != SPEC_PAYLOAD_BYTES {
        return Err(format!(
            "unexpected SPEC payload_bytes {}; expected {}",
            header.payload_bytes, SPEC_PAYLOAD_BYTES
        ));
    }
    if header.product_id != PRODUCT_FENGINE_IQ16 {
        return Err(format!(
            "unsupported SPEC product_id 0x{:04x}; expected FENGINE_IQ16",
            header.product_id
        ));
    }
    if !is_supported_spec_layout(header) {
        return Err(format!(
            "unexpected SPEC layout/product nchan={} block={}/{} chan0={} chan_count={} time_count={} taps={} flags=0x{:08x}",
            header.nchan,
            header.block_index,
            header.block_count,
            header.chan0,
            header.chan_count,
            header.time_count,
            header.pfb_taps,
            header.spec_status_flags
        ));
    }
    let expected = header.chan_count as usize * header.time_count as usize * header.ninput as usize * 4;
    if expected != header.payload_bytes as usize {
        return Err(format!(
            "SPEC layout implies {} payload bytes, header says {}",
            expected, header.payload_bytes
        ));
    }
    if udp_payload_len < HEADER_BYTES + header.payload_bytes as usize {
        return Err(format!(
            "truncated SPEC payload: available {}, needed {}",
            udp_payload_len,
            HEADER_BYTES + header.payload_bytes as usize
        ));
    }
    Ok(())
}

pub fn parse_t510_header_fast(udp_payload: &[u8]) -> Result<T510Header, FastPacketError> {
    if udp_payload.len() < HEADER_BYTES {
        return Err(FastPacketError::UdpPayloadTooShort);
    }
    let mut words = [0u64; 16];
    for (idx, chunk) in udp_payload[..HEADER_BYTES].chunks_exact(8).enumerate() {
        let mut word = [0u8; 8];
        word.copy_from_slice(chunk);
        words[idx] = u64::from_le_bytes(word);
    }
    let word0 = words[0];
    let word1 = words[1];
    let word6 = words[6];
    let word7 = words[7];
    let word8 = words[8];
    let word9 = words[9];
    let word10 = words[10];
    let word11 = words[11];
    let word15 = words[15];
    let header = T510Header {
        magic: (word0 >> 32) as u32,
        version: ((word0 >> 16) & 0xffff) as u16,
        header_bytes: (word0 & 0xffff) as u16,
        board_id: ((word1 >> 48) & 0xffff) as u16,
        stream_type: ((word1 >> 32) & 0xffff) as u16,
        epoch_mode: ((word1 >> 16) & 0xffff) as u16,
        flags: (word1 & 0xffff) as u16,
        unix_sec: words[2],
        pps_count: words[3],
        sample0: words[4],
        frame_id: words[5],
        seq_no: ((word6 >> 32) & 0xffff_ffff) as u32,
        chan0: (word6 & 0xffff_ffff) as u32,
        chan_count: ((word7 >> 48) & 0xffff) as u16,
        time_count: ((word7 >> 32) & 0xffff) as u16,
        ninput: ((word7 >> 16) & 0xffff) as u16,
        payload_format: (word7 & 0xffff) as u16,
        scale_id: ((word8 >> 32) & 0xffff_ffff) as u32,
        payload_bytes: (word8 & 0xffff_ffff) as u32,
        product_id: ((word9 >> 48) & 0xffff) as u16,
        nchan: ((word9 >> 32) & 0xffff) as u16,
        block_index: ((word9 >> 16) & 0xffff) as u16,
        block_count: (word9 & 0xffff) as u16,
        pfb_taps: ((word10 >> 48) & 0xffff) as u16,
        fft_shift: ((word10 >> 32) & 0xffff) as u16,
        spec_status_flags: (word10 & 0xffff_ffff) as u32,
        spec_sample_rate_hz: ((word11 >> 32) & 0xffff_ffff) as u32,
        scale_mode: ((word11 >> 16) & 0xffff) as u16,
        spec_half_band: (word11 & 1) != 0,
        header_crc: (word15 & 0xffff_ffff) as u32,
    };
    if header.magic != MAGIC {
        return Err(FastPacketError::BadT510Magic);
    }
    if header.version != 2 {
        return Err(FastPacketError::UnsupportedT510Version);
    }
    if header.header_bytes as usize != HEADER_BYTES {
        return Err(FastPacketError::UnexpectedT510HeaderBytes);
    }
    Ok(header)
}

pub fn validate_time_header_fast(header: &T510Header, udp_payload_len: usize) -> Result<(), FastPacketError> {
    if header.stream_type != STREAM_TIME {
        return Err(FastPacketError::NotTimeStream);
    }
    if header.ninput as usize != TIME_NINPUT {
        return Err(FastPacketError::UnsupportedNinput);
    }
    if header.payload_format != PAYLOAD_FORMAT_INT16_IQ {
        return Err(FastPacketError::UnsupportedPayloadFormat);
    }
    if header.payload_bytes as usize != TIME_PAYLOAD_BYTES {
        return Err(FastPacketError::UnexpectedPayloadBytes);
    }
    if udp_payload_len < HEADER_BYTES + header.payload_bytes as usize {
        return Err(FastPacketError::TruncatedTimePayload);
    }
    Ok(())
}

pub fn validate_spec_header_fast(header: &T510Header, udp_payload_len: usize) -> Result<(), FastPacketError> {
    if header.stream_type != STREAM_SPEC {
        return Err(FastPacketError::NotSpecStream);
    }
    if header.ninput as usize != TIME_NINPUT {
        return Err(FastPacketError::UnsupportedNinput);
    }
    if header.payload_format != PAYLOAD_FORMAT_INT16_IQ {
        return Err(FastPacketError::UnsupportedPayloadFormat);
    }
    if header.payload_bytes as usize != SPEC_PAYLOAD_BYTES {
        return Err(FastPacketError::UnexpectedPayloadBytes);
    }
    if header.product_id != PRODUCT_FENGINE_IQ16 {
        return Err(FastPacketError::UnsupportedProduct);
    }
    if !is_supported_spec_layout(header) {
        return Err(FastPacketError::UnexpectedSpecLayout);
    }
    let expected = header.chan_count as usize * header.time_count as usize * header.ninput as usize * 4;
    if expected != header.payload_bytes as usize {
        return Err(FastPacketError::UnexpectedPayloadBytes);
    }
    if udp_payload_len < HEADER_BYTES + header.payload_bytes as usize {
        return Err(FastPacketError::TruncatedSpecPayload);
    }
    Ok(())
}

pub fn parse_t510_time_header_fast(udp_payload: &[u8]) -> Result<T510Header, FastPacketError> {
    let header = parse_t510_header_fast(udp_payload)?;
    validate_time_header_fast(&header, udp_payload.len())?;
    Ok(header)
}

pub fn time_payload_complex_offset(beat: usize, sub_sample: usize, channel: usize) -> Result<usize, String> {
    if sub_sample >= TIME_SUBSAMPLES_PER_BEAT {
        return Err("sub_sample must be in range 0..3".to_string());
    }
    if channel >= TIME_NINPUT {
        return Err("channel must be in range 0..7".to_string());
    }
    let word64 = beat * TIME_WORD64_PER_BEAT + sub_sample * (TIME_NINPUT / 2) + channel / 2;
    Ok(HEADER_BYTES + word64 * 8 + if channel % 2 == 0 { 0 } else { 4 })
}

pub fn expected_sample0_delta(header: &T510Header, bandwidth: BandwidthMode) -> u64 {
    header.time_count as u64 * TIME_SUBSAMPLES_PER_BEAT as u64 * bandwidth.decimation()
}

pub fn infer_bandwidth_from_sample0_delta(header: &T510Header, delta: u64) -> Option<BandwidthMode> {
    let denom = header.time_count as u64 * TIME_SUBSAMPLES_PER_BEAT as u64;
    if denom == 0 || delta % denom != 0 {
        return None;
    }
    match delta / denom {
        1 => Some(BandwidthMode::Mhz200),
        2 => Some(BandwidthMode::Mhz100),
        8 => Some(BandwidthMode::Mhz20),
        _ => None,
    }
}

pub fn decode_channel_samples(
    udp_payload: &[u8],
    header: &T510Header,
    bandwidth: BandwidthMode,
    channel: usize,
) -> Result<Vec<DecodedSample>, String> {
    validate_time_header(header, udp_payload.len())?;
    if channel >= TIME_NINPUT {
        return Err("channel must be in range 0..7".to_string());
    }
    let mut out = Vec::with_capacity(header.time_count as usize * TIME_SUBSAMPLES_PER_BEAT);
    for beat in 0..header.time_count as usize {
        for sub in 0..TIME_SUBSAMPLES_PER_BEAT {
            let offset = time_payload_complex_offset(beat, sub, channel)?;
            let i = i16::from_le_bytes([udp_payload[offset], udp_payload[offset + 1]]);
            let q = i16::from_le_bytes([udp_payload[offset + 2], udp_payload[offset + 3]]);
            let logical_idx = beat * TIME_SUBSAMPLES_PER_BEAT + sub;
            out.push(DecodedSample {
                sample_index: header.sample0 + logical_idx as u64 * bandwidth.decimation(),
                i,
                q,
            });
        }
    }
    Ok(out)
}

pub fn spec_payload_complex_offset(
    header: &T510Header,
    time_idx: usize,
    chan_idx: usize,
    input: usize,
) -> Result<usize, String> {
    let time_count = header.time_count as usize;
    let chan_count = header.chan_count as usize;
    let ninput = header.ninput as usize;
    if time_idx >= time_count {
        return Err("time_idx out of range for SPEC payload".to_string());
    }
    if chan_idx >= chan_count {
        return Err("chan_idx out of range for SPEC payload".to_string());
    }
    if input >= ninput {
        return Err("input out of range for SPEC payload".to_string());
    }
    Ok(HEADER_BYTES + (((time_idx * chan_count + chan_idx) * ninput + input) * 4))
}

pub fn decode_spectrum_snapshot(
    udp_payload: &[u8],
    header: &T510Header,
    src_port: u16,
    dst_port: u16,
    gap_before: bool,
) -> Result<SpectrumSnapshot, String> {
    validate_spec_header(header, udp_payload.len())?;
    let chan_count = header.chan_count as usize;
    let time_count = header.time_count as usize;
    let ninput = header.ninput as usize;
    let mut lanes = Vec::with_capacity(ninput);
    for input in 0..ninput {
        let mut amplitude = Vec::with_capacity(chan_count);
        let mut phase_rad = Vec::with_capacity(chan_count);
        let mut power_db = Vec::with_capacity(chan_count);
        for chan_idx in 0..chan_count {
            let mut sum_i = 0.0f64;
            let mut sum_q = 0.0f64;
            let mut sum_power = 0.0f64;
            for time_idx in 0..time_count {
                let offset = spec_payload_complex_offset(header, time_idx, chan_idx, input)?;
                if offset + 4 > udp_payload.len() {
                    return Err("truncated payload while decoding SPEC".to_string());
                }
                let i = i16::from_le_bytes([udp_payload[offset], udp_payload[offset + 1]]) as f64;
                let q = i16::from_le_bytes([udp_payload[offset + 2], udp_payload[offset + 3]]) as f64;
                sum_i += i;
                sum_q += q;
                sum_power += i * i + q * q;
            }
            let denom = time_count.max(1) as f64;
            let avg_i = sum_i / denom;
            let avg_q = sum_q / denom;
            let avg_power = (sum_power / denom).max(1.0);
            amplitude.push((avg_i.hypot(avg_q)) as f32);
            phase_rad.push(avg_q.atan2(avg_i) as f32);
            power_db.push((10.0 * avg_power.log10()) as f32);
        }
        lanes.push(SpectrumLane {
            input,
            amplitude,
            phase_rad,
            power_db,
        });
    }

    Ok(SpectrumSnapshot {
        sample0: header.sample0,
        seq_no: header.seq_no,
        frame_id: header.frame_id,
        chan0: header.chan0,
        chan_count: header.chan_count,
        time_count: header.time_count,
        ninput: header.ninput,
        product_id: header.product_id,
        nchan: header.nchan,
        block_index: header.block_index,
        block_count: header.block_count,
        pfb_taps: header.pfb_taps,
        fft_shift: header.fft_shift,
        spec_status_flags: header.spec_status_flags,
        spec_sample_rate_hz: header.spec_sample_rate_hz,
        coverage_blocks: 1,
        coverage_mask_lo: if header.block_index < 64 {
            1u64 << header.block_index
        } else {
            0
        },
        coverage_mask_hi: if header.block_index >= 64 && header.block_index < 128 {
            1u64 << (header.block_index - 64)
        } else {
            0
        },
        src_port,
        dst_port,
        gap_before,
        lanes,
    })
}

pub fn ethernet_ipv4_udp_payload<'a>(frame: &'a [u8], dst_port_filter: u16) -> Result<&'a [u8], String> {
    if frame.len() < 42 {
        return Err("frame too short for Ethernet/IPv4/UDP".to_string());
    }
    if u16::from_be_bytes([frame[12], frame[13]]) != 0x0800 {
        return Err("non-IPv4 Ethernet frame".to_string());
    }
    let version = frame[14] >> 4;
    let ihl = (frame[14] & 0x0f) as usize;
    if version != 4 || ihl < 5 {
        return Err("unsupported IPv4 header".to_string());
    }
    let ip_header_bytes = ihl * 4;
    if frame.len() < 14 + ip_header_bytes + 8 {
        return Err("truncated IPv4/UDP frame".to_string());
    }
    if frame[23] != 17 {
        return Err("non-UDP IPv4 packet".to_string());
    }
    let udp = 14 + ip_header_bytes;
    let dst_port = u16::from_be_bytes([frame[udp + 2], frame[udp + 3]]);
    if dst_port != dst_port_filter {
        return Err("UDP dst port does not match".to_string());
    }
    let udp_len = u16::from_be_bytes([frame[udp + 4], frame[udp + 5]]) as usize;
    if udp_len < 8 || frame.len() < udp + udp_len {
        return Err("truncated UDP payload".to_string());
    }
    Ok(&frame[udp + 8..udp + udp_len])
}

pub fn ethernet_ipv4_udp_payload_fast(frame: &[u8], dst_port_filter: u16) -> Result<&[u8], FastPacketError> {
    ethernet_ipv4_udp_payload_range_fast(frame, dst_port_filter, 1).map(|view| view.payload)
}

pub fn ethernet_ipv4_udp_payload_range_fast(
    frame: &[u8],
    dst_port_base: u16,
    dst_port_count: u16,
) -> Result<UdpPayloadView<'_>, FastPacketError> {
    if frame.len() < 42 {
        return Err(FastPacketError::FrameTooShort);
    }
    if u16::from_be_bytes([frame[12], frame[13]]) != 0x0800 {
        return Err(FastPacketError::NonIpv4Ethernet);
    }
    let version = frame[14] >> 4;
    let ihl = (frame[14] & 0x0f) as usize;
    if version != 4 || ihl < 5 {
        return Err(FastPacketError::UnsupportedIpv4Header);
    }
    let ip_header_bytes = ihl * 4;
    if frame.len() < 14 + ip_header_bytes + 8 {
        return Err(FastPacketError::TruncatedIpv4Udp);
    }
    if frame[23] != 17 {
        return Err(FastPacketError::NonUdpIpv4);
    }
    let udp = 14 + ip_header_bytes;
    let src_port = u16::from_be_bytes([frame[udp], frame[udp + 1]]);
    let dst_port = u16::from_be_bytes([frame[udp + 2], frame[udp + 3]]);
    let port_count = dst_port_count.max(1);
    let dst_port_end = dst_port_base.saturating_add(port_count - 1);
    if dst_port < dst_port_base || dst_port > dst_port_end {
        return Err(FastPacketError::WrongUdpDstPort);
    }
    let udp_len = u16::from_be_bytes([frame[udp + 4], frame[udp + 5]]) as usize;
    if udp_len < 8 || frame.len() < udp + udp_len {
        return Err(FastPacketError::BadUdpLength);
    }
    Ok(UdpPayloadView {
        payload: &frame[udp + 8..udp + udp_len],
        src_port,
        dst_port,
    })
}

pub fn build_waveform(
    udp_payload: &[u8],
    header: &T510Header,
    config: &DisplayConfig,
    detected_bandwidth: Option<BandwidthMode>,
    gap_before: bool,
) -> Result<WaveformSnapshot, String> {
    let selected_bandwidth = config.bandwidth_mode();
    let waveform_bandwidth = detected_bandwidth.unwrap_or(selected_bandwidth);
        let projection_hz = waveform_carrier_hz(config);
    let expected_hz = config.target_hz(0);
    let center_hz = config.center_mhz * 1_000_000.0;
    let expected_baseband_hz = expected_hz - center_hz;
    let display_points = config.display_points.clamp(64, 16384);
    let mut channels = Vec::new();
    for channel in 0..TIME_NINPUT {
        if (config.channel_mask & (1u16 << channel)) == 0 {
            continue;
        }
        let samples = decode_channel_samples(udp_payload, header, waveform_bandwidth, channel)?;
        let stride = (samples.len().max(1) + display_points - 1) / display_points;
        let mut x_us = Vec::new();
        let mut i_values = Vec::new();
        let mut q_values = Vec::new();
        let mut mag_values = Vec::new();
        let mut sample_rf_values = Vec::new();
        let mut rf_values = Vec::new();
        let mut y = Vec::new();
        let mut sum_sq = 0.0f64;
        let mut max_abs: i16 = 0;
        for (idx, sample) in samples.iter().enumerate() {
            let abs_i = sample.i.saturating_abs();
            let abs_q = sample.q.saturating_abs();
            max_abs = max_abs.max(abs_i).max(abs_q);
            sum_sq += sample.i as f64 * sample.i as f64 + sample.q as f64 * sample.q as f64;
            if idx % stride == 0 {
                let theta = 2.0 * std::f64::consts::PI * projection_hz * sample.sample_index as f64 / RAW_SAMPLE_RATE_HZ;
                let rf = sample.i as f64 * theta.cos() - sample.q as f64 * theta.sin();
                let t_us = (sample.sample_index.saturating_sub(header.sample0)) as f64 / RAW_SAMPLE_RATE_HZ * 1_000_000.0;
                let scale = config.vertical_scale.max(1.0);
                x_us.push(t_us as f32);
                i_values.push((sample.i as f64 / scale) as f32);
                q_values.push((sample.q as f64 / scale) as f32);
                mag_values.push(((sample.i as f64).hypot(sample.q as f64) / scale) as f32);
                sample_rf_values.push((rf / scale) as f32);
                rf_values.push((rf / scale) as f32);
                y.push((rf / scale) as f32);
            }
        }
        let rms = if samples.is_empty() {
            0.0
        } else {
            (sum_sq / samples.len() as f64).sqrt() as f32
        };
        channels.push(ChannelWaveform {
            channel,
            x_us: x_us.clone(),
            i: i_values,
            q: q_values,
            mag: mag_values,
            sample_rf: sample_rf_values,
            rf_x_us: x_us,
            rf: rf_values,
            y,
            rms_code: rms,
            max_abs_code: max_abs,
            clipped: max_abs >= 32760,
        });
    }
    Ok(WaveformSnapshot {
        sample0: header.sample0,
        seq_no: header.seq_no,
        frame_id: header.frame_id,
        selected_bandwidth_mhz: selected_bandwidth.mhz(),
        detected_bandwidth_mhz: detected_bandwidth.map(|mode| mode.mhz()),
        decimation: waveform_bandwidth.decimation(),
        sample_rate_hz: waveform_bandwidth.sample_rate_hz(),
        requested_window_us: config.time_window_us.max(0.0),
        captured_window_us: channels
            .first()
            .and_then(|channel| channel.x_us.last())
            .copied()
            .unwrap_or(0.0) as f64,
        center_mhz: config.center_mhz,
        expected_mhz: expected_hz / 1_000_000.0,
        dac_mhz: config.dac_mhz,
        expected_baseband_mhz: expected_baseband_hz / 1_000_000.0,
        rf_samples_per_cycle: samples_per_cycle(waveform_bandwidth.sample_rate_hz(), expected_hz),
        baseband_samples_per_cycle: samples_per_cycle(waveform_bandwidth.sample_rate_hz(), expected_baseband_hz),
        rf_window_cycles: expected_hz.abs() * config.time_window_us.max(0.0) * 1.0e-6,
        gap_before,
        channels,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn push_word(out: &mut Vec<u8>, word: u64) {
        out.extend_from_slice(&word.to_le_bytes());
    }

    fn synthetic_payload(time_count: u16, seq: u32, sample0: u64) -> Vec<u8> {
        let mut out = Vec::new();
        push_word(&mut out, ((MAGIC as u64) << 32) | (2u64 << 16) | HEADER_BYTES as u64);
        push_word(&mut out, (37u64 << 48) | (1u64 << 32) | (1u64 << 16) | 0x0006);
        push_word(&mut out, 0);
        push_word(&mut out, 7);
        push_word(&mut out, sample0);
        push_word(&mut out, seq as u64);
        push_word(&mut out, ((seq as u64) << 32) | 0x0055);
        push_word(
            &mut out,
            ((time_count as u64) << 32) | ((TIME_NINPUT as u64) << 16) | PAYLOAD_FORMAT_INT16_IQ as u64,
        );
        push_word(&mut out, TIME_PAYLOAD_BYTES as u64);
        for _ in 9..15 {
            push_word(&mut out, 0);
        }
        push_word(&mut out, 0);
        out.resize(TIME_UDP_PAYLOAD_BYTES, 0);
        for beat in 0..time_count as usize {
            for sub in 0..TIME_SUBSAMPLES_PER_BEAT {
                for ch in 0..TIME_NINPUT {
                    let offset = time_payload_complex_offset(beat, sub, ch).unwrap();
                    let value = (beat as i16) * 100 + (sub as i16) * 10 + ch as i16;
                    out[offset..offset + 2].copy_from_slice(&value.to_le_bytes());
                    out[offset + 2..offset + 4].copy_from_slice(&(-value).to_le_bytes());
                }
            }
        }
        out
    }

    fn synthetic_ethernet_frame(udp_payload: &[u8], dst_port: u16) -> Vec<u8> {
        let ip_total_len = 20 + 8 + udp_payload.len();
        let udp_len = 8 + udp_payload.len();
        assert!(ip_total_len <= u16::MAX as usize);
        let mut frame = Vec::with_capacity(14 + ip_total_len);
        frame.extend_from_slice(&[0x08, 0xc0, 0xeb, 0xd5, 0x95, 0xb2]);
        frame.extend_from_slice(&[0x02, 0x00, 0x00, 0x00, 0x00, 0x01]);
        frame.extend_from_slice(&0x0800u16.to_be_bytes());
        frame.push(0x45);
        frame.push(0);
        frame.extend_from_slice(&(ip_total_len as u16).to_be_bytes());
        frame.extend_from_slice(&0u16.to_be_bytes());
        frame.extend_from_slice(&0u16.to_be_bytes());
        frame.push(64);
        frame.push(17);
        frame.extend_from_slice(&0u16.to_be_bytes());
        frame.extend_from_slice(&[10, 0, 1, 1]);
        frame.extend_from_slice(&[10, 0, 1, 16]);
        frame.extend_from_slice(&4000u16.to_be_bytes());
        frame.extend_from_slice(&dst_port.to_be_bytes());
        frame.extend_from_slice(&(udp_len as u16).to_be_bytes());
        frame.extend_from_slice(&0u16.to_be_bytes());
        frame.extend_from_slice(udp_payload);
        frame
    }

    #[test]
    fn parses_axis_order_header() {
        let payload = synthetic_payload(64, 12, 1000);
        let header = parse_t510_header(&payload).unwrap();
        assert_eq!(header.magic, MAGIC);
        assert_eq!(header.version, 2);
        assert_eq!(header.board_id, 37);
        assert_eq!(header.stream_type, STREAM_TIME);
        assert_eq!(header.time_count, 64);
        assert_eq!(header.ninput, 8);
        assert_eq!(header.payload_bytes as usize, TIME_PAYLOAD_BYTES);
    }

    #[test]
    fn decodes_payload_byte_offsets() {
        let payload = synthetic_payload(64, 12, 1000);
        let header = parse_t510_header(&payload).unwrap();
        let ch3 = decode_channel_samples(&payload, &header, BandwidthMode::Mhz100, 3).unwrap();
        assert_eq!(ch3.len(), 256);
        assert_eq!(ch3[0], DecodedSample { sample_index: 1000, i: 3, q: -3 });
        assert_eq!(ch3[1], DecodedSample { sample_index: 1002, i: 13, q: -13 });
        assert_eq!(ch3[4], DecodedSample { sample_index: 1008, i: 103, q: -103 });
    }

    #[test]
    fn detects_bandwidth_from_sample_delta() {
        let payload = synthetic_payload(64, 12, 1000);
        let header = parse_t510_header(&payload).unwrap();
        assert_eq!(expected_sample0_delta(&header, BandwidthMode::Mhz200), 256);
        assert_eq!(infer_bandwidth_from_sample0_delta(&header, 256), Some(BandwidthMode::Mhz200));
        assert_eq!(infer_bandwidth_from_sample0_delta(&header, 512), Some(BandwidthMode::Mhz100));
        assert_eq!(infer_bandwidth_from_sample0_delta(&header, 2048), Some(BandwidthMode::Mhz20));
        assert_eq!(infer_bandwidth_from_sample0_delta(&header, 123), None);
    }

    #[test]
    fn detected_bandwidth_drives_preview_time_axis_when_available() {
        let payload = synthetic_payload(64, 12, 1000);
        let header = parse_t510_header(&payload).unwrap();
        let ch0_200 = decode_channel_samples(&payload, &header, BandwidthMode::Mhz200, 0).unwrap();
        let ch0_20 = decode_channel_samples(&payload, &header, BandwidthMode::Mhz20, 0).unwrap();
        assert_eq!(ch0_200[1].sample_index - ch0_200[0].sample_index, 1);
        assert_eq!(ch0_20[1].sample_index - ch0_20[0].sample_index, 8);

        let mut config = DisplayConfig::default();
        config.bandwidth_mhz = 20;
        let snapshot = build_waveform(&payload, &header, &config, Some(BandwidthMode::Mhz200), true).unwrap();
        assert_eq!(snapshot.selected_bandwidth_mhz, 20);
        assert_eq!(snapshot.detected_bandwidth_mhz, Some(200));
        assert_eq!(snapshot.decimation, 1);
        assert!(snapshot.gap_before);
    }

    #[test]
    fn fast_parser_filters_ipv4_udp_and_decodes_t510() {
        let payload = synthetic_payload(64, 21, 4096);
        let frame = synthetic_ethernet_frame(&payload, 4300);
        let udp = ethernet_ipv4_udp_payload_fast(&frame, 4300).unwrap();
        assert_eq!(udp.len(), TIME_UDP_PAYLOAD_BYTES);
        let view = ethernet_ipv4_udp_payload_range_fast(&frame, 4300, 8).unwrap();
        assert_eq!(view.src_port, 4000);
        assert_eq!(view.dst_port, 4300);
        assert_eq!(view.payload.len(), TIME_UDP_PAYLOAD_BYTES);
        let header = parse_t510_time_header_fast(udp).unwrap();
        assert_eq!(header.seq_no, 21);
        assert_eq!(header.sample0, 4096);
        assert_eq!(
            ethernet_ipv4_udp_payload_fast(&frame, 4301),
            Err(FastPacketError::WrongUdpDstPort)
        );
    }

    #[test]
    fn fast_parser_rejects_truncated_time_payload() {
        let mut payload = synthetic_payload(64, 21, 4096);
        payload.truncate(HEADER_BYTES + 128);
        assert_eq!(
            parse_t510_time_header_fast(&payload),
            Err(FastPacketError::TruncatedTimePayload)
        );
    }
}
