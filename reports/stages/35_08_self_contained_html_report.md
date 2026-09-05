# Stage 35 步骤 8：自包含 HTML 科学报告

> 状态：`IN_PROGRESS / CLIENT_UI_REVIEW_REQUIRED`
> 前置条件：[步骤 7](35_07_autocorrelation_analysis.md)完成

## 1. 本步目标

把未定标、50 Ω、自相关噪声表征交付为一个不依赖 CDN、外部 CSS/JavaScript 或关键外部
图片的单文件 HTML。大体积 Zarr/Parquet 保持为权威数据档案，HTML 记录其身份、大小与
SHA-256。

## 2. 必需内容

- ADC0–ADC7 结构完全相同的章节；
- TIME ADU、4096-bin 带通与全 bin 动态谱；
- `frequency × tau` 的绝对散布和 ADEV；
- `frequency × lag` 自协方差/ACF；
- 固定杂散及邻近 bin 放大，同时保留未删除的全带原始结果；
- 任意真实 bin 选择器及 15 s 全原生桶细节；
- 2/4/15/30 s、Allan、ACF、temporal PSD 和分布面板；
- 可检索完整数值表和浏览器内导出；
- 数据 manifest、分析版本、mask/回归/bootstrap 和质量事实。

## 3. 渲染限制

统计计算不得使用抽点。长概览允许仅渲染降采样，但必须标注，并使用 min/max envelope；
选中的 15 s 窗必须显示全部原生桶。禁止红绿灯、“8 路中 N 路通过”或只给百分比。

## 4. 完成条件

在断网环境打开单个 HTML 后，交互、图、表和导出均可用；抽查值与 Parquet/Zarr 一致；
报告 SHA-256 与归档身份明确。完成本步即闭合 Stage 35 第一阶段，不自动授权步骤 9–12。

## 5. 执行记录

### 5.1 输入冻结

2026-09-01已完成步骤7终态验收，本步只读使用下列正式分析根，不再启动采集或修改板卡：

```text
root: /var/lib/t510/stage35/analysis/stage35-s2-r4-analysis-v1-20260831-2059
analysis manifest SHA-256:
d999cad943cacecfeb19dceb6f91751390a2097f60f104e8524ecbb4e06b7b09
```

48/48分块、98,304行逐扫描指标、32,768行跨扫描指标和48行TIME控制指标已
独立验签。报告生成期间保留Parquet/Zarr为权威数值层，HTML中的渲染降采样或
表示编码不参与统计重算。

### 5.2 生成器与正式队列

新增`scripts/stage-35/t510_stage35_s2_html_report.py`、
`scripts/stage-35/t510_stage35_s2_html_verify.py`和
`scripts/stage-35/t510_stage35_s2_html_queue.py`。生成器内嵌完整98,304行指标CSV、
全bin带通、frequency×tau、frequency×lag、Allan、ACF、PSD、TIME ADU以及任意
ADC/bin的Scan A首15 s全1,500个10 ms桶展示数据。长动态谱使用全部900个1 s窗
的min/max envelope，图形编码不参与统计。HTML不引用CDN、外部CSS/JavaScript
或外部图片。

2026-09-01 12:03:38 CST已一次性提交生成和独立验签两阶段队列：

```text
unit: t510-stage35-s2-html-v1-20260901-1150.service
root: /var/lib/t510/stage35/reports/stage35-s2-r4-report-v1-20260901-1150
phase 1: generate single-file HTML + report manifest + SHA-256
phase 2: decode every embedded payload and independently verify bytes/SHA/CSV rows/offline references
```

健康检查时unit为active/running，queue为running、error null，generate为running且
independent_verify已正确登记为pending。确认两阶段自动接续已武装后停止轮询；
不把生成启动写成步骤8完成。

### 5.3 最终验收与交付

队列于2026-09-01 12:04:54 CST正常结束，systemd为`Result=success`、
`ExecMainStatus=0`；generate和independent_verify两阶段均`completed`、returncode 0，
queue为`completed`、error null。正式单文件报告为：

```text
path: /var/lib/t510/stage35/reports/stage35-s2-r4-report-v1-20260901-1150/
      stage35_s2_uncalibrated_50ohm_autocorrelation.html
bytes: 324,805,196
SHA-256: 6aa8f061096d267f6de52c5d5dc82964e8fb6d3cb8a438e35418ee50ae55fb27
report manifest SHA-256:
e29896934599d60370ae45e8752ff31a596c93bf563de94375e97edd00c50788
```

独立文件级验证将全124/124个内嵌payload逐一base64解码、gzip解压并复算
原始字节数和SHA-256，全部匹配；98,304行完整指标CSV行数正确，
`external_network_references=0`、errors为空。

另用Chromium 151在断网语义下直接打开`file://`报告完成真实浏览器验收：

- 8个ADC章节和124个内嵌payload全部识别，TIME图与ADC0默认面板完成渲染；
- 切换到Scan B / ADC0 / global_bin 100后，ACF、PSD、min/max动态谱和15 s原生桶图均更新；
- 完整数值表按A/ADC0/bin3328检索得到1行、82列；
- 浏览器实际网络资源请求为0，严重console错误为0；
- 浏览器证据`browser_verification.json`和`browser_smoke.png`的SHA-256分别为
  `967132da537c557d01d2bf605be1889b8d4cbede29918caffc43771c0741b38e`与
  `c2962762ff8254afd6dc5b0b8af8b950969a17fed28c29f2cf81dd02d07794e4`。

图形值与表格值的抽查同时覆盖真实bin 100与bin 3328，报告对输入分析manifest、
显示编码和权威Parquet/Zarr边界的记录完整。步骤8据此闭合，Stage 35第一阶段
“未定标、50 Ω、单路自相关噪声表征”完成。本结论不自动授权步骤9–12。

## 6. v1 审阅不通过与 v2 返工

2026-09-01用户审阅后明确否定v1交付质量：图形粗糙，缺少频率轴、坐标名、单位、
刻度、色标、可见数值和科学说明，不能因为数据身份和离线交互验收通过就称为
合格科学报告。v1文件及证据保留为被否定的历史产物，不再作为Stage 35第一阶段
正式交付。步骤8重新打开，Stage 35第一阶段的报告闭合结论同步撤回。

v2使用原步骤7已验签分析，不重新采集或修改板卡。新报告固定为浅色科研出版风格、
中文正文与标准英文符号，使用内嵌Plotly.js 4.0.0与高性能Canvas混合渲染。频谱必须
重排为860.000000–1179.921875 MHz单调RF轴，并以global_bin作顶部副轴。先用真实数据
交付全局概览加ADC0完整样章；样章审阅确认后才启动A/B/C×ADC0–7正式全量生成。

### 6.1 v2冻结实现与样章队列

2026-09-01已冻结`scripts/stage-35/config/stage35_s2_report_v2.json`，只读绑定步骤7分析manifest
`d999cad943cacecfeb19dceb6f91751390a2097f60f104e8524ecbb4e06b7b09`。本地归档的
Plotly.js 4.0.0 SHA-256为
`14461f3b4c91c8bb590a99d6d03c3fd031ca40eec07ebab79a5e3eac107cd7ca`，MIT许可证
文本SHA-256为`8c45d9eaf50c2f72dd9c7ab9ef440788ba58a3538484b5c51c1f17d5128752e7`。

v2生成器实现float64权威指标、float32注册15 s时序和逐层uint16动态谱显示编码；显示
编码不进入统计。实数结构冒烟确认`quick=[3,8,4096,53]`、跨扫描数组
`[8,4096,7]`、四个RF锚点完全匹配，ADC0样章数值浏览器包含12,288行、82列且字段
字典逐列覆盖。异常导航为8路×4种指标×前10 bin共320行，A/B/C值完整，960 MHz固定项
另列。

