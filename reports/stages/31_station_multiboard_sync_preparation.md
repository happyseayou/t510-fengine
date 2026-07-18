# Stage 31：Station 多板同步准备

## 结论与边界

Stage 31 已把“共同参考存在”推进为可执行的数据事务：各板先冻结同一 generation/config 标识，分别按本地 PPS 计数 ARM，在同一个未来公共 PPS 边界建立共同的 TAI observation epoch，把第一拍 ADC 数据映射为 observation `sample0=0`，清空抽取/PFB/XFFT/packet 状态，并只在声明的 `first_sample0` 放行 TIME/SPEC 数据。

这使得没有 Center Hub 时也能用主机脚本完成小规模两阶段启动，并把下一步接入下发器、功分器、公共 SYSREF/MTS 和 X-engine 所需的接口准备好。它不能替代物理时钟树，也不能在没有共同输入的情况下证明跨板模拟相位已经一致。

## 为什么必须改 RTL

旧实现的 `sync_fsm` 只提供本板立即 ARM/epoch，缺少以下跨板契约：

- 没有不可变的 generation、TAI epoch、配置 ID 和 MTS 结果 ID；控制请求到达时间会变成数据起点。
- 本地 `pps_count` 从各板上电开始，数值不具有跨板绝对意义；跨板共同身份必须是 `epoch_tai + generation + sample0`。
- AA、PFB frame、XFFT 内部状态和 packet sequence 未在同一 epoch 清空；相同包头 sample0 不足以证明同一数字孔径。
- 100 MHz 的 41-tap half-band AA 有 20 raw-sample 群时延，输出拍标签满足 `sample0 mod 8 = 4`。固定使用 32768 会使状态机永远等不到目标首拍。
- 若先在时钟沿看到目标 sample0、下一拍才使能数据，会丢掉目标拍。因此需要组合前视释放，随后由寄存的 streaming 状态保持。
- 只在 ARM 瞬间看 lock 不够。ARM 后或运行期 ref/PPS/RFDC 失效必须立即撤销 data-valid 并进入错误态。

保留了旧 `sync_fsm` 兼容路径；只有 Stage 31 PREPARE 被选择后，新调度器才接管。

## 实现内容

### 数据域调度器

新增 `rtl/station_sync_scheduler.sv`，状态为：

| 值 | 状态 | 含义 |
|---:|---|---|
| 0 | IDLE | 未选择 Stage 31 |
| 1 | PREPARED | bundle 已冻结，尚未 ARM |
| 2 | ARMED | 等待本板目标 PPS |
| 3 | WAIT_EPOCH_SAMPLE | PPS 已提交，等待第一拍有效 ADC |
| 4 | PRIMING | observation epoch 已建立，等待可达的 `first_sample0` |
| 5 | STREAMING | TIME/SPEC 已放行 |
| 6 | ERROR | 事务失败，需 ABORT 后重建 generation |

关键语义：

- `generation` 必须非零并单调递增。
- `signal_chain_tag` 和 `mts_result_id` 必须非零。
- ARM 至少领先 2 个 PPS；协调脚本默认 5 个。
- 目标 PPS 上产生 pipeline epoch reset；reset 释放后、真正进入 science pipeline 的第一拍原始 ADC sample0 记入 `actual_epoch_raw_sample0`，对外映射为 observation sample0 0。reset 周期被丢弃的 beat 不参与 epoch，否则 4-sample/beat 会让抽取余数整体偏移。
- `first_sample0` 的可达规则由当前带宽和 AA 实现决定：20 MHz 为 `mod 32 = 0`；200 MHz 为 `mod 4 = 0`；100 MHz AA 为 `mod 8 = 4`（无 AA 的兼容构建为 `mod 8 = 0`）。
- TIME 首拍在前视释放时即可被记录；SPEC 首拍在首个 PFB 输出实际被 packetizer 接受时记录。
- ARM 后任一 `ref_locked=0`、`rfdc_ready=0` 或 `pps_recent=0` 都停止 streaming 并形成显式错误。

### Pipeline reset

- science rate selector 的 decimation phase、pending 拍和 AA FIR history 在 epoch 清空。
- PFB frame/capture/packet 状态在 epoch 清空。
- XFFT IP 打开 `aresetn`，epoch 后保持复位 15 个数据时钟，再重新完成配置握手。Stage 27h/27j 和仿真模型均连接该复位。
- packet stream sequence/FIFO 在同一 epoch reset。

