#!/usr/bin/env python3
"""Stopped TG-input DSA preparation; TG must remain off during P/T0/ADC operations."""
import contextlib
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import t510_stage36_init_probe as base

SELECTED = (0, 2)
ATTENUATION_DB = 20.0


def snapshot(core):
    status = core.read_status()
    if status['streaming'] or int(status['core_version']) != 0x10036:
        raise RuntimeError('requires stopped current core')
    if int(core.ctrl.read(core.regs.DAC_ENABLE_MASK)):
        raise RuntimeError('requires muted DACs')
    return {'unix_ns':time.time_ns(), 'streaming':False, 'dac_enable_mask':0,
            'rows':[dict(adc=i, tile=i//2, block=i%2,
                         dsa=dict(core.rfdc.adc_tiles[i//2].blocks[i%2].DSA)) for i in range(8)]}


def check(value, original=None):
    if [r['adc'] for r in value['rows']] != list(range(8)):
        raise RuntimeError('DSA channel mapping mismatch')
    for row in value['rows']:
        i = row['adc']; d = row['dsa']
        if i in SELECTED:
            if abs(float(d['Attenuation']) - ATTENUATION_DB) > 1e-6 or int(d['DisableRTS']) != 1:
                raise RuntimeError(f'ADC{i} DSA readback mismatch: {d}')
        elif original is not None and d != original['rows'][i]['dsa']:
            raise RuntimeError(f'untargeted ADC{i} DSA changed')


def apply(core, original):
    snapshot(core)  # Never write during streaming.
    for i in SELECTED:
        block = core.rfdc.adc_tiles[i//2].blocks[i%2]
        value = dict(block.DSA)
        value.update(Attenuation=ATTENUATION_DB, DisableRTS=1)
        block.DSA = value
    result = snapshot(core)
    check(result, original)
    return result


class Journal:
    def __init__(self, directory):
        directory = Path(directory); directory.mkdir(parents=True, exist_ok=True)
        self.path = directory/f'dsa-{time.time_ns()}-{os.getpid()}.jsonl'
        self.path.touch(exist_ok=False)
        self.rows = []; self.original = None

    def append(self, boundary, **fields):
        row = dict(boundary=boundary, **fields)
        with self.path.open('a') as f:
            f.write(json.dumps(row, default=str)+'\n'); f.flush(); os.fsync(f.fileno())
        self.rows.append(row)

    def __call__(self, boundary, core):
        try:
            value = snapshot(core)
            self.append(boundary, snapshot=value)
            if boundary == 'before_operation':
                self.original = value
                # Every other channel must retain the independent-termination setup.
                if any(float(r['dsa']['Attenuation']) != 0 for r in value['rows'] if r['adc'] not in SELECTED):
                    raise RuntimeError('unexpected other-channel attenuation')
                self.append('initial_dsa_applied', snapshot=apply(core, value))
            elif boundary == 'after_reset':
                # Record the actual Reset result before reapplying the intended experiment setting.
                self.append('post_reset_dsa_applied', snapshot=apply(core, self.original))
            else:
                check(value, self.original)
        except Exception as exc:
            self.append(boundary+'_failed', error=str(exc))
            raise


def execute(action, journal=None):
    if action not in ('probe', 'P', 'T0', 'ADC'):
        raise ValueError('unsupported DSA action')
    if action == 'probe':
        with base.hw._configure_hardware_guard(True):
            c = base.hw._controller(base.hw._load_saved_configure_request())
            value = snapshot(c.require_core())
        return dict(ok=True, action=action, snapshot=value,
                    helper_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    if journal is None:
        raise ValueError('DSA operation requires durable journal')
    result = base.execute(action, observer=journal)
    result.update(dsa_journal=journal.rows, board_journal_path=str(journal.path),
                  tg_helper_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  physical_input='SSA TG through XQY-PS2-DC/3-SE to ADC0/2; TG OFF confirmed by operator',
                  attenuation_db_by_adc=[20,0,20,0,0,0,0,0])
    return result


if __name__ == '__main__':
    journal = None
    try:
        action = sys.argv[1]
        if action != 'probe':
            journal = Journal(Path(__file__).parent/'dsa-journals')
        with contextlib.redirect_stdout(sys.stderr):
            result = execute(action, journal)
        print(json.dumps(result, default=str))
    except Exception as exc:
        print(json.dumps(dict(ok=False, error=f'{type(exc).__name__}: {exc}',
                              board_journal_path=str(journal.path) if journal else None)))
        raise
