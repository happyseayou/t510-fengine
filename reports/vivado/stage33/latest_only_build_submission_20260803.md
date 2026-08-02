# Stage 33 latest-only cleaned build submission

## Status

`FULL_CHAIN_SUBMITTED / RESULT_NOT_POLLED`

This record covers the cleaned current `demo-ant.xpr`. The final action of the
cleanup turn submits `synth_1`, queues `impl_1`, and requests
`write_bitstream`. Per the established long-task rule, no progress or result is
polled after the submission is accepted.

## Project identity

- Project: `/home/astrolab/demo-ant/demo-ant.xpr`
- Name: `demo-ant`
- Part: `xczu47dr-ffve1156-2-i`
- Top: `t510_fengine_board_top`
- Core version: `0x00010033`
- Design defines: none
- Simulation defines: `T510_SIM_FFT_MODEL` only
- Current XPR source set: 23 RTL files, 18 project simulation files, one RFDC
  BD, CMAC XCI, and single-lane real-time XFFT XCI

No second Vivado project was created.

## Submission command

The attached Vivado 2022.2 GUI session receives this dependency chain:

```tcl
reset_run synth_1
launch_runs synth_1 -jobs 8
launch_runs impl_1 -to_step write_bitstream -jobs 8
```

The `impl_1` request is dependent on the newly reset and launched `synth_1`, so
the queued request covers synthesis, implementation, and full bitstream output.

## Submission gates

- Python: PASS, 84 tests
- Board Agent Rust: PASS, 7 tests
- Time receiver Rust: PASS, 37 tests
- Web math: PASS
- Complete current XSim batch: PASS, 18 testbenches
- Repository hygiene: PASS
- `git diff --check`: PASS
- Vivado top syntax: PASS
- `validate_bd_design`: PASS
- RFDC XCI/HWH contract verifier: PASS
- RFDC XCI SHA-256:
  `3bc3b81a2d73cd3b8e968e385804556cb203def6adc5ac3b3a09dbb58ede2908`
- RFDC HWH SHA-256:
  `b7706b3e7d62be147b1962487ff0144dcad2e2ea61d31fef27f31c65b69eaefd`
- Protected `for_me.md` SHA-256:
  `519b6c2fcc9ad1fbcc97a4867ddf73da0fbc5b3fb22374867dc81ee8140db859`

Static XDC lint reports the same 18 GT-pin `MISSING_IOSTANDARD` warnings seen
before this cleanup and no pin conflict. Final DRC and routed timing are not
claimed until the chain finishes.

## Deferred audit

On the next explicit continuation after Vivado finishes:

1. Check the two run results once.
2. Audit synthesis/implementation errors and critical warnings.
3. Require fully routed design, WNS/WHS at least zero, and passing DRC.
4. Export a new immutable Stage 33 build/report directory.
5. Verify artifact SHA and RFDC XCI/HWH again.
6. Do not promote `overlay/`, catalog, or `latest` to the cleaned output until
   the required physical-board MTS/RF/production gates bind to that SHA.
