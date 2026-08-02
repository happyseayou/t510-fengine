# Stage 32h2 DAC I/Q direction first-iteration prebuild verification

> This document correctly records the first RTL-only offline gate. Physical
> loopback later found unresolved offset-dependent DAC images, so the gate is
> necessary evidence but is not sufficient for release.

## Scope

The PL DDS convention changes from `I=sin(theta), Q=cos(theta)` to the standard
positive complex sequence `I=cos(theta), Q=sin(theta)`. In this first iteration,
RFDC, LMK, MTS, PFB,
UDP, AXIS packing and `CORE_VERSION=0x00010032` remain frozen.

## RTL contract proved by XSim

- `phase0=0`: positive I, Q approximately zero.
- `phase0=90 degrees`: I approximately zero, positive Q.
- `+Fs/4`: `(+I, +Q, -I, -Q)` positive rotation in one four-sample beat.
- `-Fs/4`: `(+I, -Q, -I, +Q)` negative rotation.
- All eight DAC channels restart in phase on a shared epoch.
- Mixed enable mask gates only disabled channels; all AXIS `tvalid` behavior is unchanged.
- Packing stays `{Q3,I3,Q2,I2,Q1,I1,Q0,I0}`.

## Regression result

Run date: 2026-08-01.

| Gate | Result |
|---|---|
| Target `tb_t510_dac_loopback_source` | PASS |
| Full `scripts/run_xsim_batch.sh` (31 tops) | PASS |
| Python unittest discovery (64 tests) | PASS |
| Receiver Rust (7 lib + 29 binary) | PASS |
| Board Agent Rust (5 tests) | PASS |
| Stage 29 Web math | PASS |
| `git diff --check` | PASS |

XSim logs remain in the local `.xsim_batch/` work directory. The build has not
yet been launched and no modified bitstream has been loaded on hardware.

## Source hashes

| File | SHA256 |
|---|---|
| `rtl/t510_dac_loopback_source.sv` | `bac92e0d322510b2bc592a7c7092460f3ab470bb713860d01fb87322d64dd31e` |
| `sim/tb_t510_dac_loopback_source.sv` | `9e1fe8280a66096e563166c45a7210c81c55ff942280f97f29ec00e286cd011e` |
| `tests/test_stage32h2_dac_iq_direction.py` | `9973296306feb97418320da9f3700f866bb3ac2898ca1893245020df533ce7fc` |
| `tcl/stage32h2_dac_iq_direction_build_chain.tcl` | `f416373f7c4d77427ca13272477a7c4a54b69f4471212eb2883c8b9c8c96b417` |
