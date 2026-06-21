# Stage 19b：外部 ADC 单音解耦与假稳定性排查

## 阶段摘要

Stage 19 已闭合 CH0 DAC0-to-ADC0 dry-run/witness 相位漂移主因，但该闭环仍然依赖 DAC0 作为 ADC0 输入。Stage 19b 单独处理外部单音输入场景，避免 DAC 测试源、ADC 期望输入频率和 Jupyter 显示稳定器继续混在一起。

当前外部 `200 MHz` 源没有和板卡 LMK/10 MHz 同源锁定，因此外源 sample0-aligned phase 长期漂移本身不是失败。真正的失败判据是 raw preview、FFT peak、SNR、sample0 或幅度停止更新，或者显示层拒收却没有明确暴露原因。

板端实测已经证明：ADC0 接外部 `200 MHz` 源时，raw preview 没有停，`sample0` 持续增长，FFT 主峰持续在 `200 MHz` 附近。Jupyter “频谱不刷新”的主因是显示稳定器旧逻辑把平滑谱镜像峰当成下一帧 peak-jump 参考，导致外源 off-center 时误拒收；该逻辑已修复为用 raw/语义化 RF peak 做门禁。外源正好放在观测中心 `center=200 MHz` 时仍保留为特殊失败分类：非同源外源落在 DC 点会触发幅度/相位拟合二义性，必须改用 off-center 观测或让外源与板卡同源锁定后再按 `5%` 幅度门禁判断。

## 修改内容

- Python observation API 增加输入源语义：
  - `input_source_mode = dac_loopback | external_adc_tone`
  - `expected_signal_hz` / `input_signal_hz` 独立于 `dac_signal_hz`
  - `compute_observation_view()`、`compute_phase_provenance()`、`compute_sample0_aligned_phase_view()` 和 payload phase metrics 均优先使用 `expected_signal_hz`
- Jupyter 入口增加外源模式：
  - 新增 `输入源`、`ADC输入 MHz`、`DAC信号 MHz`
  - 外源模式下 Init/Apply 自动把 DAC amplitude 和 enable mask 置零
  - 状态栏显示 raw peak、display peak、`valid_frame`、`reject_reason`；stabilizer 拒收时状态栏转为 warn
  - 修复 stabilizer：peak-jump 判据使用语义化 `rf_peak_mhz`，不再被平滑谱 argmax 或正负基带镜像污染
- 新增板端诊断脚本：
  - `scripts/pynq_external_adc_tone_decoupling_check.py`
  - 支持 `external_direct_dac_off`、`external_direct_dac_on`、`adc_terminated_dac_on`
  - 输出 raw preview digest、sample0 增长、FFT peak、SNR、clipping、幅度 p-p、相位斜率和 stabilizer reject series

## 判定规则

- `EXTERNAL_TONE_OK_FREE_RUNNING_PHASE`：raw preview/sample0/FFT/SNR/幅度正常；相位漂移可作为非同源外部源的物理结果记录。
- `EXTERNAL_TONE_CENTER_DC_AMBIGUOUS`：外源未同源锁定且正好落在观测中心/DC，raw 数据正常但幅度/相位拟合病态；用 off-center 观测或同源锁定复核。
- `UI_STABILIZER_REJECTING_EXTERNAL_TONE`：raw 数据正常，但 display/stabilizer 持续拒收导致主频谱 hold。
- `ADC_INPUT_LEVEL_OR_PATH_FAULT`：低 SNR、clipping、峰值不在期望频率附近或幅度超过 `5%` 门禁。
- `RFDC_PREVIEW_STALLED`：sample0 或 raw IQ digest 不增长。
- `DAC_ADC_COUPLING_SUSPECT`：ADC0 端接且 DAC on 时仍出现强 DAC 相关峰。

## 板端结果

测试环境：`CORE_VERSION=0x0001000E`，ADC0 当前接外部 `200 MHz` 单音，外源未与板卡 LMK/10 MHz 同源锁定；所有结果均为 `240` frames、`512` samples、`--no-download`。

