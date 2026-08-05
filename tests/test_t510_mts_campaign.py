from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest


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
    def test_initial_conditioning_is_recorded_outside_campaign_cycles(self) -> None:
        core = _Core()
        result = CAMPAIGN._condition_initial_hardware(
            core,
            lmk_settle_seconds=0.0,
            settle_seconds=0.0,
        )
        self.assertTrue(result["ok"])
        self.assertFalse(result["counted_as_campaign_cycle"])
        self.assertEqual(len(result["reset_calls"]), 8)
        self.assertEqual(core.events[0], "stop")
        self.assertEqual(
            core.events[1],
            "clock:external_10mhz:160m_10m_continuous",
        )
        self.assertEqual(core.events[2:10], [
            "reset:adc0", "reset:adc1", "reset:adc2", "reset:adc3",
            "reset:dac0", "reset:dac1", "reset:dac2", "reset:dac3",
        ])
        self.assertEqual(core.events[-2:], ["lmk_status:False", "rfdc_contract:True"])

    def test_initial_conditioning_fails_closed_before_tile_reset(self) -> None:
        core = _Core(clock_configured=False)
        with self.assertRaisesRegex(RuntimeError, "initial LMK configuration did not lock"):
            CAMPAIGN._condition_initial_hardware(
                core,
                lmk_settle_seconds=0.0,
                settle_seconds=0.0,
            )
        self.assertFalse(any(event.startswith("reset:") for event in core.events))

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
            "DAC_TILE_LATENCY_MISMATCH",
            CAMPAIGN._assess_cycle(
                payload,
                phase="fixed",
                adc_target=452,
                dac_target=88,
            ),
        )


if __name__ == "__main__":
    unittest.main()
