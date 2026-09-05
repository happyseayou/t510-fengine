use crate::{
    T510Header, SPEC_BLOCK_CHANS, SPEC_BLOCK_COUNT, SPEC_NCHAN, SPEC_PFB_ACTIVE_FLAG,
    SPEC_TIME_COUNT, STREAM_SPEC, TIME_NINPUT,
};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, VecDeque};
use std::fs::{self, File, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, AtomicU64, AtomicUsize, Ordering};
use std::sync::mpsc::{self, Receiver, SyncSender, TrySendError};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

const HEADER_BYTES: usize = 128;
const CELLS_PER_BLOCK: usize = SPEC_BLOCK_CHANS as usize * TIME_NINPUT;
// Give every fanout worker time to observe the new capture generation before
// the first formal bucket. This is a warm-up lead only; native integration
// remains 10 ms. Ten buckets give the minimum-width capture a 100 ms lead.
const AUTOCORRELATION_START_LEAD_BUCKETS: u64 = 10;
const AUTOCORRELATION_REORDER_WINDOW: usize = 8;
const AUTOCORRELATION_WRITER_QUEUE_CAPACITY: usize = 2048;
const AUTOCORRELATION_MAX_DURATION_SECONDS: u32 = 3600;
const AUTOCORRELATION_SAMPLE_RATE_HZ: u64 = 320_000_000;
const AUTOCORRELATION_FRAME_SAMPLE0_STEP: u64 = 4096;
const AUTOCORRELATION_MAX_NATIVE_BUCKET_FRAMES: u64 =
    (AUTOCORRELATION_SAMPLE_RATE_HZ / 10).div_ceil(AUTOCORRELATION_FRAME_SAMPLE0_STEP);
const NO_GENERATION: u64 = 0;

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
pub struct AutocorrelationRequest {
    pub scan_id: String,
    pub tuning_id: String,
    pub duration_seconds: u32,
    #[serde(default = "default_native_bucket_ms")]
    pub native_bucket_ms: u32,
    pub sample_rate_msps: u32,
    pub center_mhz: f64,
    #[serde(default)]
    pub expected_fft_shift: Option<u16>,
    #[serde(default)]
    pub metadata: BTreeMap<String, String>,
}

fn default_native_bucket_ms() -> u32 {
    10
}

#[derive(Debug, Clone, Default, Serialize)]
pub struct MeasurementWriterProgress {
    pub native_rows_received: u64,
    pub moment_100ms_rows_received: u64,
    pub gap_ranges_received: u64,
    pub arrival_events_received: u64,
    pub files_committed: u64,
    pub bytes_committed: u64,
}

#[derive(Debug, Clone, Serialize)]
pub struct AutocorrelationStatus {
    pub generation: u64,
    pub status: String,
    pub request: Option<AutocorrelationRequest>,
    pub output_dir: Option<String>,
    pub armed_unix_ms: Option<u64>,
    pub started_unix_ms: Option<u64>,
    pub finished_unix_ms: Option<u64>,
    pub origin_sample0: Option<u64>,
    pub origin_frame_group: Option<u64>,
    pub completed_block_mask: u16,
    pub queued_messages: usize,
    pub queue_high_water: usize,
    pub writer: MeasurementWriterProgress,
    pub error: Option<String>,
}

#[derive(Debug, Clone)]
struct AutocorrelationControl {
    generation: u64,
    status: String,
    request: Option<AutocorrelationRequest>,
    output_dir: Option<String>,
    armed_unix_ms: Option<u64>,
    started_unix_ms: Option<u64>,
    finished_unix_ms: Option<u64>,
    error: Option<String>,
}

impl Default for AutocorrelationControl {
    fn default() -> Self {
        Self {
            generation: NO_GENERATION,
            status: "idle".to_string(),
            request: None,
            output_dir: None,
            armed_unix_ms: None,
            started_unix_ms: None,
            finished_unix_ms: None,
            error: None,
        }
    }
}

#[derive(Debug, Clone)]
struct ActiveConfig {
    generation: u64,
    request: AutocorrelationRequest,
    bucket_width_ticks: u64,
    native_bucket_count: u64,
    start_bucket: u64,
    end_bucket: u64,
    buckets_per_100ms: u64,
}

impl ActiveConfig {
    #[cfg(test)]
    fn from_request(generation: u64, request: AutocorrelationRequest) -> Result<Self, String> {
        Self::from_request_with_start_lead(generation, request, AUTOCORRELATION_START_LEAD_BUCKETS)
    }

    fn from_request_with_start_lead(
        generation: u64,
        request: AutocorrelationRequest,
        start_bucket: u64,
    ) -> Result<Self, String> {
        validate_request(&request)?;
        if start_bucket == 0 || start_bucket > 10_000 {
            return Err("start lead must be within 1..=10000 native buckets".to_string());
        }
        let duration_ms = u64::from(request.duration_seconds) * 1000;
        let bucket_ms = u64::from(request.native_bucket_ms);
        let native_bucket_count = duration_ms / bucket_ms;
        let bucket_width_ticks = AUTOCORRELATION_SAMPLE_RATE_HZ
            .checked_mul(bucket_ms)
            .and_then(|value| value.checked_div(1000))
            .ok_or_else(|| "native bucket width overflow".to_string())?;
        let end_bucket = start_bucket
            .checked_add(native_bucket_count)
            .ok_or_else(|| "native bucket count overflow".to_string())?;
        Ok(Self {
            generation,
            request,
            bucket_width_ticks,
            native_bucket_count,
            start_bucket,
            end_bucket,
            buckets_per_100ms: 100 / bucket_ms,
        })
    }

    fn moment_100ms_count(&self) -> u64 {
        self.native_bucket_count / self.buckets_per_100ms
    }
}

#[derive(Debug, Clone, Copy)]
struct HotConfig {
    bucket_width_ticks: u64,
    native_bucket_count: u64,
    start_bucket: u64,
    end_bucket: u64,
    buckets_per_100ms: u64,
    expected_fft_shift: Option<u16>,
}

impl From<&ActiveConfig> for HotConfig {
    fn from(config: &ActiveConfig) -> Self {
        Self {
            bucket_width_ticks: config.bucket_width_ticks,
            native_bucket_count: config.native_bucket_count,
            start_bucket: config.start_bucket,
            end_bucket: config.end_bucket,
            buckets_per_100ms: config.buckets_per_100ms,
            expected_fft_shift: config.request.expected_fft_shift,
        }
    }
}

impl HotConfig {
    fn bucket_for_sample0(&self, origin_sample0: u64, sample0: u64) -> Option<u64> {
        let delta = sample0.wrapping_sub(origin_sample0);
        if delta >= (1u64 << 63) {
            return None;
        }
        Some(delta / self.bucket_width_ticks)
    }

    fn output_index(&self, absolute_bucket: u64) -> Option<u64> {
        absolute_bucket
            .checked_sub(self.start_bucket)
            .filter(|index| *index < self.native_bucket_count)
    }

    fn expected_native_frames(&self, output_index: u64) -> u64 {
        let absolute_bucket = self.start_bucket + output_index;
        let start = absolute_bucket * self.bucket_width_ticks;
        let end = start + self.bucket_width_ticks;
        div_ceil_u64(end, AUTOCORRELATION_FRAME_SAMPLE0_STEP)
            .saturating_sub(div_ceil_u64(start, AUTOCORRELATION_FRAME_SAMPLE0_STEP))
    }

    fn expected_100ms_frames(&self, output_index: u64) -> u64 {
        let native_index = output_index * self.buckets_per_100ms;
        let absolute_bucket = self.start_bucket + native_index;
        let start = absolute_bucket * self.bucket_width_ticks;
        let end = start + AUTOCORRELATION_SAMPLE_RATE_HZ / 10;
        div_ceil_u64(end, AUTOCORRELATION_FRAME_SAMPLE0_STEP)
            .saturating_sub(div_ceil_u64(start, AUTOCORRELATION_FRAME_SAMPLE0_STEP))
    }
}

fn validate_request(request: &AutocorrelationRequest) -> Result<(), String> {
    validate_identifier("scan_id", &request.scan_id)?;
    validate_identifier("tuning_id", &request.tuning_id)?;
    if !(1..=AUTOCORRELATION_MAX_DURATION_SECONDS).contains(&request.duration_seconds) {
        return Err(format!(
            "duration_seconds must be within 1..={AUTOCORRELATION_MAX_DURATION_SECONDS}"
        ));
    }
    if !matches!(request.native_bucket_ms, 10 | 20 | 50 | 100) {
        return Err("native_bucket_ms must be 10, 20, 50, or 100".to_string());
    }
    if !request
        .duration_seconds
        .saturating_mul(1000)
        .is_multiple_of(request.native_bucket_ms)
    {
        return Err("duration must contain a whole number of native buckets".to_string());
    }
    if request.sample_rate_msps != 320 {
        return Err("autocorrelation requires sample_rate_msps=320".to_string());
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
        || value == "."
        || value == ".."
    {
        return Err(format!(
            "{name} must use 1..128 ASCII letters, digits, '.', '-', or '_' without path components"
        ));
    }
    Ok(())
}

fn div_ceil_u64(value: u64, divisor: u64) -> u64 {
    value.div_ceil(divisor)
}

fn unix_time_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis()
        .min(u64::MAX as u128) as u64
}

#[derive(Clone, Debug)]
pub struct AutocorrelationController {
    root: PathBuf,
    active: Arc<AtomicBool>,
    writer_running: Arc<AtomicBool>,
    cancel: Arc<AtomicBool>,
    finish_requested: Arc<AtomicBool>,
    generation: Arc<AtomicU64>,
    origin_set: Arc<AtomicBool>,
    origin_sample0: Arc<AtomicU64>,
    origin_frame_group: Arc<AtomicU64>,
    completed_block_mask: Arc<AtomicU64>,
    queued_messages: Arc<AtomicUsize>,
    queue_high_water: Arc<AtomicUsize>,
    config: Arc<Mutex<Option<Arc<ActiveConfig>>>>,
    identity: Arc<Mutex<Option<CaptureIdentity>>>,
    sender: Arc<Mutex<Option<SyncSender<WriterMessage>>>>,
    control: Arc<Mutex<AutocorrelationControl>>,
    writer_progress: Arc<Mutex<MeasurementWriterProgress>>,
}

impl AutocorrelationController {
    pub fn new(root: PathBuf) -> Self {
        Self {
            root,
            active: Arc::new(AtomicBool::new(false)),
            writer_running: Arc::new(AtomicBool::new(false)),
            cancel: Arc::new(AtomicBool::new(false)),
            finish_requested: Arc::new(AtomicBool::new(false)),
            generation: Arc::new(AtomicU64::new(NO_GENERATION)),
            origin_set: Arc::new(AtomicBool::new(false)),
            origin_sample0: Arc::new(AtomicU64::new(0)),
            origin_frame_group: Arc::new(AtomicU64::new(0)),
            completed_block_mask: Arc::new(AtomicU64::new(0)),
            queued_messages: Arc::new(AtomicUsize::new(0)),
            queue_high_water: Arc::new(AtomicUsize::new(0)),
            config: Arc::new(Mutex::new(None)),
            identity: Arc::new(Mutex::new(None)),
            sender: Arc::new(Mutex::new(None)),
            control: Arc::new(Mutex::new(AutocorrelationControl::default())),
            writer_progress: Arc::new(Mutex::new(MeasurementWriterProgress::default())),
        }
    }

    pub fn begin(&self, request: AutocorrelationRequest) -> Result<AutocorrelationStatus, String> {
        self.begin_with_start_lead(request, AUTOCORRELATION_START_LEAD_BUCKETS, 30)
    }

    pub fn begin_replay_validation(
        &self,
        request: AutocorrelationRequest,
        start_lead_buckets: u64,
    ) -> Result<AutocorrelationStatus, String> {
        if request.metadata.get("validation_mode").map(String::as_str) != Some("packet_replay") {
            return Err(
                "replay validation requires metadata.validation_mode=packet_replay".to_string(),
            );
        }
        self.begin_with_start_lead(request, start_lead_buckets, 3_600)
    }

