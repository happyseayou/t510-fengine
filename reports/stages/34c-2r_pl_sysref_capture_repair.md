BRANCH_HANDOFF_STATUS: SCIENCE_MATRIX_COMPLETE_V35_NOT_RELEASED

- 当前阶段：`SCIENCE_MATRIX_COMPLETE_V35_NOT_RELEASED`；r6完成SYSREF层18个及10/5 MHz频率层18个600秒正式run，r8完成3个低频320 MS/s补采并严格合并为42个有效run。全部数字门禁和安全恢复通过，但没有任何候选条件恢复`1/sqrt(N)`绝对门禁，因此v35候选不发布
- CORE_VERSION：`0x00010035`
- bitstream SHA256：最终隔离候选bit `8934a0c2d7033494b49133d846f954b52a6fa76a54b65c043c6e7be5289728d1`；第三轮诊断bit为`2de23f7a731622a984e2602a267ac780a1e5cedafa644f32a27d3e7d5628b5e0`；v34正式bit未被覆盖
- LMK profile SHA：修正后的TICS Pro完整导出manifest SHA256为`695308db629e6223ec2d9ef19c9c07cb0ebd231b5b18f8632a964c6210d17009`，包含4个基础profile及10/5 MHz各32个SDCLKout3原生相位profile
- Vivado invocation ID：首轮拒绝`stage34c2r-v35diag-20260810T174900+0800`；第二轮拒绝`stage34c2r-v35diag-r2-20260810T194600+0800`；第三轮诊断通过`stage34c2r-v35diag-r3-20260810T212700+0800`；最终候选`stage34c2r-v35final-20260811T110554+0800`已在GUI会话`stage34c2r@9999`完整通过`synth_1 → impl_1/phys_opt/route → write_bitstream`并导出
- systemd invocation ID：r6 `c79e2b1ae0a340e2aa74532151d23b79`完成全部36个正式run后在绘图导入停止；无硬件动作的r7因脚本入口import错误立即退出；r8 `05909aeca6074d15a5db458f87b630af`于2026-08-12 11:48:24 CST启动，`t510-stage34c2r-v35-finalize-r8.service`于11:57:59以`success`完成
- MTS分类：`10MHZ_AND_CORRECTED_5MHZ_PHASE_EYES_QUALIFIED`
- 科学分类：`SYSREF=CLOCK_SYSREF_NOT_CAUSAL_UNDER_SHARED_50OHM / RATE=SYSREF_RATE_CONTRIBUTOR / TCXO=PROFILE_UNQUALIFIED`；5 MHz仅为弱方向性贡献，不是可逆因果修复
- 是否升级latest：否；v34正式板端、catalog和receiver入口未被覆盖
- 唯一下一动作：保留v34生产配置，下一阶段转入34c-3电源与热稳定调查；不得把v35或5 MHz SYSREF profile作为生产修复发布

# Stage 34c-2R：PL SYSREF捕获修复与5 MHz调查

## 为什么必须先修RTL

Stage 34c-2第一次实验在外部10 MHz MTS-only profile的最后一次fixed-target出现DAC四tile
`[116,116,108,108]`分裂。复查v34工程发现PL SYSREF由160 MHz输入寄存器捕获后直接同时送入
ADC/DAC 80 MHz AXIS域，而且PL SYSREF输入曾被宽泛`set_false_path`屏蔽；routed证据没有
输入delay，也出现过TIMING-18。这不满足AMD针对PL clock与AXIS clock速率不同场景的重捕获
结构，因此不能用旧实验直接判断continuous SYSREF是否是科学噪声根因。

v35先保留10 MHz和全部RFDC/PFB/UDP数据契约，只修捕获拓扑和可观测性：差分PL SYSREF先在
160 MHz PL clock的IOB寄存器捕获，再由独立的ADC 80 MHz、DAC 80 MHz寄存器重捕获；三个域
分别计边沿，Gray跨到100 MHz控制域。`user_sysref_adc`与`user_sysref_dac`只在各自AXIS域
改变。三个计数器映射为`0x0030/0x0034/0x0038`，`0x002c`返回三个实时电平。

常驻Vivado GUI会缓存旧module-reference接口。为不让同名旧IP包装器静默复用v34七端口
接口，首级IOB捕获模块保留原接口，新增独立`pl_mts_axis_recapture`模块承载80 MHz重捕获和
计数；BD已实际回接`clk_wiz_0`的ADC/DAC 80 MHz时钟。该拆分不改变硬件结构或数据路径，
同时消除了工程缓存造成的不可重复重建。

## 约束与首个诊断bit边界

已删除PL SYSREF的宽泛false path，并对差分P/N建立相对160 MHz PL clock的临时
`set_input_delay -min 2.875 ns / -max 3.375 ns`。这只是为了让首个诊断bit产生真实定时端点，
状态明确为`PROVISIONAL_DIAGNOSTIC`，不能作为发布值。首个route必须输出`report_datasheet`、
输入路径报告、IOB LOC、TIMING-18检查以及PL→ADC/DAC setup/hold；随后用实际setup/hold要求
定义相位眼最小宽度。

