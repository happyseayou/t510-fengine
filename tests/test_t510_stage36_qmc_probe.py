import importlib.util
from pathlib import Path
import unittest


spec = importlib.util.spec_from_file_location(
    "qmc_probe", Path(__file__).parents[1] / "scripts/stage-36/t510_stage36_qmc_probe.py")
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class QmcProbeTests(unittest.TestCase):
    def test_gain_is_exactly_representable_and_below_driver_limit(self):
        self.assertEqual(probe.QMC_GAIN * 8192, 16383)
        self.assertLess(probe.QMC_GAIN, 2)

    def test_restore_disabled_power_on_settings_with_supported_event(self):
        original = dict(probe.gain_settings(), EnableGain=0,
                        GainCorrectionFactor=0.0, EventSource=0)
        restored = probe.restoration_settings(original)
        self.assertEqual(restored, dict(original, EventSource=2))
        self.assertEqual(original["EventSource"], 0)

    def test_reject_unsafe_original_event_before_mutation(self):
        with self.assertRaises(RuntimeError):
            probe.restoration_settings(dict(probe.gain_settings(), EventSource=0))

    def test_stopped_guard(self):
        good = dict(core_version=0x10034, streaming=False, dac_enable_mask=0)
        probe.require_stopped(good)
        for patch in (dict(streaming=True), dict(dac_enable_mask=1), dict(core_version=0x10036)):
            with self.assertRaises(RuntimeError):
                probe.require_stopped(dict(good, **patch))

    def test_readback_checks_gain_and_unrelated_datapath_configuration(self):
        import copy
        row = dict(tile=0, block=0, qmc=probe.gain_settings(),
                   mixer={"Freq": -200.0}, dsa={"Attenuation": 0}, decimation=12)
        original = {"blocks": [copy.deepcopy(row)]}
        expected = [dict(tile=0, block=0, qmc=probe.gain_settings())]
        probe.verify_rows({"blocks": [row]}, expected, original)
        for field, value in (("qmc", dict(probe.gain_settings(), EnableGain=0)),
                             ("mixer", {"Freq": -201.0}), ("dsa", {"Attenuation": 1}),
                             ("decimation", 6), ("block", 1)):
            bad = copy.deepcopy(row)
            bad[field] = value
            with self.assertRaises(RuntimeError):
                probe.verify_rows({"blocks": [bad]}, expected, original)

    def test_program_all_adc_blocks_before_tile_update(self):
        events = []

        class Block:
            def __init__(self, tile, block):
                self.tile, self.block = tile, block

            @property
            def QMCSettings(self):
                return None

            @QMCSettings.setter
            def QMCSettings(self, value):
                events.append(("set", self.tile, self.block, value))

            def UpdateEvent(self, event):
                events.append(("update", self.tile, self.block, event))

        from types import SimpleNamespace as NS
        core = NS(rfdc=NS(adc_tiles=[NS(blocks=[Block(t, b) for b in range(2)]) for t in range(4)]))
        rows = [dict(tile=t, block=b, qmc=probe.gain_settings()) for t in range(4) for b in range(2)]
        probe.apply_rows(core, NS(EVENT_QMC=4), rows)
        self.assertEqual(len(events), 16)
        for t in range(4):
            self.assertEqual([e[0] for e in events[t*4:t*4+4]], ["set", "set", "update", "update"])


if __name__ == "__main__":
    unittest.main()
