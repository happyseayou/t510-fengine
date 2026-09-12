# Stage 36：配置恢复与 RFDC 重置配对实验

用户授权继续，2026-09-09。依据 [调用链核查](36_07_rfdc_configuration_separation_audit.md)。

保持原八路独立50Ω、DAC静音、板载TCXO、320MS/s、中心200MHz、current bitstream与数字尺度。
本轮不更新 RTL、Agent、time_rx；Stage 专属板端脚本使用现有 current 控制库。

## 完整队列

1. P 短门禁10秒：不重置 RFDC，共用 prepare 恢复相同配置。
2. R 短门禁10秒：先重置八个 ADC/DAC tile，再执行同一个 prepare。
3. 各短门禁要求采集完整性、封存和独立数值复算通过，才进入后续。
4. 正式顺序 `S P S R S R S P S P S R S`，13段，每段100秒；P/R各三次，S七次。
5. 全部验签、独立复算、100秒复均值及相邻复相关差异，安全收尾。

短门禁是条件准备，不加入正式科学对比；正式有效1300秒，门禁20秒。
间隔沿用修正的180秒：上一次 STOP 返回至接收器武装前，武装后立即 START。
总耗时预计75–85分钟，包括门禁、间隔、封存与复算。所有步骤在同一队列，无阶段间确认。
任一失败立即停流静音并保存现场，不重试、不静默增加恢复步骤。

## 隔离措施

P/R共用配置对象重建、SYSREF开启和 prepare 调用，仅 R 显式调用 reset_all_rfdc_tiles。
prepare 要求 fresh_download=False、已有连接 core、force_clock_reconfigure=False、
require_clock_preserved=True。检查返回的 clock_recovery，若隐含重配时钟或额外重置则失败。
显式 Reset 次数必须为P=0、R=8；核验core、QMC/尺度、PLL、时钟SHA、ADC latency=492。
保留MTS epoch/offset、温度、校准、操作回读和原生全频100ms产品。

代码：t510_stage36_pr_queue.py；公共Stage实验帮助脚本 init_probe/init_transport/init_queue。
PR_SELFTEST 验证共同prepare参数、显式reset次数、隐含恢复拒绝、短门禁失败传播；
原有计时测试继续验证等待先于武装。离线全部PASS，不替代短硬件门禁。

## 解释范围

S为继承前一状态的停流对照，非洗脱；三个重复且非完全随机，不把样本或28对当独立实验。
P包括 MTS、mixer/NCO相位复位、QMC和PL路由恢复，不称为“仅mixer”。
P/R差异若重复出现，说明显式重置带来的状态重建有额外影响；仍不能单独定责校准或模拟部分。
只使用新的正式13段比较，不拼接旧队列、短门禁或历史科学数据。
无已知共同输入，不把相关降低等同于天文信号相干响应通过。
