# Stage 32h：单板产品发布与长稳

## 状态

`PASS`

既有五模式吞吐、PPS切换、故障恢复和长稳门禁仍为有效`PASS`证据。2026-07-29
外部绝对RF输入发现接收频率轴反向，DAC直接频谱仪测量又发现真实梳状杂散，因此
单板release重新打开以下三个串行步骤：

| 子步骤 | 内容 | 当前状态 |
|---|---|---|
| 32h1 | 外部绝对RF频率轴 | `PASS` |
| 32h2 | DAC DDS复数方向与bitstream | `PASS` |
| 32h3 | DAC频谱仪纯度门禁 | `PASS` |

32h1～32h3现已全部`PASS`，本报告恢复`PASS`。这次重新打开不追溯否定既有
数据吞吐和长稳结果，并新增了绝对RF频率、DAC频谱纯度和修复后满速回归证据。

2026-08-02更新：32h2最终候选bit SHA256为
`47117c9e656cfd8345125ef0130eb91a5ec0868cef59931b40b957da29f31234`。完整fresh
CONFIGURE后的160/320四点物理方向矩阵全部通过，反向相位bit已否决。32h3随后
完成频谱仪9项矩阵：最差镜像抑制72.66 dBc、最差最大杂散-53.04 dBc、四组
25%到100%功率增量为12.02..12.12 dB，8路同时输出对DAC0影响仅-0.01 dB；
修复后160 TIME_SPEC和320 SPEC_ONLY各60秒板端/主机回归也全部通过。因此本报告
正式恢复`PASS`。

## 目标

冻结160/320控制/API/接收端合同，完成五种合法模式、模式切换、错误注入和长稳。

## 冻结接口

- `bandwidth_mhz` 作为历史字段名保留，但Stage 32只接受160/320。
- UI显示 `160 MS/s（约128 MHz可用）` 和 `320 MS/s（约256 MHz可用）`。
- 160支持TIME_ONLY/SPEC_ONLY/TIME_SPEC；320只支持TIME_ONLY/SPEC_ONLY。
- 2-bit硬件编码、UDP header、payload、端口和24 endpoint不变。
- REST status增加profile、SYSREF模式、MTS target/latency和half-band ID；不扩展UDP头。

## 验收

- 五种模式各10分钟。
- 160 TIME_SPEC、320 TIME_ONLY、320 SPEC_ONLY各1小时。
- 覆盖五种合法模式的PPS边界切换；发现偶发问题后改做3～5次针对性复测，
  不机械追求100次。
- 对PL可观察的ADC/RFDC `rfdc_ready`丢失，数字仿真必须立即停流并锁存
  `RFDC_NOT_READY`；PS驱动`Reset()`若不使ready下降，归类为维护动作，并要求
  fresh CONFIGURE/MTS和主机恢复门禁。
- Linux warm reboot后，通过UART日志观察启动，并且只使用Stage 32 profile、
  bitstream和固定MTS target恢复。
- 所有功能、切换和故障恢复通过后，最后按需要执行30分钟针对性soak；不再把
  8小时轮换作为当前单板开发闭合的硬门槛。
- 物理拔除10 MHz/PPS和真正断电重启已于2026-07-27实际执行；示波器波形证据仍
  属于`REMOTE-EVID-001`，不能用软件reset或数字状态冒充。

## 非目标

不声明双板物理相位同步。

## 测试、证据、版本

- UDP 接收主机：`astrolab@192.168.100.162`。
- 登录和sudo凭据只在运行时交互输入，不写入仓库、报告、脚本参数或命令日志。
- 32d..32f已完成接收机满速功能门禁；32g通过后开始本阶段长稳矩阵。
- T510的`/dev/ttyUSB1`已有持续UART记录器，warm reboot时只读取其日志，不抢占
  串口设备。
- Vivado `hw_server`当前没有枚举到hardware target，因此32h恢复不依赖USB JTAG。

## 远程执行拆分

32h按以下顺序执行，每一组单独生成汇总JSON；只有全部证据通过才把本报告改为
`PASS`：

| 子步骤 | 内容 | 当前状态 |
|---|---|---|
| 32h-a | 五种合法模式各10分钟 | `PASS` |
| 32h-b | 三个满线速组合各1小时 | `PASS` |
| 32h-c | PPS切换覆盖及320 SPEC针对性复测 | `PASS` |
| 32h-d | RFDC ready-low、reference fault和Linux warm reboot恢复 | `PASS` |
| 32h-e | 最终30分钟针对性soak | `PASS` |
| 32h-p1 | 活动流物理拔PPS和10 MHz | `PASS` |
| 32h-p2 | 真正整板掉电冷启动 | `PASS` |
| 32h-s | 示波器时钟波形证据，非单板功能release硬门槛 | `BLOCKED` |

新增`scripts/stage32h_remote_matrix.py`作为薄编排层。它只依次调用现有
`stage30_agent_client.py configure`和`stage32_agent_host_gate.py`，不增加控制
协议或数据格式；每项门禁自行STOP/flush，默认遇到第一项失败就停止，支持用已有
PASS JSON断点续跑。

编排器验证：

```bash
python3 -m py_compile scripts/stage32h_remote_matrix.py
python3 -m unittest discover -s tests -p 'test_*.py'
python3 scripts/stage32h_remote_matrix.py \
  --suite ten_minute --seconds 0.1 --tag dryrun \
  --output-dir <temporary-directory> --dry-run
```

结果：45个Python测试通过；dry-run正确展开五种合法模式，没有执行数据流。

五模式10分钟正式命令：

```bash
python3 -u scripts/stage32h_remote_matrix.py \
  --suite ten_minute --tag 20260726
```

汇总证据目标：
`../board/stage32h_ten_minute_summary_20260726.json`。

## 32h-a：五模式10分钟结果

执行时间为`2026-07-26T15:58:00+08:00`至`16:52:58+08:00`，五项全部
`PASS`：

| 模式 | 主机包率 | UDP payload | 非目标流 |
|---|---:|---:|---:|
| 160 TIME_ONLY | 625,038.53 pps | 41,602.564779 Mbit/s | SPEC=0 |
| 160 SPEC_ONLY | 625,025.60 pps | 41,601.703603 Mbit/s | TIME=0 |
| 160 TIME_SPEC | 625,003.81 + 624,988.64 pps | 83,199.497694 Mbit/s | N/A |
| 320 TIME_ONLY | 1,249,966.29 pps | 83,197.756484 Mbit/s | SPEC=0 |
| 320 SPEC_ONLY | 1,250,060.53 pps | 83,204.029099 Mbit/s | TIME=0 |

