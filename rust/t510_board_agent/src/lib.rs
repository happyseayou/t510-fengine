pub mod config;
pub mod model;
pub mod system;

use axum::body::Body;
use axum::extract::rejection::JsonRejection;
use axum::extract::{DefaultBodyLimit, State};
use axum::http::{header, HeaderValue, StatusCode};
use axum::response::{Html, IntoResponse, Response};
use axum::routing::{get, post, put};
use axum::{Json, Router};
use config::{HelperBitstream, RuntimeConfig};
use model::{ConfigureRequest, DacRequest, ExpectedBoardRequest, ScheduledSyncPrepareRequest};
use serde::Serialize;
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

#[derive(Clone)]
pub struct AppState {
    pub runtime: Arc<RuntimeConfig>,
    hardware: Arc<Mutex<()>>,
    request_counter: Arc<AtomicU64>,
}

impl AppState {
    pub fn new(runtime: RuntimeConfig) -> Self {
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
                "scheduled_start": true,
                "scheduled_sync_prepare_arm_abort": true,
                "full_dual_clock_pipeline_flush": true,
                "streaming_data_path_health": true,
                "automatic_stop": false,
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
    let payload: Value = serde_json::from_str(stdout.trim()).map_err(|error| {
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
        profile.bandwidth_mhz == request.profile.bandwidth_mhz
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
                "bandwidth_mhz": request.profile.bandwidth_mhz,
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
        .route("/api/v1/info", get(info))
        .route("/api/v1/capabilities", get(capabilities))
        .route("/api/v1/bitstreams", get(bitstreams))
        .route("/api/v1/status", get(status))
        .route("/api/v1/configure", post(configure))
        .route("/api/v1/start", post(start))
        .route("/api/v1/sync/status", get(sync_status))
        .route("/api/v1/sync/prepare", post(sync_prepare))
        .route("/api/v1/sync/arm", post(sync_arm))
        .route("/api/v1/sync/abort", post(sync_abort))
        .route("/api/v1/stop", post(stop))
        .route("/api/v1/reset", post(reset))
        .route("/api/v1/dac", put(dac))
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
    use crate::model::{Endpoint, Profile, ProfileMode, SourceIdentity, StreamKind};
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
            profile: Profile {
                bandwidth_mhz: 100,
                mode,
                center_mhz: 100.0,
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
                    core_version: "0x00010030".into(),
                    profiles: vec![ProfileSpec {
                        bandwidth_mhz: 100,
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
            (100, ProfileMode::TimeOnly),
            (100, ProfileMode::SpecOnly),
            (100, ProfileMode::TimeSpec),
            (200, ProfileMode::TimeOnly),
            (200, ProfileMode::SpecOnly),
        ] {
            let mut request = configure_request(mode);
            request.profile.bandwidth_mhz = bandwidth;
            assert!(request.validate().is_ok());
        }
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
    fn catalog_paths_are_fixed_and_absolute() {
        let (_temp, state) = fixture(
            "#!/bin/sh\nread input\nprintf '{\"ok\":true,\"result\":{}}\\n'\n",
            2,
        );
        assert!(state.runtime.bitstream("test").is_some());
        assert!(state.runtime.bitstream("../../tmp/other.bit").is_none());
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
            center_mhz: 100.0,
            channels: (0..8)
                .map(|channel| crate::model::DacChannel {
                    channel,
                    enabled: true,
                    rf_frequency_mhz: 100.01,
                    amplitude_percent: 25.0,
                    phase_deg: channel as f64,
                })
                .collect(),
        };
        for (method, path, payload, expected_command) in [
            (
                "POST",
                "/api/v1/configure",
                Some(serde_json::to_value(configure).unwrap()),
                "configure",
            ),
            (
                "POST",
                "/api/v1/start",
                Some(json!({"expected_board_id": 1})),
                "start",
            ),
            ("GET", "/api/v1/status", None, "status"),
            (
                "PUT",
                "/api/v1/dac",
                Some(serde_json::to_value(dac).unwrap()),
                "set-dac",
            ),
            ("POST", "/api/v1/stop", None, "stop"),
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
            .uri("/api/v1/reset")
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
    }
}
