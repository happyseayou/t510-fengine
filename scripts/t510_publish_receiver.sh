#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="${T510_RX_TARGET:-astrolab@192.168.100.162}"
SSH_OPTS="${T510_RX_SSH_OPTS:-}"
MODE="${1:---build-only}"
STAGE="${ROOT}/build/receiver/latest"
REMOTE_STAGE="/home/astrolab/.cache/t510/latest"
RELEASE_FILES=(
  t510_time_rx
  host_t510_rx_tune.sh
  t510_host_validate.py
  t510-time-rx.service
  t510-rx-tune.service
  90-t510-rx.conf
  install-receiver.sh
  SHA256SUMS
)

case "${MODE}" in
  --build-only|--install) ;;
  *) echo "usage: t510_publish_receiver.sh [--build-only|--install]" >&2; exit 2 ;;
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

case "${STAGE}" in
  "${ROOT}/build/receiver/latest") ;;
  *) echo "refusing unsafe local stage path: ${STAGE}" >&2; exit 1 ;;
esac
install -d "${STAGE}"
# Campaign PCAPs and reports live below latest/evidence and must survive a
# receiver binary refresh.  Replace only release artifacts in the fixed latest
# tree; never erase long-task evidence while deploying a capture-side fix.
find "${STAGE}" -mindepth 1 -maxdepth 1 ! -name evidence -exec rm -rf -- {} +
install -m 0755 "${ROOT}/rust/t510_time_rx/target/aarch64-unknown-linux-musl/release/t510_time_rx" "${STAGE}/t510_time_rx"
install -m 0755 "${ROOT}/scripts/host_t510_rx_tune.sh" "${STAGE}/host_t510_rx_tune.sh"
install -m 0755 "${ROOT}/scripts/t510_host_validate.py" "${STAGE}/t510_host_validate.py"
install -m 0644 "${ROOT}/deploy/t510/t510-time-rx.service" "${STAGE}/t510-time-rx.service"
install -m 0644 "${ROOT}/deploy/t510/t510-rx-tune.service" "${STAGE}/t510-rx-tune.service"
install -m 0644 "${ROOT}/deploy/t510/90-t510-rx.conf" "${STAGE}/90-t510-rx.conf"
install -m 0755 "${ROOT}/deploy/t510/install-receiver.sh" "${STAGE}/install-receiver.sh"
(cd "${STAGE}" && sha256sum t510_time_rx host_t510_rx_tune.sh t510_host_validate.py t510-time-rx.service t510-rx-tune.service 90-t510-rx.conf install-receiver.sh > SHA256SUMS)

file "${STAGE}/t510_time_rx" | grep -q 'ARM aarch64'
if readelf -l "${STAGE}/t510_time_rx" | grep -q 'Requesting program interpreter'; then
  echo "receiver binary is dynamically linked; expected static musl" >&2
  exit 1
fi

if [[ "${MODE}" == "--build-only" ]]; then
  echo "Built current receiver release at ${STAGE}"
  exit 0
fi

ssh ${SSH_OPTS} "${TARGET}" "rm -rf -- '${REMOTE_STAGE}' && mkdir -p '${REMOTE_STAGE}'"
release_paths=()
for file in "${RELEASE_FILES[@]}"; do
  release_paths+=("${STAGE}/${file}")
done
# build/receiver/latest/evidence contains multi-gigabyte campaign PCAPs.  It is
# intentionally local evidence, not a receiver release artifact.
rsync -a -e "ssh ${SSH_OPTS}" "${release_paths[@]}" "${TARGET}:${REMOTE_STAGE}/"
remote_install="bash '${REMOTE_STAGE}/install-receiver.sh' '${REMOTE_STAGE}'"
if [[ -n "${T510_RX_SUDO_PASSWORD:-}" ]]; then
  printf '%s\n' "${T510_RX_SUDO_PASSWORD}" | ssh ${SSH_OPTS} "${TARGET}" "sudo -S ${remote_install}"
else
  ssh -t ${SSH_OPTS} "${TARGET}" "sudo ${remote_install}"
fi
ssh ${SSH_OPTS} "${TARGET}" "rm -rf -- '${REMOTE_STAGE}'"
curl --fail --silent --show-error --max-time 10 "http://${TARGET#*@}:8089/api/state" >/dev/null
echo "Installed current receiver release"
