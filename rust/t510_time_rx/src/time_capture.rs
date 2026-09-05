use crate::{SampleRateMode, T510Header, STREAM_TIME, TIME_NINPUT, TIME_SUBSAMPLES_PER_BEAT};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::mpsc::{self, Receiver, SyncSender};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

const HEADER_BYTES: usize = 128;
const FLOW_COUNT: usize = 8;
const COMPONENTS: usize = TIME_NINPUT * 2;
const CODE_COUNT: usize = 1 << 16;
const START_LEAD_BUCKETS: u64 = 10;
const HISTOGRAM_BUCKETS: usize = 5;
const MAX_DURATION_SECONDS: u32 = 3600;
const NO_GENERATION: u64 = 0;

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
pub struct TimeCaptureRequest {
    pub scan_id: String,
    pub tuning_id: String,
    pub duration_seconds: u32,
    #[serde(default = "default_bucket_ms")]
    pub native_bucket_ms: u32,
    pub sample_rate_msps: u32,
    pub center_mhz: f64,
    #[serde(default)]
    pub metadata: BTreeMap<String, String>,
}

fn default_bucket_ms() -> u32 {
    10
}

#[derive(Debug, Clone, Default, Serialize)]
pub struct TimeCaptureProgress {
    pub completed_flow_mask: u16,
    pub flow_results_received: usize,
    pub packets_received: u64,
    pub samples_per_lane_received: u64,
    pub files_committed: u64,
    pub bytes_committed: u64,
}

#[derive(Debug, Clone, Serialize)]
pub struct TimeCaptureStatus {
    pub generation: u64,
    pub status: String,
    pub request: Option<TimeCaptureRequest>,
    pub output_dir: Option<String>,
    pub armed_unix_ms: Option<u64>,
    pub started_unix_ms: Option<u64>,
    pub finished_unix_ms: Option<u64>,
    pub origin_sample0: Option<u64>,
    pub start_sample0: Option<u64>,
    pub end_sample0: Option<u64>,
    pub progress: TimeCaptureProgress,
    pub error: Option<String>,
}

#[derive(Debug, Clone, Default)]
struct Control {
    generation: u64,
    status: String,
    request: Option<TimeCaptureRequest>,
    output_dir: Option<String>,
    armed_unix_ms: Option<u64>,
    started_unix_ms: Option<u64>,
    finished_unix_ms: Option<u64>,
    error: Option<String>,
}

#[derive(Debug, Clone)]
struct ActiveConfig {
    generation: u64,
    request: TimeCaptureRequest,
    bucket_width: u64,
    bucket_count: usize,
    start_offset: u64,
    end_offset: u64,
}

impl ActiveConfig {
    fn new(generation: u64, request: TimeCaptureRequest) -> Result<Self, String> {
        validate_request(&request)?;
        let bucket_width = u64::from(request.sample_rate_msps)
            .checked_mul(1_000)
            .and_then(|rate_per_ms| rate_per_ms.checked_mul(u64::from(request.native_bucket_ms)))
            .ok_or_else(|| "TIME bucket width overflow".to_string())?;
        let bucket_count = usize::try_from(
            u64::from(request.duration_seconds) * 1000 / u64::from(request.native_bucket_ms),
        )
        .map_err(|_| "TIME bucket count does not fit host usize".to_string())?;
        let start_offset = START_LEAD_BUCKETS * bucket_width;
        let end_offset = start_offset
            .checked_add(bucket_width * bucket_count as u64)
            .ok_or_else(|| "TIME capture range overflow".to_string())?;
        Ok(Self {
            generation,
            request,
            bucket_width,
            bucket_count,
            start_offset,
            end_offset,
        })
    }
}

fn validate_request(request: &TimeCaptureRequest) -> Result<(), String> {
    validate_identifier("scan_id", &request.scan_id)?;
    validate_identifier("tuning_id", &request.tuning_id)?;
    if !(1..=MAX_DURATION_SECONDS).contains(&request.duration_seconds) {
        return Err(format!(
            "duration_seconds must be within 1..={MAX_DURATION_SECONDS}"
        ));
    }
    if request.native_bucket_ms != 10 {
        return Err("TIME capture requires native_bucket_ms=10".to_string());
    }
    if request.sample_rate_msps != 320 {
        return Err("TIME capture requires sample_rate_msps=320".to_string());
    }
    if !request.center_mhz.is_finite() {
        return Err("center_mhz must be finite".to_string());
    }
    Ok(())
}

fn validate_identifier(name: &str, value: &str) -> Result<(), String> {
    if value.is_empty()
        || value.len() > 128
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_' | b'.'))
        || matches!(value, "." | "..")
    {
        return Err(format!(
            "{name} must use 1..128 ASCII letters, digits, '.', '-', or '_' without path components"
        ));
    }
    Ok(())
}

fn unix_time_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis()
        .min(u64::MAX as u128) as u64
}

