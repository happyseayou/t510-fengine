# T510 F-engine 阶段报告

本目录根部只保留 Stage 32 及以后报告；Stage 31 及更早内容统一归档在 `arch/`，不再作为
当前接续入口。运行产物、配置、部署和脚本均遵循 latest-only，只有本目录报告使用 Stage
名称。

## 最新状态

- 当前正式版本为 Stage 34：`CORE_VERSION=0x00010034`、固定 4096 通道 8-tap PFB、
  bitstream SHA-256
  `c21d93f5ea71e9ac17a4448cff138a8faaf9c7347d879be919b680d196b8a5be`、MTS target
  ADC/DAC `416/112`。综合、实现、bitstream、MTS 40/40、八路回环与全速稳定性均已闭合。
- Stage 34a 的数字吞吐和全带扫描通过，但长积分斜率未达到`1/sqrt(N)`；时间打乱后恢复
  接近`-0.5`，证明同一路ADC存在时间相关过程，因此没有取得天文基线资格。
- Stage 34b-1 已证明当前v34可软件观测并原子freeze/unfreeze八路RFDC校准，且无需新
  bitstream。Stage 34b-2已按PG269的`-40 dBFS`器件下限改用带4 dB余量的`-36 dBFS`
  工程下限；25/50/75/100%扫描选择100%，八路实测`-33.70..-32.64 dBFS`，系数平稳、
  freeze和安全清理预检均通过。原18次A/B/C全部采完且数字完整，但训练冻结在160/320
  MS/s均未恢复`1/sqrt(N)`，34b-2科学门禁失败。50～330 MHz低RF扩展在完成7个
  160 MS/s run后按用户指令终止，第8个run排除，320 MS/s及其余重复未执行；已完成数据
  仍显示原始序列斜率`-0.187..-0.313`、时间打乱后`-0.511..-0.550`，只证明低RF也存在
  同类现象，不形成A/B/C结论。安全收尾已确认，34b-3/4仍受原门禁阻止。
- Stage 34c已经完整结束：共享SSA 50 Ω输入下的6次34c-0仍复现时间相关噪声，随后18次
  OCB1 A1动态/B快照锁定/A2恢复及一次TIME_SPEC定位全部完成，共25个正式run、57份PCAP、
  109张图，数字门禁和安全收尾均通过。空调关闭造成的环境升温按用户授权保留2 °C警告线、
  将硬停止线最小放宽到2.5 °C，并把受影响的旧t03整组重做。最终分类为
  `INCONCLUSIVE_BASELINE_NOT_REPRODUCED`：A1没有达到预注册的严格严重度复现门禁，不能正式
  把OCB1定责；但锁定OCB1在160/320 MS/s均使积分斜率和lag相关变差，解除后回到动态基线
  附近，故明确否定OCB1快照锁定作为修复方案。Stage 34正式v34产品未改变。
- Stage 34c-2已完成TICS Pro profile冻结、控制面、自动campaign、152项Python回归及板端
  部署，并于2026-08-10 14:57 CST一次性提交systemd长任务。外部GPSDO MTS-only profile
  完成10/10 discovery和9次fixed-target后，第10次DAC四tile latency分裂为
  `[116,116,108,108]`，未达到新profile“四tile一致”资格；任务按门禁安全停止，分类为
  `STAGE34C2_OPERATIONAL_FAIL`，正式科学run为0，未自动重试。板端已恢复生产continuous
  profile、STOP、DAC全零、freeze=0和OCB1动态。后续若重提任务，脚本已增加逐轮资格
  checkpoint，失败轮次也会完整保留；本次结果不能用于判断SYSREF或参考源因果性。
