#!/usr/bin/env bash
set -euo pipefail

IFACE="ens2f0np0"
APPLY_RING=1
PORT_BASE=4300
PORT_COUNT=16
QUEUE_BASE=0

usage() {
  cat <<'EOF'
Usage: scripts/host_stage27e_rx_fanout_tune.sh [--no-set] [--port-base N] [--port-count N] [--queue-base N] [interface]

Stage 27e host-side PACKET_FANOUT / ntuple evidence helper for TIME+SPEC.

Default actions:
  - set RX/TX ring to 8192 with ethtool -G when running as root
  - report ring settings, RSS hash config, RSS indirection, ntuple rules,
    queue counters, NIC drop/error counters, and IRQ distribution hints

Optional:
  STAGE27E_SET_RSS_HASH=1  attempt ethtool -N <iface> rx-flow-hash udp4 sdfn
  STAGE27E_SET_NTUPLE=1    enable ntuple and steer dst ports 4300..4315 to RX queues 0..15
  STAGE27E_CLEAR_NTUPLE=1  delete ntuple rules loc 0..15 before reporting

This script never stores credentials. Run it with sudo when you want ring
settings or ntuple rules to be applied.
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
    *)
      IFACE="$1"
      shift
      ;;
  esac
done

section() {
  printf '\n==== %s ====\n' "$1"
}

have() {
  command -v "$1" >/dev/null 2>&1
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

if ! have ethtool; then
  echo "ERROR: ethtool is required" >&2
  exit 2
fi

if (( PORT_COUNT < 1 || PORT_COUNT > 64 )); then
  echo "ERROR: --port-count must be in range 1..64" >&2
  exit 2
fi

section "Stage 27e RX Fanout Context"
date --iso-8601=seconds
echo "interface=${IFACE}"
echo "port_range=${PORT_BASE}..$((PORT_BASE + PORT_COUNT - 1))"
echo "queue_range=${QUEUE_BASE}..$((QUEUE_BASE + PORT_COUNT - 1))"
echo "driver=$(basename "$(readlink -f "/sys/class/net/${IFACE}/device/driver" 2>/dev/null || echo unknown)")"
cat "/sys/class/net/${IFACE}/operstate" 2>/dev/null | sed 's/^/operstate=/'
cat "/sys/class/net/${IFACE}/mtu" 2>/dev/null | sed 's/^/mtu=/'

if [[ "${APPLY_RING}" -eq 1 ]]; then
  section "Apply Ring Size"
  if [[ "${EUID}" -ne 0 ]]; then
    echo "WARN: not root; skipping ethtool -G. Re-run with sudo to apply RX/TX ring."
  else
    ethtool -G "${IFACE}" rx 8192 tx 8192 || echo "WARN: ethtool -G failed; continuing with current ring settings"
  fi
else
  section "Apply Ring Size"
  echo "skipped by --no-set"
fi

if [[ "${STAGE27E_SET_RSS_HASH:-0}" == "1" ]]; then
  section "Attempt UDP4 RSS Hash Setup"
  if [[ "${EUID}" -ne 0 ]]; then
    echo "WARN: not root; skipping ethtool -N rx-flow-hash udp4 sdfn"
  else
    ethtool -N "${IFACE}" rx-flow-hash udp4 sdfn || echo "WARN: driver did not accept udp4 RSS hash update"
  fi
fi

if [[ "${STAGE27E_CLEAR_NTUPLE:-0}" == "1" ]]; then
  section "Clear Stage 27e Ntuple Rules"
  if [[ "${EUID}" -ne 0 ]]; then
    echo "WARN: not root; skipping ethtool -N delete"
  else
    for ((flow = 0; flow < PORT_COUNT; flow++)); do
      ethtool -N "${IFACE}" delete "$((QUEUE_BASE + flow))" 2>/dev/null || true
    done
  fi
fi

if [[ "${STAGE27E_SET_NTUPLE:-0}" == "1" ]]; then
  section "Apply UDP Port to RX Queue Steering"
  if [[ "${EUID}" -ne 0 ]]; then
    echo "WARN: not root; skipping ntuple setup"
  else
    ethtool -K "${IFACE}" ntuple on || echo "WARN: failed to enable ntuple filters"
    for ((flow = 0; flow < PORT_COUNT; flow++)); do
      port=$((PORT_BASE + flow))
      queue=$((QUEUE_BASE + flow))
      ethtool -N "${IFACE}" flow-type udp4 dst-port "${port}" action "${queue}" loc "${queue}" \
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
  BEGIN { shown=0 }
  /rx.*(packet|bytes|drop|miss|error|crc|symbol|buffer|timeout)/ ||
  /rx[0-9]+.*(packet|bytes|drop|miss|error)/ ||
  /rx_queue_[0-9]+.*(packet|bytes|drop|miss|error)/ {
    print
    shown=1
  }
  END {
    if (!shown) {
      print "WARN: no matching ethtool -S RX counters found"
    }
  }
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
  --worker-count 16 \\
  --fanout-mode port \\
  --fanout-group 0x27e \\
  --pin-workers off \\
  --interface ${IFACE} \\
  --dst-port-base ${PORT_BASE} \\
  --src-port-base 4000 \\
  --flow-count ${PORT_COUNT} \\
  --time-flow-count 8 \\
  --spec-flow-count 8 \\
  --web 0.0.0.0:8089 \\
  --initial-bandwidth-mhz 100 \\
  --ring-mb 1024 \\
  --block-mb 4 \\
  --batch-size 4096 \\
  --web-fps 30 \\
  --waveform-points 1024 \\
  --waveform-max-points 16384
EOF
