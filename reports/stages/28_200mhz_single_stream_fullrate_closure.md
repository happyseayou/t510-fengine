# Stage 28: 200MHz TIME_ONLY / SPEC_ONLY 全速率闭合

## 结论

Stage 28 在 `0x00010030` 上闭合以下三个生产组合：

- `100MHz TIME_SPEC`
- `200MHz TIME_ONLY`
- `200MHz SPEC_ONLY`

`200MHz TIME_SPEC` 继续因 100GbE 容量限制而不属于生产范围。UDP payload、header、端口分配、4096-channel `16 x 256` SPEC 布局和 Rust wire format 均未改变。

## Vivado 产物

- bitstream SHA256: `7486a55b6f7e50e5875474e7d85299b107e9384cfff454316f64f2d3d7e9800d`
- fully routed nets: `222232 / 222232`
- routing errors: `0`
- WNS/TNS: `+0.051 ns / 0.000 ns`
- WHS/THS: `+0.010 ns / 0.000 ns`
- setup/hold failing endpoints: `0 / 0`
- routed checkpoint: `reports/vivado/stage28_final_0x00010030_realtime_xfft/t510_fengine_board_top_routed.dcp`
- build reports: `reports/vivado/stage28_final_0x00010030_realtime_xfft/`

CMAC 生产配置保持 base CMAC + RS-FEC，`INCLUDE_AUTO_NEG_LT_LOGIC=0`、`INCLUDE_AN_LT_TX_TRAINER=0`、`INCLUDE_RS_FEC=1`。Vivado 2022.2 `cmac_usplus v3.1` catalog 无条件声明 `cmac_an_lt` key 的 warning 仍作为已知厂商元数据项保留，生成 netlist 未启用 AN/LT。

## 60 秒 fresh-download 板端验收

| 组合 | TIME pps | SPEC pps | payload | 结果 |
| --- | ---: | ---: | ---: | --- |
| 100MHz TIME_SPEC | 480169.27 | 480169.33 | 63.920 Gb/s | PASS |
| 200MHz TIME_ONLY | 960891.82 | 0 | 63.957 Gb/s | PASS |
| 200MHz SPEC_ONLY | 0 | 960999.93 | 63.964 Gb/s | PASS |

三个窗口的 `rfdc/science/time/spec drop`、route miss/error、PFB capture backpressure、XFFT input/output halt、overflow、TLAST missing/unexpected 增量均为 0。SPEC 模式为 4096 channel、4-tap coefficient bank valid，16 条 SPEC route 全部启用并命中。

证据：

- `reports/board/stage28_100mhz_time_spec_board_0x00010030_60s.json`
- `reports/board/stage28_200mhz_time_only_board_0x00010030_60s.json`
- `reports/board/stage28_200mhz_spec_only_board_0x00010030_60s.json`

## 60 秒 Rust 主机验收

| 组合 | workers | TIME pps | SPEC pps | payload | 结果 |
| --- | ---: | ---: | ---: | ---: | --- |
| 100MHz TIME_SPEC | 24 | 480081.69 | 480073.26 | 63.908 Gb/s | PASS |
| 200MHz TIME_ONLY | 8 | 960483.59 | 0 | 63.930 Gb/s | PASS |
| 200MHz SPEC_ONLY | 16 | 0 | 960408.80 | 63.925 Gb/s | PASS |

三个最终窗口的 PACKET_MMAP ring、worker ring、kernel、app、parse 和 NIC error 增量均为 0；TIME seq/frame/sample0 gap 与 SPEC seq/frame gap 增量均为 0。对应模式的 waveform/spectrum 均持续更新。

证据：

- `reports/board/stage28_100mhz_time_spec_host_0x00010030_60s_queue4_retry1.json`
- `reports/board/stage28_100mhz_time_spec_host_0x00010030_60s_queue4_retry2.json`
- `reports/board/stage28_200mhz_time_only_host_0x00010030_60s_queue4.json`
- `reports/board/stage28_200mhz_spec_only_host_0x00010030_60s_queue4.json`

## 主机物理丢包闭合

在 FPGA 板端计数器正常后，本轮没有继续修改 FPGA 发包来迁就主机。初始 100MHz/24-worker 60 秒窗口记录了 `rx_discards_phy=348`、`rx_prio0_discards=348`，同时 FPGA drop/backpressure/error 仍全为 0；失败证据保留在 `reports/board/stage28_100mhz_time_spec_host_0x00010030_60s.json`。

验证主机的 ConnectX-5 RX buffer 为 `262016 bytes`。在约 64Gb/s 下，旧 `rx-usecs=32` 的合并窗口约对应 `256 KiB` 到达数据，几乎等于整个物理 RX buffer；降到 `8 us / 32 frames` 后仍有极低概率 physical discard，单独启用 CQE compression 或完全关闭 coalescing 也未闭合。

最终接收侧配置保持 24 个逻辑 flow/worker，但用 ntuple 将端口按 `flow_id % 4` 映射到 4 个 hardware RX queues，并使用 `rx-usecs=8`、`rx-frames=32`。每队列约 `240 kpps / 16 Gb/s`，连续两个 60 秒窗口的 NIC physical discard、Rust drop 和所有 gap 均为 0。生产入口为 `scripts/host_stage28_rx_fanout_tune.sh`。

最终 4-queue 部署参数也分别完成两个 200MHz 单流的 fresh-download 10 秒复核：TIME_ONLY 为 `959682.94 pps / 63.876 Gb/s`，SPEC_ONLY 为 `960774.98 pps / 63.949 Gb/s`；两个窗口的 NIC/Rust drop 和所有 gap 增量均为 0。

- `reports/board/stage28_200mhz_time_only_board_0x00010030_10s_queue4.json`
- `reports/board/stage28_200mhz_time_only_host_0x00010030_10s_queue4.json`
- `reports/board/stage28_200mhz_spec_only_board_0x00010030_10s_queue4.json`
- `reports/board/stage28_200mhz_spec_only_host_0x00010030_10s_queue4.json`

## 范围边界

本阶段不声明 `200MHz TIME_SPEC`、X-engine/Beamformer、Stage 29 模块裁剪、payload 收紧、交换机/DGX、科学幅相/功率标定或更长时间 soak 已完成。

生产 Jupyter 入口沿用 `notebooks/15_stage27h_time_spec_fft_fullrate_control.ipynb` 文件名，已更新为 Stage 28 三组合控制和按模式预览，并锁定 `CORE_VERSION=0x00010030`。
