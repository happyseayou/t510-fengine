# Stage 27f: SPEC Full F-engine Science Stream

## 阶段目标

把 Stage 27e reduced/windowed SPEC preview 收紧为正式 F-engine science stream 合约：SPEC 不再按 8 个 preview block 解释，而按 `FENGINE_IQ16`、4096 channel、64 个 64-channel blocks、每包 8192B payload 输出和接收。

## 本轮完成

- RTL/control path:
  - `CORE_VERSION=0x00010021`。
  - TX endpoint 扩为 72 个逻辑 endpoint：TIME `4300..4307`，SPEC `4308..4371`。
  - SPEC route 扩为 64 路，默认 `chan0 = route_id * 64`，每路一个 SPEC UDP port。
  - `spectral_packetizer` 增加 27f header extension：`product_id=0xf101`、`nchan=4096`、`block_index/block_count=64`、`taps`、`fft_shift`、`sample_rate_hz`、status flags。
  - `feng_ctrl_axi` 增加 high route tables：endpoint `0x13000..`，SPEC route `0x14000..`，TIME route `0x14800..`，并暴露 route hit readback。
  - `pfb_channelizer` 已从 pass-through/window scaffold 切到 `feng_channelizer_4096` wrapper：1024b science beat 拆成 4 个 256b XFFT samples，进入 4-sample PFB FIR 后接 `t510_fengine_xfft_4096`。
  - F-engine wrapper 新增 ping-pong 4-frame spectrum tile buffer：收满 `4 x 4096` 个 FFT output cells 后，按 64 个 64-channel blocks 连续发出 `chan0=0,64,...,4032` 的 8192B SPEC payload，`packet_chan_count=64`、`packet_time_count=4`；仿真已覆盖连续 2 个 full-spectrum tile、`overflow_count=0`。
  - 新增 `spec_udp_cmac512` 生产 SPEC 发送路径：`pfb_channelizer -> spec_udp_cmac512 -> cmac_tx_source_mux`，SPEC live 不再走旧 `spectral_packetizer -> tx_route_selector -> udp_frame_builder -> axis64_to_cmac512_async` 64b bridge。
  - CMAC mux 生产源收口为 heartbeat、native 512b TIME、native 512b SPEC；旧 64b SPEC path 仅保留为 legacy/header-capture 辅助，不作为 27f production science gate。
  - `spec_udp_cmac512` 直接生成 27f header extension，包含 `product_id=0xf101`、`nchan=4096`、`block_index/block_count=64`、`taps`、`fft_shift`、`sample_rate_hz`、status flags。
  - `FENGINE_SCIENCE_VALID` 不再被 `FORMAL_XFFT_BACKEND_COMPILED=0` 强制拉低；现在由合法 27f window、`taps>=4`、4096-channel 配置和 XFFT config handshake 共同决定。
- Python:
  - 新增 `configure_science_27f(...)`，默认配置 8 TIME + 64 SPEC routes。
  - rate estimator 已按 full SPEC 估算：`TIME_SPEC 100MHz ~= 62914.56 Mbps payload`。
  - `TIME_SPEC 200MHz` 继续在配置和 validation 中拒绝。
  - Stage 27f validation 要求 `FENGINE_SCIENCE_VALID`、64 route coverage、无 overflow/drop/route miss；当前 full-block XFFT path 不应再因 `PFB_FFT_NOT_READY` 失败，但若出现 PFB overflow、route miss 或 host drop 仍必须 FAIL。
- Rust/Web:
  - receiver 默认接收 72 flows，SPEC decoder 严格要求 `FENGINE_IQ16`/4096/64 blocks/64 channels/taps>=4。
  - Web spectrum websocket 升级为 `TSP3` v2，发送 full 4096-bin assembled spectrum。
  - UI 增加 amplitude/phase、power spectrum、waterfall，并解释 `X=I+jQ`、`|X|=sqrt(I^2+Q^2)`、`phase=atan2(Q,I)`、`power=I^2+Q^2`。
  - ingest path 始终 drain/validate/计数全量 TIME/SPEC 包；较重的 spectrum decode/assemble 只在有 spectrum websocket client 时按 Web FPS 抽样执行。
- Host:
  - 新增 `scripts/host_stage27f_rx_fanout_tune.sh`，默认 `4300..4371`。
  - 新增 `scripts/host_stage27f_rust_rx_validate.py`，默认 8 TIME + 64 SPEC flows，复用成熟 drop/gap/NIC gate，并输出 Stage 27f 分类名。
- Vivado project:
  - `scripts/stage27f_create_fengine_xfft_ip.tcl` 已可生成 `t510_fengine_xfft_4096` XFFT IP；本机已生成 `demo-ant.srcs/sources_1/ip/t510_fengine_xfft_4096/t510_fengine_xfft_4096.xci`。
  - Vivado 2022.2 的 XFFT v9.1 当前不接受 `pipelined_streaming_io` architecture value，脚本会优先尝试 streaming，失败后明确 fallback 到 `automatically_select` 并继续生成 IP。
  - `scripts/setup_project.tcl` 会在该 XCI 存在时自动加入工程。
  - XFFT v9.1 `realtime` 输出侧没有 `m_axis_data_tready`，当前已用单 tile buffer 吸收 4 帧输出并完成 64-block 扫出；后续 100MHz sustained no-drop 仍需要 ping-pong/更深频谱缓存，或把 SPEC packet/TX 路径改宽到能持续吞下完整 4096-bin product。

