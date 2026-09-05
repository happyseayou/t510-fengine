import unittest
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts/stage-35"))

try:
    from scripts.t510_stage35_simple_explorer import weighted_nonoverlap
    from scripts.t510_stage35_simple_math import (
        aggregate_frames,
        overlapping_allan,
        overlapping_allan_visibility,
        white_noise_reference,
    )
except ModuleNotFoundError:  # deployed GB10 control directory is intentionally flat
    from t510_stage35_simple_explorer import weighted_nonoverlap
    from t510_stage35_simple_math import (
        aggregate_frames,
        overlapping_allan,
        overlapping_allan_visibility,
        white_noise_reference,
    )


class Stage35SimpleMathTests(unittest.TestCase):
    def test_time_power_is_mean_of_integer_square_sum(self):
        iq = np.array([[3, 4], [-3, 4], [0, -5], [0, 5]], dtype=np.int16)
        power = iq[:, 0].astype(np.int64) ** 2 + iq[:, 1].astype(np.int64) ** 2
        self.assertEqual(float(np.mean(power)), 25.0)
        self.assertNotEqual(float(np.mean(power)),
                            float(np.mean(iq[:, 0])) ** 2 + float(np.mean(iq[:, 1])) ** 2)

    def test_time_10_to_100_to_1000_ms_weighted_merges_are_identical(self):
        rng = np.random.default_rng(35)
        values = rng.normal(size=(1000, 3))
        weights = rng.integers(2_000_000, 3_200_001, size=1000).astype(np.float64)
        direct_1000, direct_weights = weighted_nonoverlap(values, weights, 100)
        values_100, weights_100 = weighted_nonoverlap(values, weights, 10)
        merged_1000, merged_weights = weighted_nonoverlap(values_100, weights_100, 10)
        np.testing.assert_allclose(merged_1000, direct_1000, rtol=0, atol=2e-15)
        np.testing.assert_array_equal(merged_weights, direct_weights)

    def test_known_real_allan_point_reports_every_intermediate_count(self):
        rows = overlapping_allan(np.array([0.0, 2.0, 4.0, 6.0]), 1.0, [1.0])
        self.assertEqual(rows[0]["N"], 4)
        self.assertEqual(rows[0]["m"], 1)
        self.assertEqual(rows[0]["K"], 3)
        self.assertEqual(rows[0]["sum_squared_difference"], 12.0)
        self.assertEqual(rows[0]["variance"], 2.0)
        self.assertAlmostEqual(rows[0]["square_root"], np.sqrt(2.0))

    def test_constant_series_is_zero(self):
        rows = overlapping_allan(np.ones(64), 0.1, [0.1, 0.2, 0.4])
        self.assertTrue(all(row["variance"] == 0.0 for row in rows))

    def test_complex_visibility_uses_vector_difference_not_wrapped_phase(self):
        phase = np.deg2rad(np.array([179.0, -179.0, 179.0, -179.0]))
        visibility = np.exp(1j * phase)
        rows = overlapping_allan_visibility(
            visibility, np.ones(4), np.ones(4), np.ones(4), 1.0, [1.0],
            relative_percent=False,
        )
        # The complex vectors differ by about two degrees, not 358 degrees.
        self.assertLess(rows[0]["square_root"], 0.05)

    def test_relative_visibility_normalizes_after_window_average(self):
        visibility = np.array([2 + 0j, 4 + 0j, 6 + 0j, 8 + 0j])
        power = np.array([4.0, 16.0, 36.0, 64.0])
        rows = overlapping_allan_visibility(
            visibility, power, np.ones(4), np.ones(4), 1.0, [1.0],
            relative_percent=True,
        )
        expected = overlapping_allan(np.full(4, 100.0), 1.0, [1.0])
        self.assertAlmostEqual(rows[0]["variance"], expected[0]["variance"])

    def test_white_reference_slopes_and_frame_aggregation(self):
        points = [
            {"tau_s": 1.0, "variance": 4.0, "square_root": 2.0},
            {"tau_s": 4.0, "variance": 9.0, "square_root": 3.0},
        ]
        self.assertEqual(white_noise_reference(points, "variance"), [4.0, 1.0])
        self.assertEqual(white_noise_reference(points, "square_root"), [2.0, 1.0])
        averaged = aggregate_frames(np.arange(8.0), 4)
        np.testing.assert_allclose(averaged, [1.5, 5.5])

    def test_measured_white_noise_has_variance_minus_one_and_root_minus_half_slopes(self):
        values = np.random.default_rng(51035).normal(size=1_000_000)
        taus = [1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 64.0]
        rows = overlapping_allan(values, 1.0, taus)
        log_tau = np.log([row["tau_s"] for row in rows])
        variance_slope = np.polyfit(log_tau, np.log([row["variance"] for row in rows]), 1)[0]
        root_slope = np.polyfit(log_tau, np.log([row["square_root"] for row in rows]), 1)[0]
        self.assertAlmostEqual(variance_slope, -1.0, delta=0.03)
        self.assertAlmostEqual(root_slope, -0.5, delta=0.015)


if __name__ == "__main__":
    unittest.main()
