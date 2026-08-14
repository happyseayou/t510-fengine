# Stage 34c-2：时钟参考与SYSREF可逆因果调查

## 当前状态

`SUPERSEDED_BY_34C-2R / SCIENCE_MATRIX_COMPLETE / NO_CAUSAL_CLOCK_FIX / V35_NOT_RELEASED`

本阶段不修改RTL、bitstream、UDP、PFB或`CORE_VERSION=0x00010034`，也不运行Vivado。
正式实验继续使用`SSA RF INPUT → 二路功分器 → ADC0/ADC2`共享50 Ω参考，DAC数字和物理
输出始终关闭。该接法可以比较同一模拟终端下不同LMK条件的可逆变化，但跨ADC共同变化只作
辅助证据，不能外推为八路独立50 Ω或跨板相干资格。

> 后续处理：本阶段暴露的最后一次DAC tile latency分裂不能在旧捕获拓扑下继续解释。
> [Stage 34c-2R](34c-2r_pl_sysref_capture_repair.md)已另立`CORE_VERSION=0x00010035`候选，
> 先修复PL 160 MHz到ADC/DAC 80 MHz的SYSREF重捕获和输入时序，再重新执行本阶段的单变量
> 因果矩阵。v35的10/5 MHz相位眼均32/32点通过并选择3000 ps，最终route WNS/WHS均为
> `+0.010 ns`，隔离候选bit SHA256为
> `8934a0c2d7033494b49133d846f954b52a6fa76a54b65c043c6e7be5289728d1`。构建已闭合，正式
> v35 MTS/profile资格和科学矩阵曾由
> `t510-stage34c2r-v35-science.service`单一长任务提交，有效invocation为
> `4a2b470adc2e4dbaa0a7b457a080c71d`；continuous-10-MHz的10/10 discovery完成后，第一个
> fixed-target因factor-12量化后的ADC target恰落严格minimum边界而被RFDC拒绝。unit已受控
> 停止，fixed完成0/10、科学run为0，并已恢复v34安全状态。target现按factor-12量化floor再
> 增加一个完整量化步，ADC/DAC由728/208修正为744/228；完整Python回归167项通过。r2已以
> unit `t510-stage34c2r-v35-science-r2.service`、invocation
> `630795b5b5764eb89ec018993b0b3ab7`和独立`science_matrix/attempt_r2`证据重新提交。r2完成
> continuous和gated 10 MHz各10/10 discovery、10/10 fixed，证明target修复有效；随后
> request-low负对照因专用schema仍只接受旧无相位profile ID、不能识别冻结phase-15 ID而以
> HTTP 400停止。5 MHz及科学run为0，v34安全状态已恢复。Rust/Python/OpenAPI的外部request
> profile分类随后已统一，完整Python 169项、Cargo 8项通过，并重建ARM64 Agent。r3已以
> `t510-stage34c2r-v35-science-r3.service`、invocation
> `590633090c86456abac4ce1f7a6aaf6c`及独立`attempt_r3`证据提交。r3完成continuous 10 MHz
> 10/10 discovery和10/10 fixed；gated 10 MHz的10次discovery最大ADC 708并生成target 744，
> 前5次fixed通过，但第6次最低可行latency跃迁到780而被RFDC拒绝。负对照、5 MHz及科学run
> 为0，v34安全状态已恢复。现已基于phase-eye及r1/r2/r3全部数据冻结保守profile target：
> continuous为`768/228`，gated 10 MHz为`816/252`，gated 5 MHz为`1176/252`，TCXO为
> `816/252`，策略SHA256为`c39968a...49a3e7`。完整Python 171项、Cargo 8项通过。r4已用
> unit `t510-stage34c2r-v35-science-r4.service`、invocation
> `f42bbdc85f79469e8a81da0f0b3ff4c7`及独立`attempt_r4`证据提交；首个discovery健康完成并
> 自动接续。r4最终完成三个必需profile全部10/10 discovery和10/10 fixed、request-low负对照
> 及16个短筛查，随后因低RF标称122.88 MHz不是精确PFB bin而停止。现已固定使用最近共同
> exact bin `122.890625 MHz`（160/320 bin `-950/-475`），并修复低RF空统计分组。r6 unit
> `t510-stage34c2r-v35-science-r6.service`、invocation
> `c79e2b1ae0a340e2aa74532151d23b79`从经SHA验签的r4资格/筛查断点接续并完成36个600秒正式
> run；r8 finalizer `05909aeca6074d15a5db458f87b630af`补齐3个低频320 MS/s上下文后，于
> 2026-08-12 11:57:59 CST正常完成42-run证据闭合。最终分类为SYSREF policy不具因果性、
> 5 MHz仅为未达绝对门禁的`SYSREF_RATE_CONTRIBUTOR`、TCXO profile不合格；v35未发布并已
> 恢复v34安全状态。本文件的v34失败证据保持原样，最终证据以34c-2R报告为准。

