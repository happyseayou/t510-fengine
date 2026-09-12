#!/usr/bin/env python3
"""Common-tone measurements; numeric headroom and source-presence gates only."""
import json
import math
from pathlib import Path
import struct
import numpy as np
from t510_stage36_tile_analyze import load_rho, PAIRS

TONE_BIN = 3201


def raw_headroom(path):
    maximum = np.zeros(8, dtype=np.int64)
    groups = [dict() for _ in range(16)]
    packets = 0
    with Path(path).open('rb') as f:
        h = f.read(24)
        if len(h) != 24 or h[:4] != b'\xd4\xc3\xb2\xa1':
            raise RuntimeError('invalid PCAP')
        while r := f.read(16):
            if len(r) != 16: raise RuntimeError('truncated record')
            n = struct.unpack_from('<I', r, 8)[0]; frame = f.read(n)
            if len(frame) != n or n < 42: raise RuntimeError('truncated frame')
            udp = 14 + (frame[14] & 15) * 4
            port = struct.unpack_from('!H', frame, udp+2)[0]
            payload = frame[udp+8:]
            if len(payload) != 8320 or not 4308 <= port < 4324: raise RuntimeError('invalid SPEC packet')
            words = struct.unpack_from('<16Q', payload); block = port-4308
            if words[0]>>32 != 0x54353130 or (words[1]>>32)&65535 or words[5]%16 != block or (words[9]>>16)&65535 != block:
                raise RuntimeError('SPEC identity mismatch')
            group = words[5]//16
            if group in groups[block]: raise RuntimeError('duplicate SPEC packet')
            groups[block][group] = words[4]
            iq = np.frombuffer(payload, dtype='<i2', offset=128).reshape(256,8,2).astype(np.int32)
            maximum = np.maximum(maximum, np.max(abs(iq), axis=(0,2))); packets += 1
    common = sorted(set.intersection(*(set(g) for g in groups)))
    if len(common) < 32 or any(b != a+1 for a,b in zip(common,common[1:])):
        raise RuntimeError('insufficient contiguous fullband raw witness')
    for g in common:
        if len({b[g] for b in groups}) != 1: raise RuntimeError('cross-block sample0 mismatch')
    if any(groups[0][b]-groups[0][a] != 4096 for a,b in zip(common,common[1:])):
        raise RuntimeError('raw sample0 discontinuity')
    return dict(packets=packets, complete_frames=len(common), max_abs_iq_count_by_adc=maximum.tolist(),
                limit_count=26213, passed=bool(np.all(maximum < 26213)),
                scope='F-engine IQ16 witness adjacent after correlation window; not raw ADC headroom or every sample in the window')


def summarize(dataset, seconds, output):
    rho, visibility, power = load_rho(dataset, seconds)
    z = Path(dataset)/'xcorr.zarr'; pair = PAIRS.index((0,2))
    peaks = np.argmax(power,axis=1)
    k = int(np.argmax(np.sqrt(power[0]*power[2])))
    floor = np.median(power[:,3000:3400],axis=1)
    snr = 10*np.log10(power[:,k]/floor)
    present = all(abs(int(peaks[i])-TONE_BIN)<=2 and snr[i]>=10 for i in (0,2))
    values=[]; ratios=[]; weights=[]
    block,off=divmod(k,256)
    for sec in range(seconds):
        v=np.fromfile(z/'mean_cross_visibility_count2_100ms'/f'{sec}.0.{block}',dtype='<c16').reshape(10,28,256)[:,pair,off]
        p=np.fromfile(z/'mean_auto_power_count2_100ms'/f'{sec}.0.{block}',dtype='<f8').reshape(10,8,256)[:,:,off]
        n=np.fromfile(z/'n_valid_100ms'/f'{sec}.0',dtype='<u8').reshape(10,16)[:,block]
        values.extend(v/np.sqrt(p[:,0]*p[:,2])); ratios.extend(10*np.log10(p[:,0]/p[:,2])); weights.extend(n.tolist())
    values=np.asarray(values); center=np.angle(rho[pair,k]); delta=np.angle(values*np.exp(-1j*center),deg=True)
    result=dict(source_present=bool(present), observed_common_peak_bin=k,
        observed_peak_frequency_mhz=200+(k if k<2048 else k-4096)*320/4096,
        peaks_by_adc=peaks.tolist(), tone_over_local_median_db_by_adc=snr.tolist(),
        rho02_complex_mean_pct=float(abs(rho[pair,k])), phase02_complex_mean_deg=float(np.angle(rho[pair,k],deg=True)),
        power_ratio_0_over_2_db=float(10*np.log10(power[0,k]/power[2,k])),
        rho02_100ms_pct_percentiles=np.percentile(abs(values)*100,[5,50,95]).tolist(),
        phase02_100ms_residual_deg_percentiles=np.percentile(delta,[5,50,95]).tolist(),
        phase_note='Residuals wrapped relative to full-window phase; interpret only with sufficient source coherence.',
        interpretation='End-to-end common CW response, not proof of broadband delay alignment or a noise-floor improvement')
    np.savez_compressed(output,
        rho_pct=rho, visibility_count2=visibility, power_count2=power,
        rho02_100ms=values, power_ratio_db_100ms=ratios, n_valid_100ms=weights)
    return result
