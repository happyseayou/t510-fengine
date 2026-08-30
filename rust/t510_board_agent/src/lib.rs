pub mod config;
pub mod model;
pub mod system;

use axum::body::Body;
use axum::extract::rejection::JsonRejection;
use axum::extract::{DefaultBodyLimit, Query, State};
use axum::http::{header, HeaderValue, StatusCode};
use axum::response::{Html, IntoResponse, Response};
use axum::routing::{get, post, put};
use axum::{Json, Router};
use config::{HelperBitstream, RuntimeConfig};
use model::{
    CalibrationRequest, ClockDiagnosticPrepareRequest, ClockDiagnosticRestoreRequest,
    ConfigureRequest, DacRequest, DiagnosticMutationRequest, ExpectedBoardRequest, Ocb1Request,
    OutputLoadRequest, ScheduledSyncPrepareRequest,
};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::path::Path;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use tokio::io::AsyncWriteExt;
use tokio::process::Command;
use tokio::sync::Mutex;

const HELP_HTML: &str = include_str!("../assets/help.html");
const OPENAPI_JSON: &str = include_str!("../assets/openapi.json");
const REFERENCE_WATCHDOG_STATE_PATH: &str = "/run/t510-ref-watchdog.json";
const OCB1_STATE_PATH: &str = "/run/t510-ocb1.json";
const CLOCK_DIAGNOSTIC_STATE_PATH: &str = "/run/t510-clock-diagnostic.json";
const OUTPUT_LOAD_STATE_PATH: &str = "/run/t510-output-load.json";
const RFDC_POWER_STATE_PATH: &str = "/run/t510-rfdc-power.json";
const POWER_THERMAL_TELEMETRY_PATH: &str = "/run/t510-power-thermal.jsonl";

#[derive(Clone)]
pub struct AppState {
    pub runtime: Arc<RuntimeConfig>,
    hardware: Arc<Mutex<()>>,
    request_counter: Arc<AtomicU64>,
}

impl AppState {
    pub fn new(runtime: RuntimeConfig) -> Self {
        invalidate_ocb1_transaction_on_agent_start();
        invalidate_clock_transaction_on_agent_start();
        invalidate_diagnostic_transaction_on_agent_start(
            OUTPUT_LOAD_STATE_PATH,
            "state",
            "ACTIVE",
            "output_load_transaction_id",
        );
        invalidate_diagnostic_transaction_on_agent_start(
            RFDC_POWER_STATE_PATH,
            "state",
            "DAC_SHUTDOWN",
            "rfdc_power_transaction_id",
        );
        Self {
            runtime: Arc::new(runtime),
            hardware: Arc::new(Mutex::new(())),
            request_counter: Arc::new(AtomicU64::new(1)),
        }
    }

    fn request_id(&self) -> String {
        let millis = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_millis();
        let counter = self.request_counter.fetch_add(1, Ordering::Relaxed);
        format!("t510-{millis:x}-{counter:x}")
    }
}

fn invalidate_diagnostic_transaction_on_agent_start(
    path: &str,
    state_key: &str,
    active_state: &str,
    transaction_key: &str,
) {
    let Ok(raw) = std::fs::read_to_string(path) else {
        return;
    };
    let Ok(mut value) = serde_json::from_str::<Value>(&raw) else {
        return;
    };
    let Some(state) = value.as_object_mut() else {
        return;
    };
    if state.get(state_key).and_then(Value::as_str) != Some(active_state) {
        return;
    }
    state.insert(state_key.into(), Value::String("RESTORE_REQUIRED".into()));
    state.insert(transaction_key.into(), Value::Null);
    state.insert("transaction_valid".into(), Value::Bool(false));
    state.insert("restore_required".into(), Value::Bool(true));
    state.insert(
        "invalid_reason".into(),
        Value::String("BOARD_AGENT_RESTART".into()),
    );
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis()
        .min(u64::MAX as u128) as u64;
    state.insert("updated_at_unix_ms".into(), Value::from(millis));
    let temporary = format!("{path}.tmp");
    if let Ok(encoded) = serde_json::to_vec(&value) {
        if std::fs::write(&temporary, encoded).is_ok() {
            let _ = std::fs::rename(temporary, path);
        }
    }
}

fn invalidate_clock_transaction_on_agent_start() {
    let Ok(raw) = std::fs::read_to_string(CLOCK_DIAGNOSTIC_STATE_PATH) else {
        return;
    };
    let Ok(mut value) = serde_json::from_str::<Value>(&raw) else {
        return;
    };
    let Some(state) = value.as_object_mut() else {
        return;
    };
    if state.get("state").and_then(Value::as_str) != Some("ACTIVE") {
        return;
    }
    state.insert("state".into(), Value::String("RESTORE_REQUIRED".into()));
    state.insert("clock_transaction_id".into(), Value::Null);
    state.insert("clock_transaction_valid".into(), Value::Bool(false));
    state.insert("restore_required".into(), Value::Bool(true));
    state.insert(
        "invalid_reason".into(),
        Value::String("BOARD_AGENT_RESTART".into()),
    );
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis()
        .min(u64::MAX as u128) as u64;
    state.insert("updated_at_unix_ms".into(), Value::from(millis));
    let temporary = format!("{CLOCK_DIAGNOSTIC_STATE_PATH}.tmp");
    if let Ok(encoded) = serde_json::to_vec(&value) {
        if std::fs::write(&temporary, encoded).is_ok() {
            let _ = std::fs::rename(temporary, CLOCK_DIAGNOSTIC_STATE_PATH);
        }
    }
}

fn invalidate_ocb1_transaction_on_agent_start() {
    let Ok(raw) = std::fs::read_to_string(OCB1_STATE_PATH) else {
        return;
    };
    let Ok(mut value) = serde_json::from_str::<Value>(&raw) else {
        return;
    };
    let Some(state) = value.as_object_mut() else {
        return;
    };
    if state.get("ocb1_override_state").and_then(Value::as_str) != Some("OVERRIDE_ACTIVE") {
        return;
    }
    state.insert(
        "ocb1_override_state".into(),
        Value::String("RECONFIGURE_REQUIRED".into()),
    );
    state.insert("ocb1_transaction_id".into(), Value::Null);
    state.insert("ocb1_transaction_valid".into(), Value::Bool(false));
    state.insert("ocb1_restore_required".into(), Value::Bool(true));
    state.insert(
        "invalid_reason".into(),
        Value::String("BOARD_AGENT_RESTART".into()),
    );
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis()
        .min(u64::MAX as u128) as u64;
    state.insert("updated_at_unix_ms".into(), Value::from(millis));
    let temporary = format!("{OCB1_STATE_PATH}.tmp");
    if let Ok(encoded) = serde_json::to_vec(&value) {
        if std::fs::write(&temporary, encoded).is_ok() {
            let _ = std::fs::rename(temporary, OCB1_STATE_PATH);
        }
    }
}

#[derive(Debug, Serialize)]
struct ErrorBody {
    request_id: String,
    code: String,
    message: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    details: Option<Value>,
}

#[derive(Debug)]
struct ApiError {
    status: StatusCode,
    body: ErrorBody,
}

impl ApiError {
    fn new(
        state: &AppState,
        status: StatusCode,
        code: impl Into<String>,
        message: impl Into<String>,
        details: Option<Value>,
    ) -> Self {
        Self {
            status,
            body: ErrorBody {
                request_id: state.request_id(),
                code: code.into(),
                message: message.into(),
                details,
            },
        }
    }
}

