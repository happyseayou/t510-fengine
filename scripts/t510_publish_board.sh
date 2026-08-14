#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="${PYNQ_TARGET:-xilinx@192.168.100.117}"
SSH_OPTS="${PYNQ_SSH_OPTS:-}"
MODE="${1:---build-only}"
STAGE="${ROOT}/build/board/latest/package"
REMOTE_STAGE="/home/xilinx/.cache/t510/latest"
CATALOG="${ROOT}/config/t510/config.example.json"
OVERLAY_DIR="${T510_OVERLAY_DIR:-${ROOT}/overlay}"

case "${MODE}" in
  --build-only|--install) ;;
  *) echo "usage: t510_publish_board.sh [--build-only|--install]" >&2; exit 2 ;;
esac

EXPECTED_SHA="$(python3 - "${CATALOG}" <<'PY'
import json
import sys

catalog = json.load(open(sys.argv[1], "r", encoding="utf-8"))
entry = next(item for item in catalog["bitstreams"] if item["id"] == "fengine-0x00010034")
if entry.get("core_version") != "0x00010034":
    raise SystemExit("catalog core version is not current T510 release")
if entry.get("sha256") == "0" * 64:
    raise SystemExit("catalog is not finalized; run both MTS campaigns and t510_finalize_catalog.py")
if min(entry.get("mts_adc_target_latency", -1), entry.get("mts_dac_target_latency", -1)) < 0:
    raise SystemExit("catalog MTS targets are not finalized")
if entry.get("mts_adc_target_latency") == 230 or entry.get("mts_dac_target_latency") == 336:
    raise SystemExit("catalog reuses a forbidden retired MTS target")
campaign = entry.get("mts_campaign")
if not isinstance(campaign, dict):
    raise SystemExit("catalog MTS campaign proof is missing")
expected = {"rfdc_reset": 20, "overlay_reload": 10, "lmk_reload": 10, "passed": 40}
if campaign.get("discovery") != expected or campaign.get("fixed") != expected:
    raise SystemExit("catalog MTS campaigns are not the frozen 40/40 matrices")
if campaign.get("adc_margin") != 20 or campaign.get("dac_margin") != 16:
    raise SystemExit("catalog MTS margins are invalid")
if entry["mts_adc_target_latency"] != campaign.get("observed_adc_max", -1) + 20:
    raise SystemExit("catalog ADC MTS target is not discovery max +20")
if entry["mts_dac_target_latency"] != campaign.get("observed_dac_max", -1) + 16:
    raise SystemExit("catalog DAC MTS target is not discovery max +16")
print(entry["sha256"])
PY
)"
test "$(sha256sum "${OVERLAY_DIR}/t510_fengine.bit" | awk '{print $1}')" = "${EXPECTED_SHA}"

if ! command -v zig >/dev/null 2>&1; then
  CARGO_ZIGBUILD_ZIG_PATH="$(
    python3 -c 'from pathlib import Path; import ziglang; print(Path(ziglang.__file__).with_name("zig"))'
  )"
  export CARGO_ZIGBUILD_ZIG_PATH
fi
cargo zigbuild \
  --manifest-path "${ROOT}/rust/t510_board_agent/Cargo.toml" \
  --target aarch64-unknown-linux-musl \
  --release

case "${STAGE}" in
  "${ROOT}/build/board/latest/package") ;;
  *) echo "refusing unsafe local stage path: ${STAGE}" >&2; exit 1 ;;
esac
rm -rf -- "${STAGE}"
install -d "${STAGE}/bin" "${STAGE}/python" "${STAGE}/overlay" \
  "${STAGE}/config" "${STAGE}/deploy/t510-agent.service.d"
