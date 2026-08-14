from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from python.t510_ams import aggregate_ams_snapshots, read_ams_snapshot


class T510AmsTests(unittest.TestCase):
    def test_iio_temperature_voltage_conversion_and_missing_channel(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            device = Path(directory) / "iio:device0"
            device.mkdir()
            (device / "name").write_text("ams\n")
            (device / "in_temp0_label").write_text("ps_temp\n")
            (device / "in_temp0_raw").write_text("1000\n")
            (device / "in_temp0_offset").write_text("-100\n")
            (device / "in_temp0_scale").write_text("50\n")
            (device / "in_voltage0_label").write_text("vccint\n")
            (device / "in_voltage0_raw").write_text("500\n")
            (device / "in_voltage0_scale").write_text("2\n")
            # A partially exposed rail is reported as an error, not fatal.
            (device / "in_voltage1_raw").write_text("1\n")

            result = read_ams_snapshot(Path(directory))

        self.assertTrue(result["supported"])
        self.assertEqual(result["temperatures_c"]["ps_temp"], 45.0)
        self.assertEqual(result["voltages_v"]["vccint"], 1.0)
        self.assertTrue(any("in_voltage1" in error for error in result["errors"]))

    def test_five_hz_samples_aggregate_min_mean_max(self) -> None:
        result = aggregate_ams_snapshots(
            [
                {
                    "supported": True,
                    "temperatures_c": {"pl_temp": value},
                    "voltages_v": {"vccint": value / 100.0},
                    "errors": [],
                }
                for value in (40.0, 41.0, 42.0, 43.0, 44.0)
            ]
        )
        self.assertEqual(result["sample_count"], 5)
        self.assertEqual(result["sample_rate_hz"], 5.0)
        self.assertEqual(
            result["temperatures_c"]["pl_temp"],
            {"min": 40.0, "mean": 42.0, "max": 44.0},
        )
        self.assertAlmostEqual(result["voltages_v"]["vccint"]["mean"], 0.42)


if __name__ == "__main__":
    unittest.main()
