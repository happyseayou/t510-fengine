#!/usr/bin/env python3
"""Controlled continuous / STOP-START / clock-reinitialization comparison.

Reuse production capture, integrity, fail-stop and sealing primitives. C uses
clock/diagnostic/restore to rewrite the SAME production clock and reload the
same PL, reset RFDC and execute MTS. No fallback, retries or scientific masks.
"""
import fcntl
import itertools
import json
from pathlib import Path
import sys
import time
import numpy as np
import t510_stage36_science_capture_queue as science
import t510_stage35_fullband100_verify as fullband

GAP_SECONDS = 90.0
CLOCK_RESTORE = '/api/v2/clock/diagnostic/restore'

def plan(queue_id):
    return [dict(index=i, kind='xcorr', label=f'{group}-{segment:02d}',
                 group=group, segment=segment, scan=group, position='scan',
                 mode='spec_only', duration_seconds=seconds,
                 scan_id=f'{queue_id}-{group.lower()}{segment:02d}-{seconds}s', status='pending')
            for i,(group,segment,seconds) in enumerate(
                [('A',1,900)]+[(g,n,100) for g in ['B','C'] for n in range(1,10)])]

def initialization_identity(board):
    return {key:board.get(key) for key in ['core_version','profile','digital_scaling','mts']}

