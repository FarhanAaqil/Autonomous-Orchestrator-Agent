# ADR 0004: Sandboxed Browser Execution & Prompt Injection Defense

## Status
Accepted

## Context
Web crawling and reading unstructured web pages exposes the agent to adversarial prompt injection attacks, malicious scripts, and browser escape vulnerabilities.

## Decision
1. **Containerized Sandbox Isolation**: The Playwright browser runs in an isolated container with an unprivileged non-root user (`pwuser`, uid 1001), read-only root filesystem, memory/CPU quotas, and ephemeral contexts that discard cookies and state upon close.
2. **Read-Only Invariant**: Form submissions, script evaluations, file downloads, and mutations are disabled in the browser driver.
3. **SSRF Guard**: The sandbox driver performs strict URL scheme verification (`http`/`https` only, blocking `file://`, `data:`, `javascript:`) and resolves destinations to block private and cloud metadata IPs.
4. **Boundary Tagging**: All retrieved web page text is wrapped in `<untrusted_data source="...">` tags.
5. **Tag Breakout Neutralization**: Any adversarial occurrence of `</untrusted_data>` inside fetched content is escaped to `&lt;/untrusted_data&gt;` before injecting into agent context, preventing injection escapes.

## Consequences
- Prevents remote browser escape and host file system access.
- Defeats indirect prompt injection attacks attempting to hijack the agent loop.
