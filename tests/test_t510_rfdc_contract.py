from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock

from python.t510_fengine import (
    T510FEngine,
    _calibration_circular_delta,
    _nearest_rank_percentile,
)


class _Block:
    def __init__(self, *, factor_name: str) -> None:
        self.MixerSettings = {"Freq": 0.0, "EventSource": 1}
        self.NyquistZone = 1
        setattr(self, factor_name, 12)
        self.update_count = 0
        self.reset_count = 0
        self.active = True

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
        self._instance = object()


class _CalibrationFfi:
    NULL = None

    @staticmethod
    def typeof(_name):
        return object()

    @staticmethod
    def new(name):
        if name == "XRFdc_Cal_Freeze_Settings*":
            return SimpleNamespace(CalFrozen=0, DisableFreezePin=0, FreezeCalibration=0)
        if name == "XRFdc_Calibration_Coefficients*":
            return SimpleNamespace(**{f"Coeff{index}": 0 for index in range(8)})
        raise AssertionError(name)


class _CalibrationLib:
    def __init__(self) -> None:
        self.frozen = {(tile, block): False for tile in range(4) for block in range(2)}
        self.fail_set = None
        self.fail_ocb1_set = None
        self.override = {(tile, block): False for tile in range(4) for block in range(2)}
        self.ocb1 = {
            (tile, block): [tile * 1000 + block * 100 + index for index in range(8)]
            for tile in range(4)
            for block in range(2)
        }

    def XRFdc_GetCalFreeze(self, _instance, tile, block, settings):
        settings.CalFrozen = int(self.frozen[(tile, block)])
        settings.DisableFreezePin = 1
        settings.FreezeCalibration = int(self.frozen[(tile, block)])
        return 0

    def XRFdc_SetCalFreeze(self, _instance, tile, block, settings):
        if self.fail_set == (tile, block) and int(settings.FreezeCalibration):
            return 17
        self.frozen[(tile, block)] = bool(int(settings.FreezeCalibration))
        return 0

    def XRFdc_GetCalCoefficients(self, _instance, tile, block, calibration_block, coeff):
        for index in range(8):
            setattr(
                coeff,
                f"Coeff{index}",
                (
                    self.ocb1[(tile, block)][index]
                    if calibration_block == 0
                    else tile * 1000 + block * 100 + calibration_block * 10 + index
                ),
            )
        return 0

    def XRFdc_SetCalCoefficients(self, _instance, tile, block, calibration_block, coeff):
        if self.fail_ocb1_set == (tile, block):
            return 23
        assert calibration_block == 0
        self.ocb1[(tile, block)] = [
            int(getattr(coeff, f"Coeff{index}")) & 0xFFFF_FFFF
            for index in range(8)
        ]
        self.override[(tile, block)] = True
        return 0

    def XRFdc_DisableCoefficientsOverride(
        self, _instance, tile, block, calibration_block
    ):
        assert calibration_block == 0
        self.override[(tile, block)] = False
        return 0


def _core() -> T510FEngine:
    core = T510FEngine.__new__(T510FEngine)
    core.rfdc = _Rfdc()
    core.rfdc_bind_error = None
    return core


