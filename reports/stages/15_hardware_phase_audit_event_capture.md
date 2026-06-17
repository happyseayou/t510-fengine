# Stage 15 Hardware Phase Audit + Event Capture

## 阶段目标

在不移动 DAC0->ADC0 物理线缆的前提下，给相位抖动和大幅信号异常加硬件证据链。Stage 15 的目标不是消除异常，而是区分问题来自 Jupyter/PYNQ 显示链路、preview/sample0 latch/CDC、RFDC AXIS adapter、RFDC/模拟/时钟链路，还是 DAC phase commit。

## 输入基线

- Stage 14 已证明 synthetic/frozen frame/readback consistency 稳定，但 live repeated preview 的 sample0-aligned `phase_error` p-p 约 `359.56 deg`，且出现 `max_abs_code=32554` 级别大幅事件。
- 当前顶层仍不接 QSFP live；`UDP_DRY_RUN=1`、`QSFP_LINK_UP=0` 在无 QSFP 条件下是预期状态。
- PYNQ 目标：`xilinx@192.168.100.117`。报告不记录明文密码。

## 完成内容

- RTL:
  - `multi_preview_observer` 增加 preview audit event chain：capture request、first write、done 的 count/sample0/latency/capture beats/valid gap/sample0 step error。
  - 新增 preview source mux：`rfdc`、`internal_dds`、`sample_index_ramp`。默认仍是 `rfdc`，internal/ramp 只用于 preview 审计。
  - 新增 large-event capture：CH0 raw IQ `max_abs_code >= threshold` 时锁存 event metadata，并保存 256-word raw IQ event buffer。
  - `t510_dac_loopback_source` 增加 DAC clock-domain audit readback：epoch seen、CH0 phase accumulator、phase step、phase0、mode。
  - `CORE_VERSION` bump 到 `0x00010008`。
- Register/API:
  - 新增 `0x0730..0x078c` preview audit/status/event metadata。
  - 新增 `0x0a800..0x0abff` preview event raw IQ buffer。
  - 新增 `0x06e0..0x06f0` DAC audit readback。
  - `python/t510_fengine.py` 增加 `configure_preview_audit()`、`read_preview_audit_status()`、`capture_preview_event()`、`read_dac_audit_status()`。
- Board/Jupyter entry:
  - 新增 `scripts/pynq_hardware_phase_audit.py`，默认一次跑 internal/ramp、RFDC source、readback consistency、large-event capture、DAC phase commit。
  - notebook 13 高级面板新增 `Hardware Audit`：preview source selector、large-event trigger/status、event waveform、DAC audit readback。

## 验证证据

本地已通过：

```bash
python3 -m py_compile python/t510_fengine.py scripts/pynq_hardware_phase_audit.py
python3 -m json.tool notebooks/13_astronomer_rf_observation_console.ipynb >/dev/null
./scripts/run_xsim_batch.sh tb_t510_dac_loopback_source tb_preview_event_capture tb_feng_ctrl_axi tb_rfdc_fullrate_preview tb_t510_fengine_top_smoke
```

XSim 结果：`tb_t510_dac_loopback_source`、`tb_preview_event_capture`、`tb_feng_ctrl_axi`、`tb_rfdc_fullrate_preview`、`tb_t510_fengine_top_smoke` 全部 PASS。

Vivado/overlay：

- Synthesis：0 error，0 critical warning。
- Implementation：READY，post-route `WNS=+2.110 ns`，`WHS=+0.010 ns`，失败端点 `0/91387`，0 critical warning。
- Bitstream：`overlay/t510_fengine.bit`，SHA256 `8125eae67542b8165ca97c9a1d19ac6df840fb2bf9cda0756d7469b19f9f2e43`。

板端已跑：

```bash
cd /home/xilinx/t510_fengine_bringup
source /etc/profile.d/xrt_setup.sh
sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_hardware_phase_audit.py --signal-mhz 100 --center-mhz 100 --bw-mhz 100 --samples 512 --seconds 60 --event-threshold 28000 --timeout 2.0
```

结果摘要：

