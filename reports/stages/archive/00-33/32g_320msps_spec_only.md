# Stage 32g：320 MS/s SPEC_ONLY

## 状态

`PASS`

## 目标

消除PFB入口每个1024-bit字之后的额外空拍，使322.265625 MHz PFB可持续消费
320 MS/s输入。

## 前置条件

Stage 32f `PASS`。

## 实施内容

- PFB入口使用“当前字+预取字”两级弹性缓冲。
- 每个1024-bit字连续发出4个256-bit cell，字间无固定空拍。
- 不修改4-tap PFB、XFFT、SPEC packet layout或UDP端口。

## 验收

- 异步80/322.265625 MHz压力仿真中无周期性`tready`空洞，输入FIFO不长期增长。
- 320 SPEC_ONLY约1.25 Mpps、83.86 Gbit/s。
- TIME关闭，PFB/XFFT/backpressure/drop/gap均为0。

## 非目标

320 TIME_SPEC仍然禁止。

## 测试、证据、版本

### 实现改动

- `rtl/pfb_channelizer.sv` 已加入“当前1024-bit字+预取1024-bit字”两级弹性缓冲。
- 每个字连续输出4个256-bit cell；没有改写4-tap PFB/XFFT和packet布局。

### 本地结果

- `tb_pfb_channelizer`持续输入/backpressure场景PASS。
- `tb_spec_udp_cmac512`、`tb_spectral_packetizer`和顶层smoke：PASS。
- Vivado在该RTL上fully routed，WNS `+0.061 ns`、WHS `+0.010 ns`。
- 证据：`../vivado/stage32c/local_verification.md`及
  `../vivado/stage32c/build_summary.md`。
- bit SHA256：
  `d9ce5b49f6c6dbb5c9ff47f83e07e992a953f30444c28a680723cd251914e175`。

### 板端与主机60秒正式门禁

命令：

```bash
python3 scripts/stage30_agent_client.py configure \
  config/stage32/configure_160_time_only.example.json \
  --bandwidth-mhz 320 --mode spec_only

python3 scripts/stage32_agent_host_gate.py \
  --bandwidth-mhz 320 --mode spec_only --seconds 60 \
  --output \
  reports/board/stage32_320msps_spec_only_board_host_pass_20260726.json
```

正式结果：

- 分类：`STAGE32_320MSPS_SPEC_ONLY_BOARD_HOST_PASS`。
- 主机60秒收到`75,034,880`个SPEC包，即`1,250,581.33 pps`、
  `83,238.693547 Mbit/s` T510 UDP payload；TIME包为`0`。
- 16个SPEC flow全部有包，parse、kernel、ring、worker-ring和app drop以及
  seq/frame/sample0 gap全部为`0`。
- 接收机完整频谱发布率为`20.934 Hz`；最终快照为16/16 block、
  `coverage_mask_lo=0xffff`，无preview错误。
- 板端窗口内SPEC增加`86,955,816`包，TIME增加`0`；science、SPEC、TX、
  route drop/error增量全部为`0`。
- PFB增加`5,434,738`帧；PFB/XFFT overflow、data/status halt、TLAST错误、
  capture backpressure和frame sample0 overflow增量全部为`0`。
- half-band保持旁路；LMK profile、continuous SYSREF、ADC/DAC固定MTS target
  `230/336`和QSFP link均健康。
- 自动STOP成功，最终`stream_accepting=false`、`flush_clean=true`，PFB状态归零。

`pfb_input_fifo_level`这个既有字段名在当前production PFB中实际是打包的运行状态，
不是单调FIFO深度。正式窗口前后解码分别为：

| 快照 | prefetch | valid frame count | fill bin index |
|---|---:|---:|---:|
| before | 1 | 4 | 749 |
| after | 0 | 4 | 2819 |

`fill bin index`随当前帧推进而循环，不能把原始整数变化解释为FIFO增长。没有长期
积压的证据由`valid frame count`保持4、所有backpressure/halt/overflow为0以及
XSim持续输入压力测试共同给出。

### 保留的首次失败证据与验证器修正

首次60秒数据面实际达到`1,250,192.8 pps / 83,212.832768 Mbit/s`，16个flow、
FPGA、PFB/XFFT和主机drop/gap也全部通过，但主机验证器在状态快照恰好观察到下一
帧正在组装的11/16 block，误报`SPEC_PREVIEW_INCOMPLETE`：

- `../board/stage32_320msps_spec_only_board_host_20260726.json`
- `../board/stage32_320msps_spec_only_board_host_20260726_host.json`

接收机的`spec_preview.complete`描述“当前正在组装的帧”，下一帧开始就会清零；
`spectrum_update_hz`则只在同一帧16个block全部组装完成后递增。验证器因此改为
严格要求`block_count=16`、无preview error且完整频谱发布率不低于1 Hz，把任意
时刻正在组下一帧只记为警告。修改后45个Python单测通过，本地与接收机脚本SHA256
均为：
`5053c062c20b4e4cddebc3fc57b32e0e2cc53bb8ce95e3134bdde0dc6b7e6669`。

### 证据

- 板端/主机总证据：
  `../board/stage32_320msps_spec_only_board_host_pass_20260726.json`
- 接收机完整证据：
  `../board/stage32_320msps_spec_only_board_host_pass_20260726_host.json`
- 总证据SHA256：
  `0364d46e5dafdbda42dde5f8d949b73007fb41615234cf84f5c00656f4c82e0c`
- 主机证据SHA256：
  `f94bc0eb8cdac2fe677934c70222b4d76fecd3edf318107c0984ba2194f28366`

## 已知限制

本步骤只完成60秒功能/满速门禁；1小时320 SPEC_ONLY和8小时轮换soak属于32h。

## 失败处置

停止science并保存PFB入口FIFO、XFFT和packet状态；修复当前Stage 32弹性缓冲后
重新执行压力仿真和板端320 SPEC。

## 下一阶段准入

本报告已`PASS`，允许进入32h单板release矩阵。
