# Stage 35 步骤 5：S1 TIME-only ADU 控制观测

> 状态：`COMPLETE / READY_FOR_STEP6`
> 执行日期：2026-08-31（CST）
> 前置条件：[步骤 4](35_04_s0_60s_smoke.md)已完成

## 1. 结论

步骤 5 已完成。权威 30 s 观测覆盖 ADC0–ADC7 全部 8 路，共接收
`37,500,000/37,500,000` 个 TIME 包，每路 `9,600,000,000` 个复样本；8 路的 missing、
reorder、duplicate 均为 0。正式窗口内 receiver 的 kernel/ring drop、seq/frame/sample0 gap
以及板端 RFDC/TIME/科学链路/发送路由 drop 增量均为 0。

本数据的准确身份是 **RFDC/TIME 路径在 DDC/抽取之后的 complex IQ16 ADU**，每路复采样率
320 MS/s；它不是 ADC 的 3.84 GS/s converter 原始码。TIME-only 与 SPEC 不能在当前产品中
同时完整输出，所以本次是相邻控制观测，不宣称与后续 SPEC 扫描同步。

权威数据集位于采集机：

```text
/var/lib/t510/stage35/stage35-s1-time-control-authoritative-30s-20260831-0130
```

其 `observation_manifest.json` 为 7,765 bytes，SHA-256 为
`3b9ea12034673daaebc74f7efbba8e6ec297e8a43e860f9bcae053d008b09e87`，清单自校验
PASS；目录共 23 个文件、占用 529,382,604 bytes，且无 `.partial` 文件。

## 2. 观测身份与物理边界

| 项目 | 权威事实 |
|---|---|
| FPGA core | `0x00010034` |
| active bitstream SHA-1 | `2a04b728f66d5f6473e682bc04d5a2cbcd311b98`（板端运行时身份） |
| v34 bitstream SHA-256 | `c21d93f5ea71e9ac17a4448cff138a8faaf9c7347d879be919b680d196b8a5be`（已验证 catalog 身份） |
| 模式 | 320 MS/s、TIME-only、center 1020 MHz |
| RFDC | ADC 3.84 GS/s、decimation 12、active/valid mask `0xffff` |
| MTS target | ADC/DAC `416/112`，观测前后未变 |
| 时钟 | `onboard_tcxo`，PLL1/PLL2 均锁定 |
| clock profile | `160m_10m_request_manual_clkin0` |
| profile SHA-256 | `a8504d384354610f8f130b1cda1a446bcdfb25bf8c4bb689fbb58adefe5e88e2` |
| DAC | 全过程 mask 0；收尾 8 路均 disabled |
| 输入 | 操作者确认保持 Stage 35 的 8 路独立 50 Ω 接法；设备无连接器状态传感器，不能远程再证明 |
| 外部参考 | 操作者报告观测前已断开外部 10 MHz/PPS |

切换配置时，两次普通 FULL 配置均在 RFDC restart 中报
`DAC 0 timed out at state 6 in XRFdc_WaitForRestartClr`。没有断电；随后使用步骤 4 验证过的
clock-preserving 热更新路径恢复，事务
`1f148f0a24a18e0371b3a3737e7b8944` 未写 LMK RESET/profile，恢复后 TCXO、双 PLL、全部
RFDC tile 和 MTS 身份均重新核验通过。失败响应和最终配置响应均保存在 evidence 中。

## 3. 采集与计算实现

receiver 新增独立的 Stage 35 TIME 控制器及以下接口：

```text
POST /api/measure/stage35-time
GET  /api/measure/stage35-time/status
POST /api/measure/stage35-time/stop
```

8 个 TIME flow 在现有 PACKET_FANOUT worker 中分别就地累加，不把全速 payload 复制到中央
队列。每个原生 10 ms 桶按 `sample0` 定义，包内使用整数 `count/sum/sum_sq` 精确矩并在桶末
计算 mean、标准差和复 RMS；20 ms 行由相邻两个 10 ms 精确矩合并。正式累加前保留 100 ms
预热提前量。为避免只影响 flow 0 的显示开销，正式窗口内暂停并冻结 waveform preview。

