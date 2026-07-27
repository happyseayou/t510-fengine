# Stage 32c：RFDC ADC/DAC 1.6 GS/s、80 MHz PL 与 MTS

## 状态

`PASS`

## 目标

建立匹配 LMK160 的 RFDC/PL 时钟基线：ADC/DAC 都使用 160 MHz reference、1.6 GS/s、
5x decimation/interpolation 和 80 MHz AXIS，并恢复八路 DAC-ADC 自环和固定延迟 MTS。

## 前置条件

Stage 32b `PASS`。

## 实施内容

- PL input 160 MHz，ADC/DAC AXIS 80 MHz。
- ADC complex 5x decimation，DAC complex 5x interpolation。
- 保持 1024-bit science bus、128-bit DAC AXIS 和 continuous 10 MHz SYSREF。
- `CORE_VERSION=0x00010032`。
- `Target_Latency=-1` 做 40 次发现；ADC target 冻结为最大值加 20，DAC 为最大值加16。
- 固定 target 后复跑同一矩阵，不允许自动放宽。

## 已完成的实际改动

- `bd/t510_rfdc_bd.tcl`
  - PL reference 160 MHz；
  - Clock Wizard 160 MHz 输入、ADC/DAC AXIS 80 MHz；
  - ADC/DAC 1.6 GS/s，ADC 5x decimation，DAC 5x interpolation；
  - RFDC外部参考接口元数据与配置统一为160 MHz。
- `xdc/base_clocks.xdc` 将PL reference周期冻结为6.250 ns。
- `T510_STAGE32` 构建宏冻结 `CORE_VERSION=0x00010032`。
- `scripts/pynq_stage32_mts_campaign.py` 实现：
  - 20次RFDC reset、10次overlay reload、10次LMK reload；
  - discovery与fixed两个阶段；
  - discovery自动输出 `ADC max + 20`、`DAC max + 16`；
  - 每个cycle原子写入checkpoint JSON；
  - continuous SYSREF期间检查LMK SYNC GPIO未被MTS流程切换。
- LMK reload会中断RFDC reference。实测证明LMK重新锁定后必须等待模拟时钟稳定并
  reset八个RFDC tile，再运行MTS；否则DAC MTS返回
  `128/XRFDC_MTS_DTC_INVALID`。campaign已固化该恢复顺序。
- `scripts/pynq_stage32_8lane_loopback.py` 固化Stage 32固定target和八路
  phase/amplitude/SNR/clipping门禁，结束时无条件停流。
- Board Agent bitstream catalog增加固定ADC/DAC MTS target字段。Stage 32 catalog缺少
  非负target时拒绝启动，避免产品配置静默使用 `Target_Latency=-1`。

## Vivado结果

- 完成时间：`2026-07-26 03:06:47 +08:00`。
- bitstream SHA256：
  `d9ce5b49f6c6dbb5c9ff47f83e07e992a953f30444c28a680723cd251914e175`。
- fully routed：274749个routable net全部布通，routing error为0。
- WNS `+0.061 ns`，WHS `+0.010 ns`，TNS/THS均为0。
- DRC和methodology均无error或critical-warning violation。
- methodology中的 `TIMING-9/TIMING-10` warning规则没有形成新的CDC error类别。
- bit生成日志唯一critical warning为既有CMAC evaluation license限制。
- 完整证据：`../vivado/stage32c/build_summary.md`。

## 验收

- Vivado fully routed，WNS/WHS 非负，无新增 error。
- RFDC tile/FIFO ready，ADC/DAC MTS 全部成功。
- 八路 DAC-ADC：phase p-p ≤3°、amplitude p-p ≤5%、SNR ≥40 dB、无 clipping。

## 板端结果

板卡：`192.168.100.117`，bitstream：
`d9ce5b49f6c6dbb5c9ff47f83e07e992a953f30444c28a680723cd251914e175`。

### MTS discovery

- 初始campaign中RFDC reset `20/20`、overlay reload `10/10`通过，但LMK reload后
  未reset RFDC tile导致 `0/10`、错误统一为
  `XRFDC_MTS_DTC_INVALID`。该结果作为恢复顺序诊断证据保留。
- 加入“LMK lock -> 等待1秒 -> reset全部RFDC tile -> MTS”后正式campaign
  `40/40 PASS`：
  - RFDC reset `20/20`；
  - overlay reload `10/10`；
  - LMK reload `10/10`；
  - ADC发现范围 `180..210`；
  - DAC发现范围 `24..320`；
  - continuous SYSREF GPIO误切换 `0`。
- 固定target：
  - ADC：`max 210 + 20 = 230`；
  - DAC：`max 320 + 16 = 336`。

### 固定target

- 正式campaign `40/40 PASS`。
- ADC四tile每次均为230。
- DAC四tile每次为334或335，不超过target 336。
- MTS错误、tile错位、target超限和continuous SYSREF GPIO误切换均为0。

### 八路DAC-ADC

- `240`帧，每帧`512`样点。
- 最坏phase p-p：`0.465849 deg`。
- 最坏amplitude p-p：`0.934301%`。
- 最低SNR：`54.874483 dB`。
- 八路clipping均为false。
- 外部10 MHz/PPS诊断：`EXTERNAL_10MHZ_PPS_OK`。
- sample0从 `50491345724` 单调增长到 `53374033496`。
- 测试结束后science已停止。

## 非目标

本步骤不声明 100GbE 满速模式通过。

## 测试、证据、版本

- Vivado：`reports/vivado/stage32c/` 已归档。
- 本地验证：`reports/vivado/stage32c/local_verification.md`。当前LMK/half-band
  离线检查、45个Python测试、Board Agent 5个Rust测试、receiver 36个Rust测试和
  31个默认XSim testbench均通过。
- discovery：
  `../board/stage32c_mts_discovery_after_clock_reset_20260726.json`。
- fixed：
  `../board/stage32c_mts_fixed_20260726.json`。
- 八路自环：
  `../board/stage32c_8lane_loopback_20260726.json`。
- 恢复顺序诊断：
  `../board/stage32c_mts_discovery_20260726.json`。
- 版本：Git HEAD `53f46bb73a2d`，最终身份以bitstream SHA256为准。

## 失败处置

立即停止science，保存MTS/clock/RFDC状态；修复Stage 32配置后从LMK lock和
fresh-download重新开始，不切换历史bitstream。

## 下一阶段准入

32c证据齐全，允许进入32d的320 MS/s TIME_ONLY。后续Stage 32配置必须固定使用
ADC target 230、DAC target 336，不允许静默放宽。
