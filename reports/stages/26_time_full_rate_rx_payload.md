# Stage 26：动态 TIME Full-Rate 接收与 UDP Payload 规范

> 接续状态：本页记录 `CORE_VERSION=0x0001001C` 的 Stage 26 历史结果，当时因 `WNS=-0.205 ns` 阻塞。后续 Stage 26b/27 `0x0001001D` 已通过 `time_udp_cmac512` 输出寄存化和 DDR ring 雏形解除 timing blocker，并在 DDR-disabled direct path 上完成 `20/100/200MHz TIME_ONLY` 板端 counters/gates PASS。最新状态见 `26b_27_pl_ddr_time_buffer_timing.md`。

## 结论

Stage 26 已完成本地实现、仿真和 Vivado 生成链路，但 setup timing 仍未收敛，因此板端/主机 full-rate 验收仍是 `BLOCK`。

当前状态：

- `CORE_VERSION=0x0001001C`
- `docs/time_udp_payload_v2.md` 已新增并作为 TIME UDP payload v2 的权威说明
- Rust receiver 已落地，HTML selector 可动态切换 `20/100/200MHz` 解码/校验/显示
- RTL 已新增 native 512-bit TIME/UDP/CMAC path
- 本地 Python / Rust / XSim 回归通过
- Vivado synth / impl / route / bitstream / export 已完成，`overlay/t510_fengine.bit` 已生成，但 routed timing 仍失败
- bitstream SHA256: `138e40a6f6e74f673ed922c6ab7bad07f15096b33f20444af544419c80cf6400`
- routed timing summary: `WNS=-0.205 ns`, `TNS=-10.722 ns`, `WHS=0.007 ns`, `THS=0.000 ns`
- route status: `failed nets=0`, `unrouted nets=0`, `partially routed nets=0`

## 关键实现

- RTL：
  - `CORE_VERSION` 升级到 `0x0001001C`
  - 保留 Stage 25 低速 TIME path
  - 新增 `time_udp_cmac512.sv`，在 CMAC 域直接输出 TIME full-rate 512-bit 帧
  - Stage 26 TIME_ONLY full-rate 不再被 `WIDE_512B_TX_PATH_NOT_IMPLEMENTED` 阻塞

- Python：
  - `configure_time_live(...)`
  - `run_stage26_time_live_validation(...)`
  - `python/packet.py` 新增 TIME payload 解码 helper

- Rust / HTML：
  - 新 crate `rust/t510_time_rx`
  - 动态 bandwidth selector
  - selected vs detected bandwidth mismatch 高亮
  - per-channel RMS / max / clip 统计
  - 时间轴由 UDP sample0 / decim 语义驱动

## 本地验证

- `python3 -m py_compile python/packet.py python/t510_fengine.py scripts/pynq_stage26_time_live_bringup.py`
- `cargo test --manifest-path rust/t510_time_rx/Cargo.toml`
- `./scripts/run_xsim_batch.sh tb_time_udp_cmac512 tb_time_packetizer tb_stage25_cmac_live_tx tb_udp_frame_builder tb_tx_route_selector tb_t510_fengine_top_smoke tb_t510_fengine_board_top tb_feng_ctrl_axi`
- Vivado batch `scripts/stage26_time_live_bit_export_batch.tcl` 已跑完，bitstream/export 成功，但 `report_timing_summary` 仍报 timing failure

## 尚未完成

- 路由后 setup timing 收敛
- 板端 `20/100/200MHz` full-rate TIME live pcap
- Host 端 `HOST_PCAP_STAGE26_TIME_PASS`
- SPEC/PFB、DGX/X-engine、交换机/ARP/VLAN/PTP、长稳 soak

## Payload Contract

详见 `docs/time_udp_payload_v2.md`。
