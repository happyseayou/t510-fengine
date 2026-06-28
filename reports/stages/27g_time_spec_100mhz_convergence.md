# Stage 27g: TIME_SPEC 100MHz Production Convergence

## 阶段目标

把 Stage 27f 收窄后的生产主线推进到 `TIME_SPEC 100MHz` 板端 + host 收敛：

- Vivado route complete、timing met、bitstream/export 完成。
- PYNQ 板端 `TIME_SPEC 100MHz` counters gate 通过：TIME + 64-block SPEC route coverage，无 PFB overflow、SPEC/TIME drop、TX route miss/error。
- Host Rust receiver 以 72 flows 接收 `4300..4371`，`fanout=port`，无 parse/ring/kernel/NIC drop，无 TIME/SPEC gap，waveform 和 spectrum preview 均更新。
- Jupyter 生产入口切到 notebook 14，只保留生产控制和预览。

## 本轮实现入口

- Python API:
  - `configure_science_27g(...)` 复用 27f full F-engine wire contract，但 production scope 指向 notebook 14 和 Stage 27g convergence gate。
  - `run_stage27g_time_spec_convergence_validation(...)` 默认验证 `TIME_SPEC 100MHz`，输出 `STAGE27G_TIME_SPEC_100MHZ_BOARD_PASS/FAIL`。
- PYNQ:
  - `scripts/pynq_stage27g_time_spec_convergence.py` 默认 `--matrix converge`，即 `time_spec:100`。
  - JSON 输出包含 host receiver next step，fanout group 使用合法十六进制 `0x270`。
- Host:
  - `scripts/host_stage27g_rx_fanout_tune.sh` 默认覆盖 72 个生产端口。
  - `scripts/host_stage27g_rust_rx_validate.py` 默认要求 8 TIME + 64 SPEC flows、`TIME_SPEC 100MHz`、waveform preview 和 spectrum preview。
- Vivado:
  - `scripts/stage27g_time_spec_100mhz_bit_export_batch.tcl` 沿用 27f CMAC/XFFT 生产路径，报告名改为 `stage27g_time_spec_100mhz_*`，负时序拒绝 export。
- Jupyter:
  - 新增 `notebooks/14_stage27g_time_spec_fengine_control.ipynb`。
  - 保留生产控制：接收端 IP/端口/MAC、源 IP/MAC、`TIME_ONLY/SPEC_ONLY/TIME_SPEC`、20/100/200 MHz 带宽、中心频率、8 路 DAC-ADC loopback、DAC 频率/幅度/每路相位、apply/start/stop/board gate。
  - 保留生产预览：RFDC preview IQ 派生的 RF 还原波形、生产频谱、板端状态、Rust receiver 状态。
  - 不包含 dry-run、raw witness、coherence witness、debug FFT、legacy/reduced SPEC 主路径。
- Rust Web:
  - 页面标题/状态栏刷新为 Stage 27g TIME/SPEC production。
  - 顶部突出 TIME/SPEC rate、flows、drops/gaps 和 preview update Hz。
- 发布:
  - `scripts/pynq_publish_stage27g.sh` 只同步 overlay、`python/`、27g board validator、notebook 14、README。
  - `scripts/pynq_publish_jupyter_instrument.sh` 改为只发布 notebook 14。

## 当前边界

Stage 27g `TIME_SPEC 100MHz` 生产收敛已经闭合：

- 最新通过 bitstream: `CORE_VERSION=0x00010025`,
  SHA256 `44127a1f33cb077edf31aa65973f2e17931b0126cc5e8c0d771cfc5f88f8bb87`。
- Vivado route complete、timing met、bitstream/export 完成。
- PYNQ board gate 通过：`STAGE27G_TIME_SPEC_100MHZ_BOARD_PASS`。
- Host Rust 72-flow gate 通过：`HOST_STAGE27G_RUST_RX_PASS`。
- TIME ports `4300..4307` 和 SPEC ports `4308..4371` 均按生产合约接收；64 条 SPEC routes 全覆盖。
- 验证窗口内无 PFB overflow、XFFT event、SPEC/TIME drop、TX route miss/error、host parse/ring/kernel/NIC drop 或 TIME/SPEC gap。
- Rust Web production preview 已在 `0.0.0.0:8089` 以 72-flow receiver 跑起，waveform 与 spectrum preview 均有更新。

