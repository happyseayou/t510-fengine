# Stage 27h: TIME_SPEC 100MHz FFT-only Full-rate SPEC Convergence

## Goal

Stage 27h replaces the Stage 27g `/32` cadence SPEC path with an FFT-only,
full-rate SPEC production path for `TIME_SPEC 100MHz`.

Production pass requires board plus host:

- Vivado route complete, timing met, bitstream/export produced.
- Board loads `CORE_VERSION=0x00010026`.
- Board `TIME_SPEC 100MHz` produces TIME near `480kpps` and SPEC near `480kpps`.
- Combined T510 UDP payload is at least `63Gbps`.
- Host Rust receiver validates `24` flows with no drops/gaps while waveform and spectrum previews update.

## Production Contract

- TIME ports: `4300..4307`.
- SPEC ports: `4308..4323`.
- Host flow count: `24` (`8` TIME + `16` SPEC).
- Product ID: `FENGINE_IQ16` (`0xf101`).
- SPEC payload: `4096` channels, `16` blocks, `256` channels/block,
  `1` spectrum-time, `8` inputs, IQ16, `8192B` payload plus `128B` T510 header.
- FFT-only identification: `spec_taps=0` and `spec_status_flags[8]=1`.
- No PFB filter/delay and no SPEC decimation/thinning are acceptable for 27h pass.

## Implemented Locally

- RTL production SPEC path is FFT-only:
  - `rtl/pfb_channelizer.sv` keeps the compatibility shell but removes PFB filtering when `taps=0`.
  - `rtl/t510_fengine_top.sv` removes the production `science_stream_decimator` from SPEC.
  - `rtl/spec_udp_cmac512.sv` uses generic block metadata for `nchan / chan_count`.
  - `CORE_VERSION` is bumped to `0x00010026`.
- Python/PYNQ:
  - `configure_science_27h()` configures `16 x 256ch x 1 time` SPEC routes and rejects `TIME_SPEC 200MHz`.
  - `run_stage27h_time_spec_fft_fullrate_validation()` gates `CORE_VERSION`, FFT-only flags, route coverage, drop/error counters, and packet-rate-derived payload rate.
  - `scripts/pynq_stage27h_time_spec_fft_fullrate.py` is the board entry.
- Rust host/Web:
  - Default receiver is Stage 27h: `24` flows, `8` TIME, `16` SPEC, `fanout=port`, `initial-bandwidth=100`.
  - `--spec-layout 27h|27g|auto` is available; default `27h` rejects legacy `64x4` SPEC packets.
  - Web display shows TIME waveform, FFT-only F-engine status, spectrum, phase, power, waterfall, active flows/workers, drops/gaps, and preview Hz.
- Jupyter:
  - `notebooks/15_stage27h_time_spec_fft_fullrate_control.ipynb` is the production control + preview notebook.
  - Notebook 14 remains archived as the Stage 27g reference.
- Publishing:
  - Stage 27h publishers sync only overlay, `python/`, 27h board validator, notebook 15, and README.

## Local Validation

Run from repo root:

```bash
python3 -m py_compile python/t510_fengine.py scripts/pynq_stage27h_time_spec_fft_fullrate.py scripts/host_stage27h_rust_rx_validate.py scripts/host_stage27e_rust_rx_validate.py
python3 -m json.tool notebooks/15_stage27h_time_spec_fft_fullrate_control.ipynb >/dev/null
bash -n scripts/pynq_publish_stage27h.sh scripts/pynq_publish_jupyter_instrument.sh scripts/host_stage27h_rx_fanout_tune.sh
cargo test -q --manifest-path rust/t510_time_rx/Cargo.toml
cargo build --release --manifest-path rust/t510_time_rx/Cargo.toml
```

Targeted XSim to run before hardware export:

```bash
./scripts/run_xsim_batch.sh tb_pfb_channelizer tb_spectral_packetizer tb_spec_udp_cmac512 tb_time_udp_cmac512 tb_tx_route_selector tb_feng_ctrl_axi tb_t510_fengine_top_smoke
```

Status on 2026-06-28: all commands above passed locally. Targeted XSim passed for
FFT-only channelizer, generic spectral packetizer block metadata, 16-route SPEC
UDP, TIME UDP, route selector, control AXI, and top TIME/SPEC smoke.

## Hardware Plan

1. Export Stage 27h bitstream with `scripts/stage27h_time_spec_100mhz_fft_fullrate_bit_export_batch.tcl`.
2. Publish with `PYNQ_TARGET=xilinx@192.168.100.117 scripts/pynq_publish_stage27h.sh`.
3. Run board gate:

```bash
cd /home/xilinx/t510_fengine_bringup
source /etc/profile.d/xrt_setup.sh
printf "%s\n" "xilinx" | sudo -S -p "" -E /usr/local/share/pynq-venv/bin/python3 \
  scripts/pynq_stage27h_time_spec_fft_fullrate.py --matrix converge
```

4. Start host receiver:

```bash
sudo rust/t510_time_rx/target/release/t510_time_rx \
  --backend fanout --worker-count 32 --fanout-mode port --fanout-group 0x278 \
  --pin-workers off --interface ens2f0np0 --dst-port-base 4300 --src-port-base 4000 \
  --flow-count 24 --time-flow-count 8 --spec-flow-count 16 --spec-layout 27h \
  --web 0.0.0.0:8089 --initial-bandwidth-mhz 100 --ring-mb 2048 --batch-size 8192
```

5. Run host gate:

```bash
scripts/host_stage27h_rust_rx_validate.py --seconds 10
```

Save board and host JSON under `reports/board/` and update this report with
timing/utilization/bit SHA plus the actual board/host classifications.
