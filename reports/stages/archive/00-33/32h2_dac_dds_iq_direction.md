# Stage 32h2：DAC DDS复数方向与bitstream

## 状态

`PASS`

## 目标

让PL DDS、RFDC I/Q-to-Real mixer和接收端RF坐标使用同一符号合同：

- `baseband = requested_rf - center`；
- `I=cos(theta)`、`Q=sin(theta)`；
- 正`phase_step`产生正复频率；
- `phase_deg=0`位于正I轴，`phase_deg=90`位于正Q轴；
- AXIS保持偶数16-bit word为I、奇数word为Q，128-bit排列不变。

32h2只判定请求频率和复相位方向。镜像、梳状杂散和幅度线性是32h3的独立纯度
门禁，不能再用纯度数值否决一个频率方向正确的32h2结果。

## 前置条件

- 32h1已经用外部绝对RF源闭合接收页面、PFB bin和UDP频率轴。
- 接线为`DAC0 -> 功分器 -> ADC0/ADC1`，两路使用不同长度线缆。
- LMK、SYSREF、MTS、ADC/DAC 1.6 GS/s与5倍抽取/插值保持Stage 32冻结值。

## 最终实现

- `rtl/t510_dac_loopback_source.sv`输出标准正向复数：
  `I=cos(theta+n*step)`、`Q=sin(theta+n*step)`。
- 一拍四个样点保持
  `{Q3,I3,Q2,I2,Q1,I1,Q0,I0}`，8路独立参数、enable mask和phase epoch不变。
- Agent继续原样计算并传递
  `baseband_offset_hz=(requested_rf-center)*1e6`，没有Python反号补偿。
- `compute_dac_source_phase_metrics()`使用正复频率基函数，只用于诊断，不进入实时
  数据面。
- RFDC 8条DAC路径固定为：Real模拟输出、Fine mixer、I/Q-to-Real、width 8、
  interpolation 5。`DAC_Data_Type=1`会收缩成4条成对I/Q模拟输出，不是本项目的
  修复方案；该错误实验和综合失败记录在
  `../vivado/stage32h2_dac_iq_direction/second_iteration_synthesis_failure.md`。

最终候选产物：

| Artifact | SHA256 |
|---|---|
| bit | `47117c9e656cfd8345125ef0130eb91a5ec0868cef59931b40b957da29f31234` |
| HWH | `2a341b6a959ed9483b861c15eaac1d5fa708554dde6cded96613b52c0c96dca5` |
| overlay Tcl | `0804b781a7368a3598771f7ae304f5a9ccecc4807b66a240a7747ea3bde63c6e` |

`CORE_VERSION`保持`0x00010032`。构建已fully routed，WNS/WHS为
`+0.115/+0.010 ns`，DRC和Methodology无Error/Critical Warning violation；详见
`../vivado/stage32h2_dac_iq_direction/build_summary.md`。

## 被否决的第二个bit

SHA256为
`d4950668aeb42ba1145e1504018934dde838b8a422126dde7178afa9e5575cb0`的第二个bit
把每样点及每拍相位更新改为减`phase_step`。物理测试证明它在320 MS/s下会把
120/220 MHz全局互换，因此该假设被否决，禁止发布。对应构建的route/timing证据
仍然是真实的，但不构成产品通过证据；详见
`../vivado/stage32h2_dac_iq_direction/final_sign_fix_build_summary.md`。

## 初始化状态诊断

正向候选bit曾在一个既有160配置会话中出现请求120 MHz而raw RFDC主峰为
`+50 MHz`的异常。为了区分DAC、RFDC、half-band和PFB，新增两个只读诊断：

- `scripts/pynq_stage32h2_raw_preview.py`：直接抓RFDC ADC complex AXIS的1024个
  原始样点，绕过half-band、PFB和UDP，并在finally中STOP和关闭全部DAC；
- `scripts/pynq_stage32h2_rfdc_readback.py`：导出ADC/DAC mixer、Nyquist zone、
  抽取/插值等runtime回读。

诊断结果：

| 条件 | raw ADC0/ADC1主峰 | 结论 |
|---|---|---|
| 异常160会话，请求120 MHz | `+50/+50 MHz` | 异常发生在half-band/PFB之前 |
| fresh CONFIGURE 320，请求120 MHz | `-50/-50 MHz` | 正向候选与请求方向一致 |
| 再fresh CONFIGURE 160，请求120 MHz | `-50/-50 MHz` | 160模式本身不会翻号 |

