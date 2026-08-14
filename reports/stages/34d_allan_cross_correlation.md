# Stage 34d：Allan稳定性与八路复互相关评估

状态：`COMPLETE / ENGINEERING_PASS / OPEN_INPUT_CORRELATED_FLOOR_OBSERVED`

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

这个结果证明“八路开放输入”没有获得零相关预资格，但不能把相关地板直接归因于板内公共
噪声：悬空AC耦合输入会像天线一样拾取实验室环境RFI和串扰。要区分板内相关与环境拾取，
仍必须取得八个独立匹配50 Ω终端，因此
`INDEPENDENT_MATCHED_LOAD_ZERO_CORRELATION_QUALIFICATION_PENDING`保持不变。

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

## 目标和边界

Stage 34d不再试图用单一干预解释Stage 34a发现的自相关慢噪声，而是直接回答天文应用更关心的两个问题：功率谱在哪些积分时间内仍按白噪声下降，以及慢噪声是否会进入不同ADC之间的复可见度。固定使用正式v34、4096通道、8-tap PFB、160/320 MS/s SPEC_ONLY、1020 MHz中心频率和生产external-GPSDO continuous SYSREF，不修改RTL、bitstream、PFB或UDP。

两段物理实验严格分开：

1. `shared`：SSA RF INPUT经二路功分器接ADC0/ADC2，TG和preamp关闭、20 dB输入衰减；其余ADC和DAC物理断开。
2. `open`：用户显式确认断开ADC0/2和功分器后，八路ADC全部开放。RFDC为AC耦合，开放输入可作为安全诊断，但不等价于八个独立匹配50 Ω终端。

因此最终始终保留：`INDEPENDENT_MATCHED_LOAD_ZERO_CORRELATION_QUALIFICATION_PENDING`。

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

监测960 MHz固定项、11个10 MHz栅格点和六个离栅格点；正式Allan/相关地板门禁只使用六个离栅格点。每个run始末从receiver主环保存16端口×32包PCAP。共享阶段安全结束后以`WAITING_FOR_ALL_OPEN_CONFIRMATION`成功退出，不驻留等待；开放阶段必须用`--all-open-confirmed`显式启动。

## 判定

白噪声斜率区间固定为`-0.65..-0.35`。自相关原始总功率失败但至少80%频谱残差通过且PCA第一公共模态不低于70%时，分类为`SCALAR_TOTAL_POWER_MODE_DOMINANT`；两者都失败则为`FREQUENCY_DEPENDENT_OR_CHANNEL_LOCAL_DRIFT`。

共享ADC0/2要求短、长尺度Re/Im各至少10/12通过、1秒残差中位`|lag-1|≤0.10`且128秒散布不超过白噪声外推2倍，输出`SHARED_INPUT_VISIBILITY_RESIDUAL_PASS`或`SHARED_INPUT_VISIBILITY_FLOOR_OBSERVED`。平均相干度低于0.05时相位明确标为`SOURCE_TOO_WEAK_FOR_PHASE_GATE`。

全开放对336条序列要求短、长尺度各至少90%通过、每pair至少10/12、总体中位`|lag-1|≤0.10`、128秒散布不超过白噪声外推2倍，并以移动块bootstrap和BH检查复均值；某pair在至少4/6离栅格点重复显著即为宽带地板。分类为`OPEN_INPUT_CROSS_CORRELATION_PREQUALIFIED`、`OPEN_INPUT_NARROWBAND_PICKUP`或`OPEN_INPUT_CORRELATED_FLOOR_OBSERVED`。

所有数字完整性、安全、温度、PLL、DAC静音、freeze=0和OCB1动态条件仍是硬门禁。开放输入失败不能区分板内公共噪声与环境RFI，不能直接否决产品。

## 证据和长任务

- Board：`build/board/latest/evidence/allan_interferometry`
- Receiver：`build/receiver/latest/evidence/allan_interferometry`
- 共享unit：`t510-stage34d-allan-shared.service`
- 全开放unit：`t510-stage34d-allan-open.service`

每个物理阶段是独立用户级systemd长任务；完整队列提交并确认首个正式run健康后停止轮询。任务结束恢复停流、receiver不接收、DAC全零、freeze=0、OCB1动态、生产时钟和双PLL锁定。第二阶段结束后物理ADC保持全部断开。
