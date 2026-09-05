# Stage 6: PFB/FFT Channel Window Dry-Run

## 阶段目标

把 Stage 5 的 SPEC dry-run payload 合约推进到 4096-channel channelized payload window：在无 CMAC/QSFP 条件下，闭合 `chan0/chan_count/time_count/ninput/payload_bytes=8192` 与实际 dry-run 数据窗口的一致性。

本阶段是可综合 channel-window dry-run channelizer，不声明科学级 4-tap PFB 幅相标定完成。

## 输入基线

- Stage 5 已完成 packet FIFO、TX header capture 和 SPEC dry-run counters。
- Stage 5b 已发布 8 路 Jupyter 虚拟示波器/频谱仪，CH0 物理闭环严格门禁可用。
- 顶层设计要求的正式 SPEC payload layout 为 `channel_window[time][channel][input][IQ16]`。
- PYNQ 目标：`xilinx@192.168.100.117`。

## 完成内容

- 新增 `rtl/pfb_channelizer.sv`：
  - 默认 `nchan=4096`、`taps=4`、`chan0=0`、`chan_count=64`、`time_count=4`。
  - 256 个 256-bit beat 对应 `64 channel x 4 time x 8 input x IQ16 = 8192B`。
  - 输出 PFB status、frame counter、overflow counter、peak channel/power。
- 更新 SPEC 数据面：
  - `axis_stream_duplicator -> requantizer -> pfb_channelizer -> spectral_packetizer`。
  - `spectral_packetizer` header 的 `chan0/chan_count/time_count` 来自 PFB window 配置/状态。
- 新增 `0x0900..0x092c` PFB 控制状态寄存器，`CORE_VERSION=0x00010004`。
- 扩展 Python/Jupyter：
  - `configure_channelizer()`、`read_channelizer_status()`、`capture_pfb_preview()`。
  - 新增 `scripts/pynq_pfb_channel_window_check.py`。
  - 更新 `notebooks/10_8lane_realtime_virtual_instrument.ipynb`，增加 PFB window 控件、状态栏和 TX header capture。
- 同步并发布到 PYNQ：
  - `/home/xilinx/t510_fengine_bringup`
  - `/home/xilinx/jupyter_notebooks/t510_fengine`

## 验证证据

- 本地检查：
  ```bash
  python3 -m py_compile python/packet.py python/t510_fengine.py scripts/check_t510_packet_header.py scripts/pynq_spec_dry_run_check.py scripts/pynq_jupyter_instrument_smoke.py scripts/pynq_8lane_instrument_check.py scripts/pynq_pfb_channel_window_check.py
  python3 -m json.tool notebooks/09_single_board_virtual_instrument.ipynb >/dev/null
  python3 -m json.tool notebooks/10_8lane_realtime_virtual_instrument.ipynb >/dev/null
  ./scripts/run_xsim_batch.sh tb_pfb_channelizer tb_spectral_packetizer tb_t510_fengine_top_smoke tb_feng_ctrl_axi tb_axi4_to_axil_bridge
  ```
  结果：全部 PASS。
- Vivado：
  - synthesis：0 errors，0 critical warnings。
  - implementation/write_bitstream：0 errors，0 critical warnings。
  - post-route timing：`WNS=+2.533 ns`，`WHS=+0.010 ns`，失败端点 `0/51765`。
  - bitstream：`overlay/t510_fengine.bit`，SHA256 `dc4fdae7767ad6994ee9b4489d38ee40b54b4f45a2d8e34915db2e9a95c623cd`。
- PYNQ Stage 5 回归：
  ```bash
  cd /home/xilinx/t510_fengine_bringup
  source /etc/profile.d/xrt_setup.sh
  sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_spec_dry_run_check.py --mask 0x1 --seconds 0.5 --timeout 2.0
  ```
  结果：PASS，`CORE_VERSION=0x00010004`，`UDP_DRY_RUN=1`，`QSFP_LINK_UP=0`，captured SPEC header `chan_count=64,time_count=4,payload_bytes=8192`。
