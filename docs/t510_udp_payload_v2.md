# T510 TIME/SPEC UDP Payload v2

本文是当前 T510 F-engine 的 TIME 与 SPEC UDP 线格式合同。RTL 发送端、Python
诊断代码、Rust 接收机和下游程序都应按本文解释 UDP payload；`sample0` 始终属于
RFDC 的 `320 MS/s` 复基带时基，不能按 `3.84 GS/s` 模拟采样时钟解释。

## 帧与报文长度

TIME 和 SPEC 使用相同的定长外层结构：

| 层次 | 字节数 | 内容 |
| --- | ---: | --- |
| Ethernet II header | 14 | 无 VLAN tag |
| IPv4 header | 20 | IHL=5，protocol=UDP |
| UDP header | 8 | checksum 当前为0 |
| T510 header | 128 | 16个64-bit word |
| TIME 或 SPEC payload | 8192 | IQ16 数据 |

因此两类产品均满足：

- UDP payload（T510 header + 产品 payload）：`8320 B`
- UDP datagram（含 UDP header）：`8328 B`
- Ethernet frame（不含 FCS）：`8362 B`

接收机必须启用足以容纳该帧的 jumbo MTU。TIME 默认使用 UDP 端口
`4300..4307`，SPEC 默认使用 `4308..4323`；端口属于部署路由配置，不改变下面的
payload 布局。

## 128-byte 公共头

头由16个64-bit word组成。每个 word 在线上按 little-endian 字节顺序发送；下表的
位段则按读成 little-endian `u64` 后的逻辑位号表示。也就是说，应先用
`u64::from_le_bytes`/`unpack("<Q")` 读取，再按位拆字段。

| Word | bits `63..0` | TIME | SPEC |
| ---: | --- | --- | --- |
| 0 | `{magic[31:0], version[15:0], header_bytes[15:0]}` | `magic=0x54353130`，`header_bytes=128` | 同 TIME |
| 1 | `{board_id, stream_type, epoch_mode, flags}`，每项16 bit | `stream_type=1` | `stream_type=0` |
| 2 | `unix_sec[63:0]` | 公共时间元数据 | 同 TIME |
| 3 | `pps_count[63:0]` | PPS计数 | 同 TIME |
| 4 | `sample0[63:0]` | 本包首个 TIME 样本索引 | 产生本频谱块的 PFB 帧样本索引 |
| 5 | `frame_id[63:0]` | TIME 包帧号 | SPEC 包帧号 |
| 6 | `{seq_no[31:0], product_offset[31:0]}` | 低16 bit为`global_input0`，高16 bit为0 | `product_offset=chan0` |
| 7 | `{chan_count, time_count, ninput, payload_format}`，每项16 bit | `{0, 64, 8, 0}` | `{256, 1, 8, 0}` |
| 8 | `{scale_id[31:0], payload_bytes[31:0]}` | `payload_bytes=8192` | 同 TIME |
| 9 | `{product_id, nchan, block_index, block_count}`，每项16 bit | 全0 | `{0xf101, 4096, 0..15, 16}` |
| 10 | `{pfb_taps[15:0], fft_shift[15:0], spec_status_flags[31:0]}` | 全0 | 当前PFB/FFT参数与状态 |
| 11 | `{spec_sample_rate_hz[31:0], scale_mode[15:0], reserved[14:0], spec_half_band}` | 全0 | 频谱采样率、缩放和路由半带标志 |
| 12 | `sync_generation[63:0]` | 同步代号 | 同 TIME |
| 13 | `sync_observation_tag[63:0]` | 观测标签 | 同 TIME |
| 14 | `sync_metadata[63:0]` | `{signal_chain_tag, schedule_tag}` | 同 TIME |
| 15 | `sync_status[63:0]` | `{mts_result_id, scheduled_sync_status}` | 同 TIME |

基础头版本为2；当 `sync_generation != 0` 时，RTL 把 `version` 置为3，并启用
word 12..15 的调度同步扩展。当前接收机接受版本2和3。早期解析器曾把 word 15 的
低32 bit称为 `header_crc`；当前线上没有独立 header CRC，该位置属于
`sync_status`，不能再单独做 CRC 校验。

公共枚举和标志：

- `epoch_mode=0/1/2`：外部 PPS、仅内部时间、scheduled TAI。
- `payload_format=0`：每个复数值为 little-endian `i16 I` + `i16 Q`。
- `flags[0..5]`：依次为 time valid、internal epoch、QSFP link up、UDP dry-run、
  ADC clip、FIFO overflow；其余位保留。
- `seq_no` 和 `frame_id` 均按各自产品的已发送 UDP 包逐包递增。

## TIME payload

