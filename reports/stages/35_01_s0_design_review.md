# Stage 35 步骤 1：S0 全频段科学采集架构设计审查

> 日期：2026-08-30
> 状态：`DESIGN_REVIEW_COMPLETE`；后续实现见[步骤 2](35_02_s0_fullband_accumulator_implementation.md)
> 范围：只审查采集架构、分桶、充分统计量、落盘和验证边界；未修改接收机、未登录板卡、
> 未启动采集或 Vivado

## 1. 审查结论

设计可以进入步骤 2 实现，但正式板上观测仍被步骤 3 replay 验证和步骤 4 的 60 s 烟雾
采集阻止。批准的核心方案是：

```text
已有 AF_PACKET/PACKET_FANOUT 唯一消费者
  -> 已有 UDP/T510 头校验
  -> 16 个 SPEC block 的 worker-local 科学累加器
  -> 有界的已完成桶队列
  -> 单独 Zarr writer、chunk journal 与数据集 manifest

同一已校验包 -> 现有稀疏 spec-stability（兼容保留）
             -> 现有低频率网页 spectrum preview（兼容保留）
```

科学累加发生在完整频谱预览组装之前。每个 block 独立保存真实 `N_valid`、曝光和 gap，依靠
共同的 `sample0` 桶轴以及 `frame_id / 16` 谱帧组号保持 16 个 block 的时间一致。不得为了
构造一幅中央完整频谱而把全速数据重新汇聚到单一互斥锁。

## 2. 已审查的基线

- [仓库宪法](../../AGENTS.md)：长队列的完整提交、健康启动后交还控制权，以及 Vivado 操作
  边界。
- [Stage 35 总方案](../../reports/stages/archive/35/35_radio_astronomy_noise_study_plan.md)：8×4096、10 ms
  首选桶、A/B/C 分层数据和逐 bin 科学结果。
- [UDP payload v2 合同](../../docs/t510_udp_payload_v2.md)：16×256 block、IQ16、`sample0`
  与 `frame_id` 语义。
- [Stage 34 全速 PFB8 发布](34_fullrate_pfb8_release.md)：v34、4096 通道、8-tap PFB、
  320 MS/s 生产链和 ENBW 基线。
- [Stage 35 v34 基线统一](35_v34_baseline.md)：正式 bitstream、`onboard_tcxo` 和未部署边界。
- `rust/t510_time_rx/src/main.rs` 中的 `SpecStabilityMonitor`、`FullSpectrumAssembler`、
  `FanoutWorkerRuntime`、逐 flow 连续性统计和 TIS1 writer。
- `rust/t510_time_rx/src/lib.rs` 中的快速头解析、SPEC 合同校验和 IQ16 解码入口。

## 3. 现有代码哪些可以复用

可以复用：

- 现有 PACKET_FANOUT 端口分流。16 个 SPEC 目标端口已经把 block 分散给 worker，不需要新
  socket 或新接收进程。
- `parse_t510_header_fast` 与 `validate_spec_header_fast`，它们先验证产品身份、包长、
  4096×16×256 布局和 8-tap PFB。
- 每个 SPEC flow 的 `seq_no`/`frame_id` 连续性观测，以及全局 NIC、ring、kernel 和
  application drop 遥测。
- 现有稀疏 `spec-stability` 的 RF/bin 映射、控制面模式和充分统计量测试思路。

不能直接复用为正式全带累加核心：

- `SpecStabilityMonitor` 最多选择 32 个 bin，只接受 100/1000 ms；结果主要留在内存，遇到
  任意 gap 会终止，且不满足长扫描持续分块落盘。
- `FullSpectrumAssembler` 服务网页预览，会计算 amplitude/phase/dB，并受显示帧率、共享锁
  和选择性 decode 控制。它没有为每个谱帧留下完整质量账本，不能成为科学数据路径。
- 现有 monitor 为每个 block 使用各自收到的第一包作为桶原点；如果扫描开始处某个 block
  缺包，16 个 block 的桶原点可能错位。Stage 35 必须改用全局统一边界。
