#!/usr/bin/env python3
"""ADC6 OCB2 natural / same-value / B / A / release, complete bounded queue."""
import fcntl,json,subprocess,sys
from pathlib import Path
import numpy as np
from t510_stage36_background_lifetime_queue import Lifetime,tg
from t510_stage36_background_grid import score
from t510_stage36_tile_analyze import PAIRS

def plan(qid):
 return [dict(index=i,kind='xcorr',label=label,group='OCB2',segment=i+1,scan='OCB2',position='scan',mode='spec_only',duration_seconds=n,scan_id=f'{qid}-{label}-{n}s',action=action,status='pending') for i,(label,n,action) in enumerate([('natural',120,None),('same-value-gate',10,'A'),('A1',120,None),('B',120,'B'),('A2',120,'A'),('released',120,'release')])]
class OCB2(Lifetime):
 def __init__(self,args,template):
  super().__init__(args,template);self.phases=plan(args.queue_id);self.expected=None;self.ref=None
  self.context.update(rf_inputs='TG OFF through splitter ADC0/2; six others independent50ohm; unchanged wiring',intervention='ADC6 OCB2 only; no reset/MTS/clock/DSA changes',interpretation='OCB2 causal diagnostic; raw and fixed/state-specific background holdouts')
  self.state.update(phases=self.phases,physical_context=self.context,products=['fullband100ms_and1s_visibility_auto','OCB2_register_journals','raw_fixed_and_local_background_holdouts'],experiment=dict(sequence=['natural120','same-value10 gate','A120','B120','A120','release120','verify/analyze/stop'],target_adc=6,calibration_block=1,limitations=['Single A-B-A sequence, not proof of unique cause','Other adaptive calibrations are observed, not frozen','Release is a separate boundary; firstminute may include convergence','Failure stops streaming and preserves override state for diagnosis']))
 def call(self,action,name):
  p=subprocess.run(['/usr/bin/python3',str(Path(__file__).with_name('t510_stage36_ocb2_transport.py')),action],capture_output=True,text=True,timeout=120)
  (self.evidence/(name+'.stdout')).write_text(p.stdout);(self.evidence/(name+'.stderr')).write_text(p.stderr)
  if p.returncode:raise RuntimeError('OCB2 helper failed: '+p.stderr)
  v=json.loads(p.stdout);tg.science.base.write_json_new(self.evidence/(name+'.json'),v)
  if not v['ok'] or v['helper_sha256']!=tg.science.base.sha256_file(Path(__file__).with_name('t510_stage36_ocb2_probe.py')):raise RuntimeError('OCB2 helper identity')
  return v
 def probe(self,name):
  v=self.call('probe',name.removesuffix('.json'));rows=v['rows']
  if any(r['adc_error_bits'] for r in rows):raise RuntimeError('RFDC error')
  if [r['dsa']['Attenuation'] for r in rows]!=self.context['dsa_db_by_adc']:raise RuntimeError('DSA mismatch')
  if self.ref is not None:
   if [r['dsa'] for r in rows]!=[r['dsa'] for r in self.ref]:raise RuntimeError('DSA control changed')
   for i,r in enumerate(rows):
    if i!=6 and r['physical']!=self.ref[i]['physical']:raise RuntimeError('untargeted OCB2 changed')
   for p in rows[6]['physical']:
    if p['override']!=int(self.expected in ('A','B')):raise RuntimeError('OCB2 override changed')
   if self.expected in ('A','B') and rows[6]['coefficients']['ocb2']!=self.values[self.expected]:raise RuntimeError('OCB2 coefficients changed')
  return v
 def preflight(self):
  super().preflight()
  v=self.call('snapshot','ocb2_original');self.ref=v['rows'];self.values={'A':self.ref[6]['coefficients']['ocb2'],'B':json.loads(Path(__file__).with_name('ocb2-B.json').read_text())['coefficients']}
  if self.values['A']==self.values['B']:raise RuntimeError('A equals B')
  tg.science.base.write_json_new(self.evidence/'ocb2_values.json',self.values)
 def ensure_mode(self,phase):
  tg.TGQueue.ensure_mode(self,phase)
  if phase['action']:
   self.call(phase['action'],f"phase_{phase['index']:02d}_ocb2_action");self.expected=phase['action']
   self.probe(f"phase_{phase['index']:02d}_ocb2_checked.json")
 def run_phase(self,phase):
  tg.science.Queue.run_phase(self,phase);self.probe(f"phase_{phase['index']:02d}_stopped_probe.json")
  if self.initial!=tg.abc.initialization_identity(self.board()):raise RuntimeError('initialization changed')
  ds=self.args.measurement_root/phase['scan_id'];m=ds/'dataset_manifest.json'
  if tg.science.base.sha256_file(m)!=phase['manifest']['sha256']:raise RuntimeError('manifest changed')
  for row in json.loads(m.read_text())['files']:
   p=ds/row['path']
   if p.stat().st_size!=row['bytes'] or tg.science.base.sha256_file(p)!=row['sha256']:raise RuntimeError('dataset changed')
  result=tg.abc.fullband.verify(ds,phase['duration_seconds']);tg.science.base.write_json_new(self.evidence/f"phase_{phase['index']:02d}_numeric.json",result)
  if result['status']!='PASS':raise RuntimeError('numeric failed')
 def independent_verify(self):
  self.state['verification_status']='running';self.save();self.compare_segments();self.state['verification_status']='PASS';self.save()
 def compare_segments(self):
  arrays={};rows=[]
  for phase in self.phases:
   if phase['duration_seconds']!=120:continue
   z=self.args.measurement_root/phase['scan_id']/'xcorr.zarr';vs=[];ps=[]
   for minute in range(2):
    v=np.zeros((28,4096),complex);p=np.zeros((8,4096));n=np.zeros(4096)
    for sec in range(minute*60,(minute+1)*60):
     w=np.fromfile(z/'n_valid'/f'{sec}.0',dtype='<u8');assert len(w)==16 and np.all(w>0)
     for block in range(16):
      sl=slice(block*256,(block+1)*256);v[:,sl]+=np.fromfile(z/'mean_cross_visibility_count2'/f'{sec}.0.{block}',dtype='<c16').reshape(28,256)*w[block];p[:,sl]+=np.fromfile(z/'mean_auto_power_count2'/f'{sec}.0.{block}',dtype='<f8').reshape(8,256)*w[block];n[sl]+=w[block]
    vs.append(v/n);ps.append(p/n)
   arrays[phase['label']]=(vs,ps)
  fixed=arrays['A1'][0][0]
  for label,(vs,ps) in arrays.items():
   for policy,b in [('raw',0),('fixed_A1',fixed),('local',vs[0])]:
    rows.append(dict(state=label,policy=policy,**score(vs[1],b,ps[1])))
   np.savez_compressed(self.evidence/(label+'-minutes.npz'),visibility=vs,power=ps,fixed_background=fixed)
  tg.science.base.write_json_new(self.evidence/'ocb2_background_comparison.json',dict(rows=rows,pairs=PAIRS,definition='Each state first60 train, next60 independent test. Fixed template from A1 first60. Natural compared to A1 is retrospective, not causal online correction. Raw used for OCB2 cause assessment. No magnitude/phase subtraction.'))
def main():
 args=tg.science.parse_args()
 if args.dry_run:print(json.dumps(plan(args.queue_id),indent=2));return 0
 with args.lock.open('a+b') as lock:
  fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB);return OCB2(args,json.loads(args.template.read_text())).run()
if __name__=='__main__':sys.exit(main())
