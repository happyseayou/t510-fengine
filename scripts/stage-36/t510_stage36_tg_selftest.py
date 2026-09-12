#!/usr/bin/env python3
import json
from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace
from unittest.mock import Mock, patch
import numpy as np
import t510_stage36_tg_queue as q
from t510_stage36_tg_analyze import raw_headroom, summarize

p=q.plan('test');assert [x['duration_seconds'] for x in p]==[10,60]
assert 1 <= len(q.science.FOCUS_BINS) <= 32
assert len(set(q.science.FOCUS_BINS)) == len(q.science.FOCUS_BINS)
assert {3200,3201,3202,3073,3182,3328} <= set(q.science.FOCUS_BINS)
runner=q.TGQueue.__new__(q.TGQueue);runner.context={'rf_inputs':'TG to ADC0/2','dsa_db_by_adc':[20,0,20,0,0,0,0,0],'tg_on_operator_confirmed':True,'tg_requested_level_dbm':-20}
request={'metadata':{'physical_input':'old','interpretation':'old'}}
with patch.object(q.abc.ABC,'receiver',return_value={}):runner.receiver('/api/measure/crosscorrelation',method='POST',body=request)
assert request['metadata']['physical_input']=='TG to ADC0/2' and 'known_common' in request['metadata']['interpretation']
assert all(isinstance(v,str) for v in request['metadata'].values())
assert json.loads(request['metadata']['dsa_db_by_adc'])==runner.context['dsa_db_by_adc']
assert json.loads(request['metadata']['tg_on_operator_confirmed']) is True
for endpoint in ('/api/v2/configure','/api/v2/clock/diagnostic/restore'):
    try: runner.board(endpoint,method='POST')
    except RuntimeError: pass
    else: raise AssertionError('TG-on configuration permitted')
runner.args=SimpleNamespace(measurement_root=Path('/unused'));runner.evidence=Path('/unused');runner.probe=Mock();runner.event=Mock()
with patch.object(q.abc.ABC,'run_phase'),patch.object(q.abc.fullband,'verify',return_value={'status':'PASS'}),patch.object(q.science.base,'write_json_new'),patch.object(q,'summarize',return_value={'source_present':False}):
    try: runner.run_phase(p[0])
    except RuntimeError: pass
    else: raise AssertionError('missing source gate accepted')
runner.event.assert_not_called()
with tempfile.TemporaryDirectory() as tmp:
    root=Path(tmp);pcap=root/'test.pcap'
    with pcap.open('wb') as f:
        f.write(b'\xd4\xc3\xb2\xa1'+bytes(20))
        for g in range(32):
            for b in range(16):
                frame=bytearray(42);frame[14]=0x45;struct.pack_into('!H',frame,36,4308+b)
                words=[0]*16;words[0]=0x54353130<<32;words[4]=g*4096;words[5]=g*16+b;words[9]=b<<16
                frame+=struct.pack('<16Q',*words)+np.full(4096,100,dtype='<i2').tobytes()
                f.write(struct.pack('<4I',0,0,len(frame),len(frame)));f.write(frame)
    x=raw_headroom(pcap);assert x['passed'] and x['complete_frames']==32 and x['max_abs_iq_count_by_adc']==[100]*8
    with pcap.open('r+b') as f:f.seek(24+16+42+128);f.write(struct.pack('<h',32767))
    assert not raw_headroom(pcap)['passed']
    z=root/'xcorr.zarr'
    for n in ('n_valid','n_valid_100ms','mean_auto_power_count2','mean_cross_visibility_count2','mean_auto_power_count2_100ms','mean_cross_visibility_count2_100ms'):(z/n).mkdir(parents=True)
    for t in range(2):
        np.full(16,100,dtype='<u8').tofile(z/'n_valid'/f'{t}.0')
        np.full((10,16),10,dtype='<u8').tofile(z/'n_valid_100ms'/f'{t}.0')
        for b in range(16):
            power=np.ones((8,256),dtype='<f8');v=np.zeros((28,256),dtype='<c16')
            if b==12:
                power[0,129]=400;power[2,129]=100;v[1,129]=180*np.exp(-1j*np.deg2rad(37))
            power.tofile(z/'mean_auto_power_count2'/f'{t}.0.{b}');v.tofile(z/'mean_cross_visibility_count2'/f'{t}.0.{b}')
            np.tile(power,(10,1,1)).tofile(z/'mean_auto_power_count2_100ms'/f'{t}.0.{b}')
            np.tile(v,(10,1,1)).tofile(z/'mean_cross_visibility_count2_100ms'/f'{t}.0.{b}')
    x=summarize(root,2,root/'summary.npz')
    assert x['source_present'] and x['observed_common_peak_bin']==3201
    assert abs(x['rho02_complex_mean_pct']-90)<1e-9 and abs(x['phase02_complex_mean_deg']+37)<1e-9
print('PASS: source metadata, no configuration/reset, missing-source fail-stop, raw headroom, known complex tone and phase analysis')
