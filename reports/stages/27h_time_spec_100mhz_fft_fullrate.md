# Stage 27h：TIME_SPEC 100MHz 仅 FFT 全速 SPEC 收敛

## 阶段目标

Stage 27h 接在 Stage 27g 之后，目标是移除 27g 为收敛而保留的 `/32` SPEC 节拍，把 `TIME_SPEC 100MHz` 推到仅 FFT、全速 SPEC 的生产形态。

本阶段通过条件是板端和主机同时通过：

- Vivado 完成布线、满足时序，生成比特流并导出 overlay。
- 板端加载 `CORE_VERSION=0x00010026`。
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
  - `CORE_VERSION` 提升到 `0x00010026`。
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

截至 2026-07-01 CST，Stage 27h 时序收敛和比特流导出已完成。

- 布线后时序已满足：
  - `ROUTED_WNS=+0.014838797ns`
  - `TNS=0.000ns`
  - `WHS=+0.010ns`
  - `THS=0.000ns`
- 比特流后时序已满足：
  - `POST_BIT_WNS=+0.015ns`
  - `POST_BIT_WHS=+0.010ns`
- 布线状态 clean：
  - `172486/172486` 条可布线网络全部完成布线
  - routing errors `0`
- 导出 overlay 比特流：
  - `overlay/t510_fengine.bit`
  - SHA256 `e9f5bbf4a10132dd82857904790bd49761239ed4d3476fbde3236841b1094e82`

仍需记录的生产风险：

- Bitgen 报 Vivado `12-1790` evaluation license warning，原因是 `cmac_an_lt@2020.05` 使用 `design_linking` license；`cmac_usplus@2020.05` 使用 bought license。该 warning 未阻塞比特流生成，但最终生产 license 姿态仍需单独确认。

## 板端 10 秒验收

板端门禁产物：

- JSON：`reports/board/stage27h_time_spec_100mhz_fft_fullrate_board_streaming_fix.json`
- 分类：`STAGE27H_TIME_SPEC_100MHZ_FFT_FULLRATE_BOARD_PASS`
- `CORE_VERSION=0x00010026`
- 模式：`TIME_SPEC`
- 带宽：`100MHz`
- TIME 速率：`480544.2 pps`，T510 UDP 载荷 `31985.021952 Mbps`
- SPEC 速率：`480544.2 pps`，T510 UDP 载荷 `31985.021952 Mbps`
- 合计 T510 UDP 载荷：`63970.043904 Mbps`
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
    --output reports/board/stage27h_time_spec_100mhz_fft_fullrate_board_streaming_fix.json
```

## 主机 10 秒验收

主机门禁产物：

- JSON：`reports/board/stage27h_rust_rx_time_spec_100mhz_perf_coalesce_rawdrop_seventh.json`
- 分类：`HOST_STAGE27H_RUST_RX_PASS`
- 接收器：`fanout=port`，`24` 个活跃工作线程，`8` 条 TIME 流，`16` 条 SPEC 流
- SPEC 布局：`27h`
- `last_spec_chan_count=256`
- TIME 速率：`478994.172693 pps`
- SPEC 速率：`479835.254612 pps`
- 合计 T510 UDP 载荷：`63819.686681 Mbps`
- 丢包/错误增量：parse `0`，ring `0`，worker ring `0`，kernel `0`，NIC `0`
- TIME 间断：seq/frame/sample0 全部 `0`
- SPEC 间断：seq/frame 全部 `0`
- 预览 active：
  - 波形 `250` 次更新，`24.999839 Hz`
  - 频谱 `4053` 次更新，`400.440205 Hz`

这次通过的 10 秒主机门禁使用了 `ens2f0np0` 上的生产 RX 调优：

- CPU governor 设置为 `performance`。
- NIC RX coalescing 设置为 `adaptive-rx off rx-usecs 2 rx-frames 32`。
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
  --output reports/board/stage27h_rust_rx_time_spec_100mhz_perf_coalesce_rawdrop_seventh.json
```

至此，Stage 27h `TIME_SPEC 100MHz` 仅 FFT、全速 SPEC 的短窗口生产收敛已经闭合。剩余工作是长时间 soak 和下游科学系统集成，不是放宽 Stage 27h 的速率门槛。

## 60 秒短稳验证

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

