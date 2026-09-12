#!/usr/bin/env python3
"""Check boundary ordering, unchanged hardware calls, and failure preservation."""
import contextlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import t510_stage36_trace_queue as queue
import t510_stage36_trace_probe as trace
from t510_stage36_trace_analyze import validate_trace

phases = queue.plan('test')
formal = [p for p in phases if not p['short_gate']]
assert len(phases) == 22 and len(formal) == 19
assert len({p['scan_id'] for p in phases}) == 22
for group in ('T0', 'M', 'P'):
    assert sum(p['group'] == group for p in formal) == 3
assert all(formal[i-1]['group'] == formal[i+1]['group'] == 'S' for i in range(1, 18, 2))

for action in ('T0', 'P', 'M'):
    core = Mock()
    core.read_status.return_value = {'streaming':False, 'board_id':1}
    core.read_lmk_status.return_value = {'profile_id':'160m_10m_request_manual_clkin0', 'profile_sha256':'same', 'pll1_lock':1, 'pll2_lock':1}
    core.read_digital_scaling.return_value = {'same':True}
    core.read_adc_calibration_status.return_value = {'temperature_c':40, 'channels':[
        {'adc':i, 'tile':i//2, 'block':i%2, 'coefficients':{b:[i]*8 for b in ('ocb1','ocb2','gcb','tscb')}} for i in range(8)]}
    core.read_rfdc_tile_power_status.return_value = {'supported':True}
    core.read_rfdc_contract.return_value = {'ok':True}
    core.rfdc = SimpleNamespace(adc_tiles=[Mock() for _ in range(4)], dac_tiles=[Mock() for _ in range(4)])
    original = core._run_rfdc_mts_sequence
    original.return_value = {'calls':[{}], 'failures':[]}
    controller = Mock()
    controller.require_core.return_value = core
    def prepare(*args, **kwargs):
        core._run_rfdc_mts_sequence(required=True)
        return {'observation':{'clock_recovery':{'clock_preserved':True,'clock_reconfigured':False,'tile_reset_calls':[]}}}
    controller.prepare.side_effect = prepare
    with tempfile.TemporaryDirectory() as tmp, contextlib.ExitStack() as stack:
        for name, value in [('_configure_hardware_guard',contextlib.nullcontext()),
                            ('_load_saved_configure_request',{}), ('_controller',controller),
                            ('_config_from_saved_request','same'),
                            ('_mts_summary',{'adc':{'active_measured_latency':[492]*4}}),
                            ('_persist_mts_summary',None)]:
            stack.enter_context(patch.object(trace.base.hw, name, return_value=value))
        recorder = trace.Recorder(tmp)
        result = trace.execute(action, recorder)
        assert result['ok']
        validate_trace(action, result['boundary_trace'])
        assert core._run_rfdc_mts_sequence is original
        original.assert_called_once()
        assert controller.prepare.call_count == (0 if action == 'M' else 1)
        assert [t.Reset.call_count for t in core.rfdc.adc_tiles] == ([1,0,0,0] if action == 'T0' else [0]*4)
        assert all(t.Reset.call_count == 0 for t in core.rfdc.dac_tiles)
        core.reset_all_rfdc_tiles.assert_not_called()
        assert len(recorder.path.read_text().splitlines()) == len(recorder.rows)
        bad = list(recorder.rows[:-1])
        try: validate_trace(action, bad)
        except RuntimeError: pass
        else: raise AssertionError('missing boundary accepted')
        if action == 'T0':
            # An observer failure after the Reset must block prepare and restore the wrapper.
            controller.prepare.reset_mock()
            core.read_adc_calibration_status.side_effect = [core.read_adc_calibration_status.return_value]*2 + [RuntimeError('injected read failure')]
            failed = trace.Recorder(tmp)
            try: trace.execute(action, failed)
            except RuntimeError as exc: assert 'injected read failure' in str(exc)
            else: raise AssertionError('snapshot failure swallowed')
            controller.prepare.assert_not_called()
            assert core._run_rfdc_mts_sequence is original
            assert json.loads(failed.path.read_text().splitlines()[-1])['boundary'] == 'after_reset'
            core.stop.assert_called()
            core.set_dac_enable_mask.assert_called_with(0)
            core.clock.set_sysref.assert_called_with(False)
print('PASS: bounded plan, exact Reset/prepare/MTS calls, boundary ordering, durable failure trace, wrapper restoration and safe cleanup')
