from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import time
import unittest
from unittest import mock

from python import t510_hw


class ClockDiagnosticProfileClassificationTest(unittest.TestCase):
    def test_external_request_profiles_include_frozen_10m_and_5m_phase(self) -> None:
        for profile_id in (
            "160m_10m_request_manual_clkin2",
            "160m_5m_request_manual_clkin2",
            "160m_10m_request_clkin2_sdclkout3_phase_15",
            "160m_5m_request_clkin2_sdclkout3_phase_15",
        ):
            self.assertTrue(
                t510_hw._is_external_request_clock_profile(profile_id), profile_id
            )

    def test_external_request_profiles_exclude_continuous_tcxo_and_bad_phase(self) -> None:
        for profile_id in (
            "160m_10m_cont_manual_clkin2",
            "160m_10m_request_manual_clkin0",
            "160m_10m_request_clkin2_sdclkout3_phase_32",
            "160m_5m_request_clkin2_sdclkout3_phase_xx",
        ):
            self.assertFalse(
                t510_hw._is_external_request_clock_profile(profile_id), profile_id
            )


class FakeHardwareCore:
    def __init__(self, board_id: int = 1) -> None:
        self.board_id = board_id
        self.reset_called = False
        self.sync_prepare_kwargs = None
        self.calibration_frozen = False
        self.ocb1_override = False
        self.clock_ref = "external_10mhz"
        self.clock_profile = "160m_10m_cont_manual_clkin2"

    def read_status(self):
        return {
            "core_version": 0x00010034,
            "board_id": self.board_id,
            "streaming": 0,
            "science_sample_rate_mode": 0,
            "science_output_mode": 2,
            "pps_count": 44,
            "pps_status_input_high": 1,
            "pps_status_count_nonzero": 1,
            "ref_status_locked": 1,
            "configured_sync_mode": 2 if self.clock_ref == "tcxo_10mhz" else 0,
            "configured_clock_ref": 1 if self.clock_ref == "tcxo_10mhz" else 0,
            "tx_link_status_flags": 3,
            "time_packet_count": 100,
            "time_dropped_count": 2,
            "spec_packet_count": 200,
            "spec_dropped_count": 3,
            "tx_frame_built_count": 301,
            "tx_frame_sent_count": 300,
            "tx_frame_dropped_count": 1,
            "tx_route_miss_count": 0,
            "tx_route_error_count": 0,
            "rfdc_dropped_count": 4,
            "rfdc_downstream_ready": 1,
            "science_dropped_beat_count": 5,
            "science_sample_rate_msps": 160,
            "science_antialias_taps": 55,
            "science_antialias_100m_active": 1,
            "science_antialias_100m_primed": 1,
            "science_antialias_coeff_version": 0xAA160055,
            "tx_cmac_source_mux_locked": 0,
            "tx_cmac_mux_selected_source": 0,
            "tx_time_live_bridge_fifo_full": 0,
            "tx_time_live_bridge_fifo_empty": 1,
            "pfb_input_fifo_level": 0,
            "pfb_nchan": 4096,
            "pfb_taps": 8,
            "pfb_chan_count": 256,
            "pfb_time_count": 1,
            "pfb_frame_count": 300,
            "pfb_overflow_count": 0,
            "pfb_data_halt_count": 0,
            "pfb_xfft_event_count": 0,
            "pfb_tile_overflow_count": 0,
            "pfb_xfft_tlast_unexpected_count": 0,
            "pfb_xfft_tlast_missing_count": 0,
            "pfb_xfft_fft_overflow_count": 0,
            "pfb_xfft_data_out_halt_count": 0,
            "pfb_xfft_status_halt_count": 0,
            "pfb_capture_backpressure_count": 0,
            "pfb_frame_sample0_overflow_count": 0,
            "pfb_peak_chan": 512,
            "pfb_peak_power": 123456,
            "pfb_coeff_active_id": 0x50464234,
            "pfb_coeff_error_count": 0,
            "time_sample0": 1234,
            "rfdc_sample_count": 5678,
            "error_flags": 0,
        }

    def read_rfdc_mixer_frequencies(self):
        return {
            "available": True,
            "mixers": [
                {"kind": "dac", "frequency_mhz": 200.0}
                for _ in range(8)
            ],
        }

    def read_lmk_status(self, *, include_registers=False):
        onboard = self.clock_ref == "tcxo_10mhz"
        return {
            "profile_id": self.clock_profile,
            "profile_sha256": "1" * 64,
            "sysref_mode": "request" if onboard else "continuous",
            "sysref_policy": "mts_only" if onboard else "continuous",
            "selected_ref": self.clock_ref,
            "clock_reference": "onboard_tcxo" if onboard else "external_gpsdo",
            "lmk_clkin": "CLKin0 (manual)" if onboard else "CLKin2 (manual)",
            "sysref_request_gpio": 0,
            "sysref_output_expected_on": True,
            "pll1_lock": 1,
            "pll2_lock": 1,
            "configured": True,
            "errors": [],
        }

    def reset(self):
        self.reset_called = True

    def read_scheduled_sync_status(self):
        return {
            "state": 0,
            "current_pps_count": 44,
            "ref_locked": True,
            "rfdc_ready": True,
            "pps_recent": True,
        }

    def prepare_scheduled_sync(self, **kwargs):
        self.sync_prepare_kwargs = dict(kwargs)
        return {"prepared": True, "active_generation": kwargs["generation"]}

    def arm_scheduled_sync(self):
        return {"armed": True}

    def abort_scheduled_sync(self):
        return {"selected": False}

    def read_adc_calibration_status(self, *, require=False):
        mask = 0xFF if self.calibration_frozen else 0
        channels = [
            {
                "adc": adc,
                "tile": adc // 2,
                "block": adc % 2,
                "cal_frozen": self.calibration_frozen,
                "disable_freeze_pin": True,
                "freeze_calibration": self.calibration_frozen,
                "coefficients": {
                    name: [adc * 100 + bank * 10 + index for index in range(8)]
                    for bank, name in enumerate(("ocb1", "ocb2", "gcb", "tscb"))
                },
            }
            for adc in range(8)
        ]
        return {
            "supported": True,
            "frozen_adc_mask": mask,
            "requested_freeze_mask": mask,
            "software_owned_mask": 0xFF,
            "channels": channels,
            "coefficient_sha256": {
                "all": "a" * 64,
                "ocb1": "d" * 64,
                "gcb": "b" * 64,
                "tscb": "c" * 64,
            },
        }

    def set_adc_calibration_freeze(self, freeze):
        self.calibration_frozen = bool(freeze)
        return {
            "requested_freeze": bool(freeze),
            **self.read_adc_calibration_status(require=True),
        }

    def capture_preview_calibration_quiescent(self, *, n, input_mask, timeout):
        assert n == 1024
        assert input_mask == 0xFF
        return {
            "sample0": 1234,
            "sample_rate_hz": 320_000_000,
            "iq": {adc: [(3000 + adc, -3000 - adc)] * n for adc in range(8)},
            "calibration_dry_run": {
                "science_udp_stopped": True,
                "packet_counter_deltas": {
                    "time_packet_count": 0,
                    "spec_packet_count": 0,
                    "tx_frame_sent_count": 0,
                },
            },
        }

    def wait_adc_calibration_convergence(self, **_kwargs):
        return {
            "converged": True,
            "elapsed_seconds": 2.0,
            "trace": [],
            "snapshot": self.read_adc_calibration_status(require=True),
        }

    def set_adc_ocb1_snapshot_override(self):
        self.ocb1_override = True
        calibration = self.read_adc_calibration_status(require=True)
        return {
            "override_adc_mask": 0xFF,
            "snapshot_sha256": calibration["coefficient_sha256"]["ocb1"],
            "current_sha256": calibration["coefficient_sha256"]["ocb1"],
            "channels": [],
            "calibration": calibration,
        }

    def release_adc_ocb1_override(self):
        self.ocb1_override = False
        return {
            "override_adc_mask": 0,
            "calls": [],
            "calibration": self.read_adc_calibration_status(require=True),
        }