相位眼固定覆盖6.25 ns；按LMK04828的SDCLKout3本地DDLY、half-step和ADLY原生状态构成32点
非均匀覆盖，最大相邻间隔241.667 ps（不超过250 ps）。每点必须绑定TICS Pro完整导出的profile和
SHA，执行3次RFDC reset加1次overlay reload，四个ADC tile和四个DAC tile各自一致，双PLL
锁定且三个物理计数器频率正确。选择最长循环全通过区间中心，眼宽必须不小于
`routed setup + hold + 1.0 ns`；没有合格眼就停止。

## 5 MHz与发布边界

5 MHz不能通过手改`SYSREF_DIV`生成。10/5 MHz和每个SDCLKout3局部delay候选均已由
TICS Pro 1.7.9.1从冻结工程完整导出；共68个profile，完整manifest SHA256为
`695308db629e6223ec2d9ef19c9c07cb0ebd231b5b18f8632a964c6210d17009`。首版profile只改变
`0x13a/0x13b`后，SYSREF反馈降为5 MHz而外部10 MHz参考仍以`CLKin2_R=1`进入PLL1，TICS已明确
显示`Feedback PD Freq = 5.0 MHz, PLL1 Unlocked`，实机也正确拒绝。修正版通过TICS命名字段把
`CLKin2_R`设为2，对应新增变化`0x158`，使PLL1参考端与nested-zero-delay反馈端均为5 MHz；
输出格式、其他SDCLK/DCLK和模拟SYSREF保持预注册边界。TICS临时TCP接口
在导出后已关闭，`settings.ini`恢复为`TCPCLIENT=false`。

首个v35只作为`/run/user/<uid>/t510-stage34c2r-v35-diagnostic`候选，不调用
`scripts/t510_build_latest.sh`，不会替换仓库`overlay/`或
板端v34正式目录。只有相位眼、各profile MTS 40/40、10 MHz单变量科学矩阵、5 MHz矩阵、
160/320长积分、五模式全速、scheduled START循环和60分钟soak全部通过，才允许原位升级
Board Agent、watchdog、receiver、Web、catalog和部署脚本并发布`fengine-0x00010035`。

## 已完成的软件门禁

- 新增10/5 MHz、门控停止、三域无漏边/重复的XSim testbench；完整RTL队列18/18通过，
  包含真实生产系数的8-tap PFB bit-exact测试和整机顶层smoke。
- Python候选身份不改变v34生产默认值；Board Agent按catalog显式接受v35候选。
- 状态API用50 ms两次物理计数读回判断`sysref_capture_running`，MTS-only必须停止、
  continuous必须增长，不能只信GPIO或`expected_on`字段。
- 相位眼工具校验32个原生相位点完整性、TICS文件SHA、3+1尝试类型、PLL、四tile一致性和三个计数频率，
  并实现跨0/6.25 ns循环眼中心选择及无合格眼失败。
- 最新完整仓库Python回归159项、Board Agent Rust 7项、receiver Rust 47项和XSim
  18项均通过；新增的第159项覆盖v35科学流期间SYSREF计数增长必须触发watchdog停流。
  routed门禁仍待首个诊断构建完成后继续。
- 旧文档中“PPS依赖10 MHz SYSREF域”的描述已按当前RTL更正：PPS独立在ADC 80 MHz域同步，
  后续仍必须回归scheduled START。

未完成时不得把本文件状态写成COMPLETE或PASS。只有全部构建、MTS、安全恢复和发布门禁闭合
后，首部才允许改为`BRANCH_HANDOFF_STATUS: COMPLETE`并写入固定完成句。

## 首个诊断route结果与拒绝原因

Vivado invocation `stage34c2r-v35diag-20260810T174900+0800`于2026-08-10 19:15 CST完成
`write_bitstream`，但该bit被明确拒绝上板：

- 全局WNS/WHS为`-0.186/+0.007 ns`，900个setup endpoint失败；最坏路径属于
  322.265625 MHz PFB `read_cmd_valid/read_cmd_idx → frame RAMB36`，不是SYSREF路径。
- PL SYSREF输入到首级寄存器的临时约束setup/hold为`+2.575/+0.059 ns`，但首级寄存器
  位于`SLICE_X80Y123`而非输入IOB，说明module-reference OOC中的RTL `IOB=TRUE`没有在顶层
  implementation生效。
- methodology仍有一个TIMING-18，但对象是异步`qsfp0_modprsl`，不是PL SYSREF；该输入已
  按异步状态信号显式false-path，不能伪造相对PL clock的input delay。
- 路由错误为0，hold通过。CMAC evaluation-license告警是既有许可边界，不改变本次时序失败。
- 首轮导出在门禁失败前没有复制临时候选，随后修复版`reset_run`删除了首轮bit，因此首轮
  bit SHA不可恢复；routed报告仍完整保留。导出器已改为先保存候选bit、SHA和run logs再执行
  routed门禁，后续失败证据不会再被下一次reset覆盖。

修复保持功能和流水级不变：顶层XDC重新对唯一首级捕获寄存器强制`IOB=TRUE`；PFB三个
BRAM读控制信号的物理复制阈值由64降到16，使综合器为小型BRAM簇生成局部副本；第二次诊断
实现启用`AggressiveExplore` physical optimization和post-route physical optimization。修复版
invocation为`stage34c2r-v35diag-r2-20260810T194600+0800`，已确认`synth_1/runme.sh`健康运行。
不得使用首个诊断bit进行相位眼或MTS实验。

