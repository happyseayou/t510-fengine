# Stage 32i：双板物理同步闭合

## 状态

`BLOCKED`

## 阻塞原因

当前只有一块T510，缺少第二块板和公共射频分路条件。单板结果不能证明跨板模拟相位、
群时延或共同孔径一致。

## 解除阻塞所需硬件

- 两块T510；
- 公共10 MHz和公共1 PPS；
- 低相噪tone或相关噪声源；
- 二路功分器；
- 已知长度或可交换的参考/射频线缆。

## 验收

- 两板使用相同LMK profile、bit SHA、MTS target、PFB系数和generation事务。
- 验证160 TIME_SPEC、320 TIME_ONLY、320 SPEC_ONLY。
- 至少20次cold/warm restart。
- generation、TAI epoch和首包sample0一致。
- 整数lag重复到1个320 MS/s基准样点以内。
- 拟合残余时延<0.1个基准样点。
- 最高已验证科学频带内10分钟残余相位RMS<10°。
- 交换线缆后可区分板卡固定项和线缆固定项。

## 当前可做工作

单板阶段继续保留完整MTS latency、profile ID、signal-chain tag、PFB coefficient ID和
温度等 provenance，为第二块板接入提供可比较基线。

## 失败处置

任一板出现target超限或lock/MTS错误时，结束当前generation，不自动放宽target。

## 下一阶段准入

阻塞解除并取得共同输入实测后才能把Stage 32总体状态改为`PASS`。
