# Stage 20：外部 10MHz/PPS 与 8 路 DAC-ADC 验证

## 阶段摘要

Stage 20 针对当前新的硬件接线：8 路 `DAC0->ADC0` 到 `DAC7->ADC7` 已连接，外部 PPS 和外部 10 MHz 已接入。目标不是重新争论 Stage 19 的 CH0 相位漂移，而是把同步前提和 8 路幅相观测变成可见、可测、可失败的工程门禁。

本阶段不降低既有数据门禁：

- 8 路 DAC-loopback phase p-p `<= 3 deg`
- 8 路 DAC-loopback amplitude p-p `<= 5%`
- PPS 必须有计数增长或 recent 状态
- 外部 10 MHz 必须让 LMK 双 PLL lock
- Jupyter 和板上 LED 都必须能给出简单同步诊断

## 已实现内容

- RTL / AXI 状态：
  - `CORE_VERSION` bump 到 `0x00010010`。
  - `feng_ctrl_axi` 新增 `pps_count` 读数：
    - `0x0024`：低 32 bit
    - `0x0028`：高 32 bit
  - `PPS_STATUS` 现在同时显示 `pps_in`、`ref_locked`、`pps_count != 0`。
  - `RFDC_STATUS_FLAGS` 新增 `pps_input_high` 和 `pps_recent`，避免只知道“曾经见过 PPS”。
- LED 语义：
  - `LED0`：RF/LMK 派生数据时钟链 ready。
  - `LED1`：PPS 上升沿 blink。
  - `LED2`：最近见过 PPS。
  - `LED3`：同步错误，含 clock-chain 未 ready 或 PPS 不 recent。
- Python：
  - `configure_clock(ref="external_10mhz")` 支持外部 10 MHz LMK 配置，并返回 selector/CLKin 尝试细节。
  - 新增 `read_external_sync_diagnostics()`，统一返回 `EXTERNAL_10MHZ_PPS_OK`、`PPS_NOT_SEEN_OR_NOT_TOGGLING`、`EXTERNAL_10MHZ_LMK_UNLOCKED` 等分类。
  - 新增 `apply_external_pps_locked_observation_config()`，默认使用 `clock_ref=external_10mhz`、`sync_mode=external_pps`、`require_mts=True`。
  - DAC tone bank 支持 `phase_deg_by_channel`，8 路每路可单独设相位。
- Jupyter：
  - notebook 13 增加 8 个每通道相位滑条。
  - 增加外部 10 MHz / PPS 控件和“诊断10M/PPS”按钮。
  - 状态栏显示 `PPS_COUNT`、`PPS_RECENT`、`PPS_IN`、LMK lock、同步模式和 LED 语义。
  - `dac_loopback` 和 `external_adc_tone` 明确分离；外源模式默认 DAC off。
- 板端脚本：
  - `scripts/pynq_stage20_sync_diagnostic.py`
  - `scripts/pynq_stage20_8lane_external_sync_check.py`

## 板端验证命令

先只做同步健康检查：

```bash
cd /home/xilinx/t510_fengine_bringup
source /etc/profile.d/xrt_setup.sh
sudo -E /usr/local/share/pynq-venv/bin/python3 \
  scripts/pynq_stage20_sync_diagnostic.py \
  --configure-external \
  --output reports/stage20_external_10mhz_pps_sync.json
```

8 路 DAC-ADC 闭环严格门禁：

```bash
sudo -E /usr/local/share/pynq-venv/bin/python3 \
  scripts/pynq_stage20_8lane_external_sync_check.py \
  --center-mhz 200 --signal-mhz 200 --bw-mhz 100 \
  --phases-deg 0,45,90,135,180,-135,-90,-45 \
  --frames 240 --samples 512 \
  --phase-pp-deg 3 --amplitude-pp-percent 5 \
  --output reports/stage20_8lane_external_sync_200mhz.json
```

## 判定规则

