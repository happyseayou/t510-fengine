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

## Stage 27i 诊断 bitstream 结果

截至 2026-07-06 CST，已完成 Stage 27i 诊断 bitstream，用于切分 `122.88MHz` spur 的边界。该 bitstream 只增加默认关闭的诊断 mux，不替代 Stage 27h `0x00010028` 生产基线，也不改变 TIME/SPEC 全速目标。

- 诊断版本：`CORE_VERSION=0x00010029`
- 诊断寄存器默认值：`0x0000ff00`
  - ADC force-zero：关
  - ADC force-hold：关
  - ADC channel mask：`0xff`
  - DAC AXIS gate：关
- Vivado timing/write_bitstream：
  - route WNS `+0.042684ns`
  - write 前后 WNS `+0.043ns`
  - write 前后 WHS `+0.009ns`
  - bit SHA256 `790bce451d15571b2c486f34b0c206b1674ac18ba8f31644235afde5ead15141`

诊断前先运行 27h 生产默认关闭门禁：

- JSON：`reports/board/stage27i_diag_default_off_stage27h_validator_20260706.json`
- 分类：`STAGE27H_TIME_SPEC_100MHZ_FFT_FULLRATE_BOARD_PASS`
- `CORE_VERSION=0x00010029`
- diag 默认关闭：`stage27i_diag_control=0x0000ff00`，`stage27i_diag_disabled=1`
- TIME `481050.5 pps`
- SPEC `481049.5 pps`
- 合计 T510 UDP 载荷 `64037.376000 Mbps`
- RFDC/science/TIME/SPEC/TX route 错误增量均为 `0`

Stage 27i diagnostic probe 产物：

- JSON：`reports/board/stage27i_rfdc_axis_diag_spur_probe_loopback_20260706.json`
- 物理状态：`dac_adc_loopback_restored`
- 分类：`adc_or_rfdc_frontend_spur_confirmed_by_axis_zero`
- 原因：target spur 在诊断全关时存在，打开 RFDC AXIS 后的 ADC force-zero 后消失。

关键 target-bin 结果：

- 诊断全关、DAC amplitude `0`、enable mask `0x00`：
  - TIME target SNR `39.18dB`
  - SPEC target SNR `42.17dB`
  - SPEC target RF bin 约 `122.89MHz`
- ADC force-zero：
  - TIME target SNR `0.0dB`
  - SPEC target SNR `0.0dB`
  - TIME power 约 `-160dB`
- ADC force-hold：
  - TIME target SNR `0.0dB`
  - SPEC target SNR `0.0dB`
- DAC AXIS gate：
  - TIME target SNR `38.93dB`
  - SPEC target SNR `42.27dB`
  - spur 不随 DAC digital gate 消失。
- 单通道 isolate：
  - CH0、CH1、CH2、CH5、CH6 均为强命中。
  - CH3 最弱但仍过门限，TIME/SPEC 约 `14.40dB/12.41dB`。
  - CH4、CH7 中等命中，说明这不是单一 ADC 通道或单一回环线问题。

诊断后重新下载 bitstream 并运行 27h 恢复门禁：

- JSON：`reports/board/stage27i_restore_after_diag_spur_probe_20260706.json`
- 分类：`STAGE27H_TIME_SPEC_100MHZ_FFT_FULLRATE_BOARD_PASS`
- diag 默认关闭：`stage27i_diag_control=0x0000ff00`，`stage27i_diag_disabled=1`
- TIME `481059.0 pps`
- SPEC `481057.0 pps`
- 合计 T510 UDP 载荷 `64038.440960 Mbps`
- RFDC/science/TIME/SPEC/TX route 错误增量均为 `0`

当前边界结论：

- `122.88MHz` spur 已在 RFDC AXIS diagnostic mux 之前存在；RFDC AXIS 之后的 TIME/SPEC split、FFT-only channelizer、SPEC UDP packetizer、Rust parser、TSP3 assembler 和 Web 显示不是 spur 的生成源。
- DAC digital 路径不是主因；即使 DAC AXIS gate 打开，spur 仍存在。
- 不能用 PL 里的 notch、忽略 target bin、降低速率、恢复 decimation/thinning 作为生产修复。下一步应查 ADC 模拟输入前端、RFDC ADC/mixer/decimation 内部状态、板上 `122.88MHz` 相关时钟/参考/SYSREF/电源耦合，以及是否可以通过关闭未用 clock/SYSREF 输出或调整 LMK/RFDC profile 降低耦合。

## 生产同步默认值收紧

截至 2026-07-06 CST，27h/27i 后续生产入口默认改为外部 `10MHz` 参考加外部 `PPS` 锁定。`python/t510_fengine.py` 的生产 observation/science 默认、`scripts/pynq_stage27h_time_spec_fft_fullrate.py`、`scripts/pynq_stage27h_rfdc_spur_audit.py` 和 notebook 15 均默认 `clock_ref=external_10mhz`、`sync_mode=external_pps`。27h 板端 validator 会显式检查 configured/active sync mode、PPS recent 和 PPS count；如果 PPS 未进入锁定语义，默认生产门禁不应继续通过。

实现细节：27h board validator 现在按生产启动顺序执行，先配置 science 路由但不立即计时，随后等待 CMAC/QSFP ready、dry-run 关闭、external PPS 触发且 TIME/SPEC 包计数真实前进，再进入正式 rate/drop/error 窗口。这样避免 fresh download 后链路 bring-up 或 PPS arm 等待污染速率窗口，同时不降低 TIME/SPEC `480kpps + 480kpps` 与 `63Gbps+` 门槛。

本轮已完成 fresh-download 2 秒 smoke：

- JSON：`reports/board/stage27i_external_pps_default_smoke_ready_wait_20260706.json`
- 分类：`STAGE27H_TIME_SPEC_100MHZ_FFT_FULLRATE_BOARD_PASS`
- `configured_clock_ref=0`、`configured_sync_mode=0`、`active_sync_mode=0`
- `pps_recent=1`、`pps_count=5`
- ready wait 约 `1.16s` 后确认 TIME/SPEC 包计数前进，CMAC ready，dry-run off
- TIME `481025.0 pps`
- SPEC `481026.5 pps`
- 合计 T510 UDP 载荷 `64034.147840 Mbps`
- RFDC/science/TX route 错误增量为 `0`

历史报告中出现的 `tcxo_10mhz` 或 `free_run` 仍按当时测试条件保留；它们只作为 archived bring-up 或 clock-ref 对照 sweep，不再代表 Stage 27h 的生产默认入口。

## Stage 27i 外部 PPS spur 复测

截至 2026-07-06 CST，已在生产默认同步条件下重跑 Stage 27i 诊断 probe。该轮继续使用 `CORE_VERSION=0x00010029`，物理状态为 DAC-ADC 回环线已恢复，默认 `clock_ref=external_10mhz`、`sync_mode=external_pps`，不改 RTL、不重建 bitstream、不使用 notch 或忽略 bin。

复测前 fresh-download 2 秒门禁：

- JSON：`reports/board/stage27i_external_pps_pre_diag_smoke_20260706.json`
- 分类：`STAGE27H_TIME_SPEC_100MHZ_FFT_FULLRATE_BOARD_PASS`
- `stage27i_diag_control=0x0000ff00`，`stage27i_diag_disabled=1`
- `configured_clock_ref=external_10mhz`，`configured_sync_mode=external_pps`，`active_sync_mode=external_pps`
- `pps_recent=1`，`pps_count=5`
- TIME `481025.0 pps`
- SPEC `481024.0 pps`
- 合计 T510 UDP 载荷 `64033.981440 Mbps`

Stage 27i external-PPS probe 产物：

