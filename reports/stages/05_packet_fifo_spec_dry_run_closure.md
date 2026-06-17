# Stage 5: Packet FIFO + SPEC Dry-Run Closure

## 阶段目标

紧扣顶层架构中“连续高速流不默认走 DDR、packet FIFO 聚合 8192B payload、无 QSFP 仍可 dry-run 观测”的要求，补齐 SPEC dry-run 数据面闭环。

本阶段只声明 packetizer/FIFO/header/dry-run 语义闭合；不声明 CMAC/QSFP 真实发包成功，也不声明正式 4096-channel PFB 已接入。

## 输入基线

- 架构输入：`reports/arch/t510_fengine_refined_architecture_v0_3/t510_fengine_refined_architecture_v0_3.html`。
- Stage 3 已固定 128B UDP header v2 和 dry-run flags/counters。
- Stage 4 已把 SPEC layout 语义作为后续 channelizer/CMAC bring-up 的交接点。
- PYNQ 目标：`xilinx@192.168.100.117`。
- 当前实验条件：无 QSFP、内部 epoch/free-run、ADC0 单路作为稳定板端观测入口。

## 完成内容

- 新增 `rtl/axis_packet_fifo.sv`：64-bit AXIS packet FIFO，插在 `udp_tx_arbiter` 输出之后、dry-run sink/未来 CMAC 之前。
- 新增 FIFO 状态统计：当前水位、高水位、backpressure cycles。
- 新增 `rtl/tx_header_capture.sv`：可 arm 后抓取 TX 输出的前 16 个 64-bit word，即 128B T510 header。
- `rtl/feng_ctrl_axi.sv` bump `CORE_VERSION` 到 `0x00010003`，并新增寄存器：
  - `0x036c TX_FIFO_LEVEL_WORDS`
  - `0x0370 TX_FIFO_HIGH_WATER_WORDS`
  - `0x0374 TX_FIFO_BACKPRESSURE_CYCLES`
  - `0x0378 TX_HEADER_CAPTURE_CONTROL`
  - `0x037c TX_HEADER_CAPTURE_STATUS`
  - `0x0380..0x03fc TX_HEADER_CAPTURE_BUFFER`
- `python/packet.py` 增加 AXIS64 header word 解析入口和 `to_dict()`。
- `python/t510_fengine.py` 增加 TX FIFO/status 字段和 `capture_tx_header(timeout=...)`。
- 新增 `scripts/pynq_spec_dry_run_check.py`，板端验证 `mode=spec`、dry-run counters、FIFO high-water 和 header parser。
- 新增/扩展仿真覆盖：`tb_axis_packet_fifo`、AXI control readback、top smoke 的 SPEC dry-run/header 路径。
- 重新综合、实现、生成 bitstream、导出 overlay 并同步到 PYNQ。

## 验证证据

- 本地 Python/Notebook sanity：
  ```bash
  bash -n scripts/pynq_publish_jupyter_instrument.sh
  python3 -m py_compile python/packet.py python/t510_fengine.py scripts/check_t510_packet_header.py scripts/pynq_spec_dry_run_check.py scripts/pynq_jupyter_instrument_smoke.py
  python3 -m json.tool notebooks/09_single_board_virtual_instrument.ipynb >/dev/null
  ```
  结果：`STAGE5_LOCAL_SANITY_OK`。
- XSim：`./scripts/run_xsim_batch.sh` 全量通过；`.xsim_batch` 日志显示 `tb_axis_packet_fifo`、`tb_t510_fengine_top_smoke` 等 testbench 均 PASS。
- Vivado：`impl_1/write_bitstream Complete`；`ERROR=0`，`CRITICAL WARNING=0`；post-route timing `WNS=+2.267 ns`，`WHS=+0.011 ns`，失败端点 `0/50758`。
- Stage 5 overlay：
  - `overlay/t510_fengine.bit` SHA256：`ccad09450a8a84e4cfac91d11dcacdce51acecb703707b8d1b0b7687eae7b448`
  - `overlay/t510_fengine.hwh` SHA256：`95fd94741fc83ac4d4d94f330e1032eb90bc54a63462c3f46aeb8935ac6b700b`
