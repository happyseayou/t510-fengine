# Stage 34e：ADC 时间交织固定杂散的动态前馈补偿

## 当前状态

`V36_ROUTED_CANDIDATE_EXPORTED / OPEN_INPUT_DIAGNOSTIC_RUNNING / 50OHM_QUALIFICATION_PENDING`

Stage 34e 是隔离的工程候选，不是当前产品发布。当前正式入口仍是 v34；候选身份固定为：

- `CORE_VERSION=0x00010036`
- bitstream ID `fengine-0x00010036`
- 固定 4096 通道、8-tap PFB、IQ16、FFT shift `0x556`
- PFB profile `0x34a80001`
- 生产时钟仍为 external-GPSDO continuous SYSREF

本阶段保留 v35 已验证的 PL SYSREF 捕获修复，但不把 v35 的 MTS-only/5 MHz 诊断 profile
升级为生产配置。v36 在八个独立 50 Ω 负载资格闭合前不得写入正式 catalog，也不得替换
v34 latest 产品。

## 为什么是前馈而不是 notch

480、960、1440 MHz 是 3.84 GS/s RF-ADC 八相时间交织结构的 `Fs/8、Fs/4、3Fs/8` 固定项，
分别对应 OCB1 八点序列 DFT 的 `k=1、2、3`。notch 会把相同 RF 上的真实天文信号一起挖掉；
锁定 OCB1 又已经在 Stage 34c 中证明会恶化长积分。v36 因此只减去停流校准得到的一个复矢量，
OCB1本身继续动态工作且只读。换句话说，补偿器预测“ADC内部固定误差现在应当贡献多少”，不从
运行中的科学数据寻找峰，也不会把后来到达的同频天空信号当成误差继续追掉。

## RTL结构

新模块 `adc_interleave_spur_corrector` 位于 RFDC adapter 之后、160/320 science rate selector
之前。80 MHz 的每拍数据包含四个连续时刻、八路复 IQ16；模块每拍完整计算，不跨拍复用乘法器：

- 一个公共 48-bit 相位累加器，以原始 320 MS/s sample0 时间轴运行；
- 1024 点 Q1.17 正弦 ROM，并行形成四个子时刻的正余弦；
- 八路 Q8.16 复系数，每路每子时刻四个实乘法，共 128 个明确要求映射 DSP 的乘法器；
- 扩展位宽复数扣除、对称舍入及 IQ16 饱和；
- bypass 与补偿路径具有相同两级时延，bypass 数据 bit-exact；
- `tuser/tlast/sample0/raw_sample0`与数据一起延迟，UDP时间含义不变；
- active/shadow 系数银行只在 raw `sample0 mod 8192=0` 提交；
- sample0不连续、CRC错误、未同步相位或超过1秒没有tracker心跳，活动补偿立即失效并锁存故障。

清流只丢弃流水线 valid，不重置绝对 sample0 连续性或 NCO 时间轴。这避免 STOP/START 后产生一个
与RFDC采样时间无关的新相位原点。

控制寄存器位于 `0xAE00–0xAEFF`，包含control/status、preview raw/corrected选择、spur ID、48-bit
phase step、16个Q8.16 shadow分量、严格顺序load/CRC、profile/model/generation、最后提交sample0和
饱和/不连续/CRC/tracker-stale/commit计数。16个分量缺失、重复或乱序均不能commit。

## 模型、校准和运行合同

每板、每ADC、每物理固定频点独立保存：

`C(t) = C0 + M · (D(t) - D0)`

其中 `C` 与 OCB1 DFT `D` 都按实部/虚部展开，`M` 是实数 2×2 矩阵，因此允许实虚交叉映射。
停流校准抓64份1024点raw preview，以绝对sample0和与RTL相同的48-bit/LUT相位模型做复相关；
写入后最多做两次 corrected-preview 残差细化。模型、preview、配置、OCB1基准和系数均冻结SHA/CRC。

Board Agent增加：

- `GET /api/v2/adc/spur-correction`
- `POST /api/v2/adc/spur-correction/calibrate`
- `GET /api/v2/adc/spur-correction/calibrate/status`
- `GET /api/v2/adc/spur-correction/calibrate/result`
- `POST /api/v2/adc/spur-correction/tracker-mode`
- `POST /api/v2/adc/spur-correction/disable`

`tracker-mode`只服务开放输入工程 A/B：`static_c0`保持校准时C0但仍刷新心跳，`dynamic`使用5 Hz
只读OCB1更新。它不提供 OCB1 override。配置、MTS、NCO、LMK/overlay reload、服务重启或模型变化
使凭证失效；STOP本身不使凭证失效。温差2 °C告警，5 °C失效并安全STOP。

START合同为：不含固定项时正常bypass；含固定项但不带ID时允许启动并置UDP bit7
`ADC_INTERLEAVE_SPUR_UNCORRECTED`；匹配ID时置bit6
`ADC_INTERLEAVE_SPUR_CORRECTION_ACTIVE`；显式提供错误ID则拒绝。receiver从TIME和SPEC两类包都
汇总两个flag，Web在未校正受影响窗口显示红色科学警告。UDP包长、字段和通道顺序均未改变。

