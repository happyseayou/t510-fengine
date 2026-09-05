# Stage 35 步骤 7：全量自相关与时间噪声分析

> 状态：`COMPLETE`
> 前置条件：[步骤 6](35_06_s2_50ohm_spec_baseline.md)的数据与质量账本完整

## 1. 本步目标

对 `scan_id × tuning_id × adc_id(0..7) × global_bin(0..4095)` 的每个组合计算绝对仪器
单位结果，不用 ADC 平均、代表 bin 或 pass/fail 比例替代逐项数据。

## 2. 必需分析

- 全频带 mean I/Q、RMS、mean power、count²/Hz、分位数和绝对 min/max；
- 2/4/15/30 s 的绝对积分序列、散布、MAD、置信区间和局部缩放斜率；
- 理论 ENBW、实际 PFB 模拟和短滞后协方差三种白噪声参考；
- overlapping/non-overlapping Allan variance/deviation；
- 0–15 s 自协方差/ACF、temporal PSD，15–30 s 只作补充；
- 分布、spectral kurtosis、I/Q 偏置、削顶、突发和数据质量事实；
- 原始、减常数、温度回归三种明确标记版本，原始结果始终优先；
- 三次扫描复现性和 block bootstrap，不破坏时间结构。

## 3. 单位与限制

只报告 ADU、F-engine count、count²/channel、count²/Hz、count⁴ 等当前可溯源单位。未完成
步骤 10 前，不报告 K、Jy、SEFD、连接器 dBm 或 `T_sys`。所有统计使用完整有效桶；缺失
按质量表和曝光处理，不填零、不默认插值、不默认 mask/去趋势。

## 4. 产物与完成条件

- 权威 Parquet 指标表、分析配置、代码 commit 和复现日志；
- 每个 ADC/bin 的必需数值和不确定度；
- 数据质量、mask、回归和 bootstrap 参数；
- 与输入 Zarr/manifest 的可追溯关系。

全量表和关键交叉核对完成后，进入[步骤 8](35_08_self_contained_html_report.md)。

## 5. 执行记录

### 5.1 冻结输入

步骤7只读使用步骤6的r4正式数据，不再操作板卡：

```text
queue_id:       stage35-s2-50ohm-baseline-r4-20260831-1915
queue_manifest: bb88abf0ae63b70d5bae33f2a21f8308fe1bceabc829ce0c3104c1b62ce6a6ef
SPEC scans:     A/B/C × 900 s
TIME controls:  A/B/C × pre/post × 30 s
```

三次SPEC manifest分别为：

```text
A e109b5bcc5cee4ebdaf031b1575e917b9efa8a30dedad14b1844cb4628bebf45
B eed571bf5258ebfde973fe08270394af78650bed5644cca981327c2bf9fc0a49
C f522c60b1904b76c59c2c36410c8cf8f53b30c504cb30b236bd8bd687ee795bf
```

每次SPEC的`mean_power_count2`为`[90000,8,4096]`、10 ms原生桶；I/Q均值、功率M2和clip
为`[9000,8,4096]`、100 ms矩数组。每次manifest含100,823个文件、约32.32 GB，三次合计
约96.97 GB。全部输入已在步骤6独立复读和质量门禁中验证，无缺帧、重复、乱序或迟到。

采集机当前约93 GiB可用内存、3.3 TiB可用磁盘，但未安装NumPy/Parquet运行时。分析实现
因此固定按原生256-bin block分块读取，在独立冻结环境中生成Parquet，禁止一次性物化三次
全带数据或修改输入Zarr。

### 5.2 分块分析实现与烟雾验证

新增`scripts/stage-35/t510_stage35_s2_analyze.py`，SHA-256为
`3f3262ea27310ebaeedf297b50893c3b103bd684027da2cd2c2a2b38c0e7ad04`；冻结配置
`scripts/stage-35/config/stage35_s2_analysis_v1.json`的SHA-256为
`6f8d7c61908161c68c3e75a4e7c81a531ecbc85d28ebcb1c627a2a09385a45e1`。分析器对每个
`scan × 256-bin block`独立完成：

- 10 ms功率的绝对水平、分位数、极值和完整2/4/15/30 s非重叠序列；
- ENBW理论、精确量化8-tap PFB模型和10 ms短滞后协方差三种绝对散布参考；
- 0–15 s注册lag的自协方差/ACF、12个tau的overlapping/non-overlapping Allan量；
- 100 Hz原生功率序列的2,048点Hann Welch PSD，保留0–50 Hz原始频率轴；
- 原始、减扫描常数和板上PL温度线性回归三种显式版本；
- 保持时间顺序的circular block bootstrap，block长度由该block全ADC/bin的实测ACF
  首个非正lag的95百分位确定并记录；
- 100 ms I/Q矩、frame-level功率M2、spectral kurtosis、clip和事实质量标签。

PFB白噪声模型重新生成并核对生产系数CRC `0xb9ba227c`。隔离运行时位于采集机Stage 35
control目录，固定Python 3.12.3、NumPy 2.5.2和PyArrow 25.0.1，不修改系统Python。

A/block00实数烟雾在59.22 s内完成，峰值RSS约11.52 GiB、约10核CPU；输出2,048行、50个
基础字段和24个时间字段且无null。2/4/15/30 s序列长度分别为450/225/60/30；随机抽取的
mean power直接从原Zarr按`n_valid`重算，与Parquet值位级一致。每行ACF、Allan和PSD长度
分别为27、12和1,025；分析保持10 ms原生输入，没有频率平均或代表bin替代。

### 5.3 正式全量队列

2026-08-31 21:21 CST一次性提交48项完整离线分析队列：

```text
unit:   t510-stage35-s2-analysis-v1-20260831-2059.service
root:   /var/lib/t510/stage35/analysis/stage35-s2-r4-analysis-v1-20260831-2059
tasks:  A/B/C × block00..15
workers: 2
```

10 s与20 s健康检查时unit均为active/running，analysis state为running、error null，48项已
全部登记；A/block00和A/block01 running，其余46项pending。双worker合计使用约24 GiB峰值
内存预算，健康检查时仍有约81 GiB available。全部block成功后同一队列会自动生成六组TIME
控制表、A/B/C跨扫描复现性表、summary和逐文件SHA-256 manifest；任一block失败则状态改为
failed并保留现场。确认完整队列健康后已停止轮询，不能把烟雾或首批block写成步骤7完成。

### 5.4 最终验收

原队列于2026-09-01 04:43:38 CST正常结束，systemd记录`Result=success`、
`ExecMainStatus=0`，`analysis_state.json`记录`status=completed`、`error=null`，48/48个
`scan × block`任务全部完成。正式产物为：

```text
metric rows:       98,304  (A/B/C × ADC0..7 × 4096 bins)
cross-scan rows:   32,768  (ADC0..7 × 4096 bins)
TIME control rows: 48      (6 pre/post controls × ADC0..7)
payload files:     360
payload bytes:     2,313,447,532
```

独立复算`analysis_manifest.json`自身SHA-256为
`d999cad943cacecfeb19dceb6f91751390a2097f60f104e8524ecbb4e06b7b09`，与
`analysis_manifest.sha256`一致；清单中361个条目逐文件重算均匹配，无缺失和错码。
分析摘要状态为`PASS`，全频带行身份、单位、ACF/Allan/PSD网格和2/4/15/30 s
积分网格均完整。本步据此闭合；K、Jy、SEFD、连接器dBm和`T_sys`仍未定标，
不在本步产物中声称。