#[derive(Clone, Debug)]
pub struct TimeCaptureController {
    root: PathBuf,
    active: Arc<AtomicBool>,
    writer_running: Arc<AtomicBool>,
    cancel: Arc<AtomicBool>,
    generation: Arc<AtomicU64>,
    origin_set: Arc<AtomicBool>,
    origin_sample0: Arc<AtomicU64>,
    completed_flow_mask: Arc<AtomicU64>,
    config: Arc<Mutex<Option<Arc<ActiveConfig>>>>,
    sender: Arc<Mutex<Option<SyncSender<FlowResult>>>>,
    control: Arc<Mutex<Control>>,
    progress: Arc<Mutex<TimeCaptureProgress>>,
}

impl TimeCaptureController {
    pub fn new(root: PathBuf) -> Self {
        Self {
            root,
            active: Arc::new(AtomicBool::new(false)),
            writer_running: Arc::new(AtomicBool::new(false)),
            cancel: Arc::new(AtomicBool::new(false)),
            generation: Arc::new(AtomicU64::new(NO_GENERATION)),
            origin_set: Arc::new(AtomicBool::new(false)),
            origin_sample0: Arc::new(AtomicU64::new(0)),
            completed_flow_mask: Arc::new(AtomicU64::new(0)),
            config: Arc::new(Mutex::new(None)),
            sender: Arc::new(Mutex::new(None)),
            control: Arc::new(Mutex::new(Control::default())),
            progress: Arc::new(Mutex::new(TimeCaptureProgress::default())),
        }
    }

    pub fn begin(&self, request: TimeCaptureRequest) -> Result<TimeCaptureStatus, String> {
        validate_request(&request)?;
        let mut control = self
            .control
            .lock()
            .map_err(|_| "TIME control lock poisoned")?;
        if self.is_active() {
            return Err("a TIME capture is already active".to_string());
        }
        fs::create_dir_all(&self.root)
            .map_err(|error| format!("create measurement root failed: {error}"))?;
        let output_dir = self.root.join(&request.scan_id);
        fs::create_dir(&output_dir).map_err(|error| {
            format!(
                "create new TIME directory {} failed: {error}",
                output_dir.display()
            )
        })?;
        let generation = control.generation.wrapping_add(1).max(1);
        let config = Arc::new(ActiveConfig::new(generation, request.clone())?);
        let (sender, receiver) = mpsc::sync_channel(FLOW_COUNT);
        self.active.store(false, Ordering::Release);
        self.writer_running.store(true, Ordering::Release);
        self.cancel.store(false, Ordering::Release);
        self.origin_set.store(false, Ordering::Release);
        self.origin_sample0.store(0, Ordering::Relaxed);
        self.completed_flow_mask.store(0, Ordering::Relaxed);
        *self
            .config
            .lock()
            .map_err(|_| "TIME config lock poisoned")? = Some(config.clone());
        *self
            .sender
            .lock()
            .map_err(|_| "TIME sender lock poisoned")? = Some(sender);
        *self
            .progress
            .lock()
            .map_err(|_| "TIME progress lock poisoned")? = TimeCaptureProgress::default();
        self.generation.store(generation, Ordering::Release);
        *control = Control {
            generation,
            status: "armed".to_string(),
            request: Some(request.clone()),
            output_dir: Some(output_dir.display().to_string()),
            armed_unix_ms: Some(unix_time_ms()),
            started_unix_ms: None,
            finished_unix_ms: None,
            error: None,
        };
        drop(control);

        let writer_control = self.control.clone();
        let writer_progress = self.progress.clone();
        let writer_cancel = self.cancel.clone();
        let writer_running = self.writer_running.clone();
        thread::Builder::new()
            .name("t510-time-capture-writer".to_string())
            .spawn(move || {
                run_writer(
                    output_dir,
                    config,
                    receiver,
                    writer_cancel,
                    writer_control,
                    writer_progress,
                    writer_running,
                );
            })
            .map_err(|error| format!("spawn TIME writer failed: {error}"))?;

        self.active.store(true, Ordering::Release);
        let watchdog = self.clone();
        thread::Builder::new()
            .name("t510-time-capture-watchdog".to_string())
            .spawn(move || {
                thread::sleep(Duration::from_secs(
                    u64::from(request.duration_seconds) + 30,
                ));
                if watchdog.generation.load(Ordering::Acquire) == generation
                    && watchdog.active.load(Ordering::Acquire)
                {
                    watchdog.fail(
                        generation,
                        "host watchdog expired before all eight TIME flows completed",
                    );
                }
            })
            .map_err(|error| format!("spawn TIME watchdog failed: {error}"))?;
        Ok(self.status())
    }

    pub fn is_active(&self) -> bool {
        self.active.load(Ordering::Acquire) || self.writer_running.load(Ordering::Acquire)
    }

    pub fn status(&self) -> TimeCaptureStatus {
        let control = self
            .control
            .lock()
            .map(|value| value.clone())
            .unwrap_or_default();
        let progress = self
            .progress
            .lock()
            .map(|value| value.clone())
            .unwrap_or_default();
        let origin = self
            .origin_set
            .load(Ordering::Acquire)
            .then(|| self.origin_sample0.load(Ordering::Relaxed));
        let config = self.config.lock().ok().and_then(|value| value.clone());
        TimeCaptureStatus {
            generation: control.generation,
            status: control.status,
            request: control.request,
            output_dir: control.output_dir,
            armed_unix_ms: control.armed_unix_ms,
            started_unix_ms: control.started_unix_ms,
            finished_unix_ms: control.finished_unix_ms,
            origin_sample0: origin,
            start_sample0: origin
                .zip(config.as_ref())
                .map(|(origin, config)| origin.wrapping_add(config.start_offset)),
            end_sample0: origin
                .zip(config.as_ref())
                .map(|(origin, config)| origin.wrapping_add(config.end_offset)),
            progress,
            error: control.error,
        }
    }

