# Stage 13: Phase Provenance + Hardware Design Audit Before QSFP

## 阶段目标

在不移动 DAC0-ADC0 物理连线的前提下，把相位和大信号异常分层定位：区分 Jupyter/PYNQ 显示链路、Python 相位算法、preview BRAM/MMIO 读回、连续硬件采样/RFDC/RTL 数据路径。

本阶段不改 RTL、不重新生成 bitstream、不 bump `CORE_VERSION`；继续使用 Stage 10/11/12 overlay `CORE_VERSION=0x00010007`。

## 输入基线

- Stage 11/12 notebook 13 的主 RF scope 是 `configured RF equivalent` 显示，默认相位稳定来自配置频率和 phase slider，不等价于 raw ADC 相位稳定。
- 用户观察到：DAC0 与 ADC0 已由一根线连接，但频谱/幅度仍会时不时涌入大信号；phase 的稳定机制也需要明确 provenance。
- 当前无法操作 DAC0-ADC0 线缆，因此只能通过软件配置、冻结帧、连续采样和读回一致性做非侵入审计。

## 完成内容

- Python backend：
  - 新增 `compute_phase_provenance()`，统一输出 `configured_phase_deg`、`measured_fft_phase_deg`、`sample0_correction_deg`、`sample0_coherent_phase_deg`、`display_rf_phase_deg`、FFT peak、SNR、fit residual、clip/max/RMS。
  - 新增 `capture_preview_readback_check()`，一次 capture 后连续读 preview buffer 两次，不重新触发，用于定位 BRAM/MMIO/CDC/读写仲裁是否会改变数据。
  - 新增 `synthetic_phase_frame()`，生成纯软件 IQ 帧，用于验证算法和显示链路。
- Board audit：
  - 新增 `scripts/pynq_phase_provenance_audit.py`，支持 `synthetic`、`frozen_frame`、`repeated_preview`、`readback_consistency`、`phase_step`。
  - 脚本输出 JSON summary，必要时可用 `--save-raw-frames` 保存少量 raw IQ `.npz` 到 `reports/runtime/stage13/`。
- Jupyter：
  - `notebooks/13_astronomer_rf_observation_console.ipynb` 保留天文学家主视图。
  - 高级面板新增 `Phase Provenance`：四个相位分开显示。
  - 新增 `Freeze current frame`，冻结同一帧 raw IQ 反复重算/重绘；如果冻结帧仍漂移，才归因到显示/算法。
  - 新增 `Raw ADC IQ phase provenance` 小图，显示 measured FFT phase、sample0 coherent phase、display RF phase 历史。

## 验证证据

- 本地软件：
  ```bash
  python3 -m py_compile python/t510_fengine.py scripts/pynq_phase_provenance_audit.py
  python3 -m json.tool notebooks/13_astronomer_rf_observation_console.ipynb >/dev/null
  ```
  结果：PASS。

- PYNQ 发布与远端校验：
  - 已同步 `python/t510_fengine.py`、`scripts/pynq_phase_provenance_audit.py`、`notebooks/13_astronomer_rf_observation_console.ipynb` 到 `/home/xilinx/t510_fengine_bringup`。
  - notebook 13 已同步到 `/home/xilinx/jupyter_notebooks/t510_fengine/notebooks/`。
  - 远端 `py_compile` 与 notebook JSON 校验 PASS。

- `synthetic`：
  ```bash
  /usr/local/share/pynq-venv/bin/python3 scripts/pynq_phase_provenance_audit.py --mode synthetic --frames 100 --samples 512
  ```
  结果：PASS。100 帧中 `measured_fft_phase`、`sample0_coherent_phase`、`display_rf_phase` 抖动均为 `0.0 deg`；amplitude/RMS/max 均无变化。

- `readback_consistency`：
  ```bash
  sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_phase_provenance_audit.py --mode readback_consistency --frames 30 --samples 512 --timeout 2.0
  ```
  结果：PASS。30 次 capture 双读均一致，`mismatch_frames=0`，`mismatch_count=0`。

- `frozen_frame`：
  ```bash
  sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_phase_provenance_audit.py --mode frozen_frame --frames 100 --signal-mhz 100 --center-mhz 100 --samples 512 --timeout 2.0
  ```
  结果：PASS。同一帧 raw IQ 重算 100 次：
  - `measured_fft_phase` 抖动 `0.0 deg`
  - `sample0_coherent_phase` 抖动 `0.0 deg`
  - amplitude/RMS/max 抖动 `0.0`
  - 该帧自身 fit residual 较高，约 `71.85%`，说明 raw ADC 帧并不接近理想单音，但重算/重绘本身稳定。

- `repeated_preview` 60 秒短测：
  ```bash
  sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_phase_provenance_audit.py --mode repeated_preview --seconds 60 --frames 1 --signal-mhz 100 --center-mhz 100 --bw-mhz 100 --samples 512 --timeout 2.0 --frame-interval-s 0.05
  ```
  结果：诊断 PASS，分类为 `hardware_or_sampling_path_jitter`。
  - 采集 `1032` 帧，`sample0` 单调递增。
  - `measured_fft_phase` max abs from first `179.98 deg`，p-p `359.92 deg`。
  - `sample0_coherent_phase` max abs from first `179.93 deg`，p-p `359.43 deg`。
  - `display_rf_phase` 抖动 `0.0 deg`。
  - amplitude code `84.06..253.43`，RMS `264.86..1485.78`，`max_abs_code` 最大 `32503`，接近满幅但未越过当前 clip 阈值。
  - 该结果说明主 RF scope 的相位稳定是配置锁定；raw ADC measured phase 在连续硬件采样中并不稳定。

