# T510 PYNQ 多板安装与部署手册

## 1. 目的与范围

本文档是 T510 F-engine 板端 Linux/PYNQ 软件的正式安装部署说明，面向将同一套
Board Agent、LMK控制、RFDC/MTS、reference watchdog和当前bitstream部署到一块
或多块 MicroPhase ANTSDR T510开发板。

本文档不记录某次开发阶段的过程状态，也不固定历史bitstream SHA或MTS target。
实际发布身份始终由当前`/opt/t510-agent/current`中的catalog和bitstream SHA决定。
UDP线格式见 [t510_udp_payload_v2.md](t510_udp_payload_v2.md)；当前候选的构建、MTS
和射频门禁状态见 `reports/stages/` 中最新的阶段报告。

部署到多块板不等于多板相位同步已经验收。每块板都必须独立完成硬件身份、时钟、
MTS和数据面门禁；需要同时预约启动时，再执行本文的多板同步检查。

## 2. 部署组成

一套部署包含：

- 开发机：保存源码、最终catalog和唯一当前构建产物，交叉编译aarch64 Agent；
- T510 PYNQ板：运行 `t510-agent` 与 `t510-ref-watchdog`，加载匹配的bit/HWH；
- 采集机：运行 `t510-time-rx`，通过100GbE接收TIME/SPEC；
- 外部参考：每块板接入符合系统要求的10 MHz与PPS；
- 管理网络：开发机能够分别访问每块板的SSH和Board Agent端口8010。

板端当前版本安装位置固定为：

```text
/opt/t510-agent/current/
/etc/t510-agent/config.json
/etc/systemd/system/t510-agent.service
/etc/systemd/system/t510-ref-watchdog.service
/etc/systemd/system/t510-agent.service.d/center-hub.conf
```

`current`目录安装后由root拥有并设为只读。现场修改其中内容是禁止的；任何修订都
必须由latest-only发布脚本完整覆盖，并重新核对catalog与哈希。

## 3. 板卡与系统前置条件

已知基线为：

| 项目 | 要求或已验证基线 |
| --- | --- |
| 板卡 | MicroPhase ANTSDR T510 / ZU47DR |
| 架构 | aarch64 |
| OS | PynqLinux 3.0，Ubuntu 22.04基线 |
| Python | PYNQ venv中的Python 3.10 |
| PYNQ | 3.0.1基线，必须能够导入 `pynq` 与 `xrfdc` |
| PYNQ venv | `/usr/local/share/pynq-venv` |
| LMK SPI | `spi1.0`，运行时设备 `/dev/spidev1.0` |
| FPGA | FPGA manager/XRT可用，硬件与release中的HWH匹配 |
| 存储 | `/opt`至少512 MiB可用 |
| 权限 | 安装和硬件helper需要root；日常REST控制不传入任意代码 |

在安装任何项目文件前，每块板都保存一份预检记录：

```bash
uname -a
cat /etc/os-release
/usr/local/share/pynq-venv/bin/python3 -V
/usr/local/share/pynq-venv/bin/pip show pynq
/usr/local/share/pynq-venv/bin/python3 -c 'import pynq, xrfdc; print(pynq.__version__)'
ls -l /sys/bus/spi/devices/spi1.0
ls -l /sys/class/fpga_manager
df -h /opt
for path in /sys/class/gpio/gpiochip*/{label,base,ngpio}; do
  test -e "$path" && printf '%s=' "$path" && cat "$path"
done
```

若kernel、PYNQ、xrfdc、SPI或GPIO映射与基线不同，先记录差异并做兼容性评审，不能
直接覆盖site-packages或假定另一块板的运行态文件可复用。

## 4. T510相对基础PYNQ的板端组件

### 4.1 LMK SPI与GPIO

`python/t510_clock.py`在需要时为 `spi1.0` 绑定spidev，并使用
`/dev/spidev1.0`以SPI mode 0、1 MHz访问LMK。项目不修改PYNQ site-packages。

当前ZynqMP GPIO基线为chip base 334，项目使用以下PS pin：

| 功能 | PS pin | 基线sysfs GPIO |
| --- | ---: | ---: |
| LMK reset | 29 | 363 |
| reference select 0 | 33 | 367 |
| reference select 1 | 34 | 368 |
| LMK SYNC | 78 | 412 |