    pub fn stop(&self, reason: &str) -> Result<TimeCaptureStatus, String> {
        let generation = self.generation.load(Ordering::Acquire);
        if generation == NO_GENERATION {
            return Err("no TIME capture exists".to_string());
        }
        self.fail(generation, reason);
        Ok(self.status())
    }

    pub fn ingest(
        &self,
        worker: &mut TimeCaptureWorkerState,
        flow_id: usize,
        header: &T510Header,
        payload: &[u8],
    ) {
        if !self.active.load(Ordering::Acquire) || flow_id >= FLOW_COUNT {
            return;
        }
        let generation = self.generation.load(Ordering::Acquire);
        if worker.generation != generation {
            let Some(config) = self.config.lock().ok().and_then(|value| value.clone()) else {
                self.fail(generation, "active TIME config is missing");
                return;
            };
            let sender = self.sender.lock().ok().and_then(|value| value.clone());
            let Some(sender) = sender else {
                self.fail(generation, "TIME result sender is missing");
                return;
            };
            worker.reset(generation, flow_id, config, sender);
        }
        let Some(config) = worker.config.as_ref() else {
            self.fail(generation, "TIME worker config is missing");
            return;
        };
        if let Err(error) = validate_header(header, config.as_ref()) {
            self.fail(generation, &error);
            return;
        }
        if payload.len() < HEADER_BYTES + 8192 {
            self.fail(generation, "validated TIME payload is truncated");
            return;
        }
        if flow_id == 0 && !self.origin_set.load(Ordering::Acquire) {
            self.origin_sample0.store(header.sample0, Ordering::Relaxed);
            self.origin_set.store(true, Ordering::Release);
            if let Ok(mut control) = self.control.lock() {
                if control.generation == generation && control.status == "armed" {
                    control.status = "running".to_string();
                    control.started_unix_ms = Some(unix_time_ms());
                }
            }
        }
        if !self.origin_set.load(Ordering::Acquire) {
            return;
        }
        if worker.flow_id != Some(flow_id) {
            self.fail(
                generation,
                "one TIME worker received more than one destination flow",
            );
            return;
        }
        let origin = self.origin_sample0.load(Ordering::Relaxed);
        match worker.ingest(header, payload, origin) {
            Ok(true) => self.mark_flow_complete(generation, flow_id),
            Ok(false) => {}
            Err(error) => self.fail(generation, &error),
        }
    }

    fn mark_flow_complete(&self, generation: u64, flow_id: usize) {
        let bit = 1u64 << flow_id;
        let mask = self.completed_flow_mask.fetch_or(bit, Ordering::AcqRel) | bit;
        if let Ok(mut progress) = self.progress.lock() {
            progress.completed_flow_mask = mask as u16;
        }
        if mask & 0xff == 0xff && self.generation.load(Ordering::Acquire) == generation {
            self.active.store(false, Ordering::Release);
            if let Ok(mut control) = self.control.lock() {
                if control.generation == generation && control.status == "running" {
                    control.status = "draining".to_string();
                }
            }
        }
    }

    fn fail(&self, generation: u64, reason: &str) {
        if self.generation.load(Ordering::Acquire) != generation {
            return;
        }
        self.active.store(false, Ordering::Release);
        self.cancel.store(true, Ordering::Release);
        if let Ok(mut control) = self.control.lock() {
            if control.generation == generation && control.status != "completed" {
                control.status = "failed".to_string();
                control.error.get_or_insert_with(|| reason.to_string());
                control.finished_unix_ms.get_or_insert_with(unix_time_ms);
            }
        }
    }
}

fn validate_header(header: &T510Header, config: &ActiveConfig) -> Result<(), String> {
    if header.stream_type != STREAM_TIME
        || header.ninput as usize != TIME_NINPUT
        || header.time_count as usize * TIME_SUBSAMPLES_PER_BEAT != 256
        || header.chan_count != 0
        || header.spec_sample_rate_hz != 0
        || header.payload_bytes != 8192
        || SampleRateMode::from_mhz(config.request.sample_rate_msps)
            != Some(SampleRateMode::Msps320)
    {
        return Err(format!(
            "TIME identity mismatch: stream={} ninput={} time_count={} chan_count={} spec_rate={} payload_bytes={}",
            header.stream_type,
            header.ninput,
            header.time_count,
            header.chan_count,
            header.spec_sample_rate_hz,
            header.payload_bytes
        ));
    }
    Ok(())
}

#[derive(Debug, Clone, Copy)]
struct LaneMoments {
    sum_i: i64,
    sum_q: i64,
    sum_i2: u64,
    sum_q2: u64,
    min_i: i16,
    max_i: i16,
    min_q: i16,
    max_q: i16,
    clip_i: u64,
    clip_q: u64,
}

