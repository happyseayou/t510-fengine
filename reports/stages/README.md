# T510 F-engine Stage Reports

本目录记录落地阶段状态。`reports/arch/` 是架构输入资料；本目录是执行状态和交接入口。

## 最新状态

- 最新推进到：Stage 24c passive DAC / 100G CR4 AN-LT 变体 A' 已完成 RTL/IP 包装、顶层综合和实现，但当前状态为 `BLOCK_STAGE24C_CMAC_AN_LT_BITGEN_LICENSE`。不能声明 QSFP heartbeat pcap 通过，更不能声明 TIME/SPEC science 通过。
- 最新 overlay：仓库内 `overlay/t510_fengine.bit` 仍是 Stage 24b 旧 `0x00010013` bit，SHA256 为 `c5027c4def02990c104b1e9a919297a277cea89bcb50d95d1723c190613dbc02`。不要把它当作 Stage 24c `0x00010014` AN/LT bit 上板。
- Vivado 状态：Stage 24c `0x00010014` 变体 A' synthesis 为 `0 errors, 0 critical warnings`，implementation 已到 `route_design Complete`，route 后时序满足（`WNS=+0.426 ns`、`WHS=+0.011 ns`、failed endpoints `0/132073`），failed/unrouted/partially routed nets 均为 0。`write_bitstream` 失败于 `Common 17-69` encrypted cellview license gate。
- License 状态：`t510_cmac_usplus_0` 当前 `USED_LICENSE_KEYS` 包含 `cmac_usplus@2020.05 design_linking` 和 `cmac_an_lt@2020.05 design_linking`；本机 license 文件只找到 `cmac_usplus` bought license，没有找到 `cmac_an_lt` bitstream-capable license。安装新 license 后必须 reset/regenerate CMAC IP output products，重跑 OOC、top synth/impl/bitstream，不能只重跑 `write_bitstream`。
- 板端历史状态：Stage 24b `CORE_VERSION=0x00010013` 已确认；QSFP module present、GT refclk、GT lock、GT TX/RX reset done、CMAC reset done、CMAC TX ready 均为 1，但 `local_fault=1`、`qsfp_link_up=0`、accepted packet/byte counters 为 0。主机 `ens2f0np0` 在 Auto / RS / BaseR / forced 100G no-AN no-FEC 下均 `NO-CARRIER`；相邻口 `ens2f1np1` 只读检查为 `No cable`。线缆 EEPROM 显示为 Mellanox `MCP1600-E002` 2m passive copper DAC，声明支持 `100GBASE-CR4`。当前仍按“线缆可兼容，但 passive DAC 需要 AN/LT/FEC 策略匹配”处理，不先判线缆坏。
- Jupyter 入口：打开 `http://192.168.100.117/lab` 或 `http://192.168.100.117:9090/lab`，进入 `t510_fengine/notebooks/13_astronomer_rf_observation_console.ipynb`。
- 尚未完成：Stage 19b 的 `ADC0 50Ω 端接 + DAC0 on` 泄漏矩阵、`cmac_an_lt` bitgen license、Stage 24c `0x00010014` AN/LT bitstream、QSFP heartbeat pcap、TIME/SPEC live science、交换机/接收节点 pcap、DGX/X-engine 收包、ARP/VLAN/PTP、正式科学级 4096-channel 4-tap PFB 幅相标定、长时间 FIFO/backpressure 压力测试、`50-350 MHz` 全带 RF 频率/幅相/功率标定、浏览器端 long-run soak test。
- PYNQ 目标：`xilinx@192.168.100.117`。
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

## 推荐接续入口

