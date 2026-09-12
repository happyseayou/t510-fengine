# Stage 36：共同单音的 ADC 初始化重复性

接续 [首次共同单音测量](36_18_common_tone_capture_plan.md)。用户同意三轮重复，并于 2026-09-11 确认关闭 TG 后开始第一轮。

每轮固定顺序：用户关闭 TG → 四个 ADC tile 各 Reset 一次 → 生产 prepare/MTS → DSA、数字尺度、时钟和停流核验 → 用户开启 TG → 60 s、100 ms 积分采集。
关闭/开启 TG 需要人工操作，不能跨过该步骤自动采集。任一门禁失败停止，不自动重试。
保持原 130.078125 MHz、−20 dBm 设置与 ADC0/2 接线；DSA 两路 20 dB，其他六路 0 dB。
不重置 DAC tile，不重写 LMK 时钟配置，不下载 FPGA；MTS 包括 ADC/DAC 对齐过程。

比较三轮及原 60 s 的 ADC0×conj(ADC2) 复平均、归一化幅度、相位、功率比和 100 ms 波动。
高相关幅度不代表相位可重复。该实验是 ADC 初始化重复性，不等价于整板冷启动，也不证明宽带对齐或弱信号灵敏度。

## 第一轮初始化

- 原接收任务 completed，板上 streaming=false 后才执行。
- 四个 ADC tile 各 Reset 一次，prepare 未追加 tile Reset 或时钟重写。
- MTS ADC latency=[492,492,492,492]、offset=[9,9,9,9]；DAC latency=[72,72,72,72]。
- 重置前、重置后原始读回、重新应用 DSA、MTS 前后和 prepare 后，ADC0/2 DSA 均为 20 dB。
- 数字尺度前后一致，PLL1/PLL2 锁定，时钟 profile SHA 未变；结束停流、DAC 静音、SYSREF 关闭。
- 扩展既有 DSA helper 的 ADC 动作，复用既有生产恢复路径；模拟四 tile Reset 清除 DSA 后的恢复测试通过。

本地证据：`build/tg-repeat-20260911/round01/adc-initialize.json`。
板端 helper 与持久 journal：`/home/xilinx/t510-stage36-tg-repeat01/`。
错误标志窗口另存 `interrupt-baseline.json`：先记录，最多清除一次已存在的标志，再立即和 5 s 后检查；不在采集中清除。
本记录尚不代表第一轮 TG 开启后的测量完成。

错误窗口检查通过：初始化后八路均记录 `0x34000000`，一次清除后立即及 5 s 后均为零；
两次回读 streaming=false、DAC enable_mask=0。这里只记录初始化后的粘滞状态，不认定其具体根因。
第一轮初始化准备完成，等待用户再次确认 TG 开启。

## 第一轮采集提交

用户随后确认 TG 开启。提交单段 60 s 队列，保留全频 100 ms / 1 s 产品、相邻原始谱见证、
全部原有完整性/DSA/RFDC/源存在门禁，自动独立验证并与原始 60 s 结果计算相位差和功率比变化。
单轮结束停流；第二轮初始化仍需用户先关闭 TG，不能自动跨过人工操作。

- systemd：`t510-stage36-tg-repeat-20260911-round01.service`
- Invocation：`61b6af088fc0402c90914038e263aa04`
- GB10 队列：`/var/lib/t510/measurements/stage36-tg-repeat-20260911-round01-queue/`
- 执行快照：`/home/astrolab/.cache/t510/stage36-tg-repeat-20260911-round01/repo/`
- 本地提交脚本：`build/tg-repeat-20260911/round01/submit.sh`
- 新入口：`scripts/stage-36/t510_stage36_tg_repeat_queue.py`，继承已通过的 TG 采集流程。

提交前验证单段 60 s 计划、真实准备证据校验、相位差跨 360° 计算通过。
队列显式保存初始化证据 SHA，接收 metadata 沿用字符串接口，focus 列表仍不超过 32 点。
本段只记录提交，不代表测量完成。

