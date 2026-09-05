#!/usr/bin/env bash
set -euo pipefail

user_units=(
  snap.firmware-updater.firmware-notifier.service
  snap.firmware-updater.firmware-notifier.timer
)
export XDG_RUNTIME_DIR="/run/user/$(id -u)"
export DBUS_SESSION_BUS_ADDRESS="unix:path=${XDG_RUNTIME_DIR}/bus"

cleanup() {
  systemctl --user unmask --runtime "${user_units[@]}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

# This notifier was in a permanent 25 s crash/restart loop and coincided with
# both formal C receive-ring stalls.  The runtime mask is automatically removed
# when this bounded recovery queue exits, successfully or otherwise.
systemctl --user mask --runtime --now "${user_units[@]}"
sudo -n systemctl stop fwupd.service packagekit.service >/dev/null 2>&1 || true

"$@"
