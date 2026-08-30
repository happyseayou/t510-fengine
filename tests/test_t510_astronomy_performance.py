from __future__ import annotations

import json
from pathlib import Path
import random
import tempfile
import unittest

from scripts import t510_astronomy_performance as performance
from scripts import t510_astronomy_tg as tg


class Stage34aCampaignTests(unittest.TestCase):
    def test_160_scan_grid_and_fixed_contract(self) -> None:
        self.assertEqual(len(performance.CENTERS_160_MHZ), 23)
        self.assertEqual(performance.CENTERS_160_MHZ[0], 80.0)
        self.assertEqual(performance.CENTERS_160_MHZ[-1], 1840.0)
        self.assertEqual(performance.FORMAL_STABILITY_SECONDS, 600)
        self.assertEqual(performance.STABILITY_RF_MHZ, (960.0, 980.0, 1000.0, 1040.0, 1060.0, 1080.0))

    def test_configure_body_enables_only_spectrum_endpoints(self) -> None:
        template = {
            "endpoints": [
                {"stream": "TIME", "enabled": True},
                {"stream": "SPEC", "enabled": False},
            ]
        }
        result = performance.configure_body(template, 160, 1020.0)
        self.assertEqual(result["profile"], {"sample_rate_msps": 160, "mode": "spec_only", "center_mhz": 1020.0})
        self.assertFalse(result["endpoints"][0]["enabled"])
        self.assertTrue(result["endpoints"][1]["enabled"])
        self.assertEqual(result["bitstream_id"], "fengine-0x00010034")

    def test_frozen_local_evidence_audit_binds_current_bitstream(self) -> None:
        root = Path(__file__).resolve().parents[1]
        board_evidence = root / "build/board/latest/evidence"
        receiver_evidence = (
            root / "build/receiver/latest/evidence/fullband_spur_scan"
        )
        if not receiver_evidence.exists():
            self.skipTest(
                "historical receiver evidence was intentionally removed at closed-stage cleanup"
            )
        result = performance.audit_frozen_evidence(
            board_evidence,
            receiver_evidence,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["bitstream_sha256"], performance.BITSTREAM_SHA256)
        self.assertEqual(result["fullband_320"]["packets"], 32_256)

    def test_stability_analysis_requires_eighty_percent_clean_slopes(self) -> None:
        generator = random.Random(34)
        targets = [
            {"target_index": index, "actual_rf_mhz": rf}
            for index, rf in enumerate(performance.STABILITY_RF_MHZ)
        ]
        rows = []
        cross = []
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
                            "sum_i": 0.0,
                            "sum_q": 0.0,
                            "sum_power": power,
                            "sum_power_squared": power * power,
                        }
                    )
                cross.append(
                    {
                        "second": second,
                        "target_index": target["target_index"],
                        "channel_a": 0,
                        "channel_b": 2,
                        "sample_count": 1,
                        "sum_cross_re": 100.0,
                        "sum_cross_im": 0.0,
                        "sum_power_a": 100.0,
                        "sum_power_b": 100.0,
                    }
                )
        with tempfile.TemporaryDirectory() as temporary:
            mode = Path(temporary)
            (mode / "monitor_raw.json").write_text(
                json.dumps({"targets": targets, "power_seconds": rows, "cross_seconds": cross})
            )
            result = performance.load_stability_analysis(mode)
        self.assertEqual(result["clean_slope_total"], 40)
        self.assertTrue(result["ok"])

    def test_tg_plan_is_manual_complete_and_no_retry(self) -> None:
        plan = tg.tg_plan()
        self.assertEqual(len(plan["captures"]), 10)
        self.assertEqual(len(plan["stability"]), 2)
        self.assertEqual(plan["fresh_configure_mts_repeatability"]["cycles"], 5)
        self.assertFalse(plan["fresh_configure_mts_repeatability"]["automatic_retry"])
        self.assertEqual(plan["source_limited_signature"]["carrier_relative_offset_mhz"], 91.71875)

    def test_phase_unwrap_removes_wrap_not_real_drift(self) -> None:
        self.assertEqual(tg.unwrap_degrees([179.0, -179.0, -178.0]), [179.0, 181.0, 182.0])


if __name__ == "__main__":
    unittest.main()
