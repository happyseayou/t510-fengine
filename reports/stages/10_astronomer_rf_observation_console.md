# Stage 10: Astronomer RF Observation Console

## 阶段目标

重做 Stage 9 的 RF 仪表语义，把默认 Jupyter 入口改成面向天文学家的观测控制台。主界面只暴露测试单音 RF 频率、观测中心频率、观测带宽、时间窗口、幅度、相位、固定坐标范围和实时速率；NCO/baseband/sample0 等工程量只放在只读高级面板。

本阶段允许 RTL 小改并重新导出 overlay；`CORE_VERSION=0x00010007`。Stage 10 不做 CMAC/QSFP 真实收包，不声明科学级 RF 幅相/绝对频率标定完成。

## 输入基线

- Stage 9 已有 Plotly/Jupyter RF instrument console，但主控件仍偏 RF 工程视角，用户反馈 DAC 20 MHz 与 ADC center 1500 MHz 的语义不符合原始意图。
- 顶层设计资料：`reports/arch/t510_fengine_refined_architecture_v0_3/t510_fengine_refined_architecture_v0_3.html`，要求网页仪器像虚拟示波器/频谱仪一样直观，并最终成为 F-engine 监控入口。
- 用户约束：
  - 科学使用频段为 `50-350 MHz`。
  - DAC 输出为单音；ADC 通过观测中心和带宽去找尖峰。
  - 软件分析过采样可调，但不动态改变 RFDC decimation/interpolation。
  - 图的 x/y 坐标范围固定，不随信号跳动。
  - 相位滑块要能看到波形移动，并且有共同显示基点。
  - 实时界面要显示 ADC samples/s、UDP packets/s 和吞吐。
- PYNQ 目标：`xilinx@192.168.100.117`。

## 完成内容

- RTL：
  - `rtl/t510_dac_loopback_source.sv` 新增 `constant_phasor` DAC mode，phase step 为 0 时输出可重复的复常量相量，不再回落到默认 DDS 频率。
  - 保留旧 `single_tone` DDS mode 和 `0x0600..0x06ff` DAC 控制兼容。
  - `rtl/feng_ctrl_axi.sv` bump `CORE_VERSION` 到 `0x00010007`。
- Python backend：
  - `T510FEngine.apply_observation_instrument_config(...)` 固定天文学家语义：
    - `dac_signal_hz` 是测试单音 RF 频率，范围 `50-350 MHz`。
    - `observe_center_hz` 是观测中心频率，范围 `50-350 MHz`。
    - ADC NCO readback 期望为 `-observe_center_hz`，DAC NCO readback 期望为 `+dac_signal_hz`。
    - expected baseband peak 只作为高级只读字段：`dac_signal_hz - observe_center_hz`。
  - `compute_observation_view(...)` 输出 RF MHz 频轴、固定 BW 窗口、dBFS 频谱、phase-stabilized scope、peak RF MHz、相对相位、RMS/clip/SNR。
  - 观测频谱不再扣掉复均值；信号正好落在观测中心时，0 Hz offset 是有效尖峰。
  - `observation_capture_count()` 默认下限改为 `512` 点，避免 `0.25 us` 窗口下的频率估计过粗。
  - `read_realtime_rates()` 输出 ADC samples/s、SPEC/TIME packetizer、TX dry-run 和 frame-builder throughput。
- Jupyter：
  - 新增稳定入口 `notebooks/13_astronomer_rf_observation_console.ipynb`。
  - 主控件改为：测试单音 MHz、观测中心 MHz、观测带宽 MHz、软件过采样、时间窗口 us、幅度 %FS、相位 deg、Y 轴 ADC code、频谱 dBFS 范围、刷新 Hz。
  - Scope x/y 和 Spectrum x/y 坐标固定；Spectrum x 轴固定为 `center +/- BW/2`。
  - Apply 后等待 `200 ms`，phase-only 写入后等待 `150 ms`，避免 RFDC/NCO 切换瞬态进入第一帧显示。
  - 默认 phase-stabilized scope；高级面板保留 Raw preview toggle 和只读工程状态。
  - 状态栏显示 `CORE_VERSION`、streaming、RFDC NCO readback、sample0、preview FPS、ADC samples/s、UDP/SPEC/TX dry-run packets/s、UDP throughput、`UDP_DRY_RUN` 和 `QSFP_LINK_UP`。
