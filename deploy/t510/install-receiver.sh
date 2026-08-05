#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "install-receiver.sh must run as root" >&2
  exit 1
fi

SOURCE="${1:?usage: install-receiver.sh STAGED_CURRENT}"
if [[ "$#" -ne 1 ]]; then
  echo "usage: install-receiver.sh STAGED_CURRENT" >&2
  exit 2
fi

INSTALL_ROOT="/opt/t510-time-rx"
CURRENT="${INSTALL_ROOT}/current"
NEXT="${INSTALL_ROOT}/.current.next"
PREVIOUS="${INSTALL_ROOT}/.current.previous"
RELEASES="${INSTALL_ROOT}/releases"
SWAPPED=0

for target in "${CURRENT}" "${NEXT}" "${PREVIOUS}" "${RELEASES}"; do
  case "${target}" in
    /opt/t510-time-rx/current|/opt/t510-time-rx/.current.next|/opt/t510-time-rx/.current.previous|/opt/t510-time-rx/releases) ;;
    *) echo "refusing unsafe install target: ${target}" >&2; exit 1 ;;
  esac
done

test -d "${SOURCE}"
test -x "${SOURCE}/t510_time_rx"
test -x "${SOURCE}/host_t510_rx_tune.sh"
test -x "${SOURCE}/t510_host_validate.py"
test -f "${SOURCE}/SHA256SUMS"
(cd "${SOURCE}" && sha256sum -c SHA256SUMS)

rollback_install() {
  local status=$?
  trap - ERR
  systemctl stop t510-time-rx.service >/dev/null 2>&1 || true
  if [[ "${SWAPPED}" -eq 1 ]]; then
    rm -rf -- "${CURRENT}"
    if [[ -e "${PREVIOUS}" || -L "${PREVIOUS}" ]]; then
      mv -- "${PREVIOUS}" "${CURRENT}"
    fi
  fi
  systemctl daemon-reload >/dev/null 2>&1 || true
  systemctl start t510-rx-tune.service t510-time-rx.service >/dev/null 2>&1 || true
  exit "${status}"
}
trap rollback_install ERR

install -d -m 0755 "${INSTALL_ROOT}"
rm -rf -- "${NEXT}" "${PREVIOUS}"
# The first latest-only migration may receive the legacy `current` symlink as
# SOURCE. Dereference it so the new current is always a real directory.
cp -aL "${SOURCE}" "${NEXT}"
chown -R root:root "${NEXT}"
chmod -R a-w "${NEXT}"
chmod 0555 \
  "${NEXT}/t510_time_rx" \
  "${NEXT}/host_t510_rx_tune.sh" \
  "${NEXT}/t510_host_validate.py"

systemctl stop t510-time-rx.service
if [[ -e "${CURRENT}" || -L "${CURRENT}" ]]; then
  mv -T -- "${CURRENT}" "${PREVIOUS}"
fi
mv -T -- "${NEXT}" "${CURRENT}"
SWAPPED=1

install -o root -g root -m 0644 "${CURRENT}/90-t510-rx.conf" /etc/sysctl.d/90-t510-rx.conf
install -o root -g root -m 0644 "${CURRENT}/t510-rx-tune.service" /etc/systemd/system/t510-rx-tune.service
install -o root -g root -m 0644 "${CURRENT}/t510-time-rx.service" /etc/systemd/system/t510-time-rx.service

systemctl daemon-reload
systemctl enable t510-rx-tune.service t510-time-rx.service
systemctl restart t510-rx-tune.service
systemctl start t510-time-rx.service
systemctl is-active --quiet t510-rx-tune.service
systemctl is-active --quiet t510-time-rx.service

for _attempt in $(seq 1 40); do
  if curl --fail --silent --max-time 1 http://127.0.0.1:8089/api/state >/dev/null 2>&1; then
    break
  fi
  sleep 0.25
done
curl --fail --silent --show-error --max-time 5 http://127.0.0.1:8089/api/state >/dev/null

trap - ERR
SWAPPED=0
rm -rf -- "${PREVIOUS}" "${RELEASES}"
echo "Installed current receiver without retained releases"
