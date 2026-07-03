# T510 Jupyter 入口

## Stage 27h 生产入口

当前生产流程只推荐一个 notebook：

1. `15_stage27h_time_spec_fft_fullrate_control.ipynb`

该 notebook 是 Stage 27h 的生产控制与生产预览界面，覆盖：

- TIME/SPEC 科学数据流配置和状态。
- 接收端 IP/端口/MAC、模式、带宽、中心频率和 8 路 DAC-ADC 环回控制。
- DAC tone 频率、幅度和逐通道相位控制。
- 基于真实 RFDC preview IQ 的 RF 等效波形预览。
- FFT-only 生产频谱预览。

Stage 27h 生产合约使用 TIME 端口 `4300..4307`、SPEC 端口 `4308..4323`，SPEC 产品为 `FENGINE_IQ16` FFT-only：`4096` 个 channel、`16` 个 block、`256` 个 channel/block、`1` 个 spectrum-time、`8` 路输入、`8192B` 载荷。

Rust Web `:8089` 是主机监控端，显示 TIME RF 等效波形、完整 `16/16` block FFT-only 频谱/瀑布、target-bin 相对相位滚动图、24 流速率和 drop/gap 状态。相位滚动图默认参考 `CH1`，用于观察当前 CH0 长线相对其它近等长通道的稳定相位偏移。

## 归档 Bring-Up Notebooks

旧 notebook 只作为时钟、RFDC、UDP dry-run、DAC/ADC 环回和历史 debug 检查的 bring-up 参考，不作为 Stage 27h 生产验收条件。

`14_stage27g_time_spec_fengine_control.ipynb` 保留为 Stage 27g `/32` 节拍参考入口；`13_astronomer_rf_observation_console.ipynb` 保留为历史 rich observation/debug console。
