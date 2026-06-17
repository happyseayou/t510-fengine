# Stage 17: RFDC SYSREF Coherence Lock

## 阶段目标

把 Stage 16 已定位到 RFDC/analog/clock/adapter 路径的相位/幅度不稳定继续推进到可修复、可验收的门禁：Jupyter `Sample0-aligned measured RF scope` 稳定，TIME/SPEC dry-run UDP payload witness 也稳定。

本阶段允许 RTL、Python、notebook 和 bitstream 更新；`CORE_VERSION` bump 到 `0x0001000A`。Stage 17 仍不接 QSFP live，不移动 DAC0->ADC0 线缆。严格验收阈值保持为 phase residual p-p `<= 3 deg`、幅度 p-p `<= 5%`、无 clipping/large-event 污染。

## 完成内容

- RFDC deterministic init:
  - 新增 `apply_sysref_locked_observation_config(...)`，作为 notebook 13 和 Stage 17 smoke 的观测初始化入口。
  - 初始化流程按 SYSREF/MTS 锁定语义执行：TCXO/LMK 配置、RFDC ADC/DAC MTS init/sync、mixer `EventSource=SYSREF`、NCO phase reset、SYSREF receiver/event update、随后关闭 SYSREF。
  - 新增 `read_rfdc_sync_status()`，读回 RFDC API 可用性、mixer settings、可用方法列表和上次 SYSREF lock 结果；如果板端 `xrfdc`/MTS API 不可用，明确报 `RFDC_SYSREF_API_UNAVAILABLE`，不回退到旧流程假通过。
  - 板端适配修正：`configure_clock()` 返回 LMK 配置结果；RFDC 未启用 block 的 `MixerSettings` 读取失败记为 skipped；`MixerSettings.EventSource=SYSREF` 时不再调用 block `UpdateEvent()`，改为外部 SYSREF event 语义。
- RTL/sample0:
  - `rfdc_adc_axis_adapter` 增加 64-bit `m_axis_sample0`，定义为 full-rate `sample_count << 2`。
  - `axis_stream_duplicator` 传递 64-bit sample0 sideband。
  - TIME/SPEC packetizer header sample0 由 RFDC full-width sideband 提供，不再依赖 32-bit `tuser` 重建。
  - mode/stop/soft reset/tx clear 时显式 reset packetizer、PFB、FIFO、route、frame builder 和 witness state。
- paired coherence witness:
  - `0x07d8..0x07ff` 新增 paired coherence readback，包含 source sample0、preview sample0、header sample0、sample0 delta、RFDC flags 和 witness/preview 状态。
  - `tx_payload_witness_capture` 的 data-path clear 只清 stale valid/capturing，不再取消已 armed 状态；软件显式 clear 仍会 disarm。这样可以支持“先 arm witness，再 start/mode switch”的实际操作。
- Python/Jupyter:
  - 新增 `scripts/pynq_rfdc_sysref_coherence_lock_check.py`，一次运行 SYSREF lock、Jupyter preview 等价采样、paired capture、TIME/SPEC payload witness，并输出严格 PASS/FAIL 分类。
  - notebook 13 更新 `EXPECTED_CORE_VERSION=0x0001000A`，Apply/Init 改用 `apply_sysref_locked_observation_config(...)`。
  - notebook 13 高级状态显示 `RFDC_SYSREF_LOCK`、paired witness valid、paired preview done 和 sample0 delta。

## 本地验证

已通过：

```bash
python3 -m py_compile python/t510_fengine.py scripts/pynq_rfdc_sysref_coherence_lock_check.py scripts/pynq_rfdc_udp_coherence_audit.py
python3 -m json.tool notebooks/13_astronomer_rf_observation_console.ipynb >/dev/null
./scripts/run_xsim_batch.sh tb_rfdc_fullrate_preview tb_time_packetizer tb_spectral_packetizer tb_tx_payload_witness_capture tb_t510_fengine_top_smoke
./scripts/run_xsim_batch.sh tb_axis_stream_duplicator tb_rfdc_adc_axis_adapter tb_feng_ctrl_axi tb_axi4_to_axil_bridge
```

XSim 覆盖点：

- RFDC adapter full-width sample0 输出和 preview sample0 对齐。
- TIME/SPEC header sample0 等于输入 packet/window 第一个 RFDC sample0。
- TX payload witness stream filter/header/payload capture 正常，不反压 AXIS。
- witness arm 能跨 epoch/mode data clear 保留，避免 Stage 16 的 per-condition overlay reload workaround。
- AXI readback `CORE_VERSION=0x0001000A` 和 paired coherence register map 可读。

## Vivado/PYNQ 状态

Vivado gate 已完成：

- synthesis: `0 errors / 0 critical warnings`。
- implementation: `READY`，route complete，`WNS=+1.957 ns`，`WHS=+0.013 ns`，失败端点 `0/134809`。
- bitstream: `write_bitstream completed successfully`，`0 errors / 0 critical warnings`。
- overlay export:
  - `overlay/t510_fengine.bit` SHA256 `c053ab7c2834a2ef11e0cbc00d7a9dd62a0cd06d289bdfec233d2f32e9f81cc7`
  - `overlay/t510_fengine.hwh` SHA256 `95fd94741fc83ac4d4d94f330e1032eb90bc54a63462c3f46aeb8935ac6b700b`
  - manifest points at `/home/astrolab/demo-ant/overlay/t510_fengine.bit`

PYNQ strict gate 已执行，结果为 `FAIL`，`data_quality_gate=BLOCK_QSFP_LIVE_DATA_QUALITY`。板端 overlay 读回：