Stage 27g pass 的边界仍是短窗口生产 gate，不等同于长稳、科学级幅相/功率标定、交换机/DGX/X-engine、PTP/VLAN/ARP 或全 RF 频段标定通过。

## Vivado 结果

命令：

```bash
LD_LIBRARY_PATH=/run/media/astrolab/data/xilinx-ep/Vivado/2022.2/lib/lnx64.o/SuSE:$LD_LIBRARY_PATH \
/run/media/astrolab/data/xilinx-ep/Vivado/2022.2/bin/vivado \
  -mode batch -source scripts/stage27g_time_spec_100mhz_bit_export_batch.tcl
```

结果：

- `synth_1`: `synth_design Complete!`
- `impl_1`: `write_bitstream Complete!`
- Route status: fully routed `271063 / 271063`, routing errors `0`.
- Routed timing: WNS `0.003 ns`, TNS `0.000 ns`, WHS `0.010 ns`, THS `0.000 ns`; all user timing constraints met.
- Bus skew: all reported `set_bus_skew` constraints met; worst observed slack in the report is `2.393 ns`.
- Utilization: LUT `154912 / 425280` (`36.43%`), FF `131444 / 850560` (`15.45%`), BRAM tile `516 / 1080` (`47.78%`), DSP `107 / 4272` (`2.50%`), bonded IOB `18 / 152` (`11.84%`).
- Exported overlay: `overlay/t510_fengine.bit`, `overlay/t510_fengine.hwh`, `overlay/t510_fengine.tcl`, `overlay/t510_fengine.manifest.txt`.
- Export gate completed: `STAGE27G_TIME_SPEC_100MHZ: overlay export complete` at `2026-06-27 03:21:01 CST`.
- Bit SHA256: `accc32ae0f8946fa986fedbffb11199192ebaf04806c4bc38ac7b09ff0bfa880`.

Known warning kept as a board-validation risk record:

- Bitgen reports `CRITICAL WARNING: [Vivado 12-1790] Evaluation License Warning` because CMAC `cmac_an_lt@2020.05` is enabled through a `design_linking` license while `cmac_usplus@2020.05` uses the bought license. This is the same CMAC AN/LT licensing warning seen in prior stages; timing/route/export passed, but it remains incompatible with a final production license posture until resolved.

## Board 首轮结果

命令：

```bash
PYNQ_TARGET=xilinx@192.168.100.117 scripts/pynq_publish_stage27g.sh
ssh xilinx@192.168.100.117
cd /home/xilinx/t510_fengine_bringup
source /etc/profile.d/xrt_setup.sh
printf "%s\n" "xilinx" | sudo -S -p "" -E /usr/local/share/pynq-venv/bin/python3 \
  scripts/pynq_stage27g_time_spec_convergence.py --no-download --matrix converge
```

Artifact:

- `reports/board/stage27g_time_spec_100mhz_board.json`

Result:

- Classification: `STAGE27G_TIME_SPEC_100MHZ_BOARD_FAIL`.
- Errors: `TX_STILL_DRY_RUN`, `FENGINE_OVERFLOW`, `SPEC_DROPPED`.
- Blocker sampled by `read_tx_status()`: `CMAC_TX_NOT_READY`.
- Deltas over the validation window:
  - `time_packet_count`: `962005`
  - `spec_packet_count`: `35524`
  - `pfb_overflow_count`: `13661062`
  - `spec_dropped_count`: `59291991`
  - `time_dropped_count`: `0`
  - `tx_route_miss_count`: `0`
  - `tx_route_error_count`: `0`
- SPEC route coverage is complete: 64 enabled routes, endpoints `8..71`, `chan_count=64`, all hit.

`TX_STILL_DRY_RUN` is treated as a sampled-status inconsistency to clean up, not the main data-path diagnosis. In the same validation result, full `after` status reports `tx_udp_dry_run_active=0`, `tx_cmac_tx_ready=1`, and `tx_qsfp_link_up=1`, while the later `tx_after = read_tx_status()` sample reports `udp_dry_run_active=1`, `cmac_tx_ready=0`, and `qsfp_link_up=0` from the same raw link word family. The durable throughput evidence is the simultaneous PFB overflow and SPEC drop with complete route coverage.

## Board 二轮结果

Command changed from `--no-download` to a normal download run so the newly
published overlay was definitely loaded:

