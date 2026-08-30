use serde::{Deserialize, Serialize};
use std::collections::HashSet;
use std::net::Ipv4Addr;

const RF_FIRST_NYQUIST_MIN_MHZ: f64 = 1.0;
const RF_FIRST_NYQUIST_MAX_MHZ: f64 = 1920.0;

fn center_bounds_mhz(sample_rate_msps: u16) -> Option<(f64, f64)> {
    match sample_rate_msps {
        160 => Some((80.0, 1840.0)),
        320 => Some((160.0, 1760.0)),
        _ => None,
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum ProfileMode {
    TimeOnly,
    SpecOnly,
    TimeSpec,
}

#[derive(Clone, Copy, Debug, Default, Deserialize, Serialize, PartialEq, Eq)]
pub enum ClockReference {
    #[default]
    #[serde(rename = "external_10mhz")]
    External10Mhz,
    #[serde(rename = "onboard_tcxo")]
    OnboardTcxo,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Profile {
    pub sample_rate_msps: u16,
    pub mode: ProfileMode,
    pub center_mhz: f64,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SourceIdentity {
    pub ip: String,
    pub mac: String,
}

#[derive(Clone, Copy, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum StreamKind {
    Time,
    Spec,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Endpoint {
    pub endpoint_id: u8,
    pub stream: StreamKind,
    pub enabled: bool,
    pub destination_ip: String,
    pub destination_mac: String,
    pub source_port: u16,
    pub destination_port: u16,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ConfigureRequest {
    pub bitstream_id: String,
    pub board_id: u16,
    #[serde(default)]
    pub clock_reference: ClockReference,
    pub profile: Profile,
    pub source: SourceIdentity,
    pub endpoints: Vec<Endpoint>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ExpectedBoardRequest {
    pub expected_board_id: u16,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub ocb1_transaction_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub clock_transaction_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub output_load_transaction_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub rfdc_power_transaction_id: Option<String>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct DiagnosticMutationRequest {
    pub expected_board_id: u16,
    pub receiver_stream_accepting: bool,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct OutputLoadRequest {
    pub expected_board_id: u16,
    pub receiver_stream_accepting: bool,
    pub mode: ProfileMode,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CalibrationRequest {
    pub expected_board_id: u16,
    #[serde(default)]
    pub training_dac_active: bool,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub training_amplitude_percent: Option<f64>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Ocb1Request {
    pub expected_board_id: u16,
    pub receiver_stream_accepting: bool,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub ocb1_transaction_id: Option<String>,
}

#[derive(Clone, Copy, Debug, Default, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum MtsTargetMode {
    #[default]
    Catalog,
    Discovery,
    Fixed,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ClockDiagnosticPrepareRequest {
    pub expected_board_id: u16,
    pub profile_id: String,
    pub sample_rate_msps: u16,
    pub center_mhz: f64,
    pub receiver_stream_accepting: bool,
    #[serde(default)]
    pub mts_target_mode: MtsTargetMode,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub mts_adc_target_latency: Option<i32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub mts_dac_target_latency: Option<i32>,
    #[serde(default)]
    pub verify_sysref_negative_control: bool,
    #[serde(default = "default_clock_attempt_kind")]
    pub attempt_kind: String,
}

fn default_clock_attempt_kind() -> String {
    "overlay_reload".into()
}

fn is_stage34c2_phase_profile(profile_id: &str) -> bool {
    [
        "160m_10m_request_clkin2_sdclkout3_phase_",
        "160m_5m_request_clkin2_sdclkout3_phase_",
    ]
    .iter()
    .any(|prefix| {
        profile_id.strip_prefix(prefix).is_some_and(|suffix| {
            suffix.len() == 2
                && suffix.chars().all(|value| value.is_ascii_digit())
                && suffix.parse::<u8>().is_ok_and(|value| value < 32)
        })
    })
}

fn is_external_request_profile(profile_id: &str) -> bool {
    matches!(
        profile_id,
        "160m_10m_request_manual_clkin2" | "160m_5m_request_manual_clkin2"
    ) || is_stage34c2_phase_profile(profile_id)
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ClockDiagnosticRestoreRequest {
    pub expected_board_id: u16,
    pub receiver_stream_accepting: bool,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ScheduledSyncPrepareRequest {
    pub expected_board_id: u16,
    pub generation: u64,
    pub target_pps_count: u64,
    pub epoch_tai_seconds: u64,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub first_sample0: Option<u64>,
    #[serde(default)]
    pub observation_tag: u64,
    pub signal_chain_tag: u32,
    #[serde(default)]
    pub schedule_tag: u32,
    pub mts_result_id: u32,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub ocb1_transaction_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub clock_transaction_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub output_load_transaction_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub rfdc_power_transaction_id: Option<String>,
}

#[derive(Clone, Debug, Default, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct StopRequest {
    #[serde(default)]
    pub reason: Option<String>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct DacChannel {
    pub channel: u8,
    pub enabled: bool,
    pub rf_frequency_mhz: f64,
    pub amplitude_percent: f64,
    pub phase_deg: f64,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct DacRequest {
    pub expected_board_id: u16,
    pub center_mhz: f64,
    pub channels: Vec<DacChannel>,
}

fn validate_ipv4(value: &str, field: &str) -> Result<(), String> {
    let address: Ipv4Addr = value
        .parse()
        .map_err(|_| format!("{field} must be an IPv4 address"))?;
    if address.is_unspecified() || address.is_multicast() || address == Ipv4Addr::BROADCAST {
        return Err(format!("{field} must be a unicast IPv4 address"));
    }
    Ok(())
}

fn validate_mac(value: &str, field: &str) -> Result<(), String> {
    let octets: Vec<&str> = value.split(':').collect();
    if octets.len() != 6
        || octets
            .iter()
            .any(|item| item.len() != 2 || u8::from_str_radix(item, 16).is_err())
    {
        return Err(format!(
            "{field} must use six colon-separated hexadecimal octets"
        ));
    }
    let first = u8::from_str_radix(octets[0], 16).expect("validated");
    let all_zero = octets
        .iter()
        .all(|item| u8::from_str_radix(item, 16).expect("validated") == 0);
    if all_zero || first & 0x01 != 0 {
        return Err(format!("{field} must be a non-zero unicast MAC address"));
    }
    Ok(())
}

impl ConfigureRequest {
    pub fn validate(&self) -> Result<(), String> {
        let legal_profile = matches!(
            (&self.profile.sample_rate_msps, &self.profile.mode),
            (160, ProfileMode::TimeOnly)
                | (160, ProfileMode::SpecOnly)
                | (160, ProfileMode::TimeSpec)
                | (320, ProfileMode::TimeOnly)
                | (320, ProfileMode::SpecOnly)
        );
        if !legal_profile {
            return Err(
                "Stage 34 profile supports 160MS/s time_only/spec_only/time_spec and 320MS/s time_only/spec_only"
                    .into(),
            );
        }
        let (center_min, center_max) = center_bounds_mhz(self.profile.sample_rate_msps)
            .expect("legal profile bandwidth has center bounds");
        if !self.profile.center_mhz.is_finite()
            || !(center_min..=center_max).contains(&self.profile.center_mhz)
        {
            return Err(format!(
                "profile.center_mhz must be finite and within {center_min:.0}..{center_max:.0} MHz for the {} MS/s profile",
                self.profile.sample_rate_msps
            ));
        }
        validate_ipv4(&self.source.ip, "source.ip")?;
        validate_mac(&self.source.mac, "source.mac")?;
        if self.endpoints.len() != 24 {
            return Err("endpoints must contain exactly 24 entries".into());
        }
        let mut ids = HashSet::new();
        let mut enabled_time = 0usize;
        let mut enabled_spec = 0usize;
        for endpoint in &self.endpoints {
            if endpoint.endpoint_id > 23 || !ids.insert(endpoint.endpoint_id) {
                return Err("endpoint_id values must contain 0..23 exactly once".into());
            }
            let expected = if endpoint.endpoint_id < 8 {
                StreamKind::Time
            } else {
                StreamKind::Spec
            };
            if endpoint.stream != expected {
                return Err(format!(
                    "endpoint {} must use stream {}",
                    endpoint.endpoint_id,
                    if endpoint.endpoint_id < 8 {
                        "TIME"
                    } else {
                        "SPEC"
                    }
                ));
            }
            validate_ipv4(
                &endpoint.destination_ip,
                &format!("endpoints[{}].destination_ip", endpoint.endpoint_id),
            )?;
            validate_mac(
                &endpoint.destination_mac,
                &format!("endpoints[{}].destination_mac", endpoint.endpoint_id),
            )?;
            if endpoint.source_port == 0 || endpoint.destination_port == 0 {
                return Err(format!(
                    "endpoint {} ports must be within 1..65535",
                    endpoint.endpoint_id
                ));
            }
            if endpoint.enabled {
                if endpoint.stream == StreamKind::Time {
                    enabled_time += 1;
                } else {
                    enabled_spec += 1;
                }
            }
        }
        if ids.len() != 24 {
            return Err("endpoint_id values must contain 0..23 exactly once".into());
        }
        let mask_ok = match self.profile.mode {
            ProfileMode::TimeOnly => enabled_time > 0 && enabled_spec == 0,
            ProfileMode::SpecOnly => enabled_time == 0 && enabled_spec > 0,
            ProfileMode::TimeSpec => enabled_time > 0 && enabled_spec > 0,
        };
        if !mask_ok {
            return Err("endpoint enable mask is inconsistent with profile.mode".into());
        }
        Ok(())
    }
}

impl DacRequest {
    pub fn validate(&self) -> Result<(), String> {
        if !self.center_mhz.is_finite() || !(80.0..=1840.0).contains(&self.center_mhz) {
            return Err("center_mhz must be finite and within 80..1840 MHz; hardware enforces the active 160/320 MS/s profile and RFDC mixer readback".into());
        }
        if self.channels.len() != 8 {
            return Err("channels must contain exactly 8 entries".into());
        }
        let mut ids = HashSet::new();
        for channel in &self.channels {
            if channel.channel > 7 || !ids.insert(channel.channel) {
                return Err("channel values must contain 0..7 exactly once".into());
            }
            if !channel.rf_frequency_mhz.is_finite()
                || channel.rf_frequency_mhz < RF_FIRST_NYQUIST_MIN_MHZ
                || channel.rf_frequency_mhz >= RF_FIRST_NYQUIST_MAX_MHZ
            {
                return Err(format!(
                    "channel {} rf_frequency_mhz must be within 1..1920 MHz (upper bound exclusive)",
                    channel.channel
                ));
            }
            if (channel.rf_frequency_mhz - self.center_mhz).abs() > 160.0 {
                return Err(format!(
                    "channel {} rf_frequency_mhz must be within center +/-160 MHz; hardware further enforces +/-80 MHz for the active 160 MS/s profile",
                    channel.channel
                ));
            }
            if !channel.amplitude_percent.is_finite()
                || !(0.0..=100.0).contains(&channel.amplitude_percent)
            {
                return Err(format!(
                    "channel {} amplitude_percent must be within 0..100",
                    channel.channel
                ));
            }
            if !channel.phase_deg.is_finite() || !(-180.0..=180.0).contains(&channel.phase_deg) {
                return Err(format!(
                    "channel {} phase_deg must be within -180..180",
                    channel.channel
                ));
            }
        }
        Ok(())
    }
}

impl OutputLoadRequest {
    pub fn validate(&self) -> Result<(), String> {
        if !matches!(self.mode, ProfileMode::SpecOnly | ProfileMode::TimeSpec) {
            return Err("output-load mode must be spec_only or time_spec".into());
        }
        Ok(())
    }
}

impl ScheduledSyncPrepareRequest {
    pub fn validate(&self) -> Result<(), String> {
        if self.generation == 0 {
            return Err("generation must be positive".into());
        }
        if self.target_pps_count == 0 {
            return Err("target_pps_count must be positive".into());
        }
        if self.epoch_tai_seconds == 0 {
            return Err("epoch_tai_seconds must be positive TAI seconds".into());
        }
        if self
            .first_sample0
            .is_some_and(|value| value == 0 || value & 0x3 != 0)
        {
            return Err(
                "first_sample0 must be positive and at least aligned to four raw samples; hardware applies the active-path rule"
                    .into(),
            );
        }
        if self.mts_result_id == 0 {
            return Err(
                "mts_result_id must identify the successful configure-time MTS result".into(),
            );
        }
        if self.signal_chain_tag == 0 {
            return Err("signal_chain_tag must identify the immutable configuration".into());
        }
        Ok(())
    }
}

impl ClockDiagnosticPrepareRequest {
    pub fn validate(&self) -> Result<(), String> {
        const PROFILES: [&str; 4] = [
            "160m_10m_cont_manual_clkin2",
            "160m_10m_request_manual_clkin2",
            "160m_10m_request_manual_clkin0",
            "160m_5m_request_manual_clkin2",
        ];
        let phase_profile = is_stage34c2_phase_profile(&self.profile_id);
        if !PROFILES.contains(&self.profile_id.as_str()) && !phase_profile {
            return Err("profile_id is not a frozen Stage 34c-2 diagnostic profile".into());
        }
        let (center_min, center_max) = center_bounds_mhz(self.sample_rate_msps)
            .ok_or_else(|| "sample_rate_msps must be 160 or 320".to_string())?;
        if !self.center_mhz.is_finite() || !(center_min..=center_max).contains(&self.center_mhz) {
            return Err(format!(
                "center_mhz must be finite and within {center_min:.0}..{center_max:.0} MHz for {} MS/s",
                self.sample_rate_msps
            ));
        }
        match self.mts_target_mode {
            MtsTargetMode::Fixed => {
                if self.mts_adc_target_latency.is_none_or(|value| value < 0)
                    || self.mts_dac_target_latency.is_none_or(|value| value < 0)
                {
                    return Err("fixed MTS mode requires non-negative ADC and DAC targets".into());
                }
            }
            MtsTargetMode::Catalog | MtsTargetMode::Discovery => {
                if self.mts_adc_target_latency.is_some() || self.mts_dac_target_latency.is_some() {
                    return Err("explicit MTS targets are only valid in fixed mode".into());
                }
            }
        }
        if self.verify_sysref_negative_control && !is_external_request_profile(&self.profile_id) {
            return Err(
                "SYSREF negative control is only valid for the external request profile".into(),
            );
        }
        if !matches!(self.attempt_kind.as_str(), "overlay_reload" | "rfdc_reset") {
            return Err("attempt_kind must be overlay_reload or rfdc_reset".into());
        }
        if self.verify_sysref_negative_control && self.attempt_kind != "overlay_reload" {
            return Err("SYSREF negative control requires attempt_kind=overlay_reload".into());
        }
        Ok(())
    }
}
