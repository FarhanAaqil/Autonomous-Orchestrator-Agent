# Action security contract

The service currently supports a single trusted owner. All API credentials represent that owner; multi-user isolation is not offered.

Production and staging require an AUTH_TOKEN of at least 32 characters and an independent, strong EXECUTOR_HMAC_SECRET. Generate both with a cryptographically secure secret generator. Startup rejects absent or known development secrets. Development without authentication requires ALLOW_INSECURE_LOCAL=true and must bind only to loopback.

ACTION_EXECUTION_MODE defaults to disabled. Simulation must be explicitly selected. Live execution requires ENABLE_REAL_EMAIL=true and SMTP credentials; other provider adapters are unavailable and cannot be approved. Never enable live actions as part of automated tests.

The health endpoint, UI bootstrap and generated API documentation are public. API data and administrative circuit controls require the owner credential. Browser session integration is completed in Phase 3; secured API clients must send the Authorization bearer header.
# Runtime policy

This deployment has one owner authenticated by its bearer token. Every execution
entry point checks the global kill switch and agent enable flag. The kill switch
stops new dispatches, jobs, pipeline steps, scheduled handlers, proposals and
approved actions. It cannot recall a provider request already in flight.
Read-only inspection and rejection remain available. Proposals carry their source
agent and conversation so execution can recheck the originating agent's policy.


## Execution outcomes and recovery

ACTION_EXECUTION_MODE defaults to disabled. Simulation requires an explicit
setting and records simulated, never delivery. Live SMTP reports submitted after
server acceptance. Confirmed requires independent owner evidence; SMTP acceptance
alone cannot prove inbox delivery. Missing credentials and pre-send failures
record failed. Transport uncertainty records outcome_unknown.

Every attempt stores a stable correlation key and receipt/error class. SMTP has no
provider deduplication guarantee: Message-ID is only a correlation identifier.
Neither failed nor uncertain attempts can be replayed. Inspect GET
/approvals/{id}/attempts and the audit trail. After checking provider evidence,
POST /approvals/{id}/reconcile with outcome confirmed or failed and an evidence
description. For an interrupted process, stop that executor and wait five minutes
before reconciling. Reconciliation never sends anything. A new action requires a
new review; investigate uncertain delivery before proposing another.

Back up SQLite before upgrading. The migration preserves proposal IDs, links and
audit rows while extending status constraints. Old signed approvals must be
edited and reviewed again because the signature now binds origin and expiry.
Rollback requires restoring the pre-upgrade backup; do not run old binaries
against a database containing the new terminal states.

## Review integrity

The reviewed hash includes the execution mode. The signature also binds the source
agent, conversation, expiration and mode. Changing from simulation to live requires
a new review; a previously reviewed simulation cannot become a live send.
Missing email recipients and repository identifiers are clarification requests,
not fabricated targets. Direct producers emit the same catalog payloads as jobs.

## Local verification (2026-10-25)

- Full isolated suite: 302 passed (python scripts/test_local.py tests).
- Ruff passed for orchestrator_core, tests, scripts/test_local.py and browser sandbox.
- git diff --check passed.
- Sandbox Compose configuration validated successfully.
- SMTP and provider failure tests use fakes; no real email or model calls were made.
- No dependency advisory metadata was sent to external services.

Deployment validation is still pending. Docker Desktop was started successfully,
but the required Playwright/gateway images are not cached locally. No images or
packages were downloaded for this audit. Kernel firewall and real browser tests
have not been run; unit tests exercise the gateway and transport with fakes.
The frontend build was attempted and stopped because local tsc is unavailable.
Do not treat these local test results as production or browser certification.
