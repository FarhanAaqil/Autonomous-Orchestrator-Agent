# Dockerized Browser Sandbox (Phase 9)

## Architecture Overview
The Browser Sandbox provides an isolated, ephemeral web browsing environment powered by headless Chromium and Playwright. It enables agents (such as `linkedin_agent` and `career_agent`) to inspect web pages, professional profiles, and job postings without exposing host network boundaries, cookies, or secrets.

## Security Invariants
1. **Non-Root Execution**: Runs strictly as user `pwuser` (`uid=1001:gid=1001`).
2. **Read-Only Root Filesystem**: The container root filesystem is mounted read-only (`read_only: true`). All temporary files use tmpfs in `/tmp` (`size=512m,noexec,nosuid`).
3. **No Host Mounts**: Zero host volumes are mounted into the container.
4. **Ephemeral Profiles**: Every page navigation uses a fresh browser context (`browser.new_context()`) which is immediately closed. Cookies, local storage, and history are discarded after each request.
5. **SSRF Guard**: Blocks access to `localhost`, loopback, RFC 1918 private subnets, cloud metadata (`169.254.169.254`), and internal service discovery.
6. **Scheme Lockdown**: Only `http://` and `https://` are permitted. All dangerous schemes (`file://`, `data:`, `about:`, `chrome://`, `javascript:`) are rejected.
7. **Resource Ceilings**: CPU limit capped at 1.0 core, RAM capped at 1024 MB.
8. **Read-Only Default**: Form submissions and state-mutating browser interactions are prohibited. Real-world actions must pass through `propose_action` into human approval gates.

## Running the Container
```bash
# Build and run the sandbox container
docker compose -f docker/browser_sandbox/docker-compose.sandbox.yml up -d

# Verify health status
curl http://127.0.0.1:8888/health
```

## Environment Configuration
Set `SANDBOX_BROWSER_URL` in your environment to point orchestrator tools to the container:
```bash
export SANDBOX_BROWSER_URL=http://127.0.0.1:8888
```
When `SANDBOX_BROWSER_URL` is omitted, the `SandboxBrowserClient` uses the local in-process Playwright driver with identical security checks and ephemeral lifecycle.
