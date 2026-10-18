#!/bin/sh
set -eu
umask 077

BASE_CONFIG="${1:-/data/config.json}"
OPTIONS_FILE="${2:-/data/options.json}"
RUNTIME_CONFIG="${3:-/data/.openlist-runtime.json}"
FILTER="${4:-/usr/local/lib/openlist-addon/config-overrides.jq}"
PARSER="${5:-/usr/local/lib/openlist-addon/parse-options.py}"

if [ ! -f "${OPTIONS_FILE}" ]; then
    OPTIONS_FILE=/dev/null
fi
PREVIOUS_CONFIG=/dev/null
if [ -s "${RUNTIME_CONFIG}" ] \
    && jq --exit-status 'type == "object"' "${RUNTIME_CONFIG}" >/dev/null 2>&1; then
    PREVIOUS_CONFIG="${RUNTIME_CONFIG}"
fi

# Write atomically. Keep both the persistent source and last valid runtime file
# unchanged if options are malformed. Never print configuration values/secrets.
temporary="$(mktemp "${RUNTIME_CONFIG}.XXXXXX")"
normalized="$(mktemp "${RUNTIME_CONFIG}.options.XXXXXX")"
trap 'rm -f "${temporary}" "${normalized}"' EXIT
python3 "${PARSER}" "${OPTIONS_FILE}" > "${normalized}"
if ! jq --exit-status --slurpfile options "${normalized}" \
    --slurpfile previous "${PREVIOUS_CONFIG}" -f "${FILTER}" \
    "${BASE_CONFIG}" > "${temporary}"; then
    echo "[ERROR] Cannot apply HA OpenList settings; fix the add-on Configuration and restart" >&2
    exit 1
fi
mv "${temporary}" "${RUNTIME_CONFIG}"
echo "[INFO] HA OpenList YAML parsed; working configuration prepared (verification pending)"