- 板端 smoke：
  - 新增 `scripts/pynq_astronomer_rf_console_check.py`。
  - 对每个观测设置抓多帧并选择未削顶、SNR 最好的帧，避免 RFDC 重配瞬态导致偶发坏帧。
  - 默认 RF/baseband smoke 门限为 `750 kHz`，用于 Stage 10 bring-up 级观测控制台；科学级绝对频率标定留给后续阶段。
- 发布：
  - `overlay/`、`python/`、`scripts/`、`notebooks/` 已同步到 `/home/xilinx/t510_fengine_bringup`。
  - `overlay/`、`python/`、`notebooks/` 已发布到 `/home/xilinx/jupyter_notebooks/t510_fengine`。
  - `scripts/pynq_publish_jupyter_instrument.sh` 推荐入口已更新到 notebook 13。

## 验证证据

- 本地软件：
  ```bash
  python3 -m py_compile python/t510_fengine.py scripts/pynq_astronomer_rf_console_check.py
  python3 -m json.tool notebooks/13_astronomer_rf_observation_console.ipynb >/dev/null
  bash -n scripts/pynq_publish_jupyter_instrument.sh
  ```
  结果：PASS。

- 本地 XSim：
  ```bash
  ./scripts/run_xsim_batch.sh tb_t510_dac_loopback_source tb_feng_ctrl_axi tb_t510_fengine_top_smoke
  ```
  结果：全部 PASS。
  - `tb_t510_dac_loopback_source`：`constant_phasor`、旧 single-tone DDS、phase reset 通过。
  - `tb_feng_ctrl_axi`：`CORE_VERSION=0x00010007` 通过。
  - `tb_t510_fengine_top_smoke`：top smoke 通过。

- Vivado：
  - `impl_1` 状态：`write_bitstream Complete`。
  - `check_bitstream_readiness`：READY。
  - 0 errors，0 critical warnings。
  - post-route timing：`WNS=+2.339 ns`，`WHS=+0.010 ns`，失败端点 `0/70756`。
  - overlay bitstream SHA256：`dd01ce4fc2eb6c4b125b53989fc417980ad2c6dbc28619e368347e74d4fa4cda`。

- PYNQ Stage 10 smoke：
  ```bash
  cd /home/xilinx/t510_fengine_bringup
  source /etc/profile.d/xrt_setup.sh
  sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_astronomer_rf_console_check.py --signal-mhz 200 --center-mhz 180 --bw-mhz 100 --phase-step-deg 45 --time-window-us 0.25 --timeout 2.0
  ```
  结果：PASS。
  - `core_version=0x00010007`
  - `streaming=true`
  - `rfdc_current_valid_mask=0xffff`
  - RFDC NCO readback：ADC `-180 MHz`，DAC `+200 MHz`。
  - 观测中心 sweep：
    - center `180 MHz`：RF peak `199.366149 MHz`，baseband `+19.366149 MHz`，SNR `42.55 dB`。
    - center `200 MHz`：RF peak `199.446894 MHz`，baseband `-0.553106 MHz`，SNR `44.06 dB`。
    - center `220 MHz`：RF peak `199.358759 MHz`，baseband `-20.641241 MHz`，SNR `47.77 dB`。
  - 相位 smoke：requested `45 deg`，measured visible delta `90.41 deg`；`DAC_PHASE_EPOCH` from `5` to `6`。
  - 实时速率：ADC `86.37 MS/s` observed counter rate；SPEC/TX dry-run `~66.65 kpacket/s`；TX dry-run throughput `~557.7 MB/s`。
  - 无 QSFP 条件下：`UDP_DRY_RUN=true`，`QSFP_LINK_UP=false`。

- Jupyter 发布：
  - 远端入口存在：`/home/xilinx/jupyter_notebooks/t510_fengine/notebooks/13_astronomer_rf_observation_console.ipynb`。
  - 远端 bitstream SHA256 与本地一致：`dd01ce4fc2eb6c4b125b53989fc417980ad2c6dbc28619e368347e74d4fa4cda`。

