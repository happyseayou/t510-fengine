# Stage 32b：LMK 160 MHz远程clock-only功能门禁

## 状态

`PASS`

## 目标

在science停止的安全状态下写入Stage 32 LMK profile，通过锁定和回读验证CLKin2、
PLL、160 MHz divider配置和continuous 10 MHz SYSREF配置，为32c完整功能时钟验证
放行。

## 前置条件

- Stage 32a `PASS`。
- 外部10 MHz连接到CLKin2。
- science pipeline已STOP并完成flush。

## 远程门禁

- 10次Stage 32 profile reload。
- PLL1/PLL2全部锁定，关键寄存器回读一致。
- profile ID、manual CLKin2、continuous SYSREF和OSCout-off配置一致。
- 只接受`stage32_160`，不包含其他profile或bitstream切换路径。
- 物理频率/占空比不在本远程门禁中宣称，由32c的Clock Wizard、RFDC状态和MTS
  重复性补强功能证据。

## 非目标

本步骤不声明RFDC、MTS、DAC/ADC、UDP或模拟波形质量通过。

## 实际改动

- `scripts/pynq_stage32_clock_only.py` 只允许Stage 32 profile；它只写LMK、读锁定与
  关键寄存器，不下载overlay、不初始化RFDC、不启动UDP。
- 执行前已停止science pipeline；确认 `stream_accepting=false`、
  `flush_clean=true`。

## 测试命令与结果

板卡：`192.168.100.117`，时间：`2026-07-26T01:12..01:13+08:00`。

```bash
sudo python3 scripts/pynq_stage32_clock_only.py \
  --profile stage32_160 --reloads 10
```

- Stage 32 profile reload `10/10` PASS。
- 每次均在第1次轮询得到 `PLL1=1`、`PLL2=1`。
- 每次profile ID、continuous SYSREF、manual CLKin2、`SEL1:SEL0=10`和六个关键
  寄存器回读一致。
- pipeline保持clean STOP，没有在不匹配的bitstream上启动数据面。

## 证据路径与版本

- `../board/stage32b_lmk160_reload_20260726.json`
- 工作基线Git SHA：`53f46bb73a2dca3d32af86c95b02561796c1d53c`
- 当前clock-only入口：`scripts/pynq_stage32_clock_only.py`

## 远程边界和USB调查

- 工作站检测到Digilent Adept FT2232，序列号 `210279113854`，对应
  `/dev/ttyUSB0`和`/dev/ttyUSB1`。
- 当前用户属于`dialout`组；`/dev/ttyUSB1`由持续运行的`picocom`记录器占用，
  日志已确认它是可观察T510 Linux启动过程的UART路径。后续测试保留该记录器，
  不抢占端口。
- Vivado `hw_server`已运行，但只读查询结果为`0`个hardware target、`0`个device，
  因而当前不能依赖USB JTAG下载或恢复。
- 板卡 `192.168.100.117` 网络可达，既有Board Agent、FPGA manager和板端JSON
  已形成32b..32f功能证据。
- 该USB连接不能证明具备主板电源切断能力；USB重新枚举不计作冷启动。
- 因无法物理接触板卡，真正断电冷启动、160 MHz波形/占空比、SYSREF波形和OSCout
  噪声底列为 `REMOTE-EVID-001` 待补项，不阻止32c..32h。
- 本步骤的 `PASS` 只声明LMK写表、锁定和回读，不声明MTS或模拟波形质量。

当前远程恢复顺序固定为：

```text
停止并flush science
-> 重新写入stage32_160
-> 验证LMK lock/readback
-> 重新加载匹配的Stage 32 bitstream
-> RFDC init/fixed MTS
-> 验证健康状态后再启动science
```

其中LMK reload、RFDC reset和overlay reload的重复性证据已分别由32b/32c取得；
Linux warm reboot及UART启动日志纳入32h。该策略不包含范围外版本回退。

将来可物理接触板卡时使用
`../board/stage32b_physical_gate_template.md` 补充波形记录；补测结果不追溯阻止
当前功能开发。

## 失败处置

停止science并保存失败回读；修复Stage 32 LMK配置后重新执行10次reload，不切换
到范围外profile。

## 下一阶段准入

本远程clock-only门禁已通过，允许把Stage 32 bitstream下载到板卡并执行RFDC/MTS。
完整时钟链是否可用由32c的Clock Wizard、RFDC状态和MTS重复性最终判断。
