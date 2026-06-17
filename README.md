# T510 F-engine Overlay Skeleton

This repository contains a Vivado-oriented single-board T510 F-engine overlay targeting `xczu47dr-ffve1156-2-i`.

Implemented pieces:
- RTL control/status plane with a fixed AXI-Lite register map.
- Stream skeleton for `SPEC`, `TIME`, `SNAPSHOT`, and `MONITOR` branches.
- UDP packet header formatter aligned to the reference PDF semantics.
- Vivado Tcl scripts for project setup and block-design recreation.
- PYNQ-side Python wrapper and packet parsing helpers.
- An RFDC board top that instantiates a reproducible `PS + RFDC + MTS clock/sysref` block design, maps RFDC ADC output into the F-engine, and keeps a local DAC loopback source for board bring-up.
- A selectable sync policy: production default is external PPS, while lab bring-up can explicitly use software epoch or free-run.
- A configurable RFDC ADC active-port mask for single-channel bring-up without weakening the default full-input contract.

Current build targets:
- RFDC top: `t510_fengine_board_top`
- Synthetic regression top: `t510_fengine_synthetic_board_top`
- RFDC BD Tcl: `bd/t510_rfdc_bd.tcl`

Current limitations:
- The current RFDC-first bitstream has been generated and exported under `overlay/`; hardware bring-up still needs RFDC initialization from PYNQ and board testing.
- CMAC/100G is not connected yet. The board top terminates the packet AXIS internally and latches TX activity onto `pl_led3` after sync-gated streaming starts.
- The packetizers and duplicator are functional scaffolding, not a line-rate 100G implementation.
- The RFDC adapter currently consumes one 16-bit sample from each 64-bit RFDC AXIS port per beat, matching the vendor standalone ILA mapping. Default active mask is all 16 ports; lab bring-up can explicitly select ADC0-only or complex ch0.
- The repository does not include DGX-side reorder/X-engine software.

Primary entrypoints:
- Board top: `rtl/t510_fengine_board_top.sv`
- RFDC adapter: `rtl/rfdc_adc_axis_adapter.sv`
- RTL top: `rtl/t510_fengine_top.sv`
- T510 constraints: `xdc/t510_board_template.xdc`
- Project setup Tcl: `scripts/setup_project.tcl`
- Overlay export Tcl: `scripts/export_overlay.tcl`
- RFDC BD Tcl: `bd/t510_rfdc_bd.tcl`
- RTL simulation Tcl: `scripts/run_sim.tcl`
- Legacy placeholder BD Tcl: `bd/t510_fengine_bd.tcl`
- PYNQ wrapper: `python/t510_fengine.py`

Stage handoff reports:
- Architecture/status inputs live under `reports/arch/`.
- Execution state and AI handoff notes live under `reports/stages/`.
- On the PYNQ board, source XRT before running overlay scripts:
  `source /etc/profile.d/xrt_setup.sh`.

Control registers:
- `0x0020 SYNC_CONFIG`: bits `[1:0]` select `0=external_pps`, `1=software_epoch`, `2=free_run`; bits `[17:16]` record `0=external_10mhz`, `1=tcxo_10mhz`, `2=gps_10mhz`.
- `0x000c CONTROL`: bit0 arms, bit1 emits a software epoch pulse, bit2 stops, and bit3 soft-resets.
- `0x0010 STATUS`: bit0 armed, bit1 streaming, bits `[3:2]` active sync mode, bit4 waiting for epoch, bits `[11:8]` FSM state.
- `0x0350 RFDC_ACTIVE_MASK`: RFDC AXIS port mask used by the adapter. Default is `0xffff`; use `0x0001` for m00/ADC0-only bring-up or `0x0003` for current complex ch0 m00+m01.
- `0x0354 RFDC_CURRENT_VALID_MASK`: current RFDC AXIS `tvalid` bits.
- `0x0358 RFDC_SEEN_VALID_MASK`: sticky RFDC AXIS `tvalid` bits since data reset.

No-PPS lab bring-up:
- Default behavior remains `external_pps`; without PPS, `start()` arms the core but does not stream.
- For the current lab setup without PPS or external 10 MHz, call `configure_clock(ref="tcxo_10mhz")` and `set_sync_mode("free_run")` before `start()`.
- Use `set_sync_mode("software_epoch")` plus `trigger_epoch()` when you want deterministic software-controlled start without an external PPS cable.

