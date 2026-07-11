# Stage 27h：TIME_SPEC 100MHz 仅 FFT 全速 SPEC 收敛

## 阶段目标

Stage 27h 接在 Stage 27g 之后，目标是移除 27g 为收敛而保留的 `/32` SPEC 节拍，把 `TIME_SPEC 100MHz` 推到仅 FFT、全速 SPEC 的生产形态。

本阶段通过条件是板端和主机同时通过：

- Vivado 完成布线、满足时序，生成比特流并导出 overlay。
- 板端加载当前生产版本 `CORE_VERSION=0x00010028`。
- 板端 `TIME_SPEC 100MHz` 下 TIME 接近 `480kpps`，SPEC 接近 `480kpps`。
- 合计 T510 UDP 载荷不低于 `63Gbps`。
- 主机 Rust 接收器以 `24` 条流接收，TIME/SPEC 均无丢包/间断，同时波形与频谱预览正常更新。

Stage 27h 的关键原则是不降低目标：不允许通过 SPEC decimation、节拍抽稀、减少流数、降低包速率或恢复 reduced SPEC 来换取验收通过。

## 生产合约

- TIME 端口：`4300..4307`。
- SPEC 端口：`4308..4323`。
- 主机流数：`24`，其中 `8` 个 TIME 流、`16` 个 SPEC 流。
- 产品 ID：`FENGINE_IQ16` (`0xf101`)。
- SPEC 载荷：`4096` 个 channel，`16` 个 block，`256` 个 channel/block，`1` 个 spectrum-time，`8` 路输入，IQ16，`8192B` 载荷加 `128B` T510 头。
- FFT-only 标识：`spec_taps=0` 且 `spec_status_flags[8]=1`。
- Stage 27h 生产通过不接受 PFB filter/delay，也不接受 SPEC decimation/thinning。

## 本轮完成

- RTL 生产 SPEC 路径改为 FFT-only：
  - `rtl/pfb_channelizer.sv` 保留兼容外壳，但在 `taps=0` 时移除 PFB filter/delay。
  - `rtl/t510_fengine_top.sv` 从生产 SPEC 路径移除 `science_stream_decimator`。
  - `rtl/spec_udp_cmac512.sv` 使用通用 block metadata，不再写死 64-channel block。
  - 初始 Stage 27h 版本为 `0x00010026`；SPEC 杂散修复短门禁版本为 `0x00010027`；SPEC 双峰修复和当前短窗口生产版本为 `0x00010028`。
- Python/PYNQ：
  - 新增 `configure_science_27h()`，默认配置 `16 x 256ch x 1 time` SPEC 路由，并拒绝 `TIME_SPEC 200MHz`。
  - 新增 `run_stage27h_time_spec_fft_fullrate_validation()`，检查核心版本、FFT-only 标志、路由覆盖、丢包/错误计数器，以及由包计数推导的载荷速率。
  - 新增板端入口 `scripts/pynq_stage27h_time_spec_fft_fullrate.py`。
- Rust 主机/Web：
  - 默认接收器切到 Stage 27h：`24` 条流、`8` 条 TIME、`16` 条 SPEC、`fanout=port`、`initial-bandwidth=100`。
  - 新增 `--spec-layout 27h|27g|auto`；默认 `27h`，会拒绝旧 `64x4` SPEC 包。
  - Web 显示 TIME 波形、FFT-only F-engine 状态、频谱、相位、功率、瀑布图、活跃流/工作线程、丢包/间断和预览刷新率。
- Jupyter：
  - 新增 `notebooks/15_stage27h_time_spec_fft_fullrate_control.ipynb`，作为生产控制加生产预览入口。
  - notebook 14 保留为 Stage 27g 归档/参考入口。
- 发布：
  - Stage 27h 发布脚本只同步 overlay、`python/`、27h 板端 validator、notebook 15 和 README。

## 本地验证

从仓库根目录运行：

```bash
python3 -m py_compile python/t510_fengine.py scripts/pynq_stage27h_time_spec_fft_fullrate.py scripts/host_stage27h_rust_rx_validate.py scripts/host_stage27e_rust_rx_validate.py
python3 -m json.tool notebooks/15_stage27h_time_spec_fft_fullrate_control.ipynb >/dev/null
bash -n scripts/pynq_publish_stage27h.sh scripts/pynq_publish_jupyter_instrument.sh scripts/host_stage27h_rx_fanout_tune.sh
cargo test -q --manifest-path rust/t510_time_rx/Cargo.toml
cargo build --release --manifest-path rust/t510_time_rx/Cargo.toml
```

硬件导出前的定向 XSim：

```bash
./scripts/run_xsim_batch.sh tb_pfb_channelizer tb_spectral_packetizer tb_spec_udp_cmac512 tb_time_udp_cmac512 tb_tx_route_selector tb_feng_ctrl_axi tb_t510_fengine_top_smoke
```

截至 2026-06-28，本地命令全部通过。定向 XSim 覆盖 FFT-only channelizer、generic spectral packetizer block metadata、16 路 SPEC UDP、TIME UDP、route selector、control AXI 和顶层 TIME/SPEC smoke。

## Vivado 与比特流结果

截至 2026-07-04 CST，Stage 27h `CORE_VERSION=0x00010028` 时序收敛和比特流导出已完成。

- 布线后时序已满足：
  - `ROUTED_WNS=+0.081ns`
  - `TNS=0.000ns`
  - `WHS=+0.009ns`
  - `THS=0.000ns`
- 比特流后时序已满足：
  - `POST_BIT_WNS=+0.081ns`
  - `POST_BIT_WHS=+0.009ns`
- 布线状态 clean：
  - `172486/172486` 条可布线网络全部完成布线
  - routing errors `0`
- 导出 overlay 比特流：
  - `overlay/t510_fengine.bit`
  - SHA256 `564e34223030ee58d1a36c65bd7817804d2d76a64160c67703870736be9767cb`

`0x00010026` 是 2026-07-01 已通过的 Stage 27h 历史基线，其 60 秒短稳结果仍保留在本报告后文；`0x00010027` 是 SPEC 杂散修复短门禁版本；当前工作区和 PYNQ 发布产物已经切到 `0x00010028`。

仍需记录的生产风险：

- Bitgen 报 Vivado `12-1790` evaluation license warning，原因是 `cmac_an_lt@2020.05` 使用 `design_linking` license；`cmac_usplus@2020.05` 使用 bought license。该 warning 未阻塞比特流生成，但最终生产 license 姿态仍需单独确认。

