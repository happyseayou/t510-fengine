#!/usr/bin/env python3
"""Read sealed PR summary copies, cross-check complex differences, report descriptive statistics."""
import json
import math
from pathlib import Path
import statistics
import sys
p=Path(sys.argv[1])
segments=json.loads((p/'abc_segment_comparison.json').read_text())['rows']
paired=json.loads((p/'initialization_paired_comparison.json').read_text())['rows']
state=json.loads((p/'state-audit.json').read_text())
phases=[x['phase'] for x in state if not x['phase']['short_gate']]
assert len(phases)==13 and len(segments)==13*28*3 and len(paired)==6*28*3
lookup={(r['scan_id'],tuple(r['pair']),r['global_bin']):r for r in segments}
def rho(r):return complex(r['real_count2'],r['imag_count2'])/math.sqrt(r['power_a_count2']*r['power_b_count2'])*100
for r in paired:
 i=next(i for i,x in enumerate(phases) if x['group']==r['group'] and x['segment']==r['segment'])
 a,b,c=[lookup[(phases[j]['scan_id'],tuple(r['pair']),r['global_bin'])] for j in (i-1,i,i+1)]
 jump=rho(b)-rho(a)
 for key,value in [('jump_real_pp',jump.real),('jump_imag_pp',jump.imag),('jump_abs_pp',abs(jump)),('following_control_change_abs_pp',abs(rho(c)-rho(b)))]:
  assert math.isclose(r[key],value,rel_tol=1e-12,abs_tol=1e-12),(r,key,value)
summary=[]
for k in (3073,3182,3328):
 for g in 'PR':
  rows=[r for r in paired if r['group']==g and r['global_bin']==k]
  summary.append(dict(bin=k,group=g,entries=len(rows),repetitions=3,
    median_jump_pp=statistics.median(x['jump_abs_pp'] for x in rows),
    median_following_control_pp=statistics.median(x['following_control_change_abs_pp'] for x in rows),
    above_one_pp=sum(x['jump_abs_pp']>1 for x in rows)))
for row in state:
 if row['phase']['group'] not in 'PR':continue
 op=row['operation']['operation'];recovery=op['applied']['observation']['clock_recovery']
 assert len(op['explicit_tile_reset_calls'])==(8 if row['phase']['group']=='R' else 0)
 assert recovery['clock_preserved'] and not recovery['clock_reconfigured'] and not recovery['tile_reset_calls']
assert len({json.dumps(x['after']['digital_scaling'],sort_keys=True) for x in state})==1
assert all(x['after']['mts']['adc']['active_measured_latency']==[492]*4 for x in state)
assert all(x['after']['mts']['adc']['offset']==[9]*4 for x in state)
print(json.dumps({'verification':'PASS','summary':summary,
 'note':'Entries share channels and repetitions, not independent samples; 1pp is descriptive, not a significance threshold.'},indent=2))
