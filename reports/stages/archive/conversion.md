# 总体判断

你们看到的不是理想白噪声，而是一个**真实的低频功率涨落过程**。从射电天文接收机的角度看，白噪声积分到一定时间后被增益漂移、偏置漂移或 (1/f) 噪声接管，是常见现象，这也是为什么射电频谱仪通常用 Allan variance 和 Allan time 描述稳定性，而不只检查辐射计方程。([AANDA][1])

但需要把“常见”与“可接受”分开：

* **对未校准的总功率测量而言**，你们现在的结果不正常，也不可接受。斜率约 (-0.02)、lag-1 达到 (0.83)–(0.85)，意味着从当前最短积分尺度开始，低频过程就几乎支配了误差。
* **对干涉仪而言**，还不能据此判定 T510 F-engine 不可用。自相关功率不再积分下降，不等于两个独立输入之间的互相关也存在地板。必须进一步区分：

  1. 独立的通道增益漂移；
  2. 板内公共加性噪声；
  3. 共享输入源产生的公共模态；
  4. 数字累加器的有状态行为。

其中第 2 类最危险，因为它会直接形成虚假的相关可见度；第 1 类主要表现为随时间变化的复增益，可以通过校准处理，但校准间隔必须短于系统的稳定时间。

---

# 一、现有数字结果实际上说明了什么

设每秒得到一个功率估计 (P_t)。对于有时间相关性的序列，长度为 (N) 的平均值满足

[
{\rm Var}(\overline{P}_N)
=========================

\frac{\sigma_P^2}{N}
\left[
1+
2\sum_{k=1}^{N-1}
\left(1-\frac{k}{N}\right)\rho(k)
\right],
]

其中 (\rho(k)) 是间隔 (k) 的自相关系数。

如果相关只存在有限时间，例如一个普通的 AR(1) 过程，那么相关性只会减少有效样本数，**长期斜率最终仍会回到 (-1/2)**。

以你们的数据为例：

[
\rho_1=0.834
\quad\Rightarrow\quad
\frac{N}{N_{\rm eff}}
\simeq
\frac{1+\rho_1}{1-\rho_1}
=11.05,
]

[
\rho_1=0.852
\quad\Rightarrow\quad
\frac{N}{N_{\rm eff}}
\simeq 12.51.
]

也就是说，如果这只是短记忆 AR(1) 噪声，误差只会增加约

[
\sqrt{11.05}=3.32,\qquad
\sqrt{12.51}=3.54
]

倍，但积分曲线仍应继续下降。你们测得的斜率分别为 (-0.0215) 和 (-0.0175)，说明相关函数存在很长的尾部，或者序列包含慢漂移、状态切换或接近 (1/f) 的过程。

在近似平稳且功率谱满足

[
S_P(f)\propto f^{-\alpha}
]

的条件下，块平均标准差的斜率 (s) 近似满足

[
s\simeq\frac{\alpha-1}{2}.
]

代入当前结果：

[
\alpha_{160}\simeq0.957,\qquad
\alpha_{320}\simeq0.965.
]

因此，**现象在统计形态上非常接近 flicker 型、即近 (1/f) 的功率或增益噪声**。这不是最终物理归因，因为暖机漂移、缓慢状态切换和重叠累加也可能产生相似曲线，但它比“普通相邻样本相关”更严重。

随机打乱时间顺序恢复 (-0.5)，只能证明：

> 同一组边缘分布在破坏时间结构以后符合独立抽样规律。

它不能进一步证明相关过程一定来自 ADC 模拟端，也不能排除 FPGA 中的滑动窗口、IIR、未完全清零的累加器、旧缓冲区重复使用或控制寄存器的周期更新。

---

# 二、PFB 本身基本不可能解释这么大的相关性

你们当前是 4096-channel、4-tap、critically sampled PFB。相邻的原始 PFB 频谱确实不是完全独立的，因为 4-tap PFB 具有有限记忆。

但在 1 s 非重叠功率输出的条件下：

* 160 MS/s 时，每秒约有 (160,{\rm MHz}/4096=39062.5) 个频谱；
* 320 MS/s 时，每秒约有 (78125) 个频谱；
* 4-tap PFB 的有限记忆只有几个 FFT 帧。

因此，由 PFB 跨越一秒边界造成的相邻秒相关，量级最多约为

[
\mathcal{O}\left(\frac{4}{39062}\right)\sim10^{-4},
]

而不是 (0.84)。

所以可以更准确地说：

> **PFB 的有限冲激响应不可能直接产生当前相关性；但尚未排除以 PFB 输出为输入的滑动累加、累加器复位、ping-pong 缓冲或数据复用问题。**

尤其是 lag-1 约为 (0.84) 本身，也与一个约 84% 重叠的滑动窗口或具有类似反馈系数的 IIR 十分相似。虽然这不一定是实际原因，但必须通过数字注入闭环实验排除，而不能只依赖 shuffle。

---

# 三、目前最容易忽略的关键点：50 Ω 终端并没有主导当前噪声

这是我认为本次调研中最重要的定量结论。

对于 T510 使用的 ZU4xDR Gen 3 RF-ADC，AMD 给出的典型参数是：

* DSA = 0 dB 时满量程输入约 (+1) dBm；
* 低频输入条件下噪声谱密度约为 (-154\ {\rm dBFS/Hz})。

因此，其输入等效 ADC 自噪声约为

[
-154\ {\rm dBFS/Hz}+1\ {\rm dBm}
\simeq -153\ {\rm dBm/Hz}.
]

室温 290 K、50 Ω 电阻的可用热噪声约为

[
-174\ {\rm dBm/Hz}.
]

两者相差约

[
21\ {\rm dB}.
]

忽略 balun 损耗和匹配误差，室温终端提供的噪声功率只有 ADC 自噪声的约 (0.8%)。对于你们的两个有效带宽，数量级分别是：

|    有效带宽 |    ADC 自噪声积分功率 | 290 K 终端噪声相对满量程 |
| ------: | -------------: | --------------: |
| 128 MHz | 约 (-72.9) dBFS |  约 (-93.9) dBFS |
| 256 MHz | 约 (-69.9) dBFS |  约 (-90.9) dBFS |

因此，假设输入链路没有额外前置增益，当前实验主要测到的是：

> **ADC 本身、RFSoC 模拟电源/参考、板载输入网络和时钟共同形成的自噪声，而不是外部 50 Ω 负载的普通热噪声。**

这也解释了为什么“更换为 50 Ω 输入”不一定会改变结果。八路独立终端依然必须做，因为它能断开共享功分器、SSA 机箱地和公共源，但它主要解决的是**拓扑隔离问题**，不是提高外部噪声对 ADC 自噪声的占比。([AMD 文档][2])

这还带来一个重要工程含义：

* 如果最终真实接收机前端有足够增益，使天线、LNA 和天空噪声比 ADC 自噪声高 10–20 dB，那么当前看到的某些**加性 ADC 自噪声漂移**可能在科学运行中被压低。
* 但如果根因是 ADC 的**乘性增益漂移**，提高输入噪声不能消除它，反而会等比例调制真实输入。