- JSON：`reports/board/stage27i_rfdc_axis_diag_spur_probe_external_pps_20260706.json`
- 分类：`adc_or_rfdc_frontend_spur_confirmed_by_axis_zero`
- 物理状态：`dac_adc_loopback_restored_external_10mhz_pps`
- 同步摘要：`EXTERNAL_10MHZ_PPS_OK`，LMK selected ref 为 `external_10mhz`，RFDC MTS shim ready，RFDC readback mismatch 为空。
- 诊断全关：TIME/SPEC target SNR 约 `37.85dB/40.78dB`，target bin 仍在 `122.88MHz` 附近。
- ADC force-zero：TIME/SPEC target SNR 均为 `0.0dB`。
- ADC force-hold：TIME/SPEC target SNR 均为 `0.0dB`。
- DAC AXIS gate：TIME/SPEC target SNR 约 `38.67dB/41.34dB`，spur 不随 DAC digital gate 消失。
- 单通道 isolate：CH0..CH7 全部命中；SNR 分布约为 CH0 `37.09/37.81dB`、CH1 `45.42/45.53dB`、CH2 `41.96/42.15dB`、CH3 `16.45/22.63dB`、CH4 `22.92/27.65dB`、CH5 `36.41/35.85dB`、CH6 `40.83/40.24dB`、CH7 `28.45/30.82dB`，格式为 TIME/SPEC。

诊断后恢复门禁：

- 第一次恢复 JSON：`reports/board/stage27i_restore_after_external_pps_diag_spur_probe_20260706.json`，分类为 FAIL，原因是 CMAC/QSFP ready 窗口内 `CMAC_TX_NOT_READY` 和 `TX_STILL_DRY_RUN`；该轮诊断寄存器仍已恢复为 `0x0000ff00`，TIME/SPEC 计数窗口本身接近满速。
- 重跑恢复 JSON：`reports/board/stage27i_restore_after_external_pps_diag_spur_probe_retry_20260706.json`
- 重跑分类：`STAGE27H_TIME_SPEC_100MHZ_FFT_FULLRATE_BOARD_PASS`
- `stage27i_diag_control=0x0000ff00`，`stage27i_diag_disabled=1`
- `pps_recent=1`，`pps_count=5`
- TIME `481031.5 pps`
- SPEC `481030.5 pps`
- 合计 T510 UDP 载荷 `64034.846720 Mbps`

本轮结论没有改变生产目标，但把同步条件收紧后的边界重新确认了一遍：`122.88MHz` spur 在外部 `10MHz` 与外部 `PPS` 默认锁定下仍存在，且 force-zero/hold 在 RFDC AXIS adapter 后将其清零。因此后级 TIME/SPEC/UDP/Rust/Web 不是生成源，问题仍在 RFDC AXIS diagnostic mux 之前。当前仍不能仅凭软件区分 ADC 模拟输入前端耦合、RFDC ADC 内部行为、板上 `122.88MHz` 相关时钟/SYSREF/电源耦合；下一步应继续在 Stage 27i 内做板内时钟/RFDC 配置和物理近端证据，不开 Stage 27j。

## Stage 27i 前端 spur audit

截至 2026-07-06 CST，已在同一 Stage 27i 诊断 bitstream 上增加并运行 front-end audit；不改 RTL、不重建 bitstream、不使用 notch、bin mask、降速、thinning 或显示隐藏。该轮继续使用 `CORE_VERSION=0x00010029`，物理状态为 DAC-ADC 回环线已恢复，默认同步为外部 `10MHz` 加外部 `PPS`。

脚本和命令：

- 脚本：`scripts/pynq_stage27i_frontend_spur_audit.py`
- 底层入口：`scripts/pynq_stage27h_rfdc_spur_audit.py --stage27i-front-end-audit`
- JSON：`reports/board/stage27i_frontend_spur_audit_external_pps_20260706.json`
- log：`reports/board/stage27i_frontend_spur_audit_external_pps_20260706.log`

复测前 fresh-download 2 秒门禁：

- JSON：`reports/board/stage27i_frontend_pre_smoke_20260706.json`
- 分类：`STAGE27H_TIME_SPEC_100MHZ_FFT_FULLRATE_BOARD_PASS`
- `stage27i_diag_control=0x0000ff00`，PPS recent 有效。
- TIME `481028.0 pps`
- SPEC `481030.0 pps`
- 合计 T510 UDP 载荷 `64034.580480 Mbps`

front-end audit 结果：

- 顶层 `ok=false`，原因是证据矩阵中 `200MHz SPEC_ONLY` case 未通过 F-engine clean gate；该状态按脚本纪律不再标成全量通过。
- 定位分类仍为 `rfdc_adc_config_or_internal_suspect`。
- 分类原因：target RF spur 不在 RFDC bandwidth/decimation 或 ADC mixer center sweep 下保持稳定，且 RFDC readback 未发现 center/DAC NCO/mixer mismatch。
- `classification_cases_valid=false`，invalid case 为 `stage27i_frontend_mode_200mhz_spec_only_center_100.000`。
- 该 invalid case 的 clean-gate 失败原因为 `FENGINE_ERROR_COUNTER_DELTA`：`pfb_capture_backpressure_count` 增量约 `80390421`，`pfb_xfft_data_out_halt_count` 增量约 `10777477`，说明 `200MHz SPEC_ONLY` 当前不能作为 clean spur 证据。

关键证据：

- Baseline：外部 `10MHz` + 外部 `PPS`、`TIME_SPEC 100MHz`、DAC amplitude `0`、诊断全关时，TIME/SPEC target SNR 约 `40.47dB/43.78dB`。
- Force-zero sentinel：审计开始和结束的 ADC force-zero 均将 TIME/SPEC target SNR 压到 `0.0dB/0.0dB`，继续证明 spur 在 RFDC AXIS diagnostic mux 之前。
- Clock-ref 对照：`external_10mhz` 与 `tcxo_10mhz` 均命中，TIME/SPEC target SNR 分别约 `40.91dB/43.61dB` 与 `39.67dB/43.13dB`；未出现足够大的 clock-ref 敏感性。
- SYSREF pulse 对照：explicit SYSREF pulse 后 target SNR 约 `40.18dB/43.12dB`；未出现足够大的 SYSREF pulse 敏感性。
- Mode 对照：`20MHz SPEC_ONLY`、`100MHz TIME_SPEC`、`100MHz SPEC_ONLY`、`100MHz TIME_ONLY` 均能看到 target；`200MHz TIME_ONLY` target SNR 仅约 `1.45dB`，`200MHz SPEC_ONLY` clean gate 失败。
- Center/NCO 对照：`center=80MHz` 与 `100MHz` 时 target RF `122.88MHz` 在 TIME/SPEC 中强命中；`center=122.88MHz` 时 SPEC target 仍约 `39.47dB`，但 TIME AC 指标因 target 落到 DC 附近被均值去除压低；`center=140MHz` 与 `160MHz` 时 target RF 附近 TIME/SPEC 均低于门限。

诊断后恢复门禁：

- JSON：`reports/board/stage27i_restore_after_frontend_spur_audit_20260706.json`
- 分类：`STAGE27H_TIME_SPEC_100MHZ_FFT_FULLRATE_BOARD_PASS`
- `stage27i_diag_control=0x0000ff00`，诊断开关恢复默认关闭。
- TIME `481036.5 pps`
- SPEC `481040.0 pps`
- 合计 T510 UDP 载荷 `64035.811840 Mbps`

本轮结论边界：

- UI、Rust Web 绘图、Rust SPEC parser、TSP3 assembler、SPEC UDP layout、TIME/SPEC 后级数据面仍不是当前 spur 的生成源。
- DAC digital 路径仍不是主因；之前 DAC gate 证据已证明 gate 后 spur 不消失。
- 该轮没有支持“单纯 LMK/SYSREF/clock-ref 状态切换会显著改变 spur”的结论。
- 更强的新证据是：`122.88MHz` target 随 ADC mixer center 和 200MHz bandwidth/decimation 状态表现不稳定，因此下一步应优先查 RFDC ADC mixer/decimation/Nyquist/QMC/MTS 配置细节、RFDC ADC 内部响应，以及为何 `200MHz SPEC_ONLY` 会触发 F-engine backpressure；再结合必要的板级近端测量区分 ADC 输入前端/板级模拟耦合。
- 仍不允许用 notch、忽略 target bin、降低速率、恢复 decimation/thinning 或显示层隐藏作为生产修复。

