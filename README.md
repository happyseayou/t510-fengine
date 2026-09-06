# T510 F-engine

本仓库维护 T510 的唯一 current 产品。当前正式固件为 `CORE_VERSION=0x00010036`，
bitstream SHA-256 为
`e00c586a1d862d7c7af113361832a30093334493e49f943e3dd22bf44f950665`。它使用
3.84 GS/s RFDC、12×抽取/插值、160/320 MS/s 复基带、4096 通道 8-tap PFB，并在
RFDC QMC 与 PFB 舍入前应用已记录的数字尺度。

current 身份的唯一机器可读来源是
[`config/t510/current_release.json`](config/t510/current_release.json)。catalog 只有
`fengine-current`：板载 TCXO 与外部 10 MHz＋PPS 均已通过资格验证。

## 稳定入口

- Python 控制：`python.t510_control.FEngineController`
- Board Agent：`rust/t510_board_agent`
- TIME/SPEC 接收机：`rust/t510_time_rx`
- current 配置与部署：`config/t510/`、`deploy/t510/`
- RTL 到 bitstream：[RTL_TO_BITSTREAM_STANDARD.md](RTL_TO_BITSTREAM_STANDARD.md)
- 上板发布与资格：[BOARD_RELEASE_QUALIFICATION_STANDARD.md](BOARD_RELEASE_QUALIFICATION_STANDARD.md)
- 标准资格入口：`scripts/t510_release_qualification.py`
- Vivado 产物目录：`build/vivado/latest`
- Vivado 导出：`scripts/t510_export_current_project.tcl`
- 导出验证：`scripts/t510_build_latest.sh`
- 板端与接收机发布：`scripts/t510_publish_board.sh`、`scripts/t510_publish_receiver.sh`
- UDP 合同：[docs/t510_udp_payload_v2.md](docs/t510_udp_payload_v2.md)
- Stage 报告索引：[reports/stages/README.md](reports/stages/README.md)

接收机测量 API 为 `/api/measure/time`、`/api/measure/autocorrelation` 和
`/api/measure/crosscorrelation`，新数据写入 `/var/lib/t510/measurements`。历史
`/var/lib/t510/stage35` 和 8035 页面原样保留。

## 仓库维护模型

RTL、Board Agent、time_rx、catalog、部署资产和 `scripts/` 根目录的标准工具始终代表
current。运行时只使用 `/opt/t510-agent/current` 和 `/opt/t510-time-rx/current`；发布
可用 `.current.next` 做交换前校验，不保存 previous/releases，也不自动恢复旧版本。

Stage 专属脚本只放在 `scripts/stage-<编号>/`。Stage 报告中长期保存实验结论；标准流程
不依赖 Stage 目录。完整强制规则见 [T510 仓库宪法](AGENTS.md)。

## 验证

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
cargo test --manifest-path rust/t510_board_agent/Cargo.toml
cargo test --manifest-path rust/t510_time_rx/Cargo.toml
python3 scripts/check_repository_hygiene.py
python3 scripts/check_markdown_links.py
```

Vivado 任务只按 [AGENTS.md](AGENTS.md) 通过已 attach 的 GUI 提交，本地回归不会启动 Vivado。
