# Stage 32 T510 PYNQ复刻与额外修改指南

## 1. 文档目的

本文档说明当前Stage 32 T510板卡相对基础PynqLinux镜像增加了什么，以及如何在
另一块T510的PYNQ系统上复刻同一套LMK、RFDC/MTS、Board Agent和reference
watchdog环境。

本文档不替代Stage 32设计报告；它只处理板端Linux/PYNQ软件部署。UDP header、
payload、端口、flow数量和FPGA科学数据路径见
`../stages/32_stage32_master_plan.md`。

禁止直接克隆当前板卡的整张SD卡并假定同步成立。每块板仍必须独立验证板号、管理
网口、QSFP目标、LMK锁定、RFDC MTS实测值和物理PPS/10 MHz输入。

## 2. 当前已验证基线

### 2.1 操作系统和PYNQ

| 项目 | 当前板卡值 |
|---|---|
| 板卡 | MicroPhase ANTSDR T510 / ZU47DR |
| OS | PynqLinux 3.0，基于Ubuntu 22.04 |
| kernel | `5.15.19-xilinx-v2022.1` |
| 架构 | `aarch64` |
| Python | `3.10.4` |
| PYNQ | `3.0.1` |
| PYNQ venv | `/usr/local/share/pynq-venv` |
| xrfdc package | `/usr/local/share/pynq-venv/lib/python3.10/site-packages/xrfdc` |
| Agent用户 | `root` |
| Agent端口 | `0.0.0.0:8010` |

当前xrfdc关键文件SHA256：

| 文件 | SHA256 |
|---|---|
| `xrfdc/__init__.py` | `8d6994ef3600b084d05ccb731b7e7d4b2b76424d335ba58a0dfa36054ee80e26` |
| `xrfdc/config.py` | `399eaa66fb7bab272e234babfae9307b4048b0bd6f8fc5370efae01382e193b5` |
| `xrfdc/libxrfdc.so` | `80deec787c95da6c910dfad4baae83d7878e7798c0e9b638f4ad0a8521b823b6` |
| `xrfdc/xrfdc_functions.c` | `cc47d99d7f995dbf4df1a0978d7e23fb3013641a2816fd22d7f70c8bda061589` |

Stage 32的MTS支持由项目内`python/t510_fengine.py`在运行时向xrfdc的CFFI对象补充
`XRFdc_MultiConverter_Init`、`XRFdc_MultiConverter_Sync`和
`XRFdc_MTS_Sysref_Config`声明，再调用`libxrfdc.so`已有符号。不要仅以
`hasattr(xrfdc._lib, ...)`在补充CFFI声明之前的返回值判断MTS不可用。

### 2.2 Stage 32冻结标识

| 项目 | 值 |
|---|---|
| `CORE_VERSION` | `0x00010032` |
| bitstream SHA256 | `439080046408267493a031efa1d097fcd3c2f818850ee9eac1925ae95d6b094c` |
| LMK profile | `stage32_160_10m_cont_manual_clkin2` |
| LMK输入 | manual CLKin2 / external 10 MHz |
| LMK SYSREF | continuous 10 MHz |
| ADC固定MTS target | `230` |
| DAC固定MTS target | `336` |
| watchdog状态 | `/run/t510-stage32-ref-watchdog.json` |
| MTS状态 | `/run/t510-stage32-mts.json` |
| PYNQ当前bit状态 | PYNQ package内`pl_server/global_pl_state.json` |
| 已部署release | `stage32-ref-watchdog-r2-20260727` |

第二块板不允许为了“让测试通过”静默提高MTS target。若实测latency超过`230/336`，
应阻塞Stage 32并重新评审所有板共同使用的新target。

当前不可变release的关键文件SHA256：

| 文件 | SHA256 |
|---|---|
| `bin/t510-board-agent` | `80ef09b1b193d805f76a2f3f258ffc67d64e86a3c9d0e00ab4346122c2495fd0` |
| `python/t510_hw.py` | `847fb219170d2e63cddf8f5a06bcc994a0e8907b762b7e1773e3ef5a7e0769f6` |
| `python/t510_ref_watchdog.py` | `565e103f7ee980bcfa50ce7cbf506c65f636caa3380ca539979684d0b21204e5` |
| `python/t510_clock.py` | `d5dfcc44afdb9df2f9c92c5bf9bdb933f46d558b8d81ec52ee887bfe64a65406` |
| `deploy/install-on-board.sh` | `ecefd0cbaf0220f1d9af8a24564c39513a643beccf9462e95fd0dde936851794` |
| `deploy/t510-ref-watchdog.service` | `fc701ae64aa9bbd7f0936fcd39ade7f0ab8926ccc285d0c75ce74ead5bc81274` |
| `deploy/t510-agent.service.d/center-hub.conf` | `1755f4224ff9cd90659f7c91d5116ccfdde0438f579e2b4e906bd0c77b51e394` |

