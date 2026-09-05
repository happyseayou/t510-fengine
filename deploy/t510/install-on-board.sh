#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "install-on-board.sh must run as root" >&2
  exit 1
fi

SOURCE="${1:?usage: install-on-board.sh STAGED_CURRENT}"
if [[ "$#" -ne 1 ]]; then
  echo "usage: install-on-board.sh STAGED_CURRENT" >&2
  exit 2
fi

INSTALL_ROOT="/opt/t510-agent"
CURRENT="${INSTALL_ROOT}/current"
NEXT="${INSTALL_ROOT}/.current.next"
CONFIG="/etc/t510-agent/config.json"
CATALOG="${SOURCE}/config/config.example.json"
METADATA="${SOURCE}/config/current_release.json"

for target in "${CURRENT}" "${NEXT}"; do
  case "${target}" in
    /opt/t510-agent/current|/opt/t510-agent/.current.next) ;;
    *) echo "refusing unsafe install target: ${target}" >&2; exit 1 ;;
  esac
done

test -d "${SOURCE}"
test -x "${SOURCE}/bin/t510-board-agent"
test -f "${SOURCE}/python/t510_hw.py"
test -f "${SOURCE}/python/t510_ref_watchdog.py"
test -f "${SOURCE}/python/t510_ams.py"
test -f "${CATALOG}"
test -f "${METADATA}"
test -x "${SOURCE}/scripts/t510_current_release.py"
test -f "${SOURCE}/deploy/t510-ref-watchdog.service"
test -f "${SOURCE}/deploy/t510-agent.service.d/center-hub.conf"
EXPECTED_SHA="$(/usr/local/share/pynq-venv/bin/python3 -c \
  'import json,sys; print(json.load(open(sys.argv[1]))["bitstream_sha256"])' "${METADATA}")"
/usr/local/share/pynq-venv/bin/python3 "${SOURCE}/scripts/t510_current_release.py" \
  --metadata "${METADATA}" --catalog "${CATALOG}" \
  --bitstream "${SOURCE}/overlay/t510_fengine.bit" --require-reference onboard_tcxo >/dev/null
/usr/local/share/pynq-venv/bin/python3 -c 'import pynq, sys; assert sys.version_info[:2] == (3, 10)'
test "$(df -Pk /opt | awk 'NR==2 {print $4}')" -gt 524288

fail_install() {
  local status=$?
  trap - ERR
  systemctl stop t510-agent.service t510-ref-watchdog.service >/dev/null 2>&1 || true
  rm -rf -- "${NEXT}"
  systemctl daemon-reload >/dev/null 2>&1 || true
  echo "Current release install failed; new state retained for fix-forward repair" >&2
  exit "${status}"
}
trap fail_install ERR

install -d -m 0755 "${INSTALL_ROOT}" /etc/t510-agent \
  /etc/systemd/system/t510-agent.service.d
install -d -o root -g root -m 0700 /var/lib/t510
rm -rf -- "${NEXT}" "${INSTALL_ROOT}/.current.previous" "${INSTALL_ROOT}/releases"
# The first latest-only migration may receive the legacy `current` symlink as
# SOURCE. Dereference it so the new current is always a real directory.
cp -aL "${SOURCE}" "${NEXT}"
chown -R root:root "${NEXT}"
chmod -R a-w "${NEXT}"
chmod 0555 \
  "${NEXT}/bin/t510-board-agent" \
  "${NEXT}/python/t510_hw.py" \
  "${NEXT}/python/t510_ref_watchdog.py"

systemctl stop t510-agent.service t510-ref-watchdog.service
rm -rf -- "${CURRENT}"
mv -T -- "${NEXT}" "${CURRENT}"

install -o root -g root -m 0644 \
  "${CURRENT}/config/config.example.json" "${CONFIG}"
install -o root -g root -m 0644 \
  "${CURRENT}/deploy/t510-agent.service" \
  /etc/systemd/system/t510-agent.service
