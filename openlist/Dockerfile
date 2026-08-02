FROM docker.io/openlistteam/openlist:v4.2.2@sha256:e518d69feb6a2ee7a0db7c4c9a5111e0ab155ec81b7654e39ca917f5678ce0f5

ARG BUILD_VERSION="1.1.0"
ARG BUILD_ARCH="amd64"

USER root

COPY --chmod=0755 run.sh /usr/local/bin/openlist-addon

LABEL \
    io.hass.version="${BUILD_VERSION}" \
    io.hass.type="app" \
    io.hass.arch="${BUILD_ARCH}" \
    org.opencontainers.image.title="Home Assistant App: OpenList" \
    org.opencontainers.image.description="OpenList packaged for Home Assistant" \
    org.opencontainers.image.source="https://github.com/NewFolk/HomeAssistantRepository" \
    org.opencontainers.image.licenses="AGPL-3.0"

EXPOSE 5244

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD wget --quiet --tries=1 --timeout=5 --output-document=/dev/null \
        http://127.0.0.1:5244/ || exit 1

ENTRYPOINT ["/usr/local/bin/openlist-addon"]
CMD []
