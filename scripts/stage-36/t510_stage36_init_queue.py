#!/usr/bin/env python3
"""Interleaved intervention/control replication using the verified ABC pipeline."""
import fcntl
import json
from pathlib import Path
import subprocess
import sys
import time
import t510_stage36_abc_queue as abc
science = abc.science
GAP_SECONDS = 180.0  # Previous STOP return to receiver arm, before its watchdog starts.


def plan(queue_id):
    actions = ['S']
    # Rotation balances position within each round. Controls bracket each intervention.
    for order in [('M','R','F'), ('R','F','M'), ('F','M','R')]:
        for action in order:
            actions += [action, 'S']
    counts = {}; phases = []
    for index, action in enumerate(actions):
        counts[action] = counts.get(action, 0)+1
        segment = counts[action]
        phases.append(dict(index=index, kind='xcorr', label=f'{action}-{segment:02d}',
            group=action, segment=segment, scan=action, position='scan', mode='spec_only',
            duration_seconds=100, scan_id=f'{queue_id}-{action.lower()}{segment:02d}-100s', status='pending'))
    return phases


class InitQueue(abc.ABC):
    def __init__(self,args,template):
        super().__init__(args,template)
        self.phases = plan(args.queue_id)
        self.state.update(phases=self.phases, products=['fullband_100ms_and_1s_visibility_auto_28pairs',
             'interleaved_initialization_comparison'], experiment={
             'S':'STOP/START control; no initialization',
             'M':'MTS only including necessary SYSREF switching; no explicit RFDC reset or mixer programming',
             'R':'RFDC tile reset plus production prepare (mixer/NCO/QMC/MTS); preserve LMK profile and PL',
             'F':'production clock restore: LMK rewrite, same PL reload, RFDC reset and prepare/MTS',
             'order':[p['group'] for p in self.phases], 'gap_target_seconds':GAP_SECONDS,
             'gap_anchor':'previous STOP verified return to receiver arm request; START immediately follows arm',
             'replicates_per_intervention':3, 'control_scans':10,
             'limitations':'No washout; controls inherit previous state. Order rotated, not randomized. No known input signal, so low correlation is not proof of correct sky coherence. Startup guard unchanged (~5.225s minimum).',
             'analysis':'100s complex means, paired before/after differences and intervention-to-following-control differences; all 28 pairs, default 3 bins; preserve fullband.'})

    def intervention(self, action):
        completed = subprocess.run(['/usr/bin/python3', str(Path(__file__).with_name('t510_stage36_init_transport.py')),action],
                                   capture_output=True,text=True,timeout=180)
        if completed.returncode:
            raise RuntimeError(f'{action} helper failed: {completed.stdout} {completed.stderr}')
        result=json.loads(completed.stdout)
        if result.get('ok') is not True:raise RuntimeError(f'{action} failed: {result}')
        return result

    def preflight(self):
        super().preflight()
        science.base.write_json_new(self.evidence/'init_probe.json', self.intervention('probe'))
        science.base.write_json_new(self.evidence/'init_implementation.json', {
            'files':{p.name:science.base.sha256_file(p) for p in [Path(__file__),
                Path(__file__).with_name('t510_stage36_init_transport.py'),
                Path(__file__).with_name('t510_stage36_init_probe.py')]}, 'experiment':self.state['experiment']})

    def ensure_mode(self,phase):
        previous_stop = self.last_stop_monotonic
        science.Queue.ensure_mode(self,phase)
        # Repeated safety STOP must not move the previous capture-stop anchor.
        if previous_stop is not None:
            self.last_stop_monotonic = previous_stop
        before=self.board()
        science.base.write_json_new(self.evidence/f"phase_{phase['index']:02d}_before_intervention.json",before)
        group=phase['group']
        if group in ('M','P','R','ADC','DAC','T0','T3'):
            result=self.intervention(group)
        elif group=='F':
            result=self.board(abc.CLOCK_RESTORE,method='POST',body={'expected_board_id':1,
                                'receiver_stream_accepting':False},timeout=180)
            if result.get('restored') is not True:raise RuntimeError('full restore failed')
        else:result={'action':'S','ok':True}
        science.base.write_json_new(self.evidence/f"phase_{phase['index']:02d}_intervention.json",result)
        after=self.board()
        errors=science.identity_errors(after,mode='spec_only',center_mhz=self.args.center_mhz)
        if errors:raise RuntimeError(f'post-intervention identity: {errors}')
        if after.get('streaming') or any(ch['enabled'] for ch in after['dac']['channels']):
            raise RuntimeError('unexpected stream/DAC enabled')
        if group=='S' and abc.initialization_identity(before)!=abc.initialization_identity(after):
            raise RuntimeError('control initialization identity changed')
        if group!='S' and before['mts']['captured_at_unix_ms']==after['mts']['captured_at_unix_ms']:
            raise RuntimeError('intervention did not publish new MTS evidence')
        science.base.write_json_new(self.evidence/f"phase_{phase['index']:02d}_prepared_board.json",after)
        self.save()

    def _begin_common(self, phase):
        snapshots = science.Queue._begin_common(self, phase)
        # run_xcorr arms the receiver immediately after this method returns.
        # The receiver watchdog includes the armed period: never wait inside start_stream.
        if phase['index']:
            if self.last_stop_monotonic is None:
                raise RuntimeError('missing previous STOP anchor before receiver arm')
            elapsed = time.monotonic() - self.last_stop_monotonic
            if elapsed > GAP_SECONDS:
                raise RuntimeError(f'preparation exceeded pre-arm gap: {elapsed:.3f}s > {GAP_SECONDS}')
            self.event('matched_gap_wait_before_arm', phase=phase['label'],
                       remaining_seconds=GAP_SECONDS-elapsed)
            time.sleep(GAP_SECONDS-elapsed)
            phase['stop_to_arm_ready_seconds'] = time.monotonic()-self.last_stop_monotonic
        phase['arm_ready_unix_ms'] = science.base.unix_ms()
        self.save()
        return snapshots

    def start_stream(self, phase):
        # Deliberately bypass ABC.start_stream, which waits AFTER receiver arm.
        if phase['index']:
            phase['stop_to_start_request_seconds'] = time.monotonic()-self.last_stop_monotonic
        phase['start_request_unix_ms'] = science.base.unix_ms()
        self.save()
        return science.Queue.start_stream(self, phase)

    def compare_segments(self):
        super().compare_segments()
        source=json.loads((self.evidence/'abc_segment_comparison.json').read_text())
        rows=source['rows']; keyed={(r['scan_id'],tuple(r['pair']),r['global_bin']):r for r in rows}
        changes=[]
        for i,p in enumerate(self.phases):
            if p['group']=='S':continue
            for row in (r for r in rows if r['scan_id']==p['scan_id']):
                def rho(r):
                    return complex(r['real_count2'],r['imag_count2'])/(r['power_a_count2']*r['power_b_count2'])**.5*100
                key=(tuple(row['pair']),row['global_bin'])
                pre=keyed[(self.phases[i-1]['scan_id'],*key)]; post=keyed[(self.phases[i+1]['scan_id'],*key)]
                jump=rho(row)-rho(pre); drift=rho(post)-rho(row)
                changes.append(dict(group=p['group'],segment=p['segment'],pair=row['pair'],global_bin=row['global_bin'],
                    pre_rho_pct=abs(rho(pre)), intervention_rho_pct=abs(rho(row)),post_rho_pct=abs(rho(post)),
                    jump_real_pp=jump.real,jump_imag_pp=jump.imag,jump_abs_pp=abs(jump),following_control_change_abs_pp=abs(drift)))
        science.base.write_json_new(self.evidence/'initialization_paired_comparison.json', {'rows':changes,
            'definition':'complex rho differences in percentage points, not difference of magnitudes',
            'limitations':self.state['experiment']['limitations']})
        (self.evidence/'ABC_README.md').write_text('# Interleaved initialization comparison\n\nSee init_implementation.json and initialization_paired_comparison.json.\nControls inherit the preceding state; they are not resets to a common baseline.\n')


def main():
    args=science.parse_args()
    if args.dry_run:
        print(json.dumps({'phases':plan(args.queue_id),'science_seconds':1900,'gap_seconds':GAP_SECONDS},indent=2));return 0
    args.lock.parent.mkdir(parents=True,exist_ok=True)
    with args.lock.open('a+b') as lock:
        fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        return InitQueue(args,json.loads(args.template.read_text())).run()

if __name__=='__main__':sys.exit(main())