    fn begin_with_start_lead(
        &self,
        request: AutocorrelationRequest,
        start_lead_buckets: u64,
        watchdog_grace_seconds: u64,
    ) -> Result<AutocorrelationStatus, String> {
        validate_request(&request)?;
        let mut control = self
            .control
            .lock()
            .map_err(|_| "measurement control lock poisoned".to_string())?;
        if self.writer_running.load(Ordering::Acquire)
            || matches!(control.status.as_str(), "armed" | "running" | "draining")
        {
            return Err("a autocorrelation capture is already active".to_string());
        }

        fs::create_dir_all(&self.root)
            .map_err(|error| format!("create measurement root failed: {error}"))?;
        let output_dir = self.root.join(&request.scan_id);
        fs::create_dir(&output_dir).map_err(|error| {
            format!(
                "create new measurement scan directory {} failed: {error}",
                output_dir.display()
            )
        })?;

        let generation = control.generation.wrapping_add(1).max(1);
        let config = Arc::new(ActiveConfig::from_request_with_start_lead(
            generation,
            request.clone(),
            start_lead_buckets,
        )?);
        *self
            .writer_progress
            .lock()
            .map_err(|_| "measurement writer progress lock poisoned".to_string())? =
            MeasurementWriterProgress::default();
        let writer = match AutocorrelationDatasetWriter::new_with_progress(
            &output_dir,
            &config,
            self.writer_progress.clone(),
        ) {
            Ok(writer) => writer,
            Err(error) => {
                control.generation = generation;
                control.status = "failed".to_string();
                control.request = Some(request);
                control.output_dir = Some(output_dir.display().to_string());
                control.armed_unix_ms = Some(unix_time_ms());
                control.finished_unix_ms = Some(unix_time_ms());
                control.error = Some(error.clone());
                return Err(error);
            }
        };
        let (sender, receiver) = mpsc::sync_channel(AUTOCORRELATION_WRITER_QUEUE_CAPACITY);

        self.active.store(false, Ordering::Release);
        self.cancel.store(false, Ordering::Release);
        self.finish_requested.store(false, Ordering::Release);
        self.origin_set.store(false, Ordering::Release);
        self.origin_sample0.store(0, Ordering::Relaxed);
        self.origin_frame_group.store(0, Ordering::Relaxed);
        self.completed_block_mask.store(0, Ordering::Relaxed);
        self.queued_messages.store(0, Ordering::Relaxed);
        self.queue_high_water.store(0, Ordering::Relaxed);
        *self
            .config
            .lock()
            .map_err(|_| "measurement config lock poisoned".to_string())? = Some(config.clone());
        *self
            .identity
            .lock()
            .map_err(|_| "measurement identity lock poisoned".to_string())? = None;
        *self
            .sender
            .lock()
            .map_err(|_| "measurement sender lock poisoned".to_string())? = Some(sender);
        self.generation.store(generation, Ordering::Release);

        *control = AutocorrelationControl {
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
        let writer_progress = self.writer_progress.clone();
        let cancel = self.cancel.clone();
        let finish_requested = self.finish_requested.clone();
        let queued_messages = self.queued_messages.clone();
        let writer_running = self.writer_running.clone();
        self.writer_running.store(true, Ordering::Release);
        if let Err(error) = thread::Builder::new()
            .name("t510-autocorrelation-writer".to_string())
            .spawn(move || {
                run_writer(
                    writer,
                    receiver,
                    generation,
                    cancel,
                    finish_requested,
                    queued_messages,
                    writer_control,
                    writer_progress,
                    writer_running,
                );
            })
        {
            self.writer_running.store(false, Ordering::Release);
            self.fail(
                generation,
                &format!("spawn measurement writer failed: {error}"),
            );
            return Err(format!("spawn measurement writer failed: {error}"));
        }

        self.active.store(true, Ordering::Release);

        let watchdog = self.clone();
        if let Err(error) = thread::Builder::new()
            .name("t510-autocorrelation-watchdog".to_string())
            .spawn(move || {
                thread::sleep(Duration::from_secs(
                    u64::from(request.duration_seconds).saturating_add(watchdog_grace_seconds),
                ));
                if watchdog.generation.load(Ordering::Acquire) == generation
                    && watchdog.active.load(Ordering::Acquire)
                {
                    watchdog.fail(
                        generation,
                        "host watchdog expired before all 16 sample0-defined block ranges completed",
                    );
                }
            })
        {
            self.fail(
                generation,
                &format!("spawn measurement watchdog failed: {error}"),
            );
            return Err(format!("spawn measurement watchdog failed: {error}"));
        }

        Ok(self.status())
    }

    pub fn stop(&self, reason: &str) -> Result<AutocorrelationStatus, String> {
        let generation = self.generation.load(Ordering::Acquire);
        if generation == NO_GENERATION {
            return Err("no measurement capture exists".to_string());
        }
        self.fail(generation, reason);
        Ok(self.status())
    }

    pub fn is_active(&self) -> bool {
        self.active.load(Ordering::Acquire) || self.writer_running.load(Ordering::Acquire)
    }

    pub fn status(&self) -> AutocorrelationStatus {
        let control = self
            .control
            .lock()
            .map(|value| value.clone())
            .unwrap_or_default();
        let writer = self
            .writer_progress
            .lock()
            .map(|value| value.clone())
            .unwrap_or_default();
        let origin_set = self.origin_set.load(Ordering::Acquire);
        AutocorrelationStatus {
            generation: control.generation,
            status: control.status,
            request: control.request,
            output_dir: control.output_dir,
            armed_unix_ms: control.armed_unix_ms,
            started_unix_ms: control.started_unix_ms,
            finished_unix_ms: control.finished_unix_ms,
            origin_sample0: origin_set.then(|| self.origin_sample0.load(Ordering::Relaxed)),
            origin_frame_group: origin_set.then(|| self.origin_frame_group.load(Ordering::Relaxed)),
            completed_block_mask: self.completed_block_mask.load(Ordering::Relaxed) as u16,
            queued_messages: self.queued_messages.load(Ordering::Relaxed),
            queue_high_water: self.queue_high_water.load(Ordering::Relaxed),
            writer,
            error: control.error,
        }
    }

    pub fn ingest(&self, worker: &mut AutocorrelationWorkerState, header: &T510Header, udp_payload: &[u8]) {
        if !self.active.load(Ordering::Acquire) {
            return;
        }
        let generation = self.generation.load(Ordering::Acquire);
        if worker.generation != generation {
            let Some(config) = self.active_config(generation) else {
                self.fail(generation, "active measurement config is missing");
                return;
            };
            let sender = self.sender.lock().ok().and_then(|value| value.clone());
            let Some(sender) = sender else {
                self.fail(generation, "measurement writer sender is missing");
                return;
            };
            worker.reset(generation, HotConfig::from(config.as_ref()), sender);
        }
        let Some(config) = worker.config else {
            self.fail(generation, "worker-local measurement config is missing");
            return;
        };
        if let Err(error) = validate_live_header(header, &config) {
            self.fail(generation, &error);
            return;
        }
        if udp_payload.len() < HEADER_BYTES + CELLS_PER_BLOCK * 4 {
            self.fail(
                generation,
                "validated SPEC payload is truncated in autocorrelation ingest",
            );
            return;
        }

        let frame_group = header.frame_id / u64::from(SPEC_BLOCK_COUNT);
        let mut origin_was_set = false;
        if header.block_index == 0 && !self.origin_set.load(Ordering::Acquire) {
            let Ok(mut identity) = self.identity.lock() else {
                self.fail(generation, "measurement identity lock poisoned");
                return;
            };
            if !self.origin_set.load(Ordering::Acquire) {
                self.origin_sample0.store(header.sample0, Ordering::Relaxed);
                self.origin_frame_group
                    .store(frame_group, Ordering::Relaxed);
                *identity = Some(CaptureIdentity::from_header(header));
                self.origin_set.store(true, Ordering::Release);
                origin_was_set = true;
                if let Ok(mut control) = self.control.lock() {
                    if control.generation == generation && control.status == "armed" {
                        control.status = "running".to_string();
                        control.started_unix_ms = Some(unix_time_ms());
                    }
                }
            }
        }
        if !self.origin_set.load(Ordering::Acquire) {
            return;
        }
        if worker.identity.is_none() {
            worker.identity = self.identity.lock().ok().and_then(|identity| *identity);
        }
        let Some(identity) = worker.identity else {
            self.fail(generation, "measurement capture identity is missing");
            return;
        };
        if let Err(error) = identity.validate(header) {
            self.fail(generation, &error);
            return;
        }
        let origin_sample0 = self.origin_sample0.load(Ordering::Relaxed);
        let origin_group = self.origin_frame_group.load(Ordering::Relaxed);
        if origin_was_set
            && !self.emit(
                worker,
                WriterMessage::Start(CaptureStart {
                    generation,
                    origin_sample0,
                    origin_frame_group: origin_group,
                    start_sample0: origin_sample0
                        .wrapping_add(config.start_bucket * config.bucket_width_ticks),
                    end_sample0: origin_sample0
                        .wrapping_add(config.end_bucket * config.bucket_width_ticks),
                    start_bucket: config.start_bucket,
                    end_bucket: config.end_bucket,
                    bucket_width_ticks: config.bucket_width_ticks,
                    native_bucket_count: config.native_bucket_count,
                    board_id: header.board_id,
                    product_id: header.product_id,
                    pfb_taps: header.pfb_taps,
                    fft_shift: header.fft_shift,
                    spec_status_flags: header.spec_status_flags,
                    spec_sample_rate_hz: header.spec_sample_rate_hz,
                    scale_id: header.scale_id,
                    sync_generation: header.sync_generation,
                    sync_observation_tag: header.sync_observation_tag,
                }),
            )
        {
            return;
        }
        let group_delta = frame_group.wrapping_sub(origin_group);
        if group_delta >= (1u64 << 63) {
            return;
        }
        let expected_sample0 =
            origin_sample0.wrapping_add(group_delta.wrapping_mul(AUTOCORRELATION_FRAME_SAMPLE0_STEP));
        if header.sample0 != expected_sample0 {
            self.fail(
                generation,
                &format!(
                    "SPEC frame/sample0 identity mismatch on block {}: group={} sample0={} expected={}",
                    header.block_index, frame_group, header.sample0, expected_sample0
                ),
            );
            return;
        }

        let block_index = header.block_index;
        let block = worker
            .blocks
            .entry(block_index)
            .or_insert_with(|| BlockRuntime::new(block_index));
        if block.completed {
            return;
        }
        let mut messages = Vec::new();
        match block.ingest(
            header,
            udp_payload,
            &config,
            origin_sample0,
            origin_group,
            &mut messages,
        ) {
            Ok(completed) => {
                for message in messages {
                    if !self.emit(worker, message) {
                        return;
                    }
                }
                if completed {
                    self.mark_block_complete(generation, block_index);
                }
            }
            Err(error) => self.fail(generation, &error),
        }
    }

    fn active_config(&self, generation: u64) -> Option<Arc<ActiveConfig>> {
        self.config.lock().ok().and_then(|config| {
            config
                .as_ref()
                .filter(|config| config.generation == generation)
                .cloned()
        })
    }

    fn emit(&self, worker: &AutocorrelationWorkerState, message: WriterMessage) -> bool {
        self.queued_messages.fetch_add(1, Ordering::Relaxed);
        let queued = self.queued_messages.load(Ordering::Relaxed);
        update_atomic_max(&self.queue_high_water, queued);
        let Some(sender) = worker.sender.as_ref() else {
            self.queued_messages.fetch_sub(1, Ordering::Relaxed);
            self.fail(worker.generation, "measurement writer disconnected");
            return false;
        };
        match sender.try_send(message) {
            Ok(()) => true,
            Err(TrySendError::Full(_)) => {
                self.queued_messages.fetch_sub(1, Ordering::Relaxed);
                self.fail(worker.generation, "measurement writer queue overflow");
                false
            }
            Err(TrySendError::Disconnected(_)) => {
                self.queued_messages.fetch_sub(1, Ordering::Relaxed);
                self.fail(worker.generation, "measurement writer disconnected");
                false
            }
        }
    }

    fn mark_block_complete(&self, generation: u64, block_index: u16) {
        let bit = 1u64 << block_index;
        let mask = self.completed_block_mask.fetch_or(bit, Ordering::AcqRel) | bit;
        let full_mask = (1u64 << SPEC_BLOCK_COUNT) - 1;
        if mask & full_mask == full_mask && self.generation.load(Ordering::Acquire) == generation {
            self.active.store(false, Ordering::Release);
            self.finish_requested.store(true, Ordering::Release);
            if let Ok(mut control) = self.control.lock() {
                if control.generation == generation
                    && matches!(control.status.as_str(), "armed" | "running")
                {
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
                if control.error.is_none() {
                    control.error = Some(reason.to_string());
                }
                control.finished_unix_ms.get_or_insert_with(unix_time_ms);
            }
        }
    }
}

fn update_atomic_max(target: &AtomicUsize, value: usize) {
    let mut previous = target.load(Ordering::Relaxed);
    while value > previous {
        match target.compare_exchange_weak(previous, value, Ordering::Relaxed, Ordering::Relaxed) {
            Ok(_) => break,
            Err(actual) => previous = actual,
        }
    }
}

fn validate_live_header(header: &T510Header, config: &HotConfig) -> Result<(), String> {
    if header.stream_type != STREAM_SPEC
        || header.nchan != SPEC_NCHAN
        || header.block_count != SPEC_BLOCK_COUNT
        || header.block_index >= SPEC_BLOCK_COUNT
        || header.chan0 != u32::from(header.block_index) * u32::from(SPEC_BLOCK_CHANS)
        || header.chan_count != SPEC_BLOCK_CHANS
        || header.time_count != SPEC_TIME_COUNT
        || header.ninput as usize != TIME_NINPUT
        || header.pfb_taps != 8
        || header.spec_sample_rate_hz != AUTOCORRELATION_SAMPLE_RATE_HZ as u32
        || header.spec_status_flags & SPEC_PFB_ACTIVE_FLAG == 0
    {
        return Err(format!(
            "measurement SPEC identity changed: block={}/{} chan0={} count={} nchan={} ninput={} time_count={} taps={} rate_hz={} flags=0x{:08x}",
            header.block_index,
            header.block_count,
            header.chan0,
            header.chan_count,
            header.nchan,
            header.ninput,
            header.time_count,
            header.pfb_taps,
            header.spec_sample_rate_hz,
            header.spec_status_flags
        ));
    }
    if header.frame_id % u64::from(SPEC_BLOCK_COUNT) != u64::from(header.block_index) {
        return Err(format!(
            "frame_id {} is not aligned with block_index {}",
            header.frame_id, header.block_index
        ));
    }
    if header.seq_no % u32::from(SPEC_BLOCK_COUNT) != u32::from(header.block_index) {
        return Err(format!(
            "seq_no {} is not aligned with block_index {}",
            header.seq_no, header.block_index
        ));
    }
    if let Some(expected) = config.expected_fft_shift {
        if header.fft_shift != expected {
            return Err(format!(
                "fft_shift changed from requested {} to {}",
                expected, header.fft_shift
            ));
        }
    }
    Ok(())
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
struct CaptureIdentity {
    board_id: u16,
    product_id: u16,
    pfb_taps: u16,
    fft_shift: u16,
    spec_sample_rate_hz: u32,
    scale_id: u32,
    scale_mode: u16,
    sync_generation: u64,
    sync_observation_tag: u64,
    seq_frame_offset: u32,
}

impl CaptureIdentity {
    fn from_header(header: &T510Header) -> Self {
        Self {
            board_id: header.board_id,
            product_id: header.product_id,
            pfb_taps: header.pfb_taps,
            fft_shift: header.fft_shift,
            spec_sample_rate_hz: header.spec_sample_rate_hz,
            scale_id: header.scale_id,
            scale_mode: header.scale_mode,
            sync_generation: header.sync_generation,
            sync_observation_tag: header.sync_observation_tag,
            seq_frame_offset: header.seq_no.wrapping_sub(header.frame_id as u32),
        }
    }

    fn validate(self, header: &T510Header) -> Result<(), String> {
        let actual = Self::from_header(header);
        if actual == self {
            Ok(())
        } else {
            Err(format!(
                "measurement capture identity changed: expected {self:?}, received {actual:?}"
            ))
        }
    }
}

#[derive(Default)]
pub struct AutocorrelationWorkerState {
    generation: u64,
    config: Option<HotConfig>,
    identity: Option<CaptureIdentity>,
    sender: Option<SyncSender<WriterMessage>>,
    blocks: BTreeMap<u16, BlockRuntime>,
}

impl AutocorrelationWorkerState {
    fn reset(&mut self, generation: u64, config: HotConfig, sender: SyncSender<WriterMessage>) {
        self.generation = generation;
        self.config = Some(config);
        self.identity = None;
        self.sender = Some(sender);
        self.blocks.clear();
    }
}

#[derive(Debug, Clone, Copy, Default, Serialize)]
struct EventCounts {
    duplicate_count: u32,
    reordered_count: u32,
    late_count: u32,
}

#[derive(Debug)]
struct CellAccumulator {
    sum_i: i64,
    sum_q: i64,
    sum_p: u64,
    sum_p2: u128,
    clip_count: u32,
}

impl CellAccumulator {
    fn new() -> Self {
        Self {
            sum_i: 0,
            sum_q: 0,
            sum_p: 0,
            sum_p2: 0,
            clip_count: 0,
        }
    }

    fn mean_power(&self, n: u64) -> f64 {
        if n == 0 {
            0.0
        } else {
            self.sum_p as f64 / n as f64
        }
    }

    fn m2_power(&self, n: u64) -> f64 {
        if n == 0 {
            return 0.0;
        }
        // n * sum(p^2) - sum(p)^2 is the exact integer numerator of M2.
        // Subtracting before conversion to f64 avoids catastrophic
        // cancellation for a large DC level with small variance.
        let n128 = u128::from(n);
        let sum_p = u128::from(self.sum_p);
        let numerator = n128
            .saturating_mul(self.sum_p2)
            .saturating_sub(sum_p.saturating_mul(sum_p));
        numerator as f64 / n as f64
    }
}

#[derive(Debug)]
struct BucketAccumulator {
    n: u64,
    cells: Vec<CellAccumulator>,
    spec_status_flags_or: u32,
    first_sample0: Option<u64>,
    last_sample0: u64,
    first_frame_group: Option<u64>,
    last_frame_group: u64,
}

impl BucketAccumulator {
    fn new() -> Self {
        Self {
            n: 0,
            cells: (0..CELLS_PER_BLOCK)
                .map(|_| CellAccumulator::new())
                .collect(),
            spec_status_flags_or: 0,
            first_sample0: None,
            last_sample0: 0,
            first_frame_group: None,
            last_frame_group: 0,
        }
    }

    fn add(&mut self, header: &T510Header, udp_payload: &[u8]) -> Result<(), String> {
        let next_n = self.n.saturating_add(1);
        if next_n > AUTOCORRELATION_MAX_NATIVE_BUCKET_FRAMES {
            return Err(format!(
                "measurement native bucket exceeded {} frames",
                AUTOCORRELATION_MAX_NATIVE_BUCKET_FRAMES
            ));
        }
        let payload_end = HEADER_BYTES + CELLS_PER_BLOCK * 4;
        let cell_bytes = udp_payload
            .get(HEADER_BYTES..payload_end)
            .ok_or_else(|| "SPEC payload ended inside autocorrelation cell loop".to_string())?;
        for (cell, bytes) in self.cells.iter_mut().zip(cell_bytes.chunks_exact(4)) {
            let i = i16::from_le_bytes([bytes[0], bytes[1]]);
            let q = i16::from_le_bytes([bytes[2], bytes[3]]);
            let i64_value = i64::from(i);
            let q64_value = i64::from(q);
            let power = (i64_value * i64_value + q64_value * q64_value) as u64;
            cell.sum_i += i64_value;
            cell.sum_q += q64_value;
            cell.sum_p += power;
            cell.sum_p2 += u128::from(power) * u128::from(power);
            let clipped = i == i16::MIN
                || q == i16::MIN
                || i.saturating_abs() >= 32760
                || q.saturating_abs() >= 32760;
            if clipped {
                cell.clip_count += 1;
            }
        }
        self.n = next_n;
        self.spec_status_flags_or |= header.spec_status_flags;
        self.first_sample0.get_or_insert(header.sample0);
        self.last_sample0 = header.sample0;
        let frame_group = header.frame_id / u64::from(SPEC_BLOCK_COUNT);
        self.first_frame_group.get_or_insert(frame_group);
        self.last_frame_group = frame_group;
        Ok(())
    }

    #[cfg(test)]
    fn mean_power(&self, index: usize) -> f64 {
        self.cells[index].mean_power(self.n)
    }

    #[cfg(test)]
    fn m2_power(&self, index: usize) -> f64 {
        self.cells[index].m2_power(self.n)
    }
}

#[derive(Debug)]
struct CoarseAccumulator {
    n: u64,
    sum_i: Vec<i64>,
    sum_q: Vec<i64>,
    mean_p: Vec<f64>,
    m2_p: Vec<f64>,
    clip_count: Vec<u32>,
    spec_status_flags_or: u32,
    first_sample0: Option<u64>,
    last_sample0: u64,
}

impl CoarseAccumulator {
    fn new() -> Self {
        Self {
            n: 0,
            sum_i: vec![0; CELLS_PER_BLOCK],
            sum_q: vec![0; CELLS_PER_BLOCK],
            mean_p: vec![0.0; CELLS_PER_BLOCK],
            m2_p: vec![0.0; CELLS_PER_BLOCK],
            clip_count: vec![0; CELLS_PER_BLOCK],
            spec_status_flags_or: 0,
            first_sample0: None,
            last_sample0: 0,
        }
    }

    fn merge(&mut self, bucket: &BucketAccumulator) {
        if bucket.n == 0 {
            return;
        }
        if self.n == 0 {
            self.n = bucket.n;
            for (index, cell) in bucket.cells.iter().enumerate() {
                self.sum_i[index] = cell.sum_i;
                self.sum_q[index] = cell.sum_q;
                self.mean_p[index] = cell.mean_power(bucket.n);
                self.m2_p[index] = cell.m2_power(bucket.n);
                self.clip_count[index] = cell.clip_count;
            }
            self.spec_status_flags_or = bucket.spec_status_flags_or;
            self.first_sample0 = bucket.first_sample0;
            self.last_sample0 = bucket.last_sample0;
            return;
        }
        let n_a = self.n as f64;
        let n_b = bucket.n as f64;
        let n = n_a + n_b;
        for (index, cell) in bucket.cells.iter().enumerate() {
            self.sum_i[index] = self.sum_i[index].saturating_add(cell.sum_i);
            self.sum_q[index] = self.sum_q[index].saturating_add(cell.sum_q);
            let bucket_mean = cell.mean_power(bucket.n);
            let delta = bucket_mean - self.mean_p[index];
            self.mean_p[index] += delta * n_b / n;
            self.m2_p[index] += cell.m2_power(bucket.n) + delta * delta * n_a * n_b / n;
            self.clip_count[index] = self.clip_count[index].saturating_add(cell.clip_count);
        }
        self.n = self.n.saturating_add(bucket.n);
        self.spec_status_flags_or |= bucket.spec_status_flags_or;
        self.last_sample0 = bucket.last_sample0;
    }
}

#[derive(Debug)]
struct PendingFrame {
    header: T510Header,
    payload: Vec<u8>,
}

#[derive(Debug)]
struct BlockRuntime {
    block_index: u16,
    expected_group: Option<u64>,
    recent_accepted: VecDeque<u64>,
    pending: BTreeMap<u64, PendingFrame>,
    current_output_index: Option<u64>,
    current: BucketAccumulator,
    coarse_output_index: Option<u64>,
    coarse: CoarseAccumulator,
    events: BTreeMap<u64, EventCounts>,
    completed: bool,
}

impl BlockRuntime {
    fn new(block_index: u16) -> Self {
        Self {
            block_index,
            expected_group: None,
            recent_accepted: VecDeque::with_capacity(AUTOCORRELATION_REORDER_WINDOW * 2),
            pending: BTreeMap::new(),
            current_output_index: None,
            current: BucketAccumulator::new(),
            coarse_output_index: None,
            coarse: CoarseAccumulator::new(),
            events: BTreeMap::new(),
            completed: false,
        }
    }

    fn ingest(
        &mut self,
        header: &T510Header,
        udp_payload: &[u8],
        config: &HotConfig,
        origin_sample0: u64,
        origin_group: u64,
        messages: &mut Vec<WriterMessage>,
    ) -> Result<bool, String> {
        let Some(absolute_bucket) = config.bucket_for_sample0(origin_sample0, header.sample0)
        else {
            return Ok(false);
        };
        if absolute_bucket < config.start_bucket {
            return Ok(false);
        }
        if absolute_bucket >= config.end_bucket {
            let frame_group = header.frame_id / u64::from(SPEC_BLOCK_COUNT);
            let end_group = origin_group.wrapping_add(div_ceil_u64(
                config.end_bucket * config.bucket_width_ticks,
                AUTOCORRELATION_FRAME_SAMPLE0_STEP,
            ));
            let guard_distance = frame_group.wrapping_sub(end_group);
            if guard_distance < AUTOCORRELATION_REORDER_WINDOW as u64 {
                return Ok(false);
            }
            self.flush_pending(config, origin_sample0, origin_group, messages)?;
            self.finish(config, origin_sample0, origin_group, messages)?;
            self.completed = true;
            return Ok(true);
        }

        let frame_group = header.frame_id / u64::from(SPEC_BLOCK_COUNT);
        if self.expected_group.is_none() {
            let first_formal_group = origin_group.wrapping_add(div_ceil_u64(
                config.start_bucket * config.bucket_width_ticks,
                AUTOCORRELATION_FRAME_SAMPLE0_STEP,
            ));
            self.expected_group = Some(first_formal_group);
        }
        self.ingest_ordered(
            frame_group,
            header,
            udp_payload,
            config,
            origin_sample0,
            messages,
        )?;
        Ok(false)
    }

    fn ingest_ordered(
        &mut self,
        group: u64,
        header: &T510Header,
        udp_payload: &[u8],
        config: &HotConfig,
        origin_sample0: u64,
        messages: &mut Vec<WriterMessage>,
    ) -> Result<(), String> {
        let expected = self
            .expected_group
            .ok_or_else(|| "measurement expected group was not initialized".to_string())?;
        let distance = group.wrapping_sub(expected);
        if distance == 0 {
            self.accept_payload(header, udp_payload, false, config, origin_sample0, messages)?;
            self.expected_group = Some(expected.wrapping_add(1));
            self.drain_pending(config, origin_sample0, messages)?;
            return Ok(());
        }
        if distance >= (1u64 << 63) {
            let duplicate = self.recent_accepted.contains(&group);
            self.record_arrival_event(
                config,
                origin_sample0,
                header,
                if duplicate {
                    ArrivalEventKind::Duplicate
                } else {
                    ArrivalEventKind::Late
                },
                messages,
            );
            return Ok(());
        }
        if self.pending.contains_key(&group) {
            self.record_arrival_event(
                config,
                origin_sample0,
                header,
                ArrivalEventKind::Duplicate,
                messages,
            );
            return Ok(());
        }
        self.pending.insert(
            group,
            PendingFrame {
                header: *header,
                payload: udp_payload.to_vec(),
            },
        );
        let furthest = self
            .pending
            .keys()
            .map(|candidate| candidate.wrapping_sub(expected))
            .max()
            .unwrap_or(0);
        if self.pending.len() > AUTOCORRELATION_REORDER_WINDOW || furthest > AUTOCORRELATION_REORDER_WINDOW as u64 {
            self.force_gap_to_next(config, origin_sample0, messages)?;
        }
        Ok(())
    }

    fn drain_pending(
        &mut self,
        config: &HotConfig,
        origin_sample0: u64,
        messages: &mut Vec<WriterMessage>,
    ) -> Result<(), String> {
        while let Some(expected) = self.expected_group {
            let Some(frame) = self.pending.remove(&expected) else {
                break;
            };
            self.accept_payload(
                &frame.header,
                &frame.payload,
                true,
                config,
                origin_sample0,
                messages,
            )?;
            self.expected_group = Some(expected.wrapping_add(1));
        }
        Ok(())
    }

    fn force_gap_to_next(
        &mut self,
        config: &HotConfig,
        origin_sample0: u64,
        messages: &mut Vec<WriterMessage>,
    ) -> Result<(), String> {
        let expected = self
            .expected_group
            .ok_or_else(|| "missing expected group during reorder flush".to_string())?;
        let Some(next_group) = self
            .pending
            .keys()
            .min_by_key(|candidate| candidate.wrapping_sub(expected))
            .copied()
        else {
            return Ok(());
        };
        let missing = next_group.wrapping_sub(expected);
        if missing > 0 && missing < (1u64 << 63) {
            let next_sample0 = self
                .pending
                .get(&next_group)
                .map(|frame| frame.header.sample0)
                .ok_or_else(|| "pending gap boundary frame is missing".to_string())?;
            messages.push(WriterMessage::Gap(GapRange {
                block_index: self.block_index,
                first_missing_group: expected,
                last_missing_group: next_group.wrapping_sub(1),
                first_missing_sample0: next_sample0
                    .wrapping_sub(missing.wrapping_mul(AUTOCORRELATION_FRAME_SAMPLE0_STEP)),
                last_missing_sample0: next_sample0.wrapping_sub(AUTOCORRELATION_FRAME_SAMPLE0_STEP),
                missing_groups: missing,
            }));
        }
        self.expected_group = Some(next_group);
        self.drain_pending(config, origin_sample0, messages)
    }

    fn flush_pending(
        &mut self,
        config: &HotConfig,
        origin_sample0: u64,
        origin_group: u64,
        messages: &mut Vec<WriterMessage>,
    ) -> Result<(), String> {
        while !self.pending.is_empty() {
            self.force_gap_to_next(config, origin_sample0, messages)?;
        }
        let start_offset = config.start_bucket * config.bucket_width_ticks;
        let end_offset = config.end_bucket * config.bucket_width_ticks;
        let first_formal_group =
            origin_group.wrapping_add(div_ceil_u64(start_offset, AUTOCORRELATION_FRAME_SAMPLE0_STEP));
        let end_group =
            origin_group.wrapping_add(div_ceil_u64(end_offset, AUTOCORRELATION_FRAME_SAMPLE0_STEP));
        let expected = self.expected_group.unwrap_or(first_formal_group);
        let tail_missing = end_group.wrapping_sub(expected);
        if tail_missing > 0 && tail_missing < (1u64 << 63) {
            let first_missing_sample0 = origin_sample0.wrapping_add(
                expected
                    .wrapping_sub(origin_group)
                    .wrapping_mul(AUTOCORRELATION_FRAME_SAMPLE0_STEP),
            );
            messages.push(WriterMessage::Gap(GapRange {
                block_index: self.block_index,
                first_missing_group: expected,
                last_missing_group: end_group.wrapping_sub(1),
                first_missing_sample0,
                last_missing_sample0: first_missing_sample0.wrapping_add(
                    tail_missing
                        .wrapping_sub(1)
                        .wrapping_mul(AUTOCORRELATION_FRAME_SAMPLE0_STEP),
                ),
                missing_groups: tail_missing,
            }));
            self.expected_group = Some(end_group);
        }
        Ok(())
    }

    fn accept_payload(
        &mut self,
        header: &T510Header,
        udp_payload: &[u8],
        reordered: bool,
        config: &HotConfig,
        origin_sample0: u64,
        messages: &mut Vec<WriterMessage>,
    ) -> Result<(), String> {
        let absolute_bucket = config
            .bucket_for_sample0(origin_sample0, header.sample0)
            .ok_or_else(|| "accepted frame precedes autocorrelation origin".to_string())?;
        let Some(output_index) = config.output_index(absolute_bucket) else {
            return Ok(());
        };
        if self.current_output_index != Some(output_index) {
            self.finalize_current(config, messages)?;
            self.current_output_index = Some(output_index);
            self.current = BucketAccumulator::new();
        }
        if reordered {
            let events = self.events.entry(output_index).or_default();
            events.reordered_count = events.reordered_count.saturating_add(1);
        }
        self.current.add(header, udp_payload)?;
        let group = header.frame_id / u64::from(SPEC_BLOCK_COUNT);
        self.recent_accepted.push_back(group);
        while self.recent_accepted.len() > AUTOCORRELATION_REORDER_WINDOW * 2 {
            self.recent_accepted.pop_front();
        }
        Ok(())
    }

    fn record_arrival_event(
        &mut self,
        config: &HotConfig,
        origin_sample0: u64,
        header: &T510Header,
        kind: ArrivalEventKind,
        messages: &mut Vec<WriterMessage>,
    ) {
        let Some(absolute_bucket) = config.bucket_for_sample0(origin_sample0, header.sample0)
        else {
            return;
        };
        let Some(output_index) = config.output_index(absolute_bucket) else {
            return;
        };
        let bucket_is_closed = self
            .current_output_index
            .map(|current| output_index < current)
            .unwrap_or(self.completed);
        if bucket_is_closed {
            messages.push(WriterMessage::ArrivalEvent(ArrivalEventRow {
                bucket_index: output_index,
                block_index: self.block_index,
                frame_group: header.frame_id / u64::from(SPEC_BLOCK_COUNT),
                sample0: header.sample0,
                kind,
            }));
            return;
        }
        let events = self.events.entry(output_index).or_default();
        match kind {
            ArrivalEventKind::Duplicate => {
                events.duplicate_count = events.duplicate_count.saturating_add(1)
            }
            ArrivalEventKind::Late => events.late_count = events.late_count.saturating_add(1),
        }
    }

    fn finalize_current(
        &mut self,
        config: &HotConfig,
        messages: &mut Vec<WriterMessage>,
    ) -> Result<(), String> {
        let Some(output_index) = self.current_output_index.take() else {
            return Ok(());
        };
        if self.current.n == 0 {
            return Ok(());
        }
        let coarse_index = output_index / config.buckets_per_100ms;
        if self.coarse_output_index != Some(coarse_index) {
            self.finalize_coarse(config, messages)?;
            self.coarse_output_index = Some(coarse_index);
            self.coarse = CoarseAccumulator::new();
        }
        self.coarse.merge(&self.current);
        let events = self.events.remove(&output_index).unwrap_or_default();
        let expected_frames = config.expected_native_frames(output_index);
        let n = self.current.n as f64;
        let mean_power = self
            .current
            .cells
            .iter()
            .map(|cell| cell.sum_p as f64 / n)
            .collect();
        messages.push(WriterMessage::Native(NativeBucket {
            block_index: self.block_index,
            output_index,
            first_sample0: self.current.first_sample0.unwrap_or_default(),
            last_sample0: self.current.last_sample0,
            first_frame_group: self.current.first_frame_group.unwrap_or_default(),
            last_frame_group: self.current.last_frame_group,
            expected_frames,
            valid_frames: self.current.n,
            missing_frames: expected_frames.saturating_sub(self.current.n),
            duplicate_count: events.duplicate_count,
            reordered_count: events.reordered_count,
            late_count: events.late_count,
            spec_status_flags_or: self.current.spec_status_flags_or,
            mean_power,
        }));
        self.current = BucketAccumulator::new();
        Ok(())
    }

    fn finalize_coarse(
        &mut self,
        config: &HotConfig,
        messages: &mut Vec<WriterMessage>,
    ) -> Result<(), String> {
        let Some(output_index) = self.coarse_output_index.take() else {
            return Ok(());
        };
        if self.coarse.n == 0 {
            return Ok(());
        }
        let n = self.coarse.n as f64;
        let mut mean_i = Vec::with_capacity(CELLS_PER_BLOCK);
        let mut mean_q = Vec::with_capacity(CELLS_PER_BLOCK);
        for index in 0..CELLS_PER_BLOCK {
            mean_i.push(self.coarse.sum_i[index] as f64 / n);
            mean_q.push(self.coarse.sum_q[index] as f64 / n);
        }
        let expected_frames = config.expected_100ms_frames(output_index);
        messages.push(WriterMessage::Moment100ms(Moment100msBucket {
            block_index: self.block_index,
            output_index,
            first_sample0: self.coarse.first_sample0.unwrap_or_default(),
            last_sample0: self.coarse.last_sample0,
            expected_frames,
            valid_frames: self.coarse.n,
            missing_frames: expected_frames.saturating_sub(self.coarse.n),
            spec_status_flags_or: self.coarse.spec_status_flags_or,
            mean_i,
            mean_q,
            m2_power: self.coarse.m2_p.clone(),
            clip_count: self.coarse.clip_count.clone(),
        }));
        self.coarse = CoarseAccumulator::new();
        Ok(())
    }

    fn finish(
        &mut self,
        config: &HotConfig,
        _origin_sample0: u64,
        _origin_group: u64,
        messages: &mut Vec<WriterMessage>,
    ) -> Result<(), String> {
        self.finalize_current(config, messages)?;
        self.finalize_coarse(config, messages)
    }
}

#[derive(Debug)]
enum WriterMessage {
    Start(CaptureStart),
    Native(NativeBucket),
    Moment100ms(Moment100msBucket),
    Gap(GapRange),
    ArrivalEvent(ArrivalEventRow),
}

#[derive(Debug, Clone, Copy, Serialize)]
struct CaptureStart {
    generation: u64,
    origin_sample0: u64,
    origin_frame_group: u64,
    start_sample0: u64,
    end_sample0: u64,
    start_bucket: u64,
    end_bucket: u64,
    bucket_width_ticks: u64,
    native_bucket_count: u64,
    board_id: u16,
    product_id: u16,
    pfb_taps: u16,
    fft_shift: u16,
    spec_status_flags: u32,
    spec_sample_rate_hz: u32,
    scale_id: u32,
    sync_generation: u64,
    sync_observation_tag: u64,
}

#[derive(Debug)]
struct NativeBucket {
    block_index: u16,
    output_index: u64,
    first_sample0: u64,
    last_sample0: u64,
    first_frame_group: u64,
    last_frame_group: u64,
    expected_frames: u64,
    valid_frames: u64,
    missing_frames: u64,
    duplicate_count: u32,
    reordered_count: u32,
    late_count: u32,
    spec_status_flags_or: u32,
    mean_power: Vec<f64>,
}

#[derive(Debug)]
struct Moment100msBucket {
    block_index: u16,
    output_index: u64,
    first_sample0: u64,
    last_sample0: u64,
    expected_frames: u64,
    valid_frames: u64,
    missing_frames: u64,
    spec_status_flags_or: u32,
    mean_i: Vec<f64>,
    mean_q: Vec<f64>,
    m2_power: Vec<f64>,
    clip_count: Vec<u32>,
}

#[derive(Debug, Serialize)]
struct GapRange {
    block_index: u16,
    first_missing_group: u64,
    last_missing_group: u64,
    first_missing_sample0: u64,
    last_missing_sample0: u64,
    missing_groups: u64,
}

#[derive(Debug, Clone, Copy, Serialize)]
#[serde(rename_all = "snake_case")]
enum ArrivalEventKind {
    Duplicate,
    Late,
}

#[derive(Debug, Serialize)]
struct ArrivalEventRow {
    bucket_index: u64,
    block_index: u16,
    frame_group: u64,
    sample0: u64,
    kind: ArrivalEventKind,
}

#[derive(Debug, Clone, Serialize)]
struct FileRecord {
    path: String,
    bytes: u64,
    sha256: String,
}

#[derive(Debug, Serialize)]
struct DatasetManifest {
    format: &'static str,
    schema_version: u32,
    product: &'static str,
    complete: bool,
    failure_reason: Option<String>,
    request: AutocorrelationRequest,
    native_bucket_count: u64,
    moment_100ms_count: u64,
    files: Vec<FileRecord>,
}

struct TrackedAppendFile {
    relative: String,
    file: File,
    hasher: Sha256,
    bytes: u64,
}

impl TrackedAppendFile {
    fn create(root: &Path, relative: &str) -> Result<Self, String> {
        let path = root.join(relative);
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent)
                .map_err(|error| format!("create {} parent failed: {error}", path.display()))?;
        }
        let file = OpenOptions::new()
            .create_new(true)
            .write(true)
            .open(&path)
            .map_err(|error| format!("create {} failed: {error}", path.display()))?;
        Ok(Self {
            relative: relative.to_string(),
            file,
            hasher: Sha256::new(),
            bytes: 0,
        })
    }

    fn append_line<T: Serialize>(&mut self, value: &T) -> Result<(), String> {
        let mut bytes = serde_json::to_vec(value)
            .map_err(|error| format!("serialize {} row failed: {error}", self.relative))?;
        bytes.push(b'\n');
        self.file
            .write_all(&bytes)
            .map_err(|error| format!("append {} failed: {error}", self.relative))?;
        self.hasher.update(&bytes);
        self.bytes = self.bytes.saturating_add(bytes.len() as u64);
        Ok(())
    }

    fn finish(mut self) -> Result<FileRecord, String> {
        self.file
            .flush()
            .and_then(|_| self.file.sync_all())
            .map_err(|error| format!("sync {} failed: {error}", self.relative))?;
        Ok(FileRecord {
            path: self.relative,
            bytes: self.bytes,
            sha256: format!("{:x}", self.hasher.finalize()),
        })
    }

    fn sync_data(&mut self) -> Result<(), String> {
        self.file
            .sync_data()
            .map_err(|error| format!("sync {} failed: {error}", self.relative))
    }
}

struct Committer {
    root: PathBuf,
    journal: TrackedAppendFile,
    files: Vec<FileRecord>,
    progress: Arc<Mutex<MeasurementWriterProgress>>,
    journal_entries: u64,
}

#[derive(Serialize)]
struct JournalRow<'a> {
    path: &'a str,
    bytes: u64,
    sha256: &'a str,
}

