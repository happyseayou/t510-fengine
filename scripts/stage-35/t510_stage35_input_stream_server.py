#!/usr/bin/env python3
"""Read-only HTTP streamer for one frozen Stage 35 cluster input set."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path("/var/lib/t510/stage35").resolve()
DATASETS = (
    "stage35-40-360mhz-v2-20260902-1225-self-a-spec-scan-900s",
    "stage35-40-360mhz-v2-20260902-1225-self-b-spec-scan-900s",
    "stage35-40-360mhz-v2-20260902-1225-self-c-spec-scan-900s",
    "stage35-40-360mhz-v2-20260902-1225-self-a-time-pre-30s",
    "stage35-40-360mhz-v2-20260902-1225-self-a-time-post-30s",
    "stage35-40-360mhz-v2-20260902-1225-self-b-time-pre-30s",
    "stage35-40-360mhz-v2-20260902-1225-self-b-time-post-30s",
    "stage35-40-360mhz-v2-20260902-1225-self-c-time-pre-30s",
    "stage35-40-360mhz-v2-20260902-1225-self-c-time-post-30s",
    "stage35-40-360mhz-v2-20260902-1225-self-queue",
)
TRANSFER_LOCK = threading.Lock()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def do_HEAD(self) -> None:  # noqa: N802
        if self.path not in ("/healthz", "/identity", "/input-stream"):
            self.send_error(HTTPStatus.NOT_FOUND); return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/x-tar" if self.path == "/input-stream" else "application/json")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/healthz":
            self._json({"ok": True}); return
        if self.path == "/identity":
            queue_manifest = ROOT / DATASETS[-1] / "queue_manifest.json"
            self._json({"format": "T510_STAGE35_CLUSTER_INPUT_STREAM_V1",
                        "root": str(ROOT), "datasets": list(DATASETS),
                        "queue_manifest_sha256": sha256(queue_manifest)})
            return
        if self.path != "/input-stream":
            self.send_error(HTTPStatus.NOT_FOUND); return
        if not TRANSFER_LOCK.acquire(blocking=False):
            self.send_error(HTTPStatus.CONFLICT, "one input stream is already active"); return
        process = None
        try:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/x-tar")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            process = subprocess.Popen(
                ["/usr/bin/tar", "--format=posix", "-cf", "-", "-C", str(ROOT), *DATASETS],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            assert process.stdout is not None
            for chunk in iter(lambda: process.stdout.read(8 * 1024 * 1024), b""):
                self.wfile.write(chunk)
            stderr = process.stderr.read().decode(errors="replace") if process.stderr else ""
            if process.wait() != 0:
                raise RuntimeError(f"tar stream failed: {stderr}")
        except (BrokenPipeError, ConnectionResetError):
            if process is not None:
                process.terminate()
        finally:
            if process is not None and process.poll() is None:
                process.terminate(); process.wait()
            TRANSFER_LOCK.release()

    def _json(self, value: object) -> None:
        payload = (json.dumps(value, sort_keys=True) + "\n").encode()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers(); self.wfile.write(payload)

    def do_POST(self) -> None:  # noqa: N802
        self.send_error(HTTPStatus.METHOD_NOT_ALLOWED)

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"stage35-input-stream: {fmt % args}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bind", default="0.0.0.0:8040")
    args = parser.parse_args()
    for name in DATASETS:
        path = (ROOT / name).resolve(strict=True)
        if path.parent != ROOT or not path.is_dir():
            raise RuntimeError(f"frozen dataset is unavailable: {path}")
    host, port = args.bind.rsplit(":", 1)
    ThreadingHTTPServer((host, int(port)), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