第二个诊断invocation完成后，全局WNS/WHS改善为`+0.005/+0.010 ns`，证明PFB局部控制复制和
physical optimization修复了322.265625 MHz路径；bit SHA256为
`fdf5995860f0a4bebb40e7832f9d413b68ebd5fc06347d1a140c4b2ec1fa1003`。但实现日志显示
`[Designutils 20-1307] Command 'if' is not supported in the xdc constraint file`，因此IOB约束未执行，
首级仍位于`SLICE_X69Y110`。XDC已改为无控制流的`set_property -quiet IOB TRUE`，该bit同样
禁止上板；第二轮证据已完整归档为`diagnostic_bit_r2`。第三个诊断invocation
`stage34c2r-v35diag-r3-20260810T212700+0800`随后完成并证明IOB LOC、无该XDC Critical
Warning及全局时序通过，结果如下。

## 第三个诊断route与导出结果

第三个诊断invocation `stage34c2r-v35diag-r3-20260810T212700+0800`已于2026-08-10 23:18 CST
完成并通过诊断导出门禁：

- `synth_design Complete!`、`write_bitstream Complete!`；全局routed WNS/WHS均为`+0.010 ns`。
- 首级`pl_sys_ref_capture_reg`位于`BITSLICE_RX_TX_X0Y78`，证明顶层`IOB=TRUE`约束实际生效；
  输入setup/hold slack在临时`2.875/3.375 ns` input-delay包络下分别为`+3.555/+0.826 ns`。
- `report_datasheet`给出的该IOB输入寄存器setup/hold要求为`-0.680/+2.049 ns`；正式相位眼仍
  以实测连续通过区间为准，临时input delay不能直接冻结为发布约束。
- PL到ADC 80 MHz重捕获setup/hold为`+3.165/+0.900 ns`，PL到DAC 80 MHz为
  `+4.295/+0.262 ns`，均通过。
- SYSREF不再存在宽泛false path或TIMING-18；综合无Critical Warning。实现仅保留既有CMAC
  evaluation-license告警，未发现新的SYSREF约束或DRC错误。
- 诊断bit SHA256为
  `2de23f7a731622a984e2602a267ac780a1e5cedafa644f32a27d3e7d5628b5e0`，候选位于
  `/run/user/1000/t510-stage34c2r-v35-diagnostic/overlay`；完整routed证据位于
  `build/board/latest/evidence/clock_sysref_causality/diagnostic_bit`。该路径没有覆盖v34 latest。

因此RTL捕获拓扑、IOB位置和静态时序修复已经闭合；其后的TICS Pro完整profile与相位眼
提交状态记录如下。Stage 34c-2R整体仍未完成，后续仍需正式XDC冻结及最终v35重构建。

## TICS profile与相位眼长任务提交

TICS Pro完整导出已闭合：4个基础profile、10 MHz的32个相位profile和5 MHz的32个相位
profile均写入`build/board/latest/evidence/clock_sysref_causality/tics_profiles`，共68个profile；
修正后manifest SHA256为`695308db629e6223ec2d9ef19c9c07cb0ebd231b5b18f8632a964c6210d17009`。
原计划的均匀25点被修正为LMK真实可实现的32点非均匀原生覆盖，最大循环间隔为
241.667 ps；这样既满足“不超过250 ps”，也不把不存在的LMK延迟值写入硬件。

v35候选已从隔离的`/run`目录部署到板端8010端口，v34正式目录和latest均未覆盖。实机
10 MHz phase-00预检通过：一次overlay reload的ADC四tile latency为`[336,336,336,336]`、
DAC为`[144,144,144,144]`，三域边沿频率均约10.02 MHz，双PLL锁定，MTS结束后物理SYSREF
计数停止。预检还发现并修复两个仅影响诊断显示/辨识的软件问题：状态采样窗口曾混入LMK
查询耗时，以及完整LMK回读列表遗漏`0x10c/0x10d`相位辨识寄存器；对应回归已通过。

完整长任务已由用户级systemd一次性提交：

- unit：`t510-stage34c2r-phase-eye.service`
- invocation ID：`f6e2428bbe1e47fa865e3f733b922deb`
- 启动时间：2026-08-11 00:46:50 CST
- evidence：`build/board/latest/evidence/clock_sysref_causality/phase_eye/campaign.json`
- 队列：10 MHz 32点后自动进入5 MHz 32点；每点1次overlay reload加3次RFDC reset
- 自动收尾：任务结束或受控失败后恢复v34生产Agent、production continuous profile、fresh
  CONFIGURE/MTS、停流和DAC全零

正式队列首点已健康完成并自动进入第二点。首点4次尝试ADC均为`[336,336,336,336]`、DAC
均为`[168,168,168,168]`，双PLL、三域约10 MHz计数和MTS后门控均通过；latency与独立预检
不同但各次内部四tile一致，因此是本相位点的有效发现值而不是失败。按长任务规则，本会话
在确认自动接续后停止轮询，等待用户在新会话要求检查最终结果。

## 首轮结果、5 MHz修正与补跑

