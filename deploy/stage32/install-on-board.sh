#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "install-on-board.sh must run as root" >&2
  exit 1
fi

SOURCE="${1:?usage: install-on-board.sh STAGED_RELEASE RELEASE_ID}"
RELEASE_ID="${2:?usage: install-on-board.sh STAGED_RELEASE RELEASE_ID}"
RELEASE="/opt/t510-agent/releases/${RELEASE_ID}"
EXPECTED_SHA="47117c9e656cfd8345125ef0130eb91a5ec0868cef59931b40b957da29f31234"

test -d "${SOURCE}"
test -x "${SOURCE}/bin/t510-board-agent"
test -f "${SOURCE}/python/t510_hw.py"
test -f "${SOURCE}/python/t510_ref_watchdog.py"
test -f "${SOURCE}/config/config.example.json"
test -f "${SOURCE}/deploy/t510-ref-watchdog.service"
test -f "${SOURCE}/deploy/t510-agent.service.d/center-hub.conf"
test "$(sha256sum "${SOURCE}/overlay/t510_fengine.bit" | awk '{print $1}')" = "${EXPECTED_SHA}"
/usr/local/share/pynq-venv/bin/python3 -c 'import pynq, sys; assert sys.version_info[:2] == (3, 10)'
test "$(df -Pk /opt | awk 'NR==2 {print $4}')" -gt 524288

install -d -m 0755 /opt/t510-agent/releases /etc/t510-agent \
  /etc/systemd/system/t510-agent.service.d
if [[ ! -e "${RELEASE}" ]]; then
  cp -a "${SOURCE}" "${RELEASE}"
fi
chown -R root:root "${RELEASE}"
chmod -R a-w "${RELEASE}"
chmod 0555 \
  "${RELEASE}/bin/t510-board-agent" \
  "${RELEASE}/python/t510_hw.py" \
  "${RELEASE}/python/t510_ref_watchdog.py"
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
install -o root -g root -m 0644 \
  "${RELEASE}/deploy/t510-ref-watchdog.service" \
  /etc/systemd/system/t510-ref-watchdog.service
install -o root -g root -m 0644 \
  "${RELEASE}/deploy/t510-agent.service.d/center-hub.conf" \
  /etc/systemd/system/t510-agent.service.d/center-hub.conf

systemctl daemon-reload
systemctl enable t510-ref-watchdog.service t510-agent.service
systemctl restart t510-ref-watchdog.service
systemctl restart t510-agent.service
systemctl is-active --quiet t510-ref-watchdog.service
systemctl is-active --quiet t510-agent.service

WATCHDOG_STATE="/run/t510-stage32-ref-watchdog.json"
for _attempt in $(seq 1 80); do
  if test -s "${WATCHDOG_STATE}" &&
    /usr/local/share/pynq-venv/bin/python3 - "${WATCHDOG_STATE}" <<'PY'
import json
import sys
import time

state = json.load(open(sys.argv[1], "r", encoding="utf-8"))
age_ms = int(time.time() * 1000) - int(state.get("updated_at_unix_ms", 0))
if state.get("schema_version") != 1 or age_ms < 0 or age_ms > 1500:
    raise SystemExit(1)
PY
  then
    break
  fi
  sleep 0.25
done
/usr/local/share/pynq-venv/bin/python3 - "${WATCHDOG_STATE}" <<'PY'
import json
import sys
import time

state = json.load(open(sys.argv[1], "r", encoding="utf-8"))
age_ms = int(time.time() * 1000) - int(state.get("updated_at_unix_ms", 0))
if state.get("schema_version") != 1 or age_ms < 0 or age_ms > 1500:
    raise SystemExit("watchdog state is unavailable or stale after service restart")
PY

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

echo "Installed Stage 32 Agent/watchdog release ${RELEASE_ID}; FPGA download remains a separate configure action"
