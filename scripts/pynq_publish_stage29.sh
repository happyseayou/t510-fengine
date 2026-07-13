#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="${PYNQ_TARGET:-xilinx@192.168.100.117}"
BRINGUP="${PYNQ_BRINGUP_DIR:-/home/xilinx/t510_fengine}"
JUPYTER="${PYNQ_JUPYTER_DIR:-/home/xilinx/jupyter_notebooks/t510_fengine}"
SSH_OPTS="${PYNQ_SSH_OPTS:-}"
RSYNC_RSH="ssh ${SSH_OPTS}"

ssh ${SSH_OPTS} "${TARGET}" "mkdir -p '${BRINGUP}/scripts' '${JUPYTER}/notebooks'"
rsync -av --delete -e "${RSYNC_RSH}" --exclude='__pycache__/' \
  "${ROOT}/overlay" "${ROOT}/python" "${TARGET}:${BRINGUP}/"
rsync -av --delete -e "${RSYNC_RSH}" --exclude='__pycache__/' \
  "${ROOT}/overlay" "${ROOT}/python" "${TARGET}:${JUPYTER}/"
rsync -av --delete -e "${RSYNC_RSH}" --exclude='.ipynb_checkpoints/' \
  "${ROOT}/notebooks/" "${TARGET}:${JUPYTER}/notebooks/"
rsync -av -e "${RSYNC_RSH}" \
  "${ROOT}/README.md" "${TARGET}:${JUPYTER}/README.md"
rsync -av --delete --delete-excluded -e "${RSYNC_RSH}" \
  --include='stage29_board_validate.py' \
  --include='stage29_host_validate.py' \
  --include='host_stage29_rx_tune.sh' \
  --include='pynq_stage29_signal_audit.py' \
  --include='pynq_qsfp_udp_preflight_check.py' \
  --include='check_t510_packet.py' \
  --include='stage29_verify_aa100_coeffs.py' \
  --exclude='*' \
  "${ROOT}/scripts/" "${TARGET}:${BRINGUP}/scripts/"
ssh ${SSH_OPTS} "${TARGET}" \
  "rm -rf '${JUPYTER}/.ipynb_checkpoints' '${JUPYTER}/docs' '${JUPYTER}/reports' '${JUPYTER}/scripts' 2>/dev/null || true;
   find '${JUPYTER}' -maxdepth 1 -type f \( -name '*.ipynb' -o -name '*.html' \) -delete;
   rm -f '${BRINGUP}/regtest.py' '${BRINGUP}/t510_fengine.bit' '${BRINGUP}/t510_fengine.hwh' '${BRINGUP}/t510_fengine.manifest.txt' '${BRINGUP}/t510_fengine.tcl'"
ssh ${SSH_OPTS} "${TARGET}" "cd '${BRINGUP}' && sha256sum overlay/t510_fengine.bit"

printf 'Published the Stage 29 production surface to %s\n' "${TARGET}"
printf 'Jupyter: %s/notebooks/00_stage29_fengine_production_control.ipynb\n' "${JUPYTER}"
printf 'Board gate: sudo -E /usr/local/share/pynq-venv/bin/python3 %s/scripts/stage29_board_validate.py --bandwidth-mhz 100 --mode time_spec\n' "${BRINGUP}"
