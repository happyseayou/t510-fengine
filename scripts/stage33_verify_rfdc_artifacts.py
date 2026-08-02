#!/usr/bin/env python3
"""Verify generated Stage 33 RFDC XCI/HWH properties before release."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET


CONVERTER_SLICES = ("00", "02", "10", "12", "20", "22", "30", "32")
ADC_R2C_PATHS = (
    "00", "01", "02", "03", "10", "11", "12", "13",
    "20", "21", "22", "23", "30", "31", "32", "33",
)


def _xci_parameters(path: Path) -> dict[str, str]:
    raw_text = path.read_text(encoding="utf-8-sig")
    if raw_text.lstrip().startswith("{"):
        value = json.loads(raw_text)
        raw = value["ip_inst"]["parameters"]["component_parameters"]
        return {name: str(rows[0]["value"]) for name, rows in raw.items() if rows}

    root = ET.fromstring(raw_text)
    values: dict[str, str] = {}
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] != "configurableElementValue":
            continue
        reference = next(
            (
                value
                for name, value in element.attrib.items()
                if name.rsplit("}", 1)[-1] == "referenceId"
            ),
            None,
        )
        if reference is None or not reference.startswith("PARAM_VALUE."):
            continue
        values[reference.removeprefix("PARAM_VALUE.")] = (element.text or "").strip()
    if not values:
        raise ValueError(f"{path} contains no Vivado PARAM_VALUE entries")
    return values


def _hwh_parameters(root: ET.Element) -> dict[str, list[str]]:
    values: dict[str, list[str]] = {}
    for element in root.iter("PARAMETER"):
        name = element.get("NAME")
        value = element.get("VALUE")
        if name is not None and value is not None:
            values.setdefault(name, []).append(value)
    return values


def _require_equal(errors: list[str], source: str, values: dict[str, str], name: str, expected: str) -> None:
    actual = values.get(name)
    if actual != expected:
        errors.append(f"{source} {name}: expected {expected}, read {actual}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Stage 33 generated RFDC artifact gate")
    parser.add_argument("--xci", required=True, help="generated usp_rf_data_converter XCI")
    parser.add_argument("--hwh", default="overlay/t510_fengine.hwh")
    args = parser.parse_args()
    xci_path = Path(args.xci).resolve()
    hwh_path = Path(args.hwh).resolve()
    xci = _xci_parameters(xci_path)
    hwh_root = ET.parse(hwh_path).getroot()
    hwh_values = _hwh_parameters(hwh_root)
    errors: list[str] = []

    for tile in range(4):
        _require_equal(errors, "XCI", xci, f"ADC{tile}_Sampling_Rate", "3.8400")
        _require_equal(errors, "XCI", xci, f"DAC{tile}_Sampling_Rate", "3.8400")
        _require_equal(errors, "XCI", xci, f"ADC{tile}_Fabric_Freq", "80.000")
        _require_equal(errors, "XCI", xci, f"DAC{tile}_Fabric_Freq", "80.000")
    for slice_name in ADC_R2C_PATHS:
        for name, expected in (
            (f"ADC_Slice{slice_name}_Enable", "true"),
            (f"ADC_Decimation_Mode{slice_name}", "12"),
            (f"ADC_Data_Width{slice_name}", "4"),
            (f"ADC_Data_Type{slice_name}", "1"),
            (f"ADC_Mixer_Type{slice_name}", "2"),
            (f"ADC_Mixer_Mode{slice_name}", "0"),
            (f"ADC_Dither{slice_name}", "true"),
        ):
            _require_equal(errors, "XCI", xci, name, expected)
            if expected not in hwh_values.get(name, []):
                errors.append(
                    f"HWH {name}: expected one value {expected}, read {hwh_values.get(name)}"
                )

    for slice_name in CONVERTER_SLICES:
        for name, expected in (
            (f"DAC_Slice{slice_name}_Enable", "true"),
            (f"DAC_Interpolation_Mode{slice_name}", "12"),
            (f"DAC_Data_Width{slice_name}", "8"),
            (f"DAC_Data_Type{slice_name}", "0"),
            (f"DAC_Mixer_Type{slice_name}", "2"),
            (f"DAC_Mixer_Mode{slice_name}", "0"),
        ):
            _require_equal(errors, "XCI", xci, name, expected)
            if expected not in hwh_values.get(name, []):
                errors.append(
                    f"HWH {name}: expected one value {expected}, read {hwh_values.get(name)}"
                )

    expected_enabled = {
        "ADC": set(ADC_R2C_PATHS),
        "DAC": set(CONVERTER_SLICES),
    }
    for kind in ("ADC", "DAC"):
        enabled = {
            match.group(1)
            for name, value in xci.items()
            if (match := re.fullmatch(fr"{kind}_Slice([0-3][0-3])_Enable", name))
            and value.lower() == "true"
        }
        if enabled != expected_enabled[kind]:
            errors.append(
                f"XCI enabled {kind} digital paths: "
                f"expected {sorted(expected_enabled[kind])}, read {sorted(enabled)}"
            )

    for tile in range(4):
        for name in (f"ADC{tile}_Sampling_Rate", f"DAC{tile}_Sampling_Rate"):
            if "3.8400" not in hwh_values.get(name, []):
                errors.append(f"HWH {name}: expected 3.8400, read {hwh_values.get(name)}")

    ports = {element.get("NAME"): element for element in hwh_root.iter("PORT")}
    adc_axis_tdata = {
        name
        for name in ports
        if name is not None and re.fullmatch(r"m[0-3][0-3]_axis_tdata", name)
    }
    expected_adc_axis_tdata = {f"m{name}_axis_tdata" for name in ADC_R2C_PATHS}
    if adc_axis_tdata != expected_adc_axis_tdata:
        errors.append(
            "HWH ADC AXIS TDATA port set mismatch: "
            f"expected {sorted(expected_adc_axis_tdata)}, read {sorted(adc_axis_tdata)}"
        )
    dac_axis_tdata = {
        name
        for name in ports
        if name is not None and re.fullmatch(r"s[0-3][0-3]_axis_tdata", name)
    }
    expected_dac_axis_tdata = {f"s{name}_axis_tdata" for name in CONVERTER_SLICES}
    if dac_axis_tdata != expected_dac_axis_tdata:
        errors.append(
            "HWH DAC AXIS TDATA port set mismatch: "
            f"expected {sorted(expected_dac_axis_tdata)}, read {sorted(dac_axis_tdata)}"
        )
    for axis_name in ADC_R2C_PATHS:
        name = f"m{axis_name}_axis_tdata"
        port = ports.get(name)
        if port is None or port.get("LEFT") != "63" or port.get("RIGHT") != "0":
            errors.append(f"HWH {name}: expected [63:0]")
    for slice_name in CONVERTER_SLICES:
        name = f"s{slice_name}_axis_tdata"
        port = ports.get(name)
        if port is None or port.get("LEFT") != "127" or port.get("RIGHT") != "0":
            errors.append(f"HWH {name}: expected [127:0]")
    for clock_name in ("adc_m_axis_clk", "dac_s_axis_clk"):
        port = ports.get(clock_name)
        if port is None or port.get("CLKFREQUENCY") != "80000000":
            errors.append(f"HWH {clock_name}: expected 80000000 Hz")

    result = {
        "ok": not errors,
        "classification": (
            "STAGE33_RFDC_ARTIFACTS_PASS" if not errors else "STAGE33_RFDC_ARTIFACTS_FAIL"
        ),
        "xci": str(xci_path),
        "hwh": str(hwh_path),
        "physical_adc_converters": len(CONVERTER_SLICES),
        "enabled_adc_r2c_paths": len(ADC_R2C_PATHS),
        "enabled_dac_c2r_paths": len(CONVERTER_SLICES),
        "errors": errors,
    }
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
