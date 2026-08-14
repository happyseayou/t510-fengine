# Stage 34c：ADC 长积分相关噪声根因调查总计划

## 状态与目标

当前状态为
`PLANNED / 34B2_LOW_RF_TERMINATED / NO_EXPERIMENT_SUBMITTED / NO_PRODUCT_CHANGE`。

Stage 34c不以“换一个门限让结果通过”为目标，而是用可逆干预回答三个问题：

1. 干净频点的慢起伏是否由RF-ADC的OCB1后台偏置校准引起；
2. continuous SYSREF、采样参考时钟或供电/温度是否在制造共同或缓慢变化的噪声；
3. “DAC已静音但回环线仍连接”的模拟状态是否把DAC噪声、时钟泄漏或地环路带入ADC。

只有同时出现“干预后变化、恢复后回到原状、三次重复一致”才称为根因。只看到两个量一起
变化称为相关证据，只看到某条件稍好称为候选贡献，不写成修复。

本计划不修改Stage 34正式RTL、PFB、UDP、bitstream或坏频点掩码。当前没有提交新的板级
实验或长任务。若时钟诊断必须修改PPS/SYSREF RTL，则另生成有新版本身份的诊断bitstream，
不能沿用v34 SHA或静默替换latest。

## 34b-2终止和现有事实

用户已于2026-08-09 17:28:20 CST终止50～330 MHz低RF扩展。完成7个完整的160 MS/s
run，第8个run在fresh CONFIGURE期间中断并排除，320 MS/s及其余平衡重复未执行。
安全收尾已经确认：science停止、receiver不接收、DAC mask为0、八路幅度码全0、八路ADC
解除freeze。该队列不会恢复或重试。

截至目前可以确认：

- 原18次正式A/B/C的数字完整性全部通过；原始中位积分斜率约`-0.261`，时间打乱后约
  `-0.523`，中位`|lag-1|`约0.403。因此问题来自时间顺序，不是功率统计公式或PFB平均
  本身。
- 训练后freeze没有改善。条件B/C中GCB和TSCB哈希各自全程只有一个值，但OCB1在几乎
  每个一秒快照都改变。这说明34b-2已经否定GCB/TSCB为充分根因，没有测试“OCB1停止”。
- 18次正式数据中，同一ADC不同RF的`|correlation|`中位数约0.127；不同ADC同一RF约
  0.064。低RF已完成7次分别约0.132和0.049。起伏更多留在单路内部，优先怀疑每路
  校准或每路模拟前端；全板公共时钟/电源仍不能排除。
- 低RF7次的原始斜率为`-0.187..-0.313`，打乱后为`-0.511..-0.550`。现象不是只在
  700 MHz附近出现，但7次不构成正式频率依赖结论。
- Stage 33a已经证明480、960、1440 MHz是3.84 GS/s Dual RF-ADC八路交织形成的
  `k*Fs/8`固定项；其幅相会随OCB1变化。锁住OCB1能稳定这些固定项，却仍留下约
  9～11.5 dB高于局部噪声的残余。这个事实证明OCB1控制链确实能影响固定杂散，但尚未
  证明它会造成所有干净bin的慢功率起伏。
- 历史Stage 27物理测试还发现122.88 MHz板内固定项：回环线拔除、ADC接50 Ω输入、
  外部/板载10 MHz参考切换均未消失。这是独立的板内时钟泄漏证据，不能和OCB1的
  `k*Fs/8`固定项混成同一个问题。

## 通俗物理模型

### OCB1为什么可疑

每个物理RF-ADC实际上由多个更小的ADC轮流采样。ZU47DR的Dual RF-ADC每路有8个交织
子ADC。若八个子ADC看到“零输入”时各有一点不同的零点，误差会每8个样本重复一次，
于是频谱出现`Fs/8`及其整数倍。OCB1会在后台持续估计并修正这八个零点，主要用于跟踪
温度变化。

AMD PG269明确说明：OCB1在后台持续工作；常规CalFreeze控制的是GCB和TSCB。PG269也
说明Gen 3允许通过`XRFdc_SetCalCoefficients`恢复用户系数，但不建议手工持续更新OCB1/2；
加载系数会关闭相应实时校准，重新启用时还可能出现暂态杂散。因此OCB1 override只能作为
短时、可恢复的因果实验，不能预先当作产品方案。

