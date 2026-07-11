# Stage 27i：100MHz Anti-Alias 诊断与 Production Candidate

Stage 27i 接在 Stage 27h `TIME_SPEC 100MHz` 仅 FFT 全速 SPEC 基线之后，先用诊断 bitstream 收敛 `122.88MHz` production spur 的边界，再实现 `100MHz` production science path 的 anti-alias 修复。

本报告从原 Stage 27h 报告中拆分出来，保留 Stage 27i 的诊断、审计、raw-lane witness、anti-alias production candidate、板端/主机验收和边界结论。Stage 27h 自身基线仍见 `27h_time_spec_100mhz_fft_fullrate.md`。

## Stage 27i 诊断 bitstream 结果

截至 2026-07-06 CST，已完成 Stage 27i 诊断 bitstream，用于切分 `122.88MHz` spur 的边界。该 bitstream 只增加默认关闭的诊断 mux，不替代 Stage 27h `0x00010028` 生产基线，也不改变 TIME/SPEC 全速目标。

- 诊断版本：`CORE_VERSION=0x00010029`
- 诊断寄存器默认值：`0x0000ff00`
  - ADC force-zero：关
  - ADC force-hold：关
  - ADC channel mask：`0xff`
  - DAC AXIS gate：关
- Vivado timing/write_bitstream：
  - route WNS `+0.042684ns`
  - write 前后 WNS `+0.043ns`
  - write 前后 WHS `+0.009ns`
  - bit SHA256 `790bce451d15571b2c486f34b0c206b1674ac18ba8f31644235afde5ead15141`

诊断前先运行 27h 生产默认关闭门禁：

- JSON：`reports/board/stage27i_diag_default_off_stage27h_validator_20260706.json`
- 分类：`STAGE27H_TIME_SPEC_100MHZ_FFT_FULLRATE_BOARD_PASS`
- `CORE_VERSION=0x00010029`
- diag 默认关闭：`stage27i_diag_control=0x0000ff00`，`stage27i_diag_disabled=1`
- TIME `481050.5 pps`
- SPEC `481049.5 pps`
- 合计 T510 UDP 载荷 `64037.376000 Mbps`
- RFDC/science/TIME/SPEC/TX route 错误增量均为 `0`

Stage 27i diagnostic probe 产物：

- JSON：`reports/board/stage27i_rfdc_axis_diag_spur_probe_loopback_20260706.json`
- 物理状态：`dac_adc_loopback_restored`
- 分类：`adc_or_rfdc_frontend_spur_confirmed_by_axis_zero`
- 原因：target spur 在诊断全关时存在，打开 RFDC AXIS 后的 ADC force-zero 后消失。

关键 target-bin 结果：

- 诊断全关、DAC amplitude `0`、enable mask `0x00`：
  - TIME target SNR `39.18dB`
  - SPEC target SNR `42.17dB`
  - SPEC target RF bin 约 `122.89MHz`
- ADC force-zero：
  - TIME target SNR `0.0dB`
  - SPEC target SNR `0.0dB`
  - TIME power 约 `-160dB`
- ADC force-hold：
  - TIME target SNR `0.0dB`
  - SPEC target SNR `0.0dB`
- DAC AXIS gate：
  - TIME target SNR `38.93dB`
  - SPEC target SNR `42.27dB`
  - spur 不随 DAC digital gate 消失。
- 单通道 isolate：
  - CH0、CH1、CH2、CH5、CH6 均为强命中。
  - CH3 最弱但仍过门限，TIME/SPEC 约 `14.40dB/12.41dB`。
  - CH4、CH7 中等命中，说明这不是单一 ADC 通道或单一回环线问题。

诊断后重新下载 bitstream 并运行 27h 恢复门禁：

- JSON：`reports/board/stage27i_restore_after_diag_spur_probe_20260706.json`
- 分类：`STAGE27H_TIME_SPEC_100MHZ_FFT_FULLRATE_BOARD_PASS`
- diag 默认关闭：`stage27i_diag_control=0x0000ff00`，`stage27i_diag_disabled=1`
- TIME `481059.0 pps`
- SPEC `481057.0 pps`
- 合计 T510 UDP 载荷 `64038.440960 Mbps`
- RFDC/science/TIME/SPEC/TX route 错误增量均为 `0`

当前边界结论：

- `122.88MHz` spur 已在 RFDC AXIS diagnostic mux 之前存在；RFDC AXIS 之后的 TIME/SPEC split、FFT-only channelizer、SPEC UDP packetizer、Rust parser、TSP3 assembler 和 Web 显示不是 spur 的生成源。
- DAC digital 路径不是主因；即使 DAC AXIS gate 打开，spur 仍存在。
- 不能用 PL 里的 notch、忽略 target bin、降低速率、恢复 decimation/thinning 作为生产修复。下一步应查 ADC 模拟输入前端、RFDC ADC/mixer/decimation 内部状态、板上 `122.88MHz` 相关时钟/参考/SYSREF/电源耦合，以及是否可以通过关闭未用 clock/SYSREF 输出或调整 LMK/RFDC profile 降低耦合。

## 生产同步默认值收紧

截至 2026-07-06 CST，27h/27i 后续生产入口默认改为外部 `10MHz` 参考加外部 `PPS` 锁定。`python/t510_fengine.py` 的生产 observation/science 默认、`scripts/pynq_stage27h_time_spec_fft_fullrate.py`、`scripts/pynq_stage27h_rfdc_spur_audit.py` 和 notebook 15 均默认 `clock_ref=external_10mhz`、`sync_mode=external_pps`。27h 板端 validator 会显式检查 configured/active sync mode、PPS recent 和 PPS count；如果 PPS 未进入锁定语义，默认生产门禁不应继续通过。

实现细节：27h board validator 现在按生产启动顺序执行，先配置 science 路由但不立即计时，随后等待 CMAC/QSFP ready、dry-run 关闭、external PPS 触发且 TIME/SPEC 包计数真实前进，再进入正式 rate/drop/error 窗口。这样避免 fresh download 后链路 bring-up 或 PPS arm 等待污染速率窗口，同时不降低 TIME/SPEC `480kpps + 480kpps` 与 `63Gbps+` 门槛。

本轮已完成 fresh-download 2 秒 smoke：

- JSON：`reports/board/stage27i_external_pps_default_smoke_ready_wait_20260706.json`
- 分类：`STAGE27H_TIME_SPEC_100MHZ_FFT_FULLRATE_BOARD_PASS`
- `configured_clock_ref=0`、`configured_sync_mode=0`、`active_sync_mode=0`
- `pps_recent=1`、`pps_count=5`
- ready wait 约 `1.16s` 后确认 TIME/SPEC 包计数前进，CMAC ready，dry-run off
- TIME `481025.0 pps`
- SPEC `481026.5 pps`
- 合计 T510 UDP 载荷 `64034.147840 Mbps`
- RFDC/science/TX route 错误增量为 `0`

历史报告中出现的 `tcxo_10mhz` 或 `free_run` 仍按当时测试条件保留；它们只作为 archived bring-up 或 clock-ref 对照 sweep，不再代表 Stage 27h 的生产默认入口。

## Stage 27i 外部 PPS spur 复测

截至 2026-07-06 CST，已在生产默认同步条件下重跑 Stage 27i 诊断 probe。该轮继续使用 `CORE_VERSION=0x00010029`，物理状态为 DAC-ADC 回环线已恢复，默认 `clock_ref=external_10mhz`、`sync_mode=external_pps`，不改 RTL、不重建 bitstream、不使用 notch 或忽略 bin。

复测前 fresh-download 2 秒门禁：

- JSON：`reports/board/stage27i_external_pps_pre_diag_smoke_20260706.json`
- 分类：`STAGE27H_TIME_SPEC_100MHZ_FFT_FULLRATE_BOARD_PASS`
- `stage27i_diag_control=0x0000ff00`，`stage27i_diag_disabled=1`
- `configured_clock_ref=external_10mhz`，`configured_sync_mode=external_pps`，`active_sync_mode=external_pps`
- `pps_recent=1`，`pps_count=5`
- TIME `481025.0 pps`
- SPEC `481024.0 pps`
- 合计 T510 UDP 载荷 `64033.981440 Mbps`