## Stage 27i SPEC sideband audit

针对人工观察到的 “`SPEC_ONLY`、DAC amplitude `0`、`center=100MHz` 时，`100MHz BW` spur 在右侧而 `200MHz BW` spur 在左侧” 现象，已增加并运行 Stage 27i SPEC sideband audit。该轮仍不改 RTL、不重建 bitstream、不使用 notch/bin mask/降速/thinning/显示隐藏；`200MHz SPEC_ONLY` 只作为诊断 case，不作为 27h 生产通过目标。

脚本和命令：

- 脚本：`scripts/pynq_stage27i_spec_sideband_audit.py`
- 底层入口：`scripts/pynq_stage27h_rfdc_spur_audit.py --stage27i-spec-sideband-audit`
- JSON：`reports/board/stage27i_spec_sideband_audit_external_pps_20260706.json`
- log：`reports/board/stage27i_spec_sideband_audit_external_pps_20260706.log`

关键结果：

- 分类：`rfdc_adc_config_or_internal_suspect`
- 分类原因：`100MHz SPEC_ONLY` 能看到 target RF sideband，但 `200MHz SPEC_ONLY` 把该 target 压低，同时出现另一个 dominant SPEC peak。
- `100MHz SPEC_ONLY`、`center=100MHz`、DAC amplitude `0`：
  - SPEC 主峰在 `+22.89MHz` baseband，对应 RF `122.89MHz`。
  - SPEC target SNR 约 `42.42dB`。
- `200MHz SPEC_ONLY`、`center=100MHz`、DAC amplitude `0`：
  - `122.88MHz` target 不再是强峰。
  - SPEC 主峰在约 `-100.02MHz` baseband，按当前频率轴对应 RF 约 `0MHz`，SNR 约 `43.32dB`。
  - 该 case 未通过 F-engine clean gate：`pfb_capture_backpressure_count` 与 `pfb_xfft_data_out_halt_count` 增长，因此只能作为诊断证据，不可作为 clean science 证据。
- RFDC raw preview 在两种带宽下也以 `-100.02MHz` baseband 附近为主峰，说明 raw preview 当前更像 RFDC/full-rate 近 DC/边缘伪峰观测，不能直接替代生产 SPEC 频率归因。

诊断后恢复门禁：

- JSON：`reports/board/stage27i_restore_after_spec_sideband_audit_20260706.json`
- 分类：`STAGE27H_TIME_SPEC_100MHZ_FFT_FULLRATE_BOARD_PASS`
- TIME `481043.5 pps`
- SPEC `481042.0 pps`
- 合计 T510 UDP 载荷 `64036.410880 Mbps`

新的边界判断：

- 这不是简单的 “`122.88MHz` 在 `200MHz BW` 下被镜像到左侧”。如果只是边带符号翻转，预期应在 `-22.88MHz` baseband 附近出现强峰；实际 dominant peak 在约 `-100MHz` baseband。
- 该现象更支持 RFDC ADC/mixer/decimation 配置或 RFDC 内部响应嫌疑，尤其是 `200MHz SPEC_ONLY` 下 `pl_decim_factor=1`、sample rate `245.76MS/s` 时的低频/边缘伪峰和 F-engine backpressure。
- 下一步应优先做 RFDC ADC readback 深挖：比较 `100MHz` 与 `200MHz` 下 ADC mixer `Freq/EventSource/MixerMode/CoarseMixFreq/FineMixerScale`、decimation、Nyquist zone、QMC、MTS/SYSREF 更新路径，以及 `200MHz SPEC_ONLY` 为什么让 XFFT output halt/backpressure 增长。

## Stage 27i RFDC 100/200MHz root-cause audit

为继续定位上述 `100MHz BW` 右侧 target spur 与 `200MHz BW` 左侧/低频端 dominant peak 的差异，已新增 Stage 27i RFDC 100/200MHz root-cause audit 入口。该入口仍使用当前 `CORE_VERSION=0x00010029` 诊断 bitstream，不改 RTL、不重建 bitstream、不使用 notch/bin mask/降速/thinning/显示隐藏。

脚本和默认命令：

- 脚本：`scripts/pynq_stage27i_rfdc_200m_rootcause_audit.py`
- 底层入口：`scripts/pynq_stage27h_rfdc_spur_audit.py --stage27i-rfdc-200m-rootcause-audit`
- 默认 JSON：`reports/board/stage27i_rfdc_200m_rootcause_audit_external_pps_YYYYMMDD.json`
- 默认物理状态：`dac_adc_loopback_restored_external_10mhz_pps`
- 默认同步：外部 `10MHz` + 外部 `PPS`

该 audit 的受控 case 为 `center=100MHz` 下的 `100MHz SPEC_ONLY`、`200MHz SPEC_ONLY`、`100MHz TIME_SPEC`、`200MHz TIME_ONLY`；补充 center sweep 为 `122.88/140/160MHz` 下的 `100MHz SPEC_ONLY` 与 `200MHz SPEC_ONLY`。每个 case 记录：

- RFDC readback 四个阶段：observation 前、observation 后、science 配置后、stream start 后。
- TFW5/TSP3 频域证据：`122.88MHz` target bin、mirror bin、负 Nyquist/left-edge bin、dominant peak、TIME/SPEC target SNR。
- F-engine/TX 流控证据：`pfb_capture_backpressure_count`、`pfb_xfft_data_out_halt_count`、SPEC/TIME packet delta、route hit delta、TX drop/route miss/error delta。
- `200MHz SPEC_ONLY` 若仍触发 clean gate 失败，会保留 dirty preview 作为诊断证据，但必须继续列入 `invalid_cases`，不能作为 clean science 通过证据。

分类语义：

- `rfdc_200m_config_mismatch_suspect`：RFDC readback 与请求 center/decimation/mixer/Nyquist/MTS 状态不一致。
- `fengine_200m_output_backpressure_suspect`：`100MHz SPEC_ONLY` 命中 target，但 `200MHz SPEC_ONLY` target 被压低，同时出现 XFFT output halt 或 capture backpressure。
- `spec_axis_mapping_suspect`：`200MHz TIME_ONLY` 命中 target，而 `200MHz SPEC_ONLY` 不命中，且没有 RFDC readback mismatch 或 SPEC backpressure。
- `rfdc_200m_decimation_path_suspect`：RFDC readback 未发现配置 mismatch，且 `200MHz TIME_ONLY` 与 `200MHz SPEC_ONLY` 都把 `122.88MHz` target 压低并出现不同低频/sideband dominant peak；若 `200MHz SPEC_ONLY` 同时出现 XFFT/capture backpressure，则作为并行输出压力证据单独记录，不把根因限定为 SPEC 后级。
- `stage27i_rfdc_200m_inconclusive`：证据不足或四个受控 case 不完整。

实际运行结果：

- 审计前门禁 JSON：`reports/board/stage27i_rfdc_200m_rootcause_pre_validator_20260706.json`
- 审计前门禁：`STAGE27H_TIME_SPEC_100MHZ_FFT_FULLRATE_BOARD_PASS`，TIME `481046.0 pps`，SPEC `481044.0 pps`，合计 T510 UDP payload `64036.710400 Mbps`。
- JSON：`reports/board/stage27i_rfdc_200m_rootcause_audit_external_pps_20260706.json`
- log：`reports/board/stage27i_rfdc_200m_rootcause_audit_external_pps_20260706.log`
- 顶层结果：`ok=true`
- 分类：`rfdc_200m_decimation_path_suspect`
- 分类原因：`100MHz` target clean，但 `200MHz TIME_ONLY` 与 `200MHz SPEC_ONLY` 都将 target 压低，并产生不同的低频/sideband dominant peak；`200MHz SPEC_ONLY` 还单独记录到 XFFT/capture backpressure。

关键证据：

