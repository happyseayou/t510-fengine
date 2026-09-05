#!/usr/bin/env python3
"""New-bit Stage 36 raw TIME/SPEC amplitude gate; runs on GB10 with NumPy."""
import argparse
import json
from pathlib import Path
import struct
import sys
import time
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1] / "stage-35"))
import t510_stage35_s2_queue as base
from t510_stage35_time_verify import udp_view, crop_continuous_pcap, verify_pcap
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from python.t510_scaling import manifest_metadata

BINS=(3134,3182,3328)
START_WARMUP_SECONDS=3.0
EXPECTED_CLOCK_PROFILE='160m_10m_request_manual_clkin0'
EXPECTED_CLOCK_SHA256='a8504d384354610f8f130b1cda1a446bcdfb25bf8c4bb689fbb58adefe5e88e2'
EXPECTED_MTS_TARGETS={'adc':492,'dac':-1}

def _identity_errors(snapshot,*,mode=None,center_mhz=200.0):
    errors=[];profile=snapshot.get('profile',{});clock=snapshot.get('clock',{});mts=snapshot.get('mts',{})
    if snapshot.get('board_id')!=1:errors.append('BOARD_ID_MISMATCH')
    if snapshot.get('core_version')!='0x00010036':errors.append('CORE_VERSION_MISMATCH')
    if snapshot.get('dac',{}).get('enable_mask')!=0:errors.append('DAC_NOT_MUTED')
    if snapshot.get('error_flags',0):errors.append('FPGA_ERROR_FLAGS_NONZERO')
    if profile.get('sample_rate_msps')!=320:errors.append('SAMPLE_RATE_MISMATCH')
    if mode is not None and profile.get('mode')!=mode:errors.append('MODE_MISMATCH')
    if abs(float(profile.get('center_mhz',0))-center_mhz)>1e-6:errors.append('CENTER_FREQUENCY_MISMATCH')
    if clock.get('clock_reference')!='onboard_tcxo':errors.append('CLOCK_REFERENCE_MISMATCH')
    if clock.get('profile_id')!=EXPECTED_CLOCK_PROFILE:errors.append('CLOCK_PROFILE_MISMATCH')
    if clock.get('profile_sha256')!=EXPECTED_CLOCK_SHA256:errors.append('CLOCK_PROFILE_SHA256_MISMATCH')
    if clock.get('pll1_lock')!=1 or clock.get('pll2_lock')!=1:errors.append('CLOCK_PLL_UNLOCKED')
    for kind,target in EXPECTED_MTS_TARGETS.items():
        if mts.get(kind,{}).get('target_latency')!=target:errors.append(kind.upper()+'_MTS_TARGET_MISMATCH')
    if snapshot.get('rfdc',{}).get('readback',{}).get('ok') is not True:errors.append('RFDC_READBACK_FAILED')
    try:manifest_metadata(snapshot['digital_scaling'])
    except (KeyError,TypeError,ValueError):errors.append('DIGITAL_SCALING_READBACK_FAILED')
    return errors

def _read_board(board,attempts=3):
    errors=[]
    for attempt in range(attempts):
        try:return board()
        except Exception as exc:
            errors.append(f'{type(exc).__name__}: {exc}')
            if attempt+1<attempts:time.sleep(1)
    raise RuntimeError(f'board status read failed after {attempts} attempts: {errors}')

def _safe_stop(board,*,mode=None,center_mhz=200.0):
    """Send at most one STOP, then prove the complete stopped identity."""
    current=_read_board(board);transport_error=None
    if current.get('streaming'):
        try:board('/api/v2/stop',method='POST',body={},timeout=90)
        except Exception as exc:transport_error=f'{type(exc).__name__}: {exc}'
    readback=_read_board(board)
    errors=_identity_errors(readback,mode=mode,center_mhz=center_mhz)
    if readback.get('streaming'):errors.append('BOARD_STILL_STREAMING')
    if errors:
        raise RuntimeError(f'STOP safe readback failed: transport={transport_error}; errors={errors}')
    return dict(stopped=True,stop_response_transport_error=transport_error,
                idempotent_readback_accepted=transport_error is not None,readback=readback)

def packets(path):
    with path.open('rb') as f:
        if f.read(24)[:4]!=b'\xd4\xc3\xb2\xa1':raise RuntimeError('invalid PCAP')
        while rec:=f.read(16):
            if len(rec)!=16:raise RuntimeError('truncated PCAP header')
            size=struct.unpack_from('<I',rec,8)[0];frame=f.read(size)
            if len(frame)!=size:raise RuntimeError('truncated PCAP packet')
            port,payload=udp_view(frame)
            if len(payload)!=8320:raise RuntimeError('wrong IQ16 payload length')
            words=struct.unpack_from('<16Q',payload)
            if words[0]>>32!=0x54353130 or words[1]>>48!=1:raise RuntimeError('wrong packet identity')
            yield port,words,np.frombuffer(payload,'<i2',4096,128).reshape(256,8,2)

