#!/usr/bin/env python3
"""Exercise the Stage 35 report through an offline headless Chromium session."""

from __future__ import annotations

import argparse
import base64
import json
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path


def request(method: str, url: str, value: object | None = None, timeout: int = 240) -> object:
    data = None if value is None else json.dumps(value).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        payload = json.loads(response.read())
    value = payload.get("value")
    if isinstance(value, dict) and value.get("error"):
        raise RuntimeError(json.dumps(value, ensure_ascii=False))
    return value


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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--chromedriver", type=Path, required=True)
    parser.add_argument("--chrome", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--screenshot", type=Path, required=True)
    parser.add_argument("--port", type=int, default=9516)
    args = parser.parse_args()
    report = args.report.resolve()
    server = f"http://127.0.0.1:{args.port}"
    driver_log = args.output.with_suffix(".chromedriver.log")
    process = subprocess.Popen(
        [str(args.chromedriver), f"--port={args.port}", f"--log-path={driver_log}", "--verbose"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    session_id: str | None = None
    try:
        deadline = time.monotonic() + 15
        while True:
            try:
                request("GET", server + "/status", timeout=2)
                break
            except Exception:
                if time.monotonic() >= deadline:
                    raise RuntimeError("chromedriver did not become ready")
                time.sleep(0.25)
        capabilities = {
            "capabilities": {
                "alwaysMatch": {
                    "browserName": "chrome",
                    "goog:chromeOptions": {
                        "binary": str(args.chrome),
                        "args": [
                            "--headless=new", "--no-sandbox", "--disable-gpu",
                            "--disable-dev-shm-usage", "--allow-file-access-from-files",
                            "--window-size=1600,1200", "--disable-background-networking",
                            "--disable-component-update", "--no-first-run",
                        ],
                    },
                    "goog:loggingPrefs": {"browser": "ALL"},
                    "pageLoadStrategy": "normal",
                }
            }
        }
        session = request("POST", server + "/session", capabilities)
        if not isinstance(session, dict):
            raise RuntimeError(f"unexpected session response: {session!r}")
        session_id = str(session["sessionId"])
        base = f"{server}/session/{session_id}"
        request("POST", base + "/timeouts", {"pageLoad": 300_000, "script": 300_000})
        request("POST", base + "/url", {"url": report.as_uri()}, timeout=360)
        wait_for(base, "return document.readyState === 'complete'", 60, "document complete")
        wait_for(
            base,
            "return document.querySelector('.adc')?.dataset.ready === '1' && document.getElementById('time-rms')?.width === 1200",
            180,
            "initial ADC and TIME render",
        )
        initial = execute(
            base,
            """return {title:document.title,adcSections:document.querySelectorAll('.adc').length,
payloads:document.querySelectorAll('script[type="application/octet-stream"]').length,
firstReady:document.querySelector('.adc').dataset.ready,timeWidth:document.getElementById('time-rms').width,
externalResources:performance.getEntriesByType('resource').filter(x=>/^https?:/.test(x.name)).map(x=>x.name),
bodyText:document.body.innerText.includes('98,304')&&document.body.innerText.includes('未定标')};""",
        )
        execute(
            base,
            """let b=document.querySelector('[data-adc="0"]');b.dataset.ready='';b.querySelector('.scan').value='1';b.querySelector('.bin').value='100';b.querySelector('.render').click();return true;""",
        )
        wait_for(base, "return document.querySelector('[data-adc=\"0\"]')?.dataset.ready === '1'", 120, "ADC0 selector update")
        selector = execute(
            base,
            """let b=document.querySelector('[data-adc="0"]');return {facts:b.querySelector('.facts').textContent,
acfWidth:b.querySelector('.acfline').width,psdWidth:b.querySelector('.psd').width,nativeWidth:b.querySelector('.native').width,
dynamicMinWidth:b.querySelector('.dynamicmin').width,dynamicMaxWidth:b.querySelector('.dynamicmax').width};""",
        )
        execute(
            base,
            """document.getElementById('tscan').value='A';document.getElementById('tadc').value='0';
document.getElementById('tbin0').value='3328';document.getElementById('tbin1').value='3328';
document.getElementById('tsearch').click();return true;""",
        )
        wait_for(base, "return document.getElementById('tablestatus').textContent.includes('matched 1')", 120, "full numeric table search")
        table = execute(base, "return {status:document.getElementById('tablestatus').textContent,rows:document.querySelectorAll('#tableout tbody tr').length,columns:document.querySelectorAll('#tableout thead th').length}")
        logs = request("POST", base + "/log", {"type": "browser"})
        severe = [entry for entry in logs if entry.get("level") == "SEVERE"] if isinstance(logs, list) else []
        screenshot = request("GET", base + "/screenshot")
        if not isinstance(screenshot, str):
            raise RuntimeError("browser did not return a screenshot")
        args.screenshot.write_bytes(base64.b64decode(screenshot))
        result = {
            "format": "T510_STAGE35_S2_HTML_BROWSER_VERIFICATION_V1",
            "status": "PASS" if not severe else "FAIL",
            "offline_file_url": report.as_uri(),
            "initial": initial,
            "selector": selector,
            "table": table,
            "severe_console_entries": severe,
            "screenshot": str(args.screenshot.resolve()),
        }
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if not severe else 1
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
