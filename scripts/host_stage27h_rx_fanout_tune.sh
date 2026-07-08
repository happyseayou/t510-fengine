#!/usr/bin/env bash
set -euo pipefail

IFACE="ens2f0np0"
APPLY_RING=1
APPLY_HOST_TUNE=1
APPLY_RAW_DROP=1
APPLY_COALESCE=1
APPLY_GOVERNOR=1
PORT_BASE=4300
PORT_COUNT=24
QUEUE_BASE=0
QUEUE_COUNT=""
FANOUT_GROUP="0x279"
NETDEV_BUDGET=1000
NETDEV_BUDGET_USECS=8000
NETDEV_MAX_BACKLOG=250000
RX_USECS=32
RX_FRAMES=128

usage() {
  cat <<'EOF'
Usage: scripts/host_stage27h_rx_fanout_tune.sh [options] [interface]

Stage 27h host-side PACKET_FANOUT / ntuple helper for TIME_SPEC 100MHz convergence.

Defaults:
  - TIME ports: 4300..4307
  - SPEC ports: 4308..4323
  - applies RX/TX ring 8192
  - applies CPU performance governor when cpupower is available
  - applies netdev budget/backlog tuning
  - applies RX coalescing rx-usecs=32 rx-frames=128
  - installs raw PREROUTING drop for UDP dst ports 4300..4323 so AF_PACKET
    receives the production stream without the normal UDP stack generating
    UdpNoPorts/ICMP work for the same packets
  - reports ring/RSS/ntuple/queue/NIC counters

Optional:
  --no-set             skip ring-size update
  --no-host-tune       skip governor, coalescing, and raw-drop tuning
  --no-governor        skip CPU governor update
  --no-coalesce        skip ethtool -C update
  --no-raw-drop        skip raw PREROUTING UDP drop
  --rx-usecs N         RX coalescing usecs, default 32
  --rx-frames N        RX coalescing frames, default 128
  --netdev-budget N    net.core.netdev_budget, default 1000
  --netdev-usecs N     net.core.netdev_budget_usecs, default 8000
  --netdev-backlog N   net.core.netdev_max_backlog, default 250000
  --fanout-group HEX   PACKET_FANOUT group for the printed command, default 0x279
  --port-base N        first production UDP dst port, default 4300
  --port-count N       production flow count, default 24
  --queue-base N       first ntuple rule/queue location, default 0
  --queue-count N      ntuple queue-count modulo, default current combined queues

  STAGE27H_SET_RSS_HASH=1  attempt ethtool -N <iface> rx-flow-hash udp4 sdfn
  STAGE27H_SET_NTUPLE=1    steer dst ports 4300..4323 to RX queues, modulo available queue count
  STAGE27H_CLEAR_NTUPLE=1  delete ntuple rules loc queue_base..queue_base+port_count-1
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
    --no-host-tune)
      APPLY_HOST_TUNE=0
      APPLY_GOVERNOR=0
      APPLY_COALESCE=0
      APPLY_RAW_DROP=0
      shift
      ;;
    --no-governor)
      APPLY_GOVERNOR=0
      shift
      ;;
    --no-coalesce)
      APPLY_COALESCE=0
      shift
      ;;
    --no-raw-drop)
      APPLY_RAW_DROP=0
      shift
      ;;
    --rx-usecs)
      RX_USECS="$2"
      shift 2
      ;;
    --rx-frames)
      RX_FRAMES="$2"
      shift 2
      ;;
    --netdev-budget)
      NETDEV_BUDGET="$2"
      shift 2
      ;;
    --netdev-usecs)
      NETDEV_BUDGET_USECS="$2"
      shift 2
      ;;
    --netdev-backlog)
      NETDEV_MAX_BACKLOG="$2"
      shift 2
      ;;
    --fanout-group)
      FANOUT_GROUP="$2"
      shift 2
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
if (( PORT_COUNT < 1 || PORT_COUNT > 24 )); then
  echo "ERROR: --port-count must be in range 1..24 for Stage 27h production" >&2
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

section "Stage 27h RX Fanout Context"
date --iso-8601=seconds
echo "interface=${IFACE}"
echo "port_range=${PORT_BASE}..$((PORT_BASE + PORT_COUNT - 1))"
echo "ntuple_rule_loc_range=${QUEUE_BASE}..$((QUEUE_BASE + PORT_COUNT - 1))"
echo "action_queue_range=${QUEUE_BASE}..$((QUEUE_BASE + QUEUE_COUNT - 1))"
echo "action_queue_mapping=queue_base + (port_index % queue_count)"
echo "fanout_group=${FANOUT_GROUP}"
echo "host_tune=${APPLY_HOST_TUNE}"
echo "raw_drop=${APPLY_RAW_DROP}"
echo "coalesce=${APPLY_COALESCE} rx-usecs=${RX_USECS} rx-frames=${RX_FRAMES}"
echo "netdev_budget=${NETDEV_BUDGET} netdev_budget_usecs=${NETDEV_BUDGET_USECS} netdev_max_backlog=${NETDEV_MAX_BACKLOG}"
echo "governor=${APPLY_GOVERNOR}"
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

