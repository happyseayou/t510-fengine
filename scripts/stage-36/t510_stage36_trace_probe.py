#!/usr/bin/env python3
"""Read-only boundary observations around the existing stopped-board operations."""
import contextlib
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import t510_stage36_init_probe as base


class Recorder:
    def __init__(self, directory):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / f'trace-{time.time_ns()}-{os.getpid()}.jsonl'
        self.path.touch(exist_ok=False)
        self.rows = []

    def append(self, row):
        with self.path.open('a') as f:
            f.write(json.dumps(row, default=str) + '\n')
            f.flush()
            os.fsync(f.fileno())
        self.rows.append(row)

    def __call__(self, boundary, core):
        started = time.time_ns()
        try:
            status = core.read_status()
            if status['streaming']:
                raise RuntimeError('boundary snapshot requires stopped stream')
            row = dict(boundary=boundary, started_unix_ns=started,
                       calibration=core.read_adc_calibration_status(require=True),
                       tile_power=core.read_rfdc_tile_power_status(),
                       contract=core.read_rfdc_contract(require=False),
                       pl_status=status,
                       note='Stopped readback, not a qualified scientific capture; no cached MTS summary used.')
            row['finished_unix_ns'] = time.time_ns()
            self.append(row)
        except Exception as exc:
            self.append(dict(boundary=boundary, started_unix_ns=started, error=str(exc)))
            raise


def execute(action, recorder=None):
    if action not in ('probe', 'T0', 'P', 'M'):
        raise ValueError('unsupported trace action')
    result = base.execute(action, observer=recorder)
    result['trace_helper_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    if recorder is not None:
        result.update(boundary_trace=recorder.rows, board_trace_path=str(recorder.path))
    return result


if __name__ == '__main__':
    recorder = None
    try:
        action = sys.argv[1]
        if action != 'probe':
            recorder = Recorder(Path(__file__).parent / 'traces')
        with contextlib.redirect_stdout(sys.stderr):
            result = execute(action, recorder)
        print(json.dumps(result, default=str))
    except Exception as exc:
        print(json.dumps(dict(ok=False, error=f'{type(exc).__name__}: {exc}',
                              board_trace_path=str(recorder.path) if recorder else None)))
        raise
