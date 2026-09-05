# 上板发布与资格标准流程

标准入口：

```bash
PYNQ_SUDO_PASSWORD=xilinx python3 scripts/t510_release_qualification.py \
  --reference onboard_tcxo
```

参考源只能为 `onboard_tcxo` 或 `external_10mhz`。队列固定执行：预检 → MTS discovery
40 次 → fixed 40 次 → catalog finalize/install → 五个合法模式各 60 秒 → 结果封存。
五个模式是 160 TIME、160 SPEC、160 TIME+SPEC、320 TIME、320 SPEC；丢包、序号断点、
FIR 饱和、FFT 溢出和接口错误必须全为零。证据写入
`build/qualification/latest/<reference>/`。失败时队列立即停流、DAC 静音并保留现场。

外部参考首先选择 CLKin2，必须同时证明 PLL1/PLL2 锁定、PPS 计数增长和
`pps_recent=true`。discovery 按 RFDC 12-cycle 量化规则生成目标；DAC 没有共同确定性目标
时使用单设备相对对齐 `-1`。五模式之后，在 160 TIME+SPEC 下追加 scheduled-PPS 门禁：
目标至少为当前 PPS＋5，验证目标沿提交、TIME/SPEC 首包身份和 sample0、目标前无数据，
并连续 10 秒保持零丢包。全部通过才把 `external_10mhz` 写为 `qualified`。

未接线时只运行：

```bash
python3 scripts/t510_release_qualification.py --reference external_10mhz --dry-run
```

发布遵循 current-only 和 fix-forward：接收机先用 `scripts/t510_publish_receiver.sh`，板端再用
`scripts/t510_publish_board.sh`；交换后失败时保留新 current、停止服务和保存证据，不恢复旧版。
