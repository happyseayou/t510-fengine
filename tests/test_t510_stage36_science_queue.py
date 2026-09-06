from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/stage-36/t510_stage36_science_capture_queue.py"


class Stage36ScienceQueueTests(unittest.TestCase):
    def test_dry_run_freezes_complete_capture_plan(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--queue-id",
                "stage36-test",
                "--source-commit",
                "0123456789abcdef",
                "--template",
                str(ROOT / "config/t510/qualification-template.json"),
                "--helper-dir",
                str(ROOT / "scripts/stage-35"),
                "--dry-run",
            ],
            check=True,
            text=True,
            capture_output=True,
        )
        plan = json.loads(completed.stdout)
        phases = plan["phases"]
        self.assertEqual(plan["core_version"], "0x00010036")
        self.assertEqual(
            plan["bitstream_sha256"],
            "e00c586a1d862d7c7af113361832a30093334493e49f943e3dd22bf44f950665",
        )
        self.assertEqual(len(phases), 13)
        self.assertEqual(sum(row["duration_seconds"] for row in phases), 4740)
        self.assertEqual([row["kind"] for row in phases].count("spec"), 3)
        self.assertEqual([row["kind"] for row in phases].count("xcorr"), 1)
        self.assertEqual(sum(bool(row.get("raw_time_witness")) for row in phases), 1)
        self.assertEqual(sum(bool(row.get("raw_spec_witness")) for row in phases), 1)

    def test_source_requests_current_products_and_fail_closed_cleanup(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn('"save_fullband_100ms": True', source)
        self.assertIn('"stage": "36"', source)
        self.assertIn('"/api/measure/time"', source)
        self.assertIn('"/api/measure/autocorrelation"', source)
        self.assertIn('"/api/measure/crosscorrelation"', source)
        self.assertNotIn("/api/measure/stage35-", source)
        self.assertIn("safe_finalize(failed=True)", source)
        self.assertIn("time_derived_100ms_1s.npz", source)
        self.assertIn("from t510_stage35_time_verify import crop_continuous_pcap, verify_pcap", source)
        self.assertNotIn("from t510_time_capture_verify", source)
        self.assertIn("resume_after_time_witness_import_failure", source)


if __name__ == "__main__":
    unittest.main()
