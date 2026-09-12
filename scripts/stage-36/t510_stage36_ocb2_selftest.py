#!/usr/bin/env python3
"""Check experiment boundaries and fail-closed handling without hardware."""
import copy,json
from pathlib import Path
from t510_stage36_ocb2_queue import OCB2,plan,tg
q=object.__new__(OCB2);q.ref=None;q.context={'dsa_db_by_adc':[20,0,20,0,0,0,0,0]}
v={'rows':[dict(adc=i,dsa={'Attenuation':q.context['dsa_db_by_adc'][i]},adc_error_bits=0,physical=[{'override':0,'coefficients':[1]*4}]*2,coefficients={'ocb2':[1]*4+[0]*4}) for i in range(8)]}
q.call=lambda *a:copy.deepcopy(v)
assert q.probe('pre.json')==v
q.ref=copy.deepcopy(v['rows']);q.expected='A';q.values={'A':[1]*4+[0]*4}
try:q.probe('bad.json');raise AssertionError('missing override accepted')
except RuntimeError as e:assert 'override' in str(e)
v['rows'][6]['physical']=[{'override':1,'coefficients':[1]*4}]*2
q.probe('ok.json')
v['rows'][3]['physical']=[{'override':1,'coefficients':[2]*4}]*2
try:q.probe('bad.json');raise AssertionError('untargeted change accepted')
except RuntimeError as e:assert 'untargeted' in str(e)
phases=plan('test');assert sum(p['duration_seconds'] for p in phases)==610
assert [p['action'] for p in phases]==[None,'A',None,'B','A','release']
old=tg.TGQueue.ensure_mode;events=[]
try:
 tg.TGQueue.ensure_mode=lambda self,p:events.append(('prepare',p['index']))
 q.call=lambda action,name:events.append(('action',action))
 q.probe=lambda name:events.append(('probe',name))
 for p in phases:q.ensure_mode(p)
 assert len([e for e in events if e[0]=='prepare'])==6
 assert [e[1] for e in events if e[0]=='action']==['A','B','A','release']
finally:tg.TGQueue.ensure_mode=old
print('PASS: missing override/untargeted mutation fail closed; complete610s sequence; one preparation per phase')
