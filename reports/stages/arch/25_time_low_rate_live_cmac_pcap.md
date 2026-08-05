# Stage 25：低速 TIME live CMAC/pcap 闭环

## 结论

`STAGE25_TIME_LOW_RATE_LIVE_PASS`

Stage 25 已完成本地实现、XSim 回归、Vivado synth/impl/bitstream/export、板端 bring-up 和主机 `ens2f0np0` pcap 验收。当前产物是 `CORE_VERSION=0x0001001B`，在保留 Stage 24d no-AN/no-LT + RS-FEC CMAC 配置的基础上，低速真实 TIME live 数据路径已经闭环：

RFDC/science TIME selector -> TIME packetizer -> route selector -> UDP frame builder -> 64-bit to 512-bit async bridge -> CMAC TX source mux -> CMAC AXIS TX -> host pcap。

主机验收 classification 为 `HOST_PCAP_STAGE25_TIME_PASS`，板端 classification 为 `STAGE25_TIME_LOW_RATE_LIVE_PASS`。

## 范围边界

- 默认档位：`20MHz TIME_ONLY`
- 默认低速节拍：`TIME_LIVE_INTERVAL_BEATS=7680`
- 默认 TIME payload：`time_payload_nsamp=64`，T510 TIME header + `8192B` payload
- 目标包率：约 `1 kpps`
- 目标 endpoint2：`10.0.1.16:4300` / `08:c0:eb:d5:95:b2`
- source：`10.0.1.1:4000` / `02:00:00:00:00:01`

本阶段只证明低速 `20MHz TIME_ONLY` live TIME pcap 闭环。不声明 20/100/200MHz full science、SPEC/PFB、DGX/X-engine、交换机、ARP/VLAN/PTP 或长时间背压压力测试通过。

## RTL/API 变更

- `CORE_VERSION` 升到 `0x0001001B`。
- `time_packetizer` 新增 `packet_interval_beats`；低速等待和出包期间继续消耗/跳过输入 beat，使输出约 `1 kpps`，并保持 `sample0` start-to-start 步进为 `245760`。
- 新增 `axis64_to_cmac512_async.sv`，用完整 frame token 跨 `adc_m_axis_clk -> cmac_tx_clk`，保证 512-bit CMAC TX 帧内无 bubble，保留 `tkeep/tlast`，支持非 64B 对齐尾包。
- 新增 `cmac_tx_source_mux.sv`，Stage 25 TIME live 选中时 heartbeat 自动静默，避免双源驱动 CMAC。
- 顶层接入 TIME live path，并保留 full science blocker；`run_qsfp_live_validation()` 仍不把 SPEC/PFB/full-rate science 放行。
- Python API 新增 `configure_time_low_rate_live(...)` 和 `run_stage25_time_live_validation(...)`。
- 新增主机 pcap checker：`scripts/host_stage25_time_pcap_check.py`，复用 `python/packet.py` 解析 Ethernet/IPv4/UDP/T510 v2 header。

## 本地验证

Python 编译通过：

```bash
python3 -m py_compile python/t510_fengine.py python/packet.py scripts/pynq_stage25_time_live_bringup.py scripts/host_stage25_time_pcap_check.py
```

XSim 回归通过：

```bash
./scripts/run_xsim_batch.sh tb_stage25_cmac_live_tx tb_udp_frame_builder tb_time_packetizer tb_tx_route_selector tb_t510_qsfp_test_frame_gen tb_t510_fengine_top_smoke tb_t510_fengine_board_top tb_feng_ctrl_axi
```

覆盖项包括 TIME packet interval、64-to-512 async bridge、CMAC source mux，以及既有 UDP route/frame/top/AXI 回归。

## Vivado 结果

最终 batch log：`reports/board/stage25_time_live_samplefix_vivado.log`

结果：