- Stage 0 复跑：`scripts/pynq_adc0_dac0_loopback_check.py --mask 0x1 --seconds 0.5` PASS；`streaming=1`，`fsm_state=6`，`rfdc_current_valid_mask=0x0000ffff`，`rfdc_sample_count` 从 `197274343` 增至 `240601316`。
- Stage 1 复跑：debug capture 成功；`DEBUG_STATUS=0x00000004`，`DEBUG_DONE=1`，`DEBUG_ERROR=0`，`PEAK_POWER=247794850`。
- Stage 5 板端专项：
  ```bash
  cd /home/xilinx/t510_fengine_bringup
  source /etc/profile.d/xrt_setup.sh
  sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_spec_dry_run_check.py --mask 0x1 --seconds 0.5 --timeout 2.0
  ```
  结果：`PASS`。
- Stage 5 板端关键读回：
  - `core_version=0x00010003`
  - `streaming=1`
  - `qsfp_link_up=0`
  - `udp_dry_run=1`
  - `tx_link_status_flags=0x00000002`
  - `tx_dry_run_packet_count` 从 `63` 增至 `33476`
  - `tx_dry_run_byte_count` 从 `531120` 增至 `278531928`
  - `spec_packet_count` 从 `54` 增至 `33467`
  - `tx_fifo_high_water_words=3`
  - captured header：`version=2`，`stream_type=0/SPEC`，`payload_bytes=8192`，`header_bytes=128`，`flags=0x000a`，即 `INTERNAL_EPOCH + UDP_DRY_RUN`。

## 阶段衔接说明

- 下一阶段可依赖：`CORE_VERSION=0x00010003`、AXIS packet FIFO 已在 top 数据面中、FIFO 水位/高水位/backpressure counter 可读、TX 128B header 可抓取并由 Python parser 解析、无 QSFP 时 SPEC dry-run counters 会增长。
- 下一阶段不能依赖：CMAC/QSFP 真实 link-up、真实 UDP/IP/Ethernet 发包、DGX/X-engine 收包、正式 4096-channel PFB/FFT 输出。
- 剩余风险：当前 FIFO 已完成 smoke 和基本水位观测，但还没有长时间高吞吐/backpressure 压力测试；当前 SPEC payload 仍是 bring-up 数据路径，不是正式科学 PFB payload。
- 推荐入口命令：
  ```bash
  ./scripts/run_xsim_batch.sh tb_axis_packet_fifo tb_spectral_packetizer tb_t510_fengine_top_smoke
  python3 -m py_compile python/packet.py python/t510_fengine.py scripts/pynq_spec_dry_run_check.py
  ```
  板端：
  ```bash
  cd /home/xilinx/t510_fengine_bringup
  source /etc/profile.d/xrt_setup.sh
  sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_spec_dry_run_check.py --mask 0x1 --seconds 0.5 --timeout 2.0
  ```

## AI 接续提示

- `QSFP_LINK_UP=0` 且 `UDP_DRY_RUN=1` 是本阶段预期状态，不是失败。
- 判断 Stage 5 是否真的在板上运行，优先看 `CORE_VERSION=0x00010003`、`TX_FIFO_HIGH_WATER_WORDS>0` 和 captured header 的 `payload_bytes=8192`。
- `TX_HEADER_CAPTURE_BUFFER` 是 AXIS64 word 顺序，不是网络 byte dump；解析时使用 `T510PacketHeader.from_axis_words()` 或 `T510FEngine.capture_tx_header()`。
- 不要把本阶段的 SPEC dry-run 结果写成“CMAC 已发包”或“4096 PFB 已完成”。

## 阻塞项

- CMAC/QSFP 真实链路未接入。
- 正式 4096-channel PFB/FFT 未接入。
- FIFO/backpressure 还需要后续长时间压力和 link-up 切换测试。