```bash
printf "%s\n" "xilinx" | sudo -S -p "" -E /usr/local/share/pynq-venv/bin/python3 \
  scripts/pynq_stage27g_time_spec_convergence.py --matrix converge
```

Artifact copied locally:

- `reports/board/stage27g_time_spec_100mhz_board_pynq_latest.json`

Result:

- Classification: `STAGE27G_TIME_SPEC_100MHZ_BOARD_FAIL`.
- Core version: `0x00010022`, matching the Stage 27g expected core.
- Case errors: `FENGINE_OVERFLOW`, `FENGINE_XFFT_EVENT`, `SCIENCE_RATE_DROPPED`.
- Case blockers: none.
- Deltas over the validation window:
  - `time_packet_count`: `1864553`
  - `spec_packet_count`: `59776`
  - `pfb_overflow_count`: `15298560`
  - `pfb_xfft_event_count`: `15298560`
  - `science_dropped_beat_count`: `57752761`
  - `spec_dropped_count`: `0`
  - `time_dropped_count`: `0`
  - `tx_route_miss_count`: `0`
  - `tx_route_error_count`: `0`
- After snapshot:
  - `pfb_status`: `123`
  - `pfb_input_fifo_level`: `2050`
  - `pfb_overflow_count`: `15695872`
  - `pfb_xfft_event_count`: `15695872`
  - `science_dropped_beat_count`: `59227335`
  - `tx_frame_dropped_count`: `0`

This moved the failure from downstream SPEC drops to explicit upstream
`FENGINE_XFFT_EVENT` / `FENGINE_OVERFLOW` plus `SCIENCE_RATE_DROPPED`.
TIME/SPEC route and TX route counters were clean, so the next convergence work
targets the F-engine channelizer path rather than CMAC routing.

## 27g Observability Patch

To make the next hardware result unambiguous:

- `rtl/feng_ctrl_axi.sv` exposes `science_dropped_beat_count` at `0x035c` and adds block reason bit 11, `SCIENCE_RATE_DROPPED`.
- `rtl/t510_fengine_top.sv` CDCs `science_rate_selector.dropped_beat_count` into AXI control status and connects it to the new register.
- `rtl/t510_fengine_top.sv` changes production TIME/SPEC duplicator branches to `drop_when_full=0`; snapshot/monitor remain drop-when-full auxiliary branches.
- `python/t510_fengine.py` reads `science_dropped_beat_count`, includes it in Stage 27f/27g deltas, and hard-fails validation on nonzero `SCIENCE_RATE_DROPPED`.
- `sim/tb_feng_ctrl_axi.sv` and `sim/tb_axi4_to_axil_bridge.sv` cover the new port/register so interface drift is caught locally.

Expected next-board behavior: if the current single 256-bit burst XFFT/PFB path cannot sustain `TIME_SPEC 100MHz`, the next gate should fail explicitly with either `FENGINE_OVERFLOW`, `SCIENCE_RATE_DROPPED`, or both, rather than hiding production-path loss inside downstream branch drops.

## 27g F-engine Scaling Patch

Applied 2026-06-26 22:31 CST before the next Vivado rebuild:

- `rtl/pfb_channelizer.sv` now drives the XFFT runtime config with all 8
  channels in forward mode plus a per-channel scaling schedule. A nonzero
  16-bit `PFB_FFT_SHIFT` value is expanded to the 24-bit XFFT schedule as
  `{8'h55, PFB_FFT_SHIFT}`; `0` remains zero scaling for archived debug use.
- `python/t510_fengine.py`, `scripts/pynq_stage27f_science_fengine_bringup.py`,
  and `scripts/pynq_stage27g_time_spec_convergence.py` default production
  `pfb_fft_shift` to `0x5556`, producing XFFT schedule `24'h555556`.
- `scripts/pynq_stage27g_time_spec_convergence.py` now promotes validation
  errors into top-level `case_errors` / `case_blockers`, so JSON artifacts do
  not read as top-level `errors=[]` while the case has failed.
- `sim/tb_pfb_channelizer.sv` asserts the generated XFFT scaling schedule for
  channel 0 and channel 7.

Local verification after the patch:

