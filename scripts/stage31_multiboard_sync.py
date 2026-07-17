#!/usr/bin/env python3
"""Two-phase Stage 31 coordinator for a small station without a Center Hub.

Each --board argument is URL,BOARD_ID.  The script reads every board's
persisted configure-time MTS result, maps one common future event onto each
board's local PPS counter, prepares every board, and only then arms the whole
set.  A partial prepare or arm causes a best-effort abort on all boards.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import sys
import urllib.error
import urllib.request


def request(url: str, path: str, body: dict | None = None) -> dict:
    data = None if body is None else json.dumps(body, separators=(",", ":")).encode()
    req = urllib.request.Request(
        url.rstrip("/") + path,
        data=data,
        headers={"Content-Type": "application/json"} if data is not None else {},
        method="POST" if data is not None else "GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=45.0) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"{req.full_url}: HTTP {exc.code}: {details}") from exc
    return dict(payload.get("result", payload))


def parse_board(value: str) -> tuple[str, int]:
    try:
        url, board_id = value.rsplit(",", 1)
        return url.rstrip("/"), int(board_id, 0)
    except (ValueError, TypeError) as exc:
        raise argparse.ArgumentTypeError("board must be URL,BOARD_ID") from exc


def read_snapshots(boards: list[tuple[str, int]]) -> list[tuple[str, int, dict]]:
    def read_one(board: tuple[str, int]) -> tuple[str, int, dict]:
        url, board_id = board
        result = request(url, "/api/v1/sync/status")
        return url, board_id, dict(result["sync"])

    with ThreadPoolExecutor(max_workers=len(boards)) as pool:
        return list(pool.map(read_one, boards))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--board", action="append", required=True, type=parse_board)
    parser.add_argument("--generation", required=True, type=int)
    parser.add_argument("--epoch-tai", required=True, type=int)
    parser.add_argument("--lead-pps", type=int, default=30)
    parser.add_argument(
        "--first-sample0",
        type=int,
        help="raw-sample epoch offset; omitted selects the hardware-reported safe default",
    )
    parser.add_argument("--observation-tag", type=lambda value: int(value, 0), default=0)
    parser.add_argument("--signal-chain-tag", type=lambda value: int(value, 0), required=True)
    parser.add_argument("--schedule-tag", type=lambda value: int(value, 0), default=0)
    args = parser.parse_args()

    board_ids = [board_id for _, board_id in args.board]
    if len(set(board_ids)) != len(board_ids):
        parser.error("each --board BOARD_ID must be unique")
    if args.generation <= 0:
        parser.error("--generation must be positive")
    if args.epoch_tai <= 0:
        parser.error("--epoch-tai must be positive TAI seconds")
    if args.lead_pps < 2:
        parser.error("--lead-pps must be at least 2")
    if not 0 < args.signal_chain_tag <= 0xFFFF_FFFF:
        parser.error("--signal-chain-tag must be in 1..0xffffffff")
    # Each helper response contains one internally consistent register snapshot.
    # Stateless PYNQ helper startup takes several seconds on the board, so a
    # second HTTP sample cannot prove a 50 ms PPS-free window. Read all boards
    # once in parallel and use a generous future local-PPS lead instead.
    snapshots = read_snapshots(args.board)

    for _, board_id, sync in snapshots:
        if not sync.get("ref_locked") or not sync.get("rfdc_ready") or not sync.get("pps_recent"):
            raise RuntimeError(f"board {board_id} is not timing-ready: {sync}")
        if not int(sync.get("mts_result_id", 0)):
            raise RuntimeError(f"board {board_id} has no persisted configure-time MTS result")

    path_rules = {
        (
            int(sync["bandwidth_mode"]),
            bool(sync["aa100_active"]),
            int(sync["first_sample0_modulus"]),
            int(sync["first_sample0_residue"]),
        )
        for _, _, sync in snapshots
    }
    if len(path_rules) != 1:
        raise RuntimeError(
            "boards do not have one common science-path alignment rule: "
            f"{sorted(path_rules)}"
        )
    _, _, modulus, residue = next(iter(path_rules))
    first_sample0 = (
        int(args.first_sample0)
        if args.first_sample0 is not None
        else int(snapshots[0][2]["default_first_sample0"])
    )
    if first_sample0 <= 0 or first_sample0 % modulus != residue:
        parser.error(
            f"--first-sample0 must satisfy value % {modulus} == {residue} "
            "for the configured science path"
        )

    target_pps_by_board = {
        board_id: int(sync["current_pps_count"]) + args.lead_pps
        for _, board_id, sync in snapshots
    }
    prepared: list[tuple[str, int]] = []
    try:
        prepare_jobs = []
        with ThreadPoolExecutor(max_workers=len(snapshots)) as pool:
            for url, board_id, sync in snapshots:
                body = {
                    "expected_board_id": board_id,
                    "generation": args.generation,
                    "target_pps_count": target_pps_by_board[board_id],
                    "epoch_tai_seconds": args.epoch_tai,
                    "first_sample0": first_sample0,
                    "observation_tag": args.observation_tag,
                    "signal_chain_tag": args.signal_chain_tag,
                    "schedule_tag": args.schedule_tag,
                    "mts_result_id": int(sync["mts_result_id"]),
                }
                prepare_jobs.append((pool.submit(request, url, "/api/v1/sync/prepare", body), url, board_id))
            for future in as_completed([job[0] for job in prepare_jobs]):
                _, url, board_id = next(job for job in prepare_jobs if job[0] is future)
                future.result()
                prepared.append((url, board_id))

        armed = []
        arm_jobs = []
        with ThreadPoolExecutor(max_workers=len(prepared)) as pool:
            for url, board_id in prepared:
                future = pool.submit(
                    request, url, "/api/v1/sync/arm", {"expected_board_id": board_id}
                )
                arm_jobs.append((future, url, board_id))
            for future in as_completed([job[0] for job in arm_jobs]):
                _, url, board_id = next(job for job in arm_jobs if job[0] is future)
                armed.append({"url": url, "board_id": board_id, "result": future.result()})
    except Exception:
        for url, board_id in prepared:
            try:
                request(url, "/api/v1/sync/abort", {"expected_board_id": board_id})
            except Exception as abort_error:  # best-effort cleanup is reported, not hidden
                print(f"abort failed for board {board_id}: {abort_error}", file=sys.stderr)
        raise

    print(json.dumps({
        "generation": args.generation,
        "target_pps_count_by_board": target_pps_by_board,
        "epoch_tai_seconds": args.epoch_tai,
        "first_sample0": first_sample0,
        "boards": armed,
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
