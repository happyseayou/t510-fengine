//! measurement single-board, full-band cross-correlation capture control.
//!
//! The production receiver remains the only AF_PACKET consumer.  Validated
//! SPEC payloads are copied into sixteen bounded, single-producer rings in a
//! shared mmap.  A separate CUDA executable consumes the rings and writes the
//! visibility Zarr dataset.  Nothing in this module silently falls back to a
//! sparse or CPU correlator: a missing sidecar, a full ring, or a non-zero
//! sidecar exit fails the capture.

#[cfg(test)]
use crate::STREAM_SPEC;
use crate::{T510Header, SPEC_BLOCK_COUNT, SPEC_NCHAN, TIME_NINPUT};
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};
use std::fs::{self, File, OpenOptions};
use std::io::Write;
use std::os::fd::AsRawFd;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::ptr::NonNull;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

pub const CROSSCORRELATION_PAIR_COUNT: usize = 28;
// 32768 spectra/block is about 419 ms at 320 MS/s.  A 900 s measurement run
// observed one host scheduling/writeback pause longer than the former 105 ms
// allowance after two clean scans.  Keep the queue bounded and fail-closed,
// but provide enough headroom for that class of transient host pause.
pub const CROSSCORRELATION_RING_SLOTS: usize = 32768;
pub const CROSSCORRELATION_RING_HEADER_BYTES: usize = 4096;
pub const CROSSCORRELATION_SLOT_HEADER_BYTES: usize = 64;
pub const CROSSCORRELATION_PAYLOAD_BYTES: usize = 8192;
pub const CROSSCORRELATION_SLOT_BYTES: usize =
    CROSSCORRELATION_SLOT_HEADER_BYTES + CROSSCORRELATION_PAYLOAD_BYTES;
pub const CROSSCORRELATION_RING_MAGIC: u64 = 0x3152_4358_3533_3554; // "T55XCR1"
pub const CROSSCORRELATION_RING_VERSION: u64 = 1;

const HEADER_MAGIC: usize = 0;
const HEADER_VERSION: usize = 8;
const HEADER_STATE: usize = 16;
const HEADER_CANCEL: usize = 24;
const HEADER_FAILED: usize = 32;
const HEADER_START_SAMPLE0: usize = 40;
const HEADER_END_SAMPLE0: usize = 48;
const HEADER_COMPLETED_MASK: usize = 56;
const HEADER_GENERATION: usize = 64;
const HEADER_DURATION_SECONDS: usize = 72;
const HEADER_FULL_BUCKET_MS: usize = 80;
const HEADER_FOCUS_BUCKET_MS: usize = 88;
const HEADER_FOCUS_COUNT: usize = 96;
const HEADER_RING_SLOTS: usize = 104;
const HEADER_EXPECTED_FFT_SHIFT: usize = 112;
const HEADER_SAVE_FULLBAND_100MS: usize = 120;
const HEADER_PRODUCER_BASE: usize = 128;
const HEADER_CONSUMER_BASE: usize = 256;
const HEADER_DROP_BASE: usize = 384;
const HEADER_FOCUS_BIN_BASE: usize = 512;
const HEADER_HIGH_WATER_BASE: usize = 768;
const HEADER_WARM_LAST_BASE: usize = 1024;
const HEADER_WARM_COUNT_BASE: usize = 1152;
const HEADER_WARM_READY_MASK: usize = 1280;

const STATE_INITIALIZING: u64 = 0;
const STATE_READY: u64 = 1;
const STATE_RUNNING: u64 = 2;
const STATE_DRAINING: u64 = 3;
const STATE_COMPLETED: u64 = 4;
const STATE_FAILED: u64 = 5;
const SAMPLE0_UNSET: u64 = u64::MAX;
const SAMPLE0_STEP: u64 = 4096;
const WARMUP_CONTIGUOUS_FRAMES: u64 = 8192;
// PACKET_FANOUT workers observe a newly armed generation independently.  Give
// every one of the sixteen SPEC workers a non-scientific warm-up interval and
// leave time for an explicit pre-formal integrity snapshot; observed cold
// generation/reporting latency was under 2 s.  400,000 frames is about 5.12 s
// and does not relax any formal-window gap check.
const START_LEAD_FRAMES: u64 = 400_000;
const MAX_DURATION_SECONDS: u32 = 3600;
const SIDECAR_READY_TIMEOUT: Duration = Duration::from_secs(15);