- `external_direct_dac_off`，`expected=200 MHz`，`center=190 MHz`：
  - 结果 `PASS / EXTERNAL_TONE_OK_FREE_RUNNING_PHASE`
  - `sample0_strictly_increases=True`，`unique_preview_digest_count=240`
  - `rf_peak_mean=199.999987749 MHz`，`rf_peak_pp=0.006341 MHz`
  - `snr_min=65.119 dB`，`amplitude_pp=1.431%`
  - `accepted=240`，`reject=0`
- `external_direct_dac_on`，`expected=200 MHz`，`center=190 MHz`，`DAC0=220 MHz`：
  - 结果 `PASS / EXTERNAL_TONE_OK_FREE_RUNNING_PHASE`
  - `sample0_strictly_increases=True`，`unique_preview_digest_count=240`
  - `rf_peak_mean=200.000091563 MHz`，`rf_peak_pp=0.006095 MHz`
  - `snr_min=64.799 dB`，`amplitude_pp=1.450%`
  - `accepted=240`，`reject=0`
- `external_direct_dac_off`，`expected=200 MHz`，`center=200 MHz`：
  - 结果 `FAIL / EXTERNAL_TONE_CENTER_DC_AMBIGUOUS`
  - raw preview 仍活：`sample0_strictly_increases=True`，`unique_preview_digest_count=240`，`rf_peak_mean=200.000000 MHz`
  - 失败原因：`expected_baseband_hz=0` 且外源未同源锁定，幅度拟合 p-p `160.298%`，stabilizer 因 `amp_jump/rms_jump` 拒收 `91/240`
  - 该结果不能直接升级为 ADC 输入路径故障；off-center 同源语义复测已经通过

当前证据不支持“DAC0 打开会让外部 ADC0 单音路径冻结或必然假稳定”。在外源直连 ADC0 的接线下，DAC0 打开并设到不同频率后，ADC0 的 `200 MHz` 外源观测仍通过。还没有完成的耦合实锤测试是 `ADC0 50Ω 端接 + DAC0 on`，这需要物理换线。

## 验收命令

本地：

```bash
python3 -m py_compile python/t510_fengine.py scripts/pynq_external_adc_tone_decoupling_check.py
python3 -m json.tool notebooks/13_astronomer_rf_observation_console.ipynb >/dev/null
```

板端外源直连 ADC0、DAC off：

```bash
cd /home/xilinx/t510_fengine_bringup
source /etc/profile.d/xrt_setup.sh
sudo -E /usr/local/share/pynq-venv/bin/python3 \
  scripts/pynq_external_adc_tone_decoupling_check.py \
  --scenario external_direct_dac_off \
  --expected-mhz 200 --center-mhz 190 --bw-mhz 100 \
  --frames 240 --samples 512 --timeout 2.0 \
  --output reports/stage19b_external_adc0_200mhz_center190_dac_off.json
```

DAC 泄漏矩阵需要按物理接线分别运行：

```bash
# 外源仍直连 ADC0，DAC0 打开但不接入 ADC0
sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_external_adc_tone_decoupling_check.py \
  --scenario external_direct_dac_on --expected-mhz 200 --center-mhz 190 --dac-mhz 220 \
  --output reports/stage19b_external_adc0_dac_on.json

# ADC0 改接 50Ω 端接，DAC0 打开
sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_external_adc_tone_decoupling_check.py \
  --scenario adc_terminated_dac_on --expected-mhz 220 --center-mhz 190 --dac-mhz 220 \
  --output reports/stage19b_adc0_terminated_dac_on.json
```

## QSFP 边界

Stage 19b 仍不声明 QSFP live science data 已可验收。当前 `CORE_VERSION=0x0001000E` overlay 的 TX path 仍是 dry-run sink；只有外源 ADC 解耦门禁通过后，才进入 Stage 20 的 CMAC/QSFP wrapper、GT/refclk/reset/status、pcap 和 payload 数据质量验收。
