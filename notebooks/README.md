# T510 Jupyter Entry Points

## Stage 27h Production

Use one notebook for the current production workflow:

1. `15_stage27h_time_spec_fft_fullrate_control.ipynb`

This is the Stage 27h Jupyter control and preview surface for:

- TIME/SPEC science stream configuration and status.
- Receiver IP/port/MAC, mode, bandwidth, center frequency, and 8-lane DAC-ADC loopback control.
- DAC tone frequency, amplitude, and per-lane phase control.
- RF-reconstructed waveform preview from real RFDC preview IQ.
- FFT-only production spectrum preview.

Stage 27h production uses TIME ports `4300..4307`, SPEC ports `4308..4323`,
and the `FENGINE_IQ16` FFT-only SPEC contract: `4096` channels, `16` blocks,
`256` channels/block, `1` spectrum-time, `8` inputs, `8192B` payload.

## Archived Bring-Up Notebooks

Older notebooks remain in the repository only as bring-up references for clock,
RFDC, UDP dry-run, DAC/ADC loopback, and historical debug checks. They are not
Stage 27h production pass criteria. `14_stage27g_time_spec_fengine_control.ipynb`
is retained as the Stage 27g `/32` cadence reference, and
`13_astronomer_rf_observation_console.ipynb` remains an archived rich
observation/debug console.