Stage 27i external-PPS probe 产物：

- JSON：`reports/board/stage27i_rfdc_axis_diag_spur_probe_external_pps_20260706.json`
- 分类：`adc_or_rfdc_frontend_spur_confirmed_by_axis_zero`
- 物理状态：`dac_adc_loopback_restored_external_10mhz_pps`
- 同步摘要：`EXTERNAL_10MHZ_PPS_OK`，LMK selected ref 为 `external_10mhz`，RFDC MTS shim ready，RFDC readback mismatch 为空。
- 诊断全关：TIME/SPEC target SNR 约 `37.85dB/40.78dB`，target bin 仍在 `122.88MHz` 附近。
- ADC force-zero：TIME/SPEC target SNR 均为 `0.0dB`。
- ADC force-hold：TIME/SPEC target SNR 均为 `0.0dB`。
- DAC AXIS gate：TIME/SPEC target SNR 约 `38.67dB/41.34dB`，spur 不随 DAC digital gate 消失。
- 单通道 isolate：CH0..CH7 全部命中；SNR 分布约为 CH0 `37.09/37.81dB`、CH1 `45.42/45.53dB`、CH2 `41.96/42.15dB`、CH3 `16.45/22.63dB`、CH4 `22.92/27.65dB`、CH5 `36.41/35.85dB`、CH6 `40.83/40.24dB`、CH7 `28.45/30.82dB`，格式为 TIME/SPEC。

诊断后恢复门禁：

- 第一次恢复 JSON：`reports/board/stage27i_restore_after_external_pps_diag_spur_probe_20260706.json`，分类为 FAIL，原因是 CMAC/QSFP ready 窗口内 `CMAC_TX_NOT_READY` 和 `TX_STILL_DRY_RUN`；该轮诊断寄存器仍已恢复为 `0x0000ff00`，TIME/SPEC 计数窗口本身接近满速。
- 重跑恢复 JSON：`reports/board/stage27i_restore_after_external_pps_diag_spur_probe_retry_20260706.json`
- 重跑分类：`STAGE27H_TIME_SPEC_100MHZ_FFT_FULLRATE_BOARD_PASS`
- `stage27i_diag_control=0x0000ff00`，`stage27i_diag_disabled=1`
- `pps_recent=1`，`pps_count=5`
- TIME `481031.5 pps`
- SPEC `481030.5 pps`
- 合计 T510 UDP 载荷 `64034.846720 Mbps`

本轮结论没有改变生产目标，但把同步条件收紧后的边界重新确认了一遍：`122.88MHz` spur 在外部 `10MHz` 与外部 `PPS` 默认锁定下仍存在，且 force-zero/hold 在 RFDC AXIS adapter 后将其清零。因此后级 TIME/SPEC/UDP/Rust/Web 不是生成源，问题仍在 RFDC AXIS diagnostic mux 之前。当前仍不能仅凭软件区分 ADC 模拟输入前端耦合、RFDC ADC 内部行为、板上 `122.88MHz` 相关时钟/SYSREF/电源耦合；下一步应继续在 Stage 27i 内做板内时钟/RFDC 配置和物理近端证据，不开 Stage 27j。

## Stage 27i 前端 spur audit

截至 2026-07-06 CST，已在同一 Stage 27i 诊断 bitstream 上增加并运行 front-end audit；不改 RTL、不重建 bitstream、不使用 notch、bin mask、降速、thinning 或显示隐藏。该轮继续使用 `CORE_VERSION=0x00010029`，物理状态为 DAC-ADC 回环线已恢复，默认同步为外部 `10MHz` 加外部 `PPS`。

脚本和命令：

- 脚本：`scripts/pynq_stage27i_frontend_spur_audit.py`
- 底层入口：`scripts/pynq_stage27h_rfdc_spur_audit.py --stage27i-front-end-audit`
- JSON：`reports/board/stage27i_frontend_spur_audit_external_pps_20260706.json`
- log：`reports/board/stage27i_frontend_spur_audit_external_pps_20260706.log`

复测前 fresh-download 2 秒门禁：

- JSON：`reports/board/stage27i_frontend_pre_smoke_20260706.json`
- 分类：`STAGE27H_TIME_SPEC_100MHZ_FFT_FULLRATE_BOARD_PASS`
- `stage27i_diag_control=0x0000ff00`，PPS recent 有效。
- TIME `481028.0 pps`
- SPEC `481030.0 pps`
- 合计 T510 UDP 载荷 `64034.580480 Mbps`

front-end audit 结果：

- 顶层 `ok=false`，原因是证据矩阵中 `200MHz SPEC_ONLY` case 未通过 F-engine clean gate；该状态按脚本纪律不再标成全量通过。
- 定位分类仍为 `rfdc_adc_config_or_internal_suspect`。
- 分类原因：target RF spur 不在 RFDC bandwidth/decimation 或 ADC mixer center sweep 下保持稳定，且 RFDC readback 未发现 center/DAC NCO/mixer mismatch。
- `classification_cases_valid=false`，invalid case 为 `stage27i_frontend_mode_200mhz_spec_only_center_100.000`。
- 该 invalid case 的 clean-gate 失败原因为 `FENGINE_ERROR_COUNTER_DELTA`：`pfb_capture_backpressure_count` 增量约 `80390421`，`pfb_xfft_data_out_halt_count` 增量约 `10777477`，说明 `200MHz SPEC_ONLY` 当前不能作为 clean spur 证据。

关键证据：

- Baseline：外部 `10MHz` + 外部 `PPS`、`TIME_SPEC 100MHz`、DAC amplitude `0`、诊断全关时，TIME/SPEC target SNR 约 `40.47dB/43.78dB`。
- Force-zero sentinel：审计开始和结束的 ADC force-zero 均将 TIME/SPEC target SNR 压到 `0.0dB/0.0dB`，继续证明 spur 在 RFDC AXIS diagnostic mux 之前。
- Clock-ref 对照：`external_10mhz` 与 `tcxo_10mhz` 均命中，TIME/SPEC target SNR 分别约 `40.91dB/43.61dB` 与 `39.67dB/43.13dB`；未出现足够大的 clock-ref 敏感性。
- SYSREF pulse 对照：explicit SYSREF pulse 后 target SNR 约 `40.18dB/43.12dB`；未出现足够大的 SYSREF pulse 敏感性。
- Mode 对照：`20MHz SPEC_ONLY`、`100MHz TIME_SPEC`、`100MHz SPEC_ONLY`、`100MHz TIME_ONLY` 均能看到 target；`200MHz TIME_ONLY` target SNR 仅约 `1.45dB`，`200MHz SPEC_ONLY` clean gate 失败。
- Center/NCO 对照：`center=80MHz` 与 `100MHz` 时 target RF `122.88MHz` 在 TIME/SPEC 中强命中；`center=122.88MHz` 时 SPEC target 仍约 `39.47dB`，但 TIME AC 指标因 target 落到 DC 附近被均值去除压低；`center=140MHz` 与 `160MHz` 时 target RF 附近 TIME/SPEC 均低于门限。

诊断后恢复门禁：

- JSON：`reports/board/stage27i_restore_after_frontend_spur_audit_20260706.json`
- 分类：`STAGE27H_TIME_SPEC_100MHZ_FFT_FULLRATE_BOARD_PASS`
- `stage27i_diag_control=0x0000ff00`，诊断开关恢复默认关闭。
- TIME `481036.5 pps`
- SPEC `481040.0 pps`
- 合计 T510 UDP 载荷 `64035.811840 Mbps`

本轮结论边界：

- UI、Rust Web 绘图、Rust SPEC parser、TSP3 assembler、SPEC UDP layout、TIME/SPEC 后级数据面仍不是当前 spur 的生成源。
- DAC digital 路径仍不是主因；之前 DAC gate 证据已证明 gate 后 spur 不消失。
- 该轮没有支持“单纯 LMK/SYSREF/clock-ref 状态切换会显著改变 spur”的结论。
- 更强的新证据是：`122.88MHz` target 随 ADC mixer center 和 200MHz bandwidth/decimation 状态表现不稳定，因此下一步应优先查 RFDC ADC mixer/decimation/Nyquist/QMC/MTS 配置细节、RFDC ADC 内部响应，以及为何 `200MHz SPEC_ONLY` 会触发 F-engine backpressure；再结合必要的板级近端测量区分 ADC 输入前端/板级模拟耦合。
- 仍不允许用 notch、忽略 target bin、降低速率、恢复 decimation/thinning 或显示层隐藏作为生产修复。

