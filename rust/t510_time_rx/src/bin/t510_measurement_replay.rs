use clap::Parser;
use serde::Serialize;
use sha2::{Digest, Sha256};
use std::array;
use std::collections::BTreeMap;
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::thread;
use std::time::{Duration, Instant};
use t510_time_rx::autocorrelation::{AutocorrelationController, AutocorrelationRequest, AutocorrelationWorkerState};
use t510_time_rx::{
    ethernet_ipv4_udp_payload_range_fast, parse_t510_header_fast, validate_spec_header_fast,
    SPEC_BLOCK_COUNT,
};

const SPEC_PORT_BASE: u16 = 4308;
const SPEC_PAYLOAD_BYTES_WITH_HEADER: usize = 128 + 8192;
const SAMPLE_RATE_HZ: u64 = 320_000_000;
const FRAME_SAMPLE0_STEP: u64 = 4096;
const COMMON_LEAD_MS: u64 = 100;
const REORDER_GUARD_GROUPS: u64 = 8;

#[derive(Debug, Parser)]
#[command(about = "full-band deterministic packet-replay validator")]
struct Args {
    #[arg(long)]
    source_pcap: PathBuf,
    #[arg(long)]
    output_root: PathBuf,
    #[arg(long, default_value_t = 1)]
    duration_seconds: u32,
    #[arg(long, default_value_t = 1020.0)]
    center_mhz: f64,
}

#[derive(Debug)]
struct ReplaySource {
    templates: Vec<Vec<Vec<u8>>>,
    sha256: String,
    bytes: u64,
    packet_count: u64,
    block_packet_counts: Vec<u64>,
    first_sample0: u64,
    last_sample0: u64,
    first_frame_group_by_block: Vec<u64>,
    last_frame_group_by_block: Vec<u64>,
    seq_frame_offset: u32,
    board_id: u16,
    product_id: u16,
    pfb_taps: u16,
    fft_shift: u16,
    spec_status_flags: u32,
    spec_sample_rate_hz: u32,
    continuity_checks: u64,
}

#[derive(Debug, Serialize)]
struct SourceSummary {
    path: String,
    sha256: String,
    bytes: u64,
    packet_count: u64,
    block_packet_counts: Vec<u64>,
    first_sample0: u64,
    last_sample0: u64,
    first_frame_group_by_block: Vec<u64>,
    last_frame_group_by_block: Vec<u64>,
    seq_frame_offset: u32,
    board_id: u16,
    product_id: u16,
    pfb_taps: u16,
    fft_shift: u16,
    spec_status_flags: u32,
    spec_sample_rate_hz: u32,
    continuity_checks: u64,
}

#[derive(Debug, Serialize)]
struct ReplayRunSummary {
    scan_id: String,
    native_bucket_ms: u32,
    start_lead_buckets: u64,
    common_lead_ms: u64,
    duration_seconds: u32,
    input_packets: u64,
    formal_packets: u64,
    formal_payload_bytes: u64,
    elapsed_seconds: f64,
    formal_packets_per_second: f64,
    formal_payload_gbytes_per_second: f64,
    realtime_factor: f64,
    queue_high_water: usize,
    files_committed: u64,
    bytes_committed: u64,
    output_dir: String,
}

#[derive(Debug, Serialize)]
struct FaultSummary {
    scan_id: String,
    status: String,
    queue_high_water: usize,
    native_rows: u64,
    moment_rows: u64,
    gap_ranges: u64,
    arrival_events: u64,
    output_dir: String,
}

#[derive(Debug, Serialize)]
struct ReplaySummary {
    format: &'static str,
    schema_version: u32,
    source: SourceSummary,
    normalization: BTreeMap<String, String>,
    nominal_runs: Vec<ReplayRunSummary>,
    fault_injection: FaultSummary,
    explicit_stop: FaultSummary,
}

