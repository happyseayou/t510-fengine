# Stage 32h RFDC ready-low数字故障门禁

## 结论

`PASS`

现有生产RTL已经实现RFDC可见故障保护，不需要修改RTL或重新生成bitstream。此前
缺口是`tb_station_sync_scheduler`把`rfdc_ready`常量绑为1，没有执行活动流故障
分支。本次只修改testbench并完成目标XSim。

## 信号语义

| 故障来源 | 板顶层信号路径 | 调度器结果 |
|---|---|---|
| ADC science链失去有效数据 | `all_adc_valid -> rfdc_ready_in -> rfdc_ready` | `RFDC_NOT_READY / code 6` |
| DAC/数据参考链未ready | `all_dac_ready -> ref_chain_locked -> ref_lock_in` | `REF_UNLOCKED / code 5` |
| 外部10 MHz丢失但LMK holdover | PL不可见；PS读取LMK `0x182/0x183` | PS watchdog STOP并锁存`LMK_PLL1_UNLOCKED` |
| PPS丢失 | `pps_recent` | `PPS_NOT_RECENT / code 7` |

Stage 32的TIME/SPEC科学数据来自ADC，因此`rfdc_ready`的发布语义是ADC science链
ready。DAC是校准/自环激励源，不是外部科学输入；不能要求一次不影响
`all_adc_valid`的DAC驱动维护调用必然停止TIME/SPEC。

## RTL审计

冻结bitstream对应源码没有改动：

- `rtl/t510_fengine_board_top.sv`：
  `rfdc_ready_in(all_adc_valid)`；
- `rtl/t510_fengine_top.sv`：
  Stage 31/32的`streaming`输出还组合门控`rfdc_ready_in`，并把该信号送入
  `station_sync_scheduler`；
- `rtl/station_sync_scheduler.sv`：
  从ARMED到STREAMING任一状态观察到`!rfdc_ready`，下一拍清除
  `armed/streaming`、进入`ST_ERROR`并锁存`ERR_RFDC_NOT_READY=6`。

源码SHA256：

| 文件 | SHA256 |
|---|---|
| `rtl/station_sync_scheduler.sv` | `d82528f453e1898ded2925369d2bf334bae4c4a41d1051bff133aa176bf33740` |
| `rtl/t510_fengine_top.sv` | `d8b1162c20b9c9c6dfb859c8e49b3f7bacbbd5181f8c215925adb6c66cc84f89` |
| `rtl/t510_fengine_board_top.sv` | `263316218ec56ff30491d5f0503091c21c93ca49a568ebc1ab1ef217efaf5624` |

## 新增仿真覆盖

`sim/tb_station_sync_scheduler.sv`在预约流已经进入STREAMING并记录首个TIME/SPEC
sample0后执行：

1. 拉低`rfdc_ready`；
2. 下一拍要求`state=ST_ERROR(6)`；
3. 要求`error_code=RFDC_NOT_READY(6)`；
4. 要求`armed=0`、`streaming=0`；
5. 要求status同时报告RFDC not-ready和latched error；
6. 恢复`rfdc_ready=1`后，要求状态仍为ERROR且不得自动重启；
7. 只有显式ABORT才允许回到IDLE并清除错误码。

testbench SHA256：
`0258cbafc1e17b3793f34e82c69f4915edbd794278aceccdf48915f88d14e1c5`。

## 执行

命令：

```bash
T510_XSIM_WORK_DIR=/home/astrolab/demo-ant/.xsim_batch/stage32h_rfdc_ready_fault_gate \
  scripts/run_xsim_batch.sh tb_station_sync_scheduler
```

环境：

- Vivado Simulator `2022.2`；
- `T510_STAGE32`已由batch脚本定义；
- 只运行XSim，没有启动综合、实现、route或write_bitstream。

结果：

```text
[350000] PASS: tb_station_sync_scheduler
INFO: all XSim batch testbenches passed
```

归档日志：
`tb_station_sync_scheduler_xsim.log`，SHA256
`070f136a32061119ebb9c324699c89d307b41474a09343acdca62feccf28c9e5`。

## 板端Reset测试的重新分类

`XRFdc_Reset()`和`ShutDown()/StartUp()`是PS驱动维护调用，不是保证拉低
`all_adc_valid`的物理故障源。此前板端证据已经证明这些调用期间
`rfdc_ready`始终为true，因此它们没有触发调度器是符合信号合同的，不能再判成
“保护逻辑失败”，也不能冒充ready-low故障PASS。

Stage 32的完成定义改为：

- 对PL可观察的ADC/RFDC validity loss：必须立即数字停流并锁存code 6，本报告
  XSim已PASS；
- 对外部10 MHz和PPS：分别由PS watchdog和PL scheduler的物理断线证据闭合；
- 驱动Reset只作为维护恢复测试，必须随后fresh CONFIGURE/MTS并通过主机恢复门禁；
- 真正模拟/RFDC器件物理失效没有安全可重复的实验室注入手段，作为硬件破坏性
  测试边界记录，不要求新增RTL fault-injection或新bitstream。