通过 60 秒主机门禁所需的更严格调优已经写入 `scripts/host_stage27h_rx_fanout_tune.sh`：

- CPU governor：`performance`
- raw PREROUTING drop：生产 UDP 端口 `4300..4323`
- netdev budget/backlog：`1000`、`8000us`、`250000`
- RX coalescing：`1us/16 frames`
- fanout 工作线程：`24` 个并自动绑核

早期 60 秒尝试失败时没有降低 27h 数据目标：

- 一次运行出现 `/sys/class/net` 的 `rx_dropped=14`，但 ethtool 丢包计数器未增长，生产 TIME/SPEC 间断仍为 `0`。
- 一次运行中接收器显示配置被外部切到 `200MHz`，导致选择/检测带宽不一致，并让 TIME `sample0` 间断统计失效；当时 seq/frame 间断仍为 `0`。

当前 60 秒短稳验证已闭合，但它不能替代 10 分钟、1 小时或过夜 soak。

## 当前边界

Stage 27h 可以声明：

- `TIME_SPEC 100MHz` 仅 FFT、全速 SPEC 生产路径已经通过 Vivado 时序和比特流导出。
- 板端 10 秒门禁和 60 秒短稳验证均通过。
- 主机 24 流接收器 10 秒门禁和 60 秒短稳验证均通过。
- TIME 与 SPEC 均接近 `480kpps`。
- 合计 T510 UDP 载荷稳定超过 `63Gbps`。
- 波形与频谱预览在主机 Web/Jupyter 生产路径中可用。

Stage 27h 不能声明：

- 10 分钟、1 小时、过夜长稳已经完成。
- 科学级 4-tap PFB 幅相/功率标定完成。
- FFT-only 频谱已经等价于最终科学 PFB 产品。
- 交换机、DGX/X-engine、ARP/VLAN/PTP 或全 RF 频段标定通过。
- 生产 license 风险已经最终解决。

## 27h 后续工作建议

Stage 27h 之后应保持全速目标不动，按生产化顺序继续推进：

1. 复现性与长稳：
   - 先重复 60 秒板端和主机门禁，并用时间戳归档 JSON。
   - 继续做 10 分钟、1 小时、过夜三档 `TIME_SPEC 100MHz` 全速 soak。
   - soak 期间重点记录 TIME/SPEC 包速率、丢包/间断、预览刷新率、NIC 计数器、温度和 CMAC 链路状态。

2. 主机调优固化：
   - 将 `scripts/host_stage27h_rx_fanout_tune.sh` 中有效的 governor、netdev、coalescing、raw PREROUTING drop 变成可复现的生产配置。
   - 明确哪些设置由 systemd/sysctl/iptables/nftables 持久化，哪些仍保留为手动 bring-up 步骤。

3. 下游接收链路：
   - 在交换机、接收节点、DGX 或 X-engine 入口复现 24 流 `4300..4323` 的无丢包/无间断接收。
   - 增加 pcap 或 X-engine ingest 证据，证明 T510 头、TIME/SPEC seq/frame、SPEC `256ch x 1 time` block metadata 能被下游正确消费。

4. 科学质量：
   - 当前 Stage 27h 是仅 FFT 吞吐收敛，不是最终 4-tap PFB 科学标定。
   - 后续需要独立评估是否、何时、如何恢复科学级 PFB 幅相/功率标定；该工作不能通过重新引入 SPEC thinning 来牺牲 27h 已经闭合的全速门槛。

5. Jupyter 与 Rust Web：
   - notebook 15 继续作为生产控制/预览入口，只保留接收端 IP/端口/MAC、模式/带宽/中心频率、8 路 DAC-ADC 环回、DAC tone 频率/幅度/相位，以及 RF 还原波形和 FFT-only 频谱。
   - Rust Web 继续围绕 TIME 波形、F-engine 状态、频谱、瀑布图、活跃流/工作线程、丢包/间断和预览刷新率做生产显示，不恢复历史 debug 面板作为主界面。

## 推荐复现命令

本地：

```bash
python3 -m py_compile python/t510_fengine.py scripts/pynq_stage27h_time_spec_fft_fullrate.py scripts/host_stage27h_rust_rx_validate.py scripts/host_stage27e_rust_rx_validate.py
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