全 30 s 保存了全部 3,000 个原生 10 ms 桶（24,000 行）以及 1,500 个派生 20 ms 桶
（12,000 行），因此报告所需任意连续 15 s 原生点无需抽样即可读取。min/max、近满量程削顶
计数和全窗矩覆盖 30 s；完整 16-bit 码值直方图明确限定在正式窗口最前面的连续 50 ms，
每路、每个 I/Q 分量各 `16,000,000` 个样本，避免把全窗随机直方图写入留在实时热路径。

短原始包导出也改为 8 路各自独立 slot 和预分配 PCAP 字节区，消除了全局 mutex 与逐帧
`Vec` 分配。此实现完全由 CPU 执行，未使用 GPU；receiver 沿用 24 个 fanout worker 的
superset 配置，本次只有 8 个 TIME flow 活跃，worker pin 关闭，未新增独立计算线程池或显式
核心规避策略。

## 4. 权威 30 s 结果

| ADC | mean I/Q (ADU) | std I/Q (ADU) | complex RMS (ADU) | I min..max | Q min..max | I/Q占用码数 | I/Q削顶 |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | 0.000329 / 0.000235 | 4.772631 / 4.773434 | 6.750087 | -30..30 | -30..30 | 50 / 51 | 0 / 0 |
| 1 | 0.000084 / -0.000598 | 4.727319 / 4.726518 | 6.684872 | -29..30 | -29..28 | 49 / 48 | 0 / 0 |
| 2 | -0.000029 / -0.000393 | 4.461631 / 4.460785 | 6.309101 | -28..27 | -28..28 | 47 / 47 | 0 / 0 |
| 3 | 0.000286 / -0.000211 | 4.140293 / 4.140664 | 5.855520 | -26..26 | -27..26 | 44 / 44 | 0 / 0 |
| 4 | 0.000674 / 0.000314 | 4.573917 / 4.573755 | 6.468382 | -27..28 | -28..28 | 48 / 48 | 0 / 0 |
| 5 | 0.000146 / 0.000013 | 4.417543 / 4.417706 | 6.247464 | -28..29 | -28..27 | 48 / 48 | 0 / 0 |
| 6 | 0.000023 / 0.000260 | 4.538254 / 4.538592 | 6.418300 | -26..28 | -27..29 | 46 / 45 | 0 / 0 |
| 7 | 0.000213 / 0.000493 | 4.372202 / 4.371998 | 6.183083 | -29..27 | -28..28 | 47 / 47 | 0 / 0 |

占用码数来自上述连续 50 ms 直方图，其余数值来自完整 30 s。这里仅陈述控制数据事实，
不把通道差异解释成温度、增益或天文结论，也不选择“代表通道”。

## 5. 连续原始片段

最终原始导出先取得 8 路共 65,536 包、约 52.43 ms 的无丢失 superset；独立解析找到最长
连续 run 为 62,622 包，再从中确定性裁出精确 62,500 包，即 320 MS/s 下 50.000 ms：

```text
raw/time_50ms_4300_4307.pcap
```

- 文件大小：`523,625,024` bytes；
- SHA-256：`60b2522671a65cfdc294065075d36e75689995846786521c07250f9f7447519b`；
- 每路连续样本：`16,000,000`；
- 全局 seq：`10,208,611..10,271,110`；
- sample0：`358,024,191,412..358,040,191,156`；
- 端口 4300–4307 包数为 7,812 或 7,813；
- seq/frame/sample0 discontinuity：0。

superset 保留在
`/var/lib/t510/stage35/stage35-s1-time-raw-final-20260831-0120/time_52ms_superset.pcap`，大小
549,060,632 bytes，SHA-256 为
`14d1106904cf3ec65ad1d0a914b9281d06b71d54e4ffac0984b1707201c70a6a`。裁剪边界、源/目标
身份和独立复读结果见 `evidence/raw_verification.json`。

## 6. 失败证据与优化闭环

