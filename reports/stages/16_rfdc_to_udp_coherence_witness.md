# Stage 16: RFDC-to-UDP Coherence Witness

## 阶段目标

同时定位 `Sample0-aligned` 相位/幅度抖动来源，并证明该抖动是否进入 TIME/SPEC dry-run UDP payload。

本阶段允许 RTL 修改、重新综合实现并导出 overlay；`CORE_VERSION` bump 到 `0x00010009`。Stage 16 不接 QSFP live，不移动 DAC0->ADC0 线缆。如果数据不稳定，阶段结论应是证据链执行完成但 `BLOCK_QSFP_LIVE_DATA_QUALITY`，而不是把脚本本身判为失败。

## 输入基线

- Stage 15 已证明 `internal_dds`、`sample_index_ramp`、preview double-read、event buffer double-read 和 DAC phase commit 均 PASS；RFDC source 仍有约整周 sample0-aligned phase 漂移。
- 用户在 notebook 13 的 `Sample0-aligned measured RF scope` 中确认实测相位仍抖动，`phase residual` 在大范围内震动。
- 当前需要确认：这种 RFDC/preview 侧抖动是否也进入即将作为 TIME/SPEC UDP payload 发送的数据。
- 当前仍无 QSFP live；`UDP_DRY_RUN=1`、`QSFP_LINK_UP=0` 是预期状态。
- PYNQ 目标：`xilinx@192.168.100.117`。报告不记录明文密码。

## 完成内容

- RTL/sample0:
  - `rfdc_adc_axis_adapter` 输出 full-rate `sample0 = sample_count << 2`，作为 AXIS sideband 进入数据面。
  - `time_packetizer` header word4 的 `sample0` 改为 packet 第一个 ADC 样点的 RFDC-derived sample0。
  - `spectral_packetizer` header word4 的 `sample0` 改为 channel window 第一个 ADC 样点的 RFDC-derived sample0。
  - `CORE_VERSION` bump 到 `0x00010009`。
- TX payload witness:
  - 新增 `rtl/tx_payload_witness_capture.sv`，接在 `tx_route_selector` 输出、`udp_frame_builder` 输入之前。
  - witness 捕获 T510 internal packet header 16 个 64-bit word 和最多 112 个 payload word，总计 128 个 64-bit word。
  - witness 是只读观测模块，不参与 backpressure，不改变 packet/FIFO/TX science 数据路径。
  - 新增 `0x0790..0x07cc` witness control/status/metadata，`0x0ac00..0x0afff` witness buffer。
- Python/Jupyter:
  - `python/t510_fengine.py` 增加 `capture_tx_payload_witness()`、`decode_time_payload_iq()`、`decode_spec_payload_iq()`、`compute_payload_phase_metrics()`。
  - 新增 `scripts/pynq_rfdc_udp_coherence_audit.py`，同时采集 preview、payload witness、header、counters、RFDC flags、PFB/TX 状态。
  - notebook 13 更新 expected core version 到 `0x00010009`，高级面板新增 `RFDC-to-UDP Coherence`，用于显示 preview/payload phase residual、sample0 delta、witness header/payload 状态。

## 验证证据

本地已通过：

```bash
python3 -m py_compile python/packet.py python/t510_fengine.py scripts/pynq_rfdc_udp_coherence_audit.py
python3 -m json.tool notebooks/13_astronomer_rf_observation_console.ipynb >/dev/null
./scripts/run_xsim_batch.sh tb_tx_payload_witness_capture tb_time_packetizer tb_spectral_packetizer tb_t510_fengine_top_smoke
```

XSim 结果：`tb_tx_payload_witness_capture`、`tb_time_packetizer`、`tb_spectral_packetizer`、`tb_t510_fengine_top_smoke` 全部 PASS。覆盖点包括 TIME/SPEC header `sample0` 来自输入 RFDC sample0、witness stream filter、header + payload capture、witness 不反压 AXIS。

Vivado/overlay：

- Synthesis：0 error，0 critical warning。
- Implementation：READY，0 error，0 critical warning。
- Bitstream：`write_bitstream Complete`，0 error，0 critical warning。
- Timing：`WNS=+1.499 ns`，`WHS=+0.004 ns`，失败端点 `0/134729`。
- Bitstream：`overlay/t510_fengine.bit`，SHA256 `6417cb49bca106fb21821cce3dbe821e1cac6e1eb1d363754e877c383de82339`。
- HWH：`overlay/t510_fengine.hwh`，SHA256 `95fd94741fc83ac4d4d94f330e1032eb90bc54a63462c3f46aeb8935ac6b700b`。

板端最终审计命令：

```bash
cd /home/xilinx/t510_fengine_bringup
source /etc/profile.d/xrt_setup.sh
sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_rfdc_udp_coherence_audit.py --center-mhz 100 --signals-mhz 119.2,130.24,130,100 --modes spec,time --samples 512 --frames 120 --timeout 2.0
```

板端结果摘要：

- `result=PASS`：witness/header/payload 证据链完成。
- `CORE_VERSION=0x00010009`。
- `data_quality_gate=BLOCK_QSFP_LIVE_DATA_QUALITY`。
- `classification=preview_and_payload_unstable_correlation_unclear`。
- 8 个条件均 `120/120` valid frames，witness timeout 为 0。
- TIME/SPEC header `sample0` 非零、单调，可追溯到 RFDC sample counter。
- SPEC witness：`stream_type=0`，`payload_bytes=8192`，`chan_count=64`，`time_count=4`，`endpoint_id=0`。
- TIME witness：`stream_type=1`，`payload_bytes=8192`，`time_count=256`，`endpoint_id=2`。
- 每个 condition 前需要 overlay reload 才能稳定切换 SPEC/TIME witness；这是 Stage 16 的运行 workaround，也是后续需要调查的 state-reset 问题。

