# Stage 27g：TIME_SPEC 100MHz 生产收敛基线

## 阶段目标

Stage 27g 接在 Stage 27f 的生产范围收口之后，目标是把 `TIME/SPEC` 科学数据流和 Jupyter 生产控制/预览推到 `TIME_SPEC 100MHz` 的板端加主机闭环。

本阶段通过条件是：

- Vivado 完成布线、满足时序，并导出比特流和 overlay。
- PYNQ 板端 `TIME_SPEC 100MHz` 通过计数器门禁：TIME 和 64 条 SPEC 路由全覆盖，无 PFB overflow、SPEC/TIME 丢包、TX 路由 miss/error。
- 主机 Rust 接收器以 72 条流接收 `4300..4371`，`fanout=port`，无 parse/ring/kernel/NIC 丢包，无 TIME/SPEC seq/frame/sample 间断。
- Rust Web 波形与频谱预览均有实时更新。
- Jupyter 生产入口切到 notebook 14，只保留生产控制和生产预览，不再把 dry-run、raw witness、debug FFT、legacy/reduced SPEC 作为主验收线。

## 生产合约

- 最终核心版本：`CORE_VERSION=0x00010025`。
- 工作模式：`TIME_ONLY`、`SPEC_ONLY`、`TIME_SPEC`；`TIME_SPEC 200MHz` 继续拒绝。
- TIME 端口：`4300..4307`。
- SPEC 端口：`4308..4371`。
- 主机流数：`72`，其中 `8` 个 TIME 流、`64` 个 SPEC 流。
- SPEC 产品：`FENGINE_IQ16` (`0xf101`)。
- SPEC 布局：`4096` 个 channel，`64` 个 block，`64` 个 channel/block，`4` 个 spectrum-time，`8` 路输入，IQ16，每包 `8192B` 载荷加 `128B` T510 头。
- Stage 27g 仍使用 `/32` SPEC 节拍。它是已经通过的生产基线，但不是全速 SPEC 科学吞吐终点。

## 本轮完成

- Python API：
  - 新增 `configure_science_27g(...)`，复用 Stage 27f 全量 F-engine 线缆合约，默认配置 8 条 TIME 路由和 64 条 SPEC 路由。
  - 新增 `run_stage27g_time_spec_convergence_validation(...)`，默认验证 `TIME_SPEC 100MHz`，输出 `STAGE27G_TIME_SPEC_100MHZ_BOARD_PASS/FAIL`。
- PYNQ：
  - 新增 `scripts/pynq_stage27g_time_spec_convergence.py`，默认 `--matrix converge`，即 `time_spec:100`。
  - JSON 输出包含生产范围、路由覆盖、主机接收器下一步提示，fanout group 使用合法十六进制 `0x270`。
- 主机：
  - 新增 `scripts/host_stage27g_rx_fanout_tune.sh`，默认覆盖 72 个生产端口。
  - 新增 `scripts/host_stage27g_rust_rx_validate.py`，默认要求 8 条 TIME 流 + 64 条 SPEC 流、`TIME_SPEC 100MHz`、波形预览和频谱预览。
- Vivado：
  - 新增 `scripts/stage27g_time_spec_100mhz_bit_export_batch.tcl`，报告名使用 `stage27g_time_spec_100mhz_*`，负时序拒绝导出 overlay。
- Jupyter：
  - 新增 `notebooks/14_stage27g_time_spec_fengine_control.ipynb`。
  - 保留生产控制：接收端 IP/端口/MAC、源 IP/MAC、`TIME_ONLY/SPEC_ONLY/TIME_SPEC`、20/100/200 MHz 带宽、中心频率、8 路 DAC-ADC 环回、DAC 频率/幅度/每路相位、应用/启动/停止/板端门禁。
  - 保留生产预览：RFDC 预览 IQ 派生的 RF 还原波形、生产频谱、板端状态、Rust 接收器状态。
  - 不包含 dry-run、raw witness、coherence witness、debug FFT、legacy/reduced SPEC 主路径。
- Rust Web：
  - 页面标题和状态栏刷新为 Stage 27g TIME/SPEC 生产视图。
  - 顶部突出 TIME/SPEC 速率、流数、丢包/间断和预览刷新率。
