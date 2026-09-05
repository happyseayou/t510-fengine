# Stage 27j：TIME_SPEC 100MHz 可编程 RTL PFB

## 范围

Stage 27j 保持 Stage 27i 的 `TIME_SPEC 100MHz` 生产线约束不变，在此基础上加入真正的 4-tap RTL PFB 数据通路：

- `CORE_VERSION=0x0001002C`
- build defines：`T510_STAGE27H_PRODUCTION_ONLY + T510_STAGE27I_ANTI_ALIAS + T510_STAGE27J_PFB`
- 24 条 UDP flow，端口 `4300..4323`
- TIME flow：8 条
- SPEC flow：16 条，布局为 `4096ch / 16 blocks / 256ch / 1 time / 8 input / IQ16`
- SPEC payload 保持 `8192B` 不变
- 验收 gate 仍为 `TIME_SPEC 100MHz`，combined T510 UDP payload `>=63Gbps`

27j 的 SPEC header 约定：

- `pfb_taps=4`
- FFT-only flag bit8 清零
- AA100 bit9 置位
- PFB-active status bit10 置位

## 实现记录

- `rtl/pfb_channelizer.sv`
  - 在 XFFT 前加入 4-frame ring buffer 和 4-tap Q1.17 polyphase FIR。
  - 生产模式只接受 `taps=0` FFT-only 和 `taps=4` PFB。
  - 前 3 个输入 frame 只用于 PFB priming，不发出 SPEC 包。
  - PFB 输出 `sample0` 使用参与 FIR 输出的最早输入 frame。
  - 系数使用 active/shadow 双 bank，支持 MMIO load、checksum 和 stopped/idle commit。
  - Q1.17 累加输出路径加入符号对称 rounding。
- `rtl/science_decim2_halfband_aa.sv`
  - AA100 FIR 路径加入符号对称 magnitude rounding，消除 DAC 幅度为 0 时看到的稳定 DC bias。
- `rtl/feng_ctrl_axi.sv`
  - 新增 `0x0960..0x097c` PFB coefficient MMIO，版本更新为 `0x0001002C`。
- `rtl/t510_fengine_top.sv`
  - 27j 下不再把 PFB taps 硬连为 0；实际 active taps 进入 SPEC sideband/header。
- Python/Rust
  - Python 新增 `configure_science_27j`、`load_pfb_coefficients`、默认 Hamming-windowed sinc 系数和 27j 板端 validator。
  - Rust 新增 `stage27j` SPEC layout 校验：布局仍为 `16x256x1`，但要求 `pfb_taps>=4`，不再要求 FFT-only。

## 本地检查

当前 DC-round 增量检查已完成：

- `python3 -m py_compile python/t510_fengine.py scripts/pynq_stage27j_time_spec_pfb.py scripts/host_stage27j_rust_rx_validate.py scripts/pynq_stage27i_antialias_spur_acceptance.py scripts/pynq_stage27h_rfdc_spur_audit.py`
- `git diff --check`
- 受影响数据路径的 XSim 已通过：
  - `tb_pfb_channelizer`
  - `tb_science_rate_selector`
  - `tb_time_udp_cmac512`
  - `tb_spec_udp_cmac512`

`tb_t510_fengine_top_smoke` 在本轮启动过，但几分钟后被中断，因此不计入 post-DC-round 完整通过项。

## Vivado 闭合

当前 routed/bitstream 报告位于 `reports/board/stage27j_dc_round_*`。

- routed timing：`reports/board/stage27j_dc_round_impl_timing_summary.rpt`
  - WNS `+0.053ns`
  - TNS `0.000ns`
  - WHS `+0.010ns`
  - THS `0.000ns`
  - failing endpoints `0`
- route status：`reports/board/stage27j_dc_round_route_status.rpt`
  - fully routed nets `224828 / 224828`
  - routing errors `0`
- bitstream SHA256：
  - `overlay/t510_fengine.bit`
  - `demo-ant.runs/impl_1/t510_fengine_board_top.bit`
  - `46cfef4643331e3676fc5e7c7050fdf8a7a0a4ea928673fd7836a694953e380d`
- routed DCP：
  - `reports/board/stage27j_dc_round_routed_latest.dcp`
  - SHA256 `500a10dd10322393f0404e2f5cfdecc5c6652ea041514caa19a3c7a43c74f40c`

同一 SHA 的 overlay 已发布到 PYNQ/Jupyter。

## 板端 Gate

最终 10 秒 board gate：