34c原中心为1020 MHz，监测的980、1000、1040、1060、1080 MHz全部是相对中心
`-40、-20、+20、+40、+60 MHz`，恰好落在10 MHz continuous SYSREF栅格上；960 MHz还
是冻结的RFDC坏频点。因此34c只证明这些栅格点存在长期相关，不能证明普通离栅格频率也有
同样问题。34c-2把栅格和离栅格分开，并依次改变“采集期SYSREF是否持续输出”和“外部
GPSDO/板载TCXO参考源”。

## TICS Pro冻结profile

使用TI TICS Pro 1.7.9.1 Windows版，从Stage 32冻结工程实际加载、修改和完整导出，未手工
猜测寄存器。安装程序来自板卡随附厂商介质，SHA256为
`4cd539f3da122a92700b831b278c201c42f68ebb356977d807dba1e365210aaf`。

三个完整136-write profile及运行时按3-byte大端写序列计算的SHA256为：

| profile ID | 参考源 | 采集期SYSREF | 写表SHA256 |
|---|---|---|---|
|`160m_10m_cont_manual_clkin2`|外部GPSDO 10 MHz|continuous|`370e0dfcb1dd9d8d931e62c6f479022d9dd8d361d3e4619465d432db784fb046`|
|`160m_10m_request_manual_clkin2`|外部GPSDO 10 MHz|MTS-only|`6a358918b63aeec870f7c2b7f56a9fc344604bcc94e9763f3a27f38bce94c3d4`|
|`160m_10m_request_manual_clkin0`|板载TCXO 10 MHz|MTS-only|`ecc2e2c803056a5650bb5347e51bca7de887a96bd99e5e157bc41432d4155496`|

TICS原始产物冻结在：

- `reports/arch/lmk04828_stage34c2_160_10m_request_manual_clkin2.tcs`，SHA256
  `64eaaff59632a355aa1341e9fca59e1c4f967f59bc55c66646364dcf83c60a66`；
- 对应寄存器导出SHA256
  `fd80d79cb806399304f6a176d20e3b3290caa26cf50debed2876803e87078fdd`；
- `reports/arch/lmk04828_stage34c2_160_10m_request_manual_clkin0.tcs`，SHA256
  `610869287a4dae72ef086af3ed35fa6b3e95749d4795dfbb123d664318ec1bab`；
- 对应寄存器导出SHA256
  `3a80dc3f2aa9f51bf23aa94da3bc3fa774e6306a9b62cf9e52a837c8a2ec044d`。

外部request相对production最终只改变3个文档可解释的SYSREF字段：
`0x139:03→02`（continuous→pulser）、`0x140:03→00`（MTS期间启用SYSREF digital delay和
pulser）、`0x16a:20→60`（启用外部request）。TICS Pro的“SYSREF Request”快捷
按钮会附带选择SPI Pulser（`0x143=0x53`），这不符合LMK04828数据手册外部SYSREF Request
表格，因此在TICS界面显式改回“SYNC Pin Disabled”（`SYNC_MODE=0`、`0x143=0x50`）后重新
完整导出；该值与production相同。快捷按钮还把七个SDCLK local delay从bypass改为2 cycles，
实机隔离证明这会使RFDC reset停在state 6，因此按审计要求在TICS中恢复production的全部
输出mux、delay、格式和频率。外部profile的CLKin0 enable也保持关闭。TCXO profile在此基础
上只增加`0x146=0x28`的CLKin0 enable、`0x147=0x0f`的manual CLKin0选择和
`0x154=0x01`的PLL1输入R分频。TICS显示若只选择CLKin0
而不设R=1，PLL1 PFD只有0.08 MHz并失锁；设为R=1后恢复10 MHz并锁定。三个profile的
VCO0 2400 MHz、VCXO 122.88 MHz、RFDC/PL 160 MHz输出和10 MHz SYSREF分频保持不变。

