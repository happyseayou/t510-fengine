#!/usr/bin/env python3
"""One fixed-state31min capture -> verification -> causal background aging analysis."""
import fcntl,json,sys
from pathlib import Path
import numpy as np
import t510_stage36_tg_queue as tg
from t510_stage36_background_grid import score,smooth
from t510_stage36_tile_analyze import PAIRS
SECONDS=1860

def plan(qid):
    return [dict(index=0,kind='xcorr',label='fixed-state',group='L',segment=1,scan='BACKGROUND',position='scan',
        mode='spec_only',duration_seconds=SECONDS,scan_id=qid+'-fixed-1860s',status='pending')]
class Lifetime(tg.TGQueue):
    def __init__(self,args,template):
        super().__init__(args,template);self.phases=plan(args.queue_id)
        self.context.update(tg_on_operator_confirmed=False,tg_off_operator_confirmed=True,
            rf_inputs='eight independent 50ohm terminations operator confirmed; TG disconnected and OFF',
            interpretation='Reference-input background lifetime; no sky signal',intervention='none: no Reset/MTS/DSA/configure/calibration writes')
        self.state.update(phases=self.phases,physical_context=self.context,experiment=dict(
            sequence=['preflight','1860s uninterrupted capture','full integrity and numeric verification','background aging and causal update comparison','stop and mute'],
            training_seconds=60,validation_minutes=30,update_minutes=[1,5,10,20],
            limitation='One initialization. Reset-transfer experiment remains a separate subsequent campaign; no reset is hidden in this queue.'))
    def receiver(self,path='/api/state',**kwargs):
        if path=='/api/measure/crosscorrelation' and kwargs.get('method')=='POST':
            kwargs['body']['metadata'].update({k:v if isinstance(v,str) else json.dumps(v) for k,v in self.context.items()})
            kwargs['body']['metadata']['physical_input']=self.context['rf_inputs']+'; TG OFF operator confirmed'
            return tg.abc.ABC.receiver(self,path,**kwargs)
        return super().receiver(path,**kwargs)
    def preflight(self):
        self.initial=tg.abc.initialization_identity(self.board())
        super().preflight()
    def run_phase(self,phase):
        tg.science.Queue.run_phase(self,phase)
        self.probe('lifetime_stopped_probe.json')
        if self.initial!=tg.abc.initialization_identity(self.board()):raise RuntimeError('initialization changed during fixed-state capture')
    def compare_segments(self):
        phase=self.phases[0];z=self.args.measurement_root/phase['scan_id']/'xcorr.zarr'
        minutes=[];powers=[]
        for m in range(31):
            v=np.zeros((28,4096),complex);p=np.zeros((8,4096));n=np.zeros(4096)
            for sec in range(m*60,(m+1)*60):
                w=np.fromfile(z/'n_valid'/f'{sec}.0',dtype='<u8');assert len(w)==16 and np.all(w>0)
                for b in range(16):
                    sl=slice(b*256,(b+1)*256)
                    v[:,sl]+=np.fromfile(z/'mean_cross_visibility_count2'/f'{sec}.0.{b}',dtype='<c16').reshape(28,256)*w[b]
                    p[:,sl]+=np.fromfile(z/'mean_auto_power_count2'/f'{sec}.0.{b}',dtype='<f8').reshape(8,256)*w[b]
                    n[sl]+=w[b]
            minutes.append(v/n);powers.append(p/n)
        rows=[]
        for m in range(1,31):
            policies={'none':None,'fixed':0,**{f'update_{period}min':((m-1)//period)*period for period in (1,5,10,20)}}
            for policy,training in policies.items():
                background=0 if training is None else minutes[training]
                rows.append(dict(test_minute=m,policy=policy,training_minute=training,
                    template_age_minutes=None if training is None else m-training,
                    **score(minutes[m],background,powers[m])))
        np.savez_compressed(self.evidence/'minute_fullband.npz',visibility=np.asarray(minutes),power=np.asarray(powers))
        tg.science.base.write_json_new(self.evidence/'background_lifetime.json',dict(rows=rows,pairs=PAIRS,
            definition='Each minute complex mean; all28pairs, bins3072..3328 score. No magnitude subtraction.',
            constraints=['Every template ends before the target minute begins; no future data used.',
                'Rolling reference updates are valid in this all-reference experiment, not permission to subtract sky target means.',
                'No assumed acceptance threshold or independent-time/bin significance; one epoch only.',
                'Compare per-pair outcomes as well as global medians; lower bias is not lower Allan variance.']))
def main():
    args=tg.science.parse_args()
    if args.dry_run:print(json.dumps(plan(args.queue_id),indent=2));return 0
    with args.lock.open('a+b') as lock:
        fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        return Lifetime(args,json.loads(args.template.read_text())).run()
if __name__=='__main__':sys.exit(main())