## 板端 10 秒验收

板端门禁产物：

- JSON：`reports/board/stage27h_time_spec_100mhz_fft_fullrate_board_10028.json`
- 分类：`STAGE27H_TIME_SPEC_100MHZ_FFT_FULLRATE_BOARD_PASS`
- `CORE_VERSION=0x00010028`
- 模式：`TIME_SPEC`
- 带宽：`100MHz`
- TIME 速率：`480600.1 pps`，T510 UDP 载荷 `31988.742656 Mbps`
- SPEC 速率：`480600.0 pps`，T510 UDP 载荷 `31988.736000 Mbps`
- 合计 T510 UDP 载荷：`63977.478656 Mbps`
- 16 条 SPEC 路由全覆盖：`chan0=0..3840`，`chan_count=256`，endpoints `8..23`
- 丢包/错误增量：RFDC `0`，science `0`，TIME `0`，SPEC `0`，TX route miss/error `0`，XFFT overflow/tlast errors `0`
- `TIME_SPEC 200MHz` 拒绝检查按预期通过：`STAGE27H_TIME_SPEC_200_REJECT_PASS`

板端命令：

```bash
cd /home/xilinx/t510_fengine_bringup
source /etc/profile.d/xrt_setup.sh
printf "%s\n" "xilinx" | sudo -S -p "" -E /usr/local/share/pynq-venv/bin/python3 \
  scripts/pynq_stage27h_time_spec_fft_fullrate.py \
    --matrix converge --seconds 10 --settle-s 0.5 \
    --output reports/board/stage27h_time_spec_100mhz_fft_fullrate_board_10028.json
```

## 主机 10 秒验收

主机门禁产物：

- JSON：`reports/board/stage27h_rust_rx_time_spec_100mhz_10028_coal32_128.json`
- 分类：`HOST_STAGE27H_RUST_RX_PASS`
- 接收器：`fanout=port`，`24` 个活跃工作线程，`8` 条 TIME 流，`16` 条 SPEC 流
- SPEC 布局：`27h`
- `last_spec_chan_count=256`
- TIME 速率：`480408.812215 pps`
- SPEC 速率：`480132.960259 pps`
- 合计 T510 UDP 载荷：`63933.660376 Mbps`
- 丢包/错误增量：parse `0`，ring `0`，worker ring `0`，kernel `0`，NIC `0`
- TIME 间断：seq/frame/sample0 全部 `0`
- SPEC 间断：seq/frame 全部 `0`
- 预览 active：
  - 波形 `200` 次更新，`19.999342 Hz`
  - 频谱 `74` 次更新，`7.998941 Hz`

主机 validator 已改成默认低侵入模式：默认只读取 before/after 两次 `/api/state`，用 10 秒窗口 delta 验收速率、drop/gap 和 preview 更新。需要诊断时可显式加 `--collect-samples` 拉取中间样本；在 `63Gbps+` 实流下频繁拉取完整 state 会造成观测扰动，不应作为生产默认门禁。

这次通过的 10 秒主机门禁使用了 `ens2f0np0` 上的生产 RX 调优：

- CPU governor 设置为 `performance`。
- NIC RX coalescing 设置为 `adaptive-rx off rx-usecs 32 rx-frames 128`。短矩阵显示 `2/32`、`4/32`、`16/64`、`32/128` 都可在 10 秒内保持 `rx_dropped=0`；`8/64` 会触发 PHY discard 和 TIME/SPEC gap，不能使用。
- 对 `ens2f0np0` 上 UDP 端口 `4300:4323` 安装 raw PREROUTING drop。这样 AF_PACKET 接收器仍能接收生产包，同时避免普通 UDP/IP stack 处理同一批包并产生 `UdpNoPorts`/ICMP 压力。
- 接收器工作线程通过 `--worker-count 24 --pin-workers auto` 自动绑核。

主机调优和接收器命令：

```bash
sudo scripts/host_stage27h_rx_fanout_tune.sh ens2f0np0

sudo rust/t510_time_rx/target/release/t510_time_rx \
  --backend fanout \
  --worker-count 24 \
  --fanout-mode port \
  --fanout-group 0x279 \
  --pin-workers auto \
  --interface ens2f0np0 \
  --dst-port-base 4300 \
  --src-port-base 4000 \
  --flow-count 24 \
  --time-flow-count 8 \
  --spec-flow-count 16 \
  --spec-layout stage27h \
  --web 0.0.0.0:8089 \
  --initial-bandwidth-mhz 100 \
  --ring-mb 2048 \
  --block-mb 4 \
  --batch-size 8192 \
  --web-fps 30 \
  --waveform-points 1024 \
  --waveform-max-points 16384
```

主机 validator 命令：

```bash
python3 scripts/host_stage27h_rust_rx_validate.py \
  --seconds 10 --poll-interval 0.5 \
  --no-post-config \
  --output reports/board/stage27h_rust_rx_time_spec_100mhz_10028_coal32_128.json
```

至此，Stage 27h `TIME_SPEC 100MHz` 仅 FFT、全速 SPEC 的 `0x00010028` 短窗口生产收敛已经闭合。剩余工作是重复 `0x00010028` 的 60 秒/长时间 soak、SPEC 频谱形态复测和下游科学系统集成，不是放宽 Stage 27h 的速率门槛。

## 60 秒短稳验证

以下 60 秒短稳结果来自 `0x00010026` Stage 27h 历史基线；`0x00010028` 已完成 10 秒短窗口门禁，仍需重复 60 秒、10 分钟、1 小时和过夜 soak。

板端 60 秒门禁：

- JSON：`reports/board/stage27h_time_spec_100mhz_fft_fullrate_board_60s_20260701.json`
- 分类：`STAGE27H_TIME_SPEC_100MHZ_FFT_FULLRATE_BOARD_PASS`
- TIME 速率：`480463.233333 pps`，T510 UDP 载荷 `31979.632811 Mbps`
- SPEC 速率：`480463.216667 pps`，T510 UDP 载荷 `31979.631701 Mbps`
- 合计 T510 UDP 载荷：`63959.264512 Mbps`
- 16 条 SPEC 路由全覆盖，endpoints `8..23`
- 丢包/错误增量：RFDC `0`，science `0`，TIME `0`，SPEC `0`，TX route miss/error `0`，XFFT overflow/tlast errors `0`

主机 60 秒门禁：

