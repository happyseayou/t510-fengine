#!/usr/bin/env bash
set -euo pipefail

IFACE="ens2f0np0"
MODE="time_spec"
QUEUE_COUNT=24
RX_USECS=8
RX_FRAMES=32

usage() {
  printf '%s\n' \
    "Usage: sudo scripts/host_t510_rx_tune.sh [--mode time_only|spec_only|time_spec] [--queue-count N] [interface]" \
    "Applies the current 24-port monitor tuning and UDP ntuple map."
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode) MODE="$2"; shift 2 ;;
    --queue-count) QUEUE_COUNT="$2"; shift 2 ;;
    --help|-h) usage; exit 0 ;;
    *) IFACE="$1"; shift ;;
  esac
done

case "${MODE}" in
  time_only|spec_only|time_spec) PORT_BASE=4300; PORT_COUNT=24 ;;
  *) printf 'ERROR: invalid --mode %s\n' "${MODE}" >&2; exit 2 ;;
esac

if [[ "${EUID}" -ne 0 ]]; then
  printf 'ERROR: T510 host tuning must run as root\n' >&2
  exit 2
fi
if [[ ! -d "/sys/class/net/${IFACE}" ]]; then
  printf 'ERROR: interface %s does not exist\n' "${IFACE}" >&2
  exit 2
fi
if ! command -v ethtool >/dev/null 2>&1; then
  printf 'ERROR: ethtool is required\n' >&2
  exit 2
fi
if ! [[ "${QUEUE_COUNT}" =~ ^[1-9][0-9]*$ ]]; then
  printf 'ERROR: --queue-count must be positive\n' >&2
  exit 2
fi

ethtool -G "${IFACE}" rx 8192 tx 8192
ethtool -C "${IFACE}" rx-usecs "${RX_USECS}" rx-frames "${RX_FRAMES}"
sysctl -w net.core.netdev_budget=1000
sysctl -w net.core.netdev_budget_usecs=8000
sysctl -w net.core.netdev_max_backlog=250000
if command -v cpupower >/dev/null 2>&1; then
  cpupower frequency-set -g performance || true
fi

# Clear the full ConnectX ntuple table so the production surface contains only
# the active T510 port map.
for location in $(seq 0 127); do
  ethtool -N "${IFACE}" delete "${location}" 2>/dev/null || true
done
for index in $(seq 0 $((PORT_COUNT - 1))); do
  port=$((PORT_BASE + index))
  queue=$((index % QUEUE_COUNT))
  ethtool -N "${IFACE}" flow-type udp4 dst-port "${port}" action "${queue}" loc "${index}"
done

if command -v iptables >/dev/null 2>&1; then
  # Normalize upgrades to one current raw-table hook. Remove every retired
  # T510 receiver chain without encoding historical release names.
  while read -r legacy_chain; do
    while iptables -t raw -C PREROUTING -j "${legacy_chain}" 2>/dev/null; do
      iptables -t raw -D PREROUTING -j "${legacy_chain}"
    done
    iptables -t raw -F "${legacy_chain}"
    iptables -t raw -X "${legacy_chain}"
  done < <(
    iptables -t raw -S |
      awk '$1 == "-N" && $2 ~ /^T510_[[:alnum:]_]*_RX$/ && $2 != "T510_RX" { print $2 }'
  )

  iptables -t raw -N T510_RX 2>/dev/null || true
  while iptables -t raw -C PREROUTING -j T510_RX 2>/dev/null; do
    iptables -t raw -D PREROUTING -j T510_RX
  done
  iptables -t raw -F T510_RX
  iptables -t raw -A T510_RX -i "${IFACE}" -p udp --dport "${PORT_BASE}:$((PORT_BASE + PORT_COUNT - 1))" -j DROP
  iptables -t raw -I PREROUTING 1 -j T510_RX
fi

printf 'T510 RX tuning applied\n'
printf 'interface=%s mode=%s ports=%s..%s queues=%s rx_usecs=%s rx_frames=%s\n' \
  "${IFACE}" "${MODE}" "${PORT_BASE}" "$((PORT_BASE + PORT_COUNT - 1))" "${QUEUE_COUNT}" "${RX_USECS}" "${RX_FRAMES}"
ethtool -g "${IFACE}"
ethtool -c "${IFACE}"
ethtool -n "${IFACE}" 2>/dev/null || true
