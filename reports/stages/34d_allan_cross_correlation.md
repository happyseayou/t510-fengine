# Stage 34d：Allan稳定性与八路复互相关评估

状态：`COMPLETE / ENGINEERING_PASS / INDEPENDENT_MATCHED_LOAD_CORRELATED_FLOOR_OBSERVED`

用户于2026-08-16确认八路ADC已经分别连接50 Ω负载，补齐此前一直缺失的条件M
（independent matched loads）。脚本和systemd队列已原位扩展，不修改RTL、bitstream、PFB或
UDP；新增单测后Stage 34d专项回归`7/7`通过。完整四段矩阵以user systemd invocation
`fee1459cbb054ae687cea0089915569e`一次性提交。首条
`320 MS/s / 600 s / 100 ms bucket`在105.5秒热稳定后进入正式generation 19：18个频点、
28对复相关、16个SPEC block均连续增长，实测约`1,250,118 packet/s / 83.63 Gbit/s`，
drop/gap均为0，正式v34 header flags=`0x05`。按长任务规则，确认健康后不再驻留轮询；条件M
完成后才能决定是否解除`INDEPENDENT_MATCHED_LOAD_ZERO_CORRELATION_QUALIFICATION_PENDING`。

条件M于2026-08-16 22:10:37 CST正常结束，systemd `Result=success`，总墙钟时间2小时37分10秒。
四个正式run全部`COMPLETE/ok=true`，campaign为`operational_ok=true`、`errors=[]`，安全收尾
也没有错误。8份PCAP与4份TIS1逐文件SHA256复核全部通过；PCAP manifest SHA256为
`d05bddeedb21a149e8c958abea88f20a45c78a14ee81a9c12da3f9e3e83b7e1d`，TIS1 manifest
SHA256为`8281ec302416ad3c86cc08a81b6cbe633896ddc49ee056138ce8c537450a8aba`，四份TIS1合计
353,908,186字节。

匹配负载没有取得零互相关资格，正式分类为
`INDEPENDENT_MATCHED_LOAD_CORRELATED_FLOOR_OBSERVED`：

- 320/160 MS/s的600秒短尺度Re/Im斜率合格率分别为`194/336=57.7%`和
  `211/336=62.8%`，中位`|lag-1|`为`0.131/0.107`，均未达到90%和0.10门限；
- 160/320 MS/s的3600秒长尺度合格率分别为`96/336=28.6%`和
  `34/336=10.1%`，中位`|lag-1|`为`0.208/0.360`；
- 两个长run的128秒散布是短尺度白噪声外推的`2.60/3.55`倍，超过2倍门限；
- 两个长run均有`28/28`个ADC pair在至少4/6个离栅格频点重复显著非零；
- 自相关同样没有恢复：160/320长run的48个`ADC×离栅格bin`均为`0/48`斜率合格，中位
  斜率分别为`-0.118/-0.032`，中位`|lag-1|`为`0.592/0.847`；扣除公共标量后的频谱残差
  仍失败，均分类为`FREQUENCY_DEPENDENT_OR_CHANNEL_LOCAL_DRIFT`。

50 Ω负载对同tile相关幅度有方向性改善，但没有消除科学相关地板。全部pair的整体中位
`|gamma|`从开放输入的`0.001358`变为`0.001492`（`1.10×`）；同tile从`0.005495`降到
`0.004056`（`0.74×`），跨tile从`0.001147`变为`0.001297`（`1.13×`）。S/O/M不是严格
A/B/A顺序，因此这些倍率只作辅助诊断；决定结论的是匹配负载自身的绝对门禁失败。

这个结果否定了“开放端口像天线一样拾取环境信号足以解释全部现象”。负载回损和噪声温度
没有独立校准，所以不把结果写成器件极限；但在用户确认的八个独立50 Ω负载下，板内共享
机制、公共参考或数字形成过程现已成为更高优先级方向。零互相关资格仍未取得，Stage 34a的
长积分不合格状态不能关闭。

