from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
BOARD_CAMPAIGN = ROOT / "scripts" / "pynq_stage33_rf_campaign.py"
PURITY_MATRIX = ROOT / "scripts" / "stage33_dac_purity_matrix.py"
COLD_START_GATE = ROOT / "scripts" / "stage33_cold_start_gate.py"


class Stage33RfCampaignTests(unittest.TestCase):
    def test_board_dry_run_uses_catalog_targets_and_frozen_points(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            bitfile = work / "candidate.bit"
            bitfile.write_bytes(b"stage33-test-bitstream")
            digest = hashlib.sha256(bitfile.read_bytes()).hexdigest()
            catalog = work / "catalog.json"
            catalog.write_text(
                json.dumps(
                    {
                        "bitstreams": [
                            {
                                "id": "fengine-0x00010033",
                                "core_version": "0x00010033",
                                "sha256": digest,
                                "mts_adc_target_latency": 251,
                                "mts_dac_target_latency": 357,
                                "mts_campaign": {
                                    "discovery": {
                                        "rfdc_reset": 20,
                                        "overlay_reload": 10,
                                        "lmk_reload": 10,
                                        "passed": 40,
                                    },
                                    "fixed": {
                                        "rfdc_reset": 20,
                                        "overlay_reload": 10,
                                        "lmk_reload": 10,
                                        "passed": 40,
                                    },
                                    "observed_adc_max": 231,
                                    "observed_dac_max": 341,
                                    "adc_margin": 20,
                                    "dac_margin": 16,
                                    "evidence_sha256": "1" * 64,
                                },
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(BOARD_CAMPAIGN),
                    "--catalog",
                    str(catalog),
                    "--bitfile",
                    str(bitfile),
                    "--output-dir",
                    str(work / "out"),
                    "--tag",
                    "unit",
                    "--dry-run",
                ],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            value = json.loads(result.stdout)
            self.assertEqual(
                [(row["center_mhz"], row["signal_mhz"]) for row in value["cases"]],
                [(200.0, 210.0), (960.0, 970.0), (1760.0, 1770.0), (1760.0, 1900.0)],
            )
            self.assertEqual(value["fixed_targets"], {"adc": 251, "dac": 357})
            self.assertTrue(
                all("251" in row["command"] and "357" in row["command"] for row in value["cases"])
            )

    def test_purity_dry_run_covers_low_mid_high_and_1900(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run(
                [
                    sys.executable,
                    str(PURITY_MATRIX),
                    "--output-dir",
                    temporary,
                    "--tag",
                    "unit",
                    "--dry-run",
                ],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            value = json.loads(result.stdout)
            self.assertEqual(
                [(row["center_mhz"], row["tone_mhz"]) for row in value["cases"]],
                [(200.0, 210.0), (960.0, 970.0), (1760.0, 1770.0), (1760.0, 1900.0)],
            )
            self.assertTrue(
                all(
                    any("stage33_dac_purity_gate.py" in item for item in row["gate_command"])
                    for row in value["cases"]
                )
            )

    def test_cold_start_dry_run_checks_services_and_fresh_configure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run(
                [
                    sys.executable,
                    str(COLD_START_GATE),
                    "--output-dir",
                    temporary,
                    "--tag",
                    "unit",
                    "--dry-run",
                ],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            value = json.loads(result.stdout)
            self.assertEqual(value["classification"], "STAGE33_COLD_START_DRY_RUN")
            commands = value["commands"]
            self.assertIn("t510-agent.service", commands["board_active"])
            self.assertIn("t510-time-rx.service", commands["receiver_active"])
            self.assertTrue(
                any("t510_agent_client.py" in item for item in commands["configure"])
            )


if __name__ == "__main__":
    unittest.main()
