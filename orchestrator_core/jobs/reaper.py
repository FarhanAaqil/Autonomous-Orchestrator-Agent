"""Recover only the expired lease observed by this reaper."""
from datetime import datetime, timedelta, timezone

from orchestrator_core.storage.db import log_audit


def reap_zombies(db, timeout_seconds=60.0):
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(seconds=timeout_seconds)).isoformat()
    rows = db.execute("SELECT * FROM jobs WHERE status='running' AND (lease_expires_at<=? OR "
                      '(lease_expires_at IS NULL AND COALESCE(heartbeat_at,claimed_at)<=?))',
                      (now.isoformat(), cutoff)).fetchall()
    reaped = []
    for row in rows:
        state = 'queued' if row['attempts'] < row['max_attempts'] else 'failed'
        dependency = db.execute('SELECT kind FROM job_dependencies WHERE job_id=? AND resolved=0 LIMIT 1', (row['id'],)).fetchone()
        if dependency:
            state = 'awaiting_approval' if dependency['kind'] == 'approval' else 'awaiting_input'
        with db:
            cur = db.execute('UPDATE jobs SET status=?,claimed_by=NULL,heartbeat_at=NULL,lease_expires_at=NULL, '
                             'lease_generation=lease_generation+1,not_before=?,error=?,finished_at=? '
                             "WHERE id=? AND status='running' AND lease_generation=? AND (lease_expires_at<=? OR "
                             '(lease_expires_at IS NULL AND COALESCE(heartbeat_at,claimed_at)<=?))',
                             (state, (now+timedelta(seconds=5)).isoformat(), 'Worker lease expired',
                              now.isoformat() if state == 'failed' else None, row['id'], row['lease_generation'], now.isoformat(), cutoff))
            if cur.rowcount:
                log_audit(db, 'reaper', 'expired_lease_recovered', 'job', row['id'], {'state': state})
                reaped.append(row['id'])
    return reaped
