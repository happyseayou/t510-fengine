#!/usr/bin/env python3
"""Build, verify, and publish the Stage 36 read-only explorer on port 8036."""

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
import traceback
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

import numpy as np


FORMAT = "T510_STAGE36_EXPLORER_QUEUE_V1"
EXPECTED_QUEUE_FORMAT = "T510_STAGE36_SCIENCE_CAPTURE_MANIFEST_V1"
EXPECTED_CORE = "0x00010036"
EXPECTED_BITSTREAM = "e00c586a1d862d7c7af113361832a30093334493e49f943e3dd22bf44f950665"
TIME_GAIN = 1.9998779296875
SPEC_GAIN = 3.999755859375


def unix_ms() -> int:
    return time.time_ns() // 1_000_000


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: Any, *, exclusive: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "x" if exclusive else "w"
    with path.open(mode, encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, sort_keys=True)
        stream.write("\n")


def request_json(url: str, method: str = "GET") -> dict[str, Any]:
    request = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(request, timeout=180) as response:
        value = json.load(response)
    if not isinstance(value, dict):
        raise RuntimeError(f"non-object JSON from {url}")
    return value


def file_identity(path: Path) -> dict[str, Any]:
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": sha256_file(path)}


def component_std(array: np.ndarray, *, chunk: int) -> np.ndarray:
    count = 0
    total = np.zeros(array.shape[1:], dtype=np.float64)
    square = np.zeros(array.shape[1:], dtype=np.float64)
    for first in range(0, len(array), chunk):
        values = np.asarray(array[first:first + chunk], dtype=np.float64)
        count += len(values)
        total += np.sum(values, axis=0, dtype=np.float64)
        square += np.sum(values * values, axis=0, dtype=np.float64)
    variance = np.maximum(square / count - (total / count) ** 2, 0.0)
    return np.sqrt(variance)


def trim_spec_record(record: dict[str, Any], spectra: int = 4096) -> None:
    """Freeze the verified witness to the requested contiguous 4096 frames."""
    path = Path(record["iq16_npy"])
    source = np.load(path, mmap_mode="r")
    if len(source) < spectra:
        raise RuntimeError(f"SPEC witness contains only {len(source)} frames")
    if len(source) > spectra:
        partial = path.with_name(path.name + ".partial")
        if partial.exists():
            raise RuntimeError(f"stale SPEC crop partial exists: {partial}")
        output = np.lib.format.open_memmap(
            partial, mode="w+", dtype=source.dtype, shape=(spectra,) + source.shape[1:])
        for first in range(0, spectra, 128):
            output[first:first + 128] = source[first:first + 128]
        output.flush()
        del output, source
        partial.replace(path)
    else:
        del source
    record.update(
        spectra=spectra,
        iq16_npy_bytes=path.stat().st_size,
        iq16_npy_sha256=sha256_file(path),
        selection="first 4096 frames of the verified contiguous common sample0 interval",
    )
    if "sample0_start" in record:
        record["sample0_end"] = int(record["sample0_start"]) + spectra * 4096


