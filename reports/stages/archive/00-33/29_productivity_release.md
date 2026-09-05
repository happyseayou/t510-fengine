# Stage 29：F-engine 生产力版本发布

## 冻结边界

- `CORE_VERSION=0x00010030`
- bitstream SHA256：`7486a55b6f7e50e5875474e7d85299b107e9384cfff454316f64f2d3d7e9800d`
- 不修改 RTL、BD、XDC、Vivado IP、overlay、UDP header/payload 或 Rust binary preview 协议。
- X-engine、Beamformer、交换机/DGX 和 `200MHz TIME_SPEC` 不在范围内。

## 生产控制面

- 五种合法组合：100 MHz 三模式；200 MHz 两个单流模式。
- Python `Stage29Config` 提供 8 个 TIME 和 16 个 SPEC 逐 endpoint 目标，以及 8 路独立带内 DAC 频率/幅度/相位；endpoint ID、源地址/端口、flow、PFB、输入、时钟/PPS与诊断状态固定。
- 唯一 notebook：`notebooks/00_stage29_fengine_production_control.ipynb`。
- Notebook 日常界面不再提供 Gate seconds/Production gate；60 秒发布验收保留在 CLI。
- Rust receiver 常驻监听完整 24 flow：TIME `4300..4307`、SPEC `4308..4323`；Notebook 只同步 `output_mode`，不再因模式切换重启 receiver。
- Rust Web 使用本地 GridStack 12.6.0 和 Apache ECharts 6.1.0 构成七个可拖拽、缩放、吸附、响应式收缩和持久化的窗口；状态集中到顶层折叠面板。交互图持续刷新并在原鼠标坐标恢复 tooltip，amplitude 使用 dB 纵轴，amplitude/power 支持频率缩放和 Reset；waterfall 使用无交互、固定 512×64 RF/time category 坐标的 1 Hz 热图，phasor 默认使用相对参考通道。
- 六张图为 TIME、SPEC amplitude/phase/power/waterfall/phasor。phasor 在单位圆中显示每路 target bin 的幅度和相位，支持原始/相对相位及忽略幅度的等长箭头。
- Rust Web 的唯一频率映射优先使用 header `spec_sample_rate_hz`，采用 `RF = center - signed_bin * sample_rate / 4096` 并按 RF 升序显示；横轴、target、peak、waterfall、phase 和 phasor 共用该映射。
- SPEC 相位只比较同一 FFT bin 的通道；不同 target bin 显示独立结果，不产生伪相对相位。
- TIME Y scale 的 Rust、HTML 和 Reset defaults 均为 `512`。

## 软件验证

- Python Stage 29 共 10 个单元测试通过，覆盖五模式、非法双流、参数边界、固定生产合约、速率、路由/PFB 开关和频率几何。
- Rust receiver 共 33 个单元测试通过，并覆盖三种 output mode 的 active flow、24-flow 常驻接收、逐通道 target、ECharts 七窗口、RF 符号方向、Nyquist 范围、header 采样率优先及 WebSocket binary 协议稳定性。
- 独立浏览器数学测试覆盖 `center=100 MHz、target=60 MHz` 映射、RF 升序、phasor 幅度归一化、等长和相对相位；内联页面、ECharts 拼接资源及测试脚本均通过 `node --check`。
- Rust 通过全部单元测试和 `clippy --all-targets`；clippy 仅对白名单中的既有 receiver 风格 lint 放行，补充的 Stage 29 代码无新增 warning。全仓 `cargo fmt --check` 仍会命中既有 receiver 格式差异，本次为遵守“只改 Web 预览、不重排接收代码”的边界，没有提交全文件 rustfmt 噪声。

## 现场 60 秒门禁

每种 board case 均由 `scripts/stage29_board_validate.py` fresh-download；host 使用匹配模式的 Rust flow 数并运行 `scripts/stage29_host_validate.py`。

```bash
sudo -E python3 scripts/stage29_board_validate.py --bandwidth-mhz 100 --mode time_only --seconds 60
sudo -E python3 scripts/stage29_board_validate.py --bandwidth-mhz 100 --mode spec_only --seconds 60
sudo -E python3 scripts/stage29_board_validate.py --bandwidth-mhz 100 --mode time_spec --seconds 60
sudo -E python3 scripts/stage29_board_validate.py --bandwidth-mhz 200 --mode time_only --seconds 60
sudo -E python3 scripts/stage29_board_validate.py --bandwidth-mhz 200 --mode spec_only --seconds 60
```

本次已将生产目录同步到 PYNQ，并用 PYNQ venv 成功实例化唯一 notebook；Rust release 已按 24 workers、24 flow 和完整 `4300..4323` ntuple 映射重启。现场 100 MHz TIME_SPEC 同时达到 TIME/SPEC 各约 `480 kpps / 31.95 Gb/s`，TIME WebSocket 实测一帧含 8 路、32 个采样点及 1024 点重建曲线，SPEC 预览 `16/16` complete。CH0 的 60 MHz 实际峰值和 target 均映射到 `60.010 MHz`，不再显示为约 140 MHz。

5 秒快速 host gate 的活动流、两路速率和合计 payload 均达门槛，但仍观察到运行期 gap/drop 以及 NIC discard，因此未签字通过，也不伪造五模式 60 秒 PASS。上述五个 fresh-download board/host 结果仍是正式发布签字前必须补齐的最终证据。
