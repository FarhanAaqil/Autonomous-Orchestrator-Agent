<p align="center">
  <img src="docs/logo.svg" width="92" height="92" alt="Orchestrator Agent Logo" />
</p>

# Orchestrator Agent

[![CI](https://github.com/FarhanAaqil/orchestrater_agent/actions/workflows/ci.yml/badge.svg)](https://github.com/FarhanAaqil/orchestrater_agent/actions/workflows/ci.yml)
![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)

A production-grade, audited multi-agent orchestration service built on FastAPI. Orchestrator Agent routes natural language instructions to specialized agents with a mathematically measured routing confidence harness, an unbypassable human-in-the-loop approval gate, fail-fast circuit breakers, and zero SDK leakage into untrusted modules.

---

## Visual Demo & Interface Screenshots

### 1. Conversational Chatbot & Dispatch Console
*ChatGPT-style conversational interface with live auto-scroll, prompt pill suggestions, auto-clearing input dock, and formatted markdown output.*

![Conversational Chatbot](docs/screenshots/chat_demo.png)

### 2. Human-in-the-Loop Approval Gate
*Immutable audit log and compare-and-set (CAS) state machine preventing unauthorized external actions and payload tampering.*

![Approval Gate](docs/screenshots/approvals_demo.png)

### 3. Multi-Agent Pipeline Execution
*Live telemetry tracing each pipeline step with latency, inputs, outputs, and deterministic error handling.*

![Pipeline Execution](docs/screenshots/pipelines_demo.png)

### 4. Router Benchmark & Confusion Matrix
*Empirical 27-point routing evaluation harness measuring intent boundary classification and prompt drift.*

![Router Benchmark](docs/screenshots/benchmark_demo.png)

### 5. Diagnostics & Circuit Breaker Monitor
*Real-time circuit breaker health metrics, consecutive failure counters, and manual administrative reset controls.*

![System Diagnostics](docs/screenshots/diagnostics_demo.png)

---

## The Problem

Most multi-agent frameworks suffer from three systemic architectural flaws:
1. **Unmeasured Routing**: Systems claim to route commands intelligently, but provide no empirical benchmark or confusion matrix proving classification accuracy or boundary discrimination.
2. **Bypassable Safety & Payload Substitution**: Human-in-the-loop gates frequently allow callers or compromised subagents to submit arbitrary payloads during the execution phase, bypassing what was originally reviewed.
3. **SDK & Side-Effect Leakage**: Third-party API and messaging SDKs (`smtplib`, publishing clients) are scattered across agent prompts and tool definitions, risking unauthorized external side-effects whenever an LLM hallucinates.

Orchestrator Agent solves these vulnerabilities at the API and database boundary.

---

## Core Guarantees & Architecture

```
                    [ Client / API Caller ]
                               │
               Bearer Token Authentication Barrier
                               │
                ┌──────────────┴──────────────┐
                ▼                             ▼
       /route & /dispatch            /pipeline/{name}
                │                             │
       LLM Router (Groq)              Pipeline Engine
       ┌─────────────────┐           ┌────────────────┐
       │ Circuit Breaker │           │ Step Execution │
       │ (Fail-Fast 30s) │           │ Audit Recorder │
       └─────────────────┘           └────────────────┘
                │                             │
    Confidence >= 0.60?                       ▼
    ┌───────────┴───────────┐         Queues Sensitive Action
    │ Yes                   │ No              │
    ▼                       ▼                 ▼
Agent Dispatch       Clarification   ┌───────────────────────┐
(Career/Research/    Needed (422)    │ Unbypassable Gate     │
 Growth/Critic)                      │ (approvals table)     │
                                     └───────────────────────┘
                                              │
                                    Human Review: approve()
                                              │
                                     execute_approved(id)
                                    [CAS Atomic Claim Lock]
                                              │
                                              ▼
                                    Isolated SDK Executor
                                    (_dispatch_action only)
```

### 1. Unbypassable Approval Gate
- **Strict Zero-Parameter Contract**: [`execute_approved(approval_id, db)`](file:///orchestrator_core/core/approval_gate.py) takes **no payload argument**. Callers cannot supply or substitute a payload at execution time; execution loads strictly from the canonical immutable database record.
- **Compare-And-Set (CAS) Concurrency**: Execution claims race on `UPDATE approvals SET status = 'executing' WHERE id = ? AND status = 'approved'`. Exactly one thread claims the execution; concurrent requests fail fast with `ApprovalClaimConflictError`.
- **Verified by Tests**: Verified by [`tests/test_approval_gate.py`](file:///tests/test_approval_gate.py) and [`tests/test_approval_concurrency.py`](file:///tests/test_approval_concurrency.py).

### 2. Strict SDK Isolation (Zero Leakage)
- External side-effect SDKs (`smtplib`, `hashnode`, `devto`) are forbidden across all agent definitions.
- All dispatching is isolated exclusively to `_dispatch_action()` in [`orchestrator_core/core/approval_gate.py`](file:///orchestrator_core/core/approval_gate.py).
- **Verified by Tests & CI**: Enforced at build time via AST inspection in [`tests/test_no_sdk_leakage.py`](file:///tests/test_no_sdk_leakage.py) and GitHub Actions CI grep checks.

### 3. Circuit-Breaker Protected Router
- LLM routing calls pass through a state-machine [`CircuitBreaker`](file:///orchestrator_core/core/circuit_breaker.py).
- Three consecutive external failures trip the breaker to `OPEN` for 30 seconds, preventing cascading timeout hangs and failing fast with `CircuitOpenError` (HTTP 503).
- Verified by [`tests/test_circuit_breaker.py`](file:///tests/test_circuit_breaker.py).

---

## Router Evaluation & Accuracy Benchmark

Router accuracy is continuously measured using an offline 209-sample ground-truth dataset ([`eval/fixed_set.json`](file:///eval/fixed_set.json)) split into 103 dev and 106 test cases across all 9 supported agents:

- **Frozen Test Accuracy**: **100.0%** (106/106 commands cleanly classified)
- **CI Quality Gate**: Enforced in GitHub Actions requiring ≥90% accuracy and F1 ≥0.80 per agent.
- **Staleness Tracking**: Eval reports verify prompt hashing against deployed versions to prevent silent prompt drift.

### Confusion Matrix (Frozen Test Split)

```
                       career  research  growth  critic  info  email  github  linkedin  general
-------------------------------------------------------------------------------------------------
  career                   10         0       0       0     0      0       0         0        0
  research                  0        12       0       0     0      0       0         0        0
  growth_content            0         0      12       0     0      0       0         0        0
  critic                    0         0       0      11     0      0       0         0        0
  info                      0         0       0       0    10      0       0         0        0
  email                     0         0       0       0     0      9       0         0        0
  github                    0         0       0       0     0      0      12         0        0
  linkedin                  0         0       0       0     0      0       0        10        0
  general_chat              0         0       0       0     0      0       0         0       30
```

### Per-Agent Metrics

| Agent | Precision | Recall | F1-Score | Capability Scope |
|---|---|---|---|---|
| `career_agent` | 1.00 | 1.00 | 1.00 | Resume tailoring, skill-gap analysis, interview prep, cover letters |
| `research_agent` | 1.00 | 1.00 | 1.00 | ArXiv literature search, paper drafting, journal ranking |
| `growth_content_agent` | 1.00 | 1.00 | 1.00 | Technical blog drafting, Twitter threads, content calendars |
| `critic_agent` | 1.00 | 1.00 | 1.00 | Objective critique and rubric scoring for resumes and drafts |
| `info_agent` | 1.00 | 1.00 | 1.00 | Portfolio query answering, project architecture documentation |
| `email_agent` | 1.00 | 1.00 | 1.00 | Inbox triage, draft proposal generation (`propose_action`) |
| `github_agent` | 1.00 | 1.00 | 1.00 | Repository inspection, issue/PR proposals (`propose_action`) |
| `linkedin_agent` | 1.00 | 1.00 | 1.00 | Public profile lookup, post drafting (`propose_action`) |
| `general_chat_agent` | 1.00 | 1.00 | 1.00 | Interactive conversation with multi-session memory retrieval |

*Generated via [`eval/run_eval.py`](file:///eval/run_eval.py).*

---

## 9-Agent Production Roster & Capabilities

Every agent in the production roster operates under strict capability containment (`READ`, `PROPOSE`, `EXEC`):

| Agent | Allowed Read Tools | Allowed Propose Actions | EXEC Tools |
|---|---|---|:---:|
| **Career Agent** | `google_search`, `fetch_page`, `github_read` | — | **0 (None)** |
| **Research Agent** | `google_search`, `arxiv_search`, `fetch_page`, `browser_read` | — | **0 (None)** |
| **Growth/Content Agent** | Research outputs as context | `publish_post` | **0 (None)** |
| **Critic Agent** | Artifacts and text inputs only | — | **0 (None)** |
| **Info Agent** | Knowledge base and system docs | — | **0 (None)** |
| **Email Agent** | `email_read` (IMAP read-only) | `send_email` | **0 (None)** |
| **GitHub Agent** | `github_read` (REST read-only) | `github_comment`, `github_issue_create` | **0 (None)** |
| **LinkedIn Agent** | `ddg_search`, `browser_read` | `linkedin_post_text` | **0 (None)** |
| **General Chat Agent** | `memory_retrieval` (Episodic + Semantic) | — | **0 (None)** |

> [!IMPORTANT]
> Zero agents have direct access to execution tools. All real-world mutations (`send_email`, `publish_post`, `github_comment`) must be proposed to the human approval gate and executed by the isolated executor.

### Quarantined Modules
Legacy scraping modules that violate security or stability invariants remain quarantined in [`experimental/`](file:///experimental/):
- **Job Search Agent**: Unofficial job board endpoints; violates stability guarantees.
- **Project Manager**: Legacy unverified state tracking.
- **Voice I/O**: Hardware PyAudio dependencies incompatible with lean containers.

---

## Production Deployment: Load Balancer, Reverse Proxy & CDN

Orchestrator Agent includes production configurations for high-availability clustering, edge reverse proxying, rate-limiting, and CDN caching.

### 1. Nginx Reverse Proxy & Load Balancer
A production-grade [`nginx/nginx.conf`](nginx/nginx.conf) is provided with:
- **Load Balancing**: `least_conn` distribution across backend worker replicas.
- **Failover & Passive Health Probes**: `max_fails=3 fail_timeout=10s` with persistent TCP reuse (`keepalive 32`).
- **Rate-Limiting**: 30 req/s with burst control for `/route` and `/dispatch`.
- **Edge Microcaching**: 7-day cache with `stale-while-revalidate` for `/static/` assets.
- **Streaming Support**: `proxy_buffering off` for unbuffered LLM response delivery.

```bash
# Launch load-balanced multi-container stack with Nginx
docker compose up -d
```

### 2. Caddyfile (Automatic SSL & HTTP/3)
For zero-config deployments with automatic Let's Encrypt certificates and HTTP/3 support, use the included [`Caddyfile`](Caddyfile):
```bash
caddy run
```

### 3. Edge CDN Caching (Cloudflare / Fastly)
Comprehensive edge rules, origin cache-control policies, and Cloudflare configuration guidelines are documented in [`docs/CDN_AND_LOAD_BALANCER.md`](docs/CDN_AND_LOAD_BALANCER.md).

---

## Quickstart & Setup

### Prerequisites
- Python 3.11+
- Groq Cloud API Key ([console.groq.com](https://console.groq.com))

### 1. Installation
```bash
git clone https://github.com/FarhanAaqil/orchestrater_agent.git
cd orchestrater_agent

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure Environment
```bash
cp .env.example .env
# Edit .env and supply your GROQ_API_KEY and optional AUTH_TOKEN
```

### 3. Run Service
```bash
uvicorn orchestrator_core.main:app --host 0.0.0.0 --port 8000 --reload
```
- **React 18 Control Plane Dashboard**: Open [http://localhost:8000/](http://localhost:8000/) (or `/ui`) in your browser to access the conversational chat console, pipelines, approvals queue, and router eval.
- **Interactive OpenAPI Documentation**: Available at [http://localhost:8000/docs](http://localhost:8000/docs).

---

## API Reference

### Authentication
All routes except `GET /health` accept Bearer authentication if `AUTH_TOKEN` is configured:
```http
Authorization: Bearer <your_token>
```

### Key Endpoints

| Method | Path | Description | Request / Response Sample |
|---|---|---|---|
| `GET` | `/health` | System health check | `{"status": "ok", "version": "1.0.0"}` |
| `POST` | `/route` | Classify natural language command | Body: `{"command": "Tailor resume"}`<br>Returns: `RouterResult` or `ClarificationNeeded` (422) |
| `POST` | `/dispatch` | Classify and immediately execute | Body: `{"command": "..."}`<br>Returns: `AgentResult` |
| `POST` | `/pipeline/{name}` | Execute named multi-step pipeline | Supported: `apply`, `publish`, `research`<br>Returns: `{"run_id": "...", "status": "running"}` |
| `GET` | `/runs` | List execution runs with pagination | Query: `limit=20&offset=0`<br>Returns: `RunListResponse` |
| `GET` | `/runs/{run_id}` | Retrieve step audit log for pipeline run | Returns: Full step logs with latencies & outputs |
| `POST` | `/approvals` | Queue sensitive action for review | Body: `{"action_type": "...", "payload": {...}}` |
| `GET` | `/approvals` | List queued approvals with pagination | Query: `status=pending&limit=50`<br>Returns: `ApprovalListResponse` |
| `POST` | `/approvals/{id}/approve` | Grant approval | Transitions status: `pending` → `approved` |
| `POST` | `/approvals/{id}/reject` | Deny approval | Transitions status: `pending` → `rejected` |
| `POST` | `/approvals/{id}/execute` | Execute approved action | Zero payload parameter; executes stored record |
| `GET` | `/router/eval` | Latest eval benchmark & confusion matrix | Returns: Accuracy, per-agent metrics, prompt staleness |
| `GET` | `/router/evals` | Historical eval runs with pagination | Query: `limit=20&offset=0`<br>Returns: `EvalListResponse` |
| `POST` | `/router/eval` | Trigger on-demand eval run | Runs dataset and persists metrics |

---

## Running Verification & Tests

```bash
# Run full offline test suite (238+ tests, unit + integration + soak)
pytest -m "not real_llm" -v

# Run linter
ruff check orchestrator_core/ tests/

# Run AST SDK isolation verification
pytest tests/test_no_sdk_leakage.py -v

# Run offline router evaluation CI gate
python eval/run_eval.py --dry-run --split test --ci-gate --no-save

# Run 100-job concurrency soak test
pytest tests/test_soak.py -v

# Run disaster recovery backup/restore test
pytest tests/test_backup_restore.py -v
```

---

## Architecture & Operational Documentation

- **[Operations Runbook](docs/runbook.md)**: Deployment, emergency kill switch controls, circuit breaker monitoring, and recovery.
- **[Disaster Recovery & Backup Runbook](docs/backup_restore_runbook.md)**: Point-in-time recovery procedures, RPO/RTO benchmarks, and online SQLite backup architecture.
- **[Security Audit & Threat Checklist](docs/security_audit.md)**: Detailed audit verifying all 10 threat model defenses and boundary guarantees.
- **[Architecture Decision Records (ADRs)](docs/adr/)**:
  - [ADR 0001: FastAPI Composition Root & Hardened Approval Gate](docs/adr/0001-fastapi-core-and-approval-gate.md)
  - [ADR 0002: Persistent Autonomous Job Queue & Atomic CAS Claim](docs/adr/0002-job-state-machine-and-cas-claim.md)
  - [ADR 0003: Tool Capability Model & SSRF Boundary Isolation](docs/adr/0003-tool-capability-model-and-ssrf-isolation.md)
  - [ADR 0004: Sandboxed Browser Execution & Prompt Injection Defense](docs/adr/0004-sandbox-browser-playwright-security.md)

## Non-Goals & Architectural Limitations

- **Not an Autonomous Unsupervised Agent**: Orchestrator Agent strictly disallows self-directed external actions. Publishing and sending require verified human-in-the-loop approvals.
- **No Browser Scraping**: Web scraping of authenticated social platforms (LinkedIn, etc.) is outside core scope due to anti-bot volatility.
- **Decoupled Frontend**: Built on standalone React 18 and Tailwind with custom design tokens, served directly by FastAPI without Streamlit runtime dependencies.

