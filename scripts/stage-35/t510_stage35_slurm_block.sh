#!/usr/bin/env bash
set -euo pipefail
: "${WORK:?}" "${SLURM_ARRAY_TASK_ID:?}"
PYTHON=/home/software/commom_envs/astro2026/bin/python
scan_index=$((SLURM_ARRAY_TASK_ID / 16))
block_index=$((SLURM_ARRAY_TASK_ID % 16))
export OMP_NUM_THREADS="${SLURM_CPUS_PER_TASK}"
export OPENBLAS_NUM_THREADS="${SLURM_CPUS_PER_TASK}"
export MKL_NUM_THREADS="${SLURM_CPUS_PER_TASK}"
export NUMEXPR_NUM_THREADS="${SLURM_CPUS_PER_TASK}"
"${PYTHON}" "${WORK}/code/t510_stage35_s2_analyze.py" block \
  --config "${WORK}/analysis_config.json" \
  --scan-index "${scan_index}" --block-index "${block_index}"