- JSON：`reports/board/stage27h_rust_rx_time_spec_100mhz_60s_tuned_retry2_20260701.json`
- 分类：`HOST_STAGE27H_RUST_RX_PASS`
- TIME 速率：`479915.879466 pps`
- SPEC 速率：`480019.947596 pps`
- 合计 T510 UDP 载荷：`63893.328649 Mbps`
- 丢包/错误增量：parse `0`，ring `0`，worker ring `0`，kernel `0`，NIC `0`
- TIME 间断：seq/frame/sample0 全部 `0`
- SPEC 间断：seq/frame 全部 `0`
- 预览 active：
  - 波形 `1525` 次更新，`24.999982 Hz`
  - 频谱 `24056` 次更新，`399.507828 Hz`
- 选择/检测带宽：`100MHz` / `100MHz`

历史 `0x00010026` 60 秒主机门禁使用过以下调优；当前 `0x00010028` 短窗口主机门禁在此基础上把 `scripts/host_stage27h_rx_fanout_tune.sh` 的默认 RX coalescing 更新为 `32us/128 frames`：

- CPU governor：`performance`
- raw PREROUTING drop：生产 UDP 端口 `4300..4323`
- netdev budget/backlog：`1000`、`8000us`、`250000`
- 历史 RX coalescing：`1us/16 frames`
- 当前 `0x00010028` RX coalescing：`32us/128 frames`
- fanout 工作线程：`24` 个并自动绑核

早期 60 秒尝试失败时没有降低 27h 数据目标：

- 一次运行出现 `/sys/class/net` 的 `rx_dropped=14`，但 ethtool 丢包计数器未增长，生产 TIME/SPEC 间断仍为 `0`。
- 一次运行中接收器显示配置被外部切到 `200MHz`，导致选择/检测带宽不一致，并让 TIME `sample0` 间断统计失效；当时 seq/frame 间断仍为 `0`。

`0x00010026` 的 60 秒短稳验证已闭合，但它不能替代 `0x00010028` 的 60 秒复测，也不能替代 10 分钟、1 小时或过夜 soak。

## 当前边界

Stage 27h 可以声明：

- `TIME_SPEC 100MHz` 仅 FFT、全速 SPEC 生产路径已经通过 Vivado 时序和比特流导出。
- 当前 `0x00010028` 板端 10 秒门禁和主机 24 流 10 秒门禁均通过。
- 历史 `0x00010026` 板端和主机 60 秒短稳验证均通过，可作为 27h 全速路径短稳基线，但仍需在 `0x00010028` 上重复。
- TIME 与 SPEC 均接近 `480kpps`。
- 合计 T510 UDP 载荷稳定超过 `63Gbps`。
- 波形与频谱预览在主机 Web/Jupyter 生产路径中可用。
- Rust Web 与 notebook 15 的生产显示已经收紧为真实数据视图：TIME 波形来自真实 IQ 样点的 RF 等效重建，SPEC 频谱/瀑布来自完整 `16/16` block 的 FFT-only snapshot，SPEC 相位面板显示固定 target bin 上各通道相对参考通道的滚动相位历史。

Stage 27h 不能声明：

- 10 分钟、1 小时、过夜长稳已经完成。
- `0x00010028` 的 60 秒、10 分钟、1 小时或过夜 soak 已经完成。
- 科学级 4-tap PFB 幅相/功率标定完成。
- FFT-only 频谱已经等价于最终科学 PFB 产品。
- 交换机、DGX/X-engine、ARP/VLAN/PTP 或全 RF 频段标定通过。
- 生产 license 风险已经最终解决。

## SPEC 杂散修复 0x00010027

截至 2026-07-04 CST，当前工作区在已通过的 `0x00010026` Stage 27h 基线之上完成 `CORE_VERSION=0x00010027` 修复，用于处理 FFT-only SPEC 频谱中 DAC amplitude 置 0 后仍可见的确定性杂散/台阶。`0x00010027` 已完成 Vivado timing/bitstream、PYNQ 发布、10 秒板端门禁和 10 秒主机 24-flow 门禁，成为当前短窗口生产版本；`0x00010026` 仍保留为已有 60 秒短稳历史基线。

本轮 RTL 修复不改变 Stage 27h 的生产目标：TIME `4300..4307`、SPEC `4308..4323`、`24` flows、`16 x 256ch x 1 time`、TIME/SPEC 各约 `480kpps`、合计 T510 UDP 载荷 `63Gbps+`，并且不恢复 PFB、decimation 或 thinning。

修复点：

- XFFT 配置布局收紧为每 lane 一个 `12-bit` scale schedule slot。Stage 27h 使用单通道 lane XFFT，wrapper 实际只消费 `{3'b0, scale_schedule[11:0], fwd_inv}`；旧 `24-bit` slot 写法会让 8 lane 的缩放字段布局和 wrapper 消费格式不一致。
- Stage 27h 默认 FFT scale schedule 改为 `0x0556`，Python/PYNQ/notebook/control AXI 均限制为 `12-bit` 范围，避免继续向 27h 生产路径写入旧 `0x5556/0x0aab` 形式。
- Stage 27h lane XFFT IP 生成脚本改为 `convergent_rounding`，避免截断 rounding 在低幅度/零输入附近形成固定偏置。
- FFT output packer 改为使用 XFFT `tuser[11:0]` 中的 bin 低位决定 4-cell pack slot，并在每个 4-cell beat 的第一个 cell 清空 `pack_word`。若 XFFT bin slot 和本地 pack 状态不一致，会计入 `xfft_event_count/overflow_count`，避免旧 cell 残留或 bin 顺序异常静默进入 SPEC 包。
- 新增 zero-input XSim gate：FFT-only channelizer 在全零输入下必须输出全零 SPEC word，且 `frame_count=1`、`overflow_count=0`、`xfft_event_count=0`。

本地已通过的检查：

```bash
T510_USE_SIM_FFT_MODEL=0 EXTRA_XVLOG_DEFINES=T510_STAGE27H_PRODUCTION_ONLY ./scripts/run_xsim_batch.sh tb_xfft_8lane_config_wrapper
EXTRA_XVLOG_DEFINES=T510_STAGE27H_PRODUCTION_ONLY ./scripts/run_xsim_batch.sh tb_pfb_channelizer tb_science_rate_selector tb_feng_ctrl_axi tb_axi4_to_axil_bridge tb_t510_fengine_top_smoke
```

硬件已通过的 `0x00010027` 门禁：