样章正式队列为：

```text
unit: t510-stage35-s2-report-v2-sample-20260901-1510.service
root: /var/lib/t510/stage35/reports/stage35-s2-report-v2-sample-20260901-1510
mode: sample (global overview + complete ADC0)
phases: generate -> payload_verify -> numeric_parquet_zarr_verify
        -> offline_chromium_verify -> archive_identity
```

10 s健康检查时unit为`active/running`、queue为`running`、error为null；generate为
`running`，其余四阶段已完整登记为`pending`并将自动接续。此前`...-1506.service`
因提交命令漏传Chrome二进制参数在创建输出目录前以argument error退出，不含数据处理或
半成品；失败unit日志保留，不计为样章执行。依照长任务规则，健康启动后停止轮询，不将
启动状态写成样章完成。样章通过全部五阶段并经用户审阅前，本步骤继续保持
`IN_PROGRESS / REPORT_REWORK_REQUIRED`。

### 6.2 人类可读版重设计与新样章队列

`...-1510.service`最终在`payload_verify`失败：旧验证器用正则扫描整份内嵌源码，误把
Plotly源码、许可证和配置JSON中的URL当成HTML网络依赖。该失败样章保留，不覆盖、不冒充
正式交付。随后按用户审阅意见把正文改为“先讲结论，再给证据”的单列科学叙事：

- 首页直写50 Ω数据在科学积分尺度上不是理想白噪声，且剔除DC、频带边界、960 MHz及邻
  bin后，15 s实测/白噪声中位仍为`3.814545×`；
- TIME正文只给I/Q真实ADU码值直方图、分位区间、30 s极值和削顶事实，不再使用
  `complex RMS`主面板；六份`histogram.csv`路径和SHA-256已冻结进配置及报告manifest；
- Allan主图提升到正文前部，显示全部98,304个ADC/bin/scan、12个τ、P05–P95包络、中位线、
  理想值1和预标记剔除结果；普通代表、948.593750 MHz异常簇及960.000000 MHz固定项均与
  `τ^-1/2`白噪声参考同图；
- 15 s实测相对散布中位为`0.369994%`，理想值为`0.0969826%`，比值`3.815057×`；等效
  白噪声时间`1.03060 s`，积分效率`6.87065%`，白噪声时间代价`14.5547×`；2 s到30 s
  实测配对中位只改善`1.68722×`，而白噪声应改善`3.87298×`；
- ACF正文用“原序列与延迟序列是否仍同涨同跌”解释；`|ACF(1 s)|`中位`0.0138668`、
  P95 `0.0456400`。PL温度单变量即时线性回归R²中位`0.000425870`，只写成该模型解释不了
  问题，不写成已排除温度；
- ADC0普通代表频点由冻结规则确定为global_bin `295`；同时提供积分最差、记忆最强、
  960 MHz和自定义bin快捷选择。Plotly坐标统一传入`title.text`，global_bin副轴用隐藏绑定
  trace强制创建。

离线引用验证已改为解析真实HTML `src/href`属性；数值验证独立复算全部Allan τ、四个积分
尺度、三类命名频点、全量/预标记剔除统计、快捷bin和六份ADU直方图逐码计数。浏览器验证
新增正文术语、白噪声参考线、真实坐标名、快捷频点、零网络资源与严重console错误检查。

2026-09-01 16:53:13 CST一次性提交新的五阶段ADC0样章队列：

```text
unit: t510-stage35-s2-report-v2-human-sample-20260901-1655.service
control: /var/lib/t510/stage35/control/s2-report-v2-human-20260901-1652
root: /var/lib/t510/stage35/reports/stage35-s2-report-v2-human-sample-20260901-1655
report: stage35_s2_50ohm_human_readable_v2_sample.html
phases: generate -> payload_verify -> numeric_parquet_zarr_verify
        -> offline_chromium_verify -> archive_identity
```

10 s健康检查时unit为`active/running`，queue为`running`、error为null，`generate`为
`running`，其余四阶段均已登记为`pending`并由同一进程自动接续。依照长任务规则，此时
停止轮询并交还控制权；不把健康启动写成验收完成，也不在新报告尚未闭合时生成全8路版本。

## 7. 只读交互应用与全频复相关扩展

用户后续明确要求不再以单个静态 HTML 作为最终阅读入口。交付改为固定地址
`http://192.168.100.162:8035/`的只读内网应用；旧静态报告服务在候选应用全部验收和原子
切换前保持运行，不删除旧文件。应用正文严格区分 TIME post-DDC IQ16 ADU、F-engine IQ16
count、`|X|² count²`和两路`Vab=<Xa·conj(Xb)>`，不把这些量混称为 ADU。

交互页现已实现一个或多个 ADC、RF MHz/global_bin、A/B/C、TIME pre/post 控制段和一个或
多个 ADC pair 的 URL 可复现选择。少于等于12条时叠加原曲线，更多时自动转为热图；快捷
频点包括每路 r4 实算的普通代表、积分最差、记忆最强、948.593750 MHz异常簇、960 MHz和
自定义频点。TIME页同时给出原始 I/Q 包络/逐样本、10 ms I/Q中心与典型摆幅、普通 Hann
FFT、短/慢 Allan与ACF；F-engine页把短时I/Q count、900 s绝对count²和相对变化分轴显示。
所有Allan图明确叠加`τ^-1/2`，两路相位在`|γ|<0.05`时隐藏。

候选应用的开发数据浏览器门禁已通过：4张首页图、11张单路图、9张两路图均渲染，RF MHz
选择正确映射到global_bin，多选热图、白噪声参考、有效样本数和相位门控均在浏览器运行时
得到确认；外部网络请求和严重console错误均为0。该结果只验证实现，不是新A/B/C复相关的
科学结论，也不授权提前停止旧8035服务。

正式一键队列身份冻结为：

```text
unit: t510-stage35-xcorr-explorer-v1-20260901-2200.service
queue: stage35-xcorr-explorer-v1-20260901-2200
pipeline: synthetic CUDA/CPU oracle + frozen real SPEC PCAP oracle
          -> 60 s full-rate CUDA smoke
          -> A/B/C × (TIME pre 30 s + raw 50 ms, XCORR 900 s, TIME post 30 s + raw 50 ms)
          -> manifest/numeric/Zarr verification -> raw index -> full-band analysis
          -> candidate browser verification -> atomic 8035 cutover -> archive identity
```

队列任一阶段失败均安全停流并保留证据，旧8035继续服务；只有全部验证通过才切换到
`t510-stage35-explorer.service`。当前步骤继续保持`IN_PROGRESS / INTERACTIVE_REWORK`。

### 7.1 40–360 MHz 正式队列与应用切换完成

用户将正式RF范围改为40–360 MHz后，中心频率固定为200 MHz，实际4096通道范围为
`40.000000–359.921875 MHz`、通道间隔`0.078125 MHz`。最终队列
`stage35-40-360mhz-hpc-v1-20260902-1400-xcorr-queue`已完成A/B/C各三阶段：
TIME pre 30 s、XCORR 900 s、TIME post 30 s。九个阶段状态均为`completed`且
`formal_integrity.ok=true`；queue为`completed`、error为null。