class FakeController:
    instances = []

    def __init__(self, path, *, expected_core_version=0x00010034):
        self.path = str(path)
        self.expected_core_version = int(expected_core_version)
        self.core = FakeHardwareCore()
        self.prepared = None
        self.dac_update = None
        self.dac_channels = None
        type(self).instances.append(self)

    def connect(self, *, download=False):
        self.download = download
        return self.core.read_status()

    def require_core(self):
        return self.core

    def prepare(
        self,
        config,
        *,
        fresh_download=True,
        program_dac=False,
        clock_ref="external_10mhz",
        clock_profile="160m_10m_cont_manual_clkin2",
    ):
        self.prepared = config
        self.prepare_clock = {
            "clock_ref": clock_ref,
            "clock_profile": clock_profile,
        }
        self.core.clock_ref = clock_ref
        self.core.clock_profile = clock_profile
        self.core.board_id = config.board_id
        return {
            "status": self.core.read_status(),
            "source_identity": {
                "requested": {
                    "ip": config.source_ip,
                    "mac": config.source_mac,
                    "src_port": 4000,
                },
                "readback": {
                    "ip": config.source_ip,
                    "mac": config.source_mac,
                    "src_port": 4000,
                },
            },
            "endpoint_readback": [{"id": index} for index in range(24)],
        }

    def read_dac_channels(self, *, center_mhz=None):
        configured = self.dac_channels
        if configured is None:
            configured = [
                type(
                    "MutedDac",
                    (),
                    {
                        "enabled": False,
                        "rf_frequency_mhz": center_mhz,
                        "amplitude": 0.0,
                        "amplitude_code": 0,
                        "phase_deg": 0.0,
                    },
                )()
                for _ in range(8)
            ]
        enable_mask = sum(int(channel.enabled) << index for index, channel in enumerate(configured))
        return {
            "enable_mask": enable_mask,
            "channels": [
                {
                    "channel": channel,
                    "enabled": bool(item.enabled),
                    "rf_frequency_mhz": float(item.rf_frequency_mhz),
                    "amplitude_percent": float(item.amplitude),
                    "amplitude_code": int(item.amplitude_code),
                    "phase_deg": float(item.phase_deg),
                }
                for channel, item in enumerate(configured)
            ],
        }

    def start_immediate(self):
        return {"streaming": 1}

    def stop_and_verify(self):
        return {"streaming": 0}

    def apply_dac_live(self, channels, *, center_mhz):
        self.dac_update = (channels, center_mhz)
        self.dac_channels = list(channels)
        readback = self.read_dac_channels(center_mhz=center_mhz)
        return {"enable_mask": readback["enable_mask"], "readback": readback}