关键统计表：

| mode | signal MHz | valid | timeout | preview phase p-p deg | payload phase p-p deg | phase corr | sample0 monotonic | large preview frames |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| SPEC | 119.20 | 120 | 0 | 354.04 | 355.58 | -0.08 | yes | 0 |
| TIME | 119.20 | 120 | 0 | 355.26 | 355.94 | -0.08 | yes | 0 |
| SPEC | 130.24 | 120 | 0 | 345.12 | 344.35 | 0.20 | yes | 0 |
| TIME | 130.24 | 120 | 0 | 356.64 | 359.76 | 0.06 | yes | 1 |
| SPEC | 130.00 | 120 | 0 | 358.05 | 345.18 | 0.13 | yes | 0 |
| TIME | 130.00 | 120 | 0 | 351.72 | 351.94 | 0.05 | yes | 0 |
| SPEC | 100.00 | 120 | 0 | 180.00 | 180.00 | 0.07 | yes | 0 |
| TIME | 100.00 | 120 | 0 | 180.00 | 180.00 | -0.13 | yes | 0 |

原始板端 JSON 保存在本地 `stage16_pynq_rfdc_udp_coherence_audit_output.json`，用于后续复查每帧 preview/payload phase、amplitude、sample0 delta、RFDC flags 和 header metadata。

## 阶段衔接说明

下一阶段可依赖：

- TIME/SPEC packet header `sample0` 已不是固定 0 或 packetizer 内部从 0 递增，而是 RFDC-derived sample0。
- TX payload witness 可以抓到即将进入 UDP frame builder 的 T510 internal packet header + payload，且不反压数据面。
- `capture_tx_payload_witness()`、`decode_time_payload_iq()`、`decode_spec_payload_iq()` 和 `compute_payload_phase_metrics()` 可作为后续 QSFP 前数据质量门禁 API。
- `pynq_rfdc_udp_coherence_audit.py` 能在无 QSFP 条件下同时比较 preview 与 TIME/SPEC dry-run payload 的相位、幅度、sample0 和 header 语义。

下一阶段不能依赖：

- 不能声明 QSFP/CMAC live 链路、交换机收包或 DGX/X-engine 收包成功。
- 不能声明 TIME/SPEC payload 的相位/幅度质量已通过；当前门禁明确为 `BLOCK_QSFP_LIVE_DATA_QUALITY`。
- 不能把 SPEC dry-run channel window 当作科学级 4096-channel 4-tap PFB 幅相标定完成。
- 不能把本板 `INTERNAL_EPOCH` sample0 拿去做跨板绝对时间比较。

剩余风险：

- preview 和 payload 都存在大范围 phase residual；相关性低，说明可能还有“preview 抓取时刻”和“payload window 时刻”不一致、payload 解码/拟合窗口不等价、RFDC/clock 上游不稳定等未拆开的因素。
- 每个 condition 前需要 reload overlay 才能稳定获得 TIME/SPEC witness，提示 mode switch、route/arbiter、packetizer reset 或 witness state reset 仍有隐患。
- `sample0_delta` 在不同帧之间有抖动，当前能证明 monotonic 和非零，但还没有证明 preview frame 与 payload witness frame 是同一个 RFDC 时间窗口。
- `RFDC flags=30/31` 仍需要解码到具体 tile/block 状态，并与 phase/amplitude 大事件关联。

推荐入口命令：

```bash
./scripts/run_xsim_batch.sh tb_tx_payload_witness_capture tb_time_packetizer tb_spectral_packetizer tb_t510_fengine_top_smoke
sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_rfdc_udp_coherence_audit.py --center-mhz 100 --signals-mhz 119.2,130.24,130,100 --modes spec,time --samples 512 --frames 120 --timeout 2.0
```

## AI 接续提示

- Stage 16 结论要分两层读：`result=PASS` 表示证据链完成；`data_quality_gate=BLOCK_QSFP_LIVE_DATA_QUALITY` 表示不允许把 live QSFP science stream 当作可信数据推进。
- 下一轮不要再只看 Jupyter scope；应同时看 preview 和 payload witness 的 phase/amplitude/sample0。
- 如果要继续查相位来源，优先让 preview 和 payload 对准同一 RFDC 时间窗口：增加 trigger-coupled preview/payload paired capture，或在 packetizer/witness 侧锁存同一个 source window 的 raw IQ。
- 如果要继续查 packetizer，优先调查 per-condition overlay reload workaround：mode switch、packetizer reset、route selector filter、witness clear/arm 是否有状态污染。
- 如果要进入 QSFP/CMAC live，只能做链路层/pcap preflight；science 数据质量仍应由 Stage 16 的 gate 阻塞。
- 不要在报告、脚本或 notebook 中记录 SSH 明文密码。

## 阻塞项

- QSFP live science data quality 被 Stage 16 明确阻塞：`BLOCK_QSFP_LIVE_DATA_QUALITY`。
- preview 和 payload phase residual 都接近整周范围，且 correlation 低，尚不能归因到单一硬件模块。
- TIME/SPEC mode 切换需要 per-condition overlay reload workaround，后续必须查 reset/state contamination。
- RFDC flags、大幅事件、sample0 delta 和 payload window 之间的因果关系尚未闭合。
