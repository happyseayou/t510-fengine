#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VIVADO_ROOT="${VIVADO_ROOT:-/run/media/astrolab/data/xilinx-ep/Vivado/2022.2}"
LOCAL_LOCALE="${HOME}/.local/share/locale"
WORK_DIR="${REPO_ROOT}/.xsim_batch"

if [[ ! -d "${LOCAL_LOCALE}/en_US.UTF-8" ]]; then
  mkdir -p "${LOCAL_LOCALE}/en_US.UTF-8"
  localedef -i en_US -f UTF-8 "${LOCAL_LOCALE}/en_US.UTF-8"
fi

export LOCPATH="${LOCAL_LOCALE}"
export LD_LIBRARY_PATH="${VIVADO_ROOT}/lib/lnx64.o/SuSE${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"

mkdir -p "${WORK_DIR}"

extra_xvlog_args=()
for define in ${EXTRA_XVLOG_DEFINES:-}; do
  extra_xvlog_args+=("-d" "${define}")
done

rtl_files=(
  rtl/sync_fsm.sv
  rtl/axis_stream_duplicator.sv
  rtl/science_rate_selector.sv
  rtl/science_stream_decimator.sv
  rtl/requantizer.sv
  rtl/monitor_counters.sv
  rtl/time_packetizer.sv
  rtl/pfb_channelizer.sv
  rtl/spectral_packetizer.sv
  rtl/udp_tx_arbiter.sv
  rtl/axis_packet_fifo.sv
  rtl/tx_route_selector.sv
  rtl/udp_frame_builder.sv
  rtl/axis64_to_cmac512_async.sv
  rtl/axis512_register_slice.sv
  rtl/time_axis512_ddr_ring.sv
  rtl/time_udp_cmac512.sv
  rtl/spec_udp_cmac512.sv
  rtl/cmac_tx_source_mux.sv
  rtl/tx_header_capture.sv
  rtl/tx_payload_witness_capture.sv
  rtl/dac_tx_witness_capture.sv
  rtl/rfdc_axis_raw_witness_capture.sv
  rtl/t510_qsfp_test_frame_gen.sv
  rtl/fft_debug_observer.sv
  rtl/multi_preview_observer.sv
  rtl/t510_dac_loopback_source.sv
  rtl/feng_ctrl_axi.sv
  rtl/axi4_to_axil_bridge.sv
  rtl/rfdc_adc_axis_adapter.sv
  rtl/t510_fengine_top.sv
  rtl/t510_cmac_qsfp0.sv
  rtl/t510_fengine_synthetic_board_top.sv
)

tb_files=(
  sim/tb_feng_ctrl_axi.sv
  sim/tb_axi4_to_axil_bridge.sv
  sim/tb_sync_fsm.sv
  sim/tb_rfdc_adc_axis_adapter.sv
  sim/tb_science_rate_selector.sv
  sim/tb_science_stream_decimator.sv
  sim/tb_axis_stream_duplicator.sv
  sim/tb_time_packetizer.sv
  sim/tb_pfb_channelizer.sv
  sim/tb_spectral_packetizer.sv
  sim/tb_udp_tx_arbiter.sv
  sim/tb_axis_packet_fifo.sv
  sim/tb_tx_route_selector.sv
  sim/tb_udp_frame_builder.sv
  sim/tb_axis512_register_slice.sv
  sim/tb_time_axis512_ddr_ring.sv
  sim/tb_time_udp_cmac512.sv
  sim/tb_spec_udp_cmac512.sv
  sim/tb_stage25_cmac_live_tx.sv
  sim/tb_t510_qsfp_test_frame_gen.sv
  sim/tb_tx_payload_witness_capture.sv
  sim/tb_dac_tx_witness_capture.sv
  sim/tb_rfdc_axis_raw_witness_capture.sv
  sim/tb_fft_debug_observer.sv
  sim/tb_t510_dac_loopback_source.sv
  sim/tb_rfdc_fullrate_preview.sv
  sim/tb_preview_event_capture.sv
  sim/tb_t510_fengine_top_smoke.sv
  sim/tb_t510_fengine_board_top.sv
)

