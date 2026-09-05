from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts/stage-34'))
import t510_clock_sysref_causality as campaign
import t510_stage34c2r_finalize as finalize


class Stage34c2rFinalizeTest(unittest.TestCase):
    def test_real_r6_checkpoint_is_strictly_reusable(self) -> None:
        path = Path(
            "build/receiver/latest/evidence/clock_sysref_causality/"
            "science_matrix/attempt_r6/campaign.json"
        )
        if not path.is_file():
            self.skipTest("r6 evidence is not present")
        result = finalize.validate_completed_r6(path)
        self.assertEqual(len(result["formal"]), 36)
        self.assertEqual(len(result["accepted_low"]), 3)
        self.assertEqual(len(result["recapture"]), 3)
        self.assertEqual(
            result["analysis"]["sysref"]["classification"],
            "CLOCK_SYSREF_NOT_CAUSAL_UNDER_SHARED_50OHM",
        )

    def test_final_classification_prefers_non_neutral_frequency_result(self) -> None:
        analysis = {
            "sysref": {"classification": "CLOCK_SYSREF_NOT_CAUSAL_UNDER_SHARED_50OHM"},
            "frequency": {"classification": "SYSREF_RATE_CONTRIBUTOR"},
            "reference": {"classification": "TCXO_PROFILE_UNQUALIFIED"},
        }
        self.assertEqual(finalize.final_classification(analysis), "SYSREF_RATE_CONTRIBUTOR")

    def test_referenced_manifest_hashes_without_copying_pcaps(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pcap = root / "sample.pcap"
            pcap.write_bytes(b"pcap")
            runs = [{"begin_capture": {"paths": [str(pcap)]}, "end_capture": {"paths": [str(pcap)]}}]
            result = finalize.referenced_pcap_manifest(root, runs, root)
            self.assertEqual(result["pcap_count"], 1)
            self.assertIn("sample.pcap", (root / "pcap_manifest.sha256").read_text())


if __name__ == "__main__":
    unittest.main()
