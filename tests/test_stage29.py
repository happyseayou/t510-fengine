from __future__ import annotations

import inspect
import json
from pathlib import Path
import unittest

from python.stage29 import (
    DacChannelConfig,
    EXPECTED_CORE_VERSION,
    FlowDestination,
    PFB_BLOCK_COUNT,
    PFB_CHAN_COUNT,
    PFB_NCHAN,
    PFB_TAPS,
    PFB_TIME_COUNT,
    SPEC_DST_PORT_BASE,
    Stage29Config,
    Stage29Controller,
    TIME_DST_PORT_BASE,
)
from python.t510_fengine import RegisterMap, T510FEngine


class FakeCore:
    def __init__(self) -> None:
        self.observation_kwargs = None
        self.science_kwargs = None
        self.endpoints = None
        self.events: list[tuple] = []
        self.started = False

    def apply_mts_locked_observation_config(self, **kwargs):
        self.observation_kwargs = kwargs
        return {"ok": True}

    def configure_science_29(self, **kwargs):
        self.science_kwargs = kwargs
        return {"ok": True}

    def configure_tx_endpoints(self, endpoints):
        self.endpoints = endpoints

    def set_dac_enable_mask(self, mask):
        self.events.append(("mask", mask))

    def set_dac_tone(self, **kwargs):
        self.events.append(("tone", kwargs))

    def reset_dac_phase(self):
        self.events.append(("epoch",))
        return 9

    def start(self):
        self.started = True
        self.events.append(("start",))

    def read_status(self):
        return {"core_version": EXPECTED_CORE_VERSION}

    dac_phase_step_from_frequency = staticmethod(T510FEngine.dac_phase_step_from_frequency)
    _wrap_phase0_word = staticmethod(T510FEngine._wrap_phase0_word)


class DummyCtrl:
    def __init__(self) -> None:
        self.writes = []

    def write(self, address, value) -> None:
        self.writes.append((address, value))


class FakeStage29FEngine(T510FEngine):
    def __init__(self) -> None:
        self.ctrl = DummyCtrl()
        self.regs = RegisterMap()
        self.live_kwargs = None
        self.time_routes_cleared = False
        self.spec_routes_cleared = False
        self.started = False

    def configure_science_live_27e(self, **kwargs):
        self.live_kwargs = kwargs
        return {}

    def configure_time_routes(self, routes, *, clear_unlisted=True):
        self.time_routes_cleared = routes == [] and clear_unlisted

    def configure_spec_routes(self, routes, *, clear_unlisted=True):
        self.spec_routes_cleared = routes == [] and clear_unlisted

    def load_pfb_coefficients(self, coefficients=None, **kwargs):
        return {"loaded": coefficients is None, **kwargs}

    def start(self):
        self.started = True

    def read_science_output_status(self):
        return {}

    def read_tx_status(self):
        return {}

    def read_channelizer_status(self):
        return {}