### 时钟和SYSREF会造成什么

采样时刻如果抖动，输入信号斜率越大，转换出的幅度误差越大。所以时钟抖动的典型特征是：
同样ADC电平下，RF越高，SNR或载波裙边越差。没有输入、只接50 Ω时，单纯的随机采样抖动
通常不应制造很大的宽带慢功率漂移；但时钟直接串扰到模拟输入、PLL/VCXO电源被调制，或
continuous SYSREF像第二个时钟一样耦合，则会产生固定梳状项及可能的慢调制。

当前LMK04828一直输出10 MHz continuous SYSREF。TI数据手册明确不建议在低噪声应用中
持续输出SYSREF，因为它会串扰到device clock；AMD PG269则允许MTS完成后关闭SYSREF。
这使“只在MTS期间打开、采集期间关闭”成为高优先级的单变量实验。但当前PL用10 MHz
SYSREF域捕获1PPS，不能直接关掉后仍假装保持正式同步语义。

### 供电和温度会造成什么

慢速供电或温度变化会让ADC增益、噪声底和校准系数缓慢移动；开关电源纹波则更常形成固定
频率杂散及其与载波的边带。AMD对Gen 3的`ADC_AVCC`和`ADC_AVCCAUX`给出很严的纹波
要求：0.1～15 MHz内分别不超过0.25 mVpp和1.2 mVpp。

本板Linux已经能从`ffa50000.ams`读取PS/PL温度与芯片内部电源轨。实查没有PMBus/INA
hwmon或外部I2C电源监控，因此软件能看到慢温漂和部分芯片内部电压，却看不到ADC_AVCC、
ADC_AVCCAUX、LMK/VCXO各路稳压器的真实纹波。后者必须在确认测试点后用低噪声探头测量。

### 模拟回环为什么不是“无信号”

把DAC幅度设为0，只表示不发数字单音；DAC输出级、采样镜像、时钟泄漏、地环路和回环线
仍然连接在ADC输入。真正的“ADC本底”基线应是：DAC物理断开，ADC连接器处接各自独立、
屏蔽良好的50 Ω终端。

两只低噪放不能代替50 Ω终端。LNA本身会增加噪声、1/f增益漂移、偏置电源噪声，并可能
在不良端接下自激。它们可以在后期作为“模拟前端代表链路”接到ADC0/ADC2，但必须先用
SSA确认不振荡，并配置DC block、衰减和滤波，不能用于最初的ADC零输入定责。

## 统一测量合同

所有后续子阶段使用同一套指标，避免每发现一个现象就换算法。

### 正式数字观测

- 160和320 MS/s SPEC_ONLY；需要判断PFB之前/之后时，追加160 MS/s TIME_SPEC。320
  MS/s不启用非法TIME_SPEC。
- receiver继续从现有PACKET_MMAP环读取，不创建第二个packet socket。
- 每秒记录最多32个预注册RF/bin的八路功率、样本数、seq/frame/sample0连续性；固定包含
  干净低RF、原681.25～792.5 MHz安全bin和实验窗口内的板内时钟/固定项。
- 480、960、1440 MHz及左右各4 bin只从“干净bin总体斜率”排除，原始功率、幅相、
  OCB1关系仍完整记录。122.88 MHz及谐波另列为`BOARD_CLOCK_WATCH`，不静默屏蔽。
- 每次600秒计算1、2、4、8、16、32、64、128秒标准差、Allan deviation、原始/时间
  打乱斜率、lag-1及完整ACF、同ADC跨RF和跨ADC同RF相关矩阵。
- 每次开始/结束各保存一份QSFP原始PCAP，生成SHA256；所有drop、gap、backpressure、
  FIR saturation和XFFT overflow必须为0，否则该run不能用于物理结论。

### 新增板端伴随观测

- OCB1/OCB2/GCB/TSCB原始系数、固定顺序SHA256和每个子ADC解包值；额外把OCB1八个
  偏置系数转换为`k=1..4`离散傅里叶分量，以便直接对照`k*Fs/8`固定项。
