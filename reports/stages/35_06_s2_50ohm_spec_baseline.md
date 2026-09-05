# Stage 35 步骤 6：S2 三次 15 min 50 Ω SPEC 基线

> 状态：`COMPLETE`
> 前置条件：[步骤 5](35_05_s1_time_adu_control.md)已完成

## 1. 本步目标

用生产 v34 F-engine 对 8 路独立 50 Ω 终端取得三次相互独立、配置不变的 15 min 全频段
自相关扫描，并在每次 SPEC 扫描前后取得 30 s TIME 控制观测。

## 2. 固定完整队列

```text
TIME pre 30 s -> SPEC scan A 15 min -> TIME post 30 s
TIME pre 30 s -> SPEC scan B 15 min -> TIME post 30 s
TIME pre 30 s -> SPEC scan C 15 min -> TIME post 30 s
```

每次使用独立 `scan_id`，不更换输入、不调整 ADC 参数。若用户明确把它作为长任务提交，
必须一次性武装整个队列，阶段成功后自动接续；失败才停止并保留现场。确认完整队列健康启动
后立即停止轮询并交还控制权，不能把 A 扫描启动或完成称为整个步骤完成。

## 3. 运行前条件

- 8 路独立 50 Ω、DAC 断开、外部 10 MHz/PPS 断开、板内时钟；
- 空调稳定开启，室温、负载附近温度、板温和电压可记录；
- 磁盘空间覆盖三扫描最坏预算和 C 层片段；
- bitstream、PFB、receiver、writer、manifest schema 与原生桶宽冻结；
- 不存在另一个生产 UDP 消费者。

## 4. 产物与完成条件

- A/B/C 三个独立全频段数据立方体及各自 manifest；
- 六组 TIME 控制观测；
- 全局和逐 block 数据质量账本；
- 每个文件的大小、SHA-256 和数据集清单哈希；
- 安全收尾与最终任务/队列状态。

只有原队列最终状态和全部证据核对完成，才把本步标为 `COMPLETE`。噪声形状不在本步作
pass/fail，科学解释属于[步骤 7](35_07_autocorrelation_analysis.md)。

## 5. 执行记录

### 5.1 完整队列提交

2026-08-31 17:10:55 CST 已在采集机 `192.168.100.162` 一次性提交完整九阶段队列：

```text
queue_id: stage35-s2-50ohm-baseline-20260831-1706
unit:     t510-stage35-s2-20260831-1706.service
root:     /var/lib/t510/stage35/stage35-s2-50ohm-baseline-20260831-1706-queue
```

队列状态文件在硬件操作前即写入全部九阶段，而不是只提交 scan A：

```text
A TIME pre 30 s -> A SPEC 900 s -> A TIME post 30 s
B TIME pre 30 s -> B SPEC 900 s -> B TIME post 30 s
C TIME pre 30 s -> C SPEC 900 s -> C TIME post 30 s
```

同一持久化 runner 在每阶段成功后自动进入下一阶段；任一阶段失败会停止板端、保存错误和
安全收尾证据，不自动重试。receiver/板端模式切换只使用已验证的 clock-preserving 更新，
每次都重新核对 bitstream、LMK profile/SHA、双 PLL、RFDC active/valid mask、MTS target 和
DAC mask。三次 SPEC 的 begin/end 均取得逐 block 短原始 PCAP，首个 TIME pre 还取得并裁剪
连续 50 ms TIME PCAP；所有正式窗口保存前后计数器与30 s间隔的电源/温度遥测。

### 5.2 提交前门禁

- 采集盘可用 `3,768,096,821,248` bytes，显著高于队列固定的250 GiB最低门禁；
- receiver 两个 Stage 35 controller 均无活动任务，唯一生产 receiver 服务为 active；
- 板端 `streaming=false`、DAC mask 0、core `0x00010034`、320 MS/s TIME-only、center
  1020 MHz、TCXO双PLL锁定、RFDC active/valid `0xffff`、MTS ADC/DAC `416/112`；
- receiver 二进制 SHA-256 为
  `99dd0407316630212b9c99d81f19990bd8685c8b29235546ea364bb7178bfbe6`；
- 冻结 runner SHA-256 为
  `c9a6b6fd118ad33b1c057e43008b359a32a221f540c8c46d386b20627a4597e9`。

物理输入仍按操作者先前确认的 Stage 35 八路独立50 Ω接法和外部10 MHz/PPS已断开执行；设备
没有连接器、室温或负载附近温度传感器，因此这些事实不能由远程软件再次证明。板上可读温度
和电压会随队列记录。

### 5.3 首次队列失败与根因

