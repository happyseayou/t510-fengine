# Stage 34a：面向天文观测的性能评估

## 范围与版本冻结

Stage 34a 不修改 RTL、bitstream、UDP 布局或 PFB 系数。它只评价当前正式数字产品在
天文数据处理中的可用边界：

- `CORE_VERSION=0x00010034`
- bitstream SHA-256：
  `c21d93f5ea71e9ac17a4448cff138a8faaf9c7347d879be919b680d196b8a5be`
- 4096 通道、固定 8-tap Hamming-windowed sinc PFB、IQ16、FFT shift `0x556`
- PFB profile `0x34a80001`、coefficient CRC32 `0xb9ba227c`
- MTS target：ADC/DAC `416/112`

本阶段要分开回答三件事：数字后端能否连续无损接收；PFB 对弱谱线、强 RFI 和积分
时间意味着什么；观测到的线条究竟是 ADC 固定项、板内 DAC 产物，还是外部 SSA TG
源路径限制。没有校准噪声源和另一台独立低杂散信号源，因此不报告绝对噪声系数、系统
温度、输入参考 ENOB、ADC 单体极限 SFDR、IP3、Jy/K 或跨板相干性。

## 给非射频专业读者的指标解释

### 通道间隔与 ENBW

4096 点频谱把复采样带宽分成 4096 个横坐标点。160 MS/s 时相邻点相差
`39.0625 kHz`，320 MS/s 时相差 `78.125 kHz`；这叫通道间隔。它告诉我们谱线上两个
点画得有多密，却不等于每个通道实际接收了多宽的白噪声。

8-tap PFB 的等效噪声带宽 ENBW 是 `0.9072586 bin`，即：

| 模式 | 通道间隔 | ENBW |
| ---: | ---: | ---: |
| 160 MS/s | 39.0625 kHz | 35.4398 kHz |
| 320 MS/s | 78.125 kHz | 70.8796 kHz |

计算辐射计灵敏度和单通道噪声功率时必须使用 ENBW。直观上，PFB 通道像一个边缘平滑
的小滤波器；ENBW 是“如果改成理想矩形滤波器，需要多宽才能收进同样噪声”的宽度。
因此 160 模式的 ENBW 是 320 模式的一半，理想白噪声的单 bin 功率应低约
`10 log10(1/2) = -3.0103 dB`。固定窄线不会遵循这个规律。

### 氢线速度分辨率

在静止频率 `1420.4058 MHz` 的中性氢 21 cm 线附近，小频移可用
`Delta v = c * Delta f / f`换成视向速度。按频谱采样点，160/320 模式分别约为
`8.245/16.489 km/s`；按真正收噪声的 ENBW，分别约为`7.480/14.960 km/s`。

这不是“能精确测到这么小的速度”的完整保证。真实速度精度还取决于信噪比、谱线宽度、
频率标定、时钟稳定性和后续拟合；这里描述的是当前通道化提供的基本速度尺度。

### dBFS/bin、dBc 与 SFDR

`dBFS/bin`是某一个频谱通道的数字功率相对 IQ16 满量程的数值。0 dBFS 附近意味着
数字码快用满，负得越多表示越弱。它不是 ADC 连接器处的 dBm；在没有测量模拟增益、
损耗和校准噪声源前，也不能换成天线温度或系统温度。

`dBc`把一个杂散同主载波比较。例如 `-60 dBc`表示杂散功率比载波低 60 dB。
SFDR 通常取主载波到最强非载波线的差，因此决定强 RFI 附近还能看到多弱的谱线。
本报告同时保留原始最坏 SFDR 和按已证明来源分类后的指标；后者便于判断源纯度，前者
防止“把不好看的峰删掉”。

### 积分规律与 Allan 稳定性

