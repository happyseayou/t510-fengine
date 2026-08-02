# Stage 33 仓库“只保留最新成果”清理记录

日期：2026-08-03（Asia/Shanghai）

## 范围与结论

本次清理直接作用于现有 `demo-ant.xpr`。Stage 33 是 Stage 32 当前成果的原位升级，
没有创建第二个 Vivado 工程，也不再保留 Stage 32 回滚包、旧 stage 发布树或清理前
Stage 33 候选。当前有效数据面仍是1024-bit science bus、160/320 MS/s选择器、
4-tap PFB、TIME/SPEC CMAC512、调度同步和 DAC DDS；Stage 33 只在其基础上增加
ADC/DAC `3.84 GS/s + 12x` RFDC 合同并收敛接口与命名。

本轮共删除 `5,006,585,873` byte（`4.663 GiB`）本地旧产物。删除完成后的首次
测量为：

- 仓库占用（不含 `.git`）：`3,513,393,878` byte，约 `3.4 GiB`；
- 不含 `reports/` 的仓库占用：`3,508,930,648` byte；
- `reports/`：约 `4.3 MiB`，共73个文件；
- `build/`：空目录；
- `reports/vivado/`：只保留本轮 Stage 33 长任务提交记录。

上述仓库总量是快照；Vivado长任务同时在更新 `demo-ant.runs/`，因此总占用会继续
变化。删除字节数、`reports/`文件数和空 `build/`结论不依赖该运行态。

## 保留项与身份

- `for_me.md` 内容未被本次清理修改，清理后 SHA-256 为
  `519b6c2fcc9ad1fbcc97a4867ddf73da0fbc5b3fb22374867dc81ee8140db859`。
- 当前仓库顶层 `overlay/` 尚未提升为 Stage 33；其中 bitstream SHA-256 仍为
  `47117c9e656cfd8345125ef0130eb91a5ec0868cef59931b40b957da29f31234`。
- 当前 RFDC XCI SHA-256 为
  `3bc3b81a2d73cd3b8e968e385804556cb203def6adc5ac3b3a09dbb58ede2908`。
- 当前 HWH SHA-256 为
  `b7706b3e7d62be147b1962487ff0144dcad2e2ea61d31fef27f31c65b69eaefd`。
- 正在运行的 Vivado 长任务使用 `demo-ant.runs/`；本轮未查询、轮询、取消或修改
  该任务及其运行目录。

## 清理前 Stage 33 基线

清理前候选仅用于确认清理没有有意改变 RFDC、端口、寄存器和数据包合同：

- bitstream SHA-256：
  `caebaa96c1a06f90d8db324dfe1681692b200bf6c74baac736f5fd044046a998`；
- WNS：`0.076 ns`；
- WHS：`0.009 ns`；
- RFDC artifact verifier：PASS。

按“只保留最新成果且不考虑回退”的最新决定，该候选的 `build`、DCP和详细 Vivado
报告已删除；这里只保留身份与时序摘要，不把它当作最终 Stage 33 发布证据，也不得
把它产生的 MTS/RF 结果写入最终 catalog。

## 已完成的实现收敛

- 删除全部 `T510_STAGE*` 编译分支，`CORE_VERSION` 无条件固定为
  `0x00010033`。
- 保留当前 ADC adapter、160/320 MS/s rate selector、4-tap PFB、TIME/SPEC
  CMAC512、scheduled sync、DAC DDS、UDP字节布局、寄存器地址、端口和
  `sample0` 语义。
- 删除停用的诊断/witness路径、旧 packetizer、synthetic top、debug FFT、
  full multi-channel FFT及其 testbench。
- 当前 XPR 源集收敛为23个 RTL文件、18个工程仿真文件、一个 RFDC BD、一个 CMAC
  XCI和一个单通道实时 XFFT XCI；设计 fileset 没有 stage define，仿真 fileset
  只保留 `T510_SIM_FFT_MODEL`。
- RFDC 由 `bd/t510_rfdc_bd.tcl` 确定性生成；当前合同为8个物理 ADC converter、
  16条 ADC R2C路径、8条 DAC C2R路径、3.84 GS/s、12x、80 MHz AXIS及既有端口
  宽度。

## 稳定命名迁移

| 已删除旧名称 | 当前名称 |
| --- | --- |
| `python/stage29.py`、`Stage29Config/Controller/Mode` | `python/t510_control.py`、`FEngineConfig/Controller/Mode` |
| `python/stage29_console.py` | `python/t510_console.py` |
| `00_stage29_fengine_production_control.ipynb` | `00_t510_fengine_control.ipynb` |
| `stage30_agent_client.py` | `t510_agent_client.py` |
| `stage29_host_validate.py` | `t510_host_validate.py` |
| `host_stage29_rx_tune.sh` | `host_t510_rx_tune.sh` |
| `stage31_multiboard_sync.py`、`stage31_phase_compare.py` | `t510_multiboard_sync.py`、`t510_phase_compare.py` |
| `stage32h1_external_rf_axis_gate.py` | `t510_rf_spectral_metrics.py` |
| `stage29_math.js`、`Stage29Math` | `t510_math.js`、`T510Math` |

