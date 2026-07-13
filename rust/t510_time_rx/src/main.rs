use clap::{Parser, ValueEnum};
use base64::Engine;
use serde::{Deserialize, Serialize};
use sha1::{Digest, Sha1};
use std::collections::BTreeMap;
use std::ffi::CString;
use std::fs;
use std::io::{Read, Write};
use std::mem;
use std::net::{SocketAddr, TcpListener, TcpStream, UdpSocket};
use std::os::fd::{FromRawFd, RawFd};
use std::ptr;
use std::slice;
use std::sync::atomic::{fence, AtomicU64, AtomicUsize, Ordering};
use std::sync::{mpsc, Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};
use t510_time_rx::{
    ethernet_ipv4_udp_payload_range_fast, expected_sample0_delta, infer_bandwidth_from_sample0_delta,
    parse_t510_header_fast, time_payload_complex_offset, validate_spec_header_fast,
    validate_time_header_fast, BandwidthMode, ChannelWaveform, DisplayConfig, FastPacketError,
    SpectrumLane, SpectrumSnapshot, T510Header, WaveformSnapshot, RAW_SAMPLE_RATE_HZ,
    SPEC_BLOCK_CHANS_27F, SPEC_BLOCK_CHANS_27H, SPEC_BLOCK_COUNT_27F, SPEC_BLOCK_COUNT_27H,
    SPEC_FFT_ONLY_FLAG, SPEC_PFB_ACTIVE_FLAG, SPEC_TIME_COUNT_27F, SPEC_TIME_COUNT_27H, STREAM_SPEC, STREAM_TIME,
    TIME_NINPUT, TIME_SUBSAMPLES_PER_BEAT, TIME_UDP_PAYLOAD_BYTES,
};

const ETH_P_ALL: u16 = 0x0003;
const SOL_PACKET: libc::c_int = 263;
const PACKET_RX_RING: libc::c_int = 5;
const PACKET_STATISTICS: libc::c_int = 6;
const PACKET_VERSION: libc::c_int = 10;
const PACKET_FANOUT: libc::c_int = 18;
const PACKET_FANOUT_DATA: libc::c_int = 22;
const TPACKET_V3: libc::c_int = 2;
const PACKET_FANOUT_HASH: u16 = 0;
const PACKET_FANOUT_CBPF: u16 = 6;
const TP_STATUS_KERNEL: u32 = 0;
const TP_STATUS_USER: u32 = 1;
const SO_ATTACH_FILTER: libc::c_int = 26;
const BPF_LD: u16 = 0x00;
const BPF_ALU: u16 = 0x04;
const BPF_JMP: u16 = 0x05;
const BPF_RET: u16 = 0x06;
const BPF_H: u16 = 0x08;
const BPF_B: u16 = 0x10;
const BPF_ABS: u16 = 0x20;
const BPF_A: u16 = 0x10;
const BPF_K: u16 = 0x00;
const BPF_JEQ: u16 = 0x10;
const BPF_JGT: u16 = 0x20;
const BPF_JGE: u16 = 0x30;
const BPF_SUB: u16 = 0x10;
const BPF_MOD: u16 = 0x90;
const MIB: usize = 1024 * 1024;
const DEFAULT_TIME_COUNT: u16 = 64;
const DEFAULT_FRAME_SIZE: usize = 16 * 1024;
const WEBSOCKET_GUID: &str = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11";
const WAVEFORM_MAGIC: u32 = 0x3557_4654; // "TFW5" little-endian on the wire.
const WAVEFORM_BINARY_VERSION: u16 = 5;
const WAVEFORM_BINARY_HEADER_BYTES: u16 = 160;
const SPECTRUM_MAGIC: u32 = 0x3350_5354; // "TSP3" little-endian on the wire.
const PREVIEW_STALE_AFTER: Duration = Duration::from_secs(2);
const PREVIEW_LIVE_MIN_RATE_FRACTION: f64 = 0.25;
const PREVIEW_LIVE_MIN_PPS_FLOOR: f64 = 10_000.0;
const SPECTRUM_PREVIEW_COLLECT_TIMEOUT: Duration = Duration::from_millis(500);
const NO_DISPLAY_OWNER: usize = usize::MAX;
const NO_SPECTRUM_FRAME: u64 = u64::MAX;
const SPECTRUM_PREVIEW_GROUP_LEAD: u64 = 4096;
const DEFAULT_FLOW_COUNT_27H: usize = 24;
const DEFAULT_TIME_FLOW_COUNT_27H: usize = 8;
const DEFAULT_SPEC_FLOW_COUNT_27H: usize = 16;
const MAX_SPEC_FLOW_COUNT_27G: usize = 64;
const MAX_FLOW_COUNT_27H: usize = 72;
const MAX_WORKER_COUNT_27H: usize = 64;

#[derive(Debug, Clone, ValueEnum)]
enum Backend {
    Fanout,
    Mmap,
    Packet,
    Udp,
}

#[derive(Debug, Clone, Copy, ValueEnum, PartialEq, Eq)]
enum FanoutMode {
    Hash,
    Port,
}

impl FanoutMode {
    fn packet_type(self) -> u16 {
        match self {
            Self::Hash => PACKET_FANOUT_HASH,
            Self::Port => PACKET_FANOUT_CBPF,
        }
    }
}

#[derive(Debug, Clone, Copy, ValueEnum, PartialEq, Eq)]
enum PinWorkers {
    Auto,
    Off,
}

#[derive(Debug, Clone, Copy, ValueEnum, PartialEq, Eq)]
enum SpecLayout {
    Auto,
    Stage27g,
    Stage27h,
    Stage27j,
}

impl SpecLayout {
    fn label(self) -> &'static str {
        match self {
            Self::Auto => "auto",
            Self::Stage27g => "27g",
            Self::Stage27h => "27h",
            Self::Stage27j => "27j",
        }
    }

    fn matches(self, header: &T510Header) -> bool {
        match self {
            Self::Auto => true,
            Self::Stage27g => {
                header.block_count == SPEC_BLOCK_COUNT_27F
                    && header.chan_count == SPEC_BLOCK_CHANS_27F
                    && header.time_count == SPEC_TIME_COUNT_27F
                    && header.pfb_taps >= 4
            }
            Self::Stage27h => {
                header.block_count == SPEC_BLOCK_COUNT_27H
                    && header.chan_count == SPEC_BLOCK_CHANS_27H
                    && header.time_count == SPEC_TIME_COUNT_27H
                    && header.pfb_taps == 0
                    && (header.spec_status_flags & SPEC_FFT_ONLY_FLAG) != 0
            }
            Self::Stage27j => {
                header.block_count == SPEC_BLOCK_COUNT_27H
                    && header.chan_count == SPEC_BLOCK_CHANS_27H
                    && header.time_count == SPEC_TIME_COUNT_27H
                    && header.pfb_taps >= 4
                    && (header.spec_status_flags & SPEC_FFT_ONLY_FLAG) == 0
                    && (header.spec_status_flags & SPEC_PFB_ACTIVE_FLAG) != 0
            }
        }
    }
}

fn parse_u16_auto(value: &str) -> Result<u16, String> {
    let trimmed = value.trim();
    if let Some(hex) = trimmed.strip_prefix("0x").or_else(|| trimmed.strip_prefix("0X")) {
        u16::from_str_radix(hex, 16).map_err(|err| err.to_string())
    } else {
        trimmed.parse::<u16>().map_err(|err| err.to_string())
    }
}

#[derive(Debug, Parser, Clone)]
#[command(
    author,
    version,
    about = "T510 Stage 29 TIME/SPEC receiver and production F-engine preview"
)]
struct Args {
    #[arg(long, default_value = "ens2f0np0")]
    interface: String,
    #[arg(long, default_value_t = 4300)]
    port: u16,
    #[arg(long)]
    dst_port_base: Option<u16>,
    #[arg(long, default_value_t = 4000)]
    src_port_base: u16,
    #[arg(long, default_value_t = DEFAULT_FLOW_COUNT_27H)]
    flow_count: usize,
    #[arg(long, default_value_t = DEFAULT_TIME_FLOW_COUNT_27H)]
    time_flow_count: usize,
    #[arg(long, default_value_t = DEFAULT_SPEC_FLOW_COUNT_27H)]
    spec_flow_count: usize,
    #[arg(long, default_value_t = 8192)]
    reorder_window: u32,
    #[arg(long, default_value_t = 30)]
    web_fps: u32,
    #[arg(long, default_value_t = 1024)]
    waveform_points: usize,
    #[arg(long, default_value_t = 16384)]
    waveform_max_points: usize,
    #[arg(long, default_value = "127.0.0.1:8088")]
    web: String,
    #[arg(long, default_value_t = 100)]
    initial_bandwidth_mhz: u32,
    #[arg(long, value_enum, default_value_t = Backend::Mmap)]
    backend: Backend,
    #[arg(long, default_value_t = 32)]
    worker_count: usize,
    #[arg(long, value_parser = parse_u16_auto, default_value = "0x27d")]
    fanout_group: u16,
    #[arg(long, value_enum, default_value_t = FanoutMode::Port)]
    fanout_mode: FanoutMode,
    #[arg(long, value_enum, default_value_t = PinWorkers::Auto)]
    pin_workers: PinWorkers,
    #[arg(long, value_enum, default_value_t = SpecLayout::Stage27h)]
    spec_layout: SpecLayout,
    #[arg(long, default_value_t = 512)]
    ring_mb: usize,
    #[arg(long, default_value_t = 4)]
    block_mb: usize,
    #[arg(long, default_value_t = 0)]
    block_count: usize,
    #[arg(long, default_value_t = DEFAULT_FRAME_SIZE / 1024)]
    frame_kb: usize,
    #[arg(long, default_value_t = 4096)]
    batch_size: usize,
    #[arg(long, default_value_t = 10)]
    poll_timeout_ms: i32,
}

impl Args {
    fn dst_port_base(&self) -> u16 {
        self.dst_port_base.unwrap_or(self.port)
    }

    fn flow_count_clamped(&self) -> usize {
        self.flow_count.clamp(1, MAX_FLOW_COUNT_27H)
    }

    fn time_flow_count_clamped(&self) -> usize {
        self.time_flow_count.min(self.flow_count_clamped().min(8))
    }

    fn spec_flow_count_clamped(&self) -> usize {
        let max_spec = match self.spec_layout {
            SpecLayout::Stage27h | SpecLayout::Stage27j => DEFAULT_SPEC_FLOW_COUNT_27H,
            SpecLayout::Auto | SpecLayout::Stage27g => MAX_SPEC_FLOW_COUNT_27G,
        };
        self.spec_flow_count
            .min(max_spec)
            .min(self.flow_count_clamped().saturating_sub(self.time_flow_count_clamped()))
    }

    fn worker_count_clamped(&self) -> usize {
        self.worker_count.clamp(1, MAX_WORKER_COUNT_27H)
    }

