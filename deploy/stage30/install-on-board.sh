#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "install-on-board.sh must run as root" >&2
  exit 1
fi

SOURCE="${1:?usage: install-on-board.sh STAGED_RELEASE RELEASE_ID}"
RELEASE_ID="${2:?usage: install-on-board.sh STAGED_RELEASE RELEASE_ID}"
RELEASE="/opt/t510-agent/releases/${RELEASE_ID}"
EXPECTED_SHA="7486a55b6f7e50e5875474e7d85299b107e9384cfff454316f64f2d3d7e9800d"

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

if [[ ! -e /etc/t510-agent/config.json ]]; then
  install -o root -g root -m 0644 \
    "${RELEASE}/config/config.example.json" \
    /etc/t510-agent/config.json
fi
install -o root -g root -m 0644 \
  "${RELEASE}/deploy/t510-agent.service" \
  /etc/systemd/system/t510-agent.service

# Remove the superseded stateful Stage 30 units without touching Jupyter.
systemctl disable --now t510-worker.socket t510-worker.service 2>/dev/null || true
rm -f /etc/systemd/system/t510-worker.socket \
  /etc/systemd/system/t510-worker.service \
  /usr/local/sbin/t510-maintenance
rm -rf /etc/systemd/system/t510-worker.socket.d \
  /etc/systemd/system/t510-worker.service.d \
  /etc/systemd/system/t510-agent.service.d

systemctl daemon-reload
systemctl enable t510-agent.service
systemctl restart t510-agent.service
systemctl is-active --quiet t510-agent.service

# First rollout is intentionally read-only. These calls do not load an overlay
# or change the current science stream.
for _attempt in $(seq 1 40); do
  if curl --fail --silent --max-time 1 http://127.0.0.1:8010/health/live >/dev/null 2>&1; then
    break
  fi
  sleep 0.25
done
curl --fail --silent --show-error --max-time 5 http://127.0.0.1:8010/health/live >/dev/null
curl --fail --silent --show-error --max-time 5 http://127.0.0.1:8010/health/ready >/dev/null
curl --fail --silent --show-error --max-time 5 http://127.0.0.1:8010/api/v1/info >/dev/null
curl --fail --silent --show-error --max-time 15 http://127.0.0.1:8010/api/v1/status >/dev/null

echo "Installed stateless Stage 30 release ${RELEASE_ID}; Jupyter was not changed"