代码使用PS pin并在运行时换算sysfs编号；每块板仍必须核对gpiochip base和板级连接。
LMK PLL1/PLL2 lock由PS读取寄存器 `0x182/0x183`，不能用PL侧RFDC ready或短期PPS
频差替代外部参考锁定判断。

### 4.2 PYNQ活动bit身份

CONFIGURE成功后，`python/t510_hw.py`按bit内容更新PYNQ活动bit状态，后续硬件请求会
再次核对活动bit与catalog。安装路径固定，硬件身份仍以内容哈希为准。

### 4.3 RFDC/MTS状态

每次fresh CONFIGURE都会重新写LMK profile、下载bitstream、初始化RFDC并执行
catalog指定的MTS。结果写入：

```text
/run/t510-mts.json
```

`/run`是tmpfs。不得把另一块板的MTS文件复制过来；每块板必须生成自己的真实测量
结果。部署到新硬件批次时，如果固定target在任一板上失败，必须阻塞共同release并
重新评审，不能只为该板静默提高target。

### 4.4 External-reference watchdog

常驻 `t510-ref-watchdog` 每100 ms检查LMK锁定。活动流期间连续失锁或连续SPI读取
失败会fail-safe STOP并锁存故障；参考恢复后不会自动重新打流，必须fresh CONFIGURE
和MTS才能清除fault latch。

运行态文件为：

```text
/run/t510-ref-watchdog.json
/run/t510-ref-watchdog.lock
/run/t510-configure.lock
```

CONFIGURE对最后一个文件持独占锁，watchdog在此期间进入配置暂停，不并发读取PL、
LMK或PYNQ MMIO。`center-hub.conf`中的 `ProtectKernelTunables=false` 是CONFIGURE
访问FPGA manager和动态spidev所需的服务覆盖，不能删除。

### 4.5 Stateless Board Agent

Board Agent是aarch64 musl静态二进制，默认监听8010，只提供固定API v2。每个硬件
请求启动固定的 `python/t510_hw.py` helper；REST调用不能提供文件路径或任意Python
代码。常用端点为：

```text
/health/live
/health/ready
/api/v2/info
/api/v2/capabilities
/api/v2/bitstreams
/api/v2/configure
/api/v2/status
/api/v2/start
/api/v2/stop
/api/v2/dac
/api/v2/sync/*
```

## 5. 发布前提

板端当前版本只允许从已验收源码和bit构建。构建前确认：

1. bit、HWH、BD Tcl和manifest来自同一次当前工程导出；
2. bitstream SHA与唯一catalog完全一致；
3. catalog中没有zero SHA、负MTS target或缺失的campaign proof；
4. MTS discovery/fixed和当前阶段规定的硬件门禁已经完成；
5. 要部署的每块板使用同一个已审核当前版本，板号与网络身份另行逐板配置；
6. 采集端目标MAC、IP、端口与现场拓扑一致。

配置、部署和发布入口均使用稳定的 `t510` 名称，不随工程阶段复制。脚本从 catalog
读取唯一 bit SHA 并对占位值故障关闭。

## 6. 在开发机生成当前版本

在仓库根目录执行：

```bash
scripts/t510_publish_board.sh --build-only
```

构建脚本会：

- 核对catalog和bitstream SHA；
- 交叉编译静态aarch64 Board Agent；
- 组装Python helper、watchdog、overlay、catalog和systemd资产；
- 验证二进制架构与静态链接；
- 固定覆盖开发机`build/board/latest/package`，不访问板卡、不下载bitstream；同级
  `build/board/latest/evidence`中的MTS和板级证据不得被打包过程删除。

多块板应安装同一份`latest`内容；身份由catalog SHA和bitstream SHA确定，不再生成
release ID、时间戳目录或本地回滚副本。

## 7. 多块板逐板安装

先建立板卡清单，每块板至少分配唯一管理地址、board ID、science source IP/MAC：

| 板卡 | 管理地址 | board ID | source IP | source MAC | receiver/端口组 |
| --- | --- | ---: | --- | --- | --- |
| board-a | 待填 | 待填 | 待填 | 待填 | 待填 |
| board-b | 待填 | 待填 | 待填 | 待填 | 待填 |

安装前停止该板science并保存旧服务状态。对每块板分别执行：