- Vivado route/write_bitstream：`POST_BIT_WNS=+0.020ns`、`POST_BIT_WHS=+0.010ns`，bit SHA256 `989c3268daf9f91abed40a1323b7a16dbe7bd84aeee4f731975725b78be68051`。
- 板端 10 秒 `TIME_SPEC 100MHz`：TIME `480476.4 pps`，SPEC `480476.3 pps`，合计 T510 UDP 载荷 `63961.011712 Mbps`，16 条 SPEC route 全覆盖，RFDC/science/TIME/SPEC/TX/XFFT 错误增量为 0。
- 主机 10 秒 24-flow receive：TIME `480529.937767 pps`，SPEC `480044.064549 pps`，合计 T510 UDP 载荷 `63935.805594 Mbps`，parse/ring/kernel/NIC drop 和 TIME/SPEC gap 增量为 0，波形与频谱 preview 均 active。

`0x00010027` 已证明全速吞吐和短门禁闭合，但后续实流 UI 检查又观察到 SPEC 频谱双峰，因此不能把 `0x00010027` 直接推进为最终 soak 对象；当前已切到下面的 `0x00010028` 候选修复并完成硬门禁，仍需补实流频谱形态复测。

## SPEC 双峰修复候选 0x00010028

截至 2026-07-04 CST，针对 `0x00010027` 实流频谱中出现的双峰/异常峰结构，当前工作区已完成 `CORE_VERSION=0x00010028` 候选 RTL 修复，并已完成 Vivado timing/bitstream、PYNQ 发布、10 秒板端门禁和 10 秒主机 24-flow 门禁。本修复不改变 Stage 27h 生产合约：TIME `4300..4307`、SPEC `4308..4323`、`24` flows、`16 x 256ch x 1 time`、TIME/SPEC 各约 `480kpps`、合计 T510 UDP 载荷 `63Gbps+`，并且不恢复 PFB、decimation 或 thinning。

定位证据：

- Rust Web 和 TSP3 抓包显示 SPEC snapshot 完整，`coverage=16/16`，SPEC parse error 为 0；因此不是浏览器画图或主机 assembler 把 partial/mixed frame 当完整频谱。
- TIME 波形从真实 IQ 样点估计的 baseband tone 接近 `-40MHz`，符合 `center=100MHz`、DAC `60MHz` 的预期；因此 DAC 控制、RFDC 输入和 TIME 分支不是主要问题。
- 异常只出现在 SPEC 分支，问题边界落在 TIME/SPEC split 之后、SPEC UDP 打包之前。
- 现有 27h channelizer 在 CMAC 时钟域把每个 `1024-bit` beat 拆成 4 个 `256-bit` cell 后直接送入 streaming XFFT；由于上游 beat 以约 `30.72M beat/s` 到达，而 CMAC/XFFT 时钟约 `325MHz`，XFFT 一帧内部会看到 4-cell burst 后的 `tvalid` 空洞。packet rate 和 route coverage 仍可通过，但 pipelined streaming XFFT 的帧内输入节拍被破坏，会造成频谱形态错误。

修复点：

- `rtl/pfb_channelizer.sv` 的 Stage 27h production channelizer 增加两帧 ping-pong frame buffer。SPEC 输入仍是 RFDC selected cell -> requantizer -> FFT-only channelizer，但 channelizer 先收齐完整 `4096` 个 cell，再以连续 `4096` 个 CMAC 时钟周期送入 XFFT。
- XFFT 帧内 `tlast`、`sample0` FIFO 和 `packet_chan0` 仍按 `4096` bin、`16 x 256ch` 合约生成；UDP wire contract 不变。
- `input_fifo_level` 改为反映 frame buffer/fill 进度，`feng_busy` 覆盖 fill/feed/read/output 状态。
- `sim/tb_pfb_channelizer.sv` 新增 Stage 27h production 断言：XFFT 一帧开始后，`tready` 为高时 `tvalid` 不允许掉，且输入 bin 必须 `0..4095` 连续；zero-input gate 仍要求全零 SPEC 输出和无 XFFT event。

本地已通过的检查：

```bash
EXTRA_XVLOG_DEFINES=T510_STAGE27H_PRODUCTION_ONLY ./scripts/run_xsim_batch.sh tb_pfb_channelizer
EXTRA_XVLOG_DEFINES=T510_STAGE27H_PRODUCTION_ONLY ./scripts/run_xsim_batch.sh tb_spec_udp_cmac512 tb_t510_fengine_top_smoke tb_xfft_8lane_config_wrapper
```

硬件已通过的 `0x00010028` 门禁：

- Vivado direct bitstream：`POST_BIT_WNS=+0.081ns`、`POST_BIT_WHS=+0.009ns`，bit SHA256 `564e34223030ee58d1a36c65bd7817804d2d76a64160c67703870736be9767cb`。
- PYNQ 发布：远端 bring-up root 和 overlay bitstream SHA 与本地 bitstream 一致。
- 板端 10 秒 `TIME_SPEC 100MHz`：TIME `480600.1 pps`，SPEC `480600.0 pps`，合计 T510 UDP 载荷 `63977.478656 Mbps`，16 条 SPEC route 全覆盖，RFDC/science/TIME/SPEC/TX/XFFT 错误增量为 0。
- 主机 10 秒 24-flow receive：TIME `480408.812215 pps`，SPEC `480132.960259 pps`，合计 T510 UDP 载荷 `63933.660376 Mbps`，parse/ring/kernel/NIC drop 和 TIME/SPEC gap 增量为 0，波形与频谱 preview 均 active。
- 主机调优结论：raw PREROUTING drop 必须保留；去掉后 UDP `NoPorts` 和 ICMP rate-limit 压力会显著增加。当前默认使用 `rx-usecs=32 rx-frames=128`；`8/64` 组合已实测会产生 PHY discard 和 TIME/SPEC gap，不能作为生产配置。

`0x00010028` 仍需完成：

- DAC amplitude `0`、单音 `60MHz/140MHz` 的 SPEC 频谱形态复测。复测通过前，只声明吞吐/门禁闭合，不声明双峰现象已经在实流显示上闭合。
- 60 秒、10 分钟、1 小时和过夜 soak。

## 生产 UI 收尾

截至 2026-07-03 CST，Stage 27h 的 Jupyter 控制端和 Rust Web 监控端完成生产显示收尾；该收尾不修改 RTL、UDP wire contract、TSP3 spectrum binary、24-flow 配置或 `63Gbps+` 验收门槛。

