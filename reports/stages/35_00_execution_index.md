# Stage 35：分步执行与报告索引

> 日期：2026-08-31
> 状态：步骤 1–7 已完成；步骤 8 的极简交互报告已上线，最新交互修订等待用户页面复核；
> 步骤 12 已完成独立 50 Ω 全频基线子阶段，公共源/天空阶段仍未开始
> 总方案：[Stage 35 射电天文噪声科学研究方案](../../reports/stages/archive/35/35_radio_astronomy_noise_study_plan.md)

## 1. 报告边界

Stage 35 不再用一个持续回填的大文件混合计划、运行记录和科学结论。每个实施步骤使用独立
Markdown 文件，只有真实完成的工作才写成结果；未执行步骤只保存范围、前置条件、所需证据
和完成条件。

[v34 硬件与控制基线统一](35_v34_baseline.md)是这 12 步的前置基线，不重复计为其中一步。

## 2. 步骤与当前状态

| 步骤 | 阶段 | 报告 | 当前状态 |
|---:|---|---|---|
| 1 | S0 | [采集架构设计审查](35_01_s0_design_review.md) | `DESIGN_REVIEW_COMPLETE` |
| 2 | S0 | [全频段累加器与 writer 实现](35_02_s0_fullband_accumulator_implementation.md) | `COMPLETE / REPLAY_NOT_RUN` |
| 3 | S0 | [合成数据与 packet replay 验证](35_03_s0_replay_validation.md) | `COMPLETE / READY_FOR_STEP4` |
| 4 | S0 | [60 s 全频段烟雾采集](35_04_s0_60s_smoke.md) | `COMPLETE / GATE_PASS_10MS` |
| 5 | S1 | [TIME-only ADU 控制观测](35_05_s1_time_adu_control.md) | `COMPLETE / READY_FOR_STEP6` |
| 6 | S2 | [三次 15 min 50 Ω SPEC 基线](35_06_s2_50ohm_spec_baseline.md) | `COMPLETE` |
| 7 | S2 分析 | [全量自相关与时间噪声分析](35_07_autocorrelation_analysis.md) | `COMPLETE` |
| 8 | S2 交付 | [人类可读交互科学报告](35_08_self_contained_html_report.md) | `IN_PROGRESS / CLIENT_UI_REVIEW_REQUIRED` |
| 9 | S3 | [定标方案与硬件准备](archive/35/35_09_s3_calibration_plan.md) | `NOT_STARTED` |
| 10 | S3 | [数字比例与温度定标执行](archive/35/35_10_s3_calibration_execution.md) | `NOT_STARTED` |
| 11 | S4 | [单天线天文观测](archive/35/35_11_s4_single_antenna_observation.md) | `NOT_STARTED` |
| 12 | S5 | [28 基线干涉测量](35_12_s5_interferometry.md) | `IN_PROGRESS / INDEPENDENT_50OHM_FULLBAND_BASELINE_COMPLETE` |

## 3. 阶段门控

```text
步骤 1 设计审查
  -> 步骤 2 实现
  -> 步骤 3 replay/合成验证
  -> 步骤 4 板上 60 s 数据完整性验证
  -> 步骤 5 TIME 控制观测
  -> 步骤 6 三扫描正式队列
  -> 步骤 7 全量分析
  -> 步骤 8 单文件报告
  -> 步骤 9–12 定标与天文扩展
```

- 步骤 3 已完成四粒度 replay、合成族、跨 chunk、故障/恢复、全单元 oracle 和独立 Zarr
  复读；它不选择正式原生桶，也不替代采集机 full-rate 门禁。
- 步骤 2 已闭合代码、普通回归和独立 Zarr 复读；它不构成 full-rate replay、板端吞吐或
  10 ms 正式资格结论。
- 步骤 4 已实现并实机验证非hitless的clock-preserving热更新：严格核对LMK profile/SHA、
  selector、RESET与双PLL，journal事务`9ffa82e323a077659e890bd586ff074a`在不写LMK RESET/profile的
  前提下恢复v34，8个tile均state 15、valid 0xffff、MTS ADC/DAC target 416/112。该路径完成了
  一次真实恢复，但20/20资格矩阵尚未执行，分类仍为`EXPERIMENTAL`。
