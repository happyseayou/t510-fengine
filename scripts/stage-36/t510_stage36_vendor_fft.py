#!/usr/bin/env python3
"""Run installed AMD XFFT bit-accurate model and cross-check preserved RTL prefix.
Vendor libraries stay outside source control. Input/output use existing IQ16 fixtures.
"""
import argparse
import ctypes as C
import json
from pathlib import Path
import time
from t510_stage36_fft_contract import GENERICS, SCHEDULE, FORMAT, ARTIFACTS, sha, verify_ip

class Generics(C.Structure):
    _fields_ = [(k,C.c_int) for k in GENERICS]
class Inputs(C.Structure):
    _fields_ = [('nfft',C.c_int),('xn_re',C.POINTER(C.c_double)),('xn_re_size',C.c_int),('xn_im',C.POINTER(C.c_double)),('xn_im_size',C.c_int),('scaling_sch',C.POINTER(C.c_int)),('scaling_sch_size',C.c_int),('direction',C.c_int)]
class Outputs(C.Structure):
    _fields_ = [('xk_re',C.POINTER(C.c_double)),('xk_re_size',C.c_int),('xk_im',C.POINTER(C.c_double)),('xk_im_size',C.c_int),('blk_exp',C.c_int),('overflow',C.c_int)]
def run(root, vendor, ip_vhdl):
    start=time.monotonic()
    # Never leave a stale PASS if a rerun fails.
    (root/'vendor_xfft_crosscheck.json').unlink(missing_ok=True)
    verify_ip(ip_vhdl)
    (root/'production_xfft.vhd').write_bytes(ip_vhdl.read_bytes())
    C.CDLL(str(vendor/'libgmp.so.11'),mode=C.RTLD_GLOBAL)
    lib=C.CDLL(str(vendor/'libIp_xfft_v9_1_bitacc_cmodel.so'))
    create=lib.xilinx_ip_xfft_v9_1_create_state;create.argtypes=[Generics];create.restype=C.c_void_p
    simulate=lib.xilinx_ip_xfft_v9_1_bitacc_simulate;simulate.argtypes=[C.c_void_p,Inputs,C.POINTER(Outputs)];simulate.restype=C.c_int
    destroy=lib.xilinx_ip_xfft_v9_1_destroy_state;destroy.argtypes=[C.c_void_p]
    config=tuple(GENERICS.values())
    states=[create(Generics(*config)) for _ in range(8)]
    if not all(states):raise RuntimeError('model initialization failed')
    meta=json.loads((root/'fixture.json').read_text())
    if meta['fft_shift']!=0x556 or sha(root/'input.mem')!=meta['input_mem_sha256']:raise RuntimeError('fixture identity mismatch')
    words=[int(x,16) for x in (root/'input.mem').read_text().splitlines()]
    if len(words)!=meta['frames']*4096:raise RuntimeError('incomplete model input')
    arr=C.c_double*4096;re,im,ore,oim=arr(),arr(),arr(),arr()
    schedule=(C.c_int*6)(*SCHEDULE)
    result_words=[]
    try:
        for frame in range(meta['frames']):
            output=[0]*4096
            for lane in range(8):
                for k in range(4096):
                    w=words[frame*4096+k]>>(32*lane)
                    i=w&65535;q=(w>>16)&65535
                    re[k]=(i if i<32768 else i-65536)/32768
                    im[k]=(q if q<32768 else q-65536)/32768
                inp=Inputs(12,re,4096,im,4096,schedule,6,1)
                out=Outputs(ore,4096,oim,4096,0,0)
                if simulate(states[lane],inp,C.byref(out)) or out.overflow or out.xk_re_size!=4096 or out.xk_im_size!=4096:
                    raise RuntimeError(f'model failure/overflow frame={frame} lane={lane}')
                for k in range(4096):
                    i,q=ore[k]*32768,oim[k]*32768
                    if i!=int(i) or q!=int(q) or not(-32768<=i<=32767 and -32768<=q<=32767):raise RuntimeError('output is not IQ16')
                    output[k]|=((int(i)&65535)|((int(q)&65535)<<16))<<(32*lane)
            result_words.extend(output)
    finally:
        for state in states:destroy(state)
    dump=root/'vendor_xfft_output.txt'
    with dump.open('w') as f:
        for row,w in enumerate(result_words):f.write(f'{row//4096} {row%4096} {w:064x}\n')
    count=0
    for line in (root/'real_xfft_prefix_preserved.txt').read_text().splitlines():
        f,k,w=line.split();index=int(f)*4096+int(k)
        if index!=count:raise RuntimeError('RTL prefix is noncontiguous')
        if result_words[index]!=int(w,16):raise RuntimeError(f'RTL/model mismatch frame={f} bin={k}')
        count+=1
    if count<4*4096:raise RuntimeError('require zero, impulse, tone and at least one full measured-noise RTL frame')
    report=dict(format=FORMAT, artifact_sha256={name:sha(root/name) for name in ARTIFACTS}, status='PASS',method='complete vendor bit-accurate model with exact real-IP RTL prefix cross-check',rtl_complete_frames=count//4096,rtl_prefix_bins=count,rtl_complex_cells=count*8,rtl_mismatches=0,model_frames=meta['frames'],model_overflow=0,elapsed_seconds=time.monotonic()-start,generics=dict(zip([k for k,_ in Generics._fields_],config)),scaling_schedule=list(schedule),sha256={str(p):sha(p) for p in [vendor/'libIp_xfft_v9_1_bitacc_cmodel.so',vendor/'libgmp.so.11',root/'input.mem',root/'real_xfft_prefix_preserved.txt',dump]})
    (root/'vendor_xfft_crosscheck.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report))
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,required=True);p.add_argument('--vendor',type=Path,required=True);p.add_argument('--ip-vhdl',type=Path,required=True);a=p.parse_args();run(a.root.resolve(),a.vendor.resolve(),a.ip_vhdl.resolve())