```bash
PYNQ_TARGET=xilinx@<management-ip> \
  scripts/t510_publish_board.sh --install
```

安装脚本会上传完整当前版本、校验catalog与bit，通过临时目录事务性替换
`/opt/t510-agent/current`、安装并重启Agent/watchdog，最后检查health和API v2。
成功后删除临时旧目录、历史`releases/`和远端staging，不保留回滚版本。
安装本身不下载FPGA；PL未配置时 `/api/v2/status` 返回 `PL_NOT_CONFIGURED` 是正常
的故障关闭状态。

sudo密码只允许交互输入或使用临时进程环境，不能写入仓库、文档、命令行日志或
release。

## 8. 安装后静态检查

在每块板执行：

```bash
test -d /opt/t510-agent/current
test ! -L /opt/t510-agent/current
test ! -e /opt/t510-agent/releases
systemctl is-enabled t510-ref-watchdog.service t510-agent.service
systemctl is-active t510-ref-watchdog.service t510-agent.service
systemctl status --no-pager t510-ref-watchdog.service t510-agent.service
cat /run/t510-ref-watchdog.json
curl -fsS http://127.0.0.1:8010/health/live
curl -fsS http://127.0.0.1:8010/health/ready
curl -fsS http://127.0.0.1:8010/api/v2/info | python3 -m json.tool
curl -fsS http://127.0.0.1:8010/api/v2/bitstreams | python3 -m json.tool
```

并在开发机核对所有板返回相同的bitstream ID、core version和catalog SHA。任何
一块板不同，都不能进入批量CONFIGURE。

## 9. 每块板首次CONFIGURE

以 `config/t510/configure_160_time_only.example.json` 为模板，为每块板设置：

- 唯一 `board_id`；
- 唯一且合法的source IP/MAC；
- 与采集机数据口一致的destination MAC；
- 现场规划的destination IP和端口；
- `sample_rate_msps`、mode与完整第一Nyquist频带内的center。

然后逐板执行：

```bash
python3 scripts/t510_agent_client.py \
  --base-url http://<management-ip>:8010 \
  configure <board-config.json> --board-id <board-id>

python3 scripts/t510_agent_client.py \
  --base-url http://<management-ip>:8010 status
```

CONFIGURE必须留下 `streaming=false`，并逐项核对：

- core version、bitstream SHA和board ID；
- LMK profile、PLL1/PLL2 lock与continuous SYSREF；
- ADC/DAC tile PLL、采样率、倍率、Nyquist zone和NCO readback；
- MTS result ID、目标值、四tile latency/offset；
- RFDC valid mask、FIFO、overflow和pipeline clean状态；
- watchdog为IDLE/healthy，fault latch未置位。

不要并行CONFIGURE同一块板，也不要复制另一块板的 `/run` 状态作为通过证据。

## 10. 数据面和采集端约束

标准receiver service使用一块板的24路流：TIME端口4300..4307，SPEC端口
4308..4323。多块板安装相同PYNQ release并不意味着它们可以同时向同一个receiver
实例和同一组端口发送；并发多板采集必须采用以下之一：

- 每块板使用独立采集机或独立物理接口/receiver实例；
- 为每块板规划不重叠的端口组，并相应部署独立receiver实例；
- 在完成明确的多板接收端扩展后，再共享一个接收进程。

每个receiver实例都要核对目标MAC、MTU 9000、硬件队列/ntuple、ring大小和测试窗
口内drop/gap delta。没有数据口L3地址不一定是错误：当前receiver使用AF_PACKET，
但链路、目的MAC和端口映射必须正确。

### SPEC 科学稳定性诊断

receiver 可从已有 PACKET_MMAP worker 内部选择最多 32 个精确 PFB bin 做正式 600/3600 秒
统计，不创建第二个 packet socket，也不改变 UDP 协议：

- `POST /api/measure/spec-stability` 启动异步任务；body 提供固定
  `duration_seconds=600`、`sample_rate_msps`、`center_mhz`、
  `rf_frequencies_mhz`或`signed_bins`，以及可选的`correlation_pair`。
- `GET /api/measure/spec-stability/status` 返回任务状态、16 个 block 的收包数和已完成秒数。
- `GET /api/measure/spec-stability/result` 在结束后返回逐秒八路
  `sum_power/sum_power_squared`及可选复数互相关累加量。
