# T510 阶段报告

这里仅索引仍在活动维护范围内的 Stage 35 有效报告和 Stage 36 报告。
Stage 00–33 已移入 [`archive/00-33/`](archive/00-33/)，Stage 34 已移入
[`archive/34/`](archive/34/)，Stage 35 的 09–11 与原总研究计划已移入
[`archive/35/`](archive/35/)。`reports/arch/` 是硬件架构资料，不属于 Stage 报告归档。

当前正式产品为 `CORE_VERSION=0x00010036`，bitstream SHA-256 为
`e00c586a1d862d7c7af113361832a30093334493e49f943e3dd22bf44f950665`。Stage 36 R10 的
板载 TCXO MTS 40/40、固定目标 40/40、五个全速模式和短幅值门禁均为 PASS；900 秒科学
采集、独立复算与 `8036` 技术验收均已完成。外部 10 MHz＋PPS 标准资格也已通过。

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
- [36-02 科学复评与 8036 交付](36_02_science_evaluation.md)

## 历史归档

- [Stage 00–33](archive/00-33/)
- [Stage 34](archive/34/)
- [Stage 35 的 09–11 与研究计划](archive/35/)

强制长任务和 Vivado 规则见 [AGENTS.md](../../AGENTS.md)。
