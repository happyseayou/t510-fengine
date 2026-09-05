# Stage 33：ADC/DAC 3.84 GS/s 与第一 Nyquist 完整频带

## 当前状态

`IMPLEMENTED / OFFLINE_PASS / VIVADO_PASS_WITH_LICENSE_WARNING / MTS_40X40_PASS / LATEST_PROMOTED / RELEASE_DEPLOYED / PRODUCTION_60S_PASS / RF_PARTIAL / DAC_ONE_SAMPLE_SSA_80_940_IMAGE_PASS / ADC_EXTERNAL_TG940_GATE_PASS / ADC_FIXED_SPUR_STAGE33A / DAC_SAMPLING_IMAGE_2900_CONFIRMED / UNFILTERED_DAC_ADC_LOOPBACK_IM3_CONFIRMED / HOST_8089_MEMORY_SOAK_PASS / RECONSTRUCTION_FILTER_REQUIRED / DAC_PURITY_MULTI_POINT_PENDING`

Stage 33 是当前 `demo-ant.xpr` 对 Stage 32 成果的原位升级，不是独立工程。Stage 32
已经闭合的数据面——ADC adapter、160/320 MS/s选择器、1024-bit science bus、
4-tap PFB、TIME/SPEC CMAC512、调度同步、DAC DDS和Rust接收格式——全部保留；
本阶段把 ADC和DAC模拟采样率提升到3.84 GS/s，使第一 Nyquist区间扩展到
`0..1.92 GHz`。

当前正式bit为DDS LUT修复发布版，bitstream SHA为
`23c3eb507558820e786dd7247b6b43a59a2f3141ed3599d1f6655f19de5dd3da`。它在当前工程
完成`synth_1 -> impl_1 -> write_bitstream`，fully routed，WNS/WHS为
`+0.062/+0.010 ns`，catalog MTS target保持`452/88`，顶层`overlay/`、117开发板和
162接收机均使用该正式版本。DDS LUT修复使100 MHz回环的部分20 MHz齿下降约
`7.59..10.24 dB`；直接频谱仪测得DAC端除200 MHz外的栅格为
`-84.88..-91.26 dBc`，足以用于功能回环，但不作为高动态范围纯度源。

Stage 33a已经以
`TERMINATED / ACCEPTED_WITH_KNOWN_LIMITATIONS / NO_PRODUCTION_MITIGATION`终止。
ADC的480/960/1440 MHz固定项为`-93.95..-82.64 dBFS`，最坏约2.42 ADU；普通宽带
和时域采集可用，三处邻近bin不用于无条件长积分弱谱线或互相关。因此Stage 33继续
保持`RF_PARTIAL`，但既有3.84 GS/s、吞吐、协议、同步和功能回环能力均保持有效。

## 冻结硬件合同

- `CORE_VERSION=0x00010033`，当前 RTL 无 `T510_STAGE*` 条件编译分支。
- 四个 ADC tile和四个 DAC tile全部为 `3.84 GS/s`。
- 八个物理 ADC converter：12x decimation、R2C fine mixer、dither enabled、
  Nyquist zone 1；RFDC metadata对应16条 derived R2C AXIS路径。
- 八路 DAC：12x interpolation、C2R fine mixer、Nyquist zone 1。
- RFDC复基带保持 `320 MS/s`；ADC/DAC AXIS保持 `80 MHz`，ADC width=4、
  DAC width=8。
- 时钟序列保持160 MHz RFDC reference和10 MHz continuous SYSREF，不修改寄存器
  顺序。
- ADC NCO=`-center`，DAC NCO=`+center`；自定义 DAC DDS输入率仍为320 MS/s。
- `sample0` 继续以320 MS/s复基带时基解释，不能按3.84 GHz模拟采样率解释。

生成的当前 RFDC 合同已通过 XCI/HWH 检查：

- RFDC XCI SHA-256：
  `3bc3b81a2d73cd3b8e968e385804556cb203def6adc5ac3b3a09dbb58ede2908`
- HWH SHA-256：
  `0cf961ddd44c026216cdf5376980552a308dfbfe4da61b838f25b64f92580f8a`

## 第一 Nyquist 频率合同

| 复采样模式 | center范围 | 允许输出模式 | 单路DAC/期望RF带内约束 |
| ---: | ---: | --- | --- |
| 160 MS/s | `80 <= center_mhz <= 1840` | TIME_ONLY、SPEC_ONLY、TIME_SPEC | `center +/- 80 MHz` |
| 320 MS/s | `160 <= center_mhz <= 1760` | TIME_ONLY、SPEC_ONLY | `center +/- 160 MHz` |

每路 DAC/期望 RF信号还必须满足 `1 <= rf_frequency_mhz < 1920`；1920 MHz上边界
明确排除。`/api/v2/dac` 的 `center_mhz` 必须与当前八路 RFDC DAC mixer readback
一致，否则返回 HTTP 409，不能只改变 DDS计算基准。默认示例为
`center=200 MHz`、tone=`200.010 MHz`；`320 MS/s + center=100 MHz`必须拒绝。

## 当前控制面与接收合同

- Board Agent只提供 `/api/v2/*`；旧 `/api/v1/*` 返回404。
- 配置字段使用 `sample_rate_msps`；状态字段使用
  `selected_sample_rate_msps`、`detected_sample_rate_msps`、
  `rfdc_complex_sample_rate_hz` 和 `mts_result_id`。
- Python公共入口为 `python.t510_control.FEngineController` 和
  `python.t510_console.create_console`。
- Rust receiver只接受当前4096-channel SPEC：
  `16 blocks x 256 channels x 1 time x 8 inputs x IQ16`，并要求
  `PFB taps>=4`；CLI使用 `--initial-sample-rate-msps`。
- TIME/SPEC均为128-byte T510 header加8192-byte payload，UDP payload共8320
  byte；端口、包率和二进制布局保持现有数据面不变。
- 完整线格式见 `../../docs/t510_udp_payload_v2.md`。

## 构建与发布方式

- 只在现有 `demo-ant.xpr` 中运行 `synth_1/impl_1`，不得创建第二个工程。
- `scripts/t510_prepare_current_project.tcl`负责当前工程源集、BD和构建断言。
- 长任务成功后，由`scripts/t510_export_current_project.tcl`固定覆盖
  `build/vivado/latest`，`scripts/t510_build_latest.sh`复核XCI/HWH和SHA后原子更新顶层
  `overlay/`；不再维护候选ID、promotion状态或本地回滚树。
- `config/t510/config.example.json`已由MTS证据定版：bitstream SHA为上述唯一候选，
  ADC/DAC target为`452/88`，并包含discovery/fixed的40/40 proof。
- 发布脚本只从 catalog读取唯一 bitstream SHA，不维护第二份手写 SHA。
- Stage源码成果和正式报告继续保留；生成物、板端和接收机只保留当前版本，不保留
  旧release作为回滚。
- 面向多块T510开发板的正式安装、逐板配置和验收方法见
  `../../docs/t510_pynq_deployment.md`。

## 已通过的离线门禁

| 门禁 | 结果 |
| --- | --- |
| Python单元测试 | PASS，95 tests（板端脚本修正后完整回归） |
| Board Agent Cargo tests | PASS，7 tests |
| Time receiver Cargo tests | PASS，37 tests |
| Web数学测试 | PASS |
| 当前完整XSim回归 | PASS，18 testbenches |
| 仓库卫生检查 | PASS |
| `git diff --check` | PASS |
| `validate_bd_design` | PASS |
| RFDC XCI/HWH 3.84G/12x/80MHz合同 | PASS |

长任务提交身份与检查项见
`../vivado/stage33/latest_only_build_submission_20260803.md`；仓库清理详情见
`../maintenance/stage33_latest_only_cleanup.md`。

## 尚待硬门禁

1. 已完成：synth、impl和write_bitstream成功，设计fully routed、WNS/WHS非负、
   DRC通过。
2. 已完成：导出清理版唯一候选，记录bitstream SHA并再次核对RFDC XCI/HWH。
3. 已完成：MTS discovery的20次RFDC reset、10次overlay reload、10次LMK reload
   全部通过；ADC观测最大432、DAC观测最大72，固定target按规则定为`452/88`。
4. 已完成：固定target后同样40周期40/40通过。四tile在每次事务中均对齐；受RFDC
   driver的12-sample量化影响，最终latency允许落在target的半个factor，即`+/-6`内。
   实测ADC固定456，DAC为84或92，均满足该硬件语义且无MTS/LMK/SYSREF错误。
5. 部分完成：center=960和1760 MHz的RFDC/NCO及满速SPEC已通过；外部60/50 MHz
   频率轴通过，但SSA3032X Plus TG路径杂散未达到`-50 dBc`。DAC2到ADC2接线已由
   用户修正并确认有信号，但Stage 33的DAC2到ADC2复合回环主峰满足
   `observed_rf=2*center-requested_rf`，完整fresh configure后仍复现；必须先用
   同一外部绝对RF源比较ADC0和ADC2后，两路方向均通过，因而异常已归到DAC发送链；
   修复后再重跑200/960/1760和约1.90 GHz模拟闭环及DAC纯度。
6. 部分完成：五项60秒生产回归全部通过；3项10分钟soak、冷启动/服务恢复和60分钟
   全DAC热稳仍待执行。

新的临时板测输出统一写入`build/board/latest/evidence/`并绑定当前 SHA；
`reports/`只保留长期 Stage 和架构文档。历史候选不能替代当前门禁。

## 发布与证据闭合流程

本节合并原先独立存放的Stage 33发布说明。它是本阶段的执行记录，不作为跨版本
安装手册；通用安装说明已经迁到 `docs/`。

### Vivado当前导出