共同结果：

- 五项主机parse/kernel/ring/worker-ring/app drop和逐flow
  seq/frame/sample0 gap全部为0。
- 五项板端RFDC/science/TIME/SPEC/TX/route drop/error增量全部为0。
- 所有需要SPEC的模式中PFB/XFFT overflow、halt、TLAST、capture
  backpressure和coefficient error增量全部为0。
- 每一项都自动STOP，最终`stream_accepting=false`、`flush_clean=true`。
- `rx_steer_missed_packets`只作为T510白名单外背景帧警告保留。
- 320 SPEC_ONLY结束快照落在下一帧组装中的12/16 block；完整频谱发布率门禁已
  通过，不属于丢块。详见32g对该瞬时字段语义的说明。
- 160 TIME_ONLY的`tx_frames_sent`窗口差值再次出现异步快照归零，但接收机完整
  收包、FPGA built/drop和所有连续性计数正常；继续作为`TX-TELEM-001`在后续
  长时证据中对照，不把该易撕裂状态字段单独当作数据真值。

证据：

- 汇总：`../board/stage32h_ten_minute_summary_20260726.json`
- 汇总SHA256：
  `e6c7d090d6997903c861740754ab4fe7f05195f2d37b0600f70b036462adc0c1`
- 五项板端/主机完整JSON使用
  `../board/stage32h_ten_minute_*_20260726.json`及其`*_host.json`同名文件。

32h-a已`PASS`，板卡最终保持STOP，LMK双锁、固定MTS和QSFP正常，允许进入32h-b。

## 32h-b：三个满线速组合各1小时

正式命令：

```bash
python3 -u scripts/stage32h_remote_matrix.py \
  --suite full_line --tag 20260726
```

执行顺序固定为160 TIME_SPEC、320 TIME_ONLY、320 SPEC_ONLY；任一失败即停止，
每项结束自动STOP/flush。汇总证据目标为：
`../board/stage32h_full_line_summary_20260726.json`。

### 首轮执行与满载链路状态语义修正

首轮从`2026-07-26T16:54:59+08:00`运行到`18:56:59+08:00`：

- 160 TIME_SPEC 1小时`PASS`：TIME `624,999.13 pps`、SPEC
  `624,995.90 pps`，合计`83,199.668938 Mbit/s`；主机、FPGA和PFB/XFFT
  drop/gap/error均为0，STOP clean。
- 320 TIME_ONLY主机数据面1小时完整通过：收到`4,499,978,848`包，
  `1,249,994.12 pps / 83,199.608923 Mbit/s`，8个flow及全部主机和板端
  drop/gap/error为0；但严格门禁因开始和结束板端快照的`qsfp.link_up=false`
  判为FAIL，320 SPEC_ONLY按失败即停规则未运行。
- FAIL证据保留为
  `../board/stage32h_full_line_320msps_time_only_link_sample_fail_20260726.json`，
  对应主机PASS证据使用同名`*_host.json`，首轮汇总为
  `../board/stage32h_full_line_summary_first_fail_20260726.json`；板端FAIL文件SHA256为
  `d5b45d41aea9b68fa681b4e2898f110d5c718aa97b14bfef8dc8348a0b4b869c`。

RTL审计确认当前`rtl/t510_cmac_qsfp0.sv`把瞬时AXIS接收条件用于组合link状态：

```text
cmac_tx_ready = tx_axis_tready_raw && !usr_tx_reset
link_up = stable GT/CMAC/RX conditions && cmac_tx_ready && no faults
```

满速时主机PAUSE或CMAC反压可以让`tx_axis_tready_raw`在任意采样拍合法为0，不能
因此判物理断链。FAIL快照原始值`0x988cf00c`解码为：

- CMAC reset done、GT locked、module present、GT refclk seen、GT TX/RX reset
  done、RX aligned和RX status全部为1；
- local/remote fault、TX overflow、RX local/internal fault和TX local fault
  detail全部为0；
- 只有瞬时`tx_ready_sample=0`，从而使旧`link_up_sample=0`；
- STOP后`0x988df01d`中TREADY样本恢复，旧`link_up_sample`也恢复为1。

验收层因此增加`physical_healthy`：严格检查上述稳定GT/CMAC/RX条件和fault位，
保留原始`link_up_sample`；只有TREADY样本低时记录
`BOARD_QSFP_LINK_SAMPLE_LOW_DURING_BACKPRESSURE_*`警告，不判物理断链。主机
逐flow连续性、NIC物理drop/error和FPGA发送/drop仍全部保持严格门禁。该修正不改
bitstream、UDP、数据格式或运行时控制。

- 修正后47个Python测试通过。
- `stage32_agent_host_gate.py` SHA256：
  `52d203a707621632412d0c4b59c8484896316bafead62ed18a0362f744c505d8`
- `stage32h_remote_matrix.py` SHA256：
  `53ba823ac3980f4c46cefe8019c5273bd4c40c65ee8319b212c6d97085626f9c`

恢复命令使用`--resume`保留已PASS的160 TIME_SPEC，只覆盖失败的320 TIME_ONLY
证据，成功后继续320 SPEC_ONLY：

```bash
python3 -u scripts/stage32h_remote_matrix.py \
  --suite full_line --tag 20260726 --resume
```

### 最终结果

恢复执行在`2026-07-26T22:09:11+08:00`结束，三项全部`PASS`：

| 模式 | TIME包率 | SPEC包率 | UDP payload |
|---|---:|---:|---:|
| 160 TIME_SPEC | 624,999.13 pps | 624,995.90 pps | 83,199.668938 Mbit/s |
| 320 TIME_ONLY | 1,250,005.28 pps | 0 | 83,200.351733 Mbit/s |
| 320 SPEC_ONLY | 0 | 1,249,984.20 pps | 83,198.948648 Mbit/s |

共同结果：

- 三项主机parse/kernel/ring/app drop、逐flow seq/frame/sample0 gap和板端
  RFDC/science/TIME/SPEC/TX/route drop/error增量均为0。
- 两项SPEC路径的PFB/XFFT overflow、halt、TLAST、capture backpressure和
  coefficient error增量均为0。
- 每项结束后均STOP clean；320两项开始和结束的稳定GT/CMAC/RX条件全部健康，
  fault位全部为0。
- 320 SPEC_ONLY中的`tx_frames_sent`异步窗口差值为负，属于
  `TX-TELEM-001`；同一窗口主机完整收包、`tx_frames_built`正向增长且
  `tx_frames_dropped=0`，不改变无损结论。