2026-08-13条件S长任务已提交，user systemd invocation为
`8fb420ff3687465b816b0817121903c6`。提交前320 MS/s SPEC_ONLY监视器A/B实测约
`1,249,969 → 1,250,013 packet/s`，吞吐比`1.000035`，83.6 Gbit/s下所有drop/gap为0；
预检TIS1共360条记录且长度/SHA一致。首个160 MS/s、600秒、100 ms正式run已健康进入，
确认18个频点、28对复相关、16个block连续增长后按长任务规则停止轮询。条件O unit已安装但
未启动，必须等待用户完成八路全开放并显式确认。

条件S随后于2026-08-13正常完成，四个正式run全部`ok=true`、数字完整性全部通过、任务
`Result=success`且`errors=[]`。共享ADC0/2复可见度分类为
`SHARED_INPUT_VISIBILITY_FLOOR_OBSERVED`：四个run的12条Re/Im离栅格序列分别只有
`1/12、0/12、0/12、0/12`进入白噪声斜率区间，中位`|lag-1|`分别为
`0.400、0.444、0.558、0.527`；两个3600秒run的128秒散布为短尺度白噪声外推的
`4.69/4.55`倍。四个run的Allan分类均为
`FREQUENCY_DEPENDENT_OR_CHANNEL_LOCAL_DRIFT`，扣除标量公共模态后仍未恢复白噪声积分。
与ADC0/2相连的开放通道对还出现`SHARED_INPUT_LEAKAGE_OBSERVED`，但共享SSA终端和开放
输入可能产生共同环境拾取，因此不能仅凭条件S归因于板内串扰；条件O是下一项必要鉴别。

共享阶段保存8份PCAP、4份TIS1（合计353,908,186字节）和4幅正式PNG；PCAP manifest
SHA256为`71a112eb6420578775b3f8974c450981f2a783dfd3a7aa77c1d61e8271c31e4d`，TIS1
manifest SHA256为`e8ca050b36b59721ed327ff6a913ffb95001f71c4f2e277bbd22e0b10cd24659`。
最终回读为停流、receiver不接收、DAC全零、freeze=0、OCB1动态、生产continuous profile
且PLL1/PLL2均锁定。

用户于2026-08-13确认ADC0/2和功分器已经断开，八路ADC进入开放输入诊断条件。条件O完整
四段长任务随后提交，user systemd invocation为`1ee9b7c724794a09b471a2da1d32097e`。
第一条320 MS/s、600秒、100 ms run在完成热稳定后健康进入generation 6；确认83.62 Gbit/s
满速、18个频点、28对复相关、16个block连续增长且drop/gap为0后停止轮询。

条件O最终四个正式run全部`ok=true`并正常退出，campaign为`COMPLETE`、
`operational_ok=true`、`errors=[]`。数字工程门禁全部通过，但开放输入互相关预门禁未通过，
分类为`OPEN_INPUT_CORRELATED_FLOOR_OBSERVED`：

- 320/160 MS/s的600秒短尺度Re/Im斜率合格率分别为`194/336=57.7%`和
  `228/336=67.9%`，低于90%门限；中位`|lag-1|`为`0.193/0.121`；
- 160/320 MS/s的3600秒长尺度合格率为`91/336=27.1%`和
  `106/336=31.5%`；中位`|lag-1|`为`0.172/0.276`；
- 两个长run的128秒散布为短尺度白噪声外推的`2.64/2.97`倍，超过2倍门限；
- 四个run的自相关Allan仍均为`FREQUENCY_DEPENDENT_OR_CHANNEL_LOCAL_DRIFT`；
- 复相关平均幅度本身很小：四个run的28对中位`|gamma|`约为
  `0.00128、0.00129、0.00211、0.00114`，但长积分后多条pair在4～6个离栅格频点重复
  显著非零；同tile整体中位相干度`0.00550`，跨tile为`0.00115`。

这个结果证明“八路开放输入”没有获得零相关预资格，但当时尚不能把相关地板直接归因于板内
公共噪声：悬空AC耦合输入会像天线一样拾取实验室环境RFI和串扰。因此后续补做了本文首部
记录的八路独立50 Ω条件M；条件M仍失败，现已排除“只因输入悬空”这一解释。