- 初次60 s实测的10 ms/20 ms数据集分别缺51,295和1,665,394帧，均完整保留为失败证据。
  性能采样把主热点定位到每包2048 cell的在线浮点Welford链；receiver改用桶内整数精确矩、
  桶末一次性生成M2，并把arm预热提前量从20 ms增至100 ms，10 ms积分宽度和Zarr schema
  不变。优化后20 s门禁为25,000,000/25,000,000帧，正式60 s门禁为
  75,000,000/75,000,000帧；gap/reorder/duplicate/late、receiver kernel/ring、物理NIC和
  FPGA正式窗口drop均为0。6,743文件、2,154,644,956字节独立验签PASS，10 ms取得正式原生
  桶资格。
- 步骤 5 已在320 MS/s TIME-only模式完成ADC0–ADC7权威30 s控制观测：
  37,500,000/37,500,000包，每路9,600,000,000个RFDC DDC/抽取后complex IQ16样本，
  3,000个10 ms原生桶和1,500个20 ms派生桶完整；所有逐flow事件、receiver/物理NIC和板端
  正式窗口drop均为0。连续50 ms原始PCAP共62,500包、每路16,000,000样本，独立复读无
  seq/frame/sample0断点。步骤5数据清单和独立验证均PASS，步骤6前置门控已经打开。
- 步骤 5、6 的原始数据只落在采集机；仓库只保存 manifest、SHA-256、摘要和报告。
- 步骤 6 若被用户明确作为长任务提交，必须一次性武装完整 A/B/C 队列；确认健康启动后立即
  交还控制权，不在阶段间等待指令或持续轮询。
- 步骤 6 首次队列因错误的`SPEC stream_type=2`假阴性停止。r2修正该问题后取得完整A/B
  两组及B TIME post零丢失数据，但在数据封存后的STOP响应读取遇到connection reset，按
  fail-closed策略停止，C组未执行；安全回读证明板端已停止。STOP已改为传输异常后只读确认
  安全状态再作幂等接受，遥测也从重复4,096 s完整历史改为按sequence增量读取。三项回归
  PASS后提交的r3在A TIME pre正式30 s零丢失封存后，因八fanout worker原始PCAP起点偏斜
  导致50 ms附加门禁不足而停止；后续八阶段未执行。receiver现用共同未来sequence门同步
  八流原始缓存，实流取得65,536包完整连续超集并严格裁出62,500包/50.000 ms，所有接收和
  板端drop增量为0，10 ms正式桶保持不变。2026-08-31 19:16 CST一次性提交全新九阶段r4
  `stage35-s2-50ohm-baseline-r4-20260831-1915`；采集机unit和A TIME pre正式窗口健康，其余
  阶段由同一进程自动接续。r4最终于20:24:08 CST正常完成；三次SPEC和六次TIME独立验证
  PASS，九阶段正式窗口所有板端/receiver/NIC drop与gap增量为0，队列manifest的9个scan、
  115个证据文件身份复核无误，步骤6正式闭合。
- 步骤 8 已交付只读内网交互应用`http://192.168.100.162:8035/`。当前正式数据覆盖
  40.000000–359.921875 MHz；4张首页图、11张单路图、9张两路图和5张全仪器图均在图旁
  给出逐曲线数值、计算公式、权威源路径和当前选择的实算结果。最终Chromium门禁确认
  29/29说明完整、多选/白噪声参考/相位门控正常、外网请求0、严重console错误0。
- 步骤 12 本轮只执行八路独立 50 Ω 的全频仪器伪相关底。公共噪声源、真实天线、K/Jy/SEFD、
  天空相位和成像仍未开始；A/B/C三次900 s全频复相关及前后TIME控制现已完成且九阶段
  formal integrity均为true。完成该子阶段不等于步骤 12 全部闭合。
