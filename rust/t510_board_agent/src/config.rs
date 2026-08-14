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
    #[serde(default)]
    pub mts_adc_target_latency: Option<i32>,
    #[serde(default)]
    pub mts_dac_target_latency: Option<i32>,
    #[serde(default)]
    pub mts_campaign: Option<MtsCampaignProof>,
    pub profiles: Vec<ProfileSpec>,
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
    pub evidence_sha256: String,
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
    pub mts_adc_target_latency: Option<i32>,
    pub mts_dac_target_latency: Option<i32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub mts_campaign: Option<MtsCampaignProof>,
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
            let core_value = u32::from_str_radix(core, 16).expect("validated core version");
            let stage34c2r_diagnostic =
                core_value == 0x0001_0035 && item.id == "fengine-0x00010035";
            let stage34e_candidate = core_value == 0x0001_0036 && item.id == "fengine-0x00010036";
            if core_value != 0x0001_0034 && !stage34c2r_diagnostic && !stage34e_candidate {
                return Err(format!(
                    "bitstream {} must use production CORE_VERSION 0x00010034, isolated Stage 34c-2R diagnostic 0x00010035, or Stage 34e candidate 0x00010036",
                    item.id
                ));
            }
            let discovery_candidate = stage34c2r_diagnostic
                || (stage34e_candidate
                    && item.mts_adc_target_latency == Some(-1)
                    && item.mts_dac_target_latency == Some(-1));
            if item.mts_adc_target_latency.is_none()
                || item.mts_dac_target_latency.is_none()
                || (!discovery_candidate
                    && (item.mts_adc_target_latency.is_some_and(|value| value < 0)
                        || item.mts_dac_target_latency.is_some_and(|value| value < 0)))
                || (discovery_candidate
                    && (item.mts_adc_target_latency != Some(-1)
                        || item.mts_dac_target_latency != Some(-1)))
            {
                return Err(if discovery_candidate {
                    format!(
                        "diagnostic candidate bitstream {} requires discovery ADC/DAC targets -1/-1",
                        item.id
                    )
                } else {
                    format!(
                        "Stage 34 bitstream {} requires frozen non-negative ADC/DAC MTS target latencies",
                        item.id
                    )
                });
            }
            if item.mts_adc_target_latency == Some(230) || item.mts_dac_target_latency == Some(336)
            {
                return Err(format!(
                    "Stage 34 bitstream {} must not reuse the retired ADC/DAC MTS targets 230/336; use newly discovered targets",
                    item.id
                ));
            }
            if !discovery_candidate {
                let campaign = item.mts_campaign.as_ref().ok_or_else(|| {
                    format!(
                        "Stage 34 bitstream {} requires an MTS discovery/fixed campaign proof",
                        item.id
                    )
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
                            "Stage 34 bitstream {} {name} MTS campaign must pass 20 RFDC reset + 10 overlay reload + 10 LMK reload cycles (40/40)",
                            item.id
                        ));
                    }
                }
                if campaign.adc_margin != 20 || campaign.dac_margin != 16 {
                    return Err(format!(
                        "Stage 34 bitstream {} MTS margins must be ADC +20 and DAC +16",
                        item.id
                    ));
                }
                if item.mts_adc_target_latency != Some(campaign.observed_adc_max + 20)
                    || item.mts_dac_target_latency != Some(campaign.observed_dac_max + 16)
                {
                    return Err(format!(
                        "Stage 34 bitstream {} MTS targets must equal observed maxima plus the frozen margins",
                        item.id
                    ));
                }
                if campaign.evidence_sha256.len() != 64
                    || hex::decode(&campaign.evidence_sha256).is_err()
                {
                    return Err(format!(
                        "Stage 34 bitstream {} MTS evidence_sha256 must be 64 hex digits",
                        item.id
                    ));
                }
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
                mts_adc_target_latency: item.mts_adc_target_latency,
                mts_dac_target_latency: item.mts_dac_target_latency,
                mts_campaign: item.mts_campaign.clone(),
                profiles: item.profiles.clone(),
            };
            let helper = HelperBitstream {
                id: item.id.clone(),
                path: item.path.clone(),
                sha256: item.sha256.to_ascii_lowercase(),
                core_version: item.core_version.clone(),
                mts_adc_target_latency: item.mts_adc_target_latency,
                mts_dac_target_latency: item.mts_dac_target_latency,
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