- `EXTERNAL_10MHZ_PPS_OK` 且 8 路脚本 `STAGE20_8LANE_EXTERNAL_SYNC_PASS`：可以把 8 路 DAC-loopback 与外部同步作为下一阶段 QSFP 前数据质量前提。
- LMK 不 lock：先查外部 10 MHz 输入、LMK selector、profile 和板级参考链，不能继续判 RFDC/MTS。
- PPS 不计数：先查 PPS 电平、管脚约束、线缆、极性和 `pps_in` 同步逻辑，不能继续判 8 路相位。
- 只有部分 ADC lane 有效：先查 RFDC tile/block active mask、8 根线缆和 `rfdc_current_valid_mask`。
- 8 路幅相失败但 CH0 仍 PASS：优先查对应 lane 的 DAC phase 配置、ADC 输入链路、线缆和 RFDC tile/block 状态，不回退 Stage 19 主因结论。

## 当前状态

本阶段已完成本地构建、overlay 发布和板端严格门禁，结论为 `PASS`。

Vivado / overlay：

- `CORE_VERSION=0x00010010`
- `overlay/t510_fengine.bit` SHA256 `a39fdde33107d337eb3df71f1e1d0e906d47332adab7a7901f62380060622b0a`
- `overlay/t510_fengine.hwh` SHA256 `345fdf3aea634a323dc3fd8f9bdde872c04a92d161ba08404782fd4260e39e4f`
- synthesis：`0 errors / 0 critical warnings`
- implementation：`route_design Complete`
- timing：WNS `+1.650 ns`，WHS `+0.010 ns`，失败端点 `0/226928`
- bitgen：`0 errors / 0 critical warnings`；普通 DRC warning 主要为 DSP MREG/PREG pipeline 建议、FFT IP BRAM WRITE_FIRST advisory、RFDC 未使用 status net，无本阶段功能阻塞项。

板端同步诊断：

- 结果文件：`reports/board/stage20_external_10mhz_pps_sync.json`
- `result=PASS`
- `classification=EXTERNAL_10MHZ_PPS_OK`
- LMK external 10 MHz 选到 `CLKin1`
- `pll1_lock=1`，`pll2_lock=1`
- `pps_delta=2`，`pps_ok=true`，`ref_ok=true`

8 路 DAC-ADC 严格门禁：

- 结果文件：`reports/board/stage20_8lane_external_sync_200mhz.json`
- `result=PASS`
- `classification=STAGE20_8LANE_EXTERNAL_SYNC_PASS`
- 条件：`center=200 MHz`，`signal=200 MHz`，`frames=240`，`samples=512`
- 每通道 DAC 相位配置：`0,45,90,135,180,-135,-90,-45 deg`
- 最坏 phase p-p：`0.247806 deg`，阈值 `<=3 deg`
- 最坏 amplitude p-p：`0.377110%`，阈值 `<=5%`
- 最低 SNR：`59.947732 dB`
- 无 clipping

逐通道结果：

| 通道 | 配置相位 | phase p-p | amplitude p-p | min SNR |
| --- | ---: | ---: | ---: | ---: |
| CH0 | `0 deg` | `0.165597 deg` | `0.332405%` | `60.56 dB` |
| CH1 | `45 deg` | `0.154863 deg` | `0.331254%` | `61.77 dB` |
| CH2 | `90 deg` | `0.247806 deg` | `0.345678%` | `61.41 dB` |
| CH3 | `135 deg` | `0.212571 deg` | `0.279454%` | `60.80 dB` |
| CH4 | `180 deg` | `0.172103 deg` | `0.362183%` | `60.74 dB` |
| CH5 | `-135 deg` | `0.159195 deg` | `0.283771%` | `61.09 dB` |
| CH6 | `-90 deg` | `0.176413 deg` | `0.340680%` | `60.46 dB` |
| CH7 | `-45 deg` | `0.216069 deg` | `0.377110%` | `59.95 dB` |

## 阶段边界

Stage 20 只验收外部同步与 8 路板内 DAC-ADC 闭环。它不声明 QSFP live science data 已通过，不声明 4096-channel PFB 幅相标定完成，也不声明外部 ADC 科学输入已跨全频带标定。
