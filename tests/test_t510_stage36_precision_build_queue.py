import sys
import argparse
import asyncio
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts/stage-36'))
import t510_stage36_precision_build_queue as module


class ContinuationTests(unittest.TestCase):
    def fixture(self, root, log):
        fixture = root/'fft-fixture'; fixture.mkdir()
        (fixture/'input.mem').write_text('0000\n')
        (fixture/'reference.npz').write_bytes(b'fixture')
        (fixture/'real_xfft_output.txt').write_text('original simulation output\n')
        for name in ('vendor_xfft_crosscheck.json', 'vendor_xfft_output.txt',
                     'real_xfft_prefix_preserved.txt', 'production_xfft.vhd'):
            (fixture/name).write_text('mocked remote verifier evidence\n')
        (fixture/'fixture.json').write_text(json.dumps({'input_mem_sha256':module.sha(fixture/'input.mem')}))
        for name in ('python-validation.json', 'rtl-regression-verification.json'):
            (root/name).write_text('{"status":"PASS"}')
        (root/'rust-board-agent-validation.log').write_text('test result: ok. 8 passed; 0 failed')
        (root/'gui.log').write_text(log)
        args = argparse.Namespace(evidence=root, gui_log=root/'gui.log', log_offset=0,
            gui_pid=1, simulation_pid=2, maximum_wait_seconds=5,
            remote_evidence='/var/lib/t510/stage36/'+root.name+'/test')
        queue = module.Queue(args)
        queue.submit_build = AsyncMock()
        def identity(pid):
            return dict(pid=pid, start_ticks='1', cmdline='vivado' if pid==1 else
                'xsim.dir/tb_stage36_xfft_precision_behav/xsimk '+str(fixture/'real_xfft_output.txt'))
        return queue, identity

    def test_simulation_failure_never_reaches_build(self):
        with tempfile.TemporaryDirectory() as temp:
            queue, identity = self.fixture(Path(temp), 'Fatal: FFT overflow\n')
            with patch.object(module, 'process_identity', side_effect=identity), \
                 patch.object(module, 'source_identity', return_value={'rtl':'a'}):
                with self.assertRaisesRegex(RuntimeError, 'reported a failure'):
                    asyncio.run(queue.run())
            queue.submit_build.assert_not_called()

    def test_source_drift_blocks_before_remote_verification(self):
        with tempfile.TemporaryDirectory() as temp:
            queue, identity = self.fixture(Path(temp),
                'STAGE36_REAL_XFFT_COMPLETE frames=35 overflow=0 slave_wait_cycles=3\n'
                'STAGE36_REAL_XFFT_R4_FINISHED_CHECK_OUTPUT_REQUIRED\n')
            with patch.object(module, 'process_identity', side_effect=identity), \
                 patch.object(module, 'source_identity', side_effect=[{'rtl':'a'},{'rtl':'b'}]):
                with self.assertRaisesRegex(RuntimeError, 'sources changed'):
                    asyncio.run(queue.run())
            queue.submit_build.assert_not_called()

    def test_build_only_after_independent_numeric_pass(self):
        for numeric_pass in (False, True):
            with self.subTest(numeric_pass=numeric_pass), tempfile.TemporaryDirectory() as temp:
                queue, identity = self.fixture(Path(temp),
                    'STAGE36_REAL_XFFT_COMPLETE frames=35 overflow=0 slave_wait_cycles=3\n'
                    'STAGE36_REAL_XFFT_R4_FINISHED_CHECK_OUTPUT_REQUIRED\n')
                inputs = [queue.fixture/n for n in ('fixture.json','input.mem','reference.npz','real_xfft_output.txt',
                    'vendor_xfft_crosscheck.json','vendor_xfft_output.txt',
                    'real_xfft_prefix_preserved.txt','production_xfft.vhd')]
                inputs += [module.ROOT/'scripts/stage-36'/n for n in (
                            't510_stage36_fft_precision.py','t510_stage36_fft_contract.py')]
                inputs += [module.ROOT/'scripts/stage-35'/n for n in (
                            't510_stage35_pfb_white_model.py','t510_stage35_time_verify.py')]
                calls = []
                def ssh(name, argv, timeout=300):
                    calls.append(name)
                    if name.startswith('fft_remote_hash_'):
                        return module.sha(inputs[int(name.rsplit('_',1)[1])])+' file'
                    if name=='fft_numeric_check' and not numeric_pass:
                        raise RuntimeError('numerical gate failed')
                    return ''
                def command(name, argv, timeout=300):
                    calls.append(name)
                    if name=='fft_result_copy':
                        (queue.fixture/'real_xfft_verification.json').write_text(json.dumps(
                            dict(status='PASS',output_frames=35,output_complex_cells=35*4096*8)))
                    return ''
                queue.ssh=ssh;queue.command=command
                with patch.object(module, 'process_identity', side_effect=identity), \
                     patch.object(module, 'source_identity', return_value={'rtl':'a'}):
                    if numeric_pass:
                        asyncio.run(queue.run());queue.submit_build.assert_awaited_once()
                        self.assertLess(calls.index('fft_numeric_check'),calls.index('fft_result_copy'))
                    else:
                        with self.assertRaisesRegex(RuntimeError, 'numerical gate failed'):
                            asyncio.run(queue.run())
                        queue.submit_build.assert_not_called()

    def test_duplicate_submission_preserves_original_state(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);state=root/'precision-build-queue.json';state.write_text('{"status":"running"}')
            before=state.read_bytes()
            argv=['queue','--evidence',temp,'--gui-log',temp+'/log','--log-offset','0',
                  '--gui-pid','1','--simulation-pid','2','--remote-evidence','unused']
            with patch.object(module.sys, 'argv', argv), self.assertRaises(SystemExit):
                module.main()
            self.assertEqual(state.read_bytes(),before)

    def test_process_identity_has_stable_birth_identity(self):
        identity=module.process_identity(os.getpid())
        self.assertEqual(identity['pid'],os.getpid())
        self.assertTrue(identity['start_ticks'].isdigit())


if __name__=='__main__':
    unittest.main()
