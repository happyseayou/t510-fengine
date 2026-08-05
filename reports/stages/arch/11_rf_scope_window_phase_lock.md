# Stage 11: RF-Accurate Scope Window + Stable Phase Lock

## 阶段目标

修复 Stage 10 示波器窗口语义：主示波器改为 RF 等效波形，时间窗口严格按真实 RF 时间显示。固定观测中心 `100 MHz` 时，`60 MHz`、`100 MHz`、`130 MHz` 在同一 `0.25 us` 窗口内分别显示 `15`、`25`、`32.5` 个周期，符合天文学家对 RF 频率的直觉。

本阶段不改 RTL、不重新生成 bitstream、不 bump `CORE_VERSION`；继续使用 Stage 10 overlay `CORE_VERSION=0x00010007`。

## 输入基线

- Stage 10 已完成 astronomer RF observation console，但主示波器仍由 ADC 下变频后的 baseband peak 合成。
- 用户反馈：固定观测中心 `100 MHz` 时，`60 MHz` 显示得比 `100 MHz` 更稠密，说明主示波器用了 baseband offset，而不是 RF 频率。
- 用户要求：主界面继续服务天文学家，示波器时间窗口必须精确显示实际 RF 波形；相位不能在实时刷新中大幅抖动。

## 完成内容

- Python backend：
  - `compute_observation_view()` 新增 `rf_scope` 和 `baseband_scope` 双波形输出。
  - `rf_scope` 使用配置的 `dac_signal_hz` 生成 RF 等效主波形，x 轴严格为 `0..time_window_us`，点数按 RF 周期数自适应并限制在 Jupyter 可承受范围内。
  - `baseband_scope` 保留原 ADC preview/IQ 基带调试波形，用于工程诊断。
  - `analysis["scope"]` 兼容指向新的 `rf_scope`。
  - 主 RF scope 相位锁定改为配置频率锁定：`phase_deg + phase_deg_per_channel * channel`，不再由每帧 FFT phase 驱动。
  - Spectrum/peak/SNR/clip 计算保持不变，仍用于 RF peak 和 baseband debug 诊断。
- Jupyter：
  - `notebooks/13_astronomer_rf_observation_console.ipynb` 主图改为 `RF-equivalent scope`。
  - 新增 `Baseband debug scope`，放入高级工程状态 accordion。
  - 主 RF scope 始终使用 `rf_scope["waveform"]`；`Raw preview` 只影响基带调试图。
  - 状态栏显示 RF scope frequency/phase，工程面板显示 `phase_lock=configured_rf`。
- Board smoke：
  - `scripts/pynq_astronomer_rf_console_check.py` 新增 `--stage11-scope-check`。
  - 固定 center `100 MHz`，验证 `60/100/130 MHz` RF scope 周期数单调且精确。
  - 验证 baseband debug 仍反映 `abs(signal-center)`。
  - 连续 20 帧检查 RF scope phase jitter。
  - 检查 phase slider 等效设置 `0/45/90 deg` 在 RF scope 中稳定显示。
- 发布：
  - 更新后的 `python/`、`scripts/`、`notebooks/` 已同步到 `/home/xilinx/t510_fengine_bringup`。
  - 更新后的 notebook 13 已发布到 `/home/xilinx/jupyter_notebooks/t510_fengine`。

## 验证证据

- 本地软件：
  ```bash
  python3 -m py_compile python/t510_fengine.py scripts/pynq_astronomer_rf_console_check.py
  python3 -m json.tool notebooks/13_astronomer_rf_observation_console.ipynb >/dev/null
  ```
  结果：PASS。

