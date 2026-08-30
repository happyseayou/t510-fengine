# T510 F-engine

本仓库维护 T510 当前唯一版本。Stage 35 以已验证的 v34 作为唯一 FPGA 基线；当前合同为
`CORE_VERSION=0x00010034`：ADC/DAC 均为 `3.84 GS/s`、12×抽取/插值，复基带为
`320 MS/s`，ADC/DAC AXIS 时钟为 `80 MHz`。SPEC 使用固定 4096 通道、8-tap
Hamming-windowed sinc PFB；TIME/SPEC 协议、UDP 端口和 `/api/v2` 保持稳定。

## 当前性能边界

- DAC 足够用于通道映射、频率、同步和强信号回环。100 MHz 主音经约 20 dB
  低噪放后为 `3.84 dBm`；除 200 MHz 二次谐波外，20 MHz 栅格为
  `-84.88..-91.26 dBc`，仪表噪声约 `-95.84..-97.84 dBc`（1 kHz RBW）。
  200 MHz 项为 `-61.88 dBc`，未拆分 DAC 与低噪放贡献。它不是高动态范围纯度源。
- ADC 足够用于一般宽带功率、时域波形、吞吐和防 clip 验证。RFDC 内部固定杂散位于
  480/960/1440 MHz，范围分别为 `-89.75..-85.00`、`-93.95..-88.23`、
  `-88.25..-82.64 dBFS`，最坏约 `2.42 ADU`。这些邻近 bin 不用于长积分弱谱线或
  无条件互相关。
- Stage 33a 已按
  `TERMINATED / ACCEPTED_WITH_KNOWN_LIMITATIONS / NO_PRODUCTION_MITIGATION`
  终止；这些结论作为 Stage 34a 的来源分类基线，不因升级 8-tap PFB 而被隐藏。
- 当前正式产品已经升级为 Stage 34 固定 8-tap PFB；bitstream SHA-256 为
  `c21d93f5ea71e9ac17a4448cff138a8faaf9c7347d879be919b680d196b8a5be`，MTS target
  为 ADC/DAC `416/112`。Stage 34a 只评估天文性能，不修改这份数字产品。
- Board Agent 的 CONFIGURE 可显式选择 `onboard_tcxo` 或 `external_10mhz`。Stage 35
  单板噪声研究使用板载 TCXO、free-run 相对采样时间，不需要外部 WR 的 10 MHz 或 PPS；
  后续多天线干涉再恢复共同参考和 PPS。

完整结论见 [Stage 33a 报告](reports/stages/33a_adc_fixed_spur_characterization_and_mitigation.md)。

## 稳定入口

- Python 控制：`python.t510_control.FEngineController`
- Jupyter 控制台：`python.t510_console.create_console`
- Board Agent：`rust/t510_board_agent`
- TIME/SPEC 接收机：`rust/t510_time_rx`
- 当前配置：`config/t510/`
- 当前部署资产：`deploy/t510/`
- Vivado 工程准备：`scripts/t510_prepare_current_project.tcl`
- Vivado 产物导出：`scripts/t510_export_current_project.tcl`
- 导出验证并更新顶层 overlay：`scripts/t510_build_latest.sh`
- 板端发布：`scripts/t510_publish_board.sh`
- 接收机发布：`scripts/t510_publish_receiver.sh`
- 全带杂散扫描：`scripts/t510_fullband_spur_scan.py`
- 天文自动性能评估：`scripts/t510_astronomy_performance.py`
- 时钟/SYSREF因果campaign：`scripts/t510_clock_sysref_causality.py`
- 板内负载/供电/热稳定性campaign：`scripts/t510_power_thermal_causality.py`
- 人工 SSA TG 入口：`scripts/t510_astronomy_tg.py`
- MTS：`scripts/pynq_t510_mts_campaign.py`
- 八路功能回环：`scripts/pynq_t510_8lane_loopback.py`
- 板端/主机联合门禁：`scripts/t510_board_host_gate.py`
- 冷启动门禁：`scripts/t510_cold_start_gate.py`
- 部署说明：[docs/t510_pynq_deployment.md](docs/t510_pynq_deployment.md)
- UDP 合同：[docs/t510_udp_payload_v2.md](docs/t510_udp_payload_v2.md)

