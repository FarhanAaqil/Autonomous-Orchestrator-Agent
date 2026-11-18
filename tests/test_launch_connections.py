import json
import pytest
from cryptography.fernet import Fernet
from orchestrator_core.core.identity import create_user
from orchestrator_core.core.connections import store_connection, load_connection, list_connections, disconnect, ConnectionUnavailable
from orchestrator_core.core.plans import grant_plan, account_plan


@pytest.fixture
def owners(db, monkeypatch):
    monkeypatch.setenv('CONNECTION_KEYS', json.dumps({'one': Fernet.generate_key().decode(), 'two': Fernet.generate_key().decode()}))
    monkeypatch.setenv('CONNECTION_ACTIVE_KEY', 'one')
    return [create_user(db, name, 'fixture-password-123', role)['id'] for name, role in [('admin','administrator'),('alice','operator'),('bob','operator')]]


def test_secrets_are_owner_bound_and_never_listed(db, owners):
    _, alice, bob = owners
    store_connection(db, alice, 'github', {'token': 'fixture-secret'}, ['repo'])
    assert 'fixture-secret' not in str(list_connections(db, alice))
    assert 'fixture-secret' not in db.execute('SELECT credentials FROM connections').fetchone()[0]
    with pytest.raises(ConnectionUnavailable):
        load_connection(db, bob, 'github')
    assert load_connection(db, alice, 'github')['token'] == 'fixture-secret'
    disconnect(db, bob, 'github')
    assert load_connection(db, alice, 'github')
    disconnect(db, alice, 'github')
    with pytest.raises(ConnectionUnavailable):
        load_connection(db, alice, 'github')


def test_ciphertext_swaps_and_missing_scopes_are_rejected(db, owners):
    _, alice, bob = owners
    store_connection(db, alice, 'github', {'token': 'alice-secret'}, ['read:user'])
    with pytest.raises(ConnectionUnavailable):
        load_connection(db, alice, 'github', ['repo'])
    db.execute('UPDATE connections SET user_id=? WHERE user_id=?', (bob,alice))
    db.commit()
    with pytest.raises(ConnectionUnavailable):
        load_connection(db, bob, 'github')


def test_old_encryption_key_rotates_on_use(db, owners, monkeypatch):
    _, alice, _ = owners
    store_connection(db, alice, 'groq', {'token': 'fixture-secret'}, [])
    monkeypatch.setenv('CONNECTION_ACTIVE_KEY', 'two')
    assert load_connection(db, alice, 'groq')['token'] == 'fixture-secret'
    assert db.execute('SELECT key_id FROM connections').fetchone()[0] == 'two'


def test_plan_grants_require_admin_and_expire_without_scheduler(db, owners):
    admin, alice, bob = owners
    assert account_plan(db, alice)['plan'] == 'free'
    with pytest.raises(PermissionError):
        grant_plan(db, bob, alice, 'pro', '2099-01-01T00:00:00+00:00')
    grant_plan(db, admin, alice, 'pro', '2099-01-01T00:00:00+00:00')
    assert account_plan(db, alice)['plan'] == 'pro'
    db.execute("UPDATE users SET paid_until='2000-01-01T00:00:00+00:00' WHERE id=?", (alice,))
    db.commit()
    assert account_plan(db, alice)['plan'] == 'free'
    assert account_plan(db, alice)['expired']
