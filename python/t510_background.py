"""Fixed complex visibility background calibration; acquisition data remain immutable.

Caller supplies an acquisition-bound context. No inference from sky data, no
cross-initialization matching and no implicit extension of validity.
"""
from __future__ import annotations
import hashlib,json
from pathlib import Path
import numpy as np

IDENTITY=('initialization_epoch','wiring_id','configuration_sha256','core_version','bitstream_sha256','pair_order','frequency_bins')
def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)
def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def validate_context(c):
 for k in IDENTITY+('source_manifest_sha256','source_id','start_unix_s','end_unix_s','role'):
  if k not in c or c[k] is None or c[k]=='':raise ValueError('missing context: '+k)
 if not np.isfinite([c['start_unix_s'],c['end_unix_s']]).all() or c['end_unix_s']<=c['start_unix_s']:raise ValueError('invalid acquisition time')
 for k in ('configuration_sha256','bitstream_sha256','source_manifest_sha256'):
  if len(c[k])!=64 or any(ch not in '0123456789abcdef' for ch in c[k]):raise ValueError('invalid SHA: '+k)
 if c['role'] not in ('reference','target'):raise ValueError('invalid role')
 if not c['pair_order'] or not c['frequency_bins']:raise ValueError('empty geometry')
def validate_arrays(v,w,c):
 validate_context(c);v=np.asarray(v);w=np.asarray(w)
 if v.ndim!=3 or v.shape[1:]!=(len(c['pair_order']),len(c['frequency_bins'])) or w.shape!=(v.shape[0],v.shape[2]):raise ValueError('visibility/weight shape mismatch')
 if not np.iscomplexobj(v) or not np.isfinite(v).all() or not np.isfinite(w).all() or np.any(w<=0):raise ValueError('nonfinite or invalid weights')
 return v,w

def fit(v,w,context,output,*,valid_for_seconds=300):
 v,w=validate_arrays(v,w,context)
 if context['role']!='reference':raise ValueError('only explicit reference data may train background')
 if not np.isfinite(valid_for_seconds) or not 0<valid_for_seconds<=86400:raise ValueError('invalid validity policy')
 bg=(v*w[:,None,:]).sum(axis=0)/w.sum(axis=0)
 out=Path(output);out.mkdir(parents=True,exist_ok=False)
 np.savez_compressed(out/'background.npz',background=bg,weights=w.sum(axis=0))
 m=dict(format='T510_COMPLEX_BACKGROUND_V1',context=context,valid_until_unix_s=context['end_unix_s']+valid_for_seconds,validity_note='Operator policy, not a measured guarantee; external state changes invalidate the template.',method='per-bin weighted complex mean',training_samples=v.shape[0],background_sha256=digest(out/'background.npz'))
 (out/'template.json').write_text(canonical(m));(out/'template.sha256').write_text(digest(out/'template.json')+'\n');return m

def load_template(path):
 p=Path(path);m=json.loads((p/'template.json').read_text())
 if digest(p/'template.json')!=(p/'template.sha256').read_text().strip():raise ValueError('template manifest SHA mismatch')
 if m.get('format')!='T510_COMPLEX_BACKGROUND_V1' or digest(p/'background.npz')!=m['background_sha256']:raise ValueError('template payload SHA mismatch')
 validate_context(m['context'])
 with np.load(p/'background.npz',allow_pickle=False) as z:b=z['background'].copy()
 if b.shape!=(len(m['context']['pair_order']),len(m['context']['frequency_bins'])) or not np.iscomplexobj(b) or not np.isfinite(b).all():raise ValueError('invalid template array')
 return m,b

def compatibility(m,c):
 validate_context(c);old=m['context'];reasons=[]
 for k in IDENTITY:
  if canonical(old[k])!=canonical(c[k]):reasons.append(k+' mismatch')
 if c['start_unix_s']<old['end_unix_s']:reasons.append('target precedes/overlaps reference training')
 if c['end_unix_s']>m['valid_until_unix_s']:reasons.append('template expired at target acquisition')
 return reasons

def apply(v,w,context,*,template=None,mode='auto'):
 v,w=validate_arrays(v,w,context)
 if mode not in ('auto','required','off'):raise ValueError('invalid mode')
 meta=dict(mode=mode,source_id=context['source_id'],source_manifest_sha256=context['source_manifest_sha256'],raw_preserved=True,status='raw_only',reasons=[])
 if mode=='off':meta['reasons']=['explicitly disabled'];return None,meta
 if template is None:meta['reasons']=['no template supplied']
 else:
  # Corrupt artifacts are errors, never silently downgraded to raw-only.
  m,b=load_template(template);meta['template_sha256']=digest(Path(template)/'template.json');meta['reasons']=compatibility(m,context)
  if not meta['reasons']:meta['status']='corrected';return v-b[None,:,:],meta
 if mode=='required':raise ValueError('; '.join(meta['reasons']))
 return None,meta

def save_product(path,v,w,context,*,template=None,mode='auto'):
 corrected,meta=apply(v,w,context,template=template,mode=mode)
 out=Path(path);out.mkdir(parents=True,exist_ok=False)
 meta['context']=context
 if corrected is not None:
  np.savez_compressed(out/'corrected.npz',visibility=corrected,weights=w)
  meta['corrected_sha256']=digest(out/'corrected.npz')
 meta['format']='T510_BACKGROUND_PRODUCT_V1'
 (out/'product.json').write_text(canonical(meta));(out/'product.sha256').write_text(digest(out/'product.json')+'\n');return meta