install -m 0755 "${ROOT}/rust/t510_board_agent/target/aarch64-unknown-linux-musl/release/t510-board-agent" "${STAGE}/bin/t510-board-agent"
install -m 0755 "${ROOT}/python/t510_hw.py" "${STAGE}/python/t510_hw.py"
install -m 0755 "${ROOT}/python/t510_ref_watchdog.py" "${STAGE}/python/t510_ref_watchdog.py"
install -m 0644 "${ROOT}/python/__init__.py" "${STAGE}/python/__init__.py"
install -m 0644 "${ROOT}/python/packet.py" "${STAGE}/python/packet.py"
install -m 0644 "${ROOT}/python/t510_control.py" "${STAGE}/python/t510_control.py"
install -m 0644 "${ROOT}/python/t510_fengine.py" "${STAGE}/python/t510_fengine.py"
install -m 0644 "${ROOT}/python/t510_clock.py" "${STAGE}/python/t510_clock.py"
install -m 0644 "${ROOT}/python/t510_ams.py" "${STAGE}/python/t510_ams.py"
install -m 0644 "${OVERLAY_DIR}/t510_fengine.bit" "${STAGE}/overlay/t510_fengine.bit"
install -m 0644 "${OVERLAY_DIR}/t510_fengine.hwh" "${STAGE}/overlay/t510_fengine.hwh"
install -m 0644 "${OVERLAY_DIR}/t510_fengine.tcl" "${STAGE}/overlay/t510_fengine.tcl"
install -m 0644 "${OVERLAY_DIR}/t510_fengine.manifest.txt" "${STAGE}/overlay/t510_fengine.manifest.txt"
install -m 0644 "${CATALOG}" "${STAGE}/config/config.example.json"
install -m 0644 "${ROOT}/deploy/t510/t510-agent.service" "${STAGE}/deploy/t510-agent.service"
install -m 0644 "${ROOT}/deploy/t510/t510-ref-watchdog.service" "${STAGE}/deploy/t510-ref-watchdog.service"
install -m 0644 "${ROOT}/deploy/t510/t510-agent.service.d/center-hub.conf" "${STAGE}/deploy/t510-agent.service.d/center-hub.conf"
install -m 0755 "${ROOT}/deploy/t510/install-on-board.sh" "${STAGE}/deploy/install-on-board.sh"

file "${STAGE}/bin/t510-board-agent" | grep -q 'ARM aarch64'
if readelf -l "${STAGE}/bin/t510-board-agent" | grep -q 'Requesting program interpreter'; then
  echo "board Agent binary is dynamically linked; expected static musl" >&2
  exit 1
fi

if [[ "${MODE}" == "--build-only" ]]; then
  echo "Built current board release at ${STAGE}"
  exit 0
fi

before="$(ssh ${SSH_OPTS} "${TARGET}" \
  "systemctl is-active jupyter.service || true; systemctl is-active t510-agent.service || true; systemctl is-active t510-ref-watchdog.service || true")"
echo "Before deployment (Jupyter, Agent, watchdog):"
echo "${before}"

ssh ${SSH_OPTS} "${TARGET}" "mkdir -p '${REMOTE_STAGE}'"
rsync -a --delete -e "ssh ${SSH_OPTS}" "${STAGE}/" "${TARGET}:${REMOTE_STAGE}/"

remote_install="bash '${REMOTE_STAGE}/deploy/install-on-board.sh' '${REMOTE_STAGE}'"
if [[ -n "${PYNQ_SUDO_PASSWORD:-}" ]]; then
  printf '%s\n' "${PYNQ_SUDO_PASSWORD}" | ssh ${SSH_OPTS} "${TARGET}" "sudo -S ${remote_install}"
else
  ssh -t ${SSH_OPTS} "${TARGET}" "sudo ${remote_install}"
fi
ssh ${SSH_OPTS} "${TARGET}" "rm -rf -- '${REMOTE_STAGE}'"

after="$(ssh ${SSH_OPTS} "${TARGET}" \
  "systemctl is-active jupyter.service || true; systemctl is-active t510-agent.service || true; systemctl is-active t510-ref-watchdog.service || true")"
echo "After deployment (Jupyter, Agent, watchdog):"
echo "${after}"
curl --fail --silent --show-error --max-time 10 "http://${TARGET#*@}:8010/api/v2/bitstreams" >/dev/null
echo "Installed current board release; run configure only when a fresh FPGA download is required"
