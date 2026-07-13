# T510 Stage 29 F-engine Production Release

Stage 29 is the production software surface for the frozen T510 F-engine hardware baseline.

## Frozen hardware contract

- Target: `xczu47dr-ffve1156-2-i`
- `CORE_VERSION=0x00010030`
- Overlay bitstream SHA256: `7486a55b6f7e50e5875474e7d85299b107e9384cfff454316f64f2d3d7e9800d`
- TIME UDP ports: `4300..4307`
- SPEC UDP ports: `4308..4323`
- SPEC: `FENGINE_IQ16`, 4096 channels, `16 x 256 x 1`, 8 inputs, 8192-byte payload, 4-tap PFB
- Production synchronization: external 10 MHz plus external PPS

Stage 29 does not change RTL, Vivado IP, constraints, overlay files, UDP headers, payload layout, or Rust preview binary protocols.

## Supported production profiles

| Bandwidth | TIME_ONLY | SPEC_ONLY | TIME_SPEC |
| --- | --- | --- | --- |
| 100 MHz | supported | supported | supported |
| 200 MHz | supported | supported | rejected: exceeds 100GbE capacity |

The strict Python API is exported from `python.stage29`: `Stage29Config`, `Stage29Mode`, `FlowDestination`, `DacChannelConfig`, and `Stage29Controller`. `Stage29Config.board_id` programs the 16-bit identity carried by every T510 packet; multi-board deployments must assign each board a unique ID, source IP, and source MAC. TIME has eight independently addressed endpoints and SPEC has sixteen. The CMAC source IP/MAC are configurable once per board, while every endpoint has an independent source port and destination tuple; defaults remain board ID `0`, source `10.0.1.1` / `02:00:00:00:00:01`, with ports `4000..4023`. All eight DAC lanes retain independent in-band frequency, amplitude, phase, and enable controls. Low-level historical `T510FEngine` methods remain available for compatibility, while production callers use `configure_science_29()` and `run_stage29_validation()`.

The Rust Web preview is a seven-widget GridStack workspace: TIME, SPEC amplitude, phase, power, waterfall and phasor views, plus display-only controls. Apache ECharts 6.1.0 is packaged locally; interactive plots keep refreshing while restoring stable hover readouts, amplitude/power support frequency zoom and reset, and amplitude is displayed as `20 log10(max(|X|, 1 code))`. The waterfall uses a fixed, non-interactive 1 Hz RF/time grid, while phasor defaults to the relative reference-channel basis. GridStack handles drag, resize, snap, responsive compaction and browser-local layout persistence. The receiver remains permanently sized for all 24 production flows (`4300..4323`), while `output_mode` selects the active TIME/SPEC health contract. Hardware control remains exclusively in PYNQ/Jupyter.

## Production entrypoints

- Jupyter: `notebooks/00_stage29_fengine_production_control.ipynb`
- Board gate: `scripts/stage29_board_validate.py`
- Host/Rust gate: `scripts/stage29_host_validate.py`
- Host RX tuning: `scripts/host_stage29_rx_tune.sh`
- PYNQ publish: `scripts/pynq_publish_stage29.sh`
- Signal-path audit: `scripts/pynq_stage29_signal_audit.py`
- QSFP preflight: `scripts/pynq_qsfp_udp_preflight_check.py`
- Packet inspection: `scripts/check_t510_packet.py`

Example board gates, each performing a fresh bitstream download:

```bash
sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/stage29_board_validate.py --board-id 0 --bandwidth-mhz 100 --mode time_only
sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/stage29_board_validate.py --board-id 0 --bandwidth-mhz 100 --mode spec_only
sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/stage29_board_validate.py --board-id 0 --bandwidth-mhz 100 --mode time_spec
sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/stage29_board_validate.py --board-id 0 --bandwidth-mhz 200 --mode time_only
sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/stage29_board_validate.py --board-id 0 --bandwidth-mhz 200 --mode spec_only
```

Tune the host and run the matching 60-second Rust gate:

```bash
sudo scripts/host_stage29_rx_tune.sh --mode time_spec ens2f0np0
python3 scripts/stage29_host_validate.py --bandwidth-mhz 100 --mode time_spec --seconds 60
```

## Build and regression tools

- Project setup: `scripts/setup_project.tcl`
- Overlay export: `scripts/export_overlay.tcl`
- XFFT IP creation: `scripts/create_fengine_xfft_ip.tcl`
- XSim: `scripts/run_xsim_batch.sh` or `scripts/run_sim.tcl`
- Vivado message policy: `scripts/vivado_msg_policy.tcl`
- AA100 coefficient check: `scripts/stage29_verify_aa100_coeffs.py`

Historical implementation and hardware acceptance evidence remains under `reports/`. X-engine, beamformer, switch/DGX integration, payload changes, and `200MHz TIME_SPEC` are outside Stage 29.
