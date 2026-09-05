#!/usr/bin/env python3
"""Offline Chromium interaction and publication-contract checks for report v2."""

from __future__ import annotations

import argparse
import base64
import json
import subprocess
import time
import urllib.request
from pathlib import Path


def request(method: str, url: str, value: object | None = None, timeout: int = 300) -> object:
    data = None if value is None else json.dumps(value).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        payload = json.loads(response.read())
    result = payload.get("value")
    if isinstance(result, dict) and result.get("error"):
        raise RuntimeError(json.dumps(result, ensure_ascii=False))
    return result


def execute(base: str, script: str) -> object:
    return request("POST", base + "/execute/sync", {"script": script, "args": []})


def wait_for(base: str, script: str, timeout: float, label: str) -> object:
    deadline = time.monotonic() + timeout
    last: object = None
    while time.monotonic() < deadline:
        last = execute(base, script)
        if last:
            return last
        time.sleep(0.5)
    raise TimeoutError(f"timed out waiting for {label}; last={last!r}")


def screenshot(base: str, path: Path, selector: str) -> None:
    execute(base, f"document.querySelector({json.dumps(selector)}).scrollIntoView({{block:'start'}});return true")
    time.sleep(1)
    encoded = request("GET", base + "/screenshot")
    if not isinstance(encoded, str):
        raise RuntimeError("browser did not return screenshot")
    path.write_bytes(base64.b64decode(encoded))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--chromedriver", type=Path, required=True)
    parser.add_argument("--chrome", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--screenshot-dir", type=Path, required=True)
    parser.add_argument("--port", type=int, default=9517)
    args = parser.parse_args()
    args.screenshot_dir.mkdir(parents=True, exist_ok=True)
    report = args.report.resolve()
    server = f"http://127.0.0.1:{args.port}"
    process = subprocess.Popen(
        [str(args.chromedriver), f"--port={args.port}", f"--log-path={args.output.with_suffix('.chromedriver.log')}", "--verbose"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    session_id: str | None = None
    errors: list[str] = []
    try:
        deadline = time.monotonic() + 20
        while True:
            try:
                request("GET", server + "/status", timeout=2)
                break
            except Exception:
                if time.monotonic() >= deadline:
                    raise RuntimeError("chromedriver did not become ready")
                time.sleep(0.25)
        capabilities = {"capabilities": {"alwaysMatch": {
            "browserName": "chrome", "pageLoadStrategy": "normal",
            "goog:chromeOptions": {"binary": str(args.chrome), "args": [
                "--headless=new", "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage",
                "--allow-file-access-from-files", "--window-size=1600,1200",
                "--disable-background-networking", "--disable-component-update", "--no-first-run",
            ]}, "goog:loggingPrefs": {"browser": "ALL"},
        }}}
        session = request("POST", server + "/session", capabilities)
        if not isinstance(session, dict):
            raise RuntimeError(f"unexpected session response: {session!r}")
        session_id = str(session["sessionId"])
        base = f"{server}/session/{session_id}"
        request("POST", base + "/timeouts", {"pageLoad": 600_000, "script": 600_000})
        started = time.monotonic()
        request("POST", base + "/url", {"url": report.as_uri()}, timeout=660)
        wait_for(base, "return document.readyState === 'complete'", 60, "document complete")
        global_ready_s = time.monotonic() - started
        wait_for(base, "return document.getElementById('story-ready')?.textContent.includes('均已从完整数据渲染')", 240, "human story rendering")
        story_rendered_s = time.monotonic() - started
        wait_for(base, "return document.getElementById('global-ready')?.textContent.includes('已从float64')", 180, "global rendering")
        global_rendered_s = time.monotonic() - started
        wait_for(base, "return document.querySelector('[data-adc=\"0\"]')?.dataset.ready === '1'", 420, "ADC0 rendering")
        adc0_rendered_s = time.monotonic() - started
        execute(base, "let a=document.querySelector('[data-adc=\"0\"] .technical-atlas');a.open=true;a.querySelectorAll('.js-plotly-plot').forEach(p=>Plotly.Plots.resize(p));return true")
        initial = execute(base, """let ids=['adu-hist','allan-global','allan-examples','integration-story','acf-story','global-bandpass','global-sigma','global-repro','band-0','density-0','spur-0','sigmaheat-0','ratioheat-0','acfheat-0','adevheat-0','integration-0','integrationdist-0','acfbin-0','adevbin-0','psdbin-0','native-0','hist-0'];let plots=ids.map(id=>{let e=document.getElementById(id),l=e?._fullLayout,d=e?._fullData||[];return {id,x:l?.xaxis?.title?.text||'',x2:l?.xaxis2?.title?.text||'',y:l?.yaxis?.title?.text||'',traces:d.length,names:d.map(t=>t.name||''),colorbars:d.filter(t=>t.type==='heatmap').map(t=>t.colorbar?.title?.text||''),points:d.map(t=>t.x?.length||0)}});return {mode:META.mode,title:document.title,adcSections:document.querySelectorAll('.adc').length,payloads:document.querySelectorAll('script[type="application/octet-stream"]').length,plotly:Plotly.version,plots,externalResources:performance.getEntriesByType('resource').filter(x=>/^https?:/.test(x.name)).map(x=>x.name),bandX:[document.getElementById('global-bandpass').data[0].x[0],document.getElementById('global-bandpass').data[0].x.at(-1)],bandBins:[document.getElementById('global-bandpass').data[0].customdata[0][0],document.getElementById('global-bandpass').data[0].customdata.at(-1)[0]],canvas:{width:document.querySelector('.dynamic-canvas').width,height:document.querySelector('.dynamic-canvas').height},story:{allanTau:document.getElementById('allan-global').data[2].x,allanWhite:document.getElementById('allan-global').data.some(t=>(t.name||'').includes('理想白噪声 = 1')),examplesWhite:document.getElementById('allan-examples').data.some(t=>(t.name||'').includes('τ^-1/2')),integrationWhite:document.getElementById('integration-story').data.some(t=>(t.name||'').includes('理想白噪声')),acfZero:document.getElementById('acf-story').data.some(t=>(t.name||'').includes('参考 = 0')),presets:Array.from(document.querySelectorAll('[data-adc="0"] .preset'),b=>b.dataset.preset),defaultBin:Number(document.querySelector('[data-adc="0"] .bin').value),expectedBin:META.science_story.adc_presets['0'].representative,complexRmsInAdu:document.getElementById('adu').innerText.includes('complex RMS'),placeholderAxis:plots.some(p=>[p.x,p.x2,p.y].some(x=>x==='Click to enter axis title'))}}""")
        if not isinstance(initial, dict) or initial.get("plotly") != "4.0.0":
            errors.append("Plotly 4.0.0 did not initialize")
        if initial.get("externalResources"):
            errors.append(f"network resources observed: {initial['externalResources']}")
        if initial.get("bandX") != [860, 1179.921875] or initial.get("bandBins") != [2048, 2047]:
            errors.append(f"frequency order mismatch: {initial.get('bandX')} {initial.get('bandBins')}")
        story_check = initial.get("story", {})
        if story_check.get("allanTau") != [0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1, 2, 4, 8, 15, 30]:
            errors.append(f"Allan main plot does not show all 12 tau: {story_check.get('allanTau')}")
        if not all(story_check.get(key) for key in ("allanWhite", "examplesWhite", "integrationWhite", "acfZero")):
            errors.append(f"missing white-noise or zero-correlation references: {story_check}")
        if story_check.get("presets") != ["representative", "worst_integration", "strongest_memory", "fixed_960mhz"]:
            errors.append(f"frequency shortcuts mismatch: {story_check.get('presets')}")
        if story_check.get("defaultBin") != story_check.get("expectedBin") or story_check.get("defaultBin") == 3328:
            errors.append(f"default bin is not deterministic ordinary representative: {story_check}")
        if story_check.get("complexRmsInAdu") or story_check.get("placeholderAxis"):
            errors.append(f"human-readable body or axis-title contract failed: {story_check}")
        for plot in initial.get("plots", []):
            if not plot["x"] or not plot["y"]:
                errors.append(f"missing axis title: {plot['id']}")
            if plot["id"] in {"global-bandpass", "global-sigma", "global-repro", "band-0", "density-0", "spur-0", "sigmaheat-0", "ratioheat-0", "acfheat-0", "adevheat-0"} and plot["x2"] != "global_bin":
                errors.append(f"missing global_bin top axis: {plot['id']}")
            if plot["id"] in {"global-sigma", "global-repro", "sigmaheat-0", "ratioheat-0", "acfheat-0", "adevheat-0"} and not all(plot["colorbars"]):
                errors.append(f"missing heatmap colorbar title: {plot['id']}")
        plot_index = {plot["id"]: plot for plot in initial.get("plots", [])}
        for plot_id, traces in (("adu-hist", 16), ("allan-global", 5), ("allan-examples", 4), ("integration-story", 4), ("acf-story", 4)):
            if plot_index.get(plot_id, {}).get("traces") != traces:
                errors.append(f"main story trace count mismatch for {plot_id}: {plot_index.get(plot_id)}")
        lazy_adc_checks = []
        if initial.get("mode") == "full":
            for adc in range(1, 8):
                execute(base, f"let b=document.querySelector('[data-adc=\"{adc}\"]');b.open=true;b.dataset.ready='';b.querySelector('.render').click();return true")
                wait_for(base, f"return document.querySelector('[data-adc=\"{adc}\"]')?.dataset.ready === '1'", 420, f"lazy ADC{adc} render")
                check = execute(base, f"let b=document.querySelector('[data-adc=\"{adc}\"]');return {{adc:{adc},facts:b.querySelector('.selected-facts').textContent,plots:b.querySelectorAll('.js-plotly-plot').length,canvas:[b.querySelector('.dynamic-canvas').width,b.querySelector('.dynamic-canvas').height]}}")
                lazy_adc_checks.append(check)
                if check["plots"] != 14 or f"ADC{adc}" not in check["facts"]:
                    errors.append(f"lazy ADC{adc} render contract mismatch: {check}")
        preset_checks = []
        for preset in ("representative", "worst_integration", "strongest_memory", "fixed_960mhz"):
            expected_bin = execute(base, f"return META.science_story.adc_presets['0'][{json.dumps(preset)}]")
            execute(base, f"let b=document.querySelector('[data-adc=\"0\"]');b.dataset.ready='';b.querySelector('[data-preset={json.dumps(preset)}]').click();return true")
            wait_for(base, "return document.querySelector('[data-adc=\"0\"]')?.dataset.ready === '1'", 240, f"ADC0 preset {preset}")
            check = execute(base, "let b=document.querySelector('[data-adc=\"0\"]');return {bin:Number(b.querySelector('.bin').value),facts:b.querySelector('.selected-facts').textContent,adevNames:document.getElementById('adevbin-0').data.map(t=>t.name||'')} ")
            preset_checks.append({"preset": preset, "expected_bin": expected_bin, "result": check})
            if check["bin"] != expected_bin or f"bin {expected_bin}" not in check["facts"] or not any("τ^-1/2" in name for name in check["adevNames"]):
                errors.append(f"preset failed for {preset}: {check}")
        selector_checks = []
        for scan_value, scan_label, global_bin in ((1, "B", 100), (0, "A", 0), (0, "A", 2048), (0, "A", 3328), (0, "A", 4095)):
            execute(base, f"let b=document.querySelector('[data-adc=\"0\"]');b.dataset.ready='';b.querySelector('.scan').value='{scan_value}';b.querySelector('.bin').value='{global_bin}';b.querySelector('.render').click();return true")
            wait_for(base, "return document.querySelector('[data-adc=\"0\"]')?.dataset.ready === '1'", 240, f"ADC0 scan {scan_label} bin {global_bin}")
            check = execute(base, "let b=document.querySelector('[data-adc=\"0\"]');return {facts:b.querySelector('.selected-facts').textContent,rows:b.querySelectorAll('.selected-table tbody tr').length,distributionTraces:document.getElementById('integrationdist-0').data.length}")
            selector_checks.append({"scan": scan_label, "global_bin": global_bin, "result": check})
            if f"bin {global_bin}" not in check["facts"] or check["rows"] != 4 or check["distributionTraces"] != 4:
                errors.append(f"selector failed for scan {scan_label} bin {global_bin}: {check}")
        execute(base, """document.getElementById('table-scan').value='A';document.getElementById('table-adc').value='0';document.getElementById('table-bin0').value='3328';document.getElementById('table-bin1').value='3328';document.getElementById('table-exact-value').value='';document.getElementById('table-search').click();return true""")
        wait_for(base, "return document.getElementById('table-status').textContent.includes('完整匹配 1 行')", 180, "table exact bin range")
        table = execute(base, "return {status:document.getElementById('table-status').textContent,rows:document.querySelectorAll('#table-out tbody tr').length,dictionary:document.querySelectorAll('.dictionary tbody tr').length,headers:window.HEADER?.length||HEADER.length,sourceRows:ROWS.length}")
        expected_source_rows = 12288 if initial.get("mode") == "sample" else 98304
        if table["rows"] != 1 or table["dictionary"] != table["headers"] or table["sourceRows"] != expected_source_rows:
            errors.append(f"sample table contract mismatch: {table}")
        screenshots = {
            "summary": args.screenshot_dir / "stage35-v2-sample-summary-1600x1200.png",
            "allan": args.screenshot_dir / "stage35-v2-sample-allan-1600x1200.png",
            "global": args.screenshot_dir / "stage35-v2-sample-frequency-1600x1200.png",
            "adc0": args.screenshot_dir / "stage35-v2-sample-adc0-1600x1200.png",
            "table": args.screenshot_dir / "stage35-v2-sample-table-1600x1200.png",
            "print": args.screenshot_dir / "stage35-v2-sample-print-1600x1200.png",
        }
        screenshot(base, screenshots["summary"], "#summary")
        screenshot(base, screenshots["allan"], "#allan")
        screenshot(base, screenshots["global"], "#frequency")
        screenshot(base, screenshots["adc0"], "#adc-0")
        execute(base, "document.querySelector('#technical>details').open=true;return true")
        screenshot(base, screenshots["table"], "#technical")
        request("POST", base + "/goog/cdp/execute", {"cmd": "Emulation.setEmulatedMedia", "params": {"media": "print"}})
        screenshot(base, screenshots["print"], "#allan")
        logs = request("POST", base + "/log", {"type": "browser"})
        severe = [entry for entry in logs if entry.get("level") == "SEVERE"] if isinstance(logs, list) else []
        if severe:
            errors.append(f"severe console entries: {len(severe)}")
        result = {
            "format": "T510_STAGE35_S2_HTML_BROWSER_VERIFICATION_V2",
            "status": "PASS" if not errors else "FAIL", "offline_file_url": report.as_uri(),
            "timing_seconds": {"document_complete": global_ready_s, "story_rendered": story_rendered_s, "global_rendered": global_rendered_s, "adc0_rendered": adc0_rendered_s},
            "initial": initial, "lazy_adc_checks": lazy_adc_checks, "preset_checks": preset_checks,
            "selector_checks": selector_checks, "table": table,
            "severe_console_entries": severe,
            "screenshots": {key: str(path.resolve()) for key, path in screenshots.items()},
            "errors": errors,
        }
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if not errors else 1
    finally:
        if session_id is not None:
            try:
                request("DELETE", f"{server}/session/{session_id}", timeout=20)
            except Exception:
                pass
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


if __name__ == "__main__":
    raise SystemExit(main())