- 2026-09-03 用户否定 29 图版本的叙事与公式呈现，步骤 8 再次打开为
  `IN_PROGRESS / SIMPLE_REPORT_REWORK`。候选正文只允许“单个 ADC”和“两个 ADC 的相关结果”
  两个入口，各自只保留 TIME_ONLY、F-engine 和 Allan 方差三步。新的 4096 谱原始见证与
  全频 100 ms＋1 s 复相关尚未完成验收，当前 8035 页面只作为旧版回退服务保留。
- 首次极简版队列在正式样本窗口开始前发现板端启动瞬态 `rfdc_dropped delta=19`；队列错误地
  把这段非科学启动区间当成正式窗口，因而 fail-closed 停止，未发布任何复相关产品。该失败
  证据原样保留。门禁已恢复为此前验证过的两段边界：启动区间记录板端计数且严格检查接收端
  零丢包，正式区间继续同时要求板端与接收端零丢包。修正版完整队列
  `stage35-simple-v2-20260904-1420` 已于 2026-09-04 14:18:57 CST 在 GB10 一次性重新提交；
  60 s 全频烟雾采集已跨过启动门禁并进入 `running`，其余阶段由同一进程自动接续。
- v2 的 60 s 烟雾、4096 谱原始见证和 900 s 正式全频 100 ms＋1 s 采集均已完成，三阶段
  manifest与独立数值验证通过；正式数据约 20.9 GB。队列最终停在候选浏览器门禁，原因是
  前端把 TIME_ONLY 的`A-pre`错误地作为 F-engine 原始谱 capture 参数，而权威标签实际为
  `simple-4096`。这没有影响或污染采集数据，8035 也未切换。参数串线修复后，浏览器验证、
  原子切换和最终身份生成已由独立恢复任务
  `t510-stage35-simple-v2-browser-resume1-20260904-1510.service` 于 15:09:11 CST 提交；恢复任务
  只读复用已验签数据，不重新采集。
- resume1 的单 ADC 页面通过后，在双 ADC 原始逐帧复乘中遇到零功率样点；此时归一化相关
  幅度数学上未定义，服务端产生`NaN`并被严格 JSON 编码门禁拒绝。现已明确编码为`null`、
  保持相位不可靠标记且不伪造为0，零功率回归 oracle 通过。修正版恢复任务
  `t510-stage35-simple-v2-browser-resume2-20260904-1525.service` 已于15:20:37 CST健康启动。
- resume2 已跑完全部功能检查，唯一失败项是 Chromium 自动请求未声明的`/favicon.ico`得到
  404，并被“零严重控制台错误”门禁拦截。候选页现使用内嵌同源图标，不产生该请求；最终
  恢复任务`t510-stage35-simple-v2-browser-resume3-20260904-1530.service`已于15:23:24 CST
  健康启动，仍只读复用已验签数据。
- resume3 最终正常退出，原队列状态已闭合为`completed / error=null`。真实 Chromium 验收
  `PASS`：4096 谱原始见证、多 ADC/多 pair、4＋1 懒加载分页、白噪声参考、公式及点击实算、
  100 ms/1 s 产品均通过，外网请求0、严重控制台错误0。8035 已原子切换至
  `stage35-simple-v2-20260904-1420`，步骤8据此闭合为
  `COMPLETE / INTERACTIVE_SIMPLE_REPORT_BROWSER_VERIFIED`；步骤12只闭合独立50 Ω全频
  100 ms基线子阶段，整体仍为`IN_PROGRESS`。
- 桌面端随后暴露同页16张`scattergl`图耗尽浏览器WebGL上下文的问题。15:37部署的最多3张
  活跃图v1仍不足：`Plotly.purge`不能保证上下文立即归还，滚动后仍可出现Plotly遮罩。v2改为
  全页只保留1张活动Plotly图，离屏时显式调用`WEBGL_lose_context`后再purge，并分别显示
  WebGL 1/2及真实渲染器；Allan等全部trace仍冻结为`scattergl`，不存在SVG/CPU回退。
  2026-09-04 16:05:20 CST，单路16图和双路16图逐张门禁均确认最大活动图数为1、外网请求0、
  严重控制台错误0，v2已原子切换到8035，旧代码保留。