- `CORE_VERSION=0x0001000A`
- `UDP_DRY_RUN=1`
- `QSFP_LINK_UP=0`
- overlay bit SHA256 与本地一致：`c053ab7c2834a2ef11e0cbc00d7a9dd62a0cd06d289bdfec233d2f32e9f81cc7`

严格门禁命令：

```bash
sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_rfdc_sysref_coherence_lock_check.py --center-mhz 100 --signals-mhz 119.2,130.24,130,100 --modes time,spec --samples 512 --frames 240 --strict-phase-pp-deg 3 --strict-amplitude-pp-percent 5 --timeout 2.0
```

实际板端先运行了 quick evidence gate，用于避免在已知前置失败时浪费完整 240 帧：

```bash
sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_rfdc_sysref_coherence_lock_check.py --center-mhz 100 --signals-mhz 119.2 --modes time,spec --samples 512 --frames 5 --strict-phase-pp-deg 3 --strict-amplitude-pp-percent 5 --timeout 2.0
sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_rfdc_sysref_coherence_lock_check.py --center-mhz 100 --signals-mhz 119.2 --modes spec --samples 512 --frames 3 --strict-phase-pp-deg 3 --strict-amplitude-pp-percent 5 --timeout 2.0
```

板端分类和证据：

- `classification=RFDC_SYSREF_API_UNAVAILABLE`
- `data_quality_gate=BLOCK_QSFP_LIVE_DATA_QUALITY`
- LMK full lock 不完整：`pll1_lock=0`、`pll2_lock=1`、`reg6=32`、`configured=false`
- 当前 PYNQ `xrfdc.RFdc` 无 `MTS_Sysref_Config` / `MultiConverter_Init` / `MultiConverter_Sync` 方法；底层 `libxrfdc.so` 也未暴露 MTS/SYSREF C 符号。
- 可用 RFDC block API 只有 `MixerSettings`、`ResetNCOPhase`、`UpdateEvent`；当 mixer `EventSource=SYSREF` 时 driver 明确禁止 `UpdateEvent(EVENT_MIXER)`，提示应由外部 SYSREF 触发。
- quick TIME 5 帧：preview phase p-p `251.41 deg`，payload phase p-p `156.34 deg`；preview amplitude p-p `146.87%`，payload amplitude p-p `153.46%`；`sample0_delta_unique_count=5`。
- quick SPEC-only 3 帧：preview phase p-p `169.35 deg`，payload phase p-p `152.96 deg`；preview amplitude p-p `197.70%`，payload amplitude p-p `92.35%`；`sample0_delta_unique_count=3`。
- clipping/large-event count 为 0；失败不是由 clipping 帧污染造成。
- SPEC-only 能抓到 witness；time->spec 连续 quick 中 SPEC witness timeout，说明仍存在 mode/state/witness sequencing 风险，但不是唯一阻塞项。

通过条件：

- `CORE_VERSION=0x0001000A`。
- RFDC SYSREF/MTS lock PASS；ADC/DAC mixer event source 读回为 SYSREF。
- Jupyter preview/sample0-aligned phase p-p `<= 3 deg`，幅度 p-p `<= 5%`。
- TIME/SPEC payload phase p-p `<= 3 deg`，幅度 p-p `<= 5%`。
- header/source/preview sample0 delta 固定，或报告中有确定 latency 解释。
- 不再需要 per-condition overlay reload；mode switch 后 witness 正常。

当前未通过条件，严禁放行 QSFP live science data。下一步优先级：

1. 解决 RFDC deterministic sync 前置：更换/升级 PYNQ `xrfdc`/RFDC driver，使 MTS API 可用，或提供经验证的寄存器级 MTS/SYSREF 实现；同时查 LMK PLL1 lock 为 0 的原因。
2. 在 MTS/LMK 前置可验证后，复跑完整 240 帧 strict gate。
3. 若前置通过后 phase/amplitude 仍抖，再进入 RFDC/analog/clock path；若 preview 稳定 payload 不稳，再查 packetizer/FIFO/route/witness。
4. 独立修 `time->spec` 连续切换时偶发 SPEC witness timeout。

## 阶段衔接说明

下一阶段可依赖：

- Stage 17 的 local RTL/software gate 已闭合。
- notebook 13 的推荐入口已切到 SYSREF-locked observation init。
- payload witness、preview status 和 paired sample0 readback 可以作为 QSFP 前数据质量门禁证据。
- Stage 17 板端 quick evidence 已证明当前不满足严格稳定性阈值，且 RFDC MTS API/LMK full lock 是前置阻塞。

下一阶段不能依赖：

- 未通过 Stage 17 板端严格门禁前，不能放行 QSFP live science data。
- 当前 PYNQ 镜像的 `xrfdc` 不可直接依赖 MTS API。
- `UDP_DRY_RUN=1`、`QSFP_LINK_UP=0` 在无 QSFP live 条件下仍是预期状态。
- CH0 DAC0->ADC0 仍是唯一 analog verified 通道；CH1..CH7 不能作为本阶段稳定性验收依据。

## AI 接续提示

- 不要降低 `3 deg / 5%` 严格阈值；若不达标，保留阻塞结论。
- 如果板端返回 `RFDC_SYSREF_API_UNAVAILABLE`，先根据 `read_rfdc_sync_status()` 暴露的方法列表修正 PYNQ `xrfdc` MTS API 适配，不要用旧 NCO update 流程假通过。
- 如果 SYSREF lock PASS 但 preview 与 payload 同步抖动，按 `RFDC_ANALOG_CLOCK_PATH_UNSTABLE` 推进硬件/clock/RFDC path；如果 preview 稳定而 payload 不稳定，再查 packetizer/FIFO/route/witness。
- 不要在报告、脚本或 notebook 中记录 SSH 明文密码。