所以后面必须做输入功率扫描，以区分加性和乘性机制。

---

# 四、对现有七组实验应当怎样重新解释

## 1. GCB/TSCB 冻结：降低了校准游走的可能性，但没有完全排除 RFDC 内部状态

AMD 文档明确说明：

* OCB1、GCB、TSCB 在后台实时运行；
* OCB1 用于连续修正主要由温度变化引起的 sub-ADC 偏置；
* GCB 和 TSCB 依赖输入信号，输入低于约 (-40) dBFS 时不再有效；
* 普通 `cal_freeze` 端口冻结的是 GCB 和 TSCB，不包括 OCB1。([AMD 文档][3])

所以你们“强单音训练后冻结”的实验已经很好地降低了 GCB/TSCB 在弱输入下随机游走的可能性。但还需要确认：

* `cal_frozen` 状态位确实置位；
* 每次 run 中没有软件重新解除冻结；
* 没有 Signal Magnitude Detector、AGC 或其他逻辑通过实时接口控制 freeze；
* 没有周期性更新 DSA、QMC gain、NCO 或 calibration coefficients。

Gen 3 RF-ADC 还带有 Signal Magnitude Detector，其中包含可编程 leaky integrator；它本身不会自动形成 AGC，除非 PL 或软件使用其输出控制 DSA、校准或外部增益，但这类隐藏控制路径需要检查 IP 配置和 HDL。([AMD 文档][4])

## 2. OCB1 快照锁定：结果更像“移除了补偿”，而不是证明 OCB1 是噪声源

OCB1 的设计目的就是连续消除 sub-ADC 的残余偏置和 (kF_s/N) 偏置交织杂散。锁定后变差、恢复动态后回到基线，至少与“OCB1 原本正在补偿一个温度相关偏置过程”相符。([AMD 文档][5])

更重要的是，PG269 说明：使用 `XRFdc_SetCalCoefficients` 写入系数会进入 coefficient override，并自动关闭实时校准；此时普通 freeze 端口不再生效。OCB1/OCB2 也不建议采用手动系数更新方式。([AMD 文档][6])

因此需要复核你们“锁定 OCB1”的代码语义：

> 如果使用的是 coefficient override，它可能不只是单独固定 OCB1，而是改变了该 ADC 的整体实时校准状态。

所以目前可以说“OCB1 快照不是修复方案”，但还不能把这组实验解释成对 OCB1 的严格单变量隔离。

## 3. SYSREF 实验：排除了 SYSREF 翻转，不等于排除了采样时钟

一套公开的 T510 射电天文实现显示，板卡使用 LMK04828 和 122.88 MHz VCXO 生成 ADC 时钟、数据接口时钟和 SYSREF。该研究还指出，122.88 MHz VCXO 与 10 MHz 外部参考组合时，会使 PLL 鉴相频率低于采用 100 MHz VCXO 的情况。([arXiv][7])

你们的实验已经说明：

* continuous SYSREF 不是主因；
* 5 MHz 与 10 MHz SYSREF 栅格至多有次要影响。

但没有排除：

* LMK/VCXO 的低频控制电压变化；
* RFDC 内部采样 PLL；
* 样本时钟幅度或相位噪声的慢包络；
* PLL lock/holdover/reacquisition；
* 时钟电源通过地或模拟轨耦合进 ADC。

对于平坦宽带噪声，纯相位噪声通常不是总功率漂移的首要解释，因此时钟的优先级低于独立终端和供电；但对最终干涉相位稳定性，它仍是必须单独验证的项目。

## 4. 数字输出负载实验：基本排除了负载强度，但没有排除状态逻辑

SPEC_ONLY 与 TIME_SPEC 之间约两倍输出流量变化没有可逆改变结果，说明 CMAC、packetizer 和整体 PL 动态负载不是主导因素。

但两个模式可能仍共享：

* 同一个 PFB；
* 同一个功率累加器；
* 同一组积分触发和复位；
* 同一套 BRAM/URAM ping-pong 缓冲；
* 同一秒级控制寄存器更新；
* 相同的 DMA 数据刷新逻辑。

所以应把当前结论写成：

> **网络传输、丢包、数据率和高层输出负载已基本排除；RFDC 输出之后的有状态数字积分路径尚未通过确定性数字注入完全闭合。**

## 5. AMS 温度与电压无相关：这是有效阴性结果，但排除能力有限

AMD 对 Gen 3 模拟轨给出的 0.1–15 MHz 纹波上限包括：

* ADC_AVCC：(0.25) mVpp；
* ADC_AVCCAUX：(1.2) mVpp。

AMD 还建议在真实逻辑活动条件下，使用至少 3 GHz 示波器和 1.5 GHz 探头或直接同轴连接，在器件附近的供电点测量，而不是依赖片内遥测。([AMD 文档][8])

因此 AMS 的阴性结果只能说明：

> 没有发现与 AMS 可见的板级平均温度、电压直接同步的线性慢漂。

它不能排除：

* ADC_AVCC/AVCCAUX 上数百微伏的纹波；
* 开关电源 burst/PFM 的慢包络；
* 两个开关频率之间的低频拍频；
* 局部 balun、VCXO、模拟稳压器或终端温度；
* 带有几十秒热延迟的非零滞后相关；
* 高频纹波幅度包络对 ADC 噪声的调制。

简单的零时延 Pearson 相关不足以发现这些过程。

## 6. DAC tile 关停失败：不应继续强行使用运行时 power-down 作为主要路径

AMD 推荐 ADC 与 DAC 使用分离电源，但也说明在某些 ADC-only、同时使用 MTS 的设计中，DAC tile 仍然需要供电，即使 DAC tile 不被使能。([AMD 文档][9])

所以更安全、更可解释的方法不是继续强行驱动状态机，而是：

* 生成一个在 RFDC IP 配置阶段就禁用 DAC converter/digital path 的 ADC-only bitstream；
* 保留 MTS 所需的合法供电和时钟条件；
* 关闭不需要的 DAC fabric 时钟和 LMK 输出；
* 再与现有 bitstream 做 A1/B/A2。

---

# 五、当前最可能的机制类别

我会把目前的“物理可能性”和“实验优先级”分开排列。

| 机制                        | 与当前结果的吻合程度     | 典型观测指纹                                           |
| ------------------------- | -------------- | ------------------------------------------------ |
| 公共乘性增益漂移                  | 高              | 所有干净频率通道具有近似相同的 fractional fluctuation；第一主成分接近平坦 |
| ADC/板级公共加性自噪声漂移           | 高              | 绝对功率变化近似与输入电平无关；弱输入时最明显                          |
| 共享 SSA、功分器、机箱地或源波动        | 中到高，尚未隔离       | ADC0/ADC2 公共模态强，但二者比值或差分恢复白噪声                    |
| ADC_AVCC/AVCCAUX、内部参考或地调制 | 中到高            | 多通道低频相干，可能按 tile 或电源域聚类                          |
| 数字滑动累加、复位或旧缓冲区问题          | 概率未知，但测试优先级最高  | 数字 PRBS 注入仍然失败；不同模拟输入无影响                         |
| OCB/GCB/TSCB 或 DSA 隐藏状态   | 中低             | 功率变化与系数、DSA code、over_voltage 标志或特定交织杂散同步        |
| LMK/VCXO/采样 PLL           | 中等；对相位比对总功率更重要 | 双音相位漂移随频率线性增长，或频谱残差呈 bandpass 导数形状               |
| DAC tile 内部活动             | 中低             | 只有 ADC-only bitstream 才产生可逆变化                    |
| PFB 有限记忆                  | 极低             | 只应产生短记忆、远小于当前值的相关                                |

