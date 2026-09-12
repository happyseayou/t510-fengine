# Stage 36：单 ADC tile 重置空间对照

2026-09-10。用户批准执行[研究方案](36_12_adc_initialization_research_plan.md)第一步。
只改Stage实验脚本，不写校准系数，不发布current组件，不改RTL或接线。
沿用八路独立50Ω、DAC静音、板载TCXO、320MS/s、中心200MHz及原数字尺度。
接线为继承的实验条件，软件不能独立核验实体连接。

## 操作和顺序

- T0：仅ADC tile0（ADC0/1）Reset，然后共同production prepare。
- T3：仅ADC tile3（ADC6/7）Reset，然后相同prepare。
- P：不Reset，执行相同prepare，隔离公共配置/MTS步骤的影响。
- S：普通STOP/START。所有组最后八路均工作，DAC输出保持静音。

共同prepare仍会写其他tile的MTS/NCO/QMC等配置；未被显式Reset不等于寄存器完全不写。
严格拒绝隐式时钟恢复或额外Reset；要求固定ADC MTS 492、时钟SHA/锁定、尺度和核心身份不变。

先运行T0/T3/P各10秒短门禁，独立复算通过后自动继续；短门禁不进入正式比较。
正式顺序：`S T0 S T3 S P S T3 S P S T0 S P S T0 S T3 S`。
19段各100秒，100ms原生产品与1秒派生产品；三种干预各三次，十次停启对照。
间隔固定180秒，从上一段STOP返回到下一段接收器武装前；武装后立即START。
队列自动完成全部验签/独立复算、默认三频点及全4096频点空间比较、最终停流静音。
任一步失败安全停流并保留现场，无自动重试。预计110–125分钟。

## 预定分析

每个重置目标预先分为涉及其两路的13对、其余六路组成的15对；P按两种分区各比较一次。
先按有效帧数计算100秒复数均值和自功率，再归一化得到复相关。
用复数差的模比较“前S→干预”和“干预→后S”，不以幅度差替代相位变化。
全频及预定120–140MHz区域分别给出每对中位数；保存完整复数数组以供频谱/相位检查。
不同频点和不同ADC对不能视作独立重复，三次轮换也不等于随机化或洗脱。
前后校准、温度、自功率、MTS及Reset调用列表保留；不给系数变化提前贴因果标签。

## 实现与验证

入口 `scripts/stage-36/t510_stage36_tile_queue.py`。
空间分析 `t510_stage36_tile_analyze.py`。复用PR/ADC-DAC队列的短门禁、完整性和安全收尾。
新增T0/T3受限操作及选定索引Reset；板端helper SHA必须与执行树匹配。
离线测试通过：单tile索引/其他tile不Reset、三组相同prepare、Reset失败后禁止prepare且清理；
13/15预分区、纯相位变化检出、真实chunk读取的非等权平均。
原PR隐藏恢复拒绝、ADC/DAC隔离、MTS隔离及wait→arm→START计时回归均通过。

队列ID `stage36-tile-20260910`；GB10 unit `t510-stage36-tile-20260910.service`。
证据 `/var/lib/t510/measurements/stage36-tile-20260910-queue/`。
独立执行树 `/home/astrolab/.cache/t510/stage36-tile-20260910/repo`，保留含工作区修改的文件SHA清单。
板端helper `/home/xilinx/t510-stage36-tile/t510_stage36_init_probe.py`。
本地提交记录 `build/tile-20260910/`。提交后以实际queue_state判断状态，不把提交视为完成。