证据：

- 最终汇总：
  `../board/stage32h_full_line_summary_20260726.json`
- 汇总SHA256：
  `24dcbe4541f8f17962f3c7d3c5b7c2f3f0033e52a8cd90d175e8cc6aa16297ad`
- 160 TIME_SPEC板端/主机SHA256：
  `4bdfe513fcdaa93d9cc0ef514b2bdbd39a69f8f6d060b6bb8b301bfeebc0f369` /
  `76680606f3c210f91c21daca29d4a98cb12986ccddf3e84a1d41a2f414419278`
- 320 TIME_ONLY板端/主机SHA256：
  `04c25d5bb630ec5f8d19a92f07f9c3702a6396020a087e2bb9d9f342efba02af` /
  `f4817a2a66fa1bf1e3cb5f5e2fbbb0ffcc170532a40753499811f18e8aadf677`
- 320 SPEC_ONLY板端/主机SHA256：
  `cd5ff182ffdb483f4e3acf2c5e9cd52e16efadbacf1cd8ff35d51016596c957b` /
  `2b05cf6083fbbd6df852f20ab6866d0b0bf5aad0c7ecbe10c022a2e4ab38f2eb`

32h-b已`PASS`。板端查询确认`streaming=false`、
`stream_accepting=false`、`flush_clean=true`，允许进入32h-c。

## 32h-c：PPS边界切换与320 SPEC针对性复测

原始发布级方案按160 TIME_ONLY、160 SPEC_ONLY、160 TIME_SPEC、320 TIME_ONLY、
320 SPEC_ONLY轮换，现按开发闭合范围缩减。每次仍必须验证：

- CONFIGURE后LMK双锁、固定MTS、profile与合法模式匹配；
- PREPARE和ARM使用未来PPS，commit计数等于目标PPS；
- generation匹配，160首样点满足`sample0 mod 8 = 4`，320满足
  `sample0 mod 4 = 0`；
- 所需TIME/SPEC首包均出现并持续增长，非目标流不启动；
- RFDC/science/TIME/SPEC/PFB/XFFT错误与drop不增长；
- 每次STOP后pipeline clean，不出现半包锁死。

先执行1次冒烟验证证据结构和时间预算；已有覆盖后只对失败路径做少量针对性复测。

新增编排器：

- `../../scripts/stage32h_pps_switch_campaign.py`
- SHA256：
  `8a0e9d0298803f79827c4eaa783f3c3cfd01678172a3cbc8e44efc22eb65834e`
- 本地`py_compile`、五模式dry-run和47个Python回归通过。

第一次真实冒烟保留为负向证据：PREPARE/ARM均成功，但编排器在PPS 45读取第二个
固定快照，而目标为PPS 47，因采样过早错误判FAIL；随后硬件实际在PPS 47正确提交，
STOP后pipeline clean。证据为
`../board/stage32h_pps_switch_001_160msps_time_only_20260726_smoke.json`。
编排器已改为持续轮询到commit或明确超时，再额外读取一次持续进展快照。

修正后的160 TIME_ONLY冒烟`PASS`：

- `actual_commit_pps_count`与目标PPS一致；
- `actual_first_time_sample0=32788`，满足`32788 mod 8 = 4`；
- 两个提交后快照之间TIME新增`5,147,243`包，所有drop/error增量为0；
- STOP后`streaming=false`、`stream_accepting=false`、`flush_clean=true`。

通过证据：
`../board/stage32h_pps_switch_001_160msps_time_only_20260726_smoke2.json`，
SHA256为
`19ac8ca2179b63d6600155857345904a3490d88e142079b87f2a11b46030c985`。

曾启动的发布级campaign使用独立generation范围，命令仅作为历史证据保留：

```bash
python3 -u scripts/stage32h_pps_switch_campaign.py \
  --tag 20260726 --iterations 100 --generation-base 3201000000
```

汇总证据目标为
`../board/stage32h_pps_switch_summary_20260726.json`。

正式campaign于`2026-07-26T22:31:05+08:00`启动，并在第15轮按失败即停规则
自动结束：

- 第1..14轮全部`PASS`，已经覆盖两轮完整五模式循环以及第三轮的
  160 TIME_ONLY、160 SPEC_ONLY、160 TIME_SPEC和320 TIME_ONLY；
- 第15轮320 SPEC_ONLY的PPS commit、首样点、SPEC包持续增长、RFDC/science/
  SPEC/TX drop和route error均正常，但两个提交后快照之间PFB
  `overflow_count: 2 -> 3`、`xfft_event_count: 2 -> 3`，因此判`FAIL`；
- STOP后`streaming=false`、`stream_accepting=false`、`flush_clean=true`，
  LMK双锁、固定MTS、QSFP和板端总错误标志正常。

汇总：
`../board/stage32h_pps_switch_summary_20260726.json`；第15轮证据：
`../board/stage32h_pps_switch_015_320msps_spec_only_20260726.json`。

根据当前开发阶段，不再机械追求100次。现有14次成功足以覆盖PPS事务和五模式
切换功能；第15轮的偶发PFB事件不能用更多重复次数冲淡，下一步改为少量、针对性的
“进入320 SPEC_ONLY”启动复测并定位该事件。32h-c保持`IN_PROGRESS`。

### 320 SPEC启动路径的针对性复现

只运行320 SPEC_ONLY的定时PPS启动：

```bash
python3 -u scripts/stage32h_pps_switch_campaign.py \
  --tag 20260726_320spec_targeted \
  --iterations 5 \
  --only-case 320_spec_only \
  --generation-base 3202000000
```

编排器同时加强为：CONFIGURE后的PFB/XFFT初始错误计数必须为0，不能只检查测试
窗口内增量。结果在第2轮按失败即停：

- 第1轮`PASS`，两个提交后快照之间新增`10,328,181`个SPEC包，所有PFB/XFFT
  错误和数据面drop均为0；
- 第2轮CONFIGURE和PPS commit前的快照中PFB/XFFT错误均为0；
- 第2轮第一个commit后快照出现`overflow=1`、`data_halt=19`、
  `xfft_event=1`和`xfft_tlast_missing=1`；8秒后的第二个快照错误数不再增长，
  同一测试窗口仍连续产生`10,331,233`个SPEC包且网络/FPGA drop为0。

证据：

- 汇总：
  `../board/stage32h_pps_switch_summary_20260726_320spec_targeted.json`
  （SHA256
  `0bb69edc320b410a0c635a81388d70255570b517712f388a944969a1d926ba1b`）；