```text
queue state:
/var/lib/t510/stage35/stage35-40-360mhz-hpc-v1-20260902-1400-xcorr-queue/queue_state.json
SHA-256: 7b32290ccb94cbf777b218707b99e9f31309918781cdaa261314bac85817a512

queue manifest: 9 scans, 293 files
/var/lib/t510/stage35/stage35-40-360mhz-hpc-v1-20260902-1400-xcorr-queue/queue_manifest.json
SHA-256: ed87a9008cb98d560d35fe13fe39ff005e486db2e29a0a073d85a72a9cb7a131

analysis root:
/var/lib/t510/stage35/analysis/stage35-40-360mhz-hpc-v1-analysis

explorer data release:
/var/lib/t510/stage35/explorer/releases/
stage35-40-360mhz-hpc-v1-20260902-1400-xcorr-time-retry2
```

全部数值和浏览器门禁通过后，`t510-stage35-explorer.service`已正式提供
`http://192.168.100.162:8035/`。本次切换复用接收机上的Parquet/Zarr和原始见证数据，
没有重新计算或归档搬移科学数据。

### 7.2 每图公式、来源和实算值说明

2026-09-03按用户审阅意见再次修改阅读层。应用中的29张Plotly图现在统一采用“左图、右说明”
的单列正文布局；每个说明栏固定包含五部分：

1. `本图实际算得`：随当前ADC、频点、扫描、TIME段和ADC pair选择动态重算并显示数字；
2. `曲线分别是什么、图上有哪些数`：列出每条legend曲线的名称、线型/颜色、点数、首末值、
   最小值、平均值和最大值；多于12条转热图时显示单元数、中位和范围；
3. `具体计算公式`：明确列出ADU概率、`I²+Q²`、相对功率、重叠Allan、`τ^-1/2`、ACF、
   Welch temporal PSD、`Vab`、`|γ|`、相位门控、积分散布、谱峰度、温度R²和扫描间散布；
4. `数值来源`：显示所选原始PCAP及SHA-256、解包`iq16.npy`/`summary.npz`、自功率Parquet
   分区或复相关`xcorr.zarr`及具体数组名；
5. `用人话怎么读`：说明该数回答的观测问题和不能越过的物理边界。

服务端`/api/meta`为此新增只读`provenance`字段，覆盖六份TIME histogram、六份TIME raw、
六份SPEC raw、A/B/C自功率分析分区、A/B/C全频复相关Zarr、动态谱显示层和完整统计源。
应用代码不接受任意路径参数，也未新增写接口。

最终正式部署浏览器验收使用2个ADC、2个频点和2个pair遍历全部四个图表页：

```text
overview:   4/4 figures with result/formula/source notes
single ADC: 11/11
ADC pair:   9/9
statistics: 5/5
total:      29/29
external network requests: 0
severe console errors: 0
```

证据保存在：

```text
/var/lib/t510/stage35/explorer/validation/figure-notes-20260903/browser_verification.json
SHA-256: 1e7f11a3ea70b55cb4b493fdf13e316c9b9dc02e456dad2d6b16a85c20dacf9d

/var/lib/t510/stage35/explorer/validation/figure-notes-20260903/browser_smoke.png
SHA-256: 243ed4e86464eee2c83cfdd039bbcbd510f2f0f9b8845857890de834820a8098
```

正式`figure_notes.js` SHA-256为
`65c164c9f86cc533d09a8dd81e9dd29ff67c6c43cdc79e9591d0209ef940cb55`。步骤8据此闭合为
`COMPLETE / INTERACTIVE_APP_LIVE`；这只闭合人类可读交付，不改变未定标边界，也不把独立
50 Ω 复相关写成天空观测。

## 8. 极简人类可读版再次返工

2026-09-03 用户审阅 29 图版本后明确否定其信息结构：图太多、缩写和工程统计抢占正文，
读者无法从“原始数值是什么”顺着计算走到 Allan 方差。此前应用和全部旧数据继续保留，
但不再把该页面称为最终交付；步骤 8 重新打开为
`IN_PROGRESS / SIMPLE_REPORT_REWORK`。

新正文严格只保留两个平行入口：单个 ADC 与两个 ADC 的相关结果。每个入口都只回答三件
事：TIME_ONLY 原样点及时间平均、F-engine 原始帧及时间平均（另列普通 Hann FFT 参照）、
以及从相应 F-engine 序列逐步计算 Allan 方差。ACF、PSD、动态谱、温度回归、积分效率、
矩阵、谱峰度和通用统计卡全部退出正文。每张图旁固定写“这些点是什么、原始数据是什么、
怎么算、当前算得什么、怎样理解”；公式由本地 KaTeX 渲染，点击 Allan 实测点必须返回
该点实际使用的 `N、m、K、τ`、平方差之和与最终值。

本次需要在 GB10 采集机上新增且原地保留两项权威输入：4096 个完整 F-engine 谱的 IQ16
短时见证，以及一次 900 s、4096 通道、28 对 ADC 的全频 100 ms＋1 s 复相关。1 s 产品必须
由同批十个 100 ms 产品按有效谱数合并。候选应用在全部数值和真实浏览器门禁通过前不会
替换当前 8035 服务；不调用工作站或 HPC 计算，也不制作数据归档副本。

完整队列已于 2026-09-03 21:31:53 CST 一次性提交：

```text
unit: t510-stage35-simple-v1-20260903-2130.service
queue: /var/lib/t510/stage35/stage35-simple-v1-20260903-2130-queue
pipeline: oracle -> 60 s fullband-100 ms smoke -> 4096 raw spectra
          -> 900 s fullband-100 ms formal -> numeric/SHA verification
          -> six TIME FFT references -> candidate browser verification
          -> atomic 8035 cutover -> in-place identity
```

健康检查时 unit 为 `active/running`，queue 为 `running`、`error=null`，60 s 烟雾阶段为
`starting`，后续步骤均已登记并由同一进程自动接续。依仓库长任务规则此时停止轮询；这只
证明完整队列已健康启动，不表示新数据、浏览器验收或 8035 切换已经完成。

### 8.1 首次停止与修正版重提

上述 v1 队列随后在正式样本窗口尚未开始、`packets_published=0` 时 fail-closed 停止。直接
原因是 START 期间板端 `rfdc_dropped` 增加 19，而极简队列错误地将“CUDA 环预热和 16 路
对齐之前的启动区间”也纳入正式零丢失门禁。CUDA 合成整数 oracle、冻结 PCAP 的 CPU/CUDA
对照以及 Allan 常数、白噪声斜率和复向量跨相位 oracle 均已通过；失败任务没有生成可供
报告使用的烟雾或正式复相关产品，板卡和接收任务已安全停止，旧 8035 服务未被切换。

修复没有放宽科学数据窗口的质量要求：启动区间的板端增量继续写入证据，启动区间只以接收
端丢包作为阻止武装的条件；未来 `sample0` 正式窗口则仍从 START 后快照开始，对板端和接收
端的 drop、gap、ring overflow 全部执行零容忍。该边界与此前成功的全频复相关队列一致。

2026-09-04 14:18:57 CST 已使用全新任务号一次性重新提交原完整流水线：

```text
unit: t510-stage35-simple-v2-20260904-1420.service
queue: /var/lib/t510/stage35/stage35-simple-v2-20260904-1420-queue
pipeline: oracle -> 60 s fullband-100 ms smoke -> 4096 raw spectra
          -> 900 s fullband-100 ms formal -> numeric/SHA verification
          -> six TIME FFT references -> candidate browser verification
          -> atomic 8035 cutover -> in-place identity
```

复核时 unit 为 `active`，queue 为 `running`、`error=null`；60 s 烟雾阶段已跨过修正的启动
门禁，接收任务为 `running`，`ring_drops=0`。后续步骤由同一进程自动接续，当前仍保持
`IN_PROGRESS / SIMPLE_REPORT_REWORK`，不提前宣称新报告或正式数据完成。

