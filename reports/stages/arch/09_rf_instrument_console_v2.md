# Stage 9: F-engine RF Instrument Console v2

## 阶段目标

重做 DAC0 -> ADC0 的 Jupyter 实时虚拟仪器，不再沿用 Stage 8 的 matplotlib 重绘式 notebook。目标是在一个页面内提供 DAC 单音频率/幅度/相位控制、ADC center/BW 显示控制、实时示波器、实时频谱仪、共享 `sample0` 相位基点和状态栏，并让这套 backend 成为后续 F-engine 监控面板的公共入口。

本阶段不改 RTL、不重新生成 bitstream、不 bump `CORE_VERSION`；复用 Stage 8 overlay `CORE_VERSION=0x00010006` 和 full-rate preview。

## 输入基线

- Stage 8 已完成 DAC0 -> ADC0 coherent smoke，preview sample rate 固定为 `245.76 MS/s`，AXIS beat rate 为 `61.44 MHz`。
- 顶层设计 `reports/arch/t510_fengine_refined_architecture_v0_3/t510_fengine_refined_architecture_v0_3.html` 要求 PYNQ 提供多通道虚拟示波器/频谱仪，并在同一界面内集成 DAC tone frequency、phase、amplitude、visible channels 和 live refresh。
- 用户反馈 Stage 8 notebook 问题：
  - DAC 输出频率和 ADC center/BW 控件不够清晰。
  - 实时刷新不足。
  - 相位滑块和共同对齐基点不成熟。
  - 仪器形态应服务整个 F-engine，不应继续复制一次性 notebook 逻辑。
- PYNQ 目标：`xilinx@192.168.100.117`。

## 完成内容

- Python 公共 backend：
  - `T510FEngine.configure_dac_tone_bank()` 新增 `phase_offset_deg`，让 DAC0 也能随相位滑块移动。
  - 新增 `apply_rf_instrument_config(center_hz, bw_hz, tone_hz, amplitude, phase_deg, enable_mask, ...)`，只在 Apply/init 时写 RFDC/DAC 并 reset DAC phase epoch。
  - 新增 `capture_preview_fast(input_mask, n)`，使用 PYNQ `MMIO.array` 的 numpy slice 读取 preview buffer，替代逐 word AXI-Lite read。
  - 新增 `compute_scope_spectrum(preview, display_bw_hz, phase_ref_input)`，统一输出 scope traces、spectrum traces、baseband/RF peak、coherent phase、delta phase、RMS、clip 和 SNR。
  - 频谱分析使用 zero-padded FFT 和 log-power interpolation，修正 512 点 FFT 下的频率显示粗糙问题。
- Jupyter：
  - 新增稳定入口 `notebooks/12_rf_instrument_console_v2.ipynb`。
  - UI 使用 `ipywidgets + plotly FigureWidget`，保留持久 trace，只更新数据，不再每帧重建 matplotlib 图。
  - 同页控件包含 Load、Init、Apply RF、Phase reset、Capture、Start Live、Stop Live。
  - DAC 控件包含 tone frequency MHz、amplitude %FS、phase deg、visible channels。
  - ADC/显示控件包含 center frequency MHz、display BW MHz、samples、refresh Hz、phase ref input。
  - Scope 以 `sample0` 为共同基点显示 I waveform；Spectrum 同时显示 baseband MHz 和 `RF = center + baseband peak`。
  - 状态栏显示 `CORE_VERSION`、streaming、RFDC NCO readback、preview sample rate、sample0、measured FPS、clip/max/RMS、CH0 physical verified 和 CH1..CH7 digital/control only。
- 板端 smoke：
  - 新增 `scripts/pynq_rf_instrument_v2_check.py`，覆盖 10/20/30 MHz DAC tone sweep、RFDC NCO readback、fast capture rate、phase epoch、phase movement、clipping 和 SNR。
- 发布：
  - `python/t510_fengine.py`、`scripts/pynq_rf_instrument_v2_check.py`、`notebooks/12_rf_instrument_console_v2.ipynb` 已同步到 `/home/xilinx/t510_fengine_bringup`。
  - `python/t510_fengine.py` 和 notebook 12 已发布到 `/home/xilinx/jupyter_notebooks/t510_fengine`。
  - `scripts/pynq_publish_jupyter_instrument.sh` 的推荐入口已更新为 notebook 12。

## 验证证据

- 本地软件：
  ```bash
  python3 -m py_compile python/t510_fengine.py scripts/pynq_rf_instrument_v2_check.py
  python3 -m json.tool notebooks/12_rf_instrument_console_v2.ipynb >/dev/null
  bash -n scripts/pynq_publish_jupyter_instrument.sh
  ```
  结果：PASS。

