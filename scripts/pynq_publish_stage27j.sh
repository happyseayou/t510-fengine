#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYNQ_TARGET="${PYNQ_TARGET:-xilinx@192.168.100.117}"
PYNQ_BRINGUP_DIR="${PYNQ_BRINGUP_DIR:-/home/xilinx/t510_fengine_bringup}"
PYNQ_SSH_OPTS="${PYNQ_SSH_OPTS:-}"
PYNQ_RSYNC_RSH="${PYNQ_RSYNC_RSH:-ssh ${PYNQ_SSH_OPTS}}"

"${REPO_ROOT}/scripts/pynq_publish_stage27h.sh"

rsync -av -e "${PYNQ_RSYNC_RSH}" \
  "${REPO_ROOT}/scripts/pynq_stage27j_time_spec_pfb.py" \
  "${REPO_ROOT}/scripts/host_stage27j_rust_rx_validate.py" \
  "${PYNQ_TARGET}:${PYNQ_BRINGUP_DIR}/scripts/"

cat <<EOF
Published Stage 27j PFB validation entries to:
  ${PYNQ_TARGET}:${PYNQ_BRINGUP_DIR}

Board 27j gate:
  cd ${PYNQ_BRINGUP_DIR}
  source /etc/profile.d/xrt_setup.sh
  sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_stage27j_time_spec_pfb.py

PFB spectral + AA100 gate:
  sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_stage27i_antialias_spur_acceptance.py --stage27j-pfb

Host 27j gate:
  scripts/host_stage27j_rust_rx_validate.py
EOF
