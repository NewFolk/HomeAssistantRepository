#!/bin/sh
set -eu

OPENLIST_BIN="/opt/openlist/openlist"
NGINX_TEMPLATE="/etc/nginx/openlist-ingress.conf.template"
NGINX_CONFIG="/tmp/openlist-ingress.conf"
OPENLIST_PATH="/openlist"
OPENLIST_PID=""
NGINX_PID=""

# ShellCheck cannot infer that this function is invoked by the EXIT trap.
# shellcheck disable=SC2317
cleanup() {
    trap - EXIT INT TERM

    if [ -n "${NGINX_PID}" ]; then
        kill "${NGINX_PID}" >/dev/null 2>&1 || true
        wait "${NGINX_PID}" >/dev/null 2>&1 || true
    fi

    if [ -n "${OPENLIST_PID}" ]; then
        kill "${OPENLIST_PID}" >/dev/null 2>&1 || true
        wait "${OPENLIST_PID}" >/dev/null 2>&1 || true
    fi
}
trap cleanup EXIT
trap 'exit 0' INT TERM

resolve_ingress_entry() {
    if [ -n "${INGRESS_ENTRY:-}" ]; then
        printf '%s' "${INGRESS_ENTRY}"
        return
    fi

    if [ -z "${SUPERVISOR_TOKEN:-}" ]; then
        echo "[WARN] SUPERVISOR_TOKEN is unavailable; using the test Ingress path" >&2
        printf '%s' "/api/hassio_ingress/openlist-test"
        return
    fi

    addon_info="$(
        wget --quiet --output-document=- \
            --header="Authorization: Bearer ${SUPERVISOR_TOKEN}" \
            http://supervisor/addons/self/info
    )" || {
        echo "[ERROR] Failed to read the Ingress path from the Supervisor API" >&2
        exit 1
    }

    printf '%s' "${addon_info}" \
        | jq --exit-status --raw-output \
            '.data.ingress_entry | select(type == "string" and length > 0)'
}

if [ ! -x "${OPENLIST_BIN}" ]; then
    echo "[ERROR] OpenList executable was not found at ${OPENLIST_BIN}" >&2
    exit 1
fi

if [ ! -f "${NGINX_TEMPLATE}" ]; then
    echo "[ERROR] Nginx template was not found at ${NGINX_TEMPLATE}" >&2
    exit 1
fi

mkdir -p /data

if [ ! -w /data ]; then
    echo "[ERROR] OpenList data directory is not writable: /data" >&2
    exit 1
fi

INGRESS_ENTRY="$(resolve_ingress_entry)" || {
    echo "[ERROR] Could not determine the Home Assistant Ingress path" >&2
    exit 1
}

case "${INGRESS_ENTRY}" in
    /api/hassio_ingress/[A-Za-z0-9_-]*) ;;
    *)
        echo "[ERROR] Invalid Home Assistant Ingress path: ${INGRESS_ENTRY}" >&2
        exit 1
        ;;
esac

sed "s|%%INGRESS_ENTRY%%|${INGRESS_ENTRY}|g" \
    "${NGINX_TEMPLATE}" > "${NGINX_CONFIG}"
nginx -t -c "${NGINX_CONFIG}"

export SITE_URL="${OPENLIST_PATH}"

echo "[INFO] Starting OpenList on port 5244"
echo "[INFO] Starting Home Assistant Ingress proxy on port 8099"
echo "[INFO] Ingress entry: ${INGRESS_ENTRY}${OPENLIST_PATH}/"
echo "[INFO] Persistent application data: /data"

"${OPENLIST_BIN}" server --data /data --no-prefix --log-std &
OPENLIST_PID="$!"

nginx -c "${NGINX_CONFIG}" -g 'daemon off;' &
NGINX_PID="$!"

while kill -0 "${OPENLIST_PID}" >/dev/null 2>&1 \
    && kill -0 "${NGINX_PID}" >/dev/null 2>&1; do
    sleep 1
done

echo "[ERROR] OpenList or its Ingress proxy stopped unexpectedly" >&2
exit 1