- 用户的Apple M2 Max随后证明WebGL 1/2和ANGLE Metal均正常，v2失败源于应用主动
  `WEBGL_lose_context`与异步`Plotly.react`竞争，而非浏览器能力不足。v3改为全部32个图槽
  共享一个长期存在的Plotly GPU画布，滚动时只移动该画布并串行更新数据，不再正常销毁或
  新建上下文。候选门禁确认单路16图、双路16图始终使用同一
  `stage35-shared-gpu-surface`，最大活动图数1、外网请求0、严重控制台错误0；
  2026-09-04 17:14:56 CST已原子切换至8035。
- 目标端确认为Chrome 151.0.7922.138 arm64；v3仍在第一张图取得上下文前失败。复核发现线上
  使用Plotly 4.0.0，而官方当前将4.0.0-rc.0列为预发布、3.7.0列为稳定最新版。v4已固定为
  本地同源Plotly 3.7.0并增加版本/user-agent/上下文创建状态诊断，于2026-09-04 17:23:39
  CST切换到8035；步骤8等待目标Chrome实际复核，不以GB10无显示headless替代客户端结论。
- 完整Console最终给出`Too many active WebGL contexts`，确认失败后的自动重试和trace身份变化仍
  会反复建立Plotly GL层。当前实现冻结一个Plotly图、12个`scattergl`槽位和稳定UID：整个
  门禁只执行1次`newPlot`，其后59次均在原图上更新，失败后禁止自动重试。按用户要求公开地址
  和静态资源不再带v4/v5命名，唯一入口固定为`http://192.168.100.162:8035/`；HTML/JS设置
  `no-store`。2026-09-04 17:32:47 CST已切换，等待目标M2 Max Chrome复核。
- 162本机和M2 Max随后都显示“当前12个固定trace槽＋Plotly 4.0.0”，证明浏览器把新应用与
  此前缓存的同名Plotly资源错配加载，而非两台机器同时缺少WebGL。2026-09-04 17:41 CST正式
  HTML改用此前从未出现、无版本查询串的固定资源名`stage35-app.js`和
  `stage35-plotly.min.js`，并在启动时强制核对Plotly 3.7.0。Chromium 151候选门禁记录
  `newPlotCalls=1`、`reactCalls=56`、`fixedTraceSlots=12`、`fatal=false`，外网请求0、严重
  控制台错误0；8035已原子切换，步骤8仍等待目标M2 Max Chrome最终复核。
- 缓存错配消除后，Mac加载3.7.0仍在第一次`newPlot`失败；162真实X11桌面Chrome 151复现同一
  问题。根因收敛为严格`script-src 'self'`CSP与Plotly标准包的函数构造器不兼容。替换为同版
  官方Plotly strict包后，162硬件门禁使用`ANGLE (NVIDIA GB10/PCIe, OpenGL 4.5.0)`逐张通过
  单路16图和双路16图，WebGL遮罩0、`newPlotCalls=1`、`reactCalls=60`、外网请求0、严重错误0；
  此次没有headless/SwiftShader或遮罩豁免。正式资源以固定名
  `stage35-plotly-strict.min.js`和SRI身份交付，2026-09-04 17:57 CST已原子切换8035，等待目标
  M2 Max Chrome复核。
- 用户截图随后显示窄屏单列中的长公式/SHA把说明栏撑出卡片，且Plotly重复标题与顶部图例重叠。
  当前网格和子元素已改为可收缩宽度，长身份可断行，KaTeX按计算步骤逐行显示；Plotly内部重复
  标题已删除，图例使用独立顶部空间。162真实硬件Chrome 151在1705 px与1035 px视口均通过：
  页面横向溢出false、逃出卡片元素0、空公式0、重复图标题0、严重控制台错误0。CSS为
  此前未使用的固定名`stage35-app.css`并带SRI，绕过旧CSS缓存；2026-09-04 18:52 CST已原子
  切换8035。
