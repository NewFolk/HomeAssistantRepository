#!/usr/bin/env bash
set -Eeuo pipefail

IMAGE="${1:-local/openlist-addon:test}"
EXPECTED_VERSION="${2:?Expected OpenList version is required as the second argument}"
INGRESS_ENTRY="/api/hassio_ingress/test-token"
CONTAINER="openlist-addon-smoke-$$"
DATA_DIR="$(mktemp -d)"
DIRECT_HOST_PORT=""

cleanup() {
    docker rm --force "${CONTAINER}" >/dev/null 2>&1 || true
    docker run --rm \
        --platform linux/amd64 \
        --entrypoint /bin/sh \
        --volume "${DATA_DIR}:/data" \
        "${IMAGE}" \
        -c 'rm -rf /data/* /data/.[!.]* /data/..?*' \
        >/dev/null 2>&1 || true
    rmdir "${DATA_DIR}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

show_diagnostics() {
    docker inspect "${CONTAINER}" || true
    docker logs "${CONTAINER}" || true
}

source_checksum() {
    docker run --rm --platform linux/amd64 --entrypoint sha256sum \
        --volume "${DATA_DIR}:/data:ro" "${IMAGE}" /data/config.json \
        | cut -d ' ' -f 1
}

wait_until_healthy() {
    local running
    local status

    for _ in {1..60}; do
        running="$(docker inspect --format '{{.State.Running}}' "${CONTAINER}")"
        status="$(docker inspect --format '{{.State.Health.Status}}' "${CONTAINER}")"

        if [[ "${running}" != "true" ]]; then
            echo "Container stopped before becoming healthy" >&2
            show_diagnostics
            return 1
        fi

        if [[ "${status}" == "healthy" ]]; then
            curl --fail --silent --show-error --max-time 5 \
                "http://127.0.0.1:${DIRECT_HOST_PORT}/openlist/" >/dev/null
            return 0
        fi

        sleep 2
    done

    echo "Container did not become healthy within 120 seconds" >&2
    show_diagnostics
    return 1
}

start_container() {
    docker run --detach \
        --name "${CONTAINER}" \
        --platform linux/amd64 \
        --env "INGRESS_ENTRY=${INGRESS_ENTRY}" \
        --publish 127.0.0.1::5244 \
        --volume "${DATA_DIR}:/data" \
        "${IMAGE}" >/dev/null
    DIRECT_HOST_PORT="$(
        docker inspect \
            --format '{{(index (index .NetworkSettings.Ports "5244/tcp") 0).HostPort}}' \
            "${CONTAINER}"
    )"
    wait_until_healthy
}

test_ingress() {
    local asset_path
    local backend_asset_path
    local ingress_html
    local ingress_manifest

    ingress_html="$(
        docker exec "${CONTAINER}" \
            wget --quiet --output-document=- \
                http://127.0.0.1:8099/openlist/
    )"

    grep --quiet --fixed-strings \
        "base_path: '${INGRESS_ENTRY}/openlist'" <<<"${ingress_html}"
    grep --quiet --fixed-strings \
        "cdn: '${INGRESS_ENTRY}/openlist'" <<<"${ingress_html}"

    asset_path="$(
        grep --max-count=1 --only-matching --extended-regexp \
            "/assets/[A-Za-z0-9._/-]+\\.js" \
            <<<"${ingress_html}"
    )"
    test -n "${asset_path}"
    backend_asset_path="/openlist${asset_path}"

    docker exec "${CONTAINER}" \
        wget --quiet --output-document=/dev/null \
            "http://127.0.0.1:8099${backend_asset_path}"
    docker exec "${CONTAINER}" \
        wget --quiet --output-document=/dev/null \
            http://127.0.0.1:8099/openlist/api/public/settings
    ingress_manifest="$(
        docker exec "${CONTAINER}" \
            wget --quiet --output-document=- \
                http://127.0.0.1:8099/openlist/manifest.json
    )"
    grep --quiet --fixed-strings \
        "\"start_url\":\"${INGRESS_ENTRY}/openlist\"" \
        <<<"${ingress_manifest}"
}

version_output="$(
    docker run --rm \
        --platform linux/amd64 \
        --entrypoint /opt/openlist/openlist \
        "${IMAGE}" version
)"
if ! grep --quiet --fixed-strings "Version: ${EXPECTED_VERSION}" <<<"${version_output}"; then
    echo "Expected OpenList ${EXPECTED_VERSION}, but the image reported:" >&2
    printf '%s\n' "${version_output}" >&2
    exit 1
fi

start_container
test_ingress
test -s "${DATA_DIR}/config.json"
test -e "${DATA_DIR}/data.db"

expect_startup_failure() {
    local expected_message="$1"
    local stopped=false
    local failure_log
    docker rm --force "${CONTAINER}" >/dev/null
    docker run --detach --name "${CONTAINER}" --platform linux/amd64 \
        --env "INGRESS_ENTRY=${INGRESS_ENTRY}" \
        --volume "${DATA_DIR}:/data" "${IMAGE}" >/dev/null
    for _ in {1..30}; do
        if [[ "$(docker inspect --format '{{.State.Running}}' "${CONTAINER}")" == false ]]; then
            stopped=true
            break
        fi
        sleep 1
    done
    test "${stopped}" = true
    test "$(docker inspect --format '{{.State.ExitCode}}' "${CONTAINER}")" != 0
    failure_log="$(docker logs "${CONTAINER}" 2>&1)"
    grep --quiet --fixed-strings "${expected_message}" <<<"${failure_log}"
    test "$(source_checksum)" = "${config_checksum}"
}
config_checksum="$(source_checksum)"

# Reuse the populated data directory across recreated containers. HA options
# must affect the running application, but not overwrite the persistent source.
docker exec "${CONTAINER}" sh -c \
    'printf "%s\n" '\''{"openlist":"tasks:\n  copy:\n    task_persistant: true\ntoken_expires_in: 168\n"}'\'' > /data/options.json'
docker rm --force "${CONTAINER}" >/dev/null
start_container
test_ingress
docker exec "${CONTAINER}" jq --exit-status \
    '.tasks.copy.task_persistant == true and .token_expires_in == 168' \
    /data/.openlist-runtime.json >/dev/null
test "$(source_checksum)" = "${config_checksum}"

docker exec "${CONTAINER}" sh -c 'printf "%s\n" '\''{"openlist":"{}"}'\'' > /data/options.json'
docker rm --force "${CONTAINER}" >/dev/null
start_container
test_ingress
docker exec "${CONTAINER}" jq --exit-status \
    '.tasks.copy.task_persistant == false and .token_expires_in == 48' \
    /data/.openlist-runtime.json >/dev/null
test "$(source_checksum)" = "${config_checksum}"
test -e "${DATA_DIR}/data.db"

docker exec "${CONTAINER}" sh -c 'printf "%s\n" '\''{"openlist":"site_url: /wrong"}'\'' > /data/options.json'
expect_startup_failure 'openlist.site_url is managed by the HA add-on'
docker run --rm --platform linux/amd64 --entrypoint /bin/sh \
    --volume "${DATA_DIR}:/data" "${IMAGE}" -c \
    'printf "%s\n" '\''{"openlist":"tasks:\n  copy:\n    task_persistant: not-a-boolean"}'\'' > /data/options.json'
expect_startup_failure 'load config error'
