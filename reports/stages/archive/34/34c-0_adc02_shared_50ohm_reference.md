# Stage 34c-0：ADC0/ADC2共享50 Ω参考长积分实验

## 状态

当前状态：`COMPLETE / SHARED_50OHM_REFERENCE_REPRODUCES_CORRELATED_NOISE / ENTERED_34C1`。

Invocation ID`b0994db7b1964421b0ee30a30deac419`已完成320 SPEC_ONLY和160 TIME_SPEC性能
预检及全部六次34c-0正式run；每次均有601条伴随记录且数字门禁为零。160 MS/s的30个组合
只有6个斜率合格，中位斜率-0.304、中位绝对lag-1为0.354；320 MS/s只有4/30合格，中位
斜率-0.251、中位绝对lag-1为0.490。时间打乱后中位斜率分别为-0.531和-0.520，因此共享
50 Ω输入没有消除时间相关过程，campaign按计划进入34c-1。

此前一次运行的receiver已完整完成600秒，但watchdog以`last=now`调度1 Hz伴随采样，回调
与100 ms轮询抖动逐周期累积，最终只有559条而触发严格的`>=595`门禁。修复后调度锚定理想
周期且不回填真正漏掉的整秒；实机25.027秒取得26个快照，间隔中位数1.001秒、最大
1.004秒。该失败证据保存在`operational_failures/attempt_5`，未降门限或挑选数据。

下一次运行仍只有572条，原因不是watchdog周期，而是campaign每条观测都重新序列化并覆盖
整份轨迹；约第401条后，约58 MB的pretty JSON与HTTP查询使采集循环开始错过中间快照。
修复后运行中只逐行追加并flush`calibration_ams_trace.jsonl`，正常完成或可控异常时再一次性
生成原格式`calibration_ams_trace.json`，强杀时保留JSONL现场；`>=595`门禁保持不变。该现场
保存在`operational_failures/attempt_6`。重新提交后的正式run在receiver第43秒时已有44条
JSONL记录，所有数字门禁为零。

本阶段不再把“DAC数字幅度为0”当作无输入。物理输入固定为：

`SSA RF INPUT（TG关闭、preamp关闭、20 dB衰减） → 二路功分器 → ADC0/ADC2`

其余ADC及全部DAC物理断开，板端DAC enable mask和八路幅度码仍必须为0。SSA的RF输入是
标称50 Ω，但ADC0和ADC2共享同一个终端，因此本阶段结论严格命名为
`SHARED_50OHM_REFERENCE`，不外推成八路独立50 Ω或跨路天文相干资格。

## 自动实验

固定`center=1020 MHz`，监测960、980、1000、1040、1060、1080 MHz。960 MHz是已知
`Fs/4`交织固定项，只观察、不进入干净bin门禁；其余五点在160/320 MS/s均精确落bin。

预检顺序为：

1. 核对v34、4096通道、8-tap、profile `0x34a80001`，STOP、DAC静音、freeze mask=0；
2. 停流preview检查八路无clip且peak低于-1 dBFS；
3. 每次开流先保持全速预热，直到PS/PL/remote每只传感器各自连续60秒的前10秒与后10秒
   中位温度差不超过0.30 °C；该稳健趋势判定避免AMS约0.3 °C读数抖动支配预热状态，最长
   等待600秒，超时仍失败；正式run同时保存未平滑原始值，并以10秒滚动中位温度执行
   2 °C峰峰值门禁，避免AMS约0.3 °C读数抖动中的单点极值冒充真实板温阶跃；
4. 320 MS/s SPEC_ONLY、160 MS/s TIME_SPEC各做60秒monitor关闭/开启A/B，要求所有drop、
   gap、backpressure、FIR saturation和XFFT overflow增量为0；
5. 按`160-r1 → 320-r1 → 320-r2 → 160-r2 → 160-r3 → 320-r3`执行六次600秒
   SPEC_ONLY，每次fresh CONFIGURE/MTS，OCB1/GCB/TSCB保持动态。

每种速率的正式门禁是每次至少8/10个`ADC×clean-bin`斜率落在`-0.65..-0.35`，合计至少
24/30，每次中位斜率合格，中位`|lag-1|≤0.10`，原始/时间打乱中位斜率差不超过0.10。
两种速率都通过时分类为`SHARED_50OHM_REFERENCE_RECOVERS_LONG_INTEGRATION`并正常结束；
否则自动追加一次160 MS/s TIME_SPEC 600秒定位run，并进入Stage 34c-1。科学门禁不通过
不是service崩溃，只有运行或安全故障才非零退出。

## 数据合同与产物

receiver只使用现有PACKET_MMAP主环，`lane_mask=0x05`，相关对固定ADC0/ADC2；不会创建
第二个packet socket。TIME_SPEC只按包序轮转抽取一个复样点，统计每秒I/Q均值、RMS、
峰值和clip。每次run首尾从同一接收环导出原始PCAP：SPEC为16端口×32包，TIME_SPEC为
24端口×32包，并生成SHA256。

正式结果写入固定目录：

- `build/receiver/latest/evidence/adc_correlated_noise_root_cause`
- `build/board/latest/evidence/adc_correlated_noise_root_cause`

自动生成每个run的功率时间线、原始/打乱积分曲线、Allan deviation、ACF、跨频相关矩阵，
定位run额外生成TIME RMS；另生成AMS温度/电压共时间轴、CSV、JSON及PCAP manifest。

## 已完成的软件验证

- Python全仓`unittest`：150项通过；
- receiver Rust：47项通过，其中覆盖ADC0/ADC2 lane mask、轮转TIME抽样、gap中止和24流
  TIME_SPEC PCAP；
- Board Agent Rust：7项通过；
- 当前阶段不修改RTL、PFB、UDP、bitstream或CORE_VERSION，也不运行Vivado。

最终科学结果须在长任务完成后从冻结证据回填；在此之前Stage 34a的长积分失败结论不变。