class ABC(science.Queue):
    def __init__(self,args,template):
        super().__init__(args,template)
        self.phases=plan(args.queue_id)
        self.last_stop_monotonic=None
        self.state.update(phases=self.phases,products=['fullband_100ms_and_1s_visibility_auto_28pairs',
                          'ABC_100s_segment_comparison'],experiment={
            'A':'one uninterrupted 900 s scan; nine virtual 100 s segments',
            'B':'nine 100 s scans, STOP/START only',
            'C':'nine 100 s scans; production clock rewrite, same PL reload, RFDC reset/MTS before EACH',
            'gap_target_seconds':GAP_SECONDS,'gap_anchor':'previous STOP verified return to next START request',
            'order':'A then B then C; order/temperature confounding remains',
            'receiver_startup_policy':'existing 8192 contiguous frames plus 400000-frame lead (~5.225 s minimum); initial startup guard is not a scientific product',
            'no_claim_of_independent_hardware_states':True})

    def preflight(self):
        super().preflight()
        b=self.board()
        errors=science.identity_errors(b,mode='spec_only',center_mhz=self.args.center_mhz)
        if errors:raise RuntimeError(f'ABC requires preconfigured SPEC: {errors}')
        # Verify C's endpoint exists before committing the full queue; no mutation.
        import urllib.request
        with urllib.request.urlopen(self.args.agent_base+'/api/openapi.json',timeout=10) as f:
            api=json.load(f)
        if CLOCK_RESTORE not in api['paths']:raise RuntimeError('clock restore endpoint absent')
        science.base.write_json_new(self.evidence/'abc_implementation.json',{
            'runner_sha256':science.base.sha256_file(Path(__file__)),
            'verifier_sha256':science.base.sha256_file(Path(fullband.__file__)),
            'experiment':self.state['experiment']})

    def board(self,path='/api/v2/status',**kwargs):
        # Never silently hot-configure B (or other phases) on mismatch.
        if path=='/api/v2/configure':raise RuntimeError('unexpected CONFIGURE in controlled ABC queue')
        result=super().board(path,**kwargs)
        if path=='/api/v2/stop':self.last_stop_monotonic=time.monotonic()
        return result

    def ensure_mode(self,phase):
        before=self.board()
        super().ensure_mode(phase)
        if phase['group']=='C':
            started=science.base.unix_ms()
            result=self.board(CLOCK_RESTORE,method='POST',body={
                'expected_board_id':1,'receiver_stream_accepting':False},timeout=180)
            science.base.write_json_new(self.evidence/f"phase_{phase['index']:02d}_clock_reinitialize.json",result)
            if result.get('restored') is not True:raise RuntimeError('clock restore did not succeed')
            phase['clock_reinitialization_ms']=science.base.unix_ms()-started
        after=self.board()
        errors=science.identity_errors(after,mode='spec_only',center_mhz=self.args.center_mhz)
        if errors:raise RuntimeError(f'ABC pre-start identity: {errors}')
        if after.get('streaming'):raise RuntimeError('unexpected streaming before arm')
        if any(ch['enabled'] for ch in after['dac']['channels']):raise RuntimeError('DAC is enabled')
        if phase['group']!='C' and initialization_identity(before)!=initialization_identity(after):
            raise RuntimeError('A/B initialization identity changed during STOP/START preparation')
        science.base.write_json_new(self.evidence/f"phase_{phase['index']:02d}_prepared_board.json",after)
        self.save()

    def start_stream(self,phase):
        if phase['index']:
            if self.last_stop_monotonic is None:raise RuntimeError('missing stop interval anchor')
            elapsed=time.monotonic()-self.last_stop_monotonic
            if elapsed>GAP_SECONDS:
                raise RuntimeError(f'preparation exceeded matched gap: {elapsed:.3f}s > {GAP_SECONDS}')
            # Receiver is armed, board remains stopped. Record actual timing.
            self.event('matched_gap_wait',phase=phase['label'],remaining_seconds=GAP_SECONDS-elapsed)
            time.sleep(GAP_SECONDS-elapsed)
            phase['stop_to_start_request_seconds']=time.monotonic()-self.last_stop_monotonic
        phase['start_request_unix_ms']=science.base.unix_ms()
        self.save()
        return super().start_stream(phase)

    def independent_verify(self):
        self.state['verification_status']='running';self.save()
        for phase in self.phases:
            dataset=self.args.measurement_root/phase['scan_id']
            mp=dataset/'dataset_manifest.json'
            if science.base.sha256_file(mp)!=(dataset/'dataset_manifest.sha256').read_text().split()[0]:
                raise RuntimeError('manifest SHA mismatch')
            for row in json.loads(mp.read_text())['files']:
                path=dataset/row['path']
                if path.stat().st_size!=row['bytes'] or science.base.sha256_file(path)!=row['sha256']:
                    raise RuntimeError(f'sealed file mismatch: {path}')
            result=fullband.verify(dataset,phase['duration_seconds'])
            science.base.write_json_new(self.evidence/f"phase_{phase['index']:02d}_numeric_verification.json",result)
            if result['status']!='PASS':raise RuntimeError('independent numeric verification failed')
        self.compare_segments()
        self.state['verification_status']='PASS';self.save()

    def compare_segments(self):
        # Every second, all 28 pairs, three prespecified frequencies. Fullband
        # 100 ms files remain sealed for detailed follow-up, including starts.
        pairs=list(itertools.combinations(range(8),2));bins=[3073,3182,3328];rows=[]
        for phase in self.phases:
            z=self.args.measurement_root/phase['scan_id']/'xcorr.zarr'
            for start in range(0,phase['duration_seconds'],100):
                vs=np.zeros((28,3),complex);ps=np.zeros((8,3));weights=np.zeros(3)
                for t in range(start,start+100):
                    n=np.fromfile(z/'n_valid'/f'{t}.0',dtype='<u8')
                    for j,k in enumerate(bins):
                        block,local=divmod(k,256)
                        v=np.fromfile(z/'mean_cross_visibility_count2'/f'{t}.0.{block}',dtype='<c16').reshape(28,256)
                        p=np.fromfile(z/'mean_auto_power_count2'/f'{t}.0.{block}',dtype='<f8').reshape(8,256)
                        vs[:,j]+=v[:,local]*n[block];ps[:,j]+=p[:,local]*n[block];weights[j]+=n[block]
                vs/=weights;ps/=weights
                for index,(a,b) in enumerate(pairs):
                    for j,k in enumerate(bins):
                        v=vs[index,j];rho=v/np.sqrt(ps[a,j]*ps[b,j])
                        rows.append(dict(group=phase['group'],segment=(start//100+1 if phase['group']=='A' else phase['segment']),
                            scan_id=phase['scan_id'],pair=[a,b],global_bin=k,real_count2=float(v.real),imag_count2=float(v.imag),
                            amplitude_count2=float(abs(v)),phase_deg=float(np.angle(v,deg=True)),rho_pct=float(abs(rho)*100),
                            power_a_count2=float(ps[a,j]),power_b_count2=float(ps[b,j])))
        science.base.write_json_new(self.evidence/'abc_segment_comparison.json',{
            'definition':'100s weighted complex mean then magnitude, not mean of magnitudes',
            'gap_handling':'segments remain separate; no Allan across gaps', 'rows':rows})
        (self.evidence/'ABC_README.md').write_text(
            '# ABC completed\n\nA: nine virtual segments. B/C: nine separate scans.\n'
            'See abc_segment_comparison.json; phase telemetry and initialization readbacks are retained.\n'
            'All 100 ms fullband data are retained, including initial valid buckets.\n'
            'Acquisition is ordered A/B/C; elapsed-time and temperature are potential confounders.\n')

def main():
    args=science.parse_args()
    if args.dry_run:
        phases=plan(args.queue_id)
        print(json.dumps({'phases':phases,'science_seconds':sum(p['duration_seconds'] for p in phases),
                          'gap_target_seconds':GAP_SECONDS},indent=2));return 0
    args.lock.parent.mkdir(parents=True,exist_ok=True)
    with args.lock.open('a+b') as lock:
        fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        return ABC(args,json.loads(args.template.read_text())).run()

if __name__=='__main__':sys.exit(main())
