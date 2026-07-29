from __future__ import annotations

import unittest

from scripts.stage32h1_external_rf_axis_gate import (
    bin_for_rf,
    circular_bin_error,
    rf_for_bin,
    signed_bin,
)


class Stage32H1ExternalRfAxisMathTest(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
