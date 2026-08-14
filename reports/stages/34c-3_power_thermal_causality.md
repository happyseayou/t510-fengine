# Stage 34c-3：板内负载、供电与热稳定性调查

## 当前状态

`IMPLEMENTED / REGRESSION_PASS / DEPLOYED / LONG_TASK_COMPLETE /
OPERATIONAL_PASS / OUTPUT_LOAD_NOT_CAUSAL /
DAC_TILE_INTERVENTION_UNQUALIFIED / LONG_INTEGRATION_FAIL`

本阶段继续使用正式v34：`CORE_VERSION=0x00010034`，bitstream SHA256为
`c21d93f5ea71e9ac17a4448cff138a8faaf9c7347d879be919b680d196b8a5be`，固定4096通道、
8-tap PFB和生产`160m_10m_cont_manual_clkin2`时钟profile。不修改RTL、PFB、UDP、LMK
profile或系数，不运行Vivado。

物理输入保持`SSA RF INPUT → 二路功分器 → ADC0/ADC2`共享50 Ω参考，SSA TG和preamp
关闭、输入衰减20 dB；其余ADC和全部DAC物理断开，板端DAC数字mask和八路幅度恒为0。
科学门禁只使用离开10 MHz SYSREF栅格、且在160/320 MS/s均精确落bin的
966.875、988.75、1007.5、1032.5、1051.25、1073.125 MHz。960 MHz固定项和11个
10 MHz栅格点保留原始观测，但不进入积分斜率门禁。

## 已实现控制面与监测

- resident watchdog以5 Hz读取PS、PL、remote温度和AMS可见内部电压，每秒生成
  min/mean/max，并把唯一epoch、递增sequence、stream状态、RFDC tile状态、校准系数哈希
  和OCB1 DFT写入`/run/t510-power-thermal.jsonl`有界环；service重启形成新epoch。
- `GET /api/v2/telemetry/power-thermal?since_seq=N`只读取resident缓存，不触碰PL、SPI或
  RFDC。600秒要求至少594条唯一记录，3600秒要求至少3564条，最大sequence缺口2秒。
- `POST /api/v2/diagnostics/output-load`及`restore`只在停流安全状态切换160 MS/s的
  SPEC_ONLY/TIME_SPEC、TIME endpoint和八条TIME路由；切换前后保护MTS ID、NCO、时钟、
  PFB、FFT和系数指纹，并用一次性事务ID约束START。实机快速A/B/A已经通过。
- `GET /api/v2/rfdc/power`提供四个ADC和四个DAC tile的IPStatus；shutdown/restore接口
  使用官方RFDC驱动，START必须匹配一次性电源事务。恢复路径固定为完整production
  CONFIGURE/MTS，不能把简单StartUp当作已恢复。
- receiver正式SPEC monitor支持600或3600秒、`lane_mask=0x05`和TIME_SPEC轻量TIME统计，
  继续使用现有PACKET_MMAP主环，不创建第二个packet socket。
- 自动分析计算积分斜率、Allan deviation、原始/打乱对照、lag-1、ACF、Spearman、一阶
  差分、±60秒交叉相关、块bootstrap 95%区间和Benjamini–Hochberg校正。AMS记录按receiver
  monitor的`started_unix_ms`对齐，不能把预热段错当成正式功率相关。

## DAC tile干预资格结果

在正式长矩阵前，按注册操作调用
`XRFdc_Shutdown(Type=DAC, Tile_Id=-1)`。四个DAC tile都进入`PowerUpState=0`、
`TileState=1`，但驱动等待restart-clear状态6超时：

```text
DAC 0 timed out at state 6 in XRFdc_WaitForRestartClr
```

因此没有得到“四个DAC tile全部停止、四个ADC tile继续运行”的正式回读，也没有在这个
中间状态授权science START。简单StartUp不能恢复，随后独立完整v34 CONFIGURE/MTS成功，
最终回读四个ADC/DAC tile全部运行、stream停止、DAC全零、freeze=0、OCB1动态、生产时钟和
双PLL锁定。冻结证据为
`build/board/latest/evidence/power_thermal_causality/dac_intervention_qualification.json`。