160与320的全部有效RFDC block回读逐字段一致：ADC为`-170 MHz/R2C/decimation 5`，
DAC为`+170 MHz/C2R/interpolation 5`，Nyquist zone均为1。异常会话在一次完整
`STOP/flush -> bit download -> RFDC init/MTS`的fresh CONFIGURE后消失，且随后raw
和UDP复验均正确。因此它记录为`INIT-STATE-001`：不能用旧overlay状态或仅修改
DAC寄存器代替完整发布序列。RFDC可见回读本身不足以证明数据路径已经重新初始化。

证据：

- `../board/stage32h2_raw_preview_160_120mhz_20260802.json`；
- `../board/stage32h2_raw_preview_320_120mhz_20260802.json`；
- `../board/stage32h2_raw_preview_160_120mhz_after_fresh_configure_20260802.json`；
- `../board/stage32h2_rfdc_readback_160_20260802.json`；
- `../board/stage32h2_rfdc_readback_320_20260802.json`。

## 最终物理矩阵

每个点均从停流、DAC全关状态开始。160和320之间使用完整fresh CONFIGURE；每项
结束均STOP/flush并回读DAC mask为0。

| 模式 | 请求RF | ADC0主峰/镜像抑制 | ADC1主峰/镜像抑制 | 方向 |
|---|---:|---:|---:|---|
| 160 | 120 MHz | 120 MHz / 64.42 dB | 120 MHz / 65.78 dB | PASS |
| 160 | 220 MHz | 220 MHz / 66.05 dB | 220 MHz / 52.02 dB | PASS |
| 320 | 60 MHz | 60 MHz / 55.35 dB | 60 MHz / 60.82 dB | PASS |
| 320 | 280 MHz | 280 MHz / 66.93 dB | 280 MHz / 60.69 dB | PASS |

四项的目标bin误差均为0。正式采集窗口内，FPGA science/PFB/XFFT/TX drop或
overflow增量、receiver kernel/ring/app drop及sequence/frame gap增量均为0；
`rfdc_dropped`在每个窗口前后也保持不变。52.02和55.35 dB只记录为32h3纯度
warning，不改变32h2方向判定。

证据：

- `../board/stage32h2_positive_candidate_loopback_160_120mhz_after_fresh_configure_20260802.json`；
- `../board/stage32h2_positive_candidate_loopback_160_220mhz_after_fresh_configure_20260802.json`；
- `../board/stage32h2_positive_candidate_loopback_320_60mhz_after_fresh_configure_20260802.json`；
- `../board/stage32h2_positive_candidate_loopback_320_280mhz_after_fresh_configure_20260802.json`。

## 离线验证

- `python3 -m unittest tests.test_stage32h2_dac_iq_direction`：5项PASS。
- `scripts/run_xsim_batch.sh tb_t510_dac_loopback_source`：PASS，验证正/负Fs/4、
  phase0、每拍4样点、8路同步、enable mask和phase epoch。
- 第一轮候选构建前全量31项XSim、Python、Board Agent Rust和receiver Rust回归
  已PASS；构建及版本证据见上述Vivado报告。
- `scripts/stage32h2_dac_loopback_gate.py`现将频率/bin、drop/gap作为32h2硬门禁，
  镜像抑制默认记录warning；只有显式`--enforce-image-rejection`才作为纯度硬门禁。

## 非目标与冻结项

未修改LMK、SYSREF、MTS target、ADC/DAC速率、PFB、UDP header/payload/端口/flow、
REST schema或`CORE_VERSION`。物理线长造成的固定相位和幅度差不属于频率方向错误。

## 回滚与发布规则

- 发布只允许使用SHA256为`47117c...1234`的Stage 32候选，禁止使用`d495...5cb0`。
- 每次上板必须完整执行：STOP/flush、LMK lock、下载匹配bit、RFDC init/MTS，再
  设置DAC并START；不得在旧overlay状态上只热改DAC寄存器。
- 失败时恢复到停流、DAC mask 0，保存raw preview和RFDC回读后重新fresh
  CONFIGURE；不回退Stage 31。

## 下一阶段准入

32h2证据齐全，准入32h3频谱仪纯度测试。32h3通过前，32h仍保持`IN_PROGRESS`，
不得恢复Stage 32单板release声明。