impl IntoResponse for ApiError {
    fn into_response(self) -> Response {
        (self.status, Json(self.body)).into_response()
    }
}

fn json_rejection(state: &AppState, rejection: JsonRejection) -> ApiError {
    ApiError::new(
        state,
        StatusCode::BAD_REQUEST,
        "INVALID_JSON",
        "request body does not match the API schema",
        Some(json!({"reason": rejection.body_text()})),
    )
}

fn success(state: &AppState, result: Value) -> Json<Value> {
    Json(json!({"request_id": state.request_id(), "result": result}))
}

async fn root() -> Response {
    let mut response = Response::new(Body::empty());
    *response.status_mut() = StatusCode::FOUND;
    response
        .headers_mut()
        .insert(header::LOCATION, HeaderValue::from_static("/api/help"));
    response
}

async fn help() -> Html<&'static str> {
    Html(HELP_HTML)
}

async fn openapi() -> Response {
    let mut response = Response::new(Body::from(OPENAPI_JSON));
    response.headers_mut().insert(
        header::CONTENT_TYPE,
        HeaderValue::from_static("application/json; charset=utf-8"),
    );
    response
}

async fn live(State(state): State<AppState>) -> Json<Value> {
    success(
        &state,
        json!({
            "live": true,
            "agent_version": env!("CARGO_PKG_VERSION"),
            "security_mode": "none"
        }),
    )
}

async fn ready(State(state): State<AppState>) -> Result<Json<Value>, ApiError> {
    let errors = state.runtime.ready_errors();
    if errors.is_empty() {
        Ok(success(
            &state,
            json!({"ready": true, "hardware_accessed": false}),
        ))
    } else {
        Err(ApiError::new(
            &state,
            StatusCode::SERVICE_UNAVAILABLE,
            "AGENT_NOT_READY",
            "one or more local Agent files are unavailable",
            Some(json!({"errors": errors, "hardware_accessed": false})),
        ))
    }
}

async fn info(State(state): State<AppState>) -> Result<Json<Value>, ApiError> {
    let interface = &state.runtime.config.management_interface;
    let mac = system::interface_mac(interface).map_err(|message| {
        ApiError::new(
            &state,
            StatusCode::SERVICE_UNAVAILABLE,
            "DEVICE_INFO_UNAVAILABLE",
            message,
            None,
        )
    })?;
    let addresses = system::network_addresses(interface).map_err(|message| {
        ApiError::new(
            &state,
            StatusCode::SERVICE_UNAVAILABLE,
            "DEVICE_INFO_UNAVAILABLE",
            message,
            None,
        )
    })?;
    let memory = system::memory_info().map_err(|message| {
        ApiError::new(
            &state,
            StatusCode::SERVICE_UNAVAILABLE,
            "DEVICE_INFO_UNAVAILABLE",
            message,
            None,
        )
    })?;
    let hostname = system::read_trimmed("/etc/hostname").unwrap_or_else(|_| "unknown".into());
    let machine_id =
        system::read_trimmed("/etc/machine-id").unwrap_or_else(|_| "unavailable".into());
    let management_addresses: Vec<&str> = addresses
        .iter()
        .filter(|item| item.management)
        .map(|item| item.address.as_str())
        .collect();
    let listen_port = state
        .runtime
        .config
        .listen
        .parse::<std::net::SocketAddr>()
        .map(|address| address.port())
        .unwrap_or(8010);
    Ok(success(
        &state,
        json!({
            "device_uid": system::device_uid(&mac),
            "hostname": hostname,
            "machine_id": machine_id,
            "architecture": std::env::consts::ARCH,
            "agent_version": env!("CARGO_PKG_VERSION"),
            "management_interface": interface,
            "management_mac": mac,
            "management_addresses": management_addresses,
            "addresses": addresses,
            "memory": memory,
            "listen": state.runtime.config.listen,
            "listen_port": listen_port,
            "security_mode": "none"
        }),
    ))
}

async fn capabilities(State(state): State<AppState>) -> Json<Value> {
    success(
        &state,
        json!({
            "security_mode": "none",
            "cors": false,
            "stateless": true,
            "hardware_serialization": "agent_local_try_lock",
            "board_id_assignment": "configure_request",
            "start_modes": ["IMMEDIATE", "SCHEDULED_PPS"],
            "clock_references": {
                "external_10mhz": {"sync_mode": "external_pps"},
                "onboard_tcxo": {"sync_mode": "free_run", "external_10mhz_required": false, "external_pps_required": false}
            },
            "scheduled_pps_requires_clock_reference": "external_10mhz",
            "status": {
                "single_register_snapshot": true,
                "background_polling": false,
                "rates_or_trends": false,
                "waveform": false,
                "spectrum": false,
                "packet_capture": false
            },
            "operations": {
                "configure": true,
                "start": true,
                "stop": true,
                "reset": true,
                "dac_atomic_update": true,
                "rfdc_calibration_observation": true,
                "rfdc_calibration_software_freeze": true,
                "rfdc_calibration_stopped_preview": true,
                "rfdc_ocb1_snapshot_override": true,
                "rfdc_ocb1_transaction_bound_start": true,
                "clock_diagnostic_profiles": true,
                "clock_transaction_bound_start": true,
                "sysref_mts_only_diagnostic": true,
                "scheduled_start": true,
                "scheduled_sync_prepare_arm_abort": true,
                "full_dual_clock_pipeline_flush": true,
                "streaming_data_path_health": true,
                "automatic_stop": true,
                "external_reference_watchdog": {
                    "enabled": true,
                    "source": "LMK04828_SPI_PLL1_PLL2",
                    "state_path": "/run/t510-ref-watchdog.json",
                    "start_arm_fail_closed": true
                },
                "delay_schedule": false,
                "maintenance_lease": false
            },
            "coordination": {
                "jupyter_managed": false,
                "notebook_locking": false,
                "hub_registration": false
            }
        }),
    )
}

async fn bitstreams(State(state): State<AppState>) -> Json<Value> {
    let mut items: Vec<_> = state
        .runtime
        .catalog
        .values()
        .map(|item| &item.public)
        .collect();
    items.sort_by(|left, right| left.id.cmp(&right.id));
    success(
        &state,
        json!({
            "default_bitstream_id": state.runtime.config.default_bitstream_id,
            "bitstreams": items
        }),
    )
}

fn helper_error(
    state: &AppState,
    exit_code: Option<i32>,
    payload: Option<&Value>,
    stderr: &str,
) -> ApiError {
    let helper = payload
        .and_then(|value| value.get("error"))
        .and_then(Value::as_object);
    let helper_code = helper
        .and_then(|value| value.get("code"))
        .and_then(Value::as_str)
        .unwrap_or("HARDWARE_OPERATION_FAILED");
    let message = helper
        .and_then(|value| value.get("message"))
        .and_then(Value::as_str)
        .unwrap_or("Python helper failed");
    let details = helper
        .and_then(|value| value.get("details"))
        .cloned()
        .unwrap_or_else(|| json!({"python_exit_code": exit_code, "stderr": stderr}));
    let status = match exit_code {
        Some(2) => StatusCode::BAD_REQUEST,
        Some(3) => StatusCode::CONFLICT,
        Some(4..=6) | None => StatusCode::SERVICE_UNAVAILABLE,
        _ => StatusCode::SERVICE_UNAVAILABLE,
    };
    ApiError::new(state, status, helper_code, message, Some(details))
}

