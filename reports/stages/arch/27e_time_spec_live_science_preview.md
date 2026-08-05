# Stage 27e：TIME + SPEC Live Science Preview

## Summary

Stage 27e 在 Stage 27d 的 8-flow `TIME_ONLY` 接收闭环上，接入 `SPEC/F-engine` channel-window live preview。当前阶段目标是验证 live 链路、路由、端口 fanout 和 Rust 预览能力；SPEC payload 仍使用现有 `8192B channel-window[time][channel][input][IQ16]` 合约，不声明真实科学级 4096-channel PFB/FFT 幅相标定完成。

当前实现状态：

- RTL：TIME native 512b hot path 保留；SPEC 64b legacy frame path 接入 CMAC 512b mux。
- Routing：TX endpoint 扩到 16 个逻辑端口，默认 TIME `4300..4307`、SPEC `4308..4315`，同一默认 host `10.0.1.16`。
- Python：新增 `configure_science_live_27e(...)` 和 Stage 27e 板端 bring-up 脚本。
- Rust：单 receiver 进程接收 16 个 UDP port，UI 同时显示 TIME waveform 和 SPEC amplitude/phase。
- Mode matrix：`TIME_ONLY/SPEC_ONLY = 20/100/200MHz`；`TIME_SPEC = 20/100MHz`；`TIME_SPEC @ 200MHz` 在 Python 和 RTL status/block reason 侧拒绝。
- Vivado/bit/board：`synth_1`/`impl_1` route complete；post-route `phys_opt_design -directive AggressiveExplore` 后 timing met；27e bitstream/export 已完成并发布到 PYNQ。当前 SHA 的 smoke/full board matrix 均 PASS，`TIME_SPEC 200MHz` reject PASS。
- Host Rust preview：`TIME_SPEC 20MHz` 在 16-port fanout/ntuple 模式下 PASS；websocket probe 已实读 TIME waveform 和 SPEC 8-lane amplitude/phase binary frames。`TIME_SPEC 100MHz` 板端 PASS，但 host 100MHz no-loss/preview 严格验收仍不作为 27e 完成声明。

## Implementation

### RTL

- `rtl/t510_fengine_top.sv`
  - 保留 Stage 27d `time_udp_cmac512` native 512b TIME path。
  - 保留 `time_axis512_ddr_ring` 代码资产但不启用 DDR ring 数据面。
  - 将 `spectral_packetizer -> tx_route_selector -> udp_frame_builder` 的 64b SPEC frame 通过 `axis64_to_cmac512_async` 转成 CMAC 512b。
  - 新增三源 CMAC mux：heartbeat、native TIME、SPEC/legacy bridge frame-level round-robin。

- `rtl/feng_ctrl_axi.sv`
  - `CORE_VERSION=0x0001_001F`。
  - `N_TX_ENDPOINTS=16`。
  - 默认 endpoint：
    - TIME endpoints `0..7`: dst `4300..4307`, src `4000..4007`
    - SPEC endpoints `8..15`: dst `4308..4315`, src `4008..4015`
    - dst IP `10.0.1.16`, dst MAC `08:c0:eb:d5:95:b2`
  - 默认 SPEC routes：
    - route `0..7`, `chan0=0,64,...,448`
    - `chan_count=64`, endpoint `8..15`
  - `SCIENCE_STATUS` 增加 TIME/SPEC enable 和 `TIME_SPEC_200M_REJECTED` 语义。

### Python

- `python/t510_fengine.py`
  - 新增 `configure_science_live_27e(...)`。
  - 一次性配置 science bandwidth/mode、TIME endpoints、SPEC endpoints、TIME route、SPEC route/window、channelizer、TX control。
  - 明确拒绝 `TIME_SPEC @ 200MHz`。
  - `SPEC_LIVE_PREVIEW_NOT_READY` 不再作为旧 scaffold blocker 阻塞 27e live preview。

- `scripts/pynq_stage27e_science_live_bringup.py`
  - 支持 `smoke/full/custom` mode matrix。
  - 默认 `smoke` 覆盖 `TIME_ONLY 20/100/200`、`SPEC_ONLY 100`、`TIME_SPEC 20/100`。
  - 默认执行 `TIME_SPEC 200MHz` 拒绝验证。
  - 分类前对 TX live 状态做短重试采样，避免 `cmac_tx_ready/udp_dry_run_active` 单次过渡读数误判；JSON 保留 `tx_status_samples`。

