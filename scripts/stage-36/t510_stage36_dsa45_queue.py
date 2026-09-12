#!/usr/bin/env python3
"""Seven TG-off DSA conditions, fixed initialization, independent verification."""
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import numpy as np
import t510_stage36_tg_queue as tg
from t510_stage36_tile_analyze import load_rho, PAIRS

SETTINGS={'A':(0,0),'B':(10,0),'C':(0,10),'D':(10,10)}
def plan(qid):
    return [dict(index=i,kind='xcorr',label=f'{letter}{i}',group=letter,segment=i+1,scan='DSA45',position='scan',
        mode='spec_only',duration_seconds=60,scan_id=f'{qid}-{letter.lower()}{i}-60s',status='pending')
        for i,letter in enumerate('ABACADA')]

class DSAQueue(tg.TGQueue):
    def __init__(self,args,template):
        super().__init__(args,template)
        self.phases=plan(args.queue_id)
        self.context.update(tg_on_operator_confirmed=False,tg_off_operator_confirmed=True,
            interpretation='TG OFF ADC4/5 DSA experiment; ADC0/2 still coupled via splitter',
            intervention='DSA45 only; no ADC reset, MTS, configure or digital gain changes')
        self.state.update(phases=self.phases,physical_context=self.context,
            experiment=dict(sequence=list('ABACADA'),seconds_each=60,settings_db=SETTINGS,
                source_gate='none: TG OFF',initialization='round03 held fixed',
                rts='ADC4/5 DisableRTS=1 from first A onward; untouched channels retained',
                completion='last A sets attenuation0; stop and mute; on failure preserve DSA at failure'))

    def control(self,action,name):
        p=subprocess.run(['/usr/bin/python3',str(Path(__file__).with_name('t510_stage36_init_transport.py')),action],
            capture_output=True,text=True,timeout=60)
        (self.evidence/(name+'.stdout')).write_text(p.stdout)
        (self.evidence/(name+'.stderr')).write_text(p.stderr)
        if p.returncode:raise RuntimeError('DSA helper failed: '+p.stdout+p.stderr)
        value=json.loads(p.stdout);tg.science.base.write_json_new(self.evidence/name,value)
        if value.get('ok') is not True or value['helper_sha256']!=tg.science.base.sha256_file(Path(__file__).with_name('t510_stage36_dsa45_probe.py')):
            raise RuntimeError('DSA helper identity mismatch')
        if [r['dsa']['Attenuation'] for r in value['rows']]!=self.context['dsa_db_by_adc']:
            raise RuntimeError('DSA actual/expected mismatch')
        if any(r['adc_error_bits'] for r in value['rows']):raise RuntimeError('RFDC errors present')
        return value

    def probe(self,name):return self.control('probe',name)

    def preflight(self):
        old=self.args.measurement_root/'stage36-tg-repeat-20260911-round03-queue'
        state=json.loads((old/'queue_state.json').read_text())
        if state['status']!='completed' or state['verification_status']!='PASS':raise RuntimeError('round03 not qualified')
        ref=json.loads((old/'evidence/phase_00_board_after.json').read_text())
        self.identity=tg.abc.initialization_identity(ref)
        if self.identity!=tg.abc.initialization_identity(self.board()):raise RuntimeError('round03 state changed')
        super().preflight()

    def ensure_mode(self,phase):
        tg.science.Queue.ensure_mode(self,phase)
        self.context['dsa_db_by_adc']=[20,0,20,0,*SETTINGS[phase['group']],0,0]
        self.control('DSA_'+phase['group'],f"phase_{phase['index']:02d}_dsa_applied.json")
        if self.identity!=tg.abc.initialization_identity(self.board()):raise RuntimeError('initialization changed during DSA intervention')
        self.save()

    def receiver(self,path='/api/state',**kwargs):
        if path=='/api/measure/crosscorrelation' and kwargs.get('method')=='POST':
            meta=kwargs['body']['metadata']
            meta.update({k:v if isinstance(v,str) else json.dumps(v) for k,v in self.context.items()})
            meta['physical_input']=self.context['rf_inputs']+'; TG OFF confirmed'
            return tg.abc.ABC.receiver(self,path,**kwargs)
        return super().receiver(path,**kwargs)

    def run_phase(self,phase):
        tg.science.Queue.run_phase(self,phase)
        self.probe(f"phase_{phase['index']:02d}_dsa_after.json")
        if self.identity!=tg.abc.initialization_identity(self.board()):raise RuntimeError('initialization identity changed during capture')

    def compare_segments(self):
        rows=[];arrays=[]
        for phase in self.phases:
            rho,v,p=load_rho(self.args.measurement_root/phase['scan_id'],60)
            arrays.append((rho,v,p))
            np.savez_compressed(self.evidence/(phase['label']+'-fullband.npz'),rho_pct=rho,visibility_count2=v,power_count2=p)
            for j,pair in enumerate(PAIRS):
                for k in (3073,3182,3201,3328):
                    rows.append(dict(condition=phase['label'],dsa45_db=SETTINGS[phase['group']],pair=list(pair),bin=k,
                        real_count2=float(v[j,k].real),imag_count2=float(v[j,k].imag),amplitude_count2=float(abs(v[j,k])),
                        phase_deg=float(np.angle(v[j,k],deg=True)),rho_pct=float(abs(rho[j,k])),
                        power_a_count2=float(p[pair[0],k]),power_b_count2=float(p[pair[1],k])))
        j=PAIRS.index((4,5));contrasts=[]
        for i in (1,3,5):
            for k in (3073,3182,3328):
                a=arrays[i-1][1][j,k];b=arrays[i][1][j,k];c=arrays[i+1][1][j,k]
                contrasts.append(dict(condition=self.phases[i]['label'],bin=k,
                    intervention_complex_change_count2=float(abs(b-a)),return_A_complex_change_count2=float(abs(c-a)),
                    visibility_amplitude_over_previous_A=float(abs(b)/abs(a)) if abs(a)>0 else None))
        tg.science.base.write_json_new(self.evidence/'dsa45_comparison.json',dict(rows=rows,contrasts=contrasts,
            limitation='Descriptive A/B/A comparison; DSA can change analog noise or calibration behavior. No simple location proof from rho alone.'))

def main():
    args=tg.science.parse_args()
    if args.dry_run:print(json.dumps(plan(args.queue_id),indent=2));return 0
    with args.lock.open('a+b') as lock:
        fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        return DSAQueue(args,json.loads(args.template.read_text())).run()

if __name__=='__main__':sys.exit(main())
