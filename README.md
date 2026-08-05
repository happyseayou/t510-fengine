# T510 F-engine

本仓库维护 T510 当前唯一版本。当前 FPGA 合同为
`CORE_VERSION=0x00010033`：ADC/DAC 均为 `3.84 GS/s`、12×抽取/插值，复基带为
`320 MS/s`，ADC/DAC AXIS 时钟为 `80 MHz`。TIME/SPEC 协议、UDP 端口、Rust 接收机
和 `/api/v2` 保持稳定。

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
  终止；Stage 33 总体为 `RF_PARTIAL`，满足当前工程和功能验证用途。

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
- MTS：`scripts/pynq_t510_mts_campaign.py`
- 八路功能回环：`scripts/pynq_t510_8lane_loopback.py`
- 板端/主机联合门禁：`scripts/t510_board_host_gate.py`
- 冷启动门禁：`scripts/t510_cold_start_gate.py`
- 部署说明：[docs/t510_pynq_deployment.md](docs/t510_pynq_deployment.md)
- UDP 合同：[docs/t510_udp_payload_v2.md](docs/t510_udp_payload_v2.md)

## Latest-only 规则

Stage 34 及以后继续原位更新当前版本，不创建带 Stage 号的配置、部署目录、构建脚本、
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
- `config/t510/`、`deploy/t510/` 和稳定 `t510_*` 脚本始终表示当前版本；推进 Stage 34
  时直接更新这些入口，不复制或改名。

## Vivado 长任务规则

- 综合、实现、物理优化、布线、`write_bitstream` 和报告生成只通过已 attach 的 Vivado
  GUI MCP 执行；不启动 shell 后台 Vivado，不使用阻塞式 Tcl `wait_on_run`。
- run 启动或阶段变化后按 `10s -> 20s -> 30s -> 60s` 轮询；确认持续健康且等待仍有价值时，
  可逐级延长，单次最长 `600s`。
- 对健康的长任务，只确认已经启动并记录当前阶段，然后停止等待；不取消、不重复提交，
  也不由另一个 Vivado 进程接管。
- 用户确认完成或要求继续时，再通过同一 GUI MCP 检查 run 状态、时序、route status、
  DRC/methodology、bitstream 和报告；进入新阶段后重新从短间隔开始。

## 验证

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
cargo test --manifest-path rust/t510_board_agent/Cargo.toml
cargo test --manifest-path rust/t510_time_rx/Cargo.toml
scripts/run_xsim_batch.sh
python3 scripts/check_repository_hygiene.py
```

Vivado 运行由上述长任务规则单独管理；本地回归不得隐式启动 Vivado。

## 阶段报告

活动索引只保留 Stage 32 以后：

- [Stage 32 总计划](reports/stages/32_stage32_master_plan.md)
- [Stage 32 单板发布收口](reports/stages/32h_single_board_release_soak.md)
- [Stage 33 3.84 GS/s 发布](reports/stages/33_rfdc_adc_dac_3p84g_release.md)
- [Stage 33a ADC 固定杂散终止归档](reports/stages/33a_adc_fixed_spur_characterization_and_mitigation.md)

更早报告统一位于 `reports/stages/arch/`，不再列入顶层活动索引。