- 发布：
  - `scripts/pynq_publish_stage27g.sh` 只同步 overlay、`python/`、27g 板端 validator、notebook 14 和 README。
  - `scripts/pynq_publish_jupyter_instrument.sh` 只发布 notebook 14。

## 本地验证

最终进入比特流导出前，本地检查覆盖 Python、notebook、shell、Rust 和重点 XSim：

```bash
python3 -m py_compile python/packet.py python/t510_fengine.py scripts/pynq_stage27g_time_spec_convergence.py scripts/host_stage27g_rust_rx_validate.py
python3 -m json.tool notebooks/14_stage27g_time_spec_fengine_control.ipynb >/dev/null
cargo test --manifest-path rust/t510_time_rx/Cargo.toml
cargo build --release --manifest-path rust/t510_time_rx/Cargo.toml
bash -n scripts/pynq_publish_stage27g.sh scripts/pynq_publish_jupyter_instrument.sh scripts/host_stage27g_rx_fanout_tune.sh
./scripts/run_xsim_batch.sh tb_axis_stream_duplicator tb_science_rate_selector tb_feng_ctrl_axi tb_axi4_to_axil_bridge tb_t510_fengine_top_smoke tb_spec_udp_cmac512 tb_time_udp_cmac512
```

重点仿真覆盖：

- `tb_axis_stream_duplicator`：SPEC 反压会同步压住共享 beat 的 TIME `tvalid`，避免重复 TIME 打包。
- `tb_science_stream_decimator`：验证 20/100/200 MHz 下 SPEC 选中/丢弃节拍。
- `tb_pfb_channelizer`：验证 XFFT 缩放计划和非 realtime ready/status 接口。
- `tb_spec_udp_cmac512`：验证 64 条 SPEC 路由、T510 头、`FENGINE_IQ16`、`nchan=4096`、`block_index=0..63`。
- `tb_t510_fengine_top_smoke`：验证生产 TIME/SPEC 能从顶层进入 CMAC 发送路径。

## Vivado 结果

最终 Stage 27g 比特流导出于 2026-06-28 00:04 CST 完成：

- Bit SHA256：`44127a1f33cb077edf31aa65973f2e17931b0126cc5e8c0d771cfc5f88f8bb87`。
- 导出门禁：`STAGE27G_TIME_SPEC_100MHZ: overlay export complete`。
- 布线状态：`271201 / 271201` 条可布线网络全部完成布线，routing errors `0`。
- 布线后时序：WNS `0.082 ns`，TNS `0.000 ns`，WHS `0.010 ns`，THS `0.000 ns`，所有用户时序约束满足。
- Utilization：CLB LUT `153034 / 425280` (`35.98%`)，CLB registers `134221 / 850560` (`15.78%`)，BRAM tile `516 / 1080` (`47.78%`)，DSP `107 / 4272` (`2.50%`)，URAM `0 / 80` (`0.00%`)，bonded IOB `18 / 152` (`11.84%`)。
- 导出产物：
  - `overlay/t510_fengine.bit`
  - `overlay/t510_fengine.hwh`
  - `overlay/t510_fengine.tcl`
  - `overlay/t510_fengine.manifest.txt`

仍需记录的生产风险：

- Bitgen 报 `CRITICAL WARNING: [Vivado 12-1790] Evaluation License Warning`，原因是 CMAC `cmac_an_lt@2020.05` 通过 `design_linking` license 启用，而 `cmac_usplus@2020.05` 使用 bought license。该 warning 未阻塞布线、时序或导出，但最终生产 license 姿态仍需单独确认。

## 板端收敛过程

Stage 27g 中间经历了多轮硬件失败，这些失败是后续 27h 设计取舍的依据。

第一轮加载旧路径时失败：

- 产物：`reports/board/stage27g_time_spec_100mhz_board.json`。
- 分类：`STAGE27G_TIME_SPEC_100MHZ_BOARD_FAIL`。
- 主要错误：`TX_STILL_DRY_RUN`、`FENGINE_OVERFLOW`、`SPEC_DROPPED`。
- 验证窗口 delta：
  - `time_packet_count=962005`
  - `spec_packet_count=35524`
  - `pfb_overflow_count=13661062`
  - `spec_dropped_count=59291991`
  - `time_dropped_count=0`
  - `tx_route_miss_count=0`
  - `tx_route_error_count=0`
