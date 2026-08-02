from __future__ import annotations

import inspect
import json
from pathlib import Path
import unittest

from python.t510_control import (
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
    FEngineConfig,
    FEngineController,
    TIME_DST_PORT_BASE,
    TIME_SRC_PORT_BASE,
)
from python.t510_fengine import RegisterMap, T510FEngine
from scripts.stage33_agent_host_gate import _qsfp_physical_health, _stage33_rfdc_health


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

    def configure_science(self, **kwargs):
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
        return {
            "core_version": EXPECTED_CORE_VERSION,
            "board_id": self.board_id,
            "science_sample_rate_msps": 160,
        }

    def read_rfdc_mixer_frequencies(self):
        center_mhz = 200.0
        return {
            "available": True,
            "mixers": [
                {"kind": "dac", "tile": channel // 2, "block": (channel % 2) * 2, "frequency_mhz": center_mhz}
                for channel in range(8)
            ],
            "errors": [],
        }

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


class FakeFEngineFEngine(T510FEngine):
    def __init__(self) -> None:
        self.ctrl = DummyCtrl()
        self.regs = RegisterMap()
        self.live_kwargs = None
        self.time_routes_cleared = False
        self.spec_routes_cleared = False
        self.started = False

    def _configure_science_data_path(self, **kwargs):
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


class LifecycleCore:
    def __init__(self, statuses: list[dict]) -> None:
        self.statuses = list(statuses)
        self.last_status = dict(statuses[-1])
        self.started = False
        self.stopped = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def read_status(self) -> dict:
        if self.statuses:
            self.last_status = dict(self.statuses.pop(0))
        return dict(self.last_status)


class FEngineConfigTests(unittest.TestCase):
    def test_qsfp_health_does_not_treat_axis_backpressure_as_link_loss(self) -> None:
        health = _qsfp_physical_health(
            {"link_up": False, "raw_flags": 0x988C_F00C}
        )
        self.assertTrue(health["physical_healthy"])
        self.assertFalse(health["link_up_sample"])
        self.assertFalse(health["tx_ready_sample"])

    def test_qsfp_health_rejects_missing_alignment_or_real_fault(self) -> None:
        missing_alignment = _qsfp_physical_health(
            {"link_up": False, "raw_flags": 0x988C_F00C & ~(1 << 18)}
        )
        local_fault = _qsfp_physical_health(
            {"link_up": False, "raw_flags": 0x988C_F00C | (1 << 5)}
        )
        self.assertFalse(missing_alignment["physical_healthy"])
        self.assertFalse(local_fault["physical_healthy"])

    def test_stage33_host_gate_requires_full_rfdc_readback(self) -> None:
        tiles = [
            {
                "kind": kind,
                "tile": tile,
                "pll_lock_status": 1,
                "sample_rate_hz": 3_840_000_000.0,
            }
            for kind in ("adc", "dac")
            for tile in range(4)
        ]
        blocks = [
            {
                "kind": kind,
                "tile": tile,
                "block": block,
                "factor": 12,
                "nyquist_zone": 1,
                "mixer_frequency_mhz": -200.0 if kind == "adc" else 200.0,
            }
            for kind in ("adc", "dac")
            for tile in range(4)
            for block in range(2)
        ]
        snapshot = {
            "profile": {"center_mhz": 200.0},
            "rfdc": {
                "adc_analog_sample_rate_hz": 3_840_000_000,
                "dac_analog_sample_rate_hz": 3_840_000_000,
                "complex_sample_rate_hz": 320_000_000,
                "adc_decimation": 12,
                "dac_interpolation": 12,
                "adc_axis_rate_hz": 80_000_000,
                "dac_axis_rate_hz": 80_000_000,
                "active_mask": 0xFFFF,
                "current_valid_mask": 0xFFFF,
                "readback": {
                    "ok": True,
                    "active_block_count": {"adc": 8, "dac": 8},
                    "tiles": tiles,
                    "blocks": blocks,
                },
            },
        }
        self.assertTrue(_stage33_rfdc_health(snapshot, require_valid=True)["ok"])
        snapshot["rfdc"]["readback"]["blocks"][0]["factor"] = 5
        health = _stage33_rfdc_health(snapshot, require_valid=True)
        self.assertFalse(health["ok"])
        self.assertIn("RFDC_ADC_FACTOR_MISMATCH", health["errors"])

    def test_five_profiles_and_rates(self) -> None:
        expected = {
            (160, "time_only"): (8, 41_600.0),
            (160, "spec_only"): (16, 41_600.0),
            (160, "time_spec"): (24, 83_200.0),
            (320, "time_only"): (8, 83_200.0),
            (320, "spec_only"): (16, 83_200.0),
        }
        for (bandwidth, mode), (flows, payload) in expected.items():
            with self.subTest(bandwidth=bandwidth, mode=mode):
                config = FEngineConfig(sample_rate_msps=bandwidth, mode=mode)
                self.assertEqual(config.flow_count, flows)
                self.assertAlmostEqual(config.expected_packet_rates["combined_t510_udp_payload_mbps"], payload)

    def test_320msps_dual_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "320MS/s"):
            FEngineConfig(sample_rate_msps=320, mode="time_spec")

    def test_production_scope_uses_sample_rate_names(self) -> None:
        scope = T510FEngine.PRODUCTION_SCOPE
        self.assertEqual(
            scope["production_modes"],
            (
                "160MS/s TIME_ONLY",
                "160MS/s SPEC_ONLY",
                "160MS/s TIME_SPEC",
                "320MS/s TIME_ONLY",
                "320MS/s SPEC_ONLY",
            ),
        )
        self.assertTrue(
            any(
                item.startswith("320MS/s TIME_SPEC")
                for item in scope["excluded_from_gate"]
            )
        )
        self.assertNotIn("100MHz", json.dumps(scope))
        self.assertNotIn("200MHz", json.dumps(scope))

    def test_mts_targets_are_exposed_by_real_observation_api(self) -> None:
        signature = inspect.signature(
            T510FEngine.apply_sysref_locked_observation_config
        )
        self.assertEqual(signature.parameters["mts_adc_target_latency"].default, -1)
        self.assertEqual(signature.parameters["mts_dac_target_latency"].default, -1)

    def test_destination_defaults_and_validation(self) -> None:
        config = FEngineConfig()
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
            FEngineConfig(time_destinations=(FlowDestination(),) * 7)

    def test_source_identity_validation(self) -> None:
        config = FEngineConfig(source_ip="10.20.30.40", source_mac="02:AA:BB:CC:DD:EE")
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
                FEngineConfig(**kwargs)

    def test_board_id_validation(self) -> None:
        self.assertEqual(FEngineConfig().board_id, 0)
        self.assertEqual(FEngineConfig(board_id=0xFFFF).board_id, 0xFFFF)
        for board_id in (-1, 0x1_0000):
            with self.subTest(board_id=board_id), self.assertRaisesRegex(ValueError, "board_id"):
                FEngineConfig(board_id=board_id)

    def test_dac_validation_and_band_edges(self) -> None:
        for kwargs in ({"amplitude": -1}, {"rf_frequency_mhz": float("nan")}, {"phase_deg": 181}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                DacChannelConfig(**kwargs)
        edge_160 = tuple(DacChannelConfig(rf_frequency_mhz=value) for value in (120.0, 280.0) + (200.0,) * 6)
        FEngineConfig(sample_rate_msps=160, dac_channels=edge_160)
        with self.assertRaisesRegex(ValueError, "Nyquist"):
            FEngineConfig(sample_rate_msps=160, dac_channels=(DacChannelConfig(rf_frequency_mhz=280.001),) * 8)
        edge_320 = tuple(DacChannelConfig(rf_frequency_mhz=value) for value in (40.0, 360.0) + (200.0,) * 6)
        FEngineConfig(sample_rate_msps=320, mode="spec_only", dac_channels=edge_320)
        with self.assertRaisesRegex(ValueError, "upper bound exclusive"):
            DacChannelConfig(rf_frequency_mhz=1920.0)

    def test_stage33_center_boundaries_and_complete_band_rule(self) -> None:
        for bandwidth, lower, upper in ((160, 80.0, 1840.0), (320, 160.0, 1760.0)):
            mode = "time_only"
            for center in (lower, upper):
                with self.subTest(bandwidth=bandwidth, center=center):
                    tones = (DacChannelConfig(rf_frequency_mhz=center),) * 8
                    FEngineConfig(
                        sample_rate_msps=bandwidth,
                        mode=mode,
                        center_mhz=center,
                        dac_channels=tones,
                    )
            for center in (lower - 0.001, upper + 0.001):
                with self.subTest(bandwidth=bandwidth, rejected=center), self.assertRaisesRegex(ValueError, "center_mhz"):
                    FEngineConfig(sample_rate_msps=bandwidth, mode=mode, center_mhz=center)
        with self.assertRaisesRegex(ValueError, "160..1760"):
            FEngineConfig(sample_rate_msps=320, mode="time_only", center_mhz=100.0)

    def test_frozen_contract_and_frequency_geometry(self) -> None:
        self.assertEqual((TIME_DST_PORT_BASE, SPEC_DST_PORT_BASE), (4300, 4308))
        self.assertEqual((TIME_SRC_PORT_BASE, SPEC_SRC_PORT_BASE), (4000, 4008))
        self.assertEqual((PFB_NCHAN, PFB_TAPS), (4096, 4))
        self.assertEqual((PFB_BLOCK_COUNT, PFB_CHAN_COUNT, PFB_TIME_COUNT), (16, 256, 1))
        for bandwidth, half_span, bin_width in ((160, 80.0, 39_062.5), (320, 160.0, 78_125.0)):
            config = FEngineConfig(sample_rate_msps=bandwidth, mode="spec_only", center_mhz=200.0)
            info = config.nearest_fft_bin()
            self.assertEqual(info["bin_width_hz"], bin_width)
            self.assertAlmostEqual(config.center_mhz - config.sample_rate_hz / 2.0 / 1.0e6, 200.0 - half_span)

    def test_controller_programs_endpoint_table_and_common_nco(self) -> None:
        core = FakeCore()
        controller = FEngineController("overlay/t510_fengine.bit", core=core)  # type: ignore[arg-type]
        time = list(FEngineConfig().time_destinations)
        time[3] = FlowDestination(ip="10.0.1.33", mac="02:11:22:33:44:55", destination_port=5303, source_port=5103)
        config = FEngineConfig(
            sample_rate_msps=160,
            mode="time_only",
            board_id=37,
            source_ip="10.20.30.40",
            source_mac="02:aa:bb:cc:dd:ee",
            time_destinations=tuple(time),
        )
        result = controller.apply(config, fresh_download=False)
        self.assertEqual(core.observation_kwargs["dac_signal_hz"], 200_000_000.0)
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

    def test_prepare_leaves_stream_stopped_and_apply_starts(self) -> None:
        core = FakeCore()
        controller = FEngineController("overlay/t510_fengine.bit", core=core)  # type: ignore[arg-type]
        prepared = controller.prepare(FEngineConfig(), fresh_download=False)
        self.assertFalse(prepared["started"])
        self.assertFalse(core.started)
        self.assertNotIn(("start",), core.events)
        applied = controller.apply(FEngineConfig(), fresh_download=False)
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
                controller = FEngineController("overlay/t510_fengine.bit", core=core)  # type: ignore[arg-type]
                with self.assertRaisesRegex(RuntimeError, "readback mismatch"):
                    controller.apply(FEngineConfig(), fresh_download=False)
                self.assertFalse(core.started)
                self.assertNotIn(("start",), core.events)

    def test_all_24_source_ports_follow_endpoint_rows_and_mode(self) -> None:
        core = FakeCore()
        controller = FEngineController("overlay/t510_fengine.bit", core=core)  # type: ignore[arg-type]
        time = tuple(
            FlowDestination(destination_port=4300 + flow, source_port=12000 + flow)
            for flow in range(8)
        )
        spec = tuple(
            FlowDestination(destination_port=4308 + flow, source_port=22000 + flow)
            for flow in range(16)
        )
        controller.apply(
            FEngineConfig(mode="spec_only", time_destinations=time, spec_destinations=spec),
            fresh_download=False,
        )
        self.assertEqual([row["src_port"] for row in core.endpoints[:8]], list(range(12000, 12008)))
        self.assertEqual([row["src_port"] for row in core.endpoints[8:]], list(range(22000, 22016)))
        self.assertTrue(all(not row["enable"] for row in core.endpoints[:8]))
        self.assertTrue(all(row["enable"] for row in core.endpoints[8:]))
        self.assertEqual(core.source_identity["src_port"], 22000)

    def test_duplicate_active_udp_tuple_warns_without_blocking(self) -> None:
        core = FakeCore()
        controller = FEngineController("overlay/t510_fengine.bit", core=core)  # type: ignore[arg-type]
        time = list(FEngineConfig().time_destinations)
        time[1] = FlowDestination(
            ip=time[0].ip,
            mac=time[0].mac,
            destination_port=time[0].destination_port,
            source_port=time[0].source_port,
        )
        result = controller.apply(
            FEngineConfig(mode="time_only", time_destinations=tuple(time)),
            fresh_download=False,
        )
        self.assertTrue(core.started)
        self.assertEqual(len(result["flow_warnings"]), 1)
        self.assertIn("EP0 and EP1", result["flow_warnings"][0])

    def test_live_dac_apply_mutes_writes_all_lanes_and_restores(self) -> None:
        core = FakeCore()
        controller = FEngineController("overlay/t510_fengine.bit", core=core)  # type: ignore[arg-type]
        controller.config = FEngineConfig()
        channels = tuple(DacChannelConfig(enabled=channel != 7, rf_frequency_mhz=200.0 + channel, amplitude=10 + channel, phase_deg=channel * 5) for channel in range(8))
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
        controller = FEngineController("overlay/t510_fengine.bit", core=core)  # type: ignore[arg-type]
        controller.config = FEngineConfig(board_id=23)
        controller.apply_dac_live(controller.config.dac_channels)
        self.assertEqual(controller.config.board_id, 23)
        self.assertEqual(core.board_calls, 0)

    def test_stateless_live_dac_apply_accepts_explicit_center(self) -> None:
        core = FakeCore()
        controller = FEngineController("overlay/t510_fengine.bit", core=core)  # type: ignore[arg-type]
        channels = tuple(
            DacChannelConfig(rf_frequency_mhz=200.01, phase_deg=channel)
            for channel in range(8)
        )
        result = controller.apply_dac_live(channels, center_mhz=200.0)
        self.assertEqual(result["enable_mask"], 0xFF)
        self.assertEqual(len(result["readback"]["channels"]), 8)
        self.assertIsNone(controller.config)
        self.assertNotIn(("start",), core.events)

    def test_live_dac_rejects_center_that_differs_from_rfdc(self) -> None:
        core = FakeCore()
        controller = FEngineController("overlay/t510_fengine.bit", core=core)  # type: ignore[arg-type]
        with self.assertRaisesRegex(RuntimeError, "RFDC_CENTER_CONFLICT"):
            controller.apply_dac_live(FEngineConfig().dac_channels, center_mhz=201.0)

    def test_dac_register_readback_covers_all_eight_channels(self) -> None:
        core = FakeFEngineFEngine()
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
                core = FakeFEngineFEngine()
                result = core.configure_science(output_mode=mode, start=False)
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

    def test_low_level_t510_control_accepts_global_source_identity(self) -> None:
        core = FakeFEngineFEngine()
        core.configure_science(
            output_mode="time_only",
            src_ip="10.20.30.40",
            src_mac="02:aa:bb:cc:dd:ee",
            start=False,
        )
        self.assertEqual(core.live_kwargs["src_ip"], "10.20.30.40")
        self.assertEqual(core.live_kwargs["src_mac"], "02:aa:bb:cc:dd:ee")

    def test_inactive_endpoint_with_full_config_programs_every_field(self) -> None:
        core = FakeFEngineFEngine()
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
        core = FakeFEngineFEngine()
        result = core.configure_tx_source_identity(
            ip="10.20.30.40",
            mac="02:aa:bb:cc:dd:ee",
            src_port=5010,
        )
        self.assertEqual(result, {"ip": "10.20.30.40", "mac": "02:aa:bb:cc:dd:ee", "src_port": 5010})

    def test_board_id_register_round_trip_and_validation(self) -> None:
        core = FakeFEngineFEngine()
        self.assertEqual(core.configure_board_id(0xBEEF), 0xBEEF)
        self.assertIn((core.regs.BOARD_ID, 0xBEEF), core.ctrl.writes)
        for board_id in (-1, 0x1_0000):
            with self.subTest(board_id=board_id), self.assertRaisesRegex(ValueError, "board_id"):
                core.configure_board_id(board_id)

    def test_low_level_t510_control_rejects_fixed_parameter_override_before_hardware(self) -> None:
        core = object.__new__(T510FEngine)
        with self.assertRaisesRegex(ValueError, "cannot be overridden"):
            core.configure_science(time_dst_port_base=9999)

    def test_clock_recovery_resets_all_eight_rfdc_tiles(self) -> None:
        events: list[str] = []

        class Tile:
            def __init__(self, name: str) -> None:
                self.name = name

            def Reset(self):
                events.append(self.name)
                return 0

        class Rfdc:
            adc_tiles = [Tile(f"adc{index}") for index in range(4)]
            dac_tiles = [Tile(f"dac{index}") for index in range(4)]

        core = object.__new__(T510FEngine)
        core.rfdc = Rfdc()
        calls = core.reset_all_rfdc_tiles()
        self.assertEqual(
            events,
            ["adc0", "adc1", "adc2", "adc3", "dac0", "dac1", "dac2", "dac3"],
        )
        self.assertEqual(len(calls), 8)
        self.assertTrue(all(call["method"] == "Reset" for call in calls))

    def test_scheduled_sync_first_sample_alignment_tracks_active_science_path(self) -> None:
        self.assertEqual(T510FEngine._first_sample0_rule(0, False), (32, 0, 32768))
        self.assertEqual(T510FEngine._first_sample0_rule(1, False), (8, 0, 32768))
        self.assertEqual(T510FEngine._first_sample0_rule(1, True), (8, 4, 32788))
        self.assertEqual(T510FEngine._first_sample0_rule(2, False), (4, 0, 32768))

    def test_low_level_stop_preserves_configuration_and_flushes_both_domains(self) -> None:
        core = FakeFEngineFEngine()
        core.ctrl.values[core.regs.PFB_CONTROL] = 0x1
        core.ctrl.values[core.regs.TX_CONTROL] = 0x1D
        core.stop()
        self.assertEqual(
            core.ctrl.writes[-3:],
            [
                (core.regs.CONTROL, 0x4),
                (core.regs.PFB_CONTROL, 0x3),
                (core.regs.TX_CONTROL, 0x3D),
            ],
        )

    def test_low_level_abort_also_flushes_pre_fix_bitstreams(self) -> None:
        core = FakeFEngineFEngine()
        core.ctrl.values[core.regs.PFB_CONTROL] = 0x1
        core.ctrl.values[core.regs.TX_CONTROL] = 0x16
        core.read_scheduled_sync_status = lambda: {  # type: ignore[method-assign]
            "error": False,
            "selected": False,
        }
        status = core.abort_scheduled_sync(timeout_s=0.01)
        self.assertTrue(status["pipeline_flush"]["tx_clear_pulsed"])
        self.assertEqual(
            core.ctrl.writes[-3:],
            [
                (core.regs.SYNC_COMMAND, 0x4),
                (core.regs.PFB_CONTROL, 0x3),
                (core.regs.TX_CONTROL, 0x36),
            ],
        )

    def test_start_waits_for_accepting_rfdc_path(self) -> None:
        core = LifecycleCore(
            [
                {"streaming": 1, "rfdc_downstream_ready": 0},
                {"streaming": 1, "rfdc_downstream_ready": 1},
            ]
        )
        controller = FEngineController("overlay/t510_fengine.bit", core=core)  # type: ignore[arg-type]
        status = controller.start_immediate(timeout=0.1)
        self.assertTrue(core.started)
        self.assertEqual(status["rfdc_downstream_ready"], 1)

    def test_stop_rejects_stale_science_frame_until_flush_is_visible(self) -> None:
        core = LifecycleCore(
            [
                {
                    "streaming": 0,
                    "time_packet_count": 5,
                    "spec_packet_count": 0,
                    "tx_frame_sent_count": 5,
                    "rfdc_downstream_ready": 1,
                    "tx_cmac_source_mux_locked": 1,
                    "tx_cmac_mux_selected_source": 2,
                },
                {
                    "streaming": 0,
                    "time_packet_count": 5,
                    "spec_packet_count": 0,
                    "tx_frame_sent_count": 5,
                    "rfdc_downstream_ready": 1,
                    "tx_cmac_source_mux_locked": 0,
                    "tx_cmac_mux_selected_source": 0,
                },
            ]
        )
        controller = FEngineController("overlay/t510_fengine.bit", core=core)  # type: ignore[arg-type]
        status = controller.stop_and_verify(settle_seconds=0.01, timeout=0.1)
        self.assertTrue(core.stopped)
        self.assertEqual(status["tx_cmac_source_mux_locked"], 0)

    def test_current_validation_api_and_thin_notebook(self) -> None:
        production = inspect.signature(T510FEngine.run_production_validation)
        self.assertNotIn("expected_core_version", production.parameters)
        self.assertFalse(hasattr(T510FEngine, "run_" + "stage" + "28_validation"))
        path = Path(__file__).resolve().parents[1] / "notebooks" / "00_t510_fengine_control.ipynb"
        notebook = json.loads(path.read_text())
        code = "".join("".join(cell.get("source", [])) for cell in notebook["cells"] if cell.get("cell_type") == "code")
        self.assertLess(len(code), 2000)
        self.assertIn("create_console", code)


if __name__ == "__main__":
    unittest.main()
