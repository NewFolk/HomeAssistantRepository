ARG BUILD_FROM
FROM ${BUILD_FROM}

COPY run.sh /usr/local/bin/openlist-addon

RUN chmod 0755 /usr/local/bin/openlist-addon

EXPOSE 5244

ENTRYPOINT ["/usr/local/bin/openlist-addon"]