### 8.2 科学数据完成，浏览器参数串线恢复

v2 后续完成了 60 s 烟雾、4096 个完整原始 F-engine 谱和 900 s 全频 100 ms＋1 s 正式
复相关；三阶段状态均为`completed`，正式数据 manifest 覆盖 67,545 个文件、约 20.9 GB，
SHA-256 为`8da17bc97c087b5eb6945e967c0bbd4dcc0416c929d14867c2d9caf7e279b3e0`。
队列没有在采集或数值验证处失败，而是在候选浏览器验收发现前端参数串线后停止：公共参数
函数把 TIME_ONLY 选择`A-pre`同时发送给 F-engine 原始谱接口，而新谱在权威索引中的标签为
`simple-4096`。服务器因此正确拒绝未知 F-engine capture，8035 保持旧版。

现已把 F-engine 原始帧选择固定到`/api/v2/meta`返回的`spec_capture`，TIME_ONLY 和它的普通
FFT仍独立使用`A-pre`。首次浏览器失败 JSON 原样改名保留；已验签的科学数据不重采、不搬移。
2026-09-04 15:09:11 CST 提交
`t510-stage35-simple-v2-browser-resume1-20260904-1510.service`，只执行真实浏览器全验收、8035
原子切换和最终身份生成。恢复任务健康启动后 queue 为`running`、`error=null`；在其完成前
步骤8继续保持`IN_PROGRESS / SIMPLE_REPORT_REWORK`。

resume1 已证明单 ADC 页面可完整加载，但切换到双 ADC 原始逐帧复乘时，个别样点的两路功率
分母为0，`|V|/sqrt(PaPb)`在数学上未定义。服务端原先把该缺测值保留成`NaN`，严格 JSON
编码门禁按设计拒绝非标准数值并停止。修复将这种情况明确输出为 JSON `null`，同时将相位
标记为不可靠；没有把缺测值伪造成相关系数0。浏览器端也把`null`显示成破折号而不是数字0。
零功率 oracle 已验证`[NaN,1]`正确编码为`[null,1.0]`。

2026-09-04 15:20:37 CST 已提交
`t510-stage35-simple-v2-browser-resume2-20260904-1525.service`；健康检查为`active/running`、
queue 为`running`、`error=null`。它继续执行完整双路页面、分页、URL、离线资源、控制台和
8035 原子切换门禁，不重新读取板卡或采集新数据。

resume2 已执行到浏览器最终日志检查，数据视图、公式、双路弱相位、分页、URL复现和零外网
请求等前序检查均未触发失败；唯一严重日志是 Chromium 自动请求`/favicon.ico`得到404。
候选页已增加 CSP 允许的内嵌 SVG 图标，避免额外网络资源和404。2026-09-04 15:23:24 CST
提交最终恢复任务`t510-stage35-simple-v2-browser-resume3-20260904-1530.service`；健康检查为
`active/running`、queue 为`running`、`error=null`，仍不重新采集。

### 8.3 极简版最终验收与切换

resume3 正常退出，原队列`stage35-simple-v2-20260904-1420`最终状态为`completed`、
`error=null`。真实 Chromium 验收为`PASS`：F-engine 原始见证确认为4096个完整谱；多 ADC、
多 ADC pair、每页最多4个对象及第2页1个对象、URL状态复现、Allan点实算说明、100 ms与1 s
复可见度、弱相关相位门控和本地公式渲染均通过；外部网络请求为空，严重控制台错误为空。

8035 已原子切换到：

```text
http://192.168.100.162:8035/
data release: /var/lib/t510/stage35/explorer/releases/stage35-simple-v2-20260904-1420
browser verification SHA-256:
ae8aed23f34e480e8f91ace7d2b26248ee066ff99fd269bcbf0683fcfadafbec
queue state SHA-256:
38a25f97faad778cbddf1279f5909916f26c5205f77d0f81cd6a735e253df29b
queue manifest SHA-256:
f2a5651e50d5fde45cad9cc2f8d8646e5c407bb173a8786de952368c5a1305af
cutover identity SHA-256:
d2c19d79c5a04a97b523899adc60d397444ade06c942269d3fb21e8231b617fa
```

在线`/healthz`返回`application=stage35-simple`，`/api/v2/meta`确认频率范围
40.000000–359.921875 MHz、F-engine 原始标签`simple-4096`和本次900 s正式复相关数据段。
旧代码和旧数据 release 均保留以便回退，没有制作归档副本。步骤8至此闭合为
`COMPLETE / INTERACTIVE_SIMPLE_REPORT_BROWSER_VERIFIED`。

### 8.4 WebGL 上下文池修复

用户在桌面浏览器看到 Plotly 的“WebGL is not supported”遮罩。复核确认页面所有大数据曲线
原本已经使用`scattergl`，问题不是用户浏览器缺少 WebGL，而是同页同时创建16张图导致浏览器
WebGL上下文耗尽。修复坚持 GPU 路径，不增加 SVG/CPU fallback：包括 Allan 实线和白噪声
参考线在内的全部 trace 均冻结为`scattergl`；页面只给当前视口附近的图分配上下文，同时
最多保留3张，离开视口立即`Plotly.purge`释放，滚回时重新用GPU绘制。启动时先探测WebGL；
若确实不可用则明确报错，不静默换成CPU。页面脚本使用`?v=webgl-gpu-v1`避免旧缓存。

候选浏览器逐图滚动结构门禁覆盖单路16张、双路16张图，逐张确认trace类型全为`scattergl`、
并发活跃图最大值为3、外网请求0、严重控制台错误0。GB10无显示会话的headless Chromium不能
取得Plotly绘图用的硬件上下文，因此该环境只验证WebGL结构和上下文生命周期；桌面端实际GPU
渲染由页面WebGL强制门禁保证，不把headless软件环境冒充成硬件性能验证。最终证据：

```text
/var/lib/t510/stage35/explorer/validation/webgl-gpu-v1-final-20260904/browser_verification.json
SHA-256: 6d8ca429501cf8fc052429e875a25a21b8cab744d6ecc45eafb1a0183b1800c4
live app.js SHA-256: 7495d3e3dabf715c6f741d4b04d8ba2f024e8f265a09d5011c4d816c27d7cacd
previous code: /opt/t510-stage35-explorer/previous-stage35-webgl-gpu-v1-20260904
```

2026-09-04 15:37:51 CST 原子切换完成；线上`/healthz`返回
`{"ok":true,"application":"stage35-simple"}`，服务为`active/running`且无错误日志。数据release
没有变化，也没有重新采集或搬移。

### 8.5 WebGL 单上下文修复（v2）

用户复核后确认上述最多3张图的v1仍会出现Plotly的巨大“WebGL is not supported”遮罩。进一步
检查发现，`Plotly.purge`并不保证已创建的WebGL上下文立即归还给浏览器；连续滚动仍可能累积
上下文。此外，旧探针没有把Plotly `scattergl`实际依赖的WebGL 1与WebGL 2分开报告，因此
“浏览器支持WebGL”不足以证明Plotly已取得它需要的上下文。

v2继续坚持GPU绘图且不增加SVG/CPU回退，并作如下冻结：

- 全页任一时刻只保留1张活动Plotly图；离屏时先对图内canvas调用
  `WEBGL_lose_context`，再执行`Plotly.purge`；
- IntersectionObserver在一次回调后统一选择最靠近视口中心的图，避免相邻图按回调顺序争抢
  唯一上下文；占位按钮可显式选择当前图；
