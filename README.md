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

On 2026-11-27 the complete isolated suite passed **413 tests with no skips**, with disposable PostgreSQL, RLS and encrypted restore enabled. The latest browser run passed **13 workflows**. The frontend builds and passes lint, its 6 unit tests, and the configured asset budgets. Three desktop endpoint checks also passed. These are local results; no production database upgrade was performed.

The corrected frozen offline router evaluation measured **71/106 (67.0%)**, below the unchanged **90%** accuracy gate and several per-class F1 gates. Development-only intent improvements scored 102/103 on the development split but did not generalize sufficiently. The former label-derived 100% score was invalid. The release gate remains failing; do not bypass it or report the release complete. No live provider evaluation was performed.

## Personal accounts in this branch

Settings supports separate GitHub and Gmail OAuth grants, validated DEV/Hashnode/Groq personal tokens, encrypted owner-bound storage, disconnect, personal execution mode, daily/monthly token usage, and JSON account export. Gmail is restricted to the configured beta allowlist; sending uses the account's own grant and still requires signed approval. LinkedIn is manual drafts only. Other publishing adapters remain unavailable.

Pricing reads the server-owned limits. An optional HTTPS payment link opens the operator's configured payment page; administrators grant Pro access with an explicit expiry after verifying payment. Automatic payment webhooks are deferred. Policy pages are prominently marked **DRAFT: needs human review**. Starter templates fill an editable brief without submitting it.

## Remaining launch gates

- Final deployment and hostile multi-user review of PostgreSQL isolation. RLS and NOT NULL owner constraints are implemented, with transaction scope, worker polling, first-admin backfill, rollback and restricted-role/API tests. Production data has not been migrated.
- Account export and password-confirmed deletion are implemented. Deletion removes active SQL records and vectors, revokes sessions, preserves the last administrator, and waits for running work to finish. Vector writes recheck current ownership inside the deletion lock; failed cleanup leaves the account available for retry.
- Personal GitHub/DEV/Hashnode publishing adapters with receipt/error tests; Gmail OAuth operator verification and configuration.
- Daily admission limits covering synchronous work as well as queued jobs, and additional first-24-hour abuse limits. Request concurrency is currently bounded per account and globally in one API process; multiple API processes require coordinated admission.
- Passing genuine router quality gates, nightly production backup scheduling, uptime/error tracking, final deployment/load/recovery checks, and independent security review.
- Real domain/hosting, SMTP, OAuth applications, connection encryption keys, payment details, and human review of legal drafts.

The Compose `public` profile provides a Caddy proxy; it does not establish launch readiness. Public registration defaults to disabled. Keep the installation private until these gates pass. Existing running containers are not automatically upgraded by source commits.

## Operations

See [the runtime notes](docs/phase2-runtime.md), [approval security notes](docs/phase1-security.md), and the repository's local `implementation.md` for tracked work. Older runbooks and screenshots may describe earlier releases; verify commands against the current code.

PostgreSQL backup tooling is in `orchestrator_core.storage.postgres_backup`. It encrypts archives, requires an empty restore destination, revokes restored sessions, and marks vectors for rebuilding. Store encryption keys separately from archives. Account deletion does not rewrite existing encrypted backup archives. Operators must document and enforce their archive retention period and reapply deletions before making a restored database available to users. No recovery-time or recovery-point objective is claimed without a measured deployment drill.

## License

See [LICENSE](LICENSE).