- `100MHz SPEC_ONLY, center=100MHz`：case clean。SPEC target/primary RF 约 `122.89MHz`，baseband 约 `+22.89MHz`，target SNR 约 `41.77dB`，未出现 XFFT/capture backpressure。
- `100MHz TIME_SPEC, center=100MHz`：case clean。SPEC target/primary RF 约 `122.89MHz`，target SNR 约 `43.79dB`；TIME target/primary RF 约 `122.71MHz`，baseband 约 `+22.71MHz`，target SNR 约 `41.19dB`，未出现 XFFT/capture backpressure。
- `200MHz TIME_ONLY, center=100MHz`：case clean。TIME target RF 约 `122.68MHz`，target SNR 仅约 `2.44dB`；dominant TIME peak 转到 RF 约 `-0.17MHz`、baseband 约 `-100.17MHz`，SNR 约 `45.65dB`。这说明 `200MHz` 异常已经出现在 TIME/RFDC 预览路径，不是 SPEC/TSP3 映射或 SPEC UI 单独造成。
- `200MHz SPEC_ONLY, center=100MHz`：作为 dirty 诊断证据保留，不作为 clean science pass。SPEC target RF 约 `122.62MHz`，target SNR 约 `1.91dB`；dominant SPEC peak 转到 RF 约 `-0.02MHz`、baseband 约 `-100.02MHz`，SNR 约 `43.39dB`；同时 `pfb_xfft_data_out_halt_count` 与 `pfb_capture_backpressure_count` 增长。

结论边界：

- 当前证据不支持把 `200MHz` 左侧/低频端异常归因于浏览器绘制、Rust SPEC parser、TSP3 frame assembler 或 SPEC-only packetizer。
- `200MHz SPEC_ONLY` 的 XFFT/capture backpressure 是必须修的输出压力问题，但 `200MHz TIME_ONLY` 在无 SPEC 输出压力时已经出现同类 target 抑制和低频 dominant peak，因此更优先的根因方向是 RFDC `200MHz` 带宽对应的 ADC mixer/decimation/Nyquist/sideband 数据路径。
- 仍不允许用 notch、bin mask、显示隐藏、降速、thinning 或忽略异常 bin 作为 Stage 27h/27i 生产修复。

审计后恢复门禁：

- JSON：`reports/board/stage27i_restore_after_rfdc_200m_rootcause_audit_20260706.json`
- log：`reports/board/stage27i_restore_after_rfdc_200m_rootcause_audit_20260706.log`
- 分类：`STAGE27H_TIME_SPEC_100MHZ_FFT_FULLRATE_BOARD_PASS`
- `CORE_VERSION=0x00010029`
- `stage27i_diag_control=0x0000ff00`，诊断开关恢复默认关闭。
- TIME `481036.5 pps`，SPEC `481040.0 pps`，合计 T510 UDP payload `64035.811840 Mbps`，错误列表为空。

## Stage 27i 100MHz spur taxonomy audit

为避免 `200MHz` 诊断现象干扰 `100MHz` 生产路径判断，已新增 Stage 27i `100MHz-only`、TIME-first 的 spur taxonomy audit。该入口继续使用 `CORE_VERSION=0x00010029` 诊断 bitstream，不改 RTL、不重建 bitstream、不使用 notch/bin mask/降速/thinning/显示隐藏；`200MHz` 只作为历史线索，不进入本轮分类门禁。

脚本和默认命令：

- 脚本：`scripts/pynq_stage27i_100m_spur_taxonomy_audit.py`
- 底层入口：`scripts/pynq_stage27h_rfdc_spur_audit.py --stage27i-100m-spur-taxonomy-audit`
- 默认 JSON：`reports/board/stage27i_100m_spur_taxonomy_audit_external_pps_YYYYMMDD.json`
- 默认物理状态：`dac_adc_loopback_restored_external_10mhz_pps`
- 默认同步：外部 `10MHz` + 外部 `PPS`

该 audit 的判断优先级为 TIME/RFDC 证据，SPEC 只做交叉确认。受控 case 包括：

- 首尾 `force-zero` sentinel，验证 RFDC AXIS 后置诊断 mux 能清除 target。
- `100MHz TIME_ONLY` dense center sweep：`70/80/90/100/110/120/122.88/130/140/150/160MHz`。
- `100MHz TIME_SPEC` confirm：`80/100/122.88/140MHz`。
- `center=100MHz` repeated apply 三次，观察 RFDC mixer/NCO update 后 target SNR 和相对通道相位是否重置或漂移。
- `center=100MHz` explicit SYSREF pulse 前后对照。

每个 case 记录 RFDC 四阶段 readback、TIME TFW5 target/mirror/negative-edge/DC bin、per-channel target SNR/phase、SPEC TSP3 confirm、F-engine/TX clean gate 和同步状态。TIME TFW5 额外保留 raw target/DC 指标，避免 `center=122.88MHz` 时 target 落到 DC 后被 AC/mean-removed 指标误判为消失。

分类语义：

- `fixed_rf_or_board_coupling_suspect`：TIME target 在 `100MHz` center sweep 中稳定保持同一绝对 RF，SPEC confirm 同向，NCO/SYSREF 操作不显著改变 target。
- `rfdc_mixer_nco_sideband_suspect`：target 频率、功率或相对通道相位随 center/NCO/SYSREF 变化，或 RFDC readback 与请求状态不一致。
- `rfdc_dc_image_or_iq_mapping_suspect`：`center=122.88MHz` 附近出现 DC/image/mirror 异常，且缺少广泛固定 RF 证据。
- `adc_or_rfdc_frontend_internal_suspect`：force-zero 可清除、后级不是来源，但 100MHz 证据不足以归为固定 RF/板级耦合或 NCO/sideband。
- `stage27i_100m_spur_taxonomy_inconclusive`：case 未 clean、force-zero sentinel 失效、readback 缺失或 target 证据不足。

实际运行结果：

- 审计前第一次门禁 JSON：`reports/board/stage27i_100m_spur_taxonomy_pre_validator_20260707.json`，分类为 FAIL，原因是 ready 窗口内 `TX_STILL_DRY_RUN` / `CMAC_TX_NOT_READY`；该轮只作为链路 bring-up 瞬态记录。
- 审计前重跑门禁 JSON：`reports/board/stage27i_100m_spur_taxonomy_pre_validator_retry_20260707.json`
- 审计前重跑门禁：`STAGE27H_TIME_SPEC_100MHZ_FFT_FULLRATE_BOARD_PASS`，TIME `481044.5 pps`，SPEC `481043.5 pps`，合计 T510 UDP payload `64036.577280 Mbps`。
- Audit JSON：`reports/board/stage27i_100m_spur_taxonomy_audit_external_pps_final_20260707.json`
- Audit log：`reports/board/stage27i_100m_spur_taxonomy_audit_external_pps_final_20260707.log`
- 顶层结果：`ok=true`，`invalid_cases=[]`
- 分类：`rfdc_mixer_nco_sideband_suspect`
- 分类原因：target power 或高 SNR 通道的相对 phase 随 repeated RFDC mixer/NCO apply 或 SYSREF pulse 变化；同时 100MHz center sweep 显示 target 只在 `70..130MHz` center 下稳定过门限，`140/150/160MHz` 低于门限。

关键证据：

- force-zero sentinel 生效：`force_zero_clears_target=true`，说明后级 TIME/SPEC/UDP/Rust/Web 仍不是生成源。
- `100MHz TIME_ONLY` dense sweep：target 在 `70/80/90/100/110/120/122.88/130MHz` 命中，TIME target SNR 约 `28.13..40.56dB`；在 `140/150/160MHz` 低于门限，SNR 约 `6.31/1.66/2.38dB`。
- `100MHz TIME_SPEC` confirm：`80/100/122.88MHz` 下 TIME 与 SPEC 同时命中；`140MHz` 下 TIME/SPEC 均低于门限。该结果支持异常已在 RFDC/TIME 路径中随 center 映射变化，而不是 SPEC-only 路径单独产生。
- `center=122.88MHz` DC case：raw TIME target SNR 约 `36.72dB`，但 AC/mean-removed target SNR 约 `5.90dB`；因此 target 落到 DC 时必须看 raw 指标，不能用去均值后的 AC 指标判定 spur 消失。
- repeated apply / SYSREF 对照：经过 SNR 过滤后，`nco_repeat_2` 中 CH3/CH4 相对 phase 分别变化约 `-144.07deg` / `+101.99deg`；`sysref_pulse` 中 CH4 相对 phase 变化约 `-160.91deg`。这不是低 SNR 噪声相位触发，分类时已过滤低于 `12dB` 的通道。