## 控制面与失效语义

Board Agent新增：

- `GET /api/v2/clock/diagnostic`；
- `POST /api/v2/clock/diagnostic/prepare`；
- `POST /api/v2/clock/diagnostic/restore`。

`prepare`只在science停流、receiver明确不接收、scheduled sync未准备/arm、八路DAC全零、
freeze mask为0且OCB1为`DYNAMIC`时执行。它重新写完整LMK表、等待PLL1/PLL2锁定、reset全部
RFDC tile、在MTS期间控制SYSREF、完成ADC/DAC MTS和NCO/QMC更新，并逐项回读profile
SHA、GPIO、PLL和MTS结果。MTS-only profile返回前必须满足SYSREF_REQ=0且物理输出预期为
off。成功后签发一次性`clock_transaction_id`，START和scheduled START必须携带匹配ID。

实机还证明“overlay已运行后再完整重写LMK”会让RFDC reset停在state 6；正确原子顺序固定为：
先STOP并用`XRFdc_Shutdown`停止旧tile，在旧tile停止状态完整写LMK并等双锁，request模式先
拉高SYSREF，再重新加载同一SHA的v34 overlay，reset八个tile并执行MTS，最后关闭SYSREF。
这只是重载同一产品bitstream以复位RFDC电源状态机，不修改RTL或bitstream身份。

STOP、CONFIGURE、RFDC reset、service重启、LMK/profile改变都会使ID失效并进入
`RESTORE_REQUIRED`；此状态不能再次prepare或START，必须先完整恢复production profile。
任一准备/恢复失败都执行STOP、DAC静音、unfreeze、OCB1 release和production profile
重配；恢复也失败时锁存故障并禁止START。

资格阶段允许仅诊断使用的MTS discovery/fixed目标。外部request profile还执行带15秒超时
的真实负对照：临时强制SYSREF_REQ保持低，MTS必须返回失败或超时；随后reset全部tile、
重新拉高request完成正常MTS，再关闭SYSREF。该证据用于排除“软件只改了状态名称，GPIO并未
控制RFDC所见SYSREF”的假阳性。

## 实验矩阵

profile资格先对两个新profile各执行10次discovery和10次fixed-target。诊断target取各自
四tile实测最大值加余量：ADC `+20`、DAC `+16`，不修改生产catalog。TCXO资格失败只产生
`TCXO_PROFILE_UNQUALIFIED`并跳过参考源层；外部request失败则不能继续实验。

### 2026-08-10首次正式提交结果

完整自动队列已作为用户级systemd长任务
`t510-stage34c2-clock-sysref-causality.service`一次性提交，启动时间为
`2026-08-10 14:57:41 CST`，invocation ID为
`465903dfb2304b69b954d88d63c87858`。任务按预注册顺序完成外部request profile的
10/10 discovery和前9次fixed-target；第10次fixed-target中ADC通过，但DAC四tile实测
latency分裂为`[116,116,108,108]`。因为新profile资格要求四tile latency一致，任务于
`15:17:06 CST`以`STAGE34C2_OPERATIONAL_FAIL`停止，未执行SYSREF负对照、TCXO正式资格、
120秒筛查或600秒科学矩阵，正式run数为0。不能把这次结果解释为SYSREF或参考源的科学
因果结论，也不允许自动重试或放宽门禁。

