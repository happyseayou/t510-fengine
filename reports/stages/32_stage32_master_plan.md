# Stage 32：160/320 MS/s 双速率与多板同步总体任务

## 当前结论

2026-07-29 外部绝对RF输入发现Stage 32接收页面把复频率符号映射反向：
center为170 MHz时，真实280 MHz输入被标为60 MHz，真实60 MHz输入被标为
280 MHz。随后ADC0/ADC1的外部280 MHz实测分别取得约72.7/74.9 dB镜像抑制，
证明ADC、PFB和UDP数据本身没有产生此前DAC自环中的强镜像；DAC直接接频谱仪则
确认梳状杂散真实存在于DAC侧。Stage 32h因此从`PASS`重新置为`IN_PROGRESS`，
新增依赖链`32h1 -> 32h2 -> 32h3`，分别闭合接收频率轴、DAC DDS复数方向和
DAC频谱纯度。既有吞吐、切换、故障恢复和长稳证据继续有效，但在三个新增步骤
全部取得证据前不再声明Stage 32单板release闭合。

Stage 32 已正式进入实施阶段。`32a` 的 LMK 离线集成已经 `PASS`；`32b` 已完成
10次Stage 32 LMK reload、双PLL锁定和寄存器回读，在“当前无法物理接触板卡”的
约束下按远程功能门禁判定为 `PASS`。`32c` 已完成Stage 32 bitstream的BD、综合、
实现和导出，并已在板上完成MTS discovery/fixed与八路DAC-ADC门禁，判定为
`PASS`。`32d` 的320 MS/s TIME_ONLY板端与接收机60秒满速门禁也已完成，判定为
`PASS`。`32e` 已完成55-tap half-band数字频响、定点动态仿真、160 MS/s
TIME_ONLY满速门禁和定时首样点验证，判定为`PASS`。`32f`已完成160 MS/s
SPEC_ONLY、TIME_SPEC以及八路tone的bin/IQ验证；`32g`已完成320 MS/s SPEC_ONLY
满速门禁，均判定为`PASS`。`32h-a`五模式10分钟和`32h-b`三模式各1小时满线速
矩阵也已全部通过。`32h-c`已取得14次连续PPS边界切换PASS，第15次320
SPEC_ONLY捕获一次新增PFB overflow/XFFT event。该启动问题和随后第10个PPS前的
单帧尾块缺失已分别定位为XFFT配置时序及恰好1秒的PPS recent超时边界；最终
PPS guard bitstream完成Vivado闭合，并通过3次针对性定时PPS 320 SPEC_ONLY
板端/主机测试，`32h-c`已`PASS`。`32h-d`的Linux warm reboot、UART启动观察、
同release重新CONFIGURE/MTS和320 SPEC_ONLY恢复门禁已`PASS`。活动流物理断PPS
已正确锁存`pps_not_recent`并自动停流，判`PASS`。活动流物理断10 MHz最初明确
暴露PL不可见PLL1 lock的问题；现已部署
`stage32-ref-watchdog-r2-20260727`常驻PS watchdog，通过LMK SPI连续两次确认
失锁后直接调用现有STOP/flush。最终物理测试锁存`LMK_PLL1_UNLOCKED`，PL确认
停止延迟`0.257 ms`且flush clean；接线恢复后直接START仍被fault latch拒绝，
fresh CONFIGURE/MTS和320 TIME_ONLY 20秒无损恢复门禁均`PASS`。所有PYNQ额外
修改和跨进程CONFIGURE互斥记录在
`../deployment/stage32_pynq_replication_guide.md`。RFDC驱动
`Reset()`/`ShutDown()`没有使PL可见的`rfdc_ready`下降，现已正式归类为维护动作，
不再冒充故障注入。生产信号合同由新增XSim闭合：预约流STREAMING中拉低
`rfdc_ready`，下一拍必须停流、锁存`RFDC_NOT_READY / code 6`，ready恢复后也
不得自动重启；测试已PASS且没有修改RTL/bitstream。因此`32h-d`改为`PASS`。
真正整板断电冷启动、服务自启、配置前fail-closed、fresh CONFIGURE/MTS和20秒
320 TIME_ONLY无损恢复也已`PASS`。最后的160 TIME_SPEC、320 TIME_ONLY和320
SPEC_ONLY各10分钟针对性soak全部通过，因此`32h`改为`PASS`，Stage 32单板
release正式闭合。由于实验室当前只有一块 T510，`32i`状态仍为`BLOCKED`，
Stage 32总体保持`IN_PROGRESS / BLOCKED_BY_HARDWARE`，不能用单板重复性替代
双板物理同步。