## Stage 27i SPEC sideband audit

针对人工观察到的 “`SPEC_ONLY`、DAC amplitude `0`、`center=100MHz` 时，`100MHz BW` spur 在右侧而 `200MHz BW` spur 在左侧” 现象，已增加并运行 Stage 27i SPEC sideband audit。该轮仍不改 RTL、不重建 bitstream、不使用 notch/bin mask/降速/thinning/显示隐藏；`200MHz SPEC_ONLY` 只作为诊断 case，不作为 27h 生产通过目标。

脚本和命令：

- 脚本：`scripts/pynq_stage27i_spec_sideband_audit.py`
- 底层入口：`scripts/pynq_stage27h_rfdc_spur_audit.py --stage27i-spec-sideband-audit`
- JSON：`reports/board/stage27i_spec_sideband_audit_external_pps_20260706.json`
- log：`reports/board/stage27i_spec_sideband_audit_external_pps_20260706.log`

关键结果：

- 分类：`rfdc_adc_config_or_internal_suspect`
- 分类原因：`100MHz SPEC_ONLY` 能看到 target RF sideband，但 `200MHz SPEC_ONLY` 把该 target 压低，同时出现另一个 dominant SPEC peak。
- `100MHz SPEC_ONLY`、`center=100MHz`、DAC amplitude `0`：
  - SPEC 主峰在 `+22.89MHz` baseband，对应 RF `122.89MHz`。
  - SPEC target SNR 约 `42.42dB`。
- `200MHz SPEC_ONLY`、`center=100MHz`、DAC amplitude `0`：
  - `122.88MHz` target 不再是强峰。
  - SPEC 主峰在约 `-100.02MHz` baseband，按当前频率轴对应 RF 约 `0MHz`，SNR 约 `43.32dB`。
  - 该 case 未通过 F-engine clean gate：`pfb_capture_backpressure_count` 与 `pfb_xfft_data_out_halt_count` 增长，因此只能作为诊断证据，不可作为 clean science 证据。
- RFDC raw preview 在两种带宽下也以 `-100.02MHz` baseband 附近为主峰，说明 raw preview 当前更像 RFDC/full-rate 近 DC/边缘伪峰观测，不能直接替代生产 SPEC 频率归因。

诊断后恢复门禁：

- JSON：`reports/board/stage27i_restore_after_spec_sideband_audit_20260706.json`
- 分类：`STAGE27H_TIME_SPEC_100MHZ_FFT_FULLRATE_BOARD_PASS`
- TIME `481043.5 pps`
- SPEC `481042.0 pps`
- 合计 T510 UDP 载荷 `64036.410880 Mbps`

新的边界判断：

- 这不是简单的 “`122.88MHz` 在 `200MHz BW` 下被镜像到左侧”。如果只是边带符号翻转，预期应在 `-22.88MHz` baseband 附近出现强峰；实际 dominant peak 在约 `-100MHz` baseband。
- 该现象更支持 RFDC ADC/mixer/decimation 配置或 RFDC 内部响应嫌疑，尤其是 `200MHz SPEC_ONLY` 下 `pl_decim_factor=1`、sample rate `245.76MS/s` 时的低频/边缘伪峰和 F-engine backpressure。
- 下一步应优先做 RFDC ADC readback 深挖：比较 `100MHz` 与 `200MHz` 下 ADC mixer `Freq/EventSource/MixerMode/CoarseMixFreq/FineMixerScale`、decimation、Nyquist zone、QMC、MTS/SYSREF 更新路径，以及 `200MHz SPEC_ONLY` 为什么让 XFFT output halt/backpressure 增长。

## Stage 27i RFDC 100/200MHz root-cause audit

为继续定位上述 `100MHz BW` 右侧 target spur 与 `200MHz BW` 左侧/低频端 dominant peak 的差异，已新增 Stage 27i RFDC 100/200MHz root-cause audit 入口。该入口仍使用当前 `CORE_VERSION=0x00010029` 诊断 bitstream，不改 RTL、不重建 bitstream、不使用 notch/bin mask/降速/thinning/显示隐藏。

脚本和默认命令：

- 脚本：`scripts/pynq_stage27i_rfdc_200m_rootcause_audit.py`
- 底层入口：`scripts/pynq_stage27h_rfdc_spur_audit.py --stage27i-rfdc-200m-rootcause-audit`
- 默认 JSON：`reports/board/stage27i_rfdc_200m_rootcause_audit_external_pps_YYYYMMDD.json`
- 默认物理状态：`dac_adc_loopback_restored_external_10mhz_pps`
- 默认同步：外部 `10MHz` + 外部 `PPS`

该 audit 的受控 case 为 `center=100MHz` 下的 `100MHz SPEC_ONLY`、`200MHz SPEC_ONLY`、`100MHz TIME_SPEC`、`200MHz TIME_ONLY`；补充 center sweep 为 `122.88/140/160MHz` 下的 `100MHz SPEC_ONLY` 与 `200MHz SPEC_ONLY`。每个 case 记录：

- RFDC readback 四个阶段：observation 前、observation 后、science 配置后、stream start 后。
- TFW5/TSP3 频域证据：`122.88MHz` target bin、mirror bin、负 Nyquist/left-edge bin、dominant peak、TIME/SPEC target SNR。
- F-engine/TX 流控证据：`pfb_capture_backpressure_count`、`pfb_xfft_data_out_halt_count`、SPEC/TIME packet delta、route hit delta、TX drop/route miss/error delta。
- `200MHz SPEC_ONLY` 若仍触发 clean gate 失败，会保留 dirty preview 作为诊断证据，但必须继续列入 `invalid_cases`，不能作为 clean science 通过证据。

分类语义：

- `rfdc_200m_config_mismatch_suspect`：RFDC readback 与请求 center/decimation/mixer/Nyquist/MTS 状态不一致。
- `fengine_200m_output_backpressure_suspect`：`100MHz SPEC_ONLY` 命中 target，但 `200MHz SPEC_ONLY` target 被压低，同时出现 XFFT output halt 或 capture backpressure。
- `spec_axis_mapping_suspect`：`200MHz TIME_ONLY` 命中 target，而 `200MHz SPEC_ONLY` 不命中，且没有 RFDC readback mismatch 或 SPEC backpressure。
- `rfdc_200m_decimation_path_suspect`：RFDC readback 未发现配置 mismatch，且 `200MHz TIME_ONLY` 与 `200MHz SPEC_ONLY` 都把 `122.88MHz` target 压低并出现不同低频/sideband dominant peak；若 `200MHz SPEC_ONLY` 同时出现 XFFT/capture backpressure，则作为并行输出压力证据单独记录，不把根因限定为 SPEC 后级。
- `stage27i_rfdc_200m_inconclusive`：证据不足或四个受控 case 不完整。

实际运行结果：

- 审计前门禁 JSON：`reports/board/stage27i_rfdc_200m_rootcause_pre_validator_20260706.json`
- 审计前门禁：`STAGE27H_TIME_SPEC_100MHZ_FFT_FULLRATE_BOARD_PASS`，TIME `481046.0 pps`，SPEC `481044.0 pps`，合计 T510 UDP payload `64036.710400 Mbps`。
- JSON：`reports/board/stage27i_rfdc_200m_rootcause_audit_external_pps_20260706.json`
- log：`reports/board/stage27i_rfdc_200m_rootcause_audit_external_pps_20260706.log`
- 顶层结果：`ok=true`
- 分类：`rfdc_200m_decimation_path_suspect`
- 分类原因：`100MHz` target clean，但 `200MHz TIME_ONLY` 与 `200MHz SPEC_ONLY` 都将 target 压低，并产生不同的低频/sideband dominant peak；`200MHz SPEC_ONLY` 还单独记录到 XFFT/capture backpressure。

