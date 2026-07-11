#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
vivado_root="${VIVADO_ROOT:-/run/media/astrolab/data/xilinx-ep/Vivado/2022.2}"
report_dir="${repo_root}/reports/board"
log_file="${repo_root}/demo-ant.runs/synth_1/runme.log"
pid_file="${report_dir}/stage27j_dc_round_build_submit.pid"
out_file="${report_dir}/stage27j_dc_round_build_submit.out"

mkdir -p "${report_dir}"
rm -f "${pid_file}" "${out_file}"

setsid bash -c '
  echo $$ > "$1"
  while true; do
    if rg -q "synth_design completed successfully" "$2"; then
      break
    fi
    if rg -q "^ERROR:.*synth_design|synth_design failed" "$2"; then
      echo "Stage 27j DC-round build submitter: synth_1 failed" >&2
      exit 1
    fi
    sleep 30
  done
  cd "$3"
  export LD_LIBRARY_PATH="$4/lib/lnx64.o/SuSE${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
  exec "$4/bin/vivado" -mode batch -source scripts/stage27j_dc_round_impl_write.tcl
' _ "${pid_file}" "${log_file}" "${repo_root}" "${vivado_root}" >"${out_file}" 2>&1 < /dev/null &

sleep 1
pid="$(cat "${pid_file}")"
printf 'Stage 27j DC-round implementation/bitstream submitter started: pid=%s\nlog=%s\n' "${pid}" "${out_file}"
