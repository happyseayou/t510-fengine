# Stage 34：全速固定 8-tap PFB 发布

## 产品合同

- `CORE_VERSION=0x00010034`，bitstream ID 为 `fengine-0x00010034`。
- SPEC 固定使用 4096 通道、8 路复数 IQ16、8-tap PFB，不提供 4/8-tap 切换。
- 原型滤波器为对称 Hamming-windowed sinc，共 32768 个 tap-major Q1.17 系数。
- 每相系数和精确为 131072；profile ID 为 `0x34a80001`，IEEE/zlib CRC32 为
  `0xb9ba227c`。
- 群时延为 16383.5 个选定采样率样本：320 MS/s 时约 51.198 us，160 MS/s 时
  约 102.397 us。UDP v2 布局、FFT 通道顺序和包率不变。

## 实现

- PFB 使用 8 个 4096×256-bit 帧存储器和 active/shadow 两组 8×4096×18-bit
  系数存储器。
- 128 个 16×18-bit DSP 乘法器同时完成 `8 lanes × I/Q × 8 taps`，随后经
  37/38/39-bit 三级平衡加法树、Q17 对称舍入和 IQ16 饱和。
- 系数索引扩展为 15 bit，加载必须从 0 到 32767 严格连续；旧 4-tap、乱序、
  重复和不完整 profile 均不能提交。
- `0x0978` 返回 active profile CRC32。`PFB_TILE_OVERFLOW_COUNT` 重新定义为
  包含任一 FIR 饱和分量的 PFB cell 数，软件名为 `fir_saturation_count`。

## 定点特性

| 指标 | 定点结果 |
|---|---:|
| 0.25 bin | +0.0295 dB |
| 0.4 bin | -1.2055 dB |
| 0.5 bin | -6.0199 dB |
| 0.75 bin | -49.4649 dB |
| 1..4 bin 最坏阻带 | -57.8915 dB |
| ENBW | 0.9072586 bin |
| 最大每相 L1 增益 | 1.6518707 |

160/320 MS/s 的 ENBW 分别约为 35.44/70.88 kHz。深阻带以定点模型和 XSim
为权威；DAC-ADC 模拟回环受转换器固定杂散和模拟底噪限制。

## 验证状态

- Python 单元测试：100/100 PASS；覆盖系数数量、范围、全局对称、逐相精确归一、
  CRC32、定点响应、ENBW、L1 增益和固定 taps=8 拒绝策略。
- Rust Board Agent/receiver：Board Agent 7/7、receiver 42/42 PASS；receiver 对
  当前 UDP v2 要求 `pfb_taps == 8`，旧 4-tap 数据明确拒绝。
- XSim：18/18 testbench PASS。PFB 主测试使用真实生产 Hamming 系数，覆盖 8 帧
  启动、跨帧 bit-exact、随机输出 FIFO 压力、严格连续加载/poison、CRC、零输入、
  最大正负输入和故意 FIR 饱和；顶层 smoke 同时确认 UDP header 固定 taps=8。
- Vivado 2022.2 current-project 构建完成：`synth_1=synth_design Complete!`、
  `impl_1=write_bitstream Complete!`，设计为 Fully Routed，299230 个 routable nets
  全部完成，route error 为 0。322.266 MHz CMAC 时钟保持不变；routed
  `WNS=+0.046 ns`、`WHS=+0.010 ns`，setup/hold failing endpoint 均为 0。
- routed 整机资源为 129504 LUT、175493 FF、553 RAMB36、194 RAMB18 和 760 DSP；
  即 650 BRAM tiles（约 60.2%）和 760/4272 DSP（约 17.8%）。PFB+XFFT 层级为
  37766 LUT、63723 FF、256 RAMB36、160 RAMB18 和 248 DSP，即 336 BRAM tiles；
  其中 128 个新 PFB FIR 乘法器均保留为 DSP48E2。
- DRC 和 methodology 均没有 Error 或 Critical Warning；现有条目只有 Warning/
  Advisory。拥塞报告中 PFB 区域最高为 level 5，level 6 仍位于既有
  `science_decim2_halfband_aa`。PFB 高扇出项的最坏时序余量均为正；例如
  `pfb_s5_negative` fanout 2930/slack +0.303 ns，`pfb_r0_coeff` fanout
  2021/slack +0.132 ns。实现日志唯一 Critical Warning 是既有 CMAC Evaluation
  License Warning，不是 PFB、约束或 route 问题，继续作为发布风险显式保留。
- latest-only current-project export、RFDC HWH/XCI 合同和 repository `overlay/`
  原子更新通过。正式 bitstream SHA-256 为
  `c21d93f5ea71e9ac17a4448cff138a8faaf9c7347d879be919b680d196b8a5be`。
- MTS discovery/fixed 使用同一 bitstream SHA 重新完成 40/40，固定 target 为 ADC/DAC
  `416/112`；discovery、RFDC reset、overlay reload和LMK reload矩阵全部通过。
- 八路时域回环通过：各路最低 SNR 为 `58.08 dB`，最坏相位峰峰值 `0.362 deg`，
  最坏幅度峰峰值 `0.541%`，无 clip，结束后 STOP 且八路 DAC 静音。
- 160/320 MS/s 八路 PFB 频响回环均通过，频率方向、峰值 bin、半 bin 和八路归一化
  一致性符合门限，FIR saturation、XFFT overflow、drop/gap 均为零。
- 五个合法全速模式的 60 秒矩阵、160 TIME_SPEC/320 SPEC_ONLY 各 10 分钟以及
  320 SPEC_ONLY 60 分钟最大负载 soak 均通过；板端、NIC、ring、worker、application
  drop以及 seq/frame/sample0 gap 增量均为零。
- catalog、Board Agent、receiver和部署入口已经原位发布 v34。320 MS/s 全带 63 窗
  原始 QSFP UDP 扫描也通过，共 32,256 包、63 份 PCAP；DAC 静音条件下重复候选只落在
  已冻结的 480/960/1440 MHz 固定项。

因此 Stage 34 的数字发布闭合为
`IMPLEMENTED / ROUTED_TIMING_PASS / BITSTREAM_COMPLETE / MTS_40X40_PASS /
8LANE_LOOPBACK_PASS / FULLRATE_STABILITY_PASS / RELEASE_DEPLOYED`。面向长积分、弱谱线和
外部 TG 的科学定标由 [Stage 34a](34a_astronomy_performance_evaluation.md) 单独负责。

后续实际结果：Stage 34a 的数字路径仍通过，但长积分存在时间相关噪声，未取得天文资格；
[Stage 34b-1](34b-1_rfdc_calibration_control.md)证明RFDC软件freeze可用，随后
[Stage 34b-2](34b-2_calibration_causality.md)完成正式A/B/C但训练冻结未恢复积分规律；后续
[Stage 34c](34c_adc_correlated_noise_root_cause.md)已实现共享50 Ω参考与条件OCB1因果实验，
其正式长任务结果尚待回填。该科学评估结果不撤销Stage 34的数字发布结论，也没有产生
新bitstream。
