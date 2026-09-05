# Stage 36：Stage 35 经验前置审计

状态：`IMPLEMENTED / R7_SUBMITTED_IN_PROGRESS`

本审计在 qualification-r4 失败后执行。目标是把 Stage 35 已经证明过的运行规则一次性落实到
Stage 36 的 MTS、五模式、短采、安装和后续科学队列中，不再用上板失败逐项发现旧问题。

## MTS 冻结策略

r2、r3、r4 三份完整 discovery 40/40 的 SHA-256 分别为：

- `38509e3ab1bd55208cf17d5128f69c38f0eb5b9a82f637d8b64c66ea7dbe3688`
- `1c956d09aae7ba0dafa0ac5999dc55b7310877531cd5e980265d447b370a2e0d`
- `3fe9ed1469271cc67a2f58a9ff299312948dbae59c1fd3ff3532ae9e7f8c6456`

三次合并后 ADC 已见包络为 360–456，DAC 原始状态包含 32–96、384 和 768。DAC 的 SYSREF
周期为 720 T1。AMD 2022.2 驱动只在移动一个周期能**严格**缩短到固定目标的距离时换分支，
相等时保留原分支。因此目标 400 会把 32 移到 752，不能覆盖历史状态；它已在回归中明确
否决，未提交上板。

ADC 冻结目标为 492。DAC 392 曾是只覆盖 32、384、768 时的最高候选，但 r6 在完成新一轮
discovery 40/40 后、首个 fixed reset 测得新状态416。按驱动规则穷举后，32、384、416 不存在
任何共同的非负固定目标：提高392会让32换到752分支并高于目标，保持392又低于416。因此
DAC 改用 AMD 单器件相对对齐 `-1`；它仍要求 MTS API 成功、offset 合法且 tile 间报告残差
小于一个 factor。该选择沿用 Stage 35 板载 TCXO 的 free-run/sample0 相对时间合同，且正式
科学采集中 DAC 保持静音。

MTS 两阶段都固定使用 3 s LMK 稳定时间。catalog finalizer、发布器和板端安装器共同验证
40/40 动作矩阵、3 s 等待、ADC 492、DAC relative `-1` 以及固定目标不可行见证
`[32,384,416]`。第二阶段会从 discovery 原始观测重新推导合同，拒绝被修改或过期的推荐值。

## Stage 35 运行规则落实表