目前最符合数据的现象模型是

[
P_{i,f}(t)
==========

[1+g_{\rm common}(t)+g_i(t)],
\overline{P}*{i,f}
+
a*{\rm common}(f,t)
+
a_i(f,t)
+
w_{i,f}(t),
]

其中：

* (g_{\rm common})：板级或源级公共乘性增益；
* (g_i)：通道或 tile 特有增益；
* (a_{\rm common})：公共加性噪声或耦合；
* (a_i)：通道加性漂移；
* (w)：正常白色辐射计噪声。

现在的任务不是继续盲目冻结更多模块，而是把这四个项分离出来。

---

# 六、按判别力排序的实验方案

## 第 0 级：先用现有数据做四个分析

这些分析不需要新硬件，并且很可能立即把问题缩小一半。

### 0.1 总功率 Allan 与 spectroscopic Allan 分开

定义每个通道、每个频率的归一化功率：

[
z_{i,f}(t)
==========

\frac{P_{i,f}(t)}
{\langle P_{i,f}\rangle_t}-1.
]

公共标量模态为

[
c_i(t)=\left\langle z_{i,f}(t)\right\rangle_f,
]

去除总功率后的频谱形状残差为

[
r_{i,f}(t)=z_{i,f}(t)-c_i(t).
]

分别计算：

* (c_i(t)) 的 total-power Allan deviation；
* (r_{i,f}(t)) 的 spectroscopic Allan deviation；
* 去除 (c_i(t)) 后的积分斜率。

如果 (c_i(t)) 接近 (1/f)，但 (r_{i,f}(t)) 恢复 (-0.5)，说明：

> 频谱形状本身稳定，问题主要是一个标量增益或总功率模态。

这正是 Allan variance 在射电频谱仪中区分 total-power 与 spectroscopic fluctuation 的标准用途。([arXiv][10])

### 0.2 利用现有 ADC0/ADC2 共享输入数据做共模—差模分解

对已有的共享 SSA/功分器数据计算

[
c(t)=\frac{\ln P_0(t)+\ln P_2(t)}{2},
]

[
d(t)=\ln P_0(t)-\ln P_2(t).
]

结果解释非常直接：

* (c(t)) 失败、(d(t)) 恢复 (-0.5)：共享源或板级公共模态；
* (c(t)) 和 (d(t)) 都失败：存在通道/tile 特有漂移；
* 低频 coherence 只出现在某些频率：窄带杂散或模拟输入网络；
* coherence 在全带平坦：公共增益或公共加性过程。

这一步应当排在购买低噪声电源探头之前。

### 0.3 检查 DC、交织杂散和干净频段

同时比较：

[
P_{\rm raw}(t)=\langle x^2\rangle,
\qquad
P_{\rm AC}(t)=\langle[x-\langle x\rangle]^2\rangle.
]

并在频域分别计算：

* 包含所有频率；
* 去除 DC；
* 去除 (kF_s/8) 及附近若干 bin；
* 去除已知 480、960、1440 MHz 杂散；
* 去除带边和强窄带线；
* 只使用干净的中间频段。

如果只在 DC 和 (kF_s/8) 附近失败，重点回到 OCB/偏置交织；如果整个干净频段有相同 fractional mode，重点转到增益、供电或公共源。

### 0.4 不只做一次逐点 shuffle，而是做 block shuffle

把时间序列按

[
L=1,2,4,8,16,32,64,128\ {\rm s}
]

分块，只随机打乱块的顺序，保留块内相关。

当块长度增加到某个值后，积分斜率重新变差，这个转折直接给出主要相关时间尺度。还应同时输出：

* temporal PSD；
* Allan deviation；
* ACF 至至少数百秒；
* change-point 或功率跳变位置。

对于 60 min 数据，Allan 结果在 (\tau\gtrsim300)–(600) s 后独立样本数已经很少，不应对最末端几个点做强解释。

---

## 第 1 级：彻底封闭数字链路

这是目前最重要的缺失实验。

### 1.1 在 RFDC AXI 输出之后加入数字噪声 MUX

在 FPGA 内加入两种输入：

* 正常 RFDC ADC 数据；
* 长周期、独立种子的复 Gaussian-like PRBS 数字噪声。

数字噪声必须走完全相同的：

[
{\rm PFB}\rightarrow{\rm FFT}\rightarrow |X|^2
\rightarrow{\rm accumulator}\rightarrow{\rm packetizer}
\rightarrow{\rm CMAC}\rightarrow{\rm host}.
]

使用与正式实验完全相同的 1 s dump、积分计数和 UDP 格式。

判据：

* 数字注入仍为斜率约 0：数字积分、缓冲或主机分析存在问题；
* 数字注入恢复 (-0.5)：PFB 之后的数字链路基本闭合，根因位于 ADC/RFDC/时钟/模拟板级。

### 1.2 同时增加一个 pre-PFB 原始功率支路

从 RFDC 输出直接计算

[
P_{\rm pre}(t)=\sum_n x_n^2
]

并进行严格非重叠的一秒累加，不经过 PFB/FFT。

同时保留当前

[
P_{\rm post}(t)=\sum_f |X_f|^2.
]

结果解释：

| pre-PFB           | post-PFB  | 判断                |
| ----------------- | --------- | ----------------- |
| 正常                | 异常        | PFB、FFT、功率累加或频谱缓冲 |
| 异常                | 异常        | RFDC 之前或公共控制/时钟   |
| 数字 PRBS 异常        | 均异常       | 数字状态逻辑            |
| 数字 PRBS 正常、ADC 异常 | ADC/模拟/时钟 |                   |

累加数据包中应额外记录：

* `integration_id`；
* first/last `sample0`；
* 实际样本数；
* accumulator reset count；
* 数据块 checksum。

零丢包和连续 `sample0` 不能排除 payload 没有更新或旧 BRAM bank 被重复发送。

### 1.3 周期性原始 ADC 快照

不需要连续保存数小时全速数据。可以每秒捕获一段短原始样本，计算：

* code mean；
* variance；
* skewness/kurtosis；
* code histogram；
* 偶/奇或 sub-ADC 类别差异；
* 原始时间域功率；
* 离线 PFB/FFT 功率。

如果原始 code variance 已经沿同一个慢模态变化，数字 F-engine 基本可以排除。

---

## 第 2 级：独立终端、输入功率扫描与互相关

### 2.1 八路直接独立 50 Ω 终端

要求是：

