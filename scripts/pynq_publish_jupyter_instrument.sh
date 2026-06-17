#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYNQ_TARGET="${PYNQ_TARGET:-xilinx@192.168.100.117}"
PYNQ_JUPYTER_DIR="${PYNQ_JUPYTER_DIR:-/home/xilinx/jupyter_notebooks/t510_fengine}"

ssh "${PYNQ_TARGET}" "mkdir -p '${PYNQ_JUPYTER_DIR}'"

rsync -av --delete \
  --exclude='__pycache__/' \
  --exclude='.ipynb_checkpoints/' \
  "${REPO_ROOT}/overlay" \
  "${REPO_ROOT}/python" \
  "${REPO_ROOT}/scripts" \
  "${REPO_ROOT}/notebooks" \
  "${PYNQ_TARGET}:${PYNQ_JUPYTER_DIR}/"

cat <<EOF
Published T510 F-engine Jupyter instrument to:
  ${PYNQ_TARGET}:${PYNQ_JUPYTER_DIR}

Open from PYNQ Jupyter:
  t510_fengine/notebooks/13_astronomer_rf_observation_console.ipynb
This is the Stage 19 astronomer console with LMK/RFDC MTS recovery, DAC TX witness, and Preview-to-UDP Stability Gate advanced panels.
Previous Stage 9 entry:
  t510_fengine/notebooks/12_rf_instrument_console_v2.ipynb
Previous Stage 8 entry:
  t510_fengine/notebooks/11_dac_adc_coherent_scope_spectrum.ipynb
Previous Stage 7 entry:
  t510_fengine/notebooks/10_8lane_realtime_virtual_instrument.ipynb
Legacy Stage 5a entry:
  t510_fengine/notebooks/09_single_board_virtual_instrument.ipynb
EOF