- 报告：`reports/board/stage27j_dc_round_time_spec_100mhz_pfb_board_v2.remote.json`
- classification：`STAGE27J_TIME_SPEC_100MHZ_PFB_BOARD_PASS`
- core：`0x0001002c`
- TIME：`480601.3pps`
- SPEC：`480601.4pps`
- combined T510 UDP payload：`63977.651712Mbps`
- PFB：
  - active `1`
  - taps `4`
  - coefficient active valid `1`
  - active taps `4`
  - coeff id `0x27A40001`
  - checksum `536870912`
- SPEC routes：16 条 enabled route 全部命中
- 测量窗口内 delta：
  - TIME/SPEC drops `0`
  - RFDC/science drops `0`
  - route miss/error `0`
  - PFB overflow `0`
  - XFFT event `0`

validator 现在从同一个 `read_status()` measurement snapshot 推导最终 TX ready 状态，避免测量窗口之后再读 `read_tx_status()` 带来的瞬时 race。live read 仍保留在报告里用于审计；通过报告里唯一不一致项是自然递增的 `tx_frame_sent_count`。

## 主机 Gate

anti-alias 的 download-each-case 流程结束后，Rust receiver 已重启，最终 host 进程可继续使用。

- 运行 PID：`3440840`
- 命令：`rust/t510_time_rx/target/release/t510_time_rx --backend fanout ... --spec-layout stage27j --web 0.0.0.0:8089`
- Web：`http://127.0.0.1:8089`
- 最终 clean-window 报告：`reports/board/stage27j_dc_round_rust_rx_time_spec_100mhz_host_post_restart.json`
- classification：`HOST_STAGE27J_RUST_RX_PASS`
- active workers：`24`
- TIME：`480825.103pps`
- SPEC：`479721.653pps`
- combined T510 UDP payload：`63933.992048Mbps`
- 10 秒 delta：
  - parse errors `0`
  - ring/worker-ring/kernel/app drops `0`
  - TIME seq/frame/sample0 gaps `0`
  - SPEC seq/frame gaps `0`
- preview：
  - waveform updates `46`
  - spectrum updates `71`
  - display `3.98Hz`
  - spectrum `6.98Hz`

receiver 在 FPGA 已经发包时启动，因此累计状态里保留了启动瞬间的 gap；生产 gate 使用的是后续干净的 10 秒 delta 窗口。

## 零幅度中心 Bin 检查

显式把 DAC 设置为 amplitude `0`、enable mask `0xff`，保持 27j PFB active，然后通过 host SPEC websocket 抓取并解析 30 个完整 4096-bin frame。

- 报告：`reports/board/stage27j_dc_round_zero_amp_center_bin_probe.json`
- 完整 frame：`30 / 30`
- header：`pfb_taps=4`，`spec_status_flags=0x677`
  - FFT-only bit8 清零
  - AA100 bit9 置位
  - PFB-active bit10 置位
- center bin RF：`100.000MHz`
- center-bin average power：
  - mean `5.14dB`
  - min `2.73dB`
  - max `8.53dB`
  - mean above median floor `0.07dB`
  - median rank `2238 / 4096`
- 最强 bin 不稳定：
  - 30 个 frame 中出现 29 个不同 peak bin

结论：符号对称 rounding 修复后，DAC 幅度为 0 时不再出现稳定的 center-bin PFB peak。剩余低电平 peak 是量化底噪起伏，不是固定 DC/PFB 伪峰。

## Anti-Alias 验收

no-download multi-case 尝试不作为最终验收依据，因为没有 reset XFFT 的重复 stop/start 会让 IP 内部残留 TLAST/overflow 状态。最终验收使用每个 case 前 fresh download 的方式。

- 最终报告：`reports/board/stage27j_dc_round_antialias_spur_acceptance_20260711_download_each.remote.json`
- ok：`true`
- classification：`stage27i_100m_antialias_spur_suppressed`
- core：`0x0001002c`
- cases：`5`
- 每个 case：
  - `downloaded_before_case=true`
  - PFB active `1`
  - PFB taps `4`
  - PFB overflow `0`
  - XFFT event `0`
  - clean gate `true`
- zero-amplitude 122.88MHz target-bin SNR：
  - enable `0xff`：SPEC `2.62dB`，TIME `3.61dB`
  - enable `0x00`：SPEC `2.00dB`，TIME `1.94dB`
  - DAC NCO `60MHz`：SPEC `1.76dB`，TIME `2.28dB`
  - DAC NCO `100MHz`：SPEC `1.46dB`，TIME `1.75dB`
