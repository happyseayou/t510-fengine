# T510 F-engine 阶段报告

本目录记录落地阶段状态。`reports/arch/` 是架构输入资料；本目录是执行状态和交接入口。

## 最新状态

- 最新开发状态：Stage 27h `TIME_SPEC 100MHz` 仅 FFT、全速 SPEC 生产门禁和 60 秒短稳验证已闭合。当前生产合约为 `CORE_VERSION=0x00010026`、TIME 端口 `4300..4307`、SPEC 端口 `4308..4323`、主机 `24` 条流；SPEC 为 `FENGINE_IQ16`、`4096` 个 channel、`16` 个 `256-channel x 1 spectrum-time x 8 inputs x IQ16` block、`8192B` 载荷，`spec_taps=0` 且 `spec_status_flags[8]=1` 标识 FFT-only。Vivado 布线和 `write_bitstream` 已满足时序，`overlay/t510_fengine.bit` SHA256 为 `e9f5bbf4a10132dd82857904790bd49761239ed4d3476fbde3236841b1094e82`。60 秒 PYNQ 板端门禁为 `STAGE27H_TIME_SPEC_100MHZ_FFT_FULLRATE_BOARD_PASS`，TIME `480463.23 pps`、SPEC `480463.22 pps`，合计 T510 UDP 载荷 `63959.264512 Mbps`，丢包/错误为 0；60 秒主机门禁为 `HOST_STAGE27H_RUST_RX_PASS`，`24` 个活跃工作线程，TIME `479915.88 pps`、SPEC `480019.95 pps`、合计 `63893.328649 Mbps`，丢包/间断为 0，波形/频谱预览持续更新。主机复测需使用 `scripts/host_stage27h_rx_fanout_tune.sh` 设置 performance governor、netdev budget/backlog、RX coalescing `1us/16 frames` 和 raw PREROUTING drop。Jupyter 生产入口为 notebook 15；notebook 14 保留为 27g 参考入口。27h 详见 `27h_time_spec_100mhz_fft_fullrate.md`，27g 基线详见 `27g_time_spec_100mhz_convergence.md`。
- Stage 27d 基线：`PACKET_FANOUT_HASH` 仅作为探索分支；最终验收路径已切到 `PACKET_FANOUT` + `ntuple` port steering。Host Rust receiver 在 `fanout=port`、`--pin-workers off`、`4300..4307 -> RX queue 0..7` 规则下，`20/100/200MHz TIME_ONLY` 三档均 PASS，`200MHz` 实测 `960.5 kpps`、`8` 个 active workers、`seq/frame/sample0` gap 与 `ring/kernel/NIC` drop/error delta 均为 `0`。对应报告见 `27d_packet_fanout_host_rx.md`。
- Stage 27c 历史闭环：`CORE_VERSION=0x0001001E`，DDR ring 已从 Stage 27c 数据面 compile-out，Vivado `impl_1` route clean、timing met、bitstream/export 完成；PYNQ 8-flow TIME sender 在 `20/100/200MHz` 三档板端 counters gate 均 PASS；本机 Rust/RSS receiver 在 `20MHz`、`100MHz` PASS，`200MHz` BLOCK 于 host RX/NIC path（约 `867 kpps` < `912 kpps` 门限，`rx_out_of_buffer`/`rx_missed_errors` 增长）。详见 `27c_multiflow_hardware_closure.md`。
- Stage 26b/27 历史事实：`0x0001001D` PL-only DDR TIME 缓冲与时序优化完成；DDR disabled direct path 已通过 `20/100/200MHz TIME_ONLY` 板端 counters/gates，Rust/HTML smoke 能动态显示 8 路 TIME waveform。DDR enabled path 触发 `BLOCK_STAGE26B27_DDR_ENABLE_BOARD_UNREACHABLE`，DDR ring 修复前不要再次启用。
- 当前本地 overlay 文件已更新为 Stage 27h `0x00010026` 产物：`overlay/t510_fengine.bit` SHA256 为 `e9f5bbf4a10132dd82857904790bd49761239ed4d3476fbde3236841b1094e82`。
- PYNQ 同步/板端状态：Stage 27h 比特流 SHA `e9f5bbf4a10132dd82857904790bd49761239ed4d3476fbde3236841b1094e82` 已发布到 `/home/xilinx/t510_fengine_bringup` 和 `/home/xilinx/jupyter_notebooks/t510_fengine`；远端 `overlay/t510_fengine.bit` 与 bring-up root `t510_fengine.bit` SHA 均匹配。板端门禁为 `STAGE27H_TIME_SPEC_100MHZ_FFT_FULLRATE_BOARD_PASS`。sudo 通道已确认可用；板端密码约定为“与登录用户名相同”，命令仍通过 stdin 传入凭据，不写入脚本或 notebook。
- Vivado 状态：Stage 27h 已完成时序收敛、布线、`write_bitstream` 和 overlay 导出。布线后时序 `WNS=+0.014838797 ns`、`TNS=0.000 ns`、`WHS=+0.010 ns`、`THS=0.000 ns`；bitstream 后时序 `WNS=+0.015 ns`、`WHS=+0.010 ns`；布线状态 `172486/172486` 条可布线网络全部完成布线，routing errors `0`。
- License 状态：Stage 27h `write_bitstream` 成功，但 bitgen run log 仍报 `Vivado 12-1790` evaluation license critical warning，源于 separately licensed CMAC feature use（`cmac_an_lt@2020.05 design_linking`）；`cmac_usplus@2020.05` 为 bought license。该 warning 未阻塞比特流生成，但生产验收前必须记录并确认 license 风险。
- Stage 25 验收边界：只证明 `20MHz TIME_ONLY` 低速 live TIME pcap 闭环；不声明 20/100/200MHz full science、SPEC/PFB、交换机/DGX/X-engine、ARP/VLAN/PTP 或长稳通过。
- Stage 26/26b/27 当前边界：只声明动态 `20/100/200MHz TIME_ONLY` full-rate direct path 板端 counters/gates、payload contract、本地回归、timing closure、bit/export 和 PYNQ 文件同步已落地；不声明 DDR enabled path、host pcap/Rust/HTML、SPEC/PFB、DGX/X-engine、交换机、PTP/VLAN/ARP 或长稳通过。
- Stage 27a 当前边界：Rust receiver v2 本地实现、release build、API smoke、UI 布局改造和 200MHz 实流短测已完成。receiver v2 能正确解析 TIME、`selected=detected=200MHz`、`parse_errors=0`，但主机单队列 `TPACKET_V3` 仍只处理约 `262 kpps / 17.45 Gbps`，低于 `960 kpps / 63.9 Gbps payload` 目标，且 `nic_rx_missed_errors_delta` 增长；不声明 host/Rust/HTML 实流无损 PASS。当前 blocker：`BLOCK_STAGE27A_HOST_NIC_SINGLE_QUEUE_RX_LIMIT`。
- Stage 27b 当前边界：只声明多 flow/RSS 接收方案、Rust/Web 60Hz binary waveform、本地 Rust/Python 回归、targeted XSim 和 host tuning 脚本已落地；尚未完成全量 XSim 回归、Vivado bitstream/export、PYNQ 同步或 20/100/200MHz 实流无损验收。当前下一步是重建 bitstream，然后用 `scripts/host_stage27b_rx_tune.sh` 记录 RSS/queue 证据并实测 8-flow 200MHz。
- Stage 27c 当前边界：声明 `0x0001001E` 版本 bump、DDR ring compile-out、Vivado bitstream/export、PYNQ 同步和板端 8-flow counters gate 已完成；routed timing `WNS=+0.005 ns`、`TNS=0.000 ns`、`WHS=+0.003 ns`，route errors `0`。Host Rust/RSS `20/100MHz` PASS；`200MHz` 当前分类 `BLOCK_STAGE27C_HOST_RSS_RX_LIMIT`，需下一阶段优化 host receive path。
- Stage 27e 当前边界：声明本地 RTL/Python/Rust 集成、验收脚本、Vivado route/timing、bitstream/export、PYNQ sync、板端 full matrix 和 host `TIME_SPEC 20MHz` Rust preview 已完成；不声明 host `TIME_SPEC 100MHz` no-loss、长稳、X-engine/DGX、交换机路径或科学级 PFB 标定通过。27e `TIME_SPEC 100MHz` 总流量约 32Gbps 的直接原因是 SPEC 仍为 reduced/windowed stream，非 full 4096-bin F-engine science stream。
- Stage 27g 当前边界：声明 `TIME_SPEC 100MHz` 生产短窗口板端加主机门禁已闭合；27g wrappers 和 notebook 14 作为 `/32` 节拍参考保留，不恢复 dry-run/raw witness/debug FFT/reduced SPEC 作为验收线。不声明长稳、科学级 PFB 幅相/功率标定、交换机/DGX/X-engine、ARP/VLAN/PTP 或全 RF 频段标定通过。
- Stage 27h 当前边界：声明 `TIME_SPEC 100MHz` 仅 FFT、全速 SPEC 生产收敛和 60 秒短稳验证已通过 Vivado 时序/比特流导出、PYNQ 板端门禁和主机 24 流无丢包/无间断门禁；不声明 10 分钟/1 小时/过夜长稳、科学级 4-tap PFB 幅相/功率标定、交换机/DGX/X-engine、ARP/VLAN/PTP 或全 RF 频段标定通过。
- Jupyter 入口：打开 `http://192.168.100.117/lab` 或 `http://192.168.100.117:9090/lab`，进入 `t510_fengine/notebooks/15_stage27h_time_spec_fft_fullrate_control.ipynb`。该 notebook 只保留生产控制和生产预览，预览仅包括 RF 还原波形与 FFT-only 生产频谱。
- 尚未完成：长时间 `TIME_SPEC 100MHz` soak、真实科学级 4096-channel 4-tap PFB 幅相/功率标定、交换机/接收节点 pcap、DGX/X-engine 收包、ARP/VLAN/PTP、长时间 FIFO/反压压力测试、`50-350 MHz` 全带 RF 频率/幅相/功率标定、浏览器端长时间 soak test。
- PYNQ 目标：`xilinx@192.168.100.117`；默认登录用户和 sudo 密码均为 `xilinx`。自动化命令通过 stdin 传入 sudo 密码，不要把密码硬编码进脚本或 notebook。
- PYNQ 运行 Python 前必须 source XRT：`source /etc/profile.d/xrt_setup.sh`，否则 `pynq.Device.devices` 为空。