`reports/arch/` 中的设计文档和 TICS 文件是架构输入，本文件和各 `32x` 报告才是执行
状态的唯一来源。

## 冻结规格与名词

- **复采样率**：网络中相邻 complex IQ16 样点的速率。Stage 32 为 160 或
  320 MS/s，不等同于平坦模拟带宽。
- **建议科学带宽**：RFDC 和 anti-alias 过渡带之外建议使用的平坦频带；
  160 MS/s 对应约 128 MHz，320 MS/s 对应约 256 MHz。
- **RFDC 基准路径**：ADC 1.6 GS/s、5x decimation，固定产生 320 MS/s complex；
  DAC 1.6 GS/s、5x interpolation，固定消费 320 MS/s complex。
- **PL 数据接口**：ADC/DAC AXIS 均为 80 MHz；ADC 聚合 science bus 保持
  1024 bit，每拍 8 input × 4 complex sample × IQ16。
- **160 MS/s 路径**：在 PL 内对 320 MS/s 做 2x、55-tap half-band 抽取。
- **同步时钟**：外部 CLKin2 10 MHz；LMK VCO0 2400 MHz；RFDC/PL reference
  160 MHz；Analog/PL SYSREF 为 continuous 10 MHz。
- **网络冻结**：T510 header 128 B、science payload 8192 B、TIME 端口
  `4300..4307`、SPEC 端口 `4308..4323`、IQ16 和 24 endpoint 均不改变。
- **以太网时钟例外**：CMAC 322.265625 MHz 是独立网络时钟，不是多板采样相位
  基准，不纳入“同步相关时钟为 10 MHz 整数倍”的约束。

## LMK 冻结基线

| 项目 | 值 |
|---|---|
| TICS profile | `../arch/lmk04828_stage32_min_delta_160_10m_cont_manual_clkin2.tcs` |
| register export | `../arch/lmk04828_stage32_min_delta_160_10m_cont_manual_clkin2_registers.txt` |
| TCS SHA256 | `a9fac413bf18ff7bda1844284f72e59fde3e72dcfceed6144b59dcbda82f216e` |
| register SHA256 | `9bface367f371a0b3bc2c7f659b2c62aecb976a0fc32bc8658ef3e0a0c6b032a` |
| 写入条数 | 136 |
| SYSREF | 10 MHz continuous |
| 输入选择 | manual CLKin2 / external 10 MHz |

相对论文黄金 profile 的受控差异只允许：

- `0x118: 0x18 -> 0x0f`：DCLKout6/PL clock 从 100 MHz 攓为 160 MHz；
- `0x138: 0x05 -> 0x00`：关闭 OSCout，释放 CLKin2 输入路径。

## 状态表

| 子阶段 | 状态 | 目标 | 报告 |
|---|---|---|---|
| 32a | `PASS` | LMK profile、控制器和离线审计 | `32a_lmk160_profile_integration.md` |
| 32b | `PASS` | LMK远程clock-only功能门禁 | `32b_lmk160_clock_only_board_gate.md` |
| 32c | `PASS` | ADC/DAC 1.6 GS/s、80 MHz PL、MTS | `32c_rfdc_adc_dac_1p6g_mts.md` |
| 32d | `PASS` | 320 MS/s TIME_ONLY | `32d_320msps_time_only.md` |
| 32e | `PASS` | 160 MS/s、80 dB half-band、TIME | `32e_160msps_halfband80_time.md` |
| 32f | `PASS` | 160 MS/s SPEC_ONLY/TIME_SPEC | `32f_160msps_spec_dual.md` |
| 32g | `PASS` | 320 MS/s SPEC_ONLY | `32g_320msps_spec_only.md` |
| 32h | `IN_PROGRESS` | 单板产品矩阵、频率真值和长稳 | `32h_single_board_release_soak.md` |
| 32h1 | `IN_PROGRESS` | 外部绝对RF频率轴 | `32h1_external_rf_frequency_axis.md` |
| 32h2 | `NOT_STARTED` | DAC DDS复数方向与新bitstream | `32h2_dac_dds_iq_direction.md` |
| 32h3 | `NOT_STARTED` | DAC频谱仪纯度门禁 | `32h3_dac_spectral_purity.md` |
| 32i | `BLOCKED` | 双板共同输入物理闭合 | `32i_multiboard_physical_closure.md` |