#[derive(Debug, Clone, Deserialize, Serialize, PartialEq)]
pub struct CrossCorrelationRequest {
    pub scan_id: String,
    pub tuning_id: String,
    pub duration_seconds: u32,
    #[serde(default = "default_fullband_bucket_ms")]
    pub fullband_bucket_ms: u32,
    #[serde(default = "default_focus_bucket_ms")]
    pub focus_bucket_ms: u32,
    /// Preserve every full-band 100 ms auto/cross product in addition to the
    /// backwards-compatible 1 s arrays.  The default remains false so old
    /// clients and old storage estimates keep their original behaviour.
    #[serde(default)]
    pub save_fullband_100ms: bool,
    pub sample_rate_msps: u32,
    pub center_mhz: f64,
    pub focus_global_bins: Vec<u16>,
    #[serde(default = "default_lane_mask")]
    pub lane_mask: u16,
    #[serde(default)]
    pub expected_fft_shift: Option<u16>,
    #[serde(default)]
    pub metadata: BTreeMap<String, String>,
}

fn default_fullband_bucket_ms() -> u32 {
    1000
}

fn default_focus_bucket_ms() -> u32 {
    100
}

fn default_lane_mask() -> u16 {
    0xff
}

#[derive(Debug, Clone, Default, Serialize)]
pub struct CrossCorrelationProgress {
    pub packets_published: u64,
    pub packets_consumed: u64,
    pub ring_drops: u64,
    pub completed_block_mask: u16,
    pub ring_fill_high_water: u64,
}

#[derive(Debug, Clone, Serialize)]
pub struct CrossCorrelationStatus {
    pub generation: u64,
    pub status: String,
    pub backend: String,
    pub request: Option<CrossCorrelationRequest>,
    pub output_dir: Option<String>,
    pub ring_path: Option<String>,
    pub armed_unix_ms: Option<u64>,
    pub started_unix_ms: Option<u64>,
    pub finished_unix_ms: Option<u64>,
    pub start_sample0: Option<u64>,
    pub end_sample0: Option<u64>,
    pub progress: CrossCorrelationProgress,
    pub error: Option<String>,
}

#[derive(Debug, Clone)]
struct Control {
    generation: u64,
    status: String,
    request: Option<CrossCorrelationRequest>,
    output_dir: Option<String>,
    ring_path: Option<String>,
    armed_unix_ms: Option<u64>,
    started_unix_ms: Option<u64>,
    finished_unix_ms: Option<u64>,
    error: Option<String>,
}

impl Default for Control {
    fn default() -> Self {
        Self {
            generation: 0,
            status: "idle".to_string(),
            request: None,
            output_dir: None,
            ring_path: None,
            armed_unix_ms: None,
            started_unix_ms: None,
            finished_unix_ms: None,
            error: None,
        }
    }
}

#[derive(Debug)]
struct RingMapping {
    pointer: NonNull<u8>,
    bytes: usize,
    _file: File,
}

// The mapping contains only fixed-width POD records and atomics. Each SPEC
// block has one producer. The CUDA sidecar is the sole consumer.
unsafe impl Send for RingMapping {}
unsafe impl Sync for RingMapping {}

impl Drop for RingMapping {
    fn drop(&mut self) {
        unsafe {
            libc::munmap(self.pointer.as_ptr().cast(), self.bytes);
        }
    }
}

