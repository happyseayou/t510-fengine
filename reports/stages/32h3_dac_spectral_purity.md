# Stage 32h3：DAC频谱仪纯度门禁

## 状态

`NOT_STARTED`

## 前置条件

32h1、32h2均为`PASS`，且新32h2 bitstream已经完成、检查并上板。

## 人工频谱仪矩阵

- 频谱仪覆盖10～330 MHz，RBW不高于10 kHz，VBW不高于RBW，peak detector，
  输入不压缩。
- DAC0单路在60/67/170/280 MHz分别测试25%和100%幅度。
- 追加8路同时60 MHz、100%测试。
- 每项保存主峰、载波dBm、关于170 MHz的镜像、最大杂散、10/20 MHz网格杂散和
  截图。

## PASS标准

- 频率误差不超过`max(1 kHz, RBW)`。
- 60/280和67/273 MHz镜像抑制不低于60 dBc。
- 排除载波邻域后最大杂散不高于-50 dBc。
- 25%到100%载波功率增加12.04±1 dB，无削顶趋势。
- 随后的160 TIME_SPEC、320 SPEC_ONLY各60秒无新增drop/gap/overflow。

## 失败处置

- 主峰位置错误：32h2退回`BLOCKED`。
- 170 MHz干净而偏频脏：分类为PL DDS/RFDC DUC路径问题。
- 170 MHz仍有固定10/20 MHz梳状峰：分类为SYSREF/reference/DAC固定耦合。
- 不自动修改LMK、SYSREF、UDP或PFB；保存证据并保持`BLOCKED`重新评审。