关键证据：

- `100MHz SPEC_ONLY, center=100MHz`：case clean。SPEC target/primary RF 约 `122.89MHz`，baseband 约 `+22.89MHz`，target SNR 约 `41.77dB`，未出现 XFFT/capture backpressure。
- `100MHz TIME_SPEC, center=100MHz`：case clean。SPEC target/primary RF 约 `122.89MHz`，target SNR 约 `43.79dB`；TIME target/primary RF 约 `122.71MHz`，baseband 约 `+22.71MHz`，target SNR 约 `41.19dB`，未出现 XFFT/capture backpressure。
- `200MHz TIME_ONLY, center=100MHz`：case clean。TIME target RF 约 `122.68MHz`，target SNR 仅约 `2.44dB`；dominant TIME peak 转到 RF 约 `-0.17MHz`、baseband 约 `-100.17MHz`，SNR 约 `45.65dB`。这说明 `200MHz` 异常已经出现在 TIME/RFDC 预览路径，不是 SPEC/TSP3 映射或 SPEC UI 单独造成。
- `200MHz SPEC_ONLY, center=100MHz`：作为 dirty 诊断证据保留，不作为 clean science pass。SPEC target RF 约 `122.62MHz`，target SNR 约 `1.91dB`；dominant SPEC peak 转到 RF 约 `-0.02MHz`、baseband 约 `-100.02MHz`，SNR 约 `43.39dB`；同时 `pfb_xfft_data_out_halt_count` 与 `pfb_capture_backpressure_count` 增长。

结论边界：

- 当前证据不支持把 `200MHz` 左侧/低频端异常归因于浏览器绘制、Rust SPEC parser、TSP3 frame assembler 或 SPEC-only packetizer。
- `200MHz SPEC_ONLY` 的 XFFT/capture backpressure 是必须修的输出压力问题，但 `200MHz TIME_ONLY` 在无 SPEC 输出压力时已经出现同类 target 抑制和低频 dominant peak，因此更优先的根因方向是 RFDC `200MHz` 带宽对应的 ADC mixer/decimation/Nyquist/sideband 数据路径。
- 仍不允许用 notch、bin mask、显示隐藏、降速、thinning 或忽略异常 bin 作为 Stage 27h/27i 生产修复。

审计后恢复门禁：

- JSON：`reports/board/stage27i_restore_after_rfdc_200m_rootcause_audit_20260706.json`
- log：`reports/board/stage27i_restore_after_rfdc_200m_rootcause_audit_20260706.log`
- 分类：`STAGE27H_TIME_SPEC_100MHZ_FFT_FULLRATE_BOARD_PASS`
- `CORE_VERSION=0x00010029`
- `stage27i_diag_control=0x0000ff00`，诊断开关恢复默认关闭。
- TIME `481036.5 pps`，SPEC `481040.0 pps`，合计 T510 UDP payload `64035.811840 Mbps`，错误列表为空。

## Stage 27i 100MHz spur taxonomy audit

为避免 `200MHz` 诊断现象干扰 `100MHz` 生产路径判断，已新增 Stage 27i `100MHz-only`、TIME-first 的 spur taxonomy audit。该入口继续使用 `CORE_VERSION=0x00010029` 诊断 bitstream，不改 RTL、不重建 bitstream、不使用 notch/bin mask/降速/thinning/显示隐藏；`200MHz` 只作为历史线索，不进入本轮分类门禁。

脚本和默认命令：

- 脚本：`scripts/pynq_stage27i_100m_spur_taxonomy_audit.py`
- 底层入口：`scripts/pynq_stage27h_rfdc_spur_audit.py --stage27i-100m-spur-taxonomy-audit`
- 默认 JSON：`reports/board/stage27i_100m_spur_taxonomy_audit_external_pps_YYYYMMDD.json`
- 默认物理状态：`dac_adc_loopback_restored_external_10mhz_pps`
- 默认同步：外部 `10MHz` + 外部 `PPS`

该 audit 的判断优先级为 TIME/RFDC 证据，SPEC 只做交叉确认。受控 case 包括：

- 首尾 `force-zero` sentinel，验证 RFDC AXIS 后置诊断 mux 能清除 target。
- `100MHz TIME_ONLY` dense center sweep：`70/80/90/100/110/120/122.88/130/140/150/160MHz`。
- `100MHz TIME_SPEC` confirm：`80/100/122.88/140MHz`。
- `center=100MHz` repeated apply 三次，观察 RFDC mixer/NCO update 后 target SNR 和相对通道相位是否重置或漂移。
- `center=100MHz` explicit SYSREF pulse 前后对照。

每个 case 记录 RFDC 四阶段 readback、TIME TFW5 target/mirror/negative-edge/DC bin、per-channel target SNR/phase、SPEC TSP3 confirm、F-engine/TX clean gate 和同步状态。TIME TFW5 额外保留 raw target/DC 指标，避免 `center=122.88MHz` 时 target 落到 DC 后被 AC/mean-removed 指标误判为消失。

分类语义：

- `fixed_rf_or_board_coupling_suspect`：TIME target 在 `100MHz` center sweep 中稳定保持同一绝对 RF，SPEC confirm 同向，NCO/SYSREF 操作不显著改变 target。
- `rfdc_mixer_nco_sideband_suspect`：target 频率、功率或相对通道相位随 center/NCO/SYSREF 变化，或 RFDC readback 与请求状态不一致。
- `rfdc_dc_image_or_iq_mapping_suspect`：`center=122.88MHz` 附近出现 DC/image/mirror 异常，且缺少广泛固定 RF 证据。
- `adc_or_rfdc_frontend_internal_suspect`：force-zero 可清除、后级不是来源，但 100MHz 证据不足以归为固定 RF/板级耦合或 NCO/sideband。
- `stage27i_100m_spur_taxonomy_inconclusive`：case 未 clean、force-zero sentinel 失效、readback 缺失或 target 证据不足。

实际运行结果：

- 审计前第一次门禁 JSON：`reports/board/stage27i_100m_spur_taxonomy_pre_validator_20260707.json`，分类为 FAIL，原因是 ready 窗口内 `TX_STILL_DRY_RUN` / `CMAC_TX_NOT_READY`；该轮只作为链路 bring-up 瞬态记录。
- 审计前重跑门禁 JSON：`reports/board/stage27i_100m_spur_taxonomy_pre_validator_retry_20260707.json`
- 审计前重跑门禁：`STAGE27H_TIME_SPEC_100MHZ_FFT_FULLRATE_BOARD_PASS`，TIME `481044.5 pps`，SPEC `481043.5 pps`，合计 T510 UDP payload `64036.577280 Mbps`。
- Audit JSON：`reports/board/stage27i_100m_spur_taxonomy_audit_external_pps_final_20260707.json`
- Audit log：`reports/board/stage27i_100m_spur_taxonomy_audit_external_pps_final_20260707.log`
- 顶层结果：`ok=true`，`invalid_cases=[]`
- 分类：`rfdc_mixer_nco_sideband_suspect`
- 分类原因：target power 或高 SNR 通道的相对 phase 随 repeated RFDC mixer/NCO apply 或 SYSREF pulse 变化；同时 100MHz center sweep 显示 target 只在 `70..130MHz` center 下稳定过门限，`140/150/160MHz` 低于门限。

关键证据：

- force-zero sentinel 生效：`force_zero_clears_target=true`，说明后级 TIME/SPEC/UDP/Rust/Web 仍不是生成源。
- `100MHz TIME_ONLY` dense sweep：target 在 `70/80/90/100/110/120/122.88/130MHz` 命中，TIME target SNR 约 `28.13..40.56dB`；在 `140/150/160MHz` 低于门限，SNR 约 `6.31/1.66/2.38dB`。
- `100MHz TIME_SPEC` confirm：`80/100/122.88MHz` 下 TIME 与 SPEC 同时命中；`140MHz` 下 TIME/SPEC 均低于门限。该结果支持异常已在 RFDC/TIME 路径中随 center 映射变化，而不是 SPEC-only 路径单独产生。
- `center=122.88MHz` DC case：raw TIME target SNR 约 `36.72dB`，但 AC/mean-removed target SNR 约 `5.90dB`；因此 target 落到 DC 时必须看 raw 指标，不能用去均值后的 AC 指标判定 spur 消失。
- repeated apply / SYSREF 对照：经过 SNR 过滤后，`nco_repeat_2` 中 CH3/CH4 相对 phase 分别变化约 `-144.07deg` / `+101.99deg`；`sysref_pulse` 中 CH4 相对 phase 变化约 `-160.91deg`。这不是低 SNR 噪声相位触发，分类时已过滤低于 `12dB` 的通道。

