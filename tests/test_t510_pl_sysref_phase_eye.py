from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).parents[1] / "scripts" / "t510_pl_sysref_phase_eye.py"
SPEC = importlib.util.spec_from_file_location("t510_pl_sysref_phase_eye", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
phase_eye = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(phase_eye)


class PhaseEyeTests(unittest.TestCase):
    def test_grid_covers_one_period(self) -> None:
        grid = phase_eye.phase_grid()
        self.assertEqual(len(grid), 32)
        self.assertEqual(grid[0], 0.0)
        gaps = [
            (grid[(index + 1) % len(grid)] - value) % phase_eye.PHASE_PERIOD_PS
            for index, value in enumerate(grid)
        ]
        self.assertLessEqual(max(gaps), 250.0)

    def test_cyclic_window_wraps(self) -> None:
        start, length = phase_eye.longest_cyclic_pass_window(
            [True, True, False, False, True, True, True]
        )
        self.assertEqual((start, length), (4, 5))

    def test_selects_eye_center_and_requires_margin(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory) / "profile.tcs"
            profile.write_text("TICS Pro export\n", encoding="utf-8")
            sha = hashlib.sha256(profile.read_bytes()).hexdigest()
            points = []
            for delay in phase_eye.phase_grid():
                passed = 500 <= delay <= 3000
                attempts = []
                for kind in ("rfdc_reset", "rfdc_reset", "rfdc_reset", "overlay_reload"):
                    attempts.append(
                        {
                            "kind": kind,
                            "mts_passed": passed,
                            "pll1_locked": True,
                            "pll2_locked": True,
                            "adc_latency": [416] * 4,
                            "dac_latency": [112] * 4,
                            "capture_interval_seconds": 0.001,
                            "sysref_capture_delta": {
                                "pl_160mhz": 10_000,
                                "adc_80mhz": 10_000,
                                "dac_80mhz": 10_000,
                            },
                        }
                    )
                points.append(
                    {
                        "delay_ps": delay,
                        "tics_profile_path": str(profile),
                        "tics_profile_sha256": sha,
                        "tics_pro_exported": True,
                        "attempts": attempts,
                    }
                )
            result = phase_eye.select_eye(
                points,
                frequency_hz=10_000_000,
                setup_ns=0.7,
                hold_ns=0.6,
            )
            self.assertTrue(result["qualified"])
            self.assertGreaterEqual(result["longest_eye_width_ps"], 2300)
            self.assertGreaterEqual(result["selected_delay_ps"], 1600)
            self.assertLessEqual(result["selected_delay_ps"], 1900)

    def test_rejects_incomplete_grid(self) -> None:
        with self.assertRaisesRegex(ValueError, "every native grid point"):
            phase_eye.select_eye([], frequency_hz=10_000_000, setup_ns=0.1, hold_ns=0.1)


if __name__ == "__main__":
    unittest.main()
