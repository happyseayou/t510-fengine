# Stage 36：ADC / DAC 分别重置对照

2026-09-09，用户授权继续。依据 [P/R结果](36_09_pr_experiment_results.md)。
目的：定位前轮重置触发的相关变化更关联ADC、DAC还是两者组合；不把变化降低直接判作改善。

## 固定条件与操作

沿用八路独立50Ω、DAC输出静音、板载TCXO、320MS/s、中心200MHz和current固件、数字尺度。
不修改RTL、Agent、接收器，不改接线。Stage板端helper调用已部署current控制库。

| 组 | 显式Reset | 后续流程 |
|---|---|---|
| ADC | 四个ADC tile | 共用production prepare |
| DAC | 四个DAC tile | 相同prepare |
| R | 四ADC+四DAC tile | 相同prepare，作为重置效应重复对照 |
| S | 无 | STOP/START |

prepare仍会设置ADC和DAC的MTS、mixer/NCO/QMC及PL输出；“只重置”限定显式tile Reset调用，
不表示另一侧寄存器完全不写，或无跨器件模拟耦合。三种重置均先开启SYSREF，保留LMK与PL。
禁止隐含clock recovery或额外tile reset。每次ADC MTS要求492，核心/增益/PLL/时钟SHA均核验。

## 完整队列

- 先做ADC、DAC、R各10秒短门禁，各自完整性、封存和独立复算通过才进入下一段。
- 再执行 `S ADC S DAC S R S DAC S R S ADC S R S ADC S DAC S`。
- 正式19段各100秒：三种干预各三次，十次相邻对照；有效1900秒，短门禁30秒排除在科学分析外。
- 每段间隔180秒，从上一次STOP返回到武装前；等待不计入接收器watchdog，随后立即START。
- 自动全量验签/独立复算、100秒复均值及相邻复相关差异、停流静音。预计110–125分钟。
- 全部步骤一次提交同一队列；任一步失败立即安全收尾，不重试或增加额外恢复。

## 证据和解释

保留各段操作前后MTS、完整Reset调用列表、时钟/尺度、温度、校准以及全28对×4096bin的100ms产品。
正式比较三个预定频点的复数归一化差异；原始全频留作后续检查。短门禁是条件准备，不参与正式比较。
对照继承前状态、非洗脱；三次轮换不等于完全随机化，温度和历史状态仍是混杂因素。
ADC组有变化不直接定责ADC转换核心；DAC组有变化也不等于已证明DAC通过某条路径串扰。
R组用于检查先前“重置可触发”是否本轮复现；若全部弱变化，应如实报告未复现。

## 离线验证

`t510_stage36_adc_dac_selftest.py`：选择侧Reset次数/通道、另一侧无显式Reset、
三组相同prepare、注入Reset失败后不执行prepare且停流静音、3短门禁+19正式段结构，PASS。
PR共同恢复/隐藏重置拒绝测试、原计时回归测试均PASS。
组名用ADC/DAC，避免旧ABC分析器对组名A的900秒虚拟分段特殊处理。

队列脚本：scripts/stage-36/t510_stage36_adc_dac_queue.py。
沿用已验证的短门禁和自动分析实现；current组件没有新部署。
