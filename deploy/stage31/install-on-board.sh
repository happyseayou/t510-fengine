#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "install-on-board.sh must run as root" >&2
  exit 1
fi

SOURCE="${1:?usage: install-on-board.sh STAGED_RELEASE RELEASE_ID}"
RELEASE_ID="${2:?usage: install-on-board.sh STAGED_RELEASE RELEASE_ID}"
RELEASE="/opt/t510-agent/releases/${RELEASE_ID}"
EXPECTED_SHA="3696845d30dc471f572904b7039aa231bc766a21be05de7796d53704f8d08eec"

test -d "${SOURCE}"
test -x "${SOURCE}/bin/t510-board-agent"
test -f "${SOURCE}/python/t510_hw.py"
test -f "${SOURCE}/config/config.example.json"
test "$(sha256sum "${SOURCE}/overlay/t510_fengine.bit" | awk '{print $1}')" = "${EXPECTED_SHA}"
/usr/local/share/pynq-venv/bin/python3 -c 'import pynq, sys; assert sys.version_info[:2] == (3, 10)'
test "$(df -Pk /opt | awk 'NR==2 {print $4}')" -gt 524288

install -d -m 0755 /opt/t510-agent/releases /etc/t510-agent
if [[ ! -e "${RELEASE}" ]]; then
  cp -a "${SOURCE}" "${RELEASE}"
fi
chown -R root:root "${RELEASE}"
chmod -R a-w "${RELEASE}"
chmod 0555 "${RELEASE}/bin/t510-board-agent" "${RELEASE}/python/t510_hw.py"
ln -sfn "${RELEASE}" /opt/t510-agent/current

if [[ -e /etc/t510-agent/config.json ]]; then
  cp -a /etc/t510-agent/config.json "/etc/t510-agent/config.json.pre-${RELEASE_ID}"
fi
install -o root -g root -m 0644 \
  "${RELEASE}/config/config.example.json" \
  /etc/t510-agent/config.json
install -o root -g root -m 0644 \
  "${RELEASE}/deploy/t510-agent.service" \
  /etc/systemd/system/t510-agent.service

systemctl daemon-reload
systemctl enable t510-agent.service
systemctl restart t510-agent.service
systemctl is-active --quiet t510-agent.service

for _attempt in $(seq 1 40); do
  if curl --fail --silent --max-time 1 http://127.0.0.1:8010/health/live >/dev/null 2>&1; then
    break
  fi
  sleep 0.25
done
curl --fail --silent --show-error --max-time 5 http://127.0.0.1:8010/health/live >/dev/null
curl --fail --silent --show-error --max-time 5 http://127.0.0.1:8010/health/ready >/dev/null
curl --fail --silent --show-error --max-time 5 http://127.0.0.1:8010/api/v1/info >/dev/null
curl --fail --silent --show-error --max-time 5 http://127.0.0.1:8010/api/v1/bitstreams >/dev/null

echo "Installed Stage 31 Agent release ${RELEASE_ID}; FPGA download is intentionally separate"
