#!/usr/bin/env python3
"""TG-off control in round02 state; qualify before preparing round03."""
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import numpy as np
import t510_stage36_tg_repeat_queue as repeat
from t510_stage36_tile_analyze import load_rho, PAIRS
tg = repeat.tg


class OffQueue(repeat.RepeatQueue):
    def __init__(self,args,template):
        super().__init__(args,template)
        self.context.update(tg_on_operator_confirmed=False,tg_off_operator_confirmed=True,
            intervention='TG OFF control in round02 state; no reset during capture',
            interpretation='TG off; ADC0/2 still coupled through splitter, not independent terminations')
        self.state['experiment'].update(sequence=['60s TG OFF control','verification and ON/OFF analysis',
            'safe stop','round03 ADC initialization and MTS','interrupt baseline check','await operator TG ON'],
            source_gate='No source-presence acceptance gate for TG OFF; record tone power change',
            hardware_operations='STOP/START for capture; ADC Reset/prepare/MTS only after verified control')
        self.state['third_round_preparation']='pending'

    def receiver(self,path='/api/state',**kwargs):
        if path=='/api/measure/crosscorrelation' and kwargs.get('method')=='POST':
            meta=kwargs['body']['metadata']
            meta.update({k:v if isinstance(v,str) else json.dumps(v) for k,v in self.context.items()})
            meta['physical_input']=self.context['rf_inputs']+'; TG OFF confirmed'
            return tg.abc.ABC.receiver(self,path,**kwargs)
        return super().receiver(path,**kwargs)

    def preflight(self):
        self.on_root=self.args.measurement_root/'stage36-tg-repeat-20260911-round02-queue'
        state=json.loads((self.on_root/'queue_state.json').read_text())
        if state['status']!='completed' or state['verification_status']!='PASS':
            raise RuntimeError('round02 ON control not qualified')
        reference=json.loads((self.on_root/'evidence/phase_00_board_after.json').read_text())
        if tg.abc.initialization_identity(reference)!=tg.abc.initialization_identity(self.board()):
            raise RuntimeError('round02 initialization identity changed before OFF control')
        super().preflight()

    def run_phase(self,phase):
        # Retain capture/integrity/headroom and DSA checks; no TG-on tone gate.
        tg.science.Queue.run_phase(self,phase)
        self.probe(f"phase_{phase['index']:02d}_dsa_after.json")

    def compare_segments(self):
        dataset=self.args.measurement_root/self.phases[0]['scan_id']
        off,visibility,power=load_rho(dataset,60)
        path=self.on_root/'evidence/phase_00_tone.npz'
        with np.load(path) as on:
            rows=[]
            for index,pair in enumerate(PAIRS):
                for k in (3073,3182,3201,3328):
                    rows.append(dict(pair=list(pair),bin=k,on_rho_pct=float(abs(on['rho_pct'][index,k])),
                        off_rho_pct=float(abs(off[index,k])),on_phase_deg=float(np.angle(on['rho_pct'][index,k],deg=True)),
                        off_phase_deg=float(np.angle(off[index,k],deg=True))))
            result=dict(rows=rows,tone_power_off_over_on_db_by_adc=(10*np.log10(power[:,3201]/on['power_count2'][:,3201])).tolist(),
                source_sha256=tg.science.base.sha256_file(path),
                limitation='Sequential ON/OFF comparison; time drift not excluded. ADC0/2 remain connected to splitter.')
        np.savez_compressed(self.evidence/'off_fullband.npz',rho_pct=off,visibility_count2=visibility,power_count2=power)
        tg.science.base.write_json_new(self.evidence/'on_off_comparison.json',result)

    def prepare_call(self,helper,action,name):
        env=dict(os.environ,T510_INIT_HELPER='/home/xilinx/t510-stage36-tg-repeat03/'+helper)
        p=subprocess.run(['/usr/bin/python3',str(Path(__file__).with_name('t510_stage36_init_transport.py')),action],
            env=env,capture_output=True,text=True,timeout=180)
        (self.evidence/(name+'.stdout')).write_text(p.stdout)
        (self.evidence/(name+'.stderr')).write_text(p.stderr)
        value=json.loads(p.stdout)
        tg.science.base.write_json_new(self.evidence/(name+'.json'),value)
        if p.returncode or value.get('ok') is not True:raise RuntimeError('round03 preparation failed: '+name)
        return value

    def independent_verify(self):
        super().independent_verify()
        errors=self.safe_finalize(failed=False)
        if errors:raise RuntimeError(str(errors))
        self.state['third_round_preparation']='running';self.save()
        result=self.prepare_call('t510_stage36_tg_dsa_probe.py','ADC','round03-adc-initialize')
        if result['tg_helper_sha256']!=tg.science.base.sha256_file(Path(__file__).with_name('t510_stage36_tg_dsa_probe.py')):
            raise RuntimeError('round03 DSA helper identity mismatch')
        self.prepare_call('t510_stage36_tg_clear_errors.py','clear_once','round03-interrupt-baseline')
        self.probe('round03_ready_monitor.json')
        self.state['third_round_preparation']='PASS_awaiting_operator_TG_ON';self.save()


def main():
    args=tg.science.parse_args()
    if args.dry_run:
        print(json.dumps(dict(phases=repeat.plan(args.queue_id),after_verification='round03 ADC initialization, then wait for TG ON'),indent=2));return 0
    with args.lock.open('a+b') as lock:
        fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        return OffQueue(args,json.loads(args.template.read_text())).run()


if __name__=='__main__':sys.exit(main())
