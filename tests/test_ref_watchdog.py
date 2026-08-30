from __future__ import annotations

from pathlib import Path
import json
import tempfile
import unittest
from unittest import mock

from python import t510_hw
from python.t510_clock import T510ClockController
from python.t510_ref_watchdog import (
    BoundedJsonlRing,
    ReferenceWatchdog,
    WatchdogPolicy,
    _periodic_schedule_due,
)


class _FakeRegisters:
    STATUS = 0x10
    TIME_PACKET_COUNT = 0x14
    SPEC_PACKET_COUNT = 0x18
    SYSREF_PL_EDGE_COUNT = 0x30
    SYSREF_ADC_EDGE_COUNT = 0x34
    SYSREF_DAC_EDGE_COUNT = 0x38


class _FakeControl:
    def __init__(self) -> None:
        self.streaming = True
        self.time_packets = 100
        self.spec_packets = 200
        self.sysref_count = 1000

    def read(self, register: int) -> int:
        if register == _FakeRegisters.STATUS:
            return 0x2 if self.streaming else 0
        if register == _FakeRegisters.TIME_PACKET_COUNT:
            return self.time_packets
        if register == _FakeRegisters.SPEC_PACKET_COUNT:
            return self.spec_packets
        if register in (
            _FakeRegisters.SYSREF_PL_EDGE_COUNT,
            _FakeRegisters.SYSREF_ADC_EDGE_COUNT,
            _FakeRegisters.SYSREF_DAC_EDGE_COUNT,
        ):
            return self.sysref_count
        raise AssertionError(f"unexpected register {register}")


class _FakeCore:
    def __init__(self) -> None:
        self.regs = _FakeRegisters()
        self.ctrl = _FakeControl()
        self.stop_calls = 0

    def stop(self) -> None:
        self.stop_calls += 1
        self.ctrl.streaming = False

    def read_status(self):
        return {
            "streaming": int(self.ctrl.streaming),
            "rfdc_downstream_ready": 1,
            "tx_time_live_bridge_fifo_full": 0,
            "tx_cmac_source_mux_locked": 0,
            "tx_cmac_mux_selected_source": 0,
        }

    def _adc_calibration_blocks(self):
        return [(tile, block) for tile in range(4) for block in range(2)]

    def read_adc_calibration_status(self, *, require=False, _blocks=None):
        self.asserted_blocks = list(_blocks or [])
        return {
            "supported": True,
            "frozen_adc_mask": 0xFF,
            "requested_freeze_mask": 0xFF,
            "software_owned_mask": 0xFF,
            "channels": [],
            "coefficient_sha256": {
                "ocb1": "1" * 64,
                "ocb2": "2" * 64,
                "gcb": "3" * 64,
                "tscb": "4" * 64,
                "all": "5" * 64,
            },
        }


