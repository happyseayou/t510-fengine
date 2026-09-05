# Stage 34c-1：OCB1动态—锁定—恢复可逆因果实验

## 状态与进入条件

当前状态：`COMPLETE / OPERATIONAL_PASS / INCONCLUSIVE_BASELINE_NOT_REPRODUCED`。

只有Stage 34c-0在共享50 Ω参考下仍复现时间相关噪声，才自动进入本阶段。若34c-0已经恢复
`1/sqrt(N)`，本阶段不执行，避免为已经被物理输入状态解释的现象额外改动RFDC校准。

## 唯一主动变量

Board Agent在现有RFDC CFFI层加入`XRFdc_SetCalCoefficients`和
`XRFdc_DisableCoefficientsOverride`，并提供：

- `GET /api/v2/rfdc/calibration/ocb1`
- `POST /api/v2/rfdc/calibration/ocb1/snapshot-override`
- `POST /api/v2/rfdc/calibration/ocb1/release`

snapshot在停流、receiver不接收、sync未prepare/arm、DAC全静音、freeze mask=0时读取八路
OCB1，把每路刚读出的同一组值只写回一次并逐路bit-exact回读。它不搜索新系数、不循环
追踪写入。B条件只锁定OCB1；OCB2、GCB、TSCB继续动态，freeze mask必须保持0，从而保证
唯一主动变量是OCB1。

事务由一次性`ocb1_transaction_id`和系数SHA256绑定。override启用后，START或scheduled
START缺少匹配事务ID会被拒绝；CONFIGURE、reset、overlay/LMK reload、MTS变化或Board
Agent重启都会使事务失效。release后进入`RECONFIGURE_REQUIRED`，只有完整
CONFIGURE/MTS才回到`DYNAMIC`。部分写入、回读或回滚失败会锁存故障并禁止START。

状态同时提供八路原始u32、8个有符号16-bit系数及交织DFT `k=1..4`，以便直接对照
960 MHz固定项。该override仅用于因果诊断，不是产品校准流程。

## A1/B/A2矩阵

160和320 MS/s各执行三组固定triplet，总计18次600秒：

1. `A1_DYNAMIC`：fresh CONFIGURE/MTS，OCB1动态；
2. `B_OCB1_SNAPSHOT`：与A1共享同一次RFDC配置，只在两者之间停流并锁定当前OCB1；
3. `A2_RESTORED`：release后fresh CONFIGURE/MTS，确认回到动态OCB1。

速率顺序固定为`r1:160→320，r2:320→160，r3:160→320`。原2.0 °C温度跨度继续标记
`WARNING_OVER_ORIGINAL_2C_LIMIT`；用户确认房间空调关闭造成共同缓慢升温后，硬停止线最小
放宽至2.5 °C。旧t03的A1/B与升温后的A2不混用，完整归档后从A1/B/A2整组重做。B期间
OCB1哈希必须唯一且固定，A1/A2期间必须持续变化；GCB/TSCB freeze mask始终为0。

`OCB1_CAUSAL_ADC0_ADC2`要求两种速率下A1复现、B绝对门禁通过、合格比例提高至少50个
百分点、`|slope+0.5|`中位误差改善至少0.12、`|lag-1|`下降至少0.10，同时A2重新恶化
并在斜率和lag上回到A1的±0.10范围。否则只按证据分类为
`OCB1_FIXED_SPUR_ONLY`、`OCB1_CONTRIBUTOR`、`OCB1_NOT_CAUSAL_UNDER_SHARED_50OHM`或
`INCONCLUSIVE_BASELINE_NOT_REPRODUCED`；这些科学否定均为正常任务完成。

## 安全与验证

任一drop、gap、backpressure、饱和、overflow、clip、PLL失锁、温度超限或回滚失败会立即
STOP、DAC静音并以运行故障退出。最终必须回到stream停止、receiver不接收、DAC mask=0、
freeze mask=0、OCB1 override mask=0、OCB1=`DYNAMIC`和external-10-MHz continuous LMK
profile，并恢复campaign前的板端与Web配置。

Python全仓150项、receiver Rust 47项、Board Agent Rust 7项已通过。专项测试覆盖packed
系数、SHA/DFT、八路原子写入与部分失败回滚、事务绑定和失效、科学否定零退出、AMS换算、
lane mask、TIME抽样、多worker合并及故障安全收尾。

## 最终结果

18次600秒A1/B/A2 run全部完成，任务错误列表为空，所有数字完整性与安全收尾门禁通过。
三次重复汇总如下：

| 速率 | 条件 | 中位积分斜率 | 中位绝对lag-1 | 合格组合 |
|---:|---|---:|---:|---:|
| 160 MS/s | A1动态 | -0.297 | 0.360 | 6/30 |
| 160 MS/s | B锁定OCB1 | -0.216 | 0.551 | 2/30 |
| 160 MS/s | A2恢复 | -0.344 | 0.370 | 14/30 |
| 320 MS/s | A1动态 | -0.281 | 0.431 | 9/30 |
| 320 MS/s | B锁定OCB1 | -0.197 | 0.551 | 0/30 |
| 320 MS/s | A2恢复 | -0.235 | 0.429 | 3/30 |

A1严格严重度门禁没有再次达到预注册的“基线复现”阈值，因此分类保持
`INCONCLUSIVE_BASELINE_NOT_REPRODUCED`，不能把OCB1正式定责。与此同时，B在两种速率下
均比A1更差，且A2回到A1附近，足以否定“锁定当前OCB1即可修复长积分”的工程路线。

固定证据目录共保存109张图，跨条件总览为
`build/receiver/latest/evidence/adc_correlated_noise_root_cause/plots/stage34c_ocb1_condition_summary.png`。
