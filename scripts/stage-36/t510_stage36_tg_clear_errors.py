#!/usr/bin/env python3
"""One journaled pre-capture clear of historical RFDC interrupt latches."""
import contextlib
import json
import os
from pathlib import Path
import sys
import time
import t510_stage36_tg_dsa_probe as dsa
MASK=0xFCFF0FFF  # API-level ADC overvoltage/range/common-mode/data/FIFO plus decoder/datapath.

def main():
    if sys.argv[1] != 'clear_once':raise ValueError('requires explicit clear_once action')
    directory=Path(__file__).parent/'interrupt-journals';directory.mkdir(exist_ok=True)
    path=directory/f'clear-{time.time_ns()}.jsonl'
    rows=[]
    def save(label,**fields):
        row=dict(label=label,unix_ns=time.time_ns(),**fields)
        with path.open('a') as f:f.write(json.dumps(row)+'\n');f.flush();os.fsync(f.fileno())
        rows.append(row)
    with dsa.base.hw._configure_hardware_guard(True):
        import xrfdc
        core=dsa.base.hw._controller(dsa.base.hw._load_saved_configure_request()).require_core()
        def read():
            snap=dsa.snapshot(core);dsa.check(snap)
            for row in snap['rows']:
                value=xrfdc._ffi.new('u32 *')
                core.rfdc.adc_tiles[row['tile']].blocks[row['block']]._call_function('GetIntrStatus',value)
                row['interrupt_status']=int(value[0]);row['adc_error_bits']=int(value[0])&MASK
            return snap
        try:
            before=read();save('before',snapshot=before)
            for r in before['rows']:
                if r['adc_error_bits']:
                    core.rfdc.adc_tiles[r['tile']].blocks[r['block']]._call_function('IntrClr',r['adc_error_bits'])
                    save('cleared',adc=r['adc'],mask=r['adc_error_bits'])
            after=read();save('immediate_after',snapshot=after)
            time.sleep(5)
            final=read();save('five_seconds_after',snapshot=final)
            ok=not any(r['adc_error_bits'] for snap in (after,final) for r in snap['rows'])
            return dict(ok=ok,board_journal_path=str(path),rows=rows)
        except Exception as exc:
            save('failed',error=str(exc));raise
        finally:
            core.stop();core.set_dac_enable_mask(0)

if __name__=='__main__':
    with contextlib.redirect_stdout(sys.stderr):result=main()
    print(json.dumps(result));sys.exit(0 if result['ok'] else 1)
