#!/usr/bin/env python3
"""Offline current CUDA ring replay; never connects to board or live receiver."""
import argparse, ctypes, ctypes.util, hashlib, itertools, json, mmap
from pathlib import Path
import subprocess, time, traceback
import numpy as np

PAIRS=list(itertools.combinations(range(8),2))
BIN=[0,17,2048,3073,3182,4095]
SLOTS=32768; SLOT=8256; SIZE=4096+16*SLOTS*SLOT

def save(p,x): p.write_text(json.dumps(x,indent=2)+'\n')
def sha(p):
 h=hashlib.sha256()
 with open(p,'rb') as f:
  for b in iter(lambda:f.read(8388608),b''): h.update(b)
 return h.hexdigest()

def replay(raw,out,binary):
 out.mkdir()
 request=out/'request.json'; save(request,{'offline_repeated_witness':True,'seconds':2})
 ring=out/'ring.bin'
 with ring.open('xb') as f: f.truncate(SIZE)
 f=ring.open('r+b'); m=mmap.mmap(f.fileno(),SIZE)
 anchor=ctypes.c_char.from_buffer(m); address=ctypes.addressof(anchor)
 lib=ctypes.CDLL(ctypes.util.find_library('atomic'))
 st=getattr(lib,'__atomic_store_8'); st.argtypes=[ctypes.c_void_p,ctypes.c_uint64,ctypes.c_int]
 ld=getattr(lib,'__atomic_load_8'); ld.argtypes=[ctypes.c_void_p,ctypes.c_int];ld.restype=ctypes.c_uint64
 def put(o,v): st(address+o,int(v),3)
 def get(o): return ld(address+o,2)
 for o,v in {0:0x3152435835333554,8:1,40:0,48:640000000,64:1,72:2,80:1000,88:100,96:len(BIN),104:SLOTS,112:0x556,120:1}.items(): put(o,v)
 for j,b in enumerate(BIN):put(512+j*8,b)
 log=(out/'sidecar.log').open('w')
 proc=subprocess.Popen([str(binary),'--ring',str(ring),'--output',str(out),'--request',str(request)],stdout=log,stderr=subprocess.STDOUT)
 deadline=time.monotonic()+300
 def healthy():
  if proc.poll() is not None: raise RuntimeError('sidecar exited early: '+(out/'sidecar.log').read_text())
  if time.monotonic()>deadline: raise TimeoutError('offline replay deadline')
 try:
  while get(16)!=1: healthy();time.sleep(.02)
  put(16,2)
  # Headers and payload views retain production ABI strides; publication uses release atomics.
  views=[]
  for b in range(16):
   base=4096+b*SLOTS*SLOT
   fields={}
   for name,offset,dtype in [('sample',0,'<u8'),('frame',8,'<u8'),('seq',16,'<u4'),('flags',20,'<u4'),('block',24,'<u2'),('bytes',26,'<u2'),('fft',28,'<u2'),('product',38,'<u2'),('rate',40,'<u4'),('taps',44,'<u2')]:
    fields[name]=np.ndarray((SLOTS,),dtype=dtype,buffer=m,offset=base+offset,strides=(SLOT,))
   fields['payload']=np.ndarray((SLOTS,256,8,2),dtype='<i2',buffer=m,offset=base+64,strides=(SLOT,32,4,2))
   views.append(fields)
  pos=0
  while pos<156250:
   healthy(); n=min(257,156250-pos,SLOTS-pos%SLOTS)
   if any(pos+n-get(256+b*8)>SLOTS for b in range(16)):time.sleep(.001);continue
   indices=np.arange(pos,pos+n); sl=slice(pos%SLOTS,pos%SLOTS+n)
   data=raw[indices%len(raw)]
   for b,v in enumerate(views):
    for name,value in [('sample',indices*4096),('frame',indices*16+b),('seq',indices*16+b),('flags',1024),('block',b),('bytes',8192),('fft',0x556),('product',0xf101),('rate',320000000),('taps',8)]:v[name][sl]=value
    v['payload'][sl]=data[:,:,b*256:(b+1)*256,:].transpose(0,2,1,3)
    put(128+b*8,pos+n)
   pos+=n
  put(56,65535)
  assert proc.wait(timeout=max(1,deadline-time.monotonic()))==0,(out/'sidecar.log').read_text()
  assert get(16)==4 and all(get(256+b*8)==156250 for b in range(16))
 finally:
  if proc.poll() is None:
   put(24,1)
   try:proc.wait(timeout=10)
   except subprocess.TimeoutExpired:proc.kill();proc.wait()
  log.close()
  # Evidence ring retained on failure; successful ring is disposable repeated input.
 if get(16)==4: ring.unlink()
 z=out/'xcorr.zarr'
 edges=(np.arange(21,dtype=np.int64)*32000000+4095)//4096
 counts=np.diff(edges)
 auto=np.empty((20,8,4096));cross=np.empty((20,28,4096),complex)
 def sums(x):
  cumulative=np.cumsum(x,axis=0,dtype=np.int64)
  prefix=np.vstack((np.zeros((1,4096),dtype=np.int64),cumulative))
  at=prefix[edges%len(raw)]+(edges//len(raw))[:,None]*prefix[-1]
  return np.diff(at,axis=0)/counts[:,None]
 for a in range(8):
  i=raw[:,a,:,0].astype(np.int64);q=raw[:,a,:,1].astype(np.int64)
  auto[:,a]=sums(i*i+q*q)
 for p,(a,b) in enumerate(PAIRS):
  ia=raw[:,a,:,0].astype(np.int64);qa=raw[:,a,:,1].astype(np.int64)
  ib=raw[:,b,:,0].astype(np.int64);qb=raw[:,b,:,1].astype(np.int64)
  cross[:,p]=sums(ia*ib+qa*qb)+1j*sums(qa*ib-ia*qb)
 maximum=0.;checked=0
 def check(got,want):
  nonlocal maximum,checked
  assert got.shape==want.shape,(got.shape,want.shape)
  err=float(np.max(abs(got-want)));maximum=max(maximum,err);checked+=got.size
  assert np.allclose(got,want,rtol=0,atol=1e-10),err
 assert np.array_equal(np.fromfile(z/'pair_index/0.0',dtype='u1').reshape(28,2),PAIRS)
 for second in range(2):
  rows=slice(second*10,(second+1)*10);w=counts[rows]
  check(np.fromfile(z/'n_valid'/f'{second}.0',dtype='<u8'),np.full(16,78125))
  for name in ('n_valid_100ms','focus_n_valid'):
   check(np.fromfile(z/name/f'{second}.0',dtype='<u8').reshape(10,16),np.repeat(w[:,None],16,axis=1))
  for name,start in [('sample0_start',second*320000000),('sample0_end',(second+1)*320000000)]:check(np.fromfile(z/name/str(second),dtype='<u8'),np.array([start]))
  for kind,reference,dtype,n in [('auto_power',auto,'<f8',8),('cross_visibility',cross,'<c16',28)]:
   base='mean_'+kind+'_count2'
   for b in range(16):
    want=reference[rows,:,b*256:(b+1)*256]
    check(np.fromfile(z/(base+'_100ms')/f'{second}.0.{b}',dtype=dtype).reshape(10,n,256),want)
    check(np.fromfile(z/base/f'{second}.0.{b}',dtype=dtype).reshape(n,256),np.sum(w[:,None,None]*want,axis=0)/78125)
   check(np.fromfile(z/('focus_'+base)/f'{second}.0.0',dtype=dtype).reshape(10,n,len(BIN)),reference[rows][:,:,BIN])
 return {'status':'PASS','max_abs_error_count2':maximum,'values_checked':checked,'frames':156250,'ring_wraps':4,'seconds':2,'repeated_raw_frames':len(raw),'scope':'production sidecar ring through Zarr, not UDP receiver or historical binary'}

def main():
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);args=p.parse_args()
 out=args.output;out.mkdir(exist_ok=False)
 binary=Path('/opt/t510-time-rx/current/t510_xcorr_cuda')
 state={'status':'running'};save(out/'state.json',state)
 try:
  result={'binary':str(binary),'binary_sha256':sha(binary),'stages':{}}
  for s in (35,36):
   state['phase']=f'stage{s}';save(out/'state.json',state)
   cmd=subprocess.check_output(['systemctl','show','-p','ExecStart','--value',f't510-stage{s}-explorer.service'],text=True)
   cp=Path(cmd.split('--config ')[1].split()[0]);cfg=json.loads(cp.read_text())
   source=json.loads(Path(cfg['simple_raw_index_manifest']).read_text())
   rec=next(iter(source['spec'].values()));path=Path(rec['iq16_npy'])
   assert sha(path)==rec['iq16_npy_sha256'];raw=np.load(path,mmap_mode='r');assert raw.shape==(4096,8,4096,2)
   save(out/f'stage{s}_config.json',cfg)
   save(out/f'stage{s}_raw_manifest.json',source)
   scan=Path(cfg['cross_scan'])
   for filename in ('request.json','dataset_manifest.json'):
    if (scan/filename).exists():save(out/f'stage{s}_cross_{filename}',json.loads((scan/filename).read_text()))
   result['stages'][str(s)]=replay(raw,out/f'stage{s}',binary)
   result['stages'][str(s)]['raw_sha256']=rec['iq16_npy_sha256']
   save(out/'result.json',result)
  assert sha(binary)==result['binary_sha256'],'binary changed during replay'
  state={'status':'completed','result':'PASS'}
 except Exception:
  state={'status':'failed','error':traceback.format_exc()};raise
 finally:save(out/'state.json',state)
if __name__=='__main__':main()