该层按计划注册规则标为`INTERVENTION_UNQUALIFIED`，不会重试，也不会把“没能安全执行”
写成`DAC_TILE_STATE_NOT_CAUSAL`。长任务继续执行相互独立且已经实机验证安全的数字输出负载
层和自然AMS观察层。完整注册矩阵仍保留29-run定义；本次安全可执行队列为9个输出负载run
加2个60分钟自然观察run，共11个正式run、12600秒纯采集。

## 自动队列与门禁

输出负载层执行三组600秒：

```text
A1 SPEC_ONLY → B TIME_SPEC → A2 SPEC_ONLY
```

每组只在A1前fresh CONFIGURE/MTS，A1/B/A2之间仅使用output-load事务。自然观察层分别执行
160和320 MS/s SPEC_ONLY各60分钟。每个正式run开始和结束从receiver主环导出PCAP并生成
SHA256；TIME_SPEC保存24流，SPEC_ONLY保存16流。

硬门禁包括零drop/gap、零sample0跳变、零backpressure、零FIR saturation、零XFFT
overflow、零clip、PLL不失锁和resident遥测不断代。每个run前以当前负载连续60秒热稳定；
600秒run使用2.0 °C警告和2.5 °C硬停止，60分钟使用2.5 °C警告、5 °C环境异常停止及
70 °C绝对安全停止。

科学分类不得越过仪器边界：AMS只有慢趋势分辨率，因此即使出现显著相关，也只允许
`POWER_THERMAL_CORRELATED_ONLY`；长期保留
`ADC_ANALOG_RAIL_RIPPLE_QUALIFICATION_PENDING`和
`THERMAL_CAUSALITY_PENDING_ACTIVE_CONTROL`。DAC tile层未取得干预资格时，最终分类会显式
包含`DAC_TILE_INTERVENTION_UNQUALIFIED`，不会伪装成已经排除。

## 长任务和产物

自动入口为`scripts/t510_power_thermal_causality.py`，用户级systemd unit为
`deploy/t510/t510-stage34c3-power-thermal.service`。固定证据目录：

- `build/board/latest/evidence/power_thermal_causality`
- `build/receiver/latest/evidence/power_thermal_causality`

任务按长任务规则一次性提交；步骤成功自动进入下一步，任何运行或安全故障立即STOP、DAC
静音、恢复tile/freeze/OCB1和生产配置，不自动挑选数据。确认首个正式600秒run健康进入后
停止轮询。最终科学数值、图、PCAP manifest和安全收尾现已全部闭合，见下文“最终正式
结果”。

最终已生成A1/B/A2功率时间线、斜率/lag/合格率总览、60分钟积分和Allan曲线、功率—温度—
内部电压—OCB1共时间轴、传感器×ADC×RF相关热图、CSV、JSON、PCAP及SHA256 manifest。

提交前回归于2026-08-12完成：Python 191项、Board Agent Cargo 8项、receiver Cargo 48项
全部通过，repository hygiene、OpenAPI JSON及systemd unit校验通过。部署后的Board Agent
SHA256为`b7d79ec83469cce70f0e2903adc5e4bbe82d5a1309452176bd5a4a0f0144463e`，receiver
SHA256为`aa43a6a742c2127c551a3c09bebf6d21a07cc2cfb988e2dd941bdc1f9e13f466`。在线回读确认
v34、生产continuous profile、双PLL锁定、四个ADC/DAC tile全运行、停流、DAC全零、
freeze=0、OCB1动态，resident新epoch持续递增。

首次长任务invocation `b958cbcdb7ba490796d9e51eba54b7d0`在collector关闭预检中受控停止：
脚本在START前取计数基线，把START过渡期`rfdc_dropped +18`错误计入120秒稳态窗口。失败
证据完整保留为`operational_failures/attempt_1`。稳态合同已统一为START、等待2秒、再取
基线；独立320 MS/s 10秒资格实测83.62 Gbit/s且全部计数增量为0。