### 第一轮最终结果

用户询问后核验：队列 completed、verification_status=PASS、error=null。
正式窗口丢包、序号/sample0 断点、接口错误均零；结束后八路 RFDC 错误位均零。
板上当前 streaming=false、DAC enable_mask=0。

| 指标 | 原始 60 s | 第一轮初始化后 60 s |
|---|---:|---:|
| ADC0–ADC2 归一化复平均幅度 | 99.999275% | 99.999291% |
| 相位 | −0.199142° | −0.203352° |
| ADC0/ADC2 功率比 | 0.337188 dB | 0.375621 dB |

相位变化 −0.004210°，功率比变化 +0.038434 dB。第一轮 100 ms 相位相对全段均值的
P5/P95 为 −0.006448° / +0.005505°。本次未见共同单音响应的大幅跳变；一次重复不足以断言初始化总能保持一致，
时间间隔、温度及 TG 开关也未独立控制。尚待第二、第三轮；不能据此宣布原相关噪声问题已解决。

## 第二轮初始化准备

用户再次确认 TG 关闭后，核对第一轮 completed/PASS、板上停流和 DAC 静音，按相同 helper 执行四个 ADC tile 各一次 Reset 与 prepare/MTS。
helper 与本地源码 SHA 一致，数字尺度前后一致；ADC latency=[492]*4、offset=[9]*4。
DAC latency=[72]*4，本次 DAC offset=[0,2,0,0]（第一轮为全零），保留实际差异；未显式重置 DAC tile，DAC 继续静音。
ADC0/2 DSA 回读 20 dB、DisableRTS=1，其余六路 0 dB。
初始化后八路错误标志均 `0x34000000`，保存后一次清除，立即和 5 s 后均为零；回读 streaming=false、DAC enable_mask=0。

本地证据：`build/tg-repeat-20260911/round02/{preflight,adc-initialize,interrupt-baseline}.json`。
板端 helper/journal：`/home/xilinx/t510-stage36-tg-repeat02/`。
第二轮初始化完成，尚未采集，等待用户确认 TG 再次开启。

### 第二轮采集提交

用户确认 TG 开启后，复用第一轮执行快照与单段 60 s 队列，替换为第二轮准备证据及只读监测 helper 路径。
自动采集、完整性验证、封存、分析和对原始 60 s 的比较；不执行初始化或清除错误标志。

- unit：`t510-stage36-tg-repeat-20260911-round02.service`
- Invocation：`649dbfdcdc474ffcb51e4c02979cdd50`
- 队列：`/var/lib/t510/measurements/stage36-tg-repeat-20260911-round02-queue/`
- 执行快照：`/home/astrolab/.cache/t510/stage36-tg-repeat-20260911-round02/repo/`
- 本地提交及 SHA manifest：`build/tg-repeat-20260911/round02/`

此处为提交记录，最终状态待后续核验。第三轮仍须在用户关闭 TG 后另行初始化。

### 第二轮完成与三组分析

用户要求“就分析”，因此未继续第三轮。第二轮 completed/PASS，正式丢包、序号/sample0 断点和接口错误零，结束后 RFDC 错误位八路均零。
当前板上 streaming=false、DAC enable_mask=0。

共同单音 ADC0/2 在原始、第一轮、第二轮的归一化复平均幅度分别为
99.999275%、99.999291%、99.999351%；相位分别 −0.199142°、−0.203352°、−0.216090°。
第二轮相对原始相位变化 −0.016947°，不能称完全不变，也不能由未控制温度/时间/TG 开关的比较唯一归因于 Reset。
功率比分别 0.337188、0.375621、0.267669 dB，三组极差约 0.108 dB。

同时检查未接 TG、独立终端的 ADC1/3、4/5、6/7。在 120.078125 MHz（bin3073），
使用整段 60 s 加权复平均再取归一化幅度：

