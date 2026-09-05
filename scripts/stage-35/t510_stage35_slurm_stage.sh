#!/usr/bin/env bash
set -euo pipefail
: "${WORK:?}" "${INPUT_URL:?}" "${ANALYSIS_DIR:?}"
PYTHON=/home/software/commom_envs/astro2026/bin/python
mkdir -p "${WORK}/input" "${WORK}/logs"
curl --fail --location --retry 2 --retry-delay 30 "${INPUT_URL}" \
  | tar -xf - -C "${WORK}/input"
for dataset in \
  stage35-40-360mhz-v2-20260902-1225-self-a-spec-scan-900s \
  stage35-40-360mhz-v2-20260902-1225-self-b-spec-scan-900s \
  stage35-40-360mhz-v2-20260902-1225-self-c-spec-scan-900s \
  stage35-40-360mhz-v2-20260902-1225-self-a-time-pre-30s \
  stage35-40-360mhz-v2-20260902-1225-self-a-time-post-30s \
  stage35-40-360mhz-v2-20260902-1225-self-b-time-pre-30s \
  stage35-40-360mhz-v2-20260902-1225-self-b-time-post-30s \
  stage35-40-360mhz-v2-20260902-1225-self-c-time-pre-30s \
  stage35-40-360mhz-v2-20260902-1225-self-c-time-post-30s
do
  jq -r --arg dataset "${dataset}" \
    '.files[] | "\(.sha256)  \($dataset)/\(.path)"' \
    "${WORK}/input/${dataset}/dataset_manifest.json"
done > "${WORK}/input_files.sha256"
mkdir "${WORK}/checksum_parts"
split -d -n l/96 "${WORK}/input_files.sha256" "${WORK}/checksum_parts/part-"
find "${WORK}/checksum_parts" -type f -print0 \
  | xargs -0 -n 1 -P 96 sh -c 'cd "$1/input" && sha256sum --quiet --check "$2"' sh "${WORK}"
jq --arg input "${WORK}/input" --arg output "${WORK}/${ANALYSIS_DIR}" '
  walk(if type == "string" then sub("^/var/lib/t510/stage35"; $input) else . end)
  | .output_root = $output | .parallel_workers = 1
' "${WORK}/source_analysis_config.json" > "${WORK}/analysis_config.json.partial"
mv "${WORK}/analysis_config.json.partial" "${WORK}/analysis_config.json"
mkdir -p "${WORK}/${ANALYSIS_DIR}"
"${PYTHON}" "${WORK}/code/t510_stage35_s2_analyze.py" self-test
PYTHONPATH="${WORK}/code" "${PYTHON}" -c \
  'import json,sys,t510_stage35_s2_analyze as a; c=json.load(open(sys.argv[1])); a.validate_config(c); print(json.dumps(a.verify_inputs(c),sort_keys=True))' \
  "${WORK}/analysis_config.json"
touch "${WORK}/STAGED"
