# Stage 14: Sample0-Aligned Measured Phase Preview

## 阶段目标

把用户担心的“采样相位偏移/抖动”直接放进 Jupyter 实时预览：新增一个 `Sample0-aligned measured RF scope`，用 ADC raw IQ、`sample0`、采样率和配置频率计算每帧实测相位。如果采样链路稳定，实测波形应相对参考波形稳定；如果采样相位漂移，实测波形会在实时图里横向/相位抖动。

本阶段不改 RTL、不重新生成 bitstream、不 bump `CORE_VERSION`；继续使用 Stage 10/11/12/13 overlay `CORE_VERSION=0x00010007`。

## 输入基线

- Stage 13 已证明 synthetic、frozen frame、readback consistency 稳定，但 repeated live preview 中 raw phase/amplitude 大幅漂移。
- Stage 13 notebook 主 RF scope 是配置锁定参考显示，不能用它证明硬件采样相位稳定。
- 用户需要在实时预览中看到真实采样链路的相位漂移，而不是只看到被配置相位锁住的稳定波形。
- 核心时间语义固定：
  ```text
  每帧只有一个 sample0 标记点
  第 n 个样点的隐含时间 = (sample0 + n) / sample_rate
  不是每个 ADC 样点各自带 timestamp
  ```

## 完成内容

- Python backend：
  - `T510FEngine` 新增 `compute_sample0_aligned_phase_view()`。
  - 对齐主基准使用配置频率 `expected_baseband_hz = dac_signal_hz - observe_center_hz`，不再用每帧 FFT peak 做相位对齐，避免把 FFT peak 抖动混入相位判断。
  - 输出 `expected_reference_waveform`、`measured_sample0_aligned_waveform`、`phase_error_deg`、`fit_residual_fraction`、`snr_db`、`max_abs_code`、`rms_code`、`sample0_mod_phase_deg`。
  - 保留 `fft_peak_phase_deg` 作为诊断字段，但不作为 sample0 对齐主判断。
- Board audit：
  - `scripts/pynq_phase_provenance_audit.py` 新增 `--mode sample0_aligned_preview`。
  - 该模式覆盖 synthetic fixed phase、synthetic phase step、synthetic injected drift、frozen hardware frame、repeated live preview。
- Jupyter：
  - `notebooks/13_astronomer_rf_observation_console.ipynb` 增加 `Sample0-aligned measured RF scope`。
  - 原主图改名为 `Configured RF reference scope`，明确它是配置相位参考。
  - 新增 `Set alignment anchor`、`Apply后自动对齐`、`显示实测对齐`、`显示参考虚线` 控件。
  - 新增 `Sample0-aligned phase residual` 历史图，显示最近帧的 `phase_error_deg`。
  - 高级 `Phase Provenance` 面板新增 `expected_tone_measured_phase_deg`、`sample0_aligned_phase_deg`、`phase_error_deg` 等字段。

## 验证证据

- 本地软件：
  ```bash
  python3 -m py_compile python/t510_fengine.py scripts/pynq_phase_provenance_audit.py
  python3 -m json.tool notebooks/13_astronomer_rf_observation_console.ipynb >/dev/null
  ```
  结果：PASS。

- PYNQ 发布与远端校验：
  - 已同步 `python/t510_fengine.py` 到 `/home/xilinx/t510_fengine_bringup/python/` 和 `/home/xilinx/jupyter_notebooks/t510_fengine/python/`。
  - 已同步 `scripts/pynq_phase_provenance_audit.py` 到 `/home/xilinx/t510_fengine_bringup/scripts/`。
  - 已同步 notebook 13 到 `/home/xilinx/t510_fengine_bringup/notebooks/` 和 `/home/xilinx/jupyter_notebooks/t510_fengine/notebooks/`。
  - 远端 `py_compile` 与 notebook JSON 校验 PASS。

- Stage 14 board smoke：
  ```bash
  cd /home/xilinx/t510_fengine_bringup
  source /etc/profile.d/xrt_setup.sh
  sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_phase_provenance_audit.py --mode sample0_aligned_preview --signal-mhz 100 --center-mhz 100 --bw-mhz 100 --samples 512 --seconds 60 --timeout 2.0 --save-raw-frames 0
  ```
  结果：PASS，分类为 `sample0_aligned_live_phase_jitter`。

- synthetic fixed phase：
  - `phase_error` p-p `0.0 deg`。
  - 说明 sample0 对齐算法在纯软件固定相位下不产生假抖动。

- synthetic phase step：
  - `0/45/90/180 deg` phase step residual 均为 `0.0 deg`。
  - 说明配置相位变化可以被 sample0-aligned measured waveform 正确表达。

- synthetic injected drift：
  - 注入 `+30 deg` 漂移，测得 `29.9947 deg`。
  - 说明该视图能把真实相位漂移显式显示出来。