async fn run_hardware(
    state: &AppState,
    command_name: &str,
    bitstream: &HelperBitstream,
    request: Value,
    timeout_seconds: u64,
) -> Result<Json<Value>, ApiError> {
    let _guard = state.hardware.try_lock().map_err(|_| {
        ApiError::new(
            state,
            StatusCode::CONFLICT,
            "HARDWARE_BUSY",
            "another Agent hardware request is running",
            None,
        )
    })?;
    let envelope = json!({"bitstream": bitstream, "request": request});
    let input = serde_json::to_vec(&envelope).expect("serializable helper request");
    let mut child = Command::new(&state.runtime.config.python_executable)
        .arg(&state.runtime.config.helper_path)
        .arg(command_name)
        .env("PYTHONPATH", &state.runtime.config.helper_pythonpath)
        .env("PYTHONDONTWRITEBYTECODE", "1")
        .env("PYTHONUNBUFFERED", "1")
        .env("XILINX_XRT", "/usr")
        .stdin(std::process::Stdio::piped())
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped())
        .kill_on_drop(true)
        .spawn()
        .map_err(|error| {
            ApiError::new(
                state,
                StatusCode::SERVICE_UNAVAILABLE,
                "PYTHON_UNAVAILABLE",
                format!("cannot start Python helper: {error}"),
                None,
            )
        })?;
    child
        .stdin
        .as_mut()
        .expect("piped stdin")
        .write_all(&input)
        .await
        .map_err(|error| {
            ApiError::new(
                state,
                StatusCode::SERVICE_UNAVAILABLE,
                "PYTHON_IO_FAILED",
                format!("cannot write Python helper request: {error}"),
                None,
            )
        })?;
    drop(child.stdin.take());
    let output = tokio::time::timeout(
        Duration::from_secs(timeout_seconds),
        child.wait_with_output(),
    )
    .await
    .map_err(|_| {
        ApiError::new(
            state,
            StatusCode::GATEWAY_TIMEOUT,
            "PYTHON_TIMEOUT",
            format!("Python helper exceeded {timeout_seconds} seconds"),
            Some(json!({"command": command_name})),
        )
    })?
    .map_err(|error| {
        ApiError::new(
            state,
            StatusCode::SERVICE_UNAVAILABLE,
            "PYTHON_IO_FAILED",
            format!("cannot collect Python helper output: {error}"),
            None,
        )
    })?;
    let stdout = String::from_utf8_lossy(&output.stdout);
    let stderr = String::from_utf8_lossy(&output.stderr);
    if !stderr.trim().is_empty() {
        tracing::info!(
            command = command_name,
            stderr = %stderr.trim(),
            "Python helper diagnostics"
        );
    }
    let parsed_whole = serde_json::from_str(stdout.trim());
    let payload: Value = parsed_whole
        .or_else(|whole_error| {
            // libmetal writes a few RFDC driver diagnostics directly to the C
            // stdout file descriptor, bypassing Python's redirect_stdout.  The
            // helper contract remains its final JSON line; preserve earlier text
            // as diagnostics instead of hiding the structured hardware failure.
            stdout
                .lines()
                .rev()
                .find_map(|line| serde_json::from_str::<Value>(line.trim()).ok())
                .ok_or(whole_error)
        })
        .map_err(|error| {
            ApiError::new(
                state,
                StatusCode::SERVICE_UNAVAILABLE,
                "PYTHON_PROTOCOL_ERROR",
                "Python helper did not emit one valid JSON object",
                Some(json!({
                    "reason": error.to_string(),
                    "stdout": stdout.chars().take(2048).collect::<String>(),
                    "stderr": stderr.chars().take(2048).collect::<String>()
                })),
            )
        })?;
    if !output.status.success() || payload.get("ok") != Some(&Value::Bool(true)) {
        return Err(helper_error(
            state,
            output.status.code(),
            Some(&payload),
            &stderr,
        ));
    }
    let result = payload.get("result").cloned().unwrap_or(Value::Null);
    Ok(success(state, result))
}

async fn status(State(state): State<AppState>) -> Result<Json<Value>, ApiError> {
    run_hardware(
        &state,
        "status",
        &state.runtime.default_bitstream().helper,
        json!({}),
        state.runtime.config.operation_timeout_seconds,
    )
    .await
}

async fn calibration_status(State(state): State<AppState>) -> Result<Json<Value>, ApiError> {
    run_hardware(
        &state,
        "calibration-status",
        &state.runtime.default_bitstream().helper,
        json!({}),
        state.runtime.config.operation_timeout_seconds,
    )
    .await
}

async fn calibration_monitor(State(state): State<AppState>) -> Result<Json<Value>, ApiError> {
    let raw = std::fs::read_to_string(REFERENCE_WATCHDOG_STATE_PATH).map_err(|error| {
        ApiError::new(
            &state,
            StatusCode::SERVICE_UNAVAILABLE,
            "CALIBRATION_MONITOR_UNAVAILABLE",
            format!("cannot read resident calibration monitor: {error}"),
            Some(json!({"path": REFERENCE_WATCHDOG_STATE_PATH})),
        )
    })?;
    let watchdog: Value = serde_json::from_str(&raw).map_err(|error| {
        ApiError::new(
            &state,
            StatusCode::SERVICE_UNAVAILABLE,
            "CALIBRATION_MONITOR_INVALID",
            format!("resident calibration monitor is not valid JSON: {error}"),
            Some(json!({"path": REFERENCE_WATCHDOG_STATE_PATH})),
        )
    })?;
    let observation = watchdog
        .get("calibration_observation")
        .cloned()
        .ok_or_else(|| {
            ApiError::new(
                &state,
                StatusCode::SERVICE_UNAVAILABLE,
                "CALIBRATION_MONITOR_NOT_READY",
                "resident watchdog has not published a calibration observation",
                Some(json!({"path": REFERENCE_WATCHDOG_STATE_PATH})),
            )
        })?;
    let ocb1: Value = std::fs::read_to_string(OCB1_STATE_PATH)
        .ok()
        .and_then(|raw| serde_json::from_str(&raw).ok())
        .unwrap_or_else(|| {
            json!({
                "ocb1_override_state": "DYNAMIC",
                "ocb1_override_adc_mask": 0,
                "ocb1_transaction_id": null,
                "ocb1_transaction_valid": false,
                "ocb1_restore_required": false
            })
        });
    let current_hash = observation
        .pointer("/coefficient_sha256/ocb1")
        .and_then(Value::as_str);
    let expected_hash = ocb1.get("ocb1_snapshot_sha256").and_then(Value::as_str);
    let active = ocb1.get("ocb1_override_state").and_then(Value::as_str) == Some("OVERRIDE_ACTIVE");
    let ocb1_integrity_ok = !active
        || (ocb1.get("ocb1_transaction_valid").and_then(Value::as_bool) == Some(true)
            && current_hash.is_some()
            && current_hash == expected_hash);
    Ok(success(
        &state,
        json!({
            "source": "resident_reference_watchdog",
            "watchdog_updated_at_unix_ms": watchdog.get("updated_at_unix_ms"),
            "watchdog_mode": watchdog.get("mode"),
            "watchdog_healthy": watchdog.get("healthy"),
            "hardware": watchdog.get("hardware"),
            "calibration": observation,
            "ams": watchdog.get("ams_telemetry"),
            "power_thermal_telemetry": watchdog.get("power_thermal_telemetry"),
            "ocb1": {
                "state": ocb1,
                "current_sha256": current_hash,
                "integrity_ok": ocb1_integrity_ok,
            },
        }),
    ))
}