fn main() -> Result<(), String> {
    let args = Args::parse();
    if !(1..=30).contains(&args.duration_seconds) {
        return Err("duration_seconds must be within 1..=30 for replay validation".to_string());
    }
    if args.output_root.join("step3_replay_summary.json").exists() {
        return Err(format!(
            "refusing to overwrite {}",
            args.output_root.join("step3_replay_summary.json").display()
        ));
    }
    fs::create_dir_all(&args.output_root)
        .map_err(|error| format!("create output root failed: {error}"))?;
    let source = Arc::new(read_source_pcap(&args.source_pcap)?);
    let mut nominal_runs = Vec::new();
    for bucket_ms in [10, 20, 50, 100] {
        nominal_runs.push(run_nominal(
            &args.output_root,
            source.clone(),
            bucket_ms,
            args.duration_seconds,
            args.center_mhz,
        )?);
    }
    let fault_injection = run_fault_injection(&args.output_root, source.clone(), args.center_mhz)?;
    let explicit_stop = run_explicit_stop(&args.output_root, source.clone(), args.center_mhz)?;

    let summary = ReplaySummary {
        format: "T510_MEASUREMENT_REPLAY_VALIDATION_V1",
        schema_version: 1,
        source: SourceSummary {
            path: args.source_pcap.display().to_string(),
            sha256: source.sha256.clone(),
            bytes: source.bytes,
            packet_count: source.packet_count,
            block_packet_counts: source.block_packet_counts.clone(),
            first_sample0: source.first_sample0,
            last_sample0: source.last_sample0,
            first_frame_group_by_block: source.first_frame_group_by_block.clone(),
            last_frame_group_by_block: source.last_frame_group_by_block.clone(),
            seq_frame_offset: source.seq_frame_offset,
            board_id: source.board_id,
            product_id: source.product_id,
            pfb_taps: source.pfb_taps,
            fft_shift: source.fft_shift,
            spec_status_flags: source.spec_status_flags,
            spec_sample_rate_hz: source.spec_sample_rate_hz,
            continuity_checks: source.continuity_checks,
        },
        normalization: BTreeMap::from([
            (
                "payload".to_string(),
                "all 512 source IQ16 payloads preserved byte-for-byte".to_string(),
            ),
            (
                "timeline".to_string(),
                "per-block 32-frame windows repeat on a common 4096-tick frame axis".to_string(),
            ),
            (
                "common_formal_start".to_string(),
                "100 ms after replay origin for every native bucket width".to_string(),
            ),
            (
                "header_rewrite".to_string(),
                "sample0/frame_id/seq_no only; observation and product identity retained"
                    .to_string(),
            ),
        ]),
        nominal_runs,
        fault_injection,
        explicit_stop,
    };
    write_json_create_new(
        &args.output_root.join("step3_replay_summary.json"),
        &summary,
    )?;
    println!(
        "T510_MEASUREMENT_REPLAY_OK summary={}",
        args.output_root.join("step3_replay_summary.json").display()
    );
    Ok(())
}

