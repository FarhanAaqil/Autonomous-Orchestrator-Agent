"""Durable approval/child continuations, reconciled after process restarts."""
import json
import uuid
from datetime import datetime, timezone

from orchestrator_core.storage.db import log_audit


def attach(db, job_id, kind, target_id):
    if kind not in ('approval', 'child'):
        raise ValueError('Unknown dependency kind')
    table = 'approvals' if kind == 'approval' else 'jobs'
    parent = db.execute('SELECT user_id FROM jobs WHERE id=?', (job_id,)).fetchone()
    target = db.execute(f'SELECT user_id FROM {table} WHERE id=?', (target_id,)).fetchone()
    if not parent or not target or parent['user_id'] != target['user_id']:
        raise ValueError('Dependency source not found')
    db.execute('INSERT INTO job_dependencies (id,job_id,kind,target_id,user_id) VALUES (?,?,?,?,?) '
               'ON CONFLICT(job_id,kind,target_id) DO NOTHING',
               (str(uuid.uuid4()), job_id, kind, target_id, parent['user_id']))


def reconcile(db):
    pending = db.execute('SELECT * FROM job_dependencies WHERE resolved=0').fetchall()
    resumed = []
    for dependency in pending:
        table = 'approvals' if dependency['kind'] == 'approval' else 'jobs'
        result = db.execute(f'SELECT * FROM {table} WHERE id=?', (dependency['target_id'],)).fetchone()
        if not result or result['user_id'] != dependency['user_id']:
            continue
        status = result['status']
        success = status in ('simulated', 'submitted', 'confirmed', 'succeeded')
        failure = status in ('rejected', 'expired', 'failed', 'cancelled', 'superseded')
        unknown = status == 'outcome_unknown'
        if not (success or failure or unknown):
            continue
        observation = {'dependency': dependency['kind'], 'target_id': dependency['target_id'], 'status': status}
        if table == 'jobs':
            observation['result'] = result['result_json']
            observation['error'] = result['error']
        else:
            attempt = db.execute('SELECT outcome,receipt_json,error_class FROM execution_attempts WHERE approval_id=?',
                                 (dependency['target_id'],)).fetchone()
            observation['execution'] = dict(attempt) if attempt else None
        encoded = json.dumps(observation, separators=(',', ':'))
        timestamp = datetime.now(timezone.utc).isoformat()
        db.execute('BEGIN IMMEDIATE')
        try:
            job = db.execute('SELECT * FROM jobs WHERE id=?', (dependency['job_id'],)).fetchone()
            if not job or job['user_id'] != dependency['user_id'] or job['status'] not in ('awaiting_approval', 'awaiting_input'):
                db.rollback()
                continue
            cur = db.execute('UPDATE job_dependencies SET resolved=1,outcome_json=? WHERE id=? AND resolved=0', (encoded, dependency['id']))
            if not cur.rowcount:
                db.rollback()
                continue
            state = 'queued' if success else ('awaiting_input' if unknown else 'failed')
            db.execute('UPDATE jobs SET status=?,claimed_by=NULL,lease_expires_at=NULL,lease_generation=lease_generation+1, '
                       'error=?,finished_at=? WHERE id=?',
                       (state, None if success else 'Dependency outcome: '+status, timestamp if failure else None, job['id']))
            idx = db.execute('SELECT COALESCE(MAX(idx),-1)+1 FROM job_steps WHERE job_id=?', (job['id'],)).fetchone()[0]
            db.execute('INSERT INTO job_steps (id,job_id,idx,kind,name,output_json,created_at,user_id) VALUES (?,?,?,\'note\',\'dependency_result\',?,?,?)',
                       ('dependency:'+dependency['id'], job['id'], idx, encoded, timestamp, job['user_id']))
            db.execute('UPDATE jobs SET step_count=step_count+1 WHERE id=?', (job['id'],))
            log_audit(db, 'dependency_resolver', 'dependency_resolved', 'job', job['id'], observation)
            db.commit()
            resumed.append(job['id'])
        except BaseException:
            db.rollback()
            raise
    return resumed