审计后恢复门禁：

- JSON：`reports/board/stage27i_restore_after_100m_spur_taxonomy_audit_20260707.json`
- log：`reports/board/stage27i_restore_after_100m_spur_taxonomy_audit_20260707.log`
- 分类：`STAGE27H_TIME_SPEC_100MHZ_FFT_FULLRATE_BOARD_PASS`
- `CORE_VERSION=0x00010029`
- TIME `481072.5 pps`，SPEC `481072.0 pps`，合计 T510 UDP payload `64040.337920 Mbps`，错误列表为空。

本轮结论边界：

- 如果先不考虑 `200MHz`，`100MHz` clean evidence 已经不支持“固定绝对 RF/单纯板级耦合在整个观测中心范围内稳定存在”的简单解释。
- 更优先的下一步是继续查 RFDC ADC mixer/NCO/SYSREF/sideband 映射和 `center` 相关行为；必要时在 Stage 27i 内增加更靠近 RFDC AXIS 原始 lane 的诊断 tap，但仍不开 27j。

## Stage 27i RFDC mixer/NCO/SYSREF event audit

为继续拆分 `rfdc_mixer_nco_sideband_suspect`，已新增 Stage 27i `100MHz BW` 专用 RFDC mixer event audit。该入口继续使用 `CORE_VERSION=0x00010029` 诊断 bitstream，默认外部 `10MHz` + 外部 `PPS`，不改 RTL、不重建 bitstream、不使用 notch/bin mask/降速/thinning/显示隐藏；`200MHz` 不参与本轮分类。

脚本和默认命令：

- 脚本：`scripts/pynq_stage27i_rfdc_mixer_event_audit.py`
- 底层入口：`scripts/pynq_stage27h_rfdc_spur_audit.py --stage27i-rfdc-mixer-event-audit`
- 默认 JSON：`reports/board/stage27i_rfdc_mixer_event_audit_external_pps_YYYYMMDD.json`
- 默认物理状态：`dac_adc_loopback_restored_external_10mhz_pps`
- 默认同步：外部 `10MHz` + 外部 `PPS`

受控 case：

- 首尾 `force-zero` sentinel，确认 RFDC AXIS 后置诊断 mux 仍能清除 target。
- `100MHz TIME_ONLY` center baseline：`100/120/122.88/130/140MHz`。
- 每个 center 后连续两次 repeat apply，复查生产 observation 路径中的 `UpdateEvent(EVENT_MIXER)` + `ResetNCOPhase()` 是否改变 target SNR 或相对通道相位。
- 每个 center 后执行一次 explicit SYSREF pulse，再采集 TIME target/SNR/phase。

分类语义：

- `mixer_event_phase_sensitive`：重复 RFDC mixer/NCO apply 后 target power 或高 SNR 通道相对 phase 显著改变。
- `sysref_sensitive`：explicit SYSREF pulse 后 target power 或相对 phase 显著改变。
- `center_sideband_mapping_sensitive`：clean `100MHz` center baseline 中，target 只在部分 center 命中。
- `rfdc_internal_or_adc_frontend_remaining`：force-zero 可清除，但 repeat apply/SYSREF/center baseline 未显示可操作的软件事件敏感性。
- `stage27i_mixer_event_inconclusive`：case 未 clean、force-zero sentinel 失效、readback 缺失或 target 证据不足。

运行纪律：

- audit 前先 fresh-download 跑 2 秒 Stage 27h/27i validator，确认 external `10MHz` + external `PPS`、diag `0x0000ff00`、`TIME_SPEC 100MHz` 满速通过。
- audit 后再次 fresh-download 跑 2 秒或 10 秒 validator，确认恢复 `STAGE27H_TIME_SPEC_100MHZ_FFT_FULLRATE_BOARD_PASS`。
- 如果该软件-only audit 仍不能切开边界，下一步才进入 Stage 27i 诊断 bitstream，在 RFDC AXIS preview/raw lane 后、science selector/TIME/SPEC split/diag force-zero mux 前增加最小 raw-lane witness；该 witness 只作为诊断入口，不进入生产 Jupyter/Rust/Web 或生产验收主线。

实际运行结果：

- 审计前第一次门禁 JSON：`reports/board/stage27i_mixer_event_pre_validator_20260707.json`，分类为 FAIL，原因是命令默认期望 `CORE_VERSION=0x00010028`，而当前 Stage 27i 诊断 bitstream 为 `0x00010029`；该轮不作为链路失败证据。
- 审计前重跑门禁 JSON：`reports/board/stage27i_mixer_event_pre_validator_retry_20260707.json`
- 审计前重跑门禁：`STAGE27H_TIME_SPEC_100MHZ_FFT_FULLRATE_BOARD_PASS`，`CORE_VERSION=0x00010029`，TIME `481038.5 pps`，SPEC `481040.0 pps`，合计 T510 UDP payload `64035.944960 Mbps`。
- Audit JSON：`reports/board/stage27i_rfdc_mixer_event_audit_external_pps_20260707.json`
- Audit log：`reports/board/stage27i_rfdc_mixer_event_audit_external_pps_20260707.log`
- 顶层结果：`ok=true`，`invalid_cases=[]`，RFDC readback mismatch 为空。
- 分类：`mixer_event_phase_sensitive`
- 分类原因：重复 RFDC mixer/NCO apply 后，target 的高 SNR 通道相对 phase 发生显著变化。

关键证据：

- Force-zero sentinel 生效：`force_zero_clears_target=true`，继续证明后级 TIME/SPEC/UDP/Rust/Web 不是生成源。
- center baseline：`100/120/122.88/130MHz` 均命中 target，TIME effective target SNR 分别约 `41.35/40.00/38.11/29.49dB`；`140MHz` 低于门限，SNR 约 `6.17dB`。
- repeat apply 敏感性：`center=130MHz` 的第二次 repeat apply 中，CH3 相对 CH1 的 target phase 相对 baseline 改变约 `-129.67deg`，超过 `45deg` 门限，且参与比较的通道均经过 `12dB` SNR 过滤。
- SYSREF pulse：本轮未产生超过门限的 target power 或相对 phase 敏感性，`sysref_sensitivity=[]`。

审计后恢复门禁：

- 第一次恢复 JSON：`reports/board/stage27i_restore_after_mixer_event_audit_20260707.json`，分类为 FAIL，原因是 CMAC/QSFP ready 窗口内 `CMAC_TX_NOT_READY` / `TX_STILL_DRY_RUN`；该轮诊断寄存器已恢复默认关闭。
- 重跑恢复 JSON：`reports/board/stage27i_restore_after_mixer_event_audit_retry_20260707.json`
- 重跑恢复门禁：`STAGE27H_TIME_SPEC_100MHZ_FFT_FULLRATE_BOARD_PASS`，TIME `481042.5 pps`，SPEC `481040.0 pps`，合计 T510 UDP payload `64036.211200 Mbps`，错误列表为空。

本轮结论边界：

- `100MHz` production-relevant 证据已经进一步支持 RFDC mixer/NCO event path 与该 spur 的 phase 行为相关。
- 当前没有证据支持 SYSREF pulse 是主触发因素；也没有 RFDC readback mismatch。
- 下一步如果继续软件定位，应集中比较 RFDC mixer `EventSource`/`UpdateEvent`/`ResetNCOPhase` 的具体调用顺序；如果软件证据仍不足，再进入 Stage 27i 诊断 bitstream raw-lane witness，不开 27j。

## Stage 27i RFDC mixer EventSource/UpdateEvent sequence audit