* 每个 SMA 直接接独立高质量 feedthrough terminator；
* 不通过功分器；
* 不连接 SSA 或其他接地仪器；
* 终端尽量固定在同一铜块上；
* 记录终端附近温度；
* 交换终端和端口，判断异常跟随终端还是跟随 ADC 端口。

随后计算八通道低频 covariance 和 coherence，并按物理 tile 分组。

典型结果：

* 八通道全部同相：板级公共电源、地、时钟或温度；
* 同 tile 内更强：tile 局部电源、内部校准或时钟分配；
* 只跟随某个端口：输入 balun、连接器或 ADC channel；
* 跟随某个终端：终端或连接方式。

### 2.2 三档以上的宽带输入电平

需要用外部稳定宽带源，把输入噪声提升到 ADC 自噪声之上。可以覆盖例如：

* 终端/ADC 自噪声状态；
* 约 (-50) dBFS RMS；
* 约 (-35) dBFS RMS；
* 约 (-25) dBFS RMS。

实际电平要以 Gaussian 峰值不触发 over-amplitude、DSA 和 clipping 为准。每个 run 都应固定并读回 DSA，同时记录 `over_voltage` sticky flag。Gen 3 RF-ADC 在过幅时会自动改变片内 DSA，直到清除标志后才恢复用户设定。([AMD 文档][11])

模型为

[
P_{\rm out}(t)=G(t)P_{\rm in}+A(t).
]

比较慢漂移幅度与平均输入功率：

* (\delta P) 在输出线性单位中近似不随 (P_{\rm in}) 改变：加性 ADC 自噪声或偏置；
* (\delta P/P) 近似不随 (P_{\rm in}) 改变：乘性增益漂移；
* 只有跨过 (-40) dBFS 左右后改善：低输入状态下的校准或量化/自噪声机制；
* 输入升高后仍完全不变：板级增益、电源或时钟更可疑。

分析必须在线性功率单位完成，不能先转 dB 再拟合加性/乘性模型。

### 2.3 把互相关作为干涉仪的正式门禁

用八路独立终端时，计算任意两路的复 cross-spectrum：

[
V_{ij}(f,\tau)=\langle X_i(f)X_j^*(f)\rangle_\tau.
]

理想情况下，它应围绕零继续按 (1/\sqrt{\tau}) 收敛。

结果具有直接科学含义：

* auto-power 不积分，但 independent-load cross-power 正常：主要是独立增益或独立加性漂移，干涉测量可能仍可用；
* independent-load cross-power 出现非零地板：存在公共加性耦合、时钟泄漏、地噪声或板内串扰，这是干涉仪必须解决的问题；
* 同 tile pair 比跨 tile pair 更差：tile 内部公共模态；
* 所有 pair 同时异常：板级公共模态。

再用一个强宽带公共源分到多个通道，测量归一化复相干度，可以得到相对增益和相位稳定性，而公共源自身的功率变化会在通道比值中部分抵消。

你们现有多块 T510，因此板间 A/B 也应提前做：同一 bitstream、同一终端、同一时钟和同一端口编号，比较不同板卡。如果只有一块板异常，应优先怀疑板级器件、焊接或某个 regulator；如果多块板具有相同模态，则更像设计、clock profile、RFDC 配置或测试拓扑。

---

## 第 3 级：供电与主动热控

### 3.1 供电应同时测两个频率区间

第一路测 AMD 规范对应的

[
100\ {\rm kHz} - 15\ {\rm MHz},
]

目标包括 ADC_AVCC、ADC_AVCCAUX 和必要的参考轨。应在靠近 RFSoC 的去耦电容或厂商批准的测试点，以低环路面积同轴或高带宽差分探头测量。

第二路测

[
{\rm mHz} - 100\ {\rm kHz},
]

使用低噪声差分前置放大器和高分辨率采集，寻找：

* regulator PFM/burst；
* phase shedding；
* fan/PWM 包络；
* 供电拍频；
* 周期性负载管理；
* 几十秒至数分钟的慢变化。

最重要的不是只计算 rail voltage 与 ADC power 的零时延相关，而是计算：

* 滞后互相关；
* magnitude-squared coherence；
* rail 高频纹波的短时 RMS 或 envelope 与 ADC power 的相关；
* 自然漂移与主动电源 A/B 的可逆性。

ADC 对高频纹波的响应可能取决于纹波的 RMS 包络，而 AMS 看到的平均电压仍然完全不变。

### 3.2 主动热扰动比被动相关更有判别力

建议保持固定风扇转速，并对以下区域分别做温度阶跃：

1. 输入终端或功分器；
2. T510 输入 balun/连接器区域；
3. ADC 模拟稳压器；
4. LMK04828/VCXO；
5. RFSoC 所在区域的环境空气。

每次采用你们已经使用过的 A1/B/A2 可逆结构，并测量

[
\frac{\partial\ln P(f)}{\partial T}
]

及时间延迟。

如果受控温度阶跃产生的频谱主成分与自然漂移的主成分一致，就获得了比被动相关强得多的因果证据。固定暖机时间、固定机箱风量和随机化 A/B 顺序也很重要，否则长时间热演化会与实验条件混淆。

---

## 第 4 级：时钟、RFDC 状态与 DAC tile

### 4.1 双音或多音时钟诊断

注入两个稳定相干单音 (f_1,f_2)，连续跟踪复振幅。

采样时间误差 (\delta t(t)) 会产生

[
\delta\phi(f,t)=2\pi f,\delta t(t).
]

所以：

* 相位漂移与频率成线性比例：采样时钟或时延；
* 两个频率振幅同向漂移、相位稳定：增益或电源；
* 频谱残差与平均 bandpass 的导数相似：采样频率或 NCO 的微小漂移；
* 只有固定杂散幅度变化：校准、偏置或供电耦合。

SYSREF 频率实验不能代替这一测试。

### 4.2 RFDC 完整状态审计

每个 run 至少记录：

* GCB/TSCB `cal_frozen`；
* OCB1/OCB2/GCB/TSCB coefficient readback；
* calibration override 状态；
* calibration mode：AutoCal、Mode 1 或 Mode 2；
* DSA code；
* over-amplitude/over-voltage；
* common-mode flags；
* tile current state、reset count；
* RFDC PLL lock；
* 所有运行期 RFDC register write。

AMD 对 Gen 3 推荐实际比较 AutoCal 与 legacy Mode 1/Mode 2，而不是假定某一种必然最优。Mode 1 针对第一 Nyquist 区中 (0.4F_s) 到 (F_s/2)，Mode 2 针对 0 到 (0.4F_s)。([AMD 文档][12])

这些实验的优先级低于数字注入和输入功率扫描，因为现有冻结结果已经降低了普通 GCB/TSCB 漂移的可能性。

### 4.3 ADC-only bitstream

在 RFDC IP 配置阶段禁用 DAC，而不是运行时强制 power-down。对比：

* 当前 ADC+DAC 配置；
* DAC converters disabled；
* DAC PL interface disabled；
* 不需要的 DAC/clock outputs disabled；
* 相同 ADC、MTS 和采样配置。

