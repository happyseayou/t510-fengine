# Stage 26b/27：PL-only DDR TIME 缓冲与时序优化

## 结论

Stage 26b/27 已完成本地 RTL/API/TB 落地并完成 Vivado 复跑，`CORE_VERSION=0x0001001D`。目标是先修 Stage 26 里 `time_udp_cmac512` 的组合输出临界路径，再接入 PL-only DDR ring buffer 作为 TIME packet/frame 的短时弹性缓存。

当前结论：

- `time_udp_cmac512` 的 CMAC AXIS 输出已寄存化。
- `axis512_register_slice` 已改成 2-entry skid/register buffer。
- 新增 `time_axis512_ddr_ring.sv`，以完整 512-bit packet/frame beat 为单位写入/读出 DDR，保留 `tkeep/tlast`。
- `t510_fengine_top` 已把 TIME CMAC path 接入 DDR ring；DDR disable 时保持 pass-through。
- `t510_fengine_board_top` 已把 core DDR AXI master 通过 BD wrapper 接到 DDR controller 的 PL AXI 通道；PS CPU 不参与数据搬运。
- `feng_ctrl_axi` / Python API 已新增 DDR enable/base/slots/status/counter 配置与读回。
- Stage 25 low-rate path、TIME UDP payload v2 wire format、SPEC/PFB/full-science blocker 保持不变。

Vivado 结果已经收敛：`synth_1` 完成，`impl_1` route complete，timing met，bitstream/export 完成。当前不把 license critical warning 当成功能失败，但需要在报告里明确保留。

## 关键实现

### RTL

- `rtl/feng_ctrl_axi.sv`
  - `CORE_VERSION` 升到 `0x0001001D`。
  - 新增 TIME DDR ring control/status/readback register。

- `rtl/time_udp_cmac512.sv`
  - 输出侧使用 `out_tdata/out_tkeep/out_tlast/out_tvalid` 寄存器驱动 `m_axis_*`。
  - header beat 和 IPv4 checksum 元数据在 send 前预计算/寄存，缩短 CMAC TX 输出路径。

- `rtl/axis512_register_slice.sv`
  - 实现为 2-entry skid/register buffer。
  - `tb_axis512_register_slice` 已按 skid 容量更新，验证满两拍后反压、下游释放后有序输出。

- `rtl/time_axis512_ddr_ring.sv`
  - 写侧接 TIME 512-bit frame stream，读侧接 CMAC TX stream。
  - DDR slot 内存放 metadata + frame data，metadata 保存 last `tkeep`、frame beat count 和 `last_seen`。
  - 满载策略为 drop 当前 frame 并递增 `drop_frame_count`，不长期反压 RFDC/science path。
  - `occupancy_frames = write_frame_count - read_frame_count`，避免同周期读写更新丢失。

- `bd/t510_rfdc_bd.tcl` / `rtl/t510_fengine_board_top.sv`
  - BD 打开 DDR controller 的 PL AXI 通道，并 externalize 为 `time_ddr_s_axi`。
  - board top 将 40-bit core DDR address zero-extend 到 wrapper 的 49-bit AXI address。
  - `time_ddr_s_axi_awuser/aruser` tie-off 到 `1'b0`。

### Python / API

- `python/t510_fengine.py`
  - 新增 `read_time_ddr_ring_status()`。
  - 新增 `configure_time_ddr_ring(...)`。
  - `configure_time_live(...)` 支持 `ddr_enable`、`ddr_base_addr`、`ddr_slots`、`ddr_clear`。
  - `run_stage26_time_live_validation(...)` 默认 expected core version 更新为 `0x0001001D`，并记录 DDR ring status/counter delta。

- `scripts/pynq_stage26_time_live_bringup.py`
  - expected core version 更新到 `0x0001001D`。
  - 新增 `--ddr-enable`、`--ddr-base-addr`、`--ddr-slots`、`--ddr-clear`。

## 本地验证

已通过：

```bash
./scripts/run_xsim_batch.sh tb_axis512_register_slice tb_time_axis512_ddr_ring tb_time_udp_cmac512 tb_feng_ctrl_axi tb_stage25_cmac_live_tx tb_t510_fengine_top_smoke tb_t510_fengine_board_top
./scripts/run_xsim_batch.sh tb_t510_fengine_board_top
python3 -m py_compile python/t510_fengine.py python/packet.py scripts/pynq_stage26_time_live_bringup.py scripts/pynq_stage25_time_live_bringup.py scripts/host_stage25_time_pcap_check.py
cargo test --manifest-path rust/t510_time_rx/Cargo.toml
git diff --check
```

覆盖项：

- `time_udp_cmac512` frame packing / tail `tkeep` / output frame count。
- DDR ring pass-through、write/read、wrap/full/drop、metadata 对齐。
- AXI-Lite DDR register readback。
- CMAC live source mux 和 top smoke。
- Rust TIME payload decode、bandwidth dynamic selector、sample0 delta auto-detect。

## Vivado 状态

当前 Vivado session：`stage26`。

已执行：

