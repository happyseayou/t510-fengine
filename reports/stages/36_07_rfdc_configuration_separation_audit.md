# Stage 36：RFDC 配置与重置可分离性核查

2026-09-09。范围：代码调用链、已部署软件身份、AMD 文档、现有证据及离线调用测试。
未启动采流、未修改板上配置、未部署新组件。本结论是软件路径可分离，不是新硬件实验通过。

## 结论和建议

可以首先比较 **P：恢复相同配置** 与 **R：重置 RFDC 后恢复完全相同配置**。
P 仍包含 MTS、NCO 相位复位、QMC 重写及 PL 采流参数恢复，不能命名“仅 mixer”。
两组共同流程相同，仅 R 增加八个 tile Reset。这样优先检验重置及其触发的初始化过程
是否在既有配置恢复之外增加相关变化。重置后的模拟/校准状态变化仍不能由这个比较进一步分离。

| 操作 | S 停流对照 | P 恢复配置 | R 重置再恢复 |
|---|---|---|---|
| 同一板载时钟 profile、同一 PL | 保持 | 保持 | 保持 |
| 显式 ADC/DAC tile Reset | 无 | 无 | 八次 |
| MTS 与必要 SYSREF | 无 | 有 | 有 |
| mixer/NCO、NyquistZone、NCO 相位复位 | 无 | 有 | 有 |
| 当前 QMC 增益与 PL 输出/网络配置恢复 | 无 | 有 | 有 |
| 显式写校准系数/冻结校准 | 无 | 无 | 无 |

准备路径应先连接现有 core（download=False），锁定硬件配置锁，核验停止/DAC静音、
同一锁定时钟、core/hash、增益、接收器无活动任务。两组同样开启准备所需 SYSREF，
R 才调用 reset_all_rfdc_tiles，然后共用：

```python
controller.prepare(
    same_config,
    fresh_download=False,
    program_dac=False,
    clock_ref="tcxo_10mhz",
    clock_profile="160m_10m_request_manual_clkin0",
    force_clock_reconfigure=False,
    require_clock_preserved=True,
)
```

**必须已有连接的 core**；prepare 即使 fresh_download=False，只要 self.core=None 仍会下载 PL。
时钟不符直接失败，不走恢复分支。动作前后保留 MTS epoch/offset、校准、温度、尺度、时钟与计数器。
两组共用同一包装器、输出格式和异常停流/静音逻辑，避免复制两套相似流程。
本次仅核查该设计，未新增板端 P 执行入口或提交队列。

## 已发现的接口语义

1. t510_control.prepare 固定 initialize=True，但 apply_sysref_locked_observation_config
   只有在实际重配时钟的分支才调用 reset_all_rfdc_tiles；initialize=True 本身不等于 tile Reset。
2. require_mts=False 不是跳过 MTS：_configure_rfdc_sysref_locked_pair 无条件调用
   _run_rfdc_mts_sequence(required=require_mts)。该参数控制必需性/失败处理。
3. prepare_clock_preserving_hot_update 会 connect(download=True)，只保留时钟，不保留 PL，
   因此不适合这里的 P 组。fresh_download=False 也需要已经连接 core。
4. production mixer writer 同时写 ADC/DAC 的 NyquistZone、MixerSettings，默认 ResetNCOPhase；
   后续 SYSREF 才提交动态更新。只调用底层 block writer 并看到读回成功，不等于硬件事件已提交。
5. sysref_no_reset 是不执行 NCO 相位复位的分支，不是“不重置整个 RFDC”的开关。
   真正的纯 mixer 组需要单独封装 SYSREF 提交及原状态验证，不能用 require_mts=False 冒充。

## 身份与离线证据

板上 /opt/t510-agent/current 与本地以下三个文件 SHA256 一致：
- python/t510_fengine.py：1aa07fde7abc02d73d12dc079f0134acdea9e98a8c8d684c8e6e33e9392cbc37
- python/t510_hw.py：94312ab7d118c49ed09fc0653e1cbd23785d6a8aa7273d461288e918117b788a
- python/t510_control.py：55bcde2f62fb00296feee695de766e4ba94fa02e7721430484174a1a2f2194e0

板上 xrfdc Python 包中 tile.Reset 与 block.ResetNCOPhase 是不同 C API 的直接包装。
离线脚本：scripts/stage-36/t510_stage36_config_separation_audit.py。
四项测试 PASS：锁定时钟路径不调用 Reset；坏时钟先失败；require_mts=False 仍调用 MTS；
sysref_no_reset block writer 不复位 NCO、也不调用 UpdateEvent（提交阶段在外层）。
这些测试使用假硬件对象，只证明 Python 调用边界，不证明底层 C 驱动和硅片不存在其他副作用。
日志：build/rfdc-separation-audit/offline-tests.log。

## 文档与已有实验的联系

AMD 的 [XRFdc_Reset](https://docs.amd.com/r/en-US/pg269-rf-data-converter/XRFdc_Reset)
说明 tile Reset 会恢复初始寄存器设置；
[启动流程](https://docs.amd.com/r/en-US/pg269-rf-data-converter/Power-on-Sequence-Steps)
包含 ADC 校准。
[ResetNCOPhase](https://docs.amd.com/r/en-US/pg269-rf-data-converter/XRFdc_ResetNCOPhase)
用于武装 NCO 相位累加器复位，不能与 tile Reset 混淆。
[校准系数 API](https://docs.amd.com/r/en-US/pg269-rf-data-converter/XRFdc_GetCalCoefficients)
把 OCB2 标为前台校准，OCB1/GCB/TSCB 标为背景校准。

这与上一轮 R/F 后 OCB2 系数改变、S/M 后不变的记录相符；但系数变化只是重初始化线索，
不是 OCB2 定责。Stage34 的部分校准冻结试验未稳定改善，因此本轮不默认冻结或恢复旧系数。

## 下一轮判读

先做停止状态下的短硬件功能核验，再将 P/R 交错并用 S 夹住，每种干预三次、每段100秒。
沿用上轮修正：等待发生在接收器武装前；保留100ms原生全频产品，失败立即停流静音。
- P 接近对照、R 显著更大且可重复：支持重置及其带来的状态重建是额外触发因素。
- P/R 都有大变化：配置恢复本身也足以触发，才值得继续拆 NCO、QMC 与提交事件。
- 两者都未复现：报告该状态下未复现，不能宣布现象消失。

这里的“显著更大”是工程描述，统计结论须考虑三次重复、温度、顺序、状态继承及频点多重比较。
没有已知共同信号时，相关下降仍不能证明有用相干响应正常。
