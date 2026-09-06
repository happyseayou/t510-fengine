# Stage 36：数字精度调整与 Stage 35 最终产品复评

日期：2026-09-05–06（CST）。状态：`SCIENTIFIC_EVALUATION_COMPLETE / 8036_CLIENT_REVIEW_REQUIRED`。

## 已确认的执行合同

- TIME_ONLY 与 F-engine 的 I、Q 各分量标准差均以约 10 count 为目标，验收范围 8–12。
  F-engine 检查每路全频标准差中位数及 global_bin 3134/3182/3328，完整保留逐 bin 带通差异。
- 只采新档，与 Stage 35 历史数据比较，不增加同 bitstream 双档正式观测。
- 候选为 RFDC QMC `16383/8192 = 1.9998779296875`，以及 PFB 累加结果到 IQ16
  的舍入右移从 17 改为 16。系数保持 Q1.17，FFT 调度仍为 `0x0556`。
- 新生产 core 计划使用 `0x00010036`。当前 QMC 资格诊断仍运行在 v34；其数据不等于
  Stage 36 生产科学结果，必须带独立增益身份。
- QMC 诊断包括 readback、30 s 全速 TIME、50 ms 连续原始见证、低位码占用、
  RFDC 错误、独立数值/哈希验证及有效原配置恢复。失败即停止后续阶段。
- 读数范围、数字精度证据、数据完整性、科学结论、页面验收分别记录，不预先承诺 ADC ENOB、
  Allan 或仪器伪相关改善。

## 阶段状态

| 阶段 | 内容 | 状态 |
|---|---|---|
| 36.0 | Stage 35 页面、数据及工作区身份冻结 | COMPLETE |
| 36.1 | v34 上 QMC 新增益资格与恢复 | PASS / RESTORED |
| 36.2 | PFB 定点 RTL、软件尺度身份、真实 XFFT / 位精确模型 | PASS：V2 位精确合同与独立误差验证 |
| 36.3 | GUI MCP 完整综合→实现→bitstream 链 | R2 PASS，已导出：WNS +0.050668 ns |
| 36.4 | 新固件导出、MTS、五个合法模式全速门禁 | COMPLETE：板载与外部参考资格均 PASS |
| 36.5 | 新档完整科学采集与独立复算 | COMPLETE：13/13 阶段、总 manifest 与独立复算 PASS |
| 36.6 | 8036 报告与浏览器验收 | TECHNICAL PASS：服务在线，等待用户实际页面复核 |

## 基线与资格任务身份

基线冻结 ID：`stage36-20260905T061103Z`。

- 本机：`build/stage36/stage36-20260905T061103Z/`。保存 415 个当前工作区文件的
  归档、逐文件 SHA-256、git HEAD/状态/工作差异，以及线上首页、JavaScript 和 meta。
  冻结包含已有未提交的 Stage 35 成果，没有重置或丢弃它们。
- GB10：`/var/lib/t510/stage36/stage36-20260905T061103Z/baseline/`。保存线上应用
  归档、服务配置、报告配置、原始索引、长 TIME 索引、A/B/C 和复相关 manifest、
  已完成原任务状态、接收器二进制 SHA-256；大体积原始数据保留原处。
- QMC 首次任务：`stage36-20260905T061103Z-qmc-r1` 在 SSH 主机身份预检失败，未写 QMC、
  未启动采流。使用本机已信任的板端 ED25519 主机公钥补齐独立 pinned known-hosts 文件，
  通过实验室默认凭据的 SSH askpass 登录；不关闭主机密钥验证，也不复制私钥。
- 当前任务：`stage36-20260905T061103Z-qmc-r2`。接收器沿用已有 writer 存储根，
  新数据目录具有 Stage 36 唯一前缀；原有 Stage 35 观测未覆盖。
- 板端恢复日志：`/var/lib/t510/stage36/stage36-20260905T061103Z/qmc-r2.json`。
- QMC 诊断代码：`scripts/stage-36/t510_stage36_qmc_probe.py`、`scripts/stage-36/t510_stage36_qmc_gate.py`。

## 后续完整队列合同

36.1 通过后，先完成浮点/定点参考、边界饱和、背压与 sample0 对齐验证，以及真实 XFFT IP
数值仿真。现有 `T510_SIM_FFT_MODEL` 仅作接口/时序仿真，不作为 FFT 数值精度证据。

Vivado 只能使用已 attach 的 GUI MCP；一次性武装完整综合、实现、bitstream 自动接续。
确认健康启动即交还控制权。用户通知完成或要求继续后，检查 routed 时序、route status、
DRC/methodology、bitstream 与报告，才能导出、烧录和重做新 bitstream MTS 资格。