在当前 `demo-ant.xpr` 中完成长任务并通过一次性结果审计后，使用
`scripts/t510_export_current_project.tcl` 固定覆盖当前导出：

```text
build/vivado/latest/overlay/
build/vivado/latest/reports/
```

导出时必须重新核对fully routed、WNS/WHS非负、DRC、RFDC XCI/HWH和bitstream
SHA。`scripts/t510_build_latest.sh`验证固定`latest`目录后原子更新顶层`overlay/`；不再
维护build ID、候选目录、报告软链接或promotion状态。

### MTS discovery/fixed与catalog

对任何新候选，`config/t510/config.example.json`在物理MTS完成前必须先恢复为
zero SHA、负target和空campaign proof，使发布脚本故障关闭；完成以下流程后才能
重新定版。当前候选已经完成该流程并写入`452/88`：

```bash
python3 scripts/pynq_t510_mts_campaign.py --phase discovery \
  --output build/board/latest/evidence/mts_discovery.json

python3 scripts/pynq_t510_mts_campaign.py --phase fixed \
  --discovery-json build/board/latest/evidence/mts_discovery.json \
  --output build/board/latest/evidence/mts_fixed.json

python3 scripts/t510_finalize_catalog.py \
  --discovery-json build/board/latest/evidence/mts_discovery.json \
  --fixed-json build/board/latest/evidence/mts_fixed.json
```

两个阶段都必须包含20次RFDC reset、10次overlay reload和10次LMK reload，均为
40/40 PASS。ADC target等于discovery最大值+20，DAC target等于最大值+16；fixed
阶段要求每次事务内四tile latency一致、target读回一致、最终latency位于target的
半个factor范围内，并保持MTS/LMK/SYSREF无错误。raw offset是driver校正量，不作为
跨事务相位重复性的替代指标；射频相位重复性由独立闭环门禁测量。旧230/336 target
明确禁止。

### 构建与安装当前版本

Rust receiver不依赖bitstream catalog，可以先本地构建或直接安装当前版本：

```bash
scripts/t510_publish_receiver.sh --build-only
scripts/t510_publish_receiver.sh --install
```

`--build-only`不切换远端服务。板端安装必须等catalog固化后才允许：

```bash
scripts/t510_publish_board.sh --build-only
scripts/t510_publish_board.sh --install
```

receiver只有显式执行上传脚本给出的远端安装命令才会切换
`/opt/t510-time-rx/current`。sudo凭据禁止写入仓库、报告或命令行日志。

### 发布后门禁

临时 JSON 统一写入固定的 `build/*/latest/evidence/`，可由下一次修改或清理覆盖。
Stage 33 使用过的 RF 点阵、DAC purity matrix 和带 tag 的 release matrix 均属于
一次性验收工具，终止归档时已经删除；后续只保留下列稳定门禁：

```bash
scripts/pynq_t510_8lane_loopback.py --adc-target 452 --dac-target 88
scripts/t510_board_host_gate.py --sample-rate-msps 160 --mode time_only
scripts/t510_cold_start_gate.py
```

dry-run 只检查命令，不是验收证据。任何失败均先停止 science、mute DAC 并保存当前
状态；不得用旧 target、旧 bit 或旧 catalog 绕过当前门禁。

## 2026-08-03 板端campaign、部署与实测

### MTS discovery与fixed campaign

两次早期失败均保留为诊断证据，没有覆盖：第一次暴露LMK初始conditioning缺失和
`event_immediate`兼容常量回归，第二次暴露RFDC模拟采样率兼容别名缺失。修复后先用
smoke确认完整bootstrap，再执行正式campaign。

- discovery：20次RFDC reset、10次overlay reload、10次LMK reload，40/40 PASS，
  ADC latency范围408..432，DAC范围32..72；证据
  `stage33_mts_discovery.json`，SHA-256
  `f673b109353b7c96fee2ef1ba62e970de48d5345cdc82656107d1b8c806a94ef`。
- fixed：同样40周期40/40 PASS；ADC四tile每次均为456，DAC四tile每次均为84或
  92，相对target残差分别为`+4`和`-4/+4`，均在12-sample factor的半量化范围内；
  证据`stage33_mts_fixed.json`，SHA-256
  `300c20e6656c0bf64d8b5202006a7547242325f63bf920d541700f6d88868c3d`。
- catalog最终固定ADC/DAC target=`452/88`，campaign evidence SHA-256为
  `ed0925d391719e43cc7624f37281b866ba19023450bf09656e65586814e7b8a0`。

AMD RFDC driver会按`Factor=12`量化最终latency，因此结果可在target两侧半个factor
内收敛；raw offset是driver为各tile选择的校正量，不是射频相位读数。campaign和
catalog finalizer现在都独立检查这一语义，不能再把`Latency <= Target`或跨40周期
offset逐项相等误当成硬件合同。

### 历史正式release安装记录

下列路径是2026-08-04测试时的历史身份；2026-08-05 latest-only迁移后已删除，当前
安装固定为117的`/opt/t510-agent/current`和162的`/opt/t510-time-rx/current`实目录。

- 板端`192.168.100.117`：
  `/opt/t510-agent/releases/stage33-one-sample-7657d4c79823-mts452-88-20260804a`；
  `current`已指向该目录，`t510-agent`和reference watchdog均active。
- 采集机`192.168.100.162`：
  `/opt/t510-time-rx/releases/stage33-rx-memory-fix-20260804k`；
  `current`已指向该目录，receiver和NIC tune服务均active。
- 当时板端catalog只报告`fengine-0x00010033`、正式bit SHA
  `7657d4c7982343d55bb10c51186fbbd720dd2172b0e8ab3e64861c23801b771d`和target
  `452/88`。
- receiver数据口为`enp1s0f0np0`，MAC `4c:bb:47:2b:42:6e`，链路`LOWER_UP`；
  安装脚本已清理历史raw-table链，只保留当前`T510_RX`规则面。

安装后fresh configure成功读回`CORE_VERSION=0x00010033`、ADC/DAC 3.84 GS/s、
12x、80 MHz AXIS、16/16 valid mask和MTS固定结果。本文当前记录点板端为
160 MS/s、center=100 MHz、SPEC_ONLY、`streaming=true`、仅DAC2使能，输出请求
60 MHz、幅度约1.001%，watchdog healthy。TG已经关闭；当前物理接线为
`DAC2 -> 功分器 -> ADC0 + SSA3032X Plus RF INPUT`，采集机Web为
`http://192.168.100.162:8089/`。

### 外部TG 60 MHz输入：频率轴通过，纯度受输入路径限制

现场外部TG的60 MHz窄带信号经功分器进入ADC0和ADC1。160 MS/s、center=100 MHz、
SPEC_ONLY的8帧结果如下：

| ADC | 主峰 | bin误差 | 镜像抑制 | 载波外最大杂散 |
| --- | ---: | ---: | ---: | ---: |
| ADC0 | 60.000 MHz | 0 | 81.98 dB | -35.57 dBc @ 151.71875 MHz |
| ADC1 | 60.000 MHz | 0 | 75.12 dB | -36.91 dBc @ 151.71875 MHz |

主峰和RF轴准确、镜像均超过60 dB，接收机drop/gap增量为0；但最大杂散没有达到
`-50 dBc`，所以完整纯度门禁按实记录为FAIL，证据
`stage33_external_tg_60mhz_adc01_20260803.json`，
SHA-256 `026dd271a32daec20c34d443cfbf8b07c32de7b49e0b8e31009d533d39debd7e`。

保持物理输入不动、fresh configure到center=120 MHz后，151.71875 MHz分量从bin
1324移动到bin 812，但绝对RF频率保持不变，证明它不是固定PFB/bin伪谱，而是进入
ADC0/ADC1的真实模拟分量。该分量仍可能来自TG、功分器/线缆或ADC前端，未用外部
频谱仪在ADC接口处直接分段测量前不能进一步归因。center=120时60 MHz的镜像位置
恰为180 MHz，也与三次谐波重合，因而该诊断点不用于镜像验收。证据
`stage33_external_tg_60mhz_adc01_center120_diagnostic_20260803.json`。

随后在保持center=100 MHz和全部数字配置不变时物理拔掉TG，60 MHz功率从约82 dB
降至ADC0/ADC1的4.59/6.15 dB；151.71875 MHz功率也从46.00/44.84 dB降至
4.77/0.00 dB，下降约41..45 dB并进入噪声底。该单变量对照排除了板上固定时钟、
RFDC/PFB或packetizer自生151.71875 MHz的解释，把来源收敛到TG及其公共外部输入
路径。拔线证据为
`stage33_external_tg_unplugged_adc01_live_20260803.json`。

TG重新接入并保持`-20 dBm`，只把载波从60改为50 MHz后，ADC0/ADC1主峰均以0-bin
误差落在50 MHz；原151.71875 MHz杂散同步移动到141.71875 MHz，即载波和杂散都
向下移动10 MHz，二者偏移恒为`+91.71875 MHz`，幅度约为-36.74/-38.10 dBc。
这排除了固定绝对RF环境串扰，更符合TG合成/混频链的固定偏移边带。50 MHz关于
center=100 MHz的镜像位置150 MHz恰好也是三次谐波，所以该点的约53.5 dB只记录，
不用于否决ADC镜像。证据为
`stage33_external_tg_50mhz_adc01_frequency_shift_20260803.json`。

随后旁路功分器，以同一根输出线将TG直接接到ADC0。载波由82.49升至88.21 dB，
增加5.72 dB；141.71875 MHz杂散由45.75升至55.53 dB，增加9.78 dB，因而相对
杂散从-36.74恶化到-32.67 dBc。功分器不是杂散产生源，其插损反而改善约4.07 dB；
非线性增长指向ADC/模拟前端的电平相关混频，或者TG在直连负载/回波条件下源端纯度
恶化。必须直接测量TG输出才能在两者之间定责。证据为
`stage33_external_tg_50mhz_adc0_direct_no_splitter_20260803.json`。