首轮unit在2026-08-11 01:28:55 CST按门禁退出。10 MHz部分完整完成32/32点、128次MTS：
全部点通过，循环通过宽度6008.333 ps，大于2369 ps门限，选择中心为3000 ps。首个5 MHz
profile则在写表后PLL1持续不锁，任务没有进入5 MHz MTS，随后自动恢复v34 production
continuous profile、fresh CONFIGURE/MTS、STOP和DAC全零；这是有效的配置拒绝，不是板端残留。

根因由TICS工程自身直接给出：本板以SYSREF divider作为PLL1 nested-zero-delay反馈。只把
`SYSREF_DIV`从240改为480会使反馈从10 MHz变为5 MHz，但外部10 MHz参考仍以
`CLKin2_R=1`进入相位检测器，因此两侧频率不相等。修正版使用TICS命名字段同时设置
`SYSREF_DIV=480`与`CLKin2_R=2`，TICS显示SYSREF、PLL1 PFD和反馈均为5 MHz且PLL1 locked；
完整寄存器diff严格限定为`0x13a/0x13b/0x158`。

修正版5 MHz phase-00实机预检通过：ADC latency `[336,336,336,336]`、DAC
`[144,144,144,144]`，双PLL锁定，三域在51.721 ms内计数约259.16k（约5.01 MHz），MTS后
计数停止。只补跑5 MHz的systemd任务已提交：

- unit：`t510-stage34c2r-phase-eye-5m.service`
- invocation ID：`edbe4ce383784b24870c00c36d125a24`
- evidence：`build/board/latest/evidence/clock_sysref_causality/phase_eye_5mhz_corrected`
- 最终状态：`success`、退出码0、`PHASE_EYE_5M_QUALIFIED`；32/32点和128/128次尝试通过，
  v34安全恢复且恢复错误为空

本分支会话的最终边界已按用户澄清：必须在5 MHz相位眼后继续冻结正式XDC，并完成最终v35
的`synth → implementation/physical optimization/route → write_bitstream`及routed门禁；科学
因果矩阵不在本分支执行。

## 修正5 MHz相位眼闭合与最终v35构建提交

修正后的5 MHz补跑已正常完成，unit结果为`success`、退出码0，campaign分类为
`PHASE_EYE_5M_QUALIFIED`：32/32个原生相位点和128/128次MTS尝试全部通过，循环保守通过宽度
为6008.333 ps，大于2369 ps门限，最长相位间隔为241.667 ps，最终同样选择3000 ps。
自动收尾确认v34恢复成功且无错误。10 MHz和5 MHz因此冻结为：

- 10 MHz：`160m_10m_request_clkin2_sdclkout3_phase_15`，寄存器SHA256
  `2dee613b9c267ffc452a904f22f19d69009187b33a080c57282cc93def8dffc6`；
- 5 MHz：`160m_5m_request_clkin2_sdclkout3_phase_15`，寄存器SHA256
  `31eb4c56ec9bfacedab4a1246e2d43a601698fc8f785c32c10a56a23953b88d9`。

最终XDC以3000 ps为中心，并用原生扫描最大间隔的一半作为保守量化误差包络：
`set_input_delay -min 2.879166 ns / -max 3.120834 ns`。导出器已增加隔离的`candidate`模式，
正式候选输出到`/run/user/1000/t510-stage34c2r-v35-candidate`并把routed证据写入
`build/board/latest/evidence/clock_sysref_causality/final_candidate_bit`，不会覆盖v34 latest，
也不会删除第三轮诊断bit证据。

最终Vivado长任务已于2026-08-11 11:05 CST在已连接GUI中一次性提交：

- invocation：`stage34c2r-v35final-20260811T110554+0800`；
- 链路：`synth_1 → impl_1`（含AggressiveExplore phys_opt和post-route phys_opt）
  `→ route → write_bitstream`，8 jobs；
- 启动确认：`synth_1`状态为`Running synth_design...`，runme.log已创建并持续更新；
- 长任务边界：本轮确认健康后停止轮询，等待用户通知GUI完成，再执行最终routed检查与候选导出。

## 最终route、bitstream与科学矩阵前交接

用户确认GUI完成后，本分支检查并导出了最终候选。Vivado invocation
`stage34c2r-v35final-20260811T110554+0800`的最终结果为：

- `synth_design Complete!`和`write_bitstream Complete!`，综合0 Critical Warning、0 Error；
- routed WNS/WHS为`+0.010/+0.010 ns`，TNS/THS均为0，失败endpoint为0；
- 首级PL SYSREF寄存器位于`BITSLICE_RX_TX_X0Y78`且`IOB=TRUE`；最终相位包络下输入
  setup/hold slack为`+3.809/+0.830 ns`，Board Agent状态使用较小值`0.830 ns`；
- PL→ADC 80 MHz重捕获setup/hold为`+3.165/+0.900 ns`，PL→DAC 80 MHz为
  `+4.295/+0.262 ns`；
- route error为0，严重DRC为0，TIMING-18为0；methodology集合与第三轮通过的诊断bit
  完全相同，没有新增SYSREF告警。实现日志唯一Critical Warning仍是既有CMAC evaluation
  license提示，不是引脚、SYSREF、DRC或时序失败；
- 最终bit SHA256为
  `8934a0c2d7033494b49133d846f954b52a6fa76a54b65c043c6e7be5289728d1`，bit头目标器件为
  `xczu47dr-ffve1156-2-i`，构建时间为2026-08-11 12:57:35 CST；
