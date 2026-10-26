FROM postgres:16@sha256:9e2cf6287f25c3151f4c9421ccce2b17f3e60061c111a29165e0d2cdd9ff0a97

COPY docker/postgres/init/ /docker-entrypoint-initdb.d/
RUN sed -i 's/\r$//' /docker-entrypoint-initdb.d/*.sh \
    && chmod 0555 /docker-entrypoint-initdb.d/*.sh
