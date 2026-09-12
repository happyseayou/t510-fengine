# Stage 36：共同单音输入的DSA准备

2026-09-11。用户确认SSA已设置、TG关闭；接线按上一轮指导为SSA TG OUTPUT→
XQY-PS2-DC/3-SE IN，OUT1/OUT2→ADC0/ADC2，其余六路独立50Ω。实体端口及实际输出电平未由软件独立测量。
请求频率130.078125MHz、Zero Span、TG -20dBm；无外部衰减器。外部10MHz/PPS不变更，继续板载TCXO。

## 已完成，不等于科学采集通过

- 核对前一trace队列completed/PASS，板端停流、DAC静音，接收器time/autocorrelation/crosscorrelation均无活动任务。
- 读取八路DSA，初始均Attenuation=0、DisableRTS=0。
- 仅ADC0和ADC2写入Attenuation=20dB、DisableRTS=1；其他六路原样。
- 一次TG关闭条件下T0恢复验证：先应用DSA→只Reset ADC tile0→记录原始回读→重新应用目标DSA→共同prepare/MTS→回读。
- **此次实际Reset后两路仍保持20dB**；不能据此承诺所有重启/重载路径都会保持，因此后续各阶段仍明确应用和核验。
- MTS ADC延迟[492]*4、offset[9]*4，固定数字尺度与时钟身份检查通过。
- 新进程再次回读：[20,0,20,0,0,0,0,0]dB，ADC0/2的DisableRTS=1，停流、DAC静音，helper SHA一致。

当前没有开启TG、没有启动科学采集，没有修改RTL或部署current组件。
DSA降低转换前信号幅度，但不能代替ADC连接器过功率保护；沿用TG最低输出，不自行提高电平。
驱动依据：[AMD XRFdc_SetDSA](https://docs.amd.com/r/en-US/pg269-rf-data-converter/XRFdc_SetDSA-Gen-3/DFE)。

## 后续接续约束

1. 用户开启TG后，先10秒短采确认ADC0/2主音、码值、FIR/FFT/RFDC错误及数据完整性，再考虑60秒100ms积分共同信号测试。
2. 该物理状态不是八路独立50Ω，不直接套用此前噪声队列的physical_input/interpretation元数据。
3. 数据必须记录TG频率/请求电平、功分器型号、连接ADC、每路实际DSA及原数字尺度。
4. DSA固定；任何Reset或配置后都重新核验。需要Reset时先要求TG关闭，不在TG已开情况下直接调用本准备helper。
5. TG关闭但功分器仍连接的ADC0/2不是两个独立50Ω负载，不能把它们作为原噪声基线。
6. 这一步回到已知共同信号相干响应；校准系数因果诊断仍是后续候选，没有启动手工系数写回。

## 实现和证据

脚本：`scripts/stage-36/t510_stage36_tg_dsa_probe.py`，复用原受锁保护、停流和时钟保持的P/T0操作。
本轮只执行一次T0。observer仅在初始和Reset后应用DSA，其余边界只读核验；失败立即停止，保留已写入状态和日志，不自动降回0dB。
测试：`t510_stage36_tg_dsa_selftest.py` PASS，含选择通道、模拟Reset清除后的重新应用、读回、禁流中写入及失败清理。
实际板端Reset是否清除由现场日志决定，不能将模拟清除当成真实观测。

本地：`build/tg-dsa-20260911/{board-before,receiver-before,dsa-before,dsa-reset-qualification,dsa-final}.json`。
板端helper：`/home/xilinx/t510-stage36-tg/t510_stage36_tg_dsa_probe.py`，持久journal在同目录`dsa-journals/`。
GB10转发：`/home/astrolab/.cache/t510/stage36-tg-20260911/`。
当前等待用户打开TG后的短采接续。
