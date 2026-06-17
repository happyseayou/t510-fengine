# Stage 8: DAC0-ADC0 Coherent RF Instrument Closure

## 阶段目标

先把 DAC0 -> ADC0 在内部时钟 `tcxo_10mhz + free_run` 下闭合成可信的网页虚拟示波器/频谱仪：频率显示正确，预览采样率语义正确，波形接近单音正弦，刷新足够实时，多通道相位以共同 `sample0` 为基点。

本阶段只声明 DAC0 -> ADC0 物理闭环通过；CH1..CH7 保留单音控制和 preview metadata，但仍是未物理验证通道。本阶段不做 QSFP/交换机收包。

## 输入基线

- Stage 7 已完成 UDP frame preflight 和 8+8 静态路由 dry-run，`CORE_VERSION=0x00010005`。
- Stage 5b 的 Jupyter 8 路仪器已可显示 scope/spectrum，但 20 MHz 高频点存在显示频率/自动门禁不一致问题。
- 顶层设计要求 PYNQ 提供虚拟示波器、频谱仪、DAC 单音控制、中心频率和带宽控制。
- T510 RF 裸机手册关键约束：
  - RFDC ADC/DAC sample rate：`4.9152 GS/s`。
  - decimation/interpolation：`20x`。
  - 基带采样率：`245.76 MS/s`。
  - AXIS beat rate：`61.44 MHz`，每个 64-bit RFDC AXIS beat 含 4 个连续 16-bit 样点。
  - ADC0 I = `m00_axis_tdata`，ADC0 Q = `m01_axis_tdata`。
  - DAC AXIS word layout：`{q3,i3,q2,i2,q1,i1,q0,i0}`。
- PYNQ 目标：`xilinx@192.168.100.117`。

## 完成内容

- RTL：
  - `rtl/t510_dac_loopback_source.sv`：把旧 triangle tone 改为 8 路 single-tone sine DDS；新增 DAC phase epoch/reset，禁用通道输出 0。
  - `rtl/rfdc_adc_axis_adapter.sv`：保留既有 61.44 MHz 主 F-engine beat 路径，新增 full-rate preview 输出；`m_preview_sample0 = axis_sample_count * 4`。
  - `rtl/multi_preview_observer.sv`：每个 RFDC ADC beat 写入 4 个连续 preview 样点，buffer 地址兼容 `0x2800 + channel*0x1000 + sample*4`。
  - `rtl/feng_ctrl_axi.sv`：`CORE_VERSION=0x00010006`；新增 `0x060c DAC_PHASE_EPOCH`、`0x071c PREVIEW_SAMPLE_RATE_HZ=245760000`、`0x0720 PREVIEW_AXIS_BEAT_RATE_HZ=61440000`、`0x0724 PREVIEW_MODE=1`。
- Python：
  - `T510FEngine` 在 PYNQ 未自动把 RFDC IP 绑定为 `xrfdc.RFdc` 时，自动用 `xrfdc.RFdc(description)` 重绑。
  - `configure_rfdc_center_frequency(center_freq_hz, bandwidth_hz, require=True)` 真实配置 RFDC ADC/DAC mixer/NCO：ADC NCO 为 `-center`，DAC NCO 为 `+center`，并执行 mixer update/NCO phase reset。
  - `dac_phase_step_from_frequency()` 和 DAC tone bank 统一按 `245.76 MS/s` 基带采样率计算，`20 MHz -> 0x14d55555`。
  - `capture_preview()` 返回 full-rate metadata：`sample_rate_hz=245760000`、`axis_beat_rate_hz=61440000`、`preview_mode=1`、`sample0`、`phase_ref_input`、`bandwidth_hz`、`center_freq_hz`。
  - 频谱 peak 显示增加 log-power 抛物线插值，避免 1024 点 FFT 的 `240 kHz/bin` 粗粒度把 20 MHz 显示为 19.92 MHz。