- Stage 34d扩展参数`bucket_ms=100|1000`、`correlation_mode=none|single|all`和
  `result_format=json|binary`。`all`固定计算八路的28对`Xi·conj(Xj)`，且要求
  `lane_mask=0xff`与binary结果；旧`correlation_pair`继续作为single兼容入口。
- `GET /api/measure/spec-stability/data`下载完成任务的小端`TIS1`。时间桶由
  FPGA `sample0`严格划分，文件包含target/pair映射、每桶首尾sample0、八路I/Q与
  功率矩、28对复相关实虚和样本数；`result`同时返回文件字节数及SHA256。

启动时 receiver Web 配置必须已经是相同 center/rate 的`spec_only`；接口只接受当前
固定600/3600秒合同和精确落bin的频点。运行中会检查全部16个block的v34可观察
数据合同（4096 通道、8 tap、采样率、chan0/block 映射）以及 seq/frame/sample0
连续性；任一不符立即失败。`CORE_VERSION`、PFB profile ID、MTS target、DAC 静音和
FPGA计数器由 campaign 同时通过 Board Agent 核对，因为这些字段并非都在 UDP v2
header 内。

## 11. 可选多板预约同步

只有当所有板已经用同一release完成CONFIGURE，且sample rate、mode、center、外部
10 MHz/PPS和科学路径规则一致时，才运行多板预约：

```bash
python3 scripts/t510_multiboard_sync.py \
  --board http://<board-a>:8010,<board-a-id> \
  --board http://<board-b>:8010,<board-b-id> \
  --generation <positive-generation> \
  --epoch-tai <tai-seconds> \
  --signal-chain-tag <nonzero-tag> \
  --output build/receiver/latest/evidence/multiboard_sync.json
```

协调器先读取每块板当前PPS与MTS result，全部prepare成功后才arm；部分失败会对已
prepare板执行best-effort abort。脚本通过只证明数字预约和数据进度，不能替代多板
物理相位、线缆延迟和RF闭环验收。

## 12. 逐板验收

每块板至少完成：

1. Agent/watchdog active，API v2和OpenAPI可读；
2. fresh CONFIGURE/MTS及固定target readback通过；
3. STOP状态pipeline clean；
4. TIME_ONLY、SPEC_ONLY及支持的TIME_SPEC模式打流；
5. 采集机测试窗口内kernel/ring/app drop与seq/frame/sample0 gap增量均为0；
6. 活动预约流断PPS后PL自动停流并锁存错误；
7. 活动流断10 MHz后watchdog fail-safe STOP；
8. 参考恢复后直接START仍被拒绝，fresh CONFIGURE/MTS后才恢复；
9. 冷启动、服务自启和恢复门禁；
10. 当前release定义的RF频点、soak与热稳定性门禁。

物理10 MHz与PPS必须分别故障注入，不能同时拔线，否则无法判断保护层级。

## 13. 失败处理和禁止事项

任何安装、CONFIGURE或门禁失败都先STOP science、mute DAC、保存Agent/watchdog/
MTS/采集端必要诊断，再修复当前版本。禁止：

- 混用不同构建的bit、HWH、Python helper、catalog或systemd文件；
- 复制其他板的MTS/watchdog运行态；
- 静默改变MTS target、bit SHA或门限绕过失败；
- 在PLL失锁后自动恢复打流；
- 删除CONFIGURE/watchdog跨进程锁；
- 绕过latest-only发布脚本只替换单个远端脚本；
- 把sudo、SSH或采集机凭据写入文件或日志。

## 14. 部署记录模板

每块板保存以下记录，并将必要结论绑定到Git提交与bitstream SHA：

| 项目 | 结果 |
| --- | --- |
| 管理IP/MAC | 待填 |
| board ID | 待填 |
| Git提交 | 待填 |
| bitstream ID / SHA-256 | 待填 |
| PYNQ / xrfdc版本 | 待填 |
| GPIO chip base / spidev | 待填 |
| LMK profile / PLL readback | 待填 |
| ADC/DAC MTS target与实测 | 待填 |
| watchdog idle health | 待填 |
| PPS fault-stop | 待填 |
| 10 MHz fault-stop | 待填 |
| receiver接口、MAC和端口组 | 待填 |
| smoke / soak / thermal报告 | 待填 |
