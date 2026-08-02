from __future__ import annotations

import cmath
import inspect
import math
from pathlib import Path
import re
import unittest

from python.t510_fengine import T510FEngine


def pl_complex_dds(count: int, signed_bin: int) -> list[complex]:
    """Model the standard Stage 32h2 I=cos, Q=sin complex DDS."""

    return [
        complex(math.cos(2.0 * math.pi * signed_bin * n / count),
                math.sin(2.0 * math.pi * signed_bin * n / count))
        for n in range(count)
    ]


def dft_power(samples: list[complex]) -> list[float]:
    count = len(samples)
    return [
        abs(sum(
            sample * cmath.exp(-2j * math.pi * bin_index * n / count)
            for n, sample in enumerate(samples)
        )) ** 2
        for bin_index in range(count)
    ]


class Stage32H2DacIqDirectionTests(unittest.TestCase):
    def test_rfdc_dac_contract_is_iq_to_real_on_every_enabled_path(self) -> None:
        bd_tcl = Path("bd/t510_rfdc_bd.tcl").read_text(encoding="utf-8")
        enabled_paths = ("00", "02", "10", "12", "20", "22", "30", "32")
        for path in enabled_paths:
            values = re.findall(
                rf"CONFIG\.DAC_Data_Type{path}\s+\{{([01])\}}",
                bd_tcl,
            )
            # RFDC GUI Data_Type describes the analog output.  A real DAC
            # output therefore uses type 0 while the fine mixer consumes the
            # alternating PL I/Q words through mode 0 (I/Q -> Real).
            self.assertEqual(values, ["0"], f"DAC path {path} must produce real analog output")
            self.assertRegex(
                bd_tcl,
                rf"CONFIG\.DAC_Mixer_Type{path}\s+\{{2\}}",
                f"DAC path {path} must use the fine mixer",
            )
            self.assertRegex(
                bd_tcl,
                rf"CONFIG\.DAC_Mixer_Mode{path}\s+\{{0\}}",
                f"DAC path {path} must use I/Q-to-Real",
            )
            self.assertRegex(
                bd_tcl,
                rf"CONFIG\.DAC_Data_Width{path}\s+\{{8\}}",
                f"DAC path {path} must keep eight 16-bit words per AXIS beat",
            )

        self.assertNotRegex(bd_tcl, r"CONFIG\.DAC_Data_Type(?:00|02|10|12|20|22|30|32)\s+\{1\}")

    def test_phase_zero_and_positive_complex_rotation(self) -> None:
        samples = pl_complex_dds(4, 1)
        self.assertAlmostEqual(samples[0].real, 1.0, places=12)
        self.assertAlmostEqual(samples[0].imag, 0.0, places=12)
        self.assertAlmostEqual(samples[1].real, 0.0, places=12)
        self.assertAlmostEqual(samples[1].imag, 1.0, places=12)

    def test_signed_offsets_use_matching_complex_bins(self) -> None:
        count = 64
        for signed_bin in (7, -11):
            powers = dft_power(pl_complex_dds(count, signed_bin))
            peak_bin = max(range(count), key=powers.__getitem__)
            self.assertEqual(peak_bin, signed_bin % count)
            wrong_bin = (-signed_bin) % count
            self.assertGreater(powers[peak_bin], max(powers[wrong_bin], 1e-24) * 1e12)

    def test_board_witness_metric_uses_positive_complex_rotation(self) -> None:
        source = inspect.getsource(T510FEngine.compute_dac_source_phase_metrics)
        self.assertIn("basis = np.exp(1j *", source)
        self.assertNotIn("basis = np.exp(-1j *", source)

    def test_rfdc_dac_mixer_does_not_force_an_extra_fifo_width_reset(self) -> None:
        source = inspect.getsource(T510FEngine._configure_rfdc_mixer_blocks_sysref)
        self.assertNotIn("ResetInternalFIFOWidth", source)


if __name__ == "__main__":
    unittest.main()
