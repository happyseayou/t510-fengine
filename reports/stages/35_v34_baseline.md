# Stage 35：v34 硬件与控制基线统一

> 日期：2026-08-30
> 状态：仓库基线与本地发布包已完成；板端发布未执行

## 1. 基线定义

Stage 35 不新造一个 FPGA 版本。它固定使用已经完成全速发布验证的 v34：

- `CORE_VERSION=0x00010034`；
- 8 路复数 IQ16；
- 160/320 MS/s；
- 4096 通道、8-tap PFB；
- TIME/SPEC 生产 UDP；
- 正式 bitstream SHA-256：
  `c21d93f5ea71e9ac17a4448cff138a8faaf9c7347d879be919b680d196b8a5be`；
- routed WNS/WHS：`+0.046/+0.010 ns`；
- 固定 MTS ADC/DAC target：`416/112`。

“统一到 v34”只约束 FPGA 数据通路和 Agent 可发布的 bitstream 身份，不表示把软件整体
退回旧日期。Stage 35 软件继续向前维护，但必须只控制 v34，并为科学采集提供明确、可复现
的配置。

## 2. 精确源码恢复

v34 构建当时没有形成独立 Git commit。此次没有从 v33/v35 人工拼接，而是从 Git 尚未回收
的对象中恢复了完整源码：

- v34 RTL tree：`f2b306e8055e0ea3825e0047fd6bb43d382a43c9`；
- 含 v34 XPR 的根 tree：`1bacfd3a2a4e03a22902c6875a557efa593c841e`；
- `rtl/feng_ctrl_axi.sv` blob：
  `6650f43b5f49165342ff7bed29dce141f16daa18`。

活动 `rtl/`、`bd/`、`xdc/`、`demo-ant.xpr`、仿真 source list 和导出脚本已经与这套 v34
工程一致。v35 的 PL SYSREF recapture、v36 的 ADC interleave spur corrector，以及 Stage 34f
ADC-only/诊断 RTL 均不属于本基线。

## 3. 32-beat 弹性 FIFO

未提交的 32-beat FIFO 是 v36 spur-corrector 输出端的启动缓冲，用来吸收 320 MS/s START
瞬间的下游反压。v34 没有该 spur-corrector 插入点，而且原 v34 已完成全速验证，因此不能把
这个 FIFO 静默混入科学基线。

该变更已从活动 RTL 移除，并作为可恢复补丁保存在仓库外：

```text
/home/astrolab/.t510-stage34f-archive.2wVXeh/source-patches/
v36-spur-start-elastic-fifo.patch
SHA-256 96952eb97fa19865c4b0c997e3945882f48dd3e195be3d267cbdedc54e357eeb
```

若未来重新设计 FPGA，必须把它作为一个独立的新版本变更重新评审、仿真和走完整 Vivado
构建链，不能把修改后的设计继续标作 v34。

## 4. Agent 与无 WR 模式

Agent 以 v36 之前、与正式 v34 发布包一致的控制源码为起点，移除了 v36 杂散校正事务和
对应 packet flag、API、watchdog tracker、接收机解释及测试。bitstream catalog 只接受
`0x00010034`，不再接受 v35/v36 诊断 image。

Stage 35 新增 CONFIGURE 字段 `clock_reference`：

| API 值 | LMK 输入/策略 | 同步语义 | 外部连接 |
|---|---|---|---|
| `onboard_tcxo` | CLKin0，request-mode SYSREF 只在 MTS 时开启 | `free_run`，以 `sample0` 表示相对时间 | 不需要外部 10 MHz/PPS |
| `external_10mhz` | CLKin2，continuous SYSREF | `external_pps` | 需要有意提供外部 10 MHz/PPS |

为了兼容旧请求，省略字段仍默认为 `external_10mhz`；Stage 35 配置和数据 manifest 必须显式
写 `onboard_tcxo`。此前调查得到的 LMK CLKin0 修复也被正式保留：R0x147 的 CLKin0 buffer
选择为 `2`，避免 PLL1 输入被关闭。

## 5. 当前边界

- 仓库源码基线已经回到 v34；正式 v34 bit/HWH/BD Tcl 仍保留，无需为这次统一重新构建。
- 板上此前仍运行 Stage 34f v42 ADC-only image；本次源码整理本身不等于板端已经发布。
- Agent 0.3.6 和采集端的 ARM64 musl 本地发布包已重新生成并校验，但未部署到板上或采集机。
- 若后续发现必须修改 RTL，则新设计必须使用新的 `CORE_VERSION`，并严格按 `AGENTS.md`
  通过已 attach 的 Vivado GUI 一次性武装完整
  `synth_1 -> impl_1 -> write_bitstream` 链。

## 6. 回归与包一致性

2026-08-30 完成的本地验证：

- Python：206 项通过，2 项历史现场证据用例跳过；
- Board Agent Rust：8 项通过；
- 采集端 Rust：49 项通过；
- XSim：18 个当前 v34 testbench 全部通过；
- 仓库卫生、Rust format、JSON 和 Python 语法检查通过；
- `overlay/`、Vivado 归档和新板端包中的 bitstream SHA-256 均为
  `c21d93f5ea71e9ac17a4448cff138a8faaf9c7347d879be919b680d196b8a5be`；
- bitstream catalog 只含 `fengine-0x00010034`，板端 Agent 和采集端发布件均为
  静态链接 ARM64 二进制。

本次没有启动 Vivado 综合/实现：仓库恢复的是构造正式 v34 bit 的精确源码，发布包也使用已经完成
时序、DRC 和板上全速验证的同一份 bitstream。重跑布线会产生不同物理布局，反而不再是本次要固定的实验基线。

## 7. Stage 35 下一步

基线统一完成后直接进入 S0：在采集机现有 Rust SPEC 接收路径中实现 8×4096 全频段、
按 `sample0` 分桶的 10/20/50/100 ms 自相关累加器和分块 writer。先用合成数据与 packet
replay 验证，再做 60 s 板上烟雾采集；此阶段不再修改 FPGA RTL。