彼此独立的随机噪声平均 N 次后，均值的起伏应大致按`1/sqrt(N)`下降。在对数图上，
标准差相对积分时间的斜率应接近 `-0.5`。这就是长积分提高弱谱线灵敏度的基础。
固定杂散、周期干扰和某些增益漂移不会这样下降，所以短谱里很小的固定线在数小时
积分后反而可能成为主限制。

Allan deviation 比较相邻时间段平均值的差。短时间内它若继续下降，表示增加积分仍有
收益；到某个时间开始变平或上升，说明温漂、增益漂移或时钟过程开始占主导。这个转折
时间比单独给一条“10 分钟很稳定”更能指导真实观测如何分段校准。

### 相干度

相干度由两路复数谱的互相关与各自功率归一化得到，范围是 0 到 1。接近 1 表示两路对
同一窄带信号保持稳定的相位关系；随机而不相关的噪声趋近 0。它对干涉测量重要，但本
阶段外部 TG 只接 ADC0/ADC2，所以最多证明单板这两路端到端相干，不外推到跨板基线。

## 来源分类和科学掩码

任何分类都不改变原始 PCAP，也不在 FPGA 或分析前端实施 notch、扣除或隐藏 bin。

- 480、960、1440 MHz 是 Stage 33a 已定责的 RFADC 固定交织项。在每种频率网格上
  标记最近 bin 及左右各 4 bin，作为科学坏频点从全带汇总统计中排除；原始功率、时间
  稳定性及跨路相干度仍单列。
- 160、1120、1280、1600 MHz 是观察名单。再次出现就记录强度和复现率，但不自动屏蔽。
- 20 MHz DAC 梳状项、谐波和采样镜像只能在“DAC 回环源纯度”指标中标为
  `SOURCE_LIMITED_DAC`。它们若出现在 DAC 静音或外部 TG 数据中，不享受这个豁免。
- Stage 33 冻结的 SSA TG 公共源路径特征为载波上方`+91.71875 MHz`偏移边带。只有
  频率偏移吻合并在 ADC0/ADC2 同时复现，才标为`SOURCE_LIMITED`；仍保留原始峰。
- 新候选突出度 6～12 dB 为`WARNING`；在至少两个重叠窗口复现且达到 12 dB 的未知
  固定峰为`ASTRONOMY_REVIEW_REQUIRED`。

## 已实现的数据路径

receiver 新增异步接口：

- `POST /api/measure/spec-stability`
- `GET /api/measure/spec-stability/status`
- `GET /api/measure/spec-stability/result`

正式时长固定 600 秒，最多选择 32 个精确落在 PFB 网格上的 RF/bin，并可选择一对通道
计算复数互相关。统计直接挂在已有 PACKET_MMAP fanout worker 内：每个 SPEC block
使用独立累加锁，只解码被选中的 IQ16，不复制完整数据包，也不打开第二个 packet
socket。即使某个 block 没有选中 bin，仍检查它的 seq/frame/sample0 连续性；任一
身份或 gap 错误立即终止测量。

每个“秒×bin×ADC”保存样本数、I/Q 和、功率和及功率平方和；可选通道对保存复互相关
实部/虚部和两路功率。这些是复算 dBFS/bin、标准差、Allan deviation、相位和相干度
所需的充分统计量。接口不替代 Board Agent 门禁；campaign 同时检查 v34、PFB profile、
MTS、DAC 静音、FIR saturation、XFFT overflow、backpressure和全部 drop/gap计数。

自动入口为`scripts/stage-34/t510_astronomy_performance.py`，依次执行：

1. 按 bitstream SHA 审计 Stage 34 的 MTS 40/40、八路回环、PFB 频响、五模式及 soak；
2. 复用已经通过的 320 MS/s 63 窗、32,256 包、63 PCAP 全带扫描；
3. 新采 160 MS/s DAC 静音的 23 个中心窗口，每窗 16 block×32 包；
4. 在 center 1020 MHz 对 160/320 SPEC_ONLY 各做 600 秒科学稳定性；
5. 生成全带、160−320 差值、来源分类 SFDR、时间线、积分斜率和 Allan 图；
6. 任一失败立即 STOP、动态读取 board_id 后静音八路 DAC，并保留现场，不自动重试。