2026-07-18 与 Hub 联测暴露了一个跨时钟域清理缺口：ARM 后同步 FSM 可以进入
`STREAMING`，但若 STOP/ABORT 落在 TIME/SPEC 半包期间，数据时钟域生产者会被清空，
CMAC 时钟域的 source mux/output slice 却仍锁定原 source 等待 `TLAST`。该反压会沿
TIME/SPEC、PFB/AA 一直传回 RFDC，形成 TIME 只出少量包、SPEC 不出包且 RFDC drop
持续增长；再次 `ABORT -> STOP -> IMMEDIATE START` 不能释放 CMAC 半包状态，只有
重载 bitstream 同时复位两个时钟域才恢复。

修复后的 reset/enable 所有权为：

- `epoch_reset`、STOP、soft reset、Stage 31 ABORT、TX clear 和 mode change 统一产生
  `packet_stream_reset_pulse`，并用 toggle CDC 把同一个逻辑 flush 送入 CMAC 时钟域。
- 数据域清 science selector、AA/PFB、TIME/SPEC packet/FIFO 和监控状态；CMAC 域同时
  清 TIME DDR ring、TIME/SPEC 宽口 CDC 输出、heartbeat、source mux 和最终 output slice，
  因而旧半包不能跨 observation/run 存活。
- 调度器不再仅凭 `science_valid` 声明运行，而只在目标首拍完成
  `science_valid && science_ready` 握手后进入 `STREAMING`。
- 板端 STOP/ABORT/reset 额外脉冲 PFB clear 与 TX clear，并保留 PFB enable 和
  TX policy 位。这既是新 RTL 的防御性清理，也是旧 Stage 31 bitstream 的软件恢复路径。
- Hub 协调脚本在 ARM ACK 后默认要求两次健康状态：所需 TIME/SPEC counter 前进、
  RFDC drop 不增长、RFDC downstream ready、无 stale science mux lock；不再把
  “FSM 显示 STREAMING”单独当作联测成功。

RFDC DDC/NCO 的跨器件确定性仍依赖 configure-time 公共 SYSREF/MTS；Stage 31 保存并门控非零 MTS result ID，但没有通过普通 AXI 软件写在 PPS 边沿重触发 RFDC NCO。若最终时钟硬件要求“每个观测起点重新 SYSREF/NCO update”，需由确定性硬件触发链完成，不能用 HTTP/AXI 软件时序代替。

### AXI-Lite 合同

基地址 `0xAC00`：

| 地址 | 读写 | 内容 |
|---:|:---:|---|
| `AC00` | R | capability/version |
| `AC04` | W | bit0 PREPARE，bit1 ARM，bit2 ABORT，bit3 CLEAR_STATUS |
| `AC08` | R | status flags |
| `AC0C` | R | error code |
| `AC10..17` | RW | generation |
| `AC18..1F` | RW | 本板 local target PPS count |
| `AC20..27` | RW | observation epoch TAI seconds |
| `AC28..2F` | RW | first_sample0（raw ADC sample unit） |
| `AC30..37` | RW | observation tag |
| `AC38` | RW | signal-chain/config tag |
| `AC3C` | RW | schedule tag |
| `AC40` | RW | configure-time MTS result ID |
| `AC44..4B` | R | active generation |
| `AC4C..53` | R | actual local commit PPS count |
| `AC54..5B` | R | actual raw ADC epoch sample0 |
| `AC5C..63` | R | actual first TIME sample0 |
| `AC64..6B` | R | actual first SPEC sample0 |
| `AC6C..73` | R | current local PPS count |

status bits 0..12 分别为 selected、prepared、armed、epoch committed、epoch valid、streaming、error、PPS recent、reference locked、RFDC ready、MTS valid、first TIME seen、first SPEC seen；状态值在 19:16。

错误码 1..13 覆盖 busy、不可达 first_sample0、generation、MTS、reference、RFDC、PPS、状态、lead 不足、错过 PPS、错过首拍、无效 signal-chain tag 和无效 TAI epoch。

### Packet v3

Stage 31 active 时 packet header version 为 3，`epoch_mode=2` 明确 word 2 是 TAI seconds：

| word | 内容 |
|---:|---|
| 12 | sync generation |
| 13 | observation tag |
| 14 | `{signal_chain_tag, schedule_tag}` |
| 15 | `{mts_result_id, sync_status}` |

非 Stage 31 数据仍发 version 2。Python parser 和 Rust receiver 同时接受 v2/v3。

## Vivado 实现闭合与本地产物

