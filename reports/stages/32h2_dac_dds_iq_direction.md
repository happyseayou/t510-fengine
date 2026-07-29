# Stage 32h2：DAC DDS复数方向与新bitstream

## 状态

`NOT_STARTED`

## 目标

把PL DDS统一为标准正向复数`I=cos(theta), Q=sin(theta)`，保持
`baseband=requested_rf-center`、偶数word为I、奇数word为Q和128-bit AXIS排列
不变。`phase_deg=0`正式对应正I轴。

## 实施与门禁

- [ ] 更新DDS tone和constant-phasor模式。
- [ ] XSim验证正/负复频率、四样点/拍、八通道、enable mask和phase epoch。
- [ ] 全量XSim、Python、Rust和`git diff --check`通过。
- [ ] 启动非阻塞`synth_1 -> impl_1 -> write_bitstream`后停止后续工作。
- [ ] 用户确认新bit完成后检查route、timing、DRC、bit SHA和overlay。
- [ ] 按Stage 32发布顺序上板并验证320的60/280 MHz、160的120/220 MHz。

## 冻结项

`CORE_VERSION=0x00010032`，LMK、MTS target、UDP、PFB和REST schema不变。

## 回滚

上板失败时只允许恢复上一Stage 32 bitstream，不回退Stage 31。