```tcl
source /home/astrolab/demo-ant/bd/t510_rfdc_bd.tcl
source /home/astrolab/demo-ant/scripts/setup_project.tcl
reset_run synth_1
launch_runs synth_1 -jobs 8
reset_run impl_1
launch_runs impl_1 -to_step write_bitstream -jobs 8
```

结果：

- `synth_1` 完成：`0 Errors`、`0 Critical Warnings`、`439 Warnings`。
- `impl_1` route complete，`0` routing errors，`129912` fully routed nets。
- Routed timing summary：`WNS=+0.000 ns`、`TNS=0.000 ns`、`WHS=+0.012 ns`、`THS=0.000 ns`。
- `txoutclk_out[0]` 是最薄的 setup path group，最终 worst setup slack 为 `0.000 ns`。
- Physopt 中最值得关注的改善点是 `u_core/u_time_udp_cmac512/token_ip_checksum_reg_*` 和 `u_core/u_time_live_ddr_ring/m_axi_awaddr_reg*`。
- Bitstream 已生成：`demo-ant.runs/impl_1/t510_fengine_board_top.bit`。
- Overlay 已导出并与 bitstream 对齐：`overlay/t510_fengine.bit`。

Bitstream 证据：

- `overlay/t510_fengine.bit` SHA256：`6380d6ef70d002dbebd985027622b4f6bdb2fd2af9d5a6a2a04857082ebeb3b8`
- `overlay/t510_fengine.hwh` SHA256：`5e6cde952e062cee76200ba5851c2bede926bff90a06435c52f23eeecf78e0be`
- `overlay/t510_fengine.tcl` SHA256：`854f0ec83bd8cc399484da6574737746856ffed5b930596e565d69fc88f9f574`
- `overlay/t510_fengine.manifest.txt` SHA256：`e7b8be99a88b41a4412f60b2600bf854a2c556b35db5809998c8a3bf5fd10b4b`

## 板端同步尝试

2026-06-22 已把 `0x0001001D` overlay 同步到 PYNQ：

- `/home/xilinx/t510_fengine_bringup/overlay/t510_fengine.bit`
- `/home/xilinx/t510_fengine_bringup/t510_fengine.bit`
- `/home/xilinx/jupyter_notebooks/t510_fengine/overlay/t510_fengine.bit`

三处 bit SHA256 均为 `6380d6ef70d002dbebd985027622b4f6bdb2fd2af9d5a6a2a04857082ebeb3b8`。

2026-06-22 后续推进：

- sudo 执行通道已确认可用；板端密码约定为“与登录用户名相同”。命令仍通过 stdin 传入凭据，不把实际密码写入脚本或 notebook。
- 修正 `run_stage26_time_live_validation(...)` 的 TX gate 判据：使用同一次 `read_tx_status()` 解析后的 TX 快照判断 `cmac_tx_ready`、`udp_dry_run_active`、fault、mux、underflow/overflow，避免 `read_status()` 顶层别名在 100/200MHz 高速切换窗口里采到瞬态 `TX_STATUS=64014` 后误报。
- DDR disabled direct path 已跑通：

```bash
cd /home/xilinx/t510_fengine_bringup
source /etc/profile.d/xrt_setup.sh
printf "%s\n" "<operator-provided-sudo-password>" | sudo -S -p "" -E \
  /usr/local/share/pynq-venv/bin/python3 scripts/pynq_stage26_time_live_bringup.py \
  --no-download --bandwidth-mhz all --seconds 2 \
  --output reports/board/stage26_time_full_rate_live_direct_bringup_fixed.json
```

结果：`STAGE26_TIME_FULL_RATE_PASS` / `PASS`，`20/100/200MHz TIME_ONLY` direct path 均 PASS。该结果只覆盖板端 counters/gates，不覆盖 host pcap/Rust/HTML。

2026-06-22 板子因 DDR enabled path 挂死后已重启，重启后复测发现一个软件状态污染问题：

- RFDC/debug smoke 使用 `--mask 0x1` 后，`rfdc_active_mask` 留在 `0x0001`。
- Stage 26 TIME route 表按 8 路默认写入 `input_mask=0x00ff`、endpoint 2；full-rate RTL 的 route key 是 `{8'd0, rfdc_active_mask[7:0]}`。
- 因此重启后第一次 direct run 出现 `TX_ROUTE_MISS`、`tx_selected_endpoint=0`、`time_packet_count=0`，但 CMAC/RFDC/link 本身 ready。

修复：

- `configure_time_low_rate_live(...)` 现在在 TIME live bring-up 时显式把 RFDC active mask 和 TIME route input mask 绑定到低 8 路，默认恢复 `0x00ff`。
- `run_stage26_time_live_validation(...)` 对 TX gate 状态增加短窗口多次采样；如果 100MHz 高速切换窗口偶发读到 `cmac_tx_ready=0` / `udp_dry_run_active=1`，只要后续样本 clean 且 counters 正常增长，就不误判为链路失败。

重启后修复版 direct path 证据：