impl RingMapping {
    fn create(path: &Path, generation: u64, request: &CrossCorrelationRequest) -> Result<Self, String> {
        let bytes = ring_bytes();
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .create_new(true)
            .open(path)
            .map_err(|error| format!("create cross-correlation ring failed: {error}"))?;
        file.set_len(bytes as u64)
            .map_err(|error| format!("size cross-correlation ring failed: {error}"))?;
        let raw = unsafe {
            libc::mmap(
                std::ptr::null_mut(),
                bytes,
                libc::PROT_READ | libc::PROT_WRITE,
                libc::MAP_SHARED,
                file.as_raw_fd(),
                0,
            )
        };
        if raw == libc::MAP_FAILED {
            return Err(format!(
                "mmap cross-correlation ring failed: {}",
                std::io::Error::last_os_error()
            ));
        }
        let pointer = NonNull::new(raw.cast::<u8>()).ok_or("mmap returned null")?;
        // A newly created, length-extended regular file reads as zero.  Do not
        // fault every data page into RAM here: slots are initialized before
        // their producer counter is released, and only the fixed header needs
        // explicit initialization below.
        let mapping = Self {
            pointer,
            bytes,
            _file: file,
        };
        mapping.store(HEADER_MAGIC, CROSSCORRELATION_RING_MAGIC, Ordering::Relaxed);
        mapping.store(
            HEADER_VERSION,
            CROSSCORRELATION_RING_VERSION,
            Ordering::Relaxed,
        );
        mapping.store(HEADER_STATE, STATE_INITIALIZING, Ordering::Relaxed);
        mapping.store(HEADER_CANCEL, 0, Ordering::Relaxed);
        mapping.store(HEADER_FAILED, 0, Ordering::Relaxed);
        mapping.store(HEADER_START_SAMPLE0, SAMPLE0_UNSET, Ordering::Relaxed);
        mapping.store(HEADER_END_SAMPLE0, SAMPLE0_UNSET, Ordering::Relaxed);
        mapping.store(HEADER_COMPLETED_MASK, 0, Ordering::Relaxed);
        mapping.store(HEADER_GENERATION, generation, Ordering::Relaxed);
        mapping.store(
            HEADER_DURATION_SECONDS,
            u64::from(request.duration_seconds),
            Ordering::Relaxed,
        );
        mapping.store(
            HEADER_FULL_BUCKET_MS,
            u64::from(request.fullband_bucket_ms),
            Ordering::Relaxed,
        );
        mapping.store(
            HEADER_FOCUS_BUCKET_MS,
            u64::from(request.focus_bucket_ms),
            Ordering::Relaxed,
        );
        mapping.store(
            HEADER_FOCUS_COUNT,
            request.focus_global_bins.len() as u64,
            Ordering::Relaxed,
        );
        mapping.store(
            HEADER_RING_SLOTS,
            CROSSCORRELATION_RING_SLOTS as u64,
            Ordering::Relaxed,
        );
        mapping.store(
            HEADER_EXPECTED_FFT_SHIFT,
            request
                .expected_fft_shift
                .map(u64::from)
                .unwrap_or(u64::MAX),
            Ordering::Relaxed,
        );
        mapping.store(
            HEADER_SAVE_FULLBAND_100MS,
            u64::from(request.save_fullband_100ms),
            Ordering::Relaxed,
        );
        for (index, global_bin) in request.focus_global_bins.iter().copied().enumerate() {
            mapping.store(
                HEADER_FOCUS_BIN_BASE + index * 8,
                u64::from(global_bin),
                Ordering::Relaxed,
            );
        }
        unsafe {
            libc::msync(
                mapping.pointer.as_ptr().cast(),
                CROSSCORRELATION_RING_HEADER_BYTES,
                libc::MS_SYNC,
            );
        }
        Ok(mapping)
    }

    fn atomic(&self, offset: usize) -> &AtomicU64 {
        assert_eq!(offset % std::mem::align_of::<AtomicU64>(), 0);
        assert!(offset + 8 <= self.bytes);
        unsafe { &*self.pointer.as_ptr().add(offset).cast::<AtomicU64>() }
    }

    fn load(&self, offset: usize, ordering: Ordering) -> u64 {
        self.atomic(offset).load(ordering)
    }

    fn store(&self, offset: usize, value: u64, ordering: Ordering) {
        self.atomic(offset).store(value, ordering);
    }

    fn state(&self) -> u64 {
        self.load(HEADER_STATE, Ordering::Acquire)
    }

    fn fail(&self) {
        self.store(HEADER_FAILED, 1, Ordering::Release);
        self.store(HEADER_CANCEL, 1, Ordering::Release);
    }

    fn producer_offset(block: usize) -> usize {
        HEADER_PRODUCER_BASE + block * 8
    }

    fn consumer_offset(block: usize) -> usize {
        HEADER_CONSUMER_BASE + block * 8
    }

    fn drop_offset(block: usize) -> usize {
        HEADER_DROP_BASE + block * 8
    }

    fn high_water_offset(block: usize) -> usize {
        HEADER_HIGH_WATER_BASE + block * 8
    }

    fn slot_offset(block: usize, sequence: u64) -> usize {
        CROSSCORRELATION_RING_HEADER_BYTES
            + (block * CROSSCORRELATION_RING_SLOTS + sequence as usize % CROSSCORRELATION_RING_SLOTS)
                * CROSSCORRELATION_SLOT_BYTES
    }