## 阶段索引

1. `00_rebaseline_board_access.md`
2. `01_debug_observer_closure.md`
3. `02_single_board_instrument.md`
4. `03_udp_dry_run_time_semantics.md`
5. `04_spec_channelizer_prep.md`
6. `05_packet_fifo_spec_dry_run_closure.md`
7. `05a_jupyter_instrument_publish.md`
8. `05b_8lane_realtime_jupyter_instrument.md`
9. `06_pfb_fft_channel_window_dry_run.md`
10. `07_qsfp_cmac_udp_tx_preflight.md`
11. `08_dac_adc_coherent_instrument_closure.md`
12. `09_rf_instrument_console_v2.md`
13. `10_astronomer_rf_observation_console.md`
14. `11_rf_scope_window_phase_lock.md`
15. `12_stable_spectrum_waterfall.md`
16. `13_phase_provenance_hardware_audit.md`
17. `14_sample0_aligned_phase_preview.md`
18. `15_hardware_phase_audit_event_capture.md`
19. `16_rfdc_to_udp_coherence_witness.md`
20. `17_rfdc_sysref_coherence_lock.md`
21. `18_lmk_rfdc_mts_recovery_stability_gate.md`
22. `19_phase_drift_root_cause_closure.md`
23. `19b_external_adc_tone_decoupling.md`
24. `20_external_sync_8lane_validation.md`
25. `21_qsfp_link_pcap_preflight.md`
26. `22_jupyter_real_waveform_rfdc_raw_witness.md`
27. `23_cmac_100g_science_bandwidth_rf_equiv.md`
28. `24_qsfp0_cmac_100g_link_pcap_bringup.md`
29. `25_time_low_rate_live_cmac_pcap.md`
30. `26_time_full_rate_rx_payload.md`
31. `26b_27_pl_ddr_time_buffer_timing.md`
32. `27a_rust_time_receiver_v2.md`
33. `27b_multiflow_rss_web_waveform.md`
34. `27c_multiflow_hardware_closure.md`
35. `27d_packet_fanout_host_rx.md`
36. `27e_time_spec_live_science_preview.md`
37. `27f_fengine_science_stream.md`
38. `27g_time_spec_100mhz_convergence.md`
39. `27h_time_spec_100mhz_fft_fullrate.md`

