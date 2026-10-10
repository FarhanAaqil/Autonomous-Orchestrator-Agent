# ADR 0002: Persistent Autonomous Job Queue & Atomic CAS Claim

## Status
Accepted

## Context
Long-running agent workflows must survive worker crashes, network interruptions, and service restarts without losing progress, creating duplicate executions, or corrupting state.

## Decision
1. **Persistent SQLite Store**: All jobs and execution steps are persisted in `jobs` and `job_steps` tables with foreign keys and WAL mode.
2. **Atomic Compare-And-Set (CAS)**: Workers claim queued jobs using atomic SQL updates:
   ```sql
   UPDATE jobs
   SET status = 'running', claimed_by = ?, claimed_at = ?
   WHERE id = ? AND status = 'queued';
   ```
3. **Heartbeat & Zombie Reaper**: Active workers periodically update `heartbeat_at`. A background reaper re-queues expired zombie jobs with exponential backoff up to `max_attempts`.
4. **Step-by-Step Rehydration**: On worker restart, the ReAct loop reconstructs agent context from persisted `job_steps`.
5. **Hard Safety Caps**: Every step enforces emergency kill switch checks, daily dollar budget ceilings, maximum step caps, token limits, and loop repeat detectors.

## Consequences
- Guaranteed zero duplicate job claims under concurrent workers.
- Crash-resilient resumption from the last recorded step.
- Predictable financial and resource containment.
