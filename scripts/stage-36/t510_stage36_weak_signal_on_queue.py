#!/usr/bin/env python3
"""Known -20dBm common-tone anchor; apply sealed OFF template without ON refit."""
import fcntl,json,sys
from pathlib import Path
import numpy as np
import t510_stage36_tg_queue as tg
from t510_stage36_tile_analyze import PAIRS
OFF_ID='stage36-weak-off-20260912'

def compare(on,background):
    residual=on-background
    return dict(raw_amplitude_count2=float(abs(on)),corrected_amplitude_count2=float(abs(residual)),
        raw_phase_deg=float(np.angle(on,deg=True)),corrected_phase_deg=float(np.angle(residual,deg=True)) if abs(residual)>0 else None,
        correction_vector_count2=float(abs(background)),
        corrected_over_raw=float(abs(residual)/abs(on)) if abs(on)>0 else None)
class OnReference(tg.TGQueue):
    def __init__(self,args,template):
        super().__init__(args,template)
        self.context.update(tg_off_operator_confirmed=False,
            interpretation='Known common-signal anchor; OFF-template subtraction, not yet a weak-signal sensitivity claim')
        self.state['physical_context']=self.context
        self.state['experiment'].update(background_source=OFF_ID,background_fit='first60s OFF only, fixed; never refit to ON',
            reference_level='operator confirmed -20dBm; not calibrated received power')
    def preflight(self):
        q=self.args.measurement_root/(OFF_ID+'-queue');s=json.loads((q/'queue_state.json').read_text())
        if s['status']!='completed' or s['verification_status']!='PASS':raise RuntimeError('OFF predecessor not PASS')
        m=q/'queue_manifest.json'
        if tg.science.base.sha256_file(m)!=(q/'queue_manifest.sha256').read_text().split()[0]:raise RuntimeError('OFF manifest SHA mismatch')
        files={x['path']:x for x in json.loads(m.read_text())['files']}
        self.off=q/'evidence/off_template_validation.npz';ref=q/'evidence/phase_00_board_after.json'
        for path in (self.off,ref):
            if tg.science.base.sha256_file(path)!=files[str(path.relative_to(q))]['sha256']:raise RuntimeError('OFF source file SHA mismatch')
        self.initial=tg.abc.initialization_identity(json.loads(ref.read_text()))
        if self.initial!=tg.abc.initialization_identity(self.board()):raise RuntimeError('hardware initialization changed since OFF')
        tg.science.base.write_json_new(self.evidence/'off_template_identity.json',dict(path=str(self.off),sha256=tg.science.base.sha256_file(self.off),queue_manifest_sha256=tg.science.base.sha256_file(m)))
        super().preflight()
    def run_phase(self,phase):
        super().run_phase(phase)
        if self.initial!=tg.abc.initialization_identity(self.board()):raise RuntimeError('ON identity differs from OFF')
    def compare_segments(self):
        super().compare_segments()
        with np.load(self.off) as z:background=z['background'].copy();off_validation=z['validation'].copy()
        rows=[]
        for phase in self.phases:
            path=self.evidence/f"phase_{phase['index']:02d}_tone.npz"
            with np.load(path) as z:v=z['visibility_count2'].copy();p=z['power_count2'].copy()
            corrected=v-background
            np.savez_compressed(self.evidence/(phase['label']+'-off-corrected.npz'),raw_visibility=v,corrected_visibility=corrected,background=background,power=p)
            for j,pair in enumerate(PAIRS):
                for k in (3073,3182,3200,3201,3202,3328):
                    rows.append(dict(phase=phase['label'],pair=list(pair),bin=k,**compare(v[j,k],background[j,k]),
                        raw_rho_pct=float(100*abs(v[j,k])/np.sqrt(p[pair[0],k]*p[pair[1],k])),
                        corrected_normalized_pct=float(100*abs(corrected[j,k])/np.sqrt(p[pair[0],k]*p[pair[1],k])),
                        off_validation_residual_count2=float(abs(off_validation[j,k]-background[j,k]))))
        tg.science.base.write_json_new(self.evidence/'on_off_correction.json',dict(rows=rows,
            definition='Subtract sealed first60s OFF complex template; retain ON powers for normalization.',
            limitations=['Strong reference only; does not establish weak-signal recovery or absolute amplitude calibration.',
                'Sequential OFF/ON, drift remains. Need subsequent OFF control.',
                'Corrected normalized residual is not constrained to <=100 percent like a raw correlation coefficient.']))
def main():
    args=tg.science.parse_args()
    if args.dry_run:print(json.dumps(tg.plan(args.queue_id),indent=2));return 0
    with args.lock.open('a+b') as lock:
        fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        return OnReference(args,json.loads(args.template.read_text())).run()
if __name__=='__main__':sys.exit(main())
