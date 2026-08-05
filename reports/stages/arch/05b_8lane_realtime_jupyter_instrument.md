# Stage 5b: 8-Lane Realtime Jupyter Instrument

## 阶段目标

在不改 RTL、不重新生成 bitstream 的前提下，把 Stage 5a 的单路 Jupyter 仪器扩展成接近顶层设计示例的 8 路虚拟示波器/频谱仪。

本阶段目标是网页仪器与 8 路 preview/control 闭合；不是 8 路模拟链路闭合。当前只有 DAC0 -> ADC0 有物理连接。

## 输入基线

- Stage 5 overlay 已验收通过：`CORE_VERSION=0x00010003`。
- Stage 5a 已发布单路 Jupyter 仪器：`09_single_board_virtual_instrument.ipynb`。
- 顶层设计要求：PYNQ preview 应提供多路虚拟示波器、频谱仪、DAC frequency/phase/amplitude 控制和 metadata readout。
- PYNQ 目标：`xilinx@192.168.100.117`。

## 完成内容

- 新增 `notebooks/10_8lane_realtime_virtual_instrument.ipynb`：
  - 一键加载 Stage 5 overlay。
  - 一键初始化 `tcxo_10mhz + free_run + mode=spec`。
  - 同页集成 `frequency_mhz`、`dac_rate_mhz`、`amplitude`、`phase_deg_per_channel`、`visible_channels`、`preview_samples`、`refresh_interval`、`start/stop live`。
  - Scope 区域显示多路时域叠加；Spectrum 区域显示 8 路 preview 软件 FFT peak、peak MHz、phase，并绘制 DAC reference line。
  - 状态栏显示 `CORE_VERSION`、`sample0`、`input_mask`、`UDP_DRY_RUN`、`QSFP_LINK_UP`、FIFO high-water 和通道验收标签。
  - 实时刷新使用 `ipywidgets + asyncio` 轮询，不引入新前端依赖。
- 扩展 `python/t510_fengine.py`：
  - `dac_phase_step_from_frequency(freq_hz, dac_sample_rate_hz=245_760_000)`。
  - `configure_dac_tone_bank(freq_hz, amplitude, phase_deg_per_channel, enable_mask, ...)`。
  - `capture_preview_spectrum(..., n=...)` 支持实时低成本 FFT。
- 新增 `scripts/pynq_8lane_instrument_check.py`：
  - 配置 8 路 DAC tone bank。
  - 抓取 `capture_preview(input_mask=0xff, n=512)`，确认 8 路 preview buffer 都可读。
  - 使用 debug FFT 对 CH0 做物理闭环严格门禁，默认稳定频点为 `5 MHz`。
  - `20 MHz` 仍可配置和显示，但当前自动门禁只给 warning，不把高频 exact peak 作为失败条件。
- 更新 `scripts/pynq_publish_jupyter_instrument.sh` 的发布提示，Stage 5b 默认入口改为 notebook 10。

## 验证证据

- 本地检查：
  ```bash
  python3 -m py_compile python/t510_fengine.py scripts/pynq_8lane_instrument_check.py
  python3 -m json.tool notebooks/10_8lane_realtime_virtual_instrument.ipynb >/dev/null
  ```
  结果：`STAGE5B_LOCAL_OK`，notebook code cell compile OK。
- API 频率换算：
  - `20 MHz` at API default `245.76 MHz` -> `phase_step=0x14d55555`。
  - Stage 5b 默认严格验收频点 `5 MHz` -> `phase_step=0x05355555`。
- 板端严格 smoke：
  ```bash
  cd /home/xilinx/t510_fengine_bringup
  source /etc/profile.d/xrt_setup.sh
  sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_8lane_instrument_check.py --channels 8 --samples 512 --timeout 2.0
  ```
  结果：`PASS`。
- 严格 smoke 关键读回：
  - `core_version=0x00010003`
  - `streaming=true`
  - `rfdc_current_valid_mask=0xffff`
  - `preview.input_mask=0xff`
  - `preview.inputs=[0,1,2,3,4,5,6,7]`
  - `preview.count=512`
  - `preview.sample_rate_hz=61440000`
  - `UDP_DRY_RUN=true`
  - `QSFP_LINK_UP=false`
  - `tx_fifo_high_water_words=3`
  - CH0 debug FFT strict gate：requested `5.0 MHz`，measured `4.98 MHz`，`bin_delta=0.333`。
- 20 MHz 探索 smoke：
  ```bash
  sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_8lane_instrument_check.py --freq-mhz 20 --channels 8 --samples 512 --timeout 2.0
  ```
  结果：`PASS` with warning。当前板端 debug FFT measured `7.740 MHz`，preview global peak measured `22.800 MHz`，所以 exact CH0 high-frequency gate 被跳过。
- Jupyter 发布：
  - 目录：`/home/xilinx/jupyter_notebooks/t510_fengine`
  - 默认入口：`t510_fengine/notebooks/10_8lane_realtime_virtual_instrument.ipynb`
  - 旧入口保留：`t510_fengine/notebooks/09_single_board_virtual_instrument.ipynb`

## 阶段衔接说明

- 下一阶段可依赖：8 路 preview buffer 读回、8 路 DAC tone bank 控制、Jupyter 实时轮询 UI、CH0 低频物理闭环严格门禁、20 MHz 可作为人工探索频点。
- 下一阶段不能依赖：CH1..CH7 模拟链路闭环；preview 软件 FFT 的全局 peak 在高频点等于 DAC 设置频率；20 MHz exact physical peak 自动门禁。
- 剩余风险：高频 tone 下 preview/debug peak 受当前模拟链路、DDC/混叠或 spur 影响，仍需要单独的频率响应标定；浏览器端长时间运行未做自动截图验收。
- 推荐入口：
  ```bash
  cd /home/xilinx/t510_fengine_bringup
  source /etc/profile.d/xrt_setup.sh
  sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_8lane_instrument_check.py --channels 8 --samples 512 --timeout 2.0
  ```
  Jupyter：打开 `http://192.168.100.117/lab` 或 `http://192.168.100.117:9090/lab`，进入 `t510_fengine/notebooks/10_8lane_realtime_virtual_instrument.ipynb`。

## AI 接续提示

- 不要把 CH1..CH7 标记为 analog verified；它们目前只是 digital/control preview 可读。
- notebook 默认 `5 MHz` 是为了稳定自动验收；用户仍可把滑块调到 `20 MHz` 做人工观察。
- 若后续要恢复 `20 MHz` exact gate，先做 frequency response calibration，找出高频 peak 偏移来源。
- Stage 5b 没有改 RTL、没跑 Vivado、没 bump `CORE_VERSION`。

## 阻塞项

- CH1..CH7 尚无物理线缆闭环。
- 20 MHz exact peak 自动门禁未闭合，仅作为 warning/人工探索频点。
- 浏览器端长时间 live refresh 没有自动化截图验收。
