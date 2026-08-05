# Stage 5a: Jupyter Instrument Publish

## 阶段目标

在 Stage 5 overlay 验收通过后，把当前可靠的数据面、debug capture、preview 和 SPEC dry-run header capture 发布成 PYNQ Jupyter 网页仪器入口，让板端可以马上稳定查看虚拟示波器和频谱仪。

## 输入基线

- Stage 5 已完成并通过板端 `pynq_spec_dry_run_check.py`。
- 使用同一个 Stage 5 overlay：`CORE_VERSION=0x00010003`。
- PYNQ 目标：`xilinx@192.168.100.117`。
- Jupyter 发布目录：`/home/xilinx/jupyter_notebooks/t510_fengine`。

## 完成内容

- 新增 `notebooks/09_single_board_virtual_instrument.ipynb`，作为网页仪器稳定入口。
- Notebook 第一版包含：
  - 一键加载 Stage 5 overlay。
  - 一键 `tcxo_10mhz + free_run + ADC0 mask` 初始化。
  - 显示 core/status/debug/preview/TX dry-run/FIFO 状态。
  - 显示 ADC0 时域波形。
  - 显示 1024 点 debug FFT 频谱。
  - 提供 DAC tone enable、amplitude、phase step 控制。
  - 触发 SPEC dry-run header capture 并展示解析结果。
- 新增 `scripts/pynq_jupyter_instrument_smoke.py`，复用 notebook 背后的初始化、preview、FFT 和 header capture 逻辑，不依赖 widget。
- 新增并修正 `scripts/pynq_publish_jupyter_instrument.sh`：
  - 发布 `overlay/`、`python/`、`notebooks/` 到 Jupyter 目录。
  - 排除 `__pycache__/` 和 `.ipynb_checkpoints/`，避免本机缓存和 Jupyter 旧 checkpoint 影响发布。
- 已把 Jupyter 文件发布到板端。

## 验证证据

- 本地 sanity：
  ```bash
  bash -n scripts/pynq_publish_jupyter_instrument.sh
  python3 -m py_compile python/packet.py python/t510_fengine.py scripts/pynq_jupyter_instrument_smoke.py
  python3 -m json.tool notebooks/09_single_board_virtual_instrument.ipynb >/dev/null
  ```
  结果：`STAGE5_LOCAL_SANITY_OK`。
- PYNQ Jupyter 端口探测：
  - `http://192.168.100.117/lab` 返回 HTTP 200。
  - `http://192.168.100.117:9090/lab` 返回 HTTP 200。
- 发布命令：
  ```bash
  PYNQ_TARGET=xilinx@192.168.100.117 \
  PYNQ_JUPYTER_DIR=/home/xilinx/jupyter_notebooks/t510_fengine \
  scripts/pynq_publish_jupyter_instrument.sh
  ```
  结果：发布成功。
- 板端文件确认：
  - `/home/xilinx/jupyter_notebooks/t510_fengine/notebooks/09_single_board_virtual_instrument.ipynb`
  - `/home/xilinx/jupyter_notebooks/t510_fengine/overlay/t510_fengine.bit`
  - `/home/xilinx/jupyter_notebooks/t510_fengine/python/t510_fengine.py`
- Stage 5a 板端 smoke：
  ```bash
  cd /home/xilinx/t510_fengine_bringup
  source /etc/profile.d/xrt_setup.sh
  sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_jupyter_instrument_smoke.py --mask 0x1 --timeout 2.0
  ```
  结果：`PASS`。
- Smoke 关键读回：
  - `core_version=0x00010003`
  - `streaming=true`
  - `rfdc_current_valid_mask=0xffff`
  - `preview_count=256`
  - `preview_sample0=196447178`
  - `debug_peak_bin=8`
  - `debug_peak_power=254330152`
  - `tx_fifo_high_water_words=3`
  - captured header：`version=2`，`stream_type=0/SPEC`，`payload_bytes=8192`，`flags=10`。

## 阶段衔接说明

- 下一阶段可依赖：Jupyter 已有稳定入口；ADC0 单路 preview、debug FFT、DAC tone 控制、TX dry-run/FIFO 状态、SPEC header capture 都可通过网页 notebook 操作。
- 下一阶段不能依赖：多路相位仪器完整验收、浏览器端长期运行稳定性、CMAC/QSFP 真实发包、正式 4096-channel PFB。
- 剩余风险：本阶段完成了文件发布和后端 smoke，没有用浏览器自动截图逐单元验收；matplotlib/widget 的显示体验仍需在实际浏览器里人工确认。
- 推荐入口：
  - 打开 `http://192.168.100.117/lab` 或 `http://192.168.100.117:9090/lab`。
  - 在文件树中打开 `t510_fengine/notebooks/09_single_board_virtual_instrument.ipynb`。
  - 先运行 notebook 顶部的 overlay/init/status 单元，再运行 preview/FFT/header 单元。
- 推荐复测命令：
  ```bash
  cd /home/xilinx/t510_fengine_bringup
  source /etc/profile.d/xrt_setup.sh
  sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_jupyter_instrument_smoke.py --mask 0x1 --timeout 2.0
  ```

## AI 接续提示

- 用户问“什么时候能使用 Jupyter 虚拟示波器和频谱仪”时，当前答案是：现在可以打开 Stage 5a notebook 使用。
- notebook 的稳定性判断先看 `pynq_jupyter_instrument_smoke.py`，再看浏览器显示；不要先改 widget 复杂度。
- 新增仪器能力时，先保留 ADC0 单路默认路径，再逐步打开多路相位/频谱增强。
- 不要在 notebook、脚本或报告里写入 SSH 明文密码。

## 阻塞项

- Stage 5a 第一版使用已发布且后端 smoke 已通过；没有阻塞使用的工程项。
- 浏览器端逐单元截图和长时间交互稳定性未自动化。
- 多路仪器、CMAC link-up 视图、正式 PFB 频谱视图留待后续阶段。