- 现有正式 monitor 用主机 `sleep` 结束测量；Stage 35 的正式开始、分桶和目标曝光必须由
  `sample0` 决定，主机时钟只记录操作时间。

## 4. 累加位置与 16-block 时间一致性

### 4.1 位置

在 `FanoutWorkerRuntime::process_frame` 完成 SPEC 头校验后、网页预览处理前，调用新的
Stage 35 ingest。累加器只解码本包的 `256 × 8` 个 IQ16，不生成幅度、相位或 dB。

默认 fanout-by-port 下，一个 SPEC block 始终进入同一个 worker。实现应把热路径状态放在
worker/flow 本地，避免每包获取全局 monitor mutex。控制器只用 generation、armed/start/end
bucket 和失败状态等低频共享状态；完成桶通过有界队列送 writer。

### 4.2 统一谱帧身份

每个包至少验证并记录：

```text
frame_group = floor(frame_id / 16)
block_index = 0..15
chan0       = block_index * 256
sample0_step_per_group = 4096          # 320 MS/s Stage 35 正式模式
seq/frame delta per same block = 16
```

同一 `frame_group` 的 16 个 block 必须具有相同 `sample0` 和产品身份。全速热路径不建立中央
逐帧 16-bit coverage map；每个 block 保存缺失/重复/乱序 group range，离线可对 16 份 range
求交并恢复“完整频谱帧”集合。没有 gap 时，16 个 block 的首末 group、`sample0` 和
`N_valid` 必须完全一致。

### 4.3 正式扫描起止

控制器先进入 `armed`。由 block 0 的有效包选择未来的共同完整桶边界作为
`start_bucket`，所有 block 使用同一个 start/end bucket 范围；15 min、30 s 等持续时间换算
为完整桶数。首尾主机命令落入的部分桶不进入正式数据，但作为启动/收尾事实写入日志。

## 5. `sample0` 分桶设计

320 MS/s 正式模式下 `sample0` 使用 320 MHz 时基：

| 桶宽 | `sample0` ticks | 每桶谱帧数的自然模式 |
|---:|---:|---|
| 10 ms | 3,200,000 | 781 或 782 |
| 20 ms | 6,400,000 | 1562 或 1563 |
| 50 ms | 16,000,000 | 3906 或 3907 |
| 100 ms | 32,000,000 | 7812 或 7813 |

桶号只由共同的 `start_sample0` 和上述整数宽度计算，不按包到达时间计算。每个包按半开区间
`[bucket_sample0_start, bucket_sample0_end)` 归属；保存实际首末 `sample0`、`N_valid` 和
曝光。预期帧数按实际 PFB 帧相位计算，不能硬编码成恒定 781、782 或 7813。

10/20/50/100 ms replay 验证使用四个相互独立的分桶器。10 ms 充分统计量还要离线合并成
20/50/100 ms，与独立分桶结果逐项比较。若正式数据最终退到 20 ms，50 ms 不是 20 ms 的
整数倍，因此 50 ms 只保留为独立验证产品，不能声称由 20 ms 桶无损重建。

`sample0` 的 `u64` wrap 虽在现实扫描中不会发生，仍作为协议测试：检测 wrap 后增加本次
扫描内部的 `sample_epoch`，不让 wrap 前后的桶相撞。进程重启生成新 scan segment，禁止
把两个 segment 静默拼接。

## 6. 统计字段、类型与合并公式

### 6.1 热路径充分统计量

对每个 `block × adc × local_bin` 维护：

| 字段 | 内部类型 | 说明 |
|---|---|---|
| `n` | `u64` | 有效谱帧数；包级校验通过后同一 block 内所有 cell 一致 |
| `sum_i`, `sum_q` | `i64` | IQ16 精确加宽求和 |
| `sum_p` | `u64` | `P=I²+Q²` 的加宽和；单个 P 最大为 `2^31` |
| `mean_p`, `m2_p` | `f64` | 稳定的功率均值与未归一化二阶中心矩 |
| `clip_count` | `u64` | I/Q 达饱和定义的次数；落盘桶内可校验后转 `u32` |

