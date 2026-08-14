from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from python.t510_clock import (
    LMK04828_INIT_160M_10M_CONTINUOUS,
    LMK04828_INIT_160M_10M_REQUEST_CLKIN0,
    LMK04828_INIT_160M_10M_REQUEST_CLKIN2,
    LMK04828_PROFILE_SHA256,
)
from scripts import t510_clock_sysref_causality as campaign


def _registers(values: tuple[int, ...]) -> dict[int, int]:
    return {(word >> 8) & 0xFFFF: word & 0xFF for word in values}


def _sha(values: tuple[int, ...]) -> str:
    return hashlib.sha256(
        b"".join(value.to_bytes(3, "big") for value in values)
    ).hexdigest()


def test_tics_profiles_are_full_tables_with_frozen_explainable_diffs() -> None:
    assert len(LMK04828_INIT_160M_10M_CONTINUOUS) == 136
    assert len(LMK04828_INIT_160M_10M_REQUEST_CLKIN2) == 136
    assert len(LMK04828_INIT_160M_10M_REQUEST_CLKIN0) == 136
    continuous = _registers(LMK04828_INIT_160M_10M_CONTINUOUS)
    request = _registers(LMK04828_INIT_160M_10M_REQUEST_CLKIN2)
    tcxo = _registers(LMK04828_INIT_160M_10M_REQUEST_CLKIN0)
    assert {address for address in continuous if continuous[address] != request[address]} == {
        0x139, 0x140, 0x16A,
    }
    assert {address for address in request if request[address] != tcxo[address]} == {
        0x146, 0x147, 0x154,
    }
    assert LMK04828_PROFILE_SHA256 == {
        "160m_10m_cont_manual_clkin2": _sha(LMK04828_INIT_160M_10M_CONTINUOUS),
        "160m_10m_request_manual_clkin2": _sha(LMK04828_INIT_160M_10M_REQUEST_CLKIN2),
        "160m_10m_request_manual_clkin0": _sha(LMK04828_INIT_160M_10M_REQUEST_CLKIN0),
    }
    assert campaign.EXT_GATED_PROFILE.endswith("phase_15")
    assert campaign.FIVE_GATED_PROFILE.endswith("phase_15")


def test_campaign_plan_is_complete_balanced_and_non_reusing() -> None:
    screening = campaign.screening_plan()
    assert len(screening) == 18
    assert len({row["name"] for row in screening}) == 18
    assert len(campaign.low_rf_plan()) == 8
    assert len(campaign.low_rf_plan(include_tcxo=False)) == 6
    for layer in ("sysref", "frequency", "reference"):
        rows = campaign.formal_triplet_plan(layer)
        assert len(rows) == 18
        assert len({row["name"] for row in rows}) == 18
        assert [row["sample_rate_msps"] for row in rows[::3]] == [
            160, 320, 320, 160, 160, 320
        ]
        assert [row["condition"] for row in rows] == ["A1", "B", "A2"] * 6


def test_offgrid_points_are_exact_bins_in_both_sample_rates() -> None:
    expected = {
        160: {-1360, -800, -320, 320, 800, 1360},
        320: {-680, -400, -160, 160, 400, 680},
    }
    for rate in campaign.RATES_MSPS:
        spacing_mhz = rate / 4096.0
        bins = {
            round((frequency - campaign.CENTER_MHZ) / spacing_mhz)
            for frequency in campaign.OFFGRID_RF_MHZ
        }
        assert bins == expected[rate]
        for frequency in campaign.OFFGRID_RF_MHZ:
            value = (frequency - campaign.CENTER_MHZ) / spacing_mhz
            assert abs(value - round(value)) < 1e-12