2026-07-17 已在 attach 的 Vivado 2022.2 GUI 会话中完成初版 production build，
并在 2026-07-18 发布到单块 T510。Hub 联测暴露双时钟域 flush 缺口后，同日重新完成
顶层综合、实现、布线、`write_bitstream` 和 overlay 导出；以下数值均是修复版 build，
不是初版 bit 的复用报告。

- 工程 part 为 `xczu47dr-ffve1156-2-i`，top 为 `t510_fengine_board_top`，`synth_1` 状态为 `synth_design Complete!`，`impl_1` 状态为 `write_bitstream Complete!`。
- route status 为 fully routed `229935/229935`，routing errors 为 0。
- setup 为 `WNS=+0.012 ns`、`TNS=0`、失败端点 `0/335156`；hold 为 `WHS=+0.010 ns`、`THS=0`、失败端点 `0/335156`；pulse width 为 `WPWS=+0.052 ns`、`TPWS=0`、失败端点 0。Vivado 结论为所有用户时序约束满足。
- 资源占用为 CLB LUT `103408/425280 (24.32%)`、register `126161/850560 (14.83%)`、BRAM tile `520/1080 (48.15%)`、DSP `600/4272 (14.04%)`、URAM `0/80`。
- routed DRC 的 `825` 项均为 Warning/Advisory：`DPIP-2=480`、`DPOP-3=96`、`DPOP-4=160`、`REQP-1857=24`、`RTSTAT-10=1`、`AVAL-155=64`。前四类主要是 AA FIR DSP pipeline 与 RAM collision mode 的实现建议；它们没有形成 DRC error、routing error 或时序失败，但保留在报告中供后续功耗/裕量优化审计。
- 唯一 Critical Warning 是厂商 CMAC catalog 的历史 `Vivado 12-1790` evaluation-license metadata。实际 XCI/实现配置为 `INCLUDE_RS_FEC=1`、`INCLUDE_AUTO_NEG_LT_LOGIC=0`、`INCLUDE_AN_LT_TX_TRAINER=0`，所以没有启用受限 AN/LT 功能；按仓库永久规则归类为非阻塞 warning，而不是忽略真实 license enable。
- bit 头部可读到 design `t510_fengine_board_top`、part `xczu47dr-ffve1156-2-i`、Vivado `2022.2`、构建时间 `2026-07-18 07:57:58`。Vivado MCP 的离线 bit 解析器受文件大小保护限制时，仍以头部字符串、run 产物路径和 SHA256 三方核对。
- run bit、本地 overlay bit 和 build-only release 内 bit 的 SHA256 均为 `21357385978297a688e9418e086852d4a8aac2deaa25078e1570b81cdc4266c9`。overlay 的 `.bit/.hwh/.tcl/manifest` 已重新导出；manifest 仍明确 `ltx=`，本轮没有 ILA probe 文件。
- 与 bitstream 一致的 `T510_STAGE27H_PRODUCTION_ONLY + T510_STAGE27I_ANTI_ALIAS + T510_STAGE27J_PFB` 顶层 XSim 已 PASS 到 `1,193,925 ns`；该 run 先验证 STOP、ABORT 在 data/CMAC 两域各形成一次 reset，再验证 production PFB/SPEC CMAC frame。TIME/SPEC 半包、CMAC source mux 解锁和 scheduler `valid && ready` 另有定向 testbench 覆盖。
- Board Agent 已更新为 `0.2.1`。修复版 release
  `stage31-54a3e73cf7af-20260718083108` 已安装到 T510 `192.168.100.117`，fresh
  configure 回读的新 bit SHA 与 catalog 一致，并通过
  `START -> ABORT -> STOP -> IMMEDIATE START` 恢复 smoke；详细板端证据见
  `../board/stage31_pipeline_flush_recovery_smoke_20260718.md`。

完整产物保存在 `reports/vivado/stage31_multiboard_sync_0x00010031/`，其中 `vivado_build_summary.txt` 是闭合摘要，`cmac_license_audit.txt` 保存 license 判定依据，另保留 routed timing、route status、DRC、methodology、utilization、power 和 clock-utilization 报告。

### 修复版上板恢复复测

修复版 fresh configure 后，第一次 immediate start 的两次快照中 TIME packets 从
`8,632,830` 增至 `17,438,909`，SPEC packets 从 `8,632,751` 增至 `17,438,828`，
RFDC drop 保持 `7`。随后执行现场故障原序列 `ABORT -> STOP -> IMMEDIATE START`，
第二次启动的三个快照中 TIME/SPEC 最终增至 `28,179,891/28,179,808`，RFDC drop
保持 `35`，science/TIME/SPEC/TX drop 与 route error 均为 0，不再需要 reload bitstream
恢复。测试后再次 STOP，板卡保持修复版和已配置 profile，pipeline clean、FIFO 空、RFDC
ready，供 Center Hub 从干净状态开始 PREPARE/ARM 联测。

