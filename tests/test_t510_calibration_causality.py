from __future__ import annotations

import random
import unittest

from scripts import t510_calibration_causality as causality
from scripts import t510_calibration_causality_low_rf as low_rf


class Stage34b2CausalityTests(unittest.TestCase):
    def test_balanced_order_has_eighteen_fresh_runs(self) -> None:
        runs = causality.campaign_runs()
        self.assertEqual(len(runs), 18)
        for rate in causality.RATES_MSPS:
            selected = [row for row in runs if row["sample_rate_msps"] == rate]
            self.assertEqual(
                [row["condition"] for row in selected],
                [value for order in causality.BALANCED_ORDERS for value in order],
            )
            for condition in causality.CONDITIONS:
                self.assertEqual(
                    sum(row["condition"] == condition for row in selected),
                    3,
                )

    def test_pg269_engineering_level_gate(self) -> None:
        base = {"clipped": False, "rms_dbfs": -35.0, "peak_dbfs": -20.0}
        self.assertTrue(causality.level_pass(base))
        self.assertFalse(causality.level_pass({**base, "rms_dbfs": -36.1}))
        self.assertFalse(causality.level_pass({**base, "peak_dbfs": -0.5}))
        self.assertFalse(causality.level_pass({**base, "clipped": True}))

    def test_low_rf_extension_has_two_bands_and_thirty_six_balanced_runs(self) -> None:
        runs = low_rf.low_rf_runs()
        self.assertEqual(len(runs), 36)
        self.assertIn(100.0, low_rf.LOW_RF_BANDS["low"]["rf_frequencies_mhz"])
        self.assertEqual(
            (
                min(
                    frequency
                    for band in low_rf.LOW_RF_BANDS.values()
                    for frequency in band["rf_frequencies_mhz"]
                ),
                max(
                    frequency
                    for band in low_rf.LOW_RF_BANDS.values()
                    for frequency in band["rf_frequencies_mhz"]
                ),
            ),
            (50.0, 330.0),
        )
        for band in low_rf.LOW_RF_BANDS:
            for rate in causality.RATES_MSPS:
                selected = [
                    row
                    for row in runs
                    if row["band"] == band and row["sample_rate_msps"] == rate
                ]
                self.assertEqual(len(selected), 9)
                for condition in causality.CONDITIONS:
                    self.assertEqual(
                        sum(row["condition"] == condition for row in selected),
                        3,
                    )

    def test_low_rf_targets_are_exact_bins_with_edge_guard(self) -> None:
        plan = low_rf.validate_frequency_plan()
        self.assertEqual(len(plan), 4)
        for row in plan:
            self.assertGreaterEqual(row["edge_guard_mhz"], 15.0)
            self.assertTrue(all(-2048 < value < 2048 for value in row["signed_bins"]))

    def test_resident_timestamp_allows_small_cross_host_clock_skew(self) -> None:
        self.assertEqual(causality.resident_observation_age_ms(10_004, 10_000), -4)
        self.assertEqual(causality.resident_observation_age_ms(9_000, 10_000), 1000)
        with self.assertRaisesRegex(RuntimeError, "stale by -1001 ms"):
            causality.resident_observation_age_ms(11_001, 10_000)
        with self.assertRaisesRegex(RuntimeError, "stale by 2501 ms"):
            causality.resident_observation_age_ms(7_499, 10_000)

    def test_monitor_analysis_recovers_white_noise_slope_and_low_lag(self) -> None:
        generator = random.Random(0x34B2)
        targets = [
            {"target_index": index, "actual_rf_mhz": rf}
            for index, rf in enumerate(causality.SAFE_RF_MHZ)
        ]
        rows = []
        for second in range(600):
            for target in targets:
                for lane in range(8):
                    power = max(1.0, 10_000.0 + generator.gauss(0.0, 1000.0))
                    rows.append(
                        {
                            "second": second,
                            "target_index": target["target_index"],
                            "lane": lane,
                            "sample_count": 1,
                            "sum_power": power,
                        }
                    )
        result = causality.analyze_monitor(
            {"targets": targets, "power_seconds": rows},
            seed=34,
        )
        self.assertEqual(len(result["combinations"]), 48)
        self.assertGreaterEqual(result["slope_pass_fraction"], 0.75)
        self.assertLessEqual(result["median_abs_lag1"], 0.10)


if __name__ == "__main__":
    unittest.main()
