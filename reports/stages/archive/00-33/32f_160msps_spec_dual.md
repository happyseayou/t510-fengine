# Stage 32f：160 MS/s SPEC_ONLY 与 TIME_SPEC

## 状态

`PASS`

## 目标

复用现有4096-channel、4-tap PFB和 `16 x 256 x 1` packet layout，闭合160
`SPEC_ONLY` 和 `TIME_SPEC`。

## 前置条件

Stage 32e `PASS`。

## 验收

- channel spacing 39.0625 kHz，bin顺序和IQ方向正确。
- SPEC frame/sample0 连续，PFB/XFFT overflow为0。
- 160 SPEC_ONLY无drop/gap。
- 160 TIME_SPEC约1.25 Mpps、83.86 Gbit/s，24 flow无drop/gap。

## 非目标

不修改PFB数学定义，不声明320 SPEC。

## 测试、证据、版本

### 实际改动

- 继续复用4096-channel、4-tap PFB、`16 x 256 x 1` SPEC布局。
- UDP header、8192 B payload、IQ16、SPEC端口 `4308..4323`未改变。
- 控制/API允许160 `SPEC_ONLY`和 `TIME_SPEC`。
- REST status增加只读`channelizer`快照，暴露PFB/XFFT已有寄存器；不修改RTL、
  bitstream或wire contract。
- `scripts/stage32_agent_host_gate.py`对SPEC模式严格检查4096 channels、4 taps、
  `256 x 1`布局、PFB frame增长及12类PFB/XFFT错误增量。
- `scripts/stage32_agent_pfb_tone_gate.py`从Rust接收机WebSocket读取完整4096-bin
  snapshot，用已连接的DAC-ADC自环验证bin顺序和复数IQ方向。
- 板端只读遥测release为
  `stage32-telemetry2-53f46bb73a2d-20260726`；FPGA bitstream未改变。

### 本地结果

- `tb_pfb_channelizer`、`tb_spectral_packetizer`、`tb_spec_udp_cmac512`、
  `tb_cmac_tx_source_mux`和顶层smoke：PASS。
- Python/Rust单元测试覆盖160三种合法profile、24 endpoint及固定wire contract。
- 证据：`../vivado/stage32c/local_verification.md`。
- bit SHA256：
  `d9ce5b49f6c6dbb5c9ff47f83e07e992a953f30444c28a680723cd251914e175`。

### 160 SPEC_ONLY正式结果

- 正式证据：
  `../board/stage32_160msps_spec_only_board_host_20260726.json`。
- 接收机完整证据：
  `../board/stage32_160msps_spec_only_board_host_20260726_host.json`。
- 主机60秒收到`37,514,334`个SPEC包，平均`625,238.9 pps`，
  T510 UDP payload为`41,615.901184 Mbit/s`；TIME包为0。
- 16个SPEC flow全部活跃，parse/kernel/ring/app drop和SPEC sequence/frame
  gap增量均为0；完整频谱预览在运行时满足16/16 blocks。
- 板端SPEC新增`43,552,704`包，PFB新增`2,722,044`帧；RFDC/science/SPEC/TX
  drop、route error以及PFB/XFFT overflow/halt/TLAST/backpressure/error增量均为0。
- `rx_steer_missed_packets=30`仅作为精确ntuple白名单之外的背景包warning保留；
  T510逐flow连续性和物理错误计数均通过。

### Bin顺序和复数IQ方向

- 正式证据：
  `../board/stage32f_160msps_pfb_bin_iq_receiver_20260726.json`。
- center为100 MHz，DAC-ADC自环tone为120 MHz，即`+20 MHz` complex baseband。
- 160 MS/s / 4096得到`39.0625 kHz` bin宽，理论目标为`+512` bin；若IQ方向
  反转则应落在3584。
- Rust接收机重组的8路、4096-bin、16/16-block完整snapshot中，8路峰值全部
  精确落在512，误差均为0 bin，`gap_before=false`。
- 观察期间PFB新增`441,365`帧，所有PFB/XFFT错误为0；测试后DAC enable mask
  恢复为0并STOP到clean pipeline。
- 生产PFB内部`peak_chan/peak_power`寄存器当前固定回读0/0，不能用于验收。
  首次诊断失败保留在
  `../board/stage32f_160msps_pfb_bin_iq_tone_20260726.json`；正式判断使用接收机
  完整科学payload，而不是该不可用遥测。

### 160 TIME_SPEC正式结果

- 正式证据采用更严格的90秒PASS：
  `../board/stage32_160msps_time_spec_90s_link_diagnostic_20260726.json`。
- 接收机完整证据：
  `../board/stage32_160msps_time_spec_90s_link_diagnostic_20260726_host.json`。
- 主机90秒收到TIME `56,250,864`包、SPEC `56,252,837`包；
  TIME `625,009.6 pps`、SPEC `625,031.5 pps`，合计
  `83,202.737095 Mbit/s`。
- 24个flow全部活跃，parse/kernel/ring/app drop以及TIME/SPEC
  sequence/frame/sample0 gap增量均为0；SPEC preview完整16/16 blocks。
- 板端TIME/SPEC分别新增`62,352,159/62,352,157`包，PFB新增
  `3,897,009`帧；所有drop/route/PFB/XFFT错误增量为0，运行末端QSFP link up，
  STOP后pipeline clean。

### 保留的链路瞬变诊断

两次60秒TIME_SPEC运行的主机数据面和PFB均无损，但约70秒后的单次板端快照捕获到
QSFP link/TX-ready位同时为0，因此门禁正确判为FAIL：

- `../board/stage32_160msps_time_spec_board_host_20260726.json`；
- `../board/stage32_160msps_time_spec_board_host_retry_20260726.json`。

两次STOP快照均已恢复link up；随后覆盖该时间点的90秒门禁仍保持24-flow零gap/drop
并在运行末端link up，因此32f按更长PASS证据闭合。该瞬变不能删除或忽略，必须在
32h的1小时TIME_SPEC和8小时轮换soak中继续观察。CMAC `tx_frames_sent`遥测还出现
异步清零，但接收机逐flow包数、NIC物理计数、FPGA built/drop和连续性未显示数据
丢失；在32h中按`TX-TELEM-001`继续审计，不把该计数作为已发送包总量真值。

## 失败处置

停止SPEC/TIME流并保存PFB/XFFT/packet状态；修复当前Stage 32实现后从160
SPEC_ONLY重新验证。

## 下一阶段准入

160的TIME_ONLY、SPEC_ONLY和TIME_SPEC均已通过，允许进入32g的320 SPEC_ONLY。