为继续拆分 RFDC mixer/NCO event path，已在 Stage 27i 内增加 RFDC mixer `EventSource`、`UpdateEvent(EVENT_MIXER)` 和 `ResetNCOPhase()` 顺序审计。该轮仍使用 `CORE_VERSION=0x00010029` 诊断 bitstream，默认外部 `10MHz` + 外部 `PPS`，不改 RTL、不重建 bitstream，不使用 notch/bin mask/显示隐藏/降速/thinning。

实现修正：

- `python/t510_fengine.py` 的生产默认 sequence 保持 `sysref_reset_before_pulse` 不变。
- 诊断 API 增加 `rfdc_mixer_sequence`，支持 `sysref_reset_before_pulse`、`sysref_no_reset`、`tile_update_then_reset`、`tile_reset_then_update`、`tile_update_no_reset`。
- 早期 exploratory run 证明 `EVNT_SRC_IMMEDIATE=0` 和 `EVNT_SRC_SLICE=1` 均被当前 4GSPS ADC block 拒绝，错误为 `Invalid Event Source`；因此最终 clean 矩阵只使用 RFDC 接受的 `EVNT_SRC_SYSREF=3` 与 `EVNT_SRC_TILE=2`。

实际运行结果：

- 审计前门禁 JSON：`reports/board/stage27i_mixer_sequence_sysref_tile_pre_validator_20260707.json`
- 审计前门禁：`STAGE27H_TIME_SPEC_100MHZ_FFT_FULLRATE_BOARD_PASS`，TIME `481024.0 pps`，SPEC `481024.0 pps`，合计 T510 UDP payload `64033.914880 Mbps`。
- Audit JSON：`reports/board/stage27i_rfdc_mixer_sequence_sysref_tile_audit_external_pps_20260707.json`
- Audit log：`reports/board/stage27i_rfdc_mixer_sequence_sysref_tile_audit_external_pps_20260707.log`
- 顶层结果：`ok=true`，`classification_cases_valid=true`，`invalid_cases=[]`，RFDC readback mismatch 为空。
- 分类：`mixer_eventsource_sensitive`
- 分类原因：TILE `UpdateEvent(EVENT_MIXER)` sequence 与默认 SYSREF sequence 相比，会改变 target 的高 SNR 通道相对 phase。

关键证据：

- Force-zero sentinel 继续生效：`force_zero_clears_target=true`。
- target 命中范围保持 center 相关：`100/122.88/130MHz` 命中，`140MHz` 低于 `12dB` 门限。
- `center=100MHz`：SYSREF 与 TILE sequence 均命中 target，TIME effective target SNR 约 `39.10..39.92dB`；target power 没有被 TILE event source 消除。
- `center=122.88MHz`：target 落近 DC，必须使用 raw 指标；SYSREF 与 TILE sequence 的 raw/effective target SNR 约 `36.35..36.63dB`。
- `center=130MHz`：SYSREF 与 TILE sequence 均命中，SNR 约 `27.07..28.02dB`。
- `center=140MHz`：所有 SYSREF/TILE sequence 均低于门限，SNR 约 `4.87..7.70dB`。
- `sysref_no_reset` 相对默认 `sysref_reset_before_pulse` 未产生超过门限的敏感性，`reset_sensitivity=[]`。
- TILE 分支产生 9 条相对相位敏感性证据。例如：
  - `center=100MHz`、`tile_update_no_reset`：CH0/CH2/CH4/CH5/CH6/CH7 相对 phase 变化约 `98.48/97.61/-138.60/-149.96/114.45/-123.33deg`。
  - `center=122.88MHz`、`tile_reset_then_update`：CH2/CH3/CH5/CH6 相对 phase 变化约 `-142.92/73.41/144.93/144.49deg`。
  - `center=130MHz`、`tile_reset_then_update`：CH2/CH3/CH5/CH6/CH7 相对 phase 变化约 `104.02/161.77/111.83/-135.58/84.50deg`。

审计后恢复门禁：

- 恢复 JSON：`reports/board/stage27i_restore_after_mixer_sequence_sysref_tile_audit_20260707.json`
- 恢复门禁：`STAGE27H_TIME_SPEC_100MHZ_FFT_FULLRATE_BOARD_PASS`，TIME `481039.0 pps`，SPEC `481037.5 pps`，合计 T510 UDP payload `64035.811840 Mbps`。

本轮结论边界：

- 该 spur 的存在和功率仍不能由 TIME/SPEC/UDP/Rust/Web、SPEC FFT-only packetizer 或 UI 解释；force-zero 继续证明源头在 RFDC AXIS diagnostic mux 之前。
- TILE event source 并不能消除 `122.88MHz` target，但会显著改变高 SNR 通道的相对 phase，说明 RFDC mixer/NCO event alignment 参与了观测相位。
- `EVNT_SRC_IMMEDIATE` 和 `EVNT_SRC_SLICE` 对当前 4GSPS ADC 不可用；后续不要把这两类 exploratory run 作为物理结论。
- 下一步应继续在 Stage 27i 内查 RFDC ADC mixer/NCO/Nyquist/QMC/MTS 配置细节和 raw-lane witness；如果需要改 RTL，只能增加诊断可观测性，不开 27j，也不能通过滤波、忽略 target bin、降低速率或恢复 decimation 掩盖 spur。

## Stage 27i RFDC raw-lane witness 诊断准备

本轮继续在 Stage 27i 内推进，不开 27j。目的不是替代 Stage 27h/27i 生产 bitstream，而是增加一个更靠近 RFDC AXIS adapter 输入边界的诊断证据，用于回答：

- `122.88MHz` target 是否在 RFDC raw lane 组合后已经存在；
- raw lane、production TIME、FFT-only SPEC 是否看到同一 target-bin 行为；
- Stage 27i `adc_force_zero`/`adc_force_hold`/`adc_channel_mask` 清掉 production TIME/SPEC 时，pre-diag raw witness 是否仍能看到原始 target。

设计约束：

- 诊断 core version bump 到 `0x0001002A`，仅标记为 Stage 27i diagnostic。
- `T510_STAGE27H_PRODUCTION_ONLY` 生产范围保持 24 flows、TIME `4300..4307`、SPEC `4308..4323`、FFT-only SPEC `256ch x 1 time x 16 blocks`。
- 27h production build 仍不编译 raw witness；只有设置 `T510_STAGE27I_RAW_WITNESS=1` 的 27i 诊断 build 编译 `rfdc_axis_raw_witness_capture`。
- raw witness tap 已从原来的 production preview 口移到 `rfdc_adc_axis_adapter` 内部 pre-diag raw preview 输出；该输出不受 `diag_force_zero`、`diag_force_hold` 和 `diag_channel_mask` 影响，只保留 RFDC active port mask。
- `feng_ctrl_axi` 在 `RAW_WITNESS_DIAGNOSTIC=1` 时开放 `0xe200` 控制/状态和 `0xe800..0xf7ff` capture buffer；27h production 下这些窗口仍为 archived/no-op。

新增入口：

```bash
scripts/stage27i_raw_witness_timing_closure_iter.sh
scripts/stage27i_raw_witness_write_bitstream.sh
scripts/pynq_stage27i_raw_lane_witness_audit.py
```

预期板端审计流程：

```bash
cd /home/xilinx/t510_fengine_bringup
source /etc/profile.d/xrt_setup.sh
printf "%s\n" "xilinx" | sudo -S -p "" -E /usr/local/share/pynq-venv/bin/python3 \
  scripts/pynq_stage27i_raw_lane_witness_audit.py
```

审计默认条件：

- 外部 `10MHz` + 外部 `PPS`；
- DAC-ADC 回环线恢复；
- `bandwidth=100MHz`，`output_mode=TIME_SPEC`；
- DAC amplitude `0`，DAC enable mask `0xff`；
- center 矩阵 `100/122.88/130/140MHz`；
- 开始/结束各跑一次 `adc_force_zero` sentinel。

分类解释：

