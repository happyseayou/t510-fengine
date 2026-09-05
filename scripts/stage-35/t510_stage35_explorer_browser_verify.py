#!/usr/bin/env python3
"""Launch a candidate explorer and verify its real browser/network contract."""

from __future__ import annotations

import argparse
import base64
import json
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


def request(method: str, url: str, value: Any = None, timeout: float = 30) -> Any:
    data = None if value is None else json.dumps(value).encode()
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        payload = response.read()
    return json.loads(payload) if payload else None


def webdriver(method: str, base: str, path: str, value: Any = None) -> Any:
    result = request(method, base + path, value, timeout=120)
    value = result.get("value") if isinstance(result, dict) else None
    if isinstance(value, dict) and value.get("error"):
        raise RuntimeError(json.dumps(value, ensure_ascii=False))
    return value


def execute(base: str, session: str, script: str) -> Any:
    return webdriver("POST", base, f"/session/{session}/execute/sync",
                     {"script": script, "args": []})


def wait_http(url: str, timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            request("GET", url, timeout=2)
            return
        except Exception:
            time.sleep(.2)
    raise TimeoutError(f"server did not become ready: {url}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--server", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--helper-dir", type=Path, required=True)
    parser.add_argument("--static-root", type=Path, required=True)
    parser.add_argument("--chrome", type=Path, required=True)
    parser.add_argument("--chromedriver", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--screenshot", type=Path, required=True)
    parser.add_argument("--app-port", type=int, default=8036)
    parser.add_argument("--driver-port", type=int, default=9518)
    args = parser.parse_args()
    app_base = f"http://127.0.0.1:{args.app_port}"
    driver_base = f"http://127.0.0.1:{args.driver_port}"
    app = subprocess.Popen([
        str(args.python), str(args.server), "--config", str(args.config),
        "--helper-dir", str(args.helper_dir), "--static-root", str(args.static_root),
        "--bind", f"127.0.0.1:{args.app_port}",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    driver = subprocess.Popen([
        str(args.chromedriver), f"--port={args.driver_port}", "--verbose",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    session = None
    evidence: dict[str, Any] = {"format": "T510_STAGE35_EXPLORER_BROWSER_VERIFY_V1",
                                "errors": []}
    try:
        wait_http(app_base + "/healthz")
        wait_http(driver_base + "/status")
        session = webdriver("POST", driver_base, "/session", {"capabilities": {"alwaysMatch": {
            "browserName": "chrome", "pageLoadStrategy": "normal",
            "goog:loggingPrefs": {"browser": "ALL", "performance": "ALL"},
            "goog:chromeOptions": {"binary": str(args.chrome), "args": [
                "--headless=new", "--no-sandbox", "--disable-gpu", "--window-size=1800,1200",
            ]},
        }}})["sessionId"]
        url = app_base + "/?adcs=0%2C1&bins=295%2C3182&scans=A&pairs=0-1%2C2-3&time=A-pre&spec=A-begin"
        webdriver("POST", driver_base, f"/session/{session}/url", {"url": url})
        deadline = time.monotonic() + 90
        health = ""
        while time.monotonic() < deadline:
            health = execute(driver_base, session, "return document.getElementById('health').textContent")
            if "权威数据就绪" in health:
                break
            time.sleep(.25)
        if "权威数据就绪" not in health:
            raise RuntimeError(f"overview did not become ready: {health}")
        overview_plots = execute(driver_base, session,
                                 "return document.querySelectorAll('.js-plotly-plot').length")
        overview_notes = execute(driver_base, session, """
            return Array.from(document.querySelectorAll('#overview .js-plotly-plot')).map(plot=>{
              const note=plot.closest('.figure').querySelector('.figure-note');
              return {id:plot.id,ready:note?.dataset.ready,
                sections:note?.querySelectorAll('.note-section').length||0,
                hasFormula:!!note?.querySelector('.note-section.formula'),
                hasSource:!!note?.querySelector('.note-section.source'),
                hasResult:!!note?.querySelector('.note-section.result')};
            });
        """)
        if not overview_notes or any(
            row["ready"] != "true" or row["sections"] != 5
            or not row["hasFormula"] or not row["hasSource"] or not row["hasResult"]
            for row in overview_notes
        ):
            raise RuntimeError(f"overview figure calculation notes are incomplete: {overview_notes}")
        execute(driver_base, session, "document.querySelector('[data-view=single]').click();return true")
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            health = execute(driver_base, session, "return document.getElementById('health').textContent")
            if "单 ADC 视图已从权威数据读取" in health:
                break
            time.sleep(.5)
        if "单 ADC 视图已从权威数据读取" not in health:
            raise RuntimeError(f"multi-ADC view did not become ready: {health}")
        url_after = webdriver("GET", driver_base, f"/session/{session}/url")
        # textContent intentionally includes the hidden tab panels: browser
        # verification must prove the complete human explanation is shipped,
        # while the active-tab checks above separately prove visible rendering.
        text = execute(driver_base, session, "return document.documentElement.textContent")
        source = execute(driver_base, session, "return document.documentElement.outerHTML")
        required = ["post-DDC IQ16 ADU", "F-engine IQ16 count", "τ", "白噪声",
                    "ACF", "complex RMS", "不是天空信号", "导出当前"]
        missing = [value for value in required if value not in text]
        if missing:
            raise RuntimeError(f"required human explanations are missing: {missing}")
        if "Click to enter axis title" in source:
            raise RuntimeError("Plotly axis placeholder is visible")
        axis_titles = execute(driver_base, session, "return Array.from(document.querySelectorAll('.xtitle,.ytitle')).map(x=>x.textContent).filter(Boolean)")
        if not axis_titles or not any("ADU" in value for value in axis_titles):
            raise RuntimeError(f"real axis titles were not rendered: {axis_titles[:8]}")
        single_plot_count = execute(driver_base, session,
                                    "return document.querySelectorAll('#single .js-plotly-plot').length")
        single_note_count = execute(driver_base, session, """
            return Array.from(document.querySelectorAll('#single .js-plotly-plot'))
              .filter(plot=>plot.closest('.figure').querySelector('.figure-note[data-ready=true] .formula')
                && plot.closest('.figure').querySelector('.figure-note[data-ready=true] .source')
                && plot.closest('.figure').querySelector('.figure-note[data-ready=true] .result')).length;
        """)
        if single_note_count != single_plot_count:
            raise RuntimeError(
                f"single-ADC formula/source/result notes {single_note_count} != plots {single_plot_count}"
            )
        heatmap_runtime = execute(
            driver_base, session,
            "return (document.getElementById('timeControl').data||[]).some(x=>x.type==='heatmap')")
        if not heatmap_runtime:
            raise RuntimeError("more-than-12 TIME comparison traces did not become a heatmap")
        white_reference_runtime = execute(driver_base, session, """
            return ['timeAllan','allanSingle'].every(id=>(document.getElementById(id).data||[])
              .some(x=>(x.name||'').includes('白噪声')));
        """)
        if not white_reference_runtime:
            raise RuntimeError("single-ADC Allan white-noise reference is missing")
        meta = request("GET", app_base + "/api/meta")
        sentinel_rf = float(meta["rf_mhz"][3328])
        rf_selection = request(
            "GET", app_base + f"/api/single?adcs=0&bins={sentinel_rf:.6f}MHz&scans=A&time_captures=A-pre"
        )
        if rf_selection.get("bins") != [3328]:
            raise RuntimeError(f"RF MHz selection did not resolve to global_bin 3328: {rf_selection.get('bins')}")
        pair_plot_count = 0
        phase_gate_runtime = False
        if meta.get("xcorr_scans"):
            execute(driver_base, session,
                    "document.querySelector('[data-view=pair]').click();return true")
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                health = execute(driver_base, session,
                                 "return document.getElementById('health').textContent")
                if "两路视图已从权威数据读取" in health:
                    break
                time.sleep(.5)
            if "两路视图已从权威数据读取" not in health:
                raise RuntimeError(f"multi-pair view did not become ready: {health}")
            pair_plot_count = execute(
                driver_base, session,
                "return document.querySelectorAll('#pair .js-plotly-plot').length")
            if pair_plot_count < 8:
                raise RuntimeError(f"pair view rendered only {pair_plot_count} plots")
            valid_samples_runtime = execute(driver_base, session, """
                const d=(document.getElementById('validSamples').data||[]);
                return d.length>0 && d.every(x=>x.y.every(v=>Number.isInteger(v)&&v>0));
            """)
            if not valid_samples_runtime:
                raise RuntimeError("pair view did not render positive integer n_valid samples")
            phase_gate_runtime = execute(driver_base, session, """
                const phase=(document.getElementById('gammaTime').data||[])
                  .filter(x=>(x.name||'').includes('phase'));
                return phase.length>0 && phase.some(x=>x.y.some(v=>v===null));
            """)
            if not phase_gate_runtime:
                raise RuntimeError("runtime phase gate did not hide weak-correlation phase samples")
            pair_note_count = execute(driver_base, session, """
                return Array.from(document.querySelectorAll('#pair .js-plotly-plot'))
                  .filter(plot=>plot.closest('.figure').querySelector('.figure-note[data-ready=true] .formula')
                    && plot.closest('.figure').querySelector('.figure-note[data-ready=true] .source')
                    && plot.closest('.figure').querySelector('.figure-note[data-ready=true] .result')).length;
            """)
            if pair_note_count != pair_plot_count:
                raise RuntimeError(
                    f"pair formula/source/result notes {pair_note_count} != plots {pair_plot_count}"
                )
        execute(driver_base, session,
                "document.querySelector('[data-view=statistics]').click();return true")
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            health = execute(driver_base, session,
                             "return document.getElementById('health').textContent")
            if "全仪器统计已读取" in health:
                break
            time.sleep(.5)
        if "全仪器统计已读取" not in health:
            raise RuntimeError(f"statistics view did not become ready: {health}")
        statistics_plot_count = execute(
            driver_base, session,
            "return document.querySelectorAll('#statistics .js-plotly-plot').length")
        statistics_note_count = execute(driver_base, session, """
            return Array.from(document.querySelectorAll('#statistics .js-plotly-plot'))
              .filter(plot=>plot.closest('.figure').querySelector('.figure-note[data-ready=true] .formula')
                && plot.closest('.figure').querySelector('.figure-note[data-ready=true] .source')
                && plot.closest('.figure').querySelector('.figure-note[data-ready=true] .result')).length;
        """)
        if statistics_note_count != statistics_plot_count:
            raise RuntimeError(
                f"statistics formula/source/result notes {statistics_note_count} != plots {statistics_plot_count}"
            )
        notes_contract = execute(driver_base, session, """
            const notes=Array.from(document.querySelectorAll('.figure-note[data-ready=true]'));
            return {
              count:notes.length,
              allHaveNumbers:notes.every(n=>/[0-9]/.test(n.querySelector('.result')?.textContent||'')),
              allHaveFormula:notes.every(n=>(n.querySelector('.formula')?.textContent||'').includes('=')),
              allHaveProvenance:notes.every(n=>(n.querySelector('.source')?.textContent||'').includes('/var/lib/t510/stage35/')),
              beside:Array.from(document.querySelectorAll('#statistics .figure-note')).every(n=>{
                const p=n.closest('.figure').querySelector('.plot'),a=p.getBoundingClientRect(),b=n.getBoundingClientRect();
                return a.right<=b.left+2 && Math.min(a.bottom,b.bottom)>Math.max(a.top,b.top);
              })
            };
        """)
        if (notes_contract["count"] < overview_plots + single_plot_count + statistics_plot_count
                or not notes_contract["allHaveNumbers"]
                or not notes_contract["allHaveFormula"]
                or not notes_contract["allHaveProvenance"]
                or not notes_contract["beside"]):
            raise RuntimeError(f"figure note browser contract failed: {notes_contract}")
        meta_provenance = meta.get("provenance", {})
        if not meta_provenance.get("time_raw") or not meta_provenance.get("self_power") \
                or not meta_provenance.get("xcorr"):
            raise RuntimeError("API meta does not expose auditable TIME/self-power/XCORR provenance")
        logs = webdriver("POST", driver_base, f"/session/{session}/log", {"type": "performance"})
        network_urls = []
        for row in logs:
            message = json.loads(row["message"])["message"]
            if message["method"] == "Network.requestWillBeSent":
                network_urls.append(message["params"]["request"]["url"])
        external = sorted({url for url in network_urls if not url.startswith(app_base) and not url.startswith("data:")})
        if external:
            raise RuntimeError(f"browser made external requests: {external}")
        console = webdriver("POST", driver_base, f"/session/{session}/log", {"type": "browser"})
        severe = [row for row in console if row.get("level") == "SEVERE"]
        if severe:
            raise RuntimeError(f"severe browser console errors: {severe}")
        encoded = webdriver("GET", driver_base, f"/session/{session}/screenshot")
        args.screenshot.write_bytes(base64.b64decode(encoded))
        try:
            request("POST", app_base + "/api/meta", {})
            raise RuntimeError("read-only server unexpectedly accepted POST")
        except urllib.error.HTTPError as error:
            if error.code != 405:
                raise
        try:
            request("GET", app_base + "/static/../app_config.json")
            raise RuntimeError("static path traversal unexpectedly succeeded")
        except urllib.error.HTTPError as error:
            if error.code != 404:
                raise
        evidence.update({
            "status": "PASS", "url": url, "url_after_interaction": url_after,
            "overview_plot_count": overview_plots,
            "single_plot_count": single_plot_count,
            "pair_plot_count": pair_plot_count,
            "statistics_plot_count": statistics_plot_count,
            "overview_figure_notes": overview_notes,
            "single_figure_note_count": single_note_count,
            "pair_figure_note_count": pair_note_count if meta.get("xcorr_scans") else 0,
            "statistics_figure_note_count": statistics_note_count,
            "figure_note_contract": notes_contract,
            "axis_titles": axis_titles, "network_request_count": len(network_urls),
            "external_network_requests": external, "severe_console_errors": severe,
            "multi_adc": True, "multi_frequency": True, "multi_pair_url": True,
            "rf_mhz_selection": rf_selection["series"][0]["rf_mhz"],
            "automatic_heatmap_runtime": heatmap_runtime,
            "white_reference_runtime": white_reference_runtime,
            "valid_samples_runtime": valid_samples_runtime if meta.get("xcorr_scans") else False,
            "csv_export_controls": execute(driver_base, session,
                                            "return !!document.getElementById('singleCsv') && !!document.getElementById('pairCsv')"),
            "phase_gate_text": "|γ|<0.05" in text,
            "phase_gate_runtime": phase_gate_runtime,
        })
    except Exception as error:
        evidence["status"] = "FAIL"
        evidence["errors"].append(f"{type(error).__name__}: {error}")
        raise
    finally:
        if session:
            try:
                webdriver("DELETE", driver_base, f"/session/{session}")
            except Exception:
                pass
        driver.terminate(); app.terminate()
        try: driver.wait(timeout=5)
        except subprocess.TimeoutExpired: driver.kill()
        try: app.wait(timeout=10)
        except subprocess.TimeoutExpired: app.kill()
        if app.stderr:
            evidence["server_stderr"] = app.stderr.read()[-8000:]
        args.output.write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
