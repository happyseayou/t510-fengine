# Stage 31 单板 Agent、同步事务与 DAC-ADC 自环 Smoke

## 结论

2026-07-18 已把 Stage 31 production bitstream、Python helper 和 Rust Board Agent 发布到 T510 `192.168.100.117`，并完成一次真实 fresh download、PREPARE/ARM/PPS commit 和两次本板 DAC-ADC signal capture。单板数字事务和现有自环链路通过；该结果不等价于多板共同输入相位验收。

## 发布事实

- Agent release：`/opt/t510-agent/releases/stage31-8ab17ebf0b82-20260717160628`
- Agent version：`0.2.0`
- catalog：`fengine-0x00010031`
- core version：`0x00010031`
- board ID：`1`
- bitstream SHA256：`3696845d30dc471f572904b7039aa231bc766a21be05de7796d53704f8d08eec`
- fresh configure：`100 MHz TIME_SPEC`、AA100 active、24 endpoints 回读一致，耗时 `12531.293 ms`
- Jupyter server/kernel PID 在部署前后保持 `878/115849`，Agent 和 Jupyter service 均为 active；Agent 最近 15 分钟无 warning journal。
- 原 `/etc/t510-agent/config.json` 已备份；Stage 31 配置把单次硬件操作 timeout 从 10 秒增加到 30 秒。

## Stage 31 同步事务

单板 coordinator 使用 generation 1、lead 30 PPS 执行 PREPARE 后 ARM：

- ARM 快照：current PPS `185`，target PPS `199`，state `2/ARMED`，MTS result ID `2400283333` 有效，error code `0`。
- 最终提交：`actual_commit_pps_count=199`，与 target 完全一致。
- epoch：`epoch_valid=true`，`actual_epoch_raw_sample0=48764337788`。
- 100 MHz AA 对齐规则：`sample0 mod 8 = 4`，请求 `first_sample0=32788`。
- 首包：`actual_first_time_sample0=32788`、`actual_first_spec_sample0=32788`，两者均严格命中声明值。
- 最终 state `5/STREAMING`，generation、TAI、observation tag、signal-chain tag、schedule tag 和 MTS ID 均保持冻结；reference/PPS/RFDC 均 ready，error code `0`。
- 在 current PPS `414` 的复读中，TIME `103375009`、SPEC `103374928`、TX sent `206751207`；RFDC/science/TIME/SPEC/TX drop、route miss 和 route error 全部为 0。

真实板证明无状态 PYNQ helper 每次进程启动/import 需要数秒。原协调脚本的“两次相隔 50 ms 且 local PPS count 不变”不适用于该 Agent 架构，且 lead 5 PPS 不足以覆盖 status→PREPARE→ARM。因此脚本已改为对所有板并行读取一次内部原子快照，默认 lead 30 PPS，HTTP timeout 45 秒；Agent operation timeout 改为 30 秒。

## DAC-ADC 自环信号

通过 Agent 原子更新八路 DAC：`60.010 MHz`、幅度请求 `6%`、phase `0°`、enable mask `0xff`，回读 amplitude code `492`、实际 `6.005859375%`、DAC phase epoch `2`。

两次独立 1024-sample preview 均返回历史命名的 `STAGE29_SIGNAL_AUDIT_PASS`，实际 core 均为 Stage 31 `0x00010031`：

- 第一次八路 RF peak 为 `60.010040..60.010477 MHz`，SNR `50.73..52.61 dB`，全部 valid、无 clipping。
- 第二次八路 RF peak 为 `60.009751..60.010172 MHz`，SNR `51.19..52.03 dB`，全部 valid、无 clipping。
- AA100 已 active/primed；4-tap PFB、8-lane XFFT 配置完成；overflow、backpressure、XFFT event/tlast、drop 和 route error 为 0。

原始 JSON：

- `stage31_single_board_dac_adc_signal_audit_20260718.json`
- `stage31_single_board_dac_adc_signal_audit_repeat_20260718.json`

第一次 CLI audit 因 SSH/sudo 环境未设置 `XILINX_XRT=/usr`，在 PYNQ 打开设备前退出，没有访问或修改 FPGA；使用与 systemd Agent 相同的 XRT 环境后两次均通过。

## 验收边界

- 本次证明 Stage 31 Agent/API/MMIO、PPS 精确提交、epoch reset、首 TIME/SPEC sample0、连续发包和当前八路本板 DAC-ADC tone 路径可用。
- 两次 capture 的显示相位不用于 cold/warm phase repeatability 判定：capture sample0 不同，短窗频率估计误差会被大 sample0 相位外推放大。正式相位验收必须保存复数 waveform/F-engine voltage，并按共同 generation/sample0 做相关或 cross-spectrum。
- 没有共同输入功分，因此不声明跨板 ADC/F-engine 相位一致，不生成跨板 delay calibration 或 complex gain。