## 已完成验证

软件及XSim回归已经覆盖：

- 正/负48-bit phase step、四子样顺序、sample0相位连续；
- 八路复扣除、对称舍入、故意饱和、bit-exact bypass、backpressure；
- shadow严格顺序CRC、原子边界commit、tracker超时和错误锁存；
- 固定误差与额外真实同频信号并存时，只减去预校准矢量；
- OCB1 DFT、2×2拟合、LUT相位复相关、模型SHA及系数CRC；
- 凭证绑定/失效、无ID警告、错误ID拒绝、安全STOP；
- receiver v34兼容、v36 bit6/bit7和TIME_ONLY Web状态；
- 静态C0与动态OCB1工程诊断模式。

当前最终提交前回归记录：Python 219项、Board Agent 8项、receiver 50项和XSim 19/19均通过；
最后一次清流边界修复后，补偿器定向仿真和完整顶层冒烟仿真也已重新通过。Board Agent已用项目
冻结的`cargo zigbuild`流程生成ARM64静态候选产物。已连接Vivado GUI完成
`synth → impl/phys_opt/route → write_bitstream → current-project export`：

- bitstream SHA256：`a16bcd192ebcf01684ced0f80a55aca8cd7b7665f70adf100492038309e5e83e`；
- routed WNS `+0.061 ns`、WHS `+0.009 ns`，setup/hold失败端点均为0；
- 325,199条可布线网络全部完成，route error为0；
- 全设计DSP48E2为888，补偿器层级恰为128个DSP48E2；
- 全设计LUT 142,938、FF 187,153、RAMB36 553、RAMB18 194；
- 未新增阻断发布的DRC/methodology问题；保留的critical warning为既有CMAC Evaluation License。

这些结果只闭合v36候选的构建和布线门禁，不替代开放输入及50 Ω板级资格。

## 开放输入诊断队列

固定runner为 `scripts/t510_adc_interleave_spur_diagnostic.py`，证据只写入：

- `build/board/latest/evidence/adc_interleave_spur_correction`
- `build/receiver/latest/evidence/adc_interleave_spur_correction`

六个窗口使用 center=`spur−60 MHz`，令固定项在160/320模式分别精确落 `+1536/+768` bin。
每窗依次执行raw、static C0、dynamic各60秒；从receiver主PACKET_MMAP环统计固定bin及左右8个
局部背景bin，始末导出16流×32包PCAP并校验实际QSFP packet flag、4096/8-tap和连续性。随后
960 MHz dynamic运行60分钟，再执行五个合法模式各60秒、160 TIME_SPEC与320 SPEC_ONLY各
10分钟及320 SPEC_ONLY 60分钟soak。任一失败不重试，立即STOP、DAC静音并保留现场。

开放输入必须看到八路改善方向一致才继续；结果统一标记 `OPEN_INPUT_DIAGNOSTIC`。它既不能建立
正式模型，也不能发布v36。

候选队列使用用户级systemd单元`t510-stage34e-v36-open-input.service`。启动期间发现并修复了三类
受门禁正确拦截的问题：候选/生产bitstream切换顺序、Agent短暂硬件互斥，以及ADC mixer readback
的数字下变频负号到物理RF轴的换算；失败现场完整保存在`attempts/attempt_001..004`。receiver已
原位升级为同时兼容v34/v36的版本，远端二进制SHA256为
`1a27931a6bf341cc958a510cd271dd4981539bac20f6a2b3b27e046d7527f493`。

2026-08-14提交的当前队列invocation ID为`09b098224a0e4f27b9b5a2b7685dbeb9`。首个
480 MHz/160 MS/s raw窗口已健康进入60秒monitor：v36、center 420 MHz、SPEC_ONLY，采集机
实测约41.80 Gbit/s和624.8 kpacket/s；QSFP UDP flag为`0x0085`，即bit7未校正警告有效、bit6
未置。FPGA、NIC、ring、application drop及seq/frame/sample0 gap均为0，DAC mask为0，首份
16端口PCAP已从receiver主PACKET_MMAP环导出。按长任务规则，确认首窗运行后不继续驻留轮询。

## 尚未完成的硬门禁

1. 当前八路开放输入六窗、60分钟tracker和全速矩阵；
2. 八个独立50 Ω负载到货后的144组合、三条60分钟跟踪、SSA同频信号保持、积分A/B、MTS 40/40、
   20次循环和全速soak。

正式目标仍是每个60秒平均固定项不高于局部噪底+6 dB，raw-preview固定矢量不差于-90 dBFS；
SSA同频真实信号补偿前后幅度误差不超过2%、相位误差不超过2°。只有上述50 Ω资格全部通过，
Stage 33a/34a才能更新为“由动态OCB1状态驱动的前馈补偿获得工程修复”。