fn run_nominal(
    output_root: &Path,
    source: Arc<ReplaySource>,
    bucket_ms: u32,
    duration_seconds: u32,
    center_mhz: f64,
) -> Result<ReplayRunSummary, String> {
    let start_lead_buckets = COMMON_LEAD_MS / u64::from(bucket_ms);
    let scan_id = format!("nominal_{bucket_ms}ms");
    let controller = Arc::new(AutocorrelationController::new(output_root.to_path_buf()));
    controller.begin_replay_validation(
        replay_request(&scan_id, bucket_ms, duration_seconds, center_mhz, &source),
        start_lead_buckets,
    )?;
    let origin_group = 10_000_000u64;
    let origin_sample0 = 1_000_000_000_000u64;
    let mut origin_worker = AutocorrelationWorkerState::default();
    ingest_rewritten(
        &controller,
        &mut origin_worker,
        &source.templates[0][0],
        0,
        0,
        origin_group,
        origin_sample0,
        source.seq_frame_offset,
    )?;

    let formal_delta = div_ceil(COMMON_LEAD_MS * SAMPLE_RATE_HZ / 1000, FRAME_SAMPLE0_STEP);
    let end_delta = div_ceil(
        (COMMON_LEAD_MS + u64::from(duration_seconds) * 1000) * SAMPLE_RATE_HZ / 1000,
        FRAME_SAMPLE0_STEP,
    );
    let completion_delta = end_delta + REORDER_GUARD_GROUPS;
    let started = Instant::now();
    let mut handles = Vec::with_capacity(SPEC_BLOCK_COUNT as usize);
    let seq_frame_offset = source.seq_frame_offset;
    for block_index in 0..SPEC_BLOCK_COUNT {
        let controller = controller.clone();
        let mut templates = source.templates[block_index as usize].clone();
        handles.push(thread::spawn(move || -> Result<u64, String> {
            let mut worker = AutocorrelationWorkerState::default();
            let first_delta = if block_index == 0 { 1 } else { 0 };
            let mut packets = 0u64;
            for delta in first_delta..=completion_delta {
                let source_index = if delta >= formal_delta {
                    ((delta - formal_delta) % templates.len() as u64) as usize
                } else {
                    (delta % templates.len() as u64) as usize
                };
                rewrite_and_ingest(
                    &controller,
                    &mut worker,
                    &mut templates[source_index],
                    block_index,
                    delta,
                    origin_group,
                    origin_sample0,
                    seq_frame_offset,
                )?;
                packets = packets.saturating_add(1);
            }
            Ok(packets)
        }));
    }
    let mut input_packets = 1u64;
    for handle in handles {
        input_packets = input_packets.saturating_add(
            handle
                .join()
                .map_err(|_| "replay worker panicked".to_string())??,
        );
    }
    wait_for_status(&controller, "completed", Duration::from_secs(300))?;
    let elapsed_seconds = started.elapsed().as_secs_f64();
    let status = controller.status();
    let formal_groups = end_delta.saturating_sub(formal_delta);
    let formal_packets = formal_groups.saturating_mul(u64::from(SPEC_BLOCK_COUNT));
    let formal_payload_bytes = formal_packets.saturating_mul(SPEC_PAYLOAD_BYTES_WITH_HEADER as u64);
    Ok(ReplayRunSummary {
        scan_id,
        native_bucket_ms: bucket_ms,
        start_lead_buckets,
        common_lead_ms: COMMON_LEAD_MS,
        duration_seconds,
        input_packets,
        formal_packets,
        formal_payload_bytes,
        elapsed_seconds,
        formal_packets_per_second: formal_packets as f64 / elapsed_seconds,
        formal_payload_gbytes_per_second: formal_payload_bytes as f64 / elapsed_seconds / 1.0e9,
        realtime_factor: f64::from(duration_seconds) / elapsed_seconds,
        queue_high_water: status.queue_high_water,
        files_committed: status.writer.files_committed,
        bytes_committed: status.writer.bytes_committed,
        output_dir: status.output_dir.unwrap_or_default(),
    })
}

fn run_fault_injection(
    output_root: &Path,
    source: Arc<ReplaySource>,
    center_mhz: f64,
) -> Result<FaultSummary, String> {
    let scan_id = "fault_injection_100ms";
    let controller = AutocorrelationController::new(output_root.to_path_buf());
    controller.begin_replay_validation(replay_request(scan_id, 100, 1, center_mhz, &source), 1)?;
    let origin_group = 20_000_000u64;
    let origin_sample0 = 2_000_000_000_000u64;
    let mut workers: [AutocorrelationWorkerState; SPEC_BLOCK_COUNT as usize] =
        array::from_fn(|_| AutocorrelationWorkerState::default());
    ingest_rewritten(
        &controller,
        &mut workers[0],
        &source.templates[0][0],
        0,
        0,
        origin_group,
        origin_sample0,
        source.seq_frame_offset,
    )?;
    let bucket_ticks = SAMPLE_RATE_HZ / 10;
    for block_index in 0..SPEC_BLOCK_COUNT {
        for bucket in 0..10u64 {
            if block_index == 1 && bucket == 5 {
                continue;
            }
            let delta = div_ceil((1 + bucket) * bucket_ticks, FRAME_SAMPLE0_STEP);
            let template = &source.templates[block_index as usize]
                [(bucket as usize) % source.templates[block_index as usize].len()];
            if block_index == 0 && bucket == 0 {
                for injected_delta in [delta, delta + 2, delta + 1, delta + 1] {
                    ingest_rewritten(
                        &controller,
                        &mut workers[0],
                        template,
                        0,
                        injected_delta,
                        origin_group,
                        origin_sample0,
                        source.seq_frame_offset,
                    )?;
                }
            } else {
                ingest_rewritten(
                    &controller,
                    &mut workers[block_index as usize],
                    template,
                    block_index,
                    delta,
                    origin_group,
                    origin_sample0,
                    source.seq_frame_offset,
                )?;
                if block_index == 0 && bucket == 1 {
                    let first_delta = div_ceil(bucket_ticks, FRAME_SAMPLE0_STEP);
                    let unseen_late_delta = first_delta + 100;
                    ingest_rewritten(
                        &controller,
                        &mut workers[0],
                        &source.templates[0][0],
                        0,
                        unseen_late_delta,
                        origin_group,
                        origin_sample0,
                        source.seq_frame_offset,
                    )?;
                }
            }
        }
        let completion_delta =
            div_ceil(11 * bucket_ticks, FRAME_SAMPLE0_STEP) + REORDER_GUARD_GROUPS;
        ingest_rewritten(
            &controller,
            &mut workers[block_index as usize],
            &source.templates[block_index as usize][0],
            block_index,
            completion_delta,
            origin_group,
            origin_sample0,
            source.seq_frame_offset,
        )?;
    }
    wait_for_status(&controller, "completed", Duration::from_secs(30))?;
    Ok(fault_summary(scan_id, &controller))
}

