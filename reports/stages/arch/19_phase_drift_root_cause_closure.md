# Stage 19：相位漂移根因闭环

## 阶段摘要

Stage 19 已经把 CH0 DAC0 到 ADC0 这条 dry-run/witness 路径上的相位漂移主因闭合。此前怀疑过的 Jupyter 显示、Python 相位算法、preview BRAM 读数、DAC phase commit、DAC 单音源，以及 RFDC/模拟链路本身作为一阶主因，都已经被当前证据压下去了。

本阶段实际闭合的是两个具体问题：

- RFDC AXIS clock tree 曾经有真实偏差：RFDC/F-engine 数据面现在已经使用并上报精确的 `61.440 MHz` AXIS beat 和 `245.760 MHz` sample metadata。
- SPEC payload 曾经有数据连续性问题：旧版 `spectral_packetizer` 把一个 256-bit beat 拆成四个 64-bit subword 输出时会对下游施加反压，但 RFDC ADC adapter 本身不能反压上游，导致 SPEC payload 内部跳样；新版改成先连续抓完整 payload window 到 BRAM，再输出 header/payload。

整个阶段没有降低门禁：

- preview/payload 相位 p-p `<= 3 deg`
- preview/payload 幅度 p-p `<= 5%`
- DAC pre-RFDC witness 相位 p-p `<= 0.5 deg`
- DAC pre-RFDC witness 幅度 p-p `<= 1%`

## 修改内容

- `rtl/spectral_packetizer.sv`
  - SPEC payload 由原来的边读边拆分输出，改为连续抓取 256 个 256-bit beat，再从本地 BRAM 发出 payload。
  - 使用 `xpm_memory_sdpram`，避免 inferred register-array payload buffer 带来的 FF/LUT 暴涨。
  - ADC 侧捕获保持连续，不再制造与 `rfdc_adc_axis_adapter.sv` 冲突的反压行为。
- `rtl/feng_ctrl_axi.sv`
  - `CORE_VERSION` bump 到 `0x0001000E`。
- 板端 Stage 19 脚本同步期望 `0x0001000E`：
  - `scripts/pynq_stage19_phase_root_cause_check.py`
  - `scripts/pynq_lmk_rfdc_mts_recovery_check.py`
  - `scripts/pynq_rfdc_sysref_coherence_lock_check.py`
  - `scripts/pynq_rfdc_udp_coherence_audit.py`
- DAC pre-RFDC witness 保留并用于 `constant_phasor` 和 `single_tone` 两种 DAC 源模式。

## 本地门禁

Vivado implementation / bitstream：

- `impl_1`：`write_bitstream Complete`
- bitgen：`0 Errors`，`0 Critical Warnings`
- 时序：
  - `WNS=+1.267 ns`
  - `WHS=+0.010 ns`
  - failed endpoints `0/226852`
- placed utilization：
  - CLB LUTs `62369/425280 = 14.67%`
  - CLB registers `120834/850560 = 14.21%`
  - Block RAM tiles `39.5/1080 = 3.66%`
  - RAMB36/FIFO `20`，RAMB18 `39`

Overlay 导出：

- `overlay/t510_fengine.bit` SHA256 `a7dc97e186d1981fcd07d7abfc3f33ffbaf04381e9771e5aaa325a5e907e714d`
- `overlay/t510_fengine.hwh` SHA256 `345fdf3aea634a323dc3fd8f9bdde872c04a92d161ba08404782fd4260e39e4f`
- `overlay/t510_fengine.tcl` SHA256 `015b765be0ac7b80b97a2b2c895d9b87d911715414df9d834504011282013b8c`
- manifest：`overlay/t510_fengine.manifest.txt`

## 板端证据

板卡：`xilinx@192.168.100.117`

板端 overlay hash 与本地一致：

- `overlay/t510_fengine.bit` SHA256 `a7dc97e186d1981fcd07d7abfc3f33ffbaf04381e9771e5aaa325a5e907e714d`

LMK/RFDC MTS：

- tile0-only probe：`reports/stage19_lmk_mts_core_0001000e_tile0.json`
  - `result=PASS`
  - `classification=RFDC_MTS_LOCK_PASS`
  - `CORE_VERSION=0x0001000E`
  - LMK `pll1_lock=1`，`pll2_lock=1`
  - MTS probe `ok=true`，failures `[]`
- full-mask probe：`reports/stage19_lmk_mts_core_0001000e_fullmask.json`
  - `result=PASS`
  - `classification=RFDC_MTS_LOCK_PASS`
  - ADC/DAC tile masks `0xf/0xf`
  - MTS probe `ok=true`，failures `[]`