| Stage 35 已知问题 | Stage 36 前置处理 | 门禁位置 |
|---|---|---|
| 下载 PL 后重写 LMK 会触发 DAC state 6 | 保留实时合格时钟；LMK 切换固定为 STOP/静音、旧时钟下 shutdown、写入并锁定、SYSREF on、重载 PL、Reset/MTS | `pynq_t510_mts_campaign.py` |
| 一次 discovery 不能代表后续 latency 状态 | ADC 合并历史包络并固定492；DAC依据完整32/384/416见证改为相对对齐 | `t510_mts_target.py` |
| 把 MTS 报告 latency 完全相等误当成成功条件 | 按 AMD factor-12 舍入验证：API 成功、tile 间残差跨度小于 12 T1；fixed 还要求每 tile 在目标 ±6 T1 | campaign、repeatability、finalizer |
| DAC 32/384/416 状态不存在共同固定 target | 沿用 Stage 35 TCXO free-run/sample0 语义：ADC 固定 492，静音 DAC 使用单器件相对 MTS `-1`；保留 API、offset 和 tile 残差门禁 | policy、campaign、catalog、Agent、运行门禁 |
| LMK 写入后 1 s 偶发不足 | discovery/fixed 均强制 3 s，证据和 catalog 必须记录 | campaign、finalizer、installer |
| 每次 START 有 18–19 beat 板端初始化瞬态 | START 后等待 3 s，再冻结正式前快照；启动期板端差值单独记录 | 五模式和短采 gate |
| 启动期接收机丢包不能被忽略 | START 前后读取 receiver 计数；任何 receiver drop/gap 立即失败 | 五模式和短采 gate |
| STOP 已成功但 HTTP 大响应被 reset | STOP 最多发送一次；传输异常后只读三次，只有停流、DAC 静音、v36、profile、RFDC 和尺度身份全通过才接受 | 五模式和短采 gate |
| 遥测轮询反复返回 4096 s 历史 | 正式 60 s 窗口从 watchdog sequence 游标增量读取；检查 epoch、首序号、逐条连续性和数量 | 五模式 gate |
| SPEC 类型曾误写为 2 | 明确要求 `stream_type=0` | 短采 parser |
| SPEC 同端口 seq/frame 步进误当 1 | 按 Stage 35 协议使用每端口 +16，并以 `floor(frame_id/16)` 拼 16 个频率块 | 短采 parser |
| PFB 正常状态被误当成 status=0 | 要求 PFB active bit10，拒绝旧 FFT-only bit8、320M halfband bit9、overflow/data-halt bits | 短采 parser |
| 50 ms 原始 TIME 边界不齐 | 继续使用 receiver 的未来共同 sequence gate，再裁连续 50 ms | Stage 35 helper 复用 |
| 只看 8010 端口会误认旧 Agent | 安装继续校验 systemd MainPID 的 `/proc/PID/exe` 指向当前二进制 | board installer |
| catalog 最终化后包身份发生变化 | 立即更新 catalog SHA，重新逐文件验证远端 staging 和安装后的 `/opt/current` | qualification queue |
| 安装一成功就更新本地 latest 会形成假发布 | 本地 overlay/config 晋升移到 40/40、五模式和短采全部 PASS 之后 | qualification queue |
| 失败后 Agent 与低层控制器可能竞争 | 失败先停 Agent/watchdog，再执行 STOP、DAC=0、SYSREF off；分别保留两步错误 | qualification queue |
| scan_id、磁盘或其他任务冲突 | 后续科学队列沿用 Stage 35 的唯一 scan_id、最坏磁盘预算、receiver/board idle 预检 | 科学队列合同 |
| 页面参数串线、NaN、favicon、WebGL、缓存/CSP | 8036 复用 8035 最终实现及浏览器门禁：`simple-4096`、null+可靠性、内嵌 favicon、单共享 WebGL、固定版本资源名、Plotly strict、无外网 | 报告合同 |

## 回归证据

- 本机相关 Python 回归 122 项通过；包括时钟顺序、冻结目标负例、catalog、安装、发布顺序、
  STOP 响应丢失、遥测序号、QMC/尺度、控制器和时序门禁。
- Rust 板端 Agent 回归 8 项通过，静态 AArch64 发布二进制及 catalog 冻结合同验证通过。
- GB10 NumPy 环境的 Stage 36 短采回归 9 项通过。
- 新 SPEC parser 直接重读 Stage 35 已验收的 4096 个完整频谱 PCAP，得到连续 group
  859584–863679、削顶 0、八路全频 I/Q 标准差中位数 2.122–2.324 count，与 Stage 35
  页面范围一致。这同时验证了 `stream_type=0`、每端口 +16、16 block frame-group 和正常
  `spec_status_flags` 的真实协议解释。
- shell 语法、Python 编译和 `git diff --check` 通过。
- r5 的真实 `[768,768,768,764]` discovery 向量通过 factor 量化判据；12 T1 跨度负例仍会
  失败。ADC 492 / DAC relative `-1` 的宽范围 T510 回归运行 254 项，其中 243 项通过、11 项
  按环境条件跳过。

R5 暴露了合法 factor 量化残差误判；R6 discovery 40/40 通过后证明 DAC 固定 392 无法覆盖
新见证416。两者均未进入安装并已安全停止。ADC-fixed/DAC-relative 合同下的 R7 从 discovery
0/40 开始，完整队列已自动武装 discovery、混合目标 40、catalog/安装、五模式 60 s、
TIME/SPEC 短采和最终本地晋升。首次健康检查状态为 `running / MTS_discovery_40`。只有 R7
完整资格通过后才能提交 Stage 36 正式科学长队列。
