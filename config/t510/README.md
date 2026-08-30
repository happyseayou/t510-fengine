# T510 current release catalog

`config.example.json` is the finalized catalog for the Stage 35 hardware
baseline: the verified Stage 34 4096-channel, 8-tap F-engine. Its bitstream
SHA-256 is
`c21d93f5ea71e9ac17a4448cff138a8faaf9c7347d879be919b680d196b8a5be`, and
its fixed ADC/DAC MTS targets are `416/112`. The current release is installed
directly below `/opt/t510-agent/current`; versioned release directories are no
longer retained. Replacing these values with a zero
SHA, `-1` targets, or null campaign proof returns the catalog to its deliberate
fail-closed sentinel state; the Board Agent and publish script reject it.

CONFIGURE accepts an explicit `clock_reference`. Use `onboard_tcxo` for the
Stage 35 single-board noise study with external 10 MHz and PPS disconnected;
use `external_10mhz` when a common external reference is intentionally present.
The two request examples select `onboard_tcxo` explicitly. Omitting the field
keeps the historical `external_10mhz` default for API compatibility.

For a new candidate, run both required board campaigns and then finalize the
catalog again:

```bash
python3 scripts/pynq_t510_mts_campaign.py --phase discovery \
  --output build/board/latest/evidence/mts_discovery.json
python3 scripts/pynq_t510_mts_campaign.py --phase fixed \
  --discovery-json build/board/latest/evidence/mts_discovery.json \
  --output build/board/latest/evidence/mts_fixed.json
python3 scripts/t510_finalize_catalog.py \
  --discovery-json build/board/latest/evidence/mts_discovery.json \
  --fixed-json build/board/latest/evidence/mts_fixed.json
```

The finalizer requires 20 RFDC-reset, 10 overlay-reload, and 10 LMK-reload
cycles in each phase, all 40 passing. It derives ADC/DAC targets from the
discovery maxima plus 20/16, records a hash of both reports, and writes the
bitstream SHA into this single catalog. Both reports carry that SHA, and the
finalizer rejects evidence captured with any other candidate bitstream. In
every fixed cycle all four tiles of each converter kind must report the same
final latency. The RFDC driver applies correction delay in one
decimation/interpolation-factor step, so a final latency on either side of
`Target_Latency` is accepted only within half one factor. Raw correction
offsets remain evidence but are not RF phase; phase repeatability is verified
by the separate RF loopback/TG gate. The retired targets 230/336 are explicitly
rejected.