class LowRfMarkerTest(unittest.TestCase):
    def test_markers_use_exact_bins_and_vcxo_uses_nearest_common_bin(self) -> None:
        self.assertEqual(campaign.LOW_RF_NOMINAL_VCXO_MHZ, 122.88)
        self.assertEqual(campaign.LOW_RF_VCXO_CAPTURE_MHZ, 122.890625)
        self.assertIn(
            campaign.LOW_RF_VCXO_CAPTURE_MHZ, campaign.LOW_RF_MARKERS_MHZ
        )
        for rate in campaign.RATES_MSPS:
            spacing_mhz = rate / 4096.0
            for frequency in campaign.LOW_RF_MARKERS_MHZ:
                exact = (frequency - campaign.LOW_RF_CENTER_MHZ) / spacing_mhz
                self.assertLess(abs(exact - round(exact)), 1e-12)
            self.assertLessEqual(
                abs(
                    campaign.LOW_RF_VCXO_CAPTURE_MHZ
                    - campaign.LOW_RF_NOMINAL_VCXO_MHZ
                ),
                spacing_mhz / 2.0,
            )
        contract = campaign.monitor_frequency_contract()
        self.assertEqual(
            contract["low_rf"]["bins"]["160"]["122.890625000"], -950
        )
        self.assertEqual(
            contract["low_rf"]["bins"]["320"]["122.890625000"], -475
        )

    def test_empty_science_groups_are_explicit_for_low_rf_context_runs(self) -> None:
        self.assertEqual(
            campaign.summarize([]),
            {
                "count": 0,
                "slope_pass_count": 0,
                "slope_pass_fraction": None,
                "median_slope": None,
                "median_shuffled_slope": None,
                "median_abs_lag1": None,
                "median_abs_slope_error": None,
            },
        )


class ResumeCheckpointTest(unittest.TestCase):
    @staticmethod
    def checkpoint() -> dict:
        qualifications = {}
        for profile_id in campaign.REQUIRED_PROFILES:
            qualifications[profile_id] = {
                "qualified": True,
                "discovery": [{}] * 10,
                "fixed": [{}] * 10,
                "target": campaign.frozen_profile_target_policy(profile_id)["target"],
            }
        qualifications[campaign.TCXO_GATED_PROFILE] = {
            "qualified": False,
            "discovery": [],
            "fixed": [],
            "error": "PLL1 did not lock",
        }
        screens = [
            {
                "name": row["name"],
                "profile_id": row["profile_id"],
                "duration_seconds": campaign.SCREEN_SECONDS,
                "ok": True,
                "errors": [],
            }
            for row in campaign.screening_plan()
            if row["profile_id"] != campaign.TCXO_GATED_PROFILE
        ]
        return {
            "classification": "STAGE34C2_OPERATIONAL_FAIL",
            "core_version": campaign.CORE_VERSION,
            "bitstream_id": campaign.BITSTREAM_ID,
            "bitstream_sha256": campaign.BITSTREAM_SHA256,
            "pfb_profile_id": campaign.PFB_PROFILE_ID,
            "frozen_target_policy": {
                "sha256": campaign.frozen_target_policy_sha256()
            },
            "profile_qualification": qualifications,
            "runs": screens,
            "errors": [
                "RuntimeError: RF 122.880000000 MHz is not on an exact PFB bin"
            ],
        }

    def test_accepts_only_complete_registered_low_rf_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "campaign.json"
            path.write_text(json.dumps(self.checkpoint()))
            result = campaign.validate_resume_checkpoint(path)
        self.assertFalse(result["tcxo_qualified"])
        self.assertEqual(len(result["reused_screening_names"]), 16)
        self.assertEqual(
            result["targets"][campaign.FIVE_GATED_PROFILE],
            {"adc": 1176, "dac": 252},
        )

    def test_rejects_incomplete_screening_checkpoint(self) -> None:
        checkpoint = self.checkpoint()
        checkpoint["runs"].pop()
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "campaign.json"
            path.write_text(json.dumps(checkpoint))
            with self.assertRaisesRegex(RuntimeError, "screening set mismatch"):
                campaign.validate_resume_checkpoint(path)


