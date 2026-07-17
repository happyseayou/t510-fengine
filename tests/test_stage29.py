from __future__ import annotations

import inspect
import json
from pathlib import Path
import unittest

from python.stage29 import (
    DacChannelConfig,
    DEFAULT_SOURCE_IP,
    DEFAULT_SOURCE_MAC,
    EXPECTED_CORE_VERSION,
    FlowDestination,
    PFB_BLOCK_COUNT,
    PFB_CHAN_COUNT,
    PFB_NCHAN,
    PFB_TAPS,
    PFB_TIME_COUNT,
    SPEC_DST_PORT_BASE,
    SPEC_SRC_PORT_BASE,
    Stage29Config,
    Stage29Controller,
    TIME_DST_PORT_BASE,
    TIME_SRC_PORT_BASE,
)
from python.t510_fengine import RegisterMap, T510FEngine


class FakeCore:
    def __init__(self) -> None:
        self.observation_kwargs = None
        self.science_kwargs = None
        self.endpoints = None
        self.source_identity = None
        self.source_calls = 0
        self.board_id = 0
        self.board_calls = 0
        self.corrupt_endpoint = None
        self.corrupt_source = False
        self.corrupt_board = False
        self.events: list[tuple] = []
        self.started = False

    def apply_mts_locked_observation_config(self, **kwargs):
        self.observation_kwargs = kwargs
        return {
            "ok": True,
            "nco": {
                "mts": {
                    "available": True,
                    "calls": [{"label": "adc_mts_sync", "result": 0}],
                    "failures": [],
                }
            },
        }

    def configure_science_29(self, **kwargs):
        self.science_kwargs = kwargs
        return {"ok": True}

    def configure_tx_endpoints(self, endpoints):
        self.endpoints = [dict(endpoint) for endpoint in endpoints]

    def read_tx_endpoints(self, endpoint_ids):
        selected = [dict(self.endpoints[index]) for index in endpoint_ids]
        if self.corrupt_endpoint is not None:
            selected[self.corrupt_endpoint]["src_port"] += 1
        return selected

    def configure_tx_source_identity(self, **kwargs):
        self.source_calls += 1
        self.source_identity = dict(kwargs)
        result = dict(kwargs)
        if self.corrupt_source:
            result["src_port"] += 1
        return result

    def configure_board_id(self, board_id):
        self.board_calls += 1
        self.board_id = int(board_id)
        if self.corrupt_board:
            return self.board_id ^ 1
        self.events.append(("board_id", self.board_id))
        return self.board_id

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

    def stop(self):
        self.events.append(("stop",))

    def read_status(self):
        return {"core_version": EXPECTED_CORE_VERSION, "board_id": self.board_id}

    def read_dac_channels(self, *, dac_sample_rate_hz):
        return {
            "enable_mask": 0,
            "dac_phase_epoch": 9,
            "channels": [
                {
                    "channel": channel,
                    "enabled": False,
                    "phase_step": 0,
                    "baseband_frequency_hz": 0.0,
                    "amplitude_code": 0,
                    "phase_deg": 0.0,
                }
                for channel in range(8)
            ],
        }

    dac_phase_step_from_frequency = staticmethod(T510FEngine.dac_phase_step_from_frequency)
    _wrap_phase0_word = staticmethod(T510FEngine._wrap_phase0_word)


