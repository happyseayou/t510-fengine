# Stage 34c：ADC0/ADC2共享50 Ω参考与OCB1因果调查

> Stage 34c-3已经闭合：9个输出负载run及160/320两条60分钟观察全部取得有效结果，所有
> 数字门禁通过。160/320离栅格点中位积分斜率分别为-0.0215/-0.0175、lag-1为0.834/0.852，
> 长积分问题仍强烈存在；TIME_SPEC相对SPEC_ONLY没有可逆改善，因此输出负载不是主因。
> AMS没有达到注册的温度/内部电压相关证据线。DAC全tile Shutdown实机未能到达驱动可验证
> 的安全停止态，已完整CONFIGURE/MTS恢复并将该层冻结为`INTERVENTION_UNQUALIFIED`，不能
> 写成已排除。最终分类为`OUTPUT_LOAD_NOT_CAUSAL_DAC_TILE_INTERVENTION_UNQUALIFIED`。
> 详见[Stage 34c-3](34c-3_power_thermal_causality.md)。

> Stage 34c-2的v34外部request profile资格在最后一次DAC tile latency一致性门禁失败，
> 未进入科学矩阵。后续已另立
> [Stage 34c-2R](34c-2r_pl_sysref_capture_repair.md)：使用`CORE_VERSION=0x00010035`
> 修复PL 160 MHz输入捕获到ADC/DAC 80 MHz域的SYSREF重捕获和定时可观测性，先重做10 MHz
> 单变量因果，再独立引入5 MHz。10/5 MHz相位眼和最终v35 route/bitstream已经闭合，候选
> bit SHA256为`8934a0c2d7033494b49133d846f954b52a6fa76a54b65c043c6e7be5289728d1`。后续34c-2R
> 科学矩阵已经闭合，但5 MHz只构成弱贡献、没有恢复`1/sqrt(N)`；v35未发布。Stage 34正式
> v34产品和本报告原有长积分失败结论均不改变。

## 当前状态

`IMPLEMENTED / DEPLOYED / LONG_TASK_COMPLETE / OPERATIONAL_PASS /
INCONCLUSIVE_BASELINE_NOT_REPRODUCED / NO_PRODUCT_FORMAT_CHANGE`

34c-0六次正式run均完成并分类为`SHARED_50OHM_REFERENCE_REPRODUCES_CORRELATED_NOISE`，
因此已进入34c-1。原Invocation `b0994db7b1964421b0ee30a30deac419`在完成前两个OCB1
triplet及第三组A1/B后，因房间空调关闭造成共同缓慢升温，第三组A2在PS温度10秒中位跨度
达到2.011 °C时按原2 °C硬门禁停止。用户确认环境原因并授权最小放宽后，旧t03整组归档，
续跑Invocation ID为`85010df4f0ac4351b36b4499d029e696`；重新执行的t03 A1/B/A2及
后续全部run均已完成。最终共完成25个正式run，任务正常退出、错误列表为空，安全状态回读
全部通过。

启动和首轮运行中发现并修复了五个软件合同问题：温度比较曾错误混合不同传感器、TIME曾误用
SPEC-only采样率字段、冷机到满速的正常升温曾被计入正式漂移，以及resident watchdog曾用
“实际回调结束时间”重置1 Hz周期，导致回调抖动在600秒内累计、receiver完整完成时伴随观测
只有559条。周期现以理想时间轴为锚点，迟到时跳过真正遗漏的整周期但不累计亚周期抖动；部署
后25.027秒内取得26个快照，间隔中位数1.001秒、最大1.004秒。随后又发现campaign每秒把
不断增大的完整轨迹重新pretty-print并覆盖写盘，文件增至约58 MB后开始错过快照，最终只有
572条；现改为每秒只flush一行JSONL，正常或可控异常退出时才一次性物化原JSON数组，强杀时
保留JSONL现场。六份失败/受控中断现场保留在固定证据目录的
`operational_failures/attempt_1..6`，当前campaign使用干净根目录；每次收尾均回读stream
停止、DAC/freeze/OCB1 override mask为0且OCB1为`DYNAMIC`。

Stage 34c使用用户已完成的`SSA RF INPUT → 二路功分器 → ADC0/ADC2`接线，先回答去掉
DAC回环后长积分是否恢复；仅在仍复现时，才自动执行OCB1动态—快照锁定—完整恢复的
可逆因果实验。

物理状态固定为SSA开机、TG关闭、preamp关闭、输入衰减20 dB，ADC0对应tile0/block0，
ADC2对应tile1/block0；其余ADC和全部DAC物理断开，DAC数字mask仍为0。该状态只称
`SHARED_50OHM_REFERENCE`，不称八路独立50 Ω。

## 已实现内容

- Board Agent加入OCB1状态、八路原子snapshot override/release、bit-exact回读、事务绑定、
  START/scheduled START授权、重启/CONFIGURE/reset/MTS失效和故障恢复；
- RFDC状态提供每路8个有符号OCB1系数及`k=1..4` DFT；
- resident watchdog从`ams` IIO以5 Hz采样PS/PL/remote温度和已暴露内部电压，每秒保存
  min/mean/max，修复先前温度一直为null的问题；
- 每次正式计时前保持相同全速负载，并以逐传感器连续60秒的前/后10秒中位温差不超过
  0.30 °C确认热稳态，避免把冷机到满载的正常升温误判为600秒内漂移；正式run保留原始
  温度；原2.0 °C run/triplet门禁继续作为显式警告线，用户确认空调关闭的环境事件后只把
  硬停止线最小放宽至2.5 °C。旧t03不能与新温度基线拼接，因此A1/B/A2完整重做；
- receiver monitor支持`lane_mask=0x05`、ADC0/ADC2相关、160 MS/s TIME_SPEC的轻量TIME
  统计和从现有主环导出24流PCAP，不创建第二个packet socket；
- 单一campaign完成预检、六次34c-0、条件TIME_SPEC定位以及必要时18次34c-1；科学假设
  被否定时正常退出，只有运行/安全故障非零退出；
- 产物包括功率时间线、原始/打乱积分曲线、Allan、ACF、跨频相关、TIME RMS、OCB1系数
  与DFT、AMS温度/电压、CSV/JSON、PCAP和SHA256 manifest。最终生成109张PNG且全部通过
  图片完整性校验，其中跨条件总览为
  `plots/stage34c_ocb1_condition_summary.png`。

细节分别见[Stage 34c-0](34c-0_adc02_shared_50ohm_reference.md)与
[Stage 34c-1](34c-1_ocb1_causality.md)。原始扩展调查路线保留在
[Stage 34c总计划](34c_adc_correlated_noise_root_cause_plan.md)，但本轮明确不执行SYSREF切换、
电源纹波探测或LNA实验。

## 验证与结论边界

本地回归已通过Python `unittest` 150项、receiver Rust 47项、Board Agent Rust 7项。没有
修改RTL、PFB、UDP、bitstream或`CORE_VERSION=0x00010034`，不运行Vivado。

Stage 34a原“长积分不合格”保持不变。34c-1最终分类为
`INCONCLUSIVE_BASELINE_NOT_REPRODUCED`：严格A1严重度门禁没有再次达到预注册阈值，因此
不能给出正式OCB1因果定责；但观测方向很清楚，B条件锁定OCB1在160/320 MS/s均使积分斜率
更靠近0、lag-1相关更高，解除后又回到动态基线附近，所以OCB1快照锁定不是修复方案。
共享SSA终端造成的ADC0/ADC2同步变化本身不当作失败，也不外推到八路独立终端或完整天文
输入资格。