- PYNQ Stage 9 smoke：
  ```bash
  cd /home/xilinx/t510_fengine_bringup
  source /etc/profile.d/xrt_setup.sh
  sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_rf_instrument_v2_check.py --center-mhz 1500 --bw-mhz 100 --tone-start-mhz 10 --tone-stop-mhz 30 --phase-step-deg 45 --samples 512 --timeout 2.0
  ```
  结果：PASS。
  - `core_version=0x00010006`
  - `streaming=true`
  - `rfdc_current_valid_mask=0xffff`
  - RFDC NCO configured：ADC blocks `8`，DAC blocks `8`；ADC readback `-1500 MHz`，DAC readback `+1500 MHz`。
  - fast preview/analysis rate：`143.24 captures/s` for 512 samples。
  - 10 MHz tone：peak `-9.961805 MHz`，absolute error `38.2 kHz`，SNR `48.32 dB`，no clipping。
  - 20 MHz tone：peak `-20.060567 MHz`，absolute error `60.6 kHz`，SNR `43.10 dB`，no clipping。
  - 30 MHz tone：peak `-30.140303 MHz`，absolute error `140.3 kHz`，SNR `35.84 dB`，no clipping。
  - phase check：requested `45.0 deg`，measured delta `61.15 deg`，phase error `16.15 deg`；`DAC_PHASE_EPOCH` from `5` to `6`。

## 阶段衔接说明

- 下一阶段可依赖：
  - Stage 9 notebook 入口：`t510_fengine/notebooks/12_rf_instrument_console_v2.ipynb`。
  - `T510FEngine` 的 RF instrument backend 是后续监控公共入口，不需要在新 notebook 中重新复制 capture/FFT/status 逻辑。
  - DAC tone frequency、amplitude、phase 和 ADC center/BW 显示语义已在同一 API 中固定。
  - live loop 可以只做 fast capture + FFT + Plotly trace update；硬件配置只在 Apply/init 时写入。
  - `sample0` 是 coherent phase 的共同基点；相位显示应继续使用 `compute_scope_spectrum()` 返回的 coherent/delta phase 字段。
- 下一阶段不能依赖：
  - Stage 9 不改变 RTL，不提升 RFDC/preview 硬件吞吐，不声明 DDR snapshot 或硬件连续流式示波器完成。
  - ADC BW 仍是显示/分析窗口，不动态改变 RFDC decimation/interpolation。
  - CH1..CH7 仍不能声明 analog verified。
  - 浏览器端长时间 live 运行还没有自动截图或 soak test。
  - CMAC/QSFP 真实交换机收包仍不属于本阶段。
- 剩余风险：
  - 30 MHz 点在 512 samples 下误差约 `140.3 kHz`，已满足 smoke 门限，但后续做科学级频率/相位标定时需要更长 capture 或更严格 estimator。
  - Plotly FigureWidget 在 PYNQ Jupyter 中依赖板上 `plotly 5.9.0` 和 `ipywidgets 7.7.1`；本阶段已做 notebook JSON 与 backend smoke，但未做浏览器截图自动验收。
  - DAC0 -> ADC0 幅度仍偏低，Stage 9 只门禁 no clipping、SNR 和可见单音移动，不做绝对功率标定。
- 推荐入口命令：
  ```bash
  cd /home/xilinx/t510_fengine_bringup
  source /etc/profile.d/xrt_setup.sh
  sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_rf_instrument_v2_check.py --center-mhz 1500 --bw-mhz 100 --tone-start-mhz 10 --tone-stop-mhz 30 --phase-step-deg 45 --samples 512 --timeout 2.0
  ```
  Jupyter：打开 `http://192.168.100.117/lab` 或 `http://192.168.100.117:9090/lab`，进入 `t510_fengine/notebooks/12_rf_instrument_console_v2.ipynb`。

## AI 接续提示

- 判断 Stage 9 是否可用，先看 `CORE_VERSION=0x00010006`、notebook 12、`capture_preview_fast()` 是否走 `fast_path=True`、smoke 是否 PASS。
- 如果 Jupyter 中改 DAC frequency 后频谱不移动，先确认用户点击了 Apply RF；Stage 9 规则是不在滑块变化时自动重配硬件。
- ADC center/BW 控件语义：center 走 RFDC NCO，BW 是显示/分析窗口；不要把 BW 描述成 RFDC decimation 动态切换。
- 频谱负号来自当前 ADC/DAC mixer 符号约定；验收时使用 absolute baseband frequency 或 RF marker 判断 tone 是否按设置移动。
- 后续 PFB、TX route、QSFP status 面板应复用 `T510FEngine` 的 status/capture 模型，不要再写各自的逐 word preview reader。
- 不要在脚本、notebook 或报告中记录 SSH 明文密码。

## 阻塞项

- 尚未做浏览器端自动截图/长时间 live soak test。
- 尚未做 CH1..CH7 analog loopback。
- 尚未做 100 MHz 带内扫频、幅度平坦度、IQ imbalance、image rejection、SFDR 和绝对功率标定。
- 尚未做 CMAC/QSFP 真实链路、交换机、接收节点 pcap。