fn run_explicit_stop(
    output_root: &Path,
    source: Arc<ReplaySource>,
    center_mhz: f64,
) -> Result<FaultSummary, String> {
    let scan_id = "explicit_stop_100ms";
    let controller = AutocorrelationController::new(output_root.to_path_buf());
    controller.begin_replay_validation(replay_request(scan_id, 100, 1, center_mhz, &source), 1)?;
    let mut worker = AutocorrelationWorkerState::default();
    let origin_group = 30_000_000u64;
    let origin_sample0 = 3_000_000_000_000u64;
    for delta in [0, div_ceil(SAMPLE_RATE_HZ / 10, FRAME_SAMPLE0_STEP)] {
        ingest_rewritten(
            &controller,
            &mut worker,
            &source.templates[0][0],
            0,
            delta,
            origin_group,
            origin_sample0,
            source.seq_frame_offset,
        )?;
    }
    controller.stop("intentional measurement replay recovery validation")?;
    wait_for_status(&controller, "failed", Duration::from_secs(30))?;
    Ok(fault_summary(scan_id, &controller))
}

fn fault_summary(scan_id: &str, controller: &AutocorrelationController) -> FaultSummary {
    let status = controller.status();
    FaultSummary {
        scan_id: scan_id.to_string(),
        status: status.status,
        queue_high_water: status.queue_high_water,
        native_rows: status.writer.native_rows_received,
        moment_rows: status.writer.moment_100ms_rows_received,
        gap_ranges: status.writer.gap_ranges_received,
        arrival_events: status.writer.arrival_events_received,
        output_dir: status.output_dir.unwrap_or_default(),
    }
}

fn replay_request(
    scan_id: &str,
    bucket_ms: u32,
    duration_seconds: u32,
    center_mhz: f64,
    source: &ReplaySource,
) -> AutocorrelationRequest {
    AutocorrelationRequest {
        scan_id: scan_id.to_string(),
        tuning_id: "stage34a-stability-320msps-begin".to_string(),
        duration_seconds,
        native_bucket_ms: bucket_ms,
        sample_rate_msps: 320,
        center_mhz,
        expected_fft_shift: Some(source.fft_shift),
        metadata: BTreeMap::from([
            ("validation_mode".to_string(), "packet_replay".to_string()),
            ("source_sha256".to_string(), source.sha256.clone()),
            (
                "source_transform".to_string(),
                "repeat_per_block_32_frames_and_rewrite_timeline".to_string(),
            ),
        ]),
    }
}

#[allow(clippy::too_many_arguments)]
fn ingest_rewritten(
    controller: &AutocorrelationController,
    worker: &mut AutocorrelationWorkerState,
    template: &[u8],
    block_index: u16,
    group_delta: u64,
    origin_group: u64,
    origin_sample0: u64,
    seq_frame_offset: u32,
) -> Result<(), String> {
    let mut payload = template.to_vec();
    rewrite_and_ingest(
        controller,
        worker,
        &mut payload,
        block_index,
        group_delta,
        origin_group,
        origin_sample0,
        seq_frame_offset,
    )
}

