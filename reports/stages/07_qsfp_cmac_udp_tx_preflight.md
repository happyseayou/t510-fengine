# Stage 7: QSFP/CMAC UDP TX Preflight + 8+8 Static Routing

## 阶段目标

完成真实 QSFP/CMAC 发包前的链路预检：把 Stage 6 的 T510 internal packet 包装成 Ethernet II + IPv4 + UDP frame，并在无真实交换机收包门禁的条件下验证 8 个频域 route、8 个时域 route、frame header capture、dry-run/CMAC 状态语义。

本阶段不声明 QSFP28 真实链路发包成功；交换机、接收节点抓包和多节点压力测试进入 Stage 7a。

## 输入基线

- Stage 6 已闭合 PFB/FFT channel-window dry-run 合约：`chan0/chan_count/time_count/ninput/payload_bytes=8192`。
- Stage 5 packet FIFO、internal T510 header capture 和 dry-run counters 可用。
- Stage 5b Jupyter 8 路虚拟示波器/频谱仪作为操作入口继续保留。
- 顶层设计要求：
  - 频率模式下按频点段选择不同 UDP 目标节点。
  - 时域模式下按采样通道 mask 选择 UDP 目标，可多个采样通道共用一个目标。
  - QSFP28 正式运行会接交换机。
- PYNQ 目标：`xilinx@192.168.100.117`。

## 完成内容

- 新增 Stage 7 TX preflight 数据面：
  - `rtl/tx_route_selector.sv`：解析 T510 internal header，按 SPEC channel window 或 TIME input mask 选择 endpoint。
  - `rtl/udp_frame_builder.sv`：在 T510 packet 前插 Ethernet II、IPv4、UDP header，UDP payload 的起点仍是 T510 128B header v2。
  - `rtl/t510_fengine_top.sv`：packet FIFO 后接 route selector、UDP frame builder、frame header capture。
  - 保留原 `capture_tx_header()` 抓 internal T510 header；新增 `capture_tx_frame_header()` 抓 Ethernet/IP/UDP frame header。
- 新增 `0xB000` TX/route register 区，`CORE_VERSION=0x00010005`：
  - `TX_CONTROL/TX_STATUS`、frame built/sent/dropped/byte counters、route miss/error counters。
  - endpoint table：8 entries，静态 `dst_ip/dst_mac/dst_udp_port/src_udp_port`。
  - SPEC route table：8 entries，`enable/chan0/chan_count/endpoint_id/hit_count`。
  - TIME route table：8 entries，`enable/input_mask/endpoint_id/hit_count`。
  - frame capture buffer：`0xB040..0xB0BF`。
- 保持兼容：
  - overlay 名称仍为 `overlay/t510_fengine.bit`。
  - `T510FEngine` 初始化方式不变。
  - 旧 `DGX_A/DGX_B/TIME` 网络寄存器仍可写，并同步为默认 endpoint。
- Python/Jupyter：
  - `python/packet.py` 增加 Ethernet/IPv4/UDP frame parser。
  - `python/t510_fengine.py` 增加 `configure_tx_endpoints()`、`configure_spec_routes()`、`configure_time_routes()`、`read_tx_status()`、`capture_tx_frame_header()`、`run_spec_route_walk()`。
  - 新增 `scripts/pynq_qsfp_udp_preflight_check.py`。
  - 更新 `notebooks/10_8lane_realtime_virtual_instrument.ipynb`，增加 TX route/status/preflight panel。
- 板级连接状态：
  - 当前 board top 仍把 TX AXIS 接到 dry-run sink，`m_axis_tx_tready=1`。
  - CMAC/QSFP wrapper 尚未接入本阶段门禁；`force_dry_run=1` 是预期状态。

## 验证证据

