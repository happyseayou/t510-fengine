# stage 27d目前还是演示的阶段，当确认流量正常后，就要开始做生产力的收紧
# stage 27e-i TIME + SPEC， TIME预览波形，SPEC预览频谱

100MHz:
  有 PL decim2 alias 问题。
  raw 端点/带外分量被折叠进 122.88MHz。

200MHz:
  没有 PL decim2 alias。
  raw 端点/带外分量仍会直接出现在频谱边缘/低频端。
  SPEC_ONLY 200MHz 还有额外的 F-engine/output backpressure 问题。

# stage 27j TIME + SPEC， 加入PFB

# 预计stage 28开始生产力收紧，具体要求
## 1、去除所有的多余的模块，包括RTL和本地接收端
## 2、根据新的RTL顶层设计（现在还没有），收紧所有的接口，payload
## 3、根据新的X-engine设计，收紧所有的接口，payload
## 4、板卡端模式定义：TIME only， TIME+SPEC， SPEC only
## 5、rust接收端模式定义：监控预览（常驻，根据板卡模式，显示不同的内容），X-engine和Beamformer模式（暂不实现）
## 6、负载设计，不同模式下，如果存在多个板块，多个接受端，SPEC负载按照频率来分配，那么TIME呢？