- Stage 34c-2R已完成上述实验的硬件偏差修复和科学调查：候选`CORE_VERSION=0x00010035`先修复PL
  SYSREF的160 MHz IOB捕获及ADC/DAC 80 MHz独立重捕获，并增加三个物理边沿计数器；首个
  10 MHz诊断bit只用于routed datasheet和相位眼，不覆盖v34正式入口。软件回归与XSim
  18/18已通过。首轮route发现首级捕获未进IOB且全局WNS为`-0.186 ns`，该bit已拒绝上板；
  顶层IOB约束、PFB局部控制复制和更积极physical optimization修复后，Vivado invocation
  `stage34c2r-v35diag-r2-20260810T194600+0800`恢复全局WNS/WHS到`+0.005/+0.010 ns`，但
  XDC中的`if`不受支持导致IOB约束未执行，第二个bit仍被拒绝。改为合法无控制流XDC后，
  第三轮`stage34c2r-v35diag-r3-20260810T212700+0800`已完成，诊断bit SHA256为
  `2de23f7a731622a984e2602a267ac780a1e5cedafa644f32a27d3e7d5628b5e0`；全局WNS/WHS均为
  `+0.010 ns`，首级SYSREF捕获位于`BITSLICE_RX_TX_X0Y78`，PL到ADC/DAC重捕获setup/hold
  均通过。TICS Pro随后完整导出4个基础profile及10/5 MHz各32个LMK原生相位profile，
  首轮相位眼完成10 MHz全部32点并选择3000 ps中心，随后首版5 MHz profile因
  nested-zero-delay反馈已降为5 MHz、但`CLKin2_R=1`仍向PLL1提供10 MHz而正确拒绝；板端已
  安全恢复v34。修正版由TICS同时设置`SYSREF_DIV=480`、`CLKin2_R=2`，完整diff限定为
  `0x13a/0x13b/0x158`，manifest SHA256为`695308db...0d17009`，实机5 MHz预检通过。5 MHz
  32点补跑最终32/32点、128/128次尝试全部通过，选择与10 MHz相同的3000 ps中心；两种频率
  的保守通过宽度均为6008.333 ps。正式XDC已冻结为3000 ps中心及±120.834 ps相位量化包络，
  即`set_input_delay -min 2.879166 ns / -max 3.120834 ns`。最终v35候选Vivado invocation
  `stage34c2r-v35final-20260811T110554+0800`已在连接的GUI中完成完整
  synth→implementation/phys_opt/route→write_bitstream链。最终WNS/WHS为`+0.010/+0.010 ns`，
  SYSREF输入setup/hold为`+3.809/+0.830 ns`，首级位于`BITSLICE_RX_TX_X0Y78`，PL到ADC/DAC
  重捕获均通过，route error、严重DRC和TIMING-18均为0。隔离候选bit SHA256为
  `8934a0c2d7033494b49133d846f954b52a6fa76a54b65c043c6e7be5289728d1`，完整证据已导出到
  `build/board/latest/evidence/clock_sysref_causality/final_candidate_bit`。正式MTS/profile资格、
  负对照、短筛查及科学矩阵曾由用户级systemd单一长任务
  `t510-stage34c2r-v35-science.service`提交，有效invocation为
  `4a2b470adc2e4dbaa0a7b457a080c71d`（2026-08-11 14:14:02 CST）。隔离候选bit SHA已在板端
  复核，continuous-10-MHz的10/10 discovery全部完成且每轮四tile一致；但第一个fixed-target
  因ADC请求728在factor-12对齐到732后恰落本轮严格minimum边界而被RFDC拒绝，unit于14:27:48
  受控停止，fixed完成0/10、科学run为0。该MTS target计算运行故障未形成SYSREF科学结论，
  v34安全状态已恢复。target现按factor-12把nominal margin向上量化后再增加一个完整量化步：
  首次数据的ADC/DAC请求由728/208修正为744/228；边界测试和完整Python回归167项通过。
  r2完整队列已用unit `t510-stage34c2r-v35-science-r2.service`、invocation
  `630795b5b5764eb89ec018993b0b3ab7`于15:14:36 CST提交，独立证据位于
  `science_matrix/attempt_r2`。r2最终完成continuous和gated 10 MHz各10/10 discovery、10/10
  fixed，四tile分别精确回读744/228和756/252，证明target修复有效；但gated phase-15随后的
  request-low负对照被仍只接受旧无相位profile名的Rust/Python专用校验以HTTP 400拒绝。
  unit于15:54:28受控停止，5 MHz及科学run为0，不形成科学结论。Rust/Python现已统一接受
  10/5 MHz基础及phase-00..31外部request profile，并拒绝continuous、TCXO和非法phase；
  完整Python 169项、Cargo 8项通过，新ARM64 Agent SHA256为`bb46348a...cd23986d`。r3已用
  unit `t510-stage34c2r-v35-science-r3.service`、invocation
  `590633090c86456abac4ce1f7a6aaf6c`于16:33:44 CST提交，独立证据位于`attempt_r3`。r3完成
  continuous 10 MHz 10/10 discovery和10/10 fixed；gated 10 MHz的10轮discovery最大ADC仅708，
  target 744前5次fixed通过，但第6次最低可行latency跃迁到780而被RFDC拒绝，unit于17:09:34
  受控停止。负对照、5 MHz及科学run为0，不形成科学结论。该结果证明单次10轮discovery不能
  覆盖gated profile延迟包络。现已综合phase-eye与r1/r2/r3全部数据冻结target：continuous
  `768/228`、gated 10 MHz `816/252`、gated 5 MHz `1176/252`、TCXO `816/252`，策略SHA为
  `c39968a...49a3e7`；完整Python 171项、Cargo 8项通过。r4已用unit
  `t510-stage34c2r-v35-science-r4.service`、invocation
  `f42bbdc85f79469e8a81da0f0b3ff4c7`于18:14:44 CST提交。r4完成三个必需profile全部10+10资格、
  request-low负对照及16个短筛查，随后因低RF标称122.88 MHz不是精确PFB bin而安全停止。
  修复使用共同最近点`122.890625 MHz`（160/320 bin `-950/-475`）并以r4 campaign SHA严格
  断点验签。r5进一步暴露并修复低RF不存在fixed/grid分组时的空汇总；真实60秒raw离线重算
  成功，完整Python 175项通过。r6 unit `t510-stage34c2r-v35-science-r6.service`、invocation
  `c79e2b1ae0a340e2aa74532151d23b79`从r4资格/筛查后接续。r6最终完成SYSREF层18个和10/5 MHz
  频率层18个600秒run，全部数字门禁通过；TCXO因PLL1不锁按规则跳过。最终分析SYSREF层为
  `CLOCK_SYSREF_NOT_CAUSAL_UNDER_SHARED_50OHM`，频率层为`SYSREF_RATE_CONTRIBUTOR`，即5 MHz
  只有小幅改善而没有恢复`1/sqrt(N)`。r6随后仅因本机缺Matplotlib在最终出图停止；另3个
  320 MS/s低频上下文run因`159.9999999999909`边界的冗余DAC静音写被标失败。静音已改为先
  接受全零硬件回读，绘图改Pillow，完整Python 180项通过。r8 finalizer unit
  `t510-stage34c2r-v35-finalize-r8.service`、invocation `05909aeca6074d15a5db458f87b630af`
  已于2026-08-12 11:57:59 CST正常完成3个低频补采并离线闭合42个有效run。最终84份PCAP
  SHA256全部复核通过，CSV和3幅PNG已生成；`operational_ok=true`、`errors=[]`。最终分类为
  `CLOCK_SYSREF_NOT_CAUSAL_UNDER_SHARED_50OHM / SYSREF_RATE_CONTRIBUTOR /
  TCXO_PROFILE_UNQUALIFIED`：5 MHz只有弱方向性改善，没有恢复`1/sqrt(N)`，不能作为生产修复。
  v35未发布，板端已恢复v34、停流、DAC全零、freeze=0、OCB1动态和双PLL锁定。
  跨分支接续以34c-2R报告首部的`BRANCH_HANDOFF_STATUS`和唯一下一动作为准。