impl Default for LaneMoments {
    fn default() -> Self {
        Self {
            sum_i: 0,
            sum_q: 0,
            sum_i2: 0,
            sum_q2: 0,
            min_i: i16::MAX,
            max_i: i16::MIN,
            min_q: i16::MAX,
            max_q: i16::MIN,
            clip_i: 0,
            clip_q: 0,
        }
    }
}

impl LaneMoments {
    fn add(&mut self, i: i16, q: i16) {
        let ii = i as i64;
        let qq = q as i64;
        self.sum_i += ii;
        self.sum_q += qq;
        self.sum_i2 += (ii * ii) as u64;
        self.sum_q2 += (qq * qq) as u64;
        self.min_i = self.min_i.min(i);
        self.max_i = self.max_i.max(i);
        self.min_q = self.min_q.min(q);
        self.max_q = self.max_q.max(q);
        self.clip_i += u64::from(i == i16::MIN || i.abs() >= 32760);
        self.clip_q += u64::from(q == i16::MIN || q.abs() >= 32760);
    }

    fn merge(&mut self, other: &Self) {
        self.sum_i += other.sum_i;
        self.sum_q += other.sum_q;
        self.sum_i2 += other.sum_i2;
        self.sum_q2 += other.sum_q2;
        self.min_i = self.min_i.min(other.min_i);
        self.max_i = self.max_i.max(other.max_i);
        self.min_q = self.min_q.min(other.min_q);
        self.max_q = self.max_q.max(other.max_q);
        self.clip_i += other.clip_i;
        self.clip_q += other.clip_q;
    }
}

#[derive(Debug, Clone)]
struct TimeBucket {
    samples_per_lane: u64,
    packets: u64,
    first_sample0: Option<u64>,
    last_sample0: u64,
    lanes: [LaneMoments; TIME_NINPUT],
}

impl Default for TimeBucket {
    fn default() -> Self {
        Self {
            samples_per_lane: 0,
            packets: 0,
            first_sample0: None,
            last_sample0: 0,
            lanes: std::array::from_fn(|_| LaneMoments::default()),
        }
    }
}

impl TimeBucket {
    fn merge(&mut self, other: &Self) {
        self.samples_per_lane += other.samples_per_lane;
        self.packets += other.packets;
        if let Some(first) = other.first_sample0 {
            self.first_sample0 = Some(self.first_sample0.map_or(first, |value| value.min(first)));
        }
        self.last_sample0 = self.last_sample0.max(other.last_sample0);
        for lane in 0..TIME_NINPUT {
            self.lanes[lane].merge(&other.lanes[lane]);
        }
    }
}

struct FlowResult {
    flow_id: usize,
    packets: u64,
    missing_packets: u64,
    reordered_packets: u64,
    duplicate_packets: u64,
    first_seq: Option<u32>,
    last_seq: Option<u32>,
    first_sample0: Option<u64>,
    last_sample0: Option<u64>,
    buckets: Vec<TimeBucket>,
    histogram: Box<[u32]>,
    histogram_samples_per_lane: u64,
}

#[derive(Default)]
pub struct TimeCaptureWorkerState {
    generation: u64,
    flow_id: Option<usize>,
    config: Option<Arc<ActiveConfig>>,
    sender: Option<SyncSender<FlowResult>>,
    result: Option<FlowResult>,
    previous: Option<T510Header>,
    sent: bool,
}

impl TimeCaptureWorkerState {
    fn reset(
        &mut self,
        generation: u64,
        flow_id: usize,
        config: Arc<ActiveConfig>,
        sender: SyncSender<FlowResult>,
    ) {
        self.generation = generation;
        self.flow_id = Some(flow_id);
        let bucket_count = config.bucket_count;
        self.config = Some(config);
        self.sender = Some(sender);
        self.result = Some(FlowResult {
            flow_id,
            packets: 0,
            missing_packets: 0,
            reordered_packets: 0,
            duplicate_packets: 0,
            first_seq: None,
            last_seq: None,
            first_sample0: None,
            last_sample0: None,
            buckets: vec![TimeBucket::default(); bucket_count],
            histogram: vec![0u32; COMPONENTS * CODE_COUNT].into_boxed_slice(),
            histogram_samples_per_lane: 0,
        });
        self.previous = None;
        self.sent = false;
    }

