# Stage 12: Stable Spectrum/Amplitude + Selectable Waterfall

## 阶段目标

修复 Stage 11 后仍存在的主频谱和幅度显示抖动：主显示改为稳定观测视图，raw 单帧读数保留在高级诊断中；新增可选通道瀑布流，默认 CH0、60 帧历史。

本阶段不改 RTL、不重新生成 bitstream、不 bump `CORE_VERSION`；继续使用 Stage 10/11 overlay `CORE_VERSION=0x00010007`。

## 输入基线

- Stage 11 已闭合 RF 等效主示波器：时间窗口和相位稳定，`60/100/130 MHz` 在 `0.25 us` 下周期数正确。
- 用户反馈：主波形幅度和频谱显示仍会接近 `50%` 抖动；需要新增瀑布流图。
- notebook 推荐入口仍为 `notebooks/13_astronomer_rf_observation_console.ipynb`。
- 当前板端条件仍为无 QSFP：`UDP_DRY_RUN=1`，`QSFP_LINK_UP=0` 是预期状态。

## 完成内容

- Python backend：
  - `compute_observation_view()` 保留 raw spectrum 输出，并新增每通道 `peak_dbfs`、`noise_floor_dbfs`、`rms_dbfs`、`valid_frame`、`reject_reason`。
  - 新增 `ObservationSpectrumStabilizer`，用线性功率 EMA 做主频谱平滑，默认 `alpha=0.25`。
  - 坏帧拒收规则：clipped、SNR 低于阈值、peak 频率跳变超过 `2 MHz`、peak 幅度跳变超过 `6 dB`、RMS 幅度跳变超过 `6 dB`。
  - 被拒收帧只进入 raw 诊断，不更新 smoothed 主显示和 waterfall 历史。
- Jupyter：
  - `notebooks/13_astronomer_rf_observation_console.ipynb` 更新为 Stage 12 入口。
  - 增加 `频谱平滑`、`平滑强度`、`瀑布通道`、`瀑布历史帧`、`Reset history` 控件。
  - 主 Spectrum 默认显示 smoothed spectrum；高级面板保留 `Raw spectrum` toggle 和 raw peak/RMS/reject reason。
  - 新增 Waterfall 图，x 轴固定为 `center ± BW/2`，y 轴为最近帧序号，颜色范围复用频谱 dBFS 控件。
  - 切换瀑布通道、修改历史深度、Apply RF/init/load overlay 时自动清空平滑和瀑布历史，避免不同配置混帧。
  - 主 RF scope 仍使用 Stage 11 的配置频率/相位锁定；仅用 smoothed peak 对显示幅度做轻量缩放，不改变频率或相位语义。
  - 性能修正 v2：主频谱送 Plotly 前默认峰值保留降采样到 `384` 点；RF scope 默认 `512` 点；Waterfall 默认 `192` 个频点、`30` 帧历史、`0.8 Hz` 刷新；状态/速率寄存器默认 `1 Hz` 读取。
  - Live loop 增加 `UI让步 ms`，默认每帧至少 `30 ms` 让出 Jupyter event loop，避免处理时间超过目标周期时 `sleep(0)` 导致消息越积越多。
  - 主图改用 `Scattergl`；基带调试图默认不实时刷新；layout/title 只在显示配置变化时更新，不再每帧推送。
- Board smoke：
  - `scripts/pynq_astronomer_rf_console_check.py` 新增 `--stage12-stability-check`。
  - 固定 signal/center/BW 连续采集，比较 raw 与 smoothed peak/RMS p-p 抖动，验证瀑布历史达到 60 帧。
  - 输出 rejected frame 摘要，确认坏帧不会污染主历史。
- 发布：
  - 更新后的 `python/`、`scripts/`、`notebooks/` 已同步到 `/home/xilinx/t510_fengine_bringup`。
  - 更新后的 notebook 13 已发布到 `/home/xilinx/jupyter_notebooks/t510_fengine`。

## 验证证据

- 本地软件：
  ```bash
  python3 -m py_compile python/t510_fengine.py scripts/pynq_astronomer_rf_console_check.py
  python3 -m json.tool notebooks/13_astronomer_rf_observation_console.ipynb >/dev/null
  bash -n scripts/pynq_publish_jupyter_instrument.sh
  ```
  结果：PASS。

- PYNQ Stage 12 stability check：
  ```bash
  cd /home/xilinx/t510_fengine_bringup
  source /etc/profile.d/xrt_setup.sh
  sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_astronomer_rf_console_check.py --stage12-stability-check --signal-mhz 100 --center-mhz 100 --bw-mhz 100 --frames 60 --timeout 2.0
  ```
  结果：PASS。
  - `core_version=0x00010007`
  - `accepted_frames=60`
  - `attempts=65`
  - `rejected_frames=5`
  - rejected reason：`rms_jump>6.0dB`
  - raw peak p-p jitter：`7.06%`
  - smoothed peak p-p jitter：`2.88%`
  - raw RMS p-p jitter：`81.53%`
  - smoothed RMS p-p jitter：`25.41%`
  - waterfall：CH0，`60` 帧，x range `50..150 MHz`。
  - realtime rates：ADC observed counter `86.35 MS/s`，TX dry-run `~66.64 kpacket/s`，`~557.64 MB/s`。
  - `UDP_DRY_RUN=true`，`QSFP_LINK_UP=false`。

