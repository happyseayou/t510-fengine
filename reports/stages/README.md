# T510 阶段报告

这里仅索引仍在活动维护范围内的 Stage 34、Stage 35 有效报告和 Stage 36 报告。
Stage 00–33 已移入 [`archive/00-33/`](archive/00-33/)，Stage 35 的 09–11 与原总研究
计划已移入 [`archive/35/`](archive/35/)。`reports/arch/` 是硬件架构资料，不属于 Stage
报告归档。

当前正式产品为 `CORE_VERSION=0x00010036`，bitstream SHA-256 为
`e00c586a1d862d7c7af113361832a30093334493e49f943e3dd22bf44f950665`。Stage 36 R10 的
板载 TCXO MTS 40/40、固定目标 40/40、五个全速模式和短幅值门禁均为 PASS；900 秒科学
采集尚未启动。外部 10 MHz＋PPS 标准资格保持 pending。

## Stage 34

- [34 固定 8-tap PFB 发布](34_fullrate_pfb8_release.md)
- [34a 天文性能评估](34a_astronomy_performance_evaluation.md)
- [34b-1 RFDC 校准控制](34b-1_rfdc_calibration_control.md)
- [34b-2 校准因果实验](34b-2_calibration_causality.md)
- [34b-3 校准产品化](34b-3_calibration_productization.md)
- [34b-4 校准资格](34b-4_calibration_qualification.md)
- [34c 相关噪声根因计划](34c_adc_correlated_noise_root_cause_plan.md)
- [34c-0 共享 50 Ω 实验](34c-0_adc02_shared_50ohm_reference.md)
- [34c-1 OCB1 因果实验](34c-1_ocb1_causality.md)
- [34c-2 时钟与 SYSREF](34c-2_clock_sysref_causality.md)
- [34c-2R PL SYSREF 修复](34c-2r_pl_sysref_capture_repair.md)
- [34c-3 电源与热稳定性](34c-3_power_thermal_causality.md)
- [34d Allan 与互相关](34d_allan_cross_correlation.md)
- [34e 交织杂散补偿](34e_adc_interleave_spur_correction.md)
- [34f 前端定位结题](34f_closure.md)

## Stage 35

- [35 current 前硬件基线](35_v34_baseline.md)
- [35 分步执行索引](35_00_execution_index.md)
- [35-01 设计审查](35_01_s0_design_review.md)
- [35-02 累加器与 writer](35_02_s0_fullband_accumulator_implementation.md)
- [35-03 replay 验证](35_03_s0_replay_validation.md)
- [35-04 60 秒烟雾采集](35_04_s0_60s_smoke.md)
- [35-05 TIME ADU 控制](35_05_s1_time_adu_control.md)
- [35-06 50 Ω SPEC 基线](35_06_s2_50ohm_spec_baseline.md)
- [35-07 自相关分析](35_07_autocorrelation_analysis.md)
- [35-08 HTML 科学报告](35_08_self_contained_html_report.md)
- [35-12 28 基线干涉测量](35_12_s5_interferometry.md)

## Stage 36

- [36 执行索引](36_00_execution_index.md)
- [36-01 Stage 35 经验审计](36_01_stage35_lessons_audit.md)

## 历史归档

- [Stage 00–33](archive/00-33/)
- [Stage 35 的 09–11 与研究计划](archive/35/)

强制长任务和 Vivado 规则见 [AGENTS.md](../../AGENTS.md)。