- freeze mask、请求状态、校准模式、dither状态和本次OCB override的软件事务ID。
- RFSoC AMS的PS/PL/remote温度，以及`vccint/vccaux/vccbram`等已暴露内部轨；建议5 Hz
  读取后按秒保存min/mean/max。当前34b证据中的temperature全为null，此处必须修复。
- LMK PLL1/PLL2 lock、当前profile、reference选择和关键寄存器在run首尾读取；高频轮询
  只读lock状态，避免SPI轮询本身成为新的活动源。
- 外部示波器、相噪仪或SSA证据统一使用公共10 MHz/1PPS或显式时间标记对齐；无法对齐的
  数据只做频谱证据，不与一秒功率序列做伪精确回归。

### 因果判定

候选被称为`CAUSAL`至少同时满足：

1. 预注册主指标在3次重复中方向一致；
2. 干预相对紧邻控制使中位`|slope+0.5|`改善至少0.12，且中位`|lag-1|`下降至少0.10；
3. 至少80%的`ADC×clean-bin`斜率进入`-0.65..-0.35`，原始与打乱后的中位斜率差不超过
   0.10；
4. 撤销干预后，指标回到干预前95%置信区间，或再次显著恶化；
5. 所有数字完整性门禁通过，且没有通过降低速率、减少通道或丢帧换取改善。

若只稳定480/960/1440 MHz而干净bin斜率不变，结论为
`OCB1_FIXED_SPUR_ONLY`；若只改善外部强单音的高频SNR而静默积分不变，结论为
`CLOCK_TONE_QUALITY_ONLY`；部分但可重复的改善标为`CONTRIBUTOR`，不冒充唯一根因。

## Stage 34c-0：可观测性和50 Ω参考状态

这是所有因果实验的前置门。先实现上述伴随监控，再做以下对照：

1. 保持当前“DAC静音但八路回环线连接”，160/320各采600秒一次，复现现状。
2. STOP、DAC静音、物理拔除八路回环线，在八个ADC连接器处安装经过检查的独立50 Ω
   终端；160/320各做3次600秒平衡重复。
3. 160 MS/s追加一次600秒TIME_SPEC，同时对每路TIME计算一秒I/Q均值、RMS、峰值、
   偏度/峰度；判断相同慢起伏在PFB之前是否已经存在。
4. 每种物理状态开始前做SSA本底/终端检查，并保存连接照片、终端编号和通道映射。

分流规则：

- 若50 Ω后斜率恢复、lag明显下降，优先进入34c-4，OCB1/时钟/供电只做最小复核；
- 若50 Ω后仍复现，进入34c-1；
- 若TIME平稳而SPEC不平稳，重新审查PFB/功率统计；若TIME和SPEC共同起伏，继续模拟/RFDC
  根因路线。

## Stage 34c-1：OCB1可逆因果实验

### 支持边界

ZU47DR属于Gen 3。板端`libxrfdc.so`已实查具备：

- `XRFdc_GetCalCoefficients`
- `XRFdc_SetCalCoefficients`
- `XRFdc_DisableCoefficientsOverride`
- `XRFdc_Set/GetCalFreeze`
- `XRFdc_Set/GetCalibrationMode`
- `XRFdc_Set/GetDither`

PG269对Gen 3允许OCB1系数get/set，但明确不推荐人工持续更新。实验只把刚读出的原值写回，
不搜索“更好系数”、不持续追踪写入、不改某几个子ADC，也不把override带进正式观测。

### A1/B/A2设计

在34c-0确认会复现问题的物理输入状态下，每种采样率执行3个fresh重复；每个重复固定为：

1. `A1_DYNAMIC`：fresh CONFIGURE/MTS；GCB/TSCB按同一批准流程固定；OCB1保持正常后台
   运行，600秒。
2. `B_OCB1_SNAPSHOT_OVERRIDE`：fresh CONFIGURE/MTS，在停流状态读取八路OCB1，原子写回
   同一组值并回读；600秒期间禁止任何系数再写，保存八路哈希和固定项幅相。
3. `A2_RESTORED`：STOP后调用`XRFdc_DisableCoefficientsOverride`，再做完整RFDC reset、
   CONFIGURE和MTS，确认OCB1重新变化后运行600秒。

