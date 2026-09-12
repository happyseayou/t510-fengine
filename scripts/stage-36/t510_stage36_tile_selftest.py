#!/usr/bin/env python3
"""Offline isolation and fail-stop checks for single-tile Reset."""
import contextlib
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock, patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import t510_stage36_tile_queue as q
import t510_stage36_init_probe as helper
p=q.plan('test');formal=[x for x in p if not x['short_gate']]
assert len(p)==22 and len(formal)==19 and sum(x['duration_seconds'] for x in formal)==1900
assert len({x['scan_id'] for x in p})==22
assert [x['group'] for x in p[:3]]==['T0','T3','P']
assert all(formal[i-1]['group']==formal[i+1]['group']=='S' for i in range(1,18,2))
for g in ('T0','T3','P'):assert [x['segment'] for x in formal if x['group']==g]==[1,2,3]
assert all(x['group']!='A' for x in p) # A is reserved by old ABC 900s segment reducer.

prepare_kwargs=[]
for action in ('T0','T3','P'):
 core=Mock();core.read_status.return_value={'streaming':False,'board_id':1}
 core.read_lmk_status.return_value={'profile_id':'160m_10m_request_manual_clkin0','profile_sha256':'same','pll1_lock':1,'pll2_lock':1}
 core.read_digital_scaling.return_value={'ok':True}
 core.rfdc=SimpleNamespace(adc_tiles=[Mock() for _ in range(4)],dac_tiles=[Mock() for _ in range(4)])
 core.reset_all_rfdc_tiles.return_value=[{}]*8
 controller=Mock();controller.require_core.return_value=core
 controller.prepare.return_value={'observation':{'clock_recovery':{'clock_preserved':True,'clock_reconfigured':False,'tile_reset_calls':[]}}}
 with patch.object(helper.hw,'_configure_hardware_guard',return_value=contextlib.nullcontext()),patch.object(helper.hw,'_load_saved_configure_request',return_value={}),patch.object(helper.hw,'_controller',return_value=controller),patch.object(helper.hw,'_config_from_saved_request',return_value='same_config'),patch.object(helper.hw,'_mts_summary',return_value={'adc':{'active_measured_latency':[492]*4}}),patch.object(helper.hw,'_persist_mts_summary'):
  result=helper.execute(action);assert result['ok']
  prepare_kwargs.append(controller.prepare.call_args)
  assert core.reset_all_rfdc_tiles.call_count==(1 if action=='R' else 0)
  for kind in ('adc','dac'):
   for index,t in enumerate(getattr(core.rfdc,kind+'_tiles')):
    assert t.Reset.call_count == int(kind=='adc' and action in ('T0','T3') and index==int(action[1]))
  controller.connect.assert_not_called()
  if action in ('T0','T3'):
   assert [(x['kind'],x['tile']) for x in result['operation']['explicit_tile_reset_calls']]==[('adc',int(action[1]))]
   controller.prepare.reset_mock()
   selected=core.rfdc.adc_tiles
   selected[int(action[1])].Reset.side_effect=RuntimeError('injected reset failure')
   try:helper.execute(action);raise AssertionError('reset failure swallowed')
   except RuntimeError as e:assert str(e)=='injected reset failure'
   controller.prepare.assert_not_called()
   core.stop.assert_called();core.set_dac_enable_mask.assert_called_with(0);core.clock.set_sysref.assert_called_with(False)
assert prepare_kwargs[0]==prepare_kwargs[1]==prepare_kwargs[2]
print('PASS: 3 gates + 19 formal scans, selected ADC tile only, common prepare, reset failure blocks prepare and cleans up')

import numpy as np
from t510_stage36_tile_analyze import PAIRS, partition, pair_rows, load_rho
for target in ('T0','T3'):
 assert sum(partition(pair,target)=='involved' for pair in PAIRS)==13
 assert sum(partition(pair,target)=='untouched' for pair in PAIRS)==15
# Equal magnitudes with rotated phase must register a complex change.
x=np.ones((28,4096),complex)
rows=pair_rows(x,1j*x,1j*x,'T0',1,'T0')
assert len(rows)==28 and abs(rows[0]['fullband']['jump_median_pp']-2**.5)<1e-12
assert rows[0]['fullband']['following_control_median_pp']==0
# Test the real chunk reader with unequal frame weights and changing powers.
import tempfile
with tempfile.TemporaryDirectory() as d:
 z=Path(d)/'xcorr.zarr'
 for name in ('n_valid','mean_auto_power_count2','mean_cross_visibility_count2'):(z/name).mkdir(parents=True)
 for t,weight in enumerate((1,3)):
  np.full(16,weight,dtype='<u8').tofile(z/'n_valid'/f'{t}.0')
  for block in range(16):
   np.full((8,256),4 if t==0 else 8,dtype='<f8').tofile(z/'mean_auto_power_count2'/f'{t}.0.{block}')
   np.full((28,256),1 if t==0 else 1j,dtype='<c16').tofile(z/'mean_cross_visibility_count2'/f'{t}.0.{block}')
 rho,v,p=load_rho(d,2)
 np.testing.assert_allclose(v,.25+.75j);np.testing.assert_allclose(p,7)
 np.testing.assert_allclose(rho,(.25+.75j)/7*100)
print('PASS: 13/15 spatial partitions, phase-sensitive difference, weighted fullband chunk reader')
