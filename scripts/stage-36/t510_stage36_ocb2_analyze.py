#!/usr/bin/env python3
"""Read-only OCB2 vector contrasts with verified 1s/fullband and native100ms witnesses."""
import argparse,hashlib,itertools,json
from pathlib import Path
import numpy as np
PAIRS=list(itertools.combinations(range(8),2));BINS=[3073,3182,3200,3201,3202,3328];STATES=['natural','A1','B','A2','released']
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def dump(p,d):p.write_text(json.dumps(d,separators=(',',':'),allow_nan=False))
def contrast(a,b,c,alpha):return b-((1-alpha)*a+alpha*c)
def main(root,out):
 out.mkdir(parents=True,exist_ok=False);(out/'pairs').mkdir();q=root/'stage36-ocb2-20260912-queue'
 qm=q/'queue_manifest.json';assert sha(qm)==(q/'queue_manifest.sha256').read_text().split()[0]
 files={f['path']:f for f in json.loads(qm.read_text())['files']}
 def evidence(name):
  p=q/name;assert sha(p)==files[name]['sha256'];return p
 s=json.loads(evidence('queue_state.json').read_text()) if 'queue_state.json' in files else json.loads((q/'queue_state.json').read_text())
 assert s['status']=='completed' and s['verification_status']=='PASS'
 allv={};allp={};ten={};native={};epochs={};sources=[]
 for label in STATES:
  phase=next(p for p in s['phases'] if p['label']==label);ds=root/phase['scan_id'];m=ds/'dataset_manifest.json';assert sha(m)==phase['manifest']['sha256'];df={f['path']:f for f in json.loads(m.read_text())['files']}
  def read(rel,dtype,shape):
   p=ds/rel;assert sha(p)==df[rel]['sha256'];return np.fromfile(p,dtype=dtype).reshape(shape)
  vs=np.empty((120,28,4096),complex);ps=np.empty((120,8,4096));ns=np.empty((120,4096));nv=np.empty((1200,28,6),complex);npow=np.empty((1200,8,6));nw=np.empty((1200,6))
  for sec in range(120):
   n=read(f'xcorr.zarr/n_valid/{sec}.0','<u8',(16,));n100=read(f'xcorr.zarr/n_valid_100ms/{sec}.0','<u8',(10,16))
   for block in range(16):
    sl=slice(block*256,(block+1)*256);vs[sec,:,sl]=read(f'xcorr.zarr/mean_cross_visibility_count2/{sec}.0.{block}','<c16',(28,256));ps[sec,:,sl]=read(f'xcorr.zarr/mean_auto_power_count2/{sec}.0.{block}','<f8',(8,256));ns[sec,sl]=n[block]
    if block not in (12,13):continue
    vv=read(f'xcorr.zarr/mean_cross_visibility_count2_100ms/{sec}.0.{block}','<c16',(10,28,256));pp=read(f'xcorr.zarr/mean_auto_power_count2_100ms/{sec}.0.{block}','<f8',(10,8,256))
    for bi,k in enumerate(BINS):
     if k//256==block:nv[sec*10:sec*10+10,:,bi]=vv[:,:,k%256];npow[sec*10:sec*10+10,:,bi]=pp[:,:,k%256];nw[sec*10:sec*10+10,bi]=n100[:,block]
  assert np.all(ns>0) and np.all(nw>0)
  def mean(a,n,start,end):return (a[start:end]*n[start:end,None,:]).sum(axis=0)/n[start:end].sum(axis=0)
  v=np.array([mean(vs,ns,i,i+60) for i in (0,60)]);p=np.array([mean(ps,ns,i,i+60) for i in (0,60)])
  with np.load(evidence('evidence/'+label+'-minutes.npz')) as z:
   np.testing.assert_allclose(v,z['visibility'],rtol=1e-11,atol=1e-9);np.testing.assert_allclose(p,z['power'],rtol=1e-11,atol=1e-9)
  for i in (0,1):
   np.testing.assert_allclose(mean(nv,nw,i*600,(i+1)*600),v[i][:,BINS],rtol=1e-11,atol=1e-9)
   np.testing.assert_allclose(mean(npow,nw,i*600,(i+1)*600),p[i][:,BINS],rtol=1e-11,atol=1e-9)
  allv[label]=v;allp[label]=p;ten[label]=np.array([mean(vs,ns,i,i+10) for i in range(0,120,10)]);native[label]=(nv,npow,nw)
  epochs[label]=phase['capture_status']['started_unix_ms']/1000+90
  sources.append(dict(state=label,scan_id=phase['scan_id'],manifest_sha256=sha(m),test_midpoint_unix_s=epochs[label]))
  print('verified '+label,flush=True)
 alpha=(epochs['B']-epochs['A1'])/(epochs['A2']-epochs['A1']);assert 0<alpha<1
 a,b,c=[allv[k][1] for k in ('A1','B','A2')];power=(allp['A1'][1]+allp['A2'][1])/2
 norm=np.array([np.sqrt(power[i]*power[j]) for i,j in PAIRS]);assert np.all(norm>0)
 delta=contrast(a,b,c,alpha);ret=c-a
 drift=np.median(np.concatenate([np.abs(np.diff(ten[k][6:],axis=0)) for k in ('A1','B','A2')]),axis=0)
 metrics={'B_vs_interpolated_A':100*np.abs(delta)/norm,'A_return':100*np.abs(ret)/norm,'within_10s_change':100*drift/norm,'same_value_change':100*np.abs(a-allv['natural'][1])/norm,'release_change':100*np.abs(allv['released'][1]-c)/norm}
 summary=[];band=slice(3072,3329)
 for j,pair in enumerate(PAIRS):
  row=dict(pair=pair,target_pair=6 in pair,**{k:float(np.median(v[j,band])) for k,v in metrics.items()});row['fraction_effect_above_both_descriptive_scales']=float(np.mean((metrics['B_vs_interpolated_A'][j,band]>metrics['A_return'][j,band]) & (metrics['B_vs_interpolated_A'][j,band]>metrics['within_10s_change'][j,band])));summary.append(row)
  spectra={k:v[j].tolist() for k,v in metrics.items()}
  spectra['raw_rho']={k:(100*np.abs(allv[k][1][j])/np.sqrt(allp[k][1][pair[0]]*allp[k][1][pair[1]])).tolist() for k in STATES}
  spectra['corrected_rho']={policy:{k:(100*np.abs(allv[k][1][j]-(allv['A1'][0][j] if policy=='fixed' else allv[k][0][j]))/np.sqrt(allp[k][1][pair[0]]*allp[k][1][pair[1]])).tolist() for k in STATES} for policy in ('fixed','local')}
  spectra['adc_power']={k:[allp[k][1][pair[0]].tolist(),allp[k][1][pair[1]].tolist()] for k in STATES}
  records={}
  for bi,k in enumerate(BINS):
   records[k]={}
   for label in STATES:
    v,p,w=native[label];z=v[:,j,bi];bg=allv['A1'][0][j,k];local=allv[label][0][j,k]
    records[k][label]=dict(real=z.real.tolist(),imag=z.imag.tolist(),power_a=p[:,pair[0],bi].tolist(),power_b=p[:,pair[1],bi].tolist(),n_valid=w[:,bi].astype(int).tolist(),fixed=[bg.real,bg.imag],local=[local.real,local.imag],ten_real=ten[label][:,j,k].real.tolist(),ten_imag=ten[label][:,j,k].imag.tolist())
  dump(out/'pairs'/f'{pair[0]}-{pair[1]}.json',dict(pair=pair,native=records,spectra=spectra))
 payload=dict(pairs=PAIRS,bins=BINS,states=STATES,summary=summary,alpha=alpha,sources=sources,queue_manifest_sha256=sha(qm),definitions={'band':'bins3072..3328 inclusive','B_vs_interpolated_A':'100*abs(B-((1-alpha)*A1+alpha*A2))/sqrt(Pa*Pb), test60s means, common A mean-power normalization','A_return':'100*abs(A2-A1)/sqrt(Pa*Pb)','within_10s_change':'median abs adjacent10s complex mean changes within test halves of A1/B/A2, same normalization; descriptive scale, not standard error'},limitations=['One A-B-A, no p values; frequency/time samples not assumed independent.','10s-change scale is not 60s-mean uncertainty; exceedance not significance.','Time interpolation removes only assumed linear drift; cannot exclude nonlinear drift.','Natural and release boundaries include override-mode changes.'])
 dump(out/'summary.json',payload);print(json.dumps(summary),flush=True)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();main(a.root,a.output)