def time_stats(path):
    total=np.zeros((8,2),np.int64);squares=total.copy();odd=total.copy();clips=total.copy();count=0
    for _,w,data in packets(path):
        if (w[1]>>32)&65535!=1:raise RuntimeError('not TIME')
        x=data.astype(np.int64);total+=x.sum(axis=0);squares+=(x*x).sum(axis=0)
        odd+=(x&1).sum(axis=0);clips+=((x==-32768)|(x==32767)).sum(axis=0);count+=len(x)
    if count==0:raise RuntimeError('empty TIME witness')
    return dict(samples_per_adc=count,std_iq=np.sqrt(squares/count-(total/count)**2).tolist(),
                odd_fraction_iq=(odd/count).tolist(),clip_iq=clips.tolist())

def spec_stats(path,out):
    identities=[{} for _ in range(16)];last=[None]*16
    for port,w,_ in packets(path):
        block=(w[9]>>16)&65535;frame=w[5];sample0=w[4];seq=w[6]>>32;group=frame//16
        if ((w[1]>>32)&65535)!=0 or not 0<=block<16 or port!=4308+block:
            raise RuntimeError('SPEC block identity mismatch')
        if (w[6]&0xffffffff)!=block*256 or (w[7]>>48)!=256 or ((w[7]>>16)&65535)!=8:
            raise RuntimeError('SPEC channel layout mismatch')
        status=w[10]&0xffffffff
        if ((w[10]>>48)!=8 or ((w[10]>>32)&65535)!=0x556 or
                not status&(1<<10) or status&(1<<9) or status&(1<<8) or status&((1<<7)|(1<<3))):
            raise RuntimeError('SPEC taps/FFT schedule/status mismatch')
        if frame%16!=block:raise RuntimeError('SPEC frame/block order mismatch')
        if group in identities[block]:raise RuntimeError('duplicate SPEC frame-group/block')
        previous=last[block]
        if previous is not None and (seq!=(previous[0]+16)&0xffffffff or frame!=previous[1]+16 or sample0!=previous[2]+4096):
            raise RuntimeError('SPEC sequence/frame/sample0 gap')
        identities[block][group]=(sample0,seq,frame);last[block]=(seq,frame,sample0)
    common=sorted(set.intersection(*(set(x) for x in identities)))
    if len(common)<4096 or any(b!=a+1 for a,b in zip(common,common[1:])):
        raise RuntimeError('need 4096 contiguous complete full-band frames')
    selected=common[:4096];first=selected[0];last_group=selected[-1]
    for group in selected:
        if len({x[group][0] for x in identities})!=1:raise RuntimeError('SPEC cross-block sample0 mismatch')
    total=np.zeros((4096,8,2),np.int64);squares=total.copy();counts=np.zeros(4096,np.int64);clips=0
    for _,w,data in packets(path):
        group=w[5]//16
        if first<=group<=last_group:
            block=(w[9]>>16)&65535;x=data.astype(np.int64);sl=slice(block*256,(block+1)*256)
            total[sl]+=x;squares[sl]+=x*x;counts[sl]+=1;clips+=int(((x==-32768)|(x==32767)).sum())
    if not np.all(counts==4096):raise RuntimeError('SPEC full-band frame count mismatch')
    std=np.sqrt(squares/4096-(total/4096)**2)
    np.savez_compressed(out/'spec_fullband_statistics.npz',mean_iq=total/4096,std_iq=std,
                        frames=4096,first_frame_group=first,first_sample0=identities[0][first][0])
    return dict(frames=4096,first_frame_group=first,last_frame_group=last_group,clip_components=clips,
                median_std_iq_by_adc=np.median(std,axis=0).tolist(),
                selected_bins={str(k):std[k].tolist() for k in BINS})

def numerical_errors(time_result,spec_result):
    errors=[]
    groups={'TIME':time_result['std_iq'],'SPEC median':spec_result['median_std_iq_by_adc']}
    groups.update({'SPEC bin '+k:v for k,v in spec_result['selected_bins'].items()})
    for name,rows in groups.items():
        for adc,row in enumerate(rows):
            for comp,value in zip('IQ',row):
                if not np.isfinite(value) or not 8<=value<=12:errors.append(f'{name} ADC{adc} {comp} std={value} outside [8,12]')
    if np.any(time_result['clip_iq']) or spec_result['clip_components']:errors.append('IQ16 clipping')
    if any(not 0.1<=x<=0.9 for row in time_result['odd_fraction_iq'] for x in row):errors.append('TIME sparse low-bit occupancy')
    return errors

def startup_boundary_evidence(integrity):
    """Preserve Stage 35 START transients outside the formal raw window."""
    return dict(seconds=START_WARMUP_SECONDS,integrity=integrity,
                boundary_events=list(integrity.get('errors',[])),
                excluded_from_formal_window=True)

