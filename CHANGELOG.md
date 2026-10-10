# Changelog

All notable changes to the Orchestrator Agent service will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.0.0] - 2026-10-11

### Full Autonomous Release (Phases 1–10 Complete)

#### Phase 1: FastAPI Composition Root & Persistence
- Modular FastAPI engine with WAL mode and foreign-key enforced SQLite schema.
- Structured request logging middleware, unified error handling, and `/health` diagnostic endpoints.

#### Phase 2: Router Evaluation Harness & CI Gate
- Expanded router evaluation harness to 209 benchmark test cases across dev and test splits.
- Enforced automated CI gate in GitHub Actions guaranteeing ≥90% accuracy and F1 score ≥0.80 across all 9 agents (achieved 100.0% frozen test split accuracy).

#### Phase 3: Approval Gate Cryptographic Hardening (SEC-01..08)
- Zero-payload execution contract (`execute_approved(approval_id)`).
- SHA-256 canonical payload hash binding (`compute_payload_hash()`).
- Server-side HMAC-SHA256 signature verification (`EXECUTOR_HMAC_SECRET`).
- Atomic Compare-And-Set (CAS) concurrency enforcement and unique `idempotency_key` deduplication.
- TOCTOU protection returning HTTP 409 Conflict if payload changes before approval.
- Edit-and-supersede proposal lifecycle and append-only audit trail logging.

#### Phase 4: AST Safety Guards & CI Enforcements
- AST analysis enforcing zero imports from `experimental/`.
- Zero SDK leakage outside `approval_gate.py` across all agents and tools.
- Verification that all read tools strictly use idempotent GET requests.

#### Phase 5: Autonomy Engine & Persistent Job Queue
- Persistent SQLite job queue with atomic CAS claiming (`claimed_by`, `claimed_at`).
- Granular step recording in `job_steps` tracking LLM thoughts, tool calls, token usage, duration, and output.
- ReAct loop with repeat loop detection (aborting on 5× identical calls), emergency kill switch, token/step limits, and wall-clock timeouts.
- Background worker with heartbeat leases and exponential backoff zombie job reaper.

#### Phase 6: Capability-Tagged Tool Registry & Full Agent Roster
- Explicit capability taxonomy (`READ`, `PROPOSE`, `EXEC`), strictly excluding `EXEC` tools from agents.
- 9 fully wired agents: `career_agent`, `research_agent`, `growth_content_agent`, `critic_agent`, `info_agent`, `email_agent`, `github_agent`, `linkedin_agent`, `general_chat_agent`.
- SSRF-protected shared HTTP client blocking private IP subnets and cloud metadata services.
- Circuit breakers protecting fragile external scrapers and search APIs.

#### Phase 7: Episodic & Semantic Memory Engine
- Multi-tier memory model: semantic facts/preferences and episodic conversation summaries.
- Owner review queue (`pending_review=1`) for auto-extracted facts before permanent promotion.
- Token-budgeted context retrieval (`get_context_slice()`) with cosine similarity ranking.
- Complete forget flow with soft-deletion and ChromaDB vector embedding purge.

#### Phase 8: Executive Control Plane Dashboard
- Production-grade React 18 single-page application with 10 integrated views: Dispatch/Chat, Jobs Timeline, Approvals Gate, Schedules, Memory Management, Pipelines, Benchmark, Settings, and Diagnostics.
- Server-Sent Events (SSE) streaming with reconnection replay via `Last-Event-ID` and query parameter fallback.
- Sticky-bottom intelligent autoscroll with "Jump to latest ↓" indicators.

#### Phase 9: Playwright Browser Sandbox
- Containerized Playwright sandbox running as unprivileged user with read-only root and ephemeral contexts.
- Strict scheme filtering and SSRF isolation blocking private networks and metadata IPs.
- Untrusted XML boundary tagging (`<untrusted_data>`) with adversarial tag breakout neutralization.

#### Phase 10: Hardening, Disaster Recovery & Release
- Atomic zero-downtime SQLite and ChromaDB backup and restore CLI (`scripts/backup_restore.py`) with RPO ≤ 1h and RTO < 30s.
- High-concurrency soak testing with 100 jobs, 5 concurrent workers, simulated crashes, and reaper recovery verifying zero duplicate executions.
- Daily budget dollar ceilings with automatic job abort and `system.budget_alarm` alerts.
- Formal security audit against Section 10 threat checklist with 0 npm/pip vulnerabilities.
- Complete Architecture Decision Records (`docs/adr/0001` through `0004`) and Operations Runbook (`docs/runbook.md`).

