# T510 Stage 33 F-engine

Stage 33 raises every ADC and DAC tile to `3.84 GS/s`. The RFDC performs 12×
decimation/interpolation, so the complex baseband remains `320 MS/s` and both
ADC/DAC AXIS clocks remain `80 MHz`. The existing 1024-bit science bus, PFB,
TIME/SPEC packet formats, UDP ports, and Rust receiver protocol are unchanged.

## Hardware and API contract

- Target: `xczu47dr-ffve1156-2-i`
- `CORE_VERSION=0x00010033`
- ADC: `3.84 GS/s`, 12× decimation, R2C fine mixer, Nyquist zone 1
- DAC: `3.84 GS/s`, 12× interpolation, C2R fine mixer, Nyquist zone 1
- RFDC complex baseband: `320 MS/s`; `sample0` remains on this timebase
- RFDC reference: stable 160 MHz LMK profile with continuous 10 MHz SYSREF
- TIME UDP ports: `4300..4307`; SPEC UDP ports: `4308..4323`
- SPEC: 4096 channels, `16 x 256 x 1`, 8 inputs, 8192-byte payload, 4-tap PFB
- API remains `/api/v2`; compatibility names such as `FEngineConfig` and
  `sample_rate_msps` are retained

The supported profiles and complete-band first-Nyquist center limits are:

| Complex rate | Center range | TIME_ONLY | SPEC_ONLY | TIME_SPEC |
| ---: | ---: | --- | --- | --- |
| 160 MS/s | 80..1840 MHz | supported | supported | supported |
| 320 MS/s | 160..1760 MHz | supported | supported | rejected |

DAC/RF signals must satisfy `1 <= f < 1920 MHz` and remain within center ±80
MHz at 160 MS/s or center ±160 MHz at 320 MS/s. A live `/api/v2/dac` update is
accepted only when its `center_mhz` matches all eight current RFDC DAC mixer
readbacks; a mismatch returns HTTP 409.

## Main entry points

- Python control: `python.t510_control.FEngineController`
- Jupyter console: `python.t510_console.create_console`
- Board Agent: `rust/t510_board_agent`
- TIME/SPEC receiver: `rust/t510_time_rx`
- OpenAPI: `rust/t510_board_agent/assets/openapi.json`
- TIME/SPEC wire contract: `docs/t510_udp_payload_v2.md`
- Stage 33 configuration: `config/stage33/`
- Current-project Vivado preparation: `scripts/build_stage33.tcl`
- Current-project artifact export: `scripts/export_stage33_current_project.tcl`
- Export verification/latest promotion: `scripts/build_stage33.sh`
- Board release: `scripts/pynq_publish_stage33.sh`
- Receiver release: `scripts/host_publish_stage33_rx.sh`
- MTS campaign: `scripts/pynq_stage33_mts_campaign.py`
- Eight-lane RF gate: `scripts/pynq_stage33_8lane_loopback.py`
- Eight-lane RF point campaign: `scripts/pynq_stage33_rf_campaign.py`
- DAC purity point campaign: `scripts/stage33_dac_purity_matrix.py`
- Cold-start/service/resume gate: `scripts/stage33_cold_start_gate.py`
- Board/host gate: `scripts/stage33_agent_host_gate.py`
- Production matrix: `scripts/stage33_release_matrix.py`
- Stage report: `reports/stages/33_rfdc_adc_dac_3p84g_release.md`
- Offline verification: `reports/vivado/stage33/latest_only_build_submission_20260803.md`
- Deployment/evidence guide: `reports/deployment/stage33_replication_guide.md`

## MTS release gate

Retired targets `230/336` are not valid Stage 33 defaults. Run a discovery
campaign consisting of 20 RFDC resets, 10 overlay reloads, and 10 LMK reloads.
Set the ADC target to the observed maximum +20 and the DAC target to the
observed maximum +16, then repeat the same 40 cycles with fixed targets and
require 40/40 passes. The fixed report also requires identical ADC/DAC
four-tile latency and offset vectors across all 40 cycles.

`config/stage33/config.example.json` remains intentionally non-deployable until
this evidence exists. `scripts/stage33_finalize_catalog.py` validates both
reports and writes the targets, campaign proof, and the sole release bitstream
SHA into that catalog. The publish and install scripts read the SHA from the
catalog and fail closed on placeholders.

## Offline regression

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
cargo test --manifest-path rust/t510_board_agent/Cargo.toml
cargo test --manifest-path rust/t510_time_rx/Cargo.toml
scripts/run_xsim_batch.sh
```

Once the finalized candidate is on the physical board, the production matrix
provides the frozen 5×60 s smoke, 3×10 minute soak, and 60 minute all-DAC-lane
thermal campaigns:

```bash
scripts/stage33_release_matrix.py --suite smoke_60s --tag candidate1
scripts/stage33_release_matrix.py --suite soak_10m --tag candidate1
scripts/stage33_release_matrix.py --suite thermal_60m --tag candidate1
```

The matrix performs a fresh configure/MTS for each case, continuously polls
PLL/SYSREF/RFDC/data-path health, and mutes all DAC lanes after the thermal
case.

The RF acceptance entry points cover eight lanes at center frequencies 200,
960, and 1760 MHz, plus a 1.90 GHz signal, followed by the low/mid/high DAC
purity and image/spur gates. The board campaign reads its fixed targets and
candidate SHA only from the finalized catalog:

```bash
scripts/pynq_stage33_rf_campaign.py --tag candidate1
scripts/stage33_dac_purity_matrix.py --tag candidate1
scripts/stage33_cold_start_gate.py --tag candidate1
```

Vivado release acceptance additionally requires block-design validation,
synthesis, implementation, DRC, bitstream generation, non-negative WNS/WHS,
and generated RFDC metadata readback at 3.84G/12×/80 MHz. After the cleaned
candidate passes board acceptance, only its latest artifact and run state are retained.

Stage 33 is built directly in the existing `demo-ant.xpr`; no second Vivado
project is created. Through the attached Vivado GUI, source
`scripts/build_stage33.tcl`, run the existing `synth_1` and `impl_1` with the
Vivado MCP operations, and generate the bitstream. Then set a new
`T510_STAGE33_BUILD_DIR` below `build/stage33-vivado/` and source
`scripts/export_stage33_current_project.tcl`. This directory is only an
immutable artifact snapshot from the current project, not another project.
Finally run `STAGE33_BUILD_ID=<id> scripts/build_stage33.sh` to verify the
generated XCI/HWH contract and advance the Stage 33 artifact/report `latest`
symlinks.