- WebGL 1和WebGL 2分别探测，页首直接显示可用性及`WEBGL_debug_renderer_info`返回的渲染器；
- Plotly若仍返回其WebGL遮罩，立即释放上下文并用同一`scattergl`路径重试一次；再次失败时只
  显示简短诊断，不留下巨大遮罩，也不退回CPU；
- 静态入口改为`app.js?v=webgl-gpu-v2`，避免浏览器继续使用v1缓存。

候选浏览器门禁逐张激活单ADC 16图和双ADC 16图，全部trace仍为`scattergl`，两组测试的
最大活动图数均为1；多选、Allan点击实算、100 ms/1 s产品、分页和URL复现继续通过，外网
请求0、严重控制台错误0。GB10的无显示headless会话仍只作为GPU结构和生命周期验证，不把
软件/无显示环境冒充成桌面硬件渲染证明；桌面页面本身会给出实际WebGL 1/2及渲染器诊断。

```text
deployment time: 2026-09-04 16:05:20 CST
live URL: http://192.168.100.162:8035/
live app.js SHA-256: 90892759b6ba067e3ae81ae03184b002cd91caf0a01cd4a118c5c9c3b5b4c59f
live index.html SHA-256: 3344869a62923a243bf4cff8a18f2ba73af2058b2e10159697f65413a8289186
browser evidence: /var/lib/t510/stage35/explorer/validation/webgl-gpu-v2-final-20260904/browser_verification.json
browser evidence SHA-256: da4a1db24f635462412dab9bf2d232b8c4cc4e9b8182040d39f336f0d0ad694e
previous code: /opt/t510-stage35-explorer/previous-stage35-webgl-gpu-v1-before-v2-20260904
```

切换使用候选整包SHA-256门禁和失败自动回滚；切换后`/healthz`通过，systemd为
`active/running`。数据release、采集结果和分析数值均未变化，没有重新采集、归档或搬移数据。

### 8.6 Apple ANGLE/Metal 共享画布修复（v3）

用户在Apple M2 Max浏览器复核v2时，页面探针同时确认WebGL 1和WebGL 2可用，实际渲染器为
`ANGLE Metal Renderer: Apple M2 Max`，但Plotly仍报告无法取得上下文。这证明浏览器和GPU
能力正常，失败来自应用自己的生命周期竞争：滚动观察器可以在异步`Plotly.react`尚未完成时
释放目标，且主动调用`WEBGL_lose_context`会让ANGLE/Metal异步处理上下文丢失；“同时只保留
1张图”仍不等于不会反复创建和销毁上下文。

v3取消正常滚动路径上的上下文销毁策略，改为一个长期存在的Plotly GPU画布：

- 单ADC和双ADC的全部图槽共用唯一DOM节点`stage35-shared-gpu-surface`；
- 滚动或点击另一图时只移动同一个画布，并用串行化`Plotly.react`替换数据与布局；
- 不再为每个图创建画布，也不在正常切图时调用`WEBGL_lose_context`或`Plotly.purge`；
- 不再另外创建WebGL探针canvas；第一张图成功后直接从Plotly实际canvas读取GPU渲染器；
- 仍只接受`scattergl`，没有SVG/CPU回退；只有Plotly已经失败的异常清理路径才允许purge。

候选门禁逐张切换单ADC 16图和双ADC 16图，所有32个槽在每次切换后均引用同一个
`stage35-shared-gpu-surface`，最大活动图数为1；原有数据、公式、分页、URL、只读和离线门禁
继续通过，外网请求0、严重控制台错误0。无显示headless环境只验证共享画布身份、串行生命周期
和GPU-only trace契约，不被写成Apple硬件渲染证明；Apple M2 Max的硬件身份来自用户浏览器
实际返回的ANGLE/Metal信息。

```text
deployment time: 2026-09-04 17:14:56 CST
live URL: http://192.168.100.162:8035/?v=webgl-gpu-v3
live app.js SHA-256: 373418c8d70763fd30bd614faefcd79476532f78203c50e5ae8ffc3375459c2a
live index.html SHA-256: 72ede8dcca4c3d4d58e83db7ce1853578650d1c4409cdaaa9bd270e63c2daef9
browser evidence: /var/lib/t510/stage35/explorer/validation/webgl-gpu-v3-final-20260904/browser_verification.json
browser evidence SHA-256: 327e47a40c103823fe07144afeea54dfd3b0e818c0902b1e89680249a59aaa94
previous code: /opt/t510-stage35-explorer/previous-stage35-webgl-gpu-v2-before-v3-20260904
```

切换后`/healthz`通过，systemd为`active/running`。本次只修改前端GPU画布管理，没有重新
分析、采集、归档或搬移任何科学数据。

### 8.7 Chrome 151 arm64 与 Plotly 稳定版固定（v4）

用户在Chrome 151.0.7922.138 arm64上继续复核v3：页面能看到WebGL 1/2 API，但Plotly在
第一张图创建实际上下文前失败；Console只有应用抛出的Plotly失败栈，没有
`Too many active WebGL contexts`、`CONTEXT_LOST_WEBGL`或ANGLE/Metal驱动错误。线上资源
随后确认使用`plotly.js v4.0.0`，而Plotly官方发布页仍把`v4.0.0-rc.0`列为预发布、
`v3.7.0`列为稳定最新版。故v4候选把运行时库固定回官方稳定版3.7.0，同时保留v3的唯一
共享GPU画布设计。

新Plotly包从官方`https://cdn.plot.ly/plotly-3.7.0.min.js`取得并固化到同源静态目录，浏览器
运行时不访问CDN；入口使用`plotly.min.js?v=3.7.0`和`app.js?v=webgl-gpu-v4`强制跨过旧缓存。
页首和失败诊断新增实际Plotly版本、Chrome user-agent以及浏览器提供时的
`webglcontextcreationerror.statusMessage`。

候选的全功能结构门禁通过：单路16图、双路16图均保持唯一
`stage35-shared-gpu-surface`，最大活动图数1，外网请求0、严重控制台错误0。GB10无显示
headless Chromium的严格硬件上下文测试仍失败，因此该证据不冒充Apple M2 Max客户端验证；
步骤8在用户用目标Chrome确认前重新标为`IN_PROGRESS / CLIENT_WEBGL_RECHECK_REQUIRED`。

```text
deployment time: 2026-09-04 17:23:39 CST
live URL: http://192.168.100.162:8035/?v=webgl-gpu-v4
Plotly: 3.7.0
Plotly SHA-256: 8ef4c6ab1369f0019611cbcd2d5b8aafef23e5d19ef58c39d4b4249831fe2180
live app.js SHA-256: 59a0a0b53978c7f57b665a761bc6161b0b6b43844664232830de2188370dfc61
live index.html SHA-256: 995d406d226517af93f84e91a846cc6b35daedafb78c9db9696b4d5cf77e1e3b
browser structural evidence: /var/lib/t510/stage35/explorer/validation/webgl-gpu-v4-final-20260904/browser_verification.json
browser structural evidence SHA-256: 63a3d632088470335043b50cc41ac2810fb60c6130a8035a25822c984ebdb7fa
previous code: /opt/t510-stage35-explorer/previous-stage35-webgl-gpu-v3-before-v4-20260904
```

### 8.8 单一正式入口与固定 Plotly 图

Chrome 151 arm64的完整Console随后给出底层证据：多次应用失败之后，Plotly明确输出
`Too many active WebGL contexts. Oldest context will be lost.`。这揭示v4仍有一个循环：
IntersectionObserver在失败后再次尝试，且每次`Plotly.react`使用不同数量和身份的trace，
Plotly会重建部分GL层；失败尝试留下的上下文不能同步回收，最终把Chrome推到上下文上限。