- reference tone：
  - expected `60.01MHz`
  - SPEC peak `60.01MHz`，SNR `73.01dB`
  - TIME peak `59.92MHz`，SNR `68.88dB`
- 27j PFB spectral purity：
  - main peak `60.01MHz`
  - strongest out-of-main spur `120.01MHz`
  - main-to-spur `55.48dB`
  - required `35.00dB`
  - header ok，`pfb_taps=4`，`spec_flags=0x677`

## 最终运行状态

验收后，板端已 fresh download 恢复到 nominal 27j observation：

- 报告：`reports/board/stage27j_dc_round_restore_nominal.stdout.json`
- DAC enable mask `0xff`
- DAC amplitude `2048`
- DAC tone mode `constant_phasor`
- RFDC active/current valid mask `0xffff`
- science mode `TIME_SPEC`
- bandwidth `100MHz`
- sample rate `122.88MS/s`
- PFB active `1`
- PFB taps `4`
- PFB coefficient valid `1`
- PFB overflow `0`
- XFFT event count `0`

Host UI config 已恢复为 center/expected/DAC `100MHz`。

## 已知后续

- XFFT IP 仍没有直接 reset。严格的 no-download 重复 stop/start 不属于 27j gate；multi-case audit 应在每个 case 前 fresh-download。
- 200MHz `SPEC_ONLY` backpressure 仍不属于 27j gate。
- 长时间 soak 和科学标定仍是后续工作；27j 验收的是 production candidate 数据通路和传输契约，不声明最终科学标定闭合。

## 100MHz 中心、60MHz DAC 右侧 Peak 复查

在用户复查 GUI 频谱时，观察条件为 center `100MHz`、DAC `60MHz`。右侧可见一个随 DAC amplitude 改变的 peak；为确认是否来自 27j RTL PFB，进行了 fresh-download sweep 和 live amplitude sweep。

- fresh-download sweep：`reports/board/stage27j_center100_dac60_amp_sweep_20260711.json`
- live amplitude sweep：`reports/board/stage27j_center100_dac60_live_amp_sweep_20260711.json`
- 观测条件：
  - center `100MHz`
  - expected/DAC `60MHz`
  - bandwidth `100MHz`
  - SPEC layout `stage27j`
  - PFB active `1`
  - PFB taps `4`

live sweep 结果：

| DAC amplitude | 主峰 60.01MHz | 右侧 120.01MHz | 120MHz 相对主峰 | 140MHz |
| ---: | ---: | ---: | ---: | ---: |
| 0 | 12.2dB | 6.4dB | -5.8dB | 6.5dB |
| 512 | 64.9dB | 28.2dB | -36.8dB | 6.5dB |
| 1024 | 71.0dB | 26.4dB | -44.6dB | 6.3dB |
| 2048 | 77.0dB | 22.2dB | -54.7dB | 6.6dB |
| 4096 | 83.0dB | 14.7dB | -68.3dB | 6.5dB |
| 8192 | 89.0dB | 21.5dB | -67.5dB | 6.4dB |

结论：

- 右侧稳定 peak 的位置是 `120.01MHz`，对应 DAC `60MHz` 的二次频率。
- 如果是围绕 `100MHz` center 的镜像，候选位置应为 `140MHz`；实测 `140MHz` 基本贴近底噪。
- clean 状态下所有 sweep 点均保持 `pfb_overflow=0`、`pfb_overflow_count=0`、`pfb_xfft_event_count=0`，没有 XFFT TLAST error。
- 线性 4-tap FIR + FFT PFB 在无 overflow/XFFT error 条件下不应产生二次谐波；该 peak 更符合 DAC/RFDC/模拟回环链路中的二次谐波或二阶耦合。
- amplitude 会影响该 peak 的可见性，但实测绝对功率不随 amplitude 单调增加；GUI 的 auto-scale/waterfall max-pool 可能使满幅状态看起来最明显。

复查结束后，板端恢复到用户当前排查条件：center `100MHz`、DAC `60MHz`、DAC amplitude `8192`。1 秒状态检查中 TIME/SPEC 继续出包，`pfb_overflow=0`、`pfb_xfft_event_count=0`。

## Stage 27j 完成声明

Stage 27j 已完成：以 TIME/SPEC `100MHz` 为 gate，启用 4-tap RTL PFB，保持 24-flow/16-SPEC-route 传输契约，PYNQ 和 host 验证通过，anti-alias spur acceptance 通过。`200MHz SPEC_ONLY` backpressure 和后续科学标定不属于 27j 完成条件。