class ReferenceWatchdogPolicyTests(unittest.TestCase):
    def test_power_thermal_jsonl_ring_has_epoch_sequence_and_bounded_window(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "telemetry.jsonl"
            ring = BoundedJsonlRing(path, capacity=4, compaction_slack=2)
            first_epoch = ring.epoch_id
            for value in range(6):
                row = ring.append({"value": value})
                self.assertEqual(row["sequence"], value + 1)
                self.assertEqual(row["epoch_id"], first_epoch)
            lines = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual([row["sequence"] for row in lines], [2, 3, 4, 5, 6])
            self.assertLessEqual(len(lines), ring.capacity + ring.compaction_slack - 1)
            restarted = BoundedJsonlRing(path, capacity=4, compaction_slack=2)
            self.assertNotEqual(restarted.epoch_id, first_epoch)
            self.assertEqual(path.read_text(), "")

    def test_full_lmk_readback_keeps_stage34c2r_phase_identity_registers(self) -> None:
        self.assertIn(0x10C, T510ClockController.KEY_REGISTERS)
        self.assertIn(0x10D, T510ClockController.KEY_REGISTERS)

    def test_periodic_schedule_does_not_accumulate_callback_jitter(self) -> None:
        due, anchor = _periodic_schedule_due(100.0, float("-inf"), 1.0)
        self.assertTrue(due)
        self.assertEqual(anchor, 100.0)

        due, anchor = _periodic_schedule_due(101.08, anchor, 1.0)
        self.assertTrue(due)
        self.assertEqual(anchor, 101.0)

        due, unchanged = _periodic_schedule_due(101.98, anchor, 1.0)
        self.assertFalse(due)
        self.assertEqual(unchanged, 101.0)

        due, anchor = _periodic_schedule_due(102.02, unchanged, 1.0)
        self.assertTrue(due)
        self.assertEqual(anchor, 102.0)

    def test_idle_unlock_does_not_latch_but_blocks_health_externally(self) -> None:
        policy = WatchdogPolicy(unlock_confirmations=2)
        self.assertIsNone(
            policy.observe(streaming=False, pll1_lock=0, pll2_lock=1)
        )
        self.assertFalse(policy.fault_latched)
        self.assertEqual(policy.pll1_unlock_count, 0)

    def test_two_active_pll1_unlock_samples_trip(self) -> None:
        policy = WatchdogPolicy(unlock_confirmations=2)
        self.assertIsNone(
            policy.observe(streaming=True, pll1_lock=0, pll2_lock=1)
        )
        self.assertEqual(
            policy.observe(streaming=True, pll1_lock=0, pll2_lock=1),
            "LMK_PLL1_UNLOCKED",
        )
        self.assertTrue(policy.fault_latched)

    def test_good_sample_clears_transient_unlock_confirmation(self) -> None:
        policy = WatchdogPolicy(unlock_confirmations=2)
        policy.observe(streaming=True, pll1_lock=0, pll2_lock=1)
        self.assertIsNone(
            policy.observe(streaming=True, pll1_lock=1, pll2_lock=1)
        )
        self.assertEqual(policy.pll1_unlock_count, 0)
        self.assertFalse(policy.fault_latched)

    def test_sustained_spi_error_trips_fail_safe(self) -> None:
        policy = WatchdogPolicy(spi_error_confirmations=3)
        for _ in range(2):
            self.assertIsNone(
                policy.observe(
                    streaming=True,
                    pll1_lock=None,
                    pll2_lock=None,
                    spi_error=True,
                )
            )
        self.assertEqual(
            policy.observe(
                streaming=True,
                pll1_lock=None,
                pll2_lock=None,
                spi_error=True,
            ),
            "LMK_SPI_UNAVAILABLE",
        )

    def test_fresh_configure_clears_fault_latch(self) -> None:
        policy = WatchdogPolicy(unlock_confirmations=2)
        policy.observe(streaming=True, pll1_lock=0, pll2_lock=1)
        policy.observe(streaming=True, pll1_lock=0, pll2_lock=1)
        self.assertTrue(policy.fault_latched)
        policy.clear_for_fresh_configure()
        self.assertFalse(policy.fault_latched)
        self.assertEqual(policy.pll1_unlock_count, 0)

    def test_lmk_lock_status_decodes_digital_lock_bits(self) -> None:
        clock = T510ClockController()
        with mock.patch.object(
            clock,
            "read_registers",
            return_value={"0x182": 0x02, "0x183": 0x00},
        ):
            status = clock.read_lock_status()
        self.assertEqual(status["pll1_lock"], 1)
        self.assertEqual(status["pll2_lock"], 0)
        self.assertEqual(status["reg_0x182"], 0x02)

    def test_trip_directly_stops_and_records_flush_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            bitfile = Path(directory) / "test.bit"
            bitfile.write_bytes(b"watchdog-test-bit")
            watchdog = ReferenceWatchdog(
                bitfile=bitfile,
                state_path=Path(directory) / "state.json",
                interval_seconds=0.1,
                stop_timeout_seconds=0.5,
                unlock_confirmations=2,
                spi_error_confirmations=5,
            )
            core = _FakeCore()
            watchdog.core = core
            watchdog.pl_identity = "sha1:timestamp"
            watchdog.hardware = {
                "streaming": True,
                "selected": True,
                "generation": 17,
                "time_packets": 100,
                "spec_packets": 200,
            }
            watchdog.lock_status = {"pll1_lock": 0, "pll2_lock": 1}
            watchdog._trip("LMK_PLL1_UNLOCKED")
        self.assertEqual(core.stop_calls, 1)
        self.assertIsNotNone(watchdog.last_fault)
        self.assertTrue(watchdog.last_fault["stop_ok"])
        self.assertFalse(watchdog.last_fault["after"]["streaming"])
        self.assertTrue(watchdog.last_fault["after"]["flush_clean"])

    def test_configure_guard_pauses_watchdog_hardware_reads(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bitfile = root / "test.bit"
            bitfile.write_bytes(b"watchdog-test-bit")
            configure_lock = root / "configure.lock"
            watchdog = ReferenceWatchdog(
                bitfile=bitfile,
                state_path=root / "state.json",
                interval_seconds=0.1,
                stop_timeout_seconds=0.5,
                unlock_confirmations=2,
                spi_error_confirmations=5,
                configure_lock_path=configure_lock,
            )
            with mock.patch.object(
                t510_hw,
                "CONFIGURE_LOCK_PATH",
                configure_lock,
            ):
                with t510_hw._configure_hardware_guard(True):
                    with watchdog._configure_read_guard() as read_allowed:
                        self.assertFalse(read_allowed)
            with watchdog._configure_read_guard() as read_allowed:
                self.assertTrue(read_allowed)

    def test_resident_watchdog_publishes_one_second_calibration_observation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            bitfile = Path(directory) / "test.bit"
            bitfile.write_bytes(b"watchdog-test-bit")
            watchdog = ReferenceWatchdog(
                bitfile=bitfile,
                state_path=Path(directory) / "state.json",
                interval_seconds=0.1,
                stop_timeout_seconds=0.5,
                unlock_confirmations=2,
                spi_error_confirmations=5,
            )
            core = _FakeCore()
            watchdog.core = core
            watchdog._sample_calibration_if_due()
            first = watchdog.calibration_observation
            watchdog._sample_calibration_if_due()
        self.assertTrue(first["supported"])
        self.assertEqual(first["frozen_adc_mask"], 0xFF)
        self.assertEqual(first["coefficient_sha256"]["gcb"], "3" * 64)
        self.assertEqual(
            core.asserted_blocks,
            [(tile, block) for tile in range(4) for block in range(2)],
        )

    def test_v35_watchdog_rejects_sysref_edges_during_mts_only_science(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bitfile = root / "test.bit"
            bitfile.write_bytes(b"watchdog-test-bit")
            clock_state = root / "clock.json"
            clock_state.write_text('{"sysref_policy":"mts_only"}\n')
            watchdog = ReferenceWatchdog(
                bitfile=bitfile,
                state_path=root / "state.json",
                interval_seconds=0.1,
                stop_timeout_seconds=0.5,
                unlock_confirmations=2,
                spi_error_confirmations=5,
                expected_core_version=0x00010035,
                clock_diagnostic_state_path=clock_state,
            )
            previous = {
                "streaming": True,
                "sysref_capture_counts": {
                    "pl_160mhz": 10,
                    "adc_80mhz": 10,
                    "dac_80mhz": 10,
                },
            }
            current = {
                "streaming": True,
                "sysref_capture_counts": {
                    "pl_160mhz": 11,
                    "adc_80mhz": 11,
                    "dac_80mhz": 11,
                },
            }
            self.assertEqual(
                watchdog._observe_sysref_capture(previous, current),
                "SYSREF_CAPTURE_DURING_SCIENCE",
            )


if __name__ == "__main__":
    unittest.main()
