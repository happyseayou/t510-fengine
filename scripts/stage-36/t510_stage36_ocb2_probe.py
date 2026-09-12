#!/usr/bin/env python3
"""Journaled ADC6 OCB2 experiment. No reset, clock, DSA or direct register writes."""
import sys,os,json,time,contextlib,hashlib
from pathlib import Path
sys.path.insert(0,'/home/xilinx/t510-stage36-tg-repeat03')
import t510_stage36_tg_dsa_probe as dsa
ADC=6
ROOT=Path(__file__).resolve().parent

def snapshot(core):
 import xrfdc
 v=dsa.snapshot(core);dsa.check(v)
 cal=core.read_adc_calibration_status(require=True)
 for row,c in zip(v['rows'],cal['channels']):
  assert row['adc']==c['adc']
  row['coefficients']=c['coefficients'];row['physical']=[]
  for physical in (row['block']*2,row['block']*2+1):
   addr=0x16000+row['tile']*0x4000+physical*0x400
   regs=[int(core.rfdc.read(addr+off))&0xffff for off in (0x204,0x20c,0x214,0x21c)]
   row['physical'].append(dict(block=physical,override=int(core.rfdc.read(addr+0x150))&1,coefficients=regs))
  packed=[row['physical'][0]['coefficients'][i]|row['physical'][1]['coefficients'][i]<<16 for i in range(4)]
  if packed!=c['coefficients']['ocb2'][:4]:raise RuntimeError('physical coefficient mapping differs from API')
  p=xrfdc._ffi.new('u32 *');core.rfdc.adc_tiles[row['tile']].blocks[row['block']]._call_function('GetIntrStatus',p)
  row['adc_error_bits']=int(p[0])&0xFCFF0FFF
 return v

def execute(action):
 import xrfdc
 journal=ROOT/'journals';journal.mkdir(exist_ok=True)
 jp=journal/f'{time.time_ns()}-{action}.jsonl'
 def log(event,**data):
  with jp.open('a') as f:f.write(json.dumps(dict(event=event,**data))+'\n');f.flush();os.fsync(f.fileno())
 with dsa.base.hw._configure_hardware_guard(True):
  core=dsa.base.hw._controller(dsa.base.hw._load_saved_configure_request()).require_core()
  before=snapshot(core);log('before',snapshot=before)
  if any(r['adc_error_bits'] for r in before['rows']):raise RuntimeError('RFDC errors; preserve without clearing')
  if action=='snapshot':
   if any(p['override'] for r in before['rows'] for p in r['physical']):raise RuntimeError('pre-existing OCB2 override')
   with (ROOT/'A.json').open('x') as f:json.dump(dict(adc=ADC,coefficients=before['rows'][ADC]['coefficients']['ocb2']),f)
  elif action in ('A','B','release'):
   a=json.loads((ROOT/'A.json').read_text());assert a['adc']==ADC
   # All untargeted overrides must remain clear.
   if any(p['override'] for r in before['rows'] if r['adc']!=ADC for p in r['physical']):raise RuntimeError('untargeted override')
   if action=='release':
    status=int(xrfdc._lib.XRFdc_DisableCoefficientsOverride(core.rfdc._instance,ADC//2,ADC%2,1))
   else:
    target=json.loads((ROOT/(action+'.json')).read_text());assert target['adc']==ADC
    values=target['coefficients'];assert len(values)==8 and values[4:]==[0]*4 and all(0<=v<=0xffffffff for v in values)
    coeff=xrfdc._ffi.new('XRFdc_Calibration_Coefficients*')
    for i,v in enumerate(values):setattr(coeff,f'Coeff{i}',v)
    log('write_intent',adc=ADC,calibration_block=1,coefficients=values)
    status=int(xrfdc._lib.XRFdc_SetCalCoefficients(core.rfdc._instance,ADC//2,ADC%2,1,coeff))
   log('api_return',status=status)
   if status:raise RuntimeError('OCB2 API rejected')
  elif action!='probe':raise ValueError(action)
  after=snapshot(core);log('after',snapshot=after)
  if action in ('A','B','release'):
   if any(p['override']!=(0 if action=='release' else 1) for p in after['rows'][ADC]['physical']):raise RuntimeError('override readback mismatch')
   if action!='release' and after['rows'][ADC]['coefficients']['ocb2']!=values:raise RuntimeError('coefficient readback mismatch')
   for i in range(8):
    if after['rows'][i]['dsa']!=before['rows'][i]['dsa']:raise RuntimeError('DSA changed')
    if i!=ADC and after['rows'][i]['physical']!=before['rows'][i]['physical']:raise RuntimeError('untargeted OCB2 changed')
  if any(r['adc_error_bits'] for r in after['rows']):raise RuntimeError('RFDC errors after operation')
 return dict(ok=True,action=action,before=before,rows=after['rows'],journal=str(jp),helper_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
if __name__=='__main__':
 with contextlib.redirect_stdout(sys.stderr):result=execute(sys.argv[1])
 print(json.dumps(result))