### Rust Host Receiver

- `rust/t510_time_rx`
  - 泛化 T510 header parser，支持 `STREAM_TIME=1` 和 `STREAM_SPEC=0`。
  - 默认 `--flow-count 16 --time-flow-count 8 --spec-flow-count 8`。
  - `PACKET_FANOUT` port mode 支持 `4300..4315`。
  - SPEC decode 按 `chan0/chan_count/time_count/ninput` 解析 payload，对每个 input lane 和 frequency bin 做复数时间平均：
    - `amplitude = sqrt(I^2 + Q^2)`
    - `phase = atan2(Q, I)`
  - Web UI 新增 SPEC amplitude/phase 面板和 `/ws/spectrum` binary stream。

### Host Scripts

- `scripts/host_stage27e_rx_fanout_tune.sh`
  - 记录 ring/RSS/ntuple/queue/NIC counter/IRQ 证据。
  - 可通过 `STAGE27E_SET_NTUPLE=1` 设置 `4300..4315 -> RX queue 0..15`。
  - 推荐 receiver 命令使用 `--backend fanout --fanout-mode port --worker-count 16 --flow-count 16`。

- `scripts/host_stage27e_rust_rx_validate.py`
  - 读取 Rust `/api/state`，按 `TIME_ONLY` / `SPEC_ONLY` / `TIME_SPEC` 验证 counters。
  - 检查 per-flow TIME/SPEC packet delta、TIME/SPEC gap、parse error、ring/kernel/NIC drop/error、active workers。
  - 可选 `--require-waveform` / `--require-spectrum` 检查 websocket preview 更新。

## Validation

本地回归已通过：

```bash
python3 -m py_compile python/t510_fengine.py python/packet.py scripts/pynq_stage27e_science_live_bringup.py scripts/host_stage27e_rust_rx_validate.py
bash -n scripts/host_stage27e_rx_fanout_tune.sh
python3 scripts/pynq_stage27e_science_live_bringup.py --help
scripts/host_stage27e_rx_fanout_tune.sh --help
scripts/host_stage27e_rust_rx_validate.py --help
cargo test --manifest-path rust/t510_time_rx/Cargo.toml
cargo build --release --manifest-path rust/t510_time_rx/Cargo.toml
scripts/run_xsim_batch.sh tb_stage25_cmac_live_tx tb_feng_ctrl_axi tb_axi4_to_axil_bridge tb_tx_route_selector tb_tx_payload_witness_capture tb_time_udp_cmac512 tb_t510_fengine_top_smoke
git diff --check
```

XSim coverage now includes:

- 16 endpoint register/default coverage.
- SPEC route/window and route hit readback.
- `TIME_SPEC @ 200MHz` reject status/block reason.
- `tx_route_selector` 4-bit endpoint route meta.
- `tx_payload_witness_capture` route meta endpoint widening.
- `time_udp_cmac512` Stage 27d TIME hot-path regression.
- `axis64_to_cmac512_async` and `cmac_tx_source_mux` heartbeat/SPEC/TIME source behavior.
- top smoke SPEC Ethernet/T510 frame capture and payload witness.

Vivado closure, latest current-SHA rebuild 2026-06-24:

- Initial routed design after mux-clear rebuild was route clean but failed timing by a narrow margin: `WNS=-0.055 ns`, `TNS=-1.229 ns`, `48` failing endpoints, all in `txoutclk_out[0]`.
- Post-route `phys_opt_design -directive AggressiveExplore` closed the design without RTL changes to the TIME hot path.
- Timing report: `reports/board/stage27e_science_live_impl_timing_summary_after_postroute_physopt.rpt`
  - `WNS=+0.002 ns`, `TNS=0.000 ns`, failing endpoints `0/153149`
  - `WHS=+0.005 ns`
  - Report states: all user specified timing constraints are met.
- Route report: `reports/board/stage27e_science_live_route_status_after_postroute_physopt.rpt`
  - `128776/128776` routable nets fully routed
  - routing errors `0`
- DRC/bus skew/utilization/worst-path reports were regenerated with `after_postroute_physopt` suffix under `reports/board/`.
- `write_bitstream` completed successfully. The only critical warning observed during bitgen is the known `[Vivado 12-1790] Evaluation License Warning` for the CMAC feature set (`cmac_an_lt@2020.05 design_linking`, `cmac_usplus@2020.05 bought`). Production release must explicitly accept or resolve this license risk.

