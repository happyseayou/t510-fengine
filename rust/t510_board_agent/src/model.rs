use serde::{Deserialize, Serialize};
use std::collections::HashSet;
use std::net::Ipv4Addr;

#[derive(Clone, Copy, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum ProfileMode {
    TimeOnly,
    SpecOnly,
    TimeSpec,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Profile {
    pub bandwidth_mhz: u16,
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
    pub profile: Profile,
    pub source: SourceIdentity,
    pub endpoints: Vec<Endpoint>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ExpectedBoardRequest {
    pub expected_board_id: u16,
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
            (&self.profile.bandwidth_mhz, &self.profile.mode),
            (100, ProfileMode::TimeOnly)
                | (100, ProfileMode::SpecOnly)
                | (100, ProfileMode::TimeSpec)
                | (200, ProfileMode::TimeOnly)
                | (200, ProfileMode::SpecOnly)
        );
        if !legal_profile {
            return Err(
                "profile supports 100MHz time_only/spec_only/time_spec and 200MHz time_only/spec_only"
                    .into(),
            );
        }
        if !self.profile.center_mhz.is_finite()
            || !(50.0..=350.0).contains(&self.profile.center_mhz)
        {
            return Err("profile.center_mhz must be finite and within 50..350 MHz".into());
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
        if !self.center_mhz.is_finite() || !(50.0..=350.0).contains(&self.center_mhz) {
            return Err("center_mhz must be finite and within 50..350 MHz".into());
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
                || !(50.0..=350.0).contains(&channel.rf_frequency_mhz)
            {
                return Err(format!(
                    "channel {} rf_frequency_mhz must be within 50..350 MHz",
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
