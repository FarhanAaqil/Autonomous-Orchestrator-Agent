import pytest
from fastapi.testclient import TestClient

from orchestrator_core.core import identity
from orchestrator_core.storage.db import get_db_connection


def test_hashes_revocation_and_bootstrap(db):
    user = identity.create_user(db, 'admin', 'strong-test-password-123', 'administrator', bootstrap=True)
    with pytest.raises(ValueError):
        identity.create_user(db, 'second', 'strong-test-password-123', bootstrap=True)
    token = identity.login(db, 'admin', 'strong-test-password-123', '127.0.0.1')
    assert identity.principal(db, token)['id'] == user['id']
    stored = db.execute('SELECT password_hash FROM users').fetchone()[0]
    assert stored.startswith('$argon2id$') and stored != 'strong-test-password-123'
    assert db.execute('SELECT token_hash FROM sessions').fetchone()[0] != token
    identity.logout(db, token)
    assert identity.principal(db, token) is None


def test_login_limit_and_expiration(db):
    identity.create_user(db, 'operator', 'strong-test-password-123')
    for _ in range(5):
        assert identity.login(db, 'operator', 'wrong', '127.0.0.1') is None
    assert identity.login(db, 'operator', 'strong-test-password-123', '127.0.0.1') is None
    db.execute('DELETE FROM login_limits')
    db.commit()
    token = identity.login(db, 'operator', 'strong-test-password-123', '127.0.0.1')
    db.execute("UPDATE sessions SET expires_at='2000-01-01T00:00:00+00:00'")
    db.commit()
    assert identity.principal(db, token) is None


def test_role_change_revokes_sessions(db):
    user = identity.create_user(db, 'operator', 'strong-test-password-123')
    token = identity.login(db, 'operator', 'strong-test-password-123', '127.0.0.1')
    identity.change_access(db, user['id'], 'viewer', True, 'admin')
    assert identity.principal(db, token) is None


def test_browser_csrf_and_role_boundaries(db):
    from orchestrator_core.main import app
    identity.create_user(db, 'viewer', 'strong-test-password-123', 'viewer')
    identity.create_user(db, 'operator', 'strong-test-password-123', 'operator')
    app.dependency_overrides[get_db_connection] = lambda: db
    try:
        client = TestClient(app)
        response = client.post('/auth/login', json={'username': 'viewer', 'password': 'strong-test-password-123'})
        assert response.status_code == 200
        assert 'HttpOnly' in response.headers['set-cookie']
        assert 'SameSite=strict' in response.headers['set-cookie']
        csrf = response.json()['csrf_token']
        assert client.post('/system/kill-switch', json={'on': True}, headers={'x-csrf-token': csrf}).status_code == 403
        assert client.post('/auth/logout').status_code == 403
        # Logout must be allowed for every authenticated role.
        assert client.get('/auth/session').status_code == 200
        changed = client.post('/auth/password', json={'current_password': 'strong-test-password-123', 'new_password': 'different-strong-password-123'}, headers={'x-csrf-token': csrf})
        assert changed.status_code == 200
        response = client.post('/auth/login', json={'username': 'viewer', 'password': 'different-strong-password-123'})
        assert response.status_code == 200
        assert client.post('/auth/logout', headers={'x-csrf-token': response.json()['csrf_token']}).status_code == 200
    finally:
        app.dependency_overrides.clear()