- Jupyter：
  - 新增 `notebooks/11_dac_adc_coherent_scope_spectrum.ipynb` 作为 Stage 8 稳定入口。
  - 控件包含 center MHz、BW MHz 默认 `100 MHz`、single-tone frequency 默认 `20 MHz`、amplitude、per-channel phase、visible channels、samples、refresh interval、phase ref。
  - live loop 只执行 preview capture + FFT + 轻量状态读取；RFDC/DAC 配置只在 Apply/init 时写入。
- 板端脚本：
  - 新增 `scripts/pynq_dac_adc_coherent_check.py`，门禁 DAC0 -> ADC0 物理闭环：RFDC NCO、streaming、preview rate、FFT peak、clipping、SNR、sine-fit residual、capture refresh。
- 发布：
  - overlay/python/scripts/notebooks 已同步到 `/home/xilinx/t510_fengine_bringup`。
  - overlay/python/notebooks 已发布到 `/home/xilinx/jupyter_notebooks/t510_fengine`。

## 验证证据

- 本地软件：
  ```bash
  python3 -m py_compile python/t510_fengine.py scripts/pynq_dac_adc_coherent_check.py
  python3 -m json.tool notebooks/11_dac_adc_coherent_scope_spectrum.ipynb >/dev/null
  ```
  结果：PASS。
- 本地 XSim：
  ```bash
  ./scripts/run_xsim_batch.sh tb_t510_dac_loopback_source tb_rfdc_fullrate_preview tb_feng_ctrl_axi tb_t510_fengine_top_smoke
  ```
  结果：全部 PASS。
  - `tb_t510_dac_loopback_source`：sine DDS、I/Q 90 度、phase reset、phase_step 通过。
  - `tb_rfdc_fullrate_preview`：ADC0 I/Q lane unpack、4 样点顺序、`sample0=axis_beat*4` 通过。
  - `tb_feng_ctrl_axi`：`CORE_VERSION=0x00010006`、DAC epoch 和 preview metadata register readback 通过。
  - `tb_t510_fengine_top_smoke`：Stage 7 packet/PFB 路径和 Stage 8 preview metadata 通过。
- Vivado：
  - synthesis：0 errors，0 critical warnings。
  - implementation：route complete，0 errors，0 critical warnings。
  - bitgen：0 errors，0 critical warnings；普通 warnings 包含 DSP pipeline/power 建议和 RFDC unused status nets。
  - post-route timing：`WNS=+2.971 ns`，`WHS=+0.014 ns`，失败端点 `0/70760`。
  - bitstream：`overlay/t510_fengine.bit`，SHA256 `fc4ce70ed281b004647db4549045152b180094882f277db5f81a103d125a082f`。
- PYNQ 同步/轻量检查：
  - 远端 bitstream SHA256 与本地一致：`fc4ce70ed281b004647db4549045152b180094882f277db5f81a103d125a082f`。
  - 清理并修复远端 `__pycache__` 权限后，远端 Python 轻量检查 PASS。
- PYNQ Stage 8 验收：
  ```bash
  cd /home/xilinx/t510_fengine_bringup
  source /etc/profile.d/xrt_setup.sh
  sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_dac_adc_coherent_check.py --center-mhz 1500 --bw-mhz 100 --tone-mhz 20 --samples 1024 --timeout 2.0
  ```
  结果：PASS。
  - `core_version=0x00010006`
  - `streaming=true`
  - `rfdc_current_valid_mask=0xffff`
  - RFDC NCO configured：ADC blocks `8`，DAC blocks `8`；ADC readback `-1500 MHz`，DAC readback `+1500 MHz`。
  - preview：`sample_rate_hz=245760000`，`axis_beat_rate_hz=61440000`，`preview_mode=1`，`sample0=1056313932`。
  - DAC：`tone_freq_mhz=20.0`，`phase_step=0x14d55555`，`phase_epoch=1`。
  - CH0 FFT：raw nearest bin `-19.920 MHz`；interpolated peak `-20.003053 MHz`；absolute error `3.1 kHz`。
  - CH0 waveform quality：no clipping，`max_abs_code=207`，`SNR=44.39 dB`，sine-fit residual ratio `0.577`，PASS threshold `<=0.85`。
  - preview refresh in smoke：`44.19 captures/s` for 3 captures of 1024 samples。