- 本地 Python/notebook：
  ```bash
  python3 -m py_compile python/packet.py python/t510_fengine.py scripts/check_t510_udp_frame.py scripts/pynq_qsfp_udp_preflight_check.py scripts/pynq_pfb_channel_window_check.py
  python3 -m json.tool notebooks/10_8lane_realtime_virtual_instrument.ipynb >/dev/null
  ```
  结果：PASS；notebook code cells compile：PASS。
- 本地 XSim：
  ```bash
  ./scripts/run_xsim_batch.sh tb_tx_route_selector tb_udp_frame_builder tb_feng_ctrl_axi tb_t510_fengine_top_smoke
  ```
  结果：全部 PASS。
  - `tb_tx_route_selector`：SPEC route、TIME route、route miss/error 选择语义通过。
  - `tb_udp_frame_builder`：Ethernet/IP/UDP header、IPv4 checksum、UDP length 和 payload alignment 通过。
  - `tb_feng_ctrl_axi`：`CORE_VERSION=0x00010005` 和 `0xB000` register readback 通过。
  - `tb_t510_fengine_top_smoke`：top-level SPEC dry-run、internal header capture、frame header capture 通过。
- Vivado：
  - synthesis：0 errors，0 critical warnings，189 warnings。
  - implementation route：0 errors，0 critical warnings。
  - bitgen：0 errors，0 critical warnings，普通 warnings 包含既有 DAC loopback DSP pipeline 建议、RFDC unused status nets 和 power advisory。
  - readiness：`READY`，route complete。
  - post-route timing：`WNS=+2.550 ns`，`WHS=+0.013 ns`，失败端点 `0/69199`。
  - bitstream：`overlay/t510_fengine.bit`，SHA256 `c10c32972394bf22dec7f292446b7ea897578ecdb6ef2f636b8b0f911117deaf`。
- PYNQ 同步/发布：
  - `/home/xilinx/t510_fengine_bringup`
  - `/home/xilinx/jupyter_notebooks/t510_fengine`
- PYNQ Stage 6 回归：
  ```bash
  cd /home/xilinx/t510_fengine_bringup
  source /etc/profile.d/xrt_setup.sh
  sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_pfb_channel_window_check.py --chan0 0 --chan-count 64 --time-count 4 --timeout 2.0
  ```
  结果：PASS。
  - `core_version=0x00010005`
  - `streaming=1`
  - `UDP_DRY_RUN=1`
  - `QSFP_LINK_UP=0`
  - `pfb_nchan=4096`
  - `pfb_chan0=0`
  - `pfb_chan_count=64`
  - `pfb_time_count=4`
  - `pfb_frame_count` 从 `158` 增长到 `33737`
  - header：`version=2 stream_type=SPEC chan0=0 chan_count=64 time_count=4 ninput=8 payload_bytes=8192 flags=INTERNAL_EPOCH|UDP_DRY_RUN`
- PYNQ Stage 7 验收：
  ```bash
  sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_qsfp_udp_preflight_check.py --force-dry-run --timeout 2.0
  ```
  结果：PASS。
  - `core_version=0x00010005`
  - `streaming=1`
  - `tx_control=0x0000000d`
  - `tx_status=0x00000602`
  - `tx_udp_dry_run_active=1`
  - `tx_qsfp_link_up=0`
  - `tx_frame_built_count` 从 `165` 增长到 `33940`
  - `tx_frame_sent_count` 从 `164` 增长到 `33939`
  - `tx_frame_dropped_count=0`
  - `tx_route_miss_count=0`
  - `tx_route_error_count=0`
  - SPEC route0 readback：`chan0=0, chan_count=2048, endpoint_id=0, hit_count=33806`
  - SPEC route1 readback：`chan0=2048, chan_count=2048, endpoint_id=1, hit_count=180`
  - TIME route0 readback：`input_mask=0x0001, endpoint_id=2`
  - route0 frame：`dst_mac=02:00:00:00:00:0a dst_ip=10.0.1.10 dst_port=4100 src_ip=10.0.1.1 src_port=4000 udp_length=8328 ipv4_total_length=8348`
  - route1 frame：`dst_mac=02:00:00:00:00:0b dst_ip=10.0.1.11 dst_port=4200 src_ip=10.0.1.1 src_port=4000 udp_length=8328 ipv4_total_length=8348`

