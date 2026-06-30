#!/usr/bin/env bash
set -euo pipefail

VIVADO_ROOT="${VIVADO_ROOT:-/run/media/astrolab/data/xilinx-ep/Vivado/2022.2}"
LOCAL_LOCALE="${LOCAL_LOCALE:-${HOME}/.local/share/locale}"

if [[ ! -d "${LOCAL_LOCALE}/en_US.UTF-8" ]]; then
  mkdir -p "${LOCAL_LOCALE}/en_US.UTF-8"
  localedef -i en_US -f UTF-8 "${LOCAL_LOCALE}/en_US.UTF-8"
fi

export LOCPATH="${LOCAL_LOCALE}"
export LD_LIBRARY_PATH="${VIVADO_ROOT}/lib/lnx64.o/SuSE${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"

exec "${VIVADO_ROOT}/bin/vivado" "$@"
