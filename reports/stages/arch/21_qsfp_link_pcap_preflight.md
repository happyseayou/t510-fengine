# Stage 21：QSFP 链路与 pcap 预检边界

## 阶段摘要

QSFP 物理口现在已经接上，但当前 RTL 顶层仍没有真实 CMAC/GT/QSFP 高速数据通路。`t510_fengine_board_top.sv` 里 `m_axis_tx_tready` 仍绑为 `1'b1`，`tx_link_status_flags` 仍固定 dry-run active；这表示包被内部 dry-run sink 消费，不表示线缆上已经发出 UDP science data。

因此 Stage 21 只能做两件事：

- 准备 QSFP link/CMAC/pcap 预检脚本和状态分类。
- 如果当前 bit 仍无 CMAC/GT path，明确返回失败分类，阻止把 dry-run 误报成 live science data。

## 已实现内容

- Python 新增 `read_qsfp_preflight_diagnostics()`：
  - 读取 `tx_status`、`tx_link_status_flags`、dry-run、link、GT lock、CMAC reset done、CMAC TX ready。
  - 分类：
    - `CURRENT_BIT_DRY_RUN_NO_CMAC_GT_DATAPATH`
    - `QSFP_LINK_READY_FOR_PCAP`
    - `QSFP_LINK_SEEN_BUT_TX_FORCED_DRY_RUN`
    - `QSFP_LINK_NOT_READY`
- 新增脚本 `scripts/pynq_stage21_qsfp_link_pcap_check.py`：
  - 配置默认 SPEC/TIME UDP endpoint。
  - 尝试关闭 dry-run 并打开 CMAC enable。
  - 若硬件仍报告 dry-run/no live CMAC-GT path，直接失败并写明不能验证 pcap。
  - 只有在 `link_pcap_possible=True` 时才允许要求 `--pcap-interface` 抓包。

## 预检命令

```bash
cd /home/xilinx/t510_fengine_bringup
source /etc/profile.d/xrt_setup.sh
sudo -E /usr/local/share/pynq-venv/bin/python3 \
  scripts/pynq_stage21_qsfp_link_pcap_check.py \
  --seconds 2.0 \
  --output reports/stage21_qsfp_preflight.json
```

如果未来 CMAC/GT path 真正接入并且脚本返回 `QSFP_LINK_READY_FOR_PCAP`，再指定接收机网卡：

```bash
sudo -E /usr/local/share/pynq-venv/bin/python3 \
  scripts/pynq_stage21_qsfp_link_pcap_check.py \
  --seconds 10.0 \
  --pcap-interface <rx_interface> \
  --pcap-output reports/stage21_qsfp_udp.pcap \
  --output reports/stage21_qsfp_pcap.json
```

## 判定规则

- `CURRENT_BIT_DRY_RUN_NO_CMAC_GT_DATAPATH`：当前 bit 不能做 QSFP live science data 验收，需要先接 CMAC/GT wrapper、refclk/reset/status 和 TX AXIS。
- `QSFP_LINK_NOT_READY`：硬件 path 可能存在，但 link/GT/CMAC 状态不齐，先查 refclk、reset、GT lock、CMAC status 和约束。
- `QSFP_LINK_SEEN_BUT_TX_FORCED_DRY_RUN`：链路状态可能起来了，但 TX 仍被 dry-run 或控制寄存器拦住，先查 `TX_CONTROL` 和 status flags。
- `QSFP_LINK_READY_FOR_PCAP`：才允许进入 pcap 和下游 packet checker。

## 下一步硬件工作

要真正进入 QSFP live science data，必须完成：

- 在 board top 或 BD 中接入 CMAC/QSFP wrapper 与 GT/refclk/reset。
- 把 F-engine `m_axis_tx_*` 接到 CMAC TX AXIS，而不是内部 dry-run sink。
- 增加真实 link/status/counter readback，区分 dry-run accepted、CMAC accepted、line transmitted、pcap received。
- 补 QSFP GT/refclk/IO 约束和实现时序门禁。
- 上板后用 pcap 和 packet checker 验证 SPEC/TIME UDP frame，同时继续保持 Stage 19/20 的 `3 deg / 5%` 数据质量门禁。

## 当前状态

本阶段脚本已落地并已在 Stage 20 overlay `CORE_VERSION=0x00010010` 上板运行。结论为预期阻塞：`CURRENT_BIT_DRY_RUN_NO_CMAC_GT_DATAPATH`。

板端结果：

- 结果文件：`reports/board/stage21_qsfp_preflight.json`
- `result=FAIL`
- `classification=CURRENT_BIT_DRY_RUN_NO_CMAC_GT_DATAPATH`
- `science_data_validated=false`
- `link_pcap_possible=false`
- `qsfp_link_up=0`
- `tx_gt_locked=0`
- `tx_cmac_reset_done=0`
- `tx_cmac_tx_ready=0`
- `tx_udp_dry_run_active=1`
- 错误说明：current overlay is still dry-run/no live CMAC-GT datapath; QSFP live pcap cannot be validated

这不是线缆接错的直接证据，也不是 Stage 20 数据质量失败；它说明当前 bit 的 RTL 边界仍停在 dry-run TX。QSFP 口可以接线并做存在/状态检查，但在接入真实 CMAC/GT/QSFP wrapper 前，不能声明 live science data 通过。
