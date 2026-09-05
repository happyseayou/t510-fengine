#!/usr/bin/env bash
set -euo pipefail
: "${WORK:?}" "${ANALYSIS_DIR:?}" "${ARRAY_JOB_ID:?}"
PYTHON=/home/software/commom_envs/astro2026/bin/python
sacct -j "${ARRAY_JOB_ID}" --state=COMPLETED,FAILED,CANCELLED,TIMEOUT,OUT_OF_MEMORY \
  --format=JobID,JobName,State,ExitCode,NodeList,Elapsed,AllocCPUS,ReqMem,MaxRSS \
  --parsable2 > "${WORK}/slurm_evidence.txt"
completed=$(awk -F'|' '$1 ~ /^[0-9]+_[0-9]+$/ && $3 == "COMPLETED" {n++} END {print n+0}' "${WORK}/slurm_evidence.txt")
test "${completed}" -eq 48
PYTHONPATH="${WORK}/code" "${PYTHON}" "${WORK}/code/t510_stage35_slurm_finalize.py" \
  --config "${WORK}/analysis_config.json" --slurm-evidence "${WORK}/slurm_evidence.txt"
printf 'READY\n' > "${WORK}/READY.partial"
mv "${WORK}/READY.partial" "${WORK}/READY"