## 推荐接续入口

Stage 27h 后续只按生产核心推进：`TIME/SPEC` 科学数据流，以及 Jupyter 端控制/预览。旧 dry-run、raw witness、debug FFT、历史 notebook、Stage 27g `/32` 节拍和 reduced/window SPEC 只作为必要时追根因的归档/参考工具，不再作为 27h 生产验收主线。当前接续重点是复现/长稳 `TIME_SPEC 100MHz` 仅 FFT、全速门禁，而不是降低速率或恢复 decimation。

1. 本地生产检查：
   ```bash
   python3 -m py_compile python/packet.py python/t510_fengine.py scripts/pynq_stage27h_time_spec_fft_fullrate.py scripts/host_stage27h_rust_rx_validate.py
   python3 -m json.tool notebooks/15_stage27h_time_spec_fft_fullrate_control.ipynb >/dev/null
   cargo test --manifest-path rust/t510_time_rx/Cargo.toml
   cargo build --release --manifest-path rust/t510_time_rx/Cargo.toml
   bash -n scripts/pynq_publish_stage27h.sh scripts/pynq_publish_jupyter_instrument.sh scripts/host_stage27h_rx_fanout_tune.sh
   ./scripts/run_xsim_batch.sh tb_pfb_channelizer tb_spec_udp_cmac512 tb_time_udp_cmac512 tb_t510_fengine_top_smoke tb_tx_route_selector tb_feng_ctrl_axi
   ```
