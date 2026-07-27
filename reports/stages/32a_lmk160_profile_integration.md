# Stage 32a：LMK 160 MHz profile 离线集成

## 状态

`PASS`

## 目标

把TICS Pro导出的Stage 32 profile机械地集成到生产时钟控制器，证明 `.tcs`、
register export和Python写表逐项一致。

## 前置条件

- `reports/arch/lmk04828_stage32_min_delta_160_10m_cont_manual_clkin2.tcs`
- `reports/arch/lmk04828_stage32_min_delta_160_10m_cont_manual_clkin2_registers.txt`
- 外部输入固定为 CLKin2 10 MHz。

## 实施内容

- 增加无第三方依赖的 LMK profile 审计脚本。
- 集成 136 条 Stage 32 写表、profile ID、期望寄存器和 SHA。
- 修正 `CLKin_SEL1:CLKin_SEL0` 真值表。
- 时钟控制器显式区分 request/pulser 与 continuous SYSREF。
- continuous profile 的 MTS 流程不得通过 GPIO 关闭 SYSREF。

## 非目标

- 本步骤不写入真实 LMK。
- 不下载 bitstream，不修改 RFDC，不声明 160 MHz 实际波形通过。

## 验收

- TCS、register export、Python 初始化表三方 136/136 一致。
- 文件 SHA 与总体计划一致。
- 相对黄金 profile 只有 `0x118` 和 `0x138` 两项受控差异。
- Python语法检查和时钟控制器单元测试通过。

## 实际改动

- `python/t510_clock.py` 增加唯一 Stage 32 初始化表、profile ID、manual CLKin2
  配置入口和关键寄存器只读状态。
- Stage 32执行入口只接受`stage32_160`，通用时钟控制器中其他profile不参与本阶段
  执行、恢复或准入。
- SYSREF 控制显式分成 `continuous` 与 `request/pulser`；continuous 模式下
  `set_sysref()` 不切换 LMK SYNC GPIO，`pulse_sysref()` 会明确拒绝操作。
- `python/t510_fengine.py` 的 `T510Clock` 增加 profile 参数并把 SYSREF 模式传给
  MTS 前后的时钟控制。
- 新增 `scripts/stage32_verify_lmk_profile.py`。

## 测试命令与结果

```bash
python3 -m py_compile \
  python/t510_clock.py python/t510_fengine.py \
  scripts/stage32_verify_lmk_profile.py \
  scripts/pynq_stage32_clock_only.py
python3 scripts/stage32_verify_lmk_profile.py
```

结果为 `STAGE32_LMK_PROFILE_OFFLINE_PASS`：

- TCS SHA256：
  `a9fac413bf18ff7bda1844284f72e59fde3e72dcfceed6144b59dcbda82f216e`
- register export SHA256：
  `9bface367f371a0b3bc2c7f659b2c62aecb976a0fc32bc8658ef3e0a0c6b032a`
- 136/136 条初始化写入一致。
- 关键回读期望为 `0x118=0x0f`、`0x138=0x00`、`0x139=0x03`、
  `0x143=0x50`、`0x15a=0x01`、`0x16a=0x20`。
- continuous SYSREF 模拟控制路径未改变 GPIO。

## 证据路径与版本

- TCS：`../arch/lmk04828_stage32_min_delta_160_10m_cont_manual_clkin2.tcs`
- 寄存器导出：
  `../arch/lmk04828_stage32_min_delta_160_10m_cont_manual_clkin2_registers.txt`
- 审计脚本 SHA256：
  `33125b222223fa6ccd69ebd847d4b278682ca31c8f90066f8a14e9aa74689c20`
- 时钟控制器 SHA256：
  `64415f4c2b8a87137d061523334af8cab9076962c7c1a1e1469253d1bf5d79bc`
- 工作基线 Git SHA：`53f46bb73a2dca3d32af86c95b02561796c1d53c`
- 证据时间：`2026-07-26T01:13:16+08:00`

## 已知限制

32a 只证明导出物、写表和软件控制语义一致，不证明真实输出频率、占空比、相噪或
RFDC MTS。相关物理证据属于 32b/32c。

## 失败处置

停止science并保存LMK写表/回读证据，修复Stage 32 profile后重新执行离线校验；
不切换到范围外profile替代Stage 32验收。

## 下一阶段准入

本报告已 `PASS`，允许进入 `32b` 的 clock-only 写表。
