# Stage 35 步骤 3：S0 合成数据与 packet replay 验证

> 日期：2026-08-30
> 状态：`COMPLETE / READY_FOR_STEP4 / NATIVE_BUCKET_NOT_YET_SELECTED`
> 前置报告：[步骤 2](35_02_s0_fullband_accumulator_implementation.md)
> 范围：本地合成测试、保存 PCAP replay、独立数值/Zarr/恢复审计；未部署采集机、未登录
> 板卡、未启动 Vivado、未执行 60 s 实机烟雾采集

## 1. 结论

步骤 3 已完成，可以进入[步骤 4](35_04_s0_60s_smoke.md)。同一份已保存的生产 320 MS/s
SPEC PCAP 已分别驱动 10/20/50/100 ms 四个独立累加器；2 s 正式区间覆盖
`16 block × 8 ADC × 4096 bin`、每个 block 156,250 帧，并实际跨越 Zarr 时间 chunk。

独立 Python 标准库 oracle 对四种原生 `mean_P` 共 11,796,480 个值逐一复算，全部位于注册
容差内，其中实测绝对误差均为 0。10 ms 按真实 `N_valid` 加权合并到 20/50/100 ms 的
5,242,880 个比较全部通过，最大绝对/相对误差分别为 `9.095e-13 / 4.213e-16`。100 ms
`mean_I/mean_Q/clip/N_valid` 与整数 oracle 一致；`M2_P` 最大相对误差为 `2.346e-14`。

本步不选择正式原生桶。本开发机的 CPU-paced replay 只有实时输入的约 `0.286–0.289×`，且
没有 NIC/ring/磁盘实时竞争；这个数值既不能证明采集机可承受 10 ms，也不能据此把 10 ms
降级。10 ms、20 ms fallback 与 writer 余量仍由步骤 4 在唯一生产消费者上实测决定。

## 2. 输入身份与 replay 变换

权威输入位于采集机 `192.168.100.162`：

```text
/home/astrolab/demo-ant/build/receiver/latest/evidence/
  performance_evaluation/stability_320msps/raw/begin/spec_4308_4323.pcap
SHA-256 d0a05961ecb104a270bb07e58f1602a102676386cce26787c92509f1c89a7653
bytes   4,289,560
```

输入包含 512 个通过协议校验的 SPEC 包，每个 block 恰好 32 包，block-local 连续性检查
496/496 通过；身份为 board 1、product `0xf101`、320 MHz sample clock、4096-channel 8-tap
PFB、`fft_shift=1366`。原始 PCAP 是 16 个 block 各自的 32-frame 窗口，不存在一个共同的
32-frame 全频谱交集，因此本报告不把它误写成 32 幅同步完整频谱。

replay 保留全部 512 个 IQ16 数据体字节，按 block 重复各自 32-frame 序列，只改写
`sample0/frame_id/seq_no`，形成共同的 4096-tick 谱帧轴。四种模式的正式起点统一为 replay
origin 后 100 ms，正式长度统一为 2 s。源数据的 block-local `spec_half_band` 和动态
`spec_status_flags` 原样保留；本地临时 PCAP 副本在验签和摘要完成后已删除。

实现与复读入口：

- Rust replay 驱动：[t510_stage35_replay.rs](../../rust/t510_time_rx/src/bin/t510_measurement_replay.rs)
- 独立整数/Zarr oracle：[t510_stage35_replay_validate.py](../../scripts/stage-35/t510_stage35_replay_validate.py)
- 第三方 Zarr 互操作：[t510_stage35_zarr_interop.py](../../scripts/stage-35/t510_stage35_zarr_interop.py)
- 中断审计：[t510_stage35_recovery_audit.py](../../scripts/stage-35/t510_stage35_recovery_audit.py)
- 生产 PFB 白噪声模型：[t510_stage35_pfb_white_model.py](../../scripts/stage-35/t510_stage35_pfb_white_model.py)

## 3. 合成矩阵与桶边界

Rust 回归新增一个直接作用于真实 `BucketAccumulator/CoarseAccumulator` 的合成族测试，逐个
case 同时比较整数/两遍 oracle 和不规则分段 Chan 合并：

| case | 注入内容 | 核对结果 |
|---|---|---|
| deterministic white | 固定种子 IQ16 伪白噪声 | mean、M2、I/Q sum、clip、merge 全通过 |
| 1/f-like | 四个倍频周期的低频加权和 | 同上 |
| slow gain drift | 白噪声乘 0.75→1.25 线性增益 | 同上 |
| boundary pulse | 脉冲放在首尾及不规则分段边界 | 未漏计、未重复 |
| coherent tone | 17-frame 周期复单音 | mean/M2/merge 通过 |
| equivalent 8-tap overlap | 8-tap 重叠白噪声序列 | oracle/merge 通过，lag-1 为正 |