正式新档队列包括：TIME_ONLY 900 s（10 ms 原生及 100 ms/1 s 派生），A/B/C 各 900 s
自功率及每次前后 30 s TIME，连续 4096 帧全频原始谱，全部 28 对×4096 通道 900 s
复可见度（100 ms 原生及 1 s 派生）及前后 TIME 对照。队列自动接续独立复算、验签、报告
和浏览器门禁；任一阶段失败停止并保留现场。

新档产品全部重采，不将 Stage 35 文件充当 Stage 36 正式数据。报告复用当前最终页面的
单 ADC / ADC 对入口、原始与长时曲线、Allan、公式点击实算、多选叠加和相位可靠性标记。
同时提供统一尺度及原始 count 比较；I/Q 增益、功率/复可见度增益和 Allan 方差增益分别
正确换算。默认发布 8036，保留 8035；不纳入温度/天文源定标、天空成像和多板同步。

## 已完成的软件验证

QMC 诊断 6 项单元测试 PASS：精确可表示增益、禁用 QMC 恢复事件归一、拒绝不可安全恢复的
原状态、停止/版本/DAC 门控、每 tile 两路参数先写入再触发更新，以及 gain/mixer/DSA/
decimation/通道映射变化的回读拒绝。两个诊断脚本语法检查及
`git diff --check` 通过。

恢复说明：高采样率 ADC 驱动不接受 QMC power-on 默认 EventSource=0 的 setter；恢复禁用
QMC 时通过合法 TILE 事件重新落实原 gain/phase/offset，并明确记录 EventSource=2。
这恢复原有效信号处理设置，不声称事件源寄存器与 power-on 值逐位一致。

## QMC 资格结果

`qmc-r2` 已完成，候选门禁 PASS，清理错误为空，板端恢复为原有效禁用 QMC 设置。
30 s TIME 与 50 ms 原始见证独立复核通过；八路 I/Q 标准差为 8.083–9.273 count，
奇数码比例约 0.5，全部削顶、正式采集丢包/序号错误和 RFDC 错误门禁为零。
50 ms 原始见证共 62,500 包、每路 16,000,000 点，SHA-256：
`f5ab166fc7a7c5c87c9cecb79da1f87371afd9ee5818de7336bcae90f73adcfb`。
本机独立数值证据：`build/stage36/stage36-20260905T061103Z/qmc-evidence/candidate_numeric_gate.json`。

同一份 QMC 后实测输入的 PFB 浮点/定点模型：旧量化输入折算 MSE
0.0799443，新量化 MSE 0.0204387，比值 0.255662。此时真实 XFFT 尚未通过，
该结果只说明 FIR 量化模型，不是完整数字链路或 ADC ENOB 证据。

## 软件与回归门禁实施

- `python/t510_scaling.py` 统一版本绑定的尺度、八路真实 QMC 回读校验、receiver 字符串
  metadata、以及 count/功率/复可见度/Allan 的历史尺度换算。
- 新 core 在 MTS 配置后设置并回读 QMC，立即 START 和 ScheduledSync ARM 前再次核验。
  状态接口返回 `digital_scaling`，MTS 每周期证据保存相同字段；finalizer 拒绝缺失身份。
- 控制器默认版本、Rust catalog 验证、发布/安装/板上门禁与导出身份已转为 v36；
  工作区 `config.example.json` 当前故意未资格（SHA 全零、MTS 目标 -1，无旧 campaign）。
  只有新 bitstream 的新 40/40 证据可完成此 catalog，尚未发布板端软件。
- RTL 首轮 AXI bridge 测试遗留 v34 断言失败，而旧脚本在 GUI 缺失 `simulate.log` 时
  误报完成。已保存 `rtl-regression-r1-session.log`，修正两个断言，并新增必须实际到达
  `TB_PASS` 才生成的完成文件；缺文件或失败立即退出，不允许单靠 `run all` 返回认定通过。
  PFB 首轮已经实际打印 PASS，复用其边界/跨帧/背压/sample0 证据，桥测试单独重跑。

普通 RTL 回归已闭合：首轮 16 个测试实际 PASS，修正后的 AXI bridge 与统一完成标记的
CMAC pause 独立重跑 PASS，共 17 个测试。汇总：`rtl-regression-verification.json`。
真实 XFFT 初次启动因 Vivado 2022.2 仍从当前 sim_1 取宏和 plusargs 而失败，未产生
数值输出；已显式切换独立 current simset，并在测试中拒绝简化模型宏，重新执行。
这类仿真启动失败不记为 FFT 数值门禁通过。

MTS 资格脚本新增显式参考源，Stage 36 默认 `tcxo_10mhz` +
`160m_10m_request_manual_clkin0`，与本次冻结页面一致；MTS 完成后检查 request SYSREF
已关闭。保留显式 external 参考分支，禁止隐式切到旧默认 external/continuous 配置。