这些hash用于判断新板是否真正复刻了同一套PS软件，不替代bitstream SHA256、
LMK寄存器回读或MTS板端实测。

## 3. 相对基础PYNQ的额外修改

### 3.1 LMK SPI设备

项目使用：

```text
SPI controller device : spi1.0
Linux device          : /dev/spidev1.0
mode                  : SPI mode 0
speed                 : 1 MHz
owner                 : root:root
```

基础镜像可能有SPI控制器但没有自动绑定spidev。`python/t510_clock.py`会在需要时：

1. 检查`/sys/bus/spi/devices/spi1.0`；
2. 写`driver_override=spidev`；
3. 写`/sys/bus/spi/drivers/spidev/bind`；
4. 等待`/dev/spidev1.0`出现。

因此Agent和watchdog必须以root运行，systemd unit不得阻止上述sysfs写入。

### 3.2 LMK GPIO编号

当前PYNQ的ZynqMP GPIO chip：

```text
label = zynqmp_gpio
base  = 334
ngpio = 174
```

项目代码使用PS pin编号，sysfs全局GPIO为`334 + PS pin`：

| 功能 | PS pin | sysfs GPIO | 当前路径 |
|---|---:|---:|---|
| LMK reset | 29 | 363 | `/sys/class/gpio/gpio363` |
| LMK reference select 0 | 33 | 367 | `/sys/class/gpio/gpio367` |
| LMK reference select 1 | 34 | 368 | `/sys/class/gpio/gpio368` |
| LMK SYNC | 78 | 412 | `/sys/class/gpio/gpio412` |

`python/t510_clock.py`会按需export这些GPIO。换板前必须核对`gpiochip` base和板级连接；
不能在不同PYNQ镜像上盲目假定base仍为334。

当前板没有导出LMK PLL lock GPIO，FPGA顶层/XDC也没有
`STATUS_LD1/STATUS_LD2`输入。PLL1/PLL2 lock由PS通过LMK寄存器`0x182/0x183`
读取。

### 3.3 PYNQ当前bit状态修正

当前T510使用PYNQ XRT backend。该backend完成FPGA下载后，不一定更新
`global_pl_state.json`。项目的`python/t510_hw.py`在CONFIGURE成功后会：

1. 对实际下载的bit计算SHA1；
2. 保留PYNQ已有`active_name`、`shutdown_ips`和`psddr`字段；
3. 原子更新`bitfile_name`、`bitfile_hash`和`timestamp`；
4. 后续每个一次性helper请求再次验证活动bit与catalog是否一致。

这不是修改PYNQ site-packages，而是项目helper中的兼容层。不要删除
`_record_active_bitstream_state()`或把bit路径验证改成只比较字符串；同一不可变bit
可能通过不同release symlink访问，硬件身份以内容hash为准。

### 3.4 RFDC固定MTS结果

CONFIGURE完成MTS后，项目原子写：

```text
/run/t510-stage32-mts.json
```

当前已验证内容：

```text
ADC target/measured = 230 / [230,230,230,230]
DAC target/measured = 336 / [335,335,335,335]
```

`/run`是tmpfs，重启后该文件消失是正常现象。不得把旧板的`/run`文件复制到新板；
新板必须执行真实CONFIGURE/MTS生成自己的实测记录。

### 3.5 Stateless Board Agent

安装位置：

```text
/opt/t510-agent/releases/<release-id>/
/opt/t510-agent/current -> releases/<release-id>
/etc/t510-agent/config.json
/etc/systemd/system/t510-agent.service
/etc/systemd/system/t510-agent.service.d/center-hub.conf
```

Agent是aarch64 musl静态Rust binary。每个硬件REST请求启动一次固定
`python/t510_hw.py` helper；任意路径或任意Python代码不能通过REST传入。