- Stage 34c-3已完成控制面、密集AMS resident遥测、receiver 3600秒monitor和自动campaign。
  两次预检分别暴露并修复启动瞬态基线及TIME聚合route合同；完整Python 191项、Board Agent
  8项和receiver 48项回归通过。正式队列完成9个输出负载600秒run；第一次160 MS/s 60分钟
  观察因用户中途关闭空调导致三路温度跨度7.6～7.7 °C，按5 °C环境异常线拒绝。空调恢复
  后，invocation `ec53e9a5785b449abd9c4be1b0626287`只补跑160/320两条60分钟run且全部通过。
  11个有效run的drop/gap/饱和/overflow均为0，22份有效PCAP及2份失败现场PCAP的SHA均通过。
  160/320离栅格点中位斜率分别为-0.0215/-0.0175、lag-1为0.834/0.852，均0/12合格，确认
  长积分相关噪声持续存在。TIME_SPEC相对SPEC_ONLY没有可逆改善，正式排除数字输出负载为
  主因；AMS温度/内部电压没有达到注册相关证据线。官方
  `XRFdc_Shutdown(DAC,-1)`使四个DAC tile进入关机过渡态后却在驱动restart-clear状态6超时，
  简单StartUp不能恢复，完整v34 CONFIGURE/MTS已恢复全部tile和生产安全状态。因此DAC tile
  层按注册规则冻结为`INTERVENTION_UNQUALIFIED`，不能把未执行的DAC层写成无因果。最终
  分类为`OUTPUT_LOAD_NOT_CAUSAL_DAC_TILE_INTERVENTION_UNQUALIFIED`；模拟轨亚毫伏纹波和
  主动热因果资格仍待后续仪器/实验。
