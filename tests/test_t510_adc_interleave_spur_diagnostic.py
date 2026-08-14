import unittest

from scripts import t510_adc_interleave_spur_diagnostic as diagnostic


class Stage34eDiagnosticTests(unittest.TestCase):
    def test_six_windows_cover_three_spurs_and_both_rates(self) -> None:
        rows = diagnostic.diagnostic_windows()
        self.assertEqual(len(rows), 6)
        self.assertEqual(
            {(row["spur_mhz"], row["sample_rate_msps"]) for row in rows},
            {(spur, rate) for spur in diagnostic.FIXED_SPURS_MHZ for rate in (160, 320)},
        )
        self.assertTrue(all(row["spur_mhz"] - row["center_mhz"] == 60.0 for row in rows))

    def test_comparison_order_is_raw_static_dynamic_per_window(self) -> None:
        rows = diagnostic.comparison_plan()
        self.assertEqual(len(rows), 18)
        for offset in range(0, len(rows), 3):
            self.assertEqual(
                [row["condition"] for row in rows[offset : offset + 3]],
                ["raw", "static_c0", "dynamic"],
            )

    def test_local_targets_are_exact_and_keep_spur_first(self) -> None:
        for row in diagnostic.diagnostic_windows():
            targets = diagnostic.local_rf_targets(
                float(row["center_mhz"]), int(row["sample_rate_msps"])
            )
            self.assertEqual(len(targets), 9)
            self.assertAlmostEqual(targets[0], row["spur_mhz"])
            spacing = row["sample_rate_msps"] / 4096.0
            self.assertTrue(
                all(abs((target - row["center_mhz"]) / spacing - round((target - row["center_mhz"]) / spacing)) < 1e-9 for target in targets)
            )

    def test_prominence_uses_linear_power_median(self) -> None:
        raw = {
            "targets": [
                {"target_index": index, "actual_rf_mhz": 960.0 + index}
                for index in range(9)
            ],
            "power_seconds": [],
        }
        for lane in range(8):
            for target in range(9):
                power = 99.0 if target == 0 else 25.0
                raw["power_seconds"].append(
                    {
                        "lane": lane,
                        "target_index": target,
                        "sample_count": 1,
                        "sum_power": power,
                    }
                )
        result = diagnostic.summarize_spur_monitor(raw)
        self.assertTrue(result["all_lanes_at_or_below_noise_plus_6db"])
        self.assertAlmostEqual(result["worst_prominence_db"], 10.0 * __import__("math").log10(99.0 / 25.0))

    def test_throughput_matrix_keeps_only_five_legal_modes(self) -> None:
        rows = diagnostic.throughput_plan()
        legal = {(160, "time_only"), (160, "spec_only"), (160, "time_spec"), (320, "time_only"), (320, "spec_only")}
        sixty = {(row["rate"], row["mode"]) for row in rows if row["duration"] == 60}
        self.assertEqual(sixty, legal)
        self.assertNotIn((320, "time_spec"), {(row["rate"], row["mode"]) for row in rows})
        self.assertEqual(sum(row["duration"] == 3600 for row in rows), 1)


if __name__ == "__main__":
    unittest.main()