条件O保存8份PCAP、4份TIS1（合计353,908,186字节）和4幅正式PNG；PCAP manifest
SHA256为`e8ff93b889b911e6f4198cbad410231e898b867cf500ed692b1c5f50d828c967`，TIS1
manifest SHA256为`c5c250f8e186d1cc7e819ca59e1e6317f827aeadde4d8666dffb136a4e42372a`。
最终回读为停流、receiver不接收、DAC全零、freeze=0、OCB1动态、生产时钟且双PLL锁定；
物理ADC端口按计划保持全部断开。

## 易读版图表

原自动图保留为机器闭合证据；另从冻结JSON/TIS1生成一套面向非专业读者的七张图，位于
`build/receiver/latest/evidence/allan_interferometry/plots_explained`：

1. 总览卡片：工程通过、科学未通过和结论边界；
2. 四个3600秒run的积分散布与理想`1/√τ`同轴对比；
3. sampled-total-power与spectroscopic overlapping Allan deviation；
4. 共享SSA下ADC0×ADC2的Re/Im残差收敛；
5. 开放输入28对的`|γ|`和显著频点数8×8矩阵；
6. 同tile与跨tile中位相关幅度及倍率；
7. 从TIS1直接提取的1007.5 MHz、320 MS/s真实1秒功率/复可见度时间线，并叠加32秒
   滑动平均。

每张图包含坐标、单位、理想参考、门限、图例及通俗解释；`SHA256SUMS`冻结七张PNG。
重绘脚本为`scripts/t510_plot_allan_interferometry_explained.py`，不重新采集、不改写原始证据。

条件M完成后另生成五张匹配负载易读图，位于
`build/receiver/latest/evidence/allan_interferometry/plots_matched_explained`：

1. 匹配负载最终结论和关键数字总览；
2. 160/320长run的自相关、复互相关与理想`1/sqrt(tau)`对比；
3. 两种速率的28对`|gamma|`及显著频点矩阵；
4. 开放输入与50 Ω负载的直接比较；
5. 从匹配负载TIS1直接提取的1007.5 MHz真实1秒与32秒平均时间线。

五张PNG已由`SHA256SUMS`冻结；生成脚本为
`scripts/t510_plot_matched_load_interferometry_explained.py`。

## 目标和边界

Stage 34d不再试图用单一干预解释Stage 34a发现的自相关慢噪声，而是直接回答天文应用更关心的两个问题：功率谱在哪些积分时间内仍按白噪声下降，以及慢噪声是否会进入不同ADC之间的复可见度。固定使用正式v34、4096通道、8-tap PFB、160/320 MS/s SPEC_ONLY、1020 MHz中心频率和生产external-GPSDO continuous SYSREF，不修改RTL、bitstream、PFB或UDP。

三个物理实验严格分开：

1. `shared`：SSA RF INPUT经二路功分器接ADC0/ADC2，TG和preamp关闭、20 dB输入衰减；其余ADC和DAC物理断开。
2. `open`：用户显式确认断开ADC0/2和功分器后，八路ADC全部开放。RFDC为AC耦合，开放输入可作为安全诊断，但不等价于八个独立匹配50 Ω终端。
3. `matched`：用户显式确认八路ADC分别连接50 Ω负载，全部DAC继续物理断开和数字静音；这是
   正式零互相关资格条件。负载回损和噪声温度没有独立校准，因此结论限定为“在本组用户确认
   的独立50 Ω负载下”。

条件M结束前继续保留：`INDEPENDENT_MATCHED_LOAD_ZERO_CORRELATION_QUALIFICATION_PENDING`。

## 实现

receiver的既有`/api/measure/spec-stability`原位扩展：

- `bucket_ms=100|1000`；桶边界只由FPGA `sample0`决定，不依赖主机墙钟；
- `correlation_mode=none|single|all`，旧`correlation_pair`继续兼容；`all`按`01,02,...,67`固定顺序累计28对；
- 复乘固定为`Xi·conj(Xj)`，实部为`IiIj+QiQj`，虚部为`QiIj-IiQj`；
- `result_format=binary`和`GET /api/measure/spec-stability/data`返回小端TIS1；
- TIS1保存每个bucket/target的sample0边界、样本数、八路I/Q及功率矩、28对复相关和JSON映射；结果接口同时冻结字节数与SHA256；
- 数据仍来自现有PACKET_MMAP主接收环，不创建第二个packet socket。

