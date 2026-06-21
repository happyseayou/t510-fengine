#!/usr/bin/env bash
set -euo pipefail

IFACE="${1:-ens2f0np0}"

if [[ "${IFACE}" == "enp4s0f2np2" ]]; then
  echo "Refusing to touch management interface ${IFACE}" >&2
  exit 2
fi

if [[ "$(id -u)" -eq 0 ]]; then
  SUDO=()
else
  SUDO=(sudo)
fi

if ! ip link show dev "${IFACE}" >/dev/null 2>&1; then
  echo "Interface ${IFACE} not found" >&2
  exit 1
fi

"${SUDO[@]}" ip link set dev "${IFACE}" mtu 9000
"${SUDO[@]}" ip link set dev "${IFACE}" up
"${SUDO[@]}" ip link set dev "${IFACE}" promisc on

for addr in 10.0.1.16/24 10.0.1.10/24 10.0.1.11/24; do
  if ! ip -4 addr show dev "${IFACE}" | grep -q "${addr%/*}"; then
    "${SUDO[@]}" ip addr add "${addr}" dev "${IFACE}"
  fi
done

if command -v ethtool >/dev/null 2>&1; then
  for feature in gro lro tso gso rx tx sg; do
    "${SUDO[@]}" ethtool -K "${IFACE}" "${feature}" off >/dev/null 2>&1 || true
  done
fi

echo "Configured ${IFACE}: MTU 9000, promisc on, IPs 10.0.1.16/24 10.0.1.10/24 10.0.1.11/24"
ip -br link show dev "${IFACE}"
ip -br addr show dev "${IFACE}"
