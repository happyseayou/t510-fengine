# Stage 32h2 RFDC DAC contract hypothesis correction

## Status

`HYPOTHESIS_REJECTED`

The first interpretation of `DAC_Data_Type=0` as a real-only PL interface was
incorrect. In this RFDC configuration the field selects a real analog DAC
output, while `DAC_Mixer_Mode=0` selects I/Q-to-Real and the 128-bit stream
carries four interleaved complex samples.

The valid eight-path contract is:

- `DAC_Data_Type00/02/10/12/20/22/30/32 = 0` (Real analog output);
- `DAC_Mixer_Type* = 2` (Fine);
- `DAC_Mixer_Mode* = 0` (I/Q-to-Real);
- `DAC_Data_Width* = 8` (eight 16-bit words, four complex samples);
- `DAC_Interpolation_Mode* = 5`;
- PL word order `I0,Q0,I1,Q1,I2,Q2,I3,Q3`, least-significant word first.

Changing Data Type to 1 paired physical DACs as analog I/Q outputs and removed
the `s02/s12/s22/s32` AXIS ports. Synthesis then failed at the unchanged top
level. The experiment has been fully reverted and all eight ports and nets are
present again.

This correction resolves the build-topology error only. It does not explain or
close the physical DAC mirror/comb issue.