100 ms 最坏约 7813 帧，`sum_i/q` 和 `sum_p` 均远小于对应整数上限。不得用 `u64` 保存
`sum(P²)`：IQ16 极值下它会溢出。`M2_P` 使用 float64 的 Welford/Chan 形式，并在合成极值、
常数、小方差和大直流偏置数据上验证误差。

两个可合并 moment `A/B` 使用：

```text
n     = n_a + n_b
delta = mean_b - mean_a
mean  = mean_a + delta * n_b / n
M2    = M2_a + M2_b + delta^2 * n_a * n_b / n
```

I/Q 和功率均值必须按真实 `n` 加权；缺桶不以零代替。`n=0` 时数值数组写 NaN，并由
`N_valid=0` 和质量 flag 明确解释。

### 6.2 正式落盘层

- A 层 10 ms：`mean_power_count2` 为 float64，形状
  `[time_bucket, adc=8, global_bin=4096]`；`N_valid`、起止 `sample0` 和质量计数按
  `[time_bucket, block=16]` 保存。
- B 层 100 ms：`mean_i_count`、`mean_q_count`、`m2_power_count4` 为 float64，
  `clip_count` 为 uint32；B 层由 10 ms 完整充分统计量用上述公式合并，不从已舍弃字段的
  A 层文件反推。
- C 层：独立短 PCAP/SPEC 和 TIME 原始片段，只用于验证短记忆、量化和累加一致性。

## 7. writer、分块和中断恢复

在线格式优先选择 Zarr directory store。原因是采集端当前为静态 ARM64 musl Rust 发布件，
直接引入原生 HDF5 会增加动态库和交叉编译边界。实现必须使用经过独立 reader 验证的标准
Zarr 布局，不能只生成名称像 Zarr 的私有二进制文件。

建议 A 层 chunk 为 `[100 buckets, 8 ADC, 256 bins]`，即每个 block 每秒约 1.64 MB；
B 层采用相同的 256-bin 频率分块和约 1 s 时间分块。单 writer 管理元数据和 16 组互不重叠
的频率 chunk；packet worker 只 `try_send` 已完成桶，绝不在热路径执行磁盘 I/O。

- 队列必须有界并报告 high-water mark。
- 队列满或 writer 失败时，扫描立即标记 `capture_failed`；不得静默丢桶，也不得阻塞收包
  worker 直到造成未记录的网络丢包。
- chunk 先写 `.partial`，完成长度、checksum 和 fsync 后原子 rename；journal 只登记已经
  commit 的 chunk。
- 异常退出保留 `.partial`、journal、已完成 chunk 和失败原因。恢复工具只做验证和封存；
  除非有显式、可证明连续的 resume 合同，否则新进程使用新 `scan_segment_id`。
- 数据集 manifest 为每个文件记录大小和 SHA-256，并生成整个目录的稳定清单哈希。

## 8. 容量与吞吐预算

以下为不依赖压缩的 15 min 单次扫描十进制容量：

| 数据 | 10 ms | 20 ms fallback |
|---|---:|---:|
| A 层 `mean_P` float64 | 23.593 GB | 11.796 GB |
| B 层三个 float64 字段（100 ms） | 7.078 GB | 7.078 GB |
| B 层 `clip_count` uint32（100 ms） | 1.180 GB | 1.180 GB |
| block 质量表、元数据、哈希 | 小于上述主数组，实测回填 | 同左 |
| 单扫描小计（不含 C 层） | 约 31.85 GB | 约 20.05 GB |
| 三次扫描小计（不含 C 层） | 约 95.55 GB | 约 60.16 GB |

