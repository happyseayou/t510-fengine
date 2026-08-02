# Stage 32h2 320-MS/s raw DAC sign diagnostic

## Status

`SUPERSEDED_BY_FRESH_CONFIGURE_DIAGNOSTIC`

## Setup

- RFDC/science mode: 320 MS/s SPEC_ONLY, center 170 MHz, half-band bypassed.
- Physical path: DAC0 through a power splitter to ADC0 and ADC1 using different
  cable lengths.
- DDS amplitude: 25%.
- Receiver FFT: 4096 bins, 78.125 kHz/bin.

## Result

| Requested RF | Logical baseband | Expected bin | ADC0 peak | ADC1 peak |
|---|---:|---:|---:|---:|
| 120 MHz | -50 MHz | 3456 | 640 | 640 |
| 220 MHz | +50 MHz | 640 | 3456 | 3456 |

Bin 640 is +50 MHz and bin 3456 is -50 MHz. Both cable paths therefore prove
the same exact sign reversal. Because this test bypasses the 160-MS/s
half-band, the half-band is not the source of the mirror.

## Implementation consequence

The original implementation consequence below was wrong: this session was
used to infer that the PL must subtract `phase_step`.  A later direct RFDC raw
preview showed that the same standard-positive bit produces the correct signed
baseband after a complete fresh CONFIGURE, in both 160 and 320 modes.  The
subtraction bit was then physically rejected because it globally swapped
120/220 MHz.

Final implementation keeps `baseband=requested_rf-center` and generates
`I=cos(theta+n*step), Q=sin(theta+n*step)`.  This file remains as evidence of
the anomalous pre-reinitialization session, not as the current root-cause
conclusion.

## Safe final state

Both diagnostic runs executed STOP and disabled all DACs. The final board
status reported streaming false, DAC enable mask 0, flush clean, both LMK PLLs
locked, PPS recent and QSFP link up.