## 关键解释

- 27e `TIME_SPEC 100MHz` 总流量只有约 32Gbps，是因为 SPEC 仍是 reduced/windowed preview stream：TIME 约 30Gbps，SPEC 只有少量 window block。
- 27f 的目标是 full TIME + full SPEC。对 100MHz 档，TIME payload 约 `31.46Gbps`，SPEC payload 约 `31.46Gbps`，合计约 `62.91Gbps payload`。
- amplitude/phase 来自每个频率 bin 上的复电压 `X = I + jQ`：幅度是该 bin 复电压大小，相位是该 bin 相对采样/同步参考的复相角。功率谱默认从 `I^2+Q^2` 派生，瀑布图是功率谱随时间滚动的历史。

## 验证

本地已通过：

```bash
python3 -m py_compile python/t510_fengine.py scripts/pynq_stage27f_science_fengine_bringup.py scripts/host_stage27f_rust_rx_validate.py
cargo test -q
./scripts/run_xsim_batch.sh tb_pfb_channelizer tb_spec_udp_cmac512 tb_time_udp_cmac512 tb_t510_fengine_top_smoke tb_tx_route_selector
```

结果：全部 PASS。

新增覆盖点：

- `tb_pfb_channelizer`：连续 2 个 full 4096-bin tile、64-block sweep、非 pass-through、`overflow_count=0`。
- `tb_spec_udp_cmac512`：64 个 SPEC blocks 全覆盖，默认 ports `4308..4371`，T510 v2 header、`FENGINE_IQ16` product、`nchan=4096`、`block_index=0..63`、payload alignment、route hit counters。
- `tb_t510_fengine_top_smoke`：生产 SPEC 通过 `cmac_tx_axis` 发出 27f header，route 0 hit；TIME native 512b 回归继续通过。

## 当前边界

- 当前 RTL 已接通正式 Xilinx 4096 XFFT 数据面，并且已经完成 full 4096-bin、64-block SPEC payload sweep；不再是 selected-window preview，也不再输出 raw pass-through。
- 生产 SPEC 已从旧 64b packetizer/bridge 迁移到 512b CMAC path；route/UDP bridge 不再是已知的 100MHz SPEC 限速主因。
- 当前仍有两个硬门槛：第一，4-tap PFB coefficient ROM/scale schedule 需要从当前 4-sample FIR 收紧为正式 polyphase 系数；第二，持续 full-rate 输入需要继续处理 1024b science beat 到 256b XFFT input 的吞吐边界。当前 wrapper 每个 1024b beat 拆成 4 个 256b XFFT samples，若上游按 100MHz 档持续满速给 beat，`s_axis_tready` 仍可能呈约 1/4 duty；若板端仍见 `spec_dropped_count/pfb_overflow_count`，下一刀应优先加输入侧 elastic FIFO/更宽或多 lane FFT feed，而不是回退到 reduced SPEC。
- 因此板端验收应先把 `SPEC_ONLY 20/100/200` 和 `TIME_SPEC 20/100` 作为真实 XFFT full-block bring-up 跑通，并重点记录 `pfb_overflow_count`、64-block route hit coverage、host drop/gap 和 waterfall/spectrum 连续性；在 sustained buffering/wide-TX 完成前，不应把 100MHz `62.9Gbps payload` 宣称为已闭环。

## 生产范围收口

按当前 27f 决策，后续生产验收只保留两类功能：

- TIME/SPEC 科学数据流：native 512b TIME + native 512b SPEC/F-engine IQ16，经 72-flow endpoint/route 表输出。
- Jupyter 控制与预览：board 控制、TIME/SPEC 状态、8 路时域预览、频谱/幅相/瀑布显示。

旧 dry-run、raw witness、legacy 64b SPEC、历史 debug observer 可以继续作为 bring-up/仿真辅助，但不再作为 production science 通过条件，也不能阻塞核心数据流收敛，除非它们暴露出会影响 TIME/SPEC 或 Jupyter 控制预览的真实问题。

2026-06-25 进一步收口：Stage 27f 发布和接续入口默认只同步/推荐生产白名单：

- `overlay/`
- `python/`
- `scripts/pynq_stage27f_science_fengine_bringup.py`
- `notebooks/13_astronomer_rf_observation_console.ipynb`
- `notebooks/README.md`

其他历史脚本和 notebook 仍留在仓库，定位为 archived bring-up aids。新的板端 JSON validation 输出也会带 `production_scope` 字段，明确生产通过只看 TIME/SPEC science streams 与 Jupyter control/preview。