随后按SSA3032X Plus TG的固定单音方式，把分析仪设为center=50 MHz、Zero Span、
TG level=-20 dBm，并恢复`TG -> 功分器 -> ADC0/ADC1`。24帧结果与普通模式几乎
完全一致：ADC0/ADC1载波为82.49/82.66 dB，141.71875 MHz边带为
45.36/44.42 dB，即`-37.13/-38.24 dBc`；相对前一组仅变化`-0.40/-0.13 dB`。
因此TG扫频不是边带成因。证据为
`stage33_external_tg_50mhz_zero_span_adc01_20260803.json`，
SHA-256 `bef64d515d7bbdc9c076080f94b4dab78e5966fbd0f1555229181222483ba522`。

### DAC2到ADC2物理映射与方向异常

在160 MS/s、center=200 MHz、tone=210 MHz下先只开DAC2为5%，ADC2没有看到目标
bin。随后仍只开DAC2、提高到10%，软件和寄存器读回均确认enable mask=`0x04`、
amplitude code=819，再扫描ADC0..ADC7，八路均未出现210 MHz tone。ADC0/ADC1仍只
看到外部TG路径的151.71875 MHz分量。

因此第一次诊断只能判定“现场DAC2到ADC2线未接通或面板标号不对应”，不能据此
否决DAC数字实现。两次历史诊断证据分别为
`stage33_dac2_adc2_loopback_160_210mhz_5pct_20260803.json`
和
`stage33_dac2_all_adc_mapping_diagnostic_160_210mhz_10pct_20260803.json`。

用户随后修正了DAC2到ADC2接线。在160 MS/s、center=100 MHz下只开DAC2为5%，
请求50 MHz时ADC2最强峰为150 MHz，50 MHz次峰低5.60 dB；请求60 MHz时最强峰
精确移动到140 MHz，60 MHz次峰低7.76 dB。两点共同满足
`observed_rf=2*center-requested_rf`，确认物理回环已接通，同时确认DAC2到ADC2
复合链路的方向与API的`requested_rf-center`合同相反。由于当前没有独立测量DAC2
输出，也没有用绝对外部RF源校验ADC2，不能仅凭这一条回环把方向错误归到DAC或ADC2。
按Stage 32的`INIT-STATE-001`处置要求执行
完整`STOP/flush -> 同一Stage 33 bit重新下载 -> RFDC init/MTS -> START`后，请求
60 MHz仍得到140 MHz主峰和`-7.78 dB`的60 MHz次峰，所以它不是旧overlay热状态，
也不能在完成DAC/ADC2隔离前通过软件反号或恢复被Stage 32否决的反号bitstream处理。
证据为
`stage33_dac2_adc2_loopback_60mhz_5pct_sign_diagnostic_20260803.json`
和
`stage33_dac2_adc2_loopback_60mhz_5pct_after_fresh_configure_20260803.json`。

利用已知镜像关系向DAC2请求150 MHz时，ADC2在逻辑RF轴的50 MHz处得到63.85 dB
主峰，141.71875 MHz探针为11.39 dB，即`-52.46 dBc`；同频TG进入ADC0/ADC1时为
`-37.13/-38.24 dBc`。这个约14..15 dB差异是有价值的旁证，但若ADC2本身方向反转，
其逻辑141.71875 MHz并不代表同一物理RF频点，所以在ADC2绝对RF轴闭合前，不能据此
完成TG或DAC定责。证据为
`stage33_dac2_adc2_actual50mhz_via_mirrored_request_5pct_20260803.json`
和
`stage33_dac2_adc2_141p71875mhz_probe_with_actual50mhz_20260803.json`。
诊断结束后八路DAC已恢复为mask=`0x00`；SPEC流继续运行。

最后将功分器原ADC1支路移到ADC2，使同一Zero Span 50 MHz、-20 dBm TG同时进入
ADC0和ADC2。32帧结果中ADC0/ADC2均以0-bin误差落在50 MHz，150 MHz镜像抑制为
53.41/54.55 dB；141.71875 MHz固定偏移边带在两路分别为`-36.51/-37.76 dBc`。
因此ADC2接收方向与ADC0一致且正确，DAC2到ADC2回环的center镜像异常可归到DAC
发送链；TG强偏移边带也与ADC通道无关，来源为TG及其公共外部源路径。证据为
`stage33_external_tg_50mhz_adc02_direction_isolation_20260803.json`，
SHA-256 `d457a0b9f20fd30d20d1f530ee04fd1a1a03abe125b628d87b15b01f8e249b7e`。

随后关闭TG并将`DAC2 -> 功分器 -> ADC0/ADC2`。只开DAC2、请求60 MHz、幅度降到
1%后，ADC0/ADC2仍同时在140 MHz得到主峰，60 MHz分量分别低7.53/7.58 dB；
两路主峰功率仅44.29/44.31 dB，远低于外部TG约82.5 dB的输入基线。这排除了单个
ADC通道、5%幅度和ADC过载造成方向/镜像异常的解释，并把DAC发送链异常复现到两条
已由外部绝对RF闭合的ADC接收路径。证据为
`stage33_dac2_split_adc02_60mhz_1pct_direction_20260803.json`，
SHA-256 `b463a3b15a8127af2d39550cc9214b1ee62bbd30590f1beb3ebe7ce8c4207b6b`。

为完全绕过ADC、PFB和接收机，用户随后把功分器原ADC2支路移到SSA3032X Plus的
RF输入，保持DAC2请求60 MHz、幅度1%、TG关闭。用户于2026-08-03 13:15:39提供的
分析仪截图采用20..180 MHz扫频、center=100 MHz、RBW/VBW均为10 kHz；直接测得
60 MHz为`-51.99 dBm`、140 MHz为`-45.25 dBm`，即错误的140 MHz边带比请求的
60 MHz高`6.74 dB`。该绝对模拟测量与ADC0/ADC2回环约7.5 dB的比值一致，排除了
ADC方向、PFB频率轴、UDP或接收端显示造成此现象；Stage 33 DAC模拟输出本身同时
包含60/140 MHz，且当前错误边带占优。这个结果仍不能由简单反转DDS频率符号修复，
因为反号只会交换两个边带的名称，不能把约`-6.74 dBc`的镜像恢复到Stage 32已达到
的至少60 dB抑制。

保持同一接线、center=100 MHz、1%幅度和20..180 MHz扫频，随后又完成两组直接SSA
测量：请求80 MHz时，2026-08-03 13:34:12读得80 MHz为`-56.16 dBm`、120 MHz为
`-42.87 dBm`，错误边带高`13.29 dB`；请求40 MHz时，2026-08-03 13:39:54读得
40 MHz为`-46.43 dBm`、160 MHz为`-44.16 dBm`，错误边带高`2.27 dB`。三点汇总如下：

| 复基带偏移绝对值 | 请求RF | center镜像 | 错误边带相对请求边带 |
| ---: | ---: | ---: | ---: |
| 20 MHz | 80 MHz | 120 MHz | +13.29 dB |
| 40 MHz | 60 MHz | 140 MHz | +6.74 dB |
| 60 MHz | 40 MHz | 160 MHz | +2.27 dB |

该比值显著依赖复基带频率，不符合固定I/Q增益失配。用“Q路相对I路反相并存在纯时延”
模型同时拟合三点，最佳Q/I增益为`1.000`、时延为`3.444 ns`，功率比拟合均方根残差
仅`0.11 dB`；三个点单独反算的时延为`3.394/3.433/3.481 ns`。这个量级接近一个
320 MS/s复样点的`3.125 ns`，把根因进一步收敛到Stage 33的12x RF-DAC C2R输入
数据队列/IQ时序合同，而不是DDS符号、固定增益、外部TG或ADC接收链。上述是当前
测量支持的等效模型；在用修复bit恢复至少60 dB镜像抑制前，不把它表述为已经证明的
RFDC内部实现缺陷。

为排除DAC2单路连接器或模拟通道异常，只把功分器输入从DAC2移到DAC0，并保持
center=100 MHz、请求80 MHz、1%幅度及SSA设置完全不变。2026-08-03 14:03:22
直接测得DAC0的80 MHz为`-56.38 dBm`、120 MHz为`-42.88 dBm`，错误边带高
`13.50 dB`；与DAC2相同测试的`13.29 dB`仅差`0.21 dB`。因此该问题不是DAC2
单路故障，而是至少跨DAC tile复现的全局数字链问题。

当前修复候选保留Stage 32的mode 0标准`I=cos,Q=sin`及128-bit字序不变，新增两个
Stage 33专用tone mode：mode 2执行`Q反相 + 141/128样点超前`，mode 3执行相同幅度
的反方向补偿。`141/128=1.1015625`，与三点拟合的`1.10198`样点差约0.0004样点。
两个方向同时进入同一bitstream，控制软件先选择mode 2；若直接SSA验证表明时延方向
相反，只需切换为mode 3，不重新综合或改变API JSON。该补偿在物理SSA门禁通过前仍为
诊断候选，不能据离线数学模型提前标记为修复完成。

2026-08-03 16时后，新候选bit SHA-256
`e45e737892725330485d868efd2874ba28920377621000f31223141e628dca6d`完成实现，
WNS/WHS为`+0.052/+0.009 ns`，并以不修改正式catalog/release的独立诊断方式加载。
旧bit固定MTS target `452/88`在新候选上被RFDC拒绝；候选单次discovery得到ADC
`396/396/396/396`、DAC `48/48/48/48`，因此临时诊断target按margin设置为
`416/64`。固定结果为ADC `420/420/420/420`、DAC `60/60/60/60`，8个tile PLL
全部锁定、RFDC合同通过。

