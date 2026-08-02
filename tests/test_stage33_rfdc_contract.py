from __future__ import annotations

from pathlib import Path
import unittest

from python.t510_fengine import T510FEngine


class _Block:
    def __init__(self, *, factor_name: str) -> None:
        self.MixerSettings = {"Freq": 0.0, "EventSource": 1}
        self.NyquistZone = 1
        setattr(self, factor_name, 12)
        self.update_count = 0
        self.reset_count = 0

    def UpdateEvent(self, _event: int) -> None:
        self.update_count += 1

    def ResetNCOPhase(self) -> None:
        self.reset_count += 1


class _Tile:
    def __init__(self, *, factor_name: str) -> None:
        self.PLLLockStatus = 1
        self.PLLConfig = {"SampleRate": 3.84}
        self.blocks = [_Block(factor_name=factor_name), _Block(factor_name=factor_name)]


class _Rfdc:
    def __init__(self) -> None:
        self.adc_tiles = [_Tile(factor_name="DecimationFactor") for _ in range(4)]
        self.dac_tiles = [_Tile(factor_name="InterpolationFactor") for _ in range(4)]


def _core() -> T510FEngine:
    core = T510FEngine.__new__(T510FEngine)
    core.rfdc = _Rfdc()
    core.rfdc_bind_error = None
    return core


class Stage33RfdcContractTests(unittest.TestCase):
    def test_constants_preserve_320m_complex_and_80m_axis_rates(self) -> None:
        self.assertEqual(T510FEngine.RFDC_ADC_ANALOG_SAMPLE_RATE_HZ, 3_840_000_000)
        self.assertEqual(T510FEngine.RFDC_DAC_ANALOG_SAMPLE_RATE_HZ, 3_840_000_000)
        self.assertEqual(T510FEngine.RFDC_COMPLEX_SAMPLE_RATE_HZ, 320_000_000)
        self.assertEqual((T510FEngine.RFDC_DECIMATION, T510FEngine.RFDC_INTERPOLATION), (12, 12))
        self.assertEqual((T510FEngine.ADC_AXIS_RATE_HZ, T510FEngine.DAC_AXIS_RATE_HZ), (80_000_000, 80_000_000))

    def test_live_contract_reads_all_tiles_and_blocks(self) -> None:
        core = _core()
        result = core.read_rfdc_contract(require=True)
        self.assertTrue(result["ok"])
        self.assertEqual(result["active_block_count"], {"adc": 8, "dac": 8})
        self.assertTrue(
            all("mixer_frequency_mhz" in row for row in result["blocks"])
        )
        core.rfdc.adc_tiles[2].blocks[1].DecimationFactor = 5
        with self.assertRaisesRegex(RuntimeError, "factor expected 12"):
            core.read_rfdc_contract(require=True)

    def test_live_contract_rejects_missing_tile_or_sample_rate(self) -> None:
        core = _core()
        core.rfdc.dac_tiles.pop()
        with self.assertRaisesRegex(RuntimeError, "expected 4 DAC tiles"):
            core.read_rfdc_contract(require=True)
        core = _core()
        core.rfdc.adc_tiles[0].PLLConfig = {}
        with self.assertRaisesRegex(RuntimeError, "no SampleRate readback"):
            core.read_rfdc_contract(require=True)
        core = _core()
        core.rfdc.adc_tiles[0].PLLConfig = {"SampleRate": 3840.0}
        self.assertTrue(core.read_rfdc_contract(require=True)["ok"])

    def test_nco_write_sets_zone_one_and_verifies_frequency(self) -> None:
        core = _core()
        for tile in core.rfdc.adc_tiles + core.rfdc.dac_tiles:
            for block in tile.blocks:
                block.NyquistZone = 2
        result = core._configure_rfdc_nco_pair(
            adc_nco_hz=-1_760_000_000.0,
            dac_nco_hz=1_760_000_000.0,
            bandwidth_hz=320_000_000.0,
            require=True,
        )
        self.assertTrue(result["configured"])
        self.assertEqual((result["adc_blocks"], result["dac_blocks"]), (8, 8))
        self.assertTrue(all(row["nyquist_zone"] == 1 for row in result["results"]))

    def test_first_nyquist_complete_band_boundaries(self) -> None:
        self.assertEqual(T510FEngine.science_center_bounds_hz(160), (80e6, 1840e6))
        self.assertEqual(T510FEngine.science_center_bounds_hz(320), (160e6, 1760e6))
        T510FEngine.validate_observation_frequency_plan(
            center_hz=1760e6,
            bandwidth_hz=320e6,
            signal_hz=1919.999e6,
        )
        with self.assertRaisesRegex(ValueError, "upper bound exclusive"):
            T510FEngine.validate_observation_frequency_plan(
                center_hz=1760e6,
                bandwidth_hz=320e6,
                signal_hz=1920e6,
            )

    def test_bd_source_freezes_stage33_rfdc_properties(self) -> None:
        source = Path("bd/t510_rfdc_bd.tcl").read_text(encoding="utf-8")
        for tile in range(4):
            self.assertIn(f"CONFIG.ADC{tile}_Sampling_Rate {{3.8400}}", source)
            self.assertIn(f"CONFIG.DAC{tile}_Sampling_Rate {{3.8400}}", source)
        adc_r2c_paths = (
            "00", "01", "02", "03", "10", "11", "12", "13",
            "20", "21", "22", "23", "30", "31", "32", "33",
        )
        self.assertIn(f"foreach slice {{{' '.join(adc_r2c_paths)}}}", source)
        self.assertIn(
            "_assert_bd_property $rfdc CONFIG.ADC_Decimation_Mode${slice} 12",
            source,
        )
        self.assertIn(
            "_assert_bd_property $rfdc CONFIG.ADC_Dither${slice} true",
            source,
        )
        for slice_name in ("00", "02", "10", "12", "20", "22", "30", "32"):
            self.assertIn(f"CONFIG.ADC_Decimation_Mode{slice_name} {{12}}", source)
            self.assertIn(f"CONFIG.ADC_Dither{slice_name} {{true}}", source)
            self.assertIn(f"CONFIG.ADC_Data_Width{slice_name} {{4}}", source)
            self.assertIn(f"CONFIG.ADC_Mixer_Mode{slice_name} {{0}}", source)
        for slice_name in ("00", "02", "10", "12", "20", "22", "30", "32"):
            self.assertIn(f"CONFIG.DAC_Interpolation_Mode{slice_name} {{12}}", source)
            self.assertIn(f"CONFIG.DAC_Data_Width{slice_name} {{8}}", source)
            self.assertIn(f"CONFIG.DAC_Mixer_Mode{slice_name} {{0}}", source)

    def test_current_project_build_has_no_stage_compile_switches(self) -> None:
        build = Path("scripts/build_stage33.tcl").read_text(encoding="utf-8")
        setup = Path("scripts/setup_project.tcl").read_text(encoding="utf-8")
        self.assertIn("Stage 33 must update demo-ant", build)
        self.assertNotIn("create_project", build)
        self.assertNotIn("wait_on_run", build)
        self.assertNotIn("launch_runs", build)
        self.assertIn("set_property verilog_define {} [get_filesets sources_1]", setup)
        self.assertIn("set_property verilog_define {T510_SIM_FFT_MODEL}", setup)
        self.assertNotIn("T510_" + "STAGE", build + setup)


if __name__ == "__main__":
    unittest.main()
