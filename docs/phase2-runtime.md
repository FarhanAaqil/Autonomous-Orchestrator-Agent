# Phase 2 implementation and local verification

Recorded 2026-10-26. Backend implementation is in place and the focused checks
passed. This is not a production-release certification: the complete suite,
independent security review, hostile process-death matrix and load objectives
remain Phase 4 work.

## Local deployment

Run `docker compose up -d` from the repository root. The API is available at
http://127.0.0.1:8080. PostgreSQL binds only to 127.0.0.1:5432. The API, worker
and scheduler use the restricted application role; the one-shot migration
service uses a separate schema owner. Runtime startup rejects administrative
database roles and mismatched schema versions.

The existing SQLite source was opened read-only and imported into PostgreSQL.
The SQLite files remain available for rollback. PostgreSQL is now the Compose
application's source of truth. Its named volume survives container replacement.
Host Python commands need a database URL with 127.0.0.1 instead of the Compose
hostname postgres; do not print URLs containing credentials.

Automation is deliberately paused with the kill switch on. The two legacy
built-in schedules are disabled. Real email remains disabled and actions remain
in simulation mode. No real model requests or external actions were used during
verification.

Create the first administrator locally:

```powershell
docker compose exec orchestrator_core python -m orchestrator_core.bootstrap --username admin
```

Enter and repeat a password of at least 14 characters at the hidden prompts.
No administrator password was generated, stored in source, or sent through chat.
The bootstrap refuses a second initialization. Sign in through POST /auth/login;
the designed login screen and browser integration belong to Phase 3. Once signed
in, an administrator can explicitly turn off the kill switch when ready.

Accounts share one workspace. Administrator, operator and viewer are roles,
not isolated tenants. Cookies are HttpOnly and SameSite=Strict; outside local
development they also require HTTPS. Mutations require a session-bound CSRF
header. Password/access changes revoke sessions. Service bearer tokens remain
administrative credentials and must never be embedded in browser code.

## Evidence

- 34 focused Phase 2 checks passed across the implementation and follow-up runs;
  a separate encrypted backup/restore regression also passed.
- The 65-test focused CI security gate passed locally. Ruff and diff checks
  passed. The full 302-test suite was not run during Phase 2.
- Actual PostgreSQL concurrent connections proved one claim per job and one
  queued job per schedule occurrence. Saved approval dependencies resumed once
  after reopening the connection.
- API /health and /ready returned 200. Readiness included PostgreSQL, worker,
  scheduler and sandbox, and returned ready after worker/scheduler restarts.
  Anonymous /jobs and /auth/session requests returned 401.
- The deployed application role could not CREATE TABLE. Migration and bootstrap
  credentials were absent from the API environment.
- The browser process ran as UID 1001 with zero effective/bounding capabilities.
  Its OUTPUT chain defaulted to DROP. Only the read gateway was reachable in the
  direct socket probes; public, private and metadata probes were blocked.
  A real Chromium navigation to the metadata URL returned a policy denial, 403.
  The container health probe uses explicit IPv4 loopback because IPv6 egress
  is deliberately blocked; localhost could otherwise time out on its IPv6 address.
- The actual imported database was encrypted into
  backups/phase2-cutover-2026-10-26.dump.enc (201784 bytes, about 0.39 seconds).
  It restored into a disposable database in about 0.25 seconds; all 21 approvals
  and 85 audit records matched exactly. These small-data timings are not RPO/RTO
  promises. See [recovery.md](recovery.md) for key handling and restore commands.
- The existing dry-run router CI gate passed. Its synthetic predictions do not
  establish real model accuracy.

CI now includes a disposable PostgreSQL service and focused Phase 2 regressions.
The restore regression skips unless an explicitly empty restore target is
provided. Remote CI has not been claimed green; these commits have not been pushed.

## Behavior and limits

Workers use expiring leases with generations, independent renewal and fenced
writes. Approval/child dependencies, schedules and event replay live in SQL.
Pipeline/evaluation requests enqueue durable jobs and synchronous handlers run
in FastAPI's thread pool. Event streams use bounded polling batches and browser
session revalidation.

Provider calls reserve budget before execution. Input/output accounting ceilings
are $10/$30 per million tokens, used as conservative accounting units, not
verified provider pricing. Missing provider usage retains the full reservation.
Calls have a 30-second response deadline, no automatic SDK retries and eight
concurrent call slots. A timed-out SDK thread may continue until its transport
returns; it keeps its slot and cannot directly write job results. Spend settlement
can occur after a lease expires because it records already-incurred usage.

Dispatch uses SSE for routing and response events, but model completions are
currently buffered and emitted as one response chunk to enforce the deadline.
Incremental token delivery is not claimed. Session revocation stops output at the
next check; it cannot undo a request already accepted by a provider.

Recent conversation context and reviewed, source-attributed memory come from SQL.
Vector updates are retryable derived state. Job events currently have no retention
job; retention, sustained queue growth, representative load and memory measurements
remain release hardening work. Backups revoke restored sessions intentionally,
rather than resurrecting access from old snapshots.

## Commit map

| Task | Main implementation |
|---|---|
| PostgreSQL and local setup | 0310d5b, 3fb5da3 |
| Accounts and sessions | 1a210e7 |
| Worker fencing | 7fdf00f |
| Dependency resumption | af626e5 |
| Usage and limits | 4aa47d8 |
| Persistent schedules | da0cfd0 |
| Supervised services | c596ec5 |
| Durable events | b86c230 |
| Context and memory | ed153ab |
| Backup and restore | 5f36f63 |
| Request isolation | 9b92f52 |
| Integration corrections and verification | 0564428, 0a8df0c, 1fb7ff0, 931f797, 74879d0 |

