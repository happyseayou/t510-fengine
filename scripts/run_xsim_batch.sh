#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VIVADO_ROOT="${VIVADO_ROOT:-/run/media/astrolab/data/xilinx-ep/Vivado/2022.2}"
LOCAL_LOCALE="${HOME}/.local/share/locale"
WORK_DIR="${T510_XSIM_WORK_DIR:-${REPO_ROOT}/.xsim_batch}"

if [[ ! -d "${LOCAL_LOCALE}/en_US.UTF-8" ]]; then
  mkdir -p "${LOCAL_LOCALE}/en_US.UTF-8"
  localedef -i en_US -f UTF-8 "${LOCAL_LOCALE}/en_US.UTF-8"
fi

export LOCPATH="${LOCAL_LOCALE}"
export LD_LIBRARY_PATH="${VIVADO_ROOT}/lib/lnx64.o/SuSE${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"
mkdir -p "${WORK_DIR}"
cp "${REPO_ROOT}/rtl/adc_interleave_sine_q17_1024.mem" "${WORK_DIR}/adc_interleave_sine_q17_1024.mem"

extra_xvlog_args=()
for define in ${EXTRA_XVLOG_DEFINES:-}; do
  extra_xvlog_args+=("-d" "${define}")
done
if [[ "${T510_USE_SIM_FFT_MODEL:-1}" == "1" ]]; then
  extra_xvlog_args=("-d" "T510_SIM_FFT_MODEL" "${extra_xvlog_args[@]}")
fi

rtl_files=(
  rtl/sync_fsm.sv
  rtl/station_sync_scheduler.sv
  rtl/axis_stream_duplicator.sv
  rtl/science_decim2_halfband_aa.sv
  rtl/science_rate_selector.sv
  rtl/requantizer.sv
  rtl/monitor_counters.sv
  rtl/adc_interleave_spur_corrector.sv
  rtl/pfb_channelizer.sv
  rtl/axis_sideband_async_fifo.sv
  rtl/axis512_register_slice.sv
  rtl/time_axis512_ddr_ring.sv
  rtl/time_udp_cmac512.sv
  rtl/spec_udp_cmac512.sv
  rtl/cmac_tx_source_mux.sv
  rtl/t510_cmac_qsfp0.sv
  rtl/multi_preview_observer.sv
  rtl/t510_dac_loopback_source.sv
  rtl/feng_ctrl_axi.sv
  rtl/axi4_to_axil_bridge.sv
  rtl/rfdc_adc_axis_adapter.sv
  rtl/t510_fengine_top.sv
)

tb_files=(
  sim/tb_adc_interleave_spur_corrector.sv
  sim/tb_feng_ctrl_axi.sv
  sim/tb_axi4_to_axil_bridge.sv
  sim/tb_sync_fsm.sv
  sim/tb_station_sync_scheduler.sv
  sim/tb_t510_dac_loopback_source.sv
  sim/tb_rfdc_adc_axis_adapter.sv
  sim/tb_science_rate_selector.sv
  sim/tb_rfdc_fullrate_preview.sv
  sim/tb_axis_stream_duplicator.sv
  sim/tb_pfb_channelizer.sv
  sim/tb_axis512_register_slice.sv
  sim/tb_time_axis512_ddr_ring.sv
  sim/tb_time_udp_cmac512.sv
  sim/tb_spec_udp_cmac512.sv
  sim/tb_cmac_tx_source_mux.sv
  sim/tb_t510_cmac_pause.sv
  sim/tb_t510_fengine_top_smoke.sv
  sim/tb_xfft_8lane_config_wrapper.sv
)

tb_tops=("$@")
if [[ ${#tb_tops[@]} -eq 0 ]]; then
  tb_tops=(
    tb_adc_interleave_spur_corrector
    tb_feng_ctrl_axi
    tb_axi4_to_axil_bridge
    tb_sync_fsm
    tb_station_sync_scheduler
    tb_t510_dac_loopback_source
    tb_rfdc_adc_axis_adapter
    tb_science_rate_selector
    tb_rfdc_fullrate_preview
    tb_axis_stream_duplicator
    tb_pfb_channelizer
    tb_axis512_register_slice
    tb_time_axis512_ddr_ring
    tb_time_udp_cmac512
    tb_spec_udp_cmac512
    tb_cmac_tx_source_mux
    tb_t510_cmac_pause
    tb_t510_fengine_top_smoke
    tb_xfft_8lane_config_wrapper
  )
fi

pushd "${WORK_DIR}" >/dev/null
{
  printf 'verilog xil_defaultlib "%s"\n' "${REPO_ROOT}/sim/tb_common.svh"
  printf 'verilog xil_defaultlib "%s"\n' "${VIVADO_ROOT}/data/verilog/src/glbl.v"
  for file in "${rtl_files[@]}"; do
    printf 'verilog xil_defaultlib "%s/%s"\n' "${REPO_ROOT}" "${file}"
  done
  for file in "${tb_files[@]}"; do
    printf 'verilog xil_defaultlib "%s/%s"\n' "${REPO_ROOT}" "${file}"
  done
} > vlog.prj

sv_abs_files=("${REPO_ROOT}/sim/tb_common.svh")
for file in "${rtl_files[@]}"; do
  sv_abs_files+=("${REPO_ROOT}/${file}")
done
for file in "${tb_files[@]}"; do
  sv_abs_files+=("${REPO_ROOT}/${file}")
done

"${VIVADO_ROOT}/bin/xvlog" --incr --relax --work xil_defaultlib \
  "${VIVADO_ROOT}/data/verilog/src/glbl.v" | tee xvlog_glbl.log
"${VIVADO_ROOT}/bin/xvlog" --incr --relax --sv --work xil_defaultlib \
  "${extra_xvlog_args[@]}" -i "${REPO_ROOT}/sim" "${sv_abs_files[@]}" | tee xvlog.log

failed=0
for tb in "${tb_tops[@]}"; do
  echo "INFO: Running ${tb}"
  "${VIVADO_ROOT}/bin/xelab" --incr --debug typical --relax --mt 8 \
    -L xil_defaultlib -L unisims_ver -L unimacro_ver -L secureip -L xpm \
    --snapshot "${tb}_behav" "xil_defaultlib.${tb}" xil_defaultlib.glbl \
    -log "${tb}_xelab.log"
  "${VIVADO_ROOT}/bin/xsim" "${tb}_behav" -R -log "${tb}_xsim.log" || failed=1
  if grep -Eq "CHECK FAILED|^Error:|^Fatal:" "${tb}_xsim.log"; then
    failed=1
  fi
done
popd >/dev/null

if [[ ${failed} -ne 0 ]]; then
  echo "ERROR: one or more current XSim testbenches failed; logs are in ${WORK_DIR}" >&2
  exit 1
fi
echo "INFO: all current XSim batch testbenches passed"
