#!/usr/bin/env python3
"""TG-on 10s gate then 60s common-signal measurement; no board configuration."""
import fcntl
import json
from pathlib import Path
import subprocess
import sys
import t510_stage36_abc_queue as abc
from t510_stage36_tg_analyze import raw_headroom, summarize
science = abc.science
science.FOCUS_BINS = tuple(dict.fromkeys((3200,3201,3202,3073,3182,3328)+science.FOCUS_BINS))[:32]


def plan(qid):
    return [dict(index=i,kind='xcorr',label=label,group='TG',segment=i+1,scan='TG02',position='scan',
                 mode='spec_only',duration_seconds=seconds,short_gate=i==0,
                 scan_id=f'{qid}-{label}-{seconds}s',status='pending')
            for i,(label,seconds) in enumerate((('gate',10),('steady',60)))]


class TGQueue(abc.ABC):
    def __init__(self,args,template):
        super().__init__(args,template)
        self.phases=plan(args.queue_id)
        self.context=dict(rf_inputs='SSA TG via XQY-PS2-DC/3-SE to ADC0/2; other six independent 50ohm',
            tg_on_operator_confirmed=True,tg_requested_frequency_mhz=130.078125,tg_requested_level_dbm=-20,
            tg_zero_span=True,external_attenuator=False,dsa_db_by_adc=[20,0,20,0,0,0,0,0],
            clock_reference='onboard_tcxo',dac='muted',source_level_at_adc_dbm='not measured')
        self.state.update(phases=self.phases,physical_context=self.context,
            products=['fullband_visibility_100ms_and_1s','common_tone02_response','adjacent_raw_iq_headroom'],
            experiment=dict(sequence=['10s gate','60s steady if gate passes'],
                hardware_operations='STOP/START only; reject CONFIGURE/Reset/MTS/clock actions while TG on',
                source_gate='peaks within 2 bins of3201 on ADC0/2 and at least10dB above local median; no coherence acceptance threshold',
                completion='stop stream/DAC mute; external TG remains under operator control'))

    def board(self,path='/api/v2/status',**kwargs):
        if kwargs.get('method') == 'POST' and path not in ('/api/v2/start','/api/v2/stop','/api/v2/dac'):
            raise RuntimeError(f'prohibited TG-on hardware action: {path}')
        return super().board(path,**kwargs)

    def receiver(self,path='/api/state',**kwargs):
        if path=='/api/measure/crosscorrelation' and kwargs.get('method')=='POST':
            meta=kwargs['body']['metadata']
            # Receiver metadata is a map of strings; retain typed context in queue evidence.
            meta.update({k:v if isinstance(v,str) else json.dumps(v) for k,v in self.context.items()},physical_input=self.context['rf_inputs'],
                        interpretation='known_common_CW_end_to_end_response_not_independent_noise')
        return super().receiver(path,**kwargs)

    def probe(self,name):
        p=subprocess.run(['/usr/bin/python3',str(Path(__file__).with_name('t510_stage36_init_transport.py')),'probe'],
                         capture_output=True,text=True,timeout=60)
        if p.returncode:raise RuntimeError(f'TG read-only probe failed: {p.stdout} {p.stderr}')
        value=json.loads(p.stdout)
        science.base.write_json_new(self.evidence/name,value)
        if value.get('ok') is not True or value['helper_sha256']!=science.base.sha256_file(Path(__file__).with_name('t510_stage36_tg_monitor.py')):
            raise RuntimeError('TG monitor identity mismatch')
        if [r['dsa']['Attenuation'] for r in value['rows']] != self.context['dsa_db_by_adc']:
            raise RuntimeError('actual DSA differs from measurement identity')
        if any(r['adc_error_bits'] for r in value['rows']):
            raise RuntimeError('RFDC sticky error bits set; preserve evidence, do not proceed')
        return value

    def preflight(self):
        science.Queue.preflight(self)
        errors=science.identity_errors(self.board(),mode='spec_only',center_mhz=self.args.center_mhz)
        if errors:raise RuntimeError(str(errors))
        self.probe('tg_monitor_preflight.json')
        science.base.write_json_new(self.evidence/'tg_implementation.json',{
            'context':self.context,'files':{p.name:science.base.sha256_file(p) for p in [Path(__file__),
            Path(__file__).with_name('t510_stage36_tg_analyze.py'),Path(__file__).with_name('t510_stage36_tg_monitor.py')]}})

    def ensure_mode(self,phase):
        before=self.board()
        science.Queue.ensure_mode(self,phase)
        if abc.initialization_identity(before)!=abc.initialization_identity(self.board()):
            raise RuntimeError('initialization identity changed during STOP/START')
        self.probe(f"phase_{phase['index']:02d}_dsa_before.json")

    def start_stream(self,phase):
        return science.Queue.start_stream(self,phase)

    def monitor_capture(self,phase,status_path):
        result=super().monitor_capture(phase,status_path)
        # The measurement is complete, the board is still streaming; witness is adjacent, not simultaneous.
        path=self.raw/f"{phase['label']}-headroom.pcap"
        capture=science.base.http_to_new_file(self.args.receiver_base+'/api/capture/spec-pcap',path,
            body=dict(packets_per_block=66,include_time=False,time_only=False),timeout=30)
        headroom=raw_headroom(path)
        science.base.write_json_new(self.evidence/f"phase_{phase['index']:02d}_headroom.json",dict(capture=capture,**headroom))
        if not headroom['passed']:raise RuntimeError('F-engine raw IQ headroom below 20 percent')
        return result

    def run_phase(self,phase):
        super().run_phase(phase)
        self.probe(f"phase_{phase['index']:02d}_dsa_after.json")
        dataset=self.args.measurement_root/phase['scan_id']
        verification=abc.fullband.verify(dataset,phase['duration_seconds'])
        science.base.write_json_new(self.evidence/f"phase_{phase['index']:02d}_short_verification.json",verification)
        if verification['status']!='PASS':raise RuntimeError('numeric verification failed')
        summary=summarize(dataset,phase['duration_seconds'],self.evidence/f"phase_{phase['index']:02d}_tone.npz")
        science.base.write_json_new(self.evidence/f"phase_{phase['index']:02d}_tone.json",summary)
        if not summary['source_present']:raise RuntimeError('expected source not present on both ADC0/2; keep result for diagnosis')
        self.event('tone_gate_pass',phase=phase['label'],summary=summary)

    def compare_segments(self):
        rows=[dict(phase=p['label'],**json.loads((self.evidence/f"phase_{p['index']:02d}_tone.json").read_text())) for p in self.phases]
        science.base.write_json_new(self.evidence/'common_tone_results.json',dict(context=self.context,rows=rows,
            limitation='Steady common CW test only; no reboot-repeatability or broadband alignment claim'))


def main():
    args=science.parse_args()
    if args.dry_run:
        print(json.dumps(dict(phases=plan(args.queue_id),note='TG on; no CONFIGURE or Reset'),indent=2));return 0
    with args.lock.open('a+b') as lock:
        fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        return TGQueue(args,json.loads(args.template.read_text())).run()

if __name__=='__main__':sys.exit(main())
