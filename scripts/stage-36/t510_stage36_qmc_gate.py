#!/usr/bin/env python3
"""Run the bounded v34/QMC candidate TIME gate, then restore effective QMC state.

Uses the established Stage 35 full-rate writer and raw-PCAP verifier. All new
datasets have Stage 36 IDs and explicit gain metadata; no old scan is overwritten.
"""

from __future__ import annotations

import argparse
import csv
import fcntl
import json
import os
from pathlib import Path
import shlex
import subprocess
import time
import traceback

import t510_stage35_s2_queue as base
import t510_time_capture_verify as time_verify
from t510_stage36_qmc_probe import QMC_GAIN


class Gate(base.QueueRunner):
    def __init__(self, args, template):
        super().__init__(args, template)
        self.phases = [dict(index=0, label="a-time-pre", scan="QMC", position="candidate",
                            kind="time", mode="time_only", duration_seconds=30,
                            scan_id=args.queue_id + "-time-30s", status="pending")]
        self.state.update(format="T510_STAGE36_QMC_GATE_V1", phases=self.phases,
                          pipeline=["preflight", "QMC_apply_and_readback", "30s_TIME",
                                    "50ms_raw_witness", "independent_verify", "restore_QMC"],
                          requested_qmc_gain=QMC_GAIN, pfb_output_shift=17,
                          gate_is_not_stage36_science_release=True)
        self.qmc_attempted = False

    def qmc(self, action):
        command = ["sudo", "-S", "-p", "", "/usr/local/share/pynq-venv/bin/python3",
                   str(self.args.board_helper), action, "--journal", str(self.args.board_journal)]
        env = dict(os.environ, SSH_ASKPASS=str(self.args.askpass),
                   SSH_ASKPASS_REQUIRE="force", DISPLAY="stage36-askpass")
        process = subprocess.run(
            ["ssh", "-o", "StrictHostKeyChecking=yes", "-o", "ConnectTimeout=6",
             "-o", "NumberOfPasswordPrompts=1", "-o", "BatchMode=no",
             "-o", f"UserKnownHostsFile={self.args.known_hosts}",
             "xilinx@192.168.100.117", shlex.join(command)],
            input=os.environ["PYNQ_SUDO_PASSWORD"] + "\n", text=True,
            capture_output=True, timeout=60, env=env, start_new_session=True)
        record = dict(action=action, returncode=process.returncode,
                      stdout=process.stdout, stderr=process.stderr)
        base.write_json_new(self.evidence / f"qmc_{action}_{base.unix_ms()}.json", record)
        if process.returncode:
            raise RuntimeError(f"QMC {action} failed: {process.stderr or process.stdout}")
        return json.loads(process.stdout)

    def preflight(self):
        super().preflight()
        board = self.board()
        if board.get("profile", {}).get("mode") != "time_only":
            raise RuntimeError("QMC gate requires the already-configured TIME-only baseline")
        cross = self.receiver("/api/measure/crosscorrelation/status")
        if cross.get("status") in ("armed", "running", "draining"):
            raise RuntimeError("another cross-correlation observation is active")
        before = self.qmc("snapshot")
        if any(row["qmc"]["EnableGain"] or row["qmc"]["EnablePhase"]
               or row["qmc"]["OffsetCorrectionFactor"] for row in before["blocks"]):
            raise RuntimeError("original QMC is not the frozen disabled baseline")
        self.state["qmc_original"] = before
        self.save()

    def ensure_mode(self, phase):
        super().ensure_mode(phase)
        self.qmc_attempted = True
        self.state["qmc_applied"] = self.qmc("apply")
        self.save()

    def receiver(self, path="/api/state", **kwargs):
        body = kwargs.get("body")
        if path == "/api/measure/time" and body is not None:
            body["metadata"].update(stage="36", step="QMC_qualification",
                                    qmc_gain=str(QMC_GAIN), pfb_output_shift="17",
                                    scaling_profile="stage36-qmc-candidate-on-v34",
                                    actual_core_version="0x00010034")
        return super().receiver(path, **kwargs)

    def verify_candidate(self):
        after = self.qmc("snapshot")
        base.write_json_new(self.evidence / "qmc_after_capture.json", after)
        for row in after["blocks"]:
            if row["adc_error_bits"]:
                raise RuntimeError(f"RFDC interrupt gate failed: {row}")
            if row["qmc"] != self.state["qmc_applied"]["snapshot"]["blocks"][row["tile"]*2+row["block"]]["qmc"]:
                raise RuntimeError("QMC changed during capture")
        dataset = self.args.measurement_root / self.phases[0]["scan_id"]
        verified = time_verify.verify(dataset)
        base.write_json_new(self.evidence / "independent_time_verification.json", verified)
        summary = json.loads((dataset / "summary.json").read_text())
        parity = {(lane, comp): [0, 0] for lane in range(8) for comp in ("I", "Q")}
        with (dataset / "histogram.csv").open() as stream:
            for row in csv.DictReader(stream):
                parity[int(row["lane"]), row["component"]][int(row["code"]) & 1] += int(row["count"])
        errors, rows = [], []
        for lane in summary["lanes"]:
            result = dict(lane)
            for comp in ("I", "Q"):
                std = float(lane[f"std_{comp.lower()}_adu"])
                counts = parity[lane["lane"], comp]
                odd = counts[1] / sum(counts)
                result[f"{comp.lower()}_odd_code_fraction"] = odd
                if not 8 <= std <= 12:
                    errors.append(f"ADC{lane['lane']} {comp} std={std:.6f} outside [8,12]")
                if not 0.1 <= odd <= 0.9:
                    errors.append(f"ADC{lane['lane']} {comp} sparse LSB occupancy: odd={odd}")
                if lane[f"clip_{comp.lower()}"]:
                    errors.append(f"ADC{lane['lane']} {comp} clipped")
            rows.append(result)
        result = dict(status="FAIL" if errors else "PASS", errors=errors, lanes=rows,
                      qmc_gain=QMC_GAIN, samples_per_lane=summary["samples_per_lane"],
                      qualification="amplitude_code_occupancy_and_integrity_only_not_ADC_ENOB",
                      pfb_rtl_changed=False)
        base.write_json_new(self.evidence / "candidate_numeric_gate.json", result)
        self.state["numeric_gate"] = result
        self.save()
        if errors:
            raise RuntimeError(f"QMC candidate numerical gate failed: {errors}")

    def run(self):
        self.initialize()
        self.state.update(status="running", started_unix_ms=base.unix_ms())
        self.save()
        error = None
        cleanup_errors = []
        try:
            self.preflight()
            self.run_phase(self.phases[0])
            self.verify_candidate()
        except Exception as exc:
            error = dict(message=str(exc), traceback=traceback.format_exc())
            self.event("gate_failed", error=error)
        finally:
            # Do not disturb pre-existing work if preflight rejected ownership.
            if self.qmc_attempted:
                cleanup_errors = self.safe_finalize(failed=error is not None)
                if not cleanup_errors:
                    try:
                        self.state["qmc_restore"] = self.qmc("restore")
                    except Exception as exc:
                        cleanup_errors.append(f"QMC restore failed: {exc}")
        self.state.update(status="failed" if error or cleanup_errors else "completed",
                          error=error, cleanup_errors=cleanup_errors,
                          finished_unix_ms=base.unix_ms())
        self.save()
        print(json.dumps(dict(status=self.state["status"], root=str(self.root),
                              error=error, cleanup_errors=cleanup_errors)), flush=True)
        return int(bool(error or cleanup_errors))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue-id", required=True)
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--board-helper", type=Path, required=True)
    parser.add_argument("--board-journal", type=Path, required=True)
    parser.add_argument("--known-hosts", type=Path, required=True)
    parser.add_argument("--askpass", type=Path, required=True)
    parser.add_argument("--helper-dir", type=Path, required=True)
    parser.add_argument("--measurement-root", type=Path, default=Path("/var/lib/t510/measurements"))
    parser.add_argument("--agent-base", default="http://192.168.100.117:8010")
    parser.add_argument("--receiver-base", default="http://127.0.0.1:8089")
    parser.add_argument("--center-mhz", type=float, default=200.0)
    parser.add_argument("--minimum-free-bytes", type=int, default=10*1024**3)
    args = parser.parse_args()
    if not args.queue_id.startswith("stage36-") or not all(c.isalnum() or c in "-_" for c in args.queue_id):
        parser.error("queue-id must be a Stage 36 identifier")
    if not os.environ.get("PYNQ_SUDO_PASSWORD"):
        parser.error("PYNQ_SUDO_PASSWORD is required")
    if not args.known_hosts.is_file() or not os.access(args.askpass, os.X_OK):
        parser.error("pinned known-hosts and executable askpass are required")
    with Path("/run/lock/t510-stage36-qmc.lock").open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return Gate(args, json.loads(args.template.read_text())).run()


if __name__ == "__main__":
    raise SystemExit(main())
