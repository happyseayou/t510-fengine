#!/usr/bin/env bash
set -euo pipefail

IFACE="ens2f0np0"
APPLY_RING=1
PORT_BASE=4300
PORT_COUNT=72
QUEUE_BASE=0
QUEUE_COUNT=""

usage() {
  cat <<'EOF'
Usage: scripts/host_stage27g_rx_fanout_tune.sh [--no-set] [--port-base N] [--port-count N] [--queue-base N] [--queue-count N] [interface]

Stage 27g host-side PACKET_FANOUT / ntuple helper for TIME_SPEC 100MHz convergence.

Defaults:
  - TIME ports: 4300..4307
  - SPEC ports: 4308..4371
  - reports ring/RSS/ntuple/queue/NIC counters

Optional:
  STAGE27G_SET_RSS_HASH=1  attempt ethtool -N <iface> rx-flow-hash udp4 sdfn
  STAGE27G_SET_NTUPLE=1    steer dst ports 4300..4371 to RX queues, modulo available queue count
  STAGE27G_CLEAR_NTUPLE=1  delete ntuple rules loc queue_base..queue_base+port_count-1
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --help|-h)
      usage
      exit 0
      ;;
    --no-set)
      APPLY_RING=0
      shift
      ;;
    --port-base)
      PORT_BASE="$2"
      shift 2
      ;;
    --port-count)
      PORT_COUNT="$2"
      shift 2
      ;;
    --queue-base)
      QUEUE_BASE="$2"
      shift 2
      ;;
    --queue-count)
      QUEUE_COUNT="$2"
      shift 2
      ;;
    *)
      IFACE="$1"
      shift
      ;;
  esac
done

section() {
  printf '\n==== %s ====\n' "$1"
}

run_or_note() {
  local label="$1"
  shift
  section "$label"
  if ! "$@"; then
    printf 'WARN: command failed:'
    printf ' %q' "$@"
    printf '\n'
  fi
}

if [[ ! -d "/sys/class/net/${IFACE}" ]]; then
  echo "ERROR: interface ${IFACE} not found under /sys/class/net" >&2
  exit 2
fi
if ! command -v ethtool >/dev/null 2>&1; then
  echo "ERROR: ethtool is required" >&2
  exit 2
fi
if (( PORT_COUNT < 1 || PORT_COUNT > 72 )); then
  echo "ERROR: --port-count must be in range 1..72" >&2
  exit 2
fi
if [[ -z "${QUEUE_COUNT}" ]]; then
  QUEUE_COUNT="$(ethtool -l "${IFACE}" 2>/dev/null | awk '
    /^Current hardware settings:/ { current=1; next }
    current && $1 == "Combined:" { print $2; exit }
  ')"
fi
if [[ -z "${QUEUE_COUNT}" || ! "${QUEUE_COUNT}" =~ ^[0-9]+$ ]]; then
  QUEUE_COUNT="${PORT_COUNT}"
fi
if (( QUEUE_COUNT < 1 )); then
  echo "ERROR: --queue-count must be >= 1" >&2
  exit 2
fi

section "Stage 27g RX Fanout Context"
date --iso-8601=seconds
echo "interface=${IFACE}"
echo "port_range=${PORT_BASE}..$((PORT_BASE + PORT_COUNT - 1))"
echo "ntuple_rule_loc_range=${QUEUE_BASE}..$((QUEUE_BASE + PORT_COUNT - 1))"
echo "action_queue_range=${QUEUE_BASE}..$((QUEUE_BASE + QUEUE_COUNT - 1))"
echo "action_queue_mapping=queue_base + (port_index % queue_count)"
echo "fanout_group=0x270"
echo "driver=$(basename "$(readlink -f "/sys/class/net/${IFACE}/device/driver" 2>/dev/null || echo unknown)")"
cat "/sys/class/net/${IFACE}/operstate" 2>/dev/null | sed 's/^/operstate=/'
cat "/sys/class/net/${IFACE}/mtu" 2>/dev/null | sed 's/^/mtu=/'

section "Apply Ring Size"
if [[ "${APPLY_RING}" -eq 1 ]]; then
  if [[ "${EUID}" -ne 0 ]]; then
    echo "WARN: not root; skipping ethtool -G. Re-run with sudo to apply RX/TX ring."
  else
    ethtool -G "${IFACE}" rx 8192 tx 8192 || echo "WARN: ethtool -G failed"
  fi
