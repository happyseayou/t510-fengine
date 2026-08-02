#!/usr/bin/env bash
set -euo pipefail

# Post-process an export produced from the current demo-ant Vivado project.
# Synthesis/implementation must be run through the attached GUI MCP; this
# script never starts Vivado and never creates a second project.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_ID="${STAGE33_BUILD_ID:?set STAGE33_BUILD_ID to the exported build id}"
BUILD_ROOT="${ROOT}/build/stage33-vivado"
BUILD_DIR="${BUILD_ROOT}/${BUILD_ID}"
REPORT_ROOT="${ROOT}/reports/vivado/stage33"
REPORT_DIR="${REPORT_ROOT}/${BUILD_ID}"
OVERLAY_DIR="${BUILD_DIR}/overlay"

if [[ ! "${BUILD_ID}" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]]; then
  echo "invalid STAGE33_BUILD_ID: ${BUILD_ID}" >&2
  exit 2
fi

test -f "${OVERLAY_DIR}/t510_fengine.bit"
test -f "${OVERLAY_DIR}/t510_fengine.hwh"
test -f "${OVERLAY_DIR}/t510_fengine.tcl"
test -f "${OVERLAY_DIR}/t510_fengine_rfdc.xci"
test -f "${OVERLAY_DIR}/t510_fengine.manifest.txt"
test -d "${REPORT_DIR}"
grep -qx 'stage=33' "${OVERLAY_DIR}/t510_fengine.manifest.txt"
grep -qx 'core_version=0x00010033' "${OVERLAY_DIR}/t510_fengine.manifest.txt"
grep -qx 'project=demo-ant' "${OVERLAY_DIR}/t510_fengine.manifest.txt"

python3 "${ROOT}/scripts/stage33_verify_rfdc_artifacts.py" \
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

if [[ -e "${BUILD_ROOT}/latest" && ! -L "${BUILD_ROOT}/latest" ]]; then
  echo "refusing to replace non-symlink ${BUILD_ROOT}/latest" >&2
  exit 1
fi
if [[ -e "${REPORT_ROOT}/latest" && ! -L "${REPORT_ROOT}/latest" ]]; then
  echo "refusing to replace non-symlink ${REPORT_ROOT}/latest" >&2
  exit 1
fi
ln -sfn "${BUILD_DIR}" "${BUILD_ROOT}/latest"
ln -sfn "${REPORT_DIR}" "${REPORT_ROOT}/latest"
echo "Verified Stage 33 export from current project: ${OVERLAY_DIR}"
echo "Stage 33 reports: ${REPORT_DIR}"
