# Stage 33 release catalog

`config.example.json` is intentionally fail-closed until a physical-board MTS
campaign has completed. Its zero SHA, `-1` targets, and null campaign proof are
sentinels; the Board Agent and Stage 33 publish script both reject them.

Run the two required board campaigns and then finalize the catalog:

```bash
python3 scripts/pynq_stage33_mts_campaign.py --phase discovery \
  --output reports/board/stage33_mts_discovery.json
python3 scripts/pynq_stage33_mts_campaign.py --phase fixed \
  --discovery-json reports/board/stage33_mts_discovery.json \
  --output reports/board/stage33_mts_fixed.json
python3 scripts/stage33_finalize_catalog.py \
  --discovery-json reports/board/stage33_mts_discovery.json \
  --fixed-json reports/board/stage33_mts_fixed.json
```

The finalizer requires 20 RFDC-reset, 10 overlay-reload, and 10 LMK-reload
cycles in each phase, all 40 passing. It derives ADC/DAC targets from the
discovery maxima plus 20/16, records a hash of both reports, and writes the
bitstream SHA into this single catalog. Both reports carry that SHA, and the
finalizer rejects evidence captured with any other candidate bitstream. The
fixed campaign must also return identical four-tile latency/offset vectors for
ADC and DAC across all 40 cycles. The retired targets 230/336 are explicitly
rejected.