## 依赖和放行规则

```text
32a -> 32b -> 32c -> 32d -> 32e -> 32f -> 32g
     -> 32h既有门禁 -> 32h1 -> 32h2 -> 32h3 -> 32i
```

- 失败的时钟门禁不得通过修改数据面绕过。
- 每个步骤必须保存实际命令、Git/bit SHA、`CORE_VERSION`、板卡地址、时间戳和报告。
- Vivado 证据放在 `reports/vivado/stage32*/`，板端/主机 JSON 放在
  `reports/board/`。
- Stage 32 UDP主机门禁使用 `astrolab@192.168.100.162`；sudo凭据只允许在运行时
  交互输入，不得写入仓库、报告、脚本参数或命令日志。
- 32a 到 32h 全部通过后，只能声明“Stage 32 单板 release”。
- 只有 32i 取得两块板、公共 10 MHz/PPS 和共同射频输入的实测证据后，本阶段总体
  才能标为 `PASS`。

## 已知偏差与风险

### CLK-DEV-001

AMD PG269 对 RFDC MTS 的文字要求为 SYSREF `<10 MHz`，本项目采用论文同款 T510
已验证拓扑的 exact 10 MHz continuous SYSREF。处置是条件接受并在当前 bitstream、
RFDC driver 和板卡上重新验证。若 MTS 不稳定，停止 Stage 32 并重新评审；不得静默
切换为 5 MHz。

### 单板硬件边界

当前只有一块 T510。单板可以完成 tile 内 MTS、固定 target latency、PPS epoch、
8 路 DAC-ADC 自环和重启重复性，但不能证明跨板模拟相位和相关孔径一致。

### REMOTE-EVID-001

现场现在可以操作10 MHz、PPS线缆和整板电源；活动流物理断线和真正断电冷启动
门禁均已实际执行。当前仍没有示波器证据直接测量
160 MHz占空比、continuous 10 MHz SYSREF波形和OSCout噪声底。剩余限制不阻止
Stage 32 32a..32g单板功能开发；
32h-d要求的fault-stop证据单独判定，不能由以下重复性证据替代：

- LMK 10/10 reload锁定和关键寄存器回读；
- Stage 32 bitstream内Clock Wizard/data-clock lock；
- RFDC tile/FIFO ready和ADC/DAC数据活动；
- continuous SYSREF下MTS discovery/fixed重复性；
- LMK reload、RFDC reset、overlay reload和Linux暖重启恢复。

这些证据能证明系统实际可运行且重复同步，但不能替代模拟波形质量和真正掉电启动
结论。2026-07-27的活动流物理测试证明PPS丢失由PL scheduler自动停流；10 MHz
丢失最初不会被PL检测，随后由常驻PS watchdog闭合：LMK PLL1失锁后自动STOP、
fault latch、fresh CONFIGURE恢复和20秒主机无损门禁均已PASS。将来补测冷启动和
波形质量本身不追溯阻塞32a..32g。

2026-07-26 对工作站USB路径的只读调查确认：

- Digilent Adept FT2232双接口设备序列号为`210279113854`，枚举为
  `/dev/ttyUSB0`和`/dev/ttyUSB1`；当前用户属于`dialout`组。
- `/dev/ttyUSB1`已有持续运行的`picocom`记录器，日志能看到T510 Linux完整启动
  过程，因此它可作为暖重启观察和网络失联后的UART救援路径。Stage 32测试不得
  抢占、终止或并行打开该端口。
- Vivado `hw_server`虽然在`127.0.0.1:3121`运行，但只读查询得到
  `get_hw_targets=0`、`get_hw_devices=0`；当前不能把USB当作可用JTAG下载路径。
- 该USB连接没有已验证的主板电源开关能力，也未安装可用的USB hub逐端口电源控制
  工具；不得用USB重新枚举冒充T510冷启动。

因此，当前采用只面向Stage 32的四层远程恢复矩阵：

