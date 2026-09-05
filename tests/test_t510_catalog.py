from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from python.t510_scaling import qmc_settings, scaling_identity


ROOT = Path(__file__).resolve().parents[1]
FINALIZER = ROOT / "scripts" / "t510_finalize_catalog.py"
EXPECTED_ACTIONS = {"rfdc_reset": 20, "overlay_reload": 10, "lmk_reload": 10}


def _cycles(*, phase: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    cycle = 0
    for action, count in EXPECTED_ACTIONS.items():
        for _ in range(count):
            row: dict[str, object] = {
                "cycle": cycle,
                "action": action,
                "ok": True,
                "errors": [],
            }
            if phase == "fixed":
                row["evidence"] = {
                    "mts": {
                        "adc_config": {
                            "tiles": 0xF,
                            "target_latency": 492,
                            "latency": [492, 492, 492, 492],
                            "offset": [0, 1, 2, 3],
                        },
                        "dac_config": {
                            "tiles": 0xF,
                            "target_latency": -1,
                            "latency": [416, 416, 416, 416],
                            "offset": [4, 5, 6, 7],
                        },
                    }
                }
            row.setdefault('evidence', {})['digital_scaling'] = scaling_identity(
                0x00010036, 0x556,
                [dict(tile=t, block=b, qmc=qmc_settings()) for t in range(4) for b in range(2)])
            rows.append(row)
            cycle += 1
    return rows


def _report(*, phase: str, bitstream_sha256: str) -> dict[str, object]:
    value: dict[str, object] = {
        "phase": phase,
        "clock_ref": "tcxo_10mhz",
        "core_version": "0x00010036",
        "bitstream_sha256": bitstream_sha256,
        "ok": True,
        "required_cycles": EXPECTED_ACTIONS,
        "cycles": _cycles(phase=phase),
        "latency_quanta": {"adc": 12, "dac": 12},
        "lmk_settle_seconds": 3.0,
    }
    if phase == "discovery":
        value["observed_latency"] = {
            "adc": [432] * 4,
            "adc_max": 432,
            "dac": [72] * 4,
            "dac_max": 72,
        }
        value["recommended_fixed_targets"] = {"adc": 492, "dac": -1}
    else:
        value["targets"] = {"adc": 492, "dac": -1}
        value["fixed_repeatability"] = {"ok": True}
    return value


def _catalog() -> dict[str, object]:
    return {
        "listen": "0.0.0.0:8010",
        "management_interface": "eth0",
        "python_executable": "/python3",
        "helper_path": "/t510_hw.py",
        "helper_pythonpath": "/python",
        "default_bitstream_id": "fengine-current",
        "bitstreams": [
            {
                "id": "fengine-current",
                "path": "/overlay/t510_fengine.bit",
                "sha256": "0" * 64,
                "core_version": "0x00010036",
                "scaling_profile": "qmc16383of8192-pfb16-fft0556",
                "pfb_output_shift": 16,
                "coefficient_fraction_bits": 17,
                "fft_shift": "0x0556",
                "required_qmc_gain": 1.9998779296875,
                "mts_qualifications": {
                    "onboard_tcxo": {"status": "pending"},
                    "external_10mhz": {"status": "pending"},
                },
                "profiles": [],
            }
        ],
    }


class T510CatalogFinalizerTests(unittest.TestCase):
    def _fixture(self, directory: Path) -> tuple[Path, Path, Path, Path, str]:
        bitstream = directory / "candidate.bit"
        bitstream.write_bytes(b"t510-current-bitstream")
        digest = hashlib.sha256(bitstream.read_bytes()).hexdigest()
        discovery = directory / "discovery.json"
        fixed = directory / "fixed.json"
        catalog = directory / "catalog.json"
        discovery.write_text(json.dumps(_report(phase="discovery", bitstream_sha256=digest)))
        fixed.write_text(json.dumps(_report(phase="fixed", bitstream_sha256=digest)))
        catalog.write_text(json.dumps(_catalog()))
        return bitstream, discovery, fixed, catalog, digest

    @staticmethod
    def _run(bitstream: Path, discovery: Path, fixed: Path, catalog: Path) -> subprocess.CompletedProcess[str]:
        metadata = json.loads((ROOT / "config/t510/current_release.json").read_text())
        metadata["bitstream_sha256"] = hashlib.sha256(bitstream.read_bytes()).hexdigest()
        metadata_path = bitstream.parent / "current_release.json"
        metadata_path.write_text(json.dumps(metadata))
        return subprocess.run(
            [
                sys.executable,
                str(FINALIZER),
                "--reference", "onboard_tcxo",
                "--metadata", str(metadata_path),
                "--bitstream",
                str(bitstream),
                "--discovery-json",
                str(discovery),
                "--fixed-json",
                str(fixed),
                "--catalog",
                str(catalog),
            ],
            check=False,
            capture_output=True,
            text=True,
        )

    def test_finalizer_binds_campaigns_and_targets_to_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            bitstream, discovery, fixed, catalog, digest = self._fixture(Path(temporary))
            result = self._run(bitstream, discovery, fixed, catalog)
            self.assertEqual(result.returncode, 0, result.stderr)
            entry = json.loads(catalog.read_text())["bitstreams"][0]
            self.assertEqual(entry["sha256"], digest)
            qualification = entry["mts_qualifications"]["onboard_tcxo"]
            self.assertEqual(qualification["mts_adc_target_latency"], 492)
            self.assertEqual(qualification["mts_dac_target_latency"], -1)
            self.assertEqual(
                qualification["campaign"]["dac_alignment_mode"],
                "single_device_relative",
            )
            self.assertEqual(qualification["campaign"]["discovery"]["passed"], 40)
            self.assertEqual(qualification["campaign"]["fixed"]["passed"], 40)

    def test_finalizer_rejects_campaign_from_another_bitstream(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            bitstream, discovery, fixed, catalog, _digest = self._fixture(Path(temporary))
            report = json.loads(fixed.read_text())
            report["bitstream_sha256"] = "f" * 64
            fixed.write_text(json.dumps(report))
            result = self._run(bitstream, discovery, fixed, catalog)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("bitstream SHA", result.stderr)

    def test_finalizer_accepts_quantized_fixed_latency_on_either_side_of_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            bitstream, discovery, fixed, catalog, _digest = self._fixture(Path(temporary))
            report = json.loads(fixed.read_text())
            for index, row in enumerate(report["cycles"]):
                row["evidence"]["mts"]["adc_config"]["latency"] = [
                    498 if index % 2 else 486
                ] * 4
                row["evidence"]["mts"]["dac_config"]["latency"] = [
                    416 if index % 2 else 32
                ] * 4
                row["evidence"]["mts"]["adc_config"]["target_latency"] = 492
                row["evidence"]["mts"]["dac_config"]["target_latency"] = -1
                row["evidence"]["mts"]["adc_config"]["offset"] = [index % 6] * 4
            fixed.write_text(json.dumps(report))
            result = self._run(bitstream, discovery, fixed, catalog)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_finalizer_accepts_driver_quantized_intertile_residual(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            bitstream, discovery, fixed, catalog, _digest = self._fixture(Path(temporary))
            report = json.loads(fixed.read_text())
            report["cycles"][-1]["evidence"]["mts"]["dac_config"]["latency"] = [
                768, 768, 768, 764
            ]
            fixed.write_text(json.dumps(report))
            result = self._run(bitstream, discovery, fixed, catalog)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_finalizer_rejects_intertile_residual_of_one_factor(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            bitstream, discovery, fixed, catalog, _digest = self._fixture(Path(temporary))
            report = json.loads(fixed.read_text())
            report["cycles"][-1]["evidence"]["mts"]["dac_config"]["latency"] = [
                768, 768, 768, 756
            ]
            fixed.write_text(json.dumps(report))
            result = self._run(bitstream, discovery, fixed, catalog)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("inter-tile span is too large", result.stderr)

    def test_finalizer_rejects_missing_scale_readback_without_writing_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            bitstream, discovery, fixed, catalog, _digest = self._fixture(Path(temporary))
            before = catalog.read_bytes()
            report = json.loads(fixed.read_text())
            del report['cycles'][-1]['evidence']['digital_scaling']
            fixed.write_text(json.dumps(report))
            result = self._run(bitstream, discovery, fixed, catalog)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('scaling identity', result.stderr)
            self.assertEqual(catalog.read_bytes(), before)

    def test_finalizer_rejects_pre_stage35_lmk_settle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            bitstream, discovery, fixed, catalog, _digest = self._fixture(Path(temporary))
            report = json.loads(discovery.read_text())
            report["lmk_settle_seconds"] = 1.0
            discovery.write_text(json.dumps(report))
            result = self._run(bitstream, discovery, fixed, catalog)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("3 s LMK settle", result.stderr)


if __name__ == "__main__":
    unittest.main()
