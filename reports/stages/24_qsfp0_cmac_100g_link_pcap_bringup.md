# Stage 24：QSFP0 / CMAC 100G 链路打通与主机 pcap 闭环

## 结论

`STAGE24_QSFP_HEARTBEAT_PASS`

本阶段目标已经闭环：QSFP0 真实 100G CMAC 链路起来，并且本机 `ens2f0np0` 抓到了 FPGA 发出的 UDP heartbeat/test frame。

这不是 TIME/SPEC science 数据验收。当前只证明 CMAC/QSFP0 物理链路、PCS/FEC、512-bit CMAC TX heartbeat 数据面、主机 pcap 接收路径打通。TIME/SPEC full science、PFB/FFT、20/100/200 MHz 科学 payload 质量仍放到后续阶段。

## 本次通过配置

- `CORE_VERSION=0x0001001A`
- CMAC refclk：`156.25 MHz`
- CMAC AN/LT：关闭
- CMAC RS-FEC：开启
- XCI 关键配置：
  - `GT_REF_CLK_FREQ=156.25`
  - `INCLUDE_RS_FEC=1`
  - `INCLUDE_AUTO_NEG_LT_LOGIC=0`
  - `INCLUDE_AN_LT_TX_TRAINER=0`
- bit SHA256：`8850a412554b7c2d2d35c0a0d27dede694bde71ba01cecdf3c20043851387327`

说明：AOC 光缆最终需要 no-AN/no-LT + RS-FEC 才与本机 `ens2f0np0` 建链。此前 no-FEC 变体能让 GT/CMAC TX 活起来，但 `rx_aligned=0/local_fault=1`，不能通过。

## Vivado 结果

- `synth_design`：`0 errors, 0 critical warnings`
- `route_design`：成功
- route status：
  - routable nets：`107443`
  - fully routed nets：`107443`
  - routing errors：`0`
- routed timing：
  - `WNS=+0.508 ns`
  - `WHS=+0.009 ns`
  - failing endpoints：`0`
  - `All user specified timing constraints are met.`
- `write_bitstream`：成功

仍需记录的风险：bitgen 仍报 `cmac_an_lt@2020.05 design_linking` evaluation license warning。它没有阻塞本轮 bitstream/上板/pcap，但生产验收前必须确认 license 风险或重新生成无该特征依赖的 IP。

## 板端链路证据

证据文件：`reports/board/stage24d_001a_156p25_rsfec_qsfp_link_bringup.json`

板端加载新 bit 后通过：

- `core_version=0x0001001A`
- `module_present=1`
- `gt_refclk_seen=1`
- `gt_locked=1`
- `gt_tx_reset_done=1`
- `gt_rx_reset_done=1`
- `cmac_reset_done=1`
- `cmac_tx_ready=1`
- `cmac_rx_aligned=1`
- `cmac_rx_status=1`
- `local_fault=0`
- `remote_fault=0`
- `qsfp_link_up=1`
- `udp_dry_run_active=0`
- `tx_underflow=0`
- `tx_overflow=0`
- accepted packet delta：`3006`
- accepted byte delta：`192384`

板端同时确认 PPS/10 MHz 相关状态在本次运行中可见：`ref_status_locked=1`、`pps_seen=1`、`pps_recent=1`、`pps_count=3`。这只是运行时健康线索，不替代后续外部同步专项验收。

## 主机链路证据

主机口固定为 `ens2f0np0`，不碰管理口。

当前主机状态：

- MAC：`08:c0:eb:d5:95:b2`
- IP：`10.0.1.16/24`，兼容 alias `10.0.1.10/24`、`10.0.1.11/24`
- link：`UP, LOWER_UP`
- speed：`100000Mb/s`
- lanes：`4`
- autoneg：`off`
- active FEC：`RS`
- link detected：`yes`

证据文件：

- `reports/board/stage24d_001a_host_ip_addr.txt`
- `reports/board/stage24d_001a_host_ip_link.txt`
- `reports/board/stage24d_001a_host_ethtool.txt`
- `reports/board/stage24d_001a_host_fec.txt`
- `reports/board/stage24d_001a_host_module_eeprom.txt`

## pcap 验证

最终采用修复后的 live capture 结果：

- pcap：`reports/board/stage24d_001a_156p25_rsfec_heartbeat_livefixed.pcap`
- JSON：`reports/board/stage24d_001a_156p25_rsfec_pcap_check_livefixed.json`
- classification：`HOST_PCAP_STAGE24_HEARTBEAT_PASS`
- matching packets：`981`
- kernel dropped：`0`
- destination MAC：`08:c0:eb:d5:95:b2`
- destination IP/port：`10.0.1.16:4300`
- source IP/port：`10.0.1.1:4000`
- payload magic：`T510`
- payload core version：`0x0001001A`
- seq discontinuities：`[]`

第一次 live pcap 尝试因为 helper 脚本的 signal/进程组处理问题留下两个 tcpdump 同时写同一个 pcap，导致那份旧文件出现 seq 顺序污染。该文件不作为通过证据。脚本已修复并回归通过。

## Science 状态

本阶段没有声明 TIME/SPEC science 通过。

当前 board status 仍明确给出 science block：

- `WIDE_512B_TX_PATH_NOT_IMPLEMENTED`
- `FORCED_DRY_RUN`

因此后续必须另开阶段，把 TIME low-rate live 接到 CMAC，再逐步做 20/100/200 MHz science payload、PFB/SPEC、sample0、phase/amplitude 和 pcap 长稳验证。

## 产物

- overlay bit：`overlay/t510_fengine.bit`
- overlay HWH：`overlay/t510_fengine.hwh`
- overlay Tcl：`overlay/t510_fengine.tcl`
- overlay SHA：`reports/board/stage24d_001a_overlay_sha256.txt`
- Vivado batch log：`reports/board/stage24d_001a_156p25_rsfec_batch2.log`
- Vivado journal：`reports/board/stage24d_001a_156p25_rsfec_batch2.jou`
- 板端 bring-up JSON：`reports/board/stage24d_001a_156p25_rsfec_qsfp_link_bringup.json`
- 主机 pcap JSON：`reports/board/stage24d_001a_156p25_rsfec_pcap_check_livefixed.json`
- 主机 pcap：`reports/board/stage24d_001a_156p25_rsfec_heartbeat_livefixed.pcap`

## 下一步

建议下一阶段从低速 TIME live 开始，不直接跳到 full science：

1. 保留当前 `0x0001001A` CMAC link 配置。
2. 把 TIME low-rate/monitor path 接入 512-bit CMAC live TX，而不是旧 64-bit dry-run。
3. 用 pcap 校验 T510 TIME header、seq、sample0 连续和 payload layout。
4. 再扩到 20 MHz science 档，最后推进 100/200 MHz 与 SPEC/PFB。

在这些完成前，QSFP 只能说“链路和 heartbeat 已通”，不能说“科学数据已通”。
