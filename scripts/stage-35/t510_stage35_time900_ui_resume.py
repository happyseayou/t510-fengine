#!/usr/bin/env python3
"""Resume only the verified browser/cutover tail of the TIME900 UI queue."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace

import t510_stage35_s2_queue as base
from t510_time_capture900_ui_queue import Queue


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue-id", required=True)
    parser.add_argument("--browser-verification", type=Path, required=True)
    parser.add_argument("--measurement-root", type=Path, default=Path("/var/lib/t510/stage35"))
    parser.add_argument("--explorer-root", type=Path,
                        default=Path("/var/lib/t510/stage35/explorer"))
    parser.add_argument("--app-root", type=Path,
                        default=Path("/opt/t510-stage35-explorer/candidate"))
    args = parser.parse_args()
    queue_root = args.measurement_root / f"{args.queue_id}-queue"
    state_path = queue_root / "queue_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    if state.get("status") != "failed" or len(state.get("phases", [])) != 2:
        raise RuntimeError("resume requires the expected failed two-phase queue")
    if any(phase.get("status") != "completed" for phase in state["phases"]):
        raise RuntimeError("resume refuses incomplete acquisition phases")
    message = str(state.get("error", {}).get("message", ""))
    if "sidebar_browser_verify failed" not in message:
        raise RuntimeError("resume refuses a non-browser queue failure")
    browser = json.loads(args.browser_verification.read_text(encoding="utf-8"))
    if browser.get("status") != "PASS":
        raise RuntimeError("browser verification is not PASS")
    release = args.explorer_root / "releases" / args.queue_id
    for required in (
        release / "app_config.json",
        release / "time_long" / "time_long_index.json",
        args.app_root / "t510_stage35_explorer.py",
        args.app_root / "static" / "index.html",
    ):
        if not required.is_file():
            raise RuntimeError(f"required resume input is missing: {required}")

    queue_args = SimpleNamespace(
        queue_id=args.queue_id,
        measurement_root=args.measurement_root,
        agent_base=state["agent_base"],
        receiver_base=state["receiver_base"],
        center_mhz=float(state["center_mhz"]),
        minimum_free_bytes=int(state["minimum_free_bytes"]),
        explorer_root=args.explorer_root,
        app_root=args.app_root,
    )
    queue = Queue(queue_args, {})
    queue.state = state
    queue.phases = state["phases"]
    queue.cutover(release)
    state.update({
        "status": "completed",
        "current_phase_index": None,
        "finished_unix_ms": base.unix_ms(),
        "error": None,
        "explorer_release": str(release),
        "browser_verification_path": str(args.browser_verification),
        "url": "http://192.168.100.162:8035/",
        "resumed_after_browser_gate_fix": True,
    })
    queue.state = state
    queue.save()
    queue.event("queue_complete_after_browser_gate_fix",
                browser_verification=str(args.browser_verification))
    queue.final_manifest()
    print(json.dumps({
        "status": "PASS",
        "url": state["url"],
        "release": str(release),
        "browser_verification": str(args.browser_verification),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
