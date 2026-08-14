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
PREVIOUS="${INSTALL_ROOT}/.current.previous"
RELEASES="${INSTALL_ROOT}/releases"
CONFIG="/etc/t510-agent/config.json"
CONFIG_PREVIOUS="/etc/t510-agent/.config.previous"
CATALOG="${SOURCE}/config/config.example.json"
SWAPPED=0

for target in "${CURRENT}" "${NEXT}" "${PREVIOUS}" "${RELEASES}"; do
  case "${target}" in
    /opt/t510-agent/current|/opt/t510-agent/.current.next|/opt/t510-agent/.current.previous|/opt/t510-agent/releases) ;;
    *) echo "refusing unsafe install target: ${target}" >&2; exit 1 ;;
  esac
done

test -d "${SOURCE}"
test -x "${SOURCE}/bin/t510-board-agent"
test -f "${SOURCE}/python/t510_hw.py"
test -f "${SOURCE}/python/t510_ref_watchdog.py"
test -f "${SOURCE}/python/t510_ams.py"
test -f "${CATALOG}"
test -f "${SOURCE}/deploy/t510-ref-watchdog.service"
test -f "${SOURCE}/deploy/t510-agent.service.d/center-hub.conf"
EXPECTED_SHA="$(/usr/local/share/pynq-venv/bin/python3 - "${CATALOG}" <<'PY'
import json
import sys

catalog = json.load(open(sys.argv[1], "r", encoding="utf-8"))
entry = next(item for item in catalog["bitstreams"] if item["id"] == "fengine-0x00010034")
if entry["core_version"] != "0x00010034":
    raise SystemExit("catalog has the wrong core version")
if entry["sha256"] == "0" * 64 or len(entry["sha256"]) != 64:
    raise SystemExit("catalog has not been finalized")
if min(entry["mts_adc_target_latency"], entry["mts_dac_target_latency"]) < 0:
    raise SystemExit("catalog MTS targets have not been finalized")
if entry["mts_adc_target_latency"] == 230 or entry["mts_dac_target_latency"] == 336:
    raise SystemExit("catalog reuses a forbidden retired MTS target")
campaign = entry.get("mts_campaign")
if not isinstance(campaign, dict):
    raise SystemExit("catalog MTS campaign proof is missing")
expected = {"rfdc_reset": 20, "overlay_reload": 10, "lmk_reload": 10, "passed": 40}
if campaign.get("discovery") != expected or campaign.get("fixed") != expected:
    raise SystemExit("catalog MTS campaigns are not the frozen 40/40 matrices")
if campaign.get("adc_margin") != 20 or campaign.get("dac_margin") != 16:
    raise SystemExit("catalog MTS margins are invalid")
if entry["mts_adc_target_latency"] != campaign.get("observed_adc_max", -1) + 20:
    raise SystemExit("catalog ADC MTS target is not discovery max +20")
if entry["mts_dac_target_latency"] != campaign.get("observed_dac_max", -1) + 16:
    raise SystemExit("catalog DAC MTS target is not discovery max +16")
print(entry["sha256"])
PY
)"
test "$(sha256sum "${SOURCE}/overlay/t510_fengine.bit" | awk '{print $1}')" = "${EXPECTED_SHA}"
/usr/local/share/pynq-venv/bin/python3 -c 'import pynq, sys; assert sys.version_info[:2] == (3, 10)'
test "$(df -Pk /opt | awk 'NR==2 {print $4}')" -gt 524288

rollback_install() {
  local status=$?
  trap - ERR
  systemctl stop t510-agent.service t510-ref-watchdog.service >/dev/null 2>&1 || true
  if [[ "${SWAPPED}" -eq 1 ]]; then
    rm -rf -- "${CURRENT}"
    if [[ -e "${PREVIOUS}" || -L "${PREVIOUS}" ]]; then
      mv -- "${PREVIOUS}" "${CURRENT}"
    fi
  fi
  if [[ -e "${CONFIG_PREVIOUS}" ]]; then
    mv -f -- "${CONFIG_PREVIOUS}" "${CONFIG}"
  fi
  systemctl daemon-reload >/dev/null 2>&1 || true
  systemctl start t510-ref-watchdog.service t510-agent.service >/dev/null 2>&1 || true
  exit "${status}"
}
trap rollback_install ERR

install -d -m 0755 "${INSTALL_ROOT}" /etc/t510-agent \
  /etc/systemd/system/t510-agent.service.d
rm -rf -- "${NEXT}" "${PREVIOUS}"
# The first latest-only migration may receive the legacy `current` symlink as
# SOURCE. Dereference it so the new current is always a real directory.
cp -aL "${SOURCE}" "${NEXT}"
chown -R root:root "${NEXT}"
chmod -R a-w "${NEXT}"
chmod 0555 \
  "${NEXT}/bin/t510-board-agent" \
  "${NEXT}/python/t510_hw.py" \
  "${NEXT}/python/t510_ref_watchdog.py"

rm -f -- "${CONFIG_PREVIOUS}"
if [[ -e "${CONFIG}" ]]; then
  cp -a "${CONFIG}" "${CONFIG_PREVIOUS}"
fi
systemctl stop t510-agent.service t510-ref-watchdog.service
if [[ -e "${CURRENT}" || -L "${CURRENT}" ]]; then
  mv -T -- "${CURRENT}" "${PREVIOUS}"
fi
mv -T -- "${NEXT}" "${CURRENT}"
SWAPPED=1

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
systemctl is-active --quiet t510-ref-watchdog.service
systemctl is-active --quiet t510-agent.service

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
  if curl --fail --silent --max-time 1 http://127.0.0.1:8010/health/ready >/dev/null 2>&1; then
    break
  fi
  sleep 0.25
done
curl --fail --silent --show-error --max-time 5 http://127.0.0.1:8010/health/live >/dev/null
curl --fail --silent --show-error --max-time 5 http://127.0.0.1:8010/health/ready >/dev/null
curl --fail --silent --show-error --max-time 5 http://127.0.0.1:8010/api/v2/info >/dev/null
curl --fail --silent --show-error --max-time 5 http://127.0.0.1:8010/api/v2/bitstreams >/dev/null

trap - ERR
SWAPPED=0
rm -rf -- "${PREVIOUS}" "${RELEASES}"
rm -f -- "${CONFIG_PREVIOUS}" /etc/t510-agent/config.json.pre-*
echo "Installed current Agent/watchdog without retained releases; bitstream SHA ${EXPECTED_SHA}"