真实 XFFT 测试台还修正了协议假设：PG109（2022-05-04，Controlling the FFT Core）
允许 Realtime IP 在缓冲首符号后插入 slave waitstate，禁止的是上游不按请求提供数据。
测试台现在始终保持 TVALID/data，只有握手成功才前进，并检查 `event_data_in_channel_halt`；
不能把 TREADY 拉低本身当成数值门禁失败。先前失败日志分别保存在
`real-xfft-r2-startup-ready-failure.log` 和 `real-xfft-r3-slave-wait-failure.log`。
依据：[AMD PG109 2022](https://www.amd.com/content/dam/xilinx/support/documents/ip_documentation/xfft/v9_1/pg109-xfft.pdf)。

## 用户授权的仿真优化与门禁暂停

用户授权优化后停止原 XSim（只终止 PID 2887725，保留原 Vivado GUI），未重启或另开
Vivado。原仿真不是完整 PASS：完整保留 9 帧及第 10 帧部分输出，共 38,238 个 bin、
305,904 个复数样本。停止原因保存在 `simulation-optimization-stop.json`，原输出另存
`fft-fixture/real_xfft_prefix_preserved.txt`，GUI 日志另存 `real-xfft-r4-user-stopped.log`。

新增 `scripts/stage-36/t510_stage36_vendor_fft.py`，使用本机 Vivado 2022.2 自带 XFFT v9.1
位精确 C 模型，通过 ctypes 调用；供应商库仅放在 build 证据目录，不纳入源码。
按生成的生产 IP VHDL 核对参数：4096 点、pipelined、固定长度、IQ16、twiddle16、
scaled、非 BFP、convergent rounding；前向 FFT，缩放各级 `[2,1,1,1,1,1]`。
全部 35 帧 × 8 路模型运行加逐点比对约 5.08 s，溢出为零；与保留的真实 IP 输出
逐位一致，零差异。损坏一个 RTL 输出 bit 的负例被拒绝，不能仅靠浮点近似判定一致。
模型不替代 RTL 协议、背压或流水线测试；已有 RTL 回归和真实 IP 前缀单独保留。

独立 NumPy 检查使用 `--backend vendor`，结果明确写入 `vendor_xfft_verification.json`，
不冒充 35 帧完整 RTL 通过。原 4 count 最大复数误差门禁保持不变，结果 **FAIL**：
1,146,880 个复数单元中仅 1 个超限，位于旧 PFB 量化输入的 frame 15 / bin 1892 /
lane 0。模型输出 `(-4, 1)`，浮点参考 `(0.0086481, 0.5839493)`，复数误差
4.0301809 count，最大分量误差 4.0086481。新 PFB 输入组最大复数误差 3.9245126。
这定位到旧尺度用例，但还不能据此把原门禁改判 PASS；需要审查 FFT 误差预算的依据。

同尺度完整 PFB+FFT 复数 MSE：旧 1.2339128，新 0.3079490，比值 0.2495711。
这属于该实测输入上的数字量化误差改善，不是 ADC ENOB 或 Allan 改善证明。
模型仅 16 帧噪声，新尺度每路 I/Q 全频标准差中位数约 7.23–8.38 count；短样本统计
不是正式板端 8–12 count 验收，后续必须扩大统计并保留未达标的可能性。

证据在 `build/stage36/stage36-20260905T061103Z/fft-fixture/`：
`vendor_xfft_crosscheck.json`、`vendor_xfft_verification.json`、
`vendor_xfft_failure_detail.json`，另有源文件哈希和负例测试结果。
独立复算副本在 GB10 `/var/lib/t510/stage36/stage36-20260905T061103Z/optimized-fft/`。
原 35 帧自动等待脚本没有提交；门禁失败后未提交构建，GUI 回读 synth_1 / impl_1
均为 Not started，当前 simset 已恢复 sim_1。未改板端配置，未进入长采集。

## FFT 门禁修复（V2，2026-09-05）

根因是验证器使用了没有推导依据的固定 `max(abs(fixed-float)) <= 4 count`。
该数值由本轮实现加入，并非用户批准计划中的要求，也不是 AMD 对本参数组合的保证。
PG109 2022 第 33 页说明 butterfly 舍入选项不覆盖所有内部字长缩减位置；
第 70 页规定 C 模型按帧位精确、但不模拟延迟/接口；第 77 页说明 streaming 架构
溢出时不保证模型和硬件数据一致。因此 V2 正确性合同要求零溢出及位精确一致，
浮点距离单独量化并保留，不把观察到的极值改为新的阈值。
依据：[AMD PG109，Rounding Implementation / C Model](https://www.amd.com/content/dam/xilinx/support/documents/ip_documentation/xfft/v9_1/pg109-xfft.pdf)。

- 新 `t510_stage36_fft_contract.py` 核查生成的生产 IP 全部九个数值参数、FFT 调度、
  系数 CRC、35 帧输入/参考/模型输出/真实 RTL 前缀 SHA-256、连续帧/bin 和输出长度。
  独立检查阶段重新逐位比较 RTL 前缀，不只信任上一步的 PASS 字段。
- 模型重跑仍得到完全相同输出 SHA-256，35 帧无溢出；真实前缀 305,904 个复数值零差异。
  未改动 PFB/FFT RTL 来迎合门限，23 个 RTL 源文件与已验证快照完全一致。
- 分析器核对 reference.npz 中的 IQ16 输入与 input.mem 一致，重新计算浮点 FFT，
  拒绝非有限参考。完整输出要求与模型逐位一致；新尺度的同尺度 MSE 必须在总量及
  八路 I/Q 各分量分别改善。原最大误差 4.0301809 和唯一一次旧 4 count 超限继续输出。
- 总复数 MSE 由 1.2339128 降至 0.3079490（比值 0.2495711）；八路 I/Q 各分量
  从约 0.614–0.621 降至 0.153–0.156。该结论仅限本见证输入的数字量化误差。
- 9 项实测夹具回归通过：原 4.030 count 用例保留且按新合同通过、单 bit 错误拒绝、
  输入身份变化拒绝、模型溢出拒绝、模型/生产 IP 舍入配置变化拒绝、RTL 见证不足拒绝、
  NaN 参考拒绝、同尺度误差恶化拒绝。自动接续/失败停止相关 5 项回归也通过。
- V1 失败结果保持原文件；V2 证据另存本机 `fft-gate-v2/` 和 GB10 同名目录。
  构建前汇总为 `gate-v2-prebuild-verification.json`，构建源码哈希为
  `gate-v2-prebuild-source-sha256.json`。这不是正式板端读数、Allan 或科学页面验收。

2026-09-05 16:09 CST：通过原 attach GUI 一次性提交完整构建链。启动准备耗时约
102 s，首次 MCP 等待超时后未重发命令；新只读连接确认 `armed=1`、8 个 IP
综合任务运行、顶层 synth_1 排队、phys_opt 已启用。综合成功后同一 GUI 自动启动
impl_1 到 write_bitstream，失败停止。健康启动确认后停止轮询并交还控制权；
尚未检查最终时序/报告、导出或发布。提交状态：`gate-v2-build-submission.json`。

## 时序修复 R2（2026-09-05，用户授权重新提交）

R1 原任务最终为 `write_bitstream Complete!`，但时序不合格：WNS -0.195381 ns，
TNS -27.846113 ns，603 个 setup 失败端点；WHS 0.009 ns，hold / pulse-width
失败数均为零，299,423 个可布线网络全部布通，routing errors 为零。
R1 bitstream 未导出或发布。旧 routed DCP、bitstream、报告、SHA-256、原运行配置和
全部 603 条负余量路径保存在 `timing-r1-failed/`，随后才能重置原 run。

路径分组：PFB 帧缓存 220、SPEC 输出 CDC FIFO 98、频谱 UDP 打包器 247、
PFB 其他 25、TIME 打包器 3、SPEC 输入 CDC FIFO 10。最差路径只有 0–4 级逻辑，
主要延迟来自 BRAM 控制/地址线布线（最差若干路径约 92%–97%）。
原配置为 Performance_Explore，place / phys_opt / route 均为 Explore，
post-route phys_opt 关闭，write_bitstream 前无时序门禁。

据此先修实现配置，而不改变数值链路：

- `t510_stage36_timing_closure.tcl`：WLDrivenBlockPlacement 布局、
  AggressiveFanoutOpt 布局后优化、AggressiveExplore 布线及 `-tns_cleanup`，
  启用 AggressiveExplore 布线后物理优化。全部选项已由现有 Vivado 2022.2 GUI 回读。
- `t510_stage36_pre_bitstream_gate.tcl`：在 write_bitstream 前重新生成最终时序与
  route status 报告；setup / hold / pulse-width 失败数必须全零，精确 max/min
  slack 非负，routing errors 为零。失败通过 Tcl error 停止该 run，保留现场报告。
- `t510_timing_gate_common.tcl`：严格解析完整设计摘要，缺失/非数值报告失败；
  endpoint 计数和精确 slack 防止负余量显示成 -0.000 时误放行。
- 9 项 Tcl 门禁回归 PASS。另在原失败 routed design 上由 GUI 实际执行新 hook，
  确认以 WNS=-0.195 拒绝生成 bitstream；负例证据独立放在
  `timing-r2/gate-negative-control/`，不代表 R2 构建结果。

RTL、BD、IP 配置及时钟/时序例外未改变，已有数值/协议验证继续适用，不重跑长仿真。
物理优化的选择依据为 AMD 的关键高扇出网络优化建议，以及本机 2022.2 的
Performance_WLBlockPlacementFanoutOpt 策略定义；能否收敛以 R2 最终 routed
结果为准，当前不能记为时序通过。
参考：[AMD UG949：Use Physical Optimization](https://docs.amd.com/r/2022.1-English/ug949-vivado-design-methodology/Use-Physical-Optimization)。

R2 完整链已通过原 attach GUI 重新提交，10 s 健康检查确认 synth_1 正在运行、
armed=1，post-route phys_opt 与 pre-bitstream 时序门禁均保留。实现和 bitstream
由同一 GUI 自动接续。现在停止轮询，等待用户通知完成或要求继续；尚未宣称时序收敛。

## R2 完成与板端资格队列

用户通知完成后，GUI 回读 synth / write_bitstream Complete，NEEDS_REFRESH=0。
R2 WNS +0.050668 ns、TNS=0；setup / hold / pulse-width 失败端点全零，
WHS +0.010 ns，WPWS +0.052 ns，299,455 个可布线网络全部布通，无 routing error。
bitstream 前门禁 PASS。DRC 无 Error / Critical Warning；实现日志保留既有 CMAC
Evaluation License 提示（与 Stage 34 发布边界相同）。通过同一 GUI 导出并再次执行
时序/DRC 门禁、报告及 HWH/BD 导出，结果 PASS；未重启 Vivado。

新 bitstream SHA-256：
`e00c586a1d862d7c7af113361832a30093334493e49f943e3dd22bf44f950665`。
导出带 core 0x00010036、QMC 16383/8192、PFB shift16、FFT 0x0556 身份。
旧 latest 导出已另存 `pre-stage36-export-latest/`，新 review 在 `r2-final-review/`。

板端资格队列 `stage36-20260905T061103Z-qualification-r1`：
1. 核查停流、DAC 静音、板载参考和接收机空闲，逐文件校验候选包，备份旧板端应用/config。
2. 暂停 Agent/watchdog，执行新 bitstream discovery 40 周期，再自动使用其推荐目标执行
   fixed 40 周期。每周期核验真实数字尺度，首个失败立即停止，保留候选和检查点。
3. 仅在新 40/40 全部通过后绑定新 catalog、安装新 Agent/watchdog 并更新本地 overlay/catalog。
4. 自动完成 160 MS/s TIME/SPEC/TIME_SPEC、320 MS/s TIME/SPEC 五模式各 60 s
   板端+接收机门禁；每窗口核验 QMC/PFB 身份、零丢包、零 FIR 饱和、零 FFT 溢出。
5. 自动进行新档 TIME 连续 50 ms 原始见证与 SPEC 连续 4096 帧全频原始谱短验收，
   标准差 8–12 count 门禁保持不变，检查每路全频中位数及 bins 3134/3182/3328，
   保存完整带通统计和实际尺度。失败不进入正式长科学采集。

资格包装核查发现 watchdog 仍重复定义 v34 默认值，已改为导入控制器的统一版本常量；
13 项 watchdog 测试及板端导入核查通过。其余资格回归：MTS 4、失败停止/防重提 3、
短采数值 6、catalog 5 均通过。新 Agent 为静态 aarch64 musl，依赖预检通过。
物理接线沿用 Stage35 已确认的八路独立 50 Ω；连接器状态无法远程感知。

资格队列已一次性提交为 user service
`stage36-qualification-20260905T061103Z-r1.service`，invocation
`a28a82baff91485d87ba33512192b58e`。在健康启动确认期间，discovery 初始化失败：
`XRFdc_Reset: DAC 0 timed out at state 6 in XRFdc_WaitForRestartClr`。
completed_cycles=0，尚未进入任何正式 MTS 周期。服务以退出码 1 停止；没有重复提交。

失败清理已执行 STOP，未发生清理错误。只读回读确认 core=0x00010036、streaming=0，
LMK 板载参考 profile 正确、PLL1/PLL2 均锁定，RFDC contract readback ok=true；
这不撤销先前的复位超时，也不证明 MTS 合格，根因仍待定位。
旧板端应用/config 已备份到 `/var/lib/t510/stage36/stage36-20260905T061103Z-qualification-r1/board-before.tgz`。
Agent/watchdog 保持暂停，Jupyter 仍运行；未安装新 Agent、未完成 catalog、未进入矩阵或科学采集。
板上新候选 bitstream 保持停流，保留失败现场，未偷偷恢复旧固件或跳过初始化门禁。

本机失败证据：`qualification-r1/mts_discovery_failed.json`、
`failure-readonly-status.json`、`failure_stop.log`、`queue-state.json`。
后续应先定位 DAC0 复位/时钟启动顺序问题，再以新队列身份执行完整资格，不能续算该失败队列为 PASS。

### DAC0 state 6 历史流程复用修复（qualification-r2）

核对 Stage 35 步骤 4 第 5.5–5.7 节及 Stage 34c-2 后确认，本次 campaign 初始化仍使用
“下载 PL → 重写 LMK → 请求 SYSREF 关闭时 Reset”的旧路径，未复用已验证的时钟流程。
不增加新的硬件恢复方法，不要求断电，也不靠反复 Reset 碰运气：

- 初始化调用现有 `_clock_preserving_preflight`，核验实时 LMK SHA、参考选择和双 PLL 锁，
  然后仅下载候选 PL；不重写 LMK，不执行额外 bootstrap Reset。
- 单独 RFDC Reset 周期按既有 `_repeat_active_clock_profile_mts` 顺序先请求 SYSREF，
  MTS 完成后关闭请求；复用 `reset_all_rfdc_tiles()` 的八 tile 完整性检查。
- LMK 重载周期按既有 `_apply_clock_profile` 顺序，在旧时钟下 Shutdown → LMK 写入/锁定 →
  SYSREF 请求 → PL 重载 → RFDC Reset/MTS。附带 PL 重载明确记录，不冒充独立 LMK-only 操作。
- 每次 PL 重载立即 STOP、DAC mask=0；失败清理同时 STOP、DAC mask=0、SYSREF 请求关闭。
- 五模式配置使用 Stage 35 的 `clock_preserving` API；短采已复用 Stage 35 同一配置构造器。
- 新队列恢复入口要求旧队列确为 FAIL、候选 SHA 相同、板端 Agent/watchdog 停止，
  在配置锁下校验 PYNQ 活跃 bitfile SHA、实际 core 与停流状态；不启动旧 v34 Agent 管理 v36。

相关回归共 19 项通过，包括时钟身份失败不得下载、Shutdown/LMK/SYSREF/重载/Reset 顺序、
锁定失败停止、首失败停止与防重复提交。新增验证聚焦 Stage 36 尺度差异，后续基础运维与
科学评测优先沿用 Stage 35 的实现和证据，避免重新走已排除的路径。

新完整队列 `stage36-qualification-20260905T061103Z-r2.service` 已提交，invocation
`8e637cca1b1747cca0505b064126a898`；证据目录 `qualification-r2/`。
自动接续 discovery 40 → fixed 40 → catalog/install → 五模式各 60 s → 新尺度短采门禁。
上次 r1 服务已核实 failed/exit 1，原证据未覆盖。本条仅记录提交，健康启动与最终状态另记。

健康启动检查：初始化成功，LMK RESET 与 profile 表均未写入；discovery 已完成 6 个周期、
errors=[]，越过原 DAC0 state 6 失败点。完整后续队列已武装，按 AGENTS.md 停止轮询并交还控制权。
这是健康启动证据，不代表 40/40、矩阵或读数范围已经通过。

### qualification-r2 Fixed 目标量化失败与修复

r2 的 discovery 40/40 通过，观测最大延迟为 ADC 432、DAC 768。Fixed 的前 20 个
RFDC-reset 周期通过；第 21 个周期（首次 overlay reload）停止，AMD 驱动报告 ADC 目标
452 小于本次最小可达 456。该失败与时钟 state 6 无关。

根因是 Stage 36 campaign 和 catalog finalizer 使用了简单的 `max + 20/+16`，遗漏了
Stage 35 已注册的 factor-12 量化及严格一 quantum 余量规则。现已把 Stage 35 的规则抽成
共享 `python/t510_mts_target.py`：先向上量化 margin floor，再增加 12。按 r2 包络对应 ADC
468、DAC 804。Stage 35 因果脚本、Stage 36 campaign 和 catalog finalizer 共同调用该实现；
25 项相关回归通过。r2 失败证据完整保留，r3 从 discovery 0/40 重新执行，不继承通过周期。

r3 完整队列已提交为 `stage36-qualification-20260905T061103Z-r3.service`，invocation
`92b292de8d734dd9b045be1e414fe481`。健康启动检查时 discovery 已完成 9 个周期，初始化成功、
errors=[]；discovery 完成后会自动用共享策略产生新目标，并接续 Fixed、发布、五模式和短采。
按长任务规则停止轮询并交还控制权；当前健康启动不代表最终资格通过。

### qualification-r3 DAC 周期分支失败与修复

r3 discovery 40/40 通过，Fixed 前 21 周期通过；第 22 周期（第二次 overlay reload）
停止。目标为 ADC/DAC `492/804`，DAC 四 tile 需要的 correction delay 超过驱动最大 31，
API 返回 `XRFDC_MTS_DELAY_OVER`。未进入安装、模式矩阵或短采。

AMD 2022.2 `XRFdc_MTS_Latency` 会在固定目标存在时，把测量值按一个 SYSREF 周期移动到
更接近目标的等价分支；Discovery 无外部目标，其首 tile 可使同一 DAC 相位族报告为
`32–96` 或 `768`。r2/r3 raw 数据证明本配置周期为 720 T1，Stage 35 已验证目标 112，
所以 768 应规范化为 48，不能作为线性最大值。新的共享策略以 Stage 35 的 112 为分支参考，
完整保留 raw/normalized 向量，再施加严格量化余量。r2/r3 重算均得到 DAC 132；ADC 分别为
468/492。相关 MTS、因果、catalog 与发布回归通过。r4 将从零重跑完整资格。

r4 已提交为 `stage36-qualification-20260905T061103Z-r4.service`，invocation
`c5cde104b61d4b61acb08c16eb497874`。健康检查时 discovery 已完成 11 个周期，初始化成功、
errors=[]；完整 discovery → fixed → 安装 → 五模式 → 短采队列已武装。按长任务规则停止轮询；
这只表示健康启动，不代表最终资格通过。

### qualification-r4 失败与 Stage 35 经验前置审计

r4 discovery 40/40 通过，fixed 前 35 周期通过；第 36 周期即第六次 LMK reload 出现
DAC 最小可达 latency 384，而当时目标 132，驱动以 `XRFDC_MTS_TARGET_LOW` 停止。未安装、
未运行五模式或短采，失败服务和原证据均保留。

本次不直接为 384 再加 margin 提交 r5。完整审计见
[36-01 Stage 35 经验前置审计](36_01_stage35_lessons_audit.md)。审计同时发现并修正了 DAC
周期分支可行域、3 s LMK 等待、START 3 s 正式边界、receiver 启动丢失、STOP 回包丢失、
增量遥测、SPEC frame-group/status 解释、最终 catalog 包身份，以及本地发布过早等问题。
冻结目标为 ADC/DAC `492/392`；相关本机 122 项、Rust 8 项及 GB10 9 项回归通过。

r5 完整资格队列已提交为 `stage36-qualification-20260905T061103Z-r5.service`，invocation
`0de2edf9f6d64b0e826b523fd8010ffa`；证据目录为 `qualification-r5/`。首次健康检查时服务持续
运行，队列状态为 `running / MTS_discovery_40`，提交身份锁定候选 bitstream SHA-256
`e00c586a1d862d7c7af113361832a30093334493e49f943e3dd22bf44f950665` 和冻结目标 `492/392`。
完整 discovery → fixed → catalog/安装 → 五模式 60 s → TIME/SPEC 短采 → 本地晋升已自动武装；
按长任务规则停止轮询。这只表示健康启动，不代表最终资格通过。

### qualification-r5 量化残差误判与 qualification-r6

r5 在 discovery 第 21 个动作（首个 overlay reload）停止。AMD API 返回成功、PLL1/PLL2 均锁定，
ADC latency 为 `[408,408,408,408]`；DAC latency 为 `[768,768,768,764]`、offset 为
`[0,0,0,29]`。旧门禁额外要求四 tile 报告值完全相等，因此误报
`DAC_TILE_LATENCY_MISMATCH`。r5 没有进入 fixed、安装、五模式或短采，失败清理成功，Agent 与
watchdog 均为 inactive。

AMD 2022.2 `XRFdc_MTS_Latency` 把 FIFO 校正量舍入为 converter factor 12 的整数倍，平局向下；
成功同步的最终报告残差可为 `-6..+5 T1`，所以合法的 tile 间跨度可以达到 11 T1。campaign、
fixed repeatability 和 catalog finalizer 已统一改为：API 必须成功，tile 间跨度必须小于一个
factor，fixed 的每个结果还必须落在目标的 ±6 T1 内。真实 r5 discovery 向量和预期 fixed
向量 `[396,396,396,392]` 已加入回归；12 T1 跨度仍被拒绝。宽范围 T510 回归共运行 254 项，
243 项通过、11 项按环境条件跳过。

r6 已提交为 `stage36-qualification-20260905T061103Z-r6.service`，invocation
`0a8a9903c6e74783adaaeec5bbda8f3e`；证据目录为 `qualification-r6/`。远端 25 个包文件逐项
验签通过，首次健康检查状态为 `running / MTS_discovery_40`，并从 discovery 0/40 重新开始；
后续完整资格队列已自动武装。按长任务规则停止轮询。

### qualification-r6 DAC 固定目标不可行与 qualification-r7

r6 discovery 40/40 完整通过；首个 fixed RFDC reset 随后测得 DAC latency
`[416,416,416,416]`，请求 392 时 AMD 驱动返回 `XRFDC_MTS_TARGET_LOW`。结合此前已经出现的
32、384 状态，按驱动的 720 T1 周期分支、factor 12 舍入和最大 31 级延迟逐个枚举，见证集合
`[32,384,416]` 没有任何共同的非负固定 DAC target。继续增大 392 会使低状态 32 被映射到
752 并再次产生 TARGET_LOW，因此不能再用增加 margin 修补。

Stage 35 的板载 TCXO 合同为 free-run，并用 sample0 表示相对时间；Stage 36 正式科学采集中
DAC 静音。资格合同据此改为 ADC deterministic target 492、DAC single-device relative
alignment `-1`。DAC 每次仍必须通过 AMD MTS API、四 tile 回读完整、offset 0..31 且 tile 间
factor 量化残差跨度小于 12 T1；这保留板内 DAC tile 对齐，但不再声明实际不可能稳定满足的
DAC 总延迟。catalog、Rust Agent、安装/发布器、五模式与短采身份门禁已同步该合同。

资格包进一步冻结 host/GB10 门禁脚本并在执行前验签，避免长任务引用后来变化的工作区文件。
本机 T510 回归运行 254 项，其中 243 项通过、11 项条件跳过；Rust 8 项、GB10 NumPy 9 项通过；AArch64 静态
Agent SHA-256 为 `bd801bd897839d1047dc5a11d3b814a57a09effe685d081f11503892613d7d09`。

r7 已提交为 `stage36-qualification-20260905T061103Z-r7.service`，invocation
`b888a144bfde44ebb75626bcaaf41d4e`。板端 30 文件、GB10 16 文件运行时验签通过，首次健康检查
状态为 `running / MTS_discovery_40`；完整 discovery → ADC-fixed/DAC-relative 40 → 安装 →
五模式 → 短采 → 晋升队列已自动武装。按长任务规则停止轮询。

### qualification-r10 封存与 current 发布

R10 已完成并通过板载 TCXO 的 discovery 40/40、fixed 40/40、五个合法全速模式各 60 秒及
新尺度短幅值门禁。正式 bitstream 为 `CORE_VERSION=0x00010036`，SHA-256 为
`e00c586a1d862d7c7af113361832a30093334493e49f943e3dd22bf44f950665`；R10 原证据已转换为
`build/qualification/latest/onboard_tcxo/adopted-r10.json`，没有重复运行耗时硬件门禁。

组件已改为 current-only：catalog 只有 `fengine-current`，Board Agent、time_rx、CUDA sidecar、
测量 API 和数据根均使用中性命名。2026-09-06 已先发布 time_rx，再发布 Board Agent、watchdog、
catalog 与 current overlay。板上原 bitstream SHA 相同，因此只更新 PYNQ current 路径，没有
重新下载 FPGA。部署后 160 MS/s TIME_ONLY 的 5 秒配置/收流/停流回归 PASS，host 与 board
正式窗口错误为零；结束状态为停流、DAC enable mask 0、core v36、QMC/PFB 尺度回读一致。
8035 历史页面继续返回 HTTP 200，旧 Stage 35 数据未移动。

2026-09-06 外部 10 MHz＋PPS 标准资格完成：CLKin2 双 PLL 锁定且 PPS 连续增长；discovery
与 fixed 均为 40/40 PASS，冻结目标为 ADC 468、DAC 108；五个合法全速模式各 60 秒均为
PASS。160 TIME+SPEC scheduled-PPS 门禁实际预留 40 个 PPS，TIME/SPEC 首包 sample0 均为
32788，连续 10 秒 host 门禁无错误。结束时已停流、DAC enable mask 为 0，catalog 状态为
`external_10mhz=qualified`。

### 正式科学采集、分析与 8036 交付

正式科学队列 `stage36-science-20260906-1852` 已完成 TIME_ONLY 900 s、A/B/C 三次
F-engine 自功率各 900 s、全部 28 对全频复可见度 900 s、八个 30 s TIME 对照，以及
连续 50 ms TIME 和连续 4096 帧全频 SPEC 见证。13/13 阶段均为 `completed`，最终总
manifest、TIME900、幅值门禁与跨数据集独立验签均 PASS；最终停流、DAC mask 0。

原始 TIME I/Q 标准差为 8.211–9.195 count，F-engine 八路全频 I/Q 标准差中位数为
8.005–8.720 count，均落在 8–12。按 QMC 和 PFB 实际增益消除尺度后，范围分别为
4.106–4.598 和 2.001–2.180 count；相对 Stage 35 中位数变化为 -1.19% 和 -3.18%。
因此读数放大符合设计，不能单独记作科学性能改善。

GB10 原地复用 Stage 35 最终 Explorer 的解包、Hann FFT、时间合并、Allan 数学和页面框架，
没有调用 HPC 或搬运约百 GB 输入。数值 API 与真实 Chromium 多选门禁 PASS，`8036` 已作为
独立只读 system service 发布；`8035` 保持存活且数据未修改。完整身份与限制见
[36-02 科学复评与 8036 交付](36_02_science_evaluation.md)。
