import copy,tempfile,unittest
from pathlib import Path
import numpy as np
from python.t510_background import fit,apply,load_template
class BackgroundTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.path=Path(self.tmp.name)/'template'
  self.c=dict(initialization_epoch='one',wiring_id='independent-loads',configuration_sha256='a'*64,core_version='current-test',bitstream_sha256='b'*64,pair_order=[[0,1]],frequency_bins=[0],source_manifest_sha256='c'*64,source_id='source',start_unix_s=0,end_unix_s=60,role='reference')
  self.v=np.array([[[1+2j]],[[3+4j]]]);self.w=np.array([[1.],[3.]])
  fit(self.v,self.w,self.c,self.path);self.target={**self.c,'start_unix_s':60,'end_unix_s':120,'role':'target'}
 def test_weighted_complex_and_holdout(self):
  m,b=load_template(self.path);self.assertEqual(b[0,0],2.5+3.5j)
  raw=np.array([[[5+8j]],[[2+7j]]]);before=raw.copy();r,m=apply(raw,self.w,self.target,template=self.path)
  np.testing.assert_array_equal(raw,before);np.testing.assert_allclose(r,raw-(2.5+3.5j));self.assertEqual(m['status'],'corrected')
  np.testing.assert_allclose(np.diff(r,axis=0),np.diff(raw,axis=0));np.testing.assert_allclose(r-r.mean(0),raw-raw.mean(0))
 def test_identity_changes(self):
  for key,value in [('initialization_epoch','reset'),('wiring_id','antenna'),('configuration_sha256','d'*64),('frequency_bins',[1]),('pair_order',[[1,2]])]:
   c={**self.target,key:value};r,m=apply(self.v,self.w,c,template=self.path);self.assertIsNone(r);self.assertIn(key+' mismatch',m['reasons'])
   with self.assertRaises(ValueError):apply(self.v,self.w,c,template=self.path,mode='required')
 def test_overlap_expiry_and_missing(self):
  for c in ({**self.target,'start_unix_s':59},{**self.target,'end_unix_s':361}):self.assertIsNone(apply(self.v,self.w,c,template=self.path)[0])
  self.assertIsNone(apply(self.v,self.w,self.target)[0])
  with self.assertRaises(ValueError):fit(self.v,self.w,self.target,Path(self.tmp.name)/'bad')
 def test_tamper_and_bad_weights(self):
  (self.path/'background.npz').write_bytes(b'corrupt')
  with self.assertRaises(ValueError):apply(self.v,self.w,self.target,template=self.path)
  with self.assertRaises(ValueError):apply(self.v,np.zeros_like(self.w),self.target)
if __name__=='__main__':unittest.main()
