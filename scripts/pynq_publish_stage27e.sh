#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYNQ_TARGET="${PYNQ_TARGET:-xilinx@192.168.100.117}"
PYNQ_BRINGUP_DIR="${PYNQ_BRINGUP_DIR:-/home/xilinx/t510_fengine_bringup}"
PYNQ_JUPYTER_DIR="${PYNQ_JUPYTER_DIR:-/home/xilinx/jupyter_notebooks/t510_fengine}"

ssh "${PYNQ_TARGET}" "mkdir -p '${PYNQ_BRINGUP_DIR}' '${PYNQ_JUPYTER_DIR}'"

rsync -av \
  --exclude='__pycache__/' \
  --exclude='.ipynb_checkpoints/' \
  "${REPO_ROOT}/overlay" \
  "${REPO_ROOT}/python" \
  "${REPO_ROOT}/scripts" \
  "${REPO_ROOT}/notebooks" \
  "${REPO_ROOT}/docs" \
  "${PYNQ_TARGET}:${PYNQ_BRINGUP_DIR}/"

ssh "${PYNQ_TARGET}" "cp '${PYNQ_BRINGUP_DIR}/overlay/t510_fengine.bit' '${PYNQ_BRINGUP_DIR}/t510_fengine.bit' && cp '${PYNQ_BRINGUP_DIR}/overlay/t510_fengine.hwh' '${PYNQ_BRINGUP_DIR}/t510_fengine.hwh' 2>/dev/null || true"

rsync -av --delete \
  --exclude='__pycache__/' \
  --exclude='.ipynb_checkpoints/' \
  "${REPO_ROOT}/overlay" \
  "${REPO_ROOT}/python" \
  "${REPO_ROOT}/scripts" \
  "${REPO_ROOT}/notebooks" \
  "${REPO_ROOT}/docs" \
  "${PYNQ_TARGET}:${PYNQ_JUPYTER_DIR}/"

ssh "${PYNQ_TARGET}" "cd '${PYNQ_BRINGUP_DIR}' && sha256sum overlay/t510_fengine.bit t510_fengine.bit 2>/dev/null || sha256sum overlay/t510_fengine.bit"

cat <<EOF
Published Stage 27e T510 F-engine assets to:
  ${PYNQ_TARGET}:${PYNQ_BRINGUP_DIR}
  ${PYNQ_TARGET}:${PYNQ_JUPYTER_DIR}

Board bring-up entry:
  cd ${PYNQ_BRINGUP_DIR}
  source /etc/profile.d/xrt_setup.sh
  sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_stage27e_science_live_bringup.py --no-download --matrix smoke
EOF
