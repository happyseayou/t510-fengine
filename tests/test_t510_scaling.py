from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from python.t510_fengine import RegisterMap, T510FEngine
from python.t510_scaling import (CURRENT_CORE_VERSION, CURRENT_QMC_GAIN, qmc_settings,
                                 scaling_identity, manifest_metadata, historical_unit_divisor)


def rows():
    return [dict(tile=t, block=b, qmc=qmc_settings()) for t in range(4) for b in range(2)]


class ScalingTests(unittest.TestCase):
    def test_actual_units_and_schedule(self):
        result = scaling_identity(CURRENT_CORE_VERSION, 0x556, rows())
        self.assertTrue(result['ok'])
        self.assertEqual(result['time_voltage_gain_by_adc'], [CURRENT_QMC_GAIN]*8)
        self.assertEqual(result['spec_voltage_gain_by_adc'], [2*CURRENT_QMC_GAIN]*8)
        self.assertEqual(result['pfb_output_shift'], 16)
        self.assertEqual(result['fft_shift'], 0x556)

    def test_missing_adc_or_changed_qmc_rejected(self):
        for key, value in [('EnableGain', 0), ('EnablePhase', 1),
                           ('GainCorrectionFactor', 1.0), ('OffsetCorrectionFactor', 1),
                           ('EventSource', 3)]:
            actual = rows()
            actual[7]['qmc'][key] = value
            self.assertFalse(scaling_identity(CURRENT_CORE_VERSION, 0x556, actual)['ok'])
        self.assertFalse(scaling_identity(CURRENT_CORE_VERSION, 0x556, rows()[:-1])['ok'])
        self.assertFalse(scaling_identity(CURRENT_CORE_VERSION, 0x555, rows())['ok'])

    def test_manifest_and_scientific_gain_powers(self):
        result = scaling_identity(CURRENT_CORE_VERSION, 0x556, rows())
        self.assertEqual(manifest_metadata(result)['fft_shift'], '0x0556')
        gain = 2*CURRENT_QMC_GAIN
        for product, factor in [('power', gain**2), ('allan_power_variance', gain**4),
                                ('normalized_allan_variance', 1)]:
            self.assertEqual(historical_unit_divisor(result, product, stream='spec', adc=0), factor)
        self.assertEqual(historical_unit_divisor(result, 'visibility', stream='spec', adc=0, other_adc=7), gain**2)
        self.assertEqual(historical_unit_divisor(result, 'allan_visibility_variance', stream='spec', adc=0, other_adc=7), gain**4)
        result['pfb_output_shift'] = 17
        with self.assertRaises(ValueError):
            manifest_metadata(result)

    def test_disabled_legacy_gain_is_unity_even_register_zero(self):
        actual = rows()
        for row in actual:
            row['qmc'].update(EnableGain=0, GainCorrectionFactor=0.0, EventSource=0)
        result = scaling_identity(0x00010034, 0x556, actual)
        self.assertTrue(result['ok'])
        self.assertEqual(result['spec_voltage_gain_by_adc'], [1.0]*8)
        self.assertFalse(scaling_identity(0x00010037, 0x556, actual)['ok'])

    def make_core(self):
        core = object.__new__(T510FEngine)
        core.regs = RegisterMap()
        core.ctrl = Mock()
        core.ctrl.read.side_effect = lambda address: CURRENT_CORE_VERSION if address == core.regs.CORE_VERSION else 0x556
        core.rfdc = SimpleNamespace(adc_tiles=[SimpleNamespace(blocks=[
            SimpleNamespace(QMCSettings={}, UpdateEvent=Mock()) for _ in range(2)]) for _ in range(4)])
        core.read_status = Mock(return_value={'streaming': False})
        return core

    def test_configure_then_start_and_reject_drift(self):
        core = self.make_core()
        with patch.dict('sys.modules', {'xrfdc': SimpleNamespace(EVENT_QMC=4)}):
            self.assertTrue(core.configure_digital_scaling()['ok'])
        core.start()
        core.ctrl.write.assert_called_with(core.regs.CONTROL, 1)
        core.ctrl.write.reset_mock()
        core.rfdc.adc_tiles[2].blocks[1].QMCSettings['EnableGain'] = 0
        with self.assertRaisesRegex(RuntimeError, 'DIGITAL_SCALING_MISMATCH'):
            core.start()
        with self.assertRaisesRegex(RuntimeError, 'DIGITAL_SCALING_MISMATCH'):
            core.arm_scheduled_sync()
        core.ctrl.write.assert_not_called()

    def test_reject_mutation_during_stream(self):
        core = self.make_core()
        core.read_status.return_value = {'streaming': True}
        with self.assertRaisesRegex(RuntimeError, 'stopped'):
            core.configure_digital_scaling()
        self.assertEqual(core.rfdc.adc_tiles[0].blocks[0].QMCSettings, {})


if __name__ == '__main__':
    unittest.main()
