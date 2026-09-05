#!/usr/bin/env bash
set -euo pipefail
: "${WORK:?}" "${ANALYSIS_DIR:?}"
PYTHON=/home/software/commom_envs/astro2026/bin/python
"${PYTHON}" "${WORK}/code/t510_stage35_slurm_prepare.py" \
  --work "${WORK}" --analysis-dir "${ANALYSIS_DIR}" --workers 96
"${PYTHON}" "${WORK}/code/t510_stage35_s2_analyze.py" self-test
PYTHONPATH="${WORK}/code" "${PYTHON}" -c \
  'import json,sys,t510_stage35_s2_analyze as a; c=json.load(open(sys.argv[1])); a.validate_config(c); print(json.dumps(a.verify_inputs(c),sort_keys=True))' \
  "${WORK}/analysis_config.json"
