from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts/stage-34'))
import t510_power_thermal_causality as campaign


class Stage34c3CampaignTests(unittest.TestCase):
    def test_natural_resume_preserves_success_and_uses_retry_suffix(self) -> None:
        output = [
            {**row, "ok": True}
            for row in campaign.output_load_plan()
        ]
        state = {
            "preflight": {"interventions": {"dac_tile": {"qualified": False}}},
            "runs": output,
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "runs" / "natural_160msps_60min_retry1").mkdir(parents=True)
            rows = campaign.natural_resume_rows(state, root)
            self.assertEqual(
                [row["name"] for row in rows],
                ["natural_160msps_60min_retry2", "natural_320msps_60min_retry1"],
            )

            state["runs"].append(
                {
                    **campaign.natural_plan()[0],
                    "name": "natural_160msps_60min_retry2",
                    "ok": True,
                }
            )
            rows = campaign.natural_resume_rows(state, root)
            self.assertEqual(
                [row["name"] for row in rows],
                ["natural_320msps_60min_retry1"],
            )

    def test_natural_resume_rejects_incomplete_intervention_prefix(self) -> None:
        state = {
            "preflight": {"interventions": {"dac_tile": {"qualified": False}}},
            "runs": [{**row, "ok": True} for row in campaign.output_load_plan()[:-1]],
        }
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(RuntimeError):
                campaign.natural_resume_rows(state, Path(temporary))

    def test_registered_29_run_order_and_duration(self) -> None:
        rows = campaign.full_formal_plan()
        self.assertEqual(len(rows), 29)
        self.assertEqual(len(campaign.output_load_plan()), 9)
        self.assertEqual(len(campaign.dac_tile_plan()), 18)
        self.assertEqual(len(campaign.natural_plan()), 2)
        self.assertEqual(
            [row["condition"] for row in campaign.output_load_plan()],
            ["A1", "B", "A2"] * 3,
        )
        tile = campaign.dac_tile_plan()
        self.assertEqual(
            [row["sample_rate_msps"] for row in tile if row["condition"] == "A1"],
            [160, 320, 320, 160, 160, 320],
        )
        self.assertEqual(
            29 * 600 + 2 * (3600 - 600),
            23_400,
        )

    def test_every_monitor_frequency_is_exact_for_both_rates(self) -> None:
        contract = campaign.monitor_frequency_contract()
        self.assertEqual(len(contract["160"]), 18)
        self.assertEqual(len(contract["320"]), 18)
        self.assertEqual(contract["160"]["966.875000000"], -1360)
        self.assertEqual(contract["320"]["1073.125000000"], 680)

    def test_rank_spearman_bootstrap_and_bh(self) -> None:
        left = [float(value) for value in range(64)]
        right = [2.0 * value + 1.0 for value in left]
        self.assertAlmostEqual(campaign.spearman(left, right), 1.0)
        interval = campaign.block_bootstrap_ci(left, right, seed=34, repetitions=40)
        self.assertGreater(interval["low"], 0.99)
        adjusted = campaign.bh_adjust([0.01, 0.04, 0.03, 0.20])
        self.assertEqual(len(adjusted), 4)
        self.assertTrue(all(0.0 <= value <= 1.0 for value in adjusted))
        self.assertLessEqual(adjusted[0], adjusted[1])

    def test_telemetry_rejects_epoch_change_gap_and_short_run(self) -> None:
        marker = {"epoch_id": "a", "sequence": 10}
        rows = [
            {"epoch_id": "a", "sequence": sequence}
            for sequence in range(11, 605)
        ]
        result = campaign.validate_telemetry(rows, 600, marker=marker)
        self.assertEqual(result["record_count"], 594)
        with self.assertRaises(RuntimeError):
            campaign.validate_telemetry(rows[:-1], 600, marker=marker)
        broken = list(rows)
        broken[20] = {"epoch_id": "a", "sequence": 40}
        with self.assertRaises(RuntimeError):
            campaign.validate_telemetry(broken, 600, marker=marker)

    def test_telemetry_is_aligned_to_receiver_monitor_start(self) -> None:
        rows = [
            {"captured_at_unix_ms": 9_000 + second * 1_000, "sequence": second}
            for second in range(20)
        ]
        aligned, evidence = campaign.align_telemetry_to_monitor(
            {"started_unix_ms": 12_500}, rows, 6
        )
        self.assertEqual([row["captured_at_unix_ms"] for row in aligned], [13_000, 14_000, 15_000, 16_000, 17_000, 18_000])
        self.assertEqual(evidence["first_offset_ms"], 500)

    def test_reversible_gate_and_classification(self) -> None:
        def run(condition: str, repeat: int, slope: float, lag: float, passed: bool):
            combinations = [
                {
                    "group": "offgrid",
                    "slope": slope,
                    "shuffled_slope": -0.5,
                    "slope_pass": passed,
                    "lag1_correlation": lag,
                }
                for _ in range(12)
            ]
            return {
                "name": f"{condition}-{repeat}",
                "condition": condition,
                "repeat": repeat,
                "analysis": {
                    "combinations": combinations,
                    "offgrid": campaign.summarize(combinations),
                },
            }

        rows = []
        for repeat in range(1, 4):
            rows.extend(
                (
                    run("A1", repeat, -0.10, 0.35, False),
                    run("B", repeat, -0.50, 0.02, True),
                    run("A2", repeat, -0.12, 0.33, False),
                )
            )
        metrics = campaign.reversible_metrics(rows)
        self.assertTrue(metrics["causal"])
        self.assertGreater(
            metrics["deltas_b_minus_a1"]["median_abs_slope_error_improvement"],
            0.12,
        )

    def test_unqualified_dac_layer_is_not_silently_called_not_causal(self) -> None:
        def run(condition: str, repeat: int):
            combinations = [
                {
                    "group": "offgrid",
                    "slope": -0.1,
                    "shuffled_slope": -0.5,
                    "slope_pass": False,
                    "lag1_correlation": 0.3,
                }
                for _ in range(12)
            ]
            return {
                "name": f"output-{condition}-{repeat}",
                "layer": "output_load",
                "condition": condition,
                "repeat": repeat,
                "analysis": {
                    "combinations": combinations,
                    "offgrid": campaign.summarize(combinations),
                    "telemetry_correlations": [],
                },
            }

        rows = [run(condition, repeat) for repeat in range(1, 4) for condition in ("A1", "B", "A2")]
        result = campaign.classify(
            rows,
            {"dac_tile": {"qualified": False, "reason": "driver timeout"}},
        )
        self.assertEqual(
            result["primary"],
            "OUTPUT_LOAD_NOT_CAUSAL_DAC_TILE_INTERVENTION_UNQUALIFIED",
        )


if __name__ == "__main__":
    unittest.main()