install -o root -g root -m 0644 \
  "${CURRENT}/deploy/t510-ref-watchdog.service" \
  /etc/systemd/system/t510-ref-watchdog.service
install -o root -g root -m 0644 \
  "${CURRENT}/deploy/t510-agent.service.d/center-hub.conf" \
  /etc/systemd/system/t510-agent.service.d/center-hub.conf

# PYNQ stores the absolute bitfile path in its global PL state. Preserve the
# active design without a new FPGA download when the content hash matches the
# newly installed current bit; otherwise clear the stale path fail-closed.
/usr/local/share/pynq-venv/bin/python3 - \
  /home/xilinx/pynq/pl_server/global_pl_state.json \
  "${CURRENT}/overlay/t510_fengine.bit" <<'PY'
import hashlib
import json
import os
import sys
from pathlib import Path

state_path = Path(sys.argv[1])
bit_path = Path(sys.argv[2])
if state_path.exists():
    state = json.loads(state_path.read_text(encoding="utf-8"))
    digest = hashlib.sha1(bit_path.read_bytes()).hexdigest()
    if state.get("bitfile_hash") == digest:
        state["bitfile_name"] = str(bit_path)
        temporary = state_path.with_suffix(state_path.suffix + ".tmp")
        temporary.write_text(json.dumps(state, separators=(",", ":")), encoding="utf-8")
        os.chmod(temporary, 0o644)
        temporary.replace(state_path)
    else:
        state_path.unlink()
PY

systemctl daemon-reload
systemctl enable t510-ref-watchdog.service t510-agent.service
systemctl start t510-ref-watchdog.service t510-agent.service

WATCHDOG_STATE="/run/t510-ref-watchdog.json"
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

for _attempt in $(seq 1 40); do
  agent_state="$(systemctl is-active t510-agent.service 2>/dev/null || true)"
  agent_pid="$(systemctl show t510-agent.service --property MainPID --value)"
  agent_exe=""
  if [[ "${agent_pid}" =~ ^[1-9][0-9]*$ ]]; then
    agent_exe="$(readlink -f "/proc/${agent_pid}/exe" 2>/dev/null || true)"
  fi
  if [[ "${agent_state}" == "active" ]] &&
    [[ "${agent_exe}" == "${CURRENT}/bin/t510-board-agent" ]] &&
    curl --fail --silent --max-time 1 http://127.0.0.1:8010/health/ready >/dev/null 2>&1
  then
    break
  fi
  sleep 0.25
done
test "$(systemctl is-active t510-ref-watchdog.service)" = "active"
test "$(systemctl is-active t510-agent.service)" = "active"
test "${agent_exe}" = "${CURRENT}/bin/t510-board-agent"
curl --fail --silent --show-error --max-time 5 http://127.0.0.1:8010/health/live >/dev/null
curl --fail --silent --show-error --max-time 5 http://127.0.0.1:8010/health/ready >/dev/null
curl --fail --silent --show-error --max-time 5 http://127.0.0.1:8010/api/v2/info >/dev/null
curl --fail --silent --show-error --max-time 5 http://127.0.0.1:8010/api/v2/bitstreams |
  /usr/local/share/pynq-venv/bin/python3 -c '
import json
import sys

result = json.load(sys.stdin)["result"]
entries = result.get("bitstreams", [])
assert result.get("default_bitstream_id") == "fengine-current"
assert len(entries) == 1 and entries[0].get("id") == "fengine-current"
assert entries[0].get("mts_qualifications", {}).get("onboard_tcxo", {}).get("status") == "qualified"
'

trap - ERR
rm -rf -- "${INSTALL_ROOT}/.current.previous" "${INSTALL_ROOT}/releases"
rm -f -- /etc/t510-agent/.config.previous /etc/t510-agent/config.json.pre-*
echo "Installed current Agent/watchdog without retained releases; bitstream SHA ${EXPECTED_SHA}"
