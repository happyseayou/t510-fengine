# Stage 33：ADC/DAC 3.84 GS/s 与第一 Nyquist 完整频带

## 当前状态

`IMPLEMENTED / OFFLINE_PASS / FULL_CHAIN_SUBMITTED / BOARD_PENDING`

Stage 33 是当前 `demo-ant.xpr` 对 Stage 32 成果的原位升级，不是独立工程。Stage 32
已经闭合的数据面——ADC adapter、160/320 MS/s选择器、1024-bit science bus、
4-tap PFB、TIME/SPEC CMAC512、调度同步、DAC DDS和Rust接收格式——全部保留；
本阶段把 ADC和DAC模拟采样率提升到3.84 GS/s，使第一 Nyquist区间扩展到
`0..1.92 GHz`。

源码和离线门禁已经完成，清理版已完整提交
`synth_1 -> impl_1 -> write_bitstream` 长任务，当前按长任务规则不轮询。最终
timing/DRC/bitstream、MTS、射频、生产矩阵和热稳定性尚未验收，因此不能标记为
发布 PASS。

## 冻结硬件合同

- `CORE_VERSION=0x00010033`，当前 RTL 无 `T510_STAGE*` 条件编译分支。
- 四个 ADC tile和四个 DAC tile全部为 `3.84 GS/s`。
- 八个物理 ADC converter：12x decimation、R2C fine mixer、dither enabled、
  Nyquist zone 1；RFDC metadata对应16条 derived R2C AXIS路径。
- 八路 DAC：12x interpolation、C2R fine mixer、Nyquist zone 1。
- RFDC复基带保持 `320 MS/s`；ADC/DAC AXIS保持 `80 MHz`，ADC width=4、
  DAC width=8。
- 时钟序列保持160 MHz RFDC reference和10 MHz continuous SYSREF，不修改寄存器
  顺序。
- ADC NCO=`-center`，DAC NCO=`+center`；自定义 DAC DDS输入率仍为320 MS/s。
- `sample0` 继续以320 MS/s复基带时基解释，不能按3.84 GHz模拟采样率解释。

生成的当前 RFDC 合同已通过 XCI/HWH 检查：

- RFDC XCI SHA-256：
  `3bc3b81a2d73cd3b8e968e385804556cb203def6adc5ac3b3a09dbb58ede2908`
- HWH SHA-256：
  `b7706b3e7d62be147b1962487ff0144dcad2e2ea61d31fef27f31c65b69eaefd`

## 第一 Nyquist 频率合同

| 复采样模式 | center范围 | 允许输出模式 | 单路DAC/期望RF带内约束 |
| ---: | ---: | --- | --- |
| 160 MS/s | `80 <= center_mhz <= 1840` | TIME_ONLY、SPEC_ONLY、TIME_SPEC | `center +/- 80 MHz` |
| 320 MS/s | `160 <= center_mhz <= 1760` | TIME_ONLY、SPEC_ONLY | `center +/- 160 MHz` |

每路 DAC/期望 RF信号还必须满足 `1 <= rf_frequency_mhz < 1920`；1920 MHz上边界
明确排除。`/api/v2/dac` 的 `center_mhz` 必须与当前八路 RFDC DAC mixer readback
一致，否则返回 HTTP 409，不能只改变 DDS计算基准。默认示例为
`center=200 MHz`、tone=`200.010 MHz`；`320 MS/s + center=100 MHz`必须拒绝。

## 当前控制面与接收合同

- Board Agent只提供 `/api/v2/*`；旧 `/api/v1/*` 返回404。
- 配置字段使用 `sample_rate_msps`；状态字段使用
  `selected_sample_rate_msps`、`detected_sample_rate_msps`、
  `rfdc_complex_sample_rate_hz` 和 `mts_result_id`。
- Python公共入口为 `python.t510_control.FEngineController` 和
  `python.t510_console.create_console`。
- Rust receiver只接受当前4096-channel SPEC：
  `16 blocks x 256 channels x 1 time x 8 inputs x IQ16`，并要求
  `PFB taps>=4`；CLI使用 `--initial-sample-rate-msps`。
- TIME/SPEC均为128-byte T510 header加8192-byte payload，UDP payload共8320
  byte；端口、包率和二进制布局保持现有数据面不变。
- 完整线格式见 `../../docs/t510_udp_payload_v2.md`。

## 构建与发布方式

- 只在现有 `demo-ant.xpr` 中运行 `synth_1/impl_1`，不得创建第二个工程。
- `scripts/build_stage33.tcl`负责当前工程源集、BD和构建断言。
- 长任务成功后，由 `scripts/export_stage33_current_project.tcl`导出唯一候选，
  `scripts/build_stage33.sh`复核 XCI/HWH和 SHA。
- `config/stage33/config.example.json`在 MTS discovery/fixed完成前保持故障关闭：
  SHA占位、target无效、campaign proof为空。
- 发布脚本只从 catalog读取唯一 bitstream SHA，不维护第二份手写 SHA。
- 当前不保留 Stage 31/32 rollback或清理前 Stage 33 build；`build/`已清空，成功后
  只生成最新 Stage 33候选。

## 已通过的离线门禁

| 门禁 | 结果 |
| --- | --- |
| Python单元测试 | PASS，84 tests |
| Board Agent Cargo tests | PASS，7 tests |
| Time receiver Cargo tests | PASS，37 tests |
| Web数学测试 | PASS |
| 当前完整XSim回归 | PASS，18 testbenches |
| 仓库卫生检查 | PASS |
| `git diff --check` | PASS |
| `validate_bd_design` | PASS |
| RFDC XCI/HWH 3.84G/12x/80MHz合同 | PASS |

长任务提交身份与检查项见
`../vivado/stage33/latest_only_build_submission_20260803.md`；仓库清理详情见
`../maintenance/stage33_latest_only_cleanup.md`。

## 尚待硬门禁

1. 长任务完成后只检查一次结果：synth、impl和write_bitstream必须全部成功；设计
   fully routed，WNS/WHS均不小于0，DRC通过。
2. 导出清理版唯一候选，记录最终 bitstream SHA并再次核对 RFDC XCI/HWH。
3. MTS discovery执行20次 RFDC reset、10次 overlay reload、10次 LMK reload；
   ADC target取观测最大值+20，DAC target取最大值+16。
4. 固定 target后重复同样40周期，要求40/40通过，ADC/DAC latency和offset向量
   全部可重复。
5. 八路闭环覆盖 center=200/960/1760 MHz及约1.90 GHz，复测低/中/高/1.90 GHz
   DAC纯度。
6. 完成5项60秒生产回归、3项10分钟 soak、冷启动/服务恢复和60分钟全 DAC热稳。

所有板端新证据由脚本重新创建 `reports/board/` 并绑定最终 SHA。清理前候选和
Stage 32报告不能替代上述任何门禁；物理门禁通过前不提升顶层 `overlay/`、catalog
或 `latest`。

## 非目标

- 不实施 `for_me.md` 后续的 +/-8192 ADU限幅。
- 不执行完整 bandpass扫频或通道平坦度验收，仅执行计划中的离散频点门禁。
- 本阶段保持单板发布范围；第二块物理板可用后再验收多板相位同步。
- 不修改1024-bit science bus、PFB规格、TIME/SPEC产品语义或UDP字节布局。