#[allow(clippy::too_many_arguments)]
fn rewrite_and_ingest(
    controller: &AutocorrelationController,
    worker: &mut AutocorrelationWorkerState,
    payload: &mut [u8],
    block_index: u16,
    group_delta: u64,
    origin_group: u64,
    origin_sample0: u64,
    seq_frame_offset: u32,
) -> Result<(), String> {
    let frame_group = origin_group.wrapping_add(group_delta);
    let frame_id = frame_group
        .wrapping_mul(u64::from(SPEC_BLOCK_COUNT))
        .wrapping_add(u64::from(block_index));
    let sample0 = origin_sample0.wrapping_add(group_delta.wrapping_mul(FRAME_SAMPLE0_STEP));
    let seq_no = (frame_id as u32).wrapping_add(seq_frame_offset);
    payload[32..40].copy_from_slice(&sample0.to_le_bytes());
    payload[40..48].copy_from_slice(&frame_id.to_le_bytes());
    let chan0 = u32::from_le_bytes(payload[48..52].try_into().unwrap());
    let word6 = (u64::from(seq_no) << 32) | u64::from(chan0);
    payload[48..56].copy_from_slice(&word6.to_le_bytes());
    let header = parse_t510_header_fast(payload)
        .map_err(|error| format!("rewritten header parse failed: {error:?}"))?;
    validate_spec_header_fast(&header, payload.len())
        .map_err(|error| format!("rewritten SPEC validation failed: {error:?}"))?;
    controller.ingest(worker, &header, payload);
    Ok(())
}

fn wait_for_status(
    controller: &AutocorrelationController,
    expected: &str,
    timeout: Duration,
) -> Result<(), String> {
    let deadline = Instant::now() + timeout;
    loop {
        let status = controller.status();
        if status.status == expected && (expected != "failed" || !controller.is_active()) {
            return Ok(());
        }
        if status.status == "failed" && expected != "failed" {
            return Err(format!("capture failed: {:?}", status.error));
        }
        if Instant::now() >= deadline {
            return Err(format!(
                "timed out waiting for {expected}; current={} error={:?}",
                status.status, status.error
            ));
        }
        thread::sleep(Duration::from_millis(10));
    }
}

