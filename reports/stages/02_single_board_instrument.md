# Stage 2: Single Board Instrument

## 阶段目标

把单板调试能力从单 DAC tone/单 ADC debug 预览扩展为 8 路 DAC 可控和多路 preview capture。

## 输入基线

- Stage 0 证明 ADC0/DAC0 free-run 闭环可用。
- Stage 1 使 debug observer 的 done/error 语义更干净。

## 完成内容

- 新增 `rtl/multi_preview_observer.sv`：
  - 支持 8 路 complex preview。
  - 所有路共享同一次 capture 的 `sample0`。
  - `0x2800 + input*0x1000 + sample*4` 读取 preview buffer。
- 扩展 `rtl/feng_ctrl_axi.sv`：
  - `0x0600..0x06ff`：8 路 DAC 控制。
  - `0x0700..0x0718`：preview control/status/sample0/nsamp。
  - 保留旧 `0x0440..0x0448` DAC broadcast 兼容寄存器。
- 扩展 `rtl/t510_dac_loopback_source.sv`：
  - 8 路独立 enable、amplitude、phase step、phase0、phase inject、mode。
  - 当前 mode 只实现 `single_tone`。
- 扩展 `python/t510_fengine.py`：
  - `set_dac_tone(channel=...)`
  - `set_dac_enable_mask(...)`
  - `capture_preview(...)`
  - `capture_preview_spectrum(...)`

## 验证证据

- `tb_feng_ctrl_axi` 覆盖 DAC mask、per-channel phase/amplitude/phase inject、preview status/sample0/buffer readback。
- 全量 XSim 通过：
  ```bash
  ./scripts/run_xsim_batch.sh
  ```
- Python 编译通过。
- Vivado 实现和 bitstream 通过：`write_bitstream Complete`，0 error，0 critical warning，`WNS=+1.619 ns`，`WHS=+0.011 ns`。
- 板端 preview 最小冒烟通过：
  - 运行条件：已由 Stage 0/1 初始化为 `streaming=1`
  - 读回：`dac_enable_mask=0xff`
  - 触发：`capture_preview(n=16, input_mask=0x1, timeout=2.0)`
  - 结果：`PREVIEW_STATUS=0x00000004`，`preview_done=1`，`preview_error=0`，`preview_capture_count=1024`，`sample0=1893948642`
  - `preview_iq0_first8=[(108,0),(115,0),(105,0),(93,0),(92,0),(81,0),(85,0),(75,0)]`

## 阶段衔接说明

- 下一阶段可依赖：新寄存器契约、Python API、preview 单路板端 capture、implementation/timing 均已过门禁。
- 下一阶段不能依赖：8 路 DAC 相位/频率变化与多路 preview 峰值的完整对应关系尚未专项验收。
- 剩余风险：多路同时 preview、跨通道相位一致性、DAC 输出到 ADC 输入的模拟链路关联还需要实验矩阵。
- 推荐入口命令：
  ```bash
  cd /home/xilinx/t510_fengine_bringup
  source /etc/profile.d/xrt_setup.sh
  sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_fengine_debug_capture.py --mask 0x1 --timeout 2.0
  ```

## AI 接续提示

- 当前 overlay 已包含 Stage 2 新寄存器；后续修改 Stage 2 RTL 后仍需重新导出并同步。
- `capture_preview_spectrum()` 是 PYNQ 端软件 FFT，用于多路调试预览，不替代正式 4096-channel PFB。

## 阻塞项

- 8 路 DAC phase/frequency 改变与 preview spectrum peak 的系统性验收尚未完成。
- notebook UI 尚未完整重做成多路交互仪器；Python API 已先落地。