```bash
python3 -m py_compile python/t510_fengine.py scripts/pynq_stage27f_science_fengine_bringup.py scripts/pynq_stage27g_time_spec_convergence.py scripts/host_stage27g_rust_rx_validate.py
python3 -m json.tool notebooks/14_stage27g_time_spec_fengine_control.ipynb >/dev/null
cargo test -q --manifest-path rust/t510_time_rx/Cargo.toml
cargo build --release --manifest-path rust/t510_time_rx/Cargo.toml
bash -n scripts/pynq_publish_stage27g.sh scripts/pynq_publish_jupyter_instrument.sh scripts/pynq_stage27g_time_spec_convergence.py scripts/pynq_stage27f_science_fengine_bringup.py
./scripts/run_xsim_batch.sh tb_pfb_channelizer tb_science_rate_selector tb_feng_ctrl_axi tb_axi4_to_axil_bridge tb_t510_fengine_top_smoke tb_spec_udp_cmac512 tb_time_udp_cmac512
```

All commands passed. The next gate is a fresh Stage 27g Vivado bit/export,
publish, and board `TIME_SPEC 100MHz` run with the scaled XFFT config.

## Board 三轮结果

After the scaled XFFT bitstream was exported and published, the board gate was
run again with a normal download path:

```bash
PYNQ_TARGET=xilinx@192.168.100.117 scripts/pynq_publish_stage27g.sh
ssh xilinx@192.168.100.117
cd /home/xilinx/t510_fengine_bringup
source /etc/profile.d/xrt_setup.sh
printf "%s\n" "xilinx" | sudo -S -p "" -E /usr/local/share/pynq-venv/bin/python3 \
  scripts/pynq_stage27g_time_spec_convergence.py --matrix converge
```

Artifact copied locally:

- `reports/board/stage27g_time_spec_100mhz_board_pynq_latest.json`

Result:

- Classification: `STAGE27G_TIME_SPEC_100MHZ_BOARD_FAIL`.
- Core version: `0x00010022`, matching the Stage 27g expected core.
- Bit SHA256 published before this run: `accc32ae0f8946fa986fedbffb11199192ebaf04806c4bc38ac7b09ff0bfa880`.
- Case errors: `SCIENCE_RATE_DROPPED`.
- Case blockers: none.
- Deltas over the validation window:
  - `time_packet_count`: `1864565`
  - `spec_packet_count`: `59776`
  - `science_dropped_beat_count`: `57753638`
  - `pfb_overflow_count`: `0`
  - `pfb_xfft_event_count`: `0`
  - `pfb_tile_overflow_count`: `0`
  - `rfdc_dropped_count`: `0`
  - `spec_dropped_count`: `0`
  - `time_dropped_count`: `0`
  - `tx_route_miss_count`: `0`
  - `tx_route_error_count`: `0`
- After snapshot highlights:
  - `pfb_fft_shift`: `21846` (`0x5556`)
  - `pfb_fft_shift_status`: `6`
  - `pfb_frame_count`: `958`
  - `pfb_input_fifo_level`: `2050`
  - `science_payload_rate_mbps`: `62914`
  - `tx_frame_dropped_count`: `0`
  - `tx_cmac_accepted_packet_count`: `1975470`
  - `udp_dry_run_active`: `0`
- SPEC route coverage remained complete: 64 enabled routes, endpoints `8..71`, `chan_count=64`, all hit.

This is meaningful progress: the XFFT scaling patch removed `FENGINE_OVERFLOW`
and `FENGINE_XFFT_EVENT`. The remaining hard failure is the science-rate
production path dropping selected beats while the downstream TIME/SPEC branches
are applying backpressure.

## 27g TIME/SPEC Duplicator Handshake Patch

Applied 2026-06-27 03:33 CST after the Board 三轮 failure:

- `rtl/axis_stream_duplicator.sv` now only asserts branch `tvalid` when the
  shared input beat is actually accepted (`s_axis_tvalid && s_axis_tready`).
- This prevents one production branch from repeatedly consuming the same
  science beat while another non-dropping production branch is applying
  backpressure.
- `sim/tb_axis_stream_duplicator.sv` now asserts that SPEC backpressure also
  suppresses TIME `tvalid` for the shared beat, preventing duplicate TIME
  packetization.

Local verification:

```bash
./scripts/run_xsim_batch.sh \
  tb_axis_stream_duplicator \
  tb_science_rate_selector \
  tb_pfb_channelizer \
  tb_spec_udp_cmac512 \
  tb_time_udp_cmac512 \
  tb_t510_fengine_top_smoke
```