- 隔离候选位于`/run/user/1000/t510-stage34c2r-v35-candidate/overlay`，完整报告、routed DCP、
  run日志和summary位于`build/board/latest/evidence/clock_sysref_causality/final_candidate_bit`。

导出期间没有调用latest发布路径。最终安全回读仍为v34 production continuous profile，
`streaming=false`、DAC enable mask为0、八路幅度码全0、freeze mask为0、OCB1 override mask为0
且状态为`DYNAMIC`，PLL1/PLL2均锁定。因此PL SYSREF捕获/静态时序修复和本分支要求的全部
Vivado构建工作已经完成；后续MTS及科学矩阵现已由下节记录的长任务执行。任务结束前不得把
这一状态写成v35生产资格或科学PASS。

`Stage 34c-2R PL SYSREF capture/timing repair completed; MTS/science qualification running.`

## 正式MTS与科学矩阵长任务提交

最终v35候选的正式资格与科学矩阵入口已原位升级。campaign固定使用最终bit身份
`CORE_VERSION=0x00010035`及SHA256
`8934a0c2d7033494b49133d846f954b52a6fa76a54b65c043c6e7be5289728d1`，并选用相位眼冻结的
10 MHz和5 MHz 3000 ps profile。资格队列依次执行每个必需profile的10次discovery、
10次fixed-target及request-low负对照；科学部分比较continuous 10 MHz、gated 10 MHz和
gated 5 MHz。中心1020 MHz的monitor扩展为30个点：960 MHz固定项、11个10 MHz栅格点、
12个仅属于5 MHz栅格的点和6个离栅格科学点，保持在receiver单任务32-bin上限以内。TCXO
profile只在自身资格通过时进入参考源矩阵，资格失败不会污染10/5 MHz主因果矩阵。

本轮软件更改完成后，完整Python回归164项通过，包含v35身份绑定、profile集合、30-bin映射、
矩阵顺序、隔离部署和安全恢复。长任务runner把候选Agent/watchdog部署在板端`/run`隔离目录，
运行期间停止v34生产service；任务成功或失败都会恢复v34生产continuous profile、fresh
CONFIGURE/MTS、STOP、receiver原配置和DAC全零，不会把候选发布到latest。

提交时有两次部署前故障，均未进入MTS或科学run，且均自动恢复v34安全状态：

- invocation `f9f67da860ec4e8ca94de54c63719986`（2026-08-11 14:05:07 CST）因远端sudo只覆盖
  `rm`、未覆盖`install /run`而退出；
- invocation `118d613472234540ad719377ce164d59`（2026-08-11 14:09:40 CST）因上传临时目录
  属主错误导致SCP拒绝而退出。

runner已把整条远端命令纳入sudo shell并显式设置上传目录属主，独立上传预检通过。当前唯一
有效任务为：

- unit：`t510-stage34c2r-v35-science.service`；
- invocation ID：`4a2b470adc2e4dbaa0a7b457a080c71d`；
- 启动时间：2026-08-11 14:14:02 CST；
- runner evidence：`build/board/latest/evidence/clock_sysref_causality/science_matrix/runner.json`；
- campaign evidence：`build/receiver/latest/evidence/clock_sysref_causality/science_matrix/campaign.json`。

有效任务已确认板端隔离候选Agent和watchdog均为active，远端候选bit SHA与最终冻结值一致。
首个production continuous-10-MHz discovery已健康完成：ADC四tile latency为
`[348,348,348,348]`，DAC为`[144,144,144,144]`，clock transaction ID为
`clock-dc6e2901938b6e4b8647d59926bf386d`；任务随后自动进入下一轮资格。按长任务规则，本会话
在确认自动接续后停止轮询。当前只可写为`RUNNING`，不得提前写成MTS、科学或v35生产PASS。

## 首次正式资格任务停止结果

用户后续检查时，unit `t510-stage34c2r-v35-science.service`已于2026-08-11 14:27:48 CST
以非零状态受控停止，总运行13分45秒。continuous-10-MHz profile的10次discovery全部完成，
每次ADC和DAC四tile内部一致；ADC discovery在`348/708`两种latency间切换，DAC为
`120/144/192`，脚本据此生成ADC/DAC target `728/208`。首个fixed-target中ADC报告本轮最低
可行latency为732，而请求728在RFDC内部对齐到732边界后仍不满足严格最小值条件，
`adc_mts_sync`返回32。该失败发生在第一个fixed-target，fixed完成数0/10；gated 10 MHz、
gated 5 MHz、TCXO、负对照、短筛查、低RF观察和600秒正式矩阵均未开始，科学run数为0。

这是fixed-target余量/量化计算的运行故障，不是continuous SYSREF科学结论，也不是已证明的
v35硬件失效。现有算法直接使用`max(discovery)+20/+16`，没有在factor-12网格上保证量化后
严格高于当轮minimum；下一次提交前必须改成带显式严格余量的向上量化并覆盖“恰好落在minimum”
边界测试，不能通过人工挑选一次成功结果继续。

