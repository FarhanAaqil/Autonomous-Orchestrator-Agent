# Dockerfile for Isolated Browser Sandbox (Playwright)
# Enforces:
#   1. Non-root user (pwuser, uid 1001)
#   2. Read-only root filesystem compatible (/tmp ephemeral storage)
#   3. No host mounts or persistent session state
#   4. CPU and memory resource ceilings

FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

# The firewall initializer drops to this fixed, unprivileged numeric identity.
RUN (getent group 1001 || groupadd -g 1001 sandbox_runtime) && \
    (getent passwd 1001 || useradd -u 1001 -g 1001 -m sandbox_runtime) && \
    mkdir -p /app /tmp/playwright_cache /tmp/ephemeral_profile && \
    chown -R 1001:1001 /app /tmp/playwright_cache /tmp/ephemeral_profile

WORKDIR /app

# Install minimal server dependencies
COPY docker/browser_sandbox/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy server code
COPY docker/browser_sandbox/server.py docker/browser_sandbox/gateway.py /app/
COPY docker/browser_sandbox/entrypoint.sh /app/entrypoint.sh
RUN sed -i 's/\r$//' /app/entrypoint.sh && chmod 755 /app/entrypoint.sh
RUN apt-get update && apt-get install -y --no-install-recommends iptables util-linux && rm -rf /var/lib/apt/lists/*
RUN chown -R 1001:1001 /app

# Firewall setup runs as root; entrypoint drops all privileges before serving
USER root
ENTRYPOINT ["/app/entrypoint.sh"]

ENV PORT=8888 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    TEMP=/tmp \
    TMPDIR=/tmp

EXPOSE 8888

# Healthcheck
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8888/health')" || exit 1

# Launch lightweight RPC server
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8888", "--workers", "1"]
