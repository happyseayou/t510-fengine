from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
MATRIX = ROOT / "scripts" / "stage33_release_matrix.py"


class Stage33ReleaseMatrixTests(unittest.TestCase):
    def test_dry_run_covers_frozen_smoke_soak_and_thermal_cases(self) -> None:
        expected = {
            "smoke_60s": [
                (160, "time_only"),
                (160, "spec_only"),
                (160, "time_spec"),
                (320, "time_only"),
                (320, "spec_only"),
            ],
            "soak_10m": [
                (160, "time_spec"),
                (320, "time_only"),
                (320, "spec_only"),
            ],
            "thermal_60m": [(160, "time_spec")],
        }
        with tempfile.TemporaryDirectory() as temporary:
            for suite, cases in expected.items():
                with self.subTest(suite=suite):
                    result = subprocess.run(
                        [
                            sys.executable,
                            str(MATRIX),
                            "--suite",
                            suite,
                            "--tag",
                            "unit",
                            "--output-dir",
                            temporary,
                            "--dry-run",
                        ],
                        cwd=ROOT,
                        check=False,
                        capture_output=True,
                        text=True,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    value = json.loads(result.stdout)
                    actual = [
                        (row["sample_rate_msps"], row["mode"])
                        for row in value["cases"]
                    ]
                    self.assertEqual(actual, cases)
                    self.assertTrue(all(row["ok"] for row in value["cases"]))
                    self.assertEqual(
                        value["cases"][0]["enable_all_dacs"],
                        suite == "thermal_60m",
                    )
                    self.assertTrue(
                        all(
                            any("stage33_agent_host_gate.py" in item for item in row["gate_command"])
                            for row in value["cases"]
                        )
                    )
                    self.assertTrue(
                        all(
                            "--center-mhz" in row["gate_command"]
                            and "200.0" in row["gate_command"]
                            for row in value["cases"]
                        )
                    )


if __name__ == "__main__":
    unittest.main()