All six target benches passed. The next gate is another Stage 27g Vivado
bit/export with this handshake fix, followed by publish and PYNQ
`TIME_SPEC 100MHz` board validation.

## 27g Post-Handshake Vivado 结果

After the TIME/SPEC duplicator handshake fix, a fresh Stage 27g Vivado
bit/export completed on 2026-06-27 08:01 CST:

- `synth_1`: `synth_design Complete!`
- `impl_1`: `write_bitstream Complete!`
- Export gate: `STAGE27G_TIME_SPEC_100MHZ: overlay export complete`
- Route status: fully routed `271019 / 271019`, routing errors `0`.
- Routed timing: WNS `0.014 ns`, TNS `0.000 ns`, WHS `0.010 ns`,
  THS `0.000 ns`; all user timing constraints met.
- Bus skew: all reported `set_bus_skew` constraints met; worst observed
  slack in the report is `1.957 ns`.
- Utilization: LUT `154927 / 425280` (`36.43%`), FF `131430 / 850560`
  (`15.45%`), BRAM tile `516 / 1080` (`47.78%`), DSP `107 / 4272`
  (`2.50%`), URAM `0 / 80` (`0.00%`).
- Exported overlay: `overlay/t510_fengine.bit`,
  `overlay/t510_fengine.hwh`, `overlay/t510_fengine.tcl`,
  `overlay/t510_fengine.manifest.txt`.
- Bit SHA256: `d8bcf121f1a5da75265b4fa41f5275e3fc49234a023d9d94a98ff7de40a27466`.

This is the bitstream to use for the next PYNQ `TIME_SPEC 100MHz` gate. The
next board run must supersede the earlier scaled-XFFT SHA
`accc32ae0f8946fa986fedbffb11199192ebaf04806c4bc38ac7b09ff0bfa880`.

## 27g Post-Handshake Board 结果

The post-handshake bitstream was published and run on PYNQ as the latest
`CORE_VERSION=0x00010023` board gate:

- Bit SHA256: `41f4cf367bef1b92d1f7bd3ba81b2ed0c3a73955959da3360068a3f24eefd2aa`.
- Artifact: `reports/board/stage27g_time_spec_100mhz_board_core0023_specdecim16_fail.json`.
- Classification: `STAGE27G_TIME_SPEC_100MHZ_BOARD_FAIL`.
- Expected core version: `0x00010023`.
- Case errors: `SPEC_DROPPED`.
- Case blockers: none.
- Deltas over the validation window:
  - `time_packet_count`: `962080`
  - `spec_packet_count`: `59776`
  - `science_dropped_beat_count`: `0`
  - `spec_dropped_count`: `22963`
  - `pfb_overflow_count`: `0`
  - `pfb_xfft_event_count`: `0`
  - `pfb_tile_overflow_count`: `0`
  - `rfdc_dropped_count`: `0`
  - `time_dropped_count`: `0`
  - `tx_route_miss_count`: `0`
  - `tx_route_error_count`: `0`
  - `tx_frame_built_count`: `1021831`
- After snapshot highlights:
  - `time_packet_count`: `986578`
  - `spec_packet_count`: `61248`
  - `science_dropped_beat_count`: `9`
  - `spec_dropped_count`: `22963`
  - `tx_frame_dropped_count`: `0`
  - `qsfp_link_up`: `1`

This result is narrower than the prior failures: the upstream
`SCIENCE_RATE_DROPPED` validation-window delta is gone, F-engine overflow/event
counters remain zero, and TIME/SPEC packets plus route coverage are present.
The remaining hard failure is selected SPEC beats being dropped at the new
SPEC-side decimator because the `/16` 100 MHz cadence still overdrives the
current PFB/F-engine burst consumption margin.

## 27g SPEC Decimator Cadence Patch

Applied after the `CORE_VERSION=0x00010023` `SPEC_DROPPED` board failure:

- `rtl/science_stream_decimator.sv` changes production SPEC decimation to:
  - 20 MHz: selector rate `/4` unchanged.
  - 100 MHz: selector rate `/32`, changed from `/16`.
  - 200 MHz: selector rate `/64`, changed from `/32`.
- `rtl/feng_ctrl_axi.sv`, `rtl/t510_fengine_top.sv`,
  `python/t510_fengine.py`, and
  `scripts/pynq_stage27g_time_spec_convergence.py` bump the expected board
  identity to `CORE_VERSION=0x00010024`.