审计后恢复门禁：

- JSON：`reports/board/stage27i_restore_after_100m_spur_taxonomy_audit_20260707.json`
- log：`reports/board/stage27i_restore_after_100m_spur_taxonomy_audit_20260707.log`
- 分类：`STAGE27H_TIME_SPEC_100MHZ_FFT_FULLRATE_BOARD_PASS`
- `CORE_VERSION=0x00010029`
- TIME `481072.5 pps`，SPEC `481072.0 pps`，合计 T510 UDP payload `64040.337920 Mbps`，错误列表为空。

本轮结论边界：

- 如果先不考虑 `200MHz`，`100MHz` clean evidence 已经不支持“固定绝对 RF/单纯板级耦合在整个观测中心范围内稳定存在”的简单解释。
- 更优先的下一步是继续查 RFDC ADC mixer/NCO/SYSREF/sideband 映射和 `center` 相关行为；必要时在 Stage 27i 内增加更靠近 RFDC AXIS 原始 lane 的诊断 tap，但仍不开 27j。

## Stage 27i RFDC mixer/NCO/SYSREF event audit

为继续拆分 `rfdc_mixer_nco_sideband_suspect`，已新增 Stage 27i `100MHz BW` 专用 RFDC mixer event audit。该入口继续使用 `CORE_VERSION=0x00010029` 诊断 bitstream，默认外部 `10MHz` + 外部 `PPS`，不改 RTL、不重建 bitstream、不使用 notch/bin mask/降速/thinning/显示隐藏；`200MHz` 不参与本轮分类。

脚本和默认命令：

- 脚本：`scripts/pynq_stage27i_rfdc_mixer_event_audit.py`
- 底层入口：`scripts/pynq_stage27h_rfdc_spur_audit.py --stage27i-rfdc-mixer-event-audit`
- 默认 JSON：`reports/board/stage27i_rfdc_mixer_event_audit_external_pps_YYYYMMDD.json`
- 默认物理状态：`dac_adc_loopback_restored_external_10mhz_pps`
- 默认同步：外部 `10MHz` + 外部 `PPS`

受控 case：

- 首尾 `force-zero` sentinel，确认 RFDC AXIS 后置诊断 mux 仍能清除 target。
- `100MHz TIME_ONLY` center baseline：`100/120/122.88/130/140MHz`。
- 每个 center 后连续两次 repeat apply，复查生产 observation 路径中的 `UpdateEvent(EVENT_MIXER)` + `ResetNCOPhase()` 是否改变 target SNR 或相对通道相位。
- 每个 center 后执行一次 explicit SYSREF pulse，再采集 TIME target/SNR/phase。

分类语义：

- `mixer_event_phase_sensitive`：重复 RFDC mixer/NCO apply 后 target power 或高 SNR 通道相对 phase 显著改变。
- `sysref_sensitive`：explicit SYSREF pulse 后 target power 或相对 phase 显著改变。
- `center_sideband_mapping_sensitive`：clean `100MHz` center baseline 中，target 只在部分 center 命中。
- `rfdc_internal_or_adc_frontend_remaining`：force-zero 可清除，但 repeat apply/SYSREF/center baseline 未显示可操作的软件事件敏感性。
- `stage27i_mixer_event_inconclusive`：case 未 clean、force-zero sentinel 失效、readback 缺失或 target 证据不足。

运行纪律：

- audit 前先 fresh-download 跑 2 秒 Stage 27h/27i validator，确认 external `10MHz` + external `PPS`、diag `0x0000ff00`、`TIME_SPEC 100MHz` 满速通过。
- audit 后再次 fresh-download 跑 2 秒或 10 秒 validator，确认恢复 `STAGE27H_TIME_SPEC_100MHZ_FFT_FULLRATE_BOARD_PASS`。
- 如果该软件-only audit 仍不能切开边界，下一步才进入 Stage 27i 诊断 bitstream，在 RFDC AXIS preview/raw lane 后、science selector/TIME/SPEC split/diag force-zero mux 前增加最小 raw-lane witness；该 witness 只作为诊断入口，不进入生产 Jupyter/Rust/Web 或生产验收主线。

实际运行结果：

- 审计前第一次门禁 JSON：`reports/board/stage27i_mixer_event_pre_validator_20260707.json`，分类为 FAIL，原因是命令默认期望 `CORE_VERSION=0x00010028`，而当前 Stage 27i 诊断 bitstream 为 `0x00010029`；该轮不作为链路失败证据。
- 审计前重跑门禁 JSON：`reports/board/stage27i_mixer_event_pre_validator_retry_20260707.json`
- 审计前重跑门禁：`STAGE27H_TIME_SPEC_100MHZ_FFT_FULLRATE_BOARD_PASS`，`CORE_VERSION=0x00010029`，TIME `481038.5 pps`，SPEC `481040.0 pps`，合计 T510 UDP payload `64035.944960 Mbps`。
- Audit JSON：`reports/board/stage27i_rfdc_mixer_event_audit_external_pps_20260707.json`
- Audit log：`reports/board/stage27i_rfdc_mixer_event_audit_external_pps_20260707.log`
- 顶层结果：`ok=true`，`invalid_cases=[]`，RFDC readback mismatch 为空。
- 分类：`mixer_event_phase_sensitive`
- 分类原因：重复 RFDC mixer/NCO apply 后，target 的高 SNR 通道相对 phase 发生显著变化。

关键证据：

- Force-zero sentinel 生效：`force_zero_clears_target=true`，继续证明后级 TIME/SPEC/UDP/Rust/Web 不是生成源。
- center baseline：`100/120/122.88/130MHz` 均命中 target，TIME effective target SNR 分别约 `41.35/40.00/38.11/29.49dB`；`140MHz` 低于门限，SNR 约 `6.17dB`。
- repeat apply 敏感性：`center=130MHz` 的第二次 repeat apply 中，CH3 相对 CH1 的 target phase 相对 baseline 改变约 `-129.67deg`，超过 `45deg` 门限，且参与比较的通道均经过 `12dB` SNR 过滤。
- SYSREF pulse：本轮未产生超过门限的 target power 或相对 phase 敏感性，`sysref_sensitivity=[]`。

审计后恢复门禁：

- 第一次恢复 JSON：`reports/board/stage27i_restore_after_mixer_event_audit_20260707.json`，分类为 FAIL，原因是 CMAC/QSFP ready 窗口内 `CMAC_TX_NOT_READY` / `TX_STILL_DRY_RUN`；该轮诊断寄存器已恢复默认关闭。
- 重跑恢复 JSON：`reports/board/stage27i_restore_after_mixer_event_audit_retry_20260707.json`
- 重跑恢复门禁：`STAGE27H_TIME_SPEC_100MHZ_FFT_FULLRATE_BOARD_PASS`，TIME `481042.5 pps`，SPEC `481040.0 pps`，合计 T510 UDP payload `64036.211200 Mbps`，错误列表为空。

本轮结论边界：

- `100MHz` production-relevant 证据已经进一步支持 RFDC mixer/NCO event path 与该 spur 的 phase 行为相关。
- 当前没有证据支持 SYSREF pulse 是主触发因素；也没有 RFDC readback mismatch。
- 下一步如果继续软件定位，应集中比较 RFDC mixer `EventSource`/`UpdateEvent`/`ResetNCOPhase` 的具体调用顺序；如果软件证据仍不足，再进入 Stage 27i 诊断 bitstream raw-lane witness，不开 27j。

## Stage 27i RFDC mixer EventSource/UpdateEvent sequence audit