- 第1轮：
  `../board/stage32h_pps_switch_001_320msps_spec_only_20260726_320spec_targeted.json`
  （SHA256
  `fa250453a5dfed303c71b8e89b7c7720d573e003482d41e3f21f73531ace557d`）；
- 第2轮：
  `../board/stage32h_pps_switch_002_320msps_spec_only_20260726_320spec_targeted.json`
  （SHA256
  `5add2c09180ca81008c3ec8a37825e09a6f1f0376b85a517c930696879980f8c`）。

作为对照，使用相同旧bitstream连续执行3次“重新CONFIGURE后立即启动”320
SPEC_ONLY板端+主机5秒门禁，3/3均`PASS`：

- 每次开始快照的PFB/XFFT错误均为0；
- 每次PFB处理约114万帧，所有PFB/XFFT错误增量为0；
- 主机SPEC流、板端数据面及STOP/flush门禁均通过。

对照证据为
`../board/stage32h_320spec_immediate_{1,2,3}_20260726.json`及其
`*_host.json`；三份板端JSON的SHA256依次为
`051c0281ac8ba5f1a89d191447cd12432abb78a031e9635df781e5e4894a42d8`、
`6b696eecd45c5a29578a8ad03f7dff876ad0b5934ab2b75ac28166fbfbec99ec`和
`a88bf66c0863f7b05773a209fb7f47899d1e1f5fe79b76efe431875249de08c0`。

这组A/B证据把异常隔离到定时PPS启动时的“XFFT先配置、随后空闲、最后放行
SPEC”序列，而不是320 MS/s持续吞吐、UDP发送或PFB稳态处理。定时启动会在目标
PPS复位epoch/XFFT，再等待`first_sample0=32768`，即约`102.4 us`，才打开SPEC；
立即启动不存在这段配置后的空闲窗口。

### 候选RTL修复和离线门禁

在`rtl/pfb_channelizer.sv`的Stage 32分支内，将8路realtime XFFT的配置握手延后
到`enable`有效后执行。输入CDC FIFO可吸收配置所需的少量时钟，因此不需要修改
PFB算法、FFT参数、UDP格式、端口、payload或控制协议。非Stage 32编译路径保持
原行为。

同步更新`sim/tb_pfb_channelizer.sv`，明确验证：

- SPEC未使能时XFFT保持未配置、science-valid保持低；
- SPEC使能后8路配置握手全部完成，science-valid再放行；
- Stage 32 PFB入口仍保持每4个PFB时钟接收一个1024-bit字，不恢复旧的第5个空拍。

离线结果：

- `tb_station_sync_scheduler`、`tb_pfb_channelizer`、
  `tb_t510_fengine_top_smoke`和`tb_t510_fengine_board_top`全部`PASS`；
- 47个Python单元测试全部`PASS`；
- `git diff --check`通过；
- `rtl/pfb_channelizer.sv` SHA256：
  `96af96658ac91c31608f77735a765f5f69d89e1d599abaa013267cdb93196c8d`；
- `sim/tb_pfb_channelizer.sv` SHA256：
  `cd70c139c115e5920b927426b916ff9dec66ce2fcf7aa869a29e6ae18ab14ee6`；
- 加强后的PPS编排器SHA256：
  `153ecab17c09bfaeb5c0be7fa98b58ce0f28a64b03b668f75b0376e55ffde9f5`；
- 加强后的板端/主机门禁SHA256：
  `e793665f546f7e8744fe6fe7a28411b7d567496b7759efbcc9f4548b9059d30b`。

2026-07-26已通过attach的Vivado GUI启动非阻塞
`synth_1 -> impl_1 -> write_bitstream`构建链，启动后`synth_1`状态为
`Running synth_design...`。构建链脚本为
`../../tcl/stage32h_xfft_startup_build_chain.tcl`，SHA256为
`1e2a706afccdbe61030abb6ab1f865b3d3e451e7ba51cc6b70b0fcb421fdb2e0`。
本报告此时不等待构建，也不把旧bitstream当作新修复版本；只有用户确认GUI显示
新`write_bitstream`完成后，才检查时序/DRC/bit SHA并继续板端复测。

该修复在新bitstream完成并通过板端定时PPS复测前仍属于“候选修复”，不能据离线
仿真把32h-c改为`PASS`。

### 定时启动后第10秒的单帧尾块缺失

XFFT reset-gate候选bitstream解决了定时启动时的PFB/XFFT事件，板内定时启动测试
能够持续打流且PFB/XFFT/drop计数均为0。随后320 SPEC_ONLY的60秒主机门禁仍发现：

- flow 8～22各出现一次`seq/frame delta=15`；
- flow 23出现一次`seq/frame delta=31`；
- 事件前最后一组为flow 23、`seq=12,498,847`，事件后第一组为flow 8、
  `seq=12,498,863`；
- 因而不是NIC或主机漏收，而是一个4096-channel PFB帧少输出了最后的
  `chan0=3840`、256-channel block；
- 同一窗口约`1.250 Mpps / 83.22 Gbit/s`，NIC/kernel/ring/app drop和板内
  PFB/XFFT/drop计数均为0。

诊断接收机只在既有REST JSON内增加最近一次SPEC gap的前值、后值和delta，不改变
UDP协议或接收判定。证据为：

- `../board/stage32h_pps_switch_001_320msps_spec_only_xfft_reset_gate_gapdiag60.json`
  （SHA256
  `11e9e29ed514efb1cebb24ce4843335872f8e5dbe3f04f787224d4a77430497d`）；
- `../board/stage32h_pps_switch_001_320msps_spec_only_xfft_reset_gate_gapdiag60_host.json`
  （SHA256
  `342c179df603bf486e5ed02ff9158844ea541754d93256f047f5c5e57c039ca8`）。

事件所在PFB frame约为`781,178`，对应observation sample0约
`3,199,737,856`，即启动后`9.9992 s`，恰好在第10个PPS边沿之前。Stage 32
`t510_fengine_board_top`原先把`pps_recent`门限设为恰好
`80,000,000 / 80 MHz = 1 s`。外部PPS与ADC AXIS时钟的有限相位/频率误差会使
`pps_recent`在健康PPS到达前短暂变低；scheduled路径把该状态直接门控到
`streaming/PFB enable`，从而截断正在处理的FFT帧。立即启动路径不使用该scheduled
门控；同一bitstream的20秒立即启动对照为PASS且没有新增gap：
`../board/stage32h_320msps_spec_only_xfft_reset_gate_immediate_gapdiag20_host.json`。