不能仅靠`DisableCoefficientsOverride`后立即开流，因为PG269提醒重新启用实时校准可能产生
暂态杂散。A2必须经过完整恢复并重新建立基线。任意一路写入/回读失败，都立即STOP、DAC
静音、对全部八路解除override并做RFDC恢复；部分override的数据全部无效。

主观察量同时包含：

- 480/960/1440 MHz固定项的幅度和相位是否停止游走；
- 干净bin的斜率、lag和同路跨频相关是否恢复；
- OCB1的`k=1..4`分量与固定项/干净bin的滞后相关；
- A2是否重新出现A1行为。

如果八路A1/B/A2显示明确效果，再追加“每个tile一条override、一条dynamic”的配对诊断，
以相同温度、时钟和供电同时比较，排除全板慢漂移。该配对状态只允许在单次诊断run内存在，
结束后必须全板恢复。

当前dither不列为首轮变量。ZU47DR最大RF-ADC速率为5.0 GS/s，3.84 GS/s约为其76.8%，
位于PG269建议启用dither的范围，且Stage 33a已做过dither A/B。若AMD支持明确要求复查，
再将其作为独立变量，不能与OCB1 override同时改变。

## Stage 34c-2：时钟、SYSREF和参考源

### 先测量，不先改寄存器

当前PLL lock只证明“锁住”，不能证明低相噪、无杂散或供电干净。先在可接触测试点测：

- 外部10 MHz的幅度、占空比、相噪/积分抖动和离散杂散；
- 122.88 MHz VCXO、LMK 160 MHz RFDC reference和10 MHz Analog/PL SYSREF；
- ADC连接器50 Ω状态下的122.88 MHz、10/20 MHz栅格及其谐波；
- LMK未用输出是否关断、相邻clock/SYSREF输出组和线缆/地回路。

探头噪底、RBW、积分范围和测试点都要记录。不能把“仪器没看见”写成低于ADC内部噪底，
除非仪器门限确实足够。

### 单变量A/B顺序

1. `CLK-A`：外部10 MHz + 当前10 MHz continuous SYSREF。
2. `CLK-B`：外部10 MHz不变，只把SYSREF改为request/pulser；MTS期间打开，采集期间关闭。
3. `CLK-C`：板载TCXO参考 + continuous SYSREF；需要真实的CLKin0 LMK profile，不能只改
   selector GPIO，因为当前profile手动固定CLKin2。
4. `CLK-D`：若B有明确效果，再测试TCXO + request SYSREF，区分外部参考和SYSREF串扰。
5. `CLK-E`：只有10 MHz相关项仍明确时，才单独建立小于10 MHz的SYSREF profile；不能把
   频率、continuous/request和PLL拓扑三项同时改掉。

现有PL以10 MHz SYSREF域捕获PPS。CLK-B采集期间关闭SYSREF时，首先尝试显式标记的
immediate-start诊断模式，并暂停依赖该域的正式同步资格判断；数字数据仍必须连续。若现有
bitstream无法在该状态安全采集，就停止软件尝试，另立诊断bitstream重构PPS捕获。任何新
bitstream都使用新CORE_VERSION，并按完整synthesis→implementation→write_bitstream长任务
链构建，不能篡改v34身份。

静默50 Ω积分之外，SSA TG经滤波/功分器接ADC0/ADC2，以相同ADC dBFS在100、700、
1420 MHz附近注入稳定单音。若时钟是主因，载波裙边或SNR恶化应随RF升高，并随参考/SYSREF
干预可逆变化。单音结果称为时钟+源+ADC0/ADC2端到端结果，不把SSA边带写成ADC杂散。

## Stage 34c-3：供电和热稳定性

当前执行入口和资格状态见
[Stage 34c-3正式报告](34c-3_power_thermal_causality.md)。软件可控的输出负载层已经实机
快速验证；DAC全tile Shutdown因RFDC驱动等待状态6超时，按预注册规则标为
`INTERVENTION_UNQUALIFIED`并在完整CONFIGURE/MTS恢复后停止重试。独立的输出负载和自然
AMS层现已全部完成：TIME_SPEC没有相对SPEC_ONLY产生可逆改善，160/320两条60分钟观察仍
分别得到接近0的积分斜率和约0.84/0.85的lag-1，因此输出负载被排除为主因，长积分失败保持。
AMS没有达到注册相关证据线；物理模拟电源纹波与主动热控因果仍保持待办。