class FixedLatencyTargetTest(unittest.TestCase):
    def test_reserves_a_quantum_above_boundary(self) -> None:
        adc = campaign.fixed_latency_target(708, kind="adc")
        dac = campaign.fixed_latency_target(192, kind="dac")
        self.assertEqual(
            adc,
            {
                "max_observed": 708,
                "nominal_margin": 20,
                "margin_floor": 728,
                "latency_quantum": 12,
                "quantized_margin_floor": 732,
                "headroom_quanta": 1,
                "target": 744,
            },
        )
        self.assertEqual(dac["margin_floor"], 208)
        self.assertEqual(dac["quantized_margin_floor"], 216)
        self.assertEqual(dac["target"], 228)
        self.assertGreater(adc["target"], adc["quantized_margin_floor"])
        self.assertGreater(dac["target"], dac["quantized_margin_floor"])

    def test_exact_quantum_still_gets_strict_headroom(self) -> None:
        result = campaign.fixed_latency_target(712, kind="adc")
        self.assertEqual(result["margin_floor"], 732)
        self.assertEqual(result["quantized_margin_floor"], 732)
        self.assertEqual(result["target"], 744)

    def test_profile_targets_are_frozen_from_all_evidence_envelopes(self) -> None:
        expected = {
            campaign.CONT_PROFILE: {"adc": 768, "dac": 228},
            campaign.EXT_GATED_PROFILE: {"adc": 816, "dac": 252},
            campaign.FIVE_GATED_PROFILE: {"adc": 1176, "dac": 252},
            campaign.TCXO_GATED_PROFILE: {"adc": 816, "dac": 252},
        }
        for profile_id, target in expected.items():
            policy = campaign.frozen_profile_target_policy(profile_id)
            self.assertEqual(policy["target"], target)
            self.assertEqual(policy["policy"], "frozen_all_evidence_envelope_v1")
            self.assertTrue(policy["source_sha256"])
        self.assertEqual(
            campaign.frozen_target_policy_sha256(),
            "c39968a394ad53b2fc8dbf401f4974d37340360f285819f545b5ee1e2549a3e7",
        )


def _run(rate: int, slope: float, lag: float) -> dict:
    combinations = []
    for lane in campaign.LANES:
        for group, frequencies in (
            ("fixed", campaign.FIXED_RF_MHZ),
            ("grid", campaign.GRID_RF_MHZ),
            ("offgrid", campaign.OFFGRID_RF_MHZ),
        ):
            for frequency in frequencies:
                combinations.append(
                    {
                        "lane": lane,
                        "group": group,
                        "slope": slope,
                        "shuffled_slope": -0.5,
                        "slope_pass": -0.65 <= slope <= -0.35,
                        "lag1_correlation": lag,
                        "mean_dbfs": -80.0,
                    }
                )
    return {"sample_rate_msps": rate, "analysis": {"combinations": combinations}}


def test_offgrid_absolute_gate_and_causal_reversal() -> None:
    good = [_run(rate, -0.50, 0.02) for rate in campaign.RATES_MSPS for _ in range(3)]
    bad = [_run(rate, -0.05, 0.35) for rate in campaign.RATES_MSPS for _ in range(3)]
    assert campaign.condition_gate(good, "offgrid")["pass"]
    assert not campaign.condition_gate(bad, "offgrid")["pass"]
    causal = campaign.causal_metrics(bad, good, bad, "offgrid")
    assert causal["pass"]