Local bitstream/export/PYNQ sync, 2026-06-24:

- Bitstream generated: `demo-ant.runs/impl_1/t510_fengine_board_top.bit`
- Bit SHA256: `97908310a04aa4a98bf790619a77fb2b20187a4e6d84ff24b2fee6966d6906f7`
- Overlay SHA256:
  - `overlay/t510_fengine.bit`: `97908310a04aa4a98bf790619a77fb2b20187a4e6d84ff24b2fee6966d6906f7`
  - `overlay/t510_fengine.hwh`: `5e6cde952e062cee76200ba5851c2bede926bff90a06435c52f23eeecf78e0be`
  - `overlay/t510_fengine.tcl`: `854f0ec83bd8cc399484da6574737746856ffed5b930596e565d69fc88f9f574`
  - `overlay/t510_fengine.manifest.txt`: `e7b8be99a88b41a4412f60b2600bf854a2c556b35db5809998c8a3bf5fd10b4b`
- Published to:
  - `xilinx@192.168.100.117:/home/xilinx/t510_fengine_bringup`
  - `xilinx@192.168.100.117:/home/xilinx/jupyter_notebooks/t510_fengine`
- Remote `overlay/t510_fengine.bit` and bring-up root `t510_fengine.bit` both matched SHA `97908310a04aa4a98bf790619a77fb2b20187a4e6d84ff24b2fee6966d6906f7`.

Board smoke/full matrix, current SHA `97908310...6906f7`:

- Smoke report: `reports/board/stage27e_science_live_board_smoke_after_mux_clear.json`
  - Overall: `STAGE27E_SCIENCE_LIVE_PASS`
  - `TIME_ONLY 20/100/200`: PASS; TIME deltas `240559 / 962217 / 1924362`
  - `SPEC_ONLY 100`: PASS; SPEC delta `95038`
  - `TIME_SPEC 20`: PASS; TIME/SPEC deltas `240547 / 73309`
  - `TIME_SPEC 100`: PASS; TIME/SPEC deltas `961311 / 94944`
  - all smoke cases: `rfdc_dropped_count=0`, `tx_frame_dropped_count=0`, route miss/error `0`, `tx_underflow=0`
  - reject check: `TIME_SPEC 200MHz` classified `STAGE27E_TIME_SPEC_200_REJECT_PASS`
- Full matrix report: `reports/board/stage27e_science_live_board_full_after_mux_clear.json`
  - Overall: `STAGE27E_SCIENCE_LIVE_PASS`, `errors=[]`
  - `TIME_ONLY 20/100/200`: PASS; TIME deltas `240549 / 987599 / 1974718`
  - `SPEC_ONLY 20/100/200`: PASS; SPEC deltas `73307 / 95032 / 99966`
  - `TIME_SPEC 20`: PASS; TIME/SPEC deltas `240538 / 73307`
  - `TIME_SPEC 100`: PASS; TIME/SPEC deltas `962166 / 95028`
  - all full cases: `rfdc_dropped_count=0`, `tx_frame_dropped_count=0`, route miss/error `0`, `tx_underflow=0`, `tx_overflow=0`
  - reject check: `TIME_SPEC 200MHz` classified `STAGE27E_TIME_SPEC_200_REJECT_PASS`
- Additional board single-case report after leaving the board in 20MHz preview mode: `reports/board/stage27e_science_live_board_time_spec_20_after_mux_clear.json`, PASS with TIME/SPEC deltas `240550 / 73310`.

Host/Rust live preview validation, current SHA:

- Host fanout evidence: `reports/board/stage27e_host_rx_fanout_tune_after_mux_clear.txt`
  - interface `ens2f0np0`, driver `mlx5_core`, MTU `9000`
  - RX/TX ring current hardware settings `8192/8192`
  - RSS has `24` combined queues
  - ntuple has `16` UDP rules steering `4300..4315 -> RX queue 0..15`
- Rust receiver validation: `reports/board/stage27e_rust_rx_time_spec_20mhz_after_mux_clear.json`
  - Overall: `HOST_STAGE27E_RUST_RX_PASS`
  - mode `TIME_SPEC`, bandwidth `20MHz`
  - backend `fanout`, fanout mode `port`, active workers `16/16`
  - TIME packets delta `727171`, SPEC packets delta `220700`
  - preview delta: `waveform_updates=150`, `display_update_hz=25.0`, `spectrum_updates=1203`, `spectrum_update_hz=199.76`
  - drop/error deltas: parse/ring/worker/kernel/NIC all `0`
  - TIME/SPEC gap deltas all `0`