- `phase_step` 短测：
  ```bash
  sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_phase_provenance_audit.py --mode phase_step --phase-deg 0,45,90,180 --seconds-per-step 5 --frames-per-step 1 --signal-mhz 100 --center-mhz 100 --bw-mhz 100 --samples 512 --timeout 2.0
  ```
  结果：控制面 PASS，数据面仍不稳定。
  - `DAC_PHASE_EPOCH` 随相位步进递增：`2/3/4/5`。
  - `display_rf_phase` 严格跟随 `0/45/90/180 deg`。
  - raw `sample0_coherent_phase` 每个相位段内仍接近全范围漂移；例如各段 max abs from first 约 `178..180 deg`。
  - measured phase delta 未可靠跟随 requested delta；不能用 raw measured phase 证明 DAC phase slider 已在模拟闭环中稳定生效。

## 阶段衔接说明

- 下一阶段可依赖：
  - `compute_phase_provenance()` 可作为后续所有 F-engine 监控面板的相位 provenance 公共 API。
  - `Freeze current frame` 可用于在 notebook 中快速区分显示/算法漂移与硬件 live capture 漂移。
  - `capture_preview_readback_check()` 已证明当前一次 capture 完成后的 preview BRAM/MMIO 双读一致；同帧读回本身不是已观测相位漂移主因。
  - `synthetic` 和 `frozen_frame` 均稳定，说明 Python 相位算法和 Plotly 重绘不是当前主要嫌疑。
- 下一阶段不能依赖：
  - 不能把主 RF scope 的相位稳定当作 raw ADC 采样相位稳定。
  - 不能声明 DAC0-ADC0 模拟闭环已经达到相位稳定；Stage 13 证据显示 repeated preview 中 raw measured phase 仍大幅漂移。
  - 不能声明偶发大幅信号是线缆或外部干扰导致；当前不能移动线缆，证据只说明异常出现在连续硬件采样路径中。
  - 不应在 raw phase/amplitude 问题未定位前，把 QSFP live science stream 作为可信科学数据推进；CMAC/route preflight 可继续，但数据质量门禁应单独挂起。
- 剩余风险：
  - `repeated_preview` 本次为 60 秒短测，不是完整 180 秒长测；间歇性异常需要更长 soak 和触发式 raw frame 保存。
  - 仍未区分异常来自 RFDC ADC、DAC 输出、模拟链路、clock/MTS/NCO reset、RTL preview trigger/sample0 latch、I/Q lane mapping 或阈值事件。
  - `phase_step` 只证明控制寄存器和 display phase 动作正确；raw measured phase 没有稳定跟随。
- 推荐入口命令：
  ```bash
  cd /home/xilinx/t510_fengine_bringup
  source /etc/profile.d/xrt_setup.sh
  sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_phase_provenance_audit.py --mode repeated_preview --seconds 180 --signal-mhz 100 --center-mhz 100 --bw-mhz 100 --samples 512 --timeout 2.0
  sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_phase_provenance_audit.py --mode readback_consistency --frames 100 --samples 512 --timeout 2.0
  ```

## AI 接续提示

- 判断相位问题必须看四个相位：
  - `configured_phase_deg`：用户滑块配置。
  - `measured_fft_phase_deg`：当前 raw ADC IQ 单帧拟合相位。
  - `sample0_coherent_phase_deg`：扣除 `sample0` 时间基点后的 raw measured phase。
  - `display_rf_phase_deg`：主 RF 等效示波器实际使用的显示相位。
- 如果 synthetic/frozen 稳定但 repeated preview 抖动，优先查 RFDC/RTL/硬件采样链路，不要继续调主 RF scope。
- 下一步硬件/RTL 审计建议：
  - 增加 preview capture event log：capture request、first-write、done 的 `sample0`、write pointer、valid mask、RFDC flags。
  - 增加大幅事件触发器：当 ADC max/RMS 超阈值时锁存前后 raw samples、`sample0`、RFDC flags、DAC phase epoch、TX counters。
  - 增加内部数字注入路径：把已知 DDS/constant phasor 直接送入 preview/PFB 分支，绕过 RFDC/模拟链路，用于区分 RTL preview/sample0 与 RFDC/模拟问题。
  - 审计 live loop 中是否存在 RFDC NCO `UpdateEvent` 或 `ResetNCOPhase` 误触发；Stage 13 repeated preview 脚本没有重配 RFDC/DAC，因此 notebook UI 不是该短测的重配来源。
  - 审计 ADC I/Q lane mapping、full-rate unpack、CDC、preview trigger 与 `sample0` latch 是否同源。
- 如果未来接 QSFP，先把 Stage 7/packet route 作为链路 preflight；science payload 的 raw phase/amplitude 质量仍应受 Stage 13 后续硬件审计约束。
- 不要在报告、notebook 或脚本里记录 SSH 明文密码。

## 阻塞项

- raw repeated preview 的相位和幅度异常未定位。
- 大幅事件尚无硬件锁存/触发式 raw capture，无法判断事件与 RFDC flags/sample0/preview trigger 的精确关系。
- DAC phase slider 的 display/control 面已动作，但 measured raw ADC phase 未稳定跟随。
- DAC0-ADC0 线缆当前不能移动，不能通过换线/终端/衰减器排除板级模拟问题。
- CMAC/QSFP 真实链路仍未接交换机抓包；即使后续链路打通，也不能把当前 raw ADC 数据质量视为已通过。
