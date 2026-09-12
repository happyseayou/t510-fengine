#!/usr/bin/env python3
"""Read-only A0-trained fixed complex background prediction of A2/A4/A6."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
from t510_stage36_tile_analyze import PAIRS

BINS=(3073,3182,3328)
SIZES=(1,2,5,10,20,50,100,200,300,600)

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def metrics(series,weights,background,training_variance,training_effective_n=600):
    out=[]
    for n in SIZES:
        w=weights.reshape(-1,n)
        means=np.sum(series.reshape(-1,n)*w,axis=1)/w.sum(axis=1)
        residual=means-background
        centered=means-np.average(means,weights=w.sum(axis=1))
        q=w.sum(axis=1)/w.sum()
        scatter=float(np.sqrt(np.sum(q*abs(centered)**2)/(1-np.sum(q*q)))) if len(means)>1 else None
        out.append(dict(tau_seconds=n/10,blocks=len(means),residual_complex_rms_count2=float(np.sqrt(np.sum(q*abs(residual)**2))),
            centered_complex_scatter_count2=scatter,
            white_reference_with_training_uncertainty_count2=float(np.sqrt(training_variance*(np.sum(q*np.sum(w*w,axis=1)/w.sum(axis=1)**2)+1/training_effective_n)))))
    return out

def analyze(root,output):
    output.mkdir(parents=True,exist_ok=False)
    qid='stage36-dsa45-20260911';q=root/(qid+'-queue');state=json.loads((q/'queue_state.json').read_text())
    assert state['status']=='completed' and state['verification_status']=='PASS'
    qm=q/'queue_manifest.json';assert sha(qm)==(q/'queue_manifest.sha256').read_text().split()[0]
    qfiles={r['path']:r for r in json.loads(qm.read_text())['files']}
    cache=[];sources=[]
    for i in (0,2,4,6):
        phase=state['phases'][i];dataset=root/phase['scan_id'];mp=dataset/'dataset_manifest.json'
        assert sha(mp)==phase['manifest']['sha256']==(dataset/'dataset_manifest.sha256').read_text().split()[0]
        files={r['path']:r for r in json.loads(mp.read_text())['files']}
        def read(relative,dtype):
            path=dataset/relative;info=files[relative]
            assert path.stat().st_size==info['bytes'] and sha(path)==info['sha256']
            return np.fromfile(path,dtype=dtype)
        npz=q/'evidence'/(phase['label']+'-fullband.npz')
        assert sha(npz)==qfiles[str(npz.relative_to(q))]['sha256']
        with np.load(npz) as z:full={k:z[k].copy() for k in z.files}
        series=np.empty((600,28,3),complex);weights=np.empty((600,3),np.uint64)
        for sec in range(60):
            ns=read(f'xcorr.zarr/n_valid_100ms/{sec}.0','<u8').reshape(10,16)
            for block in sorted({k//256 for k in BINS}):
                values=read(f'xcorr.zarr/mean_cross_visibility_count2_100ms/{sec}.0.{block}','<c16').reshape(10,28,256)
                for j,k in enumerate(BINS):
                    if k//256==block:
                        series[sec*10:sec*10+10,:,j]=values[:,:,k%256];weights[sec*10:sec*10+10,j]=ns[:,block]
        assert np.all(weights>0) and np.all(np.max(weights,axis=0)-np.min(weights,axis=0)<=1)
        mean=np.sum(series*weights[:,None,:],axis=0)/weights.sum(axis=0)
        np.testing.assert_allclose(mean,full['visibility_count2'][:,BINS],rtol=1e-12,atol=1e-11)
        cache.append(dict(label=phase['label'],series=series,weights=weights,full=full,
            midpoint_ms=(phase['capture_status']['started_unix_ms']+phase['capture_status']['finished_unix_ms'])/2))
        sources.append(dict(scan_id=phase['scan_id'],dataset_manifest_sha256=sha(mp),summary_sha256=sha(npz)))
    train=cache[0];background=train['full']['visibility_count2'];curves=[];means=[];band=[]
    variance=np.var(train['series'],axis=0,ddof=1)
    for test in cache[1:]:
        full=test['full'];res=full['visibility_count2']-background
        normalized=np.asarray([100*res[j]/np.sqrt(full['power_count2'][a]*full['power_count2'][b]) for j,(a,b) in enumerate(PAIRS)])
        np.savez_compressed(output/(test['label']+'-prediction.npz'),residual_count2=res,residual_normalized_pct=normalized)
        for j,pair in enumerate(PAIRS):
            band.append(dict(test=test['label'],pair=list(pair),median_abs_residual_fullband_pct=float(np.median(abs(normalized[j]))),
                median_abs_residual_science_band_pct=float(np.median(abs(normalized[j,3072:3329])))))
            for b,k in enumerate(BINS):
                mu=background[j,k];v=full['visibility_count2'][j,k]
                means.append(dict(test=test['label'],pair=list(pair),bin=k,minutes_since_training=(test['midpoint_ms']-train['midpoint_ms'])/60000,
                    training_real_count2=float(mu.real),training_imag_count2=float(mu.imag),
                    test_real_count2=float(v.real),test_imag_count2=float(v.imag),raw_amplitude_count2=float(abs(v)),
                    residual_amplitude_count2=float(abs(v-mu)),residual_normalized_pct=float(abs(normalized[j,k])),
                    residual_over_raw=float(abs(v-mu)/abs(v)) if abs(v)>0 else None))
                tw=train['weights'][:,b].astype(float)
                curves.append(dict(test=test['label'],pair=list(pair),bin=k,points=metrics(test['series'][:,j,b],test['weights'][:,b],mu,variance[j,b],tw.sum()**2/np.sum(tw*tw))))
    # Native 100ms complex values; no interpolation or synthetic extension.
    trend_dir=output/'trends';trend_dir.mkdir()
    for j,pair in enumerate(PAIRS):
        for b,k in enumerate(BINS):
            mu=background[j,k]
            records=[]
            for test in cache[1:]:
                v=test['series'][:,j,b]
                records.append(dict(test=test['label'],real=v.real.tolist(),imag=v.imag.tolist(),
                    n_valid=test['weights'][:,b].tolist()))
            payload=dict(pair=list(pair),bin=k,cadence_ms=100,points=600,
                time_s=((np.arange(600)+0.5)/10).tolist(),
                background_real=float(mu.real),background_imag=float(mu.imag),series=records)
            (trend_dir/f'{pair[0]}-{pair[1]}-{k}.json').write_text(json.dumps(payload,separators=(',',':')))
    result=dict(training='A0 only, fixed complex mean, no holdout refit',sources=sources,means=means,curves=curves,fullband=band,
        qualifications=['Read-file SHA and dataset manifest SHA verified; selected100ms means reproduce fullband60s products.',
            'Residual is complex test visibility minus A0 complex mean, not subtraction of magnitudes.',
            'Subtracting a constant cannot improve centered variance or Allan variance.',
            'White reference assumes independent stationary100ms buckets; includes finite60s training uncertainty; not a significance test.',
            '60s tau has one block: scatter unavailable. No integration across inter-scan gaps.',
            'A scans share settings but intervening B/C/D and elapsed time remain; no new hardware measurements.'])
    (output/'holdout_results.json').write_text(json.dumps(result,indent=2))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(1,2,figsize=(12,4.5),layout='constrained')
    j=PAIRS.index((4,5));mu=background[j,3073]
    axes[0].plot(mu.real,mu.imag,'k*',markersize=12,label='A0 training')
    for label in ('A2','A4','A6'):
        row=next(r for r in means if r['test']==label and r['pair']==[4,5] and r['bin']==3073)
        axes[0].plot(row['test_real_count2'],row['test_imag_count2'],'o',label=label)
        curve=next(r for r in curves if r['test']==label and r['pair']==[4,5] and r['bin']==3073)['points']
        axes[1].loglog([r['tau_seconds'] for r in curve],[r['residual_complex_rms_count2'] for r in curve],'o-',label=label)
    axes[1].loglog([r['tau_seconds'] for r in curve],[r['white_reference_with_training_uncertainty_count2'] for r in curve],'k--',label='Stationary white reference + training error')
    axes[0].set(xlabel='Real visibility (count²)',ylabel='Imaginary visibility (count²)',title='ADC4–ADC5: independent 60s means')
    axes[1].set(xlabel='Integration (s)',ylabel='Complex residual RMS (count²)',title='A0 fixed subtraction: 120.078125 MHz')
    for ax in axes:ax.grid(alpha=.25);ax.legend(fontsize=8)
    fig.savefig(output/'holdout.png',dpi=180);plt.close(fig)
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    result=analyze(a.root,a.output)
    print(json.dumps([r for r in result['means'] if r['pair']==[4,5] and r['bin']==3073],indent=2))