#[derive(Debug, Default, Deserialize)]
struct PowerThermalQuery {
    #[serde(default)]
    since_seq: u64,
}

async fn power_thermal_telemetry(
    State(state): State<AppState>,
    Query(query): Query<PowerThermalQuery>,
) -> Result<Json<Value>, ApiError> {
    let raw = std::fs::read_to_string(POWER_THERMAL_TELEMETRY_PATH).map_err(|error| {
        ApiError::new(
            &state,
            StatusCode::SERVICE_UNAVAILABLE,
            "POWER_THERMAL_TELEMETRY_UNAVAILABLE",
            format!("cannot read resident power/thermal telemetry: {error}"),
            Some(json!({"path": POWER_THERMAL_TELEMETRY_PATH})),
        )
    })?;
    let mut rows = Vec::new();
    for (line_number, line) in raw.lines().enumerate() {
        if line.trim().is_empty() {
            continue;
        }
        let row: Value = serde_json::from_str(line).map_err(|error| {
            ApiError::new(
                &state,
                StatusCode::SERVICE_UNAVAILABLE,
                "POWER_THERMAL_TELEMETRY_INVALID",
                format!(
                    "invalid telemetry JSONL at line {}: {error}",
                    line_number + 1
                ),
                Some(json!({"path": POWER_THERMAL_TELEMETRY_PATH})),
            )
        })?;
        let sequence = row.get("sequence").and_then(Value::as_u64).unwrap_or(0);
        if sequence > query.since_seq {
            rows.push(row);
        }
    }
    let first_sequence = rows
        .first()
        .and_then(|row| row.get("sequence"))
        .and_then(Value::as_u64);
    let last_sequence = rows
        .last()
        .and_then(|row| row.get("sequence"))
        .and_then(Value::as_u64);
    let epoch_id = rows
        .last()
        .and_then(|row| row.get("epoch_id"))
        .and_then(Value::as_str);
    Ok(success(
        &state,
        json!({
            "source": "resident_reference_watchdog",
            "path": POWER_THERMAL_TELEMETRY_PATH,
            "since_seq": query.since_seq,
            "record_count": rows.len(),
            "first_sequence": first_sequence,
            "last_sequence": last_sequence,
            "epoch_id": epoch_id,
            "records": rows,
        }),
    ))
}

async fn output_load_status(State(state): State<AppState>) -> Result<Json<Value>, ApiError> {
    run_hardware(
        &state,
        "output-load-status",
        &state.runtime.default_bitstream().helper,
        json!({}),
        state.runtime.config.operation_timeout_seconds,
    )
    .await
}

async fn output_load_apply(
    State(state): State<AppState>,
    payload: Result<Json<OutputLoadRequest>, JsonRejection>,
) -> Result<Json<Value>, ApiError> {
    let Json(request) = payload.map_err(|error| json_rejection(&state, error))?;
    request.validate().map_err(|message| {
        ApiError::new(
            &state,
            StatusCode::BAD_REQUEST,
            "SCHEMA_VALIDATION_FAILED",
            message,
            None,
        )
    })?;
    run_hardware(
        &state,
        "output-load-apply",
        &state.runtime.default_bitstream().helper,
        serde_json::to_value(request).expect("serializable output-load request"),
        state.runtime.config.operation_timeout_seconds,
    )
    .await
}

async fn output_load_restore(
    State(state): State<AppState>,
    payload: Result<Json<DiagnosticMutationRequest>, JsonRejection>,
) -> Result<Json<Value>, ApiError> {
    let Json(request) = payload.map_err(|error| json_rejection(&state, error))?;
    run_hardware(
        &state,
        "output-load-restore",
        &state.runtime.default_bitstream().helper,
        serde_json::to_value(request).expect("serializable diagnostic request"),
        state.runtime.config.operation_timeout_seconds,
    )
    .await
}

async fn rfdc_power_status(State(state): State<AppState>) -> Result<Json<Value>, ApiError> {
    run_hardware(
        &state,
        "rfdc-power-status",
        &state.runtime.default_bitstream().helper,
        json!({}),
        state.runtime.config.operation_timeout_seconds,
    )
    .await
}

async fn rfdc_power_dac_shutdown(
    State(state): State<AppState>,
    payload: Result<Json<DiagnosticMutationRequest>, JsonRejection>,
) -> Result<Json<Value>, ApiError> {
    let Json(request) = payload.map_err(|error| json_rejection(&state, error))?;
    run_hardware(
        &state,
        "rfdc-power-dac-shutdown",
        &state.runtime.default_bitstream().helper,
        serde_json::to_value(request).expect("serializable diagnostic request"),
        state
            .runtime
            .config
            .configure_timeout_seconds
            .saturating_add(30),
    )
    .await
}

async fn rfdc_power_restore(
    State(state): State<AppState>,
    payload: Result<Json<DiagnosticMutationRequest>, JsonRejection>,
) -> Result<Json<Value>, ApiError> {
    let Json(request) = payload.map_err(|error| json_rejection(&state, error))?;
    run_hardware(
        &state,
        "rfdc-power-restore",
        &state.runtime.default_bitstream().helper,
        serde_json::to_value(request).expect("serializable diagnostic request"),
        state
            .runtime
            .config
            .configure_timeout_seconds
            .saturating_add(30),
    )
    .await
}

async fn ocb1_status(State(state): State<AppState>) -> Result<Json<Value>, ApiError> {
    run_hardware(
        &state,
        "ocb1-status",
        &state.runtime.default_bitstream().helper,
        json!({}),
        state.runtime.config.operation_timeout_seconds,
    )
    .await
}

async fn ocb1_snapshot_override(
    State(state): State<AppState>,
    payload: Result<Json<Ocb1Request>, JsonRejection>,
) -> Result<Json<Value>, ApiError> {
    let Json(request) = payload.map_err(|error| json_rejection(&state, error))?;
    run_hardware(
        &state,
        "ocb1-snapshot-override",
        &state.runtime.default_bitstream().helper,
        serde_json::to_value(request).expect("serializable OCB1 request"),
        state
            .runtime
            .config
            .configure_timeout_seconds
            .saturating_add(30),
    )
    .await
}

async fn ocb1_release(
    State(state): State<AppState>,
    payload: Result<Json<Ocb1Request>, JsonRejection>,
) -> Result<Json<Value>, ApiError> {
    let Json(request) = payload.map_err(|error| json_rejection(&state, error))?;
    run_hardware(
        &state,
        "ocb1-release",
        &state.runtime.default_bitstream().helper,
        serde_json::to_value(request).expect("serializable OCB1 request"),
        state
            .runtime
            .config
            .configure_timeout_seconds
            .saturating_add(30),
    )
    .await
}

async fn clock_diagnostic_status(State(state): State<AppState>) -> Result<Json<Value>, ApiError> {
    run_hardware(
        &state,
        "clock-diagnostic-status",
        &state.runtime.default_bitstream().helper,
        json!({}),
        state.runtime.config.operation_timeout_seconds,
    )
    .await
}

