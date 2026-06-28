# Stage 27a：Rust TIME Receiver v2 高吞吐接收与底部控制界面

## 结论

Stage 27a 已完成本地主机端实现和 dry-run/API 验证。Rust TIME receiver 默认后端已从逐包 `AF_PACKET recv()` 切换为 `AF_PACKET + PACKET_MMAP + TPACKET_V3`，并重做 HTML 为“顶部状态条 / 中间波形 canvas / 底部常驻控制与统计”的非遮挡布局。

当前结论只覆盖本地实现、编译和 API smoke；尚未声明 `200MHz TIME_ONLY` 主机短窗口无损 PASS。下一步需要在 `ens2f0np0` 上以 root 运行 release receiver，并配合 Jupyter/板端脚本依次跑 `20/100/200MHz` 实流验收。

## 关键实现

- Rust 接收后端：
  - `--backend mmap` 成为默认值。
  - 新增 `AF_PACKET + PACKET_MMAP + TPACKET_V3` RX ring。
  - 保留 `--backend packet` 和 `--backend udp` 作为 fallback/debug。
  - 新增启动参数：`--initial-bandwidth-mhz`、`--ring-mb`、`--block-mb`、`--block-count`、`--frame-kb`、`--batch-size`、`--poll-timeout-ms`。
  - 默认 ring 配置为 `512 MiB`、`4 MiB` block、`16 KiB` frame，适配当前 TIME jumbo frame。
  - 接收热路径使用无分配 Ethernet/IPv4/UDP/T510 快速 parser，只做 filter、header、gap 和速率统计。
  - 8 路 RF waveform 只按 UI 刷新节奏从最新可显示包构建，避免每包绘图拖慢接收。

- 统计/API：
  - `/api/state` 扩展 `expected_packets_per_sec`、`expected_fpga_gbps`、`rx_processed_packets_per_sec`、`rx_processed_gbps`、`display_update_hz`。
  - 增加 ring 配置/填充近似值、`PACKET_STATISTICS` drop、NIC `/sys/class/net/.../statistics` RX delta。
  - 保留旧 `packets_per_sec` / `gbps` 字段兼容已有页面和脚本。
  - `/api/config` 改为 patch/partial update，兼容旧 full config POST；`paused`、`pause`、`freeze` 三种写法都可控制冻结。

- HTML/UI：
  - 顶部状态条显示连接、selected/detected bandwidth、gap/loss、expected/processed rate。
  - 中间 canvas 独占波形区域，稳定尺寸，不被控制区遮挡。
  - 底部控制栏包含 bandwidth、center/expected/DAC MHz、window、points、Y scale、8 路 phase、channel mask、pause/freeze。
  - 详细诊断放在底部 `<details>` 中，不覆盖波形。
  - 移动/窄窗口下底部控制纵向堆叠。

## 本地验证

已通过：

```bash
cargo test --manifest-path rust/t510_time_rx/Cargo.toml
cargo build --release --manifest-path rust/t510_time_rx/Cargo.toml
git diff --check -- rust/t510_time_rx/src/lib.rs rust/t510_time_rx/src/main.rs
```

结果：

- Rust tests：`6 passed`
- release build：完成
- diff whitespace check：通过

API smoke：

```bash
rust/t510_time_rx/target/release/t510_time_rx \
  --backend udp --port 44300 --web 127.0.0.1:8090

curl -s -X POST http://127.0.0.1:8090/api/config \
  -H 'Content-Type: application/json' \
  -d '{"bandwidth_mhz":100,"pause":true}'
```

结果：`config.bandwidth_mhz=100`、`config.paused=true`、`stats.selected_bandwidth_mhz=100`。

sudo mmap open smoke：

```bash
sudo -n timeout 3s rust/t510_time_rx/target/release/t510_time_rx \
  --interface ens2f0np0 \
  --port 44301 \
  --web 127.0.0.1:8090 \
  --backend mmap \
  --ring-mb 64 \
  --block-mb 4 \
  --batch-size 512
```

结果：receiver 成功启动并打印 `T510 TIME receiver HTML: http://127.0.0.1:8090`；`timeout` 正常结束。该 smoke 只证明 root 权限下 mmap ring 初始化可用，不代表实流收包无损。

200MHz 实流短测：

- 板端输出：`reports/board/stage27a_time_live_200mhz_board.json`
- 主机输出：`reports/board/stage27a_rust_mmap_rx_200mhz_state.json`
- 板端结果：`STAGE26_TIME_FULL_RATE_PASS`，`200MHz TIME_ONLY` direct path counters/gates PASS。
- 板端估计：`packet_rate_est=960000.0`，payload 约 `62.9 Gbps`，wire 约 `64.4 Gbps`。
- 主机 receiver：`backend=mmap`、`parse_errors=0`、`selected=detected=200MHz`、`display_update_hz≈29`。
- 主机处理速率：`rx_processed_packets_per_sec≈262244`，`rx_processed_gbps≈17.45`，未达到 `expected_fpga_gbps=63.8976`。
- 主机 drop/gap：`seq_gaps=93201`、`frame_gaps=93201`、`sample0_gaps=93201`、`app_drops=15812594`，`nic_rx_missed_errors_delta=693360`。
- NIC tuning：已执行 `ethtool -G ens2f0np0 rx 8192 tx 8192`，当前单流仍落在 `rx6` 一个 RX queue。

结论：Stage 27a receiver v2 已比旧 debug `packet` 路径更可观测，且页面/解析/带宽检测正确；但 `TPACKET_V3` 单 socket 仍不足以完成 200MHz 短窗口无损。当前 blocker 分类为 `BLOCK_STAGE27A_HOST_NIC_SINGLE_QUEUE_RX_LIMIT`，下一步应进入 AF_XDP/多队列/多流 RSS 或板端多 UDP flow 分流方案。

未完成：

- `cargo fmt`：当前默认 nightly toolchain 未安装 `rustfmt` component，`stable` toolchain 也未安装；未执行格式化命令成功。
- 实流 `mmap` 验收：需要 root 权限和 `ens2f0np0` live TIME 流。
- 200MHz 短窗口无损：尚未声明 PASS。

## 实流验收入口

推荐先用 8089，因为当前 8088 被 Vivado 占用：

```bash
sudo rust/t510_time_rx/target/release/t510_time_rx \
  --interface ens2f0np0 \
  --port 4300 \
  --web 0.0.0.0:8089 \
  --backend mmap \
  --initial-bandwidth-mhz 200 \
  --ring-mb 512 \
  --block-mb 4 \
  --batch-size 4096 \
  --poll-timeout-ms 10
```

板端/Jupyter 切换 `20/100/200MHz TIME_ONLY` 时，Rust receiver 不需要重启；只在 HTML 中同步 selected bandwidth 和 RF 回算参数。

PASS 条件仍按 Stage 27a 计划：

- selected/detected bandwidth 一致。
- `parse_errors=0`。
- 短窗口内 `seq_gaps=0`、`frame_gaps=0`、`sample0_gaps=0`。
- `ring_drops=0`、`kernel_drops=0`、NIC missed/error/CRC delta 为 0。
- 8 路 waveform 正常，Jupyter 调频/调相后 HTML 的 RF 等效波形语义一致。

## 阶段边界

Stage 27a 只升级主机 Rust receiver 和 HTML。不改 FPGA TIME UDP payload v2 wire format，不声明 DDR enabled path、SPEC/PFB、DGX/X-engine、交换机/PTP/VLAN/ARP 或长稳 soak。
