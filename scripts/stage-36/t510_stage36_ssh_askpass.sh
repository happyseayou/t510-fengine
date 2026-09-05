#!/bin/sh
# The lab-image credential stays in the process environment, never in this file.
test -n "${PYNQ_SUDO_PASSWORD:-}" || exit 1
printf '%s\n' "$PYNQ_SUDO_PASSWORD"
