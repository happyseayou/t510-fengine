# Stage 27c：27b 硬件闭环与 8-Flow RSS 实流验收

## 结论

Stage 27c 目标是把 Stage 27b 的 8-flow TIME live/Rust 60Hz waveform 从本地实现推进到新 bitstream、PYNQ 同步和主机实流验收。当前 `CORE_VERSION=0x0001001E` bitstream/export 已完成，Vivado route clean 且 timing met；DDR ring 已从 Stage 27c 实现路径 compile-out，保留 AXI-Lite 可见寄存器但硬件数据面固定 disabled/zero。

硬件闭环结论：板端 8-flow TIME sender 在 `20/100/200MHz` 三档均 PASS；Rust receiver/RSS 主机侧 `20MHz`、`100MHz` PASS，`200MHz` 仍 BLOCK 于 host RX/NIC path。200MHz 时板端 route/drop/underflow/overflow 干净，但本机 receiver 只能处理约 `867 kpps`，低于 `912 kpps` PASS 门限，且 Mellanox `rx_out_of_buffer` / `rx_missed_errors` 增长。因此 Stage 27c 不声明 200MHz 主机无损 PASS；下一阶段应进入多 socket/fanout、AF_XDP 或更多 RX queue 绑定优化。

## 关键实现

- RTL / build：
  - `CORE_VERSION` 升到 `0x0001001E`，区分包含 Stage 27b multiflow 的硬件 bit。
  - Stage 27c 不再综合 DDR ring 数据面：`TIME_DDR_RING_COMPILED=1'b0`，TIME AXIS 直连 CMAC TX slice；DDR AXI master idle，DDR occupancy/drop/error counters 恒为 0。这个决定来自 Stage 26b/27 DDR enabled path 触发板端管理网失联，且 Stage 27c 目标是先闭合 8-flow TIME/RSS。
  - 新增 `scripts/stage27c_multiflow_rss_bit_export_batch.tcl`，复用 Stage 24d CMAC 配置、refresh project、CMAC OOC、top synth、impl/write_bitstream 和 overlay export。
  - build batch 输出 `reports/board/stage27c_multiflow_rss_*` timing/utilization/route/license evidence，并在 timing negative 时拒绝 export overlay。
  - Vivado 2026-06-23 build 结果：
    - `synth_1`: `synth_design Complete!`，0 errors、0 critical warnings。
    - `impl_1`: `write_bitstream Complete!`。
    - Route status：`125937` routable nets fully routed，routing errors `0`。
    - Routed timing：`WNS=+0.005 ns`、`TNS=0.000 ns`、`WHS=+0.003 ns`、`THS=0.000 ns`；`All user specified timing constraints are met`。
    - Worst setup path slack：`+0.005 ns`，当前仍很薄，下一轮优化优先继续切 `time_udp_cmac512` token/IP checksum path。
    - Bitstream SHA256：`4c28b8e2616a1a67ffed07253ffb7fea8c5867ed78a56659c0ebd6f0a4f31069`。
    - HWH SHA256：`5e6cde952e062cee76200ba5851c2bede926bff90a06435c52f23eeecf78e0be`。
    - CMAC evaluation license warning 仍存在：`cmac_an_lt@2020.05 design_linking`；`cmac_usplus@2020.05` 为 bought license。

- PYNQ / board：
  - 新增 `scripts/pynq_stage27c_time_multiflow_bringup.py`。
  - 默认 `multiflow_count=8`、endpoint `0..7`、dst `4300..4307`、src `4000..4007`、DDR disabled。
  - 输出 `reports/board/stage27c_time_multiflow_board.json`。
  - PASS 条件包括 multiflow control enabled/count=8、TIME packet/frame counters 增长、route miss/error 为 0、frame drop 为 0、CMAC underflow/overflow 为 0、heartbeat silent、DDR disabled。
  - 新增 `scripts/pynq_publish_stage27c.sh`，同步 overlay/python/scripts/notebooks/docs 到 bring-up 和 Jupyter 目录。

- Host / Rust：
  - 新增 `scripts/host_stage27c_rust_rx_validate.py`，采样 Rust `/api/state`、sysfs NIC counters 和 `ethtool -S` queue counters。
  - Rust receiver 修复 aggregate detected bandwidth：多 flow 下 global reorder 被丢包打断时，用 per-flow 一致 detected value 回填，避免 `20/100MHz` 无损实测被 `detected=null` 或旧 detected 状态误判。
  - Rust HTTP listener 加 `SO_REUSEADDR`，避免频繁重启后 `8089` 被 `TIME_WAIT` 短暂卡住。
  - 无 WebSocket 客户端时暂停 waveform packet copy/build，只保留接收统计热路径；打开 HTML 后仍按 60Hz 推送 waveform。
  - 默认阈值：
    - `20MHz`: expected `120000 pps`，PASS `>=114000`
    - `100MHz`: expected `480000 pps`，PASS `>=456000`
    - `200MHz`: expected `960000 pps`，PASS `>=912000`
  - 分类：
    - `HOST_STAGE27C_RUST_RX_PASS`
    - `BLOCK_STAGE27C_HOST_RSS_RX_LIMIT`
    - `BLOCK_STAGE27C_RSS_NOT_DISTRIBUTING_FLOWS`
    - `BLOCK_RSS_QUEUE_COUNTER_UNAVAILABLE`

