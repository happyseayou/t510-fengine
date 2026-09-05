# Stage 1: Debug Observer Closure

## 阶段目标

清理 `fft_debug_observer` 的 `debug_error` 语义，让成功 capture 后目标 `DEBUG_STATUS=0x4`，bit1 只表示真正 fatal 错误。

## 输入基线

- Stage 0 已确认现有板上 debug capture 可读，但旧 bitstream 上 `DEBUG_STATUS=0x6` 曾被视作可接受。
- 当前 RTL 中 `fft_debug_observer` 会把 XFFT input backpressure 或 `event_data_in_channel_halt` 记为 error。

## 完成内容

- 修改 `rtl/fft_debug_observer.sv`：
  - 不再把采样流和 XFFT ready 的短时不匹配记为 fatal。
  - 不再把 `event_data_in_channel_halt` 直接映射为 `debug_error`。
  - 保留 `event_tlast_unexpected`、`event_tlast_missing` 和输出 `tlast` 不匹配作为 fatal。

## 验证证据

- 本地 Python 编译通过：
  ```bash
  python3 -m py_compile python/packet.py python/t510_fengine.py scripts/check_t510_packet_header.py
  ```
- 全量 XSim 通过：
  ```bash
  ./scripts/run_xsim_batch.sh
  ```
  结果：11 个 testbench 全部 PASS，包括 `tb_fft_debug_observer`。
- Vivado 实现和 bitstream：
  - `impl_1` 状态：`write_bitstream Complete`
  - bitgen：0 error，0 critical warning
  - timing：`WNS=+1.619 ns`，`WHS=+0.011 ns`
- 板端 debug capture 通过：
  ```bash
  cd /home/xilinx/t510_fengine_bringup
  source /etc/profile.d/xrt_setup.sh
  sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_fengine_debug_capture.py --mask 0x1 --timeout 2.0
  ```
  结果摘要：`debug_nfft=1024`，`debug_sample_rate_hz=61440000`，前 16 个 I 样本非零，`peak_bin=1016`。
- 板端寄存器复读确认：`DEBUG_STATUS=0x00000004`，`debug_busy=0`，`debug_error=0`，`debug_done=1`，`capture_count=1024`。

## 阶段衔接说明

- 下一阶段可依赖：debug capture 可作为可靠观测门禁；成功 capture 后 `DEBUG_STATUS=0x4` 已在板端确认。
- 下一阶段不能依赖：debug FFT 是 1024-point 观测器，不是 Stage 4 正式 4096-channel PFB。
- 剩余风险：debug observer 只覆盖单板 bring-up 观测，不覆盖 CMAC/QSFP 或正式 SPEC payload 正确性。
- 推荐入口命令：
  ```bash
  cd /home/xilinx/t510_fengine_bringup
  source /etc/profile.d/xrt_setup.sh
  sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_fengine_debug_capture.py --mask 0x1 --timeout 2.0
  ```

## AI 接续提示

- 看到 `DEBUG_STATUS=0x6` 时，应先怀疑 overlay 不是本次导出的 bitstream，或读到了旧板端状态；本次验收目标是 `0x4`。
- `core_version=0x00010002` 未随本阶段变化，接续时用 overlay hash 或 `DEBUG_STATUS` 行为判断。

## 阻塞项

- 无阻塞项影响 Stage 1。