- PYNQ Stage 11 regression：
  ```bash
  sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_astronomer_rf_console_check.py --stage11-scope-check --center-mhz 100 --signals-mhz 60,100,130 --bw-mhz 100 --time-window-us 0.25 --timeout 2.0
  ```
  结果：PASS。
  - RF scope cycles：`60 MHz -> 15.0`，`100 MHz -> 25.0`，`130 MHz -> 32.5`。
  - RF scope x-axis end：`0.25 us`。
  - phase jitter over 20 frames：`0.0 deg`。
  - phase display：requested `0/45/90 deg`，RF scope phase `0/45/90 deg`。

- PYNQ Stage 12 backend performance check：
  ```bash
  sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_astronomer_rf_console_check.py --stage12-performance-check --signal-mhz 100 --center-mhz 100 --bw-mhz 100 --frames 40 --timeout 2.0 --no-download
  ```
  结果：PASS。
  - `capture_ms_avg=3.38`
  - `analysis_ms_avg=5.16`
  - `display_reduce_ms_avg=1.81`
  - `total_backend_ms_avg=10.35`
  - backend estimate：`96.65 FPS`
  - 判断：板端采集/FFT/平滑降采样不是当前 Jupyter 卡顿瓶颈，主要瓶颈在浏览器 Plotly/Jupyter comm。

- Jupyter 发布：
  - 远端入口存在：`/home/xilinx/jupyter_notebooks/t510_fengine/notebooks/13_astronomer_rf_observation_console.ipynb`。
  - 远端 bitstream SHA256：`dd01ce4fc2eb6c4b125b53989fc417980ad2c6dbc28619e368347e74d4fa4cda`。
  - 性能修正 v2 后的 notebook 已重新发布，远端 JSON 校验 PASS。

## 阶段衔接说明

- 下一阶段可依赖：
  - `CORE_VERSION=0x00010007`。
  - notebook 13 已具备稳定主频谱、平滑主幅度状态、raw 高级诊断和 CH-selectable waterfall。
  - Stage 11 RF 等效 scope 语义仍成立：时间窗口、周期数和相位锁定没有被 Stage 12 改动破坏。
  - `ObservationSpectrumStabilizer` 可作为后续 F-engine 监控面板的公共显示稳定器。
- 下一阶段不能依赖：
  - Smoothed spectrum/waterfall 是显示稳定后的观测视图，不是科学级功率标定结果。
  - RMS 抖动已被坏帧拒收和平滑显著压低，但模拟链路噪声/干扰来源仍未定位。
  - CH1..CH7 仍只能声明 digital/control preview 可读，不能声明 analog verified。
  - CMAC/QSFP 真实链路、交换机收包、接收节点 pcap 仍未完成。
- 剩余风险：
  - 浏览器端长时间 live soak 和自动截图尚未做。
  - Waterfall 第一版只维护一个选中通道；多通道并行 waterfall 和持久化记录仍未做。
  - `50-350 MHz` 全带 RF 幅相/功率标定仍未完成。
- 推荐入口命令：
  ```bash
  cd /home/xilinx/t510_fengine_bringup
  source /etc/profile.d/xrt_setup.sh
  sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_astronomer_rf_console_check.py --stage12-stability-check --signal-mhz 100 --center-mhz 100 --bw-mhz 100 --frames 60 --timeout 2.0
  ```
  Jupyter：打开 `http://192.168.100.117/lab` 或 `http://192.168.100.117:9090/lab`，进入 `t510_fengine/notebooks/13_astronomer_rf_observation_console.ipynb`。

## AI 接续提示

- Stage 12 判断入口：`--stage12-stability-check` 是否 PASS，以及 notebook 13 是否显示 `Waterfall` 图和 `频谱平滑/瀑布通道` 控件。
- 不要把 smoothed spectrum 当作 raw 测量；raw 单帧数据在高级面板 `Raw spectrum` 和脚本输出中保留。
- 如果用户继续反馈幅度跳动，先看 `rejected_preview`、`raw_peak_pp_fraction`、`smoothed_peak_pp_fraction`、`raw_rms_pp_fraction`、`smoothed_rms_pp_fraction`。
- 如果瀑布流看起来混乱，先确认 Apply/init/切换瀑布通道后 history 是否被清空，x 轴是否固定为 `center ± BW/2`。
- 如果 Jupyter live 仍卡顿，优先调低高级工程状态中的 `频谱显示点`、`波形显示点`、`瀑布频点`、`瀑布刷新 Hz`，保持 `状态刷新 Hz` 在 `1 Hz` 左右，并确认 `快速模式` 开启、`刷新基带图` 关闭。
- 不要在报告、notebook 或脚本里记录 SSH 明文密码。

## 阻塞项

- 科学级 RF 功率/相位/频率标定未完成。
- RMS 突跳的物理来源未定位；目前只在观测显示层拒收坏帧。
- CH1..CH7 未接物理模拟闭环。
- 浏览器端 Jupyter live refresh 未做长时间 soak。
- CMAC/QSFP 真实链路、交换机、接收节点 pcap 仍未完成。