1. 先读本文件和最新阶段报告的“阶段衔接说明”。
2. 本地先跑：
   ```bash
   python3 -m py_compile python/packet.py python/t510_fengine.py scripts/check_t510_packet_header.py scripts/pynq_spec_dry_run_check.py scripts/pynq_jupyter_instrument_smoke.py scripts/pynq_8lane_instrument_check.py scripts/pynq_dac_adc_coherent_check.py scripts/pynq_rf_instrument_v2_check.py
   python3 -m py_compile scripts/pynq_pfb_channel_window_check.py scripts/check_t510_udp_frame.py scripts/pynq_qsfp_udp_preflight_check.py scripts/pynq_astronomer_rf_console_check.py scripts/pynq_phase_provenance_audit.py scripts/pynq_hardware_phase_audit.py scripts/pynq_rfdc_udp_coherence_audit.py scripts/pynq_rfdc_sysref_coherence_lock_check.py scripts/pynq_lmk_rfdc_mts_recovery_check.py scripts/pynq_external_adc_tone_decoupling_check.py scripts/pynq_stage20_sync_diagnostic.py scripts/pynq_stage20_8lane_external_sync_check.py scripts/pynq_stage21_qsfp_link_pcap_check.py scripts/pynq_stage23_qsfp_science_check.py
   python3 -m json.tool notebooks/09_single_board_virtual_instrument.ipynb >/dev/null
   python3 -m json.tool notebooks/10_8lane_realtime_virtual_instrument.ipynb >/dev/null
   python3 -m json.tool notebooks/11_dac_adc_coherent_scope_spectrum.ipynb >/dev/null
   python3 -m json.tool notebooks/12_rf_instrument_console_v2.ipynb >/dev/null
   python3 -m json.tool notebooks/13_astronomer_rf_observation_console.ipynb >/dev/null
   ./scripts/run_xsim_batch.sh tb_t510_dac_loopback_source tb_dac_tx_witness_capture tb_preview_event_capture tb_rfdc_fullrate_preview tb_science_rate_selector tb_rfdc_adc_axis_adapter tb_feng_ctrl_axi tb_axi4_to_axil_bridge tb_tx_payload_witness_capture tb_time_packetizer tb_spectral_packetizer tb_t510_fengine_board_top tb_t510_fengine_top_smoke
   ```
3. 板端复测先用现有 overlay：
   ```bash
   cd /home/xilinx/t510_fengine_bringup
   source /etc/profile.d/xrt_setup.sh
   sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_adc0_dac0_loopback_check.py --mask 0x1 --seconds 0.5
   sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_fengine_debug_capture.py --mask 0x1 --timeout 2.0
   sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_spec_dry_run_check.py --mask 0x1 --seconds 0.5 --timeout 2.0
   sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_jupyter_instrument_smoke.py --mask 0x1 --timeout 2.0
   sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_8lane_instrument_check.py --channels 8 --samples 512 --timeout 2.0
   sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_pfb_channel_window_check.py --chan0 0 --chan-count 64 --time-count 4 --timeout 2.0
   sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_qsfp_udp_preflight_check.py --force-dry-run --timeout 2.0
   sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_dac_adc_coherent_check.py --center-mhz 1500 --bw-mhz 100 --tone-mhz 20 --samples 1024 --timeout 2.0
   sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_rf_instrument_v2_check.py --center-mhz 1500 --bw-mhz 100 --tone-start-mhz 10 --tone-stop-mhz 30 --phase-step-deg 45 --samples 512 --timeout 2.0
   sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_astronomer_rf_console_check.py --signal-mhz 200 --center-mhz 180 --bw-mhz 100 --phase-step-deg 45 --time-window-us 0.25 --timeout 2.0
   sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_astronomer_rf_console_check.py --stage11-scope-check --center-mhz 100 --signals-mhz 60,100,130 --bw-mhz 100 --time-window-us 0.25 --timeout 2.0
   sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_astronomer_rf_console_check.py --stage12-stability-check --signal-mhz 100 --center-mhz 100 --bw-mhz 100 --frames 60 --timeout 2.0
   sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_phase_provenance_audit.py --mode readback_consistency --frames 100 --samples 512 --timeout 2.0
   sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_phase_provenance_audit.py --mode repeated_preview --seconds 180 --signal-mhz 100 --center-mhz 100 --bw-mhz 100 --samples 512 --timeout 2.0
   sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_phase_provenance_audit.py --mode sample0_aligned_preview --signal-mhz 100 --center-mhz 100 --bw-mhz 100 --samples 512 --seconds 60 --timeout 2.0
   sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_hardware_phase_audit.py --signal-mhz 100 --center-mhz 100 --bw-mhz 100 --samples 512 --seconds 60 --event-threshold 28000 --timeout 2.0
   sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_rfdc_udp_coherence_audit.py --center-mhz 100 --signals-mhz 119.2,130.24,130,100 --modes spec,time --samples 512 --frames 120 --timeout 2.0
   sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_lmk_rfdc_mts_recovery_check.py --dump-lmk --dump-rfdc-api --timeout 2.0
   sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_lmk_rfdc_mts_recovery_check.py --probe-mts --adc-tiles 0x1 --dac-tiles 0x1 --timeout 2.0
   sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_stage19_phase_root_cause_check.py --signals-mhz 119.2,130.24,130.0 --dac-source-modes constant_phasor,single_tone --modes time,spec --frames 240 --mts-adc-tiles 0x1 --mts-dac-tiles 0x1 --strict-phase-pp-deg 3 --strict-amplitude-pp-percent 5 --dac-strict-phase-pp-deg 0.5 --dac-strict-amplitude-pp-percent 1.0 --timeout 2.0
   sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_stage20_sync_diagnostic.py --configure-external --timeout 3.0 --output reports/stage20_external_10mhz_pps_sync.json
   sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_stage20_8lane_external_sync_check.py --center-mhz 200 --signal-mhz 200 --bw-mhz 100 --phases-deg 0,45,90,135,180,-135,-90,-45 --frames 240 --samples 512 --timeout 3.0 --output reports/stage20_8lane_external_sync_200mhz.json
   sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_stage21_qsfp_link_pcap_check.py --seconds 2.0 --output reports/stage21_qsfp_preflight.json
   ```
