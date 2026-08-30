import json
import math
import random
import struct
import unittest

from scripts import t510_allan_interferometry as stage34d


def make_tis1(*, bucket_count=2, pair_count=28):
    pairs = list(stage34d.ADC_PAIRS[:pair_count])
    metadata = json.dumps(
        {
            "format": "TIS1",
            "version": 1,
            "targets": [{"target_index": 0, "actual_rf_mhz": 966.875}],
            "pairs": pairs,
        },
        separators=(",", ":"),
    ).encode()
    record_bytes = 32 + 8 * 40 + pair_count * 24
    blob = bytearray()
    blob += b"TIS1"
    blob += struct.pack(
        "<HHIIIIHHHHQQQQ",
        1, 64, len(metadata), 100, 320, 1, 1, 8, pair_count, 0,
        bucket_count, 1234, 0, record_bytes,
    )
    blob += metadata
    for bucket in range(bucket_count):
        blob += struct.pack("<IHHQQQ", bucket, 0, 0, bucket * 32_000_000, bucket * 32_000_000 + 4096, 2)
        for lane in range(8):
            i, q = lane + 1.0, lane + 2.0
            power = i * i + q * q
            blob += struct.pack("<Qdddd", 2, 2 * i, 2 * q, 2 * power, 2 * power * power)
        for channel_a, channel_b in pairs:
            ia, qa = channel_a + 1.0, channel_a + 2.0
            ib, qb = channel_b + 1.0, channel_b + 2.0
            blob += struct.pack("<Qdd", 2, 2 * (ia * ib + qa * qb), 2 * (qa * ib - ia * qb))
    return bytes(blob)


class Stage34dTests(unittest.TestCase):
    def test_tis1_round_trip_and_complex_sign(self):
        decoded = stage34d.decode_tis1(make_tis1(bucket_count=10))
        self.assertEqual(decoded["pair_count"], 28)
        self.assertEqual(decoded["record_bytes"], 1024)
        self.assertEqual(decoded["metadata"]["pairs"][0], [0, 1])
        self.assertEqual(decoded["metadata"]["pairs"][-1], [6, 7])
        count, real, imag = decoded["records"][0]["crosses"][0]
        self.assertEqual(count, 2)
        self.assertEqual(real / count, 8.0)
        self.assertEqual(imag / count, 1.0)

    def test_tis1_rejects_truncation_and_missing_bucket(self):
        blob = make_tis1(bucket_count=10)
        with self.assertRaisesRegex(ValueError, "length"):
            stage34d.decode_tis1(blob[:-1])
        damaged = bytearray(blob)
        metadata_len = struct.unpack_from("<I", damaged, 8)[0]
        record_bytes = struct.unpack_from("<Q", damaged, 56)[0]
        second = 64 + metadata_len + record_bytes
        struct.pack_into("<I", damaged, second, 2)
        with self.assertRaisesRegex(ValueError, "out of order|missing/non-contiguous"):
            stage34d.decode_tis1(bytes(damaged))

    def test_overlapping_allan_and_white_noise_integration_slope(self):
        rng = random.Random(34)
        white = [10.0 + rng.gauss(0, 1) for _ in range(65536)]
        curve = stage34d.stability_curve(white, 0.1, stage34d.SHORT_TAUS)
        self.assertTrue(-0.58 <= curve["slope"] <= -0.42)
        self.assertGreater(stage34d.overlapping_allan_deviation(white, 8), 0)
        drift = [10.0 + index / len(white) + rng.gauss(0, 0.02) for index in range(len(white))]
        self.assertGreater(stage34d.stability_curve(drift, 0.1, stage34d.SHORT_TAUS)["slope"], -0.35)

    def test_pca_identifies_dominant_common_scalar_mode(self):
        rng = random.Random(340); matrix = []
        for index in range(3000):
            common = math.sin(index / 70) + rng.gauss(0, 0.05)
            matrix.append([common + rng.gauss(0, 0.08) for _ in range(12)])
        result = stage34d.first_pca_mode(matrix)
        self.assertGreater(result["explained_fraction"], 0.9)
        self.assertEqual(len(result["loadings"]), 12)

    def test_bootstrap_and_bh_detect_nonzero_floor(self):
        rng = random.Random(341)
        zero = [rng.gauss(0, 1) for _ in range(2000)]
        biased = [0.4 + rng.gauss(0, 1) for _ in range(2000)]
        self.assertGreater(stage34d.moving_block_bootstrap_mean(zero, seed=1)["p_two_sided"], 0.01)
        self.assertLessEqual(stage34d.moving_block_bootstrap_mean(biased, seed=2)["p_two_sided"], 0.01)
        adjusted = stage34d.bh_adjust([0.0001, 0.02, 0.5])
        self.assertTrue(adjusted[0] <= adjusted[1] <= adjusted[2])

    def test_physical_phase_plans_are_balanced_and_fixed(self):
        shared = stage34d.shared_plan(); opened = stage34d.open_plan(); matched = stage34d.matched_plan()
        self.assertEqual([(row["rate"], row["duration"], row["bucket_ms"]) for row in shared], [
            (160, 600, 100), (320, 600, 100), (320, 3600, 1000), (160, 3600, 1000)
        ])
        self.assertEqual([(row["rate"], row["duration"], row["bucket_ms"]) for row in opened], [
            (320, 600, 100), (160, 600, 100), (160, 3600, 1000), (320, 3600, 1000)
        ])
        self.assertEqual([(row["rate"], row["duration"], row["bucket_ms"]) for row in matched], [
            (320, 600, 100), (160, 600, 100), (160, 3600, 1000), (320, 3600, 1000)
        ])
        self.assertEqual(len(stage34d.ADC_PAIRS), 28)
        self.assertTrue(set(stage34d.SAME_TILE_PAIRS).issubset(stage34d.ADC_PAIRS))

    def test_matched_classification_renames_open_gate_without_weakening_it(self):
        rows = []
        for pair in stage34d.ADC_PAIRS:
            for rf_mhz in stage34d.OFFGRID_RF_MHZ:
                rows.append({
                    "channel_a": pair[0], "channel_b": pair[1], "rf_mhz": rf_mhz,
                    "re_slope_pass": True, "im_slope_pass": True,
                    "re_lag1_1s": 0.01, "im_lag1_1s": -0.02,
                    "re_white_128_ratio": 1.1, "im_white_128_ratio": 1.2,
                    "zero_mean_significant_q0p01": False, "mean_coherence": 1e-4,
                })
        runs = [{"name": "matched", "rate": 320, "bucket_ms": 1000, "analysis": {"cross_metrics": rows}}]
        result = stage34d.classify_matched(runs)
        self.assertTrue(result["pass"])
        self.assertEqual(result["classification"], "INDEPENDENT_MATCHED_LOAD_ZERO_CORRELATION_QUALIFIED")


if __name__ == "__main__":
    unittest.main()
