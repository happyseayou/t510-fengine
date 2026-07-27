# Stage 32h最终30分钟针对性soak

## 结论

`PASS`

在真实整板冷启动、fresh CONFIGURE/MTS和20秒恢复门禁通过后，按冻结顺序执行
三个满线速模式，每项600秒：

1. 160 MS/s TIME_SPEC；
2. 320 MS/s TIME_ONLY；
3. 320 MS/s SPEC_ONLY。

编排汇总为`STAGE32H_FULL_LINE_PASS`，三个模式的板端和主机门禁全部通过，每项
结束后均自动STOP且`flush_clean=true`。

## 执行

首次执行：

```bash
python3 scripts/stage32h_remote_matrix.py \
  --suite full_line \
  --seconds 600 \
  --tag final30_20260727
```

前两项完成后，在切换到第三项时，一个人工只读status请求恰好与CONFIGURE重叠。
Agent按预期返回`409 HARDWARE_BUSY`，第三项尚未开始打流。该事件是验证工具的
互斥冲突，不是板卡、时钟、MTS或数据面故障。

确认板卡已安全停流后，用相同tag断点续跑：

```bash
python3 scripts/stage32h_remote_matrix.py \
  --suite full_line \
  --seconds 600 \
  --tag final30_20260727 \
  --resume
```

编排器复用前两项PASS证据，只执行第三项，最终汇总无error。

## 结果

| 模式 | 主机有效包 | 包率 | UDP payload速率 | 板端数据面错误增量 | 主机drop/gap |
|---|---:|---:|---:|---:|---:|
| 160 TIME_SPEC | TIME `375,004,272` + SPEC `374,997,076` | TIME `625,007.12` + SPEC `624,995.13` pps | `83,200.149538 Mbit/s` | 0 | 0 |
| 320 TIME_ONLY | TIME `750,002,096` | `1,250,003.49 pps` | `83,200.232516 Mbit/s` | 0 | 0 |
| 320 SPEC_ONLY | SPEC `750,033,344` | `1,250,055.57 pps` | `83,203.698961 Mbit/s` | 0 | 0 |

三项共同满足：

- RFDC、science、TIME、SPEC、TX drop和route error/miss的正式窗口增量为0；
- 需要PFB的模式中，overflow、data halt、XFFT event、tile overflow、TLAST
  error、FFT overflow、backpressure、sample0 overflow和系数错误增量均为0；
- 主机parse、kernel、ring、worker-ring和application drop均为0；
- TIME和SPEC的sequence/frame/sample0 gap均为0；
- TIME_ONLY没有SPEC包，SPEC_ONLY没有TIME包；
- QSFP全部稳定物理条件通过；
- watchdog没有锁存10 MHz fault；
- 每项测试后`streaming=false`、`stream_accepting=false`、
  `flush_clean=true`。

## 非阻塞观测

每项开始快照都可能看到
`BOARD_QSFP_LINK_SAMPLE_LOW_DURING_BACKPRESSURE_BEFORE`。当前`link_up`字段包含
瞬时CMAC `tready`，而物理GT lock、reset done、RX aligned/status、module
present和fault bits全部健康，因此验证器把它正确归类为warning。

接收机分别记录少量
`NIC_RX_STEER_MISSED_OUTSIDE_T510_WHITELIST=119/71/122`。这些是白名单外的NIC
流量，没有对应T510 parse/drop/gap，不影响验收。

320 TIME_ONLY证据中的`board_counter_delta.tx_frames_sent=-11637654`不是负数发包
或真实丢包。该status字段在RTL中是条件复用值：CMAC `tready`瞬时低时从live
frame计数切到dry-run计数；结束快照恰好读到dry-run分支的0，因此不能把它当作
单调计数器求差。同期可用的`tx_frames_built`增量为`761,839,040`，主机有效TIME
包为`750,002,096`，所有专用drop/gap计数均为0。该语义限制保留在报告中，不修改
UDP格式或生产RTL。

320模式每次START到正式稳态快照前可见`rfdc_dropped=18`启动基线；各600秒正式
窗口中该值增量为0。与冷启动20秒门禁的观测一致。

## 证据

| 文件 | SHA256 |
|---|---|
| `stage32h_full_line_summary_final30_20260727.json` | `86f21834135560115e27831e3e4901c9fd6fe320ed2fb1aa7bd680f6b453b887` |
| `stage32h_full_line_160msps_time_spec_final30_20260727.json` | `bedbd80809644b56a8e6ca248f97e72f5f2f1ccc8aeea6ae5e5ff0e89b343bec` |
| `stage32h_full_line_160msps_time_spec_final30_20260727_host.json` | `453ba0d1e0fa97111ce0ba627531face907d6e16612c44ac3179f135ac9214e8` |
| `stage32h_full_line_320msps_time_only_final30_20260727.json` | `c2e4b02c00dba0af75f76dcecc12f2df3701d2d3b9a976ef9ab7f6f54e48974d` |
| `stage32h_full_line_320msps_time_only_final30_20260727_host.json` | `c88899f3890a454e7be0e3b336a0d9cd6ed609b5655c199350652953e0dfde12` |
| `stage32h_full_line_320msps_spec_only_final30_20260727.json` | `350f5666fa19b17ef60c9f538e1a69f283e350178a706e3327bee1c8fd1db54b` |
| `stage32h_full_line_320msps_spec_only_final30_20260727_host.json` | `3bf397f5de8f32935cab1d0bcb8d953e7153f156ba3fdf9fbaf135c88e8c72f6` |

## 最终状态

Stage 32h的功能矩阵、长稳、PPS切换、reference fault、RFDC ready-low、Linux
warm reboot、真实整板冷启动和最终soak均已通过。`32h`可改为`PASS`，Stage 32
单板release闭合。双板物理同步仍必须等待`32i`，不能由本报告代替。