本轮只闭合单板 pipeline recovery，不把它写成修复版多板同步通过；共同 PPS/SYSREF、
共同输入、修复版 PREPARE/ARM 首包和 Hub 实际接收仍待联合验证。运行中还观察到 QSFP
link/mux 瞬时抖动，science producer 未卡死，但联测时必须结合 Hub 收包继续监控。

### 初版单板发布记录

以下现场记录对应初版 SHA `3696845d30dc471f572904b7039aa231bc766a21be05de7796d53704f8d08eec`
与 Agent `0.2.0`，只保留为 Stage 31 初始功能证据。真实 PREPARE/ARM 在 local PPS
`199` 精确提交，最终 state 为 STREAMING，TIME/SPEC 首 sample0 均为 `32788`，同步错误
和数据面 drop/route error 为 0。八路 `60.010 MHz`、约 6% DAC 自环在两次 preview
中全部命中，SNR 约 `50.7..52.6 dB` 且无 clipping；这些结果不能替代修复版重新上板后的
STOP/ABORT/restart 回归。

真实板还表明无状态 helper 的进程启动/import 需要数秒，因此协调脚本不能使用 50 ms 双 HTTP 采样。当前实现使用一次内部原子快照、默认 lead 30 PPS、HTTP timeout 45 秒；板端 Agent operation timeout 为 30 秒。

## 无 Hub 使用

先用 Stage 29/30 configure 流程完成 clock、RFDC、MTS、PFB 和路由。成功的 MTS 详情被规范化后生成非零 result ID，并写入 Stage 31 寄存器。

检查每块板：

```bash
curl -sS http://BOARD_IP:8010/api/v1/sync/status | jq
```

小规模多板同时准备/ARM：

```bash
scripts/stage31_multiboard_sync.py \
  --board http://192.168.100.117:8010,1 \
  --board http://192.168.100.118:8010,2 \
  --generation 7 \
  --epoch-tai 1784256005 \
  --signal-chain-tag 0x5a31c004 \
  --observation-tag 0x202607170001 \
  --schedule-tag 0x31
```

每次 helper 响应内部是一份原子寄存器快照。由于无状态 PYNQ helper 的进程启动和 import 在真实板上需要数秒，不能用两次相隔 50 ms 的 HTTP 请求证明“没有跨 PPS”；协调脚本改为对所有板并行读取一次原子快照，并给每板下发 `local current_pps_count + lead_pps`，默认提前量由 5 PPS 增加到 30 PPS，以覆盖 status→PREPARE→ARM 的进程启动时延。因此各板本地 PPS 计数可以不同，但只要它们的 PPS 是同一物理脉冲，都会在各自对应的未来计数提交。PREPARE 或 ARM 部分失败时，对已准备板执行 best-effort ABORT。

`epoch_tai` 必须由可信 TAI/GNSS 时间源给出，并对应将要提交的物理 PPS。当前板端没有独立的 TAI-of-current-PPS 硬件寄存器，所以脚本无法仅靠本地 PPS 计数证明该 TAI 映射；Center Hub/时间接收机接入后应把这个关系变成硬件可校验字段。

## 现在没有下发器/功分器时能验证什么

### 可以完成

1. 每块板分别接本板 DAC→ADC，自循环验证 cold/warm restart 后 `actual_commit_pps`、epoch、first TIME/SPEC sample0 和本板相位是否可复现。
2. 用一块板 DAC→另一块板 ADC，验证跨板电气链能进入 ADC、相同 Stage 31 generation/TAI/sample0 能贯穿 packet/F-engine，并测该一条链的固定延迟。
3. 运行 RTL 回归，验证 prepare/arm/abort、PPS 精确提交、AA/PFB/XFFT reset、首拍不丢和 packet v3。
4. 先完成控制/API、配置 ID、MTS provenance、收包解析与离线相位算法。

### 不能据此宣称

- 一根 DAC→ADC 跨板线没有同时给两块 ADC 同一个随机过程，不能测两块采集板的相对孔径/模拟相位。
- 两块板各用自己的 DAC 互测时，PL tone phase reset 和 DAC 模拟路径本身也是未知量；测到的是两套 DAC+ADC 路径之差，不是纯 ADC/F-engine 对齐。
- 顺序拔插同一根线只能做重复性检查，连接器重插和时间漂移会混入结果。
- 共 10 MHz、相同 sample0 或相同 tone 峰值都不能单独证明相干。