def configure_body() -> dict:
    endpoints = []
    for endpoint_id in range(24):
        endpoints.append(
            {
                "endpoint_id": endpoint_id,
                "stream": "TIME" if endpoint_id < 8 else "SPEC",
                "enabled": True,
                "destination_ip": "10.0.1.16",
                "destination_mac": "08:c0:eb:d5:95:b2",
                "source_port": 4000 + endpoint_id,
                "destination_port": 4300 + endpoint_id,
            }
        )
    return {
        "bitstream_id": "fengine-0x00010034",
        "board_id": 37,
        "profile": {"sample_rate_msps": 160, "mode": "time_spec", "center_mhz": 200.0},
        "source": {"ip": "10.0.1.1", "mac": "02:00:00:00:00:01"},
        "endpoints": endpoints,
    }


class T510HelperTests(unittest.TestCase):
    def test_v35_sysref_capture_evidence_proves_running_domains(self) -> None:
        class CaptureCore:
            def __init__(self):
                self.count = 100

            def read_status(self):
                self.count += 500_000
                return {
                    "core_version": 0x00010035,
                    "sysref_pl_edge_count": self.count,
                    "sysref_adc_edge_count": self.count - 1,
                    "sysref_dac_edge_count": self.count - 1,
                    "sysref_pl_capture_level": 1,
                    "sysref_adc_capture_level": 1,
                    "sysref_dac_capture_level": 1,
                }

        core = CaptureCore()
        first = core.read_status()
        result = t510_hw._read_sysref_capture_evidence(
            core,
            first,
            interval_seconds=0.0,
        )
        self.assertTrue(result["supported"])
        self.assertTrue(result["running"])
        self.assertEqual(result["count_deltas"], {
            "pl_160mhz": 500_000,
            "adc_80mhz": 500_000,
            "dac_80mhz": 500_000,
        })

    def test_v35_sysref_capture_evidence_proves_gated_domains(self) -> None:
        class CaptureCore:
            def read_status(self):
                return {
                    "core_version": 0x00010035,
                    "sysref_pl_edge_count": 77,
                    "sysref_adc_edge_count": 77,
                    "sysref_dac_edge_count": 77,
                }

        result = t510_hw._read_sysref_capture_evidence(
            CaptureCore(),
            interval_seconds=0.0,
        )
        self.assertTrue(result["supported"])
        self.assertFalse(result["running"])
        self.assertEqual(set(result["count_deltas"].values()), {0})

    def setUp(self) -> None:
        FakeController.instances.clear()
        self.temp = tempfile.TemporaryDirectory()
        self.bitstream = Path(self.temp.name) / "test.bit"
        self.bitstream.write_bytes(b"test-bitstream")
        self.proof = {
            "id": "fengine-0x00010034",
            "path": str(self.bitstream),
            "sha256": hashlib.sha256(b"test-bitstream").hexdigest(),
            "core_version": "0x00010034",
            "mts_adc_target_latency": 240,
            "mts_dac_target_latency": 224,
        }
        self.fpga_state = mock.patch.object(
            t510_hw,
            "_read_fpga_manager_state",
            return_value="operating",
        )
        self.pynq_state = mock.patch.object(
            t510_hw,
            "_read_pynq_global_pl_state",
            return_value={
                "bitfile_name": str(self.bitstream),
                "bitfile_hash": hashlib.sha1(b"test-bitstream").hexdigest(),
            },
        )
        self.fpga_state.start()
        self.pynq_state.start()
        self.mts_state = mock.patch.object(
            t510_hw,
            "MTS_STATE_PATH",
            Path(self.temp.name) / "mts.json",
        )
        self.mts_state.start()
        self.watchdog_path = Path(self.temp.name) / "ref-watchdog.json"
        self.watchdog_state = mock.patch.object(
            t510_hw,
            "REFERENCE_WATCHDOG_STATE_PATH",
            self.watchdog_path,
        )
        self.watchdog_state.start()
        self.ocb1_state = mock.patch.object(
            t510_hw,
            "OCB1_STATE_PATH",
            Path(self.temp.name) / "ocb1.json",
        )
        self.last_configure = mock.patch.object(
            t510_hw,
            "LAST_CONFIGURE_REQUEST_PATH",
            Path(self.temp.name) / "last-configure.json",
        )
        self.ocb1_state.start()
        self.last_configure.start()
        self.clock_state = mock.patch.object(
            t510_hw,
            "CLOCK_DIAGNOSTIC_STATE_PATH",
            Path(self.temp.name) / "clock-diagnostic.json",
        )
        self.clock_state.start()
        self.output_load_state = mock.patch.object(
            t510_hw,
            "OUTPUT_LOAD_STATE_PATH",
            Path(self.temp.name) / "output-load.json",
        )
        self.rfdc_power_state = mock.patch.object(
            t510_hw,
            "RFDC_POWER_STATE_PATH",
            Path(self.temp.name) / "rfdc-power.json",
        )
        self.output_load_state.start()
        self.rfdc_power_state.start()
        self._write_watchdog_state()

    def tearDown(self) -> None:
        self.rfdc_power_state.stop()
        self.output_load_state.stop()
        self.clock_state.stop()
        self.last_configure.stop()
        self.ocb1_state.stop()
        self.watchdog_state.stop()
        self.pynq_state.stop()
        self.fpga_state.stop()
        self.mts_state.stop()
        self.temp.cleanup()

    def _write_watchdog_state(self, **overrides) -> None:
        state = {
            "schema_version": 1,
            "updated_at_unix_ms": time.time_ns() // 1_000_000,
            "healthy": True,
            "fault_latched": False,
            "mode": "IDLE",
            "active_bitstream_sha1": hashlib.sha1(b"test-bitstream").hexdigest(),
            "lock_status": {"pll1_lock": 1, "pll2_lock": 1},
        }
        state.update(overrides)
        self.watchdog_path.write_text(json.dumps(state), encoding="utf-8")

    @mock.patch.object(t510_hw, "_record_active_bitstream_state")
    @mock.patch.object(t510_hw, "FEngineController", FakeController)
    def test_configure_uses_prepare_and_leaves_stream_stopped(
        self,
        record_active_bitstream_state,
    ) -> None:
        body = configure_body()
        body["profile"]["center_mhz"] = 170.0
        result = t510_hw._configure(
            {"bitstream": self.proof, "request": body}
        )
        controller = FakeController.instances[-1]
        self.assertEqual(controller.prepared.board_id, 37)
        self.assertEqual(controller.prepared.center_mhz, 170.0)
        self.assertEqual(len(controller.prepared.dac_channels), 8)
        self.assertTrue(
            all(
                channel.rf_frequency_mhz == 170.0
                for channel in controller.prepared.dac_channels
            )
        )
        self.assertEqual(controller.prepared.mts_adc_target_latency, 240)
        self.assertEqual(controller.prepared.mts_dac_target_latency, 224)
        self.assertFalse(result["streaming"])
        self.assertEqual(result["board_id"], 37)
        self.assertEqual(len(result["endpoints"]), 24)
        self.assertFalse(result["streaming"])
        record_active_bitstream_state.assert_called_once_with(self.bitstream)

    @mock.patch.object(t510_hw, "_record_active_bitstream_state")
    @mock.patch.object(t510_hw, "FEngineController", FakeController)
    def test_configure_promotes_onboard_tcxo_to_production_state(
        self,
        _record_active_bitstream_state,
    ) -> None:
        body = configure_body()
        body["clock_reference"] = "onboard_tcxo"
        result = t510_hw._configure(
            {"bitstream": self.proof, "request": body}
        )
        controller = FakeController.instances[-1]
        self.assertEqual(
            controller.prepare_clock,
            {
                "clock_ref": "tcxo_10mhz",
                "clock_profile": "160m_10m_request_manual_clkin0",
            },
        )
        self.assertEqual(result["clock_reference"], "onboard_tcxo")
        self.assertEqual(result["clock_diagnostic"]["state"], "PRODUCTION")
        self.assertEqual(
            result["clock_diagnostic"]["profile_id"],
            "160m_10m_request_manual_clkin0",
        )
        self.assertEqual(
            result["clock_diagnostic"]["clock_reference"], "onboard_tcxo"
        )
        self.assertEqual(result["clock_diagnostic"]["sysref_policy"], "mts_only")
        saved = json.loads(t510_hw.LAST_CONFIGURE_REQUEST_PATH.read_text())
        self.assertEqual(saved["request"]["clock_reference"], "onboard_tcxo")

    def test_production_clock_selection_rejects_unknown_reference(self) -> None:
        with self.assertRaisesRegex(t510_hw.HelperError, "clock_reference"):
            t510_hw._production_clock_selection(
                {"clock_reference": "mystery_reference"}
            )

    @mock.patch.object(t510_hw, "FEngineController", FakeController)
    def test_status_is_one_snapshot_of_cumulative_registers(self) -> None:
        result = t510_hw._status({"bitstream": self.proof, "request": {}})
        self.assertEqual(result["core_version"], "0x00010034")
        self.assertEqual(result["board_id"], 1)
        self.assertEqual(result["counters"]["time_packets"], 100)
        self.assertEqual(result["counters"]["spec_dropped"], 3)
        self.assertNotIn("packets_per_second", result)
        self.assertNotIn("history", result)
        self.assertEqual(result["clock"]["sysref_mode"], "continuous")
        self.assertEqual(result["halfband"]["coefficient_id"], "0xaa160055")
        self.assertEqual(result["channelizer"]["nchan"], 4096)
        self.assertEqual(result["channelizer"]["taps"], 8)
        self.assertEqual(result["channelizer"]["packet_chan_count"], 256)
        self.assertEqual(result["channelizer"]["peak_chan"], 512)
        self.assertEqual(result["channelizer"]["coefficient_id"], "0x50464234")
        self.assertEqual(result["rfdc"]["adc_analog_sample_rate_hz"], 3_840_000_000)
        self.assertEqual(result["rfdc"]["dac_analog_sample_rate_hz"], 3_840_000_000)
        self.assertEqual(result["rfdc"]["complex_sample_rate_hz"], 320_000_000)
        self.assertEqual(result["rfdc"]["adc_decimation"], 12)
        self.assertEqual(result["rfdc"]["dac_interpolation"], 12)
        self.assertTrue(result["reference_watchdog"]["healthy"])
        self.assertTrue(result["rfdc"]["calibration"]["supported"])
        self.assertEqual(result["rfdc"]["calibration"]["frozen_adc_mask"], 0)

    @mock.patch.object(t510_hw, "FEngineController", FakeController)
    def test_calibration_freeze_unfreeze_and_stopped_preview_are_all_eight_lane(self) -> None:
        request = {
            "bitstream": self.proof,
            "request": {"expected_board_id": 1},
        }
        frozen = t510_hw._calibration_freeze(request)
        self.assertTrue(frozen["updated"])
        self.assertEqual(frozen["calibration"]["frozen_adc_mask"], 0xFF)
        self.assertEqual(frozen["snapshot"]["rfdc"]["calibration"]["frozen_adc_mask"], 0xFF)
        unfrozen = t510_hw._calibration_unfreeze(request)
        self.assertEqual(unfrozen["calibration"]["frozen_adc_mask"], 0)
        preview = t510_hw._calibration_preview(request)
        self.assertTrue(preview["science_udp_stopped"])
        self.assertEqual(len(preview["channels"]), 8)
        self.assertTrue(all(not item["clipped"] for item in preview["channels"]))

    @mock.patch.object(t510_hw, "FEngineController", FakeController)
    def test_ocb1_transaction_binds_start_release_and_requires_reconfigure(self) -> None:
        request = {"bitstream": self.proof, "request": {}}
        controller = t510_hw._controller(request)
        body = {
            "expected_board_id": 1,
            "receiver_stream_accepting": False,
        }
        snapshot = t510_hw._ocb1_snapshot_override(
            {"bitstream": self.proof, "request": body}
        )
        transaction_id = snapshot["ocb1"]["ocb1_transaction_id"]
        self.assertEqual(snapshot["ocb1"]["ocb1_override_adc_mask"], 0xFF)
        with self.assertRaisesRegex(t510_hw.HelperError, "matching active"):
            t510_hw._require_ocb1_start_authorization(
                controller, {"expected_board_id": 1}
            )
        authorized = t510_hw._require_ocb1_start_authorization(
            controller,
            {
                "expected_board_id": 1,
                "ocb1_transaction_id": transaction_id,
            },
        )
        self.assertTrue(authorized["ocb1_integrity_ok"])
        released = t510_hw._ocb1_release(
            {
                "bitstream": self.proof,
                "request": {
                    **body,
                    "ocb1_transaction_id": transaction_id,
                },
            }
        )
        self.assertEqual(
            released["ocb1"]["ocb1_override_state"],
            t510_hw.OCB1_RECONFIGURE_REQUIRED,
        )
        with self.assertRaisesRegex(t510_hw.HelperError, "complete CONFIGURE"):
            t510_hw._require_ocb1_start_authorization(
                controller, {"expected_board_id": 1}
            )

    @mock.patch.object(t510_hw, "FEngineController", FakeController)
    def test_clock_transaction_binds_start_and_stop_requires_restore(self) -> None:
        controller = t510_hw._controller({"bitstream": self.proof, "request": {}})
        transaction_id = "clock-test-123"
        t510_hw._persist_clock_diagnostic_state(
            {
                "state": "ACTIVE",
                "clock_transaction_id": transaction_id,
                "clock_transaction_valid": True,
                "profile_id": t510_hw.CLOCK_PRODUCTION_PROFILE,
                "profile_sha256": "1" * 64,
                "clock_reference": "external_gpsdo",
                "sysref_policy": "continuous",
            }
        )
        with self.assertRaisesRegex(t510_hw.HelperError, "matching active"):
            t510_hw._require_clock_start_authorization(controller, {})
        authorized = t510_hw._require_clock_start_authorization(
            controller, {"clock_transaction_id": transaction_id}
        )
        self.assertTrue(authorized["integrity_ok"])
        t510_hw._invalidate_clock_diagnostic_state("STOP")
        with self.assertRaisesRegex(t510_hw.HelperError, "restored"):
            t510_hw._require_clock_start_authorization(
                controller, {"clock_transaction_id": transaction_id}
            )

    @mock.patch.object(t510_hw, "FEngineController", FakeController)
    def test_training_freeze_uses_pg269_engineering_window_and_declared_amplitude(self) -> None:
        controller = FakeController(self.bitstream)
        controller.dac_channels = [
            SimpleNamespace(
                enabled=True,
                rf_frequency_mhz=260.0,
                amplitude=100.0,
                amplitude_code=32767,
                phase_deg=0.0,
            )
            for _ in range(8)
        ]
        with mock.patch.object(t510_hw, "_controller", return_value=controller):
            result = t510_hw._calibration_train_freeze(
                {
                    "bitstream": self.proof,
                    "request": {
                        "expected_board_id": 1,
                        "training_dac_active": True,
                        "training_amplitude_percent": 100.0,
                    },
                }
            )
        self.assertTrue(result["trained_and_frozen"])
        self.assertEqual(result["amplitude_percent"], 100.0)
        self.assertEqual(result["level_policy"]["official_min_dbfs"], -40.0)
        self.assertEqual(result["level_policy"]["engineering_min_dbfs"], -36.0)

    @mock.patch.object(t510_hw, "FEngineController", FakeController)
    def test_dac_requires_matching_board_and_complete_readback(self) -> None:
        channels = [
            {
                "channel": channel,
                "enabled": True,
                "rf_frequency_mhz": 200.01,
                "amplitude_percent": 25.0,
                "phase_deg": float(channel),
            }
            for channel in range(8)
        ]
        result = t510_hw._set_dac(
            {
                "bitstream": self.proof,
                "request": {
                    "expected_board_id": 1,
                    "center_mhz": 200.0,
                    "channels": channels,
                },
            }
        )
        self.assertTrue(result["updated"])
        self.assertEqual(len(result["readback"]["channels"]), 8)
        with self.assertRaisesRegex(t510_hw.HelperError, "expected board_id"):
            t510_hw._set_dac(
                {
                    "bitstream": self.proof,
                    "request": {
                        "expected_board_id": 2,
                        "center_mhz": 200.0,
                        "channels": channels,
                    },
                }
            )

    @mock.patch.object(t510_hw, "FEngineController", FakeController)
    def test_start_stop_and_reset_are_semantic_operations(self) -> None:
        request = {"bitstream": self.proof, "request": {"expected_board_id": 1}}
        started = t510_hw._start(request)
        self.assertTrue(started["started"])
        self.assertEqual(started["status"]["streaming"], 1)
        stopped = t510_hw._stop({"bitstream": self.proof, "request": {}})
        self.assertTrue(stopped["stopped"])
        self.assertEqual(stopped["status"]["streaming"], 0)
        self.assertTrue(stopped["snapshot"]["pipeline"]["flush_clean"])
        reset = t510_hw._reset(request)
        self.assertTrue(reset["reset"])
        self.assertTrue(FakeController.instances[-1].core.reset_called)

    @mock.patch.object(t510_hw, "FEngineController", FakeController)
    def test_start_fails_closed_when_reference_watchdog_latched(self) -> None:
        self._write_watchdog_state(
            healthy=False,
            fault_latched=True,
            mode="FAULT_LATCHED",
            lock_status={"pll1_lock": 0, "pll2_lock": 1},
        )
        with self.assertRaises(t510_hw.HelperError) as caught:
            t510_hw._start(
                {
                    "bitstream": self.proof,
                    "request": {"expected_board_id": 1},
                }
            )
        self.assertEqual(caught.exception.code, "REFERENCE_WATCHDOG_NOT_READY")
        self.assertIn("FAULT_LATCHED", caught.exception.details["errors"])
        self.assertIn("PLL1_NOT_LOCKED", caught.exception.details["errors"])

    @mock.patch.object(t510_hw, "FEngineController", FakeController)
    def test_arm_fails_closed_when_reference_watchdog_state_is_stale(self) -> None:
        self._write_watchdog_state(
            updated_at_unix_ms=(
                time.time_ns() // 1_000_000
                - t510_hw.REFERENCE_WATCHDOG_MAX_AGE_MS
                - 1
            )
        )
        with self.assertRaises(t510_hw.HelperError) as caught:
            t510_hw._sync_arm(
                {
                    "bitstream": self.proof,
                    "request": {"expected_board_id": 1},
                }
            )
        self.assertEqual(caught.exception.code, "REFERENCE_WATCHDOG_NOT_READY")
        self.assertIn("STATE_STALE", caught.exception.details["errors"])

    @mock.patch.object(t510_hw, "FEngineController", FakeController)
    def test_scheduled_sync_prepare_arm_abort_helpers_preserve_transaction_identity(self) -> None:
        request = {
            "bitstream": self.proof,
            "request": {
                "expected_board_id": 1,
                "generation": 7,
                "target_pps_count": 50,
                "epoch_tai_seconds": 1784256005,
                "first_sample0": 32788,
                "observation_tag": 0x1234,
                "signal_chain_tag": 0x5A31C004,
                "schedule_tag": 0x31,
                "mts_result_id": 0xAA55,
            },
        }
        prepared = t510_hw._sync_prepare(request)
        self.assertTrue(prepared["prepared"])
        kwargs = FakeController.instances[-1].core.sync_prepare_kwargs
        self.assertEqual(kwargs["generation"], 7)
        self.assertEqual(kwargs["signal_chain_tag"], 0x5A31C004)
        self.assertEqual(kwargs["first_sample0"], 32788)
        self.assertTrue(
            t510_hw._sync_arm(
                {"bitstream": self.proof, "request": {"expected_board_id": 1}}
            )["armed"]
        )
        self.assertTrue(
            t510_hw._sync_abort(
                {"bitstream": self.proof, "request": {"expected_board_id": 1}}
            )["aborted"]
        )

    @mock.patch.object(t510_hw, "FEngineController", FakeController)
    def test_scheduled_sync_rejects_onboard_tcxo_free_run(self) -> None:
        controller = t510_hw._controller(
            {"bitstream": self.proof, "request": {}}
        )
        controller.core.clock_ref = "tcxo_10mhz"
        with mock.patch.object(t510_hw, "_controller", return_value=controller):
            with self.assertRaises(t510_hw.HelperError) as caught:
                t510_hw._sync_prepare(
                    {
                        "bitstream": self.proof,
                        "request": {
                            "expected_board_id": 1,
                            "generation": 7,
                            "target_pps_count": 50,
                            "epoch_tai_seconds": 1784256005,
                            "signal_chain_tag": 1,
                            "mts_result_id": 1,
                        },
                    }
                )
        self.assertEqual(
            caught.exception.code,
            "SCHEDULED_SYNC_REQUIRES_EXTERNAL_REFERENCE",
        )

    def test_stdout_protocol_is_exactly_one_json_object(self) -> None:
        original = t510_hw.COMMANDS["status"]
        t510_hw.COMMANDS["status"] = lambda request: {"streaming": False}
        try:
            stdout = io.StringIO()
            with mock.patch("sys.stdin", io.StringIO("{}")), mock.patch(
                "sys.stdout", stdout
            ):
                exit_code = t510_hw.main(["status"])
        finally:
            t510_hw.COMMANDS["status"] = original
        self.assertEqual(exit_code, 0)
        lines = stdout.getvalue().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0]), {"ok": True, "result": {"streaming": False}})

    def test_bad_sha_is_rejected_before_hardware_access(self) -> None:
        proof = {**self.proof, "sha256": "0" * 64}
        with self.assertRaisesRegex(t510_hw.HelperError, "SHA256"):
            t510_hw._configure({"bitstream": proof, "request": configure_body()})

    @mock.patch.object(t510_hw, "FEngineController", FakeController)
    def test_cold_boot_rejects_mmio_before_constructing_controller(self) -> None:
        with (
            mock.patch.object(
                t510_hw,
                "_read_fpga_manager_state",
                return_value="unknown",
            ),
            mock.patch.object(t510_hw, "_load_control") as load_t510_control,
        ):
            with self.assertRaises(t510_hw.HelperError) as caught:
                t510_hw._status({"bitstream": self.proof, "request": {}})
        self.assertEqual(caught.exception.code, "PL_NOT_CONFIGURED")
        self.assertEqual(caught.exception.exit_code, t510_hw.EXIT_STATE_CONFLICT)
        load_t510_control.assert_not_called()
        self.assertEqual(FakeController.instances, [])

    @mock.patch.object(t510_hw, "FEngineController", FakeController)
    def test_active_bitstream_mismatch_rejects_mmio(self) -> None:
        with mock.patch.object(
            t510_hw,
            "_read_pynq_global_pl_state",
            return_value={
                "bitfile_name": "/tmp/other.bit",
                "bitfile_hash": "0" * 40,
            },
        ):
            with self.assertRaises(t510_hw.HelperError) as caught:
                t510_hw._start(
                    {
                        "bitstream": self.proof,
                        "request": {"expected_board_id": 1},
                    }
                )
        self.assertEqual(caught.exception.code, "ACTIVE_BITSTREAM_MISMATCH")
        self.assertEqual(FakeController.instances, [])

    @mock.patch.object(t510_hw, "FEngineController", FakeController)
    def test_matching_active_hash_accepts_release_path_alias(self) -> None:
        with mock.patch.object(
            t510_hw,
            "_read_pynq_global_pl_state",
            return_value={
                "bitfile_name": "/home/xilinx/bringup/alias.bit",
                "bitfile_hash": hashlib.sha1(b"test-bitstream").hexdigest(),
            },
        ):
            result = t510_hw._status({"bitstream": self.proof, "request": {}})
        self.assertEqual(result["core_version"], "0x00010034")
        self.assertTrue(FakeController.instances)

    @mock.patch.object(t510_hw, "_record_active_bitstream_state")
    @mock.patch.object(t510_hw, "FEngineController", FakeController)
    def test_configure_is_allowed_when_pl_is_not_configured(
        self,
        record_active_bitstream_state,
    ) -> None:
        with mock.patch.object(
            t510_hw,
            "_read_fpga_manager_state",
            return_value="unknown",
        ) as read_state:
            result = t510_hw._configure(
                {"bitstream": self.proof, "request": configure_body()}
            )
        self.assertEqual(result["board_id"], 37)
        self.assertTrue(FakeController.instances)
        read_state.assert_not_called()
        record_active_bitstream_state.assert_called_once_with(self.bitstream)

    def test_successful_configure_records_resolved_bitstream_hash_atomically(self) -> None:
        state_path = Path(self.temp.name) / "global_pl_state.json"
        state_path.write_text(
            json.dumps(
                {
                    "bitfile_name": "/old/release.bit",
                    "bitfile_hash": "0" * 40,
                    "active_name": "T510",
                    "shutdown_ips": {"keep": {"name": "keep", "base_addr": 4096}},
                    "psddr": {"size": 1234},
                }
            ),
            encoding="utf-8",
        )
        with mock.patch.object(
            t510_hw,
            "_pynq_global_state_path",
            return_value=state_path,
        ):
            t510_hw._record_active_bitstream_state(self.bitstream)
        state = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertEqual(state["bitfile_name"], str(self.bitstream.resolve()))
        self.assertEqual(
            state["bitfile_hash"],
            hashlib.sha1(b"test-bitstream").hexdigest(),
        )
        self.assertEqual(state["shutdown_ips"]["keep"]["base_addr"], 4096)
        self.assertEqual(state["psddr"]["size"], 1234)
        self.assertFalse(state_path.with_name(".global_pl_state.json.tmp").exists())


if __name__ == "__main__":
    unittest.main()