2. Vivado 生产比特流复现：
   - 运行 `scripts/stage27h_time_spec_100mhz_fft_fullrate_bit_export_batch.tcl`，重新跑 `synth_1 -> impl_1 -> write_bitstream/export`。
   - 最终要求布线完成、时序满足、0 errors；CMAC evaluation/license critical warning 按用户要求记录但不阻塞。

3. 发布到 PYNQ：
   ```bash
   PYNQ_TARGET=xilinx@192.168.100.117 scripts/pynq_publish_stage27h.sh
   ```

4. 板端生产矩阵复现：
   ```bash
   ssh xilinx@192.168.100.117
   cd /home/xilinx/t510_fengine_bringup
   source /etc/profile.d/xrt_setup.sh
   printf "%s\n" "xilinx" | sudo -S -p "" -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_stage27h_time_spec_fft_fullrate.py --matrix converge
   ```

5. 主机接收与 Web/Jupyter：
   ```bash
   sudo scripts/host_stage27h_rx_fanout_tune.sh ens2f0np0
   sudo rust/t510_time_rx/target/release/t510_time_rx --backend fanout --worker-count 24 --pin-workers auto --interface ens2f0np0 --dst-port-base 4300 --src-port-base 4000 --flow-count 24 --time-flow-count 8 --spec-flow-count 16 --spec-layout stage27h --fanout-mode port --fanout-group 0x279 --web 0.0.0.0:8089 --initial-bandwidth-mhz 100 --ring-mb 2048 --block-mb 4 --batch-size 8192
   scripts/host_stage27h_rust_rx_validate.py --seconds 10
   ```
   Jupyter 生产入口只推荐 `t510_fengine/notebooks/15_stage27h_time_spec_fft_fullrate_control.ipynb`，用于控制 TIME/SPEC、接收端 IP/端口/MAC、带宽/中心频率、8 路 DAC-ADC 环回、DAC 频率/相位，并查看 RF 还原波形和 FFT-only 生产频谱。