    fn ingest(&mut self, header: &T510Header, payload: &[u8], origin: u64) -> Result<bool, String> {
        if self.sent {
            return Ok(false);
        }
        let config = self
            .config
            .as_ref()
            .ok_or_else(|| "TIME worker config missing".to_string())?;
        let delta = header.sample0.wrapping_sub(origin);
        if delta >= (1u64 << 63) || delta < config.start_offset {
            return Ok(false);
        }
        if delta >= config.end_offset {
            let result = self
                .result
                .take()
                .ok_or_else(|| "TIME flow result missing".to_string())?;
            self.sender
                .as_ref()
                .ok_or_else(|| "TIME result sender missing".to_string())?
                .send(result)
                .map_err(|_| "TIME writer disconnected".to_string())?;
            self.sent = true;
            return Ok(true);
        }
        let result = self
            .result
            .as_mut()
            .ok_or_else(|| "TIME flow result missing".to_string())?;
        if let Some(previous) = self.previous {
            let seq_delta = header.seq_no.wrapping_sub(previous.seq_no);
            let frame_delta = header.frame_id.wrapping_sub(previous.frame_id);
            let sample_delta = header.sample0.wrapping_sub(previous.sample0);
            if seq_delta == 0 || frame_delta == 0 || sample_delta == 0 {
                result.duplicate_packets += 1;
                return Ok(false);
            }
            if seq_delta >= (1u32 << 31)
                || frame_delta >= (1u64 << 63)
                || sample_delta >= (1u64 << 63)
            {
                result.reordered_packets += 1;
                return Ok(false);
            }
            let expected = FLOW_COUNT as u64;
            if u64::from(seq_delta) != expected
                || frame_delta != expected
                || sample_delta != expected * 256
            {
                let missing = u64::from(seq_delta)
                    .saturating_div(expected)
                    .saturating_sub(1);
                result.missing_packets += missing.max(1);
            }
        }
        self.previous = Some(*header);
        result.first_seq.get_or_insert(header.seq_no);
        result.last_seq = Some(header.seq_no);
        result.first_sample0.get_or_insert(header.sample0);
        result.last_sample0 = Some(header.sample0);
        result.packets += 1;
        let bucket_index = usize::try_from((delta - config.start_offset) / config.bucket_width)
            .map_err(|_| "TIME bucket index does not fit host usize".to_string())?;
        let bucket = result
            .buckets
            .get_mut(bucket_index)
            .ok_or_else(|| format!("TIME bucket {bucket_index} out of range"))?;
        bucket.packets += 1;
        bucket.samples_per_lane += 256;
        bucket.first_sample0.get_or_insert(header.sample0);
        bucket.last_sample0 = header.sample0 + 255;
        for sample in 0..256usize {
            let base = HEADER_BYTES + sample * TIME_NINPUT * 4;
            for lane in 0..TIME_NINPUT {
                let offset = base + lane * 4;
                let i = i16::from_le_bytes([payload[offset], payload[offset + 1]]);
                let q = i16::from_le_bytes([payload[offset + 2], payload[offset + 3]]);
                bucket.lanes[lane].add(i, q);
                if bucket_index < HISTOGRAM_BUCKETS {
                    let i_index =
                        (lane * 2) * CODE_COUNT + u16::from_ne_bytes(i.to_ne_bytes()) as usize;
                    let q_index =
                        (lane * 2 + 1) * CODE_COUNT + u16::from_ne_bytes(q.to_ne_bytes()) as usize;
                    result.histogram[i_index] = result.histogram[i_index].saturating_add(1);
                    result.histogram[q_index] = result.histogram[q_index].saturating_add(1);
                }
            }
            if bucket_index < HISTOGRAM_BUCKETS {
                result.histogram_samples_per_lane += 1;
            }
        }
        Ok(false)
    }
}

#[derive(Serialize)]
struct FileIdentity {
    path: String,
    bytes: u64,
    sha256: String,
}

fn run_writer(
    root: PathBuf,
    config: Arc<ActiveConfig>,
    receiver: Receiver<FlowResult>,
    cancel: Arc<AtomicBool>,
    control: Arc<Mutex<Control>>,
    progress: Arc<Mutex<TimeCaptureProgress>>,
    writer_running: Arc<AtomicBool>,
) {
    let result = collect_and_write(&root, &config, &receiver, &cancel, &progress);
    if let Ok(mut control) = control.lock() {
        if control.generation == config.generation {
            control.finished_unix_ms = Some(unix_time_ms());
            match result {
                Ok(()) if !cancel.load(Ordering::Acquire) => {
                    control.status = "completed".to_string();
                    control.error = None;
                }
                Ok(()) => {
                    control.status = "failed".to_string();
                    control
                        .error
                        .get_or_insert_with(|| "TIME capture cancelled".to_string());
                }
                Err(error) => {
                    control.status = "failed".to_string();
                    control.error.get_or_insert(error);
                }
            }
        }
    }
    writer_running.store(false, Ordering::Release);
}

