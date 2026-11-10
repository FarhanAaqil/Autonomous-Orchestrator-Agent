"""Focused integration checks against a disposable PostgreSQL database only."""
import os
import pytest

from orchestrator_core.storage.postgres import connect, migrate, parameters


@pytest.fixture
def pg():
    url = os.environ.get('PHASE2_TEST_DATABASE_URL')
    if not url:
        pytest.skip('Set PHASE2_TEST_DATABASE_URL to a disposable PostgreSQL database')
    conn = connect(url, pooled=False)
    migrate(conn)
    yield conn
    conn.close()


def test_parameters_preserve_literals():
    assert parameters("SELECT '?' AS x, ? AS y, '50%' AS z") == "SELECT '?' AS x, %s AS y, '50%%' AS z"


def test_migrations_repeat_and_transactions_rollback(pg):
    migrate(pg)
    with pytest.raises(RuntimeError):
        with pg:
            pg.execute("INSERT INTO system_flags (key,value) VALUES ('rollback_probe','yes')")
            raise RuntimeError('rollback')
    assert pg.execute("SELECT value FROM system_flags WHERE key='rollback_probe'").fetchone() is None
    assert pg.execute('SELECT COUNT(*) FROM schema_versions').fetchone()[0] == 1


def test_approval_consent_survives_postgres(pg):
    from orchestrator_core.core.approval_gate import request_approval, approve, reject
    from orchestrator_core.exceptions import ApprovalNotGrantedError
    approval = request_approval('send_email', {'to': 'test@example.com', 'subject': 'Test', 'body': 'Test'}, pg)
    row = pg.execute('SELECT * FROM approvals WHERE id=?', (approval,)).fetchone()
    approve(approval, pg, expected_hash=row['payload_hash'])
    with pytest.raises(ApprovalNotGrantedError):
        reject(approval, pg)
    assert pg.execute('SELECT status FROM approvals WHERE id=?', (approval,)).fetchone()[0] == 'approved'


def test_job_creation_and_claim(pg):
    from orchestrator_core.jobs.service import JobService
    job = JobService.create_job('general_chat', 'Test database claim', pg)
    claimed = JobService.claim_job('test-worker', pg, job.id)
    assert claimed.id == job.id
    assert JobService.claim_job('other-worker', pg, job.id) is None


def race(operation):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    barrier = Barrier(2)
    def run(index):
        db = connect(os.environ['PHASE2_TEST_DATABASE_URL'], pooled=False)
        try:
            barrier.wait(timeout=5)
            return operation(db, index)
        finally:
            db.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        return list(pool.map(run, range(2)))


def test_two_connections_cannot_claim_the_same_job(pg):
    from orchestrator_core.jobs.service import JobService
    job = JobService.create_job('general_chat', 'Concurrent claims', pg)
    results = race(lambda db, index: JobService.claim_job(f'worker-{index}', db, job.id))
    assert sum(result is not None for result in results) == 1


def test_two_schedulers_commit_one_occurrence(pg, monkeypatch):
    import uuid
    from datetime import datetime, timezone
    from orchestrator_core.core.scheduler import tick
    from orchestrator_core.memory import context
    monkeypatch.setattr(context, 'synchronize_vectors', lambda _: None)
    schedule = str(uuid.uuid4())
    with pg:
        pg.execute("INSERT INTO schedules(id,name,agent,goal,cron_expr,next_run_at) VALUES (?, 'Race','general_chat','Test','0 8 * * *','2026-01-01T08:00:00+00:00')", (schedule,))
    try:
        results = race(lambda db, _: tick(db, datetime(2026, 1, 2, 9, tzinfo=timezone.utc)))
        assert sum(len(result) for result in results) == 1
        assert pg.execute('SELECT COUNT(*) FROM schedule_occurrences WHERE schedule_id=?', (schedule,)).fetchone()[0] == 1
    finally:
        with pg:
            pg.execute('UPDATE schedules SET is_active=0 WHERE id=?', (schedule,))


def test_saved_dependency_resumes_after_connection_restart(pg):
    from orchestrator_core.jobs.service import JobService
    from orchestrator_core.jobs.dependencies import reconcile
    from orchestrator_core.runner.loop import run_job
    job = JobService.create_job('email_agent', 'Durable review', pg)
    run_job(job, pg, llm_client=lambda _: '{"action":"propose","action_input":{"action_type":"send_email","payload":{"to":"test@example.com","subject":"Test","body":"Test"}}}')
    approval = pg.execute('SELECT target_id FROM job_dependencies WHERE job_id=?', (job.id,)).fetchone()[0]
    restarted = connect(os.environ['PHASE2_TEST_DATABASE_URL'], pooled=False)
    try:
        with restarted:
            restarted.execute("UPDATE approvals SET status='confirmed' WHERE id=?", (approval,))
        assert job.id in reconcile(restarted)
        assert job.id not in reconcile(restarted)
        assert JobService.get_job(job.id, restarted).status == 'queued'
    finally:
        restarted.close()
