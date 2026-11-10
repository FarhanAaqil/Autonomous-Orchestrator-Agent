import pytest
from orchestrator_core.jobs.service import JobService
from orchestrator_core.jobs.leases import current_lease
from orchestrator_core.jobs.reaper import reap_zombies
from orchestrator_core.exceptions import JobClaimConflictError
from orchestrator_core.core.approval_gate import request_approval


def test_reclaimed_generation_rejects_old_worker_writes(db):
    original = JobService.create_job('general_chat', 'Fence writes', db)
    old = JobService.claim_job('same-worker-name', db)
    db.execute("UPDATE jobs SET lease_expires_at='2000-01-01' WHERE id=?", (old.id,))
    db.commit()
    assert reap_zombies(db) == [old.id]
    db.execute('UPDATE jobs SET not_before=NULL WHERE id=?', (old.id,))
    db.commit()
    new = JobService.claim_job('same-worker-name', db)
    assert new.lease_generation > old.lease_generation
    marker = current_lease.set((old.id, old.claimed_by, old.lease_generation))
    try:
        assert not JobService.heartbeat(old.id, old.claimed_by, db)
        with pytest.raises(JobClaimConflictError):
            JobService.record_step(old.id, 0, 'note', db)
        with pytest.raises(JobClaimConflictError):
            JobService.transition(old.id, 'succeeded', db)
        with pytest.raises(JobClaimConflictError):
            request_approval('send_email', {'to': 'test@example.com', 'subject': 'Test', 'body': 'Test'}, db)
    finally:
        current_lease.reset(marker)
    assert not JobService.get_steps(original.id, db)
    assert db.execute('SELECT COUNT(*) FROM approvals').fetchone()[0] == 0


def test_cancellation_defeats_current_worker(db):
    JobService.create_job('general_chat', 'Cancel work', db)
    job = JobService.claim_job('worker', db)
    JobService.cancel_job(job.id, db)
    marker = current_lease.set((job.id, 'worker', job.lease_generation))
    try:
        with pytest.raises(JobClaimConflictError):
            JobService.record_step(job.id, 0, 'note', db)
    finally:
        current_lease.reset(marker)


def test_runner_claims_and_completes_with_lease(db):
    from orchestrator_core.runner.loop import run_job
    job = JobService.create_job('general_chat', 'Complete fake work', db)
    result = run_job(job, db, llm_client=lambda _: '{"action":"final","action_input":{"summary":"done"}}')
    assert result.status == 'succeeded'
