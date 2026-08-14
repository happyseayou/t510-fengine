# Stage 34b-1：RFDC 校准观测与安全冻结

## 结论

状态为 `PASS / SOFTWARE_FREEZE_SUPPORTED / NO_BITSTREAM_CHANGE`。

当前 Stage 34 bitstream 和板端 PYNQ `libxrfdc` 已实机确认支持：

- `XRFdc_SetCalFreeze`
- `XRFdc_GetCalFreeze`
- `XRFdc_GetCalCoefficients`

八路 ADC 可以由软件统一 freeze/unfreeze，并能读取 OCB1、OCB2、GCB、TSCB。没有修改
RTL、RFDC XCI、PFB、UDP 或 bitstream，产品身份仍为 `CORE_VERSION=0x00010034`，bitstream
SHA-256 仍为
`c21d93f5ea71e9ac17a4448cff138a8faaf9c7347d879be919b680d196b8a5be`。

## 实现

Board Agent `0.3.3`新增：

- `GET /api/v2/rfdc/calibration`
- `POST /api/v2/rfdc/calibration/freeze`
- `POST /api/v2/rfdc/calibration/unfreeze`
- `POST /api/v2/rfdc/calibration/preview`
- 受控诊断入口`POST /api/v2/rfdc/calibration/train-freeze`

逻辑 ADC0～ADC7 按 RFDC contract 的八个已启用 ADC block 生成，不把容器中未启用的
物理 slice 当作输入。每路读取四类、每类8个32-bit系数。哈希顺序固定为
`ADC lane → OCB1/OCB2/GCB/TSCB → Coeff0..7`，每个数按 little-endian u32 输入SHA-256。

freeze事务固定写入`DisableFreezePin=1`和`FreezeCalibration=1`。任何一路调用或回读失败，
都尝试八路unfreeze、STOP和DAC静音；不允许留下部分冻结状态。普通freeze要求停流、未
prepare/arm且DAC静音。训练事务只接受八路`center+60 MHz`、25%单音，并在freeze成功后
由同一个helper静音DAC。

STOP时preview记录器没有输入握手。软件没有用正常START偷偷发送UDP，而是临时把
SCIENCE和TX同时置于dry-run，只启动内部全局数据握手，完成1024点八路preview后STOP并
原样恢复两个控制寄存器。实机证明TIME、SPEC和TX sent计数增量均为0。

## 实机验收

- 初始动态校准：frozen mask=`0x00`。
- 八路freeze回读：frozen/requested/software-owned mask均为`0xff`。
- 间隔2秒的两次冻结读取：GCB和TSCB SHA-256分别完全一致。
- OCB1 SHA在两次读取间变化；这与Stage 33a的已知行为一致，本阶段只记录，不将其误判
  为freeze失败。
- unfreeze回读：frozen/requested mask=`0x00`。
- 停流preview：八路1024点、`science_udp_stopped=true`，三个science/TX包计数增量为0，
  SCIENCE/TX控制均恢复。
- 最终状态：`streaming=false`、`stream_accepting=false`、DAC enable mask=0、八路幅度码
  全0、frozen mask=`0x00`。

原始JSON位于`build/board/latest/evidence/rfdc_calibration/34b1`，manifest SHA-256为
`f852957288cdefb5a6aefae935912c31a65f37fdd08692d80a1be9d8a73019e0`。

