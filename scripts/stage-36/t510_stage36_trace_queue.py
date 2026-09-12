#!/usr/bin/env python3
"""Trace cross-tile changes across Reset, prepare, and MTS boundaries."""
import fcntl
import json
from pathlib import Path
import sys
import t510_stage36_pr_queue as pr
science=pr.science

def plan(queue_id):
    actions=[(g,0,10,True) for g in ('T0','M','P')]
    sequence=['S']
    for order in [('T0','M','P'),('M','P','T0'),('P','T0','M')]:
        for g in order:sequence += [g,'S']
    counts={g:0 for g in ('T0','M','P','S')}
    for g in sequence:
        counts[g]+=1;actions.append((g,counts[g],100,False))
    return [dict(index=i,kind='xcorr',label=('gate-' if gate else '')+f'{g}-{n:02d}',
        group=g,segment=n,scan=g,position='scan',mode='spec_only',duration_seconds=seconds,
        short_gate=gate,scan_id=f'{queue_id}-'+('gate-' if gate else '')+f'{g.lower()}{n:02d}-{seconds}s',status='pending')
        for i,(g,n,seconds,gate) in enumerate(actions)]

class TraceQueue(pr.PRQueue):
    def __init__(self,args,template):
        super().__init__(args,template)
        self.phases=plan(args.queue_id)
        self.state.update(phases=self.phases,products=['fullband_100ms_and_1s_visibility_auto_28pairs','reset_boundary_trace_and_spatial_comparison'],
            experiment={'T0':'reset ADC tile0 only (ADC0/1), then common production prepare',
                'M':'MTS only, without tile Reset or production prepare',
                'P':'same prepare without any tile Reset',
                'S':'STOP/START only',
                'short_gates':'10s T0/M/P, each independently verified before continuing; excluded from science comparison',
                'order':[p['label'] for p in self.phases], 'gap_target_seconds':pr.init.GAP_SECONDS,
                'gap_anchor':'previous STOP return to arm-ready; arm then immediate START',
                'replicates_per_intervention':3,'control_scans':10,
                'limitations':'Preservation refers to tile Reset only: common prepare still configures both ADC/DAC. Three repetitions, inherited state/no washout; thermal/time effects not isolated; no known common input; startup guard retained.',
                'analysis':'100s weighted complex rho; all4096 bins and three preset bins; preassigned 13 involved/15 untouched pairs for each target; P/M analyzed using tile0 target partition; focus on ADC2/3 cross-tile event'})

    def compare_segments(self):
        super().compare_segments()
        from t510_stage36_tile_analyze import analyze
        analyze(self.args.measurement_root, [p for p in self.phases if not p["short_gate"]], self.evidence, control_targets=('T0',))
        from t510_stage36_trace_analyze import analyze_boundaries
        analyze_boundaries(self.evidence, self.phases)

    def intervention(self, action):
        result = super().intervention(action)
        if action != 'probe':
            from t510_stage36_trace_analyze import validate_trace
            validate_trace(action, result['boundary_trace'])
        return result

    def preflight(self):
        super().preflight()
        helper = Path(__file__).with_name('t510_stage36_init_probe.py')
        probe = json.loads((self.evidence/'init_probe.json').read_text())
        if probe['helper_sha256'] != science.base.sha256_file(helper):
            raise RuntimeError('board experiment helper identity mismatch')
        trace_helper = Path(__file__).with_name('t510_stage36_trace_probe.py')
        if probe['trace_helper_sha256'] != science.base.sha256_file(trace_helper):
            raise RuntimeError('trace helper identity mismatch')
        science.base.write_json_new(self.evidence/'trace_implementation.json',{
            'runner_sha256':science.base.sha256_file(Path(__file__)),
            'analyzer_sha256':science.base.sha256_file(Path(__file__).with_name('t510_stage36_tile_analyze.py')),
            'trace_helper_sha256':science.base.sha256_file(trace_helper),
            'experiment':self.state['experiment']})

def main():
    args=science.parse_args()
    if args.dry_run:
        print(json.dumps({'phases':plan(args.queue_id),'formal_seconds':1900,'gate_seconds':30,'gap_seconds':pr.init.GAP_SECONDS},indent=2));return 0
    args.lock.parent.mkdir(parents=True,exist_ok=True)
    with args.lock.open('a+b') as lock:
        fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        return TraceQueue(args,json.loads(args.template.read_text())).run()
if __name__=='__main__':sys.exit(main())
