<p align="center"><img src="docs/logo.png" width="96" height="96" alt="Orchestrator Agent logo" /></p>

# Autonomous Orchestrator Agent

A local agent workspace built with FastAPI, PostgreSQL, ChromaDB, and a compiled React 19 interface. It supports conversations, durable jobs, recurring schedules, reviewed memories, pipelines, and explicit approval of proposed external actions. The interface uses warm surfaces, reduced-motion support, and an optional 3D agent view.

[Watch the narrated introduction](docs/media/toji-intro.mp4).

**Public launch is not ready.** Phase 4 and the multi-user launch work are in progress. Keep public registration disabled and external actions in simulation while the remaining gates are completed. Passing tests are evidence for their covered behaviors, not a guarantee of security.

## Current behavior

- Cookie sessions, CSRF checks, administrator/operator/viewer roles, and local administrator recovery.
- Opt-in email verification and password recovery using hashed, expiring, single-use tokens. SMTP must be configured privately; development logs do not print token-bearing links.
- Owner-filtered conversations, jobs, events, approvals, schedules, memory, pipeline runs, and evaluation history. Background jobs retain ownership. PostgreSQL row-level security and final owner constraints are still pending.
- Approval hashes and signatures bind the reviewed content, mode, expiry, and account. Outcomes distinguish simulation, submission, confirmation, failure, and uncertainty.
- Atomic daily job/token limits, schedule and connection limits, per-account job concurrency, and expiring free/pro plan policy. Personal usage is available in Settings. Administrator plan grants are manual; no automatic payment integration is claimed.
- Encrypted owner-bound provider credential storage and key rotation. OAuth onboarding and personal-provider execution integration are not yet complete.

PostgreSQL is the intended runtime database. SQLite remains available for development and isolated tests. API, worker, scheduler, browser sandbox, and database run as separate services. Release version comes from `orchestrator_core/version.py`.

## Local setup

For a new installation with Python, Node, and Docker available:

```powershell
python scripts/setup_local_postgres.py
cd frontend
npm ci --ignore-scripts --no-audit --no-fund
npm run build
cd ..
docker compose up -d --build
docker exec -it toji_orchestrator_core python -m orchestrator_core.bootstrap --username admin
```

Choose a private password of 14 or more characters. Password input is invisible. Open http://localhost:8080 and sign in with `admin` and that password. No default administrator password is shipped.

To recover an existing account locally:

```powershell
docker exec -it toji_orchestrator_core python -m orchestrator_core.reset_password --username admin
```

Recovery revokes existing sessions. Do not put passwords in command-line arguments or chat. Back up existing data before upgrading or running new migrations; the local setup instructions are not a migration approval for an existing installation.

## Verification

```powershell
python scripts/test_local.py tests
python scripts/export_frontend_contract.py --check
python scripts/check_frontend_budget.py
```

The local runner disables dotenv loading and external sockets and uses disposable state. PostgreSQL and restore tests require explicitly configured disposable databases. Never point those tests at your working database.

In `frontend`, run `npm run lint`, `npm test`, and `npm run build`. Browser workflows use `python scripts/phase3_browser_server.py` on port 8081, then `npm --prefix frontend run test:browser`; this fixture has separate test accounts and simulation-only data.

On 2026-11-25 the combined local branch passed **364 Python tests**, with **8 PostgreSQL/restore checks skipped**, and **11 browser workflows**. Eight disposable PostgreSQL checks passed separately on 2026-11-19. These are local results, not a claim that current remote CI or production deployment passed.

The corrected frozen offline router evaluation measured **66/106 (62.3%)**, below the unchanged **90%** gate. The previous label-derived 100% score was invalid. The router release gate remains failing; it must not be bypassed or reported as complete. Live provider evaluation has not been performed.

## Remaining launch gates

- Database-enforced tenant isolation, final owner constraints, and complete adversarial two-account coverage.
- Personal GitHub/Gmail OAuth and publishing credentials, provider scope validation, per-account execution mode, and removal of operator-credential fallback for user work.
- Complete usage enforcement across synchronous work and email, personal model keys, payment-link workflow, and account export/deletion.
- Landing/pricing/onboarding and reviewed privacy, terms, and acceptable-use policies.
- Router quality gate, production backup schedule and restore drill, load/recovery testing, sanitized logs, deployment checks, and independent security review.

The optional Compose `public` profile provides a Caddy proxy, but does not establish public-launch readiness. Domain, hosting, SMTP, OAuth applications, payment details, and legal review require operator configuration. The application should remain private until the gates above pass.

## Operations

See [the runtime notes](docs/phase2-runtime.md), [approval security notes](docs/phase1-security.md), and the repository's local `implementation.md` for tracked work. Older runbooks and screenshots may describe earlier releases; verify commands against the current code.

PostgreSQL backup tooling is in `orchestrator_core.storage.postgres_backup`. It encrypts archives, requires an empty restore destination, revokes restored sessions, and marks vectors for rebuilding. Store encryption keys separately from archives. No recovery-time or recovery-point objective is claimed without a measured deployment drill.

## License

See [LICENSE](LICENSE).