- PYNQ Stage 11 scope check：
  ```bash
  cd /home/xilinx/t510_fengine_bringup
  source /etc/profile.d/xrt_setup.sh
  sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_astronomer_rf_console_check.py --stage11-scope-check --center-mhz 100 --signals-mhz 60,100,130 --bw-mhz 100 --time-window-us 0.25 --timeout 2.0
  ```
  结果：PASS。
  - `core_version=0x00010007`
  - `streaming=true`
  - RF scope cycles：`60 MHz -> 15.0`，`100 MHz -> 25.0`，`130 MHz -> 32.5`。
  - RF scope x-axis end：`0.25 us`。
  - RF scope points：`360/600/780`。
  - phase jitter over 20 frames：`0.0 deg`。
  - phase display：requested `0/45/90 deg`，RF scope phase `0/45/90 deg`。
  - baseband debug：`-40.756/-0.385/+28.929 MHz` for `60/100/130 MHz` signals at `100 MHz` center.
  - realtime rates：ADC observed counter `86.36 MS/s`，TX dry-run `~66.65 kpacket/s`，`~557.71 MB/s`。
  - `UDP_DRY_RUN=true`，`QSFP_LINK_UP=false`。

- PYNQ Stage 10 regression smoke：
  ```bash
  sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_astronomer_rf_console_check.py --signal-mhz 200 --center-mhz 180 --bw-mhz 100 --phase-step-deg 45 --time-window-us 0.25 --timeout 2.0
  ```
  结果：PASS。

- Jupyter 发布：
  - 远端入口存在：`/home/xilinx/jupyter_notebooks/t510_fengine/notebooks/13_astronomer_rf_observation_console.ipynb`。
  - 远端 bitstream SHA256 仍为 Stage 10 bit：`dd01ce4fc2eb6c4b125b53989fc417980ad2c6dbc28619e368347e74d4fa4cda`。

## 阶段衔接说明

- 下一阶段可依赖：
  - `CORE_VERSION=0x00010007`。
  - notebook 13 的主示波器已经是 RF 等效波形，时间窗口严格等于用户设置。
  - 主 RF scope 周期数由配置的测试单音 RF 频率决定，观测中心变化只影响 spectrum 和 baseband debug。
  - 主 RF scope phase 已由配置锁定，不再随每帧 FFT phase 大幅抖动。
  - `baseband_scope` 可作为工程调试图使用，用于观察 ADC 下变频后的 I/Q。
- 下一阶段不能依赖：
  - RF scope 是由 ADC IQ 幅度和配置 RF 频率生成的 RF 等效显示，不是 4.9152 GS/s 原始 RF 采样波形。
  - Phase slider 现在在显示层稳定可控，但模拟链路的科学级相位标定仍未完成。
  - `50-350 MHz` 全带 RF 频率/幅度/相位标定仍未完成。
  - CH1..CH7 仍不能声明 analog verified。
- 剩余风险：
  - baseband peak 仍有 Stage 10 已知的未标定 RF residual，后续应做 observation calibration。
  - 浏览器端长期 live soak 和自动截图仍未做。
- 推荐入口命令：
  ```bash
  cd /home/xilinx/t510_fengine_bringup
  source /etc/profile.d/xrt_setup.sh
  sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_astronomer_rf_console_check.py --stage11-scope-check --center-mhz 100 --signals-mhz 60,100,130 --bw-mhz 100 --time-window-us 0.25 --timeout 2.0
  ```
  Jupyter：打开 `http://192.168.100.117/lab` 或 `http://192.168.100.117:9090/lab`，进入 `t510_fengine/notebooks/13_astronomer_rf_observation_console.ipynb`。

## AI 接续提示

- 判断 Stage 11 是否可用，优先看 notebook 13 主图标题 `RF-equivalent scope`、`analysis["rf_scope"]`、`analysis["baseband_scope"]` 和 `--stage11-scope-check` 是否 PASS。
- 不要再用 baseband offset 驱动主示波器周期数；baseband 只能作为调试副图。
- 如果用户说波形窗口不对，先检查 RF scope cycles 是否等于 `signal_mhz * time_window_us`。
- 不要把 RF scope 说成原始 RF ADC 采样；它是 RF 等效显示。

## 阻塞项

- 科学级 RF 频率/幅度/相位标定未完成。
- CH1..CH7 未接物理模拟闭环。
- 浏览器端 Jupyter live refresh 未做自动截图/长时间稳定性验收。
- CMAC/QSFP 真实链路、交换机、接收节点 pcap 仍未完成。
