"""RLS checks use a restricted role, never the migrating superuser."""
import os
import uuid
from contextlib import contextmanager
import pytest
import psycopg
from orchestrator_core.storage.postgres import connect, migrate, verify_runtime_role
from orchestrator_core.core.identity import create_user
from orchestrator_core.core.ownership import execution_owner


@contextmanager
def scope(owner):
    marker = execution_owner.set(owner)
    try:
        yield
    finally:
        execution_owner.reset(marker)


@pytest.fixture
def tenants():
    url = os.environ.get('PHASE2_RLS_DATABASE_URL')
    if not url:
        pytest.skip('Fresh disposable RLS database required')
    migration = connect(url, pooled=False)
    migrate(migration)
    tag = uuid.uuid4().hex
    alice = create_user(migration, 'alice-' + tag, 'fixture-password-123', 'administrator')['id']
    bob = create_user(migration, 'bob-' + tag, 'fixture-password-123')['id']
    role = 'tenant_test_' + tag
    migration.execute('CREATE ROLE ' + role + ' NOLOGIN NOBYPASSRLS')
    migration.execute('GRANT USAGE ON SCHEMA public TO ' + role)
    migration.execute('GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA public TO ' + role)
    migration.execute('GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO ' + role)
    db = connect(url, pooled=False)
    db.execute('SET ROLE ' + role)
    try:
        verify_runtime_role(db)
        yield db, alice, bob
    finally:
        db.close()
        migration.execute('DROP OWNED BY ' + role)
        migration.execute('DROP ROLE ' + role)
        migration.close()


def test_database_denies_cross_account_reads_and_writes(tenants):
    db, alice, bob = tenants
    with scope(alice):
        db.execute("INSERT INTO conversations(id,title,user_id) VALUES (?, 'Private Alice', ?)", ('a-' + alice, alice))
        assert db.execute('SELECT COUNT(*) FROM conversations').fetchone()[0] == 1
    with scope(bob):
        assert db.execute('SELECT COUNT(*) FROM conversations').fetchone()[0] == 0
        assert db.execute('UPDATE conversations SET title=? WHERE id=?', ('Stolen', 'a-' + alice)).rowcount == 0
        assert db.execute('DELETE FROM conversations WHERE id=?', ('a-' + alice,)).rowcount == 0
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            db.execute("INSERT INTO conversations(id,title,user_id) VALUES (?, 'Foreign insert', ?)", ('forged-' + alice, alice))
    # No owner must fail closed, including after reusing a connection.
    assert db.execute('SELECT COUNT(*) FROM conversations').fetchone()[0] == 0
    with pytest.raises((psycopg.errors.NotNullViolation, psycopg.errors.InsufficientPrivilege)):
        db.execute("INSERT INTO conversations(id,title) VALUES (?, 'Unowned')", ('unowned-' + alice,))


def test_admin_can_read_usage_but_not_another_accounts_rows(tenants):
    from orchestrator_core.core.plans import usage_summary
    from orchestrator_core.core.usage import platform_spend
    from datetime import datetime, timezone
    db, alice, bob = tenants
    day = datetime.now(timezone.utc).date().isoformat()
    with scope(bob):
        db.execute("INSERT INTO conversations(id,title,user_id) VALUES (?, 'Private Bob', ?)", ('b-' + bob, bob))
        db.execute("INSERT INTO provider_usage(id,used_at,reserved_tokens,reserved_cost,state,user_id) VALUES (?,?,100,1,'reserved',?)", ('usage-' + bob, day, bob))
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            usage_summary(db, alice)
    with scope(alice):
        assert db.execute('SELECT COUNT(*) FROM conversations WHERE user_id=?', (bob,)).fetchone()[0] == 0
        assert usage_summary(db, bob)['tokens'] == 100
        assert platform_spend(db, day) >= 1


def test_job_events_follow_database_ownership(tenants):
    from orchestrator_core.jobs.service import JobService
    db, alice, bob = tenants
    with scope(alice):
        job = JobService.create_job('general_chat', 'Scoped job', db)
        assert job.user_id == alice
        assert db.execute("SELECT COUNT(*) FROM job_events WHERE data_json::json->>'job_id'=?", (job.id,)).fetchone()[0] > 0
    with scope(bob):
        assert db.execute('SELECT COUNT(*) FROM jobs WHERE id=?', (job.id,)).fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM job_events WHERE data_json::json->>'job_id'=?", (job.id,)).fetchone()[0] == 0
        assert JobService.claim_job('wrong-owner', db, job.id) is None