为继续拆分 RFDC mixer/NCO event path，已在 Stage 27i 内增加 RFDC mixer `EventSource`、`UpdateEvent(EVENT_MIXER)` 和 `ResetNCOPhase()` 顺序审计。该轮仍使用 `CORE_VERSION=0x00010029` 诊断 bitstream，默认外部 `10MHz` + 外部 `PPS`，不改 RTL、不重建 bitstream，不使用 notch/bin mask/显示隐藏/降速/thinning。

实现修正：

- `python/t510_fengine.py` 的生产默认 sequence 保持 `sysref_reset_before_pulse` 不变。
- 诊断 API 增加 `rfdc_mixer_sequence`，支持 `sysref_reset_before_pulse`、`sysref_no_reset`、`tile_update_then_reset`、`tile_reset_then_update`、`tile_update_no_reset`。
- 早期 exploratory run 证明 `EVNT_SRC_IMMEDIATE=0` 和 `EVNT_SRC_SLICE=1` 均被当前 4GSPS ADC block 拒绝，错误为 `Invalid Event Source`；因此最终 clean 矩阵只使用 RFDC 接受的 `EVNT_SRC_SYSREF=3` 与 `EVNT_SRC_TILE=2`。

实际运行结果：

- 审计前门禁 JSON：`reports/board/stage27i_mixer_sequence_sysref_tile_pre_validator_20260707.json`
- 审计前门禁：`STAGE27H_TIME_SPEC_100MHZ_FFT_FULLRATE_BOARD_PASS`，TIME `481024.0 pps`，SPEC `481024.0 pps`，合计 T510 UDP payload `64033.914880 Mbps`。
- Audit JSON：`reports/board/stage27i_rfdc_mixer_sequence_sysref_tile_audit_external_pps_20260707.json`
- Audit log：`reports/board/stage27i_rfdc_mixer_sequence_sysref_tile_audit_external_pps_20260707.log`
- 顶层结果：`ok=true`，`classification_cases_valid=true`，`invalid_cases=[]`，RFDC readback mismatch 为空。
- 分类：`mixer_eventsource_sensitive`
- 分类原因：TILE `UpdateEvent(EVENT_MIXER)` sequence 与默认 SYSREF sequence 相比，会改变 target 的高 SNR 通道相对 phase。

关键证据：

- Force-zero sentinel 继续生效：`force_zero_clears_target=true`。
- target 命中范围保持 center 相关：`100/122.88/130MHz` 命中，`140MHz` 低于 `12dB` 门限。
- `center=100MHz`：SYSREF 与 TILE sequence 均命中 target，TIME effective target SNR 约 `39.10..39.92dB`；target power 没有被 TILE event source 消除。
- `center=122.88MHz`：target 落近 DC，必须使用 raw 指标；SYSREF 与 TILE sequence 的 raw/effective target SNR 约 `36.35..36.63dB`。
- `center=130MHz`：SYSREF 与 TILE sequence 均命中，SNR 约 `27.07..28.02dB`。
- `center=140MHz`：所有 SYSREF/TILE sequence 均低于门限，SNR 约 `4.87..7.70dB`。
- `sysref_no_reset` 相对默认 `sysref_reset_before_pulse` 未产生超过门限的敏感性，`reset_sensitivity=[]`。
- TILE 分支产生 9 条相对相位敏感性证据。例如：
  - `center=100MHz`、`tile_update_no_reset`：CH0/CH2/CH4/CH5/CH6/CH7 相对 phase 变化约 `98.48/97.61/-138.60/-149.96/114.45/-123.33deg`。
  - `center=122.88MHz`、`tile_reset_then_update`：CH2/CH3/CH5/CH6 相对 phase 变化约 `-142.92/73.41/144.93/144.49deg`。
  - `center=130MHz`、`tile_reset_then_update`：CH2/CH3/CH5/CH6/CH7 相对 phase 变化约 `104.02/161.77/111.83/-135.58/84.50deg`。

审计后恢复门禁：

- 恢复 JSON：`reports/board/stage27i_restore_after_mixer_sequence_sysref_tile_audit_20260707.json`
- 恢复门禁：`STAGE27H_TIME_SPEC_100MHZ_FFT_FULLRATE_BOARD_PASS`，TIME `481039.0 pps`，SPEC `481037.5 pps`，合计 T510 UDP payload `64035.811840 Mbps`。

本轮结论边界：

- 该 spur 的存在和功率仍不能由 TIME/SPEC/UDP/Rust/Web、SPEC FFT-only packetizer 或 UI 解释；force-zero 继续证明源头在 RFDC AXIS diagnostic mux 之前。
- TILE event source 并不能消除 `122.88MHz` target，但会显著改变高 SNR 通道的相对 phase，说明 RFDC mixer/NCO event alignment 参与了观测相位。
- `EVNT_SRC_IMMEDIATE` 和 `EVNT_SRC_SLICE` 对当前 4GSPS ADC 不可用；后续不要把这两类 exploratory run 作为物理结论。
- 下一步应继续在 Stage 27i 内查 RFDC ADC mixer/NCO/Nyquist/QMC/MTS 配置细节和 raw-lane witness；如果需要改 RTL，只能增加诊断可观测性，不开 27j，也不能通过滤波、忽略 target bin、降低速率或恢复 decimation 掩盖 spur。

## Stage 27i RFDC raw-lane witness 诊断准备

本轮继续在 Stage 27i 内推进，不开 27j。目的不是替代 Stage 27h/27i 生产 bitstream，而是增加一个更靠近 RFDC AXIS adapter 输入边界的诊断证据，用于回答：

- `122.88MHz` target 是否在 RFDC raw lane 组合后已经存在；
- raw lane、production TIME、FFT-only SPEC 是否看到同一 target-bin 行为；
- Stage 27i `adc_force_zero`/`adc_force_hold`/`adc_channel_mask` 清掉 production TIME/SPEC 时，pre-diag raw witness 是否仍能看到原始 target。

设计约束：

- 诊断 core version bump 到 `0x0001002A`，仅标记为 Stage 27i diagnostic。
- `T510_STAGE27H_PRODUCTION_ONLY` 生产范围保持 24 flows、TIME `4300..4307`、SPEC `4308..4323`、FFT-only SPEC `256ch x 1 time x 16 blocks`。
- 27h production build 仍不编译 raw witness；只有设置 `T510_STAGE27I_RAW_WITNESS=1` 的 27i 诊断 build 编译 `rfdc_axis_raw_witness_capture`。
- raw witness tap 已从原来的 production preview 口移到 `rfdc_adc_axis_adapter` 内部 pre-diag raw preview 输出；该输出不受 `diag_force_zero`、`diag_force_hold` 和 `diag_channel_mask` 影响，只保留 RFDC active port mask。
- `feng_ctrl_axi` 在 `RAW_WITNESS_DIAGNOSTIC=1` 时开放 `0xe200` 控制/状态和 `0xe800..0xf7ff` capture buffer；27h production 下这些窗口仍为 archived/no-op。

新增入口：

```bash
scripts/stage27i_raw_witness_timing_closure_iter.sh
scripts/stage27i_raw_witness_write_bitstream.sh
scripts/pynq_stage27i_raw_lane_witness_audit.py
```

预期板端审计流程：

```bash
cd /home/xilinx/t510_fengine_bringup
source /etc/profile.d/xrt_setup.sh
printf "%s\n" "xilinx" | sudo -S -p "" -E /usr/local/share/pynq-venv/bin/python3 \
  scripts/pynq_stage27i_raw_lane_witness_audit.py
```

审计默认条件：

- 外部 `10MHz` + 外部 `PPS`；
- DAC-ADC 回环线恢复；
- `bandwidth=100MHz`，`output_mode=TIME_SPEC`；
- DAC amplitude `0`，DAC enable mask `0xff`；
- center 矩阵 `100/122.88/130/140MHz`；
- 开始/结束各跑一次 `adc_force_zero` sentinel。

分类解释：

- `raw_lane_matches_time_spec`：pre-diag raw lane、production TIME、FFT-only SPEC 在 clean case 中看到同一 target-bin 行为，说明后续 adapter/science split/SPEC UDP/Rust Web 不是 spur 生成源。
- `raw_lane_time_spec_mapping_suspect`：raw lane 与 production TIME/SPEC 不一致，应转查 RFDC AXIS adapter、channel/lane mapping 或 science selector。
- `raw_lane_witness_inconclusive`：raw witness capture、clean gate、force-zero sentinel 或 target SNR 证据不足。