    fn publish(&self, header: &T510Header, udp_payload: &[u8]) -> Result<bool, String> {
        let block = usize::from(header.block_index);
        if block >= usize::from(SPEC_BLOCK_COUNT) {
            return Err(format!("invalid cross-correlation block {block}"));
        }
        let expected_fft_shift = self.load(HEADER_EXPECTED_FFT_SHIFT, Ordering::Relaxed);
        if expected_fft_shift != u64::MAX && u64::from(header.fft_shift) != expected_fft_shift {
            self.fail();
            return Err(format!(
                "cross-correlation fft_shift changed from requested {} to {}",
                expected_fft_shift, header.fft_shift
            ));
        }
        let start = self.load(HEADER_START_SAMPLE0, Ordering::Acquire);
        if start == SAMPLE0_UNSET {
            let count_offset = HEADER_WARM_COUNT_BASE + block * 8;
            let last_offset = HEADER_WARM_LAST_BASE + block * 8;
            let prior_count = self.load(count_offset, Ordering::Relaxed);
            let prior_sample0 = self.load(last_offset, Ordering::Relaxed);
            let count =
                if prior_count != 0 && header.sample0 == prior_sample0.wrapping_add(SAMPLE0_STEP) {
                    prior_count.saturating_add(1)
                } else {
                    1
                };
            self.store(last_offset, header.sample0, Ordering::Relaxed);
            self.store(count_offset, count, Ordering::Release);
            if count >= WARMUP_CONTIGUOUS_FRAMES {
                self.atomic(HEADER_WARM_READY_MASK)
                    .fetch_or(1u64 << block, Ordering::AcqRel);
            }
            if block != 0 {
                return Ok(false);
            }
            if self.load(HEADER_WARM_READY_MASK, Ordering::Acquire) != 0xffff {
                return Ok(false);
            }
            let candidate = header
                .sample0
                .checked_add(START_LEAD_FRAMES * SAMPLE0_STEP)
                .ok_or_else(|| "cross-correlation start sample0 overflow".to_string())?;
            if self
                .atomic(HEADER_START_SAMPLE0)
                .compare_exchange(
                    SAMPLE0_UNSET,
                    candidate,
                    Ordering::AcqRel,
                    Ordering::Acquire,
                )
                .is_ok()
            {
                let duration_ticks = self
                    .load(HEADER_DURATION_SECONDS, Ordering::Relaxed)
                    .checked_mul(320_000_000)
                    .ok_or_else(|| "cross-correlation duration sample0 overflow".to_string())?;
                self.store(
                    HEADER_END_SAMPLE0,
                    candidate
                        .checked_add(duration_ticks)
                        .ok_or_else(|| "cross-correlation end sample0 overflow".to_string())?,
                    Ordering::Release,
                );
                self.store(HEADER_STATE, STATE_RUNNING, Ordering::Release);
            }
            return Ok(false);
        }
        let end = self.load(HEADER_END_SAMPLE0, Ordering::Acquire);
        if header.sample0 < start {
            return Ok(false);
        }
        if header.sample0 >= end {
            let bit = 1u64 << block;
            self.atomic(HEADER_COMPLETED_MASK)
                .fetch_or(bit, Ordering::AcqRel);
            return Ok(false);
        }
        let body = udp_payload
            .get(128..128 + CROSSCORRELATION_PAYLOAD_BYTES)
            .ok_or_else(|| {
                "validated SPEC payload is truncated for cross-correlation".to_string()
            })?;
        let producer = self.load(Self::producer_offset(block), Ordering::Relaxed);
        let consumer = self.load(Self::consumer_offset(block), Ordering::Acquire);
        let fill = producer.saturating_sub(consumer);
        if fill >= CROSSCORRELATION_RING_SLOTS as u64 {
            self.atomic(Self::drop_offset(block))
                .fetch_add(1, Ordering::Relaxed);
            self.fail();
            return Err(format!(
                "CUDA cross-correlation ring {block} is full at {fill} packets"
            ));
        }
        self.atomic(Self::high_water_offset(block))
            .fetch_max(fill + 1, Ordering::Relaxed);
        let offset = Self::slot_offset(block, producer);
        unsafe {
            let base = self.pointer.as_ptr().add(offset);
            std::ptr::copy_nonoverlapping(header.sample0.to_le_bytes().as_ptr(), base, 8);
            std::ptr::copy_nonoverlapping(header.frame_id.to_le_bytes().as_ptr(), base.add(8), 8);
            std::ptr::copy_nonoverlapping(header.seq_no.to_le_bytes().as_ptr(), base.add(16), 4);
            std::ptr::copy_nonoverlapping(
                header.spec_status_flags.to_le_bytes().as_ptr(),
                base.add(20),
                4,
            );
            std::ptr::copy_nonoverlapping((block as u16).to_le_bytes().as_ptr(), base.add(24), 2);
            std::ptr::copy_nonoverlapping(
                (CROSSCORRELATION_PAYLOAD_BYTES as u16).to_le_bytes().as_ptr(),
                base.add(26),
                2,
            );
            std::ptr::copy_nonoverlapping(header.fft_shift.to_le_bytes().as_ptr(), base.add(28), 2);
            std::ptr::copy_nonoverlapping(
                header.scale_mode.to_le_bytes().as_ptr(),
                base.add(30),
                2,
            );
            std::ptr::copy_nonoverlapping(header.scale_id.to_le_bytes().as_ptr(), base.add(32), 4);
            std::ptr::copy_nonoverlapping(header.board_id.to_le_bytes().as_ptr(), base.add(36), 2);
            std::ptr::copy_nonoverlapping(
                header.product_id.to_le_bytes().as_ptr(),
                base.add(38),
                2,
            );
            std::ptr::copy_nonoverlapping(
                header.spec_sample_rate_hz.to_le_bytes().as_ptr(),
                base.add(40),
                4,
            );
            std::ptr::copy_nonoverlapping(header.pfb_taps.to_le_bytes().as_ptr(), base.add(44), 2);
            std::ptr::write_bytes(base.add(46), 0, 2);
            std::ptr::copy_nonoverlapping(
                header.sync_generation.to_le_bytes().as_ptr(),
                base.add(48),
                8,
            );
            std::ptr::copy_nonoverlapping(
                header.sync_observation_tag.to_le_bytes().as_ptr(),
                base.add(56),
                8,
            );
            std::ptr::copy_nonoverlapping(
                body.as_ptr(),
                base.add(CROSSCORRELATION_SLOT_HEADER_BYTES),
                CROSSCORRELATION_PAYLOAD_BYTES,
            );
        }
        self.store(
            Self::producer_offset(block),
            producer + 1,
            Ordering::Release,
        );
        Ok(true)
    }