async fn clock_diagnostic_prepare(
    State(state): State<AppState>,
    payload: Result<Json<ClockDiagnosticPrepareRequest>, JsonRejection>,
) -> Result<Json<Value>, ApiError> {
    let Json(request) = payload.map_err(|error| json_rejection(&state, error))?;
    request.validate().map_err(|message| {
        ApiError::new(
            &state,
            StatusCode::BAD_REQUEST,
            "SCHEMA_VALIDATION_FAILED",
            message,
            None,
        )
    })?;
    run_hardware(
        &state,
        "clock-diagnostic-prepare",
        &state.runtime.default_bitstream().helper,
        serde_json::to_value(request).expect("serializable clock diagnostic request"),
        state
            .runtime
            .config
            .configure_timeout_seconds
            .saturating_add(30),
    )
    .await
}

async fn clock_diagnostic_restore(
    State(state): State<AppState>,
    payload: Result<Json<ClockDiagnosticRestoreRequest>, JsonRejection>,
) -> Result<Json<Value>, ApiError> {
    let Json(request) = payload.map_err(|error| json_rejection(&state, error))?;
    run_hardware(
        &state,
        "clock-diagnostic-restore",
        &state.runtime.default_bitstream().helper,
        serde_json::to_value(request).expect("serializable clock restore request"),
        state
            .runtime
            .config
            .configure_timeout_seconds
            .saturating_add(30),
    )
    .await
}

async fn calibration_freeze(
    State(state): State<AppState>,
    payload: Result<Json<CalibrationRequest>, JsonRejection>,
) -> Result<Json<Value>, ApiError> {
    let Json(request) = payload.map_err(|error| json_rejection(&state, error))?;
    run_hardware(
        &state,
        "calibration-freeze",
        &state.runtime.default_bitstream().helper,
        serde_json::to_value(request).expect("serializable calibration request"),
        state.runtime.config.operation_timeout_seconds,
    )
    .await
}

async fn calibration_unfreeze(
    State(state): State<AppState>,
    payload: Result<Json<CalibrationRequest>, JsonRejection>,
) -> Result<Json<Value>, ApiError> {
    let Json(request) = payload.map_err(|error| json_rejection(&state, error))?;
    run_hardware(
        &state,
        "calibration-unfreeze",
        &state.runtime.default_bitstream().helper,
        serde_json::to_value(request).expect("serializable calibration request"),
        state.runtime.config.operation_timeout_seconds,
    )
    .await
}

async fn calibration_preview(
    State(state): State<AppState>,
    payload: Result<Json<CalibrationRequest>, JsonRejection>,
) -> Result<Json<Value>, ApiError> {
    let Json(request) = payload.map_err(|error| json_rejection(&state, error))?;
    run_hardware(
        &state,
        "calibration-preview",
        &state.runtime.default_bitstream().helper,
        serde_json::to_value(request).expect("serializable calibration request"),
        state.runtime.config.operation_timeout_seconds,
    )
    .await
}

async fn calibration_train_freeze(
    State(state): State<AppState>,
    payload: Result<Json<CalibrationRequest>, JsonRejection>,
) -> Result<Json<Value>, ApiError> {
    let Json(request) = payload.map_err(|error| json_rejection(&state, error))?;
    if !request.training_dac_active {
        return Err(ApiError::new(
            &state,
            StatusCode::BAD_REQUEST,
            "CALIBRATION_TRAINING_DAC_REQUIRED",
            "train-freeze requires training_dac_active=true",
            None,
        ));
    }
    let amplitude = request.training_amplitude_percent.ok_or_else(|| {
        ApiError::new(
            &state,
            StatusCode::BAD_REQUEST,
            "CALIBRATION_TRAINING_AMPLITUDE_REQUIRED",
            "train-freeze requires training_amplitude_percent",
            None,
        )
    })?;
    if !amplitude.is_finite() || amplitude <= 0.0 || amplitude > 100.0 {
        return Err(ApiError::new(
            &state,
            StatusCode::BAD_REQUEST,
            "CALIBRATION_TRAINING_AMPLITUDE_INVALID",
            "training_amplitude_percent must be within (0, 100]",
            Some(json!({"training_amplitude_percent": amplitude})),
        ));
    }
    run_hardware(
        &state,
        "calibration-train-freeze",
        &state.runtime.default_bitstream().helper,
        serde_json::to_value(request).expect("serializable calibration request"),
        45,
    )
    .await
}

async fn configure(
    State(state): State<AppState>,
    payload: Result<Json<ConfigureRequest>, JsonRejection>,
) -> Result<Json<Value>, ApiError> {
    let Json(request) = payload.map_err(|error| json_rejection(&state, error))?;
    request.validate().map_err(|message| {
        ApiError::new(
            &state,
            StatusCode::BAD_REQUEST,
            "SCHEMA_VALIDATION_FAILED",
            message,
            None,
        )
    })?;
    let resolved = state
        .runtime
        .bitstream(&request.bitstream_id)
        .ok_or_else(|| {
            ApiError::new(
                &state,
                StatusCode::NOT_FOUND,
                "UNKNOWN_BITSTREAM",
                format!("unknown bitstream_id {}", request.bitstream_id),
                None,
            )
        })?;
    let profile_supported = resolved.public.profiles.iter().any(|profile| {
        profile.sample_rate_msps == request.profile.sample_rate_msps
            && profile.modes.contains(&request.profile.mode)
    });
    if !profile_supported {
        return Err(ApiError::new(
            &state,
            StatusCode::CONFLICT,
            "PROFILE_UNAVAILABLE",
            "the selected bitstream does not advertise the requested profile",
            Some(json!({
                "bitstream_id": request.bitstream_id,
                "sample_rate_msps": request.profile.sample_rate_msps,
                "mode": request.profile.mode
            })),
        ));
    }
    let bitstream = resolved.helper.clone();
    run_hardware(
        &state,
        "configure",
        &bitstream,
        serde_json::to_value(request).expect("serializable configure request"),
        state.runtime.config.configure_timeout_seconds,
    )
    .await
}

async fn start(
    State(state): State<AppState>,
    payload: Result<Json<ExpectedBoardRequest>, JsonRejection>,
) -> Result<Json<Value>, ApiError> {
    let Json(request) = payload.map_err(|error| json_rejection(&state, error))?;
    run_hardware(
        &state,
        "start",
        &state.runtime.default_bitstream().helper,
        serde_json::to_value(request).expect("serializable start request"),
        state.runtime.config.operation_timeout_seconds,
    )
    .await
}

async fn sync_status(State(state): State<AppState>) -> Result<Json<Value>, ApiError> {
    run_hardware(
        &state,
        "sync-status",
        &state.runtime.default_bitstream().helper,
        json!({}),
        state.runtime.config.operation_timeout_seconds,
    )
    .await
}

async fn sync_prepare(
    State(state): State<AppState>,
    payload: Result<Json<ScheduledSyncPrepareRequest>, JsonRejection>,
) -> Result<Json<Value>, ApiError> {
    let Json(request) = payload.map_err(|error| json_rejection(&state, error))?;
    request.validate().map_err(|message| {
        ApiError::new(
            &state,
            StatusCode::BAD_REQUEST,
            "SCHEMA_VALIDATION_FAILED",
            message,
            None,
        )
    })?;
    run_hardware(
        &state,
        "sync-prepare",
        &state.runtime.default_bitstream().helper,
        serde_json::to_value(request).expect("serializable scheduled sync request"),
        state.runtime.config.operation_timeout_seconds,
    )
    .await
}

