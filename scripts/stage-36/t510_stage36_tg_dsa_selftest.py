#!/usr/bin/env python3
"""Test DSA write scope, reset reapplication, and failure cleanup."""
import contextlib
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import t510_stage36_tg_dsa_probe as probe

core = Mock()
core.read_status.return_value = dict(streaming=False, core_version=0x10036, board_id=1)
core.ctrl.read.return_value = 0
core.read_lmk_status.return_value = dict(profile_id='160m_10m_request_manual_clkin0', profile_sha256='same', pll1_lock=1, pll2_lock=1)
core.read_digital_scaling.return_value = {'unchanged':True}
tiles = []
for _ in range(4):
    tile = Mock()
    tile.blocks = [SimpleNamespace(DSA={'Attenuation':0., 'DisableRTS':0}) for _ in range(2)]
    tile.Reset.side_effect = lambda t=tile: [setattr(b,'DSA',{'Attenuation':0., 'DisableRTS':0}) for b in t.blocks]
    tiles.append(tile)
core.rfdc = SimpleNamespace(adc_tiles=tiles)
controller = Mock(); controller.require_core.return_value = core
core._run_rfdc_mts_sequence.return_value = {'calls':[{}], 'failures':[]}
def prepare(*args, **kwargs):
    core._run_rfdc_mts_sequence(required=True)
    return {'observation':{'clock_recovery':{'clock_preserved':True,'clock_reconfigured':False,'tile_reset_calls':[]}}}
controller.prepare.side_effect = prepare
with tempfile.TemporaryDirectory() as directory, contextlib.ExitStack() as stack:
    for name, value in [('_configure_hardware_guard',contextlib.nullcontext()),
                        ('_load_saved_configure_request',{}),('_controller',controller),
                        ('_config_from_saved_request',{}),('_mts_summary',{'adc':{'active_measured_latency':[492]*4}}),
                        ('_persist_mts_summary',None)]:
        stack.enter_context(patch.object(probe.base.hw,name,return_value=value))
    journal = probe.Journal(directory)
    assert probe.execute('T0',journal)['ok']
    assert [t.Reset.call_count for t in tiles] == [1,0,0,0]
    after_reset = next(r['snapshot'] for r in journal.rows if r['boundary']=='after_reset')
    assert after_reset['rows'][0]['dsa']['Attenuation'] == 0
    assert after_reset['rows'][2]['dsa']['Attenuation'] == 20
    probe.check(probe.snapshot(core),journal.original)
    assert [b.DSA['Attenuation'] for t in tiles for b in t.blocks] == [20,0,20,0,0,0,0,0]
    assert [r['boundary'] for r in journal.rows] == ['before_operation','initial_dsa_applied','before_reset','after_reset','post_reset_dsa_applied','before_mts','after_mts','after_prepare']
    for tile in tiles: tile.Reset.reset_mock()
    adc_journal = probe.Journal(directory)
    assert probe.execute('ADC',adc_journal)['ok']
    assert [t.Reset.call_count for t in tiles] == [1,1,1,1]
    reset_value = next(r['snapshot'] for r in adc_journal.rows if r['boundary']=='after_reset')
    assert [r['dsa']['Attenuation'] for r in reset_value['rows']] == [0]*8
    probe.check(probe.snapshot(core),adc_journal.original)
    controller.prepare.reset_mock()
    with patch.object(probe,'apply',side_effect=RuntimeError('injected write failure')):
        failed = probe.Journal(directory)
        try: probe.execute('T0',failed)
        except RuntimeError: pass
        else: raise AssertionError('failure swallowed')
        controller.prepare.assert_not_called()
        assert failed.path.read_text().find('injected write failure') >= 0
    core.stop.assert_called(); core.set_dac_enable_mask.assert_called_with(0)
    core.read_status.return_value['streaming'] = True
    try: probe.apply(core,journal.original)
    except RuntimeError: pass
    else: raise AssertionError('live DSA write permitted')
print('PASS: selected ADC0/2 only, simulated Reset clears/reapplies DSA, boundary verification, streaming guard and fail-stop journal')
