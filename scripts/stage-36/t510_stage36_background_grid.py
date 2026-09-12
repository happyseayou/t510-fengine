#!/usr/bin/env python3
"""Read-only training-duration/frequency-width screen. A6 is not used to select."""
import argparse,hashlib,json
from pathlib import Path
import numpy as np
from t510_stage36_tile_analyze import PAIRS
DURATIONS=(1,5,10,30,60)
WIDTHS=(1,3,5,9,17)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def smooth(v,width):
    # No wrap, no zero padding: truncated neighbourhood at physical band edges.
    cs=np.pad(np.cumsum(v,axis=-1),((0,0),(1,0)))
    k=np.arange(v.shape[-1]);lo=np.maximum(0,k-width//2);hi=np.minimum(v.shape[-1],k+width//2+1)
    return (cs[:,hi]-cs[:,lo])/(hi-lo)
def score(v,b,p):
    norm=np.stack([np.sqrt(p[a]*p[c]) for a,c in PAIRS])
    residual=abs(v-b)
    region=100*residual[:,3072:3329]/norm[:,3072:3329]
    return dict(median_pct=float(np.median(region)),p90_pct=float(np.percentile(region,90)),
        median_count2=float(np.median(residual[:,3072:3329])),pair_median_pct=np.median(region,axis=1).tolist())
def main(root,out):
    out.mkdir(parents=True,exist_ok=False)
    queue=root/'stage36-dsa45-20260911-queue';state=json.loads((queue/'queue_state.json').read_text())
    assert state['status']=='completed' and state['verification_status']=='PASS'
    mp=queue/'queue_manifest.json';assert sha(mp)==(queue/'queue_manifest.sha256').read_text().split()[0]
    qfiles={x['path']:x for x in json.loads(mp.read_text())['files']}
    ds=root/state['phases'][0]['scan_id'];dm=ds/'dataset_manifest.json'
    assert sha(dm)==state['phases'][0]['manifest']['sha256']==(ds/'dataset_manifest.sha256').read_text().split()[0]
    files={x['path']:x for x in json.loads(dm.read_text())['files']}
    def read(rel,dtype,shape):
        p=ds/rel;assert sha(p)==files[rel]['sha256'] and p.stat().st_size==files[rel]['bytes']
        return np.fromfile(p,dtype=dtype).reshape(shape)
    accum=np.zeros((28,4096),complex);n=np.zeros(4096);templates={}
    for sec in range(60):
        weights=read(f'xcorr.zarr/n_valid_100ms/{sec}.0','<u8',(10,16));assert np.all(weights>0)
        for block in range(16):
            v=read(f'xcorr.zarr/mean_cross_visibility_count2_100ms/{sec}.0.{block}','<c16',(10,28,256))
            sl=slice(block*256,(block+1)*256);w=weights[:,block]
            accum[:,sl]+=np.sum(v*w[:,None,None],axis=0);n[sl]+=w.sum()
        if sec+1 in DURATIONS:templates[sec+1]=accum/n
    def full(label):
        p=queue/'evidence'/f'{label}-fullband.npz';assert sha(p)==qfiles[str(p.relative_to(queue))]['sha256']
        with np.load(p) as z:return {k:z[k].copy() for k in z.files}
    np.testing.assert_allclose(templates[60],full('A0')['visibility_count2'],rtol=1e-11,atol=1e-10)
    candidates={'none':np.zeros_like(accum)}
    for t in DURATIONS:
        for w in WIDTHS:candidates[f't{t}-k{w}']=smooth(templates[t],w)
    results=[];dev={label:full(label) for label in ('A2','A4')}
    for name,b in candidates.items():
        by={label:score(a['visibility_count2'],b,a['power_count2']) for label,a in dev.items()}
        results.append(dict(candidate=name,development=by,objective=float(np.mean([x['median_pct'] for x in by.values()]))))
    ranking=sorted(results,key=lambda x:x['objective']);choice=ranking[0]['candidate']
    selection=dict(primary='Mean of A2 and A4 median |complex residual| normalized by test powers, all28pairs and bins3072..3328.',
        selected=choice,ranking=ranking,training_manifest_sha256=sha(dm),queue_manifest_sha256=sha(mp),
        grid=dict(seconds=DURATIONS,bins=WIDTHS),test_not_used='A6')
    selected_path=out/'selection.json';selected_path.write_text(json.dumps(selection,indent=2))
    # Selection recorded on disk before opening the final A6 test summary.
    hold=full('A6');confirmation={}
    for name in dict.fromkeys(['none','t60-k1',choice]):
        confirmation[name]=score(hold['visibility_count2'],candidates[name],hold['power_count2'])
    np.savez_compressed(out/'selected_template.npz',background=candidates[choice])
    report=dict(selected=choice,selection_sha256=sha(selected_path),confirmation_A6=confirmation,
        pairs=PAIRS,limitations=['Exploratory development on A2/A4; A6 held out from this grid selection but previously inspected in earlier studies.',
        'Same initialization, interleaved DSA conditions, elapsed time and temperature remain confounded.',
        'Frequency smoothing assumes local smoothness; adjacent channels not assumed independent.',
        'Criterion uses60s complex means, not a claim of improved random variance or Allan variance.',
        'Global grid selection is not per-pair deployment approval; compare each pair to no correction.'])
    (out/'results.json').write_text(json.dumps(report,indent=2));print(json.dumps(dict(top5=ranking[:5],confirmation=report),indent=2))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();main(a.root,a.output)
