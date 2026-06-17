# Stage 18: LMK/RFDC MTS Recovery + Stability Gate Closure

## Summary

Stage 18 targets the blockers exposed by Stage 17 before QSFP live science data can be trusted:

- LMK full lock must be observable as `pll1_lock=1` and `pll2_lock=1`.
- RFDC deterministic sync must use real MTS/SYSREF capability, not the older immediate mixer update flow.
- Preview and TIME/SPEC dry-run UDP payload witness must both satisfy the strict data-quality gate: phase p-p `<= 3 deg`, amplitude p-p `<= 5%`, no clipping/large-event pollution.

Stage 18 does not connect QSFP live and does not move the DAC0->ADC0 cable.

## Implementation

- Added `scripts/pynq_lmk_rfdc_mts_recovery_check.py`.
  - Reads LMK GPIO, lock bits and optional LMK register dump.
  - Reads PYNQ/xrfdc package path, RFDC driver status and `libxrfdc.so` symbols.
  - Can create a timestamped backup of the current `xrfdc` package and `libxrfdc.so`, with a rollback script.
  - Can optionally run a real MTS probe when LMK full lock is present.
  - Writes JSON evidence under `artifacts/`.
- Extended `python/t510_clock.py`.
  - Adds LMK register dump, GPIO readback, profile ID and SYSREF pulse helper.
- Extended `python/t510_fengine.py`.
  - Adds `read_lmk_status()`, `read_rfdc_driver_status()` and `apply_mts_locked_observation_config(...)`.
  - Adds a minimal runtime cffi shim for existing `libxrfdc.so` MTS symbols when PYNQ's Python wrapper does not expose them.
  - The strict init path now treats LMK lock or MTS failure as a hard prerequisite failure.
- Updated `notebooks/13_astronomer_rf_observation_console.ipynb`.
  - Init/Apply now uses the MTS-locked observation config.
  - Advanced status shows LMK lock, RFDC MTS capability, MTS latency and preview/payload gate.

## Board Probe Notes

Initial non-mutating board inspection found:

- After reboot the management Ethernet address changed to `192.168.100.237`; after applying the stable management MAC, DHCP returned the board to `192.168.100.117`.
- `eth0` current MAC is `e6:39:8e:4c:37:0b`; Linux reads it from `/proc/device-tree/axi/ethernet@ff0e0000/local-mac-address`.
- `/proc/cmdline` does not provide a MAC address, `fw_printenv` is not installed, and `/etc/network/interfaces.d/eth0` currently uses DHCP without a fixed `hwaddress`.
- Because the device-tree MAC appears to change between boots, DHCP sees a new client and the management IP is not stable. This is a QSFP/preflight reproducibility risk; fix by adding a stable board MAC in U-Boot/device tree or by setting `hwaddress ether ...` before DHCP in the ifupdown config.
- Added `scripts/pynq_fix_management_mac.sh` as a non-disruptive board-side helper. It derives a stable local MAC from `/etc/machine-id` unless `--mac` is supplied; for the current board that default is `02:51:10:23:dc:28`. The helper backs up `/etc/network/interfaces.d/eth0` under `/etc/network/stage18-backups/` and does not cycle the interface unless `--apply-now` is explicitly given. It has been executed on the board with `--apply-now`; current `eth0` is `02:51:10:23:dc:28` with DHCP address `192.168.100.117`.
- PYNQ version: `3.0.1`.
- `xrfdc` Python package path: `/usr/local/share/pynq-venv/lib/python3.10/site-packages/xrfdc/__init__.py`.
- PYNQ Python wrapper exposes RFDC block/tile APIs but not top-level MTS methods.
- The installed `libxrfdc.so` does expose:
  - `XRFdc_MTS_Sysref_Config`
  - `XRFdc_MultiConverter_Init`
  - `XRFdc_MultiConverter_Sync`
  - `XRFdc_GetMTSEnable`
- The runtime cffi extension can load the missing MTS struct/function prototypes without replacing the system library.

## Recovery Commands

Board audit:

```bash
cd /home/xilinx/t510_fengine_bringup
source /etc/profile.d/xrt_setup.sh
sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_lmk_rfdc_mts_recovery_check.py --dump-lmk --dump-rfdc-api --timeout 2.0
```

CH0 tile0-only MTS probe:

```bash
sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_lmk_rfdc_mts_recovery_check.py --probe-mts --adc-tiles 0x1 --dac-tiles 0x1 --timeout 2.0
```

Management MAC stabilization, for the next reboot without dropping the current SSH/Jupyter session:

```bash
sudo scripts/pynq_fix_management_mac.sh
```

Optional system backup before any system-level RFDC package work:

```bash
sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_lmk_rfdc_mts_recovery_check.py --dump-rfdc-api --backup-system --timeout 2.0
```

Strict stability gate after LMK/MTS prerequisites pass:

```bash
sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_rfdc_sysref_coherence_lock_check.py --center-mhz 100 --signals-mhz 119.2,130.24,130,100 --modes time,spec --samples 512 --frames 240 --strict-phase-pp-deg 3 --strict-amplitude-pp-percent 5 --timeout 2.0
```

## Pass Criteria

- `CORE_VERSION=0x0001000A`, unless a later RTL fix is explicitly required.
- LMK `pll1_lock=1` and `pll2_lock=1`.
- RFDC MTS API or runtime shim can run ADC/DAC MTS init/sync and report latency/status.
- ADC/DAC mixer event source is SYSREF.
- Preview phase p-p `<= 3 deg`, amplitude p-p `<= 5%`.
- TIME/SPEC payload phase p-p `<= 3 deg`, amplitude p-p `<= 5%`.
- `sample0_delta` is fixed or has a deterministic latency explanation.
- No clipping or large-event pollution.

## Current Gate

Latest board evidence at `192.168.100.117` after management MAC/IP recovery:

- LMK full lock: PASS (`pll1_lock=1`, `pll2_lock=1`).
- RFDC MTS shim availability: PASS.
- CH0 tile0-only MTS probe: PASS (`adc latency=1440`, `dac latency=1760`).
- Short CH0 TIME strict gate: FAIL, classified as `RFDC_ANALOG_CLOCK_PATH_UNSTABLE`.
  - Preview phase p-p: `312.76 deg`.
  - Payload phase p-p: `343.46 deg`.
  - Preview amplitude p-p: `57.74%`.
  - Payload amplitude p-p: `137.30%`.
  - TX source/header sample0 delta was fixed at `80`, so this run does not point to packet header sample0 drift as the primary failure.

Until the board audit and strict gate pass, QSFP live science data remains:

```text
BLOCK_QSFP_LIVE_DATA_QUALITY
```
