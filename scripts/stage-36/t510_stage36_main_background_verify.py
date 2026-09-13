#!/usr/bin/env python3
"""Read-only numerical acceptance for historical main-report holdouts."""
import argparse
import json
from pathlib import Path
import numpy as np
from t510_stage36_explorer import SimpleData


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    data = SimpleData(args.root / 'app_config.json', args.root / 'helpers')
    checks = []
    for group in ('original', 'repeat1', 'repeat2'):
        for pair in ((0, 1), (5, 7)):
            for cadence in (100, 1000):
                v, a, b, n = data.cross_base(pair, 3073, cadence, group)
                native, _, _, weights = data.cross_base(pair, 3073, 100, group)
                bg = np.sum(native[:600] * weights[:600]) / weights[:600].sum()
                q = {'group': [group], 'pair': ['-'.join(map(str,pair))], 'bins': ['3073'], 'cadence_ms': [str(cadence)]}
                corrected = data.fengine_long_pair({**q, 'correction': ['subtract']})
                start = 60000 // cadence
                row = corrected['series'][0]
                np.testing.assert_allclose(row['amplitude_count2'], np.abs(v[start:] - bg), rtol=1e-12)
                np.testing.assert_allclose(row['phase_deg'], np.angle(v[start:] - bg, deg=True), atol=1e-10)
                assert len(corrected['time_s']) == 840000 // cadence
                assert corrected['time_s'][0] == 60 + cadence / 2000
                for scale in ('absolute', 'relative'):
                    results = []
                    for correction in ('raw', 'subtract'):
                        result = data.allan({**q, 'subject': ['pair'], 'window': ['holdout'], 'correction': [correction], 'scale': [scale], 'form': ['variance']})
                        assert result['group'] == group
                        assert result['source']['scan_id'] == data.cross_groups[group]['path'].name
                        values = v[start:] - (bg if correction == 'subtract' else 0)
                        for point in result['series'][0]['points']:
                            m = point['m']
                            # Independent convolution reference, not the production prefix-sum helper.
                            w = np.ones(m)
                            den = np.convolve(n[start:], w, 'valid')
                            z = np.convolve(values*n[start:], w, 'valid') / den
                            if scale == 'relative':
                                pa = np.convolve(a[start:]*n[start:], w, 'valid') / den
                                pb = np.convolve(b[start:]*n[start:], w, 'valid') / den
                                z = 100*z / np.sqrt(pa*pb)
                            reference = np.mean(np.abs(z[m:] - z[:-m])**2) / 2
                            np.testing.assert_allclose(point['variance'], reference, rtol=1e-8, atol=1e-12)
                            assert point['N'] == len(values)
                        results.append([p['variance'] for p in result['series'][0]['points']])
                    if scale == 'absolute':
                        np.testing.assert_allclose(*results, rtol=1e-9, atol=1e-12)
                checks.append({'group': group, 'pair': pair, 'cadence_ms': cadence, 'status': 'PASS'})
    print(json.dumps({'status': 'PASS', 'checks': checks}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
