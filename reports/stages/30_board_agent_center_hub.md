# Stage 30：轻量无状态 Rust Board Agent

## 当前结论

Stage 30 已按轻量方案重构并在 T510 `192.168.100.117` 上完成只读上线。最终入口：

```text
http://192.168.100.117:8010
```

根路径返回 `302` 到 `/api/help`；OpenAPI 3.1 位于 `/api/openapi.json`。

本阶段没有修改 RTL、bitstream、UDP 数据协议或 Rust WebSocket 协议，冻结值仍为：

- `CORE_VERSION=0x00010030`
- bitstream SHA256：`7486a55b6f7e50e5875474e7d85299b107e9384cfff454316f64f2d3d7e9800d`

Agent 已与 Jupyter 同时运行。安装前后的 Jupyter server PID `878`、kernel PID `115849` 均未变化；当前 science preview 仍为 board ID 1、约 `960 kpps`，waveform/spectrum 均 live。

## 实现边界

### Rust Agent

新增独立 crate `rust/t510_board_agent`，单个静态 binary 负责：

- HTTP 路由、严格 JSON schema、统一错误响应、help 和 OpenAPI；
- hostname、machine-id、管理网卡 MAC/IP、内存、架构和 Agent 版本汇报；
- 从 `/etc/t510-agent/config.json` 加载命名 bitstream catalog；
- 启动时验证 catalog bitstream SHA256、core version 格式和绝对路径；
- 只允许客户端提交 `bitstream_id`，不接受任意文件路径；
- 对自身硬件请求使用全局 `try_lock`，冲突立即返回 `409 HARDWARE_BUSY`；
- configure 默认等待 180 秒，其他硬件命令默认等待 10 秒；
- 每个硬件请求启动一次固定 Python helper，完成后退出；
- 只写 journald，不创建数据库、operation journal 或运行状态文件。

最终 aarch64 binary 为 `2.9 MiB`、静态 musl、stripped。板端空闲 RSS 约 `3.8 MiB`。

### Python PYNQ helper

`python/t510_hw.py` 是无服务、无数据库的单次 CLI，仅支持：

```text
status
configure
start
stop
reset
set-dac
```

stdin 必须是一个 JSON object，stdout 只输出一个 JSON object。PYNQ 的其他输出和 traceback 进入 stderr/journald。

helper 复用 Stage 29 控制原语：

- `prepare()`：加载 overlay、时钟/MTS、science profile、source、24 endpoint 和 board ID，完成后保持停流；
- `start_immediate()`；
- `stop_and_verify()`；
- 八路 DAC mute、完整更新、phase commit、恢复 enable mask 和寄存器回读；
- `status` 只读取一次当前寄存器事实和累计 counters。

Stage 29 notebook 的旧 `apply()` 仍保持 `prepare(program_dac=True) -> start_immediate()` 行为。Agent 不管理、停止或锁定 Jupyter。

## 监控职责

Agent 不实现：

- waveform/spectrum capture；
- FFT、WebSocket 或 packet capture；
- 后台轮询；
- packet/drop rate 或趋势计算；
- Rust receiver/Web UI 调用。

`GET /api/v1/status` 每次启动一个 helper，返回带 `captured_at_unix_ms` 的寄存器快照。Center Hub 应保存相邻快照，并用时间戳和累计 counter 差值计算 rate。

现场连续两次快照证明 TIME/SPEC 和 TX counters 正常增加，所有 drop/error counter 的窗口增量为 0。当前快照包括：

- core `0x00010030`、board ID 1、`streaming=true`；
- `100 MHz TIME_SPEC`、center readback 约 `100 MHz`；
- PPS recent、reference locked；
- QSFP link up、module present；
- TIME/SPEC/TX 累计 counters、sample0、error flags；
- 八路 DAC enable/frequency/amplitude/phase/epoch readback。

## API

发现和文档：

- `GET /`
- `GET /api/help`
- `GET /api/openapi.json`
- `GET /health/live`
- `GET /health/ready`
- `GET /api/v1/info`
- `GET /api/v1/capabilities`
- `GET /api/v1/bitstreams`

硬件接口：

- `GET /api/v1/status`
- `POST /api/v1/configure`
- `POST /api/v1/start`
- `POST /api/v1/stop`
- `POST /api/v1/reset`
- `PUT /api/v1/dac`

`configure` 要求恰好 24 个 endpoint，ID 0..23 各一次；0..7 为 TIME，8..23 为 SPEC；profile 和 enable mask 必须一致。board ID 为 16-bit，只随 configure 请求下发。

