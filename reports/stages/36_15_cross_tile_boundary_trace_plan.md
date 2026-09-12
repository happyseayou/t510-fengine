# Stage 36：跨tile变化的有界追查与主线返回条件

2026-09-10。用户授权追查，并要求随后绕回主线。依据[单tile结果](36_14_single_tile_reset_results.md)。
本轮只增加Stage实验观察，不改current组件/RTL、不手工写校准系数、不改变接线。

## 问题与有界设计

前轮T0第一次之后，未显式Reset的ADC2/3相关从5.41%降到0.22%，其自身OCB2未变。
本轮复核T0→2/3，并比较共同prepare、MTS的作用。沿用八路50Ω、DAC静音、板载TCXO、320MS/s、中心200MHz及原尺度。
物理接线条件为继承，软件无法独立核验。

T0：仅Reset ADC tile0，再共同prepare；P：相同prepare，无Reset；M：仅MTS；S：普通停启。
先T0/M/P各10秒短门禁，独立验证后进入19段100秒、100ms积分正式队列：
`S T0 S M S P S M S P S T0 S P S T0 S M S`。
三种干预各三次、十次S，固定180秒STOP到下次接收器武装前间隔。完整队列一次提交，失败停流静音并保留现场。
预计110–130分钟，包含独立复算、全频比较和边界摘要。短门禁用于资格验证，不进入正式科学比较。

不额外Reset来寻找某种起始相关。上一轮ADC2/3已经较低；若本轮一直低，不能用未观察到大幅下降否定历史跨组事件。

## 新增观察，不更改标准操作顺序

Stage helper给原操作增加只读observer，MTS方法仅在该Python进程内临时包装，最终恢复原方法。
T0/P记录：操作前、SYSREF开启后且Reset前、Reset后（P为无Reset对照）、MTS前、MTS后、prepare完成后。
M记录：操作前、MTS前、MTS后。
每个边界记录开始/结束时间、全八路四组校准原始系数、温度、RFDC tile电源/启动状态、配置读回和PL状态。
所有快照必须停流；不把Reset后但未MTS的读回当作科学采集或有效同步证明。

每条记录写入板端独立JSONL并fsync；读取失败同样写入失败边界后退出，保留此前记录。
成功调用完整记录同时写入GB10对应phase证据。快照会增加少量停流时间，不能声称观察绝对无扰动；共同P记录用于对照。
原有核心/尺度/时钟/固定MTS门禁仍生效，禁止隐含时钟恢复或额外Reset。observer不调用校准写入API。

## 自动产物与解释

保留28对×4096bin原生100ms数据。全频加权复相关按涉及tile0的13对和其他15对预分组；P/M使用相同分组。
关注ADC2/3，但不只挑这一对，默认三频点和完整频带均保留。
`boundary_changes.json`报告每个操作边界之间各校准bank哪些ADC读回发生变化；不直接对打包系数作数值差值。
寄存器快照只能定位已记录状态变化，不能证明可见度跳变的精确时刻发生在Reset或MTS。

## 必须绕回的主线

1. 本轮完成后先回答跨组现象是否复现、是否关联T0而非P/M及起始状态是否具备观察机会。
2. 无论复现与否，不自动续加重置轮次；将证据带回“校准系数是否参与相关结构”的机制问题。
3. 如证据支持，再设计有同值写回对照的系数诊断；不能凭OCB2变化直接写入或固化系数。
4. 最终回到已知共同输入的相干响应验证：降低50Ω假相关不能替代真实信号幅相重复性验收。

队列自动生成 `RETURN_TO_MAIN_QUESTION.md`，确保跨会话恢复仍能看到上述返回条件。
本队列不包含后续系数写回或新接线实验。

## 实现与离线验证

入口 `scripts/stage-36/t510_stage36_trace_queue.py`；板端 `t510_stage36_trace_probe.py`；边界分析 `t510_stage36_trace_analyze.py`。
`trace_selftest`验证三个操作的精确Reset/prepare/MTS调用、边界顺序、失败记录落盘、observer恢复与安全收尾。
原tile/PR/MTS及watchdog计时测试均PASS。
执行树及板端两个helper的SHA在预检中核对；已完成的历史执行树保持不变。

队列：`stage36-trace-20260910`；GB10 unit：`t510-stage36-trace-20260910.service`。
证据：`/var/lib/t510/measurements/stage36-trace-20260910-queue/`。
执行树：`/home/astrolab/.cache/t510/stage36-trace-20260910/repo`。
板端：`/home/xilinx/t510-stage36-trace/`，失败时检查其 `traces/`。
本地提交记录：`build/trace-20260910/`。
