# T510 F-engine Jupyter entry

The only supported notebook is `00_t510_fengine_control.ipynb`.

It exposes the five production profiles, per-port TIME/SPEC receiver tables, eight-lane live DAC frequency/amplitude/phase control, mode-selective waveform/spectrum previews, board/PFB/XFFT/AA status, and Rust receiver status.

Endpoint IDs, source identity/ports, flow counts, PFB parameters, input mask, and external-clock/PPS discipline are fixed by `python.t510_control` and are not notebook controls. `Apply + Start` always performs a fresh bitstream download. The 60-second production gate remains a release CLI operation and is intentionally not part of the daily notebook UI.