- `raw_lane_matches_time_spec`：pre-diag raw lane、production TIME、FFT-only SPEC 在 clean case 中看到同一 target-bin 行为，说明后续 adapter/science split/SPEC UDP/Rust Web 不是 spur 生成源。
- `raw_lane_time_spec_mapping_suspect`：raw lane 与 production TIME/SPEC 不一致，应转查 RFDC AXIS adapter、channel/lane mapping 或 science selector。
- `raw_lane_witness_inconclusive`：raw witness capture、clean gate、force-zero sentinel 或 target SNR 证据不足。

注意：`center=122.88MHz` 时 target 落在 DC 附近，TIME/raw 的 AC 去均值指标可能把 DC 分量抑掉；该 case 必须同时记录 raw/DC target 指标，不能用 AC 指标单独判断 target 消失。

## Stage 27i RFDC raw-lane witness 审计结果

截至 2026-07-07 CST，Stage 27i raw-lane witness 诊断 bitstream 已完成 timing、`write_bitstream`、PYNQ 发布和板端审计。本轮仍只作为 Stage 27i 诊断，不替代 Stage 27h `0x00010028` 生产基线，也不改变 `TIME_SPEC 100MHz`、24 flows、FFT-only SPEC 满速目标。

构建与发布证据：

- 诊断版本：`CORE_VERSION=0x0001002A`。
- Vivado fast timing closure routed DCP：`reports/board/stage27i_raw_witness_timing_closure_iter_routed_latest.dcp`。
- route timing：`WNS=+0.051387ns`，routing errors `0`。
- bitstream SHA256：`4066cc2b591d74c83c34ea49f9d0298a0202aa685b9ebc8b6b441614cddb70f3`。
- PYNQ 发布后远端 `overlay/t510_fengine.bit` 与 bring-up root `t510_fengine.bit` SHA 均匹配。

板端 raw-lane alias 审计产物：

- JSON：`reports/board/stage27i_raw_lane_witness_alias_audit_external_pps_20260707.json`。
- log：`reports/board/stage27i_raw_lane_witness_alias_audit_external_pps_20260707.log`。
- 顶层结果：`ok=true`，`invalid_cases=[]`。
- 分类：`raw_lane_decim2_alias_matches_time_spec`。
- 分类原因：raw-lane direct view 与 production TIME/SPEC 不一致，但按 RTL `science_rate_selector` 的 `100MHz` decim2 规则取偶数样点后，raw-lane decim2 model 与 production TIME/SPEC 的 target-bin 行为一致。
- force-zero 边界：`force_zero_boundary_ok=true`。开始和结束的 `adc_force_zero` sentinel 均把 production TIME/SPEC target 清零，而 pre-diag raw witness 仍可看到 raw primary peak，证明 raw witness tap 位于诊断 force-zero mux 之前。

关键 case 证据：

- `center=100MHz`：
  - raw-lane direct target `122.88MHz` 未通过，target SNR 约 `1.84dB`；
  - raw-lane direct primary peak 在 RF 约 `-0.02MHz`，baseband 约 `-100.02MHz`，SNR 约 `36.89dB`；
  - raw-lane `rtl_decim2_model` target 通过，SNR 约 `33.41dB`，primary peak 在 RF 约 `122.89MHz`、baseband 约 `+22.89MHz`；
  - production TIME target 通过，SNR 约 `39.42dB`；
  - FFT-only SPEC target 通过，SNR 约 `42.43dB`。
- `center=130MHz`：
  - raw-lane direct target `122.88MHz` 未通过，target SNR 约 `-0.93dB`；
  - raw-lane direct primary peak 在 RF 约 `245.74MHz`，baseband 约 `+115.74MHz`，SNR 约 `20.54dB`；
  - raw-lane `rtl_decim2_model` target 通过，SNR 约 `17.40dB`；
  - production TIME target 通过，SNR 约 `24.24dB`；
  - FFT-only SPEC target 通过，SNR 约 `25.41dB`。
- `center=140MHz`：
  - raw-lane direct、raw-lane decim2 model、production TIME 和 FFT-only SPEC 均低于 target SNR 门限；
  - 该 case 支持 decim2 alias 模型与 production 行为一致，而不是单纯显示层或 SPEC-only 误解。
- `center=122.88MHz` 是 DC 特殊 case，target 落在 DC 附近；仍需使用 raw/DC 指标，不能用 AC 去均值后的指标单独判断 target 消失。

审计后的恢复门禁：

- JSON：`reports/board/stage27i_restore_after_raw_lane_alias_audit_20260707.json`。
- 分类：`STAGE27H_TIME_SPEC_100MHZ_FFT_FULLRATE_BOARD_PASS`。
- 速率：TIME `481040.5 pps`，SPEC `481040.0 pps`，合计 T510 UDP payload `64036.07808 Mbps`。
- drop/error/XFFT 增量：`time_dropped_count=0`、`spec_dropped_count=0`、`tx_route_error_count=0`、`tx_route_miss_count=0`、`pfb_overflow_count=0`、`pfb_xfft_event_count=0`、`pfb_xfft_tlast_missing_count=0`、`pfb_xfft_tlast_unexpected_count=0`、`pfb_xfft_data_out_halt_count=0`、`pfb_capture_backpressure_count=0`。
- 诊断默认恢复：`stage27i_diag_control=0x0000ff00`，`adc_force_zero=0`，`adc_force_hold=0`，`adc_channel_mask=0xff`，`dac_gate=0`，`stage27i_diag_disabled=1`。

当前结论边界：

- `122.88MHz` production target 不是 raw-lane direct view 中同一绝对 RF 的主峰；它由 raw full-rate 分量经过 `100MHz` PL decim2 alias 后出现在 production TIME/SPEC 中。
- `center=100MHz` 时，raw full-rate 的 RF 约 `0MHz`、baseband `-100.02MHz` 分量，经 decim2 后折叠到 production baseband `+22.86/+22.89MHz`，即 RF `122.86/122.89MHz`。
- `center=130MHz` 时，raw full-rate 的 RF 约 `245.74MHz`、baseband `+115.74MHz` 分量，经 decim2 后折叠到 production baseband `-7.14MHz`，即 RF `122.86MHz`。
- 这也解释了此前 `200MHz SPEC_ONLY` 线索：200MHz 模式不走 PL decim2，因此 dominant peak 保持在 raw/full-rate 频率轴的低频端或高端附近；100MHz 模式直接抽样后把该 out-of-band 分量折叠到 `122.88MHz` target。
- 因此当前主要问题从“神秘固定 `122.88MHz` RF spur”收敛为“raw full-rate out-of-band/端点分量 + `science_rate_selector` 100MHz 未滤波 decim2 alias”。后级 TIME/SPEC/UDP/Rust/Web 不是生成源；production TIME/SPEC 对 alias 的观测是科学数据路径真实行为。
- 下一步修复方向应是 Stage 27i/27h 生产 science selector 的 anti-alias：为 `100MHz` decim2 和 `20MHz` decim8 增加合适的抗混叠滤波，或改用 RFDC 内部可验证的 decimation/filter 配置；不能用 notch、忽略 target bin、降低速率、恢复 SPEC thinning 或显示隐藏来通过。与此同时仍需追 raw full-rate 的 RF `0/245.76MHz` 端点分量来源，但它已经不是 production `122.88MHz` 位置的唯一解释。

## Stage 27i 100MHz anti-alias production candidate

截至 2026-07-07 CST，已在 Stage 27i 内实现 `100MHz BW` production science path 的抗混叠修复，不开 27j，不改变 TIME/SPEC 满速目标。

实现范围：

- 新增 `rtl/science_decim2_halfband_aa.sv`，用于 `100MHz` 模式的 PL anti-alias halfband FIR + decim2。
- FIR 规格：输入 `245.76MS/s`，输出 `122.88MS/s`，41 taps，Q1.17，线性相位，DC unity gain。
- 系数校验脚本：`scripts/stage27i_verify_aa100_halfband_coeffs.py`。当前校验结果：
  - passband `|f| <= 50MHz` ripple `0.01495dB`；
  - stopband `|f| >= 72.88MHz` attenuation `59.88dB`；
  - coefficient sum `131072`，即 Q1.17 unity gain。