- Websocket probe: `reports/board/stage27e_ws_probe_time_spec_20mhz_after_mux_clear.log`
  - `/ws/waveform`: `358` binary frames, last frame `channels=8`, `points=1024`, `selected_mhz=20`, `detected_mhz=20`, `decim=8`
  - `/ws/spectrum`: `359` binary frames, frame length `4176B`, `lane_count=8`, `bins=64`, `chan_count=64`, `time_count=4`
  - first parsed SPEC frame: `chan0=128`, `dst_port=4310`, `first_amp=138.79`, `first_phase=-1.023 rad`
  - last parsed SPEC frame: `chan0=320`, `dst_port=4313`, `first_amp=138.43`, `first_phase=1.283 rad`
  - This proves the SPEC amplitude/phase preview binary path, not scientific calibration quality.

## Board/Host Acceptance Recipe

Host NIC setup:

```bash
sudo STAGE27E_CLEAR_NTUPLE=1 STAGE27E_SET_NTUPLE=1 scripts/host_stage27e_rx_fanout_tune.sh ens2f0np0 \
  | tee reports/board/stage27e_host_rx_fanout_tune.txt
```

Rust receiver:

```bash
sudo rust/t510_time_rx/target/release/t510_time_rx \
  --backend fanout \
  --worker-count 16 \
  --fanout-mode port \
  --fanout-group 0x27e \
  --pin-workers off \
  --interface ens2f0np0 \
  --dst-port-base 4300 \
  --src-port-base 4000 \
  --flow-count 16 \
  --time-flow-count 8 \
  --spec-flow-count 8 \
  --web 0.0.0.0:8089 \
  --initial-bandwidth-mhz 100 \
  --ring-mb 1024 \
  --block-mb 4 \
  --batch-size 4096 \
  --web-fps 30 \
  --waveform-points 1024 \
  --waveform-max-points 16384
```

Board matrix:

```bash
cd /home/xilinx/t510_fengine_bringup
source /etc/profile.d/xrt_setup.sh
sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_stage27e_science_live_bringup.py \
  --no-download \
  --matrix full \
  --seconds 2 \
  --output reports/board/stage27e_science_live_board_full.json
```

Host validations, run after each matching board mode is active:

```bash
scripts/host_stage27e_rust_rx_validate.py --mode time_only --bandwidth-mhz 20 --seconds 8
scripts/host_stage27e_rust_rx_validate.py --mode time_only --bandwidth-mhz 100 --seconds 8
scripts/host_stage27e_rust_rx_validate.py --mode time_only --bandwidth-mhz 200 --seconds 8
scripts/host_stage27e_rust_rx_validate.py --mode spec_only --bandwidth-mhz 20 --seconds 8
scripts/host_stage27e_rust_rx_validate.py --mode spec_only --bandwidth-mhz 100 --seconds 8
scripts/host_stage27e_rust_rx_validate.py --mode spec_only --bandwidth-mhz 200 --seconds 8
scripts/host_stage27e_rust_rx_validate.py --mode time_spec --bandwidth-mhz 20 --seconds 8
scripts/host_stage27e_rust_rx_validate.py --mode time_spec --bandwidth-mhz 100 --seconds 8
```

For preview gates, keep the web UI open at `http://<host>:8089/` or attach websocket clients to `/ws/waveform` and `/ws/spectrum` before running:

```bash
scripts/host_stage27e_rust_rx_validate.py --mode time_spec --bandwidth-mhz 20 --seconds 8 --require-waveform --require-spectrum
```

## Boundary

Stage 27e currently proves local RTL/Python/Rust integration, Vivado route/timing closure after post-route physopt, bitstream/export, PYNQ publish, current-SHA board smoke/full matrix, and `TIME_SPEC 20MHz` host Rust live preview. It does not yet claim:

- Host no-loss PASS for `TIME_SPEC 100MHz` traffic.
- Long soak.
- Switch/DGX/X-engine path.
- ARP/VLAN/PTP.
- Real calibrated 4096-channel scientific PFB/FFT output.

The next production gate is longer soak plus host `TIME_SPEC 100MHz` receive/preview tuning under `4300..4315` ntuple steering.