Python分析入口为`scripts/t510_allan_interferometry.py`，实现普通积分散布、overlapping Allan deviation、sampled-total-power、扣除公共标量模态后的spectroscopic Allan、ADC0/2对数功率共/差模、八路PCA、ACF、FFT temporal PSD、block-shuffle、移动块bootstrap和BH `q=0.01`。互相关始终分别检验`Re(V)`和`Im(V)`，不使用天然为正的`|V|`冒充零相关检验。

## 冻结采集矩阵

共享输入：160/600 s/100 ms → 320/600 s/100 ms → 320/3600 s/1 s → 160/3600 s/1 s。

全开放：320/600 s/100 ms → 160/600 s/100 ms → 160/3600 s/1 s → 320/3600 s/1 s。

独立50 Ω负载：320/600 s/100 ms → 160/600 s/100 ms → 160/3600 s/1 s →
320/3600 s/1 s。

监测960 MHz固定项、11个10 MHz栅格点和六个离栅格点；正式Allan/相关地板门禁只使用六个离栅格点。每个run始末从receiver主环保存16端口×32包PCAP。共享阶段安全结束后以`WAITING_FOR_ALL_OPEN_CONFIRMATION`成功退出，不驻留等待；开放阶段必须用`--all-open-confirmed`显式启动。

## 判定

白噪声斜率区间固定为`-0.65..-0.35`。自相关原始总功率失败但至少80%频谱残差通过且PCA第一公共模态不低于70%时，分类为`SCALAR_TOTAL_POWER_MODE_DOMINANT`；两者都失败则为`FREQUENCY_DEPENDENT_OR_CHANNEL_LOCAL_DRIFT`。

共享ADC0/2要求短、长尺度Re/Im各至少10/12通过、1秒残差中位`|lag-1|≤0.10`且128秒散布不超过白噪声外推2倍，输出`SHARED_INPUT_VISIBILITY_RESIDUAL_PASS`或`SHARED_INPUT_VISIBILITY_FLOOR_OBSERVED`。平均相干度低于0.05时相位明确标为`SOURCE_TOO_WEAK_FOR_PHASE_GATE`。

全开放对336条序列要求短、长尺度各至少90%通过、每pair至少10/12、总体中位`|lag-1|≤0.10`、128秒散布不超过白噪声外推2倍，并以移动块bootstrap和BH检查复均值；某pair在至少4/6离栅格点重复显著即为宽带地板。分类为`OPEN_INPUT_CROSS_CORRELATION_PREQUALIFIED`、`OPEN_INPUT_NARROWBAND_PICKUP`或`OPEN_INPUT_CORRELATED_FLOOR_OBSERVED`。

独立50 Ω负载使用完全相同且不放宽的336序列门禁；通过时分类为
`INDEPENDENT_MATCHED_LOAD_ZERO_CORRELATION_QUALIFIED`，否则区分
`INDEPENDENT_MATCHED_LOAD_NARROWBAND_PICKUP`与
`INDEPENDENT_MATCHED_LOAD_CORRELATED_FLOOR_OBSERVED`。开放与匹配负载的相关幅度比只作辅助
诊断，绝对匹配负载门禁才决定资格。

所有数字完整性、安全、温度、PLL、DAC静音、freeze=0和OCB1动态条件仍是硬门禁。开放输入失败不能区分板内公共噪声与环境RFI，不能直接否决产品。

## 证据和长任务

- Board：`build/board/latest/evidence/allan_interferometry`
- Receiver：`build/receiver/latest/evidence/allan_interferometry`
- 共享unit：`t510-stage34d-allan-shared.service`
- 全开放unit：`t510-stage34d-allan-open.service`
- 独立50 Ω负载unit：`t510-stage34d-allan-matched.service`

每个物理阶段是独立用户级systemd长任务；完整队列提交并确认首个正式run健康后停止轮询。
任务结束恢复停流、receiver不接收、DAC全零、freeze=0、OCB1动态、生产时钟和双PLL锁定。
条件M结束后软件安全状态全部在线复核通过，八个物理50 Ω负载保持连接。