    fn progress(&self) -> CrossCorrelationProgress {
        let mut published = 0u64;
        let mut consumed = 0u64;
        let mut drops = 0u64;
        let mut high_water = 0u64;
        for block in 0..usize::from(SPEC_BLOCK_COUNT) {
            let producer = self.load(Self::producer_offset(block), Ordering::Acquire);
            let consumer = self.load(Self::consumer_offset(block), Ordering::Acquire);
            published = published.saturating_add(producer);
            consumed = consumed.saturating_add(consumer);
            drops = drops.saturating_add(self.load(Self::drop_offset(block), Ordering::Relaxed));
            high_water =
                high_water.max(self.load(Self::high_water_offset(block), Ordering::Relaxed));
        }
        CrossCorrelationProgress {
            packets_published: published,
            packets_consumed: consumed,
            ring_drops: drops,
            completed_block_mask: self.load(HEADER_COMPLETED_MASK, Ordering::Acquire) as u16,
            ring_fill_high_water: high_water,
        }
    }
}

#[derive(Debug, Clone)]
pub struct CrossCorrelationController {
    root: PathBuf,
    sidecar: PathBuf,
    active: Arc<AtomicBool>,
    generation: Arc<AtomicU64>,
    mapping: Arc<Mutex<Option<Arc<RingMapping>>>>,
    control: Arc<Mutex<Control>>,
}

impl CrossCorrelationController {
    pub fn new(root: PathBuf, sidecar: PathBuf) -> Self {
        Self {
            root,
            sidecar,
            active: Arc::new(AtomicBool::new(false)),
            generation: Arc::new(AtomicU64::new(0)),
            mapping: Arc::new(Mutex::new(None)),
            control: Arc::new(Mutex::new(Control::default())),
        }
    }

    pub fn is_active(&self) -> bool {
        self.active.load(Ordering::Acquire)
    }