- frozen hardware frame：
  - 同一帧 raw IQ 重复计算 100 次，`phase_error` p-p `0.0 deg`。
  - 说明同帧算法和显示链路稳定；冻结帧不漂。

- repeated live preview：
  - 采集 `1024` 帧。
  - `phase_error` max abs from first `179.78 deg`。
  - `phase_error` p-p `359.56 deg`。
  - `phase_error` RMS `102.95 deg`。
  - `large_signal_frames=2`。
  - `max_abs_code=32554`。
  - `rms_code` p-p 约 `1198.79`。
  - `fit_residual_fraction` mean `12.31`，max `125.15`。
  - 结论：synthetic/frozen/display 路径稳定，但 live hardware preview 的 sample0-aligned measured phase 和幅度仍有真实不稳定。

## 阶段衔接说明

- 下一阶段可依赖：
  - notebook 13 中 `Configured RF reference scope` 作为配置相位参考图。
  - notebook 13 中 `Sample0-aligned measured RF scope` 作为实时观测采样相位漂移的主图。
  - `phase_error_deg` 是后续判断 live 采样相位漂移的主要字段。
  - `compute_sample0_aligned_phase_view()` 可作为后续 F-engine 监控公共 API。
  - `--mode sample0_aligned_preview` 已把 synthetic、frozen frame 和 repeated live preview 串成同一套门禁。
- 下一阶段不能依赖：
  - 不能把 `Configured RF reference scope` 的稳定误认为 raw ADC phase 稳定。
  - 不能声明 DAC0-ADC0 模拟闭环相位已经稳定；Stage 14 repeated live preview 显示 `phase_error` 接近全范围漂移。
  - 不能认为每个 ADC 样点有独立 timestamp；当前只有每帧一个 `sample0` 标记点。
  - 不能把当前 RF 等效波形当作 4.9152 GS/s 原始 RF 采样波形；它仍是由 baseband IQ 重建的 RF 等效显示。
- 剩余风险：
  - Stage 14 量化了 live preview 相位/幅度不稳定，但尚未定位根因。
  - 仍未区分异常来自 RFDC ADC、DAC 输出、clock/MTS/NCO reset、RTL preview trigger/sample0 latch、I/Q lane mapping、模拟链路或偶发大幅事件。
  - 当前缺少硬件触发式 raw capture/event log，无法把大幅事件与 `sample0` latch、RFDC flags、preview trigger 精确关联。
- 推荐入口命令：
  ```bash
  cd /home/xilinx/t510_fengine_bringup
  source /etc/profile.d/xrt_setup.sh
  sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_phase_provenance_audit.py --mode sample0_aligned_preview --signal-mhz 100 --center-mhz 100 --bw-mhz 100 --samples 512 --seconds 60 --timeout 2.0
  ```

## AI 接续提示

- 相位判断优先级：
  - `configured_phase_deg`：用户设置的配置相位。
  - `display_reference_phase_deg`：配置参考图实际使用的显示相位。
  - `expected_tone_measured_phase_deg`：raw IQ 在配置 expected baseband frequency 上拟合得到的单帧相位。
  - `sample0_aligned_phase_deg`：扣除 `sample0` 时间基点后的实测相位。
  - `phase_error_deg`：sample0 对齐后相对 anchor/配置相位的残差，是 live drift 主判断字段。
- 解释给用户时要明确：ADC 样点不是逐点 timestamp；每帧只有一个 `sample0`，第 `n` 点时间由 `(sample0+n)/sample_rate` 推导。
- 如果 `Freeze current frame` 稳定而 live `phase_error_deg` 抖动，优先查 RFDC/RTL/硬件采样链路。
- 下一阶段建议改 RTL/硬件观测能力：
  - 增加 preview capture event log：capture request、first-write、done 的 `sample0`、write pointer、valid mask、RFDC flags。
  - 增加大幅事件触发器：当 ADC max/RMS 超阈值时锁存前后 raw samples、`sample0`、RFDC flags、DAC phase epoch、TX counters。
  - 增加内部数字注入路径：把已知 DDS/constant phasor 直接送入 preview/PFB 分支，绕过 RFDC/模拟链路。
  - 审计 preview trigger 与 `sample0` latch 是否同源、是否跨时钟域安全、I/Q lane unpack 是否稳定。
  - 审计 live loop 和脚本是否误触发 RFDC NCO `UpdateEvent` 或 `ResetNCOPhase`；Stage 14 smoke 不应每帧重配 RFDC/DAC。
- 不要在报告、notebook 或脚本里记录 SSH 明文密码。

## 阻塞项

- live sample0-aligned measured phase 仍接近全范围漂移，根因未定位。
- live preview 中仍有大幅事件，`max_abs_code` 接近满幅，缺少硬件触发式证据链。
- DAC0-ADC0 线缆当前不能移动，无法通过换线/衰减/终端验证排除模拟外部因素。
- CMAC/QSFP 真实链路仍未做交换机/接收节点抓包；接入前需要明确 science payload 数据质量风险。
