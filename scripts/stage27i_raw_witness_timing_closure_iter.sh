#!/usr/bin/env bash
set -euo pipefail

export T510_STAGE27I_RAW_WITNESS=1
export T510_TIMING_STAGE_NAME="${T510_TIMING_STAGE_NAME:-stage27i_raw_witness_timing_closure_iter}"

exec "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/stage27h_timing_closure_iter.sh"
