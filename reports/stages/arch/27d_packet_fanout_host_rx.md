# Stage 27d：PACKET_FANOUT 多 Worker 主机接收闭环

## Summary

Stage 27d 已把 Stage 27c 阻塞的 `200MHz TIME_ONLY` 主机接收推进到 PASS。FPGA/board 继续复用 Stage 27c `CORE_VERSION=0x0001001E` 8-flow TIME sender；本阶段未改 RTL、未改 TIME UDP payload v2、未启用 DDR、未进入 AF_XDP。

最终可验收路径不是裸 `PACKET_FANOUT_HASH`，而是：

- Rust receiver：`--backend fanout --fanout-mode port --worker-count 8 --pin-workers off`
- Host NIC steering：启用 ntuple，将 UDP dst port `4300..4307` 显式导到 RX queue `0..7`
- Rust fanout port mode：用 `PACKET_FANOUT_CBPF + PACKET_FANOUT_DATA`，按 UDP dst port 映射到 worker，避免 kernel hash collision

## Implementation

- Rust receiver
  - 新增 `--backend fanout`。
  - 新增 `--worker-count`、`--fanout-group`、`--fanout-mode hash|port`、`--pin-workers auto|off`。
  - 每个 worker 拥有独立 AF_PACKET socket、TPACKET_V3 mmap ring、BPF dst-port range filter。
  - fanout-safe gap 语义按 flow 内 stride 检查：`seq_no/frame_id += flow_count`，`sample0 += expected_delta * flow_count`。
  - `/api/state` 新增 `per_worker[]`、`worker_ring_drops`、`active_worker_count`、`fanout_mode`、`fanout_group`。
  - WebSocket waveform binary 格式保持兼容；fanout display tap 支持 flow stride。

- Host scripts
  - 新增 `scripts/host_stage27d_rx_fanout_tune.sh`。
  - 新增 `scripts/host_stage27d_rust_rx_validate.py`。
  - `host_stage27d_rx_fanout_tune.sh` 支持 `STAGE27D_SET_NTUPLE=1`，写入 `4300..4307 -> queue 0..7` 规则。

## Key Findings

- `PACKET_FANOUT_HASH` 多 worker 能解决单 socket 瓶颈的一部分，但 8 个 UDP flow 会 hash collision 到少数 workers，`200MHz` 仍低于 `912 kpps` PASS 门限。
- 增加 worker 到 `16/32` 不能根治 hash collision；active worker 数仍不足，且 NIC/RX queue 侧仍有 drop。
- `PACKET_FANOUT_CBPF` 的 BPF offset 与 socket filter 不同：fanout CBPF 从 IP header 起算，UDP dst port offset 是 `22`，不是 Ethernet frame offset `36`。
- 最终通过条件来自两层显式分流：
  - NIC ntuple：UDP dst port `4300..4307` 分别进入 RX queue `0..7`。
  - AF_PACKET fanout port mode：UDP dst port 映射到 Rust worker `0..7`。

## Validation

本地回归：

```bash
python3 -m py_compile scripts/host_stage27d_rust_rx_validate.py
bash -n scripts/host_stage27d_rx_fanout_tune.sh
cargo test --manifest-path rust/t510_time_rx/Cargo.toml
cargo build --release --manifest-path rust/t510_time_rx/Cargo.toml
git diff --check -- rust/t510_time_rx/src/main.rs scripts/host_stage27d_rx_fanout_tune.sh scripts/host_stage27d_rust_rx_validate.py
```

Host tuning evidence：

- `reports/board/stage27d_host_rx_fanout_tune.txt`
- ntuple rules: `4300..4307 -> RX queue 0..7`
- final receiver command:

```bash
sudo rust/t510_time_rx/target/release/t510_time_rx \
  --backend fanout \
  --worker-count 8 \
  --fanout-mode port \
  --fanout-group 0x27d \
  --pin-workers off \
  --interface ens2f0np0 \
  --dst-port-base 4300 \
  --src-port-base 4000 \
  --flow-count 8 \
  --web 0.0.0.0:8089 \
  --initial-bandwidth-mhz 200 \
  --ring-mb 512 \
  --block-mb 4 \
  --batch-size 4096 \
  --web-fps 60 \
  --waveform-points 4096 \
  --waveform-max-points 16384
```

Board/host final results:

| Bandwidth | Board config evidence | Host result | Processed rate | Notes |
| --- | --- | --- | --- | --- |
| `20MHz` | `reports/board/stage27d_time_multiflow_board_20mhz.stdout.json` | `HOST_STAGE27D_RUST_RX_PASS` | `119957.93 pps` | 8 workers, 8 RX queues, gap/drop/error delta 0 |
| `100MHz` | `reports/board/stage27d_time_multiflow_board_100mhz.stdout.json` | `HOST_STAGE27D_RUST_RX_PASS` | `479958.67 pps` | 8 workers, 8 RX queues, gap/drop/error delta 0 |
| `200MHz` | `reports/board/stage27d_time_multiflow_board_200mhz.stdout.json` | `HOST_STAGE27D_RUST_RX_PASS` | `960509.46 pps` | 8 workers, 8 RX queues, gap/drop/error delta 0 |

Final JSON outputs:

- `reports/board/stage27d_rust_rx_20mhz.json`
- `reports/board/stage27d_rust_rx_100mhz.json`
- `reports/board/stage27d_rust_rx_200mhz.json`

## Boundary

Stage 27d proves short-window `20/100/200MHz TIME_ONLY` host receive closure on this local host/NIC with explicit ntuple steering. It does not claim SPEC/PFB, DGX/X-engine, switch path, PTP/VLAN/ARP, long soak, AF_XDP, or full science readiness.

The current receiver process is intentionally left running on `0.0.0.0:8089` with `fanout=port`; the HTML can be used for waveform smoke while Jupyter controls the board.