- top `synth_design`：`synth_design Complete!`
- route：`Router Completed Successfully`
- route status：failed nets `0`、unrouted nets `0`、partially routed nets `0`、node overlaps `0`
- routed timing estimate：`WNS=+0.107 ns`、`TNS=0.000 ns`、`WHS=+0.010 ns`、`THS=0.000 ns`
- `write_bitstream`：`write_bitstream Complete!`
- overlay export：完成
- bitgen：`0 Errors`

仍需记录的风险：bitgen 仍报 `Vivado 12-1790` evaluation license critical warning，源于 `cmac_an_lt@2020.05 design_linking`；`cmac_usplus@2020.05` 为 bought license。该 warning 没有阻塞本轮 bitstream/export，但生产验收前仍需确认 license 风险。

## 板端验收

板端命令：

```bash
sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_stage25_time_live_bringup.py \
  --bitfile overlay/t510_fengine.bit \
  --seconds 3 \
  --output reports/board/stage25_time_low_rate_live_bringup.json
```

结果文件：`reports/board/stage25_time_low_rate_live_bringup.json`

关键结果：

- classification：`STAGE25_TIME_LOW_RATE_LIVE_PASS`
- core version：`0x0001001B`
- `time_packet_count` delta：`3005`
- `tx_frame_built_count` delta：`3005`
- `time_dropped_count`：`0`
- `tx_route_miss_count` / `tx_route_error_count`：`0` / `0`
- `tx_underflow` / `tx_overflow`：`0` / `0`
- `tx_cmac_mux_selected_time`：`1`
- heartbeat：disabled/silent
- final CMAC/QSFP link：ready/up
- dry-run：disabled

## 主机 pcap 验收

主机命令：

```bash
scripts/host_stage25_time_pcap_check.py \
  --interface ens2f0np0 \
  --sudo \
  --seconds 5 \
  --capture-output reports/board/stage25_time_low_rate_live.pcap \
  --output reports/board/stage25_time_low_rate_live_pcap.json
```

结果文件：

- pcap：`reports/board/stage25_time_low_rate_live.pcap`
- JSON：`reports/board/stage25_time_low_rate_live_pcap.json`

关键结果：

- classification：`HOST_PCAP_STAGE25_TIME_PASS`
- matching packets：`4947`
- total packets：`4947`
- kernel drops：`0`
- bad payload count：`0`
- `stream_type=TIME`
- `payload_bytes=8192`
- UDP payload length：`8320`
- expected `sample0_step=245760`
- seq/frame discontinuities：`0`
- sample0 discontinuities：`0`
- first seq / last seq：`102002` / `106948`
- first sample0 / last sample0：`25197466996` / `26412995956`

主机 NIC 物理层计数在 pcap 前后未增长：

- `rx_crc_errors_phy=601730`
- `rx_symbol_err_phy=601730`

## 产物

- overlay bit：`overlay/t510_fengine.bit`
- overlay HWH：`overlay/t510_fengine.hwh`
- overlay Tcl：`overlay/t510_fengine.tcl`
- overlay manifest：`overlay/t510_fengine.manifest.txt`
- overlay SHA256：`2ab541a8f855ddfcc3ea2271fcc3bc46288bb8d6a73e2a695201300cda160dca`
- SHA 文件：`reports/board/stage25_time_low_rate_live_overlay_sha256.txt`
- Vivado log：`reports/board/stage25_time_live_samplefix_vivado.log`
- board bring-up JSON：`reports/board/stage25_time_low_rate_live_bringup.json`
- host pcap：`reports/board/stage25_time_low_rate_live.pcap`
- host pcap JSON：`reports/board/stage25_time_low_rate_live_pcap.json`

## 阶段衔接说明

Stage 25 可以作为“CMAC 能发真实低速 TIME/T510 包、主机能按 pcap 收到并解析”的通过点。后续若推进 full science，仍必须单独打开并验收 SPEC/PFB、wide/full-rate 512-bit TX、20/100/200MHz 档位、交换机/DGX/X-engine 收包、PTP/VLAN/ARP，以及长时间 backpressure/soak。