clock metadata：

- `preview_axis_beat_rate_hz=61440000`
- `preview_sample_rate_hz=245760000`
- 二者精确匹配预期的 `61.440 MHz` 和 `245.760 MHz`。

## 严格矩阵

完整板端门禁：

- 证据文件：`reports/stage19_phase_root_cause_core_0001000e_full.json`
- 条件矩阵：`constant_phasor,single_tone` x `119.2,130.24,130.0 MHz` x `TIME,SPEC`
- 帧数：每个条件 `240` 帧，共 `2880` 条 records
- 结果：`PASS`
- 分类：`PS_DERIVED_AXIS_CLOCK_MISMATCH_CLOSED`
- 数据质量门禁：对 CH0 dry-run/witness 路径为 `READY_FOR_QSFP_SCIENCE_DATA`
- errors：`0`

全矩阵最差值：

- preview phase p-p：`0.281892 deg`
- preview amplitude p-p：`1.289775%`
- payload phase p-p：`0.474061 deg`
- payload amplitude p-p：`2.032418%`
- DAC pre-RFDC witness phase p-p：`0.222517 deg`
- DAC pre-RFDC witness amplitude p-p：`0.123542%`

重点条件：

- `constant_phasor` off-center SPEC 已通过：
  - `119.2 MHz` payload phase p-p `0.363496 deg`，amplitude p-p `0.612835%`
  - `130.24 MHz` payload phase p-p `0.349372 deg`，amplitude p-p `0.711305%`
- `single_tone` off-center SPEC 已通过：
  - `119.2 MHz` payload phase p-p `0.430108 deg`，amplitude p-p `0.741489%`
  - `130.24 MHz` payload phase p-p `0.339779 deg`，amplitude p-p `0.744581%`
- center/DC 条件相位 p-p 为 `0.0 deg`，幅度 p-p 均低于 `2.04%`。

witness 和 latency 证据：

- DAC witness 每个条件都抓到数据，并满足 `0.5 deg / 1%` 门禁。
- TX payload witness word count 在全部 `2880` 条 records 中固定为 `1040`。
- `tx_source_header_delta` 在全部 `2880` 条 records 中固定为 `1100`。
- 没有 witness overflow、filter mismatch 或 invalid witness state。
- 没有 record-level error。
- 没有 clipping 或 large-event 污染。
- preview 到 payload 的 `sample0_delta` 会变化，因为二者是顺序采集，不是同一个冻结 RFDC window。确定性的 packetizer latency 证据是固定的 `tx_source_header_delta=1100`。

## 前后对照

旧版 Stage 19 完整报告：

- 证据文件：`reports/stage19_phase_root_cause_core_0001000d_full.json`
- 结果：`FAIL`
- 分类：`PACKETIZER_PAYLOAD_UNSTABLE,PS_DERIVED_AXIS_CLOCK_MISMATCH_CLOSED`
- SPEC off-center 失败：
  - `constant_phasor 119.2 MHz SPEC`：payload phase p-p `347.872507 deg`，amplitude p-p `194.471156%`
  - `constant_phasor 130.24 MHz SPEC`：payload phase p-p `358.479368 deg`，amplitude p-p `293.068118%`
  - `single_tone 119.2 MHz SPEC`：payload phase p-p `350.621069 deg`，amplitude p-p `204.256897%`
  - `single_tone 130.24 MHz SPEC`：payload phase p-p `358.266976 deg`，amplitude p-p `245.401572%`

当前 Stage 19 完整报告：

- 证据文件：`reports/stage19_phase_root_cause_core_0001000e_full.json`
- 结果：`PASS`
- 条件矩阵和严格阈值不变。
- 最大 payload phase p-p 从接近整周 wrap 降到 `0.474061 deg`。
- 最大 payload amplitude p-p 降到 `2.032418%`。

这个 before/after 形态指向 SPEC packetizer 数据连续性错误，而不是 DAC single-tone 产生、RFDC preview、Jupyter 显示或 Python 相位算法错误。

## 阶段判定

对于 CH0 DAC0 到 ADC0 dry-run/witness 路径：

```text
PHASE_DRIFT_ROOT_CAUSE_CLOSED
```

已经闭合的主因：

