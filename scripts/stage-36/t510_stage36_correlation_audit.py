#!/usr/bin/env python3
"""Read-only full-band correlation comparison and independent IQ cross-product audit."""
import argparse
import hashlib
import itertools
import json
from pathlib import Path
import subprocess
import traceback
import urllib.request
import numpy as np

PAIRS = list(itertools.combinations(range(8), 2))
BINS = [3072, 3073, 3074, 3134, 3182, 3328]
def read(p):
    return json.loads(Path(p).read_text())
def save(p, x):
    Path(p).write_text(json.dumps(x, ensure_ascii=False, indent=2) + '\n')
def sha(p):
    h = hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda: f.read(8388608), b''): h.update(b)
    return h.hexdigest()
def api(stage, path):
    with urllib.request.urlopen(f'http://127.0.0.1:80{stage}' + path, timeout=120) as r:
        return json.load(r)

def audit(stage, out):
    cmd = subprocess.check_output(['systemctl','show','-p','ExecStart','--value',
                                  f't510-stage{stage}-explorer.service'], text=True)
    config_path = Path(cmd.split('--config ')[1].split()[0])
    cfg = read(config_path)
    z = Path(cfg['cross_scan']) / 'xcorr.zarr'
    meta = read(z/'mean_cross_visibility_count2/.zarray')
    assert meta['shape'] == [900,28,4096] and meta['chunks'] == [1,28,256]
    assert meta['compressor'] is None and meta['dtype'] == '<c16'
    vc = np.zeros((28,4096),complex)
    ac = np.zeros((8,4096))
    totals = np.zeros(4096)
    # Retain block averages to measure stability without using a fixed gamma threshold.
    segments = np.zeros((15,28,4096),complex)
    segment_weights = np.zeros((15,4096))
    for second in range(900):
        n = np.fromfile(z/'n_valid'/f'{second}.0', dtype='<u8')
        assert n.shape == (16,) and np.all(n > 0)
        for block in range(16):
            sl = slice(block*256,(block+1)*256)
            v = np.fromfile(z/'mean_cross_visibility_count2'/f'{second}.0.{block}',dtype='<c16').reshape(28,256)
            a = np.fromfile(z/'mean_auto_power_count2'/f'{second}.0.{block}',dtype='<f8').reshape(8,256)
            assert np.isfinite(v).all() and np.isfinite(a).all() and np.all(a > 0)
            vc[:,sl] += v*n[block]; ac[:,sl] += a*n[block]; totals[sl] += n[block]
            segments[second//60,:,sl] += v*n[block]
            segment_weights[second//60,sl] += n[block]
    vc /= totals; ac /= totals
    segments /= segment_weights[:,None,:]
    denom = np.sqrt(np.array([ac[a]*ac[b] for a,b in PAIRS]))
    rho = vc/denom
    # Scatter of 60 s blocks is descriptive; do not assume independent blocks.
    scatter = np.sqrt(np.mean(abs(segments-vc)**2,axis=0))
    np.savez(out/f'stage{stage}_fullband.npz', visibility=vc, auto=ac, rho=rho,
             block60_visibility=segments, block60_scatter=scatter)

    manifest_path = Path(cfg['simple_raw_index_manifest'])
    record = next(iter(read(manifest_path)['spec'].values()))
    rawpath = Path(record['iq16_npy'])
    assert sha(rawpath) == record['iq16_npy_sha256']
    raw = np.load(rawpath, mmap_mode='r')
    assert raw.shape == (4096,8,4096,2)
    rawv = np.zeros((28,4096),complex); rawa = np.zeros((8,4096))
    # Independent int64 component arithmetic, no application complex-multiply helper.
    for start in range(0,4096,128):
        i = raw[start:start+128,:,:,0].astype(np.int64)
        q = raw[start:start+128,:,:,1].astype(np.int64)
        rawa += np.sum(i*i+q*q,axis=0)
        for p,(a,b) in enumerate(PAIRS):
            real = np.sum(i[:,a]*i[:,b]+q[:,a]*q[:,b],axis=0)
            imag = np.sum(q[:,a]*i[:,b]-i[:,a]*q[:,b],axis=0)
            rawv[p] += real+1j*imag
    rawv /= 4096; rawa /= 4096
    rawrho = rawv/np.sqrt(np.array([rawa[a]*rawa[b] for a,b in PAIRS]))
    np.savez(out/f'stage{stage}_raw.npz', visibility=rawv, auto=rawa, rho=rawrho)
    checks = []
    for a,b in PAIRS:
        response = api(stage, f'/api/v2/timeseries?domain=fengine_raw_pair&pair={a}-{b}&bins=3073,3182&bucket=16')
        for row in response['series']:
            k = row['global_bin']
            i = raw[:,:,k,0].astype(np.int64); q = raw[:,:,k,1].astype(np.int64)
            real = (i[:,a]*i[:,b]+q[:,a]*q[:,b]).reshape(-1,16).mean(axis=1)
            imag = (q[:,a]*i[:,b]-i[:,a]*q[:,b]).reshape(-1,16).mean(axis=1)
            observed = np.array(row['amplitude'])*np.exp(1j*np.deg2rad(row['phase_deg']))
            err = float(np.max(abs(observed-(real+1j*imag))))
            assert err < 1e-9, (a,b,k,err)
            checks.append(dict(pair=[a,b],bin=k,max_complex_error=err))
    # Explicitly avoid claiming a same-sample CUDA check from a separate witness.
    result = dict(stage=stage,config=str(config_path),config_sha256=sha(config_path),
                  dataset_manifest_sha256=sha(Path(cfg['cross_scan'])/'dataset_manifest.json'),
                  raw_sha256=sha(rawpath),raw_api_checks=checks,
                  production_same_sample_check='NOT_ESTABLISHED: raw witness is a separate capture',
                  raw_shape=list(raw.shape),selected=[])
    for p,(a,b) in enumerate(PAIRS):
        result['selected'].append(dict(pair=f'{a}-{b}',same_tile=a//2==b//2,
            gamma_900s=float(abs(rho[p,3073])),phase_deg=float(np.angle(rho[p,3073],deg=True)),
            visibility_abs=float(abs(vc[p,3073])),raw_gamma=float(abs(rawrho[p,3073])),
            raw_phase_deg=float(np.angle(rawrho[p,3073],deg=True)),
            fullband_median_gamma=float(np.median(abs(rho[p]))),
            fraction_bins_gamma_above_005=float(np.mean(abs(rho[p])>0.05))))
    save(out/f'stage{stage}_summary.json',result)
    return result

def plot_report(out, results):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    f = 200 + np.where(np.arange(4096)<2048,np.arange(4096),np.arange(4096)-4096)*.078125
    order = np.argsort(f)
    arrays = [np.load(out/f'stage{s}_fullband.npz') for s in (35,36)]
    vmax = max(float(np.quantile(abs(a['rho']),.995)*100) for a in arrays)
    fig,axes=plt.subplots(2,1,figsize=(14,13),layout='constrained')
    for ax,s,a in zip(axes,(35,36),arrays):
        im=ax.imshow(abs(a['rho'][:,order])*100,aspect='auto',origin='lower',
                     extent=[f[order][0],f[order][-1],-.5,27.5],vmin=0,vmax=vmax)
        ax.set_yticks(range(28),[f'{x}-{y}' for x,y in PAIRS],fontsize=7)
        ax.set_title(f'Stage {s}: abs(weighted mean V) / sqrt(mean Pa mean Pb), %')
        ax.set_xlabel('RF MHz'); fig.colorbar(im,ax=ax,label='Correlation % (clipped at shared 99.5th percentile)')
    fig.savefig(out/'fullband_pairs.png',dpi=150);plt.close(fig)
    fig,axes=plt.subplots(2,2,figsize=(12,10),layout='constrained')
    for column,(s,a) in enumerate(zip((35,36),arrays)):
        matrix=np.eye(8,dtype=complex)
        for p,(x,y) in enumerate(PAIRS):matrix[x,y]=a['rho'][p,3073];matrix[y,x]=matrix[x,y].conjugate()
        for row in (0,1):
            values=abs(matrix)*100 if row==0 else np.angle(matrix,deg=True)
            np.fill_diagonal(values,np.nan)
            im=axes[row,column].imshow(values,vmin=0 if row==0 else -180,
                vmax=20 if row==0 else 180,cmap='viridis' if row==0 else 'twilight')
            axes[row,column].set_title(f'Stage {s}, 120.078125 MHz: '+('correlation %' if row==0 else 'phase deg'))
            fig.colorbar(im,ax=axes[row,column])
    fig.savefig(out/'bin3073_matrix.png',dpi=150);plt.close(fig)
    lines=['# Correlation audit','',
           'Weights are valid frame counts. Long rho = mean(V)/sqrt(mean(Pa)*mean(Pb)); not mean(abs(V)).',
           '60 s block scatter is descriptive, not an independent-sample confidence interval.',
           'Raw witnesses and 900 s scans are separate captures: this does NOT certify the production CUDA path against the same raw samples.',
           'Phase colour threshold 0.05 is not a significance test. No hardware root cause is assigned.',
           '', '| Pair | S35 rho % | S36 rho % | S35 phase | S36 phase |','|---|---:|---:|---:|---:|']
    for old,new in zip(results[0]['selected'],results[1]['selected']):
        lines.append(f"| {old['pair']} | {100*old['gamma_900s']:.4f} | {100*new['gamma_900s']:.4f} | {old['phase_deg']:.2f} | {new['phase_deg']:.2f} |")
    lines += ['', '![Full band](fullband_pairs.png)','![Selected bin](bin3073_matrix.png)']
    (out/'report.md').write_text('\n'.join(lines)+'\n')

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    out=args.output;out.mkdir(parents=True,exist_ok=False)
    state={'status':'running','phase':'preflight'}
    save(out/'state.json',state)
    try:
        results=[]
        for stage in (35,36):
            state['phase']=f'stage{stage}_fullband_and_raw';save(out/'state.json',state)
            results.append(audit(stage,out))
        state['phase']='plots_and_comparison';save(out/'state.json',state)
        plot_report(out,results)
        save(out/'manifest.json',{'files':[dict(path=x.name,sha256=sha(x)) for x in sorted(out.iterdir()) if x.name!='state.json']})
        state.update(status='completed',phase=None);save(out/'state.json',state)
    except Exception:
        state.update(status='failed',error=traceback.format_exc());save(out/'state.json',state);raise
if __name__=='__main__':main()