TIME payload 是64个连续的1024-bit science beat。每个 beat 含4个时间子样本、
每个子样本含8路复数输入，所以一个包对每路提供 `64 * 4 = 256` 个复样本。

每个复数值占4 byte：

- byte `0..1`：little-endian signed `i16 I`
- byte `2..3`：little-endian signed `i16 Q`

同一个64-bit payload word装相邻两路：低32 bit是偶数通道，高32 bit是奇数通道。
对 `beat b`、子样本 `s=0..3` 和输入 `ch=0..7`：

```text
word64      = b * 16 + s * 4 + floor(ch / 2)
byte_offset = 128 + word64 * 8 + (0 if ch is even else 4)
I           = le_i16(byte_offset + 0)
Q           = le_i16(byte_offset + 2)
```

TIME 的 `sample0` 是本包第一个样本在 `320 MS/s` RFDC 复基带时基上的索引。
API 的 `sample_rate_msps` 只决定 PL 采样步长：

| `sample_rate_msps` | 相对320 MS/s的步长 `decim` | 有效复采样率 | 相邻满包的 `sample0` 差 |
| ---: | ---: | ---: | ---: |
| 320 | 1 | 320 MS/s | 256 |
| 160 | 2 | 160 MS/s | 512 |

包内第 `b * 4 + s` 个逻辑样本的绝对索引为：

```text
sample_index = sample0 + (b * 4 + s) * decim
```

TIME 接收机应同时检查 `seq_no`、`frame_id` 和上述 `sample0` 增量。任何不连续都应
标记为 gap，不得在显示或后处理时插值掩盖。

## SPEC payload

当前唯一接受的 SPEC 产品为 `FENGINE_IQ16 (product_id=0xf101)`：

- `nchan=4096`
- `block_count=16`
- 每包 `chan_count=256`
- `time_count=1`
- `ninput=8`
- `payload_format=0`（IQ16）
- `pfb_taps=8`
- `spec_status_flags[10]`（PFB active）必须为1
- `spec_status_flags[8]`（旧 FFT-only 标志）必须为0

每包只携带完整4096-bin频谱的一个连续块：

```text
block_index = 0 .. 15
chan0       = block_index * 256
global_bin  = chan0 + chan_idx
```

payload 顺序是 time-major、channel-major、input-minor。对
`time_idx=0..time_count-1`、包内 `chan_idx=0..chan_count-1`、
`input=0..ninput-1`：

```text
complex_index = (time_idx * chan_count + chan_idx) * ninput + input
byte_offset   = 128 + complex_index * 4
I             = le_i16(byte_offset + 0)
Q             = le_i16(byte_offset + 2)
```

当前参数给出 `1 * 256 * 8 * 4 = 8192 B`。接收机用 `block_index` 建立16-bit
coverage mask；只有0..15全部出现，才构成完整4096-bin频谱。当前 Rust assembler
用 `floor(frame_id / block_count)` 归组，因此同一完整频谱的16个块必须连续发送，
并保持 `seq_no/frame_id` 逐包连续。

SPEC 的 bin 保持 FFT 原始顺序。令 `k=global_bin`、`Fs=spec_sample_rate_hz`：

```text
signed_bin = k                    , k < 2048
             k - 4096             , k >= 2048
baseband_hz = signed_bin * Fs / 4096
rf_hz       = center_hz + baseband_hz
```

`Fs` 在当前模式下为160 MHz或320 MHz，对应 bin 宽分别为39.0625 kHz和
78.125 kHz。`sample0` 仍来自320 MS/s复基带时基；它用于标识产生该PFB帧的输入
时间位置，不能换算为3.84 GHz ADC索引。

`spec_status_flags[9]`表示160 MS/s路径的 anti-alias 滤波活动，bit 10表示当前
固定8-tap PFB产品有效；bits 7..0保留PFB运行状态。`spec_half_band`是按
`chan_split`生成的路由元数据，不改变 `global_bin` 或上述频率公式。

## 接收端最低校验

无论 TIME 还是 SPEC，接收端至少应执行：

1. 校验 `magic`、`version in {2,3}` 和 `header_bytes=128`。
2. 按 `stream_type` 选择 TIME 或 SPEC 解码，不按 UDP 端口猜 payload 类型。
3. 要求 `ninput=8`、`payload_format=0`、`payload_bytes=8192`，并检查实际 UDP
   payload 至少为8320 byte。
4. TIME 校验固定64 beat及 `sample0` 步长；SPEC校验当前
   `16 x 256 x 1`、`product_id=0xf101`、8-tap PFB和完整块覆盖。
5. 对 `seq_no/frame_id/sample0` 或 SPEC coverage 的异常显式报告 gap/drop。

当前实现对应的权威代码是 `rtl/time_udp_cmac512.sv`、
`rtl/spec_udp_cmac512.sv`、`python/packet.py` 和
`rust/t510_time_rx/src/lib.rs`。

