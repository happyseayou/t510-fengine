use crate::model::ProfileMode;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::{HashMap, HashSet};
use std::fs::File;
use std::io::Read;
use std::path::{Path, PathBuf};

fn default_configure_timeout() -> u64 {
    180
}

fn default_operation_timeout() -> u64 {
    10
}

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct AgentConfig {
    pub listen: String,
    pub management_interface: String,
    pub python_executable: PathBuf,
    pub helper_path: PathBuf,
    pub helper_pythonpath: PathBuf,
    pub default_bitstream_id: String,
    #[serde(default = "default_configure_timeout")]
    pub configure_timeout_seconds: u64,
    #[serde(default = "default_operation_timeout")]
    pub operation_timeout_seconds: u64,
    pub bitstreams: Vec<BitstreamSpec>,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct BitstreamSpec {
    pub id: String,
    pub path: PathBuf,
    pub sha256: String,
    pub core_version: String,
    pub scaling_profile: String,
    pub pfb_output_shift: u8,
    pub coefficient_fraction_bits: u8,
    pub fft_shift: String,
    pub required_qmc_gain: f64,
    pub mts_qualifications: HashMap<String, MtsQualification>,
    pub profiles: Vec<ProfileSpec>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct MtsQualification {
    pub status: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub mts_adc_target_latency: Option<i32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub mts_dac_target_latency: Option<i32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub campaign: Option<MtsCampaignProof>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct MtsCampaignCycles {
    pub rfdc_reset: u32,
    pub overlay_reload: u32,
    pub lmk_reload: u32,
    pub passed: u32,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct MtsCampaignProof {
    pub discovery: MtsCampaignCycles,
    pub fixed: MtsCampaignCycles,
    pub observed_adc_max: i32,
    pub observed_dac_max: i32,
    pub adc_margin: i32,
    pub dac_margin: i32,
    pub latency_quantum: i32,
    pub strict_headroom_quanta: i32,
    pub dac_sysref_t1_period: i32,
    pub frozen_evidence_bounds: MtsLatencyBounds,
    pub frozen_fixed_targets: MtsLatencyTargets,
    pub dac_nominal_target: i32,
    pub dac_period_branch_ceiling: i32,
    pub dac_alignment_mode: String,
    pub dac_deterministic_target_feasible: bool,
    pub dac_deterministic_infeasible_witness: Vec<i32>,
    pub lmk_settle_seconds: MtsSettleSeconds,
    pub evidence_sha256: String,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct MtsMinMax {
    pub min: i32,
    pub max: i32,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct MtsLatencyBounds {
    pub adc: MtsMinMax,
    pub dac: MtsMinMax,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct MtsLatencyTargets {
    pub adc: i32,
    pub dac: i32,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct MtsSettleSeconds {
    pub discovery: f64,
    pub fixed: f64,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ProfileSpec {
    pub sample_rate_msps: u16,
    pub modes: Vec<ProfileMode>,
}

#[derive(Clone, Debug, Serialize)]
pub struct PublicBitstream {
    pub id: String,
    pub sha256: String,
    pub core_version: String,
    pub scaling_profile: String,
    pub pfb_output_shift: u8,
    pub coefficient_fraction_bits: u8,
    pub fft_shift: String,
    pub required_qmc_gain: f64,
    pub mts_qualifications: HashMap<String, MtsQualification>,
    pub profiles: Vec<ProfileSpec>,
}

#[derive(Clone, Debug, Serialize)]
pub struct HelperBitstream {
    pub id: String,
    pub path: PathBuf,
    pub sha256: String,
    pub core_version: String,
    pub mts_adc_target_latency: Option<i32>,
    pub mts_dac_target_latency: Option<i32>,
}

#[derive(Clone, Debug)]
pub struct ResolvedBitstream {
    pub helper: HelperBitstream,
    pub public: PublicBitstream,
}

#[derive(Clone, Debug)]
pub struct RuntimeConfig {
    pub source_path: PathBuf,
    pub config: AgentConfig,
    pub catalog: HashMap<String, ResolvedBitstream>,
}

fn sha256_file(path: &Path) -> Result<String, String> {
    let mut file = File::open(path)
        .map_err(|error| format!("cannot open bitstream {}: {error}", path.display()))?;
    let mut digest = Sha256::new();
    let mut buffer = [0u8; 1024 * 1024];
    loop {
        let count = file
            .read(&mut buffer)
            .map_err(|error| format!("cannot read bitstream {}: {error}", path.display()))?;
        if count == 0 {
            break;
        }
        digest.update(&buffer[..count]);
    }
    Ok(hex::encode(digest.finalize()))
}

fn validate_mts_qualification(
    bitstream_id: &str,
    reference: &str,
    qualification: &MtsQualification,
) -> Result<(), String> {
    match qualification.status.as_str() {
        "pending" => {
            if qualification.mts_adc_target_latency.is_some()
                || qualification.mts_dac_target_latency.is_some()
                || qualification.campaign.is_some()
            {
                return Err(format!(
                    "bitstream {bitstream_id} reference {reference} is pending but contains qualification results"
                ));
            }
            Ok(())
        }
        "qualified" => {
            let adc = qualification.mts_adc_target_latency.ok_or_else(|| {
                format!("bitstream {bitstream_id} reference {reference} has no ADC MTS target")
            })?;
            let dac = qualification.mts_dac_target_latency.ok_or_else(|| {
                format!("bitstream {bitstream_id} reference {reference} has no DAC MTS target")
            })?;
            if adc < 0 || dac < -1 {
                return Err(format!(
                    "bitstream {bitstream_id} reference {reference} has invalid MTS targets"
                ));
            }
            let campaign = qualification.campaign.as_ref().ok_or_else(|| {
                format!("bitstream {bitstream_id} reference {reference} has no MTS campaign proof")
            })?;
            for (name, cycles) in [
                ("discovery", &campaign.discovery),
                ("fixed", &campaign.fixed),
            ] {
                if cycles.rfdc_reset != 20
                    || cycles.overlay_reload != 10
                    || cycles.lmk_reload != 10
                    || cycles.passed != 40
                {
                    return Err(format!(
                        "bitstream {bitstream_id} reference {reference} {name} campaign must pass the complete 40-cycle matrix"
                    ));
                }
            }
            if campaign.adc_margin != 20
                || campaign.dac_margin != 16
                || campaign.latency_quantum != 12
                || campaign.strict_headroom_quanta != 1
                || campaign.dac_sysref_t1_period != 720
                || campaign.lmk_settle_seconds.discovery != 3.0
                || campaign.lmk_settle_seconds.fixed != 3.0
                || campaign.frozen_fixed_targets != (MtsLatencyTargets { adc, dac })
                || campaign.frozen_evidence_bounds.adc.min
                    > campaign.frozen_evidence_bounds.adc.max
                || campaign.frozen_evidence_bounds.dac.min
                    > campaign.frozen_evidence_bounds.dac.max
            {
                return Err(format!(
                    "bitstream {bitstream_id} reference {reference} has an invalid MTS campaign contract"
                ));
            }
            if campaign.evidence_sha256.len() != 64
                || hex::decode(&campaign.evidence_sha256).is_err()
            {
                return Err(format!(
                    "bitstream {bitstream_id} reference {reference} has an invalid evidence SHA256"
                ));
            }
            Ok(())
        }
        status => Err(format!(
            "bitstream {bitstream_id} reference {reference} has unknown qualification status {status}"
        )),
    }
}

impl RuntimeConfig {
    pub fn load(path: &Path) -> Result<Self, String> {
        let bytes = std::fs::read(path)
            .map_err(|error| format!("cannot read config {}: {error}", path.display()))?;
        let config: AgentConfig = serde_json::from_slice(&bytes)
            .map_err(|error| format!("invalid config {}: {error}", path.display()))?;
        Self::validate(path.to_path_buf(), config, true)
    }

    pub fn validate(
        source_path: PathBuf,
        config: AgentConfig,
        verify_hashes: bool,
    ) -> Result<Self, String> {
        let _: std::net::SocketAddr = config
            .listen
            .parse()
            .map_err(|_| "listen must be an IP socket address such as 0.0.0.0:8010")?;
        for (name, path) in [
            ("python_executable", &config.python_executable),
            ("helper_path", &config.helper_path),
            ("helper_pythonpath", &config.helper_pythonpath),
        ] {
            if !path.is_absolute() {
                return Err(format!("{name} must be an absolute path"));
            }
        }
        if config.configure_timeout_seconds == 0 || config.operation_timeout_seconds == 0 {
            return Err("timeouts must be positive".into());
        }
        if config.bitstreams.is_empty() {
            return Err("bitstreams catalog must not be empty".into());
        }
        let mut catalog = HashMap::new();
        let mut ids = HashSet::new();
        for item in &config.bitstreams {
            if item.id.trim().is_empty() || !ids.insert(item.id.clone()) {
                return Err("bitstream IDs must be non-empty and unique".into());
            }
            if !item.path.is_absolute() {
                return Err(format!("bitstream {} path must be absolute", item.id));
            }
            if item.sha256.len() != 64 || hex::decode(&item.sha256).is_err() {
                return Err(format!(
                    "bitstream {} sha256 must be 64 hex digits",
                    item.id
                ));
            }
            let core = item
                .core_version
                .strip_prefix("0x")
                .unwrap_or(&item.core_version);
            if core.len() != 8 || u32::from_str_radix(core, 16).is_err() {
                return Err(format!(
                    "bitstream {} core_version must look like 0x00010030",
                    item.id
                ));
            }
            if item.scaling_profile.trim().is_empty()
                || !item.fft_shift.starts_with("0x")
                || item.pfb_output_shift == 0
                || item.coefficient_fraction_bits == 0
                || !item.required_qmc_gain.is_finite()
                || item.required_qmc_gain <= 0.0
            {
                return Err(format!("bitstream {} has invalid digital scaling metadata", item.id));
            }
            if config.bitstreams.len() != 1 || item.id != "fengine-current" {
                return Err(
                    "the current-only catalog must contain exactly one fengine-current entry".into(),
                );
            }
            let required_references = HashSet::from(["onboard_tcxo", "external_10mhz"]);
            let actual_references: HashSet<&str> =
                item.mts_qualifications.keys().map(String::as_str).collect();
            if actual_references != required_references {
                return Err(format!(
                    "bitstream {} must declare onboard_tcxo and external_10mhz qualifications",
                    item.id
                ));
            }
            for (reference, qualification) in &item.mts_qualifications {
                validate_mts_qualification(&item.id, reference, qualification)?;
            }
            if item
                .mts_qualifications
                .get("onboard_tcxo")
                .is_none_or(|qualification| qualification.status != "qualified")
            {
                return Err(format!(
                    "bitstream {} requires a qualified onboard_tcxo profile",
                    item.id
                ));
            }
            if item.profiles.is_empty() {
                return Err(format!("bitstream {} profiles must not be empty", item.id));
            }
            if verify_hashes {
                let actual = sha256_file(&item.path)?;
                if actual != item.sha256.to_ascii_lowercase() {
                    return Err(format!(
                        "bitstream {} SHA256 mismatch: expected {}, actual {}",
                        item.id, item.sha256, actual
                    ));
                }
            }
            let public = PublicBitstream {
                id: item.id.clone(),
                sha256: item.sha256.to_ascii_lowercase(),
                core_version: item.core_version.clone(),
                scaling_profile: item.scaling_profile.clone(),
                pfb_output_shift: item.pfb_output_shift,
                coefficient_fraction_bits: item.coefficient_fraction_bits,
                fft_shift: item.fft_shift.clone(),
                required_qmc_gain: item.required_qmc_gain,
                mts_qualifications: item.mts_qualifications.clone(),
                profiles: item.profiles.clone(),
            };
            let onboard = item
                .mts_qualifications
                .get("onboard_tcxo")
                .expect("validated onboard qualification");
            let helper = HelperBitstream {
                id: item.id.clone(),
                path: item.path.clone(),
                sha256: item.sha256.to_ascii_lowercase(),
                core_version: item.core_version.clone(),
                mts_adc_target_latency: onboard.mts_adc_target_latency,
                mts_dac_target_latency: onboard.mts_dac_target_latency,
            };
            catalog.insert(item.id.clone(), ResolvedBitstream { helper, public });
        }
        if !catalog.contains_key(&config.default_bitstream_id) {
            return Err("default_bitstream_id is not present in the catalog".into());
        }
        Ok(Self {
            source_path,
            config,
            catalog,
        })
    }

    pub fn bitstream(&self, id: &str) -> Option<&ResolvedBitstream> {
        self.catalog.get(id)
    }

    pub fn default_bitstream(&self) -> &ResolvedBitstream {
        self.catalog
            .get(&self.config.default_bitstream_id)
            .expect("validated default bitstream")
    }

    pub fn ready_errors(&self) -> Vec<String> {
        let mut errors = Vec::new();
        for (name, path) in [
            ("config", &self.source_path),
            ("python", &self.config.python_executable),
            ("helper", &self.config.helper_path),
            ("helper_pythonpath", &self.config.helper_pythonpath),
        ] {
            if !path.exists() {
                errors.push(format!("{name} is unavailable: {}", path.display()));
            }
        }
        for item in self.catalog.values() {
            if !item.helper.path.is_file() {
                errors.push(format!(
                    "bitstream {} is unavailable: {}",
                    item.helper.id,
                    item.helper.path.display()
                ));
            }
        }
        errors
    }
}
