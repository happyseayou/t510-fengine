#!/usr/bin/env python3
"""Three complete old60/reset/new60/test540 rounds, verify then compare."""
import fcntl,json,os,subprocess,sys
from pathlib import Path
import numpy as np
from t510_stage36_background_lifetime_queue import Lifetime,tg
from t510_stage36_background_grid import score
from t510_stage36_tile_analyze import PAIRS,load_rho

def plan(qid):
    return [dict(index=3*r+j,kind='xcorr',label=f'r{r+1}-{label}',group='RESET_BG',round=r+1,role=label,segment=j+1,
        scan='BACKGROUND',position='scan',mode='spec_only',duration_seconds=seconds,
        scan_id=f'{qid}-r{r+1}-{label}-{seconds}s',status='pending')
        for r in range(3) for j,(label,seconds) in enumerate([('old',60),('new',60),('test',540)])]
class ResetQueue(Lifetime):
    def __init__(self,args,template):
        super().__init__(args,template);self.phases=plan(args.queue_id)
        self.context['intervention']='ADC-only reset and same-profile prepare/MTS before each new reference; full DSA fields preserved'
        self.state.update(phases=self.phases,experiment=dict(rounds=3,sequence='old60 -> ADC reset/prepare/MTS -> new60 -> test540; repeat3; verify and analyze',
            parameters='Fixed60s per-bin complex mean. No fitting to test samples.',
            reset_scope='four ADC tiles only; no DAC reset, no PL reload or clock rewrite',
            interrupt_policy='record and clear historical latches once immediately after successful reset/prepare; five-second recurrence gate; never clear capture errors',
            limitations=['All-reference inputs, no astronomical signal.','No-reset control is previous fixed-state experiment; sequential time effects remain.']))
    def call(self,action,name,helper=None):
        env=dict(os.environ)
        if helper:env['T510_INIT_HELPER']=str(Path(env['T510_INIT_HELPER']).with_name(helper))
        p=subprocess.run(['/usr/bin/python3',str(Path(__file__).with_name('t510_stage36_init_transport.py')),action],env=env,capture_output=True,text=True,timeout=240)
        (self.evidence/(name+'.stdout')).write_text(p.stdout);(self.evidence/(name+'.stderr')).write_text(p.stderr)
        if p.returncode:raise RuntimeError(f'board action failed {name}: {p.stdout} {p.stderr}')
        v=json.loads(p.stdout);tg.science.base.write_json_new(self.evidence/(name+'.json'),v)
        if not v.get('ok'):raise RuntimeError('board action not OK: '+name)
        return v
    def probe(self,name):
        v=self.call('probe',name.removesuffix('.json'))
        if v['helper_sha256']!=tg.science.base.sha256_file(Path(__file__).with_name('t510_stage36_background_reset_probe.py')):raise RuntimeError('helper SHA mismatch')
        if [r['dsa']['Attenuation'] for r in v['rows']]!=self.context['dsa_db_by_adc'] or any(r['adc_error_bits'] for r in v['rows']):raise RuntimeError('DSA/RFDC error gate')
        if hasattr(self,'dsa_reference') and [r['dsa'] for r in v['rows']]!=self.dsa_reference:raise RuntimeError('DSA control state differs from queue start')
        self.dsa_reference=[r['dsa'] for r in v['rows']]
        return v
    def preflight(self):
        prior=self.args.measurement_root/'stage36-background-life-20260911-queue/queue_state.json'
        s=json.loads(prior.read_text())
        if s['status']!='completed' or s['verification_status']!='PASS':raise RuntimeError('lifetime predecessor not qualified')
        super().preflight()
        tg.science.base.write_json_new(self.evidence/'reset_implementation.json',{'files':{p.name:tg.science.base.sha256_file(p) for p in [Path(__file__),Path(__file__).with_name('t510_stage36_background_reset_probe.py'),Path(__file__).with_name('t510_stage36_tg_clear_errors.py')]}})
    def ensure_mode(self,phase):
        # One preparation/evidence write per phase. Reset follows stopped preparation.
        tg.TGQueue.ensure_mode(self,phase)
        if phase['role']=='new':
            self.probe(f'r{phase["round"]}_before_reset.json')
            value=self.call('ADC',f'r{phase["round"]}_reset')
            if value['background_helper_sha256']!=tg.science.base.sha256_file(Path(__file__).with_name('t510_stage36_background_reset_probe.py')):raise RuntimeError('reset helper SHA mismatch')
            self.call('clear_once',f'r{phase["round"]}_interrupt_baseline','t510_stage36_tg_clear_errors.py')
            after=self.board()
            errors=tg.science.identity_errors(after,mode='spec_only',center_mhz=self.args.center_mhz)
            if errors or after.get('streaming') or any(c['enabled'] for c in after['dac']['channels']):
                raise RuntimeError(f'post-reset identity/state mismatch: {errors}')
            self.probe(f'r{phase["round"]}_after_reset.json')
            self.initial=tg.abc.initialization_identity(after)
            tg.science.base.write_json_new(self.evidence/f'r{phase["round"]}_prepared_board.json',after)
    def run_phase(self,phase):
        tg.science.Queue.run_phase(self,phase)
        self.probe(f'phase_{phase["index"]:02d}_stopped_probe.json')
        if self.initial!=tg.abc.initialization_identity(self.board()):raise RuntimeError('initialization changed within capture')
        # Validate and seal each phase before the next reset/capture, never advance on bad data.
        ds=self.args.measurement_root/phase['scan_id'];mp=ds/'dataset_manifest.json'
        if tg.science.base.sha256_file(mp)!=(ds/'dataset_manifest.sha256').read_text().split()[0]:raise RuntimeError('dataset manifest SHA mismatch')
        for row in json.loads(mp.read_text())['files']:
            p=ds/row['path']
            if p.stat().st_size!=row['bytes'] or tg.science.base.sha256_file(p)!=row['sha256']:raise RuntimeError('sealed chunk mismatch')
        v=tg.abc.fullband.verify(ds,phase['duration_seconds'])
        tg.science.base.write_json_new(self.evidence/f'phase_{phase["index"]:02d}_numeric_verification.json',v)
        if v['status']!='PASS':raise RuntimeError('numeric verification failed')
    def independent_verify(self):
        self.state['verification_status']='running';self.save();self.compare_segments()
        self.state['verification_status']='PASS';self.save()
    def compare_segments(self):
        rows=[]
        for r in range(3):
            phases=self.phases[r*3:r*3+3]
            old=load_rho(self.args.measurement_root/phases[0]['scan_id'],60)[1]
            new=load_rho(self.args.measurement_root/phases[1]['scan_id'],60)[1]
            z=self.args.measurement_root/phases[2]['scan_id']/'xcorr.zarr';minutes=[];powers=[]
            for m in range(9):
                v=np.zeros((28,4096),complex);p=np.zeros((8,4096));n=np.zeros(4096)
                for sec in range(m*60,(m+1)*60):
                    weights=np.fromfile(z/'n_valid'/f'{sec}.0',dtype='<u8');assert len(weights)==16 and np.all(weights>0)
                    for b in range(16):
                        sl=slice(b*256,(b+1)*256);w=weights[b]
                        v[:,sl]+=np.fromfile(z/'mean_cross_visibility_count2'/f'{sec}.0.{b}',dtype='<c16').reshape(28,256)*w
                        p[:,sl]+=np.fromfile(z/'mean_auto_power_count2'/f'{sec}.0.{b}',dtype='<f8').reshape(8,256)*w;n[sl]+=w
                v/=n;p/=n;minutes.append(v);powers.append(p)
                for policy,bg in [('none',0),('old',old),('new',new)]:
                    residual=v-bg
                    rows.append(dict(round=r+1,test_minute=m+1,policy=policy,**score(v,bg,p),focus=[dict(pair=list(pair),bin=k,raw_count2=float(abs(v[j,k])),residual_count2=float(abs(residual[j,k])),phase_deg=float(np.angle(residual[j,k],deg=True))) for j,pair in enumerate(PAIRS) for k in (3073,3182,3328)]))
            np.savez_compressed(self.evidence/f'round{r+1}_templates_test.npz',old=old,new=new,visibility=np.asarray(minutes),power=np.asarray(powers))
        tg.science.base.write_json_new(self.evidence/'reset_background_comparison.json',dict(rows=rows,pairs=PAIRS,definition='Per-minute weighted complex means, subtract fixed pre/post-reset templates before magnitude.',limitations=['Three sequential resets, not cold boots.','New reference is closer in time than old; previous fixed-state evidence provides context but not randomized control.','No claim of lower Allan variance or verified weak sky sensitivity.']))
def main():
    args=tg.science.parse_args()
    if args.dry_run:print(json.dumps(plan(args.queue_id),indent=2));return 0
    with args.lock.open('a+b') as lock:
        fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        return ResetQueue(args,json.loads(args.template.read_text())).run()
if __name__=='__main__':sys.exit(main())
