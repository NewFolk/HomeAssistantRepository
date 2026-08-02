#!/usr/bin/env bash
set -Eeuo pipefail

IMAGE="${1:-local/openlist-addon:test}"
EXPECTED_VERSION="${2:-v4.2.2}"
CONTAINER="openlist-addon-smoke-$$"
DATA_DIR="$(mktemp -d)"
HOST_PORT=""

cleanup() {
    docker rm --force "${CONTAINER}" >/dev/null 2>&1 || true
    rm -rf "${DATA_DIR}"
}
trap cleanup EXIT

show_diagnostics() {
    docker inspect "${CONTAINER}" || true
    docker logs "${CONTAINER}" || true
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
                "http://127.0.0.1:${HOST_PORT}/" >/dev/null
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
        --publish 127.0.0.1::5244 \
        --volume "${DATA_DIR}:/data" \
        "${IMAGE}" >/dev/null
    HOST_PORT="$(
        docker inspect \
            --format '{{(index (index .NetworkSettings.Ports "5244/tcp") 0).HostPort}}' \
            "${CONTAINER}"
    )"
    wait_until_healthy
}

version_output="$(
    docker run --rm \
        --platform linux/amd64 \
        --entrypoint /opt/openlist/openlist \
        "${IMAGE}" version
)"
grep --fixed-strings "Version: ${EXPECTED_VERSION}" <<<"${version_output}"

start_container
test -s "${DATA_DIR}/config.json"
test -e "${DATA_DIR}/data.db"
config_checksum="$(sha256sum "${DATA_DIR}/config.json" | cut -d ' ' -f 1)"

docker rm --force "${CONTAINER}" >/dev/null
start_container

test "$(sha256sum "${DATA_DIR}/config.json" | cut -d ' ' -f 1)" = "${config_checksum}"
test -e "${DATA_DIR}/data.db"
