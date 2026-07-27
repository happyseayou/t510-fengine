# Stage 32 本地验证记录

## 结论

`PASS` 仅表示当前 Stage 32 源码的离线、仿真和软件单元测试通过；32b
clock-only与32c RFDC/MTS已经由各自板端报告单独闭合，本记录本身不替代板端UDP
或主机收包门禁。

## 身份

- 验证日期：`2026-07-26`（Asia/Shanghai）。
- Git HEAD：`53f46bb73a2dca3d32af86c95b02561796c1d53c`。
- 工作树包含尚未提交的Stage 32改动，因此bitstream以SHA256作为实际身份。
- bitstream SHA256：
  `d9ce5b49f6c6dbb5c9ff47f83e07e992a953f30444c28a680723cd251914e175`。
- 构建宏：
  `T510_STAGE27H_PRODUCTION_ONLY T510_STAGE27I_ANTI_ALIAS T510_STAGE27J_PFB T510_STAGE32`。

## 执行结果

| 检查 | 命令 | 结果 |
|---|---|---|
| LMK profile离线一致性 | `python3 scripts/stage32_verify_lmk_profile.py` | PASS；136 writes，TCS/register SHA匹配，continuous GPIO未变化 |
| 55-tap half-band | `python3 scripts/stage32_verify_halfband55.py` | PASS；ripple 0.000742 dB，系数stopband 86.539 dB，定点动态最差85.070 dB，DC gain精确，delay 27 |
| Python | `python3 -m unittest discover -s tests -p 'test_*.py'` | PASS；45 tests |
| Python语法 | `python3 -m py_compile ...` | PASS |
| Board Agent Rust | `cargo test --manifest-path rust/t510_board_agent/Cargo.toml` | PASS；5 tests |
| Receiver Rust | `cargo test --manifest-path rust/t510_time_rx/Cargo.toml` | PASS；7 library + 29 binary tests |
| RTL/XSim | 完整sweep，修正断言后重跑 `tb_axi4_to_axil_bridge` | PASS；31个默认testbench当前日志均有PASS且无CHECK FAILED |

完整XSim当前日志保存在本目录的 `xsim/`。完整套件首次运行时只有
`tb_axi4_to_axil_bridge` 使用旧core-version期望值而失败；断言按
`T510_STAGE32 -> 0x00010032` 修正后单独重跑通过。该修改只影响testbench，
不影响已生成的bitstream。

## 尚未覆盖

- 三次LMK断电冷启动和160/10 MHz示波器证据。
- 160三种模式和320 SPEC_ONLY板端及 `192.168.100.162` 主机的UDP无损验收；
  320 TIME_ONLY已经通过60秒正式门禁。