tb_tops=("$@")
if [[ ${#tb_tops[@]} -eq 0 ]]; then
  tb_tops=(
    tb_feng_ctrl_axi
    tb_axi4_to_axil_bridge
    tb_sync_fsm
    tb_rfdc_adc_axis_adapter
    tb_science_rate_selector
    tb_science_stream_decimator
    tb_axis_stream_duplicator
    tb_time_packetizer
    tb_pfb_channelizer
    tb_spectral_packetizer
    tb_udp_tx_arbiter
    tb_axis_packet_fifo
    tb_tx_route_selector
    tb_udp_frame_builder
    tb_axis512_register_slice
    tb_time_axis512_ddr_ring
    tb_time_udp_cmac512
    tb_spec_udp_cmac512
    tb_stage25_cmac_live_tx
    tb_t510_qsfp_test_frame_gen
    tb_tx_payload_witness_capture
    tb_dac_tx_witness_capture
    tb_rfdc_axis_raw_witness_capture
    tb_fft_debug_observer
    tb_t510_dac_loopback_source
    tb_rfdc_fullrate_preview
    tb_preview_event_capture
    tb_t510_fengine_top_smoke
    tb_t510_fengine_board_top
  )
fi

pushd "${WORK_DIR}" >/dev/null

cat > vlog.prj <<EOF
verilog xil_defaultlib "${REPO_ROOT}/sim/tb_common.svh"
verilog xil_defaultlib "${VIVADO_ROOT}/data/verilog/src/glbl.v"
EOF

for f in "${rtl_files[@]}"; do
  echo "verilog xil_defaultlib \"${REPO_ROOT}/${f}\"" >> vlog.prj
done
for f in "${tb_files[@]}"; do
  echo "verilog xil_defaultlib \"${REPO_ROOT}/${f}\"" >> vlog.prj
done

sv_abs_files=("${REPO_ROOT}/sim/tb_common.svh")
for f in "${rtl_files[@]}"; do
  sv_abs_files+=("${REPO_ROOT}/${f}")
done
for f in "${tb_files[@]}"; do
  sv_abs_files+=("${REPO_ROOT}/${f}")
done

"${VIVADO_ROOT}/bin/xvlog" --incr --relax --work xil_defaultlib \
  "${VIVADO_ROOT}/data/verilog/src/glbl.v" | tee xvlog_glbl.log
"${VIVADO_ROOT}/bin/xvlog" --incr --relax --sv --work xil_defaultlib \
  -d T510_SIM_FFT_MODEL "${extra_xvlog_args[@]}" \
  -i "${REPO_ROOT}/sim" "${sv_abs_files[@]}" | tee xvlog.log

failed=0
for tb in "${tb_tops[@]}"; do
  echo "INFO: Running ${tb}"
  "${VIVADO_ROOT}/bin/xelab" --incr --debug typical --relax --mt 8 \
    -L xil_defaultlib -L unisims_ver -L unimacro_ver -L secureip -L xpm \
    --snapshot "${tb}_behav" "xil_defaultlib.${tb}" xil_defaultlib.glbl \
    -log "${tb}_xelab.log"
  "${VIVADO_ROOT}/bin/xsim" "${tb}_behav" -R -log "${tb}_xsim.log" || failed=1
  if grep -Eq "CHECK FAILED|^Error: \\[" "${tb}_xsim.log"; then
    failed=1
  fi
done

popd >/dev/null

if [[ ${failed} -ne 0 ]]; then
  echo "ERROR: one or more XSim testbenches failed; logs are in ${WORK_DIR}" >&2
  exit 1
fi

echo "INFO: all XSim batch testbenches passed"