最小修复只把Stage 32的PPS recent门限改为`100,000,000`个80 MHz周期，即
`1.25 s`：

- 正常PPS获得25%边沿容差，不再在每秒边界误停流；
- 真正漏掉一个PPS时，仍在预期PPS之后约250 ms停流；
- LMK、RFDC、PFB算法/系数、UDP header/payload、flow、端口和REST控制语义均不变。

修复后的离线门禁：

- `tb_station_sync_scheduler`：PASS；
- `tb_pfb_channelizer`：PASS；
- `tb_t510_fengine_top_smoke`：PASS；
- `tb_t510_fengine_board_top`：PASS；
- receiver Rust tests：`36 / 36 PASS`；
- `git diff --check`：PASS。

下一候选构建使用
`../../tcl/stage32h_pps_recent_guard_build_chain.tcl`。新bitstream完成并通过定时PPS
的320 SPEC_ONLY板端/主机复测前，32h-c继续保持`IN_PROGRESS`。

### PPS recent guard最终构建和板端闭合

用户确认Vivado GUI完成后，attach会话中`synth_1`和`impl_1`均为100%，
`impl_1 STATUS=write_bitstream Complete!`。最终候选：

- bitstream SHA256：
  `439080046408267493a031efa1d097fcd3c2f818850ee9eac1925ae95d6b094c`；
- fully routed：`274680 / 274680`，routing errors为0；
- WNS/WHS：`+0.081 / +0.009 ns`，setup/hold failing endpoints均为0；
- DRC和Methodology的Error/Critical Warning均为0；
- 实现归档：
  `../vivado/stage32h_pps_recent_guard/build_summary.md`。

该bit被固化到release
`stage32-pps-recent-guard-20260727`并fresh-download到板卡。随后只运行3次
针对性的定时PPS 320 SPEC_ONLY板端/主机测试：

| 次数 | 接收窗 | SPEC包率 | UDP payload | 结果 |
|---|---:|---:|---:|---|
| 1 | 60 s | 1,250,589.6 pps | 83,239.243776 Mbit/s | PASS |
| 2 | 20 s | 1,250,713.6 pps | 83,247.497216 Mbit/s | PASS |
| 3 | 20 s | 1,250,713.6 pps | 83,247.497216 Mbit/s | PASS |

共同结果：

- 每次都重新CONFIGURE/fresh-download，不复用前一轮PFB/XFFT状态；
- 固定ADC/DAC MTS target为`230/336`，4 tile测量值各自一致且不超过target；
- 板端RFDC/science/SPEC/TX/route drop/error增量均为0；
- PFB/XFFT overflow、halt、TLAST和backpressure增量均为0；
- 16个SPEC flow的`spec_seq_gaps/spec_frame_gaps`全部为0，新增诊断的最近
  gap字段均为`null`；
- 每次结束均STOP，`stream_accepting=false`、`flush_clean=true`。

证据：

- 60秒汇总：
  `../board/stage32h_pps_switch_summary_pps_recent_guard_host60.json`
  （SHA256
  `49d0164399226173867ec905bc84ab2f03ccbf3e74f9686b83ac6c60876ab3bd`）；
- 两次20秒汇总：
  `../board/stage32h_pps_switch_summary_pps_recent_guard_repeat20.json`
  （SHA256
  `672c5d9325c9f1657794732889eac167ff1a04fec80669f5cc7ddc974b1720d8`）。

因此原第10个PPS前截断一个PFB frame的问题已经由PPS recent guard修复并取得
3/3板端/主机证据，32h-c改为`PASS`。

## 32h-d：RFDC fault和Linux warm reboot恢复

### RFDC驱动动作的负向结果

使用`../../scripts/pynq_stage32_rfdc_reset_fault.py`在已提交并持续运行的预约
320 TIME_ONLY流上，对4个ADC tile和4个DAC tile依次调用驱动`Reset()`。诊断脚本
最终SHA256为
`28894fcb6816bacd7437a7524c6de8309e66d6abea5d239f5633795ae0a6bbb9`；
它会逐tile保存调用结果，并在单个`StartUp()`失败时继续尝试恢复其余tile，保证
负向测试也能留下完整JSON。对板卡的首次实际测试发生在该健壮性修订之前，以下
现场JSON和状态快照保持原始证据不改写：

- 8/8调用均成功返回；
- 后续2秒、约100 ms间隔的21个快照中，`rfdc_ready`始终为true；
- 调度器保持STREAMING且无`RFDC_NOT_READY`，TIME包持续增长。

这说明当前RFDC驱动/硬件组合的`Reset()`是快速自恢复动作，没有在PL的
`all_adc_valid`上产生可观察低电平。该结果不能冒充“故障后自动停流PASS”。
负向证据：
`../board/stage32h_rfdc_reset_fault_20260727.json`
（SHA256
`f666f7b43de0e9e0505e7ef5f89e42a11b643bebd8446b748c2ce0343a66df24`）。

进一步尝试驱动公开的`ShutDown()`/`StartUp()`：

- 8个tile进入`ShutDown()`后，ADC0的`StartUp()`在RFDC restart-clear状态超时；
- 紧接着的Agent状态快照仍显示`rfdc_ready=true`、预约流继续前进，没有锁存
  `RFDC_NOT_READY`；
- 因脚本异常中止，立即执行正式fresh CONFIGURE，重新下载相同bit并重建
  LMK/RFDC/MTS，没有让板卡长期停在该状态。

现场快照：
`../board/stage32h_rfdc_shutdown_live_status_20260727.json`
（SHA256
`4cc78da67201272482847d6ec8e7b42b374033b33b1b89b11586f03884421e3a`）。

恢复后的320 TIME_ONLY板端/主机20秒门禁为PASS：

- `1,251,135.2 pps / 83,275.558912 Mbit/s`；
- 8 flow的sequence/frame/sample0 gap和主机drop均为0；
- 板端所有drop/error窗口增量为0，最终STOP clean。

恢复证据：
`../board/stage32h_rfdc_fault_recovery_320_time_20s_20260727.json`
（SHA256
`13315f68332a5aa3f10f6bd1e6b406a3fed16596b9ee644b545d823b5cd046f7`）。

当时结论是“RFDC动作后的正式恢复”已通过，但驱动动作没有制造出PL可观察的
ready-low，因此不能证明或否定调度器的RFDC故障分支。后续闭合候选为：

1. 现场物理断开10 MHz/PPS或使用可控参考源制造真实失锁；或
2. 新增受控RTL fault/status注入，再生成bitstream验证调度器错误门控。

