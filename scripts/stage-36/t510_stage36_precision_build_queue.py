#!/usr/bin/env python3
"""Continue the ORIGINAL running XSim through verification and GUI-MCP build.

Legacy full-35-frame path, not used by the optimized Stage 36 run. Its fixture
must also contain the V2 qualified vendor-model evidence required by the checker.

Never starts/restarts/stops a simulation or spawns Vivado. The only build
interface is the installed Vivado MCP server in explicit attach mode. Once
the synth -> implementation -> write_bitstream chain is healthy, disconnect
and exit; export, deployment and final routed-report review require the next
user continuation under AGENTS.md.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import timedelta
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[2]
REMOTE = 'astrolab@192.168.100.162'
REMOTE_PYTHON = '/var/lib/t510/measurements/control/s2-analysis-v1-20260831-2059/venv/bin/python'
VIVADO = '/run/media/astrolab/data/xilinx-ep/Vivado/2022.2/bin/vivado'
COMPLETE = re.compile(r'^STAGE36_REAL_XFFT_COMPLETE frames=35 overflow=0 slave_wait_cycles=\d+$', re.M)
FAILURE = re.compile(r'^(?:Fatal:|Error:|STAGE36_REAL_XFFT_R4_FAILED)', re.M | re.I)


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def atomic(path, value):
    temporary = path.with_suffix(path.suffix + '.partial')
    with temporary.open('w') as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
    temporary.replace(path)


def process_identity(pid):
    root = Path('/proc') / str(pid)
    stat = (root/'stat').read_text().rsplit(')', 1)[1].split()
    if stat[0] == 'Z':
        raise RuntimeError(f'process {pid} became a zombie')
    return dict(pid=pid, start_ticks=stat[19],
                cmdline=(root/'cmdline').read_bytes().replace(b'\0', b' ').decode())


def source_identity():
    paths = set()
    for directory in ('rtl', 'bd', 'constraints', 'python'):
        paths.update(p for p in (ROOT/directory).rglob('*')
                     if p.is_file() and '__pycache__' not in p.parts)
    paths.update((ROOT/'demo-ant.srcs').rglob('*.xci'))
    paths.update(ROOT/'scripts'/name for name in (
        'setup_project.tcl', 't510_prepare_current_project.tcl',
        't510_arm_current_project_build_chain.tcl', 't510_export_current_project.tcl'))
    paths.update((ROOT/'scripts/stage-36'/name) for name in (
        't510_stage36_precision_build_queue.py', 't510_stage36_fft_precision.py',
        't510_stage36_fft_contract.py', 't510_stage36_vendor_fft.py'))
    paths.update((ROOT/'scripts/stage-35'/name) for name in (
        't510_stage35_pfb_white_model.py', 't510_stage35_time_verify.py'))
    paths.add(ROOT/'sim/tb_stage36_xfft_precision.sv')
    return {str(p.relative_to(ROOT)): sha(p) for p in sorted(paths)}


def mcp_text(result):
    text = '\n'.join(item.text for item in result.content if hasattr(item, 'text'))
    if result.isError or '[ERROR]' in text:
        raise RuntimeError(text)
    return text


class Queue:
    def __init__(self, args):
        self.args = args
        self.root = args.evidence.resolve()
        self.fixture = self.root/'fft-fixture'
        self.state_path = self.root/'precision-build-queue.json'
        self.state = dict(format='T510_STAGE36_PRECISION_BUILD_QUEUE_V1', status='armed',
                          phases=['original_XSim_35_frames', 'independent_numeric_verification',
                                  'GUI_MCP_synth', 'GUI_impl_through_write_bitstream'],
                          synthesis_started=False, automatic_continuation_armed=True,
                          gui_chain_armed=False, build_submission_outcome='not_attempted',
                          created_unix_s=time.time(), gui_port=9999,
                          remote_evidence=args.remote_evidence)

    def save(self, **fields):
        self.state.update(fields, updated_unix_s=time.time())
        atomic(self.state_path, self.state)

    def command(self, name, argv, timeout=300):
        result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        atomic(self.root/(name+'.json'), dict(argv=argv, returncode=result.returncode,
                                            stdout=result.stdout, stderr=result.stderr))
        if result.returncode:
            raise RuntimeError(f'{name} failed: {result.stderr or result.stdout}')
        return result.stdout

    def ssh(self, name, argv, timeout=300):
        return self.command(name, ['ssh', '-o', 'BatchMode=yes', REMOTE, shlex.join(argv)], timeout)

    async def run(self):
        if self.state_path.exists():
            raise RuntimeError('queue already exists; inspect original task instead of resubmitting')
        self.root.mkdir(parents=True, exist_ok=True)
        self.state['gui_process'] = process_identity(self.args.gui_pid)
        self.state['simulation_process'] = process_identity(self.args.simulation_pid)
        if 'tb_stage36_xfft_precision_behav/xsimk ' not in self.state['simulation_process']['cmdline']:
            raise RuntimeError('PID does not identify the original precision simulation')
        if str(self.fixture/'real_xfft_output.txt') not in self.state['simulation_process']['cmdline']:
            raise RuntimeError('simulation is writing a different fixture')
        metadata = json.loads((self.fixture/'fixture.json').read_text())
        if sha(self.fixture/'input.mem') != metadata['input_mem_sha256']:
            raise RuntimeError('simulation input changed since fixture generation')
        for name in ('python-validation.json', 'rtl-regression-verification.json'):
            if json.loads((self.root/name).read_text())['status'] != 'PASS':
                raise RuntimeError(f'prerequisite did not pass: {name}')
        rust = (self.root/'rust-board-agent-validation.log').read_text()
        if 'test result: ok. 8 passed; 0 failed' not in rust:
            raise RuntimeError('Rust prerequisite did not pass')
        self.sources = source_identity()
        atomic(self.root/'queued-source-sha256.json', self.sources)
        self.fixture_hashes = {n: sha(self.fixture/n) for n in ('fixture.json', 'input.mem', 'reference.npz')}
        self.save(status='running', phase='original_XSim_35_frames',
                  fixture_sha256=self.fixture_hashes, log_offset=self.args.log_offset)

        # This observes the original kernel; it never takes over its execution.
        # All future phases have already been defined before the first wait.
        started = time.monotonic()
        while True:
            if process_identity(self.args.gui_pid) != self.state['gui_process']:
                raise RuntimeError('original Vivado GUI identity changed')
            with self.args.gui_log.open('rb') as stream:
                stream.seek(self.args.log_offset)
                log = stream.read().decode(errors='replace')
            if FAILURE.search(log):
                (self.root/'real-xfft-final-session.log').write_text(log)
                raise RuntimeError('original XSim reported a failure; build remains unsubmitted')
            if COMPLETE.search(log) and 'STAGE36_REAL_XFFT_R4_FINISHED_CHECK_OUTPUT_REQUIRED' in log:
                (self.root/'real-xfft-final-session.log').write_text(log)
                break
            if process_identity(self.args.simulation_pid) != self.state['simulation_process']:
                raise RuntimeError('original simulation kernel identity changed before completion')
            if time.monotonic()-started > self.args.maximum_wait_seconds:
                raise RuntimeError('simulation wait deadline reached; original kernel was not cancelled')
            output = self.fixture/'real_xfft_output.txt'
            self.save(output_bytes=output.stat().st_size if output.exists() else 0,
                      original_simulation_alive=True)
            await asyncio.sleep(30)

        if source_identity() != self.sources:
            raise RuntimeError('sources changed during simulation; refuse an unverified build')
        if any(sha(self.fixture/n) != digest for n, digest in self.fixture_hashes.items()):
            raise RuntimeError('fixture changed during simulation')
        self.save(phase='independent_numeric_verification',
                  output_sha256=sha(self.fixture/'real_xfft_output.txt'))
        remote = self.args.remote_evidence
        if not remote.startswith('/var/lib/t510/stage36/'+self.root.name+'/'):
            raise RuntimeError('remote evidence must be an exclusive Stage 36 subdirectory')
        self.ssh('fft_remote_create', ['mkdir', remote])  # exclusive new evidence directory
        inputs = [self.fixture/n for n in ('fixture.json', 'input.mem', 'reference.npz', 'real_xfft_output.txt',
                    'vendor_xfft_crosscheck.json', 'vendor_xfft_output.txt',
                    'real_xfft_prefix_preserved.txt', 'production_xfft.vhd')]
        inputs += [ROOT/'scripts/stage-36'/n for n in ('t510_stage36_fft_precision.py',
                                                       't510_stage36_fft_contract.py')]
        inputs += [ROOT/'scripts/stage-35'/n for n in ('t510_stage35_pfb_white_model.py',
                                                       't510_stage35_time_verify.py')]
        self.command('fft_remote_copy', ['scp', *map(str, inputs), f'{REMOTE}:{remote}/'])
        for index, path in enumerate(inputs):
            remote_hash = self.ssh(f'fft_remote_hash_{index}', ['sha256sum', remote+'/'+path.name]).split()[0]
            if remote_hash != sha(path):
                raise RuntimeError(f'remote copy hash mismatch: {path.name}')
        self.ssh('fft_numeric_check', [REMOTE_PYTHON, remote+'/t510_stage36_fft_precision.py',
                                      'check', '--root', remote, '--dump', remote+'/real_xfft_output.txt'])
        self.command('fft_result_copy', ['scp', f'{REMOTE}:{remote}/real_xfft_verification.json', str(self.fixture)])
        result = json.loads((self.fixture/'real_xfft_verification.json').read_text())
        if result['status'] != 'PASS' or result['output_frames'] != 35 or result['output_complex_cells'] != 35*4096*8:
            raise RuntimeError('independent real-XFFT numerical gate did not pass')
        if source_identity() != self.sources:
            raise RuntimeError('sources changed before build submission')
        self.save(phase='GUI_MCP_build_submission', numeric_verification=result)
        await self.submit_build()

    async def submit_build(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        # This subprocess is ONLY an MCP server. Explicit attach mode cannot
        # spawn Vivado; its cleanup disconnects without terminating the GUI.
        parameters = StdioServerParameters(command=sys.executable,
                                           args=['-m', 'vivado_mcp', 'serve'], cwd=str(ROOT))
        with (self.root/'continuation-mcp-server.log').open('w') as stderr:
            async with stdio_client(parameters, errlog=stderr) as (read, write):
                async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=720)) as client:
                    await client.initialize()
                    response = mcp_text(await client.call_tool('start_session', dict(
                        session_id='stage36_continuation', mode='attach', port=9999,
                        vivado_path=VIVADO, timeout=60)))
                    self.save(mcp_attach=response)
                    command = '''
if {[get_property NAME [current_project]] ne "demo-ant" ||
    [file normalize [get_property DIRECTORY [current_project]]] ne "/home/astrolab/demo-ant" ||
    [get_property PART [current_project]] ne "xczu47dr-ffve1156-2-i"} {error "wrong GUI project"}
if {[llength [get_property verilog_define [get_filesets sources_1]]]} {error "unexpected synthesis defines"}
if {[info exists ::t510_build_chain::armed] && $::t510_build_chain::armed} {error "another build chain is armed"}
foreach r {synth_1 impl_1} {
    if {[get_property STATUS [get_runs $r]] ne "Not started"} {error "run $r changed; do not reset or resubmit it"}
}
catch {close_sim -force}
current_fileset -simset [get_filesets sim_1]
set_property STEPS.PHYS_OPT_DESIGN.IS_ENABLED true [get_runs impl_1]
source /home/astrolab/demo-ant/scripts/t510_arm_current_project_build_chain.tcl
::t510_build_chain::start 8
list STAGE36_COMPLETE_BUILD_CHAIN_ARMED $::t510_build_chain::armed [get_property STATUS [get_runs synth_1]]
'''
                    # No retry of this mutation, including after a timeout.
                    self.save(submission_command=command, submission_attempted=True,
                              gui_chain_armed=None, build_submission_outcome='unknown_until_acknowledged')
                    response = mcp_text(await client.call_tool('run_tcl', dict(
                        session_id='stage36_continuation', command=command, timeout=600)))
                    if 'STAGE36_COMPLETE_BUILD_CHAIN_ARMED' not in response:
                        raise RuntimeError('build submission response did not confirm the full chain')
                    self.save(synthesis_started=True, submission_response=response,
                              gui_chain_armed=True, build_submission_outcome='acknowledged')
                    for delay in (10, 20, 30, 60):
                        await asyncio.sleep(delay)
                        query = '''
set s [get_property STATUS [get_runs synth_1]]
set i [get_property STATUS [get_runs impl_1]]
set active {}
foreach r [get_runs] {if {[string match -nocase *running* [get_property STATUS $r]]} {lappend active $r}}
set healthy [expr {($::t510_build_chain::armed && [regexp -nocase {running|queued} $s] && [llength $active]) || [string match -nocase *running* $i]}]
list STAGE36_HEALTH $healthy $::t510_build_chain::armed $s $i $active
'''
                        health = mcp_text(await client.call_tool('run_tcl', dict(
                            session_id='stage36_continuation', command=query, timeout=60)))
                        self.save(build_health=health)
                        if re.search(r'error|fail|cancel', health, re.I):
                            raise RuntimeError(f'build failed during healthy-start confirmation: {health}')
                        if re.search(r'STAGE36_HEALTH 1(?:\s|$)', health):
                            self.save(status='build_submitted', phase='await_user_build_completion',
                                      healthy_start_confirmed=True,
                                      handoff='No final run/report/export checks; wait for user continuation')
                            return
                    raise RuntimeError('full chain submitted, but healthy start not confirmed; inspect original runs')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--gui-log', type=Path, required=True)
    parser.add_argument('--log-offset', type=int, required=True)
    parser.add_argument('--gui-pid', type=int, required=True)
    parser.add_argument('--simulation-pid', type=int, required=True)
    parser.add_argument('--remote-evidence', required=True)
    parser.add_argument('--maximum-wait-seconds', type=int, default=21600)
    args = parser.parse_args()
    queue = Queue(args)
    with (queue.root/'precision-build-queue.lock').open('a+b') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if queue.state_path.exists():
            raise SystemExit('original queue state already exists; refusing resubmission without modifying it')
        try:
            asyncio.run(queue.run())
        except Exception as exc:
            queue.save(status='failed', automatic_continuation_armed=False,
                       error=f'{type(exc).__name__}: {exc}', traceback=traceback.format_exc())
            raise


if __name__ == '__main__':
    main()
