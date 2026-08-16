FROM docker.io/openlistteam/openlist:v4.2.5@sha256:3b9e56330ebf4aa40192e566bbbd79567591bb13c0ac252db02c41616cd75d1d

ARG BUILD_VERSION="1.2.1"
ARG BUILD_ARCH="amd64"

USER root

RUN apk add --no-cache jq nginx

COPY --chmod=0755 run.sh /usr/local/bin/openlist-addon
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
        http://127.0.0.1:8099/openlist/ || exit 1

ENTRYPOINT ["/usr/local/bin/openlist-addon"]
CMD []