6. 下一步建议：
   - 先复现 27h 60 秒 PYNQ 板端门禁和主机 24 流门禁，并把 board/host JSON 以时间戳归档。
   - 做 10 分钟、1 小时、过夜三档 `TIME_SPEC 100MHz` 全速 soak。
   - 在 FFT-only 速率闭合后，再决定是否恢复科学级 PFB 幅相/功率标定和下游交换机/DGX/X-engine 接收验证。

## AI 接续提示

- 不要从 `reports/arch/*.html` 推断执行进度；执行状态以 `reports/stages/*.md` 为准。
- 板端 sudo 密码约定为与登录用户名相同；仍通过 stdin 传入，不要把实际密码硬编码进脚本或 notebook。
- 板上 Stage 23 `core_version` 应为 `0x00010012`；如果仍读到 `0x00010011`，说明还在 Stage 22 overlay，不能跑 Stage 23 live science 验收。
- 无 QSFP 时 `UDP_DRY_RUN=1` 且 `QSFP_LINK_UP=0` 是预期状态，不代表失败。
- Stage 12 稳定 Jupyter 入口仍是 `13_astronomer_rf_observation_console.ipynb`；Stage 9 的 `12_rf_instrument_console_v2.ipynb` 和 Stage 8 的 `11_dac_adc_coherent_scope_spectrum.ipynb` 只作为验收记录保留。
- Stage 10 主界面只暴露天文学家视角：测试单音 RF 频率、观测中心、观测带宽、时间窗口、幅度、相位和实时速率；不要把 baseband/NCO 重新做成主控件。
- Stage 11 主示波器是 RF 等效波形；`baseband_scope` 只作为高级工程调试图。不要再用 baseband offset 驱动主示波器周期数。
- RF scope cycles 应等于 `signal_mhz * time_window_us`：例如 `60/100/130 MHz` 在 `0.25 us` 下为 `15/25/32.5`。
- Stage 12 主频谱和主幅度是 smoothed observation view；raw 单帧 spectrum/peak/RMS 保留在高级诊断中，不要把 smoothed waterfall 当作科学级功率标定。
- Stage 12 bad-frame gate 会拒收 clipped、低 SNR、peak 频率/幅度突跳和 RMS 突跳帧；被拒收帧不更新主频谱和 waterfall history。
- Stage 12 Jupyter 性能默认值 v2：`快速模式` 开启、`刷新基带图` 关闭、频谱显示 `384` 点、RF scope `512` 点、waterfall `192` 频点、`30` 帧历史、waterfall `0.8 Hz`、状态/速率读取 `1 Hz`、每帧至少 `30 ms` UI 让步；不要在 live loop 里每帧推送完整 `4096 x 60` waterfall。
- Stage 12 后端性能门禁：`--stage12-performance-check` 已测得板端 capture+analysis+display-reduce 平均 `10.35 ms/帧`，约 `96.65 FPS`；若浏览器仍卡顿，优先查 Plotly/Jupyter comm，而不是 RFDC preview/FFT。
- Stage 13 后必须区分四个相位：`configured_phase_deg`、`measured_fft_phase_deg`、`sample0_coherent_phase_deg`、`display_rf_phase_deg`。主 RF scope 的 `display_rf_phase_deg` 稳定不代表 raw ADC measured phase 稳定。
- Stage 13 结论：synthetic、frozen frame、readback consistency 稳定；repeated preview raw phase/amplitude 大幅漂移。下一步应查 RFDC/RTL/sample0/preview trigger/大幅事件锁存，而不是继续调 notebook 主图。
- Stage 13 notebook 13 高级面板新增 `Freeze current frame` 和 `Phase Provenance`。冻结帧若稳定、live preview 若抖动，应按硬件采样链路问题推进。
- Stage 14 后 notebook 13 新增 `Sample0-aligned measured RF scope`。它不是配置锁定参考，而是用 raw IQ、`sample0`、采样率和配置 expected baseband frequency 计算的实测 RF 等效波形。
- Stage 14 相位漂移主字段是 `phase_error_deg`；辅助字段包括 `expected_tone_measured_phase_deg`、`sample0_aligned_phase_deg`、`sample0_mod_phase_deg`、`fit_residual_fraction`、`snr_db`、`max_abs_code`、`rms_code`。
- Stage 14 时间语义：每帧只有一个 `sample0`，第 `n` 个样点的隐含时间是 `(sample0+n)/sample_rate_hz`；不是每个 ADC 样点都有独立 timestamp。
- Stage 14 结论：synthetic fixed/phase step/injected drift 和 frozen hardware frame 稳定；repeated live preview 的 sample0-aligned `phase_error` p-p `359.56 deg`。下一步应进入 RTL/RFDC/sample0 latch/preview trigger/大幅事件硬件审计。
- Stage 15 结论：`internal_dds`、`sample_index_ramp`、preview double-read、event buffer double-read 和 DAC phase commit 均 PASS；RFDC source 仍有约整周相位漂移，当前分类是 `rfdc_or_analog_or_clock_path_suspect`。
- Stage 15 internal DDS 在 Python `I+jQ` 约定下是 `-15.36 MHz` 对照源；用 `+15.36 MHz` 会误报 internal DDS 失败。
- Stage 16 结论：RFDC-derived packet `sample0` 和 TX payload witness 已闭合；TIME/SPEC witness 均可抓取，header `sample0` 非零且单调。
- Stage 16 的 `result=PASS` 只表示证据链通过；`data_quality_gate=BLOCK_QSFP_LIVE_DATA_QUALITY` 表示 QSFP live science 数据质量仍禁止放行。
- Stage 16 观测到 preview 和 payload phase residual 都大范围抖动，且 correlation 低；下一步要让 preview 和 payload 对准同一 RFDC 时间窗口，再查 RFDC/clock/adapter 与 packetizer/witness reset。
- Stage 16 每个 condition 前需要 overlay reload 才能稳定抓 TIME/SPEC witness；后续要调查 mode switch、route/arbiter、packetizer reset 或 witness clear/arm 的状态污染。
- Stage 17 本地修复 witness data-clear/arm 语义，并新增 SYSREF-locked observation init；板端若仍需要 per-condition overlay reload，应分类为 `MODE_SWITCH_STATE_CONTAMINATION`。
- Stage 17 严格数据质量门禁是 preview 与 TIME/SPEC payload phase p-p `<=3 deg`、amplitude p-p `<=5%`、无 clipping/large-event。不要为了推进 QSFP live science data 而放宽阈值。
- Stage 19 结论：CH0 DAC0-to-ADC0 dry-run/witness 相位漂移主因已闭合。SPEC off-center payload 旧失败来自 packetizer payload discontinuity，而不是 DAC single-tone 产生、Jupyter、Python phase math 或 preview BRAM。后续不要在没有新证据时把该问题回退到这些方向。
- Stage 19 的 `READY_FOR_QSFP_SCIENCE_DATA` 只覆盖 CH0 dry-run/witness 数据质量门禁；QSFP live receive、switch/ARP/VLAN/PTP、downstream X-engine 和科学级 PFB/FFT 仍需单独验收。
- Stage 19 Jupyter 入口已更新为 `CORE_VERSION=0x0001000E`，并在第一格同时 reload `python.t510_clock` 和 `python.t510_fengine`。如果网页 Init 报 `LMK TCXO clock did not lock` 且结果里 `attempts=3`，这是旧 kernel 缓存了 Stage 18 时的短 retry 模块；重启 kernel 或重跑第一格后再 Init。当前 Stage 19 LMK lock 可能需要十几次 0.5s poll，不能退回 3 次 retry。
- Stage 19b 后必须区分 DAC 测试信号和 ADC 期望输入信号：外源模式使用 `input_source_mode=external_adc_tone` 和 `expected_signal_hz/input_signal_hz`，DAC 默认关闭。外部源未与 LMK/10 MHz 同源锁定时，相位线性漂移不是失败；raw preview/sample0/FFT/SNR 停止更新或 stabilizer 拒收未暴露才是失败。外源正好落在观测中心/DC 时使用 `EXTERNAL_TONE_CENTER_DC_AMBIGUOUS` 分类，优先改成 off-center 观测或同源锁定，不直接判 ADC 输入路径故障。
- Stage 20 以后 Jupyter 和 LED 同步语义固定为：LED0=RF/LMK 派生数据时钟链 ready，LED1=PPS edge blink，LED2=PPS recent，LED3=同步错误。`read_external_sync_diagnostics()` 是软件侧对应入口。
- Stage 20 的 8 路相位滑条只控制 DAC test tone 的每通道 phase；外部 ADC 单音模式下 DAC 默认关闭，不能用该模式证明 8 路 DAC-loopback 相位。
- Stage 21 只能在当前 bit 上做 QSFP 预检分类。只要 board top 仍无真实 CMAC/GT/QSFP data path，`CURRENT_BIT_DRY_RUN_NO_CMAC_GT_DATAPATH` 就是预期阻塞，不能声明 live science data 通过。
- Stage 22 后 Jupyter 里凡是叫“波形”的图都必须来自真实采集数据。主波形只画 RFDC preview 的 I/Q/|IQ|；RFDC Raw Witness 面板画 `0x0e800..0x0f7ff` buffer 解码出的真实 sub-sample。不要再把配置频率/相位、expected reference、拟合 cos 伪装成波形。
- Stage 23 的 `RF等效(I/Q回算)` 可以作为波形视图，但必须标注 `derived_from_real_iq=True`、`raw_rf=False`；它是用真实 RFDC preview I/Q 按观测中心回算的 RF 等效波形，不是 RFDC 内部 pre-DDC 原始 RF。
- Stage 23 后 RFDC science bus 截断问题已修：`RFDC_SCIENCE_BUS_TRUNCATED_TO_LOW16` 对新 bit 应为 0。仍不得声明 QSFP live science 通过；只要 `SPEC_SCIENCE_BLOCKED_PFB_SCAFFOLD`、`CMAC_LIVE_BLOCKED_NO_GT_DATAPATH` 或 `WIDE_512B_TX_PATH_NOT_IMPLEMENTED` 任一存在，live science 必须 BLOCK。
- Stage 24b 结论：`0x00010013` bit 已上板，但 QSFP0/CMAC heartbeat 没通过。板端 `module/refclk/GT/reset/tx_ready` 都好，失败点是 `local_fault=1`、`link_up=0`、主机 `ens2f0np0 NO-CARRIER`、accepted counters 为 0。当前线缆为 Mellanox `MCP1600-E002` 2m passive copper DAC，声明支持 `100GBASE-CR4`；CMAC IP 配置无 RS-FEC、无 Auto-Neg/Link-Training。下一步优先做 CMAC AN/LT/FEC 匹配变体，不要跑 pcap 假装通过。
- Stage 24c 结论：`0x00010014` AN/LT 变体 A' 已 route clean/timing pass，但 `write_bitstream` 被 `cmac_an_lt@2020.05 design_linking` 拦截。当前不要同步 `overlay/t510_fengine.bit` 到板上当作 24c，也不要继续跑 host pcap。拿到 bitstream-capable `cmac_an_lt` license 后，必须 reset/regenerate CMAC IP output products，重跑 OOC、top synth/impl/bitstream/export，再上板。
- Stage 24d 结论：`0x0001001A` no-AN/no-LT + RS-FEC CMAC 配置已通过 QSFP0 heartbeat 和主机 `ens2f0np0` pcap。Stage 24d 只证明 CMAC/QSFP/heartbeat 数据面，不证明 TIME/SPEC science。
- Stage 25 当前结论：`0x0001001B` 低速 `20MHz TIME_ONLY` live TIME CMAC/pcap 闭环已通过，板端为 `STAGE25_TIME_LOW_RATE_LIVE_PASS`，主机为 `HOST_PCAP_STAGE25_TIME_PASS`。这只证明低速 TIME live pcap，不证明 SPEC/PFB、20/100/200MHz full science、交换机/DGX/X-engine 或长稳。
- Stage 26b/27 当前结论：`0x0001001D` 已完成 PL 侧 `time_udp_cmac512` 输出寄存化和 `time_axis512_ddr_ring` 缓冲雏形，本地 XSim/Python/Rust 回归通过；Vivado route clean、timing met、bitstream/export 完成，PYNQ 文件同步完成。`txoutclk_out[0]` 最薄 setup slack 为 `0.000 ns`，后续优化仍需关注 CMAC token checksum 和 DDR address 路径。DDR disabled direct path 的 `20/100/200MHz TIME_ONLY` 板端 counters/gates 为 `STAGE26_TIME_FULL_RATE_PASS`；重启后已修复 `rfdc_active_mask` 与 TIME route mask 不一致导致的 route miss，并增加 TX gate 短窗口采样避免高速切换瞬态误报。Rust/HTML smoke 已证明动态 selected/detected bandwidth 和 8 路 waveform 显示语义，但高档位无损接收仍未过。DDR enabled path 触发板端管理网失联，分类 `BLOCK_STAGE26B27_DDR_ENABLE_BOARD_UNREACHABLE`。下一步先优化 host receiver/pcap 无损验收；DDR 需先修 address map / AXI timeout / DDR carveout 并做隔离 smoke，再接回 TIME path。
- Stage 10 已知未标定项：200 MHz 单音在 180/200/220 MHz 观测中心下 RF peak residual 约 `0.55-0.65 MHz`；后续应做 RF observation calibration，不要误判为 Jupyter 语义错误。
- Stage 9 live loop 只做 fast preview capture、FFT、Plotly trace update 和轻量 status read；硬件重配必须通过 Apply RF/init 触发。
- ADC BW 在 Stage 9 是显示/分析窗口，不是 RFDC decimation 动态切换。
- Stage 6 已闭合 channel-window dry-run 合约；后续不要把它误判为科学级 PFB 幅相标定完成。
- Stage 7 已闭合 Ethernet/IP/UDP frame preflight 和静态 route 选择；后续不要把 `tx_frame_sent_count` 误判为真实 QSFP 发包。
- 频域 route table 支持 8 个静态频点段；Stage 7a 应用 `chan0=0` 和 `chan0=2048` 抓包验证 endpoint0/endpoint1。
- 时域 route table 支持 `input_mask -> endpoint_id`，但 payload lane repack 未完成，不能声明时域 payload 已按 mask 裁剪。
- CH0 是当前唯一 physical loopback verified 通道；CH1..CH7 只能声明 digital/control preview 可读。
- Stage 8 已闭合 20 MHz coherent smoke；raw FFT bin 可能是 `19.92 MHz`，应以插值 peak 或配置频率作为频率判据。