- notebook 15 保留生产控制和生产预览：接收端 IP/端口/MAC、模式/带宽/中心频率、8 路 DAC-ADC 环回、DAC tone 频率/幅度/相位，以及 RF 还原波形和 FFT-only 生产频谱。
- RF 波形显示语义已明确：使用真实 TIME/RFDC IQ 样点逐点形成包络，再按中心频率重建 RF 等效曲线；同时保留真实采样点标记。曲线用于人眼判断 RF 频率和相位，采样点用于证明数据来源；停流后 stale preview 会清空，不继续显示旧波形。
- Rust Web 的 SPEC 频谱和瀑布只发布完整 `4096` bin snapshot；assembler 必须收齐 `16/16` 个 `256-channel` block，避免把 partial frame 或 mixed frame 当成生产频谱。
- SPEC phase 面板从频率横轴的瞬时 phase 图改为时间横轴的滚动相对 phase 图。目标 bin 优先由 `expected_mhz` 决定，缺省时回退到 `dac_mhz`；bin 映射使用 TSP3 中的真实 `sampleRateHz`。默认参考通道为 `CH1`，显示 `wrap/unwrap(phase[ch] - phase[CH1])` 的 degree 曲线，默认窗口 `30s`，最多保留 `2048` 点。
- phase history 只在 `coverage=16/16` 且 target bin 平均功率高于噪声底 `12dB` 时追加；当 `expected_mhz/dac_mhz/center_mhz/bandwidth_mhz/phaseRef` 改变、配置 Apply、SPEC 断流或 coverage 不完整时清空。

2026-07-04 CST 追加修复：

- 对 `center=100MHz`、`DAC=60.000MHz` 出现的主峰分裂做了复核。Stage 27h 已移除 PFB，当前 SPEC 是 FFT-only 矩形窗；100MHz 模式实际 sample rate 为 `122.88MS/s`，4096 点 FFT 的 bin 间隔为 `30kHz`。`60.000MHz` 对应 baseband `-40MHz`，即 `-1333.333` bin，不在 FFT bin 上，因此会天然产生相邻 bin 分裂和旁瓣。该现象本身不是 UDP 解码错误，也不是 27h 吞吐目标退化。
- notebook 15 增加生产默认 `Snap DAC to FFT bin`，并把当前默认观测改为 `center=100MHz`、`DAC/expected=60.010MHz`，即最近的 `-1333` FFT bin。Apply 时会显示 bin 宽、signed bin、请求频率、对齐频率和误差；需要检查 SPEC 单音窄峰时应保持该选项开启。
- notebook 15 的 `Apply phase` 不再把 DAC source 切到 `single_tone`，只更新 `constant_phasor` 幅度和 8 路相位；RF 频率/NCO 变化必须走完整 `Apply`，避免 phase-only 操作把生产环回从 RFDC NCO 单音改成基带 single-tone。
- Rust Web 默认配置同步为 `center=100MHz`、`expected=dac=60.010MHz`，并修正 target-bin 计算的 fallback sample rate：不再用 `bandwidth_mhz * 1e6` 代替采样率，而是使用 TSP3 header 中的 `spec_sample_rate_hz`，缺省时按 `245.76MHz / decimation` 推导。SPEC 状态栏现在显示 target bin error 和 bin width，用于直接判断 off-bin 泄漏是否会影响图形判断。

此前实流检查使用 `center=100MHz`、`expected=dac=60MHz`，峰值实际落在最近 bin 对齐频率约 `60.010MHz`：

- Rust receiver 运行在 `0.0.0.0:8089`，配置 `24` flow、`8` TIME、`16` SPEC、`spec-layout=stage27h`。
- `/api/state` 显示 TIME/SPEC 均 live，速率约 TIME `479.9 kpps / 31.94 Gbps`、SPEC `479.9 kpps / 31.94 Gbps`。
- 5 秒窗口内历史 drop/gap 计数没有继续增长。
- 从 `/ws/spectrum` 抓取完整 TSP3 snapshot 后，`60MHz` target 映射到 bin `2763`，peak 也在 bin `2763`，target bin 频率约 `60.010MHz`。
- target bin 上 CH0 相对 CH1 的相位约 `-51.56 deg`；CH1..CH7 相对 CH1 约在 `-0.27..+0.37 deg` 范围，符合当前 CH0 使用更长线缆、其余通道近似等长的实验预期。

2026-07-04 CST 追加调查：

