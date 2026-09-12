# Stage 36：三轮 RFDC reset 后背景转移验证

## 固定实验设计

用户授权三轮，沿用已确认八路独立50Ω、TG关闭。每轮：

1. old：重置前60秒，估计旧复背景。
2. 四个ADC tile Reset，原时钟不重写、PL不重新下载；生产prepare/MTS恢复相同配置。
3. new：重置后60秒，估计新复背景。
4. test：540秒独立检验，按九个60秒段比较不扣除、扣旧背景、扣新背景。

共9段1980秒科学数据，三次Reset。不追加轮数，不根据test调参，不写OCB2覆盖。
模板固定60秒、每bin独立复均值；全部28对4096bin原生100ms与派生1s保存。
DSA固定ADC0/2=20dB、其他0dB，DisableRTS等完整字段重置前记录、重置后恢复并验证。
DAC始终静音；显式Reset仅ADC四tile，不Reset DAC。

## 门禁和接续

每一段结束先停流、读取RFDC错误，完成manifest SHA与所有数据块SHA以及独立数值验证，才能进入下一段。
正式采集要求板端/接收端丢包、序号/sample0断点、FIR/FFT、接口与RFDC错误零。
仅在成功Reset/prepare后，允许按既有验证流程记录并清一次历史中断锁存，立即及5秒后核查不复发。
正式采集后的错误不清除、不重试。任何门禁失败停流并保留现场。
三轮全部通过后自动进行全频分钟统计、旧新模板比较并封存；健康启动后遵循AGENTS交还控制权。

板端reset helper复用已验证的init_probe执行路径，只增加完整DSA状态保存恢复与持久边界journal。
新helper只允许probe和ADC，控制器HTTP仅允许START/STOP/DAC静音，禁止旁路CONFIGURE或时钟恢复。

## 判读

固定评分：每分钟各ADC对科学频带bin3072–3328的归一化复残差，保留逐对和整体统计及三个预定频点。
全频old/new模板和九分钟复均值/功率另存NPZ，以便后续独立复查、100ms可视化。
看旧模板是否在Reset后变差、新模板能否重复降低残差，保留没有改善的通道/轮次。
没有预设必须改善的科学门槛，不以低偏置代替Allan或弱信号恢复验收。
新模板距检验较近，旧模板更老；结果需结合此前无Reset有效期实验解释，不作严格随机因果证明。
这里是ADC Reset与必要prepare/MTS的组合，不是整板冷启动，也不能唯一归因于OCB2。

## 实现与提交

- 队列：`scripts/stage-36/t510_stage36_background_reset_queue.py`
- 板端：`scripts/stage-36/t510_stage36_background_reset_probe.py`
- 测试：九段/三Reset边界、完整DSA恢复（含DisableRTS）、DSA漂移与RFDC错误拒绝、禁止全RFDC重置动作通过。
- GB10快照：`/home/astrolab/.cache/t510/stage36-background-reset-20260911/repo/`
- 板端helper与journal：`/home/xilinx/t510-stage36-background-reset/`
- 证据：`/var/lib/t510/measurements/stage36-background-reset-20260911-queue/`
- 提交及源SHA：`build/background-reset-20260911/`

预计含Reset、逐段验证和最终分析约45–60分钟；本段是计划与提交记录，不代表结果通过。

首次提交在预检阶段发现快照缺少 `t510_stage36_tg_clear_errors.py`，未启动任何采集或Reset，安全停流成功。
原失败队列 `stage36-background-reset-20260911` 保留。补全依赖并在提交脚本增加显式依赖存在性断言后，
使用新快照和新证据身份 `stage36-background-reset-20260911-r2` 提交完整九段队列；板端helper路径不变。

完整队列健康启动确认：第一轮old60处于running，ring_drops=0、error=null；余下八段已在同一进程队列中武装。
unit：`t510-stage36-background-reset-20260911-r2.service`；Invocation：`63f742afd7cd4b508147bc01e7d844f6`。
按AGENTS停止轮询并交还控制权，等待用户要求检查最终状态；不把健康启动当成完成。

## r2恢复检查与修复

用户要求检查后发现r2失败：第一轮old60已完成、完整性及数值验证PASS；ADC Reset/prepare/MTS和一次中断基线门禁ok。
进入new60前重复调用prepare，第二次独占创建 `phase_01_receiver_config.json` 抛出FileExistsError。
new60未采集，三轮未完成，没有背景对照结果。停止成功，复查streaming=false、八路DAC关闭。
这是队列编排错误，不是硬件MTS失败。