注意：`center=122.88MHz` 时 target 落在 DC 附近，TIME/raw 的 AC 去均值指标可能把 DC 分量抑掉；该 case 必须同时记录 raw/DC target 指标，不能用 AC 指标单独判断 target 消失。

## Stage 27i RFDC raw-lane witness 审计结果

截至 2026-07-07 CST，Stage 27i raw-lane witness 诊断 bitstream 已完成 timing、`write_bitstream`、PYNQ 发布和板端审计。本轮仍只作为 Stage 27i 诊断，不替代 Stage 27h `0x00010028` 生产基线，也不改变 `TIME_SPEC 100MHz`、24 flows、FFT-only SPEC 满速目标。

构建与发布证据：

- 诊断版本：`CORE_VERSION=0x0001002A`。
- Vivado fast timing closure routed DCP：`reports/board/stage27i_raw_witness_timing_closure_iter_routed_latest.dcp`。
- route timing：`WNS=+0.051387ns`，routing errors `0`。
- bitstream SHA256：`4066cc2b591d74c83c34ea49f9d0298a0202aa685b9ebc8b6b441614cddb70f3`。
- PYNQ 发布后远端 `overlay/t510_fengine.bit` 与 bring-up root `t510_fengine.bit` SHA 均匹配。

板端 raw-lane alias 审计产物：

- JSON：`reports/board/stage27i_raw_lane_witness_alias_audit_external_pps_20260707.json`。
- log：`reports/board/stage27i_raw_lane_witness_alias_audit_external_pps_20260707.log`。
- 顶层结果：`ok=true`，`invalid_cases=[]`。
- 分类：`raw_lane_decim2_alias_matches_time_spec`。
- 分类原因：raw-lane direct view 与 production TIME/SPEC 不一致，但按 RTL `science_rate_selector` 的 `100MHz` decim2 规则取偶数样点后，raw-lane decim2 model 与 production TIME/SPEC 的 target-bin 行为一致。
- force-zero 边界：`force_zero_boundary_ok=true`。开始和结束的 `adc_force_zero` sentinel 均把 production TIME/SPEC target 清零，而 pre-diag raw witness 仍可看到 raw primary peak，证明 raw witness tap 位于诊断 force-zero mux 之前。

关键 case 证据：

- `center=100MHz`：
  - raw-lane direct target `122.88MHz` 未通过，target SNR 约 `1.84dB`；
  - raw-lane direct primary peak 在 RF 约 `-0.02MHz`，baseband 约 `-100.02MHz`，SNR 约 `36.89dB`；
  - raw-lane `rtl_decim2_model` target 通过，SNR 约 `33.41dB`，primary peak 在 RF 约 `122.89MHz`、baseband 约 `+22.89MHz`；
  - production TIME target 通过，SNR 约 `39.42dB`；
  - FFT-only SPEC target 通过，SNR 约 `42.43dB`。
- `center=130MHz`：
  - raw-lane direct target `122.88MHz` 未通过，target SNR 约 `-0.93dB`；
  - raw-lane direct primary peak 在 RF 约 `245.74MHz`，baseband 约 `+115.74MHz`，SNR 约 `20.54dB`；
  - raw-lane `rtl_decim2_model` target 通过，SNR 约 `17.40dB`；
  - production TIME target 通过，SNR 约 `24.24dB`；
  - FFT-only SPEC target 通过，SNR 约 `25.41dB`。
- `center=140MHz`：
  - raw-lane direct、raw-lane decim2 model、production TIME 和 FFT-only SPEC 均低于 target SNR 门限；
  - 该 case 支持 decim2 alias 模型与 production 行为一致，而不是单纯显示层或 SPEC-only 误解。
- `center=122.88MHz` 是 DC 特殊 case，target 落在 DC 附近；仍需使用 raw/DC 指标，不能用 AC 去均值后的指标单独判断 target 消失。

审计后的恢复门禁：

- JSON：`reports/board/stage27i_restore_after_raw_lane_alias_audit_20260707.json`。
- 分类：`STAGE27H_TIME_SPEC_100MHZ_FFT_FULLRATE_BOARD_PASS`。
- 速率：TIME `481040.5 pps`，SPEC `481040.0 pps`，合计 T510 UDP payload `64036.07808 Mbps`。
- drop/error/XFFT 增量：`time_dropped_count=0`、`spec_dropped_count=0`、`tx_route_error_count=0`、`tx_route_miss_count=0`、`pfb_overflow_count=0`、`pfb_xfft_event_count=0`、`pfb_xfft_tlast_missing_count=0`、`pfb_xfft_tlast_unexpected_count=0`、`pfb_xfft_data_out_halt_count=0`、`pfb_capture_backpressure_count=0`。
- 诊断默认恢复：`stage27i_diag_control=0x0000ff00`，`adc_force_zero=0`，`adc_force_hold=0`，`adc_channel_mask=0xff`，`dac_gate=0`，`stage27i_diag_disabled=1`。

当前结论边界：

- `122.88MHz` production target 不是 raw-lane direct view 中同一绝对 RF 的主峰；它由 raw full-rate 分量经过 `100MHz` PL decim2 alias 后出现在 production TIME/SPEC 中。
- `center=100MHz` 时，raw full-rate 的 RF 约 `0MHz`、baseband `-100.02MHz` 分量，经 decim2 后折叠到 production baseband `+22.86/+22.89MHz`，即 RF `122.86/122.89MHz`。
- `center=130MHz` 时，raw full-rate 的 RF 约 `245.74MHz`、baseband `+115.74MHz` 分量，经 decim2 后折叠到 production baseband `-7.14MHz`，即 RF `122.86MHz`。
- 这也解释了此前 `200MHz SPEC_ONLY` 线索：200MHz 模式不走 PL decim2，因此 dominant peak 保持在 raw/full-rate 频率轴的低频端或高端附近；100MHz 模式直接抽样后把该 out-of-band 分量折叠到 `122.88MHz` target。
- 因此当前主要问题从“神秘固定 `122.88MHz` RF spur”收敛为“raw full-rate out-of-band/端点分量 + `science_rate_selector` 100MHz 未滤波 decim2 alias”。后级 TIME/SPEC/UDP/Rust/Web 不是生成源；production TIME/SPEC 对 alias 的观测是科学数据路径真实行为。
- 下一步修复方向应是 Stage 27i/27h 生产 science selector 的 anti-alias：为 `100MHz` decim2 和 `20MHz` decim8 增加合适的抗混叠滤波，或改用 RFDC 内部可验证的 decimation/filter 配置；不能用 notch、忽略 target bin、降低速率、恢复 SPEC thinning 或显示隐藏来通过。与此同时仍需追 raw full-rate 的 RF `0/245.76MHz` 端点分量来源，但它已经不是 production `122.88MHz` 位置的唯一解释。

## Stage 27i 100MHz anti-alias production candidate

截至 2026-07-07 CST，已在 Stage 27i 内实现 `100MHz BW` production science path 的抗混叠修复，不开 27j，不改变 TIME/SPEC 满速目标。

实现范围：

- 新增 `rtl/science_decim2_halfband_aa.sv`，用于 `100MHz` 模式的 PL anti-alias halfband FIR + decim2。
- FIR 规格：输入 `245.76MS/s`，输出 `122.88MS/s`，41 taps，Q1.17，线性相位，DC unity gain。
- 系数校验脚本：`scripts/stage27i_verify_aa100_halfband_coeffs.py`。当前校验结果：
  - passband `|f| <= 50MHz` ripple `0.01495dB`；
  - stopband `|f| >= 72.88MHz` attenuation `59.88dB`；
  - coefficient sum `131072`，即 Q1.17 unity gain。
