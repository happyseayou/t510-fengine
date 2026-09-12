#!/usr/bin/env python3
"""Stopped ADC4/5 attenuation only; never reset, prepare, MTS or clear errors."""
import contextlib
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import t510_stage36_tg_dsa_probe as base

SETTINGS={'DSA_A':(0.,0.),'DSA_B':(10.,0.),'DSA_C':(0.,10.),'DSA_D':(10.,10.)}

def snapshot(core):
    import xrfdc
    value=base.snapshot(core)
    for row in value['rows']:
        ptr=xrfdc._ffi.new('u32 *')
        core.rfdc.adc_tiles[row['tile']].blocks[row['block']]._call_function('GetIntrStatus',ptr)
        row['adc_error_bits']=int(ptr[0])&0xFCFF0FFF
    return value

def validate(value):
    for row in value['rows']:
        i=row['adc'];d=row['dsa']
        if row['adc_error_bits']:raise RuntimeError('RFDC error present; no clearing permitted')
        if i not in (4,5) and d['Attenuation']!=(20 if i in (0,2) else 0):
            raise RuntimeError('non-target DSA mismatch')
        if i in (0,2) and d['DisableRTS']!=1:raise RuntimeError('ADC0/2 DSA control mismatch')
        if i in (4,5) and d['Attenuation'] not in (0,10):raise RuntimeError('unexpected ADC4/5 setting')

def apply(core,action,save):
    before=snapshot(core);save('before',snapshot=before);validate(before)
    for i,target in zip((4,5),SETTINGS[action]):
        block=core.rfdc.adc_tiles[i//2].blocks[i%2]
        value=dict(block.DSA);value.update(Attenuation=target,DisableRTS=1)
        block.DSA=value
        save('write',adc=i,value=value)
    after=snapshot(core);save('after',snapshot=after);validate(after)
    for i,row in enumerate(after['rows']):
        if i in (4,5):
            if row['dsa']['Attenuation']!=SETTINGS[action][i-4] or row['dsa']['DisableRTS']!=1:
                raise RuntimeError('DSA write readback mismatch')
        elif row['dsa']!=before['rows'][i]['dsa']:raise RuntimeError('non-target DSA changed')
    return after

def execute(action):
    if action not in ('probe',*SETTINGS):raise ValueError('unsupported DSA action')
    directory=Path(__file__).parent/'dsa45-journals';directory.mkdir(exist_ok=True)
    path=directory/f'{time.time_ns()}-{action}.jsonl'
    def save(boundary,**fields):
        with path.open('a') as f:
            f.write(json.dumps(dict(boundary=boundary,unix_ns=time.time_ns(),**fields))+'\n');f.flush();os.fsync(f.fileno())
    with base.base.hw._configure_hardware_guard(True):
        core=base.base.hw._controller(base.base.hw._load_saved_configure_request()).require_core()
        try:
            if action=='probe':value=snapshot(core);validate(value);save('probe',snapshot=value)
            else:value=apply(core,action,save)
        except Exception as exc:
            save('failed',error=str(exc));raise
    return dict(value,ok=True,action=action,board_journal_path=str(path),helper_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())

if __name__=='__main__':
    with contextlib.redirect_stdout(sys.stderr):result=execute(sys.argv[1])
    print(json.dumps(result))