- `science_rate_selector` 在 `T510_STAGE27I_ANTI_ALIAS` define 打开时，`BW_100MHZ` 使用新 FIR decim2；未打开 define 时保持旧裸 decim2，便于区分历史诊断 bit。
- `BW_200MHZ` 保持直通；`BW_20MHZ` 本轮仍不声明科学频谱闭合。
- `CORE_VERSION` 在 anti-alias candidate build 中 bump 到 `0x0001002B`。
- 新增 science MMIO：
  - `0xD054 SCIENCE_ANTIALIAS_STATUS`：bit8=`aa100_active`，bit9=`aa100_primed`，低 8 位为 tap count。
  - `0xD058 SCIENCE_ANTIALIAS_COEFF_VERSION`：当前为 `0xAA100041`。
- SPEC UDP header 的 `spec_status_flags` 改为产品状态语义，保留 bit8=`FFT-only`，新增 bit9=`AA100 active`；PFB/XFFT 内部状态仍从原 MMIO 读取，不再把整份内部 PFB 状态直接当作产品 header status。

脚本与 UI：

- 新增 Vivado wrapper：
  - `scripts/stage27i_antialias_timing_closure_iter.sh`
  - `scripts/stage27i_antialias_write_bitstream.sh`
- 新增板端验收 wrapper：
  - `scripts/pynq_stage27i_antialias_spur_acceptance.py`
  - 底层入口：`scripts/pynq_stage27h_rfdc_spur_audit.py --stage27i-antialias-acceptance`
- `scripts/pynq_stage27h_time_spec_fft_fullrate.py` 默认 expected core version 更新为 `0x0001002B`。
- `python/t510_fengine.py` 的 Stage 27h/27i board validator 在 `100MHz` 模式下默认要求 `aa100_active=1`、`aa100_primed=1`、tap count `41`、coeff version `0xAA100041`。
- notebook 15 更新为 Stage 27i anti-alias candidate 入口，仍只保留生产控制和生产预览。
- Rust Web 显示 SPEC header 中的 `AA100 active/off` 状态；不隐藏任何 bin，不做 notch。

本地验证：

- `python3 scripts/stage27i_verify_aa100_halfband_coeffs.py`：PASS。
- `python3 -m py_compile python/t510_fengine.py scripts/pynq_stage27h_time_spec_fft_fullrate.py scripts/pynq_stage27h_rfdc_spur_audit.py scripts/stage27i_verify_aa100_halfband_coeffs.py`：PASS。
- `python3 -m json.tool notebooks/15_stage27h_time_spec_fft_fullrate_control.ipynb >/dev/null`：PASS。
- `bash -n scripts/pynq_publish_stage27h.sh scripts/stage27i_antialias_timing_closure_iter.sh scripts/stage27i_antialias_write_bitstream.sh scripts/stage27h_timing_closure_iter.sh scripts/stage27h_write_bitstream_from_timing_closure.sh scripts/run_xsim_batch.sh`：PASS。
- `cargo test -q --manifest-path rust/t510_time_rx/Cargo.toml`：PASS，28 tests。
- `cargo build --release --manifest-path rust/t510_time_rx/Cargo.toml`：PASS。
- `node --check` embedded Rust Web JS：PASS。
- XSim：
  - `EXTRA_XVLOG_DEFINES=T510_STAGE27I_ANTI_ALIAS ./scripts/run_xsim_batch.sh tb_science_rate_selector`：PASS。
  - `EXTRA_XVLOG_DEFINES=T510_STAGE27I_ANTI_ALIAS ./scripts/run_xsim_batch.sh tb_feng_ctrl_axi`：PASS。
  - `EXTRA_XVLOG_DEFINES=T510_STAGE27I_ANTI_ALIAS ./scripts/run_xsim_batch.sh tb_axi4_to_axil_bridge`：PASS。
  - `EXTRA_XVLOG_DEFINES=T510_STAGE27I_ANTI_ALIAS ./scripts/run_xsim_batch.sh tb_time_udp_cmac512 tb_spec_udp_cmac512 tb_t510_fengine_top_smoke`：PASS for these three.
  - `tb_pfb_channelizer` standalone 当前仍 FAIL，输出计数为 0；不带 `T510_STAGE27I_ANTI_ALIAS` 单独重跑也同样 FAIL，因此目前归类为本轮 anti-alias 之外的既有 PFB/channelizer 仿真问题。生产顶层 smoke 和 TIME/SPEC UDP targeted XSim 已通过，后续仍需单独修复该 standalone TB 或其仿真模型。

Vivado 与 bitstream：

- `scripts/stage27i_antialias_timing_closure_iter.sh` 已完成 route，产物为 `reports/board/stage27i_antialias_timing_closure_iter_routed_latest.dcp`。
- route 后 timing：`WNS=+0.003ns`、`TNS=0`、route errors `0`。
- `scripts/stage27i_antialias_write_bitstream.sh` 已完成 `write_bitstream`。
- local/PYNQ bitstream SHA256：`8b1a9406688a79b53e4f2c0e02aa98385db1ec54f6e7ea9076a561d4f7eaf5b6`。

板端与主机验证：

- Board 10 秒 post-acceptance JSON：`reports/board/stage27i_antialias_time_spec_100mhz_10s_post_acceptance_20260707.json`。
- Board 分类：`STAGE27H_TIME_SPEC_100MHZ_FFT_FULLRATE_BOARD_PASS`，`CORE_VERSION=0x0001002B`。
- Board 速率：TIME `480173.2pps`、SPEC `480172.8pps`，合计 T510 UDP payload `63920.629760Mbps`。
- Board 状态：`aa100_active=1`、`aa100_primed=1`、tap count `41`、coeff `0xAA100041`；RFDC/science/TIME/SPEC/TX route/XFFT/backpressure 错误增量均为 `0`；16 条 SPEC route 全命中。
- Stage 27i anti-alias acceptance JSON：`reports/board/stage27i_antialias_spur_acceptance_20260707.json`。
- Acceptance 分类：`stage27i_100m_antialias_spur_suppressed`。零幅度生产 case 下 `122.88MHz` target 均低于 `12dB` SNR 门限：
  - `zero_amp_enable_ff`：TIME `4.63dB`、SPEC `4.45dB`；
  - `zero_amp_enable_00`：TIME `4.25dB`、SPEC `4.77dB`；
  - `zero_amp_dac_nco_60`：TIME `3.47dB`、SPEC `5.47dB`；
  - `zero_amp_dac_nco_100`：TIME `4.54dB`、SPEC `5.06dB`。
- Reference tone：`60.010MHz` 在 TIME/SPEC 中正常落点；TIME peak `59.92MHz`、SNR `69.10dB`，SPEC peak `60.01MHz`、SNR `72.37dB`。
- Host 10 秒 JSON：`reports/board/stage27i_antialias_host_rust_rx_10s_post_acceptance_20260707.json`。
- Host 分类：`HOST_STAGE27H_RUST_RX_PASS`，24 个 active workers，TIME `480063.93pps`、SPEC `479956.65pps`，合计 T510 UDP payload `63898.970071Mbps`。
- Host 窗口内 `app/ring/kernel/worker/hard NIC` drops 均为 `0`，TIME/SPEC seq/frame/sample0 gaps 均为 `0`；`netdev_rx_dropped_advisory=930` 仅按 advisory 记录。预览仍 active：display `2.89Hz`、spectrum `7.98Hz`。
- 本轮主机使用 `ens2f0np0` RX coalescing `rx-usecs=8`、`rx-frames=32`；这是主机接收稳定性配置，不改变板端数据率或生产 wire contract。

结论边界：

- `100MHz` production TIME/SPEC 中由 raw full-rate 端点/带外分量经裸 decim2 折叠出的 `122.88MHz` target 已被 PL anti-alias FIR 抑制到门限以下。
- 本轮不声明 `20MHz` decim8 科学频谱闭合；`200MHz` 仍为直通路径，历史 `200MHz SPEC_ONLY` 现象只保留为 RFDC/sideband 线索。
- raw/full-rate RF `0/245.76MHz` 端点分量来源仍需继续定位；本轮只是阻止它折叠进 `100MHz` production TIME/SPEC 带内。