第2项会引入新RTL和新bitstream，超出本轮最小改动验证，未自动启动。

### Linux warm reboot：PASS

板卡在STOP clean状态执行Linux warm reboot：

- boot-id从`f3cd9b72-a4ce-41fe-bdac-6ba5df086c5e`变为
  `71219781-9c20-4540-9174-ba6750344aca`；
- UART持续记录器捕获systemd shutdown、`reboot: Restarting system`、
  U-Boot 2022.01、ZynqMP和Linux 5.15启动；
- 当前release仍为`stage32-pps-recent-guard-20260727`；
- Agent自动恢复；配置前`/status`按安全策略返回
  `PL_NOT_CONFIGURED`/HTTP 409，没有沿用旧PL状态打流；
- Jupyter恢复为active。

UART和启动证据归档在
`../board/stage32h_warm_reboot_20260727/`。

随后使用相同release重新执行完整CONFIGURE、固定MTS和预约PPS 320 SPEC_ONLY：

- 20秒SPEC `1,250,713.6 pps / 83,247.497216 Mbit/s`；
- 16 flow无sequence/frame gap，主机和板端drop/error均为0；
- PFB/XFFT错误增量为0，结束STOP clean。

汇总：
`../board/stage32h_pps_switch_summary_warm_reboot_recovery_host20.json`
（SHA256
`b87f6edbbfe4d7ba44ec98cce01c7b8134475eefb172ecbb11413df08282cfea`）。

Linux warm reboot子项判定为`PASS`。本次测试当时尚未补齐
`rfdc_ready`数字故障覆盖；最终结论以后文“RFDC ready-low数字门禁”为准。

最终一致性审计中，诊断脚本通过`py_compile`，仓库Python单元测试
`48 / 48 PASS`，`git diff --check`通过。板端只读状态确认当前catalog bit SHA256为
`439080046408267493a031efa1d097fcd3c2f818850ee9eac1925ae95d6b094c`，
`streaming=false`、`stream_accepting=false`、`flush_clean=true`，LMK双锁、
固定MTS和QSFP link均保持正常；未启动新的Vivado构建或soak。

### 首次物理断开10 MHz/PPS：空闲态证据

现场现在可以操作板卡。操作员在板卡已经STOP的前提下同时断开外部10 MHz和PPS，
`2026-07-27T09:25:14+08:00`的只读快照显示：

- LMK `pll1_lock=0`、`clock.configured=false`，证明外部10 MHz丢失可由时钟控制
  层检测；
- LMK `pll2_lock=1`，这是内部VCO环仍锁定，不代表外部参考仍存在；
- 调度器`pps_recent=false`，证明PPS丢失可见；
- `streaming=false`、`stream_accepting=false`、`flush_clean=true`；
- PL侧`ref_locked=true`，说明该字段不是LMK PLL1失锁的直接镜像。

证据：
`../board/stage32h_physical_ref_disconnected_idle_20260727.md`。

该次操作发生在停流状态，因此只能关闭“物理故障是否可见”的疑问，尚不能证明
活动流能自动停下。下一步必须先恢复10 MHz/PPS并确认锁定，然后在预约流活动期间
分别断开PPS和10 MHz，不能把两种故障同时注入，否则无法判断是哪一个门控生效。

### 活动流物理断PPS：PASS

新增`../../scripts/stage32h_physical_fault_gate.py`。PPS测试时revision的SHA256为
`5699d442bc66beb5364cb3624d595807b6b315f695c31353511103b0cbc70b81`；
加入PS watchdog证据解析后的最终SHA256为
`61db0ca4340dcd14092fba0382743fecae01792d29f6cf0bec3c2e4aa2ed7a54`。
它只复用现有CONFIGURE、PREPARE、ARM和STOP接口：重新加载同一个Stage 32 bit，
固定MTS后预约启动320 TIME_ONLY，提示操作员断线并记录约100 ms粒度的状态时间线。
它不改RTL、REST或UDP合同。

第一次准备尝试使用5个PPS提前量，因stateless helper启动耗时而被Agent安全拒绝：
请求到达时`target_pps_count=17`、当前已经为20，没有ARM或打流。该负向配置证据
保留为
`../board/stage32h_physical_pps_fault_20260727.json`
（SHA256
`8ba79fddd413548799cb56729fcd6af1bb30b774e610ba7712f5e675e8cea6a3`）。
脚本默认值随后固定为与既有campaign相同的35个PPS。

正式测试generation为`3203201002`。活动流稳定后，操作员只断开PPS、保持10 MHz：

- LMK PLL1/PLL2始终为`1/1`，排除误断10 MHz；
- 调度器在`pps_recent=false`的同一快照进入`state=6`；
- 自动置`streaming=false`、`stream_accepting=false`；
- 锁存`error_code=7 / pps_not_recent`；
- TIME包计数停止在`307,812,372`，后续约8秒不再增长；
- RFDC/science/TIME/TX drop均未增加，最终STOP后`flush_clean=true`。

证据：
`../board/stage32h_physical_pps_fault_pass_20260727.json`
（SHA256
`7b1f9d9c44c56e02d60b5bea7fe26f087841fc20b6595fbb064d940906e2c858`）。

物理PPS故障自动停流判定为`PASS`。

### 活动流物理断10 MHz：FAIL并定位根因

恢复PPS并确认recent后，generation `3203201003`再次预约启动320 TIME_ONLY。
操作员只断开10 MHz、保持PPS：

- LMK `pll1_lock: 1 -> 0`、`clock.configured=false`，物理失锁已被PS侧SPI
  寄存器`0x182`明确检测；
- PLL2保持1，这是内部VCO/分配路径仍在运行；
- PPS保持recent且计数前进，排除PPS门控干预；
- PL的`ref_locked`始终为true，调度器保持`state=5 / streaming=true`；
- 没有锁存预期`error_code=5 / ref_unlocked`；
- 在首次观测PLL1失锁后，TIME仍增加`9,474,926`包，随后测试脚本主动STOP；
- 主动STOP后`streaming=false`、`stream_accepting=false`、`flush_clean=true`。

证据：
`../board/stage32h_physical_10mhz_fault_20260727.json`
（SHA256
`8fd20c88d95ccc1fd569727c811f25cd9ea6067cb206a26ebb184d1bb1c4b309`）。

RTL审计确认当前board top中：

```systemverilog
wire ref_chain_locked = data_rst_n && all_dac_ready;
```

