#!/usr/bin/env bash
set -euo pipefail

export T510_STAGE27I_RAW_WITNESS=1
export T510_TIMING_STAGE_NAME="${T510_TIMING_STAGE_NAME:-stage27i_raw_witness_timing_closure_iter}"
export T510_WRITE_STAGE_NAME="${T510_WRITE_STAGE_NAME:-stage27i_raw_witness_write_bitstream}"

exec "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/stage27h_write_bitstream_from_timing_closure.sh"