    pub fn begin(&self, request: CrossCorrelationRequest) -> Result<CrossCorrelationStatus, String> {
        validate_request(&request)?;
        if self.is_active() {
            return Err("a cross-correlation capture is already active".to_string());
        }
        if !self.sidecar.is_file() {
            return Err(format!(
                "CUDA cross-correlation sidecar is unavailable: {}",
                self.sidecar.display()
            ));
        }
        fs::create_dir_all(&self.root)
            .map_err(|error| format!("create measurement root failed: {error}"))?;
        let output_dir = self.root.join(&request.scan_id);
        fs::create_dir(&output_dir).map_err(|error| {
            format!(
                "create new cross-correlation directory {} failed: {error}",
                output_dir.display()
            )
        })?;
        let generation = self
            .generation
            .load(Ordering::Relaxed)
            .wrapping_add(1)
            .max(1);
        let ring_path = PathBuf::from(format!(
            "/run/t510-time-rx/crosscorrelation-{}-{generation}.ring",
            std::process::id()
        ));
        let mapping = match RingMapping::create(&ring_path, generation, &request) {
            Ok(mapping) => Arc::new(mapping),
            Err(error) => {
                let _ = fs::remove_dir(&output_dir);
                return Err(error);
            }
        };
        let request_path = output_dir.join("request.json");
        write_json_new(&request_path, &request)?;
        let mut child = match Command::new(&self.sidecar)
            .arg("--ring")
            .arg(&ring_path)
            .arg("--output")
            .arg(&output_dir)
            .arg("--request")
            .arg(&request_path)
            .spawn()
        {
            Ok(child) => child,
            Err(error) => {
                let _ = fs::remove_file(&ring_path);
                return Err(format!(
                    "start CUDA cross-correlation sidecar failed: {error}"
                ));
            }
        };

        let ready_deadline = Instant::now() + SIDECAR_READY_TIMEOUT;
        loop {
            if mapping.state() == STATE_READY {
                break;
            }
            if mapping.state() == STATE_FAILED
                || mapping.load(HEADER_FAILED, Ordering::Acquire) != 0
            {
                let _ = child.wait();
                return Err(read_sidecar_error(&output_dir).unwrap_or_else(|| {
                    "CUDA cross-correlation sidecar failed during initialization".to_string()
                }));
            }
            if let Some(exit) = child
                .try_wait()
                .map_err(|error| format!("poll CUDA sidecar failed: {error}"))?
            {
                return Err(format!(
                    "CUDA cross-correlation sidecar exited before ready: {exit}"
                ));
            }
            if Instant::now() >= ready_deadline {
                mapping.fail();
                let _ = child.wait();
                return Err(
                    "CUDA cross-correlation sidecar did not become ready in 15 s".to_string(),
                );
            }
            thread::sleep(Duration::from_millis(20));
        }

        self.generation.store(generation, Ordering::Release);
        *self
            .mapping
            .lock()
            .map_err(|_| "cross mapping lock poisoned")? = Some(mapping.clone());
        *self
            .control
            .lock()
            .map_err(|_| "cross control lock poisoned")? = Control {
            generation,
            status: "armed".to_string(),
            request: Some(request.clone()),
            output_dir: Some(output_dir.display().to_string()),
            ring_path: Some(ring_path.display().to_string()),
            armed_unix_ms: Some(unix_ms()),
            started_unix_ms: None,
            finished_unix_ms: None,
            error: None,
        };
        self.active.store(true, Ordering::Release);

        let monitor = self.clone();
        let monitor_output = output_dir.clone();
        let monitor_ring = ring_path.clone();
        thread::Builder::new()
            .name("t510-crosscorrelation-monitor".to_string())
            .spawn(move || {
                let result = child.wait();
                monitor.active.store(false, Ordering::Release);
                let state = mapping.state();
                if let Ok(mut control) = monitor.control.lock() {
                    if control.generation == generation {
                        control.finished_unix_ms = Some(unix_ms());
                        match result {
                            Ok(exit) if exit.success() && state == STATE_COMPLETED => {
                                control.status = "completed".to_string();
                                control.error = None;
                            }
                            Ok(exit) => {
                                control.status = "failed".to_string();
                                control.error.get_or_insert_with(|| {
                                    read_sidecar_error(&monitor_output).unwrap_or_else(|| {
                                        format!("CUDA sidecar exited {exit}; shared state={state}")
                                    })
                                });
                            }
                            Err(error) => {
                                control.status = "failed".to_string();
                                control.error =
                                    Some(format!("wait for CUDA sidecar failed: {error}"));
                            }
                        }
                    }
                }
                let _ = fs::remove_file(monitor_ring);
            })
            .map_err(|error| format!("spawn CUDA sidecar monitor failed: {error}"))?;

        let watchdog = self.clone();
        thread::Builder::new()
            .name("t510-crosscorrelation-watchdog".to_string())
            .spawn(move || {
                thread::sleep(Duration::from_secs(
                    u64::from(request.duration_seconds) + 120,
                ));
                if watchdog.generation.load(Ordering::Acquire) == generation && watchdog.is_active()
                {
                    watchdog.fail(generation, "cross-correlation watchdog expired");
                }
            })
            .map_err(|error| format!("spawn cross-correlation watchdog failed: {error}"))?;
        Ok(self.status())
    }

    pub fn ingest(
        &self,
        worker: &mut CrossCorrelationWorkerState,
        header: &T510Header,
        udp_payload: &[u8],
    ) {
        if !self.is_active() {
            return;
        }
        let generation = self.generation.load(Ordering::Acquire);
        if worker.generation != generation {
            worker.generation = generation;
            worker.mapping = self.mapping.lock().ok().and_then(|value| value.clone());
        }
        let Some(mapping) = worker.mapping.as_ref() else {
            self.fail(
                generation,
                "active cross-correlation ring mapping is missing",
            );
            return;
        };
        if mapping.load(HEADER_CANCEL, Ordering::Acquire) != 0 {
            return;
        }
        match mapping.publish(header, udp_payload) {
            Ok(true) => {
                if let Ok(mut control) = self.control.lock() {
                    if control.generation == generation && control.status == "armed" {
                        control.status = "running".to_string();
                        control.started_unix_ms = Some(unix_ms());
                    }
                }
            }
            Ok(false) => {}
            Err(error) => self.fail(generation, &error),
        }
    }

    pub fn stop(&self, reason: &str) -> Result<CrossCorrelationStatus, String> {
        let generation = self.generation.load(Ordering::Acquire);
        if generation == 0 {
            return Err("no cross-correlation capture exists".to_string());
        }
        self.fail(generation, reason);
        Ok(self.status())
    }

