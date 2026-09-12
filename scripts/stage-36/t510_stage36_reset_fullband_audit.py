#!/usr/bin/env python3
"""Read-only fullband summary of existing selective Reset experiment."""
import json
from pathlib import Path
import sys
import itertools
import numpy as np
root=Path(sys.argv[1]);qid='stage36-adc-dac-20260909'
pairs=list(itertools.combinations(range(8),2));results=[]
for label in ('s08','adc03','s09','dac03','s10'):
 z=root/(qid+'-'+label+'-100s')/'xcorr.zarr'
 v=np.zeros((28,4096),complex);p=np.zeros((8,4096));w=np.zeros(4096)
 for sec in range(100):
  n=np.fromfile(z/'n_valid'/f'{sec}.0',dtype='<u8')
  for block in range(16):
   sl=slice(block*256,(block+1)*256)
   v[:,sl]+=np.fromfile(z/'mean_cross_visibility_count2'/f'{sec}.0.{block}',dtype='<c16').reshape(28,256)*n[block]
   p[:,sl]+=np.fromfile(z/'mean_auto_power_count2'/f'{sec}.0.{block}',dtype='<f8').reshape(8,256)*n[block]
   w[sl]+=n[block]
 v/=w;p/=w
 rho=np.asarray([v[j]/np.sqrt(p[a]*p[b])*100 for j,(a,b) in enumerate(pairs)])
 entry={'scan':label,'pairs':[]}
 # Include full band and predetermined science region; no significance tests.
 for pair in ((1,3),(6,7)):
  x=rho[pairs.index(pair)]
  entry['pairs'].append({'pair':pair,'rho3073_pct':float(abs(x[3073])),
    'fullband_median_rho_pct':float(np.median(abs(x))),
    'fullband_bins_above3pct':int(np.sum(abs(x)>3)),
    'bins3072to3328_median_rho_pct':float(np.median(abs(x[3072:3329]))),
    'bins3072to3328_above3pct':int(np.sum(abs(x[3072:3329])>3))})
 results.append(entry)
print(json.dumps({'scans':results,'note':'3 percent is descriptive, not a significance threshold; all4096 bins included without band-edge masks.'},indent=2))