fn read_source_pcap(path: &Path) -> Result<ReplaySource, String> {
    let raw = fs::read(path).map_err(|error| format!("read {} failed: {error}", path.display()))?;
    let mut hasher = Sha256::new();
    hasher.update(&raw);
    let sha256 = format!("{:x}", hasher.finalize());
    if raw.len() < 24 {
        return Err("source PCAP is shorter than the global header".to_string());
    }
    let little_endian = match &raw[0..4] {
        [0xd4, 0xc3, 0xb2, 0xa1] | [0x4d, 0x3c, 0xb2, 0xa1] => true,
        [0xa1, 0xb2, 0xc3, 0xd4] | [0xa1, 0xb2, 0x3c, 0x4d] => false,
        magic => return Err(format!("unsupported PCAP magic {:02x?}", magic)),
    };
    if read_u32(&raw[20..24], little_endian) != 1 {
        return Err("source PCAP is not Ethernet link type 1".to_string());
    }
    let mut templates: Vec<Vec<Vec<u8>>> = (0..SPEC_BLOCK_COUNT).map(|_| Vec::new()).collect();
    let mut previous = vec![None; SPEC_BLOCK_COUNT as usize];
    let mut first_group = vec![u64::MAX; SPEC_BLOCK_COUNT as usize];
    let mut last_group = vec![0; SPEC_BLOCK_COUNT as usize];
    let mut first_sample0 = u64::MAX;
    let mut last_sample0 = 0u64;
    let mut packet_count = 0u64;
    let mut continuity_checks = 0u64;
    let mut identity = None;
    let mut spec_status_flags_or = 0u32;
    let mut seq_frame_offset = None;
    let mut offset = 24usize;
    while offset + 16 <= raw.len() {
        let included = read_u32(&raw[offset + 8..offset + 12], little_endian) as usize;
        offset += 16;
        let end = offset
            .checked_add(included)
            .ok_or_else(|| "PCAP record length overflow".to_string())?;
        if end > raw.len() {
            return Err("source PCAP contains a truncated record".to_string());
        }
        let frame = &raw[offset..end];
        offset = end;
        let Ok(view) =
            ethernet_ipv4_udp_payload_range_fast(frame, SPEC_PORT_BASE, SPEC_BLOCK_COUNT)
        else {
            continue;
        };
        let header = parse_t510_header_fast(view.payload)
            .map_err(|error| format!("source header parse failed: {error:?}"))?;
        validate_spec_header_fast(&header, view.payload.len())
            .map_err(|error| format!("source SPEC validation failed: {error:?}"))?;
        if view.payload.len() != SPEC_PAYLOAD_BYTES_WITH_HEADER {
            return Err(format!(
                "unexpected source payload length {}",
                view.payload.len()
            ));
        }
        if view.dst_port != SPEC_PORT_BASE + header.block_index {
            return Err("source port/block mapping mismatch".to_string());
        }
        let current_identity = (
            header.board_id,
            header.product_id,
            header.pfb_taps,
            header.fft_shift,
            header.spec_sample_rate_hz,
            header.scale_id,
            header.scale_mode,
            header.sync_generation,
            header.sync_observation_tag,
        );
        if let Some(expected) = identity {
            if current_identity != expected {
                return Err("source observation/product identity changed".to_string());
            }
        } else {
            identity = Some(current_identity);
        }
        spec_status_flags_or |= header.spec_status_flags;
        let current_offset = header.seq_no.wrapping_sub(header.frame_id as u32);
        if let Some(expected) = seq_frame_offset {
            if current_offset != expected {
                return Err("source seq_no/frame_id offset changed".to_string());
            }
        } else {
            seq_frame_offset = Some(current_offset);
        }
        let block = header.block_index as usize;
        if let Some((prior_seq, prior_frame, prior_sample0)) = previous[block] {
            if header.seq_no.wrapping_sub(prior_seq) != u32::from(SPEC_BLOCK_COUNT)
                || header.frame_id.wrapping_sub(prior_frame) != u64::from(SPEC_BLOCK_COUNT)
                || header.sample0.wrapping_sub(prior_sample0) != FRAME_SAMPLE0_STEP
            {
                return Err(format!("source block {block} continuity mismatch"));
            }
            continuity_checks = continuity_checks.saturating_add(1);
        }
        previous[block] = Some((header.seq_no, header.frame_id, header.sample0));
        let group = header.frame_id / u64::from(SPEC_BLOCK_COUNT);
        first_group[block] = first_group[block].min(group);
        last_group[block] = last_group[block].max(group);
        first_sample0 = first_sample0.min(header.sample0);
        last_sample0 = last_sample0.max(header.sample0);
        templates[block].push(view.payload.to_vec());
        packet_count = packet_count.saturating_add(1);
    }
    if offset != raw.len() {
        return Err("source PCAP has trailing bytes".to_string());
    }
    let block_packet_counts: Vec<u64> = templates.iter().map(|rows| rows.len() as u64).collect();
    if templates.iter().any(|rows| rows.len() < 2)
        || block_packet_counts
            .iter()
            .any(|count| *count != block_packet_counts[0])
    {
        return Err(format!(
            "source block packet counts are incomplete/unbalanced: {block_packet_counts:?}"
        ));
    }
    let identity = identity.ok_or_else(|| "source PCAP has no SPEC packets".to_string())?;
    Ok(ReplaySource {
        templates,
        sha256,
        bytes: raw.len() as u64,
        packet_count,
        block_packet_counts,
        first_sample0,
        last_sample0,
        first_frame_group_by_block: first_group,
        last_frame_group_by_block: last_group,
        seq_frame_offset: seq_frame_offset.unwrap_or_default(),
        board_id: identity.0,
        product_id: identity.1,
        pfb_taps: identity.2,
        fft_shift: identity.3,
        spec_status_flags: spec_status_flags_or,
        spec_sample_rate_hz: identity.4,
        continuity_checks,
    })
}

fn read_u32(bytes: &[u8], little_endian: bool) -> u32 {
    let bytes: [u8; 4] = bytes.try_into().unwrap();
    if little_endian {
        u32::from_le_bytes(bytes)
    } else {
        u32::from_be_bytes(bytes)
    }
}

fn div_ceil(value: u64, divisor: u64) -> u64 {
    value.div_ceil(divisor)
}

fn write_json_create_new<T: Serialize>(path: &Path, value: &T) -> Result<(), String> {
    let bytes = serde_json::to_vec_pretty(value)
        .map_err(|error| format!("serialize {} failed: {error}", path.display()))?;
    let mut file = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(path)
        .map_err(|error| format!("create {} failed: {error}", path.display()))?;
    file.write_all(&bytes)
        .and_then(|_| file.flush())
        .and_then(|_| file.sync_all())
        .map_err(|error| format!("write {} failed: {error}", path.display()))
}
