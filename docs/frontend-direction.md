# Supported application

The compiled React/TypeScript application in frontend is the sole maintained UI.
archive/legacy-dashboard.html and archive/frontend-prototype preserve the earlier
CDN dashboard and unfinished typed prototype for reference. Neither is served or
packaged. No production workflow depends on them.

| Workflow | Decision |
|---|---|
| Chat and response events | Migrate; persist conversation IDs and history |
| Jobs and durable events | Keep; render actual state and reconnect |
| Approvals | Keep exact payload, hash, expiry, mode and execution evidence |
| Schedules | Keep saved cron, timezone, pause and run controls |
| Memory | Keep review, provenance, editing and deletion |
| Pipelines and evaluation | Migrate to durable queued job responses |
| Diagnostics and settings | Keep readiness, budget, pause and agent controls |
| Legacy CDN scripts and desktop overlay | Retire from production |
| Desktop voice and automatic sidecar | Disable until independently supported |

The user's chosen visual direction is a warm, mid-light workspace: oat, sand,
clay and brown. No white, navy, cyan or dark-mode surfaces. Reusable surfaces,
clear focus rings and restrained motion provide depth. Optional 3D is an explicit
enhancement to the same accessible agent list, never part of approval or login.
