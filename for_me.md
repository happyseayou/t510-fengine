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

# stage 28 推进200MHz频宽的全速率的 TIME_only / SPEC_only 模式
在保持100MHz模式都正常的情况下，推进200MHz模式的TIME_only / SPEC_only模式，解决现有的200MHz模式下的F-engine/output backpressure问题。
注意每次改完后都要在100MHz模式下验证（TIME_SPEC），确保没有引入新的问题。
要用vivado的mcp，等待使用阶梯式等待


# 预计stage 29开始生产力，具体要求
F-engine生产力


# stage 30
PYNQ上使用API模式

# stage 31
多板同步准备，协同API

# stage 32
修改时钟策略，改为10M的倍数，320MHz


# stage 33
原始采样率太低了，这样第一Nyquist区间内的射频输入只能到800 MHz。使用的3840MSps的采样率，DDC+12倍下抽样，这样射频输入可以到1.92GHz

# stage 33a
杂散相关的调研

# stage 34
把pfb提高到8-tap，性能评估（杂散，rfi抑制，灵敏度）

stage 34d，Allan 负责判断系统稳定时间尺度，互相关负责判断科学上是否可用。
	​

# stage 35
科学评测

# stage 36
多板同步，把stage 32i搞过来


# 后续规划，忽略
规划：
限制adu数值到正负8192，预留一些给突发的rfi
扫一遍bandpass