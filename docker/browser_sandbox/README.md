# Isolated browser reads

Run from the repository root:

    docker compose -f docker/browser_sandbox/docker-compose.sandbox.yml up --build -d

Set SANDBOX_BROWSER_URL=http://127.0.0.1:8888 for a host API process. For a
containerized API, attach it to the isolated network and use the browser service
name; never expose the gateway port publicly.

The browser has an internal Docker network and kernel OUTPUT rules allowing only
the read gateway. The gateway validates every URL, resolves public addresses, and
connects to that numeric address while preserving TLS hostname verification.
Private, metadata and nonstandard-port destinations are refused. Redirects are
bounded to five; each response and the aggregate browser page have byte limits.
IPv6 egress is disabled in this deployment.

Page JavaScript, service workers, forms and downloads are disabled. Screenshots
therefore render static content; this service does not support interactive sites.
Every resource is fulfilled by the gateway. No native browser request is continued.
POST/PUT/PATCH/DELETE are aborted and logged. GET endpoints with side effects
cannot be identified automatically; use domain allowlists for untrusted browsing.

Startup briefly needs NET_ADMIN to install firewall rules, then drops UID/GID to
1001 and all capabilities before starting the server. Missing firewall support
fails startup. Use the compose file; directly running server.py lacks this kernel
boundary and is unsupported for production.

A configured sandbox denial or outage propagates to the caller. Local reading is
development-only, explicitly enabled with SANDBOX_ALLOW_LOCAL=true; it uses the
same pinned HTTP transport, has no JavaScript and cannot take screenshots.

Offline regression checks:

    python scripts/test_local.py tests/test_phase1_network.py tests/test_browser_sandbox.py tests/test_tool_safety.py
    docker compose -f docker/browser_sandbox/docker-compose.sandbox.yml config --quiet

Container checks after building: inspect OUTPUT chains as root, verify the service
runs as UID 1001 with zero effective capabilities, and attempt sockets to a public
IP, private gateway and metadata from the browser container. Only the read gateway
may be reachable. The gateway must refuse private URLs and non-GET/HEAD methods.
Do not enable live external actions until deployment checks are recorded.
