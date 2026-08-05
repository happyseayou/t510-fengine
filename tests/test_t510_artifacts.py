from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
VERIFIER = ROOT / "scripts" / "t510_verify_rfdc_artifacts.py"
SLICES = ("00", "02", "10", "12", "20", "22", "30", "32")
ADC_PATHS = (
    "00", "01", "02", "03", "10", "11", "12", "13",
    "20", "21", "22", "23", "30", "31", "32", "33",
)


def _parameters() -> dict[str, list[dict[str, str]]]:
    values: dict[str, str] = {}
    for tile in range(4):
        values[f"ADC{tile}_Sampling_Rate"] = "3.8400"
        values[f"DAC{tile}_Sampling_Rate"] = "3.8400"
        values[f"ADC{tile}_Fabric_Freq"] = "80.000"
        values[f"DAC{tile}_Fabric_Freq"] = "80.000"
    for tile in range(4):
        for block in range(4):
            name = f"{tile}{block}"
            values[f"ADC_Slice{name}_Enable"] = "true"
            values[f"DAC_Slice{name}_Enable"] = "true" if name in SLICES else "false"
    for name in ADC_PATHS:
        values[f"ADC_Decimation_Mode{name}"] = "12"
        values[f"ADC_Data_Width{name}"] = "4"
        values[f"ADC_Data_Type{name}"] = "1"
        values[f"ADC_Mixer_Type{name}"] = "2"
        values[f"ADC_Mixer_Mode{name}"] = "0"
        values[f"ADC_Dither{name}"] = "true"
    for name in SLICES:
        values[f"ADC_CalOpt_Mode{name}"] = "1"
        values[f"DAC_Interpolation_Mode{name}"] = "12"
        values[f"DAC_Data_Width{name}"] = "8"
        values[f"DAC_Data_Type{name}"] = "0"
        values[f"DAC_Mixer_Type{name}"] = "2"
        values[f"DAC_Mixer_Mode{name}"] = "0"
    return {name: [{"value": value}] for name, value in values.items()}


def _write_xci(path: Path, parameters: dict[str, list[dict[str, str]]]) -> None:
    path.write_text(
        json.dumps(
            {
                "ip_inst": {
                    "parameters": {"component_parameters": parameters}
                }
            }
        )
    )


def _write_xml_xci(path: Path, parameters: dict[str, list[dict[str, str]]]) -> None:
    namespace = "http://www.spiritconsortium.org/XMLSchema/SPIRIT/1685-2009"
    root = ET.Element(f"{{{namespace}}}design")
    values = ET.SubElement(root, f"{{{namespace}}}configurableElementValues")
    for name, rows in parameters.items():
        element = ET.SubElement(
            values,
            f"{{{namespace}}}configurableElementValue",
            {f"{{{namespace}}}referenceId": f"PARAM_VALUE.{name}"},
        )
        element.text = rows[0]["value"]
    ET.ElementTree(root).write(path, encoding="unicode")


def _write_hwh(path: Path, parameters: dict[str, list[dict[str, str]]]) -> None:
    root = ET.Element("SYSTEM")
    for name, rows in parameters.items():
        if name.endswith("_Enable") and rows[0]["value"] == "false":
            continue
        ET.SubElement(root, "PARAMETER", NAME=name, VALUE=rows[0]["value"])
    for name in ADC_PATHS:
        ET.SubElement(root, "PORT", NAME=f"m{name}_axis_tdata", LEFT="63", RIGHT="0")
    for name in SLICES:
        ET.SubElement(root, "PORT", NAME=f"s{name}_axis_tdata", LEFT="127", RIGHT="0")
    ET.SubElement(root, "PORT", NAME="adc_m_axis_clk", CLKFREQUENCY="80000000")
    ET.SubElement(root, "PORT", NAME="dac_s_axis_clk", CLKFREQUENCY="80000000")
    ET.ElementTree(root).write(path, encoding="unicode")


class T510ArtifactVerifierTests(unittest.TestCase):
    @staticmethod
    def _run(xci: Path, hwh: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(VERIFIER), "--xci", str(xci), "--hwh", str(hwh)],
            check=False,
            capture_output=True,
            text=True,
        )

    def test_accepts_current_converter_and_axis_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            xci = directory / "rfdc.xci"
            hwh = directory / "overlay.hwh"
            parameters = _parameters()
            _write_xci(xci, parameters)
            _write_hwh(hwh, parameters)
            result = self._run(xci, hwh)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue(json.loads(result.stdout)["ok"])

    def test_rejects_extra_enabled_slice_and_wrong_sample_rate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            xci = directory / "rfdc.xci"
            hwh = directory / "overlay.hwh"
            parameters = _parameters()
            parameters["ADC0_Sampling_Rate"][0]["value"] = "1.6000"
            parameters["DAC_Slice01_Enable"][0]["value"] = "true"
            _write_xci(xci, parameters)
            _write_hwh(hwh, parameters)
            result = self._run(xci, hwh)
            self.assertNotEqual(result.returncode, 0)
            errors = json.loads(result.stdout)["errors"]
            self.assertTrue(any("ADC0_Sampling_Rate" in error for error in errors))
            self.assertTrue(any("enabled DAC digital paths" in error for error in errors))

    def test_rejects_physically_failed_adc_autocal_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            xci = directory / "rfdc.xci"
            hwh = directory / "overlay.hwh"
            parameters = _parameters()
            parameters["ADC_CalOpt_Mode00"][0]["value"] = "2"
            _write_xci(xci, parameters)
            _write_hwh(hwh, parameters)
            result = self._run(xci, hwh)
            self.assertNotEqual(result.returncode, 0)
            errors = json.loads(result.stdout)["errors"]
            self.assertTrue(any("ADC_CalOpt_Mode00" in error for error in errors))

    def test_accepts_vivado_2022_xml_xci(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            xci = directory / "rfdc.xci"
            hwh = directory / "overlay.hwh"
            parameters = _parameters()
            _write_xml_xci(xci, parameters)
            _write_hwh(hwh, parameters)
            result = self._run(xci, hwh)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue(json.loads(result.stdout)["ok"])

    def test_build_wrapper_uses_one_latest_export_and_current_overlay(self) -> None:
        wrapper = (ROOT / "scripts/t510_build_latest.sh").read_text(encoding="utf-8")
        exporter = (ROOT / "scripts/t510_export_current_project.tcl").read_text(
            encoding="utf-8"
        )
        self.assertIn('BUILD_DIR="${ROOT}/build/vivado/latest"', wrapper)
        self.assertIn('CURRENT_OVERLAY="${ROOT}/overlay"', wrapper)
        self.assertNotIn("BUILD_ID", wrapper + exporter)
        self.assertNotIn("--promote-latest", wrapper)
        self.assertNotIn("ln -sfn", wrapper)
        self.assertIn("build vivado latest", exporter)
        self.assertIn("file delete -force $build_dir", exporter)
        self.assertIn('release=latest', wrapper + exporter)


if __name__ == "__main__":
    unittest.main()
