"""Worker fencing tokens propagated through runner and proposal calls."""
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from functools import wraps
import inspect
import threading

from orchestrator_core.exceptions import JobClaimConflictError

current_lease = ContextVar('current_lease', default=None)
LEASE_SECONDS = 60


def expires():
    return (datetime.now(timezone.utc) + timedelta(seconds=LEASE_SECONDS)).isoformat()


def require_lease(db, job_id=None):
    lease = current_lease.get()
    if lease is None or (job_id and job_id != lease[0]):
        raise JobClaimConflictError(job_id or 'missing lease')
    job_id, worker, generation = lease
    cur = db.execute('UPDATE jobs SET lease_generation=lease_generation WHERE id=? AND claimed_by=? '
                     "AND lease_generation=? AND status='running' AND lease_expires_at>?",
                     (job_id, worker, generation, datetime.now(timezone.utc).isoformat()))
    if cur.rowcount != 1:
        raise JobClaimConflictError(job_id)


def fenced_runner(fn):
    @wraps(fn)
    def run(*args, **kwargs):
        from orchestrator_core.jobs.service import JobService
        bound = inspect.signature(fn).bind(*args, **kwargs)
        bound.apply_defaults()
        job, db, worker = bound.arguments['job'], bound.arguments['db'], bound.arguments['worker_id']
        if job.status == 'queued':
            job = JobService.claim_job(worker, db, job_id=job.id)
            if job is None:
                raise JobClaimConflictError(bound.arguments['job'].id)
            bound.arguments['job'] = job
        marker = current_lease.set((job.id, worker, job.lease_generation))
        from orchestrator_core.core.usage import usage_db
        usage_marker = usage_db.set(db)
        try:
            with db:
                require_lease(db, job.id)
            try:
                return fn(*bound.args, **bound.kwargs)
            except JobClaimConflictError:
                return JobService.get_job(job.id, db)
            except Exception as exc:
                from orchestrator_core.exceptions import JobError
                if not isinstance(exc, JobError):
                    raise
                return JobService.transition(job.id, 'failed', db, error=str(exc), worker_id=worker)
        finally:
            usage_db.reset(usage_marker)
            current_lease.reset(marker)
    return run