- Jupyter 发布路径确认：
  - `/home/xilinx/jupyter_notebooks/t510_fengine/notebooks/11_dac_adc_coherent_scope_spectrum.ipynb`
  - `/home/xilinx/jupyter_notebooks/t510_fengine/overlay/t510_fengine.bit`

## 阶段衔接说明

- 下一阶段可依赖：
  - `CORE_VERSION=0x00010006`。
  - DAC0 -> ADC0 在 `tcxo_10mhz + free_run` 下通过 20 MHz 单音闭环验收。
  - RFDC center frequency 可通过 `xrfdc` 真实配置，Stage 8 已验证 center `1500 MHz` readback。
  - preview sample rate 语义已固定为 `245.76 MS/s`；AXIS beat rate 单独标记为 `61.44 MHz`。
  - preview `sample0` 是基带样点号，可作为多通道相位对齐共同基点。
  - Jupyter `11_dac_adc_coherent_scope_spectrum.ipynb` 是当前虚拟示波器/频谱仪稳定入口。
  - Stage 7 packet/PFB/TX preflight 路径未破坏，top smoke 已回归。
- 下一阶段不能依赖：
  - CH1..CH7 模拟闭环；目前只有 DAC0 -> ADC0 physical loopback verified。
  - 科学级 RF 幅相标定、绝对功率标定、完整 100 MHz 带内平坦度。
  - Jupyter 浏览器端长时间运行截图自动验收。
  - CMAC/QSFP 真实发包或交换机/接收节点收包。
- 剩余风险：
  - CH0 幅度读回约 `207 codes`，说明当前闭环链路/衰减设置下信号幅度较低；本阶段只门禁频率、相干采样、SNR 和基本正弦质量。
  - sine-fit residual 已通过工程阈值，但仍不是科学级失真指标；后续需要更严格的 IQ imbalance、image rejection、SFDR 和带内标定。
  - RFDC block discovery 依赖 PYNQ `xrfdc.RFdc(description)`；若 PYNQ 镜像更新后自动绑定行为改变，应优先检查 `T510FEngine._resolve_rfdc_ip()`。
- 推荐入口命令：
  ```bash
  cd /home/xilinx/t510_fengine_bringup
  source /etc/profile.d/xrt_setup.sh
  sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_dac_adc_coherent_check.py --center-mhz 1500 --bw-mhz 100 --tone-mhz 20 --samples 1024 --timeout 2.0
  ```
  Jupyter：打开 `http://192.168.100.117/lab` 或 `http://192.168.100.117:9090/lab`，进入 `t510_fengine/notebooks/11_dac_adc_coherent_scope_spectrum.ipynb`。

## AI 接续提示

- 判断是否进入 Stage 8，优先看 `CORE_VERSION=0x00010006`、`PREVIEW_SAMPLE_RATE_HZ=245760000`、`PREVIEW_MODE=1`、`DAC_PHASE_EPOCH` 增长和 RFDC NCO readback。
- 20 MHz 的 raw FFT bin 可能显示为 `19.92 MHz`，这是 1024 点/245.76 MS/s 下的 bin 分辨率；应使用插值后的 `peak_mhz` 或配置频率做判据。
- 如果板端报 `adc_blocks=0 dac_blocks=0`，优先检查 PYNQ 是否把 RFDC IP 绑定成 `DefaultIP`；当前 API 会自动用 `xrfdc.RFdc(description)` 重绑。
- 不要把 CH1..CH7 标记为 analog verified；它们仍然只可声明为 digital/control only。
- 不要在脚本、notebook 或报告中记录 SSH 明文密码。

## 阻塞项

- CH1..CH7 未接物理模拟闭环。
- 尚未做 100 MHz 带内扫频、幅度平坦度、IQ imbalance、image rejection、SFDR 和绝对功率标定。
- 浏览器端 Jupyter live refresh 未做自动截图/长时间稳定性验收。
- CMAC/QSFP 真实链路、交换机、接收节点 pcap 仍留给 Stage 7a。
