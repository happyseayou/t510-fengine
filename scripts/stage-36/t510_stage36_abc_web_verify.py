#!/usr/bin/env python3
"""Check ABC API identities, segment statistics, and preserved acquisition gaps."""
import argparse
import json
import urllib.request
from pathlib import Path
import numpy as np

def main():
    p=argparse.ArgumentParser();p.add_argument('--url',default='http://127.0.0.1:8036')
    p.add_argument('--queue',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    def get(path):
        with urllib.request.urlopen(a.url+path,timeout=180) as r:return json.load(r)
    state=json.loads((a.queue/'queue_state.json').read_text())
    reference=json.loads((a.queue/'evidence/abc_segment_comparison.json').read_text())['rows']
    assert get('/api/v2/meta')['abc_available']
    results=[]
    for group in 'ABC':
        for cadence in [100,1000]:
            params=f'domain=abc_pair&group={group}&pair=1-2&bins=3073&cadence_ms={cadence}'
            t=get('/api/v2/timeseries?'+params+'&view=timeline')
            s=get('/api/v2/timeseries?'+params+'&view=segments')
            assert len(t['time_s'])==900000//cadence and len(s['time_s'])==9
            assert len(t['break_before_indices'])==(0 if group=='A' else 8)
            assert all(t['time_s'][j]-t['time_s'][j-1]>90 for j in t['break_before_indices'])
            phases=[p for p in state['phases'] if p['group']==group]
            assert [x['scan_id'] for x in t['segments']]==[p['scan_id'] for p in phases]
            expected=[x for x in reference if x['group']==group and x['pair']==[1,2] and x['global_bin']==3073]
            np.testing.assert_allclose(s['series'][0]['amplitude_count2'],[x['rho_pct'] for x in expected],atol=1e-11)
            np.testing.assert_allclose(s['series'][0]['phase_deg'],[x['phase_deg'] for x in expected],atol=1e-10)
            # Direct comparison to the first native chunk, no API helpers.
            z=a.queue.parent/phases[0]['scan_id']/'xcorr.zarr'
            if cadence==100:
                v=np.fromfile(z/'mean_cross_visibility_count2_100ms'/'0.0.12',dtype='<c16').reshape(10,28,256)[:,7,1]
            else:
                v=np.fromfile(z/'mean_cross_visibility_count2'/'0.0.12',dtype='<c16').reshape(28,256)[7,1:2]
            np.testing.assert_allclose(t['series'][0]['amplitude_count2'][:len(v)],abs(v),atol=1e-12)
            results.append(dict(group=group,cadence_ms=cadence,points=len(t['time_s']),segments=len(s['time_s']),gap_count=len(t['break_before_indices'])))
    a.output.write_text(json.dumps({'status':'PASS','checks':results},indent=2))
    print(json.dumps({'status':'PASS','checks':results}))
if __name__=='__main__':main()
