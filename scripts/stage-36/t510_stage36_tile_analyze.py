#!/usr/bin/env python3
"""Fullband paired complex differences with prespecified spatial partitions."""
import itertools
import json
from pathlib import Path
import numpy as np

PAIRS = list(itertools.combinations(range(8), 2))
TARGETS = {'T0': (0, 1), 'T3': (6, 7)}


def partition(pair, target):
    return 'involved' if set(pair).intersection(TARGETS[target]) else 'untouched'


def load_rho(dataset, seconds):
    z = Path(dataset) / 'xcorr.zarr'
    v = np.zeros((28, 4096), complex)
    p = np.zeros((8, 4096))
    w = np.zeros(4096)
    for sec in range(seconds):
        n = np.fromfile(z / 'n_valid' / f'{sec}.0', dtype='<u8')
        if n.shape != (16,) or np.any(n == 0):
            raise RuntimeError('missing valid frames')
        for block in range(16):
            sl = slice(block * 256, (block + 1) * 256)
            v[:, sl] += np.fromfile(z / 'mean_cross_visibility_count2' / f'{sec}.0.{block}', dtype='<c16').reshape(28, 256) * n[block]
            p[:, sl] += np.fromfile(z / 'mean_auto_power_count2' / f'{sec}.0.{block}', dtype='<f8').reshape(8, 256) * n[block]
            w[sl] += n[block]
    v /= w
    p /= w
    if np.any(p <= 0) or not np.all(np.isfinite(p)) or not np.all(np.isfinite(v)):
        raise RuntimeError('invalid visibility or power')
    rho = np.asarray([v[i] / np.sqrt(p[a] * p[b]) * 100 for i, (a, b) in enumerate(PAIRS)])
    return rho, v, p


def pair_rows(pre, current, post, group, segment, target):
    jump = np.abs(current - pre)
    drift = np.abs(post - current)
    rows = []
    for i, pair in enumerate(PAIRS):
        row = dict(group=group, segment=segment, target_partition=target,
                   pair=list(pair), partition=partition(pair, target))
        for name, sl in [('fullband', slice(None)), ('bins3072to3328', slice(3072, 3329))]:
            row[name] = dict(jump_median_pp=float(np.median(jump[i, sl])),
                             following_control_median_pp=float(np.median(drift[i, sl])),
                             pre_rho_median_pct=float(np.median(abs(pre[i, sl]))),
                             current_rho_median_pct=float(np.median(abs(current[i, sl]))),
                             post_rho_median_pct=float(np.median(abs(post[i, sl]))))
        rows.append(row)
    return rows


def analyze(root, phases, evidence, control_targets=None):
    evidence = Path(evidence)
    output = evidence / 'tile_fullband'
    output.mkdir(exist_ok=False)
    values = {}
    for phase in phases:
        rho, visibility, power = load_rho(Path(root) / phase['scan_id'], phase['duration_seconds'])
        values[phase['scan_id']] = rho
        np.savez_compressed(output / (phase['scan_id'] + '.npz'), rho_pct=rho,
                            visibility_count2=visibility, power_count2=power, pairs=PAIRS)
    rows = []
    for i, phase in enumerate(phases):
        if phase['group'] == 'S':
            continue
        if i == 0 or i + 1 == len(phases) or phases[i-1]['group'] != 'S' or phases[i+1]['group'] != 'S':
            raise RuntimeError('missing bracketing controls')
        for target in ((control_targets or TARGETS) if phase['group'] in ('P', 'M') else [phase['group']]):
            rows += pair_rows(values[phases[i-1]['scan_id']], values[phase['scan_id']],
                              values[phases[i+1]['scan_id']], phase['group'], phase['segment'], target)
    result = {'rows': rows, 'definition': 'absolute complex rho difference in percentage points; weighted complex means before normalization',
              'limitations': 'Three repeats; pairs/bins are not independent trials. Controls inherit state. Whole band has no edge mask; preset science region also reported. No significance threshold.'}
    with (evidence / 'tile_spatial_comparison.json').open('x') as f:
        json.dump(result, f, indent=2, allow_nan=False)
    return result
