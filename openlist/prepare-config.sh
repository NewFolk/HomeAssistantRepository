#!/bin/sh
set -eu
umask 077

BASE_CONFIG="${1:-/data/config.json}"
OPTIONS_FILE="${2:-/data/options.json}"
RUNTIME_CONFIG="${3:-/data/.openlist-runtime.json}"
FILTER="${4:-/usr/local/lib/openlist-addon/config-overrides.jq}"

if [ ! -f "${OPTIONS_FILE}" ]; then
    OPTIONS_FILE=/dev/null
fi
PREVIOUS_CONFIG=/dev/null
if [ -s "${RUNTIME_CONFIG}" ]; then
    PREVIOUS_CONFIG="${RUNTIME_CONFIG}"
fi

# Write atomically. Keep both the persistent source and last valid runtime file
# unchanged if options are malformed. Never print configuration values/secrets.
temporary="$(mktemp "${RUNTIME_CONFIG}.XXXXXX")"
trap 'rm -f "${temporary}"' EXIT
if ! jq --exit-status --slurpfile options "${OPTIONS_FILE}" \
    --slurpfile previous "${PREVIOUS_CONFIG}" -f "${FILTER}" \
    "${BASE_CONFIG}" > "${temporary}"; then
    echo "[ERROR] Cannot apply HA OpenList settings; fix the add-on Configuration and restart" >&2
    exit 1
fi
mv "${temporary}" "${RUNTIME_CONFIG}"
echo "[INFO] OpenList configuration prepared from persistent settings and HA overrides"
