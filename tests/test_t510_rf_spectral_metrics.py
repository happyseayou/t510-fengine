from __future__ import annotations

import unittest

from python.t510_fengine import T510FEngine
from scripts.t510_pfb8_loopback_gate import dac_request, pfb_response_db
from scripts.t510_rf_spectral_metrics import (
    bin_for_rf,
    circular_bin_error,
    cross_lane_phase_statistics,
    rf_for_bin,
    signed_bin,
    strongest_spur,
)


class RfSpectralMetricsTest(unittest.TestCase):
    def test_signed_bins(self) -> None:
        self.assertEqual(signed_bin(1408, 4096), 1408)
        self.assertEqual(signed_bin(2688, 4096), -1408)

    def test_320m_absolute_mapping(self) -> None:
        self.assertEqual(rf_for_bin(170.0, 320_000_000, 4096, 1408), 280.0)
        self.assertEqual(rf_for_bin(170.0, 320_000_000, 4096, 2688), 60.0)
        self.assertEqual(bin_for_rf(170.0, 320_000_000, 4096, 280.0), 1408)
        self.assertEqual(bin_for_rf(170.0, 320_000_000, 4096, 60.0), 2688)

    def test_160m_absolute_mapping(self) -> None:
        self.assertEqual(rf_for_bin(170.0, 160_000_000, 4096, 1280), 220.0)
        self.assertEqual(rf_for_bin(170.0, 160_000_000, 4096, 2816), 120.0)

    def test_circular_error(self) -> None:
        self.assertEqual(circular_bin_error(0, 4095, 4096), 1)
        self.assertEqual(circular_bin_error(4095, 0, 4096), 1)

    def test_strongest_spur_excludes_carrier_neighborhood(self) -> None:
        power = [-100.0] * 16
        power[15] = 0.0
        power[14] = -10.0
        power[0] = -20.0
        power[5] = -52.0
        self.assertEqual(strongest_spur(power, 15, 1), (5, -52.0))

    def test_strongest_spur_requires_remaining_bins(self) -> None:
        with self.assertRaises(ValueError):
            strongest_spur([-1.0, 0.0, -2.0], 1, 1)

    def test_cross_lane_phase_statistics_uses_circular_mean(self) -> None:
        frames = [
            {"phases": [[0.0], [0.5]]},
            {"phases": [[0.1], [0.6]]},
            {"phases": [[-0.1], [0.4]]},
        ]
        phase_deg, coherence = cross_lane_phase_statistics(frames, 0, 1, 0)
        self.assertAlmostEqual(phase_deg, 28.6478898, places=6)
        self.assertAlmostEqual(coherence, 1.0, places=6)

    def test_pfb8_gate_uses_frozen_fractional_bin_response(self) -> None:
        coefficients = T510FEngine.generate_default_pfb_coefficients()
        self.assertAlmostEqual(pfb_response_db(coefficients, 0.5), -6.0198581776, places=3)
        self.assertLessEqual(pfb_response_db(coefficients, 0.75), -49.0)
        self.assertLessEqual(pfb_response_db(coefficients, 1.125), -57.5)

    def test_pfb8_gate_programs_and_mutes_all_eight_dacs(self) -> None:
        active = dac_request(
            board_id=7,
            center_mhz=200.0,
            rf_mhz=220.0,
            amplitude_percent=25.0,
        )
        muted = dac_request(
            board_id=7,
            center_mhz=200.0,
            rf_mhz=200.0,
            amplitude_percent=0.0,
        )
        self.assertEqual([row["channel"] for row in active["channels"]], list(range(8)))
        self.assertTrue(all(row["enabled"] for row in active["channels"]))
        self.assertTrue(all(not row["enabled"] for row in muted["channels"]))


if __name__ == "__main__":
    unittest.main()
