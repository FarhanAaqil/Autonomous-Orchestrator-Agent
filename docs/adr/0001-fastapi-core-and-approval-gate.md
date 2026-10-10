# ADR 0001: FastAPI Composition Root & Hardened Approval Gate

## Status
Accepted

## Context
In earlier prototypes, agent modules invoked external SMTP and publishing SDKs directly from within agent loops, creating an unbypassable side-effect risk where an LLM hallucination or prompt injection could trigger unintended real-world mutations. Furthermore, callers could supply unvetted payloads at execution time.

## Decision
1. **Zero SDK Leakage**: All direct mutation SDK imports are forbidden in agent and runner modules, strictly enforced via CI AST checks.
2. **SEC-01 Contract**: The approval execution endpoint `execute_approved(approval_id)` accepts ONLY the approval ID, completely eliminating execution-time payload substitution.
3. **Payload Binding**: All approval proposals compute a canonical SHA-256 payload hash (`payload_hash`).
4. **HMAC Signing**: Approvals are signed with `EXECUTOR_HMAC_SECRET` upon human decision and verified prior to execution.
5. **Idempotency & TOCTOU**: State transitions use atomic compare-and-set database transactions, requiring `expected_hash` to match. Duplicate execution is prevented by unique `idempotency_key` constraints.

## Consequences
- Agents can only request approvals via `request_approval()`.
- Tampered database rows or forged approval signatures fail execution immediately.
- Execution cannot be replayed or duplicated.