当前正式实现不再自动重试，并把一个Plotly图固定为12个`scattergl`槽位，每个槽位使用稳定
UID。全页生命周期只允许第一次调用一次`Plotly.newPlot`；后续切换只在相同12个槽位和相同
DOM画布上调用`Plotly.react`更新数据。任一次真实WebGL失败都会设置全局fatal门禁并停止继续
创建上下文，不再形成失败循环。`persistGlLayer`同时保持GL层常驻。

按用户要求，公开交付不再使用v4/v5式地址或资源参数：唯一入口固定为
`http://192.168.100.162:8035/`，资源固定为`/static/app.js`和`/static/plotly.min.js`。
HTML与JavaScript响应改为`Cache-Control: no-store`，后续始终在同一地址更新。Plotly仍固定为
本地同源3.7.0，数据曲线仍全部为`scattergl`，没有SVG/CPU回退。

候选完整门禁的内部计数为：`newPlotCalls=1`、`reactCalls=59`、`fixedTraceSlots=12`、
`fatal=false`；单路16图和双路16图始终引用同一`stage35-shared-gpu-surface`，最大活动图数1，
外网请求0、严重控制台错误0。目标Apple M2 Max确认前，步骤8仍保持
`IN_PROGRESS / CLIENT_WEBGL_RECHECK_REQUIRED`。

```text
deployment time: 2026-09-04 17:32:47 CST
only live URL: http://192.168.100.162:8035/
app.js SHA-256: c0c28a4eb0e1464ae314e0bcb061bc88af9572f0676746b369b64a1c6a01374b
index.html SHA-256: 638776a572c4f66403ae823b913038b2c6f0b94c7c51902dba65e4b4e14d7380
Plotly 3.7.0 SHA-256: 8ef4c6ab1369f0019611cbcd2d5b8aafef23e5d19ef58c39d4b4249831fe2180
server SHA-256: 6a9a3eedf1c0861bb0507b316d290c5c966157b9b4f1f99931c72d8fc66195fd
browser evidence: /var/lib/t510/stage35/explorer/validation/webgl-single-final-20260904/browser_verification.json
browser evidence SHA-256: 15f92b584ad9ab2e8ad9dfe059aa57d6a43d1302ac19a4bb79998857e8198d53
```

### 8.9 固定资源名消除客户端旧缓存错配

用户在162本机和Apple M2 Max Chrome 151上看到的新诊断同时包含
`fixedTraceSlots=12`和`plotlyVersion=4.0.0`。前者只存在于当前应用代码，后者却不是服务端
当时提供的3.7.0，因此这不是两台机器同时失去WebGL能力，而是浏览器把新`app.js`与旧公共
路径缓存中的Plotly 4.0.0组合加载。仅给响应增加`no-store`不能追回此前已缓存的同名资源。

正式入口仍只保留`http://192.168.100.162:8035/`，但HTML一次性改用此前从未出现过、此后
保持不变的`/static/stage35-app.js`和`/static/stage35-plotly.min.js`；没有v4/v5地址，也没有
版本查询参数。HTML和两个JavaScript响应均为`Cache-Control: no-store`。应用启动时同时强制
验证Plotly必须恰为3.7.0；若资源身份错配，会明确报告“静态资源版本错配”，不再误报为
WebGL失败。

候选真实Chromium 151门禁通过：`plotlyVersion=3.7.0`、`newPlotCalls=1`、
`reactCalls=56`、`fixedTraceSlots=12`、`fatal=false`；外网请求0、严重控制台错误0。候选通过
后于2026-09-04 17:41 CST原子切换到8035，服务`active`，根页面及两份固定JavaScript均返回
`no-store`。目标Apple M2 Max实际确认前，步骤8继续保持
`IN_PROGRESS / CLIENT_WEBGL_RECHECK_REQUIRED`。

```text
only live URL: http://192.168.100.162:8035/
index.html SHA-256: 2242bf941847dacb7df79bc13ebd9006e8109d01102cf9de02aa66292ad2bbe0
stage35-app.js SHA-256: 9befe9e3a456b522e97732b3f904d1b64e987cd92b6c43b906c6dadc484f9f84
stage35-plotly.min.js SHA-256: 8ef4c6ab1369f0019611cbcd2d5b8aafef23e5d19ef58c39d4b4249831fe2180
browser evidence: /var/lib/t510/stage35/explorer/validation/webgl-canonical-final-20260904/browser_verification.json
browser evidence SHA-256: c96f2941c49f1f774ba5d331288e7f7d44d16cfa1e8816117900148a80e2eab0
rollback code: /opt/t510-stage35-explorer/previous-stage35-before-canonical-assets-20260904
```

### 8.10 严格 CSP 与 Plotly strict GPU 包

固定资源名生效后，目标Mac明确加载到Plotly 3.7.0，但第一次`newPlot`仍显示Plotly自己的
WebGL失败遮罩。该现象随后在162的真实X11桌面Chrome 151中原样复现，排除了Mac、Metal和
客户端缓存这三项差异。复核发现页面CSP保持`script-src 'self'`且不允许`unsafe-eval`，而此前
使用的是Plotly标准包；Plotly官方提供的strict发行包专门避免函数构造器，并且包含本报告所用
的`scattergl`。

同一候选只把标准包替换为官方`plotly-strict-3.7.0.min.js`后，162真实桌面硬件门禁完整通过：
Chrome 151实际渲染器为`ANGLE (NVIDIA Corporation, NVIDIA GB10/PCIe, OpenGL 4.5.0)`，单路
16图与双路16图的Plotly WebGL遮罩均为0，`newPlotCalls=1`、`reactCalls=60`、
`fixedTraceSlots=12`、`fatal=false`，外网请求0、严重控制台错误0。该门禁没有headless参数、
没有SwiftShader，也没有结构性豁免。另一个无显示测试也在取消“忽略WebGL遮罩”后通过，避免
此前空canvas探针造成的假阳性。

正式HTML现在只引用固定资源`/static/stage35-plotly-strict.min.js`，并用SRI冻结其SHA-256；
URL没有v4/v5或版本查询串。2026-09-04 17:57 CST候选已原子切换到8035，服务与整包身份检查
通过。目标Apple M2 Max复核前，步骤8仍保持
`IN_PROGRESS / CLIENT_WEBGL_RECHECK_REQUIRED`。

```text
only live URL: http://192.168.100.162:8035/
index.html SHA-256: a4058a397697e2f155a66ea2d66cc46af89701ab832fd005dabe68ea9a346616
stage35-app.js SHA-256: bf43169ac9a80d66e41e6a9514dd651f7e784fac6fd4e89fc6edbed38606b3aa
plotly strict 3.7.0 SHA-256: ca8715e7e348e1d56fb5d31575c7850b5cdd277f601bf047c0fefc4172e2957b
SRI: sha256-yocV5+NI4dVvtdMVdceFC1zdJ39gG/BHwP78QXLilXs=
hardware browser evidence: /var/lib/t510/stage35/explorer/validation/webgl-strict-headful-final-20260904/browser_verification.json
hardware evidence SHA-256: 1a64abc33b26444c4800bfbfc46cadc73c2c6d6bcf9af5f19638465d2888cfd9
rollback code: /opt/t510-stage35-explorer/previous-stage35-before-strict-csp-20260904
```

### 8.11 说明栏、公式与图例排版修复

