# Stage 34b-2：训练冻结因果实验

## 当前状态

状态为
`ORIGINAL_CAUSALITY_FAIL / LOW_RF_EXTENSION_TERMINATED_BY_USER / 34B-3_BLOCKED`。

原始完整18次A/B/C队列已于2026-08-09 00:58:45 CST结束。18/18个run和全部数字完整性
门禁均通过，但训练后冻结B没有恢复`1/sqrt(N)`：160 MS/s的B条件合格比例为19.4%、
中位斜率为`-0.267`、中位`|lag-1|`为0.322；320 MS/s分别为9.7%、`-0.246`和
0.408。A基线在两种速率下均复现，因此最终结论为
`T510_STAGE34B2_CAUSALITY_FAIL`，不是运行程序崩溃。按原硬门禁34b-3/4仍不得进入。

用户随后要求增加30～350 MHz低RF组。端点30/350 MHz位于计划通带边缘，因此正式测点
保留约20 MHz保护带并分成两个可同时监测的子带：

- 低段：50、75、100、125、150、175 MHz；
- 高段：205、230、255、280、305、330 MHz。

每个子带均执行160/320 MS/s、A/B/C、三次平衡重复，总计36次fresh CONFIGURE/MTS和
36×600秒积分。所有测点均为精确PFB bin；160 MS/s的两个子带中心分别为112.5和
267.5 MHz，320 MS/s中心分别为160和267.5 MHz。完整队列已于2026-08-09 15:58:59 CST
首次尝试，并于2026-08-09 16:03:32 CST成功作为用户级systemd长任务
`t510-stage34b2-low-rf.service`一次性提交。15:58:59的首次启动因入口缺少仓库根路径而在
任何硬件操作前退出，未创建campaign；16:00:15的首次硬件run因板端时钟领先采集机4 ms、
被原零负容差误判为陈旧快照而在9秒处安全终止。该证据保存在
`low_rf_attempt1_clock_skew_fail`，没有并入正式数据；将跨主机未来偏差容差限定为1秒并
通过回归后才形成有效提交。

用户于2026-08-09 17:28:20 CST明确终止低RF扩展，把工作转向OCB1、时钟/供电和模拟链路
定责。终止前完成7个完整的160 MS/s run，第8个run在fresh CONFIGURE期间中断并明确排除；
320 MS/s及其余平衡重复均未执行，因此这些数据只作诊断提示，不能补成正式A/B/C结论。
7个完整run的中位斜率为`-0.187..-0.313`，时间打乱后为`-0.511..-0.550`，说明50～330 MHz
也已经看到与原681.25～792.5 MHz组同类的时间相关过程。样本不足以比较A/B/C或判断
RF依赖强弱。

终止后已显式STOP、静音八路DAC并解除八路freeze，最终回读为`streaming=false`、
`stream_accepting=false`、DAC enable mask=`0x00`、八路幅度码全0、
`frozen_adc_mask=0x00`、receiver流量0。队列不会恢复，也不会自动重试。

固定运行证据位于：

- `build/receiver/latest/evidence/rfdc_calibration/34b2/campaign.json`
- `build/receiver/latest/evidence/rfdc_calibration/34b2/runs/`
- `build/board/latest/evidence/rfdc_calibration/34b2/campaign_summary.json`
- `build/receiver/latest/evidence/rfdc_calibration/34b2/low_rf/campaign.json`
- `build/receiver/latest/evidence/rfdc_calibration/34b2/low_rf/runs/`
- `build/board/latest/evidence/rfdc_calibration/34b2/low_rf/campaign_summary.json`
- `build/receiver/latest/evidence/rfdc_calibration/34b2/low_rf_attempt1_clock_skew_fail/`

## 训练电平门限的修正

原计划使用的时域RMS `-24..-8 dBFS`不是器件规范规定的门限。AMD RFSoC RF Data
Converter PG269规定GCB和TSCB运行所需的最小输入信号为`-40 dBFS`；因此本阶段采用
`-36 dBFS`作为工程下限，保留4 dB余量，上限仍为`-8 dBFS`，peak必须低于`-1 dBFS`
且不得clip。

对同一fresh 320 MS/s配置实测25%、50%、75%、100%四档DAC幅度。100%是第一个能让
全部八路满足工程下限的档位，八路时域RMS为`-33.696..-32.639 dBFS`。各档功率增量
同时接受线性检查，所有通道误差均不超过1.5 dB。100%在这里表示DAC DDS的数字幅度码，
不表示ADC已经接近满量程；ADC仍有约32 dB RMS余量。

正式预检证据：

- `build/board/latest/evidence/rfdc_calibration/34b2/amplitude_preflight_pg269.json`
- SHA-256：`b5e2cad58819b5803fe9b91aa8594a77342c353fa268a7a689cbfa8b8acf7ea6`

## 系数平稳性判据

GCB/TSCB是冻结前持续工作的后台自适应环路，要求全部256个子系数连续2秒完全不动或
逐项变化不超过1 LSB，会把正常微调误判成“未收敛”。另外，RFDC返回值中每个32-bit
字段打包了两个有符号子系数；必须按GCB 12 bit、TSCB 9 bit分别解包，并按二补码环形
距离计算变化，否则高16位的一次1 LSB更新会被误报成65536 LSB，边界跨越也会被误报
成511/4095 LSB。

修正后的连续2秒平稳性门禁为：

- 256个子系数变化量的中位数不超过1 LSB；
- 95分位不超过4 LSB；
- 任一离群变化不超过32 LSB。

正式预检在2.009秒内通过：每个5 Hz采样间隔的中位数均为0 LSB，95分位为1～3 LSB，
最大值为6～22 LSB。随后八路原子冻结回读mask=`0xff`，驻留watchdog再次独立读回
mask=`0xff`；安全收尾无错误。

前两次失败证据没有删除，分别保留为：

- `amplitude_preflight_pg269_attempt1_packed_decode_fail.json`：打包字段解码错误；
- `amplitude_preflight_pg269_attempt2_exact_1lsb_fail.json`：不合理的逐项1 LSB硬判据。

它们只记录预检方法的修正过程，不是A/B/C科学结果，也没有被拼接进正式队列。

## 最终门禁

以下是低RF扩展原定但已停止的判据，仅用于说明为什么7个已完成run不能正式判定：B条件
每次至少75%、合计至少80%的
`ADC×安全bin`斜率落入`-0.65..-0.35`；中位lag-1相关不超过0.10；原始与时间打乱后的
中位斜率差不超过0.10；相对A的合格率至少提高50个百分点、斜率误差至少改善0.12。
A若不能复现原问题则结论只能是`INCONCLUSIVE_BASELINE_NOT_REPRODUCED`。任何一种采样率
不通过都不得进入34b-3或34b-4。原始681.25～792.5 MHz组已经失败的事实不变；终止的
低RF数据不用于通过挑选频段绕过门禁。

所有run仍要求packet、seq、frame、sample0、FPGA/NIC/ring/worker/application drop与gap
均为零，且无backpressure、FIR saturation或XFFT overflow。B/C积分期间freeze mask必须
始终为`0xff`，GCB/TSCB哈希必须完全不变；A必须保持动态校准。
