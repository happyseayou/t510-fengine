# T510 current 配置

`current_release.json` 是 current 固件身份和数字尺度的唯一元数据源。
`config.example.json` 只包含 `fengine-current`，并按 `onboard_tcxo` 与
`external_10mhz` 分别保存 MTS 资格。

当前板载 TCXO 资格来自已封存的完整 40＋40 MTS 和五模式门禁。外部参考在完成同一
标准流程以及 scheduled-PPS 门禁前保持 `pending`；Agent 会拒绝该参考源的 CONFIGURE。

```bash
python3 scripts/t510_current_release.py --require-reference onboard_tcxo
python3 scripts/t510_release_qualification.py --reference external_10mhz --dry-run
```

新的硬件资格必须通过 `scripts/t510_release_qualification.py` 完整提交。该队列会调用
MTS、catalog finalizer、安装和五个 60 秒模式门禁；外部参考还会追加 scheduled-PPS 门禁。