def test_worker_polls_each_owner_without_bypassing_rls(tenants, monkeypatch):
    from orchestrator_core.jobs.service import JobService
    from orchestrator_core.jobs.worker import Worker
    db, alice, bob = tenants
    with scope(alice):
        first = JobService.create_job('general_chat', 'Alice work', db)
    with scope(bob):
        second = JobService.create_job('general_chat', 'Bob work', db)
    seen = []
    def run(job, db, worker_id, **kwargs):
        assert execution_owner.get() == job.user_id
        seen.append(job.user_id)
        JobService.transition(job.id, 'succeeded', db, worker_id=worker_id)
    from orchestrator_core.jobs.leases import fenced_runner
    monkeypatch.setattr('orchestrator_core.runner.loop.run_job', fenced_runner(run))
    worker = Worker()
    # Earlier tests can leave work in this shared disposable database. Drain only
    # enough cycles to observe both newly created accounts, without provider calls.
    for _ in range(50):
        worker.run_once(db)
        if alice in seen and bob in seen:
            break
    assert alice in seen and bob in seen
    assert execution_owner.get() is None
    with scope(alice):
        assert JobService.get_job(first.id, db).status == 'succeeded'
    with scope(bob):
        assert JobService.get_job(second.id, db).status == 'succeeded'


def test_authenticated_routes_bind_and_clear_database_owner(tenants):
    from fastapi.testclient import TestClient
    from orchestrator_core.main import app
    from orchestrator_core.storage.db import get_db_connection
    db, alice, bob = tenants
    names = {row['id']: row['username'] for row in db.execute('SELECT id,username FROM users WHERE id IN (?,?)', (alice, bob)).fetchall()}
    app.dependency_overrides[get_db_connection] = lambda: db
    try:
        client_a, client_b = TestClient(app), TestClient(app)
        auth = client_a.post('/auth/login', json={'username': names[alice], 'password': 'fixture-password-123'})
        assert auth.status_code == 200
        assert client_b.post('/auth/login', json={'username': names[bob], 'password': 'fixture-password-123'}).status_code == 200
        created = client_a.post('/conversations', json={'title': 'Private browser thread'}, headers={'x-csrf-token': auth.json()['csrf_token']})
        assert created.status_code in (200, 201)
        conversation = created.json()['id']
        assert client_b.get('/conversations/' + conversation + '/messages').status_code == 404
        assert client_a.get('/conversations/' + conversation + '/messages').status_code == 200
        assert client_a.get('/account').status_code == 200
        assert client_a.get('/account/export').status_code == 200
        assert db.execute('SELECT COUNT(*) FROM conversations').fetchone()[0] == 0
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def legacy_database():
    from psycopg import sql
    from psycopg.conninfo import make_conninfo
    from unittest.mock import patch
    url = os.environ.get('PHASE2_RLS_DATABASE_URL')
    if not url:
        pytest.skip('Disposable PostgreSQL database required')
    name = 'pytest_rls_' + uuid.uuid4().hex
    control = psycopg.connect(url, autocommit=True)
    control.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
    db = connect(make_conninfo(url, dbname=name), pooled=False)
    try:
        # Reconstruct the released pre-RLS schema without changing real data.
        with patch('orchestrator_core.storage.tenant_schema.install'):
            migrate(db)
        db.execute('DELETE FROM application_migrations WHERE version=17')
        yield db
    finally:
        db.close()
        assert name.startswith('pytest_rls_') and len(name) == 43
        control.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(name)))
        control.close()


def test_legacy_backfill_assigns_first_admin_and_repeats(legacy_database):
    db = legacy_database
    owner = create_user(db, 'first-admin', 'fixture-password-123', 'administrator')['id']
    db.execute("INSERT INTO conversations(id,title) VALUES ('legacy', 'Existing data')")
    migrate(db)
    migrate(db)
    assert db.execute("SELECT user_id FROM conversations WHERE id='legacy'").fetchone()[0] == owner
    assert db.execute("SELECT attnotnull FROM pg_attribute WHERE attrelid='conversations'::regclass AND attname='user_id'").fetchone()[0]


def test_missing_admin_rolls_back_rls_migration(legacy_database):
    db = legacy_database
    db.execute("INSERT INTO conversations(id,title) VALUES ('legacy', 'Preserve me')")
    with pytest.raises(RuntimeError, match='first administrator'):
        migrate(db)
    assert db.execute('SELECT 1 FROM application_migrations WHERE version=17').fetchone() is None
    row = db.execute("SELECT title,user_id FROM conversations WHERE id='legacy'").fetchone()
    assert row['title'] == 'Preserve me' and row['user_id'] is None
    assert not db.execute("SELECT relrowsecurity FROM pg_class WHERE oid='conversations'::regclass").fetchone()[0]
