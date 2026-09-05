# Stage 35 步骤 2：S0 全频段累加器与 writer 实现

> 日期：2026-08-30
> 状态：`COMPLETE / PACKET_REPLAY_AND_BOARD_SMOKE_NOT_RUN`
> 前置报告：[步骤 1 设计审查](35_01_s0_design_review.md)
> 代码身份：当前工作树，尚未提交 commit
> 范围：Rust receiver、单元/互操作测试和格式文档；未部署采集机、未登录板卡、未启动
> Vivado、未执行 packet replay 或正式采集

## 1. 结论

步骤 2 的实现范围已完成，可以进入[步骤 3 合成数据与 packet replay 验证](35_03_s0_replay_validation.md)。
现有 receiver 的唯一 SPEC 消费路径已经具备 8×4096 全频段自相关累加、10/20/50/100 ms
`sample0` 分桶、100 ms 可合并 moment、有界异步 writer、Zarr v2 落盘和完整质量账本。

本步只证明实现、普通回归和文件格式互操作正确，不证明 10 ms 能承受生产全速流量。10 ms
是否成为正式原生桶，仍由步骤 3 replay 和步骤 4 板上 60 s 烟雾采集共同决定。

## 2. 实现位置与数据路径

- 新模块：`rust/t510_time_rx/src/stage35.rs`。
- receiver 接入和 HTTP 控制面：`rust/t510_time_rx/src/main.rs`。
- 线格式和落盘合同：`docs/t510_udp_payload_v2.md`。

数据路径保持为：

```text
已有 AF_PACKET/PACKET_FANOUT 唯一消费者
  -> 既有 SPEC 快速解析和合同校验
  -> worker-local Stage35 block accumulator
  -> 容量 2048 的 try_send 队列
  -> 单独 Zarr writer
  -> 既有网页 preview
```

没有新建 UDP socket、第二个接收进程或中央完整频谱互斥锁。普通 receiver 和 fanout worker
都在 SPEC 包校验后、preview 之前调用同一个控制器；扫描未武装时只有一次 atomic active
检查。

## 3. 已实现合同

### 3.1 分桶、连续性和身份

- 只接受 320 MS/s、4096 通道、16×256 block、8 input、IQ16、8-tap PFB active 产品。
- block 0 的首个有效包建立共同 origin，正式开始边界预留两个完整原生桶；开始、归桶和结束
  都由 `sample0` 决定，主机 watchdog 只负责失败保护。
- 原生桶支持 10/20/50/100 ms；10 ms 的 781/782 帧自然交替按整数边界计算并保存真实计数。
- 每 block 使用 8-group 有界重排窗；duplicate、reordered、late 和 gap 均显式记录，gap 同时
  保存 group 与 `sample0` 范围；end 后再观察 8 个谱帧组才封口，使最后一个桶同样受重排窗
  保护。
- 已经提交逐桶质量行后才到达的 duplicate/late 包写入只追加的
  `arrival_events.jsonl`，不丢弃也不回写已提交记录。
- 原生和 100 ms 质量行保存桶内 `spec_status_flags_or`，使 PFB/XFFT 运行状态能够与曝光桶
  对齐审计。
- 首包后冻结 board/product、PFB、FFT shift、scale、sync identity 和 `seq_no-frame_id`
  offset；扫描中身份变化立即失败并封存当前 segment。

### 3.2 数值统计

每个 `block × adc × local_bin` 使用全部 IQ16 样本，不选 bin、不 stride、不采用网页降采样：

- `sum_i/sum_q: i64`、`sum_p: u64`；
- `mean_p/m2_p: f64`，使用 Welford 在线更新；
- 原生桶写精确加宽和归一化得到的 `mean_P`；
- 100 ms 使用 Chan 公式合并原生桶内部 moment，写 `mean_I/mean_Q/M2_P/clip_count`；
- 缺桶绝不填功率零：浮点数组为 NaN，`N_valid=0`，质量行仍保存实际 missing 数。

### 3.3 writer 与恢复

- worker 只对已完成桶执行 `try_send`；队列满、writer 断开或写入失败会把扫描标为 failed，
  不阻塞收包热路径。
- Zarr chunk 先写 `.partial`，`flush + sync_all` 后原子 rename；每 64 个已提交文件同步
  `chunk_journal.jsonl`。
- 每个扫描目录只能由合法 `scan_id` 新建一次，失败或显式 stop 后不得复用同名目录。
- 正常完成和显式 stop 都生成 `dataset_manifest.json` 与其 SHA-256；失败 manifest 使用
  `complete=false` 并保存原因。
- writer 完成前禁止开始下一扫描，避免旧 finalizer 与新 generation 交叉。

## 4. 控制面

receiver 新增参数：

```text
--stage35-root /var/lib/t510/stage35
```

接口为：

- `POST /api/measure/stage35-autocorrelation`
- `GET /api/measure/stage35-autocorrelation/status`
- `POST /api/measure/stage35-autocorrelation/stop`