runner随后恢复v34生产Agent和watchdog，候选服务停止。2026-08-11约14:42 CST的实时回读
确认`CORE_VERSION=0x00010034`、production external-GPSDO continuous profile、PLL1/PLL2锁定、
`streaming=false`、`stream_accepting=false`、DAC mask为0、八路幅度码全0、freeze mask为0；
因此当前板端安全，但任务已经停止而非等待中。本次campaign和runner结果继续保存在原
`science_matrix`目录，修复后的新提交必须使用新证据作用域并引用本次失败，不能覆盖。

## Fixed-target修复与r2重新提交

首次失败的根因已按factor-12规则修复。新算法保留预注册的ADC `+20`、DAC `+16` nominal
margin，先把`max(discovery)+margin`向上量化到12-cycle网格，再额外保留一个完整12-cycle
headroom；这保证请求值严格高于RFDC的量化minimum，而不是恰好相等。首次数据对应：

- ADC：`max=708 → margin floor=728 → quantized floor=732 → target=744`；
- DAC：`max=192 → margin floor=208 → quantized floor=216 → target=228`。

新增测试覆盖首次实际边界、nominal floor恰为12倍数的等号边界、target policy证据和checkpoint；
相关测试8项、完整Python回归167项、`py_compile`及`git diff --check`均通过。首次失败目录原样
保留，r2写入独立的`science_matrix/attempt_r2`，没有复用旧discovery或挑选旧结果。

r2已作为新的完整长任务提交：

- unit：`t510-stage34c2r-v35-science-r2.service`；
- invocation ID：`630795b5b5764eb89ec018993b0b3ab7`；
- 启动时间：2026-08-11 15:14:36 CST；
- runner evidence：`build/board/latest/evidence/clock_sysref_causality/science_matrix/attempt_r2/runner.json`；
- campaign evidence：`build/receiver/latest/evidence/clock_sysref_causality/science_matrix/attempt_r2/campaign.json`。

实机已重新完成continuous-10-MHz的10/10 discovery。随后fixed 1/10和2/10均成功，两个轮次
ADC四tile均为`[744,744,744,744]`，DAC均为`[228,228,228,228]`，证明本次修复跨过了原
728/732失败边界；runner/campaign均为`IN_PROGRESS`且errors为空，任务已自动进入fixed 3/10。
按长任务规则，确认关键修复和自动接续后停止驻留轮询，后续由用户要求时检查同一r2任务。

## r2停止结果：负对照profile名称不一致

r2随后完成了两组完整资格主体：

- production continuous 10 MHz：10/10 discovery、10/10 fixed全部通过，target为ADC/DAC
  `744/228`；
- selected gated 10 MHz phase-15：10/10 discovery、10/10 fixed全部通过，target为ADC/DAC
  `756/252`。

第二组完成后，campaign提交request-low SYSREF负对照。通用profile校验已经接受冻结的
`160m_10m_request_clkin2_sdclkout3_phase_15`，但Rust负对照专用校验和Python helper仍只接受
旧profile ID `160m_10m_request_manual_clkin2`，因此请求在硬件负对照开始前以HTTP 400
`SCHEMA_VALIDATION_FAILED`被拒绝。unit于2026-08-11 15:54:28 CST受控停止，总运行39分52秒；
5 MHz、TCXO、短筛查、低RF和600秒正式矩阵均未开始，科学run为0。

该结果证明fixed-target量化修复有效，也证明continuous及gated 10 MHz的20/20主体资格通过；
它不构成SYSREF负对照或科学因果结论。runner已恢复v34生产状态。约16:28 CST实时回读确认
`CORE_VERSION=0x00010034`、production continuous profile、PLL1/PLL2锁定、STOP、receiver
不接收、DAC mask及八路幅度全0、freeze mask为0。r2证据固定保留在
`science_matrix/attempt_r2`。

## 负对照schema修复与r3重新提交

Rust请求模型和Python helper现使用同一外部request profile规则：接受10/5 MHz基础CLKin2
request profile以及TICS冻结的`phase_00..31`，拒绝production continuous、TCXO和越界/非数字
phase。OpenAPI同步取消过时的三值enum并明确冻结phase profile语义。新增回归覆盖10 MHz
phase-15、5 MHz phase-15、两个基础request profile的接受，以及continuous、TCXO、phase-32
和非数字phase的拒绝。

验证结果：针对性Python 10项、完整Python 169项、Cargo 8项全部通过；ARM64静态Agent使用
工程规定的`cargo zigbuild --release --target aarch64-unknown-linux-musl`重新构建，SHA256为
`bb46348a083cd42d9f363c778d83fc5e605f3a51a2ff4f90d7e81585cd23986d`。没有复用r2旧binary。

r3完整队列已提交：

- unit：`t510-stage34c2r-v35-science-r3.service`；
- invocation ID：`590633090c86456abac4ce1f7a6aaf6c`；
- 启动时间：2026-08-11 16:33:44 CST；
- runner evidence：`build/board/latest/evidence/clock_sysref_causality/science_matrix/attempt_r3/runner.json`；
- campaign evidence：`build/receiver/latest/evidence/clock_sysref_causality/science_matrix/attempt_r3/campaign.json`。