`center-hub.conf`必须保留`ProtectKernelTunables=false`，否则CONFIGURE无法完成
FPGA manager/sysfs和动态spidev操作。

### 3.6 LMK reference watchdog

物理测试证明：拔掉10 MHz后LMK PLL1失锁，但PLL2、160 MHz和RFDC数据时钟继续，
原PL `ref_locked`仍为true，活动流不会自动停止。

新增常驻服务：

```text
/opt/t510-agent/current/python/t510_ref_watchdog.py
/etc/systemd/system/t510-ref-watchdog.service
/run/t510-stage32-ref-watchdog.json
/run/t510-stage32-ref-watchdog.lock
/run/t510-stage32-configure.lock
```

生产参数：

```text
poll interval             = 100 ms
PLL unlock confirmations  = 2
SPI error confirmations   = 5
STOP verify timeout       = 2000 ms
```

行为：

1. 只读LMK`0x182/0x183`，不重写profile；
2. 空闲时失锁不会写PL，但watchdog变为not healthy，START/ARM被helper拒绝；
3. streaming期间连续两次PLL1或PLL2失锁，直接写现有FPGA STOP/flush寄存器；
4. streaming期间连续五次无法读取LMK，也按fail-safe执行STOP；
5. 保存检测时刻、generation、包计数、STOP latency和flush结果；
6. 故障恢复后不会自动重新打流；
7. 只有fresh CONFIGURE更新PYNQ活动bit timestamp并重新完成MTS，才清除fault latch；
8. watchdog状态超过1500 ms未更新、服务不健康、bit身份不匹配或fault已锁存时，
   `START`和`sync/ARM`均返回`REFERENCE_WATCHDOG_NOT_READY`。

CONFIGURE会重新下载PL并初始化RFDC，不能与watchdog的PYNQ MMIO轮询并发。`r2`
增加跨进程`flock`：

1. `t510_hw.py configure`对`/run/t510-stage32-configure.lock`持有独占锁；
2. watchdog每次轮询只尝试获取共享锁；
3. 独占锁存在时watchdog写`mode=CONFIGURE_PAUSE`、
   `healthy=false`、`last_error=CONFIGURE_IN_PROGRESS`，但不访问PL或LMK SPI；
4. CONFIGURE返回并释放锁后，watchdog根据新的PYNQ bit timestamp重新连接，
   清除旧fault latch并恢复`IDLE/healthy`。

这项互斥是必要功能，不是性能优化。未互斥的`r1`在现场连续两次使ADC0
`XRFdc_Reset`停在state 6；`r2`板端观察到CONFIGURE全程
`CONFIGURE_PAUSE`后，RFDC/MTS正常完成。复制到其他板时不得删除该锁，也不能把
watchdog改成在CONFIGURE期间继续读MMIO。

systemd将watchdog设为`Restart=always`。Agent unit通过`Wants/After`依赖watchdog，
但真正的fail-closed保证来自helper对状态新鲜度和锁定值的检查，不依赖服务启动
顺序碰巧正确。

## 4. Release文件清单

Stage 32板端release至少包含：

```text
bin/t510-board-agent
python/__init__.py
python/packet.py
python/stage29.py
python/t510_clock.py
python/t510_fengine.py
python/t510_hw.py
python/t510_ref_watchdog.py
overlay/t510_fengine.bit
overlay/t510_fengine.hwh
overlay/t510_fengine.tcl
overlay/t510_fengine.manifest.txt
config/config.example.json
deploy/t510-agent.service
deploy/t510-ref-watchdog.service
deploy/t510-agent.service.d/center-hub.conf
deploy/install-on-board.sh
```

不要只复制watchdog脚本。watchdog依赖同一release中的`stage29.py`、
`t510_fengine.py`、`t510_clock.py`、匹配的HWH和bitstream。

## 5. 新板预检

在安装任何项目文件前保存：

```bash
uname -a
cat /etc/os-release
/usr/local/share/pynq-venv/bin/python3 -V
/usr/local/share/pynq-venv/bin/pip show pynq
ls -l /sys/bus/spi/devices/spi1.0
for path in /sys/class/gpio/gpiochip*/{label,base,ngpio}; do
  echo "$path=$(cat "$path")"
done
sha256sum \
  /usr/local/share/pynq-venv/lib/python3.10/site-packages/xrfdc/__init__.py \
  /usr/local/share/pynq-venv/lib/python3.10/site-packages/xrfdc/config.py \
  /usr/local/share/pynq-venv/lib/python3.10/site-packages/xrfdc/libxrfdc.so \
  /usr/local/share/pynq-venv/lib/python3.10/site-packages/xrfdc/xrfdc_functions.c
```