示例请求：

```json
{
  "scan_id": "stage35-s0-replay-001",
  "tuning_id": "fc-1020mhz",
  "duration_seconds": 60,
  "native_bucket_ms": 10,
  "sample_rate_msps": 320,
  "center_mhz": 1020.0,
  "metadata": {
    "clock_reference": "onboard_tcxo",
    "input_state": "8x50ohm"
  }
}
```

启动前同时检查 receiver 为 `spec_only`、采样率和中心频率与请求一致。新的全频段采集与既有
稀疏 `spec-stability` monitor 互斥，避免两套科学统计同时争用计算资源；采集 active/draining
期间 receiver 配置冻结，防止中心频率、模式或显示配置 generation 在 segment 内漂移。

## 5. Zarr v2 数据集

| 数组 | dtype | shape | 首选 chunk |
|---|---|---|---|
| `mean_power_count2` | `<f8` | `[T_native, 8, 4096]` | `[100, 8, 256]` |
| `n_valid` | `<u4` | `[T_native, 16]` | `[100, 1]` |
| `mean_i_count_100ms` | `<f8` | `[T_100ms, 8, 4096]` | `[10, 8, 256]` |
| `mean_q_count_100ms` | `<f8` | 同上 | `[10, 8, 256]` |
| `m2_power_count4_100ms` | `<f8` | 同上 | `[10, 8, 256]` |
| `clip_count_100ms` | `<u4` | 同上 | `[10, 8, 256]` |
| `n_valid_100ms` | `<u4` | `[T_100ms, 16]` | `[10, 1]` |

短扫描的时间 chunk 自动缩小到数组长度。随附文件包括
`observation_request.json`、`capture_start.json`、两个 bucket quality JSONL、
`gap_ranges.jsonl`、`arrival_events.jsonl`、chunk journal 和最终 manifest。

容量继续采用步骤 1 的无压缩最坏预算：10 ms A+B 层约 35.4 MB/s、15 min 约
31.85 GB；三次扫描不含 C 层约 95.55 GB，正式前至少准备 120 GB。该数值是静态预算，
不是本机或板端吞吐实测。

## 6. 验证证据

### 6.1 Rust 回归与构建

在 `rust/t510_time_rx` 执行：

```text
cargo fmt -- --check
cargo test
cargo clippy --all-targets
cargo build --release
```

结果：

- `cargo test`：lib 8/8、binary 52/52，共 60/60 通过；doc-test 0。
- `cargo build --release`：通过。
- `cargo clippy --all-targets`：退出码 0；`stage35.rs` 无 warning。输出中的 32 个 warning
  行来自仓库既有 `lib.rs/main.rs` lint，包含不同 target 的重复项，本步未扩大修改范围处理。
- `cargo fmt -- --check`：通过。

新增测试覆盖四种桶宽、781/782 模式与 wrap、常数、IQ16 极值、伪噪声、强直流小方差、
Welford/Chan 对照、跨桶、缺桶、reorder、duplicate、late、gap、NaN/`N_valid=0`、身份漂移、
尾部重排保护、显式中止封存和 scan identity 不复用。

### 6.2 独立 Zarr reader

用测试保留的一秒合成 fixture（100 ms 原生桶，故意令 block 0 缺一个整桶），再用独立
Node reader `zarrita 0.7.4` 打开目录。结果为：

```text
ZARR_INTEROP_OK zarrita=0.7.4 arrays=7 files=135 quality_rows=160
```

独立复读核对了 7 个数组的 shape/dtype、真实 chunk 值、缺桶 NaN、`N_valid=0`、manifest
中 135 个文件的长度与 SHA-256、160 个原生质量行及状态位，以及
`dataset_manifest.sha256`。fixture 和临时 reader 依赖随后已清理，仓库未保存大体积数据。

## 7. 未在本步完成的事项

- 尚未用保存的真实 packet replay 同时运行 10/20/50/100 ms，也未比较 10 ms 离线合并与
  各原生桶结果；属于步骤 3。
- 尚未测量 full-rate CPU、NIC、ring、队列 high-water 和真实磁盘吞吐；属于步骤 3/4。
- 尚未部署采集机、登录板卡或做 60 s 烟雾采集；属于步骤 4。
- 尚未决定正式数据使用 10 ms 还是 fallback；步骤 4 门禁前不得下结论。
- C 层短 PCAP/TIME 片段继续使用 receiver 既有 raw capture，具体 replay fixture 身份在
  步骤 3 登记。

## 8. 下一动作

进入[步骤 3](35_03_s0_replay_validation.md)：冻结同一份合成/真实 replay 输入，分别运行
10/20/50/100 ms，验证全量计数、桶合并、乱序/重复/丢包/wrap、恢复封存以及 CPU/队列余量。
步骤 3 通过前不部署板端正式观测。
