#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYNQ_TARGET="${PYNQ_TARGET:-xilinx@192.168.100.117}"
PYNQ_BRINGUP_DIR="${PYNQ_BRINGUP_DIR:-/home/xilinx/t510_fengine_bringup}"
PYNQ_SSH_OPTS="${PYNQ_SSH_OPTS:-}"
PYNQ_RSYNC_RSH="${PYNQ_RSYNC_RSH:-ssh ${PYNQ_SSH_OPTS}}"

"${REPO_ROOT}/scripts/pynq_publish_stage27j.sh"

rsync -av -e "${PYNQ_RSYNC_RSH}" \
  "${REPO_ROOT}/scripts/pynq_stage28_fullrate.py" \
  "${REPO_ROOT}/scripts/host_stage28_rust_rx_validate.py" \
  "${PYNQ_TARGET}:${PYNQ_BRINGUP_DIR}/scripts/"

cat <<EOF
Published Stage 28 full-rate validation entries to:
  ${PYNQ_TARGET}:${PYNQ_BRINGUP_DIR}

Board gate (fresh download is the default):
  sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_stage28_fullrate.py --bandwidth-mhz 100 --mode time_spec
  sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_stage28_fullrate.py --bandwidth-mhz 200 --mode time_only
  sudo -E /usr/local/share/pynq-venv/bin/python3 scripts/pynq_stage28_fullrate.py --bandwidth-mhz 200 --mode spec_only

Host gate (run against a mode-sized Rust receiver):
  scripts/host_stage28_rust_rx_validate.py --bandwidth-mhz 100 --mode time_spec
  scripts/host_stage28_rust_rx_validate.py --bandwidth-mhz 200 --mode time_only
  scripts/host_stage28_rust_rx_validate.py --bandwidth-mhz 200 --mode spec_only
EOF
