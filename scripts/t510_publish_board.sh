#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="${PYNQ_TARGET:-xilinx@192.168.100.117}"
SSH_OPTS="${PYNQ_SSH_OPTS:-}"
MODE="${1:---build-only}"
STAGE="${ROOT}/build/board/latest/package"
REMOTE_STAGE="/home/xilinx/.cache/t510/latest"
CATALOG="${ROOT}/config/t510/config.example.json"
METADATA="${ROOT}/config/t510/current_release.json"
OVERLAY_DIR="${T510_OVERLAY_DIR:-${ROOT}/overlay}"

case "${MODE}" in
  --build-only|--install) ;;
  *) echo "usage: t510_publish_board.sh [--build-only|--install]" >&2; exit 2 ;;
esac

VERIFY_ARGS=(--metadata "${METADATA}" --catalog "${CATALOG}" \
  --bitstream "${OVERLAY_DIR}/t510_fengine.bit")
if [[ "${MODE}" == "--build-only" ]]; then
  VERIFY_ARGS+=(--allow-unqualified)
else
  VERIFY_ARGS+=(--require-reference onboard_tcxo)
fi
python3 "${ROOT}/scripts/t510_current_release.py" "${VERIFY_ARGS[@]}" >/dev/null
EXPECTED_SHA="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["bitstream_sha256"])' "${METADATA}")"

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
  "${STAGE}/config" "${STAGE}/scripts" "${STAGE}/deploy/t510-agent.service.d"
install -m 0755 "${ROOT}/rust/t510_board_agent/target/aarch64-unknown-linux-musl/release/t510-board-agent" "${STAGE}/bin/t510-board-agent"
install -m 0755 "${ROOT}/python/t510_hw.py" "${STAGE}/python/t510_hw.py"
install -m 0755 "${ROOT}/python/t510_ref_watchdog.py" "${STAGE}/python/t510_ref_watchdog.py"
install -m 0644 "${ROOT}/python/__init__.py" "${STAGE}/python/__init__.py"
install -m 0644 "${ROOT}/python/packet.py" "${STAGE}/python/packet.py"
install -m 0644 "${ROOT}/python/t510_control.py" "${STAGE}/python/t510_control.py"
install -m 0644 "${ROOT}/python/t510_fengine.py" "${STAGE}/python/t510_fengine.py"
install -m 0644 "${ROOT}/python/t510_scaling.py" "${STAGE}/python/t510_scaling.py"
install -m 0644 "${ROOT}/python/t510_mts_target.py" "${STAGE}/python/t510_mts_target.py"
install -m 0644 "${ROOT}/python/t510_clock.py" "${STAGE}/python/t510_clock.py"
install -m 0644 "${ROOT}/python/t510_ams.py" "${STAGE}/python/t510_ams.py"
install -m 0644 "${OVERLAY_DIR}/t510_fengine.bit" "${STAGE}/overlay/t510_fengine.bit"
install -m 0644 "${OVERLAY_DIR}/t510_fengine.hwh" "${STAGE}/overlay/t510_fengine.hwh"
install -m 0644 "${OVERLAY_DIR}/t510_fengine.tcl" "${STAGE}/overlay/t510_fengine.tcl"
install -m 0644 "${OVERLAY_DIR}/t510_fengine.manifest.txt" "${STAGE}/overlay/t510_fengine.manifest.txt"
install -m 0644 "${CATALOG}" "${STAGE}/config/config.example.json"
install -m 0644 "${METADATA}" "${STAGE}/config/current_release.json"
install -m 0644 "${ROOT}/config/t510/qualification-template.json" "${STAGE}/config/qualification-template.json"
install -m 0755 "${ROOT}/scripts/t510_current_release.py" "${STAGE}/scripts/t510_current_release.py"
for helper in pynq_t510_mts_campaign.py t510_finalize_catalog.py \
  t510_board_host_gate.py t510_host_validate.py t510_multiboard_sync.py \
  t510_scheduled_pps_gate.py t510_release_qualification.py; do
  install -m 0755 "${ROOT}/scripts/${helper}" "${STAGE}/scripts/${helper}"
done
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
