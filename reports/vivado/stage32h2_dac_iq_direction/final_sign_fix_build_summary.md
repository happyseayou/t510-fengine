# Stage 32h2 DAC physical-sign fix build summary

## Status

`REJECTED_BY_PHYSICAL_TEST`

## Build identity

- Completed: `2026-08-02 01:32:20 +08:00`.
- Vivado: `2022.2`.
- Device: `xczu47dr-ffve1156-2-i`.
- Top: `t510_fengine_board_top`.
- `CORE_VERSION`: `0x00010032`.
- Chain: `synth_1 -> impl_1 -> write_bitstream`.
- Design state: Fully Routed.

## Timing and implementation gates

- WNS/TNS: `+0.181 ns / 0.000 ns`.
- WHS/THS: `+0.010 ns / 0.000 ns`.
- Setup/hold failing endpoints: `0 / 0`.
- Routed DRC: `0 Error`; warning/advisory classes are unchanged design-quality
  items and contain no blocking violation.
- Methodology: warning/advisory only; no Error or Critical Warning violation.
- Bitgen: completed successfully.
- The single run-log Critical Warning is the existing `[Vivado 12-1790]`
  evaluation-license warning. It is not a DRC/Methodology violation or a new
  DDS-sign issue, but production licensing remains a separate release concern.

## Controlled hardware change

The valid eight-stream RFDC contract remains `Real analog output + Fine
I/Q-to-Real`, width 8 and interpolation 5. The only functional hardware change
from the first Stage 32h2 candidate is the DDS tone phase progression: a logical
positive RF baseband offset now generates the negative PL complex rotation
measured to produce the correct physical RF direction. Constant-phasor phase0
coordinates and the 128-bit AXIS word layout remain unchanged.

## Exported artifacts

| Artifact | SHA256 |
|---|---|
| `demo-ant.runs/impl_1/t510_fengine_board_top.bit` | `d4950668aeb42ba1145e1504018934dde838b8a422126dde7178afa9e5575cb0` |
| `overlay/t510_fengine.bit` | `d4950668aeb42ba1145e1504018934dde838b8a422126dde7178afa9e5575cb0` |
| `overlay/t510_fengine.hwh` | `bdd680b1308221edb9dc9956800ba83c8e6e672b012afcd66ee251b2030c72cb` |
| `overlay/t510_fengine.tcl` | `0890fab897d4cd7e6e9b84f1aeefa1be0f9c7c4161f72a2ed87f34a2bb1826f5` |
| `overlay/t510_fengine.manifest.txt` | `e7b8be99a88b41a4412f60b2600bf854a2c556b35db5809998c8a3bf5fd10b4b` |

The run bit and overlay bit are byte-identical. The exported HWH contains all
eight DAC AXIS interfaces and reports all eight `DAC_Data_Type*=0` and
`DAC_Mixer_Mode*=0` values.

## Physical rejection

After deployment, this bit made requested 120 MHz appear at 220 MHz and
requested 220 MHz appear at 120 MHz in 320-MS/s raw operation.  The global
phase subtraction hypothesis is therefore false.  The route/timing/DRC facts
above remain valid implementation evidence, but this artifact is not a release
candidate and must not be published.

The accepted Stage 32h2 artifact is the earlier standard-positive DDS bit with
SHA256 `47117c9e656cfd8345125ef0130eb91a5ec0868cef59931b40b957da29f31234`.

## Disposition

Do not publish or reload this artifact.  It is retained only to preserve the
failed-hypothesis build record.
