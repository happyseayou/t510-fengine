# 复可见度背景处理标准

入口为 `scripts/t510_background.py`，数值实现为 `python/t510_background.py`；仅依赖Python与NumPy，不依赖Stage目录。
部署入口为GB10 `/opt/t510-analysis/current/scripts/t510_background.py`，用同目录current/venv/bin/python执行。

## 默认行为与范围

`apply --mode auto` 为默认：显式给定且验证匹配的模板生成独立corrected产品。未提供模板、身份不匹配、时段重叠或过期时生成raw_only产品说明和具体原因；不偷偷生成新模板、不改写输入。
`required` 要求必须可扣除，否则报错；`off` 明确只保留原始引用。模板文件损坏在auto下也报错，不隐式吞错。
这是通用分析入口的默认，不是更改F-engine、X-engine或time_rx的原始采集API，也不会改写历史网页。

## 输入与调用

输入NPZ包含 `visibility[time,pair,bin]` 复数、`weights[time,bin]` 正有效帧数。
必须由采集适配器先验证原始数据manifest及块SHA，然后给选定窗口提供context JSON。

```
python scripts/t510_background.py fit --input reference.npz --context reference.json --output template --valid-for-seconds 300
python scripts/t510_background.py apply --input target.npz --context target.json --template template --output product
```

输出目录必须不存在，防止覆盖。模板包含background.npz、template.json及SHA；扣除产品包含corrected.npz、product.json及SHA。原始数据由source_id和source_manifest_sha256引用，调用方必须保留原始档。

context必需字段：

- initialization_epoch：由采集控制者管理的初始化会话标识；reset/重载后必须更换，不能从相同core版本推断相同初始化。
- wiring_id：确认的接线身份，参考负载与天线不可混用。
- configuration_sha256：配置规范JSON的SHA，须覆盖实际时钟/MTS、采样率/频段、DSA/QMC/PFB/FFT尺度及相关校准状态。
- core_version、bitstream_sha256：实际固件身份。
- pair_order、frequency_bins：精确数组顺序。
- source_id、source_manifest_sha256：已经验签的采集来源。
- start_unix_s、end_unix_s：所选窗口采集时段；训练、检验必须不重叠，检验不能早于训练结束。
- role：reference或target；只有显式reference可以训练。

通用函数不能感知用户重新插线、未记录reset或伪造context；采集适配器必须负责上述真实性。仅JSON一致不等于硬件自动追踪完备。

## 方法与有效期

B=sum(w*V)/sum(w)，每ADC对每bin独立复均值；R=V-B，然后才取幅度/相位。固定B不改变中心化散布或复可见度的Allan方差；幅度模的Allan是另一指标，不作不变承诺。
当前参考条件候选60秒逐bin。300秒是验收队列的保守配置上限，不是稳定性保证；按目标采集时刻而非分析运行日期检查，历史重算不因此失效。
不自动邻频平滑、不用目标数据续训。复相关扣除不修改自功率，功率归一化仍使用原始自功率。

## Stage验收适配

`scripts/stage-36/t510_stage36_background_standard_queue.py` 调用此通用实现，不反向成为标准依赖。
新八路独立50Ω连续120秒，前60秒参考，后60秒验证；保存全28对4096bin的100ms扣除产品，另保留原始采集manifest。
采集前后核对初始化、OCB2、完整DSA字段；本次epoch仅代表此受控连续窗口，不授权任意后续采集继承。
自动验证产品复数相减、原始未变、中心化散布与复Allan差分不变，生成网页及浏览器验收。
天线模板迁移属于Stage37；不在当前默认规则中暗含授权。