- Stage 33a 已终止，状态为
  `TERMINATED / ACCEPTED_WITH_KNOWN_LIMITATIONS / NO_PRODUCTION_MITIGATION`，只作为来源
  分类和坏频点的冻结历史基线。
- DAC 的 20 MHz 栅格除 200 MHz 项外为 `-84.88..-91.26 dBc`；仪表噪声为
  `-95.84..-97.84 dBc`（1 kHz RBW），200 MHz 二次谐波为 `-61.88 dBc`。功能回环
  足够，不作为高动态范围频谱纯度源。
- ADC 在 480/960/1440 MHz 的 RFDC 固定项分别为 `-89.75..-85.00`、
  `-93.95..-88.23`、`-88.25..-82.64 dBFS`，最坏约 `2.42 ADU`。一般采集足够，
  三处邻近 bin 不适合长积分弱谱线或无条件互相关。
- 不得继续 Stage 33a 的 OCB1 override、notch、自适应抵消、
  前馈扣除或新 RTL 修复路线；如需重新研究，应另立阶段。

## Stage 32

- [32 总计划](32_stage32_master_plan.md)
- [32a LMK 160 MHz profile](32a_lmk160_profile_integration.md)
- [32b clock-only 板级门禁](32b_lmk160_clock_only_board_gate.md)
- [32c RFDC ADC/DAC 1.6 GS/s MTS](32c_rfdc_adc_dac_1p6g_mts.md)
- [32d 320 MS/s TIME_ONLY](32d_320msps_time_only.md)
- [32e 160 MS/s halfband TIME](32e_160msps_halfband80_time.md)
- [32f 160 MS/s SPEC dual](32f_160msps_spec_dual.md)
- [32g 320 MS/s SPEC_ONLY](32g_320msps_spec_only.md)
- [32h 单板发布与 soak](32h_single_board_release_soak.md)
- [32h1 外部 RF 频率轴](32h1_external_rf_frequency_axis.md)
- [32h2 DAC DDS I/Q 方向](32h2_dac_dds_iq_direction.md)
- [32h3 DAC 频谱纯度](32h3_dac_spectral_purity.md)
- [32i 多板物理闭合](32i_multiboard_physical_closure.md)

## Stage 33

- [33 RFDC ADC/DAC 3.84 GS/s 发布](33_rfdc_adc_dac_3p84g_release.md)
- [33a ADC 固定杂散定责与终止归档](33a_adc_fixed_spur_characterization_and_mitigation.md)

## Stage 34