板端保持Agent/watchdog停止，不切换production release；最初仅DAC0启用，center
100 MHz、tone 80 MHz、amplitude code 82（约1%）、mode 2
`stage33_q_advance`，供SSA直接读取80/120 MHz。证据为
`stage33_dac_iq_candidate_discovery_center100_20260803.json`
和
`stage33_dac_iq_candidate_mode2_center100_tone80_20260803.json`。
这两项只闭合一次候选诊断配置，不替代正式20+10+10 discovery/fixed campaign。

用户随后在同一20..180 MHz、center=100 MHz、RBW/VBW=10 kHz和20 dB输入衰减的
SSA设置下直接测得：请求的80 MHz为`-42.31 dBm`，center镜像120 MHz为
`-77.56 dBm`，可见镜像抑制为`35.25 dB`。这与修复前DAC0错误的120 MHz边带高
`13.50 dB`形成方向反转，证明mode 2补偿方向正确；但120 MHz已经贴近约
`-78 dBm`的SSA显示噪底，因此该截图只给出`>=35.25 dB`的噪底受限下限，不能把
DAC纯度提前声明为计划要求的`>=60 dBc`。

为提高ADC对照的动态范围，只把DAC0 amplitude code提高到`2048`（25%），center、
tone、mode和enable mask保持不变；完整RFDC读回仍为ADC/DAC 3.84 GS/s、12x、
Nyquist zone 1、16/16 valid，临时MTS target仍为`416/64`。配置证据为
`stage33_dac_iq_candidate_mode2_center100_tone80_25pct_20260803.json`，
SHA-256 `f4dc7925b03dbf9ed098c5be6dc754db7912760116a949a8015f27b7ac5532b8`。

随后从ADC0采集64帧、每帧1024个320 MS/s原始复样点。80 MHz精确落在目标bin，
bin误差为0；120 MHz为`-33.83 dBc`，比上述SSA可见下限少`1.42 dB`，且高于ADC
噪底`22.45 dB`，对照可分辨。生产160 MS/s RF带内除载波外的最大峰就是该120 MHz
源端镜像；未削顶、RFDC drop增量为0、sample0严格单调，判定
`STAGE33_ADC_SOURCE_REFERRED_PASS`。这证明本次ADC0反测没有方向错误或新增强杂散。
由于SSA和ADC数据分别取自1%和25%的DAC幅度，该`1.42 dB`只作为初步源端对照，
正式纯度门禁仍需在同一幅度下同步复测。证据为
`stage33_adc0_source_compare_mode2_80mhz_25pct_20260803.json`，
SHA-256 `5b55b87d4c37bbbb4c5cb0e9d0b9db22d95993c7e78d5ccff08ef48ee1944cd7`。

用户紧接着在同一25%幅度下完成了同幅度SSA读数：80 MHz为`-14.15 dBm`，120 MHz
为`-48.66 dBm`，镜像抑制为`34.51 dB`。它与ADC0的`33.83 dB`只差`0.68 dB`，
因此正式确认ADC0只是忠实接收了DAC源端残余镜像，没有新增这条强边带；同时也确认
mode 2只修复了发送方向，当前DAC纯度仍比`>=60 dBc`门限少`25.49 dB`，不能把该
候选提升为正式修复。25%结果还表明1%截图的120 MHz读数确实受SSA噪底限制。

为区分残差来自幅度还是相位，随后使用候选已有的constant-phasor mode，依次发送
`+I/-I/+Q/-Q`，在ADC0上各执行16次1024点采集并作差，以消除ADC/DC偏置。测得
Q/I幅度比`0.999842`、所需增益补偿仅`1.000158x`，Q/I相位为`-89.9931 deg`；未
削顶且RFDC drop增量为0。这排除了约3.7%的I/Q增益误差，说明34.51 dBc残差主要是
20 MHz偏移处仍有约2.16度相位误差。证据为
`stage33_dac0_adc0_iq_dc_calibration_25pct_20260803.json`，
SHA-256 `da2707dd6a93cd767db94fe38f9bd0568592a5db56da7a308a2e171b667f5aec`。

最后在同一ADC0链路中依次切换未补偿mode 0、当前mode 2和反向mode 3，各采64帧
复数FFT。三者tone/image分别为`-14.20/+33.85/+6.94 dB`；mode 2相对mode 0的
边带复乘积相位差为`-0.202 deg`，mode 3则为`-179.874 deg`，三项相干度均高于
`0.9990`。因此当前`141/128`样点前移明确是补偿过量，物理等效值收敛到约1个
320 MS/s样点；下一候选应使用精确`+/-1`样点，而不是增加I/Q增益修正。证据为
`stage33_dac0_adc0_mode_phase_sweep_80mhz_25pct_20260803.json`，
SHA-256 `5994743190692a4196b1fa34981196a48de4c5bce01ff0725b636ee16f9ec04c`。

诊断结束后science输出已回到OFF；DAC0恢复为25%、80 MHz、mode 2输出。正式Agent、
watchdog、production catalog和`latest`均未改变。

RTL随后把mode 2/3从`+/-141/128`改为精确`+/-1`样点，mode 0和全部Stage 32数据面
保持不变；Python 96、两个Rust测试集37+7、XSim 18项、仓库卫生和diff检查均通过。
当前同一`demo-ant.xpr`已于2026-08-03 17:21完整提交
`synth_1 -> impl_1 -> write_bitstream`长任务，提交后未轮询进度。提交记录见
`latest_only_build_submission_20260803.md`。

用户确认长任务完成后执行了一次最终审计。精确单样点候选fully routed，WNS/WHS为
`+0.024/+0.010 ns`，DRC和methodology没有Error或Critical Warning；实现run有一条
独立的Evaluation License Critical Warning，按发布风险保留。不可变bit SHA-256为
`7657d4c7982343d55bb10c51186fbbd720dd2172b0e8ab3e64861c23801b771d`，RFDC
XCI/HWH合同通过，`--verify-only`通过且没有提升`latest`或写正式catalog。构建证据见
`stage33-dac-iq-one-sample-20260803b/build_audit.md`。

该候选随后加载到117板的独立缓存目录。单次MTS discovery得到ADC
`432/432/432/432`、DAC `32/32/32/32`，按`+20/+16`margin设置临时target
`452/48`后，固定读回ADC `456/456/456/456`、DAC `44/44/44/44`；全部结果均在
12x量化允许的target正负6范围内。PLL1/PLL2和8个RFDC tile锁定，valid mask
`0xffff`，RFDC drop/error均为0。证据为
`stage33_dac_iq_one_sample_discovery_mode2_center100_tone80_25pct_20260803.json`
和
`stage33_dac_iq_one_sample_fixed_mode2_center100_tone80_25pct_20260803.json`。
当前Agent/watchdog仍停止，science输出OFF；只开启DAC0，center=100 MHz、请求80 MHz、
amplitude code 2048（25%）、mode 2 `stage33_q_advance`，等待SSA直接读取80/120 MHz。
这一组仅为单次物理诊断，不替代正式MTS 40/40 campaign。

用户于2026-08-03 18:29:12提供同幅度SSA截图，设置为20..180 MHz、center
100 MHz、RBW/VBW 1 kHz、20 dB输入衰减。80 MHz主信号为`-14.16 dBm`，120 MHz
镜像点为`-84.17 dBm`，得到噪底受限的可见镜像抑制下限`>=70.01 dB`；160 MHz
最大可见杂散为`-70.81 dBm`，即`-56.65 dBc`。因此该离散点同时通过计划要求的
`>=60 dBc`镜像和`<=-50 dBc`杂散门限。相较141/128候选同幅度只有`34.51 dB`，
精确1样点补偿把镜像可见下限提高了至少`35.50 dB`。

保持DAC0到功分器再到ADC0/SSA的接线不变，随后从ADC0采集64帧、每帧1024个
320 MS/s复样点。80 MHz精确落在目标bin，120 MHz点低于ADC中值噪声底`0.91 dB`，
所以ADC侧`57.22 dB`只代表1024点预览的噪底受限下限，不是可分辨镜像。带内最大
其他峰为`-52.32 dBc @ 20 MHz`；无clip、RFDC drop增量0、sample0严格单调，分类
为`STAGE33_ADC_SOURCE_REFERRED_PASS`。这证明ADC0没有重新制造镜像或新增超过
门限的强杂散。证据为
`stage33_adc0_source_compare_exact_one_sample_80mhz_25pct_20260803.json`，
SHA-256 `087af0850d9821dc1d3ab01187009a0c00586b13b07e81a7a64d3ba40a9dcf2b`。

中频点随后切为center=960 MHz、DAC0请求940 MHz、25%幅度，临时MTS target仍为
`452/48`且RFDC合同完整。用户于2026-08-03 18:39:52提供span=160 MHz、RBW/VBW
1 kHz的SSA截图：940 MHz为`-18.38 dBm`，980 MHz镜像点为`-82.65 dBm`，得到
噪底受限的镜像抑制下限`>=64.27 dB`，通过60 dBc门限。配置证据为
`stage33_dac_iq_one_sample_fixed_mode2_center960_tone940_25pct_20260803.json`，
SHA-256 `0db1153c4bc5bad8f82e69be06798e89b9ccd736b33512fc0bdc633d8009fbd0`。

后续同一25%幅度SSA截图把第一Nyquist内的源端对照补齐：940/980/1020 MHz分别为
`-18.59/-81.00/-82.05 dBm`，即980 MHz镜像`-62.41 dBc`、1020 MHz分量
`-63.46 dBc`，两者均通过门限。幅度降至code 512（6.25%）后，三点分别为
`-30.58/-83.35/-82.09 dBm`；后两点已接近SSA噪底，只能给出`>=52.77 dB`和
`>=51.51 dB`的下限。

