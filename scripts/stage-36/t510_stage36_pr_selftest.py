#!/usr/bin/env python3
"""Offline PR gate/plan and same-restore-path tests."""
import contextlib
import json
from pathlib import Path
import sys
from unittest.mock import Mock, patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import t510_stage36_pr_queue as q
import t510_stage36_init_probe as helper
p=q.plan('test');formal=[x for x in p if not x['short_gate']]
assert len(p)==15 and len(formal)==13
assert sum(x['duration_seconds'] for x in formal)==1300
assert [x['group'] for x in p[:2]]==['P','R'] and all(x['duration_seconds']==10 for x in p[:2])
assert ''.join(x['group'] for x in formal)=='SPSRSRSPSPSRS'
assert all(formal[i-1]['group']==formal[i+1]['group']=='S' for i in range(1,12,2))
for g in 'PR':assert sum(x['group']==g for x in formal)==3

calls=[]
for action in 'PR':
 core=Mock();core.read_status.return_value={'streaming':False,'board_id':1}
 core.read_lmk_status.return_value={'profile_id':'160m_10m_request_manual_clkin0','profile_sha256':'same','pll1_lock':1,'pll2_lock':1}
 core.read_digital_scaling.return_value={'ok':True};core.reset_all_rfdc_tiles.return_value=[{}]*8
 controller=Mock();controller.require_core.return_value=core
 controller.prepare.return_value={'observation':{'clock_recovery':{'clock_preserved':True,'clock_reconfigured':False,'tile_reset_calls':[]}}}
 config=object()
 with patch.object(helper.hw,'_configure_hardware_guard',return_value=contextlib.nullcontext()),patch.object(helper.hw,'_load_saved_configure_request',return_value={}),patch.object(helper.hw,'_controller',return_value=controller),patch.object(helper.hw,'_config_from_saved_request',return_value=config),patch.object(helper.hw,'_mts_summary',return_value={'adc':{'active_measured_latency':[492]*4}}),patch.object(helper.hw,'_persist_mts_summary'):
  result=helper.execute(action);assert result['ok']
  controller.prepare.assert_called_once();assert controller.prepare.call_args.args==(config,)
  calls.append(controller.prepare.call_args.kwargs)
  assert core.reset_all_rfdc_tiles.call_count==(1 if action=='R' else 0)
  controller.connect.assert_not_called()
  core.clock.set_sysref.assert_any_call(True);core.clock.set_sysref.assert_called_with(False)
  # Reject hidden clock/reset recovery from the common prepare path.
  controller.prepare.return_value['observation']['clock_recovery']['clock_reconfigured']=True
  try:helper.execute(action);raise AssertionError('hidden clock recovery accepted')
  except RuntimeError as e:assert 'unexpectedly' in str(e)
assert calls[0]==calls[1] and calls[0]['require_clock_preserved'] and not calls[0]['fresh_download']
# A short gate failure propagates; no later stage can run in science.Queue.run.
runner=q.PRQueue.__new__(q.PRQueue);runner.args=Mock();runner.args.measurement_root=Path('/unused');runner.evidence=Path('/unused');runner.event=Mock()
with patch.object(q.init.InitQueue,'run_phase'),patch.object(q.init.abc.fullband,'verify',return_value={'status':'FAIL'}),patch.object(q.science.base,'write_json_new'):
 try:runner.run_phase(p[0]);raise AssertionError('failed short gate accepted')
 except RuntimeError as e:assert 'short gate failed' in str(e)
runner.event.assert_not_called()
print('PASS: 2 short gates + 13 formal scans; identical P/R prepare; reset count; hidden recovery rejection; short gate fail-stop')