impl Committer {
    fn new(root: PathBuf, progress: Arc<Mutex<MeasurementWriterProgress>>) -> Result<Self, String> {
        let journal = TrackedAppendFile::create(&root, "chunk_journal.jsonl")?;
        Ok(Self {
            root,
            journal,
            files: Vec::new(),
            progress,
            journal_entries: 0,
        })
    }

    fn commit(&mut self, relative: &str, bytes: &[u8]) -> Result<(), String> {
        let path = self.root.join(relative);
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent)
                .map_err(|error| format!("create {} parent failed: {error}", path.display()))?;
        }
        let file_name = path
            .file_name()
            .and_then(|value| value.to_str())
            .ok_or_else(|| format!("invalid output filename {}", path.display()))?;
        let partial = path.with_file_name(format!("{file_name}.partial"));
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
        fs::rename(&partial, &path).map_err(|error| {
            format!(
                "commit {} to {} failed: {error}",
                partial.display(),
                path.display()
            )
        })?;
        let mut hasher = Sha256::new();
        hasher.update(bytes);
        let sha256 = format!("{:x}", hasher.finalize());
        self.journal.append_line(&JournalRow {
            path: relative,
            bytes: bytes.len() as u64,
            sha256: &sha256,
        })?;
        self.journal_entries = self.journal_entries.saturating_add(1);
        if self.journal_entries.is_multiple_of(64) {
            self.journal.sync_data()?;
        }
        self.files.push(FileRecord {
            path: relative.to_string(),
            bytes: bytes.len() as u64,
            sha256,
        });
        if let Ok(mut progress) = self.progress.lock() {
            progress.files_committed = progress.files_committed.saturating_add(1);
            progress.bytes_committed = progress.bytes_committed.saturating_add(bytes.len() as u64);
        }
        Ok(())
    }

    fn finish_journal(mut self) -> Result<(Vec<FileRecord>, FileRecord), String> {
        let journal = self.journal.finish()?;
        self.files.sort_by(|a, b| a.path.cmp(&b.path));
        Ok((self.files, journal))
    }
}

