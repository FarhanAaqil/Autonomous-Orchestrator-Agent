import pytest
from orchestrator_core.core.identity import create_user
from orchestrator_core.core.plans import PLANS, PlanLimitExceeded
from orchestrator_core.jobs.service import JobService


def test_daily_admission_limit_is_per_account_and_counts_failed_work(db, monkeypatch):
    monkeypatch.setitem(PLANS, 'free', {**PLANS['free'], 'runs_per_day': 1})
    alice = create_user(db, 'alice', 'fixture-password-123')['id']
    bob = create_user(db, 'bob', 'fixture-password-123')['id']
    job = JobService.create_job('general_chat', 'First', db, owner=alice)
    JobService.cancel_job(job.id, db)
    with pytest.raises(PlanLimitExceeded):
        JobService.create_job('general_chat', 'Over limit', db, owner=alice)
    assert JobService.create_job('general_chat', 'Other account', db, owner=bob).user_id == bob


def test_worker_skips_accounts_at_concurrency_limit(db):
    alice = create_user(db, 'alice', 'fixture-password-123')['id']
    bob = create_user(db, 'bob', 'fixture-password-123')['id']
    first = JobService.create_job('general_chat', 'First', db, owner=alice)
    second = JobService.create_job('general_chat', 'Second', db, owner=alice)
    third = JobService.create_job('general_chat', 'Third', db, owner=bob)
    assert JobService.claim_job('a', db, first.id).id == first.id
    assert JobService.claim_job('b', db, second.id) is None
    assert JobService.claim_job('b', db).id == third.id


def test_token_reservations_enforce_daily_account_budget(db, monkeypatch):
    from orchestrator_core.core.policy import execution_scope
    from orchestrator_core.core.usage import reserve
    alice = create_user(db, 'alice', 'fixture-password-123')['id']
    monkeypatch.setitem(PLANS, 'free', {**PLANS['free'], 'daily_tokens': 400})
    with execution_scope('orchestrator', owner=alice):
        reservation, _ = reserve(db, [], 100)
        with pytest.raises(PlanLimitExceeded):
            reserve(db, [], 100)
    assert db.execute('SELECT user_id FROM provider_usage WHERE id=?', (reservation,)).fetchone()['user_id'] == alice
    assert db.execute('SELECT COUNT(*) FROM provider_usage').fetchone()[0] == 1


def test_account_api_hides_private_fields_and_rejects_self_upgrade(db):
    from fastapi.testclient import TestClient
    from orchestrator_core.main import app
    from orchestrator_core.storage.db import get_db_connection
    owner = create_user(db, 'alice', 'fixture-password-123')['id']
    app.dependency_overrides[get_db_connection] = lambda: db
    try:
        client = TestClient(app)
        csrf = client.post('/auth/login', json={'username': 'alice', 'password': 'fixture-password-123'}).json()['csrf_token']
        response = client.get('/account')
        assert response.status_code == 200
        assert response.json()['plan'] == 'free'
        assert response.json()['usage']['runs'] == 0
        assert 'password_hash' not in response.text
        assert client.put('/account/users/' + owner + '/plan', json={'plan': 'pro', 'paid_until': '2099-01-01T00:00:00+00:00'}, headers={'x-csrf-token': csrf}).status_code == 403
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize('personal_key', [False, True])
def test_monthly_limit_includes_prior_days_and_personal_keys(db, monkeypatch, personal_key):
    from orchestrator_core.core.policy import execution_scope
    from orchestrator_core.core.usage import reserve
    from datetime import datetime, timezone
    owner = create_user(db, 'alice', 'fixture-password-123')['id']
    monkeypatch.setitem(PLANS, 'free', {**PLANS['free'], 'monthly_tokens': 400})
    with execution_scope('orchestrator', owner=owner):
        reservation, _ = reserve(db, [], 100, personal_key=personal_key)
        month = datetime.now(timezone.utc).strftime('%Y-%m')
        with db:
            db.execute('UPDATE provider_usage SET used_at=? WHERE id=?', (month + '-01T00:00:00+00:00', reservation))
        with pytest.raises(PlanLimitExceeded, match='monthly tokens'):
            reserve(db, [], 100, personal_key=personal_key)
    assert db.execute('SELECT COUNT(*) FROM provider_usage').fetchone()[0] == 1


def test_public_payment_link_requires_https(monkeypatch):
    from orchestrator_core.routes.auth import public_plans
    for value in ('javascript:alert(1)', 'http://example.org/pay', 'https://user:secret@example.org/pay'):
        monkeypatch.setenv('UPGRADE_PAYMENT_URL', value)
        assert public_plans()['payment_url'] is None
    monkeypatch.setenv('UPGRADE_PAYMENT_URL', 'https://payments.example.org/upgrade')
    assert public_plans()['payment_url'] == 'https://payments.example.org/upgrade'
