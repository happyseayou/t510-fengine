#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="${STAGE33_RX_TARGET:-astrolab@192.168.100.162}"
SSH_OPTS="${STAGE33_RX_SSH_OPTS:-}"
MODE="${1:---build-only}"
RELEASE_ID="${STAGE33_RX_RELEASE_ID:-stage33-$(git -C "${ROOT}" rev-parse --short=12 HEAD)-$(date -u +%Y%m%d%H%M%S)}"
BUILD_DIR="${ROOT}/build/stage33-rx"
STAGE="${BUILD_DIR}/${RELEASE_ID}"
REMOTE_STAGE="/home/astrolab/.cache/t510-stage33-rx/${RELEASE_ID}"

case "${MODE}" in
  --build-only|--stage-remote) ;;
  *) echo "usage: host_publish_stage33_rx.sh [--build-only|--stage-remote]" >&2; exit 2 ;;
esac

if ! command -v zig >/dev/null 2>&1; then
  CARGO_ZIGBUILD_ZIG_PATH="$(
    python3 -c 'from pathlib import Path; import ziglang; print(Path(ziglang.__file__).with_name("zig"))'
  )"
  export CARGO_ZIGBUILD_ZIG_PATH
fi
cargo zigbuild \
  --manifest-path "${ROOT}/rust/t510_time_rx/Cargo.toml" \
  --target aarch64-unknown-linux-musl \
  --release

test ! -e "${STAGE}"
install -d "${STAGE}"
install -m 0755 "${ROOT}/rust/t510_time_rx/target/aarch64-unknown-linux-musl/release/t510_time_rx" "${STAGE}/t510_time_rx"
install -m 0755 "${ROOT}/scripts/host_t510_rx_tune.sh" "${STAGE}/host_t510_rx_tune.sh"
install -m 0755 "${ROOT}/scripts/t510_host_validate.py" "${STAGE}/t510_host_validate.py"
install -m 0644 "${ROOT}/deploy/stage33/t510-time-rx.service" "${STAGE}/t510-time-rx.service"
install -m 0644 "${ROOT}/deploy/stage33/t510-rx-tune.service" "${STAGE}/t510-rx-tune.service"
install -m 0644 "${ROOT}/deploy/stage33/90-t510-rx.conf" "${STAGE}/90-t510-rx.conf"
install -m 0755 "${ROOT}/deploy/stage33/install-receiver.sh" "${STAGE}/install-receiver.sh"
(cd "${STAGE}" && sha256sum t510_time_rx host_t510_rx_tune.sh t510_host_validate.py t510-time-rx.service t510-rx-tune.service 90-t510-rx.conf install-receiver.sh > SHA256SUMS)

file "${STAGE}/t510_time_rx" | grep -q 'ARM aarch64'
if readelf -l "${STAGE}/t510_time_rx" | grep -q 'Requesting program interpreter'; then
  echo "Stage 33 receiver is dynamically linked; expected static musl" >&2
  exit 1
fi

if [[ "${MODE}" == "--build-only" ]]; then
  echo "Built static Stage 33 receiver release at ${STAGE}"
  exit 0
fi

ssh ${SSH_OPTS} "${TARGET}" "mkdir -p '${REMOTE_STAGE}'"
rsync -a -e "ssh ${SSH_OPTS}" "${STAGE}/" "${TARGET}:${REMOTE_STAGE}/"
echo "Staged ${RELEASE_ID} at ${TARGET}:${REMOTE_STAGE}"
echo "Install with: sudo bash '${REMOTE_STAGE}/install-receiver.sh' '${REMOTE_STAGE}' '${RELEASE_ID}'"
