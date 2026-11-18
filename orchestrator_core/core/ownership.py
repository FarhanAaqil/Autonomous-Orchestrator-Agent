"""Explicit request ownership. Service tokens never impersonate a human account."""
from fastapi import Depends, HTTPException
from orchestrator_core.dependencies import verify_bearer_token
from orchestrator_core.config import get_settings

OWNED_TABLES = ('conversations', 'messages', 'jobs', 'job_steps', 'job_events', 'job_dependencies', 'approvals', 'execution_attempts', 'pipeline_runs', 'pipeline_steps', 'memory_items', 'schedules', 'schedule_occurrences', 'provider_usage', 'router_eval_runs')


def request_owner(principal_id=Depends(verify_bearer_token)):
    if principal_id in ('service', 'local-development'):
        settings = get_settings()
        if settings.environment == 'development' and not settings.public_registration:
            return None  # Legacy local-workspace compatibility, never public tenancy.
        raise HTTPException(401, 'Sign in with a personal account')
    return principal_id


def adopt_legacy_rows(db, user_id):
    # Migration/bootstrap-only operation. Caller must already hold its transaction.
    for table in OWNED_TABLES:
        db.execute(f'UPDATE {table} SET user_id=? WHERE user_id IS NULL', (user_id,))


def conversation_for_owner(db, conversation_id, owner):
    row = db.execute('SELECT id,user_id FROM conversations WHERE id=?', (conversation_id,)).fetchone()
    if row and row['user_id'] != owner:
        raise HTTPException(404, 'Conversation not found')
    return row


def require_owned_job(db, job_id, owner):
    row = db.execute("SELECT id FROM jobs WHERE id=? AND COALESCE(user_id,'')=?", (job_id, owner or '')).fetchone()
    if not row:
        raise HTTPException(404, 'Job not found')
