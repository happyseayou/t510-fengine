# Stage 35 步骤 12：S5 28 基线干涉测量

> 状态：`IN_PROGRESS / INDEPENDENT_50OHM_FULLBAND_BASELINE_COMPLETE`
> 前置条件：第一阶段单路时间噪声已经闭合，并另行确认互相关数据体积与物理信号方案

## 1. 本步目标

对全部 `a < b` 的 28 对 ADC、全部 4096 bin 计算生产 F-engine 复可见度
`V_ab=<X_a conj(X_b)>`，先测独立 50 Ω 负载下的仪器内部相关底，再用公共已知噪声源做
相对增益/相位/延迟定标，最后才扩展到真实双天线或阵列。

## 2. 独立设计决策

- 10 ms 全部 28×4096 complex float64 约 183.5 MB/s，进入本步前必须明确保存原生桶还是
  保存 2/4/15/30 s 可合并统计；
- 不得只选若干基线或 bin；
- 零可见度附近以 Re/Im 为主，幅度和相位只作带限制的辅助量；
- 双天线必须重新引入并定标共同频率参考、PPS/绝对时间、几何延迟、fringe stopping、天线
  位置和源模型；第一阶段无 WR 的相对时间结论不能直接外推。

## 3. 必需结果

- 每条基线每 bin 的 Re/Im、绝对散布、Allan、自协方差和 temporal PSD；
- 2/4/15/30 s 产品、相干度辅助量、延迟谱和相位斜率；
- 独立负载、公共噪声源和真实天空三层物理解释严格分开；
- 不输出“28 条中 N 条合格”。

## 4. 完成条件

28 条基线全量数据、质量账本、定标身份和逐项结果完成后闭合。本报告当前仅是范围骨架，
没有授权新物理接线或长任务。

## 5. 独立 50 Ω 全频子阶段执行记录

本轮不修改FPGA、bitstream或UDP格式。receiver唯一PACKET_FANOUT接收机把已验证的16个
SPEC block写入16个有界共享内存环，GB10上的CUDA 13 sidecar批量解包IQ16并形成8路自功率
和冻结顺序`(0,1),(0,2)…(6,7)`的28对Hermitian外积。正式Zarr v2保存全4096 bin的1 s
auto/cross、精确sample0、16 block `n_valid`和质量账本；32个r4自动选择重点频点另存100 ms
产品。环满、GPU错误、缺包、乱序或writer落后均使观测失败，不静默降级。

开发门禁已完成10 s真实链路零丢失资格观测：12,500,000包发布/消费完全一致，16 block
完成掩码`0xffff`、ring drop为0。独立Zarr复读检查1,474,560个全带值和115,200个重点值，
100 ms加权合并到1 s的最大绝对差为`1.818989e-12 count²`。CUDA/CPU整数oracle覆盖独立噪声、
共同噪声、固定/随频相位、慢漂移、IQ16削顶、缺包拒绝、乱序拒绝和复乘符号；冻结真实
SPEC PCAP oracle将作为正式队列第一阶段再次运行。

正式长队列冻结为`stage35-xcorr-explorer-v1-20260901-2200`，对应unit
`t510-stage35-xcorr-explorer-v1-20260901-2200.service`。完整队列包含60 s全频CUDA烟雾门禁、
A/B/C三组`TIME pre 30 s + XCORR 900 s + TIME post 30 s`、六份50 ms TIME raw、每次XCORR
始末SPEC raw、独立数值验证、全带bootstrap/BH分析和只读应用验收/切换。

此状态只表示独立50 Ω子阶段已具备正式执行条件。新数据尚未完成前不写复相关科学结论；
即使子阶段完成，公共噪声源定标、真实天线、天空相位、延迟模型和成像仍属于后续工作，
步骤12不会因此标记`COMPLETE`。

## 6. 40–360 MHz 独立 50 Ω 基线完成

正式工作点随后按用户要求改为中心200 MHz，实际RF覆盖
`40.000000–359.921875 MHz`。最终队列
`stage35-40-360mhz-hpc-v1-20260902-1400-xcorr-queue`已完成A/B/C三次900 s全频复相关，
每次前后各含30 s TIME控制段和50 ms raw witness。九阶段均为`completed`、
`formal_integrity.ok=true`，没有把失败重试的半成品混入最终应用。

全频产品仍为1 s的8路auto、28对complex cross和16 block有效样本账本；32个重点bin保留
100 ms产品。当前只读应用已能按一个或多个pair/频点读取Re/Im、`|γ|`、门控相位、Allan、
ACF、2/4/15/30 s散布和同tile/跨tile矩阵。29张应用图的计算公式、权威Zarr/Parquet/PCAP
来源及当前实算数字均在图旁显示，正式Chromium验收外网请求0、严重console错误0。

