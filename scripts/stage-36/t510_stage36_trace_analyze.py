#!/usr/bin/env python3
"""Validate and summarize calibration changes at recorded operation boundaries."""
import json
from pathlib import Path


def validate_trace(action, rows):
    expected = ['before_operation', 'before_mts', 'after_mts'] if action == 'M' else [
        'before_operation', 'before_reset', 'after_reset' if action == 'T0' else 'no_reset_control',
        'before_mts', 'after_mts', 'after_prepare']
    if [r['boundary'] for r in rows] != expected:
        raise RuntimeError(f'incomplete trace for {action}')
    for row in rows:
        if row.get('error') or row['pl_status']['streaming']:
            raise RuntimeError('invalid boundary observation')
        channels = row['calibration']['channels']
        if sorted(c['adc'] for c in channels) != list(range(8)):
            raise RuntimeError('incomplete ADC boundary calibration')
        for c in channels:
            if (c['tile'], c['block']) != (c['adc']//2, c['adc']%2):
                raise RuntimeError('unexpected ADC mapping')


def analyze_boundaries(evidence, phases):
    evidence = Path(evidence)
    changes = []
    for phase in phases:
        if phase['group'] == 'S':
            continue
        result = json.loads((evidence/f"phase_{phase['index']:02d}_intervention.json").read_text())
        rows = result['boundary_trace']
        validate_trace(phase['group'], rows)
        for before, after in zip(rows, rows[1:]):
            b = {c['adc']:c['coefficients'] for c in before['calibration']['channels']}
            a = {c['adc']:c['coefficients'] for c in after['calibration']['channels']}
            changes.append(dict(phase=phase['label'], short_gate=phase['short_gate'],
                from_boundary=before['boundary'], to_boundary=after['boundary'],
                changed_adc_by_bank={bank:[i for i in range(8) if a[i][bank] != b[i][bank]]
                                     for bank in ('ocb1','ocb2','gcb','tscb')},
                temperature_before=before['calibration'].get('temperature_c'),
                temperature_after=after['calibration'].get('temperature_c')))
    with (evidence/'boundary_changes.json').open('x') as f:
        json.dump(dict(rows=changes, interpretation='Readback change locations, not proof of the instant visibility changed; no scientific capture between Reset and MTS.'), f, indent=2)
    (evidence/'RETURN_TO_MAIN_QUESTION.md').write_text(
        '# Return to the main investigation\n\n'
        'This bounded queue ends after three repetitions per intervention. Do not automatically add resets to hunt a desired baseline.\n\n'
        'First assess whether T0-to-ADC2/3 cross-tile change reproduced, including starting correlation. '
        'If absent, report not reproduced; low initial correlation limits sensitivity to the previously observed drop. '
        'If present, inspect Reset/prepare/MTS boundary readbacks; snapshots alone cannot time-localize a visibility jump.\n\n'
        'Then return to the calibration hypothesis: decide whether coefficient replay is justified as a controlled diagnostic, '
        'rather than assuming OCB2 is causal. Finally validate a known common input before calling reduced noise correlation an improvement. '
        'No automatic coefficient writes or extra hardware campaigns are included.\n')