板端`/run/t510-stage34c2r-v35-agent/bin/t510-board-agent`实测SHA与新构建完全一致；候选Agent和
watchdog均active，v34 production服务在隔离运行期间inactive。r3前2次continuous discovery已
通过，runner/campaign为`IN_PROGRESS`、errors为空并自动接续。负对照约在完成前两组各20轮
资格后到达；按长任务规则，本会话确认新二进制和首轮MTS健康后停止驻留轮询。

## r3停止结果：10轮discovery未覆盖gated延迟包络

r3中的production continuous 10 MHz再次完成10/10 discovery和10/10 fixed，ADC/DAC target
为`744/228`。selected gated 10 MHz完成10/10 discovery，ADC观测为
`360/384/696/708`、最大708，DAC最大216，因此生成target `744/252`。前5次fixed均精确回读
ADC/DAC `744/252`；第6次RFDC的ADC最低可行latency跃迁到780，请求744无法满足，
`adc_mts_sync`返回32，任务于2026-08-11 17:09:34 CST受控停止，总运行35分50秒。

因此r3没有到达已修复schema的request-low负对照；5 MHz、TCXO、筛查和正式科学run也均为0。
这不是科学结论，而是资格方法暴露的新问题：10轮discovery没有包住同一profile稍后fixed阶段的
偶发780状态。r2同一profile的discovery最大720、target756曾完成10/10 fixed，进一步证明按单次
10轮样本动态生成target会导致不同attempt采用不同包络，不能作为稳定冻结策略。下一次必须基于
phase-eye及r1/r2/r3全部数据预注册保守profile target和验证轮数，不能只针对本次值临时加12。

runner已恢复v34。约18:04 CST实时回读确认`CORE_VERSION=0x00010034`、production continuous
profile、PLL1/PLL2锁定、`streaming=false`、`stream_accepting=false`、DAC mask及八路幅度全0、
freeze mask为0。r3证据固定保留在`science_matrix/attempt_r3`。

## 全证据冻结target修复与r4重新提交

r3之后不再使用“每次10轮discovery的最大值”重新计算target。新策略把phase-eye及r1/r2/r3
里观察到的自然latency和RFDC在失败时报告的严格minimum统一形成冻结证据包络，再执行固定的
`nominal margin → factor-12向上量化 → 额外一个12-cycle headroom`。冻结值为：

- production continuous 10 MHz：证据包络ADC/DAC `732/192`，target `768/228`；
- selected gated 10 MHz phase-15：证据包络`780/216`，target `816/252`；
- corrected gated 5 MHz phase-15：32相位128次证据包络`1140/216`，target `1176/252`；
- TCXO gated：保守继承10 MHz包络`780/216`，target `816/252`。

较高target只增加确定性的RFDC管线延迟，不降低3.84 GS/s采样、160/320 MS/s科学速率或网络
吞吐。每次10轮discovery仍保留，但现在只检查有没有超出冻结证据包络，不再把target向下调整。
完整策略JSON的冻结SHA256为
`c39968a394ad53b2fc8dbf401f4974d37340360f285819f545b5ee1e2549a3e7`；测试覆盖冻结target、
策略SHA、超包络立即停止、失败轮次checkpoint以及原边界，完整Python 171项、Cargo 8项通过。

r4使用独立证据目录提交：

- unit：`t510-stage34c2r-v35-science-r4.service`；
- invocation ID：`f42bbdc85f79469e8a81da0f0b3ff4c7`；
- 启动时间：2026-08-11 18:14:44 CST；
- runner evidence：`build/board/latest/evidence/clock_sysref_causality/science_matrix/attempt_r4/runner.json`；
- campaign evidence：`build/receiver/latest/evidence/clock_sysref_causality/science_matrix/attempt_r4/campaign.json`。

提交后已确认候选Agent SHA256仍为`bb46348a083cd42d9f363c778d83fc5e605f3a51a2ff4f90d7e81585cd23986d`，
候选bit及TICS manifest SHA均匹配，板端隔离Agent/watchdog active，campaign内冻结策略SHA和
四个target回读正确。后续检查时continuous和gated 10 MHz均已完成10/10 discovery及10/10
fixed，四tile固定回读分别为`768/228`与`816/252`，因此已跨过r1和r3的两个latency失败点。
gated 10 MHz的request-low负对照实测返回`MTS_TIMEOUT + SYSREF_FREQ_NDONE`，恢复后以冻结target
重新MTS成功，`passed=true`；r2的phase-profile schema故障也已闭合。当前首个gated 5 MHz
discovery完成，unit保持running、errors为空。按长任务规则后续只检查同一r4，不重新提交。

## r4低频marker故障、断点恢复与r6接续

r4后续完整通过gated 5 MHz资格和负对照。三个必需profile均完成10/10 discovery及10/10
fixed；TCXO因PLL1不锁按预注册规则标记为不合格并排除。随后16个适用120秒筛查全部完成，
数字门禁未报错。进入低RF上下文时receiver正确拒绝`122.880000 MHz`：该标称频率在
center=160 MHz下不是160/320 MS/s的精确4096通道PFB bin。r4因此于2026-08-11 20:21:15
CST受控停止，600秒正式科学run为0并恢复v34安全状态。

