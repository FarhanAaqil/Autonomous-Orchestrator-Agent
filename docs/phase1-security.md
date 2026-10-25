# Action security contract

The service currently supports a single trusted owner. All API credentials represent that owner; multi-user isolation is not offered.

Production and staging require an AUTH_TOKEN of at least 32 characters and an independent, strong EXECUTOR_HMAC_SECRET. Generate both with a cryptographically secure secret generator. Startup rejects absent or known development secrets. Development without authentication requires ALLOW_INSECURE_LOCAL=true and must bind only to loopback.

ACTION_EXECUTION_MODE defaults to disabled. Simulation must be explicitly selected. Live execution requires ENABLE_REAL_EMAIL=true and SMTP credentials; other provider adapters are unavailable and cannot be approved. Never enable live actions as part of automated tests.

The health endpoint, UI bootstrap and generated API documentation are public. API data and administrative circuit controls require the owner credential. Browser session integration is completed in Phase 3; secured API clients must send the Authorization bearer header.