- 64 条 SPEC 路由全覆盖，因此主要问题不是路由表，而是 F-engine/SPEC 生产路径无法持续消费。

第二轮正常下载新 overlay 后失败：

- 产物：`reports/board/stage27g_time_spec_100mhz_board_pynq_latest.json`。
- 核心版本：`0x00010022`。
- 主要错误：`FENGINE_OVERFLOW`、`FENGINE_XFFT_EVENT`、`SCIENCE_RATE_DROPPED`。
- 验证窗口 delta：
  - `time_packet_count=1864553`
  - `spec_packet_count=59776`
  - `pfb_overflow_count=15298560`
  - `pfb_xfft_event_count=15298560`
  - `science_dropped_beat_count=57752761`
  - `spec_dropped_count=0`
  - `time_dropped_count=0`
  - `tx_route_miss_count=0`
  - `tx_route_error_count=0`
- 失败点从下游 SPEC 丢包收窄到上游 F-engine/XFFT 和 science-rate 路径。

XFFT 缩放补丁后失败收窄：

- `pfb_fft_shift` 默认改为 `0x5556`，生成 XFFT schedule `24'h555556`。
- 产物：`reports/board/stage27g_time_spec_100mhz_board_pynq_latest.json`。
- 核心版本：`0x00010022`。
- 主要错误：`SCIENCE_RATE_DROPPED`。
- 验证窗口 delta：
  - `time_packet_count=1864565`
  - `spec_packet_count=59776`
  - `science_dropped_beat_count=57753638`
  - `pfb_overflow_count=0`
  - `pfb_xfft_event_count=0`
  - `spec_dropped_count=0`
  - `time_dropped_count=0`
  - `tx_route_miss_count=0`
  - `tx_route_error_count=0`
- 这证明数值 overflow 已被移除，但 TIME/SPEC 复制器与反压语义还需要修。

TIME/SPEC 复制器握手补丁后，Vivado 重新通过：

- Bit SHA256：`d8bcf121f1a5da75265b4fa41f5275e3fc49234a023d9d94a98ff7de40a27466`。
- 布线后时序：WNS `0.014 ns`，TNS `0.000 ns`，WHS `0.010 ns`，THS `0.000 ns`。
- 布线状态：`271019 / 271019` 全部完成布线，routing errors `0`。

对应板端 `CORE_VERSION=0x00010023` 失败：

- Bit SHA256：`41f4cf367bef1b92d1f7bd3ba81b2ed0c3a73955959da3360068a3f24eefd2aa`。
- 产物：`reports/board/stage27g_time_spec_100mhz_board_core0023_specdecim16_fail.json`。
- 分类：`STAGE27G_TIME_SPEC_100MHZ_BOARD_FAIL`。
- 主要错误：`SPEC_DROPPED`。
- 验证窗口增量：
  - `time_packet_count=962080`
  - `spec_packet_count=59776`
  - `science_dropped_beat_count=0`
  - `spec_dropped_count=22963`
  - `pfb_overflow_count=0`
  - `pfb_xfft_event_count=0`
  - `time_dropped_count=0`
  - `tx_route_miss_count=0`
  - `tx_route_error_count=0`
- 结论：上游 science-rate 丢包已消除，但 `/16` SPEC 节拍仍超过当时 PFB/F-engine 突发消费余量。

SPEC 节拍从 `/16` 改为 `/32` 后，`CORE_VERSION=0x00010024` 仍失败：

- Bit SHA256：`4b58a4fac324a132eb6f4359b3feb3ed72c0977ee0ef5d04b0c3a3980d2a6c74`。
- 产物：`reports/board/stage27g_time_spec_100mhz_board_core0024_latest.json`。
- 分类：`STAGE27G_TIME_SPEC_100MHZ_BOARD_FAIL`。
- 主要错误：`FENGINE_OVERFLOW`、`FENGINE_XFFT_EVENT`。
- 验证窗口增量：
  - `time_packet_count=962091`
  - `spec_packet_count=59264`
  - `science_dropped_beat_count=0`
  - `spec_dropped_count=0`
  - `pfb_data_halt_count=7486093`
  - `pfb_overflow_count=13906`
  - `pfb_xfft_event_count=13906`
  - `time_dropped_count=0`
  - `tx_route_miss_count=0`
  - `tx_route_error_count=0`
