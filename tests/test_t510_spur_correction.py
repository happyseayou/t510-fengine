from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
import zlib
import math

from python.packet import (
    FLAG_ADC_INTERLEAVE_SPUR_CORRECTION_ACTIVE,
    FLAG_ADC_INTERLEAVE_SPUR_UNCORRECTED,
    T510PacketHeader,
)
from python.t510_spur_correction import (
    PHASE_MODULUS,
    LaneSpurModel,
    apply_ocb_tracking_matrix,
    coefficient_crc32,
    estimate_preview_vector,
    find_in_band_spur,
    fit_real_2x2,
    hardware_phasor,
    load_model,
    ocb1_dft,
    phase_seed_u48,
    phase_step_signed,
    phase_step_u48,
    quantize_q8_16,
    save_model,
)


class SpurCorrectionModelTests(unittest.TestCase):
    def test_each_legal_window_contains_at_most_one_registered_spur(self) -> None:
        self.assertEqual(find_in_band_spur(540e6, 160e6)["spur_id"], 1)
        self.assertEqual(find_in_band_spur(900e6, 320e6)["spur_id"], 2)
        self.assertEqual(find_in_band_spur(1380e6, 160e6)["spur_id"], 3)
        self.assertIsNone(find_in_band_spur(700e6, 160e6))
        # A spur exactly on the selected-band edge is not a science bin.
        self.assertIsNone(find_in_band_spur(560e6, 160e6))

    def test_positive_negative_phase_step_and_absolute_seed(self) -> None:
        positive = phase_step_u48(80e6)
        negative = phase_step_u48(-80e6)
        self.assertEqual(positive, 1 << 46)
        self.assertEqual(phase_step_signed(positive), 1 << 46)
        self.assertEqual(phase_step_signed(negative), -(1 << 46))
        self.assertEqual(phase_seed_u48(positive, 8193), positive)
        self.assertEqual((positive * 8192) % PHASE_MODULUS, 0)

    def test_ocb1_dft_identifies_k1_k2_k3_components(self) -> None:
        for expected_k in (1, 2, 3):
            coefficients = [
                int(round(1000 * math.cos(2 * math.pi * expected_k * n / 8)))
                for n in range(8)
            ]
            dft = ocb1_dft(coefficients)
            dominant = max((1, 2, 3), key=lambda k: abs(dft[k]))
            self.assertEqual(dominant, expected_k)

    def test_real_2x2_tracking_preserves_cross_terms(self) -> None:
        d_values = [0 + 0j, 1 + 0j, 0 + 1j, 2 - 1j, -1 + 3j]
        expected = [[2.0, -0.5], [0.25, 3.0]]
        c0 = 4.0 - 7.0j
        c_values = [
            apply_ocb_tracking_matrix(c0, value, 0j, expected)
            for value in d_values
        ]
        fitted = fit_real_2x2(d_values, c_values)
        for actual_row, expected_row in zip(fitted, expected):
            for actual, target in zip(actual_row, expected_row):
                self.assertAlmostEqual(actual, target, places=12)
        model = LaneSpurModel(c0=c0, d0=0j, matrix_2x2=tuple(map(tuple, fitted)))
        self.assertAlmostEqual(model.tracked(2 - 1j).real, 8.5)
        self.assertAlmostEqual(model.tracked(2 - 1j).imag, -9.5)

    def test_preview_correlation_uses_exact_lut_and_absolute_sample0(self) -> None:
        step = phase_step_u48(-60e6)
        sample0 = 12_345
        phase_origin = 8_192
        phasor = hardware_phasor(
            step, range(sample0 - phase_origin, sample0 - phase_origin + 1024)
        )
        injected = 2.25 - 1.5j
        samples = [injected * value for value in phasor]
        iq = [[value.real, value.imag] for value in samples]
        measured = estimate_preview_vector(
            iq,
            sample0=sample0,
            step_u48=step,
            phase_origin_sample0=phase_origin,
        )
        self.assertAlmostEqual(measured.real, injected.real, places=10)
        self.assertAlmostEqual(measured.imag, injected.imag, places=10)

    def test_q8_16_crc_is_little_endian_low24_with_zero_high_byte(self) -> None:
        values = [quantize_q8_16(complex(index / 8, -index / 16)) for index in range(8)]
        raw = b"".join(
            int(component & 0x00FF_FFFF).to_bytes(4, "little")
            for pair in values
            for component in pair
        )
        self.assertEqual(coefficient_crc32(values), zlib.crc32(raw) & 0xFFFF_FFFF)

    def test_frozen_model_rejects_tamper(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.json"
            frozen = save_model(path, {"schema_version": 1, "lanes": [{"c0": [1, 2]}]})
            self.assertEqual(load_model(path)["sha256"], frozen["sha256"])
            value = json.loads(path.read_text())
            value["lanes"][0]["c0"][0] = 3
            path.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError, "SHA256 mismatch"):
                load_model(path)

    def test_udp_v2_preserves_layout_and_round_trips_new_flags(self) -> None:
        flags = (
            FLAG_ADC_INTERLEAVE_SPUR_CORRECTION_ACTIVE
            | FLAG_ADC_INTERLEAVE_SPUR_UNCORRECTED
        )
        encoded = T510PacketHeader(flags=flags).to_bytes()
        decoded = T510PacketHeader.from_bytes(encoded)
        self.assertEqual(decoded.flags & flags, flags)
        self.assertEqual(len(encoded), 128)


if __name__ == "__main__":
    unittest.main()
