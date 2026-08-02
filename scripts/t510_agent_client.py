#!/usr/bin/env python3
"""Small Center Hub reference client for the stateless T510 API v2."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import urllib.error
import urllib.request
from typing import Any


class AgentError(RuntimeError):
    pass


def load_json(path: str) -> dict[str, Any]:
    value = json.loads(Path(path).read_text())
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def request(
    base_url: str,
    method: str,
    path: str,
    *,
    body: dict[str, Any] | None = None,
    timeout: float = 190.0,
) -> Any:
    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        base_url.rstrip("/") + path,
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            problem = json.loads(raw)
        except Exception:
            problem = {"message": raw.decode("utf-8", errors="replace")}
        raise AgentError(f"HTTP {exc.code}: {json.dumps(problem, ensure_ascii=False)}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://192.168.100.117:8010")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("live", "ready", "info", "capabilities", "bitstreams", "status", "stop"):
        sub.add_parser(name)
    configure = sub.add_parser("configure")
    configure.add_argument("path")
    configure.add_argument(
        "--board-id",
        type=int,
        help="override the 16-bit board identity",
    )
    configure.add_argument("--sample-rate-msps", type=int, choices=(160, 320))
    configure.add_argument(
        "--center-mhz",
        type=float,
        help="override profile center frequency in MHz",
    )
    configure.add_argument(
        "--mode",
        choices=("time_only", "spec_only", "time_spec"),
        help="override profile mode and derive endpoint enables from stream type",
    )
    start = sub.add_parser("start")
    start.add_argument("--board-id", type=int, required=True)
    reset = sub.add_parser("reset")
    reset.add_argument("--board-id", type=int, required=True)
    dac = sub.add_parser("dac")
    dac.add_argument("path")
    args = parser.parse_args()

    simple_get = {
        "live": "/health/live",
        "ready": "/health/ready",
        "info": "/api/v2/info",
        "capabilities": "/api/v2/capabilities",
        "bitstreams": "/api/v2/bitstreams",
        "status": "/api/v2/status",
    }
    if args.command in simple_get:
        result = request(args.base_url, "GET", simple_get[args.command], timeout=15.0)
    elif args.command == "configure":
        body = load_json(args.path)
        if args.board_id is not None:
            if not 0 <= args.board_id <= 0xFFFF:
                raise ValueError("--board-id must be within 0..65535")
            body["board_id"] = args.board_id
        profile = body.get("profile")
        if not isinstance(profile, dict):
            raise ValueError("configure body must contain a profile object")
        if args.sample_rate_msps is not None:
            profile["sample_rate_msps"] = args.sample_rate_msps
        if args.center_mhz is not None:
            profile["center_mhz"] = args.center_mhz
        if args.mode is not None:
            profile["mode"] = args.mode
            enabled_streams = {
                "time_only": {"TIME"},
                "spec_only": {"SPEC"},
                "time_spec": {"TIME", "SPEC"},
            }[args.mode]
            endpoints = body.get("endpoints")
            if not isinstance(endpoints, list):
                raise ValueError("configure body must contain an endpoints array")
            for endpoint in endpoints:
                if not isinstance(endpoint, dict):
                    raise ValueError("each endpoint must be an object")
                endpoint["enabled"] = str(endpoint.get("stream", "")).upper() in enabled_streams
        result = request(
            args.base_url,
            "POST",
            "/api/v2/configure",
            body=body,
        )
    elif args.command in ("start", "reset"):
        result = request(
            args.base_url,
            "POST",
            f"/api/v2/{args.command}",
            body={"expected_board_id": args.board_id},
            timeout=15.0,
        )
    elif args.command == "stop":
        result = request(args.base_url, "POST", "/api/v2/stop", timeout=15.0)
    elif args.command == "dac":
        result = request(
            args.base_url,
            "PUT",
            "/api/v2/dac",
            body=load_json(args.path),
            timeout=15.0,
        )
    else:
        raise AssertionError(args.command)
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
