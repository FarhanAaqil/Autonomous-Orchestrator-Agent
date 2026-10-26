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
    claimed = JobService.claim_job('test-worker', pg)
    assert claimed.id == job.id
    assert JobService.claim_job('other-worker', pg) is None
