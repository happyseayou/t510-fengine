# Stage 32c Vivado build summary

- Build completed: `2026-07-26 03:06:47 +08:00`
- Vivado: `2022.2`
- Part: `xczu47dr-ffve1156-2-i`
- Top: `t510_fengine_board_top`
- Source defines:
  `T510_STAGE27H_PRODUCTION_ONLY T510_STAGE27I_ANTI_ALIAS T510_STAGE27J_PFB T510_STAGE32`
- Git HEAD at evidence capture:
  `53f46bb73a2dca3d32af86c95b02561796c1d53c`
- Worktree: dirty; the Stage 32 source changes are intentionally not represented
  by the Git HEAD alone. The bitstream SHA below is the release identity.

## Result

- `synth_1`: `synth_design Complete!`
- `impl_1`: `write_bitstream Complete!`
- Design state: fully routed
- Routable nets: 274749
- Routing errors: 0
- WNS: `+0.061 ns`
- WHS: `+0.010 ns`
- TNS/THS: `0`
- DRC error/critical-warning violations: 0
- Methodology error/critical-warning violations: 0
- Bit generation: successful

The one build-log critical warning is the pre-existing CMAC evaluation-license
warning. It is not a DRC, CDC, routing or timing failure and remains a release
licensing constraint.

## Artifact identity

| Artifact | SHA256 |
|---|---|
| `overlay/t510_fengine.bit` | `d9ce5b49f6c6dbb5c9ff47f83e07e992a953f30444c28a680723cd251914e175` |
| `overlay/t510_fengine.hwh` | `2a341b6a959ed9483b861c15eaac1d5fa708554dde6cded96613b52c0c96dca5` |
| `overlay/t510_fengine.tcl` | `0804b781a7368a3598771f7ae304f5a9ccecc4807b66a240a7747ea3bde63c6e` |

The bit header identifies design `t510_fengine_board_top`, part
`xczu47dr-ffve1156-2-i`, build date `2026/07/26`, and build time `03:06:46`.

## RFDC/clock readback from exported HWH

- PL reference: 160 MHz.
- ADC/DAC RFDC reference: 160 MHz.
- ADC/DAC sampling: 1.6000 GS/s.
- ADC decimation: 5.
- DAC interpolation: 5.
- ADC/DAC AXIS clocks: 80 MHz.

## Evidence

- `timing_summary.rpt`
- `route_status.rpt`
- `drc.rpt`
- `methodology.rpt`
- `utilization_placed.rpt`
- `clock_utilization.rpt`
- `synthesis_run.log`
- `implementation_run.log`
