# Stage 23：CMAC 100G、三档科学带宽与真实 I/Q RF 等效波形

## 当前结论

本阶段先把不会撒谎的部分落地：Jupyter 增加 `RF等效(I/Q回算)` 视图，三档科学带宽和 TIME/SPEC 输出模式进入 Python API、notebook 控件和 RTL 控制寄存器；RFDC 到 science path 的内部数据源已从 256-bit 低位截断修成 1024-bit 完整 4 sub-sample beat，并接入三档 PL rate selector；同时把 QSFP/CMAC live science 的阻塞条件显式暴露。

Stage 23 bitstream 已重新生成并导出到 `overlay/`：

- `overlay/t510_fengine.bit` SHA256 `01488c23831f2f53715103fa0a2106c68965ba033ed5944b2bc814e320eab057`
- `overlay/t510_fengine.hwh` SHA256 `c6400e1a31f3034b5cad81a75d8ef32b9aa4915e54ea970979ee7ac7431d030a`
- `CORE_VERSION=0x00010012`

当前不能声明 QSFP live science data 通过。原因不是 QSFP 线缆没接，而是硬件数据面仍未完成真实 `cmac_usplus` 100G/512-bit TX path、async packet FIFO、真实 4096-channel 4-tap PFB/FFT。Stage 23 代码会把这些状态标成 `BLOCK`，不允许 dry-run 冒充 live。

板端 Stage 23 gate 已执行，结果为预期 `BLOCK`，不是失败：

- `CORE_VERSION=0x00010012`
- `QSFP_MODULE_PRESENT_BUT_CMAC_NOT_READY`
- `tx_qsfp_module_present=1`
- `tx_gt_locked=0`
- `tx_cmac_reset_done=0`
- `tx_cmac_tx_ready=0`
- `pps_seen=1`、`pps_recent=1`、`ref_status_locked=1`
- live blocker：`CMAC_LINK_NOT_READY,WIDE_512B_TX_PATH_NOT_IMPLEMENTED`
- `science_after` blockers：`SPEC_SCIENCE_BLOCKED_PFB_SCAFFOLD`、`CMAC_LIVE_BLOCKED_NO_GT_DATAPATH`、`WIDE_512B_TX_PATH_NOT_IMPLEMENTED`、`FORCED_DRY_RUN`
- 板端 JSON：`reports/board/stage23_qsfp_science_check.json`

## 已实现

- `CORE_VERSION` 更新为 `0x00010012`。
- `python/t510_fengine.py` 新增：
  - `estimate_science_payload_rate(bandwidth_mhz, output_mode)`
  - `configure_science_output(bandwidth_mhz, output_mode, force_dry_run, cmac_enable)`
  - `read_cmac_status()`
  - `run_qsfp_live_validation()`
  - RF 等效波形字段：`rf_equivalent_waveform`、`derived_from_real_iq=True`、`raw_rf=False`
- Jupyter notebook 13 新增：
  - 三档带宽：`20 / 100 / 200 MHz`
  - 输出模式：`OFF / TIME_ONLY / SPEC_ONLY / TIME_SPEC / TIME_MONITOR_SPEC`
  - `RF等效(I/Q回算)` 波形模式
  - QSFP module present、CMAC ready、science sample rate、payload Mbps、BLOCK reason 状态显示
- RTL 控制面新增 `0x0d000..0x0d020` science 寄存器窗口：
  - 带宽模式、输出模式、有效复采样率、PL decim、payload Mbps、capability、block reason
  - `200MHz + TIME_SPEC` 硬件侧置 `TIME_SPEC_200M_REJECTED`
  - SPEC scaffold、CMAC/GT 数据面、512-bit path 作为 block reason 暴露
- RTL 数据源新增/修正：
  - `rfdc_adc_axis_adapter.sv` 的正式 science bus 改为 `1024-bit`：每个 RFDC beat 保留 `4 sub-sample x 8 complex I/Q`，不再只取每 RFDC port 低 16 bit。
  - 新增 `science_rate_selector.sv`：`200MHz` 透传 x1，`100MHz` 每两个 RFDC beat 输出 4 个 decimated sample，`20MHz` 每八个 RFDC beat 输出 4 个 decimated sample；selector 不反压 RFDC，后级堵塞会计数 drop。
  - `time_packetizer.sv` / `spectral_packetizer.sv` 的 payload 分片已泛化到 `1024-bit -> 64-bit`。
  - `time_packetizer.sv` 的 8192B payload buffer 已从寄存器数组改为 XPM BRAM。第一次实现时 Vivado 在 `payload_mem[*][1023]` 上暴露出大 fanout/BUFG 插入，place 阶段长时间停在 post-placement optimization；该结构已修正，避免把 1024-bit payload 缓存综合成大面积寄存器和高 fanout 控制网。
  - `pfb_channelizer.sv` 仍是 pass-through scaffold，但已按 `cells_per_beat` 修正 1024-bit 窗口计数，避免包长/窗口语义错位。
- QSFP module-present 进入 `TX_STATUS` bit12；板上插入 QSFP 模块时 Jupyter/脚本可以区分“模块存在”和“CMAC未就绪”。
- 新增 `scripts/pynq_stage23_qsfp_science_check.py`，用于板端三档模式矩阵、CMAC 状态和 live validation gate。