这才能对“静音 DAC tile 是否仍通过电源或时钟影响 ADC”给出安全且可重复的判断。

---

# 七、今后的报告不应只给积分斜率

斜率只能描述形状，不能描述实际影响。一个斜率为 0、地板为 10 ppm 的系统，与地板为 (10^{-3}) 的系统完全不同。

每个 run 至少应输出：

1. fractional power time series，单位 ppm 或 (\delta P/P)；
2. overlapping Allan deviation；
3. total-power Allan 与 spectroscopic Allan；
4. Allan minimum/time；
5. temporal PSD 及低频指数；
6. (1/f) knee；
7. 各通道低频 coherence；
8. 第一主成分的频谱 loading 和解释方差；
9. 去除第一公共模态后的积分斜率；
10. independent-load cross-power 的收敛曲线；
11. 干净频段、DC/杂散频段和全带结果；
12. 斜率及 Allan 值的置信区间。

其中最能直接回答“是否影响干涉仪”的不是 auto-power slope，而是：

[
V_{ij}^{\rm independent\ loads}(\tau)
]

是否继续向零收敛，以及公共宽带输入下复增益在预定校准周期内的稳定性。

---

# 最终结论

你们原来的一句话结论方向正确，但建议改得更严格一些：

> **当前数据证明系统存在近 (1/f) 的低频功率模态；普通 GCB/TSCB 冻结、OCB1 快照锁定、continuous SYSREF、输出数据率以及 packet loss/overflow 均不是其主要解释。PFB 的有限记忆也不足以产生观测到的 lag-1 相关。然而，RFDC 输出之后的有状态数字累加路径尚未通过确定性数字注入完全排除。由于室温 50 Ω 终端的噪声约比 ZU4xDR ADC 输入等效自噪声低 21 dB，当前实验主要测量的是 ADC/板卡自噪声稳定性。下一步应依次完成：现有数据的总功率—频谱 Allan 和共模—差模分析、post-RFDC 数字噪声注入与 pre-PFB 功率支路、八路独立终端及独立负载互相关、宽带输入电平扫描，随后再进行 ADC 模拟供电和主动热扰动实验。**

从根因概率上，我目前最怀疑的是：

[
\boxed{
\text{ADC/板级公共乘性增益或加性自噪声的慢调制}
}
]

物理载体可能是模拟供电、内部参考、地、局部温度或共享输入拓扑。现有证据还不能在这些物理来源之间唯一选择。时钟采样路径和未审计的 RFDC/DSA 状态仍需检查，但优先级低于数字闭环、独立终端和输入功率扫描。

[1]: https://www.aanda.org/articles/aa/abs/2001/26/aah2637/aah2637.html "https://www.aanda.org/articles/aa/abs/2001/26/aah2637/aah2637.html"
[2]: https://docs.amd.com/r/en-US/ds926-zynq-ultrascale-plus-rfsoc/RF-ADC-Electrical-Characteristics "https://docs.amd.com/r/en-US/ds926-zynq-ultrascale-plus-rfsoc/RF-ADC-Electrical-Characteristics"
[3]: https://docs.amd.com/r/en-US/pg269-rf-data-converter/Background-Calibration-Process "https://docs.amd.com/r/en-US/pg269-rf-data-converter/Background-Calibration-Process"
[4]: https://docs.amd.com/r/en-US/pg269-rf-data-converter/Signal-Magnitude-Detector-Details?utm_source=chatgpt.com "Signal Magnitude Detector Details - 2.6 English - PG269"
[5]: https://docs.amd.com/r/en-US/pg269-rf-data-converter/Time-Interleaved-Offset-Calibration-Block-OCB?utm_source=chatgpt.com "Time Interleaved Offset Calibration Block (OCB) - 2.6 English"
[6]: https://docs.amd.com/r/en-US/pg269-rf-data-converter/Getting/Setting-Calibration-Coefficients "https://docs.amd.com/r/en-US/pg269-rf-data-converter/Getting/Setting-Calibration-Coefficients"
[7]: https://arxiv.org/html/2607.01975v1 "https://arxiv.org/html/2607.01975v1"
[8]: https://docs.amd.com/r/en-US/ug583-ultrascale-pcb-design/ADC-and-DAC-Voltage-Supply-Specifications "https://docs.amd.com/r/en-US/ug583-ultrascale-pcb-design/ADC-and-DAC-Voltage-Supply-Specifications"
[9]: https://docs.amd.com/r/en-US/ug583-ultrascale-pcb-design/Power-Regulation-and-Decoupling-for-ADC-and-DAC-Supplies "https://docs.amd.com/r/en-US/ug583-ultrascale-pcb-design/Power-Regulation-and-Decoupling-for-ADC-and-DAC-Supplies"
[10]: https://arxiv.org/abs/0712.4335 "https://arxiv.org/abs/0712.4335"
[11]: https://docs.amd.com/r/en-US/pg269-rf-data-converter/DSA-Operation-Details-Gen-3/DFE "https://docs.amd.com/r/en-US/pg269-rf-data-converter/DSA-Operation-Details-Gen-3/DFE"
[12]: https://docs.amd.com/r/en-US/pg269-rf-data-converter/Calibration-Modes "https://docs.amd.com/r/en-US/pg269-rf-data-converter/Calibration-Modes"

# 我的提问
我现在手头上只有前面所说的设备，最终我确实是要做互相关的，我想把互相关作为正式的门禁。如果这样子考虑的话，我是不是大概做两件事情？，1、把统计上的验证用你说的 Allan(我还不了解是什么)，2、看看互相关是不是满足√N 的规律


是。核心上可以归纳成两条线，但它们的地位不同：

1. **Allan 分析是诊断工具**：回答噪声从什么积分时间开始不再是白噪声，以及最佳积分/校准时间尺度是多少。
2. **互相关积分是正式科学门禁**：回答当前自相关功率中的时间相关噪声，是否会形成虚假的干涉可见度或互相关噪声地板。

需要注意，你说的“满足 (\sqrt{N}) 规律”准确地说是：

[
\text{随机误差}\propto \frac{1}{\sqrt{N}},
\qquad
\text{S/N}\propto \sqrt{N}.
]

---

## 1. Allan 分析到底在做什么

你现在的做法是：把功率序列按不同长度平均，检查平均后的标准差是否按

[
\sigma(\tau)\propto\tau^{-1/2}
]

下降。

Allan deviation 与它类似，但不直接看所有平均值相对于总体均值的离散程度，而是看**相邻时间块之间变化了多少**。

设原始数据是每秒一个功率值 (P_k)。对于积分时间 (\tau=m) s，先得到连续时间块的平均功率：

[
\overline P_j(\tau)
===================

\frac{1}{m}\sum_{k=jm}^{(j+1)m-1}P_k.
]

然后 Allan deviation 定义为

[
\sigma_{\rm A}(\tau)
====================

\sqrt{
\frac{1}{2}
\left\langle
\left[
\overline P_{j+1}(\tau)-\overline P_j(\tau)
\right]^2
\right\rangle
}.
]

实际计算时，最好先把功率归一化：

[
y_k=\frac{P_k}{\langle P\rangle}-1,
]

