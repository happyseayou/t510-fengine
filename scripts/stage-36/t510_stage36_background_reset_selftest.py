#!/usr/bin/env python3
"""Exercise all nine preparation paths with real exclusive evidence-file writes."""
import json,tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import t510_stage36_background_reset_queue as module

def run(fail_reset=False):
    with tempfile.TemporaryDirectory() as d:
        q=object.__new__(module.ResetQueue);q.evidence=Path(d);q.args=SimpleNamespace(center_mhz=200)
        events=[]
        board={'streaming':False,'dac':{'channels':[{'enabled':False}]*8},'mts':{'epoch':0}}
        q.board=lambda:board.copy()
        def probe(name):module.tg.science.base.write_json_new(q.evidence/name,{'ok':True});events.append(('probe',name))
        q.probe=probe
        def prepare(self,phase):
            events.append(('prepare',phase['index']))
            module.tg.science.base.write_json_new(q.evidence/f"phase_{phase['index']:02d}_receiver_config.json",{'ok':True})
        def call(action,name,helper=None):
            events.append((action,name))
            if fail_reset and action=='ADC':raise RuntimeError('simulated reset failure')
            if action=='ADC':board['mts']={'epoch':board['mts']['epoch']+1}
            module.tg.science.base.write_json_new(q.evidence/(name+'.json'),{'ok':True})
            return {'ok':True,'background_helper_sha256':module.tg.science.base.sha256_file(Path(module.__file__).with_name('t510_stage36_background_reset_probe.py'))}
        q.call=call
        with patch.object(module.tg.science.Queue,'ensure_mode',prepare),patch.object(module.tg.science,'identity_errors',return_value=[]):
            if fail_reset:
                try:q.ensure_mode(module.plan('test')[1])
                except RuntimeError as e:assert str(e)=='simulated reset failure'
                else:raise AssertionError('reset failure did not stop')
                assert not any(a=='clear_once' for a,b in events)
                assert not list(q.evidence.glob('*prepared_board*'))
            else:
                for phase in module.plan('test'):q.ensure_mode(phase)
                assert [b for a,b in events if a=='prepare']==list(range(9))
                assert len([a for a,b in events if a=='ADC'])==3
                assert len([a for a,b in events if a=='clear_once'])==3
                assert len(list(q.evidence.glob('phase_*_receiver_config.json')))==9
                assert len(list(q.evidence.glob('r*_prepared_board.json')))==3
                assert q.initial['mts']=={'epoch':3}
                assert all(events.index(('prepare',i))<events.index(('ADC',f'r{i//3+1}_reset')) for i in (1,4,7))
run();run(True)
print('PASS: nine phases, one exclusive preparation write each, exactly3 resets/baselines, failure prevents continuation')
