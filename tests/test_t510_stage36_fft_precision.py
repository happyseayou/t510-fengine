"""Integration regressions using the frozen measured Stage 36 fixture.

Set STAGE36_FFT_FIXTURE to a qualified V2 fixture; requires NumPy. Mutations
use private copies and never alter the frozen evidence or vendor libraries.
"""
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts/stage-36'))
from t510_stage36_fft_contract import sha, verify_contract, verify_ip

FIXTURE = os.environ.get('STAGE36_FFT_FIXTURE')

@unittest.skipUnless(FIXTURE, 'requires qualified Stage 36 measured fixture')
class PrecisionContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='stage36-fft-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)/'fixture'
        shutil.copytree(FIXTURE,self.root)

    def update_proof(self, change):
        p=self.root/'vendor_xfft_crosscheck.json'
        proof=json.loads(p.read_text());change(proof)
        p.write_text(json.dumps(proof))

    def check(self, dump=None):
        from t510_stage36_fft_precision import check
        with contextlib.redirect_stdout(io.StringIO()):
            check(self.root,dump or self.root/'vendor_xfft_output.txt','vendor')

    def test_real_fixture_passes_preserving_old_float_exceedance(self):
        self.check()
        result=json.loads((self.root/'vendor_xfft_verification.json').read_text())
        self.assertEqual(result['status'],'PASS')
        self.assertEqual(result['legacy_float_4_count_exceedances'],1)
        self.assertGreater(result['max_fft_float_error_count'],4)
        self.assertLess(result['new_over_old_mse'],1)

    def test_single_bit_output_error_rejected_even_below_old_float_limit(self):
        p=self.root/'bad_output.txt'
        lines=(self.root/'vendor_xfft_output.txt').read_text().splitlines()
        fields=lines[0].split();fields[2]=f'{int(fields[2],16)^1:064x}';lines[0]=' '.join(fields)
        p.write_text('\n'.join(lines)+'\n')
        with self.assertRaisesRegex(RuntimeError,'bit-accurate oracle'):
            self.check(p)
        self.assertFalse((self.root/'vendor_xfft_verification.json').exists())

    def test_stale_input_identity_rejected(self):
        p=self.root/'input.mem';p.write_text(p.read_text()+'0\n')
        with self.assertRaisesRegex(RuntimeError,'identity mismatch'):
            verify_contract(self.root)

    def test_overflow_rejected(self):
        self.update_proof(lambda p:p.update(model_overflow=1))
        with self.assertRaisesRegex(RuntimeError,'overflow'):
            verify_contract(self.root)

    def test_wrong_model_rounding_rejected(self):
        self.update_proof(lambda p:p['generics'].update(C_HAS_ROUNDING=0))
        with self.assertRaisesRegex(RuntimeError,'configuration mismatch'):
            verify_contract(self.root)

    def test_production_ip_rounding_change_rejected(self):
        p=self.root/'production_xfft.vhd'
        p.write_text(p.read_text().replace('C_HAS_ROUNDING => 1','C_HAS_ROUNDING => 0'))
        with self.assertRaisesRegex(RuntimeError,'parameter mismatch'):
            verify_ip(p)

    def test_incomplete_rtl_witness_rejected_even_with_updated_digest(self):
        p=self.root/'real_xfft_prefix_preserved.txt';p.write_text(p.read_text().splitlines()[0]+'\n')
        self.update_proof(lambda x:x['artifact_sha256'].update({p.name:sha(p)}))
        with self.assertRaisesRegex(RuntimeError,'inadequate'):
            verify_contract(self.root)

    def test_nonfinite_float_reference_rejected(self):
        import numpy as np
        p=self.root/'reference.npz'
        with np.load(p) as data:ref={k:data[k].copy() for k in data.files}
        ref['floating'][0,0,0]=np.nan
        np.savez_compressed(p,**ref)
        self.update_proof(lambda x:x['artifact_sha256'].update({p.name:sha(p)}))
        with self.assertRaisesRegex(RuntimeError,'nonfinite'):
            self.check()

    def test_error_regression_rejected(self):
        import numpy as np
        p=self.root/'reference.npz'
        with np.load(p) as data:ref={k:data[k].copy() for k in data.files}
        rows=(self.root/'vendor_xfft_output.txt').read_text().splitlines()[3*4096:19*4096]
        for line in rows:
            f,k,w=line.split();w=int(w,16)
            v=np.array([(w>>(16*j))&65535 for j in range(16)],dtype=np.uint16).view(np.int16)
            ref['ideal_fft'][int(f)-3,int(k)]=v[::2].astype(float)+1j*v[1::2]
        np.savez_compressed(p,**ref)
        self.update_proof(lambda x:x['artifact_sha256'].update({p.name:sha(p)}))
        with self.assertRaisesRegex(RuntimeError,'did not improve'):
            self.check()

if __name__=='__main__':unittest.main()