计划原文要求“122.88 MHz及最近PFB bin”。修复固定使用两种速率共同的最近精确点
`122.890625 MHz`，对应160/320 MS/s signed bin `-950/-475`；campaign启动前现在验证全部
科学和低频频点的双速率exact-bin契约。r4 campaign SHA256
`d1f89cf0fe5a2732cd01b7dd454d5ab0f3f0693538d5ca8f1db4c60a9466dc2a`通过严格断点恢复门禁：
候选身份、冻结策略、三个必需profile的10+10资格和16个筛查名称/状态均匹配，且唯一失败必须
是已登记的122.88 MHz错误，否则拒绝复用。

r5证明修正频点已被receiver接受并完整采得60秒、1080条功率记录，但离线汇总对低RF不存在的
`fixed/grid10/grid5_only`空分组调用`fmean`而失败。该run没有进入正式结果；空分组现在固定
输出`count=0`及`null`统计值。使用r5真实raw离线重算得到18个完整ADC×频点组合，完整Python
回归为175项通过。

r6使用相同r4 checkpoint重新提交：

- unit：`t510-stage34c2r-v35-science-r6.service`；
- invocation ID：`c79e2b1ae0a340e2aa74532151d23b79`；
- 启动时间：2026-08-11 20:39:36 CST；
- evidence：`build/{board,receiver}/latest/evidence/clock_sysref_causality/science_matrix/attempt_r6`。

r6已验签复用16个筛查，首个`lowrf_160msps_ext_cont`完整完成：60秒monitor、始末PCAP、18个
组合分析、数字完整性和安全收尾均通过，campaign errors为空；队列已自动进入
`lowrf_320msps_ext_cont`。按长任务规则后续只检查同一r6，不重复提交。

## r6正式矩阵完成与r8离线闭合

r6随后完成全部计划中的外部GPSDO正式数据：SYSREF层18个600秒run和10/5 MHz频率层18个
600秒run均为`STAGE34C2_RUN_COMPLETE`，每个run的drop、gap、backpressure、FIR saturation、
XFFT overflow和温度门禁均通过。TCXO profile资格时PLL1不锁，因此参考源层按预注册规则
标记`TCXO_PROFILE_UNQUALIFIED`并跳过，没有伪造TCXO结论。r6分析得到：

- SYSREF层：`CLOCK_SYSREF_NOT_CAUSAL_UNDER_SHARED_50OHM`；关闭continuous SYSREF没有达到
  绝对或可逆因果门禁；
- 10/5 MHz频率层：`SYSREF_RATE_CONTRIBUTOR`；5 MHz有小幅、可重复方向性改善，但没有达到
  恢复`1/sqrt(N)`的绝对门禁，不能称为修复；
- reference层：`TCXO_PROFILE_UNQUALIFIED`。

r6在所有采集和分析完成后才因本机`/usr/bin/python3`缺少Matplotlib而于2026-08-12
05:32:26 CST退出。另有3个320 MS/s低频上下文run的冗余静音写使用板端量化回读
`159.9999999999909 MHz`，被160 MHz下边界拒绝；这些run的DAC在前后读回均已全零、采集及
数字完整性均成功，但仍按硬门禁不直接复用。安全静音现优先接受STOP后的全零硬件读回，
否则把实时中心约束到采样率合法边界；绘图改为项目内Pillow后端。完整Python回归180项通过。

专用finalizer严格验证r6的36个正式run集合、每run完整性、组合数和bit-exact分析，只补采上述
3个320 MS/s低频上下文run。r7在任何硬件动作前因脚本入口缺少repo `sys.path`立即退出；修复
后直接执行`--help`与测试通过。当前r8：

- unit：`t510-stage34c2r-v35-finalize-r8.service`；
- invocation ID：`05909aeca6074d15a5db458f87b630af`；
- evidence：`build/{board,receiver}/latest/evidence/clock_sysref_causality/science_matrix/attempt_r8_finalization`。

r8于2026-08-12 11:57:59 CST正常完成。三个低频320 MS/s补采均完成60秒monitor、始末PCAP、
分析和安全静音，最终严格合并6个低频上下文run与r6的36个正式run，共42个有效run；
`operational_ok=true`、`errors=[]`。最终生成3幅Pillow PNG、`summary.csv`以及84份被引用PCAP的
SHA256 manifest；manifest自身SHA256为
`6359a02f961f924b43b6c43287033748366ea3b63f77b17def2860a153ae29d0`，84/84文件现场复核通过。

最终分类保持：SYSREF层为`CLOCK_SYSREF_NOT_CAUSAL_UNDER_SHARED_50OHM`，即continuous与
MTS-only/gated之间没有绝对或可逆改善；10/5 MHz层为`SYSREF_RATE_CONTRIBUTOR`，5 MHz相对
10 MHz仅有小幅方向性改善，但绝对斜率、lag和A2恢复关系均不足以证明因果，更没有恢复
`1/sqrt(N)`；TCXO因PLL1不锁为`TCXO_PROFILE_UNQUALIFIED`，不作参考源结论。因此Stage 34a
长积分不合格状态不变，v35候选不得发布。

r8自动恢复生产v34。完成后再次在线回读确认`CORE_VERSION=0x00010034`、外部GPSDO 10 MHz
continuous profile、PLL1/PLL2锁定、`streaming=false`、`stream_accepting=false`、DAC mask=0、
八路幅度码全0、freeze mask=0、OCB1 override mask=0且状态为`DYNAMIC`；receiver流量为0且
kernel/app drop保持0。
