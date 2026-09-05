"""Exercise the exact Tcl pre-bitstream report parser without running Vivado."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
HEADER='WNS(ns) TNS(ns) TNS Failing Endpoints TNS Total Endpoints WHS(ns) THS(ns) THS Failing Endpoints THS Total Endpoints WPWS(ns) TPWS(ns) TPWS Failing Endpoints TPWS Total Endpoints'
class TimingGateTests(unittest.TestCase):
    def hook(self, exact_bad=False, route_errors=0):
        with tempfile.TemporaryDirectory() as temp:
            script='set report {'+HEADER+'\n0.010 0.000 0 100 0.010 0.000 0 100 0.010 0.000 0 100\n}\n'
            script+='proc report_timing_summary args {set f [open [lindex $args end] w]; puts $f $::report; close $f}\n'
            script+='proc report_route_status args {set f [open [lindex $args end] w]; puts $f {# of nets with routing errors.......... : '+str(route_errors)+' :}; close $f}\n'
            script+='proc get_timing_paths args {return {'+('bad_path' if exact_bad else '')+'}}\n'
            script+='proc get_property args {return -0.000001}\n'
            script+='if {[catch {source {'+str(ROOT/'scripts/t510_pre_bitstream_gate.tcl')+'}} detail]} {puts $detail; exit 1}\n'
            r=subprocess.run(['tclsh'],input=script,text=True,capture_output=True,cwd=temp)
            return r,(Path(temp)/'current_pre_bitstream_gate.txt').read_text()
    def test_full_hook_positive_control(self):
        r,status=self.hook();self.assertEqual(r.returncode,0,r.stdout+r.stderr);self.assertTrue(status.startswith('PASS'))
    def test_full_hook_exact_sub_precision_failure(self):
        r,status=self.hook(exact_bad=True);self.assertNotEqual(r.returncode,0);self.assertIn('negative exact',status)
    def test_full_hook_route_error(self):
        r,status=self.hook(route_errors=1);self.assertNotEqual(r.returncode,0);self.assertIn('routing errors',status)
    def parse(self,row):
        script='source {'+str(ROOT/'scripts/t510_timing_gate_common.tcl')+'}\n'
        script+='if {[catch {::t510_timing_gate::parse_summary {'+HEADER+'\n------- -------\n'+row+'\n}} detail]} {puts "FAIL $detail"; exit 1}\nputs "PASS $detail"\n'
        return subprocess.run(['tclsh'],input=script,text=True,capture_output=True)
    def test_positive_timing_passes(self):
        r=self.parse('0.050 0.000 0 453719 0.009 0.000 0 453719 0.052 0.000 0 196993');self.assertEqual(r.returncode,0,r.stdout+r.stderr)
    def test_actual_negative_slack_failure_rejected(self):
        r=self.parse('-0.195 -27.846 603 453719 0.009 0.000 0 453719 0.052 0.000 0 196993');self.assertNotEqual(r.returncode,0);self.assertIn('WNS=-0.195',r.stdout)
    def test_rounded_zero_setup_failure_rejected(self):
        self.assertNotEqual(self.parse('-0.000 -0.000 1 100 0.010 0.000 0 100 0.010 0.000 0 100').returncode,0)
    def test_hold_failure_rejected(self):
        self.assertNotEqual(self.parse('0.010 0.000 0 100 -0.005 -0.005 1 100 0.010 0.000 0 100').returncode,0)
    def test_pulse_width_failure_rejected(self):
        self.assertNotEqual(self.parse('0.010 0.000 0 100 0.010 0.000 0 100 -0.005 -0.005 1 100').returncode,0)
    def test_missing_or_malformed_summary_rejected(self):
        for row in ('','NA 0 0 100 0 0 0 100 0 0 0 100','0 0 0'):
            with self.subTest(row=row):self.assertNotEqual(self.parse(row).returncode,0)
if __name__=='__main__':unittest.main()