### 软件层

Board Agent增加只读AMS monitor。当前实机已确认可读PS、PL、remote三点温度及内部
`vccint/vccaux/vccbram`等电源；这些量以5 Hz采样、一秒min/mean/max保存，并与功率和
OCB1轨迹统一时间轴。AMS只用于慢漂移/负载阶跃，不用于证明0.1～15 MHz纹波合格。

### 物理层

先取得MicroPhase电源树/测试点说明；没有图纸或测试点身份时不在未知焊盘上探测。正式
至少覆盖：

- `ADC_AVCC 0.925 V`，Gen 3规范纹波不超过0.25 mVpp；
- `ADC_AVCCAUX 1.8 V`，Gen 3规范纹波不超过1.2 mVpp；
- LMK的VCO、PLL2/charge pump、SYSREF/clock-output-group与VCXO供电；
- 板卡总输入电源和地电位差。

测量分成DC～10 Hz慢变化、10 Hz～100 kHz低频噪声和0.1～15 MHz规范带宽；高频开关
杂散另用频谱/近场探头。探头本底必须显著低于0.25 mVpp，否则只能给上限，不能给PASS。

负载与环境按一次只改一项执行：

1. stream off与160/320 SPEC full-rate；
2. DAC tile正常但静音，与在器件允许流程下关闭DAC tile；
3. 当前电源适配器与同电压、足够电流的低噪声实验室总输入电源；
4. 风扇固定安全转速的冷/暖两个稳态，不使用热风枪直接冲击器件；
5. 当前接地与整理后的星形接地/去除不必要USB地环路。

只有“某轨或温度量与功率起伏相符，改变该物理量后指标改善，恢复后问题回来”才判为
`POWER_CAUSAL`或`THERMAL_CAUSAL`。仅有回归相关、没有干预复现，标为`CORRELATED_ONLY`。
若ADC轨纹波超AMD规范，直接转入独立板级电源整改阶段，不在软件中滤掉结果。

## Stage 34c-4：模拟输入链路隔离

按以下物理状态逐层增加器件，每种状态都保存照片、线缆/终端序列号和连接表：

1. 八路DAC回环连接、DAC数字静音；
2. 回环线全部拔除、八路ADC连接器各自50 Ω终端；
3. 交换终端和线缆，判断现象跟随ADC通道还是跟随夹具；
4. SSA TG经已验证功分器只接ADC0/ADC2，另外六路保持独立50 Ω；
5. 两只LNA的输入各接50 Ω，输出经DC block、带外滤波和可调衰减后接ADC0/ADC2；
6. 后续有校准宽带噪声源时，再做真正的外部宽带`1/sqrt(N)`天文资格测试。

LNA步骤必须先在SSA上确认：无自激、输出无clip、增益和噪底随时间稳定、偏置电源干净；
ADC输入电平留足余量。两只LNA只能给ADC0/ADC2代表性模拟前端结论，不能外推八路或系统
温度，也不能代替校准噪声源。

判断方式：

- 问题从回环状态切到50 Ω后消失：`DAC_LOOPBACK_ANALOG_CHAIN_CAUSAL`；
- 问题跟随终端/线缆：`FIXTURE_CAUSAL`；
- 问题固定在ADC通道、与夹具交换无关：`BOARD_LANE_OR_RFADC_CAUSAL`；
- 八路同时随参考/供电变化：转回34c-2/3；
- 122.88 MHz固定项在50 Ω下仍存在但长积分干净bin正常：单独归为板内时钟泄漏坏频点，
  不把它误判成全部相关噪声的根因。

## 执行顺序与停止规则

固定顺序为：

```text
34c-0 50 Ω基线与监控闭合
  ├─ 50 Ω已修复 → 34c-4模拟链路定责
  └─ 50 Ω仍复现 → 34c-1 OCB1 A1/B/A2
                         ├─ OCB1只稳固定项 → 34c-2
                         └─ OCB1改善干净bin → 配对复核后仍继续最小clock/power审计
34c-2 clock/SYSREF
34c-3 power/thermal
34c-4 analog-chain synthesis and external-front-end check
```