    fn fail(&self, generation: u64, reason: &str) {
        if self.generation.load(Ordering::Acquire) != generation {
            return;
        }
        if let Some(mapping) = self.mapping.lock().ok().and_then(|value| value.clone()) {
            mapping.fail();
        }
        if let Ok(mut control) = self.control.lock() {
            if control.generation == generation && control.status != "completed" {
                control.status = "failed".to_string();
                control.error.get_or_insert_with(|| reason.to_string());
                control.finished_unix_ms.get_or_insert_with(unix_ms);
            }
        }
    }

    pub fn status(&self) -> CrossCorrelationStatus {
        let control = self
            .control
            .lock()
            .map(|value| value.clone())
            .unwrap_or_default();
        let mapping = self.mapping.lock().ok().and_then(|value| value.clone());
        let start = mapping
            .as_ref()
            .map(|value| value.load(HEADER_START_SAMPLE0, Ordering::Acquire))
            .filter(|value| *value != SAMPLE0_UNSET);
        let end = mapping
            .as_ref()
            .map(|value| value.load(HEADER_END_SAMPLE0, Ordering::Acquire))
            .filter(|value| *value != SAMPLE0_UNSET);
        let status = if control.status == "running"
            && mapping.as_ref().map(|value| value.state()) == Some(STATE_DRAINING)
        {
            "draining".to_string()
        } else {
            control.status.clone()
        };
        CrossCorrelationStatus {
            generation: control.generation,
            status,
            backend: "cuda13_shared_ring".to_string(),
            request: control.request,
            output_dir: control.output_dir,
            ring_path: control.ring_path,
            armed_unix_ms: control.armed_unix_ms,
            started_unix_ms: control.started_unix_ms,
            finished_unix_ms: control.finished_unix_ms,
            start_sample0: start,
            end_sample0: end,
            progress: mapping.map(|value| value.progress()).unwrap_or_default(),
            error: control.error,
        }
    }
}

#[derive(Default)]
pub struct CrossCorrelationWorkerState {
    generation: u64,
    mapping: Option<Arc<RingMapping>>,
}

pub fn adc_pairs() -> [[u8; 2]; CROSSCORRELATION_PAIR_COUNT] {
    let mut pairs = [[0u8; 2]; CROSSCORRELATION_PAIR_COUNT];
    let mut index = 0;
    for left in 0..TIME_NINPUT {
        for right in left + 1..TIME_NINPUT {
            pairs[index] = [left as u8, right as u8];
            index += 1;
        }
    }
    pairs
}

