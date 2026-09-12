#!/usr/bin/env python3
"""ADC-only reset/prepare/MTS with complete DSA preservation and durable journal."""
import contextlib,hashlib,json,os,sys,time
from pathlib import Path
import t510_stage36_init_probe as base
EXPECTED=[20,0,20,0,0,0,0,0]
def snapshot(core):
    import xrfdc
    s=core.read_status()
    if s['streaming'] or int(s['core_version'])!=0x10036 or core.ctrl.read(core.regs.DAC_ENABLE_MASK):
        raise RuntimeError('requires stopped current core and muted DAC')
    rows=[]
    for i in range(8):
        b=core.rfdc.adc_tiles[i//2].blocks[i%2];p=xrfdc._ffi.new('u32 *');b._call_function('GetIntrStatus',p)
        rows.append(dict(adc=i,tile=i//2,block=i%2,dsa=dict(b.DSA),interrupt_status=int(p[0]),adc_error_bits=int(p[0])&0xFCFF0FFF))
    return dict(streaming=False,dac_enable_mask=0,rows=rows,unix_ns=time.time_ns())
def validate(v,reference=None,errors=True):
    if [r['dsa']['Attenuation'] for r in v['rows']]!=EXPECTED:raise RuntimeError('attenuation mismatch')
    if errors and any(r['adc_error_bits'] for r in v['rows']):raise RuntimeError('RFDC error bits present')
    if reference is not None and [r['dsa'] for r in v['rows']]!=[r['dsa'] for r in reference['rows']]:raise RuntimeError('full DSA control state changed')
class Journal:
    def __init__(self):
        d=Path(__file__).parent/'reset-journals';d.mkdir(exist_ok=True)
        self.path=d/f'{time.time_ns()}-{os.getpid()}.jsonl';self.rows=[];self.original=None
    def save(self,label,**data):
        row=dict(label=label,unix_ns=time.time_ns(),**data)
        with self.path.open('a') as f:f.write(json.dumps(row)+'\n');f.flush();os.fsync(f.fileno())
        self.rows.append(row)
    def __call__(self,boundary,core):
        v=snapshot(core);self.save(boundary,snapshot=v)
        if boundary=='before_operation':validate(v);self.original=v
        elif boundary=='after_reset':
            if self.original is None:raise RuntimeError('missing pre-reset reference')
            for row in self.original['rows']:
                core.rfdc.adc_tiles[row['tile']].blocks[row['block']].DSA=dict(row['dsa'])
                self.save('dsa_reapplied',adc=row['adc'],dsa=row['dsa'])
            after=snapshot(core);validate(after,self.original,errors=False);self.save('after_dsa_restore',snapshot=after)
        else:validate(v,self.original,errors=False)
def execute(action):
    if action=='probe':
        with base.hw._configure_hardware_guard(True):
            core=base.hw._controller(base.hw._load_saved_configure_request()).require_core();v=snapshot(core);validate(v)
        return dict(v,ok=True,helper_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    if action!='ADC':raise ValueError('only probe or ADC allowed')
    journal=Journal()
    try:
        r=base.execute('ADC',observer=journal)
        calls=r['operation']['explicit_tile_reset_calls']
        if [(c['kind'],c['tile']) for c in calls]!=[('adc',i) for i in range(4)]:raise RuntimeError('reset scope mismatch')
        r.update(background_helper_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),board_journal_path=str(journal.path),journal=journal.rows)
        return r
    except Exception as e:journal.save('failed',error=str(e));raise
if __name__=='__main__':
    with contextlib.redirect_stdout(sys.stderr):result=execute(sys.argv[1])
    print(json.dumps(result,default=str))