10 ms 主数据写入约 26.2 MB/s；加上 B 层摊销后约 35.4 MB/s。磁盘带宽不是主要未知量，
主要风险是对约 10.24 GB/s SPEC payload 中全部复数执行功率和 moment 运算。实现必须利用
16-block fanout、连续内存和批量/SIMD 友好的循环，并以 full-rate replay 和板上 60 s 实测
决定是否有足够余量。正式三扫描前建议为主数据、C 层片段、临时 chunk 和安全余量准备至少
120 GB 可用空间；实际要求由步骤 4 回填。

## 9. 丢包、乱序、重复与质量账本

新的 per-block reorder/continuity tracker 不能沿用“见一个 gap 就放弃整次结果”的行为：

- 在有界 reorder window 内恢复乱序后再累计。
- 重复 group 只计入 `duplicate_count`，不重复进入科学统计。
- window 外的缺失记录 group/sample0 range，后续有效帧继续累计。
- late packet 记录为 `late_count`；已经 commit 的桶不得被后台悄悄改写。
- 每桶每 block 保存 expected/valid/missing/duplicate/reordered/late、首末 group、首末
  `sample0`、seq/frame 异常和 writer 状态。
- 布局、PFB profile、sample rate、`fft_shift` 或观测身份在扫描中变化时立即结束当前
  segment 并保留现场，不能把两种配置混在同一数组。

科学分析默认使用全量有效数据，并按真实曝光加权；是否另派生“只含 16-block 全帧交集”的
产品由离线 gap-range 账本决定。任何一种产品都不得填零替代缺失。

## 10. 10 ms 与 20 ms 的选择门槛

步骤 3 必须先用相同 replay 同时验证 10/20/50/100 ms，步骤 4 再对 10 ms 做 60 s 实机
烟雾采集。10 ms 只有同时满足下列事实才成为正式原生桶：

- NIC、kernel、ring、worker、application 和 writer 未出现未解释 drop/gap；
- 所有 16 个 block 的正式桶数、首末边界和无 gap 时的 `N_valid` 一致；
- writer 队列无溢出，结束后所有 chunk、journal、manifest 和 SHA-256 可复读；
- replay 的 10 ms 离线合并与独立 20/50/100 ms 累加器在注册容差内一致；
- 统计循环使用全部 IQ16 值，未通过 stride、抽 bin 或显示降采样降低计算量。

若 10 ms 失败，必须先区分原始全带计算、chunk/metadata 频率还是存储抖动造成的瓶颈。
只有修复后仍不能无损运行，才测试并记录 20 ms fallback；20 ms 不会减少逐复数功率计算量，
因此不能把它当作所有 CPU 问题的默认修复。

## 11. “全部有效桶而非抽点”的证明

步骤 3/4 至少保存并核对：

- 输入有效 frame/group 总数等于各 block 所有桶 `N_valid` 之和加明确排除的首尾部分帧；
- 每个输出桶的 `source_first/last_group` 和 `N_valid` 可追溯到 replay/短 PCAP；
- 合成脉冲放在每一种桶内位置和 chunk 边界，输出均能恢复其功率贡献；
- 15 s 细节查询返回恰好 1500 个 10 ms 桶或 750 个 20 ms 桶，减去的只能是带 flag 的真实
  缺失桶；
- HTML 的像素 envelope 在步骤 8 单独生成，不参与 Parquet/Zarr 数值计算。

## 12. 实现拆分与下一动作

步骤 2 建议按以下代码边界实现：

1. 可独立单测的 `stage35` accumulator、bucket clock、moment merge 和 continuity 模块；
2. fanout worker 热路径接入与 generation/start/end 控制；
3. 有界队列、Zarr chunk writer、journal 和 manifest；
4. HTTP/CLI 状态面只暴露控制与进度，不通过 HTTP 返回整个数据立方体；
5. 合成/replay 驱动和 Python/独立 reader 互操作验证入口。

步骤 2 不修改 FPGA RTL、不启动 Vivado、不部署板卡，也不提交 S1/S2 长队列。完成实现和
普通单元测试后，转入独立的[步骤 3 replay 验证](35_03_s0_replay_validation.md)。