- `science_rate_selector` 在 `T510_STAGE27I_ANTI_ALIAS` define 打开时，`BW_100MHZ` 使用新 FIR decim2；未打开 define 时保持旧裸 decim2，便于区分历史诊断 bit。
- `BW_200MHZ` 保持直通；`BW_20MHZ` 本轮仍不声明科学频谱闭合。
- `CORE_VERSION` 在 anti-alias candidate build 中 bump 到 `0x0001002B`。
- 新增 science MMIO：
  - `0xD054 SCIENCE_ANTIALIAS_STATUS`：bit8=`aa100_active`，bit9=`aa100_primed`，低 8 位为 tap count。
  - `0xD058 SCIENCE_ANTIALIAS_COEFF_VERSION`：当前为 `0xAA100041`。
- SPEC UDP header 的 `spec_status_flags` 改为产品状态语义，保留 bit8=`FFT-only`，新增 bit9=`AA100 active`；PFB/XFFT 内部状态仍从原 MMIO 读取，不再把整份内部 PFB 状态直接当作产品 header status。

脚本与 UI：

- 新增 Vivado wrapper：
  - `scripts/stage27i_antialias_timing_closure_iter.sh`
  - `scripts/stage27i_antialias_write_bitstream.sh`
- 新增板端验收 wrapper：
  - `scripts/pynq_stage27i_antialias_spur_acceptance.py`
  - 底层入口：`scripts/pynq_stage27h_rfdc_spur_audit.py --stage27i-antialias-acceptance`
- `scripts/pynq_stage27h_time_spec_fft_fullrate.py` 默认 expected core version 更新为 `0x0001002B`。
- `python/t510_fengine.py` 的 Stage 27h/27i board validator 在 `100MHz` 模式下默认要求 `aa100_active=1`、`aa100_primed=1`、tap count `41`、coeff version `0xAA100041`。
- notebook 15 更新为 Stage 27i anti-alias candidate 入口，仍只保留生产控制和生产预览。
- Rust Web 显示 SPEC header 中的 `AA100 active/off` 状态；不隐藏任何 bin，不做 notch。

本地验证：

- `python3 scripts/stage27i_verify_aa100_halfband_coeffs.py`：PASS。
- `python3 -m py_compile python/t510_fengine.py scripts/pynq_stage27h_time_spec_fft_fullrate.py scripts/pynq_stage27h_rfdc_spur_audit.py scripts/stage27i_verify_aa100_halfband_coeffs.py`：PASS。
- `python3 -m json.tool notebooks/15_stage27h_time_spec_fft_fullrate_control.ipynb >/dev/null`：PASS。
- `bash -n scripts/pynq_publish_stage27h.sh scripts/stage27i_antialias_timing_closure_iter.sh scripts/stage27i_antialias_write_bitstream.sh scripts/stage27h_timing_closure_iter.sh scripts/stage27h_write_bitstream_from_timing_closure.sh scripts/run_xsim_batch.sh`：PASS。
- `cargo test -q --manifest-path rust/t510_time_rx/Cargo.toml`：PASS，28 tests。
- `cargo build --release --manifest-path rust/t510_time_rx/Cargo.toml`：PASS。
- `node --check` embedded Rust Web JS：PASS。
- XSim：
  - `EXTRA_XVLOG_DEFINES=T510_STAGE27I_ANTI_ALIAS ./scripts/run_xsim_batch.sh tb_science_rate_selector`：PASS。
  - `EXTRA_XVLOG_DEFINES=T510_STAGE27I_ANTI_ALIAS ./scripts/run_xsim_batch.sh tb_feng_ctrl_axi`：PASS。
  - `EXTRA_XVLOG_DEFINES=T510_STAGE27I_ANTI_ALIAS ./scripts/run_xsim_batch.sh tb_axi4_to_axil_bridge`：PASS。
  - `EXTRA_XVLOG_DEFINES=T510_STAGE27I_ANTI_ALIAS ./scripts/run_xsim_batch.sh tb_time_udp_cmac512 tb_spec_udp_cmac512 tb_t510_fengine_top_smoke`：PASS for these three.
  - `tb_pfb_channelizer` standalone 当前仍 FAIL，输出计数为 0；不带 `T510_STAGE27I_ANTI_ALIAS` 单独重跑也同样 FAIL，因此目前归类为本轮 anti-alias 之外的既有 PFB/channelizer 仿真问题。生产顶层 smoke 和 TIME/SPEC UDP targeted XSim 已通过，后续仍需单独修复该 standalone TB 或其仿真模型。

Vivado 与 bitstream：

- `scripts/stage27i_antialias_timing_closure_iter.sh` 已完成 route，产物为 `reports/board/stage27i_antialias_timing_closure_iter_routed_latest.dcp`。
- route 后 timing：`WNS=+0.003ns`、`TNS=0`、route errors `0`。
- `scripts/stage27i_antialias_write_bitstream.sh` 已完成 `write_bitstream`。
- local/PYNQ bitstream SHA256：`8b1a9406688a79b53e4f2c0e02aa98385db1ec54f6e7ea9076a561d4f7eaf5b6`。

板端与主机验证：

- Board 10 秒 post-acceptance JSON：`reports/board/stage27i_antialias_time_spec_100mhz_10s_post_acceptance_20260707.json`。
- Board 分类：`STAGE27H_TIME_SPEC_100MHZ_FFT_FULLRATE_BOARD_PASS`，`CORE_VERSION=0x0001002B`。
- Board 速率：TIME `480173.2pps`、SPEC `480172.8pps`，合计 T510 UDP payload `63920.629760Mbps`。
- Board 状态：`aa100_active=1`、`aa100_primed=1`、tap count `41`、coeff `0xAA100041`；RFDC/science/TIME/SPEC/TX route/XFFT/backpressure 错误增量均为 `0`；16 条 SPEC route 全命中。
- Stage 27i anti-alias acceptance JSON：`reports/board/stage27i_antialias_spur_acceptance_20260707.json`。
- Acceptance 分类：`stage27i_100m_antialias_spur_suppressed`。零幅度生产 case 下 `122.88MHz` target 均低于 `12dB` SNR 门限：
  - `zero_amp_enable_ff`：TIME `4.63dB`、SPEC `4.45dB`；
  - `zero_amp_enable_00`：TIME `4.25dB`、SPEC `4.77dB`；
  - `zero_amp_dac_nco_60`：TIME `3.47dB`、SPEC `5.47dB`；
  - `zero_amp_dac_nco_100`：TIME `4.54dB`、SPEC `5.06dB`。
- Reference tone：`60.010MHz` 在 TIME/SPEC 中正常落点；TIME peak `59.92MHz`、SNR `69.10dB`，SPEC peak `60.01MHz`、SNR `72.37dB`。
- Host 10 秒 JSON：`reports/board/stage27i_antialias_host_rust_rx_10s_post_acceptance_20260707.json`。
- Host 分类：`HOST_STAGE27H_RUST_RX_PASS`，24 个 active workers，TIME `480063.93pps`、SPEC `479956.65pps`，合计 T510 UDP payload `63898.970071Mbps`。
- Host 窗口内 `app/ring/kernel/worker/hard NIC` drops 均为 `0`，TIME/SPEC seq/frame/sample0 gaps 均为 `0`；`netdev_rx_dropped_advisory=930` 仅按 advisory 记录。预览仍 active：display `2.89Hz`、spectrum `7.98Hz`。
- 本轮主机使用 `ens2f0np0` RX coalescing `rx-usecs=8`、`rx-frames=32`；这是主机接收稳定性配置，不改变板端数据率或生产 wire contract。

结论边界：

- `100MHz` production TIME/SPEC 中由 raw full-rate 端点/带外分量经裸 decim2 折叠出的 `122.88MHz` target 已被 PL anti-alias FIR 抑制到门限以下。
- 本轮不声明 `20MHz` decim8 科学频谱闭合；`200MHz` 仍为直通路径，历史 `200MHz SPEC_ONLY` 现象只保留为 RFDC/sideband 线索。
- raw/full-rate RF `0/245.76MHz` 端点分量来源仍需继续定位；本轮只是阻止它折叠进 `100MHz` production TIME/SPEC 带内。

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