用户截图暴露两个独立排版缺陷。第一，窄屏单列规则使用`1fr`时仍保留内容的最小固有宽度，
KaTeX长公式和连续SHA-256会把整个网格列撑出卡片，导致说明正文、公式背景和右边框横向越界。
第二，每个图已经有正文`h4`标题，Plotly内部又重复绘制标题，并与顶部横向图例占用同一区域，
因此出现“ADC0 · TIME_ONLY原样点”和I/Q图例互相覆盖。

当前样式把卡片、图、说明栏及单列网格全部冻结为可收缩的`minmax(0, …)`，连续数据身份使用
任意位置换行，公式框只允许自身横向滚动而不能撑宽页面。公式按`,\\quad`与`\\qquad`语义
分隔符拆为逐步KaTeX行，Allan的归一化、窗口平均、K、方差和白噪声参考分别显示。Plotly内部
重复标题被移除，只保留图外的人类可读标题；图例获得独立顶部空间，坐标标题启用自动边距。
CSS改用此前未出现的固定资源名`stage35-app.css`并以SRI冻结身份，响应为`no-store`；这会绕过
旧`app.css`曾经留下的一小时缓存，普通刷新即可取得修复。

162真实桌面Chrome 151在1705 px和1035 px两个视口完成全功能硬件门禁。单ADC与ADC对页面均
满足：页面横向溢出false、越出卡片的说明/公式元素0、空公式框0、重复Plotly标题0；GPU仍为
`ANGLE (NVIDIA GB10/PCIe, OpenGL 4.5.0)`，外网请求0、严重控制台错误0。2026-09-04
18:52 CST最终候选已原子切换到8035。

```text
only live URL: http://192.168.100.162:8035/
index.html SHA-256: 9dd40a20011c7707f0dc09dd13f2c7abe583e6a4034200f841a2bc9e188f3267
stage35-app.css SHA-256: 1454033036a8a53c70c1ea2daf82b3551c0077cf4c2a30bd04a2cd2f57f9ab03
stage35-app.js SHA-256: 2a96fd74f952b32e63af5525c540a7460674ac6c26a69b7a5767807dc63800ed
server SHA-256: 743a13e5fa20f5bcf3f1da49092f6be9c4a4acb42b8de33c8b4ee9c9c779d75b
wide hardware evidence: /var/lib/t510/stage35/explorer/validation/layout-canonical-css-headful-20260904/browser_verification.json
wide evidence SHA-256: f71b8242586df4644f8f257e576c2276ff23ee76689b7fe19caae2def55807eb
narrow hardware evidence: /var/lib/t510/stage35/explorer/validation/layout-headful-narrow-20260904/browser_verification.json
narrow evidence SHA-256: d85267bdf7e7a984e570f7b91d043ed7090f1009545c294ecf3b346da1ffa731
rollback code: /opt/t510-stage35-explorer/previous-stage35-before-canonical-css-20260904
```

### 8.12 数据层级说明、Pan与阶梯散点

图旁“原始数据是什么”此前错误地展示数据段、数组名和SHA，无法回答读者真正关心的“这个
数字在仪器链中的哪一步”。当前说明改为逐类解释物理数据层级：TIME_ONLY是模拟输入经ADC
采样、RFDC数字下变频和12倍抽取后，以320 MS/s输出的复数I/Q，I/Q各为有符号16位整数；它
不是3.84 GS/s ADC原始转换码。F-engine、TIME软件FFT、两路复乘、自功率与Allan说明也分别
写明上游数据和变换；存储数组与SHA只保留在底部折叠技术区。

服务端取消了原样TIME_ONLY统一转float的行为，并为未平均F-engine I/Q保留int16整数语义。
在线独立复核确认两类JSON均为整数，分桶平均仍为浮点；例如A-post窗口的一个实值为I=9、
Q=-3。前端提示框改为分别列出时间、样点编号和有符号整数，不再显示含糊的`(x,y)`。

所有图的默认拖拽工具明确冻结为Pan，Plotly工具删除列表为空，因此缩放、选择、套索等其他
工具仍保留。所有测量点统一为小型`x`；每张时间序列图提供独立“用阶梯线连接”开关，开启
后保持叉形标记并使用`hv`线，Allan及白噪声参考不作阶梯连接。共享GPU画布切换前后保存各图
自己的开关状态，不创建第二个WebGL上下文。

162真实X11桌面Chrome 151硬件验收通过：实际渲染器为
`ANGLE (NVIDIA Corporation, NVIDIA GB10/PCIe, OpenGL 4.5.0)`，`newPlotCalls=1`、
`reactCalls=64`、`restyleCalls=1`、外网请求0、严重控制台错误0、横向溢出0。候选通过后于
2026-09-04 19:50 CST原子切换到8035；未搬移或重算采集数据。

```text
only live URL: http://192.168.100.162:8035/
server SHA-256: f8d0fddcbb45127fe64d8ce1e4b4b3b5c0d185bd5367f34dbd88ec1c05890278
index.html SHA-256: 14796809c102d5e40f12a33d26176f5f9eb571b4f20d8b70f5fd14bf53bcd1dd
stage35-app.js SHA-256: e8d75fe115836e9e6b4fe8388552d9860fb803f1123d154a5f46c97dacba277c
stage35-app.css SHA-256: a08fa16a49555b5d6674a4d4a82283705a5ea6eb7d5b23a0ece0e753d8be6632
browser evidence: /var/lib/t510/stage35/explorer/validation/semantic-pan-step-20260904/browser_verification.json
browser evidence SHA-256: 6373317b0cb2dcd71c3604e6e40230d96c2437c797d0018a0012b26e5b3cfb12
```

### 8.13 共享GPU画布的横轴裁剪修复

用户复核发现复可见度Allan图没有显示时间轴。真实浏览器边界测量确认数据和坐标标题都存在，
但共享Plotly画布从之前的幅度/相位双层图继承了620 px高度，Allan外层容器仍只有390 px；
横轴刻度位于外层底边以下约185 px，因`overflow: hidden`被裁掉。

当前每张图接管唯一GPU画布时都同步设置自己的Plotly高度和外层容器高度。普通图固定520 px，
双层幅度/相位图继续使用620 px。浏览器门禁新增逐图约束：Plotly布局高度必须等于外层高度，
所有横轴刻度和标题必须落在容器边界内。162真实Chrome 151硬件全验收通过，仍只有一个WebGL
画布，外网请求0、严重控制台错误0。

正式8035切换后再次直接测量复可见度Allan图：容器、共享画布和SVG均为520 px；横轴刻度底边
937.73 px、标题底边970.73 px，均小于容器底边982.73 px，时间轴完整可见。

```text
deployment time: 2026-09-04 20:05 CST
only live URL: http://192.168.100.162:8035/
stage35-app.js SHA-256: e94a1026750b63406654f92d0881f8e0cd464b29a6758fdcd0769e62de54832d
browser evidence: /var/lib/t510/stage35/explorer/validation/axis-height-fix-20260904/browser_verification.json
browser evidence SHA-256: f0021e44338ad781025d3f25fa8453590e0660346eee585242f7b59fb0c67b64
```

### 8.14 多ADC与多ADC对的同图比较

用户进一步明确，“一个或多个ADC/ADC对”表示把所选对象的相同物理量画在同一幅图中，而不是
为每个对象重复生成一套图。前端渲染现按当前页聚合：单ADC入口的TIME_ONLY原始I/Q、分桶I/Q、
F-engine原始I/Q、逐帧/分桶/900秒功率、TIME_ONLY FFT参照和Allan方差，均在各自唯一图中
叠加本页所选ADC；两路入口的TIME_ONLY复乘、F-engine复可见度、100 ms、1 s、FFT参照和
复可见度Allan也同样叠加本页所选ADC对。每条图例同时写明ADC或ADC对与频率。