四种桶宽另对 start lead `1..13` 逐一验证一秒计数恒为 78,125 帧；10 ms 的 781/782 模式、
非整数谱帧边界和 `sample0` wrap 均通过。最终 2 s replay 中，10 ms 主数组 shape 为
`[200,8,4096]`、chunk 为 `[100,8,256]`；100 ms moment shape 为 `[20,8,4096]`、chunk 为
`[10,8,256]`，两层都真实写入并复读两个时间 chunk。

## 4. 四粒度数值结果

### 4.1 原生桶与计数守恒

| 原生桶 | 原生质量行 | 每 block 有效帧 | oracle 比较数 | 最大绝对误差 | gap/arrival |
|---:|---:|---:|---:|---:|---:|
| 10 ms | 3,200 | 156,250 | 6,553,600 | 0 | 0/0 |
| 20 ms | 1,600 | 156,250 | 3,276,800 | 0 | 0/0 |
| 50 ms | 640 | 156,250 | 1,310,720 | 0 | 0/0 |
| 100 ms | 320 | 156,250 | 655,360 | 0 | 0/0 |

每种模式另有 320 行 100 ms 质量记录。所有 nominal 桶的 `expected_frames=N_valid`、
`missing=duplicate=reordered=late=0`；各 block 的 `N_valid` 总和都与输入正式 frame/group 数
一致，没有抽 bin、stride、填零或隐藏排除。

### 4.2 10 ms 加权合并

| 目标桶 | 比较数 | 最大绝对误差 | 最大相对误差 | 注册容差 `rtol/atol` |
|---:|---:|---:|---:|---:|
| 20 ms | 3,276,800 | `9.095e-13` | `2.219e-16` | `2e-13 / 1e-8` |
| 50 ms | 1,310,720 | `2.842e-14` | `4.213e-16` | `2e-13 / 1e-8` |
| 100 ms | 655,360 | `2.842e-14` | `2.213e-16` | `2e-13 / 1e-8` |

100 ms moment 的跨模式比较另覆盖每个浮点/计数字段：`mean_I`、`mean_Q`、clip 和
`N_valid` 最大误差为 0；`M2_P` 1,966,080 次比较的最大相对误差为 `1.256e-14`。

## 5. 故障、缺桶与恢复

独立 `fault_injection_100ms` 数据集验证了以下事实：

- block 0 bucket 0 的 `delta,+2,+1,+1` 序列只累计 3 帧，记录
  `reordered_count=1`、`duplicate_count=1`，重复帧未进入科学统计；
- 已关闭 bucket 0 后注入一个从未接收过的旧 group，append-only ledger 明确记录
  `kind=late`；
- block 1 bucket 5 整桶缺失，Zarr 浮点值为 NaN、`N_valid=0`，没有功率零填充；
- 159 个 gap range 全部进入账本，故障数据集仍以 `complete=true` 封存；
- 显式 stop 数据集以 `complete=false`、固定失败原因和 23 个已验签文件封存。

执行过程真实暴露并修复了两个回归缺口：

1. `spec_half_band` 是 block 0–7/8–15 不同的路由元数据，不能作为全观测恒定身份；原错误
   guard 在首个 block 8 包处正确失败，现已从全局身份字段移除，同时保留其余 product/scale/
   sync 身份冻结。
2. replay 驱动原先在控制状态先变为 failed 时就退出，没有继续等待 writer finalizer；现改为
   `failed && !is_active()` 后才返回，显式 stop manifest 已稳定生成。

两次修复前的真实未封存目录分别由恢复工具只读核对 18 个 journal commit，并生成外置
`SEALED_INCOMPLETE` seal；没有续写或提升为完成数据集。两次中断都发生在原子 rename 之间，
残留 `.partial` 实测为 0，这一“无残留”事实连同完整文件树 SHA 已写入 seal，而不是人为制造
`.partial`。最终六个 scan 的 manifest 共核对 1,020 个 journal entry/1,050 个 manifest file
record，所有长度与 SHA-256 通过，残留 `.partial=0`。

## 6. PFB 微秒相关基线

生产系数等价模型按 RTL 同一 sinc×Hamming、逐 phase 归一化和 18-bit 量化规则生成
`8×4096=32,768` 个系数。所有 phase 的整数和精确为 131,072，按硬件 tap-major 小端顺序得到
CRC32 `0xb9ba227c`，与生产 profile `0x34a80001` 完全一致。