| 层级 | 操作 | 通过依据 | 当前状态 |
|---|---|---|---|
| R1 | Stage 32 LMK profile reload | PLL1/PLL2、profile ID、关键寄存器 | 32b已`10/10 PASS` |
| R2 | RFDC reset后重新执行固定MTS | tile/FIFO ready、固定latency、无错位 | 32c已`20/20 PASS` |
| R3 | 重新加载Stage 32 overlay | bit SHA、Clock Wizard、RFDC/MTS | 32c已`10/10 PASS` |
| R4 | Linux warm reboot | UART启动日志、网络/Agent恢复、再走完整Stage 32发布顺序 | 32h已`PASS` |

R1..R4是已经完成的功能恢复和重复性验证；它们都不等价于整板断电。
物理拔除10 MHz/PPS和真正冷启动均已实测，不再属于缺失证据；示波器时钟质量仍
记入`REMOTE-EVID-001`，不伪造结论。

## Stage 32发布顺序

固定顺序：

```text
停止 science
-> 清空 TIME/SPEC/CMAC pipeline
-> 写入 Stage 32 LMK profile
-> 验证 LMK lock/readback
-> 下载 Stage 32 bitstream
-> RFDC init/MTS
-> 放行 science
```

Stage 32执行和准入范围只包含本计划冻结的LMK profile、bitstream和软件release。
失败处置固定为停止science、保存证据、修复Stage 32配置后重新从LMK lock开始；
不得切换到范围外的profile或bitstream来通过当前阶段门禁。

## 当前实现证据

- Stage 32 bitstream：
  `439080046408267493a031efa1d097fcd3c2f818850ee9eac1925ae95d6b094c`。
- 最终PPS recent guard构建fully routed，routing error为0，WNS
  `+0.081 ns`、WHS `+0.009 ns`，DRC/Methodology Error和Critical Warning均为0：
  `../vivado/stage32h_pps_recent_guard/build_summary.md`。
- 45个Python测试、Board Agent 5个Rust测试、receiver 36个Rust测试、31个默认
  XSim testbench和LMK/half-band离线检查：
  `../vivado/stage32c/local_verification.md`。
- 32b远程功能门禁已通过，允许下载该bitstream进入32c；在MTS discovery/fixed和
  八路自环完成后，32c已 `PASS`。
- 固定MTS target：ADC `230`、DAC `336`；后续单板和未来第二块板必须使用相同值。
- Stage 32 Board Agent/watchdog release：
  `stage32-ref-watchdog-r2-20260727`；接收机release：
  `stage32-53f46bb73a2d-20260726070721`，接收机binary SHA256为
  `56d19e0686aafa022581e7a9b59cb40dfe7464edcd0a92117f5b0226e99fe5db`。
- 32d正式门禁：主机60秒收到`75,032,400`个TIME包，`1,250,540 pps`、
  `83,235.9424 Mbit/s` T510 UDP payload；SPEC包、主机parse/kernel/ring/app
  drop、sequence/frame/sample0 gap和板端新增drop/error均为0：
  `../board/stage32_320msps_time_only_board_host_pass_20260726.json`。
- 32e正式门禁：主机60秒收到`37,516,944`个TIME包，`625,282.4 pps`、
  `41,618.796544 Mbit/s` T510 UDP payload；SPEC包、主机drop/gap和板端新增
  drop/error均为0，half-band保持active/primed：
  `../board/stage32_160msps_time_only_board_host_20260726.json`。
- 32e定时首样点：generation `32160001`在PPS 234提交，
  `actual_first_time_sample0=32788`且`32788 mod 8 = 4`，同步错误为0：
  `../board/stage32e_160msps_scheduled_first_sample0_20260726.json`。
- 32f SPEC_ONLY：60秒主机`625,238.9 pps`、`41,615.901184 Mbit/s`，
  16个SPEC flow无drop/gap，PFB/XFFT错误增量均为0：
  `../board/stage32_160msps_spec_only_board_host_20260726.json`。
- 32f bin/IQ：100 MHz center下的120 MHz tone在8路完整4096-bin snapshot中
  全部落到预期`+512` bin，而非IQ反向的3584，bin宽`39.0625 kHz`：
  `../board/stage32f_160msps_pfb_bin_iq_receiver_20260726.json`。
- 32f TIME_SPEC：90秒主机TIME `625,009.6 pps`、SPEC `625,031.5 pps`，
  合计`83,202.737095 Mbit/s`，24 flow无drop/gap，PFB/XFFT错误增量均为0：
  `../board/stage32_160msps_time_spec_90s_link_diagnostic_20260726.json`。