pub fn validate_request(request: &CrossCorrelationRequest) -> Result<(), String> {
    validate_identifier("scan_id", &request.scan_id)?;
    validate_identifier("tuning_id", &request.tuning_id)?;
    if !(1..=MAX_DURATION_SECONDS).contains(&request.duration_seconds) {
        return Err(format!(
            "duration_seconds must be within 1..={MAX_DURATION_SECONDS}"
        ));
    }
    if request.fullband_bucket_ms != 1000 {
        return Err("fullband_bucket_ms must be 1000".to_string());
    }
    if request.focus_bucket_ms != 100 {
        return Err("focus_bucket_ms must be 100".to_string());
    }
    if request.sample_rate_msps != 320 {
        return Err("cross-correlation requires sample_rate_msps=320".to_string());
    }
    if !request.center_mhz.is_finite() || !(160.0..=6000.0).contains(&request.center_mhz) {
        return Err(
            "cross-correlation center_mhz must be finite and within 160..=6000"
                .to_string(),
        );
    }
    if request.lane_mask != 0xff {
        return Err("all 28 pairs require lane_mask=0xff".to_string());
    }
    if request.focus_global_bins.is_empty() || request.focus_global_bins.len() > 32 {
        return Err("focus_global_bins must contain 1..=32 bins".to_string());
    }
    let unique: BTreeSet<_> = request.focus_global_bins.iter().copied().collect();
    if unique.len() != request.focus_global_bins.len() {
        return Err("focus_global_bins must be unique".to_string());
    }
    if request
        .focus_global_bins
        .iter()
        .any(|value| *value >= SPEC_NCHAN)
    {
        return Err(format!(
            "focus_global_bins must be within 0..{}",
            SPEC_NCHAN - 1
        ));
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

fn ring_bytes() -> usize {
    CROSSCORRELATION_RING_HEADER_BYTES
        + usize::from(SPEC_BLOCK_COUNT) * CROSSCORRELATION_RING_SLOTS * CROSSCORRELATION_SLOT_BYTES
}

fn unix_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis()
        .min(u64::MAX as u128) as u64
}

fn write_json_new<T: Serialize>(path: &Path, value: &T) -> Result<(), String> {
    let bytes = serde_json::to_vec_pretty(value).map_err(|error| error.to_string())?;
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(path)
        .map_err(|error| format!("create {} failed: {error}", path.display()))?;
    file.write_all(&bytes)
        .and_then(|_| file.write_all(b"\n"))
        .and_then(|_| file.sync_all())
        .map_err(|error| format!("write {} failed: {error}", path.display()))
}

fn read_sidecar_error(output: &Path) -> Option<String> {
    let value: serde_json::Value =
        serde_json::from_slice(&fs::read(output.join("sidecar_status.json")).ok()?).ok()?;
    value
        .get("error")
        .and_then(serde_json::Value::as_str)
        .map(str::to_string)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn request() -> CrossCorrelationRequest {
        CrossCorrelationRequest {
            scan_id: "xcorr-test".to_string(),
            tuning_id: "center-1020".to_string(),
            duration_seconds: 60,
            fullband_bucket_ms: 1000,
            focus_bucket_ms: 100,
            save_fullband_100ms: false,
            sample_rate_msps: 320,
            center_mhz: 1020.0,
            focus_global_bins: vec![0, 1, 2048, 4095],
            lane_mask: 0xff,
            expected_fft_shift: Some(1366),
            metadata: BTreeMap::new(),
        }
    }

    #[test]
    fn pair_order_is_lexicographic_and_complete() {
        let pairs = adc_pairs();
        assert_eq!(pairs[0], [0, 1]);
        assert_eq!(pairs[6], [0, 7]);
        assert_eq!(pairs[7], [1, 2]);
        assert_eq!(pairs[27], [6, 7]);
        assert_eq!(pairs.iter().copied().collect::<BTreeSet<_>>().len(), 28);
    }

    #[test]
    fn request_contract_is_fixed_and_rejects_duplicate_focus_bins() {
        assert!(validate_request(&request()).is_ok());
        let mut invalid = request();
        invalid.focus_global_bins.push(1);
        assert!(validate_request(&invalid).unwrap_err().contains("unique"));
        invalid = request();
        invalid.fullband_bucket_ms = 100;
        assert!(validate_request(&invalid).unwrap_err().contains("1000"));
        invalid = request();
        invalid.center_mhz = 159.0;
        assert!(validate_request(&invalid)
            .unwrap_err()
            .contains("160..=6000"));
        let mut low_band = request();
        low_band.center_mhz = 200.0;
        assert!(validate_request(&low_band).is_ok());
        let mut fullband_100ms = request();
        fullband_100ms.save_fullband_100ms = true;
        assert!(validate_request(&fullband_100ms).is_ok());
    }

    #[test]
    fn shared_ring_publishes_only_formal_window_and_fails_when_full() {
        let root = std::env::temp_dir().join(format!("t510-xcorr-ring-{}", unix_ms()));
        fs::create_dir(&root).unwrap();
        let path = root.join("ring");
        let mapping = RingMapping::create(&path, 7, &request()).unwrap();
        assert_eq!(
            mapping.load(HEADER_SAVE_FULLBAND_100MS, Ordering::Relaxed),
            0
        );
        mapping.store(HEADER_STATE, STATE_READY, Ordering::Release);
        let mut header = T510Header {
            magic: 0x5435_3130,
            version: 2,
            header_bytes: 128,
            board_id: 1,
            stream_type: STREAM_SPEC,
            epoch_mode: 0,
            flags: 0,
            unix_sec: 0,
            pps_count: 0,
            sample0: 1000,
            frame_id: 1,
            seq_no: 1,
            chan0: 0,
            chan_count: 256,
            time_count: 1,
            ninput: 8,
            payload_format: 0,
            scale_id: 0,
            payload_bytes: 8192,
            product_id: 0xf101,
            nchan: 4096,
            block_index: 0,
            block_count: 16,
            pfb_taps: 8,
            fft_shift: 1366,
            spec_status_flags: 1 << 10,
            spec_sample_rate_hz: 320_000_000,
            scale_mode: 0,
            spec_half_band: false,
            header_crc: 0,
            sync_generation: 0,
            sync_observation_tag: 0,
            sync_metadata: 0,
            sync_status: 0,
        };
        let payload = vec![0u8; 128 + CROSSCORRELATION_PAYLOAD_BYTES];
        mapping.store(HEADER_WARM_READY_MASK, 0xffff, Ordering::Release);
        assert!(!mapping.publish(&header, &payload).unwrap());
        let start = mapping.load(HEADER_START_SAMPLE0, Ordering::Acquire);
        header.sample0 = start;
        assert!(mapping.publish(&header, &payload).unwrap());
        assert_eq!(mapping.progress().packets_published, 1);
        mapping.store(
            RingMapping::producer_offset(0),
            CROSSCORRELATION_RING_SLOTS as u64,
            Ordering::Release,
        );
        let error = mapping.publish(&header, &payload).unwrap_err();
        assert!(error.contains("full"));
        assert_eq!(mapping.load(HEADER_FAILED, Ordering::Acquire), 1);
        drop(mapping);
        fs::remove_dir_all(root).unwrap();
    }
}