硬前置：

- aarch64 PynqLinux 3.0/Python 3.10；
- PYNQ和xrfdc可导入；
- `spi1.0`存在；
- FPGA manager存在；
- T510 PL/RFDC硬件与当前HWH匹配；
- 外部10 MHz和PPS已经接好；
- `/opt`至少保留512 MiB空闲空间。

若PYNQ、kernel、xrfdc或GPIO映射不同，先记录差异并做兼容性评审，不要直接覆盖
site-packages。

## 6. 构建和安装

### 6.1 在开发机生成不可变release

```bash
cd /home/astrolab/demo-ant
STAGE32_RELEASE_ID=stage32-ref-watchdog-<date> \
  scripts/pynq_publish_stage32.sh --build-only
```

构建脚本会：

- 校验冻结bitstream SHA256；
- 构建aarch64 musl静态Agent；
- 组装上述完整release目录；
- 不访问板卡、不下载bitstream。

### 6.2 安装到目标板

安装前必须先停止science并确认pipeline clean。随后：

```bash
PYNQ_TARGET=xilinx@<target-management-ip> \
STAGE32_RELEASE_ID=stage32-ref-watchdog-<date> \
  scripts/pynq_publish_stage32.sh --install
```

安装脚本：

1. 把release放入`/opt/t510-agent/releases/<release-id>`；
2. 将release改为root拥有、只读；
3. 原子更新`/opt/t510-agent/current` symlink；
4. 安装Agent、watchdog unit和Agent drop-in；
5. enable/restart watchdog和Agent；
6. 最多等待20秒，验证watchdog状态文件存在且年龄小于1500 ms；
7. 验证两个service active和REST live/ready；
8. 不自动下载bitstream。

sudo密码只能交互输入，不得写入仓库、本文档、shell history或release。

## 7. 安装后首次配置

先检查服务：

```bash
systemctl is-enabled t510-ref-watchdog.service t510-agent.service
systemctl is-active t510-ref-watchdog.service t510-agent.service
systemctl status --no-pager t510-ref-watchdog.service t510-agent.service
cat /run/t510-stage32-ref-watchdog.json
curl -sS http://127.0.0.1:8010/api/v1/capabilities | python3 -m json.tool
```

刚启动且PL未配置时，watchdog显示`WAITING_FOR_PL`是正常的。然后使用该板自己的
board ID和目标endpoint执行Stage 32 CONFIGURE。CONFIGURE必须重新：

```text
写LMK profile
-> 验证PLL1/PLL2
-> 下载匹配bit
-> 初始化RFDC
-> 执行固定target MTS
-> 保持STOP
```

等待watchdog出现：

```text
mode=IDLE
healthy=true
fault_latched=false
lock_status.pll1_lock=1
lock_status.pll2_lock=1
active_bitstream_sha1与PYNQ活动bit一致
```

只有此后才允许START或PREPARE/ARM。

## 8. 新板验收

### 8.1 软件与静态检查

```bash
python3 -m py_compile \
  /opt/t510-agent/current/python/t510_hw.py \
  /opt/t510-agent/current/python/t510_ref_watchdog.py
systemd-analyze verify \
  /etc/systemd/system/t510-agent.service \
  /etc/systemd/system/t510-ref-watchdog.service
journalctl -u t510-ref-watchdog.service -b --no-pager
```

### 8.2 正常状态

- Agent和watchdog active；
- LMK PLL1/PLL2为1；
- watchdog状态年龄小于1500 ms；
- 固定MTS不超过`230/336`；
- STOP时`streaming=false`、`stream_accepting=false`、`flush_clean=true`。

### 8.3 Fail-closed

至少验证：

1. 停流时断10 MHz：watchdog变not healthy，START/ARM被拒绝；
2. 活动预约流时断PPS：PL锁存`pps_not_recent`并自动停流；
3. 活动预约流时只断10 MHz：watchdog锁存`LMK_PLL1_UNLOCKED`并直接停流；
4. 10 MHz接回后直接ARM仍被拒绝；
5. fresh CONFIGURE/MTS后fault latch才清除；
6. 恢复后跑一次20秒主机收包门禁，无drop/gap和半包锁死。

