#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="${PYNQ_TARGET:-xilinx@192.168.100.117}"
SSH_OPTS="${PYNQ_SSH_OPTS:-}"
MODE="${1:---build-only}"
RELEASE_ID="${STAGE31_RELEASE_ID:-stage31-$(git -C "${ROOT}" rev-parse --short=12 HEAD)-$(date -u +%Y%m%d%H%M%S)}"
BUILD_DIR="${ROOT}/build/stage31"
STAGE="${BUILD_DIR}/${RELEASE_ID}"
REMOTE_STAGE="/home/xilinx/.cache/t510-stage31/${RELEASE_ID}"
EXPECTED_SHA="3696845d30dc471f572904b7039aa231bc766a21be05de7796d53704f8d08eec"

case "${MODE}" in
  --build-only|--install) ;;
  *) echo "usage: pynq_publish_stage31.sh [--build-only|--install]" >&2; exit 2 ;;
esac

test "$(sha256sum "${ROOT}/overlay/t510_fengine.bit" | awk '{print $1}')" = "${EXPECTED_SHA}"
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

rm -rf "${STAGE}"
install -d "${STAGE}/bin" "${STAGE}/python" "${STAGE}/overlay" \
  "${STAGE}/config" "${STAGE}/deploy"
install -m 0755 \
  "${ROOT}/rust/t510_board_agent/target/aarch64-unknown-linux-musl/release/t510-board-agent" \
  "${STAGE}/bin/t510-board-agent"
install -m 0755 "${ROOT}/python/t510_hw.py" "${STAGE}/python/t510_hw.py"
install -m 0644 "${ROOT}/python/__init__.py" "${STAGE}/python/__init__.py"
install -m 0644 "${ROOT}/python/packet.py" "${STAGE}/python/packet.py"
install -m 0644 "${ROOT}/python/stage29.py" "${STAGE}/python/stage29.py"
install -m 0644 "${ROOT}/python/t510_fengine.py" "${STAGE}/python/t510_fengine.py"
install -m 0644 "${ROOT}/python/t510_clock.py" "${STAGE}/python/t510_clock.py"
install -m 0644 "${ROOT}/overlay/t510_fengine.bit" "${STAGE}/overlay/t510_fengine.bit"
install -m 0644 "${ROOT}/overlay/t510_fengine.hwh" "${STAGE}/overlay/t510_fengine.hwh"
install -m 0644 "${ROOT}/overlay/t510_fengine.tcl" "${STAGE}/overlay/t510_fengine.tcl"
install -m 0644 "${ROOT}/overlay/t510_fengine.manifest.txt" "${STAGE}/overlay/t510_fengine.manifest.txt"
install -m 0644 "${ROOT}/config/stage31/config.example.json" "${STAGE}/config/config.example.json"
install -m 0644 "${ROOT}/deploy/stage30/t510-agent.service" "${STAGE}/deploy/t510-agent.service"
install -m 0755 "${ROOT}/deploy/stage31/install-on-board.sh" "${STAGE}/deploy/install-on-board.sh"

file "${STAGE}/bin/t510-board-agent" | grep -q 'ARM aarch64'
if readelf -l "${STAGE}/bin/t510-board-agent" | grep -q 'Requesting program interpreter'; then
  echo "Stage 31 binary is dynamically linked; expected static musl" >&2
  exit 1
fi

if [[ "${MODE}" == "--build-only" ]]; then
  echo "Built static Stage 31 release at ${STAGE}"
  exit 0
fi

before="$(ssh ${SSH_OPTS} "${TARGET}" \
  "systemctl is-active jupyter.service || true; systemctl is-active t510-agent.service || true")"
echo "Before deployment (Jupyter, Agent):"
echo "${before}"

ssh ${SSH_OPTS} "${TARGET}" "mkdir -p '${REMOTE_STAGE}'"
rsync -a --delete -e "ssh ${SSH_OPTS}" "${STAGE}/" "${TARGET}:${REMOTE_STAGE}/"

remote_install="bash '${REMOTE_STAGE}/deploy/install-on-board.sh' '${REMOTE_STAGE}' '${RELEASE_ID}'"
if [[ -n "${PYNQ_SUDO_PASSWORD:-}" ]]; then
  printf '%s\n' "${PYNQ_SUDO_PASSWORD}" | ssh ${SSH_OPTS} "${TARGET}" "sudo -S ${remote_install}"
else
  ssh -t ${SSH_OPTS} "${TARGET}" "sudo ${remote_install}"
fi

after="$(ssh ${SSH_OPTS} "${TARGET}" \
  "systemctl is-active jupyter.service || true; systemctl is-active t510-agent.service || true")"
echo "After deployment (Jupyter, Agent):"
echo "${after}"
curl --fail --silent --show-error --max-time 10 \
  "http://${TARGET#*@}:8010/api/v1/bitstreams" >/dev/null
echo "Installed ${RELEASE_ID}; run configure to fresh-download the Stage 31 bitstream"