- 用户进一步澄清TIME_ONLY图应解释数字在采集链中的含义，而不是在正文重复文件和SHA身份；
  同时指定默认图工具为Pan，要求保留其他工具，并用小叉代替实心圆。当前正文已明确TIME_ONLY
  是ADC采样后经RFDC数字下变频和12倍抽取得到的320 MS/s复数I/Q，不是3.84 GS/s ADC原始
  转换码；文件、数组和SHA只保留在底部折叠区。未经平均的TIME_ONLY和F-engine I/Q接口现按
  JSON整数返回，分桶平均仍保留小数。每张时间序列图新增独立的`hv`阶梯连接开关，Allan图
  不使用阶梯线。162真实硬件Chrome 151验收记录默认`dragmode=pan`、删除工具列表为空、所有
  测量标记为`x`、阶梯状态切图不串扰、NVIDIA GB10渲染、外网请求0、严重错误0；2026-09-04
  19:50 CST已切换8035，等待用户页面复核。
- 用户复核发现复可见度Allan图的横轴消失。浏览器边界测量确认共享Plotly画布从前一张620 px
  双层图继承高度，而Allan外层仍为390 px，横轴在容器外被裁剪。当前每张图接管共享画布时
  都显式同步Plotly和外层高度：普通图520 px、幅度/相位双层图620 px。全页硬件门禁逐图检查
  横轴标题与刻度均在容器内部，正式8035复测的Allan图容器、画布和SVG均为520 px，横轴完整
  可见；2026-09-04 20:05 CST已切换。
- “一个或多个ADC/ADC对”已按用户语义改为同图比较，不再为每个对象复制整套卡片。当前每个
  章节每页只有一个分组卡片；本页最多4个ADC或ADC对，其相同物理量的曲线叠加在同一幅图，
  图例明确写出对象与频率。超过4个对象仍分页，第二页继续同样分组。单图固定GPU槽位相应从
  12增至64，仍只复用一个WebGL画布。162真实Chrome 151验收覆盖ADC0/ADC1及ADC0–ADC1/
  ADC2–ADC3同图曲线、4+1对象分页、NVIDIA GB10硬件渲染、外网请求0、严重错误0；
  2026-09-04 20:27 CST已原子切换8035。
- I/Q与幅相标记现成对区分：I和幅度为小叉，Q和相位为空心小三角；弱相关相位为灰色空心
  小三角，Allan实测点保持小叉。162真实Chrome/GB10门禁通过后已切换8035。
- 2026-09-04 用户要求把全部配置移入按章节分组的左侧栏，并补采连续900 s TIME_ONLY。
  新实现不保存约9.2 TB原始流，而是在GB10接收机上处理全部320 MS/s复数I/Q，并只封存
  10 ms的平均I、平均Q、`mean(I²+Q²)`、有效样本数和质量账本。双路入口同时删除
  TIME_ONLY瞬时复乘与TIME软件FFT相关参照，只保留F-engine复可见度和其Allan方差。
  完整队列`t510-stage35-time900-ui-v1-20260904-2141.service`已一次性登记60 s烟雾、900 s
  正式采集、独立复算、只读数组、候选应用、真实浏览器验收、8035原子切换和原地身份。
  采集与数值验证完成后，首次浏览器门禁因用子字符串检查旧URL参数`time=`而误命中新参数
  `time_capture=`并停止；修正为解析实际查询参数键后，候选在162真实硬件Chrome上通过。
  8035已切换到`stage35-time900-ui-v1-20260904-2141`，queue=`completed`、error=`null`；
  1 s接口实测返回900个TIME_ONLY点。步骤8仍等待用户页面复核，保持
  `IN_PROGRESS / CLIENT_UI_REVIEW_REQUIRED`。

## 4. 状态写法

每个分步报告只使用事实状态：`NOT_STARTED`、`IN_PROGRESS`、`BLOCKED`、
`COMPLETE`，并可附加清楚的工程分类。`COMPLETE` 必须同时给出证据位置、数据身份和验证
结果；创建了报告骨架不等于该步骤已经执行。