- SPEC 频谱/瀑布里出现了两个叠加问题，必须分开处理，不能用显示层修复掩盖科学数据异常。
- Rust Web 旧的 spectrum/power 绘制使用 stride 抽点，`4096` 个 bin 压到几百像素宽时，单 bin 或窄峰可能因浏览器宽度变化被抽中或跳过；waterfall 也用单 bin stride 取样，因此浏览器 resize 后 target peak 时有时无、瀑布图不稳定，这是显示层 bug。
- 直接抓取 Rust Web 推给浏览器的完整 TSP3 spectrum binary 后，snapshot 为 `coverage=16/16`、`sampleRate=122.88MS/s`、FFT-only。DAC amplitude 为 `0` 时仍能看到中心右侧强峰；该峰不是正常 DAC tone。
- Rust Web 已切换为 peak-preserving spectrum/power 绘制和 waterfall max-pooling。该修复只保证 UI 不因 canvas 宽度丢窄峰；它不是科学数据修复，也不会消除真实数据里的 spur。
- 新增并修订 `scripts/pynq_stage27h_rfdc_spur_audit.py`，用于可复现地区分 `fixed_baseband_spur`、`fixed_rf_spur`、`dac_related_spur`、`time_decode_issue`、`spec_only_issue` 或 `inconclusive`。脚本现在同时抓取 Rust Web `/ws/waveform` 的 TFW5 production TIME I/Q 样点并做 AC-coupled FFT，以及 `/ws/spectrum` 的完整 TSP3 SPEC snapshot；RFDC raw preview 只保留为旁证，不再直接作为 production TIME/SPEC 一致性判据。
- 需要更正的是，`reports/board/stage27h_rfdc_time_spur_audit_min_prodtime_v2.json` 和 `reports/board/stage27h_rfdc_time_spur_audit_min_prodtime_ref_v2.json` 中曾记录的 production TIME 与 SPEC 峰位不一致，不能作为最终科学证据。复查发现这些样本采集时 `channelizer_status` 已出现 `pfb_overflow=1`、`pfb_xfft_event_count`、`pfb_xfft_tlast_missing_count` 和 `pfb_xfft_tlast_unexpected_count` 增长；同一状态下官方 Stage 27h validator 也会因 XFFT 错误计数非零失败。
- 重新下载当前 `0x00010028` bitstream 后，官方 2 秒板端 validator 再次通过：TIME/SPEC 均接近 `481kpps`，合计 T510 UDP 载荷约 `64Gbps`，`pfb_overflow_count`、`pfb_xfft_event_count`、`pfb_xfft_tlast_missing_count`、`pfb_xfft_tlast_unexpected_count` 等错误计数增量均为 `0`。因此 `0x00010028` 的生产吞吐/短门禁结论没有被上述无效 audit 样本推翻。
- 当前脚本已补充 F-engine clean gate：每个 audit case 在抓取 Rust TIME/SPEC 前必须证明 FFT-only channelizer 配置正确、`pfb_frame_count` 前进，并且 `pfb_overflow/data_halt/XFFT/tlast/backpressure` 相关计数在短窗口内零增量。门禁失败的 case 会写入 JSON，但 `valid_for_spur=false`，不会参与 fixed-baseband、fixed-RF、DAC-related、TIME decode 或 SPEC-only 分类。
- 当前脚本默认对每个 audit case 重新下载 `0x00010028` bitstream，避免跨 case RFDC/F-engine 重配残留污染诊断。显式 `--no-download` 或 `--no-download-each-case` 只用于当前状态 smoke，不应用作多 case 科学结论。
- Clean-gated 完整 sweep 产物：`reports/board/stage27h_rfdc_spur_audit_clean_gate_full_fixed_rf_20260704.json`。所有 case 的 F-engine clean gate 均通过，`invalid_cases=[]`，分类为 `fixed_rf_spur`，source 为 `production_time`，`rf_span_mhz=0.34`。zero-amplitude、DAC enable mask `0xff` 时，`center=80/100/120MHz` 的 production TIME/SPEC 主峰均落在绝对 RF 约 `122.8MHz`；`center=160MHz` 时该峰已不在 100MHz 观测带宽内，主峰 SNR 低于分类阈值。DAC enable mask `0x00`、`center=100MHz` 时 spur 仍存在。reference tone case 中 `center=100MHz`、DAC/expected `60.010MHz`，production TIME 主峰约 `59.92MHz`，SPEC 主峰约 `60.01MHz`，SNR 分别约 `70dB/75dB`，证明 reference 单音、Rust parser、TSP3 assembler 和 FFT-only SPEC 落点在 clean 状态下是一致的。
- 因此当前 spur 结论是：右侧异常不是 Rust Web 绘图问题，不是 SPEC-only 解码问题，也不是 DAC enable 产生的 tone；它是一个进入 production TIME 和 SPEC 的固定绝对 RF spur，约在 `122.8MHz`。下一步应优先查 RFDC/ADC 输入链路、RFDC mixer/decimation/NCO 配置、板级固定 RF/时钟/模拟耦合源；只有后续 clean-gated reference tone 证明 TIME/SPEC 再次不同频时，才回到 SPEC channelizer/bin-map RTL 审计。
- 审计后已用 fresh download 跑官方板端恢复门禁：`reports/board/stage27h_restore_after_spur_audit_clean_gate_full_20260704.json`，分类 `STAGE27H_TIME_SPEC_100MHZ_FFT_FULLRATE_BOARD_PASS`，TIME `481110.5 pps`、SPEC `481109.0 pps`，合计 T510 UDP 载荷 `64045.329920 Mbps`，证明 audit 后板端已恢复到干净生产状态。
- 2026-07-05 的 fixed-RF 定向审计不改 RTL、不重建 bitstream、不做物理插拔，只使用已发布的 `0x00010028`。产物为 `reports/board/stage27h_rfdc_fixed_rf_spur_audit_20260705.json`，命令入口为 `scripts/pynq_stage27h_rfdc_spur_audit.py --fixed-rf-audit`。本轮对 target RF `122.88MHz` 做直接审计，并在 target 周围 `+/-0.30MHz` 内取局部峰，避免 TIME 预览较短窗口的 FFT bin 量化误差把同一个窄峰误判为未命中。
- 该 fixed-RF 审计分类为 `adc_or_board_fixed_rf_suspect`，原因是 target RF spur 在 `70/80/90/100/110/120/130MHz` center 下均同时出现在 production TIME 与完整 TSP3 SPEC 中；`center=100MHz`、DAC amplitude `0`、DAC enable mask `0x00` 时仍存在；DAC amplitude `0` 且 DAC NCO 分别为 `60/100/122.88/180MHz` 时仍存在，4 个 DAC NCO sweep case 均通过 target SNR 门限。因此该 spur 不随 DAC NCO 走，也不依赖 DAC enable。
- 参与分类的 case 均为 `valid_for_spur=true`，`invalid_cases=[]`，RFDC readback check 未发现 mixer/decimation/Nyquist/QMC 配置与请求值不一致。reference tone case 中 `center=100MHz`、DAC/expected `60.010MHz`，TIME 峰约 `59.92MHz`、SPEC 峰 `60.01MHz`，delta 分别约 `0.09MHz/0.00MHz`，SNR 分别约 `69.8dB/74.9dB`，说明 TIME/SPEC parser、SPEC assembler 和 FFT-only bin 落点在该审计中仍可信。
- 因此当前无物理操作条件下的最强结论是：`122.88MHz` 附近固定绝对 RF spur 已进入 ADC/RFDC production 数据链，并同时被 TIME 与 SPEC 看到；软件 sweep 未支持 RFDC mixer/NCO 配置错误或 DAC 数字耦合作为主因。该结论仍不能区分外部线缆/终端耦合、板上模拟耦合、时钟串扰或 ADC 本体来源，下一步需要 RFDC/ADC 输入和板级固定 RF/时钟/模拟路径的物理或仪器化诊断。
- 审计后已 fresh download 并运行官方 2 秒恢复门禁：`reports/board/stage27h_restore_after_fixed_rf_spur_audit_20260705.json`，分类 `STAGE27H_TIME_SPEC_100MHZ_FFT_FULLRATE_BOARD_PASS`，`CORE_VERSION=0x00010028`，TIME `481053.5 pps`、SPEC `481052.5 pps`，合计 T510 UDP 载荷 `64037.775360 Mbps`，错误列表为空。Stage 27h 全速生产路径在本轮 audit 后已恢复到干净状态。
- 2026-07-06 在所有 DAC-ADC 回环线断开、ADC 输入开路的物理状态下，重复 fixed-RF 审计，产物为 `reports/board/stage27h_rfdc_fixed_rf_spur_audit_all_dac_adc_unplugged_20260706.json`。脚本总分类为 `inconclusive`，原因是 reference tone `60.010MHz` 未通过；这在回环线全部断开的状态下符合预期，不代表 TIME/SPEC 解析失效。关键 target RF 结果是：`122.88MHz` 附近 spur 仍在 `70/80/90/100/110/120/130MHz` center 下同时被 production TIME 与完整 TSP3 SPEC 命中，`center=100MHz`、DAC enable mask `0x00` 时仍存在，DAC NCO `{60,100,122.88,180MHz}` sweep 下仍存在。与 2026-07-05 接线状态相比，target SNR 大多只变化数 dB；`center=100MHz` enable-off case 中 TIME/SPEC target SNR 分别约 `37.3dB/40.8dB`。
- 全拔线逐通道结果显示该 spur 不是单一回环线问题：`center=100MHz` enable-off case 中 TIME target SNR 约为 CH0 `39.1dB`、CH1 `41.9dB`、CH2 `41.3dB`、CH3 `19.3dB`、CH4 `20.9dB`、CH5 `37.2dB`、CH6 `40.6dB`、CH7 `30.1dB`；SPEC target SNR 约为 CH0 `42.1dB`、CH1 `47.5dB`、CH2 `46.4dB`、CH3 `26.0dB`、CH4 `21.7dB`、CH5 `42.1dB`、CH6 `42.0dB`、CH7 `33.0dB`。因此“外部 DAC-ADC 回环线或 DAC 输出 tone 通过线缆进入 ADC”已经不是主因。由于 ADC 输入此时是开路，仍不能排除开路输入作为天线拾取板上/环境中的 `122.88MHz` 时钟或谐波耦合；下一步需要 50 欧终端或等效 50 欧输入条件复测。
- 全拔线审计后已 fresh download 并运行官方 2 秒恢复门禁：`reports/board/stage27h_restore_after_all_dac_adc_unplugged_spur_audit_20260706.json`，分类 `STAGE27H_TIME_SPEC_100MHZ_FFT_FULLRATE_BOARD_PASS`，`CORE_VERSION=0x00010028`，TIME `481047.5 pps`、SPEC `481048.0 pps`，合计 T510 UDP 载荷 `64037.076480 Mbps`，错误列表为空。
- 2026-07-06 用户进一步将 ADC 接到频谱仪 `50Ω input`，重复 fixed-RF 审计，产物为 `reports/board/stage27h_rfdc_fixed_rf_spur_audit_adc_to_spectrum_analyzer_50ohm_20260706.json`。脚本总分类仍为 `inconclusive`，同样是因为没有 DAC-ADC 回环路径时 reference tone 不应通过；target RF 证据不受该分类影响。`122.88MHz` spur 仍在 `70/80/90/100/110/120/130MHz` center 下同时被 production TIME 与完整 TSP3 SPEC 命中。`center=100MHz` 时，zero-amp enable-on 的 TIME/SPEC target SNR 约 `38.7dB/41.7dB`，enable-off 约 `38.8dB/41.7dB`，DAC NCO `60MHz` 约 `38.9dB/41.5dB`，DAC NCO `122.88MHz` 约 `39.1dB/41.6dB`。
- 50 欧输入条件与接线状态相比，`center=100MHz` target SNR 变化只有约 `-0.7..+2.0dB`；与 ADC 开路相比变化约 `+0.3..+1.5dB`。因此“ADC 开路当天线拾取外部/线缆 RF”的解释也不成立；当前最强边界是板内 `122.88MHz` 相关源、ADC 模拟输入附近耦合、RFDC/ADC 本体或采样/参考时钟相关耦合。下一步应查板上 `122.88MHz`/采样时钟/参考时钟分布和 ADC 输入前端近场耦合，而不是继续怀疑 DAC-ADC 回环线。
- 50 欧输入审计后已 fresh download 并运行官方 2 秒恢复门禁：`reports/board/stage27h_restore_after_adc_to_spectrum_analyzer_50ohm_spur_audit_20260706.json`，分类 `STAGE27H_TIME_SPEC_100MHZ_FFT_FULLRATE_BOARD_PASS`，`CORE_VERSION=0x00010028`，TIME `481032.5 pps`、SPEC `481033.5 pps`，合计 T510 UDP 载荷 `64035.112960 Mbps`，错误列表为空。
- 2026-07-06 在 ADC 接频谱仪 `50Ω input` 条件下追加板内定向 sweep，产物为 `reports/board/stage27h_board_internal_spur_audit_50ohm_20260706.json`。该 sweep 不改 RTL，仍使用 `0x00010028`，并覆盖 `tcxo_10mhz` 与 `external_10mhz` 两种 clock ref，以及 `20MHz SPEC_ONLY`、`100MHz TIME_SPEC`、`100MHz SPEC_ONLY`、`100MHz TIME_ONLY` 四个生产模式。分类为 `board_internal_122p88_spur_persistent`，`invalid_cases=[]`；target RF `122.88MHz` 在两种 clock ref 下都命中，在四个 mode case 下也都命中。
- 板内 sweep 的代表性 SNR：`tcxo_10mhz`、`100MHz TIME_SPEC` 下 TIME/SPEC target SNR 约 `40.1dB/43.3dB`；`external_10mhz` 下约 `33.7dB/36.4dB`；`20MHz SPEC_ONLY`、`center=120MHz` 下 SPEC target SNR 约 `35.7dB`；`100MHz TIME_ONLY` 下 TIME target SNR 约 `35.7dB`。因此该 spur 不依赖 SPEC 分支、TIME 分支、TIME_SPEC 双路同时工作，也不被 `tcxo` 与 `external` reference 选择消除。
- 板内 sweep 后已 fresh download 并运行官方 2 秒恢复门禁：`reports/board/stage27h_restore_after_board_internal_spur_audit_50ohm_20260706.json`，分类 `STAGE27H_TIME_SPEC_100MHZ_FFT_FULLRATE_BOARD_PASS`，`CORE_VERSION=0x00010028`，TIME `481174.0 pps`、SPEC `481176.0 pps`，合计 T510 UDP 载荷 `64054.016000 Mbps`，错误列表为空。
- 当前结论边界进一步收紧为：`122.88MHz` spur 是已经进入 ADC/RFDC production 数据链的板内固定 RF/时钟相关问题；现有证据不支持 UI、Rust/SPEC 解码、DAC tone、DAC 数字输出、外部回环线、ADC 开路拾取或单一 TIME/SPEC 数字分支作为主因。下一步需要 Stage 27i 诊断 bitstream，在 RFDC AXIS adapter 后加入默认关闭的 `force_zero`/`force_hold`/per-channel isolate，以及 DAC AXIS gate，用于把“RFDC/ADC 前端已带 spur”和“RFDC 后数字链路生成 spur”彻底切开。任何数字 notch、忽略 target bin、降低速率或恢复 thinning 都不能作为 Stage 27h 生产修复。

