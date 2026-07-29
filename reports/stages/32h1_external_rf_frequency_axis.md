# Stage 32h1：外部绝对RF频率轴

## 状态

`IN_PROGRESS`

## 目标

用外部已知RF源校正接收页面的SPEC频率方向，只修改RF显示、marker和频率到bin
换算，不修改ADC Q、PFB、UDP bin顺序、header、payload、端口或flow。

## 已确认的修复前证据

- 320 MS/s、center 170 MHz、外部真实280 MHz经功分送入ADC0/ADC1。
- 两路主峰都位于raw SPEC bin 1408；旧页面按减号映射为60 MHz，正确加号映射为
  280 MHz。
- 真实60 MHz共轭bin 2688功率分别约9.03/6.99 dB，主峰约81.71/81.84 dB，
  镜像抑制约72.68/74.85 dB。
- 该结果证明ADC real-to-complex、PFB和UDP数据没有产生DAC自环中约4.5 dB的
  强镜像。

## 实施与门禁

- [x] Web频率换算、反向bin换算和横轴顺序修正。
- [x] Node、receiver Rust和静态musl构建通过。
- [x] 新receiver部署到`astrolab@192.168.100.162`。
- [x] 320 MS/s外部60/280 MHz在ADC0/ADC1均命中真实RF±1 bin，镜像≥60 dBc。
- [ ] 160 MS/s外部120/220 MHz在ADC0/ADC1均命中真实RF±1 bin，镜像≥60 dBc。
- [ ] 主机和FPGA没有新增drop/gap/overflow。

## 实际改动

- `rust/t510_time_rx/static/stage29_math.js`
  - `RF = center + signed_bin * sample_rate / nchan`。
  - `signed_bin = round((RF - center) * nchan / sample_rate)`。
  - `orderedBins()`按负频率到正频率严格递增输出。
- `tests/test_stage29_web_math.js`覆盖320/160 MS/s绝对频率、半bin往返误差和
  横轴单调性。
- `rust/t510_time_rx/src/main.rs`中的内嵌Web数学测试同步为加号约定。
- 新增只读门禁脚本`scripts/stage32h1_external_rf_axis_gate.py`及其Python测试。

## 离线测试结果

- `node tests/test_stage29_web_math.js`：PASS。
- `python3 -m unittest discover -s tests`：62项PASS。
- receiver Rust测试：lib 7项、binary 29项，共36项PASS。
- x86_64 musl静态release构建：PASS（仅有既有linker warning）。
- 实施所基于的仓库HEAD：`1c96aa4b811c5889762d87136b4975296a310071`；
  本阶段代码尚未提交，因此最终提交SHA待闭合时补记。

## 部署与板端证据

- receiver release ID：`stage32h1-rf-axis-20260729-r2`。
- 部署二进制SHA256：
  `65c61dffc9506f39b0f11da7053b9da271a68d46e260e44f0b0def375ca4f840`。
- systemd服务：`t510-time-rx.service`为`active`，Web监听端口为8089。
- 修复前外部280 MHz快照：
  `reports/board/stage32h1_external_280mhz_predeploy_20260729.json`。
- 修复后外部280 MHz快照：
  `reports/board/stage32h1_external_280mhz_postdeploy_20260729.json`。
- 修复后320 MS/s、center 170 MHz、外部280 MHz：
  - ADC0：peak bin 1408 → 280.000 MHz，镜像抑制70.42 dB。
  - ADC1：peak bin 1408 → 280.000 MHz，镜像抑制68.59 dB。
  - 五帧观测窗口内receiver新增kernel/ring/app drop及SPEC sequence/frame gap均为0。
- 修复后外部60 MHz快照：
  `reports/board/stage32h1_external_60mhz_postdeploy_20260729.json`。
- 修复后320 MS/s、center 170 MHz、外部60 MHz：
  - ADC0：peak bin 2688 → 60.000 MHz，镜像抑制67.15 dB。
  - ADC1：peak bin 2688 → 60.000 MHz，镜像抑制63.49 dB。
  - 五帧观测窗口内receiver新增kernel/ring/app drop及SPEC sequence/frame gap均为0。
- 同一时刻板端LMK PLL1/PLL2均锁定，reference watchdog healthy，
  PFB/XFFT/backpressure/drop错误为0。`rfdc_dropped=18`是本次START建立流时已经存在的
  启动计数，后续门禁只接受增量为0。

## 160 MS/s、center 170 MHz配置门禁修复

切换到160 MS/s前，Agent先正确拒绝了硬件中仍为60 MHz的DAC配置。将实时DAC临时
移到170 MHz后，CONFIGURE仍被固定的`DacChannelConfig`默认值60.010 MHz拒绝。
根因是`python/t510_hw.py::_configure()`已经使用`program_dac=False`，却在仅用于
合法性检查的`Stage29Config`中没有提供占位DAC配置，因此错误继承了历史默认值。

最小修复如下：

- CONFIGURE用请求的`profile.center_mhz`构造8路带内占位DAC配置；
- `program_dac=False`保持不变，CONFIGURE不会实际写这些占位值；
- `tests/test_t510_hw.py`明确用160 MS/s、center 170 MHz验证8路占位频率；
- 14项`t510_hw`单元测试和`git diff --check`均PASS；
- 本地验证包：
  `build/stage32/stage32h1-center170-config-20260729/`；
- 板端不可变PYNQ release：
  `stage32h1-center170-config-20260729-r2`；
- 修复后`t510_hw.py` SHA256：
  `7e27ec263211c2ea858cf133cea1ded1d0fa27f114cd86f68a8eae23d80f18b5`。
- 安装后Jupyter、Board Agent和reference watchdog三个systemd服务均为
  `active`。
- 160 MS/s、`SPEC_ONLY`、center 170 MHz fresh CONFIGURE成功，耗时
  8645.082 ms；ADC latency为`[230,230,230,230]`、target 230，DAC latency为
  `[335,335,335,335]`、target 336。
- START后LMK双锁、watchdog `MONITORING/healthy`、QSFP link、55-tap half-band
  和PFB/XFFT均健康；receiver稳定接收约625 kpps / 41.60 Gbit/s，主机drop为0。
- fresh bitstream把DAC恢复为8路disabled、0%和零基带，避免DAC信号干扰外部ADC
  绝对频率门禁。
- 160 MS/s外部120 MHz快照：
  `reports/board/stage32h1_external_120mhz_postdeploy_20260729.json`。
- 160 MS/s、center 170 MHz、外部120 MHz：
  - ADC0：peak bin 2816 → 120.000 MHz，镜像抑制71.54 dB。
  - ADC1：peak bin 2816 → 120.000 MHz，镜像抑制69.43 dB。
  - 五帧观测窗口内receiver新增kernel/ring/app drop及SPEC sequence/frame gap均为0。

160 MS/s的220 MHz证据尚未完成，因此32h1仍为`IN_PROGRESS`。

## 尚需人工配合的门禁

同一外部源继续经功分送入ADC0/ADC1，最后设置为160 MS/s的220 MHz。稳定后运行
同一只读门禁并保存JSON。四个频点全部通过前，本阶段维持`IN_PROGRESS`，32h2
不得启动Vivado构建。

## 回滚

接收机部署失败时恢复上一Stage 32 receiver release；不更改板上LMK或bitstream。