仓库内客户端、测试、notebook、systemd配置和发布脚本均已直接迁移，不保留旧模块、
旧符号或旧路由的兼容壳。

## API、接收机与协议收敛

- Board Agent 只提供 `/api/v2/*`，旧 `/api/v1/*` 返回404。
- 当前字段统一为 `sample_rate_msps`、`selected_sample_rate_msps`、
  `detected_sample_rate_msps`、`rfdc_complex_sample_rate_hz` 和
  `mts_result_id`。
- Rust receiver 只接受当前 SPEC `16 blocks x 256 channels x 1 time`、
  `PFB taps>=4` 布局，CLI 使用 `--initial-sample-rate-msps`。
- UDP布局、端口、包率和 `sample0` 时间语义未改变。
- 原 `docs/time_udp_payload_v2.md` 已改名为
  `docs/t510_udp_payload_v2.md`，并按 RTL/Rust 实现完整记录公共头、TIME payload、
  SPEC `16 x 256 x 1` 分块、IQ16顺序、coverage和频率轴。
- `scripts/check_repository_hygiene.py` 检查活动源码和路径中的旧 stage编号、旧 REST
  路由、旧采样率字段和旧 receiver layout选项。

## 本轮实际删除清单

| 路径或类型 | 清理前约占用 | 处理结果 |
| --- | ---: | --- |
| `reports/stages/timing_debug_27e/` | 936 KiB | 整目录删除 |
| `reports/board/` | 1.7 GiB | Stage 20..32原始JSON/pcap/log/DCP全部删除；Stage 33脚本需要时重建 |
| `reports/vivado/`旧目录 | 1.1 GiB | 删除Stage 27j..32及清理前Stage 33 DCP/报告，只保留当前提交说明 |
| `build/`全部内容 | 2.0 GiB | Stage 31、Stage 32、rollback及清理前Stage 33候选全部删除 |
| `.xsim_batch/`、`.xsim_xfft_wrapper/` | 143 MiB | 删除 |
| `.Xil/` | 3.2 MiB | 删除 |
| 根目录 `*.jou`、`*.log` | 约3 MiB | 全部删除 |

这些被忽略的生成物和原始运行证据没有另做备份，无法从当前工作区本地恢复；已跟踪
源码仍可从 Git 历史恢复。`demo-ant.runs/`、`demo-ant.cache/`、`demo-ant.gen/` 和
`demo-ant.sim/` 属于当前工程或当前长任务，未在任务运行期间删除。两个 Rust
`target/` 当前也保留，避免无必要地重建全部依赖。

## 离线验证

清理版在提交长任务前已得到以下结果：

| 门禁 | 结果 |
| --- | --- |
| Python compile与单元测试 | PASS，84 tests |
| Board Agent Cargo tests | PASS，7 tests |
| Time receiver Cargo tests | PASS，37 tests |
| Rust格式检查 | PASS |
| Web数学测试 | PASS |
| 仓库卫生检查 | PASS |
| `git diff --check` | PASS |
| Vivado当前源集准备 | PASS |
| `validate_bd_design` | PASS |
| RFDC XCI/HWH合同检查 | PASS |
| 当前完整XSim回归 | PASS，18 testbenches |

XDC静态检查仍报告18个既有 QSFP GT pin `MISSING_IOSTANDARD` warning，没有 pin
冲突；最终以完成后的 routed DRC与timing为准。XSim同时修正了 CMAC pause
testbench 的假通过：测试会等待 XPM `glbl.GSR` 释放，batch runner也会把
`Error:`、`Fatal:`和`CHECK FAILED`视为硬失败。

## 当前长任务与后续门禁

清理版已向当前工程完整提交：

```tcl
reset_run synth_1
launch_runs synth_1 -jobs 8
launch_runs impl_1 -to_step write_bitstream -jobs 8
```

当前状态为 `FULL_CHAIN_SUBMITTED / RESULT_NOT_POLLED`。长任务完成后只检查一次；
要求 synthesis、implementation和write_bitstream全部成功，设计 fully routed，
WNS/WHS均不小于0，DRC通过，并再次核对 RFDC XCI/HWH合同。通过后才导出新的唯一
Stage 33成品并记录最终 bitstream SHA。

MTS discovery/fixed、200/960/1760 MHz与1.90 GHz RF点、DAC纯度、生产矩阵、
soak、冷启动和热稳定性门禁仍待最终 SHA 绑定。顶层 `overlay/`、release catalog和
`latest`在物理板门禁通过前均不提升。