ADC0/DAC0 loopback bring-up:
- With only ADC0 and DAC0 cabled, do not leave the active mask at `0xffff`; the final 8-complex-input default intentionally waits for every RFDC port.
- First try m00-only:
  `sudo -E python3 scripts/pynq_adc0_dac0_loopback_check.py --mask 0x1`
- If the board wiring/RFDC config presents ADC0 as complex ch0, try:
  `sudo -E python3 scripts/pynq_adc0_dac0_loopback_check.py --mask 0x3`
- A passing single-channel bring-up requires selected `current_valid_mask` bits present, `rfdc_sample_count` increasing, and free-run `streaming=1`.

RTL simulation:
- The repository includes self-checking SystemVerilog testbenches under `sim/`.
- Preferred local batch command:
  `./scripts/run_xsim_batch.sh`
- To run selected testbenches:
  `./scripts/run_xsim_batch.sh tb_time_packetizer tb_spectral_packetizer`
- You can also run them from the attached Vivado MCP session with:
  `source /home/astrolab/demo-ant/scripts/run_sim.tcl`
- The full XSim batch can take longer than the MCP tool call wait window. If the API call times out, wait for the Vivado console to finish; success is reported as `INFO: All RTL simulations passed`.
- Covered RTL behavior: AXI-Lite register reads/writes, external-PPS/software-epoch/free-run sync startup, stream duplicator drop/backpressure policy, TIME/SPEC packet headers and 8192-byte payload framing, UDP TX arbitration, a top-level mode smoke test for `spec/time/dual/snapshot`, and a board-top synthetic-data smoke test.
- Not covered yet: RFDC hard IP, CMAC/100G Ethernet, real UDP/IP framing, PL DDR, and snapshot DMA integration.

RFDC/IP build flow:
- `source /home/astrolab/demo-ant/bd/t510_rfdc_bd.tcl`
- `source /home/astrolab/demo-ant/scripts/setup_project.tcl`
- `validate_bd_design`
- `generate_target all [get_files */t510_rfdc_bd.bd]`
- Run synthesis only after RFDC BD generation has produced `t510_rfdc_bd_wrapper.v`.
- After synthesis/implementation, export PYNQ overlay metadata with:
  `source /home/astrolab/demo-ant/scripts/export_overlay.tcl`
  This writes `overlay/t510_fengine.hwh` and `overlay/t510_fengine.tcl`; `overlay/t510_fengine.bit` is copied when a bitstream exists.

Validated status:
- `sim_1` behavioral XSim: all self-checking testbenches passed.
- XDC lint: `base_clocks.xdc`, `cdc_exceptions.xdc`, and `t510_board_template.xdc` pass static lint.
- RFDC BD address map: RFDC is `0x8000_0000` / `256K`; F-engine AXI-Lite `core_s_axi` is `0x8004_0000` / `64K`.
- `synth_1`: `t510_fengine_board_top` completes with `0 errors` and `0 critical warnings`.
- `impl_1`: `write_bitstream Complete!`, `0 errors`, `0 critical warnings`; readiness check returns `READY`.
- Post-route timing passes with `WNS +1.629 ns`, `WHS +0.011 ns`, and `0/28637` failing endpoints.
- Post-place utilization is low: `13380` LUTs (`3.15%`), `12662` registers (`1.49%`), `0` BRAM, `0` DSP, and `19` bonded IOBs (`12.50%`).
- IO placement verification reports `19/19` constrained ports matched, `0` mismatches, and `0` unplaced ports.
- Exported overlay artifacts: `overlay/t510_fengine.bit`, `overlay/t510_fengine.hwh`, `overlay/t510_fengine.tcl`, and `overlay/t510_fengine.manifest.txt`.

Known non-blocking warnings:
- `qsfp0_resetl`, `qsfp0_lpmode`, `qsfp0_modsell`, `clk_main_sel`, and `iic_rst_n` are intentionally tied to constants in this RFDC-first build.
- `rfdc_adc_axis_adapter` intentionally uses only `[15:0]` from each 64-bit RFDC ADC AXIS word for the first bring-up mapping; Vivado warns that upper bits are unused.
- Bitgen reports `DRC RTSTAT-10` for unused RFDC internal status nets with no routable loads. This is expected because the first RFDC build does not expose those status buses to debug ILA or top-level pins.