第二次invocation `c1a26790918946cdb663e218dfc9b68c`通过两种collector A/B后，在输出负载
快速B段正确发现`time_dropped / tx_frames_dropped / tx_route_miss`并受控停止，证据保留为
`operational_failures/attempt_2`。根因是TIME宽路径每拍携带8路聚合输入，route lookup要求
单条`input_mask=0x00ff`；旧诊断实现错误写成8条单bit mask，因而没有任何route匹配。
修复后冻结为一条聚合route，再由既有8-way multiflow按seq轮转endpoint 0..7，并逐项回读
endpoint、route和multiflow。Python完整回归现为191项通过。独立10秒A1/B/A2实机资格结果：

| 条件 | 模式 | 实测吞吐 | route/drop/gap/饱和/overflow增量 |
|---|---|---:|---:|
| A1 | 160 SPEC_ONLY | 41.81 Gbit/s | 全0 |
| B | 160 TIME_SPEC | 83.60 Gbit/s | 全0 |
| A2 | 160 SPEC_ONLY | 41.79 Gbit/s | 全0 |

修复前后的MTS/NCO/PFB/时钟保护指纹均为
`299c9eb56ac49e248fd80721e25d9f2f458227fd5ea9fee93967cb4ec9602db1`；未通过清计数、
降速或删除TIME流取得通过。

第三次正式长任务invocation `8a7fdb6cf62840808b0d005831f88ad5`于2026-08-12 16:28:34
CST提交。完整预检已原子通过；首个正式run `output_load_r1_a1_spec_only`于16:51:51左右
进入600秒monitor。16:52:58复核时已完成76秒，160 SPEC_ONLY实测41.81 Gbit/s，板端
`rfdc_dropped/science_dropped/time_dropped/spec_dropped/tx_frames_dropped/route_miss/route_error`
均为0，receiver kernel/ring/worker/application drop和seq/frame/sample0 gap均为0，FIR
saturation、XFFT overflow和capture backpressure均为0。按长任务规则已停止主动轮询，等待
用户之后要求检查最终证据。

## 最终正式结果

### 队列闭合与环境事件

第三次invocation完整完成9个输出负载600秒run和首个160 MS/s自然观察的3600秒采集；但
用户在该小时中途关闭房间空调，PL、PS和remote温度跨度分别达到7.560、7.728和7.633 °C，
超过预注册的5 °C环境异常硬停止线。该160 MS/s run因此作为运行失败现场保留，不能进入
正式科学统计，队列也没有继续启动320 MS/s。这里没有放宽门限或挑选结果。

空调恢复并满足连续60秒、前后10秒中位温差不超过0.30 °C后，增加只允许补自然观察的
`--resume-natural`断点入口。它要求原9个输出负载run全部成功、拒绝覆盖旧目录，并给重试
使用单调`retryN`后缀。续跑invocation
`ec53e9a5785b449abd9c4be1b0626287`于20:02:06 CST提交：

| 有效run | 正式采集 | 温度跨度（PL / PS / remote） | 温度门禁 |
|---|---:|---:|---|
| `natural_160msps_60min_retry1` | 3600秒 | 3.816 / 3.963 / 3.614 °C | 2.5 °C警告，低于5 °C硬线，PASS |
| `natural_320msps_60min_retry1` | 3600秒 | 1.627 / 1.792 / 1.279 °C | 无警告，PASS |

两条run分别取得3613条唯一秒级AMS记录，高于3600秒run要求的3564条；每条生成129600个
`ADC×RF×秒`功率记录。160 MS/s在负载稳态建立后仍有自然缓慢升温，所以如实保留警告；
320 MS/s环境更稳定。两条run均没有触及70 °C绝对保护线。

最终有效矩阵是9个输出负载run加2个自然观察run，共11个正式run、12600秒纯采集。每个
有效run的FPGA、NIC、PACKET_MMAP、worker和application drop均为0，seq/frame/sample0 gap、
backpressure、FIR saturation、XFFT overflow、clip和PLL失锁均为0。manifest共列24份PCAP：
22份来自11个有效run，另2份是上述温度失败现场；所有24份SHA256均已复核通过。manifest
SHA256为`e4497fda2bfc23343dd45b47d8cd78e729141152b8ea40f142e1c9ad4d5a8d65`。

### 数字输出负载不是根因

输出负载层比较唯一变量为SPEC_ONLY约41.6 Gbit/s与TIME_SPEC约83.2 Gbit/s：

