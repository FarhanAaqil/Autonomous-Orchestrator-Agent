"""Persistent pipeline and evaluation jobs processed by supervised workers."""
import json

from orchestrator_core.jobs.service import JobService
from orchestrator_core.jobs.leases import fenced_runner, require_lease
from orchestrator_core.storage.transactions import transaction


def enqueue(db, kind, payload):
    if kind not in ('pipeline', 'evaluation'):
        raise ValueError('Unsupported background work')
    agent = {'research': 'research_agent', 'apply': 'career_agent', 'publish': 'growth_content_agent'}.get(payload.get('name'), 'general_chat')
    with transaction(db):
        job = JobService.create_job(agent, payload.get('command') or 'Evaluate router', db)
        db.execute('UPDATE jobs SET work_kind=?,work_payload_json=? WHERE id=?', (kind, json.dumps(payload), job.id))
    return job.id


@fenced_runner
def run_background_job(job, db, worker_id='worker-1', **unused):
    from orchestrator_core.models import PipelineRequest
    if job.result_json:
        return JobService.transition(job.id, 'succeeded', db, worker_id=worker_id)
    payload = json.loads(job.work_payload_json)
    try:
        if job.work_kind == 'pipeline':
            from orchestrator_core.core.pipeline_engine import run_pipeline
            result = {'run_id': run_pipeline(payload['name'], PipelineRequest(command=payload['command']), db)}
        elif job.work_kind == 'evaluation':
            from orchestrator_core.routes.router_eval import evaluate
            result = evaluate(job.id, db)
        else:
            raise ValueError('Unknown background work kind')
        with transaction(db):
            require_lease(db, job.id)
        pending = db.execute('SELECT 1 FROM job_dependencies WHERE job_id=? AND resolved=0', (job.id,)).fetchone()
        return JobService.transition(job.id, 'awaiting_approval' if pending else 'succeeded', db,
                                     result_json=json.dumps(result), worker_id=worker_id)
    except Exception as exc:
        from orchestrator_core.exceptions import JobClaimConflictError
        if isinstance(exc, JobClaimConflictError):
            raise
        return JobService.transition(job.id, 'failed', db, error=str(exc), worker_id=worker_id)
