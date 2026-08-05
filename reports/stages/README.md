# T510 F-engine 阶段报告

本目录根部只保留 Stage 32 及以后报告；Stage 31 及更早内容统一归档在 `arch/`，不再作为
当前接续入口。运行产物、配置、部署和脚本均遵循 latest-only，只有本目录报告使用 Stage
名称。

## 最新状态

- Stage 33a 已终止，状态为
  `TERMINATED / ACCEPTED_WITH_KNOWN_LIMITATIONS / NO_PRODUCTION_MITIGATION`。
- DAC 的 20 MHz 栅格除 200 MHz 项外为 `-84.88..-91.26 dBc`；仪表噪声为
  `-95.84..-97.84 dBc`（1 kHz RBW），200 MHz 二次谐波为 `-61.88 dBc`。功能回环
  足够，不作为高动态范围频谱纯度源。
- ADC 在 480/960/1440 MHz 的 RFDC 固定项分别为 `-89.75..-85.00`、
  `-93.95..-88.23`、`-88.25..-82.64 dBFS`，最坏约 `2.42 ADU`。一般采集足够，
  三处邻近 bin 不适合长积分弱谱线或无条件互相关。
- 当前正式 bit SHA-256 为
  `23c3eb507558820e786dd7247b6b43a59a2f3141ed3599d1f6655f19de5dd3da`，
  `CORE_VERSION=0x00010033`，MTS target 为 `452/88`。Stage 33 保持
  `LATEST_PROMOTED / RELEASE_DEPLOYED / PRODUCTION_60S_PASS / RF_PARTIAL`。
- 推荐接续入口为 Stage 34。不得继续 Stage 33a 的 OCB1 override、notch、自适应抵消、
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

## 长任务规则

- Vivado 综合、实现、物理优化、布线、`write_bitstream` 和报告生成只通过已 attach 的
  Vivado GUI MCP 执行；不启动 shell 后台 Vivado，不使用阻塞式 Tcl `wait_on_run`。
- run 启动或阶段变化后按 `10s -> 20s -> 30s -> 60s` 轮询；确认健康且继续等待有价值时
  可逐级延长，单次最长 `600s`。
- 健康的长任务只确认已启动并记录阶段，然后停止等待；不取消、不重复提交，也不由另一
  Vivado 进程接管。
- 用户确认完成或要求继续后，再检查 run 状态、时序、route status、DRC/methodology、
  bitstream 和报告；新阶段重新从短间隔开始。

## Stage 34 及以后

- `config/t510/`、`deploy/t510/`、顶层 `overlay/` 和稳定 `t510_*` 脚本原位更新。
- 构建、临时证据和发布包只使用固定 `build/*/latest` 路径并覆盖旧内容。
- 不创建 Stage 号目录、build/release ID、候选目录、时间戳副本或长期回滚树。
- 只有需要长期保留的工程结论写入新的 `reports/stages/<stage>_*.md`。