else
  echo "skipped by --no-set"
fi

if [[ "${STAGE27G_SET_RSS_HASH:-0}" == "1" ]]; then
  section "Attempt UDP4 RSS Hash Setup"
  if [[ "${EUID}" -ne 0 ]]; then
    echo "WARN: not root; skipping ethtool -N rx-flow-hash udp4 sdfn"
  else
    ethtool -N "${IFACE}" rx-flow-hash udp4 sdfn || echo "WARN: driver did not accept udp4 RSS hash update"
  fi
fi

if [[ "${STAGE27G_CLEAR_NTUPLE:-0}" == "1" ]]; then
  section "Clear Stage 27g Ntuple Rules"
  if [[ "${EUID}" -ne 0 ]]; then
    echo "WARN: not root; skipping ethtool -N delete"
  else
    for ((flow = 0; flow < PORT_COUNT; flow++)); do
      ethtool -N "${IFACE}" delete "$((QUEUE_BASE + flow))" 2>/dev/null || true
    done
  fi
fi

if [[ "${STAGE27G_SET_NTUPLE:-0}" == "1" ]]; then
  section "Apply UDP Port to RX Queue Steering"
  if [[ "${EUID}" -ne 0 ]]; then
    echo "WARN: not root; skipping ntuple setup"
  else
    ethtool -K "${IFACE}" ntuple on || echo "WARN: failed to enable ntuple filters"
    for ((flow = 0; flow < PORT_COUNT; flow++)); do
      port=$((PORT_BASE + flow))
      queue=$((QUEUE_BASE + (flow % QUEUE_COUNT)))
      loc=$((QUEUE_BASE + flow))
      ethtool -N "${IFACE}" flow-type udp4 dst-port "${port}" action "${queue}" loc "${loc}" \
        || echo "WARN: failed to steer UDP dst port ${port} to RX queue ${queue}"
    done
  fi
fi

run_or_note "Ring Settings" ethtool -g "${IFACE}"
run_or_note "Driver Info" ethtool -i "${IFACE}"
run_or_note "Channel Settings" ethtool -l "${IFACE}"
run_or_note "RSS Indirection Table" ethtool -x "${IFACE}"
run_or_note "UDP4 RSS Hash Fields" ethtool -n "${IFACE}" rx-flow-hash udp4
run_or_note "Ntuple Rules" ethtool -n "${IFACE}"

section "Selected NIC Counters"
ethtool -S "${IFACE}" 2>/dev/null | awk '
  /rx.*(packet|bytes|drop|miss|error|crc|symbol|buffer|timeout)/ ||
  /rx[0-9]+.*(packet|bytes|drop|miss|error)/ ||
  /rx_queue_[0-9]+.*(packet|bytes|drop|miss|error)/ { print; shown=1 }
  END { if (!shown) print "WARN: no matching ethtool -S RX counters found" }
'

section "Kernel Netdev Counters"
for stat in rx_packets rx_bytes rx_dropped rx_errors rx_missed_errors rx_crc_errors tx_packets tx_bytes tx_dropped tx_errors; do
  path="/sys/class/net/${IFACE}/statistics/${stat}"
  if [[ -r "${path}" ]]; then
    printf '%s=%s\n' "${stat}" "$(cat "${path}")"
  fi
done

section "IRQ Distribution Hints"
grep -E "${IFACE}|mlx|ice|i40e|ixgbe|enp|ens" /proc/interrupts 2>/dev/null || echo "WARN: no matching IRQ lines found"

section "Recommended Receiver Command"
cat <<EOF
sudo rust/t510_time_rx/target/release/t510_time_rx \\
  --backend fanout \\
  --worker-count 32 \\
  --fanout-mode port \\
  --fanout-group 0x270 \\
  --pin-workers off \\
  --interface ${IFACE} \\
  --dst-port-base ${PORT_BASE} \\
  --src-port-base 4000 \\
  --flow-count ${PORT_COUNT} \\
  --time-flow-count 8 \\
  --spec-flow-count 64 \\
  --web 0.0.0.0:8089 \\
  --initial-bandwidth-mhz 100 \\
  --ring-mb 2048 \\
  --block-mb 4 \\
  --batch-size 8192 \\
  --web-fps 30 \\
  --waveform-points 1024 \\
  --waveform-max-points 16384
EOF
