#!/usr/bin/env python3
"""Read-only stopped-board DSA and RFDC interrupt check for the TG experiment."""
import contextlib
import hashlib
import json
from pathlib import Path
import sys
import t510_stage36_tg_dsa_probe as dsa

if __name__ == '__main__':
    if sys.argv[1] != 'probe':
        raise ValueError('TG monitor permits probe only; no Reset/prepare with TG on')
    with contextlib.redirect_stdout(sys.stderr), dsa.base.hw._configure_hardware_guard(True):
        import xrfdc
        core = dsa.base.hw._controller(dsa.base.hw._load_saved_configure_request()).require_core()
        result = dsa.snapshot(core)
        dsa.check(result)
        if any(r['dsa']['Attenuation'] != 0 for r in result['rows'] if r['adc'] not in (0,2)):
            raise RuntimeError('unexpected other-channel DSA')
        for row in result['rows']:
            value = xrfdc._ffi.new('u32 *')
            core.rfdc.adc_tiles[row['tile']].blocks[row['block']]._call_function('GetIntrStatus', value)
            row['interrupt_status'] = int(value[0])
            row['adc_error_bits'] = int(value[0]) & 0xFCFF0FFF
        result.update(ok=True, helper_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    print(json.dumps(result))