## 接收机内嵌科学监视器

`/api/measure/spec-stability`只是在 receiver 已接收并验证的 SPEC 包内抽取少量 bin；
它不增加包字段、端口、socket 或旁路数据流。每个被选 bin 的八路 IQ16 以一秒为桶，
保存样本数、I/Q和、功率和及功率平方和；可选通道对另存
`sum(x_a*conj(x_b))`与两路功率和。这些充分统计量用于计算 dBFS/bin、积分斜率、
Allan deviation、相位和相干度。正式任务仍必须同时核对 receiver/FPGA 的全局
drop、gap、FIR saturation、XFFT overflow与backpressure计数；监视器结果不能替代
这些硬门禁。

currentd的正式任务使用100 ms或1 s的`sample0`分桶，一次累计八路自相关和28对
复互相关，并通过`/api/measure/spec-stability/data`导出TIS1。该功能只增加receiver
旁路统计和证据格式；FPGA header、payload、端口映射与包长完全不变。

## 全频段自相关采集器

当前 receiver 在同一个 receiver 和同一个 `PACKET_FANOUT` 消费组内增加全频段自相关采集，
不打开第二个 UDP/AF_PACKET 消费者，也不改变上述线格式。已通过 SPEC 合同校验的包在各自
256-bin block worker 内累加全部 8 路 IQ16；网页 preview 仍是独立的低频率显示旁路。

- 武装：`POST /api/measure/autocorrelation`
- 状态：`GET /api/measure/autocorrelation/status`
- 显式中止：`POST /api/measure/autocorrelation/stop`
- 数据根目录：receiver 参数 `--measurement-root`，每个合法 `scan_id` 只能新建一次，禁止覆盖。

请求固定包含 `scan_id`、`tuning_id`、`duration_seconds`、`native_bucket_ms`、
`sample_rate_msps=320`、`center_mhz`，并可带 `expected_fft_shift` 和字符串 metadata。
原生桶支持10/20/50/100 ms；正式首选10 ms。开始和结束都使用共同的 `sample0` 桶边界，
主机时间只记录控制事件。越过正式 end 后仍观察8个谱帧组才封口，保证最后一个桶也受有界
重排窗保护。

落盘为标准 Zarr v2 directory store：A层保存原生桶 `mean_power_count2`，B层保存100 ms的
`mean_i_count_100ms`、`mean_q_count_100ms`、`m2_power_count4_100ms`和
`clip_count_100ms`。`n_valid`、逐桶质量JSONL、gap range、chunk journal、逐文件SHA-256
和最终manifest同时保存。完整扫描即使整桶无有效帧，也会在质量账本中写出
`valid_frames=0`和实际`missing_frames`；缺失浮点数据使用Zarr NaN fill且`N_valid=0`，
永远不填功率零。已经提交质量行后才到达的duplicate/late包另存到只追加的
`arrival_events.jsonl`，按`bucket_index, block_index`与逐桶质量行合并，不能静默丢弃。
原生和100 ms质量行还保存桶内`spec_status_flags_or`，用于按曝光桶审计PFB/XFFT状态。
遇到writer队列溢出、配置身份变化或显式中止时，采集标为failed并封存未完成manifest；
不得把中断segment静默续写成同一数据集。

## 当前数值身份

`CORE_VERSION=0x00010036` 保持本文 IQ16、UDP header 和 payload 布局。`fft_shift`
仍是实际 XFFT 缩放调度 `0x0556`，不能用它编码 PFB 增益。新 core 的 8-tap 系数仍为
Q1.17，FIR 累加器在 IQ16 对称舍入前右移 16 位；相对 v34，此处电压尺度增加 2 倍。
RFDC 八路 QMC 使用增益 `16383/8192`、禁用相位校正、零偏置，并通过 TILE 事件更新。

仅凭 UDP 包不能确定 RFDC QMC 设置。新采集 manifest 必须保存配置时及采集前后实际回读
的 `digital_scaling`，包括 core、profile、八路 QMC、PFB 输出移位和 FFT 调度；身份缺失、
前后变化或不匹配时不得按 current 数值身份解释。`python/t510_scaling.py` 提供严格校验及
receiver 现有字符串 metadata 字段的序列化，不改变线上数据包版本。

和历史基线比较时，TIME 电压增益为 `g=16383/8192`，SPEC 电压增益为 `2g`。
电压除以对应增益，功率除以增益平方，ADC 对复可见度除以两路增益乘积；功率的 Allan
方差除以增益四次方。已除以均值平方的归一化 Allan 方差不再次缩放。保留原始 count
与统一尺度两套结果，尺度变化本身不构成科学性能改善。
