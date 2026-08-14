#!/usr/bin/env python3
"""Run the Stage 34c-2R 10/5 MHz PL SYSREF phase-eye campaign."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import time
from typing import Any

from t510_fullband_spur_scan import _http_json
from t510_pl_sysref_phase_eye import select_eye


BOARD_ID = 1
CORE_VERSION = "0x00010035"
BITSTREAM_ID = "fengine-0x00010035"
BITSTREAM_SHA256 = "2de23f7a731622a984e2602a267ac780a1e5cedafa644f32a27d3e7d5628b5e0"
PRODUCTION_BITSTREAM_ID = "fengine-0x00010034"
CENTER_MHZ = 1020.0
SETUP_NS = -0.680
HOLD_NS = 2.049


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def configure_body(template: dict[str, Any], bitstream_id: str) -> dict[str, Any]:
    body = json.loads(json.dumps(template))
    body["bitstream_id"] = bitstream_id
    body["board_id"] = BOARD_ID
    body["profile"] = {
        "sample_rate_msps": 320,
        "mode": "spec_only",
        "center_mhz": CENTER_MHZ,
    }
    for endpoint in body["endpoints"]:
        endpoint["enabled"] = str(endpoint["stream"]).upper() == "SPEC"
    return body


def prepare(
    agent_base: str,
    profile_id: str,
    *,
    attempt_kind: str,
) -> dict[str, Any]:
    return _http_json(
        agent_base.rstrip("/") + "/api/v2/clock/diagnostic/prepare",
        method="POST",
        body={
            "expected_board_id": BOARD_ID,
            "profile_id": profile_id,
            "sample_rate_msps": 320,
            "center_mhz": CENTER_MHZ,
            "receiver_stream_accepting": False,
            "mts_target_mode": "discovery",
            "verify_sysref_negative_control": False,
            "attempt_kind": attempt_kind,
        },
        timeout=300.0,
    )


def restore_clock(agent_base: str) -> dict[str, Any]:
    return _http_json(
        agent_base.rstrip("/") + "/api/v2/clock/diagnostic/restore",
        method="POST",
        body={"expected_board_id": BOARD_ID, "receiver_stream_accepting": False},
        timeout=300.0,
    )


def extract_attempt(result: dict[str, Any], kind: str, expected_file_sha: str) -> dict[str, Any]:
    diagnostic = result.get("clock_diagnostic", {})
    live = diagnostic.get("live", {})
    mts = result.get("mts", {})
    adc = list(mts.get("adc", {}).get("active_measured_latency") or [])
    dac = list(mts.get("dac", {}).get("active_measured_latency") or [])
    capture = result.get("sysref_running_capture") or {}
    if str(live.get("tics_file_sha256", "")).lower() != expected_file_sha.lower():
        raise RuntimeError(
            f"TICS file SHA readback mismatch: {live.get('tics_file_sha256')} != {expected_file_sha}"
        )
    return {
        "kind": kind,
        "mts_passed": bool(mts.get("available") and len(adc) == 4 and len(dac) == 4),
        "pll1_locked": int(live.get("pll1_lock", 0)) == 1,
        "pll2_locked": int(live.get("pll2_lock", 0)) == 1,
        "adc_latency": [int(value) for value in adc],
        "dac_latency": [int(value) for value in dac],
        "capture_interval_seconds": float(capture.get("observation_seconds", 0.0)),
        "sysref_capture_delta": {
            key: int(value) for key, value in (capture.get("count_deltas") or {}).items()
        },
        "sysref_capture_running": bool(capture.get("running")),
        "sysref_stopped_after_mts": not bool((result.get("sysref_capture") or {}).get("running")),
        "clock_transaction_id": result.get("clock_transaction_id"),
        "profile_sha256": live.get("profile_sha256"),
        "tics_file_sha256": live.get("tics_file_sha256"),
        "sysref_frequency_hz": live.get("sysref_frequency_hz"),
        "pl_sysref_delay_ps": live.get("pl_sysref_delay_ps"),
        "raw": result,
    }


def build_points(manifest: dict[str, Any], frequency_hz: int) -> list[dict[str, Any]]:
    rows = [
        row
        for row in manifest["profiles"]
        if int(row.get("sysref_frequency_hz", 0)) == frequency_hz
        and "_sdclkout3_phase_" in str(row.get("profile_id", ""))
    ]
    rows.sort(key=lambda row: float(row["phase_ps"]))
    if len(rows) != 32:
        raise RuntimeError(f"expected 32 phase profiles for {frequency_hz} Hz, found {len(rows)}")
    return [
        {
            "delay_ps": float(row["phase_ps"]),
            "profile_id": str(row["profile_id"]),
            "phase_controls": row["phase_controls"],
            "tics_profile_path": str(row["path"]),
            "tics_profile_sha256": str(row["file_sha256"]),
            "tics_register_sha256": str(row["register_sha256"]),
            "tics_pro_exported": True,
            "attempts": [],
        }
        for row in rows
    ]


def remote_sudo(host: str, command: str) -> None:
    result = subprocess.run(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=8",
            host,
            f"printf '%s\\n' xilinx | sudo -S {command}",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=60,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(f"remote command failed ({command}): {result.stdout.strip()}")


def restore_v34_services(
    *, host: str, agent_base: str, configure_template: dict[str, Any]
) -> dict[str, Any]:
    evidence: dict[str, Any] = {"errors": []}
    try:
        remote_sudo(host, "systemctl stop t510-stage34c2r-v35-agent.service")
    except Exception as exc:  # noqa: BLE001 - preserve cleanup diagnostics
        evidence["errors"].append(f"STOP_CANDIDATE:{type(exc).__name__}:{exc}")
    try:
        remote_sudo(host, "systemctl start t510-agent.service")
        deadline = time.monotonic() + 30.0
        while True:
            try:
                _http_json(agent_base.rstrip("/") + "/api/v2/capabilities", timeout=3.0)
                break
            except Exception:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(1.0)
        evidence["configure"] = _http_json(
            agent_base.rstrip("/") + "/api/v2/configure",
            method="POST",
            body=configure_body(configure_template, PRODUCTION_BITSTREAM_ID),
            timeout=240.0,
        )
        evidence["status"] = _http_json(agent_base.rstrip("/") + "/api/v2/status", timeout=30.0)
        if str(evidence["status"].get("core_version", "")).lower() != "0x00010034":
            raise RuntimeError("v34 production core was not restored")
        remote_sudo(host, "systemctl start t510-ref-watchdog.service")
    except Exception as exc:  # noqa: BLE001
        evidence["errors"].append(f"RESTORE_V34:{type(exc).__name__}:{exc}")
    evidence["restored"] = not evidence["errors"]
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent-base", default="http://192.168.100.117:8010")
    parser.add_argument("--board-ssh", default="xilinx@192.168.100.117")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--configure-template", type=Path, default=Path("config/t510/configure_320_time_only.example.json"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--frequency-hz",
        type=int,
        choices=(5_000_000, 10_000_000),
        action="append",
        dest="frequencies_hz",
        help="scan only the selected SYSREF frequency; repeat for multiple values",
    )
    parser.add_argument("--restore-v34", action="store_true")
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    template = json.loads(args.configure_template.read_text(encoding="utf-8"))
    output = args.output.resolve()
    frequencies_hz = tuple(args.frequencies_hz or (10_000_000, 5_000_000))
    campaign_path = output / "campaign.json"
    if campaign_path.exists():
        raise RuntimeError(f"refusing to overwrite phase-eye evidence: {campaign_path}")
    state: dict[str, Any] = {
        "schema_version": 1,
        "stage": "34c-2R",
        "classification": "PHASE_EYE_IN_PROGRESS",
        "operational_ok": False,
        "core_version": CORE_VERSION,
        "bitstream_id": BITSTREAM_ID,
        "bitstream_sha256": BITSTREAM_SHA256,
        "tics_manifest": str(args.manifest.resolve()),
        "requested_frequencies_hz": list(frequencies_hz),
        "frequencies": {},
        "errors": [],
        "started_at_unix_ms": time.time_ns() // 1_000_000,
    }
    write_json(campaign_path, state)
    try:
        state["candidate_capabilities"] = _http_json(
            args.agent_base.rstrip("/") + "/api/v2/capabilities", timeout=10.0
        )
        configured = _http_json(
            args.agent_base.rstrip("/") + "/api/v2/configure",
            method="POST",
            body=configure_body(template, BITSTREAM_ID),
            timeout=240.0,
        )
        state["candidate_configure"] = configured
        initial = _http_json(args.agent_base.rstrip("/") + "/api/v2/status", timeout=30.0)
        state["initial_status"] = initial
        if str(initial.get("core_version", "")).lower() != CORE_VERSION:
            raise RuntimeError(f"candidate CORE_VERSION mismatch: {initial.get('core_version')}")
        if initial.get("streaming") or initial.get("pipeline", {}).get("stream_accepting"):
            raise RuntimeError("phase-eye candidate did not remain stopped after CONFIGURE")
        write_json(campaign_path, state)
        for frequency_hz in frequencies_hz:
            points = build_points(manifest, frequency_hz)
            frequency_state = {
                "frequency_hz": frequency_hz,
                "points": points,
                "selection": None,
            }
            state["frequencies"][str(frequency_hz)] = frequency_state
            write_json(campaign_path, state)
            for point_index, point in enumerate(points, start=1):
                print(
                    f"PHASE_POINT_START frequency_hz={frequency_hz} point={point_index}/32 "
                    f"phase_ps={point['delay_ps']} profile={point['profile_id']}",
                    flush=True,
                )
                first = prepare(args.agent_base, point["profile_id"], attempt_kind="overlay_reload")
                point["attempts"].append(
                    extract_attempt(first, "overlay_reload", point["tics_profile_sha256"])
                )
                write_json(campaign_path, state)
                for reset_index in range(1, 4):
                    repeated = prepare(args.agent_base, point["profile_id"], attempt_kind="rfdc_reset")
                    point["attempts"].append(
                        extract_attempt(repeated, "rfdc_reset", point["tics_profile_sha256"])
                    )
                    write_json(campaign_path, state)
                    print(
                        f"PHASE_POINT_RESET_OK frequency_hz={frequency_hz} point={point_index}/32 "
                        f"reset={reset_index}/3",
                        flush=True,
                    )
                point["restore"] = restore_clock(args.agent_base)
                write_json(campaign_path, state)
                print(
                    f"PHASE_POINT_COMPLETE frequency_hz={frequency_hz} point={point_index}/32",
                    flush=True,
                )
            selection = select_eye(
                points,
                frequency_hz=frequency_hz,
                setup_ns=SETUP_NS,
                hold_ns=HOLD_NS,
            )
            frequency_state["selection"] = selection
            write_json(output / f"phase_eye_{frequency_hz // 1_000_000}mhz.json", selection)
            write_json(campaign_path, state)
            if not selection["qualified"]:
                raise RuntimeError(f"{frequency_hz} Hz has no qualified phase eye")
        state["classification"] = (
            "PHASE_EYE_10M_5M_QUALIFIED"
            if set(frequencies_hz) == {10_000_000, 5_000_000}
            else f"PHASE_EYE_{frequencies_hz[0] // 1_000_000}M_QUALIFIED"
        )
        state["operational_ok"] = True
    except Exception as exc:  # noqa: BLE001
        state["errors"].append(f"{type(exc).__name__}: {exc}")
        state["classification"] = "PHASE_EYE_OPERATIONAL_FAIL"
    finally:
        try:
            state["candidate_clock_restore"] = restore_clock(args.agent_base)
        except Exception as exc:  # noqa: BLE001
            state["errors"].append(f"CANDIDATE_RESTORE:{type(exc).__name__}:{exc}")
        if args.restore_v34:
            state["v34_restore"] = restore_v34_services(
                host=args.board_ssh,
                agent_base=args.agent_base,
                configure_template=template,
            )
            if not state["v34_restore"]["restored"]:
                state["errors"].extend(state["v34_restore"]["errors"])
        state["finished_at_unix_ms"] = time.time_ns() // 1_000_000
        if state["errors"]:
            state["operational_ok"] = False
            state["classification"] = "PHASE_EYE_OPERATIONAL_FAIL"
        write_json(campaign_path, state)
    print(
        json.dumps(
            {
                "classification": state["classification"],
                "operational_ok": state["operational_ok"],
                "campaign": str(campaign_path),
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0 if state["operational_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