---

## [2.0.0-alpha] - 2026-09-19

### Phase 0 — Safety Baseline & Environment Sanitization
- Isolated `.env` secrets and provided documented [`.env.example`](.env.example) with required/optional parameter flags.
- Removed legacy bypass tools and insecure direct-execution utilities.
- Established `.gitignore` rules for WAL files, SQLite artifacts, and planning documentation.

### Phase 1 — FastAPI Core Architecture & Persistence
- Implemented modular FastAPI core service in [`orchestrator_core/`](orchestrator_core/).
- Added lazy, cached settings configuration with `pydantic-settings` in [`config.py`](orchestrator_core/config.py).
- Implemented declarative SQLite migrations with Write-Ahead Logging (WAL) and foreign key enforcement in [`storage/db.py`](orchestrator_core/storage/db.py).
- Isolated ChromaDB client within [`storage/chroma_client.py`](orchestrator_core/storage/chroma_client.py) avoiding global import side-effects.
- Added public, zero-dependency `GET /health` endpoint.

### Phase 2 — LLM Router & Accuracy Evaluation Harness
- Created LLM router in [`core/router.py`](orchestrator_core/core/router.py) mapping commands to 4 core agents (`career_agent`, `research_agent`, `growth_content_agent`, `critic_agent`).
- Built offline evaluation dataset with 27 curated commands in [`eval/fixed_set.json`](eval/fixed_set.json).
- Implemented evaluation harness [`eval/run_eval.py`](eval/run_eval.py) calculating overall accuracy, per-agent precision, recall, F1, and confusion matrices.
- Added [`eval/render_confusion_matrix.py`](eval/render_confusion_matrix.py) for rendering formatted markdown matrix tables.
- Added router evaluation API endpoints `GET /router/eval`, `GET /router/evals`, and `POST /router/eval`.

### Phase 3 — Unbypassable Approval Gate
- Designed state machine approval gate in [`core/approval_gate.py`](orchestrator_core/core/approval_gate.py) (`pending` → `approved` → `executing` → `executed`).
- Enforced strict zero-payload security contract on `execute_approved(approval_id, db)` preventing payload substitution attacks.
- Added compare-and-set (CAS) update concurrency locks ensuring exactly one thread claims execution.
- Added crash recovery guarantees: failed executions remain in `executing` status for auditable reconciliation without silent revert.
- Added pipeline execution engine in [`core/pipeline_engine.py`](orchestrator_core/core/pipeline_engine.py) recording every step to `pipeline_steps` with latency and trace data.

### Phase 4 — Testing Suite & Concurrency Verification
- Created pytest test suite in [`tests/`](tests/) totaling 34 unit and integration tests:
  - Approval state machine transitions and expiry handling.
  - Concurrent CAS execution races and replay protection.
  - Router classification boundaries, low-confidence clarification fallbacks, and prompt hashing.
  - Circuit breaker counting, fail-fast `OPEN` states, cooldown timers, and `HALF_OPEN` trial recovery.
  - Static AST inspection verifying zero external side-effect SDK imports outside `approval_gate.py`.
- Configured [`pytest.ini`](pytest.ini) with `real_llm` marker to run completely offline by default.

### Phase 5 — Quarantine, Authentication, Containerization & CI
- Quarantined 6 legacy v1 modules into [`experimental/`](experimental/) with [`NOT_SUPPORTED.md`](experimental/) boundary notes.
- Implemented HTTP Bearer token authentication in [`dependencies.py`](orchestrator_core/dependencies.py) protecting all non-health routes.
- Engineered multi-stage [`Dockerfile`](Dockerfile) running under non-root `appuser` with built-in healthchecks.
- Created GitHub Actions CI workflow [`.github/workflows/ci.yml`](.github/workflows/ci.yml) enforcing ruff linting, zero experimental imports, zero SDK leakage, and full test execution.

### Phase 6 — Documentation & Release Polish
- Rewrote [`README.md`](README.md) with comprehensive problem statements, architectural diagrams, confusion matrix benchmarks, and setup guides.
- Published updated [`BASELINE.md`](BASELINE.md) documenting verification telemetry.