fn collect_and_write(
    root: &Path,
    config: &ActiveConfig,
    receiver: &Receiver<FlowResult>,
    cancel: &AtomicBool,
    progress: &Mutex<TimeCaptureProgress>,
) -> Result<(), String> {
    let mut flows = Vec::with_capacity(FLOW_COUNT);
    while flows.len() < FLOW_COUNT {
        if cancel.load(Ordering::Acquire) {
            return Err("TIME capture cancelled before all flow results arrived".to_string());
        }
        match receiver.recv_timeout(Duration::from_millis(100)) {
            Ok(flow) => {
                if flows
                    .iter()
                    .any(|prior: &FlowResult| prior.flow_id == flow.flow_id)
                {
                    return Err(format!("duplicate TIME result for flow {}", flow.flow_id));
                }
                if let Ok(mut value) = progress.lock() {
                    value.flow_results_received += 1;
                    value.packets_received += flow.packets;
                    value.samples_per_lane_received += flow.packets * 256;
                }
                flows.push(flow);
            }
            Err(mpsc::RecvTimeoutError::Timeout) => {}
            Err(mpsc::RecvTimeoutError::Disconnected) => {
                return Err("TIME result channel disconnected".to_string());
            }
        }
    }
    flows.sort_by_key(|flow| flow.flow_id);
    let mut buckets = vec![TimeBucket::default(); config.bucket_count];
    let mut histogram = vec![0u64; COMPONENTS * CODE_COUNT];
    for flow in &flows {
        for (target, source) in buckets.iter_mut().zip(&flow.buckets) {
            target.merge(source);
        }
        for (target, source) in histogram.iter_mut().zip(flow.histogram.iter()) {
            *target += u64::from(*source);
        }
    }
    let expected_samples = config.bucket_width;
    let mut files = Vec::new();
    files.push(write_flow_quality(root, &flows)?);
    if buckets
        .iter()
        .any(|bucket| bucket.samples_per_lane != expected_samples)
    {
        files.push(write_coverage(root, &buckets, expected_samples)?);
        return Err("one or more 10 ms TIME buckets have incomplete sample coverage".to_string());
    }

    files.push(write_buckets(root, "time_10ms.csv", &buckets, 10)?);
    let buckets20: Vec<TimeBucket> = buckets
        .chunks_exact(2)
        .map(|pair| {
            let mut merged = TimeBucket::default();
            merged.merge(&pair[0]);
            merged.merge(&pair[1]);
            merged
        })
        .collect();
    files.push(write_buckets(root, "time_20ms.csv", &buckets20, 20)?);
    files.push(write_histogram(root, &histogram)?);
    files.push(write_summary(root, config, &buckets, &histogram, &flows)?);
    let manifest = serde_json::json!({
        "format": "T510_TIME_CAPTURE_V1",
        "schema_version": 2,
        "complete": true,
        "request": config.request,
        "unit": "RFDC/TIME post-DDC/decimation ADU; not 3.84 GS/s converter raw code",
        "native_bucket_ms": 10,
        "derived_bucket_ms": 20,
        "bucket_count_10ms": buckets.len(),
        "bucket_count_20ms": buckets20.len(),
        "histogram_duration_ms": HISTOGRAM_BUCKETS * 10,
        "histogram_samples_per_lane": flows.iter().map(|flow| flow.histogram_samples_per_lane).sum::<u64>(),
        "expected_samples_per_lane": u64::from(config.request.sample_rate_msps) * 1_000_000 * u64::from(config.request.duration_seconds),
        "files": files,
    });
    let bytes = serde_json::to_vec_pretty(&manifest).map_err(|error| error.to_string())?;
    let identity = write_file(root, "dataset_manifest.json", &bytes)?;
    let digest = format!("{}  dataset_manifest.json\n", identity.sha256);
    let digest_identity = write_file(root, "dataset_manifest.sha256", digest.as_bytes())?;
    if let Ok(mut value) = progress.lock() {
        value.files_committed = files.len() as u64 + 2;
        value.bytes_committed = files.iter().map(|file| file.bytes).sum::<u64>()
            + identity.bytes
            + digest_identity.bytes;
    }
    Ok(())
}

fn write_buckets(
    root: &Path,
    name: &str,
    buckets: &[TimeBucket],
    bucket_ms: u32,
) -> Result<FileIdentity, String> {
    let mut out = Vec::new();
    writeln!(out, "bucket,bucket_ms,lane,samples,packets,first_sample0,last_sample0,mean_i_adu,mean_q_adu,std_i_adu,std_q_adu,complex_rms_adu,min_i,max_i,min_q,max_q,clip_i,clip_q,mean_power_adu2")
        .map_err(|error| error.to_string())?;
    for (index, bucket) in buckets.iter().enumerate() {
        let n = bucket.samples_per_lane as f64;
        for lane in 0..TIME_NINPUT {
            let value = &bucket.lanes[lane];
            let mean_i = value.sum_i as f64 / n;
            let mean_q = value.sum_q as f64 / n;
            let mean_i2 = value.sum_i2 as f64 / n;
            let mean_q2 = value.sum_q2 as f64 / n;
            let std_i = (mean_i2 - mean_i * mean_i).max(0.0).sqrt();
            let std_q = (mean_q2 - mean_q * mean_q).max(0.0).sqrt();
            let complex_rms = (mean_i2 + mean_q2).sqrt();
            let mean_power = mean_i2 + mean_q2;
            writeln!(out, "{index},{bucket_ms},{lane},{},{},{},{},{mean_i:.12},{mean_q:.12},{std_i:.12},{std_q:.12},{complex_rms:.12},{},{},{},{},{},{},{mean_power:.12}",
                bucket.samples_per_lane, bucket.packets, bucket.first_sample0.unwrap_or_default(), bucket.last_sample0,
                value.min_i, value.max_i, value.min_q, value.max_q, value.clip_i, value.clip_q)
                .map_err(|error| error.to_string())?;
        }
    }
    write_file(root, name, &out)
}