- 32g 320 SPEC_ONLY：60秒主机SPEC `1,250,581.33 pps`、
  `83,238.693547 Mbit/s`，TIME为0，16 flow无drop/gap，PFB/XFFT处理
  `5,434,738`帧且错误/反压增量均为0：
  `../board/stage32_320msps_spec_only_board_host_pass_20260726.json`。
- 32h-a五模式10分钟矩阵：五项全部PASS，160单流约`625 kpps`、160 TIME_SPEC
  和两个320单流约`1.25 Mpps / 83.20 Gbit/s`，全部主机drop/gap和板端
  PFB/XFFT/drop/error增量为0，每项STOP后pipeline clean：
  `../board/stage32h_ten_minute_summary_20260726.json`。
- 32h-b三组各1小时满线速矩阵：160 TIME_SPEC、320 TIME_ONLY和320 SPEC_ONLY
  全部PASS，合计流量分别为`83,199.668938`、`83,200.351733`和
  `83,198.948648 Mbit/s`；三项主机drop/gap、板端drop/error及SPEC路径
  PFB/XFFT错误均为0，每项STOP后pipeline clean：
  `../board/stage32h_full_line_summary_20260726.json`，汇总SHA256为
  `24dcbe4541f8f17962f3c7d3c5b7c2f3f0033e52a8cd90d175e8cc6aa16297ad`。
- 32h-c最终PPS guard bitstream的定时320 SPEC_ONLY针对性复测为3/3 PASS：
  60秒一次、20秒两次，SPEC均约`1.2506..1.2507 Mpps /
  83.24 Gbit/s`，16 flow无sequence/frame gap，板端PFB/XFFT和所有drop/error
  增量为0：
  `../board/stage32h_pps_switch_summary_pps_recent_guard_host60.json`和
  `../board/stage32h_pps_switch_summary_pps_recent_guard_repeat20.json`。
- 32h-d RFDC驱动动作是信号语义证据：8 tile `Reset()`调用成功但PL的
  `rfdc_ready`始终为true且流继续；`ShutDown()`后的driver restart也没有使该
  ready信号下降，因此这些调用归类为维护动作。相同bit的fresh CONFIGURE/MTS及
  320 TIME_ONLY 20秒恢复门禁PASS：
  `../board/stage32h_rfdc_reset_fault_20260727.json`和
  `../board/stage32h_rfdc_fault_recovery_320_time_20s_20260727.json`。
- 32h-d RFDC ready-low数字故障门禁PASS：板顶层
  `all_adc_valid -> rfdc_ready_in`，活动预约流中拉低ready后，调度器下一拍进入
  ERROR、锁存`RFDC_NOT_READY / code 6`并清除streaming；ready恢复后不自动
  重启，只有显式ABORT清错。目标XSim没有修改RTL或生成bitstream：
  `../vivado/stage32h_rfdc_ready_fault_gate/verification.md`。
- 32h-d/p1的PS reference watchdog物理门禁PASS：活动320 TIME_ONLY中断开
  10 MHz后锁存`LMK_PLL1_UNLOCKED`，PL STOP确认延迟`0.257 ms`且flush clean；
  接回参考后直接START被HTTP 409拒绝，fresh CONFIGURE/MTS清除锁存，随后20秒
  主机收到`25,017,248`个TIME包，`1,250,862.4 pps /
  83,257.401344 Mbit/s`，所有主机drop/gap和板端drop/error增量为0：
  `../board/stage32h_physical_10mhz_watchdog_pass_20260727.json`、
  `../board/stage32h_watchdog_recovery_configure_20260727.json`和
  `../board/stage32h_watchdog_recovery_320_time_only_20s_20260727.json`。
- 当前PYNQ相对基础镜像的全部额外修改、OS/xrfdc基线、GPIO/SPI映射、release
  SHA256、systemd单元、CONFIGURE互斥、逐板安装和验收步骤见
  `../deployment/stage32_pynq_replication_guide.md`。
- Linux warm reboot的boot-id变化和UART完整启动已归档；配置前Agent正确返回
  `PL_NOT_CONFIGURED`，随后同release完成固定MTS和定时320 SPEC_ONLY 20秒无损
  门禁：
  `../board/stage32h_warm_reboot_20260727/`和
  `../board/stage32h_pps_switch_summary_warm_reboot_recovery_host20.json`。