class Queue:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.root = args.output_root.resolve()
        self.data = self.root / "data"
        self.app = self.root / "app"
        self.evidence = self.root / "evidence"
        self.state_path = self.root / "queue_state.json"
        self.events_path = self.root / "queue_events.jsonl"
        self.state: dict[str, Any] = {
            "format": FORMAT,
            "status": "armed",
            "created_unix_ms": unix_ms(),
            "source_commit": args.source_commit,
            "capture_queue": str(args.capture_queue),
            "output_root": str(self.root),
            "current_phase": None,
            "error": None,
            "phases": [
                {"name": name, "status": "pending"} for name in (
                    "preflight", "raw_and_long_arrays", "stage35_comparison",
                    "time_temperature",
                    "candidate_build", "numeric_api_verify", "browser_verify",
                    "publish_8036", "live_verify", "final_manifest",
                )
            ],
        }

    def save(self) -> None:
        partial = self.state_path.with_suffix(".json.partial")
        write_json(partial, self.state, exclusive=False)
        partial.replace(self.state_path)

    def event(self, event: str, **fields: Any) -> None:
        row = {"unix_ms": unix_ms(), "event": event, **fields}
        with self.events_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, sort_keys=True) + "\n")
            stream.flush(); os.fsync(stream.fileno())

    def phase(self, name: str, operation: Any) -> Any:
        item = next(row for row in self.state["phases"] if row["name"] == name)
        self.state["current_phase"] = name
        item.pop("error", None)
        item.update(status="running", started_unix_ms=unix_ms())
        self.save(); self.event("phase_start", phase=name)
        result = operation()
        item.update(status="completed", finished_unix_ms=unix_ms())
        self.save(); self.event("phase_complete", phase=name)
        return result

    def initialize(self) -> None:
        self.root.mkdir(parents=True, exist_ok=False)
        self.data.mkdir(); self.app.mkdir(); self.evidence.mkdir()
        self.save(); self.event("queue_armed")

    def preflight(self) -> None:
        manifest_path = self.args.capture_queue / "queue_manifest.json"
        checksum_path = self.args.capture_queue / "queue_manifest.sha256"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        expected = checksum_path.read_text(encoding="ascii").split()[0]
        errors = []
        if manifest.get("format") != EXPECTED_QUEUE_FORMAT or not manifest.get("complete"):
            errors.append("capture queue manifest is not complete")
        if manifest.get("core_version") != EXPECTED_CORE:
            errors.append("capture core identity mismatch")
        if manifest.get("bitstream_sha256") != EXPECTED_BITSTREAM:
            errors.append("capture bitstream identity mismatch")
        if sha256_file(manifest_path) != expected:
            errors.append("capture queue manifest SHA mismatch")
        if len(manifest.get("scans", [])) != 13:
            errors.append("capture queue does not contain all 13 scans")
        amplitude = json.loads((self.args.capture_queue / "evidence/formal_amplitude_verification.json").read_text())
        independent = json.loads((self.args.capture_queue / "evidence/independent_verification.json").read_text())
        if amplitude.get("status") != "PASS" or independent.get("status") != "PASS":
            errors.append("capture independent verification is not PASS")
        required = [self.args.server, self.args.static_source / "index.html",
                    self.args.static_source / "stage36-app.js",
                    self.args.static_source / "stage36-app.css",
                    self.args.static_source / "katex/katex.min.js",
                    self.args.static_source / "katex/katex.min.css",
                    self.args.helper_dir / "t510_stage35_explorer_prepare.py",
                    self.args.helper_dir / "t510_stage35_simple_prepare.py",
                    self.args.helper_dir / "t510_stage35_time_long_prepare.py",
                    self.args.helper_dir / "t510_stage35_simple_math.py",
                    self.args.plotly, self.args.stage35_config,
                    self.args.capture_queue / "evidence/phase_00_telemetry.json",
                    self.args.capture_queue / "queue_state.json"]
        errors.extend(f"missing input: {path}" for path in required if not path.is_file())
        if shutil.disk_usage(self.root.parent).free < 100 * 1024**3:
            errors.append("less than 100 GiB free")
        try:
            request_json("http://127.0.0.1:8035/healthz")
        except Exception as exc:
            errors.append(f"Stage 35 page is not alive: {exc}")
        if errors:
            raise RuntimeError(str(errors))
        write_json(self.evidence / "preflight.json", {
            "status": "PASS", "capture_manifest": file_identity(manifest_path),
            "amplitude": amplitude, "independent": independent,
            "inputs": [file_identity(path) for path in required],
        })

    def prepare_arrays(self) -> None:
        sys.path.insert(0, str(self.args.helper_dir))
        import t510_stage35_explorer_prepare as prepare
        import t510_stage35_simple_prepare as simple
        prepare.DATA_ROOT = Path("/var/lib/t510").resolve()
        simple.DATA_ROOT = prepare.DATA_ROOT
        raw_root = self.data / "raw"
        raw_root.mkdir()
        time_source = self.args.capture_queue / "raw/time-formal-50ms.pcap"
        spec_source = self.args.capture_queue / "raw/spec-fullband-4096frames.pcap"
        time_record = prepare.prepare_time("TIME-formal", time_source, raw_root)
        time_record = simple.prepare_time_fft("TIME-formal", time_record, raw_root)
        spec_record = prepare.prepare_spec("F-engine-4096", spec_source, raw_root / "spec_index")
        trim_spec_record(spec_record)
        raw_manifest = {
            "format": "T510_STAGE36_SIMPLE_RAW_INDEX_V1",
            "time": {"TIME-formal": time_record},
            "spec": {"F-engine-4096": spec_record},
            "capture_queue_manifest": file_identity(self.args.capture_queue / "queue_manifest.json"),
        }
        write_json(raw_root / "simple_raw_index_manifest.json", raw_manifest)
        completed = subprocess.run([
            sys.executable, str(self.args.helper_dir / "t510_stage35_time_long_prepare.py"),
            "--dataset", str(self.args.measurement_root / "stage36-science-20260906-1852-time-formal-900s"),
            "--output", str(self.data / "time_long"), "--label", "TIME-900s",
        ], text=True, capture_output=True, timeout=1800, check=False)
        write_json(self.evidence / "time_long_process.json", {
            "returncode": completed.returncode, "stdout": completed.stdout, "stderr": completed.stderr})
        if completed.returncode:
            raise RuntimeError(f"TIME long preparation failed: {completed.stderr}")
        self.state["raw_manifest"] = str(raw_root / "simple_raw_index_manifest.json")
        self.state["time_long_index"] = str(self.data / "time_long/time_long_index.json")
        self.save()

    def comparison(self) -> None:
        stage35_config = json.loads(self.args.stage35_config.read_text(encoding="utf-8"))
        stage35_raw_path = Path(stage35_config["simple_raw_index_manifest"])
        stage35_raw = json.loads(stage35_raw_path.read_text(encoding="utf-8"))
        time_label = "A-pre" if "A-pre" in stage35_raw["time"] else sorted(stage35_raw["time"])[0]
        spec_label = sorted(stage35_raw["spec"])[0]
        time_array = np.load(stage35_raw["time"][time_label]["iq16_npy"], mmap_mode="r")
        spec_array = np.load(stage35_raw["spec"][spec_label]["iq16_npy"], mmap_mode="r")
        s35_time = component_std(time_array, chunk=250_000)
        s35_spec = np.median(component_std(spec_array, chunk=128), axis=1)
        amplitude = json.loads((self.args.capture_queue / "evidence/formal_amplitude_verification.json").read_text())
        s36_time = np.asarray(amplitude["time"]["std_iq"], dtype=np.float64)
        s36_spec = np.asarray(amplitude["spec"]["median_std_iq_by_adc"], dtype=np.float64)

        def section(old: np.ndarray, new: np.ndarray, gain: float) -> dict[str, Any]:
            unified = new / gain
            old_range = [float(np.min(old)), float(np.max(old))]
            new_range = [float(np.min(new)), float(np.max(new))]
            unified_range = [float(np.min(unified)), float(np.max(unified))]
            relative = 100.0 * (float(np.median(unified)) / float(np.median(old)) - 1.0)
            return {
                "stage35_raw_by_adc_iq": old.tolist(),
                "stage35_raw_range": old_range,
                "stage36_raw_by_adc_iq": new.tolist(),
                "stage36_raw_range": new_range,
                "stage36_unified_by_adc_iq": unified.tolist(),
                "stage36_unified_range": unified_range,
                "voltage_gain_removed": gain,
                "median_unified_change_percent": relative,
            }

        result = {
            "format": "T510_STAGE36_STAGE35_SCALE_COMPARISON_V1",
            "status": "PASS",
            "time": section(s35_time, s36_time, TIME_GAIN),
            "fengine": section(s35_spec, s36_spec, SPEC_GAIN),
            "scaling": {
                "time_voltage": TIME_GAIN, "fengine_voltage": SPEC_GAIN,
                "time_power": TIME_GAIN**2, "fengine_power_and_visibility": SPEC_GAIN**2,
                "fengine_power_or_visibility_allan_variance": SPEC_GAIN**4,
            },
            "interpretation": "The raw count increase is expected from digital scaling and is not itself a scientific performance improvement.",
            "stage35_sources": {"config": file_identity(self.args.stage35_config),
                                "raw_manifest": file_identity(stage35_raw_path),
                                "time_capture": time_label, "spec_capture": spec_label},
            "stage36_source": file_identity(self.args.capture_queue / "evidence/formal_amplitude_verification.json"),
        }
        for name in ("time", "fengine"):
            if abs(result[name]["median_unified_change_percent"]) > 20.0:
                result["status"] = "FAIL"
        if result["status"] != "PASS":
            raise RuntimeError(f"unified Stage 35/36 comparison is outside 20%: {result}")
        write_json(self.data / "stage35_comparison.json", result)

    def prepare_temperature(self) -> None:
        telemetry_path = self.args.capture_queue / "evidence/phase_00_telemetry.json"
        queue_state_path = self.args.capture_queue / "queue_state.json"
        telemetry = json.loads(telemetry_path.read_text(encoding="utf-8"))
        queue_state = json.loads(queue_state_path.read_text(encoding="utf-8"))
        phase = next(item for item in queue_state["phases"] if item.get("label") == "time-formal")
        start_ms = int(phase["capture_status"]["started_unix_ms"])
        end_ms = start_ms + int(phase["duration_seconds"]) * 1000
        by_timestamp: dict[int, dict[str, Any]] = {}
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
                        "mean": float(pl["mean"]), "min": float(pl["min"]),
                        "max": float(pl["max"]), "sequence": record.get("sequence"),
                    }
        ordered = sorted(by_timestamp.items())
        if len(ordered) != 900:
            raise RuntimeError(f"formal TIME window must contain 900 PL temperature points, got {len(ordered)}")
        result = {
            "format": "T510_STAGE36_TIME_TEMPERATURE_V1",
            "sensor": "pl_temp", "unit": "degC", "points": len(ordered),
            "sampling": "original board AMS telemetry at approximately 1 Hz; no interpolation",
            "capture_start_unix_ms": start_ms, "capture_duration_seconds": 900,
            "time_s": [(timestamp - start_ms) / 1000.0 for timestamp, _ in ordered],
            "mean_c": [value["mean"] for _, value in ordered],
            "min_c": [value["min"] for _, value in ordered],
            "max_c": [value["max"] for _, value in ordered],
            "source": file_identity(telemetry_path),
            "queue_state": file_identity(queue_state_path),
        }
        write_json(self.data / "time_temperature.json", result)
        self.state["time_temperature"] = str(self.data / "time_temperature.json")
        self.save()

    def build_candidate(self) -> None:
        shutil.copy2(self.args.server, self.app / "t510_stage36_explorer.py")
        helpers = self.app / "helpers"; helpers.mkdir()
        shutil.copy2(self.args.helper_dir / "t510_stage35_simple_math.py", helpers)
        static = self.app / "static"; static.mkdir()
        for name in ("index.html", "stage36-app.js", "stage36-app.css"):
            shutil.copy2(self.args.static_source / name, static / name)
        shutil.copytree(self.args.static_source / "katex", static / "katex")
        shutil.copy2(self.args.plotly, static / "plotly-strict.min.js")
        scans = {
            "A": self.args.measurement_root / "stage36-science-20260906-1852-self-a-spec-scan-900s",
            "B": self.args.measurement_root / "stage36-science-20260906-1852-self-b-spec-scan-900s",
            "C": self.args.measurement_root / "stage36-science-20260906-1852-self-c-spec-scan-900s",
        }
        config = {
            "format": "T510_STAGE36_SIMPLE_EXPLORER_CONFIG_V1",
            "center_mhz": 200.0,
            "simple_raw_index_manifest": self.state["raw_manifest"],
            "time_long_index": self.state["time_long_index"],
            "self_scans": {key: str(value) for key, value in scans.items()},
            "cross_scan": str(self.args.measurement_root / "stage36-science-20260906-1852-pairs-xcorr-scan-900s"),
            "stage35_comparison": str(self.data / "stage35_comparison.json"),
            "time_temperature": self.state["time_temperature"],
            "scientific_boundary": {
                "TIME_ONLY": "post-DDC 320 MS/s IQ16 ADU; no physical calibration",
                "F-engine": "channelized IQ16 count; no K/Jy/SEFD calibration",
                "cross": "independent 50-ohm instrument false-correlation floor, not sky visibility",
                "comparison": "scale-normalized comparison is descriptive, not strict causal proof",
            },
        }
        write_json(self.data / "app_config.json", config)
        identities = []
        for path in sorted(item for item in self.app.rglob("*") if item.is_file()):
            identities.append(file_identity(path))
        write_json(self.evidence / "candidate_identity.json", {"files": identities})

    def start_candidate(self, port: int) -> subprocess.Popen[str]:
        process = subprocess.Popen([
            sys.executable, str(self.app / "t510_stage36_explorer.py"),
            "--config", str(self.data / "app_config.json"),
            "--helper-dir", str(self.app / "helpers"),
            "--static-root", str(self.app / "static"), "--bind", f"127.0.0.1:{port}",
        ], text=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f"candidate exited: {process.stderr.read()}")
            try:
                if request_json(f"http://127.0.0.1:{port}/healthz").get("application") == "stage36-simple":
                    return process
            except Exception:
                time.sleep(.25)
        process.terminate()
        raise RuntimeError("candidate did not become healthy")

    def api_verify(self) -> None:
        port = self.args.candidate_port
        process = self.start_candidate(port)
        base = f"http://127.0.0.1:{port}"
        try:
            meta = request_json(base + "/api/v2/meta")
            if meta.get("format") != "T510_STAGE36_SIMPLE_EXPLORER_META_V1":
                raise RuntimeError("candidate meta format mismatch")
            if meta.get("stage35_comparison", {}).get("status") != "PASS":
                raise RuntimeError("Stage 35 comparison is not PASS")
            if meta.get("time_temperature", {}).get("points") != 900:
                raise RuntimeError("TIME temperature coverage mismatch")
            checks = {
                "time_raw": "/api/v2/timeseries?domain=time_single&adc=0&capture=TIME-formal&bucket=raw",
                "time_10ms": "/api/v2/timeseries?domain=time_long_single&adc=0&cadence_ms=10",
                "time_100ms": "/api/v2/timeseries?domain=time_long_single&adc=0&cadence_ms=100",
                "time_1s": "/api/v2/timeseries?domain=time_long_single&adc=0&cadence_ms=1000",
                "spec_raw": "/api/v2/timeseries?domain=fengine_raw_single&adc=0&bins=3134,3182,3328&bucket=1",
                "self_100ms": "/api/v2/timeseries?domain=fengine_long_single&adc=0&bins=3134,3182,3328&scan=A&cadence_ms=100",
                "pair_100ms": "/api/v2/timeseries?domain=fengine_long_pair&pair=0-1&bins=3134,3182,3328&cadence_ms=100",
                "pair_1s": "/api/v2/timeseries?domain=fengine_long_pair&pair=0-1&bins=3328&cadence_ms=1000",
                "allan_single": "/api/v2/allan?subject=single&adc=0&bins=3134,3182,3328&scan=A&form=variance&scale=relative",
                "allan_pair": "/api/v2/allan?subject=pair&pair=0-1&bins=3328&cadence_ms=100&form=variance&scale=relative",
            }
            results = {name: request_json(base + path) for name, path in checks.items()}
            if len(results["time_raw"]["i_adu"]) != 4096:
                raise RuntimeError("TIME raw point count mismatch")
            if [len(results[name]["time_s"]) for name in ("time_10ms", "time_100ms", "time_1s")] != [90000, 9000, 900]:
                raise RuntimeError("TIME long cadence coverage mismatch")
            if len(results["time_100ms"].get("temperature", {}).get("time_s", [])) != 900:
                raise RuntimeError("TIME API temperature coverage mismatch")
            if any(len(row["i"]) != 4096 for row in results["spec_raw"]["series"]):
                raise RuntimeError("SPEC raw coverage mismatch")
            if len(results["self_100ms"]["time_s"]) != 9000:
                raise RuntimeError("self-power coverage mismatch")
            if len(results["pair_100ms"]["time_s"]) != 9000 or len(results["pair_1s"]["time_s"]) != 900:
                raise RuntimeError("cross-power coverage mismatch")
            if not results["allan_single"].get("series") or not results["allan_pair"].get("series"):
                raise RuntimeError("Allan products are empty")
            write_json(self.evidence / "numeric_api_verification.json", {
                "status": "PASS", "meta": meta,
                "checks": {name: {"domain": value.get("domain", value.get("format")),
                                   "formula": value.get("formula")} for name, value in results.items()},
            })
        finally:
            process.terminate()
            try: process.wait(timeout=10)
            except subprocess.TimeoutExpired: process.kill()

    def browser_verify(self) -> None:
        port = self.args.candidate_port
        process = self.start_candidate(port)
        base = f"http://127.0.0.1:{port}"
        profile = Path.home() / "snap/chromium/common/t510-stage36-browser" / self.root.name
        profile.parent.mkdir(parents=True, exist_ok=True)
        url = (base + "/?mode=single&adcs=0,1&pairs=0-1,2-3&"
               "bins=3134,3182,3328&time_capture=TIME-formal&fengine_short=16&"
               "self_scan=A&self_ms=100&pair_visibility_ms=100&allan_form=variance&allan_scale=relative")
        command = [str(self.args.chromium), "--headless=new", "--no-sandbox",
                   "--disable-dev-shm-usage", "--enable-unsafe-swiftshader",
                   "--use-gl=angle", "--use-angle=swiftshader", "--window-size=1600,1200",
                   f"--user-data-dir={profile}", "--virtual-time-budget=120000", "--dump-dom", url]
        try:
            completed = subprocess.run(command, text=True, capture_output=True, timeout=300, check=False)
            (self.evidence / "browser_dom.html").write_text(completed.stdout, encoding="utf-8")
            (self.evidence / "browser_stderr.txt").write_text(completed.stderr, encoding="utf-8")
            errors = []
            if completed.returncode:
                errors.append(f"Chromium returncode={completed.returncode}")
            if "权威数据就绪" not in completed.stdout:
                errors.append("browser did not reach authoritative-data-ready state")
            if "Stage 36 原始读数" not in completed.stdout:
                errors.append("Stage 35/36 comparison is not visible")
            if "PL温度来自同一正式窗口" not in completed.stdout:
                errors.append("TIME power temperature explanation is not visible")
            if 'class="katex"' not in completed.stdout:
                errors.append("KaTeX did not render formulas")
            if "Failed To Create Data Directory" in completed.stderr:
                errors.append("Chromium profile directory was not usable")
            if "加载失败：" in completed.stdout or "有章节加载失败" in completed.stdout:
                errors.append("browser rendered a data failure")
            sources = "\n".join((self.app / "static" / name).read_text(encoding="utf-8")
                                  for name in ("index.html", "stage36-app.js", "stage36-app.css"))
            sources = sources.replace("http://www.w3.org/2000/svg", "")
            if "https://" in sources or "http://" in sources:
                errors.append("candidate static bundle contains an external URL")
            if errors:
                raise RuntimeError(str(errors))
            write_json(self.evidence / "browser_verification.json", {
                "status": "PASS", "url": url, "selected_adcs": [0, 1],
                "selected_pairs": [[0, 1], [2, 3]], "selected_bins": [3134, 3182, 3328],
                "dom": file_identity(self.evidence / "browser_dom.html"),
                "stderr": file_identity(self.evidence / "browser_stderr.txt"),
                "external_static_urls": 0,
            })
        finally:
            process.terminate()
            try: process.wait(timeout=10)
            except subprocess.TimeoutExpired: process.kill()
            shutil.rmtree(profile, ignore_errors=True)

    def publish(self) -> None:
        install = Path("/opt/t510-stage36-explorer")
        staged = install / ".current.next"
        service = self.root / "t510-stage36-explorer.service"
        service.write_text(f"""[Unit]\nDescription=T510 Stage 36 read-only human explorer\nAfter=network-online.target\n\n[Service]\nType=simple\nUser={os.environ.get('USER', 'astrolab')}\nGroup={os.environ.get('USER', 'astrolab')}\nWorkingDirectory={install}/current\nExecStart={sys.executable} {install}/current/t510_stage36_explorer.py --config {self.data}/app_config.json --helper-dir {install}/current/helpers --static-root {install}/current/static --bind 0.0.0.0:8036\nRestart=on-failure\nRestartSec=2\nNoNewPrivileges=true\nPrivateTmp=true\nProtectHome=true\nProtectSystem=full\nReadOnlyPaths=/var/lib/t510\n\n[Install]\nWantedBy=multi-user.target\n""", encoding="utf-8")
        commands = [
            ["sudo", "-n", "mkdir", "-p", str(install)],
            ["sudo", "-n", "rm", "-rf", str(staged)],
            ["sudo", "-n", "cp", "-a", str(self.app), str(staged)],
            ["sudo", "-n", "rm", "-rf", str(install / "current")],
            ["sudo", "-n", "mv", str(staged), str(install / "current")],
            ["sudo", "-n", "cp", str(service), "/etc/systemd/system/t510-stage36-explorer.service"],
            ["sudo", "-n", "systemctl", "daemon-reload"],
            ["sudo", "-n", "systemctl", "enable", "--now", "t510-stage36-explorer.service"],
        ]
        rows = []
        for command in commands:
            completed = subprocess.run(command, text=True, capture_output=True, timeout=120, check=False)
            rows.append({"argv": command, "returncode": completed.returncode,
                         "stdout": completed.stdout, "stderr": completed.stderr})
            if completed.returncode:
                write_json(self.evidence / "publish_process.json", rows)
                raise RuntimeError(f"publish failed: {command}: {completed.stderr}")
        write_json(self.evidence / "publish_process.json", rows)

    def live_verify(self) -> None:
        deadline = time.monotonic() + 30
        health = None
        while time.monotonic() < deadline:
            try:
                health = request_json("http://127.0.0.1:8036/healthz")
                if health.get("application") == "stage36-simple": break
            except Exception: time.sleep(.5)
        else: raise RuntimeError("live 8036 service did not become healthy")
        meta = request_json("http://127.0.0.1:8036/api/v2/meta")
        old_health = request_json("http://127.0.0.1:8035/healthz")
        service = subprocess.run(["systemctl", "is-active", "t510-stage36-explorer.service"],
                                 text=True, capture_output=True, check=False)
        if service.stdout.strip() != "active" or meta.get("title", "").split("：")[0] != "Stage 36":
            raise RuntimeError("live service identity mismatch")
        if old_health.get("application") != "stage35-simple":
            raise RuntimeError("historical 8035 service changed")
        write_json(self.evidence / "live_verification.json", {
            "status": "PASS", "url": "http://192.168.100.162:8036/",
            "health": health, "meta_format": meta.get("format"),
            "stage35_8035_health": old_health, "service": service.stdout.strip(),
        })

    def final_manifest(self) -> None:
        files = []
        for path in sorted(item for item in self.root.rglob("*") if item.is_file()):
            if path.name in ("artifact_manifest.json", "artifact_manifest.sha256",
                              "queue_state.json", "queue_events.jsonl"):
                continue
            files.append({"path": path.relative_to(self.root).as_posix(),
                          "bytes": path.stat().st_size, "sha256": sha256_file(path)})
        manifest = {"format": "T510_STAGE36_EXPLORER_ARTIFACT_MANIFEST_V1",
                    "complete": True, "url": "http://192.168.100.162:8036/", "files": files}
        path = self.root / "artifact_manifest.json"; write_json(path, manifest)
        (self.root / "artifact_manifest.sha256").write_text(
            f"{sha256_file(path)}  artifact_manifest.json\n", encoding="ascii")

    def run(self) -> int:
        self.initialize()
        self.state.update(status="running", started_unix_ms=unix_ms()); self.save()
        try:
            self.phase("preflight", self.preflight)
            self.phase("raw_and_long_arrays", self.prepare_arrays)
            self.phase("stage35_comparison", self.comparison)
            self.phase("time_temperature", self.prepare_temperature)
            self.phase("candidate_build", self.build_candidate)
            self.phase("numeric_api_verify", self.api_verify)
            self.phase("browser_verify", self.browser_verify)
            self.phase("publish_8036", self.publish)
            self.phase("live_verify", self.live_verify)
            self.phase("final_manifest", self.final_manifest)
            self.state.update(status="completed", current_phase=None, finished_unix_ms=unix_ms())
            self.save(); self.event("queue_complete")
            return 0
        except Exception as exc:
            current = self.state.get("current_phase")
            for item in self.state["phases"]:
                if item["name"] == current and item["status"] == "running":
                    item.update(status="failed", error=f"{type(exc).__name__}: {exc}")
            self.state.update(status="failed", finished_unix_ms=unix_ms(), error={
                "message": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc()})
            self.save(); self.event("queue_failed", error=self.state["error"])
            return 1

    def resume_after_spec_coverage_failure(self) -> int:
        expected_error = "RuntimeError: SPEC raw coverage mismatch"
        if not self.state_path.is_file():
            raise RuntimeError(f"resume state does not exist: {self.state_path}")
        loaded = json.loads(self.state_path.read_text(encoding="utf-8"))
        if (loaded.get("format") != FORMAT or loaded.get("status") != "failed"
                or loaded.get("error", {}).get("message") != expected_error
                or loaded.get("source_commit") != "72e7074"):
            raise RuntimeError("output is not the registered SPEC coverage verifier failure")
        expected_status = {
            "preflight": "completed", "raw_and_long_arrays": "completed",
            "stage35_comparison": "completed", "candidate_build": "completed",
            "numeric_api_verify": "failed", "browser_verify": "pending",
            "publish_8036": "pending", "live_verify": "pending", "final_manifest": "pending",
        }
        if {row["name"]: row["status"] for row in loaded.get("phases", [])} != expected_status:
            raise RuntimeError("registered resume phase state mismatch")
        self.state = loaded
        manifest_path = Path(self.state["raw_manifest"])
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if set(manifest.get("spec", {})) != {"F-engine-4096"}:
            raise RuntimeError("registered raw manifest SPEC identity mismatch")
        record = manifest["spec"]["F-engine-4096"]
        before = {"spectra": record.get("spectra"),
                  "iq16_npy": file_identity(Path(record["iq16_npy"]))}
        if int(record.get("spectra", 0)) != 4098:
            raise RuntimeError("registered resume requires the observed 4098-frame derived array")
        trim_spec_record(record)
        partial_manifest = manifest_path.with_name(manifest_path.name + ".partial")
        write_json(partial_manifest, manifest)
        partial_manifest.replace(manifest_path)
        history = self.state.setdefault("resume_history", [])
        history.append({
            "resumed_unix_ms": unix_ms(), "resume_source_commit": self.args.source_commit,
            "original_error": self.state.get("error"), "repair": "crop verified common SPEC interval to 4096 frames",
            "before": before, "after": {"spectra": record["spectra"],
                                         "iq16_npy": file_identity(Path(record["iq16_npy"]))},
        })
        self.state.update(status="running", current_phase=None, error=None, finished_unix_ms=None)
        self.save(); self.event("registered_spec_coverage_failure_recovered")
        try:
            self.phase("numeric_api_verify", self.api_verify)
            self.phase("browser_verify", self.browser_verify)
            self.phase("publish_8036", self.publish)
            self.phase("live_verify", self.live_verify)
            self.phase("final_manifest", self.final_manifest)
            self.state.update(status="completed", current_phase=None, finished_unix_ms=unix_ms())
            self.save(); self.event("queue_complete")
            return 0
        except Exception as exc:
            current = self.state.get("current_phase")
            for item in self.state["phases"]:
                if item["name"] == current and item["status"] == "running":
                    item.update(status="failed", error=f"{type(exc).__name__}: {exc}")
            self.state.update(status="failed", finished_unix_ms=unix_ms(), error={
                "message": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc()})
            self.save(); self.event("queue_failed", error=self.state["error"])
            return 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--capture-queue", type=Path, required=True)
    parser.add_argument("--measurement-root", type=Path, default=Path("/var/lib/t510/measurements"))
    parser.add_argument("--server", type=Path, required=True)
    parser.add_argument("--static-source", type=Path, required=True)
    parser.add_argument("--helper-dir", type=Path, required=True)
    parser.add_argument("--plotly", type=Path, required=True)
    parser.add_argument("--stage35-config", type=Path,
                        default=Path("/var/lib/t510/stage35/explorer/current/app_config.json"))
    parser.add_argument("--chromium", type=Path, default=Path("/snap/bin/chromium"))
    parser.add_argument("--candidate-port", type=int, default=18036)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--lock", type=Path, default=Path("/run/lock/t510-stage36-explorer.lock"))
    parser.add_argument("--resume-after-spec-coverage-failure", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.lock.parent.mkdir(parents=True, exist_ok=True)
    with args.lock.open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        queue = Queue(args)
        if args.resume_after_spec_coverage_failure:
            return queue.resume_after_spec_coverage_failure()
        return queue.run()


if __name__ == "__main__":
    raise SystemExit(main())
