#!/usr/bin/env python3
"""Add sealed PL-temperature telemetry to the historical Stage 35 explorer."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.request
from typing import Any


def unix_ms() -> int:
    return time.time_ns() // 1_000_000


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def identity(path: Path) -> dict[str, Any]:
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": sha256_file(path)}


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".partial")
    with partial.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, sort_keys=True)
        stream.write("\n")
    partial.replace(path)


def request_json(url: str) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=180) as response:
        value = json.load(response)
    if not isinstance(value, dict):
        raise RuntimeError(f"non-object response from {url}")
    return value


def temperature_product(telemetry_path: Path, queue_state_path: Path) -> dict[str, Any]:
    telemetry = json.loads(telemetry_path.read_text(encoding="utf-8"))
    queue_state = json.loads(queue_state_path.read_text(encoding="utf-8"))
    phase = next(item for item in queue_state["phases"] if item.get("label") == "time-formal")
    start_ms = int(phase["capture_status"]["started_unix_ms"])
    end_ms = start_ms + int(phase["duration_seconds"]) * 1000
    by_timestamp: dict[int, dict[str, float]] = {}
    for poll in telemetry:
        for record in poll.get("board", {}).get("records", []):
            ams = record.get("ams") or {}
            timestamp = ams.get("captured_at_unix_ms")
            pl = (ams.get("temperatures_c") or {}).get("pl_temp")
            if timestamp is None or not isinstance(pl, dict):
                continue
            timestamp = int(timestamp)
            if start_ms <= timestamp <= end_ms:
                by_timestamp[timestamp] = {
                    "mean": float(pl["mean"]), "min": float(pl["min"]), "max": float(pl["max"]),
                }
    ordered = sorted(by_timestamp.items())
    if len(ordered) < 880:
        raise RuntimeError(f"expected at least 880 in-window PL temperature points, got {len(ordered)}")
    return {
        "format": "T510_STAGE35_TIME_TEMPERATURE_V1",
        "sensor": "pl_temp", "unit": "degC", "points": len(ordered),
        "sampling": "original board AMS telemetry at approximately 1 Hz; no interpolation",
        "capture_start_unix_ms": start_ms, "capture_duration_seconds": 900,
        "coverage_seconds": (ordered[-1][0] - start_ms) / 1000.0,
        "time_s": [(timestamp - start_ms) / 1000.0 for timestamp, _ in ordered],
        "mean_c": [value["mean"] for _, value in ordered],
        "min_c": [value["min"] for _, value in ordered],
        "max_c": [value["max"] for _, value in ordered],
        "source": identity(telemetry_path), "queue_state": identity(queue_state_path),
    }


def checked(command: list[str], evidence: list[dict[str, Any]], timeout: int = 120) -> None:
    result = subprocess.run(command, text=True, capture_output=True, timeout=timeout, check=False)
    evidence.append({"argv": command, "returncode": result.returncode,
                     "stdout": result.stdout, "stderr": result.stderr})
    if result.returncode:
        raise RuntimeError(f"command failed: {command}: {result.stderr}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--source-app", type=Path, default=Path("/opt/t510-stage35-explorer/current"))
    parser.add_argument("--source-config", type=Path, required=True)
    parser.add_argument("--capture-queue", type=Path, required=True)
    parser.add_argument("--server", type=Path, required=True)
    parser.add_argument("--javascript", type=Path, required=True)
    parser.add_argument("--legend-verifier", type=Path, required=True)
    parser.add_argument("--chromedriver", type=Path, required=True)
    parser.add_argument("--chromium", type=Path, default=Path("/snap/bin/chromium"))
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--candidate-port", type=int, default=18037)
    parser.add_argument("--lock", type=Path, default=Path("/run/lock/t510-stage35-temperature-overlay.lock"))
    args = parser.parse_args()

    args.lock.parent.mkdir(parents=True, exist_ok=True)
    with args.lock.open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        root = args.output_root.resolve()
        root.mkdir(parents=True, exist_ok=False)
        app, data, evidence_dir = root / "app", root / "data", root / "evidence"
        data.mkdir(); evidence_dir.mkdir()
        state = {"format": "T510_STAGE35_TEMPERATURE_OVERLAY_QUEUE_V1", "status": "running",
                 "started_unix_ms": unix_ms(), "output_root": str(root)}
        write_json(root / "queue_state.json", state)
        process: subprocess.Popen[str] | None = None
        published = False
        commands: list[dict[str, Any]] = []
        try:
            telemetry = args.capture_queue / "evidence/phase_01_telemetry.json"
            queue_state = args.capture_queue / "queue_state.json"
            for path in (args.source_app, args.source_config, telemetry, queue_state,
                         args.server, args.javascript, args.legend_verifier,
                         args.chromium, args.chromedriver, args.python):
                if not path.exists():
                    raise RuntimeError(f"missing input: {path}")
            product = temperature_product(telemetry, queue_state)
            write_json(data / "time_temperature.json", product)
            shutil.copytree(args.source_app, app)
            app.chmod(0o755)
            (app / "static").chmod(0o755)
            (app / "t510_stage35_explorer.py").unlink()
            (app / "static/stage35-app.js").unlink()
            shutil.copy2(args.server, app / "t510_stage35_explorer.py")
            shutil.copy2(args.javascript, app / "static/stage35-app.js")
            config = json.loads(args.source_config.read_text(encoding="utf-8"))
            config["time_temperature"] = str(data / "time_temperature.json")
            write_json(data / "app_config.json", config)

            base = f"http://127.0.0.1:{args.candidate_port}"
            process = subprocess.Popen([
                str(args.python), str(app / "t510_stage35_explorer.py"),
                "--config", str(data / "app_config.json"), "--helper-dir", str(app / "helpers"),
                "--static-root", str(app / "static"), "--bind", f"127.0.0.1:{args.candidate_port}",
            ], text=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            for _ in range(120):
                if process.poll() is not None:
                    raise RuntimeError(f"candidate exited: {process.stderr.read()}")
                try:
                    if request_json(base + "/healthz").get("application") == "stage35-simple":
                        break
                except Exception:
                    time.sleep(.25)
            else:
                raise RuntimeError("candidate did not become healthy")
            meta = request_json(base + "/api/v2/meta")
            series = request_json(base + "/api/v2/timeseries?domain=time_long_single&adc=0&cadence_ms=100")
            temp = series.get("temperature", {})
            if (meta.get("time_temperature", {}).get("points") != product["points"]
                    or len(temp.get("time_s", [])) != product["points"]):
                raise RuntimeError("candidate temperature API coverage mismatch")
            if not (39.0 < min(temp["mean_c"]) < max(temp["mean_c"]) < 42.0):
                raise RuntimeError("candidate PL temperature range is implausible")
            write_json(evidence_dir / "numeric_verification.json", {
                "status": "PASS", "meta": meta["time_temperature"],
                "time_100ms_points": len(series["time_s"]),
                "temperature_points": len(temp["time_s"]),
                "temperature_mean_c_range": [min(temp["mean_c"]), max(temp["mean_c"])],
            })

            profile = Path.home() / "snap/chromium/common/t510-stage35-browser" / root.name
            profile.parent.mkdir(parents=True, exist_ok=True)
            browser = subprocess.run([
                str(args.chromium), "--headless=new", "--no-sandbox", "--disable-dev-shm-usage",
                "--enable-unsafe-swiftshader", "--use-gl=angle", "--use-angle=swiftshader",
                "--window-size=1600,1200", f"--user-data-dir={profile}",
                "--virtual-time-budget=120000", "--dump-dom", base + "/?mode=single&adcs=0",
            ], text=True, capture_output=True, timeout=300, check=False)
            (evidence_dir / "browser_dom.html").write_text(browser.stdout, encoding="utf-8")
            (evidence_dir / "browser_stderr.txt").write_text(browser.stderr, encoding="utf-8")
            shutil.rmtree(profile, ignore_errors=True)
            if browser.returncode or "PL温度来自同一正式窗口" not in browser.stdout or "加载失败：" in browser.stdout:
                raise RuntimeError("browser did not render the PL temperature overlay")
            write_json(evidence_dir / "browser_verification.json", {"status": "PASS"})
            checked([
                str(args.python), str(args.legend_verifier), "--url", base,
                "--chromium", str(args.chromium), "--chromedriver", str(args.chromedriver),
                "--output", str(evidence_dir / "visibility_legend_verification.json"),
            ], commands, timeout=300)
            process.terminate(); process.wait(timeout=10); process = None

            install = Path("/opt/t510-stage35-explorer")
            staged = install / ".current.next"
            unit = root / "t510-stage35-explorer.service"
            unit.write_text(
                "[Unit]\nDescription=T510 Stage 35 read-only human explorer\nAfter=network-online.target\n\n"
                "[Service]\nType=simple\nUser=astrolab\nGroup=astrolab\n"
                f"WorkingDirectory={install}/current\nExecStart={args.python} {install}/current/t510_stage35_explorer.py "
                f"--config {data}/app_config.json --helper-dir {install}/current/helpers "
                f"--static-root {install}/current/static --bind 0.0.0.0:8035\n"
                "Restart=on-failure\nRestartSec=2\nNoNewPrivileges=true\nPrivateTmp=true\n"
                "ProtectHome=true\nProtectSystem=full\nReadOnlyPaths=/var/lib/t510\n\n"
                "[Install]\nWantedBy=multi-user.target\n", encoding="utf-8")
            for command in (["sudo", "-n", "rm", "-rf", str(staged)],
                            ["sudo", "-n", "cp", "-a", str(app), str(staged)],
                            ["sudo", "-n", "rm", "-rf", str(install / "current")],
                            ["sudo", "-n", "mv", str(staged), str(install / "current")],
                            ["sudo", "-n", "cp", str(unit), "/etc/systemd/system/t510-stage35-explorer.service"],
                            ["sudo", "-n", "systemctl", "daemon-reload"],
                            ["sudo", "-n", "systemctl", "restart", "t510-stage35-explorer.service"]):
                if command[:4] == ["sudo", "-n", "rm", "-rf"] and command[-1] == str(install / "current"):
                    published = True
                checked(command, commands)
            write_json(evidence_dir / "publish_process.json", commands)
            for _ in range(60):
                try:
                    if request_json("http://127.0.0.1:8035/healthz").get("application") == "stage35-simple":
                        break
                except Exception:
                    time.sleep(.5)
            else:
                raise RuntimeError("live explorer did not become healthy")
            live = request_json("http://127.0.0.1:8035/api/v2/timeseries?domain=time_long_single&adc=0&cadence_ms=100")
            old = request_json("http://127.0.0.1:8036/healthz")
            if (len(live.get("temperature", {}).get("time_s", [])) != product["points"]
                    or old.get("application") != "stage36-simple"):
                raise RuntimeError("live verification failed")
            write_json(evidence_dir / "live_verification.json", {
                "status": "PASS", "url": "http://192.168.100.162:8035/",
                "temperature_points": len(temp["time_s"]), "stage36_8036": old,
            })
            files = [identity(path) for path in sorted(root.rglob("*"))
                     if path.is_file() and path.name not in {"artifact_manifest.json", "queue_state.json"}]
            write_json(root / "artifact_manifest.json", {
                "format": "T510_STAGE35_TEMPERATURE_OVERLAY_ARTIFACT_MANIFEST_V1",
                "complete": True, "files": files,
            })
            state.update(status="completed", finished_unix_ms=unix_ms(), temperature_points=len(temp["time_s"]))
            write_json(root / "queue_state.json", state)
            return 0
        except Exception as exc:
            if process is not None and process.poll() is None:
                process.terminate()
            if published:
                subprocess.run(["sudo", "-n", "systemctl", "stop", "t510-stage35-explorer.service"], check=False)
            state.update(status="failed", finished_unix_ms=unix_ms(), error=f"{type(exc).__name__}: {exc}")
            write_json(root / "queue_state.json", state)
            raise


if __name__ == "__main__":
    raise SystemExit(main())
