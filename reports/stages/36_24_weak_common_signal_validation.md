# Stage 36：弱共同信号验证——TG OFF参考准备

2026-09-12。用户确认TG关闭，功分器两路接ADC0/2，其他六路独立50Ω。
此接线与此前八路独立50Ω不同，重新建立背景模板，不混用旧模板。
当前ADC0/2 DSA=20dB，其余0dB；本队列不Reset、不MTS、不CONFIGURE、不写增益或DSA。

## 已提交队列

`stage36-weak-off-20260912`：预检 → 连续120秒TG OFF复可见度 → 全部manifest/数据块SHA与独立数值验证
→ 前60秒逐bin复背景、后60秒独立OFF验证 → 停流、DAC静音、封存。
全28对4096bin的100ms原生产物与1s派生产品保留。
输出 `off_template_validation.npz` 保存训练/检验复均值及两路功率，摘要 `off_reference_summary.json` 包含ADC0/2目标bin3201及邻频。
后续TG ON数据只应用这个已封存背景，不参与重新拟合；ON电平与开关需用户后续操作，目前不自动进入ON。

## 输入切换后的错误基线

第一次停止状态读回ADC0 RFDC错误位非零（1490552160），其他路零；未启动正式采集。
保存读数后调用既有单次中断清除流程，其before读回ADC0为1222116704，立即及5秒后回读八路均零，ok=true。
这只记录发生过锁存，不凭读数变化判定接线瞬态或其他具体根因。原始probe与全部清除日志纳入队列证据。
正式窗口不再清错误，若复发则停止并保留现场。

## 身份

- runner：`scripts/stage-36/t510_stage36_weak_signal_off_queue.py`
- GB10快照：`/home/astrolab/.cache/t510/stage36-weak-off-20260912/repo/`
- 证据：`/var/lib/t510/measurements/stage36-weak-off-20260912-queue/`
- 本地准备/提交：`build/weak-signal-20260912/`
- unit：`t510-stage36-weak-off-20260912.service`

当前仅提交TG OFF阶段，不代表验证通过，也不代表弱信号已测得。
后续先根据新OFF结果和既有TG动态范围确定安全电平，明确区分强信号线性验证与真正接近背景的弱信号验证。

## OFF完成

恢复核查：completed、verification_status=PASS、error=null。正式丢包/序号/sample0/接口错误零，段末八路RFDC错误零。
queue manifest及OFF摘要/停止probe验SHA一致；当前停止采流、八路DAC关闭。
ADC0/2目标bin3201：训练背景0.246287+j0.209327 count²，后60秒验证0.146135+j0.286004，残差幅度0.126134 count²。
对应验证功率ADC0/2为138.444727/117.573239 count²。模板已封存，后续ON不能重新拟合。
下一步先用此前已验证过的TG −20dBm、130.078125MHz零扫宽建立共同信号参考，须用户手动开启确认后采集。
该档是参考响应，不预先称为接近背景的弱信号；后续根据实测及TG/DSA动态范围决定是否需要额外衰减。

## ON参考队列提交

用户确认TG开启，沿用−20dBm、130.078125MHz。完整队列 `stage36-weak-on-m20-20260912` 已提交：
10秒共同信号/数据/原始IQ余量门禁 → 60秒正式采集 → 全文件验签及数值验证 → 应用封存OFF复背景 → 停流、DAC静音。
运行入口 `scripts/stage-36/t510_stage36_weak_signal_on_queue.py`，不执行RESET/MTS/CONFIGURE或增益修改。
预检验证OFF manifest与模板SHA及硬件初始化身份；ON不重新拟合背景。TG由用户控制，队列不会关闭外部TG。
unit `t510-stage36-weak-on-m20-20260912.service`，invocation `19da205b11eb44a4868a0ca90bb7f77a`。
源快照和manifest位于GB10 `/home/astrolab/.cache/t510/stage36-weak-on-m20-20260912/`。
纯软件自检已验证复矢量扣除、零残差相位未定义、10+60秒队列及禁止配置/时钟写操作。
此处仅记录提交，最终PASS和科学结论以完成后的证据核查为准。

## ON参考完成核查

`stage36-weak-on-m20-20260912` completed，verification_status=PASS，error=null。
10秒和60秒两段正式完整性门禁通过，丢包、序号/sample0断点与接口错误增量均零。
恢复检查queue manifest及扣除结果、结束状态文件SHA一致。
60秒ADC0/2 bin3201：原始幅度27708214.973370 count²，扣除后27708214.727455 count²；
原始相位−0.101917487°，扣除后−0.101917921°，原始归一化相关幅度99.9993418%。
背景矢量仅0.323226 count²。因此本档证明该强共同信号在固定背景扣除后几乎不变，
不足以验证接近背景的弱信号恢复。下一步需用户关闭TG、保持接线和配置，补OFF后控，检查背景返回情况。

