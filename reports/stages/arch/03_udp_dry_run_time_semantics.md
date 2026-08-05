# Stage 3: UDP Dry-Run Time Semantics

## 阶段目标

无 QSFP 条件下，让 packetizer 仍可产生带时间语义的 header，并通过 dry-run sink counters 验证 UDP 数据面活动。

## 输入基线

- Stage 0 已证明无 QSFP 不影响单板采样。
- 旧 packetizer header 缺少明确的 `epoch_mode`、`pps_count`、`payload_format` 字段。

## 完成内容

- 升级 TIME/SPEC packetizer header 到 v2：
  - `epoch_mode`
  - `flags`
  - `unix_sec`
  - `pps_count`
  - `sample0`
  - `frame_id`
  - `seq_no`
  - channel/time/input/payload layout
- 新增 flags 语义：
  - bit0 `TIME_VALID`
  - bit1 `INTERNAL_EPOCH`
  - bit2 `QSFP_LINK_UP`
  - bit3 `UDP_DRY_RUN`
  - bit4 `ADC_CLIP`
  - bit5 `FIFO_OVERFLOW`
- 新增寄存器：
  - `0x0360 TX_LINK_STATUS_FLAGS`
  - `0x0364 TX_DRY_RUN_PACKET_COUNT`
  - `0x0368 TX_DRY_RUN_BYTE_COUNT`
- 更新 `python/packet.py`：
  - v2 parser/emitter。
  - v1 backward-compatible parser。
- 新增 `scripts/check_t510_packet_header.py` host-side checker。

## 验证证据

- `tb_time_packetizer` 和 `tb_spectral_packetizer` 已锁定 v2 header word。
- `tb_t510_fengine_top_smoke` 已验证 top 输出 header version 2。
- `tb_feng_ctrl_axi` 已覆盖 dry-run flags/counter readback。
- 全量 XSim 通过。
- Vivado 实现和 bitstream 通过：`write_bitstream Complete`，0 error，0 critical warning，`WNS=+1.619 ns`，`WHS=+0.011 ns`。
- 板端 time-mode dry-run counter 冒烟通过：
  - 配置：`tcxo_10mhz + free_run + mode=time + mask=0x1`
  - 状态：`status=0x0000060b`，`streaming=1`，`fsm_state=6`
  - link flags：`tx_link_status_flags=0x00000002`，`qsfp_link_up=0`，`udp_dry_run=1`
  - counters：`tx_dry_run_packet_count=0 -> 33382`，`tx_dry_run_byte_count=0 -> 277751496`，`time_packet_count=0 -> 33379`

## 阶段衔接说明

- 下一阶段可依赖：header v2 的字段布局、Python parser、无 QSFP 时 dry-run link flag 和 sink counters。
- 下一阶段不能依赖：真实 CMAC/QSFP link-up；当前仍是内部 dry-run sink。
- 剩余风险：host-side 二进制 header capture/checker 尚未接入真实板端数据源；AXIS 到 Ethernet/UDP/IP/CMAC 的真实 framing 尚未接入。
- 推荐入口命令：
  ```bash
  ./scripts/run_xsim_batch.sh tb_time_packetizer tb_spectral_packetizer tb_t510_fengine_top_smoke
  python3 scripts/check_t510_packet_header.py --require-dry-run <captured_packet.bin>
  ```

## AI 接续提示

- 无 QSFP 时 `UDP_DRY_RUN=1` 是预期状态，不是错误。
- `QSFP_LINK_UP=0` 时只能信任 packetizer/counter/header 语义，不能声明真实发包成功。
- host-side checker 输入必须是包含 128B T510 header 的二进制包。

## 阻塞项

- CMAC/100G 未接入。
- 板端 host-side header capture 文件尚未形成，`check_t510_packet_header.py` 还没有真实板端二进制包输入。
- 真实 UDP/IP checksum、MAC framing、DGX 收包未验收。
