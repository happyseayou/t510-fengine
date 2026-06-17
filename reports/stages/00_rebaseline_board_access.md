# Stage 0: Rebaseline Board Access

## 阶段目标

确认 PYNQ 可达、同步当前工程交付物，并在无 QSFP、无 PPS/10 MHz 条件下复测现有 ADC0/DAC0 单板闭环。

## 输入基线

- 架构输入：`reports/arch/t510_fengine_refined_architecture_v0_3/t510_fengine_refined_architecture_v0_3.html`。
- 当前状态输入：`reports/arch/t510_fengine_current_status_report.html`。
- PYNQ 目标：`xilinx@192.168.100.117`。
- 同步路径：`/home/xilinx/t510_fengine_bringup`。

## 完成内容

- 已同步目录：`overlay/`、`python/`、`scripts/`、`notebooks/`。
- 同步文件数：`overlay=4`、`python=4`、`scripts=7`、`notebooks=10`。
- 已重新导出 overlay：`overlay/t510_fengine.bit/.hwh/.tcl/.manifest.txt`。
- PYNQ 端 `overlay/t510_fengine.bit` SHA256 与本地一致：`12d02026e8d4a248bb705ed640e8e7ca0473b808917d1e967bcd255173c3bcfd`。
- 确认 PYNQ venv 可 import `pynq`。
- 确认必须 source `/etc/profile.d/xrt_setup.sh` 后，`pynq.Device.devices` 才能枚举到 `EmbeddedDevice`。

## 验证证据

- SSH/PYNQ：ping 可达，SSH 22 开放。
- Vivado/overlay：
  - `impl_1` 状态：`write_bitstream Complete`
  - bitgen：0 error，0 critical warning
  - timing：`WNS=+1.619 ns`，`WHS=+0.011 ns`，失败端点 `0/43385`
  - `check_bitstream_readiness`：`READY`
- 环境：
  - hostname: `pynq`
  - kernel: `5.15.19-xilinx-v2022.1`
  - Python: `/usr/local/share/pynq-venv/bin/python3`
  - overlay bit/hwh: present
- Loopback 命令通过：
  ```bash
  sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_adc0_dac0_loopback_check.py --mask 0x1 --seconds 0.5
  ```
  结果摘要：`sync_config=0x00010002`，`rfdc_status_flags=0x1f`，`rfdc_current_valid_mask=0xffff`，`fsm_state=6`，`streaming=1`，`rfdc_sample_count` 从 `197116707` 增长到 `240512912`，`time_packet_count=33376`，PASS。
- Debug capture 命令通过：
  ```bash
  sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_fengine_debug_capture.py --mask 0x1 --timeout 2.0
  ```
  结果摘要：`core_version=0x00010002`，`debug_nfft=1024`，`debug_sample_rate_hz=61440000`，前 16 个 I 样本非零，Q 为 0，`peak_bin=1016`，`peak_frequency_hz_unshifted=60960000.000`。

## 阶段衔接说明

- 下一阶段可依赖：PYNQ 网络、XRT/PYNQ venv、overlay 文件同步路径、最新 bitstream 上板、ADC0/DAC0 free-run 闭环。
- 下一阶段不能依赖：QSFP/CMAC 真实链路、外部 PPS/10 MHz、正式 PFB 输出。
- 剩余风险：板端命令如果忘记 source XRT，会报 `RuntimeError: No Devices Found`；`core_version` 未递增，接续时应核对 overlay hash 或寄存器行为。
- 推荐入口命令：
  ```bash
  cd /home/xilinx/t510_fengine_bringup
  source /etc/profile.d/xrt_setup.sh
  sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_fengine_debug_capture.py --mask 0x1 --timeout 2.0
  ```

## AI 接续提示

- 板端失败时先检查 XRT 环境，不要直接判断 overlay 或 RFDC RTL 失败。
- 报告中不得记录明文密码。
- 当前报告对应的 overlay 已经重新 synthesis/implementation/export 并同步到 PYNQ；后续 RTL 改动后仍必须重复这一流程。

## 阻塞项

- 无阻塞项影响 Stage 0。
- Stage 0 已完成当前 overlay 的上板基线复测。