#[derive(Debug)]
struct F64CubeChunk {
    chunk_index: u64,
    values: Vec<f64>,
}

struct F64CubeWriter {
    name: String,
    time_len: u64,
    chunk_time: usize,
    buffers: Vec<Option<F64CubeChunk>>,
}

impl F64CubeWriter {
    fn create(
        name: &str,
        unit: &str,
        time_len: u64,
        preferred_chunk_time: usize,
        committer: &mut Committer,
    ) -> Result<Self, String> {
        let chunk_time = preferred_chunk_time.min(time_len.max(1) as usize).max(1);
        write_zarr_array_metadata(
            name,
            &[time_len, TIME_NINPUT as u64, SPEC_NCHAN as u64],
            &[
                chunk_time as u64,
                TIME_NINPUT as u64,
                SPEC_BLOCK_CHANS as u64,
            ],
            "<f8",
            serde_json::Value::String("NaN".to_string()),
            unit,
            committer,
        )?;
        Ok(Self {
            name: name.to_string(),
            time_len,
            chunk_time,
            buffers: (0..SPEC_BLOCK_COUNT).map(|_| None).collect(),
        })
    }

    fn write_row(
        &mut self,
        block_index: u16,
        output_index: u64,
        source: &[f64],
        committer: &mut Committer,
    ) -> Result<(), String> {
        if block_index >= SPEC_BLOCK_COUNT
            || output_index >= self.time_len
            || source.len() != CELLS_PER_BLOCK
        {
            return Err(format!(
                "invalid {} row block={} time={} cells={}",
                self.name,
                block_index,
                output_index,
                source.len()
            ));
        }
        let chunk_index = output_index / self.chunk_time as u64;
        let block = block_index as usize;
        if self.buffers[block]
            .as_ref()
            .map(|chunk| chunk.chunk_index != chunk_index)
            .unwrap_or(false)
        {
            self.flush_block(block_index, committer)?;
        }
        let chunk = self.buffers[block].get_or_insert_with(|| F64CubeChunk {
            chunk_index,
            values: vec![f64::NAN; self.chunk_time * TIME_NINPUT * SPEC_BLOCK_CHANS as usize],
        });
        let row = (output_index % self.chunk_time as u64) as usize;
        for local_bin in 0..SPEC_BLOCK_CHANS as usize {
            for adc in 0..TIME_NINPUT {
                let src = local_bin * TIME_NINPUT + adc;
                let dst = (row * TIME_NINPUT + adc) * SPEC_BLOCK_CHANS as usize + local_bin;
                chunk.values[dst] = source[src];
            }
        }
        Ok(())
    }

