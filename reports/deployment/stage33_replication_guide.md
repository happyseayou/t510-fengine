# Stage 33 单板发布与证据归档指南

## 发布边界

Stage 33 使用现有服务名 `t510-agent`、`t510-ref-watchdog`、`t510-time-rx` 和 API v1，
但 release 和配置必须来自独立留档的 `config/stage33/` 与 `deploy/stage33/`。
Vivado 直接复用当前 `demo-ant.xpr`；`build/stage33-vivado/` 只是从当前工程导出的
Stage 33 artifact snapshot，不是第二个工程。不得覆盖或删除 Stage 32 release、
cache 或报告。

当前 `config/stage33/config.example.json` 是故障关闭模板，不是可部署 catalog。
zero SHA、负 MTS target 或缺少 campaign proof 时，发布和安装脚本必须失败。

## 证据闭合顺序

1. 在当前 `demo-ant.xpr` 中按 `reports/stages/README.md` 的 Vivado GUI MCP 协议
   source `scripts/build_stage33.tcl`，使用既有 `synth_1/impl_1` 生成 Stage 33
   bitstream；source `scripts/export_stage33_current_project.tcl` 将成品和报告归档到
   `build/stage33-vivado/<build-id>/` 与 `reports/vivado/stage33/<build-id>/`。
2. 在板端运行 discovery：

   ```bash
   python3 scripts/pynq_stage33_mts_campaign.py --phase discovery \
     --output reports/board/stage33_mts_discovery.json
   ```

3. 使用 discovery 报告运行 fixed：

   ```bash
   python3 scripts/pynq_stage33_mts_campaign.py --phase fixed \
     --discovery-json reports/board/stage33_mts_discovery.json \
     --output reports/board/stage33_mts_fixed.json
   ```

4. 在仓库根目录固化唯一 catalog：

   ```bash
   python3 scripts/stage33_finalize_catalog.py \
     --discovery-json reports/board/stage33_mts_discovery.json \
     --fixed-json reports/board/stage33_mts_fixed.json
   ```

finalizer 必须核对两个阶段各40/40、20/10/10动作分布、新 target 为 discovery
ADC max+20/DAC max+16、fixed latency/offset vector可重复、bit SHA一致，且 target
不是 Stage 32 的230/336。

## 构建和安装 release

catalog 固化后才允许构建或安装：

```bash
scripts/pynq_publish_stage33.sh --build-only
scripts/host_publish_stage33_rx.sh --build-only
scripts/pynq_publish_stage33.sh --install
scripts/host_publish_stage33_rx.sh --stage-remote
```

接收机脚本只把 release staged 到远端；按它输出的命令在接收机上显式安装。sudo
凭据只允许交互输入或通过临时环境提供，禁止写入仓库、报告或命令行日志。

## 发布后门禁

使用唯一 tag 运行并保留原始 JSON：

```bash
scripts/pynq_stage33_rf_campaign.py --tag candidate1
scripts/stage33_dac_purity_matrix.py --tag candidate1
scripts/stage33_release_matrix.py --suite smoke_60s --tag candidate1
scripts/stage33_release_matrix.py --suite soak_10m --tag candidate1
scripts/stage33_cold_start_gate.py --tag candidate1
scripts/stage33_release_matrix.py --suite thermal_60m --tag candidate1
```

所有脚本默认写入 `reports/board/`，并拒绝覆盖同名证据。dry-run仅用于检查命令矩阵，
不能作为验收结果。任何失败均先停止 science、mute DAC、保存报告，不得降低门限、
复用 Stage 32 MTS target 或改写 SHA 绕过 catalog。

## 回滚

回滚使用保留的 Stage 32 catalog、release和bitstream，按 Stage 32 固定顺序重新执行
LMK profile、fresh overlay、RFDC init/MTS和数据面门禁。不要把 Stage 32 target 或
bit SHA 写回 Stage 33 catalog，也不要删除失败的 Stage 33 原始证据。