- `CORE_VERSION=0x00010008`，脚本 `result=PASS`，说明 Stage 15 证据链执行完成；这不代表 RFDC/模拟相位稳定。
- `classification=rfdc_or_analog_or_clock_path_suspect`。
- `sample_index_ramp=PASS`：0 mismatch，`valid_gap_count=0`，`sample0_error_count=0`。
- `internal_dds=PASS`：按 `I+jQ` 约定使用 `-15.36 MHz` 内部对照频率后，sample0-aligned phase p-p `2.84e-14 deg`，fit residual mean `7.45e-5`。
- `readback_consistency=PASS`：同一 preview buffer 双读一致。
- `large_event_capture=PASS`：事件 buffer 双读一致，event `max_code=28734`，`RFDC flags=30`。
- `dac_phase_commit=PASS`：`0/45/90/180 deg` phase commit 后 DAC clock-domain epoch 增长，CH0 constant phasor mode/phase0 readback 正确。
- `rfdc_source=PASS` with warning：`phase_error` p-p `353.01 deg`，max abs from first `176.58 deg`，RMS `100.17 deg`，触发 RFDC/模拟/时钟路径嫌疑。

补充非 DC 基带检查：

```bash
sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_hardware_phase_audit.py --mode rfdc --signal-mhz 130 --center-mhz 100 --bw-mhz 100 --samples 512 --frames 60 --seconds 10 --event-threshold 28000 --timeout 2.0
```

结果：`classification=rfdc_or_analog_or_clock_path_suspect`，expected baseband `30 MHz`，RFDC phase p-p `351.04 deg`，max abs from first `176.84 deg`，RMS `111.13 deg`，`max_abs_code=32616`，large-signal frames `1`。这说明抖动不只是 `signal=center` 的 DC 拟合现象。

## 阶段衔接说明

下一阶段可依赖：

- `internal_dds` 和 `sample_index_ramp` 可作为 preview/sample0/CDC 的内部对照源。
- large-event buffer 可在不移动线缆时抓取异常帧的 raw IQ、`sample0`、RFDC flags、DAC phase epoch。
- DAC phase commit 不再只看 AXI 写寄存器，可读到 DAC clock domain seen epoch 和 CH0 phase state。
- Stage 15 已基本排除 Jupyter/Plotly、preview BRAM/MMIO 双读、sample_index 顺序、internal DDS 对照源、DAC phase commit 作为当前大相位抖动的一阶主因。

下一阶段不能依赖：

- Stage 15 不证明 RFDC/模拟链路已稳定，也不证明科学 payload 幅相质量通过。
- Stage 15 不接 CMAC/QSFP live，不声明交换机或接收节点收到 UDP 包。
- `internal_dds`/`sample_index_ramp` 只进入 preview audit mux，不是 science/PFB/TX 数据源。

剩余风险：

- 当前证据已经进入 `internal_dds` 稳定但 `rfdc` 抖动的分支；下一阶段应重点查 RFDC mixer/NCO reset、RFDC MTS/clock、RFDC AXIS adapter lane validity 和模拟链路。
- event buffer 双读目前一致；如果后续出现不一致，再回到 preview BRAM/MMIO/CDC readout。
- DAC audit epoch/phase0 目前跟随配置；如果后续 phase slider 不影响 measured phase，再查 DAC constant phasor/phase reset 与 RFDC DAC tile 输出路径。
- `RFDC flags=30` 在 event metadata 中仍需解码到具体 tile/block 状态位，作为下一阶段定位入口。

推荐入口命令：

```bash
./scripts/run_xsim_batch.sh tb_preview_event_capture tb_rfdc_fullrate_preview tb_feng_ctrl_axi
sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_hardware_phase_audit.py --signal-mhz 100 --center-mhz 100 --bw-mhz 100 --samples 512 --seconds 60 --event-threshold 28000 --timeout 2.0
```

## AI 接续提示

- 读 Stage 15 结果时先看 `classification` 字段：
  - `preview_bram_or_mmio_readback_unstable`：先修 readback/CDC。
  - `preview_observer_sample0_latch_or_cdc_suspect`：先修 preview observer/sample0 latch。
  - `dac_phase_commit_cdc_suspect`：先修 DAC phase commit。
  - `rfdc_or_analog_or_clock_path_suspect`：Jupyter/preview 内部源基本排除，转 RFDC/模拟/clock/adapter。
- `internal_dds` 的内部对照频率在 Python `I+jQ` 约定下是 `-15.36 MHz`；不要再用 `+15.36 MHz` 判定它，否则会误报 preview/sample0/CDC 失败。
- notebook 主观测图仍服务天文学家；`Hardware Audit` 只放在高级面板。
- 不要把配置锁定的 reference phase 当成硬件相位稳定证据；硬件判断看 Stage 14/15 的 sample0-aligned measured phase、event metadata 和 audit source 对照。

## 阻塞项

- Stage 15 本身已完成；QSFP live 接入前仍阻塞在 RFDC/模拟/clock/adapter 抖动归因。
- 下一阶段需要在不移动 DAC0-ADC0 线缆的前提下继续查 RFDC 配置/状态、MTS/clock、AXIS lane 映射和事件帧 raw IQ。
