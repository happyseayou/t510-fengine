# Stage 32h2 second-iteration prebuild verification

## Status

`SUPERSEDED_FALSE_SIGN_HYPOTHESIS`

The earlier PASS in this file depended on the incorrect assumption that
`DAC_Data_Type=1` meant an I/Q PL input. That assumption is rejected and the
associated synthesis failed because four DAC AXIS ports disappeared.

The project has been restored to the valid eight-path RFDC contract:

- analog output Real (`Data_Type=0`);
- Fine I/Q-to-Real mixer (`Mixer_Type=2`, `Mixer_Mode=0`);
- width 8, interpolation 5;
- eight connected 128-bit DAC AXIS interfaces.

The then-current 320-MS/s raw-spectrum diagnostic appeared to provide the
following physical evidence:

- requested 120 MHz (baseband -50 MHz): expected bin 3456, ADC0/ADC1 both peak
  at bin 640 (physical 220 MHz);
- requested 220 MHz (baseband +50 MHz): expected bin 640, ADC0/ADC1 both peak
  at bin 3456 (physical 120 MHz).

This conclusion was later falsified.  Direct raw RFDC preview after a complete
fresh CONFIGURE produced the correct `-50 MHz` raw peak for a requested
120 MHz tone in both 160 and 320 modes, while the subtraction bit globally
mirrored 120/220 MHz.  Keep the prebuild test results as an audit record, but
do not use its sign conclusion or build inputs for release.

Prebuild gates completed:

- targeted DAC DDS XSim: PASS;
- full XSim batch: PASS;
- Python: 67 PASS;
- Board Agent Rust: 5 PASS;
- receiver Rust: 36 PASS;
- `git diff --check`: PASS;
- board restored to STOP, DAC mask 0, flush clean, LMK PLL1/PLL2 locked,
  PPS recent and QSFP link up.

Evidence:

- `../../board/stage32h2_diag_320_120mhz_20260801.json`
- `../../board/stage32h2_diag_320_220mhz_20260801.json`

Build input SHA256:

| File | SHA256 |
|---|---|
| `rtl/t510_dac_loopback_source.sv` | `a390989a2c27a5ffe579704ca48d160a9d364e59d79df5bb41da105702615cbf` |
| `sim/tb_t510_dac_loopback_source.sv` | `301b72a986d25f9bb13c1f121ab0de7979f64d9bc0915d3ae6637daa8dfb11f5` |
| `python/t510_fengine.py` | `c9e1d64ceeed66a508aee6a0fda0f39db68e5ff432ccb515e4a4dce7170d8640` |
| `bd/t510_rfdc_bd.tcl` | `76234809ff3238a53382a8edc0507dfae43cdc20c7d7a39d3ab2c78ab9513b0b` |
| `tcl/stage32h2_dac_iq_direction_build_chain.tcl` | `7671a1a183f323f5e9b84f03b0ae42839541af27fd9d9f6fa813167adf60e39f` |