物理10 MHz和PPS必须分别断开，不能同时拔线，否则不能判断是哪一层保护生效。

## 9. 每块板必须单独填写

| 项目 | 板A | 新板 |
|---|---|---|
| 管理IP/MAC | `192.168.100.117` / 现场读取 | 待填 |
| board ID | `1` | 待填 |
| bit SHA256 | 冻结值 | 待验证 |
| Agent release ID | `stage32-ref-watchdog-r2-20260727` | 待填 |
| PYNQ/xrfdc hash | 本文基线 | 待验证 |
| GPIO chip base | `334` | 待验证 |
| `/dev/spidev1.0` | PASS | 待验证 |
| LMK profile/readback | PASS | 待验证 |
| ADC latency/target | `[230,230,230,230] / 230` | 待实测 |
| DAC latency/target | `[335,335,335,335] / 336` | 待实测 |
| watchdog idle health | PASS | 待验证 |
| 物理PPS fault-stop | PASS | 待验证 |
| 物理10 MHz fault-stop | PASS，STOP latency `0.257 ms` | 待验证 |
| 20秒恢复收包 | PASS，25,017,248 TIME包，零drop/gap | 待验证 |

当前板`2026-07-27`最终验收证据：

- 物理10 MHz断开：
  `../board/stage32h_physical_10mhz_watchdog_pass_20260727.json`，
  SHA256
  `d3c97b95dda0db6938f2a1cc29e912137fe8d9a7196e56f3ad3a9a77f0953dde`；
- 参考恢复后的fresh CONFIGURE/MTS：
  `../board/stage32h_watchdog_recovery_configure_20260727.json`，
  SHA256
  `149c6abacd5fa958012aa88f018cbf4d2a0674fc6163a1f70b062bcadafaed29`；
- 320 MS/s TIME_ONLY 20秒板端/主机恢复门禁：
  `../board/stage32h_watchdog_recovery_320_time_only_20s_20260727.json`，
  SHA256
  `79e2256387e43ee11aa1f0540dfca4f33d5de736a8a077f1d43c65877ff73343`；
- 对应接收机原始证据：
  `../board/stage32h_watchdog_recovery_320_time_only_20s_20260727_host.json`，
  SHA256
  `5484cac9910b629ace6e0e2856606a526d536baf3f94ddcf363115d5401f6c77`。

物理故障中watchdog锁存`LMK_PLL1_UNLOCKED`，在约200 ms的两次确认窗口后执行
现有STOP；从发出STOP到PL确认停止为`0.257 ms`，最终
`flush_clean=true`。接回10 MHz后直接START仍以HTTP 409拒绝；只有fresh
CONFIGURE/MTS才清除锁存。恢复收包为`1,250,862.4 pps /
83,257.401344 Mbit/s`，所有主机kernel/ring/app drop和连续性gap增量为0。

## 10. 回滚

新watchdog release与新helper是成套的。不能只disable watchdog后继续使用带
fail-closed检查的新`python/t510_hw.py`，因为START/ARM会按设计拒绝。

回滚顺序：

```text
STOP并确认flush clean
-> 记录当前release和watchdog state
-> 将/opt/t510-agent/current切回完整的上一release
-> 恢复上一release匹配的Agent unit/drop-in
-> daemon-reload并restart Agent
-> 按上一release的发布流程重新CONFIGURE
```

如果回滚到没有watchdog的release：

```bash
systemctl disable --now t510-ref-watchdog.service
```

仅在`current` symlink已经指向完整旧release、旧helper不要求watchdog之后执行。
任何回滚都不能混用Stage 31 bitstream/LMK profile来冒充Stage 32验收。

## 11. 禁止事项

- 不复制另一块板的`/run/t510-stage32-mts.json`或watchdog fault state；
- 不在PLL1失锁时自动恢复打流；
- 不因PLL2仍锁定就判断外部10 MHz正常；
- 不以PPS对PL时钟的短期频差估算替代LMK PLL1 lock；
- 不静默增大MTS target；
- 不向UDP header增加watchdog字段；
- 不在release目录内现场修改文件；任何修订必须产生新的不可变release ID；
- 不把sudo、SSH或接收机凭据写入文档和脚本。
