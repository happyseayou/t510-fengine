#!/usr/bin/env python3
"""Post-TG OFF control; compare both minutes with the sealed pre-ON template."""
import fcntl,json,sys
import numpy as np
from t510_stage36_weak_signal_off_queue import OffReference,Lifetime,tg,plan,PAIRS,score
OFF='stage36-weak-off-20260912'
ON='stage36-weak-on-m20-20260912'
class PostOff(OffReference):
    def __init__(self,args,template):
        super().__init__(args,template)
        self.state['experiment'].update(sequence=['preflight','120s post-TG OFF','verify','compare both minutes against sealed pre-ON background','stop and mute'],background_source=OFF,on_source=ON,followup='Review background return; do not replace original background with post data')
        self.context['interpretation']='Post-TG OFF return control; original pre-ON template remains fixed'
    def preflight(self):
        for qid in (OFF,ON):
            q=self.args.measurement_root/(qid+'-queue');s=json.loads((q/'queue_state.json').read_text())
            if s['status']!='completed' or s['verification_status']!='PASS':raise RuntimeError('Predecessor not PASS: '+qid)
            m=q/'queue_manifest.json'
            if tg.science.base.sha256_file(m)!=(q/'queue_manifest.sha256').read_text().split()[0]:raise RuntimeError('Predecessor manifest SHA mismatch')
            files={f['path']:f for f in json.loads(m.read_text())['files']}
            names=['evidence/board_final_safe.json']
            if qid==OFF:names+=['evidence/off_template_validation.npz']
            for name in names:
                if tg.science.base.sha256_file(q/name)!=files[name]['sha256']:raise RuntimeError('Predecessor evidence SHA mismatch')
            identity=tg.abc.initialization_identity(json.loads((q/names[0]).read_text()))
            if identity!=tg.abc.initialization_identity(self.board()):raise RuntimeError('Initialization changed since '+qid)
            tg.science.base.write_json_new(self.evidence/(qid+'-identity.json'),dict(queue=qid,manifest_sha256=tg.science.base.sha256_file(m),identity=identity))
        self.original=self.args.measurement_root/(OFF+'-queue/evidence/off_template_validation.npz')
        Lifetime.preflight(self)
    def compare_segments(self):
        super().compare_segments()
        with np.load(self.original) as z:b=z['background'].copy();before=z['validation'].copy()
        with np.load(self.evidence/'off_template_validation.npz') as z:vs=[z['background'].copy(),z['validation'].copy()];ps=[z['training_power'].copy(),z['validation_power'].copy()]
        rows=[]
        for minute,(v,p) in enumerate(zip(vs,ps),1):
            for j,pair in enumerate(PAIRS):
                for k in (3073,3182,3200,3201,3202,3328):
                    rows.append(dict(minute=minute,pair=list(pair),bin=k,post_complex=[float(v[j,k].real),float(v[j,k].imag)],original_background=[float(b[j,k].real),float(b[j,k].imag)],post_residual_count2=float(abs(v[j,k]-b[j,k])),pre_validation_residual_count2=float(abs(before[j,k]-b[j,k]))))
        np.savez_compressed(self.evidence/'post_off_fixed_background.npz',original_background=b,pre_validation=before,post_visibility=vs,post_power=ps,post_residual=np.asarray(vs)-b)
        tg.science.base.write_json_new(self.evidence/'post_off_return.json',dict(rows=rows,minute_scores=[dict(minute=i+1,raw=score(v,0,p),fixed_original=score(v,b,p)) for i,(v,p) in enumerate(zip(vs,ps))],interpretation='Both post minutes are holdouts against pre-ON first60s; no post refit. Sequential comparison does not isolate TG causality from drift.'))
def main():
    args=tg.science.parse_args()
    if args.dry_run:print(json.dumps(plan(args.queue_id),indent=2));return 0
    with args.lock.open('a+b') as lock:
        fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        return PostOff(args,json.loads(args.template.read_text())).run()
if __name__=='__main__':sys.exit(main())
