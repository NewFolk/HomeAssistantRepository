#!/bin/sh
set -eu

OPENLIST_BIN="/opt/openlist/openlist"

if [ ! -x "${OPENLIST_BIN}" ]; then
    echo "[ERROR] OpenList executable was not found at ${OPENLIST_BIN}" >&2
    exit 1
fi

mkdir -p /data

if [ ! -w /data ]; then
    echo "[ERROR] OpenList data directory is not writable: /data" >&2
    exit 1
fi

echo "[INFO] Starting OpenList on port 5244"
echo "[INFO] Persistent application data: /data"

exec "${OPENLIST_BIN}" server --data /data --no-prefix --log-std
