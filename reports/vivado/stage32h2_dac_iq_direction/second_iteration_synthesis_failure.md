# Stage 32h2 second-iteration synthesis failure

## Status

`FAIL_CORRECTED_NOT_RELAUNCHED`

## Failure

Vivado `synth_1` stopped in `synth_design` with 15 errors. The direct errors
reported that `s02_axis_tdata/tready/tvalid`, `s12_*`, `s22_*` and `s32_*` did
not exist on `t510_rfdc_bd_wrapper` while
`rtl/t510_fengine_board_top.sv` still connected all eight DAC streams.

## Root cause

An experimental change set all enabled RFDC `DAC_Data_Type` values from 0 to 1.
That selects paired I/Q analog outputs, so the generated IP legitimately reduced
eight independent real DAC output paths to four interface streams. It was not a
SystemVerilog syntax or timing failure.

## Correction and verification

- Restored all eight paths to `Data_Type=0`, `Mixer_Type=2`, `Mixer_Mode=0`,
  `Data_Width=8`, `Interpolation=5`.
- Reconnected the four external interface nets that had survived while their
  RFDC pins were temporarily absent.
- Regenerated the RFDC output products and wrapper.
- Confirmed `s00/s02/s10/s12/s20/s22/s30/s32` each appear in the wrapper and
  each BD port and RFDC pin has one interface net.
- Confirmed the restored XCI tuple matches the previous golden XCI.
- Updated the reproducible BD Tcl, test and build preflight so a four-stream
  topology is rejected before synthesis.

The run was deliberately not relaunched: after reverting the invalid RFDC
experiment there was no new hardware fix relative to the already tested first
Stage 32h2 bit. The next build must wait for evidence identifying the actual
DAC image mechanism.
