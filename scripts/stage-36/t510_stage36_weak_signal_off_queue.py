#!/usr/bin/env python3
"""TG OFF splitter reference: first60s training + next60s untouched validation."""
import fcntl,json,sys
from pathlib import Path
import numpy as np
from t510_stage36_background_lifetime_queue import Lifetime,tg
from t510_stage36_background_grid import score
from t510_stage36_tile_analyze import PAIRS

def plan(qid):
    return [dict(index=0,kind='xcorr',label='off-reference',group='WEAK_OFF',segment=1,scan='WEAK_SIGNAL',position='scan',
        mode='spec_only',duration_seconds=120,scan_id=qid+'-off-120s',status='pending')]
class OffReference(Lifetime):
    def __init__(self,args,template):
        super().__init__(args,template);self.phases=plan(args.queue_id)
        self.context.update(rf_inputs='TG OFF via splitter to ADC0/2; other six independent50ohm; operator confirmed',
            interpretation='Weak common-signal experiment OFF reference; ADC0/2 are not independent loads',
            intervention='none; no Reset/MTS/DSA/configuration changes',tg_requested_level_dbm=None)
        self.state.update(phases=self.phases,physical_context=self.context,experiment=dict(
            sequence=['preflight','120s TG OFF','full verification','first60s template and next60s OFF validation','stop and mute'],
            training_seconds=60,validation_seconds=60,followup='Await operator TG level/ON instruction after verified OFF result',
            no_automatic_tg_on=True,source_frequency_mhz=130.078125,
            limitations=['OFF path includes splitter and powered source with TG disabled.','Do not apply independent50ohm template to this new wiring.']))
    def preflight(self):
        preparation=Path(__file__).resolve().parents[3]/'preparation'
        for name in ('preflight-probe.json','interrupt-baseline.json'):
            value=json.loads((preparation/name).read_text())
            tg.science.base.write_json_new(self.evidence/name,value)
            if name=='interrupt-baseline.json' and not value.get('ok'):raise RuntimeError('interrupt baseline failed')
        super().preflight()
    def compare_segments(self):
        z=self.args.measurement_root/self.phases[0]['scan_id']/'xcorr.zarr';vs=[];ps=[]
        for m in range(2):
            v=np.zeros((28,4096),complex);p=np.zeros((8,4096));n=np.zeros(4096)
            for sec in range(m*60,(m+1)*60):
                w=np.fromfile(z/'n_valid'/f'{sec}.0',dtype='<u8');assert len(w)==16 and np.all(w>0)
                for b in range(16):
                    sl=slice(b*256,(b+1)*256)
                    v[:,sl]+=np.fromfile(z/'mean_cross_visibility_count2'/f'{sec}.0.{b}',dtype='<c16').reshape(28,256)*w[b]
                    p[:,sl]+=np.fromfile(z/'mean_auto_power_count2'/f'{sec}.0.{b}',dtype='<f8').reshape(8,256)*w[b];n[sl]+=w[b]
            vs.append(v/n);ps.append(p/n)
        np.savez_compressed(self.evidence/'off_template_validation.npz',background=vs[0],validation=vs[1],training_power=ps[0],validation_power=ps[1])
        j=PAIRS.index((0,2));focus=[]
        for k in (3073,3182,3200,3201,3202,3328):
            b,v=vs[0][j,k],vs[1][j,k]
            focus.append(dict(bin=k,background=[float(b.real),float(b.imag)],validation=[float(v.real),float(v.imag)],residual_count2=float(abs(v-b)),power0=float(ps[1][0,k]),power2=float(ps[1][2,k])))
        tg.science.base.write_json_new(self.evidence/'off_reference_summary.json',dict(pair=[0,2],focus=focus,
            none=score(vs[1],0,ps[1]),corrected=score(vs[1],vs[0],ps[1]),
            interpretation='Fixed first60s template evaluated on next60s; use this sealed template for later ON data, no ON refit.'))
def main():
    args=tg.science.parse_args()
    if args.dry_run:print(json.dumps(plan(args.queue_id),indent=2));return 0
    with args.lock.open('a+b') as lock:
        fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        return OffReference(args,json.loads(args.template.read_text())).run()
if __name__=='__main__':sys.exit(main())