## 三档科学带宽

- `20MHz`：PL decim x8，复采样率 `30.72 MS/s`，允许 `TIME_ONLY / SPEC_ONLY / TIME_SPEC`。
- `100MHz`：PL decim x2，复采样率 `122.88 MS/s`，允许 `TIME_ONLY / SPEC_ONLY / TIME_SPEC`。
- `200MHz`：PL decim x1，复采样率 `245.76 MS/s`，只允许 `TIME_ONLY / SPEC_ONLY`；`TIME_SPEC` 明确拒绝。
- `TIME_MONITOR_SPEC` 只表示 TIME full stream 加低速监控频谱，不等同 full SPEC science。

## QSFP/CMAC 资料状态

已从 T510 公共 PDF 抽取 QSFP0 Bank128 管脚资料，后续可用于真实 CMAC 接入：

- QSFP0 refclk：`M28/M29` 或 `K28/K29`
- QSFP0 RX1..4：`P33/P34`、`M33/M34`、`K33/K34`、`H33/H34`
- QSFP0 TX1..4：`N30/N31`、`L30/L31`、`J30/J31`、`G30/G31`

注意：当前还没有把这些 GT 端口接入 board top，也没有生成可验收的 CMAC live science 数据面。Stage 23 bitstream 可用于 Jupyter、三档 rate selector、science control/status 和 dry-run/witness 门禁；不能用于 live pcap 科学数据验收。

## 必须继续 BLOCK 的问题

- `SPEC_SCIENCE_BLOCKED_PFB_SCAFFOLD`：当前 `pfb_channelizer.sv` 仍是 pass-through scaffold，不是真实 PFB/FFT。
- `CMAC_LIVE_BLOCKED_NO_GT_DATAPATH`：board top 当前仍无真实 CMAC/GT TX datapath。
- `WIDE_512B_TX_PATH_NOT_IMPLEMENTED`：当前 TX path 仍是旧 64-bit packet/frame path。

已清掉的问题：

- `RFDC_SCIENCE_BUS_TRUNCATED_TO_LOW16`：已修。硬件 block reason bit4 现在应为 `0`；`tb_feng_ctrl_axi` 已覆盖默认、20MHz TIME_SPEC、200MHz TIME_SPEC 三种状态。

## 本地验证

- Python/Jupyter：
  - `python3 -m py_compile python/t510_fengine.py python/packet.py scripts/pynq_stage23_qsfp_science_check.py`
  - notebook 13 JSON/AST parse PASS
  - grep gate PASS：旧虚拟波形关键词未回到主绘图路径
- XSim：
  - `./scripts/run_xsim_batch.sh tb_science_rate_selector tb_rfdc_adc_axis_adapter tb_pfb_channelizer tb_time_packetizer tb_spectral_packetizer tb_t510_fengine_top_smoke tb_feng_ctrl_axi tb_t510_fengine_board_top`
  - 结果：all XSim batch testbenches passed
- Vivado：
  - `synth_1`：0 errors、0 critical warnings
  - `impl_1`：route_design Complete
  - `check_bitstream_readiness`：READY
  - post-route timing：WNS `+1.248 ns`、WHS `+0.011 ns`、failed endpoints `0/106509`
  - route status：failed/unrouted/partially-routed nets 均为 `0`
  - placed utilization：CLB LUT `50165/425280 = 11.80%`，CLB registers `59960/850560 = 7.05%`，BRAM tile `62.5/1080 = 5.79%`，DSP `79/4272 = 1.85%`，Bonded IOB `18/152 = 11.84%`
  - bitgen：0 errors、0 critical warnings；有普通 DRC warnings，主要是 DAC loopback DDS DSP output pipeline 建议、debug FFT BRAM WRITE_FIRST advisory、RFDC unused status nets。
  - overlay export PASS：`overlay/t510_fengine.manifest.txt` 指向 Stage 23 bit/hwh。
- 板端：
  - overlay/Python/scripts/notebook 已同步到 PYNQ Jupyter 目录。
  - 远端 SHA256 与本地一致。
  - 远端 Python py_compile PASS。
  - `scripts/pynq_stage23_qsfp_science_check.py`：`result=BLOCK`，`science_data_validated=false`。
  - 三档模式矩阵：`20/100 MHz` 的 `TIME_ONLY/SPEC_ONLY/TIME_SPEC` 均 dry-run configured；`200 MHz TIME_ONLY/SPEC_ONLY` dry-run configured；`200 MHz TIME_SPEC` 明确 `TIME_SPEC_200M_REJECTED`。

## 下一步

1. 替换 `pfb_channelizer.sv` scaffold 为真实 4096-channel 4-tap PFB/FFT；做不到则 SPEC live science 保持 BLOCK。
2. 接入 `cmac_usplus` 100G：GT refclk、QSFP lane、reset/status、512-bit AXIS、async FIFO。
3. 把当前 64-bit UDP frame builder/live shell 替换为真正 512-bit CMAC TX path。
4. 真实 CMAC/GT 数据面完成后再跑 `scripts/pynq_stage23_qsfp_science_check.py --try-live`，随后做接收端 MTU 9000 + pcap 验证。