但ADC0原始复样点在该频点稳定发现独立的1020 MHz分量：第一次为`-41.59 dBc`；
诊断脚本补上`-50 dBc`最大杂散硬门限后重采64帧，得到`-40.11 dBc`并正确分类为
`STAGE33_ADC_SOURCE_REFERRED_FAIL / ADC_MAX_SPUR_EXCEEDS_LIMIT`。980 MHz镜像仍在
ADC噪声底附近，目标bin误差0、无clip、RFDC drop增量0、sample0严格单调。第一
Nyquist内的SSA已经排除DAC在1020 MHz直接输出同等强度分量，但仍不能单凭这一点
把它定责到ADC。修正后证据为
`stage33_adc0_source_compare_exact_one_sample_940mhz_25pct_gated_20260803.json`，
SHA-256 `c9816d981d32d10355657c46847be9e651b26d6344a5d155c4f6c69ab0e8684e`。

按用户要求，候选当前保持ADC/PFB和实时SPEC持续开启。板端装入16,384个4-tap PFB
系数，运行160 MS/s SPEC_ONLY、16条SPEC route和CMAC live；DAC0 940 MHz tone
保持不变。162端8089显示参数已经设置为center=960 MHz、target=940 MHz，Spectrum
live且覆盖16/16 block。实测约`625,114 pps / 41.608 Gbit/s`；连续3秒窗口内
parse/ring/worker/kernel/app drop以及SPEC seq/frame gap增量全部为0。证据为
`stage33_candidate_live_spec_center960_tone940_25pct_20260803.json`，
SHA-256 `0d6d70330111a43c69d1bdc788ca3b22dbac1a223a0911567b0536462dc46557`。

由于Web界面没有频点marker，随后直接订阅8089的`/ws/spectrum`二进制流，按网页
相同的循环FFT-bin到RF映射，对CH0连续帧在线性功率域平均。在线切换DAC码幅时不
停止SPEC流，三档32帧结果如下；每次采集的receiver drop/gap增量均为0：

| DAC码幅 | 940 MHz功率 | 960 MHz / dBc | 980 MHz / dBc | 1020 MHz / dBc |
| ---: | ---: | ---: | ---: | ---: |
| 512 | 58.57 dB | -27.74 | -46.62 | -45.80 |
| 1024 | 64.42 dB | -23.31 | -49.63 | -44.72 |
| 2048 | 70.13 dB | -29.83 | -63.11 | -42.18 |

恢复code 512后另取64帧，940 MHz为`58.42 dB`，960/980/1020 MHz分别为
`-33.84/-45.34/-48.02 dBc`，再次确认1020 MHz不是Web绘图伪影，同时也表明低码幅
结果已接近接收噪底。证据为
`code512`、
`code1024`、
`code2048`和
`code512恢复复测`。

1020 MHz恰好满足`3840 - 3*940 = 1020 MHz`。因此曾保留一个物理歧义：DAC/线缆
若在2.82 GHz存在940 MHz的三次谐波，它会被3.84 GS/s ADC折叠到1.02 GHz。保持
现有功分接线、DAC code 2048后，用户用SSA直接观察2.82 GHz，结果仅为约
`-80 dBm`噪底。相对于940 MHz的`-18.59 dBm`载波，这给出源端三次谐波
`<=-61.41 dBc`的上限；而同幅度ADC原始预览/WebSocket分别为`-40.11/-42.18 dBc`，
接收路径多出至少约`19.23 dB`，DAC/线缆的可见带外谐波不能解释该分量。

随后不改线、不中断SPEC流，只把DAC tone从940改为945 MHz。64帧WebSocket结果中
945 MHz载波为`70.39 dB`，原1020 MHz点降到`-61.93 dBc`，新杂散精确移动到
1005 MHz并为`-42.48 dBc`，满足`3840 - 3*945 = 1005 MHz`；975 MHz镜像为
`-56.66 dBc`。receiver所有drop/gap增量为0。tone已在线恢复为940 MHz、code 2048，
SPEC流保持开启且RFDC drop增量为0。

随后保持物理DAC tone为940 MHz，只把8路ADC NCO从-960 MHz同步改为-950 MHz，
并把接收端RF轴中心同步改为950 MHz。若1020 MHz来自DDC后的复基带三次非线性，
940 MHz在新基带中的-10 MHz分量应产生+30 MHz分量，即物理980 MHz；实际64帧结果
为：940 MHz载波`70.16 dB`，950/960/980/1020 MHz分别为
`-59.28/-35.93/-58.81/-46.27 dBc`。980 MHz候选落在噪底附近，而物理1020 MHz
分量仍然存在；其相对值变小与它移到新DDC通带边缘+70 MHz一致。该实验把问题进一步
收敛到DDC之前的ADC模拟输入/RFADC采样校准支路，排除了ADC adapter、PFB、UDP、
接收端和Web，也排除了RFDC DDC后的复基带非线性。

该阶段当时只把范围暂时收敛到ADC的DDC前支路；后续外部TG与DAC带外扫描已经推翻
“ADC输入支路自行产生三次谐波”的临时解释，并闭合为DAC采样镜像参与输入端互调，
详见后文“外部TG与2.90 GHz DAC采样镜像定责”。移频证据为
`stage33_adc0_websocket_center960_tone945_code2048_alias_test_20260803.json`，
SHA-256 `2c7ebfb7ef50cc363557d62adb18fedac1dd0f4276b9511d4c3424881d7f5fec`；恢复证据为
`stage33_live_dac_level_center960_tone940_restore_code2048_20260803.json`，
SHA-256 `cbf82991e990772d7e3e448a61a4b810b3f49187fc19296d61f8ea7ecc204f7d`。
ADC中心平移证据为
`stage33_adc0_websocket_adc_center950_tone940_code2048_baseband_vs_analog_20260803.json`，
SHA-256 `92c6a8dae2064fbef44e18c65e9c0f4849ee8fd45c930b55e4575af227fc7073`；
NCO已恢复为-960 MHz，恢复证据SHA-256为
`bc71b4194902fab54135981c6c4a967c17286882b2fc3fe5c4c30651eeee1552`，全程RFDC和
receiver drop/gap增量均为0。