- 运行时把 `--pfb-fft-shift` 提到 `0xffff` 后仍失败，说明这不是简单数值缩放问题，而是 XFFT realtime/data-halt 行为和输出反压问题。

XFFT nonrealtime patch 后进入最终通过版本：

- `scripts/stage27f_create_fengine_xfft_ip.tcl` 将 F-engine XFFT IP throttle scheme 从 `realtime` 改为 `nonrealtime`。
- `rtl/pfb_channelizer.sv` 接入 nonrealtime XFFT ready/status 端口，并只在 valid/ready fire 时接受输出。
- PFB/XFFT 观测计数器拆分，用于区分 TLAST mismatch、数值 FFT overflow、output/status halt、capture 反压和 frame-sample0 overflow。
- 期望核心版本提升到 `CORE_VERSION=0x00010025`。

## 板端最终结果

最终比特流发布并在 PYNQ 上正常下载。此前一次 `--no-download` 尝试因板上仍运行 `CORE_VERSION=0x00010024` 而正确失败版本检查。

- 产物：`reports/board/stage27g_time_spec_100mhz_board_core0025_programmed_latest.json`。
- 分类：`STAGE27G_TIME_SPEC_100MHZ_BOARD_PASS`。
- 期望/实测核心版本：`0x00010025`。
- 用例错误/阻塞项：无。
- 验证窗口增量：
  - `time_packet_count=962155`
  - `spec_packet_count=30080`
  - `science_dropped_beat_count=0`
  - `spec_dropped_count=0`
  - `pfb_data_halt_count=26321880`
  - `pfb_overflow_count=0`
  - `pfb_xfft_event_count=0`
  - `pfb_xfft_fft_overflow_count=0`
  - `pfb_xfft_data_out_halt_count=0`
  - `pfb_xfft_status_halt_count=0`
  - `pfb_xfft_tlast_missing_count=0`
  - `pfb_xfft_tlast_unexpected_count=0`
  - `tx_frame_built_count=992162`
  - `tx_route_miss_count=0`
  - `tx_route_error_count=0`
- SPEC 路由覆盖：64 条路由全部启用并命中，endpoints `8..71`，`chan_count=64`。

`pfb_data_halt_count` 是 XFFT nonrealtime 反压观测计数器。最终门禁中它没有伴随 science 丢包、PFB/XFFT error event、路由 miss 或主机间断，因此不作为 Stage 27g 失败条件。

## 主机最终结果

生产 Rust 接收器使用 72 流 Stage 27g 命令运行：

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

产物：

- `reports/board/stage27g_host_fanout_tune_core0025.log`
- `reports/board/stage27g_rust_rx_core0025_72flow.log`
- `reports/board/stage27g_rust_rx_time_spec_100mhz_core0025_latest.json`

结果：

- 分类：`HOST_STAGE27G_RUST_RX_PASS`。
- 后端/fanout：`fanout`、`port`。
- 活跃工作线程：`32 / 32`，满足要求。
- 选择/检测带宽：`100 MHz / 100 MHz`。
- 10 秒验证增量：
  - `time_packet_delta=4867660`
  - `spec_packet_delta=152217`
  - `rx_time_packets_per_sec=479879.046`
  - `rx_spec_packets_per_sec=15000.611`
  - `parse_errors=0`
  - `ring_drops=0`
  - `worker_ring_drops=0`
  - `kernel_drops=0`
  - `nic_error_delta_sum=0`
  - TIME seq/frame/sample0/per-flow 间断全部为 `0`
  - SPEC seq/frame/per-flow 间断全部为 `0`
  - 缺失 TIME/SPEC 流：无
- 预览：
  - `waveform_updates=240`
  - `spectrum_updates=7960`
  - `display_update_hz=22.985`
  - `spectrum_update_hz=782.557`

Stage 27g 因此完成了当时定义的生产收敛：`TIME_SPEC 100MHz` 板端计数器门禁加主机 72 流无丢包/无间断门禁均通过。

## 关键解释

Stage 27g 通过后仍有一个明确边界：SPEC 输出数量低。主机实测 SPEC 约 `15000.611 pps`，而 TIME 约 `479879.046 pps`。这不是 UDP 路由或 CMAC 发包主链路损坏造成的：

