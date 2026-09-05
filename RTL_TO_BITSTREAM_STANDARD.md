# RTL 到 bitstream 标准流程

1. 修改 RTL 时同步更新 `config/t510/current_release.json` 中的 core、数字尺度和 FFT/PFB
   字段；生成 bitstream 后填入实际 SHA-256。catalog 始终只有 `fengine-current`，新硬件
   身份的两类参考源资格先置为 `pending`。
2. 先运行快速 RTL 单元测试和定点模型。真实 XFFT/IP 仿真只保留少量接口、sample0、边界、
   舍入和饱和用例；大规模统计比较使用 AMD 官方位精确模型。真实 IP 长仿真遵守
   `AGENTS.md` 的长任务规则。
3. 在已 attach 的 Vivado GUI 中 source `scripts/t510_timing_closure.tcl`，一次性武装
   `synth_1 -> impl_1 -> write_bitstream`。任一阶段失败即停止并保留报告。
4. 用户确认 GUI 完成后，检查 routed setup/hold、route status、DRC 和 methodology；
   `scripts/t510_pre_bitstream_gate.tcl` 必须通过。
5. 在同一 GUI 中 source `scripts/t510_export_current_project.tcl`，导出到
   `build/vivado/latest`。运行 `scripts/t510_build_latest.sh` 校验身份、RFDC XCI/HWH、摘要和
   SHA，并直接更新顶层 `overlay/`。
6. 不建立候选、previous 或 releases 目录。发现问题就修改 current 并重新完成本流程。

导出后必须继续执行 [上板发布与资格标准](BOARD_RELEASE_QUALIFICATION_STANDARD.md)。