4. 重新发布 Jupyter instrument：
   ```bash
   PYNQ_TARGET=xilinx@192.168.100.117 \
   PYNQ_JUPYTER_DIR=/home/xilinx/jupyter_notebooks/t510_fengine \
   scripts/pynq_publish_jupyter_instrument.sh
   ```
5. 管理网 MAC 固定建议在板端执行一次，默认只写 ifupdown 配置、不打断当前 SSH/Jupyter：
   ```bash
   cd /home/xilinx/t510_fengine_bringup
   sudo scripts/pynq_fix_management_mac.sh
   ```
   当前板端已应用该配置，`eth0` live MAC 为 `02:51:10:23:dc:28`，DHCP 地址为 `192.168.100.117`。

## AI 接续提示

- 不要从 `reports/arch/*.html` 推断执行进度；执行状态以 `reports/stages/*.md` 为准。
- 不要把 SSH 密码写入报告、脚本或 notebook。
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
- Stage 10 已知未标定项：200 MHz 单音在 180/200/220 MHz 观测中心下 RF peak residual 约 `0.55-0.65 MHz`；后续应做 RF observation calibration，不要误判为 Jupyter 语义错误。
- Stage 9 live loop 只做 fast preview capture、FFT、Plotly trace update 和轻量 status read；硬件重配必须通过 Apply RF/init 触发。
- ADC BW 在 Stage 9 是显示/分析窗口，不是 RFDC decimation 动态切换。
- Stage 6 已闭合 channel-window dry-run 合约；后续不要把它误判为科学级 PFB 幅相标定完成。
- Stage 7 已闭合 Ethernet/IP/UDP frame preflight 和静态 route 选择；后续不要把 `tx_frame_sent_count` 误判为真实 QSFP 发包。
- 频域 route table 支持 8 个静态频点段；Stage 7a 应用 `chan0=0` 和 `chan0=2048` 抓包验证 endpoint0/endpoint1。
- 时域 route table 支持 `input_mask -> endpoint_id`，但 payload lane repack 未完成，不能声明时域 payload 已按 mask 裁剪。
- CH0 是当前唯一 physical loopback verified 通道；CH1..CH7 只能声明 digital/control preview 可读。
- Stage 8 已闭合 20 MHz coherent smoke；raw FFT bin 可能是 `19.92 MHz`，应以插值 peak 或配置频率作为频率判据。