这样 Allan deviation 表示 fractional fluctuation，可以用 ppm 或百分数表示。

### 怎么看 Allan 曲线

在双对数图上：

* 白噪声主导：

[
\sigma_{\rm A}(\tau)\propto\tau^{-1/2};
]

* 近似 (1/f) 或 flicker 噪声主导：

[
\sigma_{\rm A}(\tau)\approx {\rm constant};
]

* 温漂、随机游走或长期趋势主导：

[
\sigma_{\rm A}(\tau)
]

会随 (\tau) 上升。

典型曲线是先下降，然后达到最低点，再变平或上升：

```text
Allan deviation
      |
      |\
      | \
      |  \      白噪声区，斜率约 -0.5
      |   \
      |    \___
      |        \__
      |           \   漂移开始占主导
      +-------------------- integration time
                   ↑
               Allan time
```

最低点对应的时间通常称为 **Allan time**。它的物理意义是：

> 在这个时间尺度以内，继续积分有效；超过以后，低频漂移开始抵消积分带来的收益。

你们现在从 1 s 开始，普通积分斜率就已经接近 0，因此 Allan 曲线很可能从 1 s 起就已经接近平坦。那意味着：

* 系统的白噪声区可能短于 1 s；
* 或者 1 s 功率序列中已经混入了一个很强的公共慢模态。

因此，条件允许时，最好增加较短的输出间隔，例如 0.01、0.1 或 0.25 s，再计算 Allan deviation。否则只能得到：

[
\tau_{\rm Allan}<1~{\rm s}
]

或“在当前可测范围内没有发现白噪声区”。

### Allan 对你们的价值

它不会直接告诉你根因是电源、ADC 还是温度，但能回答三个很实用的问题：

1. 噪声在什么时间尺度由白噪声变成相关噪声；
2. 是否存在明确的 (1/f) 区域；
3. 干涉仪的校准时间间隔是否必须短于某个值。

所以建议保留你们已有的“块平均积分斜率”，再补充 overlapping Allan deviation。两者不是互相替代，而是互相验证。

---

# 2. 互相关应当作为正式门禁

这一点比自相关功率是否满足 (1/\sqrt{N}) 更重要。

设两个 ADC 通道的复数 PFB 输出为

[
X_i(f,t),\qquad X_j(f,t).
]

真正的干涉可见度估计是

[
V_{ij}(f,\tau)
==============

\frac{1}{N}
\sum_{n=1}^{N}
X_i(f,n)X_j^*(f,n).
]

这里必须使用**复数通道化数据**。不能把两个通道的功率时间序列做相关来代替干涉互相关，因为功率已经丢失了电场相位。

对于两个完全独立的输入，理论上有

[
\langle V_{ij}\rangle=0.
]

同时其实部和虚部的随机误差应满足

[
\sigma_{\operatorname{Re}V}
\propto
\frac{1}{\sqrt{B\tau}},
\qquad
\sigma_{\operatorname{Im}V}
\propto
\frac{1}{\sqrt{B\tau}},
]

其中 (B) 是有效带宽，(\tau) 是积分时间。

因此正式的互相关门禁不能只看一个斜率，而应同时满足三个条件：

### 条件一：均值是否为零

对于独立终端：

[
\langle \operatorname{Re}V_{ij}\rangle
\simeq 0,
\qquad
\langle \operatorname{Im}V_{ij}\rangle
\simeq 0.
]

如果长时间积分后趋向一个非零值，这说明存在：

* 板内公共加性噪声；
* 电源或地耦合；
* 时钟泄漏；
* ADC 通道串扰；
* 模拟输入网络耦合；
* 其他公共模态。

这种非零值就是干涉仪最危险的 correlated noise floor。

### 条件二：随机散布是否按 (1/\sqrt{\tau}) 下降

把连续可见度按不同积分时间平均，然后计算各时间块之间的散布：

[
\sigma_{\operatorname{Re}V}(\tau),
\qquad
\sigma_{\operatorname{Im}V}(\tau).
]

拟合

[
\log \sigma = s\log \tau+C.
]

理想情况下：

[
s\simeq -0.5.
]

初步工程门限可以先使用例如

[
-0.6<s<-0.4,
]

但最终门限应结合拟合不确定度、积分范围和你们的科学动态范围要求，而不是机械地要求恰好等于 (-0.500)。

### 条件三：长积分后是否出现地板

即使前几十秒满足 (-0.5)，也可能在更长积分时间后出现平台：

[
\sigma_V(\tau)
\rightarrow \sigma_{\rm floor}.
]

因此门禁必须覆盖至少一个实际科学相关时间尺度，例如：

* 一次相位校准间隔；
* 一次观测 scan；
* 预期最长的无校准积分时间。

600 s 数据可以用于初步测试，但最终最好覆盖实际运行中的典型校准周期。

---

# 3. 当前共享 50 Ω 输入不能直接做“零相关门禁”

这是你当前方案里最重要的限制。

你们现在是：

```text
ADC0 ──┐
       ├── 二路功分器 ── SSA 的同一个 50 Ω 输入
ADC2 ──┘
```

这两个 ADC 并不是独立输入。它们共享：

* 同一个 50 Ω 终端；
* 同一个功分器；
* 同一个机箱地；
* 部分共同热噪声；
* 功分器有限隔离导致的通道间耦合。

因此理论上互相关不一定趋近零：

[
V_{02}(\tau)\rightarrow V_{\rm common}\neq0.
]

这时如果你直接画

[
|V_{02}|
]

随积分时间的变化，它很可能先下降，最后停在一个平台。这个平台不一定代表 T510 内部产生了坏的相关噪声，也可能只是你故意给两个通道输入了同一个公共噪声源。

对当前共享输入，正确的检查方法是：

[
\delta V_{02}(t)
================

V_{02}(t)-\langle V_{02}\rangle.
]

然后看：

[
\sigma_{\operatorname{Re}\delta V}(\tau),
\qquad
\sigma_{\operatorname{Im}\delta V}(\tau)
]

是否按 (1/\sqrt{\tau}) 下降。

同时检查公共可见度本身的：

* 振幅稳定性；
* 相位稳定性；
* 频率方向连续性；
* 是否存在随时间变化的附加相关分量。

这个实验能回答：

> 对一个公共输入信号，T510 两路通道之间的相对复增益是否稳定，相关器的随机误差是否正常积分。

但它不能最终回答：

> 在没有共同天空信号时，T510 自己是否产生了虚假的互相关。

后一个问题必须依赖两个物理独立的 50 Ω 终端。

---

# 4. 在你现有设备条件下，实际可以先做什么

你当前可以完成两项核心测试。

## 测试 A：每个通道的 auto-power Allan 分析

对 ADC0、ADC2 分别计算：

[
y_i(t)=\frac{P_i(t)}{\langle P_i\rangle}-1.
]

输出：

1. 普通块平均标准差；
2. overlapping Allan deviation；
3. temporal PSD；
4. ADC0 与 ADC2 功率变化的相关性；
5. 共模和差模。

共模、差模可以定义为