    fn flush_block(&mut self, block_index: u16, committer: &mut Committer) -> Result<(), String> {
        let Some(chunk) = self.buffers[block_index as usize].take() else {
            return Ok(());
        };
        let mut bytes = Vec::with_capacity(chunk.values.len() * 8);
        for value in chunk.values {
            bytes.extend_from_slice(&value.to_le_bytes());
        }
        committer.commit(
            &format!("{}/{}.0.{}", self.name, chunk.chunk_index, block_index),
            &bytes,
        )
    }

    fn flush_all(&mut self, committer: &mut Committer) -> Result<(), String> {
        for block in 0..SPEC_BLOCK_COUNT {
            self.flush_block(block, committer)?;
        }
        Ok(())
    }
}

#[derive(Debug)]
struct U32CubeChunk {
    chunk_index: u64,
    values: Vec<u32>,
}

struct U32CubeWriter {
    name: String,
    time_len: u64,
    chunk_time: usize,
    buffers: Vec<Option<U32CubeChunk>>,
}

impl U32CubeWriter {
    fn create(
        name: &str,
        unit: &str,
        time_len: u64,
        preferred_chunk_time: usize,
        committer: &mut Committer,
    ) -> Result<Self, String> {
        let chunk_time = preferred_chunk_time.min(time_len.max(1) as usize).max(1);
        write_zarr_array_metadata(
            name,
            &[time_len, TIME_NINPUT as u64, SPEC_NCHAN as u64],
            &[
                chunk_time as u64,
                TIME_NINPUT as u64,
                SPEC_BLOCK_CHANS as u64,
            ],
            "<u4",
            serde_json::Value::from(0),
            unit,
            committer,
        )?;
        Ok(Self {
            name: name.to_string(),
            time_len,
            chunk_time,
            buffers: (0..SPEC_BLOCK_COUNT).map(|_| None).collect(),
        })
    }

    fn write_row(
        &mut self,
        block_index: u16,
        output_index: u64,
        source: &[u32],
        committer: &mut Committer,
    ) -> Result<(), String> {
        if block_index >= SPEC_BLOCK_COUNT
            || output_index >= self.time_len
            || source.len() != CELLS_PER_BLOCK
        {
            return Err(format!(
                "invalid {} row block={} time={} cells={}",
                self.name,
                block_index,
                output_index,
                source.len()
            ));
        }
        let chunk_index = output_index / self.chunk_time as u64;
        let block = block_index as usize;
        if self.buffers[block]
            .as_ref()
            .map(|chunk| chunk.chunk_index != chunk_index)
            .unwrap_or(false)
        {
            self.flush_block(block_index, committer)?;
        }
        let chunk = self.buffers[block].get_or_insert_with(|| U32CubeChunk {
            chunk_index,
            values: vec![0; self.chunk_time * TIME_NINPUT * SPEC_BLOCK_CHANS as usize],
        });
        let row = (output_index % self.chunk_time as u64) as usize;
        for local_bin in 0..SPEC_BLOCK_CHANS as usize {
            for adc in 0..TIME_NINPUT {
                let src = local_bin * TIME_NINPUT + adc;
                let dst = (row * TIME_NINPUT + adc) * SPEC_BLOCK_CHANS as usize + local_bin;
                chunk.values[dst] = source[src];
            }
        }
        Ok(())
    }

    fn flush_block(&mut self, block_index: u16, committer: &mut Committer) -> Result<(), String> {
        let Some(chunk) = self.buffers[block_index as usize].take() else {
            return Ok(());
        };
        let mut bytes = Vec::with_capacity(chunk.values.len() * 4);
        for value in chunk.values {
            bytes.extend_from_slice(&value.to_le_bytes());
        }
        committer.commit(
            &format!("{}/{}.0.{}", self.name, chunk.chunk_index, block_index),
            &bytes,
        )
    }

    fn flush_all(&mut self, committer: &mut Committer) -> Result<(), String> {
        for block in 0..SPEC_BLOCK_COUNT {
            self.flush_block(block, committer)?;
        }
        Ok(())
    }
}

#[derive(Debug)]
struct U32ScalarChunk {
    chunk_index: u64,
    values: Vec<u32>,
}

struct U32BlockScalarWriter {
    name: String,
    time_len: u64,
    chunk_time: usize,
    buffers: Vec<Option<U32ScalarChunk>>,
}

impl U32BlockScalarWriter {
    fn create(
        name: &str,
        unit: &str,
        time_len: u64,
        preferred_chunk_time: usize,
        committer: &mut Committer,
    ) -> Result<Self, String> {
        let chunk_time = preferred_chunk_time.min(time_len.max(1) as usize).max(1);
        write_zarr_array_metadata(
            name,
            &[time_len, SPEC_BLOCK_COUNT as u64],
            &[chunk_time as u64, 1],
            "<u4",
            serde_json::Value::from(0),
            unit,
            committer,
        )?;
        Ok(Self {
            name: name.to_string(),
            time_len,
            chunk_time,
            buffers: (0..SPEC_BLOCK_COUNT).map(|_| None).collect(),
        })
    }

    fn write_value(
        &mut self,
        block_index: u16,
        output_index: u64,
        value: u64,
        committer: &mut Committer,
    ) -> Result<(), String> {
        if block_index >= SPEC_BLOCK_COUNT || output_index >= self.time_len {
            return Err(format!(
                "invalid {} scalar block={} time={}",
                self.name, block_index, output_index
            ));
        }
        let value = u32::try_from(value).map_err(|_| {
            format!(
                "{} value {} does not fit uint32 at block={} time={}",
                self.name, value, block_index, output_index
            )
        })?;
        let chunk_index = output_index / self.chunk_time as u64;
        let block = block_index as usize;
        if self.buffers[block]
            .as_ref()
            .map(|chunk| chunk.chunk_index != chunk_index)
            .unwrap_or(false)
        {
            self.flush_block(block_index, committer)?;
        }
        let chunk = self.buffers[block].get_or_insert_with(|| U32ScalarChunk {
            chunk_index,
            values: vec![0; self.chunk_time],
        });
        chunk.values[(output_index % self.chunk_time as u64) as usize] = value;
        Ok(())
    }

    fn flush_block(&mut self, block_index: u16, committer: &mut Committer) -> Result<(), String> {
        let Some(chunk) = self.buffers[block_index as usize].take() else {
            return Ok(());
        };
        let mut bytes = Vec::with_capacity(chunk.values.len() * 4);
        for value in chunk.values {
            bytes.extend_from_slice(&value.to_le_bytes());
        }
        committer.commit(
            &format!("{}/{}.{}", self.name, chunk.chunk_index, block_index),
            &bytes,
        )
    }

    fn flush_all(&mut self, committer: &mut Committer) -> Result<(), String> {
        for block in 0..SPEC_BLOCK_COUNT {
            self.flush_block(block, committer)?;
        }
        Ok(())
    }
}

fn write_zarr_array_metadata(
    name: &str,
    shape: &[u64],
    chunks: &[u64],
    dtype: &str,
    fill_value: serde_json::Value,
    unit: &str,
    committer: &mut Committer,
) -> Result<(), String> {
    let metadata = serde_json::to_vec_pretty(&serde_json::json!({
        "zarr_format": 2,
        "shape": shape,
        "chunks": chunks,
        "dtype": dtype,
        "compressor": null,
        "fill_value": fill_value,
        "order": "C",
        "filters": null,
        "dimension_separator": "."
    }))
    .map_err(|error| format!("serialize {name}/.zarray failed: {error}"))?;
    committer.commit(&format!("{name}/.zarray"), &metadata)?;
    let attrs = serde_json::to_vec_pretty(&serde_json::json!({
        "product": "autocorrelation",
        "unit": unit,
        "axis_order": if shape.len() == 3 {
            vec!["time_bucket", "adc_id", "global_bin"]
        } else {
            vec!["time_bucket", "block_index"]
        },
        "bin_order": "FFT native order",
        "missing_value_policy": "NaN for floating arrays; N_valid=0 for missing exposure"
    }))
    .map_err(|error| format!("serialize {name}/.zattrs failed: {error}"))?;
    committer.commit(&format!("{name}/.zattrs"), &attrs)
}

#[derive(Serialize)]
struct NativeQualityRow {
    bucket_index: u64,
    block_index: u16,
    first_sample0: Option<u64>,
    last_sample0: Option<u64>,
    first_frame_group: Option<u64>,
    last_frame_group: Option<u64>,
    expected_frames: u64,
    valid_frames: u64,
    missing_frames: u64,
    duplicate_count: u32,
    reordered_count: u32,
    late_count: u32,
    spec_status_flags_or: u32,
}

#[derive(Serialize)]
struct MomentQualityRow {
    bucket_100ms_index: u64,
    block_index: u16,
    first_sample0: Option<u64>,
    last_sample0: Option<u64>,
    expected_frames: u64,
    valid_frames: u64,
    missing_frames: u64,
    spec_status_flags_or: u32,
}

struct AutocorrelationDatasetWriter {
    config: Arc<ActiveConfig>,
    committer: Committer,
    native_quality: Option<TrackedAppendFile>,
    moment_quality: Option<TrackedAppendFile>,
    gap_ranges: Option<TrackedAppendFile>,
    arrival_events: Option<TrackedAppendFile>,
    capture_start: Option<CaptureStart>,
    native_seen: Vec<u16>,
    moment_seen: Vec<u16>,
    mean_power: F64CubeWriter,
    n_valid: U32BlockScalarWriter,
    mean_i_100ms: F64CubeWriter,
    mean_q_100ms: F64CubeWriter,
    m2_power_100ms: F64CubeWriter,
    clip_count_100ms: U32CubeWriter,
    n_valid_100ms: U32BlockScalarWriter,
}

