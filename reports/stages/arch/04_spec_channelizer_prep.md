# Stage 4: SPEC Channelizer Prep

## 阶段目标

为正式 4096-channel SPEC channelizer 和后续 CMAC/QSFP bring-up 做接口准备，同时保持当前单板闭环可用。

## 输入基线

- Stage 2 已提供多路 preview 调试接口。
- Stage 3 已提供 header v2 和 dry-run packetizer/counter。
- 当前 RFDC adapter 仍是每 64-bit RFDC port 取 `[15:0]` 的 bring-up 路径。

## 完成内容

- 保持 `rfdc_adc_axis_adapter` 当前单板 bring-up 行为不变，避免破坏 Stage 0 已验证路径。
- 通过 header v2 固定 SPEC layout 字段：`chan0`、`chan_count`、`time_count`、`ninput`、`payload_format`。
- 保留 Stage 4 后续入口：在 channelizer 接入前，先以 dry-run SPEC header/counter 和 preview spectrum 验证控制面。

## 验证证据

- `tb_spectral_packetizer` 已覆盖 SPEC v2 header 和 channel wrap。
- 全量 XSim 通过。
- Vivado 实现和 bitstream 通过：`write_bitstream Complete`，0 error，0 critical warning，`WNS=+1.619 ns`，`WHS=+0.011 ns`。
- Stage 2 preview 单路板端 capture 已通过，可作为后续 PFB 接入前的 ADC 观测入口。
- Stage 3 time-mode dry-run counters 已在板端增长；SPEC dry-run 仍待切到 `mode=spec` 后专项验证。

## 阶段衔接说明

- 下一阶段可依赖：SPEC packetizer header 字段约定、dry-run sink 机制、PYNQ preview API、当前实现/timing 门禁。
- 下一阶段不能依赖：正式 4096 PFB/FFT 尚未实现；RFDC adapter 仍不是最终吞吐设计；CMAC/QSFP 未接入。
- 剩余风险：正式 PFB 的资源、时序、缩放、窗函数、payload layout 需要单独设计和验收。
- 推荐入口命令：
  ```bash
  ./scripts/run_xsim_batch.sh tb_spectral_packetizer tb_t510_fengine_top_smoke
  ```

## AI 接续提示

- 不要把当前 debug FFT 当成正式 4096-channel PFB。
- 不要把当前 RFDC adapter 的 `[15:0]` bring-up 映射当成最终多样本吞吐路径。
- 接入 PFB 前，先写单独的 channelizer testbench 和 payload layout checker。

## 阻塞项

- 正式 4096-channel PFB/FFT 未实现。
- CMAC/100G 未接入。
- SPEC mode 板端 dry-run counter 和 header capture 尚未专项验收。