- SPEC 路由覆盖完整，64 条路由全命中。
- `tx_route_miss_count=0`、`tx_route_error_count=0`。
- 主机无 parse/ring/kernel/NIC 丢包。
- TIME/SPEC seq/frame 间断均为 0。
- Rust Web 波形和频谱预览都在更新。

SPEC 数量低的直接原因是 Stage 27g 为了让 PFB/XFFT 生产链路收敛，保留了 `100MHz` 下 `/32` SPEC 节拍。也就是说，Stage 27g 证明的是生产控制、路由、UDP、主机接收器和预览链路能在 100MHz 模式下稳定工作；它没有证明 SPEC 全速科学吞吐已经达标。

这也是 Stage 27h 的直接动机：不能继续用 decimation/thinning 作为生产通过条件，必须把 SPEC 改为仅 FFT 全速输出，目标变为 TIME 约 `480kpps` 加 SPEC 约 `480kpps`，合计 T510 UDP 载荷 `63Gbps+`。

## 当前边界

Stage 27g 可以声明：

- `TIME_SPEC 100MHz` 生产短窗口板端门禁通过。
- Rust 72 流主机接收无丢包/无间断通过。
- notebook 14 的生产控制与生产预览可作为 Stage 27g 参考入口。
- TIME ports `4300..4307` 和 SPEC ports `4308..4371` 按 Stage 27g 合约工作。

Stage 27g 不能声明：

- SPEC 全速通过。
- `TIME_SPEC 100MHz` 长时间 soak 通过。
- 科学级 PFB 幅相/功率标定完成。
- 交换机、DGX/X-engine、ARP/VLAN/PTP 或全 RF 频段标定通过。

## 进入 Stage 27h 的决策

Stage 27h 不回退 Stage 27g 的生产控制和主机能力，而是在此基础上更换 SPEC 生产合约：

- 保留 `TIME_SPEC 100MHz` 目标，不降低速率。
- 移除生产 SPEC 路径中的 `science_stream_decimator`，禁止 `/32` 或任何节拍抽稀作为通过条件。
- 移除生产 PFB filter/delay，先用 FFT-only 把吞吐闭合。
- SPEC 线缆合约改为 `4096` 个 channel、`16` 个 block、`256` 个 channel/block、`1` 个 spectrum-time、`8` 路输入、IQ16。
- SPEC 端口从 `4308..4371` 收窄到 `4308..4323`，总流数从 `72` 降到 `24`。
- 期望 TIME 和 SPEC 各自接近 `480kpps`，合计 T510 UDP 载荷不低于 `63Gbps`。
- 新生产入口为 notebook 15；notebook 14 保留为 Stage 27g 归档/参考入口。

## 推荐复现命令

本地：

```bash
python3 -m py_compile python/packet.py python/t510_fengine.py scripts/pynq_stage27g_time_spec_convergence.py scripts/host_stage27g_rust_rx_validate.py
python3 -m json.tool notebooks/14_stage27g_time_spec_fengine_control.ipynb >/dev/null
cargo test --manifest-path rust/t510_time_rx/Cargo.toml
cargo build --release --manifest-path rust/t510_time_rx/Cargo.toml
bash -n scripts/pynq_publish_stage27g.sh scripts/pynq_publish_jupyter_instrument.sh scripts/host_stage27g_rx_fanout_tune.sh
./scripts/run_xsim_batch.sh tb_axis_stream_duplicator tb_science_rate_selector tb_feng_ctrl_axi tb_axi4_to_axil_bridge tb_t510_fengine_top_smoke tb_spec_udp_cmac512 tb_time_udp_cmac512
```

Vivado：

```bash
vivado -mode batch -source scripts/stage27g_time_spec_100mhz_bit_export_batch.tcl
```

板端：

```bash
PYNQ_TARGET=xilinx@192.168.100.117 scripts/pynq_publish_stage27g.sh
ssh xilinx@192.168.100.117
cd /home/xilinx/t510_fengine_bringup
source /etc/profile.d/xrt_setup.sh
printf "%s\n" "xilinx" | sudo -S -p "" -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_stage27g_time_spec_convergence.py --matrix converge
```

主机：

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