用户要求检查后确认首次远端 unit 已于2026-08-31 17:14:38 CST以exit status 1停止。
`queue_state.json` 为 `failed`：A TIME pre完整完成，A SPEC及后续阶段未执行。A TIME pre
为37,500,000包、每路9,600,000,000样本，missing/reorder/duplicate均为0；manifest
SHA-256为`64838afd02acf19962be1c94faa54052ca2da65357a13b78ae023adbd1f8e858`。
随附50 ms TIME PCAP也连续无断点，SHA-256为
`c83f3ad364cb6e5616629477e8d6f873bfdb35b83111784692416f9c691e8360`。

失败发生在A SPEC正式900 s窗口之前的短PCAP门禁。runner错误地要求
`stream_type=2`，而仓库协议常量明确为`STREAM_SPEC=0`。失败现场PCAP实际为4,096包，端口
4308–4323各256包，payload均8,320 bytes，magic为`0x54353130`，16个block内部的
seq/frame/sample0步长均为`16/16/4096`且无断点；文件SHA-256为
`71eccc5d36b235f20b48c865de011f8e8b363ee911b0f5b0f0a87ed5ca7a0295`。因此这是host
校验器假阴性，不是SPEC数据损坏或板端丢包。原队列按fail-closed策略正确停止，最终板端
streaming false、DAC mask 0、PLL 1/1、RFDC active/valid `0xffff`，receiver速率和全部
drop/gap均为0。

提交过程中还曾误向开发机systemd发出同名命令；它在`CHDIR`、启动Python之前以
`status=200/CHDIR`失败，采集机无队列目录、板端无操作。该事件不构成数据扫描，也没有
复用或覆盖任何`scan_id`。

### 5.4 修正与完整替代队列

校验器已改用`STREAM_SPEC=0`，并允许失败安全收尾后板端/receiver一致处于合法
`time_only`或`spec_only`模式，再由首阶段内部执行受控模式切换。修正后直接复读上述失败
现场PCAP PASS；九阶段定义仍为9项、正式观测总时长2,880 s。修正版runner SHA-256为
`b64ff16b33c866de43ae2530c38af913211f3b98d69c770300c968fb63bebca4`。

旧队列保持`failed`且不续跑、不覆盖。经用户授权，2026-08-31 17:39:23 CST使用全新身份
一次性提交从A TIME pre开始的完整替代队列：

```text
queue_id: stage35-s2-50ohm-baseline-r2-20260831-1738
unit:     t510-stage35-s2-r2-20260831-1738.service
root:     /var/lib/t510/stage35/stage35-s2-50ohm-baseline-r2-20260831-1738-queue
```

健康检查时远端unit为`active/running`、MainPID `335442`，状态文件一次性包含全部九阶段，
当前索引0、其余八阶段pending、queue error为null。A TIME pre正式capture已经完成并进入该
阶段的C层TIME原始片段处理，unit仍由同一进程自动接续。这里不把首阶段完成写成步骤6完成；
按长任务规则，确认替代完整队列健康后已停止轮询。

### 5.5 r2 STOP响应失败与r3完整队列

用户再次要求检查后，确认r2于2026-08-31 18:25:05 CST fail-closed停止。r2已经完整封存
A/B两次15 min SPEC以及A/B各自的TIME pre/post；其中B TIME post虽然在状态文件中标为
failed，但其30 s数据集已经完成，manifest SHA-256
`a9f402630ca5c840800d255b63347a393332e7414fb0c3a0a40e46f24e9240d1`自校验一致，
37,500,000包、每路9,600,000,000样本，逐flow和正式窗口所有drop/gap均为0。失败发生在
数据封存后的板端STOP HTTP响应读取：`ConnectionResetError: [Errno 104]`。后续安全收尾
无错误且证明板端已经停止，因此这不是正式观测数据质量失败；C组未执行，r2仍不能算完整
S2队列。

r2同时暴露了遥测读取未传`since_seq`的问题：每次轮询都返回4,096 s完整历史，两个15 min
阶段各生成约1.8 GiB遥测JSON。r3作如下加固：

- STOP传输异常后不盲目重复mutation；只做新状态读取，且仅当`streaming=false`及完整板端
  身份门禁通过时，把原STOP按幂等成功接受；
- 每阶段从正式窗口起始sequence增量读取power/thermal记录；现场2 s测试只返回4条、
  33,485 bytes，不再重复完整历史；
- 模拟STOP连接重置、增量遥测和r2真实SPEC PCAP均回归PASS。

修正版runner SHA-256为
`cb83412735589b8e825b610e6d268af6aa2df99120585ee1e400a734c4b3e832`。r1/r2和所有数据
均原样保留，不续跑、不覆盖。经用户授权，2026-08-31 18:41 CST又以全新身份一次性提交
从A开始的完整r3九阶段队列：

```text
queue_id: stage35-s2-50ohm-baseline-r3-20260831-1838
unit:     t510-stage35-s2-r3-20260831-1838.service
root:     /var/lib/t510/stage35/stage35-s2-50ohm-baseline-r3-20260831-1838-queue
```