- PS-derived RFDC AXIS clock/sample-rate mismatch 是真实早期根因，已通过精确的 RFDC/PL-derived clock metadata 闭合。
- clock 修复后残留的 SPEC payload 漂移来自 packetizer payload discontinuity。根因是对不能反压的 ADC stream 施加了拆包反压；BRAM capture/emission 修复已在板端闭合。

本阶段不声明：

- 不声明科学级 RF 绝对功率/相位标定完成。
- 不声明 CH1..CH7 模拟 loopback 稳定。
- 不声明 CMAC/QSFP live receive path、交换机、VLAN、ARP、PTP 或下游 X-engine 正确。
- 不把当前 placeholder `pfb_channelizer.sv` 当作科学级 4096-channel 4-tap PFB/FFT。

## QSFP 状态边界

Stage 19 的 `READY_FOR_QSFP_SCIENCE_DATA` 只表示 CH0 dry-run/witness 数据质量已经允许进入 QSFP 验证阶段，不表示当前 overlay 已经具备真实 QSFP live 发包能力。

当前 `t510_fengine_board_top.sv` 仍然没有接入 CMAC/GT/QSFP 高速数据通路：

- board top 只有 `qsfp0_modprsl/intl/resetl/lpmode/modsell` 这些 QSFP 管脚控制/状态信号。
- `tx_link_status_flags` 在 board top 中固定为 `32'h0000_0002`，含义是 dry-run active。
- core 的 `m_axis_tx_tready` 在 board top 中绑为 `1'b1`，TX frame 被内部 dry-run sink 消费。
- 当前 `tx_frame_sent_count` 仍然等价于 dry-run sink 接收计数，不是真实 QSFP 发包计数。

因此，下一步可以进入 QSFP 阶段，但第一步必须是硬件工程工作：接入 CMAC/QSFP wrapper、GT/refclk/reset/status、约束和 live TX AXIS，然后重新综合实现、bitgen、上板验证 link-up 与 pcap。不能把现在的 `0x0001000E` bit 直接当作 live QSFP 数据验证 bit。

## 复现命令

同步 overlay/scripts/python 后，板端命令如下：

```bash
cd /home/xilinx/t510_fengine_bringup
source /etc/profile.d/xrt_setup.sh

sudo -E env PYTHONUNBUFFERED=1 /usr/local/share/pynq-venv/bin/python3 \
  scripts/pynq_lmk_rfdc_mts_recovery_check.py \
  --configure-lmk --probe-mts \
  --adc-tiles 0x1 --dac-tiles 0x1 \
  --adc-ref-tile 0 --dac-ref-tile 0 \
  --output reports/stage19_lmk_mts_core_0001000e_tile0.json

sudo -E env PYTHONUNBUFFERED=1 /usr/local/share/pynq-venv/bin/python3 \
  scripts/pynq_stage19_phase_root_cause_check.py \
  --signals-mhz 119.2,130.24,130.0 \
  --dac-source-modes constant_phasor,single_tone \
  --modes time,spec \
  --frames 240 \
  --mts-adc-tiles 0x1 --mts-dac-tiles 0x1 \
  --mts-adc-ref-tile 0 --mts-dac-ref-tile 0 \
  --output reports/stage19_phase_root_cause_core_0001000e_full.json

sudo -E env PYTHONUNBUFFERED=1 /usr/local/share/pynq-venv/bin/python3 \
  scripts/pynq_lmk_rfdc_mts_recovery_check.py \
  --configure-lmk --probe-mts \
  --adc-tiles 0xf --dac-tiles 0xf \
  --adc-ref-tile 0 --dac-ref-tile 0 \
  --output reports/stage19_lmk_mts_core_0001000e_fullmask.json
```

## 阶段交接

后续除非出现新的反证，不要再把这个相位漂移问题回退到 notebook、Python、DAC source 或 preview BRAM 方向。

推荐下一阶段：

1. 做 Stage 20：CMAC/QSFP live TX bring-up。
2. 接入 CMAC/QSFP wrapper，把 `m_axis_tx_*` 从 dry-run sink 接到 CMAC TX AXIS。
3. 增加真实 link/status/counter readback，区分 dry-run accepted、CMAC accepted、line transmitted、pcap received。
4. 接收端抓 pcap，先验证 Ethernet/IP/UDP header、route、seq/sample0，再验证 payload 相位/幅度。
5. 在真实 QSFP path 上保持 Stage 19 的 `3 deg / 5%` 数据质量阈值，不降低门禁。
6. 在声明科学级频谱数据前，实现并验收真实 PFB/FFT，而不是继续依赖 placeholder `pfb_channelizer.sv`。
