# Stage 32h XFFT reset-gate candidate build

## 结论

本候选 bitstream 于 2026-07-27 01:59:18 +08:00 完成
`synth_1 -> impl_1 -> write_bitstream`。实现门禁通过：

- 目标器件：`xczu47dr-ffve1156-2-i`
- bitstream SHA256：
  `b92fff3cadc948867e22359280c82ca14bd5a2a0351fac7e1c51a88b9a6cf2ec`
- fully routed：`274688 / 274688`
- routing errors：`0`
- WNS/TNS：`+0.024 ns / 0.000 ns`
- setup failing endpoints：`0`
- WHS/THS：`+0.010 ns / 0.000 ns`
- hold failing endpoints：`0`
- DRC Error/Critical Warning：`0 / 0`
- Methodology Error/Critical Warning：`0 / 0`

DRC与Methodology报告中仅有既有Warning/Advisory。实现日志保留一条
`[Vivado 12-1790]` CMAC evaluation metadata警告；它不是本次XFFT复位修改引入
的实现错误。

## 候选修改

预约启动在目标PPS清空流水线后，可能等待到`first_sample0`才启用SPEC。该候选
在SPEC未启用期间保持realtime XFFT处于复位；SPEC启用后释放复位并发送既有XFFT
配置。LMK、RFDC、PFB系数、UDP格式、端口和控制寄存器接口均未改变。

## 构建前验证

- `tb_pfb_channelizer`：PASS
- `tb_station_sync_scheduler`：PASS
- `tb_t510_fengine_top_smoke`：PASS
- `tb_t510_fengine_board_top`：PASS
- Python unittest：`47 / 47 PASS`

关键文件SHA256：

| 文件 | SHA256 |
|---|---|
| `rtl/pfb_channelizer.sv` | `9c373c8aa69df17912a12d1452b3290162b88fc5b5589150bd4d34842528419a` |
| `sim/tb_pfb_channelizer.sv` | `1ae520f8ae1098430fc56ca89144ac27bd9d570d45215c4285749d9d06240f1d` |
| `tcl/stage32h_xfft_reset_gate_build_chain.tcl` | `14c1ef2ecbf0c0f8565ae72d3cc3030211ca7e9985c2a40d9557d25fd6fe756f` |

本报告只证明候选设计成功实现；是否修复预约启动问题必须由板端测试判定。
