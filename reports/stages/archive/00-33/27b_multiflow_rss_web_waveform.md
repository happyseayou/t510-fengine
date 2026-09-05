# Stage 27b：多 Flow RSS 接收 + 60Hz 高点数 Web 波形

## 结论

Stage 27b 已完成本地实现落地：FPGA TIME live path 支持按全局 `seq_no` 分流到 8 个 UDP flow，Python `configure_time_live(...)` 默认配置 `4300..4307`，Rust receiver 默认以 `TPACKET_V3` mmap 后端接收端口范围，并通过 WebSocket 二进制流以 60Hz 推送高点数 RF 等效波形。

当前结论只覆盖代码实现和本地回归；尚未声明板端 bitstream 或 `200MHz TIME_ONLY` 主机短窗口无损 PASS。下一步需要跑仿真、Vivado synth/impl/bitstream/export、同步 overlay，然后在 `ens2f0np0` 上做 `20/100/200MHz` 实流验收。

## 关键实现

- RTL / AXI-Lite：
  - `time_udp_cmac512` 增加 TIME multiflow endpoint striping。
  - `flow_id = seq_no % flow_count`，endpoint=`time_multiflow_base_endpoint + flow_id`。
  - 支持 `flow_count=1/2/4/8`，非法/关闭时保持单 endpoint 兼容路径。
  - 新增 AXI-Lite register `0xD050`：
    - bit `0`：`time_multiflow_enable`
    - bits `10:8`：`time_multiflow_base_endpoint`
    - bits `19:16`：`time_multiflow_count`
  - TIME UDP payload v2 wire format 不变；`seq_no/frame_id/sample0` 仍全局单调。

- Python / Jupyter 控制：
  - `configure_time_live(...)` 默认启用 Stage 27b 8-flow：
    - host IP/MAC 仍为 Stage 24/25 通过配置。
    - endpoint `0..7` 映射到同一 host IP/MAC。
    - dst port `4300..4307`，src port `4000..4007`。
  - 保留 `multiflow_count=1` 作为单 flow fallback。
  - `read_science_output_status()` 增加 `time_multiflow_*` 状态字段。

- Rust receiver：
  - 新增 CLI：
    - `--dst-port-base`
    - `--src-port-base`
    - `--flow-count`
    - `--reorder-window`
    - `--web-fps`
    - `--waveform-points`
    - `--waveform-max-points`
  - `mmap` 和 `packet` 后端增加 classic BPF filter，只接收 IPv4 UDP dst port range。
  - 增加 per-flow + aggregate stats：pps/Gbps、seq/frame/sample0 gaps、detected bandwidth、NIC/ring counters。
  - 增加 reorder coordinator：允许多 flow/RSS 小范围乱序，默认窗口 `8192` packets，超过窗口才记全局 gap。
  - 接收热路径只做 fast Ethernet/IP/UDP/T510 header parse 和统计；display tap 按 Web tick 抓连续 packet window 解码 waveform。

- Web / UI：
  - `/api/state` 保持统计 JSON，默认 4Hz polling。
  - 新增 `/ws/waveform` 二进制 WebSocket，默认 `60Hz`。
  - waveform message 固定 64B header：
    - magic `0x32574654`
    - version `1`
    - sample0
    - seq start/end
    - selected/detected MHz
    - gap/mismatch flags
    - channel mask
    - points/channel
    - channel count
    - decimation
  - payload 为每个 channel 连续 `f32 y[points]`。
  - 默认每路 `4096` 点，可切 `1024/2048/4096/8192/16384`。
  - 页面保持顶部状态、中间 canvas、底部控制/统计，不遮挡波形。

- Host tuning：
  - 新增 `scripts/host_stage27b_rx_tune.sh`。
  - 默认设置 `ethtool -G ens2f0np0 rx 8192 tx 8192`。
  - 输出 ring、RSS hash、RSS indirection、queue/counter、IRQ 分布证据。
  - 可选 `STAGE27B_SET_RSS_HASH=1` 尝试设置 `udp4 sdfn` hash fields。

## 本地验证

已通过：

```bash
cargo test --manifest-path rust/t510_time_rx/Cargo.toml
cargo build --release --manifest-path rust/t510_time_rx/Cargo.toml
python3 -m py_compile python/t510_fengine.py python/packet.py scripts/pynq_stage26_time_live_bringup.py
./scripts/run_xsim_batch.sh tb_time_udp_cmac512 tb_feng_ctrl_axi
```

Rust test 覆盖：

- TIME v2 header / payload byte offsets。
- 20/100/200MHz sample0 delta detection。
- IPv4/UDP dst port range parser。
- classic BPF port range offsets。
- cross-flow reorder 不误报 gap。
- real gap 正确计入 seq/frame/sample0 gap。
- WebSocket waveform binary header/payload layout。

XSim 覆盖：

- `tb_time_udp_cmac512`：`flow_count=1/2/4/8`，验证 dst/src port striping、全局 seq/frame/sample0 单调、payload packing、tail `tkeep/tlast`、route/counter 无 error。
- `tb_feng_ctrl_axi`：验证 `0xD050` multiflow control register read/write/default 行为。

## 实流验收入口

主机调优与证据采集：

```bash
sudo scripts/host_stage27b_rx_tune.sh ens2f0np0
```

Rust receiver 推荐启动：

```bash
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

板端/Jupyter：

- 用 Jupyter/Python 切换 `20/100/200MHz TIME_ONLY`。
- Rust receiver 不需要重启。
- HTML bandwidth selector 只同步本机解码/显示，不直接改 FPGA。

PASS 条件：

- `selected=detected=200MHz`。
- `rx_processed_packets_per_sec >= 912000`。
- `parse_errors=0`。
- `seq_gaps=0`、`frame_gaps=0`、`sample0_gaps=0`。
- `ring_drops=0`、`kernel_drops=0`。
- NIC missed/drop/error/CRC/symbol counter 不增长。
- 8 路 waveform 60Hz 流畅刷新，4096 点默认显示；8192/16384 点切换时 UI 不遮挡。

## 尚未完成

- 需要跑全量 XSim 回归，覆盖 board/top smoke 与 Stage 25/26 相关 testbench。
- 需要 Vivado synth/impl/bitstream/export，并确认 route complete、timing met、0 errors、0 critical warnings。
- 需要同步新 bit/overlay 到板端。
- 需要实测 NIC RSS 是否把 `4300..4307` 分散到多个 RX queue。
- 需要板端/主机跑 `20/100/200MHz` 实流验收。

## 阶段边界

Stage 27b 不改变 TIME UDP payload v2，不启用 DDR ring，不声明 SPEC/PFB、DGX/X-engine、交换机、PTP/VLAN/ARP 或长稳 soak。若 8-flow `TPACKET_V3` 仍无法完成 200MHz 无损，下一阶段进入 AF_XDP/更多硬件队列/RSS tuning，而不是回退板端 TIME sender 结论。