## 实测证据

- Vivado/export：
  - `reports/board/stage27c_multiflow_rss_impl_timing_summary.rpt`
  - `reports/board/stage27c_multiflow_rss_route_status.rpt`
  - `reports/board/stage27c_multiflow_rss_worst_paths.rpt`
  - `overlay/t510_fengine.bit` SHA256 `4c28b8e2616a1a67ffed07253ffb7fea8c5867ed78a56659c0ebd6f0a4f31069`
- PYNQ board:
  - `reports/board/stage27c_time_multiflow_board.json`
  - classification `STAGE27C_TIME_MULTIFLOW_BOARD_PASS`
  - `core_version=0x0001001e`
  - `time_multiflow_enable=1`、`time_multiflow_count=8`
  - 20MHz deltas: `time_packet_count=240502`、`tx_frame_built_count=240503`、route miss/error `0`、time drop `0`、DDR counters `0`
  - 100MHz deltas: `time_packet_count=961977`、`tx_frame_built_count=961978`、route miss/error `0`、time drop `0`、DDR counters `0`
  - 200MHz deltas: `time_packet_count=1923919`、`tx_frame_built_count=1923928`、route miss/error `0`、time drop `0`、DDR counters `0`
- Host/Rust:
  - `reports/board/stage27c_host_rx_tune.txt`: `mlx5_core`、100G link、MTU 9000、RX/TX ring 8192、24 combined queues、UDP4 RSS hash includes IP SA/DA and UDP src/dst ports.
  - `reports/board/stage27c_rust_rx_20mhz.json`: `HOST_STAGE27C_RUST_RX_PASS`，`119790.67 pps`，selected/detected `20MHz`，gap/drop/error deltas `0`，4 RX queues active.
  - `reports/board/stage27c_rust_rx_100mhz.json`: `HOST_STAGE27C_RUST_RX_PASS`，`479980.48 pps`，selected/detected `100MHz`，gap/drop/error deltas `0`，4 RX queues active.
  - `reports/board/stage27c_rust_rx_200mhz.json`: `BLOCK_STAGE27C_HOST_RSS_RX_LIMIT`，`867318.81 pps` < `912000 pps` threshold，selected/detected `200MHz`，parse/gap deltas `0`，4 RX queues active, but `rx_out_of_buffer=808249` and `rx_missed_errors=797763` increased over the validation window.

## 验收入口

本地：

```bash
python3 -m py_compile python/t510_fengine.py python/packet.py scripts/pynq_stage26_time_live_bringup.py scripts/pynq_stage27c_time_multiflow_bringup.py scripts/host_stage27c_rust_rx_validate.py
cargo test --manifest-path rust/t510_time_rx/Cargo.toml
cargo build --release --manifest-path rust/t510_time_rx/Cargo.toml
./scripts/run_xsim_batch.sh tb_time_udp_cmac512 tb_feng_ctrl_axi tb_stage25_cmac_live_tx tb_t510_fengine_top_smoke tb_t510_fengine_board_top
```

Vivado：

```bash
vivado -mode batch -source scripts/stage27c_multiflow_rss_bit_export_batch.tcl
```

发布到 PYNQ：

```bash
PYNQ_TARGET=xilinx@192.168.100.117 scripts/pynq_publish_stage27c.sh
```

主机 receiver：

```bash
sudo scripts/host_stage27b_rx_tune.sh ens2f0np0
sudo rust/t510_time_rx/target/release/t510_time_rx \
  --interface ens2f0np0 \
  --dst-port-base 4300 \
  --src-port-base 4000 \
  --flow-count 8 \
  --backend mmap \
  --web 0.0.0.0:8089 \
  --initial-bandwidth-mhz 200 \
  --ring-mb 512 \
  --block-mb 4 \
  --batch-size 4096 \
  --web-fps 60 \
  --waveform-points 4096 \
  --waveform-max-points 16384
```

板端 / 主机逐档：

```bash
cd /home/xilinx/t510_fengine_bringup
source /etc/profile.d/xrt_setup.sh
sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_stage27c_time_multiflow_bringup.py --no-download --bandwidth-mhz all --seconds 2 --output reports/board/stage27c_time_multiflow_board.json

scripts/host_stage27c_rust_rx_validate.py --bandwidth-mhz 20 --seconds 8
scripts/host_stage27c_rust_rx_validate.py --bandwidth-mhz 100 --seconds 8
scripts/host_stage27c_rust_rx_validate.py --bandwidth-mhz 200 --seconds 8
```

## 阶段边界

Stage 27c 不改变 TIME UDP payload v2，不启用/不综合 DDR ring，不声明 SPEC/PFB、DGX/X-engine、交换机、PTP/VLAN/ARP 或长稳 soak。当前 8-flow `TPACKET_V3` 已证明 `20/100MHz` 主机无损，但 `200MHz` 仍不足；下一阶段进入 AF_XDP、多 socket `PACKET_FANOUT`、RX queue affinity/IRQ pinning 或更多 flow/queue tuning。

板端账户为 `xilinx@192.168.100.117`，sudo/登录密码约定与用户名相同。命令可通过 stdin/交互传入凭据；不要把密码硬编码进脚本或 notebook。
