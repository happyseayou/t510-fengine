#!/usr/bin/env python3
"""Verify formula definitions, CSS application and screenshots of both report views."""

from __future__ import annotations

import base64
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import urllib.request
from typing import Any


ELEMENT_KEY = "element-6066-11e4-a52e-4f735466cecf"


def request(method: str, url: str, value: Any = None) -> Any:
    data = None if value is None else json.dumps(value).encode()
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as response:
        payload = response.read()
    result = json.loads(payload) if payload else None
    value = result.get("value") if isinstance(result, dict) else None
    if isinstance(value, dict) and value.get("error"):
        raise RuntimeError(json.dumps(value, ensure_ascii=False))
    return value


def execute(driver: str, session: str, script: str) -> Any:
    return request("POST", f"{driver}/session/{session}/execute/sync",
                   {"script": script, "args": []})


def wait_until(operation: Any, timeout: float = 60) -> Any:
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            last = operation()
        except Exception as exc:
            last = f"{type(exc).__name__}: {exc}"
            time.sleep(.25)
            continue
        if last:
            return last
        time.sleep(.25)
    raise TimeoutError(f"browser condition did not become true: {last}")


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, sort_keys=True)
        stream.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--chromium", type=Path, default=Path("/snap/bin/chromium"))
    parser.add_argument("--chromedriver", type=Path, required=True)
    parser.add_argument("--driver-port", type=int, default=19515)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    driver_url = f"http://127.0.0.1:{args.driver_port}"
    profile = Path.home() / "snap/chromium/common/t510-legend-verifier" / str(os.getpid())
    profile.parent.mkdir(parents=True, exist_ok=True)
    driver = subprocess.Popen([str(args.chromedriver), f"--port={args.driver_port}"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    session = None
    try:
        wait_until(lambda: request("GET", driver_url + "/status"), 30)
        created = request("POST", driver_url + "/session", {"capabilities": {"alwaysMatch": {
            "browserName": "chrome", "pageLoadStrategy": "normal",
            "goog:chromeOptions": {"binary": str(args.chromium), "args": [
                "--headless=new", "--no-sandbox", "--disable-dev-shm-usage",
                "--enable-unsafe-swiftshader", "--use-gl=angle", "--use-angle=swiftshader",
                "--window-size=1600,1200", f"--user-data-dir={profile}",
            ]},
        }}})
        session = created["sessionId"]
        results = []
        for mode in ("single", "pair"):
            request("POST", f"{driver_url}/session/{session}/url", {"url": args.url + "/?mode=" + mode})
            wait_until(lambda: "权威数据就绪" in execute(driver_url, session,
                "return document.getElementById('health').textContent"), 180)
            execute(driver_url, session, "document.querySelector('.report-view:not([hidden]) .figure').scrollIntoView();")
            time.sleep(2)
            shot=request("GET", f"{driver_url}/session/{session}/screenshot")
            Path(str(args.output)+"-"+mode+".png").write_bytes(base64.b64decode(shot))
            layout = execute(driver_url, session, """
              const f=document.querySelector('.report-view:not([hidden]) .figure');
              const plot=f.querySelector('.plot').getBoundingClientRect();
              const note=f.querySelector('.explanation').getBoundingClientRect();
              return {display:getComputedStyle(f).display, plotRight:plot.right,
                noteLeft:note.left, plotTop:plot.top, noteTop:note.top,
                width:document.documentElement.clientWidth, scroll:document.documentElement.scrollWidth};
            """)
            assert layout['display']=='grid' and layout['scroll']<=layout['width']+1, layout
            assert layout['noteLeft']>=layout['plotRight'] and abs(layout['plotTop']-layout['noteTop'])<2, layout
            rows = execute(driver_url, session, """
              return [...document.querySelectorAll('.report-view:not([hidden]) .figure')].map(f=>({
                title:f.querySelector('h4').textContent,
                definitions:f.querySelectorAll('.formula-symbols p').length,
                formulas:f.querySelectorAll('.formula-line .katex').length,
                errors:f.querySelectorAll('.katex-error').length
              }));
            """)
            assert rows and all(r['definitions'] >= 4 and r['formulas'] and not r['errors'] for r in rows), rows
            results.append({"mode":mode,"figures":rows})
        write_json(args.output, {"status":"PASS", "results":results})
        print(json.dumps(results, ensure_ascii=False))
        return 0

    finally:
        if session:
            try:
                request("DELETE", f"{driver_url}/session/{session}")
            except Exception:
                pass
        driver.terminate()
        try:
            driver.wait(timeout=10)
        except subprocess.TimeoutExpired:
            driver.kill()
        shutil.rmtree(profile, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