因此目前可以把数字事务和单链路诊断准备完；最终跨板相位验收仍需要“一源同时分路”：一台低相噪源或一块 DAC，经 2-way/多路功分器和已知/交换线缆同时送到所有 ADC。

## 有共同输入后的两种验证

### 1. 波形法

采集同一 generation 且重叠 sample0 的复电压，先去 DC/丢弃 AA priming，再计算：

```text
R_ab[l] = sum_n x_a[n] * conj(x_b[n+l])
lag = argmax_l |R_ab[l]|
phase = arg R_ab[lag]
coherence = |R_ab| / sqrt(sum|x_a|^2 sum|x_b|^2)
```

峰值 lag 给出整数样点差，phase 给出该 tone 上的固定相位。单 tone 的“固定相位”和“时延”不可分辨，至少要多 tone；更推荐宽带相关噪声。

离线工具接受 `.npy/.npz` 复数数组：

```bash
scripts/stage31_phase_compare.py waveform \
  --a board1_wave.npy --b board2_wave.npy \
  --sample-rate-hz 122880000 --max-lag 256 \
  --output reports/board/stage31_wave_board1_board2.json
```

`sample-rate-hz` 是数组中相邻复样点的实际速率，不是 raw sample0 标签速率；100 MHz science path 当前是 122.88 Msps。

### 2. F-engine 相位法

必须保存每板每通道的复数 F-engine 电压，不能使用 `|X|²` 功率谱。对同 generation、相同 sample0/frame/channel 的数据计算：

```text
V_ab[k] = mean_t X_a[k,t] * conj(X_b[k,t])
phi[k] = unwrap(arg V_ab[k])
phi(f) = phi0 - 2*pi*f*tau + residual(f)
```

斜率给出非色散相对群时延，截距是固定相位；去除拟合时延后的 residual RMS 才是跨带相位质量。归一化 `|V_ab|/sqrt(P_a P_b)` 用来排除低 SNR/RFI channel。

```bash
scripts/stage31_phase_compare.py fengine \
  --a board1_fengine.npy --b board2_fengine.npy \
  --freq-start-hz 50000000 --freq-step-hz 30000 \
  --output reports/board/stage31_fengine_board1_board2.json
```

数组形状为 `[frame, channel]`。`freq-start/step` 必须按实际 RF channel 顺序填写；若频谱方向、I/Q 或共轭约定错误，phase slope 的符号也会错。

建议每次至少记录 generation、epoch TAI、sample0、board/input map、signal-chain tag、MTS ID、PFB coefficient ID/hash、温度和线缆连接。先交换两块板的两根输入线：若差值跟着线走是线缆/模拟路径，跟着板走是板/RFDC/数字路径。

## 验收顺序

1. 无公共源：每板 20 次 warm/cold restart，确认 generation、首 TIME/SPEC sample0、错误码和本板自环相位无多峰跳变。
2. 有共同 tone 分路：确认整数 lag 可复现到 1 raw sample 或更好，记录每 tone 固定相位和 10 min phase RMS。
3. 有相关噪声分路：拟合跨带 delay；目标为小于 0.1 raw sample 的残余，并按方案首版门槛检查 350 MHz 下 10 min residual phase RMS <10°。
4. 人为断开 PPS/reference：确认 streaming 立即撤销、generation 结束且 error/clock-break 可追溯。
5. 至少 20 次 cold/warm restart 后再固化 `delay_calibration` 和 `complex_gain`；在此之前只能标为 engineering/commissioning 数据。

## 尚待物理硬件闭环

- 低相噪参考/采样时钟 fan-out、同源 PPS、analog_SYSREF/PL_SYSREF 拓扑与线缆标定。
- 每板 PLL/SYSREF capture window 和逐 tile/device MTS latency 的黄金分布比较；当前 Stage 31 用 result ID 证明“执行过”，没有把全部 latency 明细放入包头。
- 可信 current-PPS→TAI 的硬件映射和 leap-second table ID。
- 若要求观测起点同步重置 PL DAC tone/RFDC NCO，增加 DAC-clock/RFDC 硬件触发，不使用软件到达时间。
- 公共 tone/噪声分路、线缆交换、温漂和断锁注入测试。
- X-engine 侧按 `(generation, epoch_tai, signal_chain_tag, sample0, channel)` 聚合，并拒绝 MTS/config/status 不一致的数据。