人工入口为`scripts/stage-34/t510_astronomy_tg.py`。由于 SSA TG 没有 SCPI 自动控制，每次采集
必须由操作员先设置并用`--confirm-source`明确确认；脚本随后自动完成数据门禁和安全
收尾。计划包含：

- 408.000、1420.4057518、1665.40184 MHz 在 160/320 MS/s 各一次；center 固定为
  tone+60 MHz，因此载波精确落在`-1536/-768` bin；
- H I 点的 `-30/-25/-20 dBm`线性扫描；
- H I `-20 dBm`在两种速率各 600 秒 ADC0/ADC2 增益、相位、相干度；
- H I、320 MS/s、`-20 dBm`连续 5 次 fresh CONFIGURE/MTS，不自动重试失败周期。

外部结果统一称为“SSA TG＋已验证功分器＋ADC0/ADC2端到端性能”，不写成 ADC 单体
SFDR。其余六路只画上下文谱，不参与外部源结论。

## 判定

`ENGINEERING_PASS`要求版本、PFB、MTS、吞吐、包连续性、计数器、monitor A/B开销和
最终 STOP/DAC 静音全部通过。任何数字 drop、sample0跳变、FIR saturation、XFFT
overflow、backpressure或未静音 DAC 都直接失败。

`ASTRONOMY_BASELINE_QUALIFIED_WITH_KNOWN_MASKS`还要求：

- 160/320 的干净“通道×bin”中至少 80% 的积分斜率落在`-0.50±0.15`；
- ADC0/ADC2 TG 的 5 dB 步进为`5±1 dB`；
- H I 十分钟增益峰峰值不超过 1%，去固定线缆相位后的相位峰峰值不超过 3°，相干度
  不低于 0.99；
- 除冻结坏频点和严格匹配的`SOURCE_LIMITED`外，没有新的 ≥12 dB 重复固定峰。

TG源纯度造成的`SOURCE_LIMITED`不会单独否决工程层；没有完成TG时不能提前给出天文
资格结论。

## 实际结果与产物位置

自动硬件campaign已完成。160 MS/s的23窗静默扫描、320 MS/s既有63窗扫描、数字吞吐、
包连续性和安全收尾均通过，证据位于：

- `build/receiver/latest/evidence/performance_evaluation`
- `build/board/latest/evidence/performance_evaluation`

长积分原始中位斜率约为160 MS/s `-0.2668`、320 MS/s `-0.2336`；将同一批每秒功率
随机打乱后分别约为`-0.5136/-0.4987`。这说明PFB、UDP顺序和统计公式可以产生正确的
白噪声积分规律，但原始时间序列含有同一路ADC内的时间相关过程。480、960、1440 MHz
仍按Stage 33a固定坏频点单独处理，不能用来解释所有干净bin共同出现的斜率变浅。

因此状态为
`ENGINEERING_DATA_PATH_PASS / LONG_INTEGRATION_FAIL / NO_ASTRONOMY_QUALIFICATION`。
后续34b-1完成了RFDC软件freeze能力验证；34b-2在调整为满足器件电平要求的训练源后完成
正式A/B/C，但训练冻结仍未恢复`1/sqrt(N)`。Stage 34c随后完成共享50 Ω、OCB1、时钟/SYSREF
及34c-3板内负载/AMS调查：OCB1锁定不是修复，5 MHz SYSREF仅有弱方向性改善，TIME_SPEC与
SPEC_ONLY没有可逆差异；34c-3的160/320 MS/s 60分钟离栅格点中位斜率进一步达到
`-0.0215/-0.0175`，时间打乱后为`-0.5066/-0.5222`。因此本报告的长积分失败结论继续保持；
模拟ADC电源纹波和主动热因果仍待具备相应仪器或可逆干预后调查。