| ADC 对 | 原始 | 第一轮 | 第二轮 |
|---|---:|---:|---:|
| 1–3 | 0.227% | 0.524% | 15.608% |
| 4–5 | 5.350% | 0.494% | 0.303% |
| 6–7 | 7.721% | 4.784% | 0.604% |

这种变化并非仅一个频点：bin3072..3328 的幅度中位数分别为
1–3：0.140%→0.461%→15.947%；4–5：5.599%→0.494%→0.577%；6–7：8.342%→4.765%→0.656%。
这是一项事后描述性检查，范围含 TG 主频；三个原默认频点 3073/3182/3328 也支持同方向变化。
原始分析数值保存于 `build/tg-repeat-20260911/three_capture_comparison.json`。

结论：当前 ADC0/2 的强共同单音响应在两次 ADC 初始化后仍高度相干且相位仅小幅改变，
与此同时其他终端 ADC 对的相关底大幅改变。两种现象可以同时存在，不能用强单音接近 100% 来否定相关噪声问题。
这些是不同 ADC 对、不同频点/输入强度的观察；尚不能证明同一路弱信号测量稳定，不能将其等价为整板重启实验。
此处 TG 持续接入系统，未独立排除 TG 泄漏或其他共享干扰，不能把终端输入结果当作严格 TG-off 对照，更不能直接锁定某个校准系数为根因。

## TG 关闭对照与第三轮接续

用户澄清“就分析”并不表示暂停，三轮计划继续。用户确认 TG 关闭并授权继续：
在第二轮原状态采集 60 s OFF 对照，验证及分析通过后自动执行第三轮四 ADC tile Reset、prepare/MTS、一次错误基线清理与停流核验。
此前没有提交 OFF 任务；本次只提交一次完整队列。测量期间只 STOP/START，进入第三轮初始化的门禁为 OFF 数据完整性及数值验证通过。
第三轮初始化后等用户开启 TG，不能自动继续 ON 采集。

OFF 产品明确记录 TG 关闭、ADC0/2 仍通过功分器连接；没有套用共同单音存在门禁。
保留 DSA、错误、数字身份及原始谱余量检查。采集前核对 round02 ON 的最终初始化身份与当前一致。
比较全 28 对在 bin3073/3182/3201/3328 的整段归一化复平均，并保存全频结果及两路 TG 主频功率的 ON/OFF 变化。
该比较有时间间隔，不能单凭一次开关证明严格因果关系。

- 入口：`scripts/stage-36/t510_stage36_tg_off_queue.py`
- unit：`t510-stage36-tg-off-20260911-round02.service`
- Invocation：`1695a5cf59f049ab93bc2e5d1129c8d1`
- 队列：`/var/lib/t510/measurements/stage36-tg-off-20260911-round02-queue/`
- 执行快照：`/home/astrolab/.cache/t510/stage36-tg-off-20260911-round02/repo/`
- 第三轮准备证据自动写入上述队列 evidence 的 `round03-adc-initialize.json`、`round03-interrupt-baseline.json`、`round03_ready_monitor.json`。
- 板端第三轮 helper/journal：`/home/xilinx/t510-stage36-tg-repeat03/`
- 本地提交与源 SHA：`build/tg-repeat-20260911/off-round02/`

提交前测试通过：OFF 元数据字符串编码、单段 60 s、验证失败禁止 Reset、验证成功后 ADC→错误基线→ready 顺序。
本段为提交记录，尚不代表 OFF 测量或第三轮初始化完成。

### OFF 对照和第三轮初始化完成

用户询问后核验队列 completed、verification_status=PASS、error=null，
third_round_preparation=PASS_awaiting_operator_TG_ON。
第二轮原初始化状态下，bin3073 的 ADC1/3 归一化相关幅度 TG ON=15.6081%、OFF=15.5363%，
相位 −141.5917°→−142.2070°；高相关未随 TG 关闭消失。
ADC4/5 为 0.3035%→0.2274%，ADC6/7 为 0.6043%→0.5723%。
ADC0/2 在 bin3201 的功率分别下降 53.4158/53.7493 dB，支持 TG 开关实际改变了输入单音。
这表明高相关无需 TG 持续输出即可维持；仍不等于确定内部具体根因或排除全部外部干扰。

