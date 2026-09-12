#!/usr/bin/env python3
"""Isolate ADC/DAC resets with same prepare, short gates and bracketed repetitions."""
import fcntl
import json
from pathlib import Path
import sys
import t510_stage36_pr_queue as pr
science=pr.science

def plan(queue_id):
    actions=[(g,0,10,True) for g in ('ADC','DAC','R')]
    sequence=['S']
    for order in [('ADC','DAC','R'),('DAC','R','ADC'),('R','ADC','DAC')]:
        for g in order:sequence += [g,'S']
    counts={g:0 for g in ('ADC','DAC','R','S')}
    for g in sequence:
        counts[g]+=1;actions.append((g,counts[g],100,False))
    return [dict(index=i,kind='xcorr',label=('gate-' if gate else '')+f'{g}-{n:02d}',
        group=g,segment=n,scan=g,position='scan',mode='spec_only',duration_seconds=seconds,
        short_gate=gate,scan_id=f'{queue_id}-'+('gate-' if gate else '')+f'{g.lower()}{n:02d}-{seconds}s',status='pending')
        for i,(g,n,seconds,gate) in enumerate(actions)]

class SplitQueue(pr.PRQueue):
    def __init__(self,args,template):
        super().__init__(args,template)
        self.phases=plan(args.queue_id)
        self.state.update(phases=self.phases,products=['fullband_100ms_and_1s_visibility_auto_28pairs','ADC_DAC_reset_paired_comparison'],
            experiment={'ADC':'reset four ADC tiles, preserve DAC tiles, then common production prepare',
                'DAC':'reset four DAC tiles, preserve ADC tiles, then same prepare',
                'R':'reset all four ADC and four DAC tiles, then same prepare; replication comparator',
                'S':'STOP/START only',
                'short_gates':'10s ADC/DAC/R, each independently verified before continuing; excluded from science comparison',
                'order':[p['label'] for p in self.phases], 'gap_target_seconds':pr.init.GAP_SECONDS,
                'gap_anchor':'previous STOP return to arm-ready; arm then immediate START',
                'replicates_per_intervention':3,'control_scans':10,
                'limitations':'Preservation refers to tile Reset only: common prepare still configures both ADC/DAC. Three repetitions, inherited state/no washout; thermal/time effects not isolated; no known common input; startup guard retained.',
                'analysis':'100s complex normalized visibility differences, all 28 pairs and three preset frequencies; preserve fullband 100ms'})

    def preflight(self):
        super().preflight()
        science.base.write_json_new(self.evidence/'adc_dac_implementation.json',{
            'runner_sha256':science.base.sha256_file(Path(__file__)), 'experiment':self.state['experiment']})

def main():
    args=science.parse_args()
    if args.dry_run:
        print(json.dumps({'phases':plan(args.queue_id),'formal_seconds':1900,'gate_seconds':30,'gap_seconds':pr.init.GAP_SECONDS},indent=2));return 0
    args.lock.parent.mkdir(parents=True,exist_ok=True)
    with args.lock.open('a+b') as lock:
        fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        return SplitQueue(args,json.loads(args.template.read_text())).run()
if __name__=='__main__':sys.exit(main())
