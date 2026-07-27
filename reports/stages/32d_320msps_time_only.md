# Stage 32d：320 MS/s TIME_ONLY

## 状态

`PASS`

## 目标

验证 RFDC 320 MS/s complex 旁路到现有 TIME packet/CMAC 路径，不改变 wire contract。

## 前置条件

Stage 32c `PASS`。

## 实施内容与门禁

- `sample0` 使用 320 MS/s 基准，相邻样点增量1。
- 8路 TIME、128 B header、8192 B payload、端口 `4300..4307`。
- 60秒板端和60秒主机门禁：约1.25 Mpps、83.86 Gbit/s。
- FPGA、NIC、kernel、ring、应用 drop 和 sequence gap 全为0。
- 320 `TIME_SPEC` 必须被明确拒绝。

## 非目标

不启用 PFB/SPEC，不声明160路径。

## 测试、证据、版本

### 实际改动

- PL控制面只接受160/320两档，320路径旁路half-band。
- 320 `TIME_SPEC` 在Python、Rust API和RTL控制面均明确拒绝。
- TIME header、8192 B payload、8个flow和端口 `4300..4307` 未改变。
- `scripts/stage29_board_validate.py` 与 `scripts/stage29_host_validate.py`
  已按Stage 32速率和分类更新；历史文件名保留以减少入口变化。
- Board Agent只安装Stage 32 bit/profile catalog，避免新旧LMK/bitstream混用。
- 正式配置固定使用manual CLKin2、continuous 10 MHz SYSREF、ADC target 230、
  DAC target 336和8个TIME endpoint。
- production configure流程在LMK reload稳定后reset全部RFDC tile再执行MTS，
  与32c campaign中验证通过的恢复顺序一致。
- PYNQ active bit身份从“路径相同”收紧为“SHA1相同”，允许Agent识别PYNQ
  canonical path alias，但仍拒绝内容不同的bitstream。
- Rust接收机在配置generation改变时清除旧generation连续性基线，防止把两次
  独立运行之间的正常sample0跳变误报为本次丢包。

### 本地结果

- `tb_science_rate_selector`、`tb_time_packetizer`、`tb_time_udp_cmac512`、
  `tb_feng_ctrl_axi`和顶层smoke均PASS。
- Python单元测试覆盖五种合法profile和320 `TIME_SPEC`拒绝；当前完整回归
  `45/45 PASS`。
- Board Agent `5/5`、receiver `36/36` Rust测试和31个默认XSim testbench通过。
- 证据：`../vivado/stage32c/local_verification.md`。
- bit SHA256：
  `d9ce5b49f6c6dbb5c9ff47f83e07e992a953f30444c28a680723cd251914e175`。

### 板端与主机正式结果

- 正式证据：
  `../board/stage32_320msps_time_only_board_host_pass_20260726.json`。
- 接收机完整证据：
  `../board/stage32_320msps_time_only_board_host_pass_20260726_host.json`。
- classification：
  `STAGE32_320MSPS_TIME_ONLY_BOARD_HOST_PASS`。
- 主机60秒收到`75,032,400`个TIME包，平均`1,250,540 pps`。
- 主机T510 UDP payload为`83,235.9424 Mbit/s`；SPEC包为0。
- 主机parse、kernel、packet ring、worker ring、application drop均为0；
  sequence、frame和sample0 gap均为0。
- 板端观测窗口内TIME新增`87,378,433`包，SPEC新增0；
  RFDC/science/TIME/SPEC/TX drop、route error/miss增量均为0。
- LMK保持manual CLKin2、双PLL锁定和continuous SYSREF；MTS ADC实测230、
  DAC实测335，分别不超过固定target 230/336。
- 320路径half-band为inactive；QSFP link up。
- 门禁结束后Agent自动STOP，pipeline `flush_clean=true`。

### 非法模式拒绝

向Agent提交320 `TIME_SPEC`配置得到HTTP 400和
`SCHEMA_VALIDATION_FAILED`，因此非法组合在启动打流前即被拒绝。

### 保留的诊断记录

第一次正式运行保留在
`../board/stage32_320msps_time_only_board_host_20260726.json`。该次T510数据的
主机连续性和应用计数均为0 gap/drop，但专用NIC的
`rx_steer_missed_packets`增加19，被旧验证器的宽泛NIC正则判为失败。该mlx5计数表示
没有命中flow-table规则而被丢弃的包；当前接口只为目的端口`4300..4323`安装精确
ntuple规则，因此它也可能统计与T510 science无关的背景帧。验证器现在保留该原始
计数和warning，同时继续严格检查T510 sequence/sample0、kernel/ring/app drop以及
其他物理错误。最终PASS运行中该计数增量也为0。

### 版本

- Git HEAD：`53f46bb73a2dca3d32af86c95b02561796c1d53c`；工作树Stage 32改动
  未提交，bitstream SHA是硬件身份。
- Board Agent release：`stage32-53f46bb73a2d-20260726070320`。
- receiver release：`stage32-53f46bb73a2d-20260726070721`。
- receiver binary SHA256：
  `56d19e0686aafa022581e7a9b59cb40dfe7464edcd0a92117f5b0226e99fe5db`。

## 失败处置

停止science并保存Stage 32 clock/MTS/TIME counters，不启动后续模式；修复当前
Stage 32实现后fresh-download复测。

## 下一阶段准入

板端和主机证据齐全，允许进入32e的160 MS/s half-band TIME_ONLY。
