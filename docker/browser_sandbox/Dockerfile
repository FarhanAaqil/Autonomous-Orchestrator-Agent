# Dockerfile for Isolated Browser Sandbox (Playwright)
# Enforces:
#   1. Non-root user (pwuser, uid 1001)
#   2. Read-only root filesystem compatible (/tmp ephemeral storage)
#   3. No host mounts or persistent session state
#   4. CPU and memory resource ceilings

FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

# Create non-root user
RUN useradd -u 1001 -m -s /bin/bash pwuser && \
    mkdir -p /app /tmp/playwright_cache /tmp/ephemeral_profile && \
    chown -R pwuser:pwuser /app /tmp/playwright_cache /tmp/ephemeral_profile

WORKDIR /app

# Install minimal server dependencies
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy server code
COPY server.py security.py /app/
RUN chown -R pwuser:pwuser /app

# Switch to non-root user
USER pwuser

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