该信号只说明PL/RFDC数据时钟和DAC ready仍存在，不代表LMK PLL1锁定。现有T510
顶层/XDC只有LMK reset、CLKin选择和SYNC控制，没有LMK `STATUS_LD1/LD2`输入；
板端也只导出了对应PS GPIO 29、33、34和78。PLL1状态目前只能由PS通过LMK SPI
寄存器读取。LMK进入holdover且PLL2继续工作时，PL不会自动知道外部10 MHz已经
丢失，这正是本次FAIL的根因。

因此不采用“重复测试”或soak冲淡该结果。闭合10 MHz fault-stop需要二选一：

1. 增加常驻PS reference watchdog，直接低延迟轮询LMK `0x182`，只在预约流活动
   时于连续失锁后直接写现有STOP寄存器，并保留持久故障证据；无需新bitstream；
2. 硬件改线，把LMK `STATUS_LD1`实际接入一个可用FPGA引脚，再新增同步器并送入
   scheduler `ref_locked`；这是最直接的PL方案，但需要原理图确认、板级改线、
   XDC/RTL和新bitstream。

只用PPS与PL时钟周期差估算失锁不能等价于LMK lock detect：holdover频率可能在
短时间内非常接近原频率，无法保证及时、确定地检测，故不作为发布门禁修复。

### PS reference watchdog：实现、部署和CONFIGURE互斥

已选择上述第1种方案，不修改RTL、bitstream、UDP或REST合同。最终板端release为
`stage32-ref-watchdog-r2-20260727`。当前通用的PYNQ安装、逐板配置与多板部署方法
见 `../../docs/t510_pynq_deployment.md`。

实现组成：

- `python/t510_clock.py`增加最小只读`read_lock_status()`，只读LMK
  `0x182/0x183`；
- 新增常驻root服务`python/t510_ref_watchdog.py`和
  `t510-ref-watchdog.service`；
- watchdog每100 ms读取一次PLL1/PLL2，活动流中连续2次失锁即直接调用现有
  STOP/flush；连续5次SPI读取失败也fail-safe STOP；
- `/run/t510-stage32-ref-watchdog.json`原子记录PL身份、generation、包计数、
  故障原因、停止延迟和flush结果；
- `t510_hw.py`在START和ARM前检查状态年龄、双锁、bit身份和fault latch，任一
  不满足均返回`REFERENCE_WATCHDOG_NOT_READY`；
- 故障接回后不自动恢复打流；只有fresh CONFIGURE更新PYNQ bit timestamp并完成
  RFDC/MTS，watchdog才清除fault latch；
- Board Agent capabilities声明`automatic_stop=true`和watchdog状态路径，不向
  UDP header增加字段。

最初`r1` release部署后服务本身健康，但CONFIGURE与watchdog的PYNQ/MMIO轮询没有
跨进程互斥，连续两次CONFIGURE均使ADC0 `XRFdc_Reset`停在state 6。两次失败发生
在PREPARE/ARM和打流之前，板卡保持STOP，原始证据为：

- `../board/stage32h_physical_10mhz_watchdog_configure_attempt1_fail_20260727.json`
  （SHA256
  `76048cb44e217dc6c847150d7b66a9ae89c9b9622d7438279edb68a2d0d28b3f`）；
- `../board/stage32h_physical_10mhz_watchdog_configure_attempt2_fail_20260727.json`
  （SHA256
  `bef11a05f2a2de87c2c30ad233e85e7c6712d7249ae1291f5973f49c568b2a34`）。

`r2`增加`/run/t510-stage32-configure.lock`：CONFIGURE持有独占`flock`，
watchdog每次硬件轮询持有共享锁。配置期间watchdog持续写新鲜的
`CONFIGURE_PAUSE/CONFIGURE_IN_PROGRESS`状态但不访问PL/SPI；配置结束后根据新
timestamp重新连接。现场实际观察到CONFIGURE全程进入`CONFIGURE_PAUSE`，RFDC和
固定MTS随后正常完成。第三次验证的配置、PREPARE和ARM均成功，之后因测试脚本把
合法的`last_fault=null`误转为字典而在断线提示前退出；没有注入故障，最终STOP
clean。该脚本负向证据保留为
`../board/stage32h_physical_10mhz_watchdog_script_attempt3_fail_20260727.json`
（SHA256
`8b032a0c15d6a054c2a7c9b61d72da047f3ae07a142b37106f51fb33d8313a14`）。
修正nullable解析后，22项watchdog/helper单元测试和`git diff --check`通过。

最终不可变release关键SHA256：

| 文件 | SHA256 |
|---|---|
| Agent | `80ef09b1b193d805f76a2f3f258ffc67d64e86a3c9d0e00ab4346122c2495fd0` |
| `t510_hw.py` | `847fb219170d2e63cddf8f5a06bcc994a0e8907b762b7e1773e3ef5a7e0769f6` |
| `t510_ref_watchdog.py` | `565e103f7ee980bcfa50ce7cbf506c65f636caa3380ca539979684d0b21204e5` |
| `t510_clock.py` | `d5dfcc44afdb9df2f9c92c5bf9bdb933f46d558b8d81ec52ee887bfe64a65406` |
| watchdog unit | `fc701ae64aa9bbd7f0936fcd39ade7f0ab8926ccc285d0c75ce74ead5bc81274` |

### 活动流物理断10 MHz：watchdog修复后PASS

最终测试generation为`3203201007`。预约320 TIME_ONLY稳定运行后，只断开10 MHz、
保持PPS：

- watchdog通过LMK SPI看到`PLL1=0`、`PLL2=1`，PPS始终recent；
- 两次确认后锁存`LMK_PLL1_UNLOCKED`；
- 故障前记录generation `3203201007`、scheduler state 5和TIME packet
  `133,547,641`；
- 直接写现有STOP后，PL确认停止延迟为`0.257 ms`；
- `streaming=false`、`stream_accepting=false`、`flush_clean=true`；
- PL scheduler没有伪造`ref_unlocked`错误码；自动停止和错误证据来自PS
  watchdog，符合本方案分层；
- RFDC/science/TIME/TX drop均未增加。

证据：
`../board/stage32h_physical_10mhz_watchdog_pass_20260727.json`
（SHA256
`d3c97b95dda0db6938f2a1cc29e912137fe8d9a7196e56f3ad3a9a77f0953dde`）。

10 MHz接回且PLL1/PLL2恢复`1/1`后，未fresh CONFIGURE时直接START仍返回HTTP 409
`REFERENCE_WATCHDOG_NOT_READY`，错误只剩`NOT_HEALTHY/FAULT_LATCHED`，证明接线
恢复不会自动重新打流。