[
c(t)=\frac{\ln P_0(t)+\ln P_2(t)}{2},
]

[
d(t)=\ln P_0(t)-\ln P_2(t).
]

如果：

* (c(t)) 很相关，但 (d(t)) 恢复白噪声，说明主要是共享输入或板级共模；
* (d(t)) 也不积分，说明两个通道分别存在独立的增益或偏置漂移。

这一步可以直接使用你们已经完成的共享 50 Ω 数据。

## 测试 B：共享输入下的复互相关稳定性

计算每个频率通道的

[
V_{02}(f,t)=X_0(f,t)X_2^*(f,t),
]

然后对不同时间尺度积分。

不要只分析 (|V|)，而应分别分析：

[
\operatorname{Re}V,\qquad
\operatorname{Im}V,
]

以及归一化复相干度：

[
\gamma_{02}(f,t)
================

\frac{V_{02}(f,t)}
{\sqrt{P_0(f,t)P_2(f,t)}}.
]

对共享输入应检查：

[
V_{02}-\langle V_{02}\rangle
]

的实部和虚部散布是否按 (1/\sqrt{\tau}) 下降，以及 (\gamma_{02}) 的相位是否发生慢漂。

---

# 5. 最终门禁建议

可以把正式门禁分为两级。

## 一级：当前设备可以完成

**公共输入相关稳定性门禁**

* 复可见度残差的实部和虚部满足约 (1/\sqrt{\tau})；
* 没有新的长积分随机噪声平台；
* 归一化可见度振幅稳定；
* 相位漂移满足未来相位校准预算；
* 不同频率通道没有异常公共谱结构。

这证明 F-engine 和后续相关链路能够稳定测量一个公共输入。

## 二级：必须有独立终端才能完成

**独立输入零相关门禁**

* 两路输入物理独立；
* 复互相关均值与零统计相容；
* 实部和虚部的 RMS 按 (1/\sqrt{\tau}) 下降；
* 在最长测试积分时间内不出现相关地板；
* 不同 ADC pair 的相关矩阵中没有 tile 级或板级公共模态。

只有通过第二级，才能严格证明当前 auto-power 的时间相关噪声不会转化成虚假干涉信号。

---

# 最简化的结论

你的思路可以概括为：

[
\boxed{
\text{Allan 负责判断系统稳定时间尺度，互相关负责判断科学上是否可用。}
}
]

但互相关门禁需要区分：

[
\boxed{
\begin{aligned}
\text{共享输入：}&\quad
V-\langle V\rangle\text{ 是否按 }1/\sqrt{\tau}\text{ 收敛；}\
\text{独立输入：}&\quad
V\text{ 是否向零收敛且没有相关地板。}
\end{aligned}
}
]

使用你们当前的共享 SSA 50 Ω 输入，可以立刻完成 Allan 分析和公共输入互相关稳定性测试；但它不能单独完成最终的零相关门禁。最终只需要增加两个真正独立的 50 Ω 终端，不需要先引入复杂的新仪器。


# 我的提问
现在的问题是我也没有 50 欧姆的负载，我是不是可以将全部 ADC 都断开进行后面的 Allan 分析和互相关测试

可以。**把 8 路 ADC 全部断开，可以立刻进行 Allan 分析和互相关测试**，但应把它定义为：

[
\boxed{\text{开放输入诊断／预门禁，而不是最终的零相关门禁}}
]

原因是开放输入既有诊断价值，又引入了新的不确定性。

## 一、先确认一个硬件条件

AMD 明确允许“已在 RFDC IP 中启用、但没有外部驱动”的 ADC 输入保持 floating，**前提是 RF-ADC 配置为 AC-coupled mode**。同时，AMD 也说明 ADC 输入需要适当的源阻抗匹配，才能获得最佳动态性能。([AMD 文档][1])

因此，在断开全部 ADC 前，先确认：

1. RFDC IP 中 ADC 使用的是 **AC-coupled mode**；
2. T510 的 SMA 到 RFSoC ADC 之间确实经过 balun/DC block；
3. 没有把 ADC 配置成依赖外部共模电压的 DC-coupled 模式。

RFSoC 的模拟输入本质上是差分接口，典型板卡通过 balun 把外部单端 50 Ω 系统转换为 ADC 所需的差分阻抗环境；因此，“SMA 开路”与“50 Ω 匹配终端”不是同一种输入条件。([AMD 文档][2])

只要确认是 AC coupling，短期和长期采集通常都可以安全进行。

---

# 二、开放输入下可以做 Allan 分析

这项测试是有效的。

把全部 ADC 断开以后，每个 ADC 测得的主要是：

* ADC 自身噪声；
* 板级电源和参考噪声；
* ADC tile 内部公共过程；
* 时钟或地耦合；
* SMA、走线和 balun 接收到的外界电磁干扰；
* 通道之间的串扰。

因此开放输入 Allan 分析回答的是：

> 在没有外部有意信号的条件下，整块 T510 的 ADC 和板级系统具有怎样的时间稳定性？

它可以用于判断：

* 每个通道的相关噪声是否仍然存在；
* 8 路是否具有相同的 Allan 曲线；
* 同一个 ADC tile 内的通道是否更相似；
* 是否存在全板公共慢模态；
* 稳定性转折发生在什么时间尺度。

建议对每个 ADC、每个频率通道先构造归一化功率：

[
y_i(f,t)
========

\frac{P_i(f,t)}
{\left\langle P_i(f,t)\right\rangle_t}-1.
]

然后至少计算三类量：

### 1. 每个 ADC 的总功率 Allan deviation

[
y_i(t)=\left\langle y_i(f,t)\right\rangle_f.
]

这主要看整体功率或整体增益是否缓慢变化。

### 2. 去除总功率共模后的 Allan deviation

[
r_i(f,t)=y_i(f,t)-y_i(t).
]

如果原始 Allan 很差，但去除 (y_i(t)) 后恢复白噪声规律，说明主要是一个近似频率无关的标量增益漂移。

### 3. 八通道的相关矩阵

计算不同通道功率序列的相关性：

[
C_{ij}
======

{\rm corr}[y_i(t),y_j(t)].
]

它可以初步区分：

* 全部 ADC 同时变化：全板公共过程；
* 同 tile 内相关更强：tile 级过程；
* 各通道互不相关：通道独立噪声；
* 个别通道异常：端口或局部模拟链问题。

开放输入 Allan 的结果本身有意义，但它描述的是“开放输入状态”，不能直接代表未来接上 LNA、滤波器和天线后的稳定性。

---

# 三、开放输入下也可以做互相关，而且很值得做

需要使用 PFB 输出的**复数电压数据**：

[
X_i(f,t),
]

然后对每一对 ADC 计算

[
V_{ij}(f,\tau)
==============

\frac{1}{N}
\sum_{n=1}^{N}
X_i(f,n)X_j^*(f,n).
]

8 路 ADC 一共有

[
\frac{8\times7}{2}=28
]

组互相关基线。

这个测试可以直接检查：

