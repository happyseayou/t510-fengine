#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="${T510_RX_TARGET:-astrolab@192.168.100.162}"
SSH_OPTS="${T510_RX_SSH_OPTS:-}"
STAGE="${ROOT}/build/stage35-explorer/latest"
REMOTE=/home/astrolab/.cache/t510/stage35-explorer-latest
case "${STAGE}" in "${ROOT}/build/stage35-explorer/latest") ;; *) exit 1;; esac
install -d "${STAGE}/helpers" "${STAGE}/static"
find "${STAGE}" -mindepth 1 -maxdepth 1 ! -name helpers ! -name static -exec rm -rf -- {} +
find "${STAGE}/helpers" -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
find "${STAGE}/static" -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
install -m 0755 "${ROOT}/scripts/stage-35/t510_stage35_simple_explorer.py" "${STAGE}/t510_stage35_explorer.py"
for file in t510_stage35_simple_math.py; do
  install -m 0644 "${ROOT}/scripts/${file}" "${STAGE}/helpers/${file}"
done
install -m 0644 "${ROOT}/scripts/stage-35/web/explorer/index.html" "${STAGE}/static/index.html"
install -m 0644 "${ROOT}/scripts/stage-35/web/explorer/app.css" "${STAGE}/static/app.css"
install -m 0644 "${ROOT}/scripts/stage-35/web/explorer/app.js" "${STAGE}/static/app.js"
install -d "${STAGE}/static/katex"
cp -a "${ROOT}/scripts/stage-35/web/explorer/katex/." "${STAGE}/static/katex/"
scp -q ${SSH_OPTS} "${TARGET}:/var/lib/t510/stage35/control/s2-report-v2-human-20260901-1652/plotly-4.0.0.min.js" "${STAGE}/static/plotly.min.js"
install -m 0644 "${ROOT}/scripts/stage-35/deploy/t510-stage35-explorer.service" "${STAGE}/t510-stage35-explorer.service"
install -m 0755 "${ROOT}/scripts/stage-35/deploy/install-stage35-explorer.sh" "${STAGE}/install-stage35-explorer.sh"
(cd "${STAGE}" && find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS)
ssh ${SSH_OPTS} "${TARGET}" "rm -rf -- '${REMOTE}' && mkdir -p '${REMOTE}'"
rsync -a -e "ssh ${SSH_OPTS}" "${STAGE}/" "${TARGET}:${REMOTE}/"
if [[ -n "${T510_RX_SUDO_PASSWORD:-}" ]]; then
  printf '%s\n' "${T510_RX_SUDO_PASSWORD}" | ssh ${SSH_OPTS} "${TARGET}" "sudo -S bash '${REMOTE}/install-stage35-explorer.sh' '${REMOTE}'"
elif ssh ${SSH_OPTS} "${TARGET}" "sudo -n true" >/dev/null 2>&1; then
  ssh ${SSH_OPTS} "${TARGET}" "sudo -n bash '${REMOTE}/install-stage35-explorer.sh' '${REMOTE}'"
else
  ssh -t ${SSH_OPTS} "${TARGET}" "sudo bash '${REMOTE}/install-stage35-explorer.sh' '${REMOTE}'"
fi
ssh ${SSH_OPTS} "${TARGET}" "rm -rf -- '${REMOTE}'"