fn write_histogram(root: &Path, histogram: &[u64]) -> Result<FileIdentity, String> {
    let mut out = Vec::new();
    writeln!(out, "lane,component,code,count").map_err(|error| error.to_string())?;
    for lane in 0..TIME_NINPUT {
        for component in 0..2usize {
            let base = (lane * 2 + component) * CODE_COUNT;
            for raw in 0..CODE_COUNT {
                let count = histogram[base + raw];
                if count != 0 {
                    let code = i16::from_ne_bytes((raw as u16).to_ne_bytes());
                    writeln!(
                        out,
                        "{lane},{},{code},{count}",
                        if component == 0 { "I" } else { "Q" }
                    )
                    .map_err(|error| error.to_string())?;
                }
            }
        }
    }
    write_file(root, "histogram.csv", &out)
}

fn write_flow_quality(root: &Path, flows: &[FlowResult]) -> Result<FileIdentity, String> {
    let rows: Vec<_> = flows
        .iter()
        .map(|flow| {
            serde_json::json!({
                "flow_id": flow.flow_id,
                "dst_port": 4300 + flow.flow_id,
                "packets": flow.packets,
                "missing_packets": flow.missing_packets,
                "reordered_packets": flow.reordered_packets,
                "duplicate_packets": flow.duplicate_packets,
                "first_seq": flow.first_seq,
                "last_seq": flow.last_seq,
                "first_sample0": flow.first_sample0,
                "last_sample0": flow.last_sample0,
                "histogram_samples_per_lane": flow.histogram_samples_per_lane,
            })
        })
        .collect();
    let bytes = serde_json::to_vec_pretty(&rows).map_err(|error| error.to_string())?;
    write_file(root, "flow_quality.json", &bytes)
}

fn write_coverage(
    root: &Path,
    buckets: &[TimeBucket],
    expected_samples_per_lane: u64,
) -> Result<FileIdentity, String> {
    let rows: Vec<_> = buckets
        .iter()
        .enumerate()
        .map(|(bucket, value)| {
            serde_json::json!({
                "bucket": bucket,
                "expected_samples_per_lane": expected_samples_per_lane,
                "valid_samples_per_lane": value.samples_per_lane,
                "missing_samples_per_lane": expected_samples_per_lane.saturating_sub(value.samples_per_lane),
                "packets": value.packets,
            })
        })
        .collect();
    let bytes = serde_json::to_vec_pretty(&rows).map_err(|error| error.to_string())?;
    write_file(root, "coverage_failure.json", &bytes)
}

fn write_summary(
    root: &Path,
    config: &ActiveConfig,
    buckets: &[TimeBucket],
    histogram: &[u64],
    flows: &[FlowResult],
) -> Result<FileIdentity, String> {
    let mut totals: [LaneMoments; TIME_NINPUT] = std::array::from_fn(|_| LaneMoments::default());
    let mut sample_count = 0u64;
    for bucket in buckets {
        sample_count += bucket.samples_per_lane;
        for (total, lane) in totals.iter_mut().zip(&bucket.lanes) {
            total.merge(lane);
        }
    }
    let n = sample_count as f64;
    let lanes: Vec<_> = totals
        .iter()
        .enumerate()
        .map(|(lane, value)| {
            let mean_i = value.sum_i as f64 / n;
            let mean_q = value.sum_q as f64 / n;
            let mean_i2 = value.sum_i2 as f64 / n;
            let mean_q2 = value.sum_q2 as f64 / n;
            let occupancy_i = histogram[(lane * 2) * CODE_COUNT..(lane * 2 + 1) * CODE_COUNT]
                .iter()
                .filter(|count| **count != 0)
                .count();
            let occupancy_q = histogram[(lane * 2 + 1) * CODE_COUNT..(lane * 2 + 2) * CODE_COUNT]
                .iter()
                .filter(|count| **count != 0)
                .count();
            serde_json::json!({
                "lane": lane,
                "samples": sample_count,
                "mean_i_adu": mean_i,
                "mean_q_adu": mean_q,
                "std_i_adu": (mean_i2 - mean_i * mean_i).max(0.0).sqrt(),
                "std_q_adu": (mean_q2 - mean_q * mean_q).max(0.0).sqrt(),
                "complex_rms_adu": (mean_i2 + mean_q2).sqrt(),
                "min_i": value.min_i,
                "max_i": value.max_i,
                "min_q": value.min_q,
                "max_q": value.max_q,
                "clip_i": value.clip_i,
                "clip_q": value.clip_q,
                "occupied_i_codes": occupancy_i,
                "occupied_q_codes": occupancy_q,
            })
        })
        .collect();
    let summary = serde_json::json!({
        "request": config.request,
        "data_path_identity": "RFDC/TIME post-DDC/decimation complex IQ16",
        "not_converter_raw": true,
        "samples_per_lane": sample_count,
        "packets": flows.iter().map(|flow| flow.packets).sum::<u64>(),
        "missing_packets": flows.iter().map(|flow| flow.missing_packets).sum::<u64>(),
        "reordered_packets": flows.iter().map(|flow| flow.reordered_packets).sum::<u64>(),
        "duplicate_packets": flows.iter().map(|flow| flow.duplicate_packets).sum::<u64>(),
        "histogram_duration_ms": HISTOGRAM_BUCKETS * 10,
        "histogram_samples_per_lane": flows.iter().map(|flow| flow.histogram_samples_per_lane).sum::<u64>(),
        "lanes": lanes,
    });
    let bytes = serde_json::to_vec_pretty(&summary).map_err(|error| error.to_string())?;
    write_file(root, "summary.json", &bytes)
}

