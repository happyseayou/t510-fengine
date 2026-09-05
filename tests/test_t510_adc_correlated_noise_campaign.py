from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts/stage-34'))
import t510_adc_correlated_noise_campaign as campaign


def combinations(*, slope: float, lag: float) -> list[dict]:
    rows = []
    for lane in campaign.LANES:
        for rf_mhz in campaign.RF_FREQUENCIES_MHZ:
            rows.append(
                {
                    "lane": lane,
                    "rf_mhz": rf_mhz,
                    "clean": rf_mhz in campaign.CLEAN_RF_MHZ,
                    "slope": slope,
                    "shuffled_slope": -0.5,
                    "slope_pass": -0.65 <= slope <= -0.35,
                    "lag1_correlation": lag,
                }
            )
    return rows


def run(rate: int, condition: str, slope: float, lag: float, hashes: int) -> dict:
    rows = combinations(slope=slope, lag=lag)
    clean = [row for row in rows if row["clean"]]
    fixed = [row for row in rows if not row["clean"]]
    return {
        "sample_rate_msps": rate,
        "condition": condition,
        "ocb1_unique_hashes": hashes,
        "analysis": {
            "combinations": rows,
            "clean": campaign.summarize_combinations(clean),
            "fixed_960": campaign.summarize_combinations(fixed),
        },
    }


class Stage34cCampaignTests(unittest.TestCase):
    def test_large_trace_is_appended_then_materialized_once(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "calibration_ams_trace.json"
            with campaign.IncrementalJsonTrace(path) as trace:
                for index in range(600):
                    trace.append(
                        {
                            "elapsed_seconds": index,
                            "payload": "x" * 1000,
                        }
                    )
                self.assertFalse(path.exists())
                self.assertEqual(
                    len(path.with_suffix(".jsonl").read_text().splitlines()), 600
                )
            rows = json.loads(path.read_text())
            self.assertEqual(len(rows), 600)
            self.assertEqual(rows[-1]["elapsed_seconds"], 599)
            self.assertFalse(path.with_suffix(".jsonl").exists())

    def test_configure_body_selects_time_spec_and_spec_only_endpoints(self) -> None:
        template = {
            "endpoints": [
                {"stream": "TIME", "enabled": False},
                {"stream": "SPEC", "enabled": False},
            ]
        }
        time_spec = campaign.configure_body(template, 160, "time_spec", 1020.0)
        self.assertEqual([row["enabled"] for row in time_spec["endpoints"]], [True, True])
        spec_only = campaign.configure_body(template, 320, "spec_only", 1020.0)
        self.assertEqual([row["enabled"] for row in spec_only["endpoints"]], [False, True])

    def test_stage34c0_requires_each_repeat_and_24_of_30(self) -> None:
        passing = [run(160, "C0_DYNAMIC", -0.5, 0.02, 3) for _ in range(3)]
        gate = campaign.run_gate(passing)
        self.assertTrue(gate["pass"])
        failing = list(passing)
        failing[1] = run(160, "C0_DYNAMIC", -0.1, 0.3, 3)
        self.assertFalse(campaign.run_gate(failing)["pass"])

    def test_temperature_channels_are_not_mixed_into_one_span(self) -> None:
        result = campaign.extract_temperatures(
            {
                "ams": {
                    "temperatures_c": {
                        "ps_temp": {"min": 39.8, "mean": 40.0, "max": 40.2},
                        "pl_temp": {"min": 42.8, "mean": 43.0, "max": 43.2},
                    }
                }
            }
        )
        self.assertEqual(result, {"ps_temp": 40.0, "pl_temp": 43.0})
        self.assertLess(max([39.9, result["ps_temp"]]) - min([39.9, result["ps_temp"]]), 2.0)
        self.assertLess(max([42.9, result["pl_temp"]]) - min([42.9, result["pl_temp"]]), 2.0)

    def test_thermal_warmup_requires_each_sensor_to_be_stable_for_one_minute(self) -> None:
        stable = campaign.thermal_window_summary(
            [
                {
                    "ps_temp": 40.0 + 0.2 * index / 59.0,
                    "pl_temp": 43.0 + 0.3 * index / 59.0,
                    "remote_temp": 41.0 + 0.1 * index / 59.0,
                }
                for index in range(60)
            ]
        )
        self.assertTrue(stable["stable"])

        warming = campaign.thermal_window_summary(
            [{"remote_temp": 40.0 + index / 59.0} for index in range(60)]
        )
        self.assertFalse(warming["stable"])

    def test_temperature_gate_preserves_raw_spike_but_uses_rolling_median(self) -> None:
        values = [40.0] * 60
        values[30] = 42.5
        summary = campaign.temperature_series_summary({"ps_temp": values})["ps_temp"]
        self.assertEqual(summary["raw"]["span"], 2.5)
        self.assertEqual(summary["filtered"]["span"], 0.0)

    def test_temperature_relaxation_warns_above_two_and_stops_above_2p5(self) -> None:
        warning = campaign.temperature_gate(
            {
                "ps_temp": {
                    "filtered": {"min": 45.0, "max": 47.011, "span": 2.011}
                }
            }
        )
        self.assertTrue(warning["pass"])
        self.assertTrue(warning["warning"])
        self.assertEqual(
            warning["sensors"]["ps_temp"]["status"],
            "WARNING_OVER_ORIGINAL_2C_LIMIT",
        )

        failed = campaign.temperature_gate(
            {
                "ps_temp": {
                    "filtered": {"min": 45.0, "max": 47.501, "span": 2.501}
                }
            }
        )
        self.assertFalse(failed["pass"])
        self.assertEqual(failed["failed_sensors"], ["ps_temp"])

    def test_ocb1_resume_from_triplet_three_repeats_complete_triplet_suffix(self) -> None:
        plan = campaign.ocb1_triplet_plan()
        self.assertEqual(len(plan), 6)
        self.assertEqual(plan[2]["prefix"], "c1_t03_320msps_r2")
        self.assertEqual(
            [row["prefix"] for row in plan if row["triplet_index"] >= 3],
            [
                "c1_t03_320msps_r2",
                "c1_t04_160msps_r2",
                "c1_t05_160msps_r3",
                "c1_t06_320msps_r3",
            ],
        )

    def test_ocb1_causal_requires_a1_b_a2_reversibility_and_hashes(self) -> None:
        rows = []
        for rate in campaign.RATES_MSPS:
            for _repeat in range(3):
                rows.extend(
                    [
                        run(rate, "A1_DYNAMIC", -0.1, 0.30, 3),
                        run(rate, "B_OCB1_SNAPSHOT", -0.5, 0.02, 1),
                        run(rate, "A2_RESTORED", -0.1, 0.30, 3),
                    ]
                )
        result = campaign.aggregate_ocb1(rows)
        self.assertTrue(result["pass"])
        self.assertEqual(result["classification"], "OCB1_CAUSAL_ADC0_ADC2")

        rows[1]["ocb1_unique_hashes"] = 2
        failed = campaign.aggregate_ocb1(rows)
        self.assertFalse(failed["pass"])
        self.assertEqual(failed["classification"], "OCB1_CONTRIBUTOR")

    def test_scientific_negative_classifications_are_successful_completion(self) -> None:
        self.assertIn(
            "OCB1_NOT_CAUSAL_UNDER_SHARED_50OHM",
            campaign.SCIENTIFIC_EXIT_CLASSIFICATIONS,
        )
        self.assertNotIn("STAGE34C_OPERATIONAL_FAIL", campaign.SCIENTIFIC_EXIT_CLASSIFICATIONS)


if __name__ == "__main__":
    unittest.main()
