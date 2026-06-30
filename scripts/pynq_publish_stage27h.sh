#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYNQ_TARGET="${PYNQ_TARGET:-xilinx@192.168.100.117}"
PYNQ_BRINGUP_DIR="${PYNQ_BRINGUP_DIR:-/home/xilinx/t510_fengine_bringup}"
PYNQ_JUPYTER_DIR="${PYNQ_JUPYTER_DIR:-/home/xilinx/jupyter_notebooks/t510_fengine}"
PYNQ_SSH_OPTS="${PYNQ_SSH_OPTS:-}"
PYNQ_RSYNC_RSH="${PYNQ_RSYNC_RSH:-ssh ${PYNQ_SSH_OPTS}}"

ssh_cmd=(ssh)
if [[ -n "${PYNQ_SSH_OPTS}" ]]; then
  # shellcheck disable=SC2206
  ssh_extra_opts=(${PYNQ_SSH_OPTS})
  ssh_cmd+=("${ssh_extra_opts[@]}")
fi

"${ssh_cmd[@]}" "${PYNQ_TARGET}" "mkdir -p '${PYNQ_BRINGUP_DIR}' '${PYNQ_JUPYTER_DIR}'"

"${ssh_cmd[@]}" "${PYNQ_TARGET}" "mkdir -p '${PYNQ_BRINGUP_DIR}/scripts' '${PYNQ_BRINGUP_DIR}/notebooks'"

rsync -av --delete -e "${PYNQ_RSYNC_RSH}" \
  --exclude='__pycache__/' \
  "${REPO_ROOT}/overlay" \
  "${REPO_ROOT}/python" \
  "${PYNQ_TARGET}:${PYNQ_BRINGUP_DIR}/"

rsync -av -e "${PYNQ_RSYNC_RSH}" \
  "${REPO_ROOT}/scripts/pynq_stage27h_time_spec_fft_fullrate.py" \
  "${PYNQ_TARGET}:${PYNQ_BRINGUP_DIR}/scripts/"

rsync -av -e "${PYNQ_RSYNC_RSH}" \
  "${REPO_ROOT}/notebooks/15_stage27h_time_spec_fft_fullrate_control.ipynb" \
  "${REPO_ROOT}/notebooks/README.md" \
  "${PYNQ_TARGET}:${PYNQ_BRINGUP_DIR}/notebooks/"

"${ssh_cmd[@]}" "${PYNQ_TARGET}" "cp '${PYNQ_BRINGUP_DIR}/overlay/t510_fengine.bit' '${PYNQ_BRINGUP_DIR}/t510_fengine.bit' && cp '${PYNQ_BRINGUP_DIR}/overlay/t510_fengine.hwh' '${PYNQ_BRINGUP_DIR}/t510_fengine.hwh' 2>/dev/null || true"

"${ssh_cmd[@]}" "${PYNQ_TARGET}" "mkdir -p '${PYNQ_JUPYTER_DIR}/notebooks'"

rsync -av --delete -e "${PYNQ_RSYNC_RSH}" \
  --exclude='__pycache__/' \
  "${REPO_ROOT}/overlay" \
  "${REPO_ROOT}/python" \
  "${PYNQ_TARGET}:${PYNQ_JUPYTER_DIR}/"

rsync -av -e "${PYNQ_RSYNC_RSH}" \
  "${REPO_ROOT}/notebooks/15_stage27h_time_spec_fft_fullrate_control.ipynb" \
  "${REPO_ROOT}/notebooks/README.md" \
  "${PYNQ_TARGET}:${PYNQ_JUPYTER_DIR}/notebooks/"

"${ssh_cmd[@]}" "${PYNQ_TARGET}" "cd '${PYNQ_BRINGUP_DIR}' && sha256sum overlay/t510_fengine.bit t510_fengine.bit 2>/dev/null || sha256sum overlay/t510_fengine.bit"

cat <<EOF
Published Stage 27h T510 F-engine assets to:
  ${PYNQ_TARGET}:${PYNQ_BRINGUP_DIR}
  ${PYNQ_TARGET}:${PYNQ_JUPYTER_DIR}

If local OpenSSH global config blocks publishing, retry with:
  PYNQ_SSH_OPTS='-F /dev/null' PYNQ_TARGET=${PYNQ_TARGET} scripts/pynq_publish_stage27h.sh

Board convergence entry:
  cd ${PYNQ_BRINGUP_DIR}
  source /etc/profile.d/xrt_setup.sh
  sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_stage27h_time_spec_fft_fullrate.py --no-download --matrix converge

Jupyter production entry:
  ${PYNQ_JUPYTER_DIR}/notebooks/15_stage27h_time_spec_fft_fullrate_control.ipynb

Stage 27h production scope is intentionally narrow: TIME/SPEC science streams
plus Jupyter control/preview. This publisher only syncs the production board
validation script and the production notebook; legacy dry-run, witness, debug
FFT, and reduced SPEC tools stay in the repository as archived bring-up aids.
EOF