`start` 和 `reset` 要求 `expected_board_id`；`stop` 无条件执行安全停止；`dac` 要求 expected board ID、center MHz 和完整八路配置。

成功响应：

```json
{"request_id": "t510-...", "result": {}}
```

错误响应包含稳定 `code`、message 和可选 details。现场已验证：

- 缺字段 configure：`400 INVALID_JSON`
- 不完整 DAC：`400 SCHEMA_VALIDATION_FAILED`
- 未知 bitstream：`404 UNKNOWN_BITSTREAM`
- 两个并发 status：一个 200，另一个 `409 HARDWARE_BUSY`
- root：`302 /api/help`
- CORS preflight：`405`，无 `Access-Control-Allow-Origin`

## 设备发现结果

`GET /api/v1/info` 当前返回：

- `device_uid=t510-psmac-02511023dc28`
- hostname `pynq`
- architecture `aarch64`
- management MAC `02:51:10:23:dc:28`
- management IPv4 `192.168.100.117`、alias `192.168.2.99` 和 eth0 IPv6 地址
- listen `0.0.0.0:8010`
- `security_mode=none`

Agent 不设置 PS 地址、不注册或广播到 Hub。Center Hub 只需保存该 URL，并在 configure 时分配 board ID。

## 部署

最终现场 release：

```text
/opt/t510-agent/releases/740c6f820a41-20260716104500
```

`/opt/t510-agent/current` 指向该不可变目录。安装内容仅包括：

- Rust binary；
- Python helper、Stage 29/PYNQ 必要模块；
- bit/hwh/tcl/manifest；
- catalog/config；
- 单个 `t510-agent.service`。

systemd 只有一个 root Agent service，监听 `0.0.0.0:8010`。Jupyter 保持 active/enabled。未发现 `.db`、`.sqlite` 或 `.sqlite3` 状态文件，helper 请求完成后没有常驻 Python 进程。

发布脚本使用 `cargo-zigbuild` 生成 `aarch64-unknown-linux-musl` 静态 binary；板端不安装 Rust toolchain。首次安装只调用 help/health/info/status，没有调用 configure/start/stop/reset/DAC。

现场部署调试发现并修复了三个纯部署问题：

1. release 最初漏带 `python/packet.py`；
2. systemd 需要 `AF_NETLINK` 才能执行 `getifaddrs`；
3. PYNQ global-state 会校验当前 Jupyter bitfile 的 `/home/xilinx/...` 路径，因此不能用 `ProtectHome=true` 隐藏该只读路径。

以上失败均发生在 import/metadata 阶段，没有执行硬件写操作；整个过程中 science stream 和 Jupyter 持续正常。

## 测试结果

2026-07-16：

- Rust Board Agent：5 项通过，覆盖五种 profile、24 endpoint、catalog 路径、完整 Fake helper HTTP configure/start/status/DAC/stop、错误映射、BUSY、timeout、help/OpenAPI；
- Python Stage 29 + helper：29 项通过，覆盖 prepare/apply 兼容、五 profile、24 endpoint、board ID、累计 status、start/stop/reset、八路 DAC 和单 JSON stdout；
- Rust receiver：34 项通过；
- browser math：PASS；
- Python compile、JSON parse、shell syntax、Rust fmt：PASS；
- aarch64 musl 静态构建和真实板启动：PASS。

## 安全与剩余 Gate

Stage 30 按当前选择完全开放在实验室局域网：

- 无 token；
- 无 IP allowlist；
- 无 mTLS；
- 无 CORS；
- `/capabilities` 和 `/api/help` 明确报告 `security_mode=none`。

当前节点 `192.168.100.192` 已验证可以访问 8010；T510 到 Hub `192.168.99.119` ping 为 `0.871 ms`。由于当前没有 Hub 主机 SSH 权限，本次未从 `192.168.99.119` 本机执行反向 curl，Hub -> T510 入站仍需在 Center Hub 上补一条：

```bash
curl http://192.168.100.117:8010/health/live
```

真实 configure/start/stop/reset/DAC 控制 Gate 仍按计划延后到 Center Hub 联调维护窗口。本次没有调用这些写接口。

Center Hub 仍需增加独立 DAC–ADC lab profile：完整八路 enable、RF MHz、amplitude percent、phase degrees，并调用 `PUT /api/v1/dac`。该配置不要混入正式 observation descriptor。
