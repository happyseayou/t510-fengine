# Stage 36：科学复评与 8036 交付

状态：`TECHNICAL_COMPLETE / CLIENT_UI_REVIEW_REQUIRED`  
日期：2026-09-06（CST）

## 正式输入与数据完整性

正式队列为 `stage36-science-20260906-1852`，数据和证据位于 GB10：

```text
/var/lib/t510/measurements/stage36-science-20260906-1852-queue/
```

队列使用 core `0x00010036`、bitstream SHA-256
`e00c586a1d862d7c7af113361832a30093334493e49f943e3dd22bf44f950665`、板载 TCXO、
中心频率 200 MHz、320 MS/s、QMC `1.9998779296875`、PFB output shift 16 和 FFT shift
`0x0556`。八路输入为用户确认的独立 50 Ω，DAC 保持静音。

13 个阶段全部完成：TIME_ONLY 900 s；A/B/C 各自的 30 s TIME pre、900 s 自功率和 30 s
TIME post；全部 28 个 ADC 对的 30 s TIME pre、900 s 全频复可见度和 30 s TIME post。
TIME900 每路处理 288,000,000,000 个样点；复相关发布和消费均为 1,125,000,000 包，
`ring_drops=0`，16 个频率块全部完成。最终 manifest、逐数据集 manifest、TIME900 独立
复算和跨数据集 SHA-256 复核均 PASS。

首次队列在 TIME900 完成后因见证验证模块名写错而停止。恢复入口严格验证原错误、已封存
TIME900 和 52 ms PCAP 后，只裁取连续 50 ms 见证并从下一阶段继续，没有重复采 TIME900。
原故障、恢复身份及无法在导入失败前持久化的 live post-window 快照均保留在队列状态中；
该窗口的连续性由接收机 manifest、八路质量账本、运行遥测和原始 PCAP 共同建立。

## 读数门禁

50 ms TIME 见证含每路 16,000,000 个 I/Q 样点，无削顶；连续 4096 帧 SPEC 见证覆盖全部
4096 通道，无削顶。实测标准差为：

| 产品 | Stage 35 原始范围 | Stage 36 原始范围 | Stage 36 统一尺度范围 |
|---|---:|---:|---:|
| TIME I/Q | 4.117–4.674 ADU | 8.211–9.195 ADU | 4.106–4.598 ADU |
| F-engine 全频 I/Q 标准差中位数 | 2.122–2.324 count | 8.005–8.720 count | 2.001–2.180 count |

Stage 36 原始值全部落在 8–12 count 合同内。消除数字尺度后，中位数相对 Stage 35 分别
变化 -1.19% 和 -3.18%。统一尺度使用实际电压增益：TIME 除以
`1.9998779296875`，F-engine 除以 `3.999755859375`；TIME 功率除以增益平方，F-engine
功率及复可见度除以其增益平方，相应绝对 Allan 方差除以增益四次方。相对功率、归一化
复相关和相对 Allan 量不因统一电压尺度改变。

这些结果证明数字读数范围已按设计增大，并保持与 Stage 35 相近的统一尺度。它不证明 ADC
丢失的信息得到恢复，也不把 count 增大、Allan 变化或伪相关变化直接解释为科学性能改善。

## GB10 原地分析

本轮目标是重复当前 `8035` 最终页面的产品，不重复早期对全部 bin 生成 ACF、PSD、温度回归
和 bootstrap 的七小时批处理。因此没有使用 HPC。GB10 直接复用 Stage 35 已验证的：

- TIME/SPEC PCAP 解包和严格 sample0 连续区间；
- 4096 点 Hann FFT 参照；
- 900 s TIME 的 10 ms 原生数组及 100 ms／1 s 加权合并；
- A/B/C 900 s 自功率按 bin 读取；
- 28 对复可见度 100 ms 原生产品及 1 s 产品；
- 重叠 Allan 方差、白噪声参考、复向量 Allan 和相位可靠性门控。

原始 SPEC superset 含每块 4098 包，以确保存在至少 4096 个共同连续帧。Explorer 派生数组
明确冻结其中前 4096 个已验证共同 sample0 帧；首次 API 门禁因错误地期望解包器自动只保留
4096 帧而停止，修复后从已有派生数组裁取，未重新读取或重算正式长数据。恢复前后数组身份
均登记在 `resume_history`。

## 8036 发布与验收

交付入口：

```text
http://192.168.100.162:8036/
```

服务 `t510-stage36-explorer.service` 为 `active/running`，只接受 GET/HEAD。页面复用 `8035`
当前稳定布局、单共享 WebGL 图面、本地 Plotly strict bundle、公式实算、多 ADC/ADC 对和多
频点选择、100 ms／1 s 产品、白噪声参考及相位可靠性标记。页面顶部显示 Stage 35/36 原始
与统一尺度范围，并明确说明数值放大不等于科学改善。

候选数值 API 门禁覆盖 TIME raw、10/100/1000 ms TIME、4096 帧 F-engine raw、A 扫描
100 ms 自功率、ADC0–1 的 100 ms／1 s 复可见度，以及单路/ADC 对 Allan。真实 Chromium
以两个 ADC、两个 ADC 对和三个默认频点完成渲染，页面到达“权威数据就绪”，没有章节失败，
静态资源无外网 URL。发布后独立核对：

- `8036 /healthz`：`stage36-simple`；
- `8035 /healthz`：`stage35-simple`，历史页面保持在线；
- Explorer artifact manifest：29 个不可变文件，SHA-256 自检 PASS；
- 数据根：
  `/var/lib/t510/measurements/stage36-science-20260906-1852-explorer-20260906-212658/`。

技术门禁已完成。最后只需用户在目标浏览器打开 `8036`，检查文字、布局和交互是否符合实际
阅读习惯；该人工观感不由 GB10 headless Chromium 代替。

### TIME 功率图温度右轴

`TIME_ONLY 900秒平均数字功率`图已加入右侧 Y 轴的板上 PL 温度曲线。温度取自同一正式
TIME 窗口的 AMS 遥测，以采集实际起点对齐时间轴；保留 900 个约 1 Hz 原始点，没有插值成
功率图的 100 ms 点。温度点覆盖 0.857–899.881 s，记录均值范围为
39.032–40.912 °C。图注明确区分板上 PL 温度和未经物理定标的数字噪声功率。

轻量更新队列未重算长数据。候选 API 验证了 9000 个 100 ms 功率点和 900 个温度点，真实
Chromium 验证了温度说明能够显示；current-only 交换后 `8036` 与历史 `8035` 均健康。更新
证据位于：

```text
/var/lib/t510/measurements/stage36-science-20260906-1852-temperature-overlay-20260906-134419/
```