- PYNQ Stage 5b 回归：
  ```bash
  sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_8lane_instrument_check.py --channels 8 --samples 512 --timeout 2.0
  ```
  结果：PASS，8 路 preview 可读，CH0 debug FFT strict gate `5 MHz` 通过，CH1..CH7 仍为 digital/control only。
- PYNQ Stage 6 验收：
  ```bash
  sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_pfb_channel_window_check.py --chan0 0 --chan-count 64 --time-count 4 --timeout 2.0
  ```
  结果：PASS。
  - `core_version=0x00010004`
  - `pfb_nchan=4096`
  - `pfb_taps=4`
  - `pfb_chan0=0`
  - `pfb_chan_count=64`
  - `pfb_time_count=4`
  - `pfb_config_valid=1`
  - `pfb_frame_count` 从 `146` 增长到 `33705`
  - `pfb_overflow_count=0`
  - TX header：`version=2 stream_type=SPEC chan0=0 chan_count=64 time_count=4 ninput=8 payload_bytes=8192 flags=INTERNAL_EPOCH|UDP_DRY_RUN`
- Jupyter 发布路径确认：
  - `/home/xilinx/jupyter_notebooks/t510_fengine/notebooks/10_8lane_realtime_virtual_instrument.ipynb`
  - `/home/xilinx/jupyter_notebooks/t510_fengine/overlay/t510_fengine.bit`

## 阶段衔接说明

- 下一阶段可依赖：
  - `CORE_VERSION=0x00010004`。
  - PFB/channel-window dry-run payload contract：`chan0=0`、`chan_count=64`、`time_count=4`、`ninput=8`、`payload_bytes=8192`。
  - Stage 5 packet FIFO、TX header capture、dry-run counters 仍可用。
  - Stage 5b Jupyter scope/spectrum 仍可作为 CH0 物理闭环和 8 路 preview/control 入口。
- 下一阶段不能依赖：
  - CMAC/QSFP 真实 UDP 发包。
  - DGX/X-engine 实际收包。
  - 科学级 4-tap PFB 幅相标定或窗函数系数精度。
  - CH1..CH7 模拟闭环。
- 剩余风险：
  - `pfb_channelizer` 当前是 channel-window dry-run，payload 内容仍是 bring-up 数据路径，不是最终 PFB 频域输出。
  - bitgen 普通 warnings 仍包括既有 DAC loopback DSP pipeline 建议和 RFDC unused status nets；本阶段没有新增 critical warning。
  - HWH 来自同一 BD，时间戳未变化；寄存器扩展在 PL RTL/AXI aperture 内，不依赖 BD address map 变化。
- 推荐入口命令：
  ```bash
  cd /home/xilinx/t510_fengine_bringup
  source /etc/profile.d/xrt_setup.sh
  sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_pfb_channel_window_check.py --chan0 0 --chan-count 64 --time-count 4 --timeout 2.0
  ```
  Jupyter：打开 `http://192.168.100.117/lab` 或 `http://192.168.100.117:9090/lab`，进入 `t510_fengine/notebooks/10_8lane_realtime_virtual_instrument.ipynb`。

## AI 接续提示

- 判断是否进入 Stage 6，优先看 `CORE_VERSION=0x00010004`、`PFB_STATUS bit1 config_valid=1`、`PFB_FRAME_COUNT` 增长、captured header 的 `chan_count=64/time_count=4/payload_bytes=8192`。
- 不要把 Stage 6 称为正式 PFB 科学输出；它闭合的是 channel-window contract 和 dry-run 可观测性。
- 后续若接 CMAC/QSFP，必须保留 `capture_tx_header()` 作为 header 语义门禁，再增加真实链路收包证据。
- 不要在脚本、notebook 或报告中记录 SSH 明文密码。

## 阻塞项

- CMAC/QSFP 真实发包未接入。
- DGX/X-engine 收包未验证。
- 正式 4096-channel 4-tap PFB 幅相标定未完成。
- CH1..CH7 尚无物理模拟闭环。
