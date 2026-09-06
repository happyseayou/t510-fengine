#!/usr/bin/env python3
"""Verify that a visibility legend toggles its amplitude and both phase traces."""

from __future__ import annotations

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
        url = args.url.rstrip("/") + "/?mode=pair&pairs=0-1&bins=128.593750MHz&pair_visibility_ms=100"
        request("POST", f"{driver_url}/session/{session}/url", {"url": url})
        wait_until(lambda: "权威数据就绪" in execute(
            driver_url, session, "return document.getElementById('health').textContent"), 180)
        execute(driver_url, session, """
          const p=document.querySelector('#pairFengineCards .plot');
          p.scrollIntoView({block:'center',behavior:'instant'});
          p.querySelector('.gpu-placeholder')?.click(); return true;
        """)
        wait_until(lambda: execute(driver_url, session, """
          return document.querySelector('#pairFengineCards .plot')?.dataset.gpuState==='rendered';
        """), 60)

        inspect = """
          const p=document.querySelector('#pairFengineCards .plot .js-plotly-plot');
          const rows=(p.data||[]).slice(0,3).map((t,index)=>({index,name:t.name,
            axis:t.yaxis||'y',group:t.legendgroup||'',visible:t.visible,points:(t.x||[]).length}));
          return {rows,groupclick:p.layout?.legend?.groupclick||'',legends:p.querySelectorAll('.legendtoggle').length};
        """
        before = execute(driver_url, session, inspect)
        if (len(before["rows"]) != 3 or len({row["group"] for row in before["rows"]}) != 1
                or not before["rows"][0]["group"] or before["groupclick"] != "togglegroup"
                or before["legends"] < 1):
            raise RuntimeError(f"visibility traces are not configured as one legend group: {before}")

        element = request("POST", f"{driver_url}/session/{session}/element",
                          {"using": "css selector", "value": ".legendtoggle"})
        element_id = element[ELEMENT_KEY]
        request("POST", f"{driver_url}/session/{session}/element/{element_id}/click", {})
        time.sleep(1)
        hidden = execute(driver_url, session, inspect)
        displayed = [row for row in hidden["rows"] if row["points"] > 0]
        if (not any(row["axis"] == "y2" for row in displayed)
                or any(row["visible"] != "legendonly" for row in displayed)):
            raise RuntimeError(f"legend click did not hide amplitude and phase together: {hidden}")

        element = request("POST", f"{driver_url}/session/{session}/element",
                          {"using": "css selector", "value": ".legendtoggle"})
        request("POST", f"{driver_url}/session/{session}/element/{element[ELEMENT_KEY]}/click", {})
        time.sleep(1)
        restored = execute(driver_url, session, inspect)
        if any(row["visible"] is not True for row in restored["rows"] if row["points"] > 0):
            raise RuntimeError(f"second legend click did not restore amplitude and phase together: {restored}")

        write_json(args.output, {"format": "T510_VISIBILITY_LEGEND_VERIFY_V1", "status": "PASS",
                                 "url": url, "before": before, "hidden": hidden,
                                 "restored": restored})
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
