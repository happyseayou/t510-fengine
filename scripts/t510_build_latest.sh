#!/usr/bin/env bash
set -euo pipefail

# Verify the latest export produced from the current demo-ant Vivado project,
# then atomically replace the repository-level current overlay. This script
# never starts Vivado and intentionally keeps no candidate or rollback tree.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="${ROOT}/build/vivado/latest"
REPORT_DIR="${BUILD_DIR}/reports"
OVERLAY_DIR="${BUILD_DIR}/overlay"
CURRENT_OVERLAY="${ROOT}/overlay"
METADATA="${ROOT}/config/t510/current_release.json"
CATALOG="${ROOT}/config/t510/config.example.json"

if [[ "$#" -ne 0 ]]; then
  echo "usage: t510_build_latest.sh" >&2
  exit 2
fi

test -f "${OVERLAY_DIR}/t510_fengine.bit"
test -f "${OVERLAY_DIR}/t510_fengine.hwh"
test -f "${OVERLAY_DIR}/t510_fengine.tcl"
test -f "${OVERLAY_DIR}/t510_fengine_rfdc.xci"
test -f "${OVERLAY_DIR}/t510_fengine.manifest.txt"
test -d "${REPORT_DIR}"
grep -qx 'release=latest' "${OVERLAY_DIR}/t510_fengine.manifest.txt"
grep -qx 'project=demo-ant' "${OVERLAY_DIR}/t510_fengine.manifest.txt"

python3 "${ROOT}/scripts/t510_current_release.py" \
  --metadata "${METADATA}" --catalog "${CATALOG}" \
  --bitstream "${OVERLAY_DIR}/t510_fengine.bit" --allow-unqualified >/dev/null

python3 "${ROOT}/scripts/t510_verify_rfdc_artifacts.py" \
  --xci "${OVERLAY_DIR}/t510_fengine_rfdc.xci" \
  --hwh "${OVERLAY_DIR}/t510_fengine.hwh" \
  > "${REPORT_DIR}/rfdc_artifact_verification.json"

(
  cd "${OVERLAY_DIR}"
  sha256sum \
    t510_fengine.bit \
    t510_fengine.hwh \
    t510_fengine.tcl \
    t510_fengine_rfdc.xci \
    t510_fengine.manifest.txt
) > "${REPORT_DIR}/artifact_sha256.txt"

NEXT_OVERLAY="$(mktemp -d "${ROOT}/.overlay.next.XXXXXX")"
case "${NEXT_OVERLAY}" in
  "${ROOT}"/.overlay.next.*) ;;
  *) echo "refusing unsafe temporary overlay path: ${NEXT_OVERLAY}" >&2; exit 1 ;;
esac
trap 'rm -rf -- "${NEXT_OVERLAY}"' EXIT
cp -a "${OVERLAY_DIR}/." "${NEXT_OVERLAY}/"

rm -rf -- "${CURRENT_OVERLAY}"
mv -- "${NEXT_OVERLAY}" "${CURRENT_OVERLAY}"
NEXT_OVERLAY="${ROOT}/.overlay.next.completed"

echo "Verified latest export and updated current overlay: ${CURRENT_OVERLAY}"
echo "Current build reports: ${REPORT_DIR}"
