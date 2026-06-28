#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYNQ_TARGET="${PYNQ_TARGET:-xilinx@192.168.100.117}"
PYNQ_JUPYTER_DIR="${PYNQ_JUPYTER_DIR:-/home/xilinx/jupyter_notebooks/t510_fengine}"

ssh "${PYNQ_TARGET}" "mkdir -p '${PYNQ_JUPYTER_DIR}'"

ssh "${PYNQ_TARGET}" "mkdir -p '${PYNQ_JUPYTER_DIR}/notebooks'"

rsync -av --delete \
  --exclude='__pycache__/' \
  "${REPO_ROOT}/overlay" \
  "${REPO_ROOT}/python" \
  "${PYNQ_TARGET}:${PYNQ_JUPYTER_DIR}/"

rsync -av \
  "${REPO_ROOT}/notebooks/15_stage27h_time_spec_fft_fullrate_control.ipynb" \
  "${REPO_ROOT}/notebooks/README.md" \
  "${PYNQ_TARGET}:${PYNQ_JUPYTER_DIR}/notebooks/"

cat <<EOF
Published T510 F-engine Jupyter instrument to:
  ${PYNQ_TARGET}:${PYNQ_JUPYTER_DIR}

Open from PYNQ Jupyter:
  t510_fengine/notebooks/15_stage27h_time_spec_fft_fullrate_control.ipynb
Stage 27h production scope:
  - TIME/SPEC 100MHz FFT-only full-rate science stream control and status
  - Jupyter preview/control for RF reconstructed waveform and FFT-only spectrum

Older notebooks remain in the repository as archived bring-up references. This
publisher intentionally syncs only the production notebook.
EOF