对 proper-complex 白噪声，模型使用
`rho_l=sum(c[t]c[t+l])/sum(c[t]^2)`，功率相关为 `|rho_l|²`：

| lag | 时间 | 复电压相关 | 功率相关 |
|---:|---:|---:|---:|
| 1 | 12.8 µs | `+0.0974334` | `9.4933e-3` |
| 2 | 25.6 µs | `-0.0702129` | `4.9298e-3` |
| 3 | 38.4 µs | `+0.0372847` | `1.3901e-3` |
| 4 | 51.2 µs | `-0.0158873` | `2.5241e-4` |
| 5 | 64.0 µs | `+0.00297335` | `8.8408e-6` |
| 6 | 76.8 µs | `-0.000543197` | `2.9506e-7` |
| 7 | 89.6 µs | `+0.0000627270` | `3.9347e-9` |

这是使用 bit-exact 原型系数的未饱和白噪声等价基线，不包含最终 IQ16 舍入/饱和。真实短 PCAP
的 32-frame、逐 cell 去均值 pooled Pearson 参考为 lag 1–8
`[-0.01236,-0.03244,-0.00716,-0.05102,-0.03302,-0.02651,-0.05078,-0.02043]`；它来自有色、
有限长度的实际 fixture，不能拿来代替白噪声理论值或外推正式 50 Ω 扫描。

## 7. 互操作与性能事实

独立 Python `zarr 3.3.0 / numpy 2.5.2` 打开 6 个 scan 的 42 个数组，实际物化
25,566,720 个逻辑元素、191,395,840 bytes；shape、chunk、dtype、有限值/NaN 和逻辑 C-order
hash 均已保存。Zarr 对根目录 JSON/JSONL sidecar 发出“非 hierarchy component”提示，数组
复读不受影响；这些 sidecar 本来就由 dataset manifest 管理。

| 桶宽 | 2 s replay 用时 | 逻辑 payload 速率 | realtime factor | writer queue high-water |
|---:|---:|---:|---:|---:|
| 10 ms | 7.000 s | 2.971 GB/s | 0.2857× | 116/2048 |
| 20 ms | 6.933 s | 3.000 GB/s | 0.2885× | 40/2048 |
| 50 ms | 6.946 s | 2.994 GB/s | 0.2879× | 15/2048 |
| 100 ms | 6.920 s | 3.006 GB/s | 0.2890× | 12/2048 |

每个 nominal run 的正式输入均为 2,500,000 包、20.8 GB 逻辑 UDP payload；队列没有溢出，
但 CPU-paced replay 没有模拟生产 NIC 的并发到达，因此这张表只描述开发机回放成本。

## 8. 回归、证据与数据边界

最终执行：

```text
cargo test --all-targets   -> lib 20/20 + main 41/41 = 61/61 PASS
cargo build --release --bin t510_stage35_replay -> PASS
cargo clippy --all-targets -> exit 0；仅仓库既有 lib.rs/main.rs lint
Python py_compile          -> 6 个 Stage 35 验证/证据脚本 PASS
```

长期保留的紧凑证据位于
`build/host/latest/evidence/stage35_replay_validation_summary/`：34 个 manifest/摘要文件，
407,902 bytes，canonical tree SHA-256
`aaf446c5d4ff7589bea029fc9238112660a631bfab91e1c00d1ec7be0d0665a4`。入口为
[compact_evidence_index.json](../../build/host/latest/evidence/stage35_replay_validation_summary/compact_evidence_index.json)。

紧凑包保留四粒度运行摘要、全 oracle、第三方互操作、PFB 模型、两个恢复 seal、最终完整文件
manifest，以及六个数据集各自的 request/capture-start/manifest/SHA。开发机最终轮生成的约
182 MB 临时 Zarr、各轮被替代的 replay 输出、临时第三方依赖和 PCAP 副本已删除；权威 PCAP 原件仍
只在采集机。删除的是本步创建且已由紧凑包验签的临时派生物，长期摘要不能恢复被删除的 Zarr
数值块，但可验证当时完整复读的身份与结果。

## 9. 下一动作

进入步骤 4，在采集机唯一 receiver 上执行 60 s 全频段烟雾采集，实测 NIC/ring/application
drop、16-block `N_valid`、writer queue high-water、磁盘吞吐、chunk/manifest 完整性和第三方
复读。只有 10 ms 在该门禁中无损且有合理余量，才能冻结为正式原生桶；否则按 20→50→100 ms
顺序记录证据后选择 fallback。步骤 4 仍只是数据完整性验证，不输出科学“通过率”。
