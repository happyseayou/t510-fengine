from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "pynq_t510_mts_campaign",
    ROOT / "scripts" / "pynq_t510_mts_campaign.py",
)
assert SPEC is not None and SPEC.loader is not None
CAMPAIGN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CAMPAIGN)


class _Tile:
    def __init__(self, events: list[str], label: str) -> None:
        self.events = events
        self.label = label

    def Reset(self) -> None:
        self.events.append(f"reset:{self.label}")


class _Core:
    PRODUCTION_CLOCK_REF = "external_10mhz"
    PRODUCTION_CLOCK_PROFILE = "160m_10m_continuous"

    def __init__(self, *, clock_configured: bool = True) -> None:
        self.events: list[str] = []
        self.clock_configured = clock_configured
        self.rfdc = SimpleNamespace(
            adc_tiles=[_Tile(self.events, f"adc{index}") for index in range(4)],
            dac_tiles=[_Tile(self.events, f"dac{index}") for index in range(4)],
        )

    def stop(self) -> None:
        self.events.append("stop")

    def configure_clock(self, *, ref: str, profile: str) -> dict[str, object]:
        self.events.append(f"clock:{ref}:{profile}")
        return {"configured": self.clock_configured}

    def read_lmk_status(self, *, include_registers: bool) -> dict[str, object]:
        self.events.append(f"lmk_status:{include_registers}")
        return {"configured": True, "profile_id": "160m_10m_cont_manual_clkin2"}

    def read_rfdc_contract(self, *, require: bool) -> dict[str, object]:
        self.events.append(f"rfdc_contract:{require}")
        return {"ok": True}