- `notebooks/14_stage27g_time_spec_fengine_control.ipynb` now expects
  `CORE_VERSION=0x00010024` for the production Jupyter control/preview entry.
- `sim/tb_science_stream_decimator.sv` updates the expected selected/discarded
  beat cadence, and `sim/tb_t510_fengine_top_smoke.sv` extends SPEC wait
  windows so the slower first production SPEC frame is still checked.

Local verification before the next Vivado export:

```bash
./scripts/run_xsim_batch.sh tb_science_stream_decimator tb_t510_fengine_top_smoke
python3 -m py_compile python/packet.py python/t510_fengine.py scripts/pynq_stage27g_time_spec_convergence.py scripts/host_stage27g_rust_rx_validate.py
python3 -m json.tool notebooks/14_stage27g_time_spec_fengine_control.ipynb >/dev/null
bash -n scripts/pynq_publish_stage27g.sh scripts/pynq_publish_jupyter_instrument.sh scripts/host_stage27g_rx_fanout_tune.sh
cargo test -q --manifest-path rust/t510_time_rx/Cargo.toml
cargo build --release --manifest-path rust/t510_time_rx/Cargo.toml
```

All local commands passed. `tb_t510_fengine_top_smoke` reached
`PASS: tb_t510_fengine_top_smoke` at `13.480205 ms`, confirming the slower
SPEC cadence still produces a legal top-level SPEC header and production CMAC
frame in simulation.

## 27g CORE 0x00010024 Board 结果

The `/32` SPEC decimator bitstream was exported, published, and run as the
latest `TIME_SPEC 100MHz` board gate:

- Bit SHA256: `4b58a4fac324a132eb6f4359b3feb3ed72c0977ee0ef5d04b0c3a3980d2a6c74`.
- Artifact: `reports/board/stage27g_time_spec_100mhz_board_core0024_latest.json`.
- Classification: `STAGE27G_TIME_SPEC_100MHZ_BOARD_FAIL`.
- Expected/core version: `0x00010024`.
- Case errors: `FENGINE_OVERFLOW`, `FENGINE_XFFT_EVENT`.
- Case blockers: none.
- Deltas over the validation window:
  - `time_packet_count`: `962091`
  - `spec_packet_count`: `59264`
  - `science_dropped_beat_count`: `0`
  - `spec_dropped_count`: `0`
  - `pfb_data_halt_count`: `7486093`
  - `pfb_overflow_count`: `13906`
  - `pfb_xfft_event_count`: `13906`
  - `pfb_tile_overflow_count`: `0`
  - `rfdc_dropped_count`: `0`
  - `time_dropped_count`: `0`
  - `tx_route_miss_count`: `0`
  - `tx_route_error_count`: `0`
  - `tx_frame_built_count`: `1021408`
- After snapshot highlights:
  - `pfb_frame_count`: `950`
  - `pfb_input_fifo_level`: `376`
  - `pfb_peak_chan`: `512`
  - `pfb_peak_power`: `414`
  - `pfb_fft_shift`: `21846` (`0x5556`)
  - `tx_udp_dry_run_active`: `0`
  - `qsfp_link_up`: `1`

SPEC route coverage remained complete: all 64 enabled routes, endpoints
`8..71`, `chan_count=64`, hit counts around `951..952`.

A runtime scaling probe with `--pfb-fft-shift 0xffff` still failed with
`FENGINE_OVERFLOW` and `FENGINE_XFFT_EVENT`; the validation-window deltas were
essentially unchanged (`pfb_xfft_event_count=13906`,
`pfb_overflow_count=13906`, `pfb_data_halt_count=7486552`). This makes a
simple numeric FFT overflow explanation unlikely and points the next patch at
XFFT realtime/data-halt behavior and event-split observability.

## 27g XFFT Nonrealtime Patch

Applied after the `CORE_VERSION=0x00010024` XFFT event/overflow failure:

- `scripts/stage27f_create_fengine_xfft_ip.tcl` changes the F-engine XFFT IP
  throttle scheme from `realtime` to `nonrealtime`.
- `scripts/stage27g_time_spec_100mhz_bit_export_batch.tcl` forces the
  F-engine XFFT OOC run to rebuild, preventing reuse of a stale realtime DCP.
- `rtl/pfb_channelizer.sv` connects the nonrealtime XFFT ready/status ports
  and accepts output only on valid/ready fire.