随后执行fresh CONFIGURE/MTS：

- CONFIGURE耗时`8348.44 ms`；
- watchdog fault latch清除并恢复`IDLE/healthy`；
- ADC latency保持`[230,230,230,230]`、target 230；
- DAC latency不超过固定target 336；
- 板卡保持STOP、PPS recent、pipeline clean。

证据：
`../board/stage32h_watchdog_recovery_configure_20260727.json`
（SHA256
`149c6abacd5fa958012aa88f018cbf4d2a0674fc6163a1f70b062bcadafaed29`）。

恢复后的320 TIME_ONLY板端/接收机20秒门禁也为PASS：

- 主机收到`25,017,248`个TIME包，`1,250,862.4 pps /
  83,257.401344 Mbit/s`；
- 8个TIME flow的sequence/frame/sample0 gap均为0；
- 主机parse/kernel/ring/worker-ring/app drop增量均为0；
- 板端RFDC/science/TIME/SPEC/TX/route drop增量均为0；
- QSFP物理状态健康，结束后自动STOP/flush clean。

板端/主机证据：

- `../board/stage32h_watchdog_recovery_320_time_only_20s_20260727.json`
  （SHA256
  `79e2256387e43ee11aa1f0540dfca4f33d5de736a8a077f1d43c65877ff73343`）；
- `../board/stage32h_watchdog_recovery_320_time_only_20s_20260727_host.json`
  （SHA256
  `5484cac9910b629ace6e0e2856606a526d536baf3f94ddcf363115d5401f6c77`）。

因此活动流PPS和10 MHz两种物理参考故障自动停流均已`PASS`，32h-p1改为
`PASS`。真正整板断电和示波器波形仍属于`REMOTE-EVID-001`，单独保持
32h-p2 `NOT_STARTED`和32h-s `BLOCKED`；其中示波器证据不作为当前单板功能
release的硬门槛。

### RFDC ready-low数字故障门禁：PASS

经用户确认，Stage 32采用最小改动的信号合同闭合方式，不新增RTL fault-injection、
不生成新bitstream。详细报告与归档XSim日志：
`../vivado/stage32h_rfdc_ready_fault_gate/verification.md`。

源码审计确认：

- 板顶层`all_adc_valid -> rfdc_ready_in`，它表示ADC science链是否可提供有效
  TIME/SPEC输入；
- `t510_fengine_top`把`rfdc_ready_in`同时作为STREAMING组合门控和
  `station_sync_scheduler.rfdc_ready`输入；
- 调度器从ARMED到STREAMING任一状态看到ready低，下一拍清除armed/streaming、
  进入ERROR并锁存`RFDC_NOT_READY / code 6`；
- DAC ready通过`all_dac_ready -> ref_chain_locked -> ref_lock_in`门控；DAC是
  校准/自环激励源，不是外部科学ADC输入，不能要求不影响ADC validity的DAC维护
  调用必然停止TIME/SPEC。

此前testbench把`rfdc_ready`常量绑为1。本次只修改
`sim/tb_station_sync_scheduler.sv`，在预约流已经STREAMING后拉低ready，并证明：

1. 下一拍`state=ERROR(6)`、`error_code=RFDC_NOT_READY(6)`；
2. `armed=0`、`streaming=0`；
3. status报告RFDC not-ready和latched error；
4. ready恢复后仍保持ERROR，不自动重启；
5. 只有显式ABORT才回到IDLE并清错。

执行命令：

```bash
T510_XSIM_WORK_DIR=/home/astrolab/demo-ant/.xsim_batch/stage32h_rfdc_ready_fault_gate \
  scripts/run_xsim_batch.sh tb_station_sync_scheduler
```

XSim 2022.2结果：

```text
[350000] PASS: tb_station_sync_scheduler
INFO: all XSim batch testbenches passed
```

归档日志：
`../vivado/stage32h_rfdc_ready_fault_gate/tb_station_sync_scheduler_xsim.log`
（SHA256
`070f136a32061119ebb9c324699c89d307b41474a09343acdca62feccf28c9e5`）。
testbench SHA256为
`0258cbafc1e17b3793f34e82c69f4915edbd794278aceccdf48915f88d14e1c5`。
58项Python回归和`git diff --check`同时通过。

因此板端`XRFdc_Reset()/ShutDown()`重新分类为“没有拉低
`all_adc_valid/rfdc_ready`的驱动维护动作”，而不是“RFDC故障保护失败”。它们的
恢复仍由已有fresh CONFIGURE/MTS和20秒无损主机门禁证明。对PL可观察的ADC/RFDC
validity loss，数字自动停流和fail-closed已经闭合；32h-d改为`PASS`。

## 后续顺序

1. PS watchdog、物理10 MHz/PPS fault-stop和RFDC ready-low数字门禁均已闭合。
2. 真正整板断电冷启动已经`PASS`：服务自动启动、配置前fail-closed、fresh
   CONFIGURE/MTS和20秒主机恢复均通过。详细证据见
   `../board/stage32h_cold_boot_20260727.md`。
3. 最终30分钟针对性soak已经`PASS`：160 TIME_SPEC、320 TIME_ONLY和320
   SPEC_ONLY各10分钟。详细证据见
   `../board/stage32h_final30_soak_20260727.md`。
4. 示波器时钟质量继续作为`REMOTE-EVID-001`延期，不阻止当前单板功能release，
   也不与双板同步结论混合。

soak只用于观察低概率、随时间积累或温度相关的问题，不用于代替功能和故障恢复
门禁。由于32h-a和32h-b已经累计接近4小时满速测试，当前不再要求8小时轮换。

## 失败处置

立即停流并保存当前Stage 32的clock/MTS/packet/drop状态；修复后从LMK lock、
匹配Stage 32 bitstream和固定MTS target重新开始，不使用范围外release替代验收。

## 下一阶段准入

既有32h-c、32h-d、32h-e、32h-p1和32h-p2证据仍为`PASS`。此前把
`DAC_Data_Type=0`判成PL real输入是错误假设，已经撤回；后续direct raw preview
与完整fresh CONFIGURE证明标准正向DDS候选的160/320频率方向正确，32h2已
`PASS`。32h3的频谱仪9项矩阵和两项修复后60秒满速回归也已`PASS`，Stage 32
单板release重新闭合。`32i`仍保持`BLOCKED`，总体Stage 32继续为
`IN_PROGRESS / BLOCKED_BY_HARDWARE`。