## 当前 PFB 合同

- 固定 `4096` 通道、`8` tap、8 路复数 IQ16 输入，不提供 4/8-tap 运行时切换。
- 原型滤波器为对称 Hamming-windowed sinc，共 `32768` 个有符号 Q1.17 系数；
  每个 phase 的系数和精确为 `131072`。
- 当前 profile ID 为 `0x34a80001`，IEEE/zlib CRC32 为 `0xb9ba227c`。
- 8 tap 在 322.265625 MHz CMAC 时钟内完全并行计算，160/320 MS/s 的输出包率、
  FFT 布局和 UDP payload 不变。
- 群时延为 16383.5 个所选采样率样本，即 320 MS/s 时约 51.198 us，160 MS/s
  时约 102.397 us；`sample0` 仍表示窗口中最早输入帧。
- `PFB_TILE_OVERFLOW_COUNT` 现表示发生任一 IQ16 FIR 饱和的 PFB cell 数；软件同时
  以 `fir_saturation_count` 对外报告，正式门禁要求为零。

## Latest-only 规则

Stage 35 及以后继续原位更新当前版本，不创建带 Stage 号的配置、部署目录、构建脚本、
发布脚本或临时目录。只有 `reports/stages/*.md` 使用 Stage 名称记录工程结论。

- 顶层 `overlay/` 是运行和发布使用的唯一当前 bitstream；验证后的 Vivado 导出原子覆盖它。
- Vivado、板端包和接收机包只写入 `build/vivado/latest`、`build/board/latest` 和
  `build/receiver/latest`；每次执行精确覆盖，不生成 build ID、release ID、候选目录、
  时间戳副本、软链接或长期回滚树。
- 临时板测证据只写入相应 `build/*/latest/evidence/` 并允许下次执行覆盖；需要长期保留的
  方法、数值和限制必须固化到 Stage 报告。
- 板端和接收机固定安装到 `/opt/t510-agent/current` 与
  `/opt/t510-time-rx/current`。安装使用 `.current.next` 完成校验和事务切换，成功后删除
  临时旧目录及 `releases/`。
- `config/t510/`、`deploy/t510/` 和稳定 `t510_*` 脚本始终表示当前版本；推进 Stage 35
  时直接更新这些入口，不复制或改名。

## 强制操作规则

长任务、Vivado 构建链及 T510 实验室板默认运维账号的唯一权威规则见
[T510 仓库宪法](AGENTS.md)。执行相关操作前必须先阅读该文件；README 不再维护规则副本。

## 验证

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
cargo test --manifest-path rust/t510_board_agent/Cargo.toml
cargo test --manifest-path rust/t510_time_rx/Cargo.toml
scripts/run_xsim_batch.sh
python3 scripts/check_repository_hygiene.py
```

Vivado 运行由 [T510 仓库宪法](AGENTS.md) 的长任务规则单独管理；本地回归不得隐式启动
Vivado。

## 阶段报告

活动索引只保留 Stage 32 以后：

- [Stage 32 总计划](reports/stages/32_stage32_master_plan.md)
- [Stage 32 单板发布收口](reports/stages/32h_single_board_release_soak.md)
- [Stage 33 3.84 GS/s 发布](reports/stages/33_rfdc_adc_dac_3p84g_release.md)
- [Stage 33a ADC 固定杂散终止归档](reports/stages/33a_adc_fixed_spur_characterization_and_mitigation.md)
- [Stage 34 全速固定 8-tap PFB](reports/stages/34_fullrate_pfb8_release.md)
- [Stage 34c-2 时钟参考与SYSREF因果调查](reports/stages/34c-2_clock_sysref_causality.md)
- [Stage 35 v34 基线统一](reports/stages/35_v34_baseline.md)
- [Stage 35 射电天文噪声研究方案](STAGE35_RADIO_ASTRONOMY_NOISE_STUDY_PLAN.md)

更早报告统一位于 `reports/stages/arch/`，不再列入顶层活动索引。