修复为所有phase只执行一次TGQueue.ensure_mode；new阶段在停止准备后执行Reset，再独立检查身份/DSA与唯一命名的证据。
新增 `t510_stage36_background_reset_selftest.py`，模拟全部九段并使用真实独占文件写入，验证每段一次prepare、
恰三次Reset/中断基线、状态更新、Reset失败不继续，测试PASS。提交脚本强制先运行该测试。

原r2失败证据保留。重新从当前停止状态提交完整三轮，新身份 `stage36-background-reset-20260911-r3`，
unit同名加`t510-`；Invocation `b508cbee76cb4ca5a6c18932757ba7a3`。
r2已发生的一次Reset是失败尝试历史，不计入r3计划的三轮成功实验；不把两次队列拼接成一个实验。

## r3最终结果

用户询问后核查：completed，verification_status=PASS，error=null，耗时约53.9分钟。
九段正式完整性全部ok，九段独立数值验证PASS，段末RFDC错误位均零；三次ADC Reset/MTS与中断基线门禁ok。
queue manifest验SHA，比较结果与以上逐段验证/探针均与封存文件SHA一致。复查已停流，八路DAC关闭。

每轮九个检验分钟的评分中位数（每分钟评分为28对×bin3072–3328的归一化复残差模中位数）：

| 轮次 | 不扣除 % | 扣旧背景 % | 扣新背景 % |
|---|---:|---:|---:|
| 1 | 0.1754 | 0.2270 | 0.1456 |
| 2 | 0.1851 | 0.2612 | 0.1745 |
| 3 | 0.1247 | 0.2709 | 0.1134 |

三轮该汇总指标均显示旧模板比不扣除更差，新模板优于旧模板且小幅优于不扣除。
支持Reset后需要重新验证/估计模板，不能无条件沿用旧背景。尚未逐对审计，不把汇总改善泛化为所有通道/频点。
并非Reset每次必然改变背景的证明；输入参考条件、时间间隔与组合prepare/MTS操作边界仍适用。
本地结果 `build/background-reset-20260911/reset_background_comparison.json`，最终状态 `final-state-r3.json`。

## 逐对分析与可视化

每对每轮以九分钟的频带评分中位数比较：

| 轮次 | 新背景优于不扣除的对数 | 新背景优于旧背景的对数 |
|---|---:|---:|
| 1 | 19/28 | 27/28 |
| 2 | 12/28 | 24/28 |
| 3 | 16/28 | 28/28 |

因此不能把三轮整体改善解释为所有通道对均改善。尤其第二轮仅12对优于不扣除。

代表例子（各对科学频带、九分钟汇总，单位%）：

| ADC对／轮次 | 不扣除 | 扣旧背景 | 扣新背景 |
|---|---:|---:|---:|
| 0/2，第1轮 | 11.888 | 11.604 | 0.372 |
| 0/2，第2轮 | 0.508 | 11.222 | 0.294 |
| 6/7，第2轮 | 6.595 | 6.393 | 0.319 |
| 6/7，第3轮 | 0.636 | 6.225 | 0.227 |
| 4/5，第3轮 | 8.123 | 7.732 | 0.165 |
| 5/7，第2轮 | 0.220 | 0.225 | 0.290 |

这组数据直接展示“旧模板可能把已消失的偏置重新带入残差”；新模板能去掉某些重新出现的强偏置，
但弱背景中估计误差、变化及时间差足以使新模板比不扣除更差。以上为描述统计，无独立性或显著性声明。
当前建议：Reset/prepare后旧模板先失效，使用新参考验证是否需要扣除；不立即为全部对启用自动校正。
按数据逐对挑最小残差的策略还需要独立数据验证，不能在当前test上选完再宣称泛化。

新页面 `http://192.168.100.162:8036/static/background-reset.html`，首页与旧背景实验页均有入口。
每轮5400个原生100ms点，三轮/28对/三个频点可选，三策略幅度、相位与分钟曲线图例联动。
含完整逐对改善/变差表格及逐符号解释；频带汇总表不随单频点选择改变。
原生导出脚本 `scripts/stage-36/t510_stage36_background_reset_export.py`：核验队列/数据manifest与读取块SHA，
逐分钟从原生100ms重算复均值并对照封存NPZ，全部一致。
静态数据目录GB10 `/home/astrolab/.cache/t510/background-reset-web-20260911/`，不改写历史数据。
浏览器验证脚本 `scripts/stage-36/t510_stage36_background_reset_web_verify.py`，在GB10 Chromium中核对16200个幅度/相位值、
27个分钟点、5400点完整性、真实图例点击、三轮叠加及选择器，截图/验证JSON存本地 `build/background-reset-20260911/web-check/`。