## Stage 27i 拆分说明

原本混在本报告后半段的 Stage 27i 诊断、raw-lane witness 和 `100MHz` anti-alias production candidate 记录，已单独拆分到 `27i_time_spec_100mhz_antialias.md`。

本文件只保留 Stage 27h `CORE_VERSION=0x00010028` 的 FFT-only 全速 SPEC 基线、验收结果和后续建议。Stage 27i 的 `CORE_VERSION=0x00010029/0x0001002A/0x0001002B` 诊断与 anti-alias 内容不再作为 27h 正文维护。

## 27h 后续工作建议

Stage 27h 之后应保持全速目标不动，按生产化顺序继续推进：

1. 复现性与长稳：
   - 先重复 60 秒板端和主机门禁，并用时间戳归档 JSON。
   - 继续做 10 分钟、1 小时、过夜三档 `TIME_SPEC 100MHz` 全速 soak。
   - soak 期间重点记录 TIME/SPEC 包速率、丢包/间断、预览刷新率、NIC 计数器、温度和 CMAC 链路状态。

2. 主机调优固化：
   - 将 `scripts/host_stage27h_rx_fanout_tune.sh` 中有效的 governor、netdev、coalescing、raw PREROUTING drop 变成可复现的生产配置。
   - 明确哪些设置由 systemd/sysctl/iptables/nftables 持久化，哪些仍保留为手动 bring-up 步骤。

