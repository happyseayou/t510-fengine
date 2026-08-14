import argparse
import json
import math
from pathlib import Path
import struct
import tempfile
import unittest
from unittest import mock

from scripts import t510_fullband_spur_scan as scan
from scripts.t510_plot_spec_udp_pcap import collect_spectra


def _spec_frame(block: int, packet_index: int, *, break_sample0: bool = False) -> bytes:
    seq_no = 1000 + packet_index * 16 + block
    frame_id = 2000 + packet_index * 16 + block
    sample0 = 3000 + packet_index * 4096 + (1 if break_sample0 and packet_index else 0)
    words = [0] * 16
    words[0] = (0x54353130 << 32) | (2 << 16) | 128
    words[1] = 1 << 48
    words[4] = sample0
    words[5] = frame_id
    words[6] = (seq_no << 32) | (block * 256)
    words[7] = (256 << 48) | (1 << 32) | (8 << 16)
    words[8] = 8192
    words[9] = (4096 << 32) | (block << 16) | 16
    words[10] = (8 << 48) | (0x556 << 32)
    words[11] = 320_000_000 << 32
    payload = struct.pack("<16Q", *words) + struct.pack("<4096h", *([100, -50] * 2048))
    udp = struct.pack("!HHHH", 12000, 4308 + block, 8 + len(payload), 0) + payload
    ip = bytearray(20)
    ip[0] = 0x45
    struct.pack_into("!H", ip, 2, 20 + len(udp))
    ip[8] = 64
    ip[9] = 17
    ethernet = bytes(12) + struct.pack("!H", 0x0800)
    return ethernet + bytes(ip) + udp


