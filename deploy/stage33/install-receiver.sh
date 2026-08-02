#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "install-receiver.sh must run as root" >&2
  exit 1
fi

SOURCE="${1:?usage: install-receiver.sh STAGED_RELEASE RELEASE_ID}"
RELEASE_ID="${2:?usage: install-receiver.sh STAGED_RELEASE RELEASE_ID}"
RELEASE="/opt/t510-time-rx/releases/${RELEASE_ID}"

test -d "${SOURCE}"
test -x "${SOURCE}/t510_time_rx"
test -x "${SOURCE}/host_t510_rx_tune.sh"
test -x "${SOURCE}/t510_host_validate.py"
test -f "${SOURCE}/SHA256SUMS"
(cd "${SOURCE}" && sha256sum -c SHA256SUMS)

install -d -m 0755 /opt/t510-time-rx/releases
if [[ ! -e "${RELEASE}" ]]; then
  cp -a "${SOURCE}" "${RELEASE}"
fi
chown -R root:root "${RELEASE}"
chmod -R a-w "${RELEASE}"
chmod 0555 \
  "${RELEASE}/t510_time_rx" \
  "${RELEASE}/host_t510_rx_tune.sh" \
  "${RELEASE}/t510_host_validate.py"
ln -sfn "${RELEASE}" /opt/t510-time-rx/current

install -o root -g root -m 0644 "${RELEASE}/90-t510-rx.conf" /etc/sysctl.d/90-t510-rx.conf
install -o root -g root -m 0644 "${RELEASE}/t510-rx-tune.service" /etc/systemd/system/t510-rx-tune.service
install -o root -g root -m 0644 "${RELEASE}/t510-time-rx.service" /etc/systemd/system/t510-time-rx.service

systemctl daemon-reload
systemctl enable t510-rx-tune.service t510-time-rx.service
systemctl restart t510-rx-tune.service
systemctl restart t510-time-rx.service
systemctl is-active --quiet t510-rx-tune.service
systemctl is-active --quiet t510-time-rx.service

for _attempt in $(seq 1 40); do
  if curl --fail --silent --max-time 1 http://127.0.0.1:8089/api/state >/dev/null 2>&1; then
    break
  fi
  sleep 0.25
done
curl --fail --silent --show-error --max-time 5 http://127.0.0.1:8089/api/state >/dev/null

echo "Installed Stage 33 receiver release ${RELEASE_ID}"
