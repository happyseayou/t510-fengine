#!/usr/bin/env python3
"""One-shot Stage 36 qualification queue. Failure stops; never resumes implicitly.

MTS discovery -> fixed -> qualified catalog/install -> 5x60s host/board matrix
-> new-scale short raw gate. Long scientific captures are a subsequent queue.
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import time
import traceback
import urllib.request

ROOT=Path(__file__).resolve().parents[2]
BOARD='xilinx@192.168.100.117'
GB10='astrolab@192.168.100.162'
BOARD_PY='/usr/local/share/pynq-venv/bin/python3'
GB_PY='/var/lib/t510/measurements/control/s2-analysis-v1-20260831-2059/venv/bin/python'
MODES=((160,'time_only'),(160,'spec_only'),(160,'time_spec'),(320,'time_only'),(320,'spec_only'))
EXPECTED_BITSTREAM_SHA256='e00c586a1d862d7c7af113361832a30093334493e49f943e3dd22bf44f950665'

def sha(p):
    with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def atomic(p,value):
    temp=p.with_suffix('.tmp');temp.write_text(json.dumps(value,indent=2)+'\n');temp.replace(p)

def http(path,body=None):
    request=urllib.request.Request('http://192.168.100.117:8010'+path,
        data=None if body is None else json.dumps(body).encode(),
        headers={} if body is None else {'Content-Type':'application/json'})
    with urllib.request.urlopen(request,timeout=300) as f:value=json.load(f)
    return value.get('result',value)

class Queue:
    def __init__(self,args):
        self.args=args;self.root=args.evidence.resolve();self.package=args.package.resolve()
        self.remote='/home/xilinx/.cache/t510/'+args.queue_id+'/package'
        self.board_evidence='/var/lib/t510/stage36/'+args.queue_id
        self.gb='/var/lib/t510/stage36/'+args.queue_id
        self.state=dict(status='armed',queue_id=args.queue_id,phases=['preflight','MTS_discovery_40','MTS_fixed_40','catalog_install','5_modes_60s','short_raw_amplitude_gate','local_release_promotion'],completed=[],hardware_owned=False,created_unix_s=time.time())
    def save(self,**fields):
        self.state.update(fields,updated_unix_s=time.time());atomic(self.root/'queue-state.json',self.state)
    def command(self,name,argv,*,sudo=False,timeout=3600):
        self.save(current_command=name)
        with (self.root/(name+'.log')).open('x') as f:
            result=subprocess.run(argv,input=(os.environ['PYNQ_SUDO_PASSWORD']+'\n') if sudo else None,
                                  stdout=f,stderr=subprocess.STDOUT,text=True,timeout=timeout)
        if result.returncode:raise RuntimeError(f'{name} returned {result.returncode}; see {name}.log')
    def remote_command(self,name,argv,*,sudo=False,host=BOARD,timeout=3600):
        cmd=(['sudo','-S','-p',''] if sudo else [])+list(map(str,argv))
        self.command(name,['ssh','-o','BatchMode=yes',host,shlex.join(cmd)],sudo=sudo,timeout=timeout)
    def phase(self,name):self.save(phase=name)
    def complete(self,name):self.state['completed'].append(name);self.save()
    def verify_sources(self):
        actual={str(p.relative_to(self.package)):sha(p) for p in self.package.rglob('*') if p.is_file() and '__pycache__' not in p.parts}
        for name,digest in self.state['package_sha256'].items():
            if actual.get(name)!=digest:raise RuntimeError('staged source drift: '+name)
        if set(actual)!=set(self.state['package_sha256']):
            raise RuntimeError('staged source file set drift')
    def validate_package(self):
        mirrors={
            'deploy/install-on-board.sh':ROOT/'deploy/t510/install-on-board.sh',
            'deploy/t510-agent.service':ROOT/'deploy/t510/t510-agent.service',
            'deploy/t510-ref-watchdog.service':ROOT/'deploy/t510/t510-ref-watchdog.service',
            'deploy/t510-agent.service.d/center-hub.conf':ROOT/'deploy/t510/t510-agent.service.d/center-hub.conf',
            'scripts/pynq_t510_mts_campaign.py':ROOT/'scripts/pynq_t510_mts_campaign.py',
            'scripts/t510_finalize_catalog.py':ROOT/'scripts/t510_finalize_catalog.py',
            'scripts/t510_board_host_gate.py':ROOT/'scripts/t510_board_host_gate.py',
            'scripts/t510_host_validate.py':ROOT/'scripts/t510_host_validate.py',
            'scripts/stage-36/t510_stage36_qualification_queue.py':ROOT/'scripts/stage-36/t510_stage36_qualification_queue.py',
            'scripts/stage-36/t510_stage36_short_gate.py':ROOT/'scripts/stage-36/t510_stage36_short_gate.py',
            'scripts/stage-35/t510_stage35_s2_queue.py':ROOT/'scripts/stage-35/t510_stage35_s2_queue.py',
            'scripts/stage-35/t510_time_capture_verify.py':ROOT/'scripts/stage-35/t510_time_capture_verify.py',
            'bin/t510-board-agent':ROOT/'rust/t510_board_agent/target/aarch64-unknown-linux-musl/release/t510-board-agent',
        }
        for name in ('__init__.py','packet.py','t510_ams.py','t510_astronomy.py',
                     't510_clock.py','t510_console.py','t510_control.py','t510_fengine.py',
                     't510_hw.py','t510_mts_target.py','t510_ref_watchdog.py','t510_scaling.py'):
            mirrors['python/'+name]=ROOT/'python'/name
        for relative,source in mirrors.items():
            staged=self.package/relative
            if not staged.is_file() or sha(staged)!=sha(source):
                raise RuntimeError('qualification package is missing current source: '+relative)
        for relative in ('overlay/t510_fengine.bit','overlay/t510_fengine.hwh',
                         'overlay/t510_fengine.tcl','overlay/t510_fengine.manifest.txt',
                         'overlay/t510_fengine_rfdc.xci','config/qualification-template.json',
                         'config/config.example.json'):
            if not (self.package/relative).is_file():
                raise RuntimeError('qualification package is missing: '+relative)
        if sha(self.package/'overlay/t510_fengine.bit')!=EXPECTED_BITSTREAM_SHA256:
            raise RuntimeError('qualification package has the wrong routed bitstream')
        binary=(self.package/'bin/t510-board-agent').read_bytes()[:20]
        if binary[:4]!=b'\x7fELF' or int.from_bytes(binary[18:20],'little')!=183:
            raise RuntimeError('qualification Agent is not an AArch64 ELF binary')
        catalog=json.loads((self.package/'config/config.example.json').read_text())
        entries=[row for row in catalog.get('bitstreams',[]) if row.get('id')=='fengine-0x00010036']
        if len(entries)!=1 or entries[0].get('sha256')!='0'*64 or entries[0].get('mts_campaign') is not None:
            raise RuntimeError('qualification catalog must begin as the unqualified v36 placeholder')
        self.verify_sources()
    def promote_local_release(self):
        for artifact in (self.package/'overlay').iterdir():
            shutil.copy2(artifact,ROOT/'overlay'/artifact.name)
        shutil.copy2(self.package/'config/config.example.json',ROOT/'config/t510/config.example.json')
    def run(self):
        self.root.mkdir(parents=True,exist_ok=True)
        if (self.root/'queue-state.json').exists():raise RuntimeError('original queue exists; inspect it, never resubmit')
        with (self.root/'queue.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            self.state['package_sha256']={str(p.relative_to(self.package)):sha(p) for p in self.package.rglob('*') if p.is_file() and '__pycache__' not in p.parts}
            self.save(status='running',phase='preflight')
            try:
                self.validate_package()
                if getattr(self.args, 'failed_queue', None):
                    previous=json.loads((self.args.failed_queue/'queue-state.json').read_text())
                    if previous.get('status')!='FAIL' or not previous.get('hardware_owned'):
                        raise RuntimeError('recovery requires a failed, hardware-owned queue')
                    if previous['package_sha256']['overlay/t510_fengine.bit']!=sha(self.package/'overlay/t510_fengine.bit'):
                        raise RuntimeError('recovery candidate differs from failed queue')
                    self.remote_command('recovery_preflight',['env','XILINX_XRT=/usr',BOARD_PY,'-c',
                        "import sys,json,hashlib,subprocess; sys.path.insert(0,sys.argv[1]); from pynq import PL; from python.t510_control import FEngineController; from scripts.pynq_t510_mts_campaign import _acquire_configure_lock,DEFAULT_CONFIGURE_LOCK,_preserve_clock; lock=_acquire_configure_lock(DEFAULT_CONFIGURE_LOCK); assert all(subprocess.run(['systemctl','is-active','--quiet',n]).returncode==3 for n in ['t510-agent','t510-ref-watchdog']); actual=hashlib.sha256(open(PL.bitfile_name,'rb').read()).hexdigest(); assert actual==sys.argv[2], 'active PL identity mismatch'; c=FEngineController(sys.argv[1]+'/overlay/t510_fengine.bit'); c.connect(download=False); core=c.require_core(); s=core.read_status(); assert s['core_version']==0x10036 and not s['streaming']; clock=_preserve_clock('tcxo_10mhz'); core.set_dac_enable_mask(0); assert core.read_status()['dac_enable_mask']==0; print(json.dumps({'status':s,'clock':clock,'bitstream_sha256':actual,'dac_muted':True},default=str))",
                        self.remote,sha(self.package/'overlay/t510_fengine.bit')],sudo=True,timeout=90)
                    self.save(recovery_of=previous['queue_id'])
                else:
                    before=http('/api/v2/status');atomic(self.root/'board-before.json',before)
                    if before.get('streaming') or before.get('dac',{}).get('enable_mask')!=0:raise RuntimeError('board must be stopped and DAC muted')
                    if before.get('core_version')!='0x00010034':raise RuntimeError('unexpected baseline core')
                    if before.get('clock',{}).get('clock_reference')!='onboard_tcxo':raise RuntimeError('baseline reference changed')
                self.remote_command('package_identity',['python3','-c',
                    "import hashlib,json,pathlib,sys; root=pathlib.Path(sys.argv[1]); expected=json.loads(sys.argv[2]); actual={n:hashlib.sha256((root/n).read_bytes()).hexdigest() for n in expected}; assert actual==expected, 'staged package identity mismatch'; print(json.dumps({'status':'PASS','files':len(actual)}))",
                    self.remote,json.dumps(self.state['package_sha256'])],timeout=120)
                self.remote_command('receiver_idle',['python3','-c',
                    "import json,urllib.request; base='http://127.0.0.1:8089'; s=json.load(urllib.request.urlopen(base+'/api/state')); assert not s.get('stats',{}).get('packets_per_sec',0); paths=['stage35-time','stage35-autocorrelation','stage35-crosscorrelation','spec-stability']; rows=[json.load(urllib.request.urlopen(base+'/api/measure/'+p+'/status')) for p in paths]; assert all(r.get('status') not in ('armed','running','draining') for r in rows); print(json.dumps(rows))"],host=GB10,timeout=30)
                gb_sources={
                    'qualification-template.json':sha(self.package/'config/qualification-template.json'),
                    **{
                        'scripts/'+name:sha(self.package/'scripts'/name)
                        for name in ('t510_host_validate.py','t510_stage36_short_gate.py','t510_stage35_s2_queue.py','t510_time_capture_verify.py')
                    },
                    **{
                        'python/'+name:sha(self.package/'python'/name)
                        for name in ('__init__.py','packet.py','t510_ams.py','t510_astronomy.py',
                                     't510_clock.py','t510_console.py','t510_control.py','t510_fengine.py',
                                     't510_hw.py','t510_mts_target.py','t510_ref_watchdog.py','t510_scaling.py')
                    },
                }
                self.remote_command('gb_package_identity',['python3','-c',
                    "import hashlib,json,pathlib,sys; root=pathlib.Path(sys.argv[1]); expected=json.loads(sys.argv[2]); actual={n:hashlib.sha256((root/n).read_bytes()).hexdigest() for n in expected}; assert actual==expected, 'GB staged source identity mismatch'; print(json.dumps({'status':'PASS','files':len(actual)}))",
                    self.gb,json.dumps(gb_sources)],host=GB10,timeout=120)
                self.remote_command('backup_dir',['mkdir','-p',self.board_evidence],sudo=True)
                self.remote_command('backup',['tar','-C','/','-czf',self.board_evidence+'/board-before.tgz','opt/t510-agent/current','etc/t510-agent/config.json'],sudo=True)
                self.remote_command('services_stop',['systemctl','stop','t510-agent.service','t510-ref-watchdog.service'],sudo=True)
                self.save(hardware_owned=True)
                for phase in ('discovery','fixed'):
                    self.phase('MTS_'+phase+'_40');self.verify_sources()
                    args=['env','XILINX_XRT=/usr','PYTHONDONTWRITEBYTECODE=1',BOARD_PY,self.remote+'/scripts/pynq_t510_mts_campaign.py',
                        '--phase',phase,'--bitfile',self.remote+'/overlay/t510_fengine.bit','--center-mhz','200','--clock-ref','tcxo_10mhz',
                        '--lmk-settle-seconds','3','--output',self.board_evidence+'/mts_'+phase+'.json']
                    if phase=='fixed':args+=['--discovery-json',self.board_evidence+'/mts_discovery.json']
                    self.remote_command('mts_'+phase,args,sudo=True,timeout=7200)
                    self.remote_command('mts_'+phase+'_read',['cat',self.board_evidence+'/mts_'+phase+'.json'],sudo=True)
                    value=json.loads((self.root/('mts_'+phase+'_read.log')).read_text())
                    atomic(self.root/('mts_'+phase+'.json'),value)
                    if not value.get('ok') or value.get('completed_cycles')!=40:raise RuntimeError('MTS phase not qualified')
                    if value['bitstream_sha256']!=sha(self.package/'overlay/t510_fengine.bit'):raise RuntimeError('MTS bit identity mismatch')
                    self.complete('MTS_'+phase+'_40')
                self.phase('catalog_install');self.verify_sources()
                self.command('catalog_finalize',[sys.executable,str(self.package/'scripts/t510_finalize_catalog.py'),
                    '--bitstream',str(self.package/'overlay/t510_fengine.bit'),'--discovery-json',str(self.root/'mts_discovery.json'),
                    '--fixed-json',str(self.root/'mts_fixed.json'),'--catalog',str(self.package/'config/config.example.json')])
                self.state['package_sha256']['config/config.example.json']=sha(self.package/'config/config.example.json')
                self.save(finalized_catalog_sha256=self.state['package_sha256']['config/config.example.json'])
                self.verify_sources()
                self.command('catalog_copy',['scp',str(self.package/'config/config.example.json'),BOARD+':'+self.remote+'/config/config.example.json'])
                self.remote_command('final_package_identity',['python3','-c',
                    "import hashlib,json,pathlib,sys; root=pathlib.Path(sys.argv[1]); expected=json.loads(sys.argv[2]); actual={n:hashlib.sha256((root/n).read_bytes()).hexdigest() for n in expected}; assert actual==expected, 'final staged package identity mismatch'; print(json.dumps({'status':'PASS','files':len(actual)}))",
                    self.remote,json.dumps(self.state['package_sha256'])],timeout=120)
                self.remote_command('install',['bash',self.remote+'/deploy/install-on-board.sh',self.remote],sudo=True,timeout=300)
                self.remote_command('installed_package_identity',['python3','-c',
                    "import hashlib,json,pathlib,sys; root=pathlib.Path('/opt/t510-agent/current'); expected=json.loads(sys.argv[1]); actual={n:hashlib.sha256((root/n).read_bytes()).hexdigest() for n in expected}; assert actual==expected, 'installed package identity mismatch'; print(json.dumps({'status':'PASS','files':len(actual)}))",
                    json.dumps(self.state['package_sha256'])],timeout=120)
                self.complete('catalog_install')
                template=json.loads((self.package/'config/qualification-template.json').read_text())
                for rate,mode in MODES:
                    label=f'{rate}_{mode}';self.phase('matrix_'+label)
                    body=json.loads(json.dumps(template));body['profile']=dict(sample_rate_msps=rate,mode=mode,center_mhz=200.0)
                    body['update_mode']='clock_preserving'
                    body['receiver_stream_accepting']=False
                    for endpoint in body['endpoints']:
                        endpoint['enabled']=(endpoint['stream']=='TIME' and mode in ('time_only','time_spec')) or (endpoint['stream']=='SPEC' and mode in ('spec_only','time_spec'))
                    configured=http('/api/v2/configure',body);atomic(self.root/(label+'_configured.json'),configured)
                    if configured.get('bitstream',{}).get('sha256')!=sha(self.package/'overlay/t510_fengine.bit'):raise RuntimeError('matrix bit identity mismatch')
                    self.command('gate_'+label,[sys.executable,str(self.package/'scripts/t510_board_host_gate.py'),'--sample-rate-msps',str(rate),'--mode',mode,
                        '--seconds','60','--center-mhz','200','--remote-validator',self.gb+'/scripts/t510_host_validate.py',
                        '--remote-output',self.gb+'/'+label+'_host.json','--output',str(self.root/(label+'_gate.json'))],timeout=240)
                    if not json.loads((self.root/(label+'_gate.json')).read_text()).get('ok'):raise RuntimeError('matrix gate failed')
                    self.complete('matrix_'+label)
                self.phase('short_raw_amplitude_gate')
                self.command('numeric_catalog_copy',['scp',str(self.package/'config/config.example.json'),GB10+':'+self.gb+'/config.example.json'])
                self.remote_command('short_gate',[GB_PY,self.gb+'/scripts/stage-36/t510_stage36_short_gate.py','--output',self.gb+'/short-raw',
                    '--template',self.gb+'/qualification-template.json','--catalog',self.gb+'/config.example.json'],host=GB10,timeout=1200)
                self.command('short_result_copy',['scp',GB10+':'+self.gb+'/short-raw/state.json',str(self.root/'short-gate.json')])
                if json.loads((self.root/'short-gate.json').read_text())['status']!='PASS':raise RuntimeError('short numeric gate failed')
                self.complete('short_raw_amplitude_gate')
                self.phase('local_release_promotion');self.verify_sources();self.promote_local_release()
                self.complete('local_release_promotion');self.save(status='PASS',phase='await_science_queue',finished_unix_s=time.time())
            except Exception as exc:
                self.save(status='FAIL',error=str(exc),traceback=traceback.format_exc(),finished_unix_s=time.time())
                if self.state['hardware_owned']:
                    # Stop only. Keep failed candidate/evidence; never silently
                    # install an old catalog against a new unqualified design.
                    cleanup_errors=[]
                    try:
                        self.remote_command('failure_services_stop',['systemctl','stop','t510-agent.service','t510-ref-watchdog.service'],sudo=True,timeout=60)
                    except Exception as cleanup:
                        cleanup_errors.append('services: '+str(cleanup))
                    try:
                        self.remote_command('failure_stop',['env','XILINX_XRT=/usr',BOARD_PY,'-c',
                        "import sys; sys.path.insert(0,"+repr(self.remote)+"); from python.t510_control import FEngineController; c=FEngineController("+repr(self.remote+'/overlay/t510_fengine.bit')+"); c.connect(download=False); c.require_core().stop(); c.require_core().set_dac_enable_mask(0); c.require_core().clock.set_sysref(False)"],sudo=True,timeout=60)
                    except Exception as cleanup:
                        cleanup_errors.append('hardware: '+str(cleanup))
                    if cleanup_errors:self.save(cleanup_errors=cleanup_errors)
                raise

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--evidence',type=Path,required=True);p.add_argument('--package',type=Path,required=True);p.add_argument('--queue-id',required=True);p.add_argument('--failed-queue',type=Path);a=p.parse_args()
    if not a.queue_id.startswith('stage36-') or not all(c.isalnum() or c in '-_' for c in a.queue_id):p.error('invalid Stage36 queue identifier')
    if not os.environ.get('PYNQ_SUDO_PASSWORD'):p.error('PYNQ_SUDO_PASSWORD required')
    Queue(a).run()