## 阶段衔接说明

- 下一阶段可依赖：
  - `CORE_VERSION=0x00010005`。
  - T510 internal header v2 仍作为 UDP payload 开头，且 internal capture 保持可用。
  - Ethernet II + IPv4 + UDP frame builder 已能在 dry-run 中输出可解析 header。
  - 8 个 SPEC route 和 8 个 TIME route 的静态寄存器接口、readback、命中计数和 endpoint 选择语义。
  - 频域 route-walk：改变 PFB `chan0` 可验证 endpoint0/endpoint1 选择变化。
  - Stage 6 PFB channel-window contract 未破坏。
  - Jupyter `10_8lane_realtime_virtual_instrument.ipynb` 可继续作为 scope/spectrum/PFB/TX preflight 入口。
- 下一阶段不能依赖：
  - CMAC/QSFP 真实发包。
  - 交换机端或接收节点实际收到 UDP frame。
  - ARP、VLAN、PTP、真实 DGX/X-engine ingest。
  - TIME payload 已按 `input_mask` 去除未选 lane；本阶段只闭合 route metadata/header/frame 选择。
  - 多频段持续自动调度；本阶段验证的是软件 route-walk 静态切换。
- 剩余风险：
  - board top 尚未接 Xilinx CMAC wrapper，当前 TX AXIS 由 dry-run sink 消费。
  - 交换机正式运行需要 jumbo MTU，当前 frame 长度约 `8362B`，不含 FCS。
  - UDP checksum 固定为 0；Stage 7a 抓包时应确认接收端接受 IPv4 UDP checksum zero。
  - 静态 MAC 是唯一 L2 寻址方式，不支持 ARP。
  - route miss/error 策略当前按 `drop_on_route_miss` 执行，Stage 7a 需要在真实链路前明确异常包处理策略。
- 推荐入口命令：
  ```bash
  cd /home/xilinx/t510_fengine_bringup
  source /etc/profile.d/xrt_setup.sh
  sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_pfb_channel_window_check.py --chan0 0 --chan-count 64 --time-count 4 --timeout 2.0
  sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_qsfp_udp_preflight_check.py --force-dry-run --timeout 2.0
  ```
  Jupyter：打开 `http://192.168.100.117/lab` 或 `http://192.168.100.117:9090/lab`，进入 `t510_fengine/notebooks/10_8lane_realtime_virtual_instrument.ipynb`。

## AI 接续提示

- 判断是否进入 Stage 7，优先看 `CORE_VERSION=0x00010005`、`TX_STATUS bit1 UDP_DRY_RUN_ACTIVE=1`、`TX_STATUS bit9 frame_builder_enabled=1`、`capture_tx_frame_header()` 的 `dst_ip/dst_port/udp_length/ipv4_total_length`。
- 不要把 `tx_frame_sent_count` 解读为真实 QSFP 发包；当前它等价于 dry-run sink 接收 packet/frame。
- 频域分发已支持静态 route table；下一步若做 Stage 7a，应把 `chan0=0` 和 `chan0=2048` 分别抓到 endpoint0/endpoint1 的 pcap 作为证据。
- 时域 route table 已有 `input_mask -> endpoint_id`，但 payload lane repack 尚未完成；不要声称时域 payload 已按 mask 裁剪。
- 不要在脚本、notebook 或报告中记录 SSH 明文密码。

## 阻塞项

- Xilinx CMAC wrapper 未接入 board top；QSFP GT/refclk/pin map 与 live link-up 未验收。
- 交换机和接收节点未抓包，真实 UDP 收包未验证。
- jumbo MTU、交换机端口配置、静态 MAC 表/接收端 MAC/IP 配置尚未形成 Stage 7a 证据。
- ARP、VLAN、PTP 不在本阶段实现范围。
