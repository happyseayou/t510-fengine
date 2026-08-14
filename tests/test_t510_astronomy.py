from __future__ import annotations

import math
import random
import unittest

from python import t510_astronomy as astronomy


class AstronomyPerformanceTests(unittest.TestCase):
    def test_astronomy_reference_bin_mapping_is_exact(self) -> None:
        references = (
            (408.0, 468.0),
            (1420.4057518, 1480.4057518),
            (1665.40184, 1725.40184),
        )
        for rf_mhz, center_mhz in references:
            self.assertEqual(astronomy.rf_to_signed_bin(rf_mhz, center_mhz, 160), -1536)
            self.assertEqual(astronomy.rf_to_signed_bin(rf_mhz, center_mhz, 320), -768)

    def test_integration_curve_follows_radiometer_law_for_white_noise(self) -> None:
        generator = random.Random(0x34A)
        powers = [100.0 + generator.gauss(0.0, 10.0) for _ in range(8192)]
        result = astronomy.integration_statistics(powers)
        self.assertGreater(result["slope"], -0.57)
        self.assertLess(result["slope"], -0.43)
        self.assertEqual([row["tau_seconds"] for row in result["curve"]], [1, 2, 4, 8, 16, 32, 64, 128])

    def test_coherence_preserves_complex_phase(self) -> None:
        phase = math.radians(30.0)
        result = astronomy.coherence_from_accumulators(
            [
                {
                    "sample_count": 100,
                    "sum_cross_re": 100.0 * math.cos(phase),
                    "sum_cross_im": 100.0 * math.sin(phase),
                    "sum_power_a": 100.0,
                    "sum_power_b": 100.0,
                }
            ]
        )
        self.assertAlmostEqual(result["coherence"], 1.0)
        self.assertAlmostEqual(result["phase_deg"], 30.0)

    def test_source_exemptions_do_not_leak_into_muted_adc_context(self) -> None:
        muted = astronomy.classify_spur(
            rf_mhz=700.0,
            prominence_db=15.0,
            reproduced=True,
            bin_width_mhz=160.0 / 4096,
            context="muted_adc",
            dac_signature_match=True,
        )
        self.assertEqual(muted["classification"], "ASTRONOMY_REVIEW_REQUIRED")
        dac = astronomy.classify_spur(
            rf_mhz=700.0,
            prominence_db=15.0,
            reproduced=True,
            bin_width_mhz=160.0 / 4096,
            context="dac_loopback",
            dac_signature_match=True,
        )
        self.assertEqual(dac["classification"], "SOURCE_LIMITED_DAC")

    def test_fixed_spurs_masks_and_watchlist_are_distinct(self) -> None:
        fixed = astronomy.classify_spur(
            rf_mhz=960.0,
            prominence_db=20.0,
            reproduced=True,
            bin_width_mhz=160.0 / 4096,
            context="muted_adc",
        )
        watch = astronomy.classify_spur(
            rf_mhz=1120.0,
            prominence_db=20.0,
            reproduced=True,
            bin_width_mhz=160.0 / 4096,
            context="muted_adc",
        )
        self.assertTrue(fixed["exclude_science_summary"])
        self.assertEqual(watch["classification"], "ADC_WATCHLIST")
        self.assertEqual(len(astronomy.science_bad_bins()[0]["masked_global_bins"]), 9)

    def test_stitch_uses_linear_power_median(self) -> None:
        empty = [[-300.0] * astronomy.NCHAN for _ in range(astronomy.NINPUT)]
        first = [lane[:] for lane in empty]
        second = [lane[:] for lane in empty]
        # RF=80 MHz is bin 2048 around center=0 and DC around center=80.
        # Use a nearby non-DC point that both windows retain.
        rf_mhz = 60.0
        first_index = round((rf_mhz - 0.0) / (160.0 / astronomy.NCHAN)) % astronomy.NCHAN
        second_index = round((rf_mhz - 80.0) / (160.0 / astronomy.NCHAN)) % astronomy.NCHAN
        for lane in range(astronomy.NINPUT):
            first[lane][first_index] = -80.0
            second[lane][second_index] = -70.0
        stitched = astronomy.stitch_overlapping_windows(
            [
                {"center_mhz": 0.0, "power_dbfs": first},
                {"center_mhz": 80.0, "power_dbfs": second},
            ],
            160,
        )
        index = round(rf_mhz / (160.0 / astronomy.NCHAN))
        expected = 10.0 * math.log10((10.0**-8 + 10.0**-7) / 2.0)
        self.assertAlmostEqual(stitched[0][index], expected)


if __name__ == "__main__":
    unittest.main()