RFDC驱动只读检查显示，ADC0及其他启用slice均为`CalibrationMode=2`、`Dither=1`、
`DSA=0 dB`、`CalFreeze=0`、QMC gain/phase关闭、Nyquist zone 1和12x decimation；
PLL、FIFO及数据路径状态正常。按AMD
[PG269 Calibration Modes](https://docs.amd.com/r/en-US/pg269-rf-data-converter/Calibration-Modes)，
3.84 GS/s的Mode 2适用于`0..0.4Fs`即`0..1.536 GHz`，因此940 MHz使用Mode 2正确。
当前bit运行时把Mode 0写入RFDC被拒绝；进一步审计生成的RFDC 2.6 XCI和IP GUI
元数据后确认，8路`ADC_CalOpt_ModeXX`当前均固定为`1`，该枚举代表legacy Mode 2，
而`2`才代表AutoCal。因此运行时拒绝并不证明器件不支持AutoCal，而是当前RFDC IP
在生成时没有启用它。在线A/B中，Mode 2基线、
Mode 1和恢复Mode 2的1020 MHz分别为`-40.95/-41.95/-40.30 dBc`，Mode 1仅有约
1 dB波动级改善，不能作为修复；最终已恢复Mode 2。

ADC0片内DSA随后以3/6/9 dB在线扫描，结果如下：

| DSA | 940 MHz功率 | 1020 MHz / dBc | 结果 |
| ---: | ---: | ---: | --- |
| 0 dB基线 | 70.07 dB | -40.30 | FAIL |
| 3 dB | 67.29 dB | -40.79 | FAIL |
| 6 dB | 64.52 dB | -44.32 | FAIL |
| 9 dB | 61.73 dB | -45.20 | FAIL |

DSA证明输入电平参与该非线性，但9 dB仍距`-50 dBc`门限约4.8 dB，同时牺牲载波和
接收动态范围，且960 MHz固定中心项的相对值恶化，不能直接作为Stage 33生产修复。
所有窗口drop/gap增量均为0；ADC0最后已明确恢复`DSA=0 dB, DisableRTS=0`，实时
SPEC保持开启。校准A/B证据为
`Mode 2基线`、
`Mode 1`和
`Mode 2恢复`；
DSA证据为
`3 dB`、
`6 dB`、
`9 dB`和
`0 dB恢复`。

下一受控候选只在权威RFDC BD Tcl中把8个物理ADC converter显式固定为
`ADC_CalOpt_Mode=2 (AutoCal)`，并把同一条件加入Tcl构建断言和XCI/HWH artifact
门禁；16条派生R2C数字路径不单独配置校准模式。该候选不改变3.84 GS/s、12x、
80 MHz AXIS、Nyquist zone、NCO、ADC adapter、DAC精确单样点补偿或Stage 32的
science/PFB/TIME/SPEC/UDP/Rust数据面。只有新bit上板读回AutoCal并把1020 MHz降至
`<=-50 dBc`后，才可把它标为物理修复；现阶段不使用DSA换取门限，也不提升
`latest`或production catalog。

该AutoCal候选随后在当前`demo-ant.xpr`中完成综合、实现和write_bitstream。最终
设计fully routed，WNS/WHS为`+0.035/+0.009 ns`，DRC和methodology没有Error或
Critical Warning；实现日志仍保留一条Evaluation License Critical Warning。不可变
候选ID为`stage33-adc-autocal-20260803b`，bit SHA-256为
`e64c8ac8f215da7c834f0808617e2bf99f46f69c700412289e78aaddf982ee3f`；RFDC XCI/HWH
合同和8路AutoCal artifact门禁通过，`--verify-only`通过且没有提升`latest`或正式
catalog。构建证据见
Stage 33a的AutoCal否决项汇总。该候选没有进入catalog，重复的探索构建目录已在
Stage 33a证据收口时清理；候选ID、bit SHA、时序和物理否决结论保留在本节。

AutoCal候选随后以独立缓存加载到117板。单次MTS discovery为ADC
`408/408/408/408`、DAC `72/72/72/72`，临时target `428/88`固定后读回ADC
`432/432/432/432`、DAC `84/84/84/84`。全部tile PLL锁定、valid mask
`0xffff`、FIFO正常、RFDC drop/error为0。最终XCI的8个converter均为
`ADC_CalOpt_Mode=2`；板端8个活动ADC block均为12x、Nyquist zone 1、dither开启、
DSA 0 dB，运行时活动legacy校准寄存器读回为Mode 2。运行时请求Mode 0仍被驱动
拒绝且读回不变，但streaming保持、drop增量为0；该运行时寄存器不用于否定XCI中的
AutoCal生成策略。健康读回证据为
`stage33_adc_autocal_runtime_readback_corrected_center960_tone940_code2048_20260803.json`。

center=960 MHz、DAC0=940 MHz、code 2048、精确单样点mode 2下，从162端8089连续
采64帧：940 MHz载波`69.99 dB`，960 MHz为`-44.20 dBc`，980 MHz镜像
`-52.68 dBc`，1020 MHz为`-39.08 dBc`。目标bin误差0，receiver的kernel/ring/app
drop及SPEC seq/frame gap增量全部为0。1020 MHz不仅没有达到`<=-50 dBc`，也没有
优于AutoCal前约`-42.18 dBc`，所以该候选最终分类为
`ADC_AUTOCAL_PHYSICAL_REJECTED`，没有提升`latest`或正式catalog。频谱证据为
`stage33_adc0_websocket_autocal_center960_tone940_code2048_20260803.json`。

诊断结束后117板已恢复精确单样点候选SHA
`7657d4c7982343d55bb10c51186fbbd720dd2172b0e8ab3e64861c23801b771d`。重载后DAC
discovery下限为72，旧临时target 48被MTS拒绝；使用ADC `452`、DAC `88`后固定
读回ADC `456/456/456/456`、DAC `84/84/84/84`。SPEC_ONLY 160 MS/s已重新发送到
采集机`enp1s0f0np0`的实际MAC `4c:bb:47:2b:42:6e`，8089配置generation更新为16；
短窗口实测约`625.1 kpps / 41.82 Gbit/s`，drop/gap增量全为0。32帧恢复检查得到
1020 MHz `-40.67 dBc`，继续作为未修复ADC输入/RFADC问题保留。恢复证据为
`MTS与位流`、
`live SPEC`和
`频谱`。

权威`bd/t510_rfdc_bd.tcl`和生产artifact verifier随后恢复并显式锁定
`ADC_CalOpt_Mode=1`（legacy Mode 2）；AutoCal失败候选继续作为不可变诊断证据保留，
但后续Stage 33正常重生会拒绝`ADC_CalOpt_Mode=2`。已恢复的精确单样点候选XCI/HWH
在新门禁下通过，Python 99项测试、脚本编译和`git diff --check`均通过。相同生产
配置已有已验证不可变bit，因此没有仅为回退元数据重复启动一次Vivado长任务。

### ADC0/ADC2同源相干与DSA差分定位

用户随后把同一940 MHz输出经功分同时接入ADC0和ADC2。两路128帧同时采集结果为：

| 项目 | ADC0 | ADC2 | ADC2-ADC0 |
| --- | ---: | ---: | ---: |
| 940 MHz载波 | 70.49 dB | 70.81 dB | +0.32 dB |
| 1020 MHz绝对功率 | 29.01 dB | 28.74 dB | -0.26 dB |
| 1020 MHz相对载波 | -41.49 dBc | -42.06 dBc | -0.58 dB |

940 MHz两路复相位差为`-0.09 deg`、相干度`0.9999995`；1020 MHz相位差
`+0.24 deg`、相干度`0.9972`。两路目标bin均无误差，receiver drop/gap增量全为0。
这排除了ADC0单路连接器、单个tile或Web绘图异常；1020 MHz是两路共有的相干分量。
证据为
`stage33_adc0_adc2_same_source_coherence_center960_tone940_code2048_20260803.json`，
SHA-256 `47019cd291a225c6518163c5b2676f19ffdc79cde7083e3c0b9535bc6d655dae`。

不中断SPEC流、只把DAC0 amplitude从2048置零后，ADC0/ADC2的940 MHz绝对功率分别
下降`62.54/62.51 dB`，1020 MHz分别下降`21.11/21.05 dB`并落到约7.8 dB噪声区；
1020 MHz两路相干度由`0.9972`降至`0.0903`。恢复code 2048后载波、1020 MHz及
`>0.996`相干度全部恢复。这证明1020 MHz不是固定时钟泄漏，而是由外部940 MHz输入
驱动的相干分量。DAC置零和恢复证据分别为
`置零频谱`和
`恢复频谱`。

最后保持ADC0 DSA=0 dB，只把ADC2 DSA设为9 dB做同时差分。ADC2相对ADC0的940 MHz
下降`8.02 dB`，1020 MHz下降`8.49 dB`，所以1020相对载波只改善`0.47 dB`，没有
呈现转换器后级新生三次谐波应有的额外阶次衰减。按AMD
[PG269 DSA说明](https://docs.amd.com/r/en-US/pg269-rf-data-converter/Digital-Step-Attenuator-Gen-3/DFE)，
DSA集成在RF-ADC输入buffer中；因此当前范围进一步收敛为DSA/input buffer之前或附近
的模拟链路，或者一个由ADC线性采入的2.82 GHz源端分量，不能再归到DDC/PFB/UDP。
ADC2已恢复`DSA=0 dB, DisableRTS=0`，DAC0也恢复code 2048，SPEC流保持开启。
DSA证据为
`stage33_adc2_dsa9_adc0_dsa0_same_source_coherence_20260803.json`，
SHA-256 `ad62aaa08d9b0c146d6ae82db1b7582c9889549d2ca6fdf08bd50af4fe8ea37b`；
恢复证据为
`stage33_adc2_dsa0_restore_verify_same_source_20260803.json`。

### 外部TG与2.90 GHz DAC采样镜像定责

决定性A/B使用完全相同的功分器、线缆和ADC0输入支路，只切换功分器输入源。外部
SSA3032X Plus TG在940 MHz、SSA实测`-28.54 dBm`时，ADC0连续128帧得到940 MHz
载波`80.35 dB`、1020 MHz `-57.76 dBc`、980 MHz镜像抑制`68.58 dB`、最大带内
杂散`-50.52 dBc`，全部通过且drop/gap增量为0。该载波在ADC数字谱中还比板载DAC
源高约10 dB，因此不是“输入不够大所以没有激发问题”。证据为
`stage33_external_tg940_adc0_center960_ssa_minus28p54dbm_20260803.json`，
SHA-256 `e77bfccbe3de25a363c59e15cd2949bfa56cd265d47351e2b79f986ccdc79de8`。

这里的`PASS`表示达到Stage 33离散门限，不表示频谱上完全没有峰。外部TG条件下，
物理960/1020 MHz仍分别可见`-54.38/-57.76 dBc`的小峰；换为物理DAC0后，两点分别
恶化到`-38.44/-41.16 dBc`。两点不能按同一根因处理：强1020 MHz会随DAC tone从
940改到945 MHz而精确移动至1005 MHz，已由后文定责为DAC采样镜像参与的源相关
互调；960 MHz在ADC NCO中心从960改到950 MHz时仍停留在物理960 MHz，且绝对功率
仍为`34.23 dB`，而新的中心950 MHz仅`-59.28 dBc`。所以960不是DDC中心DC泄漏，
而是固定模拟/RFADC频点。

`960 MHz = Fs_ADC/4`恰好落在RFADC交织offset位置。AMD
[Time-Interleaved OCB说明](https://docs.amd.com/r/en-US/pg269-rf-data-converter/Time-Interleaved-Offset-Calibration-Block-OCB)
指出，子ADC残余offset会出现在`k*Fs/N`；本器件无论按4路还是8路交织解释，
`Fs/4`都是该集合中的位置。AMD的
[Foreground Calibration Process](https://docs.amd.com/r/en-US/pg269-rf-data-converter/Foreground-Calibration-Process)
还要求启动前景校准期间输入静音，避免在交织offset位置存在能量。因此960 MHz当时
归类为`ADC_FS_OVER_4_INTERLEAVE_OFFSET_CANDIDATE`：频点关系和NCO平移证据成立，
但不提前把RFADC交织offset位置等同于已经证明的OCB系数故障。

用户随后把DAC物理连接完全拔掉并保持ADC/PFB/SPEC运行。立即抓取128帧后，ADC0的
960 MHz仍为`39.49 dB`，而940/1020 MHz分别只有`6.96/7.29 dB`噪声区；960比1020
高`32.20 dB`，且receiver drop/gap增量全部为0。证据为
`stage33_adc0_dac_physically_disconnected_fs_over_4_spur_20260803.json`，
SHA-256 `efe9498a06ef8f18b5a7530f1a7f00f5e92e715f50ba2f7305e2f40b1c7daead`。

更早的DAC amplitude置零、ADC0/ADC2同时采集数据也提供了跨converter证据：两路
960 MHz绝对功率为`38.73/37.00 dB`，复相干度`0.9896`；同一窗口1020 MHz只有
`7.89/7.69 dB`且相干度`0.0903`。证据为
`stage33_adc0_adc2_same_source_dac_off_coherence_center960_20260803.json`，
SHA-256 `8c045ebb10d0eb613f08cba0a5d3d93e5013701fe413a9cb7fd111ba1dd13e41`。

据此正式升级为`ADC_FS_OVER_4_SPUR_CONFIRMED`：960 MHz不依赖外部TG或DAC输入、跨
ADC高度相干、频率固定在`Fs_ADC/4`且不跟随DDC NCO。问题位于RFADC交织offset/
采样时钟相关支路；仍需通过foreground calibration输入静音A/B和校准系数读回，
区分OCB残余offset与板级`Fs/4`时钟耦合。与此同时，物理断开DAC后1020 MHz落回
噪声且失去跨ADC相干，进一步确认强1020与固定960不是同一问题。

TG切到2820 MHz、SSA实测`-30.62 dBm`后，ADC折叠峰落在1019.9609375 MHz并为
`68.29 dB`；相较TG 940 MHz的`80.35 dB`低`12.06 dB`。扣除源电平低`2.08 dB`，
ADC在2.82 GHz的相对灵敏度约低`9.98 dB`，而不是早期歧义所需的高约20 dB。
所以DAC端2.82 GHz三次谐波`<=-61.41 dBc`最多只能在ADC中表现为约`-71.4 dBc`，
不能解释`-42 dBc`。证据为
`stage33_external_tg2820_alias1020_adc0_center960_ssa_minus30p62dbm_20260803.json`，
SHA-256 `e98221e112294a8825cef5512d1b702786e9c4d40800311e5a72ac91fd2c34f9`。

为排除DAC开启后的封装、电源或时钟串扰，外部TG 940 MHz继续送入ADC0，同时让板载
DAC0输出连接器保持开路。板载DAC关闭/开启时，ADC0的1020 MHz分别为
`-57.96/-59.18 dBc`，均通过且没有随DAC开启出现杂散；因此问题必须经过外部模拟
输出路径。证据为
`DAC关闭`和
`DAC开启但输出开路`，
SHA-256分别为`99e9a3cd2edd53b11602195485f55481e8f4d7f1bfa00f8f036e58bc8ab29572`和
`5d6948e0f0efac7307efdfeaa72820e3bac7cfc00f67c2e131e171171c11510b`。

保持功分器输出到ADC0和SSA完全不动，把输入从TG换回物理DAC0后，ADC0立即复现
940 MHz载波`70.30 dB`和1020 MHz `-41.16 dBc`，drop/gap增量仍为0。证据为
`stage33_same_path_dac0_adc0_center960_tone940_code2048_20260803.json`，
SHA-256 `3e70adfb03ef7a86c948df3c87e51d83bb41f0dfa26f2f5cb98c50c169dd5ceb`。

最后在DAC0保持940 MHz、code 2048、同一功分路径和TG关闭时扫描第一Nyquist区间
之外。2.82 GHz处只有约`-80 dBm`噪底；2.900 GHz处明确测得`-64.19 dBm`离散谱线。
它不是三次谐波，而是3.84 GS/s DAC的第一采样镜像：

```text
f_image = Fs_DAC - f = 3840 - 940 = 2900 MHz
f_spur  = |2f - f_image| = |3f - Fs_DAC| = 1020 MHz
```

同路径最近一次940 MHz基波为`-18.59 dBm`，所以2.90 GHz镜像约为`-45.60 dBc`；
该比值不是同时测量，只作为工程估计。更强的交叉验证来自先前移频实验：tone从
940改到945 MHz时，采样镜像应从2900移到2895 MHz，互调产物应从1020精确移到
`|3*945-3840|=1005 MHz`，实际观察完全一致。SSA人工转录证据为
`stage33_dac0_ssa_sampling_image_2900mhz_20260803.json`，
SHA-256 `87077b4512cf9897b92a1de1c697bfd9a62b6b5755667a29c1c3916cfa56e3b9`。

因此1020 MHz的最终物理结论是：外部低失真940 MHz源进入ADC0时只有
`-57.76 dBc`残余，满足`-50 dBc`门限；未滤波的DAC到ADC直连同时把940 MHz基波和
2.90 GHz DAC采样镜像送入宽带模拟输入链，产生强1020 MHz三阶互调。该强分量不是
PFB/Web伪影、不是DDC后非线性、不是AutoCal问题，也不是2.82 GHz三次谐波。这个
结论不覆盖独立的960 MHz `Fs/4`固定杂散；后者仍作为ADC交织offset候选继续调查。

当前XCI已是12x interpolation、normal DAC mode且inverse-sinc关闭。AMD的
[RF-DAC Nyquist Zone Operation](https://docs.amd.com/r/en-US/pg269-rf-data-converter/RF-DAC-Nyquist-Zone-Operation)
说明normal mode对第二Nyquist镜像只有DAC sinc包络衰减；
[Inverse Sinc Filter](https://docs.amd.com/r/en-US/pg269-rf-data-converter/RF-DAC-Inverse-Sinc-Filter)
用于补偿第一Nyquist内的sinc下垂，不是模拟重构滤波器，不能作为2.90 GHz镜像的
抑制方案。Stage 33第一Nyquist DAC到ADC纯度回环必须在DAC输出后加入重构低通或
频段滤波器；要把当前约`-41 dBc`互调压到`<=-50 dBc`，理论最低需要约9 dB的有效
抑制，工程门禁建议在2.90 GHz至少提供20 dB衰减余量。

### ADC固定交织杂散转入Stage 33a

Stage 33的3.84 GS/s升级在第一Nyquist区内暴露出独立的RFADC固定交织残差。
八路ADC、160/320 MS/s两模式和NCO偏移复核共同确认480、960、1440 MHz三条
主固定线；raw-preview绝对幅度约`-93.95..-82.64 dBFS`。连接器侧SSA没有检测到
对应窄线，PFB前raw preview已经看到相同结果，因此该项不是TG、DAC、DDC、PFB、
packetizer、CMAC、Rust或Web生成。它不破坏Stage 33已经通过的宽带吞吐、协议和
防clip能力，但会污染固定RF邻域的长积分弱谱线，Stage 33继续保持`RF_PARTIAL`。

完整定责、全带原始UDP证据、被否决方案、科学性能边界以及“受控校准＋固定前馈
扣除”的有条件修复建议统一转入
[`Stage 33a`](33a_adc_fixed_spur_characterization_and_mitigation.md)。Stage 33不实施
OCB1生产override、notch、持续自适应消除或RTL扣除，也不因此回退Stage 32已经
验收的数据面。

### 162端8089内存占用定责、部署修复与soak

2026-08-04对采集机`192.168.100.162`做只读诊断时，`t510_time_rx`已运行约6小时，
RSS从约110.3 GiB继续升到112.9 GiB，其中`RssAnon=100.33 GiB`、
`RssFile=12.59 GiB`，整机只余约6.3 GiB可用内存。连续60秒采样RSS增加447,436 KiB，
即约7.46 MiB/s或26.8 GiB/h，属于会最终触发OOM的无界匿名堆增长，不是浏览器正常
缓存。进程CPU约21.8%，文件描述符32、线程30，没有对应数量的连接或文件泄漏。

其中约12 GiB是可解释且有界的AF_PACKET映射：服务使用24个fanout worker，
`--ring-mb 512`在当前实现中是每worker 512 MiB，而不是全进程总量；API中的聚合
`ring_bytes`也按24倍报告。这个固定映射解释`RssFile`，但不能解释约100 GiB匿名堆。
本次先不降低ring，避免在41.6/83.2 Gbit/s门禁尚未复测前把内存修复和收包裕量变化
混在一起；部署修复后的健康稳态预期仍会保留约12..14 GiB RSS。

第一层无界增长定位到Spectrum Web preview的所有权和复制路径。一个完整频谱仅数组
数据就有`8 lanes * 4096 bins * 3 float32 = 393,216 bytes`。旧实现每收到16个SPEC
block中的一块就调用`FullSpectrumAssembler::snapshot()`深拷贝一次完整频谱，即每个
真正发布周期产生约6.29 MiB临时数组复制；约10.97次/s更新时仅该处就有约69 MiB/s
分配周转。发布时又保留一份从未被读取的结构化snapshot并编码一份binary；Spectrum
WebSocket还会深拷贝约384 KiB binary。服务器没有保存历史频谱队列，主故障是反复
深拷贝和多线程allocator retention。

仓库内第一组修复保持API、WebSocket binary格式和Rust科学数据解释不变：SPEC payload
直接解码到预分配assembler lane；只在16块完整后编码binary；删除SharedState中从未
读取的结构化waveform/spectrum副本；binary改为带有界spare pool的`Arc<Vec<u8>>`，
WebSocket只增加引用计数；WebSocket帧头改为栈数组；worker统计通道先由无界改为有界，
HTTP处理由每连接一线程改为固定16 worker、128连接队列。逐项候选把匿名RSS斜率从
原始约7.46 MiB/s降到约0.2 MiB/s以下，但仍能观察到慢速线性增长，因此没有把中间
候选误标为通过。

对候选j做`paused=true/false` A/B后，即使暂停频谱预览，匿名RSS仍约每10秒增加
0.7..1.1 MiB；20秒`strace -f`仍记录52次`mmap`、52次`munmap`和20次`mremap`，且
调用来自多个收包worker。这排除了剩余增长来自ADC谱计算。代码回查确认24个fanout
worker每100 ms都会克隆`WorkerStats + Vec<FlowStats>`后跨线程发送：内存在worker
线程分配，却在聚合线程释放，glibc为不同worker arena不断保留新的64 KiB小堆。

最终候选k把24份worker report改为启动时预分配的共享槽位；worker每秒只原位覆盖，
聚合线程在自己的可复用存储中取快照，统计发布频率与本来就为1 Hz的速率计算一致。
频谱binary发布和WebSocket发送仍按现有实时节奏运行，所以8089画谱刷新没有被降成
1 Hz。新增回归测试还显式检查report刷新后`per_flow`底层指针不变。Time receiver
Cargo回归共`41/41 PASS`，静态aarch64候选为
`stage33-rx-memory-fix-20260804k`，binary SHA-256为
`f45ec2373572212aceabfc48a0bacad97bcd39ee8a9770a270e61f78f2c61c81`。

用户确认允许重启后，候选k已部署到`192.168.100.162`并恢复160 MS/s、SPEC_ONLY、
center=960 MHz。服务启动造成的累计kernel/ring drop `3281991`和SPEC seq/frame gap
`283/283`先冻结为基线，不计入活动窗口。随后从2026-08-04 14:12:42到14:22:51做
609秒soak：21个30秒采样点的`RssAnon`全部为`3956 KiB`，首尾`VmRSS`均为
`12588096 KiB`，匿名RSS斜率为0；`RssFile=12584140 KiB`保持不变，对应保留的有界
24×512 MiB packet ring。活动窗口kernel/ring/app drop增量`0/0/0`、SPEC seq/frame
gap增量`0/0`、report drop增量0、`last_error=null`；包率
`624487.9..625163.2 pps`，总线速`41.7757..41.8209 Gbit/s`，Spectrum持续live。
binary cache allocations首尾均为2，期间只把reuse从737增加到6487。因此分类更新为
`HOST_8089_MEMORY_FIX_DEPLOYED / HOST_8089_MEMORY_SOAK_PASS`。完整证据为
`stage33_host_8089_memory_soak_20260804.json`。

### 五种生产模式60秒回归

| 模式 | center | 主机包率 | T510 payload | 结果/证据 |
| --- | ---: | ---: | ---: | --- |
| 160 TIME_ONLY | 200 MHz | TIME 625,133.6 pps | 41,608.89 Mbit/s | PASS |
| 160 SPEC_ONLY | 960 MHz | SPEC 625,052.7 pps | 41,603.51 Mbit/s | PASS |
| 160 TIME_SPEC | 200 MHz | TIME 625,265.9 + SPEC 625,295.6 pps | 83,237.37 Mbit/s | PASS |
| 320 TIME_ONLY | 200 MHz | TIME 1,250,449.1 pps | 83,229.89 Mbit/s | PASS |
| 320 SPEC_ONLY | 1760 MHz | SPEC 1,250,325.1 pps | 83,221.64 Mbit/s | PASS |

五项主机parse/kernel/ring/worker/app drop及TIME/SPEC sequence/frame/sample0 gap增量
全部为0；板端RFDC/science/TIME/SPEC/TX/route drop/error增量全部为0；需要SPEC的
三项PFB/XFFT/overflow/halt/TLAST/backpressure/coefficient error增量全部为0。960
和1760 MHz两项的全部ADC/DAC NCO分别精确读回`-center/+center`，四tile PLL锁定、
12x、Nyquist zone 1和16/16 valid mask保持正常。

320模式在START前已有`rfdc_dropped=19`启动基线，60秒窗口内保持不变。这沿用
Stage 32已经记录的启动计数语义：门禁要求活动窗口增量为0，不把START前基线伪装为
科学数据丢失。1760 MHz结束快照恰遇一次合法CMAC `TREADY`低，物理GT/CMAC/RX
健康位和实际流量均正常，因此只保留backpressure warning，不改变PASS。

### 2026-08-04 精确单样点bit正式发布收口

精确单样点构建在80/940 MHz直接SSA通过后，使用同一bit SHA重新执行正式MTS。
discovery的20次RFDC reset、10次overlay reload和10次LMK reload共40/40通过，观测
ADC/DAC最大latency为`432/72`，固定target为`452/88`。第一次fixed在最后一次LMK
reload遇到ADC0 restart state 6超时，按规则判为39/40失败；LMK reload settle window
从1秒增至3秒后，以fresh bit download重跑，最终fixed 40/40通过，零MTS错误。ADC
四tile固定为456，DAC四tile为84或92，均在12x量化允许的target `+/-6`内。

catalog已由最终discovery/fixed证据定版，combined evidence SHA-256为
`a8199588f9f0cec7d4d130f011ac03626a3cb524cbcc8def86aacdd79d482f4a`。
当时的build/report latest和顶层`overlay/`均已提升到bit SHA
`7657d4c7982343d55bb10c51186fbbd720dd2172b0e8ab3e64861c23801b771d`。
117正式release为
`/opt/t510-agent/releases/stage33-one-sample-7657d4c79823-mts452-88-20260804a`，
Agent和reference watchdog均active、healthy；旧release保留回滚。

正式release的fresh configure明确返回上述路径和SHA，RFDC 3.84 GS/s、12x、80 MHz
AXIS、Nyquist zone 1、16/16 valid、全部tile PLL和MTS读回通过。随后以160 MS/s、
TIME_ONLY、center=200 MHz运行10秒板端+162联合门禁，接收`6,276,880`个TIME包、
payload约`41.779 Gbit/s`；8路sequence/sample0 gap和板端/主机drop/error增量均为0，
分类为`STAGE33_160MSPS_TIME_ONLY_BOARD_HOST_PASS`。fresh configure、联合门禁和主机
明细JSON的SHA-256依次为
`bc7041f32d75af9583df261d1d68baf4f903da9c18044780d1005b91937ff27a`、
`85f44117549dcddffff24d13c8ea508fe77238efe1b09f614b14bf01cafccb56`和
`e55885b47aab5b4c3b390a3e4ffd0e4ca052787fa9bf429ec57cd7635b0a2d89`。门禁后science
正常停止。

本次发布闭合数字DAC I/Q one-sample修复；它不改变Stage 33a的ADC固定杂散结论，也
不把未滤波DAC采样镜像误标为数字I/Q回退。后续重构滤波、1.90 GHz闭环和长时间射频
门禁仍按`RF_PARTIAL`继续。

### 2026-08-05 DDS LUT修复与Stage 33a终止

当前正式bit已提升为DDS LUT修复版，SHA-256为
`23c3eb507558820e786dd7247b6b43a59a2f3141ed3599d1f6655f19de5dd3da`，WNS/WHS为
`+0.062/+0.010 ns`。100 MHz旧/新原始UDP A/B中，20、180、260 MHz齿分别改善
`7.59/10.24/8.59 dB`，主音和噪声仅变化约`-0.03 dB`。频谱仪直测DAC输出路径时，
除200 MHz外的20 MHz栅格为`-84.88..-91.26 dBc`；200 MHz二次谐波为
`-61.88 dBc`，中间20 dB低噪放的贡献未拆分。该性能接受为功能回环等级。

ADC TIME原始数据在PFB前已经看到剩余20 MHz栅格，DSA A/B又证明多数残余位于ADC
衰减器之后；因此PFB不是生成源，剩余项也不能继续归为DDS LUT。Stage 33a对
480/960/1440 MHz RFDC固定杂散的最终状态为
`TERMINATED / ACCEPTED_WITH_KNOWN_LIMITATIONS / NO_PRODUCTION_MITIGATION`。不再实施
OCB1 override、notch、自适应/前馈扣除或新的RTL修复。

### 终止后已知边界

- AutoCal已经以物理结果否决，不再作为1020 MHz杂散修复路线。外部TG 940 MHz已
  证明ADC接收链达到当前离散门限；强1020 MHz已定责为未滤波DAC采样镜像参与模拟
  输入端互调。外部TG下仍存在`-57.76 dBc`残余，不能写成“完全没有1020峰”。
- 已确认480/960/1440 MHz `k*Fs_ADC/8`固定杂散族：完整160/320全频普查、
  多NCO raw-preview、受控50 ohm终端、前景reset、CalFreeze、dither和OCB1 override
  A/B均已完成；SSA在三点的100 Hz RBW直测均只有约`-113 dBm`噪声，RFDC/PFB内部却
  保持12..29 dB相干可见度，但绝对最坏值只有2.42 ADU/`-82.64 dBFS`。一次性静态
  复矢量扣除因15秒漂移而否决，持续自适应扣除会
  吞掉三个真实RF频点；“锁OCB1 + 静态扣除”只保留为历史离线模型，不进入生产。
  不允许用软件隐藏bin、简单notch或牺牲完整第一Nyquist频带；只声明一般采集可用，
  不声明三个污染区具备无条件科学动态范围。
- 保留Stage 32已经通过的正复数DDS、精确单样点修复和API RF频率语义。在DAC输出后
  加入合适的重构低通或频段滤波器，再使用已确认的DAC到ADC物理回环执行
  center=200/960/1760 MHz和约1.90 GHz离散点的相位/幅度/SNR、镜像与`-50 dBc`
  杂散门禁；不能用DSA牺牲动态范围，也不能在无滤波直连结果上放宽门限。
- 使用独立信号源或第二台频谱仪直接测SSA3032X Plus TG源端，完成最终定责；现有
  拔线、频移、Zero Span和板内50 MHz对照已把`+91.71875 MHz`强边带收敛到TG
  外部输入路径，但仍只接受“ADC频率轴通过、输入源纯度失败”的正式结论。
- 执行160 TIME_SPEC、320 TIME_ONLY、320 SPEC_ONLY各10分钟soak，冷启动/服务恢复，
  以及全部DAC启用的60分钟热稳定性测试。
- `latest`已绑定本次正式bit；上述剩余物理项继续作为Stage 33完整RF验收门禁，失败
  时不得伪写完整PASS，也不得无证据切换到新bit或新target。

## 非目标

- 不实施 `for_me.md` 后续的 +/-8192 ADU限幅。
- 不执行完整 bandpass扫频或通道平坦度验收，仅执行计划中的离散频点门禁。
- 本阶段保持单板发布范围；第二块物理板可用后再验收多板相位同步。
- 不修改1024-bit science bus、PFB规格、TIME/SPEC产品语义或UDP字节布局。
