#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYNQ_TARGET="${PYNQ_TARGET:-xilinx@192.168.100.117}"
PYNQ_BRINGUP_DIR="${PYNQ_BRINGUP_DIR:-/home/xilinx/t510_fengine_bringup}"
PYNQ_JUPYTER_DIR="${PYNQ_JUPYTER_DIR:-/home/xilinx/jupyter_notebooks/t510_fengine}"

ssh "${PYNQ_TARGET}" "mkdir -p '${PYNQ_BRINGUP_DIR}' '${PYNQ_JUPYTER_DIR}'"

ssh "${PYNQ_TARGET}" "mkdir -p '${PYNQ_BRINGUP_DIR}/scripts' '${PYNQ_BRINGUP_DIR}/notebooks'"

rsync -av --delete \
  --exclude='__pycache__/' \
  "${REPO_ROOT}/overlay" \
  "${REPO_ROOT}/python" \
  "${PYNQ_TARGET}:${PYNQ_BRINGUP_DIR}/"

rsync -av \
  "${REPO_ROOT}/scripts/pynq_stage27g_time_spec_convergence.py" \
  "${PYNQ_TARGET}:${PYNQ_BRINGUP_DIR}/scripts/"

rsync -av \
  "${REPO_ROOT}/notebooks/14_stage27g_time_spec_fengine_control.ipynb" \
  "${REPO_ROOT}/notebooks/README.md" \
  "${PYNQ_TARGET}:${PYNQ_BRINGUP_DIR}/notebooks/"

ssh "${PYNQ_TARGET}" "cp '${PYNQ_BRINGUP_DIR}/overlay/t510_fengine.bit' '${PYNQ_BRINGUP_DIR}/t510_fengine.bit' && cp '${PYNQ_BRINGUP_DIR}/overlay/t510_fengine.hwh' '${PYNQ_BRINGUP_DIR}/t510_fengine.hwh' 2>/dev/null || true"

ssh "${PYNQ_TARGET}" "mkdir -p '${PYNQ_JUPYTER_DIR}/notebooks'"

rsync -av --delete \
  --exclude='__pycache__/' \
  "${REPO_ROOT}/overlay" \
  "${REPO_ROOT}/python" \
  "${PYNQ_TARGET}:${PYNQ_JUPYTER_DIR}/"

rsync -av \
  "${REPO_ROOT}/notebooks/14_stage27g_time_spec_fengine_control.ipynb" \
  "${REPO_ROOT}/notebooks/README.md" \
  "${PYNQ_TARGET}:${PYNQ_JUPYTER_DIR}/notebooks/"

ssh "${PYNQ_TARGET}" "cd '${PYNQ_BRINGUP_DIR}' && sha256sum overlay/t510_fengine.bit t510_fengine.bit 2>/dev/null || sha256sum overlay/t510_fengine.bit"

cat <<EOF
Published Stage 27g T510 F-engine assets to:
  ${PYNQ_TARGET}:${PYNQ_BRINGUP_DIR}
  ${PYNQ_TARGET}:${PYNQ_JUPYTER_DIR}

Board convergence entry:
  cd ${PYNQ_BRINGUP_DIR}
  source /etc/profile.d/xrt_setup.sh
  sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_stage27g_time_spec_convergence.py --no-download --matrix converge

Jupyter production entry:
  ${PYNQ_JUPYTER_DIR}/notebooks/14_stage27g_time_spec_fengine_control.ipynb

Stage 27g production scope is intentionally narrow: TIME/SPEC science streams
plus Jupyter control/preview. This publisher only syncs the production board
validation script and the production notebook; legacy dry-run, witness, debug
FFT, and reduced SPEC tools stay in the repository as archived bring-up aids.
EOF
