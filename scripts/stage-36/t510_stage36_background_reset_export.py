#!/usr/bin/env python3
"""Verified native100ms reset experiment export; no acquisition or calibration writes."""
import argparse,hashlib,json
from pathlib import Path
import numpy as np

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main(root,out):
 out.mkdir(parents=True,exist_ok=False);(out/'trends').mkdir()
 q=root/'stage36-background-reset-20260911-r3-queue';state=json.loads((q/'queue_state.json').read_text())
 assert state['status']=='completed' and state['verification_status']=='PASS'
 mp=q/'queue_manifest.json';assert sha(mp)==(q/'queue_manifest.sha256').read_text().split()[0]
 files={r['path']:r for r in json.loads(mp.read_text())['files']}
 def verified(rel):
  p=q/rel;assert sha(p)==files[rel]['sha256'];return p
 result=json.loads(verified('evidence/reset_background_comparison.json').read_text());pairs=result['pairs'];bins=[3073,3182,3328]
 summary=[]
 for rnd in (1,2,3):
  for j,pair in enumerate(pairs):
   med={policy:float(np.median([r['pair_median_pct'][j] for r in result['rows'] if r['round']==rnd and r['policy']==policy])) for policy in ('none','old','new')}
   summary.append(dict(round=rnd,pair=pair,median_pct=med,new_better_none=med['new']<med['none'],new_better_old=med['new']<med['old']))
  phase=state['phases'][(rnd-1)*3+2];ds=root/phase['scan_id'];dmp=ds/'dataset_manifest.json'
  assert sha(dmp)==phase['manifest']['sha256']==(ds/'dataset_manifest.sha256').read_text().split()[0]
  df={r['path']:r for r in json.loads(dmp.read_text())['files']}
  def read(rel,dtype,shape):
   p=ds/rel;assert sha(p)==df[rel]['sha256'] and p.stat().st_size==df[rel]['bytes'];return np.fromfile(p,dtype=dtype).reshape(shape)
  with np.load(verified(f'evidence/round{rnd}_templates_test.npz')) as z:arrays={k:z[k].copy() for k in z.files}
  values=np.empty((5400,28,3),complex);weights=np.empty((5400,3))
  for sec in range(540):
   n=read(f'xcorr.zarr/n_valid_100ms/{sec}.0','<u8',(10,16))
   for block in (12,13):
    v=read(f'xcorr.zarr/mean_cross_visibility_count2_100ms/{sec}.0.{block}','<c16',(10,28,256))
    for b,k in enumerate(bins):
     if k//256==block:values[sec*10:sec*10+10,:,b]=v[:,:,k%256];weights[sec*10:sec*10+10,b]=n[:,block]
  assert np.all(weights>0)
  for m in range(9):
   v=values[m*600:(m+1)*600];w=weights[m*600:(m+1)*600]
   np.testing.assert_allclose(np.sum(v*w[:,None,:],axis=0)/w.sum(axis=0),arrays['visibility'][m][:,bins],atol=1e-10,rtol=1e-11)
  for j,pair in enumerate(pairs):
   for b,k in enumerate(bins):
    v=values[:,j,b]
    record=dict(round=rnd,pair=pair,bin=k,points=5400,cadence_ms=100,scan_id=phase['scan_id'],manifest_sha256=sha(dmp),
      real=v.real.tolist(),imag=v.imag.tolist(),n_valid=weights[:,b].astype(int).tolist(),
      old=[float(arrays['old'][j,k].real),float(arrays['old'][j,k].imag)],new=[float(arrays['new'][j,k].real),float(arrays['new'][j,k].imag)],
      minutes=[dict(real=float(arrays['visibility'][m,j,k].real),imag=float(arrays['visibility'][m,j,k].imag),power_a=float(arrays['power'][m,pair[0],k]),power_b=float(arrays['power'][m,pair[1],k])) for m in range(9)])
    (out/'trends'/f'{rnd}-{pair[0]}-{pair[1]}-{k}.json').write_text(json.dumps(record,separators=(',',':')))
 clean=[{k:v for k,v in r.items() if k!='focus'} for r in result['rows']]
 payload=dict(pairs=pairs,summary=summary,rows=clean,queue_manifest_sha256=sha(mp),limitations=result['limitations'])
 (out/'summary.json').write_text(json.dumps(payload,separators=(',',':')))
 print(json.dumps({rnd:{'new_better_none':sum(r['new_better_none'] for r in summary if r['round']==rnd),'new_better_old':sum(r['new_better_old'] for r in summary if r['round']==rnd)} for rnd in (1,2,3)}))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();main(a.root,a.output)