fn write_file(root: &Path, name: &str, bytes: &[u8]) -> Result<FileIdentity, String> {
    let partial = root.join(format!("{name}.partial"));
    let path = root.join(name);
    let mut file = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(&partial)
        .map_err(|error| format!("create {} failed: {error}", partial.display()))?;
    file.write_all(bytes)
        .and_then(|_| file.flush())
        .and_then(|_| file.sync_all())
        .map_err(|error| format!("write {} failed: {error}", partial.display()))?;
    drop(file);
    fs::rename(&partial, &path)
        .map_err(|error| format!("commit {} failed: {error}", path.display()))?;
    let mut hasher = Sha256::new();
    hasher.update(bytes);
    Ok(FileIdentity {
        path: name.to_string(),
        bytes: bytes.len() as u64,
        sha256: format!("{:x}", hasher.finalize()),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn request() -> TimeCaptureRequest {
        TimeCaptureRequest {
            scan_id: "time-test".to_string(),
            tuning_id: "tuning-1020mhz".to_string(),
            duration_seconds: 1,
            native_bucket_ms: 10,
            sample_rate_msps: 320,
            center_mhz: 1020.0,
            metadata: BTreeMap::new(),
        }
    }

    #[test]
    fn request_and_bucket_geometry_are_fixed_for_s1() {
        let config = ActiveConfig::new(1, request()).unwrap();
        assert_eq!(config.bucket_width, 3_200_000);
        assert_eq!(config.bucket_count, 100);
        assert_eq!(config.start_offset, 32_000_000);
        let mut bad = request();
        bad.native_bucket_ms = 20;
        assert!(ActiveConfig::new(1, bad).is_err());
    }

    #[test]
    fn exact_moments_merge_without_losing_min_max_or_clips() {
        let mut first = LaneMoments::default();
        first.add(-32768, 4);
        let mut second = LaneMoments::default();
        second.add(3, 32760);
        first.merge(&second);
        assert_eq!(first.sum_i, -32765);
        assert_eq!(first.sum_q, 32764);
        assert_eq!(first.min_i, -32768);
        assert_eq!(first.max_q, 32760);
        assert_eq!(first.clip_i, 1);
        assert_eq!(first.clip_q, 1);
    }

    #[test]
    fn bucket_csv_keeps_direct_mean_integer_power() {
        let mut bucket = TimeBucket {
            samples_per_lane: 2,
            packets: 1,
            first_sample0: Some(100),
            last_sample0: 356,
            ..TimeBucket::default()
        };
        for lane in 0..TIME_NINPUT {
            bucket.lanes[lane].add(3, 4);
            bucket.lanes[lane].add(-3, 4);
        }
        let root = std::env::temp_dir().join(format!(
            "t510-time-capture-power-{}-{}",
            std::process::id(),
            unix_time_ms()
        ));
        fs::create_dir(&root).unwrap();
        write_buckets(&root, "time.csv", &[bucket], 10).unwrap();
        let text = fs::read_to_string(root.join("time.csv")).unwrap();
        let mut lines = text.lines();
        assert!(lines.next().unwrap().ends_with(",mean_power_adu2"));
        for line in lines {
            assert_eq!(line.split(',').next_back().unwrap(), "25.000000000000");
        }
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn synthetic_time_packet_replay_preserves_iq_and_power_moments() {
        let config = Arc::new(ActiveConfig::new(1, request()).unwrap());
        let (sender, _receiver) = mpsc::sync_channel(FLOW_COUNT);
        let mut worker = TimeCaptureWorkerState::default();
        worker.reset(1, 0, config.clone(), sender);
        let mut payload = vec![0u8; HEADER_BYTES + 8192];
        for sample in 0..256usize {
            for lane in 0..TIME_NINPUT {
                let offset = HEADER_BYTES + sample * TIME_NINPUT * 4 + lane * 4;
                payload[offset..offset + 2].copy_from_slice(&3i16.to_le_bytes());
                payload[offset + 2..offset + 4].copy_from_slice(&(-4i16).to_le_bytes());
            }
        }
        let header = T510Header {
            magic: 0x5435_3130,
            version: 1,
            header_bytes: HEADER_BYTES as u16,
            board_id: 1,
            stream_type: STREAM_TIME,
            epoch_mode: 0,
            flags: 0,
            unix_sec: 0,
            pps_count: 0,
            sample0: config.start_offset,
            frame_id: 0,
            seq_no: 0,
            chan0: 0,
            chan_count: 0,
            time_count: 32,
            ninput: TIME_NINPUT as u16,
            payload_format: 1,
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
            sync_generation: 0,
            sync_observation_tag: 0,
            sync_metadata: 0,
            sync_status: 0,
        };
        assert!(!worker.ingest(&header, &payload, 0).unwrap());
        let result = worker.result.as_ref().unwrap();
        let bucket = &result.buckets[0];
        assert_eq!(bucket.samples_per_lane, 256);
        assert_eq!(bucket.lanes[0].sum_i, 768);
        assert_eq!(bucket.lanes[0].sum_q, -1024);
        assert_eq!(bucket.lanes[0].sum_i2 + bucket.lanes[0].sum_q2, 256 * 25);
    }
}
