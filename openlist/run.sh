#!/bin/sh
set -eu

OPENLIST_BIN="/opt/openlist/openlist"
NGINX_TEMPLATE="/etc/nginx/openlist-ingress.conf.template"
NGINX_CONFIG="/tmp/openlist-ingress.conf"
OPENLIST_PID=""
NGINX_PID=""
AUTH_PID=""

# ShellCheck cannot infer that this function is invoked by the EXIT trap.
# shellcheck disable=SC2317
cleanup() {
    trap - EXIT INT TERM

    if [ -n "${AUTH_PID}" ]; then
        kill "${AUTH_PID}" >/dev/null 2>&1 || true
        wait "${AUTH_PID}" >/dev/null 2>&1 || true
    fi

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

echo "[INFO] OpenList Home Assistant add-on ${OPENLIST_ADDON_VERSION:-unknown}"

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

# Validate options before any first-run initialization. An empty base is enough
# for wrapper validation; upstream remains responsible for OpenList field types.
if [ ! -f /data/config.json ]; then
    printf '{}\n' > /tmp/openlist-empty-config.json
    /usr/local/bin/openlist-prepare-config /tmp/openlist-empty-config.json
    echo "[INFO] Initializing persistent OpenList configuration"
    "${OPENLIST_BIN}" admin --data /data --log-std
    chmod 600 /data/config.json
fi
/usr/local/bin/openlist-prepare-config
python3 /usr/local/lib/openlist-addon/ingress-auth.py configure
ingress_auto_login="$(jq -r '.ingress_auto_login // false' /data/options.json 2>/dev/null || printf false)"

INGRESS_ENTRY="$(resolve_ingress_entry)" || {
    echo "[ERROR] Could not determine the Home Assistant Ingress path" >&2
    exit 1
}

case "${INGRESS_ENTRY}" in
    /api/hassio_ingress/*)
        ingress_token="${INGRESS_ENTRY#/api/hassio_ingress/}"
        case "${ingress_token}" in
            ""|*[!A-Za-z0-9_-]*)
                echo "[ERROR] Supervisor returned an invalid Ingress token" >&2
                exit 1
                ;;
        esac
        ;;
    *)
        echo "[ERROR] Supervisor returned an invalid Ingress path" >&2
        exit 1
        ;;
esac

sed "s|%%INGRESS_ENTRY%%|${INGRESS_ENTRY}|g" \
    "${NGINX_TEMPLATE}" > "${NGINX_CONFIG}"
nginx -t -c "${NGINX_CONFIG}"

echo "[INFO] Starting OpenList on port 5244"
echo "[INFO] Home Assistant Ingress path configured"
echo "[INFO] Persistent application data: /data"

"${OPENLIST_BIN}" server --data /data --config /data/.openlist-runtime.json --no-prefix --log-std &
OPENLIST_PID="$!"

# InitConfig rewrites the working JSON using upstream's typed configuration,
# dropping unknown fields. Do not check our own pre-merge output as proof that
# OpenList recognized an override. Delay Ingress until upstream is ready.
while ! wget --quiet --tries=1 --timeout=1 --output-document=/dev/null \
    http://127.0.0.1:5244/openlist/ping; do
    if ! kill -0 "${OPENLIST_PID}" >/dev/null 2>&1; then
        echo "[ERROR] OpenList stopped before HA override verification" >&2
        exit 1
    fi
    sleep 1
done
verification_options=/data/options.json
if [ ! -f "${verification_options}" ]; then
    verification_options=/dev/null
fi
python3 /usr/local/lib/openlist-addon/parse-options.py "${verification_options}" \
    --verify /data/.openlist-runtime.json

if [ "${ingress_auto_login}" = true ]; then
    echo "[INFO] Ingress auto-login enabled for Home Assistant administrators only"
    python3 /usr/local/lib/openlist-addon/ingress-auth.py serve &
    AUTH_PID="$!"
else
    echo "[INFO] Ingress auto-login disabled; using native OpenList authentication"
fi

echo "[INFO] Starting Home Assistant Ingress proxy on port 8099"
nginx -c "${NGINX_CONFIG}" -g 'daemon off;' &
NGINX_PID="$!"

while kill -0 "${OPENLIST_PID}" >/dev/null 2>&1 \
    && kill -0 "${NGINX_PID}" >/dev/null 2>&1; do
    if [ -n "${AUTH_PID}" ] && ! kill -0 "${AUTH_PID}" >/dev/null 2>&1; then
        echo "[ERROR] Ingress authentication helper stopped unexpectedly" >&2
        exit 1
    fi
    sleep 1
done

echo "[ERROR] OpenList or its Ingress proxy stopped unexpectedly" >&2
exit 1