def run(a):
    a.output.mkdir(parents=True,exist_ok=False)
    template=json.loads(a.template.read_text());catalog=json.loads(a.catalog.read_text())['bitstreams'][0]
    board=lambda path='/api/v2/status',**kw:base.http_json(a.agent_base+path,**kw)
    receiver=lambda path='/api/state',**kw:base.http_json(a.receiver_base+path,**kw)
    state=dict(status='running',scope='Stage36 new-bit amplitude qualification, not long science',phases=[])
    save=lambda:base.write_json_atomic(a.output/'state.json',state)
    save();owns=False;configured_mode=None
    try:
        if board().get('streaming'):raise RuntimeError('board must be stopped before qualification')
        for task in ('stage35-time','stage35-autocorrelation','stage35-crosscorrelation','spec-stability'):
            if receiver('/api/measure/'+task+'/status').get('status') in ('armed','running','draining'):
                raise RuntimeError('another receiver task is active')
        for mode in ('time_only','spec_only'):
            deadline=time.monotonic()+15
            while True:
                stats=receiver().get('stats',{})
                if not stats.get('packets_per_sec',0) and not stats.get('active_worker_count',0):break
                if time.monotonic()>deadline:raise RuntimeError('receiver did not quiesce')
                time.sleep(0.5)
            receiver('/api/config',method='POST',body=base.receiver_config(mode,200))
            body=base.configure_body(template,mode,200);body['bitstream_id']='fengine-0x00010036'
            owns=True
            configured=board('/api/v2/configure',method='POST',body=body,timeout=300)
            configured_mode=mode
            if configured.get('bitstream',{}).get('sha256')!=catalog['sha256']:raise RuntimeError('configured bit identity mismatch')
            idle=board();identity=idle['digital_scaling'];metadata=manifest_metadata(identity)
            identity_errors=_identity_errors(idle,mode=mode)
            if idle.get('streaming'):identity_errors.append('BOARD_NOT_STOPPED')
            if identity_errors:raise RuntimeError('configured identity mismatch: '+str(identity_errors))
            prestart_rx=receiver()
            board('/api/v2/start',method='POST',body={'expected_board_id':1});time.sleep(START_WARMUP_SECONDS)
            before=board();rx_before=receiver();raw=a.output/(mode+'-superset.pcap')
            startup=base.formal_integrity(idle,before,prestart_rx,rx_before)
            capture=base.http_to_new_file(a.receiver_base+'/api/capture/spec-pcap',raw,
                body={'packets_per_block':8192 if mode=='time_only' else 4098,
                      'include_time':mode=='time_only','time_only':mode=='time_only'},timeout=240)
            after=board();rx_after=receiver()
            integrity=base.formal_integrity(before,after,rx_before,rx_after)
            manifest_metadata(after['digital_scaling'])
            if before['digital_scaling']!=identity or after['digital_scaling']!=identity:raise RuntimeError('scale drift during raw capture')
            if before.get('error_flags',0) or after.get('error_flags',0):raise RuntimeError('FPGA error flags')
            for k in ('fir_saturation_count','xfft_fft_overflow_count','overflow_count','xfft_tlast_unexpected_count','xfft_tlast_missing_count','coefficient_error_count'):
                if after.get('channelizer',{}).get(k,0)!=before.get('channelizer',{}).get(k,0):
                    integrity['errors'].append('channelizer.'+k);integrity['ok']=False
            row=dict(mode=mode,capture=capture,metadata=metadata,before=before,after=after,
                     startup_warmup=startup_boundary_evidence(startup),integrity=integrity)
            state['phases'].append(row);save()
            row['stop']=_safe_stop(board,mode=mode);save()
            if not integrity['ok']:raise RuntimeError(str(integrity['errors']))
            if mode=='time_only':
                cropped=a.output/'time-50ms.pcap';row['crop']=crop_continuous_pcap(raw,cropped)
                row['raw_verification']=verify_pcap(cropped);state['time']=time_stats(cropped)
            else:state['spec']=spec_stats(raw,a.output)
            save()
        state['errors']=numerical_errors(state['time'],state['spec'])
        state['status']='FAIL' if state['errors'] else 'PASS';save()
        if state['errors']:raise RuntimeError(str(state['errors']))
    except Exception as exc:
        state.update(status='FAIL',error=str(exc));save();raise
    finally:
        if owns:
            try:state['final_stop']=_safe_stop(board,mode=configured_mode);save()
            except Exception as exc:state.update(status='FAIL',cleanup_error=str(exc));save();raise
    print(json.dumps(state))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);p.add_argument('--template',type=Path,required=True);p.add_argument('--catalog',type=Path,required=True);p.add_argument('--agent-base',default='http://192.168.100.117:8010');p.add_argument('--receiver-base',default='http://127.0.0.1:8089');run(p.parse_args())