section "Apply Stage 27h Production Host RX Tuning"
if [[ "${APPLY_HOST_TUNE}" -eq 0 ]]; then
  echo "skipped by --no-host-tune"
elif [[ "${EUID}" -ne 0 ]]; then
  echo "WARN: not root; skipping production host tuning. Re-run with sudo."
else
  if [[ "${APPLY_GOVERNOR}" -eq 1 ]]; then
    if command -v cpupower >/dev/null 2>&1; then
      cpupower frequency-set -g performance || echo "WARN: cpupower performance governor update failed"
    else
      for governor in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do
        [[ -w "${governor}" ]] && printf 'performance\n' >"${governor}" || true
      done
    fi
  else
    echo "CPU governor update skipped"
  fi

  if [[ "${APPLY_COALESCE}" -eq 1 ]]; then
    sysctl -w \
      net.core.netdev_budget="${NETDEV_BUDGET}" \
      net.core.netdev_budget_usecs="${NETDEV_BUDGET_USECS}" \
      net.core.netdev_max_backlog="${NETDEV_MAX_BACKLOG}" || echo "WARN: sysctl netdev production tuning failed"
    ethtool -C "${IFACE}" adaptive-rx off rx-usecs "${RX_USECS}" rx-frames "${RX_FRAMES}" \
      adaptive-tx off tx-usecs 8 tx-frames 128 || echo "WARN: ethtool -C production coalescing update failed"
  else
    echo "RX coalescing update skipped"
  fi

  if [[ "${APPLY_RAW_DROP}" -eq 1 ]]; then
    if command -v iptables >/dev/null 2>&1; then
      port_end=$((PORT_BASE + PORT_COUNT - 1))
      iptables -t raw -C PREROUTING -i "${IFACE}" -p udp -m udp --dport "${PORT_BASE}:${port_end}" -j DROP 2>/dev/null ||
        iptables -t raw -I PREROUTING 1 -i "${IFACE}" -p udp -m udp --dport "${PORT_BASE}:${port_end}" -j DROP ||
        echo "WARN: failed to install raw PREROUTING UDP drop for ${PORT_BASE}:${port_end}"
    else
      echo "WARN: iptables not found; raw PREROUTING UDP drop not installed"
    fi
  else
    echo "raw PREROUTING UDP drop skipped"
  fi
fi

run_or_note "CPU Governor" bash -lc 'cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor 2>/dev/null || true'
run_or_note "Coalescing Settings" ethtool -c "${IFACE}"
if command -v iptables >/dev/null 2>&1; then
  run_or_note "Raw PREROUTING Rules" iptables -t raw -S PREROUTING
fi

if [[ "${STAGE27H_SET_RSS_HASH:-0}" == "1" ]]; then
  section "Attempt UDP4 RSS Hash Setup"
  if [[ "${EUID}" -ne 0 ]]; then
    echo "WARN: not root; skipping ethtool -N rx-flow-hash udp4 sdfn"
  else
    ethtool -N "${IFACE}" rx-flow-hash udp4 sdfn || echo "WARN: driver did not accept udp4 RSS hash update"
  fi
fi

if [[ "${STAGE27H_CLEAR_NTUPLE:-0}" == "1" ]]; then
  section "Clear Stage 27h Ntuple Rules"
  if [[ "${EUID}" -ne 0 ]]; then
    echo "WARN: not root; skipping ethtool -N delete"
  else
    for ((flow = 0; flow < PORT_COUNT; flow++)); do
      ethtool -N "${IFACE}" delete "$((QUEUE_BASE + flow))" 2>/dev/null || true
    done
  fi
fi

if [[ "${STAGE27H_SET_NTUPLE:-0}" == "1" ]]; then
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
  --worker-count 24 \\
  --fanout-mode port \\
  --fanout-group ${FANOUT_GROUP} \\
  --pin-workers auto \\
  --interface ${IFACE} \\
  --dst-port-base ${PORT_BASE} \\
  --src-port-base 4000 \\
  --flow-count ${PORT_COUNT} \\
  --time-flow-count 8 \\
  --spec-flow-count 16 \\
  --spec-layout 27h \\
  --web 0.0.0.0:8089 \\
  --initial-bandwidth-mhz 100 \\
  --ring-mb 2048 \\
  --block-mb 4 \\
  --batch-size 8192 \\
  --web-fps 30 \\
  --waveform-points 1024 \\
  --waveform-max-points 16384
EOF