- [34 全速固定 8-tap PFB 发布](34_fullrate_pfb8_release.md)
- [34a 面向天文观测的性能评估](34a_astronomy_performance_evaluation.md)
- [34b-1 RFDC 校准观测与安全冻结](34b-1_rfdc_calibration_control.md)
- [34b-2 训练冻结因果实验（原组失败；低RF扩展已终止）](34b-2_calibration_causality.md)
- [34b-3 显式校准产品化（未进入）](34b-3_calibration_productization.md)
- [34b-4 校准资格验证（未进入）](34b-4_calibration_qualification.md)
- [34c ADC0/ADC2共享50 Ω参考与OCB1因果调查](34c_adc_correlated_noise_root_cause.md)
- [34c-0 ADC0/ADC2共享50 Ω参考长积分实验](34c-0_adc02_shared_50ohm_reference.md)
- [34c-1 OCB1可逆因果实验（条件进入）](34c-1_ocb1_causality.md)
- [34c-2 时钟参考与SYSREF可逆因果调查](34c-2_clock_sysref_causality.md)
- [34c-2R PL SYSREF捕获修复与5 MHz调查（42个run闭合，v35未发布）](34c-2r_pl_sysref_capture_repair.md)
- [34c-3 板内负载、供电与热稳定性调查](34c-3_power_thermal_causality.md)
- [34c 后续根因调查总计划](34c_adc_correlated_noise_root_cause_plan.md)
- [34d Allan稳定性与八路复互相关评估](34d_allan_cross_correlation.md)

## 长任务规则

- 用户点名为长任务的构建链、MTS campaign、全速稳定性矩阵、长时间 soak 和循环门禁，
  必须一次性提交完整任务或完整队列。一个阶段成功后自动进入下一个阶段，不得在阶段之间
  等待用户再次下令；任一阶段失败才停止并保留现场与证据。
- 长任务完整提交并确认健康启动后立即停止等待、停止轮询并把控制权交回用户；不取消、
  不重复提交、不由另一进程接管，也不把中间进度当作完成。跨会话恢复或用户通知完成后，
  先检查原任务/队列的最终状态和证据，再按用户指令继续后续工作。

### T510 实验室板默认运维账号

- 当前实验室 PYNQ 默认镜像使用用户 `xilinx`，默认 sudo 密码与用户名相同，即
  `xilinx`。这是该实验室默认镜像的公开默认凭据，可供自动化发布通过
  `PYNQ_SUDO_PASSWORD` 使用；不得把这一规则外推到已修改密码、生产或非实验室设备。

### Vivado 构建链

- Vivado 综合、实现、物理优化、布线、`write_bitstream` 和报告生成只通过已 attach 的
  Vivado GUI MCP 执行；不启动 shell 后台 Vivado，不使用阻塞式 Tcl `wait_on_run`。
- “提交 Vivado 长任务”固定表示一次性武装完整的
  `synth_1 -> impl_1 (opt/place/phys_opt/route) -> write_bitstream` 链。综合成功后必须由
  同一 GUI 会话自动启动实现，实现成功后自动进入 `write_bitstream`；不得把只启动
  `synth_1`称为完成长任务提交，也不得在两个阶段之间等待用户再次下令。任一阶段失败则
  停止链并保留现场，不得继续使用旧结果。
- run 启动或阶段变化后按 `10s -> 20s -> 30s -> 60s` 轮询；确认健康且继续等待有价值时
  可逐级延长，单次最长 `600s`。
- 完整链健康启动并确认自动接续已武装后停止等待；不取消、不重复提交，也不由另一
  Vivado 进程接管。即使跨会话恢复，也必须先确认三段链是否已全部武装，不能只看到
  综合在跑就遗漏实现或 bitstream。
- 只有用户确认 GUI 已显示新 `write_bitstream Complete!` 或要求继续后，才检查最终 run
  状态、routed 时序、route status、DRC/methodology、bitstream 和报告，然后执行导出及
  后续工作。

## Stage 34 及以后

- `config/t510/`、`deploy/t510/`、顶层 `overlay/` 和稳定 `t510_*` 脚本原位更新。
- 构建、临时证据和发布包只使用固定 `build/*/latest` 路径并覆盖旧内容。
- 不创建 Stage 号目录、build/release ID、候选目录、时间戳副本或长期回滚树。
- 只有需要长期保留的工程结论写入新的 `reports/stages/<stage>_*.md`。
