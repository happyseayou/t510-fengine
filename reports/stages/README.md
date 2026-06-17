# T510 F-engine Stage Reports

本目录记录落地阶段状态。`reports/arch/` 是架构输入资料；本目录是执行状态和交接入口。

## 最新状态

- 最新推进到：Stage 19 Phase Drift Root-Cause Closure 已闭合 CH0 DAC0-to-ADC0 dry-run/witness 相位漂移主因。`CORE_VERSION=0x0001000E`，RFDC AXIS clock metadata 精确为 `61.440 MHz / 245.760 MHz`，SPEC packetizer 已改为 BRAM capture/emission，避免对非 backpressure ADC stream 造成 payload discontinuity。Stage 18 LMK/RFDC MTS、Stage 17 RFDC SYSREF Coherence Lock、Stage 16 RFDC-to-UDP Coherence Witness、Stage 15 hardware phase audit、Stage 14 sample0-aligned measured preview、Stage 13 phase provenance、Stage 12 stable spectrum/waterfall、Stage 11 RF-accurate scope、Stage 10 astronomer console、Stage 7 UDP TX preflight 和 Stage 6 PFB channel-window contract 保持可用。
- 最新 overlay：Stage 19 `overlay/t510_fengine.bit` SHA256 `a7dc97e186d1981fcd07d7abfc3f33ffbaf04381e9771e5aaa325a5e907e714d`；`overlay/t510_fengine.hwh` SHA256 `345fdf3aea634a323dc3fd8f9bdde872c04a92d161ba08404782fd4260e39e4f`。
- Vivado 状态：Stage 19 implementation/bitstream 通过；implementation `READY`，`0 critical warning`，`WNS=+1.267 ns`，`WHS=+0.010 ns`，失败端点 `0/226852`。
- 板端状态：Stage 19 overlay 已同步并读回 `CORE_VERSION=0x0001000E`；LMK `pll1_lock=1/pll2_lock=1`；RFDC MTS tile0-only 和 full-mask `0xf/0xf` probe 均 PASS。完整 240-frame strict matrix 覆盖 `constant_phasor/single_tone`、`119.2/130.24/130.0 MHz`、`TIME/SPEC` 共 12 条件，全部 PASS，最大 preview phase p-p `0.281892 deg`、payload phase p-p `0.474061 deg`、preview amplitude p-p `1.289775%`、payload amplitude p-p `2.032418%`、DAC pre-RFDC phase p-p `0.222517 deg`、DAC amplitude p-p `0.123542%`。CH0 dry-run/witness data-quality gate 为 `READY_FOR_QSFP_SCIENCE_DATA`；QSFP live receive/science path 仍未声明完成。管理口为 `192.168.100.117`，`eth0` 当前 MAC 为稳定值 `02:51:10:23:dc:28`。
- Jupyter 入口：打开 `http://192.168.100.117/lab` 或 `http://192.168.100.117:9090/lab`，进入 `t510_fengine/notebooks/13_astronomer_rf_observation_console.ipynb`。
- 尚未完成：CMAC/QSFP 真实发包、交换机/接收节点 pcap、DGX/X-engine 收包、ARP/VLAN/PTP、正式科学级 4096-channel 4-tap PFB 幅相标定、长时间 FIFO/backpressure 压力测试、CH1..CH7 模拟闭环、`50-350 MHz` 全带 RF 频率/幅相/功率标定、浏览器端 long-run soak test。
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

## 推荐接续入口

1. 先读本文件和最新阶段报告的“阶段衔接说明”。
2. 本地先跑：
   ```bash
   python3 -m py_compile python/packet.py python/t510_fengine.py scripts/check_t510_packet_header.py scripts/pynq_spec_dry_run_check.py scripts/pynq_jupyter_instrument_smoke.py scripts/pynq_8lane_instrument_check.py scripts/pynq_dac_adc_coherent_check.py scripts/pynq_rf_instrument_v2_check.py
   python3 -m py_compile scripts/pynq_pfb_channel_window_check.py scripts/check_t510_udp_frame.py scripts/pynq_qsfp_udp_preflight_check.py scripts/pynq_astronomer_rf_console_check.py scripts/pynq_phase_provenance_audit.py scripts/pynq_hardware_phase_audit.py scripts/pynq_rfdc_udp_coherence_audit.py scripts/pynq_rfdc_sysref_coherence_lock_check.py scripts/pynq_lmk_rfdc_mts_recovery_check.py
   python3 -m json.tool notebooks/09_single_board_virtual_instrument.ipynb >/dev/null
   python3 -m json.tool notebooks/10_8lane_realtime_virtual_instrument.ipynb >/dev/null
   python3 -m json.tool notebooks/11_dac_adc_coherent_scope_spectrum.ipynb >/dev/null
   python3 -m json.tool notebooks/12_rf_instrument_console_v2.ipynb >/dev/null
   python3 -m json.tool notebooks/13_astronomer_rf_observation_console.ipynb >/dev/null
   ./scripts/run_xsim_batch.sh tb_t510_dac_loopback_source tb_preview_event_capture tb_rfdc_fullrate_preview tb_feng_ctrl_axi tb_tx_payload_witness_capture tb_time_packetizer tb_spectral_packetizer tb_t510_fengine_top_smoke
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
- 板上 Stage 19 `core_version` 应为 `0x0001000E`；如果读到旧版本，先核对 overlay SHA256、同步路径和 notebook 是否加载了 Stage 19 bitfile。
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
- Stage 10 已知未标定项：200 MHz 单音在 180/200/220 MHz 观测中心下 RF peak residual 约 `0.55-0.65 MHz`；后续应做 RF observation calibration，不要误判为 Jupyter 语义错误。
- Stage 9 live loop 只做 fast preview capture、FFT、Plotly trace update 和轻量 status read；硬件重配必须通过 Apply RF/init 触发。
- ADC BW 在 Stage 9 是显示/分析窗口，不是 RFDC decimation 动态切换。
- Stage 6 已闭合 channel-window dry-run 合约；后续不要把它误判为科学级 PFB 幅相标定完成。
- Stage 7 已闭合 Ethernet/IP/UDP frame preflight 和静态 route 选择；后续不要把 `tx_frame_sent_count` 误判为真实 QSFP 发包。
- 频域 route table 支持 8 个静态频点段；Stage 7a 应用 `chan0=0` 和 `chan0=2048` 抓包验证 endpoint0/endpoint1。
- 时域 route table 支持 `input_mask -> endpoint_id`，但 payload lane repack 未完成，不能声明时域 payload 已按 mask 裁剪。
- CH0 是当前唯一 physical loopback verified 通道；CH1..CH7 只能声明 digital/control preview 可读。
- Stage 8 已闭合 20 MHz coherent smoke；raw FFT bin 可能是 `19.92 MHz`，应以插值 peak 或配置频率作为频率判据。
