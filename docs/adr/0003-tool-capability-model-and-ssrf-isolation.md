# ADR 0003: Tool Capability Model & SSRF Boundary Isolation

## Status
Accepted

## Context
Exposing general tools to autonomous LLM agents introduces risks of unauthorized mutations, Server-Side Request Forgery (SSRF) targeting internal networks or cloud metadata, and unpredictable side effects.

## Decision
1. **Explicit Capability Tagging**:
   - `Capability.READ`: Idempotent, read-only queries with zero mutating HTTP verbs.
   - `Capability.PROPOSE`: Writes strictly to proposals table for human approval.
   - `Capability.EXEC`: Real-world side effects; forbidden in agent registries, reserved exclusively for the approval executor.
2. **Strict Agent Allowlists**: Every agent defines a frozenset `TOOL_ALLOWLIST`. The `ToolRegistry` enforces that agents only receive tools on their allowlist, with zero EXEC tools.
3. **SSRF Guardrails**: All outbound HTTP fetch operations pass through a shared client that resolves IPs and strictly blocks loopback (`127.0.0.1`), RFC 1918 private subnets (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`), and Cloud Instance Metadata (`169.254.169.254`).
4. **Resilience & Circuit Breakers**: External APIs (Google Search, arXiv, DuckDuckGo, GitHub) are wrapped in configurable circuit breakers that trip on 3 consecutive failures to protect upstream rate limits.

## Consequences
- Agents cannot mutate state without human review.
- Internal infrastructure and metadata endpoints are insulated against exfiltration.
- Graceful degradation when third-party services fail.
