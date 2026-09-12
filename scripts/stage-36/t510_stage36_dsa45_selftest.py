#!/usr/bin/env python3
import copy
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import t510_stage36_dsa45_probe as p

blocks=[SimpleNamespace(DSA={'Attenuation':20. if i in (0,2) else 0.,'DisableRTS':1 if i in (0,2) else 0}) for i in range(8)]
core=SimpleNamespace(rfdc=SimpleNamespace(adc_tiles=[SimpleNamespace(blocks=blocks[i:i+2]) for i in range(0,8,2)]))
def snap(c):return {'rows':[dict(adc=i,dsa=copy.deepcopy(b.DSA),adc_error_bits=0) for i,b in enumerate(blocks)]}
original=snap(core)
with patch.object(p,'snapshot',side_effect=snap):
    for letter in 'ABACADA':
        result=p.apply(core,'DSA_'+letter,Mock())
        assert [r['dsa']['Attenuation'] for r in result['rows'][4:6]]==list(p.SETTINGS['DSA_'+letter])
        for i in (0,1,2,3,6,7):assert blocks[i].DSA==original['rows'][i]['dsa']
    before=copy.deepcopy([b.DSA for b in blocks]);bad=snap(core);bad['rows'][4]['adc_error_bits']=1
    with patch.object(p,'snapshot',return_value=bad):
        try:p.apply(core,'DSA_B',Mock())
        except RuntimeError:pass
        else:raise AssertionError('error did not block writes')
    assert [b.DSA for b in blocks]==before
with patch.object(p,'snapshot',side_effect=RuntimeError('streaming guard')):
    try:p.apply(core,'DSA_B',Mock())
    except RuntimeError:pass
    else:raise AssertionError('streaming guard bypass')
for action in ('ADC','R','M','clear_once'):
    try:p.execute(action)
    except ValueError:pass
    else:raise AssertionError('unsupported action allowed')
print('PASS: seven DSA settings, untouched channels, RFDC/streaming error blocks writes, forbidden reset/MTS/clear')
