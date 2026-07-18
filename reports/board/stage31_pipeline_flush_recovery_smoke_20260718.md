# Stage 31 修复版 Pipeline Flush 上板恢复 Smoke

## 结论

2026-07-18 已将修复版 Stage 31 bitstream 与 Board Agent 安装到 T510
`192.168.100.117`，执行 fresh configure 后按现场故障顺序完成
`START -> ABORT -> STOP -> IMMEDIATE START`。第二次启动后的 TIME/SPEC 计数持续前进，
RFDC drop 只在 flush/restart 边界出现有限增量，随后保持不变；science、TIME、SPEC、TX
drop 和 route error 均为 0。该 smoke 证明原来必须 reload bitstream 才能恢复的数据通路
锁死已经解除。

这不是多板同步验收。修复版的 PREPARE/ARM/PPS commit、共同输入相位与 Hub 端实际收包
仍需在 Center Hub 联测中完成。

## 发布与 fresh configure

- Board Agent release：`/opt/t510-agent/releases/stage31-54a3e73cf7af-20260718083108`
- Agent version：`0.2.1`
- catalog：`fengine-0x00010031`
- core version：`0x00010031`
- bitstream SHA256：`21357385978297a688e9418e086852d4a8aac2deaa25078e1570b81cdc4266c9`
- board ID：`1`
- fresh configure：`100 MHz TIME_SPEC`、AA100 active、24 endpoints 与 source identity 回读一致，耗时 `9250.524 ms`
- configure 后：`streaming=false`、TIME/SPEC/TX counters 为 0、`flush_clean=true`、PFB FIFO 为 0、RFDC downstream ready、error flags 为 0
- 部署和测试后 `t510-agent.service` 与 `jupyter.service` 均为 active；测试没有重启 Jupyter。

## 故障序列复测

### 第一次 immediate start

两次相邻健康快照如下：

| 指标 | 快照 1 | 快照 2 |
|---|---:|---:|
| TIME packets | 8,632,830 | 17,438,909 |
| SPEC packets | 8,632,751 | 17,438,828 |
| TX frames built | 17,266,885 | 34,878,983 |
| RFDC dropped | 7 | 7 |
| science/TIME/SPEC/TX dropped | 0 | 0 |

两路 science counter 都持续前进，`stream_accepting=true`、RFDC downstream ready，
且 RFDC drop 在观察窗口内不增长。

### ABORT、STOP 与第二次 immediate start

- ABORT 返回 `aborted=true`，并报告 `pfb_clear_pulsed=1`、`tx_clear_pulsed=1`；PFB/TX 配置位均被保留。
- STOP 后 `streaming=false`、PFB FIFO 为 0、CMAC mux 解锁、`flush_clean=true`。
- 第二次 immediate start 后的三个快照中，TIME packets 从 `7,018,470` 增至
  `13,774,837`，再增至 `28,179,891`；SPEC packets 从 `7,018,384` 增至
  `13,774,752`，再增至 `28,179,808`。
- 同一窗口内 RFDC dropped 固定为 `35`，science/TIME/SPEC/TX dropped、route miss、
  route error 全部为 0；`stream_accepting=true`、RFDC downstream ready、error flags 为 0。

因此没有复现旧行为的“TIME 只有几包、SPEC 为 0、RFDC drop 持续增长”，也不需要重新
configure/reload bitstream 才能恢复。

## 现场观察与联测边界

运行中 QSFP link/mux 状态有瞬时抖动，一次 Agent 快照的 `tx_frames_sent` 回读为 0，后续
快照恢复为 `56,360,966`，最终 STOP 快照为 link-up。此期间 TIME/SPEC 与 frames-built
始终持续增长，未形成 RFDC 反压，因此它不属于本次已修复的 science pipeline 锁死；但
板端快照也不能替代 Hub 实际收包，联合测试应同时检查 Hub 端 sequence gap/drop 和板端
QSFP/link/mux 状态。

测试结束后板卡保留修复版 bitstream 和 `100 MHz TIME_SPEC` 配置，并停在：

- `streaming=false`
- PFB disabled、PFB FIFO 为 0
- CMAC mux unlocked、无 stale science frame
- `flush_clean=true`、RFDC downstream ready
- science block reasons 为空、error flags 为 0
- QSFP module present、link-up

Center Hub 可以从该状态开始新的 configure 或 Stage 31 PREPARE/ARM 联测。