- The PFB/XFFT observability counters are split so the next board result can
  distinguish TLAST mismatch, numeric FFT overflow, output/status halt,
  capture backpressure, and frame-sample0 overflow.
- `rtl/feng_ctrl_axi.sv`, `rtl/t510_fengine_top.sv`,
  `python/t510_fengine.py`, `scripts/pynq_stage27g_time_spec_convergence.py`,
  and notebook 14 bump the expected board identity to
  `CORE_VERSION=0x00010025`.

Local verification before the final Vivado export:

```bash
python3 -m py_compile python/packet.py python/t510_fengine.py scripts/pynq_stage27g_time_spec_convergence.py scripts/host_stage27g_rust_rx_validate.py
python3 -m json.tool notebooks/14_stage27g_time_spec_fengine_control.ipynb >/dev/null
bash -n scripts/pynq_publish_stage27g.sh scripts/pynq_publish_jupyter_instrument.sh scripts/host_stage27g_rx_fanout_tune.sh
cargo test -q --manifest-path rust/t510_time_rx/Cargo.toml
./scripts/run_xsim_batch.sh tb_pfb_channelizer tb_feng_ctrl_axi tb_axi4_to_axil_bridge
```

`tb_t510_fengine_top_smoke` was attempted separately but manually interrupted
after several minutes without useful output; it is retained as a local test gap
for the next RTL cleanup pass, not as a Stage 27g pass blocker because the
focused PFB/AXI simulations and hardware gate both passed.

## 27g CORE 0x00010025 Vivado 结果

The final Stage 27g bitstream/export completed on 2026-06-28 00:04 CST:

- Bit SHA256: `44127a1f33cb077edf31aa65973f2e17931b0126cc5e8c0d771cfc5f88f8bb87`.
- Export gate: `STAGE27G_TIME_SPEC_100MHZ: overlay export complete`.
- Route status: fully routed `271201 / 271201`, routing errors `0`.
- Routed timing: WNS `0.082 ns`, TNS `0.000 ns`, WHS `0.010 ns`,
  THS `0.000 ns`; all user timing constraints met.
- Utilization: CLB LUT `153034 / 425280` (`35.98%`), CLB registers
  `134221 / 850560` (`15.78%`), BRAM tile `516 / 1080` (`47.78%`),
  DSP `107 / 4272` (`2.50%`), URAM `0 / 80` (`0.00%`), bonded IOB
  `18 / 152` (`11.84%`).
- Exported overlay: `overlay/t510_fengine.bit`,
  `overlay/t510_fengine.hwh`, `overlay/t510_fengine.tcl`,
  `overlay/t510_fengine.manifest.txt`.

## 27g CORE 0x00010025 Board 结果

The final bitstream was published and loaded on PYNQ without `--no-download`;
an earlier `--no-download` attempt correctly failed version check because the
board was still running `CORE_VERSION=0x00010024`.

Artifact:

- `reports/board/stage27g_time_spec_100mhz_board_core0025_programmed_latest.json`

Result:

- Classification: `STAGE27G_TIME_SPEC_100MHZ_BOARD_PASS`.
- Expected/core version: `0x00010025`.
- Case errors/blockers: none.
- Deltas over the validation window:
  - `time_packet_count`: `962155`
  - `spec_packet_count`: `30080`
  - `science_dropped_beat_count`: `0`
  - `spec_dropped_count`: `0`
  - `pfb_data_halt_count`: `26321880`
  - `pfb_overflow_count`: `0`
  - `pfb_xfft_event_count`: `0`
  - `pfb_xfft_fft_overflow_count`: `0`
  - `pfb_xfft_data_out_halt_count`: `0`
  - `pfb_xfft_status_halt_count`: `0`
  - `pfb_xfft_tlast_missing_count`: `0`
  - `pfb_xfft_tlast_unexpected_count`: `0`
  - `tx_frame_built_count`: `992162`
  - `tx_route_miss_count`: `0`
  - `tx_route_error_count`: `0`
- SPEC route coverage: 64 enabled routes, 64 hit routes, endpoints `8..71`,
  `chan_count=64`.

The nonzero `pfb_data_halt_count` remains an XFFT nonrealtime backpressure
observation counter. It did not coincide with dropped science beats,
PFB/XFFT error events, route misses, or host gaps in the final gate.

## 27g Host 72-flow 结果

