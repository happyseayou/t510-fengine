# Stage 32h PPS recent guard candidate build

## 结论

本候选 bitstream 于 2026-07-27 03:37:52 +08:00 完成
`synth_1 -> impl_1 -> write_bitstream`。实现门禁通过：

- 目标器件：`xczu47dr-ffve1156-2-i`
- bitstream SHA256：
  `439080046408267493a031efa1d097fcd3c2f818850ee9eac1925ae95d6b094c`
- fully routed：`274680 / 274680`
- routing errors：`0`
- WNS/TNS：`+0.081 ns / 0.000 ns`
- setup failing endpoints：`0`
- WHS/THS：`+0.009 ns / 0.000 ns`
- hold failing endpoints：`0`
- DRC Error/Critical Warning：`0 / 0`
- Methodology Error/Critical Warning：`0 / 0`

DRC与Methodology报告中仅有Warning/Advisory。实现日志保留一条
`[Vivado 12-1790]` CMAC evaluation metadata警告；它不是本次PPS保护窗口修改
引入的实现错误。

## 候选修改

Stage 32的ADC AXIS时钟为80 MHz。原设计把`pps_recent`超时固定为
`80,000,000`个周期，恰好等于1.000秒。外部1 PPS与PL时钟之间存在相位和微小
频率偏差时，健康PPS到来前可能短暂超时，导致预约启动的数据门控掉电并截断一个
正在处理的PFB frame。

本候选只把Stage 32的超时改为`100,000,000`个周期，即1.25秒：

- 正常相邻PPS获得25%保护余量；
- 若确实丢失一个PPS，预约流会在预计边沿后约250 ms停止；
- LMK、RFDC、PFB算法、UDP格式、端口和控制寄存器接口均未改变。

## 构建与源码对应关系

- 修改源码时间：2026-07-27 02:32:15 +08:00
- 综合启动时间：2026-07-27 02:36:29 +08:00
- `rtl/t510_fengine_board_top.sv` SHA256：
  `263316218ec56ff30491d5f0503091c21c93ca49a568ebc1ab1ef217efaf5624`
- `tcl/stage32h_pps_recent_guard_build_chain.tcl` SHA256：
  `702fa38d108b44949ae2f9d08b1a993f3a2bd1442333659ce7629eccda7922b5`

Vivado综合日志明确从当前工作区的
`rtl/t510_fengine_board_top.sv`读取顶层，且综合在源码修改之后启动。

## 构建前验证

- `tb_pfb_channelizer`：PASS
- `tb_station_sync_scheduler`：PASS
- `tb_t510_fengine_top_smoke`：PASS
- `tb_t510_fengine_board_top`：PASS
- `git diff --check`：PASS

本报告只证明候选设计完成实现闭合；PPS边界问题是否修复仍以板端定时启动和远端
Rust接收机无gap复测为准。