失败后的安全收尾实机回读通过：`streaming=false`、`stream_accepting=false`、DAC mask和
八路幅度全零、freeze mask为0、OCB1 override mask为0且状态为`DYNAMIC`；LMK恢复
`160m_10m_cont_manual_clkin2`生产profile，时钟事务状态为`PRODUCTION`，reference watchdog
双PLL锁定且healthy。receiver停止收包，drop基线未增加。

本次campaign JSON SHA256为
`cf0c36e763de38d3d2ca062028a981a1cb7836fbf92abeac1a4384e6aa8534a1`，板端summary SHA256为
`7b60e8c891e143c3373fec341e515914ea0b2cc0844550f97cac315f5e4b102a`。首版脚本在异常路径只把
资格摘要写进campaign，19个成功轮次的详细对象没有逐轮checkpoint；这不改变MTS失败值和
停止判定，但属于证据完整性缺陷。脚本随后改为每次discovery/fixed结果先原子落盘再判门禁，
并新增“最后一次失败也必须保留”的单元测试。该修复只影响后续提交的证据可靠性，没有自动
重启本次实验。

中心1020 MHz正式同时监测18点：

- 固定坏点960 MHz，仅观察；
- 10 MHz栅格：970、980、990、1000、1010、1030、1040、1050、1060、1070、1080 MHz；
- 离栅格：966.875、988.75、1007.5、1032.5、1051.25、1073.125 MHz。

离栅格点在320 MS/s精确为bin `±160/±400/±680`，在160 MS/s精确为
`±320/±800/±1360`。receiver从现有PACKET_MMAP主环统计ADC0/ADC2，不创建第二个packet
socket。

自动队列依次执行：

1. 12个120秒短筛查：两层各按`A1 → B → A2`，160/320各一次；
2. center=160 MHz的三个profile×两种速率×60秒低RF观察，并保存完整PFB PCAP；
3. SYSREF层18个600秒run：`EXT_CONT → EXT_GATED → EXT_CONT_RESTORED`；
4. 参考源层18个600秒run：`EXT_GATED → TCXO_GATED → EXT_GATED_RESTORED`。

每层有3次fresh triplet，速率顺序为`160→320、320→160、160→320`。每个正式run前在
相同全速负载下等待连续60秒热稳定；2.0 °C为警告、2.5 °C为硬停止，环境变化时不能拼接
triplet。每个run首尾都从receiver主环导出16端口×32完整包PCAP并生成SHA256。

正式离栅格绝对门禁和可逆因果门禁完全按本阶段计划实现。科学假设成立或被否定均以任务
成功退出；只有drop/gap、sample0跳变、backpressure、FIR饱和、XFFT overflow、clip、PLL
失锁、温度超限或安全恢复失败才是非零运行故障。

## 证据与结论边界

固定证据目录为：

- `build/board/latest/evidence/clock_sysref_causality`；
- `build/receiver/latest/evidence/clock_sysref_causality`。

campaign生成逐run原始/打乱积分曲线数据、Allan输入序列、lag与跨频矩阵、A1/B/A2总览、
低RF全带图、LMK和MTS证据、AMS温度/电压轨迹、CSV、JSON、PCAP及SHA256 manifest。

本阶段最多定责SYSREF policy或参考源对ADC0/ADC2时间相关性的可逆影响。即使MTS-only通过，
也不直接升级生产profile；必须另做五模式全速、MTS 40/40、长soak和同步恢复资格。若两层
均无因果效果，下一步进入34c-3电源与热稳定调查。Stage 34a的长积分不合格状态在可逆修复
得到完整资格前保持不变。

参考：[TI LMK04828数据手册](https://www.ti.com/lit/ds/symlink/lmk04828.pdf)、
[TI TICS Pro](https://www.ti.com/tool/TICSPRO-SW)、
[AMD同步步骤](https://docs.amd.com/r/en-US/pg269-rf-data-converter/Synchronization-Steps)、
[AMD MTS主流程](https://docs.amd.com/r/en-US/pg269-rf-data-converter/Main-Sequence-to-Perform-Synchronization-for-AC-or-DC-Coupled-Single-or-Multiple-Device)。
