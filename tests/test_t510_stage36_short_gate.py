import copy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts/stage-36'))
import t510_stage36_short_gate as gate
import numpy as np
from python.t510_scaling import qmc_settings,scaling_identity

class ShortGateTests(unittest.TestCase):
    @staticmethod
    def board_snapshot(streaming):
        scale=scaling_identity(0x10036,0x556,[dict(tile=t,block=b,qmc=qmc_settings()) for t in range(4) for b in range(2)])
        return {'streaming':streaming,'board_id':1,'core_version':'0x00010036','error_flags':0,
                'dac':{'enable_mask':0},'clock':{'clock_reference':'onboard_tcxo',
                'profile_id':gate.EXPECTED_CLOCK_PROFILE,'profile_sha256':gate.EXPECTED_CLOCK_SHA256,
                'pll1_lock':1,'pll2_lock':1},'mts':{'adc':{'target_latency':492},'dac':{'target_latency':-1}},
                'profile':{'sample_rate_msps':320,'mode':'time_only','center_mhz':200.0},'digital_scaling':scale,
                'rfdc':{'readback':{'ok':True}}}

    def values(self):
        t=dict(std_iq=[[10.,10.] for _ in range(8)],odd_fraction_iq=[[.5,.5] for _ in range(8)],clip_iq=[[0,0] for _ in range(8)])
        s=dict(median_std_iq_by_adc=[[10.,10.] for _ in range(8)],selected_bins={str(k):[[10.,10.] for _ in range(8)] for k in gate.BINS},clip_components=0)
        return copy.deepcopy((t,s))
    def test_in_range(self):
        t,s=self.values();self.assertEqual(gate.numerical_errors(t,s),[])
    def test_one_default_bin_outside_range_rejected(self):
        t,s=self.values();s['selected_bins']['3134'][3][1]=7.99
        self.assertTrue(gate.numerical_errors(t,s))
    def test_nan_and_clipping_rejected(self):
        t,s=self.values();t['std_iq'][1][0]=float('nan');s['clip_components']=1
        self.assertEqual(len(gate.numerical_errors(t,s)),2)
    def test_sparse_lsb_rejected(self):
        t,s=self.values();t['odd_fraction_iq'][4][1]=0
        self.assertTrue(gate.numerical_errors(t,s))
    def test_spec_sequence_gap_rejected(self):
        def row(seq,frame):
            w=[0]*16;w[1]=1<<48;w[4]=(frame//16)*4096;w[5]=frame;w[6]=seq<<32
            w[7]=(256<<48)|(8<<16);w[10]=(8<<48)|(0x556<<32)|0x437
            return 4308,w,np.zeros((256,8,2),np.int16)
        with patch.object(gate,'packets',return_value=iter([row(0,0),row(32,16)])),self.assertRaisesRegex(RuntimeError,'gap'):
            gate.spec_stats(Path('unused'),Path('unused'))
    def test_time_integer_statistics(self):
        data=np.empty((256,8,2),np.int16);data[::2]=10;data[1::2]=-10
        with patch.object(gate,'packets',return_value=iter([(4300,[0,1<<32],data)])):
            result=gate.time_stats(Path('unused'))
        self.assertEqual(result['std_iq'],[[10.,10.] for _ in range(8)])
        self.assertEqual(result['samples_per_adc'],256)

    def test_start_warmup_reuses_stage35_boundary(self):
        self.assertEqual(gate.START_WARMUP_SECONDS,3.0)

    def test_start_warmup_integrity_event_is_preserved_but_excluded(self):
        integrity={'ok':False,'errors':['receiver.sample0_gaps delta=1']}
        evidence=gate.startup_boundary_evidence(integrity)
        self.assertEqual(evidence['boundary_events'],integrity['errors'])
        self.assertTrue(evidence['excluded_from_formal_window'])

    def test_stop_response_loss_is_read_back_without_second_stop(self):
        snapshots=[self.board_snapshot(True),self.board_snapshot(False)]
        stop_calls=[]
        def board(path='/api/v2/status',**kwargs):
            if path.endswith('/stop'):
                stop_calls.append(path);raise ConnectionResetError('lost reply')
            return snapshots.pop(0)
        result=gate._safe_stop(board,mode='time_only')
        self.assertTrue(result['idempotent_readback_accepted'])
        self.assertEqual(len(stop_calls),1)

    def test_stop_response_loss_rejects_streaming_readback(self):
        snapshots=[self.board_snapshot(True),self.board_snapshot(True)]
        stop_calls=[]
        def board(path='/api/v2/status',**kwargs):
            if path.endswith('/stop'):
                stop_calls.append(path);raise ConnectionResetError('lost reply')
            return snapshots.pop(0)
        with self.assertRaisesRegex(RuntimeError,'BOARD_STILL_STREAMING'):
            gate._safe_stop(board,mode='time_only')
        self.assertEqual(len(stop_calls),1)
if __name__=='__main__':unittest.main()