class T510MtsCampaignTests(unittest.TestCase):
    def test_bootstrap_preserves_clock_before_download_without_tile_reset(self):
        events=[]; ctrl=Mock(); core=ctrl.require_core.return_value
        ctrl.connect.side_effect=lambda **kw: events.append('download')
        core.stop.side_effect=lambda: events.append('stop')
        core.set_dac_enable_mask.side_effect=lambda n: events.append(('mute', n))
        with patch.object(CAMPAIGN, '_preserve_clock', side_effect=lambda ref: events.append('clock_gate')):
            result=CAMPAIGN._condition_initial_hardware(ctrl, lmk_settle_seconds=0,
                settle_seconds=0, clock_ref='tcxo_10mhz')
        self.assertEqual(events, ['clock_gate','download','stop',('mute',0)])
        self.assertFalse(result['counted_as_campaign_cycle'])
        core.configure_clock.assert_not_called()
        core.reset_all_rfdc_tiles.assert_not_called()

    def test_clock_identity_failure_cannot_download_or_reset(self):
        ctrl=Mock()
        with patch.object(CAMPAIGN, '_preserve_clock', side_effect=RuntimeError('identity mismatch')):
            with self.assertRaisesRegex(RuntimeError, 'identity mismatch'):
                CAMPAIGN._condition_initial_hardware(ctrl, lmk_settle_seconds=0,
                    settle_seconds=0, clock_ref='tcxo_10mhz')
        ctrl.connect.assert_not_called()

    def test_lmk_handoff_shutdown_precedes_clock_and_sysref_precedes_restart(self):
        events=[]; ctrl=Mock(); core=ctrl.require_core.return_value
        core.shutdown_all_rfdc_tiles.side_effect=lambda: events.append('shutdown')
        core.configure_clock.side_effect=lambda **kw: events.append('lmk') or {'configured':True}
        core.clock.set_sysref.side_effect=lambda on: events.append(('sysref',on))
        ctrl.connect.side_effect=lambda **kw: events.append('download')
        core.set_dac_enable_mask.side_effect=lambda mask: events.append(('mute',mask))
        with patch.object(CAMPAIGN, '_reset_rfdc_tiles', side_effect=lambda c: events.append('reset')):
            CAMPAIGN._reload_lmk(ctrl, clock_ref='tcxo_10mhz', settle_seconds=0)
        self.assertEqual(events,[('mute',0),'shutdown','lmk',('sysref',True),'download',('mute',0),'reset'])

    def test_lmk_lock_failure_does_not_reload_or_reset(self):
        ctrl=Mock(); core=ctrl.require_core.return_value
        core.configure_clock.return_value={'configured':False}
        with self.assertRaisesRegex(RuntimeError,'failed to lock'):
            CAMPAIGN._reload_lmk(ctrl, clock_ref='tcxo_10mhz', settle_seconds=0)
        ctrl.connect.assert_not_called()
        core.clock.set_sysref.assert_not_called()

    def test_discovery_reuses_quantized_strict_headroom_policy(self):
        policy = CAMPAIGN._recommended_fixed_targets(
            [432] * 4 + [456] * 4,
            [48] * 4 + [768] * 4 + [96] * 4,
        )
        self.assertEqual(policy["targets"], {"adc": 492, "dac": -1})
        self.assertEqual(
            policy["derivation"]["current_observed_bounds"]["adc"]["max"], 456
        )
        self.assertEqual(
            policy["derivation"]["dac_normalized_observations"],
            [48] * 4 + [48] * 4 + [96] * 4,
        )
        self.assertEqual(policy["derivation"]["dac_sysref_t1_period"], 720)
        self.assertIsNone(policy["derivation"]["worst_case_frozen_offsets"]["dac"])
        self.assertEqual(policy["derivation"]["dac_alignment_mode"], "single_device_relative")
        self.assertFalse(policy["derivation"]["dac_deterministic_target_feasible"])
        self.assertEqual(
            policy["derivation"]["dac_deterministic_infeasible_witness"],
            [32, 384, 416],
        )
        self.assertEqual(policy["derivation"]["dac_feasible_fixed_targets"], [])
        boundary = CAMPAIGN._recommended_fixed_targets(
            [360, 456], [32, 384, 416, 768]
        )
        self.assertEqual(
            boundary["derivation"]["dac_normalized_observations"],
            [32, 384, 416, 48],
        )

    def test_discovery_fails_if_frozen_envelope_or_delay_range_is_exceeded(self):
        with self.assertRaisesRegex(ValueError, "ADC_DISCOVERY_EXCEEDS_FROZEN_MAX"):
            CAMPAIGN._recommended_fixed_targets([468] * 4, [48] * 4)
        with self.assertRaisesRegex(ValueError, "ADC_DISCOVERY_EXCEEDS_DELAY_RANGE"):
            CAMPAIGN._recommended_fixed_targets([0] * 4, [48] * 4)
        relative = CAMPAIGN._recommended_fixed_targets([432] * 4, [752] * 4)
        self.assertEqual(relative["targets"]["dac"], -1)

    def test_fixed_cycle_accepts_driver_factor_quantization(self) -> None:
        payload = {
            "clock": {
                "configured": True,
                "profile_id": "160m_10m_cont_manual_clkin2",
                "sysref_mode": "continuous",
            },
            "mts": {
                "failures": [],
                "calls": [],
                "adc_config": {
                    "tiles": 0xF,
                    "target_latency": 452,
                    "latency": [456] * 4,
                    "offset": [2] * 4,
                },
                "dac_config": {
                    "tiles": 0xF,
                    "target_latency": 88,
                    "latency": [92] * 4,
                    "offset": [5] * 4,
                },
            },
        }
        self.assertEqual(
            CAMPAIGN._assess_cycle(
                payload,
                phase="fixed",
                adc_target=452,
                dac_target=88,
            ),
            [],
        )
        payload["mts"]["dac_config"]["latency"] = [92, 92, 92, 80]
        self.assertIn(
            "DAC_INTERTILE_RESIDUAL_EXCEEDS_FACTOR_QUANTIZATION",
            CAMPAIGN._assess_cycle(
                payload,
                phase="fixed",
                adc_target=452,
                dac_target=88,
            ),
        )

    def test_discovery_accepts_real_r5_driver_quantized_dac_vector(self) -> None:
        payload = {
            "clock_ref": "tcxo_10mhz",
            "clock": {
                "configured": True,
                "profile_id": "160m_10m_request_manual_clkin0",
                "sysref_mode": "request",
                "sysref_request_gpio": 0,
                "sysref_output_expected_on": False,
            },
            "mts": {
                "failures": [],
                "calls": [],
                "adc_config": {
                    "tiles": 0xF,
                    "target_latency": -1,
                    "latency": [408, 408, 408, 408],
                    "offset": [0, 0, 0, 0],
                },
                "dac_config": {
                    "tiles": 0xF,
                    "target_latency": -1,
                    "latency": [768, 768, 768, 764],
                    "offset": [0, 0, 0, 29],
                },
            },
        }
        self.assertEqual(
            CAMPAIGN._assess_cycle(
                payload, phase="discovery", adc_target=-1, dac_target=-1
            ),
            [],
        )

    def test_fixed_accepts_adc_target_with_r6_dac_relative_vector(self) -> None:
        payload = {
            "clock_ref": "tcxo_10mhz",
            "clock": {
                "configured": True,
                "profile_id": "160m_10m_request_manual_clkin0",
                "sysref_mode": "request",
                "sysref_request_gpio": 0,
                "sysref_output_expected_on": False,
            },
            "mts": {
                "failures": [],
                "calls": [],
                "adc_config": {
                    "tiles": 0xF,
                    "target_latency": 492,
                    "latency": [492, 492, 492, 492],
                    "offset": [7, 7, 7, 7],
                },
                "dac_config": {
                    "tiles": 0xF,
                    "target_latency": -1,
                    "latency": [416, 416, 416, 416],
                    "offset": [0, 0, 0, 0],
                },
            },
        }
        self.assertEqual(
            CAMPAIGN._assess_cycle(
                payload, phase="fixed", adc_target=492, dac_target=-1
            ),
            [],
        )

    def test_fixed_phase_rederives_frozen_target_from_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            discovery = Path(temporary) / "discovery.json"
            discovery.write_text(json.dumps({
                "observed_latency": {"adc": [360, 456], "dac": [32, 384, 768]},
                "recommended_fixed_targets": {"adc": 480, "dac": 400},
            }))
            args = SimpleNamespace(
                phase="fixed", adc_target=None, dac_target=None,
                discovery_json=str(discovery),
            )
            with self.assertRaisesRegex(ValueError, "do not match frozen policy"):
                CAMPAIGN._targets(args)


if __name__ == "__main__":
    unittest.main()
