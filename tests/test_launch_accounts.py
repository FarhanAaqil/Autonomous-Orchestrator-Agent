import pytest
from fastapi.testclient import TestClient
from orchestrator_core.core import identity
from orchestrator_core.core.account_recovery import issue_token, consume_token
from orchestrator_core.main import app
from orchestrator_core.storage.db import get_db_connection
from orchestrator_core.config import get_settings


@pytest.fixture
def accounts(db, monkeypatch):
    monkeypatch.setenv('PUBLIC_REGISTRATION', 'true')
    get_settings.cache_clear()
    app.dependency_overrides[get_db_connection] = lambda: db
    links = []
    monkeypatch.setattr('orchestrator_core.core.mailer.send_account_link', lambda *args: links.append(args))
    yield TestClient(app), links
    app.dependency_overrides.clear()
    get_settings.cache_clear()


def test_registration_verification_and_reset(accounts, db):
    client, links = accounts
    payload = {'email': 'Person@Example.com', 'password': 'fixture-strong-password'}
    first = client.post('/auth/register', json=payload)
    second = client.post('/auth/register', json=payload)
    assert first.status_code == 202 and first.json() == second.json()
    assert db.execute('SELECT COUNT(*) FROM users').fetchone()[0] == 1
    assert client.post('/auth/login', json={'username': 'person@example.com', 'password': payload['password']}).status_code == 401
    old_token, token = links[0][2], links[-1][2]
    assert client.post('/auth/verify', json={'token': old_token}).status_code == 400
    assert client.post('/auth/verify', json={'token': token}).status_code == 200
    assert client.post('/auth/verify', json={'token': token}).status_code == 400
    login = client.post('/auth/login', json={'username': payload['email'], 'password': payload['password']})
    assert login.status_code == 200 and login.json()['user']['role'] == 'operator'
    assert client.post('/auth/password/reset/request', json={'email': payload['email']}).status_code == 202
    reset = links[-1][2]
    assert reset not in str([dict(row) for row in db.execute('SELECT * FROM account_tokens')])
    assert client.post('/auth/password/reset/confirm', json={'token': reset, 'password': 'replacement-password-123'}).status_code == 200
    assert client.get('/auth/session').status_code == 401
    assert client.post('/auth/password/reset/confirm', json={'token': reset, 'password': 'replacement-password-123'}).status_code == 400


def test_expired_and_wrong_purpose_tokens_fail(db):
    user = identity.create_user(db, 'a@example.com', 'fixture-strong-password')
    token = issue_token(db, user['id'], 'verify')
    with pytest.raises(ValueError):
        consume_token(db, token, 'reset', 'replacement-password-123')
    db.execute("UPDATE account_tokens SET expires_at='2000-01-01'")
    db.commit()
    with pytest.raises(ValueError):
        consume_token(db, token, 'verify')


def test_public_auth_origin_and_limits(accounts):
    client, _ = accounts
    payload = {'email': 'absent@example.com'}
    assert client.post('/auth/password/reset/request', json=payload, headers={'Origin': 'https://attacker.invalid'}).status_code == 403
    for _ in range(5):
        assert client.post('/auth/password/reset/request', json=payload).status_code == 202
    assert client.post('/auth/password/reset/request', json=payload).status_code == 429


def test_signup_disabled_by_default(db):
    app.dependency_overrides[get_db_connection] = lambda: db
    try:
        assert TestClient(app).post('/auth/register', json={'email': 'a@example.com', 'password': 'fixture-strong-password'}).status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_local_recovery_invalidates_pending_email_resets(db):
    from orchestrator_core.reset_password import reset_password
    user = identity.create_user(db, 'admin', 'fixture-strong-password', 'administrator')
    token = issue_token(db, user['id'], 'reset')
    reset_password(db, 'admin', 'replacement-password-123')
    with pytest.raises(ValueError):
        consume_token(db, token, 'reset', 'attacker-replacement-123')
