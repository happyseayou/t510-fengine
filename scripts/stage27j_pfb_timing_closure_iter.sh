#!/usr/bin/env bash
set -euo pipefail

export T510_TIMING_STAGE_NAME="${T510_TIMING_STAGE_NAME:-stage27j_pfb_timing_closure_iter}"
export T510_STAGE27I_ANTI_ALIAS="${T510_STAGE27I_ANTI_ALIAS:-1}"
export T510_STAGE27J_PFB="${T510_STAGE27J_PFB:-1}"

exec "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/stage27h_timing_closure_iter.sh"