完成 OFF 产品验证和比较后自动进入第三轮初始化：ADC MTS latency=[492]*4、offset=[9]*4，
DAC latency=[72]*4、offset=[0]*4，DSA=[20,0,20,0,0,0,0,0] dB。
初始化后八路标志 `0x34000000` 已保存并清除一次，立即和 5 s 后均零；独立 ready probe 通过。
最新 Agent 回读 streaming=false、DAC enable_mask=0。第三轮 ON 60 s 尚未采，等待用户打开 TG。
第三轮准备证据另存本地 `build/tg-repeat-20260911/round03/`。

### 第三轮 ON 采集提交

用户确认 TG 再次开启后，复用前两轮的单段 60 s 流程，加载第三轮准备证据。
全频 100 ms/1 s 采集、相邻原始谱见证、门禁、独立校验和对原始 60 s 的比较均自动执行，结束停流。
TG 开启期间不重置、不配置、不清除错误标志。

- unit：`t510-stage36-tg-repeat-20260911-round03.service`
- Invocation：`9262b7377433478790d095e038086157`
- 队列：`/var/lib/t510/measurements/stage36-tg-repeat-20260911-round03-queue/`
- 执行快照：`/home/astrolab/.cache/t510/stage36-tg-repeat-20260911-round03/repo/`
- 本地提交及源 SHA：`build/tg-repeat-20260911/round03/`

此处为提交记录，尚不代表第三轮采集完成；完成后汇总原始及三轮结果。

### 三轮全部完成

用户询问后核验第三轮 completed/PASS、error=null，正式丢包/序号/sample0 断点/接口错误均零，
结束后的 RFDC 错误位八路均零。原始谱见证余量通过。当前 streaming=false、DAC enable_mask=0。
原始及三轮的全部数值汇总：`build/tg-repeat-20260911/four_capture_comparison.json`。

| 指标 | 原始 | 第一轮 | 第二轮 | 第三轮 |
|---|---:|---:|---:|---:|
| ADC0/2 单音相关幅度 % | 99.999275 | 99.999291 | 99.999351 | 99.999299 |
| ADC0/2 单音相位 ° | −0.199142 | −0.203352 | −0.216090 | −0.228347 |
| ADC0/2 功率比 dB | 0.337188 | 0.375621 | 0.267669 | 0.404509 |
| ADC1/3 相关幅度 %，bin3073 | 0.226675 | 0.524102 | 15.608122 | 1.132396 |
| ADC4/5 相关幅度 %，bin3073 | 5.349992 | 0.494059 | 0.303455 | 5.859076 |
| ADC6/7 相关幅度 %，bin3073 | 7.720730 | 4.784497 | 0.604330 | 0.299060 |

第三轮 ADC1/3 的 bin3072..3328 幅度中位数为 1.5493%，ADC4/5 为 6.1850%，ADC6/7 为 0.5081%，
支持背景相关改变并非仅单个频点。三轮之间并非单向改善：第二轮 ADC1/3 升高，第三轮该对降低而 ADC4/5 再度升高。

强共同单音均接近完全相干，相位总变化约 −0.02920°，功率比极差约 0.13684 dB。
相位均值按时间单向变化，不能将这些小差异直接认定为 Reset 跳变，温漂/时间漂移等未独立排除。
结合第二轮 TG OFF 后 ADC1/3 仍约15.54%的对照，当前证据支持高相关背景不依赖 TG 持续输出，
并且强共同信号稳定与其他终端通道背景相关可变这两种现象并存。
三次 ADC Reset 不能等价于所有冷启动，不能证明弱信号或宽带测量已合格，也未定位具体校准机制。
原定三轮 ON 测量现已全部完成，另完成第二轮状态的 OFF 对照；不继续自动增加硬件实验。