class ProfileQualificationCheckpointTest(unittest.TestCase):
    def test_failing_cycle_is_persisted(self) -> None:
        calls = 0

        def prepare(*args, **kwargs):
            nonlocal calls
            calls += 1
            discovery = calls <= 10
            failing_fixed = calls == 20
            return {
                "mts": {
                    "adc": {"active_measured_latency": [400] * 4},
                    "dac": {
                        "active_measured_latency": (
                            [100] * 4
                            if discovery or not failing_fixed
                            else [116, 116, 108, 108]
                        )
                    },
                }
            }

        with tempfile.TemporaryDirectory() as temp_dir, mock.patch.object(
            campaign, "fresh_configure", return_value={}
        ), mock.patch.object(
            campaign, "restore_clock", return_value={}
        ), mock.patch.object(
            campaign, "prepare_clock", side_effect=prepare
        ):
            checkpoint = Path(temp_dir) / "qualification.json"
            with self.assertRaisesRegex(RuntimeError, "fixed dac latency"):
                campaign.qualify_profile(
                    object(),
                    {},
                    campaign.EXT_GATED_PROFILE,
                    checkpoint_path=checkpoint,
                )
            evidence = json.loads(checkpoint.read_text())
        self.assertEqual(len(evidence["discovery"]), 10)
        self.assertEqual(len(evidence["fixed"]), 10)
        self.assertEqual(evidence["target"], {"adc": 816, "dac": 252})
        self.assertEqual(
            evidence["target_policy"]["derivation"]["adc"]["quantized_margin_floor"],
            804,
        )
        self.assertEqual(
            evidence["fixed"][-1]["mts"]["dac"]["active_measured_latency"],
            [116, 116, 108, 108],
        )

    def test_discovery_above_frozen_envelope_stops_before_fixed(self) -> None:
        calls = 0

        def prepare(*args, **kwargs):
            nonlocal calls
            calls += 1
            return {
                "mts": {
                    "adc": {"active_measured_latency": [792] * 4},
                    "dac": {"active_measured_latency": [216] * 4},
                }
            }

        with tempfile.TemporaryDirectory() as temp_dir, mock.patch.object(
            campaign, "fresh_configure", return_value={}
        ), mock.patch.object(
            campaign, "restore_clock", return_value={}
        ), mock.patch.object(
            campaign, "prepare_clock", side_effect=prepare
        ):
            checkpoint = Path(temp_dir) / "qualification.json"
            with self.assertRaisesRegex(RuntimeError, "exceeds frozen envelope 780"):
                campaign.qualify_profile(
                    object(),
                    {},
                    campaign.EXT_GATED_PROFILE,
                    checkpoint_path=checkpoint,
                )
            evidence = json.loads(checkpoint.read_text())
        self.assertEqual(calls, 10)
        self.assertEqual(len(evidence["fixed"]), 0)
        self.assertEqual(evidence["target_policy"]["observed_discovery_max"]["adc"], 792)


class V35SciencePlanTest(unittest.TestCase):
    def test_v35_identity_and_selected_profiles_are_frozen(self) -> None:
        self.assertEqual(campaign.CORE_VERSION, "0x00010035")
        self.assertEqual(campaign.BITSTREAM_ID, "fengine-0x00010035")
        self.assertEqual(
            campaign.BITSTREAM_SHA256,
            "8934a0c2d7033494b49133d846f954b52a6fa76a54b65c043c6e7be5289728d1",
        )
        self.assertEqual(
            campaign.EXT_GATED_PROFILE,
            "160m_10m_request_clkin2_sdclkout3_phase_15",
        )
        self.assertEqual(
            campaign.FIVE_GATED_PROFILE,
            "160m_5m_request_clkin2_sdclkout3_phase_15",
        )

    def test_all_three_reversible_layers_are_balanced(self) -> None:
        self.assertEqual(len(campaign.screening_plan()), 18)
        for layer in ("sysref", "frequency", "reference"):
            rows = campaign.formal_triplet_plan(layer)
            self.assertEqual(len(rows), 18)
            self.assertEqual(
                [row["condition"] for row in rows], ["A1", "B", "A2"] * 6
            )
        frequency = campaign.formal_triplet_plan("frequency")
        self.assertEqual(
            [row["profile_id"] for row in frequency[:3]],
            [
                campaign.EXT_GATED_PROFILE,
                campaign.FIVE_GATED_PROFILE,
                campaign.EXT_GATED_PROFILE,
            ],
        )