健康检查时unit为`active/running`、MainPID `426082`，queue为`running`、phase_count 9、
current index 0、error null；A TIME pre generation 7处于`running`，其余八阶段pending并由
同一进程自动接续。确认完整r3队列健康后已停止轮询。只有用户通知r3结束或明确要求检查后，
才读取原r3 unit、状态、九个数据集和最终验签；当时不得标为`COMPLETE`。

### 5.6 r3原始片段失败、同步序号门与r4完整队列

用户要求检查后确认r3已于2026-08-31 18:42:19 CST以exit status 1停止。第一个A TIME pre
正式30 s数据集已经完整封存：37,500,000包、每路9,600,000,000样本，逐flow的missing、
reorder、duplicate均为0；manifest SHA-256为
`b1835eca55ad7e275c2f6f49398c6b7ebf878a23a0a4ccbb214fb26770dd1236`且自校验一致。
失败只发生在随后附加的50 ms原始PCAP门禁：52.4 ms超集中最长连续段为61,573包，少于要求
的62,500包；后续八阶段未执行。安全收尾证明板端streaming false、DAC mask 0、双PLL锁定。

三次52.4 ms超集的八接收线程起点偏斜分别为3,004、1,107和3,970个全局包，说明问题不是
正式10 ms桶丢包，而是各fanout worker在不同时间看见原始抓取请求。单纯把每流缓存增至
9,216包的实流试验仍因某线程提前11,831包而只得到61,904包公共连续区间，因此没有用继续
扩大近GB级缓存掩盖调度问题。receiver改为同步未来序号门：首个worker只设定65,536包后的
统一、按八流周期对齐的起点，各worker到达同一序号区间后才写入原始证据。正式TIME数据的
10 ms原生桶、schema和完成条件均未改变。

该修正仅热重启采集机receiver，板卡未断电、未重载bitstream。完整Rust测试65项PASS；
实流回归超集65,536包全部连续，成功裁出62,500包、每路16,000,000样本、严格50.000 ms且
seq/frame/sample0无断点，裁剪PCAP SHA-256为
`c6cd9d08b707b2bfea01693c63e0e5ce88448f8256f8d65b81056359cf266d4b`。抓取前后receiver
kernel/ring/app和板端正式计数器增量均为0。新receiver SHA-256为
`b4c33fc10a0179a8adfc0f982448c9539c3eb6db2d5e559750ecc16c0a91662a`；冻结runner仍为
`cb83412735589b8e825b610e6d268af6aa2df99120585ee1e400a734c4b3e832`。

r1–r3及诊断现场均原样保留。经用户授权，2026-08-31 19:16 CST以新身份一次性提交完整
r4九阶段队列：

```text
queue_id: stage35-s2-50ohm-baseline-r4-20260831-1915
unit:     t510-stage35-s2-r4-20260831-1915.service
root:     /var/lib/t510/stage35/stage35-s2-50ohm-baseline-r4-20260831-1915-queue
```

10 s与20 s健康检查时unit均为`active/running`、MainPID `498120`；状态文件一次性含全部
九阶段，queue为`running`、current index 0、error null，A TIME pre generation 1正式窗口
为`running`，其余八阶段pending并由同一进程自动接续。确认健康后已按长任务规则停止轮询；
步骤6仍为`IN_PROGRESS / FULL_QUEUE_ARMED`，不能提前标为`COMPLETE`。

### 5.7 r4最终验收

用户要求检查后确认r4已于2026-08-31 20:24:08 CST正常退出，systemd `Result=success`、
queue `status=completed`、error null。A/B/C三次900 s SPEC及六次30 s TIME均为completed。

- 三次SPEC独立复读均为`PASS`，missing/duplicate/reordered/late、gap range和arrival event全为0；
- 六次TIME各为37,500,000包、每路9,600,000,000样本，逐flow事件全为0；
- 九阶段的板端drop、receiver kernel/ring/worker/app drop、seq/frame/sample0 gap及NIC即时错误
  增量全为0；
- 队列manifest标记complete，含9个scan和115个队列证据文件；manifest自身SHA-256为
  `bb88abf0ae63b70d5bae33f2a21f8308fe1bceabc829ce0c3104c1b62ce6a6ef`，逐文件大小和
  SHA-256复核无误；
- 最终安全状态为streaming false、receiver 0 packet/s且无active worker、DAC mask 0、
  双PLL锁定、RFDC active/valid均为`0xffff`。

至此步骤6的三次独立50 Ω生产F-engine基线、六组相邻TIME控制和全部质量账本闭合，状态
正式改为`COMPLETE`；科学解释转入[步骤7](35_07_autocorrelation_analysis.md)。