class Stage29ConfigTests(unittest.TestCase):
    def test_five_profiles_and_rates(self) -> None:
        expected = {
            (100, "time_only"): (8, 31_948.8),
            (100, "spec_only"): (16, 31_948.8),
            (100, "time_spec"): (24, 63_897.6),
            (200, "time_only"): (8, 63_897.6),
            (200, "spec_only"): (16, 63_897.6),
        }
        for (bandwidth, mode), (flows, payload) in expected.items():
            with self.subTest(bandwidth=bandwidth, mode=mode):
                config = Stage29Config(bandwidth_mhz=bandwidth, mode=mode)
                self.assertEqual(config.flow_count, flows)
                self.assertAlmostEqual(config.expected_packet_rates["combined_t510_udp_payload_mbps"], payload)

    def test_200mhz_dual_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "200MHz"):
            Stage29Config(bandwidth_mhz=200, mode="time_spec")

    def test_destination_defaults_and_validation(self) -> None:
        config = Stage29Config()
        self.assertEqual(len(config.time_destinations), 8)
        self.assertEqual(len(config.spec_destinations), 16)
        self.assertEqual([row.destination_port for row in config.time_destinations], list(range(4300, 4308)))
        self.assertEqual([row.destination_port for row in config.spec_destinations], list(range(4308, 4324)))
        for kwargs in ({"ip": "999.1.1.1"}, {"mac": "bad"}, {"destination_port": 0}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                FlowDestination(**kwargs)
        with self.assertRaisesRegex(ValueError, "exactly 8"):
            Stage29Config(time_destinations=(FlowDestination(),) * 7)

    def test_dac_validation_and_band_edges(self) -> None:
        for kwargs in ({"amplitude": -1}, {"rf_frequency_mhz": float("nan")}, {"phase_deg": 181}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                DacChannelConfig(**kwargs)
        edge_100 = tuple(DacChannelConfig(rf_frequency_mhz=value) for value in (50.0, 161.44) + (100.0,) * 6)
        Stage29Config(bandwidth_mhz=100, dac_channels=edge_100)
        with self.assertRaisesRegex(ValueError, "Nyquist"):
            Stage29Config(bandwidth_mhz=100, dac_channels=(DacChannelConfig(rf_frequency_mhz=161.441),) * 8)
        edge_200 = tuple(DacChannelConfig(rf_frequency_mhz=value) for value in (50.0, 222.88) + (100.0,) * 6)
        Stage29Config(bandwidth_mhz=200, mode="spec_only", dac_channels=edge_200)

    def test_frozen_contract_and_frequency_geometry(self) -> None:
        self.assertEqual((TIME_DST_PORT_BASE, SPEC_DST_PORT_BASE), (4300, 4308))
        self.assertEqual((PFB_NCHAN, PFB_TAPS), (4096, 4))
        self.assertEqual((PFB_BLOCK_COUNT, PFB_CHAN_COUNT, PFB_TIME_COUNT), (16, 256, 1))
        for bandwidth, half_span, bin_width in ((100, 61.44, 30_000.0), (200, 122.88, 60_000.0)):
            config = Stage29Config(bandwidth_mhz=bandwidth, mode="spec_only", center_mhz=100.0)
            info = config.nearest_fft_bin()
            self.assertEqual(info["bin_width_hz"], bin_width)
            self.assertAlmostEqual(config.center_mhz - config.sample_rate_hz / 2.0 / 1.0e6, 100.0 - half_span)

    def test_controller_programs_endpoint_table_and_common_nco(self) -> None:
        core = FakeCore()
        controller = Stage29Controller("overlay/t510_fengine.bit", core=core)  # type: ignore[arg-type]
        time = list(Stage29Config().time_destinations)
        time[3] = FlowDestination(ip="10.0.1.33", mac="02:11:22:33:44:55", destination_port=5303)
        config = Stage29Config(bandwidth_mhz=100, mode="time_only", time_destinations=tuple(time))
        controller.apply(config, fresh_download=False)
        self.assertEqual(core.observation_kwargs["dac_signal_hz"], 100_000_000.0)
        self.assertEqual(core.observation_kwargs["enable_mask"], 0)
        self.assertEqual(core.science_kwargs["start"], False)
        self.assertEqual(len(core.endpoints), 24)
        self.assertEqual(core.endpoints[3]["dst_port"], 5303)
        self.assertEqual(core.endpoints[3]["src_port"], 4003)
        self.assertTrue(core.endpoints[3]["enable"])
        self.assertFalse(core.endpoints[8]["enable"])
        self.assertTrue(core.started)

    def test_live_dac_apply_mutes_writes_all_lanes_and_restores(self) -> None:
        core = FakeCore()
        controller = Stage29Controller("overlay/t510_fengine.bit", core=core)  # type: ignore[arg-type]
        controller.config = Stage29Config()
        channels = tuple(DacChannelConfig(enabled=channel != 7, rf_frequency_mhz=60.0 + channel, amplitude=10 + channel, phase_deg=channel * 5) for channel in range(8))
        result = controller.apply_dac_live(channels)
        self.assertEqual(core.events[0], ("mask", 0))
        tones = [event for event in core.events if event[0] == "tone"]
        self.assertEqual(len(tones), 8)
        self.assertTrue(all(event[1]["enable"] is False for event in tones))
        self.assertEqual(core.events[-2], ("epoch",))
        self.assertEqual(core.events[-1], ("mask", 0x7F))
        self.assertEqual(result["enable_mask"], 0x7F)
        self.assertNotIn(("start",), core.events)

    def test_low_level_profiles_fix_routes_pfb_and_wire_parameters(self) -> None:
        for mode, clear_time, clear_spec, pfb_control in (("time_only", False, True, 0), ("spec_only", True, False, 3), ("time_spec", False, False, 3)):
            with self.subTest(mode=mode):
                core = FakeStage29FEngine()
                result = core.configure_science_29(output_mode=mode, start=False)
                self.assertEqual(core.time_routes_cleared, clear_time)
                self.assertEqual(core.spec_routes_cleared, clear_spec)
                self.assertIn((core.regs.PFB_CONTROL, pfb_control), core.ctrl.writes)
                self.assertEqual(core.live_kwargs["time_dst_port_base"], 4300)
                self.assertEqual(core.live_kwargs["spec_dst_port_base"], 4308)
                self.assertEqual(core.live_kwargs["time_flow_count"], 8)
                self.assertEqual(core.live_kwargs["spec_route_count"], 16)
                self.assertEqual(core.live_kwargs["input_mask"], 0xFF)
                self.assertEqual(result["host_flow_count"], 8 if mode == "time_only" else (16 if mode == "spec_only" else 24))

    def test_low_level_stage29_rejects_fixed_parameter_override_before_hardware(self) -> None:
        core = object.__new__(T510FEngine)
        with self.assertRaisesRegex(ValueError, "cannot be overridden"):
            core.configure_science_29(time_dst_port_base=9999)

    def test_stage28_api_and_thin_notebook(self) -> None:
        stage28 = inspect.signature(T510FEngine.run_stage28_validation)
        stage29 = inspect.signature(T510FEngine.run_stage29_validation)
        self.assertEqual(stage28.parameters["expected_core_version"].default, EXPECTED_CORE_VERSION)
        self.assertNotIn("expected_core_version", stage29.parameters)
        path = Path(__file__).resolve().parents[1] / "notebooks" / "00_stage29_fengine_production_control.ipynb"
        notebook = json.loads(path.read_text())
        code = "".join("".join(cell.get("source", [])) for cell in notebook["cells"] if cell.get("cell_type") == "code")
        self.assertLess(len(code), 2000)
        self.assertIn("create_console", code)


if __name__ == "__main__":
    unittest.main()
