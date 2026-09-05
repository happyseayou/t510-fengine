import argparse
import contextlib
import io
import json
from pathlib import Path
import shlex
import sys
import tempfile
import unittest
from unittest.mock import Mock,patch
from scripts import pynq_t510_mts_campaign as mts
from scripts import t510_release_qualification as queue
from scripts import t510_board_host_gate as board_gate
from scripts import t510_host_validate as host_gate
from python.t510_scaling import scaling_identity,qmc_settings

class QualificationTests(unittest.TestCase):
    @staticmethod
    def stopped_snapshot():
        tiles=[{'kind':kind,'tile':tile,'pll_lock_status':1,'sample_rate_hz':3_840_000_000.0}
               for kind in ('adc','dac') for tile in range(4)]
        blocks=[{'kind':kind,'tile':tile,'block':block,'factor':12,'nyquist_zone':1,
                 'mixer_frequency_mhz':-200.0 if kind=='adc' else 200.0}
                for kind in ('adc','dac') for tile in range(4) for block in range(2)]
        scale=scaling_identity(0x10036,0x556,[dict(tile=t,block=b,qmc=qmc_settings()) for t in range(4) for b in range(2)])
        return {'streaming':False,'board_id':1,'core_version':'0x00010036','error_flags':0,
                'dac':{'enable_mask':0},'profile':{'sample_rate_msps':320,'mode':'time_only','center_mhz':200.0},
                'clock':{'clock_reference':'onboard_tcxo','profile_id':board_gate.EXPECTED_CLOCK_PROFILE,
                         'profile_sha256':board_gate.EXPECTED_CLOCK_SHA256,'pll1_lock':1,'pll2_lock':1},
                'mts':{'adc':{'target_latency':492},'dac':{'target_latency':-1}},
                'digital_scaling':scale,'rfdc':{'adc_analog_sample_rate_hz':3_840_000_000,
                'dac_analog_sample_rate_hz':3_840_000_000,'complex_sample_rate_hz':320_000_000,
                'adc_decimation':12,'dac_interpolation':12,'adc_axis_rate_hz':80_000_000,
                'dac_axis_rate_hz':80_000_000,'readback':{'ok':True,
                'active_block_count':{'adc':8,'dac':8},'tiles':tiles,'blocks':blocks}}}

    def test_stop_lost_response_is_accepted_only_after_safe_readback(self):
        running=self.stopped_snapshot();running['streaming']=True
        stopped=self.stopped_snapshot();calls=[]
        def request(url,**kwargs):
            calls.append((url,kwargs.get('body')))
            if url.endswith('/stop'):raise ConnectionResetError('injected lost response')
            return {'result':running if len([x for x in calls if x[0].endswith('/status')])==1 else stopped}
        with patch.object(board_gate,'_http_json',side_effect=request):
            result=board_gate._safe_stop('http://board',reason='test',expected_board_id=1,
                sample_rate_msps=320,mode='time_only',center_mhz=200)
        self.assertTrue(result['idempotent_readback_accepted'])
        self.assertEqual(sum(url.endswith('/stop') for url,_ in calls),1)

    def test_remote_receiver_state_preserves_python_c_argument(self):
        payload={'result':{'stats':{'packets_per_sec':1}}}
        completed=Mock(returncode=0,stdout=json.dumps(payload),stderr='')
        with patch.object(board_gate.subprocess,'run',return_value=completed) as run:
            value=board_gate._remote_receiver_state(
                'receiver.example', 'http://127.0.0.1:8089'
            )
        self.assertEqual(value,payload['result'])
        command=run.call_args.args[0]
        self.assertEqual(command[:4],['ssh','-o','BatchMode=yes','receiver.example'])
        remote_argv=shlex.split(command[4])
        self.assertEqual(remote_argv[0:2],['python3','-c'])
        self.assertIn('json.dumps',remote_argv[2])
        self.assertEqual(remote_argv[3],'http://127.0.0.1:8089')

    def test_receiver_worker_gate_matches_port_fanout_capacity(self):
        # TIME_SPEC has 24 active flows distributed modulo 16 workers.
        self.assertEqual(host_gate._worker_capacity_errors(
            {'worker_count':16,'active_worker_count':16},24
        ),[])
        self.assertEqual(host_gate._worker_capacity_errors(
            {'worker_count':16,'active_worker_count':15},24
        ),['ACTIVE_WORKERS_LOW'])
        self.assertEqual(host_gate._worker_capacity_errors(
            {'worker_count':16,'active_worker_count':8},8
        ),[])
        self.assertEqual(host_gate._worker_capacity_errors(
            {'worker_count':0,'active_worker_count':0},8
        ),['CAPTURE_WORKER_CAPACITY_INVALID'])

    def test_start_warmup_sample0_boundary_is_recorded_outside_formal_gate(self):
        before={key:0 for key in board_gate.RECEIVER_LOSS_COUNTERS}
        after=dict(before);after['sample0_gaps']=1
        boundary=board_gate._startup_receiver_boundary(after,before)
        self.assertEqual(boundary['receiver_counter_delta']['sample0_gaps'],1)
        self.assertEqual(boundary['receiver_boundary_events'],[
            'receiver.sample0_gaps delta=1'
        ])
        self.assertTrue(boundary['excluded_from_formal_window'])

    def test_stop_lost_response_rejects_unsafe_readback_without_retry(self):
        running=self.stopped_snapshot();running['streaming']=True
        calls=[]
        def request(url,**kwargs):
            calls.append(url)
            if url.endswith('/stop'):raise ConnectionResetError('injected lost response')
            return {'result':running}
        with patch.object(board_gate,'_http_json',side_effect=request),self.assertRaisesRegex(RuntimeError,'BOARD_STILL_STREAMING'):
            board_gate._safe_stop('http://board',reason='test',expected_board_id=1,
                sample_rate_msps=320,mode='time_only',center_mhz=200)
        self.assertEqual(sum(url.endswith('/stop') for url in calls),1)

    def test_incremental_telemetry_uses_cursor_and_rejects_gap(self):
        before={'reference_watchdog':{'power_thermal_telemetry':{'sequence':10,'epoch_id':'e1'}}}
        response={'result':{'source':'watchdog','since_seq':10,'record_count':2,
                  'first_sequence':11,'last_sequence':12,'epoch_id':'e1',
                  'records':[{'sequence':11,'epoch_id':'e1'},{'sequence':12,'epoch_id':'e1'}]}}
        with patch.object(board_gate,'_http_json',return_value=response) as request:
            result=board_gate._incremental_telemetry('http://board',before)
        self.assertEqual(result['errors'],[])
        self.assertIn('since_seq=10',request.call_args.args[0])
        response['result']['records'][1]['sequence']=13
        with patch.object(board_gate,'_http_json',return_value=response):
            result=board_gate._incremental_telemetry('http://board',before)
        self.assertIn('TELEMETRY_RECORDS_NOT_CONTIGUOUS',result['errors'])

    def test_mts_stops_at_first_failed_cycle(self):
        for invalid_scale in (False,True):
            with self.subTest(invalid_scale=invalid_scale),tempfile.TemporaryDirectory() as temp:
                root=Path(temp);bit=root/'candidate.bit';bit.write_bytes(b'test')
                scale=scaling_identity(0x10036,0x556,[dict(tile=t,block=b,qmc=qmc_settings()) for t in range(4) for b in range(2)])
                if invalid_scale:scale['ok']=False
                core=Mock();core.clock.set_sysref.return_value={'enabled':True};core.read_status.return_value={'core_version':0x10036}
                ctrl=Mock();ctrl.require_core.return_value=core
                args=['mts','--phase','discovery','--bitfile',str(bit),'--output',str(root/'out.json'),'--settle-seconds','0']
                with patch.object(sys,'argv',args),patch('python.t510_control.FEngineController',return_value=ctrl),\
                     patch.object(mts,'_acquire_configure_lock'),patch.object(mts,'_condition_initial_hardware',return_value={'ok':True}),\
                     patch.object(mts,'_reset_rfdc_tiles',return_value=[]),patch.object(mts,'_run_mts',return_value={'digital_scaling':scale}) as run,\
                     patch.object(mts,'_assess_cycle',return_value=[] if invalid_scale else ['injected MTS failure']),\
                     contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(mts.main(),1)
                state=json.loads((root/'out.json').read_text())
                self.assertEqual(state['completed_cycles'],1);self.assertTrue(state['stopped_on_first_failure'])
                self.assertEqual(run.call_count,1);self.assertFalse(state['ok'])

    def test_queue_does_not_install_after_failed_discovery(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);package=root/'package';package.mkdir()
            q=queue.QualificationQueue(argparse.Namespace(evidence=root/'evidence',package=package,queue_id='stage36-test'))
            q.validate_package=Mock()
            names=[]
            def remote(name,*args,**kwargs):
                names.append(name)
                if name=='mts_discovery_40':raise RuntimeError('injected discovery failure')
            q.remote=remote
            q.command=Mock()
            before={'streaming':False,'dac':{'enable_mask':0},'core_version':'0x00010034','clock':{'clock_reference':'onboard_tcxo'}}
            q.http=Mock(return_value=before)
            with self.assertRaisesRegex(RuntimeError,'injected discovery'):
                q.run()
            self.assertNotIn('install',names);self.assertNotIn('mts_fixed_40',names)
            self.assertIn('failure_mute',names)
            self.assertEqual(json.loads((q.evidence/'queue-state.json').read_text())['status'],'FAIL')

    def test_existing_queue_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);p=root/'queue-state.json';p.write_text('{"status":"running"}')
            q=queue.QualificationQueue(argparse.Namespace(evidence=root,package=root,queue_id='stage36-test'))
            with self.assertRaisesRegex(RuntimeError,'evidence already exists'):q.run()
            self.assertEqual(p.read_text(),'{"status":"running"}')
if __name__=='__main__':unittest.main()
