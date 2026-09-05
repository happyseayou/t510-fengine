import importlib.util
import math
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "t510_stage35_report_v2_core", ROOT / "scripts/stage-35" / "t510_stage35_report_v2_core.py"
)
assert SPEC and SPEC.loader
core = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = core
SPEC.loader.exec_module(core)


class Stage35ReportV2CoreTest(unittest.TestCase):
    def test_registered_frequency_landmarks(self):
        self.assertEqual(core.rf_hz(2048), 860_000_000.0)
        self.assertEqual(core.rf_hz(3328), 960_000_000.0)
        self.assertEqual(core.rf_hz(0), 1_020_000_000.0)
        self.assertEqual(core.rf_hz(2047), 1_179_921_875.0)
        self.assertEqual(core.global_bin_at_rf_hz(960_000_000.0), 3328)

    def test_frequency_order_is_monotonic_and_complete(self):
        bins = core.ascending_global_bins()
        self.assertEqual(len(bins), 4096)
        self.assertEqual(len(set(bins)), 4096)
        self.assertEqual(bins[0], 2048)
        self.assertEqual(bins[-1], 2047)
        values = [core.rf_hz(value) for value in bins]
        self.assertTrue(all(a < b for a, b in zip(values, values[1:])))

    def test_every_figure_has_visible_axis_and_colorbar_contract(self):
        core.validate_figure_contracts()
        for figure in core.FIGURE_CONTRACTS:
            self.assertTrue(figure.x_title)
            self.assertTrue(figure.y_title)
            if figure.requires_colorbar:
                self.assertTrue(figure.colorbar_title)

    def test_white_noise_and_radiometer_bridge(self):
        expected = 1.0 / math.sqrt(core.ENBW_HZ * 15.0)
        self.assertAlmostEqual(core.white_fractional_sigma(15.0), expected, places=15)
        self.assertAlmostEqual(
            core.white_fractional_sigma(60.0),
            core.white_fractional_sigma(15.0) / 2.0,
            places=15,
        )
        self.assertAlmostEqual(core.radiometer_efficiency(4.0), 1.0 / 16.0)
        self.assertAlmostEqual(core.equivalent_white_time(16.0, 4.0), 1.0)
        with self.assertRaises(ValueError):
            core.white_fractional_sigma(0.0)

    def test_preflagged_bins_are_frozen(self):
        self.assertEqual(core.preflagged_bins(), {0, 2048, 3327, 3328, 3329})

    def test_full_and_preflag_excluded_population_statistics(self):
        values = [float(index) for index in range(core.BIN_COUNT)]
        eligible = [index not in core.preflagged_bins() for index in range(core.BIN_COUNT)]
        full = core.population_quantiles(values)
        clean = core.population_quantiles(values, eligible)
        self.assertEqual(full["median"], 2047.5)
        self.assertNotEqual(full, clean)
        expected_clean = [value for value, keep in zip(values, eligible) if keep]
        self.assertEqual(clean["median"], core._linear_quantile(expected_clean, 0.5))

    def test_representative_bin_is_deterministic_and_respects_mask(self):
        rows = [(100.0, 100.0, 100.0) for _ in range(core.BIN_COUNT)]
        rows[11] = (1.0, 1.0, 1.0)
        rows[12] = (1.0, 1.0, 1.0)
        eligible = [False] * core.BIN_COUNT
        eligible[11] = True
        eligible[12] = True
        self.assertEqual(core.representative_bin(rows, eligible), 11)

    def test_units_and_dictionary_are_explicit(self):
        self.assertEqual(core.UNITS["power"], "count²/PFB channel")
        self.assertEqual(core.UNITS["psd"], "count⁴/Hz")
        names = {row[0] for row in core.DATA_DICTIONARY}
        self.assertIn("mean_power_count2", names)
        self.assertIn("sigma_theory_enbw_count2", names)
        self.assertIn("between_scan_fractional_std", names)

    def test_export_dictionary_covers_every_column(self):
        columns = ["scan_label", "global_bin", "integration_std_count2_15s", "temperature_r2", "drop_count"]
        rows = core.dictionary_for_columns(columns)
        self.assertEqual([row[0] for row in rows], columns)
        self.assertTrue(all(row[1] and row[2] and row[3] and row[4] for row in rows))
        self.assertEqual(rows[2][3], "count²")


if __name__ == "__main__":
    unittest.main()
