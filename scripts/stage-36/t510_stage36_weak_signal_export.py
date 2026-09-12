#!/usr/bin/env python3
"""Export verified native 100ms OFF/ON/OFF points, retaining one fixed background."""
import argparse,json,hashlib,itertools
from pathlib import Path
import numpy as np

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main(root,out):
 out.mkdir(parents=True,exist_ok=False);(out/'trends').mkdir()
 pairs=list(itertools.combinations(range(8),2));bins=[3073,3182,3200,3201,3202,3328]
 series=[];background=None
 for label,qid in [('before','stage36-weak-off-20260912'),('on','stage36-weak-on-m20-20260912'),('after','stage36-weak-post-off-20260912')]:
  q=root/(qid+'-queue');s=json.loads((q/'queue_state.json').read_text());assert s['status']=='completed' and s['verification_status']=='PASS'
  m=q/'queue_manifest.json';assert sha(m)==(q/'queue_manifest.sha256').read_text().split()[0]
  files={f['path']:f for f in json.loads(m.read_text())['files']}
  name='evidence/phase_01_tone.npz' if label=='on' else 'evidence/off_template_validation.npz'
  p=q/name;assert sha(p)==files[name]['sha256']
  with np.load(p) as z:
   if label=='before':background=z['background'].copy()
   reference=z['visibility_count2'].copy() if label=='on' else z['validation'].copy()
  phase=s['phases'][1 if label=='on' else 0];ds=root/phase['scan_id'];m=ds/'dataset_manifest.json';assert sha(m)==phase['manifest']['sha256']
  df={f['path']:f for f in json.loads(m.read_text())['files']}
  def read(rel,dtype,shape):
   p=ds/rel;assert sha(p)==df[rel]['sha256'];return np.fromfile(p,dtype=dtype).reshape(shape)
  duration=phase['duration_seconds'];v=np.empty((duration*10,28,len(bins)),complex);w=np.empty((duration*10,len(bins)))
  for sec in range(duration):
   n=read(f'xcorr.zarr/n_valid_100ms/{sec}.0','<u8',(10,16))
   for block in (12,13):
    a=read(f'xcorr.zarr/mean_cross_visibility_count2_100ms/{sec}.0.{block}','<c16',(10,28,256))
    for bi,k in enumerate(bins):
     if k//256==block:v[sec*10:sec*10+10,:,bi]=a[:,:,k%256];w[sec*10:sec*10+10,bi]=n[:,block]
  assert np.all(w>0)
  start=0 if label=='on' else 600
  np.testing.assert_allclose((v[start:]*w[start:,None,:]).sum(axis=0)/w[start:].sum(axis=0),reference[:,bins],rtol=1e-10,atol=1e-8)
  series.append(dict(id=label,duration=duration,scan_id=phase['scan_id'],manifest_sha256=sha(m)))
  for j,pair in enumerate(pairs):
   for bi,k in enumerate(bins):
    a=v[:,j,bi];b=background[j,k]
    record=dict(real=a.real.tolist(),imag=a.imag.tolist(),weights=w[:,bi].astype(int).tolist(),background=[float(b.real),float(b.imag)])
    (out/'trends'/f'{label}-{pair[0]}-{pair[1]}-{k}.json').write_text(json.dumps(record,separators=(',',':')))
 (out/'summary.json').write_text(json.dumps(dict(pairs=pairs,bins=bins,series=series),separators=(',',':')))
 print('PASS: native chunks SHA and weighted means match sealed products')
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();main(a.root,a.output)