3. 固定 RF spur 根因定位：
   - Stage 27i 已证明 production TIME/SPEC 中的 spur 可被 RFDC AXIS adapter 后的 force-zero/hold 清掉，后级 UDP/Rust/Web 不是生成源。
   - raw-lane witness alias audit 显示 production `122.88MHz` target 可由 raw full-rate RF `0/245.76MHz` 端点附近分量经 `100MHz` PL decim2 折叠得到；Stage 27i `0x0001002B` 已通过 PL halfband anti-alias FIR 抑制该 production alias。
   - anti-alias 已解决 `100MHz` production alias 进入 TIME/SPEC 的问题，但仍需继续追 raw full-rate RF `0/245.76MHz` 端点分量来源，重点是 RFDC ADC mixer/NCO/Nyquist/QMC/MTS readback、ADC 模拟输入前端、板上 `122.88MHz/245.76MHz` 相关时钟/参考/SYSREF/电源耦合，以及是否可以关闭未用 clock/SYSREF 输出或调整 LMK/RFDC profile。
   - 后续若继续动 RTL，只能增加诊断可观测性，不能通过滤波、忽略 target bin、降低速率或恢复 decimation 来掩盖 spur。

4. 下游接收链路：
   - 在交换机、接收节点、DGX 或 X-engine 入口复现 24 流 `4300..4323` 的无丢包/无间断接收。
   - 增加 pcap 或 X-engine ingest 证据，证明 T510 头、TIME/SPEC seq/frame、SPEC `256ch x 1 time` block metadata 能被下游正确消费。

5. 科学质量：
   - 当前 Stage 27h 是仅 FFT 吞吐收敛，不是最终 4-tap PFB 科学标定。
   - 后续需要独立评估是否、何时、如何恢复科学级 PFB 幅相/功率标定；该工作不能通过重新引入 SPEC thinning 来牺牲 27h 已经闭合的全速门槛。

6. Jupyter 与 Rust Web：
   - notebook 15 继续作为生产控制/预览入口，只保留接收端 IP/端口/MAC、模式/带宽/中心频率、8 路 DAC-ADC 环回、DAC tone 频率/幅度/相位，以及 RF 还原波形和 FFT-only 频谱。
   - Rust Web 继续围绕 TIME RF 等效波形、F-engine 状态、完整 FFT-only 频谱、瀑布图、target-bin 相对相位滚动图、活跃流/工作线程、丢包/间断和预览刷新率做生产显示，不恢复历史 debug 面板作为主界面。

## 推荐复现命令

本地：

```bash
python3 -m py_compile python/t510_fengine.py scripts/pynq_stage27h_time_spec_fft_fullrate.py scripts/host_stage27h_rust_rx_validate.py scripts/host_stage27e_rust_rx_validate.py
python3 -m py_compile scripts/pynq_stage27h_rfdc_spur_audit.py
python3 -m json.tool notebooks/15_stage27h_time_spec_fft_fullrate_control.ipynb >/dev/null
bash -n scripts/pynq_publish_stage27h.sh scripts/pynq_publish_jupyter_instrument.sh scripts/host_stage27h_rx_fanout_tune.sh
cargo test -q --manifest-path rust/t510_time_rx/Cargo.toml
cargo build --release --manifest-path rust/t510_time_rx/Cargo.toml
```

板端：

```bash
cd /home/xilinx/t510_fengine_bringup
source /etc/profile.d/xrt_setup.sh
printf "%s\n" "xilinx" | sudo -S -p "" -E /usr/local/share/pynq-venv/bin/python3 \
  scripts/pynq_stage27h_time_spec_fft_fullrate.py --matrix converge --seconds 60
printf "%s\n" "xilinx" | sudo -S -p "" -E /usr/local/share/pynq-venv/bin/python3 \
  scripts/pynq_stage27h_rfdc_spur_audit.py --fixed-rf-audit
```

主机：

```bash
sudo scripts/host_stage27h_rx_fanout_tune.sh ens2f0np0
sudo rust/t510_time_rx/target/release/t510_time_rx \
  --backend fanout \
  --worker-count 24 \
  --fanout-mode port \
  --fanout-group 0x279 \
  --pin-workers auto \
  --interface ens2f0np0 \
  --dst-port-base 4300 \
  --src-port-base 4000 \
  --flow-count 24 \
  --time-flow-count 8 \
  --spec-flow-count 16 \
  --spec-layout stage27h \
  --web 0.0.0.0:8089 \
  --initial-bandwidth-mhz 100 \
  --ring-mb 2048 \
  --block-mb 4 \
  --batch-size 8192 \
  --web-fps 30 \
  --waveform-points 1024 \
  --waveform-max-points 16384
python3 scripts/host_stage27h_rust_rx_validate.py --seconds 60 --poll-interval 0.5
```