* RFSoC 内部是否产生公共加性噪声；
* ADC tile 内是否有串扰；
* 板级电源、地或时钟是否在多通道中形成相干信号；
* F-engine 互相关结果是否出现长积分噪声地板。

## 不要只分析 (\lvert V_{ij}\rvert)

正确做法是分别分析：

[
{\rm Re},V_{ij},\qquad {\rm Im},V_{ij}.
]

因为即使真实互相关为零，(\lvert V\rvert) 也始终为正，会产生统计偏置。对于独立输入，理想结果应为：

[
\left\langle {\rm Re},V_{ij}\right\rangle\simeq0,
\qquad
\left\langle {\rm Im},V_{ij}\right\rangle\simeq0,
]

并且不同积分长度下的散布满足

[
\sigma_{{\rm Re}V}(\tau)\propto\tau^{-1/2},
]

[
\sigma_{{\rm Im}V}(\tau)\propto\tau^{-1/2}.
]

还应计算归一化相干度：

[
\gamma_{ij}(f,\tau)
===================

\frac{V_{ij}(f,\tau)}
{\sqrt{P_i(f,\tau)P_j(f,\tau)}}.
]

理想独立输入应满足：

[
\gamma_{ij}\rightarrow0.
]

---

# 四、为什么开放输入不能成为最终门禁

开放的 SMA 端口和输入走线会表现得像小型接收天线。多个 ADC 端口处于同一板卡、同一机箱和同一电磁环境，因此可能同时接收到：

* 开关电源辐射；
* FPGA、DDR、CMAC 或时钟谐波；
* 风扇和控制器产生的周期性干扰；
* 外界无线电信号；
* 相邻 SMA 端口和走线之间的串扰。

因此，开放输入时如果测到

[
V_{ij}\neq0,
]

不能立即判断是 ADC 内部问题。它可能来自：

[
\text{内部公共噪声}
+
\text{板级辐射耦合}
+
\text{外部环境拾取}.
]

反过来，如果开放输入条件下 28 条基线都能满足：

* 实部、虚部均值接近零；
* 散布按 (1/\sqrt{\tau}) 下降；
* 长积分没有明显平台；
* 没有 tile 级或全板公共频谱结构；

那么这是一个很强的正面结果，说明至少在开放输入这种容易拾取干扰的条件下，没有发现明显的内部相关噪声地板。

所以对开放输入测试的解释是：

| 开放输入结果       | 可以得出的结论                            |
| ------------ | ---------------------------------- |
| 通过           | 很有价值，说明没有发现明显相关地板                  |
| 不通过          | 不能直接判定 ADC/F-engine 失败，需要匹配终端进一步区分 |
| 个别窄带失败       | 很可能是时钟、数字杂散或外界 RFI                 |
| 全带宽平坦相关      | 更应怀疑公共电源、地、ADC 自噪声或板级耦合            |
| 同 tile 内明显更强 | 更应怀疑 tile 内部公共过程或局部供电              |
| 所有基线同时相关     | 更应怀疑全板公共模态或外界公共拾取                  |

---

# 五、你现在可以建立一个三级测试体系

## 第一级：开放输入预门禁

全部 8 路 ADC 断开。

检查：

1. 每个通道的 Allan deviation；
2. 8 路功率相关矩阵；
3. 28 条复互相关基线；
4. 实部和虚部 RMS 是否按 (1/\sqrt{\tau}) 下降；
5. 是否出现长积分地板；
6. 相关结构是否按 ADC tile 聚类。

这一步现在就可以做。

## 第二级：共享 SSA 50 Ω 输入

使用你已有的 SSA 50 Ω 输入和功分器。

这里两路输入共享同一个物理噪声源，所以

[
V_{ij}\neq0
]

是正常的。此时不要测试“是否趋近零”，而要测试：

* 复可见度残差是否按 (1/\sqrt{\tau}) 下降；
* 归一化相关幅度是否稳定；
* 相位是否缓慢漂移；
* 两个通道的相对复增益是否稳定。

具体可以分析：

[
\delta V_{ij}(t)
================

V_{ij}(t)-\left\langle V_{ij}\right\rangle.
]

然后检查

[
\sigma_{{\rm Re}\delta V}(\tau),
\qquad
\sigma_{{\rm Im}\delta V}(\tau)
]

是否按 (\tau^{-1/2}) 下降。

这一步主要验证“相关器能否稳定测量公共信号”。

## 第三级：最终独立输入门禁

最终仍需要独立的匹配输入，例如每路独立 50 Ω 终端，或者未来真实的独立前端。

最终正式门禁应要求：

[
\langle V_{ij}\rangle\simeq0,
]

[
\sigma_{{\rm Re}V}(\tau),
\sigma_{{\rm Im}V}(\tau)
\propto\tau^{-1/2},
]

并且在目标积分时间内不存在相关地板。

---

# 六、建议你现在实际怎么做

在现有条件下，建议直接完成以下采集：

### 条件 O：全部开放

* 8 路 ADC 全断开；
* 160 MS/s 和 320 MS/s 各做；
* 每种至少 3 次；
* 每次至少 600 s；
* 更好的是增加一次 3600 s；
* 固定 RFDC 校准模式、风扇和时钟设置；
* 同时输出所有 28 条互相关。

### 条件 S：共享 SSA 终端

* ADC0/ADC2 使用现有功分器和 SSA；
* 保留其他 ADC 开放；
* 与条件 O 做 A/B/A；
* 检查相关特征是否只出现在 ADC0/ADC2；
* 检查其他开放通道是否与 ADC0/ADC2 同时相关。

这个设计实际上很有判别力：

* ADC0/ADC2 之间的公共相关增强，是共享输入的预期结果；
* 其他开放通道如果也同步增强，说明可能有板级串扰；
* 其他开放通道不变，说明共享输入影响主要局限于目标通道；
* 开放通道彼此出现公共相关，则重点检查板级公共过程。

---

# 结论

你可以把全部 ADC 断开，并继续做 Allan 和互相关测试。这个实验不是无效的，反而是当前最合理的下一步之一。

但应准确表述为：

[
\boxed{
\text{开放输入用于筛查时间稳定性、公共模态和相关噪声地板，}
}
]

而不是：

[
\boxed{
\text{开放输入等价于八路独立 50 Ω 终端。}
}
]

对当前阶段，可以把门禁暂定为：

> 在全部 ADC 开放条件下，28 条基线的复互相关实部和虚部应在统计上接近零，其散布应在目标积分范围内近似按 (1/\sqrt{\tau}) 下降，并且不出现稳定的宽带相关地板。若不通过，该结果只能触发进一步调查，不能直接判定 T510 干涉采集链失败。

最终采购或制作独立 50 Ω 终端后，再执行正式的独立输入零相关门禁。

[1]: https://docs.amd.com/r/en-US/pg269-rf-data-converter/RF-ADC-Analog-Input "RF-ADC Analog Input - RF-ADC Analog Input - 2.6 English - PG269"
[2]: https://docs.amd.com/r/en-US/ug583-ultrascale-pcb-design/Choosing-the-Appropriate-Balun "Choosing the Appropriate Balun - Choosing the Appropriate Balun - UG583"