```text
queue_state SHA-256:
7b32290ccb94cbf777b218707b99e9f31309918781cdaa261314bac85817a512
queue_manifest: 9 scans / 293 files
queue_manifest SHA-256:
ed87a9008cb98d560d35fe13fe39ff005e486db2e29a0a073d85a72a9cb7a131
application: http://192.168.100.162:8035/
```

本次结果只闭合`INDEPENDENT_50OHM_FULLBAND_BASELINE`子阶段。公共噪声源相对增益/相位/延迟
定标、真实天线、天空相位和成像尚未开始，因此步骤12整体继续保持`IN_PROGRESS`。

## 7. 全频 100 ms 扩展正在实施

极简报告需要任意 ADC 对、任意频率都能查看同批数据的 100 ms 与 1 s 复可见度，而上一版
只有 32 个重点频点保存了 100 ms。2026-09-03 因此新增兼容请求字段
`save_fullband_100ms`，默认 `false`；本次正式任务才设置为 `true`。CUDA writer 将保存
`[9000,8,4096]` auto、`[9000,28,4096]` complex cross、sample0 和 16-block `n_valid`，
并由每十行的整数累加量与有效谱数形成既有名称的 1 s 产品。

本扩展在 60 s 全速烟雾、一次 900 s 正式采集、逐通道加权合并复算、原地 SHA-256 和浏览器
验收前不记为完成。即便通过，也只增加
`INDEPENDENT_50OHM_FULLBAND_100MS_BASELINE_COMPLETE`子状态；步骤 12 整体仍为
`IN_PROGRESS`，不报告天空相位、成像或未测量的物理根因。

该扩展已由同一 GB10 长队列 `t510-stage35-simple-v1-20260903-2130.service` 一次性提交。
健康检查时 unit 为 `active/running`、queue 为 `running`、`error=null`，60 s 烟雾阶段正在
启动，900 s 正式阶段已登记为 pending 并会自动接续；当前不提前写入完成结论。

v1 后续在正式 `sample0` 窗口开始前因板端 START 瞬态 `rfdc_dropped delta=19` 停止，
`packets_published=0`，因此没有形成可验收的 100 ms 数据。问题属于新队列对启动区间和正式
区间的门禁边界实现错误，不是 CUDA 数值 oracle 或正式采集数据失败。失败目录和计数证据均
保留，板卡已安全停流。

门禁边界修正后，完整流水线已于 2026-09-04 14:18:57 CST 以新 unit
`t510-stage35-simple-v2-20260904-1420.service` 和新 queue
`/var/lib/t510/stage35/stage35-simple-v2-20260904-1420-queue` 重新提交。复核时 60 s 全频
100 ms writer 烟雾阶段已进入 `running`、`ring_drops=0`，900 s 正式阶段仍由同一进程等待
自动接续。本子阶段因此继续为实施中，不提前记录完成状态。

该队列随后完成 60 s 烟雾和 900 s 正式数据，正式 manifest 覆盖约 20.9 GB，采集阶段和
全频 100 ms→1 s 加权合并数值验证均完成。最终失败仅来自候选网页把 TIME_ONLY capture
标签误送给 F-engine 原始谱接口；复相关数据未受影响。修复后的浏览器/切换恢复任务已于
2026-09-04 15:09:11 CST 启动且不重新采集。在恢复任务通过并生成最终身份前，本子阶段仍不
提前写成`COMPLETE`。

第一次浏览器恢复在逐帧双路归一化相关幅度的零功率分母处发现`NaN`并按严格 JSON 门禁停止。
该值现明确作为缺测`null`输出、相位标为不可靠，不会伪造成0；它不改变已经验签的复可见度
数组。第二次浏览器/切换恢复任务已于2026-09-04 15:20:37 CST健康启动，仍不重新采集。

第二次恢复的唯一失败是浏览器自动 favicon 请求产生404严重日志；全部复相关视图已越过数据
加载门禁。内嵌图标修复后的第三次恢复任务已于15:23:24 CST健康启动，科学数组保持不变。

第三次恢复最终正常完成，浏览器门禁`PASS`、8035已切换，队列 manifest 标记
`complete=true`且`no_archive_copy=true`。因此本轮
`INDEPENDENT_50OHM_FULLBAND_100MS_BASELINE_COMPLETE`子阶段完成；步骤12整体仍保持
`IN_PROGRESS`，公共噪声源定标、真实天线、天空相位及成像能力仍未执行。