| 尝试 | 结果 | 结论与处置 |
|---|---|---|
| 5 s，30 s尺度全直方图实现 | 5,868,881/6,250,000 包，ring drop 457,206 | 全码域随机写是热路径；直方图严格改为连续 50 ms |
| 优化后 5 s | 6,250,000/6,250,000，所有 drop/gap 为 0 | 通过诊断门禁 |
| 首次 30 s | 37,347,093/37,500,000；仅 flow 0 缺 152,907，ring drop 167,147 | 缺失从 bucket 492 开始；定位为 flow 0 额外 waveform preview 工作 |
| preview 冻结后 30 s | 37,500,000/37,500,000，正式窗口全零丢失 | 通过，随后以最终相同 receiver 二进制重采权威数据 |
| 原始导出：全局 mutex | ring drop 增量 13,609 | 丢弃 |
| 原始导出：分 flow、逐帧 `Vec` | ring drop 增量 2,939 | 仍丢弃 |
| 原始导出：分 flow、预分配 PCAP | 65,536/65,536 包，drop/gap 均为 0 | 作为最终原始片段来源 |

失败目录未冒充正式结果，并在 `observation_manifest.json` 的 `known_failed_evidence` 中列出，
包括首个直方图诊断、首次 30 s 丢包观测以及旧的不完整原始片段。

## 7. 数据清单与独立验证

权威数据集中主要文件如下：

| 文件 | 内容 | SHA-256 |
|---|---|---|
| `dataset_manifest.json` | 统计数据集清单 | `c5510d0a6c579b5c1f1732bd936f0662dde89b96a7b66868c2f93b6145bc0d98` |
| `time_10ms.csv` | 3,000桶 × 8路 | `210fe538bb244e11ae1eab54a7f144189ed6bbeb12ba372c6cfdde15d1ae092d` |
| `time_20ms.csv` | 1,500桶 × 8路 | `d3758d2acd8c6b7867ebeca5b731339af38ebf4bdb480999fd26aa1d52834e19` |
| `flow_quality.json` | 8路连续性账本 | `a18c4925e854e8d15e0e9cc32de29408f0783b6425beb3a4c463e1c4c88104c9` |
| `histogram.csv` | 前50 ms完整码值直方图 | `b405bbf329e074b2ecad88a747b1ae56eff0da94ca5098453348bc60b0f3f1af` |
| `summary.json` | 8路全窗摘要 | `894ed31f63ced08f97248dcd74ed3a4c52307e74e100a8e15c7b72be25dd832c` |
| `independent_verification.json` | 独立复读结果 | `c31a0a6705e8d438827afda5b5ac43b5fe823f13d41ffd61bc8282f9098954ef` |

独立验证脚本重新计算每个 manifest 文件哈希，检查 10/20 ms 桶数、逐桶 8 路覆盖、逐 flow
包数与事件账本、直方图总数，并直接解析 PCAP 检查 payload、seq/frame/sample0 连续性，结果
为 PASS。最终 receiver 二进制 SHA-256 为
`99dd0407316630212b9c99d81f19990bd8685c8b29235546ea364bb7178bfbe6`。

代码回归结果为 Rust release 测试 65/65 PASS、Clippy 成功（保留非阻断风格警告）、Python
校验脚本编译通过和 `git diff --check` 通过。当前系统 Python 未安装 pytest，因此本次收尾
没有在该解释器中重复运行 Python pytest；这不改变采集机独立数据验签结果。

## 8. 安全收尾与下一门控

板端已显式 STOP：`streaming=false`、`stream_accepting=false`、8 路 DAC disabled，TCXO 的
PLL1/PLL2 仍为 1，RFDC active/valid mask 仍为 `0xffff`。receiver 保持服务运行但处理速率
为 0、active worker 为 0，最终 drop/gap 计数均为 0。

步骤 5 的完成条件已满足，[步骤 6](35_06_s2_50ohm_spec_baseline.md)现为可提交状态。步骤 6
是 `TIME pre -> SPEC A/B/C -> TIME post` 的完整长队列；本步未启动该队列。
