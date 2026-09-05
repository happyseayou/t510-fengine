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

for target in "${CURRENT}" "${NEXT}"; do
  case "${target}" in
    /opt/t510-time-rx/current|/opt/t510-time-rx/.current.next) ;;
    *) echo "refusing unsafe install target: ${target}" >&2; exit 1 ;;
  esac
done

test -d "${SOURCE}"
test -x "${SOURCE}/t510_time_rx"
test -x "${SOURCE}/t510_xcorr_cuda"
test -x "${SOURCE}/host_t510_rx_tune.sh"
test -x "${SOURCE}/t510_host_validate.py"
test -f "${SOURCE}/SHA256SUMS"
(cd "${SOURCE}" && sha256sum -c SHA256SUMS)

fail_install() {
  local status=$?
  trap - ERR
  systemctl stop t510-time-rx.service >/dev/null 2>&1 || true
  rm -rf -- "${NEXT}"
  systemctl daemon-reload >/dev/null 2>&1 || true
  echo "Current receiver install failed; new state retained for fix-forward repair" >&2
  exit "${status}"
}
trap fail_install ERR

install -d -m 0755 "${INSTALL_ROOT}"
# New measurements use the neutral root. The historical Stage 35 tree remains
# untouched for the read-only report served on port 8035.
install -d -o astrolab -g astrolab -m 0750 \
  /var/lib/t510 /var/lib/t510/measurements /var/lib/t510/stage35
rm -rf -- "${NEXT}" "${INSTALL_ROOT}/.current.previous" "${INSTALL_ROOT}/releases"
# The first latest-only migration may receive the legacy `current` symlink as
# SOURCE. Dereference it so the new current is always a real directory.
cp -aL "${SOURCE}" "${NEXT}"
chown -R root:root "${NEXT}"
chmod -R a-w "${NEXT}"
chmod 0555 \
  "${NEXT}/t510_time_rx" \
  "${NEXT}/t510_xcorr_cuda" \
  "${NEXT}/host_t510_rx_tune.sh" \
  "${NEXT}/t510_host_validate.py"

systemctl stop t510-time-rx.service
rm -rf -- "${CURRENT}"
mv -T -- "${NEXT}" "${CURRENT}"

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
rm -rf -- "${INSTALL_ROOT}/.current.previous" "${INSTALL_ROOT}/releases"
echo "Installed current receiver without retained releases"
