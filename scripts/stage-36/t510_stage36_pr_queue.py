#!/usr/bin/env python3
"""Two short gates, then bracketed prepare-vs-reset experiment; one fail-stop queue."""
import fcntl
import json
from pathlib import Path
import sys
import t510_stage36_init_queue as init
science = init.science

def plan(queue_id):
    actions=[('P',0,10,True),('R',0,10,True)]
    counts={g:0 for g in 'SPR'}
    for group in 'SPSRSRSPSPSRS':
        counts[group]+=1
        actions.append((group,counts[group],100,False))
    return [dict(index=i,kind='xcorr',label=('gate-' if gate else '')+f'{g}-{n:02d}',
        group=g,segment=n,scan=g,position='scan',mode='spec_only',duration_seconds=seconds,
        short_gate=gate,scan_id=f'{queue_id}-'+('gate-' if gate else '')+f'{g.lower()}{n:02d}-{seconds}s',status='pending')
        for i,(g,n,seconds,gate) in enumerate(actions)]

class PRQueue(init.InitQueue):
    def __init__(self,args,template):
        super().__init__(args,template)
        self.phases=plan(args.queue_id)
        self.state.update(phases=self.phases,products=['fullband_100ms_and_1s_visibility_auto_28pairs','PR_paired_comparison'],
            experiment={'P':'same production prepare without tile Reset; includes MTS/NCO/QMC/PL settings',
                'R':'same prepare plus eight RFDC tile Reset calls', 'S':'STOP/START only',
                'short_gates':'10s P then 10s R, independently verified before proceeding; conditioning, excluded from science comparison',
                'order':[p['label'] for p in self.phases], 'gap_target_seconds':init.GAP_SECONDS,
                'gap_anchor':'previous STOP return to arm-ready; arm then immediate START',
                'replicates_per_intervention':3,'control_scans':7,
                'limitations':'Three repetitions, inherited state/no washout; thermal/time effects not isolated; no known common input; startup guard retained.',
                'analysis':'100s complex normalized visibility differences, all 28 pairs and three preset frequencies; preserve fullband 100ms'})

    def preflight(self):
        super().preflight()
        science.base.write_json_new(self.evidence/'pr_implementation.json',{
            'runner_sha256':science.base.sha256_file(Path(__file__)), 'experiment':self.state['experiment']})

    def run_phase(self,phase):
        super().run_phase(phase)
        if phase['short_gate']:
            result=init.abc.fullband.verify(self.args.measurement_root/phase['scan_id'],phase['duration_seconds'])
            science.base.write_json_new(self.evidence/f"phase_{phase['index']:02d}_short_gate_verification.json",result)
            if result['status']!='PASS':raise RuntimeError(f"short gate failed: {phase['label']}")
            self.event('short_gate_pass',phase=phase['label'])

    def compare_segments(self):
        all_phases=self.phases
        try:
            self.phases=[p for p in all_phases if not p['short_gate']]
            super().compare_segments()
        finally:
            self.phases=all_phases

def main():
    args=science.parse_args()
    if args.dry_run:
        p=plan(args.queue_id)
        print(json.dumps({'phases':p,'formal_seconds':1300,'gate_seconds':20,'gap_seconds':init.GAP_SECONDS},indent=2));return 0
    args.lock.parent.mkdir(parents=True,exist_ok=True)
    with args.lock.open('a+b') as lock:
        fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        return PRQueue(args,json.loads(args.template.read_text())).run()
if __name__=='__main__':sys.exit(main())
