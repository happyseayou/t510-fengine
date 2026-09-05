# Stage 32e：160 MS/s、80 dB half-band 与 TIME

## 状态

`PASS`

## 目标

使用 55-tap Q1.17 half-band 把 320 MS/s 转为160 MS/s，并验证数字阻带≥80 dB和
TIME_ONLY无损输出。

## 前置条件

Stage 32d `PASS`。

## 冻结滤波器

- 55 taps，group delay 27个320 MS/s基准样点。
- passband 0..64 MHz，stopband 96..160 MHz。
- coefficient ID `0xAA160055`。
- 通带纹波≤0.1 dB，量化后阻带≥80 dB，DC gain精确为1。
- 使用DSP流水和分级加法树；实现延迟不写入信号时间戳。
- 首 TIME sample0 保持 `mod 8 = 4`。

## 验收

- stdlib离线频响、定点仿真和RTL backpressure测试通过。
- 160 TIME总计约625 kpps、41.93 Gbit/s，板端/主机无drop/gap。
- 模拟自环只验证到可测噪声底；80 dB是数字滤波器验收值。

## 非目标

不声明 SPEC 或最终科学幅相标定。

## 测试、证据、版本

### 已准备但尚未计入阶段通过的改动

- `rtl/science_decim2_halfband_aa.sv` 已实现55-tap Q1.17对称half-band、
  DSP乘法流水和分级加法树。
- 160路径的half-band ID固定为 `0xAA160055`，320路径旁路。
- sample0继续使用320 MS/s基准语义；160相邻科学样点递增2。

### 本地结果

- `python3 scripts/stage32_verify_halfband55.py`：PASS。
- ripple `0.000742 dB`，stopband attenuation `86.539 dB`，
  Q1.17系数和为131072，group delay为27。
- 定点动态仿真在最坏阻带边界96 MHz使用幅度30000、8个初相、每相8192点，
  按RTL相同的Q1.17乘加和round-away-from-zero量化，最差阻带衰减
  `85.070 dB`，仍高于80 dB门限。
- `tb_science_rate_selector`、`tb_science_stream_decimator`及顶层smoke：PASS。
- 证据：`../vivado/stage32c/local_verification.md`。
- bit SHA256：
  `d9ce5b49f6c6dbb5c9ff47f83e07e992a953f30444c28a680723cd251914e175`。

### 板端与主机正式结果

- 正式证据：
  `../board/stage32_160msps_time_only_board_host_20260726.json`。
- 接收机完整证据：
  `../board/stage32_160msps_time_only_board_host_20260726_host.json`。
- classification：`STAGE32_160MSPS_TIME_ONLY_BOARD_HOST_PASS`。
- 主机60秒收到`37,516,944`个TIME包，平均`625,282.4 pps`，
  T510 UDP payload为`41,618.796544 Mbit/s`；SPEC包为0。
- 主机parse、kernel、packet ring、worker ring、application drop均为0；
  sequence、frame和sample0 gap增量均为0，接收机检测采样率为160 MS/s。
- 板端观测窗口内TIME新增`43,560,366`包，SPEC新增0；
  RFDC/science/TIME/SPEC/TX drop和route error/miss增量均为0。
- 运行期间half-band为active/primed、55 taps、ID `0xAA160055`；LMK、
  MTS和QSFP状态正常。
- 门禁结束后Agent自动STOP，pipeline `flush_clean=true`。

### 定时首样点

- 证据：
  `../board/stage32e_160msps_scheduled_first_sample0_20260726.json`。
- 单板PREPARE/ARM generation `32160001`在本地PPS计数234提交。
- 请求和硬件实际首TIME sample0均为`32788`，满足`32788 mod 8 = 4`。
- `epoch_committed=true`、`first_time_seen=true`、同步error为false；
  连续验证窗口TIME新增`5,784,517`包，RFDC drop增量为0。
- 普通`/start`用于吞吐门禁，不重置观测历元；`mod 8 = 4`由保留的
  PREPARE/ARM定时启动路径验证。该区分不改变UDP sample0单位或格式。

### 模拟链边界

32c的八路DAC-ADC自环已经证明当前模拟链和RFDC配置可稳定观测tone，最低SNR
`54.87 dB`。80 dB阻带指标由系数频响和包含16-bit输出量化的定点数字仿真判定；
不以当前模拟链约55 dB可观察噪声底否定或冒充数字滤波器结果。

## 失败处置

停止science并保存half-band/packet证据；修复当前Stage 32 half-band后重新执行
离线频响、XSim和板端160 TIME测试。

## 下一阶段准入

数字频响、定点量化、160 TIME满速门禁和定时首样点证据齐全，允许进入32f的
160 SPEC_ONLY与TIME_SPEC。
