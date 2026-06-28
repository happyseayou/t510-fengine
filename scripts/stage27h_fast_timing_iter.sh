#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VIVADO_ROOT="${VIVADO_ROOT:-/run/media/astrolab/data/xilinx-ep/Vivado/2022.2}"
LOCAL_LOCALE="${LOCAL_LOCALE:-${HOME}/.local/share/locale}"
REPORT_DIR="${REPO_ROOT}/reports/board"
mkdir -p "${REPORT_DIR}"

PIDFILE="${REPORT_DIR}/stage27h_fast_timing_iter_vivado.pid"
LOG="${REPORT_DIR}/stage27h_fast_timing_iter_vivado.log"
JOU="${REPORT_DIR}/stage27h_fast_timing_iter_vivado.jou"
OUT="${REPORT_DIR}/stage27h_fast_timing_iter_nohup.out"

if [[ -f "${PIDFILE}" ]]; then
  old_pid="$(cat "${PIDFILE}" 2>/dev/null || true)"
  if [[ -n "${old_pid}" ]] && ps -p "${old_pid}" >/dev/null 2>&1; then
    old_cmd="$(ps -o cmd= -p "${old_pid}")"
    if [[ "${old_cmd}" == *"stage27h_fast_timing_iter.tcl"* ]]; then
      old_pgid="$(ps -o pgid= -p "${old_pid}" | tr -d ' ')"
      echo "Stopping existing Stage 27h fast timing run pid=${old_pid} pgid=${old_pgid}"
      kill -TERM "-${old_pgid}" 2>/dev/null || true
      sleep 5
      if ps -p "${old_pid}" >/dev/null 2>&1; then
        kill -KILL "-${old_pgid}" 2>/dev/null || true
      fi
    else
      echo "Refusing to reuse ${PIDFILE}: pid ${old_pid} is not a Stage 27h fast timing run." >&2
      exit 1
    fi
  fi
fi

rm -f "${PIDFILE}" "${LOG}" "${JOU}" "${OUT}"
rm -f \
  "${REPO_ROOT}/demo-ant.runs/synth_1/__synthesis_is_running__" \
  "${REPO_ROOT}/demo-ant.runs/impl_1/__implementation_is_running__"

setsid bash -c '
  echo $$ > "$1"
  cd "$2"
  export LOCPATH="$3"
  export LD_LIBRARY_PATH="$4/lib/lnx64.o/SuSE${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
  exec "$4/bin/vivado" -mode batch \
    -source scripts/stage27h_fast_timing_iter.tcl \
    -journal "$5" \
    -log "$6"
' _ "${PIDFILE}" "${REPO_ROOT}" "${LOCAL_LOCALE}" "${VIVADO_ROOT}" "${JOU}" "${LOG}" \
  > "${OUT}" 2>&1 < /dev/null &

sleep 3
pid="$(cat "${PIDFILE}")"
ps -o pid,ppid,pgid,sid,etimes,stat,cmd -p "${pid}"

cat <<EOF
Stage 27h fast timing run started.
  pid: ${pid}
  log: ${LOG}
  journal: ${JOU}
  out: ${OUT}
EOF