async fn sync_arm(
    State(state): State<AppState>,
    payload: Result<Json<ExpectedBoardRequest>, JsonRejection>,
) -> Result<Json<Value>, ApiError> {
    let Json(request) = payload.map_err(|error| json_rejection(&state, error))?;
    run_hardware(
        &state,
        "sync-arm",
        &state.runtime.default_bitstream().helper,
        serde_json::to_value(request).expect("serializable scheduled arm request"),
        state.runtime.config.operation_timeout_seconds,
    )
    .await
}

async fn sync_abort(
    State(state): State<AppState>,
    payload: Result<Json<ExpectedBoardRequest>, JsonRejection>,
) -> Result<Json<Value>, ApiError> {
    let Json(request) = payload.map_err(|error| json_rejection(&state, error))?;
    run_hardware(
        &state,
        "sync-abort",
        &state.runtime.default_bitstream().helper,
        serde_json::to_value(request).expect("serializable scheduled abort request"),
        state.runtime.config.operation_timeout_seconds,
    )
    .await
}

async fn stop(State(state): State<AppState>) -> Result<Json<Value>, ApiError> {
    run_hardware(
        &state,
        "stop",
        &state.runtime.default_bitstream().helper,
        json!({}),
        state.runtime.config.operation_timeout_seconds,
    )
    .await
}

async fn reset(
    State(state): State<AppState>,
    payload: Result<Json<ExpectedBoardRequest>, JsonRejection>,
) -> Result<Json<Value>, ApiError> {
    let Json(request) = payload.map_err(|error| json_rejection(&state, error))?;
    run_hardware(
        &state,
        "reset",
        &state.runtime.default_bitstream().helper,
        serde_json::to_value(request).expect("serializable reset request"),
        state.runtime.config.operation_timeout_seconds,
    )
    .await
}

async fn dac(
    State(state): State<AppState>,
    payload: Result<Json<DacRequest>, JsonRejection>,
) -> Result<Json<Value>, ApiError> {
    let Json(request) = payload.map_err(|error| json_rejection(&state, error))?;
    request.validate().map_err(|message| {
        ApiError::new(
            &state,
            StatusCode::BAD_REQUEST,
            "SCHEMA_VALIDATION_FAILED",
            message,
            None,
        )
    })?;
    run_hardware(
        &state,
        "set-dac",
        &state.runtime.default_bitstream().helper,
        serde_json::to_value(request).expect("serializable DAC request"),
        state.runtime.config.operation_timeout_seconds,
    )
    .await
}

async fn fallback(State(state): State<AppState>) -> ApiError {
    ApiError::new(
        &state,
        StatusCode::NOT_FOUND,
        "NOT_FOUND",
        "API route not found; open /api/help",
        None,
    )
}

pub fn app(state: AppState) -> Router {
    Router::new()
        .route("/", get(root))
        .route("/api/help", get(help))
        .route("/api/openapi.json", get(openapi))
        .route("/health/live", get(live))
        .route("/health/ready", get(ready))
        .route("/api/v2/info", get(info))
        .route("/api/v2/capabilities", get(capabilities))
        .route("/api/v2/bitstreams", get(bitstreams))
        .route("/api/v2/status", get(status))
        .route("/api/v2/rfdc/calibration", get(calibration_status))
        .route("/api/v2/rfdc/calibration/monitor", get(calibration_monitor))
        .route(
            "/api/v2/telemetry/power-thermal",
            get(power_thermal_telemetry),
        )
        .route(
            "/api/v2/diagnostics/output-load",
            get(output_load_status).post(output_load_apply),
        )
        .route(
            "/api/v2/diagnostics/output-load/restore",
            post(output_load_restore),
        )
        .route("/api/v2/rfdc/power", get(rfdc_power_status))
        .route(
            "/api/v2/rfdc/power/dac-shutdown",
            post(rfdc_power_dac_shutdown),
        )
        .route("/api/v2/rfdc/power/restore", post(rfdc_power_restore))
        .route("/api/v2/rfdc/calibration/ocb1", get(ocb1_status))
        .route(
            "/api/v2/rfdc/calibration/ocb1/snapshot-override",
            post(ocb1_snapshot_override),
        )
        .route("/api/v2/rfdc/calibration/ocb1/release", post(ocb1_release))
        .route("/api/v2/clock/diagnostic", get(clock_diagnostic_status))
        .route(
            "/api/v2/clock/diagnostic/prepare",
            post(clock_diagnostic_prepare),
        )
        .route(
            "/api/v2/clock/diagnostic/restore",
            post(clock_diagnostic_restore),
        )
        .route("/api/v2/rfdc/calibration/freeze", post(calibration_freeze))
        .route(
            "/api/v2/rfdc/calibration/unfreeze",
            post(calibration_unfreeze),
        )
        .route(
            "/api/v2/rfdc/calibration/preview",
            post(calibration_preview),
        )
        .route(
            "/api/v2/rfdc/calibration/train-freeze",
            post(calibration_train_freeze),
        )
        .route("/api/v2/configure", post(configure))
        .route("/api/v2/start", post(start))
        .route("/api/v2/sync/status", get(sync_status))
        .route("/api/v2/sync/prepare", post(sync_prepare))
        .route("/api/v2/sync/arm", post(sync_arm))
        .route("/api/v2/sync/abort", post(sync_abort))
        .route("/api/v2/stop", post(stop))
        .route("/api/v2/reset", post(reset))
        .route("/api/v2/dac", put(dac))
        .fallback(fallback)
        .layer(DefaultBodyLimit::max(1024 * 1024))
        .with_state(state)
}

