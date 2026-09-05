#!/usr/bin/env python3
"""Prepare/check real-XFFT fixtures using the qualified RFDC TIME witness.

Old and new PFB quantizers process the SAME measured RFDC samples. This isolates
the proposed PFB quantizer/FFT numerical change; it is not an RFDC ENOB model.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import struct
import zlib
import numpy as np
from t510_stage35_pfb_white_model import coefficients_for_phase, EXPECTED_CRC32
from t510_time_capture_verify import packet_identity, udp_view
from t510_stage36_fft_contract import FORMAT, sha, read_words, verify_contract

N = 4096
NOISE_FRAMES = 16


def rounded(values, shift):
    mag = (np.abs(values) + (1 << (shift-1))) >> shift
    return np.clip(np.where(values < 0, -mag, mag), -32768, 32767).astype(np.int16)


def prepare(pcap, out):
    out.mkdir(parents=True, exist_ok=False)
    samples = (NOISE_FRAMES + 7)*N
    raw = np.zeros((samples, 8, 2), dtype=np.int16)
    seen = np.zeros(samples//256, dtype=bool)
    first = None
    with pcap.open('rb') as stream:
        stream.read(24)
        while rec := stream.read(16):
            frame = stream.read(struct.unpack_from('<I', rec, 8)[0])
            _, _, _, sample0 = packet_identity(frame)
            first = sample0 if first is None else min(first, sample0)
    with pcap.open('rb') as stream:
        stream.read(24)
        while rec := stream.read(16):
            frame = stream.read(struct.unpack_from('<I', rec, 8)[0])
            _, _, _, sample0 = packet_identity(frame)
            offset = sample0-first
            if 0 <= offset < samples:
                if offset % 256 or seen[offset//256]:
                    raise RuntimeError('raw duplicate or unaligned sample0')
                raw[offset:offset+256] = np.frombuffer(udp_view(frame)[1], '<i2', 4096, 128).reshape(256,8,2)
                seen[offset//256] = True
    if not seen.all():
        raise RuntimeError('missing contiguous raw input samples')
    coeff = np.asarray([coefficients_for_phase(p) for p in range(N)], dtype=np.int64)
    crc = zlib.crc32((coeff.T.astype('<i4') & 0x3ffff).tobytes())
    if crc != EXPECTED_CRC32:
        raise RuntimeError('production coefficient CRC mismatch')
    frames = raw.reshape(NOISE_FRAMES+7,N,8,2).astype(np.int64)
    acc = np.stack([sum(frames[f+7-t]*coeff[:,t,None,None] for t in range(8))
                    for f in range(NOISE_FRAMES)])
    old, new = rounded(acc,17), rounded(acc,16)
    ideal = acc.astype(np.float64)/(1<<17)
    ideal_fft = np.fft.fft(ideal[...,0]+1j*ideal[...,1],axis=1)/128
    zero = np.zeros((1,N,8,2),dtype=np.int16)
    impulse = zero.copy();impulse[0,0,:,0] = np.arange(8)*32+64
    tone = zero.copy()
    for lane in range(8):
        z = 256*np.exp(2j*np.pi*(lane+1)*np.arange(N)/N)
        tone[0,:,lane,0] = np.rint(z.real).astype(np.int16)
        tone[0,:,lane,1] = np.rint(z.imag).astype(np.int16)
    inputs = np.concatenate([zero,impulse,tone,old,new],axis=0)
    floating = np.fft.fft(inputs[...,0].astype(float)+1j*inputs[...,1].astype(float),axis=1)/128
    with (out/'input.mem').open('x') as stream:
        for row in inputs.reshape(-1,16):
            stream.write(''.join(f'{int(x)&65535:04x}' for x in row[::-1])+'\n')
    np.savez_compressed(out/'reference.npz', floating=floating, ideal_fft=ideal_fft, inputs=inputs)
    fir_old = float(np.mean((old.astype(float)-ideal)**2))
    fir_new = float(np.mean((new.astype(float)/2-ideal)**2))
    meta = dict(format='T510_STAGE36_REAL_XFFT_FIXTURE_V1', frames=len(inputs),
                noise_frames=NOISE_FRAMES, coeff_crc32=f'0x{crc:08x}', fft_shift=0x556,
                first_sample0=first, input_samples=samples,
                source_pcap=str(pcap), source_sha256=hashlib.file_digest(pcap.open('rb'),'sha256').hexdigest(),
                input_mem_sha256=hashlib.file_digest((out/'input.mem').open('rb'),'sha256').hexdigest(),
                old_fir_referred_mse=fir_old, new_fir_referred_mse=fir_new,
                new_over_old_fir_mse=fir_new/fir_old,
                scope='same measured post-DDC input; PFB/FFT precision only; not ADC ENOB')
    (out/'fixture.json').write_text(json.dumps(meta,indent=2)+'\n')
    print(json.dumps(meta))


def check(root, dump, backend='rtl'):
    name = 'real_xfft_verification.json' if backend == 'rtl' else 'vendor_xfft_verification.json'
    (root/name).unlink(missing_ok=True)
    proof, model_words = verify_contract(root)
    meta=json.loads((root/'fixture.json').read_text())
    ref=np.load(root/'reference.npz')
    shape=(meta['frames'],N,8)
    if (ref['inputs'].shape != (*shape, 2) or ref['inputs'].dtype != np.int16
            or ref['floating'].shape != shape
            or ref['ideal_fft'].shape != (meta['noise_frames'],N,8)
            or not np.isfinite(ref['floating']).all()
            or not np.isfinite(ref['ideal_fft']).all()):
        raise RuntimeError('invalid or nonfinite reference')
    recalculated = np.fft.fft(ref['inputs'][...,0].astype(float)
                             + 1j*ref['inputs'][...,1].astype(float),axis=1)/128
    if not np.allclose(recalculated,ref['floating'],rtol=0,atol=1e-12):
        raise RuntimeError('floating reference disagrees with input and FFT schedule')
    encoded = []
    for row in ref['inputs'].reshape(-1,16):
        encoded.append(sum((int(v)&65535) << (16*j) for j,v in enumerate(row)))
    if encoded != [int(x,16) for x in (root/'input.mem').read_text().splitlines()]:
        raise RuntimeError('reference inputs differ from model/RTL inputs')
    actual=np.zeros(shape,dtype=np.complex128);seen=np.zeros(shape[:2],dtype=bool)
    for index,w in read_words(dump):
        f,k=divmod(index,N)
        if not (0<=f<shape[0]) or seen[f,k]:
            raise RuntimeError('invalid or duplicate output frame/bin')
        if w != model_words[index]:
            raise RuntimeError(f'output disagrees with bit-accurate oracle at frame={f} bin={k}')
        values=np.array([(w>>(16*j))&65535 for j in range(16)],dtype=np.uint16).view(np.int16)
        actual[f,k]=values[::2].astype(float)+1j*values[1::2].astype(float)
        seen[f,k]=True
    if not seen.all():raise RuntimeError('incomplete real-XFFT output')
    error=actual-ref['floating']
    n=meta['noise_frames'];old=actual[3:3+n];new=actual[3+n:3+2*n]
    old_mse=float(np.mean(np.abs(old-ref['ideal_fft'])**2))
    new_mse=float(np.mean(np.abs(new/2-ref['ideal_fft'])**2))
    old_error=old-ref['ideal_fft'];new_error=new/2-ref['ideal_fft']
    old_iq_mse=np.stack([np.mean(old_error.real**2,axis=(0,1)),
                         np.mean(old_error.imag**2,axis=(0,1))],axis=-1)
    new_iq_mse=np.stack([np.mean(new_error.real**2,axis=(0,1)),
                         np.mean(new_error.imag**2,axis=(0,1))],axis=-1)
    errors=[]
    if np.any(actual[0]):errors.append('zero input produced nonzero output')
    # PG109 pp. 33/70/77: fixed-point implementation correctness is exact
    # agreement with the configured vendor model without overflow. Float
    # distance measures quantization; 4 count was not a derived error bound.
    if not new_mse<old_mse:errors.append('input-referred numerical error did not improve')
    if not np.all(new_iq_mse<old_iq_mse):
        errors.append('input-referred error did not improve for every ADC I/Q component')
    std=np.stack([new.real.std(axis=0),new.imag.std(axis=0)],axis=-1)
    result=dict(status='FAIL' if errors else 'PASS',errors=errors,
                backend=backend,
                validation_contract=FORMAT,
                correctness_oracle='configured vendor bit-accurate model; zero mismatch; zero overflow',
                real_rtl_prefix_complex_cells=proof['rtl_complex_cells'],
                evidence_sha256=proof['artifact_sha256'],
                checked_dump_sha256=sha(dump),
                float_error_role='quantization diagnostic, not implementation correctness gate',
                legacy_float_4_count_exceedances=int(np.count_nonzero(np.abs(error)>4)),
                output_frames=shape[0], output_complex_cells=int(np.prod(shape)),
                max_fft_float_error_count=float(np.abs(error).max()),
                old_total_referred_complex_mse=old_mse,new_total_referred_complex_mse=new_mse,
                new_over_old_mse=new_mse/old_mse if old_mse>0 else None,
                old_iq_mse_by_adc=old_iq_mse.tolist(),
                new_iq_mse_by_adc=new_iq_mse.tolist(),
                candidate_iq_std_median_by_adc=np.median(std,axis=0).tolist(),
                fixture=meta)
    (root/name).write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))
    if errors:raise RuntimeError('; '.join(errors))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['prepare','check'])
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--pcap',type=Path)
    parser.add_argument('--dump',type=Path)
    parser.add_argument('--backend',choices=['rtl','vendor'],default='rtl')
    a=parser.parse_args()
    if a.action=='prepare':prepare(a.pcap,a.root)
    else:check(a.root,a.dump,a.backend)
