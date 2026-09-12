import sys
from pathlib import Path
sys.path.insert(0,str(Path(sys.argv[1])/'scripts/stage-36'))
import t510_stage36_init_queue as q
p=q.plan('test')
assert len(p)==19 and sum(r['duration_seconds'] for r in p)==1900
assert len({r['scan_id'] for r in p})==19
assert [r['group'] for r in p[1::2]]==list('MRFRFMFMR')
for i in range(1,18,2):assert p[i-1]['group']==p[i+1]['group']=='S'
for g in 'MRF':assert sum(r['group']==g for r in p)==3
# Model the stopped-board helper: M must not call reset/prepare, and failure must clean up.
import importlib.util
from types import SimpleNamespace
from unittest.mock import Mock, patch
import contextlib
spec=importlib.util.spec_from_file_location('probe',Path(sys.argv[1])/'scripts/stage-36/t510_stage36_init_probe.py')
m=importlib.util.module_from_spec(spec)
sys.path.insert(0,sys.argv[1]);spec.loader.exec_module(m)
core=Mock(); core.read_status.return_value={'streaming':False,'board_id':1}
core.read_lmk_status.return_value={'profile_id':'160m_10m_request_manual_clkin0','pll1_lock':1,'pll2_lock':1}
core.read_digital_scaling.return_value={'ok':True}
core._run_rfdc_mts_sequence.return_value={'calls':[{}],'failures':[]}
controller=Mock();controller.require_core.return_value=core
summary={'adc':{'active_measured_latency':[492]*4}}
with patch.object(m.hw,'_configure_hardware_guard',return_value=contextlib.nullcontext()), patch.object(m.hw,'_load_saved_configure_request',return_value={}), patch.object(m.hw,'_controller',return_value=controller), patch.object(m.hw,'_mts_summary',return_value=summary), patch.object(m.hw,'_persist_mts_summary'):
 assert m.execute('M')['ok']
 core.reset_all_rfdc_tiles.assert_not_called();controller.prepare.assert_not_called()
 core._run_rfdc_mts_sequence.side_effect=RuntimeError('injected MTS failure')
 try:m.execute('M');raise AssertionError('failure swallowed')
 except RuntimeError as e:assert str(e)=='injected MTS failure'
 core.stop.assert_called();core.set_dac_enable_mask.assert_called_with(0);core.clock.set_sysref.assert_called_with(False)
print('PASS: interleaved plan, isolated MTS operation, fail-stop cleanup')

# Exercise the real run_xcorr call ordering with a fake clock and receiver.
# Reproduce the old 125 s wait: it must occur BEFORE arm and consume none
# of the receiver's duration+120 s watchdog budget.
class CaptureDone(Exception): pass
runner=q.InitQueue.__new__(q.InitQueue)
runner.last_stop_monotonic=0.0
runner.args=SimpleNamespace(center_mhz=200.0,queue_id='test')
runner.event=Mock();runner.save=Mock()
now=[55.0];order=[];armed=[]
phase=q.plan('test')[1]
def sleep(seconds):
 assert not armed,'wait occurred after receiver arm'
 order.append('wait');now[0]+=seconds

def receiver(path='/',**kwargs):
 assert path=='/api/measure/crosscorrelation' and kwargs['method']=='POST'
 armed.append(now[0]);order.append('arm');return {}
def start(self,phase):
 order.append('start');assert now[0]==armed[0]
 # Formal start overhead plus 100 seconds must fit the 220-second watchdog.
 assert now[0]+15+phase['duration_seconds'] < armed[0]+phase['duration_seconds']+120
 raise CaptureDone()
runner.receiver=receiver
with patch.object(q.science.Queue,'_begin_common',return_value=({},{})), patch.object(q.time,'monotonic',side_effect=lambda:now[0]), patch.object(q.time,'sleep',side_effect=sleep), patch.object(q.science.Queue,'start_stream',start):
 try:runner.run_xcorr(phase)
 except CaptureDone:pass
 else:raise AssertionError('START not called')
assert order==['wait','arm','start'] and armed==[180.0]
assert phase['stop_to_start_request_seconds']==180.0
# Late preparation must fail before a new receiver task can be armed.
armed.clear();order.clear();now[0]=181.0
with patch.object(q.science.Queue,'_begin_common',return_value=({},{})), patch.object(q.time,'monotonic',side_effect=lambda:now[0]):
 try:runner.run_xcorr(phase)
 except RuntimeError as e:assert 'exceeded pre-arm gap' in str(e)
 else:raise AssertionError('late preparation accepted')
assert not armed
print('PASS: real capture ordering wait -> arm -> START; watchdog budget and pre-arm overrun gate')