impl AutocorrelationDatasetWriter {
    fn new_with_progress(
        output_dir: &Path,
        config: &Arc<ActiveConfig>,
        progress: Arc<Mutex<MeasurementWriterProgress>>,
    ) -> Result<Self, String> {
        let mut committer = Committer::new(output_dir.to_path_buf(), progress)?;
        committer.commit(".zgroup", br#"{"zarr_format":2}"#)?;
        let root_attrs = serde_json::to_vec_pretty(&serde_json::json!({
            "product": "autocorrelation",
            "schema_version": 1,
            "scan_id": config.request.scan_id,
            "tuning_id": config.request.tuning_id,
            "sample_rate_msps": config.request.sample_rate_msps,
            "center_mhz": config.request.center_mhz,
            "native_bucket_ms": config.request.native_bucket_ms,
            "bucket_source": "sample0",
            "sample0_tick_hz": AUTOCORRELATION_SAMPLE_RATE_HZ,
            "frame_sample0_step": AUTOCORRELATION_FRAME_SAMPLE0_STEP,
            "block_count": SPEC_BLOCK_COUNT,
            "block_chans": SPEC_BLOCK_CHANS,
            "adc_count": TIME_NINPUT,
            "metadata": config.request.metadata
        }))
        .map_err(|error| format!("serialize root Zarr attrs failed: {error}"))?;
        committer.commit(".zattrs", &root_attrs)?;
        let request_bytes = serde_json::to_vec_pretty(&config.request)
            .map_err(|error| format!("serialize observation request failed: {error}"))?;
        committer.commit("observation_request.json", &request_bytes)?;

        let native_count = config.native_bucket_count;
        let moment_count = config.moment_100ms_count();
        let native_len = usize::try_from(native_count)
            .map_err(|_| "native bucket count does not fit host usize".to_string())?;
        let moment_len = usize::try_from(moment_count)
            .map_err(|_| "100 ms bucket count does not fit host usize".to_string())?;
        let mean_power = F64CubeWriter::create(
            "mean_power_count2",
            "count^2/PFB_channel",
            native_count,
            100,
            &mut committer,
        )?;
        let n_valid = U32BlockScalarWriter::create(
            "n_valid",
            "spectrum_frames",
            native_count,
            100,
            &mut committer,
        )?;
        let mean_i_100ms = F64CubeWriter::create(
            "mean_i_count_100ms",
            "F-engine_IQ16_count",
            moment_count,
            10,
            &mut committer,
        )?;
        let mean_q_100ms = F64CubeWriter::create(
            "mean_q_count_100ms",
            "F-engine_IQ16_count",
            moment_count,
            10,
            &mut committer,
        )?;
        let m2_power_100ms = F64CubeWriter::create(
            "m2_power_count4_100ms",
            "count^4",
            moment_count,
            10,
            &mut committer,
        )?;
        let clip_count_100ms = U32CubeWriter::create(
            "clip_count_100ms",
            "samples",
            moment_count,
            10,
            &mut committer,
        )?;
        let n_valid_100ms = U32BlockScalarWriter::create(
            "n_valid_100ms",
            "spectrum_frames",
            moment_count,
            10,
            &mut committer,
        )?;

        Ok(Self {
            config: config.clone(),
            committer,
            native_quality: Some(TrackedAppendFile::create(
                output_dir,
                "bucket_quality.jsonl",
            )?),
            moment_quality: Some(TrackedAppendFile::create(
                output_dir,
                "bucket_quality_100ms.jsonl",
            )?),
            gap_ranges: Some(TrackedAppendFile::create(output_dir, "gap_ranges.jsonl")?),
            arrival_events: Some(TrackedAppendFile::create(
                output_dir,
                "arrival_events.jsonl",
            )?),
            capture_start: None,
            native_seen: vec![0; native_len],
            moment_seen: vec![0; moment_len],
            mean_power,
            n_valid,
            mean_i_100ms,
            mean_q_100ms,
            m2_power_100ms,
            clip_count_100ms,
            n_valid_100ms,
        })
    }

    fn replace_progress(&mut self, progress: Arc<Mutex<MeasurementWriterProgress>>) {
        self.committer.progress = progress;
    }

    fn process(&mut self, message: WriterMessage) -> Result<(), String> {
        match message {
            WriterMessage::Start(start) => {
                if self.capture_start.is_some() {
                    return Err("duplicate measurement capture-start record".to_string());
                }
                let bytes = serde_json::to_vec_pretty(&start)
                    .map_err(|error| format!("serialize capture start failed: {error}"))?;
                self.committer.commit("capture_start.json", &bytes)?;
                self.capture_start = Some(start);
            }
            WriterMessage::Native(bucket) => {
                mark_row_seen(
                    &mut self.native_seen,
                    bucket.output_index,
                    bucket.block_index,
                    "native",
                )?;
                self.mean_power.write_row(
                    bucket.block_index,
                    bucket.output_index,
                    &bucket.mean_power,
                    &mut self.committer,
                )?;
                self.n_valid.write_value(
                    bucket.block_index,
                    bucket.output_index,
                    bucket.valid_frames,
                    &mut self.committer,
                )?;
                self.native_quality
                    .as_mut()
                    .ok_or_else(|| "native quality file already closed".to_string())?
                    .append_line(&NativeQualityRow {
                        bucket_index: bucket.output_index,
                        block_index: bucket.block_index,
                        first_sample0: Some(bucket.first_sample0),
                        last_sample0: Some(bucket.last_sample0),
                        first_frame_group: Some(bucket.first_frame_group),
                        last_frame_group: Some(bucket.last_frame_group),
                        expected_frames: bucket.expected_frames,
                        valid_frames: bucket.valid_frames,
                        missing_frames: bucket.missing_frames,
                        duplicate_count: bucket.duplicate_count,
                        reordered_count: bucket.reordered_count,
                        late_count: bucket.late_count,
                        spec_status_flags_or: bucket.spec_status_flags_or,
                    })?;
                if let Ok(mut progress) = self.committer.progress.lock() {
                    progress.native_rows_received = progress.native_rows_received.saturating_add(1);
                }
            }
            WriterMessage::Moment100ms(bucket) => {
                mark_row_seen(
                    &mut self.moment_seen,
                    bucket.output_index,
                    bucket.block_index,
                    "100 ms",
                )?;
                self.mean_i_100ms.write_row(
                    bucket.block_index,
                    bucket.output_index,
                    &bucket.mean_i,
                    &mut self.committer,
                )?;
                self.mean_q_100ms.write_row(
                    bucket.block_index,
                    bucket.output_index,
                    &bucket.mean_q,
                    &mut self.committer,
                )?;
                self.m2_power_100ms.write_row(
                    bucket.block_index,
                    bucket.output_index,
                    &bucket.m2_power,
                    &mut self.committer,
                )?;
                self.clip_count_100ms.write_row(
                    bucket.block_index,
                    bucket.output_index,
                    &bucket.clip_count,
                    &mut self.committer,
                )?;
                self.n_valid_100ms.write_value(
                    bucket.block_index,
                    bucket.output_index,
                    bucket.valid_frames,
                    &mut self.committer,
                )?;
                self.moment_quality
                    .as_mut()
                    .ok_or_else(|| "100 ms quality file already closed".to_string())?
                    .append_line(&MomentQualityRow {
                        bucket_100ms_index: bucket.output_index,
                        block_index: bucket.block_index,
                        first_sample0: Some(bucket.first_sample0),
                        last_sample0: Some(bucket.last_sample0),
                        expected_frames: bucket.expected_frames,
                        valid_frames: bucket.valid_frames,
                        missing_frames: bucket.missing_frames,
                        spec_status_flags_or: bucket.spec_status_flags_or,
                    })?;
                if let Ok(mut progress) = self.committer.progress.lock() {
                    progress.moment_100ms_rows_received =
                        progress.moment_100ms_rows_received.saturating_add(1);
                }
            }
            WriterMessage::Gap(gap) => {
                self.gap_ranges
                    .as_mut()
                    .ok_or_else(|| "gap range file already closed".to_string())?
                    .append_line(&gap)?;
                if let Ok(mut progress) = self.committer.progress.lock() {
                    progress.gap_ranges_received = progress.gap_ranges_received.saturating_add(1);
                }
            }
            WriterMessage::ArrivalEvent(event) => {
                self.arrival_events
                    .as_mut()
                    .ok_or_else(|| "arrival event file already closed".to_string())?
                    .append_line(&event)?;
                if let Ok(mut progress) = self.committer.progress.lock() {
                    progress.arrival_events_received =
                        progress.arrival_events_received.saturating_add(1);
                }
            }
        }
        Ok(())
    }

    fn append_missing_quality_rows(&mut self) -> Result<(), String> {
        let hot = HotConfig::from(self.config.as_ref());
        let native_quality = self
            .native_quality
            .as_mut()
            .ok_or_else(|| "native quality file already closed".to_string())?;
        for (output_index, seen_mask) in self.native_seen.iter().copied().enumerate() {
            let output_index = output_index as u64;
            let expected_frames = hot.expected_native_frames(output_index);
            for block_index in 0..SPEC_BLOCK_COUNT {
                if seen_mask & (1u16 << block_index) != 0 {
                    continue;
                }
                native_quality.append_line(&NativeQualityRow {
                    bucket_index: output_index,
                    block_index,
                    first_sample0: None,
                    last_sample0: None,
                    first_frame_group: None,
                    last_frame_group: None,
                    expected_frames,
                    valid_frames: 0,
                    missing_frames: expected_frames,
                    duplicate_count: 0,
                    reordered_count: 0,
                    late_count: 0,
                    spec_status_flags_or: 0,
                })?;
                if let Ok(mut progress) = self.committer.progress.lock() {
                    progress.native_rows_received = progress.native_rows_received.saturating_add(1);
                }
            }
        }

        let moment_quality = self
            .moment_quality
            .as_mut()
            .ok_or_else(|| "100 ms quality file already closed".to_string())?;
        for (output_index, seen_mask) in self.moment_seen.iter().copied().enumerate() {
            let output_index = output_index as u64;
            let expected_frames = hot.expected_100ms_frames(output_index);
            for block_index in 0..SPEC_BLOCK_COUNT {
                if seen_mask & (1u16 << block_index) != 0 {
                    continue;
                }
                moment_quality.append_line(&MomentQualityRow {
                    bucket_100ms_index: output_index,
                    block_index,
                    first_sample0: None,
                    last_sample0: None,
                    expected_frames,
                    valid_frames: 0,
                    missing_frames: expected_frames,
                    spec_status_flags_or: 0,
                })?;
                if let Ok(mut progress) = self.committer.progress.lock() {
                    progress.moment_100ms_rows_received =
                        progress.moment_100ms_rows_received.saturating_add(1);
                }
            }
        }
        Ok(())
    }

    fn finalize(mut self, complete: bool, failure_reason: Option<String>) -> Result<(), String> {
        if complete && self.capture_start.is_none() {
            return Err("complete measurement capture has no capture-start identity".to_string());
        }
        if complete {
            self.append_missing_quality_rows()?;
        }
        self.mean_power.flush_all(&mut self.committer)?;
        self.n_valid.flush_all(&mut self.committer)?;
        self.mean_i_100ms.flush_all(&mut self.committer)?;
        self.mean_q_100ms.flush_all(&mut self.committer)?;
        self.m2_power_100ms.flush_all(&mut self.committer)?;
        self.clip_count_100ms.flush_all(&mut self.committer)?;
        self.n_valid_100ms.flush_all(&mut self.committer)?;

        for file in [
            self.native_quality.take(),
            self.moment_quality.take(),
            self.gap_ranges.take(),
            self.arrival_events.take(),
        ]
        .into_iter()
        .flatten()
        {
            self.committer.files.push(file.finish()?);
        }
        let root = self.committer.root.clone();
        let (mut files, journal) = self.committer.finish_journal()?;
        files.push(journal);
        files.sort_by(|a, b| a.path.cmp(&b.path));
        let manifest = DatasetManifest {
            format: "T510_AUTOCORRELATION_ZARR_V1",
            schema_version: 1,
            product: "autocorrelation",
            complete,
            failure_reason,
            request: self.config.request.clone(),
            native_bucket_count: self.config.native_bucket_count,
            moment_100ms_count: self.config.moment_100ms_count(),
            files,
        };
        let manifest_bytes = serde_json::to_vec_pretty(&manifest)
            .map_err(|error| format!("serialize autocorrelation manifest failed: {error}"))?;
        write_final_atomic(&root, "dataset_manifest.json", &manifest_bytes)?;
        let mut hasher = Sha256::new();
        hasher.update(&manifest_bytes);
        let digest = format!("{:x}  dataset_manifest.json\n", hasher.finalize());
        write_final_atomic(&root, "dataset_manifest.sha256", digest.as_bytes())
    }
}

fn mark_row_seen(
    seen: &mut [u16],
    output_index: u64,
    block_index: u16,
    label: &str,
) -> Result<(), String> {
    let index = usize::try_from(output_index)
        .map_err(|_| format!("{label} row index does not fit host usize"))?;
    let mask = seen
        .get_mut(index)
        .ok_or_else(|| format!("{label} row index {output_index} is out of range"))?;
    if block_index >= SPEC_BLOCK_COUNT {
        return Err(format!("{label} block index {block_index} is out of range"));
    }
    let bit = 1u16 << block_index;
    if *mask & bit != 0 {
        return Err(format!(
            "duplicate {label} row at bucket={output_index} block={block_index}"
        ));
    }
    *mask |= bit;
    Ok(())
}

fn write_final_atomic(root: &Path, relative: &str, bytes: &[u8]) -> Result<(), String> {
    let path = root.join(relative);
    let partial = root.join(format!("{relative}.partial"));
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
        .map_err(|error| format!("commit {} failed: {error}", path.display()))
}

#[allow(clippy::too_many_arguments)]
fn run_writer(
    mut writer: AutocorrelationDatasetWriter,
    receiver: Receiver<WriterMessage>,
    generation: u64,
    cancel: Arc<AtomicBool>,
    finish_requested: Arc<AtomicBool>,
    queued_messages: Arc<AtomicUsize>,
    control: Arc<Mutex<AutocorrelationControl>>,
    progress: Arc<Mutex<MeasurementWriterProgress>>,
    writer_running: Arc<AtomicBool>,
) {
    writer.replace_progress(progress);
    let mut processing_error = None;
    loop {
        match receiver.recv_timeout(Duration::from_millis(100)) {
            Ok(message) => {
                let result = writer.process(message);
                queued_messages.fetch_sub(1, Ordering::Relaxed);
                if let Err(error) = result {
                    processing_error = Some(error);
                    cancel.store(true, Ordering::Release);
                    break;
                }
            }
            Err(mpsc::RecvTimeoutError::Timeout) => {}
            Err(mpsc::RecvTimeoutError::Disconnected) => {
                processing_error = Some("measurement writer channel disconnected".to_string());
                cancel.store(true, Ordering::Release);
                break;
            }
        }
        if cancel.load(Ordering::Acquire) {
            while let Ok(message) = receiver.try_recv() {
                if processing_error.is_none() {
                    if let Err(error) = writer.process(message) {
                        processing_error = Some(error);
                    }
                }
                queued_messages.fetch_sub(1, Ordering::Relaxed);
            }
            break;
        }
        if finish_requested.load(Ordering::Acquire) && queued_messages.load(Ordering::Acquire) == 0
        {
            break;
        }
    }

    let prior_error = control.lock().ok().and_then(|value| value.error.clone());
    let failure_reason = processing_error.or(prior_error);
    let complete = !cancel.load(Ordering::Acquire) && failure_reason.is_none();
    let finalize_result = writer.finalize(complete, failure_reason.clone());
    if let Ok(mut control) = control.lock() {
        if control.generation == generation {
            control.finished_unix_ms = Some(unix_time_ms());
            match finalize_result {
                Ok(()) if complete => {
                    control.status = "completed".to_string();
                    control.error = None;
                }
                Ok(()) => {
                    control.status = "failed".to_string();
                    control.error = failure_reason.or_else(|| {
                        Some("measurement capture was cancelled before completion".to_string())
                    });
                }
                Err(error) => {
                    control.status = "failed".to_string();
                    control.error = Some(match failure_reason {
                        Some(reason) => format!("{reason}; finalization failed: {error}"),
                        None => format!("autocorrelation finalization failed: {error}"),
                    });
                }
            }
        }
    }
    writer_running.store(false, Ordering::Release);
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Read;

    fn request(scan_id: &str, native_bucket_ms: u32) -> AutocorrelationRequest {
        AutocorrelationRequest {
            scan_id: scan_id.to_string(),
            tuning_id: "tuning-1020mhz".to_string(),
            duration_seconds: 1,
            native_bucket_ms,
            sample_rate_msps: 320,
            center_mhz: 1020.0,
            expected_fft_shift: Some(0),
            metadata: BTreeMap::from([
                ("clock_reference".to_string(), "onboard_tcxo".to_string()),
                ("input_state".to_string(), "8x50ohm".to_string()),
            ]),
        }
    }

    fn header(block: u16, group: u64, sample0: u64) -> T510Header {
        let frame_id = group * u64::from(SPEC_BLOCK_COUNT) + u64::from(block);
        T510Header {
            magic: 0x5435_3130,
            version: 2,
            header_bytes: HEADER_BYTES as u16,
            board_id: 1,
            stream_type: STREAM_SPEC,
            epoch_mode: 1,
            flags: 0,
            unix_sec: 0,
            pps_count: 0,
            sample0,
            frame_id,
            seq_no: frame_id as u32,
            chan0: u32::from(block) * u32::from(SPEC_BLOCK_CHANS),
            chan_count: SPEC_BLOCK_CHANS,
            time_count: SPEC_TIME_COUNT,
            ninput: TIME_NINPUT as u16,
            payload_format: 0,
            scale_id: 0,
            payload_bytes: (CELLS_PER_BLOCK * 4) as u32,
            product_id: 0xf101,
            nchan: SPEC_NCHAN,
            block_index: block,
            block_count: SPEC_BLOCK_COUNT,
            pfb_taps: 8,
            fft_shift: 0,
            spec_status_flags: SPEC_PFB_ACTIVE_FLAG,
            spec_sample_rate_hz: AUTOCORRELATION_SAMPLE_RATE_HZ as u32,
            scale_mode: 0,
            spec_half_band: block >= SPEC_BLOCK_COUNT / 2,
            header_crc: 0,
            sync_generation: 0,
            sync_observation_tag: 0,
            sync_metadata: 0,
            sync_status: 0,
        }
    }

    fn payload(i: i16, q: i16) -> Vec<u8> {
        let mut payload = vec![0u8; HEADER_BYTES + CELLS_PER_BLOCK * 4];
        for index in 0..CELLS_PER_BLOCK {
            let offset = HEADER_BYTES + index * 4;
            payload[offset..offset + 2].copy_from_slice(&i.to_le_bytes());
            payload[offset + 2..offset + 4].copy_from_slice(&q.to_le_bytes());
        }
        payload
    }

    fn unique_temp_root(name: &str) -> PathBuf {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_nanos();
        std::env::temp_dir().join(format!(
            "t510-autocorrelation-{name}-{}-{nonce}",
            std::process::id()
        ))
    }

    #[test]
    fn request_rejects_path_components_and_non_320msps() {
        let mut bad_path = request("../escape", 10);
        assert!(validate_request(&bad_path).is_err());
        bad_path.scan_id = "valid-scan".to_string();
        bad_path.sample_rate_msps = 160;
        assert!(validate_request(&bad_path).is_err());
        bad_path.sample_rate_msps = 320;
        bad_path.native_bucket_ms = 30;
        assert!(validate_request(&bad_path).is_err());
    }

    #[test]
    fn sample0_bucket_math_preserves_781_782_pattern_and_wrap() {
        assert_eq!(AUTOCORRELATION_MAX_NATIVE_BUCKET_FRAMES, 7_813);
        let active = ActiveConfig::from_request(1, request("bucket-math", 10)).unwrap();
        let hot = HotConfig::from(&active);
        let counts: Vec<u64> = (0..4)
            .map(|index| hot.expected_native_frames(index))
            .collect();
        assert_eq!(counts.iter().sum::<u64>(), 3125);
        assert_eq!(counts.iter().filter(|count| **count == 782).count(), 1);
        assert_eq!(counts.iter().filter(|count| **count == 781).count(), 3);

        let origin = u64::MAX - 1000;
        let sample0 = origin.wrapping_add(hot.bucket_width_ticks * hot.start_bucket);
        assert_eq!(
            hot.bucket_for_sample0(origin, sample0),
            Some(hot.start_bucket)
        );
        assert_eq!(hot.output_index(hot.start_bucket), Some(0));
    }

    #[test]
    fn native_bucket_frame_bound_fails_before_touching_cell_storage() {
        let mut accumulator = BucketAccumulator::new();
        accumulator.n = AUTOCORRELATION_MAX_NATIVE_BUCKET_FRAMES;
        let error = accumulator
            .add(&header(0, 0, 0), &payload(1, 2))
            .unwrap_err();
        assert!(error.contains("exceeded 7813 frames"));
    }

    #[test]
    fn all_registered_bucket_widths_cover_one_second_and_form_100ms_rows() {
        for bucket_ms in [10, 20, 50, 100] {
            let active =
                ActiveConfig::from_request(1, request(&format!("bucket-{bucket_ms}"), bucket_ms))
                    .unwrap();
            let hot = HotConfig::from(&active);
            assert_eq!(active.native_bucket_count, u64::from(1000 / bucket_ms));
            assert_eq!(active.moment_100ms_count(), 10);
            assert_eq!(
                (0..active.native_bucket_count)
                    .map(|index| hot.expected_native_frames(index))
                    .sum::<u64>(),
                78_125
            );
            for start_lead in 1..=13 {
                let offset = ActiveConfig::from_request_with_start_lead(
                    1,
                    request(&format!("bucket-{bucket_ms}-lead-{start_lead}"), bucket_ms),
                    start_lead,
                )
                .unwrap();
                let offset_hot = HotConfig::from(&offset);
                assert_eq!(
                    (0..offset.native_bucket_count)
                        .map(|index| offset_hot.expected_native_frames(index))
                        .sum::<u64>(),
                    78_125
                );
            }
        }
    }

    #[test]
    fn welford_and_chan_moments_handle_constants_extremes_and_merge() {
        let first_header = header(0, 0, 0);
        let mut constant = BucketAccumulator::new();
        let constant_payload = payload(3, 4);
        constant.add(&first_header, &constant_payload).unwrap();
        constant
            .add(&header(0, 1, AUTOCORRELATION_FRAME_SAMPLE0_STEP), &constant_payload)
            .unwrap();
        assert_eq!(constant.n, 2);
        assert_eq!(constant.cells[0].sum_i, 6);
        assert_eq!(constant.cells[0].sum_q, 8);
        assert_eq!(constant.mean_power(0), 25.0);
        assert_eq!(constant.m2_power(0), 0.0);

        let mut second = BucketAccumulator::new();
        second.add(&first_header, &payload(6, 8)).unwrap();
        let mut merged = CoarseAccumulator::new();
        merged.merge(&constant);
        merged.merge(&second);
        assert_eq!(merged.n, 3);
        assert!((merged.mean_p[0] - 50.0).abs() < 1.0e-12);
        assert!((merged.m2_p[0] - 3750.0).abs() < 1.0e-9);

        let mut extreme = BucketAccumulator::new();
        extreme
            .add(&first_header, &payload(i16::MIN, i16::MIN))
            .unwrap();
        extreme
            .add(
                &header(0, 1, AUTOCORRELATION_FRAME_SAMPLE0_STEP),
                &payload(i16::MAX, i16::MAX),
            )
            .unwrap();
        assert!(extreme.mean_power(0).is_finite());
        assert!(extreme.m2_power(0).is_finite());
        assert!(extreme.m2_power(0) >= 0.0);
        assert_eq!(extreme.cells[0].clip_count, 2);
    }

    #[test]
    fn online_moments_match_two_pass_noise_and_large_dc_small_variance() {
        fn check_sequence(samples: &[(i16, i16)]) {
            let mut accumulator = BucketAccumulator::new();
            let mut powers = Vec::with_capacity(samples.len());
            for (group, (i, q)) in samples.iter().copied().enumerate() {
                accumulator
                    .add(
                        &header(0, group as u64, group as u64 * AUTOCORRELATION_FRAME_SAMPLE0_STEP),
                        &payload(i, q),
                    )
                    .unwrap();
                let i = f64::from(i);
                let q = f64::from(q);
                powers.push(i * i + q * q);
            }
            let mean = powers.iter().sum::<f64>() / powers.len() as f64;
            let m2 = powers
                .iter()
                .map(|power| {
                    let delta = power - mean;
                    delta * delta
                })
                .sum::<f64>();
            assert!((accumulator.mean_power(0) - mean).abs() <= mean.abs().max(1.0) * 1.0e-12);
            assert!((accumulator.m2_power(0) - m2).abs() <= m2.abs().max(1.0) * 1.0e-10);
        }

        let mut state = 0x1234_5678u32;
        let noise: Vec<(i16, i16)> = (0..257)
            .map(|_| {
                state = state.wrapping_mul(1_664_525).wrapping_add(1_013_904_223);
                let i = ((state >> 8) as i16) >> 4;
                state = state.wrapping_mul(1_664_525).wrapping_add(1_013_904_223);
                let q = ((state >> 8) as i16) >> 4;
                (i, q)
            })
            .collect();
        check_sequence(&noise);

        let large_dc: Vec<(i16, i16)> = (0..257)
            .map(|index| (30_000 + (index % 3) as i16, -20_000 + (index % 2) as i16))
            .collect();
        check_sequence(&large_dc);
    }

    #[test]
    fn synthetic_white_pink_drift_pulse_tone_and_pfb_overlap_match_integer_oracles() {
        fn validate_case(name: &str, samples: &[(i16, i16)]) {
            let mut whole = BucketAccumulator::new();
            let mut pieces = Vec::new();
            let mut piece = BucketAccumulator::new();
            let mut sum_i = 0i64;
            let mut sum_q = 0i64;
            let mut powers = Vec::with_capacity(samples.len());
            let mut clips = 0u32;
            for (index, (i, q)) in samples.iter().copied().enumerate() {
                let sample_header =
                    header(0, index as u64, index as u64 * AUTOCORRELATION_FRAME_SAMPLE0_STEP);
                let data = payload(i, q);
                whole.add(&sample_header, &data).unwrap();
                piece.add(&sample_header, &data).unwrap();
                sum_i += i64::from(i);
                sum_q += i64::from(q);
                let power = i64::from(i) * i64::from(i) + i64::from(q) * i64::from(q);
                powers.push(power as f64);
                if i == i16::MIN
                    || q == i16::MIN
                    || i.saturating_abs() >= 32760
                    || q.saturating_abs() >= 32760
                {
                    clips += 1;
                }
                if matches!(index, 72 | 199 | 310 | 443) {
                    pieces.push(std::mem::replace(&mut piece, BucketAccumulator::new()));
                }
            }
            pieces.push(piece);
            let mean = powers.iter().sum::<f64>() / powers.len() as f64;
            let m2 = powers
                .iter()
                .map(|power| {
                    let delta = power - mean;
                    delta * delta
                })
                .sum::<f64>();
            assert_eq!(whole.n as usize, samples.len(), "{name}");
            assert_eq!(whole.cells[0].sum_i, sum_i, "{name}");
            assert_eq!(whole.cells[0].sum_q, sum_q, "{name}");
            assert_eq!(whole.cells[0].clip_count, clips, "{name}");
            assert!(
                (whole.mean_power(0) - mean).abs() <= mean.abs().max(1.0) * 2.0e-13,
                "{name}"
            );
            assert!(
                (whole.m2_power(0) - m2).abs() <= m2.abs().max(1.0) * 2.0e-12,
                "{name}"
            );

            let mut merged = CoarseAccumulator::new();
            for value in &pieces {
                merged.merge(value);
            }
            assert_eq!(merged.n, whole.n, "{name}");
            assert_eq!(merged.sum_i[0], whole.cells[0].sum_i, "{name}");
            assert_eq!(merged.sum_q[0], whole.cells[0].sum_q, "{name}");
            assert_eq!(merged.clip_count[0], whole.cells[0].clip_count, "{name}");
            assert!(
                (merged.mean_p[0] - whole.mean_power(0)).abs() <= mean.abs().max(1.0) * 2.0e-13,
                "{name}"
            );
            assert!(
                (merged.m2_p[0] - whole.m2_power(0)).abs() <= m2.abs().max(1.0) * 2.0e-12,
                "{name}"
            );
        }

        let mut state = 0x9e37_79b9u32;
        let white: Vec<(i16, i16)> = (0..512)
            .map(|_| {
                state = state.wrapping_mul(1_664_525).wrapping_add(1_013_904_223);
                let i = ((state >> 8) as i16) >> 3;
                state = state.wrapping_mul(1_664_525).wrapping_add(1_013_904_223);
                let q = ((state >> 8) as i16) >> 3;
                (i, q)
            })
            .collect();
        validate_case("deterministic-white", &white);

        let pink: Vec<(i16, i16)> = (0..512)
            .map(|index| {
                let phase = index as f64;
                let value = 1800.0 * (std::f64::consts::TAU * phase / 512.0).sin()
                    + 1200.0 * (std::f64::consts::TAU * phase / 256.0).sin()
                    + 800.0 * (std::f64::consts::TAU * phase / 128.0).sin()
                    + 500.0 * (std::f64::consts::TAU * phase / 64.0).sin();
                (value.round() as i16, (value * 0.37).round() as i16)
            })
            .collect();
        validate_case("one-over-f-like", &pink);

        let drift: Vec<(i16, i16)> = white
            .iter()
            .enumerate()
            .map(|(index, (i, q))| {
                let gain = 0.75 + 0.5 * index as f64 / 511.0;
                (
                    (f64::from(*i) * gain).round() as i16,
                    (f64::from(*q) * gain).round() as i16,
                )
            })
            .collect();
        validate_case("slow-gain-drift", &drift);

        let pulse: Vec<(i16, i16)> = (0..512)
            .map(|index| {
                if matches!(index, 0 | 72 | 199 | 310 | 443 | 511) {
                    (30_000, -29_000)
                } else {
                    (0, 0)
                }
            })
            .collect();
        validate_case("boundary-pulses", &pulse);

        let tone: Vec<(i16, i16)> = (0..512)
            .map(|index| {
                let phase = std::f64::consts::TAU * index as f64 / 17.0;
                (
                    (12_000.0 * phase.cos()).round() as i16,
                    (12_000.0 * phase.sin()).round() as i16,
                )
            })
            .collect();
        validate_case("coherent-complex-tone", &tone);

        let raw: Vec<i32> = white.iter().map(|(i, _)| i32::from(*i)).collect();
        let weights = [1i32, 2, 3, 4, 4, 3, 2, 1];
        let pfb_overlap: Vec<(i16, i16)> = (0..512)
            .map(|index| {
                let i = weights
                    .iter()
                    .enumerate()
                    .map(|(tap, weight)| weight * raw[(index + tap) % raw.len()])
                    .sum::<i32>()
                    / 20;
                let q = weights
                    .iter()
                    .enumerate()
                    .map(|(tap, weight)| weight * raw[(index + tap + 137) % raw.len()])
                    .sum::<i32>()
                    / 20;
                (i as i16, q as i16)
            })
            .collect();
        validate_case("equivalent-eight-tap-overlap", &pfb_overlap);
        let mean = pfb_overlap.iter().map(|(i, _)| f64::from(*i)).sum::<f64>() / 512.0;
        let covariance = pfb_overlap
            .windows(2)
            .map(|pair| (f64::from(pair[0].0) - mean) * (f64::from(pair[1].0) - mean))
            .sum::<f64>();
        let variance = pfb_overlap
            .iter()
            .map(|(i, _)| (f64::from(*i) - mean).powi(2))
            .sum::<f64>();
        assert!(covariance / variance > 0.5);
    }

    #[test]
    fn bounded_reorder_counts_duplicate_reordered_and_gap_without_zero_fill() {
        let active = ActiveConfig::from_request(1, request("reorder", 100)).unwrap();
        let hot = HotConfig::from(&active);
        let origin_sample0 = 0;
        let origin_group = 0;
        let start_group = div_ceil_u64(
            hot.start_bucket * hot.bucket_width_ticks,
            AUTOCORRELATION_FRAME_SAMPLE0_STEP,
        );
        let data = payload(1, 2);
        let mut block = BlockRuntime::new(0);
        let mut messages = Vec::new();

        let h0 = header(0, start_group, start_group * AUTOCORRELATION_FRAME_SAMPLE0_STEP);
        block
            .ingest(
                &h0,
                &data,
                &hot,
                origin_sample0,
                origin_group,
                &mut messages,
            )
            .unwrap();
        let h2 = header(
            0,
            start_group + 2,
            (start_group + 2) * AUTOCORRELATION_FRAME_SAMPLE0_STEP,
        );
        block
            .ingest(
                &h2,
                &data,
                &hot,
                origin_sample0,
                origin_group,
                &mut messages,
            )
            .unwrap();
        let h1 = header(
            0,
            start_group + 1,
            (start_group + 1) * AUTOCORRELATION_FRAME_SAMPLE0_STEP,
        );
        block
            .ingest(
                &h1,
                &data,
                &hot,
                origin_sample0,
                origin_group,
                &mut messages,
            )
            .unwrap();
        block
            .ingest(
                &h1,
                &data,
                &hot,
                origin_sample0,
                origin_group,
                &mut messages,
            )
            .unwrap();

        let end_offset = hot.end_bucket * hot.bucket_width_ticks;
        let end_group = div_ceil_u64(end_offset, AUTOCORRELATION_FRAME_SAMPLE0_STEP);
        let completion_group = end_group + AUTOCORRELATION_REORDER_WINDOW as u64;
        let end = header(
            0,
            completion_group,
            completion_group * AUTOCORRELATION_FRAME_SAMPLE0_STEP,
        );
        assert!(block
            .ingest(
                &end,
                &data,
                &hot,
                origin_sample0,
                origin_group,
                &mut messages,
            )
            .unwrap());
        let native = messages.iter().find_map(|message| match message {
            WriterMessage::Native(bucket) => Some(bucket),
            _ => None,
        });
        let native = native.expect("native bucket");
        assert_eq!(native.valid_frames, 3);
        assert_eq!(native.reordered_count, 1);
        assert_eq!(native.duplicate_count, 1);
        assert_eq!(native.mean_power[0], 5.0);
        assert!(native.missing_frames > 0);
        assert!(messages
            .iter()
            .any(|message| matches!(message, WriterMessage::Gap(_))));
    }

    #[test]
    fn arrival_after_bucket_commit_is_preserved_in_append_only_event_ledger() {
        let active = ActiveConfig::from_request(1, request("late-event", 100)).unwrap();
        let hot = HotConfig::from(&active);
        let start_group = div_ceil_u64(
            hot.start_bucket * hot.bucket_width_ticks,
            AUTOCORRELATION_FRAME_SAMPLE0_STEP,
        );
        let next_bucket_group = div_ceil_u64(
            (hot.start_bucket + 1) * hot.bucket_width_ticks,
            AUTOCORRELATION_FRAME_SAMPLE0_STEP,
        );
        let data = payload(1, 2);
        let mut block = BlockRuntime::new(0);
        let mut messages = Vec::new();
        let first = header(0, start_group, start_group * AUTOCORRELATION_FRAME_SAMPLE0_STEP);
        block
            .ingest(&first, &data, &hot, 0, 0, &mut messages)
            .unwrap();
        let second = header(
            0,
            next_bucket_group,
            next_bucket_group * AUTOCORRELATION_FRAME_SAMPLE0_STEP,
        );
        block
            .ingest(&second, &data, &hot, 0, 0, &mut messages)
            .unwrap();
        block
            .ingest(&first, &data, &hot, 0, 0, &mut messages)
            .unwrap();
        assert!(messages.iter().any(|message| matches!(
            message,
            WriterMessage::ArrivalEvent(ArrivalEventRow {
                bucket_index: 0,
                kind: ArrivalEventKind::Duplicate,
                ..
            })
        )));
    }

    #[test]
    fn end_boundary_waits_for_tail_reorder_guard_before_sealing() {
        let active = ActiveConfig::from_request(1, request("tail-guard", 100)).unwrap();
        let hot = HotConfig::from(&active);
        let end_group = div_ceil_u64(
            hot.end_bucket * hot.bucket_width_ticks,
            AUTOCORRELATION_FRAME_SAMPLE0_STEP,
        );
        let data = payload(1, 2);
        let mut block = BlockRuntime::new(0);
        block.expected_group = Some(end_group - 2);
        let mut messages = Vec::new();
        for group in [end_group - 2, end_group] {
            let completed = block
                .ingest(
                    &header(0, group, group * AUTOCORRELATION_FRAME_SAMPLE0_STEP),
                    &data,
                    &hot,
                    0,
                    0,
                    &mut messages,
                )
                .unwrap();
            assert!(!completed);
        }
        assert!(!block
            .ingest(
                &header(
                    0,
                    end_group - 1,
                    (end_group - 1) * AUTOCORRELATION_FRAME_SAMPLE0_STEP,
                ),
                &data,
                &hot,
                0,
                0,
                &mut messages,
            )
            .unwrap());
        let completion_group = end_group + AUTOCORRELATION_REORDER_WINDOW as u64;
        assert!(block
            .ingest(
                &header(
                    0,
                    completion_group,
                    completion_group * AUTOCORRELATION_FRAME_SAMPLE0_STEP,
                ),
                &data,
                &hot,
                0,
                0,
                &mut messages,
            )
            .unwrap());
        let tail = messages.iter().find_map(|message| match message {
            WriterMessage::Native(bucket) if bucket.output_index == 9 => Some(bucket),
            _ => None,
        });
        assert_eq!(tail.expect("tail bucket").valid_frames, 2);
    }

    #[test]
    fn controller_writes_standard_zarr_chunks_quality_and_complete_manifest() {
        let root = unique_temp_root("writer");
        let controller = AutocorrelationController::new(root.clone());
        let capture_request = request("scan-001", 100);
        let status = controller.begin(capture_request.clone()).unwrap();
        assert_eq!(status.status, "armed");

        let origin_sample0 = 10_000u64;
        let origin_group = 100u64;
        let data_by_block: Vec<Vec<u8>> = (0..SPEC_BLOCK_COUNT)
            .map(|block| payload(block as i16 + 1, 2))
            .collect();
        let mut worker = AutocorrelationWorkerState::default();
        controller.ingest(
            &mut worker,
            &header(0, origin_group, origin_sample0),
            &data_by_block[0],
        );

        let width = AUTOCORRELATION_SAMPLE_RATE_HZ / 10;
        for output_index in 0..10u64 {
            let offset = (AUTOCORRELATION_START_LEAD_BUCKETS + output_index) * width;
            let group_delta = div_ceil_u64(offset, AUTOCORRELATION_FRAME_SAMPLE0_STEP);
            let sample0 = origin_sample0.wrapping_add(group_delta * AUTOCORRELATION_FRAME_SAMPLE0_STEP);
            for block in 0..SPEC_BLOCK_COUNT {
                if output_index == 5 && block == 0 {
                    continue;
                }
                controller.ingest(
                    &mut worker,
                    &header(block, origin_group + group_delta, sample0),
                    &data_by_block[block as usize],
                );
            }
        }
        let end_offset = (AUTOCORRELATION_START_LEAD_BUCKETS + 10) * width;
        let end_delta = div_ceil_u64(end_offset, AUTOCORRELATION_FRAME_SAMPLE0_STEP);
        let completion_delta = end_delta + AUTOCORRELATION_REORDER_WINDOW as u64;
        let end_sample0 =
            origin_sample0.wrapping_add(completion_delta * AUTOCORRELATION_FRAME_SAMPLE0_STEP);
        for block in 0..SPEC_BLOCK_COUNT {
            controller.ingest(
                &mut worker,
                &header(block, origin_group + completion_delta, end_sample0),
                &data_by_block[block as usize],
            );
        }

        let deadline = std::time::Instant::now() + Duration::from_secs(10);
        loop {
            let status = controller.status();
            if status.status == "completed" {
                assert_eq!(status.completed_block_mask, 0xffff);
                assert_eq!(status.writer.native_rows_received, 160);
                assert_eq!(status.writer.moment_100ms_rows_received, 160);
                break;
            }
            assert_ne!(status.status, "failed", "{:?}", status.error);
            assert!(std::time::Instant::now() < deadline, "writer timeout");
            thread::sleep(Duration::from_millis(10));
        }

        let scan = root.join("scan-001");
        let capture_start: serde_json::Value =
            serde_json::from_slice(&fs::read(scan.join("capture_start.json")).unwrap()).unwrap();
        assert_eq!(capture_start["origin_sample0"], origin_sample0);
        assert_eq!(capture_start["origin_frame_group"], origin_group);
        let metadata: serde_json::Value =
            serde_json::from_slice(&fs::read(scan.join("mean_power_count2/.zarray")).unwrap())
                .unwrap();
        assert_eq!(metadata["zarr_format"], 2);
        assert_eq!(metadata["shape"], serde_json::json!([10, 8, 4096]));
        assert_eq!(metadata["chunks"], serde_json::json!([10, 8, 256]));

        let chunk = fs::read(scan.join("mean_power_count2/0.0.0")).unwrap();
        assert_eq!(chunk.len(), 10 * 8 * 256 * 8);
        let first_power = f64::from_le_bytes(chunk[0..8].try_into().unwrap());
        assert_eq!(first_power, 5.0);
        let missing_row_offset = 5 * TIME_NINPUT * SPEC_BLOCK_CHANS as usize * 8;
        let missing_power = f64::from_le_bytes(
            chunk[missing_row_offset..missing_row_offset + 8]
                .try_into()
                .unwrap(),
        );
        assert!(missing_power.is_nan());
        let n_valid = fs::read(scan.join("n_valid/0.0")).unwrap();
        assert_eq!(u32::from_le_bytes(n_valid[0..4].try_into().unwrap()), 1);
        assert_eq!(
            u32::from_le_bytes(n_valid[5 * 4..6 * 4].try_into().unwrap()),
            0
        );

        let manifest_bytes = fs::read(scan.join("dataset_manifest.json")).unwrap();
        let manifest: serde_json::Value = serde_json::from_slice(&manifest_bytes).unwrap();
        assert_eq!(manifest["format"], "T510_AUTOCORRELATION_ZARR_V1");
        assert_eq!(manifest["complete"], true);
        assert!(manifest["files"].as_array().unwrap().len() > 20);
        let mut quality = String::new();
        File::open(scan.join("bucket_quality.jsonl"))
            .unwrap()
            .read_to_string(&mut quality)
            .unwrap();
        assert_eq!(quality.lines().count(), 160);
        let first_quality: serde_json::Value =
            serde_json::from_str(quality.lines().next().unwrap()).unwrap();
        assert_eq!(first_quality["spec_status_flags_or"], SPEC_PFB_ACTIVE_FLAG);

        if std::env::var_os("T510_AUTOCORRELATION_KEEP_FIXTURE").is_some() {
            println!("AUTOCORRELATION_FIXTURE={}", scan.display());
        } else {
            fs::remove_dir_all(&root).unwrap();
        }
    }

    #[test]
    fn live_capture_identity_change_fails_the_segment() {
        let root = unique_temp_root("identity");
        let controller = AutocorrelationController::new(root.clone());
        controller.begin(request("scan-identity", 100)).unwrap();
        let mut worker = AutocorrelationWorkerState::default();
        let data = payload(1, 2);
        controller.ingest(&mut worker, &header(0, 0, 0), &data);
        let mut changed = header(1, 1, AUTOCORRELATION_FRAME_SAMPLE0_STEP);
        changed.scale_id = 9;
        controller.ingest(&mut worker, &changed, &data);
        assert_eq!(controller.status().status, "failed");
        assert!(controller
            .status()
            .error
            .as_deref()
            .unwrap_or_default()
            .contains("capture identity changed"));

        let deadline = std::time::Instant::now() + Duration::from_secs(10);
        while controller.is_active() {
            assert!(std::time::Instant::now() < deadline, "finalizer timeout");
            thread::sleep(Duration::from_millis(10));
        }
        fs::remove_dir_all(&root).unwrap();
    }

    #[test]
    fn explicit_stop_seals_an_incomplete_dataset_without_reusing_scan_identity() {
        let root = unique_temp_root("abort");
        let controller = AutocorrelationController::new(root.clone());
        controller.begin(request("scan-abort", 100)).unwrap();
        controller
            .stop("intentional unit-test interruption")
            .unwrap();

        let deadline = std::time::Instant::now() + Duration::from_secs(10);
        while controller.is_active() {
            assert!(
                std::time::Instant::now() < deadline,
                "abort finalizer timeout"
            );
            thread::sleep(Duration::from_millis(10));
        }
        let status = controller.status();
        assert_eq!(status.status, "failed");
        assert!(status
            .error
            .as_deref()
            .unwrap_or_default()
            .contains("intentional unit-test interruption"));
        let manifest: serde_json::Value = serde_json::from_slice(
            &fs::read(root.join("scan-abort/dataset_manifest.json")).unwrap(),
        )
        .unwrap();
        assert_eq!(manifest["complete"], false);
        assert!(manifest["failure_reason"]
            .as_str()
            .unwrap_or_default()
            .contains("intentional unit-test interruption"));
        assert!(controller.begin(request("scan-abort", 100)).is_err());

        fs::remove_dir_all(&root).unwrap();
    }
}