## POST OFF队列提交

用户确认TG关闭，完整提交 `stage36-weak-post-off-20260912`：预检 → 120秒OFF → 完整数据验证 → 两分钟分别与原OFF首60秒封存背景比较 → 停流、DAC静音。
原OFF及ON须completed/PASS，预检核验manifest与所用证据SHA、初始化身份一致，不清中断、不重新配置。
入口 `scripts/stage-36/t510_stage36_weak_signal_post_off_queue.py`，unit同queue加t510前缀。
invocation `4556e158d62c43e282d624fc5ce52f81`。结果 `post_off_return.json` 和 `post_off_fixed_background.npz`。
复用OFF分钟汇总也生成局部两分钟比较文件，但本实验主结论使用原始pre-ON模板，不用post数据重拟合。
此处记录提交，不代表完成；TG关闭后时间漂移仍是前后对比的混杂因素。

## POST OFF完成核查

completed、verification_status=PASS、error=null。正式丢包/序号/sample0/接口错误均零；结束streaming=false，八路DAC关闭。
恢复检查queue manifest及post_off_return、post_off_fixed_background、board_final_safe的SHA一致。
ADC0/2 bin3201：原背景0.246286933+j0.209327360 count²；post第1分钟0.187169067+j0.654208213，第2分钟0.2464064+j0.2038208。
相对原背景残差分别0.448791595、0.005507856 count²，原pre-OFF验证残差0.126133856 count²。
强TG谱峰关闭后不再维持ON的27708214.97 count²水平；第二分钟该bin接近原背景，但单bin结果不能证明全带背景完全稳定或第一分钟必为开关瞬态。
科学带28对全局归一化幅度中位数：第1分钟raw0.144829%→fixed0.121146%；第2分钟raw0.144395%→fixed0.147145%。
p90分别4.180776%→0.385131%、4.329492%→0.531027%。说明大偏置尾部受到抑制，但全体弱相关点并非均获益。
本轮强信号保持与OFF返回对照完成；弱信号恢复仍未验证，不能据此默认全对/全bin扣除或判断因果机制。

## 网页与衰减方案（2026-09-12）

页面 `/static/weak-signal.html` 已加入8036主报告入口。28对、6频点，原生100ms幅度及相位、图例联动、OFF独立显示、对数轴、60秒复均值表。训练段与独立检验明确区分。
导出逐块验SHA，并核对100ms加权复均值与封存产品一致。162 Chromium真实浏览器检验28对、1200点扣除公式、图例点击联动、ADC切换、窄屏无水平溢出PASS；截图已人工查看。

SSA3000X Plus官方手册TG范围−20至0dBm： https://www.siglent.eu/_downloads/09cc7a3fb44f0caa384f6482c3471b25 。目前已在下限。
AMD DSA资料 https://docs.amd.com/r/en-US/pg269-rf-data-converter/DSA-Operation-Details-Gen-3/DFE 给出27dB范围示例，具体上限依器件；本轮不写DSA探测上限。现20dB保持不变，避免引入新的背景状态。
推荐外部50Ω同轴固定衰减组合覆盖60/70/80/90dB（例如20dB×4、10dB×1），覆盖130MHz，连接器按实际线缆匹配；置于TG与功分器之间，两路共用，不是只衰减一支。
预测模型：两路电压各乘10^(−L/20)，共同复可见度乘10^(−L/10)。当前27708214.97count²下，增加60/70/80/90dB预计27.7082/2.77082/0.277082/0.0277082count²。
这是相对于当前设置的理想共同信号预测，不是绝对输入功率标定；80dB接近本频点0.323count²复背景，但背景不等于检出阈值。
高衰减时泄漏或绕过衰减器的耦合可能占主导，必须检查每增加10dB共同响应是否约降10倍。若不跟随，停止用标称衰减推算输入。
执行顺序：新增接线后TG OFF新模板 → 每档ON10秒门禁+60秒正式 → OFF60秒检验；拟合只用OFF。先60dB，再70/80/90dB，实际不足时再延长积分；不预设所有档均可检出。
本轮未新增硬件采集，TG保持关闭。待衰减器可用后执行，不把纯软件缩小数值当成物理弱信号试验。
