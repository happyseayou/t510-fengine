#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Stage 28 keeps 24 logical flows/workers but steers them onto four hardware
# RX queues.  At the production aggregate rate this is about 240 kpps / 16
# Gbit/s per queue.  This avoids the intermittent ConnectX-5 physical-port
# discards seen with 24 simultaneously active RX queues, before packets reach
# PACKET_MMAP or Rust.  Arguments supplied by the caller remain last so an
# alternate queue count or interface can still be selected explicitly.
exec env STAGE27H_SET_NTUPLE=1 \
  "${SCRIPT_DIR}/host_stage27h_rx_fanout_tune.sh" \
  --queue-count 4 \
  "$@"