分页边界继续保留为每页最多4个对象；其作用只是控制同图密度和GPU负载，不再产生4套图。
组合配色按“对象×频率”稳定分配。相位子图只在幅度曲线的图例中列出组合身份，避免相同组合
的幅度、可靠相位和弱相位重复占满图例；白噪声虚线也只保留一个通用图例说明。单图最坏情况
为4个ADC对×4个频率×3类相位/幅度trace，因此固定GPU槽位由12调整为64，但全页仍只创建
一次Plotly图并复用同一个WebGL画布。

162真实X11桌面Chrome 151候选门禁通过：单ADC三个章节各只有1个分组卡片、共8幅图，每幅
相应图同时含ADC0和ADC1；ADC对三个章节也各只有1个分组卡片、共8幅图，相应图同时含
ADC0–ADC1和ADC2–ADC3。五ADC分页实测为第一页1张卡片叠加4个对象、第二页1张卡片显示
余下1个对象。实际渲染器为`ANGLE (NVIDIA Corporation, NVIDIA GB10/PCIe, OpenGL 4.5.0)`，
`newPlotCalls=1`、`fixedTraceSlots=64`、`fatal=false`，外网请求0、严重控制台错误0。候选于
2026-09-04 20:27 CST原子切换到8035；未重算或搬移科学数据。

```text
only live URL: http://192.168.100.162:8035/
stage35-app.js SHA-256: 3a6bdc69ee29259717b7b9b2f7d203617efbb9a435993e8ccb16107b7145f0d4
browser evidence: /var/lib/t510/stage35/explorer/validation/same-plot-overlay-20260904/browser_verification.json
browser evidence SHA-256: d02ec14b7778966b444f7e77ff6975a1a6bb519494750fe8b517949894a6927c
rollback code: /opt/t510-stage35-explorer/.current-before-same-plot
```

### 8.15 I/Q与幅相标记区分

按用户复核意见，所有I/Q时间序列现用形状而不只靠颜色区分：I为小叉，Q为空心小三角；所有
复可见度双层图同样以小叉表示幅度、空心小三角表示相位，低于门限的相位继续显示为灰色空心
小三角。Allan实测点仍保持小叉。162真实Chrome/GB10验收同时检查形状配对、Pan、阶梯切换、
单WebGL画布、零外网请求和零严重控制台错误；2026-09-04正式切换后服务健康。

```text
only live URL: http://192.168.100.162:8035/
stage35-app.js SHA-256: e117baace42f1cacc04ab777dd85618ea380cba8ecb3c4a6640f0983e38ad8ff
browser evidence: /var/lib/t510/stage35/explorer/validation/marker-pairs-20260904/browser_verification.json
browser evidence SHA-256: 17a89d0ce0d6409ece7f43122dfbc53b35bacd859606e5a5d6f3de8672e209c0
rollback code: /opt/t510-stage35-explorer/.current-before-marker-shapes
```

阶梯连接线随后按用户要求改为同系列颜色的24%不透明度和0.8 px线宽，叉形与空心三角标记本身
保持原有清晰度。实机门禁确认切换、切图和恢复状态均正确。正式`stage35-app.js` SHA-256为
`620ab28a70a1cb7772ef3297ae6b8ff9ce7561223965092f7c8722b00ba34615`；浏览器证据位于
`/var/lib/t510/stage35/explorer/validation/step-line-fade-20260904/browser_verification.json`，其
SHA-256为`1d11c91f23938ab8aadb37e4e054a1e4af4930f213e6f1ed28a86125d39b1831`。

### 8.16 左侧分组控制与TIME_ONLY 900秒在线汇总

用户复核指出顶部配置与多个含义不明的“间隔”控件混在一起，无法判断一个开关正在控制哪张
图；现有TIME_ONLY也只有六段50 ms原始I/Q，确实没有连续900 s曲线。新页面把全部选择移到
固定左栏，并冻结成三个互不串线的刷新域：TIME_ONLY、F-engine和Allan。每组明确列出所影响
的章节，控件变化自动刷新该章，同时保留独立“重新加载本章”按钮；防抖和代次门禁保证慢的
旧请求不能覆盖新选择。ADC/ADC对与分页才刷新当前入口的全部章节。桌面左栏可折叠，窄屏为
左侧抽屉，标题区不再放配置控件。

单路TIME_ONLY将新增连续900 s的I/Q中心和平均数字功率。完整八路320 MS/s原始流若全部保存
约需9.2 TB，本次不保存该巨量流；GB10接收机仍逐样点处理全部数据，每10 ms直接累加并保存
平均I、平均Q、`mean(I²+Q²)`、有效样本数、sample0、极值、削顶和质量账本。100 ms与1 s
显示值只能由这些10 ms基础点按有效样本数加权合并，不能直接平均标准差，也不在正文使用
RMS。TIME_ONLY是未通道化的post-DDC 320 MS/s复数I/Q，所以这两张900 s图没有频率bin。

双路入口现只保留生产F-engine复可见度与复可见度Allan；TIME_ONLY逐样点复乘和TIME普通
FFT相关参照已退出页面。F-engine短时帧平均、自功率900 s间隔、复可见度900 s间隔、单路
Allan数据段和双路Allan基础间隔均使用完整名称并保持独立状态。

接收机单元测试与合成TIME包重放共4项已在GB10通过，Python数值测试共8项通过。完整长队列
已于2026-09-04 21:41 CST一次性提交：

```text
unit: t510-stage35-time900-ui-v1-20260904-2141.service
queue: /var/lib/t510/stage35/stage35-time900-ui-v1-20260904-2141-queue
pipeline: receiver unit/synthetic packet replay
          -> 60 s full-rate TIME smoke
          -> 900 s formal TIME online summary
          -> independent numeric/SHA verification -> read-only arrays
          -> sidebar candidate browser verification -> atomic 8035 cutover
          -> in-place identity (no archive copy)
```

10 s健康检查时unit为`active`，queue为`running`、error为`null`，60 s阶段为`starting`，900 s
正式阶段已登记为`pending`并会由同一进程自动接续；旧8035仍返回健康。依仓库长任务规则，
确认完整队列健康启动后停止轮询并交还控制权。当前只记录“已启动”，不提前写采集、浏览器
验收或切换完成；步骤8继续保持`IN_PROGRESS / CLIENT_UI_REVIEW_REQUIRED`。

队列随后完成60 s烟雾和900 s正式采集：正式窗口处理`1,125,000,000`包、每路
`288,000,000,000`个post-DDC I/Q样点；板端、receiver、NIC的drop/gap/reorder/duplicate
增量全部为0，schema-v2 manifest与独立复算通过。首次浏览器门禁没有切换8035，原因是验证
脚本以子字符串搜索旧URL参数`time=`，误命中新参数名`time_capture=`。该问题不涉及页面、
GPU或科学数据；验证器改为解析实际查询参数键，并等待移动抽屉180 ms动画结束后再测量。

真实硬件Chrome复验`browser_verification_resume2.json`为`PASS`，随后只读复用已验签数据完成
原子切换，没有重新采集。当前数据release为
`/var/lib/t510/stage35/explorer/releases/stage35-time900-ui-v1-20260904-2141`；应用meta公开
10/100/1000 ms三档TIME_ONLY，1 s接口返回900点。原队列已恢复为`completed`、error=`null`，
固定入口仍为`http://192.168.100.162:8035/`。步骤8在用户复核前继续保持
`IN_PROGRESS / CLIENT_UI_REVIEW_REQUIRED`。
