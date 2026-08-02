from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
FINALIZER = ROOT / "scripts" / "stage33_finalize_catalog.py"
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
                            "latency": [231, 231, 231, 231],
                            "offset": [0, 1, 2, 3],
                        },
                        "dac_config": {
                            "tiles": 0xF,
                            "latency": [327, 327, 327, 327],
                            "offset": [4, 5, 6, 7],
                        },
                    }
                }
            rows.append(row)
            cycle += 1
    return rows


def _report(*, phase: str, bitstream_sha256: str) -> dict[str, object]:
    value: dict[str, object] = {
        "phase": phase,
        "core_version": "0x00010033",
        "bitstream_sha256": bitstream_sha256,
        "ok": True,
        "required_cycles": EXPECTED_ACTIONS,
        "cycles": _cycles(phase=phase),
    }
    if phase == "discovery":
        value["observed_latency"] = {"adc_max": 211, "dac_max": 311}
        value["recommended_fixed_targets"] = {"adc": 231, "dac": 327}
    else:
        value["targets"] = {"adc": 231, "dac": 327}
    return value


def _catalog() -> dict[str, object]:
    return {
        "listen": "0.0.0.0:8010",
        "management_interface": "eth0",
        "python_executable": "/python3",
        "helper_path": "/t510_hw.py",
        "helper_pythonpath": "/python",
        "default_bitstream_id": "fengine-0x00010033",
        "bitstreams": [
            {
                "id": "fengine-0x00010033",
                "path": "/overlay/t510_fengine.bit",
                "sha256": "0" * 64,
                "core_version": "0x00010033",
                "mts_adc_target_latency": -1,
                "mts_dac_target_latency": -1,
                "mts_campaign": None,
                "profiles": [],
            }
        ],
    }


class Stage33CatalogFinalizerTests(unittest.TestCase):
    def _fixture(self, directory: Path) -> tuple[Path, Path, Path, Path, str]:
        bitstream = directory / "candidate.bit"
        bitstream.write_bytes(b"stage33-candidate-bitstream")
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
        return subprocess.run(
            [
                sys.executable,
                str(FINALIZER),
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
            self.assertEqual(entry["mts_adc_target_latency"], 231)
            self.assertEqual(entry["mts_dac_target_latency"], 327)
            self.assertEqual(entry["mts_campaign"]["discovery"]["passed"], 40)
            self.assertEqual(entry["mts_campaign"]["fixed"]["passed"], 40)

    def test_finalizer_rejects_campaign_from_another_bitstream(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            bitstream, discovery, fixed, catalog, _digest = self._fixture(Path(temporary))
            report = json.loads(fixed.read_text())
            report["bitstream_sha256"] = "f" * 64
            fixed.write_text(json.dumps(report))
            result = self._run(bitstream, discovery, fixed, catalog)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("bitstream SHA", result.stderr)

    def test_finalizer_rejects_nonrepeatable_fixed_offsets(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            bitstream, discovery, fixed, catalog, _digest = self._fixture(Path(temporary))
            report = json.loads(fixed.read_text())
            report["cycles"][-1]["evidence"]["mts"]["adc_config"]["offset"][0] = 9
            fixed.write_text(json.dumps(report))
            result = self._run(bitstream, discovery, fixed, catalog)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("not repeatable", result.stderr)


if __name__ == "__main__":
    unittest.main()
