# Stage 32h2 DAC DDS I/Q方向第一轮构建摘要

> 本bit在完整fresh CONFIGURE后的最终160/320物理方向矩阵中通过，现为32h2候选
> 发布产物。此前旧初始化会话中的镜像异常由direct raw preview定位并在完整
> bit download、RFDC init/MTS后消失；详见阶段报告。`Data_Type=0`是正确的Real
> 模拟输出配置，并与`Mixer_Mode=I/Q->Real`共同形成PL复数输入合同。

- 构建完成：`2026-08-01 21:05:49 +08:00`
- Vivado：`2022.2`
- 器件：`xczu47dr-ffve1156-2-i`
- 顶层：`t510_fengine_board_top`
- `CORE_VERSION`：`0x00010032`
- 构建链：`synth_1 -> impl_1 -> write_bitstream`
- `synth_1`：`synth_design Complete!`，100%
- `impl_1`：`write_bitstream Complete!`，100%，`NEEDS_REFRESH=0`

## 受控修改

本候选只把PL DAC DDS从`I=sin(theta), Q=cos(theta)`改为标准正向复数
`I=cos(theta), Q=sin(theta)`。128-bit AXIS仍为
`{Q3,I3,Q2,I2,Q1,I1,Q0,I0}`；LMK、SYSREF、RFDC、MTS、PFB、UDP、REST和
`CORE_VERSION`均未修改。

| 源文件 | SHA256 |
|---|---|
| `rtl/t510_dac_loopback_source.sv` | `bac92e0d322510b2bc592a7c7092460f3ab470bb713860d01fb87322d64dd31e` |
| `sim/tb_t510_dac_loopback_source.sv` | `9e1fe8280a66096e563166c45a7210c81c55ff942280f97f29ec00e286cd011e` |
| `tests/test_stage32h2_dac_iq_direction.py` | `9973296306feb97418320da9f3700f866bb3ac2898ca1893245020df533ce7fc` |
| `tcl/stage32h2_dac_iq_direction_build_chain.tcl` | `f416373f7c4d77427ca13272477a7c4a54b69f4471212eb2883c8b9c8c96b417` |

## 实现门禁

- Design State：Fully Routed。
- routable nets：`274786 / 274786`。
- routing errors：`0`。
- WNS/TNS：`+0.115 ns / 0.000 ns`。
- WHS/THS：`+0.010 ns / 0.000 ns`。
- setup/hold failing endpoints：`0 / 0`。
- Routed DRC：无Error或Critical Warning violation。
- Methodology：无Error或Critical Warning violation。
- Bitgen：成功。

实现日志保留一条既有的`[Vivado 12-1790]` CMAC evaluation-license metadata
Critical Warning。它不属于DRC/Methodology violation，也不是本次DDS修改引入；
正式产品部署仍需使用合适的IP许可证。

## Artifact标识

| Artifact | SHA256 |
|---|---|
| `demo-ant.runs/impl_1/t510_fengine_board_top.bit` | `47117c9e656cfd8345125ef0130eb91a5ec0868cef59931b40b957da29f31234` |
| `overlay/t510_fengine.bit` | `47117c9e656cfd8345125ef0130eb91a5ec0868cef59931b40b957da29f31234` |
| `overlay/t510_fengine.hwh` | `2a341b6a959ed9483b861c15eaac1d5fa708554dde6cded96613b52c0c96dca5` |
| `overlay/t510_fengine.tcl` | `0804b781a7368a3598771f7ae304f5a9ccecc4807b66a240a7747ea3bde63c6e` |
| `overlay/t510_fengine.manifest.txt` | `e7b8be99a88b41a4412f60b2600bf854a2c556b35db5809998c8a3bf5fd10b4b` |

bitstream与实现产物逐字节一致；HWH、BD Tcl和manifest SHA未变，符合本次没有修改
Block Design或RFDC配置的预期。

## 证据文件

- `synthesis_run.log`
- `implementation_run.log`
- `route_status.rpt`
- `timing_summary.rpt`
- `drc.rpt`
- `methodology.rpt`
- `utilization_placed.rpt`
- `clock_utilization.rpt`
- `prebuild_verification.md`

离线实现和32h2真实DAC频率方向均已闭合；频谱纯度仍由Stage 32h3判定。

## 构建后诊断同步

新bit上板后，把Python DAC witness相位诊断从旧的负旋转基函数同步到标准正旋转
约定。该修改不进入FPGA实时数据面，不改变本摘要对应的bit：

| 文件 | SHA256 |
|---|---|
| `python/t510_fengine.py` | `8b46dd1f5055e449bb87efeae1f11db075e79961a772625c4d50d08a761117d9` |
| `tests/test_stage32h2_dac_iq_direction.py` | `e6f7934dbc3462d4576292d641020315ca32f9abe996f3571a56580e1fc7f91f` |

目标3项及全量65项Python测试PASS。生产define会裁剪板内DAC AXIS witness，因此不为
诊断重新打开该逻辑或重跑bit，最终方向以物理RF落点为准。