pub fn load_state(config_path: &Path) -> Result<AppState, String> {
    RuntimeConfig::load(config_path).map(AppState::new)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::{AgentConfig, BitstreamSpec, ProfileSpec, RuntimeConfig};
    use crate::model::{
        ClockDiagnosticPrepareRequest, ClockReference, Endpoint, MtsTargetMode, Profile,
        ProfileMode, SourceIdentity, StreamKind,
    };
    use http_body_util::BodyExt;
    use sha2::{Digest, Sha256};
    use std::os::unix::fs::PermissionsExt;
    use tempfile::TempDir;
    use tower::ServiceExt;

    fn endpoints(mode: ProfileMode) -> Vec<Endpoint> {
        (0u8..24)
            .map(|id| {
                let stream = if id < 8 {
                    StreamKind::Time
                } else {
                    StreamKind::Spec
                };
                let enabled = match mode {
                    ProfileMode::TimeOnly => stream == StreamKind::Time,
                    ProfileMode::SpecOnly => stream == StreamKind::Spec,
                    ProfileMode::TimeSpec => true,
                };
                Endpoint {
                    endpoint_id: id,
                    stream,
                    enabled,
                    destination_ip: "10.0.1.16".into(),
                    destination_mac: "08:c0:eb:d5:95:b2".into(),
                    source_port: 4000 + id as u16,
                    destination_port: 4300 + id as u16,
                }
            })
            .collect()
    }

    fn configure_request(mode: ProfileMode) -> ConfigureRequest {
        ConfigureRequest {
            bitstream_id: "test".into(),
            board_id: 1,
            clock_reference: ClockReference::External10Mhz,
            profile: Profile {
                sample_rate_msps: 160,
                mode,
                center_mhz: 200.0,
            },
            source: SourceIdentity {
                ip: "10.0.1.1".into(),
                mac: "02:00:00:00:00:01".into(),
            },
            endpoints: endpoints(mode),
        }
    }

    fn fixture(script: &str, operation_timeout_seconds: u64) -> (TempDir, AppState) {
        let temp = TempDir::new().unwrap();
        let bitstream = temp.path().join("test.bit");
        std::fs::write(&bitstream, b"bitstream").unwrap();
        let sha = hex::encode(Sha256::digest(b"bitstream"));
        let helper = temp.path().join("helper.sh");
        std::fs::write(&helper, script).unwrap();
        let mut permissions = std::fs::metadata(&helper).unwrap().permissions();
        permissions.set_mode(0o755);
        std::fs::set_permissions(&helper, permissions).unwrap();
        let config_path = temp.path().join("config.json");
        std::fs::write(&config_path, "{}").unwrap();
        let runtime = RuntimeConfig::validate(
            config_path,
            AgentConfig {
                listen: "127.0.0.1:8010".into(),
                management_interface: "lo".into(),
                python_executable: Path::new("/bin/sh").to_path_buf(),
                helper_path: helper,
                helper_pythonpath: temp.path().to_path_buf(),
                default_bitstream_id: "test".into(),
                configure_timeout_seconds: operation_timeout_seconds,
                operation_timeout_seconds,
                bitstreams: vec![BitstreamSpec {
                    id: "test".into(),
                    path: bitstream,
                    sha256: sha,
                    core_version: "0x00010034".into(),
                    mts_adc_target_latency: Some(240),
                    mts_dac_target_latency: Some(224),
                    mts_campaign: Some(crate::config::MtsCampaignProof {
                        discovery: crate::config::MtsCampaignCycles {
                            rfdc_reset: 20,
                            overlay_reload: 10,
                            lmk_reload: 10,
                            passed: 40,
                        },
                        fixed: crate::config::MtsCampaignCycles {
                            rfdc_reset: 20,
                            overlay_reload: 10,
                            lmk_reload: 10,
                            passed: 40,
                        },
                        observed_adc_max: 220,
                        observed_dac_max: 208,
                        adc_margin: 20,
                        dac_margin: 16,
                        evidence_sha256: "1".repeat(64),
                    }),
                    profiles: vec![ProfileSpec {
                        sample_rate_msps: 160,
                        modes: vec![
                            ProfileMode::TimeOnly,
                            ProfileMode::SpecOnly,
                            ProfileMode::TimeSpec,
                        ],
                    }],
                }],
            },
            true,
        )
        .unwrap();
        (temp, AppState::new(runtime))
    }

    #[test]
    fn validates_all_five_profiles_and_endpoint_shape() {
        for (bandwidth, mode) in [
            (160, ProfileMode::TimeOnly),
            (160, ProfileMode::SpecOnly),
            (160, ProfileMode::TimeSpec),
            (320, ProfileMode::TimeOnly),
            (320, ProfileMode::SpecOnly),
        ] {
            let mut request = configure_request(mode);
            request.profile.sample_rate_msps = bandwidth;
            assert!(request.validate().is_ok());
        }
        let mut invalid_320_center = configure_request(ProfileMode::TimeOnly);
        invalid_320_center.profile.sample_rate_msps = 320;
        invalid_320_center.profile.center_mhz = 100.0;
        assert!(invalid_320_center
            .validate()
            .unwrap_err()
            .contains("160..1760"));
        let mut duplicate = configure_request(ProfileMode::TimeSpec);
        duplicate.endpoints[23].endpoint_id = 22;
        assert!(duplicate.validate().unwrap_err().contains("0..23"));
        let mut wrong_stream = configure_request(ProfileMode::TimeSpec);
        wrong_stream.endpoints[0].stream = StreamKind::Spec;
        assert!(wrong_stream
            .validate()
            .unwrap_err()
            .contains("must use stream"));
        let mut bad_mask = configure_request(ProfileMode::TimeOnly);
        bad_mask.endpoints[8].enabled = true;
        assert!(bad_mask.validate().unwrap_err().contains("enable mask"));
    }

    #[test]
    fn validates_stage33_dac_first_nyquist_and_offset_bounds() {
        let request = |center_mhz: f64, rf_frequency_mhz: f64| DacRequest {
            expected_board_id: 1,
            center_mhz,
            channels: (0..8)
                .map(|channel| crate::model::DacChannel {
                    channel,
                    enabled: true,
                    rf_frequency_mhz,
                    amplitude_percent: 25.0,
                    phase_deg: 0.0,
                })
                .collect(),
        };
        assert!(request(160.0, 1.0).validate().is_ok());
        assert!(request(1760.0, 1919.999).validate().is_ok());
        assert!(request(1760.0, 1920.0)
            .validate()
            .unwrap_err()
            .contains("upper bound exclusive"));
        assert!(request(200.0, 360.001)
            .validate()
            .unwrap_err()
            .contains("+/-160"));
    }

    #[test]
    fn negative_control_accepts_frozen_external_request_profiles_only() {
        let request = |profile_id: &str| ClockDiagnosticPrepareRequest {
            expected_board_id: 1,
            profile_id: profile_id.into(),
            sample_rate_msps: 320,
            center_mhz: 1020.0,
            receiver_stream_accepting: false,
            mts_target_mode: MtsTargetMode::Fixed,
            mts_adc_target_latency: Some(756),
            mts_dac_target_latency: Some(252),
            verify_sysref_negative_control: true,
            attempt_kind: "overlay_reload".into(),
        };
        for profile_id in [
            "160m_10m_request_manual_clkin2",
            "160m_5m_request_manual_clkin2",
            "160m_10m_request_clkin2_sdclkout3_phase_15",
            "160m_5m_request_clkin2_sdclkout3_phase_15",
        ] {
            assert!(request(profile_id).validate().is_ok(), "{profile_id}");
        }
        for profile_id in [
            "160m_10m_cont_manual_clkin2",
            "160m_10m_request_manual_clkin0",
        ] {
            assert!(request(profile_id)
                .validate()
                .unwrap_err()
                .contains("external request profile"));
        }
        assert!(request("160m_10m_request_clkin2_sdclkout3_phase_32")
            .validate()
            .unwrap_err()
            .contains("not a frozen"));
    }

    #[test]
    fn catalog_paths_are_fixed_and_absolute() {
        let (_temp, state) = fixture(
            "#!/bin/sh\nread input\nprintf '{\"ok\":true,\"result\":{}}\\n'\n",
            2,
        );
        let resolved = state.runtime.bitstream("test").unwrap();
        assert_eq!(resolved.helper.mts_adc_target_latency, Some(240));
        assert_eq!(resolved.helper.mts_dac_target_latency, Some(224));
        assert!(state.runtime.bitstream("../../tmp/other.bit").is_none());
        let mut missing_target = state.runtime.config.clone();
        missing_target.bitstreams[0].mts_adc_target_latency = None;
        assert!(
            RuntimeConfig::validate(Path::new("/x").into(), missing_target, false)
                .unwrap_err()
                .contains("requires frozen non-negative ADC/DAC MTS target latencies")
        );
        let mut missing_campaign = state.runtime.config.clone();
        missing_campaign.bitstreams[0].mts_campaign = None;
        assert!(
            RuntimeConfig::validate(Path::new("/x").into(), missing_campaign, false)
                .unwrap_err()
                .contains("campaign proof")
        );
        let mut wrong_target = state.runtime.config.clone();
        wrong_target.bitstreams[0].mts_adc_target_latency = Some(241);
        assert!(
            RuntimeConfig::validate(Path::new("/x").into(), wrong_target, false)
                .unwrap_err()
                .contains("observed maxima")
        );
        let mut stale_target = state.runtime.config.clone();
        stale_target.bitstreams[0].mts_adc_target_latency = Some(230);
        stale_target.bitstreams[0]
            .mts_campaign
            .as_mut()
            .unwrap()
            .observed_adc_max = 210;
        assert!(
            RuntimeConfig::validate(Path::new("/x").into(), stale_target, false)
                .unwrap_err()
                .contains("must not reuse")
        );
        let mut config = state.runtime.config.clone();
        config.bitstreams[0].path = Path::new("relative.bit").to_path_buf();
        assert!(
            RuntimeConfig::validate(Path::new("/x").into(), config, false)
                .unwrap_err()
                .contains("absolute")
        );
    }

    #[tokio::test]
    async fn fake_helper_runs_full_http_operation_and_maps_errors() {
        let (_temp, state) = fixture(
            "#!/bin/sh\ncommand=$1\ninput=$(cat)\nif [ \"$command\" = reset ]; then printf '{\"ok\":false,\"error\":{\"code\":\"BOARD_ID_MISMATCH\",\"message\":\"wrong board\"}}\\n'; exit 3; fi\nprintf '{\"ok\":true,\"result\":{\"command\":\"%s\"}}\\n' \"$command\"\n",
            2,
        );
        let app = app(state);
        let configure = configure_request(ProfileMode::TimeSpec);
        let dac = DacRequest {
            expected_board_id: 1,
            center_mhz: 200.0,
            channels: (0..8)
                .map(|channel| crate::model::DacChannel {
                    channel,
                    enabled: true,
                    rf_frequency_mhz: 200.01,
                    amplitude_percent: 25.0,
                    phase_deg: channel as f64,
                })
                .collect(),
        };
        for (method, path, payload, expected_command) in [
            (
                "POST",
                "/api/v2/configure",
                Some(serde_json::to_value(configure).unwrap()),
                "configure",
            ),
            (
                "POST",
                "/api/v2/start",
                Some(json!({"expected_board_id": 1})),
                "start",
            ),
            ("GET", "/api/v2/status", None, "status"),
            (
                "GET",
                "/api/v2/rfdc/calibration",
                None,
                "calibration-status",
            ),
            (
                "POST",
                "/api/v2/rfdc/calibration/freeze",
                Some(json!({"expected_board_id": 1})),
                "calibration-freeze",
            ),
            (
                "POST",
                "/api/v2/rfdc/calibration/unfreeze",
                Some(json!({"expected_board_id": 1})),
                "calibration-unfreeze",
            ),
            (
                "POST",
                "/api/v2/rfdc/calibration/preview",
                Some(json!({
                    "expected_board_id": 1,
                    "training_dac_active": true,
                    "training_amplitude_percent": 100.0
                })),
                "calibration-preview",
            ),
            (
                "POST",
                "/api/v2/rfdc/calibration/train-freeze",
                Some(json!({
                    "expected_board_id": 1,
                    "training_dac_active": true,
                    "training_amplitude_percent": 100.0
                })),
                "calibration-train-freeze",
            ),
            (
                "PUT",
                "/api/v2/dac",
                Some(serde_json::to_value(dac).unwrap()),
                "set-dac",
            ),
            ("POST", "/api/v2/stop", None, "stop"),
        ] {
            let mut request = axum::http::Request::builder().method(method).uri(path);
            let body = if let Some(payload) = payload {
                request = request.header("content-type", "application/json");
                Body::from(serde_json::to_vec(&payload).unwrap())
            } else {
                Body::empty()
            };
            let response = app
                .clone()
                .oneshot(request.body(body).unwrap())
                .await
                .unwrap();
            assert_eq!(response.status(), StatusCode::OK, "{method} {path}");
            let body: Value =
                serde_json::from_slice(&response.into_body().collect().await.unwrap().to_bytes())
                    .unwrap();
            assert_eq!(body["result"]["command"], expected_command);
        }

        let request = axum::http::Request::builder()
            .method("POST")
            .uri("/api/v2/reset")
            .header("content-type", "application/json")
            .body(Body::from(r#"{"expected_board_id":1}"#))
            .unwrap();
        let response = app.oneshot(request).await.unwrap();
        assert_eq!(response.status(), StatusCode::CONFLICT);
        let body: Value =
            serde_json::from_slice(&response.into_body().collect().await.unwrap().to_bytes())
                .unwrap();
        assert_eq!(body["code"], "BOARD_ID_MISMATCH");
    }

    #[tokio::test]
    async fn v1_routes_are_not_registered() {
        let (_temp, state) = fixture(
            "#!/bin/sh\nread input\nprintf '{\"ok\":true,\"result\":{}}\\n'\n",
            2,
        );
        let retired_route = ["/api/", "v1", "/status"].concat();
        let response = app(state)
            .oneshot(
                axum::http::Request::builder()
                    .uri(retired_route)
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::NOT_FOUND);
    }

    #[tokio::test]
    async fn hardware_busy_and_timeout_are_explicit() {
        let (_temp, state) = fixture(
            "#!/bin/sh\ncat >/dev/null\nsleep 2\nprintf '{\"ok\":true,\"result\":{}}\\n'\n",
            1,
        );
        let locked = state.hardware.lock().await;
        let response = run_hardware(
            &state,
            "status",
            &state.runtime.default_bitstream().helper,
            json!({}),
            1,
        )
        .await
        .unwrap_err();
        assert_eq!(response.status, StatusCode::CONFLICT);
        assert_eq!(response.body.code, "HARDWARE_BUSY");
        drop(locked);
        let response = run_hardware(
            &state,
            "status",
            &state.runtime.default_bitstream().helper,
            json!({}),
            1,
        )
        .await
        .unwrap_err();
        assert_eq!(response.status, StatusCode::GATEWAY_TIMEOUT);
        assert_eq!(response.body.code, "PYTHON_TIMEOUT");
    }

    #[test]
    fn help_and_openapi_cover_every_public_route() {
        let value: Value = serde_json::from_str(OPENAPI_JSON).unwrap();
        for path in value["paths"].as_object().unwrap().keys() {
            assert!(HELP_HTML.contains(path), "help is missing {path}");
        }
        assert!(HELP_HTML.contains("security_mode=none"));
        assert!(HELP_HTML.contains("does not calculate packet rates"));
        assert_eq!(
            value["components"]["schemas"]["Profile"]["oneOf"]
                .as_array()
                .unwrap()
                .len(),
            2
        );
        assert_eq!(
            value["components"]["schemas"]["DacChannel"]["properties"]["rf_frequency_mhz"]
                ["exclusiveMaximum"],
            1920
        );
        assert_eq!(
            value["components"]["schemas"]["CalibrationRequest"]["properties"]
                ["training_dac_active"]["default"],
            false
        );
    }
}