## 阶段衔接说明

- 下一阶段可依赖：
  - `CORE_VERSION=0x00010007`。
  - notebook 13 是当前推荐网页入口：`t510_fengine/notebooks/13_astronomer_rf_observation_console.ipynb`。
  - 主界面语义已经固定为天文学家视角：测试单音 RF 频率、观测中心、观测带宽、时间窗口、幅度、相位和实时速率。
  - DAC 默认使用 `constant_phasor`，DAC RF 频率由 RFDC DAC NCO 控制；ADC 观测中心由 RFDC ADC NCO 控制。
  - Scope/Spectrum 固定坐标范围、phase-stabilized scope、多帧 smoke 过滤瞬态和实时速率读数可以作为后续 F-engine monitor 公共模型。
  - UDP/SPEC/TX dry-run 速率计数可以在无 QSFP 时作为吞吐可视化指标。
- 下一阶段不能依赖：
  - 不能声明科学级 RF 绝对频率标定完成。当前 200 MHz 单音在 180/200/220 MHz 观测中心下仍有约 `0.55-0.65 MHz` 的未标定 RF peak residual。
  - 不能声明 phase slider 的角度值已经科学标定；Stage 10 只门禁“可见移动”和 epoch 增长。
  - ADC samples/s 当前来自现有 RFDC sample counter 语义，显示为 observed counter rate；它不是 RFDC 物理 `245.76 MS/s` 的正式计量校准。
  - CH1..CH7 仍不能声明 analog verified。
  - CMAC/QSFP 真实链路、交换机、接收节点 pcap 不属于 Stage 10。
- 剩余风险：
  - RFDC 低频绝对 NCO/观测频轴需要做标定表或频率校正模型，尤其是 `50-350 MHz` 全带宽。
  - RFDC/NCO 重配后偶发第一帧坏帧；notebook 已加入 settle，smoke 已做多帧择优，但后续可进一步做 live UI 的坏帧抑制。
  - 目前浏览器端未做自动 screenshot/soak test；只完成 notebook JSON 和板端 backend smoke。
- 推荐入口命令：
  ```bash
  cd /home/xilinx/t510_fengine_bringup
  source /etc/profile.d/xrt_setup.sh
  sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_astronomer_rf_console_check.py --signal-mhz 200 --center-mhz 180 --bw-mhz 100 --phase-step-deg 45 --time-window-us 0.25 --timeout 2.0
  ```
  Jupyter：打开 `http://192.168.100.117/lab` 或 `http://192.168.100.117:9090/lab`，进入 `t510_fengine/notebooks/13_astronomer_rf_observation_console.ipynb`。

## AI 接续提示

- 判断 Stage 10 是否可用，优先看 `CORE_VERSION=0x00010007`、notebook 13、`constant_phasor` mode、`apply_observation_instrument_config()`、PYNQ smoke 是否 PASS。
- 不要把主界面退回 baseband/NCO 控件；这些只能作为高级只读信息。
- 主频率范围固定 `50-350 MHz`；观测带宽 UI 范围固定 `5-100 MHz`，且只是显示/分析窗口。
- Stage 10 的 RF peak residual 是已知未标定项，不要误判为 Jupyter UI 语义错误；下一步应规划 RF observation calibration，而不是让用户调中间变量。
- Phase slider 当前只声明可见移动；如果要把输入角度和观测相位一一对应，需要新阶段做幅相标定。
- 不要在脚本、notebook 或报告中记录 SSH 明文密码。

## 阻塞项

- `50-350 MHz` 全带 RF 频率标定表、频轴校正、幅度平坦度、IQ imbalance、image rejection、SFDR 未完成。
- Phase slider 角度值尚未科学标定。
- CH1..CH7 未接物理模拟闭环。
- 浏览器端 Jupyter live refresh 未做自动截图/长时间稳定性验收。
- CMAC/QSFP 真实链路、交换机、接收节点 pcap 仍留给 Stage 7a 或后续网络阶段。
