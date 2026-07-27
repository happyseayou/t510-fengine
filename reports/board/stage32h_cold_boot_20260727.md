# Stage 32h真实整板冷启动门禁

## 结论

`PASS`

2026-07-27由用户关闭T510整板主电源、等待约10秒后重新上电。10 MHz、PPS、
USB和网络连接保持不变。本次不是Linux warm reboot，也没有用USB重新枚举冒充
掉电启动。

## 启动身份与服务自启

- 新Linux boot ID：
  `089b6ea6-eed4-4ad7-8d5b-7af28b84f466`；
- 首次读取时uptime约72秒；
- Board Agent版本：`0.3.2`；
- `t510-agent.service`：`enabled / active / running`，本次boot进入active时间
  `2026-07-27 06:17:51 UTC`；
- `t510-ref-watchdog.service`：`enabled / active / running`，本次boot进入active
  时间`2026-07-27 06:17:41 UTC`。

两个服务均由systemd自动启动，没有人工执行`systemctl start`。

## 配置前fail-closed

冷启动后、调用CONFIGURE前：

- `/health/live`返回`live=true`；
- `/health/ready`返回`ready=true, hardware_accessed=false`；
- `/api/v1/status`返回HTTP 409、错误码`PL_NOT_CONFIGURED`；
- watchdog为`WAITING_FOR_PL`，`last_error=RuntimeError:FPGA_MANAGER_UNKNOWN`；
- watchdog硬件镜像为`generation=0`、`selected=false`、`streaming=false`；
- 没有沿用掉电前的MTS结果或自动放行science数据。

因此“Agent可提供控制服务”和“PL已配置可打流”被正确区分，冷启动默认状态为
fail-closed。

## Fresh CONFIGURE/MTS

执行：

```bash
python3 scripts/stage30_agent_client.py configure \
  config/stage32/configure_320_time_only.example.json
```

结果：

- CONFIGURE耗时`15365.082 ms`；
- bitstream SHA256：
  `439080046408267493a031efa1d097fcd3c2f818850ee9eac1925ae95d6b094c`；
- `CORE_VERSION=0x00010032`；
- LMK profile为`stage32_160_10m_cont_manual_clkin2`；
- manual CLKin2、external 10 MHz、continuous SYSREF；
- PLL1/PLL2均锁定；
- ADC active measured latency为`[230, 230, 230, 230]`，target为`230`；
- DAC active measured latency为`[335, 335, 335, 335]`，target为`336`；
- RFDC ready、PPS recent、QSFP physical health和pipeline flush均正常；
- CONFIGURE完成后watchdog自动从`CONFIGURE_PAUSE`恢复到健康`IDLE`。

## 20秒320 MS/s TIME_ONLY恢复门禁

执行：

```bash
python3 scripts/stage32_agent_host_gate.py \
  --bandwidth-mhz 320 \
  --mode time_only \
  --seconds 20 \
  --output \
  reports/board/stage32h_cold_boot_recovery_320_time_only_20s_20260727.json
```

结果：

- 分类：`STAGE32_320MSPS_TIME_ONLY_BOARD_HOST_PASS`；
- 主机TIME包：`24,999,888`；
- 包率：`1,249,994.4 pps`；
- UDP payload速率：`83,199.627264 Mbit/s`；
- 8路TIME sequence/frame/sample0 gap均为0；
- parse、kernel、ring、worker-ring和application drop均为0；
- 板端20秒测量窗口内RFDC/science/TIME/SPEC/TX/route drop增量均为0；
- QSFP物理状态健康；
- 测试结束自动STOP，`streaming=false`、`stream_accepting=false`、
  `flush_clean=true`。

START到稳态快照之间出现`rfdc_dropped=19`的启动瞬态；20秒正式测量窗口中该计数
保持不变。证据不隐藏该值，最终30分钟soak继续观察其是否在稳态增长。

接收机报告了一项非T510白名单流量的NIC steering warning：
`NIC_RX_STEER_MISSED_OUTSIDE_T510_WHITELIST=13`。它没有对应T510 parse/drop/gap，
不影响本门禁结论。

## 证据

| 文件 | SHA256 |
|---|---|
| `stage32h_cold_boot_recovery_320_time_only_20s_20260727.json` | `3895c4fde823e739178f56769d7debbf4bb2598675bffe928156913bf6c51757` |
| `stage32h_cold_boot_recovery_320_time_only_20s_20260727_host.json` | `095dd23579fdf5357499da2569b3d512babbf4d81a62b5e1d1bd9ad884e5564d` |

## 准入结论

真正整板掉电、服务自启、配置前fail-closed、fresh CONFIGURE/MTS和主机无损恢复
全部通过。`32h-p2`可改为`PASS`。下一步只剩排在最后的30分钟针对性soak。
