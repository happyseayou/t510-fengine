# Stage 36 标准背景处理接入与新参考验收

2026-09-12。用户确认八路ADC均接回独立50Ω；原功分器接线模板不沿用。TG保持关闭，原DSA20/0/20/0/0/0/0/0保持，不隐式改模拟或数字增益。

## 已实现

通用数值模块 `python/t510_background.py`，标准入口 `scripts/t510_background.py`，文档 [标准说明](../../docs/BACKGROUND_ANALYSIS.md)。
GB10安装 `/opt/t510-analysis/current/`，独立venv NumPy2.5.3；不依赖Stage目录提供数值实现。
默认auto：匹配模板生成独立扣除产品；缺失/身份失配/重叠/过期则raw_only并明确原因。required拒绝不匹配；off不扣；损坏模板始终报错。
初始化epoch、接线、配置hash、core/bit身份、ADC对/频点顺序和采集时段纳入门禁。模板仅允许显式reference训练。
context由采集适配器负责真实性；没有声称能够自动感知任意外部插线或未记录reset。
原始采集API不变，历史数据和网页不改写；默认是本标准分析入口的默认，不是所有旧客户端已自动换行为。

四项数值与门禁测试在部署环境PASS：加权复均值、原始不变与固定相减差分不变、状态/接线/配置/几何不匹配拒绝、时间窗口/过期/缺模板、目标不得训练、损坏/无效权重报错。
本机python缺NumPy，未在本机环境安装依赖，改用GB10已部署环境完成验证。

## 完整验收队列

`stage36-background-standard-20260912`：预检 → 120秒完整参考采集 → 原始SHA与数值验证 → 首60秒模板 → 后60秒全28对4096bin原生100ms扣除产品 → 产品复算 → 生成网页 → 停流/封存 → 自动发布并浏览器验收。
主采集结束后，队列生成全带扣除产品，6个默认频点验证中心化波动与复Allan(0.1/1/10秒)不变；不把幅度模Allan误当复Allan。
300秒只是本次配置有效期上限，不声称实测可稳定300秒。epoch局限于这次受控连续采集会话，不授权任意后续目标使用。

unit `t510-stage36-background-standard-20260912.service`，invocation `84d4d73fe93544948a6740f953fa9a0c`。
源及提交 `/home/astrolab/.cache/t510/stage36-background-standard-20260912/`。
证据 `/var/lib/t510/measurements/stage36-background-standard-20260912-queue/`。
成功发布URL `/static/background-standard.html`，只有完成和SHA通过后发布，浏览器验收通过后添加主页面入口。
失败停止并保留证据，不替换旧模板、不重采。提交记录不是完成声明。

## 首次预检失败与新编号提交

首次队列在任何采集前因ADC0锁存错误1073743200停止，其余7路零；安全退出无错误。没有正式数据，不声称故障一定由插拔产生。
保持独立50Ω、TG关闭后调用既有journaled clear_once一次：before1073743200，立即及5秒后八路全零，ok=true。完整日志保留。
新队列 `stage36-background-standard-20260912-r2`，源/脚本与提交同名cache目录，额外把首次probe与清除基线纳入evidence；完整采集→分析→发布→浏览器队列不变。
不复用失败队列目录，不在采集中清错误。成功发布页面路径仍为background-standard.html。

## R2完成核查

2026-09-12 20:06:47完整unit成功退出。采集completed、verification_status=PASS、error=null，正式丢包/序号/sample0/接口错误均零。
全28对4096bin后60秒100ms扣除产品已保存为60个一秒文件，每文件含10个100ms桶；模板、产品、web及队列manifest完整。恢复核验manifest与其中JSON/NPZ SHA全部通过。
科学带bin3072–3328归一化残差模总体中位数0.132393%→0.100462%，p90为4.432146%→0.417806%；28对中23对的频带中位数降低，5对未降低。仅说明该参考窗口的偏置指标，不作为Allan或弱信号灵敏度改善。
结束streaming=false、八路DAC关闭。网页自动发布及Chromium验收PASS：28对、600个原生点公式、图例联动、ADC切换、窄屏布局；截图已读取检查。
页面 http://192.168.100.162:8036/static/background-standard.html ，主报告入口已更新并同步本地源码。
标准分析入口默认auto的实现和本次新参考接线验收完成；该模板的300秒上限不授权未来采集继续使用，后续新epoch/新接线须新参考或重新验证。
