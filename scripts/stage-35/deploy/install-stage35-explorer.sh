#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "install-stage35-explorer.sh must run as root" >&2
  exit 1
fi
SOURCE="${1:?usage: install-stage35-explorer.sh STAGED_RELEASE}"
[[ "$#" -eq 1 ]] || { echo "usage: install-stage35-explorer.sh STAGED_RELEASE" >&2; exit 2; }
ROOT=/opt/t510-stage35-explorer
CANDIDATE="${ROOT}/candidate"
CANDIDATE_NEXT="${ROOT}/.candidate.next"
for target in "${CANDIDATE}" "${CANDIDATE_NEXT}"; do
  case "${target}" in
    /opt/t510-stage35-explorer/candidate|/opt/t510-stage35-explorer/.candidate.next) ;;
    *) echo "refusing unsafe explorer candidate target ${target}" >&2; exit 1 ;;
  esac
done
test -f "${SOURCE}/SHA256SUMS"
test -x "${SOURCE}/t510_stage35_explorer.py"
test -f "${SOURCE}/static/index.html"
(cd "${SOURCE}" && sha256sum -c SHA256SUMS)
install -d -m 0755 "${ROOT}"
rm -rf -- "${CANDIDATE_NEXT}"
cp -aL "${SOURCE}" "${CANDIDATE_NEXT}"
chown -R root:root "${CANDIDATE_NEXT}"
chmod -R a-w "${CANDIDATE_NEXT}"
chmod 0555 "${CANDIDATE_NEXT}/t510_stage35_explorer.py"
rm -rf -- "${CANDIDATE}"
mv -T -- "${CANDIDATE_NEXT}" "${CANDIDATE}"
# Keep current code, current data, and port 8035 untouched.  The formal queue
# validates this candidate on 8036 before it performs an atomic swap.
echo "Installed Stage 35 simple explorer candidate without changing port 8035"
