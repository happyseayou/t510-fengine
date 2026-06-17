#!/usr/bin/env bash
set -euo pipefail

IFACE_FILE="${IFACE_FILE:-/etc/network/interfaces.d/eth0}"
MAC="${T510_ETH0_MAC:-}"
APPLY_NOW=0

usage() {
  cat <<'EOF'
Usage:
  sudo scripts/pynq_fix_management_mac.sh [--mac 02:51:10:xx:yy:zz] [--apply-now]

Fix the PYNQ management eth0 MAC before DHCP by adding:
  hwaddress ether <mac>
under /etc/network/interfaces.d/eth0.

Default MAC is derived from /etc/machine-id with a locally administered
T510 prefix. The script creates a timestamped backup and does not cycle the
network interface unless --apply-now is given.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mac)
      MAC="${2:-}"
      shift 2
      ;;
    --apply-now)
      APPLY_NOW=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run with sudo on the PYNQ board." >&2
  exit 1
fi

if [[ -z "$MAC" ]]; then
  if [[ ! -r /etc/machine-id ]]; then
    echo "No --mac provided and /etc/machine-id is not readable." >&2
    exit 1
  fi
  MAC="$(python3 - <<'PY'
import hashlib
mid = open('/etc/machine-id', 'r', encoding='ascii').read().strip()
h = hashlib.sha256(mid.encode('ascii')).digest()
print(':'.join(['02', '51', '10'] + [f'{b:02x}' for b in h[:3]]))
PY
)"
fi

if ! [[ "$MAC" =~ ^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$ ]]; then
  echo "Invalid MAC address: $MAC" >&2
  exit 1
fi

first_octet=$((16#${MAC%%:*}))
if (( (first_octet & 1) != 0 )); then
  echo "Invalid unicast MAC address: $MAC" >&2
  exit 1
fi

if [[ ! -f "$IFACE_FILE" ]]; then
  echo "Interface config not found: $IFACE_FILE" >&2
  exit 1
fi

backup_dir="/etc/network/stage18-backups"
mkdir -p "$backup_dir"
backup="${backup_dir}/$(basename "$IFACE_FILE").stage18-$(date -u +%Y%m%dT%H%M%SZ).bak"
cp -a "$IFACE_FILE" "$backup"

python3 - "$IFACE_FILE" "$MAC" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
mac = sys.argv[2].lower()
lines = path.read_text().splitlines()
out = []
inserted = False

for line in lines:
    stripped = line.strip()
    if stripped.startswith('hwaddress '):
        continue
    out.append(line)
    if stripped == 'iface eth0 inet dhcp':
        out.append(f'    hwaddress ether {mac}')
        inserted = True

if not inserted:
    if out and out[-1].strip():
        out.append('')
    out.extend(['auto eth0', 'iface eth0 inet dhcp', f'    hwaddress ether {mac}'])

path.write_text('\n'.join(out) + '\n')
PY

echo "Configured stable eth0 MAC: $MAC"
echo "Backup: $backup"
echo "Updated: $IFACE_FILE"

if [[ "$APPLY_NOW" -eq 1 ]]; then
  echo "Cycling eth0 now; SSH/Jupyter may disconnect."
  ifdown eth0 || true
  ip link set dev eth0 address "$MAC"
  ifup eth0
  ip -br addr show eth0 || true
else
  echo "Not cycling eth0. Reboot or run with --apply-now when ready."
fi