def _write_pcap(path: Path, frames: list[bytes]) -> None:
    data = bytearray(struct.pack("<IHHIIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 1))
    for index, frame in enumerate(frames):
        data += struct.pack("<IIII", 1, index, len(frame), len(frame))
        data += frame
    path.write_bytes(data)


class FullBandSpurScanTests(unittest.TestCase):
    def test_receiver_ring_capture_writes_one_raw_pcap(self) -> None:
        pcap = struct.pack("<IHHIIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 1)
        with tempfile.TemporaryDirectory() as temp, mock.patch.object(
            scan, "_http_bytes", return_value=pcap
        ) as request:
            paths, metadata = scan.capture_receiver_pcap(
                receiver_base="http://receiver:8089",
                local_dir=Path(temp),
                packets_per_block=32,
            )
            self.assertEqual(paths, [Path(temp) / "spec_4308_4323.pcap"])
            self.assertEqual(paths[0].read_bytes(), pcap)
            self.assertEqual(metadata["method"], "receiver_packet_mmap_raw_export")
            request.assert_called_once_with(
                "http://receiver:8089/api/capture/spec-pcap",
                method="POST",
                body={"packets_per_block": 32},
                timeout=20.0,
            )

    def test_campaign_grid_and_preflight_order(self) -> None:
        windows = scan.campaign_windows()
        self.assertEqual(len(windows), 63)
        self.assertEqual(scan.scan_centers(), tuple(float(value) for value in range(160, 1761, 80)))
        self.assertEqual(
            [(row["condition"], row["center_mhz"]) for row in windows[:3]],
            [("muted", 160.0), ("tone_25", 160.0), ("tone_100", 160.0)],
        )
        self.assertEqual(
            sorted({row["tone_mhz"] for row in windows if row["tone_mhz"] is not None}),
            [float(value) for value in range(100, 1701, 80)],
        )
        self.assertEqual(sum(row["condition"] == "muted" for row in windows), 21)
        self.assertEqual(sum(row["condition"] == "tone_25" for row in windows), 21)
        self.assertEqual(sum(row["condition"] == "tone_100" for row in windows), 21)

    def test_resume_accepts_only_a_successful_prefix_and_rebuilds_decode(self) -> None:
        windows = scan.campaign_windows()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            local_dir = root / "raw" / "muted" / "center_0160mhz"
            local_dir.mkdir(parents=True)
            (local_dir / "spec_4308_4323.pcap").write_bytes(b"pcap")
            campaign = root / "campaign.json"
            campaign.write_text(
                json.dumps(
                    {
                        "classification": "T510_FULLBAND_SPUR_SCAN_FAIL",
                        "errors": ["old failure"],
                        "windows": [
                            {
                                **windows[0],
                                "name": "muted_center_0160mhz",
                                "ok": True,
                                "local_dir": str(local_dir),
                            }
                        ],
                    }
                )
            )
            power = [[-100.0] * 4096 for _ in range(8)]
            with mock.patch.object(
                scan, "decode_window", return_value={"power_dbfs": power, "capture": {}}
            ) as decode:
                evidence, decoded, completed = scan._resume_campaign(campaign, windows)
            self.assertEqual(completed, 1)
            self.assertEqual(len(decoded), 1)
            self.assertEqual(evidence["errors"], [])
            self.assertEqual(evidence["resume_history"][0]["errors"], ["old failure"])
            decode.assert_called_once_with([local_dir / "spec_4308_4323.pcap"])

            damaged = json.loads(campaign.read_text())
            damaged["windows"][0]["name"] = "tone_25_center_0160mhz"
            campaign.write_text(json.dumps(damaged))
            with self.assertRaisesRegex(RuntimeError, "successful prefix"):
                scan._resume_campaign(campaign, windows)

    def test_dbfs_and_frequency_math(self) -> None:
        self.assertAlmostEqual(scan.db_code_to_dbfs(20.0 * math.log10(32768.0)), 0.0)
        self.assertEqual(scan.CARRIER_SIGNED_BIN * scan.BIN_WIDTH_MHZ, -60.0)
        self.assertEqual(scan.first_nyquist_fold_mhz(2000.0), 1840.0)
        self.assertEqual(scan.circular_bin_distance(0, 4095), 1)

    def test_overlap_stitch_is_linear_power_median(self) -> None:
        powers_a = [[-80.0] * 4096 for _ in range(8)]
        powers_b = [[-70.0] * 4096 for _ in range(8)]
        windows = [
            {"center_mhz": 800.0, "power_dbfs": powers_a},
            {"center_mhz": 880.0, "power_dbfs": powers_b},
        ]
        stitched = scan.stitch_muted(windows)
        global_bin = round(840.0 / scan.BIN_WIDTH_MHZ)
        expected = 10.0 * math.log10((10.0 ** -8 + 10.0 ** -7) / 2.0)
        self.assertAlmostEqual(stitched[0][global_bin], expected, places=9)

    def test_spur_requires_two_internal_window_reproductions(self) -> None:
        global_bin = round(1000.0 / scan.BIN_WIDTH_MHZ)
        stitched = [[-90.0] * scan.FULL_BAND_BINS for _ in range(8)]
        stitched[0][global_bin] = -70.0
        windows = []
        for center in (960.0, 1040.0):
            powers = [[-90.0] * 4096 for _ in range(8)]
            local_bin = (global_bin - round(center / scan.BIN_WIDTH_MHZ)) % 4096
            powers[0][local_bin] = -70.0
            windows.append({"center_mhz": center, "power_dbfs": powers})
        rows = scan.find_spurs(stitched, windows)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["reproduced_window_count"], 2)
        rows = scan.find_spurs(stitched, windows[:1])
        self.assertEqual(rows, [])

    def test_tone_guard_and_amplitude_linearity(self) -> None:
        metrics = []
        for center in scan.CENTERS_MHZ:
            for lane in range(8):
                metrics.extend(
                    [
                        {
                            "condition": "tone_25",
                            "center_mhz": center,
                            "lane": lane,
                            "carrier_dbfs": -20.0,
                            "worst_spur_dbc": -60.0,
                        },
                        {
                            "condition": "tone_100",
                            "center_mhz": center,
                            "lane": lane,
                            "carrier_dbfs": -7.96,
                            "worst_spur_dbc": -55.0,
                        },
                    ]
                )
        rows = scan.amplitude_linearity(metrics)
        self.assertEqual(len(rows), 168)
        self.assertTrue(all(abs(row["increase_db"] - 12.04) < 1.0e-9 for row in rows))
        power = [[-100.0] * 4096 for _ in range(8)]
        for lane in range(8):
            power[lane][scan.CARRIER_BIN] = -10.0
            power[lane][(scan.CARRIER_BIN + 3) % 4096] = -11.0
            power[lane][123] = -40.0
        row = scan.tone_metrics(
            [{
                "condition": "tone_25",
                "amplitude_percent": 25.0,
                "center_mhz": 160.0,
                "tone_mhz": 100.0,
                "power_dbfs": power,
            }]
        )[0]
        self.assertEqual(row["worst_spur_bin"], 123)
        self.assertEqual(row["worst_spur_dbc"], -30.0)

    def test_raw_pcap_reassembly_and_continuity(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            paths = []
            for block in range(16):
                path = root / f"spec_{4308 + block}.pcap"
                _write_pcap(path, [_spec_frame(block, 0), _spec_frame(block, 1)])
                paths.append(path)
            capture = collect_spectra(paths)
            self.assertEqual(capture["packet_count"], 32)
            self.assertEqual(capture["block_packets"], [2] * 16)
            self.assertEqual(capture["continuity_checks"], 16)
            self.assertEqual(capture["pfb_taps"], 8)
            bad = root / "spec_4308.pcap"
            _write_pcap(bad, [_spec_frame(0, 0), _spec_frame(0, 1, break_sample0=True)])
            with self.assertRaisesRegex(ValueError, "continuity mismatch"):
                collect_spectra(paths)

    def test_failure_always_stops_and_mutes_dac(self) -> None:
        calls = []

        def fake_http(url, *, method="GET", body=None, timeout=30.0):
            calls.append((url, method, body))
            if url.endswith("/api/v2/configure"):
                return {"snapshot": {"core_version": "0x00010034"}}
            if url.endswith("/api/v2/status"):
                return {
                    "streaming": True,
                    "core_version": "0x00010034",
                    "profile": {"mode": "spec_only", "sample_rate_msps": 320, "center_mhz": 160.0},
                    "channelizer": {"nchan": 4096, "taps": 8, "coefficient_id": "0x34a80001"},
                }
            if url.endswith("/api/state"):
                return {"stats": {}}
            return {}

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            template = root / "configure.json"
            template.write_text(json.dumps({"endpoints": []}))
            args = argparse.Namespace(
                output=root / "evidence",
                configure_template=template,
                receiver_base="http://receiver",
                agent_base="http://agent",
                packets_per_port=32,
                settle_seconds=0.5,
            )
            with mock.patch.object(scan, "_http_json", side_effect=fake_http), mock.patch.object(
                scan, "capture_receiver_pcap", side_effect=RuntimeError("capture failed")
            ), mock.patch.object(scan.time, "sleep"):
                self.assertEqual(scan.run_campaign(args), 1)
            evidence = json.loads((args.output / "campaign.json").read_text())
            self.assertEqual(evidence["classification"], "T510_FULLBAND_SPUR_SCAN_FAIL")
            self.assertTrue(any("capture failed" in error for error in evidence["errors"]))
        dac_calls = [body for url, method, body in calls if url.endswith("/api/v2/dac")]
        self.assertFalse(dac_calls[-1]["channels"][0]["enabled"])
        stop_calls = [(method, body) for url, method, body in calls if url.endswith("/api/v2/stop")]
        self.assertEqual(stop_calls[-1], ("POST", None))

    def test_final_shutdown_uses_fault_state_board_identity(self) -> None:
        calls = []
        status_count = 0

        def fake_http(url, *, method="GET", body=None, timeout=30.0):
            nonlocal status_count
            calls.append((url, method, body))
            if url.endswith("/api/v2/status"):
                status_count += 1
                return {
                    "board_id": 0,
                    "streaming": False,
                    "profile": {"center_mhz": 1500.0},
                    "pipeline": {"stream_accepting": False},
                    "dac": {
                        "enable_mask": 1 if status_count == 1 else 0,
                        "channels": [
                            {
                                "enabled": status_count == 1 and lane == 0,
                                "amplitude_code": 1 if status_count == 1 and lane == 0 else 0,
                            }
                            for lane in range(8)
                        ],
                    },
                }
            return {}

        args = argparse.Namespace(agent_base="http://agent")
        with mock.patch.object(scan, "_http_json", side_effect=fake_http):
            self.assertEqual(scan._final_stop_and_mute(args, 1200.0), [])
        dac = next(body for url, method, body in calls if url.endswith("/api/v2/dac"))
        self.assertEqual(dac["expected_board_id"], 0)
        self.assertEqual(dac["center_mhz"], 1500.0)
        self.assertTrue(all(not channel["enabled"] for channel in dac["channels"]))
        self.assertEqual(status_count, 2)

    def test_final_shutdown_skips_redundant_dac_write_when_readback_is_safe(self) -> None:
        calls = []

        def fake_http(url, *, method="GET", body=None, timeout=30.0):
            calls.append((url, method, body))
            if url.endswith("/api/v2/status"):
                return {
                    "board_id": 1,
                    "streaming": False,
                    "profile": {
                        "center_mhz": 159.9999999999909,
                        "sample_rate_msps": 320,
                    },
                    "pipeline": {"stream_accepting": False},
                    "dac": {
                        "enable_mask": 0,
                        "channels": [
                            {"enabled": False, "amplitude_code": 0}
                            for _ in range(8)
                        ],
                    },
                }
            return {}

        args = argparse.Namespace(agent_base="http://agent")
        with mock.patch.object(scan, "_http_json", side_effect=fake_http):
            self.assertEqual(scan._final_stop_and_mute(args, 160.0), [])
        self.assertFalse(any(url.endswith("/api/v2/dac") for url, _, _ in calls))

    def test_final_shutdown_clamps_quantization_epsilon_before_dac_write(self) -> None:
        calls = []
        status_count = 0

        def fake_http(url, *, method="GET", body=None, timeout=30.0):
            nonlocal status_count
            calls.append((url, method, body))
            if url.endswith("/api/v2/status"):
                status_count += 1
                return {
                    "board_id": 1,
                    "streaming": False,
                    "profile": {
                        "center_mhz": 159.9999999999909,
                        "sample_rate_msps": 320,
                    },
                    "pipeline": {"stream_accepting": False},
                    "dac": {
                        "enable_mask": 1 if status_count == 1 else 0,
                        "channels": [
                            {
                                "enabled": status_count == 1 and lane == 0,
                                "amplitude_code": 1 if status_count == 1 and lane == 0 else 0,
                            }
                            for lane in range(8)
                        ],
                    },
                }
            return {}

        args = argparse.Namespace(agent_base="http://agent")
        with mock.patch.object(scan, "_http_json", side_effect=fake_http):
            self.assertEqual(scan._final_stop_and_mute(args, 160.0), [])
        dac = next(body for url, _, body in calls if url.endswith("/api/v2/dac"))
        self.assertEqual(dac["center_mhz"], 160.0)


if __name__ == "__main__":
    unittest.main()
