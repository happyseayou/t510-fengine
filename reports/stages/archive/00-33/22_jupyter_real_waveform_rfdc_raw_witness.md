# Stage 22：Jupyter 全真实波形与 RFDC 输出 Raw Witness 修正

## 结论

- 已纠正 Jupyter 中“波形”由配置频率/相位合成正弦的问题。现在主界面和 sample0-aligned 视图只显示 RFDC preview buffer 中真实读回的 I/Q/|IQ| 数据。
- 已新增 RFDC AXIS 输出 raw witness。该 witness 以无反压方式抓取 RFDC 输出到 PL 后、进入现有 preview/adapter 旁路附近的真实 AXIS beat；它不是 RFDC 内部 pre-DDC 最高采样率原始 RF。
- `CORE_VERSION` 已更新为 `0x00010011`。
- Vivado 已完成 synth、impl、bitstream、overlay export，并已发布到 PYNQ Jupyter 目录。

## 关键改动

- `python/t510_fengine.py`
  - `compute_observation_view()` 改为只输出真实 RFDC preview 数据，metadata 标记 `waveform_source="rfdc_preview_buffer"`、`virtual_waveform=False`。
  - `compute_sample0_aligned_phase_view()` 保留 phase/SNR/residual/sample0 等数值诊断，但不再输出或依赖合成参考波形。
  - 新增 `capture_rfdc_axis_raw_witness()` 与 `decode_rfdc_axis_raw_words()`。
- `notebooks/13_astronomer_rf_observation_console.ipynb`
  - 主波形模式只保留 `I`、`Q`、`I/Q overlay`、`|IQ|`。
  - 移除可见 RF reference/expected waveform 绘图路径。
  - 增加 RFDC Raw Witness 面板，可选择 CH0..CH7 查看真实 sub-sample I/Q。
- RTL
  - 新增 `rtl/rfdc_axis_raw_witness_capture.sv`。
  - `rtl/t510_fengine_top.sv` 接入 RFDC AXIS raw witness tap。
  - `rtl/feng_ctrl_axi.sv` 增加 `0x0e200..` witness control/status，`0x0e800..0x0f7ff` raw buffer 读窗。
  - 为避免与 TX payload witness buffer 重叠，TX payload witness buffer 已移到 `0x10000`，core AXI address range 扩为 `128K`。

## 本地验证

- `python3 -m py_compile python/t510_fengine.py scripts/pynq_external_adc_tone_decoupling_check.py scripts/pynq_stage20_8lane_external_sync_check.py scripts/pynq_stage21_qsfp_link_pcap_check.py`：PASS
- notebook JSON 校验：PASS
- notebook code-cell AST 校验：PASS
- grep 门禁：未发现 `RF参考`、`Configured RF reference`、`expected_reference_waveform`、`measured_sample0_aligned_waveform`、`analysis['rf_scope']` 等旧虚拟波形路径。
- XSim 已通过：
  - `tb_rfdc_axis_raw_witness_capture`
  - `tb_feng_ctrl_axi`
  - `tb_preview_event_capture`
  - `tb_t510_fengine_top_smoke`
  - `tb_t510_fengine_board_top`

## Vivado 验证

- `synth_1`：0 errors，0 critical warnings。
- `impl_1`：route complete，0 errors，0 critical warnings。
- bitstream readiness：`READY`
  - WNS `+1.215 ns`
  - WHS `+0.006 ns`
  - failing endpoints `0 / 227443`
- bitgen：`write_bitstream completed successfully`
  - 0 errors
  - 0 critical warnings
  - 普通 DRC warnings 主要为 DSP pipeline 建议、FFT IP BRAM advisory、RFDC STATUS 未接负载；不阻塞本阶段。

## Overlay 发布

- 本地 overlay：
  - `overlay/t510_fengine.bit`
  - `overlay/t510_fengine.hwh`
  - `overlay/t510_fengine.tcl`
  - `overlay/t510_fengine.manifest.txt`
- SHA256：
  - bit：`606f2c2d2bdf6105a1e5257efe43bd45a2ed66f17744a5f2bdb839cec2c152b7`
  - hwh：`c6400e1a31f3034b5cad81a75d8ef32b9aa4915e54ea970979ee7ac7431d030a`
- 已同步到 PYNQ：
  - `/home/xilinx/jupyter_notebooks/t510_fengine/overlay/t510_fengine.bit`
  - `/home/xilinx/jupyter_notebooks/t510_fengine/overlay/t510_fengine.hwh`
  - `/home/xilinx/jupyter_notebooks/t510_fengine/python/t510_fengine.py`
  - `/home/xilinx/jupyter_notebooks/t510_fengine/notebooks/13_astronomer_rf_observation_console.ipynb`
- 远端 SHA256 与本地一致。
- 远端 Python 编译检查通过；远端旧 `__pycache__` 有权限问题，检查时使用了临时 `PYTHONPYCACHEPREFIX`。
- 板端最小 overlay 读回已通过：
  - `CORE_VERSION=0x00010011`
  - `preview_axis_beat_rate_hz=61440000`
  - `preview_sample_rate_hz=245760000`
  - `tx_link_status_flags=0x00000002`

## 板端下一步

1. 在 Jupyter 打开 `t510_fengine/notebooks/13_astronomer_rf_observation_console.ipynb`，确认界面显示 `CORE_VERSION=0x00010011`。
2. 用外部非正弦/失真输入测试主波形图：图形必须跟随真实 preview 样点形状变化，不能回到固定正弦。
3. 打开 RFDC Raw Witness 面板，逐路 CH0..CH7 抓取，确认 sample0、word_count、I/Q sub-sample 与 preview 同步变化。
4. 再跑 8 路 DAC-ADC loopback 的 `3 deg / 5%` 严格门禁，确认 witness 加入没有退化原闭环。

## 注意

- 本阶段没有降低任何相位/幅度门禁。
- 本阶段没有把 SSH 密码写入脚本、notebook 或报告。
- QSFP live science 验证仍属于 Stage 20/21 之后的独立数据面验收，不与本次 Jupyter 波形真实性修正混在一起。
