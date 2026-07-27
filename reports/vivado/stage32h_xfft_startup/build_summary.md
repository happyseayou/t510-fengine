# Stage 32h XFFT scheduled-start build summary

- Build completed: `2026-07-27 00:37:38 +08:00`
- Vivado: `2022.2`
- Part: `xczu47dr-ffve1156-2-i`
- Top: `t510_fengine_board_top`
- Source defines:
  `T510_STAGE27H_PRODUCTION_ONLY T510_STAGE27I_ANTI_ALIAS T510_STAGE27J_PFB T510_STAGE32`
- Git HEAD at evidence capture:
  `53f46bb73a2dca3d32af86c95b02561796c1d53c`
- Worktree: dirty; Stage 32 release identity is the bit SHA and source hashes below,
  not Git HEAD alone.

## Controlled change

Only the Stage 32 realtime XFFT startup sequencing is changed: configuration is
deferred until SPEC `enable` is asserted. UDP headers, payload sizes, ports, flow
count, PFB coefficients, FFT length and packet layout are unchanged.

| Source | SHA256 |
|---|---|
| `rtl/pfb_channelizer.sv` | `96af96658ac91c31608f77735a765f5f69d89e1d599abaa013267cdb93196c8d` |
| `sim/tb_pfb_channelizer.sv` | `cd70c139c115e5920b927426b916ff9dec66ce2fcf7aa869a29e6ae18ab14ee6` |
| `tcl/stage32h_xfft_startup_build_chain.tcl` | `1e2a706afccdbe61030abb6ab1f865b3d3e451e7ba51cc6b70b0fcb421fdb2e0` |

## Vivado result

- `synth_1`: `synth_design Complete!`, `NEEDS_REFRESH=0`.
- `impl_1`: `write_bitstream Complete!`, `NEEDS_REFRESH=0`.
- Design state: fully routed.
- Routable nets: `274888/274888`.
- Routing errors: `0`.
- WNS/TNS: `+0.012 ns / 0.000 ns`.
- WHS/THS: `+0.009 ns / 0.000 ns`.
- Setup/hold failing endpoints: `0/0`.
- Routed DRC: no error or critical-warning violations.
- Methodology: no error or critical-warning violations.
- Bit generation: successful.

The one build-log critical warning is the pre-existing Vivado
`[Vivado 12-1790]` CMAC evaluation-license metadata warning. Generated CMAC
parameters remain `C_INCLUDE_AUTO_NEG_LT_LOGIC=0` and
`C_INCLUDE_AN_LT_TX_TRAINER=0`; AN/LT is not enabled.

## Artifact identity

| Artifact | SHA256 |
|---|---|
| `overlay/t510_fengine.bit` | `8ed9289113edbe292b4031cfb3859db19db104b0019c01b2acdd64090f990e3d` |
| `overlay/t510_fengine.hwh` | `2a341b6a959ed9483b861c15eaac1d5fa708554dde6cded96613b52c0c96dca5` |
| `overlay/t510_fengine.tcl` | `0804b781a7368a3598771f7ae304f5a9ccecc4807b66a240a7747ea3bde63c6e` |

The BD and RFDC configuration did not change in this build, so the Stage 32 HWH
and BD Tcl artifacts are intentionally unchanged.

## Pre-deployment local verification

- `tb_station_sync_scheduler`: `PASS`.
- `tb_pfb_channelizer`: `PASS`.
- `tb_t510_fengine_top_smoke`: `PASS`.
- `tb_t510_fengine_board_top`: `PASS`.
- Python unit tests: `47/47 PASS`.
- `git diff --check`: `PASS`.

## Evidence

- `synthesis_run.log`
- `implementation_run.log`
- `route_status.rpt`
- `timing_summary.rpt`
- `drc.rpt`
- `methodology.rpt`
- `utilization_placed.rpt`
- `clock_utilization.rpt`
