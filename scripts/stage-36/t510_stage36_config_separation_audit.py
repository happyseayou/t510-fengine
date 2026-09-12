#!/usr/bin/env python3
"""Offline call-boundary audit. No hardware access or acquisition."""
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from python.t510_fengine import T510FEngine

class ReachedDigitalSetup(Exception): pass

class Audit(unittest.TestCase):
    def initialization_probe(self, locked=True):
        clock = dict(configured=True, selected_ref='tcxo_10mhz',
                     profile_id='160m_10m_request_manual_clkin0',
                     pll1_lock=int(locked), pll2_lock=1)
        c = SimpleNamespace(clock=SimpleNamespace(read_status=Mock(return_value=clock)),
            validate_observation_frequency_plan=Mock(),
            _normalize_input_source_mode=T510FEngine._normalize_input_source_mode,
            stop=Mock(), configure_clock=Mock(), reset_all_rfdc_tiles=Mock(),
            _write_sync_config=Mock(), CLOCK_REFS={'tcxo_10mhz':1},
            set_adc_active_mask=Mock(), set_sync_mode=Mock(), set_mode=Mock(),
            RFDC_COMPLEX_SAMPLE_RATE_HZ=320000000, RFDC_DECIMATION=12,
            configure_rfdc=Mock(side_effect=ReachedDigitalSetup))
        kwargs=dict(observe_center_hz=200e6,dac_signal_hz=200e6,view_bw_hz=320e6,
            initialize=True,force_clock_reconfigure=False,require_clock_preserved=True,
            clock_ref='tcxo_10mhz',clock_profile='160m_10m_request_manual_clkin0')
        return c,kwargs

    def test_initialize_true_preserves_verified_clock_without_tile_reset(self):
        c,k=self.initialization_probe()
        with patch('python.t510_fengine.time.sleep'),self.assertRaises(ReachedDigitalSetup):
            T510FEngine.apply_sysref_locked_observation_config(c,**k)
        c.configure_clock.assert_not_called();c.reset_all_rfdc_tiles.assert_not_called()
        c.configure_rfdc.assert_called_once()

    def test_bad_clock_fails_before_digital_setup_or_recovery(self):
        c,k=self.initialization_probe(False)
        with patch('python.t510_fengine.time.sleep'),self.assertRaisesRegex(RuntimeError,'PRESERVE_GATE'):
            T510FEngine.apply_sysref_locked_observation_config(c,**k)
        c.configure_clock.assert_not_called();c.reset_all_rfdc_tiles.assert_not_called()
        c.configure_rfdc.assert_not_called()

    def test_require_mts_false_still_calls_mts(self):
        c=SimpleNamespace(rfdc=object(), _run_rfdc_mts_sequence=Mock(return_value={'available':True}),
            _configure_rfdc_mixer_blocks_sysref=Mock(return_value={'configured':True,'uses_sysref_event':False}),
            clock=SimpleNamespace(set_sysref=Mock(return_value={})),
            read_rfdc_contract=Mock(return_value={'ok':True}))
        T510FEngine._configure_rfdc_sysref_locked_pair(c,adc_nco_hz=-200e6,dac_nco_hz=200e6,
            bandwidth_hz=320e6,require_mts=False)
        c._run_rfdc_mts_sequence.assert_called_once()
        self.assertFalse(c._run_rfdc_mts_sequence.call_args.kwargs['required'])

    def test_mixer_no_reset_sequence_is_only_register_programming(self):
        # Existing block writer has separate SYSREF/reset choices, but its return
        # is not proof of a hardware update: external SYSREF commit follows it.
        class Block:
            MixerSettings={'Freq':0,'EventSource':0}
            NyquistZone=1
            ResetNCOPhase=Mock()
            UpdateEvent=Mock()
        blocks=[Block() for _ in range(16)]
        c=T510FEngine.__new__(T510FEngine)
        c.rfdc=SimpleNamespace(adc_tiles=[SimpleNamespace(blocks=blocks[:8])],
                              dac_tiles=[SimpleNamespace(blocks=blocks[8:])])
        with patch.object(c,'_iter_rfdc_blocks',side_effect=lambda tile:tile.blocks):
            result=c._configure_rfdc_mixer_blocks_sysref(adc_nco_hz=-200e6,dac_nco_hz=200e6,
                                                       require=True,rfdc_mixer_sequence='sysref_no_reset')
        self.assertTrue(result['uses_sysref_event'])
        Block.ResetNCOPhase.assert_not_called();Block.UpdateEvent.assert_not_called()
        self.assertEqual(result['adc_blocks'],8);self.assertEqual(result['dac_blocks'],8)

if __name__=='__main__':unittest.main(verbosity=2)