    fn waveform_points_clamped(&self) -> usize {
        self.waveform_points
            .clamp(1024, self.waveform_max_points.clamp(1024, 16384))
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct FlowStats {
    flow_id: usize,
    dst_port: u16,
    src_port: u16,
    time_packets: u64,
    time_bytes: u64,
    spec_packets: u64,
    spec_bytes: u64,
    packets_per_sec: f64,
    gbps: f64,
    seq_gaps: u64,
    frame_gaps: u64,
    sample0_gaps: u64,
    spec_seq_gaps: u64,
    spec_frame_gaps: u64,
    detected_bandwidth_mhz: Option<u32>,
    last_seq_no: Option<u32>,
    last_frame_id: Option<u64>,
    last_sample0: Option<u64>,
    last_spec_seq_no: Option<u32>,
    last_spec_frame_id: Option<u64>,
    last_spec_sample0: Option<u64>,
    last_spec_chan0: Option<u32>,
    last_spec_chan_count: Option<u16>,
}

impl FlowStats {
    fn new(flow_id: usize, dst_port: u16, src_port: u16) -> Self {
        Self {
            flow_id,
            dst_port,
            src_port,
            time_packets: 0,
            time_bytes: 0,
            spec_packets: 0,
            spec_bytes: 0,
            packets_per_sec: 0.0,
            gbps: 0.0,
            seq_gaps: 0,
            frame_gaps: 0,
            sample0_gaps: 0,
            spec_seq_gaps: 0,
            spec_frame_gaps: 0,
            detected_bandwidth_mhz: None,
            last_seq_no: None,
            last_frame_id: None,
            last_sample0: None,
            last_spec_seq_no: None,
            last_spec_frame_id: None,
            last_spec_sample0: None,
            last_spec_chan0: None,
            last_spec_chan_count: None,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct WorkerStats {
    worker_id: usize,
    total_packets: u64,
    time_packets: u64,
    spec_packets: u64,
    total_bytes: u64,
    time_bytes: u64,
    spec_bytes: u64,
    parse_errors: u64,
    filtered_packets: u64,
    kernel_drops: u64,
    ring_drops: u64,
    app_drops: u64,
    seq_gaps: u64,
    frame_gaps: u64,
    sample0_gaps: u64,
    spec_seq_gaps: u64,
    spec_frame_gaps: u64,
    waveform_updates: u64,
    spectrum_updates: u64,
    packets_per_sec: f64,
    gbps: f64,
    rx_processed_packets_per_sec: f64,
    rx_processed_gbps: f64,
    spec_processed_packets_per_sec: f64,
    spec_processed_gbps: f64,
    display_update_hz: f64,
    spectrum_update_hz: f64,
    ring_fill_blocks: u32,
    ring_fill_percent: f64,
    ring_freeze_q_count: u64,
    last_seq_no: Option<u32>,
    last_frame_id: Option<u64>,
    last_sample0: Option<u64>,
    last_time_count: Option<u16>,
    last_spec_seq_no: Option<u32>,
    last_spec_frame_id: Option<u64>,
    last_spec_sample0: Option<u64>,
    last_spec_chan0: Option<u32>,
    last_spec_chan_count: Option<u16>,
    detected_bandwidth_mhz: Option<u32>,
    last_error: Option<String>,
}

impl WorkerStats {
    fn new(worker_id: usize) -> Self {
        Self {
            worker_id,
            total_packets: 0,
            time_packets: 0,
            spec_packets: 0,
            total_bytes: 0,
            time_bytes: 0,
            spec_bytes: 0,
            parse_errors: 0,
            filtered_packets: 0,
            kernel_drops: 0,
            ring_drops: 0,
            app_drops: 0,
            seq_gaps: 0,
            frame_gaps: 0,
            sample0_gaps: 0,
            spec_seq_gaps: 0,
            spec_frame_gaps: 0,
            waveform_updates: 0,
            spectrum_updates: 0,
            packets_per_sec: 0.0,
            gbps: 0.0,
            rx_processed_packets_per_sec: 0.0,
            rx_processed_gbps: 0.0,
            spec_processed_packets_per_sec: 0.0,
            spec_processed_gbps: 0.0,
            display_update_hz: 0.0,
            spectrum_update_hz: 0.0,
            ring_fill_blocks: 0,
            ring_fill_percent: 0.0,
            ring_freeze_q_count: 0,
            last_seq_no: None,
            last_frame_id: None,
            last_sample0: None,
            last_time_count: None,
            last_spec_seq_no: None,
            last_spec_frame_id: None,
            last_spec_sample0: None,
            last_spec_chan0: None,
            last_spec_chan_count: None,
            detected_bandwidth_mhz: None,
            last_error: None,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct ReceiverStats {
    started_unix_ms: u128,
    backend: String,
    interface: String,
    port: u16,
    dst_port_base: u16,
    src_port_base: u16,
    flow_count: usize,
    time_flow_count: usize,
    spec_flow_count: usize,
    active_flow_count: usize,
    active_time_flow_count: usize,
    active_spec_flow_count: usize,
    spec_layout: String,
    worker_count: usize,
    active_worker_count: usize,
    fanout_group: u16,
    fanout_mode: String,
    total_packets: u64,
    time_packets: u64,
    spec_packets: u64,
    total_bytes: u64,
    time_bytes: u64,
    spec_bytes: u64,
    parse_errors: u64,
    filtered_packets: u64,
    kernel_drops: u64,
    ring_drops: u64,
    app_drops: u64,
    seq_gaps: u64,
    frame_gaps: u64,
    sample0_gaps: u64,
    spec_seq_gaps: u64,
    spec_frame_gaps: u64,
    waveform_updates: u64,
    spectrum_updates: u64,
    websocket_clients: u64,
    waveform_websocket_clients: u64,
    spectrum_websocket_clients: u64,
    packets_per_sec: f64,
    gbps: f64,
    expected_packets_per_sec: f64,
    expected_fpga_gbps: f64,
    expected_time_gbps: f64,
    expected_spec_gbps: f64,
    rx_processed_packets_per_sec: f64,
    rx_processed_gbps: f64,
    spec_processed_packets_per_sec: f64,
    spec_processed_gbps: f64,
    display_update_hz: f64,
    spectrum_update_hz: f64,
    loss_percent: f64,
    ring_bytes: u64,
    ring_block_size: u32,
    ring_block_count: u32,
    ring_frame_size: u32,
    ring_frame_count: u32,
    ring_fill_blocks: u32,
    ring_fill_percent: f64,
    ring_freeze_q_count: u64,
    nic_rx_packets_per_sec: f64,
    nic_rx_gbps: f64,
    nic_rx_dropped_delta: u64,
    nic_rx_errors_delta: u64,
    nic_rx_missed_errors_delta: u64,
    nic_rx_crc_errors_delta: u64,
    worker_ring_drops: u64,
    last_seq_no: Option<u32>,
    last_frame_id: Option<u64>,
    last_sample0: Option<u64>,
    last_time_count: Option<u16>,
    last_spec_seq_no: Option<u32>,
    last_spec_frame_id: Option<u64>,
    last_spec_sample0: Option<u64>,
    last_spec_chan0: Option<u32>,
    last_spec_chan_count: Option<u16>,
    selected_bandwidth_mhz: u32,
    detected_bandwidth_mhz: Option<u32>,
    selected_detected_mismatch: bool,
    channel_rms_code: [f32; TIME_NINPUT],
    channel_max_abs_code: [i16; TIME_NINPUT],
    channel_clipped: [bool; TIME_NINPUT],
    per_flow: Vec<FlowStats>,
    per_worker: Vec<WorkerStats>,
    last_error: Option<String>,
}

impl ReceiverStats {
    fn new(args: &Args) -> Self {
        let started_unix_ms = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_millis();
        Self {
            started_unix_ms,
            backend: format!("{:?}", args.backend).to_lowercase(),
            interface: args.interface.clone(),
            port: args.dst_port_base(),
            dst_port_base: args.dst_port_base(),
            src_port_base: args.src_port_base,
            flow_count: args.flow_count_clamped(),
            time_flow_count: args.time_flow_count_clamped(),
            spec_flow_count: args.spec_flow_count_clamped(),
            active_flow_count: args.flow_count_clamped(),
            active_time_flow_count: args.time_flow_count_clamped(),
            active_spec_flow_count: args.spec_flow_count_clamped(),
            spec_layout: args.spec_layout.label().to_string(),
            worker_count: args.worker_count_clamped(),
            active_worker_count: 0,
            fanout_group: args.fanout_group,
            fanout_mode: format!("{:?}", args.fanout_mode).to_lowercase(),
            total_packets: 0,
            time_packets: 0,
            spec_packets: 0,
            total_bytes: 0,
            time_bytes: 0,
            spec_bytes: 0,
            parse_errors: 0,
            filtered_packets: 0,
            kernel_drops: 0,
            ring_drops: 0,
            app_drops: 0,
            seq_gaps: 0,
            frame_gaps: 0,
            sample0_gaps: 0,
            spec_seq_gaps: 0,
            spec_frame_gaps: 0,
            waveform_updates: 0,
            spectrum_updates: 0,
            websocket_clients: 0,
            waveform_websocket_clients: 0,
            spectrum_websocket_clients: 0,
            packets_per_sec: 0.0,
            gbps: 0.0,
            expected_packets_per_sec: 0.0,
            expected_fpga_gbps: 0.0,
            expected_time_gbps: 0.0,
            expected_spec_gbps: 0.0,
            rx_processed_packets_per_sec: 0.0,
            rx_processed_gbps: 0.0,
            spec_processed_packets_per_sec: 0.0,
            spec_processed_gbps: 0.0,
            display_update_hz: 0.0,
            spectrum_update_hz: 0.0,
            loss_percent: 0.0,
            ring_bytes: 0,
            ring_block_size: 0,
            ring_block_count: 0,
            ring_frame_size: 0,
            ring_frame_count: 0,
            ring_fill_blocks: 0,
            ring_fill_percent: 0.0,
            ring_freeze_q_count: 0,
            nic_rx_packets_per_sec: 0.0,
            nic_rx_gbps: 0.0,
            nic_rx_dropped_delta: 0,
            nic_rx_errors_delta: 0,
            nic_rx_missed_errors_delta: 0,
            nic_rx_crc_errors_delta: 0,
            worker_ring_drops: 0,
            last_seq_no: None,
            last_frame_id: None,
            last_sample0: None,
            last_time_count: None,
            last_spec_seq_no: None,
            last_spec_frame_id: None,
            last_spec_sample0: None,
            last_spec_chan0: None,
            last_spec_chan_count: None,
            selected_bandwidth_mhz: BandwidthMode::from_mhz(args.initial_bandwidth_mhz)
                .unwrap_or(BandwidthMode::Mhz100)
                .mhz(),
            detected_bandwidth_mhz: None,
            selected_detected_mismatch: false,
            channel_rms_code: [0.0; TIME_NINPUT],
            channel_max_abs_code: [0; TIME_NINPUT],
            channel_clipped: [false; TIME_NINPUT],
            per_flow: (0..args.flow_count_clamped())
                .map(|flow_id| {
                    FlowStats::new(
                        flow_id,
                        args.dst_port_base().saturating_add(flow_id as u16),
                        args.src_port_base.saturating_add(flow_id as u16),
                    )
                })
                .collect(),
            per_worker: (0..args.worker_count_clamped())
                .map(WorkerStats::new)
                .collect(),
            last_error: None,
        }
    }
}

fn per_flow_detected_consensus(flows: &[FlowStats]) -> Option<u32> {
    let mut consensus = None;
    for flow in flows {
        let Some(mhz) = flow.detected_bandwidth_mhz else {
            continue;
        };
        match consensus {
            Some(prev) if prev != mhz => return None,
            Some(_) => {}
            None => consensus = Some(mhz),
        }
    }
    consensus
}

fn spectrum_preview_enabled(config: &DisplayConfig) -> bool {
    config.needs_spec() && !config.paused
}

#[derive(Debug, Clone, Serialize)]
struct ApiState {
    config: DisplayConfig,
    config_generation: u64,
    stats: ReceiverStats,
    spec_preview: SpecPreviewStatus,
    waveform_live: bool,
    waveform_age_ms: Option<u64>,
    spectrum_live: bool,
    spectrum_age_ms: Option<u64>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct SpecPreviewStatus {
    frame_id: Option<u64>,
    sample0: Option<u64>,
    coverage_blocks: u32,
    block_count: u16,
    complete: bool,
    coverage_mask_lo: u64,
    coverage_mask_hi: u64,
    last_block_index: Option<u16>,
    last_chan0: Option<u32>,
    last_chan_count: Option<u16>,
    last_dst_port: Option<u16>,
    last_error: Option<String>,
}

impl Default for SpecPreviewStatus {
    fn default() -> Self {
        Self {
            frame_id: None,
            sample0: None,
            coverage_blocks: 0,
            block_count: SPEC_BLOCK_COUNT_27H,
            complete: false,
            coverage_mask_lo: 0,
            coverage_mask_hi: 0,
            last_block_index: None,
            last_chan0: None,
            last_chan_count: None,
            last_dst_port: None,
            last_error: None,
        }
    }
}

#[derive(Debug, Clone)]
struct FullSpectrumAssembler {
    sample0: u64,
    seq_no: u32,
    frame_id: u64,
    product_id: u16,
    nchan: u16,
    block_count: u16,
    pfb_taps: u16,
    fft_shift: u16,
    spec_status_flags: u32,
    spec_sample_rate_hz: u32,
    src_port: u16,
    dst_port: u16,
    gap_before: bool,
    coverage_mask_lo: u64,
    coverage_mask_hi: u64,
    lanes: Vec<SpectrumLane>,
}

impl Default for FullSpectrumAssembler {
    fn default() -> Self {
        Self {
            sample0: 0,
            seq_no: 0,
            frame_id: 0,
            product_id: 0,
            nchan: 4096,
            block_count: SPEC_BLOCK_COUNT_27H,
            pfb_taps: 0,
            fft_shift: 0,
            spec_status_flags: 0,
            spec_sample_rate_hz: 0,
            src_port: 0,
            dst_port: 0,
            gap_before: false,
            coverage_mask_lo: 0,
            coverage_mask_hi: 0,
            lanes: (0..TIME_NINPUT)
                .map(|input| SpectrumLane {
                    input,
                    amplitude: vec![0.0; 4096],
                    phase_rad: vec![0.0; 4096],
                    power_db: vec![-160.0; 4096],
                })
                .collect(),
        }
    }
}

impl FullSpectrumAssembler {
    fn frame_group(frame_id: u64, block_count: u16) -> u64 {
        frame_id / u64::from(block_count.max(1))
    }

    fn reset_for_layout(&mut self, block: &SpectrumSnapshot) {
        self.sample0 = block.sample0;
        self.seq_no = block.seq_no;
        self.frame_id = block.frame_id;
        self.product_id = block.product_id;
        self.nchan = block.nchan;
        self.block_count = block.block_count.max(1);
        self.pfb_taps = block.pfb_taps;
        self.fft_shift = block.fft_shift;
        self.spec_status_flags = block.spec_status_flags;
        self.spec_sample_rate_hz = block.spec_sample_rate_hz;
        self.src_port = block.src_port;
        self.dst_port = block.dst_port;
        self.coverage_mask_lo = 0;
        self.coverage_mask_hi = 0;
        self.gap_before = false;
        if self.lanes.len() != block.lanes.len()
            || self.lanes.first().map(|lane| lane.amplitude.len()).unwrap_or(0) != block.nchan as usize
        {
            self.lanes = (0..block.lanes.len())
                .map(|input| SpectrumLane {
                    input,
                    amplitude: vec![0.0; block.nchan as usize],
                    phase_rad: vec![0.0; block.nchan as usize],
                    power_db: vec![-160.0; block.nchan as usize],
                })
                .collect();
        } else {
            for lane in &mut self.lanes {
                lane.amplitude.fill(0.0);
                lane.phase_rad.fill(0.0);
                lane.power_db.fill(-160.0);
            }
        }
    }

    fn layout_matches(&self, block: &SpectrumSnapshot) -> bool {
        self.product_id == block.product_id
            && Self::frame_group(self.frame_id, self.block_count)
                == Self::frame_group(block.frame_id, block.block_count)
            && self.nchan == block.nchan
            && self.block_count == block.block_count.max(1)
            && self.pfb_taps == block.pfb_taps
            && self.lanes.len() == block.lanes.len()
    }

    fn ingest_block(&mut self, block: &SpectrumSnapshot) {
        if self.product_id == 0 || !self.layout_matches(block) {
            self.reset_for_layout(block);
        }
        self.sample0 = block.sample0;
        self.seq_no = block.seq_no;
        self.frame_id = block.frame_id;
        self.product_id = block.product_id;
        self.nchan = block.nchan;
        self.block_count = block.block_count;
        self.pfb_taps = block.pfb_taps;
        self.fft_shift = block.fft_shift;
        self.spec_status_flags = block.spec_status_flags;
        self.spec_sample_rate_hz = block.spec_sample_rate_hz;
        self.src_port = block.src_port;
        self.dst_port = block.dst_port;
        self.gap_before |= block.gap_before;

        let start = block.chan0 as usize;
        let count = block.chan_count as usize;
        for lane in &block.lanes {
            if let Some(dst) = self.lanes.get_mut(lane.input) {
                let end = (start + count)
                    .min(dst.amplitude.len())
                    .min(start + lane.amplitude.len())
                    .min(start + lane.phase_rad.len())
                    .min(start + lane.power_db.len());
                if start < end {
                    let len = end - start;
                    dst.amplitude[start..end].copy_from_slice(&lane.amplitude[..len]);
                    dst.phase_rad[start..end].copy_from_slice(&lane.phase_rad[..len]);
                    dst.power_db[start..end].copy_from_slice(&lane.power_db[..len]);
                }
            }
        }
        if block.block_index < 64 {
            self.coverage_mask_lo |= 1u64 << block.block_index;
        } else if block.block_index < 128 {
            self.coverage_mask_hi |= 1u64 << (block.block_index - 64);
        }
    }

    fn coverage_blocks(&self) -> u32 {
        self.coverage_mask_lo.count_ones() + self.coverage_mask_hi.count_ones()
    }

    fn update(&mut self, block: &SpectrumSnapshot) -> Option<SpectrumSnapshot> {
        let block_count = block.block_count.max(1).min(128);
        if block.block_index >= block_count {
            return None;
        }
        self.ingest_block(block);
        Some(self.snapshot())
    }

    fn snapshot(&self) -> SpectrumSnapshot {
        SpectrumSnapshot {
            sample0: self.sample0,
            seq_no: self.seq_no,
            frame_id: self.frame_id,
            chan0: 0,
            chan_count: self.nchan,
            time_count: SPEC_TIME_COUNT_27H,
            ninput: self.lanes.len() as u16,
            product_id: self.product_id,
            nchan: self.nchan,
            block_index: 0,
            block_count: self.block_count,
            pfb_taps: self.pfb_taps,
            fft_shift: self.fft_shift,
            spec_status_flags: self.spec_status_flags,
            spec_sample_rate_hz: self.spec_sample_rate_hz,
            coverage_blocks: self.coverage_blocks(),
            coverage_mask_lo: self.coverage_mask_lo,
            coverage_mask_hi: self.coverage_mask_hi,
            src_port: self.src_port,
            dst_port: self.dst_port,
            gap_before: self.gap_before,
            lanes: self.lanes.clone(),
        }
    }
}

#[derive(Debug, Clone)]
struct SpecPreviewCapture {
    active: bool,
    last_publish: Instant,
    decode_window_start: Instant,
    decode_mask_lo: u64,
    decode_mask_hi: u64,
    assembler: FullSpectrumAssembler,
    status: SpecPreviewStatus,
}

impl Default for SpecPreviewCapture {
    fn default() -> Self {
        Self {
            active: false,
            last_publish: Instant::now(),
            decode_window_start: Instant::now(),
            decode_mask_lo: 0,
            decode_mask_hi: 0,
            assembler: FullSpectrumAssembler::default(),
            status: SpecPreviewStatus::default(),
        }
    }
}

impl SpecPreviewCapture {
    fn header_frame_group(header: &T510Header) -> u64 {
        header.frame_id / u64::from(header.block_count.max(1))
    }

    fn block_frame_group(block: &SpectrumSnapshot) -> u64 {
        FullSpectrumAssembler::frame_group(block.frame_id, block.block_count)
    }

    fn arm_block(&mut self, block: &SpectrumSnapshot) {
        self.active = true;
        self.decode_window_start = Instant::now();
        self.decode_mask_lo = 0;
        self.decode_mask_hi = 0;
        self.status = SpecPreviewStatus {
            frame_id: Some(block.frame_id),
            sample0: Some(block.sample0),
            block_count: block.block_count.max(1),
            last_block_index: Some(block.block_index),
            last_chan0: Some(block.chan0),
            last_chan_count: Some(block.chan_count),
            last_dst_port: Some(block.dst_port),
            ..SpecPreviewStatus::default()
        };
    }

    fn arm_frame(&mut self, header: &T510Header) {
        self.active = true;
        self.decode_window_start = Instant::now();
        self.decode_mask_lo = 0;
        self.decode_mask_hi = 0;
        self.status = SpecPreviewStatus {
            frame_id: Some(header.frame_id),
            sample0: Some(header.sample0),
            block_count: header.block_count.max(1),
            last_block_index: Some(header.block_index),
            last_chan0: Some(header.chan0),
            last_chan_count: Some(header.chan_count),
            ..SpecPreviewStatus::default()
        };
    }

    fn should_decode(&mut self, header: &T510Header, interval: Duration) -> bool {
        let new_frame = self
            .status
            .frame_id
            .map(|frame_id| frame_id / u64::from(header.block_count.max(1)) != Self::header_frame_group(header))
            .unwrap_or(true);
        if !self.active || new_frame {
            self.arm_frame(header);
        }
        let block_count = header.block_count.max(1).min(128);
        if header.block_index >= block_count {
            return false;
        }
        if self.decode_window_start.elapsed() >= interval.max(Duration::from_millis(1)) {
            self.decode_window_start = Instant::now();
            self.decode_mask_lo = 0;
            self.decode_mask_hi = 0;
        }
        if header.block_index < 64 {
            let bit = 1u64 << header.block_index;
            if self.decode_mask_lo & bit != 0 {
                return false;
            }
            self.decode_mask_lo |= bit;
        } else {
            let bit = 1u64 << (header.block_index - 64);
            if self.decode_mask_hi & bit != 0 {
                return false;
            }
            self.decode_mask_hi |= bit;
        }
        true
    }

    fn ingest(&mut self, block: &SpectrumSnapshot, interval: Duration) -> Option<SpectrumSnapshot> {
        let new_frame = self
            .status
            .frame_id
            .map(|frame_id| {
                FullSpectrumAssembler::frame_group(frame_id, block.block_count) != Self::block_frame_group(block)
            })
            .unwrap_or(true);
        if !self.active || new_frame {
            self.arm_block(block);
        }
        let block_count = block.block_count.max(1);
        let snapshot = self.assembler.update(block)?;
        let complete = snapshot.coverage_blocks >= u32::from(block_count);
        let was_complete = self.status.complete;
        self.status = SpecPreviewStatus {
            frame_id: Some(snapshot.frame_id),
            sample0: Some(snapshot.sample0),
            coverage_blocks: snapshot.coverage_blocks,
            block_count,
            complete,
            coverage_mask_lo: snapshot.coverage_mask_lo,
            coverage_mask_hi: snapshot.coverage_mask_hi,
            last_block_index: Some(block.block_index),
            last_chan0: Some(block.chan0),
            last_chan_count: Some(block.chan_count),
            last_dst_port: Some(block.dst_port),
            last_error: None,
        };
        if complete && (!was_complete || self.last_publish.elapsed() >= interval.max(Duration::from_millis(1))) {
            self.last_publish = Instant::now();
            Some(snapshot)
        } else {
            None
        }
    }

    fn record_error(&mut self, header: Option<&T510Header>, message: String) {
        if let Some(header) = header {
            self.status.frame_id = Some(header.frame_id);
            self.status.sample0 = Some(header.sample0);
            self.status.block_count = header.block_count.max(1);
            self.status.last_block_index = Some(header.block_index);
            self.status.last_chan0 = Some(header.chan0);
            self.status.last_chan_count = Some(header.chan_count);
        }
        self.status.complete = false;
        self.status.last_error = Some(message);
    }
}

#[derive(Debug)]
struct SpectrumPreviewGate {
    epoch: Instant,
    target_frame_id: AtomicU64,
    target_sample0: AtomicU64,
    target_block_count: AtomicU64,
    mask_lo: AtomicU64,
    mask_hi: AtomicU64,
    last_arm_ns: AtomicU64,
    first_hit_ns: AtomicU64,
}

impl Default for SpectrumPreviewGate {
    fn default() -> Self {
        Self {
            epoch: Instant::now(),
            target_frame_id: AtomicU64::new(NO_SPECTRUM_FRAME),
            target_sample0: AtomicU64::new(0),
            target_block_count: AtomicU64::new(0),
            mask_lo: AtomicU64::new(0),
            mask_hi: AtomicU64::new(0),
            last_arm_ns: AtomicU64::new(0),
            first_hit_ns: AtomicU64::new(0),
        }
    }
}

impl SpectrumPreviewGate {
    fn elapsed_ns(&self) -> u64 {
        self.epoch
            .elapsed()
            .as_nanos()
            .min(u128::from(u64::MAX)) as u64
    }

    fn reset(&self) {
        self.target_frame_id.store(NO_SPECTRUM_FRAME, Ordering::SeqCst);
        self.target_sample0.store(0, Ordering::SeqCst);
        self.target_block_count.store(0, Ordering::SeqCst);
        self.mask_lo.store(0, Ordering::SeqCst);
        self.mask_hi.store(0, Ordering::SeqCst);
        self.last_arm_ns.store(0, Ordering::SeqCst);
        self.first_hit_ns.store(0, Ordering::SeqCst);
    }

    fn mark_complete(&self) {
        self.target_frame_id.store(NO_SPECTRUM_FRAME, Ordering::SeqCst);
        self.target_sample0.store(0, Ordering::SeqCst);
        self.target_block_count.store(0, Ordering::SeqCst);
        self.mask_lo.store(0, Ordering::SeqCst);
        self.mask_hi.store(0, Ordering::SeqCst);
        self.first_hit_ns.store(0, Ordering::SeqCst);
    }

    fn should_decode(&self, header: &T510Header, interval: Duration) -> bool {
        let block_count = u64::from(header.block_count.max(1).min(128));
        let block_index = u64::from(header.block_index);
        if block_index >= block_count {
            return false;
        }
        let current_group = header.frame_id / block_count;

        let target_frame = self.target_frame_id.load(Ordering::SeqCst);
        if target_frame == NO_SPECTRUM_FRAME {
            let now_ns = self.elapsed_ns();
            let last_arm_ns = self.last_arm_ns.load(Ordering::SeqCst);
            if self
                .last_arm_ns
                .compare_exchange(last_arm_ns, now_ns, Ordering::SeqCst, Ordering::SeqCst)
                .is_ok()
            {
                let target_group = current_group.saturating_add(SPECTRUM_PREVIEW_GROUP_LEAD);
                self.target_sample0.store(header.sample0, Ordering::SeqCst);
                self.target_block_count.store(block_count, Ordering::SeqCst);
                self.mask_lo.store(0, Ordering::SeqCst);
                self.mask_hi.store(0, Ordering::SeqCst);
                self.first_hit_ns.store(0, Ordering::SeqCst);
                self.target_frame_id.store(target_group, Ordering::SeqCst);
            }
            return false;
        }
        if current_group < target_frame {
            return false;
        }
        if current_group > target_frame {
            let now_ns = self.elapsed_ns();
            let first_hit_ns = self.first_hit_ns.load(Ordering::SeqCst);
            let collect_timeout_ns = SPECTRUM_PREVIEW_COLLECT_TIMEOUT
                .as_nanos()
                .min(u128::from(u64::MAX)) as u64;
            if first_hit_ns != 0 && now_ns.saturating_sub(first_hit_ns) < collect_timeout_ns {
                return false;
            }
            let interval_ns = interval
                .max(Duration::from_millis(1))
                .as_nanos()
                .min(u128::from(u64::MAX)) as u64;
            let last_arm_ns = self.last_arm_ns.load(Ordering::SeqCst);
            if now_ns.saturating_sub(last_arm_ns) < interval_ns {
                return false;
            }
            if self
                .last_arm_ns
                .compare_exchange(last_arm_ns, now_ns, Ordering::SeqCst, Ordering::SeqCst)
                .is_ok()
            {
                let target_group = current_group.saturating_add(SPECTRUM_PREVIEW_GROUP_LEAD);
                self.target_sample0.store(header.sample0, Ordering::SeqCst);
                self.target_block_count.store(block_count, Ordering::SeqCst);
                self.mask_lo.store(0, Ordering::SeqCst);
                self.mask_hi.store(0, Ordering::SeqCst);
                self.first_hit_ns.store(0, Ordering::SeqCst);
                self.target_frame_id.store(target_group, Ordering::SeqCst);
            }
            return false;
        }

        if self.target_frame_id.load(Ordering::SeqCst) != current_group
            || self.target_block_count.load(Ordering::SeqCst) != block_count
        {
            return false;
        }

        if block_index < 64 {
            let bit = 1u64 << block_index;
            let first = self.mask_lo.fetch_or(bit, Ordering::SeqCst) & bit == 0;
            if first {
                let now_ns = self.elapsed_ns();
                let _ = self
                    .first_hit_ns
                    .compare_exchange(0, now_ns, Ordering::SeqCst, Ordering::SeqCst);
            }
            first
        } else {
            let bit = 1u64 << (block_index - 64);
            let first = self.mask_hi.fetch_or(bit, Ordering::SeqCst) & bit == 0;
            if first {
                let now_ns = self.elapsed_ns();
                let _ = self
                    .first_hit_ns
                    .compare_exchange(0, now_ns, Ordering::SeqCst, Ordering::SeqCst);
            }
            first
        }
    }
}

#[derive(Debug, Clone)]
struct SharedState {
    config: DisplayConfig,
    config_generation: u64,
    stats: ReceiverStats,
    waveform: Option<WaveformSnapshot>,
    waveform_binary: Option<Vec<u8>>,
    waveform_updated: Option<Instant>,
    spectrum: Option<SpectrumSnapshot>,
    spectrum_binary: Option<Vec<u8>>,
    spectrum_updated: Option<Instant>,
    spectrum_preview: SpecPreviewCapture,
}

#[derive(Debug, Deserialize)]
struct DisplayConfigPatch {
    bandwidth_mhz: Option<u32>,
    output_mode: Option<String>,
    center_mhz: Option<f64>,
    expected_mhz: Option<f64>,
    dac_mhz: Option<f64>,
    target_mhz_by_channel: Option<Vec<f64>>,
    waveform_view_mode: Option<String>,
    phase_deg_by_channel: Option<Vec<f64>>,
    channel_mask: Option<u16>,
    time_window_us: Option<f64>,
    display_points: Option<usize>,
    vertical_scale: Option<f64>,
    paused: Option<bool>,
    pause: Option<bool>,
    freeze: Option<bool>,
}

impl DisplayConfigPatch {
    fn apply_to(self, config: &mut DisplayConfig) {
        let scalar_target = self.expected_mhz.or(self.dac_mhz);
        if let Some(value) = self.bandwidth_mhz {
            config.bandwidth_mhz = value;
        }
        if let Some(value) = self.output_mode {
            config.output_mode = value;
        }
        if let Some(value) = self.center_mhz {
            config.center_mhz = value;
        }
        if let Some(value) = self.expected_mhz {
            config.expected_mhz = value;
        }
        if let Some(value) = self.dac_mhz {
            config.dac_mhz = value;
        }
        if let Some(value) = scalar_target {
            config.target_mhz_by_channel.fill(value);
        }
        if let Some(targets) = self.target_mhz_by_channel {
            for (dst, src) in config.target_mhz_by_channel.iter_mut().zip(targets) {
                *dst = src;
            }
        }
        if let Some(value) = self.waveform_view_mode {
            config.waveform_view_mode = value;
        }
        if let Some(phases) = self.phase_deg_by_channel {
            for (dst, src) in config.phase_deg_by_channel.iter_mut().zip(phases) {
                *dst = src;
            }
        }
        if let Some(value) = self.channel_mask {
            config.channel_mask = value;
        }
        if let Some(value) = self.time_window_us {
            config.time_window_us = value;
        }
        if let Some(value) = self.display_points {
            config.display_points = value;
        }
        if let Some(value) = self.vertical_scale {
            config.vertical_scale = value;
        }
        if let Some(value) = self.paused.or(self.pause).or(self.freeze) {
            config.paused = value;
        }
        sanitize_config(config);
    }
}

fn sanitize_config(config: &mut DisplayConfig) {
    if BandwidthMode::from_mhz(config.bandwidth_mhz).is_none() {
        config.bandwidth_mhz = 100;
    }
    if !matches!(config.output_mode.as_str(), "time_only" | "spec_only" | "time_spec") {
        config.output_mode = "time_spec".to_string();
    }
    config.display_points = config.display_points.clamp(64, 16384);
    if !matches!(config.waveform_view_mode.as_str(), "dual" | "samples" | "curve") {
        config.waveform_view_mode = "dual".to_string();
    }
    config.time_window_us = config.time_window_us.clamp(0.02, 25.0);
    config.vertical_scale = config.vertical_scale.clamp(1.0, 1_000_000.0);
    config.channel_mask &= 0x00ff;
    if config.channel_mask == 0 {
        config.channel_mask = 0x0001;
    }
    let fallback = expected_signal_hz(config) / 1_000_000.0;
    for target in &mut config.target_mhz_by_channel {
        if !target.is_finite() || !(0.0..=100_000.0).contains(target) {
            *target = fallback;
        }
    }
}

fn apply_display_config_patch_to_shared(state: &mut SharedState, patch: DisplayConfigPatch) -> (DisplayConfig, u64) {
    patch.apply_to(&mut state.config);
    state.config_generation = state.config_generation.saturating_add(1);
    state.waveform = None;
    state.waveform_binary = None;
    state.waveform_updated = None;
    state.spectrum = None;
    state.spectrum_binary = None;
    state.spectrum_updated = None;
    state.spectrum_preview = SpecPreviewCapture::default();
    let selected = state.config.bandwidth_mode().mhz();
    state.stats.selected_bandwidth_mhz = selected;
    state.stats.selected_detected_mismatch = state
        .stats
        .detected_bandwidth_mhz
        .map(|mhz| mhz != selected)
        .unwrap_or(false);
    (state.config.clone(), state.config_generation)
}

fn preview_age_ms(updated: Option<Instant>) -> Option<u64> {
    updated.map(|instant| instant.elapsed().as_millis().min(u128::from(u64::MAX)) as u64)
}

fn preview_live(updated: Option<Instant>) -> bool {
    updated
        .map(|instant| instant.elapsed() <= PREVIEW_STALE_AFTER)
        .unwrap_or(false)
}

fn expected_preview_pps(config: &DisplayConfig, stats: &ReceiverStats) -> f64 {
    if stats.expected_packets_per_sec.is_finite() && stats.expected_packets_per_sec > 0.0 {
        return stats.expected_packets_per_sec;
    }
    let time_count = stats.last_time_count.unwrap_or(DEFAULT_TIME_COUNT).max(1) as f64;
    config.bandwidth_mode().sample_rate_hz() / (time_count * TIME_SUBSAMPLES_PER_BEAT as f64)
}

fn preview_rate_gate_pps(config: &DisplayConfig, stats: &ReceiverStats) -> f64 {
    (expected_preview_pps(config, stats) * PREVIEW_LIVE_MIN_RATE_FRACTION).max(PREVIEW_LIVE_MIN_PPS_FLOOR)
}

fn waveform_rate_live(config: &DisplayConfig, stats: &ReceiverStats) -> bool {
    config.needs_time()
        && stats.rx_processed_packets_per_sec.is_finite()
        && stats.rx_processed_packets_per_sec >= preview_rate_gate_pps(config, stats)
}

fn clear_stale_previews(state: &mut SharedState) {
    if !state.config.needs_time()
        || !preview_live(state.waveform_updated)
        || !waveform_rate_live(&state.config, &state.stats)
    {
        state.waveform = None;
        state.waveform_binary = None;
        state.waveform_updated = None;
    }
    // A completed spectrum is direct evidence that SPEC packets are live.  The
    // aggregate fanout rate is reported asynchronously by each worker and can
    // briefly read as zero while a fresh spectrum is already available.  Do
    // not let that reporting race evict the binary frame used by the web GUI;
    // freshness still removes it promptly when the SPEC stream really stops.
    if !state.config.needs_spec() || !preview_live(state.spectrum_updated) {
        state.spectrum = None;
        state.spectrum_binary = None;
        state.spectrum_updated = None;
    }
}

#[repr(C)]
#[derive(Clone, Copy)]
struct TpacketReq3 {
    tp_block_size: libc::c_uint,
    tp_block_nr: libc::c_uint,
    tp_frame_size: libc::c_uint,
    tp_frame_nr: libc::c_uint,
    tp_retire_blk_tov: libc::c_uint,
    tp_sizeof_priv: libc::c_uint,
    tp_feature_req_word: libc::c_uint,
}

#[repr(C)]
#[derive(Clone, Copy)]
struct TpacketStatsV3 {
    tp_packets: libc::c_uint,
    tp_drops: libc::c_uint,
    tp_freeze_q_cnt: libc::c_uint,
}

#[repr(C)]
struct TpacketBdTs {
    ts_sec: libc::c_uint,
    ts_nsec: libc::c_uint,
}

#[repr(C)]
struct TpacketHdrV1 {
    block_status: u32,
    num_pkts: u32,
    offset_to_first_pkt: u32,
    blk_len: u32,
    seq_num: u64,
    ts_first_pkt: TpacketBdTs,
    ts_last_pkt: TpacketBdTs,
}

#[repr(C)]
struct TpacketBlockDesc {
    version: u32,
    offset_to_priv: u32,
    hdr: TpacketHdrV1,
}

#[repr(C)]
struct TpacketHdrVariant1 {
    tp_rxhash: u32,
    tp_vlan_tci: u32,
    tp_vlan_tpid: u16,
    tp_padding: u16,
}

#[repr(C)]
struct Tpacket3Hdr {
    tp_next_offset: u32,
    tp_sec: u32,
    tp_nsec: u32,
    tp_snaplen: u32,
    tp_len: u32,
    tp_status: u32,
    tp_mac: u16,
    tp_net: u16,
    hv1: TpacketHdrVariant1,
    tp_padding: [u8; 8],
}

#[derive(Clone, Copy)]
struct MmapOptions {
    block_size: usize,
    block_count: usize,
    frame_size: usize,
    frame_count: usize,
    ring_bytes: usize,
    batch_size: usize,
    poll_timeout_ms: i32,
}

impl MmapOptions {
    fn from_args(args: &Args) -> std::io::Result<Self> {
        let page_size = unsafe { libc::sysconf(libc::_SC_PAGESIZE) };
        if page_size <= 0 {
            return Err(std::io::Error::last_os_error());
        }
        let page_size = page_size as usize;
        let frame_size = align_up((args.frame_kb.max(1)) * 1024, 16);
        let min_frame_size = align_up(mem::size_of::<Tpacket3Hdr>() + mem::size_of::<libc::sockaddr_ll>() + 9000, 16);
        if frame_size < min_frame_size {
            return Err(std::io::Error::new(
                std::io::ErrorKind::InvalidInput,
                format!("--frame-kb too small; need at least {} KiB for jumbo TIME frames", div_ceil(min_frame_size, 1024)),
            ));
        }
        let block_size = align_up(args.block_mb.max(1) * MIB, page_size);
        if block_size % frame_size != 0 {
            return Err(std::io::Error::new(
                std::io::ErrorKind::InvalidInput,
                "--block-mb must produce a block size divisible by --frame-kb",
            ));
        }
        let block_count = if args.block_count > 0 {
            args.block_count
        } else {
            (args.ring_mb.max(args.block_mb) / args.block_mb.max(1)).max(1)
        };
        let frame_count = (block_size / frame_size) * block_count;
        let ring_bytes = block_size
            .checked_mul(block_count)
            .ok_or_else(|| std::io::Error::new(std::io::ErrorKind::InvalidInput, "ring size overflow"))?;
        Ok(Self {
            block_size,
            block_count,
            frame_size,
            frame_count,
            ring_bytes,
            batch_size: args.batch_size.max(1),
            poll_timeout_ms: args.poll_timeout_ms.max(1),
        })
    }
}

fn align_up(value: usize, align: usize) -> usize {
    (value + align - 1) & !(align - 1)
}

fn div_ceil(value: usize, divisor: usize) -> usize {
    (value + divisor - 1) / divisor
}

struct MmapBatchStats {
    packets: u64,
    blocks: u32,
}

struct MmapPacketSocket {
    fd: RawFd,
    mmap_ptr: *mut u8,
    mmap_len: usize,
    options: MmapOptions,
    current_block: usize,
    last_stats_poll: Instant,
}

#[derive(Clone, Copy)]
struct PacketFanoutConfig {
    group: u16,
    mode: FanoutMode,
    worker_count: usize,
}

impl MmapPacketSocket {
    fn open(interface: &str, options: MmapOptions, dst_port_base: u16, flow_count: usize) -> std::io::Result<Self> {
        Self::open_with_fanout(interface, options, dst_port_base, flow_count, None)
    }

    fn open_with_fanout(
        interface: &str,
        options: MmapOptions,
        dst_port_base: u16,
        flow_count: usize,
        fanout: Option<PacketFanoutConfig>,
    ) -> std::io::Result<Self> {
        let ifindex = interface_index(interface)?;
        let fd = unsafe {
            libc::socket(
                libc::AF_PACKET,
                libc::SOCK_RAW,
                i32::from(ETH_P_ALL.to_be()),
            )
        };
        if fd < 0 {
            return Err(std::io::Error::last_os_error());
        }
        if let Err(err) = set_packet_int(fd, PACKET_VERSION, TPACKET_V3) {
            unsafe {
                libc::close(fd);
            }
            return Err(err);
        }
        if let Err(err) = attach_udp_port_range_filter(fd, dst_port_base, flow_count) {
            unsafe {
                libc::close(fd);
            }
            return Err(err);
        }
        let req = TpacketReq3 {
            tp_block_size: options.block_size as libc::c_uint,
            tp_block_nr: options.block_count as libc::c_uint,
            tp_frame_size: options.frame_size as libc::c_uint,
            tp_frame_nr: options.frame_count as libc::c_uint,
            tp_retire_blk_tov: options.poll_timeout_ms.max(1) as libc::c_uint,
            tp_sizeof_priv: 0,
            tp_feature_req_word: 0,
        };
        let rc = unsafe {
            libc::setsockopt(
                fd,
                SOL_PACKET,
                PACKET_RX_RING,
                &req as *const TpacketReq3 as *const libc::c_void,
                mem::size_of::<TpacketReq3>() as libc::socklen_t,
            )
        };
        if rc < 0 {
            let err = std::io::Error::last_os_error();
            unsafe {
                libc::close(fd);
            }
            return Err(err);
        }
        let mmap_ptr = unsafe {
            libc::mmap(
                ptr::null_mut(),
                options.ring_bytes,
                libc::PROT_READ | libc::PROT_WRITE,
                libc::MAP_SHARED,
                fd,
                0,
            )
        };
        if mmap_ptr == libc::MAP_FAILED {
            let err = std::io::Error::last_os_error();
            unsafe {
                libc::close(fd);
            }
            return Err(err);
        }
        if let Err(err) = bind_packet_socket(fd, ifindex) {
            unsafe {
                libc::munmap(mmap_ptr, options.ring_bytes);
                libc::close(fd);
            }
            return Err(err);
        }
        if let Some(config) = fanout {
            if let Err(err) = set_packet_fanout(fd, config) {
                unsafe {
                    libc::munmap(mmap_ptr, options.ring_bytes);
                    libc::close(fd);
                }
                return Err(err);
            }
            if config.mode == FanoutMode::Port {
                if let Err(err) = set_packet_fanout_port_bpf(fd, dst_port_base, config.worker_count) {
                    unsafe {
                        libc::munmap(mmap_ptr, options.ring_bytes);
                        libc::close(fd);
                    }
                    return Err(err);
                }
            }
        }
        Ok(Self {
            fd,
            mmap_ptr: mmap_ptr as *mut u8,
            mmap_len: options.ring_bytes,
            options,
            current_block: 0,
            last_stats_poll: Instant::now(),
        })
    }

    fn apply_ring_config_to_stats(&self, stats: &mut ReceiverStats) {
        stats.ring_bytes = self.options.ring_bytes as u64;
        stats.ring_block_size = self.options.block_size as u32;
        stats.ring_block_count = self.options.block_count as u32;
        stats.ring_frame_size = self.options.frame_size as u32;
        stats.ring_frame_count = self.options.frame_count as u32;
    }

    fn drain<F>(&mut self, mut handle_frame: F) -> std::io::Result<MmapBatchStats>
    where
        F: FnMut(&[u8]),
    {
        let mut packets = 0u64;
        let mut blocks = 0u32;
        loop {
            let block = self.block_ptr(self.current_block);
            let status = unsafe { ptr::read_volatile(&(*block).hdr.block_status) };
            if status & TP_STATUS_USER == 0 {
                if packets == 0 {
                    if !self.poll_once()? {
                        return Ok(MmapBatchStats { packets: 0, blocks: 0 });
                    }
                    continue;
                }
                break;
            }

            fence(Ordering::Acquire);
            let block_start = block as usize;
            let block_end = block_start + self.options.block_size;
            let num_pkts = unsafe { ptr::read_volatile(&(*block).hdr.num_pkts) as usize };
            let first = unsafe { ptr::read_volatile(&(*block).hdr.offset_to_first_pkt) as usize };
            let mut pkt_ptr = unsafe { (block as *mut u8).add(first) };
            for _ in 0..num_pkts {
                if pkt_ptr as usize + mem::size_of::<Tpacket3Hdr>() > block_end {
                    break;
                }
                let hdr = unsafe { &*(pkt_ptr as *const Tpacket3Hdr) };
                let snaplen = hdr.tp_snaplen as usize;
                let mac_offset = hdr.tp_mac as usize;
                let data_ptr = unsafe { pkt_ptr.add(mac_offset) };
                if data_ptr as usize + snaplen <= block_end {
                    let frame = unsafe { slice::from_raw_parts(data_ptr, snaplen) };
                    handle_frame(frame);
                    packets = packets.saturating_add(1);
                }
                let next = hdr.tp_next_offset as usize;
                if next == 0 {
                    break;
                }
                pkt_ptr = unsafe { pkt_ptr.add(next) };
                if pkt_ptr as usize >= block_end {
                    break;
                }
            }
            fence(Ordering::Release);
            unsafe {
                ptr::write_volatile(&mut (*block).hdr.block_status, TP_STATUS_KERNEL);
            }
            self.current_block = (self.current_block + 1) % self.options.block_count;
            blocks = blocks.saturating_add(1);
            if packets >= self.options.batch_size as u64 {
                break;
            }
        }
        Ok(MmapBatchStats { packets, blocks })
    }

    fn poll_once(&self) -> std::io::Result<bool> {
        let mut pfd = libc::pollfd {
            fd: self.fd,
            events: libc::POLLIN,
            revents: 0,
        };
        loop {
            let rc = unsafe { libc::poll(&mut pfd, 1, self.options.poll_timeout_ms) };
            if rc < 0 {
                let err = std::io::Error::last_os_error();
                if err.kind() == std::io::ErrorKind::Interrupted {
                    continue;
                }
                return Err(err);
            }
            return Ok(rc > 0);
        }
    }

    fn poll_kernel_stats_if_due(&mut self, stats: &mut ReceiverStats) {
        if self.last_stats_poll.elapsed() < Duration::from_secs(1) {
            return;
        }
        match self.packet_statistics() {
            Ok(packet_stats) => {
                stats.kernel_drops = stats
                    .kernel_drops
                    .saturating_add(packet_stats.tp_drops as u64);
                stats.ring_drops = stats
                    .ring_drops
                    .saturating_add(packet_stats.tp_drops as u64);
            stats.ring_freeze_q_count = stats
                .ring_freeze_q_count
                .saturating_add(packet_stats.tp_freeze_q_cnt as u64);
            }
            Err(err) => {
                stats.last_error = Some(format!("PACKET_STATISTICS failed: {err}"));
            }
        }
        self.last_stats_poll = Instant::now();
    }

    fn poll_kernel_stats_if_due_worker(&mut self, stats: &mut WorkerStats) {
        if self.last_stats_poll.elapsed() < Duration::from_secs(1) {
            return;
        }
        match self.packet_statistics() {
            Ok(packet_stats) => {
            stats.kernel_drops = stats.kernel_drops.saturating_add(packet_stats.tp_drops as u64);
            stats.ring_drops = stats.ring_drops.saturating_add(packet_stats.tp_drops as u64);
            stats.ring_freeze_q_count = stats
                .ring_freeze_q_count
                .saturating_add(packet_stats.tp_freeze_q_cnt as u64);
            }
            Err(err) => {
                stats.last_error = Some(format!("PACKET_STATISTICS failed: {err}"));
            }
        }
        self.last_stats_poll = Instant::now();
    }

    fn packet_statistics(&self) -> std::io::Result<TpacketStatsV3> {
        let mut packet_stats = TpacketStatsV3 {
            tp_packets: 0,
            tp_drops: 0,
            tp_freeze_q_cnt: 0,
        };
        let mut len = mem::size_of::<TpacketStatsV3>() as libc::socklen_t;
        let rc = unsafe {
            libc::getsockopt(
                self.fd,
                SOL_PACKET,
                PACKET_STATISTICS,
                &mut packet_stats as *mut TpacketStatsV3 as *mut libc::c_void,
                &mut len as *mut libc::socklen_t,
            )
        };
        if rc == 0 {
            Ok(packet_stats)
        } else {
            Err(std::io::Error::last_os_error())
        }
    }

    fn block_ptr(&self, index: usize) -> *mut TpacketBlockDesc {
        unsafe { self.mmap_ptr.add(index * self.options.block_size) as *mut TpacketBlockDesc }
    }
}

impl Drop for MmapPacketSocket {
    fn drop(&mut self) {
        unsafe {
            let zero_req: TpacketReq3 = mem::zeroed();
            let _ = libc::setsockopt(
                self.fd,
                SOL_PACKET,
                PACKET_RX_RING,
                &zero_req as *const TpacketReq3 as *const libc::c_void,
                mem::size_of::<TpacketReq3>() as libc::socklen_t,
            );
            libc::munmap(self.mmap_ptr as *mut libc::c_void, self.mmap_len);
            libc::close(self.fd);
        }
    }
}

struct PacketSocket {
    fd: RawFd,
}

impl PacketSocket {
    fn open(interface: &str, dst_port_base: u16, flow_count: usize) -> std::io::Result<Self> {
        let ifindex = interface_index(interface)?;
        let fd = unsafe {
            libc::socket(
                libc::AF_PACKET,
                libc::SOCK_RAW,
                i32::from(ETH_P_ALL.to_be()),
            )
        };
        if fd < 0 {
            return Err(std::io::Error::last_os_error());
        }
        if let Err(err) = attach_udp_port_range_filter(fd, dst_port_base, flow_count) {
            unsafe {
                libc::close(fd);
            }
            return Err(err);
        }
        if let Err(err) = bind_packet_socket(fd, ifindex) {
            unsafe {
                libc::close(fd);
            }
            return Err(err);
        }
        Ok(Self { fd })
    }

    fn recv<'a>(&self, buf: &'a mut [u8]) -> std::io::Result<&'a [u8]> {
        let len = unsafe {
            libc::recv(
                self.fd,
                buf.as_mut_ptr() as *mut libc::c_void,
                buf.len(),
                0,
            )
        };
        if len < 0 {
            return Err(std::io::Error::last_os_error());
        }
        Ok(&buf[..len as usize])
    }
}

impl Drop for PacketSocket {
    fn drop(&mut self) {
        unsafe {
            libc::close(self.fd);
        }
    }
}

fn interface_index(interface: &str) -> std::io::Result<u32> {
    let ifname = CString::new(interface).map_err(|_| {
        std::io::Error::new(std::io::ErrorKind::InvalidInput, "interface name contains NUL")
    })?;
    let ifindex = unsafe { libc::if_nametoindex(ifname.as_ptr()) };
    if ifindex == 0 {
        Err(std::io::Error::last_os_error())
    } else {
        Ok(ifindex)
    }
}

fn bind_packet_socket(fd: RawFd, ifindex: u32) -> std::io::Result<()> {
    let mut addr: libc::sockaddr_ll = unsafe { mem::zeroed() };
    addr.sll_family = libc::AF_PACKET as u16;
    addr.sll_protocol = ETH_P_ALL.to_be();
    addr.sll_ifindex = ifindex as i32;
    let rc = unsafe {
        libc::bind(
            fd,
            &addr as *const libc::sockaddr_ll as *const libc::sockaddr,
            mem::size_of::<libc::sockaddr_ll>() as libc::socklen_t,
        )
    };
    if rc < 0 {
        Err(std::io::Error::last_os_error())
    } else {
        Ok(())
    }
}

fn set_packet_int(fd: RawFd, optname: libc::c_int, value: libc::c_int) -> std::io::Result<()> {
    let rc = unsafe {
        libc::setsockopt(
            fd,
            SOL_PACKET,
            optname,
            &value as *const libc::c_int as *const libc::c_void,
            mem::size_of::<libc::c_int>() as libc::socklen_t,
        )
    };
    if rc < 0 {
        Err(std::io::Error::last_os_error())
    } else {
        Ok(())
    }
}

fn packet_fanout_arg(config: PacketFanoutConfig) -> libc::c_int {
    i32::from(config.group) | (i32::from(config.mode.packet_type()) << 16)
}

fn set_packet_fanout(fd: RawFd, config: PacketFanoutConfig) -> std::io::Result<()> {
    let value = packet_fanout_arg(config);
    let rc = unsafe {
        libc::setsockopt(
            fd,
            SOL_PACKET,
            PACKET_FANOUT,
            &value as *const libc::c_int as *const libc::c_void,
            mem::size_of_val(&value) as libc::socklen_t,
        )
    };
    if rc < 0 {
        Err(std::io::Error::last_os_error())
    } else {
        Ok(())
    }
}

fn bpf_fanout_by_dst_port(dst_port_base: u16, worker_count: usize) -> [libc::sock_filter; 4] {
    let worker_count = worker_count.clamp(1, MAX_WORKER_COUNT_27H) as u32;
    [
        // PACKET_FANOUT_DATA CBPF runs with skb data at the network header.
        // For IPv4 without options, UDP dst port is IP header offset 20 + 2.
        bpf_stmt(BPF_LD | BPF_H | BPF_ABS, 22),
        bpf_stmt(BPF_ALU | BPF_SUB | BPF_K, dst_port_base as u32),
        bpf_stmt(BPF_ALU | BPF_MOD | BPF_K, worker_count),
        bpf_stmt(BPF_RET | BPF_A, 0),
    ]
}

fn set_packet_fanout_port_bpf(fd: RawFd, dst_port_base: u16, worker_count: usize) -> std::io::Result<()> {
    let worker_count = worker_count.clamp(1, MAX_WORKER_COUNT_27H);
    let mut filter = bpf_fanout_by_dst_port(dst_port_base, worker_count);
    let mut prog = libc::sock_fprog {
        len: filter.len() as u16,
        filter: filter.as_mut_ptr(),
    };
    let rc = unsafe {
        libc::setsockopt(
            fd,
            SOL_PACKET,
            PACKET_FANOUT_DATA,
            &mut prog as *mut libc::sock_fprog as *mut libc::c_void,
            mem::size_of::<libc::sock_fprog>() as libc::socklen_t,
        )
    };
    if rc < 0 {
        Err(std::io::Error::last_os_error())
    } else {
        Ok(())
    }
}

fn pin_current_thread(worker_id: usize) -> std::io::Result<()> {
    let cpus = thread::available_parallelism()
        .map(|value| value.get())
        .unwrap_or(1)
        .max(1);
    let cpu = worker_id % cpus;
    let mut set: libc::cpu_set_t = unsafe { mem::zeroed() };
    unsafe {
        libc::CPU_ZERO(&mut set);
        libc::CPU_SET(cpu, &mut set);
    }
    let rc = unsafe { libc::sched_setaffinity(0, mem::size_of::<libc::cpu_set_t>(), &set) };
    if rc < 0 {
        Err(std::io::Error::last_os_error())
    } else {
        Ok(())
    }
}

fn bpf_stmt(code: u16, k: u32) -> libc::sock_filter {
    libc::sock_filter {
        code,
        jt: 0,
        jf: 0,
        k,
    }
}

fn bpf_jump(code: u16, k: u32, jt: u8, jf: u8) -> libc::sock_filter {
    libc::sock_filter { code, jt, jf, k }
}

fn bpf_udp_port_range_filter(dst_port_base: u16, flow_count: usize) -> [libc::sock_filter; 9] {
    let count = flow_count.clamp(1, MAX_FLOW_COUNT_27H) as u16;
    let dst_port_end = dst_port_base.saturating_add(count - 1);
    [
        bpf_stmt(BPF_LD | BPF_H | BPF_ABS, 12),
        bpf_jump(BPF_JMP | BPF_JEQ | BPF_K, 0x0800, 0, 6),
        bpf_stmt(BPF_LD | BPF_B | BPF_ABS, 23),
        bpf_jump(BPF_JMP | BPF_JEQ | BPF_K, 17, 0, 4),
        bpf_stmt(BPF_LD | BPF_H | BPF_ABS, 36),
        bpf_jump(BPF_JMP | BPF_JGE | BPF_K, dst_port_base as u32, 0, 2),
        bpf_jump(BPF_JMP | BPF_JGT | BPF_K, dst_port_end as u32, 1, 0),
        bpf_stmt(BPF_RET | BPF_K, 0xffff),
        bpf_stmt(BPF_RET | BPF_K, 0),
    ]
}

fn attach_udp_port_range_filter(fd: RawFd, dst_port_base: u16, flow_count: usize) -> std::io::Result<()> {
    let mut filter = bpf_udp_port_range_filter(dst_port_base, flow_count);
    let mut prog = libc::sock_fprog {
        len: filter.len() as u16,
        filter: filter.as_mut_ptr(),
    };
    let rc = unsafe {
        libc::setsockopt(
            fd,
            libc::SOL_SOCKET,
            SO_ATTACH_FILTER,
            &mut prog as *mut libc::sock_fprog as *mut libc::c_void,
            mem::size_of::<libc::sock_fprog>() as libc::socklen_t,
        )
    };
    if rc < 0 {
        Err(std::io::Error::last_os_error())
    } else {
        Ok(())
    }
}

#[derive(Default, Debug, Clone, Copy)]
struct NicCounters {
    rx_packets: u64,
    rx_bytes: u64,
    rx_dropped: u64,
    rx_errors: u64,
    rx_missed_errors: u64,
    rx_crc_errors: u64,
}

struct NicStatsReader {
    interface: String,
    last: Option<NicCounters>,
}

impl NicStatsReader {
    fn new(interface: &str) -> Self {
        Self {
            interface: interface.to_string(),
            last: None,
        }
    }

    fn sample(&mut self, elapsed: Duration, stats: &mut ReceiverStats) {
        let Ok(now) = self.read() else {
            return;
        };
        if let Some(prev) = self.last {
            let seconds = elapsed.as_secs_f64().max(1e-9);
            stats.nic_rx_packets_per_sec = now.rx_packets.saturating_sub(prev.rx_packets) as f64 / seconds;
            stats.nic_rx_gbps = now.rx_bytes.saturating_sub(prev.rx_bytes) as f64 * 8.0 / seconds / 1.0e9;
            stats.nic_rx_dropped_delta = now.rx_dropped.saturating_sub(prev.rx_dropped);
            stats.nic_rx_errors_delta = now.rx_errors.saturating_sub(prev.rx_errors);
            stats.nic_rx_missed_errors_delta = now.rx_missed_errors.saturating_sub(prev.rx_missed_errors);
            stats.nic_rx_crc_errors_delta = now.rx_crc_errors.saturating_sub(prev.rx_crc_errors);
        }
        self.last = Some(now);
    }

    fn read(&self) -> std::io::Result<NicCounters> {
        Ok(NicCounters {
            rx_packets: read_net_stat(&self.interface, "rx_packets")?,
            rx_bytes: read_net_stat(&self.interface, "rx_bytes")?,
            rx_dropped: read_net_stat(&self.interface, "rx_dropped")?,
            rx_errors: read_net_stat(&self.interface, "rx_errors")?,
            rx_missed_errors: read_net_stat(&self.interface, "rx_missed_errors").unwrap_or(0),
            rx_crc_errors: read_net_stat(&self.interface, "rx_crc_errors").unwrap_or(0),
        })
    }
}

fn read_net_stat(interface: &str, name: &str) -> std::io::Result<u64> {
    let path = format!("/sys/class/net/{}/statistics/{}", interface, name);
    let text = fs::read_to_string(path)?;
    text.trim()
        .parse::<u64>()
        .map_err(|err| std::io::Error::new(std::io::ErrorKind::InvalidData, err))
}

enum InputKind {
    Ethernet,
    UdpPayload,
}

#[derive(Clone)]
struct PacketCopy {
    header: T510Header,
    payload: Vec<u8>,
    detected_bandwidth: Option<BandwidthMode>,
    gap_before: bool,
}

struct ReorderTracker {
    expected_seq: Option<u32>,
    pending: BTreeMap<u32, T510Header>,
    last_accepted: Option<T510Header>,
    window: u32,
}

impl ReorderTracker {
    fn new(window: u32) -> Self {
        Self {
            expected_seq: None,
            pending: BTreeMap::new(),
            last_accepted: None,
            window: window.max(1),
        }
    }

    fn ingest(
        &mut self,
        header: T510Header,
        selected: BandwidthMode,
        stats: &mut ReceiverStats,
    ) -> (Option<BandwidthMode>, bool) {
        if let Some(expected) = self.expected_seq {
            if seq_is_before(header.seq_no, expected) {
                return (None, false);
            }
        } else {
            self.expected_seq = Some(header.seq_no);
        }

        self.pending.entry(header.seq_no).or_insert(header);
        let mut detected = None;
        let mut gap_before = false;

        loop {
            let Some(expected) = self.expected_seq else {
                break;
            };
            if let Some(header) = self.pending.remove(&expected) {
                let (this_detected, this_gap) = self.accept_in_order(header, selected, stats);
                detected = this_detected.or(detected);
                gap_before |= this_gap;
                self.expected_seq = Some(expected.wrapping_add(1));
                continue;
            }

            let Some((&first_pending, _)) = self.pending.iter().next() else {
                break;
            };
            let distance = first_pending.wrapping_sub(expected);
            if distance > self.window {
                stats.seq_gaps = stats.seq_gaps.saturating_add(1);
                stats.app_drops = stats.app_drops.saturating_add(u64::from(distance).min(1_000_000));
                gap_before = true;
                self.expected_seq = Some(first_pending);
                continue;
            }
            break;
        }

        (detected, gap_before)
    }

    fn accept_in_order(
        &mut self,
        header: T510Header,
        selected: BandwidthMode,
        stats: &mut ReceiverStats,
    ) -> (Option<BandwidthMode>, bool) {
        let mut detected = None;
        let mut gap = false;
        if let Some(prev) = self.last_accepted {
            if !frame_next(prev.frame_id, header.frame_id) {
                stats.frame_gaps = stats.frame_gaps.saturating_add(1);
                gap = true;
            }
            let delta = header.sample0.wrapping_sub(prev.sample0);
            detected = infer_bandwidth_from_sample0_delta(&header, delta);
            if delta != expected_sample0_delta(&header, selected) {
                stats.sample0_gaps = stats.sample0_gaps.saturating_add(1);
                gap = true;
            }
        }
        stats.last_seq_no = Some(header.seq_no);
        stats.last_frame_id = Some(header.frame_id);
        stats.last_sample0 = Some(header.sample0);
        stats.last_time_count = Some(header.time_count);
        self.last_accepted = Some(header);
        (detected, gap)
    }
}

fn seq_is_before(seq: u32, expected: u32) -> bool {
    seq != expected && expected.wrapping_sub(seq) < 0x8000_0000
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

fn estimate_time_raw_baseband_hz(
    packets: &[PacketCopy],
    config: &DisplayConfig,
    decim: u64,
    target_channel: usize,
) -> Option<f64> {
    let decim = decim.max(1);
    let mut prev: [Option<(u64, f64, f64)>; TIME_NINPUT] = [None; TIME_NINPUT];
    let mut weighted_hz_sum = 0.0f64;
    let mut weight_sum = 0.0f64;
    let mut pair_count = 0usize;
    let channel = target_channel.min(TIME_NINPUT - 1);

    for packet in packets {
        for beat in 0..packet.header.time_count as usize {
            for sub in 0..TIME_SUBSAMPLES_PER_BEAT {
                let logical_idx = beat * TIME_SUBSAMPLES_PER_BEAT + sub;
                let sample_index = packet.header.sample0 + logical_idx as u64 * decim;
                    if (config.channel_mask & (1u16 << channel)) == 0 {
                        continue;
                    }
                    let Ok(offset) = time_payload_complex_offset(beat, sub, channel) else {
                        continue;
                    };
                    if offset + 4 > packet.payload.len() {
                        continue;
                    }
                let i =
                    i16::from_le_bytes([packet.payload[offset], packet.payload[offset + 1]]) as f64;
                let q = i16::from_le_bytes([packet.payload[offset + 2], packet.payload[offset + 3]])
                    as f64;
                    let power = i * i + q * q;
                    if power < 16.0 {
                        prev[channel] = Some((sample_index, i, q));
                        continue;
                    }
                    if let Some((prev_sample, prev_i, prev_q)) = prev[channel] {
                        let delta = sample_index.wrapping_sub(prev_sample);
                        if delta == decim {
                            let re = i * prev_i + q * prev_q;
                            let im = q * prev_i - i * prev_q;
                            let weight = (power * (prev_i * prev_i + prev_q * prev_q)).sqrt();
                            if weight > 0.0 {
                                let angle = im.atan2(re);
                                let hz = angle / (2.0 * std::f64::consts::PI)
                                    * (RAW_SAMPLE_RATE_HZ / delta as f64);
                                if hz.is_finite() {
                                    weighted_hz_sum += hz * weight;
                                    weight_sum += weight;
                                    pair_count += 1;
                                }
                            }
                        }
                    }
                    prev[channel] = Some((sample_index, i, q));
                }
            }
        }

    if pair_count >= 4 && weight_sum > 0.0 {
        Some(weighted_hz_sum / weight_sum)
    } else {
        None
    }
}

fn waveform_mixer_sign(raw_baseband_hz: Option<f64>, expected_baseband_hz: f64) -> f64 {
    let Some(raw_hz) = raw_baseband_hz else {
        return 1.0;
    };
    if !raw_hz.is_finite() || !expected_baseband_hz.is_finite() {
        return 1.0;
    }
    if raw_hz.abs() < 1.0 || expected_baseband_hz.abs() < 1.0 {
        return 1.0;
    }
    if (-raw_hz - expected_baseband_hz).abs() < (raw_hz - expected_baseband_hz).abs() {
        -1.0
    } else {
        1.0
    }
}

fn rf_equivalent_sample(i: f64, q: f64, sample_index: u64, center_hz: f64, mixer_sign: f64) -> f64 {
    rf_equivalent_at_sample(i, q, sample_index as f64, center_hz, mixer_sign)
}

fn rf_equivalent_at_sample(i: f64, q: f64, sample_index: f64, center_hz: f64, mixer_sign: f64) -> f64 {
    let theta = 2.0 * std::f64::consts::PI * center_hz * sample_index as f64 / RAW_SAMPLE_RATE_HZ;
    i * theta.cos() - mixer_sign * q * theta.sin()
}

fn sinc(x: f64) -> f64 {
    if x.abs() < 1.0e-12 {
        1.0
    } else {
        let phase = std::f64::consts::PI * x;
        phase.sin() / phase
    }
}

fn bandlimited_iq_at_sample(raw: &[(u64, f64, f64)], sample_index: f64, decim: u64) -> (f64, f64) {
    if raw.is_empty() {
        return (0.0, 0.0);
    }
    if raw.len() < 4 {
        return nearest_iq_at_sample(raw, sample_index);
    }
    let spacing = decim.max(1) as f64;
    let radius = 12.0f64;
    let mut i_acc = 0.0f64;
    let mut q_acc = 0.0f64;
    let mut w_acc = 0.0f64;
    for (sample, i, q) in raw.iter().copied() {
        let x = (sample_index - sample as f64) / spacing;
        if x.abs() < 1.0e-9 {
            return (i, q);
        }
        if x.abs() >= radius {
            continue;
        }
        let weight = sinc(x) * sinc(x / radius);
        i_acc += i * weight;
        q_acc += q * weight;
        w_acc += weight;
    }
    if w_acc.abs() > 1.0e-9 {
        (i_acc / w_acc, q_acc / w_acc)
    } else {
        nearest_iq_at_sample(raw, sample_index)
    }
}

fn nearest_iq_at_sample(raw: &[(u64, f64, f64)], sample_index: f64) -> (f64, f64) {
    let mut best = raw[0];
    let mut best_dist = (raw[0].0 as f64 - sample_index).abs();
    for item in raw.iter().copied().skip(1) {
        let dist = (item.0 as f64 - sample_index).abs();
        if dist < best_dist {
            best = item;
            best_dist = dist;
        }
    }
    (best.1, best.2)
}

struct DisplayCapture {
    active: bool,
    start_seq: Option<u32>,
    packets: BTreeMap<u32, PacketCopy>,
    max_points: usize,
    max_hold_packets: usize,
}

impl DisplayCapture {
    fn new(max_points: usize) -> Self {
        Self {
            active: false,
            start_seq: None,
            packets: BTreeMap::new(),
            max_points: max_points.clamp(1024, 16384),
            max_hold_packets: 256,
        }
    }

    fn arm(&mut self) {
        self.active = true;
        self.start_seq = None;
        self.packets.clear();
    }

    fn ingest(
        &mut self,
        header: T510Header,
        udp_payload: &[u8],
        config: &DisplayConfig,
        detected_bandwidth: Option<BandwidthMode>,
        gap_before: bool,
        seq_stride: u32,
    ) -> Option<Vec<PacketCopy>> {
        if !self.active {
            return None;
        }
        if self.start_seq.is_none() {
            self.start_seq = Some(header.seq_no);
        }
        let start = self.start_seq?;
        if seq_is_before(header.seq_no, start) {
            return None;
        }
        self.packets
            .entry(header.seq_no)
            .or_insert_with(|| PacketCopy {
            header,
            payload: udp_payload.to_vec(),
            detected_bandwidth,
            gap_before,
        });

        let samples_per_packet = (header.time_count as usize)
            .saturating_mul(TIME_SUBSAMPLES_PER_BEAT)
            .max(1);
        let bandwidth = detected_bandwidth.unwrap_or_else(|| config.bandwidth_mode());
        let window_samples = (config.time_window_us * bandwidth.sample_rate_hz() / 1_000_000.0)
            .ceil()
            .max(2.0) as usize;
        let target_samples = window_samples.saturating_add(1).clamp(2, self.max_points.max(2));
        let needed_packets = div_ceil(target_samples, samples_per_packet).clamp(1, 128);
        let mut seq = start;
        let seq_stride = seq_stride.max(1);
        let mut out = Vec::with_capacity(needed_packets);
        for _ in 0..needed_packets {
            if let Some(packet) = self.packets.get(&seq) {
                out.push(packet.clone());
                seq = seq.wrapping_add(seq_stride);
            } else {
                break;
            }
        }
        if !out.is_empty() && (out.len() >= needed_packets || self.packets.len() >= self.max_hold_packets) {
            self.active = false;
            self.start_seq = None;
            self.packets.clear();
            return Some(out);
        }
        None
    }
}

fn build_waveform_from_packets(packets: &[PacketCopy], config: &DisplayConfig) -> Result<WaveformSnapshot, String> {
    let first = packets.first().ok_or_else(|| "no packets available for waveform".to_string())?;
    let selected_bandwidth = config.bandwidth_mode();
    let bandwidth = packets
        .iter()
        .rev()
        .find_map(|packet| packet.detected_bandwidth)
        .unwrap_or(selected_bandwidth);
    let decim = bandwidth.decimation();
    let center_hz = config.center_mhz * 1_000_000.0;
    let window_us = config.time_window_us.max(0.0);
    let target_samples = (window_us * bandwidth.sample_rate_hz() / 1_000_000.0)
        .ceil()
        .max(2.0) as usize;
    let target_samples = target_samples.saturating_add(1).clamp(2, 16384);
    let curve_points = config.display_points.clamp(64, 16384);
    let first_sample0 = first.header.sample0;
    let mut channels = Vec::new();

    for channel in 0..TIME_NINPUT {
        if (config.channel_mask & (1u16 << channel)) == 0 {
            continue;
        }
        let expected_hz = config.target_hz(channel);
        let expected_baseband_hz = expected_hz - center_hz;
        let raw_baseband_hz = estimate_time_raw_baseband_hz(packets, config, decim, channel);
        let mixer_sign = waveform_mixer_sign(raw_baseband_hz, expected_baseband_hz);
        let mut raw = Vec::new();
        let mut sum_sq = 0.0f64;
        let mut max_abs: i16 = 0;
        for packet in packets {
            for beat in 0..packet.header.time_count as usize {
                for sub in 0..TIME_SUBSAMPLES_PER_BEAT {
                    let offset = time_payload_complex_offset(beat, sub, channel)?;
                    if offset + 4 > packet.payload.len() {
                        return Err("truncated payload while building waveform".to_string());
                    }
                    let i = i16::from_le_bytes([packet.payload[offset], packet.payload[offset + 1]]);
                    let q = i16::from_le_bytes([packet.payload[offset + 2], packet.payload[offset + 3]]);
                    let abs_i = i.saturating_abs();
                    let abs_q = q.saturating_abs();
                    max_abs = max_abs.max(abs_i).max(abs_q);
                    sum_sq += i as f64 * i as f64 + q as f64 * q as f64;
                    let logical_idx = beat * TIME_SUBSAMPLES_PER_BEAT + sub;
                    let sample_index = packet.header.sample0 + logical_idx as u64 * decim;
                    if raw.len() < target_samples {
                        raw.push((sample_index, i as f64, q as f64));
                    }
                }
            }
        }
        let measured_len = raw.len();
        let mut x_us = Vec::with_capacity(measured_len);
        let mut i_values = Vec::with_capacity(measured_len);
        let mut q_values = Vec::with_capacity(measured_len);
        let mut mag_values = Vec::with_capacity(measured_len);
        let mut sample_rf_values = Vec::with_capacity(measured_len);
        let mut rf_x_us = Vec::with_capacity(curve_points);
        let mut rf_values = Vec::with_capacity(curve_points);
        let scale = config.vertical_scale.max(1.0);
        for (sample_index, i, q) in raw.iter() {
            let t_us = sample_index.saturating_sub(first_sample0) as f64 / RAW_SAMPLE_RATE_HZ * 1_000_000.0;
            let rf = rf_equivalent_sample(*i, *q, *sample_index, center_hz, mixer_sign);
            x_us.push(t_us as f32);
            i_values.push((*i / scale) as f32);
            q_values.push((*q / scale) as f32);
            mag_values.push((i.hypot(*q) / scale) as f32);
            sample_rf_values.push((rf / scale) as f32);
        }
        for point in 0..curve_points {
            let frac = if curve_points > 1 {
                point as f64 / (curve_points - 1) as f64
            } else {
                0.0
            };
            let t_us = window_us * frac;
            let sample_index = first_sample0 as f64 + (t_us * 1.0e-6 * RAW_SAMPLE_RATE_HZ);
            let (i, q) = bandlimited_iq_at_sample(&raw, sample_index, decim);
            let rf = rf_equivalent_at_sample(i, q, sample_index, center_hz, mixer_sign);
            rf_x_us.push(t_us as f32);
            rf_values.push((rf / scale) as f32);
        }
        let y = sample_rf_values.clone();
        let rms = if raw.is_empty() {
            0.0
        } else {
            (sum_sq / raw.len() as f64).sqrt() as f32
        };
        channels.push(ChannelWaveform {
            channel,
            x_us,
            i: i_values,
            q: q_values,
            mag: mag_values,
            sample_rf: sample_rf_values,
            rf_x_us,
            rf: rf_values,
            y,
            rms_code: rms,
            max_abs_code: max_abs,
            clipped: max_abs >= 32760,
        });
    }

    let expected_hz = config.target_hz(0);
    let expected_baseband_hz = expected_hz - center_hz;
    Ok(WaveformSnapshot {
        sample0: first_sample0,
        seq_no: first.header.seq_no,
        frame_id: first.header.frame_id,
        selected_bandwidth_mhz: selected_bandwidth.mhz(),
        detected_bandwidth_mhz: packets.iter().rev().find_map(|packet| packet.detected_bandwidth).map(|mode| mode.mhz()),
        decimation: decim,
        sample_rate_hz: bandwidth.sample_rate_hz(),
        requested_window_us: window_us,
        captured_window_us: channels
            .first()
            .and_then(|channel| channel.x_us.last())
            .copied()
            .unwrap_or(0.0) as f64,
        center_mhz: config.center_mhz,
        expected_mhz: expected_hz / 1_000_000.0,
        dac_mhz: config.dac_mhz,
        expected_baseband_mhz: expected_baseband_hz / 1_000_000.0,
        rf_samples_per_cycle: samples_per_cycle(bandwidth.sample_rate_hz(), expected_hz),
        baseband_samples_per_cycle: samples_per_cycle(bandwidth.sample_rate_hz(), expected_baseband_hz),
        rf_window_cycles: expected_hz.abs() * config.time_window_us.max(0.0) * 1.0e-6,
        gap_before: packets.iter().any(|packet| packet.gap_before),
        channels,
    })
}

fn encode_waveform_binary(snapshot: &WaveformSnapshot, seq_end: u32) -> Vec<u8> {
    let channel_count = snapshot.channels.len() as u32;
    let measured_points_per_channel = snapshot
        .channels
        .iter()
        .map(|channel| {
            channel
                .x_us
                .len()
                .min(channel.i.len())
                .min(channel.q.len())
                .min(channel.mag.len())
                .min(channel.sample_rf.len())
        })
        .min()
        .unwrap_or(0) as u32;
    let rf_points_per_channel = snapshot
        .channels
        .iter()
        .map(|channel| channel.rf_x_us.len().min(channel.rf.len()))
        .min()
        .unwrap_or(0) as u32;
    let mut channel_mask = 0u32;
    for channel in &snapshot.channels {
        channel_mask |= 1u32 << channel.channel;
    }
    let mut out = Vec::with_capacity(
        WAVEFORM_BINARY_HEADER_BYTES as usize
            + channel_count as usize
                * (measured_points_per_channel as usize * 20 + rf_points_per_channel as usize * 8),
    );
    push_u32(&mut out, WAVEFORM_MAGIC);
    push_u16(&mut out, WAVEFORM_BINARY_VERSION);
    push_u16(&mut out, WAVEFORM_BINARY_HEADER_BYTES);
    push_u64(&mut out, snapshot.sample0);
    push_u32(&mut out, snapshot.seq_no);
    push_u32(&mut out, seq_end);
    push_u32(&mut out, snapshot.selected_bandwidth_mhz);
    push_u32(&mut out, snapshot.detected_bandwidth_mhz.unwrap_or(0));
    let flags = (snapshot.gap_before as u32)
        | ((snapshot.detected_bandwidth_mhz.map(|mhz| mhz != snapshot.selected_bandwidth_mhz).unwrap_or(false) as u32) << 1);
    push_u32(&mut out, flags);
    push_u32(&mut out, channel_mask);
    push_u32(&mut out, measured_points_per_channel);
    push_u32(&mut out, channel_count);
    push_u32(&mut out, snapshot.decimation as u32);
    push_u32(&mut out, rf_points_per_channel);
    push_f64(&mut out, snapshot.sample_rate_hz);
    push_f64(
        &mut out,
        snapshot.requested_window_us,
    );
    push_f64(&mut out, snapshot.center_mhz);
    push_f64(&mut out, snapshot.expected_mhz);
    push_f64(&mut out, snapshot.dac_mhz);
    push_f64(&mut out, snapshot.expected_baseband_mhz);
    push_f64(&mut out, snapshot.rf_samples_per_cycle);
    push_f64(&mut out, snapshot.baseband_samples_per_cycle);
    push_f64(&mut out, snapshot.rf_window_cycles);
    push_f64(&mut out, snapshot.captured_window_us);
    while out.len() < WAVEFORM_BINARY_HEADER_BYTES as usize {
        out.push(0);
    }
    for channel in &snapshot.channels {
        for value in channel.x_us.iter().take(measured_points_per_channel as usize) {
            out.extend_from_slice(&value.to_le_bytes());
        }
        for value in channel.i.iter().take(measured_points_per_channel as usize) {
            out.extend_from_slice(&value.to_le_bytes());
        }
        for value in channel.q.iter().take(measured_points_per_channel as usize) {
            out.extend_from_slice(&value.to_le_bytes());
        }
        for value in channel.mag.iter().take(measured_points_per_channel as usize) {
            out.extend_from_slice(&value.to_le_bytes());
        }
        for value in channel.sample_rf.iter().take(measured_points_per_channel as usize) {
            out.extend_from_slice(&value.to_le_bytes());
        }
        for value in channel.rf_x_us.iter().take(rf_points_per_channel as usize) {
            out.extend_from_slice(&value.to_le_bytes());
        }
        for value in channel.rf.iter().take(rf_points_per_channel as usize) {
            out.extend_from_slice(&value.to_le_bytes());
        }
    }
    out
}

fn encode_spectrum_binary(snapshot: &SpectrumSnapshot) -> Vec<u8> {
    let lane_count = snapshot.lanes.len() as u32;
    let bins_per_lane = snapshot
        .lanes
        .iter()
        .map(|lane| lane.amplitude.len().min(lane.phase_rad.len()).min(lane.power_db.len()))
        .min()
        .unwrap_or(0) as u32;
    let mut out = Vec::with_capacity(128 + lane_count as usize * bins_per_lane as usize * 12);
    push_u32(&mut out, SPECTRUM_MAGIC);
    push_u16(&mut out, 2);
    push_u16(&mut out, 128);
    push_u64(&mut out, snapshot.sample0);
    push_u64(&mut out, snapshot.frame_id);
    push_u32(&mut out, snapshot.seq_no);
    push_u32(&mut out, snapshot.gap_before as u32);
    push_u32(&mut out, snapshot.chan0);
    push_u32(&mut out, snapshot.chan_count as u32);
    push_u32(&mut out, snapshot.time_count as u32);
    push_u32(&mut out, snapshot.ninput as u32);
    push_u32(&mut out, snapshot.src_port as u32);
    push_u32(&mut out, snapshot.dst_port as u32);
    push_u32(&mut out, lane_count);
    push_u32(&mut out, bins_per_lane);
    push_u32(&mut out, snapshot.product_id as u32);
    push_u32(&mut out, snapshot.nchan as u32);
    push_u32(&mut out, snapshot.block_index as u32);
    push_u32(&mut out, snapshot.block_count as u32);
    push_u32(&mut out, snapshot.pfb_taps as u32);
    push_u32(&mut out, snapshot.fft_shift as u32);
    push_u32(&mut out, snapshot.spec_status_flags);
    push_u32(&mut out, snapshot.spec_sample_rate_hz);
    push_u32(&mut out, snapshot.coverage_blocks);
    push_u32(&mut out, 0);
    push_u64(&mut out, snapshot.coverage_mask_lo);
    push_u64(&mut out, snapshot.coverage_mask_hi);
    while out.len() < 128 {
        out.push(0);
    }
    for lane in &snapshot.lanes {
        for value in lane.amplitude.iter().take(bins_per_lane as usize) {
            out.extend_from_slice(&value.to_le_bytes());
        }
        for value in lane.phase_rad.iter().take(bins_per_lane as usize) {
            out.extend_from_slice(&value.to_le_bytes());
        }
        for value in lane.power_db.iter().take(bins_per_lane as usize) {
            out.extend_from_slice(&value.to_le_bytes());
        }
    }
    out
}

fn push_u16(out: &mut Vec<u8>, value: u16) {
    out.extend_from_slice(&value.to_le_bytes());
}

fn push_u32(out: &mut Vec<u8>, value: u32) {
    out.extend_from_slice(&value.to_le_bytes());
}

fn push_u64(out: &mut Vec<u8>, value: u64) {
    out.extend_from_slice(&value.to_le_bytes());
}

fn push_f64(out: &mut Vec<u8>, value: f64) {
    out.extend_from_slice(&value.to_le_bytes());
}

struct ReceiverRuntime {
    dst_port_base: u16,
    src_port_base: u16,
    flow_count: usize,
    time_flow_count: usize,
    spec_flow_count: usize,
    spec_layout: SpecLayout,
    shared: Arc<Mutex<SharedState>>,
    stats: ReceiverStats,
    reorder: ReorderTracker,
    flow_previous_headers: Vec<Option<T510Header>>,
    spec_previous_headers: Vec<Option<T510Header>>,
    config: DisplayConfig,
    config_generation: u64,
    last_config_refresh: Instant,
    last_waveform: Instant,
    last_spectrum: Instant,
    waveform_interval: Duration,
    spectrum_interval: Duration,
    display_capture: DisplayCapture,
    last_rate: Instant,
    last_publish: Instant,
    rate_packets: u64,
    rate_bytes: u64,
    rate_time_packets: u64,
    rate_time_bytes: u64,
    rate_spec_packets: u64,
    rate_spec_bytes: u64,
    rate_waveform_updates: u64,
    rate_spectrum_updates: u64,
    rate_flow_packets: Vec<u64>,
    rate_flow_bytes: Vec<u64>,
    nic_reader: NicStatsReader,
}

impl ReceiverRuntime {
    fn new(args: &Args, shared: Arc<Mutex<SharedState>>) -> Self {
        let (config, config_generation) = {
            let guard = shared.lock().unwrap();
            (guard.config.clone(), guard.config_generation)
        };
        Self {
            dst_port_base: args.dst_port_base(),
            src_port_base: args.src_port_base,
            flow_count: args.flow_count_clamped(),
            time_flow_count: args.time_flow_count_clamped(),
            spec_flow_count: args.spec_flow_count_clamped(),
            spec_layout: args.spec_layout,
            shared,
            stats: ReceiverStats::new(args),
            reorder: ReorderTracker::new(args.reorder_window),
            flow_previous_headers: vec![None; args.flow_count_clamped()],
            spec_previous_headers: vec![None; args.flow_count_clamped()],
            config,
            config_generation,
            last_config_refresh: Instant::now(),
            last_waveform: Instant::now(),
            last_spectrum: Instant::now(),
            waveform_interval: Duration::from_secs_f64(1.0 / args.web_fps.clamp(1, 240) as f64),
            spectrum_interval: Duration::from_secs_f64(1.0 / args.web_fps.clamp(1, 240) as f64),
            display_capture: DisplayCapture::new(args.waveform_max_points),
            last_rate: Instant::now(),
            last_publish: Instant::now(),
            rate_packets: 0,
            rate_bytes: 0,
            rate_time_packets: 0,
            rate_time_bytes: 0,
            rate_spec_packets: 0,
            rate_spec_bytes: 0,
            rate_waveform_updates: 0,
            rate_spectrum_updates: 0,
            rate_flow_packets: vec![0; args.flow_count_clamped()],
            rate_flow_bytes: vec![0; args.flow_count_clamped()],
            nic_reader: NicStatsReader::new(&args.interface),
        }
    }

    fn process_input(&mut self, frame_or_payload: &[u8], input_kind: InputKind) {
        self.stats.total_packets = self.stats.total_packets.saturating_add(1);
        self.stats.total_bytes = self.stats.total_bytes.saturating_add(frame_or_payload.len() as u64);
        self.rate_packets = self.rate_packets.saturating_add(1);
        self.rate_bytes = self.rate_bytes.saturating_add(frame_or_payload.len() as u64);

        self.refresh_config_if_due();

        let (udp_payload, src_port, dst_port) = match input_kind {
            InputKind::Ethernet => match ethernet_ipv4_udp_payload_range_fast(
                frame_or_payload,
                self.dst_port_base,
                self.flow_count as u16,
            ) {
                Ok(view) => (view.payload, view.src_port, view.dst_port),
                Err(_) => {
                    self.stats.filtered_packets = self.stats.filtered_packets.saturating_add(1);
                    self.publish_if_due();
                    return;
                }
            },
            InputKind::UdpPayload => (frame_or_payload, self.src_port_base, self.dst_port_base),
        };

        let header = match parse_t510_header_fast(udp_payload) {
            Ok(header) => header,
            Err(err) => {
                self.stats.parse_errors = self.stats.parse_errors.saturating_add(1);
                if self.stats.parse_errors < 16 || self.stats.parse_errors.is_power_of_two() {
                    self.stats.last_error = Some(format_fast_error(err));
                }
                self.publish_if_due();
                return;
            }
        };

        match header.stream_type {
            STREAM_TIME => {
                if let Err(err) = validate_time_header_fast(&header, udp_payload.len()) {
                    self.stats.parse_errors = self.stats.parse_errors.saturating_add(1);
                    if self.stats.parse_errors < 16 || self.stats.parse_errors.is_power_of_two() {
                        self.stats.last_error = Some(format_fast_error(err));
                    }
                    self.publish_if_due();
                    return;
                }
                self.process_time_packet(header, udp_payload, src_port, dst_port);
            }
            STREAM_SPEC => {
                if let Err(err) = validate_spec_header_fast(&header, udp_payload.len()) {
                    self.stats.parse_errors = self.stats.parse_errors.saturating_add(1);
                    let message = format_fast_error(err);
                    if self.stats.parse_errors < 16 || self.stats.parse_errors.is_power_of_two() {
                        self.stats.last_error = Some(message.clone());
                    }
                    record_spec_preview_error(&self.shared, Some(&header), message);
                    self.publish_if_due();
                    return;
                }
                if !self.spec_layout.matches(&header) {
                    self.stats.parse_errors = self.stats.parse_errors.saturating_add(1);
                    let message = format!(
                        "SPEC layout {:?} rejected header block_count={} chan_count={} time_count={} taps={} flags=0x{:08x}",
                        self.spec_layout,
                        header.block_count,
                        header.chan_count,
                        header.time_count,
                        header.pfb_taps,
                        header.spec_status_flags
                    );
                    self.stats.last_error = Some(message.clone());
                    record_spec_preview_error(&self.shared, Some(&header), message);
                    self.publish_if_due();
                    return;
                }
                self.process_spec_packet(header, udp_payload, src_port, dst_port);
            }
            other => {
                self.stats.filtered_packets = self.stats.filtered_packets.saturating_add(1);
                self.stats.last_error = Some(format!("unsupported T510 stream_type={other}"));
            }
        }

        self.publish_if_due();
    }

    fn process_time_packet(&mut self, header: T510Header, udp_payload: &[u8], src_port: u16, dst_port: u16) {
        self.stats.time_packets = self.stats.time_packets.saturating_add(1);
        self.stats.time_bytes = self.stats.time_bytes.saturating_add(udp_payload.len() as u64);
        self.rate_time_packets = self.rate_time_packets.saturating_add(1);
        self.rate_time_bytes = self.rate_time_bytes.saturating_add(udp_payload.len() as u64);
        self.stats.last_time_count = Some(header.time_count);

        let selected = self.config.bandwidth_mode();
        let flow_id = dst_port.saturating_sub(self.dst_port_base) as usize;
        if flow_id < self.flow_count {
            self.update_flow_stats(flow_id, header, udp_payload.len() as u64, src_port);
        }
        let (detected, gap_before) = self.reorder.ingest(header, selected, &mut self.stats);
        self.stats.selected_bandwidth_mhz = selected.mhz();
        if let Some(mode) = detected {
            self.stats.detected_bandwidth_mhz = Some(mode.mhz());
        } else {
            self.stats.detected_bandwidth_mhz = per_flow_detected_consensus(&self.stats.per_flow);
        }
        self.stats.selected_detected_mismatch = self
            .stats
            .detected_bandwidth_mhz
            .and_then(BandwidthMode::from_mhz)
            .map(|mode| mode.mhz() != selected.mhz())
            .unwrap_or(false);

        let display_enabled = self.config.needs_time()
            && self.stats.waveform_websocket_clients > 0
            && !self.config.paused;
        if display_enabled && self.last_waveform.elapsed() >= self.waveform_interval && !self.display_capture.active {
            self.display_capture.arm();
        }
        if !display_enabled && self.display_capture.active {
            self.display_capture.active = false;
            self.display_capture.start_seq = None;
            self.display_capture.packets.clear();
        }
        if display_enabled {
            if let Some(packets) = self.display_capture.ingest(
                    header,
                    udp_payload,
                    &self.config,
                self.stats
                    .detected_bandwidth_mhz
                    .and_then(BandwidthMode::from_mhz),
                    gap_before,
                    1,
            ) {
                match build_waveform_from_packets(&packets, &self.config) {
                    Ok(waveform) => {
                        self.stats.waveform_updates = self.stats.waveform_updates.saturating_add(1);
                        self.rate_waveform_updates = self.rate_waveform_updates.saturating_add(1);
                        self.update_channel_stats(&waveform);
                        let seq_end = packets
                            .last()
                            .map(|packet| packet.header.seq_no)
                            .unwrap_or(waveform.seq_no);
                        let binary = encode_waveform_binary(&waveform, seq_end);
                        if let Ok(mut guard) = self.shared.lock() {
                            guard.waveform = Some(waveform);
                            guard.waveform_binary = Some(binary);
                            guard.waveform_updated = Some(Instant::now());
                        }
                    }
                    Err(err) => {
                        self.stats.last_error = Some(err);
                    }
                }
                self.last_waveform = Instant::now();
            }
        }
    }

    fn process_spec_packet(&mut self, header: T510Header, udp_payload: &[u8], src_port: u16, dst_port: u16) {
        self.stats.spec_packets = self.stats.spec_packets.saturating_add(1);
        self.stats.spec_bytes = self.stats.spec_bytes.saturating_add(udp_payload.len() as u64);
        self.rate_spec_packets = self.rate_spec_packets.saturating_add(1);
        self.rate_spec_bytes = self.rate_spec_bytes.saturating_add(udp_payload.len() as u64);
        self.stats.last_spec_seq_no = Some(header.seq_no);
        self.stats.last_spec_frame_id = Some(header.frame_id);
        self.stats.last_spec_sample0 = Some(header.sample0);
        self.stats.last_spec_chan0 = Some(header.chan0);
        self.stats.last_spec_chan_count = Some(header.chan_count);

        let flow_id = dst_port.saturating_sub(self.dst_port_base) as usize;
        let gap_before = if flow_id < self.flow_count {
            self.update_spec_flow_stats(flow_id, header, udp_payload.len() as u64, src_port)
        } else {
            false
        };

        let display_enabled = spectrum_preview_enabled(&self.config);
        let should_decode = if display_enabled {
            self.shared
                .lock()
                .map(|mut guard| {
                    guard
                        .spectrum_preview
                        .should_decode(&header, self.spectrum_interval)
                })
                .unwrap_or(false)
        } else {
            false
        };
        if should_decode {
            match t510_time_rx::decode_spectrum_snapshot(
                udp_payload,
                &header,
                src_port,
                dst_port,
                gap_before,
            ) {
                Ok(block) => {
                    if let Ok(mut guard) = self.shared.lock() {
                        if let Some(spectrum) = guard
                            .spectrum_preview
                            .ingest(&block, self.spectrum_interval)
                        {
                            self.stats.spectrum_updates =
                                self.stats.spectrum_updates.saturating_add(1);
                            self.rate_spectrum_updates =
                                self.rate_spectrum_updates.saturating_add(1);
                        let binary = encode_spectrum_binary(&spectrum);
                        guard.spectrum = Some(spectrum);
                        guard.spectrum_binary = Some(binary);
                        guard.spectrum_updated = Some(Instant::now());
                        self.last_spectrum = Instant::now();
                        }
                    }
                }
                Err(err) => {
                    self.stats.last_error = Some(err.clone());
                    record_spec_preview_error(&self.shared, Some(&header), err);
                }
            }
        }
    }

    fn update_flow_stats(&mut self, flow_id: usize, header: T510Header, payload_len: u64, src_port: u16) {
        if let Some(flow) = self.stats.per_flow.get_mut(flow_id) {
            flow.src_port = src_port;
            flow.time_packets = flow.time_packets.saturating_add(1);
            flow.time_bytes = flow.time_bytes.saturating_add(payload_len);
            if let Some(prev) = self.flow_previous_headers[flow_id] {
                let expected_seq_delta = self.time_flow_count as u32;
                if header.seq_no.wrapping_sub(prev.seq_no) != expected_seq_delta {
                    flow.seq_gaps = flow.seq_gaps.saturating_add(1);
                }
                if header.frame_id.wrapping_sub(prev.frame_id) != self.time_flow_count as u64 {
                    flow.frame_gaps = flow.frame_gaps.saturating_add(1);
                }
                let sample_delta = header.sample0.wrapping_sub(prev.sample0);
                let single_delta = expected_sample0_delta(&header, self.config.bandwidth_mode());
                if self.time_flow_count > 0 && sample_delta % self.time_flow_count as u64 == 0 {
                    if let Some(mode) = infer_bandwidth_from_sample0_delta(&header, sample_delta / self.time_flow_count as u64) {
                        flow.detected_bandwidth_mhz = Some(mode.mhz());
                    }
                }
                if sample_delta != single_delta.saturating_mul(self.time_flow_count as u64) {
                    flow.sample0_gaps = flow.sample0_gaps.saturating_add(1);
                }
            }
            flow.last_seq_no = Some(header.seq_no);
            flow.last_frame_id = Some(header.frame_id);
            flow.last_sample0 = Some(header.sample0);
        }
        if let Some(count) = self.rate_flow_packets.get_mut(flow_id) {
            *count = count.saturating_add(1);
        }
        if let Some(bytes) = self.rate_flow_bytes.get_mut(flow_id) {
            *bytes = bytes.saturating_add(payload_len);
        }
        if let Some(prev) = self.flow_previous_headers.get_mut(flow_id) {
            *prev = Some(header);
        }
    }

    fn update_spec_flow_stats(&mut self, flow_id: usize, header: T510Header, payload_len: u64, src_port: u16) -> bool {
        let mut gap = false;
        if let Some(flow) = self.stats.per_flow.get_mut(flow_id) {
            flow.src_port = src_port;
            flow.spec_packets = flow.spec_packets.saturating_add(1);
            flow.spec_bytes = flow.spec_bytes.saturating_add(payload_len);
            if let Some(prev) = self.spec_previous_headers[flow_id] {
                let expected_delta = self.spec_flow_count.max(1) as u32;
                let seq_delta = header.seq_no.wrapping_sub(prev.seq_no);
                if seq_delta != expected_delta {
                    flow.spec_seq_gaps = flow.spec_seq_gaps.saturating_add(1);
                    self.stats.spec_seq_gaps = self.stats.spec_seq_gaps.saturating_add(1);
                    gap = true;
                }
                let frame_delta = header.frame_id.wrapping_sub(prev.frame_id);
                if frame_delta != self.spec_flow_count.max(1) as u64 {
                    flow.spec_frame_gaps = flow.spec_frame_gaps.saturating_add(1);
                    self.stats.spec_frame_gaps = self.stats.spec_frame_gaps.saturating_add(1);
                    gap = true;
                }
            }
            flow.last_spec_seq_no = Some(header.seq_no);
            flow.last_spec_frame_id = Some(header.frame_id);
            flow.last_spec_sample0 = Some(header.sample0);
            flow.last_spec_chan0 = Some(header.chan0);
            flow.last_spec_chan_count = Some(header.chan_count);
        }
        if let Some(count) = self.rate_flow_packets.get_mut(flow_id) {
            *count = count.saturating_add(1);
        }
        if let Some(bytes) = self.rate_flow_bytes.get_mut(flow_id) {
            *bytes = bytes.saturating_add(payload_len);
        }
        if let Some(prev) = self.spec_previous_headers.get_mut(flow_id) {
            *prev = Some(header);
        }
        gap
    }

    fn update_channel_stats(&mut self, waveform: &WaveformSnapshot) {
        self.stats.channel_rms_code = [0.0; TIME_NINPUT];
        self.stats.channel_max_abs_code = [0; TIME_NINPUT];
        self.stats.channel_clipped = [false; TIME_NINPUT];
        for channel in &waveform.channels {
            if channel.channel < TIME_NINPUT {
                self.stats.channel_rms_code[channel.channel] = channel.rms_code;
                self.stats.channel_max_abs_code[channel.channel] = channel.max_abs_code;
                self.stats.channel_clipped[channel.channel] = channel.clipped;
            }
        }
    }

    fn refresh_config_if_due(&mut self) {
        if self.last_config_refresh.elapsed() >= Duration::from_millis(100) {
            if let Ok(guard) = self.shared.lock() {
                if self.config_generation != guard.config_generation {
                    self.config_generation = guard.config_generation;
                    self.display_capture.arm();
                    let now = Instant::now();
                    self.last_waveform = now.checked_sub(self.waveform_interval).unwrap_or(now);
                    self.last_spectrum = now.checked_sub(self.spectrum_interval).unwrap_or(now);
                }
                self.config = guard.config.clone();
                self.stats.websocket_clients = guard.stats.websocket_clients;
                self.stats.waveform_websocket_clients = guard.stats.waveform_websocket_clients;
                self.stats.spectrum_websocket_clients = guard.stats.spectrum_websocket_clients;
            }
            self.last_config_refresh = Instant::now();
        }
    }

    fn update_ring_backlog(&mut self, batch: &MmapBatchStats, block_count: usize) {
        self.stats.ring_fill_blocks = batch.blocks;
        self.stats.ring_fill_percent = if block_count == 0 {
            0.0
        } else {
            (batch.blocks as f64 / block_count as f64 * 100.0).min(100.0)
        };
    }

    fn idle_tick(&mut self) {
        self.refresh_config_if_due();
        self.publish_if_due();
    }

    fn publish_if_due(&mut self) {
        let elapsed = self.last_rate.elapsed();
        if elapsed >= Duration::from_secs(1) {
            let seconds = elapsed.as_secs_f64();
            let mode = self.config.bandwidth_mode();
            self.stats.selected_bandwidth_mhz = mode.mhz();
            self.stats.active_time_flow_count = if self.config.needs_time() { self.time_flow_count } else { 0 };
            self.stats.active_spec_flow_count = if self.config.needs_spec() { self.spec_flow_count } else { 0 };
            self.stats.active_flow_count = self
                .stats
                .active_time_flow_count
                .saturating_add(self.stats.active_spec_flow_count);
            self.stats.detected_bandwidth_mhz = per_flow_detected_consensus(&self.stats.per_flow);
            self.stats.selected_detected_mismatch = self
                .stats
                .detected_bandwidth_mhz
                .map(|mhz| mhz != mode.mhz())
                .unwrap_or(false);
            self.stats.packets_per_sec = self.rate_packets as f64 / seconds;
            self.stats.gbps = self.rate_bytes as f64 * 8.0 / seconds / 1.0e9;
            self.stats.rx_processed_packets_per_sec = self.rate_time_packets as f64 / seconds;
            self.stats.rx_processed_gbps = self.rate_time_bytes as f64 * 8.0 / seconds / 1.0e9;
            self.stats.spec_processed_packets_per_sec = self.rate_spec_packets as f64 / seconds;
            self.stats.spec_processed_gbps = self.rate_spec_bytes as f64 * 8.0 / seconds / 1.0e9;
            self.stats.display_update_hz = self.rate_waveform_updates as f64 / seconds;
            self.stats.spectrum_update_hz = self.rate_spectrum_updates as f64 / seconds;
            for flow_id in 0..self.flow_count {
                if let Some(flow) = self.stats.per_flow.get_mut(flow_id) {
                    let packets = self.rate_flow_packets.get(flow_id).copied().unwrap_or(0);
                    let bytes = self.rate_flow_bytes.get(flow_id).copied().unwrap_or(0);
                    flow.packets_per_sec = packets as f64 / seconds;
                    flow.gbps = bytes as f64 * 8.0 / seconds / 1.0e9;
                }
            }
            let time_count = self.stats.last_time_count.unwrap_or(DEFAULT_TIME_COUNT).max(1) as f64;
            self.stats.expected_packets_per_sec =
                (RAW_SAMPLE_RATE_HZ / mode.decimation() as f64) / (time_count * 4.0);
            let expected_streams = self.config.needs_time() as u8 as f64
                + self.config.needs_spec() as u8 as f64;
            self.stats.expected_time_gbps =
                if self.config.needs_time() { self.stats.expected_packets_per_sec * TIME_UDP_PAYLOAD_BYTES as f64 * 8.0 / 1.0e9 } else { 0.0 };
            self.stats.expected_spec_gbps =
                if self.config.needs_spec() { self.stats.expected_packets_per_sec * TIME_UDP_PAYLOAD_BYTES as f64 * 8.0 / 1.0e9 } else { 0.0 };
            self.stats.expected_fpga_gbps =
                self.stats.expected_packets_per_sec * TIME_UDP_PAYLOAD_BYTES as f64 * 8.0 * expected_streams / 1.0e9;
            let denom = self.stats.time_packets.saturating_add(self.stats.app_drops);
            self.stats.loss_percent = if denom == 0 {
                0.0
            } else {
                self.stats.app_drops as f64 / denom as f64 * 100.0
            };
            self.nic_reader.sample(elapsed, &mut self.stats);
            self.rate_packets = 0;
            self.rate_bytes = 0;
            self.rate_time_packets = 0;
            self.rate_time_bytes = 0;
            self.rate_spec_packets = 0;
            self.rate_spec_bytes = 0;
            self.rate_waveform_updates = 0;
            self.rate_spectrum_updates = 0;
            for value in &mut self.rate_flow_packets {
                *value = 0;
            }
            for value in &mut self.rate_flow_bytes {
                *value = 0;
            }
            self.last_rate = Instant::now();
        }
        if self.last_publish.elapsed() >= Duration::from_millis(100) {
            if let Ok(mut guard) = self.shared.lock() {
                guard.stats = self.stats.clone();
            }
            self.last_publish = Instant::now();
        }
    }
}

#[derive(Debug, Clone)]
struct FanoutWorkerReport {
    worker_id: usize,
    stats: WorkerStats,
    per_flow: Vec<FlowStats>,
}

struct FanoutWorkerConfig {
    worker_id: usize,
    interface: String,
    dst_port_base: u16,
    src_port_base: u16,
    flow_count: usize,
    time_flow_count: usize,
    spec_flow_count: usize,
    spec_layout: SpecLayout,
    options: MmapOptions,
    fanout: PacketFanoutConfig,
    pin_workers: PinWorkers,
    web_fps: u32,
    waveform_max_points: usize,
    shared: Arc<Mutex<SharedState>>,
    tx: mpsc::Sender<FanoutWorkerReport>,
    display_owner: Arc<AtomicUsize>,
    spectrum_gate: Arc<SpectrumPreviewGate>,
}

struct FanoutWorkerRuntime {
    worker_id: usize,
    dst_port_base: u16,
    flow_count: usize,
    time_flow_count: usize,
    spec_flow_count: usize,
    spec_layout: SpecLayout,
    shared: Arc<Mutex<SharedState>>,
    tx: mpsc::Sender<FanoutWorkerReport>,
    display_owner: Arc<AtomicUsize>,
    spectrum_gate: Arc<SpectrumPreviewGate>,
    stats: WorkerStats,
    per_flow: Vec<FlowStats>,
    flow_previous_headers: Vec<Option<T510Header>>,
    spec_previous_headers: Vec<Option<T510Header>>,
    config: DisplayConfig,
    config_generation: u64,
    websocket_clients: u64,
    waveform_websocket_clients: u64,
    spectrum_websocket_clients: u64,
    last_config_refresh: Instant,
    last_waveform: Instant,
    last_spectrum: Instant,
    waveform_interval: Duration,
    spectrum_interval: Duration,
    display_capture: DisplayCapture,
    last_rate: Instant,
    last_report: Instant,
    rate_packets: u64,
    rate_bytes: u64,
    rate_time_packets: u64,
    rate_time_bytes: u64,
    rate_spec_packets: u64,
    rate_spec_bytes: u64,
    rate_waveform_updates: u64,
    rate_spectrum_updates: u64,
    rate_flow_packets: Vec<u64>,
    rate_flow_bytes: Vec<u64>,
}

impl FanoutWorkerRuntime {
    fn new(config: &FanoutWorkerConfig) -> Self {
        let (
            display_config,
            config_generation,
            websocket_clients,
            waveform_websocket_clients,
            spectrum_websocket_clients,
        ) = {
            let guard = config.shared.lock().unwrap();
            (
                guard.config.clone(),
                guard.config_generation,
                guard.stats.websocket_clients,
                guard.stats.waveform_websocket_clients,
                guard.stats.spectrum_websocket_clients,
            )
        };
        Self {
            worker_id: config.worker_id,
            dst_port_base: config.dst_port_base,
            flow_count: config.flow_count,
            time_flow_count: config.time_flow_count,
            spec_flow_count: config.spec_flow_count,
            spec_layout: config.spec_layout,
            shared: config.shared.clone(),
            tx: config.tx.clone(),
            spectrum_gate: config.spectrum_gate.clone(),
            stats: WorkerStats::new(config.worker_id),
            per_flow: (0..config.flow_count)
                .map(|flow_id| {
                    FlowStats::new(
                        flow_id,
                        config.dst_port_base.saturating_add(flow_id as u16),
                        config.src_port_base.saturating_add(flow_id as u16),
                    )
                })
                .collect(),
            flow_previous_headers: vec![None; config.flow_count],
            spec_previous_headers: vec![None; config.flow_count],
            config: display_config,
            config_generation,
            websocket_clients,
            waveform_websocket_clients,
            spectrum_websocket_clients,
            last_config_refresh: Instant::now(),
            last_waveform: Instant::now(),
            last_spectrum: Instant::now(),
            waveform_interval: Duration::from_secs_f64(1.0 / config.web_fps.clamp(1, 240) as f64),
            spectrum_interval: Duration::from_secs_f64(1.0 / config.web_fps.clamp(1, 240) as f64),
            display_capture: DisplayCapture::new(config.waveform_max_points),
            display_owner: config.display_owner.clone(),
            last_rate: Instant::now(),
            last_report: Instant::now(),
            rate_packets: 0,
            rate_bytes: 0,
            rate_time_packets: 0,
            rate_time_bytes: 0,
            rate_spec_packets: 0,
            rate_spec_bytes: 0,
            rate_waveform_updates: 0,
            rate_spectrum_updates: 0,
            rate_flow_packets: vec![0; config.flow_count],
            rate_flow_bytes: vec![0; config.flow_count],
        }
    }

    fn process_frame(&mut self, frame: &[u8]) {
        self.stats.total_packets = self.stats.total_packets.saturating_add(1);
        self.stats.total_bytes = self.stats.total_bytes.saturating_add(frame.len() as u64);
        self.rate_packets = self.rate_packets.saturating_add(1);
        self.rate_bytes = self.rate_bytes.saturating_add(frame.len() as u64);

        self.refresh_config_if_due();

        let view = match ethernet_ipv4_udp_payload_range_fast(
            frame,
            self.dst_port_base,
            self.flow_count as u16,
        ) {
            Ok(view) => view,
            Err(_) => {
                self.stats.filtered_packets = self.stats.filtered_packets.saturating_add(1);
                self.publish_if_due();
                return;
            }
        };

        let header = match parse_t510_header_fast(view.payload) {
            Ok(header) => header,
            Err(err) => {
                self.stats.parse_errors = self.stats.parse_errors.saturating_add(1);
                if self.stats.parse_errors < 16 || self.stats.parse_errors.is_power_of_two() {
                    self.stats.last_error = Some(format_fast_error(err));
                }
                self.publish_if_due();
                return;
            }
        };

        match header.stream_type {
            STREAM_TIME => {
                if let Err(err) = validate_time_header_fast(&header, view.payload.len()) {
                    self.stats.parse_errors = self.stats.parse_errors.saturating_add(1);
                    if self.stats.parse_errors < 16 || self.stats.parse_errors.is_power_of_two() {
                        self.stats.last_error = Some(format_fast_error(err));
                    }
                    self.publish_if_due();
                    return;
                }
                self.process_time_packet(header, view.payload, view.src_port, view.dst_port);
            }
            STREAM_SPEC => {
                if let Err(err) = validate_spec_header_fast(&header, view.payload.len()) {
                    self.stats.parse_errors = self.stats.parse_errors.saturating_add(1);
                    let message = format_fast_error(err);
                    if self.stats.parse_errors < 16 || self.stats.parse_errors.is_power_of_two() {
                        self.stats.last_error = Some(message.clone());
                    }
                    record_spec_preview_error(&self.shared, Some(&header), message);
                    self.publish_if_due();
                    return;
                }
                if !self.spec_layout.matches(&header) {
                    self.stats.parse_errors = self.stats.parse_errors.saturating_add(1);
                    let message = format!(
                        "SPEC layout {:?} rejected header block_count={} chan_count={} time_count={} taps={} flags=0x{:08x}",
                        self.spec_layout,
                        header.block_count,
                        header.chan_count,
                        header.time_count,
                        header.pfb_taps,
                        header.spec_status_flags
                    );
                    self.stats.last_error = Some(message.clone());
                    record_spec_preview_error(&self.shared, Some(&header), message);
                    self.publish_if_due();
                    return;
                }
                self.process_spec_packet(header, view.payload, view.src_port, view.dst_port);
            }
            other => {
                self.stats.filtered_packets = self.stats.filtered_packets.saturating_add(1);
                self.stats.last_error = Some(format!("unsupported T510 stream_type={other}"));
            }
        }

        self.publish_if_due();
    }

    fn process_time_packet(&mut self, header: T510Header, udp_payload: &[u8], src_port: u16, dst_port: u16) {
        self.stats.time_packets = self.stats.time_packets.saturating_add(1);
        self.stats.time_bytes = self.stats.time_bytes.saturating_add(udp_payload.len() as u64);
        self.rate_time_packets = self.rate_time_packets.saturating_add(1);
        self.rate_time_bytes = self.rate_time_bytes.saturating_add(udp_payload.len() as u64);
        self.stats.last_seq_no = Some(header.seq_no);
        self.stats.last_frame_id = Some(header.frame_id);
        self.stats.last_sample0 = Some(header.sample0);
        self.stats.last_time_count = Some(header.time_count);

        let flow_id = dst_port.saturating_sub(self.dst_port_base) as usize;
        let selected = self.config.bandwidth_mode();
        let mut detected = None;
        let mut gap_before = false;
        if flow_id < self.flow_count {
            let (flow_detected, flow_gap) =
                self.update_flow_stats(flow_id, header, udp_payload.len() as u64, src_port, selected);
            detected = flow_detected;
            gap_before = flow_gap;
        }
        if let Some(mode) = detected {
            self.stats.detected_bandwidth_mhz = Some(mode.mhz());
        } else {
            self.stats.detected_bandwidth_mhz = per_flow_detected_consensus(&self.per_flow);
        }

        let display_enabled = self.config.needs_time() && !self.config.paused && self.is_display_owner();
        if display_enabled && self.last_waveform.elapsed() >= self.waveform_interval && !self.display_capture.active {
            self.display_capture.arm();
        }
        if !display_enabled && self.display_capture.active {
            self.display_capture.active = false;
            self.display_capture.start_seq = None;
            self.display_capture.packets.clear();
        }
        if display_enabled {
            if let Some(packets) = self.display_capture.ingest(
                header,
                udp_payload,
                &self.config,
                detected,
                gap_before,
                self.time_flow_count as u32,
            ) {
                match build_waveform_from_packets(&packets, &self.config) {
                    Ok(waveform) => {
                        self.rate_waveform_updates = self.rate_waveform_updates.saturating_add(1);
                        let seq_end = packets.last().map(|packet| packet.header.seq_no).unwrap_or(waveform.seq_no);
                        let binary = encode_waveform_binary(&waveform, seq_end);
                        if let Ok(mut guard) = self.shared.lock() {
                            guard.waveform = Some(waveform);
                            guard.waveform_binary = Some(binary);
                            guard.waveform_updated = Some(Instant::now());
                        }
                    }
                    Err(err) => {
                        self.stats.last_error = Some(err);
                    }
                }
                self.last_waveform = Instant::now();
            }
        }
    }

    fn process_spec_packet(&mut self, header: T510Header, udp_payload: &[u8], src_port: u16, dst_port: u16) {
        self.stats.spec_packets = self.stats.spec_packets.saturating_add(1);
        self.stats.spec_bytes = self.stats.spec_bytes.saturating_add(udp_payload.len() as u64);
        self.rate_spec_packets = self.rate_spec_packets.saturating_add(1);
        self.rate_spec_bytes = self.rate_spec_bytes.saturating_add(udp_payload.len() as u64);
        self.stats.last_spec_seq_no = Some(header.seq_no);
        self.stats.last_spec_frame_id = Some(header.frame_id);
        self.stats.last_spec_sample0 = Some(header.sample0);
        self.stats.last_spec_chan0 = Some(header.chan0);
        self.stats.last_spec_chan_count = Some(header.chan_count);

        let flow_id = dst_port.saturating_sub(self.dst_port_base) as usize;
        let gap_before = if flow_id < self.flow_count {
            self.update_spec_flow_stats(flow_id, header, udp_payload.len() as u64, src_port)
        } else {
            false
        };

        let display_enabled = spectrum_preview_enabled(&self.config);
        let should_decode = display_enabled && self.spectrum_gate.should_decode(&header, self.spectrum_interval);
        if should_decode {
            match t510_time_rx::decode_spectrum_snapshot(udp_payload, &header, src_port, dst_port, gap_before) {
                Ok(block) => {
                    if let Ok(mut guard) = self.shared.lock() {
                        if let Some(spectrum) = guard.spectrum_preview.ingest(&block, self.spectrum_interval) {
                            self.rate_spectrum_updates = self.rate_spectrum_updates.saturating_add(1);
                            self.spectrum_gate.mark_complete();
                            let binary = encode_spectrum_binary(&spectrum);
                            guard.spectrum = Some(spectrum);
                            guard.spectrum_binary = Some(binary);
                            guard.spectrum_updated = Some(Instant::now());
                            self.last_spectrum = Instant::now();
                        }
                    }
                }
                Err(err) => {
                    self.stats.last_error = Some(err.clone());
                    record_spec_preview_error(&self.shared, Some(&header), err);
                }
            }
        }
    }

    fn update_flow_stats(
        &mut self,
        flow_id: usize,
        header: T510Header,
        payload_len: u64,
        src_port: u16,
        selected: BandwidthMode,
    ) -> (Option<BandwidthMode>, bool) {
        let mut detected = None;
        let mut gap = false;
        if let Some(flow) = self.per_flow.get_mut(flow_id) {
            flow.src_port = src_port;
            flow.time_packets = flow.time_packets.saturating_add(1);
            flow.time_bytes = flow.time_bytes.saturating_add(payload_len);
            if let Some(prev) = self.flow_previous_headers[flow_id] {
                let expected_seq_delta = self.time_flow_count as u32;
                let seq_delta = header.seq_no.wrapping_sub(prev.seq_no);
                if seq_delta != expected_seq_delta {
                    flow.seq_gaps = flow.seq_gaps.saturating_add(1);
                    self.stats.seq_gaps = self.stats.seq_gaps.saturating_add(1);
                    if seq_delta > expected_seq_delta && expected_seq_delta > 0 {
                        self.stats.app_drops = self
                            .stats
                            .app_drops
                            .saturating_add((seq_delta / expected_seq_delta).saturating_sub(1) as u64);
                    } else {
                        self.stats.app_drops = self.stats.app_drops.saturating_add(1);
                    }
                    gap = true;
                }
                if header.frame_id.wrapping_sub(prev.frame_id) != self.time_flow_count as u64 {
                    flow.frame_gaps = flow.frame_gaps.saturating_add(1);
                    self.stats.frame_gaps = self.stats.frame_gaps.saturating_add(1);
                    gap = true;
                }
                let sample_delta = header.sample0.wrapping_sub(prev.sample0);
                if self.time_flow_count > 0 && sample_delta % self.time_flow_count as u64 == 0 {
                    detected = infer_bandwidth_from_sample0_delta(&header, sample_delta / self.time_flow_count as u64);
                    if let Some(mode) = detected {
                        flow.detected_bandwidth_mhz = Some(mode.mhz());
                    }
                }
                let expected_sample_delta =
                    expected_sample0_delta(&header, selected).saturating_mul(self.time_flow_count as u64);
                if sample_delta != expected_sample_delta {
                    flow.sample0_gaps = flow.sample0_gaps.saturating_add(1);
                    self.stats.sample0_gaps = self.stats.sample0_gaps.saturating_add(1);
                    gap = true;
                }
            }
            flow.last_seq_no = Some(header.seq_no);
            flow.last_frame_id = Some(header.frame_id);
            flow.last_sample0 = Some(header.sample0);
        }
        if let Some(count) = self.rate_flow_packets.get_mut(flow_id) {
            *count = count.saturating_add(1);
        }
        if let Some(bytes) = self.rate_flow_bytes.get_mut(flow_id) {
            *bytes = bytes.saturating_add(payload_len);
        }
        if let Some(prev) = self.flow_previous_headers.get_mut(flow_id) {
            *prev = Some(header);
        }
        (detected, gap)
    }

    fn update_spec_flow_stats(&mut self, flow_id: usize, header: T510Header, payload_len: u64, src_port: u16) -> bool {
        let mut gap = false;
        if let Some(flow) = self.per_flow.get_mut(flow_id) {
            flow.src_port = src_port;
            flow.spec_packets = flow.spec_packets.saturating_add(1);
            flow.spec_bytes = flow.spec_bytes.saturating_add(payload_len);
            if let Some(prev) = self.spec_previous_headers[flow_id] {
                let expected_delta = self.spec_flow_count.max(1) as u32;
                let seq_delta = header.seq_no.wrapping_sub(prev.seq_no);
                if seq_delta != expected_delta {
                    flow.spec_seq_gaps = flow.spec_seq_gaps.saturating_add(1);
                    self.stats.spec_seq_gaps = self.stats.spec_seq_gaps.saturating_add(1);
                    gap = true;
                }
                let frame_delta = header.frame_id.wrapping_sub(prev.frame_id);
                if frame_delta != self.spec_flow_count.max(1) as u64 {
                    flow.spec_frame_gaps = flow.spec_frame_gaps.saturating_add(1);
                    self.stats.spec_frame_gaps = self.stats.spec_frame_gaps.saturating_add(1);
                    gap = true;
                }
            }
            flow.last_spec_seq_no = Some(header.seq_no);
            flow.last_spec_frame_id = Some(header.frame_id);
            flow.last_spec_sample0 = Some(header.sample0);
            flow.last_spec_chan0 = Some(header.chan0);
            flow.last_spec_chan_count = Some(header.chan_count);
        }
        if let Some(count) = self.rate_flow_packets.get_mut(flow_id) {
            *count = count.saturating_add(1);
        }
        if let Some(bytes) = self.rate_flow_bytes.get_mut(flow_id) {
            *bytes = bytes.saturating_add(payload_len);
        }
        if let Some(prev) = self.spec_previous_headers.get_mut(flow_id) {
            *prev = Some(header);
        }
        gap
    }

    fn refresh_config_if_due(&mut self) {
        if self.last_config_refresh.elapsed() >= Duration::from_millis(100) {
            if let Ok(guard) = self.shared.lock() {
                if self.config_generation != guard.config_generation {
                    self.config_generation = guard.config_generation;
                    self.display_capture.arm();
                    if self.worker_id == 0 {
                        self.spectrum_gate.reset();
                    }
                    let now = Instant::now();
                    self.last_waveform = now.checked_sub(self.waveform_interval).unwrap_or(now);
                    self.last_spectrum = now.checked_sub(self.spectrum_interval).unwrap_or(now);
                }
                self.config = guard.config.clone();
                self.websocket_clients = guard.stats.websocket_clients;
                self.waveform_websocket_clients = guard.stats.waveform_websocket_clients;
                self.spectrum_websocket_clients = guard.stats.spectrum_websocket_clients;
            }
            self.last_config_refresh = Instant::now();
        }
    }

    fn is_display_owner(&self) -> bool {
        match self.display_owner.compare_exchange(
            NO_DISPLAY_OWNER,
            self.worker_id,
            Ordering::AcqRel,
            Ordering::Acquire,
        ) {
            Ok(_) => true,
            Err(owner) => owner == self.worker_id,
        }
    }

    fn update_ring_backlog(&mut self, batch: &MmapBatchStats, block_count: usize) {
        self.stats.ring_fill_blocks = batch.blocks;
        self.stats.ring_fill_percent = if block_count == 0 {
            0.0
        } else {
            (batch.blocks as f64 / block_count as f64 * 100.0).min(100.0)
        };
    }

    fn idle_tick(&mut self) {
        self.refresh_config_if_due();
        self.publish_if_due();
    }

    fn publish_if_due(&mut self) {
        let elapsed = self.last_rate.elapsed();
        if elapsed >= Duration::from_secs(1) {
            let seconds = elapsed.as_secs_f64();
            self.stats.packets_per_sec = self.rate_packets as f64 / seconds;
            self.stats.gbps = self.rate_bytes as f64 * 8.0 / seconds / 1.0e9;
            self.stats.rx_processed_packets_per_sec = self.rate_time_packets as f64 / seconds;
            self.stats.rx_processed_gbps = self.rate_time_bytes as f64 * 8.0 / seconds / 1.0e9;
            self.stats.spec_processed_packets_per_sec = self.rate_spec_packets as f64 / seconds;
            self.stats.spec_processed_gbps = self.rate_spec_bytes as f64 * 8.0 / seconds / 1.0e9;
            self.stats.display_update_hz = self.rate_waveform_updates as f64 / seconds;
            self.stats.spectrum_update_hz = self.rate_spectrum_updates as f64 / seconds;
            for flow_id in 0..self.flow_count {
                if let Some(flow) = self.per_flow.get_mut(flow_id) {
                    let packets = self.rate_flow_packets.get(flow_id).copied().unwrap_or(0);
                    let bytes = self.rate_flow_bytes.get(flow_id).copied().unwrap_or(0);
                    flow.packets_per_sec = packets as f64 / seconds;
                    flow.gbps = bytes as f64 * 8.0 / seconds / 1.0e9;
                }
            }
            self.stats.detected_bandwidth_mhz = per_flow_detected_consensus(&self.per_flow);
            self.stats.waveform_updates = self
                .stats
                .waveform_updates
                .saturating_add(self.rate_waveform_updates);
            self.stats.spectrum_updates = self
                .stats
                .spectrum_updates
                .saturating_add(self.rate_spectrum_updates);
            self.rate_packets = 0;
            self.rate_bytes = 0;
            self.rate_time_packets = 0;
            self.rate_time_bytes = 0;
            self.rate_spec_packets = 0;
            self.rate_spec_bytes = 0;
            self.rate_waveform_updates = 0;
            self.rate_spectrum_updates = 0;
            for value in &mut self.rate_flow_packets {
                *value = 0;
            }
            for value in &mut self.rate_flow_bytes {
                *value = 0;
            }
            self.last_rate = Instant::now();
        }
        if self.last_report.elapsed() >= Duration::from_millis(100) {
            let _ = self.tx.send(FanoutWorkerReport {
                worker_id: self.worker_id,
                stats: self.stats.clone(),
                per_flow: self.per_flow.clone(),
            });
            self.last_report = Instant::now();
        }
    }

    fn force_report(&mut self) {
        let _ = self.tx.send(FanoutWorkerReport {
            worker_id: self.worker_id,
            stats: self.stats.clone(),
            per_flow: self.per_flow.clone(),
        });
    }
}

fn run_fanout_worker(config: FanoutWorkerConfig) {
    let mut runtime = FanoutWorkerRuntime::new(&config);
    if config.pin_workers == PinWorkers::Auto {
        if let Err(err) = pin_current_thread(config.worker_id) {
            runtime.stats.last_error = Some(format!("worker {} CPU pin failed: {err}", config.worker_id));
        }
    }
    let mut socket = match MmapPacketSocket::open_with_fanout(
        &config.interface,
        config.options,
        config.dst_port_base,
        config.flow_count,
        Some(config.fanout),
    ) {
        Ok(socket) => socket,
        Err(err) => {
            runtime.stats.last_error = Some(format!("worker {} fanout socket open failed: {err}", config.worker_id));
            runtime.force_report();
            return;
        }
    };
    runtime.force_report();
    loop {
        let batch = match socket.drain(|frame| runtime.process_frame(frame)) {
            Ok(batch) => batch,
            Err(err) => {
                runtime.stats.last_error = Some(format!("worker {} mmap drain failed: {err}", config.worker_id));
                runtime.force_report();
                return;
            }
        };
        runtime.update_ring_backlog(&batch, socket.options.block_count);
        socket.poll_kernel_stats_if_due_worker(&mut runtime.stats);
        if batch.packets == 0 {
            runtime.idle_tick();
        }
    }
}

fn merge_flow_stats(dst: &mut FlowStats, src: &FlowStats) {
    let dst_was_inactive = dst.packets_per_sec <= 0.5;
    let src_active = src.packets_per_sec > 0.5;
    dst.time_packets = dst.time_packets.saturating_add(src.time_packets);
    dst.time_bytes = dst.time_bytes.saturating_add(src.time_bytes);
    dst.spec_packets = dst.spec_packets.saturating_add(src.spec_packets);
    dst.spec_bytes = dst.spec_bytes.saturating_add(src.spec_bytes);
    dst.packets_per_sec += src.packets_per_sec;
    dst.gbps += src.gbps;
    dst.seq_gaps = dst.seq_gaps.saturating_add(src.seq_gaps);
    dst.frame_gaps = dst.frame_gaps.saturating_add(src.frame_gaps);
    dst.sample0_gaps = dst.sample0_gaps.saturating_add(src.sample0_gaps);
    dst.spec_seq_gaps = dst.spec_seq_gaps.saturating_add(src.spec_seq_gaps);
    dst.spec_frame_gaps = dst.spec_frame_gaps.saturating_add(src.spec_frame_gaps);
    if src_active || (dst_was_inactive && src.detected_bandwidth_mhz.is_some()) {
        dst.detected_bandwidth_mhz = src.detected_bandwidth_mhz;
    }
    if src.last_seq_no.is_some() && (src_active || dst_was_inactive) {
        dst.last_seq_no = src.last_seq_no;
        dst.last_frame_id = src.last_frame_id;
        dst.last_sample0 = src.last_sample0;
        dst.src_port = src.src_port;
    }
    if src.last_spec_seq_no.is_some() && (src_active || dst_was_inactive || dst.last_spec_seq_no.is_none()) {
        dst.last_spec_seq_no = src.last_spec_seq_no;
        dst.last_spec_frame_id = src.last_spec_frame_id;
        dst.last_spec_sample0 = src.last_spec_sample0;
        dst.last_spec_chan0 = src.last_spec_chan0;
        dst.last_spec_chan_count = src.last_spec_chan_count;
        dst.src_port = src.src_port;
    }
}

fn aggregate_fanout_stats(
    base: &ReceiverStats,
    reports: &[Option<FanoutWorkerReport>],
    config: &DisplayConfig,
    websocket_clients: u64,
    waveform_websocket_clients: u64,
    spectrum_websocket_clients: u64,
) -> ReceiverStats {
    let mut stats = base.clone();
    stats.total_packets = 0;
    stats.time_packets = 0;
    stats.spec_packets = 0;
    stats.total_bytes = 0;
    stats.time_bytes = 0;
    stats.spec_bytes = 0;
    stats.parse_errors = 0;
    stats.filtered_packets = 0;
    stats.kernel_drops = 0;
    stats.ring_drops = 0;
    stats.app_drops = 0;
    stats.seq_gaps = 0;
    stats.frame_gaps = 0;
    stats.sample0_gaps = 0;
    stats.spec_seq_gaps = 0;
    stats.spec_frame_gaps = 0;
    stats.waveform_updates = 0;
    stats.spectrum_updates = 0;
    stats.packets_per_sec = 0.0;
    stats.gbps = 0.0;
    stats.expected_time_gbps = 0.0;
    stats.expected_spec_gbps = 0.0;
    stats.rx_processed_packets_per_sec = 0.0;
    stats.rx_processed_gbps = 0.0;
    stats.spec_processed_packets_per_sec = 0.0;
    stats.spec_processed_gbps = 0.0;
    stats.display_update_hz = 0.0;
    stats.spectrum_update_hz = 0.0;
    stats.ring_fill_blocks = 0;
    stats.ring_fill_percent = 0.0;
    stats.ring_freeze_q_count = 0;
    stats.worker_ring_drops = 0;
    stats.active_worker_count = 0;
    stats.last_seq_no = None;
    stats.last_frame_id = None;
    stats.last_sample0 = None;
    stats.last_time_count = None;
    stats.last_spec_seq_no = None;
    stats.last_spec_frame_id = None;
    stats.last_spec_sample0 = None;
    stats.last_spec_chan0 = None;
    stats.last_spec_chan_count = None;
    stats.detected_bandwidth_mhz = None;
    stats.last_error = None;
    stats.websocket_clients = websocket_clients;
    stats.waveform_websocket_clients = waveform_websocket_clients;
    stats.spectrum_websocket_clients = spectrum_websocket_clients;
    stats.selected_bandwidth_mhz = config.bandwidth_mode().mhz();
    stats.active_time_flow_count = if config.needs_time() { stats.time_flow_count } else { 0 };
    stats.active_spec_flow_count = if config.needs_spec() { stats.spec_flow_count } else { 0 };
    stats.active_flow_count = stats
        .active_time_flow_count
        .saturating_add(stats.active_spec_flow_count);
    stats.per_worker = reports
        .iter()
        .enumerate()
        .map(|(worker_id, report)| {
            report
                .as_ref()
                .map(|report| report.stats.clone())
                .unwrap_or_else(|| WorkerStats::new(worker_id))
        })
        .collect();
    stats.per_flow = (0..stats.flow_count)
        .map(|flow_id| {
            FlowStats::new(
                flow_id,
                stats.dst_port_base.saturating_add(flow_id as u16),
                stats.src_port_base.saturating_add(flow_id as u16),
            )
        })
        .collect();

    for worker in &stats.per_worker {
        stats.total_packets = stats.total_packets.saturating_add(worker.total_packets);
        stats.time_packets = stats.time_packets.saturating_add(worker.time_packets);
        stats.spec_packets = stats.spec_packets.saturating_add(worker.spec_packets);
        stats.total_bytes = stats.total_bytes.saturating_add(worker.total_bytes);
        stats.time_bytes = stats.time_bytes.saturating_add(worker.time_bytes);
        stats.spec_bytes = stats.spec_bytes.saturating_add(worker.spec_bytes);
        stats.parse_errors = stats.parse_errors.saturating_add(worker.parse_errors);
        stats.filtered_packets = stats.filtered_packets.saturating_add(worker.filtered_packets);
        stats.kernel_drops = stats.kernel_drops.saturating_add(worker.kernel_drops);
        stats.ring_drops = stats.ring_drops.saturating_add(worker.ring_drops);
        stats.worker_ring_drops = stats.worker_ring_drops.saturating_add(worker.ring_drops);
        stats.app_drops = stats.app_drops.saturating_add(worker.app_drops);
        stats.seq_gaps = stats.seq_gaps.saturating_add(worker.seq_gaps);
        stats.frame_gaps = stats.frame_gaps.saturating_add(worker.frame_gaps);
        stats.sample0_gaps = stats.sample0_gaps.saturating_add(worker.sample0_gaps);
        stats.spec_seq_gaps = stats.spec_seq_gaps.saturating_add(worker.spec_seq_gaps);
        stats.spec_frame_gaps = stats.spec_frame_gaps.saturating_add(worker.spec_frame_gaps);
        stats.waveform_updates = stats.waveform_updates.saturating_add(worker.waveform_updates);
        stats.spectrum_updates = stats.spectrum_updates.saturating_add(worker.spectrum_updates);
        stats.packets_per_sec += worker.packets_per_sec;
        stats.gbps += worker.gbps;
        stats.rx_processed_packets_per_sec += worker.rx_processed_packets_per_sec;
        stats.rx_processed_gbps += worker.rx_processed_gbps;
        stats.spec_processed_packets_per_sec += worker.spec_processed_packets_per_sec;
        stats.spec_processed_gbps += worker.spec_processed_gbps;
        stats.display_update_hz += worker.display_update_hz;
        stats.spectrum_update_hz += worker.spectrum_update_hz;
        stats.ring_fill_blocks = stats.ring_fill_blocks.saturating_add(worker.ring_fill_blocks);
        stats.ring_fill_percent = stats.ring_fill_percent.max(worker.ring_fill_percent);
        stats.ring_freeze_q_count = stats.ring_freeze_q_count.saturating_add(worker.ring_freeze_q_count);
        if worker.rx_processed_packets_per_sec > 0.5 || worker.spec_processed_packets_per_sec > 0.5 {
            stats.active_worker_count = stats.active_worker_count.saturating_add(1);
        }
        if worker.last_seq_no.is_some() {
            stats.last_seq_no = worker.last_seq_no;
            stats.last_frame_id = worker.last_frame_id;
            stats.last_sample0 = worker.last_sample0;
            stats.last_time_count = worker.last_time_count;
        }
        if worker.last_spec_seq_no.is_some() {
            stats.last_spec_seq_no = worker.last_spec_seq_no;
            stats.last_spec_frame_id = worker.last_spec_frame_id;
            stats.last_spec_sample0 = worker.last_spec_sample0;
            stats.last_spec_chan0 = worker.last_spec_chan0;
            stats.last_spec_chan_count = worker.last_spec_chan_count;
        }
        if stats.last_error.is_none() && worker.last_error.is_some() {
            stats.last_error = worker.last_error.clone();
        }
    }

    for report in reports.iter().flatten() {
        for flow in &report.per_flow {
            if let Some(dst) = stats.per_flow.get_mut(flow.flow_id) {
                merge_flow_stats(dst, flow);
            }
        }
    }
    stats.detected_bandwidth_mhz = per_flow_detected_consensus(&stats.per_flow);
    stats.selected_detected_mismatch = stats
        .detected_bandwidth_mhz
        .map(|mhz| mhz != stats.selected_bandwidth_mhz)
        .unwrap_or(false);
    let time_count = stats.last_time_count.unwrap_or(DEFAULT_TIME_COUNT).max(1) as f64;
    let mode = config.bandwidth_mode();
    stats.expected_packets_per_sec =
        (RAW_SAMPLE_RATE_HZ / mode.decimation() as f64) / (time_count * 4.0);
    let expected_streams = config.needs_time() as u8 as f64 + config.needs_spec() as u8 as f64;
    stats.expected_time_gbps =
        if config.needs_time() { stats.expected_packets_per_sec * TIME_UDP_PAYLOAD_BYTES as f64 * 8.0 / 1.0e9 } else { 0.0 };
    stats.expected_spec_gbps =
        if config.needs_spec() { stats.expected_packets_per_sec * TIME_UDP_PAYLOAD_BYTES as f64 * 8.0 / 1.0e9 } else { 0.0 };
    stats.expected_fpga_gbps =
        stats.expected_packets_per_sec * TIME_UDP_PAYLOAD_BYTES as f64 * 8.0 * expected_streams / 1.0e9;
    let denom = stats.time_packets.saturating_add(stats.app_drops);
    stats.loss_percent = if denom == 0 {
        0.0
    } else {
        stats.app_drops as f64 / denom as f64 * 100.0
    };
    stats
}

fn run_fanout_receiver(args: Args, shared: Arc<Mutex<SharedState>>) -> std::io::Result<()> {
    let options = MmapOptions::from_args(&args)?;
    let worker_count = args.worker_count_clamped();
    let flow_count = args.flow_count_clamped();
    let time_flow_count = args.time_flow_count_clamped();
    let spec_flow_count = args.spec_flow_count_clamped();
    let (tx, rx) = mpsc::channel::<FanoutWorkerReport>();
    let display_owner = Arc::new(AtomicUsize::new(NO_DISPLAY_OWNER));
    let spectrum_gate = Arc::new(SpectrumPreviewGate::default());
    let fanout = PacketFanoutConfig {
        group: args.fanout_group,
        mode: args.fanout_mode,
        worker_count,
    };
    for worker_id in 0..worker_count {
        let worker = FanoutWorkerConfig {
            worker_id,
            interface: args.interface.clone(),
            dst_port_base: args.dst_port_base(),
            src_port_base: args.src_port_base,
            flow_count,
            time_flow_count,
            spec_flow_count,
            spec_layout: args.spec_layout,
            options,
            fanout,
            pin_workers: args.pin_workers,
            web_fps: args.web_fps,
            waveform_max_points: args.waveform_max_points,
            shared: shared.clone(),
            tx: tx.clone(),
            display_owner: display_owner.clone(),
            spectrum_gate: spectrum_gate.clone(),
        };
        thread::spawn(move || run_fanout_worker(worker));
    }
    drop(tx);

    let mut base = ReceiverStats::new(&args);
    base.backend = "fanout".to_string();
    base.worker_count = worker_count;
    base.ring_bytes = (options.ring_bytes as u64).saturating_mul(worker_count as u64);
    base.ring_block_size = options.block_size as u32;
    base.ring_block_count = (options.block_count as u32).saturating_mul(worker_count as u32);
    base.ring_frame_size = options.frame_size as u32;
    base.ring_frame_count = (options.frame_count as u32).saturating_mul(worker_count as u32);

    let mut reports: Vec<Option<FanoutWorkerReport>> = vec![None; worker_count];
    let mut nic_reader = NicStatsReader::new(&args.interface);
    let mut last_nic = Instant::now();
    loop {
        match rx.recv_timeout(Duration::from_millis(100)) {
            Ok(report) => {
                let worker_id = report.worker_id;
                if worker_id < reports.len() {
                    reports[worker_id] = Some(report);
                }
            }
            Err(mpsc::RecvTimeoutError::Timeout) => {}
            Err(mpsc::RecvTimeoutError::Disconnected) => {
                base.last_error = Some("all fanout workers exited".to_string());
            }
        }
        for report in rx.try_iter() {
            let worker_id = report.worker_id;
            if worker_id < reports.len() {
                reports[worker_id] = Some(report);
            }
        }
        let (config, websocket_clients, waveform_websocket_clients, spectrum_websocket_clients) = {
            let guard = shared.lock().unwrap();
            (
                guard.config.clone(),
                guard.stats.websocket_clients,
                guard.stats.waveform_websocket_clients,
                guard.stats.spectrum_websocket_clients,
            )
        };
        let mut stats = aggregate_fanout_stats(
            &base,
            &reports,
            &config,
            websocket_clients,
            waveform_websocket_clients,
            spectrum_websocket_clients,
        );
        let nic_elapsed = last_nic.elapsed();
        if nic_elapsed >= Duration::from_millis(100) {
            nic_reader.sample(nic_elapsed, &mut stats);
            last_nic = Instant::now();
        }
        if let Ok(mut guard) = shared.lock() {
            guard.stats = stats;
        }
    }
}

fn format_fast_error(err: FastPacketError) -> String {
    format!("{:?}", err)
}

fn record_spec_preview_error(
    shared: &Arc<Mutex<SharedState>>,
    header: Option<&T510Header>,
    message: String,
) {
    if let Ok(mut guard) = shared.lock() {
        guard.spectrum_preview.record_error(header, message);
    }
}

fn frame_next(prev: u64, now: u64) -> bool {
    prev.wrapping_add(1) == now
}

fn bind_reuse_tcp_listener(bind: &str) -> std::io::Result<TcpListener> {
    let addr: SocketAddr = bind
        .parse()
        .map_err(|err| std::io::Error::new(std::io::ErrorKind::InvalidInput, err))?;
    let domain = match addr {
        SocketAddr::V4(_) => libc::AF_INET,
        SocketAddr::V6(_) => libc::AF_INET6,
    };
    let fd = unsafe { libc::socket(domain, libc::SOCK_STREAM | libc::SOCK_CLOEXEC, 0) };
    if fd < 0 {
        return Err(std::io::Error::last_os_error());
    }
    let rc = (|| {
        let yes: libc::c_int = 1;
        let set_rc = unsafe {
            libc::setsockopt(
                fd,
                libc::SOL_SOCKET,
                libc::SO_REUSEADDR,
                &yes as *const libc::c_int as *const libc::c_void,
                mem::size_of_val(&yes) as libc::socklen_t,
            )
        };
        if set_rc < 0 {
            return Err(std::io::Error::last_os_error());
        }
        match addr {
            SocketAddr::V4(addr) => {
                let octets = addr.ip().octets();
                let sockaddr = libc::sockaddr_in {
                    sin_family: libc::AF_INET as libc::sa_family_t,
                    sin_port: addr.port().to_be(),
                    sin_addr: libc::in_addr {
                        s_addr: u32::from_ne_bytes(octets),
                    },
                    sin_zero: [0; 8],
                };
                let bind_rc = unsafe {
                    libc::bind(
                        fd,
                        &sockaddr as *const libc::sockaddr_in as *const libc::sockaddr,
                        mem::size_of_val(&sockaddr) as libc::socklen_t,
                    )
                };
                if bind_rc < 0 {
                    return Err(std::io::Error::last_os_error());
                }
            }
            SocketAddr::V6(addr) => {
                let sockaddr = libc::sockaddr_in6 {
                    sin6_family: libc::AF_INET6 as libc::sa_family_t,
                    sin6_port: addr.port().to_be(),
                    sin6_flowinfo: addr.flowinfo(),
                    sin6_addr: libc::in6_addr {
                        s6_addr: addr.ip().octets(),
                    },
                    sin6_scope_id: addr.scope_id(),
                };
                let bind_rc = unsafe {
                    libc::bind(
                        fd,
                        &sockaddr as *const libc::sockaddr_in6 as *const libc::sockaddr,
                        mem::size_of_val(&sockaddr) as libc::socklen_t,
                    )
                };
                if bind_rc < 0 {
                    return Err(std::io::Error::last_os_error());
                }
            }
        }
        let listen_rc = unsafe { libc::listen(fd, 128) };
        if listen_rc < 0 {
            return Err(std::io::Error::last_os_error());
        }
        Ok(())
    })();
    if let Err(err) = rc {
        unsafe {
            libc::close(fd);
        }
        return Err(err);
    }
    Ok(unsafe { TcpListener::from_raw_fd(fd) })
}

fn run_receiver(args: Args, shared: Arc<Mutex<SharedState>>) -> std::io::Result<()> {
    if matches!(args.backend, Backend::Fanout) {
        return run_fanout_receiver(args, shared);
    }
    let mut runtime = ReceiverRuntime::new(&args, shared);

    match args.backend {
        Backend::Fanout => unreachable!("fanout backend is handled before ReceiverRuntime setup"),
        Backend::Mmap => {
            let options = MmapOptions::from_args(&args)?;
            let mut socket = MmapPacketSocket::open(
                &args.interface,
                options,
                args.dst_port_base(),
                args.flow_count_clamped(),
            )?;
            socket.apply_ring_config_to_stats(&mut runtime.stats);
            runtime.publish_if_due();
            loop {
                let batch = socket.drain(|frame| runtime.process_input(frame, InputKind::Ethernet))?;
                runtime.update_ring_backlog(&batch, socket.options.block_count);
                socket.poll_kernel_stats_if_due(&mut runtime.stats);
                if batch.packets == 0 {
                    runtime.idle_tick();
                }
            }
        }
        Backend::Packet => {
            let socket = PacketSocket::open(&args.interface, args.dst_port_base(), args.flow_count_clamped())?;
            let mut buf = vec![0u8; 16 * 1024];
            loop {
                let frame = socket.recv(&mut buf)?;
                runtime.process_input(frame, InputKind::Ethernet);
            }
        }
        Backend::Udp => {
            let socket = UdpSocket::bind(("0.0.0.0", args.dst_port_base()))?;
            let mut buf = vec![0u8; 16 * 1024];
            loop {
                let (len, _) = socket.recv_from(&mut buf)?;
                runtime.process_input(&buf[..len], InputKind::UdpPayload);
            }
        }
    }
}

fn handle_http(mut stream: TcpStream, shared: Arc<Mutex<SharedState>>, web_fps: u32) -> std::io::Result<()> {
    stream.set_read_timeout(Some(Duration::from_millis(200)))?;
    let mut buf = Vec::new();
    let mut tmp = [0u8; 4096];
    loop {
        match stream.read(&mut tmp) {
            Ok(0) => break,
            Ok(n) => {
                buf.extend_from_slice(&tmp[..n]);
                if request_complete(&buf) {
                    break;
                }
                if buf.len() > 64 * 1024 {
                    break;
                }
            }
            Err(err)
                if err.kind() == std::io::ErrorKind::WouldBlock
                    || err.kind() == std::io::ErrorKind::TimedOut =>
            {
                break
            }
            Err(err) => return Err(err),
        }
    }
    let request = String::from_utf8_lossy(&buf);
    let first = request.lines().next().unwrap_or_default();
    if first.starts_with("GET / ") || first.starts_with("GET /index.html ") {
        write_response(&mut stream, "200 OK", "text/html; charset=utf-8", HTML.as_bytes())
    } else if first.starts_with("GET /static/gridstack-all.js ") {
        write_response(
            &mut stream,
            "200 OK",
            "text/javascript; charset=utf-8",
            GRIDSTACK_JS.as_bytes(),
        )
    } else if first.starts_with("GET /static/gridstack.min.css ") {
        write_response(
            &mut stream,
            "200 OK",
            "text/css; charset=utf-8",
            GRIDSTACK_CSS.as_bytes(),
        )
    } else if first.starts_with("GET /static/echarts.min.js ") {
        write_response(
            &mut stream,
            "200 OK",
            "text/javascript; charset=utf-8",
            ECHARTS_JS.as_bytes(),
        )
    } else if first.starts_with("GET /static/stage29_math.js ") {
        write_response(
            &mut stream,
            "200 OK",
            "text/javascript; charset=utf-8",
            STAGE29_MATH_JS.as_bytes(),
        )
    } else if first.starts_with("GET /ws/waveform ") {
        handle_waveform_ws(stream, &request, shared, web_fps)
    } else if first.starts_with("GET /ws/spectrum ") {
        handle_spectrum_ws(stream, &request, shared, web_fps)
    } else if first.starts_with("GET /api/state ") {
        let state = {
            let mut guard = shared.lock().unwrap();
            clear_stale_previews(&mut guard);
            let waveform_age_ms = preview_age_ms(guard.waveform_updated);
            let spectrum_age_ms = preview_age_ms(guard.spectrum_updated);
            let waveform_live = preview_live(guard.waveform_updated) && waveform_rate_live(&guard.config, &guard.stats);
            let spectrum_live = preview_live(guard.spectrum_updated);
            ApiState {
                config: guard.config.clone(),
                config_generation: guard.config_generation,
                stats: guard.stats.clone(),
                spec_preview: guard.spectrum_preview.status.clone(),
                waveform_live,
                waveform_age_ms,
                spectrum_live,
                spectrum_age_ms,
            }
        };
        let body = serde_json::to_vec(&state).unwrap_or_else(|_| b"{}".to_vec());
        write_response(&mut stream, "200 OK", "application/json", &body)
    } else if first.starts_with("POST /api/config ") {
        let body = request_body(&buf);
        match serde_json::from_slice::<DisplayConfigPatch>(body) {
            Ok(patch) => {
                let (config, generation) = {
                    let mut guard = shared.lock().unwrap();
                    apply_display_config_patch_to_shared(&mut guard, patch)
                };
                let body = serde_json::json!({
                    "ok": true,
                    "config": config,
                    "config_generation": generation
                })
                .to_string();
                write_response(&mut stream, "200 OK", "application/json", body.as_bytes())
            }
            Err(err) => {
                let body = format!(r#"{{"ok":false,"error":"{}"}}"#, err);
                write_response(&mut stream, "400 Bad Request", "application/json", body.as_bytes())
            }
        }
    } else if first.starts_with("OPTIONS /api/config ") || first.starts_with("OPTIONS /api/state ") {
        write_response(&mut stream, "204 No Content", "text/plain", b"")
    } else {
        write_response(&mut stream, "404 Not Found", "text/plain", b"not found")
    }
}

fn handle_waveform_ws(
    mut stream: TcpStream,
    request: &str,
    shared: Arc<Mutex<SharedState>>,
    web_fps: u32,
) -> std::io::Result<()> {
    let Some(key) = websocket_key(request) else {
        return write_response(&mut stream, "400 Bad Request", "text/plain", b"missing websocket key");
    };
    let accept = websocket_accept(&key);
    write!(
        stream,
        "HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: {}\r\nCache-Control: no-store\r\n\r\n",
        accept
    )?;
    stream.set_read_timeout(None)?;
    stream.set_write_timeout(Some(Duration::from_millis(250)))?;
    if let Ok(mut guard) = shared.lock() {
        guard.stats.websocket_clients = guard.stats.websocket_clients.saturating_add(1);
        guard.stats.waveform_websocket_clients = guard.stats.waveform_websocket_clients.saturating_add(1);
    }
    let interval = Duration::from_secs_f64(1.0 / web_fps.clamp(1, 240) as f64);
    let result = loop {
        thread::sleep(interval);
        let payload = {
            let mut guard = shared.lock().unwrap();
            clear_stale_previews(&mut guard);
            guard.waveform_binary.clone()
        };
        if let Some(payload) = payload {
            if let Err(err) = write_ws_binary_frame(&mut stream, &payload) {
                break Err(err);
            }
        }
    };
    if let Ok(mut guard) = shared.lock() {
        guard.stats.websocket_clients = guard.stats.websocket_clients.saturating_sub(1);
        guard.stats.waveform_websocket_clients = guard.stats.waveform_websocket_clients.saturating_sub(1);
    }
    result
}

fn handle_spectrum_ws(
    mut stream: TcpStream,
    request: &str,
    shared: Arc<Mutex<SharedState>>,
    web_fps: u32,
) -> std::io::Result<()> {
    let Some(key) = websocket_key(request) else {
        return write_response(&mut stream, "400 Bad Request", "text/plain", b"missing websocket key");
    };
    let accept = websocket_accept(&key);
    write!(
        stream,
        "HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: {}\r\nCache-Control: no-store\r\n\r\n",
        accept
    )?;
    stream.set_read_timeout(None)?;
    stream.set_write_timeout(Some(Duration::from_millis(250)))?;
    if let Ok(mut guard) = shared.lock() {
        guard.stats.websocket_clients = guard.stats.websocket_clients.saturating_add(1);
        guard.stats.spectrum_websocket_clients = guard.stats.spectrum_websocket_clients.saturating_add(1);
    }
    let interval = Duration::from_secs_f64(1.0 / web_fps.clamp(1, 240) as f64);
    let result = loop {
        thread::sleep(interval);
        let payload = {
            let mut guard = shared.lock().unwrap();
            clear_stale_previews(&mut guard);
            guard.spectrum_binary.clone()
        };
        if let Some(payload) = payload {
            if let Err(err) = write_ws_binary_frame(&mut stream, &payload) {
                break Err(err);
            }
        }
    };
    if let Ok(mut guard) = shared.lock() {
        guard.stats.websocket_clients = guard.stats.websocket_clients.saturating_sub(1);
        guard.stats.spectrum_websocket_clients = guard.stats.spectrum_websocket_clients.saturating_sub(1);
    }
    result
}

fn websocket_key(request: &str) -> Option<String> {
    request.lines().find_map(|line| {
        let (name, value) = line.split_once(':')?;
        if name.eq_ignore_ascii_case("sec-websocket-key") {
            Some(value.trim().to_string())
        } else {
            None
        }
    })
}

fn websocket_accept(key: &str) -> String {
    let mut hasher = Sha1::new();
    hasher.update(key.as_bytes());
    hasher.update(WEBSOCKET_GUID.as_bytes());
    let digest = hasher.finalize();
    base64::engine::general_purpose::STANDARD.encode(digest)
}

fn write_ws_binary_frame(stream: &mut TcpStream, payload: &[u8]) -> std::io::Result<()> {
    let mut header = Vec::with_capacity(10);
    header.push(0x82);
    if payload.len() < 126 {
        header.push(payload.len() as u8);
    } else if payload.len() <= u16::MAX as usize {
        header.push(126);
        header.extend_from_slice(&(payload.len() as u16).to_be_bytes());
    } else {
        header.push(127);
        header.extend_from_slice(&(payload.len() as u64).to_be_bytes());
    }
    stream.write_all(&header)?;
    stream.write_all(payload)
}

fn request_complete(buf: &[u8]) -> bool {
    let Some(header_end) = find_header_end(buf) else {
        return false;
    };
    let headers = String::from_utf8_lossy(&buf[..header_end]);
    let content_length = headers
        .lines()
        .find_map(|line| {
            let (name, value) = line.split_once(':')?;
            if name.eq_ignore_ascii_case("content-length") {
                value.trim().parse::<usize>().ok()
            } else {
                None
            }
        })
        .unwrap_or(0);
    buf.len() >= header_end + 4 + content_length
}

fn find_header_end(buf: &[u8]) -> Option<usize> {
    buf.windows(4).position(|win| win == b"\r\n\r\n")
}

fn request_body(buf: &[u8]) -> &[u8] {
    if let Some(idx) = find_header_end(buf) {
        &buf[idx + 4..]
    } else {
        &[]
    }
}

fn write_response(stream: &mut TcpStream, status: &str, content_type: &str, body: &[u8]) -> std::io::Result<()> {
    write!(
        stream,
        "HTTP/1.1 {}\r\nContent-Type: {}\r\nContent-Length: {}\r\nCache-Control: no-store\r\nAccess-Control-Allow-Origin: *\r\nAccess-Control-Allow-Headers: content-type\r\nAccess-Control-Allow-Methods: GET, POST, OPTIONS\r\nConnection: close\r\n\r\n",
        status,
        content_type,
        body.len()
    )?;
    stream.write_all(body)
}

fn run_http(bind: String, shared: Arc<Mutex<SharedState>>, web_fps: u32) -> std::io::Result<()> {
    let listener = bind_reuse_tcp_listener(&bind)?;
    eprintln!("T510 TIME receiver HTML: http://{}", bind);
    for stream in listener.incoming() {
        match stream {
            Ok(stream) => {
                let shared = shared.clone();
                thread::spawn(move || {
                    let _ = handle_http(stream, shared, web_fps);
                });
            }
            Err(err) => eprintln!("HTTP accept error: {err}"),
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use t510_time_rx::SpectrumLane;

    fn test_args() -> Args {
        Args {
            interface: "ens2f0np0".to_string(),
            port: 4300,
            dst_port_base: Some(4300),
            src_port_base: 4000,
            flow_count: DEFAULT_FLOW_COUNT_27H,
            time_flow_count: 8,
            spec_flow_count: DEFAULT_SPEC_FLOW_COUNT_27H,
            reorder_window: 8,
            web_fps: 60,
            waveform_points: 4096,
            waveform_max_points: 16384,
            web: "127.0.0.1:0".to_string(),
            initial_bandwidth_mhz: 100,
            backend: Backend::Mmap,
            worker_count: 32,
            fanout_group: 0x27d,
            fanout_mode: FanoutMode::Port,
            pin_workers: PinWorkers::Auto,
            spec_layout: SpecLayout::Stage27h,
            ring_mb: 512,
            block_mb: 4,
            block_count: 0,
            frame_kb: DEFAULT_FRAME_SIZE / 1024,
            batch_size: 4096,
            poll_timeout_ms: 10,
        }
    }

    fn test_header(seq_no: u32) -> T510Header {
        T510Header {
            magic: 0x5435_3130,
            version: 2,
            header_bytes: 128,
            board_id: 1,
            stream_type: 1,
            epoch_mode: 0,
            flags: 0,
            unix_sec: 0,
            pps_count: 0,
            sample0: 10_000 + u64::from(seq_no) * 256,
            frame_id: u64::from(seq_no),
            seq_no,
            chan0: 0,
            chan_count: 0,
            time_count: DEFAULT_TIME_COUNT,
            ninput: TIME_NINPUT as u16,
            payload_format: 0,
            scale_id: 0,
            payload_bytes: 8192,
            product_id: 0,
            nchan: 0,
            block_index: 0,
            block_count: 0,
            pfb_taps: 0,
            fft_shift: 0,
            spec_status_flags: 0,
            spec_sample_rate_hz: 0,
            scale_mode: 0,
            spec_half_band: false,
            header_crc: 0,
        }
    }

    fn le_u16(bytes: &[u8], offset: usize) -> u16 {
        u16::from_le_bytes([bytes[offset], bytes[offset + 1]])
    }

    fn le_u32(bytes: &[u8], offset: usize) -> u32 {
        u32::from_le_bytes([
            bytes[offset],
            bytes[offset + 1],
            bytes[offset + 2],
            bytes[offset + 3],
        ])
    }

    fn le_u64(bytes: &[u8], offset: usize) -> u64 {
        u64::from_le_bytes([
            bytes[offset],
            bytes[offset + 1],
            bytes[offset + 2],
            bytes[offset + 3],
            bytes[offset + 4],
            bytes[offset + 5],
            bytes[offset + 6],
            bytes[offset + 7],
        ])
    }

    fn le_f64(bytes: &[u8], offset: usize) -> f64 {
        f64::from_le_bytes([
            bytes[offset],
            bytes[offset + 1],
            bytes[offset + 2],
            bytes[offset + 3],
            bytes[offset + 4],
            bytes[offset + 5],
            bytes[offset + 6],
            bytes[offset + 7],
        ])
    }

    fn time_packet(header: T510Header, i: i16, q: i16) -> PacketCopy {
        let mut payload = vec![0u8; TIME_UDP_PAYLOAD_BYTES];
        for beat in 0..header.time_count as usize {
            for sub in 0..TIME_SUBSAMPLES_PER_BEAT {
                for channel in 0..TIME_NINPUT {
                    let offset = time_payload_complex_offset(beat, sub, channel).unwrap();
                    payload[offset..offset + 2].copy_from_slice(&i.to_le_bytes());
                    payload[offset + 2..offset + 4].copy_from_slice(&q.to_le_bytes());
                }
            }
        }
        PacketCopy {
            header,
            payload,
            detected_bandwidth: Some(BandwidthMode::Mhz100),
            gap_before: false,
        }
    }

    fn time_packet_by_channel(header: T510Header, iq_by_channel: &[(i16, i16); TIME_NINPUT]) -> PacketCopy {
        let mut payload = vec![0u8; TIME_UDP_PAYLOAD_BYTES];
        for beat in 0..header.time_count as usize {
            for sub in 0..TIME_SUBSAMPLES_PER_BEAT {
                for (channel, (i, q)) in iq_by_channel.iter().copied().enumerate() {
                    let offset = time_payload_complex_offset(beat, sub, channel).unwrap();
                    payload[offset..offset + 2].copy_from_slice(&i.to_le_bytes());
                    payload[offset + 2..offset + 4].copy_from_slice(&q.to_le_bytes());
                }
            }
        }
        PacketCopy {
            header,
            payload,
            detected_bandwidth: Some(BandwidthMode::Mhz100),
            gap_before: false,
        }
    }

    fn time_packet_channel_samples(mut header: T510Header, channel: usize, samples: &[(i16, i16)]) -> PacketCopy {
        header.time_count = div_ceil(samples.len(), TIME_SUBSAMPLES_PER_BEAT) as u16;
        let mut payload = vec![0u8; TIME_UDP_PAYLOAD_BYTES];
        for (idx, (i, q)) in samples.iter().copied().enumerate() {
            let beat = idx / TIME_SUBSAMPLES_PER_BEAT;
            let sub = idx % TIME_SUBSAMPLES_PER_BEAT;
            let offset = time_payload_complex_offset(beat, sub, channel).unwrap();
            payload[offset..offset + 2].copy_from_slice(&i.to_le_bytes());
            payload[offset + 2..offset + 4].copy_from_slice(&q.to_le_bytes());
        }
        PacketCopy {
            header,
            payload,
            detected_bandwidth: Some(BandwidthMode::Mhz100),
            gap_before: false,
        }
    }

    #[test]
    fn display_defaults_to_stage27h_100mhz() {
        let config = DisplayConfig::default();
        assert_eq!(config.bandwidth_mhz, 100);
        assert_eq!(config.output_mode, "time_spec");
        assert_eq!(config.bandwidth_mode(), BandwidthMode::Mhz100);
        assert_eq!(config.center_mhz, 100.0);
        assert_eq!(config.expected_mhz, 60.010);
        assert_eq!(config.dac_mhz, 60.010);
        assert_eq!(config.target_mhz_by_channel, [60.010; TIME_NINPUT]);

        let mut invalid = config.clone();
        invalid.bandwidth_mhz = 1234;
        sanitize_config(&mut invalid);
        assert_eq!(invalid.bandwidth_mhz, 100);

        let mut args = test_args();
        args.initial_bandwidth_mhz = 1234;
        let stats = ReceiverStats::new(&args);
        assert_eq!(stats.selected_bandwidth_mhz, 100);
    }

    #[test]
    fn display_patch_supports_legacy_scalar_and_per_channel_targets() {
        let mut config = DisplayConfig::default();
        DisplayConfigPatch {
            bandwidth_mhz: None,
            output_mode: None,
            center_mhz: None,
            expected_mhz: Some(70.0),
            dac_mhz: Some(70.0),
            target_mhz_by_channel: None,
            waveform_view_mode: None,
            phase_deg_by_channel: None,
            channel_mask: None,
            time_window_us: None,
            display_points: None,
            vertical_scale: None,
            paused: None,
            pause: None,
            freeze: None,
        }
        .apply_to(&mut config);
        assert_eq!(config.target_mhz_by_channel, [70.0; TIME_NINPUT]);

        DisplayConfigPatch {
            bandwidth_mhz: None,
            output_mode: None,
            center_mhz: None,
            expected_mhz: Some(71.0),
            dac_mhz: Some(71.0),
            target_mhz_by_channel: Some(vec![60.0, 61.0, 62.0, 63.0, 64.0, 65.0, 66.0, 67.0]),
            waveform_view_mode: None,
            phase_deg_by_channel: None,
            channel_mask: None,
            time_window_us: None,
            display_points: None,
            vertical_scale: None,
            paused: None,
            pause: None,
            freeze: None,
        }
        .apply_to(&mut config);
        assert_eq!(
            config.target_mhz_by_channel,
            [60.0, 61.0, 62.0, 63.0, 64.0, 65.0, 66.0, 67.0]
        );
        assert_eq!(config.target_hz(0), 60_000_000.0);
        assert_eq!(config.target_hz(7), 67_000_000.0);
    }

    #[test]
    fn stage29_web_is_echarts_seven_widget_workspace() {
        assert_eq!(HTML.matches("class=\"grid-stack-item\"").count(), 7);
        assert!(HTML.contains("t510-stage29-layout-v2"));
        assert!(HTML.contains("ResizeObserver"));
        assert!(HTML.contains("Display Controls"));
        assert!(HTML.contains("target_mhz_by_channel"));
        assert!(HTML.contains("SPEC phasor"));
        assert!(HTML.contains("Ignore amplitude"));
        assert!(HTML.contains("echarts.init"));
        assert!(HTML.contains("WATERFALL_INTERVAL_MS=1000"));
        assert!(HTML.contains("tooltip:{show:false}"));
        assert!(HTML.contains("fixed RF/time axes"));
        assert!(HTML.contains("replaceMerge:['series']"));
        assert!(HTML.contains("type:'inside',xAxisIndex:0"));
        assert!(HTML.contains("ampReset"));
        assert!(HTML.contains("powerReset"));
        assert!(HTML.contains("const chartPointer="));
        assert!(HTML.contains("restoreTooltip('amp')"));
        assert!(HTML.contains("Amplitude (dB code)"));
        assert!(HTML.contains("20*Math.log10(Math.max(Number(value)||0,1))"));
        assert!(HTML.contains("value=\"relative\" selected"));
        assert!(HTML.contains("type:'category',data:x"));
        assert!(GRIDSTACK_JS.contains("GridStack"));
        assert!(GRIDSTACK_CSS.contains("grid-stack-item"));
        assert!(ECHARTS_JS.len() > 1_000_000);
        assert!(ECHARTS_JS.contains("echarts"));
    }

    #[test]
    fn web_spectrum_uses_rf_mhz_ticks_and_header_sample_rate() {
        assert!(HTML.contains("RF frequency (MHz)"));
        assert!(HTML.contains("Stage29Math.rfForBin"));
        assert!(HTML.contains("Stage29Math.binForRf"));
        assert!(STAGE29_MATH_JS.contains("-signedBin(index,bins)"));
        assert!(STAGE29_MATH_JS.contains("Number(centerMhz)-Number(rfMhz)"));

        let center_mhz = 100.0_f64;
        let nchan = 4096.0_f64;
        for (sample_rate_hz, half_span_mhz, bin_width_khz) in
            [(122_880_000.0, 61.44, 30.0), (245_760_000.0, 122.88, 60.0)]
        {
            let left = center_mhz - sample_rate_hz / 2.0 / 1.0e6;
            let width = sample_rate_hz / nchan / 1.0e3;
            assert!((left - (center_mhz - half_span_mhz)).abs() < 1.0e-9);
            assert!((width - bin_width_khz).abs() < 1.0e-9);
            let target_mhz = 60.0_f64;
            let signed_bin = ((center_mhz - target_mhz) * 1.0e6 / (sample_rate_hz / nchan)).round();
            let mapped_mhz = center_mhz - signed_bin * sample_rate_hz / nchan / 1.0e6;
            assert!((mapped_mhz - target_mhz).abs() <= sample_rate_hz / nchan / 2.0 / 1.0e6);
            assert!((mapped_mhz - 140.0).abs() > 1.0);
        }
    }

    #[test]
    fn output_mode_selects_active_flows_on_superset_receiver() {
        let args = test_args();
        let base = ReceiverStats::new(&args);
        let reports = vec![None; args.worker_count_clamped()];
        for (mode, time, spec, total) in [
            ("time_only", 8, 0, 8),
            ("spec_only", 0, 16, 16),
            ("time_spec", 8, 16, 24),
        ] {
            let mut config = DisplayConfig::default();
            config.output_mode = mode.to_string();
            let stats = aggregate_fanout_stats(&base, &reports, &config, 0, 0, 0);
            assert_eq!(stats.flow_count, 24);
            assert_eq!(stats.active_time_flow_count, time);
            assert_eq!(stats.active_spec_flow_count, spec);
            assert_eq!(stats.active_flow_count, total);
        }
    }

    #[test]
    fn stage28_spec_only_allows_all_sixteen_flows_without_time() {
        let mut args = test_args();
        args.flow_count = 16;
        args.time_flow_count = 0;
        args.spec_flow_count = 16;
        args.spec_layout = SpecLayout::Stage27j;

        assert_eq!(args.time_flow_count_clamped(), 0);
        assert_eq!(args.spec_flow_count_clamped(), 16);
    }

    #[test]
    fn spectrum_preview_runs_without_websocket_clients() {
        let mut config = DisplayConfig::default();
        assert!(spectrum_preview_enabled(&config));
        config.paused = true;
        assert!(!spectrum_preview_enabled(&config));
    }

    #[test]
    fn config_patch_increments_generation_and_resets_previews() {
        let args = test_args();
        let mut state = SharedState {
            config: DisplayConfig::default(),
            config_generation: 7,
            stats: ReceiverStats::new(&args),
            waveform: None,
            waveform_binary: Some(vec![1, 2, 3]),
            waveform_updated: Some(Instant::now()),
            spectrum: None,
            spectrum_binary: Some(vec![4, 5, 6]),
            spectrum_updated: Some(Instant::now()),
            spectrum_preview: SpecPreviewCapture::default(),
        };
        state.spectrum_preview.status.complete = true;
        state.stats.detected_bandwidth_mhz = Some(100);

        let (config, generation) = apply_display_config_patch_to_shared(
            &mut state,
            DisplayConfigPatch {
                bandwidth_mhz: Some(20),
                output_mode: None,
                center_mhz: None,
                expected_mhz: None,
                dac_mhz: None,
                target_mhz_by_channel: None,
                waveform_view_mode: None,
                phase_deg_by_channel: None,
                channel_mask: None,
                time_window_us: Some(0.5),
                display_points: None,
                vertical_scale: None,
                paused: None,
                pause: None,
                freeze: None,
            },
        );

        assert_eq!(generation, 8);
        assert_eq!(config.bandwidth_mhz, 20);
        assert_eq!(state.config_generation, 8);
        assert!(state.waveform_binary.is_none());
        assert!(state.waveform_updated.is_none());
        assert!(state.spectrum_binary.is_none());
        assert!(state.spectrum_updated.is_none());
        assert!(!state.spectrum_preview.status.complete);
        assert_eq!(state.stats.selected_bandwidth_mhz, 20);
        assert!(state.stats.selected_detected_mismatch);
    }

    #[test]
    fn stale_preview_cache_is_cleared_before_serving_web() {
        let args = test_args();
        let mut stats = ReceiverStats::new(&args);
        stats.expected_packets_per_sec = 480_000.0;
        stats.rx_processed_packets_per_sec = 480_000.0;
        stats.spec_processed_packets_per_sec = 480_000.0;
        let mut state = SharedState {
            config: DisplayConfig::default(),
            config_generation: 0,
            stats,
            waveform: None,
            waveform_binary: Some(vec![1, 2, 3]),
            waveform_updated: Some(Instant::now() - PREVIEW_STALE_AFTER - Duration::from_millis(1)),
            spectrum: None,
            spectrum_binary: Some(vec![4, 5, 6]),
            spectrum_updated: Some(Instant::now()),
            spectrum_preview: SpecPreviewCapture::default(),
        };

        clear_stale_previews(&mut state);

        assert!(state.waveform_binary.is_none());
        assert!(state.waveform_updated.is_none());
        assert!(state.spectrum_binary.is_some());
        assert!(state.spectrum_updated.is_some());
    }

    #[test]
    fn recent_spectrum_survives_fanout_rate_report_lag() {
        let args = test_args();
        let mut stats = ReceiverStats::new(&args);
        stats.expected_packets_per_sec = 480_000.0;
        stats.rx_processed_packets_per_sec = 1_500.0;
        stats.spec_processed_packets_per_sec = 2_000.0;
        let mut state = SharedState {
            config: DisplayConfig::default(),
            config_generation: 0,
            stats,
            waveform: None,
            waveform_binary: Some(vec![1, 2, 3]),
            waveform_updated: Some(Instant::now()),
            spectrum: None,
            spectrum_binary: Some(vec![4, 5, 6]),
            spectrum_updated: Some(Instant::now()),
            spectrum_preview: SpecPreviewCapture::default(),
        };

        clear_stale_previews(&mut state);

        assert!(state.waveform_binary.is_none());
        assert!(state.waveform_updated.is_none());
        assert!(state.spectrum_binary.is_some());
        assert!(state.spectrum_updated.is_some());
    }

    #[test]
    fn bpf_filter_matches_ipv4_udp_dst_port_range_offsets() {
        let filter = bpf_udp_port_range_filter(4300, DEFAULT_FLOW_COUNT_27H);
        assert_eq!(filter.len(), 9);
        assert_eq!(filter[0].code, BPF_LD | BPF_H | BPF_ABS);
        assert_eq!(filter[0].k, 12);
        assert_eq!(filter[1].code, BPF_JMP | BPF_JEQ | BPF_K);
        assert_eq!(filter[1].k, 0x0800);
        assert_eq!(filter[1].jf, 6);
        assert_eq!(filter[2].code, BPF_LD | BPF_B | BPF_ABS);
        assert_eq!(filter[2].k, 23);
        assert_eq!(filter[3].k, 17);
        assert_eq!(filter[4].code, BPF_LD | BPF_H | BPF_ABS);
        assert_eq!(filter[4].k, 36);
        assert_eq!(filter[5].k, 4300);
        assert_eq!(filter[6].k, 4323);
        assert_eq!(filter[7].code, BPF_RET | BPF_K);
        assert_eq!(filter[7].k, 0xffff);
        assert_eq!(filter[8].k, 0);

        let clamped = bpf_udp_port_range_filter(4300, 128);
        assert_eq!(clamped[6].k, 4371);
    }

    #[test]
    fn packet_fanout_hash_option_uses_group_low_bits_and_mode_high_bits() {
        let config = PacketFanoutConfig {
            group: 0x027d,
            mode: FanoutMode::Hash,
            worker_count: DEFAULT_FLOW_COUNT_27H,
        };
        assert_eq!(packet_fanout_arg(config), 0x027d);

        let port_config = PacketFanoutConfig {
            group: 0x027d,
            mode: FanoutMode::Port,
            worker_count: DEFAULT_FLOW_COUNT_27H,
        };
        assert_eq!(packet_fanout_arg(port_config), 0x0006_027d);
    }

    #[test]
    fn port_fanout_bpf_maps_udp_dst_port_to_worker_index() {
        let filter = bpf_fanout_by_dst_port(4300, DEFAULT_FLOW_COUNT_27H);
        assert_eq!(filter.len(), 4);
        assert_eq!(filter[0].code, BPF_LD | BPF_H | BPF_ABS);
        assert_eq!(filter[0].k, 22);
        assert_eq!(filter[1].code, BPF_ALU | BPF_SUB | BPF_K);
        assert_eq!(filter[1].k, 4300);
        assert_eq!(filter[2].code, BPF_ALU | BPF_MOD | BPF_K);
        assert_eq!(filter[2].k, DEFAULT_FLOW_COUNT_27H as u32);
        assert_eq!(filter[3].code, BPF_RET | BPF_A);
    }

    #[test]
    fn fanout_aggregate_sums_workers_and_preserves_per_flow_stride_stats() {
        let args = test_args();
        let base = ReceiverStats::new(&args);
        let mut config = DisplayConfig::default();
        config.bandwidth_mhz = 200;

        let mut worker0 = WorkerStats::new(0);
        worker0.time_packets = 10;
        worker0.time_bytes = 83_200;
        worker0.rx_processed_packets_per_sec = 10.0;
        worker0.rx_processed_gbps = 0.006656;
        worker0.ring_drops = 1;
        worker0.last_time_count = Some(DEFAULT_TIME_COUNT);

        let mut worker1 = WorkerStats::new(1);
        worker1.time_packets = 20;
        worker1.time_bytes = 166_400;
        worker1.rx_processed_packets_per_sec = 20.0;
        worker1.rx_processed_gbps = 0.013312;
        worker1.last_time_count = Some(DEFAULT_TIME_COUNT);

        let mut flow0 = FlowStats::new(0, 4300, 4000);
        flow0.time_packets = 10;
        flow0.packets_per_sec = 10.0;
        flow0.detected_bandwidth_mhz = Some(200);
        let mut flow1 = FlowStats::new(1, 4301, 4001);
        flow1.time_packets = 20;
        flow1.packets_per_sec = 20.0;
        flow1.detected_bandwidth_mhz = Some(200);

        let reports = vec![
            Some(FanoutWorkerReport {
                worker_id: 0,
                stats: worker0,
                per_flow: vec![flow0.clone()],
            }),
            Some(FanoutWorkerReport {
                worker_id: 1,
                stats: worker1,
                per_flow: vec![flow1.clone()],
            }),
        ];
        let stats = aggregate_fanout_stats(&base, &reports, &config, 0, 0, 0);
        assert_eq!(stats.time_packets, 30);
        assert_eq!(stats.worker_ring_drops, 1);
        assert_eq!(stats.active_worker_count, 2);
        assert_eq!(stats.rx_processed_packets_per_sec, 30.0);
        assert_eq!(stats.detected_bandwidth_mhz, Some(200));
        assert_eq!(stats.per_flow[0].time_packets, 10);
        assert_eq!(stats.per_flow[1].time_packets, 20);
    }

    #[test]
    fn fanout_merge_prefers_active_flow_detection_over_stale_worker_state() {
        let args = test_args();
        let base = ReceiverStats::new(&args);
        let mut config = DisplayConfig::default();
        config.bandwidth_mhz = 20;

        let mut stale_worker = WorkerStats::new(0);
        stale_worker.last_time_count = Some(DEFAULT_TIME_COUNT);
        let mut stale_flow = FlowStats::new(1, 4301, 4001);
        stale_flow.time_packets = 10_000;
        stale_flow.detected_bandwidth_mhz = Some(100);
        stale_flow.last_seq_no = Some(1_000);

        let mut active_worker = WorkerStats::new(1);
        active_worker.time_packets = 100;
        active_worker.rx_processed_packets_per_sec = 15_000.0;
        active_worker.last_time_count = Some(DEFAULT_TIME_COUNT);
        let mut active_flow = FlowStats::new(1, 4301, 4001);
        active_flow.time_packets = 100;
        active_flow.packets_per_sec = 15_000.0;
        active_flow.detected_bandwidth_mhz = Some(20);
        active_flow.last_seq_no = Some(20_000);

        let reports = vec![
            Some(FanoutWorkerReport {
                worker_id: 0,
                stats: stale_worker,
                per_flow: vec![stale_flow],
            }),
            Some(FanoutWorkerReport {
                worker_id: 1,
                stats: active_worker,
                per_flow: vec![active_flow],
            }),
        ];
        let stats = aggregate_fanout_stats(&base, &reports, &config, 0, 0, 0);
        assert_eq!(stats.per_flow[1].detected_bandwidth_mhz, Some(20));
        assert_eq!(stats.per_flow[1].last_seq_no, Some(20_000));
        assert_eq!(stats.detected_bandwidth_mhz, Some(20));
    }

    #[test]
    fn reorder_tracker_allows_small_cross_flow_reorder() {
        let args = test_args();
        let mut stats = ReceiverStats::new(&args);
        let mut reorder = ReorderTracker::new(8);

        let (_, gap0) = reorder.ingest(test_header(0), BandwidthMode::Mhz200, &mut stats);
        let (_, gap2) = reorder.ingest(test_header(2), BandwidthMode::Mhz200, &mut stats);
        let (detected, gap1) = reorder.ingest(test_header(1), BandwidthMode::Mhz200, &mut stats);

        assert!(!gap0);
        assert!(!gap2);
        assert!(!gap1);
        assert_eq!(detected, Some(BandwidthMode::Mhz200));
        assert_eq!(stats.seq_gaps, 0);
        assert_eq!(stats.frame_gaps, 0);
        assert_eq!(stats.sample0_gaps, 0);
        assert_eq!(stats.last_seq_no, Some(2));
    }

    #[test]
    fn reorder_tracker_reports_real_gap_after_window() {
        let args = test_args();
        let mut stats = ReceiverStats::new(&args);
        let mut reorder = ReorderTracker::new(2);

        let _ = reorder.ingest(test_header(0), BandwidthMode::Mhz200, &mut stats);
        let (_, gap) = reorder.ingest(test_header(4), BandwidthMode::Mhz200, &mut stats);

        assert!(gap);
        assert_eq!(stats.seq_gaps, 1);
        assert_eq!(stats.frame_gaps, 1);
        assert_eq!(stats.sample0_gaps, 1);
        assert_eq!(stats.last_seq_no, Some(4));
        assert!(stats.app_drops >= 3);
    }

    #[test]
    fn per_flow_detected_consensus_uses_only_agreeing_flows() {
        let mut flows = vec![
            FlowStats::new(0, 4300, 4000),
            FlowStats::new(1, 4301, 4001),
            FlowStats::new(2, 4302, 4002),
        ];
        assert_eq!(per_flow_detected_consensus(&flows), None);

        flows[0].detected_bandwidth_mhz = Some(100);
        flows[2].detected_bandwidth_mhz = Some(100);
        assert_eq!(per_flow_detected_consensus(&flows), Some(100));

        flows[1].detected_bandwidth_mhz = Some(200);
        assert_eq!(per_flow_detected_consensus(&flows), None);
    }

    #[test]
    fn waveform_binary_header_and_payload_are_stable() {
        let snapshot = WaveformSnapshot {
            sample0: 123_456,
            seq_no: 10,
            frame_id: 10,
            selected_bandwidth_mhz: 200,
            detected_bandwidth_mhz: Some(100),
            decimation: 1,
            sample_rate_hz: RAW_SAMPLE_RATE_HZ,
            requested_window_us: 2.0,
            captured_window_us: 1.0,
            center_mhz: 200.0,
            expected_mhz: 120.0,
            dac_mhz: 120.0,
            expected_baseband_mhz: -80.0,
            rf_samples_per_cycle: RAW_SAMPLE_RATE_HZ / 120_000_000.0,
            baseband_samples_per_cycle: RAW_SAMPLE_RATE_HZ / 80_000_000.0,
            rf_window_cycles: 30.0,
            gap_before: true,
            channels: vec![
                ChannelWaveform {
                    channel: 0,
                    x_us: vec![0.0, 1.0],
                    i: vec![1.0, -0.5],
                    q: vec![0.2, 0.3],
                    mag: vec![1.02, 0.58],
                    sample_rf: vec![0.7, -0.3],
                    rf_x_us: vec![0.0, 1.0, 2.0],
                    rf: vec![0.8, -0.4],
                    y: vec![1.0, -0.5],
                    rms_code: 0.0,
                    max_abs_code: 1,
                    clipped: false,
                },
                ChannelWaveform {
                    channel: 3,
                    x_us: vec![0.0, 1.0],
                    i: vec![0.25, 0.75],
                    q: vec![0.1, 0.2],
                    mag: vec![0.27, 0.78],
                    sample_rf: vec![0.15, 0.65],
                    rf_x_us: vec![0.0, 1.0, 2.0],
                    rf: vec![0.2, 0.6],
                    y: vec![0.25, 0.75],
                    rms_code: 0.0,
                    max_abs_code: 1,
                    clipped: false,
                },
            ],
        };
        let bytes = encode_waveform_binary(&snapshot, 12);
        assert_eq!(bytes.len(), 160 + 2 * (2 * 20 + 2 * 8));
        assert_eq!(le_u32(&bytes, 0), WAVEFORM_MAGIC);
        assert_eq!(le_u16(&bytes, 4), WAVEFORM_BINARY_VERSION);
        assert_eq!(le_u16(&bytes, 6), WAVEFORM_BINARY_HEADER_BYTES);
        assert_eq!(le_u64(&bytes, 8), 123_456);
        assert_eq!(le_u32(&bytes, 16), 10);
        assert_eq!(le_u32(&bytes, 20), 12);
        assert_eq!(le_u32(&bytes, 24), 200);
        assert_eq!(le_u32(&bytes, 28), 100);
        assert_eq!(le_u32(&bytes, 32), 0b11);
        assert_eq!(le_u32(&bytes, 36), 0b1001);
        assert_eq!(le_u32(&bytes, 40), 2);
        assert_eq!(le_u32(&bytes, 44), 2);
        assert_eq!(le_u32(&bytes, 48), 1);
        assert_eq!(le_f64(&bytes, 56), RAW_SAMPLE_RATE_HZ);
        assert_eq!(le_f64(&bytes, 64), 2.0);
        assert_eq!(le_f64(&bytes, 72), 200.0);
        assert_eq!(le_f64(&bytes, 80), 120.0);
        assert_eq!(le_f64(&bytes, 88), 120.0);
        assert_eq!(le_f64(&bytes, 96), -80.0);
        assert_eq!(le_f64(&bytes, 128), 1.0);
        assert_eq!(f32::from_le_bytes(bytes[160..164].try_into().unwrap()), 0.0);
        assert_eq!(f32::from_le_bytes(bytes[164..168].try_into().unwrap()), 1.0);
        assert_eq!(f32::from_le_bytes(bytes[168..172].try_into().unwrap()), 1.0);
        assert_eq!(f32::from_le_bytes(bytes[172..176].try_into().unwrap()), -0.5);
        assert_eq!(f32::from_le_bytes(bytes[176..180].try_into().unwrap()), 0.2);
        assert_eq!(f32::from_le_bytes(bytes[180..184].try_into().unwrap()), 0.3);
        assert_eq!(f32::from_le_bytes(bytes[184..188].try_into().unwrap()), 1.02);
        assert_eq!(f32::from_le_bytes(bytes[188..192].try_into().unwrap()), 0.58);
        assert_eq!(f32::from_le_bytes(bytes[192..196].try_into().unwrap()), 0.7);
        assert_eq!(f32::from_le_bytes(bytes[196..200].try_into().unwrap()), -0.3);
        assert_eq!(f32::from_le_bytes(bytes[200..204].try_into().unwrap()), 0.0);
        assert_eq!(f32::from_le_bytes(bytes[204..208].try_into().unwrap()), 1.0);
        assert_eq!(f32::from_le_bytes(bytes[208..212].try_into().unwrap()), 0.8);
        assert_eq!(f32::from_le_bytes(bytes[212..216].try_into().unwrap()), -0.4);
    }

    #[test]
    fn waveform_preview_keeps_real_iq_points_and_adds_display_curve() {
        let mut config = DisplayConfig::default();
        config.channel_mask = 0x0001;
        config.display_points = 1024;
        config.time_window_us = 10.0;
        config.vertical_scale = 1.0;
        config.dac_mhz = 0.0;
        config.expected_mhz = 0.0;
        config.center_mhz = 0.0;

        let mut header = test_header(0);
        header.sample0 = 0;
        header.time_count = 2;
        let snapshot = build_waveform_from_packets(&[time_packet(header, 100, 0)], &config).unwrap();
        assert_eq!(snapshot.channels.len(), 1);
        assert_eq!(snapshot.channels[0].x_us.len(), 8);
        assert_eq!(snapshot.channels[0].i.len(), 8);
        assert!(snapshot.channels[0].i.iter().all(|value| (*value - 100.0).abs() < 1.0e-3));
        assert_eq!(snapshot.channels[0].sample_rf.len(), 8);
        assert_eq!(snapshot.channels[0].rf.len(), 1024);
        assert_eq!(snapshot.channels[0].rf_x_us.len(), 1024);
    }

    #[test]
    fn waveform_scope_uses_real_iq_for_rf_reconstruction() {
        let mut config = DisplayConfig::default();
        config.channel_mask = 0x0003;
        config.display_points = 1024;
        config.time_window_us = 1.0;
        config.vertical_scale = 1.0;
        config.center_mhz = 61.44; // RAW_SAMPLE_RATE_HZ / 4.

        let mut header = test_header(0);
        header.sample0 = 1;
        header.time_count = 1;

        config.dac_mhz = 120.0;
        config.expected_mhz = 120.0;
        let packet = time_packet_by_channel(
            header,
            &[
                (1000, 0),
                (1000, 250),
                (0, 0),
                (0, 0),
                (0, 0),
                (0, 0),
                (0, 0),
                (0, 0),
            ],
        );
        let snapshot = build_waveform_from_packets(&[packet], &config).unwrap();
        assert!((snapshot.rf_window_cycles - 120.0).abs() < 1.0e-9);
        assert_eq!(snapshot.expected_mhz, 120.0);
        assert!((snapshot.expected_baseband_mhz - 58.56).abs() < 1.0e-9);
        assert_eq!(snapshot.channels[0].sample_rf.len(), 4);
        assert_eq!(snapshot.channels[1].sample_rf.len(), 4);
        assert_eq!(snapshot.channels[0].rf.len(), 1024);
        assert_eq!(snapshot.channels[1].rf.len(), 1024);
        assert!((snapshot.channels[0].sample_rf[0]).abs() < 1.0e-3);
        assert!((snapshot.channels[1].sample_rf[0] + 250.0).abs() < 1.0e-3);
    }

    fn dominant_curve_mhz(snapshot: &WaveformSnapshot) -> f64 {
        let curve = &snapshot.channels[0].rf;
        let n = curve.len().max(1);
        let curve_sample_rate_mhz = n as f64 / snapshot.requested_window_us.max(1.0e-9);
        let mut best = (0.0f64, 0usize);
        for k in 1..(n / 2).min(256) {
            let mut re = 0.0;
            let mut im = 0.0;
            for (idx, value) in curve.iter().copied().enumerate() {
                let phase = -2.0 * std::f64::consts::PI * k as f64 * idx as f64 / n as f64;
                re += value as f64 * phase.cos();
                im += value as f64 * phase.sin();
            }
            let power = re * re + im * im;
            if power > best.0 {
                best = (power, k);
            }
        }
        best.1 as f64 * curve_sample_rate_mhz / n as f64
    }

    fn tone_fit_fraction(snapshot: &WaveformSnapshot, mhz: f64) -> f64 {
        let channel = &snapshot.channels[0];
        let n = channel.rf.len().min(channel.rf_x_us.len());
        if n == 0 {
            return 0.0;
        }
        let mean = channel.rf.iter().take(n).map(|v| *v as f64).sum::<f64>() / n as f64;
        let mut cc = 0.0;
        let mut ss = 0.0;
        let mut cs = 0.0;
        let mut yc = 0.0;
        let mut ys = 0.0;
        let mut yy = 0.0;
        for idx in 0..n {
            let y = channel.rf[idx] as f64 - mean;
            let phase = 2.0 * std::f64::consts::PI * mhz * channel.rf_x_us[idx] as f64;
            let c = phase.cos();
            let s = phase.sin();
            cc += c * c;
            ss += s * s;
            cs += c * s;
            yc += y * c;
            ys += y * s;
            yy += y * y;
        }
        let det = cc * ss - cs * cs;
        if det.abs() < 1.0e-12 || yy <= 0.0 {
            return 0.0;
        }
        let a = (yc * ss - ys * cs) / det;
        let b = (ys * cc - yc * cs) / det;
        let explained = a * yc + b * ys;
        (explained / yy).clamp(0.0, 1.0)
    }

    #[test]
    fn rf_scope_uses_measured_iq_sideband_for_lower_rf_tone() {
        let mut config = DisplayConfig::default();
        config.channel_mask = 0x0001;
        config.bandwidth_mhz = 100;
        config.display_points = 1024;
        config.time_window_us = 0.25;
        config.vertical_scale = 1.0;
        config.center_mhz = 100.0;
        config.expected_mhz = 60.0;
        config.dac_mhz = 60.0;

        let amplitude = 1000.0;
        let raw_hz = 40_000_000.0;
        let sample_rate_hz = BandwidthMode::Mhz100.sample_rate_hz();
        let mut samples = Vec::new();
        for n in 0..64 {
            let phase = 2.0 * std::f64::consts::PI * raw_hz * n as f64 / sample_rate_hz;
            samples.push(((amplitude * phase.cos()).round() as i16, (amplitude * phase.sin()).round() as i16));
        }

        let mut header = test_header(0);
        header.sample0 = 0;
        let packet = time_packet_channel_samples(header, 0, &samples);
        let snapshot = build_waveform_from_packets(&[packet], &config).unwrap();
        assert_eq!(snapshot.channels.len(), 1);
        assert_eq!(snapshot.channels[0].sample_rf.len(), 32);
        assert_eq!(snapshot.channels[0].rf.len(), 1024);
        assert!((snapshot.rf_window_cycles - 15.0).abs() < 1.0e-9);
        assert!((dominant_curve_mhz(&snapshot) - 60.0).abs() < 2.5);
        assert!(tone_fit_fraction(&snapshot, 60.0) > 0.96);
    }

    #[test]
    fn rf_scope_curve_shows_upper_rf_tone_cycles() {
        let mut config = DisplayConfig::default();
        config.channel_mask = 0x0001;
        config.bandwidth_mhz = 100;
        config.display_points = 1024;
        config.time_window_us = 0.25;
        config.vertical_scale = 1.0;
        config.center_mhz = 100.0;
        config.expected_mhz = 140.0;
        config.dac_mhz = 140.0;

        let amplitude = 1000.0;
        let raw_hz = 40_000_000.0;
        let sample_rate_hz = BandwidthMode::Mhz100.sample_rate_hz();
        let mut samples = Vec::new();
        for n in 0..64 {
            let phase = 2.0 * std::f64::consts::PI * raw_hz * n as f64 / sample_rate_hz;
            samples.push(((amplitude * phase.cos()).round() as i16, (amplitude * phase.sin()).round() as i16));
        }

        let mut header = test_header(0);
        header.sample0 = 0;
        let packet = time_packet_channel_samples(header, 0, &samples);
        let snapshot = build_waveform_from_packets(&[packet], &config).unwrap();
        assert_eq!(snapshot.channels[0].sample_rf.len(), 32);
        assert_eq!(snapshot.channels[0].rf.len(), 1024);
        assert!((snapshot.rf_window_cycles - 35.0).abs() < 1.0e-9);
        assert!((dominant_curve_mhz(&snapshot) - 140.0).abs() < 3.5);
    }

    #[test]
    fn rf_scope_point_count_does_not_follow_configured_signal_frequency() {
        let mut config = DisplayConfig::default();
        config.channel_mask = 0x0001;
        config.display_points = 1024;
        config.time_window_us = 0.25;
        config.vertical_scale = 1.0;
        config.center_mhz = 200.0;

        let mut header = test_header(0);
        header.sample0 = 0;
        header.time_count = DEFAULT_TIME_COUNT;
        let packet = time_packet(header, 1000, 0);

        let mut lens = Vec::new();
        for (mhz, cycles) in [(160.0, 40.0), (190.0, 47.5), (240.0, 60.0)] {
            config.expected_mhz = mhz;
            config.dac_mhz = mhz;
            let snapshot = build_waveform_from_packets(std::slice::from_ref(&packet), &config).unwrap();
            assert!((snapshot.rf_window_cycles - cycles).abs() < 1.0e-9);
            lens.push(snapshot.channels[0].rf.len());
        }
        assert_eq!(lens, vec![1024, 1024, 1024]);
    }

    fn spec_preview_header(frame_id: u64, block_index: u16, block_count: u16) -> T510Header {
        T510Header {
            magic: 0x5435_3130,
            version: 2,
            header_bytes: 128,
            board_id: 1,
            stream_type: STREAM_SPEC,
            epoch_mode: 0,
            flags: 0,
            unix_sec: 0,
            pps_count: 0,
            sample0: frame_id * 4096,
            frame_id,
            seq_no: block_index as u32,
            chan0: block_index as u32,
            chan_count: 1,
            time_count: 1,
            ninput: 1,
            payload_format: 0,
            scale_id: 0,
            payload_bytes: 8192,
            product_id: 0xf101,
            nchan: block_count,
            block_index,
            block_count,
            pfb_taps: 0,
            fft_shift: 0,
            spec_status_flags: SPEC_FFT_ONLY_FLAG,
            spec_sample_rate_hz: 100_000_000,
            scale_mode: 0,
            spec_half_band: false,
            header_crc: 0,
        }
    }

    fn spec_preview_block(frame_id: u64, block_index: u16, block_count: u16) -> SpectrumSnapshot {
        let header = spec_preview_header(frame_id, block_index, block_count);
        SpectrumSnapshot {
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
            coverage_mask_lo: 1u64 << block_index,
            coverage_mask_hi: 0,
            src_port: 4008 + block_index,
            dst_port: 4308 + block_index,
            gap_before: false,
            lanes: vec![SpectrumLane {
                input: 0,
                amplitude: vec![block_index as f32 + 1.0],
                phase_rad: vec![0.0],
                power_db: vec![10.0],
            }],
        }
    }

    #[test]
    fn spectrum_preview_gate_selects_unique_blocks_from_one_frame() {
        let gate = SpectrumPreviewGate::default();
        let interval = Duration::from_secs(10);

        let arming_block = spec_preview_header(100, 0, 16);
        assert!(!gate.should_decode(&arming_block, interval));

        let target_group = (arming_block.frame_id / 16) + SPECTRUM_PREVIEW_GROUP_LEAD;
        let block0 = spec_preview_header(target_group * 16, 0, 16);
        let block1 = spec_preview_header(target_group * 16 + 1, 1, 16);
        let next_group = spec_preview_header((target_group + 1) * 16, 0, 16);

        assert!(gate.should_decode(&block0, interval));
        assert!(!gate.should_decode(&block0, interval));
        assert!(gate.should_decode(&block1, interval));
        assert!(!gate.should_decode(&next_group, interval));

        gate.reset();
        assert!(!gate.should_decode(&next_group, interval));
    }

    #[test]
    fn spec_preview_capture_publishes_only_complete_single_frame() {
        let mut capture = SpecPreviewCapture::default();
        capture.last_publish = Instant::now() - Duration::from_secs(1);
        let interval = Duration::from_millis(100);

        let block1_header = spec_preview_header(7, 1, 2);
        assert!(capture.should_decode(&block1_header, interval));
        assert!(capture.ingest(&spec_preview_block(7, 1, 2), interval).is_none());
        assert_eq!(capture.status.coverage_blocks, 1);

        let block0_header = spec_preview_header(8, 0, 2);
        assert!(capture.should_decode(&block0_header, interval));
        assert!(capture.ingest(&spec_preview_block(8, 0, 2), interval).is_none());
        assert_eq!(capture.status.frame_id, Some(8));
        assert_eq!(capture.status.coverage_blocks, 1);
        assert!(!capture.status.complete);

        let block1_header = spec_preview_header(8, 1, 2);
        assert!(capture.should_decode(&block1_header, interval));
        let snapshot = capture
            .ingest(&spec_preview_block(8, 1, 2), Duration::from_millis(1))
            .unwrap();
        assert_eq!(snapshot.coverage_blocks, 2);
        assert_eq!(snapshot.coverage_mask_lo & 0b11, 0b11);
        assert_eq!(snapshot.lanes[0].amplitude[0], 1.0);
        assert_eq!(snapshot.lanes[0].amplitude[1], 2.0);
        assert!(capture.status.complete);
    }

    #[test]
    fn spectrum_binary_header_and_payload_are_stable() {
        let snapshot = SpectrumSnapshot {
            sample0: 77,
            seq_no: 9,
            frame_id: 44,
            chan0: 128,
            chan_count: 2,
            time_count: 4,
            ninput: 2,
            product_id: 0xf101,
            nchan: 4096,
            block_index: 2,
            block_count: 64,
            pfb_taps: 4,
            fft_shift: 3,
            spec_status_flags: 0x21,
            spec_sample_rate_hz: 100_000_000,
            coverage_blocks: 2,
            coverage_mask_lo: 0b101,
            coverage_mask_hi: 0,
            src_port: 4008,
            dst_port: 4308,
            gap_before: true,
            lanes: vec![
                SpectrumLane {
                    input: 0,
                    amplitude: vec![1.0, 2.0],
                    phase_rad: vec![0.25, -0.25],
                    power_db: vec![10.0, 20.0],
                },
                SpectrumLane {
                    input: 1,
                    amplitude: vec![3.0, 4.0],
                    phase_rad: vec![1.0, -1.0],
                    power_db: vec![30.0, 40.0],
                },
            ],
        };
        let bytes = encode_spectrum_binary(&snapshot);
        assert_eq!(bytes.len(), 128 + 2 * 2 * 12);
        assert_eq!(le_u32(&bytes, 0), SPECTRUM_MAGIC);
        assert_eq!(le_u16(&bytes, 4), 2);
        assert_eq!(le_u16(&bytes, 6), 128);
        assert_eq!(le_u64(&bytes, 8), 77);
        assert_eq!(le_u64(&bytes, 16), 44);
        assert_eq!(le_u32(&bytes, 24), 9);
        assert_eq!(le_u32(&bytes, 28), 1);
        assert_eq!(le_u32(&bytes, 32), 128);
        assert_eq!(le_u32(&bytes, 36), 2);
        assert_eq!(le_u32(&bytes, 40), 4);
        assert_eq!(le_u32(&bytes, 44), 2);
        assert_eq!(le_u32(&bytes, 48), 4008);
        assert_eq!(le_u32(&bytes, 52), 4308);
        assert_eq!(le_u32(&bytes, 56), 2);
        assert_eq!(le_u32(&bytes, 60), 2);
        assert_eq!(le_u32(&bytes, 64), 0xf101);
        assert_eq!(le_u32(&bytes, 68), 4096);
        assert_eq!(le_u32(&bytes, 72), 2);
        assert_eq!(le_u32(&bytes, 76), 64);
        assert_eq!(le_u32(&bytes, 80), 4);
        assert_eq!(le_u32(&bytes, 84), 3);
        assert_eq!(le_u32(&bytes, 88), 0x21);
        assert_eq!(le_u32(&bytes, 92), 100_000_000);
        assert_eq!(le_u32(&bytes, 96), 2);
        assert_eq!(le_u64(&bytes, 104), 0b101);
        assert_eq!(f32::from_le_bytes(bytes[128..132].try_into().unwrap()), 1.0);
        assert_eq!(f32::from_le_bytes(bytes[132..136].try_into().unwrap()), 2.0);
        assert_eq!(f32::from_le_bytes(bytes[136..140].try_into().unwrap()), 0.25);
        assert_eq!(f32::from_le_bytes(bytes[144..148].try_into().unwrap()), 10.0);
        assert_eq!(f32::from_le_bytes(bytes[152..156].try_into().unwrap()), 3.0);
    }
}

fn main() -> std::io::Result<()> {
    let args = Args::parse();
    let stats = ReceiverStats::new(&args);
    let mut initial_config = DisplayConfig::default();
    if BandwidthMode::from_mhz(args.initial_bandwidth_mhz).is_some() {
        initial_config.bandwidth_mhz = args.initial_bandwidth_mhz;
    }
    initial_config.display_points = args.waveform_points_clamped();
    sanitize_config(&mut initial_config);
    let shared = Arc::new(Mutex::new(SharedState {
        config: initial_config,
        config_generation: 0,
        stats,
        waveform: None,
        waveform_binary: None,
        waveform_updated: None,
        spectrum: None,
        spectrum_binary: None,
        spectrum_updated: None,
        spectrum_preview: SpecPreviewCapture::default(),
    }));

    let receiver_shared = shared.clone();
    let receiver_args = Args {
        interface: args.interface.clone(),
        port: args.port,
        dst_port_base: args.dst_port_base,
        src_port_base: args.src_port_base,
        flow_count: args.flow_count,
        time_flow_count: args.time_flow_count,
        spec_flow_count: args.spec_flow_count,
        reorder_window: args.reorder_window,
        web_fps: args.web_fps,
        waveform_points: args.waveform_points,
        waveform_max_points: args.waveform_max_points,
        web: args.web.clone(),
        initial_bandwidth_mhz: args.initial_bandwidth_mhz,
        backend: args.backend.clone(),
        worker_count: args.worker_count,
        fanout_group: args.fanout_group,
        fanout_mode: args.fanout_mode,
        pin_workers: args.pin_workers,
        spec_layout: args.spec_layout,
        ring_mb: args.ring_mb,
        block_mb: args.block_mb,
        block_count: args.block_count,
        frame_kb: args.frame_kb,
        batch_size: args.batch_size,
        poll_timeout_ms: args.poll_timeout_ms,
    };
    thread::spawn(move || {
        if let Err(err) = run_receiver(receiver_args, receiver_shared) {
            eprintln!("receiver failed: {err}");
        }
    });

    run_http(args.web, shared, args.web_fps)
}

const HTML: &str = include_str!("../static/index.html");
const GRIDSTACK_JS: &str = include_str!("../static/gridstack-all.js");
const GRIDSTACK_CSS: &str = include_str!("../static/gridstack.min.css");
const ECHARTS_JS: &str = concat!(
    include_str!("../static/echarts.part1.js"),
    include_str!("../static/echarts.part2.js"),
    include_str!("../static/echarts.part3.js"),
);
const STAGE29_MATH_JS: &str = include_str!("../static/stage29_math.js");
