#!/usr/bin/env python3
"""All independent loads: one120s capture, generic template + immutable corrected products."""
import fcntl,hashlib,json,sys,uuid
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from python import t510_background as bg
from t510_stage36_background_lifetime_queue import Lifetime,tg
from t510_stage36_tile_analyze import PAIRS
from t510_stage36_background_grid import score
BINS=[3073,3182,3200,3201,3202,3328]
def plan(qid):return [dict(index=0,kind='xcorr',label='reference-validation',group='BACKGROUND_STANDARD',segment=1,scan='REFERENCE',position='scan',mode='spec_only',duration_seconds=120,scan_id=qid+'-reference-120s',status='pending')]
class Standard(Lifetime):
 def __init__(self,args,template):
  super().__init__(args,template);self.phases=plan(args.queue_id);self.epoch=str(uuid.uuid4())
  self.context.update(rf_inputs='eight independent50ohm terminations; operator reconfirmed after splitter removal',intervention='none; no reset/MTS/DSA/configuration writes',interpretation='Formal background analysis acceptance; first60 reference, last60 independent validation',wiring_id='independent-50ohm-eight-20260912',initialization_epoch=self.epoch)
  self.state.update(phases=self.phases,physical_context=self.context,experiment=dict(sequence=['preflight','120s capture','SHA and numeric verification','fit60s reference','auto-apply to independent60s','verify derived products','build webpage','stop/mute'],scope='Reference-load validity only; no transfer to antenna',validity_policy_seconds=300))
 def calibration(self,b):return [c['coefficients']['ocb2'] for c in b['rfdc']['calibration']['channels']]
 def preflight(self):
  preparation=Path(__file__).resolve().parents[3]/'preparation'
  for name in ('preflight-error.json','interrupt-baseline.json'):
   if (preparation/name).exists():
    value=json.loads((preparation/name).read_text());tg.science.base.write_json_new(self.evidence/name,value)
    if name=='interrupt-baseline.json' and not value.get('ok'):raise RuntimeError('pre-capture interrupt baseline failed')
  super().preflight();self.before=self.board();self.cal=self.calibration(self.before)
  self.dsa=json.loads((self.evidence/'tg_monitor_preflight.json').read_text())['rows']
  tg.science.base.write_json_new(self.evidence/'background_configuration.json',dict(identity=self.initial,ocb2=self.cal,dsa=self.dsa,epoch=self.epoch,context=self.context))
 def compare_segments(self):
  after=self.board()
  if self.cal!=self.calibration(after) or self.initial!=tg.abc.initialization_identity(after) or self.before['clock']['profile_sha256']!=after['clock']['profile_sha256']:raise RuntimeError('calibration/initialization changed')
  post=json.loads((self.evidence/'lifetime_stopped_probe.json').read_text())
  if [r['dsa'] for r in post['rows']]!=[r['dsa'] for r in self.dsa]:raise RuntimeError('DSA changed')
  phase=self.phases[0];ds=self.args.measurement_root/phase['scan_id'];z=ds/'xcorr.zarr';mp=ds/'dataset_manifest.json'
  files={r['path']:r for r in json.loads(mp.read_text())['files']}
  def read(rel,dtype,shape):
   p=ds/rel
   if bg.digest(p)!=files[rel]['sha256']:raise RuntimeError('source changed after verification')
   return np.fromfile(p,dtype=dtype).reshape(shape)
  cfg=dict(identity=self.initial,ocb2=self.cal,dsa=[r['dsa'] for r in self.dsa],clock=self.before['clock']['profile_sha256'])
  start=phase['capture_status']['started_unix_ms']/1000
  c=dict(initialization_epoch=self.epoch,wiring_id=self.context['wiring_id'],configuration_sha256=hashlib.sha256(bg.canonical(cfg).encode()).hexdigest(),core_version=self.before['core_version'],bitstream_sha256=tg.science.EXPECTED_BITSTREAM_SHA256,pair_order=[list(p) for p in PAIRS],frequency_bins=list(range(4096)),source_manifest_sha256=bg.digest(mp),source_id=phase['scan_id'],start_unix_s=start,end_unix_s=start+60,role='reference')
  v=np.empty((60,28,4096),complex);w=np.empty((60,4096))
  for sec in range(60):
   n=read(f'xcorr.zarr/n_valid/{sec}.0','<u8',(16,))
   for b in range(16):
    sl=slice(b*256,(b+1)*256);v[sec,:,sl]=read(f'xcorr.zarr/mean_cross_visibility_count2/{sec}.0.{b}','<c16',(28,256));w[sec,sl]=n[b]
  template=self.evidence/'background-template';bg.fit(v,w,c,template,valid_for_seconds=300);_,bkg=bg.load_template(template)
  web=self.evidence/'web';web.mkdir();(web/'trends').mkdir();rawfocus=np.empty((600,28,6),complex);corrfocus=np.empty_like(rawfocus);wf=np.empty((600,6));mean=np.zeros((28,4096),complex);power=np.zeros((8,4096));total=np.zeros(4096)
  products=[]
  for sec in range(60,120):
   v=np.empty((10,28,4096),complex);w=np.empty((10,4096));p=np.empty((10,8,4096));n=read(f'xcorr.zarr/n_valid_100ms/{sec}.0','<u8',(10,16))
   for b in range(16):
    sl=slice(b*256,(b+1)*256);v[:,:,sl]=read(f'xcorr.zarr/mean_cross_visibility_count2_100ms/{sec}.0.{b}','<c16',(10,28,256));p[:,:,sl]=read(f'xcorr.zarr/mean_auto_power_count2_100ms/{sec}.0.{b}','<f8',(10,8,256));w[:,sl]=n[:,b,None]
   target={**c,'role':'reference','start_unix_s':start+sec,'end_unix_s':start+sec+1}
   out=self.evidence/'corrected-products'/f'{sec:03d}'
   m=bg.save_product(out,v,w,target,template=template,mode='auto')
   if m['status']!='corrected':raise RuntimeError('acceptance template unexpectedly inapplicable')
   with np.load(out/'corrected.npz') as zz:r=zz['visibility'].copy()
   np.testing.assert_allclose(r,v-bkg,atol=1e-12,rtol=1e-12)
   np.testing.assert_allclose(np.diff(r,axis=0),np.diff(v,axis=0),atol=1e-11,rtol=1e-11)
   offset=(sec-60)*10;rawfocus[offset:offset+10]=v[:,:,BINS];corrfocus[offset:offset+10]=r[:,:,BINS];wf[offset:offset+10]=w[:,BINS]
   mean+=(v*w[:,None,:]).sum(0);power+=(p*w[:,None,:]).sum(0);total+=w.sum(0)
   products.append(dict(second=sec,manifest_sha256=bg.digest(out/'product.json'),payload_sha256=m['corrected_sha256']))
  mean/=total;power/=total
  for j,pair in enumerate(PAIRS):
   for bi,k in enumerate(BINS):
    v=rawfocus[:,j,bi];r=corrfocus[:,j,bi];b=bkg[j,k]
    np.testing.assert_allclose(np.mean(np.abs(v-v.mean())**2),np.mean(np.abs(r-r.mean())**2),rtol=1e-11,atol=1e-11)
    allan=[]
    for count in (1,10,100):
     def av(x):
      ww=wf[:,bi].reshape(-1,count);a=(x.reshape(-1,count)*ww).sum(1)/ww.sum(1);return float(np.mean(np.abs(np.diff(a))**2)/2)
     x,y=av(v),av(r);np.testing.assert_allclose(x,y,rtol=1e-10,atol=1e-10);allan.append(dict(tau_seconds=count/10,raw=x,corrected=y))
    (web/'trends'/f'validation-{pair[0]}-{pair[1]}-{k}.json').write_text(bg.canonical(dict(real=v.real.tolist(),imag=v.imag.tolist(),weights=wf[:,bi].astype(int).tolist(),background=[b.real,b.imag],allan_complex_count4=allan)))
  summary=dict(pairs=PAIRS,bins=BINS,series=[dict(id='validation',duration=60,scan_id=phase['scan_id'],manifest_sha256=bg.digest(mp))],status='PASS',template_sha256=bg.digest(template/'template.json'),context=c,validity_policy_seconds=300,raw_score=score(mean,0,power),corrected_score=score(mean,bkg,power),interpretation='Independent60s test. Validity is restricted to this unchanged reference session; no inferred lifetime or antenna transfer. Fixed subtraction does not improve centered variance or complex Allan variance.')
  (web/'summary.json').write_text(bg.canonical(summary));tg.science.base.write_json_new(self.evidence/'background_products.json',dict(status='PASS',template=summary['template_sha256'],raw_dataset=str(ds),products=products,context=c,raw_score=summary['raw_score'],corrected_score=summary['corrected_score']))
def main():
 args=tg.science.parse_args()
 if args.dry_run:print(json.dumps(plan(args.queue_id),indent=2));return 0
 with args.lock.open('a+b') as lock:
  fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB);return Standard(args,json.loads(args.template.read_text())).run()
if __name__=='__main__':sys.exit(main())