| 条件 | 模式 | 斜率合格 | 中位斜率 | 打乱后中位斜率 | 中位绝对lag-1 |
|---|---|---:|---:|---:|---:|
| A1 | SPEC_ONLY | 9/36（25.0%） | -0.2576 | -0.4999 | 0.3737 |
| B | TIME_SPEC | 6/36（16.7%） | -0.2471 | -0.5577 | 0.4127 |
| A2 | SPEC_ONLY恢复 | 3/36（8.3%） | -0.2167 | -0.5192 | 0.4048 |

TIME_SPEC没有恢复绝对长积分门禁，相对A1的合格率反而下降8.3个百分点，斜率误差和lag也
没有达到预注册的可逆变化幅度；A2与A1仍在注册的回归容差内。故正式结论为
`OUTPUT_LOAD_NOT_CAUSAL`：打开TIME packetizer、路由和双倍CMAC/网络流量不是已观测相关噪声
的主导根因。这个结论不表示数字输出没有任何温升，只表示它没有产生满足因果门禁的科学
指标变化。

### 60分钟结果确认相关噪声持续存在

六个离10 MHz栅格科学点、ADC0/ADC2共12个组合的结果为：

| 模式 | 斜率合格 | 中位斜率 | 时间打乱后 | 中位绝对lag-1 |
|---|---:|---:|---:|---:|
| 160 MS/s SPEC_ONLY | 0/12 | -0.02149 | -0.50656 | 0.83363 |
| 320 MS/s SPEC_ONLY | 0/12 | -0.01754 | -0.52218 | 0.85171 |

理想独立白噪声随积分时间的标准差斜率应接近-0.5。原始序列接近0且相邻秒相关约0.84，表示
延长积分几乎不能继续压低这部分慢变化；把相同数值打乱时间顺序后立即恢复约-0.5，排除了
PFB、UDP顺序或积分公式本身无法产生白噪声规律的解释。Stage 34a的
`LONG_INTEGRATION_FAIL`因此继续有效，不能给出天文长积分资格。

注册的AMS相关分类没有找到任何温度或内部电压量，能在至少4个独立run中同时满足方向一致、
BH校正显著和中位`|rho|≥0.35`，所以结果为“没有达到`POWER_THERMAL_CORRELATED_ONLY`
证据线”，而不是“证明供电/温度无因果”。AMS只能观察慢趋势，仍不能验收ADC模拟轨的亚毫伏
纹波；本阶段也没有主动热控A/B/A，因此继续保留：

- `ADC_ANALOG_RAIL_RIPPLE_QUALIFICATION_PENDING`
- `THERMAL_CAUSALITY_PENDING_ACTIVE_CONTROL`

DAC tile层因RFDC Shutdown未取得安全干预资格，没有正式B条件数据。最终完整分类为
`OUTPUT_LOAD_NOT_CAUSAL_DAC_TILE_INTERVENTION_UNQUALIFIED`。这意味着本阶段排除了“数据输出
负载是主因”，但没有排除DAC tile片内活动、不可见的模拟供电纹波或主动温度变化。

### 产物与最终安全状态

最终证据入口为
`build/receiver/latest/evidence/power_thermal_causality/campaign.json`，汇总表为`summary.csv`，
PCAP清单为`pcap_manifest.sha256`。生成6幅正式图：

- `plots/output_load_a1_b_a2_power_timelines.png`
- `plots/output_load_a1_b_a2_summary.png`
- `plots/dac_tile_intervention_unqualified.png`
- `plots/natural_60min_integration_allan.png`
- `plots/sensor_adc_rf_correlation_heatmap.png`
- `plots/natural_power_ams_ocb1_timeline.png`

续跑于22:12:38 CST正常完成，`operational_ok=true`、`errors=[]`、`finalize_errors=[]`。
最终在线回读为`streaming=false`、`stream_accepting=false`、receiver包率0、DAC mask和八路幅度
全0、freeze mask 0、OCB1 `DYNAMIC`、四个ADC/DAC tile全部运行、生产external-GPSDO
continuous profile恢复且PLL1/PLL2锁定。正式v34产品、RTL、UDP和时钟profile均未改变。
