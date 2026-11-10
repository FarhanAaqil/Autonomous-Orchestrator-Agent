# Local identities

Run migrations before `python -m orchestrator_core.bootstrap --username admin`.
The command privately prompts for a password and refuses to run after any account
exists. There is no public registration or password recovery endpoint.

This deployment is one shared operator workspace. All active accounts can read
its jobs, conversations, memory and schedules. Operators can execute workflows;
administrators additionally manage accounts, agents and system controls. Viewers
can read and manage their own password/session. This is not tenant isolation.

Use `/auth/login` to obtain an HttpOnly SameSite=Strict cookie and a CSRF token.
Send the token as `X-CSRF-Token` on mutations. `/auth/session` returns a fresh
copy of this token for an active session. Production cookies require HTTPS.
Passwords use Argon2id (64 MiB, three iterations). Sessions expire after eight
hours; logout, password changes, disablement and role changes revoke access.
Failed and successful login attempts share per-account and per-address limits;
do not trust forwarded IP headers without a separately configured trusted proxy.

The configured bearer token is reserved for trusted service clients and has
administrator permissions. Tokens in URL query parameters are no longer accepted.
Development bypass requires explicit `ALLOW_INSECURE_LOCAL=true`, development
environment, and no bearer token. Do not enable it for human account deployments.

The browser login screen is Phase 3 work. These API endpoints are available for
that integration; no passwords are generated or sent to chat.