```bash
cd /home/xilinx/t510_fengine_bringup
source /etc/profile.d/xrt_setup.sh
printf "%s\n" "<same-as-login-username>" | sudo -S -p "" -E \
  /usr/local/share/pynq-venv/bin/python3 scripts/pynq_stage26_time_live_bringup.py \
  --no-download --bandwidth-mhz all --seconds 2 \
  --output reports/board/stage26_time_full_rate_live_direct_after_reboot_maskfix2.json
```

结果文件已同步回本地：`reports/board/stage26_time_full_rate_live_direct_after_reboot_maskfix2.json`。

结果：`STAGE26_TIME_FULL_RATE_PASS` / `PASS`。

| bandwidth | active mask | TIME packet delta | TX frame built delta | route miss delta | route error delta | time drop delta | frame drop | underflow | overflow |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 20MHz | `0x00ff` | 240487 | 240487 | 0 | 0 | 0 | 0 | 0 | 0 |
| 100MHz | `0x00ff` | 962004 | 962005 | 0 | 0 | 0 | 0 | 0 | 0 |
| 200MHz | `0x00ff` | 1923880 | 1923904 | 0 | 0 | 0 | 0 | 0 | 0 |

Rust/HTML 动态接收 smoke：

- Rust receiver 先 `cargo build` / `cargo test` 通过，再以 `--interface ens2f0np0 --port 4300 --web 127.0.0.1:8089` 启动。
- `8088` 被 Vivado 占用时，改用 `8089` 不影响接收逻辑。
- 通过 HTTP API 在同一进程内连续切换 selected bandwidth 为 `20 -> 100 -> 200`，receiver 不需要重启。
- 三档在 API state 里都能看到 `selected_bandwidth_mhz == detected_bandwidth_mhz`，`parse_errors=0`，且 waveform 始终输出 8 路。
- 这仍不是 host 无损 PASS：debug receiver 的消费能力只有约 `12-14 Gbps`，100/200MHz 时 `seq_gaps/sample0_gaps/app_drops` 持续增长，说明当前只是“动态可调 + 可视化闭环”验证，不是高档位无损接收验收。

DDR enabled path 触发新的 blocker：

```bash
cd /home/xilinx/t510_fengine_bringup
source /etc/profile.d/xrt_setup.sh
printf "%s\n" "<operator-provided-sudo-password>" | sudo -S -p "" -E \
  /usr/local/share/pynq-venv/bin/python3 scripts/pynq_stage26_time_live_bringup.py \
  --no-download --bandwidth-mhz all --seconds 2 --ddr-enable --ddr-clear \
  --output reports/board/stage26_time_full_rate_live_ddr_bringup_fixed.json
```

现象：

- 命令超过 90 秒无输出。
- 同时发起的新 SSH 查询也无响应，随后主机侧对 `192.168.100.117` 变为 `No route to host`。
- 60 秒后复测，ping 仍 `100% packet loss`，SSH 仍 `No route to host`。
- 这说明 DDR ring enable 可能让 PL DDR AXI 访问触发了 PS/DDR/管理网级别的挂死或复位，当前分类为 `BLOCK_STAGE26B27_DDR_ENABLE_BOARD_UNREACHABLE`。

初步判断：

- direct CMAC/TIME 512-bit path 已经可用。
- PL-only DDR ring 的 AXI 地址/PS DDR slave interface/DDR carveout/AXI outstanding 或错误响应处理仍需修正。
- 当前默认 DDR base 为 `0x0000000800000000`，再次上板前必须核对 BD address map、PS DDR 可达窗口、XMPU/firewall/HP-HPC 端口配置，并给 DDR ring 加上更保守的默认禁用、地址范围保护和 AXI 超时/错误可观测机制。

License 说明：

- `write_bitstream` 期间仍报 `Vivado 12-1790 Evaluation License Warning`。
- 触发点是 `cmac_an_lt@2020.05` 的 `design_linking` license；`cmac_usplus@2020.05` 为 bought license。
- 这是保留风险，不是 routing 或 bitgen 失败。

## 阶段边界

Stage 26b/27 现在证明 DDR-disabled direct TIME full-rate 板端 counters/gates 已通过。不声明：

- 板端 `20/100/200MHz` TIME live pcap PASS
- DDR enabled path PASS
- SPEC/PFB/full science ready
- DGX/X-engine、交换机、ARP/VLAN/PTP
- 长时间网络 backpressure 或 soak 无损

## 下一步

1. 板端已重启恢复，direct path 保留为 Stage 26 full-rate TIME 板端 counters/gates 验收基线。
2. 继续 direct path 的 host pcap/Rust/HTML 验收；不要把当前板端 counters/gates PASS 扩大解释成 host/Rust/HTML PASS。
3. 不再直接启用 DDR ring。修 DDR ring 前置条件：核对 BD address map 和 DDR 可达窗口，降低/校验 `ddr_base_addr`，添加 AXI timeout/error 状态。
4. DDR 回板前先做独立 AXI memory smoke test，再接回 TIME path；DDR 仍只作为 PL 数据面缓存，PS CPU 不参与 TIME 数据搬运。