class DummyCtrl:
    def __init__(self) -> None:
        self.writes = []
        self.values = {}

    def write(self, address, value) -> None:
        self.writes.append((address, value))
        self.values[address] = value

    def read(self, address):
        return self.values.get(address, 0)


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
        self.assertEqual((config.source_ip, config.source_mac), (DEFAULT_SOURCE_IP, DEFAULT_SOURCE_MAC))
        self.assertEqual(len(config.time_destinations), 8)
        self.assertEqual(len(config.spec_destinations), 16)
        self.assertEqual([row.destination_port for row in config.time_destinations], list(range(4300, 4308)))
        self.assertEqual([row.destination_port for row in config.spec_destinations], list(range(4308, 4324)))
        self.assertEqual([row.source_port for row in config.time_destinations], list(range(4000, 4008)))
        self.assertEqual([row.source_port for row in config.spec_destinations], list(range(4008, 4024)))
        for kwargs in ({"ip": "999.1.1.1"}, {"mac": "bad"}, {"destination_port": 0}, {"source_port": 0}, {"source_port": 65536}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                FlowDestination(**kwargs)
        with self.assertRaisesRegex(ValueError, "exactly 8"):
            Stage29Config(time_destinations=(FlowDestination(),) * 7)

    def test_source_identity_validation(self) -> None:
        config = Stage29Config(source_ip="10.20.30.40", source_mac="02:AA:BB:CC:DD:EE")
        self.assertEqual(config.source_ip, "10.20.30.40")
        self.assertEqual(config.source_mac, "02:aa:bb:cc:dd:ee")
        for kwargs in (
            {"source_ip": "0.0.0.0"},
            {"source_ip": "239.1.2.3"},
            {"source_ip": "255.255.255.255"},
            {"source_mac": "00:00:00:00:00:00"},
            {"source_mac": "01:00:5e:00:00:01"},
            {"source_mac": "bad"},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                Stage29Config(**kwargs)

    def test_board_id_validation(self) -> None:
        self.assertEqual(Stage29Config().board_id, 0)
        self.assertEqual(Stage29Config(board_id=0xFFFF).board_id, 0xFFFF)
        for board_id in (-1, 0x1_0000):
            with self.subTest(board_id=board_id), self.assertRaisesRegex(ValueError, "board_id"):
                Stage29Config(board_id=board_id)

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
        self.assertEqual((TIME_SRC_PORT_BASE, SPEC_SRC_PORT_BASE), (4000, 4008))
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
        time[3] = FlowDestination(ip="10.0.1.33", mac="02:11:22:33:44:55", destination_port=5303, source_port=5103)
        config = Stage29Config(
            bandwidth_mhz=100,
            mode="time_only",
            board_id=37,
            source_ip="10.20.30.40",
            source_mac="02:aa:bb:cc:dd:ee",
            time_destinations=tuple(time),
        )
        result = controller.apply(config, fresh_download=False)
        self.assertEqual(core.observation_kwargs["dac_signal_hz"], 100_000_000.0)
        self.assertEqual(core.observation_kwargs["enable_mask"], 0)
        self.assertEqual(core.science_kwargs["start"], False)
        self.assertEqual(core.science_kwargs["src_ip"], "10.20.30.40")
        self.assertEqual(core.science_kwargs["src_mac"], "02:aa:bb:cc:dd:ee")
        self.assertEqual(core.board_id, 37)
        self.assertEqual(result["board_identity"], {"requested": 37, "readback": 37})
        self.assertEqual(core.source_identity, {"ip": "10.20.30.40", "mac": "02:aa:bb:cc:dd:ee", "src_port": 4000})
        self.assertEqual(len(core.endpoints), 24)
        self.assertEqual(core.endpoints[3]["dst_port"], 5303)
        self.assertEqual(core.endpoints[3]["src_port"], 5103)
        self.assertTrue(core.endpoints[3]["enable"])
        self.assertFalse(core.endpoints[8]["enable"])
        self.assertEqual(result["endpoint_readback"], core.endpoints)
        self.assertTrue(core.started)

    def test_prepare_leaves_stream_stopped_and_apply_keeps_legacy_start(self) -> None:
        core = FakeCore()
        controller = Stage29Controller("overlay/t510_fengine.bit", core=core)  # type: ignore[arg-type]
        prepared = controller.prepare(Stage29Config(), fresh_download=False)
        self.assertFalse(prepared["started"])
        self.assertFalse(core.started)
        self.assertNotIn(("start",), core.events)
        applied = controller.apply(Stage29Config(), fresh_download=False)
        self.assertTrue(applied["started"])
        self.assertTrue(core.started)
        self.assertEqual(core.events.count(("start",)), 1)

    def test_identity_or_endpoint_readback_failure_never_starts(self) -> None:
        for failure in ("board", "source", "endpoint"):
            with self.subTest(failure=failure):
                core = FakeCore()
                core.corrupt_board = failure == "board"
                core.corrupt_source = failure == "source"
                core.corrupt_endpoint = 7 if failure == "endpoint" else None
                controller = Stage29Controller("overlay/t510_fengine.bit", core=core)  # type: ignore[arg-type]
                with self.assertRaisesRegex(RuntimeError, "readback mismatch"):
                    controller.apply(Stage29Config(), fresh_download=False)
                self.assertFalse(core.started)
                self.assertNotIn(("start",), core.events)

    def test_all_24_source_ports_follow_endpoint_rows_and_mode(self) -> None:
        core = FakeCore()
        controller = Stage29Controller("overlay/t510_fengine.bit", core=core)  # type: ignore[arg-type]
        time = tuple(
            FlowDestination(destination_port=4300 + flow, source_port=12000 + flow)
            for flow in range(8)
        )
        spec = tuple(
            FlowDestination(destination_port=4308 + flow, source_port=22000 + flow)
            for flow in range(16)
        )
        controller.apply(
            Stage29Config(mode="spec_only", time_destinations=time, spec_destinations=spec),
            fresh_download=False,
        )
        self.assertEqual([row["src_port"] for row in core.endpoints[:8]], list(range(12000, 12008)))
        self.assertEqual([row["src_port"] for row in core.endpoints[8:]], list(range(22000, 22016)))
        self.assertTrue(all(not row["enable"] for row in core.endpoints[:8]))
        self.assertTrue(all(row["enable"] for row in core.endpoints[8:]))
        self.assertEqual(core.source_identity["src_port"], 22000)

    def test_duplicate_active_udp_tuple_warns_without_blocking(self) -> None:
        core = FakeCore()
        controller = Stage29Controller("overlay/t510_fengine.bit", core=core)  # type: ignore[arg-type]
        time = list(Stage29Config().time_destinations)
        time[1] = FlowDestination(
            ip=time[0].ip,
            mac=time[0].mac,
            destination_port=time[0].destination_port,
            source_port=time[0].source_port,
        )
        result = controller.apply(
            Stage29Config(mode="time_only", time_destinations=tuple(time)),
            fresh_download=False,
        )
        self.assertTrue(core.started)
        self.assertEqual(len(result["flow_warnings"]), 1)
        self.assertIn("EP0 and EP1", result["flow_warnings"][0])

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
        self.assertEqual(core.source_calls, 0)
        self.assertEqual(core.board_calls, 0)

    def test_live_dac_apply_preserves_board_id(self) -> None:
        core = FakeCore()
        controller = Stage29Controller("overlay/t510_fengine.bit", core=core)  # type: ignore[arg-type]
        controller.config = Stage29Config(board_id=23)
        controller.apply_dac_live(controller.config.dac_channels)
        self.assertEqual(controller.config.board_id, 23)
        self.assertEqual(core.board_calls, 0)

    def test_stateless_live_dac_apply_accepts_explicit_center(self) -> None:
        core = FakeCore()
        controller = Stage29Controller("overlay/t510_fengine.bit", core=core)  # type: ignore[arg-type]
        channels = tuple(
            DacChannelConfig(rf_frequency_mhz=100.01, phase_deg=channel)
            for channel in range(8)
        )
        result = controller.apply_dac_live(channels, center_mhz=100.0)
        self.assertEqual(result["enable_mask"], 0xFF)
        self.assertEqual(len(result["readback"]["channels"]), 8)
        self.assertIsNone(controller.config)
        self.assertNotIn(("start",), core.events)

    def test_dac_register_readback_covers_all_eight_channels(self) -> None:
        core = FakeStage29FEngine()
        core.ctrl.values[core.regs.DAC_ENABLE_MASK] = 0xA5
        core.ctrl.values[core.regs.DAC_PHASE_EPOCH] = 17
        for channel in range(8):
            base = core.regs.DAC_CH_BASE + channel * core.regs.DAC_CH_STRIDE
            core.ctrl.values[base + 0x00] = channel + 1
            core.ctrl.values[base + 0x04] = 1000 + channel
            core.ctrl.values[base + 0x08] = channel << 28
            core.ctrl.values[base + 0x0C] = 200 + channel
            core.ctrl.values[base + 0x10] = 1
        result = core.read_dac_channels()
        self.assertEqual(result["enable_mask"], 0xA5)
        self.assertEqual(result["dac_phase_epoch"], 17)
        self.assertEqual(len(result["channels"]), 8)
        self.assertEqual([row["enabled"] for row in result["channels"]], [True, False, True, False, False, True, False, True])
        self.assertEqual([row["amplitude_code"] for row in result["channels"]], list(range(1000, 1008)))
        self.assertAlmostEqual(result["channels"][2]["phase_deg"], 45.0)

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
                self.assertEqual(core.live_kwargs["src_ip"], DEFAULT_SOURCE_IP)
                self.assertEqual(core.live_kwargs["src_mac"], DEFAULT_SOURCE_MAC)
                self.assertEqual(result["host_flow_count"], 8 if mode == "time_only" else (16 if mode == "spec_only" else 24))

    def test_low_level_stage29_accepts_global_source_identity(self) -> None:
        core = FakeStage29FEngine()
        core.configure_science_29(
            output_mode="time_only",
            src_ip="10.20.30.40",
            src_mac="02:aa:bb:cc:dd:ee",
            start=False,
        )
        self.assertEqual(core.live_kwargs["src_ip"], "10.20.30.40")
        self.assertEqual(core.live_kwargs["src_mac"], "02:aa:bb:cc:dd:ee")

    def test_inactive_endpoint_with_full_config_programs_every_field(self) -> None:
        core = FakeStage29FEngine()
        core.configure_tx_endpoints([{
            "id": 9,
            "enable": False,
            "ip": "10.0.1.99",
            "mac": "02:11:22:33:44:55",
            "dst_port": 5399,
            "src_port": 5099,
        }])
        addresses = [address for address, _value in core.ctrl.writes]
        for address in (
            core.regs.TX_ENDPOINT_INDIRECT_IP,
            core.regs.TX_ENDPOINT_INDIRECT_MAC_LO,
            core.regs.TX_ENDPOINT_INDIRECT_MAC_HI,
            core.regs.TX_ENDPOINT_INDIRECT_DST_PORT,
            core.regs.TX_ENDPOINT_INDIRECT_SRC_PORT,
            core.regs.TX_ENDPOINT_INDIRECT_ENABLE,
        ):
            self.assertIn(address, addresses)

    def test_global_source_identity_register_round_trip(self) -> None:
        core = FakeStage29FEngine()
        result = core.configure_tx_source_identity(
            ip="10.20.30.40",
            mac="02:aa:bb:cc:dd:ee",
            src_port=5010,
        )
        self.assertEqual(result, {"ip": "10.20.30.40", "mac": "02:aa:bb:cc:dd:ee", "src_port": 5010})

    def test_board_id_register_round_trip_and_validation(self) -> None:
        core = FakeStage29FEngine()
        self.assertEqual(core.configure_board_id(0xBEEF), 0xBEEF)
        self.assertIn((core.regs.BOARD_ID, 0xBEEF), core.ctrl.writes)
        for board_id in (-1, 0x1_0000):
            with self.subTest(board_id=board_id), self.assertRaisesRegex(ValueError, "board_id"):
                core.configure_board_id(board_id)

    def test_low_level_stage29_rejects_fixed_parameter_override_before_hardware(self) -> None:
        core = object.__new__(T510FEngine)
        with self.assertRaisesRegex(ValueError, "cannot be overridden"):
            core.configure_science_29(time_dst_port_base=9999)

    def test_stage31_first_sample_alignment_tracks_active_science_path(self) -> None:
        self.assertEqual(T510FEngine._stage31_first_sample0_rule(0, False), (32, 0, 32768))
        self.assertEqual(T510FEngine._stage31_first_sample0_rule(1, False), (8, 0, 32768))
        self.assertEqual(T510FEngine._stage31_first_sample0_rule(1, True), (8, 4, 32788))
        self.assertEqual(T510FEngine._stage31_first_sample0_rule(2, False), (4, 0, 32768))

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
