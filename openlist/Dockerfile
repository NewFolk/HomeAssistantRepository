FROM docker.io/openlistteam/openlist:v4.2.7@sha256:11b490123d57f88c84ecda46285e1921869cf511da3e5bb4062f183e7e1200b7

ARG BUILD_VERSION="1.4.0"
ARG BUILD_ARCH="amd64"

USER root

RUN apk add --no-cache jq nginx python3

COPY --chmod=0755 run.sh /usr/local/bin/openlist-addon
COPY --chmod=0755 prepare-config.sh /usr/local/bin/openlist-prepare-config
COPY config-overrides.jq /usr/local/lib/openlist-addon/config-overrides.jq
COPY ingress-auth.py /usr/local/lib/openlist-addon/ingress-auth.py
COPY nginx.conf /etc/nginx/openlist-ingress.conf.template

LABEL \
    io.hass.version="${BUILD_VERSION}" \
    io.hass.type="app" \
    io.hass.arch="${BUILD_ARCH}" \
    org.opencontainers.image.title="Home Assistant App: OpenList" \
    org.opencontainers.image.description="OpenList packaged for Home Assistant" \
    org.opencontainers.image.source="https://github.com/NewFolk/HomeAssistantRepository" \
    org.opencontainers.image.licenses="AGPL-3.0"

EXPOSE 5244 8099

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD wget --quiet --tries=1 --timeout=5 --output-document=/dev/null \
        http://127.0.0.1:5244/openlist/ && \
        wget --quiet --tries=1 --timeout=5 --output-document=/dev/null \
        http://127.0.0.1:8099/_openlist_health && \
        (! grep -q '^auth_request ' /tmp/openlist-ingress-auth.conf || \
        wget --quiet --tries=1 --timeout=5 --output-document=/dev/null \
        http://127.0.0.1:8098/health) || exit 1

ENTRYPOINT ["/usr/local/bin/openlist-addon"]
CMD []
