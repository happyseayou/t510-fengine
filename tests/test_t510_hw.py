from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock

from python import t510_hw


class FakeHardwareCore:
    def __init__(self, board_id: int = 1) -> None:
        self.board_id = board_id
        self.reset_called = False
        self.sync_prepare_kwargs = None

    def read_status(self):
        return {
            "core_version": 0x00010032,
            "board_id": self.board_id,
            "streaming": 0,
            "science_bandwidth_mode": 0,
            "science_output_mode": 2,
            "pps_count": 44,
            "pps_status_input_high": 1,
            "pps_status_count_nonzero": 1,
            "ref_status_locked": 1,
            "configured_sync_mode": 0,
            "configured_clock_ref": 0,
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
            "science_bandwidth_mhz": 160,
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
            "pfb_taps": 4,
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
                {"kind": "dac", "frequency_mhz": 100.0},
                {"kind": "dac", "frequency_mhz": 100.0},
            ],
        }

    def read_lmk_status(self, *, include_registers=False):
        return {
            "profile_id": "stage32_160_manual_clkin2_continuous",
            "sysref_mode": "continuous",
            "selected_ref": "external_10mhz",
            "lmk_clkin": "CLKin2 (manual)",
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


class FakeController:
    instances = []

    def __init__(self, path):
        self.path = str(path)
        self.core = FakeHardwareCore()
        self.prepared = None
        self.dac_update = None
        type(self).instances.append(self)

    def connect(self, *, download=False):
        self.download = download
        return self.core.read_status()

    def require_core(self):
        return self.core

    def prepare(self, config, *, fresh_download=True, program_dac=False):
        self.prepared = config
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
        return {
            "enable_mask": 0,
            "channels": [
                {
                    "channel": channel,
                    "enabled": False,
                    "rf_frequency_mhz": center_mhz,
                    "amplitude_percent": 0.0,
                    "phase_deg": 0.0,
                }
                for channel in range(8)
            ],
        }

    def start_immediate(self):
        return {"streaming": 1}

    def stop_and_verify(self):
        return {"streaming": 0}

    def apply_dac_live(self, channels, *, center_mhz):
        self.dac_update = (channels, center_mhz)
        return {"enable_mask": 0xFF, "readback": self.read_dac_channels(center_mhz=center_mhz)}


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
        "bitstream_id": "fengine-0x00010032",
        "board_id": 37,
        "profile": {"bandwidth_mhz": 160, "mode": "time_spec", "center_mhz": 100.0},
        "source": {"ip": "10.0.1.1", "mac": "02:00:00:00:00:01"},
        "endpoints": endpoints,
    }


class T510HelperTests(unittest.TestCase):
    def setUp(self) -> None:
        FakeController.instances.clear()
        self.temp = tempfile.TemporaryDirectory()
        self.bitstream = Path(self.temp.name) / "test.bit"
        self.bitstream.write_bytes(b"test-bitstream")
        self.proof = {
            "id": "fengine-0x00010032",
            "path": str(self.bitstream),
            "sha256": hashlib.sha256(b"test-bitstream").hexdigest(),
            "core_version": "0x00010032",
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
            "STAGE32_MTS_STATE_PATH",
            Path(self.temp.name) / "stage32-mts.json",
        )
        self.mts_state.start()
        self.watchdog_path = Path(self.temp.name) / "stage32-ref-watchdog.json"
        self.watchdog_state = mock.patch.object(
            t510_hw,
            "STAGE32_REFERENCE_WATCHDOG_STATE_PATH",
            self.watchdog_path,
        )
        self.watchdog_state.start()
        self._write_watchdog_state()

    def tearDown(self) -> None:
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
    @mock.patch.object(t510_hw, "Stage29Controller", FakeController)
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

    @mock.patch.object(t510_hw, "Stage29Controller", FakeController)
    def test_status_is_one_snapshot_of_cumulative_registers(self) -> None:
        result = t510_hw._status({"bitstream": self.proof, "request": {}})
        self.assertEqual(result["core_version"], "0x00010032")
        self.assertEqual(result["board_id"], 1)
        self.assertEqual(result["counters"]["time_packets"], 100)
        self.assertEqual(result["counters"]["spec_dropped"], 3)
        self.assertNotIn("packets_per_second", result)
        self.assertNotIn("history", result)
        self.assertEqual(result["clock"]["sysref_mode"], "continuous")
        self.assertEqual(result["halfband"]["coefficient_id"], "0xaa160055")
        self.assertEqual(result["channelizer"]["nchan"], 4096)
        self.assertEqual(result["channelizer"]["taps"], 4)
        self.assertEqual(result["channelizer"]["packet_chan_count"], 256)
        self.assertEqual(result["channelizer"]["peak_chan"], 512)
        self.assertEqual(result["channelizer"]["coefficient_id"], "0x50464234")
        self.assertTrue(result["reference_watchdog"]["healthy"])

    @mock.patch.object(t510_hw, "Stage29Controller", FakeController)
    def test_dac_requires_matching_board_and_complete_readback(self) -> None:
        channels = [
            {
                "channel": channel,
                "enabled": True,
                "rf_frequency_mhz": 100.01,
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
                    "center_mhz": 100.0,
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
                        "center_mhz": 100.0,
                        "channels": channels,
                    },
                }
            )

    @mock.patch.object(t510_hw, "Stage29Controller", FakeController)
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

    @mock.patch.object(t510_hw, "Stage29Controller", FakeController)
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

    @mock.patch.object(t510_hw, "Stage29Controller", FakeController)
    def test_arm_fails_closed_when_reference_watchdog_state_is_stale(self) -> None:
        self._write_watchdog_state(
            updated_at_unix_ms=(
                time.time_ns() // 1_000_000
                - t510_hw.STAGE32_REFERENCE_WATCHDOG_MAX_AGE_MS
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

    @mock.patch.object(t510_hw, "Stage29Controller", FakeController)
    def test_stage31_prepare_arm_abort_helpers_preserve_transaction_identity(self) -> None:
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

    @mock.patch.object(t510_hw, "Stage29Controller", FakeController)
    def test_cold_boot_rejects_mmio_before_constructing_controller(self) -> None:
        with (
            mock.patch.object(
                t510_hw,
                "_read_fpga_manager_state",
                return_value="unknown",
            ),
            mock.patch.object(t510_hw, "_load_stage29") as load_stage29,
        ):
            with self.assertRaises(t510_hw.HelperError) as caught:
                t510_hw._status({"bitstream": self.proof, "request": {}})
        self.assertEqual(caught.exception.code, "PL_NOT_CONFIGURED")
        self.assertEqual(caught.exception.exit_code, t510_hw.EXIT_STATE_CONFLICT)
        load_stage29.assert_not_called()
        self.assertEqual(FakeController.instances, [])

    @mock.patch.object(t510_hw, "Stage29Controller", FakeController)
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

    @mock.patch.object(t510_hw, "Stage29Controller", FakeController)
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
        self.assertEqual(result["core_version"], "0x00010032")
        self.assertTrue(FakeController.instances)

    @mock.patch.object(t510_hw, "_record_active_bitstream_state")
    @mock.patch.object(t510_hw, "Stage29Controller", FakeController)
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