class T510RfdcContractTests(unittest.TestCase):
    def test_calibration_delta_uses_fixed_width_ring_and_tail_percentile(self) -> None:
        self.assertEqual(_calibration_circular_delta(255, -256, 9), 1)
        self.assertEqual(_calibration_circular_delta(2047, -2048, 12), 1)
        self.assertEqual(_calibration_circular_delta(-10, -4, 9), 6)
        self.assertEqual(_nearest_rank_percentile([0] * 95 + [4] * 4 + [32], 0.50), 0)
        self.assertEqual(_nearest_rank_percentile([0] * 95 + [4] * 4 + [32], 0.95), 0)
        self.assertEqual(_nearest_rank_percentile([0] * 94 + [4] * 5 + [32], 0.95), 4)

    def test_convergence_compares_signed_low_and_high_half_coefficients(self) -> None:
        core = _core()

        def snapshot(gcb_packed: int, tscb_packed: int):
            return {
                "channels": [
                    {
                        "coefficients": {
                            "gcb": [gcb_packed] * 8,
                            "tscb": [tscb_packed] * 8,
                        }
                    }
                    for _ in range(8)
                ],
                "coefficient_sha256": {"gcb": "g", "tscb": "t"},
            }

        # High-half -1 -> 0 is one signed LSB, not a false 65536-LSB jump.
        values = [
            snapshot(0x0FFF0000, 0x01FF0000),
            snapshot(0x00000000, 0x00000000),
            snapshot(0x00000000, 0x00000000),
        ]
        with mock.patch.object(
            core,
            "_adc_calibration_blocks",
            return_value=[(tile, block) for tile in range(4) for block in range(2)],
        ), mock.patch.object(
            core,
            "read_adc_calibration_status",
            side_effect=values,
        ):
            result = core.wait_adc_calibration_convergence(
                poll_hz=1000.0,
                stable_seconds=0.002,
                timeout_seconds=0.1,
                max_delta_lsb=1,
            )
        self.assertTrue(result["converged"])
        self.assertEqual(result["trace"][1]["max_delta_lsb"], 1)

    def test_calibration_read_freeze_unfreeze_and_partial_failure_rollback(self) -> None:
        core = _core()
        ffi = _CalibrationFfi()
        lib = _CalibrationLib()
        contract = {
            "blocks": [
                {"kind": "adc", "tile": tile, "block": block}
                for tile in range(4)
                for block in range(2)
            ]
        }
        with mock.patch.object(core, "_ensure_rfdc_calibration_cffi", return_value=(ffi, lib)), mock.patch.object(
            core, "read_rfdc_contract", return_value=contract
        ):
            initial = core.read_adc_calibration_status(require=True)
            self.assertTrue(initial["supported"])
            self.assertEqual(initial["frozen_adc_mask"], 0)
            self.assertEqual(len(initial["channels"]), 8)
            self.assertEqual(len(initial["coefficient_sha256"]["all"]), 64)
            frozen = core.set_adc_calibration_freeze(True)
            self.assertEqual(frozen["frozen_adc_mask"], 0xFF)
            self.assertEqual(frozen["software_owned_mask"], 0xFF)
            unfrozen = core.set_adc_calibration_freeze(False)
            self.assertEqual(unfrozen["frozen_adc_mask"], 0)
            lib.fail_set = (1, 1)
            with self.assertRaisesRegex(RuntimeError, "ATOMIC_UPDATE_FAILED"):
                core.set_adc_calibration_freeze(True)
            self.assertFalse(any(lib.frozen.values()))

    def test_ocb1_snapshot_override_readback_dft_release_and_rollback(self) -> None:
        core = _core()
        ffi = _CalibrationFfi()
        lib = _CalibrationLib()
        contract = {
            "blocks": [
                {"kind": "adc", "tile": tile, "block": block}
                for tile in range(4)
                for block in range(2)
            ]
        }
        with mock.patch.object(
            core, "_ensure_rfdc_calibration_cffi", return_value=(ffi, lib)
        ), mock.patch.object(core, "read_rfdc_contract", return_value=contract):
            result = core.set_adc_ocb1_snapshot_override()
            self.assertEqual(result["override_adc_mask"], 0xFF)
            self.assertTrue(all(lib.override.values()))
            self.assertEqual(len(result["channels"]), 8)
            self.assertEqual(len(result["channels"][0]["signed16"]), 8)
            self.assertEqual([row["k"] for row in result["channels"][0]["dft"]], [1, 2, 3, 4])
            released = core.release_adc_ocb1_override()
            self.assertEqual(released["override_adc_mask"], 0)
            self.assertFalse(any(lib.override.values()))

            lib.fail_ocb1_set = (1, 1)
            with self.assertRaisesRegex(RuntimeError, "ATOMIC_OVERRIDE_FAILED"):
                core.set_adc_ocb1_snapshot_override()
            self.assertFalse(any(lib.override.values()))

    def test_constants_preserve_320m_complex_and_80m_axis_rates(self) -> None:
        self.assertEqual(T510FEngine.RFDC_ADC_ANALOG_SAMPLE_RATE_HZ, 3_840_000_000)
        self.assertEqual(T510FEngine.RFDC_DAC_ANALOG_SAMPLE_RATE_HZ, 3_840_000_000)
        self.assertEqual(T510FEngine.RFDC_ANALOG_SAMPLE_RATE_HZ, 3_840_000_000)
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

    def test_sysref_mixer_status_retains_immediate_event_field(self) -> None:
        core = _core()
        result = core._configure_rfdc_mixer_blocks_sysref(
            adc_nco_hz=-200_000_000.0,
            dac_nco_hz=200_000_000.0,
            require=True,
        )
        self.assertTrue(result["configured"])
        self.assertEqual(result["event_immediate"], 0)
        self.assertEqual(result["event_source_name"], "sysref")
        self.assertEqual((result["adc_blocks"], result["dac_blocks"]), (8, 8))

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

    def test_bd_source_freezes_current_rfdc_properties(self) -> None:
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
        self.assertIn(
            "_assert_bd_property $rfdc CONFIG.ADC_CalOpt_Mode${slice} 1",
            source,
        )
        for slice_name in ("00", "02", "10", "12", "20", "22", "30", "32"):
            self.assertIn(f"CONFIG.ADC_CalOpt_Mode{slice_name} {{1}}", source)
            self.assertIn(f"CONFIG.ADC_Decimation_Mode{slice_name} {{12}}", source)
            self.assertIn(f"CONFIG.ADC_Dither{slice_name} {{true}}", source)
            self.assertIn(f"CONFIG.ADC_Data_Width{slice_name} {{4}}", source)
            self.assertIn(f"CONFIG.ADC_Mixer_Mode{slice_name} {{0}}", source)
        for slice_name in ("00", "02", "10", "12", "20", "22", "30", "32"):
            self.assertIn(f"CONFIG.DAC_Interpolation_Mode{slice_name} {{12}}", source)
            self.assertIn(f"CONFIG.DAC_Data_Width{slice_name} {{8}}", source)
            self.assertIn(f"CONFIG.DAC_Mixer_Mode{slice_name} {{0}}", source)

    def test_current_project_build_has_no_stage_compile_switches(self) -> None:
        build = Path("scripts/t510_prepare_current_project.tcl").read_text(encoding="utf-8")
        setup = Path("scripts/setup_project.tcl").read_text(encoding="utf-8")
        self.assertIn("current T510 release must update demo-ant", build)
        self.assertNotIn("create_project", build)
        self.assertNotIn("wait_on_run", build)
        self.assertNotIn("launch_runs", build)
        self.assertIn("set_property verilog_define {} [get_filesets sources_1]", setup)
        self.assertIn("set_property verilog_define {T510_SIM_FFT_MODEL}", setup)
        self.assertNotIn("T510_" + "STAGE", build + setup)


if __name__ == "__main__":
    unittest.main()