这是根因调查，不把“假设被否定”当作campaign故障；否定OCB1后应自动进入时钟，而不是
停在那里。只有以下情况立即停止整个自动队列：硬件/API错误、任何drop/gap/overflow、
ADC/DAC clip、MTS失效、时钟失锁、未知电源测试点、部分OCB override无法恢复或安全收尾
失败。

需要物理插拔、探头或SSA设置时允许暂停等待用户。每一段纯自动的600秒矩阵仍按长任务规则
一次性提交，确认健康启动后不驻留轮询。每个自动段结束必须回读：

- `streaming=false`
- `stream_accepting=false`
- DAC enable mask=`0x00`
- 八路DAC幅度码全0
- ADC freeze mask=`0x00`
- OCB1 coefficient override全部解除
- LMK恢复正式external-10-MHz continuous profile，除非下一人工步骤明确要求保留诊断状态

## 产物和结论等级

固定证据目录建议为：

- `build/board/latest/evidence/adc_correlated_noise_root_cause`
- `build/receiver/latest/evidence/adc_correlated_noise_root_cause`

生成：

- 每路功率、TIME RMS、OCB1 DFT分量、温度和内部电压的共时间轴图；
- 480/960/1440 MHz固定项幅相与OCB1轨迹图；
- 122.88 MHz及10/20 MHz栅格的clock/SYSREF A/B图；
- 原始/打乱积分曲线、Allan、ACF和跨频/跨路相关矩阵；
- 采样参考相噪、积分抖动、SYSREF和电源纹波的仪器截图/CSV；
- 物理连接矩阵、照片、设备设置、PCAP及SHA256 manifest；
- 每个干预的A1/B/A2效应量和置信区间。

最终只允许以下结论之一或多个贡献项组合：

- `OCB1_CAUSAL`
- `OCB1_FIXED_SPUR_ONLY`
- `CLOCK_SYSREF_CAUSAL`
- `CLOCK_TONE_QUALITY_ONLY`
- `POWER_CAUSAL`
- `THERMAL_CAUSAL`
- `DAC_LOOPBACK_ANALOG_CHAIN_CAUSAL`
- `BOARD_LANE_OR_RFADC_CAUSAL`
- `MULTIPLE_CONTRIBUTORS`
- `ROOT_CAUSE_NOT_IDENTIFIED`

只有找到可逆根因并完成独立资格阶段，才讨论产品修复。Stage 34a的长积分不合格状态在此
之前保持不变；不实施notch、隐藏bin、静态扣除、持续自适应扣除或降低吞吐率。

## 官方依据

- AMD PG269：
  [OCB1持续后台校准](https://docs.amd.com/r/en-US/pg269-rf-data-converter/Time-Interleaved-Offset-Calibration-Block-OCB)、
  [CalFreeze控制GCB/TSCB](https://docs.amd.com/r/en-US/pg269-rf-data-converter/Background-Calibration-Process)、
  [Gen 3系数get/set及恢复暂态](https://docs.amd.com/r/en-US/pg269-rf-data-converter/Getting/Setting-Calibration-Coefficients)。
- AMD PG269：
  [SYSREF在MTS期间需连续但完成后可关闭](https://docs.amd.com/r/en-US/pg269-rf-data-converter/SYSREF-Signal-Requirements)。
- TI LMK04828：
  [continuous SYSREF不推荐用于低噪声应用](https://www.ti.com/lit/ds/symlink/lmk04828.pdf)。
- AMD UG583：
  [RF-ADC电源纹波要求](https://docs.amd.com/r/en-US/ug583-ultrascale-pcb-design/ADC-and-DAC-Voltage-Supply-Specifications)、
  [模拟与时钟隔离要求](https://docs.amd.com/r/en-US/ug583-ultrascale-pcb-design/Analog-and-Clock-Pair-Routing)。
- AMD PG269/UG583：
  [RF-ADC差分输入与源阻抗匹配](https://docs.amd.com/r/en-US/pg269-rf-data-converter/RF-ADC-Analog-Input)、
  [50 Ω单端到100 Ω差分balun要求](https://docs.amd.com/r/en-US/ug583-ultrascale-pcb-design/Choosing-the-Appropriate-Balun)。
