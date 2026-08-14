from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock

from python import t510_hw
from python.t510_fengine import T510FEngine


def tile(enabled: bool) -> dict[str, int]:
    return {
        "IsEnabled": int(enabled),
        "TileState": 15 if enabled else 0,
        "BlockStatusMask": 3 if enabled else 0,
        "PowerUpState": 1 if enabled else 0,
        "PLLState": 1 if enabled else 0,
    }


class FakeLib:
    def __init__(self, rfdc: types.SimpleNamespace) -> None:
        self.rfdc = rfdc
        self.calls = []

    def XRFdc_Shutdown(self, instance, converter_type, tile_id):
        self.calls.append(("shutdown", converter_type, tile_id))
        self.rfdc.IPStatus["DACTileStatus"] = [tile(False) for _ in range(4)]
        return 0

    def XRFdc_StartUp(self, instance, converter_type, tile_id):
        self.calls.append(("startup", converter_type, tile_id))
        self.rfdc.IPStatus["DACTileStatus"] = [tile(True) for _ in range(4)]
        return 0


class Stage34c3PowerDiagnosticTests(unittest.TestCase):
    def test_normalized_ip_status_and_dac_all_tile_shutdown_startup(self) -> None:
        rfdc = types.SimpleNamespace(
            _instance=object(),
            IPStatus={
                "State": 1,
                "ADCTileStatus": [tile(True) for _ in range(4)],
                "DACTileStatus": [tile(True) for _ in range(4)],
            },
        )
        fake_lib = FakeLib(rfdc)
        engine = object.__new__(T510FEngine)
        engine.rfdc = rfdc
        with mock.patch.dict(sys.modules, {"xrfdc": types.SimpleNamespace(_lib=fake_lib)}):
            before = engine.read_rfdc_tile_power_status()
            self.assertEqual(before["adc_enabled_mask"], 0xF)
            self.assertEqual(before["dac_enabled_mask"], 0xF)
            stopped = engine.shutdown_all_dac_tiles()
            self.assertEqual(stopped["after"]["adc_enabled_mask"], 0xF)
            self.assertEqual(stopped["after"]["dac_enabled_mask"], 0)
            started = engine.startup_all_dac_tiles()
            self.assertEqual(started["after"]["dac_enabled_mask"], 0xF)
        self.assertEqual(
            fake_lib.calls,
            [("shutdown", 1, -1), ("startup", 1, -1)],
        )

    def test_persisted_transactions_invalidate_and_full_configure_marks_normal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "output.json"
            power = root / "power.json"
            with mock.patch.object(t510_hw, "OUTPUT_LOAD_STATE_PATH", output), mock.patch.object(
                t510_hw, "RFDC_POWER_STATE_PATH", power
            ):
                t510_hw._persist_output_load_state(
                    {
                        "state": t510_hw.OUTPUT_LOAD_ACTIVE,
                        "output_load_transaction_id": "output-1",
                        "transaction_valid": True,
                    }
                )
                invalid = t510_hw._invalidate_output_load_state("SERVICE_RESTART")
                self.assertEqual(invalid["state"], t510_hw.OUTPUT_LOAD_RESTORE_REQUIRED)
                self.assertFalse(invalid["transaction_valid"])
                t510_hw._persist_rfdc_power_state(
                    {
                        "state": t510_hw.RFDC_POWER_DAC_SHUTDOWN,
                        "rfdc_power_transaction_id": "power-1",
                        "transaction_valid": True,
                    }
                )
                invalid = t510_hw._invalidate_rfdc_power_state("SERVICE_RESTART")
                self.assertEqual(invalid["state"], t510_hw.RFDC_POWER_RESTORE_REQUIRED)
                self.assertFalse(invalid["transaction_valid"])
                self.assertEqual(t510_hw._mark_output_load_production()["state"], "PRODUCTION")
                self.assertEqual(t510_hw._mark_rfdc_power_normal()["state"], "NORMAL")
                self.assertEqual(json.loads(output.read_text())["state"], "PRODUCTION")
                self.assertEqual(json.loads(power.read_text())["state"], "NORMAL")

    def test_output_load_uses_one_aggregate_route_then_eight_way_multiflow(self) -> None:
        class Core:
            def __init__(self):
                self.endpoints = []
                self.routes = []
                self.mode = "spec_only"

            def read_status(self):
                return {
                    "science_sample_rate_msps": 160,
                    "science_output_mode": {"spec_only": 2, "time_spec": 3}[self.mode],
                }

            def configure_tx_endpoints(self, endpoints):
                self.endpoints = list(endpoints)

            def configure_time_routes(self, routes, *, clear_unlisted=True):
                self.routes = list(routes)
                self.clear_unlisted = clear_unlisted

            def configure_science_output(self, *args, **kwargs):
                self.mode = args[1]
                return {"mode": self.mode}

            def read_tx_endpoints(self, _ids):
                return list(self.endpoints)

            def read_time_route_table(self):
                return [
                    {
                        "id": route_id,
                        "enable": int(route_id == 0),
                        "endpoint_id": 0,
                        "input_mask": 0xFF if route_id == 0 else 0,
                        "hit_count": 0,
                    }
                    for route_id in range(8)
                ]

            def read_science_output_status(self):
                return {
                    "time_multiflow_enable": 1,
                    "time_multiflow_base_endpoint": 0,
                    "time_multiflow_count": 8,
                }

        core = Core()
        controller = types.SimpleNamespace(require_core=lambda: core)
        endpoints = [
            {
                "endpoint_id": endpoint_id,
                "destination_ip": "10.0.1.16",
                "destination_mac": "4c:bb:47:2b:42:6e",
                "destination_port": 4300 + endpoint_id,
                "source_port": 4000 + endpoint_id,
            }
            for endpoint_id in range(24)
        ]
        with mock.patch.object(
            t510_hw,
            "_load_saved_configure_request",
            return_value={"request": {"endpoints": endpoints}},
        ):
            result = t510_hw._apply_output_load_mode(controller, "time_spec")
        self.assertEqual(
            core.routes,
            [{"id": 0, "enable": True, "endpoint_id": 0, "input_mask": 0xFF}],
        )
        self.assertTrue(core.clear_unlisted)
        self.assertTrue(all(row["enable"] for row in core.endpoints))
        self.assertEqual(result["time_multiflow_readback"]["time_multiflow_count"], 8)


if __name__ == "__main__":
    unittest.main()