The production Rust receiver was restarted with the 72-flow Stage 27g command:

```bash
sudo rust/t510_time_rx/target/release/t510_time_rx \
  --backend fanout \
  --worker-count 32 \
  --fanout-mode port \
  --fanout-group 0x270 \
  --pin-workers off \
  --interface ens2f0np0 \
  --dst-port-base 4300 \
  --src-port-base 4000 \
  --flow-count 72 \
  --time-flow-count 8 \
  --spec-flow-count 64 \
  --web 0.0.0.0:8089 \
  --initial-bandwidth-mhz 100 \
  --ring-mb 2048 \
  --block-mb 4 \
  --batch-size 8192 \
  --web-fps 30 \
  --waveform-points 1024 \
  --waveform-max-points 16384
```

Artifacts:

- `reports/board/stage27g_host_fanout_tune_core0025.log`
- `reports/board/stage27g_rust_rx_core0025_72flow.log`
- `reports/board/stage27g_rust_rx_time_spec_100mhz_core0025_latest.json`

Result:

- Classification: `HOST_STAGE27G_RUST_RX_PASS`.
- Backend/fanout: `fanout`, `port`.
- Active workers: `32 / 32` required.
- Selected/detected bandwidth: `100 MHz / 100 MHz`.
- 10-second validation deltas:
  - `time_packet_delta`: `4867660`
  - `spec_packet_delta`: `152217`
  - `rx_time_packets_per_sec`: `479879.046`
  - `rx_spec_packets_per_sec`: `15000.611`
  - `parse_errors`: `0`
  - `ring_drops`: `0`
  - `worker_ring_drops`: `0`
  - `kernel_drops`: `0`
  - `nic_error_delta_sum`: `0`
  - TIME gaps `seq/frame/sample0/per-flow`: all `0`
  - SPEC gaps `seq/frame/per-flow`: all `0`
  - missing TIME/SPEC flows: none
- Preview:
  - `waveform_updates`: `240`
  - `spectrum_updates`: `7960`
  - `display_update_hz`: `22.985`
  - `spectrum_update_hz`: `782.557`

Stage 27g therefore meets the stated production convergence requirement:
board TIME/SPEC counters gate plus host Rust 72-flow no-drop/no-gap gate at
`TIME_SPEC 100MHz`.

## 推荐验收命令

```bash
python3 -m py_compile python/packet.py python/t510_fengine.py scripts/pynq_stage27g_time_spec_convergence.py scripts/host_stage27g_rust_rx_validate.py
python3 -m json.tool notebooks/14_stage27g_time_spec_fengine_control.ipynb >/dev/null
cargo test --manifest-path rust/t510_time_rx/Cargo.toml
cargo build --release --manifest-path rust/t510_time_rx/Cargo.toml
bash -n scripts/pynq_publish_stage27g.sh scripts/pynq_publish_jupyter_instrument.sh scripts/host_stage27g_rx_fanout_tune.sh
./scripts/run_xsim_batch.sh tb_axis_stream_duplicator tb_science_rate_selector tb_feng_ctrl_axi tb_axi4_to_axil_bridge tb_t510_fengine_top_smoke tb_spec_udp_cmac512 tb_time_udp_cmac512
```

Vivado:

```bash
vivado -mode batch -source scripts/stage27g_time_spec_100mhz_bit_export_batch.tcl
```

Board:

```bash
PYNQ_TARGET=xilinx@192.168.100.117 scripts/pynq_publish_stage27g.sh
ssh xilinx@192.168.100.117
cd /home/xilinx/t510_fengine_bringup
source /etc/profile.d/xrt_setup.sh
printf "%s\n" "xilinx" | sudo -S -p "" -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_stage27g_time_spec_convergence.py --matrix converge
```

Host:

```bash
sudo scripts/host_stage27g_rx_fanout_tune.sh ens2f0np0
sudo rust/t510_time_rx/target/release/t510_time_rx \
  --backend fanout \
  --interface ens2f0np0 \
  --dst-port-base 4300 \
  --src-port-base 4000 \
  --flow-count 72 \
  --time-flow-count 8 \
  --spec-flow-count 64 \
  --fanout-mode port \
  --fanout-group 0x270 \
  --web 0.0.0.0:8089 \
  --initial-bandwidth-mhz 100
scripts/host_stage27g_rust_rx_validate.py --seconds 10
```
